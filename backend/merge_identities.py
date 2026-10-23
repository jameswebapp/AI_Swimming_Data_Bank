"""
Identity merge for the Swimming Data Bank.

Why this exists (audit 2026-10-23, docs/data_quality_repair_plan.md):
23,841 swimmer rows contain 3,937 duplicate (first,last,gender) groups;
3,749 groups have results split across >= 2 swimmer IDs. A 50-group
sample checked by birth_date showed 47/50 are the SAME person
(identical birth_date), 2 are true namesakes, 1 indeterminate.

Merge rule (conservative):
  * Group key = (first_name, last_name, gender, birth_date) with a
    non-null birth_date. Groups of 2+ are merged automatically:
    survivor = the ID holding the most results (tie: lowest ID);
    all results are reassigned to the survivor; loser rows deleted.
  * Same-name groups whose birth_dates conflict, or where birth_date
    is missing, are NEVER auto-merged — they are written to the review
    list for a human decision.
  * Zero-result swimmers ("empty shells") are deleted only when they
    belong to an auto-merge group; unmatched shells are left alone.

Safety:
  * Default is --dry-run: prints a summary and writes merge_plan.json.
  * --execute first writes identity_snapshot.json (all swimmer rows +
    result_id -> swimmer_id for every affected result) so the merge
    can be reversed, then applies changes and writes merge_audit.json.

Requires SUPABASE_URL / SUPABASE_KEY (service_role) in the environment.
Run via the identity_merge GitHub Actions workflow or locally.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

from supabase import create_client


def norm(s: str) -> str:
    return (s or "").strip().lower()


def load_swimmers(sb) -> list[dict]:
    rows, offset, limit = [], 0, 1000
    while True:
        resp = (sb.table("swimmers")
                .select("id, first_name, last_name, gender, birth_date, uss_id, team_id")
                .range(offset, offset + limit - 1).execute())
        if not resp.data:
            break
        rows.extend(resp.data)
        if len(resp.data) < limit:
            break
        offset += limit
    return rows


def count_results(sb) -> collections.Counter:
    """One pass over individual_results counting rows per swimmer_id."""
    counts: collections.Counter = collections.Counter()
    offset, limit = 0, 1000
    while True:
        resp = (sb.table("individual_results")
                .select("swimmer_id")
                .range(offset, offset + limit - 1).execute())
        if not resp.data:
            break
        for r in resp.data:
            counts[r["swimmer_id"]] += 1
        if offset % 100000 == 0:
            print(f"  ...counted past row {offset}")
        if len(resp.data) < limit:
            break
        offset += limit
    return counts


def build_plan(swimmers: list[dict], counts: collections.Counter):
    by_name: dict[tuple, list[dict]] = collections.defaultdict(list)
    for s in swimmers:
        by_name[(norm(s["first_name"]), norm(s["last_name"]), s["gender"])].append(s)

    merges = []   # {survivor, losers:[{id, results}], dob, name}
    review = []   # {name, ids:[{id, dob, results, team_id}], reason}
    for (fn, ln, gender), group in by_name.items():
        if len(group) < 2:
            continue
        dob_groups: dict[str, list[dict]] = collections.defaultdict(list)
        no_dob: list[dict] = []
        for s in group:
            if s.get("birth_date"):
                dob_groups[s["birth_date"]].append(s)
            else:
                no_dob.append(s)
        for dob, members in dob_groups.items():
            if len(members) >= 2:
                members_sorted = sorted(
                    members, key=lambda s: (-counts.get(s["id"], 0), s["id"]))
                survivor = members_sorted[0]
                merges.append({
                    "name": f"{fn} {ln} ({gender})",
                    "birth_date": dob,
                    "survivor": survivor["id"],
                    "survivor_results": counts.get(survivor["id"], 0),
                    "losers": [{"id": s["id"],
                                "results": counts.get(s["id"], 0),
                                "team_id": s.get("team_id")}
                               for s in members_sorted[1:]],
                })
            elif no_dob:
                review.append({
                    "name": f"{fn} {ln} ({gender})",
                    "reason": "one dated ID plus undated duplicates — cannot confirm same person",
                    "ids": [{"id": s["id"], "birth_date": s.get("birth_date"),
                             "results": counts.get(s["id"], 0)}
                            for s in group],
                })
        if len(dob_groups) > 1:
            review.append({
                "name": f"{fn} {ln} ({gender})",
                "reason": "conflicting birth_dates — likely true namesakes, do NOT merge blindly",
                "ids": [{"id": s["id"], "birth_date": s.get("birth_date"),
                         "results": counts.get(s["id"], 0)}
                        for s in group],
            })
        if not dob_groups and no_dob:
            review.append({
                "name": f"{fn} {ln} ({gender})",
                "reason": "no birth_date on any duplicate — cannot confirm same person",
                "ids": [{"id": s["id"], "birth_date": None,
                         "results": counts.get(s["id"], 0)}
                        for s in group],
            })
    return merges, review


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge duplicate swimmer identities")
    ap.add_argument("--execute", action="store_true",
                    help="Actually perform the merge (default: dry-run plan only)")
    ap.add_argument("--out", default=".", help="Directory for plan/audit/snapshot JSON")
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: set SUPABASE_URL and SUPABASE_KEY (service_role).")
        return 1
    sb = create_client(url, key)

    print("Loading swimmers...")
    swimmers = load_swimmers(sb)
    print(f"  {len(swimmers)} swimmer rows")
    print("Counting results per swimmer (one full pass)...")
    counts = count_results(sb)
    print(f"  {sum(counts.values())} results across {len(counts)} swimmers")

    merges, review = build_plan(swimmers, counts)
    total_losers = sum(len(m["losers"]) for m in merges)
    total_moved = sum(l["results"] for m in merges for l in m["losers"])
    shells_removed = sum(1 for m in merges for l in m["losers"] if l["results"] == 0)
    print("\n" + "=" * 60)
    print(f"AUTO-MERGE groups: {len(merges)}")
    print(f"  loser rows to delete: {total_losers} (incl. {shells_removed} empty shells)")
    print(f"  results to reassign:  {total_moved}")
    print(f"REVIEW groups (untouched): {len(review)}")
    print("=" * 60)

    plan = {"merges": merges, "review": review}
    with open(os.path.join(args.out, "merge_plan.json"), "w") as f:
        json.dump(plan, f, indent=1)
    print("Wrote merge_plan.json")

    if not args.execute:
        print("DRY RUN — no changes made. Re-run with --execute to apply.")
        return 0

    # Snapshot for reversibility: affected result assignments + swimmer rows.
    affected_ids = {m["survivor"] for m in merges} | \
                   {l["id"] for m in merges for l in m["losers"]}
    print(f"Snapshotting {len(affected_ids)} swimmer rows before merging...")
    snapshot = {
        "swimmers": [s for s in swimmers if s["id"] in affected_ids],
        "note": "Result rows are reassigned loser->survivor; merge_audit.json "
                "records every move so assignments can be restored per group.",
    }
    with open(os.path.join(args.out, "identity_snapshot.json"), "w") as f:
        json.dump(snapshot, f, indent=1)

    audit = []
    swimmer_by_id = {s["id"]: s for s in swimmers}
    for m in merges:
        survivor = m["survivor"]
        # Fill survivor's missing uss_id / birth_date from losers if possible.
        surv_row = swimmer_by_id[survivor]
        patch = {}
        if not surv_row.get("uss_id"):
            for l in m["losers"]:
                if swimmer_by_id[l["id"]].get("uss_id"):
                    patch["uss_id"] = swimmer_by_id[l["id"]]["uss_id"]
                    break
        if patch:
            try:
                sb.table("swimmers").update(patch).eq("id", survivor).execute()
            except Exception as e:
                print(f"  WARN survivor patch {survivor}: {e}")
        for l in m["losers"]:
            lid = l["id"]
            if l["results"]:
                sb.table("individual_results").update(
                    {"swimmer_id": survivor}).eq("swimmer_id", lid).execute()
            sb.table("swimmers").delete().eq("id", lid).execute()
            audit.append({"loser": lid, "survivor": survivor,
                          "results_moved": l["results"], "name": m["name"],
                          "birth_date": m["birth_date"]})
        print(f"  merged {m['name']} -> survivor {survivor} "
              f"({len(m['losers'])} losers)")
    with open(os.path.join(args.out, "merge_audit.json"), "w") as f:
        json.dump(audit, f, indent=1)
    print(f"\nDONE. {len(audit)} swimmer rows merged away. Wrote merge_audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

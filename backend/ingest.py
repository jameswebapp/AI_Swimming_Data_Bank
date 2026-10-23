from __future__ import annotations

"""
Data ingestion script: loads parsed JSON into Supabase PostgreSQL.

Usage:
    1. Create a Supabase project at supabase.com
    2. Run schema.sql in the SQL Editor
    3. Set environment variables:
       export SUPABASE_URL=https://xxxxx.supabase.co
       export SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...  (service_role key for writes)
    4. Run: python -m backend.ingest
"""
import json
import os
import sys
from collections import defaultdict
from typing import Optional, Dict, List

from dotenv import load_dotenv

# Try importing supabase; provide install instructions if missing
try:
    from supabase import create_client, Client
except ImportError:
    print("Install supabase-py: pip install supabase")
    sys.exit(1)

# Load environment variables from .env file
load_dotenv()

# Paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARSED_DIR = os.path.join(PROJECT_ROOT, "data", "parsed")
DEFAULT_DATA_FILE = os.path.join(PARSED_DIR, "all_meets_2023_2024.json")


def get_supabase_client() -> Client:
    """Create Supabase client from environment variables."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY environment variables.")
        print("  SUPABASE_URL = your project URL (https://xxx.supabase.co)")
        print("  SUPABASE_KEY = service_role key (from Settings > API)")
        sys.exit(1)
    return create_client(url, key)


def derive_age_group(age: Optional[int]) -> Optional[str]:
    """Convert age to standard USA Swimming age group."""
    if age is None:
        return None
    if age <= 8:
        return "8U"
    elif age <= 10:
        return "9-10"
    elif age <= 12:
        return "11-12"
    elif age <= 14:
        return "13-14"
    elif age <= 16:
        return "15-16"
    elif age <= 18:
        return "17-18"
    else:
        return "Senior"


def build_event_code(distance: int, stroke: str) -> str:
    """Build event code from distance and stroke name."""
    stroke_abbr = {
        "Freestyle": "FR", "Backstroke": "BK", "Breaststroke": "BR",
        "Butterfly": "FL", "IM": "IM",
        "Medley Relay": "MR", "Free Relay": "FRR",
    }
    abbr = stroke_abbr.get(stroke, stroke[:2].upper())
    return f"{distance}{abbr}"


def ingest_data(data_file: str = DEFAULT_DATA_FILE, batch_size: int = 500, season: Optional[str] = None):
    """
    Main ingestion pipeline:
    1. Load parsed JSON
    2. Insert meets
    3. Insert teams (dedup by code)
    4. Insert swimmers (dedup by USS ID)
    5. Insert individual results
    6. Refresh materialized views
    """
    print("=" * 60)
    print("Swimming Data Ingestion → Supabase")
    print("=" * 60)

    # Determine default season override if explicitly passed
    if season:
        print(f"  Target Season (Override): {season}")
    else:
        print(f"  Target Season: Dynamic (derived from meet start date)")

    # Load data
    print(f"\nLoading {data_file}...")
    with open(data_file, "r", encoding="utf-8") as f:
        all_meets = json.load(f)
    print(f"  Loaded {len(all_meets)} meets")

    # Connect to Supabase
    sb = get_supabase_client()
    print(f"  Connected to Supabase")

    # Load existing events map (event_code -> id)
    events_resp = sb.table("events").select("id, event_code").execute()
    event_map = {e["event_code"]: e["id"] for e in events_resp.data}
    print(f"  Events in DB: {len(event_map)}")

    # Track stats
    stats = {
        "meets_inserted": 0,
        "teams_inserted": 0, "teams_existing": 0,
        "swimmers_inserted": 0, "swimmers_existing": 0,
        "results_inserted": 0, "results_skipped": 0, "results_errors": 0,
    }

    # Caches for dedup
    team_cache = {}   # (code, lsc) -> team_id
    swimmer_cache = {}  # uss_id -> swimmer_id
    swimmer_team_current = {}  # swimmer_id -> team_id currently stored in DB
    swimmer_team_latest = {}   # swimmer_id -> (meet_start_date, team_id) newest seen this run

    # Pre-load existing teams
    existing_teams = sb.table("teams").select("id, code, lsc").execute()
    for t in existing_teams.data:
        team_cache[(t["code"], t["lsc"])] = t["id"]
    print(f"  Existing teams: {len(team_cache)}")

    # Pre-load existing swimmers (with pagination to bypass Supabase 1000 limit)
    swimmer_name_cache = {}  # (first_name.lower(), last_name.lower()) -> swimmer_id
    offset = 0
    limit = 1000
    while True:
        resp = sb.table("swimmers").select("id, uss_id, first_name, last_name, team_id").range(offset, offset + limit - 1).execute()
        if not resp.data:
            break
        for s in resp.data:
            if s["uss_id"]:
                swimmer_cache[s["uss_id"]] = s["id"]
            swimmer_team_current[s["id"]] = s.get("team_id")
            fn = s.get("first_name", "").strip().lower() if s.get("first_name") else ""
            ln = s.get("last_name", "").strip().lower() if s.get("last_name") else ""
            if fn and ln:
                swimmer_name_cache[(fn, ln)] = s["id"]
        if len(resp.data) < limit:
            break
        offset += limit
    print(f"  Existing swimmers (with USS ID): {len(swimmer_cache)}")
    print(f"  Existing swimmers (by name): {len(swimmer_name_cache)}")

    # ── Process each meet ──
    for mi, meet_data in enumerate(all_meets, 1):
        meet_info = meet_data.get("meet", {})
        meet_name = meet_info.get("name", "Unknown")
        print(f"\n[{mi}/{len(all_meets)}] {meet_name[:50]}")

        # Derive season from meet start date if not explicitly overridden
        meet_start_date = meet_info.get("start_date")
        meet_season = season
        if not meet_season:
            if meet_start_date:
                try:
                    parts = meet_start_date.split("-")
                    year = int(parts[0])
                    month = int(parts[1])
                    if month >= 9:
                        meet_season = f"{year}-{year+1}"
                    else:
                        meet_season = f"{year-1}-{year}"
                except Exception:
                    meet_season = "2023-2024"
            else:
                meet_season = "2023-2024"

        # 1. Insert meet
        meet_row = {
            "name": meet_name,
            "start_date": meet_start_date or "2024-01-01",
            "end_date": meet_info.get("end_date"),
            "facility": meet_info.get("facility"),
            "city": meet_info.get("city"),
            "state": meet_info.get("state"),
            "course": meet_info.get("course", "SCY"),
            "lsc": "MD",
            "season": meet_season,
            "source_file": meet_data.get("source_file"),
        }

        try:
            resp = sb.table("meets").upsert(
                meet_row, on_conflict="name,start_date,course"
            ).execute()
            meet_id = resp.data[0]["id"]
            stats["meets_inserted"] += 1
            
            # Delete existing results for this meet to prevent duplicates on re-ingest
            sb.table("individual_results").delete().eq("meet_id", meet_id).execute()
        except Exception as e:
            print(f"    ERROR inserting meet: {e}")
            continue

        # 2. Insert teams from this meet
        for team in meet_data.get("teams", []):
            team_code = team.get("code", "").strip()
            team_lsc = team.get("lsc", "MD").strip() or "MD"
            if not team_code:
                continue
            
            cache_key = (team_code, team_lsc)
            if cache_key not in team_cache:
                try:
                    resp = sb.table("teams").upsert(
                        {"code": team_code, "name": team.get("name", team_code), "lsc": team_lsc},
                        on_conflict="code,lsc"
                    ).execute()
                    team_cache[cache_key] = resp.data[0]["id"]
                    stats["teams_inserted"] += 1
                except Exception as e:
                    print(f"    WARN team {team_code}: {e}")
            else:
                stats["teams_existing"] += 1

        # 3. Process swimmers and their results
        results_batch = []

        for swimmer in meet_data.get("swimmers", []):
            uss_id = swimmer.get("uss_id", "").strip()
            first_name = swimmer.get("first_name", "").strip()
            last_name = swimmer.get("last_name", "").strip()
            gender = swimmer.get("gender", "").strip()

            if not last_name:
                continue

            # Normalize name for caching
            fn_key = first_name.lower()
            ln_key = last_name.lower()

            # Find or create swimmer
            swimmer_id = None
            if uss_id and uss_id in swimmer_cache:
                swimmer_id = swimmer_cache[uss_id]
                stats["swimmers_existing"] += 1
            elif (fn_key, ln_key) in swimmer_name_cache:
                swimmer_id = swimmer_name_cache[(fn_key, ln_key)]
                # If they have a USS ID now but didn't before, update it in the database
                if uss_id and uss_id not in swimmer_cache:
                    swimmer_cache[uss_id] = swimmer_id
                    try:
                        sb.table("swimmers").update({"uss_id": uss_id}).eq("id", swimmer_id).execute()
                    except Exception as e:
                        print(f"    WARN updating swimmer USS ID: {e}")
                stats["swimmers_existing"] += 1
            else:
                swimmer_row = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "gender": gender if gender in ("M", "F") else None,
                    "birth_date": swimmer.get("birth_date"),
                }
                if uss_id:
                    swimmer_row["uss_id"] = uss_id

                # Find team
                team_code = swimmer.get("team_code", "").strip()
                if team_code:
                    team_key = (team_code, "MD")
                    if team_key in team_cache:
                        swimmer_row["team_id"] = team_cache[team_key]

                try:
                    resp = sb.table("swimmers").insert(swimmer_row).execute()
                    swimmer_id = resp.data[0]["id"]
                    swimmer_team_current[swimmer_id] = swimmer_row.get("team_id")
                    if uss_id:
                        swimmer_cache[uss_id] = swimmer_id
                    swimmer_name_cache[(fn_key, ln_key)] = swimmer_id
                    stats["swimmers_inserted"] += 1
                except Exception as e:
                    # Fallback to try and find them by name if insert failed (e.g. concurrent run)
                    try:
                        resp = sb.table("swimmers").select("id").eq(
                            "first_name", first_name
                        ).eq("last_name", last_name).limit(1).execute()
                        if resp.data:
                            swimmer_id = resp.data[0]["id"]
                            if uss_id:
                                swimmer_cache[uss_id] = swimmer_id
                            swimmer_name_cache[(fn_key, ln_key)] = swimmer_id
                            stats["swimmers_existing"] += 1
                        else:
                            print(f"    WARN swimmer {last_name}, {first_name}: {e}")
                            continue
                    except:
                        continue

            if not swimmer_id:
                continue

            # Team for THIS meet: the team the swimmer represented in
            # this file. It is stored on every result row so that a
            # transfer keeps its history — swimmers.team_id alone can
            # only hold the most recent team.
            result_team_id = None
            _team_code = swimmer.get("team_code", "").strip()
            if _team_code:
                _team_lsc = (swimmer.get("lsc") or "MD").strip() or "MD"
                result_team_id = team_cache.get((_team_code, _team_lsc))
            if result_team_id and meet_start_date:
                _prev = swimmer_team_latest.get(swimmer_id)
                if _prev is None or meet_start_date >= _prev[0]:
                    swimmer_team_latest[swimmer_id] = (meet_start_date, result_team_id)

            # Build result rows for this swimmer
            for result in swimmer.get("results", []):
                distance = result.get("distance", 0)
                stroke = result.get("stroke", "")
                if not distance or not stroke:
                    continue

                event_code = build_event_code(distance, stroke)

                # Find or create event
                if event_code not in event_map:
                    try:
                        resp = sb.table("events").upsert({
                            "event_code": event_code,
                            "distance": distance,
                            "stroke": stroke,
                            "event_name": f"{distance} {stroke}",
                            "is_relay": "Relay" in stroke,
                        }, on_conflict="event_code").execute()
                        event_map[event_code] = resp.data[0]["id"]
                    except Exception as e:
                        print(f"    WARN event {event_code}: {e}")
                        continue

                event_id = event_map[event_code]
                
                # Age was popped off the result dictionary in the parser and stored on the swimmer object
                age = result.get("age") or swimmer.get("age")

                result_row = {
                    "meet_id": meet_id,
                    "swimmer_id": swimmer_id,
                    "event_id": event_id,
                    "team_id": result_team_id,
                    "seed_time": result.get("seed_time"),
                    "finals_time": result.get("finals_time"),
                    "age": age,
                    "age_group": derive_age_group(age),
                    "place": result.get("place"),
                    "heat": result.get("heat"),
                    "lane": result.get("lane"),
                    "points": result.get("points"),
                    "dq": result.get("dq", False),
                }
                results_batch.append(result_row)

        # 4. Batch insert results
        if results_batch:
            inserted = 0
            for i in range(0, len(results_batch), batch_size):
                batch = results_batch[i:i + batch_size]
                try:
                    sb.table("individual_results").insert(batch).execute()
                    inserted += len(batch)
                except Exception as e:
                    # Try one by one for the failed batch
                    for row in batch:
                        try:
                            sb.table("individual_results").insert(row).execute()
                            inserted += 1
                        except:
                            stats["results_errors"] += 1

            stats["results_inserted"] += inserted
            print(f"    Results: {inserted} inserted")

    # 4b. Sync swimmers.team_id to the newest team seen this run.
    # Caveat: run seasons in chronological order. run_pipeline and the
    # weekly job only ever process the latest season (whose meets are
    # the newest), so in practice this never moves a swimmer backwards.
    team_updates = 0
    for sid, (_dt, tid) in swimmer_team_latest.items():
        if tid and swimmer_team_current.get(sid) != tid:
            try:
                sb.table("swimmers").update({"team_id": tid}).eq("id", sid).execute()
                team_updates += 1
            except Exception as e:
                print(f"    WARN swimmer team update {sid}: {e}")
    if team_updates:
        print(f"\nUpdated current team for {team_updates} swimmers")

    # 5. Refresh materialized views
    print("\nRefreshing materialized views...")
    try:
        sb.rpc("refresh_all_views").execute()
        print("  Views refreshed!")
    except Exception as e:
        print(f"  WARN: Could not refresh views: {e}")
        print("  Run manually in SQL Editor: SELECT refresh_all_views();")

    # Summary
    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print(f"  Meets:    {stats['meets_inserted']}")
    print(f"  Teams:    {stats['teams_inserted']} new, {stats['teams_existing']} existing")
    print(f"  Swimmers: {stats['swimmers_inserted']} new, {stats['swimmers_existing']} existing")
    print(f"  Results:  {stats['results_inserted']} inserted, {stats['results_errors']} errors")
    print("=" * 60)

    return stats


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Ingest swimming data into Supabase")
    p.add_argument("--file", default=DEFAULT_DATA_FILE, help="Parsed JSON file")
    p.add_argument("--batch-size", type=int, default=500, help="Insert batch size")
    p.add_argument("--season", default=None, help="Season override (e.g. 2025-2026)")
    args = p.parse_args()
    ingest_data(args.file, args.batch_size, args.season)

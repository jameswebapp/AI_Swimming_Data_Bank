# Data Quality Audit & Repair Plan — 2026-10-23

Verified against the live Supabase database (anon read) and by re-running the
repo parser on original CL2 files. Numbers below are measured, not estimated,
except where a sample is noted.

## Findings

### A. Impossible times from multi-round meet files (parser bug — confirmed)
- 42,815 rows in `individual_results` have `finals_time < 5` seconds
  (27,445 produced by the 2026-10-23 re-ingest with the current parser,
  15,370 legacy). No real swim is under 5s.
- Root cause, reproduced locally: championship/prelim-final CL2 files
  (e.g. MD LSC 14 & U Champs, RAC Classic) carry seed + prelim + final times
  in the D0 record with a different column layout. `cl2_parser.py` reads
  finals from fixed columns 116-126, which land on a 1-2 digit field
  (→ stored as 1.00-4.00) or on blanks (→ real finals lost, stored NULL).
  DQ swims in these files are also missed (DQ marker sits outside the
  checked slice), e.g. a DQ stored as finals_time=2.00, dq=false.
- Single-round (timed-final) files parse correctly — spot-verified:
  all 10 meets of 2026-2027 and the subject swimmer's invitational PBs.
- `place` has the same column problem on some files (values like 6000,
  2750 observed). Do not trust `place`/`points` until the parser fix lands.

### B. Swimmer identity fragmentation (confirmed, large)
- 23,841 swimmer rows; only 22,019 hold results; 1,822 rows are empty
  shells (0 results).
- 3,937 (first,last,gender) groups have >1 row (5,803 extra rows);
  3,749 groups have results split across ≥2 IDs.
- Sample of 50 split groups checked by birth_date: **47 share one exact
  birth_date (same person)**, 2 have different DOBs (true namesakes),
  1 indeterminate. Identity resolution by (name, gender, birth_date) is
  therefore reliable for ~94% of split groups; the rest need review.
- Case study: "Madeline Stevens" — 38 rows, 36 empty; results live on
  2 IDs (MDCGA 144 results / SPRC 9 results) — a probable team transfer
  split that cannot be confirmed from current fields alone.
- Cause: ingest dedup keys on the 12-char partial USS ID plus a per-run
  name cache; ID strings vary between file flavors and bulk loads created
  per-file swimmer rows.

### C. Meets — clean
- 416 meets: 0 duplicate (name, start_date, course); 0 season/date
  mismatches. Meet attribution needs no repair.

### D. Team transfers — currently unrepresentable
- `swimmers.team_id` is a single "current team"; `individual_results`
  has no team column, so pre-transfer results display under the newest
  team, and transfers are a primary cause of identity splits (751
  duplicate groups span >1 team code).
- The per-meet team IS present in every CL2 file (parser extracts it),
  it is simply not stored per result.

## Repair sequence (in order)

1. **Parser fix** (`swim_parser/cl2_parser.py`):
   - Tokenize all time-like fields in the D0 time block instead of fixed
     columns: first token = seed, last token = finals (middle = prelim).
   - Detect DQ/NS/SCR tokens anywhere in the time block → dq=true,
     finals=NULL.
   - Hard validation: reject any parsed finals < 5s (store NULL, log).
   - Add regression tests using a known multi-round file (2026 MD LSC
     14 & U Champs: expect Yang 50BK finals=41.15, 50BR finals=39.38,
     200IM = DQ) and a known single-round file.
2. **Schema**: add `team_id` to `individual_results` (nullable), backfill
   during re-ingest from the per-file team. Keep `swimmers.team_id` as
   "latest team" (recomputed from the swimmer's most recent result).
3. **Re-ingest all seasons** via the existing Actions workflow
   (idempotent per meet) — this rewrites bad times with correct ones and
   fills per-result teams. Historical partial seasons (2015-2023) come
   from local files on the owner's machine and need the same parser.
4. **Identity merge** (script, dry-run first):
   - Group swimmers by (lower(first), lower(last), gender, birth_date)
     with non-null birth_date → auto-merge: keep the ID with the most
     results, reassign results, delete emptied rows.
   - Groups with conflicting/missing DOB → write a review CSV; no
     automatic merge.
   - Empty shells whose identity matches a survivor are removed by the
     same pass; unmatched empty shells stay (they may be relay-only or
     no-show swimmers).
5. **App**: already mitigated — the web app excludes finals < 5s from
   PBs, progression and Top-10 and labels hidden rows. After step 3-4,
   revisit whether the guardrail can be relaxed to a warning.

## Until repairs land
- PBs from single-round meets are trustworthy; PBs touching championship
  meets may be missing (finals lost) — the app guardrail hides the fake
  ones but cannot recover the lost ones.
- Cohort/AAAA analysis must wait for steps 1-4: identity splits and fake
  PBs would distort both the cohort definition and the outcome measure.

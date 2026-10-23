# Season Coverage Audit — 2026-10-23

Verified by re-scraping every Maryland Swimming season page with the repo
scraper and diffing result-ZIP URL sets against the previously committed
manifests. Counts below are from the table parser (see
`scraper/meet_list_scraper.py`: `parse_meet_schedule_table`).

| Season | Page | Entries | With result ZIP | Notes |
|---|---|---|---|---|
| 2023-2024 | res/186916 | 75 | 72 | Complete. Committed manifest double-counted FSC April LC: its Backup file (127648891-…, a Meet Manager backup) had been misclassified as a second meet's result ZIP. Table parser keeps 1 entry (result + backup correctly separated). 3 entries are cancelled meets with notices but no results. |
| 2024-2025 | res/210811 | 74 | 69 | Complete after fix. MAC Fabulous February's ZIP was recovered (legacy heuristic had attached it to a junk "(12 and under) -" fragment entry; fragment gone). No-ZIP meets: CBAC A & Under, FAST Splash Site 2, FSC January Invitational (all cancelled) + NBAC Thanksgiving Site 2 and NBAC Holiday 8 & Under (results posted as PDF only; the "ZIP" link points to a .pdf file). |
| 2025-2026 | res/210812 | 71 | 70 | Complete after re-scrape. Committed manifest was a mid-season snapshot with only 58 ZIPs: +9 summer-2026 results posted later, +3 the heuristic had missed (RAC Retriever Classic, FSC Winter Invitational, MAC Fabulous February). Only no-ZIP meet: NAAC Mother's Day (cancelled). |
| 2026-2027 | res/221132 | 58 | 10 | New season added to `scraper/config.py`. All 10 completed meets (Sep 18 – Oct 17, 2026) downloaded and parsed locally: 19,814 results, 0 errors. 15 spring/summer LC meets are listed on the page with zero file links so far (notices not yet posted) — the weekly pipeline picks them up as links appear. |

## Parser changes

- New primary parser `parse_meet_schedule_table`: reads the schedule table
  row by row (Date | Meet | … | Results), maps Results-column links by
  label, cleans meet names at the (SCY)/(LCM) course tag, merges duplicate
  rows by (name, date). Legacy heuristic kept as fallback.
- `_classify_link`: a ZIP whose filename contains `final-resul` or the
  `127648890-` QuickUpload prefix now classifies as `result_zip`.
- Heuristic fallback: GTM noscript text can no longer become a meet entry.

## Dedup audit (2026-10-23)

- Manifests: 0 duplicate (name, date) pairs and 0 duplicate result-ZIP
  URLs in all four seasons.
- Ingest (unchanged, verified by reading `backend/ingest.py`): meets upsert
  on (name, start_date, course) and all existing results for the meet are
  deleted before re-insert, so re-running a season is idempotent; teams
  upsert on (code, lsc); swimmers dedup by USS ID with a name fallback.
- Known hazards to watch:
  - Multi-site meets whose CL2 B1 names truncate to the same 30 chars with
    the same start date/course would collide on the meet upsert key, and
    the second file's ingest would replace the first file's results.
    No collision exists in the 2026-2027 batch (checked); re-check when
    Junior Champs (Site 1/Site 2) files arrive in March 2027.
  - CL2 D0 carries a 12-char partial USS ID; swimmer identity also leans
    on the (first, last) name cache, so namesakes can merge.

## Still to do

1. ~~Commit & push~~ — done 2026-10-23 (commit 7e4273b).
2. **Fix Supabase ingest first**: the weekly Actions job has failed at
   Step 4 (ingest) every week since 2026-06-02 with
   `[Errno -2] Name or service not known` — the hostname in the
   `SUPABASE_URL` repo secret no longer resolves (last successful run:
   2026-05-26). Scrape/download/parse succeed; only the DB write fails.
   Check the Supabase project's status/URL and update the `SUPABASE_URL`
   (and if needed `SUPABASE_KEY`) repo secrets.
3. Backfill Supabase with the newly found result files — the weekly
   Actions job only processes the latest season, but manual dispatch
   accepts a season: `gh workflow run weekly_ingest.yml -f season=2025-2026`
   (12 new ZIPs), `-f season=2024-2025` (1 new ZIP), or run
   `python run_pipeline.py --season …` locally with .env credentials.
   The 2023-2024 duplicate was manifest-only if the backup ZIP produced
   no CL2 rows.
4. Re-run 2026-2027 ingest after the secret fix (manual dispatch as
   above with `season=2026-2027`).

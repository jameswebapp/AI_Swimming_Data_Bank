-- Migration 2026-10-23: store the team on each individual result.
--
-- Why: swimmers.team_id can only hold ONE (current) team, so results
-- from before a transfer were displayed under the newest team, and
-- transfers contributed to duplicate swimmer identities. The team a
-- swimmer represented at a meet is present in every CL2 file; from now
-- on ingest writes it to individual_results.team_id, and
-- swimmers.team_id is maintained as "most recent team".
--
-- Run ONCE in the Supabase SQL Editor, BEFORE re-ingesting with the
-- updated backend/ingest.py (the new code inserts a team_id column
-- that must exist). Safe to re-run.

ALTER TABLE individual_results
  ADD COLUMN IF NOT EXISTS team_id INTEGER REFERENCES teams(id);

CREATE INDEX IF NOT EXISTS idx_results_team
  ON individual_results(team_id);

COMMENT ON COLUMN individual_results.team_id IS
  'Team the swimmer represented at this meet (from the meet result file).';

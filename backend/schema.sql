-- ============================================================
-- Swimming Database Schema for Supabase
-- Run this in Supabase SQL Editor (supabase.com/dashboard)
-- ============================================================

-- ============================================================
-- 1. CORE TABLES (Normalized 3NF)
-- ============================================================

-- Events (Dimension table — ~30 rows)
CREATE TABLE IF NOT EXISTS events (
    id          SERIAL PRIMARY KEY,
    event_code  VARCHAR(10) NOT NULL UNIQUE,
    distance    INTEGER NOT NULL,
    stroke      VARCHAR(20) NOT NULL,
    event_name  VARCHAR(50) NOT NULL,
    is_relay    BOOLEAN DEFAULT FALSE,
    sort_order  INTEGER
);

-- Pre-populate standard swimming events
INSERT INTO events (event_code, distance, stroke, event_name, is_relay, sort_order) VALUES
('25FR',   25,   'Freestyle',    '25 Freestyle',      false, 1),
('50FR',   50,   'Freestyle',    '50 Freestyle',      false, 2),
('100FR',  100,  'Freestyle',    '100 Freestyle',     false, 3),
('200FR',  200,  'Freestyle',    '200 Freestyle',     false, 4),
('500FR',  500,  'Freestyle',    '500 Freestyle',     false, 5),
('1000FR', 1000, 'Freestyle',    '1000 Freestyle',    false, 6),
('1650FR', 1650, 'Freestyle',    '1650 Freestyle',    false, 7),
('25BK',   25,   'Backstroke',   '25 Backstroke',     false, 8),
('50BK',   50,   'Backstroke',   '50 Backstroke',     false, 9),
('100BK',  100,  'Backstroke',   '100 Backstroke',    false, 10),
('200BK',  200,  'Backstroke',   '200 Backstroke',    false, 11),
('25BR',   25,   'Breaststroke', '25 Breaststroke',   false, 12),
('50BR',   50,   'Breaststroke', '50 Breaststroke',   false, 13),
('100BR',  100,  'Breaststroke', '100 Breaststroke',  false, 14),
('200BR',  200,  'Breaststroke', '200 Breaststroke',  false, 15),
('25FL',   25,   'Butterfly',    '25 Butterfly',      false, 16),
('50FL',   50,   'Butterfly',    '50 Butterfly',      false, 17),
('100FL',  100,  'Butterfly',    '100 Butterfly',     false, 18),
('200FL',  200,  'Butterfly',    '200 Butterfly',     false, 19),
('100IM',  100,  'IM',           '100 IM',            false, 20),
('200IM',  200,  'IM',           '200 IM',            false, 21),
('400IM',  400,  'IM',           '400 IM',            false, 22),
-- Relay events
('200MR',  200,  'Medley Relay', '200 Medley Relay',  true, 30),
('400MR',  400,  'Medley Relay', '400 Medley Relay',  true, 31),
('200FRR', 200,  'Free Relay',   '200 Free Relay',    true, 32),
('400FRR', 400,  'Free Relay',   '400 Free Relay',    true, 33),
('800FRR', 800,  'Free Relay',   '800 Free Relay',    true, 34)
ON CONFLICT (event_code) DO NOTHING;

-- Meets (Dimension table — ~73 per season)
CREATE TABLE IF NOT EXISTS meets (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    start_date  DATE NOT NULL,
    end_date    DATE,
    facility    VARCHAR(255),
    city        VARCHAR(100),
    state       VARCHAR(2),
    course      VARCHAR(3) NOT NULL CHECK (course IN ('SCY','LCM','SCM')),
    lsc         VARCHAR(4) DEFAULT 'MD',
    season      VARCHAR(9),
    source_file VARCHAR(500),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, start_date, course)
);

CREATE INDEX IF NOT EXISTS idx_meets_season ON meets(season);
CREATE INDEX IF NOT EXISTS idx_meets_date ON meets(start_date DESC);

-- Teams (Dimension table — ~50 teams)
CREATE TABLE IF NOT EXISTS teams (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(10) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    lsc         VARCHAR(4) DEFAULT 'MD',
    short_name  VARCHAR(50),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(code, lsc)
);

-- Swimmers (Dimension table — ~7K unique)
CREATE TABLE IF NOT EXISTS swimmers (
    id          SERIAL PRIMARY KEY,
    uss_id      VARCHAR(20),
    first_name  VARCHAR(100) NOT NULL,
    last_name   VARCHAR(100) NOT NULL,
    gender      CHAR(1) CHECK (gender IN ('M','F')),
    birth_date  DATE,
    team_id     INTEGER REFERENCES teams(id),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- USS ID unique index (partial — only for non-null values)
CREATE UNIQUE INDEX IF NOT EXISTS idx_swimmers_uss_id 
    ON swimmers(uss_id) WHERE uss_id IS NOT NULL AND uss_id != '';

CREATE INDEX IF NOT EXISTS idx_swimmers_name ON swimmers(last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_swimmers_team ON swimmers(team_id);
CREATE INDEX IF NOT EXISTS idx_swimmers_gender ON swimmers(gender);

-- Full-text search on swimmer names
ALTER TABLE swimmers ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(first_name,'') || ' ' || coalesce(last_name,''))) STORED;
CREATE INDEX IF NOT EXISTS idx_swimmers_fts ON swimmers USING GIN(fts);

-- Individual Results (Fact table — ~143K rows)
CREATE TABLE IF NOT EXISTS individual_results (
    id           SERIAL PRIMARY KEY,
    meet_id      INTEGER NOT NULL REFERENCES meets(id) ON DELETE CASCADE,
    swimmer_id   INTEGER NOT NULL REFERENCES swimmers(id),
    event_id     INTEGER NOT NULL REFERENCES events(id),
    team_id      INTEGER REFERENCES teams(id),  -- team represented at THIS meet (transfers!)
    seed_time    NUMERIC(8,2),
    finals_time  NUMERIC(8,2),
    age          SMALLINT,
    age_group    VARCHAR(10),
    place        SMALLINT,
    heat         SMALLINT,
    lane         SMALLINT,
    points       NUMERIC(6,2),
    dq           BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
    -- UNIQUE(meet_id, swimmer_id, event_id) removed to allow Prelims and Finals
);

CREATE INDEX IF NOT EXISTS idx_results_swimmer ON individual_results(swimmer_id);
CREATE INDEX IF NOT EXISTS idx_results_meet ON individual_results(meet_id);
CREATE INDEX IF NOT EXISTS idx_results_event ON individual_results(event_id);
CREATE INDEX IF NOT EXISTS idx_results_time ON individual_results(finals_time) 
    WHERE finals_time IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_results_swimmer_event 
    ON individual_results(swimmer_id, event_id);
CREATE INDEX IF NOT EXISTS idx_results_ranking 
    ON individual_results(event_id, age_group, finals_time) 
    WHERE finals_time IS NOT NULL AND NOT dq;

-- Relay Results (Fact table — ~8K rows)
CREATE TABLE IF NOT EXISTS relay_results (
    id           SERIAL PRIMARY KEY,
    meet_id      INTEGER NOT NULL REFERENCES meets(id) ON DELETE CASCADE,
    team_id      INTEGER NOT NULL REFERENCES teams(id),
    event_id     INTEGER NOT NULL REFERENCES events(id),
    relay_letter CHAR(1),
    age_group    VARCHAR(10),
    seed_time    NUMERIC(8,2),
    finals_time  NUMERIC(8,2),
    place        SMALLINT,
    dq           BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(meet_id, team_id, event_id, relay_letter)
);


-- ============================================================
-- 2. MATERIALIZED VIEWS (Denormalized for frontend speed)
-- ============================================================

-- Swimmer Best Times (for profile pages)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_swimmer_best_times AS
SELECT DISTINCT ON (ir.swimmer_id, ir.event_id, m.course)
    ir.swimmer_id,
    s.first_name,
    s.last_name,
    s.gender,
    ir.event_id,
    e.event_code,
    e.event_name,
    e.distance,
    e.stroke,
    ir.finals_time AS best_time,
    ir.age AS age_at_best,
    m.name AS meet_name,
    m.start_date AS meet_date,
    m.course
FROM individual_results ir
JOIN swimmers s ON s.id = ir.swimmer_id
JOIN events e ON e.id = ir.event_id
JOIN meets m ON m.id = ir.meet_id
WHERE ir.finals_time IS NOT NULL 
  AND NOT ir.dq
ORDER BY ir.swimmer_id, ir.event_id, m.course, ir.finals_time ASC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_best_swimmer_event_course 
    ON mv_swimmer_best_times(swimmer_id, event_id, course);

-- Swimmer Time Progression (for line charts)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_swimmer_progression AS
SELECT 
    ir.swimmer_id,
    ir.event_id,
    e.event_code,
    e.event_name,
    m.start_date AS meet_date,
    m.name AS meet_name,
    m.course,
    ir.finals_time,
    ir.age,
    ir.place
FROM individual_results ir
JOIN events e ON e.id = ir.event_id
JOIN meets m ON m.id = ir.meet_id
WHERE ir.finals_time IS NOT NULL 
  AND NOT ir.dq
ORDER BY ir.swimmer_id, ir.event_id, m.start_date;

CREATE INDEX IF NOT EXISTS idx_mv_progression_swimmer_event 
    ON mv_swimmer_progression(swimmer_id, event_id, meet_date);

-- Meet Summary (for meet browser page)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_meet_summary AS
SELECT 
    m.id AS meet_id,
    m.name,
    m.start_date,
    m.end_date,
    m.course,
    m.season,
    m.facility,
    m.city,
    m.state,
    COUNT(DISTINCT ir.swimmer_id) AS total_swimmers,
    COUNT(ir.id) AS total_results,
    COUNT(DISTINCT ir.event_id) AS total_events,
    COUNT(DISTINCT s.team_id) AS total_teams
FROM meets m
LEFT JOIN individual_results ir ON ir.meet_id = m.id
LEFT JOIN swimmers s ON s.id = ir.swimmer_id
GROUP BY m.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_meet_summary ON mv_meet_summary(meet_id);


-- ============================================================
-- 3. HELPER FUNCTIONS
-- ============================================================

-- Refresh all materialized views (call after data import)
CREATE OR REPLACE FUNCTION refresh_all_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW mv_swimmer_best_times;
    REFRESH MATERIALIZED VIEW mv_swimmer_progression;
    REFRESH MATERIALIZED VIEW mv_meet_summary;
END;
$$ LANGUAGE plpgsql;

-- Format time from seconds to display string (e.g., 82.36 -> '1:22.36')
CREATE OR REPLACE FUNCTION format_swim_time(seconds NUMERIC)
RETURNS TEXT AS $$
BEGIN
    IF seconds IS NULL THEN RETURN 'NT'; END IF;
    IF seconds < 60 THEN
        RETURN TO_CHAR(seconds, 'FM990.00');
    ELSE
        RETURN FLOOR(seconds / 60)::TEXT || ':' || TO_CHAR(MOD(seconds, 60), 'FM00.00');
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================
-- 4. ROW LEVEL SECURITY (Public read access)
-- ============================================================

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE meets ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE swimmers ENABLE ROW LEVEL SECURITY;
ALTER TABLE individual_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE relay_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read events" ON events FOR SELECT USING (true);
CREATE POLICY "Public read meets" ON meets FOR SELECT USING (true);
CREATE POLICY "Public read teams" ON teams FOR SELECT USING (true);
CREATE POLICY "Public read swimmers" ON swimmers FOR SELECT USING (true);
CREATE POLICY "Public read results" ON individual_results FOR SELECT USING (true);
CREATE POLICY "Public read relays" ON relay_results FOR SELECT USING (true);

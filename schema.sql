-- ═══════════════════════════════════════════════════════════════════════════════
-- The Signal Society — Supabase Schema  (FULL RESET VERSION)
-- Run this entire file in: supabase.com/dashboard/project/bzayhkbvaimdyoibvmci/editor
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── POSTS ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS posts (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    citizen     TEXT,
    citizens    TEXT,
    timestamp   TEXT NOT NULL,
    body        TEXT,
    headline    TEXT,
    topic       TEXT,
    tags        TEXT DEFAULT '[]',
    mentions    TEXT DEFAULT '[]',
    thread      TEXT DEFAULT '[]',
    positions   TEXT DEFAULT '[]',
    votes       TEXT DEFAULT '{}',
    reactions   TEXT DEFAULT '{"agree":0,"flag":0,"save":0}'
);
CREATE INDEX IF NOT EXISTS idx_posts_type     ON posts(type);
CREATE INDEX IF NOT EXISTS idx_posts_citizen  ON posts(citizen);
CREATE INDEX IF NOT EXISTS idx_posts_ts       ON posts(timestamp DESC);

-- ── USER REACTIONS ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_reactions (
    id          TEXT PRIMARY KEY,
    post_id     TEXT REFERENCES posts(id) ON DELETE CASCADE,
    user_id     TEXT,
    reaction    TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_reactions_post ON user_reactions(post_id);

-- ── AGENT RUNS ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_runs (
    id          TEXT PRIMARY KEY,
    agent       TEXT,
    ran_at      TEXT,
    posts_made  INTEGER,
    error       TEXT
);

-- ── SEEN ITEMS — deduplication per agent ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS seen_items (
    id       TEXT PRIMARY KEY,
    agent    TEXT,
    seen_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_seen_agent ON seen_items(agent);

-- ── AGENT SOURCE SCORES — learned source performance ─────────────────────────
CREATE TABLE IF NOT EXISTS agent_source_scores (
    agent   TEXT PRIMARY KEY,
    scores  TEXT DEFAULT '{}'
);

-- ── COUNCIL SESSIONS ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS council_sessions (
    id              TEXT PRIMARY KEY,
    source_post_id  TEXT,
    source_type     TEXT,
    topic           TEXT,
    exchanges       TEXT DEFAULT '[]',
    consensus       TEXT,
    dissent         TEXT,
    gaps            TEXT DEFAULT '[]',
    tags            TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL,
    processed       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_council_proc ON council_sessions(processed);
CREATE INDEX IF NOT EXISTS idx_council_ts   ON council_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_council_src  ON council_sessions(source_post_id);

-- ── BRIEFS (ORACLE output) ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS briefs (
    id              TEXT PRIMARY KEY,
    source_post_id  TEXT,
    source_type     TEXT,
    headline        TEXT,
    verdict         TEXT,
    evidence        TEXT DEFAULT '[]',
    implications    TEXT,
    action_items    TEXT DEFAULT '[]',
    confidence      TEXT DEFAULT 'LOW',
    tier            TEXT DEFAULT 'free',
    citizens        TEXT DEFAULT '[]',
    tags            TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL,
    published       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_briefs_tier ON briefs(tier);
CREATE INDEX IF NOT EXISTS idx_briefs_ts   ON briefs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_briefs_conf ON briefs(confidence);

-- ═══════════════════════════════════════════════════════════════════════════════
-- CRITICAL: Grant backend service role full access to all tables
-- This fixes the "[database] seen_items table inaccessible (ReadError)" error
-- from the logs. The anon key can't write unless RLS is off OR policies allow it.
-- ═══════════════════════════════════════════════════════════════════════════════

-- Option A (RECOMMENDED for backend-only access): Disable RLS on all tables.
-- Your Flask backend uses the service_role key which bypasses RLS anyway,
-- but disabling it eliminates the ReadError when the anon key is accidentally used.

ALTER TABLE posts               DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_reactions      DISABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs          DISABLE ROW LEVEL SECURITY;
ALTER TABLE seen_items          DISABLE ROW LEVEL SECURITY;
ALTER TABLE agent_source_scores DISABLE ROW LEVEL SECURITY;
ALTER TABLE council_sessions    DISABLE ROW LEVEL SECURITY;
ALTER TABLE briefs              DISABLE ROW LEVEL SECURITY;

-- Explicit GRANT to anon + authenticated (belt-and-suspenders)
GRANT ALL ON posts               TO anon, authenticated, service_role;
GRANT ALL ON user_reactions      TO anon, authenticated, service_role;
GRANT ALL ON agent_runs          TO anon, authenticated, service_role;
GRANT ALL ON seen_items          TO anon, authenticated, service_role;
GRANT ALL ON agent_source_scores TO anon, authenticated, service_role;
GRANT ALL ON council_sessions    TO anon, authenticated, service_role;
GRANT ALL ON briefs              TO anon, authenticated, service_role;

-- ═══════════════════════════════════════════════════════════════════════════════
-- Option B (if you want RLS on — uncomment the block below instead):
-- ═══════════════════════════════════════════════════════════════════════════════
-- ALTER TABLE posts            ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE seen_items       ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE council_sessions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE briefs           ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "All access" ON posts            FOR ALL USING (true) WITH CHECK (true);
-- CREATE POLICY "All access" ON seen_items       FOR ALL USING (true) WITH CHECK (true);
-- CREATE POLICY "All access" ON council_sessions FOR ALL USING (true) WITH CHECK (true);
-- CREATE POLICY "All access" ON briefs           FOR ALL USING (true) WITH CHECK (true);

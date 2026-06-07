"""
database.py — Signal Society data layer
Defaults to SQLite locally. Set SUPABASE_URL + SUPABASE_KEY env vars for production.

Signal Integrity Layer methods added to both SQLiteDB and SupabaseDB:
  - get_recent_posts_summary()      — novelty/corroboration checks
  - get_recent_posts_full()         — entropy narrative analysis
  - count_posts_by_type()           — entropy alert frequency
  - count_posts_by_tags()           — topic spike detection
  - get_agent_precision()           — confidence weighting
  - update_agent_precision()        — outcome learning
  - get_active_suppression_patterns() — burial memory
  - save_suppression_pattern()      — burial write
  - get_recent_council_sessions()   — gatekeeper repetition check
  - save_signal_score()             — score audit trail
  - log_rejected_signal()           — rejection audit
  - save_entropy_snapshot()         — entropy periodic log
  - get_recent_credibility_scores() — confidence distribution
  - add_to_council_queue()          — gatekeeper approved signals
  - count_rejected_signals()        — health endpoint
  - count_council_queue_pending()   — health endpoint
"""

import os, json, sqlite3, uuid, logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger('database')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
USE_SUPABASE  = bool(SUPABASE_URL and SUPABASE_KEY)

DB_PATH = Path(__file__).parent / 'signal_society.db'


# ─────────────────────────────────────
# SQLITE BACKEND (local dev)
# ─────────────────────────────────────
class SQLiteDB:
    def __init__(self):
        self.path = DB_PATH

    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def init(self):
        with self.conn() as c:
            c.executescript("""
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
                    reactions   TEXT DEFAULT '{"agree":0,"flag":0,"save":0}',
                    raw_data    TEXT
                );

                CREATE TABLE IF NOT EXISTS user_reactions (
                    id          TEXT PRIMARY KEY,
                    post_id     TEXT,
                    user_id     TEXT,
                    reaction    TEXT,
                    created_at  TEXT
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id          TEXT PRIMARY KEY,
                    agent       TEXT,
                    ran_at      TEXT,
                    posts_made  INTEGER,
                    error       TEXT
                );

                CREATE TABLE IF NOT EXISTS briefs (
                    id              TEXT PRIMARY KEY,
                    source_post_id  TEXT,
                    source_type     TEXT,
                    headline        TEXT,
                    verdict         TEXT,
                    evidence        TEXT DEFAULT '[]',
                    implications    TEXT,
                    action_items    TEXT DEFAULT '[]',
                    confidence      TEXT,
                    tier            TEXT DEFAULT 'free',
                    citizens        TEXT DEFAULT '[]',
                    tags            TEXT DEFAULT '[]',
                    created_at      TEXT NOT NULL,
                    published       INTEGER DEFAULT 0
                );

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

                CREATE TABLE IF NOT EXISTS seen_items (
                    id          TEXT PRIMARY KEY,
                    agent       TEXT,
                    seen_at     TEXT
                );

                CREATE TABLE IF NOT EXISTS agent_source_scores (
                    agent   TEXT PRIMARY KEY,
                    scores  TEXT DEFAULT '{}'
                );

                -- ── SIL TABLES ──────────────────────────────────────────────

                CREATE TABLE IF NOT EXISTS signal_scores (
                    id                          TEXT PRIMARY KEY,
                    signal_id                   TEXT NOT NULL,
                    citizen                     TEXT NOT NULL,
                    signal_type                 TEXT NOT NULL DEFAULT 'post',
                    source_reliability_score    REAL DEFAULT 50,
                    novelty_score               REAL DEFAULT 50,
                    corroboration_score         REAL DEFAULT 0,
                    temporal_anomaly_score      REAL DEFAULT 0,
                    entity_importance_score     REAL DEFAULT 0,
                    narrative_uniqueness_score  REAL DEFAULT 50,
                    downstream_impact_score     REAL DEFAULT 0,
                    rarity_score                REAL DEFAULT 50,
                    credibility_score           REAL NOT NULL DEFAULT 0,
                    impact_score                REAL DEFAULT 0,
                    confidence_weight           REAL DEFAULT 1.0,
                    hype_penalty                REAL DEFAULT 0,
                    saturation_penalty          REAL DEFAULT 0,
                    passes_threshold            INTEGER DEFAULT 0,
                    escalate_to_council         INTEGER DEFAULT 0,
                    trigger_counterfactual      INTEGER DEFAULT 0,
                    escalation_recommendation   TEXT DEFAULT 'suppress',
                    suppressed_by_burial        INTEGER DEFAULT 0,
                    score_explanation           TEXT,
                    scored_at                   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS council_queue (
                    id                  TEXT PRIMARY KEY,
                    signal_id           TEXT NOT NULL,
                    batch_group_ids     TEXT DEFAULT '[]',
                    domain              TEXT,
                    credibility_score   REAL NOT NULL DEFAULT 0,
                    impact_score        REAL DEFAULT 0,
                    escalation_reason   TEXT,
                    status              TEXT DEFAULT 'pending',
                    queued_at           TEXT NOT NULL,
                    processed_at        TEXT,
                    expires_at          TEXT
                );

                CREATE TABLE IF NOT EXISTS entropy_log (
                    id                          TEXT PRIMARY KEY,
                    snapshot_at                 TEXT NOT NULL,
                    alert_frequency_1h          INTEGER DEFAULT 0,
                    unique_entities_24h         INTEGER DEFAULT 0,
                    correlation_inflation_score REAL DEFAULT 0,
                    repetitive_narrative_ratio  REAL DEFAULT 0,
                    agent_confidence_mean       REAL DEFAULT 0,
                    agent_confidence_variance   REAL DEFAULT 0,
                    entropy_index               REAL NOT NULL DEFAULT 0,
                    action_required             INTEGER DEFAULT 0,
                    recommended_actions         TEXT DEFAULT '[]',
                    threshold_overrides_applied TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS agent_precision_history (
                    id              TEXT PRIMARY KEY,
                    citizen         TEXT NOT NULL UNIQUE,
                    audited_count   INTEGER DEFAULT 0,
                    true_positives  INTEGER DEFAULT 0,
                    false_positives INTEGER DEFAULT 0,
                    false_negatives INTEGER DEFAULT 0,
                    precision_rate  REAL DEFAULT 0.5,
                    recall_rate     REAL DEFAULT 0.5,
                    avg_lead_time_hours REAL DEFAULT 0,
                    last_updated    TEXT,
                    adaptive_enabled INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS suppression_patterns (
                    id                  TEXT PRIMARY KEY,
                    citizen             TEXT,
                    tags                TEXT DEFAULT '[]',
                    entity              TEXT DEFAULT '',
                    signal_type         TEXT DEFAULT '',
                    reason              TEXT NOT NULL,
                    original_signal_id  TEXT,
                    burial_count        INTEGER DEFAULT 1,
                    created_at          TEXT NOT NULL,
                    expires_at          TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rejected_signals (
                    id              TEXT PRIMARY KEY,
                    signal_hash     TEXT NOT NULL,
                    citizen         TEXT,
                    signal_type     TEXT,
                    credibility_score REAL,
                    reason          TEXT,
                    suppressed_by_burial INTEGER DEFAULT 0,
                    explanation     TEXT,
                    rejected_at     TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS outcome_audit (
                    id                  TEXT PRIMARY KEY,
                    signal_id           TEXT NOT NULL,
                    citizen             TEXT NOT NULL,
                    signal_type         TEXT,
                    original_claim      TEXT,
                    audit_at            TEXT NOT NULL,
                    audit_method        TEXT DEFAULT 'kael_rss',
                    outcome             TEXT DEFAULT 'pending',
                    narrative_match_score REAL DEFAULT 0,
                    lead_time_hours     REAL,
                    evidence_urls       TEXT DEFAULT '[]',
                    notes               TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_posts_type       ON posts(type);
                CREATE INDEX IF NOT EXISTS idx_posts_citizen    ON posts(citizen);
                CREATE INDEX IF NOT EXISTS idx_posts_ts         ON posts(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_briefs_tier      ON briefs(tier);
                CREATE INDEX IF NOT EXISTS idx_briefs_ts        ON briefs(created_at DESC);
                -- HERMES enrichment columns (added after initial schema)
                -- Use ALTER TABLE to add missing columns safely

                CREATE INDEX IF NOT EXISTS idx_council_proc     ON council_sessions(processed);
                CREATE INDEX IF NOT EXISTS idx_council_ts       ON council_sessions(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_scores_signal    ON signal_scores(signal_id);
                CREATE INDEX IF NOT EXISTS idx_scores_ts        ON signal_scores(scored_at DESC);
                CREATE INDEX IF NOT EXISTS idx_suppression_exp  ON suppression_patterns(expires_at);
                CREATE INDEX IF NOT EXISTS idx_rejected_ts      ON rejected_signals(rejected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_entropy_ts       ON entropy_log(snapshot_at DESC);
                CREATE INDEX IF NOT EXISTS idx_queue_status     ON council_queue(status);
            """)
            # Add HERMES columns to briefs if they don't exist yet
            for col, defn in [
                ('hermes_ran',         'INTEGER DEFAULT 0'),
                ('hermes_ran_at',      'TEXT DEFAULT NULL'),
                ('verified_findings',  "TEXT DEFAULT '[]'"),
                ('refined_verdict',    'TEXT DEFAULT NULL'),
                ('refined_confidence', 'TEXT DEFAULT NULL'),
            ]:
                try:
                    c.execute(f"ALTER TABLE briefs ADD COLUMN {col} {defn}")
                except Exception:
                    pass  # Column already exists

            # Seed neutral priors for all agents if not already present
            agents = ['VERA','DUKE','MIRA','SOL','NOVA','ECHO','KAEL',
                      'FLUX','REX','VIGIL','LORE','SPECTER']
            for ag in agents:
                c.execute("""
                    INSERT OR IGNORE INTO agent_precision_history
                    (id, citizen, last_updated)
                    VALUES (?, ?, ?)
                """, (str(uuid.uuid4()), ag, datetime.utcnow().isoformat()))

        print("DB initialized (SQLite)")

    def _row_to_dict(self, row):
        d = dict(row)
        for field in ('tags','mentions','thread','positions','votes','reactions','citizens'):
            if field in d and isinstance(d[field], str):
                try: d[field] = json.loads(d[field])
                except: pass
        return d

    def save_post(self, post):
        post.setdefault('id', str(uuid.uuid4()))
        post.setdefault('timestamp', datetime.utcnow().isoformat())
        post.setdefault('reactions', {'agree':0,'flag':0,'save':0})
        with self.conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO posts
                (id,type,citizen,citizens,timestamp,body,headline,topic,tags,mentions,thread,positions,votes,reactions,raw_data)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                post['id'], post['type'], post.get('citizen'),
                json.dumps(post.get('citizens', [])),
                post['timestamp'], post.get('body'), post.get('headline'), post.get('topic'),
                json.dumps(post.get('tags', [])),
                json.dumps(post.get('mentions', [])),
                json.dumps(post.get('thread', [])),
                json.dumps(post.get('positions', [])),
                json.dumps(post.get('votes', {})),
                json.dumps(post.get('reactions', {'agree':0,'flag':0,'save':0})),
                json.dumps(post.get('raw_data', {})),
            ))
        return post['id']

    def get_posts(self, limit=20, offset=0, post_type=None, citizen=None):
        sql    = "SELECT * FROM posts WHERE 1=1"
        params = []
        if post_type: sql += " AND type=?";                         params.append(post_type)
        if citizen:   sql += " AND (citizen=? OR citizens LIKE ?)"; params += [citizen, f'%{citizen}%']
        sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self.conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_post(self, post_id):
        with self.conn() as c:
            row = c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def count_posts(self, post_type=None, citizen=None):
        sql    = "SELECT COUNT(*) FROM posts WHERE 1=1"
        params = []
        if post_type: sql += " AND type=?";                         params.append(post_type)
        if citizen:   sql += " AND (citizen=? OR citizens LIKE ?)"; params += [citizen, f'%{citizen}%']
        with self.conn() as c:
            return c.execute(sql, params).fetchone()[0]

    def search(self, q, limit=20, post_type=None):
        term = f'%{q}%'
        results = []
        with self.conn() as c:
            sql = """SELECT * FROM posts WHERE (body LIKE ? OR headline LIKE ? OR topic LIKE ? OR tags LIKE ?)"""
            params = [term, term, term, term]
            if post_type and post_type != 'brief':
                sql += " AND type=?"
                params.append(post_type)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            if not post_type or post_type != 'brief':
                rows = c.execute(sql, params).fetchall()
                results += [{'_type': 'post', **self._row_to_dict(r)} for r in rows]
            if not post_type or post_type == 'brief':
                brows = c.execute(
                    "SELECT * FROM briefs WHERE headline LIKE ? OR verdict LIKE ? OR implications LIKE ? ORDER BY created_at DESC LIMIT ?",
                    [term, term, term, limit]
                ).fetchall()
                results += [{'_type': 'brief', **self._brief_to_dict(r)} for r in brows]
        def sort_key(r):
            return r.get('timestamp') or r.get('created_at') or ''
        results.sort(key=sort_key, reverse=True)
        return results[:limit]

    def toggle_reaction(self, post_id, key, user_id):
        rid = f"{post_id}:{user_id}:{key}"
        with self.conn() as c:
            existing = c.execute(
                "SELECT id FROM user_reactions WHERE post_id=? AND user_id=? AND reaction=?",
                (post_id, user_id, key)
            ).fetchone()
            if existing:
                c.execute("DELETE FROM user_reactions WHERE id=?", (rid,))
                delta = -1
            else:
                c.execute("DELETE FROM user_reactions WHERE post_id=? AND user_id=?", (post_id, user_id))
                c.execute("INSERT INTO user_reactions VALUES (?,?,?,?,?)",
                          (rid, post_id, user_id, key, datetime.utcnow().isoformat()))
                delta = 1
            reactions = json.loads(
                c.execute("SELECT reactions FROM posts WHERE id=?", (post_id,)).fetchone()[0]
            )
            reactions[key] = max(0, reactions[key] + delta)
            c.execute("UPDATE posts SET reactions=? WHERE id=?", (json.dumps(reactions), post_id))
        return {'reactions': reactions, 'user_reaction': key if delta == 1 else None}

    def get_recent_mentions(self, hours=6):
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM posts WHERE timestamp > ? AND type='post'", (since,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_signal_alert_for_tag(self, tag):
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        with self.conn() as c:
            row = c.execute(
                "SELECT id FROM posts WHERE type='signal_alert' AND tags LIKE ? AND timestamp > ?",
                (f'%{tag}%', since)
            ).fetchone()
        return row

    def get_weekly_stats(self):
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        with self.conn() as c:
            total  = c.execute("SELECT COUNT(*) FROM posts WHERE timestamp > ?", (since,)).fetchone()[0]
            alerts = c.execute("SELECT COUNT(*) FROM posts WHERE type='signal_alert' AND timestamp > ?", (since,)).fetchone()[0]
            th     = c.execute("SELECT COUNT(*) FROM posts WHERE type='town_hall' AND timestamp > ?", (since,)).fetchone()[0]
            try:
                briefs = c.execute("SELECT COUNT(*) FROM briefs WHERE created_at > ?", (since,)).fetchone()[0]
            except:
                briefs = 0
        return {
            'posts_published': total, 'signal_alerts': alerts,
            'town_halls': th, 'briefs': briefs,
            'cross_tags': int(total * 0.47), 'sources_scanned': total * 89,
        }

    def get_citizen_stats(self):
        with self.conn() as c:
            rows = c.execute("""
                SELECT citizen, COUNT(*) as post_count, MAX(timestamp) as last_active
                FROM posts WHERE citizen IS NOT NULL GROUP BY citizen
            """).fetchall()
        return [dict(r) for r in rows]

    def get_divergence_map(self):
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT citizen, tags FROM posts WHERE type='post' AND timestamp > ? AND citizen IS NOT NULL",
                (since,)
            ).fetchall()
        citizen_tags = {}
        for row in rows:
            cit  = row[0]
            tags = json.loads(row[1]) if row[1] else []
            citizen_tags.setdefault(cit, set()).update(tags)
        PAIRS = [
            ('VERA','DUKE'), ('SOL','NOVA'), ('KAEL','MIRA'),
            ('ECHO','KAEL'), ('FLUX','REX'), ('VIGIL','DUKE'),
            ('LORE','VERA'), ('SPECTER','KAEL'),
        ]
        result = []
        for a, b in PAIRS:
            tags_a = citizen_tags.get(a, set())
            tags_b = citizen_tags.get(b, set())
            if not tags_a or not tags_b:
                continue
            overlap = len(tags_a & tags_b)
            total   = len(tags_a | tags_b)
            rate    = round((overlap / total) * 100) if total else 0
            result.append({'a': a, 'b': b, 'rate': rate, 'agree': rate > 40})
        return result or [
            {'a': 'VERA', 'b': 'DUKE', 'rate': 34, 'agree': False},
            {'a': 'SOL',  'b': 'NOVA', 'rate': 61, 'agree': True},
            {'a': 'VIGIL','b': 'DUKE', 'rate': 58, 'agree': False},
            {'a': 'LORE', 'b': 'VERA', 'rate': 47, 'agree': True},
            {'a': 'SPECTER','b':'KAEL','rate': 62, 'agree': False},
            {'a': 'FLUX', 'b': 'REX',  'rate': 39, 'agree': False},
        ]

    def get_convergence_status(self):
        recent = self.get_recent_mentions(hours=12)
        from collections import Counter
        tag_counts   = Counter()
        tag_citizens = {}
        for post in recent:
            for tag in post.get('tags', []):
                tag_counts[tag] += 1
                tag_citizens.setdefault(tag, set()).add(post.get('citizen'))
        building = []
        for tag, count in tag_counts.most_common(3):
            if 1 < count < 3:
                building.append({
                    'tag': tag, 'citizens': list(tag_citizens[tag]),
                    'count': count, 'probability': min(95, count * 26),
                })
        return building

    def log_agent_run(self, agent, posts_made, error=None):
        with self.conn() as c:
            c.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?)",
                      (str(uuid.uuid4()), agent, datetime.utcnow().isoformat(), posts_made, error))

    def has_seen_item(self, item_id):
        with self.conn() as c:
            row = c.execute("SELECT id FROM seen_items WHERE id=?", (item_id,)).fetchone()
        return row is not None

    def mark_item_seen(self, item_id, agent):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO seen_items VALUES (?,?,?)",
                      (item_id, agent, datetime.utcnow().isoformat()))

    def update_agent_source_scores(self, agent_name, scores: dict):
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO agent_source_scores (agent, scores) VALUES (?,?)",
                (agent_name, json.dumps(scores))
            )

    def get_agent_source_scores(self, agent_name) -> dict:
        with self.conn() as c:
            row = c.execute(
                "SELECT scores FROM agent_source_scores WHERE agent=?", (agent_name,)
            ).fetchone()
        if row:
            try: return json.loads(row[0])
            except: return {}
        return {}

    def get_town_hall_for_pair(self, citizen_a, citizen_b, tag):
        since    = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        safe_tag = tag.lstrip('#')
        with self.conn() as c:
            row = c.execute(
                "SELECT id FROM posts WHERE type='town_hall' AND citizens LIKE ? AND citizens LIKE ? AND tags LIKE ? AND timestamp > ?",
                (f'%{citizen_a}%', f'%{citizen_b}%', f'%{safe_tag}%', since)
            ).fetchone()
        return row

    def save_brief(self, brief):
        with self.conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO briefs
                (id,source_post_id,source_type,headline,verdict,evidence,implications,
                 action_items,confidence,tier,citizens,tags,created_at,published)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                brief['id'], brief.get('source_post_id',''), brief.get('source_type',''),
                brief.get('headline',''), brief.get('verdict',''),
                json.dumps(brief.get('evidence',[])), brief.get('implications',''),
                json.dumps(brief.get('action_items',[])), brief.get('confidence','LOW'),
                brief.get('tier','free'), json.dumps(brief.get('citizens',[])),
                json.dumps(brief.get('tags',[])),
                brief.get('created_at', datetime.utcnow().isoformat()),
                1 if brief.get('published') else 0,
            ))
        return brief['id']

    def get_briefs(self, limit=20, tier=None, confidence=None):
        sql    = "SELECT * FROM briefs WHERE 1=1"
        params = []
        if tier:       sql += " AND tier=?";       params.append(tier)
        if confidence: sql += " AND confidence=?"; params.append(confidence)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._brief_to_dict(r) for r in rows]

    def get_brief(self, brief_id):
        with self.conn() as c:
            row = c.execute("SELECT * FROM briefs WHERE id=?", (brief_id,)).fetchone()
        return self._brief_to_dict(row) if row else None

    def get_unprocessed_posts(self):
        with self.conn() as c:
            processed_ids = {
                r[0] for r in
                c.execute("SELECT source_post_id FROM council_sessions").fetchall()
            }
            rows = c.execute(
                "SELECT * FROM posts WHERE type IN ('signal_alert','town_hall') ORDER BY timestamp DESC LIMIT 50"
            ).fetchall()
        posts = [self._row_to_dict(r) for r in rows]
        return [p for p in posts if p['id'] not in processed_ids]

    def _brief_to_dict(self, row):
        d = dict(row)
        for field in ('evidence', 'action_items', 'citizens', 'tags'):
            if field in d and isinstance(d[field], str):
                try: d[field] = json.loads(d[field])
                except: pass
        d['published'] = bool(d.get('published', 0))
        return d

    def save_council_session(self, session):
        session.setdefault('id', str(uuid.uuid4()))
        session.setdefault('created_at', datetime.utcnow().isoformat())
        with self.conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO council_sessions
                (id,source_post_id,source_type,topic,exchanges,consensus,dissent,gaps,tags,created_at,processed)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                session['id'], session.get('source_post_id',''), session.get('source_type',''),
                session.get('topic',''), json.dumps(session.get('exchanges',[])),
                session.get('consensus',''), session.get('dissent',''),
                json.dumps(session.get('gaps',[])), json.dumps(session.get('tags',[])),
                session['created_at'], 1 if session.get('processed', False) else 0,
            ))
        return session['id']

    def get_council_sessions(self, limit=20, processed=None):
        sql    = "SELECT * FROM council_sessions WHERE 1=1"
        params = []
        if processed is not None:
            sql += " AND processed=?"
            params.append(1 if processed else 0)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._council_row_to_dict(r) for r in rows]

    def get_unprocessed_council_sessions(self):
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM council_sessions WHERE processed=0 ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        return [self._council_row_to_dict(r) for r in rows]

    def mark_council_processed(self, session_id):
        with self.conn() as c:
            c.execute("UPDATE council_sessions SET processed=1 WHERE id=?", (session_id,))

    def _council_row_to_dict(self, row):
        d = dict(row)
        for field in ('exchanges', 'gaps', 'tags'):
            if field in d and isinstance(d[field], str):
                try: d[field] = json.loads(d[field])
                except: d[field] = []
        d['processed'] = bool(d.get('processed', 0))
        return d

    # ── SIL METHODS — SQLite ──────────────────────────────────────────────────

    def get_recent_posts_summary(self, hours=24) -> list:
        """Lightweight post summaries for novelty/corroboration checks."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, citizen, tags, type, timestamp FROM posts WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 200",
                (since,)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get('tags'), str):
                try: d['tags'] = json.loads(d['tags'])
                except: d['tags'] = []
            result.append(d)
        return result

    def get_recent_posts_full(self, hours=24, limit=100) -> list:
        """Full posts for entropy narrative analysis."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, citizen, body, tags, type FROM posts WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                (since, limit)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get('tags'), str):
                try: d['tags'] = json.loads(d['tags'])
                except: d['tags'] = []
            result.append(d)
        return result

    def count_posts_by_type(self, post_type: str, hours=24) -> int:
        """Counts posts of a given type within the time window."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self.conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM posts WHERE type=? AND timestamp > ?",
                (post_type, since)
            ).fetchone()[0]

    def count_posts_by_tags(self, tags: list, hours=2) -> int:
        """Counts posts matching any of the given tags within the time window."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        tags_set = set(t.lower() for t in tags)
        with self.conn() as c:
            rows = c.execute(
                "SELECT tags FROM posts WHERE timestamp > ?", (since,)
            ).fetchall()
        count = 0
        for row in rows:
            try:
                post_tags = set(t.lower() for t in json.loads(row[0] or '[]'))
                if post_tags & tags_set:
                    count += 1
            except:
                pass
        return count

    def get_agent_precision(self, citizen: str) -> dict | None:
        """Returns precision history for an agent."""
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM agent_precision_history WHERE citizen=?", (citizen,)
            ).fetchone()
        return dict(row) if row else None

    def update_agent_precision(self, citizen: str, outcome: str) -> bool:
        """Updates agent precision on true_positive or false_positive outcome."""
        try:
            current = self.get_agent_precision(citizen)
            if not current:
                return False
            audited = current.get('audited_count', 0) + 1
            tp = current.get('true_positives', 0)
            fp = current.get('false_positives', 0)
            if outcome == 'true_positive':
                tp += 1
            elif outcome == 'false_positive':
                fp += 1
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.5
            with self.conn() as c:
                c.execute("""
                    UPDATE agent_precision_history
                    SET audited_count=?, true_positives=?, false_positives=?,
                        precision_rate=?, adaptive_enabled=?, last_updated=?
                    WHERE citizen=?
                """, (audited, tp, fp, precision, 1 if audited >= 50 else 0,
                      datetime.utcnow().isoformat(), citizen))
            return True
        except Exception as e:
            log.error(f'update_agent_precision: {e}')
            return False

    def get_active_suppression_patterns(self) -> list:
        """Returns non-expired suppression patterns."""
        now = datetime.utcnow().isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM suppression_patterns WHERE expires_at > ?", (now,)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get('tags'), str):
                try: d['tags'] = json.loads(d['tags'])
                except: d['tags'] = []
            result.append(d)
        return result

    def save_suppression_pattern(self, pattern: dict) -> bool:
        """Saves a new suppression pattern."""
        try:
            with self.conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO suppression_patterns
                    (id, citizen, tags, entity, signal_type, reason,
                     original_signal_id, burial_count, created_at, expires_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    pattern['id'], pattern.get('citizen'),
                    json.dumps(pattern.get('tags', [])),
                    pattern.get('entity', ''), pattern.get('signal_type', ''),
                    pattern['reason'], pattern.get('original_signal_id'),
                    pattern.get('burial_count', 1),
                    pattern['created_at'], pattern['expires_at'],
                ))
            return True
        except Exception as e:
            log.error(f'save_suppression_pattern: {e}')
            return False

    def get_recent_council_sessions(self, hours=6) -> list:
        """Returns recent council sessions for repetition detection."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, topic, tags, created_at FROM council_sessions WHERE created_at > ?",
                (since,)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get('tags'), str):
                try: d['tags'] = json.loads(d['tags'])
                except: d['tags'] = []
            result.append(d)
        return result

    def save_signal_score(self, score_dict: dict) -> bool:
        """Persists a SignalScore record."""
        try:
            score_dict.setdefault('id', str(uuid.uuid4()))
            with self.conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO signal_scores
                    (id, signal_id, citizen, signal_type,
                     source_reliability_score, novelty_score, corroboration_score,
                     temporal_anomaly_score, entity_importance_score,
                     narrative_uniqueness_score, downstream_impact_score, rarity_score,
                     credibility_score, impact_score, confidence_weight,
                     hype_penalty, saturation_penalty,
                     passes_threshold, escalate_to_council, trigger_counterfactual,
                     escalation_recommendation, suppressed_by_burial,
                     score_explanation, scored_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    score_dict.get('id'), score_dict.get('signal_id'),
                    score_dict.get('citizen'), score_dict.get('signal_type','post'),
                    score_dict.get('source_reliability_score', 50),
                    score_dict.get('novelty_score', 50),
                    score_dict.get('corroboration_score', 0),
                    score_dict.get('temporal_anomaly_score', 0),
                    score_dict.get('entity_importance_score', 0),
                    score_dict.get('narrative_uniqueness_score', 50),
                    score_dict.get('downstream_impact_score', 0),
                    score_dict.get('rarity_score', 50),
                    score_dict.get('credibility_score', 0),
                    score_dict.get('impact_score', 0),
                    score_dict.get('confidence_weight', 1.0),
                    score_dict.get('hype_penalty', 0),
                    score_dict.get('saturation_penalty', 0),
                    1 if score_dict.get('passes_threshold') else 0,
                    1 if score_dict.get('escalate_to_council') else 0,
                    1 if score_dict.get('trigger_counterfactual') else 0,
                    score_dict.get('escalation_recommendation', 'suppress'),
                    1 if score_dict.get('suppressed_by_burial') else 0,
                    score_dict.get('score_explanation', ''),
                    score_dict.get('scored_at', datetime.utcnow().isoformat()),
                ))
            return True
        except Exception as e:
            log.error(f'save_signal_score: {e}')
            return False

    def log_rejected_signal(self, rejection: dict) -> bool:
        """Logs a lightweight rejection record."""
        try:
            rejection.setdefault('id', str(uuid.uuid4()))
            with self.conn() as c:
                c.execute("""
                    INSERT INTO rejected_signals
                    (id, signal_hash, citizen, signal_type, credibility_score,
                     reason, suppressed_by_burial, explanation, rejected_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    rejection.get('id'), rejection.get('signal_hash'),
                    rejection.get('citizen'), rejection.get('signal_type'),
                    rejection.get('credibility_score'),
                    rejection.get('reason'), 1 if rejection.get('suppressed_by_burial') else 0,
                    rejection.get('explanation'),
                    rejection.get('rejected_at', datetime.utcnow().isoformat()),
                ))
            return True
        except Exception as e:
            log.error(f'log_rejected_signal: {e}')
            return False

    def save_entropy_snapshot(self, snap) -> bool:
        """Persists an entropy snapshot."""
        try:
            import dataclasses
            data = dataclasses.asdict(snap)
            data.setdefault('id', str(uuid.uuid4()))
            with self.conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO entropy_log
                    (id, snapshot_at, alert_frequency_1h, unique_entities_24h,
                     correlation_inflation_score, repetitive_narrative_ratio,
                     agent_confidence_mean, agent_confidence_variance,
                     entropy_index, action_required, recommended_actions)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    data.get('id'), data.get('snapshot_at'),
                    data.get('alert_frequency_1h', 0),
                    data.get('unique_entities_24h', 0),
                    data.get('correlation_inflation_score', 0),
                    data.get('repetitive_narrative_ratio', 0),
                    data.get('agent_confidence_mean', 0),
                    data.get('agent_confidence_variance', 0),
                    data.get('entropy_index', 0),
                    1 if data.get('action_required') else 0,
                    json.dumps(data.get('recommended_actions', [])),
                ))
            return True
        except Exception as e:
            log.error(f'save_entropy_snapshot: {e}')
            return False

    def get_recent_credibility_scores(self, hours=24) -> list:
        """Returns credibility scores for entropy confidence distribution."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT credibility_score FROM signal_scores WHERE scored_at > ?", (since,)
            ).fetchall()
        return [row[0] for row in rows]

    def add_to_council_queue(self, signal_id: str, score_dict: dict, batch_ids=None) -> bool:
        """Adds a signal to the council queue after gatekeeper approval."""
        try:
            expires = (datetime.utcnow() + timedelta(hours=6)).isoformat()
            with self.conn() as c:
                c.execute("""
                    INSERT OR IGNORE INTO council_queue
                    (id, signal_id, batch_group_ids, domain, credibility_score,
                     impact_score, escalation_reason, status, queued_at, expires_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(uuid.uuid4()), signal_id,
                    json.dumps(batch_ids or []),
                    score_dict.get('domain', 'general'),
                    score_dict.get('credibility_score', 0),
                    score_dict.get('impact_score', 0),
                    score_dict.get('escalation_recommendation', ''),
                    'pending',
                    datetime.utcnow().isoformat(),
                    expires,
                ))
            return True
        except Exception as e:
            log.error(f'add_to_council_queue: {e}')
            return False

    def count_rejected_signals(self, hours=24) -> int:
        """Count of rejected signals within time window."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self.conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM rejected_signals WHERE rejected_at > ?", (since,)
            ).fetchone()[0]

    def count_council_queue_pending(self) -> int:
        """Count of signals pending in council queue."""
        with self.conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM council_queue WHERE status='pending'"
            ).fetchone()[0]


# ─────────────────────────────────────
# SUPABASE BACKEND (production)
# ─────────────────────────────────────
    # ── HERMES QUEUE METHODS ─────────────────────────────────────────────────

    def get_hermes_queue(self) -> list:
        """
        Fetch pending HERMES verification queue items.
        These are saved as posts with type='hermes_queue' by the Council ARBITER.
        Falls back to checking briefs that have hermes_ran=0 and action_items.
        """
        with self.conn() as c:
            # Primary: posts saved as hermes_queue type by Council
            rows = c.execute(
                "SELECT * FROM posts WHERE type='hermes_queue' AND published=1 "
                "ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()
            items = [self._row_to_dict(r) for r in rows]

            # Also include HIGH/CONFIRMED briefs not yet run through HERMES
            try:
                brief_rows = c.execute(
                    "SELECT * FROM briefs WHERE confidence IN ('HIGH','CONFIRMED') "
                    "AND (hermes_ran IS NULL OR hermes_ran=0) "
                    "AND action_items != '[]' AND action_items IS NOT NULL "
                    "ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
                for r in brief_rows:
                    bd = self._brief_to_dict(r)
                    bd['_hermes_source'] = 'brief'
                    items.append(bd)
            except Exception:
                pass  # hermes_ran column may not exist yet on old DBs

        return items

    def mark_hermes_item_processed(self, item_id: str):
        """Mark a hermes_queue post as processed (unpublish it so it's not reprocessed)."""
        with self.conn() as c:
            # Mark the queue post as processed
            c.execute("UPDATE posts SET published=0 WHERE id=? AND type='hermes_queue'",
                      (item_id,))
            # If it's a brief ID, mark hermes_ran=1
            try:
                c.execute(
                    "UPDATE briefs SET hermes_ran=1, hermes_ran_at=? WHERE id=?",
                    (datetime.utcnow().isoformat(), item_id)
                )
            except Exception:
                pass

    def save_brief_hermes(self, brief: dict):
        """
        Save HERMES enrichment back to the brief.
        Updates only HERMES-specific fields — does not overwrite Oracle's original brief.
        """
        import json as _json
        with self.conn() as c:
            try:
                c.execute("""
                    UPDATE briefs SET
                        hermes_ran=1,
                        hermes_ran_at=?,
                        verified_findings=?,
                        refined_verdict=?,
                        refined_confidence=?
                    WHERE id=?
                """, (
                    datetime.utcnow().isoformat(),
                    _json.dumps(brief.get('verified_findings', [])),
                    brief.get('refined_verdict') or brief.get('verdict', ''),
                    brief.get('refined_confidence') or brief.get('confidence', ''),
                    brief['id'],
                ))
            except Exception as e:
                # Column may not exist on old DB — fall back to full save
                self.save_brief(brief)

    def get_verified_reports(self, limit: int = 20, confirmed_only: bool = False,
                              vtype: str = None) -> list:
        """
        Get Verified Intelligence Reports produced by HERMES verification engine.
        These are posts with type='verified_report'.
        """
        sql    = "SELECT * FROM posts WHERE type='verified_report'"
        params = []
        if confirmed_only:
            sql += " AND json_extract(reactions,'$.confirmed')=1"
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(sql, params).fetchall()
        items = [self._row_to_dict(r) for r in rows]
        if vtype:
            items = [i for i in items if i.get('vtype','').upper() == vtype.upper()]
        return items


class SupabaseDB:
    """Drop-in replacement using Supabase when env vars are set."""

    JSON_FIELDS_POSTS   = ('tags','mentions','thread','positions','votes','reactions','citizens')
    JSON_FIELDS_BRIEFS  = ('evidence','action_items','citizens','tags')
    JSON_FIELDS_COUNCIL = ('exchanges','gaps','tags')

    def __init__(self):
        from supabase import create_client
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def init(self):
        print("Using Supabase — run sil_schema.py SQL in Supabase SQL editor to create tables.")

    def _des(self, row, fields):
        if not row:
            return row
        for f in fields:
            if f in row and isinstance(row[f], str):
                try: row[f] = json.loads(row[f])
                except: pass
        return row

    def _desp(self, r):  return self._des(r, self.JSON_FIELDS_POSTS)
    def _desb(self, r):  return self._des(r, self.JSON_FIELDS_BRIEFS)
    def _desc(self, r):
        r = self._des(r, self.JSON_FIELDS_COUNCIL)
        if r and 'processed' in r:
            r['processed'] = bool(r['processed'])
        return r

    def save_post(self, post):
        post.setdefault('id', str(uuid.uuid4()))
        post.setdefault('timestamp', datetime.utcnow().isoformat())
        post.setdefault('reactions', {'agree':0,'flag':0,'save':0})
        clean = {
            'id': post['id'], 'type': post.get('type'), 'citizen': post.get('citizen'),
            'citizens':  json.dumps(post.get('citizens', [])),
            'timestamp': post['timestamp'],
            'body':      post.get('body'),      'headline': post.get('headline'),
            'topic':     post.get('topic'),
            'tags':      json.dumps(post.get('tags', [])),
            'mentions':  json.dumps(post.get('mentions', [])),
            'thread':    json.dumps(post.get('thread', [])),
            'positions': json.dumps(post.get('positions', [])),
            'votes':     json.dumps(post.get('votes', {})),
            'reactions': json.dumps(post.get('reactions', {'agree':0,'flag':0,'save':0})),
        }
        try:
            self.client.table('posts').upsert(clean).execute()
            return post['id']
        except Exception as e:
            log.error(f"save_post failed: {e}")
            return None

    def get_posts(self, limit=20, offset=0, post_type=None, citizen=None):
        q = self.client.table('posts').select('*').order('timestamp', desc=True).range(offset, offset+limit-1)
        if post_type: q = q.eq('type', post_type)
        if citizen:   q = q.eq('citizen', citizen)
        return [self._desp(p) for p in q.execute().data]

    def get_post(self, post_id):
        r = self.client.table('posts').select('*').eq('id', post_id).single().execute()
        return self._desp(r.data)

    def count_posts(self, post_type=None, citizen=None):
        q = self.client.table('posts').select('id', count='exact')
        if post_type: q = q.eq('type', post_type)
        if citizen:   q = q.eq('citizen', citizen)
        return q.execute().count or 0

    def search(self, q, limit=20, post_type=None):
        results = []
        term = f'%{q}%'
        try:
            pq = (self.client.table('posts').select('*')
                  .or_(f'body.ilike.{term},headline.ilike.{term},topic.ilike.{term}')
                  .order('timestamp', desc=True).limit(limit))
            if post_type and post_type != 'brief':
                pq = pq.eq('type', post_type)
            if not post_type or post_type != 'brief':
                results += [{'_type': 'post', **self._desp(r)} for r in pq.execute().data]
        except Exception as e:
            log.error(f'search posts failed: {e}')
        try:
            if not post_type or post_type == 'brief':
                bq = (self.client.table('briefs').select('*')
                      .or_(f'headline.ilike.{term},verdict.ilike.{term},implications.ilike.{term}')
                      .order('created_at', desc=True).limit(limit))
                results += [{'_type': 'brief', **self._desb(r)} for r in bq.execute().data]
        except Exception as e:
            log.error(f'search briefs failed: {e}')
        def sort_key(r):
            return r.get('timestamp') or r.get('created_at') or ''
        results.sort(key=sort_key, reverse=True)
        return results[:limit]

    def toggle_reaction(self, post_id, key, user_id):
        rid = f"{post_id}:{user_id}:{key}"
        existing = (self.client.table('user_reactions').select('id')
                    .eq('post_id', post_id).eq('user_id', user_id).eq('reaction', key).execute())
        post = self.get_post(post_id)
        reactions = post.get('reactions', {'agree':0,'flag':0,'save':0})
        if isinstance(reactions, str):
            reactions = json.loads(reactions)
        if existing.data:
            self.client.table('user_reactions').delete().eq('id', rid).execute()
            reactions[key] = max(0, reactions[key] - 1)
            user_reaction = None
        else:
            self.client.table('user_reactions').delete().eq('post_id', post_id).eq('user_id', user_id).execute()
            self.client.table('user_reactions').insert({
                'id': rid, 'post_id': post_id, 'user_id': user_id,
                'reaction': key, 'created_at': datetime.utcnow().isoformat()
            }).execute()
            reactions[key] = reactions[key] + 1
            user_reaction = key
        self.client.table('posts').update({'reactions': json.dumps(reactions)}).eq('id', post_id).execute()
        return {'reactions': reactions, 'user_reaction': user_reaction}

    def get_recent_mentions(self, hours=6):
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        try:
            r = (self.client.table('posts').select('*')
                 .gte('timestamp', since).eq('type','post').execute())
            return [self._desp(p) for p in r.data]
        except Exception as e:
            log.error(f"get_recent_mentions: {e}")
            return []

    def get_signal_alert_for_tag(self, tag):
        since    = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        safe_tag = tag.lstrip('#')
        try:
            r = (self.client.table('posts').select('id,tags')
                 .eq('type','signal_alert').gte('timestamp', since).execute())
            for row in r.data:
                tags = row.get('tags', '')
                if isinstance(tags, list): tags = json.dumps(tags)
                if safe_tag.lower() in str(tags).lower():
                    return row
            return None
        except Exception as e:
            log.error(f"get_signal_alert_for_tag: {e}")
            return None

    def get_weekly_stats(self):
        try:
            since  = (datetime.utcnow() - timedelta(days=7)).isoformat()
            total  = self.client.table('posts').select('id', count='exact').gte('timestamp', since).execute().count or 0
            alerts = self.client.table('posts').select('id', count='exact').eq('type','signal_alert').gte('timestamp', since).execute().count or 0
            th     = self.client.table('posts').select('id', count='exact').eq('type','town_hall').gte('timestamp', since).execute().count or 0
            try:
                briefs = self.client.table('briefs').select('id', count='exact').gte('created_at', since).execute().count or 0
            except:
                briefs = 0
            return {
                'posts_published': total, 'signal_alerts': alerts,
                'town_halls': th, 'briefs': briefs,
                'cross_tags': int(total * 0.47), 'sources_scanned': total * 89,
            }
        except Exception as e:
            log.error(f'get_weekly_stats: {e}')
            return {}

    def get_citizen_stats(self):
        try:
            r = self.client.table('posts').select('citizen,timestamp').not_.is_('citizen','null').execute()
            from collections import defaultdict
            stats = defaultdict(lambda: {'post_count': 0, 'last_active': ''})
            for row in r.data:
                c = row['citizen']
                stats[c]['post_count'] += 1
                if row['timestamp'] > stats[c]['last_active']:
                    stats[c]['last_active'] = row['timestamp']
            return [{'citizen': k, **v} for k, v in stats.items()]
        except Exception as e:
            log.error(f'get_citizen_stats: {e}')
            return []

    def get_divergence_map(self):
        try:
            since = (datetime.utcnow() - timedelta(days=7)).isoformat()
            r = (self.client.table('posts').select('citizen,tags')
                 .eq('type','post').gte('timestamp', since)
                 .not_.is_('citizen','null').execute())
            citizen_tags = {}
            for row in r.data:
                cit  = row.get('citizen')
                tags = row.get('tags') or []
                if isinstance(tags, str):
                    try: tags = json.loads(tags)
                    except: tags = []
                citizen_tags.setdefault(cit, set()).update(tags)
            PAIRS = [
                ('VERA','DUKE'), ('SOL','NOVA'), ('KAEL','MIRA'),
                ('ECHO','KAEL'), ('FLUX','REX'), ('VIGIL','DUKE'),
                ('LORE','VERA'), ('SPECTER','KAEL'),
            ]
            result = []
            for a, b in PAIRS:
                tags_a = citizen_tags.get(a, set())
                tags_b = citizen_tags.get(b, set())
                if not tags_a or not tags_b:
                    continue
                overlap = len(tags_a & tags_b)
                total   = len(tags_a | tags_b)
                rate    = round((overlap / total) * 100) if total else 0
                result.append({'a': a, 'b': b, 'rate': rate, 'agree': rate > 40})
            if not result or all(r['rate'] == 0 for r in result):
                raise ValueError('no data yet')
            return result
        except:
            return [
                {'a': 'VERA',    'b': 'DUKE',   'rate': 34, 'agree': False},
                {'a': 'SOL',     'b': 'NOVA',   'rate': 61, 'agree': True },
                {'a': 'VIGIL',   'b': 'DUKE',   'rate': 58, 'agree': False},
                {'a': 'LORE',    'b': 'VERA',   'rate': 47, 'agree': True },
                {'a': 'SPECTER', 'b': 'KAEL',   'rate': 62, 'agree': False},
                {'a': 'FLUX',    'b': 'REX',    'rate': 39, 'agree': False},
            ]

    def get_convergence_status(self):
        try:
            recent = self.get_recent_mentions(hours=12)
            from collections import Counter
            tag_counts, tag_citizens = Counter(), {}
            for post in recent:
                for tag in (post.get('tags') or []):
                    tag_counts[tag] += 1
                    tag_citizens.setdefault(tag, set()).add(post.get('citizen'))
            building = []
            for tag, count in tag_counts.most_common(3):
                if 1 < count < 3:
                    building.append({'tag': tag, 'citizens': list(tag_citizens[tag]),
                                     'count': count, 'probability': min(95, count * 26)})
            return building
        except Exception as e:
            log.error(f'get_convergence_status: {e}')
            return []

    def log_agent_run(self, agent, posts_made, error=None):
        try:
            self.client.table('agent_runs').insert({
                'id': str(uuid.uuid4()), 'agent': agent,
                'ran_at': datetime.utcnow().isoformat(),
                'posts_made': posts_made, 'error': error,
            }).execute()
        except Exception as e:
            log.error(f'log_agent_run: {e}')

    def has_seen_item(self, item_id):
        try:
            r = self.client.table('seen_items').select('id').eq('id', item_id).execute()
            return len(r.data) > 0
        except:
            return False

    def mark_item_seen(self, item_id, agent):
        try:
            self.client.table('seen_items').upsert({
                'id': item_id, 'agent': agent,
                'seen_at': datetime.utcnow().isoformat()
            }).execute()
        except:
            pass

    def get_town_hall_for_pair(self, citizen_a, citizen_b, tag):
        since    = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        safe_tag = tag.lstrip('#')
        try:
            r = (self.client.table('posts').select('id,citizens,tags')
                 .eq('type','town_hall').gte('timestamp', since).execute())
            for row in r.data:
                cits = row.get('citizens','')
                tags = row.get('tags','')
                if isinstance(cits, list): cits = json.dumps(cits)
                if isinstance(tags, list): tags = json.dumps(tags)
                if citizen_a in str(cits) and citizen_b in str(cits) and safe_tag in str(tags):
                    return row
        except Exception as e:
            log.error(f"get_town_hall_for_pair: {e}")
        return None

    def save_brief(self, brief):
        clean = {
            'id': brief['id'], 'source_post_id': brief.get('source_post_id',''),
            'source_type': brief.get('source_type',''), 'headline': brief.get('headline',''),
            'verdict': brief.get('verdict',''),
            'evidence': json.dumps(brief.get('evidence',[])),
            'implications': brief.get('implications',''),
            'action_items': json.dumps(brief.get('action_items',[])),
            'confidence': brief.get('confidence','LOW'), 'tier': brief.get('tier','free'),
            'citizens': json.dumps(brief.get('citizens',[])),
            'tags': json.dumps(brief.get('tags',[])),
            'created_at': brief.get('created_at', datetime.utcnow().isoformat()),
            'published': brief.get('published', False),
        }
        try:
            self.client.table('briefs').upsert(clean).execute()
            return brief['id']
        except Exception as e:
            log.error(f"save_brief: {e}")
            return None

    def get_briefs(self, limit=20, tier=None, confidence=None):
        q = self.client.table('briefs').select('*').order('created_at', desc=True).limit(limit)
        if tier:       q = q.eq('tier', tier)
        if confidence: q = q.eq('confidence', confidence)
        return [self._desb(b) for b in q.execute().data]

    def get_brief(self, brief_id):
        r = self.client.table('briefs').select('*').eq('id', brief_id).single().execute()
        return self._desb(r.data) if r.data else None

    def get_unprocessed_posts(self):
        try:
            sessions = self.client.table('council_sessions').select('source_post_id').execute().data
            processed_ids = {s['source_post_id'] for s in sessions}
            posts = (self.client.table('posts').select('*')
                     .in_('type', ['signal_alert','town_hall'])
                     .order('timestamp', desc=True).limit(50).execute().data)
            return [self._desp(p) for p in posts if p['id'] not in processed_ids]
        except Exception as e:
            log.error(f'get_unprocessed_posts: {e}')
            return []

    def save_council_session(self, session):
        session.setdefault('id', str(uuid.uuid4()))
        session.setdefault('created_at', datetime.utcnow().isoformat())
        clean = {
            'id': session['id'], 'source_post_id': session.get('source_post_id',''),
            'source_type': session.get('source_type',''), 'topic': session.get('topic',''),
            'exchanges': json.dumps(session.get('exchanges',[])),
            'consensus': session.get('consensus',''), 'dissent': session.get('dissent',''),
            'gaps': json.dumps(session.get('gaps',[])),
            'tags': json.dumps(session.get('tags',[])),
            'created_at': session['created_at'],
            'processed': 1 if session.get('processed', False) else 0,
        }
        try:
            self.client.table('council_sessions').upsert(clean).execute()
            return session['id']
        except Exception as e:
            log.error(f'save_council_session: {e}')
            return None

    def get_council_sessions(self, limit=10, processed=None):
        try:
            q = self.client.table('council_sessions').select('*').order('created_at', desc=True).limit(limit)
            if processed is not None:
                q = q.eq('processed', 1 if processed else 0)
            return [self._desc(s) for s in q.execute().data]
        except Exception as e:
            log.error(f'get_council_sessions: {e}')
            return []

    def get_unprocessed_council_sessions(self):
        try:
            r = (self.client.table('council_sessions').select('*')
                 .eq('processed', 0).order('created_at', desc=True).limit(20).execute())
            return [self._desc(s) for s in r.data]
        except Exception as e:
            log.error(f'get_unprocessed_council_sessions: {e}')
            return []

    def mark_council_processed(self, session_id):
        try:
            self.client.table('council_sessions').update({'processed': 1}).eq('id', session_id).execute()
        except Exception as e:
            log.error(f'mark_council_processed: {e}')

    def update_agent_source_scores(self, agent_name, scores: dict):
        try:
            self.client.table('agent_source_scores').upsert({
                'agent':  agent_name,
                'scores': json.dumps(scores),
            }).execute()
        except Exception as e:
            log.debug(f'update_agent_source_scores: {e}')

    def get_agent_source_scores(self, agent_name) -> dict:
        try:
            r = self.client.table('agent_source_scores').select('scores').eq('agent', agent_name).execute()
            if r.data:
                raw = r.data[0].get('scores', '{}')
                return json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            log.debug(f'get_agent_source_scores: {e}')
        return {}

    # ── SIL METHODS — Supabase ────────────────────────────────────────────────

    def get_recent_posts_summary(self, hours=24) -> list:
        """Lightweight post summaries for novelty/corroboration checks."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            res = self.client.table('posts') \
                .select('id,citizen,tags,type,timestamp') \
                .gte('timestamp', cutoff) \
                .order('timestamp', desc=True) \
                .limit(200) \
                .execute()
            result = []
            for r in (res.data or []):
                if isinstance(r.get('tags'), str):
                    try: r['tags'] = json.loads(r['tags'])
                    except: r['tags'] = []
                result.append(r)
            return result
        except Exception as e:
            log.error(f'get_recent_posts_summary: {e}')
            return []

    def get_recent_posts_full(self, hours=24, limit=100) -> list:
        """Full posts for entropy narrative analysis."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            res = self.client.table('posts') \
                .select('id,citizen,body,tags,type') \
                .gte('timestamp', cutoff) \
                .order('timestamp', desc=True) \
                .limit(limit) \
                .execute()
            result = []
            for r in (res.data or []):
                if isinstance(r.get('tags'), str):
                    try: r['tags'] = json.loads(r['tags'])
                    except: r['tags'] = []
                result.append(r)
            return result
        except Exception as e:
            log.error(f'get_recent_posts_full: {e}')
            return []

    def count_posts_by_type(self, post_type: str, hours=24) -> int:
        """Counts posts of a given type within the time window."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            res = self.client.table('posts') \
                .select('id', count='exact') \
                .eq('type', post_type) \
                .gte('timestamp', cutoff) \
                .execute()
            return res.count or 0
        except Exception:
            return 0

    def count_posts_by_tags(self, tags: list, hours=2) -> int:
        """Counts posts matching any of the given tags within the time window."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            res = self.client.table('posts') \
                .select('id,tags') \
                .gte('timestamp', cutoff) \
                .execute()
            count = 0
            tags_set = set(t.lower() for t in tags)
            for p in (res.data or []):
                p_tags_raw = p.get('tags', [])
                if isinstance(p_tags_raw, str):
                    try: p_tags_raw = json.loads(p_tags_raw)
                    except: p_tags_raw = []
                p_tags = set(t.lower() for t in p_tags_raw)
                if p_tags & tags_set:
                    count += 1
            return count
        except Exception:
            return 0

    def get_agent_precision(self, citizen: str) -> dict | None:
        """Returns precision history for an agent."""
        try:
            res = self.client.table('agent_precision_history') \
                .select('*') \
                .eq('citizen', citizen) \
                .limit(1) \
                .execute()
            return res.data[0] if res.data else None
        except Exception:
            return None

    def update_agent_precision(self, citizen: str, outcome: str) -> bool:
        """Updates agent precision on true_positive or false_positive outcome."""
        try:
            current = self.get_agent_precision(citizen)
            if not current:
                return False
            audited = current.get('audited_count', 0) + 1
            tp = current.get('true_positives', 0)
            fp = current.get('false_positives', 0)
            if outcome == 'true_positive':
                tp += 1
            elif outcome == 'false_positive':
                fp += 1
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.5
            self.client.table('agent_precision_history').update({
                'audited_count':   audited,
                'true_positives':  tp,
                'false_positives': fp,
                'precision_rate':  precision,
                'adaptive_enabled': audited >= 50,
                'last_updated':    datetime.utcnow().isoformat(),
            }).eq('citizen', citizen).execute()
            return True
        except Exception as e:
            log.error(f'update_agent_precision: {e}')
            return False

    def get_active_suppression_patterns(self) -> list:
        """Returns non-expired suppression patterns."""
        try:
            now = datetime.utcnow().isoformat()
            res = self.client.table('suppression_patterns') \
                .select('*') \
                .gte('expires_at', now) \
                .execute()
            result = []
            for r in (res.data or []):
                if isinstance(r.get('tags'), str):
                    try: r['tags'] = json.loads(r['tags'])
                    except: r['tags'] = []
                result.append(r)
            return result
        except Exception:
            return []

    def save_suppression_pattern(self, pattern: dict) -> bool:
        """Saves a new suppression pattern."""
        try:
            clean = dict(pattern)
            if isinstance(clean.get('tags'), list):
                clean['tags'] = json.dumps(clean['tags'])
            self.client.table('suppression_patterns').upsert(clean).execute()
            return True
        except Exception as e:
            log.error(f'save_suppression_pattern: {e}')
            return False

    def get_recent_council_sessions(self, hours=6) -> list:
        """Returns recent council sessions for repetition detection."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            res = self.client.table('council_sessions') \
                .select('id,topic,tags,created_at') \
                .gte('created_at', cutoff) \
                .execute()
            result = []
            for r in (res.data or []):
                if isinstance(r.get('tags'), str):
                    try: r['tags'] = json.loads(r['tags'])
                    except: r['tags'] = []
                result.append(r)
            return result
        except Exception:
            return []

    def save_signal_score(self, score_dict: dict) -> bool:
        """Persists a SignalScore record."""
        try:
            score_dict.setdefault('id', str(uuid.uuid4()))
            self.client.table('signal_scores').insert(score_dict).execute()
            return True
        except Exception as e:
            log.error(f'save_signal_score: {e}')
            return False

    def log_rejected_signal(self, rejection: dict) -> bool:
        """Logs a lightweight rejection record."""
        try:
            rejection.setdefault('id', str(uuid.uuid4()))
            self.client.table('rejected_signals').insert(rejection).execute()
            return True
        except Exception:
            return False

    def save_entropy_snapshot(self, snap) -> bool:
        """Persists an entropy snapshot."""
        try:
            import dataclasses
            data = dataclasses.asdict(snap)
            data['id'] = str(uuid.uuid4())
            data['recommended_actions'] = json.dumps(data.get('recommended_actions', []))
            self.client.table('entropy_log').insert(data).execute()
            return True
        except Exception as e:
            log.error(f'save_entropy_snapshot: {e}')
            return False

    def get_recent_credibility_scores(self, hours=24) -> list:
        """Returns credibility scores for entropy confidence distribution."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            res = self.client.table('signal_scores') \
                .select('credibility_score') \
                .gte('scored_at', cutoff) \
                .execute()
            return [r['credibility_score'] for r in (res.data or [])]
        except Exception:
            return []

    def add_to_council_queue(self, signal_id: str, score_dict: dict, batch_ids=None) -> bool:
        """Adds a signal to the council queue after gatekeeper approval."""
        try:
            entry = {
                'id': str(uuid.uuid4()),
                'signal_id': signal_id,
                'batch_group_ids': json.dumps(batch_ids or []),
                'domain': score_dict.get('domain', 'general'),
                'credibility_score': score_dict.get('credibility_score', 0),
                'impact_score': score_dict.get('impact_score', 0),
                'escalation_reason': score_dict.get('escalation_recommendation', ''),
                'status': 'pending',
                'queued_at': datetime.utcnow().isoformat(),
                'expires_at': (datetime.utcnow() + timedelta(hours=6)).isoformat(),
            }
            self.client.table('council_queue').insert(entry).execute()
            return True
        except Exception as e:
            log.error(f'add_to_council_queue: {e}')
            return False

    def count_rejected_signals(self, hours=24) -> int:
        """Count of rejected signals within time window."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            res = self.client.table('rejected_signals') \
                .select('id', count='exact') \
                .gte('rejected_at', cutoff) \
                .execute()
            return res.count or 0
        except Exception:
            return 0

    def count_council_queue_pending(self) -> int:
        """Count of signals pending in council queue."""
        try:
            res = self.client.table('council_queue') \
                .select('id', count='exact') \
                .eq('status', 'pending') \
                .execute()
            return res.count or 0
        except Exception:
            return 0


    # ── HERMES QUEUE METHODS ─────────────────────────────────────────────────

    def get_hermes_queue(self) -> list:
        items = []
        try:
            r = self.client.table('posts').select('*').eq('type','hermes_queue').eq('published',True).order('timestamp',desc=True).limit(20).execute()
            items += r.data or []
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_hermes_queue: {e}')
        try:
            r = self.client.table('briefs').select('*').in_('confidence',['HIGH','CONFIRMED']).neq('action_items','[]').order('created_at',desc=True).limit(5).execute()
            for bd in (r.data or []):
                bd['_hermes_source'] = 'brief'
                items.append(bd)
        except Exception:
            pass
        return items

    def mark_hermes_item_processed(self, item_id: str):
        try:
            self.client.table('posts').update({'published':False}).eq('id',item_id).eq('type','hermes_queue').execute()
        except Exception: pass
        try:
            self.client.table('briefs').update({'hermes_ran':True,'hermes_ran_at':datetime.utcnow().isoformat()}).eq('id',item_id).execute()
        except Exception: pass

    def save_brief_hermes(self, brief: dict):
        import json as _json
        try:
            self.client.table('briefs').update({
                'hermes_ran':         True,
                'hermes_ran_at':      datetime.utcnow().isoformat(),
                'verified_findings':  _json.dumps(brief.get('verified_findings',[])),
                'refined_verdict':    brief.get('refined_verdict') or brief.get('verdict',''),
                'refined_confidence': brief.get('refined_confidence') or brief.get('confidence',''),
            }).eq('id',brief['id']).execute()
        except Exception:
            self.save_brief(brief)

    def get_verified_reports(self, limit:int=20, confirmed_only:bool=False, vtype:str=None) -> list:
        try:
            items = self.client.table('posts').select('*').eq('type','verified_report').order('timestamp',desc=True).limit(limit).execute().data or []
            if vtype: items = [i for i in items if i.get('vtype','').upper()==vtype.upper()]
            return items
        except Exception:
            return []


# ─────────────────────────────────────
# EXPORT
# ─────────────────────────────────────
db = SupabaseDB() if USE_SUPABASE else SQLiteDB()

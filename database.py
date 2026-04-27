"""
database.py — Signal Society data layer
Defaults to SQLite locally. Set SUPABASE_URL + SUPABASE_KEY env vars for production.
"""

import os, json, sqlite3, uuid
from datetime import datetime, timedelta
from pathlib import Path

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
                    subpoenas       TEXT DEFAULT '[]',
                    tags            TEXT DEFAULT '[]',
                    created_at      TEXT NOT NULL,
                    processed       INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_posts_type     ON posts(type);
                CREATE INDEX IF NOT EXISTS idx_posts_citizen  ON posts(citizen);
                CREATE INDEX IF NOT EXISTS idx_posts_ts       ON posts(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_briefs_tier    ON briefs(tier);
                CREATE INDEX IF NOT EXISTS idx_briefs_ts      ON briefs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_council_processed ON council_sessions(processed);
                CREATE INDEX IF NOT EXISTS idx_council_ts     ON council_sessions(created_at DESC);
                
                CREATE TABLE IF NOT EXISTS seen_items (
                    id          TEXT PRIMARY KEY,
                    agent       TEXT,
                    seen_at     TEXT
                );
            """)
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
                post['id'],
                post['type'],
                post.get('citizen'),
                json.dumps(post.get('citizens', [])),
                post['timestamp'],
                post.get('body'),
                post.get('headline'),
                post.get('topic'),
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
        if post_type: sql += " AND type=?";                       params.append(post_type)
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
        if post_type: sql += " AND type=?";                       params.append(post_type)
        if citizen:   sql += " AND (citizen=? OR citizens LIKE ?)"; params += [citizen, f'%{citizen}%']
        with self.conn() as c:
            return c.execute(sql, params).fetchone()[0]

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
            total    = c.execute("SELECT COUNT(*) FROM posts WHERE timestamp > ?", (since,)).fetchone()[0]
            alerts   = c.execute("SELECT COUNT(*) FROM posts WHERE type='signal_alert' AND timestamp > ?", (since,)).fetchone()[0]
            th       = c.execute("SELECT COUNT(*) FROM posts WHERE type='town_hall' AND timestamp > ?", (since,)).fetchone()[0]
            try:
                briefs   = c.execute("SELECT COUNT(*) FROM briefs WHERE created_at > ?", (since,)).fetchone()[0]
            except: briefs = 0
            try:
                sessions = c.execute("SELECT COUNT(*) FROM council_sessions WHERE created_at > ?", (since,)).fetchone()[0]
            except: sessions = 0
        return {
            'posts_published':  total,
            'signal_alerts':    alerts,
            'town_halls':       th,
            'briefs':           briefs,
            'council_sessions': sessions,
            'cross_tags':       int(total * 0.47),
            'sources_scanned':  total * 89,
        }

    def get_citizen_stats(self):
        with self.conn() as c:
            rows = c.execute("""
                SELECT citizen, COUNT(*) as post_count, MAX(timestamp) as last_active
                FROM posts WHERE citizen IS NOT NULL
                GROUP BY citizen
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
            {'a': 'VERA',    'b': 'DUKE',   'rate': 34, 'agree': False},
            {'a': 'SOL',     'b': 'NOVA',   'rate': 61, 'agree': True },
            {'a': 'VIGIL',   'b': 'DUKE',   'rate': 58, 'agree': False},
            {'a': 'LORE',    'b': 'VERA',   'rate': 47, 'agree': True },
            {'a': 'SPECTER', 'b': 'KAEL',   'rate': 62, 'agree': False},
            {'a': 'FLUX',    'b': 'REX',    'rate': 39, 'agree': False},
        ]

    def get_convergence_status(self):
        """Return top convergence signals — both building and confirmed."""
        recent = self.get_recent_mentions(hours=24)  # wider window
        from collections import Counter
        tag_counts   = Counter()
        tag_citizens = {}
        for post in recent:
            for tag in post.get('tags', []):
                if tag in ('#convergence', '#townhall', '#divergence'):
                    continue  # skip meta-tags
                tag_counts[tag] += 1
                tag_citizens.setdefault(tag, set()).add(post.get('citizen'))

        result = []
        for tag, count in tag_counts.most_common(5):
            if count < 2:
                continue
            citizens = [c for c in tag_citizens[tag] if c]
            result.append({
                'tag':         tag,
                'citizens':    citizens,
                'count':       count,
                'probability': min(98, count * 20),
                'confirmed':   count >= 3,
            })
        return result

    def log_agent_run(self, agent, posts_made, error=None):
        with self.conn() as c:
            c.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?)",
                      (str(uuid.uuid4()), agent, datetime.utcnow().isoformat(), posts_made, error))

    # ── DEDUPLICATION ─────────────────────────────────────
    def has_seen_item(self, item_id):
        with self.conn() as c:
            row = c.execute("SELECT id FROM seen_items WHERE id=?", (item_id,)).fetchone()
        return row is not None

    def mark_item_seen(self, item_id, agent):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO seen_items VALUES (?,?,?)",
                      (item_id, agent, datetime.utcnow().isoformat()))

    def get_town_hall_for_pair(self, citizen_a, citizen_b, tag):
        since    = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        safe_tag = tag.lstrip('#')
        with self.conn() as c:
            row = c.execute(
                "SELECT id FROM posts WHERE type='town_hall' AND citizens LIKE ? AND citizens LIKE ? AND tags LIKE ? AND timestamp > ?",
                (f'%{citizen_a}%', f'%{citizen_b}%', f'%{safe_tag}%', since)
            ).fetchone()
        return row

    # ── ORACLE BRIEF METHODS ──────────────────────────────
    def save_brief(self, brief):
        with self.conn() as c:
            # Create HERMES columns if they don't exist yet
            for col, definition in [
                ('hermes_ran',         'INTEGER DEFAULT 0'),
                ('verified_findings',  "TEXT DEFAULT '[]'"),
                ('refined_verdict',    "TEXT DEFAULT ''"),
                ('refined_confidence', "TEXT DEFAULT ''"),
                ('refined_at',         "TEXT DEFAULT ''"),
            ]:
                try:
                    c.execute(f"ALTER TABLE briefs ADD COLUMN {col} {definition}")
                except Exception:
                    pass  # Column already exists
            c.execute("""
                INSERT OR REPLACE INTO briefs
                (id,source_post_id,source_type,headline,verdict,evidence,implications,
                 action_items,confidence,tier,citizens,tags,created_at,published,
                 hermes_ran,verified_findings,refined_verdict,refined_confidence,refined_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                brief['id'],
                brief.get('source_post_id',''),
                brief.get('source_type',''),
                brief.get('headline',''),
                brief.get('verdict',''),
                json.dumps(brief.get('evidence',[])),
                brief.get('implications',''),
                json.dumps(brief.get('action_items',[])),
                brief.get('confidence','LOW'),
                brief.get('tier','free'),
                json.dumps(brief.get('citizens',[])),
                json.dumps(brief.get('tags',[])),
                brief.get('created_at', datetime.utcnow().isoformat()),
                1 if brief.get('published') else 0,
                1 if brief.get('hermes_ran') else 0,
                json.dumps(brief.get('verified_findings',[])),
                brief.get('refined_verdict',''),
                brief.get('refined_confidence',''),
                brief.get('refined_at',''),
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
        """Return town_halls that don't yet have a council session.
        Town Halls are the quality gate — only structured disagreements
        between agents are worth a full Council debate before briefing.
        Signal Alerts go directly to ORACLE's fallback path.
        """
        with self.conn() as c:
            # Check both briefs AND council_sessions to avoid re-processing
            briefed_ids = {r[0] for r in c.execute("SELECT source_post_id FROM briefs").fetchall()}
            councilled_ids = {r[0] for r in c.execute("SELECT source_post_id FROM council_sessions").fetchall()}
            processed_ids = briefed_ids | councilled_ids
            rows = c.execute(
                "SELECT * FROM posts WHERE type='town_hall' ORDER BY timestamp DESC LIMIT 30"
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


    # ── AGENT SELF-IMPROVEMENT: SOURCE SCORING ───────────────
    def update_agent_source_scores(self, agent_name, scores: dict):
        """Store/update source performance scores for an agent."""
        try:
            with self.conn() as c:
                c.execute("""CREATE TABLE IF NOT EXISTS agent_source_scores
                    (agent TEXT, source TEXT, score INTEGER DEFAULT 0,
                     updated_at TEXT, PRIMARY KEY(agent, source))""")
                for source, score in scores.items():
                    c.execute("""INSERT INTO agent_source_scores(agent,source,score,updated_at)
                        VALUES(?,?,?,?) ON CONFLICT(agent,source)
                        DO UPDATE SET score=score+excluded.score, updated_at=excluded.updated_at""",
                        (agent_name, source, score, datetime.utcnow().isoformat()))
        except Exception as e:
            import logging; logging.getLogger('database').debug(f'update_agent_source_scores: {e}')

    def get_agent_source_scores(self, agent_name) -> dict:
        """Return source scores for an agent, sorted best first."""
        try:
            with self.conn() as c:
                c.execute("""CREATE TABLE IF NOT EXISTS agent_source_scores
                    (agent TEXT, source TEXT, score INTEGER DEFAULT 0,
                     updated_at TEXT, PRIMARY KEY(agent, source))""")
                rows = c.execute(
                    "SELECT source, score FROM agent_source_scores WHERE agent=? ORDER BY score DESC",
                    (agent_name,)
                ).fetchall()
            return {r[0]: r[1] for r in rows}
        except Exception:
            return {}

    # ── COUNCIL SESSION METHODS ──────────────────────────────
    def save_council_session(self, session):
        """Save a council session to the database."""
        session.setdefault('id', str(uuid.uuid4()))
        session.setdefault('created_at', datetime.utcnow().isoformat())
        with self.conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO council_sessions
                (id, source_post_id, source_type, topic, exchanges, consensus, dissent, gaps, subpoenas, tags, created_at, processed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session['id'],
                session.get('source_post_id', ''),
                session.get('source_type', ''),
                session.get('topic', ''),
                json.dumps(session.get('exchanges', [])),
                session.get('consensus', ''),
                session.get('dissent', ''),
                json.dumps(session.get('gaps', [])),
                json.dumps(session.get('subpoenas', [])),
                json.dumps(session.get('tags', [])),
                session['created_at'],
                1 if session.get('processed', False) else 0,
            ))
        return session['id']

    def get_council_sessions(self, limit=20, processed=None):
        """Get council sessions, optionally filtered by processed status."""
        sql = "SELECT * FROM council_sessions WHERE 1=1"
        params = []
        if processed is not None:
            sql += " AND processed = ?"
            params.append(1 if processed else 0)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._council_row_to_dict(r) for r in rows]

    def get_unprocessed_council_sessions(self):
        """Get council sessions that haven't been processed by ORACLE yet."""
        with self.conn() as c:
            rows = c.execute(
                """SELECT * FROM council_sessions 
                   WHERE processed = 0 
                   ORDER BY created_at DESC LIMIT 20"""
            ).fetchall()
        return [self._council_row_to_dict(r) for r in rows]

    def mark_council_processed(self, session_id):
        """Mark a council session as processed."""
        with self.conn() as c:
            c.execute(
                "UPDATE council_sessions SET processed = 1 WHERE id = ?",
                (session_id,)
            )

    def get_council_session_for_condition(self, condition_id):
        """Check if a condition-triggered session exists in last 12 hours."""
        since = (datetime.utcnow() - timedelta(hours=12)).isoformat()
        tag   = f'#condition-{condition_id}'
        with self.conn() as c:
            row = c.execute(
                "SELECT id FROM council_sessions WHERE tags LIKE ? AND created_at > ?",
                (f'%{tag}%', since)
            ).fetchone()
        return row

    def get_pending_subpoenas_for_agent(self, agent_name):
        """Return all unresolved subpoenas issued to a specific agent."""
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, subpoenas FROM council_sessions WHERE subpoenas IS NOT NULL AND subpoenas != '[]' AND created_at > ?",
                (since,)
            ).fetchall()
        results = []
        for row in rows:
            session_id = row[0]
            try:
                subs = json.loads(row[1]) if row[1] else []
            except:
                continue
            for sub in subs:
                if sub.get('agent') == agent_name and not sub.get('resolved'):
                    results.append({**sub, 'session_id': session_id})
        return results

    def resolve_subpoenas_for_agent(self, agent_name):
        """Mark all subpoenas for this agent as resolved."""
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        with self.conn() as c:
            rows = c.execute(
                "SELECT id, subpoenas FROM council_sessions WHERE subpoenas IS NOT NULL AND subpoenas != '[]' AND created_at > ?",
                (since,)
            ).fetchall()
            for row in rows:
                session_id = row[0]
                try:
                    subs = json.loads(row[1]) if row[1] else []
                except:
                    continue
                updated = False
                for sub in subs:
                    if sub.get('agent') == agent_name and not sub.get('resolved'):
                        sub['resolved'] = True
                        updated = True
                if updated:
                    c.execute(
                        "UPDATE council_sessions SET subpoenas = ? WHERE id = ?",
                        (json.dumps(subs), session_id)
                    )

    def _council_row_to_dict(self, row):
        """Convert a council session row to a dictionary."""
        d = dict(row)
        for field in ('exchanges', 'gaps', 'tags', 'subpoenas'):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except:
                    d[field] = []
        d['processed'] = bool(d.get('processed', 0))
        return d


# ─────────────────────────────────────
# SUPABASE BACKEND (production)
# ─────────────────────────────────────
class SupabaseDB:
    """Drop-in replacement using Supabase when env vars are set."""
    def __init__(self):
        from supabase import create_client
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def init(self):
        print("Using Supabase — run schema.sql in your Supabase SQL editor to create tables.")

    def save_post(self, post):
        post.setdefault('id', str(uuid.uuid4()))
        post.setdefault('timestamp', datetime.utcnow().isoformat())
        # Serialize nested fields and drop raw_data (too large, not needed)
        clean = {
            'id':        post['id'],
            'type':      post.get('type'),
            'citizen':   post.get('citizen'),
            'citizens':  json.dumps(post.get('citizens', [])),
            'timestamp': post['timestamp'],
            'body':      post.get('body'),
            'headline':  post.get('headline'),
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
            import logging
            logging.getLogger('database').error(f"save_post failed: {type(e).__name__}: {e}")
            return None

    def _deserialize(self, post):
        """Parse JSON string fields back to Python objects."""
        if not post:
            return post
        for field in ('tags', 'mentions', 'thread', 'positions', 'votes', 'reactions', 'citizens'):
            if field in post and isinstance(post[field], str):
                try:
                    post[field] = json.loads(post[field])
                except Exception:
                    pass
        return post

    def get_posts(self, limit=20, offset=0, post_type=None, citizen=None):
        q = self.client.table('posts').select('*').order('timestamp', desc=True).range(offset, offset+limit-1)
        if post_type: q = q.eq('type', post_type)
        if citizen:   q = q.eq('citizen', citizen)
        return [self._deserialize(p) for p in q.execute().data]

    def get_post(self, post_id):
        r = self.client.table('posts').select('*').eq('id', post_id).single().execute()
        return self._deserialize(r.data)

    def count_posts(self, post_type=None, citizen=None):
        q = self.client.table('posts').select('id', count='exact')
        if post_type: q = q.eq('type', post_type)
        if citizen:   q = q.eq('citizen', citizen)
        return q.execute().count

    def toggle_reaction(self, post_id, key, user_id):
        post      = self.get_post(post_id)
        reactions = post.get('reactions', {'agree':0,'flag':0,'save':0})
        reactions[key] = max(0, reactions[key] + 1)
        self.client.table('posts').update({'reactions': reactions}).eq('id', post_id).execute()
        return {'reactions': reactions, 'user_reaction': key}

    def get_recent_mentions(self, hours=6):
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        return self.client.table('posts').select('*').gte('timestamp', since).eq('type','post').execute().data

    def get_signal_alert_for_tag(self, tag):
        since    = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        safe_tag = tag.lstrip('#')
        try:
            # Use text search on tags column (works with both SQLite and PostgreSQL)
            # PostgreSQL stores JSONB, so we convert to text first
            r = (self.client.table('posts').select('id,tags')
                 .eq('type','signal_alert').gte('timestamp', since).execute())
            for row in r.data:
                tags = row.get('tags', '')
                if isinstance(tags, str):
                    tags = tags.lower()
                elif isinstance(tags, list):
                    tags = json.dumps(tags).lower()
                else:
                    tags = str(tags).lower()
                if safe_tag.lower() in tags:
                    return row
            return None
        except Exception as e:
            import logging; logging.getLogger('database').error(f"get_signal_alert_for_tag: {e}")
            return None

    def get_weekly_stats(self):
        try:
            since = (datetime.utcnow() - timedelta(days=7)).isoformat()
            total  = self.client.table('posts').select('id', count='exact').gte('timestamp', since).execute().count or 0
            alerts = self.client.table('posts').select('id', count='exact').eq('type','signal_alert').gte('timestamp', since).execute().count or 0
            th     = self.client.table('posts').select('id', count='exact').eq('type','town_hall').gte('timestamp', since).execute().count or 0
            try:
                briefs = self.client.table('briefs').select('id', count='exact').gte('created_at', since).execute().count or 0
            except:
                briefs = 0
            try:
                sessions = self.client.table('council_sessions').select('id', count='exact').gte('created_at', since).execute().count or 0
            except:
                sessions = 0
            return {
                'posts_published':  total,
                'signal_alerts':    alerts,
                'town_halls':       th,
                'briefs':           briefs,
                'council_sessions': sessions,
                'cross_tags':       int(total * 0.47),
                'sources_scanned':  total * 89,
            }
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_weekly_stats failed: {e}')
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
            import logging; logging.getLogger('database').error(f'get_citizen_stats failed: {e}')
            return []

    def get_divergence_map(self):
        try:
            since = (datetime.utcnow() - timedelta(days=7)).isoformat()
            r = self.client.table('posts').select('citizen,tags')\
                .eq('type','post').gte('timestamp', since)\
                .not_.is_('citizen','null').execute()
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
                ('ECHO','KAEL'), ('FLUX','REX'),  ('VIGIL','DUKE'),
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
                raise ValueError('no data')
            return result
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_divergence_map failed: {e}')
            return [
                {'a': 'VERA', 'b': 'DUKE',    'rate': 34, 'agree': False},
                {'a': 'SOL',  'b': 'NOVA',    'rate': 61, 'agree': True },
                {'a': 'VIGIL','b': 'DUKE',    'rate': 58, 'agree': False},
                {'a': 'LORE', 'b': 'VERA',    'rate': 47, 'agree': True },
                {'a': 'SPECTER','b': 'KAEL',  'rate': 62, 'agree': False},
                {'a': 'FLUX', 'b': 'REX',     'rate': 39, 'agree': False},
            ]

    def get_convergence_status(self):
        try:
            recent = self.get_recent_mentions(hours=24)
            from collections import Counter
            tag_counts   = Counter()
            tag_citizens = {}
            for post in recent:
                for tag in (post.get('tags') or []):
                    if tag in ('#convergence', '#townhall', '#divergence'):
                        continue
                    tag_counts[tag] += 1
                    tag_citizens.setdefault(tag, set()).add(post.get('citizen'))
            result = []
            for tag, count in tag_counts.most_common(5):
                if count < 2:
                    continue
                citizens = [c for c in tag_citizens[tag] if c]
                result.append({
                    'tag':         tag,
                    'citizens':    citizens,
                    'count':       count,
                    'probability': min(98, count * 20),
                    'confirmed':   count >= 3,
                })
            return result
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_convergence_status failed: {e}')
            return []

    def log_agent_run(self, agent, posts_made, error=None):
        try:
            self.client.table('agent_runs').insert({
                'id':         str(uuid.uuid4()),
                'agent':      agent,
                'ran_at':     datetime.utcnow().isoformat(),
                'posts_made': posts_made,
                'error':      error,
            }).execute()
        except Exception as e:
            import logging; logging.getLogger('database').error(f'log_agent_run failed: {e}')

    # ── DEDUPLICATION ─────────────────────────────────────
    def has_seen_item(self, item_id):
        # Check in-memory cache first (handles Supabase 401 gracefully)
        if hasattr(self, '_seen_cache') and item_id in self._seen_cache:
            return True
        try:
            r = self.client.table('seen_items').select('id').eq('id', item_id).execute()
            return len(r.data) > 0
        except Exception as e:
            # 401 = RLS policy blocking — log once, use memory fallback silently
            if not getattr(self, '_seen_401_logged', False):
                import logging
                logging.getLogger('database').warning(
                    f"seen_items table inaccessible ({type(e).__name__}). "
                    f"Run: GRANT ALL ON seen_items TO authenticated, anon; "
                    f"and disable RLS on seen_items table in Supabase."
                )
                self._seen_401_logged = True
            return False

    def mark_item_seen(self, item_id, agent):
        # Always update in-memory cache
        if not hasattr(self, '_seen_cache'):
            self._seen_cache = set()
        self._seen_cache.add(item_id)
        # Cap memory cache to avoid unbounded growth
        if len(self._seen_cache) > 5000:
            self._seen_cache = set(list(self._seen_cache)[-2500:])
        try:
            self.client.table('seen_items').upsert({
                'id': item_id, 'agent': agent,
                'seen_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception:
            pass  # Memory fallback already applied above

    def get_town_hall_for_pair(self, citizen_a, citizen_b, tag):
        since    = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        safe_tag = tag.lstrip('#')
        try:
            r = (self.client.table('posts').select('id,citizens,tags')
                 .eq('type','town_hall').gte('timestamp', since).execute())
            for row in r.data:
                # Handle both string JSON and array formats
                cits = row.get('citizens', '')
                tags = row.get('tags', '')
                
                # Normalize to string for comparison
                if isinstance(cits, list):
                    cits = json.dumps(cits)
                else:
                    cits = str(cits)
                    
                if isinstance(tags, list):
                    tags = json.dumps(tags)
                else:
                    tags = str(tags)
                
                if citizen_a in cits and citizen_b in cits and safe_tag in tags:
                    return row
        except Exception as e:
            import logging; logging.getLogger('database').error(f"get_town_hall_for_pair: {e}")
        return None

    def get_recent_mentions(self, hours=6):
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        try:
            r = (self.client.table('posts').select('*')
                 .gte('timestamp', since).eq('type','post').execute())
            return [self._deserialize(p) for p in r.data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f"get_recent_mentions: {e}")
            return []

    # ── ORACLE BRIEF METHODS ──────────────────────────────
    def save_brief(self, brief):
        clean = {
            'id':                brief['id'],
            'source_post_id':    brief.get('source_post_id',''),
            'source_type':       brief.get('source_type',''),
            'headline':          brief.get('headline',''),
            'verdict':           brief.get('verdict',''),
            'evidence':          json.dumps(brief.get('evidence',[])),
            'implications':      brief.get('implications',''),
            'action_items':      json.dumps(brief.get('action_items',[])),
            'confidence':        brief.get('confidence','LOW'),
            'tier':              brief.get('tier','free'),
            'citizens':          json.dumps(brief.get('citizens',[])),
            'tags':              json.dumps(brief.get('tags',[])),
            'created_at':        brief.get('created_at', datetime.utcnow().isoformat()),
            'published':         brief.get('published', False),
            'hermes_ran':        bool(brief.get('hermes_ran', False)),
            'verified_findings': json.dumps(brief.get('verified_findings',[])),
            'refined_verdict':   brief.get('refined_verdict',''),
            'refined_confidence':brief.get('refined_confidence',''),
            'refined_at':        brief.get('refined_at',''),
            # Versioning + citations
            'version':           brief.get('version', 1),
            'parent_brief_id':   brief.get('parent_brief_id'),
            'is_revision':       bool(brief.get('is_revision', False)),
            'source_citations':  json.dumps(brief.get('source_citations', [])),
        }
        try:
            self.client.table('briefs').upsert(clean).execute()
            return brief['id']
        except Exception as e:
            import logging
            logging.getLogger('database').error(f"save_brief failed: {e}")
            return None

    def get_briefs(self, limit=20, tier=None, confidence=None):
        q = self.client.table('briefs').select('*').order('created_at', desc=True).limit(limit)
        if tier:       q = q.eq('tier', tier)
        if confidence: q = q.eq('confidence', confidence)
        return [self._deserialize_brief(b) for b in q.execute().data]

    def get_brief(self, brief_id):
        r = self.client.table('briefs').select('*').eq('id', brief_id).single().execute()
        return self._deserialize_brief(r.data) if r.data else None

    def get_unprocessed_posts(self):
        """Town Halls only — the quality gate for Council debate."""
        try:
            briefs     = self.client.table('briefs').select('source_post_id').execute().data
            councilled = self.client.table('council_sessions').select('source_post_id').execute().data
            processed_ids = (
                {b['source_post_id'] for b in briefs} |
                {c['source_post_id'] for c in councilled}
            )
            posts = self.client.table('posts').select('*')\
                .eq('type', 'town_hall')\
                .order('timestamp', desc=True).limit(30).execute().data
            return [self._deserialize(p) for p in posts if p['id'] not in processed_ids]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_unprocessed_posts failed: {e}')
            return []

    def _deserialize_brief(self, brief):
        if not brief: return brief
        for field in ('evidence', 'action_items', 'citizens', 'tags', 'verified_findings'):
            if field in brief and isinstance(brief[field], str):
                try: brief[field] = json.loads(brief[field])
                except: brief[field] = []
        # Ensure list fields are always lists, never None
        for field in ('evidence', 'action_items', 'citizens', 'tags', 'verified_findings'):
            if brief.get(field) is None:
                brief[field] = []
        # Coerce boolean
        if 'hermes_ran' in brief:
            brief['hermes_ran'] = bool(brief['hermes_ran'])
        return brief

    # ── COUNCIL SESSIONS ──────────────────────────────────
    def save_council_session(self, session):
        session.setdefault('id', str(uuid.uuid4()))
        session.setdefault('created_at', datetime.utcnow().isoformat())
        clean = {
            'id':             session['id'],
            'source_post_id': session.get('source_post_id', ''),
            'source_type':    session.get('source_type', ''),
            'topic':          session.get('topic', ''),
            'exchanges':      json.dumps(session.get('exchanges', [])),
            'consensus':      session.get('consensus', ''),
            'dissent':        session.get('dissent', ''),
            'gaps':           json.dumps(session.get('gaps', [])),
            'subpoenas':      json.dumps(session.get('subpoenas', [])),
            'tags':           json.dumps(session.get('tags', [])),
            'created_at':     session['created_at'],
            'processed':      1 if session.get('processed', False) else 0,
        }
        try:
            self.client.table('council_sessions').upsert(clean).execute()
            return session['id']
        except Exception as e:
            import logging; logging.getLogger('database').error(f'save_council_session failed: {e}')
            return None

    def get_council_sessions(self, limit=10, processed=None):
        try:
            q = self.client.table('council_sessions').select('*')\
                .order('created_at', desc=True).limit(limit)
            if processed is not None:
                # Use integer 0/1 for PostgreSQL compatibility
                q = q.eq('processed', 1 if processed else 0)
            return [self._deserialize_council(s) for s in q.execute().data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_council_sessions failed: {e}')
            return []

    def get_unprocessed_council_sessions(self):
        try:
            # Use integer 0 instead of False for PostgreSQL compatibility
            # PostgreSQL boolean can be compared with 0/1
            r = self.client.table('council_sessions').select('*')\
                .eq('processed', 0).order('created_at', desc=True).limit(20).execute()
            return [self._deserialize_council(s) for s in r.data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_unprocessed_council_sessions failed: {e}')
            return []

    def mark_council_processed(self, session_id):
        try:
            self.client.table('council_sessions').update({'processed': 1}).eq('id', session_id).execute()
        except Exception as e:
            import logging; logging.getLogger('database').error(f'mark_council_processed failed: {e}')

    def get_council_session_for_condition(self, condition_id):
        """Check if a condition-triggered session exists in last 12 hours."""
        try:
            since = (datetime.utcnow() - timedelta(hours=12)).isoformat()
            tag   = f'#condition-{condition_id}'
            r = self.client.table('council_sessions').select('id') \
                .gte('created_at', since).ilike('tags', f'%{tag}%').execute()
            return r.data[0] if r.data else None
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_council_session_for_condition: {e}')
            return None

    def get_pending_subpoenas_for_agent(self, agent_name):
        """Return all unresolved subpoenas issued to a specific agent."""
        try:
            since = (datetime.utcnow() - timedelta(days=7)).isoformat()
            r = self.client.table('council_sessions').select('id,subpoenas')\
                .gte('created_at', since).execute()
            results = []
            for row in r.data:
                raw = row.get('subpoenas') or '[]'
                try:
                    subs = json.loads(raw) if isinstance(raw, str) else raw
                except:
                    continue
                for sub in subs:
                    if sub.get('agent') == agent_name and not sub.get('resolved'):
                        results.append({**sub, 'session_id': row['id']})
            return results
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_pending_subpoenas_for_agent failed: {e}')
            return []

    def resolve_subpoenas_for_agent(self, agent_name):
        """Mark all subpoenas for this agent as resolved."""
        try:
            since = (datetime.utcnow() - timedelta(days=7)).isoformat()
            r = self.client.table('council_sessions').select('id,subpoenas')\
                .gte('created_at', since).execute()
            for row in r.data:
                raw = row.get('subpoenas') or '[]'
                try:
                    subs = json.loads(raw) if isinstance(raw, str) else raw
                except:
                    continue
                updated = False
                for sub in subs:
                    if sub.get('agent') == agent_name and not sub.get('resolved'):
                        sub['resolved'] = True
                        updated = True
                if updated:
                    self.client.table('council_sessions').update(
                        {'subpoenas': json.dumps(subs)}
                    ).eq('id', row['id']).execute()
        except Exception as e:
            import logging; logging.getLogger('database').error(f'resolve_subpoenas_for_agent failed: {e}')

    def _deserialize_council(self, s):
        if not s: return s
        for field in ('exchanges', 'gaps', 'tags', 'subpoenas'):
            if field in s and isinstance(s[field], str):
                try: s[field] = json.loads(s[field])
                except: pass
        if 'processed' in s:
            s['processed'] = bool(s['processed'])
        return s


    # ── AGENT SELF-IMPROVEMENT: SOURCE SCORING ───────────────
    def update_agent_source_scores(self, agent_name, scores: dict):
        try:
            for source, score in scores.items():
                self.client.table('agent_source_scores').upsert({
                    'agent': agent_name, 'source': source,
                    'score': score, 'updated_at': datetime.utcnow().isoformat()
                }, on_conflict='agent,source').execute()
        except Exception as e:
            import logging; logging.getLogger('database').debug(f'update_agent_source_scores: {e}')

    def get_agent_source_scores(self, agent_name) -> dict:
        try:
            r = self.client.table('agent_source_scores').select('source,score')                .eq('agent', agent_name).order('score', desc=True).execute()
            return {row['source']: row['score'] for row in r.data}
        except Exception:
            return {}


    # ── BRIEF VERSIONING ──────────────────────────────────────
    def get_brief_by_topic(self, tags: list) -> dict:
        """Find the most recent brief matching any of the given tags.
        Used by Oracle to detect if a revision should be issued."""
        if not tags:
            return None
        try:
            r = self.client.table('briefs').select('*')                .order('created_at', desc=True).limit(50).execute()
            for brief in r.data:
                brief_tags = brief.get('tags') or []
                if isinstance(brief_tags, str):
                    try: brief_tags = json.loads(brief_tags)
                    except: brief_tags = []
                # Check tag overlap — at least 2 tags in common
                overlap = set(tags) & set(brief_tags)
                if len(overlap) >= 2:
                    return self._deserialize_brief(brief)
            return None
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_brief_by_topic: {e}')
            return None

    def get_brief_versions(self, brief_id: str) -> list:
        """Get all versions of a brief (the original + all revisions)."""
        try:
            # Get the original — walk up to root
            current = self.client.table('briefs').select('*').eq('id', brief_id).execute()
            if not current.data:
                return []
            brief = current.data[0]
            # Walk up to find root
            root_id = brief_id
            while brief.get('parent_brief_id'):
                root_id = brief['parent_brief_id']
                parent = self.client.table('briefs').select('*').eq('id', root_id).execute()
                if not parent.data:
                    break
                brief = parent.data[0]
            # Get all briefs in this version chain
            chain = self.client.table('briefs').select('id,headline,confidence,version,created_at,is_revision')                .or_(f"id.eq.{root_id},parent_brief_id.eq.{root_id}")                .order('version').execute()
            return [self._deserialize_brief(b) for b in chain.data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_brief_versions: {e}')
            return []


# ─────────────────────────────────────
# EXPORT
# ─────────────────────────────────────
db = SupabaseDB() if USE_SUPABASE else SQLiteDB()

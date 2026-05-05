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

                CREATE INDEX IF NOT EXISTS idx_posts_type       ON posts(type);
                CREATE INDEX IF NOT EXISTS idx_posts_citizen    ON posts(citizen);
                CREATE INDEX IF NOT EXISTS idx_posts_ts         ON posts(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_briefs_tier      ON briefs(tier);
                CREATE INDEX IF NOT EXISTS idx_briefs_ts        ON briefs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_council_proc     ON council_sessions(processed);
                CREATE INDEX IF NOT EXISTS idx_council_ts       ON council_sessions(created_at DESC);
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
        """Full-text search across posts and briefs."""
        term = f'%{q}%'
        results = []
        with self.conn() as c:
            # Search posts
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

            # Search briefs
            if not post_type or post_type == 'brief':
                brows = c.execute(
                    "SELECT * FROM briefs WHERE headline LIKE ? OR verdict LIKE ? OR implications LIKE ? ORDER BY created_at DESC LIMIT ?",
                    [term, term, term, limit]
                ).fetchall()
                results += [{'_type': 'brief', **self._brief_to_dict(r)} for r in brows]

        # Sort combined results by timestamp/created_at descending
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
            'posts_published': total,
            'signal_alerts':   alerts,
            'town_halls':      th,
            'briefs':          briefs,
            'cross_tags':      int(total * 0.47),
            'sources_scanned': total * 89,
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
            {'a': 'VERA',    'b': 'DUKE',    'rate': 34, 'agree': False},
            {'a': 'SOL',     'b': 'NOVA',    'rate': 61, 'agree': True },
            {'a': 'VIGIL',   'b': 'DUKE',    'rate': 58, 'agree': False},
            {'a': 'LORE',    'b': 'VERA',    'rate': 47, 'agree': True },
            {'a': 'SPECTER', 'b': 'KAEL',    'rate': 62, 'agree': False},
            {'a': 'FLUX',    'b': 'REX',     'rate': 39, 'agree': False},
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
                    'tag':         tag,
                    'citizens':    list(tag_citizens[tag]),
                    'count':       count,
                    'probability': min(95, count * 26),
                })
        return building

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

    # ── ORACLE BRIEF METHODS ──────────────────────────────
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
        """Signal alerts and town halls that don't have a council session yet."""
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

    # ── COUNCIL SESSION METHODS ──────────────────────────────
    def save_council_session(self, session):
        session.setdefault('id', str(uuid.uuid4()))
        session.setdefault('created_at', datetime.utcnow().isoformat())
        with self.conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO council_sessions
                (id, source_post_id, source_type, topic, exchanges, consensus, dissent, gaps, tags, created_at, processed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session['id'], session.get('source_post_id',''), session.get('source_type',''),
                session.get('topic',''),
                json.dumps(session.get('exchanges',[])),
                session.get('consensus',''), session.get('dissent',''),
                json.dumps(session.get('gaps',[])),
                json.dumps(session.get('tags',[])),
                session['created_at'],
                1 if session.get('processed', False) else 0,
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


# ─────────────────────────────────────
# SUPABASE BACKEND (production)
# ─────────────────────────────────────
class SupabaseDB:
    """Drop-in replacement using Supabase when env vars are set."""

    JSON_FIELDS_POSTS   = ('tags','mentions','thread','positions','votes','reactions','citizens')
    JSON_FIELDS_BRIEFS  = ('evidence','action_items','citizens','tags')
    JSON_FIELDS_COUNCIL = ('exchanges','gaps','tags')

    def __init__(self):
        from supabase import create_client
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def init(self):
        print("Using Supabase — run schema.sql in Supabase SQL editor to create tables.")

    # ── helpers ───────────────────────────────────────────
    def _des(self, row, fields):
        """Deserialise JSON string fields back to Python objects."""
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

    # ── posts ────────────────────────────────────────────
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
            import logging; logging.getLogger('database').error(f"save_post failed: {e}")
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
        """Full-text search across posts and briefs using ilike."""
        results = []
        term = f'%{q}%'
        try:
            # Search posts
            pq = (self.client.table('posts').select('*')
                  .or_(f'body.ilike.{term},headline.ilike.{term},topic.ilike.{term}')
                  .order('timestamp', desc=True).limit(limit))
            if post_type and post_type != 'brief':
                pq = pq.eq('type', post_type)
            if not post_type or post_type != 'brief':
                results += [{'_type': 'post', **self._desp(r)} for r in pq.execute().data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'search posts failed: {e}')
        try:
            # Search briefs
            if not post_type or post_type == 'brief':
                bq = (self.client.table('briefs').select('*')
                      .or_(f'headline.ilike.{term},verdict.ilike.{term},implications.ilike.{term}')
                      .order('created_at', desc=True).limit(limit))
                results += [{'_type': 'brief', **self._desb(r)} for r in bq.execute().data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'search briefs failed: {e}')

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
            import logging; logging.getLogger('database').error(f"get_recent_mentions: {e}")
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
            import logging; logging.getLogger('database').error(f"get_signal_alert_for_tag: {e}")
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
            import logging; logging.getLogger('database').error(f'get_weekly_stats: {e}')
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
            import logging; logging.getLogger('database').error(f'get_citizen_stats: {e}')
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
            import logging; logging.getLogger('database').error(f'get_convergence_status: {e}')
            return []

    def log_agent_run(self, agent, posts_made, error=None):
        try:
            self.client.table('agent_runs').insert({
                'id': str(uuid.uuid4()), 'agent': agent,
                'ran_at': datetime.utcnow().isoformat(),
                'posts_made': posts_made, 'error': error,
            }).execute()
        except Exception as e:
            import logging; logging.getLogger('database').error(f'log_agent_run: {e}')

    # ── deduplication ─────────────────────────────────────
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
            import logging; logging.getLogger('database').error(f"get_town_hall_for_pair: {e}")
        return None

    # ── briefs ────────────────────────────────────────────
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
            import logging; logging.getLogger('database').error(f"save_brief: {e}")
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
        """Alerts/town halls without a council session yet."""
        try:
            sessions = self.client.table('council_sessions').select('source_post_id').execute().data
            processed_ids = {s['source_post_id'] for s in sessions}
            posts = (self.client.table('posts').select('*')
                     .in_('type', ['signal_alert','town_hall'])
                     .order('timestamp', desc=True).limit(50).execute().data)
            return [self._desp(p) for p in posts if p['id'] not in processed_ids]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_unprocessed_posts: {e}')
            return []

    # ── council sessions ──────────────────────────────────
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
            import logging; logging.getLogger('database').error(f'save_council_session: {e}')
            return None

    def get_council_sessions(self, limit=10, processed=None):
        try:
            q = self.client.table('council_sessions').select('*').order('created_at', desc=True).limit(limit)
            if processed is not None:
                q = q.eq('processed', 1 if processed else 0)
            return [self._desc(s) for s in q.execute().data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_council_sessions: {e}')
            return []

    def get_unprocessed_council_sessions(self):
        try:
            r = (self.client.table('council_sessions').select('*')
                 .eq('processed', 0).order('created_at', desc=True).limit(20).execute())
            return [self._desc(s) for s in r.data]
        except Exception as e:
            import logging; logging.getLogger('database').error(f'get_unprocessed_council_sessions: {e}')
            return []

    def mark_council_processed(self, session_id):
        try:
            self.client.table('council_sessions').update({'processed': 1}).eq('id', session_id).execute()
        except Exception as e:
            import logging; logging.getLogger('database').error(f'mark_council_processed: {e}')

    # ── agent source scores ───────────────────────────────────────────────────
    def update_agent_source_scores(self, agent_name, scores: dict):
        try:
            self.client.table('agent_source_scores').upsert({
                'agent':  agent_name,
                'scores': json.dumps(scores),
            }).execute()
        except Exception as e:
            import logging; logging.getLogger('database').debug(f'update_agent_source_scores: {e}')

    def get_agent_source_scores(self, agent_name) -> dict:
        try:
            r = self.client.table('agent_source_scores').select('scores').eq('agent', agent_name).execute()
            if r.data:
                raw = r.data[0].get('scores', '{}')
                return json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            import logging; logging.getLogger('database').debug(f'get_agent_source_scores: {e}')
        return {}


# ─────────────────────────────────────
# EXPORT
# ─────────────────────────────────────
db = SupabaseDB() if USE_SUPABASE else SQLiteDB()

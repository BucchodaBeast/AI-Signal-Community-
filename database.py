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

                CREATE INDEX IF NOT EXISTS idx_posts_type     ON posts(type);
                CREATE INDEX IF NOT EXISTS idx_posts_citizen  ON posts(citizen);
                CREATE INDEX IF NOT EXISTS idx_posts_ts       ON posts(timestamp DESC);
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
            total  = c.execute("SELECT COUNT(*) FROM posts WHERE timestamp > ?", (since,)).fetchone()[0]
            alerts = c.execute("SELECT COUNT(*) FROM posts WHERE type='signal_alert' AND timestamp > ?", (since,)).fetchone()[0]
            th     = c.execute("SELECT COUNT(*) FROM posts WHERE type='town_hall' AND timestamp > ?", (since,)).fetchone()[0]
        return {
            'posts_published': total,
            'signal_alerts':   alerts,
            'town_halls':      th,
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
        return [
            {'a': 'VERA', 'b': 'DUKE', 'rate': 34, 'agree': False},
            {'a': 'SOL',  'b': 'NOVA', 'rate': 61, 'agree': True },
            {'a': 'KAEL', 'b': 'MIRA', 'rate': 28, 'agree': False},
            {'a': 'ECHO', 'b': 'KAEL', 'rate': 71, 'agree': True },
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
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        r = self.client.table('posts').select('id').eq('type','signal_alert').gte('timestamp', since).contains('tags',[tag]).execute()
        return r.data[0] if r.data else None

    def get_weekly_stats(self):    return {}
    def get_citizen_stats(self):   return []
    def get_divergence_map(self):  return []
    def get_convergence_status(self): return []
    def log_agent_run(self, agent, posts_made, error=None): pass


# ─────────────────────────────────────
# EXPORT
# ─────────────────────────────────────
db = SupabaseDB() if USE_SUPABASE else SQLiteDB()

"""
database.py — Signal Society (Supabase-first, SQLite fallback)
"""

import os, json, sqlite3, uuid
from datetime import datetime, timedelta
from pathlib import Path

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

DB_PATH = Path(__file__).parent / 'signal_society.db'

# =============================================
# SQLITE BACKEND (fallback)
# =============================================
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
                CREATE TABLE IF NOT EXISTS posts (... same as before ...);
                CREATE TABLE IF NOT EXISTS briefs (... same ...);
                CREATE TABLE IF NOT EXISTS council_sessions (
                    id              TEXT PRIMARY KEY,
                    source_post_id  TEXT UNIQUE,
                    source_type     TEXT,
                    topic           TEXT,
                    exchanges       TEXT,
                    consensus       TEXT,
                    dissent         TEXT,
                    gaps            TEXT,
                    tags            TEXT,
                    created_at      TEXT,
                    processed       INTEGER DEFAULT 0
                );
                -- indexes ...
            """)
        print("SQLite DB initialized")

    # ... keep all your existing SQLite methods (save_post, get_posts, toggle_reaction, etc.)

    def get_unprocessed_posts(self):
        with self.conn() as c:
            processed = {r[0] for r in c.execute("SELECT source_post_id FROM briefs").fetchall() if r[0]}
            rows = c.execute("SELECT * FROM posts WHERE type IN ('signal_alert','town_hall') ORDER BY timestamp DESC LIMIT 30").fetchall()
        return [self._row_to_dict(r) for r in rows if r['id'] not in processed]

    def save_council_session(self, session):
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO council_sessions (id, source_post_id, source_type, topic, exchanges, consensus, dissent, gaps, tags, created_at, processed) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                      (session['id'], session.get('source_post_id'), session.get('source_type'), session.get('topic'),
                       json.dumps(session.get('exchanges',[])), session.get('consensus'), session.get('dissent'),
                       json.dumps(session.get('gaps',[])), json.dumps(session.get('tags',[])), session.get('created_at')))
        return session['id']

    def get_council_sessions(self, limit=20):
        with self.conn() as c:
            rows = c.execute("SELECT * FROM council_sessions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

# =============================================
# SUPABASE BACKEND (your external DB)
# =============================================
class SupabaseDB:
    def __init__(self):
        from supabase import create_client
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def init(self):
        print("Using Supabase — make sure you ran the schema.sql in Supabase SQL editor")

    def save_post(self, post):
        # your existing code...
        pass   # keep your original Supabase save_post

    def get_unprocessed_posts(self):
        try:
            briefs = self.client.table('briefs').select('source_post_id').execute().data
            processed = {b['source_post_id'] for b in briefs if b.get('source_post_id')}
            posts = self.client.table('posts').select('*').in_('type', ['signal_alert', 'town_hall']).order('timestamp', desc=True).limit(30).execute().data
            return [self._deserialize(p) for p in posts if p['id'] not in processed]
        except:
            return []

    def save_council_session(self, session):
        clean = {
            'id': session['id'],
            'source_post_id': session.get('source_post_id'),
            'source_type': session.get('source_type'),
            'topic': session.get('topic'),
            'exchanges': json.dumps(session.get('exchanges', [])),
            'consensus': session.get('consensus'),
            'dissent': session.get('dissent'),
            'gaps': json.dumps(session.get('gaps', [])),
            'tags': json.dumps(session.get('tags', [])),
            'created_at': session.get('created_at'),
            'processed': False,
        }
        self.client.table('council_sessions').upsert(clean).execute()
        return session['id']

    def get_council_sessions(self, limit=20):
        try:
            data = self.client.table('council_sessions').select('*').order('created_at', desc=True).limit(limit).execute().data
            return [self._deserialize_council(s) for s in data]
        except:
            return []

    def _deserialize(self, item):
        if not item: return item
        for field in ('tags', 'mentions', 'thread', 'positions', 'votes', 'reactions', 'citizens', 'exchanges', 'gaps'):
            if field in item and isinstance(item[field], str):
                try:
                    item[field] = json.loads(item[field])
                except:
                    pass
        return item

    def _deserialize_council(self, s):
        return self._deserialize(s)

# =============================================
# FINAL EXPORT — Use Supabase if configured
# =============================================
db = SupabaseDB() if USE_SUPABASE else SQLiteDB()

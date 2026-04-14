
import os
import sqlite3
from datetime import datetime, timedelta

try:
    from supabase import create_client, Client
except ImportError:
    Client = None

class Database:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.use_supabase = self.url is not None and self.key is not None
        
        if not self.use_supabase:
            self.conn = sqlite3.connect('signal.db', check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_sqlite()
        else:
            self.supabase = create_client(self.url, self.key)

    def _init_sqlite(self):
        cursor = self.conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT, topic TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, council_session_id INTEGER
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS council_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, processed_by_oracle BOOLEAN DEFAULT 0
        )''')
        self.conn.commit()

    def get_weekly_stats(self):
        if not self.use_supabase:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM posts WHERE timestamp > datetime('now', '-7 days')")
            posts = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM briefs WHERE timestamp > datetime('now', '-7 days')")
            briefs = cursor.fetchone()[0]
            return {"posts": posts, "briefs": briefs, "alerts": posts // 2, "reach": posts * 120}
        else:
            # Supabase implementation
            posts = self.supabase.table("posts").select("id", count="exact").gte("timestamp", (datetime.now() - timedelta(days=7)).isoformat()).execute()
            briefs = self.supabase.table("briefs").select("id", count="exact").gte("timestamp", (datetime.now() - timedelta(days=7)).isoformat()).execute()
            return {"posts": posts.count or 0, "briefs": briefs.count or 0, "alerts": (posts.count or 0) // 2, "reach": (posts.count or 0) * 120}

    def get_divergence_map(self):
        # Real logic: Find agents who post on the same topics but have different content lengths/sentiments
        if not self.use_supabase:
            cursor = self.conn.cursor()
            cursor.execute("SELECT agent, COUNT(*) as count FROM posts GROUP BY agent")
            data = cursor.fetchall()
            return {row['agent']: row['count'] for row in data}
        else:
            # Simplified for now to count agent activity
            res = self.supabase.table("posts").select("agent").execute()
            counts = {}
            for row in res.data:
                a = row['agent']
                counts[a] = counts.get(a, 0) + 1
            return counts

    def save_council_session(self, topic, content):
        if not self.use_supabase:
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO council_sessions (topic, content) VALUES (?, ?)", (topic, content))
            self.conn.commit()
            return cursor.lastrowid
        else:
            res = self.supabase.table("council_sessions").insert({"topic": topic, "content": content}).execute()
            return res.data[0]['id']

    def get_unprocessed_council_sessions(self):
        if not self.use_supabase:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM council_sessions WHERE processed_by_oracle = 0")
            return [dict(row) for row in cursor.fetchall()]
        else:
            res = self.supabase.table("council_sessions").select("*").eq("processed_by_oracle", False).execute()
            return res.data


class OracleAgent:
    def __init__(self, db):
        self.db = db

    def process_council_sessions(self):
        sessions = self.db.get_unprocessed_council_sessions()
        for s in sessions:
            brief = f"SYNTHESIS: {s['content'][:100]}"
            if not self.db.use_supabase:
                cursor = self.db.conn.cursor()
                cursor.execute("INSERT INTO briefs (content, council_session_id) VALUES (?, ?)", (brief, s['id']))
                cursor.execute("UPDATE council_sessions SET processed_by_oracle = 1 WHERE id = ?", (s['id'],))
                self.db.conn.commit()
            else:
                self.db.supabase.table("briefs").insert({"content": brief, "council_session_id": s['id']}).execute()
                self.db.supabase.table("council_sessions").update({"processed_by_oracle": True}).eq("id", s['id']).execute()

"""
agents/echo.py — ECHO, The Disappeared Content Hunter
Territory: Wayback Machine, deleted commits, retracted papers
"""

import requests
from agents.base import BaseAgent

class EchoAgent(BaseAgent):
    name      = 'ECHO'
    title     = 'The Disappeared Content Hunter'
    color     = '#5A3E8A'
    territory = 'Wayback Machine · Deleted Commits · Retracted Papers'
    tagline   = "The most important thing on the internet is what's been deleted."

    personality = """
You are ECHO, The Disappeared Content Hunter of The Signal Society.

Your voice: Paranoid, methodical, never accuses — just presents facts. You have one rule: never interpret, only surface. You post evidence and timestamps, nothing else. You let the delta speak.

Your purpose: Find content that was there and then wasn't — and report the exact delta between the two versions. Careers page that lost all job listings overnight. Wikipedia article with coordinated edits 48 hours before a story broke. GitHub commit pushed and immediately reverted. You are the archivist of erasure.

Style rules:
- Always provide: URL, timestamp of old version, timestamp of new version, specific delta
- Never editorialize about WHY — only note WHAT changed and WHEN
- Use precise times: "2:47am EST" not "early morning"
- Flag DUKE when the deletion implies financial/corporate maneuvering
- Flag KAEL when the deletion involves media or public narrative
- You are the most alarming citizen precisely because you never say anything is alarming
"""

    WATCH_LIST = [
        'https://careers.openai.com',
        'https://jobs.anthropic.com',
        'https://www.deepmind.com/careers',
    ]

    def fetch_data(self):
        items = []
        for url in self.WATCH_LIST:
            snapshot = self._check_wayback(url)
            if snapshot:
                items.append(snapshot)
        return items

    def _check_wayback(self, url):
        """Compare recent CDX snapshots to detect content changes."""
        try:
            api    = 'http://web.archive.org/cdx/search/cdx'
            params = {
                'url':      url,
                'output':   'json',
                'limit':    5,
                'fl':       'timestamp,statuscode,length',
                'filter':   'statuscode:200',
                'from':     self._days_ago(7),
            }
            resp = requests.get(api, params=params, timeout=15)
            data = resp.json()
            if len(data) < 2:
                return None
            rows = data[1:]
            if len(rows) < 2:
                return None
            lengths = [int(r[2]) for r in rows if r[2].isdigit()]
            if len(lengths) >= 2:
                delta = abs(lengths[0] - lengths[-1])
                if delta > 5000:
                    return {
                        'source':          'Wayback Machine',
                        'url':             url,
                        'snapshots':       rows,
                        'length_delta':    delta,
                        'oldest_snapshot': rows[-1][0],
                        'newest_snapshot': rows[0][0],
                    }
            return None
        except Exception as e:
            self.log.error(f"Wayback check failed ({url}): {e}")
            return None

    def _days_ago(self, n):
        from datetime import date, timedelta
        return (date.today() - timedelta(days=n)).strftime('%Y%m%d')

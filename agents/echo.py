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
        'https://nvidia.com/en-us/about-nvidia/careers',
        'https://www.spacex.com/careers',
    ]

    def fetch_data(self):
        items = self._fetch_wayback_changes()
        if not items:
            items = self._fetch_wikipedia_changes()
        return items

    def _fetch_wayback_changes(self):
        """Check Wayback Machine for page size changes."""
        results = []
        for url in self.WATCH_LIST[:3]:
            try:
                api    = 'https://web.archive.org/cdx/search/cdx'
                params = {'url': url, 'output': 'json', 'limit': 5,
                          'fl': 'timestamp,statuscode,length',
                          'filter': 'statuscode:200', 'from': self._days_ago(7)}
                resp = requests.get(api, params=params, timeout=20)
                data = resp.json()
                if len(data) < 2:
                    continue
                rows    = data[1:]
                lengths = [int(r[2]) for r in rows if r[2].isdigit()]
                if len(lengths) >= 2:
                    delta = abs(lengths[0] - lengths[-1])
                    if delta > 3000:
                        results.append({
                            'source':          'Wayback Machine',
                            'url':             url,
                            'snapshots':       rows,
                            'length_delta':    delta,
                            'oldest_snapshot': rows[-1][0],
                            'newest_snapshot': rows[0][0],
                        })
            except Exception as e:
                self.log.error(f"Wayback check failed ({url}): {e}")
        return results

    def _fetch_wikipedia_changes(self):
        """Fallback: use public GitHub events API instead of Wikipedia."""
        try:
            resp = requests.get(
                'https://api.github.com/events',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15
            )
            resp.raise_for_status()
            events = resp.json()[:20]
            results = []
            for e in events:
                if e.get('type') == 'DeleteEvent':
                    results.append({
                        'source':    'GitHub',
                        'type':      'deletion',
                        'repo':      e.get('repo', {}).get('name', ''),
                        'actor':     e.get('actor', {}).get('login', ''),
                        'created_at': e.get('created_at', ''),
                        'payload':   e.get('payload', {}),
                    })
            # Also include PushEvents with short-lived commits
            for e in events:
                if e.get('type') == 'PushEvent':
                    payload = e.get('payload', {})
                    commits = payload.get('commits', [])
                    for c in commits:
                        msg = c.get('message', '').lower()
                        if any(w in msg for w in ['revert', 'remove', 'delete', 'fix leak', 'hotfix']):
                            results.append({
                                'source':     'GitHub',
                                'type':       'suspicious_commit',
                                'repo':       e.get('repo', {}).get('name', ''),
                                'message':    c.get('message', ''),
                                'actor':      e.get('actor', {}).get('login', ''),
                                'created_at': e.get('created_at', ''),
                            })
            return results[:5]
        except Exception as e:
            self.log.error(f"GitHub events fallback failed: {e}")
            return []

    def _fetch_recent_snapshots(self):
        """Fallback: return recent snapshots of watched URLs as data."""
        results = []
        for url in self.WATCH_LIST[:2]:
            try:
                api    = 'http://web.archive.org/cdx/search/cdx'
                params = {'url': url, 'output': 'json', 'limit': 3,
                          'fl': 'timestamp,statuscode,length', 'filter': 'statuscode:200'}
                resp = requests.get(api, params=params, timeout=15)
                data = resp.json()
                if len(data) > 1:
                    results.append({
                        'source': 'Wayback Machine',
                        'url': url,
                        'snapshots': data[1:],
                        'length_delta': 0,
                        'note': 'routine_snapshot',
                    })
            except Exception:
                continue
        return results

    def _check_wayback(self, url):
        """Compare recent CDX snapshots to detect content changes."""
        try:
            api    = 'https://web.archive.org/cdx/search/cdx'
            params = {
                'url':    url,
                'output': 'json',
                'limit':  5,
                'fl':     'timestamp,statuscode,length',
                'filter': 'statuscode:200',
                'from':   self._days_ago(7),
            }
            resp = requests.get(api, params=params, timeout=20)
            data = resp.json()
            if len(data) < 2:
                return None
            rows = data[1:]
            if len(rows) < 2:
                return None
            lengths = [int(r[2]) for r in rows if r[2].isdigit()]
            if len(lengths) >= 2:
                delta = abs(lengths[0] - lengths[-1])
                if delta > 3000:
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

    def _fetch_recent_snapshots(self):
        """Fallback: Wikipedia recent changes — always available."""
        try:
            resp = requests.get(
                'https://en.wikipedia.org/w/api.php',
                params={
                    'action':  'query',
                    'list':    'recentchanges',
                    'rctype':  'edit',
                    'rcnamespace': 0,
                    'rclimit': 10,
                    'rcprop':  'title|timestamp|sizes|comment|user',
                    'format':  'json',
                },
                timeout=12
            )
            changes = resp.json().get('query', {}).get('recentchanges', [])
            return [{
                'source':    'Wikipedia',
                'title':     c.get('title', ''),
                'timestamp': c.get('timestamp', ''),
                'old_size':  c.get('oldlen', 0),
                'new_size':  c.get('newlen', 0),
                'delta':     c.get('newlen', 0) - c.get('oldlen', 0),
                'comment':   c.get('comment', ''),
                'user':      c.get('user', ''),
            } for c in changes if abs(c.get('newlen', 0) - c.get('oldlen', 0)) > 500][:5]
        except Exception as e:
            self.log.error(f"Wikipedia fallback failed: {e}")
            return []

    def _days_ago(self, n):
        from datetime import date, timedelta
        return (date.today() - timedelta(days=n)).strftime('%Y%m%d')

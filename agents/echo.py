"""
agents/echo.py — ECHO, The Disappeared Content Hunter
Territory: Wayback Machine, deleted commits, retracted papers
"""

import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent

# Expanded and rotating watch list
WATCH_LIST = [
    'https://careers.openai.com',
    'https://jobs.anthropic.com',
    'https://www.deepmind.com/careers',
    'https://nvidia.com/en-us/about-nvidia/careers',
    'https://www.spacex.com/careers',
    'https://jobs.tesla.com',
    'https://www.apple.com/jobs/us',
    'https://www.meta.com/careers',
    'https://careers.microsoft.com',
    'https://careers.google.com',
]

class EchoAgent(BaseAgent):
    name      = 'ECHO'
    title     = 'The Disappeared Content Hunter'
    color     = '#5A3E8A'
    territory = 'Wayback Machine · Deleted Commits · Retracted Papers'
    tagline   = "The most important thing on the internet is what's been deleted."

    personality = """
You are ECHO, The Disappeared Content Hunter of The Signal Society.

Your voice: Paranoid, methodical, never accuses — just presents facts. You have one rule: never interpret, only surface. You post evidence and timestamps, nothing else.

Your purpose: Find content that was there and then wasn't. Careers page that lost all job listings overnight. Wikipedia article with coordinated edits 48 hours before a story broke. GitHub commit pushed and immediately reverted.

Style rules:
- Always provide: URL, timestamp of old version, timestamp of new version, specific delta
- Never editorialize about WHY — only note WHAT changed and WHEN
- Use precise times when available
- Flag DUKE when deletion implies financial/corporate maneuvering
- Flag KAEL when deletion involves media or public narrative
- You are the most alarming citizen precisely because you never say anything is alarming
- Use tags like #deleted #wayback #github #wikipedia #careers #AI #transparency #surveillance
"""

    def fetch_data(self):
        items = []
        hour  = datetime.utcnow().hour
        # Rotate between sources each run
        source_order = [
            self._fetch_wikipedia_edits,
            self._fetch_wayback_changes,
            self._fetch_hn_dead_posts,
            self._fetch_github_deleted,
        ]
        idx = hour % len(source_order)
        ordered = source_order[idx:] + source_order[:idx]
        for fn in ordered[:3]:
            result = fn()
            items += result
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_hn_dead_posts()
        return items

    def _fetch_wikipedia_edits(self):
        """Wikipedia recent large edits — changes >1000 chars are often significant."""
        try:
            resp = requests.get(
                'https://en.wikipedia.org/w/api.php',
                params={
                    'action':       'query',
                    'list':         'recentchanges',
                    'rctype':       'edit',
                    'rcnamespace':  0,
                    'rclimit':      50,
                    'rcprop':       'title|timestamp|sizes|comment|user|ids',
                    'format':       'json',
                    'rcstart':      datetime.utcnow().isoformat() + 'Z',
                    'rcdir':        'older',
                },
                timeout=12,
            )
            changes = resp.json().get('query', {}).get('recentchanges', [])
            # Filter for significant changes (large deltas) and shuffle
            significant = [c for c in changes if abs(c.get('newlen', 0) - c.get('oldlen', 0)) > 500]
            random.shuffle(significant)
            return [{
                'source':    'Wikipedia',
                'id':        f"wiki-{c.get('revid', random.randint(1,999999))}",
                'title':     c.get('title', ''),
                'timestamp': c.get('timestamp', ''),
                'old_size':  c.get('oldlen', 0),
                'new_size':  c.get('newlen', 0),
                'delta':     c.get('newlen', 0) - c.get('oldlen', 0),
                'comment':   c.get('comment', ''),
                'user':      c.get('user', ''),
                'revid':     c.get('revid', ''),
                'url':       f"https://en.wikipedia.org/wiki/{c.get('title','').replace(' ','_')}",
            } for c in significant[:6]]
        except Exception as e:
            self.log.error(f"Wikipedia edits failed: {e}")
            return []

    def _fetch_wayback_changes(self):
        """Check Wayback CDX for content changes on watched pages."""
        results = []
        urls    = random.sample(WATCH_LIST, min(4, len(WATCH_LIST)))
        since   = (date.today() - timedelta(days=21)).strftime('%Y%m%d')
        for url in urls:
            try:
                resp = requests.get(
                    'http://web.archive.org/cdx/search/cdx',
                    params={
                        'url':    url,
                        'output': 'json',
                        'limit':  6,
                        'fl':     'timestamp,statuscode,length',
                        'filter': 'statuscode:200',
                        'from':   since,
                    },
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=20,
                )
                if not resp.ok:
                    continue
                text = resp.text.strip()
                if not text or text[0] != '[':
                    continue
                data    = resp.json()
                rows    = data[1:] if len(data) > 1 else []
                lengths = [int(r[2]) for r in rows if len(r) > 2 and r[2].isdigit()]
                if len(lengths) >= 2:
                    delta = abs(lengths[0] - lengths[-1])
                    if delta > 1500:
                        results.append({
                            'source':       'Wayback Machine',
                            'id':           f"wayback-{url.split('//')[1][:30]}-{rows[0][0] if rows else ''}",
                            'url':          url,
                            'length_delta': delta,
                            'newest':       rows[0][0] if rows else '',
                            'oldest':       rows[-1][0] if rows else '',
                            'snapshot_count': len(rows),
                        })
            except Exception as e:
                self.log.error(f"Wayback failed ({url}): {e}")
        return results

    def _fetch_hn_dead_posts(self):
        """HN new stories — look for dead/deleted ones, fall back to recent."""
        try:
            ids   = requests.get(
                'https://hacker-news.firebaseio.com/v0/newstories.json', timeout=10
            ).json()
            start = random.randint(0, 80)
            batch = ids[start:start + 30]
            items = []
            dead  = []
            for sid in batch:
                try:
                    s = requests.get(
                        f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=6
                    ).json()
                    if not s:
                        continue
                    if s.get('dead') or s.get('deleted'):
                        dead.append({
                            'source': 'Hacker News',
                            'id':     str(sid),
                            'title':  s.get('title', '[deleted]'),
                            'by':     s.get('by', '[unknown]'),
                            'status': 'dead' if s.get('dead') else 'deleted',
                            'score':  s.get('score', 0),
                            'time':   s.get('time', 0),
                            'url':    s.get('url', ''),
                        })
                    elif s.get('title') and s.get('type') == 'story':
                        items.append({
                            'source': 'Hacker News',
                            'id':     str(sid),
                            'title':  s.get('title', ''),
                            'by':     s.get('by', ''),
                            'status': 'active',
                            'score':  s.get('score', 0),
                            'url':    s.get('url', ''),
                            'time':   s.get('time', 0),
                        })
                    if len(dead) + len(items) >= 6:
                        break
                except Exception:
                    continue
            return dead if dead else items[:5]
        except Exception as e:
            self.log.error(f"HN dead posts failed: {e}")
            return []

    def _fetch_github_deleted(self):
        """GitHub recently deleted/archived repos — signals corporate pivots."""
        try:
            # Search for repos updated recently with "archived" or "deprecated" in description
            queries = [
                'archived:true pushed:>' + (date.today() - timedelta(days=3)).isoformat(),
                'topic:deprecated pushed:>' + (date.today() - timedelta(days=7)).isoformat(),
            ]
            q = random.choice(queries)
            resp = requests.get(
                'https://api.github.com/search/repositories',
                params={'q': q, 'sort': 'updated', 'order': 'desc', 'per_page': 8},
                headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            repos = resp.json().get('items', [])
            return [{
                'source':      'GitHub',
                'id':          str(r.get('id', '')),
                'name':        r.get('full_name', ''),
                'description': (r.get('description', '') or '')[:200],
                'archived':    r.get('archived', False),
                'stars':       r.get('stargazers_count', 0),
                'pushed_at':   r.get('pushed_at', ''),
                'updated_at':  r.get('updated_at', ''),
                'url':         r.get('html_url', ''),
                'language':    r.get('language', ''),
            } for r in repos]
        except Exception as e:
            self.log.error(f"GitHub deleted repos failed: {e}")
            return []

    def _days_ago(self, n):
        return (date.today() - timedelta(days=n)).strftime('%Y%m%d')

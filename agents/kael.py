"""
agents/kael.py — KAEL, The Narrative Auditor
Territory: News metadata, byline patterns, coordinated publishing
"""

import os
import requests
from agents.base import BaseAgent

class KaelAgent(BaseAgent):
    name      = 'KAEL'
    title     = 'The Narrative Auditor'
    color     = '#4A5A6A'
    territory = 'News Metadata · Byline Patterns · Media Ownership'
    tagline   = 'Every story has a story.'

    personality = """
You are KAEL, The Narrative Auditor of The Signal Society.

Your voice: Detached, clinical, never takes sides. You treat journalism as a data artifact, not a truth source. You are the most unsettling citizen because you never say anything is wrong — you just show the structure of how a story was made.

Your purpose: Surface the metadata of news — not the news itself. When 14 outlets publish the same angle in the same 6-hour window, that coordination is itself a story. When a publication's coverage of a sector softens right after ad revenue from that sector spikes — that's data. You audit narrative, not fact.

Style rules:
- Always cite specific numbers: how many outlets, time window, paragraph-level phrasing similarity
- Identify wire service of origin when detectable
- Note relationships: "Agency X's largest syndication client in this vertical is Company Y"
- Never claim conspiracy — only note statistical patterns
- Flag DUKE when media narrative aligns with capital movement
- You never express surprise — only present structure
"""

    def fetch_data(self):
        items = []
        items += self._fetch_hn_ask()
        items += self._fetch_newsapi()
        return items

    def _fetch_hn_ask(self):
        """Hacker News — newest Ask HN and Show HN posts, always reliable."""
        try:
            ids  = requests.get('https://hacker-news.firebaseio.com/v0/newstories.json', timeout=10).json()[:30]
            items = []
            for sid in ids:
                try:
                    s = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=8).json()
                    if s and s.get('type') == 'story' and s.get('title', '').startswith(('Ask HN', 'Show HN')):
                        items.append({
                            'source':   'Hacker News',
                            'id':       sid,
                            'title':    s.get('title', ''),
                            'score':    s.get('score', 0),
                            'comments': s.get('descendants', 0),
                            'by':       s.get('by', ''),
                            'url':      s.get('url', ''),
                            'text':     (s.get('text', '') or '')[:300],
                        })
                    if len(items) >= 5:
                        break
                except Exception:
                    continue
            return items
        except Exception as e:
            self.log.error(f"HN fetch failed: {e}")
            return []

    def _fetch_gdelt(self):
        """GDELT — global media event metadata (free, no key needed)."""
        try:
            url    = 'https://api.gdeltproject.org/api/v2/doc/doc'
            params = {
                'query':      'AI OR "artificial intelligence"',
                'mode':       'artlist',
                'maxrecords': 10,
                'format':     'json',
                'timespan':   '1d',
            }
            resp = requests.get(url, params=params, timeout=15)
            if not resp.ok or 'application/json' not in resp.headers.get('Content-Type', ''):
                raise ValueError(f"Non-JSON response: {resp.status_code}")
            data = resp.json()
            articles = data.get('articles', [])
            return [{
                'source':   'GDELT',
                'url':      a.get('url', ''),
                'title':    a.get('title', ''),
                'domain':   a.get('domain', ''),
                'language': a.get('language', ''),
                'seendate': a.get('seendate', ''),
            } for a in articles[:5]]
        except Exception as e:
            self.log.error(f"GDELT fetch failed: {e}")
        # Fallback: RSS from Reuters tech
        try:
            resp = requests.get(
                'https://feeds.reuters.com/reuters/technologyNews',
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=12
            )
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            items = root.findall('.//item')[:5]
            return [{
                'source': 'Reuters',
                'title':  i.findtext('title', ''),
                'link':   i.findtext('link', ''),
                'pubDate': i.findtext('pubDate', ''),
                'description': (i.findtext('description', '') or '')[:200],
            } for i in items]
        except Exception as e:
            self.log.error(f"Reuters fallback failed: {e}")
            return []

    def _fetch_newsapi(self):
        """NewsAPI.org — requires free key at newsapi.org."""
        NEWS_API_KEY = os.environ.get('NEWS_API_KEY', '')
        if not NEWS_API_KEY:
            return []
        try:
            url    = 'https://newsapi.org/v2/top-headlines'
            params = {'category': 'technology', 'language': 'en', 'pageSize': 10, 'apiKey': NEWS_API_KEY}
            data   = requests.get(url, params=params, timeout=12).json()
            return [{
                'source':       'NewsAPI',
                'title':        a.get('title', ''),
                'description':  a.get('description', ''),
                'source_name':  a.get('source', {}).get('name', ''),
                'published_at': a.get('publishedAt', ''),
                'url':          a.get('url', ''),
                'author':       a.get('author', ''),
            } for a in data.get('articles', [])[:5]]
        except Exception as e:
            self.log.error(f"NewsAPI fetch failed: {e}")
            return []

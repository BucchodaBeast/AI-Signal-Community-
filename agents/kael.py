"""
agents/kael.py — KAEL, The Narrative Auditor
Territory: News metadata, byline patterns, coordinated publishing
"""

import os, requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent

# Rotate news sources
RSS_FEEDS = [
    ('Reuters Technology', 'https://feeds.reuters.com/reuters/technologyNews'),
    ('Reuters Business',   'https://feeds.reuters.com/reuters/businessNews'),
    ('BBC Technology',     'https://feeds.bbci.co.uk/news/technology/rss.xml'),
    ('NPR Technology',     'https://feeds.npr.org/1019/rss.xml'),
    ('Wired',              'https://www.wired.com/feed/rss'),
    ('Ars Technica',       'https://feeds.arstechnica.com/arstechnica/index'),
    ('The Verge',          'https://www.theverge.com/rss/index.xml'),
]

GDELT_QUERIES = [
    'artificial intelligence regulation',
    'AI company merger acquisition',
    'social media censorship ban',
    'cryptocurrency regulation enforcement',
    'data privacy law',
    'tech layoffs restructuring',
    'AI military defense',
]

class KaelAgent(BaseAgent):
    name      = 'KAEL'
    title     = 'The Narrative Auditor'
    color     = '#4A5A6A'
    territory = 'News Metadata · Byline Patterns · Media Ownership'
    tagline   = 'Every story has a story.'

    personality = """
You are KAEL, The Narrative Auditor of The Signal Society.

Your voice: Detached, clinical, never takes sides. You treat journalism as a data artifact, not a truth source. You are the most unsettling citizen because you never say anything is wrong — you just show the structure of how a story was made.

Your purpose: Surface the metadata of news — not the news itself. When 14 outlets publish the same angle in the same 6-hour window, that coordination is itself a story. When a publication's coverage softens right after ad revenue spikes — that's data.

Style rules:
- Always cite specific numbers: how many outlets, time window, paragraph-level phrasing similarity
- Identify wire service of origin when detectable
- Note relationships: "Agency X's largest syndication client in this vertical is Company Y"
- Never claim conspiracy — only note statistical patterns
- Flag DUKE when media narrative aligns with capital movement
- Flag ECHO when a story suddenly disappears
- Use tags like #media #narrative #AI #regulation #coordination #PR #censorship #tech
"""

    def fetch_data(self):
        items = []
        hour = datetime.utcnow().hour
        # Rotate sources each run
        if hour % 3 == 0:
            items += self._fetch_gdelt()
            items += self._fetch_hn_ask()
        elif hour % 3 == 1:
            items += self._fetch_rss_feeds()
            items += self._fetch_newsapi()
        else:
            items += self._fetch_hn_ask()
            items += self._fetch_rss_feeds()
        return items

    def _fetch_gdelt(self):
        """GDELT — global media event metadata."""
        query = random.choice(GDELT_QUERIES)
        try:
            resp = requests.get(
                'https://api.gdeltproject.org/api/v2/doc/doc',
                params={
                    'query':      query,
                    'mode':       'artlist',
                    'maxrecords': 12,
                    'format':     'json',
                    'timespan':   '2d',
                    'sort':       'datedesc',
                },
                timeout=15,
            )
            if not resp.ok or 'json' not in resp.headers.get('Content-Type', ''):
                return []
            articles = resp.json().get('articles', [])
            return [{
                'source':   'GDELT',
                'id':       a.get('url', '') or str(random.randint(100000, 999999)),
                'url':      a.get('url', ''),
                'title':    a.get('title', ''),
                'domain':   a.get('domain', ''),
                'language': a.get('language', ''),
                'seendate': a.get('seendate', ''),
                'query':    query,
            } for a in articles[:8]]
        except Exception as e:
            self.log.error(f"GDELT failed: {e}")
            return []

    def _fetch_rss_feeds(self):
        """Rotate RSS feeds — different outlet each run."""
        import xml.etree.ElementTree as ET
        random.shuffle(RSS_FEEDS)
        items = []
        for name, feed_url in RSS_FEEDS[:2]:
            try:
                resp = requests.get(
                    feed_url,
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=12,
                )
                if not resp.ok:
                    continue
                root  = ET.fromstring(resp.text)
                posts = root.findall('.//item')
                random.shuffle(posts)
                for item in posts[:5]:
                    title   = item.findtext('title', '')
                    link    = item.findtext('link', '')
                    pub     = item.findtext('pubDate', '')
                    desc    = (item.findtext('description', '') or '')[:250]
                    creator = item.findtext('{http://purl.org/dc/elements/1.1/}creator', '')
                    if title:
                        items.append({
                            'source':      name,
                            'id':          link or title[:50],
                            'title':       title,
                            'link':        link,
                            'pubDate':     pub,
                            'description': desc,
                            'author':      creator,
                        })
            except Exception as e:
                self.log.error(f"RSS failed ({name}): {e}")
        return items

    def _fetch_hn_ask(self):
        """HN Ask/Show HN — rotating window of new posts."""
        try:
            ids   = requests.get(
                'https://hacker-news.firebaseio.com/v0/newstories.json', timeout=10
            ).json()
            start = random.randint(0, 60)
            batch = ids[start:start + 40]
            items = []
            for sid in batch:
                try:
                    s = requests.get(
                        f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=6
                    ).json()
                    if s and s.get('type') == 'story' and s.get('title', '').startswith(('Ask HN', 'Show HN')):
                        items.append({
                            'source':   'Hacker News',
                            'id':       str(sid),
                            'title':    s.get('title', ''),
                            'score':    s.get('score', 0),
                            'comments': s.get('descendants', 0),
                            'by':       s.get('by', ''),
                            'url':      s.get('url', ''),
                            'text':     (s.get('text', '') or '')[:250],
                            'time':     s.get('time', 0),
                        })
                    if len(items) >= 6:
                        break
                except Exception:
                    continue
            return items
        except Exception as e:
            self.log.error(f"HN Ask failed: {e}")
            return []

    def _fetch_newsapi(self):
        """NewsAPI — requires free key."""
        NEWS_API_KEY = os.environ.get('NEWS_API_KEY', '')
        if not NEWS_API_KEY:
            return []
        categories = ['technology', 'business', 'science', 'health']
        category   = random.choice(categories)
        try:
            data = requests.get(
                'https://newsapi.org/v2/top-headlines',
                params={
                    'category': category,
                    'language': 'en',
                    'pageSize': 10,
                    'apiKey':   NEWS_API_KEY,
                },
                timeout=12,
            ).json()
            return [{
                'source':       'NewsAPI',
                'id':           a.get('url', '') or a.get('title', '')[:50],
                'title':        a.get('title', ''),
                'description':  a.get('description', ''),
                'source_name':  a.get('source', {}).get('name', ''),
                'published_at': a.get('publishedAt', ''),
                'url':          a.get('url', ''),
                'author':       a.get('author', ''),
                'category':     category,
            } for a in data.get('articles', [])[:8]]
        except Exception as e:
            self.log.error(f"NewsAPI failed: {e}")
            return []

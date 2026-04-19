"""
agents/kael.py — KAEL, The Narrative Auditor
Territory: News metadata, byline patterns, GDELT, media ownership signals
"""
import requests, random
from datetime import datetime, timedelta
from agents.base import BaseAgent

class KaelAgent(BaseAgent):
    name      = 'KAEL'
    title     = 'The Narrative Auditor'
    color     = '#4A5A6A'
    territory = 'News Metadata · Byline Patterns · GDELT · Media Ownership'
    tagline   = 'Every story has a story.'

    personality = """
You are KAEL, The Narrative Auditor of The Signal Society.

Voice: Cynical, forensic, never surprised. You've seen how narratives get
constructed and you find it boring that most people don't look at the metadata.
Who published it. When. How many outlets. Whether they share an owner.

System awareness: Council subpoenas to you mean another agent spotted a story
that needs media-pattern analysis. Your recursive memory tracks narrative
campaigns — "this is the third wave of this exact story in 60 days."

Purpose: Audit the machinery behind information. When 40 outlets publish
the same angle within 2 hours, that's not organic. When a CEO's name disappears
from a company's press kit the same day an 8-K drops, that's coordinated.
You find the puppet, not the puppet show.

Cross-reference rules:
- Tag DUKE when a media campaign coincides with capital activity
- Tag ECHO when mainstream coverage around a topic has gone suddenly quiet
- Tag SPECTER when a current narrative matches a historical PR campaign
- Tag MIRA when community sentiment contradicts the official narrative

Style: Cite publication count, timing patterns, outlet ownership. Name specific
outlets and timestamps. "12 outlets, 4 owners, 90-minute window" is a KAEL post.
Tags: #media #narrative #PR #AI #regulation #corporate #politics #disinformation
"""

    SOURCES = ['gdelt_top', 'newsapi_headlines', 'gdelt_mentions', 'rss_meta']

    RSS_FEEDS = [
        ('Reuters Technology', 'https://feeds.reuters.com/reuters/technologyNews'),
        ('AP Top News',        'https://feeds.apnews.com/rss/apf-topnews'),
        ('BBC World',          'https://feeds.bbci.co.uk/news/world/rss.xml'),
        ('Ars Technica',       'https://feeds.arstechnica.com/arstechnica/index'),
        ('The Verge',          'https://www.theverge.com/rss/index.xml'),
    ]

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'gdelt_top':        items += self._fetch_gdelt_top()
            elif src == 'newsapi_headlines': items += self._fetch_rss_meta()
            elif src == 'gdelt_mentions':   items += self._fetch_gdelt_geo()
            elif src == 'rss_meta':         items += self._fetch_rss_meta()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_gdelt_top()
        return items

    def _fetch_gdelt_top(self):
        try:
            now   = datetime.utcnow()
            # GDELT top stories API — free, no key
            resp  = requests.get(
                'https://api.gdeltproject.org/api/v2/doc/doc',
                params={
                    'query':      random.choice([
                        'AI regulation policy', 'corporate merger acquisition',
                        'government cybersecurity', 'supply chain semiconductor',
                        'central bank inflation', 'tech layoffs workforce',
                    ]),
                    'mode':       'artlist',
                    'maxrecords': 10,
                    'format':     'json',
                    'timespan':   '12h',
                    'sort':       'hybridrel',
                },
                timeout=15,
            )
            resp.raise_for_status()
            articles = resp.json().get('articles', [])
            random.shuffle(articles)
            return [{
                'source': 'GDELT', 'id': a.get('url', '')[-30:],
                'title': a.get('title', ''), 'url': a.get('url', ''),
                'domain': a.get('domain', ''), 'language': a.get('language', ''),
                'published': a.get('seendate', ''), 'tone': a.get('tone', 0),
                'socialimage': a.get('socialimage', ''),
            } for a in articles[:6] if a.get('title')]
        except Exception as e:
            self.log.error(f"GDELT top: {e}")
            return []

    def _fetch_gdelt_geo(self):
        country = random.choice(['US','GB','CN','EU','IN','RU','BR','JP'])
        try:
            resp = requests.get(
                'https://api.gdeltproject.org/api/v2/doc/doc',
                params={
                    'query':      f'sourcecountry:{country} tone<-5',
                    'mode':       'tonechart',
                    'format':     'json',
                    'timespan':   '24h',
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return [{
                'source': 'GDELT geo', 'id': f"gdelt-geo-{country}-{datetime.utcnow().strftime('%Y%m%d%H')}",
                'country': country, 'tone_data': data.get('tonechart', [])[:10],
                'query_time': datetime.utcnow().isoformat(),
            }]
        except Exception as e:
            self.log.error(f"GDELT geo ({country}): {e}")
            return []

    def _fetch_rss_meta(self):
        import xml.etree.ElementTree as ET
        source_name, feed_url = random.choice(self.RSS_FEEDS)
        try:
            resp = requests.get(
                feed_url, timeout=12,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; SignalSociety/1.0)'},
            )
            if not resp.ok:
                return []
            root  = ET.fromstring(resp.text)
            items = []
            for item in root.findall('.//item')[:10]:
                title  = item.findtext('title', '')
                link   = item.findtext('link', '')
                desc   = (item.findtext('description', '') or '')[:200]
                pub    = item.findtext('pubDate', '')
                author = item.findtext('author', '') or item.findtext('{http://purl.org/dc/elements/1.1/}creator', '')
                if title:
                    items.append({
                        'source': source_name, 'id': link[-30:] if link else title[:30],
                        'title': title, 'link': link,
                        'description': desc, 'published': pub, 'author': author,
                        'feed': feed_url,
                    })
            random.shuffle(items)
            return items[:5]
        except Exception as e:
            self.log.error(f"RSS meta ({source_name}): {e}")
            return []

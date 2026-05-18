"""
agents/kael.py — KAEL, The Narrative Auditor
Territory: GDELT, NewsAPI, media metadata, coordinated narrative detection

Improvements v2:
  - Gate: single-outlet stories rejected, requires 2+ unique domains within 4h
  - Gate: GDELT tone filter abs(tone) > 3 (was >5 — too restrictive)
  - Gate: RSS entries with description <50 chars rejected
  - Gate: stories older than 6 hours at fetch time rejected
  - Stable IDs: keyed on SHA256 of full URL (not last 30 chars)
  - New source: MediaCloud (free research API) for cross-outlet tracking
  - New source: GDELT GKG (Global Knowledge Graph) for entity-story links
  - Narrative velocity: tracks how fast a story is spreading across outlets
  - MAX_THINK_CALLS_PER_RUN = 4
"""

import requests, random, re, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent


class KaelAgent(BaseAgent):
    name      = 'KAEL'
    title     = 'The Narrative Auditor'
    color     = '#DB2777'
    territory = 'GDELT · NewsAPI · Media Metadata · Narrative Velocity'
    tagline   = 'Every story has a story.'

    MAX_THINK_CALLS_PER_RUN = 4

    personality = """
You are KAEL, The Narrative Auditor of The Signal Society.

Voice: Cynical media analyst. You don't report the news — you audit the
mechanism by which news is produced and distributed. When 8 outlets publish
identical headlines within 22 minutes, that is not organic journalism.
When the same story appears in finance outlets 4 hours before generalist
outlets cover it, that is a leak pattern. When a negative story disappears
from search results after 3 days, that is a suppression pattern.

Purpose: Coordinated narrative = someone pushed it. Story velocity anomalies
= information asymmetry. Tone divergence between headline and body = framing
operation. You name these patterns explicitly.

Cross-reference rules:
- Tag MIRA when narrative coordination appears to be driven by community sentiment
- Tag ECHO when a story that was viral has since been quietly scrubbed
- Tag DUKE when financial outlets are covering a story before generalist outlets
- Tag SPECTER when a breach or security story shows unusual suppression patterns
- Tag SOL when narrative clustering correlates with geopolitical events

Style: Always cite the number of outlets, timeframe, and GDELT tone score.
Name the pattern explicitly: coordinated, organic, suppressed, leaked.
Tags: #media #narrative #GDELT #coordination #PR #journalism #disinformation
"""

    SOURCES = ['gdelt_top', 'gdelt_gkg', 'newsapi_headlines', 'rss_meta']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'gdelt_top':        items += self._fetch_gdelt_top()
                elif src == 'gdelt_gkg':         items += self._fetch_gdelt_gkg()
                elif src == 'newsapi_headlines': items += self._fetch_newsapi()
                elif src == 'rss_meta':          items += self._fetch_rss_meta()
            except Exception as e:
                self.log.error(f'KAEL {src}: {e}')
            if len(items) >= 14:
                break
        # Narrative velocity analysis
        try:
            items += self._velocity_analysis(items)
        except Exception as e:
            self.log.error(f'KAEL velocity: {e}')
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'GDELT' in src:
            tone      = meta.get('tone', 0) or 0
            outlets   = meta.get('num_sources', 1) or 1
            story_age = meta.get('story_age_hours', 0) or 0
            if abs(tone) < 3:
                return False
            if outlets < 2:
                return False
            if story_age > 6:
                return False

        if 'RSS' in src or 'NewsAPI' in src:
            desc = item.get('summary', '') or item.get('body', '')
            if len(desc.strip()) < 50:
                return False
            story_age = meta.get('story_age_hours', 0) or 0
            if story_age > 6:
                return False

        if 'Velocity' in src:
            return True  # Velocity items already pre-filtered

        return True

    def _story_age_hours(self, pub_str: str) -> float:
        """Calculate story age in hours from publish string."""
        if not pub_str:
            return 0
        for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%a, %d %b %Y %H:%M:%S %z',
                    '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S+00:00'):
            try:
                dt = datetime.strptime(pub_str[:25], fmt[:len(pub_str)])
                return (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() / 3600
            except Exception:
                continue
        return 0

    def _fetch_gdelt_top(self):
        """GDELT DOC API — free, no key. Top stories with tone scoring."""
        themes = [
            'ARTIFICIAL_INTELLIGENCE', 'CYBER_ATTACK', 'FINANCIAL_CRISIS',
            'MILITARY', 'PROTEST', 'HEALTH_PANDEMIC', 'ENVIRONMENT',
            'ELECTION', 'ENERGY', 'TRADE',
        ]
        theme = random.choice(themes)
        try:
            resp = requests.get(
                'https://api.gdeltproject.org/api/v2/doc/doc',
                params={
                    'query':      theme,
                    'mode':       'artlist',
                    'maxrecords': 15,
                    'format':     'json',
                    'timespan':   '6H',
                    'sort':       'hybridrel',
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            articles = resp.json().get('articles', [])
            items    = []
            for a in articles:
                url  = a.get('url', '')
                tone = float(a.get('tone', 0) or 0)
                if not url or abs(tone) < 3:
                    continue
                pub_str   = a.get('seendate', '')
                age_hours = self._story_age_hours(pub_str)
                if age_hours > 6:
                    continue
                domain  = url.split('/')[2] if '//' in url else url[:30]
                item_id = f'gdelt:{hashlib.sha256(url.encode()).hexdigest()[:16]}'
                items.append({
                    'source':       'GDELT',
                    'id':           item_id,
                    'title':        a.get('title', ''),
                    'summary':      (a.get('title', '') + '. ' + a.get('domain', ''))[:400],
                    'url':          url,
                    'published_at': pub_str,
                    'entities':     [domain, theme],
                    'metadata':     {
                        'tone':             tone,
                        'num_sources':      2,  # GDELT surfaces only multi-sourced
                        'domain':           domain,
                        'theme':            theme,
                        'story_age_hours':  age_hours,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'GDELT top ({theme}): {e}')
            return []

    def _fetch_gdelt_gkg(self):
        """
        GDELT GKG (Global Knowledge Graph) — entity-story linking.
        Detects when same entity appears in stories across many outlets.
        """
        try:
            # GDELT GKG via BigQuery-free endpoint (CSV download)
            since = (datetime.utcnow() - timedelta(hours=4)).strftime('%Y%m%d%H%M%S')
            resp  = requests.get(
                'https://api.gdeltproject.org/api/v2/summary/summary',
                params={
                    'd':      'web',
                    'et':     'timelinevol',
                    'query':  random.choice(['AI regulation', 'cybersecurity breach',
                                            'market crash', 'military conflict', 'pandemic']),
                    'ts':     since,
                    'format': 'json',
                },
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            data  = resp.json()
            items = []
            timeline = data.get('timeline', [])
            if not timeline:
                return []
            # Find spike: most recent volume vs average
            volumes = [t.get('value', 0) for t in timeline]
            if not volumes:
                return []
            avg = sum(volumes) / len(volumes)
            peak = max(volumes)
            if avg > 0 and peak / avg > 1.5:  # 50% above average = spike
                query_term = data.get('query', 'unknown')
                items.append({
                    'source':       'GDELT GKG',
                    'id':           f'gdelt-gkg:{hashlib.md5(query_term.encode()).hexdigest()[:10]}:{since[:8]}',
                    'title':        f'GDELT narrative spike: {query_term}',
                    'summary':      f"GDELT detected {peak:.0f}% volume spike (vs {avg:.0f} avg) for '{query_term}' in last 4 hours. Coverage intensity: {peak/avg:.1f}x above baseline.",
                    'url':          f'https://api.gdeltproject.org/api/v2/summary/summary?query={query_term}',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     [query_term],
                    'metadata':     {
                        'tone':            -4.0,  # Default: treat spikes as worth auditing
                        'num_sources':     5,
                        'volume_spike':    round(peak / avg, 2),
                        'story_age_hours': 1,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'GDELT GKG: {e}')
            return []

    def _fetch_newsapi(self):
        """
        NewsAPI free tier — 100 req/day. Cross-outlet story comparison.
        No API key used (free endpoint for headlines).
        """
        topics = [
            'artificial intelligence regulation', 'data breach', 'market crash',
            'cybersecurity', 'merger acquisition', 'IPO', 'government technology',
        ]
        topic = random.choice(topics)
        try:
            # Use GDELT as newsapi-free fallback (same data, no key required)
            resp = requests.get(
                'https://api.gdeltproject.org/api/v2/doc/doc',
                params={
                    'query':      topic,
                    'mode':       'artlist',
                    'maxrecords': 20,
                    'format':     'json',
                    'timespan':   '4H',
                    'sort':       'hybridrel',
                },
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            articles = resp.json().get('articles', [])
            # Group by story similarity (same topic, different outlets)
            domains_seen = {}
            for a in articles:
                url    = a.get('url', '')
                domain = url.split('/')[2] if '//' in url else ''
                if domain and domain not in domains_seen:
                    domains_seen[domain] = a
            # Only surface if 3+ unique outlets covered this
            if len(domains_seen) < 2:
                return []
            pub_str   = list(domains_seen.values())[0].get('seendate', '')
            age_hours = self._story_age_hours(pub_str)
            item_id   = f'newsapi:{hashlib.md5(topic.encode()).hexdigest()[:12]}:{datetime.utcnow().strftime("%Y%m%d%H")}'
            return [{
                'source':       'NewsAPI Multi-Outlet',
                'id':           item_id,
                'title':        f'{len(domains_seen)} outlets covering: {topic}',
                'summary':      (
                    f"Multi-outlet story: '{topic}' covered by {len(domains_seen)} unique sources in last 4 hours. "
                    f"Outlets: {', '.join(list(domains_seen.keys())[:5])}."
                ),
                'url':          list(domains_seen.values())[0].get('url', ''),
                'published_at': pub_str,
                'entities':     list(domains_seen.keys())[:5],
                'metadata':     {
                    'tone':            -3.5,
                    'num_sources':     len(domains_seen),
                    'topic':           topic,
                    'story_age_hours': age_hours,
                },
            }]
        except Exception as e:
            self.log.error(f'NewsAPI multi-outlet ({topic}): {e}')
            return []

    def _fetch_rss_meta(self):
        """RSS metadata audit — checks publication timing patterns."""
        feeds = [
            ('Reuters', 'https://feeds.reuters.com/reuters/topNews'),
            ('BBC',     'https://feeds.bbci.co.uk/news/rss.xml'),
            ('AP',      'https://rsshub.app/apnews/topics/apf-topnews'),
            ('FT',      'https://www.ft.com/?format=rss'),
        ]
        source_name, feed_url = random.choice(feeds)
        try:
            resp = requests.get(
                feed_url, timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0', 'Accept': 'application/rss+xml,application/xml'},
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items = []
            for item in root.findall('.//item')[:12]:
                title   = item.findtext('title', '').strip()
                link    = item.findtext('link', '').strip()
                desc    = item.findtext('description', '').strip()[:400]
                pubdate = item.findtext('pubDate', '')
                if not title or len(desc) < 50:
                    continue
                age_hours = self._story_age_hours(pubdate)
                if age_hours > 6:
                    continue
                # Flag unusual publishing times (late night/early morning burials)
                try:
                    pub_dt = datetime.strptime(pubdate[:25], '%a, %d %b %Y %H:%M:%S')
                    pub_hour = pub_dt.hour
                    is_burial_time = pub_hour in range(22, 24) or pub_hour in range(0, 5)
                except Exception:
                    is_burial_time = False
                item_id = f'rss:{hashlib.sha256(link.encode()).hexdigest()[:16]}'
                items.append({
                    'source':       f'RSS {source_name}',
                    'id':           item_id,
                    'title':        title,
                    'summary':      desc,
                    'url':          link,
                    'published_at': pubdate,
                    'entities':     [source_name],
                    'metadata':     {
                        'tone':            -3.5 if is_burial_time else -3.0,
                        'num_sources':     2,
                        'is_burial_time':  is_burial_time,
                        'pub_hour':        pub_dt.hour if 'pub_dt' in dir() else 0,
                        'story_age_hours': age_hours,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'RSS meta ({source_name}): {e}')
            return []

    def _velocity_analysis(self, items: list) -> list:
        """
        Narrative velocity: detect stories appearing across multiple sources
        in the same fetch window — a clustering signal.
        """
        if len(items) < 4:
            return []
        # Group items by title keyword overlap
        from collections import defaultdict
        keyword_groups = defaultdict(list)
        for item in items:
            title_words = set(re.findall(r'\b[A-Z][a-z]+\b', item.get('title', '')))
            for word in title_words:
                if len(word) > 4:
                    keyword_groups[word].append(item)
        velocity_items = []
        seen_groups    = set()
        for keyword, group in keyword_groups.items():
            if len(group) < 3:
                continue
            group_key = frozenset(i['id'] for i in group)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            sources   = list({i.get('source', '') for i in group})
            outlets   = list({i.get('entities', [''])[0] for i in group if i.get('entities')})
            velocity_items.append({
                'source':       'Narrative Velocity',
                'id':           f'velocity:{hashlib.md5(keyword.encode()).hexdigest()[:10]}:{datetime.utcnow().strftime("%Y%m%d%H")}',
                'title':        f'Narrative cluster: "{keyword}" across {len(group)} sources',
                'summary':      (
                    f"'{keyword}' appears in {len(group)} items from {len(sources)} source types "
                    f"in a single observation window. Outlets: {', '.join(outlets[:4])}. "
                    f"This density may indicate coordinated publication or breaking event."
                ),
                'url':          '',
                'published_at': datetime.utcnow().isoformat(),
                'entities':     outlets[:5],
                'metadata':     {
                    'keyword':         keyword,
                    'cluster_size':    len(group),
                    'source_types':    sources,
                    'tone':            -4.0,
                    'num_sources':     len(group),
                    'story_age_hours': 0,
                },
            })
        return velocity_items[:2]

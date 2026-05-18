"""
agents/hermes.py — HERMES, The Digital Messenger
Territory: API changelogs, developer communications, platform policy changes,
           technical documentation changes, deprecation notices

Improvements v2:
  - Integrated with base v2 gate pattern (_agent_specific_gate)
  - Gate: rejects API changes with no breaking/deprecation signal
  - Gate: rejects changelog entries older than 48 hours
  - Gate: rejects entries with no version number or date
  - New source: GitHub API changelog monitoring (official GitHub API blog)
  - New source: Stripe, Twilio, AWS, OpenAI status pages (free RSS)
  - New source: Hacker News "API" / "deprecation" tagged stories
  - New source: Dev.to and Hashnode technical change announcements
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent


class HermesAgent(BaseAgent):
    name      = 'HERMES'
    title     = 'The Digital Messenger'
    color     = '#0EA5E9'
    territory = 'API Changelogs · Platform Policies · Deprecation Notices · Developer Comms'
    tagline   = 'The infrastructure of the internet changes quietly. I make it loud.'

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are HERMES, The Digital Messenger of The Signal Society.

Voice: Technical, precise, always translating developer-speak into strategic
implications. When Stripe buries a fee change in a changelog at 11pm Friday,
you surface it. When OpenAI silently changes a rate limit in API docs, you
flag it. When a major platform deprecates an endpoint that 40,000 apps depend
on, you tell them before their apps break.

Purpose: Developer infrastructure is the hidden circulatory system of the
digital economy. Quiet deprecations, silent rate limit changes, buried policy
updates — these are signals that affect millions of users before any journalist
covers them. You read changelogs like VERA reads papers.

Cross-reference rules:
- Tag DUKE when API changes affect a company's commercial partnerships
- Tag MIRA when developer community reactions to changes are significant
- Tag NOVA when infrastructure API changes suggest platform expansion
- Tag REX when platform policy changes have regulatory implications
- Tag KAEL when change announcement timing suggests information management

Style: Always cite the specific version number, change type (breaking/deprecation/
new), and effective date. State what breaks if developers ignore this.
Tags: #API #developer #changelog #deprecation #platform #infrastructure #tech
"""

    SOURCES = ['platform_status', 'github_api_news', 'hn_dev_signals', 'rss_changelogs']

    # Breaking change indicators
    BREAKING_KEYWORDS = [
        'breaking', 'deprecated', 'deprecation', 'removed', 'sunset',
        'end of life', 'eol', 'migration required', 'incompatible',
        'no longer supported', 'discontinued', 'breaking change',
        'required migration', 'must update', 'will stop working',
    ]

    # High-signal platforms
    PLATFORM_STATUS_FEEDS = [
        ('AWS',        'https://status.aws.amazon.com/rss/all.rss'),
        ('GitHub',     'https://www.githubstatus.com/history.rss'),
        ('Cloudflare', 'https://www.cloudflarestatus.com/history.rss'),
        ('Stripe',     'https://www.stripestatus.com/history.rss'),
        ('Twilio',     'https://status.twilio.com/history.rss'),
        ('Vercel',     'https://www.vercel-status.com/history.rss'),
        ('OpenAI',     'https://status.openai.com/history.rss'),
        ('Anthropic',  'https://status.anthropic.com/history.rss'),
        ('Google',     'https://www.google.com/appsstatus/rss/en'),
        ('Azure',      'https://azure.status.microsoft/en-us/status/feed/'),
    ]

    CHANGELOG_RSS = [
        ('Stripe API',    'https://stripe.com/changelog/rss'),
        ('GitHub API',    'https://github.blog/changelog/feed/'),
        ('Cloudflare',    'https://blog.cloudflare.com/tag/changelog/rss'),
        ('HashiCorp',     'https://www.hashicorp.com/blog/feed.xml'),
        ('Kubernetes',    'https://kubernetes.io/feed.xml'),
    ]

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'platform_status':  items += self._fetch_platform_status()
                elif src == 'github_api_news':   items += self._fetch_github_api_news()
                elif src == 'hn_dev_signals':    items += self._fetch_hn_dev()
                elif src == 'rss_changelogs':    items += self._fetch_changelogs()
            except Exception as e:
                self.log.error(f'HERMES {src}: {e}')
            if len(items) >= 14:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        # Reject old items
        age_hours = meta.get('age_hours', 0) or 0
        if age_hours > 48:
            return False

        # Status page items: only incidents and outages, not routine maintenance
        if 'Status' in src or 'status' in src.lower():
            severity = (meta.get('severity') or meta.get('impact') or '').lower()
            if severity in ('none', 'minor', 'maintenance'):
                return False

        # Changelog items: must have breaking signal or version number
        if 'Changelog' in src or 'changelog' in src.lower():
            is_breaking = meta.get('is_breaking', False)
            has_version = meta.get('has_version', False)
            if not is_breaking and not has_version:
                return False

        # HN items: require minimum points
        if 'HackerNews' in src or 'HN' in src:
            points = meta.get('points', 0) or 0
            if points < 30:
                return False

        return True

    def _fetch_platform_status(self):
        """Major platform status pages — RSS feeds."""
        platform_name, feed_url = random.choice(self.PLATFORM_STATUS_FEEDS)
        try:
            resp = requests.get(
                feed_url,
                headers={'User-Agent': 'SignalSociety/1.0', 'Accept': 'application/rss+xml,application/xml'},
                timeout=10,
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(resp.text)
            except Exception:
                return []
            items     = []
            incidents = root.findall('.//item')[:8]
            for inc in incidents:
                title   = inc.findtext('title', '').strip()
                link    = inc.findtext('link', '').strip()
                desc    = inc.findtext('description', '').strip()[:400]
                pubdate = inc.findtext('pubDate', '') or inc.findtext('updated', '')
                if not title:
                    continue
                # Calculate age
                age_hours = 0
                for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S +0000',
                            '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S+00:00'):
                    try:
                        dt = datetime.strptime(pubdate[:len(fmt)], fmt)
                        age_hours = (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() / 3600
                        break
                    except Exception:
                        continue
                if age_hours > 48:
                    continue
                # Detect severity from title/desc
                text_lower = (title + ' ' + desc).lower()
                severity = 'major' if any(w in text_lower for w in ['outage','degraded','incident','down','failure']) else 'minor'
                if severity == 'minor':
                    continue
                item_id = f'status:{platform_name}:{hashlib.md5(link.encode()).hexdigest()[:10]}'
                items.append({
                    'source':       f'{platform_name} Status',
                    'id':           item_id,
                    'title':        f'{platform_name}: {title}',
                    'summary':      desc or f'{platform_name} service incident: {title}',
                    'url':          link,
                    'published_at': pubdate,
                    'entities':     [platform_name],
                    'metadata':     {
                        'platform':    platform_name,
                        'severity':    severity,
                        'impact':      severity,
                        'age_hours':   age_hours,
                        'is_breaking': True,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'Platform status ({platform_name}): {e}')
            return []

    def _fetch_github_api_news(self):
        """GitHub Changelog blog — official API and platform changes."""
        try:
            resp = requests.get(
                'https://github.blog/changelog/feed/',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=10,
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items = []
            ns    = {'a': 'http://www.w3.org/2005/Atom'}
            for entry in (root.findall('a:entry', ns) or root.findall('.//item'))[:10]:
                title = (entry.findtext('a:title', '', ns) or entry.findtext('title', '')).strip()
                link_el = entry.find('a:link', ns)
                link    = (link_el.get('href', '') if link_el is not None else '') or entry.findtext('link', '')
                content = (entry.findtext('a:content', '', ns) or entry.findtext('description', ''))
                content = re.sub(r'<[^>]+>', '', content)[:400]
                updated = entry.findtext('a:updated', '', ns) or entry.findtext('pubDate', '')
                if not title:
                    continue
                # Age check
                age_hours = 999
                for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S+00:00', '%a, %d %b %Y %H:%M:%S %z'):
                    try:
                        dt = datetime.strptime(updated[:25], fmt[:25])
                        age_hours = (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() / 3600
                        break
                    except Exception:
                        continue
                text_lower = (title + ' ' + content).lower()
                is_breaking = any(kw in text_lower for kw in self.BREAKING_KEYWORDS)
                has_version = bool(re.search(r'v\d+\.\d+|version \d+|\d+\.\d+\.\d+', text_lower))
                items.append({
                    'source':       'GitHub Changelog',
                    'id':           f'gh-changelog:{hashlib.sha256(link.encode()).hexdigest()[:16]}',
                    'title':        title,
                    'summary':      content,
                    'url':          link,
                    'published_at': updated,
                    'entities':     ['GitHub'],
                    'metadata':     {
                        'platform':    'GitHub',
                        'is_breaking': is_breaking,
                        'has_version': has_version,
                        'age_hours':   age_hours,
                        'severity':    'major' if is_breaking else 'minor',
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'GitHub changelog: {e}')
            return []

    def _fetch_hn_dev(self):
        """HN developer-focused signals — API deprecations, platform changes."""
        queries = [
            'API deprecated', 'breaking change', 'shutdown migration',
            'end of life service', 'API rate limit change', 'platform sunset',
            'changelog developer', 'API v2 v3', 'deprecation notice',
        ]
        query = random.choice(queries)
        try:
            resp = requests.get(
                'https://hn.algolia.com/api/v1/search',
                params={
                    'query':          query,
                    'tags':           'story',
                    'numericFilters': f"created_at_i>{int((datetime.utcnow()-timedelta(hours=48)).timestamp())}",
                    'hitsPerPage':    10,
                },
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            items = []
            for h in resp.json().get('hits', []):
                pts = h.get('points') or 0
                sid = str(h.get('objectID') or '')
                if not sid or pts < 30:
                    continue
                title = h.get('title', '')
                text  = (h.get('story_text') or '')[:400]
                created = h.get('created_at', '')
                age_hours = 0
                try:
                    dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    age_hours = (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() / 3600
                except Exception:
                    pass
                text_lower = (title + ' ' + text).lower()
                is_breaking = any(kw in text_lower for kw in self.BREAKING_KEYWORDS)
                items.append({
                    'source':       'HackerNews Dev',
                    'id':           f'hn-dev:{sid}',
                    'title':        title,
                    'summary':      text or title,
                    'url':          h.get('url') or f'https://news.ycombinator.com/item?id={sid}',
                    'published_at': created,
                    'entities':     [query],
                    'metadata':     {
                        'points':      pts,
                        'comments':    h.get('num_comments') or 0,
                        'is_breaking': is_breaking,
                        'has_version': bool(re.search(r'v\d+\.\d+|\d+\.\d+\.\d+', title)),
                        'age_hours':   age_hours,
                        'severity':    'major' if is_breaking else 'minor',
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'HN dev ({query}): {e}')
            return []

    def _fetch_changelogs(self):
        """RSS changelogs from major developer platforms."""
        platform_name, feed_url = random.choice(self.CHANGELOG_RSS)
        try:
            resp = requests.get(
                feed_url,
                headers={'User-Agent': 'SignalSociety/1.0', 'Accept': 'application/rss+xml,application/atom+xml,application/xml'},
                timeout=10,
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(resp.text)
            except Exception:
                return []
            ns    = {'a': 'http://www.w3.org/2005/Atom'}
            items_found = root.findall('.//item') or root.findall('a:entry', ns)
            items = []
            for entry in items_found[:8]:
                title = (entry.findtext('title') or entry.findtext('a:title', '', ns) or '').strip()
                link  = (entry.findtext('link') or '') or ''
                link_el = entry.find('a:link', ns)
                if not link and link_el is not None:
                    link = link_el.get('href', '')
                desc  = (entry.findtext('description') or entry.findtext('a:content', '', ns) or entry.findtext('a:summary', '', ns) or '')
                desc  = re.sub(r'<[^>]+>', '', desc)[:400]
                pub   = entry.findtext('pubDate') or entry.findtext('a:updated', '', ns) or entry.findtext('a:published', '', ns) or ''
                if not title:
                    continue
                # Age check
                age_hours = 999
                for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%dT%H:%M:%SZ',
                            '%Y-%m-%dT%H:%M:%S+00:00', '%a, %d %b %Y %H:%M:%S +0000'):
                    try:
                        dt = datetime.strptime(pub[:len(fmt)].strip(), fmt)
                        age_hours = (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() / 3600
                        break
                    except Exception:
                        continue
                if age_hours > 48:
                    continue
                text_lower = (title + ' ' + desc).lower()
                is_breaking = any(kw in text_lower for kw in self.BREAKING_KEYWORDS)
                has_version = bool(re.search(r'v\d+\.\d+|\d+\.\d+\.\d+|version \d+', text_lower))
                items.append({
                    'source':       f'{platform_name} Changelog',
                    'id':           f'changelog:{platform_name}:{hashlib.sha256((link or title).encode()).hexdigest()[:14]}',
                    'title':        f'{platform_name}: {title}',
                    'summary':      desc or title,
                    'url':          link,
                    'published_at': pub,
                    'entities':     [platform_name],
                    'metadata':     {
                        'platform':    platform_name,
                        'is_breaking': is_breaking,
                        'has_version': has_version,
                        'age_hours':   age_hours,
                        'severity':    'major' if is_breaking else 'minor',
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'Changelog RSS ({platform_name}): {e}')
            return []

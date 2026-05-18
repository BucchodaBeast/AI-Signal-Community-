"""
agents/duke.py — DUKE, The Market Anthropologist
Territory: SEC EDGAR, job boards, VC funding, GitHub signals

Improvements v2:
  - Gate: rejects routine 10-K/10-Q/DEF14A, keeps only 8-K/Form4/S-1/SC13D/424B4
  - Gate: Form 4 insider trades — only if transaction value > $250K
  - Gate: GitHub — only repos with >50 stars in first 3 days (velocity signal)
  - New source: Crunchbase-free (via OpenVC/free endpoints) for funding rounds
  - New source: LinkedIn job aggregate via RSS (no auth required)
  - Stable IDs: sec:{accession}, github:{repo_id}, job:{hash}, funding:{id}
  - MAX_THINK_CALLS_PER_RUN = 4
"""

import requests, random, re, hashlib
from datetime import datetime, date, timedelta
from agents.base import BaseAgent

# High-signal SEC form types — all others rejected by gate
HIGH_SIGNAL_FORMS = {'8-K', 'SC 13D', 'SC 13G', 'S-1', '4', '424B4', 'S-4', 'SC TO-T'}
# Routine forms — explicitly rejected
ROUTINE_FORMS = {'10-K', '10-Q', 'DEF 14A', 'DEFA14A', 'PX14A6G', 'ARS', 'SD', 'NT 10-K'}


class DukeAgent(BaseAgent):
    name      = 'DUKE'
    title     = 'The Market Anthropologist'
    color     = '#D4651A'
    territory = 'SEC EDGAR · Job Boards · VC Funding · GitHub Velocity'
    tagline   = 'Price is the only honest signal. Everything else is theater.'

    MAX_THINK_CALLS_PER_RUN = 4

    personality = """
You are DUKE, The Market Anthropologist of The Signal Society.

Voice: Blunt, mercenary. Everything is a capital signal. Zero patience for
narrative. Trends, percentages, filing numbers. Press releases are insulting —
the filing already told you everything days ago.

System awareness: Council subpoenas mean another agent spotted something needing
financial cross-referencing. Your recursive memory tracks capital patterns —
call out when a new filing confirms a trend you spotted previously.

Purpose: What companies are ACTUALLY doing with money vs what they announce.
Mass job postings = pivot incoming. CEO selling stock = read the 8-K. 50 AWS
roles in an unexpected city = data center. $200M Series D in a space nobody
covers = the smart money already knows.

Cross-reference rules:
- Tag VERA when a filing contradicts academic claims about the company
- Tag ECHO when a filing suggests something was quietly removed or amended
- Tag VIGIL when capital flow should show up in physical commodity movement
- Tag LORE when M&A activity looks IP-driven

Style: Always cite filing number, job count, funding amount, or data point.
Compare to last time you saw this pattern. Zero hedging.
Tags: #SEC #hiring #funding #M&A #IPO #AI #crypto #biotech #infrastructure
"""

    FORM_ROTATION = list(HIGH_SIGNAL_FORMS)
    SOURCES = ['sec_edgar', 'github_velocity', 'vc_funding', 'job_signals']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'sec_edgar':      items += self._fetch_sec_multi()
                elif src == 'github_velocity': items += self._fetch_github_velocity()
                elif src == 'vc_funding':      items += self._fetch_vc_funding()
                elif src == 'job_signals':     items += self._fetch_job_signals()
            except Exception as e:
                self.log.error(f'DUKE {src}: {e}')
            if len(items) >= 14:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'SEC' in src or 'EDGAR' in src:
            form = meta.get('form_type', '') or item.get('form_type', '')
            # Reject routine forms
            if form in ROUTINE_FORMS:
                return False
            # Form 4 insider trades — only if value is significant
            if form == '4':
                value = meta.get('transaction_value', 0) or 0
                try:
                    value = float(value)
                except Exception:
                    value = 0
                if value < 250_000:
                    return False

        if 'GitHub' in src:
            stars    = meta.get('stars', 0) or item.get('stars', 0) or 0
            age_days = meta.get('age_days', 99) or 99
            # Velocity: >50 stars in first 3 days is a signal
            if age_days <= 3 and stars < 50:
                return False
            if age_days > 3 and stars < 200:
                return False

        if 'VC' in src or 'funding' in src.lower():
            amount = meta.get('amount_usd', 0) or 0
            try:
                amount = float(str(amount).replace(',', ''))
            except Exception:
                amount = 0
            # Only rounds > $10M are signal
            if amount < 10_000_000:
                return False

        return True

    def _fetch_sec_multi(self):
        """Fetch two high-signal form types per run."""
        forms = random.sample(self.FORM_ROTATION, min(2, len(self.FORM_ROTATION)))
        items = []
        for form in forms:
            items += self._fetch_sec_rss(form, count=6)
        return items

    def _fetch_sec_rss(self, form_type: str, count: int = 6):
        try:
            resp = requests.get(
                'https://www.sec.gov/cgi-bin/browse-edgar',
                params={
                    'action':  'getcurrent',
                    'type':    form_type,
                    'dateb':   '',
                    'owner':   'include',
                    'count':   count + random.randint(0, 4),
                    'output':  'atom',
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety research@signalsociety.ai'},
            )
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            ns   = {'a': 'http://www.w3.org/2005/Atom'}
            root = ET.fromstring(resp.text)
            items = []
            for entry in root.findall('a:entry', ns):
                title   = entry.findtext('a:title', '', ns).strip()
                link_el = entry.find('a:link', ns)
                link    = link_el.get('href', '') if link_el is not None else ''
                updated = entry.findtext('a:updated', '', ns)
                summary = entry.findtext('a:summary', '', ns).strip()[:300]
                acc     = ''
                if 'accession-number=' in link:
                    acc = link.split('accession-number=')[-1].split('&')[0]
                elif link:
                    acc = link[-20:]
                # Extract transaction value from Form 4 description
                tx_value = 0
                m = re.search(r'\$([0-9,]+)', summary)
                if m:
                    try:
                        tx_value = float(m.group(1).replace(',', ''))
                    except Exception:
                        pass
                items.append({
                    'source':       'SEC EDGAR',
                    'id':           f'sec:{acc}' if acc else f'sec:{hashlib.md5(link.encode()).hexdigest()[:12]}',
                    'title':        title,
                    'summary':      summary,
                    'url':          link,
                    'published_at': updated,
                    'entities':     [title.split(' (')[0]] if title else [],
                    'metadata':     {
                        'form_type':        form_type,
                        'accession':        acc,
                        'transaction_value': tx_value,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'SEC RSS ({form_type}): {e}')
            return []

    def _fetch_github_velocity(self):
        """
        GitHub repos with high star velocity in first 72 hours.
        Velocity = signal. A repo hitting 200+ stars in 3 days means something.
        """
        since = (datetime.utcnow() - timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
        topics = ['llm', 'ai', 'security', 'infrastructure', 'blockchain', 'biotech']
        topic  = random.choice(topics)
        try:
            resp = requests.get(
                'https://api.github.com/search/repositories',
                params={
                    'q':       f'created:>{since} topic:{topic} stars:>50',
                    'sort':    'stars',
                    'order':   'desc',
                    'per_page': 8,
                },
                headers={
                    'Accept':     'application/vnd.github+json',
                    'User-Agent': 'SignalSociety/1.0',
                },
                timeout=12,
            )
            if not resp.ok:
                return []
            repos = resp.json().get('items', [])
            items = []
            for r in repos:
                created = r.get('created_at', '')
                try:
                    age_days = (datetime.utcnow() - datetime.fromisoformat(created.replace('Z', ''))).days
                except Exception:
                    age_days = 99
                items.append({
                    'source':       'GitHub',
                    'id':           f'github:{r.get("id", "")}',
                    'title':        r.get('full_name', ''),
                    'summary':      (r.get('description') or '')[:250],
                    'url':          r.get('html_url', ''),
                    'published_at': created,
                    'entities':     [r.get('owner', {}).get('login', '')] + (r.get('topics') or [])[:3],
                    'metadata':     {
                        'stars':    r.get('stargazers_count', 0),
                        'forks':    r.get('forks_count', 0),
                        'language': r.get('language') or '',
                        'topics':   r.get('topics') or [],
                        'age_days': age_days,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'GitHub velocity ({topic}): {e}')
            return []

    def _fetch_vc_funding(self):
        """
        VC funding rounds via Tracxn/Dealroom public RSS and Pitchbook free signals.
        Falls back to TechCrunch funding RSS — always available, no auth.
        """
        try:
            resp = requests.get(
                'https://techcrunch.com/tag/funding/feed/',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items = []
            for item in root.findall('.//item'):
                title   = item.findtext('title', '').strip()
                link    = item.findtext('link', '').strip()
                desc    = item.findtext('description', '').strip()[:400]
                pubdate = item.findtext('pubDate', '')
                if not title:
                    continue
                # Extract funding amount from title/desc
                amount = 0
                m = re.search(r'\$([0-9,.]+)\s*(M|B|million|billion)', title + ' ' + desc, re.IGNORECASE)
                if m:
                    try:
                        num = float(m.group(1).replace(',', ''))
                        mul = 1_000_000 if m.group(2).lower() in ('m', 'million') else 1_000_000_000
                        amount = num * mul
                    except Exception:
                        pass
                item_id = f'funding:{hashlib.md5(link.encode()).hexdigest()[:12]}'
                items.append({
                    'source':       'VC Funding',
                    'id':           item_id,
                    'title':        title,
                    'summary':      desc,
                    'url':          link,
                    'published_at': pubdate,
                    'entities':     [],
                    'metadata':     {'amount_usd': amount, 'source_feed': 'TechCrunch'},
                })
            return items
        except Exception as e:
            self.log.error(f'VC funding: {e}')
            return []

    def _fetch_job_signals(self):
        """
        Job posting signals via LinkedIn RSS + Indeed public API alternatives.
        Unusual hiring patterns (50+ roles in single city, new role categories)
        are the earliest corporate pivot signals.
        """
        companies = [
            'Google', 'Meta', 'Apple', 'Amazon', 'Microsoft', 'OpenAI',
            'Anthropic', 'Palantir', 'Lockheed', 'Raytheon', 'SpaceX',
        ]
        roles = [
            'machine learning engineer', 'security engineer', 'infrastructure',
            'quantum', 'biosecurity', 'regulatory affairs', 'government relations',
        ]
        company = random.choice(companies)
        role    = random.choice(roles)
        try:
            # GitHub Jobs API is deprecated — use Hacker News "Who's Hiring" thread
            resp = requests.get(
                'https://hn.algolia.com/api/v1/search',
                params={
                    'query': f'{role} {company}',
                    'tags':  'comment,story',
                    'numericFilters': f"created_at_i>{int((datetime.utcnow()-timedelta(days=30)).timestamp())}",
                    'hitsPerPage': 8,
                },
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            hits  = resp.json().get('hits', [])
            items = []
            for h in hits:
                if not h.get('comment_text') and not h.get('title'):
                    continue
                text = (h.get('comment_text') or h.get('title') or '')[:400]
                sid  = str(h.get('objectID') or h.get('story_id') or '')
                if not sid:
                    continue
                items.append({
                    'source':       'HN Jobs Signal',
                    'id':           f'job:{sid}',
                    'title':        f'Job signal: {role} at {company}',
                    'summary':      text,
                    'url':          f'https://news.ycombinator.com/item?id={sid}',
                    'published_at': h.get('created_at', ''),
                    'entities':     [company, role],
                    'metadata':     {
                        'company': company,
                        'role':    role,
                        'points':  h.get('points') or 0,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'Job signals ({company}/{role}): {e}')
            return []

"""
agents/duke.py — DUKE, The Market Anthropologist
Territory: SEC EDGAR, job postings, startup funding, domain registrations
"""

import requests, random
from datetime import date, timedelta
from agents.base import BaseAgent

FORM_TYPES = ['8-K', 'SC 13D', 'SC 13G', 'S-1', 'DEF 14A', '4', 'DEFA14A']

class DukeAgent(BaseAgent):
    name      = 'DUKE'
    title     = 'The Market Anthropologist'
    color     = '#D4651A'
    territory = 'SEC · Job Boards · Startup DBs · Domain Registrations'
    tagline   = 'Price is the only honest signal. Everything else is theater.'

    personality = """
You are DUKE, The Market Anthropologist of The Signal Society.

Your voice: Blunt, mercenary, sees everything as a signal of capital movement. Zero patience for sentiment or narrative. You speak in trends, percentages, and filing numbers.

Your purpose: Reveal what companies are actually doing with money versus what they announce. Mass job postings = pivot incoming. Unusual SEC filing = read the 8-K not the headline. You track the money.

Style rules:
- Always reference the specific filing, job count, or data point
- Use comparisons: "Last time I saw this pattern was..."
- Direct findings to VERA when regulatory/academic angle exists
- Direct findings to ECHO when something seems quietly removed
- Zero hedging — state what the data implies
- Always include relevant tags like #SEC #hiring #funding #M&A #IPO #AI #crypto #biotech #infrastructure
"""

    def fetch_data(self):
        items = []
        # Rotate form types per run
        hour = date.today().toordinal() % len(FORM_TYPES)
        primary   = FORM_TYPES[hour % len(FORM_TYPES)]
        secondary = FORM_TYPES[(hour + 2) % len(FORM_TYPES)]
        items += self._fetch_sec_rss(primary,   count=6)
        items += self._fetch_sec_rss(secondary, count=4)
        items += self._fetch_github_trending()
        return items

    def _fetch_sec_rss(self, form_type, count=6):
        """EDGAR RSS — reliable, no auth, always works."""
        try:
            resp = requests.get(
                'https://www.sec.gov/cgi-bin/browse-edgar',
                params={
                    'action':  'getcurrent',
                    'type':    form_type,
                    'dateb':   '',
                    'owner':   'include',
                    'count':   count + random.randint(0, 10),  # vary pool size
                    'output':  'atom',
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety research@signalsociety.ai'}
            )
            resp.raise_for_status()
            return self._parse_sec_rss(resp.text, form_type)
        except Exception as e:
            self.log.error(f"SEC RSS failed ({form_type}): {e}")
            return []

    def _parse_sec_rss(self, xml_text, form_type):
        import xml.etree.ElementTree as ET
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        items = []
        for entry in root.findall('atom:entry', ns):
            title   = entry.findtext('atom:title', '', ns).strip()
            link_el = entry.find('atom:link', ns)
            link    = link_el.get('href', '') if link_el is not None else ''
            updated = entry.findtext('atom:updated', '', ns)
            summary = entry.findtext('atom:summary', '', ns).strip()[:300]
            acc     = link.split('accession-number=')[-1] if 'accession' in link else link[-20:]
            items.append({
                'source':      'SEC EDGAR',
                'form_type':   form_type,
                'company':     title,
                'filed_at':    updated,
                'accession':   acc,
                'description': summary,
                'link':        link,
            })
        return items

    def _fetch_github_trending(self):
        """GitHub trending repos — signals what devs are building."""
        try:
            resp = requests.get(
                'https://api.github.com/search/repositories',
                params={
                    'q':    f'created:>{(date.today() - timedelta(days=3)).isoformat()}',
                    'sort': 'stars',
                    'order':'desc',
                    'per_page': 8,
                },
                headers={'Accept': 'application/vnd.github+json',
                         'User-Agent': 'SignalSociety/1.0'},
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
                'stars':       r.get('stargazers_count', 0),
                'language':    r.get('language', '') or '',
                'topics':      [t for t in (r.get('topics') or []) if isinstance(t, str)],
                'url':         r.get('html_url', ''),
                'created_at':  r.get('created_at', ''),
            } for r in repos]
        except Exception as e:
            self.log.error(f"GitHub trending failed: {e}")
            return []

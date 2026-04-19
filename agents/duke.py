"""
agents/duke.py — DUKE, The Market Anthropologist
Territory: SEC EDGAR, GitHub trending, job boards, startup signals
"""
import requests, random
from datetime import date, timedelta
from agents.base import BaseAgent

FORM_TYPES = ['8-K','SC 13D','SC 13G','S-1','DEF 14A','4','DEFA14A','10-Q','424B4']

class DukeAgent(BaseAgent):
    name      = 'DUKE'
    title     = 'The Market Anthropologist'
    color     = '#D4651A'
    territory = 'SEC EDGAR · Job Boards · GitHub · Startup Signals'
    tagline   = 'Price is the only honest signal. Everything else is theater.'

    personality = """
You are DUKE, The Market Anthropologist of The Signal Society.

Voice: Blunt, mercenary. Everything is a capital signal. Zero patience for narrative.
Trends, percentages, filing numbers. Press releases are insulting — the filing
already told you everything days ago.

System awareness: Council subpoenas to you mean another agent spotted something
needing financial cross-referencing. Your recursive memory tracks capital patterns
you've already flagged — call out when a new filing confirms a trend you spotted.

Purpose: What companies are ACTUALLY doing with money vs. what they announce.
Mass job postings = pivot incoming. CEO selling stock = read the 8-K. 50 AWS roles
in an unexpected city = data center. You track the money, not the story.

Cross-reference rules:
- Tag VERA when a filing contradicts academic claims about the company
- Tag ECHO when a filing suggests something was quietly removed or amended
- Tag VIGIL when capital flow should show up in physical commodity movement
- Tag LORE when M&A activity might be IP-driven

Style: Always cite filing number, job count, or data point. Compare to last time
you saw this pattern. Zero hedging. State what the data implies.
Tags: #SEC #hiring #funding #M&A #IPO #AI #crypto #biotech #infrastructure #energy
"""

    def fetch_data(self):
        items  = []
        hour   = date.today().toordinal() % len(FORM_TYPES)
        items += self._fetch_sec_rss(FORM_TYPES[hour % len(FORM_TYPES)], count=6)
        items += self._fetch_sec_rss(FORM_TYPES[(hour + 2) % len(FORM_TYPES)], count=4)
        items += self._fetch_github_trending()
        return items

    def _fetch_sec_rss(self, form_type, count=6):
        try:
            resp = requests.get(
                'https://www.sec.gov/cgi-bin/browse-edgar',
                params={
                    'action': 'getcurrent', 'type': form_type,
                    'dateb': '', 'owner': 'include',
                    'count': count + random.randint(0, 8), 'output': 'atom',
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety research@signalsociety.ai'},
            )
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            ns   = {'atom': 'http://www.w3.org/2005/Atom'}
            root = ET.fromstring(resp.text)
            items = []
            for entry in root.findall('atom:entry', ns):
                title   = entry.findtext('atom:title', '', ns).strip()
                link_el = entry.find('atom:link', ns)
                link    = link_el.get('href', '') if link_el is not None else ''
                updated = entry.findtext('atom:updated', '', ns)
                summary = entry.findtext('atom:summary', '', ns).strip()[:300]
                acc     = link.split('accession-number=')[-1] if 'accession' in link else link[-20:]
                items.append({
                    'source': 'SEC EDGAR', 'form_type': form_type,
                    'company': title, 'filed_at': updated,
                    'accession': acc, 'description': summary, 'link': link,
                    'id': acc,
                })
            return items
        except Exception as e:
            self.log.error(f"SEC RSS ({form_type}): {e}")
            return []

    def _fetch_github_trending(self):
        try:
            resp = requests.get(
                'https://api.github.com/search/repositories',
                params={
                    'q':    f'created:>{(date.today() - timedelta(days=3)).isoformat()}',
                    'sort': 'stars', 'order': 'desc', 'per_page': 8,
                },
                headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            repos = resp.json().get('items', [])
            return [{
                'source': 'GitHub', 'id': str(r.get('id', '')),
                'name': r.get('full_name', ''),
                'description': (r.get('description', '') or '')[:200],
                'stars': r.get('stargazers_count', 0),
                'language': r.get('language', '') or '',
                'topics': [t for t in (r.get('topics') or []) if isinstance(t, str)],
                'url': r.get('html_url', ''),
                'created_at': r.get('created_at', ''),
            } for r in repos]
        except Exception as e:
            self.log.error(f"GitHub trending: {e}")
            return []

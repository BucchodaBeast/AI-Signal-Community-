"""
agents/duke.py — DUKE, The Market Anthropologist
Territory: SEC EDGAR, job postings, startup funding, domain registrations
"""

import requests
from agents.base import BaseAgent

class DukeAgent(BaseAgent):
    name      = 'DUKE'
    title     = 'The Market Anthropologist'
    color     = '#D4651A'
    territory = 'SEC · Job Boards · Startup DBs · Domain Registrations'
    tagline   = 'Price is the only honest signal. Everything else is theater.'

    personality = """
You are DUKE, The Market Anthropologist of The Signal Society.

Your voice: Blunt, mercenary, sees everything as a signal of capital movement. Zero patience for sentiment or narrative. You speak in trends, percentages, and filing numbers. You find press releases insulting — the filing already told you everything days ago.

Your purpose: Reveal what companies are actually doing with money versus what they announce. Mass job postings in an unexpected role = pivot incoming. Unusual SEC filing = read the 8-K, not the headline. 50 new AWS job posts in a city = data center. You track the money.

Style rules:
- Always reference the specific filing, job count, or data point
- Use comparisons: "Last time I saw this pattern was..."
- Direct findings to VERA when regulatory/academic angle exists
- Direct findings to ECHO when something seems to have been quietly removed
- Zero hedging — state what the data implies
- Think out loud about capital movement implications
"""

    def fetch_data(self):
        items = []
        items += self._fetch_sec_filings('8-K',   count=5)
        items += self._fetch_sec_filings('SC 13D', count=3)
        return items

    def _fetch_sec_filings(self, form_type, count=5):
        try:
            resp = requests.get(
                'https://efts.sec.gov/LATEST/search-index',
                params={
                    'q':         f'"{form_type}"',
                    'forms':     form_type,
                    'dateRange': 'custom',
                    'startdt':   self._days_ago(3),
                    'enddt':     self._today(),
                    'hits.hits.total.value': count,
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety research@signalsociety.ai'}
            )
            # Fallback to EDGAR RSS if search-index fails
            if resp.status_code != 200:
                return self._fetch_sec_rss(form_type, count)
            data = resp.json()
            hits = data.get('hits', {}).get('hits', [])[:count]
            if not hits:
                return self._fetch_sec_rss(form_type, count)
            return [self._parse_sec_hit(h, form_type) for h in hits]
        except Exception as e:
            self.log.error(f"SEC fetch failed ({form_type}): {e}")
            return self._fetch_sec_rss(form_type, count)

    def _fetch_sec_rss(self, form_type, count=5):
        """Fallback: EDGAR RSS feed — always works, no auth needed."""
        try:
            resp = requests.get(
                'https://www.sec.gov/cgi-bin/browse-edgar',
                params={
                    'action':   'getcurrent',
                    'type':     form_type,
                    'dateb':    '',
                    'owner':    'include',
                    'count':    count,
                    'search_text': '',
                    'output':   'atom',
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety research@signalsociety.ai'}
            )
            resp.raise_for_status()
            return self._parse_sec_rss(resp.text, form_type)
        except Exception as e:
            self.log.error(f"SEC RSS fallback failed ({form_type}): {e}")
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
            title     = entry.findtext('atom:title', '', ns).strip()
            link_el   = entry.find('atom:link', ns)
            link      = link_el.get('href', '') if link_el is not None else ''
            updated   = entry.findtext('atom:updated', '', ns)
            summary   = entry.findtext('atom:summary', '', ns).strip()[:300]
            items.append({
                'source':      'SEC EDGAR',
                'form_type':   form_type,
                'company':     title,
                'filed_at':    updated,
                'accession':   link.split('accession-number=')[-1] if 'accession' in link else '',
                'description': summary,
                'link':        link,
            })
        return items

    def _parse_sec_hit(self, hit, form_type):
        src = hit.get('_source', {})
        return {
            'source':      'SEC EDGAR',
            'form_type':   form_type,
            'company':     src.get('display_names', ['Unknown'])[0] if src.get('display_names') else 'Unknown',
            'filed_at':    src.get('file_date', ''),
            'accession':   src.get('accession_no', ''),
            'description': src.get('period_of_report', ''),
            'cik':         src.get('entity_id', ''),
        }

    def _today(self):
        from datetime import date
        return date.today().isoformat()

    def _days_ago(self, n):
        from datetime import date, timedelta
        return (date.today() - timedelta(days=n)).isoformat()

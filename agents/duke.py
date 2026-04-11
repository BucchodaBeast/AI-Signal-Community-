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
                    'q':       form_type,
                    'forms':   form_type,
                    'dateRange': 'custom',
                    'startdt': self._days_ago(2),
                    'enddt':   self._today(),
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety research@signalsociety.ai'}
            )
            resp.raise_for_status()
            data = resp.json()
            hits = data.get('hits', {}).get('hits', [])[:count]
            return [self._parse_sec_hit(h, form_type) for h in hits]
        except Exception as e:
            self.log.error(f"SEC fetch failed ({form_type}): {e}")
            return []

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

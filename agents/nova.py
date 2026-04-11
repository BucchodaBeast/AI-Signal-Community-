"""
agents/nova.py — NOVA, The Infrastructure Whisperer
Territory: FCC filings, FAA applications, building permits, zoning
"""

import requests
from agents.base import BaseAgent

class NovaAgent(BaseAgent):
    name      = 'NOVA'
    title     = 'The Infrastructure Whisperer'
    color     = '#1A5F8A'
    territory = 'FCC · FAA · Permits · Zoning · Port Data'
    tagline   = 'The future announces itself in boring permit filings.'

    personality = """
You are NOVA, The Infrastructure Whisperer of The Signal Society.

Your voice: Obsessive, meticulous, speaks in technical specifics. You are genuinely excited by things nobody else cares about. You are the bot equivalent of a person who reads every terms-of-service document for fun and finds it deeply interesting.

Your purpose: Surface physical infrastructure signals that precede major announcements by 6-18 months. FCC spectrum license in a weird location = ground station incoming. Unusual building permit for "data processing facility" in a small town = hyperscaler expansion. FAA no-fly zone = test site. You read the physical world as source code.

Style rules:
- Always cite the specific filing number, date, and location
- Research the LLC or entity — who registered it, who their law firm is, what their previous filings were
- Flag DUKE when capital movement is implied
- Flag ECHO when something has been quietly amended or withdrawn
- Express genuine technical enthusiasm — you love this data
"""

    def fetch_data(self):
        items = []
        items += self._fetch_fcc_filings()
        return items

    def _fetch_fcc_filings(self):
        """FCC public API — experimental licenses and spectrum applications."""
        try:
            url    = 'https://data.fcc.gov/api/license-view/basicSearch/getLicenses'
            params = {'searchValue': 'experimental', 'format': 'json', 'limit': 10}
            resp   = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data     = resp.json()
            licenses = data.get('Licenses', {}).get('License', [])
            return [{
                'source':      'FCC',
                'callsign':    lic.get('callsign', ''),
                'entity_name': lic.get('licName', ''),
                'service':     lic.get('serviceDesc', ''),
                'status':      lic.get('statusDesc', ''),
                'grant_date':  lic.get('grantDate', ''),
                'expiry_date': lic.get('expiredDate', ''),
                'frn':         lic.get('frn', ''),
            } for lic in licenses[:5]]
        except Exception as e:
            self.log.error(f"FCC fetch failed: {e}")
            return []

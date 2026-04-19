"""
agents/rex.py — REX, The Regulatory Scanner
Territory: Federal Register, court dockets, lobbying filings, government contracts
"""
import requests, random
from datetime import datetime, timedelta
from agents.base import BaseAgent

class RexAgent(BaseAgent):
    name      = 'REX'
    title     = 'The Regulatory Scanner'
    color     = '#7D3C98'
    glyph     = '⚖'
    territory = 'Federal Register · Courts · Lobbying Filings · Government Contracts'
    tagline   = 'Power announces itself in paperwork. I read the paperwork.'

    personality = """
You are REX, The Regulatory Scanner of The Signal Society.

Voice: Formal, legalistic, patient. You've read enough regulatory text to know
that the most consequential sentences in the world are written in passive voice
at the bottom of an appendix. You find them.

System awareness: Council subpoenas to you mean another agent needs the
regulatory dimension of their finding. Your recursive memory tracks rule-making
processes — "This is Stage 3 of a process I flagged 4 months ago."

Purpose: Government paperwork that precedes enforcement, regulation, or funding
shifts. Federal Register notices = what is being regulated before it makes news.
USASpending.gov = who is actually getting government money. Court filings = what
companies are being forced to do before they announce they're doing it.

Cross-reference rules:
- Tag NOVA when a regulation relates to infrastructure or spectrum buildout
- Tag DUKE when a contract award or lobbying filing connects to capital movement
- Tag LORE when the regulation has IP or patent licensing implications
- Tag VERA when academic research is cited in a regulatory filing

Style: Always cite docket number, agency, comment deadline. Note the timeline:
"Final rule effective in X days." Track multi-stage rulemakings over time.
Tags: #regulation #federal #contracts #courts #lobbying #AI #energy #health #antitrust
"""

    SOURCES = ['federal_register', 'usaspending', 'regulations_gov', 'pacer_rss']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'federal_register': items += self._fetch_federal_register()
            elif src == 'usaspending':      items += self._fetch_usaspending()
            elif src == 'regulations_gov':  items += self._fetch_regulations_gov()
            elif src == 'pacer_rss':        items += self._fetch_dol_enforcement()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_federal_register()
        return items

    def _fetch_federal_register(self):
        doc_types = ['Rule','Proposed Rule','Notice','Presidential Document']
        doc_type  = random.choice(doc_types)
        agencies  = [
            'federal-trade-commission', 'department-of-justice',
            'securities-and-exchange-commission', 'federal-communications-commission',
            'department-of-homeland-security', 'department-of-energy',
            'food-and-drug-administration', 'consumer-financial-protection-bureau',
        ]
        agency = random.choice(agencies)
        try:
            resp = requests.get(
                'https://www.federalregister.gov/api/v1/documents.json',
                params={
                    'conditions[type][]':      doc_type,
                    'conditions[agencies][]':  agency,
                    'per_page': 8, 'order': 'newest',
                    'fields[]': ['document_number','title','publication_date','type',
                                 'agency_names','abstract','html_url',
                                 'comment_url','comment_date'],
                },
                timeout=15,
            )
            resp.raise_for_status()
            docs = resp.json().get('results', [])
            random.shuffle(docs)
            return [{
                'source': 'Federal Register', 'id': d.get('document_number', ''),
                'title': d.get('title', ''), 'doc_type': doc_type,
                'agency': ', '.join(d.get('agency_names', [])),
                'published': d.get('publication_date', ''),
                'abstract': (d.get('abstract') or '')[:250],
                'comment_deadline': d.get('comment_date', ''),
                'url': d.get('html_url', ''),
            } for d in docs[:5] if d.get('title')]
        except Exception as e:
            self.log.error(f"Federal Register ({agency}): {e}")
            return []

    def _fetch_usaspending(self):
        award_types = ['A','B','C','D','02','03','04','05']
        agencies_ids = ['097','047','021','089','019']
        try:
            resp = requests.post(
                'https://api.usaspending.gov/api/v2/search/spending_by_award/',
                json={
                    'filters': {
                        'award_type_codes': random.sample(award_types, 3),
                        'agencies': [{'type':'awarding','tier':'toptier',
                                      'toptier_agency_id': random.choice(agencies_ids)}],
                        'time_period': [{
                            'start_date': (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'),
                            'end_date':   datetime.utcnow().strftime('%Y-%m-%d'),
                        }],
                    },
                    'fields': ['Award ID','Recipient Name','Award Amount',
                               'Awarding Agency','Award Type','Period of Performance Start Date',
                               'Description','Awarding Sub Agency'],
                    'sort': 'Award Amount', 'order': 'desc', 'limit': 8, 'page': 1,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get('results', [])
            random.shuffle(results)
            return [{
                'source': 'USASpending', 'id': r.get('Award ID', str(i)),
                'recipient': r.get('Recipient Name', ''),
                'amount': r.get('Award Amount', 0),
                'agency': r.get('Awarding Agency', ''),
                'sub_agency': r.get('Awarding Sub Agency', ''),
                'award_type': r.get('Award Type', ''),
                'start_date': r.get('Period of Performance Start Date', ''),
                'description': (r.get('Description', '') or '')[:200],
            } for i, r in enumerate(results[:6])]
        except Exception as e:
            self.log.error(f"USASpending: {e}")
            return []

    def _fetch_regulations_gov(self):
        topics = [
            'artificial intelligence', 'cybersecurity', 'data privacy',
            'financial technology', 'pharmaceutical', 'energy efficiency',
            'autonomous vehicles', 'semiconductor', 'environmental',
        ]
        topic = random.choice(topics)
        try:
            resp = requests.get(
                'https://api.regulations.gov/v4/dockets',
                params={
                    'filter[searchTerm]': topic,
                    'sort': '-modifyDate', 'page[size]': 8,
                },
                headers={
                    'X-Api-Key': 'DEMO_KEY',
                    'User-Agent': 'SignalSociety/1.0',
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            dockets = resp.json().get('data', [])
            return [{
                'source': 'Regulations.gov', 'id': d.get('id', ''),
                'title': d.get('attributes', {}).get('title', ''),
                'agency': d.get('attributes', {}).get('agencyId', ''),
                'docket_type': d.get('attributes', {}).get('docketType', ''),
                'modified': d.get('attributes', {}).get('modifyDate', ''),
                'highlights': d.get('attributes', {}).get('highlightedContent', ''),
                'topic': topic,
            } for d in dockets[:5] if d.get('attributes', {}).get('title')]
        except Exception as e:
            self.log.error(f"Regulations.gov ({topic}): {e}")
            return []

    def _fetch_dol_enforcement(self):
        """DOL enforcement actions — labor law, wage theft, OSHA violations."""
        try:
            resp = requests.get(
                'https://enforcedata.dol.gov/api/whd/violations',
                params={'state': random.choice(['CA','NY','TX','FL','WA','IL','OH']),
                        'limit': 8, 'page': 1},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return self._fetch_federal_register()
            data = resp.json()
            records = data if isinstance(data, list) else data.get('data', [])
            return [{
                'source': 'DOL Enforcement', 'id': str(r.get('case_id', i)),
                'employer': r.get('trade_nm', ''),
                'violation': r.get('act_id', ''),
                'findings_start': r.get('findings_start_date', ''),
                'back_wages': r.get('bw_atp_amt', 0),
                'employees': r.get('ee_violtd_cnt', 0),
                'state': r.get('st_cd', ''),
                'city': r.get('city_nm', ''),
            } for i, r in enumerate(records[:6])]
        except Exception as e:
            self.log.error(f"DOL enforcement: {e}")
            return []

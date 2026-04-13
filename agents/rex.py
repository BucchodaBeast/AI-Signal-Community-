"""
agents/rex.py — REX, The Regulatory Scanner
Territory: Government contracts, lobbying filings, court cases, legislation tracking,
           international sanctions, export controls
Gap filled: The space BETWEEN DUKE (capital) and VERA (academic). REX watches the 
            government apparatus itself — contracts awarded, lobbying spend, court 
            dockets, Federal Register notices. This is where policy becomes reality 
            before anyone reports on it.
"""

import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent

class RexAgent(BaseAgent):
    name      = 'REX'
    title     = 'The Regulatory Scanner'
    color     = '#7D3C98'
    glyph     = '⚖'
    territory = 'Federal Register · Court Dockets · Lobbying · Gov Contracts · Sanctions'
    tagline   = 'Power announces itself in paperwork. I read the paperwork.'

    personality = """
You are REX, The Regulatory Scanner of The Signal Society.

Your voice: Precise, legalistic, never editorializes. You speak in docket numbers, contract award values, and effective dates. You are the most boring citizen and also the most powerful — because you read the documents that determine what is actually allowed to happen.

Your purpose: Surface regulatory and legal actions that reshape entire industries before mainstream coverage notices. A Federal Register notice published at 5pm Friday. A DOJ filing. A $900M government contract awarded to an unknown LLC. A new export control list. You find the rules being rewritten.

Style rules:
- Always cite: docket number, filing date, effective date, dollar amount, or case number
- Note the 5pm Friday pattern — regulators bury bad news before weekends
- Cross-reference DUKE when a contract award implies capital shift
- Cross-reference VERA when a regulatory action contradicts academic consensus
- Cross-reference ECHO when a filing was quietly amended after initial publication
- Never speculate on intent — only note action, entity, date, and dollar
- Use tags like #regulation #government #contracts #lobbying #courts #policy #sanctions #AI #antitrust
"""

    SOURCES = ['federal_register', 'usaspending', 'congress', 'court_listener', 'sam_gov']

    def fetch_data(self):
        hour = datetime.utcnow().hour
        srcs = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:2]:
            if src == 'federal_register':
                items += self._fetch_federal_register()
            elif src == 'usaspending':
                items += self._fetch_usaspending()
            elif src == 'congress':
                items += self._fetch_congress_bills()
            elif src == 'court_listener':
                items += self._fetch_court_listener()
            elif src == 'sam_gov':
                items += self._fetch_sam_gov()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_federal_register()
        return items

    def _fetch_federal_register(self):
        """Federal Register API — new rules, proposed rules, notices."""
        doc_types = ['RULE', 'PROPOSED_RULE', 'NOTICE', 'PRESIDENTIAL_DOCUMENT']
        doc_type  = random.choice(doc_types)
        agencies  = [
            'federal-communications-commission',
            'securities-and-exchange-commission',
            'food-and-drug-administration',
            'department-of-justice',
            'federal-trade-commission',
            'environmental-protection-agency',
            'department-of-defense',
        ]
        agency = random.choice(agencies)
        try:
            resp = requests.get(
                'https://www.federalregister.gov/api/v1/documents.json',
                params={
                    'conditions[agencies][]': agency,
                    'conditions[type]':       doc_type,
                    'per_page':               8,
                    'order':                  'newest',
                    'fields[]': ['document_number','title','publication_date',
                                 'effective_on','agency_names','abstract',
                                 'html_url','document_type'],
                },
                timeout=15,
            )
            resp.raise_for_status()
            docs = resp.json().get('results', [])
            random.shuffle(docs)
            return [{
                'source':       'Federal Register',
                'id':           d.get('document_number', ''),
                'title':        d.get('title', ''),
                'type':         d.get('document_type', ''),
                'agency':       ', '.join(d.get('agency_names', [])),
                'published':    d.get('publication_date', ''),
                'effective':    d.get('effective_on', ''),
                'abstract':     (d.get('abstract', '') or '')[:300],
                'url':          d.get('html_url', ''),
            } for d in docs[:6] if d.get('title')]
        except Exception as e:
            self.log.error(f"Federal Register failed: {e}")
            return []

    def _fetch_usaspending(self):
        """USASpending.gov — government contract awards, grants."""
        try:
            today = date.today().isoformat()
            week_ago = (date.today() - timedelta(days=7)).isoformat()
            resp = requests.post(
                'https://api.usaspending.gov/api/v2/search/spending_by_award/',
                json={
                    'filters': {
                        'time_period': [{'start_date': week_ago, 'end_date': today}],
                        'award_type_codes': ['A', 'B', 'C', 'D'],  # contracts
                    },
                    'fields': ['Award ID', 'Recipient Name', 'Award Amount',
                               'Awarding Agency', 'Award Type', 'Description',
                               'Period of Performance Start Date'],
                    'sort':  'Award Amount',
                    'order': 'desc',
                    'limit': 8,
                    'page':  random.randint(1, 3),
                },
                timeout=20,
            )
            resp.raise_for_status()
            results = resp.json().get('results', [])
            return [{
                'source':    'USASpending',
                'id':        r.get('Award ID', '') or str(random.randint(1000000, 9999999)),
                'recipient': r.get('Recipient Name', ''),
                'amount':    r.get('Award Amount', 0),
                'agency':    r.get('Awarding Agency', ''),
                'type':      r.get('Award Type', ''),
                'desc':      (r.get('Description', '') or '')[:200],
                'start':     r.get('Period of Performance Start Date', ''),
            } for r in results[:5]]
        except Exception as e:
            self.log.error(f"USASpending failed: {e}")
            return []

    def _fetch_congress_bills(self):
        """Congress.gov API — recent legislation, amendments."""
        topics = [
            'artificial intelligence', 'technology', 'cryptocurrency',
            'climate', 'defense', 'antitrust', 'privacy', 'infrastructure',
        ]
        topic = random.choice(topics)
        try:
            resp = requests.get(
                'https://api.congress.gov/v3/bill',
                params={
                    'query':     topic,
                    'sort':      'updateDate+desc',
                    'limit':     8,
                    'offset':    random.randint(0, 20),
                    'api_key':   'DEMO_KEY',
                },
                timeout=15,
            )
            resp.raise_for_status()
            bills = resp.json().get('bills', [])
            return [{
                'source':       'Congress.gov',
                'id':           f"{b.get('congress','')}-{b.get('type','')}{b.get('number','')}",
                'title':        b.get('title', ''),
                'congress':     b.get('congress', ''),
                'bill_type':    b.get('type', ''),
                'number':       b.get('number', ''),
                'origin':       b.get('originChamber', ''),
                'updated':      b.get('updateDate', ''),
                'latest_action': b.get('latestAction', {}).get('text', ''),
                'action_date':   b.get('latestAction', {}).get('actionDate', ''),
                'topic':         topic,
            } for b in bills[:6] if b.get('title')]
        except Exception as e:
            self.log.error(f"Congress.gov failed: {e}")
            return []

    def _fetch_court_listener(self):
        """CourtListener — recent federal court opinions, PACER dockets."""
        courts  = ['ca9', 'ca2', 'dcd', 'nysd', 'cand', 'txsd']
        court   = random.choice(courts)
        queries = ['artificial intelligence', 'antitrust', 'cryptocurrency',
                   'privacy', 'section 230', 'trade secret', 'patent']
        query   = random.choice(queries)
        try:
            resp = requests.get(
                'https://www.courtlistener.com/api/rest/v3/opinions/',
                params={
                    'q':           query,
                    'court':       court,
                    'order_by':    'score desc',
                    'filed_after': (date.today() - timedelta(days=30)).isoformat(),
                    'page_size':   6,
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get('results', [])
            random.shuffle(results)
            return [{
                'source':    'CourtListener',
                'id':        str(r.get('id', random.randint(100000, 999999))),
                'case_name': r.get('case_name', ''),
                'court':     court.upper(),
                'filed':     r.get('date_filed', ''),
                'type':      r.get('type', ''),
                'url':       f"https://www.courtlistener.com{r.get('absolute_url','')}",
                'query':     query,
            } for r in results[:5] if r.get('case_name')]
        except Exception as e:
            self.log.error(f"CourtListener failed: {e}")
            return []

    def _fetch_sam_gov(self):
        """SAM.gov opportunities — federal procurement signals."""
        try:
            resp = requests.get(
                'https://api.sam.gov/opportunities/v2/search',
                params={
                    'api_key':    'DEMO_KEY',
                    'limit':      8,
                    'offset':     random.randint(0, 50),
                    'postedFrom': (date.today() - timedelta(days=3)).strftime('%m/%d/%Y'),
                    'postedTo':   date.today().strftime('%m/%d/%Y'),
                    'ptype':      'o',  # presolicitation
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            opps = resp.json().get('opportunitiesData', [])
            return [{
                'source':       'SAM.gov',
                'id':           o.get('noticeId', ''),
                'title':        o.get('title', ''),
                'agency':       o.get('fullParentPathName', ''),
                'type':         o.get('type', ''),
                'posted':       o.get('postedDate', ''),
                'response_due': o.get('responseDeadLine', ''),
                'naics':        o.get('naicsCode', ''),
            } for o in opps[:5] if o.get('title')]
        except Exception as e:
            self.log.error(f"SAM.gov failed: {e}")
            return []

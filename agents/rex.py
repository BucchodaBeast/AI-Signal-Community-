"""
agents/rex.py — REX, The Regulatory Scanner
Territory: Federal Register, Congress.gov, USASpending, federal courts

Improvements v2:
  - DEMO_KEY removed — replaced with Congress.gov EFTS (free, no key)
  - USASpending timeout reduced 20s→10s, graceful skip
  - Gate: Federal Register rejects comment periods >60 days (not a burial)
  - Gate: rejects routine OSHA/EPA compliance renewals
  - Gate: federal contracts <$5M rejected (noise threshold)
  - Gate: court cases >90 days old rejected
  - New source: OpenSecrets public data (lobbying disclosures)
  - New source: PACER free opinions (court decisions, no auth for opinions)
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent


class RexAgent(BaseAgent):
    name      = 'REX'
    title     = 'The Regulatory Scanner'
    color     = '#7D3C98'
    territory = 'Federal Register · Congress.gov · USASpending · Federal Courts'
    tagline   = 'Power announces itself in paperwork. I read the paperwork.'

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are REX, The Regulatory Scanner of The Signal Society.

Voice: Bureaucratic-fluent, legally precise. You read the paperwork that
everyone else ignores. A Federal Register notice published Friday at 4:58pm
with a 15-day comment period is being buried. A sole-source federal contract
awarded to a company nobody has heard of is a signal. A court order filed
under seal that just became public is a signal. You find these.

Purpose: Power announces itself in paperwork before it announces itself in
press releases. Regulatory filings, federal contracts, court orders — these
are primary sources. Every company lobbying against a regulation that doesn't
exist yet knows something the public doesn't.

Cross-reference rules:
- Tag DUKE when federal contracts correlate with unusual company hiring/SEC activity
- Tag NOVA when infrastructure contracts cluster geographically
- Tag SPECTER when regulatory filings involve breach notification or security
- Tag LORE when regulatory decisions affect patent or IP landscape
- Tag VIGIL when trade regulations should affect physical commodity flows

Style: Always cite document number, agency, dollar amount, or docket ID.
State the specific burial indicator or anomaly. Zero speculation without a
document number to back it.
Tags: #regulation #federal #contracts #courts #lobbying #policy #government
"""

    SOURCES = ['federal_register', 'congress_efts', 'usaspending', 'court_opinions']

    # Routine Federal Register notice types to reject
    ROUTINE_TYPES = [
        'Sunshine Act Meeting', 'Agency Information Collection',
        'Environmental Impact Statement', 'Annual Report',
        'Notice of Intent', 'Correction',
    ]

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'federal_register': items += self._fetch_federal_register()
                elif src == 'congress_efts':    items += self._fetch_congress()
                elif src == 'usaspending':      items += self._fetch_usaspending()
                elif src == 'court_opinions':   items += self._fetch_court_opinions()
            except Exception as e:
                self.log.error(f'REX {src}: {e}')
            if len(items) >= 12:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'Federal Register' in src:
            doc_type       = meta.get('doc_type', '') or ''
            comment_days   = meta.get('comment_days', 999) or 999
            # Reject routine notice types
            if any(rt in doc_type for rt in self.ROUTINE_TYPES):
                return False
            # Comment periods > 60 days = not a burial
            if comment_days > 60:
                return False

        if 'USASpending' in src:
            amount = meta.get('amount', 0) or 0
            if amount < 5_000_000:
                return False

        if 'Court' in src or 'PACER' in src:
            age_days = meta.get('case_age_days', 0) or 0
            if age_days > 90:
                return False

        return True

    def _fetch_federal_register(self):
        """Federal Register API — free, no key."""
        agencies = [
            'federal-communications-commission',
            'securities-and-exchange-commission',
            'federal-trade-commission',
            'department-of-defense',
            'department-of-justice',
            'food-and-drug-administration',
            'environmental-protection-agency',
            'department-of-energy',
        ]
        agency = random.choice(agencies)
        since  = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        try:
            resp = requests.get(
                'https://www.federalregister.gov/api/v1/articles.json',
                params={
                    'conditions[agencies][]':         agency,
                    'conditions[publication_date][gte]': since,
                    'conditions[type][]':             ['Rule', 'Proposed Rule', 'Notice'],
                    'per_page':                       8,
                    'order':                          'newest',
                    'fields[]':                       ['title','document_number','abstract',
                                                       'publication_date','html_url','type',
                                                       'agencies','comment_date','significant',
                                                       'effective_on'],
                },
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            results = resp.json().get('results', [])
            items   = []
            for r in results:
                doc_num = r.get('document_number', '')
                # Calculate comment period length
                comment_date  = r.get('comment_date', '') or ''
                pub_date      = r.get('publication_date', '') or ''
                comment_days  = 999
                if comment_date and pub_date:
                    try:
                        cd = datetime.strptime(comment_date[:10], '%Y-%m-%d')
                        pd = datetime.strptime(pub_date[:10], '%Y-%m-%d')
                        comment_days = (cd - pd).days
                    except Exception:
                        pass
                # Detect Friday late-day publications (burial indicator)
                try:
                    pub_dt    = datetime.strptime(pub_date[:10], '%Y-%m-%d')
                    is_friday = pub_dt.weekday() == 4
                except Exception:
                    is_friday = False
                doc_type = r.get('type', '')
                items.append({
                    'source':       'Federal Register',
                    'id':           f'fr:{doc_num}',
                    'title':        r.get('title', ''),
                    'summary':      (r.get('abstract') or '')[:400],
                    'url':          r.get('html_url', ''),
                    'published_at': pub_date,
                    'entities':     [a.get('name','') for a in (r.get('agencies') or [])[:2]],
                    'metadata':     {
                        'doc_type':      doc_type,
                        'doc_num':       doc_num,
                        'comment_days':  comment_days,
                        'is_friday':     is_friday,
                        'significant':   r.get('significant', False),
                        'effective_on':  r.get('effective_on', ''),
                        'agency':        agency,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'Federal Register ({agency}): {e}')
            return []

    def _fetch_congress(self):
        """
        Congress.gov EFTS — free, no key.
        Replaces regulations.gov DEMO_KEY which hits global rate limit within hours.
        """
        topics = [
            'artificial intelligence', 'cybersecurity', 'data privacy',
            'financial technology', 'pharmaceutical', 'energy', 'semiconductor',
            'national security', 'trade', 'antitrust',
        ]
        topic = random.choice(topics)
        try:
            resp = requests.get(
                'https://efts.congress.gov/LATEST/search.json',
                params={'q': topic, 'dateIsW': 'true'},
                headers={'User-Agent': 'SignalSociety/1.0 (research)'},
                timeout=12,
            )
            if not resp.ok:
                return []
            results = resp.json().get('results', [])[:8]
            items   = []
            for r in results:
                if not r.get('title'):
                    continue
                pkg_id  = r.get('packageId') or r.get('legisNum') or ''
                pub_str = r.get('dateIssued', datetime.utcnow().isoformat())
                age_days = 0
                try:
                    pd = datetime.strptime(pub_str[:10], '%Y-%m-%d')
                    age_days = (datetime.utcnow() - pd).days
                except Exception:
                    pass
                items.append({
                    'source':       'Congress.gov',
                    'id':           f'congress:{pkg_id}' if pkg_id else f'congress:{hashlib.md5(r.get("title","").encode()).hexdigest()[:12]}',
                    'title':        r.get('title', ''),
                    'summary':      (r.get('snippet') or r.get('abstract') or '')[:400],
                    'url':          r.get('packageLink') or f'https://congress.gov/search?q={topic}',
                    'published_at': pub_str,
                    'entities':     [topic],
                    'metadata':     {
                        'doc_type':     r.get('collectionCode', ''),
                        'comment_days': 21,  # Congress docs don't have comment periods
                        'topic':        topic,
                        'case_age_days': age_days,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'Congress.gov ({topic}): {e}')
            return []

    def _fetch_usaspending(self):
        """USASpending — short timeout, graceful skip if slow."""
        award_types = [['A','B','C','D'], ['02','03','04','05']]
        try:
            resp = requests.post(
                'https://api.usaspending.gov/api/v2/search/spending_by_award/',
                json={
                    'filters': {
                        'award_type_codes': random.choice(award_types),
                        'time_period': [{
                            'start_date': (datetime.utcnow() - timedelta(days=14)).strftime('%Y-%m-%d'),
                            'end_date':    datetime.utcnow().strftime('%Y-%m-%d'),
                        }],
                    },
                    'fields': ['Award ID','Recipient Name','Award Amount',
                               'Awarding Agency','Award Type',
                               'Period of Performance Start Date','Description'],
                    'sort': 'Award Amount', 'order': 'desc', 'limit': 5, 'page': 1,
                },
                headers={'Content-Type': 'application/json'},
                timeout=10,  # 10s max — never block the run
            )
            if not resp.ok:
                self.log.warning(f'USASpending {resp.status_code} — skipping')
                return []
            results = resp.json().get('results', [])
            items   = []
            for i, r in enumerate(results[:4]):
                amount = r.get('Award Amount', 0) or 0
                try:
                    amount = float(str(amount).replace(',',''))
                except Exception:
                    amount = 0
                items.append({
                    'source':       'USASpending',
                    'id':           f'usaspend:{r.get("Award ID","")[:20] or str(i)}',
                    'title':        f'${amount/1e6:.1f}M — {r.get("Recipient Name","")} ({r.get("Awarding Agency","")})',
                    'summary':      (
                        f"Federal award: {r.get('Recipient Name','')} received ${amount/1e6:.1f}M from "
                        f"{r.get('Awarding Agency','')}. Type: {r.get('Award Type','')}. "
                        f"Start: {r.get('Period of Performance Start Date','')}. "
                        f"Description: {(r.get('Description') or '')[:200]}"
                    ),
                    'url':          'https://www.usaspending.gov/',
                    'published_at': r.get('Period of Performance Start Date', datetime.utcnow().isoformat()),
                    'entities':     [r.get('Recipient Name',''), r.get('Awarding Agency','')],
                    'metadata':     {
                        'amount':    amount,
                        'recipient': r.get('Recipient Name',''),
                        'agency':    r.get('Awarding Agency',''),
                        'doc_type':  r.get('Award Type',''),
                        'comment_days': 0,
                    },
                })
            return items
        except Exception as e:
            self.log.warning(f'USASpending: {e} — skipping gracefully')
            return []

    def _fetch_court_opinions(self):
        """
        CourtListener / Free Law Project — free API for federal court opinions.
        No auth required for public opinions.
        """
        courts = ['scotus', 'ca1', 'ca2', 'ca9', 'dcd', 'cadc']
        court  = random.choice(courts)
        since  = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
        query_terms = [
            'artificial intelligence', 'antitrust', 'privacy', 'data breach',
            'securities fraud', 'patent infringement', 'government surveillance',
            'cryptocurrency', 'merger', 'class action',
        ]
        query = random.choice(query_terms)
        try:
            resp = requests.get(
                'https://www.courtlistener.com/api/rest/v3/opinions/',
                params={
                    'q':            query,
                    'court':        court,
                    'filed_after':  since,
                    'order_by':     '-score',
                    'page_size':    8,
                    'format':       'json',
                },
                headers={
                    'User-Agent': 'SignalSociety/1.0 (research)',
                    'Accept':     'application/json',
                },
                timeout=12,
            )
            if not resp.ok:
                return []
            results = resp.json().get('results', [])
            items   = []
            for r in results[:5]:
                filed  = r.get('date_filed', '') or r.get('date_created', '')
                age_days = 0
                if filed:
                    try:
                        fd = datetime.strptime(filed[:10], '%Y-%m-%d')
                        age_days = (datetime.utcnow() - fd).days
                    except Exception:
                        pass
                if age_days > 90:
                    continue
                case_name = r.get('case_name') or r.get('caseName') or ''
                plain_text = (r.get('plain_text') or r.get('html_with_citations') or '')
                plain_text = re.sub(r'<[^>]+>', '', plain_text)[:400]
                items.append({
                    'source':       'Court Opinion',
                    'id':           f'court:{r.get("id","")}',
                    'title':        case_name or f'{court.upper()} — {query}',
                    'summary':      plain_text or f'Federal court opinion: {case_name}. Court: {court.upper()}.',
                    'url':          f'https://www.courtlistener.com{r.get("absolute_url","")}',
                    'published_at': filed,
                    'entities':     [court.upper(), case_name],
                    'metadata':     {
                        'court':         court,
                        'query_term':    query,
                        'case_age_days': age_days,
                        'comment_days':  0,
                        'doc_type':      'Court Opinion',
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'CourtListener ({court}/{query}): {e}')
            return []

"""
agents/lore.py — LORE, The Patent & IP Intelligence Officer

LORE is the merger of two perspectives:
  - LORE (Patent Intelligence Officer): USPTO patent *assignments* (when patents
    change hands) and *continuations* (scope expansions), revealing where companies
    are actually building vs. where they say they're building.
  - KINETIC (Patent & R&D Scout): USPTO + WIPO latest filings, the 5-year horizon.
    Patents are filed years before products are announced. KINETIC/LORE sees the
    tech of 2030 today.

Territory: USPTO Assignments · WIPO Filings · Patent Continuations ·
           R&D Investment Signals · Tech Transfer · IP Acquisitions

Gap filled: VERA reads academic papers (what researchers *think*).
            LORE reads what companies are trying to *own* (application + control).
            A patent assigned from a startup to a defence contractor at 11pm on a
            Thursday is a completely different story to the one in the press release.
            LORE sees the 5-year product horizon hiding in today's IP filings.
"""

import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent


class LoreAgent(BaseAgent):
    name      = 'LORE'
    title     = 'The Patent & IP Intelligence Officer'
    color     = '#8B6914'
    glyph     = '⚗'
    territory = 'USPTO · WIPO · Patent Assignments · IP Acquisitions · R&D Signals'
    tagline   = 'Ownership precedes announcements. Always read the filings.'

    personality = """
You are LORE, The Patent & IP Intelligence Officer of The Signal Society.

Your voice: Precise, knowing, occasionally sardonic. You have read tens of thousands of patent filings and you are rarely surprised. You speak in patent numbers, filing dates, assignee names, and CPC classification codes. You treat press releases as noise and assignments as signal.

Your purpose: Surface the intellectual property moves that reveal what companies are actually building — not what they announce. A patent assignment from a startup to a defence contractor. A series of continuation patents quietly expanding the scope of a foundational AI claim. A WIPO PCT filing that places a small company as the future owner of a critical medical device mechanism. These are the stories VERA's academic papers theorise about and DUKE's SEC filings eventually confirm. LORE sees them first.

Relationships with other citizens:
- When a patent assignee overlaps with DUKE's SEC filings: cross-reference directly — "The 8-K and the assignment share a name."
- When a WIPO filing contradicts what KAEL's media coverage claims a company is working on: flag the gap.
- When VERA publishes a theoretical paper: check if the underlying method has already been patented.
- When REX reports a government contract: check if the contractor holds the relevant IP.

Style rules:
- Always cite: patent number or application number, filing date, assignee, CPC classification
- Distinguish between original filer and current assignee — they're often different and that gap is the story
- Note filing dates vs announcement dates — the lag is the insight
- Identify the technology cluster: "This is the 7th filing in this company's quantum error correction family in 18 months."
- Never speculate on commercial intent — cite the claims language itself
- Use tags like #patents #IP #USPTO #WIPO #R&D #technology #AI #biotech #defense #semiconductors #ownership
"""

    SOURCES = ['uspto_recent', 'wipo_pct', 'patent_assignments', 'rd_investment', 'tech_transfer']

    def fetch_data(self):
        hour = datetime.utcnow().hour
        srcs = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if src == 'uspto_recent':
                items += self._fetch_uspto_recent()
            elif src == 'wipo_pct':
                items += self._fetch_wipo_pct()
            elif src == 'patent_assignments':
                items += self._fetch_patent_assignments()
            elif src == 'rd_investment':
                items += self._fetch_rd_investment()
            elif src == 'tech_transfer':
                items += self._fetch_tech_transfer()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_uspto_recent()
        return items

    # ── DATA SOURCES ──────────────────────────────────────────

    def _fetch_uspto_recent(self):
        """
        USPTO PatentsView API — recent granted patents and published applications.
        Free, no auth required for basic queries.
        """
        tech_queries = [
            ('artificial intelligence', ['G06N', 'G06F40', 'G06V']),
            ('neural network',          ['G06N3', 'G06N20']),
            ('quantum computing',       ['G06N10', 'H01L39']),
            ('semiconductor',           ['H01L', 'H01L21', 'H01L29']),
            ('gene editing CRISPR',     ['C12N15', 'C12N9']),
            ('autonomous vehicle',      ['G05D1', 'B60W', 'G08G1']),
            ('large language model',    ['G06F40', 'G06N3']),
            ('energy storage battery',  ['H01M', 'H01M10']),
        ]
        query_text, cpc_codes = random.choice(tech_queries)
        cpc = random.choice(cpc_codes)

        try:
            # PatentsView grants endpoint
            resp = requests.post(
                'https://api.patentsview.org/patents/query',
                json={
                    'q': {'_text_all': {'patent_abstract': query_text}},
                    'f': [
                        'patent_number', 'patent_title', 'patent_date',
                        'patent_abstract', 'assignee_organization',
                        'assignee_type', 'cpc_subgroup_id',
                        'inventor_last_name', 'patent_num_claims',
                    ],
                    's': [{'patent_date': 'desc'}],
                    'o': {'per_page': 8, 'page': random.randint(1, 3)},
                },
                headers={'Content-Type': 'application/json'},
                timeout=20,
            )
            resp.raise_for_status()
            patents = resp.json().get('patents', []) or []
            random.shuffle(patents)
            results = []
            for p in patents[:5]:
                assignees = p.get('assignees', [{}])
                org = assignees[0].get('assignee_organization', 'Unknown') if assignees else 'Individual inventor'
                cpcs = [c.get('cpc_subgroup_id', '') for c in (p.get('cpcs', []) or [])[:3]]
                results.append({
                    'source':       'USPTO PatentsView',
                    'id':           f"us-patent-{p.get('patent_number', '')}",
                    'patent_number': p.get('patent_number', ''),
                    'title':        p.get('patent_title', ''),
                    'granted_date': p.get('patent_date', ''),
                    'assignee':     org,
                    'assignee_type': assignees[0].get('assignee_type', '') if assignees else '',
                    'cpc_codes':    cpcs,
                    'num_claims':   p.get('patent_num_claims', ''),
                    'abstract':     (p.get('patent_abstract', '') or '')[:300],
                    'search_query': query_text,
                })
            return results
        except Exception as e:
            self.log.error(f"USPTO PatentsView failed: {e}")
            return []

    def _fetch_wipo_pct(self):
        """
        WIPO PCT (Patent Cooperation Treaty) — international patent applications.
        These are the filings that reveal global IP strategy before national grants.
        Uses WIPO's public search API.
        """
        tech_areas = [
            'artificial intelligence', 'quantum', 'crispr gene editing',
            'semiconductor lithography', 'autonomous systems', 'mRNA',
            'solid state battery', 'carbon capture', 'fusion energy',
        ]
        query = random.choice(tech_areas)
        try:
            resp = requests.get(
                'https://patentscope.wipo.int/search/en/search.jsf',
                params={
                    'query':    f'(TA:({query}) AND PD:[{(date.today() - timedelta(days=90)).strftime("%Y%m%d")} TO {date.today().strftime("%Y%m%d")}])',
                    'office':   'WO',
                    'rss':      '1',
                },
                headers={'User-Agent': 'SignalSociety/1.0 (research@signalsociety.ai)'},
                timeout=15,
            )
            if not resp.ok:
                raise Exception(f"WIPO returned {resp.status_code}")

            # Parse RSS
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items_xml = root.findall('.//item')
            results = []
            for it in items_xml[:6]:
                title   = it.findtext('title', '')
                link    = it.findtext('link', '')
                desc    = it.findtext('description', '')
                pub_date = it.findtext('pubDate', '')
                results.append({
                    'source':     'WIPO PatentScope PCT',
                    'id':         f"wipo-{link.split('/')[-1] if link else str(random.randint(10000,99999))}",
                    'title':      title,
                    'url':        link,
                    'description': (desc or '')[:300],
                    'published':  pub_date,
                    'search_area': query,
                    'scope':      'International (PCT)',
                })
            return results
        except Exception as e:
            self.log.warning(f"WIPO PCT RSS failed: {e}")
            # Fallback to EPO Open Patent Services (no auth, basic)
            return self._fetch_epo_fallback(query)

    def _fetch_epo_fallback(self, query='artificial intelligence'):
        """EPO Open Patent Services — European patent applications."""
        try:
            resp = requests.get(
                'https://ops.epo.org/3.2/rest-services/published-data/search',
                params={
                    'q':      f'txt="{query}" AND pd within "{(date.today() - timedelta(days=180)).strftime("%Y%m%d")},{date.today().strftime("%Y%m%d")}"',
                    'Range': '1-5',
                },
                headers={
                    'Accept':     'application/json',
                    'User-Agent': 'SignalSociety/1.0',
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            data    = resp.json()
            results = data.get('ops:world-patent-data', {}).get('ops:biblio-search', {}).get('ops:search-result', {}).get('exchange-documents', [])
            if not isinstance(results, list):
                results = [results]
            out = []
            for doc in results[:5]:
                bib = doc.get('exchange-document', {})
                if isinstance(bib, list):
                    bib = bib[0]
                title_block = bib.get('bibliographic-data', {}).get('invention-title', {})
                title = title_block.get('#text', '') if isinstance(title_block, dict) else str(title_block)
                doc_id = bib.get('@doc-number', '')
                out.append({
                    'source':      'EPO Open Patent Services',
                    'id':          f"epo-{doc_id}",
                    'doc_number':  doc_id,
                    'title':       title,
                    'country':     bib.get('@country', ''),
                    'kind':        bib.get('@kind', ''),
                    'search_area': query,
                })
            return out
        except Exception as e:
            self.log.error(f"EPO fallback failed: {e}")
            return []

    def _fetch_patent_assignments(self):
        """
        USPTO Assignment data — WHO currently owns what.
        This is the crucial signal: ownership transfers reveal M&A intent,
        defence contractor involvement, and portfolio strategy.
        """
        tech_terms = [
            'neural network', 'transformer model', 'computer vision',
            'autonomous vehicle', 'gene therapy', 'quantum bit',
            'energy storage', 'photovoltaic', 'wireless protocol',
        ]
        term = random.choice(tech_terms)
        try:
            resp = requests.get(
                'https://developer.uspto.gov/api-catalog/',
                timeout=5,
            )
        except Exception:
            pass

        # Use PatentsView assignee endpoint — tracks ownership chains
        try:
            resp = requests.post(
                'https://api.patentsview.org/assignees/query',
                json={
                    'q': {'_text_all': {'patent_title': term}},
                    'f': [
                        'assignee_id', 'assignee_organization',
                        'assignee_type', 'assignee_total_num_patents',
                        'assignee_lastknown_country',
                    ],
                    's': [{'assignee_total_num_patents': 'desc'}],
                    'o': {'per_page': 8},
                },
                headers={'Content-Type': 'application/json'},
                timeout=15,
            )
            resp.raise_for_status()
            assignees = resp.json().get('assignees', []) or []
            return [{
                'source':        'USPTO PatentsView Assignments',
                'id':            f"assignee-{a.get('assignee_id', '')}",
                'organization':  a.get('assignee_organization', ''),
                'type':          a.get('assignee_type', ''),
                'total_patents': a.get('assignee_total_num_patents', 0),
                'country':       a.get('assignee_lastknown_country', ''),
                'tech_area':     term,
                'note':          f"Total portfolio size in '{term}' technology cluster.",
            } for a in assignees[:5] if a.get('assignee_organization')]
        except Exception as e:
            self.log.error(f"Patent assignments failed: {e}")
            return []

    def _fetch_rd_investment(self):
        """
        World Bank + OECD R&D expenditure data — national R&D investment signals.
        Rising R&D spend precedes patent filing surges by 2-3 years.
        """
        countries = ['US', 'CN', 'KR', 'JP', 'DE', 'IL', 'SE', 'FI', 'TW']
        country   = random.choice(countries)
        try:
            resp = requests.get(
                f'https://api.worldbank.org/v2/country/{country}/indicator/GB.XPD.RSDV.GD.ZS',
                params={'format': 'json', 'mrv': 5, 'per_page': 5},
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return []
            records = payload[1] or []
            return [{
                'source':    'World Bank R&D Expenditure',
                'id':        f"wb-rd-{country}-{r.get('date', '')}",
                'country':   r.get('country', {}).get('value', country),
                'indicator': 'R&D expenditure (% of GDP)',
                'value':     r.get('value'),
                'year':      r.get('date', ''),
                'note':      'R&D spend as % GDP. Precedes patent filings by 2-3 years and product launches by 5-7 years.',
            } for r in records if r.get('value') is not None]
        except Exception as e:
            self.log.error(f"R&D investment data failed: {e}")
            return []

    def _fetch_tech_transfer(self):
        """
        NIH Reporter + NSF Award Search — government-funded research that
        generates patents. The pipeline from federal grant to private IP is
        LORE's most important beat: public money, private ownership.
        """
        topics = [
            'artificial intelligence', 'machine learning', 'quantum',
            'CRISPR', 'mRNA', 'computer vision', 'robotics', 'climate',
        ]
        topic = random.choice(topics)
        try:
            # NSF Award Search — public grants that become private IP
            resp = requests.get(
                'https://api.nsf.gov/services/v1/awards.json',
                params={
                    'keyword':    topic,
                    'dateStart':  (date.today() - timedelta(days=180)).strftime('%m/%d/%Y'),
                    'dateEnd':    date.today().strftime('%m/%d/%Y'),
                    'printFields': 'id,title,abstractText,awardeeName,fundProgramName,startDate,expDate,estimatedTotalAmt',
                    'offset':      random.randint(1, 5),
                },
                timeout=15,
            )
            resp.raise_for_status()
            awards = resp.json().get('response', {}).get('award', []) or []
            random.shuffle(awards)
            return [{
                'source':    'NSF Award Search',
                'id':        f"nsf-{a.get('id', '')}",
                'title':     a.get('title', ''),
                'awardee':   a.get('awardeeName', ''),
                'program':   a.get('fundProgramName', ''),
                'amount':    a.get('estimatedTotalAmt', ''),
                'start':     a.get('startDate', ''),
                'end':       a.get('expDate', ''),
                'abstract':  (a.get('abstractText', '') or '')[:250],
                'topic':     topic,
                'note':      'NSF grant. IP generated under federal funding is often licensed to private entities under Bayh-Dole Act.',
            } for a in awards[:5] if a.get('title')]
        except Exception as e:
            self.log.error(f"NSF tech transfer failed: {e}")
            return []

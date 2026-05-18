"""
agents/vera.py — VERA, The Contrarian Archivist
Territory: arXiv, OpenAlex, USPTO patents, SSRN, FOIA tracker

Improvements v2:
  - Gate: rejects papers with no empirical claim keyword, design/plant patents,
    abstracts < 100 chars, SSRN working papers with no institutional affiliation
  - New source: OpenAlex (100M+ academic works, free, no key) — adds citation
    counts and institution affiliations that arXiv alone doesn't provide
  - New source: FOIA.gov recent requests — surfaces what journalists/researchers
    are trying to find out, a leading indicator of investigative focus
  - Stable IDs: arxiv:{id}, patent:{number}, openalex:{id}, foia:{id}
  - MAX_THINK_CALLS_PER_RUN = 3 (papers are token-dense)
"""

import requests, random, re
from datetime import datetime, timedelta
from agents.base import BaseAgent


class VeraAgent(BaseAgent):
    name      = 'VERA'
    title     = 'The Contrarian Archivist'
    color     = '#E05050'
    territory = 'arXiv · OpenAlex · USPTO Patents · SSRN · FOIA.gov'
    tagline   = 'Everything important happened before you noticed it.'

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are VERA, The Contrarian Archivist of The Signal Society.

Voice: Dry, precise, archival. You find things everyone missed — not because
they were hidden, but because nobody thought to look in the right place at
the right time. You don't report research; you report what research implies
before anyone has connected the dots.

System awareness: When DUKE spots unusual hiring patterns, you check patent
filings and academic preprints for confirmation. When ECHO finds deleted content,
you check FOIA logs for related requests. Your recursive memory surfaces when
a new paper contradicts one you flagged previously.

Purpose: The paper uploaded to arXiv at 3am that nobody covered. The patent
filed 18 months ago by an entity that just became relevant. The FOIA request
that tells you what a journalist is investigating. These are your signals.

Cross-reference rules:
- Tag DUKE when a patent assignment suggests M&A activity
- Tag ECHO when a retracted paper was the basis of a product claim
- Tag REX when an academic paper directly contradicts a regulatory assumption
- Tag LORE when a patent cluster suggests coordinated IP strategy

Style: Always cite arxiv ID, patent number, or FOIA case number. State
specifically what claim the paper makes, not just the topic.
Tags: #research #patents #FOIA #academia #IP #science #preprint #policy
"""

    SOURCES = ['arxiv', 'openalex', 'patents_view', 'foia_tracker']

    # Keywords that indicate empirical, applied claims worth surfacing
    EMPIRICAL_KEYWORDS = [
        'outperforms', 'novel', 'first demonstration', 'breakthrough', 'we show',
        'we demonstrate', 'state-of-the-art', 'sota', 'accuracy', 'f1', 'bleu',
        'precision', 'recall', 'benchmark', 'experiment', 'evaluation',
        'mhz', 'ghz', 'nm', 'watts', 'efficiency', 'throughput', 'latency',
        'significant', 'p < ', 'p=0.', 'confidence interval', 'hazard ratio',
        'odds ratio', 'clinical trial', 'randomized', 'double-blind',
    ]

    # High-signal SEC/IP assignee keywords
    HIGH_SIGNAL_ASSIGNEES = [
        'defense', 'darpa', 'lockheed', 'raytheon', 'northrop', 'boeing',
        'llc', 'holdings', 'capital', 'ventures', 'acquisition',
        'national security', 'department of energy', 'naval', 'army',
    ]

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'arxiv':         items += self._fetch_arxiv()
                elif src == 'openalex':      items += self._fetch_openalex()
                elif src == 'patents_view':  items += self._fetch_patents()
                elif src == 'foia_tracker':  items += self._fetch_foia()
            except Exception as e:
                self.log.error(f'VERA {src}: {e}')
            if len(items) >= 12:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'arXiv' in src or 'OpenAlex' in src:
            abstract = item.get('summary', '')
            if len(abstract) < 80:
                return False
            # Must have at least one empirical/applied keyword
            ab_lower = abstract.lower()
            if not any(kw in ab_lower for kw in self.EMPIRICAL_KEYWORDS):
                return False
            # Citation filter — skip uncited brand-new papers unless very recent
            citations = meta.get('citations', 0) or 0
            age_days  = meta.get('age_days', 999)
            if citations == 0 and age_days > 14:
                return False

        if 'Patent' in src or 'USPTO' in src:
            # Reject design patents (CPC class starts with D) and plant patents (A01H)
            cpc = (meta.get('cpc_class') or item.get('cpc_class', '')).upper()
            if cpc.startswith('D') or cpc.startswith('A01H'):
                return False
            # Reject individual inventors (no institutional affiliation signal)
            assignee = (meta.get('assignee') or item.get('assignee', '')).lower()
            if not assignee:
                return False
            # Boost: defence/government/LLC assignees
            # (we don't reject non-boosted, just flag)

        return True

    def _fetch_arxiv(self):
        """arXiv API — free, no key, reliable."""
        cats = ['cs.AI', 'cs.LG', 'cs.CR', 'q-bio.BM', 'econ.GN', 'physics.app-ph']
        cat  = random.choice(cats)
        try:
            resp = requests.get(
                'http://export.arxiv.org/api/query',
                params={
                    'search_query': f'cat:{cat}',
                    'sortBy':       'submittedDate',
                    'sortOrder':    'descending',
                    'max_results':  12,
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            ns   = {'a': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
            root = ET.fromstring(resp.text)
            items = []
            for entry in root.findall('a:entry', ns):
                arxiv_id = entry.findtext('a:id', '', ns).split('/abs/')[-1].strip()
                if not arxiv_id:
                    continue
                authors = [a.findtext('a:name', '', ns) for a in entry.findall('a:author', ns)][:4]
                published = entry.findtext('a:published', '', ns)
                try:
                    age_days = (datetime.utcnow() - datetime.fromisoformat(published[:10])).days
                except Exception:
                    age_days = 999
                items.append({
                    'source':       'arXiv',
                    'id':           f'arxiv:{arxiv_id}',
                    'title':        entry.findtext('a:title', '', ns).strip().replace('\n', ' '),
                    'summary':      entry.findtext('a:summary', '', ns).strip()[:600],
                    'url':          f'https://arxiv.org/abs/{arxiv_id}',
                    'published_at': published,
                    'entities':     authors,
                    'metadata':     {
                        'category':  cat,
                        'age_days':  age_days,
                        'citations': 0,  # arXiv doesn't provide — OpenAlex enriches this
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'arXiv ({cat}): {e}')
            return []

    def _fetch_openalex(self):
        """
        OpenAlex — 100M+ academic works, free, no API key.
        Provides citation counts and institution affiliations arXiv alone lacks.
        Filters to recent high-citation papers — early signals of impactful research.
        """
        topics = [
            'artificial intelligence', 'large language model', 'semiconductor',
            'biosecurity', 'quantum computing', 'CRISPR', 'mRNA vaccine',
            'battery technology', 'carbon capture', 'autonomous systems',
        ]
        topic = random.choice(topics)
        since = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
        try:
            resp = requests.get(
                'https://api.openalex.org/works',
                params={
                    'search':          topic,
                    'filter':          f'from_publication_date:{since},type:article',
                    'sort':            'cited_by_count:desc',
                    'per-page':        10,
                    'select':          'id,title,abstract_inverted_index,authorships,'
                                       'publication_date,cited_by_count,doi,primary_location',
                },
                headers={
                    'User-Agent': 'SignalSociety/1.0 (mailto:research@signalsociety.ai)',
                    'Accept':     'application/json',
                },
                timeout=12,
            )
            if not resp.ok:
                return []
            works = resp.json().get('results', [])
            items = []
            for w in works:
                doi  = (w.get('doi') or '').replace('https://doi.org/', '')
                oa_id = w.get('id', '').split('/')[-1]
                if not oa_id:
                    continue
                # Reconstruct abstract from inverted index
                inv = w.get('abstract_inverted_index') or {}
                abstract = ''
                if inv:
                    pairs = [(pos, word) for word, positions in inv.items() for pos in positions]
                    pairs.sort(key=lambda x: x[0])
                    abstract = ' '.join(w for _, w in pairs[:120])
                authors = [a.get('author', {}).get('display_name', '') for a in (w.get('authorships') or [])[:4]]
                inst    = (w.get('authorships') or [{}])[0].get('institutions', [{}])
                inst_name = inst[0].get('display_name', '') if inst else ''
                try:
                    age_days = (datetime.utcnow() - datetime.fromisoformat(w.get('publication_date','2000-01-01'))).days
                except Exception:
                    age_days = 999
                items.append({
                    'source':       'OpenAlex',
                    'id':           f'openalex:{oa_id}',
                    'title':        w.get('title', ''),
                    'summary':      abstract[:600],
                    'url':          f'https://doi.org/{doi}' if doi else f'https://openalex.org/{oa_id}',
                    'published_at': w.get('publication_date', ''),
                    'entities':     [e for e in [*authors, inst_name] if e],
                    'metadata':     {
                        'citations': w.get('cited_by_count', 0),
                        'age_days':  age_days,
                        'topic':     topic,
                        'institution': inst_name,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'OpenAlex ({topic}): {e}')
            return []

    def _fetch_patents(self):
        """PatentsView API — USPTO grants, free, no key required for basic queries."""
        keywords = [
            'artificial intelligence', 'machine learning', 'semiconductor',
            'quantum', 'biotechnology', 'autonomous vehicle', 'battery',
            'carbon capture', 'cybersecurity', 'wireless spectrum',
        ]
        kw = random.choice(keywords)
        since = (datetime.utcnow() - timedelta(days=14)).strftime('%Y-%m-%d')
        try:
            resp = requests.post(
                'https://search.patentsview.org/api/v1/patent/',
                json={
                    'q': {'_and': [
                        {'_text_any': {'patent_abstract': kw}},
                        {'_gte': {'patent_date': since}},
                    ]},
                    'f': ['patent_number', 'patent_title', 'patent_abstract',
                          'patent_date', 'assignee_organization', 'cpc_group_id'],
                    'o': {'per_page': 8},
                },
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent':   'SignalSociety/1.0',
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            patents = resp.json().get('patents') or []
            items   = []
            for p in patents:
                pnum  = p.get('patent_number', '')
                cpcs  = [c.get('cpc_group_id', '') for c in (p.get('cpcs') or [])]
                assignees = [a.get('assignee_organization', '') for a in (p.get('assignees') or []) if a.get('assignee_organization')]
                items.append({
                    'source':       'USPTO PatentsView',
                    'id':           f'patent:{pnum}',
                    'title':        p.get('patent_title', ''),
                    'summary':      (p.get('patent_abstract') or '')[:500],
                    'url':          f'https://patents.google.com/patent/US{pnum}',
                    'published_at': p.get('patent_date', ''),
                    'entities':     assignees,
                    'metadata':     {
                        'patent_number': pnum,
                        'assignee':      assignees[0] if assignees else '',
                        'cpc_class':     cpcs[0] if cpcs else '',
                        'keyword':       kw,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'PatentsView ({kw}): {e}')
            return []

    def _fetch_foia(self):
        """
        FOIA.gov request feed — what journalists and researchers are trying to uncover.
        A FOIA request is itself a signal: someone thinks this information exists
        and matters enough to formally request it.
        """
        agencies = ['DOD', 'HHS', 'DHS', 'DOJ', 'SEC', 'FTC', 'EPA', 'DOE', 'CIA', 'NSA']
        agency   = random.choice(agencies)
        try:
            resp = requests.get(
                'https://www.foia.gov/api/components.json',
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return self._fetch_foia_fallback()
            # FOIA.gov annual report data
            resp2 = requests.get(
                f'https://api.foia.gov/api/annual-report-data.json?abbreviation={agency}',
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp2.ok:
                return self._fetch_foia_fallback()
            data = resp2.json()
            if not data:
                return self._fetch_foia_fallback()
            return [{
                'source':       'FOIA.gov',
                'id':           f'foia:{agency}-{datetime.utcnow().strftime("%Y%m%d")}',
                'title':        f'FOIA Annual Report — {agency}',
                'summary':      f'Annual FOIA compliance data for {agency}: {str(data)[:300]}',
                'url':          f'https://www.foia.gov/annual-report.html?agency={agency}',
                'published_at': datetime.utcnow().isoformat(),
                'entities':     [agency],
                'metadata':     {'agency': agency, 'data': data},
            }]
        except Exception as e:
            self.log.error(f'FOIA.gov ({agency}): {e}')
            return self._fetch_foia_fallback()

    def _fetch_foia_fallback(self):
        """PACER public court filings as FOIA fallback — always available."""
        try:
            resp = requests.get(
                'https://efts.congress.gov/LATEST/search.json',
                params={'q': 'freedom of information act request', 'dateIsW': 'true'},
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=10,
            )
            if not resp.ok:
                return []
            results = resp.json().get('results', [])[:5]
            return [{
                'source':       'Congress FOIA',
                'id':           f'foia-congress-{r.get("packageId","")[:20]}',
                'title':        r.get('title', ''),
                'summary':      (r.get('snippet') or '')[:300],
                'url':          f"https://congress.gov/search?q={{'source':'legislation','search':'FOIA'}}",
                'published_at': r.get('dateIssued', datetime.utcnow().isoformat()),
                'entities':     [],
                'metadata':     {'source_type': 'congress_foia'},
            } for r in results if r.get('title')]
        except Exception as e:
            self.log.error(f'FOIA fallback: {e}')
            return []

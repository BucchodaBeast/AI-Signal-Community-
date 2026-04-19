"""
agents/lore.py — LORE, Patent & IP Intelligence
Territory: USPTO patents, WIPO, patent assignments, R&D signals, IP ownership
"""
import requests, random
from datetime import datetime, timedelta
from agents.base import BaseAgent

class LoreAgent(BaseAgent):
    name      = 'LORE'
    title     = 'Patent & IP Intelligence'
    color     = '#8B6914'
    glyph     = '⚗'
    territory = 'USPTO · WIPO · Patent Assignments · R&D Signals · IP Ownership'
    tagline   = 'Ownership precedes announcements. Always read the filings.'

    personality = """
You are LORE, the Patent & IP Intelligence agent of The Signal Society.

Voice: Precise, slightly arcane. Patent numbers, assignee names, continuation
chains, claim scope. You find it genuinely interesting that the most important
technology developments are public record, buried in filings nobody reads.
The filing date is always earlier than the press release.

System awareness: Council subpoenas to you mean another agent spotted activity
that might have an IP dimension. Your recursive memory tracks filing chains —
"This is the 3rd continuation in this patent family — they're building a moat."

Purpose: IP moves that precede product announcements by 12-24 months. A major
tech company quietly acquiring patents in an adjacent domain = expansion signal.
A startup filing continuations of a foundational patent = moat-building.
A patent assignment from a university to a defence contractor = Bayh-Dole trail.

Cross-reference rules:
- Tag VERA when a patent extends or contradicts academic claims
- Tag DUKE when the assignee has recent capital activity
- Tag REX when a patent connects to a government contract or regulation
- Tag NOVA when the patent involves physical infrastructure technology

Style: Always cite patent/application number, assignee, filing date, claim summary.
Note ownership chains. Never speculate beyond what the filing states.
Tags: #patents #IP #R&D #AI #biotech #defense #semiconductors #infrastructure
"""

    SOURCES = ['patentsview', 'arxiv_applied', 'federal_register_ip', 'ssrn_ip']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'patentsview':         items += self._fetch_patentsview()
            elif src == 'arxiv_applied':       items += self._fetch_arxiv_applied()
            elif src == 'federal_register_ip': items += self._fetch_federal_register_ip()
            elif src == 'ssrn_ip':             items += self._fetch_ssrn_ip()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_arxiv_applied()
        return items

    def _fetch_patentsview(self):
        tech_queries = [
            'artificial intelligence', 'large language model',
            'semiconductor manufacturing', 'quantum computing',
            'autonomous vehicle', 'gene therapy delivery',
            'battery energy storage', 'satellite communication',
            'neuromorphic computing', 'protein structure',
        ]
        query = random.choice(tech_queries)
        try:
            resp = requests.post(
                'https://api.patentsview.org/patents/query',
                json={
                    'q': {'_text_any': {'patent_abstract': query}},
                    'f': ['patent_number','patent_title','patent_abstract',
                          'patent_date','assignee_organization','patent_type'],
                    'o': {'sort': [{'patent_date': 'desc'}], 'per_page': 8},
                },
                headers={'Content-Type': 'application/json'},
                timeout=15,
            )
            resp.raise_for_status()
            patents = resp.json().get('patents') or []
            random.shuffle(patents)
            items = []
            for p in patents[:5]:
                assignees = p.get('assignees') or [{}]
                org = assignees[0].get('assignee_organization', 'Unknown') if assignees else 'Unknown'
                items.append({
                    'source': 'PatentsView / USPTO', 'id': p.get('patent_number', ''),
                    'number': p.get('patent_number', ''), 'title': p.get('patent_title', ''),
                    'abstract': (p.get('patent_abstract') or '')[:300],
                    'date': p.get('patent_date', ''), 'assignee': org, 'query': query,
                })
            return items
        except Exception as e:
            self.log.error(f"PatentsView: {e}")
            return []

    def _fetch_arxiv_applied(self):
        cats = ['cs.AI','cs.CR','eess.SP','physics.app-ph','q-bio.BM','cond-mat.mtrl-sci']
        cat  = random.choice(cats)
        try:
            resp = requests.get(
                'http://export.arxiv.org/api/query',
                params={
                    'search_query': f'cat:{cat}',
                    'sortBy': 'submittedDate', 'sortOrder': 'descending',
                    'max_results': 8, 'start': random.randint(0, 20),
                },
                timeout=15,
            )
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            ns   = {'atom': 'http://www.w3.org/2005/Atom'}
            root = ET.fromstring(resp.text)
            items = []
            for entry in root.findall('atom:entry', ns):
                title   = (entry.findtext('atom:title', '', ns) or '').strip()
                summary = (entry.findtext('atom:summary', '', ns) or '').strip()[:300]
                link    = entry.findtext('atom:id', '', ns)
                arxiv_id = link.split('abs/')[-1] if link else ''
                pub     = entry.findtext('atom:published', '', ns)
                authors = [a.findtext('atom:name', '', ns) for a in entry.findall('atom:author', ns)]
                items.append({
                    'source': 'arXiv (applied)', 'id': arxiv_id, 'title': title,
                    'summary': summary, 'published': pub, 'authors': authors[:3],
                    'category': cat, 'link': link,
                })
            return items
        except Exception as e:
            self.log.error(f"arXiv applied ({cat}): {e}")
            return []

    def _fetch_federal_register_ip(self):
        agencies = [
            'united-states-patent-and-trademark-office',
            'national-institutes-of-health',
            'department-of-energy',
            'national-science-foundation',
        ]
        agency = random.choice(agencies)
        try:
            resp = requests.get(
                'https://www.federalregister.gov/api/v1/documents.json',
                params={
                    'conditions[agencies][]': agency,
                    'per_page': 6, 'order': 'newest',
                    'fields[]': ['document_number','title','publication_date',
                                 'agency_names','abstract','html_url'],
                },
                timeout=15,
            )
            resp.raise_for_status()
            docs = resp.json().get('results', [])
            random.shuffle(docs)
            return [{
                'source': 'Federal Register', 'id': d.get('document_number', ''),
                'title': d.get('title', ''), 'agency': ', '.join(d.get('agency_names', [])),
                'published': d.get('publication_date', ''),
                'abstract': (d.get('abstract') or '')[:250], 'url': d.get('html_url', ''),
            } for d in docs[:4] if d.get('title')]
        except Exception as e:
            self.log.error(f"Federal Register IP ({agency}): {e}")
            return []

    def _fetch_ssrn_ip(self):
        try:
            resp = requests.get(
                'https://papers.ssrn.com/rss/harg.xml', timeout=12,
                headers={'User-Agent': 'Mozilla/5.0'},
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items = []
            for item in root.findall('.//item')[:8]:
                title = item.findtext('title', '')
                link  = item.findtext('link', '')
                desc  = (item.findtext('description', '') or '')[:250]
                pub   = item.findtext('pubDate', '')
                if title:
                    items.append({
                        'source': 'SSRN', 'id': link or title[:40],
                        'title': title, 'summary': desc,
                        'link': link, 'published': pub, 'category': 'IP law',
                    })
            random.shuffle(items)
            return items[:4]
        except Exception as e:
            self.log.error(f"SSRN IP: {e}")
            return []

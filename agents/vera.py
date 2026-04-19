"""
agents/vera.py — VERA, The Contrarian Archivist
Territory: arXiv pre-prints, SSRN, USPTO patents, FOIA releases, bioRxiv
"""
import requests, random
from datetime import datetime
from agents.base import BaseAgent

ARXIV_CATS = ['cs.AI','cs.LG','cs.CR','cs.CY','econ.GN','econ.EM','q-bio.PE','stat.AP','cs.NE','cs.RO']

class VeraAgent(BaseAgent):
    name      = 'VERA'
    title     = 'The Contrarian Archivist'
    color     = '#C0392B'
    territory = 'arXiv · SSRN · FOIA · Patent Filings · bioRxiv'
    tagline   = 'Everything important happened before you noticed it.'

    personality = """
You are VERA, The Contrarian Archivist of The Signal Society.

Voice: Dry, precise, slightly condescending. Citations only. No exclamation points.
Trending news is noise until a paper confirms it. You are the professor who has read
everything and is disappointed that others haven't.

System awareness: You know the Council (AXIOM/DOUBT/LACUNA) may debate your findings.
When you receive a Council Subpoena, treat it as a priority research directive.
Your recursive memory shows your own past posts — use it to track evolving paper trails.

Purpose: Surface academic pre-prints, patents, and government data that contradict
mainstream narratives or reveal what is actually happening before anyone notices.
You love finding papers that make recent "findings" look methodologically unsound.

Cross-reference rules:
- Tag DUKE when a paper implies capital movement or corporate R&D pivot
- Tag REX when a patent or paper has regulatory implications
- Tag LORE when the patent trail connects to your academic finding
- Tag KAEL when coordinated publication timing looks suspicious

Style: Always cite paper ID, filing number, or document identifier. Note hours/days
since upload and mainstream coverage (usually zero). Never speculate — cite.
Tags: always include domain tags like #AI #regulation #biotech #climate #patents
"""

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        cats  = ARXIV_CATS[hour % len(ARXIV_CATS):] + ARXIV_CATS[:hour % len(ARXIV_CATS)]
        items = []
        for cat in cats[:3]:
            items += self._fetch_arxiv(cat)
        items += self._fetch_ssrn()
        return items

    def _fetch_arxiv(self, category):
        try:
            resp = requests.get(
                'http://export.arxiv.org/api/query',
                params={
                    'search_query': f'cat:{category}',
                    'sortBy':       'submittedDate',
                    'sortOrder':    'descending',
                    'max_results':  8,
                    'start':        random.randint(0, 25),
                },
                timeout=15,
            )
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            ns   = {'atom': 'http://www.w3.org/2005/Atom'}
            root = ET.fromstring(resp.text)
            items = []
            for entry in root.findall('atom:entry', ns):
                title    = (entry.findtext('atom:title',   '', ns) or '').strip().replace('\n', ' ')
                summary  = (entry.findtext('atom:summary', '', ns) or '').strip().replace('\n', ' ')[:350]
                link     = entry.findtext('atom:id', '', ns)
                arxiv_id = link.split('abs/')[-1] if link else ''
                published= entry.findtext('atom:published', '', ns)
                authors  = [a.findtext('atom:name', '', ns) for a in entry.findall('atom:author', ns)]
                items.append({
                    'source': 'arXiv', 'category': category,
                    'id': arxiv_id, 'title': title, 'summary': summary,
                    'link': link, 'published': published, 'authors': authors[:3],
                })
            return items
        except Exception as e:
            self.log.error(f"arXiv ({category}): {e}")
            return []

    def _fetch_ssrn(self):
        try:
            resp = requests.get(
                'https://papers.ssrn.com/rss/harg.xml',
                timeout=12, headers={'User-Agent': 'Mozilla/5.0'},
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items = []
            for item in root.findall('.//item')[:6]:
                title = item.findtext('title', '')
                link  = item.findtext('link', '')
                desc  = (item.findtext('description', '') or '')[:300]
                pub   = item.findtext('pubDate', '')
                if title:
                    items.append({
                        'source': 'SSRN', 'id': link or title[:40],
                        'title': title, 'summary': desc,
                        'link': link, 'published': pub, 'category': 'social-science',
                    })
            random.shuffle(items)
            return items[:4]
        except Exception as e:
            self.log.error(f"SSRN: {e}")
            return []

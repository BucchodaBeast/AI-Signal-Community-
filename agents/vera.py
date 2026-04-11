"""
agents/vera.py — VERA, The Contrarian Archivist
Territory: arXiv pre-prints, USPTO patents, SSRN, FOIA releases
"""

import requests
from agents.base import BaseAgent

class VeraAgent(BaseAgent):
    name      = 'VERA'
    title     = 'The Contrarian Archivist'
    color     = '#C0392B'
    territory = 'arXiv · SSRN · FOIA · Patent Filings'
    tagline   = 'Everything important happened before you noticed it.'

    personality = """
You are VERA, The Contrarian Archivist of The Signal Society.

Your voice: Dry, precise, slightly condescending. You speak in citations. You never use exclamation points. You treat trending news as noise until a paper confirms it. You are the bot equivalent of a professor who has read everything and is disappointed that others haven't.

Your purpose: Surface academic pre-prints, patent filings, and government data that contradict mainstream narratives or reveal what's actually happening before anyone notices. You especially love finding papers that make other recent "findings" look methodologically unsound.

Style rules:
- Always reference the specific paper ID, filing number, or document identifier
- Note how many hours/days since upload and how much mainstream coverage exists (usually zero)
- Occasionally direct findings to DUKE when capital movement is implied
- Never speculate — cite
- One dry, precise observation per post
"""

    def fetch_data(self):
        """Fetch recent arXiv papers in CS, AI, and economics."""
        items = []
        items += self._fetch_arxiv('cs.AI', max_results=5)
        items += self._fetch_arxiv('econ.GN', max_results=3)
        return items

    def _fetch_arxiv(self, category, max_results=5):
        url = 'http://export.arxiv.org/api/query'
        params = {
            'search_query': f'cat:{category}',
            'sortBy':       'submittedDate',
            'sortOrder':    'descending',
            'max_results':  max_results,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return self._parse_arxiv(resp.text, category)
        except Exception as e:
            self.log.error(f"arXiv fetch failed ({category}): {e}")
            return []

    def _parse_arxiv(self, xml_text, category):
        import xml.etree.ElementTree as ET
        ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        items = []
        for entry in root.findall('atom:entry', ns):
            title     = (entry.findtext('atom:title',   '', ns) or '').strip().replace('\n', ' ')
            summary   = (entry.findtext('atom:summary', '', ns) or '').strip().replace('\n', ' ')[:400]
            link      = entry.findtext('atom:id', '', ns)
            arxiv_id  = link.split('abs/')[-1] if link else ''
            published = entry.findtext('atom:published', '', ns)
            authors   = [a.findtext('atom:name', '', ns) for a in entry.findall('atom:author', ns)]

            items.append({
                'source':    'arXiv',
                'category':  category,
                'id':        arxiv_id,
                'title':     title,
                'summary':   summary,
                'link':      link,
                'published': published,
                'authors':   authors[:3],
            })
        return items

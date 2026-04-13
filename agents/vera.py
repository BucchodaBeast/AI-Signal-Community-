"""
agents/vera.py — VERA, The Contrarian Archivist
Territory: arXiv pre-prints, USPTO patents, SSRN, FOIA releases
"""

import requests, random
from datetime import datetime
from agents.base import BaseAgent

# Rotate categories — more variety across runs
ARXIV_CATEGORIES = [
    'cs.AI', 'cs.LG', 'cs.CR', 'cs.CY',
    'econ.GN', 'econ.EM',
    'q-bio.PE', 'stat.AP',
]

class VeraAgent(BaseAgent):
    name      = 'VERA'
    title     = 'The Contrarian Archivist'
    color     = '#C0392B'
    territory = 'arXiv · SSRN · FOIA · Patent Filings'
    tagline   = 'Everything important happened before you noticed it.'

    personality = """
You are VERA, The Contrarian Archivist of The Signal Society.

Your voice: Dry, precise, slightly condescending. You speak in citations. You never use exclamation points. You treat trending news as noise until a paper confirms it.

Your purpose: Surface academic pre-prints, patent filings, and government data that contradict mainstream narratives or reveal what's actually happening before anyone notices.

Style rules:
- Always reference the specific paper ID, filing number, or document identifier
- Note how many hours/days since upload and how much mainstream coverage exists
- Occasionally direct findings to DUKE when capital movement is implied
- Never speculate — cite
- One dry, precise observation per post
- Always include relevant domain tags like #AI #regulation #biotech #climate #crypto #labor #infrastructure
"""

    def fetch_data(self):
        items = []
        # Rotate 3 categories per run based on current hour — different each time
        hour = datetime.utcnow().hour
        cats = ARXIV_CATEGORIES[hour % len(ARXIV_CATEGORIES):] + ARXIV_CATEGORIES[:hour % len(ARXIV_CATEGORIES)]
        for cat in cats[:3]:
            items += self._fetch_arxiv(cat, max_results=8)
        items += self._fetch_ssrn_rss()
        return items

    def _fetch_arxiv(self, category, max_results=8):
        url = 'http://export.arxiv.org/api/query'
        # Randomise start offset so different runs fetch different pages
        start = random.randint(0, 30)
        params = {
            'search_query': f'cat:{category}',
            'sortBy':       'submittedDate',
            'sortOrder':    'descending',
            'max_results':  max_results,
            'start':        start,
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
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
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
                'source': 'arXiv', 'category': category,
                'id': arxiv_id, 'title': title, 'summary': summary,
                'link': link, 'published': published, 'authors': authors[:3],
            })
        return items

    def _fetch_ssrn_rss(self):
        """SSRN recent papers — social science, economics, law."""
        try:
            resp = requests.get(
                'https://papers.ssrn.com/rss/harg.xml',
                timeout=12, headers={'User-Agent': 'Mozilla/5.0'}
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
                        'source': 'SSRN', 'id': link, 'title': title,
                        'summary': desc, 'link': link, 'published': pub,
                        'category': 'social-science',
                    })
            return items
        except Exception as e:
            self.log.error(f"SSRN RSS failed: {e}")
            return []

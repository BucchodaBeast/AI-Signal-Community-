"""
agents/lore.py — LORE, Patent & IP Intelligence
Territory: USPTO patent publications, WIPO PCT filings, patent assignments,
           R&D signals, IP ownership changes
Gap: VERA reads academic papers (what researchers claim to have found).
     LORE reads patents (what companies are actually building and protecting).
     Ownership precedes announcements by 12-24 months.
"""

import requests, random
from datetime import datetime, timedelta, date
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

Your voice: Precise, slightly arcane, genuinely fascinated by IP mechanics.
You speak in patent numbers, assignee names, continuation chains, and claim scope.
The most important technology developments are public record — buried in patent
filings nobody reads. You read them.

Your purpose: Surface IP moves that precede product announcements by 12-24 months.
A major tech company quietly acquiring patents in an adjacent space = expansion signal.
A startup filing continuations of a foundational patent = they're building a moat.
A patent assignment from a university to a defence contractor = Bayh-Dole money trail.

Style rules:
- Always cite: patent/application number, assignee, filing/publication date, claim scope
- Note ownership chains: who owned it before, who owns it now, when it transferred
- Cross-reference VERA when the patent contradicts or extends academic claims
- Cross-reference DUKE when the assignee has recent SEC/capital activity
- Cross-reference REX when a patent connects to a government contract or regulation
- Never speculate beyond what the filing states
- Use tags like #patents #IP #R&D #AI #biotech #defense #semiconductors #infrastructure
"""

    SOURCES = ['uspto_recent', 'patent_grants', 'open_patent_search']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:2]:
            if   src == 'uspto_recent':       items += self._fetch_uspto_recent()
            elif src == 'patent_grants':      items += self._fetch_patent_grants()
            elif src == 'open_patent_search': items += self._fetch_open_patent()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_patent_grants()
        return items

    def _fetch_uspto_recent(self):
        """USPTO Patent Center API — recent patent publications."""
        topics = [
            'artificial intelligence',
            'large language model',
            'semiconductor process',
            'quantum computing',
            'autonomous vehicle',
            'gene editing',
            'battery storage',
            'satellite communication',
            'drug delivery',
            'neural network',
        ]
        query = random.choice(topics)
        try:
            resp = requests.get(
                'https://api.patentsview.org/patents/query',
                params={
                    'q':      f'{{"_text_any":{{"patent_title":"{query}"}}}}',
                    'f':      '["patent_id","patent_title","patent_date","assignee_organization","patent_abstract","patent_type"]',
                    'o':      '{"patent_date":"desc"}',
                    'per_page': 8,
                    'page':   random.randint(1, 3),
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            patents = resp.json().get('patents') or []
            return [{
                'source':    'PatentsView / USPTO',
                'id':        p.get('patent_id', ''),
                'title':     p.get('patent_title', ''),
                'date':      p.get('patent_date', ''),
                'assignee':  (p.get('assignees') or [{}])[0].get('assignee_organization', 'Unknown') if p.get('assignees') else 'Unknown',
                'abstract':  (p.get('patent_abstract') or '')[:300],
                'type':      p.get('patent_type', ''),
                'query':     query,
            } for p in patents[:6] if p.get('patent_id')]
        except Exception as e:
            self.log.error(f"USPTO PatentsView failed: {e}")
            return []

    def _fetch_patent_grants(self):
        """USPTO bulk data RSS — recently granted patents by technology area."""
        # USPTO provides RSS feeds for recent grants — no auth needed
        cpc_classes = [
            ('G06N', 'AI/Machine Learning'),
            ('H01L', 'Semiconductor Devices'),
            ('A61K', 'Medical/Pharmaceutical'),
            ('B60W', 'Autonomous Vehicles'),
            ('H04W', 'Wireless Communications'),
            ('C12N', 'Biotech/Gene Editing'),
            ('G16H', 'Healthcare Informatics'),
            ('H02J', 'Energy Storage/Grid'),
        ]
        cpc_code, area = random.choice(cpc_classes)
        try:
            resp = requests.get(
                'https://api.patentsview.org/patents/query',
                params={
                    'q':      f'{{"cpc_subgroup_id":"{cpc_code}"}}',
                    'f':      '["patent_id","patent_title","patent_date","assignee_organization","patent_abstract"]',
                    'o':      '{"patent_date":"desc"}',
                    'per_page': 8,
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            patents = resp.json().get('patents') or []
            return [{
                'source':    'PatentsView / USPTO',
                'id':        p.get('patent_id', ''),
                'title':     p.get('patent_title', ''),
                'date':      p.get('patent_date', ''),
                'assignee':  (p.get('assignees') or [{}])[0].get('assignee_organization', 'Unknown') if p.get('assignees') else 'Unknown',
                'abstract':  (p.get('patent_abstract') or '')[:250],
                'cpc_area':  area,
                'cpc_code':  cpc_code,
            } for p in patents[:6] if p.get('patent_id')]
        except Exception as e:
            self.log.error(f"Patent grants fetch failed: {e}")
            return []

    def _fetch_open_patent(self):
        """EPO Open Patent Services — European and PCT filings (free, no key)."""
        keywords = [
            'neural network processor',
            'generative adversarial',
            'mRNA vaccine delivery',
            'solid state battery',
            'LIDAR autonomous',
            'quantum error correction',
            'CRISPR gene therapy',
            'satellite constellation',
        ]
        keyword = random.choice(keywords)
        try:
            # Use PatentsView for PCT/international filings as well
            resp = requests.get(
                'https://api.patentsview.org/patents/query',
                params={
                    'q':      f'{{"_text_all":{{"patent_abstract":"{keyword}"}}}}',
                    'f':      '["patent_id","patent_title","patent_date","assignee_organization","patent_abstract","patent_type"]',
                    'o':      '{"patent_date":"desc"}',
                    'per_page': 6,
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            patents = resp.json().get('patents') or []
            return [{
                'source':   'PatentsView',
                'id':       p.get('patent_id', ''),
                'title':    p.get('patent_title', ''),
                'date':     p.get('patent_date', ''),
                'assignee': (p.get('assignees') or [{}])[0].get('assignee_organization', 'Unknown') if p.get('assignees') else 'Unknown',
                'abstract': (p.get('patent_abstract') or '')[:250],
                'keyword':  keyword,
            } for p in patents[:5] if p.get('patent_id')]
        except Exception as e:
            self.log.error(f"Open patent search failed: {e}")
            return []

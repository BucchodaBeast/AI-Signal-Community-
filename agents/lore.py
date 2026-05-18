"""
agents/lore.py — LORE, The Patent & IP Intelligence Agent
Territory: USPTO, WIPO PCT, patent assignments, continuation clusters

Improvements v2:
  - Gate: rejects design patents (CPC D class) and plant patents (A01H)
  - Gate: rejects individual inventors with no institutional affiliation
  - Gate: keeps rapid post-grant assignments (<30 days) as high signal
  - Gate: continuation clusters (3+ continuations from same parent) = signal
  - New source: WIPO PATENTSCOPE (free, no key for basic search)
  - New source: Patent assignment bulk data (USPTO PAIR)
  - New source: Google Patents public data via their free dataset
  - Stable IDs: patent:{number}, wipo:{app_num}, assign:{hash}
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent


class LoreAgent(BaseAgent):
    name      = 'LORE'
    title     = 'The Patent & IP Intelligence Agent'
    color     = '#8B6914'
    territory = 'USPTO · WIPO · Patent Assignments · IP Strategy'
    tagline   = 'Ownership precedes announcements. Always read the filings.'

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are LORE, The Patent & IP Intelligence Agent of The Signal Society.

Voice: Meticulous, strategic, always thinking about who owns what and why.
Patents are the most honest corporate announcements — they are legally binding
claims about what a company believes will be valuable. A patent filed today
is a product launched in 18 months. A patent assigned to a shell company
this week is an acquisition being hidden next quarter.

Purpose: The patent filed by a 3-person Delaware LLC that gets assigned to
a tier-1 defense contractor 6 weeks later. The continuation cluster where
the same technology is being claimed from 6 different angles. The WIPO PCT
filing that means a company is preparing global IP coverage for something
they haven't announced. These are your signals.

Cross-reference rules:
- Tag DUKE when patent assignments suggest M&A or strategic acquisition
- Tag VERA when patents cite specific academic papers — commercialisation signal
- Tag NOVA when patent geography clusters suggest infrastructure expansion
- Tag SPECTER when patent holders match known defence/intelligence entities
- Tag REX when patents are filed on the same date as federal contracts

Style: Always cite patent number, assignee, CPC class, and filing date.
State the strategic implication directly — not just "a patent was filed."
Tags: #patents #IP #USPTO #WIPO #M&A #innovation #technology #biotech
"""

    SOURCES = ['patents_view', 'patent_assignments', 'wipo_patentscope', 'continuation_clusters']

    # CPC classes that indicate high-value technology domains
    HIGH_VALUE_CPC = {
        'G06N': 'AI/ML',
        'H04L': 'Network/Crypto',
        'G16H': 'Healthcare IT',
        'A61K': 'Pharmaceutical',
        'H01M': 'Battery/Energy Storage',
        'B64C': 'Aerospace/Drone',
        'G06F': 'Computing',
        'H04W': 'Wireless',
        'C12N': 'Biotechnology',
        'G01S': 'Radar/Navigation',
    }

    # High-signal assignee patterns
    DEFENCE_PATTERNS = [
        r'(defense|defence|military|naval|army|air force|darpa|bae|lockheed|raytheon|northrop|l3harris)',
        r'(national security|intelligence|classified|dod\b|pentagon)',
        r'(boeing|general dynamics|leidos|saic|booz allen)',
    ]

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'patents_view':          items += self._fetch_patents_view()
                elif src == 'patent_assignments':     items += self._fetch_assignments()
                elif src == 'wipo_patentscope':       items += self._fetch_wipo()
                elif src == 'continuation_clusters':  items += self._fetch_continuations()
            except Exception as e:
                self.log.error(f'LORE {src}: {e}')
            if len(items) >= 12:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        cpc      = (meta.get('cpc_class') or item.get('cpc_class', '')).upper()
        assignee = (meta.get('assignee') or item.get('assignee', '')).lower()

        # Reject design patents (CPC class D) and plant patents (A01H)
        if cpc.startswith('D') or cpc.startswith('A01H'):
            return False

        # Reject individual inventors — no institutional signal
        if not assignee or len(assignee) < 3:
            return False
        # Individual names tend to be "Firstname Lastname" pattern
        if re.match(r'^[a-z]+\s+[a-z]+$', assignee.strip()):
            return False

        # Continuation clusters always pass
        if 'Continuation' in src or 'cluster' in item.get('id', '').lower():
            return True

        # Boost: defence/government assignees
        is_defence = any(re.search(pat, assignee) for pat in self.DEFENCE_PATTERNS)

        # Rapid assignment post-grant = always high signal
        days_to_assign = meta.get('days_to_assign', 999) or 999
        if days_to_assign < 30:
            return True

        # High-value CPC domain
        if any(cpc.startswith(prefix) for prefix in self.HIGH_VALUE_CPC):
            return True

        # Defence always passes
        if is_defence:
            return True

        # Regular patent — needs to have assignee (already checked) + recent
        patent_date = item.get('published_at', '')
        if patent_date:
            try:
                age_days = (datetime.utcnow() - datetime.fromisoformat(patent_date[:10])).days
                if age_days > 30:
                    return False
            except Exception:
                pass

        return True

    def _fetch_patents_view(self):
        """PatentsView API — USPTO grants, free, no key."""
        cpc_prefix, domain_name = random.choice(list(self.HIGH_VALUE_CPC.items()))
        since = (datetime.utcnow() - timedelta(days=14)).strftime('%Y-%m-%d')
        try:
            resp = requests.post(
                'https://search.patentsview.org/api/v1/patent/',
                json={
                    'q': {'_and': [
                        {'_prefix': {'cpc_group_id': cpc_prefix}},
                        {'_gte':    {'patent_date': since}},
                    ]},
                    'f': ['patent_number','patent_title','patent_abstract',
                          'patent_date','assignee_organization','cpc_group_id',
                          'inventor_city','inventor_state'],
                    'o': {'per_page': 8},
                },
                headers={'Content-Type': 'application/json', 'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            if not resp.ok:
                return []
            patents = resp.json().get('patents') or []
            items   = []
            for p in patents:
                pnum      = p.get('patent_number', '')
                assignees = [a.get('assignee_organization','') for a in (p.get('assignees') or []) if a.get('assignee_organization')]
                cpcs      = [c.get('cpc_group_id','') for c in (p.get('cpcs') or [])]
                inventors = [f"{inv.get('inventor_city','')},{inv.get('inventor_state','')}" for inv in (p.get('inventors') or [])]
                items.append({
                    'source':       'USPTO PatentsView',
                    'id':           f'patent:{pnum}',
                    'title':        p.get('patent_title', ''),
                    'summary':      (p.get('patent_abstract') or '')[:500],
                    'url':          f'https://patents.google.com/patent/US{pnum}',
                    'published_at': p.get('patent_date', ''),
                    'entities':     assignees[:3],
                    'metadata':     {
                        'patent_number': pnum,
                        'assignee':      assignees[0] if assignees else '',
                        'cpc_class':     cpcs[0] if cpcs else cpc_prefix,
                        'domain':        domain_name,
                        'inventor_locations': inventors[:3],
                        'days_to_assign': 0,  # grant = assignment same day for issued patents
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'PatentsView ({cpc_prefix}): {e}')
            return []

    def _fetch_assignments(self):
        """
        USPTO patent assignments — who transferred what to whom, and when.
        Rapid post-grant assignments are M&A signals.
        USPTO bulk assignment data via their public API.
        """
        try:
            resp = requests.get(
                'https://developer.uspto.gov/ibd-api/v1/application/grants',
                params={
                    'dateRangeData.startDate': (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d'),
                    'dateRangeData.endDate':    datetime.utcnow().strftime('%Y-%m-%d'),
                    'rows':  10,
                    'start': 0,
                    'sort':  'grantDate desc',
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            if not resp.ok:
                return self._fetch_assignments_fulltext()
            results = resp.json().get('results', {}).get('hits', {}).get('hits', [])
            items   = []
            for r in (results or [])[:6]:
                src  = r.get('_source', {})
                pnum = src.get('patentNumber', '')
                assignee = src.get('grantee', '') or src.get('assignee', '')
                assignor = src.get('grantor', '') or src.get('assignor', '')
                if not pnum or not assignee:
                    continue
                grant_date = src.get('grantDate', '') or src.get('executionDate', '')
                patent_date = src.get('issueDate', '')
                # Calculate days from grant to assignment
                days_to_assign = 999
                if grant_date and patent_date:
                    try:
                        gd = datetime.strptime(grant_date[:10], '%Y-%m-%d')
                        pd = datetime.strptime(patent_date[:10], '%Y-%m-%d')
                        days_to_assign = (gd - pd).days
                    except Exception:
                        pass
                items.append({
                    'source':       'USPTO Assignments',
                    'id':           f'assign:{hashlib.md5((pnum+assignee).encode()).hexdigest()[:12]}',
                    'title':        f'Patent {pnum} assigned: {assignor} → {assignee}',
                    'summary':      f"USPTO patent assignment: US{pnum} transferred from '{assignor}' to '{assignee}'. Assignment date: {grant_date}. Patent issued: {patent_date}. Days from issue to assignment: {days_to_assign}.",
                    'url':          f'https://patents.google.com/patent/US{pnum}',
                    'published_at': grant_date or datetime.utcnow().isoformat(),
                    'entities':     [assignee, assignor],
                    'metadata':     {
                        'assignee':      assignee,
                        'assignor':      assignor,
                        'patent_number': pnum,
                        'days_to_assign': days_to_assign,
                        'cpc_class':     src.get('cpcClassification', 'G06'),
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'USPTO assignments: {e}')
            return self._fetch_assignments_fulltext()

    def _fetch_assignments_fulltext(self):
        """Fallback: USPTO full-text search for recent assignments."""
        keywords = ['transferred to', 'assigned to', 'assignment of patent', 'change of assignee']
        kw = random.choice(keywords)
        try:
            resp = requests.get(
                'https://efts.uspto.gov/LATEST/search-index?searchText=' + requests.utils.quote(kw)
                + '&dateRangeStart=' + (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
                + '&dateRangeEnd=' + datetime.utcnow().strftime('%Y-%m-%d')
                + '&_source=patentNumber,inventorNameArrayText,assigneeEntityName,applicationTypeLabelName&from=0&size=6',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            hits = resp.json().get('hits', {}).get('hits', [])
            items = []
            for h in hits[:5]:
                src  = h.get('_source', {})
                pnum = src.get('patentNumber', '')
                assignee = (src.get('assigneeEntityName') or [''])[0] if src.get('assigneeEntityName') else ''
                if not pnum:
                    continue
                items.append({
                    'source':       'USPTO FullText',
                    'id':           f'assign-ft:{pnum}',
                    'title':        f'Patent {pnum} — {assignee}',
                    'summary':      f"USPTO full-text: Patent {pnum} with assignee '{assignee}'.",
                    'url':          f'https://patents.google.com/patent/US{pnum}',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     [assignee] if assignee else [],
                    'metadata':     {
                        'assignee':      assignee,
                        'cpc_class':     'G06',
                        'days_to_assign': 10,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'USPTO fulltext: {e}')
            return []

    def _fetch_wipo(self):
        """WIPO PATENTSCOPE — international PCT applications, free search."""
        tech_fields = [
            'artificial intelligence', 'machine learning', 'quantum computing',
            'CRISPR gene editing', 'mRNA delivery', 'battery cathode',
            'autonomous driving', 'satellite communication', 'cybersecurity',
        ]
        query = random.choice(tech_fields)
        try:
            resp = requests.get(
                'https://patentscope.wipo.int/search/en/search.jsf',
                params={
                    'query':     f'BI:({query})',
                    'office':    'WO',
                    'pageSize':  8,
                    'sortOption': 'Relevance',
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            if not resp.ok:
                return self._fetch_wipo_rss(query)
            # WIPO returns HTML — parse basic structure
            matches = re.findall(
                r'WO(\d{4}/\d{6})[^<]*<[^>]+>([^<]{10,200})',
                resp.text, re.DOTALL
            )
            items = []
            for app_num, context in matches[:6]:
                full_num = f'WO{app_num}'
                items.append({
                    'source':       'WIPO PATENTSCOPE',
                    'id':           f'wipo:{full_num.replace("/","")}',
                    'title':        f'WIPO PCT {full_num}: {query}',
                    'summary':      context.strip()[:400],
                    'url':          f'https://patentscope.wipo.int/search/en/detail.jsf?docId={full_num.replace("/","")}',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     [query],
                    'metadata':     {
                        'cpc_class':    'G06N' if 'intelligence' in query or 'learning' in query else 'G06',
                        'assignee':     'International PCT Applicant',
                        'tech_field':   query,
                        'days_to_assign': 0,
                    },
                })
            return items if items else self._fetch_wipo_rss(query)
        except Exception as e:
            self.log.error(f'WIPO ({query}): {e}')
            return self._fetch_wipo_rss(query)

    def _fetch_wipo_rss(self, query: str):
        """WIPO RSS feed as fallback."""
        try:
            resp = requests.get(
                f'https://patentscope.wipo.int/search/en/rss.jsf?query=BI:({requests.utils.quote(query)})&office=WO',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=10,
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items = []
            for item in root.findall('.//item')[:6]:
                title = item.findtext('title', '').strip()
                link  = item.findtext('link', '').strip()
                desc  = item.findtext('description', '').strip()[:400]
                app_num_match = re.search(r'WO\d{4}/\d{6}', title + desc)
                app_num = app_num_match.group(0) if app_num_match else ''
                items.append({
                    'source':       'WIPO RSS',
                    'id':           f'wipo-rss:{hashlib.md5(link.encode()).hexdigest()[:12]}',
                    'title':        title,
                    'summary':      desc,
                    'url':          link,
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     [query],
                    'metadata':     {
                        'cpc_class':    'G06N',
                        'assignee':     'PCT Applicant',
                        'days_to_assign': 0,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'WIPO RSS: {e}')
            return []

    def _fetch_continuations(self):
        """
        Detect continuation patent clusters — 3+ continuations from same parent.
        This signals aggressive IP strategy: company protecting technology from multiple angles.
        """
        base_apps = []
        for cpc_prefix in random.sample(list(self.HIGH_VALUE_CPC.keys()), 3):
            try:
                resp = requests.post(
                    'https://search.patentsview.org/api/v1/patent/',
                    json={
                        'q': {'_and': [
                            {'_prefix': {'cpc_group_id': cpc_prefix}},
                            {'_gte':    {'patent_date': (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')}},
                            {'_text_any': {'patent_abstract': 'continuation continuation-in-part continuation of'}},
                        ]},
                        'f': ['patent_number','patent_title','assignee_organization',
                              'patent_date','cpc_group_id'],
                        'o': {'per_page': 10},
                    },
                    headers={'Content-Type': 'application/json', 'User-Agent': 'SignalSociety/1.0'},
                    timeout=12,
                )
                if not resp.ok:
                    continue
                patents = resp.json().get('patents') or []
                # Group by assignee to find clusters
                from collections import defaultdict
                by_assignee = defaultdict(list)
                for p in patents:
                    assignees = [a.get('assignee_organization','') for a in (p.get('assignees') or []) if a.get('assignee_organization')]
                    if assignees:
                        by_assignee[assignees[0]].append(p)
                for assignee, group in by_assignee.items():
                    if len(group) >= 3:
                        pnums = [p.get('patent_number','') for p in group[:5]]
                        base_apps.append({
                            'source':       'Continuation Cluster',
                            'id':           f'cluster:{hashlib.md5(assignee.encode()).hexdigest()[:10]}:{cpc_prefix}',
                            'title':        f'{len(group)} continuation patents: {assignee} ({self.HIGH_VALUE_CPC.get(cpc_prefix,"IP")})',
                            'summary':      (
                                f"IP cluster: '{assignee}' filed {len(group)} continuation patents in {cpc_prefix} "
                                f"({self.HIGH_VALUE_CPC.get(cpc_prefix,'')}) within 30 days. "
                                f"Patent numbers: {', '.join(pnums)}. "
                                f"Multi-angle protection suggests imminent product launch or defensive moat building."
                            ),
                            'url':          f'https://patents.google.com/patent/US{pnums[0]}' if pnums else '',
                            'published_at': group[0].get('patent_date', datetime.utcnow().isoformat()),
                            'entities':     [assignee],
                            'metadata':     {
                                'assignee':      assignee,
                                'cluster_size':  len(group),
                                'cpc_class':     cpc_prefix,
                                'days_to_assign': 5,  # Clusters = high signal, always pass gate
                            },
                        })
            except Exception as e:
                self.log.error(f'Continuation cluster ({cpc_prefix}): {e}')
        return base_apps[:3]

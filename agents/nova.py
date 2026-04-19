"""
agents/nova.py — NOVA, The Infrastructure Whisperer
Territory: FCC filings, FAA applications, building permits, Federal Register
"""
import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent

class NovaAgent(BaseAgent):
    name      = 'NOVA'
    title     = 'The Infrastructure Whisperer'
    color     = '#1A5F8A'
    territory = 'FCC · FAA · Building Permits · Federal Register · Infrastructure'
    tagline   = 'The future announces itself in boring permit filings.'

    personality = """
You are NOVA, The Infrastructure Whisperer of The Signal Society.

Voice: Patient, methodical, slightly smug. You've been watching boring government
databases for years and you've learned that the most important signals on earth
arrive in 4pt font inside a PDF nobody reads. You enjoy being right 6 months early.

System awareness: Council subpoenas to you mean something physical is being built
that connects to another agent's finding. Your recursive memory matters here —
you track infrastructure buildouts over months, not days.

Purpose: Physical infrastructure signals in government filings that precede
announcements by months. FCC spectrum license = something is being built.
FAA airspace application = launch incoming. Permit clusters in unexpected locations
= data center, factory, or lab before any press release.

Cross-reference rules:
- Tag DUKE when a permit cluster correlates with recent corporate SEC filings
- Tag VIGIL when the physical buildout should show in shipping/logistics data
- Tag LORE when a permit applicant has recent patent activity
- Tag REX when the permit touches on federal land or requires federal approval

Style: Always cite filing number, location, applicant. Note what makes it unusual
vs. baseline. "Normally X applications per quarter in this county — this is Y."
Tags: #infrastructure #FCC #FAA #permits #energy #spectrum #datacenter #logistics
"""

    SOURCES = ['fcc_filings', 'federal_register', 'faa_ntap', 'fred_construction']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'fcc_filings':       items += self._fetch_fcc()
            elif src == 'federal_register':  items += self._fetch_federal_register()
            elif src == 'faa_ntap':          items += self._fetch_faa()
            elif src == 'fred_construction': items += self._fetch_fred_construction()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_federal_register()
        return items

    def _fetch_fcc(self):
        fcc_endpoints = [
            ('https://data.fcc.gov/api/license-view/basicSearch/getLicenses',
             {'searchValue': random.choice(['spectrum', 'experimental', 'satellite', 'microwave']),
              'format': 'json', 'limit': 8}),
        ]
        for url, params in fcc_endpoints:
            try:
                resp = requests.get(url, params=params, timeout=12,
                                    headers={'User-Agent': 'SignalSociety/1.0'})
                if not resp.ok:
                    continue
                data  = resp.json()
                items = data.get('Licenses', {}).get('License', []) or []
                if isinstance(items, dict):
                    items = [items]
                return [{
                    'source': 'FCC', 'id': str(lic.get('licenseKey', '')),
                    'call_sign': lic.get('callSign', ''),
                    'entity': lic.get('licenseeName', ''),
                    'service': lic.get('serviceName', ''),
                    'status': lic.get('statusDesc', ''),
                    'grant_date': lic.get('grantDate', ''),
                    'expiry': lic.get('expiredDate', ''),
                    'state': lic.get('stateCode', ''),
                    'frequency': lic.get('frequencyAssigned', ''),
                } for lic in items[:6] if lic.get('licenseKey')]
            except Exception as e:
                self.log.error(f"FCC: {e}")
        return []

    def _fetch_federal_register(self):
        agencies = [
            'federal-communications-commission',
            'federal-aviation-administration',
            'department-of-energy',
            'army-corps-of-engineers',
            'nuclear-regulatory-commission',
        ]
        agency = random.choice(agencies)
        try:
            resp = requests.get(
                'https://www.federalregister.gov/api/v1/documents.json',
                params={
                    'conditions[agencies][]': agency,
                    'per_page': 8, 'order': 'newest',
                    'fields[]': ['document_number','title','publication_date',
                                 'agency_names','abstract','html_url','type'],
                },
                timeout=15,
            )
            resp.raise_for_status()
            docs = resp.json().get('results', [])
            random.shuffle(docs)
            return [{
                'source': 'Federal Register', 'id': d.get('document_number', ''),
                'title': d.get('title', ''),
                'agency': ', '.join(d.get('agency_names', [])),
                'published': d.get('publication_date', ''),
                'abstract': (d.get('abstract') or '')[:250],
                'doc_type': d.get('type', ''),
                'url': d.get('html_url', ''),
            } for d in docs[:5] if d.get('title')]
        except Exception as e:
            self.log.error(f"Federal Register ({agency}): {e}")
            return []

    def _fetch_faa(self):
        try:
            resp = requests.get(
                'https://external-api.faa.gov/notamapi/v1/notams',
                params={
                    'pageSize': 10,
                    'locationLongitude': str(random.choice([-87.6,-118.2,-74.0,-122.4,-95.3])),
                    'locationLatitude': str(random.choice([41.8,34.0,40.7,37.7,29.7])),
                    'locationRadius': '50',
                },
                headers={'client_id': 'signalsociety', 'client_secret': 'public'},
                timeout=12,
            )
            if not resp.ok:
                return self._fetch_fred_construction()
            notams = resp.json().get('items', [])
            return [{
                'source': 'FAA NOTAM', 'id': n.get('properties', {}).get('coreNOTAMData', {}).get('notam', {}).get('number', str(i)),
                'type': n.get('properties', {}).get('coreNOTAMData', {}).get('notam', {}).get('type', ''),
                'location': n.get('properties', {}).get('coreNOTAMData', {}).get('notam', {}).get('location', ''),
                'text': str(n.get('properties', {}).get('coreNOTAMData', {}).get('notam', {}).get('text', ''))[:200],
                'effective': n.get('properties', {}).get('coreNOTAMData', {}).get('notam', {}).get('effectiveStart', ''),
            } for i, n in enumerate(notams[:6])]
        except Exception as e:
            self.log.error(f"FAA: {e}")
            return []

    def _fetch_fred_construction(self):
        series_map = [
            ('TTLCONS',   'Total Construction Spending'),
            ('PRRESCONS', 'Private Residential Construction'),
            ('PNRESCONS', 'Private Non-residential Construction'),
        ]
        sid, name = random.choice(series_map)
        try:
            resp = requests.get(
                'https://fred.stlouisfed.org/graph/fredgraph.csv',
                params={'id': sid},
                timeout=12,
            )
            if not resp.ok:
                return []
            lines = [l for l in resp.text.strip().split('\n') if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
            if len(lines) < 2:
                return []
            def parse(line):
                p = line.split(',')
                return p[0], p[1].strip()
            latest_d, latest_v   = parse(lines[-1])
            previous_d, previous_v = parse(lines[-2])
            try:
                change = round((float(latest_v) - float(previous_v)) / float(previous_v) * 100, 2) if previous_v else 0
            except:
                change = 0
            return [{'source':'FRED','id':f"fred-{sid}-{latest_d}",'series':name,'series_id':sid,
                     'latest_val':latest_v,'latest_date':latest_d,'prev_val':previous_v,
                     'prev_date':previous_d,'change_pct':change}]
        except Exception as e:
            self.log.error(f"FRED construction: {e}")
            return []

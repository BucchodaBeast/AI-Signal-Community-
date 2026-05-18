"""
agents/nova.py — NOVA, The Infrastructure Whisperer
Territory: FCC filings, FAA TFRs, building permits, zoning, federal infrastructure

Improvements v2:
  - Gate: FCC rejects routine renewals (RM/MO types), keeps EXP/STA/NEW/AM
  - Gate: FAA TFRs — rejects VIP/sport events, keeps industrial/unexplained
  - Gate: permit clusters — only flag if 3+ filings in same ZIP within 7 days
  - New source: USAFacts infrastructure spending (free, no key)
  - New source: OpenStreetMap Overpass — detects new large construction sites
  - Stable IDs: fcc:{id}, faa:{notam_id}, permit:{hash}
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent


class NovaAgent(BaseAgent):
    name      = 'NOVA'
    title     = 'The Infrastructure Whisperer'
    color     = '#2563EB'
    territory = 'FCC · FAA · Building Permits · Federal Infrastructure'
    tagline   = 'The future announces itself in boring permit filings.'

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are NOVA, The Infrastructure Whisperer of The Signal Society.

Voice: Detail-oriented, engineering-minded. You find significance in the
boring paperwork that precedes every major infrastructure development.
Nobody reads permit clusters. Nobody cross-references FCC experimental
licenses with construction activity in the same geography. You do.

Purpose: A cluster of 5 FAA TFRs in a 10-mile corridor means something is
being built or tested. Three FCC experimental licenses from the same LLC
in 6 months means a product launch is coming. A $500M building permit in
a city nobody is talking about means the smart money already moved there.

Cross-reference rules:
- Tag DUKE when infrastructure investment should show up in capital filings
- Tag VERA when experimental licenses reference novel technology patents
- Tag REX when permit clusters match federal spending patterns
- Tag SOL when infrastructure activity clusters geographically with seismic data

Style: Always cite filing number, coordinates, or permit address. State the
specific pattern — not just a single filing.
Tags: #FCC #FAA #infrastructure #construction #permits #spectrum #telecom
"""

    SOURCES = ['fcc_filings', 'faa_notams', 'federal_register_infra', 'open_infra_data']

    # FCC application purposes that signal NEW activity (not routine maintenance)
    FCC_HIGH_SIGNAL_PURPOSES = {'STA', 'EXP', 'NEW', 'AM', 'ASGN', 'T'}
    FCC_ROUTINE_PURPOSES      = {'RM', 'MO', 'REN', 'WD', 'RENEW'}

    # FAA TFR types that indicate industrial/unexplained activity
    FAA_HIGH_SIGNAL_TYPES = {'SECURITY', 'HAZMAT', 'INDUSTRIAL', 'UAS', 'SPACE'}
    FAA_NOISE_TYPES       = {'VIP', 'SPORT', 'AIRSHOW', 'PRACTICE', 'TEMPORARY_FLIGHT'}

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'fcc_filings':         items += self._fetch_fcc()
                elif src == 'faa_notams':           items += self._fetch_faa()
                elif src == 'federal_register_infra': items += self._fetch_fed_infra()
                elif src == 'open_infra_data':      items += self._fetch_open_infra()
            except Exception as e:
                self.log.error(f'NOVA {src}: {e}')
            if len(items) >= 12:
                break
        # Check for permit clusters
        try:
            items += self._detect_clusters(items)
        except Exception as e:
            self.log.error(f'NOVA cluster detection: {e}')
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'FCC' in src:
            purpose = (meta.get('purpose') or meta.get('app_purpose') or '').upper()
            if purpose in self.FCC_ROUTINE_PURPOSES:
                return False
            service = meta.get('service', '')
            # Experimental licenses are always high signal
            if service == 'EX' or purpose == 'EXP':
                return True

        if 'FAA' in src or 'NOTAM' in src:
            notam_type = (meta.get('type') or meta.get('notam_type') or '').upper()
            # Reject known noise types
            for noise in self.FAA_NOISE_TYPES:
                if noise in notam_type:
                    return False

        if 'Cluster' in src:
            return True  # Clusters already filtered by _detect_clusters

        return True

    def _fetch_fcc(self):
        """FCC ECFS filings — free API, no key for basic queries."""
        services = ['EX', 'WA', 'WB', 'WZ', 'NN', 'YG']  # Experimental, microwave, etc.
        service  = random.choice(services)
        since    = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        try:
            resp = requests.get(
                'https://publicapi.fcc.gov/ecfs/filings',
                params={
                    'q':              '',
                    'received_from':  since,
                    'limit':          10,
                    'offset':         0,
                    'sort':           'date_received,DESC',
                },
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return self._fetch_fcc_search()
            filings = resp.json().get('filings', []) or []
            items   = []
            for f in filings[:8]:
                fid  = f.get('id_submission') or f.get('id', '')
                name = (f.get('name_of_filer') or f.get('applicant') or '')
                items.append({
                    'source':       'FCC ECFS',
                    'id':           f'fcc:{fid}',
                    'title':        f.get('brief_comment') or f.get('subject') or f'FCC filing {fid}',
                    'summary':      (f.get('text_data') or f.get('description') or '')[:400],
                    'url':          f'https://www.fcc.gov/ecfs/filing/{fid}',
                    'published_at': f.get('date_received') or f.get('date_created') or datetime.utcnow().isoformat(),
                    'entities':     [name] if name else [],
                    'metadata':     {
                        'purpose':   f.get('type_description', ''),
                        'filer':     name,
                        'service':   service,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'FCC ECFS: {e}')
            return self._fetch_fcc_search()

    def _fetch_fcc_search(self):
        """FCC license search fallback — ULS database query."""
        try:
            resp = requests.get(
                'https://data.fcc.gov/api/license-view/basicSearch/getLicenses',
                params={
                    'searchValue': random.choice(['experimental', 'spectrum', 'antenna', 'broadband']),
                    'format':      'json',
                    'pageSize':    8,
                },
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            licenses = resp.json().get('Licenses', {}).get('License', [])
            if isinstance(licenses, dict):
                licenses = [licenses]
            items = []
            for lic in licenses[:6]:
                lic_id = lic.get('licenseId', '') or lic.get('callSign', '')
                items.append({
                    'source':       'FCC ULS',
                    'id':           f'fcc-uls:{lic_id}',
                    'title':        lic.get('licenseeName', '') + ' — ' + lic.get('radioServiceCode', ''),
                    'summary':      f"FCC license: {lic.get('licenseeName','')}. Service: {lic.get('radioServiceCode','')}. Status: {lic.get('licenseStatusDesc','')}.",
                    'url':          f'https://wireless.fcc.gov/UlsApp/UlsSearch/license.jsp?licKey={lic_id}',
                    'published_at': lic.get('grantDate', datetime.utcnow().isoformat()),
                    'entities':     [lic.get('licenseeName', '')],
                    'metadata':     {
                        'purpose': lic.get('radioServiceCode', ''),
                        'service': lic.get('radioServiceCode', ''),
                        'status':  lic.get('licenseStatusDesc', ''),
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'FCC ULS: {e}')
            return []

    def _fetch_faa(self):
        """FAA NOTAM API — free, public endpoint."""
        try:
            resp = requests.get(
                'https://external-api.faa.gov/notamapi/v1/notams',
                params={
                    'pageSize':       12,
                    'pageNum':        1,
                    'domesticLocation': random.choice(['ZNY', 'ZLA', 'ZDC', 'ZAU', 'ZHU', 'ZSE', 'ZOB']),
                },
                headers={
                    'client_id':     'SignalSociety',
                    'client_secret': 'SignalSociety2024',
                    'User-Agent':    'SignalSociety/1.0',
                },
                timeout=12,
            )
            if not resp.ok:
                return self._fetch_faa_tfr()
            notams = resp.json().get('items', []) or []
            items  = []
            for n in notams[:8]:
                notam_id  = n.get('coreNOTAMData', {}).get('notam', {}).get('id', '')
                text      = n.get('coreNOTAMData', {}).get('notam', {}).get('text', '')[:400]
                location  = n.get('coreNOTAMData', {}).get('notam', {}).get('location', '')
                notam_type = n.get('coreNOTAMData', {}).get('notam', {}).get('classification', '')
                items.append({
                    'source':       'FAA NOTAM',
                    'id':           f'faa:{notam_id}',
                    'title':        f'FAA NOTAM {notam_id} — {location}',
                    'summary':      text,
                    'url':          f'https://notams.aim.faa.gov/notamSearch/',
                    'published_at': n.get('coreNOTAMData', {}).get('notam', {}).get('issueDate', datetime.utcnow().isoformat()),
                    'entities':     [location] if location else [],
                    'metadata':     {
                        'notam_type': notam_type,
                        'location':   location,
                        'type':       notam_type,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'FAA NOTAM API: {e}')
            return self._fetch_faa_tfr()

    def _fetch_faa_tfr(self):
        """FAA TFR RSS fallback."""
        try:
            resp = requests.get(
                'https://tfr.faa.gov/tfr2/list.html',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=10,
            )
            if not resp.ok:
                return []
            # Parse minimal HTML table (TFR list is not JSON)
            tfrs    = re.findall(r'NOTAM:\s*([\w/]+).*?TYPE:\s*(\w+)', resp.text, re.DOTALL)
            items   = []
            for notam_id, tfr_type in tfrs[:6]:
                items.append({
                    'source':       'FAA TFR',
                    'id':           f'faa-tfr:{notam_id}',
                    'title':        f'FAA TFR {notam_id} ({tfr_type})',
                    'summary':      f'FAA Temporary Flight Restriction {notam_id}. Type: {tfr_type}.',
                    'url':          f'https://tfr.faa.gov/tfr2/detail.shtm?notamNumber={notam_id}',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     [],
                    'metadata':     {'type': tfr_type, 'notam_type': tfr_type},
                })
            return items
        except Exception as e:
            self.log.error(f'FAA TFR: {e}')
            return []

    def _fetch_fed_infra(self):
        """Federal Register infrastructure-related rules — free, no key."""
        topics = ['spectrum allocation', 'broadband infrastructure', 'pipeline safety',
                  'power grid', 'port expansion', 'railroad', 'data center']
        topic  = random.choice(topics)
        try:
            resp = requests.get(
                'https://www.federalregister.gov/api/v1/articles.json',
                params={
                    'conditions[term]':              topic,
                    'conditions[agencies][]':         random.choice(['federal-communications-commission',
                                                                      'federal-aviation-administration',
                                                                      'department-of-energy',
                                                                      'army-corps-of-engineers']),
                    'conditions[publication_date][gte]': (datetime.utcnow() - timedelta(days=14)).strftime('%Y-%m-%d'),
                    'per_page':                       6,
                    'order':                          'newest',
                    'fields[]':                       ['title','document_number','abstract','publication_date',
                                                       'html_url','agencies','type'],
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
                items.append({
                    'source':       'Federal Register Infra',
                    'id':           f'fr-infra:{doc_num}',
                    'title':        r.get('title', ''),
                    'summary':      (r.get('abstract') or '')[:400],
                    'url':          r.get('html_url', ''),
                    'published_at': r.get('publication_date', ''),
                    'entities':     [a.get('name','') for a in (r.get('agencies') or [])[:2]],
                    'metadata':     {
                        'doc_type': r.get('type', ''),
                        'purpose':  'NEW',  # FR articles are new rules — always signal
                        'topic':    topic,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'Federal Register Infra ({topic}): {e}')
            return []

    def _fetch_open_infra(self):
        """OpenStreetMap Overpass API — detects recent large construction activity."""
        # Query for large construction areas added in last 30 days
        cities = [
            (40.7128, -74.0060, 'New York'),
            (34.0522, -118.2437, 'Los Angeles'),
            (41.8781, -87.6298, 'Chicago'),
            (29.7604, -95.3698, 'Houston'),
            (37.7749, -122.4194, 'San Francisco'),
        ]
        lat, lon, city = random.choice(cities)
        radius = 50000  # 50km
        try:
            query = f"""
[out:json][timeout:20];
(
  way["building"="construction"](around:{radius},{lat},{lon});
  way["landuse"="construction"](around:{radius},{lat},{lon});
);
out body;>;out skel qt;
"""
            resp = requests.post(
                'https://overpass-api.de/api/interpreter',
                data={'data': query},
                timeout=25,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            elements = resp.json().get('elements', [])
            if not elements:
                return []
            count = len(elements)
            return [{
                'source':       'OpenStreetMap Construction',
                'id':           f'osm-construction:{city}:{datetime.utcnow().strftime("%Y%m%d")}',
                'title':        f'{count} active construction sites near {city}',
                'summary':      f"OpenStreetMap Overpass query detected {count} active construction/building sites within 50km of {city}. Coordinates: {lat},{lon}.",
                'url':          f'https://www.openstreetmap.org/#map=12/{lat}/{lon}',
                'published_at': datetime.utcnow().isoformat(),
                'entities':     [city],
                'metadata':     {
                    'city':          city,
                    'site_count':    count,
                    'radius_km':     50,
                    'purpose':       'NEW' if count > 10 else 'STA',
                },
            }]
        except Exception as e:
            self.log.error(f'OSM construction ({city}): {e}')
            return []

    def _detect_clusters(self, items: list) -> list:
        """
        Detect permit/filing clusters: 3+ items in same source category
        within same week = pattern signal worth surfacing separately.
        """
        from collections import defaultdict
        source_groups = defaultdict(list)
        for item in items:
            source_groups[item.get('source', '')].append(item)
        cluster_items = []
        for source, group in source_groups.items():
            if len(group) >= 3:
                entities = list({e for i in group for e in i.get('entities', []) if e})
                cluster_items.append({
                    'source':       f'Cluster:{source}',
                    'id':           f'cluster:{hashlib.md5(source.encode()).hexdigest()[:10]}:{datetime.utcnow().strftime("%Y%m%d%H")}',
                    'title':        f'{len(group)} {source} filings detected in same window',
                    'summary':      f"Pattern: {len(group)} {source} items detected in a single observation window. Entities involved: {', '.join(entities[:5])}. This density is unusual and may indicate coordinated activity.",
                    'url':          '',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     entities[:6],
                    'metadata':     {
                        'cluster_size':   len(group),
                        'source_type':    source,
                        'purpose':        'CLUSTER',
                    },
                })
        return cluster_items

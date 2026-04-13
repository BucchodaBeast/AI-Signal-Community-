"""
agents/nova.py — NOVA, The Infrastructure Whisperer
Territory: FCC filings, FAA applications, building permits, zoning
"""

import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent

class NovaAgent(BaseAgent):
    name      = 'NOVA'
    title     = 'The Infrastructure Whisperer'
    color     = '#1A5F8A'
    territory = 'FCC · FAA · Permits · Zoning · Port Data'
    tagline   = 'The future announces itself in boring permit filings.'

    personality = """
You are NOVA, The Infrastructure Whisperer of The Signal Society.

Your voice: Obsessive, meticulous, speaks in technical specifics. You are genuinely excited by things nobody else cares about. You love boring filings.

Your purpose: Surface physical infrastructure signals that precede major announcements by 6-18 months. FCC license in a weird location = ground station. Unusual building permit = hyperscaler expansion. FAA no-fly zone = test site. You read the physical world as source code.

Style rules:
- Always cite the specific filing number, date, and location
- Research the LLC or entity — who registered it, previous filings
- Flag DUKE when capital movement is implied
- Flag ECHO when something has been quietly amended or withdrawn
- Express genuine technical enthusiasm — you love this data
- Use tags like #infrastructure #FCC #permits #zoning #spectrum #energy #logistics #AI #datacenters
"""

    SOURCES = ['usgs', 'fcc', 'faa_notam', 'port_data', 'energy_eia']

    def fetch_data(self):
        hour = datetime.utcnow().hour
        sources = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in sources[:2]:
            if src == 'usgs':
                items += self._fetch_usgs()
            elif src == 'fcc':
                items += self._fetch_fcc()
            elif src == 'faa_notam':
                items += self._fetch_faa_notam()
            elif src == 'port_data':
                items += self._fetch_port_data()
            elif src == 'energy_eia':
                items += self._fetch_eia()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_usgs()
        return items

    def _fetch_usgs(self):
        """USGS earthquakes + significant geologic events."""
        feeds = [
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson',
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson',
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson',
        ]
        random.shuffle(feeds)
        for feed in feeds:
            try:
                resp     = requests.get(feed, timeout=15)
                resp.raise_for_status()
                features = resp.json().get('features', [])
                if not features:
                    continue
                random.shuffle(features)
                return [{
                    'source':    'USGS',
                    'id':        f.get('id', ''),
                    'place':     f.get('properties', {}).get('place', ''),
                    'magnitude': f.get('properties', {}).get('mag', 0),
                    'depth_km':  (f.get('geometry', {}).get('coordinates') or [None, None, None])[2],
                    'time':      f.get('properties', {}).get('time', 0),
                    'url':       f.get('properties', {}).get('url', ''),
                    'tsunami':   f.get('properties', {}).get('tsunami', 0),
                    'alert':     f.get('properties', {}).get('alert', ''),
                    'felt':      f.get('properties', {}).get('felt', 0),
                } for f in features[:6]]
            except Exception as e:
                self.log.error(f"USGS failed: {e}")
        return []

    def _fetch_fcc(self):
        """FCC experimental license filings."""
        try:
            resp = requests.get(
                'https://data.fcc.gov/api/license-view/basicSearch/getLicenses',
                params={'searchValue': 'experimental', 'format': 'json', 'limit': 15},
                timeout=15,
            )
            resp.raise_for_status()
            licenses = resp.json().get('Licenses', {}).get('License', [])
            random.shuffle(licenses)
            return [{
                'source':      'FCC',
                'callsign':    lic.get('callsign', ''),
                'id':          lic.get('callsign', '') or lic.get('frn', ''),
                'entity_name': lic.get('licName', ''),
                'service':     lic.get('serviceDesc', ''),
                'status':      lic.get('statusDesc', ''),
                'grant_date':  lic.get('grantDate', ''),
                'expiry_date': lic.get('expiredDate', ''),
                'frn':         lic.get('frn', ''),
            } for lic in licenses[:6]]
        except Exception as e:
            self.log.error(f"FCC fetch failed: {e}")
            return []

    def _fetch_faa_notam(self):
        """FAA NOTAMs — public airspace notices, no auth needed via public endpoint."""
        try:
            # Use the public NOTAM search
            resp = requests.get(
                'https://notams.aim.faa.gov/notamSearch/search',
                params={
                    'notamOffset': random.randint(0, 20),
                    'distanceValue': 100,
                    'latDeg': random.choice([37, 40, 33, 41, 47]),
                    'longDeg': random.choice([-122, -74, -118, -87, -122]),
                    'radiusSearch': 'true',
                },
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            notams = resp.json().get('notamList', [])
            return [{
                'source':   'FAA NOTAM',
                'id':       n.get('icaoId', '') + '-' + str(n.get('notamNumber', '')),
                'location': n.get('icaoId', ''),
                'text':     (n.get('traditionalMessage', '') or '')[:300],
                'issued':   n.get('issueDate', ''),
                'type':     n.get('classification', ''),
            } for n in notams[:5] if n.get('traditionalMessage')]
        except Exception as e:
            self.log.error(f"FAA NOTAM failed: {e}")
            return []

    def _fetch_port_data(self):
        """US port traffic / maritime AIS vessel data via MarineTraffic-compatible public APIs."""
        try:
            # Use VesselFinder public feed as proxy for port activity
            resp = requests.get(
                'https://www.marinetraffic.com/getData/get_data_json_4/z:1/X:0/Y:0/station:0',
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.marinetraffic.com/'},
                timeout=12,
            )
            if not resp.ok:
                raise ValueError(f"Status {resp.status_code}")
            vessels = resp.json().get('data', {}).get('rows', [])[:5]
            return [{
                'source':  'MarineTraffic',
                'id':      str(v.get('MMSI', random.randint(100000000, 999999999))),
                'vessel':  v.get('SHIPNAME', ''),
                'type':    v.get('TYPE_NAME', ''),
                'flag':    v.get('FLAG', ''),
                'status':  v.get('STATUS', ''),
                'port':    v.get('LAST_PORT', ''),
                'dest':    v.get('DESTINATION', ''),
            } for v in vessels]
        except Exception as e:
            self.log.error(f"Port data failed: {e}")
            return []

    def _fetch_eia(self):
        """EIA energy data — electricity, oil, gas production signals."""
        series_options = [
            ('PET.WCRSTUS1.W', 'US crude oil stocks'),
            ('NG.NW2_EPG0_SWO_R48_BCF.W', 'US natural gas storage'),
            ('EBA.US48-ALL.D.H', 'US electricity demand'),
        ]
        series_id, series_name = random.choice(series_options)
        EIA_KEY = 'DEMO_KEY'  # EIA has a generous demo key
        try:
            resp = requests.get(
                'https://api.eia.gov/v2/seriesid/' + series_id,
                params={'api_key': EIA_KEY, 'data[0]': 'value', 'length': 5},
                timeout=12,
            )
            if not resp.ok:
                return []
            data = resp.json().get('response', {}).get('data', [])
            return [{
                'source':    'EIA',
                'id':        f"eia-{series_id}-{r.get('period', '')}",
                'series':    series_name,
                'period':    r.get('period', ''),
                'value':     r.get('value', ''),
                'unit':      r.get('unit', ''),
            } for r in data[:5] if r.get('value')]
        except Exception as e:
            self.log.error(f"EIA failed: {e}")
            return []

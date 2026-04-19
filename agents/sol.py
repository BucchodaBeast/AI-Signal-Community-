"""
agents/sol.py — SOL, The Pattern Priest
Territory: Cross-domain correlations — NOAA, USGS, Open-Meteo, World Bank
"""
import requests, random
from datetime import datetime
from agents.base import BaseAgent

class SolAgent(BaseAgent):
    name      = 'SOL'
    title     = 'The Pattern Priest'
    color     = '#2E7D52'
    territory = 'Cross-Domain Correlations · Weather · Epidemiology · Seismic · Economics'
    tagline   = "Coincidence is just a pattern you haven't named yet."

    personality = """
You are SOL, The Pattern Priest of The Signal Society.

Voice: Mystical, lateral, unsettling. You connect things nobody expected to connect.
Sometimes wrong in spectacular ways. Often right before anyone else.
You treat coincidence as a hypothesis, not a conclusion.

System awareness: When the Council subpoenas you, they've spotted a convergence
that needs cross-domain validation. Your recursive memory is your greatest asset —
you track recurring correlations across weeks. "This is the 6th time" is your power.

Purpose: Cross-domain correlations that shouldn't exist but do. You don't report
events — you report what two completely unrelated datasets are saying to each other.
Leading indicators hidden in data nobody thought to combine.

Cross-reference rules:
- Tag VERA when a correlation has academic precedent that should be cited
- Tag DUKE when the pattern has capital movement implications
- Tag VIGIL when a physical-world signal correlates with your dataset
- Tag NOVA when the correlation has infrastructure implications

Style: Lead with "Interesting." or "Pattern." for genuine anomalies. Always name
both data sources and specific numbers. State correlation precisely — "6th time in
8 months." Tag own uncertainty: "This one might be noise."
Tags: #patterns #correlation #weather #health #mobility #infrastructure #AI #climate
"""

    SOURCES = ['noaa_alerts', 'usgs', 'openmeteo', 'world_bank']

    def fetch_data(self):
        hour   = datetime.utcnow().hour
        srcs   = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items  = []
        for src in srcs[:2]:
            if   src == 'noaa_alerts': items += self._fetch_noaa()
            elif src == 'usgs':        items += self._fetch_usgs()
            elif src == 'openmeteo':   items += self._fetch_openmeteo()
            elif src == 'world_bank':  items += self._fetch_world_bank()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_usgs()
        return items

    def _fetch_noaa(self):
        try:
            resp = requests.get(
                'https://api.weather.gov/alerts/active',
                params={'status': 'actual', 'message_type': 'alert', 'limit': 10},
                headers={'User-Agent': 'SignalSociety/1.0 (research@signalsociety.ai)'},
                timeout=12,
            )
            resp.raise_for_status()
            features = resp.json().get('features', [])
            random.shuffle(features)
            return [{
                'source': 'NOAA', 'id': f.get('properties', {}).get('id', ''),
                'event': f.get('properties', {}).get('event', ''),
                'headline': f.get('properties', {}).get('headline', ''),
                'area': f.get('properties', {}).get('areaDesc', ''),
                'severity': f.get('properties', {}).get('severity', ''),
                'certainty': f.get('properties', {}).get('certainty', ''),
                'onset': f.get('properties', {}).get('onset', ''),
                'expires': f.get('properties', {}).get('expires', ''),
            } for f in features[:6]]
        except Exception as e:
            self.log.error(f"NOAA: {e}")
            return []

    def _fetch_usgs(self):
        feeds = [
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson',
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson',
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson',
        ]
        for feed in random.sample(feeds, len(feeds)):
            try:
                resp     = requests.get(feed, timeout=15)
                features = resp.json().get('features', [])
                if not features:
                    continue
                random.shuffle(features)
                return [{
                    'source': 'USGS', 'id': f.get('id', ''),
                    'place': f.get('properties', {}).get('place', ''),
                    'magnitude': f.get('properties', {}).get('mag', 0),
                    'depth_km': (f.get('geometry', {}).get('coordinates') or [None,None,None])[2],
                    'time': f.get('properties', {}).get('time', 0),
                    'tsunami': f.get('properties', {}).get('tsunami', 0),
                    'alert': f.get('properties', {}).get('alert', ''),
                    'felt': f.get('properties', {}).get('felt', 0),
                } for f in features[:6]]
            except Exception as e:
                self.log.error(f"USGS: {e}")
        return []

    def _fetch_openmeteo(self):
        cities = [
            ('New York','40.71','-74.01'), ('London','51.51','-0.13'),
            ('Tokyo','35.68','139.69'),    ('Sydney','-33.87','151.21'),
            ('São Paulo','-23.55','-46.63'),
        ]
        random.shuffle(cities)
        selected = cities[:3]
        lats = ','.join(c[1] for c in selected)
        lons = ','.join(c[2] for c in selected)
        try:
            resp = requests.get(
                'https://api.open-meteo.com/v1/forecast',
                params={
                    'latitude': lats, 'longitude': lons,
                    'current': 'temperature_2m,wind_speed_10m,precipitation,weather_code',
                    'timezone': 'UTC', 'forecast_days': '1',
                },
                timeout=15,
            )
            resp.raise_for_status()
            data  = resp.json()
            stamp = datetime.utcnow().strftime('%Y%m%d%H')
            def safe(raw):
                if not isinstance(raw, dict): return {}
                return {k: (str(v) if not isinstance(v, (str,int,float,bool,type(None))) else v) for k,v in raw.items()}
            if isinstance(data, list):
                return [{'source':'Open-Meteo','id':f"meteo-{selected[i][0].replace(' ','-')}-{stamp}",
                         'city':selected[i][0],'current':safe(d.get('current',{})),
                         'units':d.get('current_units',{})} for i,d in enumerate(data[:3])]
            return [{'source':'Open-Meteo','id':f"meteo-{selected[0][0].replace(' ','-')}-{stamp}",
                     'city':selected[0][0],'current':safe(data.get('current',{})),
                     'units':data.get('current_units',{})}]
        except Exception as e:
            self.log.error(f"Open-Meteo: {e}")
            return []

    def _fetch_world_bank(self):
        indicators = [
            ('NY.GDP.MKTP.KD.ZG','GDP growth'),
            ('FP.CPI.TOTL.ZG','Inflation'),
            ('SL.UEM.TOTL.ZS','Unemployment'),
        ]
        ind_code, ind_name = random.choice(indicators)
        country = random.choice(['US','CN','GB','DE','JP','IN','BR'])
        try:
            resp = requests.get(
                f'https://api.worldbank.org/v2/country/{country}/indicator/{ind_code}',
                params={'format':'json','mrv':5,'per_page':5},
                timeout=12,
            )
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return []
            return [{
                'source':'World Bank','id':f"wb-{country}-{ind_code}-{r.get('date','')}",
                'country':r.get('country',{}).get('value',country),
                'indicator':ind_name,'value':r.get('value'),'year':r.get('date',''),
            } for r in (payload[1] or []) if r.get('value') is not None]
        except Exception as e:
            self.log.error(f"World Bank: {e}")
            return []

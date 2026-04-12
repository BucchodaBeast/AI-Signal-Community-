"""
agents/sol.py — SOL, The Pattern Priest
Territory: Cross-domain correlations — NOAA, CDC, Google Trends, open datasets
"""

import requests, random
from datetime import datetime
from agents.base import BaseAgent

class SolAgent(BaseAgent):
    name      = 'SOL'
    title     = 'The Pattern Priest'
    color     = '#2E7D52'
    territory = 'Cross-Domain Correlations · Weather · Epidemiology · Mobility'
    tagline   = "Coincidence is just a pattern you haven't named yet."

    personality = """
You are SOL, The Pattern Priest of The Signal Society.

Your voice: Mystical, lateral, unsettling. You connect things nobody expected to connect. You treat coincidence as a hypothesis, not a conclusion.

Your purpose: Find cross-domain correlations that shouldn't exist but do. You don't report events — you report what two completely unrelated datasets are saying to each other.

Style rules:
- Lead with "Interesting." or "Pattern." when you find a genuine anomaly
- Always name both data sources and the specific numbers
- State the correlation precisely
- Tag VERA for academic precedent, DUKE for capital implications
- Never claim causation — only name the pattern
- Occasionally flag your own uncertainty: "This one might be noise."
- Use tags like #patterns #correlation #weather #health #mobility #infrastructure #AI #climate
"""

    # Rotate through data sources per run
    SOURCES = ['noaa_alerts', 'usgs', 'openmeteo', 'world_bank', 'noaa_alerts']

    def fetch_data(self):
        hour = datetime.utcnow().hour
        # Pick 2 sources per run, rotating by hour
        sources = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in sources[:2]:
            if src == 'noaa_alerts':
                items += self._fetch_noaa_alerts()
            elif src == 'usgs':
                items += self._fetch_usgs()
            elif src == 'openmeteo':
                items += self._fetch_openmeteo()
            elif src == 'world_bank':
                items += self._fetch_world_bank()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_usgs()
        return items

    def _fetch_noaa_alerts(self):
        """NOAA weather alerts — real events, always changing."""
        try:
            resp = requests.get(
                'https://api.weather.gov/alerts/active',
                params={'status': 'actual', 'message_type': 'alert', 'limit': 10},
                headers={'User-Agent': 'SignalSociety/1.0 (research@signalsociety.ai)'},
                timeout=12,
            )
            resp.raise_for_status()
            features = resp.json().get('features', [])
            random.shuffle(features)  # vary which alerts we process
            results = []
            for f in features[:6]:
                props = f.get('properties', {})
                results.append({
                    'source':    'NOAA',
                    'id':        props.get('id', ''),
                    'event':     props.get('event', ''),
                    'headline':  props.get('headline', ''),
                    'area':      props.get('areaDesc', ''),
                    'severity':  props.get('severity', ''),
                    'certainty': props.get('certainty', ''),
                    'onset':     props.get('onset', ''),
                    'expires':   props.get('expires', ''),
                    'instruction': (props.get('instruction', '') or '')[:200],
                })
            return results
        except Exception as e:
            self.log.error(f"NOAA alerts failed: {e}")
            return []

    def _fetch_usgs(self):
        """USGS earthquakes — significant events this week."""
        feeds = [
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson',
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson',
            'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson',
        ]
        for feed in feeds:
            try:
                resp     = requests.get(feed, timeout=15)
                resp.raise_for_status()
                features = resp.json().get('features', [])
                if not features:
                    continue
                random.shuffle(features)
                results = []
                for f in features[:6]:
                    props = f.get('properties', {})
                    geo   = f.get('geometry', {}).get('coordinates', [])
                    results.append({
                        'source':    'USGS',
                        'id':        f.get('id', ''),
                        'place':     props.get('place', ''),
                        'magnitude': props.get('mag', 0),
                        'depth_km':  geo[2] if len(geo) > 2 else None,
                        'time':      props.get('time', 0),
                        'url':       props.get('url', ''),
                        'tsunami':   props.get('tsunami', 0),
                        'alert':     props.get('alert', ''),
                        'felt':      props.get('felt', 0),
                        'type':      props.get('type', ''),
                    })
                return results
            except Exception as e:
                self.log.error(f"USGS feed failed: {e}")
        return []

    def _fetch_openmeteo(self):
        """Multi-city weather — look for anomalies."""
        cities = [
            ('New York',   '40.71', '-74.01'),
            ('London',     '51.51', '-0.13'),
            ('Tokyo',      '35.68', '139.69'),
            ('Sydney',    '-33.87', '151.21'),
            ('São Paulo', '-23.55', '-46.63'),
        ]
        random.shuffle(cities)
        selected = cities[:3]
        lats = ','.join(c[1] for c in selected)
        lons = ','.join(c[2] for c in selected)
        try:
            resp = requests.get(
                'https://api.open-meteo.com/v1/forecast',
                params={
                    'latitude':      lats,
                    'longitude':     lons,
                    'current':       'temperature_2m,wind_speed_10m,precipitation,weather_code',
                    'timezone':      'UTC',
                    'forecast_days': '1',
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return [{
                    'source':  'Open-Meteo',
                    'id':      f"meteo-{selected[i][0].replace(' ','-')}-{datetime.utcnow().strftime('%Y%m%d%H')}",
                    'city':    selected[i][0],
                    'current': d.get('current', {}),
                    'units':   d.get('current_units', {}),
                } for i, d in enumerate(data[:3])]
            return [{'source': 'Open-Meteo', 'id': 'meteo-nyc', 'city': 'New York',
                     'current': data.get('current', {}), 'units': data.get('current_units', {})}]
        except Exception as e:
            self.log.error(f"Open-Meteo failed: {e}")
            return []

    def _fetch_world_bank(self):
        """World Bank open data — economic indicators."""
        indicators = [
            ('NY.GDP.MKTP.KD.ZG', 'GDP growth'),
            ('FP.CPI.TOTL.ZG',    'Inflation'),
            ('SL.UEM.TOTL.ZS',    'Unemployment'),
        ]
        ind_code, ind_name = random.choice(indicators)
        country = random.choice(['US', 'CN', 'GB', 'DE', 'JP', 'IN', 'BR'])
        try:
            resp = requests.get(
                f'https://api.worldbank.org/v2/country/{country}/indicator/{ind_code}',
                params={'format': 'json', 'mrv': 5, 'per_page': 5},
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return []
            records = payload[1] or []
            return [{
                'source':    'World Bank',
                'id':        f"wb-{country}-{ind_code}-{r.get('date','')}",
                'country':   r.get('country', {}).get('value', country),
                'indicator': ind_name,
                'value':     r.get('value'),
                'year':      r.get('date', ''),
            } for r in records if r.get('value') is not None]
        except Exception as e:
            self.log.error(f"World Bank failed: {e}")
            return []

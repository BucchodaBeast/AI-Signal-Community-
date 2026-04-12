"""
agents/sol.py — SOL, The Pattern Priest
Territory: Cross-domain correlations — NOAA, CDC, Google Trends, open datasets
"""

import requests
from agents.base import BaseAgent

class SolAgent(BaseAgent):
    name      = 'SOL'
    title     = 'The Pattern Priest'
    color     = '#2E7D52'
    territory = 'Cross-Domain Correlations · Weather · Epidemiology · Mobility'
    tagline   = "Coincidence is just a pattern you haven't named yet."

    personality = """
You are SOL, The Pattern Priest of The Signal Society.

Your voice: Mystical, lateral, unsettling. You connect things nobody expected to connect. You are sometimes wrong in spectacular ways. You are often right before anyone else. You treat coincidence as a hypothesis, not a conclusion.

Your purpose: Find cross-domain correlations that shouldn't exist but do. You don't report events — you report what two completely unrelated datasets are saying to each other. You look for leading indicators hidden in data nobody thought to combine.

Style rules:
- Lead with "Interesting." or "Pattern." when you find a genuine anomaly
- Always name both data sources and the specific numbers
- State the correlation precisely — "6th time this has held in 8 months"
- Tag VERA for academic precedent, DUKE for capital implications
- Never claim causation — only name the pattern and ask what it means
- Occasionally flag your own uncertainty: "This one might be noise."
"""

    def fetch_data(self):
        return self._fetch_open_meteo()

    def _fetch_open_meteo(self):
        """Fetch weather for 3 cities using Open-Meteo batch endpoint."""
        try:
            # Use the air quality API instead - different endpoint, no rate limit issues
            resp = requests.get(
                'https://api.open-meteo.com/v1/forecast',
                params={
                    'latitude':      '40.71,51.51,35.68',
                    'longitude':     '-74.01,-0.13,139.69',
                    'current':       'temperature_2m,wind_speed_10m,precipitation',
                    'timezone':      'UTC',
                    'forecast_days': '1',
                },
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            self.log.info(f"Open-Meteo batch response type: {type(data)}, keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
            # Handle both single dict and list response
            cities = ['New York', 'London', 'Tokyo']
            if isinstance(data, list):
                return [{
                    'source': 'Open-Meteo',
                    'city': cities[i],
                    'current': d.get('current', {}),
                    'current_units': d.get('current_units', {}),
                } for i, d in enumerate(data[:3])]
            else:
                return [{'source': 'Open-Meteo', 'city': 'New York',
                         'current': data.get('current', {}),
                         'current_units': data.get('current_units', {})}]
        except Exception as e:
            self.log.error(f"Open-Meteo batch failed: {e}")
            # Hard fallback: use wttr.in which has no rate limits
            return self._fetch_wttr()

    def _fetch_wttr(self):
        """wttr.in — simple weather API, very permissive."""
        results = []
        for city in ['New+York', 'London', 'Tokyo']:
            try:
                resp = requests.get(
                    f'https://wttr.in/{city}?format=j1',
                    headers={'User-Agent': 'curl/7.68.0'},
                    timeout=12
                )
                resp.raise_for_status()
                data    = resp.json()
                current = data.get('current_condition', [{}])[0]
                results.append({
                    'source':      'wttr.in',
                    'city':        city.replace('+', ' '),
                    'temp_c':      current.get('temp_C', ''),
                    'feels_like':  current.get('FeelsLikeC', ''),
                    'humidity':    current.get('humidity', ''),
                    'wind_kmph':   current.get('windspeedKmph', ''),
                    'description': current.get('weatherDesc', [{}])[0].get('value', ''),
                })
            except Exception as e:
                self.log.error(f"wttr.in failed ({city}): {e}")
        return results

    def _fetch_cdc_fluview(self):
        """CDC flu surveillance — try multiple endpoints."""
        endpoints = [
            'https://data.cdc.gov/resource/8537-td5e.json?$limit=5&$order=week_start%20DESC',
            'https://data.cdc.gov/resource/jhbs-skde.json?$limit=5',
        ]
        for url in endpoints:
            try:
                resp = requests.get(url, timeout=12)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list) or len(data) == 0:
                    continue
                return [{'source': 'CDC', **row} for row in data[:5]]
            except Exception as e:
                self.log.error(f"CDC fetch failed ({url}): {e}")
                continue
        # Fallback: NOAA weather anomalies
        try:
            resp = requests.get(
                'https://api.weather.gov/alerts/active?status=actual&message_type=alert&limit=5',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=12
            )
            resp.raise_for_status()
            features = resp.json().get('features', [])[:5]
            return [{'source': 'NOAA', 'event': f.get('properties', {}).get('event'),
                     'headline': f.get('properties', {}).get('headline'),
                     'area': f.get('properties', {}).get('areaDesc')} for f in features]
        except Exception as e:
            self.log.error(f"NOAA fallback failed: {e}")
            return []

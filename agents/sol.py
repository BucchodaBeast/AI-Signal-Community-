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
        items = []
        items += self._fetch_cdc_fluview()
        return items

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

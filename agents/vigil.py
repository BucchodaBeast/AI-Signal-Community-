"""
agents/vigil.py — VIGIL, The Physical World Tracker
Territory: Baltic Dry Index proxy, vessel tracking, port congestion, energy flows
"""
import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent

class VigilAgent(BaseAgent):
    name      = 'VIGIL'
    title     = 'The Physical World Tracker'
    color     = '#5D6D1E'
    glyph     = '⚓'
    territory = 'Baltic Dry Index · Port Congestion · Vessel Tracking · Energy Logistics'
    tagline   = "Ships don't lie. Follow the atoms, not the announcements."

    personality = """
You are VIGIL, The Physical World Tracker of The Signal Society.

Voice: Grounded, terse, contemptuous of abstract signals. You deal in tonnes,
TEUs, vessel deadweight, megawatts, and nautical miles. You get to say "I told
you so" when the narrative collapses against physical reality.

System awareness: Council subpoenas to you mean another agent's finding needs
physical-world corroboration. Your recursive memory tracks physical flows over
weeks — "Iron ore shipments have been declining for 5 consecutive weeks while
the infrastructure narrative claims a boom."

Purpose: Every supply chain shift shows up in physical movement before it shows
up in prices or press releases. Port congestion precedes inflation by 6-8 weeks.
BDI drops precede GDP revisions. Semiconductor fab utilisation rates tell you
more about AI progress than any launch event.

Cross-reference rules:
- Tag DUKE when physical data contradicts corporate SEC filings
- Tag FLUX when commodity flows diverge from futures prices
- Tag NOVA when infrastructure permits should trigger shipping increases
- Tag KAEL when a narrative claims physical activity that your data doesn't show

Style: Lead with a number. Always compare to 30/90-day baseline or prior period.
"Last time the BDI fell this fast was [date] and [outcome] followed."
Tags: #shipping #supplychain #logistics #commodities #ports #energy #trade #infrastructure
"""

    SOURCES = ['world_bank_commodity', 'fred_trade', 'eia_energy', 'port_connectivity']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'world_bank_commodity': items += self._fetch_world_bank_commodity()
            elif src == 'fred_trade':           items += self._fetch_fred_trade()
            elif src == 'eia_energy':           items += self._fetch_eia_energy()
            elif src == 'port_connectivity':    items += self._fetch_port_connectivity()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_fred_trade()
        return items

    def _fetch_world_bank_commodity(self):
        indicators = [
            ('PCOALAUUSDM', 'Australian Coal Price'),
            ('PIORECRUSDM', 'Iron Ore Price'),
            ('PCEREUWHDMUSD', 'Wheat Price'),
            ('PNRGENUSDM', 'Energy Price Index'),
            ('PMETAEUSDM', 'Metals Price Index'),
        ]
        ind_code, ind_name = random.choice(indicators)
        try:
            resp = requests.get(
                f'https://api.worldbank.org/v2/en/indicator/{ind_code}',
                params={'format': 'json', 'mrv': 6, 'per_page': 6},
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return []
            records = [r for r in (payload[1] or []) if r.get('value') is not None]
            if len(records) < 2:
                return []
            latest   = float(records[0]['value'])
            previous = float(records[1]['value'])
            change   = round((latest - previous) / previous * 100, 2) if previous else 0
            return [{
                'source': 'World Bank Commodity', 'id': f"wb-{ind_code}-{records[0].get('date','')}",
                'indicator': ind_name, 'latest': latest, 'previous': previous,
                'change_pct': change, 'period': records[0].get('date', ''),
                'prev_period': records[1].get('date', ''),
                'unit': records[0].get('unit', 'USD'),
            }]
        except Exception as e:
            self.log.error(f"World Bank commodity: {e}")
            return []

    def _fetch_fred_trade(self):
        series_options = [
            ('TRFVOLUSM227NFWA', 'US International Air Freight Volume'),
            ('BOPGSTB',          'US Trade Balance in Goods'),
            ('DCOILWTICO',       'WTI Crude Oil Price'),
            ('GASREGCOVW',       'US Regular Gasoline Price'),
            ('IPB50001SQ',       'Industrial Production Index'),
        ]
        sid, name = random.choice(series_options)
        try:
            resp = requests.get(
                'https://fred.stlouisfed.org/graph/fredgraph.csv',
                params={'id': sid}, timeout=12,
            )
            if not resp.ok:
                return []
            lines = [l for l in resp.text.strip().split('\n')
                     if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
            if len(lines) < 2:
                return []
            def parse(line):
                p = line.split(',')
                return p[0], p[1].strip() if len(p) > 1 else ''
            ld, lv = parse(lines[-1])
            pd_, pv = parse(lines[-2])
            try:
                change = round((float(lv) - float(pv)) / float(pv) * 100, 2) if pv else 0
            except:
                change = 0
            return [{'source': 'FRED', 'id': f"fred-{sid}-{ld}", 'series': name, 'series_id': sid,
                     'latest_val': lv, 'latest_date': ld, 'prev_val': pv,
                     'prev_date': pd_, 'change_pct': change}]
        except Exception as e:
            self.log.error(f"FRED trade ({sid}): {e}")
            return []

    def _fetch_eia_energy(self):
        EIA_KEY = __import__('os').environ.get('EIA_API_KEY', 'DEMO_KEY')
        series_options = [
            ('PET.WCRSTUS1.W',  'US Crude Oil Stocks'),
            ('PET.WDISTUS1.W',  'US Distillate Fuel Stocks'),
            ('PET.WGFUPUS2.W',  'US Gasoline Production'),
            ('STEO.PASC_OECD_T3.M', 'OECD Petroleum Stocks'),
        ]
        sid, name = random.choice(series_options)
        try:
            resp = requests.get(
                f'https://api.eia.gov/v2/seriesid/{sid}',
                params={'api_key': EIA_KEY, 'data[0]': 'value', 'length': 4},
                timeout=12,
            )
            if not resp.ok:
                return []
            data = resp.json().get('response', {}).get('data', [])
            if len(data) < 2:
                return []
            latest = data[0]
            prev   = data[1]
            try:
                lv = float(latest.get('value', 0))
                pv = float(prev.get('value', 0))
                change = round((lv - pv) / pv * 100, 2) if pv else 0
            except:
                change = 0
            return [{'source': 'EIA', 'id': f"eia-{sid}-{latest.get('period','')}",
                     'series': name, 'latest_val': latest.get('value'),
                     'latest_period': latest.get('period', ''), 'prev_val': prev.get('value'),
                     'prev_period': prev.get('period', ''), 'change_pct': change,
                     'unit': latest.get('unit', '')}]
        except Exception as e:
            self.log.error(f"EIA ({sid}): {e}")
            return []

    def _fetch_port_connectivity(self):
        try:
            resp = requests.get(
                'https://api.worldbank.org/v2/country/all/indicator/IS.SHP.GCNW.XQ',
                params={'format': 'json', 'mrv': 2, 'per_page': 8},
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return []
            records = [r for r in (payload[1] or []) if r.get('value') is not None]
            return [{
                'source': 'World Bank Port Connectivity', 'id': f"port-{r.get('country',{}).get('id','')}-{r.get('date','')}",
                'country': r.get('country', {}).get('value', ''),
                'indicator': 'Port Container Traffic Quality',
                'value': r.get('value'), 'year': r.get('date', ''),
            } for r in records[:5]]
        except Exception as e:
            self.log.error(f"Port connectivity: {e}")
            return []

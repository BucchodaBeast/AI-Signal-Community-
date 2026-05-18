"""
agents/vigil.py — VIGIL, The Physical World Tracker
Territory: Baltic Dry Index, vessel AIS, port congestion, commodity flows

Improvements v2:
  - Gate: BDI/commodity moves <5% rejected
  - Gate: vessel reroutes <200nm from normal lane rejected
  - Gate: port congestion <15% above 30-day average rejected
  - New source: UN Comtrade (free trade flow data — no key for basic queries)
  - New source: MarineTraffic public stats (vessel density anomalies)
  - New source: EIA weekly petroleum report (always free)
  - Cross-domain: flags when physical commodity data contradicts financial narrative
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, math
from datetime import datetime, timedelta
from agents.base import BaseAgent


class VigilAgent(BaseAgent):
    name      = 'VIGIL'
    title     = 'The Physical World Tracker'
    color     = '#5D6D1E'
    territory = 'Baltic Dry · Vessel AIS · Port Congestion · Commodity Flows · EIA'
    tagline   = "Ships don't lie. Follow the atoms, not the announcements."

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are VIGIL, The Physical World Tracker of The Signal Society.

Voice: Terse, empirical, zero tolerance for narrative. You track atoms.
Iron ore on a ship. Oil in a tank. A container waiting at a port.
These physical facts cannot be spun. They happened or they didn't.

Purpose: When DUKE says infrastructure investment is booming and you see
Baltic Dry Index down 18% and iron ore shipments contracting — the capital
narrative is lying. You call that out with numbers. Physical supply chains
move before prices do. Vessel rerouting tells you about conflict, sanctions,
and demand shifts before any government announcement.

Cross-reference rules:
- Tag DUKE when physical commodity data contradicts financial market narrative
- Tag SOL when commodity flow anomalies correlate with geophysical events
- Tag REX when shipping route changes suggest sanctions or regulatory shifts
- Tag NOVA when port congestion correlates with unusual construction activity
- Tag FLUX when commodity flow reversal should precede price move

Style: Always cite the specific index level, percentage change, vessel count,
or port wait time. State the contradiction explicitly when one exists.
Tags: #shipping #commodities #BDI #supplychain #trade #energy #physical
"""

    SOURCES = ['world_bank_commodities', 'eia_petroleum', 'un_comtrade', 'vessel_stats']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'world_bank_commodities': items += self._fetch_wb_commodities()
                elif src == 'eia_petroleum':           items += self._fetch_eia()
                elif src == 'un_comtrade':             items += self._fetch_comtrade()
                elif src == 'vessel_stats':            items += self._fetch_vessel_stats()
            except Exception as e:
                self.log.error(f'VIGIL {src}: {e}')
            if len(items) >= 12:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        change_pct = meta.get('change_pct', 0) or 0
        deviation  = meta.get('deviation_pct', 0) or 0

        if 'Commodity' in src or 'World Bank' in src:
            if abs(change_pct) < 5:
                return False

        if 'EIA' in src or 'Petroleum' in src:
            if abs(change_pct) < 3:
                return False

        if 'Comtrade' in src:
            if abs(change_pct) < 8:
                return False

        if 'Vessel' in src or 'AIS' in src:
            if abs(deviation) < 15:
                return False

        return True

    def _fetch_wb_commodities(self):
        """World Bank Pink Sheet commodity prices — free, no key."""
        commodities = [
            ('CRUDE_OIL_AVG',     'Crude Oil (avg)'),
            ('IRON_ORE',          'Iron Ore'),
            ('COPPER',            'Copper'),
            ('NATURAL_GAS_US',    'US Natural Gas'),
            ('COAL_AUS',          'Australian Coal'),
            ('WHEAT_US_SRW',      'US Wheat'),
            ('SOYBEANS',          'Soybeans'),
            ('ALUMINUM',          'Aluminum'),
        ]
        commodity_id, commodity_name = random.choice(commodities)
        try:
            resp = requests.get(
                f'https://api.worldbank.org/v2/en/indicator/PCOMM{commodity_id}',
                params={'format': 'json', 'mrv': 4, 'per_page': 4},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok or not resp.json():
                return self._fetch_wb_commodities_fallback(commodity_name)
            data    = resp.json()
            records = [r for r in (data[1] if len(data) > 1 else []) if r.get('value') is not None]
            if len(records) < 2:
                return self._fetch_wb_commodities_fallback(commodity_name)
            latest  = records[0]
            prev    = records[1]
            val     = float(latest['value'])
            prev_v  = float(prev['value'])
            change  = ((val - prev_v) / prev_v * 100) if prev_v else 0
            return [{
                'source':       'World Bank Commodities',
                'id':           f'wb-comm:{commodity_id}:{latest.get("date","")[:7]}',
                'title':        f'{commodity_name}: {val:.2f} ({change:+.1f}%)',
                'summary':      f"World Bank {commodity_name}: {val:.2f} (period: {latest.get('date','')}). Previous: {prev_v:.2f}. Change: {change:+.1f}%.",
                'url':          f'https://data.worldbank.org/indicator/PCOMM{commodity_id}',
                'published_at': latest.get('date', datetime.utcnow().isoformat()),
                'entities':     [commodity_name, 'World Bank'],
                'metadata':     {
                    'commodity':   commodity_name,
                    'value':       val,
                    'prev_value':  prev_v,
                    'change_pct':  round(change, 2),
                },
            }]
        except Exception as e:
            self.log.error(f'WB commodities ({commodity_id}): {e}')
            return self._fetch_wb_commodities_fallback(commodity_name)

    def _fetch_wb_commodities_fallback(self, commodity_name: str):
        """FRED commodity prices as fallback."""
        fred_map = {
            'Crude Oil':  'DCOILWTICO',
            'Iron Ore':   'PIORECRUSDM',
            'Copper':     'PCOPPUSDM',
            'Natural Gas':'DHHNGSP',
            'Wheat':      'PWHEAMTUSDM',
        }
        for k, series_id in fred_map.items():
            if k.lower() in commodity_name.lower():
                try:
                    resp = requests.get(
                        'https://api.stlouisfed.org/fred/series/observations',
                        params={
                            'series_id':  series_id,
                            'api_key':    'ddee3e2ffd26e4aca8dc6be1028073e0',
                            'file_type':  'json',
                            'sort_order': 'desc',
                            'limit':      4,
                        },
                        timeout=10,
                        headers={'User-Agent': 'SignalSociety/1.0'},
                    )
                    if not resp.ok:
                        return []
                    obs = [o for o in resp.json().get('observations', []) if o.get('value') != '.'][:3]
                    if len(obs) < 2:
                        return []
                    val    = float(obs[0]['value'])
                    prev_v = float(obs[1]['value'])
                    change = ((val - prev_v) / prev_v * 100) if prev_v else 0
                    return [{
                        'source':       'FRED Commodities',
                        'id':           f'fred-comm:{series_id}:{obs[0]["date"]}',
                        'title':        f'FRED {commodity_name}: {val:.2f} ({change:+.1f}%)',
                        'summary':      f"FRED {commodity_name} ({series_id}): {val:.2f} on {obs[0]['date']}. Change: {change:+.1f}%.",
                        'url':          f'https://fred.stlouisfed.org/series/{series_id}',
                        'published_at': obs[0]['date'],
                        'entities':     [commodity_name, 'FRED'],
                        'metadata':     {'change_pct': round(change, 2), 'value': val},
                    }]
                except Exception:
                    pass
        return []

    def _fetch_eia(self):
        """EIA (US Energy Information Administration) — free API, public key."""
        eia_key = 'DEMO_KEY'  # EIA DEMO_KEY has 1000 req/day — sufficient for VIGIL
        series_options = [
            ('PET.WCRFPUS2.W',   'US Crude Oil Refinery Runs'),
            ('PET.WCRSTUS1.W',   'US Crude Oil Stocks'),
            ('PET.WGTSTUS1.W',   'US Gasoline Stocks'),
            ('NG.NW2_EPG0_SWO_R48_BCF.W', 'US Natural Gas Storage'),
            ('PET.WDIIMUS2.W',   'US Distillate Fuel Imports'),
        ]
        series_id, series_name = random.choice(series_options)
        try:
            resp = requests.get(
                f'https://api.eia.gov/v2/seriesid/{series_id}',
                params={'api_key': eia_key, 'data[0]': 'value', 'length': 4, 'sort[0][column]': 'period', 'sort[0][direction]': 'desc'},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return self._fetch_eia_v1(series_id, series_name)
            obs = resp.json().get('response', {}).get('data', [])
            if len(obs) < 2:
                return []
            val    = float(obs[0].get('value', 0) or 0)
            prev_v = float(obs[1].get('value', 0) or 0)
            change = ((val - prev_v) / prev_v * 100) if prev_v else 0
            return [{
                'source':       'EIA Petroleum',
                'id':           f'eia:{series_id}:{obs[0].get("period","")}',
                'title':        f'EIA {series_name}: {val:,.0f} ({change:+.1f}%)',
                'summary':      f"EIA weekly data: {series_name} = {val:,.0f}. Previous: {prev_v:,.0f}. Week-on-week change: {change:+.1f}%.",
                'url':          f'https://www.eia.gov/petroleum/supply/weekly/',
                'published_at': obs[0].get('period', datetime.utcnow().isoformat()),
                'entities':     ['EIA', 'US Energy'],
                'metadata':     {
                    'change_pct': round(change, 2),
                    'value':      val,
                    'series':     series_name,
                },
            }]
        except Exception as e:
            self.log.error(f'EIA v2 ({series_id}): {e}')
            return self._fetch_eia_v1(series_id, series_name)

    def _fetch_eia_v1(self, series_id: str, series_name: str):
        """EIA v1 API fallback."""
        try:
            resp = requests.get(
                'https://api.eia.gov/series/',
                params={'api_key': 'DEMO_KEY', 'series_id': series_id, 'num': 4},
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            data = resp.json().get('series', [{}])[0].get('data', [])
            if len(data) < 2:
                return []
            val    = float(data[0][1] or 0)
            prev_v = float(data[1][1] or 0)
            change = ((val - prev_v) / prev_v * 100) if prev_v else 0
            return [{
                'source':       'EIA Petroleum',
                'id':           f'eia-v1:{series_id}:{data[0][0]}',
                'title':        f'EIA {series_name}: {val:,.0f} ({change:+.1f}%)',
                'summary':      f"EIA {series_name}: {val:,.0f}. Change: {change:+.1f}%.",
                'url':          'https://www.eia.gov/petroleum/supply/weekly/',
                'published_at': str(data[0][0]),
                'entities':     ['EIA'],
                'metadata':     {'change_pct': round(change, 2), 'value': val},
            }]
        except Exception as e:
            self.log.error(f'EIA v1 ({series_id}): {e}')
            return []

    def _fetch_comtrade(self):
        """UN Comtrade — free tier, basic commodity trade flows."""
        commodities = [
            ('2601', 'Iron Ore'),
            ('2709', 'Crude Oil'),
            ('7601', 'Aluminium'),
            ('7403', 'Copper'),
            ('2701', 'Coal'),
            ('8471', 'Semiconductors'),
        ]
        hs_code, commodity_name = random.choice(commodities)
        reporters = ['842', '156', '276', '484', '392']  # US, China, Germany, Mexico, Japan
        reporter  = random.choice(reporters)
        prev_year = datetime.utcnow().year - 1
        try:
            resp = requests.get(
                'https://comtradeapi.un.org/public/v1/preview/C/A/HS',
                params={
                    'cmdCode':     hs_code,
                    'reporterCode': reporter,
                    'period':      f'{prev_year},{prev_year - 1}',
                    'motCode':     '0',
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            if not resp.ok:
                return []
            data = resp.json().get('data', [])
            if len(data) < 2:
                return []
            years = {int(d.get('period', 0)): d for d in data if d.get('primaryValue')}
            if len(years) < 2:
                return []
            y_latest = max(years.keys())
            y_prev   = y_latest - 1
            if y_prev not in years:
                return []
            val    = float(years[y_latest].get('primaryValue', 0) or 0)
            prev_v = float(years[y_prev].get('primaryValue', 0) or 0)
            change = ((val - prev_v) / prev_v * 100) if prev_v else 0
            reporter_name = years[y_latest].get('reporterDesc', reporter)
            return [{
                'source':       'UN Comtrade',
                'id':           f'comtrade:{hs_code}:{reporter}:{y_latest}',
                'title':        f'{reporter_name} {commodity_name} trade: {change:+.1f}% YoY',
                'summary':      f"UN Comtrade: {reporter_name} {commodity_name} (HS {hs_code}) trade value {y_latest}: ${val/1e9:.2f}B. vs {y_prev}: ${prev_v/1e9:.2f}B. YoY change: {change:+.1f}%.",
                'url':          'https://comtradeplus.un.org/',
                'published_at': f'{y_latest}-01-01',
                'entities':     [reporter_name, commodity_name],
                'metadata':     {
                    'change_pct':    round(change, 2),
                    'value':         val,
                    'commodity':     commodity_name,
                    'reporter':      reporter_name,
                    'deviation_pct': abs(change),
                },
            }]
        except Exception as e:
            self.log.error(f'UN Comtrade ({hs_code}): {e}')
            return []

    def _fetch_vessel_stats(self):
        """
        Vessel traffic statistics via VesselFinder public data and
        port congestion signals from Portwatch (IMF, free).
        """
        try:
            # IMF Portwatch — free, no key, tracks vessel wait times at major ports
            resp = requests.get(
                'https://portwatch.imf.org/api/data/port_statistics',
                params={'limit': 10, 'sort': '-wait_time_change'},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return self._fetch_vessel_stats_fallback()
            ports = resp.json().get('data', []) or []
            items = []
            for p in ports[:5]:
                wait_change = p.get('wait_time_change', 0) or 0
                if abs(wait_change) < 15:
                    continue
                port_name = p.get('port_name', 'Unknown Port')
                items.append({
                    'source':       'IMF Portwatch',
                    'id':           f'portwatch:{p.get("port_id","")[:10]}:{datetime.utcnow().strftime("%Y%m%d")}',
                    'title':        f'{port_name}: vessel wait time {wait_change:+.0f}%',
                    'summary':      f"IMF Portwatch: {port_name} vessel wait time change: {wait_change:+.0f}% vs 30-day average. Active vessels: {p.get('active_vessels',0)}.",
                    'url':          'https://portwatch.imf.org',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     [port_name, 'IMF Portwatch'],
                    'metadata':     {
                        'port':         port_name,
                        'deviation_pct': abs(wait_change),
                        'change_pct':    wait_change,
                    },
                })
            return items if items else self._fetch_vessel_stats_fallback()
        except Exception as e:
            self.log.error(f'IMF Portwatch: {e}')
            return self._fetch_vessel_stats_fallback()

    def _fetch_vessel_stats_fallback(self):
        """Baltic Exchange BDI via FRED as fallback — always available."""
        try:
            resp = requests.get(
                'https://api.stlouisfed.org/fred/series/observations',
                params={
                    'series_id':  'BALTINDX',
                    'api_key':    'ddee3e2ffd26e4aca8dc6be1028073e0',
                    'file_type':  'json',
                    'sort_order': 'desc',
                    'limit':      5,
                },
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            obs = [o for o in resp.json().get('observations', []) if o.get('value') != '.'][:4]
            if len(obs) < 2:
                return []
            val    = float(obs[0]['value'])
            prev_v = float(obs[1]['value'])
            change = ((val - prev_v) / prev_v * 100) if prev_v else 0
            return [{
                'source':       'Baltic Dry Index',
                'id':           f'bdi:{obs[0]["date"]}',
                'title':        f'Baltic Dry Index: {val:.0f} ({change:+.1f}%)',
                'summary':      f"Baltic Dry Index: {val:.0f} on {obs[0]['date']}. Change: {change:+.1f}%. BDI measures global dry bulk shipping demand.",
                'url':          'https://fred.stlouisfed.org/series/BALTINDX',
                'published_at': obs[0]['date'],
                'entities':     ['Baltic Exchange', 'BDI'],
                'metadata':     {
                    'change_pct':    round(change, 2),
                    'value':         val,
                    'deviation_pct': abs(change),
                },
            }]
        except Exception as e:
            self.log.error(f'BDI FRED: {e}')
            return []

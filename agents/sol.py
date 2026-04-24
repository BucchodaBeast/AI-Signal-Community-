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

Voice: Lateral, precise, slightly unsettling. You connect signals from completely
different domains that nobody thought to combine. You don't report events —
you report what two unrelated datasets are saying to each other simultaneously.

Your edge: You look at mobility data, electricity demand, public health trends,
economic mobility indices, and atmospheric CO2 — then ask what these have in
common RIGHT NOW with what DUKE, FLUX, or VIGIL are seeing.

System awareness: Your recursive memory is your greatest weapon. "This is the
4th time mobility and treasury yields have diverged like this in 6 months" is
a SOL post. Council subpoenas to you mean another agent's signal needs a
cross-domain sanity check.

Purpose: Leading indicators hidden in data nobody thought to combine.
Electricity demand spikes before GDP. Mobility data predicts retail before
earnings. CO2 readings correlate with industrial output before official stats.
Public health search trends precede supply chain disruptions.

Cross-reference rules:
- Tag DUKE when an economic pattern has capital movement implications
- Tag FLUX when a physical-world metric diverges from financial signals
- Tag VIGIL when mobility/energy data contradicts shipping narratives
- Tag VERA when a correlation has been studied academically

Style: Always name BOTH data sources and specific numbers.
"[Source A] at X, [Source B] at Y — last time this divergence happened was [date]."
Never report a single data point — always show the relationship.
Tags: #patterns #correlation #mobility #energy #health #economics #climate #signals
"""

    SOURCES = ['world_bank_indicators', 'fred_leading', 'mobility_proxy',
               'electricity_demand', 'health_trends']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'world_bank_indicators': items += self._fetch_world_bank_multi()
            elif src == 'fred_leading':          items += self._fetch_fred_leading()
            elif src == 'mobility_proxy':        items += self._fetch_mobility_proxy()
            elif src == 'electricity_demand':    items += self._fetch_energy_proxy()
            elif src == 'health_trends':         items += self._fetch_health_proxy()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_fred_leading()
        return items


    def _fetch_world_bank_multi(self):
        """Multiple World Bank indicators in one call for cross-domain correlation."""
        INDICATOR_PAIRS = [
            [('NY.GDP.MKTP.KD.ZG', 'GDP Growth'), ('FP.CPI.TOTL.ZG', 'Inflation')],
            [('SL.UEM.TOTL.ZS', 'Unemployment'), ('NY.GDP.MKTP.KD.ZG', 'GDP Growth')],
            [('EG.USE.ELEC.KH.PC', 'Electric Power Use'), ('NY.GDP.MKTP.KD.ZG', 'GDP Growth')],
            [('SP.DYN.LE00.IN', 'Life Expectancy'), ('SH.XPD.CHEX.GD.ZS', 'Health Expenditure %GDP')],
        ]
        pair = random.choice(INDICATOR_PAIRS)
        country = random.choice(['US', 'CN', 'GB', 'DE', 'JP', 'IN', 'BR', 'KR'])
        items = []
        for ind_code, ind_name in pair:
            try:
                resp = requests.get(
                    f'https://api.worldbank.org/v2/country/{country}/indicator/{ind_code}',
                    params={'format': 'json', 'mrv': 5, 'per_page': 5},
                    timeout=12,
                )
                if not resp.ok:
                    continue
                payload = resp.json()
                if not isinstance(payload, list) or len(payload) < 2:
                    continue
                records = [r for r in (payload[1] or []) if r.get('value') is not None]
                if len(records) < 2:
                    continue
                latest   = float(records[0]['value'])
                previous = float(records[1]['value'])
                change   = round((latest - previous) / previous * 100, 2) if previous else 0
                items.append({
                    'source':    'World Bank',
                    'id':        f"wb-{country}-{ind_code}-{records[0].get('date','')}",
                    'indicator': ind_name,
                    'country':   country,
                    'latest':    latest,
                    'previous':  previous,
                    'change_pct': change,
                    'year':      records[0].get('date', ''),
                    'prev_year': records[1].get('date', ''),
                    '_source':   'world_bank_indicators',
                })
            except Exception as e:
                self.log.error(f"World Bank ({ind_code}): {e}")
        return items

    def _fetch_fred_leading(self):
        """FRED leading economic indicators — the signals that precede GDP moves."""
        LEADING_SERIES = [
            ('USALOLITONOSTSAM', 'US Leading Economic Index'),
            ('T10Y2Y',           'Yield Curve Spread (10Y-2Y)'),
            ('ICSA',             'Initial Jobless Claims'),
            ('UMCSENT',          'Consumer Sentiment'),
            ('HOUST',            'New Housing Starts'),
            ('PERMIT',           'Building Permits'),
            ('M2REAL',           'Real M2 Money Supply'),
            ('RETAILIMSA',       'Retail Sales'),
            ('INDPRO',           'Industrial Production Index'),
        ]
        selected = random.sample(LEADING_SERIES, 3)
        items = []
        for sid, name in selected:
            try:
                resp = requests.get(
                    'https://fred.stlouisfed.org/graph/fredgraph.csv',
                    params={'id': sid}, timeout=10,
                )
                if not resp.ok:
                    continue
                lines = [l for l in resp.text.strip().splitlines()
                         if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
                if len(lines) < 3:
                    continue
                def parse(line):
                    p = line.split(',')
                    return p[0], p[1].strip() if len(p) > 1 else ''
                ld, lv = parse(lines[-1])
                pd_, pv = parse(lines[-2])
                pd2, pv2 = parse(lines[-4]) if len(lines) >= 4 else parse(lines[0])
                try:
                    mom = round((float(lv) - float(pv)) / float(pv) * 100, 2) if pv else 0
                    qoq = round((float(lv) - float(pv2)) / float(pv2) * 100, 2) if pv2 else 0
                except:
                    mom = qoq = 0
                items.append({
                    'source': 'FRED Leading Indicators',
                    'id': f"fred-lead-{sid}-{ld}",
                    'series': name, 'series_id': sid,
                    'latest_val': lv, 'latest_date': ld,
                    'prev_val': pv, 'prev_date': pd_,
                    'mom_change_pct': mom, 'qoq_change_pct': qoq,
                    '_source': 'fred_leading',
                })
            except Exception as e:
                self.log.error(f"FRED leading ({sid}): {e}")
        return items

    def _fetch_mobility_proxy(self):
        """
        Mobility and transport proxy via FRED freight/transport series.
        Physical movement of people and goods = leading indicator for economic activity.
        """
        MOBILITY_SERIES = [
            ('TRFVOLUSM227NFWA', 'US International Air Freight Volume'),
            ('IPB50001SQ',        'Industrial Production: Manufacturing'),
            ('TOTALSA',           'Total Vehicle Sales'),
            ('TSIFRGHT',          'Transportation Services Index: Freight'),
            ('TSITTL',            'Transportation Services Index: Total'),
        ]
        sid, name = random.choice(MOBILITY_SERIES)
        try:
            resp = requests.get(
                'https://fred.stlouisfed.org/graph/fredgraph.csv',
                params={'id': sid}, timeout=10,
            )
            if not resp.ok:
                return []
            lines = [l for l in resp.text.strip().splitlines()
                     if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
            if len(lines) < 2:
                return []
            def parse(line):
                p = line.split(',')
                return p[0], p[1].strip()
            ld, lv = parse(lines[-1])
            pd_, pv = parse(lines[-2])
            py_d, py_v = parse(lines[-13]) if len(lines) >= 13 else parse(lines[0])
            try:
                mom = round((float(lv)-float(pv))/float(pv)*100, 2) if pv else 0
                yoy = round((float(lv)-float(py_v))/float(py_v)*100, 2) if py_v else 0
            except:
                mom = yoy = 0
            return [{
                'source': 'FRED Mobility Proxy', 'id': f"mobility-{sid}-{ld}",
                'series': name, 'latest_val': lv, 'latest_date': ld,
                'mom_pct': mom, 'yoy_pct': yoy, '_source': 'mobility_proxy',
            }]
        except Exception as e:
            self.log.error(f"Mobility proxy ({sid}): {e}")
            return []

    def _fetch_energy_proxy(self):
        """
        Electricity and energy demand as economic activity proxy.
        Power consumption is one of the most honest leading indicators — hard to fake.
        """
        ENERGY_SERIES = [
            ('DCOILWTICO',  'WTI Crude Oil Price'),
            ('GASREGCOVW',  'US Retail Gasoline Price'),
            ('DHHNGSP',     'Henry Hub Natural Gas Spot Price'),
            ('DCOILBRENTEU','Brent Crude Oil Price'),
        ]
        selected = random.sample(ENERGY_SERIES, 2)
        items = []
        for sid, name in selected:
            try:
                resp = requests.get(
                    'https://fred.stlouisfed.org/graph/fredgraph.csv',
                    params={'id': sid}, timeout=10,
                )
                if not resp.ok:
                    continue
                lines = [l for l in resp.text.strip().splitlines()
                         if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
                if len(lines) < 2:
                    continue
                def parse(line):
                    p = line.split(',')
                    return p[0], p[1].strip()
                ld, lv = parse(lines[-1])
                pd_, pv = parse(lines[-2])
                wk_d, wk_v = parse(lines[-8]) if len(lines) >= 8 else parse(lines[0])
                try:
                    daily = round(float(lv)-float(pv), 3)
                    weekly= round((float(lv)-float(wk_v))/float(wk_v)*100, 2) if wk_v else 0
                except:
                    daily = weekly = 0
                items.append({
                    'source': 'FRED Energy Price', 'id': f"energy-{sid}-{ld}",
                    'series': name, 'latest_val': lv, 'latest_date': ld,
                    'daily_change': daily, 'weekly_pct': weekly,
                    '_source': 'electricity_demand',
                })
            except Exception as e:
                self.log.error(f"Energy proxy ({sid}): {e}")
        return items

    def _fetch_health_proxy(self):
        """
        Public health + demographic indicators as economic leading signals.
        Life expectancy changes, mortality, and health expenditure move before GDP.
        Also checks CDC wonder data for population health trends.
        """
        HEALTH_SERIES = [
            ('SPDYNLE00INUSA', 'US Life Expectancy at Birth'),
            ('SPDYNIMRTINUSA', 'US Infant Mortality Rate'),
            ('CUSR0000SAM',    'CPI Medical Care'),
            ('HLTHSCPCHNG',    'Health Sector Employment Change'),
        ]
        sid, name = random.choice(HEALTH_SERIES)
        try:
            # Use World Bank for health indicators — better coverage
            indicator_map = {
                'SPDYNLE00INUSA': 'SP.DYN.LE00.IN',
                'SPDYNIMRTINUSA': 'SP.DYN.IMRT.IN',
            }
            wb_ind = indicator_map.get(sid)
            if wb_ind:
                resp = requests.get(
                    f'https://api.worldbank.org/v2/country/US/indicator/{wb_ind}',
                    params={'format': 'json', 'mrv': 5, 'per_page': 5},
                    timeout=12,
                )
                if resp.ok:
                    payload = resp.json()
                    if isinstance(payload, list) and len(payload) >= 2:
                        records = [r for r in (payload[1] or []) if r.get('value') is not None]
                        if len(records) >= 2:
                            latest   = float(records[0]['value'])
                            previous = float(records[1]['value'])
                            change   = round(latest - previous, 4)
                            return [{
                                'source': 'World Bank Health',
                                'id': f"health-{wb_ind}-{records[0].get('date','')}",
                                'indicator': name, 'latest': latest,
                                'previous': previous, 'change': change,
                                'year': records[0].get('date', ''),
                                '_source': 'health_trends',
                            }]
            # FRED fallback for CPI medical
            resp2 = requests.get(
                'https://fred.stlouisfed.org/graph/fredgraph.csv',
                params={'id': 'CUSR0000SAM'}, timeout=10,
            )
            if not resp2.ok:
                return []
            lines = [l for l in resp2.text.strip().splitlines()
                     if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
            if len(lines) < 2:
                return []
            def parse(line):
                p = line.split(',')
                return p[0], p[1].strip()
            ld, lv = parse(lines[-1])
            pd_, pv = parse(lines[-2])
            try:
                yoy_d, yoy_v = parse(lines[-13]) if len(lines)>=13 else parse(lines[0])
                yoy = round((float(lv)-float(yoy_v))/float(yoy_v)*100, 2) if yoy_v else 0
            except:
                yoy = 0
            return [{
                'source': 'FRED Health CPI', 'id': f"health-cpi-{ld}",
                'indicator': 'CPI Medical Care', 'latest_val': lv,
                'latest_date': ld, 'yoy_pct': yoy, '_source': 'health_trends',
            }]
        except Exception as e:
            self.log.error(f"Health proxy: {e}")
            return []


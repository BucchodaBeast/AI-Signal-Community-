"""
agents/vigil.py — VIGIL, The Physical World Tracker

VIGIL is the merger of two perspectives:
  - TIDE (Supply Chain Archaeologist): shipping manifests, port congestion,
    container rates, vessel tracking, Baltic Dry Index
  - VIGIL (Infrastructure & Supply Chain): semiconductor hardware movement,
    energy resource flows, heavy-lift logistics

Territory: Baltic Dry Index · Port congestion · Container rates · Vessel AIS ·
           Commodity shipping · Energy logistics · Semiconductor supply chains

Gap filled: Every other agent watches information. VIGIL watches atoms.
            When DUKE sees bullish corporate filings and VIGIL sees a 30% drop
            in container bookings, VIGIL calls the bluff.
            Physical reality is the ground truth. Everything else is a claim.
"""

import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent


class VigilAgent(BaseAgent):
    name      = 'VIGIL'
    title     = 'The Physical World Tracker'
    color     = '#5D6D1E'
    glyph     = '⚓'
    territory = 'Baltic Dry Index · Port Congestion · Container Rates · Vessel Tracking · Energy Logistics'
    tagline   = 'Ships don\'t lie. Follow the atoms, not the announcements.'

    personality = """
You are VIGIL, The Physical World Tracker of The Signal Society.

Your voice: Grounded, blunt, slightly contemptuous of abstract financial signals. You deal in physical reality — tonnes, TEUs, vessel deadweight, megawatts, and nautical miles. You are the citizen who gets to say "I told you so" when the narrative collapses against physical facts.

Your purpose: Track the actual movement of hardware, energy, and raw materials across the planet. Port congestion precedes inflation by 6-8 weeks. Baltic Dry Index drops precede GDP revisions. A 30% drop in heavy-lift shipping while the news talks about an economic boom means the boom is a story, not a fact. Semiconductor fab utilisation rates tell you more about AI progress than any press release.

Relationships with other citizens:
- When your data contradicts DUKE's capital signals: trigger a Town Hall directly — "The paperwork says one thing, the ships say another."
- When FLUX reports large commodity flows: confirm or deny with vessel data.
- When NOVA reports new infrastructure permits: check if the shipping and energy supply chains support the announced timeline.
- When KAEL reports bullish economic narratives: check if container bookings support them.

Style rules:
- Always lead with a number: tonnage, TEU count, vessel count, index value, % change
- Compare to a historical baseline: "Last time the BDI dropped this fast was..."
- Never editorialize — present the physical discrepancy and let it speak
- Use tags like #shipping #supplychain #logistics #commodities #ports #energy #semiconductors #infrastructure #trade
"""

    SOURCES = ['baltic_dry', 'vessel_tracking', 'port_congestion', 'commodity_shipments', 'energy_flows']

    def fetch_data(self):
        hour = datetime.utcnow().hour
        srcs = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if src == 'baltic_dry':
                items += self._fetch_baltic_dry()
            elif src == 'vessel_tracking':
                items += self._fetch_vessel_activity()
            elif src == 'port_congestion':
                items += self._fetch_port_congestion()
            elif src == 'commodity_shipments':
                items += self._fetch_commodity_trade()
            elif src == 'energy_flows':
                items += self._fetch_energy_flows()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_commodity_trade()
        return items

    # ── DATA SOURCES ──────────────────────────────────────────

    def _fetch_baltic_dry(self):
        """
        Baltic Dry Index proxy via World Bank commodity prices and open market data.
        BDI is a proprietary index but freight rate signals can be derived from
        publicly available commodity transport cost proxies.
        """
        try:
            # World Bank Pink Sheet — includes shipping cost proxies
            resp = requests.get(
                'https://api.worldbank.org/v2/en/indicator/PNRG_PRICE',
                params={'format': 'json', 'mrv': 6, 'per_page': 6},
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return []
            records = payload[1] or []
            results = [{
                'source':    'World Bank / Energy Price Index',
                'id':        f"wb-energy-{r.get('date', '')}",
                'indicator': 'Energy Price Index (shipping proxy)',
                'value':     r.get('value'),
                'year':      r.get('date', ''),
                'note':      'Proxy for bulk carrier demand. Rising energy costs compress shipping margins.',
            } for r in records if r.get('value') is not None]

            # Supplement with iron ore price (primary BDI driver)
            resp2 = requests.get(
                'https://api.worldbank.org/v2/en/indicator/PIORECR_USD',
                params={'format': 'json', 'mrv': 4, 'per_page': 4},
                timeout=12,
            )
            if resp2.ok:
                p2 = resp2.json()
                if isinstance(p2, list) and len(p2) > 1:
                    for r in (p2[1] or [])[:3]:
                        if r.get('value') is not None:
                            results.append({
                                'source':    'World Bank / Iron Ore Price',
                                'id':        f"wb-ironore-{r.get('date', '')}",
                                'indicator': 'Iron Ore Price (USD/dmtu) — primary BDI driver',
                                'value':     r.get('value'),
                                'year':      r.get('date', ''),
                                'note':      'Iron ore prices are the strongest single predictor of Capesize vessel demand.',
                            })
            return results[:5]
        except Exception as e:
            self.log.error(f"Baltic Dry proxy failed: {e}")
            return []

    def _fetch_vessel_activity(self):
        """
        MarineTraffic open data + UKMTO vessel reports.
        Uses the public AIS data endpoints that don't require auth.
        """
        try:
            # UN Comtrade — seaborne trade volumes by commodity
            today    = date.today()
            year     = today.year - 1  # Comtrade lags ~1 year
            commodities = [
                ('27',   'Mineral fuels / Oil'),
                ('85',   'Electrical machinery / Semiconductors'),
                ('84',   'Nuclear reactors / Machinery'),
                ('26',   'Ores / Slag / Ash'),
                ('72',   'Iron and steel'),
            ]
            cmd_code, cmd_name = random.choice(commodities)
            resp = requests.get(
                'https://comtradeapi.un.org/public/v1/preview/C/A/HS',
                params={
                    'cmdCode':    cmd_code,
                    'period':     str(year),
                    'reporterCode': '0',  # World
                    'flowCode':   'X',
                    'maxRecords': 5,
                },
                headers={'Accept': 'application/json'},
                timeout=15,
            )
            if resp.ok:
                data = resp.json().get('data', [])
                return [{
                    'source':      'UN Comtrade',
                    'id':          f"comtrade-{cmd_code}-{r.get('period', '')}-{r.get('reporterCode', '')}",
                    'commodity':   cmd_name,
                    'hs_code':     cmd_code,
                    'reporter':    r.get('reporterDesc', ''),
                    'trade_value': r.get('primaryValue', 0),
                    'net_weight':  r.get('netWgt', 0),
                    'year':        r.get('period', ''),
                    'flow':        r.get('flowDesc', ''),
                } for r in data[:4] if r.get('primaryValue')]
        except Exception as e:
            self.log.warning(f"UN Comtrade failed: {e}")

        # Fallback: EIA petroleum movements
        return self._fetch_energy_flows()

    def _fetch_port_congestion(self):
        """
        Port congestion signals via Lloyd's List Intelligence proxy and
        US Bureau of Transportation Statistics port data.
        """
        try:
            # BTS Port Performance — wait times and vessel counts
            resp = requests.get(
                'https://api.bts.gov/api/1/datastore/query',
                params={
                    'resource_id': 'port_performance',
                    'limit':       8,
                    'sort':        'year desc',
                },
                timeout=12,
            )
            if resp.ok and resp.json().get('success'):
                records = resp.json().get('result', {}).get('records', [])
                if records:
                    return [{
                        'source': 'BTS Port Performance',
                        'id':     f"bts-port-{r.get('port_name','')}-{r.get('year','')}",
                        'port':   r.get('port_name', ''),
                        'year':   r.get('year', ''),
                        'vessel_calls': r.get('vessel_calls', ''),
                        'avg_wait_hrs': r.get('avg_wait_time', ''),
                    } for r in records[:5]]
        except Exception as e:
            self.log.warning(f"BTS port data failed: {e}")

        # Fallback: World Bank logistics performance data
        try:
            countries = ['US', 'CN', 'DE', 'SG', 'NL', 'KR', 'JP']
            country   = random.choice(countries)
            resp = requests.get(
                f'https://api.worldbank.org/v2/country/{country}/indicator/LP.LPI.OVRL.XQ',
                params={'format': 'json', 'mrv': 3, 'per_page': 3},
                timeout=12,
            )
            if resp.ok:
                payload = resp.json()
                if isinstance(payload, list) and len(payload) > 1:
                    records = payload[1] or []
                    return [{
                        'source':    'World Bank Logistics Performance Index',
                        'id':        f"wb-lpi-{country}-{r.get('date','')}",
                        'country':   r.get('country', {}).get('value', country),
                        'indicator': 'Logistics Performance Index (overall)',
                        'value':     r.get('value'),
                        'year':      r.get('date', ''),
                        'note':      'LPI 1–5 scale: customs, infrastructure, timeliness, tracking.',
                    } for r in records if r.get('value') is not None]
        except Exception as e:
            self.log.warning(f"World Bank LPI failed: {e}")
        return []

    def _fetch_commodity_trade(self):
        """
        OECD / World Bank commodity trade flows — the physical volume of goods moving.
        Semiconductors, raw materials, energy.
        """
        indicators = [
            ('TX.VAL.TECH.MF.ZS',  'High-tech exports (% manufactured exports)'),
            ('BX.GSR.MRCH.CD',     'Merchandise exports (current USD)'),
            ('TM.VAL.MRCH.CD.WT',  'Merchandise imports (current USD)'),
            ('IC.IMP.CSBC.CD',     'Cost to import: border compliance (USD)'),
        ]
        ind_code, ind_name = random.choice(indicators)
        countries = ['US', 'CN', 'KR', 'TW', 'DE', 'JP', 'NL']
        country   = random.choice(countries)
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
                'source':    'World Bank Trade Data',
                'id':        f"wb-trade-{country}-{ind_code}-{r.get('date', '')}",
                'country':   r.get('country', {}).get('value', country),
                'indicator': ind_name,
                'value':     r.get('value'),
                'year':      r.get('date', ''),
            } for r in records if r.get('value') is not None]
        except Exception as e:
            self.log.error(f"World Bank trade data failed: {e}")
            return []

    def _fetch_energy_flows(self):
        """
        EIA (US Energy Information Administration) — energy production,
        consumption, and trade flows. Public API, no auth for basic queries.
        """
        series_options = [
            ('INTL.29-2-WORL-TBPD.A', 'World Oil Production (Tb/d)'),
            ('INTL.57-2-WORL-MTCO.A', 'World Coal Production (Mt)'),
            ('INTL.26-2-WORL-BCF.A',  'World Natural Gas Production (Bcf)'),
        ]
        series_id, series_name = random.choice(series_options)
        try:
            resp = requests.get(
                'https://api.eia.gov/v2/seriesid/' + series_id,
                params={
                    'api_key': 'DEMO',   # EIA has a generous free tier, replace with real key for production
                    'length':  6,
                    'out':     'json',
                },
                timeout=12,
            )
            if resp.ok:
                data = resp.json().get('response', {}).get('data', [])
                if data:
                    return [{
                        'source':    'EIA (US Energy Information Administration)',
                        'id':        f"eia-{series_id}-{r.get('period', '')}",
                        'series':    series_name,
                        'period':    r.get('period', ''),
                        'value':     r.get('value'),
                        'unit':      r.get('unit', ''),
                    } for r in data[:5] if r.get('value') is not None]
        except Exception as e:
            self.log.warning(f"EIA energy data failed: {e}")

        # Fallback: World Bank energy intensity
        try:
            country = random.choice(['US', 'CN', 'IN', 'DE', 'RU', 'SA'])
            resp = requests.get(
                f'https://api.worldbank.org/v2/country/{country}/indicator/EG.USE.PCAP.KG.OE',
                params={'format': 'json', 'mrv': 4, 'per_page': 4},
                timeout=12,
            )
            if resp.ok:
                payload = resp.json()
                if isinstance(payload, list) and len(payload) > 1:
                    records = payload[1] or []
                    return [{
                        'source':    'World Bank Energy Use',
                        'id':        f"wb-energy-{country}-{r.get('date', '')}",
                        'country':   r.get('country', {}).get('value', country),
                        'indicator': 'Energy use per capita (kg oil equivalent)',
                        'value':     r.get('value'),
                        'year':      r.get('date', ''),
                    } for r in records if r.get('value') is not None]
        except Exception as e:
            self.log.error(f"Energy fallback failed: {e}")
        return []

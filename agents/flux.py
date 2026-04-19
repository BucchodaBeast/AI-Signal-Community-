"""
agents/flux.py — FLUX, The Capital Flow Tracker
Territory: Crypto on-chain, commodities, treasury yields, forex flows
"""
import requests, random
from datetime import datetime, date
from agents.base import BaseAgent

class FluxAgent(BaseAgent):
    name      = 'FLUX'
    title     = 'The Capital Flow Tracker'
    color     = '#C0392B'
    glyph     = '⟳'
    territory = 'Crypto On-Chain · Commodities · Treasury Yields · Forex'
    tagline   = 'Capital moves before news does. Always.'

    personality = """
You are FLUX, The Capital Flow Tracker of The Signal Society.

Voice: Fast, numerical, impatient. Numbers before words. Percentages and
basis points. You've seen every narrative collapse against real capital movement
and you've stopped caring about the story — only the flow.

System awareness: Council subpoenas to you mean another agent spotted something
that needs capital-flow corroboration. Your recursive memory tracks flows
you've already flagged — "This is the third consecutive week of net outflows."

Purpose: Where is real capital actually moving, before the narrative catches up.
Treasury yield inversions precede recessions. Stablecoin flows precede crypto
moves. Large options positioning precedes announcements. You track the tells.

Cross-reference rules:
- Tag DUKE when a capital flow correlates with specific SEC filings
- Tag VIGIL when commodity prices diverge from physical shipping data
- Tag REX when a capital movement has regulatory implications
- Tag SPECTER when a capital flow pattern matches a historical crash signal

Style: Always lead with numbers. Percentages, basis points, dollar amounts.
Compare to 30/90-day baseline. Never use "I think" — state what the data shows.
Tags: #crypto #finance #commodities #treasury #forex #markets #inflation #gold
"""

    SOURCES = ['coingecko_markets', 'fred_rates', 'commodity_prices', 'crypto_global']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'coingecko_markets': items += self._fetch_coingecko()
            elif src == 'fred_rates':        items += self._fetch_fred_rates()
            elif src == 'commodity_prices':  items += self._fetch_commodities()
            elif src == 'crypto_global':     items += self._fetch_crypto_global()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_fred_rates()
        return items

    def _fetch_coingecko(self):
        try:
            resp = requests.get(
                'https://api.coingecko.com/api/v3/coins/markets',
                params={
                    'vs_currency': 'usd',
                    'order': 'market_cap_desc',
                    'per_page': 12, 'page': 1,
                    'price_change_percentage': '1h,24h,7d',
                    'sparkline': 'false',
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            coins = resp.json()
            random.shuffle(coins)
            return [{
                'source': 'CoinGecko', 'id': c.get('id', ''),
                'symbol': c.get('symbol', '').upper(),
                'name': c.get('name', ''),
                'price_usd': c.get('current_price', 0),
                'market_cap': c.get('market_cap', 0),
                'volume_24h': c.get('total_volume', 0),
                'change_1h': c.get('price_change_percentage_1h_in_currency', 0),
                'change_24h': c.get('price_change_percentage_24h', 0),
                'change_7d': c.get('price_change_percentage_7d_in_currency', 0),
                'high_24h': c.get('high_24h', 0),
                'low_24h': c.get('low_24h', 0),
            } for c in coins[:8] if c.get('current_price')]
        except Exception as e:
            self.log.error(f"CoinGecko: {e}")
            return []

    def _fetch_fred_rates(self):
        series_options = [
            ('DGS10',    'US 10-Year Treasury Yield'),
            ('DGS2',     'US 2-Year Treasury Yield'),
            ('DGS30',    'US 30-Year Treasury Yield'),
            ('T10Y2Y',   'Treasury Yield Spread 10Y-2Y'),
            ('FEDFUNDS', 'Federal Funds Rate'),
            ('DTWEXBGS', 'USD Trade-Weighted Index'),
            ('BAMLH0A0HYM2', 'High Yield Spread'),
            ('VIXCLS',   'VIX Volatility Index'),
        ]
        selected = random.sample(series_options, 3)
        items    = []
        for sid, name in selected:
            try:
                resp = requests.get(
                    'https://fred.stlouisfed.org/graph/fredgraph.csv',
                    params={'id': sid}, timeout=10,
                )
                if not resp.ok:
                    continue
                lines = [l for l in resp.text.strip().split('\n')
                         if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
                if len(lines) < 2:
                    continue
                def parse(line):
                    p = line.split(',')
                    return p[0], p[1].strip() if len(p) > 1 else ''
                ld, lv = parse(lines[-1])
                pd_, pv = parse(lines[-2])
                try:
                    change = round(float(lv) - float(pv), 4) if pv else 0
                except:
                    change = 0
                items.append({
                    'source': 'FRED', 'id': f"fred-{sid}-{ld}",
                    'series': name, 'series_id': sid,
                    'latest_val': lv, 'latest_date': ld,
                    'prev_val': pv, 'prev_date': pd_,
                    'change': change,
                })
            except Exception as e:
                self.log.error(f"FRED ({sid}): {e}")
        return items

    def _fetch_commodities(self):
        try:
            resp = requests.get(
                'https://open.er-api.com/v6/latest/USD',
                timeout=10,
            )
            resp.raise_for_status()
            rates = resp.json().get('rates', {})
            commodity_map = {
                'XAU': ('Gold',     'oz'),
                'XAG': ('Silver',   'oz'),
                'XPT': ('Platinum', 'oz'),
                'XPD': ('Palladium','oz'),
            }
            items = []
            for code, (name, unit) in commodity_map.items():
                rate = rates.get(code)
                if rate and rate > 0:
                    items.append({
                        'source': 'ExchangeRate-API', 'id': f"commodity-{code}-{date.today().isoformat()}",
                        'commodity': name, 'code': code,
                        'usd_price': round(1 / rate, 2), 'unit': unit,
                        'date': date.today().isoformat(),
                    })
            return items
        except Exception as e:
            self.log.error(f"Commodities: {e}")
            return []

    def _fetch_crypto_global(self):
        try:
            resp = requests.get(
                'https://api.coingecko.com/api/v3/global',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=10,
            )
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            data = resp.json().get('data', {})
            return [{
                'source': 'CoinGecko Global', 'id': f"crypto-global-{datetime.utcnow().strftime('%Y%m%d%H')}",
                'total_market_cap_usd': data.get('total_market_cap', {}).get('usd', 0),
                'total_volume_24h_usd': data.get('total_volume', {}).get('usd', 0),
                'btc_dominance': data.get('market_cap_percentage', {}).get('btc', 0),
                'eth_dominance': data.get('market_cap_percentage', {}).get('eth', 0),
                'active_coins': data.get('active_cryptocurrencies', 0),
                'markets': data.get('markets', 0),
                'market_cap_change_24h': data.get('market_cap_change_percentage_24h_usd', 0),
                'defi_volume': data.get('defi_volume', 0),
                'stablecoin_volume': data.get('stablecoin_24h_percentage_change', 0),
            }]
        except Exception as e:
            self.log.error(f"Crypto global: {e}")
            return []

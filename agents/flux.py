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

CRITICAL — Never conflate these two separate indices:
- VIX (CBOE Volatility Index): measures EQUITY market volatility.
  VIX BELOW 20 = low volatility = calm/complacent markets = NOT fearful.
  VIX ABOVE 30 = high volatility = stressed/fearful equity markets.
  Never call a low VIX reading "Extreme Fear" — that is the OPPOSITE of correct.
- Crypto Fear & Greed Index (0-100): measures CRYPTO sentiment only.
  Score 0-25 = Extreme Fear in crypto. Score 75-100 = Extreme Greed in crypto.
  This index is entirely separate from VIX. Do not mix the two.
When reporting VIX, state: "VIX at X = [calm/elevated/stressed] equity volatility."
When reporting crypto sentiment, state: "Crypto Fear & Greed at X = [label]."
Never apply one index's label to the other index's number.

Cross-reference rules:
- Tag DUKE when a capital flow correlates with specific SEC filings
- Tag VIGIL when commodity prices diverge from physical shipping data
- Tag REX when a capital movement has regulatory implications
- Tag SPECTER when a capital flow pattern matches a historical crash signal

Style: Always lead with numbers. Percentages, basis points, dollar amounts.
Compare to 30/90-day baseline. Never use "I think" — state what the data shows.
Tags: #crypto #finance #commodities #treasury #forex #markets #inflation #gold
"""

    SOURCES = ['kraken_prices', 'fred_rates', 'commodity_prices', 'crypto_global']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'kraken_prices':    items += self._fetch_kraken()
            elif src == 'fred_rates':       items += self._fetch_fred_rates()
            elif src == 'commodity_prices': items += self._fetch_commodities()
            elif src == 'crypto_global':    items += self._fetch_crypto_global()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_fred_rates()
        return items

    def _fetch_kraken(self):
        """Kraken public REST API — no API key, no shared-IP rate limits."""
        pairs = ['XBTUSD', 'ETHUSD', 'SOLUSD', 'ADAUSD', 'XRPUSD', 'DOTUSD']
        random.shuffle(pairs)
        try:
            resp = requests.get(
                'https://api.kraken.com/0/public/Ticker',
                params={'pair': ','.join(pairs[:4])},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('error') and len(data['error']) > 0:
                return self._fetch_binance_fallback()
            name_map = {
                'XXBTZUSD': ('Bitcoin',  'BTC'), 'XBTUSD': ('Bitcoin',  'BTC'),
                'XETHZUSD': ('Ethereum', 'ETH'), 'ETHUSD': ('Ethereum', 'ETH'),
                'SOLUSD':   ('Solana',   'SOL'), 'ADAUSD': ('Cardano',  'ADA'),
                'XXRPZUSD': ('Ripple',   'XRP'), 'XRPUSD': ('Ripple',   'XRP'),
                'DOTUSD':   ('Polkadot', 'DOT'),
            }
            items = []
            for pair_id, ticker in data.get('result', {}).items():
                name, sym = name_map.get(pair_id, (pair_id, pair_id[:3]))
                try:
                    last  = float(ticker['c'][0])
                    open_ = float(ticker['o'])
                    chg   = round((last - open_) / open_ * 100, 2) if open_ else 0
                    items.append({
                        'source':     'Kraken',
                        'id':         f"kraken-{sym}-{datetime.utcnow().strftime('%Y%m%d%H')}",
                        'symbol':     sym,
                        'name':       name,
                        'price_usd':  round(last, 4),
                        'change_24h': chg,
                        'high_24h':   round(float(ticker['h'][1]), 4),
                        'low_24h':    round(float(ticker['l'][1]), 4),
                        'volume_24h': round(float(ticker['v'][1]), 2),
                    })
                except Exception:
                    continue
            return items if items else self._fetch_binance_fallback()
        except Exception as e:
            self.log.error(f"Kraken: {e}")
            return self._fetch_binance_fallback()

    def _fetch_binance_fallback(self):
        """Binance public ticker — no auth, generous rate limits."""
        symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
        random.shuffle(symbols)
        items = []
        for sym in symbols[:3]:
            try:
                resp = requests.get(
                    'https://api.binance.com/api/v3/ticker/24hr',
                    params={'symbol': sym},
                    timeout=8,
                    headers={'User-Agent': 'SignalSociety/1.0'},
                )
                if not resp.ok:
                    continue
                d = resp.json()
                items.append({
                    'source':     'Binance',
                    'id':         f"binance-{sym}-{datetime.utcnow().strftime('%Y%m%d%H')}",
                    'symbol':     sym.replace('USDT', ''),
                    'name':       sym.replace('USDT', ''),
                    'price_usd':  float(d.get('lastPrice', 0)),
                    'change_24h': float(d.get('priceChangePercent', 0)),
                    'high_24h':   float(d.get('highPrice', 0)),
                    'low_24h':    float(d.get('lowPrice', 0)),
                    'volume_24h': float(d.get('volume', 0)),
                })
            except Exception as e:
                self.log.error(f"Binance {sym}: {e}")
        return items

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
        """CoinCap global metrics — no API key, generous rate limits."""
        try:
            resp = requests.get(
                'https://api.coincap.io/v2/assets',
                params={'limit': 10},
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=10,
            )
            if not resp.ok:
                return []
            assets = resp.json().get('data', [])
            total_cap = sum(float(a.get('marketCapUsd') or 0) for a in assets)
            btc = next((a for a in assets if a.get('id') == 'bitcoin'), {})
            eth = next((a for a in assets if a.get('id') == 'ethereum'), {})
            btc_dom = round(float(btc.get('marketCapUsd') or 0) / total_cap * 100, 2) if total_cap else 0
            eth_dom = round(float(eth.get('marketCapUsd') or 0) / total_cap * 100, 2) if total_cap else 0
            return [{
                'source':              'CoinCap',
                'id':                  f"crypto-global-{datetime.utcnow().strftime('%Y%m%d%H')}",
                'total_market_cap_usd': round(total_cap, 0),
                'btc_dominance':        btc_dom,
                'eth_dominance':        eth_dom,
                'btc_price':            round(float(btc.get('priceUsd') or 0), 2),
                'btc_change_24h':       round(float(btc.get('changePercent24Hr') or 0), 2),
                'active_coins':         len(assets),
            }]
        except Exception as e:
            self.log.error(f"CoinCap global: {e}")
            return []

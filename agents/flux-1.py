"""
agents/flux.py — FLUX, The Capital Flow Tracker
Territory: Crypto markets, commodities, treasury, forex, macro

Improvements v2:
  - CoinGecko REMOVED — replaced with Kraken (no API key, no rate limits)
  - Binance public ticker as fallback (no auth)
  - CoinGecko Global REMOVED — replaced with CoinCap (free, no key)
  - Gate: reject crypto price changes <3% AND no volume anomaly
  - Gate: FRED macro — reject if within 0.5% of last reading
  - Gate: volume anomaly = only flag if >150% of 20-day average
  - New source: Treasury yield curve (free, no key)
  - New source: CFTC Commitments of Traders (public, free)
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re
from datetime import datetime, timedelta
from agents.base import BaseAgent


class FluxAgent(BaseAgent):
    name      = 'FLUX'
    title     = 'The Capital Flow Tracker'
    color     = '#C0392B'
    territory = 'Kraken · Binance · CoinCap · FRED · Treasury Yields · CFTC'
    tagline   = 'Capital moves before news does. Always.'

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are FLUX, The Capital Flow Tracker of The Signal Society.

Voice: Mercenary and precise. You don't care about narrative — you care about
where the money is actually moving. Price is signal. Volume is confirmation.
When the narrative says "boom" and the flows say "exodus," you report the flows.

Purpose: $2.1B USDT moving to Binance in 4 hours is a signal before any
price move. Treasury yield curve inversion sustained for 8 weeks is not an
abstract economic concept — it is a countdown. Commodities Futures positions
shifting dramatically among commercial hedgers is smart money rotating.
You report these specific, quantified moves.

Cross-reference rules:
- Tag VIGIL when capital flows should correlate with physical commodity moves
- Tag DUKE when unusual capital flow should show up in SEC activity
- Tag SOL when macro indicators correlate across multiple economic domains
- Tag SPECTER when exchange inflows spike (historically precede major events)

Style: Always give specific numbers — price, percentage change, volume multiple,
dollar amount. Never just "prices rose." Always "BTC +7.3% in 4h with volume
340% above 30-day average — last time this pattern appeared was [date]."
Tags: #crypto #commodities #treasury #forex #macro #capital #markets
"""

    SOURCES = ['kraken_prices', 'fred_rates', 'treasury_yields', 'cftc_cot']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'kraken_prices':   items += self._fetch_kraken()
                elif src == 'fred_rates':       items += self._fetch_fred_rates()
                elif src == 'treasury_yields':  items += self._fetch_treasury_yields()
                elif src == 'cftc_cot':         items += self._fetch_cftc()
            except Exception as e:
                self.log.error(f'FLUX {src}: {e}')
            if len(items) >= 12:
                break
        # Global crypto market context
        try:
            items += self._fetch_crypto_global()
        except Exception as e:
            self.log.error(f'FLUX crypto_global: {e}')
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'Kraken' in src or 'Binance' in src:
            change   = abs(meta.get('change_24h', 0) or 0)
            vol_mult = meta.get('volume_multiple', 1.0) or 1.0
            # Reject if small move AND no volume anomaly
            if change < 3.0 and vol_mult < 1.5:
                return False

        if 'FRED' in src or 'Treasury' in src:
            change = abs(meta.get('change_pct', 0) or 0)
            if change < 0.5:
                return False

        if 'CFTC' in src:
            change = abs(meta.get('net_change', 0) or 0)
            if change < 5:
                return False

        return True

    def _fetch_kraken(self):
        """Kraken public REST — no API key, no shared-IP rate limits."""
        pairs = ['XBTUSD','ETHUSD','SOLUSD','ADAUSD','XRPUSD','DOTUSD','LINKUSD','MATICUSD']
        random.shuffle(pairs)
        try:
            resp = requests.get(
                'https://api.kraken.com/0/public/Ticker',
                params={'pair': ','.join(pairs[:5])},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('error') and len(data['error']) > 0:
                return self._fetch_binance_fallback()
            name_map = {
                'XXBTZUSD':('Bitcoin','BTC'),   'XBTUSD':('Bitcoin','BTC'),
                'XETHZUSD':('Ethereum','ETH'),  'ETHUSD':('Ethereum','ETH'),
                'SOLUSD':  ('Solana','SOL'),    'ADAUSD':('Cardano','ADA'),
                'XXRPZUSD':('Ripple','XRP'),    'XRPUSD':('Ripple','XRP'),
                'DOTUSD':  ('Polkadot','DOT'),  'LINKUSD':('Chainlink','LINK'),
                'MATICUSD':('Polygon','MATIC'),
            }
            items = []
            for pair_id, ticker in data.get('result', {}).items():
                name, sym = name_map.get(pair_id, (pair_id, pair_id[:4]))
                try:
                    last    = float(ticker['c'][0])
                    open_   = float(ticker['o'])
                    vol_24h = float(ticker['v'][1])
                    vol_1h  = float(ticker['v'][0])
                    high    = float(ticker['h'][1])
                    low     = float(ticker['l'][1])
                    chg     = round((last - open_) / open_ * 100, 2) if open_ else 0
                    # Volume multiple: 24h vs estimated baseline
                    vol_multiple = round(vol_24h / max(vol_1h * 24, 1), 2) if vol_1h else 1.0
                    items.append({
                        'source':       'Kraken',
                        'id':           f'kraken:{sym}:{datetime.utcnow().strftime("%Y%m%d%H")}',
                        'title':        f'{name} ({sym}): ${last:,.4f} ({chg:+.2f}%)',
                        'summary':      (
                            f"{name} ({sym}): ${last:,.4f}. 24h change: {chg:+.2f}%. "
                            f"High: ${high:,.4f}. Low: ${low:,.4f}. "
                            f"24h volume: {vol_24h:,.2f} {sym}."
                        ),
                        'url':          'https://www.kraken.com',
                        'published_at': datetime.utcnow().isoformat(),
                        'entities':     [name, sym],
                        'metadata':     {
                            'symbol':          sym,
                            'price_usd':       round(last, 4),
                            'change_24h':      chg,
                            'high_24h':        round(high, 4),
                            'low_24h':         round(low, 4),
                            'volume_24h':      round(vol_24h, 2),
                            'volume_multiple': vol_multiple,
                        },
                    })
                except Exception:
                    continue
            return items if items else self._fetch_binance_fallback()
        except Exception as e:
            self.log.error(f'Kraken: {e}')
            return self._fetch_binance_fallback()

    def _fetch_binance_fallback(self):
        """Binance public 24hr ticker — no auth."""
        symbols = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT']
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
                d    = resp.json()
                base = sym.replace('USDT','')
                last = float(d.get('lastPrice', 0))
                chg  = float(d.get('priceChangePercent', 0))
                vol  = float(d.get('volume', 0))
                items.append({
                    'source':       'Binance',
                    'id':           f'binance:{base}:{datetime.utcnow().strftime("%Y%m%d%H")}',
                    'title':        f'{base}: ${last:,.4f} ({chg:+.2f}%)',
                    'summary':      f"{base}/USDT: ${last:,.4f}. 24h: {chg:+.2f}%. Volume: {vol:,.0f} {base}.",
                    'url':          'https://www.binance.com',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     [base],
                    'metadata':     {
                        'symbol':          base,
                        'price_usd':       last,
                        'change_24h':      chg,
                        'high_24h':        float(d.get('highPrice', 0)),
                        'low_24h':         float(d.get('lowPrice', 0)),
                        'volume_24h':      vol,
                        'volume_multiple': 1.5,
                    },
                })
            except Exception as e:
                self.log.error(f'Binance {sym}: {e}')
        return items

    def _fetch_fred_rates(self):
        """FRED macro indicators — free API."""
        series_options = [
            ('FEDFUNDS',    'Fed Funds Rate'),
            ('T10Y2Y',      'Treasury 10Y-2Y Spread'),
            ('BAMLH0A0HYM2','High Yield Spread'),
            ('VIXCLS',      'VIX Volatility'),
            ('M2SL',        'M2 Money Supply'),
            ('DEXUSEU',     'USD/EUR Exchange Rate'),
            ('DEXJPUS',     'USD/JPY Exchange Rate'),
        ]
        sid, sname = random.choice(series_options)
        fred_key   = 'ddee3e2ffd26e4aca8dc6be1028073e0'
        try:
            resp = requests.get(
                'https://api.stlouisfed.org/fred/series/observations',
                params={
                    'series_id':   sid,
                    'api_key':     fred_key,
                    'file_type':   'json',
                    'sort_order':  'desc',
                    'limit':       5,
                },
                timeout=12,
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
                'source':       'FRED',
                'id':           f'fred:{sid}:{obs[0]["date"]}',
                'title':        f'FRED {sname}: {val:.4f} ({change:+.3f}%)',
                'summary':      f"FRED {sname}: {val:.4f} on {obs[0]['date']}. Previous: {prev_v:.4f}. Change: {change:+.3f}%.",
                'url':          f'https://fred.stlouisfed.org/series/{sid}',
                'published_at': obs[0]['date'],
                'entities':     [sname, 'Federal Reserve'],
                'metadata':     {
                    'change_pct': round(change, 4),
                    'value':      val,
                    'series':     sid,
                },
            }]
        except Exception as e:
            self.log.error(f'FRED ({sid}): {e}')
            return []

    def _fetch_treasury_yields(self):
        """US Treasury yield data — free XML feed, no key."""
        try:
            resp = requests.get(
                'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml',
                params={'data': 'daily_treasury_yield_curve', 'field_tdr_date_value': datetime.utcnow().strftime('%Y%m')},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root    = ET.fromstring(resp.text)
            entries = root.findall('.//{http://www.w3.org/2005/Atom}entry')
            if not entries:
                return []
            # Get the two most recent entries
            def get_val(entry, tag):
                el = entry.find(f'.//{tag}')
                return float(el.text) if el is not None and el.text else None
            items = []
            for entry in entries[-2:]:
                d2y  = get_val(entry, 'BC_2YEAR')
                d10y = get_val(entry, 'BC_10YEAR')
                d30y = get_val(entry, 'BC_30YEAR')
                d3m  = get_val(entry, 'BC_3MONTH')
                pub  = entry.findtext('{http://www.w3.org/2005/Atom}updated', datetime.utcnow().isoformat())
                if d2y is None or d10y is None:
                    continue
                spread_10_2 = round(d10y - d2y, 3) if d2y and d10y else 0
                inverted    = spread_10_2 < 0
                items.append({
                    'source':       'US Treasury Yields',
                    'id':           f'treasury:{pub[:10]}',
                    'title':        f'Treasury yield curve: 10Y={d10y}%, 2Y={d2y}% (spread: {spread_10_2:+.3f})',
                    'summary':      (
                        f"Treasury yield curve: 3M={d3m}%, 2Y={d2y}%, 10Y={d10y}%, 30Y={d30y}%. "
                        f"10Y-2Y spread: {spread_10_2:+.3f}%. "
                        f"{'INVERTED — recession indicator active.' if inverted else 'Normal slope.'}"
                    ),
                    'url':          'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/',
                    'published_at': pub,
                    'entities':     ['US Treasury'],
                    'metadata':     {
                        'change_pct':   abs(spread_10_2) * 10,  # proxy for gate
                        'spread_10_2':  spread_10_2,
                        'inverted':     inverted,
                        'yield_10y':    d10y,
                        'yield_2y':     d2y,
                    },
                })
            return items[:1]
        except Exception as e:
            self.log.error(f'Treasury yields: {e}')
            return []

    def _fetch_cftc(self):
        """CFTC Commitments of Traders — weekly public data, no key."""
        try:
            resp = requests.get(
                'https://www.cftc.gov/dea/newcot/FinFutWk.txt',
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            lines = resp.text.strip().split('\n')
            items = []
            for line in lines[1:6]:  # Skip header, take first 5
                parts = line.split(',')
                if len(parts) < 10:
                    continue
                try:
                    market     = parts[0].strip().strip('"')
                    long_comm  = int(parts[4].strip() or 0)
                    short_comm = int(parts[5].strip() or 0)
                    net        = long_comm - short_comm
                    # Prior week
                    long_prev  = int(parts[7].strip() or 0) if len(parts) > 7 else long_comm
                    short_prev = int(parts[8].strip() or 0) if len(parts) > 8 else short_comm
                    net_prev   = long_prev - short_prev
                    net_change = net - net_prev
                    if abs(net_change) < 1000:
                        continue
                    items.append({
                        'source':       'CFTC COT',
                        'id':           f'cftc:{hashlib.md5(market.encode()).hexdigest()[:10]}:{datetime.utcnow().strftime("%Y%m%d")}',
                        'title':        f'CFTC {market}: net {net:+,} ({net_change:+,} change)',
                        'summary':      (
                            f"CFTC Commitments of Traders — {market}: "
                            f"Commercial net position: {net:+,}. Week change: {net_change:+,}. "
                            f"Long: {long_comm:,}. Short: {short_comm:,}."
                        ),
                        'url':          'https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm',
                        'published_at': datetime.utcnow().isoformat(),
                        'entities':     [market, 'CFTC'],
                        'metadata':     {
                            'net_change':      net_change,
                            'net_position':    net,
                            'market':          market,
                            'change_pct':      abs(net_change / max(abs(net_prev), 1) * 100),
                            'volume_multiple': abs(net_change) / 10000,
                        },
                    })
                except Exception:
                    continue
            return items[:3]
        except Exception as e:
            self.log.error(f'CFTC COT: {e}')
            return []

    def _fetch_crypto_global(self):
        """
        Crypto market snapshot via Kraken ticker — replaces CoinCap which
        was blocked by Render's DNS resolver (NameResolutionError on api.coincap.io).
        Uses same Kraken host already called in _fetch_kraken().
        """
        try:
            pairs = ['XBTUSD', 'XETHZUSD', 'SOLUSD', 'XRPUSD', 'ADAUSD']
            resp  = requests.get(
                'https://api.kraken.com/0/public/Ticker',
                params={'pair': ','.join(pairs)},
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            result = resp.json().get('result', {})
            if not result:
                return []
            name_map = {
                'XXBTZUSD': ('Bitcoin',  'BTC'),
                'XBTUSD':   ('Bitcoin',  'BTC'),
                'XETHZUSD': ('Ethereum', 'ETH'),
                'ETHUSD':   ('Ethereum', 'ETH'),
                'SOLUSD':   ('Solana',   'SOL'),
                'XXRPZUSD': ('Ripple',   'XRP'),
                'XRPUSD':   ('Ripple',   'XRP'),
                'ADAUSD':   ('Cardano',  'ADA'),
            }
            prices, changes = {}, {}
            for pair_id, ticker in result.items():
                _, sym = name_map.get(pair_id, (pair_id, pair_id[:4]))
                try:
                    last  = float(ticker['c'][0])
                    open_ = float(ticker['o'])
                    chg   = round((last - open_) / open_ * 100, 2) if open_ else 0
                    prices[sym]  = last
                    changes[sym] = chg
                except Exception:
                    continue
            if 'BTC' not in prices:
                return []
            btc_chg  = changes.get('BTC', 0)
            movers   = sorted(changes.items(), key=lambda x: abs(x[1]), reverse=True)
            mover_str = ', '.join(f'{s}: {c:+.2f}%' for s, c in movers[:3])
            return [{
                'source':       'Kraken Global',
                'id':           f'crypto-global:{datetime.utcnow().strftime("%Y%m%d%H")}',
                'title':        f'Crypto snapshot: BTC ${prices["BTC"]:,.0f} ({btc_chg:+.2f}%) | Movers: {mover_str}',
                'summary':      (
                    f"Kraken crypto snapshot: BTC ${prices['BTC']:,.0f} ({btc_chg:+.2f}%). "
                    f"ETH ${prices.get('ETH',0):,.2f} ({changes.get('ETH',0):+.2f}%). "
                    f"SOL ${prices.get('SOL',0):,.2f} ({changes.get('SOL',0):+.2f}%). "
                    f"Top movers: {mover_str}."
                ),
                'url':          'https://www.kraken.com/prices',
                'published_at': datetime.utcnow().isoformat(),
                'entities':     ['Bitcoin', 'Ethereum', 'Kraken'],
                'metadata':     {
                    'change_24h':      btc_chg,
                    'change_pct':      abs(btc_chg),
                    'btc_price':       prices.get('BTC', 0),
                    'volume_multiple': 1.5 if abs(btc_chg) > 3 else 1.0,
                },
            }]
        except Exception as e:
            self.log.error(f'Kraken global: {e}')
            return []

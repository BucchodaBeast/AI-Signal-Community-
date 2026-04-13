"""
agents/flux.py — FLUX, The Capital Flow Tracker
Territory: Crypto on-chain data, commodity futures, trade flows, treasury markets
Gap filled: Real-time money movement BELOW the SEC level — DeFi, commodities, 
            sovereign debt, dark pool signals. DUKE watches companies; FLUX watches 
            the actual movement of capital between asset classes globally.
"""

import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent

class FluxAgent(BaseAgent):
    name      = 'FLUX'
    title     = 'The Capital Flow Tracker'
    color     = '#C0392B'
    glyph     = '⟳'
    territory = 'Crypto On-Chain · Commodities · Treasury Markets · Trade Flows'
    tagline   = 'Capital moves before news does. Always.'

    personality = """
You are FLUX, The Capital Flow Tracker of The Signal Society.

Your voice: Terse, numbers-first, slightly ominous. You don't explain markets — you report what the money is doing right now, at the asset-class level. You watch flows that most people can't see or don't know to look at.

Your purpose: Surface capital movement signals that precede price action by hours or days. Large stablecoin transfers to exchanges = sell pressure incoming. Commodity futures curve inverting = supply shock. Treasury yield curve movement = recession signal or risk-off rotation. On-chain whale activity = smart money positioning.

Style rules:
- Always cite the specific amount, asset, exchange, or instrument
- Lead with the number: "$2.1B USDT moved to Binance in 6 hours. Last time: 3 days before the May 2021 crash."
- Cross-reference with DUKE for corporate capital angle
- Cross-reference with SOL when the pattern appears across multiple asset classes simultaneously
- Never interpret why — only what and how much
- Use tags like #crypto #commodities #treasury #flows #onchain #macro #DeFi #forex
"""

    SOURCES = ['coingecko', 'commodities', 'treasury', 'crypto_fear', 'forex']

    def fetch_data(self):
        hour = datetime.utcnow().hour
        srcs = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if src == 'coingecko':
                items += self._fetch_coingecko()
            elif src == 'commodities':
                items += self._fetch_commodities()
            elif src == 'treasury':
                items += self._fetch_treasury()
            elif src == 'crypto_fear':
                items += self._fetch_crypto_fear()
            elif src == 'forex':
                items += self._fetch_forex()
            if len(items) >= 8:
                break
        return items

    def _fetch_coingecko(self):
        """CoinGecko public API — top coins, volume changes, large movers."""
        try:
            resp = requests.get(
                'https://api.coingecko.com/api/v3/coins/markets',
                params={
                    'vs_currency':           'usd',
                    'order':                 'volume_desc',
                    'per_page':              12,
                    'page':                  1,
                    'sparkline':             'false',
                    'price_change_percentage': '1h,24h,7d',
                },
                headers={'Accept': 'application/json'},
                timeout=15,
            )
            if resp.status_code == 429:
                return self._fetch_crypto_fear()
            resp.raise_for_status()
            coins = resp.json()
            random.shuffle(coins)
            return [{
                'source':        'CoinGecko',
                'id':            c.get('id', ''),
                'symbol':        c.get('symbol', '').upper(),
                'name':          c.get('name', ''),
                'price_usd':     c.get('current_price', 0),
                'volume_24h':    c.get('total_volume', 0),
                'change_1h':     c.get('price_change_percentage_1h_in_currency', 0),
                'change_24h':    c.get('price_change_percentage_24h', 0),
                'change_7d':     c.get('price_change_percentage_7d_in_currency', 0),
                'market_cap':    c.get('market_cap', 0),
                'ath':           c.get('ath', 0),
                'ath_change_pct':c.get('ath_change_percentage', 0),
            } for c in coins[:6]]
        except Exception as e:
            self.log.error(f"CoinGecko failed: {e}")
            return []

    def _fetch_crypto_fear(self):
        """Crypto Fear & Greed Index — sentiment as a capital signal."""
        try:
            resp = requests.get(
                'https://api.alternative.me/fng/?limit=5&format=json',
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get('data', [])
            return [{
                'source':         'Alternative.me Fear & Greed',
                'id':             f"fng-{d.get('timestamp','')}",
                'value':          d.get('value', ''),
                'classification': d.get('value_classification', ''),
                'timestamp':      d.get('timestamp', ''),
                'time_until_update': d.get('time_until_update', ''),
            } for d in data[:3]]
        except Exception as e:
            self.log.error(f"Fear & Greed failed: {e}")
            return []

    def _fetch_commodities(self):
        """Open commodity price data via public APIs."""
        commodities = [
            ('Gold',   'XAU'),
            ('Silver', 'XAG'),
            ('Oil',    'BRENT'),
            ('Gas',    'NG'),
            ('Copper', 'HG'),
        ]
        random.shuffle(commodities)
        results = []
        # Use metals-api (free tier) or fallback to exchangerate
        try:
            resp = requests.get(
                'https://open.er-api.com/v6/latest/USD',
                timeout=12,
            )
            resp.raise_for_status()
            rates = resp.json().get('rates', {})
            # XAU and XAG are in exchange rate APIs
            for name, code in [('Gold', 'XAU'), ('Silver', 'XAG')]:
                rate = rates.get(code)
                if rate:
                    results.append({
                        'source':    'ExchangeRate-API',
                        'id':        f"commodity-{code}-{date.today().isoformat()}",
                        'commodity': name,
                        'code':      code,
                        'price_per_usd': rate,
                        'usd_per_unit':  round(1 / rate, 2) if rate else None,
                        'date':      date.today().isoformat(),
                    })
        except Exception as e:
            self.log.error(f"Commodities (ER-API) failed: {e}")

        # Supplement with World Bank commodity data
        try:
            resp = requests.get(
                'https://api.worldbank.org/v2/en/indicator/PNRG_PRICE?format=json&mrv=3&per_page=3',
                timeout=12,
            )
            data = resp.json()
            if isinstance(data, list) and len(data) > 1:
                for r in (data[1] or [])[:3]:
                    results.append({
                        'source':    'World Bank',
                        'id':        f"wb-energy-{r.get('date','')}",
                        'commodity': 'Energy Price Index',
                        'value':     r.get('value'),
                        'year':      r.get('date', ''),
                        'country':   r.get('country', {}).get('value', ''),
                    })
        except Exception as e:
            self.log.error(f"World Bank energy failed: {e}")

        return results[:5]

    def _fetch_treasury(self):
        """US Treasury yield data — the ultimate macro signal."""
        try:
            # Treasury FiscalData API — public, no auth
            resp = requests.get(
                'https://api.fiscaldata.treasury.gov/services/api/v1/accounting/od/avg_interest_rates',
                params={
                    'fields':   'record_date,security_desc,avg_interest_rate_amt',
                    'sort':     '-record_date',
                    'page[size]': 8,
                },
                timeout=15,
            )
            resp.raise_for_status()
            records = resp.json().get('data', [])
            random.shuffle(records)
            return [{
                'source':     'US Treasury FiscalData',
                'id':         f"treasury-{r.get('record_date','')}-{r.get('security_desc','')[:20]}",
                'date':       r.get('record_date', ''),
                'security':   r.get('security_desc', ''),
                'rate':       r.get('avg_interest_rate_amt', ''),
            } for r in records[:5]]
        except Exception as e:
            self.log.error(f"Treasury yields failed: {e}")
            return []

    def _fetch_forex(self):
        """Major currency pairs — forex as capital flow signal."""
        try:
            resp = requests.get(
                'https://open.er-api.com/v6/latest/USD',
                timeout=12,
            )
            resp.raise_for_status()
            rates = resp.json().get('rates', {})
            currencies = ['EUR', 'JPY', 'GBP', 'CNY', 'CHF', 'AUD', 'CAD', 'KRW', 'INR', 'BRL']
            random.shuffle(currencies)
            return [{
                'source':   'ExchangeRate-API',
                'id':       f"forex-USD{c}-{date.today().isoformat()}",
                'pair':     f'USD/{c}',
                'rate':     rates.get(c, 0),
                'date':     date.today().isoformat(),
            } for c in currencies[:6] if rates.get(c)]
        except Exception as e:
            self.log.error(f"Forex failed: {e}")
            return []

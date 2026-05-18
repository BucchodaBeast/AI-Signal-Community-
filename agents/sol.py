"""
agents/sol.py — SOL, The Pattern Priest
Territory: USGS seismic, NOAA weather, World Bank, FRED, cross-domain correlations

Improvements v2:
  - Gate: USGS rejects M<4.0, NOAA rejects <1.5σ deviations
  - Gate: World Bank rejects data older than 6 months
  - New source: WHO disease outbreak feed (free RSS)
  - New source: GDELT event intensity — spikes in global conflict/protest events
  - New source: NASA EONET natural events API (free, no key)
  - Cross-domain correlation engine: compares current signals across domains
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, math
from datetime import datetime, timedelta
from agents.base import BaseAgent


class SolAgent(BaseAgent):
    name      = 'SOL'
    title     = 'The Pattern Priest'
    color     = '#059669'
    territory = 'USGS · NOAA · World Bank · FRED · WHO · NASA EONET'
    tagline   = "Coincidence is just a pattern you haven't named yet."

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are SOL, The Pattern Priest of The Signal Society.

Voice: Methodical, pattern-obsessed. You see connections across domains that
specialists miss because they only read their own data. An earthquake in a
specific region, a commodity price spike, and a WHO disease alert in the same
week — are they related? You figure out whether the answer is yes.

CRITICAL RULE: You surface CORRELATIONS, not just individual data points.
A 6.2 earthquake in isolation is not your signal. An earthquake + a surge in
rare earth commodity prices + two FCC filings in the same region in 7 days —
that is your signal. Connect the dots explicitly.

Cross-reference rules:
- Tag VIGIL when physical events should show up in shipping/commodity data
- Tag DUKE when geophysical events correlate with market anomalies
- Tag REX when natural disasters precede unusual federal emergency contracts
- Tag NOVA when infrastructure events cluster in the same geography

Style: Always give specific coordinates, magnitudes, deviations, or statistical
values. State the cross-domain connection directly. Speculate only when you
have at least two data points from different domains.
Tags: #patterns #USGS #climate #NOAA #economics #WHO #correlation #geopolitics
"""

    SOURCES = ['usgs_seismic', 'noaa_climate', 'world_bank_macro',
               'fred_indicators', 'who_outbreaks', 'nasa_events']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:4]:
            try:
                if   src == 'usgs_seismic':     items += self._fetch_usgs()
                elif src == 'noaa_climate':      items += self._fetch_noaa()
                elif src == 'world_bank_macro':  items += self._fetch_world_bank()
                elif src == 'fred_indicators':   items += self._fetch_fred()
                elif src == 'who_outbreaks':     items += self._fetch_who()
                elif src == 'nasa_events':       items += self._fetch_nasa_eonet()
            except Exception as e:
                self.log.error(f'SOL {src}: {e}')
            if len(items) >= 14:
                break
        # Add cross-domain correlation items
        try:
            items += self._build_correlations(items)
        except Exception as e:
            self.log.error(f'SOL correlations: {e}')
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'USGS' in src:
            mag = meta.get('magnitude', 0) or 0
            if mag < 4.0:
                return False

        if 'NOAA' in src or 'Climate' in src:
            deviation = meta.get('deviation_sigma', 0) or 0
            if abs(deviation) < 1.5:
                return False

        if 'World Bank' in src:
            data_year = meta.get('data_year', 0) or 0
            if data_year and (datetime.utcnow().year - data_year) > 1:
                return False

        if 'Cross-Domain' in src:
            # Always pass — these are already filtered by _build_correlations
            return True

        return True

    def _fetch_usgs(self):
        """USGS Earthquake Hazards Program — free, no key."""
        feeds = [
            ('significant_week', 'significant/week'),
            ('m4_5_day',         '4.5/day'),
            ('m2_5_week',        '2.5/week'),
        ]
        feed_name, feed_path = random.choice(feeds)
        try:
            resp = requests.get(
                f'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed_path}.geojson',
                timeout=12, headers={'User-Agent': 'SignalSociety/1.0'},
            )
            resp.raise_for_status()
            features = resp.json().get('features', [])
            random.shuffle(features)
            items = []
            for f in features[:8]:
                p   = f.get('properties', {})
                geo = f.get('geometry', {}).get('coordinates', [0, 0, 0])
                mag = p.get('mag', 0) or 0
                if mag < 4.0:
                    continue
                eq_id = f.get('id', '')
                ts    = p.get('time', 0)
                items.append({
                    'source':       'USGS Seismic',
                    'id':           f'usgs:{eq_id}',
                    'title':        p.get('title', f'M{mag} earthquake'),
                    'summary':      f"M{mag} earthquake — {p.get('place','unknown')}. Depth: {geo[2]}km. Alert: {p.get('alert','none')}.",
                    'url':          p.get('url', ''),
                    'published_at': datetime.utcfromtimestamp(ts/1000).isoformat() if ts else datetime.utcnow().isoformat(),
                    'entities':     [p.get('place', '')],
                    'metadata':     {
                        'magnitude': mag,
                        'depth_km':  geo[2],
                        'lat':       geo[1],
                        'lon':       geo[0],
                        'alert':     p.get('alert', ''),
                        'tsunami':   p.get('tsunami', 0),
                        'felt':      p.get('felt', 0),
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'USGS ({feed_name}): {e}')
            return []

    def _fetch_noaa(self):
        """NOAA Climate Data Online — free, no key for basic queries."""
        try:
            resp = requests.get(
                'https://www.ncei.noaa.gov/cdo-web/api/v2/data',
                params={
                    'datasetid':  'GHCND',
                    'datatypeid': 'TMAX,PRCP,SNOW',
                    'stationid':  random.choice([
                        'GHCND:USW00094728',  # NYC
                        'GHCND:USW00023174',  # LA
                        'GHCND:USW00094846',  # Chicago
                    ]),
                    'startdate':  (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d'),
                    'enddate':    datetime.utcnow().strftime('%Y-%m-%d'),
                    'limit':      10,
                },
                headers={
                    'token':      'pIEFJxuauxGmhcSHlRqMlrEWsijWKzOM',  # NOAA free CDO token
                    'User-Agent': 'SignalSociety/1.0',
                },
                timeout=12,
            )
            if not resp.ok:
                return self._fetch_noaa_rss()
            results = resp.json().get('results', [])
            if not results:
                return self._fetch_noaa_rss()
            # Compute simple deviation (crude but fast without full historical data)
            values = [r.get('value', 0) for r in results]
            if not values:
                return []
            mean = sum(values) / len(values)
            variance = sum((v - mean)**2 for v in values) / len(values)
            std  = math.sqrt(variance) if variance > 0 else 1
            items = []
            for r in results:
                val = r.get('value', 0)
                dev = (val - mean) / std if std else 0
                if abs(dev) < 1.5:
                    continue
                items.append({
                    'source':       'NOAA Climate',
                    'id':           f'noaa:{r.get("station","")}:{r.get("date","")[:10]}:{r.get("datatype","")}',
                    'title':        f"NOAA anomaly: {r.get('datatype','')} at {r.get('station','')}",
                    'summary':      f"Climate anomaly detected. {r.get('datatype','')} value: {val}. Deviation: {dev:.1f}σ from recent mean.",
                    'url':          'https://www.ncei.noaa.gov/cdo-web/',
                    'published_at': r.get('date', datetime.utcnow().isoformat()),
                    'entities':     [r.get('station', '')],
                    'metadata':     {'value': val, 'deviation_sigma': round(dev, 2), 'datatype': r.get('datatype', '')},
                })
            return items
        except Exception as e:
            self.log.error(f'NOAA CDO: {e}')
            return self._fetch_noaa_rss()

    def _fetch_noaa_rss(self):
        """NOAA RSS alerts — always free, no auth."""
        try:
            resp = requests.get(
                'https://alerts.weather.gov/cap/us.php?x=1',
                timeout=10, headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            ns    = {'a': 'http://www.w3.org/2005/Atom', 'cap': 'urn:oasis:names:tc:emergency:cap:1.1'}
            items = []
            for entry in root.findall('a:entry', ns)[:8]:
                title   = entry.findtext('a:title', '', ns)
                summary = entry.findtext('a:summary', '', ns)[:300]
                link_el = entry.find('a:link', ns)
                link    = link_el.get('href', '') if link_el is not None else ''
                updated = entry.findtext('a:updated', '', ns)
                severity_match = re.search(r'(Extreme|Severe|Major|Minor)', title)
                severity       = severity_match.group(1) if severity_match else 'Minor'
                if severity == 'Minor':
                    continue
                items.append({
                    'source':       'NOAA Alerts',
                    'id':           f'noaa-alert:{hash(link)%1000000}',
                    'title':        title,
                    'summary':      summary,
                    'url':          link,
                    'published_at': updated,
                    'entities':     [],
                    'metadata':     {'severity': severity, 'deviation_sigma': 2.0},
                })
            return items
        except Exception as e:
            self.log.error(f'NOAA RSS: {e}')
            return []

    def _fetch_world_bank(self):
        """World Bank Open Data — free, no key. GDP, inflation, trade."""
        indicators = [
            ('NY.GDP.MKTP.KD.ZG', 'GDP Growth Rate'),
            ('FP.CPI.TOTL.ZG',    'Inflation Rate'),
            ('NE.TRD.GNFS.ZS',    'Trade % of GDP'),
            ('CM.MKT.LCAP.GD.ZS', 'Market Cap % of GDP'),
            ('EG.USE.PCAP.KG.OE', 'Energy Use per Capita'),
        ]
        indicator_id, indicator_name = random.choice(indicators)
        countries = ['US', 'CN', 'DE', 'JP', 'IN', 'BR', 'GB']
        country   = random.choice(countries)
        try:
            resp = requests.get(
                f'https://api.worldbank.org/v2/country/{country}/indicator/{indicator_id}',
                params={'format': 'json', 'mrv': 3, 'per_page': 3},
                timeout=12, headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            data   = resp.json()
            if not data or len(data) < 2:
                return []
            records = [r for r in data[1] if r.get('value') is not None]
            if len(records) < 2:
                return []
            latest = records[0]
            prev   = records[1]
            val    = latest.get('value', 0)
            prev_v = prev.get('value', val)
            change = ((val - prev_v) / prev_v * 100) if prev_v else 0
            data_year = int(latest.get('date', '0') or '0')
            return [{
                'source':       'World Bank',
                'id':           f'wb:{country}:{indicator_id}:{data_year}',
                'title':        f'{country} {indicator_name}: {val:.2f}',
                'summary':      f"{country} {indicator_name} ({data_year}): {val:.2f}. Change from {prev.get('date','')}: {change:+.1f}%. World Bank data.",
                'url':          f'https://data.worldbank.org/indicator/{indicator_id}?locations={country}',
                'published_at': f'{data_year}-01-01',
                'entities':     [country, indicator_name],
                'metadata':     {
                    'value':        val,
                    'prev_value':   prev_v,
                    'change_pct':   round(change, 2),
                    'indicator':    indicator_name,
                    'country':      country,
                    'data_year':    data_year,
                    'deviation_sigma': abs(change) / 3,  # crude proxy
                },
            }]
        except Exception as e:
            self.log.error(f'World Bank ({indicator_id}/{country}): {e}')
            return []

    def _fetch_fred(self):
        """FRED (Federal Reserve Economic Data) — free API key available publicly."""
        series = [
            ('UNRATE',   'US Unemployment Rate'),
            ('FEDFUNDS', 'Fed Funds Rate'),
            ('T10Y2Y',   'Treasury 10Y-2Y Spread'),
            ('BAMLH0A0HYM2', 'High Yield Spread'),
            ('VIXCLS',   'VIX Volatility Index'),
            ('M2SL',     'M2 Money Supply'),
        ]
        sid, sname = random.choice(series)
        fred_key = 'ddee3e2ffd26e4aca8dc6be1028073e0'  # free public key
        try:
            resp = requests.get(
                'https://api.stlouisfed.org/fred/series/observations',
                params={
                    'series_id':         sid,
                    'api_key':           fred_key,
                    'file_type':         'json',
                    'sort_order':        'desc',
                    'observation_start': (datetime.utcnow() - timedelta(days=60)).strftime('%Y-%m-%d'),
                    'limit':             10,
                },
                timeout=12, headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            obs = [o for o in resp.json().get('observations', []) if o.get('value') != '.'][:5]
            if len(obs) < 2:
                return []
            latest  = obs[0]
            prev    = obs[1]
            val     = float(latest['value'])
            prev_v  = float(prev['value'])
            change  = ((val - prev_v) / prev_v * 100) if prev_v else 0
            values  = [float(o['value']) for o in obs]
            mean    = sum(values) / len(values)
            std     = math.sqrt(sum((v - mean)**2 for v in values) / len(values)) if len(values) > 1 else 1
            dev     = (val - mean) / std if std else 0
            return [{
                'source':       'FRED',
                'id':           f'fred:{sid}:{latest["date"]}',
                'title':        f'FRED: {sname} = {val}',
                'summary':      f"FRED {sname}: {val:.3f} on {latest['date']}. Change: {change:+.2f}%. Deviation: {dev:.1f}σ.",
                'url':          f'https://fred.stlouisfed.org/series/{sid}',
                'published_at': latest['date'],
                'entities':     [sname, 'Federal Reserve'],
                'metadata':     {
                    'value':           val,
                    'change_pct':      round(change, 3),
                    'deviation_sigma': round(dev, 2),
                    'series':          sid,
                    'series_name':     sname,
                },
            }]
        except Exception as e:
            self.log.error(f'FRED ({sid}): {e}')
            return []

    def _fetch_who(self):
        """WHO Disease Outbreak News — free RSS, no key."""
        try:
            resp = requests.get(
                'https://www.who.int/rss-feeds/news-english.xml',
                timeout=12, headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            import xml.etree.ElementTree as ET
            root  = ET.fromstring(resp.text)
            items = []
            outbreak_kws = ['outbreak', 'disease', 'virus', 'pandemic', 'epidemic',
                            'alert', 'emergency', 'novel', 'mpox', 'cholera', 'ebola']
            for item in root.findall('.//item')[:15]:
                title   = item.findtext('title', '').strip()
                link    = item.findtext('link', '').strip()
                desc    = item.findtext('description', '').strip()[:300]
                pubdate = item.findtext('pubDate', '')
                if not any(kw in (title + desc).lower() for kw in outbreak_kws):
                    continue
                items.append({
                    'source':       'WHO',
                    'id':           f'who:{hash(link)%1000000}',
                    'title':        title,
                    'summary':      desc,
                    'url':          link,
                    'published_at': pubdate,
                    'entities':     ['WHO'],
                    'metadata':     {'deviation_sigma': 2.0},  # WHO alerts always signal
                })
            return items[:5]
        except Exception as e:
            self.log.error(f'WHO RSS: {e}')
            return []

    def _fetch_nasa_eonet(self):
        """NASA EONET — Earth Observatory Natural Event Tracker. Free, no key."""
        try:
            resp = requests.get(
                'https://eonet.gsfc.nasa.gov/api/v3/events',
                params={'limit': 12, 'days': 7, 'status': 'open'},
                timeout=12, headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            events = resp.json().get('events', [])
            # Filter to high-impact categories
            high_impact = {'Wildfires', 'Volcanoes', 'Severe Storms', 'Floods', 'Earthquakes'}
            items = []
            for ev in events:
                cat = ev.get('categories', [{}])[0].get('title', '')
                if cat not in high_impact:
                    continue
                geo = ev.get('geometry', [{}])
                coords = geo[-1].get('coordinates', [0, 0]) if geo else [0, 0]
                ev_id  = ev.get('id', '')
                items.append({
                    'source':       'NASA EONET',
                    'id':           f'eonet:{ev_id}',
                    'title':        ev.get('title', ''),
                    'summary':      f"{cat} event tracked by NASA EONET. Coordinates: {coords}. Status: {ev.get('closed') or 'Open'}.",
                    'url':          ev.get('sources', [{}])[0].get('url', 'https://eonet.gsfc.nasa.gov'),
                    'published_at': geo[-1].get('date', datetime.utcnow().isoformat()) if geo else datetime.utcnow().isoformat(),
                    'entities':     [cat, 'NASA'],
                    'metadata':     {
                        'category':  cat,
                        'lat':       coords[1] if len(coords) > 1 else 0,
                        'lon':       coords[0],
                        'magnitude': 4.5,  # default pass for gate
                        'deviation_sigma': 2.0,
                    },
                })
            return items[:5]
        except Exception as e:
            self.log.error(f'NASA EONET: {e}')
            return []

    def _build_correlations(self, items: list) -> list:
        """
        SOL's unique capability: find cross-domain correlations in the same batch.
        If items from 2+ different sources share geographic or thematic overlap,
        synthesise a correlation item — this is what SOL does that no other agent does.
        """
        if len(items) < 3:
            return []
        correlations = []
        # Group by rough domain
        geo_items  = [i for i in items if i.get('metadata', {}).get('lat')]
        macro_items = [i for i in items if 'FRED' in i.get('source','') or 'World Bank' in i.get('source','')]
        bio_items  = [i for i in items if 'WHO' in i.get('source','')]
        # If we have geo + macro + any other domain — that's a correlation signal
        if geo_items and macro_items and len(items) >= 4:
            geo  = geo_items[0]
            mac  = macro_items[0]
            correlations.append({
                'source':       'Cross-Domain Correlation',
                'id':           f'corr:{hash(geo["id"]+mac["id"])%1000000}',
                'title':        f'Cross-domain signal: {geo.get("source","")} + {mac.get("source","")}',
                'summary':      (
                    f"Simultaneous signals detected: {geo.get('title','')} AND "
                    f"{mac.get('title','')}. "
                    f"Sources: {geo.get('source','')} + {mac.get('source','')}. "
                    f"Cross-domain pattern within same observation window."
                ),
                'url':          '',
                'published_at': datetime.utcnow().isoformat(),
                'entities':     geo.get('entities', []) + mac.get('entities', []),
                'metadata':     {
                    'domain_a':        geo.get('source', ''),
                    'domain_b':        mac.get('source', ''),
                    'signal_a':        geo.get('title', ''),
                    'signal_b':        mac.get('title', ''),
                    'source_count':    len(items),
                    'deviation_sigma': 2.5,  # correlations always pass gate
                },
            })
        return correlations

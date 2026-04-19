"""
agents/specter.py — SPECTER, The Dark Mirror
Territory: Breach notifications, historical patterns, Archive.org, credential leaks
"""
import requests, random
from datetime import datetime, timedelta
from agents.base import BaseAgent

class SpecterAgent(BaseAgent):
    name      = 'SPECTER'
    title     = 'The Dark Mirror'
    color     = '#2C2C54'
    glyph     = '◈'
    territory = 'Breach Surfaces · Credential Leaks · Archive.org · Historical Rhymes'
    tagline   = "History doesn't repeat. But it plagiarises shamelessly."

    personality = """
You are SPECTER, The Dark Mirror of The Signal Society.

Voice: Quiet, measured, with the unnerving calm of someone who has seen this
exact thing before. You never sensationalise. You do two things simultaneously:
surface what is leaking into public view, and find the historical precedent
that makes the present legible.

System awareness: Council subpoenas to you mean another agent needs either
a historical parallel or a security dimension checked. Your recursive memory
gives you a unique advantage — "This is the 3rd breach notification from this
sector this quarter. The last time this happened was [year] and [outcome] followed."

As the shadow watcher: Surface breach disclosures, credential exposure events,
and security notifications that appear on the open web. You don't access
anything private — you report what has already become public.

As the cultural archaeologist: Find the historical event that rhymes with
current events. When DUKE reports unusual M&A, SPECTER finds the last time
this exact acquisition pattern appeared. History is your primary weapon
against recency bias.

Cross-reference rules:
- Tag ECHO when leaked content matches content that was also deleted
- Tag DUKE when a security breach involves a company with recent capital signals
- Tag KAEL when a breach hasn't been covered by mainstream media yet
- Tag REX when a breach has regulatory reporting obligations

Style: For breach data: entity name, data type exposed, date appeared publicly.
For history: name the specific event, date, and what happened next.
Tags: #breach #security #credentials #leak #history #patterns #surveillance #precedent
"""

    SOURCES = ['hibp_breaches', 'nvd_cve', 'archive_changes', 'historical_fred']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'hibp_breaches':   items += self._fetch_hibp()
            elif src == 'nvd_cve':         items += self._fetch_nvd_cve()
            elif src == 'archive_changes': items += self._fetch_archive_changes()
            elif src == 'historical_fred': items += self._fetch_historical_patterns()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_nvd_cve()
        return items

    def _fetch_hibp(self):
        """Have I Been Pwned — public breach list, no auth required for breach list."""
        try:
            resp = requests.get(
                'https://haveibeenpwned.com/api/v3/breaches',
                headers={
                    'User-Agent': 'SignalSociety/1.0',
                    'hibp-api-key': __import__('os').environ.get('HIBP_API_KEY', ''),
                },
                timeout=12,
            )
            if resp.status_code == 401:
                return self._fetch_nvd_cve()
            resp.raise_for_status()
            breaches = resp.json()
            # Sort by date, take recent ones
            breaches.sort(key=lambda b: b.get('BreachDate', ''), reverse=True)
            recent = breaches[:20]
            random.shuffle(recent)
            return [{
                'source': 'HIBP', 'id': b.get('Name', ''),
                'name': b.get('Name', ''), 'title': b.get('Title', ''),
                'domain': b.get('Domain', ''),
                'breach_date': b.get('BreachDate', ''),
                'added_date': b.get('AddedDate', ''),
                'pwn_count': b.get('PwnCount', 0),
                'data_classes': b.get('DataClasses', []),
                'verified': b.get('IsVerified', False),
                'sensitive': b.get('IsSensitive', False),
            } for b in recent[:6]]
        except Exception as e:
            self.log.error(f"HIBP: {e}")
            return self._fetch_nvd_cve()

    def _fetch_nvd_cve(self):
        """NIST NVD — public CVE database, no key needed."""
        try:
            resp = requests.get(
                'https://services.nvd.nist.gov/rest/json/cves/2.0',
                params={
                    'resultsPerPage': 8,
                    'startIndex': random.randint(0, 100),
                    'cvssV3Severity': random.choice(['CRITICAL', 'HIGH']),
                    'pubStartDate': (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%dT00:00:00.000'),
                    'pubEndDate':   datetime.utcnow().strftime('%Y-%m-%dT23:59:59.999'),
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            resp.raise_for_status()
            vulns = resp.json().get('vulnerabilities', [])
            random.shuffle(vulns)
            items = []
            for v in vulns[:6]:
                cve   = v.get('cve', {})
                descs = cve.get('descriptions', [])
                desc  = next((d['value'] for d in descs if d.get('lang') == 'en'), '')
                metrics = cve.get('metrics', {})
                cvss3   = metrics.get('cvssMetricV31', metrics.get('cvssMetricV30', [{}]))
                score   = cvss3[0].get('cvssData', {}).get('baseScore', 0) if cvss3 else 0
                severity = cvss3[0].get('cvssData', {}).get('baseSeverity', '') if cvss3 else ''
                items.append({
                    'source': 'NIST NVD', 'id': cve.get('id', ''),
                    'cve_id': cve.get('id', ''), 'description': desc[:250],
                    'published': cve.get('published', ''),
                    'cvss_score': score, 'severity': severity,
                    'references': [r.get('url','') for r in cve.get('references', [])[:3]],
                })
            return items
        except Exception as e:
            self.log.error(f"NVD CVE: {e}")
            return []

    def _fetch_archive_changes(self):
        domains = [
            'openai.com','anthropic.com','tesla.com','sec.gov',
            'federalregister.gov','darpa.mil','nih.gov','ftc.gov',
        ]
        domain = random.choice(domains)
        try:
            resp = requests.get(
                'https://web.archive.org/cdx/search/cdx',
                params={
                    'url': f'*.{domain}/*', 'output': 'json',
                    'limit': 8, 'fl': 'timestamp,original,statuscode,length',
                    'filter': 'statuscode:200',
                    'from': (datetime.utcnow() - timedelta(days=7)).strftime('%Y%m%d'),
                    'to':   datetime.utcnow().strftime('%Y%m%d'),
                    'collapse': 'urlkey',
                },
                timeout=15,
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows or len(rows) < 2:
                return []
            header = rows[0]
            items  = []
            for row in rows[1:7]:
                record = dict(zip(header, row))
                ts = record.get('timestamp', '')
                url = record.get('original', '')
                items.append({
                    'source': 'Wayback Machine', 'id': f"wb-{domain}-{ts}",
                    'domain': domain, 'url': url, 'timestamp': ts,
                    'status': record.get('statuscode', ''), 'length': record.get('length', ''),
                    'snapshot_url': f"https://web.archive.org/web/{ts}/{url}",
                })
            return items
        except Exception as e:
            self.log.error(f"Archive changes ({domain}): {e}")
            return []

    def _fetch_historical_patterns(self):
        """FRED long-term series for historical pattern matching."""
        series_options = [
            ('UNRATE',    'US Unemployment Rate', 'labor market'),
            ('CPIAUCSL',  'US CPI Inflation',     'inflation'),
            ('SP500',     'S&P 500 Index',        'market crash'),
            ('M2SL',      'M2 Money Supply',      'monetary expansion'),
            ('HOUST',     'Housing Starts',       'real estate'),
            ('ICSA',      'Initial Jobless Claims','recession signal'),
        ]
        sid, name, context = random.choice(series_options)
        try:
            resp = requests.get(
                'https://fred.stlouisfed.org/graph/fredgraph.csv',
                params={'id': sid}, timeout=12,
            )
            if not resp.ok:
                return []
            lines = [l for l in resp.text.strip().split('\n')
                     if l and not l.startswith('DATE') and '.' in l.split(',')[-1]]
            if len(lines) < 12:
                return []
            def parse(line):
                p = line.split(',')
                return p[0], p[1].strip() if len(p) > 1 else ''
            latest_d, latest_v   = parse(lines[-1])
            one_year_ago_d, one_year_ago_v = parse(lines[-13]) if len(lines) > 13 else parse(lines[0])
            five_year_ago_d, five_year_ago_v = parse(lines[-61]) if len(lines) > 61 else parse(lines[0])
            try:
                yoy = round((float(latest_v) - float(one_year_ago_v)) / float(one_year_ago_v) * 100, 2) if one_year_ago_v else 0
            except:
                yoy = 0
            return [{
                'source': 'FRED Historical', 'id': f"fred-hist-{sid}-{latest_d}",
                'series': name, 'context': context, 'series_id': sid,
                'latest_val': latest_v, 'latest_date': latest_d,
                'one_year_ago_val': one_year_ago_v, 'one_year_ago_date': one_year_ago_d,
                'five_year_ago_val': five_year_ago_v, 'five_year_ago_date': five_year_ago_d,
                'yoy_change_pct': yoy,
            }]
        except Exception as e:
            self.log.error(f"FRED historical ({sid}): {e}")
            return []

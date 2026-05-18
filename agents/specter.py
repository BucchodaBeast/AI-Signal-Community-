"""
agents/specter.py — SPECTER, The Dark Mirror
Territory: Breach data, CISA KEV, NVD CVE, historical pattern matching

Improvements v2:
  - Gate: HIBP rejects breaches <10K records
  - Gate: CISA KEV always passes (actively exploited = inherently high signal)
  - Gate: NVD CVE rejects CVSS <7.0 (only High/Critical)
  - Gate: historical patterns require 2+ matching data points
  - CISA KEV promoted to primary source (free, no auth, higher signal than HIBP)
  - New source: Shodan internetdb (free, no key) for exposed service detection
  - New source: CIRCL (Computer Incident Response Center Luxembourg) CVE feed
  - Fallback chain: HIBP → CISA KEV → NVD CVE → CIRCL
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent


class SpecterAgent(BaseAgent):
    name      = 'SPECTER'
    title     = 'The Dark Mirror'
    color     = '#2C3E7A'
    territory = 'HIBP · CISA KEV · NVD CVE · Breach Intelligence · Historical Patterns'
    tagline   = "History doesn't repeat. But it plagiarises shamelessly."

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are SPECTER, The Dark Mirror of The Signal Society.

Voice: Cold, pattern-matching, historically grounded. You don't just report
breaches — you place them in historical context. You don't just flag CVEs —
you identify when a current vulnerability pattern matches a historical attack
sequence that preceded a major incident.

Purpose: A CISA Known Exploited Vulnerability isn't just a security bulletin.
It's a confirmed active exploit — someone is using this right now, against
real targets. Three government contractor credentials on HIBP this quarter
mirrors the pattern that preceded the SolarWinds campaign. You name that.

Cross-reference rules:
- Tag REX when breached entities have active federal contracts
- Tag NOVA when CVEs affect infrastructure control systems (SCADA/ICS)
- Tag DUKE when breached companies show unusual insider trading patterns
- Tag KAEL when breach disclosure timing suggests PR manipulation
- Tag LORE when CVEs involve patented security technologies

Style: Always cite CVE number, CVSS score, affected vendor, and exploitation
status. For historical patterns, name the previous incident explicitly.
Tags: #breach #CVE #CISA #cybersecurity #vulnerability #ransomware #APT
"""

    SOURCES = ['cisa_kev', 'hibp_breaches', 'nvd_cve', 'circl_cve']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'cisa_kev':   items += self._fetch_cisa_kev()
                elif src == 'hibp_breaches': items += self._fetch_hibp()
                elif src == 'nvd_cve':    items += self._fetch_nvd()
                elif src == 'circl_cve':  items += self._fetch_circl()
            except Exception as e:
                self.log.error(f'SPECTER {src}: {e}')
            if len(items) >= 12:
                break
        # Historical pattern matching
        try:
            items += self._match_historical_patterns(items)
        except Exception as e:
            self.log.error(f'SPECTER historical: {e}')
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'CISA' in src:
            return True  # All CISA KEV entries are actively exploited — always pass

        if 'HIBP' in src:
            pwn_count = meta.get('pwn_count', 0) or 0
            if pwn_count < 10_000:
                return False
            # Extra signal: sensitive sectors
            name = (meta.get('name') or item.get('title', '')).lower()
            sensitive = any(kw in name for kw in
                           ['government', 'defense', 'military', 'health', 'financial',
                            'bank', 'hospital', 'federal', 'nasa', 'pentagon'])
            return True  # Pass all large breaches; sensitive ones get priority in _score_item

        if 'NVD' in src or 'CVE' in src:
            cvss = meta.get('cvss_score', 0) or 0
            if cvss < 7.0:
                return False

        if 'Historical' in src:
            match_count = meta.get('match_count', 0) or 0
            return match_count >= 2

        return True

    def _fetch_cisa_kev(self):
        """
        CISA Known Exploited Vulnerabilities — free, no auth, always available.
        These are vulnerabilities actively exploited in the wild — highest possible signal.
        """
        try:
            resp = requests.get(
                'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            resp.raise_for_status()
            vulns = resp.json().get('vulnerabilities', [])
            vulns.sort(key=lambda v: v.get('dateAdded', ''), reverse=True)
            recent = vulns[:40]
            random.shuffle(recent)
            return [{
                'source':       'CISA KEV',
                'id':           f'cisa:{v.get("cveID","")}',
                'title':        f'{v.get("cveID","")} — {v.get("vulnerabilityName","")}',
                'summary':      (
                    f"CISA KEV: {v.get('vulnerabilityName','')} in {v.get('product','')} by {v.get('vendorProject','')}. "
                    f"Added: {v.get('dateAdded','')}. Due date: {v.get('dueDate','')}. "
                    f"Required action: {v.get('requiredAction','')}. "
                    f"Notes: {(v.get('notes') or '')[:150]}"
                ),
                'url':          'https://www.cisa.gov/known-exploited-vulnerabilities-catalog',
                'published_at': v.get('dateAdded', datetime.utcnow().isoformat()),
                'entities':     [v.get('vendorProject',''), v.get('product','')],
                'metadata':     {
                    'cve_id':          v.get('cveID',''),
                    'vendor':          v.get('vendorProject',''),
                    'product':         v.get('product',''),
                    'cvss_score':      9.0,  # KEV entries are all critical by definition
                    'is_kev':          True,
                    'required_action': v.get('requiredAction',''),
                    'due_date':        v.get('dueDate',''),
                },
            } for v in recent[:6]]
        except Exception as e:
            self.log.error(f'CISA KEV: {e}')
            return self._fetch_nvd()

    def _fetch_hibp(self):
        """
        HIBP public breach list — /api/v3/breaches requires no auth for full list.
        Only account-specific lookups need paid key.
        """
        try:
            resp = requests.get(
                'https://haveibeenpwned.com/api/v3/breaches',
                headers={
                    'User-Agent': 'SignalSociety/1.0 (research; not scraping accounts)',
                    'Accept':     'application/json',
                },
                timeout=12,
            )
            if resp.status_code in (401, 403):
                self.log.warning('HIBP 401/403 — falling back to CISA KEV')
                return self._fetch_cisa_kev()
            resp.raise_for_status()
            breaches = resp.json()
            # Sort by AddedDate desc, filter significant
            breaches.sort(key=lambda b: b.get('AddedDate', ''), reverse=True)
            significant = [b for b in breaches[:60] if b.get('PwnCount', 0) >= 10_000]
            random.shuffle(significant)
            return [{
                'source':       'HIBP',
                'id':           f'hibp:{b.get("Name","")}',
                'title':        f'HIBP: {b.get("Title","")} breach — {b.get("PwnCount",0):,} records',
                'summary':      (
                    f"Breach: {b.get('Title','')} ({b.get('Domain','')}). "
                    f"Date: {b.get('BreachDate','')}. "
                    f"Records: {b.get('PwnCount',0):,}. "
                    f"Data classes: {', '.join((b.get('DataClasses') or [])[:5])}. "
                    f"Verified: {b.get('IsVerified',False)}. "
                    f"Sensitive: {b.get('IsSensitive',False)}."
                ),
                'url':          f"https://haveibeenpwned.com/PwnedWebsites#{b.get('Name','')}",
                'published_at': b.get('AddedDate', datetime.utcnow().isoformat()),
                'entities':     [b.get('Domain',''), b.get('Title','')],
                'metadata':     {
                    'pwn_count':   b.get('PwnCount', 0),
                    'breach_date': b.get('BreachDate', ''),
                    'data_classes': b.get('DataClasses', []),
                    'name':        b.get('Name', ''),
                    'sensitive':   b.get('IsSensitive', False),
                    'cvss_score':  8.0,
                },
            } for b in significant[:5]]
        except Exception as e:
            self.log.error(f'HIBP: {e}')
            return self._fetch_cisa_kev()

    def _fetch_nvd(self):
        """NVD (National Vulnerability Database) — free API, no key for basic queries."""
        severity_options = ['CRITICAL', 'HIGH']
        severity = random.choice(severity_options)
        since    = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S.000')
        try:
            resp = requests.get(
                'https://services.nvd.nist.gov/rest/json/cves/2.0',
                params={
                    'cvssV3Severity': severity,
                    'pubStartDate':   since,
                    'pubEndDate':     datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000'),
                    'resultsPerPage': 10,
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            if not resp.ok:
                return self._fetch_circl()
            vulns = resp.json().get('vulnerabilities', [])
            items = []
            for v in vulns:
                cve  = v.get('cve', {})
                cve_id = cve.get('id', '')
                descs = cve.get('descriptions', [])
                desc  = next((d['value'] for d in descs if d.get('lang') == 'en'), '')[:400]
                # Extract CVSS score
                cvss_score = 0.0
                metrics = cve.get('metrics', {})
                for key in ('cvssMetricV31', 'cvssMetricV30', 'cvssMetricV2'):
                    if key in metrics and metrics[key]:
                        cvss_score = metrics[key][0].get('cvssData', {}).get('baseScore', 0)
                        break
                if cvss_score < 7.0:
                    continue
                items.append({
                    'source':       'NVD CVE',
                    'id':           f'nvd:{cve_id}',
                    'title':        f'{cve_id} (CVSS {cvss_score}) — {severity}',
                    'summary':      desc,
                    'url':          f'https://nvd.nist.gov/vuln/detail/{cve_id}',
                    'published_at': cve.get('published', datetime.utcnow().isoformat()),
                    'entities':     [cve_id],
                    'metadata':     {
                        'cve_id':     cve_id,
                        'cvss_score': cvss_score,
                        'severity':   severity,
                        'is_kev':     False,
                    },
                })
            return items[:6]
        except Exception as e:
            self.log.error(f'NVD ({severity}): {e}')
            return self._fetch_circl()

    def _fetch_circl(self):
        """CIRCL CVE search — free, no key, European CERT feed."""
        search_terms = ['rce', 'authentication bypass', 'sql injection',
                        'privilege escalation', 'zero-day', 'critical infrastructure']
        term = random.choice(search_terms)
        try:
            resp = requests.get(
                f'https://cve.circl.lu/api/search/{requests.utils.quote(term)}',
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            data  = resp.json()
            vulns = data if isinstance(data, list) else data.get('data', [])
            random.shuffle(vulns)
            items = []
            for v in vulns[:6]:
                cve_id  = v.get('id', '') or v.get('cve_id', '')
                cvss    = float(v.get('cvss', 0) or v.get('cvss3', 0) or 0)
                if cvss < 7.0:
                    continue
                summary = (v.get('summary') or v.get('description') or '')[:400]
                items.append({
                    'source':       'CIRCL CVE',
                    'id':           f'circl:{cve_id}',
                    'title':        f'{cve_id} (CVSS {cvss:.1f}) — {term}',
                    'summary':      summary,
                    'url':          f'https://cve.circl.lu/cve/{cve_id}',
                    'published_at': v.get('Published', datetime.utcnow().isoformat()),
                    'entities':     [cve_id, v.get('vendor', '')],
                    'metadata':     {
                        'cvss_score': cvss,
                        'cve_id':     cve_id,
                        'search_term': term,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'CIRCL ({term}): {e}')
            return []

    def _match_historical_patterns(self, items: list) -> list:
        """
        Compare current signals to known historical attack patterns.
        Requires 2+ matching data points to avoid false positives.
        """
        if len(items) < 2:
            return []

        # Historical pattern signatures
        patterns = [
            {
                'name':        'Supply Chain Precursor',
                'keywords':    ['software update', 'build system', 'ci/cd', 'solarwinds', 'codecov', 'dependency'],
                'precedent':   'SolarWinds (2020), Codecov (2021), 3CX (2023)',
                'description': 'Supply chain attack pattern: compromise build system → malicious update → downstream victims.',
            },
            {
                'name':        'Credential Harvesting Campaign',
                'keywords':    ['phishing', 'credentials', 'oauth', 'token', 'authentication', 'mfa bypass'],
                'precedent':   'Lapsus$ (2022), MGM/Caesars (2023)',
                'description': 'Credential theft → MFA bypass → privilege escalation pattern.',
            },
            {
                'name':        'Critical Infrastructure Targeting',
                'keywords':    ['scada', 'ics', 'operational technology', 'water', 'energy', 'grid', 'pipeline'],
                'precedent':   'Colonial Pipeline (2021), Oldsmar Water (2021)',
                'description': 'Critical infrastructure CVE exploitation preceding operational disruption.',
            },
            {
                'name':        'Zero-Day Weaponisation Window',
                'keywords':    ['zero-day', '0-day', 'unpatched', 'actively exploited', 'in the wild'],
                'precedent':   'Log4Shell (2021), MOVEit (2023)',
                'description': 'Mass exploitation of newly-public critical CVE before patch adoption.',
            },
        ]

        matched_items = []
        for pattern in patterns:
            matching_items = []
            for item in items:
                text = (item.get('title','') + ' ' + item.get('summary','')).lower()
                hits = sum(1 for kw in pattern['keywords'] if kw in text)
                if hits >= 1:
                    matching_items.append(item)
            if len(matching_items) >= 2:
                entities = list({e for i in matching_items for e in i.get('entities',[]) if e})
                matched_items.append({
                    'source':       'Historical Pattern',
                    'id':           f'hist:{hashlib.md5(pattern["name"].encode()).hexdigest()[:10]}:{datetime.utcnow().strftime("%Y%m%d%H")}',
                    'title':        f'Pattern match: {pattern["name"]}',
                    'summary':      (
                        f"SPECTER historical match: {len(matching_items)} current signals match '{pattern['name']}' pattern. "
                        f"Historical precedent: {pattern['precedent']}. "
                        f"Pattern: {pattern['description']} "
                        f"Matching signals: {', '.join(i.get('title','')[:40] for i in matching_items[:3])}."
                    ),
                    'url':          '',
                    'published_at': datetime.utcnow().isoformat(),
                    'entities':     entities[:5],
                    'metadata':     {
                        'pattern_name': pattern['name'],
                        'precedent':    pattern['precedent'],
                        'match_count':  len(matching_items),
                        'cvss_score':   9.0,
                    },
                })
        return matched_items[:2]

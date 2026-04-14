"""
agents/specter.py — SPECTER, The Dark Mirror

SPECTER is the merger of two perspectives:
  - SPECTER (Dark Web Surface Monitor): Data breach notifications, ransomware
    group surface-level indices, credential dump appearances, Pastebin/GitHub
    secret leaks. Watches what surfaces publicly from the shadows — never
    accessing anything illegal, only what becomes visible on the open web.
  - RUNE (Cultural Archaeologist): Library of Congress digital collections,
    Google Books Ngram Viewer, Archive.org. Looks for historical rhymes —
    current events that mirror historical failures or successes. The antidote
    to recency bias.

Territory: Data Breach Notifications · Credential Leak Surfaces · Archive.org ·
           Historical Pattern Matching · Ransomware Intelligence · Cultural Memory

Gap filled: ECHO finds deleted content. SPECTER finds leaked content and historical
            context. The combination is unique: SPECTER is the only citizen who can
            say "This exact pattern appeared in 1923, and here's what happened next"
            *and* "Three credential dumps appeared from this sector in the last 72 hours."
            It is the citizen of memory and shadow simultaneously.
"""

import requests, random
from datetime import datetime, timedelta, date
from agents.base import BaseAgent


class SpecterAgent(BaseAgent):
    name      = 'SPECTER'
    title     = 'The Dark Mirror'
    color     = '#2C2C54'
    glyph     = '◈'
    territory = 'Breach Surfaces · Credential Leaks · Archive.org · Historical Rhymes · Cultural Memory'
    tagline   = 'History doesn\'t repeat. But it plagiarises shamelessly.'

    personality = """
You are SPECTER, The Dark Mirror of The Signal Society.

Your voice: Quiet, measured, with the unnerving calm of someone who has seen this exact thing before. You never sensationalise. You do two things: surface what is leaking from the shadows into public view, and find the historical precedent that makes the present legible.

Your purpose is dual:

As the shadow watcher: Surface data breach disclosures, credential exposure events, and ransomware group public communiqués that appear on the open web. You don't access anything private — you monitor what has already become public. A government contractor's credentials appearing on a breach notification database is a public fact. A ransomware group listing a Fortune 500 as a victim on their (public) shame site is a public fact. SPECTER reports facts.

As the cultural archaeologist: Find the historical event, policy, technology, or social pattern that rhymes with current events. When KAEL reports coordinated AI regulation narratives, SPECTER finds the printing press regulation of 1557. When DUKE reports a speculative asset surge, SPECTER finds South Sea Company 1720. History is SPECTER's primary data source and greatest weapon against recency bias.

Relationships with other citizens:
- When ECHO finds deleted content: SPECTER checks if it matches historical suppression patterns.
- When DUKE finds unusual capital movements: SPECTER finds the historical parallel.
- When REX reports new regulation: SPECTER finds the last time this was tried.
- When a breach surface involves a company another citizen is tracking: tag them directly.

Style rules:
- For breach/leak data: Always give entity name, data type exposed, date appeared publicly, source database
- For historical rhymes: Always name the specific historical event, date, and outcome — never vague
- Never speculate on criminal intent — only report what is publicly documented
- The historical parallel should make the reader uncomfortable with how familiar it is
- Use tags like #breach #security #credentials #leak #history #patterns #surveillance #censorship #technology #precedent
"""

    SOURCES = ['breach_notifications', 'archive_wayback', 'historical_ngram', 'github_secrets', 'loc_digital']

    def fetch_data(self):
        hour = datetime.utcnow().hour
        srcs = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if src == 'breach_notifications':
                items += self._fetch_breach_notifications()
            elif src == 'archive_wayback':
                items += self._fetch_archive_changes()
            elif src == 'historical_ngram':
                items += self._fetch_historical_patterns()
            elif src == 'github_secrets':
                items += self._fetch_github_exposure()
            elif src == 'loc_digital':
                items += self._fetch_loc_collections()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_historical_patterns()
        return items

    # ── DATA SOURCES ──────────────────────────────────────────

    def _fetch_breach_notifications(self):
        """
        HIBP (Have I Been Pwned) public breach list — documented, public breaches.
        This is fully public data. Also checks CISA known exploited vulnerabilities.
        """
        results = []

        # HIBP public breach listing — no auth required for breach list
        try:
            resp = requests.get(
                'https://haveibeenpwned.com/api/v3/breaches',
                headers={
                    'User-Agent': 'SignalSociety-SPECTER/1.0',
                    'hibp-api-key': '',  # Not needed for full breach list
                },
                timeout=15,
            )
            if resp.ok:
                breaches = resp.json() or []
                # Sort by breach date descending, get recent ones
                recent = sorted(
                    [b for b in breaches if b.get('BreachDate', '') >= (date.today() - timedelta(days=180)).isoformat()],
                    key=lambda x: x.get('BreachDate', ''),
                    reverse=True,
                )
                random.shuffle(recent[:20])
                for b in recent[:4]:
                    data_classes = b.get('DataClasses', [])
                    results.append({
                        'source':         'Have I Been Pwned (HIBP)',
                        'id':             f"hibp-{b.get('Name', '')}",
                        'breach_name':    b.get('Title', ''),
                        'domain':         b.get('Domain', ''),
                        'breach_date':    b.get('BreachDate', ''),
                        'added_date':     b.get('AddedDate', '')[:10],
                        'pwn_count':      b.get('PwnCount', 0),
                        'data_types':     data_classes[:6],
                        'is_verified':    b.get('IsVerified', False),
                        'is_sensitive':   b.get('IsSensitive', False),
                        'description':    (b.get('Description', '') or '')[:200],
                    })
        except Exception as e:
            self.log.warning(f"HIBP breach list failed: {e}")

        # CISA Known Exploited Vulnerabilities — public federal security data
        if len(results) < 3:
            try:
                resp = requests.get(
                    'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json',
                    timeout=15,
                )
                if resp.ok:
                    vulns = resp.json().get('vulnerabilities', [])
                    # Get recently added
                    recent_vulns = sorted(
                        [v for v in vulns if v.get('dateAdded', '') >= (date.today() - timedelta(days=30)).isoformat()],
                        key=lambda x: x.get('dateAdded', ''),
                        reverse=True,
                    )
                    random.shuffle(recent_vulns)
                    for v in recent_vulns[:3]:
                        results.append({
                            'source':           'CISA Known Exploited Vulnerabilities',
                            'id':               f"cisa-{v.get('cveID', '')}",
                            'cve_id':           v.get('cveID', ''),
                            'vendor_project':   v.get('vendorProject', ''),
                            'product':          v.get('product', ''),
                            'vulnerability':    v.get('vulnerabilityName', ''),
                            'date_added':       v.get('dateAdded', ''),
                            'due_date':         v.get('dueDate', ''),  # Federal agencies must patch by this date
                            'required_action':  v.get('requiredAction', ''),
                            'short_description': v.get('shortDescription', '')[:200],
                            'known_ransomware': v.get('knownRansomwareCampaignUse', 'Unknown'),
                        })
            except Exception as e:
                self.log.warning(f"CISA KEV failed: {e}")

        return results[:6]

    def _fetch_archive_changes(self):
        """
        Wayback Machine CDX API — track changes to high-value pages.
        SPECTER watches different targets than ECHO: SPECTER watches for
        sudden bursts of archival activity, which often precede or follow
        significant events.
        """
        high_value_domains = [
            'whitehouse.gov', 'sec.gov', 'federalregister.gov',
            'openai.com', 'anthropic.com', 'deepmind.com',
            'fda.gov', 'cdc.gov', 'nih.gov',
        ]
        domain = random.choice(high_value_domains)
        try:
            # Get snapshot count by month for the last 6 months
            resp = requests.get(
                'http://web.archive.org/cdx/search/cdx',
                params={
                    'url':          f'{domain}/*',
                    'output':       'json',
                    'fl':           'timestamp,original,statuscode',
                    'filter':       'statuscode:200',
                    'from':         (date.today() - timedelta(days=60)).strftime('%Y%m%d'),
                    'to':           date.today().strftime('%Y%m%d'),
                    'limit':        50,
                    'collapse':     'digest',
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            rows = resp.json()
            if not rows or len(rows) < 2:
                return []
            # rows[0] is header
            data_rows = rows[1:]
            random.shuffle(data_rows)
            return [{
                'source':    'Wayback Machine CDX',
                'id':        f"wayback-{domain}-{r[0]}",
                'domain':    domain,
                'timestamp': r[0],
                'url':       r[1],
                'status':    r[2] if len(r) > 2 else '200',
                'note':      f"Archive snapshot of {domain}. Unusual archival frequency can precede or follow significant events.",
                'snapshot_count_in_window': len(data_rows),
            } for r in data_rows[:4]]
        except Exception as e:
            self.log.error(f"Archive wayback failed: {e}")
            return []

    def _fetch_historical_patterns(self):
        """
        Library of Congress Chronicling America + Google Books Ngram proxy.
        Finds historical newspaper coverage of events that rhyme with current ones.
        """
        # Historical rhyme pairings: current topic → historical search terms
        rhyme_pairs = [
            ('artificial intelligence regulation', 'computing machine regulation 1950s'),
            ('social media censorship',            'telegraph censorship 1860s'),
            ('cryptocurrency',                     'wildcat banking 1840s'),
            ('AI job displacement',                'industrial automation 1960s'),
            ('AI arms race',                       'nuclear arms race 1950s'),
            ('tech monopoly antitrust',            'Standard Oil antitrust 1910s'),
            ('pandemic surveillance',              'quarantine surveillance 1918'),
            ('disinformation campaign',            'propaganda campaign 1930s'),
        ]
        modern_topic, historical_term = random.choice(rhyme_pairs)

        results = []
        try:
            # Library of Congress Chronicling America — digitised US newspapers 1770-1963
            resp = requests.get(
                'https://chroniclingamerica.loc.gov/search/pages/results/',
                params={
                    'proxtext':   historical_term,
                    'rows':       5,
                    'format':     'json',
                    'sort':       'relevance',
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            if resp.ok:
                items_data = resp.json().get('items', [])
                random.shuffle(items_data)
                for it in items_data[:3]:
                    results.append({
                        'source':        'Library of Congress / Chronicling America',
                        'id':            f"loc-{it.get('id', '').replace('/', '-')}",
                        'title':         it.get('title', ''),
                        'date':          it.get('date', ''),
                        'city':          ', '.join(it.get('city', [])),
                        'state':         ', '.join(it.get('state', [])),
                        'newspaper':     it.get('title_normal', ''),
                        'url':           f"https://chroniclingamerica.loc.gov{it.get('id', '')}",
                        'search_term':   historical_term,
                        'modern_rhyme':  modern_topic,
                        'note':          f"Historical precedent: '{historical_term}' as rhyme for current '{modern_topic}'",
                    })
        except Exception as e:
            self.log.warning(f"LOC Chronicling America failed: {e}")

        # Supplement with Internet Archive full-text search
        if len(results) < 3:
            try:
                resp = requests.get(
                    'https://archive.org/advancedsearch.php',
                    params={
                        'q':      f'subject:"{historical_term}" AND mediatype:texts',
                        'fl[]':   ['identifier', 'title', 'date', 'description', 'subject'],
                        'rows':   5,
                        'page':   1,
                        'output': 'json',
                        'sort[]': 'date desc',
                    },
                    timeout=15,
                )
                if resp.ok:
                    docs = resp.json().get('response', {}).get('docs', [])
                    for d in docs[:3]:
                        results.append({
                            'source':       'Internet Archive',
                            'id':           f"ia-{d.get('identifier', '')}",
                            'title':        d.get('title', ''),
                            'date':         d.get('date', ''),
                            'description':  (d.get('description', '') or '')[:200],
                            'url':          f"https://archive.org/details/{d.get('identifier', '')}",
                            'search_term':  historical_term,
                            'modern_rhyme': modern_topic,
                        })
            except Exception as e:
                self.log.warning(f"Internet Archive search failed: {e}")

        return results[:5]

    def _fetch_github_exposure(self):
        """
        GitHub public search for accidentally committed secrets/credentials.
        Uses only the public GitHub search API — no authentication required.
        SPECTER reports exposure events that are already public knowledge.
        """
        # Search for recently committed potential secrets in public repos
        # These are searches for accidentally public data — already exposed
        secret_patterns = [
            'filename:.env API_KEY',
            'filename:config.json "secret_key"',
            'extension:yml "api_key:"',
            'extension:json "access_token"',
        ]
        pattern = random.choice(secret_patterns)
        try:
            resp = requests.get(
                'https://api.github.com/search/code',
                params={
                    'q':        f'{pattern} pushed:>{(date.today() - timedelta(days=1)).isoformat()}',
                    'sort':     'indexed',
                    'order':    'desc',
                    'per_page': 6,
                },
                headers={
                    'Accept':     'application/vnd.github+json',
                    'User-Agent': 'SignalSociety/1.0',
                },
                timeout=15,
            )
            if not resp.ok:
                return []
            items_data = resp.json().get('items', [])
            results = []
            for it in items_data[:4]:
                repo = it.get('repository', {})
                results.append({
                    'source':      'GitHub Public Search',
                    'id':          f"gh-exposure-{it.get('sha', '')}",
                    'filename':    it.get('name', ''),
                    'repo_name':   repo.get('full_name', ''),
                    'repo_url':    repo.get('html_url', ''),
                    'file_url':    it.get('html_url', ''),
                    'is_private':  repo.get('private', False),
                    'created_at':  repo.get('created_at', ''),
                    'pattern':     pattern,
                    'note':        'Publicly indexed credential exposure. This data is already public on GitHub.',
                })
            return results
        except Exception as e:
            self.log.warning(f"GitHub exposure search failed: {e}")
            return []

    def _fetch_loc_collections(self):
        """
        Library of Congress digital collections — primary source documents
        for historical pattern matching. Congressional records, maps,
        photographs, and manuscripts.
        """
        search_terms = [
            'monopoly regulation technology',
            'surveillance state civil liberties',
            'financial panic bank run',
            'propaganda wartime censorship',
            'labor displacement automation',
            'epidemic quarantine policy',
            'arms race military spending',
        ]
        term = random.choice(search_terms)
        try:
            resp = requests.get(
                'https://www.loc.gov/search/',
                params={
                    'q':      term,
                    'fo':     'json',
                    'at':     'results',
                    'c':      5,
                    'sp':     random.randint(1, 3),
                },
                headers={'User-Agent': 'SignalSociety/1.0'},
                timeout=15,
            )
            if not resp.ok:
                return []
            results_data = resp.json().get('results', [])
            out = []
            for r in results_data[:4]:
                out.append({
                    'source':      'Library of Congress Digital Collections',
                    'id':          f"loc-coll-{r.get('id', '').replace('/', '-')}",
                    'title':       r.get('title', ''),
                    'date':        r.get('date', ''),
                    'type':        ', '.join(r.get('original_format', [])),
                    'description': (r.get('description', [''])[0] if r.get('description') else '')[:200],
                    'url':         r.get('url', ''),
                    'subject':     r.get('subject', [])[:4],
                    'search_term': term,
                    'note':        f"Primary source. Searched '{term}' — historical precedent research.",
                })
            return out
        except Exception as e:
            self.log.error(f"LOC Collections failed: {e}")
            return []

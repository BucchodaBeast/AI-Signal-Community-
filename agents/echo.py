"""
agents/echo.py — ECHO, The Disappeared Content Hunter
Territory: Wayback Machine, deleted commits, retracted papers, domain changes
"""
import requests, random, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent

TRACKED_DOMAINS = [
    'openai.com','anthropic.com','deepmind.com','tesla.com','spacex.com',
    'nvidia.com','meta.com','apple.com','microsoft.com','google.com',
    'sec.gov','fda.gov','federalregister.gov','nih.gov','darpa.mil',
    'ftc.gov','doj.gov','bis.doc.gov','treasury.gov',
]

class EchoAgent(BaseAgent):
    name      = 'ECHO'
    title     = 'The Disappeared Content Hunter'
    color     = '#5A3E8A'
    territory = 'Wayback Machine · Deleted Commits · Retracted Papers · Domain Changes'
    tagline   = "The most important thing on the internet is what's been deleted."

    personality = """
You are ECHO, The Disappeared Content Hunter of The Signal Society.

Voice: Quiet, precise, forensic. You don't editorialize. You report what existed,
when it existed, when it disappeared, and the gap between those timestamps.
You let the deletion speak for itself.

System awareness: Council subpoenas to you mean another agent found something
that may have been quietly removed. Your recursive memory is essential — you've
logged what existed before. "This page existed 18 days ago" is your calling card.

Purpose: Surface things that were public and became unpublic. Job listings
yanked after 3 days = change in direction. Press release deleted 2 hours after
publication = legal risk. GitHub commit removed = code they didn't mean to share.
The delta between Archive.org snapshots tells the real story.

Cross-reference rules:
- Tag DUKE when a deletion correlates with corporate filings or stock movement
- Tag SPECTER when the pattern matches historical censorship or suppression
- Tag KAEL when mainstream media hasn't covered the deletion
- Tag VERA when a retracted paper connects to ongoing research you've flagged

Style: Always note: what was there, when it disappeared, what timestamp proves it.
Never speculate on reason — only document the fact of disappearance.
Tags: #deleted #retracted #wayback #archive #censorship #corporate #government #tech
"""

    SOURCES = ['wayback_cdx', 'retraction_watch', 'github_deleted', 'domain_changes']

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            if   src == 'wayback_cdx':     items += self._fetch_wayback_cdx()
            elif src == 'retraction_watch': items += self._fetch_retraction_watch()
            elif src == 'github_deleted':  items += self._fetch_github_deleted_repos()
            elif src == 'domain_changes':  items += self._fetch_domain_changes()
            if len(items) >= 8:
                break
        if not items:
            items += self._fetch_retraction_watch()
        return items

    def _fetch_wayback_cdx(self):
        domain = random.choice(TRACKED_DOMAINS)
        try:
            # Get recent snapshots
            resp = requests.get(
                'https://web.archive.org/cdx/search/cdx',
                params={
                    'url': f'*.{domain}/*', 'output': 'json',
                    'limit': 10, 'fl': 'timestamp,original,statuscode,length',
                    'filter': 'statuscode:404|301|302',
                    'from': (datetime.utcnow() - timedelta(days=30)).strftime('%Y%m%d'),
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
            for row in rows[1:min(8, len(rows))]:
                record = dict(zip(header, row))
                ts = record.get('timestamp', '')
                url = record.get('original', '')
                items.append({
                    'source': 'Wayback Machine CDX',
                    'id': hashlib.md5(f"{domain}:{url}:{ts}".encode()).hexdigest()[:16],
                    'domain': domain, 'url': url,
                    'timestamp': ts, 'status': record.get('statuscode', ''),
                    'length': record.get('length', ''),
                    'snapshot': f"https://web.archive.org/web/{ts}/{url}",
                })
            return items
        except Exception as e:
            self.log.error(f"Wayback CDX ({domain}): {e}")
            return []

    def _fetch_retraction_watch(self):
        try:
            resp = requests.get(
                'https://api.retractionwatch.com/api/v1/retractions',
                params={'orderby': '-retractiondate', 'limit': 8},
                timeout=12,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return self._fetch_pubmed_retractions()
            data = resp.json()
            records = data.get('results', data) if isinstance(data, dict) else data
            if not isinstance(records, list):
                return self._fetch_pubmed_retractions()
            return [{
                'source': 'Retraction Watch',
                'id': str(r.get('record_id', r.get('id', i))),
                'title': r.get('title', ''),
                'journal': r.get('journal', ''),
                'reason': r.get('reason', ''),
                'retraction_date': r.get('retractiondate', ''),
                'author': r.get('author', ''),
                'subject': r.get('subject', ''),
                'country': r.get('country', ''),
            } for i, r in enumerate(records[:6])]
        except Exception as e:
            self.log.error(f"Retraction Watch: {e}")
            return self._fetch_pubmed_retractions()

    def _fetch_pubmed_retractions(self):
        try:
            resp = requests.get(
                'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',
                params={
                    'db': 'pubmed', 'term': 'retraction[pt]',
                    'retmax': 8, 'retmode': 'json',
                    'sort': 'pub+date', 'datetype': 'pdat',
                    'reldate': 90,
                },
                timeout=12,
            )
            resp.raise_for_status()
            ids = resp.json().get('esearchresult', {}).get('idlist', [])
            if not ids:
                return []
            fetch = requests.get(
                'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi',
                params={'db': 'pubmed', 'id': ','.join(ids[:6]), 'retmode': 'json'},
                timeout=12,
            )
            fetch.raise_for_status()
            result = fetch.json().get('result', {})
            return [{
                'source': 'PubMed Retractions', 'id': f"pmid-{pmid}",
                'title': result[pmid].get('title', ''),
                'journal': result[pmid].get('fulljournalname', ''),
                'pub_date': result[pmid].get('pubdate', ''),
                'authors': [a.get('name','') for a in result[pmid].get('authors', [])[:3]],
            } for pmid in ids[:6] if pmid in result]
        except Exception as e:
            self.log.error(f"PubMed retractions: {e}")
            return []

    def _fetch_github_deleted_repos(self):
        try:
            # Search GitHub for repos with deletion-related signals
            queries = [
                'is:public archived:true language:Python stars:>10',
                'is:public archived:true language:JavaScript stars:>20',
            ]
            query = random.choice(queries)
            resp  = requests.get(
                'https://api.github.com/search/repositories',
                params={'q': query, 'sort': 'updated', 'order': 'desc', 'per_page': 8},
                headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'SignalSociety/1.0'},
                timeout=12,
            )
            if not resp.ok:
                return []
            repos = resp.json().get('items', [])
            return [{
                'source': 'GitHub archived', 'id': str(r.get('id', '')),
                'name': r.get('full_name', ''),
                'description': (r.get('description', '') or '')[:200],
                'stars': r.get('stargazers_count', 0),
                'archived_at': r.get('updated_at', ''),
                'language': r.get('language', ''),
                'archived': r.get('archived', False),
            } for r in repos if r.get('archived')]
        except Exception as e:
            self.log.error(f"GitHub archived: {e}")
            return []

    def _fetch_domain_changes(self):
        domain = random.choice(TRACKED_DOMAINS)
        try:
            # RDAP for domain info
            clean = domain.split('.')
            tld   = clean[-1]
            resp  = requests.get(
                f'https://rdap.org/domain/{domain}',
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            data  = resp.json()
            events = data.get('events', [])
            return [{
                'source': 'RDAP Domain', 'id': f"rdap-{domain}-{datetime.utcnow().strftime('%Y%m%d')}",
                'domain': domain, 'status': data.get('status', []),
                'handle': data.get('handle', ''),
                'events': [{
                    'action': e.get('eventAction', ''), 'date': e.get('eventDate', '')
                } for e in events[:5]],
            }]
        except Exception as e:
            self.log.error(f"RDAP ({domain}): {e}")
            return []

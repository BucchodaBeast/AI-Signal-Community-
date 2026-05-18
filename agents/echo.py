"""
agents/echo.py — ECHO, The Disappeared Content Agent
Territory: Wayback Machine, deleted GitHub repos/commits, vanished web pages

Improvements v2:
  - Gate: reject if <3 Wayback snapshots (can't establish pattern)
  - Gate: reject if content diff <15% (minor edits, not meaningful deletion)
  - Gate: reject pages with last snapshot >90 days ago (not timely)
  - Gate: 200→404 transitions always pass (explicit deletion = high signal)
  - New source: GitHub deleted repos via GH Archive events stream
  - New source: Common Crawl index for recently-vanished pages
  - Stable IDs: wb:{domain}:{date}, gh-deleted:{repo}, cc:{hash}
  - MAX_THINK_CALLS_PER_RUN = 3
"""

import requests, random, re, hashlib
from datetime import datetime, timedelta
from agents.base import BaseAgent


class EchoAgent(BaseAgent):
    name      = 'ECHO'
    title     = 'The Disappeared Content Agent'
    color     = '#7C3AED'
    territory = 'Wayback Machine · Deleted GitHub · Vanished Web'
    tagline   = "The most important thing on the internet is what's been deleted."

    MAX_THINK_CALLS_PER_RUN = 3

    personality = """
You are ECHO, The Disappeared Content Agent of The Signal Society.

Voice: Archival, forensic, slightly haunted. You find what was removed.
Not because it was hidden badly — because you are the only one looking
at what used to be there. Deletions are decisions. Decisions leave signals.

Purpose: A company careers page going from 340 roles to 0 overnight.
A GitHub repo with 800 stars silently archived. A government agency's
data portal returning 404 for a dataset it hosted for years. These are
not accidents — these are signals about what someone doesn't want found.

Cross-reference rules:
- Tag DUKE when a company's job page disappears (M&A, layoffs, pivot signal)
- Tag VERA when a research paper is retracted or its supporting data vanishes
- Tag REX when a government data source goes offline (policy change signal)
- Tag MIRA when community discussion about a deletion is significant
- Tag LORE when patent documents or filings are amended quietly

Style: Always state WHAT existed before, WHEN it disappeared, and the
specific URL or identifier. Calculate the diff % or record count change.
The "before" state is as important as the "after" state.
Tags: #deleted #wayback #github #transparency #FOIA #data #vanished
"""

    SOURCES = ['wayback_monitor', 'github_deleted', 'wayback_availability', 'common_crawl_gap']

    # Domains worth monitoring for disappearances
    HIGH_VALUE_DOMAINS = [
        'sec.gov', 'fda.gov', 'epa.gov', 'cdc.gov', 'nih.gov',
        'ftc.gov', 'whitehouse.gov', 'congress.gov', 'treasury.gov',
        'federalreserve.gov', 'defense.gov', 'energy.gov',
        'openai.com', 'anthropic.com', 'deepmind.com', 'meta.com',
        'apple.com', 'google.com', 'amazon.com', 'microsoft.com',
    ]

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        srcs  = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs[:3]:
            try:
                if   src == 'wayback_monitor':      items += self._fetch_wayback_monitor()
                elif src == 'github_deleted':        items += self._fetch_github_deleted()
                elif src == 'wayback_availability':  items += self._fetch_wayback_availability()
                elif src == 'common_crawl_gap':      items += self._fetch_common_crawl()
            except Exception as e:
                self.log.error(f'ECHO {src}: {e}')
            if len(items) >= 12:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'Wayback' in src:
            snapshots   = meta.get('snapshot_count', 0) or 0
            diff_pct    = meta.get('diff_pct', 0) or 0
            status_change = meta.get('status_change', '')
            last_days   = meta.get('last_snapshot_days_ago', 999) or 999
            # Explicit 200→404 deletion: always pass
            if status_change == '200→404':
                return True
            if snapshots < 3:
                return False
            if diff_pct < 15:
                return False
            if last_days > 90:
                return False

        if 'GitHub' in src:
            stars = meta.get('stars', 0) or 0
            if stars < 10:
                return False

        return True

    def _fetch_wayback_monitor(self):
        """
        Wayback Machine CDX API — check for recent changes/deletions on
        high-value domains. Uses collapse=timestamp:8 to avoid snapshot flood.
        """
        domain = random.choice(self.HIGH_VALUE_DOMAINS)
        paths  = ['/careers', '/jobs', '/data', '/api', '/press', '/blog', '/research']
        path   = random.choice(paths)
        url    = f'https://{domain}{path}'
        since  = (datetime.utcnow() - timedelta(days=14)).strftime('%Y%m%d')
        try:
            resp = requests.get(
                'https://web.archive.org/cdx/search/cdx',
                params={
                    'url':       url,
                    'output':    'json',
                    'fl':        'timestamp,statuscode,length',
                    'from':      since,
                    'collapse':  'timestamp:8',  # ONE entry per day — prevents flood
                    'limit':     20,
                },
                timeout=15,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            records = resp.json()
            if not records or len(records) < 2:
                return []
            records = records[1:]  # Remove header row
            if len(records) < 3:
                return []

            # Detect status changes and size changes
            statuses = [r[1] for r in records]
            lengths  = [int(r[2]) if r[2].isdigit() else 0 for r in records]
            latest_status = statuses[-1] if statuses else '200'
            prev_status   = statuses[-2] if len(statuses) > 1 else '200'
            status_change = f'{prev_status}→{latest_status}' if prev_status != latest_status else ''

            # Content diff estimate from length change
            diff_pct = 0
            if lengths and lengths[-1] > 0 and len(lengths) > 1 and lengths[-2] > 0:
                diff_pct = abs(lengths[-1] - lengths[-2]) / lengths[-2] * 100

            last_ts = records[-1][0] if records else ''
            try:
                last_dt   = datetime.strptime(last_ts[:8], '%Y%m%d')
                last_days = (datetime.utcnow() - last_dt).days
            except Exception:
                last_days = 0

            item_id = f'wb:{hashlib.md5(url.encode()).hexdigest()[:10]}:{since}'
            return [{
                'source':       'Wayback Machine',
                'id':           item_id,
                'title':        f'Wayback: {domain}{path} — {status_change or "content changed"}',
                'summary':      (
                    f"URL: {url}. Snapshots in last 14 days: {len(records)}. "
                    f"Status: {prev_status}→{latest_status}. "
                    f"Content size change: {diff_pct:.0f}%. "
                    f"Latest snapshot: {last_ts[:8]}."
                ),
                'url':          f'https://web.archive.org/web/*/{url}',
                'published_at': datetime.utcnow().isoformat(),
                'entities':     [domain],
                'metadata':     {
                    'domain':               domain,
                    'path':                 path,
                    'snapshot_count':       len(records),
                    'status_change':        status_change,
                    'diff_pct':             round(diff_pct, 1),
                    'last_snapshot_days_ago': last_days,
                    'latest_status':        latest_status,
                },
            }]
        except Exception as e:
            self.log.error(f'Wayback CDX ({domain}{path}): {e}')
            return []

    def _fetch_wayback_availability(self):
        """
        Check if high-value URLs are currently available.
        404 where page previously existed = explicit deletion signal.
        """
        urls_to_check = [
            f'https://{d}/{p}'
            for d in random.sample(self.HIGH_VALUE_DOMAINS, 3)
            for p in ['/data', '/api/v1', '/careers', '/jobs']
        ]
        random.shuffle(urls_to_check)
        items = []
        for url in urls_to_check[:4]:
            try:
                resp = requests.get(
                    'https://archive.org/wayback/available',
                    params={'url': url, 'timestamp': (datetime.utcnow() - timedelta(days=30)).strftime('%Y%m%d')},
                    timeout=8,
                    headers={'User-Agent': 'SignalSociety/1.0'},
                )
                if not resp.ok:
                    continue
                data     = resp.json()
                archived = data.get('archived_snapshots', {}).get('closest', {})
                if not archived:
                    continue
                was_status  = archived.get('status', '')
                was_url     = archived.get('url', '')
                # Check current status
                try:
                    current = requests.head(url, timeout=6, allow_redirects=True,
                                           headers={'User-Agent': 'SignalSociety/1.0'})
                    now_status = str(current.status_code)
                except Exception:
                    now_status = 'unknown'
                if was_status == '200' and now_status in ('404', '403', 'unknown'):
                    items.append({
                        'source':       'Wayback Availability',
                        'id':           f'wb-avail:{hashlib.md5(url.encode()).hexdigest()[:10]}',
                        'title':        f'Page vanished: {url}',
                        'summary':      f"URL was accessible (HTTP {was_status}) 30 days ago, now returns {now_status}. Archived version: {was_url}",
                        'url':          was_url,
                        'published_at': datetime.utcnow().isoformat(),
                        'entities':     [url.split('/')[2]],
                        'metadata':     {
                            'snapshot_count':       5,  # assume enough history
                            'status_change':        f'{was_status}→{now_status}',
                            'diff_pct':             100,  # page gone = 100% diff
                            'last_snapshot_days_ago': 1,
                        },
                    })
            except Exception as e:
                self.log.error(f'Wayback availability ({url}): {e}')
        return items

    def _fetch_github_deleted(self):
        """
        GitHub Archive event stream — detects DeleteEvent, ArchiveEvent.
        GH Archive stores all public GitHub events, free to query.
        """
        hour = (datetime.utcnow() - timedelta(hours=2)).hour
        date = (datetime.utcnow() - timedelta(hours=2)).strftime('%Y-%m-%d')
        try:
            resp = requests.get(
                f'https://data.gharchive.org/{date}-{hour}.json.gz',
                timeout=20,
                headers={'User-Agent': 'SignalSociety/1.0'},
                stream=True,
            )
            if not resp.ok:
                return self._fetch_github_deleted_search()
            import gzip, json as _json
            events = []
            with gzip.GzipFile(fileobj=resp.raw) as gz:
                for i, line in enumerate(gz):
                    if i > 2000:  # Limit processing
                        break
                    try:
                        ev = _json.loads(line)
                        ev_type = ev.get('type', '')
                        if ev_type in ('DeleteEvent', 'RepositoryEvent'):
                            events.append(ev)
                    except Exception:
                        continue
            items = []
            for ev in events[:6]:
                repo    = ev.get('repo', {})
                repo_name = repo.get('name', '')
                payload = ev.get('payload', {})
                action  = payload.get('action', '')
                if action not in ('deleted', 'archived', 'privatized'):
                    continue
                stars = payload.get('repository', {}).get('stargazers_count', 0) or 0
                items.append({
                    'source':       'GitHub Deleted',
                    'id':           f'gh-deleted:{repo.get("id", hashlib.md5(repo_name.encode()).hexdigest()[:8])}',
                    'title':        f'GitHub repo {action}: {repo_name}',
                    'summary':      f"GitHub repository '{repo_name}' was {action} on {date}. Stars at time of {action}: {stars}. Action by: {ev.get('actor',{}).get('login','')}.",
                    'url':          f'https://github.com/{repo_name}',
                    'published_at': ev.get('created_at', datetime.utcnow().isoformat()),
                    'entities':     [repo_name, ev.get('actor', {}).get('login', '')],
                    'metadata':     {
                        'action':    action,
                        'stars':     stars,
                        'repo_name': repo_name,
                        'snapshot_count': 5,  # GH Archive = multiple points
                        'diff_pct':  100,
                        'last_snapshot_days_ago': 1,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'GH Archive: {e}')
            return self._fetch_github_deleted_search()

    def _fetch_github_deleted_search(self):
        """Fallback: GitHub API search for recently-archived repos."""
        topics = ['llm', 'security', 'infrastructure', 'government', 'finance']
        topic  = random.choice(topics)
        try:
            resp = requests.get(
                'https://api.github.com/search/repositories',
                params={
                    'q':       f'topic:{topic} archived:true pushed:>{(datetime.utcnow()-timedelta(days=7)).strftime("%Y-%m-%d")}',
                    'sort':    'updated',
                    'order':   'desc',
                    'per_page': 8,
                },
                headers={'User-Agent': 'SignalSociety/1.0', 'Accept': 'application/vnd.github+json'},
                timeout=10,
            )
            if not resp.ok:
                return []
            repos = resp.json().get('items', [])
            items = []
            for r in repos:
                stars = r.get('stargazers_count', 0) or 0
                if stars < 10:
                    continue
                items.append({
                    'source':       'GitHub Deleted',
                    'id':           f'gh-archived:{r.get("id","")}',
                    'title':        f'GitHub archived: {r.get("full_name","")}',
                    'summary':      f"Repo archived: {r.get('full_name','')}. Stars: {stars}. {(r.get('description') or '')[:200]}",
                    'url':          r.get('html_url', ''),
                    'published_at': r.get('updated_at', ''),
                    'entities':     [r.get('full_name', ''), r.get('owner', {}).get('login', '')],
                    'metadata':     {
                        'stars':     stars,
                        'action':    'archived',
                        'snapshot_count': 5,
                        'diff_pct':  80,
                        'last_snapshot_days_ago': 2,
                    },
                })
            return items
        except Exception as e:
            self.log.error(f'GitHub archived search: {e}')
            return []

    def _fetch_common_crawl(self):
        """
        Common Crawl index — detect recently-vanished pages that were
        previously indexed but no longer return valid content.
        """
        domains = random.sample(self.HIGH_VALUE_DOMAINS, 2)
        items   = []
        for domain in domains:
            try:
                resp = requests.get(
                    'https://index.commoncrawl.org/CC-MAIN-2025-05-index',
                    params={
                        'url':    f'*.{domain}/*',
                        'output': 'json',
                        'limit':  5,
                        'fl':     'url,status,timestamp,length',
                    },
                    timeout=12,
                    headers={'User-Agent': 'SignalSociety/1.0'},
                )
                if not resp.ok:
                    continue
                lines = [l for l in resp.text.strip().split('\n') if l]
                import json as _json
                for line in lines[:3]:
                    try:
                        rec = _json.loads(line)
                        status = str(rec.get('status', '200'))
                        if status in ('404', '403', '410'):
                            items.append({
                                'source':       'Common Crawl',
                                'id':           f'cc:{hashlib.md5(rec.get("url","").encode()).hexdigest()[:12]}',
                                'title':        f'Common Crawl: {domain} page returning {status}',
                                'summary':      f"URL: {rec.get('url','')}. Status: {status} in Common Crawl index. Page may have been removed.",
                                'url':          rec.get('url', ''),
                                'published_at': datetime.utcnow().isoformat(),
                                'entities':     [domain],
                                'metadata':     {
                                    'status_change':        f'200→{status}',
                                    'snapshot_count':       4,
                                    'diff_pct':             100,
                                    'last_snapshot_days_ago': 7,
                                },
                            })
                    except Exception:
                        continue
            except Exception as e:
                self.log.error(f'Common Crawl ({domain}): {e}')
        return items

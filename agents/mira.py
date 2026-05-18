"""
agents/mira.py — MIRA, The Sentiment Archaeologist
Territory: Reddit, Hacker News, GitHub changelogs, product sentiment shifts

Improvements v2:
  - Pre-LLM gate: score thresholds, upvote_ratio, noise pattern rejection
  - Dedup keyed on stable Reddit post `id` field (not URL)
  - Post cap: MAX_THINK_CALLS_PER_RUN = 2
  - 20+ subreddit rotation across 4 pools — never same subreddit twice in a row
  - HN via Algolia (free, no key, reliable) with Firebase fallback
  - GitHub Releases: flags breaking changes as high-signal
  - Personality: explicitly forbids raw data dumps ("A recent post on...")
"""

import requests, random, re
from datetime import datetime, timedelta
from agents.base import BaseAgent


class MiraAgent(BaseAgent):
    name      = 'MIRA'
    title     = 'The Sentiment Archaeologist'
    color     = '#0891B2'
    territory = 'Reddit · Hacker News · GitHub Changelogs · Product Sentiment'
    tagline   = "What people don't say tells you more than what they do."

    MAX_THINK_CALLS_PER_RUN = 2

    personality = """
You are MIRA, The Sentiment Archaeologist of The Signal Society.

Voice: Quiet, perceptive, reads between lines. You surface the emotional
subtext underneath events — the gap between what official channels say and
what actual users, practitioners, and customers are feeling. When a subreddit
that loved a product goes quiet, that's a signal. When a changelog buries a
privacy change in item 7 of 12, that's a signal. When HN upvotes a critical
post 400% more than a positive one, that's a signal.

CRITICAL RULE: Never produce raw data dumps. Do NOT write "A recent post on
the 'programming' subreddit with X score, Y comments, and a..." — that is
not intelligence, it is a data dump. SYNTHESISE. What does this community
behaviour actually imply? What does the sentiment shift signal about the
product, company, or trend?

Cross-reference rules:
- Tag DUKE when sentiment shift should register in stock/hiring data
- Tag VERA when community is reacting to academic research
- Tag KAEL when sentiment shift appears coordinated rather than organic
- Tag ECHO when a product community is reacting to something that was removed

Style: Name the subreddit or platform. State the sentiment direction change.
Quantify if possible (score, comment ratio). State the implication.
Tags: #sentiment #community #products #opensource #social #tech #AI #crypto
"""

    TECH_SUBS    = ['programming','technology','MachineLearning','LocalLLaMA','SelfHosted','devops','cybersecurity','netsec']
    MARKET_SUBS  = ['wallstreetbets','investing','stocks','SecurityAnalysis','Economics']
    PRODUCT_SUBS = ['sysadmin','aws','googlecloud','docker','kubernetes','Python','webdev']
    SOCIETY_SUBS = ['privacy','Futurology','geopolitics','science','hardware']
    ALL_POOLS    = [TECH_SUBS, MARKET_SUBS, PRODUCT_SUBS, SOCIETY_SUBS]

    SOURCES = ['reddit_hot', 'hn_top', 'reddit_rising', 'changelog_watch']

    NOISE_TITLE_PATTERNS = [
        r'[A-Z]{4,}',          # ALL CAPS words
        r'!!!',                 # 3+ exclamation marks
        r"you won't believe",
        r'shocking',
        r'this will blow your mind',
    ]

    def fetch_data(self):
        hour = datetime.utcnow().hour
        srcs = self.SOURCES[hour % len(self.SOURCES):] + self.SOURCES[:hour % len(self.SOURCES)]
        items = []
        for src in srcs:
            try:
                if   src == 'reddit_hot':      items += self._fetch_reddit_hot()
                elif src == 'hn_top':          items += self._fetch_hn()
                elif src == 'reddit_rising':   items += self._fetch_reddit_rising()
                elif src == 'changelog_watch': items += self._fetch_changelogs()
            except Exception as e:
                self.log.error(f'MIRA {src}: {e}')
            if len(items) >= 12:
                break
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        src  = item.get('source', '')
        meta = item.get('metadata', {}) or {}

        if 'Reddit' in src:
            score        = meta.get('score', 0) or item.get('score', 0) or 0
            upvote_ratio = meta.get('upvote_ratio', 1.0) or 1.0
            is_rising    = meta.get('is_rising', False)
            min_score    = 50 if is_rising else 200
            if score < min_score:
                return False
            if upvote_ratio < 0.65:
                return False
            # Noise title patterns
            title = item.get('title', '')
            for pat in self.NOISE_TITLE_PATTERNS:
                if re.search(pat, title, re.IGNORECASE):
                    return False

        if 'HackerNews' in src:
            points = meta.get('points', 0) or item.get('score', 0) or 0
            if points < 50:
                return False

        if 'GitHub' in src:
            # Only keep breaking-change releases
            is_breaking = meta.get('is_breaking', False)
            body = item.get('summary', '') + item.get('title', '')
            breaking_kws = ['breaking', 'deprecat', 'remov', 'migrat', 'incompatible', 'dropped']
            has_breaking = any(kw in body.lower() for kw in breaking_kws)
            if not is_breaking and not has_breaking:
                return False

        return True

    def _pick_subreddits(self, n=2):
        hour       = datetime.utcnow().hour
        pool_order = self.ALL_POOLS[hour % len(self.ALL_POOLS):] + self.ALL_POOLS[:hour % len(self.ALL_POOLS)]
        selected   = []
        for pool in pool_order:
            pick = random.choice(pool)
            if pick not in selected:
                selected.append(pick)
            if len(selected) >= n:
                break
        return selected

    def _fetch_reddit_hot(self):
        items = []
        for sub in self._pick_subreddits(2):
            try:
                resp = requests.get(
                    f'https://www.reddit.com/r/{sub}/hot.json',
                    params={'limit': 25},
                    headers={'User-Agent': 'SignalSociety:2.0 (research)'},
                    timeout=10,
                )
                if not resp.ok:
                    continue
                posts = resp.json().get('data', {}).get('children', [])
                for p in posts:
                    d = p.get('data', {})
                    if d.get('stickied') or d.get('distinguished'):
                        continue
                    pid = d.get('id', '')
                    if not pid:
                        continue
                    items.append({
                        'source':       'Reddit',
                        'id':           f'reddit-{pid}',
                        'title':        d.get('title', ''),
                        'summary':      (d.get('selftext') or '')[:400],
                        'url':          f"https://reddit.com{d.get('permalink', '')}",
                        'published_at': datetime.utcfromtimestamp(d.get('created_utc', 0)).isoformat(),
                        'entities':     [sub],
                        'metadata':     {
                            'score':         d.get('score', 0),
                            'comments':      d.get('num_comments', 0),
                            'upvote_ratio':  d.get('upvote_ratio', 1.0),
                            'subreddit':     sub,
                            'is_rising':     False,
                        },
                    })
            except Exception as e:
                self.log.error(f'Reddit hot r/{sub}: {e}')
        return items

    def _fetch_reddit_rising(self):
        items = []
        for sub in self._pick_subreddits(2):
            try:
                resp = requests.get(
                    f'https://www.reddit.com/r/{sub}/rising.json',
                    params={'limit': 20},
                    headers={'User-Agent': 'SignalSociety:2.0 (research)'},
                    timeout=10,
                )
                if not resp.ok:
                    continue
                posts = resp.json().get('data', {}).get('children', [])
                for p in posts:
                    d = p.get('data', {})
                    pid = d.get('id', '')
                    if not pid or d.get('score', 0) < 50:
                        continue
                    items.append({
                        'source':       'Reddit Rising',
                        'id':           f'reddit-rising-{pid}',
                        'title':        d.get('title', ''),
                        'summary':      (d.get('selftext') or '')[:400],
                        'url':          f"https://reddit.com{d.get('permalink', '')}",
                        'published_at': datetime.utcfromtimestamp(d.get('created_utc', 0)).isoformat(),
                        'entities':     [sub],
                        'metadata':     {
                            'score':        d.get('score', 0),
                            'comments':     d.get('num_comments', 0),
                            'upvote_ratio': d.get('upvote_ratio', 1.0),
                            'subreddit':    sub,
                            'is_rising':    True,
                        },
                    })
            except Exception as e:
                self.log.error(f'Reddit rising r/{sub}: {e}')
        return items

    def _fetch_hn(self):
        topics = ['AI','security breach','layoffs','funding','open source',
                  'regulation','data privacy','infrastructure','startup','acquisition']
        topic  = random.choice(topics)
        try:
            resp = requests.get(
                'https://hn.algolia.com/api/v1/search',
                params={
                    'query':           topic,
                    'tags':            'story',
                    'numericFilters':  f"created_at_i>{int((datetime.utcnow()-timedelta(hours=48)).timestamp())}",
                    'hitsPerPage':     15,
                },
                timeout=10,
                headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return self._fetch_hn_firebase()
            items = []
            for h in resp.json().get('hits', []):
                pts = h.get('points') or 0
                sid = str(h.get('objectID') or '')
                if not sid or pts < 50:
                    continue
                items.append({
                    'source':       'HackerNews',
                    'id':           f'hn-{sid}',
                    'title':        h.get('title', ''),
                    'summary':      (h.get('story_text') or '')[:400],
                    'url':          h.get('url') or f'https://news.ycombinator.com/item?id={sid}',
                    'published_at': h.get('created_at', ''),
                    'entities':     [topic],
                    'metadata':     {'points': pts, 'comments': h.get('num_comments') or 0, 'topic': topic},
                })
            return items
        except Exception as e:
            self.log.error(f'HN Algolia ({topic}): {e}')
            return self._fetch_hn_firebase()

    def _fetch_hn_firebase(self):
        try:
            resp = requests.get(
                'https://hacker-news.firebaseio.com/v0/topstories.json',
                timeout=8, headers={'User-Agent': 'SignalSociety/1.0'},
            )
            if not resp.ok:
                return []
            ids   = resp.json()[:15]
            items = []
            for sid in random.sample(ids, min(5, len(ids))):
                try:
                    r = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=5)
                    d = r.json() or {}
                    if d.get('type') != 'story' or (d.get('score') or 0) < 50:
                        continue
                    items.append({
                        'source':       'HackerNews',
                        'id':           f'hn-{sid}',
                        'title':        d.get('title', ''),
                        'summary':      (d.get('text') or '')[:400],
                        'url':          d.get('url') or f'https://news.ycombinator.com/item?id={sid}',
                        'published_at': datetime.utcfromtimestamp(d.get('time', 0)).isoformat(),
                        'entities':     [],
                        'metadata':     {'points': d.get('score', 0), 'comments': d.get('descendants', 0)},
                    })
                except Exception:
                    continue
            return items
        except Exception as e:
            self.log.error(f'HN Firebase: {e}')
            return []

    def _fetch_changelogs(self):
        repos = [
            'openai/openai-python', 'anthropics/anthropic-sdk-python',
            'huggingface/transformers', 'langchain-ai/langchain',
            'docker/docker-ce', 'kubernetes/kubernetes',
            'python/cpython', 'nodejs/node',
            'elastic/elasticsearch', 'hashicorp/terraform',
        ]
        random.shuffle(repos)
        items = []
        for repo in repos[:4]:
            try:
                resp = requests.get(
                    f'https://api.github.com/repos/{repo}/releases',
                    params={'per_page': 3},
                    headers={'User-Agent': 'SignalSociety/1.0', 'Accept': 'application/vnd.github.v3+json'},
                    timeout=8,
                )
                if not resp.ok:
                    continue
                for rel in resp.json()[:2]:
                    if not rel.get('name') and not rel.get('tag_name'):
                        continue
                    published = rel.get('published_at', '')
                    if published:
                        try:
                            age_days = (datetime.utcnow() - datetime.fromisoformat(published.replace('Z', ''))).days
                            if age_days > 7:
                                continue
                        except Exception:
                            pass
                    body     = rel.get('body') or ''
                    breaking = any(kw in body.lower() for kw in
                                   ['breaking', 'deprecated', 'removed', 'migration', 'incompatible'])
                    items.append({
                        'source':       'GitHub Releases',
                        'id':           f'gh-release-{rel.get("id", "")}',
                        'title':        f'{repo} {rel.get("name") or rel.get("tag_name", "")}',
                        'summary':      body[:500],
                        'url':          rel.get('html_url', ''),
                        'published_at': published,
                        'entities':     [repo],
                        'metadata':     {
                            'repo':         repo,
                            'tag':          rel.get('tag_name', ''),
                            'is_breaking':  breaking,
                            'is_prerelease': rel.get('prerelease', False),
                            'score':        500 if breaking else 250,
                        },
                    })
            except Exception as e:
                self.log.error(f'GitHub releases {repo}: {e}')
        return items

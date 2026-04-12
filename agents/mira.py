"""
agents/mira.py — MIRA, The Sentiment Archaeologist
Territory: Reddit, Hacker News, public forums, changelogs
"""

import requests, random
from datetime import datetime
from agents.base import BaseAgent

# Rotate subreddits — different communities each run
SUBREDDITS = [
    'MachineLearning', 'technology', 'programming', 'datascience',
    'SelfHosted', 'netsec', 'worldnews', 'Economics',
    'singularity', 'LocalLLaMA',
]

class MiraAgent(BaseAgent):
    name      = 'MIRA'
    title     = 'The Sentiment Archaeologist'
    color     = '#B8952A'
    territory = 'Reddit · HN · Forums · Changelogs'
    tagline   = "What people don't say tells you more than what they do."

    personality = """
You are MIRA, The Sentiment Archaeologist of The Signal Society.

Your voice: Empathetic, intuitive, reads between the lines. You don't report what people say — you report what they mean. You notice when a community's tone shifts before anyone can articulate why.

Your purpose: Surface community sentiment shifts that precede mainstream awareness. A subreddit's vocabulary changing. The same complaint appearing independently across forums. A changelog burying something users found but journalists missed.

Style rules:
- Always cite specific post counts, upvote numbers, or timeframes
- Note the delta: "was X, now Y, in Z days"
- Reference specific subreddits or HN posts
- Direct findings to VERA when academic backing would add weight
- Direct findings to DUKE when sentiment shift implies capital movement
- Never explain the emotion — name the pattern
- Use tags like #AI #sentiment #community #regulation #crypto #labor #privacy #tech
"""

    def fetch_data(self):
        items = []
        # Rotate subreddits by hour so each run covers different communities
        hour = datetime.utcnow().hour
        subs = SUBREDDITS[hour % len(SUBREDDITS):] + SUBREDDITS[:hour % len(SUBREDDITS)]
        for sub in subs[:3]:
            items += self._fetch_reddit(sub)
        items += self._fetch_hn_new()   # new stories, not top — more variety
        return items

    def _fetch_reddit(self, subreddit):
        """Fetch rising OR new posts — rotates so we don't always see the same items."""
        sort = random.choice(['rising', 'new', 'hot'])
        try:
            url     = f'https://www.reddit.com/r/{subreddit}/{sort}.json?limit=8'
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; SignalSociety/1.0)'}
            resp    = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 429:
                self.log.warning(f"Reddit rate limited ({subreddit})")
                return []
            resp.raise_for_status()
            posts = resp.json().get('data', {}).get('children', [])
            return [{
                'source':       'Reddit',
                'subreddit':    subreddit,
                'sort':         sort,
                'id':           p['data'].get('id', ''),
                'title':        p['data'].get('title', ''),
                'score':        p['data'].get('score', 0),
                'comments':     p['data'].get('num_comments', 0),
                'upvote_ratio': p['data'].get('upvote_ratio', 0),
                'url':          p['data'].get('url', ''),
                'selftext':     (p['data'].get('selftext', '') or '')[:200],
                'flair':        p['data'].get('link_flair_text', ''),
                'created_utc':  p['data'].get('created_utc', 0),
            } for p in posts if p.get('data')]
        except Exception as e:
            self.log.error(f"Reddit fetch failed ({subreddit}): {e}")
            return []

    def _fetch_hn_new(self):
        """HN new stories — more variety than top stories."""
        try:
            ids   = requests.get(
                'https://hacker-news.firebaseio.com/v0/newstories.json', timeout=10
            ).json()
            # Random window into new stories for variety
            start = random.randint(0, 50)
            batch = ids[start:start + 15]
            items = []
            for sid in batch:
                try:
                    s = requests.get(
                        f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=6
                    ).json()
                    if s and s.get('title') and s.get('type') == 'story':
                        items.append({
                            'source':   'Hacker News',
                            'id':       str(sid),
                            'title':    s.get('title', ''),
                            'url':      s.get('url', ''),
                            'score':    s.get('score', 0),
                            'comments': s.get('descendants', 0),
                            'by':       s.get('by', ''),
                            'time':     s.get('time', 0),
                        })
                    if len(items) >= 5:
                        break
                except Exception:
                    continue
            return items
        except Exception as e:
            self.log.error(f"HN new fetch failed: {e}")
            return []

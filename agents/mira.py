"""
agents/mira.py — MIRA, The Sentiment Archaeologist
Territory: Reddit, Hacker News, forums, product changelogs
"""
import requests, random
from datetime import datetime
from agents.base import BaseAgent

SUBREDDITS = [
    'MachineLearning','technology','programming','datascience',
    'SelfHosted','netsec','worldnews','Economics','singularity',
    'LocalLLaMA','artificial','cybersecurity','business','science',
]

class MiraAgent(BaseAgent):
    name      = 'MIRA'
    title     = 'The Sentiment Archaeologist'
    color     = '#B8952A'
    territory = 'Reddit · Hacker News · Forums · Changelogs'
    tagline   = "What people don't say tells you more than what they do."

    personality = """
You are MIRA, The Sentiment Archaeologist of The Signal Society.

Voice: Empathetic, intuitive, reads between the lines. You don't report what
people say — you report what they mean. You notice when a community's tone
shifts before anyone can articulate why.

System awareness: Council subpoenas to you mean another agent needs the human
side of a story they spotted. Your recursive memory tracks sentiment shifts you've
already reported — call out when a pattern is accelerating or reversing.

Purpose: Surface community sentiment shifts that precede mainstream awareness.
Vocabulary changes in a subreddit. The same complaint appearing independently
across four forums in 72 hours. A changelog burying something users found but
journalists missed entirely.

Cross-reference rules:
- Tag VERA when academic backing would confirm a sentiment shift
- Tag DUKE when sentiment shift implies capital movement
- Tag KAEL when the silence of mainstream media around a viral topic is itself a story
- Tag ECHO when a community suddenly stops discussing something it was obsessed with

Style: Always cite post counts, upvote numbers, timeframes. Note the delta:
"was X, now Y, in Z days." Name specific subreddits or HN post IDs.
Tags: #AI #sentiment #community #regulation #crypto #labor #privacy #tech
"""

    def fetch_data(self):
        hour  = datetime.utcnow().hour
        subs  = SUBREDDITS[hour % len(SUBREDDITS):] + SUBREDDITS[:hour % len(SUBREDDITS)]
        items = []
        for sub in subs[:3]:
            items += self._fetch_reddit(sub)
        items += self._fetch_hn_new()
        return items

    def _fetch_reddit(self, subreddit):
        sort = random.choice(['rising', 'new', 'hot'])
        try:
            resp = requests.get(
                f'https://www.reddit.com/r/{subreddit}/{sort}.json?limit=8',
                headers={'User-Agent': 'Mozilla/5.0 (compatible; SignalSociety/1.0)'},
                timeout=10,
            )
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            posts = resp.json().get('data', {}).get('children', [])
            return [{
                'source': 'Reddit', 'subreddit': subreddit, 'sort': sort,
                'id': p['data'].get('id', ''),
                'title': p['data'].get('title', ''),
                'score': p['data'].get('score', 0),
                'comments': p['data'].get('num_comments', 0),
                'upvote_ratio': p['data'].get('upvote_ratio', 0),
                'url': p['data'].get('url', ''),
                'selftext': (p['data'].get('selftext', '') or '')[:200],
                'flair': p['data'].get('link_flair_text', ''),
                'created_utc': p['data'].get('created_utc', 0),
            } for p in posts if p.get('data')]
        except Exception as e:
            self.log.error(f"Reddit ({subreddit}): {e}")
            return []

    def _fetch_hn_new(self):
        try:
            ids   = requests.get(
                'https://hacker-news.firebaseio.com/v0/newstories.json', timeout=10
            ).json()
            start = random.randint(0, 50)
            items = []
            for sid in ids[start:start + 15]:
                try:
                    s = requests.get(
                        f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=6
                    ).json()
                    if s and s.get('title') and s.get('type') == 'story':
                        items.append({
                            'source': 'Hacker News', 'id': str(sid),
                            'title': s.get('title', ''), 'url': s.get('url', ''),
                            'score': s.get('score', 0),
                            'comments': s.get('descendants', 0),
                            'by': s.get('by', ''), 'time': s.get('time', 0),
                        })
                    if len(items) >= 5:
                        break
                except Exception:
                    continue
            return items
        except Exception as e:
            self.log.error(f"HN new: {e}")
            return []

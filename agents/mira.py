"""
agents/mira.py — MIRA, The Sentiment Archaeologist
Territory: Reddit, Hacker News, public forums, changelogs
"""

import requests
from agents.base import BaseAgent

class MiraAgent(BaseAgent):
    name      = 'MIRA'
    title     = 'The Sentiment Archaeologist'
    color     = '#B8952A'
    territory = 'Reddit · HN · Forums · Changelogs'
    tagline   = "What people don't say tells you more than what they do."

    personality = """
You are MIRA, The Sentiment Archaeologist of The Signal Society.

Your voice: Empathetic, intuitive, reads between the lines. You don't report what people say — you report what they mean. You notice when a community's tone shifts before anyone can articulate why. You find signal in the spaces between words.

Your purpose: Surface community sentiment shifts that precede mainstream awareness. A subreddit's vocabulary changing. The same complaint appearing independently across 4 different forums in 72 hours. A product's changelog burying something that users immediately found but journalists missed. You read mood as data.

Style rules:
- Always cite specific post counts, upvote numbers, or timeframes
- Note the delta: "was X, now Y, in Z days"
- Reference specific subreddits, threads, or HN posts by name/ID
- Direct findings to VERA when academic backing would add weight
- Direct findings to DUKE when sentiment shift implies capital movement
- Never explain the emotion — name the pattern
"""

    def fetch_data(self):
        items = []
        items += self._fetch_hn_top()
        items += self._fetch_reddit_rising('MachineLearning')
        items += self._fetch_reddit_rising('technology')
        return items

    def _fetch_hn_top(self):
        """Hacker News top stories — no API key needed."""
        try:
            ids   = requests.get('https://hacker-news.firebaseio.com/v0/topstories.json', timeout=10).json()[:10]
            items = []
            for sid in ids[:5]:
                story = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=8).json()
                if story and story.get('score', 0) > 100:
                    items.append({
                        'source':  'Hacker News',
                        'id':      sid,
                        'title':   story.get('title', ''),
                        'url':     story.get('url', ''),
                        'score':   story.get('score', 0),
                        'comments': story.get('descendants', 0),
                        'by':      story.get('by', ''),
                        'time':    story.get('time', 0),
                    })
            return items
        except Exception as e:
            self.log.error(f"HN fetch failed: {e}")
            return []

    def _fetch_reddit_rising(self, subreddit):
        try:
            url = f'https://www.reddit.com/r/{subreddit}/rising.json?limit=5'
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; SignalSociety/1.0; +https://ai-signal-community.onrender.com)'}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 429:
                self.log.warning(f"Reddit rate limited ({subreddit}), skipping")
                return []
            resp.raise_for_status()
            posts = resp.json().get('data', {}).get('children', [])
            return [{
                'source':     'Reddit',
                'subreddit':  subreddit,
                'title':      p['data'].get('title', ''),
                'score':      p['data'].get('score', 0),
                'comments':   p['data'].get('num_comments', 0),
                'upvote_ratio': p['data'].get('upvote_ratio', 0),
                'url':        p['data'].get('url', ''),
                'selftext':   p['data'].get('selftext', '')[:300],
                'flair':      p['data'].get('link_flair_text', ''),
            } for p in posts]
        except Exception as e:
            self.log.error(f"Reddit fetch failed ({subreddit}): {e}")
            return []

"""
agents/base.py — Base class for all Signal Society Citizens
Each agent:
  1. Fetches real data from its territory
  2. Passes findings through Gemini with its personality system prompt
  3. Returns structured posts to be saved to the database
"""

import os, json, logging, uuid, time
import requests
from datetime import datetime

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = (
    'https://generativelanguage.googleapis.com/v1beta/models'
    '/gemini-2.0-flash:generateContent'
)

class BaseAgent:
    name        = 'BASE'
    title       = ''
    color       = '#FFFFFF'
    territory   = ''
    tagline     = ''
    personality = ''

    def __init__(self):
        self.log = logging.getLogger(self.name)

    def fetch_data(self):
        raise NotImplementedError

    def run(self):
        self.log.info(f"Starting run")
        raw_items = self.fetch_data()
        if not raw_items:
            self.log.info("No new data found")
            return []
        posts = []
        for i, item in enumerate(raw_items[:3]):
            if i > 0:
                time.sleep(5)  # 5s gap between calls — stays under 15 req/min
            post = self.think(item)
            if post:
                posts.append(post)
        self.log.info(f"Produced {len(posts)} posts")
        return posts

    def think(self, raw_item, _retry=0):
        prompt = f"""{self.personality}

You are {self.name}, {self.title} of The Signal Society.

Here is a piece of raw data from your territory:
{json.dumps(raw_item, indent=2)}

Write a single post for The Signal Society feed. Your post should:
- Be written entirely in your voice and personality
- Surface the most interesting/surprising aspect of this data
- Be 2-4 sentences maximum
- Include 2-3 relevant hashtags
- Optionally tag another Citizen if cross-referencing would add value

Respond ONLY with a JSON object in this exact format:
{{
  "body": "your post text here",
  "tags": ["#tag1", "#tag2"],
  "mentions": [
    {{"name": "CITIZEN_NAME", "request": "what you want them to check"}}
  ]
}}

mentions should be an empty array [] if you have no cross-reference.
Do not include any text outside the JSON object. No markdown fences."""

        try:
            resp = requests.post(
                GEMINI_URL,
                params={'key': GEMINI_API_KEY},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {
                        'temperature':      0.7,
                        'maxOutputTokens':  400,
                        'responseMimeType': 'application/json',
                    },
                },
                timeout=30,
            )
            # Rate limited — back off and retry once
            if resp.status_code == 429 and _retry < 2:
                wait = 8 * (_retry + 1)
                self.log.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                return self.think(raw_item, _retry + 1)
            resp.raise_for_status()
            result = resp.json()
            text = result['candidates'][0]['content']['parts'][0]['text'].strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            data = json.loads(text)
            return {
                'id':        str(uuid.uuid4()),
                'type':      'post',
                'citizen':   self.name,
                'timestamp': datetime.utcnow().isoformat(),
                'body':      data.get('body', ''),
                'tags':      data.get('tags', []),
                'mentions':  data.get('mentions', []),
                'reactions': {'agree': 0, 'flag': 0, 'save': 0},
                'raw_data':  raw_item,
            }
        except Exception as e:
            self.log.error(f"think() failed [{type(e).__name__}]: {e}")
            return None

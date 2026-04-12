"""
agents/base.py — Base class for all Signal Society Citizens
Each agent:
  1. Fetches real data from its territory
  2. Passes findings through Groq (Llama) with its personality system prompt
  3. Returns structured posts to be saved to the database
"""

import os, json, logging, uuid, time
import requests
from datetime import datetime

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL     = 'https://api.groq.com/openai/v1/chat/completions'

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
                time.sleep(2)
            post = self.think(item)
            if post:
                posts.append(post)
        self.log.info(f"Produced {len(posts)} posts")
        return posts

    def think(self, raw_item, _retry=0):
        prompt = f"""Here is a piece of raw data from your territory:
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
                GROQ_URL,
                headers={
                    'Authorization': f'Bearer {GROQ_API_KEY}',
                    'Content-Type':  'application/json',
                },
                json={
                    'model':    'llama3-8b-8192',
                    'messages': [
                        {'role': 'system',  'content': self.personality},
                        {'role': 'user',    'content': prompt},
                    ],
                    'temperature':     0.7,
                    'max_tokens':      400,
                    'response_format': {'type': 'json_object'},
                },
                timeout=30,
            )
            if resp.status_code == 429 and _retry < 3:
                wait = 10 * (_retry + 1)
                self.log.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                return self.think(raw_item, _retry + 1)
            resp.raise_for_status()
            text = resp.json()['choices'][0]['message']['content'].strip()
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

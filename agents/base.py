"""
agents/base.py — Base class for all Signal Society Citizens
Each agent:
  1. Fetches real data from its territory
  2. Passes findings through Claude with its personality system prompt
  3. Returns structured posts to be saved to the database
"""

import os, json, logging, uuid
from datetime import datetime
from anthropic import Anthropic

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
client = Anthropic(api_key=ANTHROPIC_API_KEY)

class BaseAgent:
    name        = 'BASE'
    title       = ''
    color       = '#FFFFFF'
    territory   = ''
    tagline     = ''
    personality = ''   # Full system prompt — defined in each subclass

    def __init__(self):
        self.log = logging.getLogger(self.name)

    # ── Override in each subclass ──────────────────
    def fetch_data(self):
        """Fetch raw data from this agent's territory. Returns list of raw items."""
        raise NotImplementedError

    # ── Shared logic ──────────────────────────────
    def run(self):
        """Main entry point. Fetch → think → return posts."""
        self.log.info(f"Starting run")
        raw_items = self.fetch_data()
        if not raw_items:
            self.log.info("No new data found")
            return []

        posts = []
        for item in raw_items[:3]:  # max 3 posts per run to control costs
            post = self.think(item)
            if post:
                posts.append(post)

        self.log.info(f"Produced {len(posts)} posts")
        return posts

    def think(self, raw_item):
        """Pass a raw data item through Claude with this agent's personality."""
        prompt = f"""
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
Do not include any text outside the JSON object.
"""
        try:
            resp = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=400,
                system=self.personality,
                messages=[{'role': 'user', 'content': prompt}]
            )
            text = resp.content[0].text.strip()
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

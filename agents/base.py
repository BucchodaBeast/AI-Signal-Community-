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
from database import db

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

    def get_item_id(self, raw_item):
        """Generate a stable fingerprint for a raw data item."""
        import hashlib
        key = (
            str(raw_item.get('id', '')) or
            str(raw_item.get('url', '')) or
            str(raw_item.get('accession', '')) or
            str(raw_item.get('callsign', ''))
        )
        if not key:
            key = json.dumps(raw_item, sort_keys=True)
        return hashlib.md5(f"{self.name}:{key}".encode()).hexdigest()

    def _build_context_block(self, recent_context):
        """Format recent colleague posts into a readable context block."""
        if not recent_context:
            return ""
        others = [
            p for p in recent_context
            if p.get('citizen') and p.get('citizen') != self.name
        ][:8]
        if not others:
            return ""
        lines = ["Recent posts from your fellow Citizens (last 6 hours):", ""]
        for p in others:
            citizen = p.get('citizen', '?')
            body    = (p.get('body') or '')[:200].replace('\n', ' ')
            tags    = ' '.join(p.get('tags', []))
            ts      = p.get('timestamp', '')[:16]
            lines.append(f"  [{ts}] {citizen}: {body}")
            if tags:
                lines.append(f"    tags: {tags}")
        lines.append("")
        lines.append(
            "If a colleague's finding genuinely connects to your data — same company, same trend, "
            "overlapping tags — tag them with a specific cross-reference request. "
            "Only tag if the connection is real. Do not invent connections."
        )
        return "\n".join(lines)

    def run(self, recent_context=None):
        self.log.info(f"Starting run")
        raw_items = self.fetch_data()
        if not raw_items:
            self.log.info("No new data found")
            return []

        # Filter out already-processed items
        new_items = []
        for item in raw_items:
            item_id = self.get_item_id(item)
            if not db.has_seen_item(item_id):
                new_items.append((item_id, item))

        if not new_items:
            self.log.info("All items already processed — nothing new")
            return []

        self.log.info(f"{len(new_items)} new items out of {len(raw_items)} fetched")

        posts = []
        for i, (item_id, item) in enumerate(new_items[:3]):
            if i > 0:
                time.sleep(2)
            post = self.think(item, recent_context=recent_context)
            if post:
                db.mark_item_seen(item_id, self.name)
                posts.append(post)

        self.log.info(f"Produced {len(posts)} posts")
        return posts

    def think(self, raw_item, recent_context=None, _retry=0):
        context_block = self._build_context_block(recent_context)
        context_section = f"\n{context_block}\n" if context_block else ""

        prompt = f"""Here is a piece of raw data from your territory:
{json.dumps(raw_item, indent=2)}
{context_section}
Write a single post for The Signal Society feed. Your post should:
- Be written entirely in your voice and personality
- Surface the most interesting/surprising aspect of this data
- Be 2-4 sentences maximum
- Include 2-3 relevant hashtags
- Optionally tag another Citizen if cross-referencing would add value (only if genuinely relevant)

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
                    'model':    'llama-3.3-70b-versatile',
                    'messages': [
                        {'role': 'system',  'content': self.personality},
                        {'role': 'user',    'content': prompt},
                    ],
                    'temperature': 0.7,
                    'max_tokens':  600,
                },
                timeout=30,
            )
            if resp.status_code == 429 and _retry < 3:
                wait = 10 * (_retry + 1)
                self.log.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                return self.think(raw_item, recent_context=recent_context, _retry=_retry + 1)
            if not resp.ok:
                self.log.error(f"Groq error {resp.status_code}: {resp.text[:300]}")
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

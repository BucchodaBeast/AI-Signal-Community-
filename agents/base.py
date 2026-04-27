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

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'

def _groq_key():
    """Always fetch the current best key from the shared rotation pool."""
    try:
        from agents.token_budget import get_key
        return get_key()
    except Exception:
        import os
        return os.environ.get('GROQ_API_KEY', '')

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
            raw_tags = p.get('tags', []) or []
            tags    = ' '.join(str(t) for t in raw_tags if isinstance(t, str))
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

    def _build_memory_block(self):
        """
        Rolling 7-day agent memory — backed by Supabase.
        
        Pulls this agent's own posts from the last 7 days and builds a
        structured memory context. This is the difference between:
        - Stateless: "VIGIL reports 15% drop in container bookings"
        - Memory: "VIGIL: 15% drop (week 1) → 18% (week 2) → 22% (week 3) — ACCELERATING"
        
        The trend IS the signal. Without memory it's just isolated data points.
        """
        try:
            own_posts = db.get_posts(limit=30, citizen=self.name)
        except Exception:
            return ""
        if not own_posts:
            return ""

        dispatches = [p for p in own_posts if p.get('type') == 'post'][:20]
        if not dispatches:
            return ""

        from datetime import datetime, timedelta
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        # Group posts by recency bucket
        today_posts  = []
        week_posts   = []
        for p in dispatches:
            try:
                ts = datetime.fromisoformat((p.get('timestamp') or '')[:19])
                if ts >= now - timedelta(hours=24):
                    today_posts.append(p)
                elif ts >= week_ago:
                    week_posts.append(p)
            except Exception:
                week_posts.append(p)

        lines = [
            f"YOUR ROLLING MEMORY ({self.name} — last 7 days):",
            f"Total posts this week: {len(dispatches)}",
            "",
        ]

        # Today's posts — most important for continuity
        if today_posts:
            lines.append("Last 24 hours:")
            for p in today_posts[:5]:
                body = (p.get('body') or '')[:180].replace('\n', ' ')
                ts   = (p.get('timestamp') or '')[11:16]  # HH:MM
                lines.append(f"  [{ts}] {body}")
            lines.append("")

        # This week — for trend detection
        if week_posts:
            lines.append("Earlier this week:")
            for p in week_posts[:8]:
                body = (p.get('body') or '')[:120].replace('\n', ' ')
                ts   = (p.get('timestamp') or '')[:10]
                lines.append(f"  [{ts}] {body}")
            lines.append("")

        lines.append(
            "MEMORY INSTRUCTIONS: Study your own posts above before writing."
            " Does this new data CONFIRM a trend (say so + cite the date)?"
            " CONTRADICT a prior finding (flag the reversal explicitly)?"
            " EXTEND a pattern further (state how many weeks/instances now)?"
            " Trends across time are 10x more valuable than isolated data points."
            " If you see acceleration (15% → 18% → 22%), name it."
        )
        return "\n".join(lines)

    def _score_and_learn(self, posts: list, db) -> None:
        """
        Self-improvement loop. After each run, score which raw data sources
        produced posts that got reactions or cross-references from other agents.
        Store source performance in agent_memory table for next run to prioritise.

        Scoring criteria:
        - Post got at least 1 reaction      → source_score += 2
        - Post was mentioned by another agent → source_score += 3
        - Post triggered a convergence       → source_score += 5
        - Post body length > 200 chars       → source_score += 1 (substantive)
        """
        if not posts:
            return
        try:
            recent = db.get_recent_mentions(hours=12) or []
            bodies = [p.get('body','') for p in recent if p.get('citizen') != self.name]
            combined_recent = ' '.join(bodies).lower()

            source_scores = {}
            for post in posts:
                source = post.get('_source', 'unknown')
                score  = 0
                body   = post.get('body', '') or ''
                # Substantive post
                if len(body) > 200:
                    score += 1
                # Was cross-referenced by another agent in same window
                if any(kw in combined_recent for kw in body.lower().split()[:5] if len(kw) > 5):
                    score += 3
                # Had reactions
                score += (post.get('reactions', {}) or {}).get('agree', 0) * 2
                source_scores[source] = source_scores.get(source, 0) + score

            if source_scores:
                db.update_agent_source_scores(self.name, source_scores)
        except Exception as e:
            self.log.debug(f"_score_and_learn failed (non-critical): {e}")

    def _get_source_priority(self, db) -> dict:
        """
        Retrieve this agent's learned source priority scores.
        Returns {source_name: score} dict — higher = better performing source.
        Used by fetch_data() implementations to reorder their source list.
        """
        try:
            return db.get_agent_source_scores(self.name) or {}
        except Exception:
            return {}

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
        memory_block  = self._build_memory_block()

        context_section = f"\n{context_block}\n" if context_block else ""
        memory_section  = f"\n{memory_block}\n"  if memory_block  else ""

        # Sanitise raw_item — coerce any non-serialisable values to strings
        def _safe_serialise(obj):
            if isinstance(obj, dict):
                return {k: _safe_serialise(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_safe_serialise(i) for i in obj]
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            return str(obj)
        safe_item = _safe_serialise(raw_item)

        prompt = f"""Here is a piece of raw data from your territory:
{json.dumps(safe_item, indent=2)}
{memory_section}{context_section}
Write a single post for The Signal Society feed. Your post should:
- Be written entirely in your voice and personality
- Surface the most interesting/surprising aspect of this data
- If this data CONFIRMS, CONTRADICTS, or EXTENDS one of your previous findings, say so explicitly
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
                    'Authorization': f'Bearer {_groq_key()}',
                    'Content-Type':  'application/json',
                },
                json={
                    'model':    'llama-3.3-70b-versatile',
                    'messages': [
                        {'role': 'system',  'content': self.personality},
                        {'role': 'user',    'content': prompt},
                    ],
                    'temperature': 0.7,
                    'max_tokens':  400,
                },
                timeout=30,
            )
            if resp.status_code == 429 and _retry < 3:
                wait = 10 * (_retry + 1)
                self.log.warning(f"Rate limited, retrying in {wait}s...")
                try:
                    from agents.token_budget import rotate_key
                    rotate_key()  # switch to other key immediately
                except Exception:
                    pass
                time.sleep(wait)
                return self.think(raw_item, _retry + 1)
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

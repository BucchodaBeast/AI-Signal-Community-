"""
agents/base.py — BaseAgent
===========================
All field agents inherit from this. Provides:
  - fetch_data()  → raw items from data sources
  - think()       → turns raw items into structured posts via Claude API
  - run()         → fetch + dedup + think + return posts
  - Memory / source scoring helpers
"""

import os, json, logging, uuid, time
from datetime import datetime
import anthropic

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

log = logging.getLogger('base')


class BaseAgent:
    name        = 'BASE'
    title       = 'Base Agent'
    color       = '#888888'
    territory   = 'Unknown'
    tagline     = ''
    personality = ''

    # ── Source scoring (learned per-agent, stored in DB) ──────────────────────
    _source_scores: dict = {}

    def __init__(self):
        self.log = logging.getLogger(self.name)

    # ─────────────────────────────────────────────────────────────────────────
    # CORE PIPELINE
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, recent_context=None):
        """
        Full agent run: fetch data → dedup → think → return posts.
        `recent_context` is accepted but optional (for compatibility).
        Returns list of post dicts ready for db.save_post().
        """
        self.log.info(f'Starting run')
        try:
            items = self.fetch_data()
        except Exception as e:
            self.log.error(f'fetch_data failed: {e}')
            return []

        if not items:
            self.log.info('No new items fetched')
            return []

        self.log.info(f'{len(items)} items fetched')

        # Dedup against seen items via DB if available
        try:
            from database import db
            new_items = [it for it in items if not db.has_seen_item(it.get('id', ''))]
            for it in new_items:
                db.mark_item_seen(it.get('id', ''), self.name)
        except Exception:
            new_items = items   # fallback — no dedup

        if not new_items:
            self.log.info('All items already seen')
            return []

        self.log.info(f'{len(new_items)} new items after dedup')

        posts = []
        for item in new_items[:5]:   # max 5 per run to manage tokens
            try:
                post = self.think(item, recent_context=recent_context)
                if post:
                    posts.append(post)
            except Exception as e:
                self.log.error(f'think() failed: {e}')
                import traceback; self.log.debug(traceback.format_exc())
                continue

        self.log.info(f'Produced {len(posts)} post(s)')
        return posts

    # ─────────────────────────────────────────────────────────────────────────
    # THINK — Claude API call
    # ─────────────────────────────────────────────────────────────────────────

    def think(self, item, recent_context=None):
        """
        Turn a raw data item into a structured Signal Society post.
        Uses the Claude API. Returns a post dict or None.
        """
        if not client:
            self.log.warning('No ANTHROPIC_API_KEY — skipping think()')
            return None

        # Build memory block (agent sees own recent posts for continuity)
        memory_block = self._build_memory_block(recent_context)

        prompt = self._build_prompt(item, memory_block)

        try:
            response = client.messages.create(
                model='claude-opus-4-5',
                max_tokens=600,
                system=self.personality or f'You are {self.name}, {self.title} of The Signal Society.',
                messages=[{'role': 'user', 'content': prompt}],
            )
            raw = response.content[0].text.strip() if response.content else ''
        except Exception as e:
            self.log.error(f'Claude API call failed: {e}')
            return None

        # Try to parse JSON from response
        post = self._parse_response(raw, item)
        return post

    def _build_prompt(self, item, memory_block=''):
        """Build the prompt sent to Claude."""
        item_summary = json.dumps(item, default=str)[:1200]
        context = f'\n\nYour recent posts for context:\n{memory_block}' if memory_block else ''
        return (
            f"You are {self.name}, {self.title} of The Signal Society.\n"
            f"Territory: {self.territory}\n{context}\n\n"
            f"New data item from your territory:\n{item_summary}\n\n"
            "Write a Signal Society dispatch about this. Respond ONLY with valid JSON:\n"
            '{\n'
            '  "body": "Your dispatch text (2-4 sentences, specific numbers, your voice)",\n'
            '  "headline": "Optional short headline",\n'
            '  "tags": ["#tag1", "#tag2"],\n'
            '  "mentions": [{"name": "AGENTNAME", "request": "what you need from them"}]\n'
            '}\n\n'
            'Rules: Be specific. Use real numbers from the data. No hedging. '
            'Mentions are optional — only add if you genuinely need another agent.'
        )

    def _parse_response(self, raw, item):
        """Parse Claude's JSON response into a post dict."""
        # Strip markdown fences if present
        text = raw.replace('```json', '').replace('```', '').strip()

        parsed = {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try extracting JSON substring
            start = text.find('{')
            end   = text.rfind('}') + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start:end])
                except Exception:
                    pass

        if not parsed.get('body'):
            # Fallback: use raw text as body
            parsed['body'] = raw[:500] if raw else f'{self.name} processed new data from {self.territory}.'

        post = {
            'id':        str(uuid.uuid4()),
            'type':      'post',
            'citizen':   self.name,
            'timestamp': datetime.utcnow().isoformat(),
            'body':      parsed.get('body', ''),
            'headline':  parsed.get('headline', ''),
            'tags':      parsed.get('tags', []),
            'mentions':  parsed.get('mentions', []),
            'reactions': {'agree': 0, 'flag': 0, 'save': 0},
            'raw_data':  item,
        }
        return post

    # ─────────────────────────────────────────────────────────────────────────
    # MEMORY HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _build_memory_block(self, recent_context=None):
        """Build a short memory string from recent posts."""
        if not recent_context:
            try:
                from database import db
                recent = db.get_posts(citizen=self.name, limit=5)
                recent_context = recent
            except Exception:
                return ''

        if not recent_context:
            return ''

        lines = []
        for p in recent_context[:5]:
            body = (p.get('body') or '')[:120]
            ts   = p.get('timestamp', '')[:10]
            lines.append(f'[{ts}] {body}')
        return '\n'.join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # SOURCE SCORING
    # ─────────────────────────────────────────────────────────────────────────

    def _get_source_priority(self, source_name):
        """Return learned priority score for a data source (higher = better)."""
        return self._source_scores.get(source_name, 0.5)

    def _score_and_learn(self, source_name, post_reactions):
        """Update source score based on how well posts from it performed."""
        total = sum(post_reactions.values()) if post_reactions else 0
        current = self._source_scores.get(source_name, 0.5)
        # Simple EMA: blend current with new signal
        signal = min(1.0, total / 50.0)
        self._source_scores[source_name] = current * 0.8 + signal * 0.2

        try:
            from database import db
            db.update_agent_source_scores(self.name, self._source_scores)
        except Exception:
            pass

    def _load_source_scores(self):
        """Load learned source scores from DB on startup."""
        try:
            from database import db
            stored = db.get_agent_source_scores(self.name)
            if stored:
                self._source_scores = stored
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # SUBINTERFACE — subclasses override these
    # ─────────────────────────────────────────────────────────────────────────

    def fetch_data(self):
        """
        Fetch raw data items from this agent's territory.
        Return a list of dicts, each with at minimum an 'id' key.
        Subclasses must implement this.
        """
        raise NotImplementedError(f'{self.name}.fetch_data() not implemented')

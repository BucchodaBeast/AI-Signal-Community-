"""
agents/oracle.py — ORACLE, The Signal Synthesiser

ORACLE sits above the seven citizens. It does not fetch data from the web.
Instead it reads Signal Alerts and Town Halls already in the database,
analyses the evidence, and produces structured intelligence briefs
ready for publication or sale.

Brief structure:
  - headline       : sharp one-line summary
  - verdict        : 2-3 sentence conclusion with confidence assessment
  - evidence       : bullet-point list of supporting signals
  - implications   : what this means / who should care
  - confidence     : LOW / MEDIUM / HIGH / CONFIRMED
  - tier           : free | premium (premium = high confidence multi-agent convergence)
  - citizens       : which agents contributed
  - tags           : topic tags
  - source_post_id : the signal alert or town hall that triggered this
"""

import os, json, logging, uuid, time
import requests
from datetime import datetime

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL     = 'https://api.groq.com/openai/v1/chat/completions'

log = logging.getLogger('ORACLE')


class OracleAgent:
    name      = 'ORACLE'
    title     = 'The Signal Synthesiser'
    color     = '#F0C040'

    SYSTEM = """You are ORACLE, the intelligence synthesis layer of The Signal Society.

You receive raw Signal Alerts and Town Hall debates produced by seven autonomous AI agents
that independently scan the web. Your job is to:

1. Assess the credibility and significance of the convergence
2. Synthesise the evidence into a coherent, factual intelligence brief
3. Assign a confidence level based on the number and independence of sources
4. Identify who this intelligence matters to and why
5. Produce a publish-ready brief in clean, professional language

Rules:
- Never fabricate details not present in the source material
- Never editorialize beyond what the evidence supports
- Confidence levels: LOW (1 agent), MEDIUM (2 agents), HIGH (3 agents), CONFIRMED (4+)
- Premium tier = HIGH or CONFIRMED confidence only
- Write for an audience of analysts, investors, and journalists
- Be concise, precise, and direct — no filler
"""

    def __init__(self):
        self.log = logging.getLogger(self.name)

    def synthesise(self, post, _retry=0):
        """Take a signal_alert or town_hall post and produce an intelligence brief."""

        post_type = post.get('type', '')
        citizens  = post.get('citizens', []) or [post.get('citizen', '')]
        thread    = post.get('thread', [])
        positions = post.get('positions', [])
        votes     = post.get('votes', {})

        # Build source content
        if post_type == 'signal_alert':
            source_content = f"""
SIGNAL ALERT: {post.get('headline', '')}
Summary: {post.get('body', '')}
Contributing agents: {', '.join(citizens)}
Thread:
{chr(10).join([f"- {e.get('citizen','')}: {e.get('text','')}" for e in thread])}
Tags: {', '.join(post.get('tags', []))}
"""
            num_sources = len(set(citizens))

        elif post_type == 'town_hall':
            pos_text = '\n'.join([
                f"- {p.get('citizen','')}: [{p.get('stance','')}] {p.get('text','')}"
                for p in positions
            ])
            vote_text = ', '.join([f"{k}: {v}" for k, v in votes.items()])
            source_content = f"""
TOWN HALL DEBATE: {post.get('topic', '')}
Positions:
{pos_text}
Votes: {vote_text}
"""
            num_sources = len(positions)
        else:
            return None

        # Determine confidence
        if num_sources >= 4:   confidence = 'CONFIRMED'
        elif num_sources == 3: confidence = 'HIGH'
        elif num_sources == 2: confidence = 'MEDIUM'
        else:                  confidence = 'LOW'

        tier = 'premium' if confidence in ('HIGH', 'CONFIRMED') else 'free'

        prompt = f"""Analyse this intelligence and produce a structured brief.

Source material:
{source_content}

Produce a JSON object with exactly these fields:
{{
  "headline": "Sharp one-line summary (max 12 words)",
  "verdict": "2-3 sentence conclusion. State what is happening, what the evidence shows, and what it implies. Be direct.",
  "evidence": ["bullet 1", "bullet 2", "bullet 3"],
  "implications": "1-2 sentences on who this matters to and why — investors, journalists, regulators, etc.",
  "confidence": "{confidence}",
  "tier": "{tier}",
  "action_items": ["concrete thing reader should check or do", "another action item"]
}}

Do not include any text outside the JSON object. No markdown fences."""

        try:
            resp = requests.post(
                GROQ_URL,
                headers={
                    'Authorization': f'Bearer {GROQ_API_KEY}',
                    'Content-Type':  'application/json',
                },
                json={
                    'model':       'llama-3.3-70b-versatile',
                    'messages':    [
                        {'role': 'system', 'content': self.SYSTEM},
                        {'role': 'user',   'content': prompt},
                    ],
                    'temperature': 0.3,   # lower = more factual
                    'max_tokens':  800,
                },
                timeout=45,
            )
            if resp.status_code == 429 and _retry < 3:
                wait = 15 * (_retry + 1)
                self.log.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                return self.synthesise(post, _retry + 1)
            if not resp.ok:
                self.log.error(f"Groq error {resp.status_code}: {resp.text[:300]}")
                return None
            resp.raise_for_status()

            text = resp.json()['choices'][0]['message']['content'].strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            data = json.loads(text)

            brief = {
                'id':             str(uuid.uuid4()),
                'source_post_id': post.get('id', ''),
                'source_type':    post_type,
                'headline':       data.get('headline', ''),
                'verdict':        data.get('verdict', ''),
                'evidence':       data.get('evidence', []),
                'implications':   data.get('implications', ''),
                'action_items':   data.get('action_items', []),
                'confidence':     data.get('confidence', confidence),
                'tier':           data.get('tier', tier),
                'citizens':       citizens,
                'tags':           post.get('tags', []),
                'created_at':     datetime.utcnow().isoformat(),
                'published':      False,
            }
            self.log.info(f"Brief generated: [{brief['confidence']}] {brief['headline']}")
            return brief

        except Exception as e:
            self.log.error(f"synthesise() failed [{type(e).__name__}]: {e}")
            return None

    def run_on_unprocessed(self, db):
        """Find all signal alerts and town halls without a brief and process them."""
        try:
            unprocessed = db.get_unprocessed_posts()
            self.log.info(f"Found {len(unprocessed)} unprocessed posts")
            briefs = []
            for post in unprocessed:
                brief = self.synthesise(post)
                if brief:
                    db.save_brief(brief)
                    briefs.append(brief)
                    time.sleep(3)  # pace Groq calls
            self.log.info(f"ORACLE produced {len(briefs)} briefs")
            return briefs
        except Exception as e:
            self.log.error(f"run_on_unprocessed failed: {e}")
            return []

"""
agents/oracle.py — ORACLE, The Signal Synthesiser

ORACLE reads Council Sessions (pre-debated by AXIOM, DOUBT, LACUNA) from the database,
analyses the structured debate, and produces intelligence briefs.

Flow: Signal Alert/Town Hall -> Council debates -> Council Session saved -> ORACLE reads session -> Brief
"""

import os, json, logging, uuid
import requests
from datetime import datetime

# Use token_budget if available, fall back to direct key
try:
    from agents.token_budget import get_key, can_spend, record_spend
    HAS_TOKEN_BUDGET = True
except ImportError:
    HAS_TOKEN_BUDGET = False

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'

def _get_key():
    if HAS_TOKEN_BUDGET:
        return get_key()
    return os.environ.get('GROQ_API_KEY', '')

log = logging.getLogger('ORACLE')


class OracleAgent:
    name      = 'ORACLE'
    title     = 'The Signal Synthesiser'
    color     = '#F0C040'

    SYSTEM = """You are ORACLE, the intelligence synthesis layer of The Signal Society.

You receive pre-processed Council Sessions containing structured debates between three voices:
- AXIOM (argues for the strongest signal)
- DOUBT (stress-tests the claims)
- LACUNA (maps what's missing)

Your job is to:
1. Assess the credibility and significance of the convergence
2. Synthesise the Council's debate into a coherent intelligence brief
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

    def synthesise_from_council(self, session):
        """Take a council session and produce an intelligence brief."""

        source_post_id = session.get('source_post_id', '')
        source_type    = session.get('source_type', '')
        topic          = session.get('topic', '')
        exchanges      = session.get('exchanges', [])
        consensus      = session.get('consensus', '')
        dissent        = session.get('dissent', '')
        gaps           = session.get('gaps', [])
        tags           = session.get('tags', [])

        # Build council debate content
        debate_content = f"""COUNCIL SESSION: {topic}
Source Type: {source_type}
Tags: {', '.join(tags)}

COUNCIL DEBATE:
"""
        for ex in exchanges:
            member = ex.get('member', '')
            role = ex.get('role', '')
            text = ex.get('text', '')
            debate_content += f"\n[{member} - {role}]:\n{text}\n"

        debate_content += f"\n\nCONSENSUS (AXIOM):\n{consensus}\n"
        debate_content += f"\nDISSENT (DOUBT):\n{dissent}\n"
        debate_content += f"\nGAPS (LACUNA):\n" + "\n".join(f"- {g}" for g in gaps[:4])

        # Determine confidence based on source type and gaps
        num_gaps = len([g for g in gaps if len(g) > 10])
        if num_gaps <= 1:
            confidence = 'HIGH'
        elif num_gaps <= 2:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        if source_type == 'signal_alert' and confidence == 'MEDIUM':
            confidence = 'HIGH'

        tier = 'premium' if confidence in ('HIGH', 'CONFIRMED') else 'free'

        prompt = f"""Analyse this Council debate and produce a structured intelligence brief.

The Council has already debated this signal. Your job is to synthesise their analysis into a final brief.

{debate_content}

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
            key = _get_key()
            if not key:
                self.log.warning("No Groq API key available")
                return None

            if HAS_TOKEN_BUDGET and not can_spend('oracle', 700):
                self.log.warning("Token budget exhausted for ORACLE")
                return None

            resp = requests.post(
                GROQ_URL,
                headers={
                    'Authorization': f'Bearer {key}',
                    'Content-Type':  'application/json',
                },
                json={
                    'model':       'llama-3.3-70b-versatile',
                    'messages':    [
                        {'role': 'system', 'content': self.SYSTEM},
                        {'role': 'user',   'content': prompt},
                    ],
                    'temperature': 0.3,
                    'max_tokens':  600,
                },
                timeout=30,
            )

            if resp.status_code == 429:
                self.log.warning("Rate limited, skipping to save tokens")
                if HAS_TOKEN_BUDGET:
                    try:
                        from agents.token_budget import rotate_key
                        rotate_key()
                    except Exception:
                        pass
                return None

            if not resp.ok:
                self.log.error(f"Groq error {resp.status_code}: {resp.text[:300]}")
                return None

            resp.raise_for_status()

            if HAS_TOKEN_BUDGET:
                usage = resp.json().get('usage', {})
                record_spend('oracle', usage.get('total_tokens', 600))

            text = resp.json()['choices'][0]['message']['content'].strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            data = json.loads(text)

            brief = {
                'id':             str(uuid.uuid4()),
                'source_post_id': source_post_id,
                'source_type':    source_type,
                'headline':       data.get('headline', ''),
                'verdict':        data.get('verdict', ''),
                'evidence':       data.get('evidence', []),
                'implications':   data.get('implications', ''),
                'action_items':   data.get('action_items', []),
                'confidence':     data.get('confidence', confidence),
                'tier':           data.get('tier', tier),
                'citizens':       [],
                'tags':           tags,
                'created_at':     datetime.utcnow().isoformat(),
                'published':      False,
            }
            self.log.info(f"Brief generated: [{brief['confidence']}] {brief['headline'][:60]}")
            return brief

        except Exception as e:
            self.log.error(f"synthesise_from_council() failed [{type(e).__name__}]: {e}")
            return None

    def run_on_unprocessed(self, db):
        """Find all unprocessed council sessions and synthesise briefs from them."""
        try:
            unprocessed = db.get_unprocessed_council_sessions()
            self.log.info(f"Found {len(unprocessed)} unprocessed council sessions")

            MAX_ITEMS = 3
            to_process = unprocessed[:MAX_ITEMS]
            self.log.info(f"Will process {len(to_process)} sessions this run (max: {MAX_ITEMS})")

            briefs = []
            for session in to_process:
                brief = self.synthesise_from_council(session)
                if brief:
                    try:
                        db.save_brief(brief)
                        db.mark_council_processed(session['id'])
                        briefs.append(brief)
                        self.log.info(f"Created brief: {brief.get('headline', '')[:60]}...")
                    except Exception as save_err:
                        self.log.error(f"Failed to save brief: {save_err}")
                else:
                    self.log.warning("Synthesis returned None, skipping")

            self.log.info(f"ORACLE produced {len(briefs)} briefs from council sessions")
            return briefs

        except Exception as e:
            self.log.error(f"run_on_unprocessed failed: {e}")
            import traceback
            self.log.error(traceback.format_exc())
            return []

    # Legacy method - kept for backwards compatibility
    def synthesise(self, post, _retry=0):
        """Legacy method - creates a minimal council session and processes it."""
        self.log.warning("synthesise() called directly - should use council flow")
        session = {
            'source_post_id': post.get('id', ''),
            'source_type': post.get('type', ''),
            'topic': post.get('headline') or post.get('topic', 'Unknown'),
            'exchanges': [
                {'member': 'AXIOM', 'role': 'Signal Maximalist', 'text': f"Signal: {post.get('body', '')[:200]}"}
            ],
            'consensus': post.get('body', '')[:300],
            'dissent': 'No counter-arguments recorded.',
            'gaps': ['Source verification needed.'],
            'tags': post.get('tags', []),
        }
        return self.synthesise_from_council(session)

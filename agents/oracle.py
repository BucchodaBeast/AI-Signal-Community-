"""
agents/oracle.py — ORACLE, The Signal Synthesiser

ORACLE sits above the Council. It does not fetch data from the web or raw posts.
Instead it reads Council Sessions (pre-debated by AXIOM, DOUBT, LACUNA) from the database,
analyses the structured debate, and produces intelligence briefs.

Flow: Signal Alert/Town Hall → Council debates → Council Session saved → ORACLE reads session → Brief

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

def _groq_key():
    try:
        from agents.token_budget import get_key
        return get_key()
    except Exception:
        return os.environ.get('GROQ_API_KEY', '')
GROQ_URL     = 'https://api.groq.com/openai/v1/chat/completions'

log = logging.getLogger('ORACLE')

# Rate limit protection - track daily usage
_daily_token_count = 0
_daily_token_reset = datetime.now().date()
MAX_DAILY_TOKENS = 80000  # Stay under 100K limit with buffer
MAX_ITEMS_PER_RUN = 3     # Process max 3 council sessions per run


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
- Consider AXIOM's argument, DOUBT's counter, and LACUNA's gaps holistically
- Confidence levels: LOW (1 agent), MEDIUM (2 agents), HIGH (3 agents), CONFIRMED (4+)
- Premium tier = HIGH or CONFIRMED confidence only
- Write for an audience of analysts, investors, and journalists
- Be concise, precise, and direct — no filler
"""

    def __init__(self):
        self.log = logging.getLogger(self.name)
        self._rate_limited = False
        self._rate_limit_until = 0

    def _check_rate_limit_budget(self, estimated_tokens=800):
        """Check if we have budget for this API call."""
        global _daily_token_count, _daily_token_reset
        
        # Reset counter if it's a new day
        today = datetime.now().date()
        if today != _daily_token_reset:
            _daily_token_count = 0
            _daily_token_reset = today
            self._rate_limited = False
        
        # Check if we're in a cooldown period from a 429 error
        if self._rate_limited and time.time() < self._rate_limit_until:
            remaining = int(self._rate_limit_until - time.time())
            self.log.warning(f"Rate limit cooldown active. Retry in {remaining}s")
            return False
        
        # Check daily token budget
        if _daily_token_count + estimated_tokens > MAX_DAILY_TOKENS:
            self.log.warning(f"Daily token budget nearly exhausted ({_daily_token_count}/{MAX_DAILY_TOKENS}). Skipping.")
            return False
        
        return True

    def _update_token_count(self, response):
        """Update token count from API response."""
        global _daily_token_count
        try:
            usage = response.get('usage', {})
            tokens = usage.get('total_tokens', 800)
            _daily_token_count += tokens
            self.log.debug(f"Token usage: {tokens}, daily total: {_daily_token_count}")
        except:
            # Estimate if we can't get actual count
            _daily_token_count += 800

    def synthesise_from_council(self, session, _retry=0):
        """Take a council session and produce an intelligence brief. NO RETRIES."""
        
        # Check rate limit budget before attempting
        if not self._check_rate_limit_budget(estimated_tokens=700):
            return None

        source_post_id = session.get('source_post_id', '')
        source_type    = session.get('source_type', '')
        topic          = session.get('topic', '')
        exchanges      = session.get('exchanges', [])
        consensus      = session.get('consensus', '')
        dissent        = session.get('dissent', '')
        gaps           = session.get('gaps', [])
        tags           = session.get('tags', [])

        # Extract citizen info from exchanges
        citizens = []
        for ex in exchanges:
            # Council members are AXIOM, DOUBT, LACUNA - we need original agents
            # The session should have this info, but we'll infer from tags/context
            pass
        
        # For now, extract from tags if they contain agent references
        # or use empty list - the brief will still work
        
        # Build council debate content
        debate_content = f"""
COUNCIL SESSION: {topic}
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
        
        # Boost confidence if it's a signal_alert (multi-agent convergence)
        if source_type == 'signal_alert' and confidence == 'MEDIUM':
            confidence = 'HIGH'
        
        tier = 'premium' if confidence in ('HIGH',) else 'free'  # Only HIGH -> premium

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
            resp = requests.post(
                GROQ_URL,
                headers={
                    'Authorization': f'Bearer {_groq_key()}',
                    'Content-Type':  'application/json',
                },
                json={
                    'model':       'llama-3.3-70b-versatile',
                    'messages':    [
                        {'role': 'system', 'content': self.SYSTEM},
                        {'role': 'user',   'content': prompt},
                    ],
                    'temperature': 0.3,
                    'max_tokens':  600,  # Reduced to save tokens
                },
                timeout=30,
            )
            
            # NO RETRIES - skip on rate limit to save tokens
            if resp.status_code == 429:
                self.log.warning("Oracle rate limited — rotating key.")
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
            
            # Update token count
            self._update_token_count(resp.json())

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
                'citizens':       [],  # Council doesn't track original agents, but that's OK
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
        """Find all unprocessed council sessions and synthesise briefs from them. NO RETRIES."""
        global _daily_token_count, _daily_token_reset
        
        # Reset counter if it's a new day
        today = datetime.now().date()
        if today != _daily_token_reset:
            _daily_token_count = 0
            _daily_token_reset = today
            self._rate_limited = False
        
        # Check if we have budget before starting
        if _daily_token_count > MAX_DAILY_TOKENS * 0.9:
            self.log.warning(f"Daily token budget nearly exhausted ({_daily_token_count}/{MAX_DAILY_TOKENS}). Skipping ORACLE run.")
            return []
        
        try:
            # Get unprocessed council sessions (not posts directly)
            unprocessed = db.get_unprocessed_council_sessions()
            self.log.info(f"Found {len(unprocessed)} unprocessed council sessions")
            
            # Limit to max items per run to control rate limits
            to_process = unprocessed[:MAX_ITEMS_PER_RUN]
            self.log.info(f"Will process {len(to_process)} sessions this run (max: {MAX_ITEMS_PER_RUN})")
            
            briefs = []
            for session in to_process:
                # Check budget before each item
                if _daily_token_count > MAX_DAILY_TOKENS * 0.9:
                    self.log.warning(f"Daily budget nearly exhausted. Stopping after {len(briefs)} briefs.")
                    break
                
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
                
                # Sleep between briefs
                time.sleep(2)
            
            self.log.info(f"ORACLE produced {len(briefs)} briefs from council sessions")
            return briefs
            
        except Exception as e:
            self.log.error(f"run_on_unprocessed failed: {e}")
            import traceback
            self.log.error(traceback.format_exc())
            return []

    # Legacy method - kept for backwards compatibility but redirects to council flow
    def synthesise(self, post, _retry=0):
        """Legacy method - now creates a minimal council session and processes it."""
        self.log.warning("synthesise() called directly on post - should use council flow. Creating minimal session.")
        
        # Create a minimal session structure from the post
        session = {
            'source_post_id': post.get('id', ''),
            'source_type': post.get('type', ''),
            'topic': post.get('headline') or post.get('topic', 'Unknown'),
            'exchanges': [
                {'member': 'AXIOM', 'role': 'Signal Maximalist', 'text': f"Signal detected: {post.get('body', '')[:200]}"}
            ],
            'consensus': post.get('body', '')[:300],
            'dissent': 'No counter-arguments recorded.',
            'gaps': ['Source verification needed.'],
            'tags': post.get('tags', []),
        }
        
        return self.synthesise_from_council(session, _retry)

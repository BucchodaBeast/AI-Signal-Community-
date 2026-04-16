"""
agents/council.py — THE COUNCIL
================================
Three autonomous voices that debate Signal Alerts and Town Halls
before ORACLE synthesises them into briefs.

AXIOM  — finds the strongest signal in the data, argues for its significance
DOUBT  — devil's advocate, stress-tests every claim, finds the weakest link
LACUNA — maps what's missing, what hasn't been checked, what the data can't see

Flow:
  Signal Alert / Town Hall → Council debates it → council_session saved →
  ORACLE reads council_session → produces brief

The Council's debate gives ORACLE structured, pre-processed material
instead of raw agent posts, making briefs dramatically better.
"""

import os, json, logging, uuid, time
import requests
from datetime import datetime

from agents.token_budget import can_spend, record_spend

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL     = 'https://api.groq.com/openai/v1/chat/completions'

log = logging.getLogger('COUNCIL')

MAX_ITEMS_PER_RUN = 2     # Max posts debated per run

COUNCIL_MEMBERS = {
    'AXIOM': {
        'role':   'The Signal Maximalist',
        'system': """You are AXIOM, a member of The Council of The Signal Society.
Your role: Find the single strongest, most credible signal in the data presented.
Argue for its significance. Cut through noise to the one thing that matters most.
Be direct and confident. Never hedge more than once. Max 3 sentences.""",
    },
    'DOUBT': {
        'role':   'The Devil\'s Advocate',
        'system': """You are DOUBT, a member of The Council of The Signal Society.
Your role: Stress-test every claim in the data presented. Find the weakest link.
What could explain this differently? What assumption is being made? What's the base rate?
Be rigorous, not cynical. Max 3 sentences.""",
    },
    'LACUNA': {
        'role':   'The Gap Finder',
        'system': """You are LACUNA, a member of The Council of The Signal Society.
Your role: Map what's missing. What data hasn't been checked? What source wasn't consulted?
What would change the conclusion if it existed? Name specific gaps, not vague uncertainty.
Max 3 sentences.""",
    },
}


def _groq(system, prompt):
    """Single Groq call — returns text or None."""
    if not can_spend('council', 300):
        log.warning("Council token budget exhausted. Skipping call.")
        return None
    try:
        resp = requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'},
            json={
                'model':       'llama-3.3-70b-versatile',
                'messages':    [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': prompt},
                ],
                'temperature': 0.6,
                'max_tokens':  250,
            },
            timeout=25,
        )
        if resp.status_code == 429:
            log.warning("Council rate limited — skipping.")
            return None
        resp.raise_for_status()
        data   = resp.json()
        tokens = data.get('usage', {}).get('total_tokens', 300)
        record_spend('council', tokens)
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.error(f'Council Groq call failed: {e}')
        return None

def _build_source_summary(post):
    """Condense a signal_alert or town_hall into a prompt-safe summary."""
    ptype     = post.get('type', '')
    citizens  = post.get('citizens') or []
    tags      = post.get('tags') or []

    if ptype == 'signal_alert':
        thread   = post.get('thread') or []
        thread_t = '\n'.join(f"  [{e.get('citizen','')}] {e.get('text','')[:180]}" for e in thread[:3])  # Reduced from 4
        return (
            f"TYPE: Signal Alert — {len(citizens)}-way convergence\n"
            f"HEADLINE: {post.get('headline','')}\n"
            f"SUMMARY: {post.get('body','')[:300]}\n"  # Truncated
            f"CONTRIBUTING AGENTS: {', '.join(citizens)}\n"
            f"THREAD:\n{thread_t}\n"
            f"TAGS: {', '.join(tags)}"
        )
    elif ptype == 'town_hall':
        positions = post.get('positions') or []
        pos_t = '\n'.join(
            f"  [{p.get('citizen','')} / {p.get('stance','')}] {p.get('text','')[:180]}"
            for p in positions
        )
        return (
            f"TYPE: Town Hall Debate\n"
            f"TOPIC: {post.get('topic','')}\n"
            f"POSITIONS:\n{pos_t}\n"
            f"TAGS: {', '.join(tags)}"
        )
    return f"TYPE: {ptype}\nBODY: {post.get('body','')[:350]}"


class CouncilAgent:
    """
    Runs a structured 3-voice debate on a signal_alert or town_hall post
    and saves a council_session for ORACLE to consume.
    """
    name  = 'COUNCIL'
    title = 'The Council'
    color = '#8B7355'

    def __init__(self):
        self.log = logging.getLogger(self.name)
        self._rate_limited = False

    def debate(self, post):
        """
        Run AXIOM → DOUBT → LACUNA in sequence, each seeing the previous
        member's response, then produce a structured council_session.
        """
        global _daily_token_count, _daily_token_reset
        
        # Reset counter if it's a new day
        today = datetime.now().date()
        if today != _daily_token_reset:
            _daily_token_count = 0
            _daily_token_reset = today
            self._rate_limited = False
        
        # Check if we have budget for 3 API calls (~900 tokens)
        if _daily_token_count + 900 > MAX_DAILY_TOKENS:
            self.log.warning(f"Insufficient token budget for full debate. Skipping.")
            return None
        
        source   = _build_source_summary(post)
        topic    = post.get('headline') or post.get('topic') or 'Unknown signal'
        tags     = post.get('tags') or []

        exchanges = []
        context   = source  # grows with each exchange

        # Round 1 — AXIOM argues for the strongest signal
        axiom_prompt = (
            f"Here is intelligence from the field:\n\n{context}\n\n"
            "What is the single strongest, most credible signal here? Argue for its significance."
        )
        axiom_text = _groq(COUNCIL_MEMBERS['AXIOM']['system'], axiom_prompt)
        if not axiom_text:
            self.log.error(f"AXIOM failed on {post.get('id','?')}")
            return None
        exchanges.append({'member': 'AXIOM', 'role': COUNCIL_MEMBERS['AXIOM']['role'], 'text': axiom_text})
        time.sleep(3)  # Increased from 2s to be safer

        # Round 2 — DOUBT stress-tests AXIOM's argument
        context += f"\n\nAXIOM argues: {axiom_text}"
        doubt_prompt = (
            f"Here is intelligence from the field:\n\n{source}\n\n"
            f"AXIOM argues the strongest signal is:\n{axiom_text}\n\n"
            "Stress-test this. What's the weakest assumption? What alternative explanation exists?"
        )
        doubt_text = _groq(COUNCIL_MEMBERS['DOUBT']['system'], doubt_prompt)
        if not doubt_text:
            self.log.error(f"DOUBT failed on {post.get('id','?')}")
            return None
        exchanges.append({'member': 'DOUBT', 'role': COUNCIL_MEMBERS['DOUBT']['role'], 'text': doubt_text})
        time.sleep(3)

        # Round 3 — LACUNA maps what's missing
        lacuna_prompt = (
            f"Here is intelligence from the field:\n\n{source}\n\n"
            f"AXIOM says: {axiom_text}\n"
            f"DOUBT counters: {doubt_text}\n\n"
            "What critical data is missing from this picture? Name specific sources not yet checked."
        )
        lacuna_text = _groq(COUNCIL_MEMBERS['LACUNA']['system'], lacuna_prompt)
        if not lacuna_text:
            self.log.error(f"LACUNA failed on {post.get('id','?')}")
            return None
        exchanges.append({'member': 'LACUNA', 'role': COUNCIL_MEMBERS['LACUNA']['role'], 'text': lacuna_text})
        time.sleep(3)

        # Determine consensus and dissent from the exchange
        # AXIOM's core claim = consensus; DOUBT's counter = dissent; LACUNA's gaps = gaps
        gaps = [g.strip() for g in lacuna_text.replace(';', '.').split('.') if len(g.strip()) > 20][:3]  # Reduced from 4

        session = {
            'id':             str(uuid.uuid4()),
            'source_post_id': post.get('id', ''),
            'source_type':    post.get('type', ''),
            'topic':          topic,
            'exchanges':      exchanges,
            'consensus':      axiom_text,
            'dissent':        doubt_text,
            'gaps':           gaps,
            'tags':           tags,
            'created_at':     datetime.utcnow().isoformat(),
            'processed':      False,
        }

        self.log.info(f"Council session created for: {topic[:60]}")
        return session

    def run_on_unprocessed(self, db):
        """
        Find Signal Alerts and Town Halls without a council session yet,
        debate each one, save sessions. ORACLE will pick these up next.
        """
        global _daily_token_count, _daily_token_reset
        
        # Reset counter if it's a new day
        today = datetime.now().date()
        if today != _daily_token_reset:
            _daily_token_count = 0
            _daily_token_reset = today
            self._rate_limited = False
        
        # Check if we have budget before starting (need ~750 tokens per item)
        estimated_needed = MAX_ITEMS_PER_RUN * 750
        if _daily_token_count + estimated_needed > MAX_DAILY_TOKENS:
            self.log.warning(f"Insufficient token budget for Council run ({_daily_token_count}/{MAX_DAILY_TOKENS}). Skipping.")
            return []
        
        try:
            # Find posts that don't have a council session yet
            all_posts = db.get_unprocessed_posts()
            self.log.info(f"Found {len(all_posts)} unprocessed signal alerts/town halls")
            
            # Get existing session source_post_ids to avoid duplicates
            existing_sessions = db.get_council_sessions(limit=200)
            processed_ids = {s['source_post_id'] for s in existing_sessions if s.get('source_post_id')}
            self.log.info(f"Existing council sessions: {len(existing_sessions)}, processed IDs: {len(processed_ids)}")
            
            pending = [p for p in all_posts if p['id'] not in processed_ids]
            self.log.info(f"Found {len(pending)} posts needing Council debate")
            
            # Limit to max items per run to control rate limits
            to_process = pending[:MAX_ITEMS_PER_RUN]
            self.log.info(f"Will debate {len(to_process)} posts this run (max: {MAX_ITEMS_PER_RUN})")
            
            sessions = []
            for post in to_process:
                # Check budget before each debate
                if _daily_token_count + 750 > MAX_DAILY_TOKENS:
                    self.log.warning(f"Daily budget nearly exhausted. Stopping after {len(sessions)} sessions.")
                    break
                
                session = self.debate(post)
                if session:
                    # Save session to database
                    try:
                        session_id = db.save_council_session(session)
                        if session_id:
                            self.log.info(f"Saved council session: {session_id}")
                            sessions.append(session)
                        else:
                            self.log.error("Failed to save council session - save_council_session returned None")
                    except Exception as save_err:
                        self.log.error(f"Failed to save council session: {save_err}")
                else:
                    self.log.warning("Debate returned None, skipping save")
                
                # Sleep between debates
                time.sleep(3)

            self.log.info(f"Council produced {len(sessions)} session(s)")
            return sessions
        except Exception as e:
            self.log.error(f"run_on_unprocessed failed: {e}")
            import traceback
            self.log.error(traceback.format_exc())
            return []

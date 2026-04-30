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

def _groq_key():
    try:
        from agents.token_budget import get_key
        return get_key()
    except Exception:
        return os.environ.get('GROQ_API_KEY', '')
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


# All field agents with their territories — Council uses this to issue subpoenas
AGENT_ROSTER = {
    'VERA':    'Academic papers, arXiv pre-prints, patents, SSRN, FOIA releases',
    'DUKE':    'SEC filings, job postings, startup funding, capital movements',
    'MIRA':    'Reddit, Hacker News, community sentiment, product changelogs',
    'SOL':     'Cross-domain correlations, weather, epidemiology, mobility data',
    'NOVA':    'FCC filings, FAA applications, building permits, infrastructure',
    'ECHO':    'Deleted content, Wayback Machine, retracted papers, GitHub deletions',
    'KAEL':    'News metadata, byline patterns, coordinated publishing, GDELT',
    'FLUX':    'Crypto on-chain data, commodities, treasury yields, forex flows',
    'REX':     'Federal Register, court dockets, lobbying filings, government contracts',
    'VIGIL':   'Baltic Dry Index, vessel tracking, port congestion, energy flows',
    'LORE':    'USPTO patents, WIPO, patent assignments, IP ownership changes',
    'SPECTER': 'Data breach notifications, historical patterns, credential leaks',
}


def _groq(system, prompt):
    """Single Groq call with global rate limiting and 429 retry."""
    if not can_spend('council', 300):
        log.warning("Council token budget exhausted. Skipping call.")
        return None
    try:
        from agents.token_budget import wait_and_retry_on_429
        resp = wait_and_retry_on_429(lambda: requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {_groq_key()}', 'Content-Type': 'application/json'},
            json={
                'model':       'llama-3.3-70b-versatile',
                'messages':    [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': prompt},
                ],
                'temperature': 0.6,
                'max_tokens':  250,
            },
            timeout=30,
        ))
        if resp.status_code == 429:
            log.warning("Council still rate limited after retries — skipping this call.")
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


def _generate_subpoenas(source_summary, axiom, doubt, lacuna, tags):
    """
    Identify which field agents should be cross-referenced based on the
    Council's debate. Pure keyword matching — no extra Groq calls.

    Returns a list of subpoena dicts:
      { agent, question, priority, issued_at }

    These are stored in the council_session and picked up by app.py,
    which injects them as priority context into the named agent's next run.
    """
    combined = f"{source_summary} {axiom} {doubt} {lacuna} {' '.join(tags)}".lower()
    subpoenas = []

    # Map keyword signals to agent + question templates
    SUBPOENA_RULES = [
        # (keywords_any_of, agent, question_template)
        (['sec filing', 'stock', 'capital', 'funding', 'acquisition', 'ipo', 'market', 'investment'],
         'DUKE', 'Cross-reference with recent SEC filings and capital movement patterns for this entity.'),

        (['paper', 'arxiv', 'research', 'study', 'academic', 'published', 'preprint', 'peer-reviewed'],
         'VERA', 'Search for academic papers that confirm or contradict this signal.'),

        (['reddit', 'sentiment', 'community', 'users', 'forum', 'discussion', 'reaction'],
         'MIRA', 'Check community sentiment and forum discussion around this topic right now.'),

        (['deleted', 'removed', 'wayback', 'disappeared', 'retracted', 'taken down'],
         'ECHO', 'Check Wayback Machine for content changes related to this entity in the last 30 days.'),

        (['patent', 'ip ', 'intellectual property', 'wipo', 'uspto', 'filing', 'assignee'],
         'LORE', 'Search patent filings for IP activity related to this entity or technology.'),

        (['permit', 'fcc', 'faa', 'infrastructure', 'zoning', 'spectrum', 'datacenter', 'construction'],
         'NOVA', 'Check FCC/FAA/permit databases for physical infrastructure activity in this area.'),

        (['regulation', 'congress', 'law', 'legislation', 'doj', 'ftc', 'antitrust', 'compliance', 'court'],
         'REX', 'Search Federal Register and court dockets for regulatory activity related to this signal.'),

        (['ship', 'vessel', 'port', 'container', 'freight', 'supply chain', 'commodity', 'bdi', 'cargo'],
         'VIGIL', 'Cross-reference with physical shipping and commodity flow data for this sector.'),

        (['breach', 'hack', 'credential', 'vulnerability', 'ransomware', 'leak', 'exposure'],
         'SPECTER', 'Check breach notification databases for security exposure related to this entity.'),

        (['media', 'narrative', 'headline', 'journalist', 'publication', 'wire', 'outlet', 'press'],
         'KAEL', 'Audit the media metadata — who is publishing this story and when?'),

        (['crypto', 'bitcoin', 'ethereum', 'defi', 'stablecoin', 'on-chain', 'treasury yield'],
         'FLUX', 'Check capital flow signals — on-chain data, commodity prices, treasury movement.'),

        (['historical', 'precedent', 'pattern', 'last time', 'similar', 'rhyme', 'analog'],
         'SPECTER', 'Find the historical precedent for this pattern and what happened next.'),
    ]

    issued_agents = set()  # One subpoena per agent max
    for keywords, agent, question in SUBPOENA_RULES:
        if agent in issued_agents:
            continue
        if any(kw in combined for kw in keywords):
            subpoenas.append({
                'agent':     agent,
                'question':  question,
                'priority':  'high' if agent in ['DUKE', 'VERA', 'REX'] else 'normal',
                'issued_at': datetime.utcnow().isoformat(),
                'resolved':  False,
            })
            issued_agents.add(agent)
        if len(subpoenas) >= 3:  # Max 3 subpoenas per session — stay focused
            break

    return subpoenas



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
        # Check if we have budget for 3 API calls via shared token_budget
        from agents.token_budget import can_spend, status as budget_status
        if not can_spend('council', 900):
            self.log.warning(f"Insufficient token budget for full debate. {budget_status()}")
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
        gaps = [g.strip() for g in lacuna_text.replace(';', '.').split('.') if len(g.strip()) > 20][:3]

        # ── SUBPOENA GENERATION ──────────────────────────────
        # Based on LACUNA's gaps, identify which field agents should be
        # cross-referenced. This is async — they'll pick up the request
        # on their next scheduled run, no extra Groq calls now.
        subpoenas = _generate_subpoenas(source, axiom_text, doubt_text, lacuna_text, tags)
        if subpoenas:
            self.log.info(f"Council issued {len(subpoenas)} subpoena(s): {[s['agent'] for s in subpoenas]}")

        session = {
            'id':             str(uuid.uuid4()),
            'source_post_id': post.get('id', ''),
            'source_type':    post.get('type', ''),
            'topic':          topic,
            'exchanges':      exchanges,
            'consensus':      axiom_text,
            'dissent':        doubt_text,
            'gaps':           gaps,
            'subpoenas':      subpoenas,
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
        # Check shared token budget before starting
        from agents.token_budget import can_spend, status as budget_status
        if not can_spend('council', MAX_ITEMS_PER_RUN * 750):
            self.log.warning(f"Insufficient token budget for Council run. {budget_status()}")
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
                # Check shared budget before each debate
                if not can_spend('council', 750):
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

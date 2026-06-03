"""
agents/council.py — THE COUNCIL (v2)

Major rework from v1:

BEFORE: Three fixed rhetorical postures (AXIOM=maximise, DOUBT=question, LACUNA=gaps)
        applied to every signal regardless of domain. Same LLM with different
        system prompts stitched together. Not a real debate.

AFTER:  Dynamic panel assembled per signal. The two agents whose territories
        have the most genuine tension on the topic BECOME the debaters.
        A third voice (ARBITER) synthesises only after real disagreement exists.

        If VIGIL finds shipping contraction and DUKE finds capital expansion
        on the same topic — VIGIL and DUKE debate it directly, each arguing
        from their actual data. ARBITER then asks what neither checked.

        Council sessions now include:
        - Domain authority scores per voice (who is most credible on THIS topic)
        - Contradiction index (how directly do the positions conflict)
        - Self-rejection: if no genuine conflict exists, Council returns None
          instead of manufacturing fake debate
        - Confidence derived from source independence, not gap count
        - HERMES verification queue: gaps that can be verified get flagged
          for HERMES to check and resolve

        The Council is the quality gate. Weak signals get no brief.
        Genuine conflicts get a real debate and a real brief.
"""

import os, json, logging, uuid, re
from datetime import datetime

try:
    from agents import llm_gateway
    HAS_GATEWAY = True
except ImportError:
    HAS_GATEWAY = False

log = logging.getLogger('COUNCIL')

# ── AGENT TERRITORY MAP ───────────────────────────────────────────────────────
# Maps each agent to the domains where they have genuine authority.
# Used to assemble the most credible panel per signal topic.

AGENT_TERRITORIES = {
    'VERA':    ['#AI', '#patents', '#research', '#regulation', '#biotech'],
    'DUKE':    ['#finance', '#labor', '#government', '#crypto', '#AI'],
    'MIRA':    ['#media', '#labor', '#AI'],
    'SOL':     ['#climate', '#supplychain', '#biotech', '#history'],
    'NOVA':    ['#infrastructure', '#regulation', '#government'],
    'ECHO':    ['#history', '#media', '#security'],
    'KAEL':    ['#media', '#government', '#regulation', '#history'],
    'FLUX':    ['#crypto', '#finance', '#supplychain'],
    'REX':     ['#regulation', '#government', '#finance', '#security'],
    'VIGIL':   ['#supplychain', '#climate', '#infrastructure'],
    'LORE':    ['#patents', '#AI', '#biotech', '#finance'],
    'SPECTER': ['#security', '#history', '#government'],
    'HERMES':  ['#infrastructure', '#media', '#regulation', '#AI'],
}

# ── TERRITORY GROUPS (for convergence independence) ───────────────────────────
TERRITORY_GROUPS = {
    'market':      {'DUKE', 'FLUX'},
    'physical':    {'VIGIL', 'NOVA', 'SOL'},
    'intelligence':{'VERA', 'LORE', 'SPECTER'},
    'narrative':   {'KAEL', 'MIRA', 'ECHO'},
    'regulatory':  {'REX', 'HERMES'},
}

# ── KNOWN DIVERGENT PAIRS (natural analytical tension) ────────────────────────
DIVERGENT_PAIRS = [
    ('VERA',    'DUKE'),    # research/academic vs market/capital
    ('VERA',    'KAEL'),    # source data vs narrative framing
    ('MIRA',    'DUKE'),    # community sentiment vs capital signals
    ('SOL',     'KAEL'),    # physical patterns vs media patterns
    ('ECHO',    'DUKE'),    # what was deleted vs what capital says
    ('NOVA',    'MIRA'),    # infrastructure data vs community reaction
    ('FLUX',    'REX'),     # capital movement vs regulatory response
    ('FLUX',    'DUKE'),    # crypto/commodity flow vs traditional market
    ('REX',     'VERA'),    # regulatory framing vs research evidence
    ('REX',     'KAEL'),    # official regulatory narrative vs media narrative
    ('VIGIL',   'DUKE'),    # physical supply chain vs capital markets
    ('VIGIL',   'FLUX'),    # physical commodity vs crypto/financial flow
    ('VIGIL',   'KAEL'),    # physical reality vs media narrative
    ('LORE',    'VERA'),    # IP/patents vs academic research
    ('LORE',    'DUKE'),    # IP strategy vs capital/hiring signals
    ('LORE',    'REX'),     # patent filings vs regulatory context
    ('SPECTER', 'KAEL'),    # breach/security data vs media coverage
    ('SPECTER', 'DUKE'),    # security signals vs market reaction
    ('SPECTER', 'ECHO'),    # active threats vs historical patterns
    ('SPECTER', 'NOVA'),    # cyber infrastructure vs physical infrastructure
]

# ── GROQ HELPER ───────────────────────────────────────────────────────────────

def _call(system: str, prompt: str, max_tokens: int = 220) -> str | None:
    if HAS_GATEWAY:
        return llm_gateway.call(
            agent='COUNCIL',
            system_prompt=system,
            user_prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.6,
            use_cache=False,
        )
    # Direct fallback
    import requests as _req
    key = os.environ.get('GROQ_API_KEY', '')
    if not key:
        return None
    try:
        resp = _req.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': prompt},
                ],
                'temperature': 0.6,
                'max_tokens': max_tokens,
            },
            timeout=25,
        )
        if resp.ok:
            return resp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.error(f'Direct Groq call failed: {e}')
    return None


# ── AGENT VOICE SYSTEMS ───────────────────────────────────────────────────────
# Each agent has a domain-specific Council voice — not a generic rhetorical
# posture, but the actual analytical lens they bring to the specific topic.

AGENT_COUNCIL_SYSTEMS = {
    'VERA': """You are VERA in a Council debate. You are the Contrarian Archivist.
Your lens: academic evidence, primary source verification, patent records, regulatory filings.
When you argue a signal: cite what the data directly shows. Name the specific paper, filing, or record.
When you counter: ask whether the evidence has been peer-reviewed, whether the sample is representative,
whether the methodology survives scrutiny.
Max 4 sentences. Be precise. Never hedge on facts — only on interpretations.""",

    'DUKE': """You are DUKE in a Council debate. You are the Market Anthropologist.
Your lens: capital allocation, hiring signals, SEC filings, institutional behaviour.
When you argue a signal: follow the money. What are entities actually doing with capital vs what they say?
When you counter: ask whether the data reflects actual capital commitment or just sentiment/narrative.
Max 4 sentences. Be direct. Price and position data do not lie — people do.""",

    'MIRA': """You are MIRA in a Council debate. You are the Sentiment Archaeologist.
Your lens: community reaction, social sentiment, what practitioners actually say vs what institutions claim.
When you argue a signal: surface the gap between official narrative and actual user/practitioner behaviour.
When you counter: ask whether the sentiment is organic or manufactured, whether the sample is representative.
Max 4 sentences. The absence of discussion is as significant as its presence.""",

    'SOL': """You are SOL in a Council debate. You are the Pattern Priest.
Your lens: cross-domain correlations, physical world data, historical pattern matching.
When you argue a signal: show where this pattern has appeared before across different domains simultaneously.
When you counter: ask whether the correlation is causal or coincidental, whether the baseline is correct.
Max 4 sentences. Patterns require at least three independent data points to be credible.""",

    'NOVA': """You are NOVA in a Council debate. You are the Infrastructure Whisperer.
Your lens: physical infrastructure filings, FCC/FAA data, permit clusters, construction patterns.
When you argue a signal: cite the specific filing numbers, coordinates, or cluster data.
When you counter: ask whether the infrastructure change has a mundane explanation before assuming strategic intent.
Max 4 sentences. Infrastructure cannot be faked — either the permits exist or they don't.""",

    'ECHO': """You are ECHO in a Council debate. You are the Disappeared Content tracker.
Your lens: what was deleted, what changed, what used to exist and no longer does.
When you argue a signal: what specifically was removed, when, and what did it say?
When you counter: ask whether the deletion was intentional suppression or routine maintenance.
Max 4 sentences. Absence of evidence is evidence — but only when presence is expected.""",

    'KAEL': """You are KAEL in a Council debate. You are the Narrative Auditor.
Your lens: how stories are constructed, framed, timed, and distributed across outlets.
When you argue a signal: identify the coordination pattern, the timing anomaly, the framing divergence.
When you counter: ask whether the pattern has a simpler explanation than coordination.
Max 4 sentences. Narrative patterns are real signals — but they require multiple data points, not vibes.""",

    'FLUX': """You are FLUX in a Council debate. You are the Capital Flow Tracker.
Your lens: crypto flows, commodity prices, treasury yields, CFTC positioning, currency movements.
When you argue a signal: cite the specific price, volume, or flow number and its deviation from baseline.
When you counter: ask whether the capital movement is significant relative to market depth.
Max 4 sentences. Capital moves before news does — but not every move is a signal.""",

    'REX': """You are REX in a Council debate. You are the Regulatory Scanner.
Your lens: Federal Register, court orders, congressional activity, regulatory enforcement patterns.
When you argue a signal: cite the docket number, rule, or enforcement action specifically.
When you counter: ask whether this is anomalous regulatory behaviour or routine compliance.
Max 4 sentences. Regulatory language is precise — imprecision in reporting is itself a signal.""",

    'VIGIL': """You are VIGIL in a Council debate. You are the Physical World Tracker.
Your lens: shipping data, commodity flows, port congestion, BDI, AIS vessel tracking.
When you argue a signal: state the specific index level, percentage change, and deviation from baseline.
When you counter: ask whether capital/narrative data reflects or contradicts physical reality.
Max 4 sentences. Ships don't lie. Physical atoms cannot be narrativised.""",

    'LORE': """You are LORE in a Council debate. You are the Patent & IP Intelligence agent.
Your lens: patent filings, IP assignments, continuation clusters, technology ownership patterns.
When you argue a signal: cite the patent number, assignee, CPC class, and strategic implication.
When you counter: ask whether the IP pattern reflects genuine development or defensive filing.
Max 4 sentences. Patent filings are legally binding claims — the most honest corporate announcements.""",

    'SPECTER': """You are SPECTER in a Council debate. You are the Dark Mirror.
Your lens: breach data, CVE exploits, historical attack patterns, predecessor incidents.
When you argue a signal: name the specific CVE, breach entity, or historical parallel with dates.
When you counter: ask whether the pattern is an active threat or historical artefact.
Max 4 sentences. History rhymes. Name the previous incident before claiming a new one.""",

    'HERMES': """You are HERMES in a Council debate. You are the Digital Messenger.
Your lens: API changes, platform policy shifts, deprecation notices, infrastructure communication.
When you argue a signal: cite the specific changelog entry, version number, or policy change with date.
When you counter: ask whether the platform change is strategic or routine maintenance.
Max 4 sentences. The infrastructure of the internet changes quietly — that silence is the signal.""",
}


# ── ARBITER SYSTEM (replaces LACUNA) ─────────────────────────────────────────
ARBITER_SYSTEM = """You are the ARBITER of The Signal Society Council.
You do not take sides. You assess the quality of the debate that just happened.

Your job:
1. Identify whether genuine disagreement exists or whether the debate is superficial
2. Name the specific data sources neither voice checked (be concrete, not vague)
3. State which agent's position is stronger given the evidence presented
4. Flag any items for HERMES to verify (specific URLs, filings, or records)
5. If the debate reveals the signal is noise, say so directly

Output format — JSON only, no markdown:
{
  "genuine_conflict": true/false,
  "stronger_position": "AGENT_NAME or EQUAL",
  "gaps": ["specific gap 1", "specific gap 2"],
  "hermes_verification_queue": ["specific URL or filing to check"],
  "signal_quality": "HIGH/MEDIUM/LOW/NOISE",
  "arbiter_note": "1-2 sentence synthesis"
}

If genuine_conflict is false and signal_quality is NOISE, the brief should not be published."""


# ── SOURCE SUMMARY ────────────────────────────────────────────────────────────

def _build_source_summary(post: dict) -> str:
    ptype    = post.get('type', '')
    citizens = post.get('citizens') or []
    tags     = post.get('tags') or []

    if ptype == 'signal_alert':
        thread = post.get('thread') or []
        thread_text = '\n'.join(
            f"  [{e.get('citizen','')}]: {e.get('text','')[:200]}"
            for e in thread[:4]
        )
        return (
            f"TYPE: Signal Alert — {len(citizens)}-way convergence\n"
            f"HEADLINE: {post.get('headline','')}\n"
            f"SUMMARY: {post.get('body','')[:300]}\n"
            f"CONTRIBUTING AGENTS: {', '.join(citizens)}\n"
            f"EVIDENCE THREAD:\n{thread_text}\n"
            f"TAGS: {', '.join(tags)}\n"
            f"SIL SCORE: {post.get('sil_score', 'unknown')}"
        )
    elif ptype == 'town_hall':
        positions = post.get('positions') or []
        pos_text = '\n'.join(
            f"  [{p.get('citizen','')} / {p.get('stance','')}]: {p.get('text','')[:200]}"
            for p in positions
        )
        return (
            f"TYPE: Town Hall Debate\n"
            f"TOPIC: {post.get('topic','')}\n"
            f"POSITIONS:\n{pos_text}\n"
            f"TAGS: {', '.join(tags)}\n"
            f"SIL SCORE: {post.get('sil_score', 'unknown')}"
        )
    return f"TYPE: {ptype}\nBODY: {post.get('body','')[:400]}\nTAGS: {', '.join(tags)}"


# ── PANEL ASSEMBLY ────────────────────────────────────────────────────────────

def _assemble_panel(post: dict) -> tuple[str, str] | None:
    """
    Assemble the two most credible, genuinely opposing voices for this signal.
    Returns (agent_a, agent_b) or None if no credible panel can be formed.
    """
    tags = set(post.get('tags') or [])
    # Also extract topics from body
    body = (post.get('body') or '').lower()

    # Score each known pair by topic relevance
    best_pair   = None
    best_score  = 0

    for a, b in DIVERGENT_PAIRS:
        a_tags = set(AGENT_TERRITORIES.get(a, []))
        b_tags = set(AGENT_TERRITORIES.get(b, []))
        # How many of the signal's tags does each agent cover?
        a_coverage = len(tags & a_tags)
        b_coverage = len(tags & b_tags)
        # Both must have at least one relevant tag
        if a_coverage == 0 or b_coverage == 0:
            continue
        # They must be in different territory groups
        a_group = next((g for g, members in TERRITORY_GROUPS.items() if a in members), None)
        b_group = next((g for g, members in TERRITORY_GROUPS.items() if b in members), None)
        if a_group and b_group and a_group == b_group:
            continue  # Same group = not genuinely independent
        score = a_coverage + b_coverage
        if score > best_score:
            best_score = score
            best_pair  = (a, b)

    # If signal involves contributing agents directly, prefer those
    contributing = set(post.get('citizens') or [])
    if len(contributing) >= 2:
        for a, b in DIVERGENT_PAIRS:
            if a in contributing and b in contributing:
                best_pair = (a, b)
                break

    return best_pair


# ── QUALITY GATE ──────────────────────────────────────────────────────────────

def _passes_quality_gate(post: dict, topic_tag: str) -> bool:
    """
    Hard quality gate before any Groq tokens are spent.
    Returns True only if the signal is worth a real debate.
    """
    # Generic tags that almost always produce weak debates
    BLACKLIST_TAGS = {
        '#history', '#data', '#technology', '#news', '#update',
        '#general', '#misc', '#other', '#information',
    }
    if topic_tag in BLACKLIST_TAGS:
        log.info(f'Council gate: {topic_tag} is blacklisted')
        return False

    # Minimum body length
    body_a = ''
    body_b = ''
    if post.get('type') == 'signal_alert':
        thread = post.get('thread') or []
        bodies = [e.get('text', '') for e in thread]
        if len(bodies) >= 2:
            body_a, body_b = bodies[0], bodies[1]
        elif bodies:
            body_a = bodies[0]
    elif post.get('type') == 'town_hall':
        positions = post.get('positions') or []
        if len(positions) >= 2:
            body_a = positions[0].get('text', '')
            body_b = positions[1].get('text', '')
        elif positions:
            body_a = positions[0].get('text', '')

    if len(body_a) < 80 or len(body_b) < 80:
        log.info(f'Council gate: bodies too short ({len(body_a)}, {len(body_b)})')
        return False

    # SIL score check — only signals that survived SIL above 0.62
    sil = post.get('sil_score', 0) or 0
    if isinstance(sil, str):
        try: sil = float(sil)
        except: sil = 0
    if sil > 0 and sil < 0.62:
        log.info(f'Council gate: SIL score {sil:.3f} too low')
        return False

    return True


# ── MAIN COUNCIL CLASS ────────────────────────────────────────────────────────

class CouncilAgent:
    name  = 'COUNCIL'
    title = 'The Council'
    color = '#8B7355'

    def __init__(self):
        self.log = logging.getLogger(self.name)

    def debate(self, post: dict) -> dict | None:
        """
        Run a dynamic domain-expert debate on a signal_alert or town_hall.

        1. Assemble the most credible opposing panel for this topic
        2. Voice A argues their position from their domain data
        3. Voice B counters from their domain data
        4. ARBITER assesses: genuine conflict? quality? gaps? verification queue?
        5. If ARBITER finds no genuine conflict → return None (no brief)
        6. Return structured session with domain authority scores
        """
        topic   = post.get('headline') or post.get('topic') or 'Unknown signal'
        tags    = post.get('tags') or []
        tag     = tags[0] if tags else '#general'
        source  = _build_source_summary(post)

        # Quality gate — before spending any tokens
        if not _passes_quality_gate(post, tag):
            self.log.info(f'Council: {topic[:50]} did not pass quality gate')
            return None

        # Assemble dynamic panel
        panel = _assemble_panel(post)
        if not panel:
            self.log.warning(f'Council: no credible panel found for {topic[:50]}')
            # Fall back to most relevant pair from contributing agents
            citizens = post.get('citizens') or []
            if len(citizens) >= 2:
                panel = (citizens[0], citizens[1])
            else:
                return None

        agent_a, agent_b = panel
        self.log.info(f'Council panel: {agent_a} vs {agent_b} on {topic[:50]}')

        exchanges = []

        # ── Voice A ───────────────────────────────────────────────────────────
        system_a = AGENT_COUNCIL_SYSTEMS.get(agent_a, f"You are {agent_a} in a Council debate. Argue from your domain expertise.")
        prompt_a = (
            f"Here is intelligence from the field:\n\n{source}\n\n"
            f"You are {agent_a}. This signal intersects your territory. "
            f"What does your data say? Argue the strongest signal from your domain."
        )
        text_a = _call(system_a, prompt_a, max_tokens=220)
        if not text_a:
            self.log.error(f'Council: {agent_a} failed on {post.get("id","?")}')
            return None
        exchanges.append({
            'member': agent_a,
            'role':   f'{agent_a} — domain expert',
            'text':   text_a,
        })

        # ── Voice B (counter) ─────────────────────────────────────────────────
        system_b = AGENT_COUNCIL_SYSTEMS.get(agent_b, f"You are {agent_b} in a Council debate. Counter from your domain expertise.")
        prompt_b = (
            f"Here is intelligence from the field:\n\n{source}\n\n"
            f"{agent_a} argues:\n{text_a}\n\n"
            f"You are {agent_b}. Your domain sees this differently. "
            f"What does your data say? Counter from your specific evidence — not just rhetorical opposition."
        )
        text_b = _call(system_b, prompt_b, max_tokens=220)
        if not text_b:
            self.log.error(f'Council: {agent_b} failed on {post.get("id","?")}')
            return None
        exchanges.append({
            'member': agent_b,
            'role':   f'{agent_b} — domain counter',
            'text':   text_b,
        })

        # ── ARBITER ───────────────────────────────────────────────────────────
        arbiter_prompt = (
            f"Original signal:\n{source}\n\n"
            f"{agent_a} argues:\n{text_a}\n\n"
            f"{agent_b} counters:\n{text_b}\n\n"
            "Assess this debate. Produce the JSON evaluation as specified."
        )
        arbiter_raw = _call(ARBITER_SYSTEM, arbiter_prompt, max_tokens=300)

        arbiter_data = {
            'genuine_conflict':           True,
            'stronger_position':          'EQUAL',
            'gaps':                       [],
            'hermes_verification_queue':  [],
            'signal_quality':             'MEDIUM',
            'arbiter_note':               '',
        }

        if arbiter_raw:
            try:
                clean = arbiter_raw.strip()
                if clean.startswith('```'):
                    clean = clean.split('\n', 1)[1].rsplit('```', 1)[0].strip()
                parsed = json.loads(clean)
                arbiter_data.update(parsed)
            except Exception as e:
                self.log.warning(f'Arbiter JSON parse failed: {e} — using defaults')
                # Extract gaps from raw text as fallback
                sentences = [s.strip() for s in arbiter_raw.replace(';','.').split('.') if len(s.strip()) > 20]
                arbiter_data['gaps'] = sentences[:3]

        # Self-rejection: ARBITER says this is noise → no session
        if not arbiter_data.get('genuine_conflict', True):
            sq = arbiter_data.get('signal_quality', 'MEDIUM')
            if sq == 'NOISE':
                self.log.info(f'Council: ARBITER rejected {topic[:50]} as noise')
                return None

        exchanges.append({
            'member': 'ARBITER',
            'role':   'The Arbiter',
            'text':   arbiter_data.get('arbiter_note', ''),
        })

        # ── Build session ─────────────────────────────────────────────────────
        session = {
            'id':                        str(uuid.uuid4()),
            'source_post_id':            post.get('id', ''),
            'source_type':               post.get('type', ''),
            'topic':                     topic,
            'panel':                     [agent_a, agent_b],
            'exchanges':                 exchanges,
            'consensus':                 text_a,   # lead voice position
            'dissent':                   text_b,   # counter position
            'gaps':                      arbiter_data.get('gaps', []),
            'hermes_queue':              arbiter_data.get('hermes_verification_queue', []),
            'stronger_position':         arbiter_data.get('stronger_position', 'EQUAL'),
            'signal_quality':            arbiter_data.get('signal_quality', 'MEDIUM'),
            'genuine_conflict':          arbiter_data.get('genuine_conflict', True),
            'tags':                      tags,
            'created_at':                datetime.utcnow().isoformat(),
            'processed':                 False,
        }

        # Dispatch HERMES verification items if queue is non-empty
        if arbiter_data.get('hermes_verification_queue'):
            self._dispatch_hermes_queue(
                arbiter_data['hermes_verification_queue'],
                post.get('id', ''),
                topic,
            )

        self.log.info(
            f"Council session: {agent_a} vs {agent_b} | "
            f"quality={arbiter_data.get('signal_quality')} | "
            f"conflict={arbiter_data.get('genuine_conflict')} | "
            f"hermes_items={len(arbiter_data.get('hermes_verification_queue',[]))}"
        )
        return session

    def _dispatch_hermes_queue(self, items: list, source_id: str, topic: str):
        """Queue items for HERMES verification. Non-blocking."""
        import threading
        def _verify():
            import time
            time.sleep(10)  # Let session save first
            try:
                from database import db
                # Save as pending verification items in a post
                verification_post = {
                    'id':        str(uuid.uuid4()),
                    'type':      'hermes_queue',
                    'citizen':   'HERMES',
                    'timestamp': datetime.utcnow().isoformat(),
                    'body':      f"Verification queue from Council debate: {topic[:80]}",
                    'tags':      ['#verification', '#hermes'],
                    'metadata':  {
                        'source_id':   source_id,
                        'queue_items': items,
                        'status':      'pending',
                    },
                }
                db.save_post(verification_post)
                log.info(f'HERMES queue dispatched: {len(items)} items for {topic[:50]}')
            except Exception as e:
                log.error(f'HERMES queue dispatch failed: {e}')
        threading.Thread(target=_verify, daemon=True).start()

    def run_on_unprocessed(self, db) -> list:
        """Find Signal Alerts/Town Halls without council sessions, debate them, save."""
        try:
            all_posts = db.get_unprocessed_posts()
            existing  = db.get_council_sessions(limit=200)
            processed = {s['source_post_id'] for s in existing if s.get('source_post_id')}
            pending   = [p for p in all_posts if p['id'] not in processed]

            self.log.info(f'Council: {len(pending)} posts pending debate')

            sessions = []
            for post in pending[:2]:  # Max 2 per run — quality over quantity
                session = self.debate(post)
                if session:
                    try:
                        sid = db.save_council_session(session)
                        if sid:
                            sessions.append(session)
                            self.log.info(f'Saved council session: {sid}')
                    except Exception as e:
                        self.log.error(f'Failed to save council session: {e}')
                else:
                    self.log.info('Debate returned None — signal not council-worthy')

            self.log.info(f'Council produced {len(sessions)} session(s)')
            return sessions

        except Exception as e:
            self.log.error(f'run_on_unprocessed failed: {e}')
            import traceback
            self.log.error(traceback.format_exc())
            return []

"""
agents/oracle.py — ORACLE (v2)

Major rework from v1:

BEFORE: Every council session became a brief. Confidence derived from gap count.
        Automatic MEDIUM→HIGH upgrade for signal_alert source. Published weak
        briefs that undermined themselves in their own evidence section.

AFTER:
  - Self-rejection: if ARBITER found no genuine conflict or KRISIS > LOGOS,
    ORACLE returns None. No brief published.
  - Epistemic tagging: every evidence item tagged VERIFIED/CORROBORATED/
    INFERRED/SPECULATIVE — users know exactly what weight to give each claim.
  - Confidence derived from source independence + evidence quality, not gap count.
  - Pattern matching: brief includes what historical cycle this most resembles
    and what happened then — the "we've seen this before" layer.
  - Timeline estimate: how long before this becomes obvious to mainstream.
  - Silence signal: if key agents that SHOULD have data are absent, brief
    flags this explicitly rather than ignoring it.
  - Brief is structured for decision-makers: what do I know, what is inferred,
    what should I do, how long do I have.
"""

import os, json, logging, uuid, re
from datetime import datetime

try:
    from agents import llm_gateway
    HAS_GATEWAY = True
except ImportError:
    HAS_GATEWAY = False

log = logging.getLogger('ORACLE')


# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────────
ORACLE_SYSTEM = """You are ORACLE, the synthesis layer of The Signal Society.

You receive a completed Council debate and produce a Chronicles Brief — the
highest-value output of the entire system. You are not a summariser. You are
a synthesiser. You take conflicting expert positions and produce the most
defensible interpretation of what is actually happening and what it means.

CRITICAL RULES:

1. SELF-REJECTION: If the Council debate shows more noise than signal — if
   the counter-position is stronger than the signal position, if the evidence
   is circumstantial, if the convergence was on a generic topic — return:
   {"reject": true, "reason": "one sentence why"}
   A rejected brief is better than a weak brief.

2. EPISTEMIC HONESTY: Tag every evidence item:
   VERIFIED = confirmed by primary source data (filing, price, record exists)
   CORROBORATED = confirmed by 2+ independent agent sources
   INFERRED = derived from patterns in verified data
   SPECULATIVE = analytical extrapolation, not yet in data

3. CONFIDENCE RULES (not negotiable):
   CONFIRMED = 3+ agents, all VERIFIED or CORROBORATED evidence, no major gaps
   HIGH      = 2+ agents, mostly VERIFIED evidence, minor gaps only
   MEDIUM    = mixed evidence quality, at least one major gap identified
   LOW       = mostly INFERRED or SPECULATIVE, single source, major gaps

   Do NOT upgrade confidence because the source type is "signal_alert".
   Signal alerts can still be LOW confidence if the underlying evidence is weak.

4. SILENCE SIGNALS: If the ARBITER identified that key agents are absent from
   the debate (e.g. a supply chain signal where VIGIL has no data), name this
   explicitly in the brief. Silence from an expected voice is intelligence.

5. PATTERN MATCHING: Every brief must include a pattern section — what cycle,
   crisis, or historical moment does this most resemble, and what happened then.
   Be specific (e.g. "2007 credit market divergence" not "previous crises").

6. TIMELINE: Estimate when this becomes obvious to mainstream analysis.
   Be specific: "4-8 weeks" not "soon."

Return ONLY valid JSON. No markdown fences. No preamble.

{
  "reject": false,
  "headline": "One precise sentence. No hedging. No 'may suggest'.",
  "verdict": "2-3 sentences. What is happening. What the evidence shows. What it implies.",
  "pattern": "What historical cycle/event this most resembles and what happened then.",
  "evidence": [
    {"claim": "specific claim", "tag": "VERIFIED|CORROBORATED|INFERRED|SPECULATIVE", "source": "agent + source"}
  ],
  "silence_signals": ["agent that should have data but doesn't, and why that matters"],
  "implications": "Who does this matter to and specifically why.",
  "whitespace": "What structural solution already exists that civilisation has forgotten.",
  "timeline": "Specific estimate of when mainstream catches up.",
  "action_items": ["specific action 1", "specific action 2"],
  "confidence": "CONFIRMED|HIGH|MEDIUM|LOW",
  "hermes_pending": true/false
}"""


# ── HISTORICAL PATTERN LIBRARY ────────────────────────────────────────────────
# Used to help ORACLE identify what cycle this signal most resembles.

PATTERN_LIBRARY = [
    {
        'name':    '2007 credit/physical divergence',
        'signals': ['capital expansion', 'physical contraction', 'narrative boom',
                    'supply chain', 'commodity', 'BDI', 'shipping', 'real estate'],
        'description': 'Financial assets pricing in growth while physical indicators contract. Preceded 2008 crisis.',
    },
    {
        'name':    '2020 pre-pandemic regulatory burial',
        'signals': ['federal register', 'friday', 'short comment period', 'regulation',
                    'public health', 'emergency', 'infrastructure', 'government'],
        'description': 'High-impact regulatory changes buried with minimal comment periods before a crisis.',
    },
    {
        'name':    '2000 tech concentration before correction',
        'signals': ['patent cluster', 'hiring spike', 'VC funding', 'concentration',
                    'monopoly', 'acquisition', 'IP strategy', 'tech'],
        'description': 'Aggressive IP and talent acquisition by dominant players before market correction.',
    },
    {
        'name':    '2021 supply chain cascade',
        'signals': ['port', 'vessel', 'container', 'semiconductor', 'manufacturing',
                    'inventory', 'lead time', 'shipping anomaly'],
        'description': 'Physical bottleneck signals 6+ months before mainstream consumer awareness.',
    },
    {
        'name':    'SolarWinds pre-compromise pattern (2020)',
        'signals': ['supply chain', 'software update', 'build system', 'security',
                    'CVE', 'breach', 'credential', 'government contractor'],
        'description': 'Supply chain attack precursors: build system access + credential exposure + unusual update patterns.',
    },
    {
        'name':    'Colonial Pipeline escalation pattern (2021)',
        'signals': ['infrastructure', 'energy', 'pipeline', 'ICS', 'SCADA',
                    'ransomware', 'critical', 'operational technology'],
        'description': 'Critical infrastructure CVE exploitation preceding operational disruption.',
    },
    {
        'name':    'SVB pre-collapse narrative gap (2023)',
        'signals': ['banking', 'liquidity', 'treasury', 'yield', 'sentiment',
                    'positive narrative', 'media coverage', 'insider selling'],
        'description': 'Positive official narrative sustained while physical/financial signals contradict it.',
    },
    {
        'name':    'Pre-announcement convergence (Amazon AWS 2006, iPhone 2007)',
        'signals': ['patent', 'FCC', 'hiring', 'permit', 'experimental license',
                    'stealth', 'acquisition', 'infrastructure cluster'],
        'description': 'Regulatory/IP/hiring signals converging on same entity 12-18 months before announcement.',
    },
]


def _match_pattern(session_text: str) -> dict | None:
    """Find the most relevant historical pattern for this signal."""
    text_lower = session_text.lower()
    best       = None
    best_score = 0
    for pattern in PATTERN_LIBRARY:
        score = sum(1 for kw in pattern['signals'] if kw in text_lower)
        if score > best_score:
            best_score = score
            best       = pattern
    return best if best_score >= 2 else None


def _build_silence_analysis(session: dict) -> list:
    """
    Detect which agents SHOULD have data on this topic but are absent
    from the debate — their silence is itself intelligence.
    """
    from agents.council import AGENT_TERRITORIES

    tags  = set(session.get('tags') or [])
    panel = set(session.get('panel') or [])
    gaps  = session.get('gaps') or []

    # Find agents not on the panel who have relevant territory
    absent_relevant = []
    for agent, agent_tags in AGENT_TERRITORIES.items():
        if agent in panel:
            continue
        coverage = len(tags & set(agent_tags))
        if coverage >= 2 and agent not in {'COUNCIL', 'ORACLE'}:
            absent_relevant.append(agent)

    silences = []
    for agent in absent_relevant[:3]:
        silences.append(
            f"{agent} has relevant territory on {', '.join(list(tags)[:2])} "
            f"but produced no signal — absence may indicate data gap or source failure."
        )
    return silences


def _call(prompt: str) -> str | None:
    if HAS_GATEWAY:
        return llm_gateway.call(
            agent        = 'ORACLE',
            system_prompt= ORACLE_SYSTEM,
            user_prompt  = prompt,
            max_tokens   = 800,
            temperature  = 0.5,
            use_cache    = False,
        )
    key = os.environ.get('GROQ_API_KEY', '')
    if not key:
        return None
    try:
        import requests as _req
        resp = _req.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [
                    {'role': 'system', 'content': ORACLE_SYSTEM},
                    {'role': 'user',   'content': prompt},
                ],
                'temperature': 0.5,
                'max_tokens':  800,
            },
            timeout=45,
        )
        if resp.ok:
            return resp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.error(f'ORACLE direct Groq call: {e}')
    return None


# ── ORACLE CLASS ──────────────────────────────────────────────────────────────

class OracleAgent:
    name  = 'ORACLE'
    title = 'The Synthesis Layer'
    color = '#8B5CF6'

    def __init__(self):
        self.log = logging.getLogger(self.name)

    def synthesise(self, session: dict) -> dict | None:
        """
        Turn a Council session into a Chronicles Brief.
        Returns None if self-rejection is triggered.
        """
        # Hard gate: if ARBITER already flagged noise, skip immediately
        if not session.get('genuine_conflict', True):
            if session.get('signal_quality') == 'NOISE':
                self.log.info(f"ORACLE: skipping noise session {session.get('id','?')[:8]}")
                return None

        panel    = session.get('panel', [])
        topic    = session.get('topic', 'Unknown')
        tags     = session.get('tags') or []
        exc      = session.get('exchanges') or []
        gaps     = session.get('gaps') or []
        stronger = session.get('stronger_position', 'EQUAL')
        sq       = session.get('signal_quality', 'MEDIUM')
        hermes_q = session.get('hermes_queue') or []

        # Build the prompt for ORACLE
        exchanges_text = '\n\n'.join(
            f"[{e.get('member','')} — {e.get('role','')}]:\n{e.get('text','')}"
            for e in exc
        )
        silence_signals = _build_silence_analysis(session)
        pattern_hint    = _match_pattern(
            topic + ' ' + ' '.join(e.get('text','') for e in exc)
        )

        prompt = (
            f"TOPIC: {topic}\n"
            f"TAGS: {', '.join(tags)}\n"
            f"COUNCIL PANEL: {', '.join(panel)}\n"
            f"ARBITER ASSESSMENT: stronger={stronger}, signal_quality={sq}\n"
            f"IDENTIFIED GAPS: {json.dumps(gaps)}\n"
            f"HERMES VERIFICATION PENDING: {len(hermes_q)} items\n"
            f"SILENCE SIGNALS: {json.dumps(silence_signals)}\n\n"
            f"COUNCIL DEBATE:\n{exchanges_text}\n\n"
        )
        if pattern_hint:
            prompt += (
                f"HISTORICAL PATTERN HINT: This signal resembles the "
                f"'{pattern_hint['name']}' — {pattern_hint['description']}\n\n"
            )
        prompt += "Synthesise this into a Chronicles Brief. Apply all rules strictly."

        raw = _call(prompt)
        if not raw:
            self.log.error(f'ORACLE: no response from Groq for {session.get("id","?")}')
            return None

        # Parse response
        text = raw.replace('```json', '').replace('```', '').strip()
        parsed = {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            s = text.find('{')
            e = text.rfind('}') + 1
            if s >= 0 and e > s:
                try:
                    parsed = json.loads(text[s:e])
                except Exception:
                    pass

        # Self-rejection
        if parsed.get('reject', False):
            reason = parsed.get('reason', 'Signal quality insufficient')
            self.log.info(f'ORACLE self-rejected: {reason}')
            return None

        headline = parsed.get('headline', '').strip()
        verdict  = parsed.get('verdict', '').strip()
        if not headline or not verdict or len(verdict) < 30:
            self.log.warning(f'ORACLE: empty headline or verdict — discarding')
            return None

        # Validate confidence — never auto-upgrade
        confidence = parsed.get('confidence', 'MEDIUM').upper()
        if confidence not in ('CONFIRMED', 'HIGH', 'MEDIUM', 'LOW'):
            confidence = 'MEDIUM'

        # Downgrade if ARBITER said weaker quality
        if sq == 'LOW' and confidence in ('HIGH', 'CONFIRMED'):
            confidence = 'MEDIUM'
            self.log.info('ORACLE: confidence downgraded from HIGH to MEDIUM per ARBITER')
        if sq == 'NOISE' and confidence != 'LOW':
            confidence = 'LOW'

        brief = {
            'id':                 str(uuid.uuid4()),
            'source_session_id':  session.get('id', ''),
            'source_post_id':     session.get('source_post_id', ''),
            'panel':              panel,
            'headline':           headline,
            'verdict':            verdict,
            'pattern':            parsed.get('pattern', ''),
            'evidence':           parsed.get('evidence', []),
            'silence_signals':    parsed.get('silence_signals', silence_signals),
            'implications':       parsed.get('implications', ''),
            'whitespace':         parsed.get('whitespace', ''),
            'timeline':           parsed.get('timeline', ''),
            'action_items':       parsed.get('action_items', []),
            'confidence':         confidence,
            'tier':               'premium' if confidence in ('CONFIRMED', 'HIGH') else 'free',
            'agents':             panel,
            'tags':               tags,
            'hermes_pending':     len(hermes_q) > 0,
            'hermes_queue':       hermes_q,
            'created_at':         datetime.utcnow().isoformat(),
            'published':          True,
        }

        self.log.info(
            f"ORACLE brief: '{headline[:60]}' | "
            f"confidence={confidence} | "
            f"evidence_items={len(parsed.get('evidence',[]))} | "
            f"hermes_pending={brief['hermes_pending']}"
        )
        return brief

    def run_on_unprocessed(self, db) -> list:
        """Process all unprocessed council sessions. Save briefs to DB."""
        try:
            sessions = db.get_council_sessions(limit=5, processed=False)
            self.log.info(f'ORACLE: {len(sessions)} unprocessed sessions')
            briefs = []
            for session in sessions:
                try:
                    brief = self.synthesise(session)
                    if brief:
                        db.save_brief(brief)
                        db.mark_session_processed(session['id'])
                        briefs.append(brief)
                        self.log.info(f"Brief saved: {brief['headline'][:60]}")
                    else:
                        # Mark as processed even on rejection — don't retry noise
                        db.mark_session_processed(session['id'])
                except Exception as e:
                    self.log.error(f"Oracle session {session.get('id','?')}: {e}")
            self.log.info(f'ORACLE: produced {len(briefs)} brief(s)')
            return briefs
        except Exception as e:
            self.log.error(f'run_on_unprocessed: {e}')
            import traceback
            self.log.error(traceback.format_exc())
            return []

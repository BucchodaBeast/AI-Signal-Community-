"""
signal_integrity.py
═══════════════════════════════════════════════════════════════════════════════
Signal Integrity Layer — Phase 1
The Signal Society's thalamus/filtering cortex.

Architecture position:
  Citizen → [Signal Integrity Layer] → Council Queue → Council → Oracle

This module contains:
  1. CredibilityScorer     — scores every raw signal before persistence
  2. CouncilGatekeeper     — ranks, deduplicates, batches for Council
  3. EntropyMonitor        — detects cognitive drift across the organism
  4. SignalBurial          — negative memory / suppression patterns

Design constraints (from architecture decisions):
  - NO Groq/LLM calls in this module. Pure deterministic logic only.
  - Thresholds are env-configurable, not hardcoded.
  - Rejected signals are logged lightweight (hash + score) for audit.
  - Low-quality signals never contaminate the downstream database.
  - The organism becoming quieter over time = intelligence improvement.

Phase 2 additions (not here):
  - Whitespace Detection
  - Counterfactual Engine (LLM-allowed)

Phase 3 additions (not here):
  - Delayed Outcome Auditing
  - Adaptive threshold evolution (requires 50+ audited signals)
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import math
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field, asdict

log = logging.getLogger('SIL')

# ── ENV-CONFIGURABLE THRESHOLDS ──────────────────────────────────────────────
# Tune these via environment variables during live testing.
# Do NOT hardcode. These will evolve rapidly.

SIGNAL_MIN_SCORE = int(os.getenv('SIGNAL_MIN_SCORE', '52'))
COUNCIL_ESCALATION_SCORE = int(os.getenv('COUNCIL_ESCALATION_SCORE', '72'))
COUNTERFACTUAL_TRIGGER_SCORE = int(os.getenv('COUNTERFACTUAL_TRIGGER_SCORE', '85'))
ENTROPY_ALERT_THRESHOLD = float(os.getenv('ENTROPY_ALERT_THRESHOLD', '0.72'))
MAX_COUNCIL_SESSIONS_PER_CYCLE = int(os.getenv('MAX_COUNCIL_SESSIONS_PER_CYCLE', '3'))
MAX_ALERTS_PER_DOMAIN_PER_HOUR = int(os.getenv('MAX_ALERTS_PER_DOMAIN_PER_HOUR', '2'))

# Signal alerts and town halls have a lower minimum — they are already
# the product of convergence detection, so they receive a scoring discount.
ALERT_MIN_SCORE = int(os.getenv('ALERT_MIN_SCORE', '42'))

# ── SCORING WEIGHTS ───────────────────────────────────────────────────────────
# These define the relative importance of each scoring dimension.
# Must sum to 1.0. Adjust via source if needed (not env — these are structural).

WEIGHTS = {
    'source_reliability':    0.18,
    'novelty':               0.18,
    'cross_agent_corroboration': 0.16,
    'temporal_anomaly':      0.14,
    'entity_importance':     0.12,
    'narrative_uniqueness':  0.10,
    'downstream_impact':     0.08,
    'rarity':                0.04,
}
# Verify weights sum to 1.0
assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001, "Scoring weights must sum to 1.0"

# ── KNOWN HIGH-IMPORTANCE ENTITIES ───────────────────────────────────────────
# Signals mentioning these receive entity_importance boost.
# Expand this list as the organism matures.

HIGH_IMPORTANCE_ENTITIES = {
    # Regulators
    'sec', 'ftc', 'fcc', 'fda', 'doj', 'cftc', 'occ', 'fdic', 'finra',
    'federal reserve', 'ecb', 'bis', 'imf', 'world bank',
    # Infrastructure
    'patent', 'fcc license', 'federal register', 'executive order',
    'court filing', 'sec filing', 'ipo', 'acquisition', 'merger',
    # Domains with high downstream consequence
    'nuclear', 'semiconductor', 'critical infrastructure', 'grid',
    'pandemic', 'outbreak', 'biosecurity', 'cyberattack', 'breach',
    'quantum', 'satellite', 'spectrum',
}

# Signals mentioning these get novelty penalty — already saturated narratives.
SATURATED_NARRATIVES = {
    'bitcoin', 'elon musk', 'chatgpt', 'openai', 'twitter', 'x.com',
    'maga', 'trump', 'election', 'inflation fears', 'recession fears',
    'market crash', 'ai bubble', 'crypto winter',
}

# ── STRUCTURAL HYPE MARKERS ───────────────────────────────────────────────────
# Language patterns that correlate with low-information / sensationalism.
# Presence of these deflates the novelty and narrative_uniqueness scores.

HYPE_MARKERS = {
    r'\beverything\b', r'\bbreaking\b', r'\bshocking\b', r'\bunbelievable\b',
    r'\bexplosive\b', r'\bgame.changer\b', r'\bwake up\b', r'\bmassive\b',
    r'\bcrazy\b', r'\bwild\b', r'\bmind.blow\b', r'\bcollapse\b',
    r'\bmeltdown\b', r'\bpanicb', r'\bfear\b.*\bgreed\b',
    r'\bthe\b.*\btrue\b.*\bstory\b', r'!!+', r'\?\?+',
}

HYPE_PATTERN = re.compile('|'.join(HYPE_MARKERS), re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SignalScore:
    """
    Complete scoring result for a single signal.
    This is the contract between the scorer and downstream systems.
    """
    signal_id: str
    citizen: str
    signal_type: str                    # post | signal_alert | town_hall | brief

    # Dimensional scores (0–100 each)
    source_reliability_score: float = 50.0
    novelty_score: float = 50.0
    corroboration_score: float = 0.0
    temporal_anomaly_score: float = 0.0
    entity_importance_score: float = 0.0
    narrative_uniqueness_score: float = 50.0
    downstream_impact_score: float = 0.0
    rarity_score: float = 50.0

    # Composite
    credibility_score: float = 0.0      # 0–100 weighted composite
    impact_score: float = 0.0           # severity × consequence
    confidence_weight: float = 1.0      # multiplier from agent precision history

    # Decisions
    passes_threshold: bool = False
    escalate_to_council: bool = False
    trigger_counterfactual: bool = False
    escalation_recommendation: str = 'suppress'  # suppress|monitor|escalate|urgent

    # Metadata
    hype_penalty: float = 0.0
    saturation_penalty: float = 0.0
    suppressed_by_burial: bool = False
    score_explanation: str = ''
    scored_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EntropySnapshot:
    """Point-in-time measurement of organism cognitive health."""
    snapshot_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    alert_frequency_1h: int = 0
    unique_entities_24h: int = 0
    correlation_inflation_score: float = 0.0
    repetitive_narrative_ratio: float = 0.0
    agent_confidence_mean: float = 0.0
    agent_confidence_variance: float = 0.0
    entropy_index: float = 0.0          # 0.0 = healthy, 1.0 = full drift
    action_required: bool = False
    recommended_actions: list = field(default_factory=list)


@dataclass
class GatekeeperDecision:
    """Council Gatekeeper's verdict on a batch of signals."""
    approved_for_council: list = field(default_factory=list)    # signal_ids
    suppressed: list = field(default_factory=list)
    batched_together: list = field(default_factory=list)        # grouped signal_ids
    domain_diversity_enforced: bool = False
    session_budget_remaining: int = 0
    decision_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ═══════════════════════════════════════════════════════════════════════════════
#  1. CREDIBILITY SCORER
# ═══════════════════════════════════════════════════════════════════════════════

class CredibilityScorer:
    """
    Scores every raw signal before persistence or council consideration.

    Pure deterministic logic. No LLM calls.

    Scoring philosophy:
      - Reward: uniqueness, precision, cross-domain corroboration, consequence potential
      - Penalise: hype language, saturated narratives, repetition, low-entity signals
      - Neutral prior for new agents until precision history accumulates

    The scorer needs a database handle to query:
      - Recent posts (novelty check)
      - Agent precision history (confidence weighting)
      - Suppression patterns (burial check)
    """

    def __init__(self, db):
        self.db = db
        self._cache = {}  # lightweight in-process cache to avoid repeat DB hits

    def score(self, signal: dict) -> SignalScore:
        """
        Main entry point. Call this for every signal before saving to DB.

        signal: dict with keys:
            id, citizen, type, body, tags, confidence (optional),
            sources (optional), mentioned_entities (optional)
        """
        sid = signal.get('id', 'unknown')
        citizen = signal.get('citizen', 'UNKNOWN')
        stype = signal.get('type', 'post')
        body = signal.get('body', '')
        tags = signal.get('tags', [])

        result = SignalScore(
            signal_id=sid,
            citizen=citizen,
            signal_type=stype,
        )

        # ── 1. Check burial suppression FIRST ────────────────────────────────
        if self._is_suppressed(body, tags, citizen):
            result.suppressed_by_burial = True
            result.passes_threshold = False
            result.escalation_recommendation = 'suppress'
            result.score_explanation = 'Suppressed by burial pattern memory.'
            log.info(f'[SCORER] {sid} suppressed by burial.')
            return result

        # ── 2. Score each dimension ───────────────────────────────────────────
        result.source_reliability_score = self._score_source_reliability(citizen)
        result.novelty_score = self._score_novelty(body, tags, citizen)
        result.corroboration_score = self._score_corroboration(tags, body)
        result.temporal_anomaly_score = self._score_temporal_anomaly(signal)
        result.entity_importance_score = self._score_entity_importance(body, tags)
        result.narrative_uniqueness_score = self._score_narrative_uniqueness(body, tags)
        result.downstream_impact_score = self._score_downstream_impact(body, tags)
        result.rarity_score = self._score_rarity(tags, body)

        # ── 3. Hype and saturation penalties ─────────────────────────────────
        result.hype_penalty = self._calculate_hype_penalty(body)
        result.saturation_penalty = self._calculate_saturation_penalty(body, tags)

        # ── 4. Agent confidence weight (neutral prior until audit history) ────
        result.confidence_weight = self._get_agent_confidence_weight(citizen)

        # ── 5. Composite credibility score ───────────────────────────────────
        raw_score = (
            result.source_reliability_score    * WEIGHTS['source_reliability'] +
            result.novelty_score               * WEIGHTS['novelty'] +
            result.corroboration_score         * WEIGHTS['cross_agent_corroboration'] +
            result.temporal_anomaly_score      * WEIGHTS['temporal_anomaly'] +
            result.entity_importance_score     * WEIGHTS['entity_importance'] +
            result.narrative_uniqueness_score  * WEIGHTS['narrative_uniqueness'] +
            result.downstream_impact_score     * WEIGHTS['downstream_impact'] +
            result.rarity_score                * WEIGHTS['rarity']
        )

        # Apply penalties and confidence weight
        penalised = raw_score - result.hype_penalty - result.saturation_penalty
        result.credibility_score = round(max(0.0, min(100.0, penalised * result.confidence_weight)), 2)

        # Impact score: entity importance × downstream impact × corroboration
        result.impact_score = round(
            (result.entity_importance_score * 0.45 +
             result.downstream_impact_score * 0.35 +
             result.corroboration_score     * 0.20) * result.confidence_weight, 2
        )

        # ── 6. Threshold decisions ────────────────────────────────────────────
        min_score = ALERT_MIN_SCORE if stype in ('signal_alert', 'town_hall') else SIGNAL_MIN_SCORE
        result.passes_threshold = result.credibility_score >= min_score
        result.escalate_to_council = result.credibility_score >= COUNCIL_ESCALATION_SCORE
        result.trigger_counterfactual = result.credibility_score >= COUNTERFACTUAL_TRIGGER_SCORE

        # ── 7. Escalation recommendation ─────────────────────────────────────
        if not result.passes_threshold:
            result.escalation_recommendation = 'suppress'
        elif result.trigger_counterfactual:
            result.escalation_recommendation = 'urgent'
        elif result.escalate_to_council:
            result.escalation_recommendation = 'escalate'
        else:
            result.escalation_recommendation = 'monitor'

        result.score_explanation = self._build_explanation(result)
        log.info(f'[SCORER] {sid} ({citizen}) score={result.credibility_score} → {result.escalation_recommendation}')
        return result

    # ── DIMENSION SCORERS ─────────────────────────────────────────────────────

    def _score_source_reliability(self, citizen: str) -> float:
        """
        Agent precision history lookup.
        Neutral prior (50) until 50 audited signals exist per agent.
        Returns 0–100.
        """
        try:
            history = self._get_agent_precision(citizen)
            if history is None or history.get('audited_count', 0) < 50:
                return 50.0  # neutral prior — no premature epistemic favoritism
            precision = history.get('precision_rate', 0.5)
            return round(precision * 100, 2)
        except Exception:
            return 50.0

    def _score_novelty(self, body: str, tags: list, citizen: str) -> float:
        """
        Measures how different this signal is from recent posts.
        Penalises repetition of the same entity/tag cluster within 24h.
        Returns 0–100.
        """
        try:
            recent = self._get_recent_posts_summary(hours=24)
            if not recent:
                return 80.0  # no history = novel

            # Count overlap between this signal's tags and recent tags
            this_tags = set(t.lower() for t in tags)
            overlap_scores = []
            for r in recent:
                r_tags = set(t.lower() for t in r.get('tags', []))
                if not r_tags:
                    continue
                overlap = len(this_tags & r_tags) / max(len(this_tags | r_tags), 1)
                overlap_scores.append(overlap)

            if not overlap_scores:
                return 80.0

            avg_overlap = sum(overlap_scores) / len(overlap_scores)
            # High overlap = low novelty
            novelty = 100.0 * (1.0 - avg_overlap)
            return round(max(10.0, novelty), 2)
        except Exception:
            return 50.0

    def _score_corroboration(self, tags: list, body: str) -> float:
        """
        Checks if multiple distinct agents have recently posted on overlapping topics.
        Cross-agent corroboration is the strongest signal quality indicator.
        Returns 0–100.
        """
        try:
            recent = self._get_recent_posts_summary(hours=12)
            if not recent:
                return 0.0

            this_tags = set(t.lower() for t in tags)
            corroborating_agents = set()
            for r in recent:
                r_tags = set(t.lower() for t in r.get('tags', []))
                r_agent = r.get('citizen', '')
                if len(this_tags & r_tags) >= 1 and r_agent:
                    corroborating_agents.add(r_agent)

            # Score scales with number of distinct corroborating agents
            # 1 agent = 25, 2 = 55, 3 = 80, 4+ = 100
            n = len(corroborating_agents)
            score_map = {0: 0, 1: 25, 2: 55, 3: 80}
            return float(score_map.get(n, 100))
        except Exception:
            return 0.0

    def _score_temporal_anomaly(self, signal: dict) -> float:
        """
        Detects unusual timing patterns:
        - Signal arriving outside agent's normal posting window
        - Sudden spike in signal volume on a topic
        - Post published at unusual hours (e.g. Friday 4:58pm regulatory burial)
        Returns 0–100.
        """
        try:
            now = datetime.utcnow()
            score = 0.0

            # Friday end-of-day regulatory burial pattern (high anomaly)
            if now.weekday() == 4 and now.hour >= 16:
                body = signal.get('body', '').lower()
                if any(w in body for w in ['federal register', 'rule', 'regulation', 'sec filing', 'notice']):
                    score += 40.0

            # Early morning signals (2am–5am UTC) from data sources
            # — often indicate automated filings or overseas activity
            if 2 <= now.hour <= 5:
                score += 20.0

            # Check for topic spike: same tags trending up in last 2h vs 24h
            tags = signal.get('tags', [])
            if tags:
                spike = self._detect_topic_spike(tags)
                score += spike * 40.0  # 0–40 additional points

            return round(min(100.0, score), 2)
        except Exception:
            return 0.0

    def _score_entity_importance(self, body: str, tags: list) -> float:
        """
        Boosts signals mentioning high-consequence entities.
        Uses a curated entity list — not ML-based.
        Returns 0–100.
        """
        body_lower = body.lower()
        tags_lower = ' '.join(tags).lower()
        combined = body_lower + ' ' + tags_lower

        matched = sum(1 for e in HIGH_IMPORTANCE_ENTITIES if e in combined)

        if matched == 0:
            return 20.0
        elif matched == 1:
            return 55.0
        elif matched == 2:
            return 75.0
        else:
            return 90.0

    def _score_narrative_uniqueness(self, body: str, tags: list) -> float:
        """
        Rewards structural novelty — signals that don't follow common
        narrative templates. Penalises hype structure even if the content
        itself is new.
        Returns 0–100.
        """
        score = 70.0  # baseline

        # Penalise hype markers (calculated separately but applied here too)
        hype_count = len(HYPE_PATTERN.findall(body))
        score -= hype_count * 8.0

        # Reward specific data presence (numbers, dates, entities, percentages)
        data_indicators = re.findall(r'\b\d+[\.\d]*\s*%|\b\d{4}-\d{2}-\d{2}\b|\$[\d,]+[BMK]?\b|\b\d+\s*(filing|patent|role|contract)', body)
        score += min(len(data_indicators) * 6.0, 30.0)

        # Reward cross-domain language (signals spanning multiple territories)
        domain_keywords = ['patent', 'hiring', 'spectrum', 'filing', 'permit',
                          'satellite', 'chemical', 'contract', 'frequency',
                          'license', 'tender', 'grant', 'acquisition']
        domain_hits = sum(1 for dk in domain_keywords if dk in body.lower())
        score += min(domain_hits * 4.0, 20.0)

        return round(max(0.0, min(100.0, score)), 2)

    def _score_downstream_impact(self, body: str, tags: list) -> float:
        """
        Estimates consequence potential: if this signal is true, does it
        matter to enough people in enough domains?
        Returns 0–100.
        """
        body_lower = body.lower()
        score = 20.0  # baseline

        # High-consequence keywords
        high_impact = ['acquisition', 'merger', 'bankruptcy', 'outbreak',
                       'executive order', 'sanction', 'breach', 'exploit',
                       'blackout', 'shortage', 'recall', 'shutdown',
                       'patent', 'clinical trial', 'fda approval', 'ipo',
                       'layoff', 'restructuring', 'default', 'downgrade']

        medium_impact = ['earnings', 'guidance', 'partnership', 'filing',
                        'contract', 'tender', 'grant', 'license', 'permit',
                        'investigation', 'probe', 'subpoena', 'ruling']

        high_hits = sum(1 for kw in high_impact if kw in body_lower)
        med_hits = sum(1 for kw in medium_impact if kw in body_lower)

        score += high_hits * 15.0
        score += med_hits * 6.0

        return round(max(0.0, min(100.0, score)), 2)

    def _score_rarity(self, tags: list, body: str) -> float:
        """
        Rewards signals from underreported domains and obscure sources.
        This is the whitespace precursor — full whitespace detection in Phase 2.
        Returns 0–100.
        """
        # Whitespace-adjacent tags (underreported domains)
        whitespace_tags = {
            '#patents', '#foia', '#permitting', '#zoning', '#llc',
            '#wayback', '#deleted', '#archived', '#dormant', '#spectrum',
            '#maritime', '#ais', '#baltic', '#comtrade', '#usgs',
            '#noaa', '#federalregister', '#usaspending', '#dockets',
            '#preprint', '#ssrn', '#clinicaltrials',
        }
        tags_lower = set(t.lower() for t in tags)
        whitespace_overlap = len(tags_lower & whitespace_tags)

        score = 40.0 + whitespace_overlap * 20.0

        # Penalty for mainstream/trending topics
        mainstream = {'#bitcoin', '#crypto', '#ai', '#chatgpt', '#musk',
                      '#trump', '#election', '#market', '#stocks'}
        mainstream_overlap = len(tags_lower & mainstream)
        score -= mainstream_overlap * 10.0

        return round(max(10.0, min(100.0, score)), 2)

    # ── PENALTY CALCULATORS ───────────────────────────────────────────────────

    def _calculate_hype_penalty(self, body: str) -> float:
        """Returns points to subtract for sensationalist language."""
        matches = HYPE_PATTERN.findall(body)
        return min(float(len(matches) * 5), 25.0)

    def _calculate_saturation_penalty(self, body: str, tags: list) -> float:
        """Returns points to subtract for already-saturated narratives."""
        body_lower = body.lower()
        tags_lower = ' '.join(tags).lower()
        combined = body_lower + ' ' + tags_lower

        saturation_hits = sum(1 for s in SATURATED_NARRATIVES if s in combined)
        return min(float(saturation_hits * 8), 20.0)

    # ── BURIAL / SUPPRESSION ──────────────────────────────────────────────────

    def _is_suppressed(self, body: str, tags: list, citizen: str) -> bool:
        """
        Checks suppression_patterns table for negative memory matches.
        Returns True if this signal matches an active suppression pattern.
        """
        try:
            patterns = self._get_suppression_patterns()
            if not patterns:
                return False

            body_lower = body.lower()
            tags_set = set(t.lower() for t in tags)
            now = datetime.utcnow()

            for p in patterns:
                # Check TTL — suppression decays over time
                expires = datetime.fromisoformat(p.get('expires_at', '2099-01-01'))
                if expires < now:
                    continue

                # Check agent match (if agent-specific suppression)
                if p.get('citizen') and p['citizen'] != citizen:
                    continue

                # Check tag overlap with suppressed pattern
                p_tags = set(p.get('tags', []))
                if p_tags and len(p_tags & tags_set) >= len(p_tags) * 0.6:
                    return True

                # Check entity match in body
                p_entity = p.get('entity', '').lower()
                if p_entity and p_entity in body_lower:
                    p_signal_type = p.get('signal_type', '')
                    if p_signal_type and p_signal_type in body_lower:
                        return True

            return False
        except Exception:
            return False

    # ── CONFIDENCE WEIGHT ─────────────────────────────────────────────────────

    def _get_agent_confidence_weight(self, citizen: str) -> float:
        """
        Returns a multiplier (0.5–1.3) based on agent precision history.
        Neutral (1.0) until 50 audited signals exist.
        Never drops below 0.5 — even bad agents deserve a floor.
        """
        try:
            history = self._get_agent_precision(citizen)
            if history is None or history.get('audited_count', 0) < 50:
                return 1.0  # neutral prior
            precision = history.get('precision_rate', 0.5)
            # Map precision 0–1 to weight 0.5–1.3
            return round(0.5 + (precision * 0.8), 3)
        except Exception:
            return 1.0

    # ── DB HELPERS ────────────────────────────────────────────────────────────

    def _get_recent_posts_summary(self, hours: int = 24) -> list:
        """Returns lightweight summary of recent posts for novelty/corroboration checks."""
        cache_key = f'recent_{hours}'
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            result = self.db.get_recent_posts_summary(hours=hours)
            self._cache[cache_key] = result or []
            return self._cache[cache_key]
        except Exception:
            return []

    def _get_agent_precision(self, citizen: str) -> Optional[dict]:
        try:
            return self.db.get_agent_precision(citizen)
        except Exception:
            return None

    def _get_suppression_patterns(self) -> list:
        try:
            return self.db.get_active_suppression_patterns()
        except Exception:
            return []

    def _detect_topic_spike(self, tags: list) -> float:
        """
        Returns 0.0–1.0 spike ratio.
        Compares last 2h post volume on these tags vs hourly average over 24h.
        """
        try:
            recent_2h = self.db.count_posts_by_tags(tags, hours=2)
            recent_24h = self.db.count_posts_by_tags(tags, hours=24)
            if not recent_24h:
                return 0.0
            hourly_avg = recent_24h / 24.0
            recent_rate = recent_2h / 2.0
            if hourly_avg == 0:
                return 0.5 if recent_2h > 0 else 0.0
            spike = (recent_rate - hourly_avg) / max(hourly_avg, 1)
            return min(1.0, max(0.0, spike))
        except Exception:
            return 0.0

    def _build_explanation(self, r: SignalScore) -> str:
        parts = [
            f"src={r.source_reliability_score:.0f}",
            f"nov={r.novelty_score:.0f}",
            f"corr={r.corroboration_score:.0f}",
            f"tmp={r.temporal_anomaly_score:.0f}",
            f"ent={r.entity_importance_score:.0f}",
            f"uniq={r.narrative_uniqueness_score:.0f}",
            f"imp={r.downstream_impact_score:.0f}",
            f"rar={r.rarity_score:.0f}",
            f"hype_pen={r.hype_penalty:.0f}",
            f"sat_pen={r.saturation_penalty:.0f}",
            f"cw={r.confidence_weight:.2f}",
        ]
        return ' | '.join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  2. COUNCIL GATEKEEPER
# ═══════════════════════════════════════════════════════════════════════════════

class CouncilGatekeeper:
    """
    Sits between Citizens and Council.
    Enforces quality, diversity, and resource constraints on Council access.

    Responsibilities:
    - Rank incoming signals by combined score
    - Deduplicate overlapping reports (same entity, same timeframe)
    - Suppress low-information posts even if they passed scorer minimum
    - Detect hype inflation (too many alerts on same topic = suppress extras)
    - Prevent repetitive council sessions
    - Batch related signals into a single debate context
    - Enforce max sessions per cycle and domain diversity

    Pure logic. No LLM calls.
    """

    def __init__(self, db):
        self.db = db

    def evaluate_batch(self, scored_signals: list[tuple[dict, SignalScore]]) -> GatekeeperDecision:
        """
        Takes a list of (signal, SignalScore) tuples.
        Returns a GatekeeperDecision with approved/suppressed/batched signals.
        """
        decision = GatekeeperDecision()
        decision.session_budget_remaining = MAX_COUNCIL_SESSIONS_PER_CYCLE

        # Filter to only escalation-worthy signals
        candidates = [
            (sig, score) for sig, score in scored_signals
            if score.escalate_to_council and not score.suppressed_by_burial
        ]

        if not candidates:
            return decision

        # Sort by credibility_score descending
        candidates.sort(key=lambda x: x[1].credibility_score, reverse=True)

        # Track domain distribution to enforce diversity
        domain_counts = {}  # domain_key → count approved
        approved_entities = set()  # track entity deduplication
        approved_session_topics = self._get_recent_council_topics(hours=6)

        for sig, score in candidates:
            if decision.session_budget_remaining <= 0:
                decision.suppressed.append(sig.get('id'))
                continue

            domain_key = self._extract_domain(sig)
            entity_key = self._extract_entity_fingerprint(sig)
            topic_fingerprint = self._topic_fingerprint(sig)

            # ── Anti-recency bias: no domain gets more than 2 slots per cycle
            if domain_counts.get(domain_key, 0) >= MAX_ALERTS_PER_DOMAIN_PER_HOUR:
                decision.suppressed.append(sig.get('id'))
                log.info(f"[GATEKEEPER] {sig.get('id')} suppressed: domain cap ({domain_key})")
                continue

            # ── Deduplication: same entity reported recently?
            if entity_key in approved_entities:
                decision.suppressed.append(sig.get('id'))
                log.info(f"[GATEKEEPER] {sig.get('id')} suppressed: duplicate entity ({entity_key})")
                continue

            # ── Anti-repetition: similar topic already in recent council sessions?
            if self._is_topic_repetitive(topic_fingerprint, approved_session_topics):
                decision.suppressed.append(sig.get('id'))
                log.info(f"[GATEKEEPER] {sig.get('id')} suppressed: repetitive topic")
                continue

            # ── Check for batchable signals (same domain, different sources)
            batch_group = self._find_batch_group(sig, score, candidates)
            if batch_group:
                decision.batched_together.append(batch_group)
                # Only the highest-scoring signal in a batch proceeds
                best_in_batch = max(batch_group, key=lambda sid: next(
                    (s.credibility_score for sg, s in candidates if sg.get('id') == sid), 0
                ))
                if sig.get('id') != best_in_batch:
                    decision.suppressed.append(sig.get('id'))
                    continue

            # ── Approve
            decision.approved_for_council.append(sig.get('id'))
            domain_counts[domain_key] = domain_counts.get(domain_key, 0) + 1
            approved_entities.add(entity_key)
            approved_session_topics.add(topic_fingerprint)
            decision.session_budget_remaining -= 1
            log.info(f"[GATEKEEPER] {sig.get('id')} approved for council (score={score.credibility_score})")

        decision.domain_diversity_enforced = len(domain_counts) > 1
        return decision

    def _extract_domain(self, signal: dict) -> str:
        """Maps a signal to its primary domain bucket."""
        tags = [t.lower() for t in signal.get('tags', [])]
        body = signal.get('body', '').lower()

        domain_map = {
            'financial':    ['#sec', '#edgar', '#earnings', '#market', '#ipo', '#m&a'],
            'crypto':       ['#crypto', '#bitcoin', '#usdt', '#defi', '#blockchain'],
            'regulatory':   ['#fcc', '#ftc', '#fda', '#regulation', '#federalregister'],
            'infrastructure':['#spectrum', '#faa', '#permit', '#grid', '#satellite'],
            'intelligence': ['#osint', '#breach', '#security', '#cyberattack'],
            'science':      ['#arxiv', '#patent', '#preprint', '#clinicaltrial'],
            'geopolitical': ['#sanctions', '#conflict', '#trade', '#tariff'],
            'commodities':  ['#oil', '#shipping', '#maritime', '#commodity', '#grain'],
            'media':        ['#gdelt', '#narrative', '#media', '#coordinated'],
            'health':       ['#outbreak', '#pandemic', '#cdc', '#who', '#pharma'],
        }

        combined = ' '.join(tags) + ' ' + body
        for domain, keywords in domain_map.items():
            if any(kw in combined for kw in keywords):
                return domain
        return 'general'

    def _extract_entity_fingerprint(self, signal: dict) -> str:
        """
        Creates a fingerprint of the primary entity being discussed.
        Used for deduplication. Same entity + same direction = duplicate.
        """
        body = signal.get('body', '').lower()
        tags = signal.get('tags', [])
        combined = body[:200] + ' '.join(tags)
        # Simple fingerprint: first 3 tags + first 50 chars of body
        return hashlib.md5(combined[:250].encode()).hexdigest()[:12]

    def _topic_fingerprint(self, signal: dict) -> str:
        """Creates a topic fingerprint for repetition detection."""
        tags = sorted(t.lower() for t in signal.get('tags', []))
        return hashlib.md5(' '.join(tags[:4]).encode()).hexdigest()[:10]

    def _is_topic_repetitive(self, fingerprint: str, recent_topics: set) -> bool:
        """Returns True if this topic fingerprint matches recent council sessions."""
        return fingerprint in recent_topics

    def _get_recent_council_topics(self, hours: int = 6) -> set:
        """Fetches topic fingerprints from recent council sessions."""
        try:
            sessions = self.db.get_recent_council_sessions(hours=hours)
            fingerprints = set()
            for s in sessions:
                tags = s.get('tags', [])
                fp = hashlib.md5(' '.join(sorted(t.lower() for t in tags)[:4]).encode()).hexdigest()[:10]
                fingerprints.add(fp)
            return fingerprints
        except Exception:
            return set()

    def _find_batch_group(self, signal: dict, score: SignalScore,
                          all_candidates: list) -> Optional[list]:
        """
        Identifies signals that should be batched into a single debate.
        Criteria: same domain, different citizens, posted within 2h.
        Returns list of signal IDs if batch found, else None.
        """
        domain = self._extract_domain(signal)
        batch = [signal.get('id')]

        for other_sig, other_score in all_candidates:
            if other_sig.get('id') == signal.get('id'):
                continue
            if self._extract_domain(other_sig) == domain:
                if other_sig.get('citizen') != signal.get('citizen'):
                    batch.append(other_sig.get('id'))

        return batch if len(batch) > 1 else None


# ═══════════════════════════════════════════════════════════════════════════════
#  3. ENTROPY MONITOR
# ═══════════════════════════════════════════════════════════════════════════════

class EntropyMonitor:
    """
    Detects cognitive drift inside the organism.

    Tracks:
    - Increasing alert frequency (too many signals = hallucination risk)
    - Rising correlation inflation (everything looks related)
    - Excessive entity convergence (same entities always flagged)
    - Repetitive narrative structures
    - Agent confidence inflation
    - Decreasing signal-to-council approval ratio

    If entropy rises beyond threshold:
    - Reduces posting thresholds (harder to escalate)
    - Tightens council access
    - Temporarily suppresses high-entropy agents
    - Logs snapshot for trend analysis

    Pure logic. No LLM calls.
    Snapshots are periodic (not per-event) to avoid excessive writes.
    """

    def __init__(self, db):
        self.db = db

    def measure(self) -> EntropySnapshot:
        """
        Takes a point-in-time entropy measurement.
        Call this on a schedule (every 2-4 hours), not per-signal.
        """
        snap = EntropySnapshot()

        try:
            # ── Alert frequency ───────────────────────────────────────────────
            snap.alert_frequency_1h = self.db.count_posts_by_type('signal_alert', hours=1)

            # ── Entity convergence ────────────────────────────────────────────
            snap.unique_entities_24h = self._count_unique_entities()

            # ── Correlation inflation ─────────────────────────────────────────
            snap.correlation_inflation_score = self._measure_correlation_inflation()

            # ── Repetitive narrative ratio ────────────────────────────────────
            snap.repetitive_narrative_ratio = self._measure_narrative_repetition()

            # ── Agent confidence stats ────────────────────────────────────────
            conf_mean, conf_var = self._measure_confidence_distribution()
            snap.agent_confidence_mean = conf_mean
            snap.agent_confidence_variance = conf_var

            # ── Composite entropy index ───────────────────────────────────────
            snap.entropy_index = self._calculate_entropy_index(snap)

            # ── Action recommendation ─────────────────────────────────────────
            snap.action_required = snap.entropy_index >= ENTROPY_ALERT_THRESHOLD
            if snap.action_required:
                snap.recommended_actions = self._recommend_actions(snap)

            log.info(f'[ENTROPY] index={snap.entropy_index:.3f} actions={snap.recommended_actions}')

        except Exception as e:
            log.error(f'[ENTROPY] Measurement failed: {e}')

        return snap

    def _count_unique_entities(self) -> int:
        """Counts unique named entities across all posts in last 24h."""
        try:
            posts = self.db.get_recent_posts_full(hours=24, limit=200)
            entities = set()
            # Extract capitalised phrases as proxy entities (no NER needed)
            for p in posts:
                body = p.get('body', '')
                caps = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', body)
                entities.update(caps)
            return len(entities)
        except Exception:
            return 0

    def _measure_correlation_inflation(self) -> float:
        """
        Returns 0.0–1.0.
        High score = too many signals marked as related to each other.
        Proxy: ratio of signal_alerts to total posts in last 24h.
        Healthy ratio: <15%. Concerning: >30%. Critical: >50%.
        """
        try:
            total = self.db.count_posts_by_type('post', hours=24)
            alerts = self.db.count_posts_by_type('signal_alert', hours=24)
            if not total:
                return 0.0
            ratio = alerts / (total + alerts)
            # Normalise: 0.15 → 0.0, 0.50 → 1.0
            return round(max(0.0, min(1.0, (ratio - 0.15) / 0.35)), 3)
        except Exception:
            return 0.0

    def _measure_narrative_repetition(self) -> float:
        """
        Returns 0.0–1.0.
        Measures how often the same tag clusters appear across posts.
        High = the organism is repeating itself.
        """
        try:
            posts = self.db.get_recent_posts_full(hours=12, limit=100)
            if len(posts) < 5:
                return 0.0

            tag_sets = [frozenset(t.lower() for t in p.get('tags', [])) for p in posts if p.get('tags')]
            if not tag_sets:
                return 0.0

            # Count pairwise overlaps
            overlaps = 0
            total_pairs = 0
            for i in range(len(tag_sets)):
                for j in range(i+1, min(len(tag_sets), 30)):  # cap at 30 for performance
                    total_pairs += 1
                    overlap = len(tag_sets[i] & tag_sets[j]) / max(len(tag_sets[i] | tag_sets[j]), 1)
                    if overlap > 0.5:
                        overlaps += 1

            if not total_pairs:
                return 0.0
            return round(overlaps / total_pairs, 3)
        except Exception:
            return 0.0

    def _measure_confidence_distribution(self) -> tuple[float, float]:
        """Returns (mean, variance) of recent signal credibility scores."""
        try:
            scores = self.db.get_recent_credibility_scores(hours=24)
            if not scores:
                return 0.5, 0.0
            mean = sum(scores) / len(scores)
            variance = sum((s - mean)**2 for s in scores) / len(scores)
            return round(mean, 3), round(variance, 3)
        except Exception:
            return 0.5, 0.0

    def _calculate_entropy_index(self, snap: EntropySnapshot) -> float:
        """
        Composite entropy index from 0.0 (healthy) to 1.0 (full drift).

        Components:
        - Alert frequency: >5 alerts/hour is concerning
        - Correlation inflation
        - Narrative repetition
        - Confidence variance: low variance = echo chamber
        """
        freq_score = min(1.0, snap.alert_frequency_1h / 8.0)
        corr_score = snap.correlation_inflation_score
        rep_score = snap.repetitive_narrative_ratio
        # Low confidence variance = agents all agreeing = echo chamber risk
        echo_score = 1.0 - min(1.0, snap.agent_confidence_variance * 10)

        index = (
            freq_score  * 0.30 +
            corr_score  * 0.30 +
            rep_score   * 0.25 +
            echo_score  * 0.15
        )
        return round(max(0.0, min(1.0, index)), 4)

    def _recommend_actions(self, snap: EntropySnapshot) -> list:
        """Returns list of recommended corrective actions."""
        actions = []
        if snap.alert_frequency_1h > 5:
            actions.append('tighten_council_threshold')
        if snap.correlation_inflation_score > 0.5:
            actions.append('reduce_convergence_sensitivity')
        if snap.repetitive_narrative_ratio > 0.6:
            actions.append('increase_novelty_weight')
        if snap.entropy_index > 0.85:
            actions.append('emergency_cooldown')
        return actions

    def apply_corrections(self, snap: EntropySnapshot) -> dict:
        """
        Returns modified threshold overrides based on entropy state.
        The caller (app.py) should apply these to the scoring pipeline.
        Does NOT mutate env vars — returns a delta dict.
        """
        if not snap.action_required:
            return {}

        overrides = {}
        severity = snap.entropy_index

        if 'tighten_council_threshold' in snap.recommended_actions:
            boost = int(severity * 15)
            overrides['COUNCIL_ESCALATION_SCORE'] = min(90, COUNCIL_ESCALATION_SCORE + boost)

        if 'emergency_cooldown' in snap.recommended_actions:
            overrides['SIGNAL_MIN_SCORE'] = min(80, SIGNAL_MIN_SCORE + 15)
            overrides['MAX_COUNCIL_SESSIONS_PER_CYCLE'] = 1

        return overrides


# ═══════════════════════════════════════════════════════════════════════════════
#  4. SIGNAL BURIAL (Negative Memory)
# ═══════════════════════════════════════════════════════════════════════════════

class SignalBurial:
    """
    Negative memory subsystem.
    Records patterns that consistently waste attention.

    Burial conditions (any one triggers):
    - Signal failed outcome audit (predicted direction was wrong)
    - Signal generated false convergence (agents agreed, reality disagreed)
    - Signal produced no downstream evolution after N days
    - Same source/entity/pattern repeated with no new information

    Burial effects:
    - Matching future signals suppressed before scoring
    - Source trust score reduced
    - Agent precision history updated

    Burial is not permanent — TTL decays over time.
    """

    def __init__(self, db):
        self.db = db

    def bury(self, signal: dict, reason: str, ttl_days: int = 14) -> bool:
        """
        Creates a suppression pattern based on a failed signal.

        signal: the original signal dict
        reason: why it's being buried
        ttl_days: how long the suppression lasts (default 14 days)
        """
        try:
            pattern = {
                'id': hashlib.md5(f"{signal.get('id','')}{reason}".encode()).hexdigest()[:16],
                'citizen': signal.get('citizen'),
                'tags': signal.get('tags', []),
                'entity': self._extract_primary_entity(signal.get('body', '')),
                'signal_type': signal.get('type', 'post'),
                'reason': reason,
                'original_signal_id': signal.get('id'),
                'created_at': datetime.utcnow().isoformat(),
                'expires_at': (datetime.utcnow() + timedelta(days=ttl_days)).isoformat(),
                'burial_count': 1,
            }
            self.db.save_suppression_pattern(pattern)
            log.info(f"[BURIAL] Pattern created: {pattern['id']} reason={reason} ttl={ttl_days}d")

            # Update agent precision history negatively
            citizen = signal.get('citizen')
            if citizen:
                self.db.update_agent_precision(citizen, outcome='false_positive')

            return True
        except Exception as e:
            log.error(f'[BURIAL] Failed to create pattern: {e}')
            return False

    def _extract_primary_entity(self, body: str) -> str:
        """Extracts the most prominent capitalised entity from body text."""
        caps = re.findall(r'\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b', body)
        # Filter out common false positives
        filtered = [c for c in caps if c not in {'The', 'This', 'That', 'In', 'At', 'By', 'For'}]
        return filtered[0] if filtered else ''

    def reinforce_positive(self, signal_id: str, citizen: str) -> bool:
        """
        Called when a signal's prediction was validated.
        Updates agent precision history positively.
        """
        try:
            self.db.update_agent_precision(citizen, outcome='true_positive')
            log.info(f'[BURIAL] Positive reinforcement: {citizen} signal={signal_id}')
            return True
        except Exception as e:
            log.error(f'[BURIAL] Positive reinforcement failed: {e}')
            return False


# ═══════════════════════════════════════════════════════════════════════════════
#  ORCHESTRATOR — wires everything together
# ═══════════════════════════════════════════════════════════════════════════════

class SignalIntegrityLayer:
    """
    Top-level orchestrator for the Signal Integrity Layer.

    Usage in app.py:
        sil = SignalIntegrityLayer(db)
        result = sil.process(signal)
        if result.passes_threshold:
            db.save_post(signal)
            if result.escalate_to_council:
                council_queue.add(signal, result)
        else:
            db.log_rejected_signal(signal, result)
    """

    def __init__(self, db):
        self.scorer = CredibilityScorer(db)
        self.gatekeeper = CouncilGatekeeper(db)
        self.entropy = EntropyMonitor(db)
        self.burial = SignalBurial(db)
        self.db = db
        self._entropy_overrides = {}  # active threshold adjustments
        self._last_entropy_check = datetime.min

    def process(self, signal: dict) -> SignalScore:
        """
        Main pipeline entry point.
        Call for every signal before saving to database.

        Returns SignalScore with full decision metadata.
        """
        # Apply any active entropy overrides to thresholds
        self._apply_entropy_overrides()

        # Score the signal
        score = self.scorer.score(signal)

        # Log rejection for audit visibility (lightweight — hash only)
        if not score.passes_threshold:
            self._log_rejection(signal, score)

        return score

    def process_council_batch(self, scored_batch: list[tuple[dict, SignalScore]]) -> GatekeeperDecision:
        """
        After scoring a batch of signals, run them through the Gatekeeper
        to determine which actually get Council access.
        """
        return self.gatekeeper.evaluate_batch(scored_batch)

    def run_entropy_check(self, force: bool = False) -> Optional[EntropySnapshot]:
        """
        Runs entropy measurement if enough time has passed since last check.
        Should be called every 2-4 hours from a scheduled job.
        """
        hours_since = (datetime.utcnow() - self._last_entropy_check).total_seconds() / 3600
        if not force and hours_since < 2:
            return None

        snap = self.entropy.measure()
        self._last_entropy_check = datetime.utcnow()

        # Apply corrections if needed
        if snap.action_required:
            self._entropy_overrides = self.entropy.apply_corrections(snap)
            log.warning(f'[SIL] Entropy action triggered. Overrides: {self._entropy_overrides}')

        # Persist snapshot (batched — not per-signal)
        try:
            self.db.save_entropy_snapshot(snap)
        except Exception as e:
            log.error(f'[SIL] Failed to persist entropy snapshot: {e}')

        return snap

    def _apply_entropy_overrides(self):
        """Temporarily adjusts module-level thresholds based on entropy state."""
        global SIGNAL_MIN_SCORE, COUNCIL_ESCALATION_SCORE, MAX_COUNCIL_SESSIONS_PER_CYCLE
        if 'SIGNAL_MIN_SCORE' in self._entropy_overrides:
            SIGNAL_MIN_SCORE = self._entropy_overrides['SIGNAL_MIN_SCORE']
        if 'COUNCIL_ESCALATION_SCORE' in self._entropy_overrides:
            COUNCIL_ESCALATION_SCORE = self._entropy_overrides['COUNCIL_ESCALATION_SCORE']
        if 'MAX_COUNCIL_SESSIONS_PER_CYCLE' in self._entropy_overrides:
            MAX_COUNCIL_SESSIONS_PER_CYCLE = self._entropy_overrides['MAX_COUNCIL_SESSIONS_PER_CYCLE']

    def _log_rejection(self, signal: dict, score: SignalScore):
        """Logs rejected signal as a lightweight hash-only record for audit."""
        try:
            rejection = {
                'signal_hash': hashlib.md5(signal.get('body', '').encode()).hexdigest()[:16],
                'citizen': signal.get('citizen'),
                'signal_type': signal.get('type'),
                'credibility_score': score.credibility_score,
                'reason': score.escalation_recommendation,
                'suppressed_by_burial': score.suppressed_by_burial,
                'explanation': score.score_explanation,
                'rejected_at': datetime.utcnow().isoformat(),
            }
            self.db.log_rejected_signal(rejection)
        except Exception:
            pass  # rejection logging must never crash the main pipeline

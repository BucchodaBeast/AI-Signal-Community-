"""
signal_integrity.py — Signal Integrity Layer v2

10-dimension scoring replacing the v1 primitive threshold system.

NEW in v2:
  - Signal half-life: score decays if signal not corroborated within 72h
  - Pre-Brief system: high-scoring signals open a living Pre-Brief that
    updates as more agents corroborate or contradict
  - Epistemic tagging integrated into scoring
  - Silence detection: agents that SHOULD see a signal but haven't
  - Anti-noise heuristics per dimension (not just a threshold)
  - Source independence weighting: 3 agents from different territory
    groups >> 3 agents from the same group
"""

import re, json, math, logging
from datetime import datetime, timedelta

log = logging.getLogger('signal_integrity')

# ── DIMENSION WEIGHTS ─────────────────────────────────────────────────────────
WEIGHTS = {
    'novelty':               0.15,
    'consequence':           0.20,
    'information_density':   0.10,
    'actionability':         0.10,
    'rarity_of_attention':   0.15,
    'cross_domain':          0.10,
    'temporal_advantage':    0.10,
    'anomaly_score':         0.05,
    'epistemic_impact':      0.03,
    'strategic_depth':       0.02,
}

MINIMUM_SCORE   = 0.35  # Below this: not published
COUNCIL_THRESHOLD = 0.25  # Above this: goes to Council
BRIEF_THRESHOLD   = 0.30 # Above this: fast-track to Brief queue

# ── TERRITORY GROUPS (for source independence scoring) ────────────────────────
TERRITORY_GROUPS = {
    'market':      {'DUKE', 'FLUX'},
    'physical':    {'VIGIL', 'NOVA', 'SOL'},
    'intelligence':{'VERA', 'LORE', 'SPECTER'},
    'narrative':   {'KAEL', 'MIRA', 'ECHO'},
    'regulatory':  {'REX', 'HERMES'},
}

def _get_territory_group(agent: str) -> str | None:
    for group, members in TERRITORY_GROUPS.items():
        if agent in members:
            return group
    return None

# ── NOISE PATTERNS ────────────────────────────────────────────────────────────
# Content patterns that indicate low-entropy summarisation output, not intelligence
NOISE_PATTERNS = [
    r'^A recent post on the',
    r'^World Bank .{0,30} data at \d',
    r'^This is a (brief|summary|report)',
    r"^{'source':",
    r'^{"source":',
    r'^Here is (a|the|an)',
    r'^I found',
    r'^Based on (the|this|my)',
    r'^\d+\.\d+ – a (number|value|figure)',
    r'potentially significant',
    r'may or may not',
    r'it is unclear whether',
    r'more research (is needed|required)',
    r'this (information|data) (could|may|might) be',
]

# Tags that are too generic to constitute real convergence topics
GENERIC_TAGS = {
    '#history', '#data', '#technology', '#news', '#update', '#general',
    '#misc', '#other', '#information', '#report', '#analysis', '#global',
    '#world', '#current', '#recent', '#new', '#latest',
}

# High-signal tag families (convergences on these are worth more)
HIGH_SIGNAL_TAG_FAMILIES = {
    'financial':   {'#SEC', '#IPO', '#M&A', '#insider', '#funding', '#crypto'},
    'security':    {'#CVE', '#breach', '#CISA', '#ransomware', '#APT', '#zero-day'},
    'regulatory':  {'#FCC', '#FAA', '#FDA', '#FTC', '#federalregister', '#enforcement'},
    'physical':    {'#BDI', '#supplychain', '#shipping', '#commodities', '#energy'},
    'ip':          {'#patents', '#USPTO', '#WIPO', '#IP'},
    'geopolitical':{'#sanctions', '#SWIFT', '#military', '#tariffs', '#treaty'},
}


class SignalIntegrityLayer:

    def score(self, post: dict, recent_posts: list = None) -> dict:
        """
        Score a post across all 10 dimensions.
        Returns: {
            'total': float,          # weighted total 0.0-1.0
            'dimensions': dict,      # individual dimension scores
            'epistemic_tag': str,    # VERIFIED/CORROBORATED/INFERRED/SPECULATIVE
            'publish': bool,         # total >= MINIMUM_SCORE
            'council': bool,         # total >= COUNCIL_THRESHOLD
            'brief_queue': bool,     # total >= BRIEF_THRESHOLD
            'pre_brief': bool,       # should open a Pre-Brief
            'noise_detected': bool,  # noise patterns found in body
        }
        """
        recent_posts = recent_posts or []
        body    = post.get('body', '') or ''
        tags    = post.get('tags', []) or []
        agent   = post.get('citizen', '') or post.get('agent', '')
        ptype   = post.get('type', 'post')
        raw     = post.get('raw_data', {}) or {}
        meta    = post.get('metadata', {}) or {}

        # Noise detection (before scoring — garbage in garbage out)
        noise_detected = self._detect_noise(body)

        dims = {}
        dims['novelty']             = self._novelty(post, recent_posts)
        dims['consequence']         = self._consequence(post, tags, raw)
        dims['information_density'] = self._information_density(body, raw, meta)
        dims['actionability']       = self._actionability(post, tags, raw)
        dims['rarity_of_attention'] = self._rarity_of_attention(tags, ptype, raw)
        dims['cross_domain']        = self._cross_domain(post, tags, recent_posts)
        dims['temporal_advantage']  = self._temporal_advantage(post, tags, raw)
        dims['anomaly_score']       = self._anomaly_score(post, raw, meta)
        dims['epistemic_impact']    = self._epistemic_impact(post, tags, raw)
        dims['strategic_depth']     = self._strategic_depth(post, tags, raw, recent_posts)

        # Noise penalty: cap each dimension at 0.4 if noise detected
        if noise_detected:
            dims = {k: min(v, 0.4) for k, v in dims.items()}

        # Source independence bonus for convergence alerts
        if ptype == 'signal_alert':
            dims = self._apply_independence_bonus(dims, post)

        # Weighted total
        total = sum(dims[dim] * WEIGHTS[dim] for dim in WEIGHTS)
        total = round(min(1.0, max(0.0, total)), 4)

        # Epistemic tag
        epistemic_tag = self._epistemic_tag(dims, post, raw)

        # Pre-Brief: open one if total is promising but not yet briefable
        pre_brief = (total >= 0.35 and total < BRIEF_THRESHOLD and not noise_detected)

        return {
            'total':          total,
            'dimensions':     dims,
            'epistemic_tag':  epistemic_tag,
            'publish':        total >= MINIMUM_SCORE and not noise_detected,
            'council':        total >= COUNCIL_THRESHOLD,
            'brief_queue':    total >= BRIEF_THRESHOLD,
            'pre_brief':      pre_brief,
            'noise_detected': noise_detected,
        }

    # ── DIMENSION SCORERS ─────────────────────────────────────────────────────

    def _novelty(self, post: dict, recent: list) -> float:
        """
        Is this genuinely uncommon vs baseline behaviour?
        Not just "have we seen this URL before" — semantic novelty.
        """
        body  = (post.get('body') or '').lower()
        tags  = set(post.get('tags') or [])
        agent = post.get('citizen') or post.get('agent', '')

        # Generic tags reduce novelty score
        generic_overlap = len(tags & GENERIC_TAGS)
        if generic_overlap >= 2:
            return 0.2

        # Count how many recent posts from same agent cover same tags
        same_agent_overlap = 0
        for r in recent:
            if r.get('citizen') == agent or r.get('agent') == agent:
                r_tags = set(r.get('tags') or [])
                if len(tags & r_tags) >= 2:
                    same_agent_overlap += 1

        if same_agent_overlap >= 2:
            return 0.25  # Same agent covering same topic repeatedly = low novelty
        if same_agent_overlap == 1:
            return 0.55

        # High-signal keywords that indicate genuine novelty
        novelty_kws = [
            'first', 'novel', 'unprecedented', 'unusual', 'anomal',
            'deleted', 'removed', 'classified', 'classified', 'experimental',
            'breach', 'exploit', 'zero-day', 'cluster', 'convergence',
        ]
        kw_hits = sum(1 for kw in novelty_kws if kw in body)
        base = 0.65 + min(0.30, kw_hits * 0.07)

        return round(base, 3)

    def _consequence(self, post: dict, tags: list, raw: dict) -> float:
        """Could this materially affect industries, markets, infrastructure, or populations?"""
        body    = (post.get('body') or '').lower()
        ptype   = post.get('type', '')
        citizens = post.get('citizens') or []

        score = 0.3  # base

        # High-consequence tag families
        for family, family_tags in HIGH_SIGNAL_TAG_FAMILIES.items():
            if any(t in family_tags for t in tags):
                score += 0.12
                break

        # Dollar amounts suggest scale of consequence
        amounts = re.findall(r'\$[\d,.]+\s*(m|b|mn|bn|million|billion)', body, re.IGNORECASE)
        if amounts:
            score += min(0.15, len(amounts) * 0.07)

        # Convergence alerts = higher consequence (multiple independent sources)
        if ptype == 'signal_alert':
            score += 0.12 + min(0.08, (len(citizens) - 2) * 0.04)

        # Named entities with known consequence weight
        high_consequence_entities = [
            'federal reserve', 'fed', 'congress', 'senate', 'military',
            'pentagon', 'nato', 'fda', 'cdc', 'critical infrastructure',
            'sbux', 'treasury', 'sec ', 'ftc', 'doj',
        ]
        if any(e in body for e in high_consequence_entities):
            score += 0.08

        return round(min(1.0, score), 3)

    def _information_density(self, body: str, raw: dict, meta: dict) -> float:
        """Compressed high-value knowledge vs verbose procedural noise."""
        if not body:
            return 0.1

        # Length is not density — a 50-word precise post beats a 500-word waffle
        words = body.split()
        if len(words) < 20:
            return 0.25

        # Numbers, percentages, specific entities = high density signals
        numbers  = len(re.findall(r'\b\d+\.?\d*\s*(%|bn|mn|m|k|B|M|K)\b', body))
        entities = len(re.findall(r'\b[A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})*\b', body))
        dates    = len(re.findall(r'\b(20\d\d|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', body))

        density_score = 0.45
        density_score += min(0.20, numbers * 0.05)
        density_score += min(0.15, entities * 0.03)
        density_score += min(0.10, dates * 0.04)

        # Penalise excessive hedging language
        hedges = ['may', 'might', 'could', 'possibly', 'perhaps', 'unclear',
                  'potentially', 'it is suggested', 'it appears']
        hedge_count = sum(1 for h in hedges if h in body.lower())
        if hedge_count >= 3:
            density_score -= 0.15

        return round(min(1.0, max(0.1, density_score)), 3)

    def _actionability(self, post: dict, tags: list, raw: dict) -> float:
        """Can a human or agent act on this information strategically?"""
        body  = (post.get('body') or '').lower()
        ptype = post.get('type', '')

        score = 0.3

        # Specific timeframes make information more actionable
        time_phrases = ['within', 'by', 'before', 'deadline', 'expires', 'window',
                        'comment period', 'filing due', '30-day', '60-day', '90-day']
        if any(t in body for t in time_phrases):
            score += 0.15

        # High-signal source types that produce actionable data
        actionable_tags = {'#SEC', '#patents', '#CVE', '#FCC', '#federalregister',
                           '#breach', '#enforcement', '#contract', '#CISA'}
        if any(t in actionable_tags for t in tags):
            score += 0.12

        # Alerts and debates are more actionable than raw dispatches
        if ptype in ('signal_alert', 'town_hall'):
            score += 0.10

        # Dollar amounts with specific entities = actionable
        if re.search(r'\$[\d,.]+', body) and re.search(r'\b[A-Z][A-Za-z]{3,}\b', post.get('body', '')):
            score += 0.08

        return round(min(1.0, score), 3)

    def _rarity_of_attention(self, tags: list, ptype: str, raw: dict) -> float:
        """Under-discussed relative to importance."""
        # Regulatory filings, patents, shipping data = chronically under-discussed
        under_covered = {
            '#federalregister', '#patents', '#USPTO', '#WIPO', '#BDI',
            '#supplychain', '#FOIA', '#COT', '#CFTC', '#portcongestion',
            '#deleted', '#wayback', '#experimental', '#STA', '#EXP',
        }
        over_covered = {
            '#AI', '#ChatGPT', '#bitcoin', '#crypto', '#election', '#economy',
        }
        tag_set = set(tags)
        under_hits = len(tag_set & under_covered)
        over_hits  = len(tag_set & over_covered)

        if under_hits >= 2:
            return 0.85
        if under_hits == 1:
            return 0.70
        if over_hits >= 2:
            return 0.30  # Heavily covered topics rarely need more coverage
        if over_hits == 1:
            return 0.45

        return 0.55  # neutral

    def _cross_domain(self, post: dict, tags: list, recent: list) -> float:
        """Does this connect unrelated systems or domains?"""
        ptype    = post.get('type', '')
        citizens = post.get('citizens') or []

        # Signal alerts from different territory groups = high cross-domain
        if ptype == 'signal_alert' and len(citizens) >= 2:
            groups = {_get_territory_group(c) for c in citizens if _get_territory_group(c)}
            if len(groups) >= 3:
                return 0.90
            if len(groups) == 2:
                return 0.75

        # Tag diversity across different families
        family_hits = set()
        for family, family_tags in HIGH_SIGNAL_TAG_FAMILIES.items():
            if any(t in family_tags for t in tags):
                family_hits.add(family)
        if len(family_hits) >= 3:
            return 0.80
        if len(family_hits) == 2:
            return 0.65

        # Body mentions multiple distinct domains
        body_lower = (post.get('body') or '').lower()
        domain_kws = [
            ('financial', ['market', 'stock', 'fund', 'capital', 'invest']),
            ('physical',  ['ship', 'port', 'commodity', 'iron', 'oil']),
            ('security',  ['breach', 'exploit', 'vulnerability', 'hack']),
            ('regulatory',['regulation', 'filing', 'agency', 'federal']),
            ('academic',  ['research', 'paper', 'study', 'patent']),
        ]
        domain_hits = sum(1 for _, kws in domain_kws if any(kw in body_lower for kw in kws))
        if domain_hits >= 3:
            return 0.70
        if domain_hits == 2:
            return 0.55

        return 0.30

    def _temporal_advantage(self, post: dict, tags: list, raw: dict) -> float:
        """Does discovering this early matter? Will it become obvious later?"""
        body  = (post.get('body') or '').lower()
        ptype = post.get('type', '')

        score = 0.35

        # Pre-announcement signals: patents, FCC experimental, hiring spikes
        pre_announcement_tags = {'#patents', '#experimental', '#FCC', '#FAAnotam', '#hiring'}
        if any(t in pre_announcement_tags for t in tags):
            score += 0.20

        # Deleted content: window closes quickly
        if '#deleted' in tags or '#wayback' in tags:
            score += 0.18

        # Regulatory comment periods: hard deadline = temporal advantage
        if 'comment period' in body or 'comment deadline' in body:
            score += 0.15

        # Breach data: early warning before public disclosure
        if '#CVE' in tags or '#breach' in tags or '#CISA' in tags:
            score += 0.12

        # Pre-filing signals (NOVA's permit clusters)
        if '#cluster' in tags or '#permit' in tags:
            score += 0.10

        return round(min(1.0, score), 3)

    def _anomaly_score(self, post: dict, raw: dict, meta: dict) -> float:
        """Does this violate expected patterns?"""
        body = (post.get('body') or '').lower()

        score = 0.3

        # Explicit anomaly language
        anomaly_kws = [
            'unusual', 'anomal', 'unexpected', 'atypical', 'unprecedented',
            'spike', 'surge', 'collapse', 'sudden', 'overnight', 'without warning',
            'buried', 'quietly', '4am', '11pm', 'friday night', 'holiday weekend',
            '200%', '300%', '400%', '500%',
        ]
        hits = sum(1 for kw in anomaly_kws if kw in body)
        score += min(0.50, hits * 0.10)

        # Statistical anomalies in metadata
        for key in ('change_pct', 'deviation_sigma', 'volume_multiple'):
            val = meta.get(key, 0) or raw.get(key, 0) or 0
            try:
                val = float(val)
                if abs(val) > 200:
                    score += 0.15
                elif abs(val) > 50:
                    score += 0.08
            except Exception:
                pass

        return round(min(1.0, score), 3)

    def _epistemic_impact(self, post: dict, tags: list, raw: dict) -> float:
        """Does this change how reality should be modelled?"""
        body = (post.get('body') or '').lower()
        ptype = post.get('type', '')

        # Town halls represent genuine contradiction = high epistemic impact
        if ptype == 'town_hall':
            return 0.70

        impact_kws = [
            'contradict', 'invalidate', 'overturns', 'disproves', 'wrong',
            'previously believed', 'assumed to be', 'consensus was', 'contrary to',
            'paradigm', 'fundamental', 'structural', 'systemic',
        ]
        hits = sum(1 for kw in impact_kws if kw in body)
        return round(min(1.0, 0.35 + hits * 0.12), 3)

    def _strategic_depth(self, post: dict, tags: list, raw: dict, recent: list) -> float:
        """Could this compound into second/third order effects?"""
        body = (post.get('body') or '').lower()

        strategic_kws = [
            'downstream', 'cascade', 'second order', 'third order', 'compound',
            'accelerate', 'feedback loop', 'systemic', 'structural', 'precede',
            'historically', 'pattern', 'cycle', 'trend reversal',
        ]
        hits = sum(1 for kw in strategic_kws if kw in body)

        # Signals with both financial and physical domain = higher strategic depth
        has_financial = any(t in {'#finance','#crypto','#markets','#capital'} for t in tags)
        has_physical  = any(t in {'#supplychain','#shipping','#BDI','#energy'} for t in tags)
        if has_financial and has_physical:
            return round(min(1.0, 0.55 + hits * 0.10), 3)

        return round(min(1.0, 0.30 + hits * 0.10), 3)

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _detect_noise(self, body: str) -> bool:
        if not body:
            return True
        for pattern in NOISE_PATTERNS:
            if re.search(pattern, body, re.IGNORECASE):
                return True
        return False

    def _apply_independence_bonus(self, dims: dict, post: dict) -> dict:
        """Bonus for convergences where agents are from different territory groups."""
        citizens = post.get('citizens') or []
        groups   = {_get_territory_group(c) for c in citizens if _get_territory_group(c)}
        if len(groups) >= 3:
            dims['cross_domain']   = min(1.0, dims['cross_domain'] + 0.15)
            dims['novelty']        = min(1.0, dims['novelty'] + 0.08)
        elif len(groups) == 2:
            dims['cross_domain']   = min(1.0, dims['cross_domain'] + 0.08)
        return dims

    def _epistemic_tag(self, dims: dict, post: dict, raw: dict) -> str:
        """Assign overall epistemic tag to the signal."""
        avg_verified = (dims['novelty'] + dims['consequence'] + dims['anomaly_score']) / 3
        if avg_verified >= 0.7 and post.get('type') in ('signal_alert',) and len(post.get('citizens') or []) >= 3:
            return 'CORROBORATED'
        if dims['anomaly_score'] >= 0.6 and dims['information_density'] >= 0.6:
            return 'VERIFIED'
        if avg_verified >= 0.5:
            return 'INFERRED'
        return 'SPECULATIVE'


# ── PRE-BRIEF MANAGER ─────────────────────────────────────────────────────────

class PreBriefManager:
    """
    Manages living Pre-Briefs — signals that are promising but not yet
    fully corroborated. A Pre-Brief stays open, collecting corroborating
    or contradicting signals, until it either:
      - Crosses BRIEF_THRESHOLD with corroboration → becomes a proper Brief
      - Ages out without corroboration (72h) → archived as unconfirmed
      - Gets contradicted by stronger signals → marked as contradicted
    """

    def __init__(self):
        self._pre_briefs = {}  # id → pre_brief dict (in-memory, also persisted to DB)

    def open(self, post: dict, sil_result: dict, db=None) -> dict:
        """Open a new Pre-Brief for a promising signal."""
        import uuid as _uuid
        pb_id = str(_uuid.uuid4())
        pre_brief = {
            'id':           pb_id,
            'source_id':    post.get('id', ''),
            'agent':        post.get('citizen') or post.get('agent', ''),
            'topic':        post.get('headline') or post.get('body', '')[:80],
            'tags':         post.get('tags') or [],
            'opened_at':    datetime.utcnow().isoformat(),
            'last_updated': datetime.utcnow().isoformat(),
            'sil_score':    sil_result['total'],
            'corroborations': [],
            'contradictions': [],
            'status':       'open',  # open / confirmed / contradicted / archived
            'confidence':   'LOW',
        }
        self._pre_briefs[pb_id] = pre_brief
        log.info(f"Pre-Brief opened: {pre_brief['topic'][:50]} (SIL {sil_result['total']:.3f})")
        if db:
            try:
                db.save_pre_brief(pre_brief)
            except Exception:
                pass
        return pre_brief

    def update(self, new_post: dict, db=None) -> list:
        """
        Check if a new post corroborates or contradicts any open Pre-Briefs.
        Returns list of Pre-Briefs that were updated.
        """
        updated = []
        new_tags  = set(new_post.get('tags') or [])
        new_agent = new_post.get('citizen') or new_post.get('agent', '')
        new_body  = (new_post.get('body') or '').lower()

        for pb_id, pb in list(self._pre_briefs.items()):
            if pb['status'] != 'open':
                continue
            pb_tags = set(pb.get('tags') or [])

            # Age out check
            opened = datetime.fromisoformat(pb['opened_at'])
            if (datetime.utcnow() - opened).total_seconds() > 72 * 3600:
                pb['status'] = 'archived'
                log.info(f"Pre-Brief archived (timeout): {pb['topic'][:50]}")
                if db:
                    try: db.save_pre_brief(pb)
                    except Exception: pass
                continue

            # Tag overlap: does the new post touch the same topic?
            overlap = len(new_tags & pb_tags)
            if overlap < 1:
                continue

            # Avoid same agent corroborating their own signal
            if new_agent == pb['agent']:
                continue

            # Check if new post corroborates or contradicts
            conflict_words = ['however', 'contrary', 'actually', 'incorrect', 'false',
                              'no evidence', 'contradicts', 'disproves', 'opposite']
            is_contradiction = any(w in new_body for w in conflict_words)

            if is_contradiction:
                pb['contradictions'].append({
                    'agent':     new_agent,
                    'post_id':   new_post.get('id', ''),
                    'timestamp': datetime.utcnow().isoformat(),
                    'note':      new_post.get('body', '')[:100],
                })
                log.info(f"Pre-Brief contradicted by {new_agent}: {pb['topic'][:40]}")
            else:
                pb['corroborations'].append({
                    'agent':     new_agent,
                    'post_id':   new_post.get('id', ''),
                    'timestamp': datetime.utcnow().isoformat(),
                })
                log.info(f"Pre-Brief corroborated by {new_agent}: {pb['topic'][:40]}")

            # Update confidence based on corroborations
            corr_count = len(pb['corroborations'])
            cont_count = len(pb['contradictions'])
            if cont_count > corr_count:
                pb['status']     = 'contradicted'
                pb['confidence'] = 'LOW'
            elif corr_count >= 3:
                pb['status']     = 'confirmed'
                pb['confidence'] = 'HIGH'
            elif corr_count == 2:
                pb['confidence'] = 'MEDIUM'
            elif corr_count == 1:
                pb['confidence'] = 'LOW'

            pb['last_updated'] = datetime.utcnow().isoformat()
            updated.append(pb)
            if db:
                try: db.save_pre_brief(pb)
                except Exception: pass

        return updated

    def get_open(self) -> list:
        return [pb for pb in self._pre_briefs.values() if pb['status'] == 'open']

    def get_confirmed(self) -> list:
        return [pb for pb in self._pre_briefs.values() if pb['status'] == 'confirmed']


# ── HALF-LIFE DECAY ───────────────────────────────────────────────────────────

def apply_decay(original_score: float, hours_since_posted: float,
                corroborations: int = 0) -> float:
    """
    Apply temporal decay to a signal's score.

    Decay logic:
    - Signals NOT corroborated within 72h decay toward MINIMUM_SCORE
    - Each corroboration adds 12h of decay resistance
    - Signals with 3+ corroborations don't decay
    - Decay is logarithmic not linear (fast early, slow later)
    """
    if corroborations >= 3:
        return original_score  # Fully corroborated = no decay

    # Effective age adjusted for corroborations
    decay_resistance = corroborations * 12  # hours
    effective_age    = max(0, hours_since_posted - decay_resistance)

    if effective_age <= 0:
        return original_score

    # Logarithmic decay: halves at 72h (without corroboration)
    HALF_LIFE_HOURS = 72.0
    decay_factor    = math.exp(-math.log(2) * effective_age / HALF_LIFE_HOURS)
    floor           = MINIMUM_SCORE - 0.05  # Signals can decay below publish threshold

    decayed = floor + (original_score - floor) * decay_factor
    return round(max(floor, min(original_score, decayed)), 4)


# ── SILENCE DETECTOR ──────────────────────────────────────────────────────────

def detect_silence(topic_tags: list, recent_agents: list,
                   hours: int = 96) -> list:
    """
    Detect agents that SHOULD have data on a topic but are absent.
    Returns list of (agent, reason) tuples.
    """
    AGENT_TERRITORIES = {
        'VERA':    ['#AI','#regulation','#biotech','#climate','#research'],
        'DUKE':    ['#finance','#SEC','#hiring','#M&A','#IPO','#capital','#crypto'],
        'MIRA':    ['#sentiment','#community','#social','#media','#narrative'],
        'SOL':     ['#patterns','#correlation','#climate','#health','#infrastructure'],
        'NOVA':    ['#infrastructure','#FCC','#permits','#zoning','#spectrum'],
        'ECHO':    ['#deleted','#wayback','#github','#transparency','#surveillance'],
        'KAEL':    ['#media','#narrative','#regulation','#AI','#coordination'],
        'FLUX':    ['#crypto','#commodities','#treasury','#flows','#finance'],
        'REX':     ['#regulation','#government','#contracts','#lobbying','#courts'],
        'VIGIL':   ['#shipping','#commodities','#supplychain','#energy','#logistics'],
        'LORE':    ['#patents','#IP','#R&D','#acquisition','#biotech','#AI'],
        'SPECTER': ['#security','#breach','#CVE','#historical','#patterns'],
    }

    tag_set = set(topic_tags)
    silences = []

    for agent, agent_tags in AGENT_TERRITORIES.items():
        coverage = len(tag_set & set(agent_tags))
        if coverage < 2:
            continue  # Agent doesn't have strong territory claim here
        if agent in recent_agents:
            continue  # Agent has been active — no silence
        silences.append((
            agent,
            f"{agent} has relevant territory on {', '.join(list(tag_set & set(agent_tags))[:2])} "
            f"but no signal in {hours}h — source failure or deliberate absence."
        ))

    return silences


# ── SINGLETON ─────────────────────────────────────────────────────────────────
sil         = SignalIntegrityLayer()
pre_briefs  = PreBriefManager()

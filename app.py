"""
The Signal Society — Flask Backend v2
======================================

Changes from v1:
  - Dynamic Council: assembles domain-expert panel per signal (not fixed AXIOM/DOUBT/LACUNA)
  - HERMES verified tab: /api/verified endpoint serves Verified Intelligence Reports
  - Pre-Brief system: promising signals open living Pre-Briefs that update as corroboration arrives
  - Signal half-life decay: scores decay logarithmically without corroboration (72h half-life)
  - Silence detection: /api/silence endpoint surfaces agents absent from expected topics
  - Convergence gate: territory independence check + blacklist of generic tags
  - CASSANDRA duplicate job fixed (was silently overwriting the 6h job with a 3h one)
  - /api/pre_briefs endpoint for the UI pre-brief monitor
  - /api/contradiction endpoint for brief contradiction index
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import logging, os, json, uuid, threading
from dotenv import load_dotenv

load_dotenv()

from database import db
from agents.vera      import VeraAgent
from agents.duke      import DukeAgent
from agents.mira      import MiraAgent
from agents.sol       import SolAgent
from agents.nova      import NovaAgent
from agents.echo      import EchoAgent
from agents.kael      import KaelAgent
from agents.flux      import FluxAgent
from agents.rex       import RexAgent
from agents.vigil     import VigilAgent
from agents.lore      import LoreAgent
from agents.specter   import SpecterAgent
from agents.cassandra import CassandraAgent
from agents.council   import CouncilAgent, TERRITORY_GROUPS as COUNCIL_TERRITORY_GROUPS, DIVERGENT_PAIRS
from agents.oracle    import OracleAgent

# Signal Integrity Layer v2
try:
    from signal_integrity import sil, pre_briefs, apply_decay, detect_silence
    SIL_ENABLED = True
    logging.getLogger('signal-society').info('Signal Integrity Layer v2: ACTIVE')
except ImportError:
    sil = None
    pre_briefs = None
    apply_decay = None
    detect_silence = None
    SIL_ENABLED = False
    logging.getLogger('signal-society').warning('signal_integrity.py not found — running without SIL')

# HERMES verification engine
try:
    from agents.hermes_verified import hermes_engine
    HERMES_ENABLED = True
except ImportError:
    hermes_engine = None
    HERMES_ENABLED = False

# ── APP SETUP ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
log = logging.getLogger('signal-society')

AGENTS = {
    'VERA':      VeraAgent(),
    'DUKE':      DukeAgent(),
    'MIRA':      MiraAgent(),
    'SOL':       SolAgent(),
    'NOVA':      NovaAgent(),
    'ECHO':      EchoAgent(),
    'KAEL':      KaelAgent(),
    'FLUX':      FluxAgent(),
    'REX':       RexAgent(),
    'VIGIL':     VigilAgent(),
    'LORE':      LoreAgent(),
    'SPECTER':   SpecterAgent(),
    'CASSANDRA': CassandraAgent(),
}
ORACLE  = OracleAgent()
COUNCIL = CouncilAgent()

_last_runs = {}

# ── CONVERGENCE CONFIG ────────────────────────────────────────────────────────
# Tags too generic to constitute valid convergence topics.
CONVERGENCE_BLACKLIST = {
    '#history', '#data', '#technology', '#news', '#update', '#general',
    '#misc', '#other', '#information', '#report', '#analysis', '#global',
    '#world', '#current', '#recent', '#new', '#latest',
}

# TOPIC_CLUSTERS — requires specific keywords per tag (unchanged from v1, still valid)
TOPIC_CLUSTERS = {
    '#AI': [
        'large language model', 'llm', 'foundation model', 'transformer model',
        'inference endpoint', 'model weights', 'training run', 'benchmark score',
        'openai', 'anthropic', 'deepmind', 'mistral', 'meta ai', 'google gemini',
        'ai chip', 'gpu cluster', 'tpu', 'ai regulation', 'ai safety',
        'ai governance', 'model collapse', 'hallucination rate', 'rlhf',
        'fine-tuning', 'context window', 'token limit', 'ai procurement',
    ],
    '#regulation': [
        'sec enforcement', 'sec filing', 'sec charges', 'sec subpoena',
        'ftc investigation', 'ftc complaint', 'ftc settlement',
        'fcc ruling', 'fcc fine', 'fcc license revocation',
        'fda approval', 'fda warning letter', 'fda recall', 'fda 510k',
        'doj indictment', 'doj settlement', 'doj probe',
        'antitrust lawsuit', 'antitrust investigation',
        'consent decree', 'regulatory comment period', 'notice of proposed rulemaking',
        'federal register rule', 'executive order signed',
    ],
    '#crypto': [
        'bitcoin price', 'btc', 'ethereum', 'eth price', 'usdt', 'usdc',
        'stablecoin depeg', 'defi protocol', 'smart contract exploit',
        'crypto exchange', 'binance', 'coinbase', 'kraken',
        'on-chain volume', 'gas fees', 'bridge exploit', 'cold wallet',
    ],
    '#infrastructure': [
        'spectrum license', 'spectrum auction', 'fcc spectrum',
        'faa temporary flight restriction', 'faa notam',
        'fiber optic permit', 'data center power', 'data center permit',
        'power grid expansion', 'transmission line', 'substation upgrade',
        'pipeline permit', 'port expansion', 'zoning variance', 'building permit cluster',
    ],
    '#biotech': [
        'phase 1 trial', 'phase 2 trial', 'phase 3 trial', 'clinical trial results',
        'fda approval', 'fda breakthrough designation', 'crispr therapy',
        'gene editing', 'mrna platform', 'biosimilar launch',
        'pandemic preparedness', 'outbreak declaration', 'cdc alert',
        'who emergency', 'epidemiological signal', 'excess mortality',
        'biotech acquisition', 'pharma merger',
    ],
    '#labor': [
        'mass layoff', 'reduction in force', 'headcount reduction',
        'hiring freeze', 'hiring surge', 'job posting spike',
        'executive departure', 'ceo resignation', 'union strike', 'union vote',
        'warn act', 'worker displacement', 'gig worker classification',
    ],
    '#climate': [
        'carbon credit', 'emissions target', 'scope 3 emissions',
        'renewable energy capacity', 'coal plant closure',
        'noaa temperature anomaly', 'arctic sea ice extent',
        'wildfire risk', 'flood risk mapping', 'drought index',
    ],
    '#media': [
        'coordinated publishing', 'identical headline', 'wire service anomaly',
        'gdelt spike', 'narrative saturation', 'media blackout',
        'story suppression', 'retraction pattern', 'outlet acquisition', 'newsroom closure',
    ],
    '#finance': [
        'ipo filing', 'ipo withdrawal', 's-1 filing', 'spac merger',
        'acquisition announced', 'merger agreement', 'hostile takeover',
        'private equity buyout', 'bond yield spike', 'credit spread widening',
        'options flow anomaly', 'short interest spike', 'sec form 4',
        'insider buying', 'insider selling cluster', 'earnings miss',
        'treasury yield inversion', 'fed rate decision',
    ],
    '#government': [
        'federal contract award', 'defense contract', 'pentagon award',
        'classified contract', 'sole source award', 'no-bid contract',
        'foia request', 'executive order', 'national security directive',
        'sanctions designation', 'export control', 'lobbying disclosure',
    ],
    '#supplychain': [
        'baltic dry index', 'bdi', 'container rate', 'freight rate spike',
        'port congestion', 'vessel rerouting', 'ais anomaly', 'tanker diversion',
        'trade flow reversal', 'semiconductor shortage', 'rare earth supply',
        'lithium supply', 'logistics bottleneck',
    ],
    '#patents': [
        'patent filing', 'patent application', 'patent grant',
        'continuation application', 'patent assignment', 'ip acquisition',
        'wipo filing', 'pct application', 'uspto grant', 'patent cluster',
        'standard essential patent', 'patent litigation',
    ],
    '#security': [
        'data breach', 'credential leak', 'ransomware attack',
        'zero-day exploit', 'cve published', 'vulnerability disclosure',
        'nation state attack', 'apt group', 'supply chain attack',
        'ddos attack', 'breach notification', 'incident response',
    ],
    '#history': [
        'historical precedent', 'rhymes with', 'parallel to',
        'same pattern as', 'last time this happened',
        'wayback machine', 'archived page', 'deleted content',
        'predecessor company', 'dormant domain', 'synchronized deletion',
    ],
}


# ── ROUTES — FEED ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/feed', methods=['GET'])
def get_feed():
    limit   = int(request.args.get('limit', 20))
    offset  = int(request.args.get('offset', 0))
    ftype   = request.args.get('type')
    citizen = request.args.get('citizen')
    posts   = db.get_posts(limit=limit, offset=offset, post_type=ftype, citizen=citizen)

    # Apply decay scores if SIL enabled
    if SIL_ENABLED and apply_decay:
        for post in posts:
            ts = post.get('timestamp', '')
            if ts:
                try:
                    age_hours = (datetime.utcnow() - datetime.fromisoformat(ts[:19])).total_seconds() / 3600
                    original  = float(post.get('sil_score') or 0)
                    corr      = len(post.get('corroborations') or [])
                    if original > 0:
                        post['decayed_score'] = apply_decay(original, age_hours, corr)
                except Exception:
                    pass
    return jsonify({'posts': posts, 'total': db.count_posts(ftype, citizen)})

@app.route('/api/feed/<post_id>', methods=['GET'])
def get_post(post_id):
    post = db.get_post(post_id)
    if not post:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(post)

# ── ROUTES — SEARCH ───────────────────────────────────────────────────────────

@app.route('/api/search', methods=['GET'])
def search():
    q     = (request.args.get('q') or '').strip()
    limit = min(int(request.args.get('limit', 20)), 50)
    ftype = request.args.get('type')
    if not q:
        return jsonify({'results': [], 'total': 0, 'query': q})
    try:
        results = db.search(q, limit=limit, post_type=ftype)
        return jsonify({'results': results, 'total': len(results), 'query': q})
    except Exception as e:
        log.error(f'Search failed: {e}')
        return jsonify({'results': [], 'total': 0, 'query': q, 'error': str(e)})

# ── ROUTES — BRIEFS ───────────────────────────────────────────────────────────

@app.route('/api/briefs', methods=['GET'])
def get_briefs():
    limit      = int(request.args.get('limit', 20))
    tier       = request.args.get('tier')
    confidence = request.args.get('confidence')
    briefs     = db.get_briefs(limit=limit, tier=tier, confidence=confidence)
    return jsonify({'briefs': briefs, 'total': len(briefs)})

@app.route('/api/briefs/<brief_id>', methods=['GET'])
def get_brief(brief_id):
    brief = db.get_brief(brief_id)
    if not brief:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(brief)

# ── ROUTES — VERIFIED (HERMES TAB) ───────────────────────────────────────────

@app.route('/api/verified', methods=['GET'])
def get_verified():
    """
    Verified Intelligence Reports — HERMES tab.
    Returns only posts of type 'verified_report' produced by HERMES
    after directly checking primary sources.

    Query params:
      limit      default 20
      confirmed  'true'|'false' — filter by verification outcome
      vtype      SEC_FILING|CVE|REGULATORY|PATENT|DELETION|API_CHANGE|COURT_ORDER|GENERAL
    """
    limit     = int(request.args.get('limit', 20))
    confirmed = request.args.get('confirmed')
    vtype     = request.args.get('vtype')

    try:
        # Fetch verified_report type posts from HERMES
        reports = db.get_posts(
            limit=limit,
            post_type='verified_report',
            citizen='HERMES',
        )

        # Apply filters
        if confirmed is not None:
            want_confirmed = confirmed.lower() == 'true'
            reports = [r for r in reports if r.get('confirmed', False) == want_confirmed]

        if vtype:
            reports = [r for r in reports if r.get('vtype', '') == vtype.upper()]

        # Build summary stats
        total     = len(reports)
        n_confirmed = sum(1 for r in reports if r.get('confirmed', False))
        n_void      = total - n_confirmed

        return jsonify({
            'reports': reports,
            'total':   total,
            'stats': {
                'confirmed': n_confirmed,
                'void':      n_void,
                'types':     _count_by_key(reports, 'vtype'),
            },
        })
    except Exception as e:
        log.error(f'get_verified: {e}')
        return jsonify({'reports': [], 'total': 0, 'error': str(e)})

@app.route('/api/verified/trigger', methods=['GET', 'POST'])
def trigger_hermes_verification():
    """Manually trigger HERMES verification queue processing."""
    if not HERMES_ENABLED:
        return jsonify({'error': 'HERMES verification engine not loaded'}), 503
    def _run():
        try:
            reports = hermes_engine.process_queue(db)
            log.info(f'HERMES manual trigger: {len(reports)} reports produced')
        except Exception as e:
            log.error(f'HERMES trigger: {e}')
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'started', 'agent': 'HERMES_VERIFIED'})

@app.route('/api/verified/<report_id>', methods=['GET'])
def get_verified_report(report_id):
    """Get a single Verified Intelligence Report."""
    post = db.get_post(report_id)
    if not post or post.get('type') != 'verified_report':
        return jsonify({'error': 'Not found'}), 404
    return jsonify(post)

def _count_by_key(items: list, key: str) -> dict:
    counts = {}
    for item in items:
        v = item.get(key, 'UNKNOWN')
        counts[v] = counts.get(v, 0) + 1
    return counts

# ── ROUTES — PRE-BRIEFS ───────────────────────────────────────────────────────

@app.route('/api/pre_briefs', methods=['GET'])
def get_pre_briefs():
    """
    Living Pre-Briefs — signals that are open, updating as corroboration arrives.
    The UI monitor shows these as the 'working intelligence' layer.
    """
    status = request.args.get('status', 'open')  # open|confirmed|contradicted|archived
    try:
        if SIL_ENABLED and pre_briefs:
            all_pbs = list(pre_briefs._pre_briefs.values())
            filtered = [pb for pb in all_pbs if pb.get('status') == status]
            # Also try DB
            try:
                db_pbs = db.get_pre_briefs(status=status)
                # Merge — DB overrides in-memory for same id
                seen_ids = {pb['id'] for pb in filtered}
                for db_pb in (db_pbs or []):
                    if db_pb['id'] not in seen_ids:
                        filtered.append(db_pb)
            except Exception:
                pass
        else:
            try:
                filtered = db.get_pre_briefs(status=status) or []
            except Exception:
                filtered = []

        return jsonify({
            'pre_briefs': filtered,
            'total': len(filtered),
            'status_filter': status,
        })
    except Exception as e:
        log.error(f'get_pre_briefs: {e}')
        return jsonify({'pre_briefs': [], 'total': 0, 'error': str(e)})

# ── ROUTES — SILENCE SIGNALS ──────────────────────────────────────────────────

@app.route('/api/silence', methods=['GET'])
def get_silence_signals():
    """
    Return agents that are absent from active topic clusters despite
    having relevant territory. Silence from an expected voice is intelligence.
    """
    hours = int(request.args.get('hours', 96))
    try:
        recent = db.get_recent_mentions(hours=hours)
        # Find active topics and which agents are producing on them
        active_topics = {}
        active_agents = set()
        for post in recent:
            agent = post.get('citizen', '')
            if agent:
                active_agents.add(agent)
            for tag, kws in TOPIC_CLUSTERS.items():
                body = (post.get('body', '') or '').lower()
                if any(kw in body for kw in kws):
                    active_topics.setdefault(tag, set()).add(agent)

        silences = []
        if SIL_ENABLED and detect_silence:
            for tag, covering_agents in active_topics.items():
                if tag in CONVERGENCE_BLACKLIST:
                    continue
                tag_silences = detect_silence(
                    topic_tags=[tag],
                    recent_agents=list(covering_agents),
                    hours=hours,
                )
                for agent, reason in tag_silences:
                    silences.append({
                        'agent':  agent,
                        'topic':  tag,
                        'reason': reason,
                        'hours':  hours,
                    })

        return jsonify({
            'silences':       silences,
            'total':          len(silences),
            'active_topics':  {k: list(v) for k, v in active_topics.items()},
            'active_agents':  list(active_agents),
            'window_hours':   hours,
        })
    except Exception as e:
        log.error(f'get_silence_signals: {e}')
        return jsonify({'silences': [], 'total': 0, 'error': str(e)})

# ── ROUTES — CONTRADICTION INDEX ──────────────────────────────────────────────

@app.route('/api/contradictions', methods=['GET'])
def get_contradictions():
    """
    Brief Contradiction Index — when new agent data contradicts a previous brief.
    Returns briefs that have been contradicted and the contradicting signals.
    """
    limit = int(request.args.get('limit', 10))
    try:
        briefs   = db.get_briefs(limit=50)
        recent   = db.get_recent_mentions(hours=48)
        contradictions = []
        for brief in briefs:
            brief_tags  = set(brief.get('tags') or [])
            brief_panel = set(brief.get('panel') or brief.get('agents') or [])
            brief_body  = (brief.get('verdict') or '') + ' ' + (brief.get('headline') or '')
            contra_kws  = ['however', 'contrary', 'contradicts', 'opposite',
                           'actually', 'incorrect', 'no evidence', 'refutes',
                           'disproves', 'declining', 'reversal']
            for post in recent:
                if post.get('citizen') in brief_panel:
                    continue
                post_tags = set(post.get('tags') or [])
                if not (brief_tags & post_tags):
                    continue
                post_body = (post.get('body') or '').lower()
                if any(kw in post_body for kw in contra_kws):
                    contradictions.append({
                        'brief_id':       brief.get('id'),
                        'brief_headline': brief.get('headline', ''),
                        'brief_confidence': brief.get('confidence', ''),
                        'brief_created':  brief.get('created_at', ''),
                        'contradicted_by': {
                            'post_id':  post.get('id'),
                            'agent':    post.get('citizen'),
                            'body':     (post.get('body') or '')[:200],
                            'timestamp': post.get('timestamp', ''),
                        },
                        'shared_tags': list(brief_tags & post_tags),
                    })

        contradictions = contradictions[:limit]
        return jsonify({
            'contradictions': contradictions,
            'total': len(contradictions),
        })
    except Exception as e:
        log.error(f'get_contradictions: {e}')
        return jsonify({'contradictions': [], 'total': 0, 'error': str(e)})

# ── ROUTES — COUNCIL + ORACLE ─────────────────────────────────────────────────

@app.route('/api/council', methods=['GET'])
def get_council_sessions():
    limit     = int(request.args.get('limit', 20))
    processed = request.args.get('processed')
    if processed is not None:
        processed = processed.lower() == 'true'
    sessions = db.get_council_sessions(limit=limit, processed=processed)
    return jsonify({'sessions': sessions, 'total': len(sessions)})

@app.route('/api/oracle/run', methods=['GET', 'POST'])
def trigger_oracle():
    threading.Thread(target=lambda: ORACLE.run_on_unprocessed(db), daemon=True).start()
    return jsonify({'status': 'started', 'agent': 'ORACLE'})

# ── ROUTES — REACTIONS ────────────────────────────────────────────────────────

@app.route('/api/react', methods=['POST'])
def react():
    data    = request.json
    post_id = data.get('post_id')
    key     = data.get('reaction')
    user_id = data.get('user_id', 'anonymous')
    if key not in ('agree', 'flag', 'save'):
        return jsonify({'error': 'Invalid reaction'}), 400
    result = db.toggle_reaction(post_id, key, user_id)
    return jsonify(result)

# ── ROUTES — CITIZENS ─────────────────────────────────────────────────────────

@app.route('/api/citizens', methods=['GET'])
def get_citizens():
    return jsonify(db.get_citizen_stats())

@app.route('/api/citizens/<name>/posts', methods=['GET'])
def get_citizen_posts(name):
    if name.upper() not in AGENTS:
        return jsonify({'error': 'Unknown citizen'}), 404
    posts = db.get_posts(citizen=name.upper(), limit=10)
    return jsonify(posts)

# ── ROUTES — STATS ────────────────────────────────────────────────────────────

@app.route('/api/stats',       methods=['GET'])
def get_stats():       return jsonify(db.get_weekly_stats())

@app.route('/api/divergence',  methods=['GET'])
def get_divergence():  return jsonify(db.get_divergence_map())

@app.route('/api/convergence', methods=['GET'])
def get_convergence(): return jsonify(db.get_convergence_status())

# ── ROUTES — HEALTH ───────────────────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    try:
        pending_council = len(db.get_unprocessed_posts())
    except Exception:
        pending_council = -1
    try:
        pending_oracle = len(db.get_unprocessed_council_sessions())
    except Exception:
        pending_oracle = -1
    try:
        total_posts  = db.count_posts()
        total_briefs = len(db.get_briefs(limit=1000))
    except Exception:
        total_posts = total_briefs = -1

    # Token budget from gateway
    budget_data = {}
    try:
        from agents.llm_gateway import get_budget_status
        budget_data = get_budget_status()
    except Exception:
        pass

    # Pre-brief status
    pre_brief_counts = {}
    if SIL_ENABLED and pre_briefs:
        try:
            all_pbs = list(pre_briefs._pre_briefs.values())
            for pb in all_pbs:
                s = pb.get('status', 'unknown')
                pre_brief_counts[s] = pre_brief_counts.get(s, 0) + 1
        except Exception:
            pass

    return jsonify({
        'status':    'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'agents': {name: {'last_run': _last_runs.get(name, 'never')} for name in AGENTS},
        'pipeline': {
            'posts_awaiting_council':   pending_council,
            'sessions_awaiting_oracle': pending_oracle,
        },
        'totals': {
            'posts':      total_posts,
            'briefs':     total_briefs,
            'pre_briefs': pre_brief_counts,
        },
        'token_budget':     budget_data,
        'sil_enabled':      SIL_ENABLED,
        'hermes_enabled':   HERMES_ENABLED,
    })

# ── ROUTES — SIL ──────────────────────────────────────────────────────────────

@app.route('/api/sil/status', methods=['GET'])
def sil_status():
    if not SIL_ENABLED:
        return jsonify({'enabled': False}), 200
    try:
        approved_24h = db.count_posts_by_type('post', hours=24) if hasattr(db, 'count_posts_by_type') else 0
        rejected_24h = db.count_rejected_signals(hours=24) if hasattr(db, 'count_rejected_signals') else 0
        return jsonify({
            'enabled':  True,
            'last_24h': {
                'approved': approved_24h,
                'rejected': rejected_24h,
                'ratio':    round(approved_24h / max(approved_24h + rejected_24h, 1), 3),
            },
            'thresholds': {
                'minimum':  0.32,
                'council':  0.34,
                'brief':    0.35,
            },
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sil/bury', methods=['POST'])
def manual_burial():
    data      = request.get_json() or {}
    signal_id = data.get('signal_id')
    if not signal_id:
        return jsonify({'error': 'signal_id required'}), 400
    post = db.get_post(signal_id)
    if not post:
        return jsonify({'error': 'Signal not found'}), 404
    try:
        db.save_post({**post, 'published': False})
        return jsonify({'buried': True, 'signal_id': signal_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── ROUTES — MANUAL TRIGGERS ──────────────────────────────────────────────────

@app.route('/api/trigger/<agent_name>', methods=['GET', 'POST'])
def trigger_agent(agent_name):
    name = agent_name.upper()

    if name == 'TOWNHALL':
        threading.Thread(target=check_for_disagreement, daemon=True).start()
        return jsonify({'ok': True, 'agent': 'TOWNHALL'}), 200
    if name == 'COUNCIL':
        threading.Thread(target=lambda: COUNCIL.run_on_unprocessed(db), daemon=True).start()
        return jsonify({'ok': True, 'agent': 'COUNCIL'}), 200
    if name == 'ORACLE':
        threading.Thread(target=lambda: ORACLE.run_on_unprocessed(db), daemon=True).start()
        return jsonify({'ok': True, 'agent': 'ORACLE'}), 200
    if name == 'HERMES':
        if HERMES_ENABLED:
            threading.Thread(target=lambda: hermes_engine.process_queue(db), daemon=True).start()
        return jsonify({'ok': True, 'agent': 'HERMES'}), 200

    if name not in AGENTS:
        return jsonify({'error': 'Unknown agent'}), 404

    def _run():
        try:
            result = AGENTS[name].run()
            _process_agent_output(name, result)
        except Exception as e:
            log.error(f'Trigger {name} failed: {e}')
            import traceback; log.error(traceback.format_exc())

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'agent': name}), 200

# ── CORE PIPELINE ─────────────────────────────────────────────────────────────

def run_agent(name: str):
    log.info(f'Scheduled run: {name}')
    try:
        posts = AGENTS[name].run()
        _process_agent_output(name, posts)
    except Exception as e:
        log.error(f'{name} agent error: {e}')
        import traceback; log.error(traceback.format_exc())
        db.log_agent_run(name, 0, str(e))


def _process_agent_output(name: str, posts: list):
    """
    Post-processing pipeline:
      1. SIL score each post
      2. Reject below minimum threshold
      3. Open Pre-Brief for promising-but-not-ready signals
      4. Save qualifying posts to DB
      5. Update Pre-Brief corroborations with new posts
      6. Run convergence + disagreement detection
    """
    if not posts:
        _last_runs[name] = datetime.utcnow().isoformat()
        return

    saved_count    = 0
    rejected_count = 0

    for post in posts:
        if not post:
            continue

        if SIL_ENABLED and sil:
            try:
                # Fetch recent posts once per batch — not per post
                recent = db.get_recent_mentions(hours=24)
                result = sil.score(post, recent_posts=recent)

                post['sil_score']  = result['total']
                post['dimensions'] = result['dimensions']
                post['epistemic_tag'] = result['epistemic_tag']

                if result['noise_detected']:
                    rejected_count += 1
                    log.info(f'[SIL] Noise rejected: {post.get("id","?")} ({name})')
                    continue

                if not result['publish']:
                    rejected_count += 1
                    log.info(
                        f'[SIL] Rejected: {post.get("id","?")} ({name}) '
                        f'score={result["total"]:.3f}'
                    )
                    # Open a Pre-Brief if score is promising (0.45-0.52)
                    if result['total'] >= 0.45 and pre_briefs:
                        pre_briefs.open(post, result, db)
                    continue

                # Open a Pre-Brief for signals that passed but aren't brief-ready yet
                if result['pre_brief'] and pre_briefs:
                    pre_briefs.open(post, result, db)

            except Exception as e:
                log.error(f'SIL scoring failed for {name}: {e}')

        # Save to DB
        try:
            db.save_post(post)
            saved_count += 1
        except Exception as e:
            log.error(f'save_post failed ({name}): {e}')

        # Update Pre-Brief corroborations
        if SIL_ENABLED and pre_briefs:
            try:
                updated = pre_briefs.update(post, db)
                if updated:
                    log.info(f'Pre-Brief updated by {name}: {len(updated)} pre-brief(s) affected')
            except Exception as e:
                log.error(f'Pre-Brief update failed: {e}')

    _last_runs[name] = datetime.utcnow().isoformat()
    db.log_agent_run(name, saved_count)
    log.info(f'{name}: {saved_count} saved, {rejected_count} rejected')

    if saved_count > 0:
        try:
            check_convergence()
        except Exception as e:
            log.error(f'check_convergence failed: {e}')
        try:
            check_for_disagreement()
        except Exception as e:
            log.error(f'check_for_disagreement failed: {e}')


# ── CONVERGENCE DETECTION (v2) ────────────────────────────────────────────────

def _post_topics(post: dict) -> set:
    """Extract topic clusters from post body + tags."""
    body     = (post.get('body', '') or '').lower()
    tags_str = ' '.join(t.lower() for t in (post.get('tags') or []))
    combined = body + ' ' + tags_str
    return {tag for tag, kws in TOPIC_CLUSTERS.items()
            if any(kw in combined for kw in kws)}

def _agents_are_independent(citizens: list) -> bool:
    """
    True if the contributing agents come from at least 2 different territory groups.
    Prevents DUKE + FLUX (both market group) from constituting a valid convergence.
    """
    groups = set()
    for agent in citizens:
        for group, members in COUNCIL_TERRITORY_GROUPS.items():
            if agent in members:
                groups.add(group)
                break
        else:
            groups.add(f'solo_{agent}')  # ungrouped agents count as their own group
    return len(groups) >= 2

def _body_length_ok(posts: list, min_chars: int = 120) -> bool:
    """At least 2 posts must have body length >= min_chars."""
    return sum(1 for p in posts if len(p.get('body', '') or '') >= min_chars) >= 2

def check_convergence():
    """
    v2 convergence detection:
      - Tags in CONVERGENCE_BLACKLIST are excluded
      - Requires agents from different territory groups (independence check)
      - Requires minimum body length per contributing dispatch
      - Existing signal alert for same tag suppresses duplicate
    """
    recent = db.get_recent_mentions(hours=6)
    if len(recent) < 2:
        return

    from collections import defaultdict
    topic_citizens = defaultdict(set)
    topic_posts    = defaultdict(list)

    for post in recent:
        citizen = post.get('citizen')
        if not citizen:
            continue
        for topic in _post_topics(post):
            if topic in CONVERGENCE_BLACKLIST:
                continue
            topic_citizens[topic].add(citizen)
            topic_posts[topic].append(post)

    for topic_tag, citizens in topic_citizens.items():
        if len(citizens) < 2:
            continue

        # Independence check — must span different territory groups
        if not _agents_are_independent(list(citizens)):
            log.info(f'Convergence suppressed: {topic_tag} — agents not independent ({citizens})')
            continue

        # Body length check — reject if posts are too thin
        if not _body_length_ok(topic_posts[topic_tag]):
            log.info(f'Convergence suppressed: {topic_tag} — bodies too short')
            continue

        # Deduplicate — don't re-alert on same tag
        if db.get_signal_alert_for_tag(topic_tag):
            continue

        log.info(f'CONVERGENCE: {topic_tag} — {citizens}')
        create_signal_alert(topic_tag, topic_posts[topic_tag], list(citizens))


def create_signal_alert(tag: str, matching_posts: list, citizens: list = None):
    if citizens is None:
        citizens = list({p['citizen'] for p in matching_posts})
    citizens = citizens[:4]

    seen_in_thread = set()
    thread = []
    for p in matching_posts:
        c = p.get('citizen')
        if c and c not in seen_in_thread and c in citizens:
            seen_in_thread.add(c)
            thread.append({'citizen': c, 'text': (p.get('body', '') or '')[:280]})
        if len(thread) >= len(citizens):
            break

    # Collect SIL scores from contributing posts
    sil_scores = [
        float(p.get('sil_score') or 0)
        for p in matching_posts
        if p.get('sil_score')
    ]
    avg_sil = round(sum(sil_scores) / len(sil_scores), 4) if sil_scores else 0

    alert_id = str(uuid.uuid4())
    alert = {
        'id':        alert_id,
        'type':      'signal_alert',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  citizens,
        'headline':  f'SIGNAL ALERT — {len(citizens)}-WAY CONVERGENCE on {tag}',
        'body':      (
            f"{len(citizens)} independent agents converged on {tag}: "
            f"{', '.join(citizens)}. "
            f"Average signal integrity: {avg_sil:.3f}."
        ),
        'tags':      [tag, '#convergence'],
        'thread':    thread,
        'sil_score': avg_sil,
    }

    db.save_post(alert)
    log.info(f'Signal Alert created: {tag} (id: {alert_id}, sil={avg_sil:.3f})')


def _town_hall_worth_debating(post_a: dict, post_b: dict, topic_tag: str) -> bool:
    """Quality gate for Council escalation from Town Hall."""
    if topic_tag in CONVERGENCE_BLACKLIST:
        return False

    HIGH_VALUE_PAIRS = {
        frozenset({'VIGIL', 'DUKE'}), frozenset({'VIGIL', 'FLUX'}),
        frozenset({'VIGIL', 'KAEL'}), frozenset({'LORE',  'VERA'}),
        frozenset({'SPECTER', 'DUKE'}), frozenset({'SPECTER', 'ECHO'}),
        frozenset({'FLUX', 'REX'}), frozenset({'REX', 'KAEL'}),
        frozenset({'VERA', 'DUKE'}), frozenset({'SOL', 'KAEL'}),
    }
    score = 0

    body_a = post_a.get('body') or ''
    body_b = post_b.get('body') or ''
    if len(body_a) > 120 and len(body_b) > 120:
        score += 1

    # SIL scores both need to be above council threshold
    sil_a = float(post_a.get('sil_score') or 0)
    sil_b = float(post_b.get('sil_score') or 0)
    if sil_a >= 0.62 and sil_b >= 0.62:
        score += 1
    elif sil_a >= 0.52 and sil_b >= 0.52:
        score += 0.5

    r_a = post_a.get('reactions') or {}
    r_b = post_b.get('reactions') or {}
    if isinstance(r_a, str):
        try: r_a = json.loads(r_a)
        except: r_a = {}
    if isinstance(r_b, str):
        try: r_b = json.loads(r_b)
        except: r_b = {}
    if sum(r_a.values()) + sum(r_b.values()) > 0:
        score += 1

    pair = frozenset({post_a.get('citizen',''), post_b.get('citizen','')})
    if pair in HIGH_VALUE_PAIRS:
        score += 1

    return score >= 2


def create_town_hall(citizen_a: str, post_a: dict, citizen_b: str, post_b: dict, topic_tag: str):
    th_id = str(uuid.uuid4())
    th = {
        'id':        th_id,
        'type':      'town_hall',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  [citizen_a, citizen_b],
        'topic':     f'Divergence on {topic_tag} — {citizen_a} vs {citizen_b}',
        'tags':      [topic_tag, '#divergence', '#townhall'],
        'positions': [
            {'citizen': citizen_a, 'stance': 'Signals', 'text': (post_a.get('body','') or '')[:300]},
            {'citizen': citizen_b, 'stance': 'Counter',  'text': (post_b.get('body','') or '')[:300]},
        ],
        'votes': {citizen_a: 0, citizen_b: 0, 'neutral': 0},
    }
    db.save_post(th)
    log.info(f'Town Hall: {citizen_a} vs {citizen_b} on {topic_tag}')

    if _town_hall_worth_debating(post_a, post_b, topic_tag):
        log.info(f'Town Hall qualified for Council: {citizen_a} vs {citizen_b}')
        def _trigger_council():
            import time; time.sleep(8)
            try:
                COUNCIL.run_on_unprocessed(db)
            except Exception as e:
                log.error(f'Council trigger failed: {e}')
        threading.Thread(target=_trigger_council, daemon=True).start()
    else:
        log.info(f'Town Hall did NOT qualify for Council: {citizen_a} vs {citizen_b} on {topic_tag}')


def check_for_disagreement():
    recent = db.get_recent_mentions(hours=12)
    if len(recent) < 2:
        return
    by_citizen = {}
    for post in recent:
        c = post.get('citizen')
        if c:
            by_citizen.setdefault(c, []).append(post)

    for citizen_a, citizen_b in DIVERGENT_PAIRS:
        posts_a = by_citizen.get(citizen_a, [])
        posts_b = by_citizen.get(citizen_b, [])
        if not posts_a or not posts_b:
            continue

        topics_a = {t for p in posts_a for t in _post_topics(p)}
        topics_b = {t for p in posts_b for t in _post_topics(p)}
        shared   = (topics_a & topics_b) - {'#convergence'} - CONVERGENCE_BLACKLIST
        if not shared:
            continue

        topic_tag = sorted(shared)[0]
        if db.get_town_hall_for_pair(citizen_a, citizen_b, topic_tag):
            continue

        kws    = TOPIC_CLUSTERS.get(topic_tag, [])
        post_a = next((p for p in posts_a if any(kw in (p.get('body','') or '').lower() for kw in kws)), posts_a[0])
        post_b = next((p for p in posts_b if any(kw in (p.get('body','') or '').lower() for kw in kws)), posts_b[0])

        # Both posts must have sufficient SIL score
        sil_a = float(post_a.get('sil_score') or 0)
        sil_b = float(post_b.get('sil_score') or 0)
        if max(sil_a, sil_b) < 0.52:
            log.info(f'Disagreement suppressed — SIL too low: {citizen_a}={sil_a:.3f} {citizen_b}={sil_b:.3f}')
            continue

        log.info(f'DISAGREEMENT: {citizen_a} vs {citizen_b} on {topic_tag}')
        create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag)


# ── SCHEDULER ─────────────────────────────────────────────────────────────────

def setup_scheduler():
    scheduler = BackgroundScheduler()
    now = datetime.now()

    # Agent schedule — offset same-territory agents to prevent simultaneous Groq calls
    scheduler.add_job(lambda: run_agent('VERA'),    'interval', hours=2, id='vera')
    scheduler.add_job(lambda: run_agent('DUKE'),    'interval', hours=2, id='duke',
                      start_date=now + timedelta(minutes=20))
    scheduler.add_job(lambda: run_agent('MIRA'),    'interval', hours=3, id='mira',
                      start_date=now + timedelta(minutes=40))  # was 1h — too frequent
    scheduler.add_job(lambda: run_agent('SOL'),     'interval', hours=3, id='sol',
                      start_date=now + timedelta(minutes=60))
    scheduler.add_job(lambda: run_agent('NOVA'),    'interval', hours=6, id='nova')
    scheduler.add_job(lambda: run_agent('ECHO'),    'interval', hours=2, id='echo',
                      start_date=now + timedelta(minutes=30))
    scheduler.add_job(lambda: run_agent('KAEL'),    'interval', hours=2, id='kael',
                      start_date=now + timedelta(minutes=50))
    scheduler.add_job(lambda: run_agent('FLUX'),    'interval', hours=2, id='flux',
                      start_date=now + timedelta(minutes=10))
    scheduler.add_job(lambda: run_agent('REX'),     'interval', hours=2, id='rex',
                      start_date=now + timedelta(minutes=70))
    scheduler.add_job(lambda: run_agent('VIGIL'),   'interval', hours=4, id='vigil',
                      start_date=now + timedelta(minutes=15))
    scheduler.add_job(lambda: run_agent('LORE'),    'interval', hours=6, id='lore',
                      start_date=now + timedelta(minutes=45))
    scheduler.add_job(lambda: run_agent('SPECTER'), 'interval', hours=3, id='specter',
                      start_date=now + timedelta(minutes=25))

    # CASSANDRA: ONE job, every 6h, starts 90min after boot
    # (v1 had duplicate jobs — the 3h one silently overwrote the 6h one)
    scheduler.add_job(
        lambda: run_agent('CASSANDRA'), 'interval', hours=6, id='cassandra',
        start_date=now + timedelta(minutes=90),
    )

    # Council every 4h; Oracle 1h after Council so sessions exist
    scheduler.add_job(
        lambda: COUNCIL.run_on_unprocessed(db), 'interval', hours=4, id='council',
    )
    scheduler.add_job(
        lambda: ORACLE.run_on_unprocessed(db), 'interval', hours=4, id='oracle',
        start_date=now + timedelta(hours=1),
    )

    # HERMES verification every 4h — offset 30min from Oracle
    if HERMES_ENABLED:
        scheduler.add_job(
            lambda: hermes_engine.process_queue(db), 'interval', hours=4, id='hermes_verified',
            start_date=now + timedelta(hours=1, minutes=30),
        )

    # Keep-alive ping to prevent Render free tier from sleeping
    @app.route('/api/ping', methods=['GET'])
    def ping():
        return jsonify({'ok': True, 'ts': datetime.utcnow().isoformat()})

    scheduler.start()
    log.info(
        f'Scheduler started — 12 agents + COUNCIL + ORACLE'
        + (' + HERMES_VERIFIED' if HERMES_ENABLED else '')
    )
    return scheduler


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    db.init()
    scheduler = setup_scheduler()
    port = int(os.environ.get('PORT', 5000))
    log.info(f'Signal Society v2 running on http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

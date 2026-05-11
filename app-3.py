"""
The Signal Society — Flask Backend
====================================
Run:  python app.py
Deps: pip install -r requirements.txt

Signal Integrity Layer wired in at:
  - run_agent()        → scorer filters before DB write
  - trigger_agent()    → same filter on manual triggers
  - setup_scheduler()  → entropy monitor added every 3h
  - /api/sil/*         → status and burial endpoints
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import logging, os, json, uuid
from dotenv import load_dotenv

load_dotenv()

from database import db
from agents.vera    import VeraAgent
from agents.duke    import DukeAgent
from agents.mira    import MiraAgent
from agents.sol     import SolAgent
from agents.nova    import NovaAgent
from agents.echo    import EchoAgent
from agents.kael    import KaelAgent
from agents.flux    import FluxAgent
from agents.rex     import RexAgent
from agents.vigil   import VigilAgent
from agents.lore    import LoreAgent
from agents.specter import SpecterAgent
from agents.cassandra import CassandraAgent
from agents.council import CouncilAgent

# Signal Integrity Layer — filtration cortex
# Sits between raw agent output and the database.
# Low-quality signals never contaminate downstream cognition.
try:
    from signal_integrity import SignalIntegrityLayer
    sil = SignalIntegrityLayer(db)
    SIL_ENABLED = True
    logging.getLogger('signal-society').info("Signal Integrity Layer: ACTIVE")
except ImportError:
    sil = None
    SIL_ENABLED = False
    logging.getLogger('signal-society').warning(
        "signal_integrity.py not found — running without SIL filtration."
    )

# ─────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────
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

# Track last agent run times for /api/health
_last_runs = {}

# ─────────────────────────────────────
# ROUTES — FEED
# ─────────────────────────────────────
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/feed', methods=['GET'])
def get_feed():
    """Return paginated feed. Query params: limit, offset, type, citizen"""
    limit   = int(request.args.get('limit', 20))
    offset  = int(request.args.get('offset', 0))
    ftype   = request.args.get('type')
    citizen = request.args.get('citizen')
    posts = db.get_posts(limit=limit, offset=offset, post_type=ftype, citizen=citizen)
    return jsonify({'posts': posts, 'total': db.count_posts(ftype, citizen)})

@app.route('/api/feed/<post_id>', methods=['GET'])
def get_post(post_id):
    post = db.get_post(post_id)
    if not post:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(post)

# ─────────────────────────────────────
# ROUTES — SEARCH
# ─────────────────────────────────────
@app.route('/api/search', methods=['GET'])
def search():
    """Full-text search across posts and briefs. Params: q, limit, type"""
    q     = (request.args.get('q') or '').strip()
    limit = min(int(request.args.get('limit', 20)), 50)
    ftype = request.args.get('type')
    if not q:
        return jsonify({'results': [], 'total': 0, 'query': q})
    try:
        results = db.search(q, limit=limit, post_type=ftype)
        return jsonify({'results': results, 'total': len(results), 'query': q})
    except Exception as e:
        log.error(f"Search failed: {e}")
        return jsonify({'results': [], 'total': 0, 'query': q, 'error': str(e)})

# ─────────────────────────────────────
# ROUTES — HEALTH
# ─────────────────────────────────────
@app.route('/api/health', methods=['GET'])
def health():
    """System status — last runs, token budgets, queue depths, SIL metrics."""
    from agents.council import _daily_token_count as council_tokens, MAX_DAILY_TOKENS as council_max
    from agents.oracle  import _daily_token_count as oracle_tokens,  MAX_DAILY_TOKENS as oracle_max
    try:
        pending_council = len(db.get_unprocessed_posts())
    except:
        pending_council = -1
    try:
        pending_oracle = len(db.get_unprocessed_council_sessions())
    except:
        pending_oracle = -1
    try:
        total_posts  = db.count_posts()
        total_briefs = len(db.get_briefs(limit=1000))
    except:
        total_posts = total_briefs = -1

    # SIL health metrics
    sil_metrics = {}
    if SIL_ENABLED:
        try:
            rejected_24h = db.count_rejected_signals(hours=24) if hasattr(db, 'count_rejected_signals') else 0
            approved_24h = db.count_posts_by_type('post', hours=24) if hasattr(db, 'count_posts_by_type') else 0
            sil_metrics = {
                'enabled': True,
                'signals_approved_24h': approved_24h,
                'signals_rejected_24h': rejected_24h,
                'thresholds': {
                    'signal_min_score': int(os.getenv('SIGNAL_MIN_SCORE', '52')),
                    'council_escalation_score': int(os.getenv('COUNCIL_ESCALATION_SCORE', '72')),
                    'counterfactual_trigger_score': int(os.getenv('COUNTERFACTUAL_TRIGGER_SCORE', '85')),
                },
            }
        except Exception as e:
            sil_metrics = {'enabled': True, 'error': str(e)}
    else:
        sil_metrics = {'enabled': False}

    return jsonify({
        'status':    'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'agents': {name: {'last_run': _last_runs.get(name, 'never')} for name in AGENTS},
        'pipeline': {
            'council_tokens_today':      council_tokens,
            'council_token_budget':      council_max,
            'oracle_tokens_today':       oracle_tokens,
            'oracle_token_budget':       oracle_max,
            'posts_awaiting_council':    pending_council,
            'sessions_awaiting_oracle':  pending_oracle,
        },
        'totals': {'posts': total_posts, 'briefs': total_briefs},
        'signal_integrity': sil_metrics,
    })

# ─────────────────────────────────────
# ROUTES — BRIEFS (ORACLE output)
# ─────────────────────────────────────
@app.route('/api/briefs', methods=['GET'])
def get_briefs():
    """Return intelligence briefs. Params: limit, tier, confidence"""
    limit      = int(request.args.get('limit', 20))
    tier       = request.args.get('tier')
    confidence = request.args.get('confidence')
    briefs = db.get_briefs(limit=limit, tier=tier, confidence=confidence)
    return jsonify({'briefs': briefs, 'total': len(briefs)})

@app.route('/api/briefs/<brief_id>', methods=['GET'])
def get_brief(brief_id):
    brief = db.get_brief(brief_id)
    if not brief:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(brief)

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
    import threading
    threading.Thread(target=lambda: ORACLE.run_on_unprocessed(db), daemon=True).start()
    return jsonify({'status': 'started', 'agent': 'ORACLE'})

# ─────────────────────────────────────
# ROUTES — REACTIONS
# ─────────────────────────────────────
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

# ─────────────────────────────────────
# ROUTES — CITIZENS
# ─────────────────────────────────────
@app.route('/api/citizens', methods=['GET'])
def get_citizens():
    return jsonify(db.get_citizen_stats())

@app.route('/api/citizens/<n>/posts', methods=['GET'])
def get_citizen_posts(name):
    if name.upper() not in AGENTS:
        return jsonify({'error': 'Unknown citizen'}), 404
    posts = db.get_posts(citizen=name.upper(), limit=10)
    return jsonify(posts)

# ─────────────────────────────────────
# ROUTES — STATS
# ─────────────────────────────────────
@app.route('/api/stats',       methods=['GET'])
def get_stats():      return jsonify(db.get_weekly_stats())

@app.route('/api/divergence',  methods=['GET'])
def get_divergence(): return jsonify(db.get_divergence_map())

@app.route('/api/convergence', methods=['GET'])
def get_convergence():return jsonify(db.get_convergence_status())

# ─────────────────────────────────────
# ROUTES — SIGNAL INTEGRITY LAYER
# ─────────────────────────────────────
@app.route('/api/sil/status', methods=['GET'])
def sil_status():
    """
    Returns current Signal Integrity Layer health metrics.
    Useful for monitoring organism cognitive drift.
    """
    if not SIL_ENABLED:
        return jsonify({'enabled': False, 'message': 'SIL not loaded'}), 200
    try:
        # Get latest entropy snapshot without forcing a new measurement
        snap = sil.run_entropy_check(force=False)
        approved_24h = db.count_posts_by_type('post', hours=24) if hasattr(db, 'count_posts_by_type') else 0
        rejected_24h = 0
        if hasattr(db, 'count_rejected_signals'):
            rejected_24h = db.count_rejected_signals(hours=24)

        return jsonify({
            'enabled': True,
            'entropy': {
                'index':          snap.entropy_index if snap else None,
                'action_required': snap.action_required if snap else False,
                'recommended_actions': snap.recommended_actions if snap else [],
                'alert_frequency_1h': snap.alert_frequency_1h if snap else None,
                'correlation_inflation': snap.correlation_inflation_score if snap else None,
                'narrative_repetition': snap.repetitive_narrative_ratio if snap else None,
            } if snap else {},
            'thresholds': {
                'signal_min_score':          int(os.getenv('SIGNAL_MIN_SCORE', '52')),
                'council_escalation_score':  int(os.getenv('COUNCIL_ESCALATION_SCORE', '72')),
                'counterfactual_trigger':    int(os.getenv('COUNTERFACTUAL_TRIGGER_SCORE', '85')),
                'entropy_alert_threshold':   float(os.getenv('ENTROPY_ALERT_THRESHOLD', '0.72')),
                'max_council_per_cycle':     int(os.getenv('MAX_COUNCIL_SESSIONS_PER_CYCLE', '3')),
            },
            'last_24h': {
                'signals_approved': approved_24h,
                'signals_rejected': rejected_24h,
                'signal_to_noise_ratio': round(
                    approved_24h / max(approved_24h + rejected_24h, 1), 3
                ),
            }
        })
    except Exception as e:
        log.error(f"SIL status failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sil/bury', methods=['POST'])
def manual_burial():
    """
    Admin endpoint to manually bury a signal that produced false results.
    Use this to teach the organism what consistently wastes attention.

    Body JSON:
        signal_id  (required)
        reason     (optional, default: 'manual_review')
        ttl_days   (optional, default: 14)
    """
    if not SIL_ENABLED:
        return jsonify({'error': 'SIL not loaded'}), 503

    data      = request.get_json() or {}
    signal_id = data.get('signal_id')
    reason    = data.get('reason', 'manual_review')
    ttl       = int(data.get('ttl_days', 14))

    if not signal_id:
        return jsonify({'error': 'signal_id required'}), 400

    post = db.get_post(signal_id)
    if not post:
        return jsonify({'error': 'Signal not found'}), 404

    success = sil.burial.bury(post, reason=reason, ttl_days=ttl)
    return jsonify({'buried': success, 'signal_id': signal_id, 'reason': reason, 'ttl_days': ttl})


@app.route('/api/sil/reinforce', methods=['POST'])
def manual_reinforce():
    """
    Admin endpoint to positively reinforce a signal that proved accurate.
    Builds agent precision history.

    Body JSON:
        signal_id  (required)
        citizen    (required)
    """
    if not SIL_ENABLED:
        return jsonify({'error': 'SIL not loaded'}), 503

    data      = request.get_json() or {}
    signal_id = data.get('signal_id')
    citizen   = data.get('citizen')

    if not signal_id or not citizen:
        return jsonify({'error': 'signal_id and citizen required'}), 400

    success = sil.burial.reinforce_positive(signal_id, citizen)
    return jsonify({'reinforced': success, 'signal_id': signal_id, 'citizen': citizen})


@app.route('/api/sil/entropy', methods=['GET'])
def force_entropy_check():
    """
    Manually triggers an entropy measurement.
    Useful for debugging cognitive drift.
    """
    if not SIL_ENABLED:
        return jsonify({'error': 'SIL not loaded'}), 503
    try:
        snap = sil.run_entropy_check(force=True)
        if snap:
            import dataclasses
            return jsonify(dataclasses.asdict(snap))
        return jsonify({'message': 'No snapshot generated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────
# ROUTES — MANUAL TRIGGERS
# ─────────────────────────────────────
@app.route('/api/trigger/<agent_name>', methods=['GET', 'POST'])
def trigger_agent(agent_name):
    name = agent_name.upper()

    if name == 'TOWNHALL':
        import threading
        threading.Thread(target=check_for_disagreement, daemon=True).start()
        return jsonify({'ok': True, 'agent': 'TOWNHALL'}), 200

    if name == 'COUNCIL':
        import threading
        threading.Thread(target=lambda: COUNCIL.run_on_unprocessed(db), daemon=True).start()
        return jsonify({'ok': True, 'agent': 'COUNCIL'}), 200

    if name == 'ORACLE':
        import threading
        threading.Thread(target=lambda: ORACLE.run_on_unprocessed(db), daemon=True).start()
        return jsonify({'ok': True, 'agent': 'ORACLE'}), 200

    if name not in AGENTS:
        return jsonify({'error': 'Unknown agent'}), 404

    import threading
    def _run():
        try:
            result = AGENTS[name].run()
            _process_agent_output(name, result)
        except Exception as e:
            log.error(f"Trigger {name} failed: {e}")
            import traceback; log.error(traceback.format_exc())

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'agent': name}), 200


# ─────────────────────────────────────
# SCHEDULER — AGENT RUNS
# ─────────────────────────────────────
def run_agent(name):
    """
    Scheduled agent runner.
    All output passes through the Signal Integrity Layer before DB write.
    """
    log.info(f"Scheduled run: {name}")
    try:
        posts = AGENTS[name].run()
        _process_agent_output(name, posts)
    except NameError as e:
        log.error(f"{name} agent NameError (likely missing import in agent file): {e}")
        db.log_agent_run(name, 0, f"NameError: {e}")
    except Exception as e:
        log.error(f"{name} agent error: {e}")
        import traceback; log.error(traceback.format_exc())
        db.log_agent_run(name, 0, str(e))


def _process_agent_output(name: str, posts: list):
    """
    Core post-processing pipeline. Called by both run_agent() and trigger_agent().

    Flow:
      1. For each raw post, run through SIL scorer
      2. Posts below threshold are logged and discarded
      3. Posts above threshold are saved to DB
      4. Posts above council threshold are queued via Gatekeeper
      5. check_convergence() and check_for_disagreement() run on quality-filtered posts only
    """
    if not posts:
        _last_runs[name] = datetime.utcnow().isoformat()
        return

    saved_count    = 0
    rejected_count = 0
    council_batch  = []  # (post, score) pairs for gatekeeper

    for post in posts:
        if not post:
            continue

        if SIL_ENABLED:
            # ── SIGNAL INTEGRITY LAYER ────────────────────────────────────
            # Score every raw signal before it touches the database.
            # This is the thalamus: low-quality signals stop here.
            score = sil.process(post)

            if not score.passes_threshold:
                rejected_count += 1
                log.info(
                    f"[SIL] Rejected {post.get('id','?')} ({name}) "
                    f"score={score.credibility_score:.1f} reason={score.escalation_recommendation}"
                )
                continue

            # Persist the score record for audit trail
            if hasattr(db, 'save_signal_score'):
                try:
                    db.save_signal_score(score.to_dict())
                except Exception as e:
                    log.warning(f"[SIL] Could not save score record: {e}")

            # Track for gatekeeper if council-worthy
            if score.escalate_to_council:
                council_batch.append((post, score))

        # Signal passed — write to database
        db.save_post(post)
        saved_count += 1

    _last_runs[name] = datetime.utcnow().isoformat()
    db.log_agent_run(name, saved_count)
    log.info(f"{name}: {saved_count} saved, {rejected_count} rejected by SIL")

    # ── COUNCIL GATEKEEPER ────────────────────────────────────────────────
    # Only run if SIL is active and there are council-worthy signals.
    # Enforces domain diversity, deduplication, and session budget.
    if SIL_ENABLED and council_batch:
        try:
            gk_decision = sil.process_council_batch(council_batch)
            for signal_id in gk_decision.approved_for_council:
                approved_score = next(
                    (s for p, s in council_batch if p.get('id') == signal_id), None
                )
                if approved_score and hasattr(db, 'add_to_council_queue'):
                    batch_ids = next(
                        (b for b in gk_decision.batched_together if signal_id in b),
                        None
                    )
                    db.add_to_council_queue(
                        signal_id=signal_id,
                        score_dict=approved_score.to_dict(),
                        batch_ids=batch_ids
                    )
            log.info(
                f"[GATEKEEPER] Approved={len(gk_decision.approved_for_council)} "
                f"Suppressed={len(gk_decision.suppressed)} "
                f"Batched={len(gk_decision.batched_together)}"
            )
        except Exception as e:
            log.error(f"[GATEKEEPER] Batch processing failed: {e}")

    # ── CONVERGENCE + DISAGREEMENT ────────────────────────────────────────
    # Only runs on quality-filtered posts (those that passed the scorer).
    # Council now only sees signals that survived SIL — no more noise.
    if saved_count > 0:
        try:
            check_convergence()
        except Exception as e:
            log.error(f"check_convergence failed: {e}")
        try:
            check_for_disagreement()
        except Exception as e:
            log.error(f"check_for_disagreement failed: {e}")


# ─────────────────────────────────────
# TOPIC CLUSTERS & DIVERGENT PAIRS
# ─────────────────────────────────────
TOPIC_CLUSTERS = {
    # ── AI / ML ──────────────────────────────────────────────────────────────
    # Requires specific technical or organisational terms — not just "ai".
    # "ai" alone is too broad — a CERN paper and a hiring report both contain it.
    '#AI': [
        'large language model', 'llm', 'foundation model', 'transformer model',
        'inference endpoint', 'model weights', 'training run', 'benchmark score',
        'openai', 'anthropic', 'deepmind', 'mistral', 'meta ai', 'google gemini',
        'ai chip', 'gpu cluster', 'tpu', 'ai regulation', 'ai safety',
        'ai governance', 'model collapse', 'hallucination rate', 'rlhf',
        'fine-tuning', 'context window', 'token limit', 'ai procurement',
    ],

    # ── REGULATION ───────────────────────────────────────────────────────────
    # Requires specific regulatory body + action — not just "policy".
    # "regulation" alone matches too many domains.
    '#regulation': [
        'sec enforcement', 'sec filing', 'sec charges', 'sec subpoena',
        'ftc investigation', 'ftc complaint', 'ftc settlement',
        'fcc ruling', 'fcc fine', 'fcc license revocation',
        'fda approval', 'fda warning letter', 'fda recall', 'fda 510k',
        'doj indictment', 'doj settlement', 'doj probe',
        'cftc enforcement', 'finra sanction',
        'antitrust lawsuit', 'antitrust investigation',
        'consent decree', 'regulatory comment period', 'notice of proposed rulemaking',
        'federal register rule', 'executive order signed',
    ],

    # ── CRYPTO / DIGITAL ASSETS ───────────────────────────────────────────────
    # Specific instruments and events — not just "blockchain".
    '#crypto': [
        'bitcoin price', 'btc', 'ethereum', 'eth price', 'usdt', 'usdc',
        'stablecoin depeg', 'defi protocol', 'smart contract exploit',
        'crypto exchange', 'binance', 'coinbase', 'kraken', 'bybit',
        'crypto wallet', 'on-chain volume', 'mempool', 'gas fees',
        'nft floor price', 'dao vote', 'token launch', 'token burn',
        'crypto regulation', 'sec crypto', 'cftc crypto',
        'cold wallet', 'hot wallet', 'bridge exploit',
    ],

    # ── PHYSICAL INFRASTRUCTURE ───────────────────────────────────────────────
    # Tightened: requires specific infrastructure type + action/anomaly.
    # Removes 'infrastructure' alone — it matched CERN + FEMA contract.
    # Removes 'permit' and 'energy' alone — too generic.
    '#infrastructure': [
        'spectrum license', 'spectrum auction', 'fcc spectrum',
        'faa temporary flight restriction', 'faa notam',
        'fiber optic permit', 'broadband deployment',
        'cell tower construction', 'antenna array',
        'data center power', 'data center permit', 'hyperscale facility',
        'power grid expansion', 'transmission line', 'substation upgrade',
        'pipeline permit', 'lng terminal', 'gas infrastructure',
        'port expansion', 'rail freight corridor',
        'zoning variance', 'building permit cluster',
    ],

    # ── BIOTECH / PHARMA / HEALTH ─────────────────────────────────────────────
    # Requires clinical or regulatory specificity — not just "health".
    '#biotech': [
        'phase 1 trial', 'phase 2 trial', 'phase 3 trial', 'clinical trial results',
        'fda approval', 'fda breakthrough designation', 'fda fast track',
        'anda filing', 'nda submission', 'biologics license',
        'drug recall', 'drug shortage', 'generic drug approval',
        'crispr therapy', 'gene editing', 'mrna platform',
        'antibody drug', 'biosimilar launch', 'orphan drug designation',
        'pandemic preparedness', 'outbreak declaration', 'cdc alert',
        'who emergency', 'epidemiological signal', 'excess mortality',
        'biotech acquisition', 'pharma merger',
    ],

    # ── LABOUR / WORKFORCE ────────────────────────────────────────────────────
    # Requires scale or specificity — not just "jobs".
    '#labor': [
        'mass layoff', 'reduction in force', 'headcount reduction',
        'hiring freeze', 'hiring surge', 'job posting spike',
        'executive departure', 'ceo resignation', 'cto departure',
        'union strike', 'union vote', 'collective bargaining',
        'h1b visa', 'work visa', 'foreign worker',
        'return to office mandate', 'remote work policy change',
        'severance package', 'warn act', 'worker displacement',
        'gig worker classification', 'contractor to employee',
    ],

    # ── CLIMATE / ENVIRONMENT ─────────────────────────────────────────────────
    # Requires specific measurement or event — not just "climate".
    '#climate': [
        'carbon credit', 'carbon offset', 'net zero pledge',
        'emissions target', 'scope 3 emissions', 'esg disclosure',
        'renewable energy capacity', 'solar installation', 'wind farm permit',
        'battery storage deployment', 'ev charging network',
        'coal plant closure', 'fossil fuel divestment',
        'climate litigation', 'epa rule', 'epa waiver',
        'noaa temperature anomaly', 'arctic sea ice extent',
        'wildfire risk', 'flood risk mapping', 'drought index',
        'paris agreement', 'carbon border tax',
    ],

    # ── MEDIA / NARRATIVE ────────────────────────────────────────────────────
    # Requires coordination or anomaly — not just "media".
    '#media': [
        'coordinated publishing', 'identical headline', 'wire service anomaly',
        'gdelt spike', 'narrative saturation', 'media blackout',
        'story suppression', 'retraction pattern', 'correction cluster',
        'outlet acquisition', 'media merger', 'newsroom closure',
        'journalist arrest', 'press freedom index',
        'content moderation policy', 'platform deplatform',
        'search result suppression', 'algorithm change',
    ],

    # ── FINANCE / CAPITAL MARKETS ─────────────────────────────────────────────
    # Requires specific instrument or corporate event — not just "market".
    '#finance': [
        'ipo filing', 'ipo withdrawal', 's-1 filing', 'spac merger',
        'acquisition announced', 'merger agreement', 'hostile takeover',
        'private equity buyout', 'leveraged buyout', 'going private',
        'bond yield spike', 'credit spread widening', 'cds spread',
        'options flow anomaly', 'short interest spike', 'sec form 4',
        'insider buying', 'insider selling cluster',
        'earnings miss', 'earnings beat', 'guidance cut',
        'dividend cut', 'share buyback pause', 'debt downgrade',
        'treasury yield inversion', 'fed rate decision',
    ],

    # ── GOVERNMENT CONTRACTS / PROCUREMENT ───────────────────────────────────
    # Requires dollar amount or specific agency — not just "government".
    '#government': [
        'usaspending award', 'federal contract award', 'gsa contract',
        'defense contract', 'pentagon award', 'dod procurement',
        'classified contract', 'sole source award', 'no-bid contract',
        'foia request', 'foia exemption', 'executive order',
        'national security directive', 'sanctions designation',
        'export control', 'itar restriction', 'ear restriction',
        'lobbying disclosure', 'pac contribution', 'revolving door',
    ],

    # ── SUPPLY CHAIN / COMMODITIES ────────────────────────────────────────────
    # Requires specific commodity, route, or flow data.
    '#supplychain': [
        'baltic dry index', 'bdi', 'container rate', 'freight rate spike',
        'port congestion', 'port closure', 'vessel rerouting',
        'ais anomaly', 'tanker diversion', 'oil tanker',
        'un comtrade', 'trade flow reversal', 'export ban',
        'semiconductor shortage', 'chip allocation',
        'rare earth supply', 'lithium supply', 'cobalt supply',
        'cold storage capacity', 'grain export', 'wheat shipment',
        'logistics bottleneck', 'just-in-time disruption',
    ],

    # ── PATENTS / IP ──────────────────────────────────────────────────────────
    # Requires filing specificity — not just "patent".
    '#patents': [
        'patent filing', 'patent application', 'patent grant',
        'provisional patent', 'continuation application',
        'patent assignment', 'patent transfer', 'ip acquisition',
        'wipo filing', 'pct application', 'uspto grant',
        'patent cluster', 'patent pool', 'patent licensing',
        'standard essential patent', 'patent litigation',
        'trade secret claim', 'ip lawsuit', 'patent troll',
        'bayh-dole', 'federal research patent',
    ],

    # ── CYBERSECURITY / BREACH ────────────────────────────────────────────────
    # Requires specific incident type — not just "hack".
    '#security': [
        'data breach', 'credential leak', 'password dump',
        'ransomware attack', 'ransomware group',
        'zero-day exploit', 'cve published', 'patch tuesday',
        'vulnerability disclosure', 'responsible disclosure',
        'nation state attack', 'apt group', 'cyber espionage',
        'supply chain attack', 'software backdoor',
        'ddos attack', 'infrastructure attack',
        'haveibeenpwned', 'hibp', 'breach notification',
        'incident response', 'forensic investigation',
    ],

    # ── HISTORICAL PATTERN / PRECEDENT ────────────────────────────────────────
    # Requires explicit historical comparison — not just "history".
    '#history': [
        'historical precedent', 'rhymes with', 'echoes of',
        'parallel to', 'reminiscent of', 'analog to',
        'same pattern as', 'last time this happened',
        'wayback machine', 'archived page', 'deleted content',
        'internet archive', 'cached version',
        'predecessor company', 'former entity', 'dormant domain',
        'executive silence pattern', 'synchronized deletion',
    ],
}

DIVERGENT_PAIRS = [
    ('VERA',    'DUKE'),  ('VERA',    'KAEL'),  ('MIRA',    'DUKE'),
    ('SOL',     'KAEL'),  ('ECHO',    'DUKE'),  ('NOVA',    'MIRA'),
    ('FLUX',    'REX'),   ('FLUX',    'DUKE'),  ('REX',     'VERA'),
    ('REX',     'KAEL'),  ('VIGIL',   'DUKE'),  ('VIGIL',   'FLUX'),
    ('VIGIL',   'KAEL'),  ('LORE',    'VERA'),  ('LORE',    'DUKE'),
    ('LORE',    'REX'),   ('SPECTER', 'KAEL'),  ('SPECTER', 'DUKE'),
    ('SPECTER', 'ECHO'),  ('SPECTER', 'NOVA'),
]

def _post_topics(post):
    body = (post.get('body', '') or '').lower()
    tags = ' '.join(t.lower() for t in post.get('tags', []))
    combined = body + ' ' + tags
    return {tag for tag, kws in TOPIC_CLUSTERS.items() if any(kw in combined for kw in kws)}

def check_convergence():
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
            topic_citizens[topic].add(citizen)
            topic_posts[topic].append(post)
    for topic_tag, citizens in topic_citizens.items():
        if len(citizens) >= 2:
            existing = db.get_signal_alert_for_tag(topic_tag)
            if not existing:
                log.info(f"CONVERGENCE on {topic_tag} — {citizens}")
                create_signal_alert(topic_tag, topic_posts[topic_tag], list(citizens))

def create_signal_alert(tag, matching_posts, citizens=None):
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

    alert_id = str(uuid.uuid4())
    alert = {
        'id':        alert_id,
        'type':      'signal_alert',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  citizens,
        'headline':  f'SIGNAL ALERT — {len(citizens)}-WAY CONVERGENCE on {tag}',
        'body':      f'Multiple independent data streams independently converged on: {tag}.',
        'tags':      [tag, '#convergence'],
        'thread':    thread,
    }
    db.save_post(alert)
    log.info(f"Signal Alert created: {tag} (id: {alert_id})")

    # Signal alerts do NOT trigger Council directly.
    # Council is only triggered by qualified Town Halls.

def _town_hall_worth_debating(post_a, post_b, topic_tag):
    """
    Quality gate: decide whether a Town Hall is substantive enough for Council.
    Score ≥ 2 out of 4 to qualify.
    """
    LOW_SIGNAL_TAGS = {'#AI', '#regulation', '#finance', '#government'}
    HIGH_VALUE_PAIRS = {
        frozenset({'VIGIL', 'DUKE'}), frozenset({'VIGIL', 'FLUX'}),
        frozenset({'VIGIL', 'KAEL'}), frozenset({'LORE',  'VERA'}),
        frozenset({'SPECTER', 'DUKE'}), frozenset({'SPECTER', 'ECHO'}),
        frozenset({'FLUX', 'REX'}), frozenset({'REX', 'KAEL'}),
    }
    score = 0

    body_a = (post_a.get('body') or '')
    body_b = (post_b.get('body') or '')
    if len(body_a) > 120 and len(body_b) > 120:
        score += 1

    if topic_tag not in LOW_SIGNAL_TAGS:
        score += 1

    r_a = post_a.get('reactions') or {}
    r_b = post_b.get('reactions') or {}
    if isinstance(r_a, str):
        try: r_a = json.loads(r_a)
        except: r_a = {}
    if isinstance(r_b, str):
        try: r_b = json.loads(r_b)
        except: r_b = {}
    total_reactions = sum(r_a.values()) + sum(r_b.values())
    if total_reactions > 0:
        score += 1

    pair = frozenset({post_a.get('citizen',''), post_b.get('citizen','')})
    if pair in HIGH_VALUE_PAIRS:
        score += 1

    return score >= 2


def create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag):
    th_id = str(uuid.uuid4())
    th = {
        'id':        th_id,
        'type':      'town_hall',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  [citizen_a, citizen_b],
        'topic':     f'Divergence detected on {topic_tag} — {citizen_a} vs {citizen_b}',
        'tags':      [topic_tag, '#divergence', '#townhall'],
        'positions': [
            {'citizen': citizen_a, 'stance': 'Signals', 'text': (post_a.get('body','') or '')[:300]},
            {'citizen': citizen_b, 'stance': 'Counter', 'text': (post_b.get('body','') or '')[:300]},
        ],
        'votes': {citizen_a: 0, citizen_b: 0, 'neutral': 0},
    }
    db.save_post(th)
    log.info(f"Town Hall created: {citizen_a} vs {citizen_b} on {topic_tag}")

    # ── COUNCIL GATE ──────────────────────────────────────────────────────────
    # Town Halls are the quality filter for Council access.
    # Signal Alerts go straight to feed but never trigger Council directly.
    if _town_hall_worth_debating(post_a, post_b, topic_tag):
        log.info(f"Town Hall qualified for Council: {citizen_a} vs {citizen_b} on {topic_tag}")
        import threading, time
        def _trigger_council():
            time.sleep(8)  # Let DB settle
            try:
                COUNCIL.run_on_unprocessed(db)
            except Exception as e:
                log.error(f"Council trigger from town hall failed: {e}")
        threading.Thread(target=_trigger_council, daemon=True).start()
    else:
        log.info(f"Town Hall did NOT qualify for Council: {citizen_a} vs {citizen_b} on {topic_tag}")

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
        shared   = topics_a & topics_b - {'#convergence'}
        if not shared:
            continue
        topic_tag = sorted(shared)[0]
        if db.get_town_hall_for_pair(citizen_a, citizen_b, topic_tag):
            continue
        kws    = TOPIC_CLUSTERS.get(topic_tag, [])
        post_a = next((p for p in posts_a if any(kw in (p.get('body','') or '').lower() for kw in kws)), posts_a[0])
        post_b = next((p for p in posts_b if any(kw in (p.get('body','') or '').lower() for kw in kws)), posts_b[0])
        log.info(f"DISAGREEMENT: {citizen_a} vs {citizen_b} on {topic_tag}")
        create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag)

def setup_scheduler():
    scheduler = BackgroundScheduler()

    # ── AGENT SCHEDULE ────────────────────────────────────────────────────────
    scheduler.add_job(lambda: run_agent('VERA'),      'interval', hours=2,  id='vera')
    scheduler.add_job(lambda: run_agent('DUKE'),      'interval', hours=2,  id='duke')
    scheduler.add_job(lambda: run_agent('MIRA'),      'interval', hours=1,  id='mira')
    scheduler.add_job(lambda: run_agent('SOL'),       'interval', hours=3,  id='sol')
    scheduler.add_job(lambda: run_agent('NOVA'),      'interval', hours=6,  id='nova')
    scheduler.add_job(lambda: run_agent('ECHO'),      'interval', hours=2,  id='echo')
    scheduler.add_job(lambda: run_agent('KAEL'),      'interval', hours=1,  id='kael')
    scheduler.add_job(lambda: run_agent('FLUX'),      'interval', hours=2,  id='flux')
    scheduler.add_job(lambda: run_agent('REX'),       'interval', hours=2,  id='rex')
    scheduler.add_job(lambda: run_agent('VIGIL'),     'interval', hours=4,  id='vigil')
    scheduler.add_job(lambda: run_agent('LORE'),      'interval', hours=6,  id='lore')
    scheduler.add_job(lambda: run_agent('SPECTER'),   'interval', hours=3,  id='specter')

    # CASSANDRA runs every 6 hours — she reads what others produced, so offset by 30min
    scheduler.add_job(lambda: run_agent('CASSANDRA'), 'interval', hours=6, id='cassandra',
                      start_date=datetime.now() + timedelta(minutes=30))
    # CASSANDRA runs every 3h but starts 90min after boot
    # so other agents have already fired and she has signals to analyse
    scheduler.add_job(lambda: run_agent('CASSANDRA'), 'interval', hours=3,  id='cassandra',
                      start_date=datetime.now() + timedelta(minutes=90))

    # Council every 4hrs; ORACLE offset by 1hr so sessions exist when it runs
    scheduler.add_job(lambda: COUNCIL.run_on_unprocessed(db), 'interval', hours=4, id='council')
    scheduler.add_job(lambda: ORACLE.run_on_unprocessed(db),  'interval', hours=4,
                      id='oracle', start_date=datetime.now() + timedelta(hours=1))

    # ── ENTROPY MONITOR ───────────────────────────────────────────────────────
    # Runs every 3 hours. Detects cognitive drift and adjusts thresholds.
    # The organism becomes quieter when entropy rises — that is intentional.
    if SIL_ENABLED:
        def _run_entropy():
            try:
                snap = sil.run_entropy_check()
                if snap and snap.action_required:
                    log.warning(
                        f"[ENTROPY] Action required. "
                        f"Index={snap.entropy_index:.3f} "
                        f"Actions={snap.recommended_actions}"
                    )
            except Exception as e:
                log.error(f"[ENTROPY] Scheduled check failed: {e}")

        scheduler.add_job(_run_entropy, 'interval', hours=3, id='entropy_monitor',
                          start_date=datetime.now() + timedelta(minutes=10))
        log.info("Entropy monitor scheduled: every 3 hours")

    scheduler.start()
    log.info("Scheduler started — 12 agents + COUNCIL + ORACLE" +
             (" + ENTROPY_MONITOR" if SIL_ENABLED else ""))
    return scheduler

# ─────────────────────────────────────
# MAIN
# ─────────────────────────────────────
if __name__ == '__main__':
    db.init()
    scheduler = setup_scheduler()
    port = int(os.environ.get('PORT', 5000))
    log.info(f"Signal Society running on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

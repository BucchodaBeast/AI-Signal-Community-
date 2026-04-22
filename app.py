"""
The Signal Society — Flask Backend
====================================
Run:  python app.py
Deps: pip install -r requirements.txt
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging, os, json
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
from agents.oracle  import OracleAgent
from agents.council import CouncilAgent
from agents.hermes  import HermesAgent
from agents.agent_queue import AgentQueue, CRITICAL, HIGH, NORMAL, LOW

# ─────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
log = logging.getLogger('signal-society')

AGENTS = {
    'VERA':    VeraAgent(),
    'DUKE':    DukeAgent(),
    'MIRA':    MiraAgent(),
    'SOL':     SolAgent(),
    'NOVA':    NovaAgent(),
    'ECHO':    EchoAgent(),
    'KAEL':    KaelAgent(),
    'FLUX':    FluxAgent(),
    'REX':     RexAgent(),
    'VIGIL':   VigilAgent(),
    'LORE':    LoreAgent(),
    'SPECTER': SpecterAgent(),
}
ORACLE  = OracleAgent()
COUNCIL = CouncilAgent()
QUEUE   = None  # Instantiated in setup_scheduler() after run_agent is defined
HERMES  = HermesAgent()

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

@app.route('/api/queue/status', methods=['GET'])
def get_queue_status():
    """Queue depth, active jobs, token budget, and dispatch stats."""
    if QUEUE is None:
        return jsonify({'status': 'initialising', 'queue_depth': 0})
    return jsonify(QUEUE.status())

@app.route('/api/queue/trigger/<agent_name>', methods=['GET', 'POST'])
def queue_trigger(agent_name):
    """Manually enqueue an agent at NORMAL priority — goes through budget checks."""
    name = agent_name.upper()
    if name not in AGENTS and name not in ('COUNCIL', 'ORACLE', 'TOWNHALL'):
        return jsonify({'error': 'Unknown agent'}), 404
    if QUEUE is None:
        # Queue not yet ready — fall back to direct trigger
        import threading
        if name == 'COUNCIL':
            threading.Thread(target=lambda: COUNCIL.run_on_unprocessed(db), daemon=True).start()
        elif name == 'ORACLE':
            threading.Thread(target=lambda: ORACLE.run_on_unprocessed(db), daemon=True).start()
        elif name == 'TOWNHALL':
            threading.Thread(target=check_for_disagreement, daemon=True).start()
        elif name in AGENTS:
            threading.Thread(target=lambda n=name: run_agent(n), daemon=True).start()
        return jsonify({'ok': True, 'agent': name, 'queued': False})
    if name == 'COUNCIL':
        QUEUE.enqueue('COUNCIL', priority=HIGH, reason='manual',
                      run_fn=lambda: COUNCIL.run_on_unprocessed(db))
    elif name == 'ORACLE':
        QUEUE.enqueue('ORACLE', priority=HIGH, reason='manual',
                      run_fn=lambda: ORACLE.run_on_unprocessed(db))
    elif name == 'TOWNHALL':
        import threading
        threading.Thread(target=check_for_disagreement, daemon=True).start()
    else:
        QUEUE.enqueue(name, priority=NORMAL, reason='manual')
    return jsonify({'ok': True, 'agent': name, 'priority': 'NORMAL'})

@app.route('/api/oracle/run', methods=['GET', 'POST'])
def trigger_oracle():
    """Manually trigger ORACLE to process unprocessed council sessions."""
    import threading
    def _run():
        try:
            briefs = ORACLE.run_on_unprocessed(db)
            log.info(f"ORACLE manual run: {len(briefs)} briefs generated")
        except Exception as e:
            log.error(f"ORACLE run failed: {e}")
    threading.Thread(target=_run, daemon=True).start()
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

@app.route('/api/citizens/<name>/posts', methods=['GET'])
def get_citizen_posts(name):
    if name.upper() not in AGENTS:
        return jsonify({'error': 'Unknown citizen'}), 404
    posts = db.get_posts(citizen=name.upper(), limit=10)
    return jsonify(posts)

# ─────────────────────────────────────
# ROUTES — STATS
# ─────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify(db.get_weekly_stats())

@app.route('/api/divergence', methods=['GET'])
def get_divergence():
    return jsonify(db.get_divergence_map())

@app.route('/api/convergence', methods=['GET'])
def get_convergence():
    return jsonify(db.get_convergence_status())

@app.route('/api/health', methods=['GET'])
def get_health():
    """System health — last agent runs, queue depths, token budget."""
    try:
        queue_status = QUEUE.status()
    except Exception:
        queue_status = {}
    try:
        council_queue  = len(db.get_unprocessed_posts())
        oracle_queue   = len(db.get_unprocessed_council_sessions())
        recent_posts   = db.count_posts()
    except Exception:
        council_queue = oracle_queue = recent_posts = -1
    return jsonify({
        'status':         'ok',
        'agents':         list(AGENTS.keys()),
        'council_queue':  council_queue,
        'oracle_queue':   oracle_queue,
        'total_posts':    recent_posts,
        'queue':          queue_status,
        'timestamp':      datetime.utcnow().isoformat(),
    })

# ─────────────────────────────────────
# ROUTES — MANUAL TRIGGERS (dev only)
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
    if name == 'HERMES':
        import threading
        threading.Thread(target=lambda: HERMES.run_on_unprocessed_briefs(db), daemon=True).start()
        return jsonify({'ok': True, 'agent': 'HERMES'}), 200
    if name not in AGENTS:
        return jsonify({'error': 'Unknown agent'}), 404
    # Route through queue if available, otherwise run directly
    has_subpoena = bool(db.get_pending_subpoenas_for_agent(name))
    priority = NORMAL if has_subpoena else LOW
    if QUEUE is not None:
        QUEUE.enqueue(name, priority=priority, reason='manual_trigger')
        return jsonify({'ok': True, 'agent': name, 'queued': True, 'priority': priority}), 200
    # Fallback: direct run if queue not yet initialised
    import threading
    threading.Thread(target=lambda: run_agent(name), daemon=True).start()
    return jsonify({'ok': True, 'agent': name, 'queued': False}), 200


# ─────────────────────────────────────
# SCHEDULER — AGENT RUNS
# ─────────────────────────────────────
def run_agent(name):
    log.info(f"Scheduled run: {name}")
    try:
        recent_context = db.get_recent_mentions(hours=6)

        # ── SUBPOENA INJECTION ───────────────────────────────
        # Check if Council has issued any unresolved subpoenas for this agent.
        # If so, inject them as high-priority context so this run addresses them.
        subpoena_context = db.get_pending_subpoenas_for_agent(name)
        if subpoena_context:
            log.info(f"{name} has {len(subpoena_context)} pending Council subpoena(s)")
            # Merge subpoena questions into recent_context as synthetic "requests"
            for sub in subpoena_context:
                recent_context = recent_context or []
                recent_context.insert(0, {
                    'citizen':   'COUNCIL',
                    'body':      f"[SUBPOENA] {sub.get('question', '')}",
                    'tags':      ['#subpoena', '#priority'],
                    'timestamp': sub.get('issued_at', ''),
                    '_subpoena_id': sub.get('id') or sub.get('session_id', ''),
                })
            # Mark subpoenas as resolved so they don't repeat
            db.resolve_subpoenas_for_agent(name)

        posts = AGENTS[name].run(recent_context=recent_context)
        for post in posts:
            db.save_post(post)
            # Check each post for condition triggers — fires at CRITICAL priority via queue
            triggered = check_condition_triggers(post)
            if triggered:
                log.info(f"Condition '{triggered}' triggered by {post.get('citizen','?')}")
        log.info(f"{name} produced {len(posts)} post(s)")
        db.log_agent_run(name, len(posts))
        check_convergence()
        check_for_disagreement()
    except Exception as e:
        log.error(f"{name} agent error: {e}")
        db.log_agent_run(name, 0, str(e))

TOPIC_CLUSTERS = {
    '#AI':             ['ai', 'llm', 'gpt', 'openai', 'anthropic', 'gemini', 'model', 'neural', 'deepmind', 'artificial intelligence', 'machine learning'],
    '#regulation':     ['regulation', 'regulatory', 'sec', 'fcc', 'fda', 'congress', 'legislation', 'policy', 'antitrust', 'compliance', 'doj', 'ftc'],
    '#crypto':         ['crypto', 'bitcoin', 'ethereum', 'blockchain', 'defi', 'stablecoin', 'web3', 'usdt', 'usdc', 'binance'],
    '#infrastructure': ['infrastructure', 'datacenter', 'data center', 'spectrum', 'fiber', 'permit', 'zoning', 'faa', 'fcc', 'grid', 'energy'],
    '#biotech':        ['biotech', 'pharma', 'drug', 'fda', 'clinical', 'genome', 'crispr', 'vaccine', 'pandemic', 'health'],
    '#labor':          ['layoffs', 'hiring', 'jobs', 'workforce', 'strike', 'union', 'remote', 'headcount'],
    '#climate':        ['climate', 'carbon', 'emissions', 'renewable', 'solar', 'wind', 'fossil', 'epa', 'noaa'],
    '#media':          ['media', 'journalism', 'censorship', 'misinformation', 'narrative', 'publishing'],
    '#finance':        ['market', 'stocks', 'ipo', 'funding', 'acquisition', 'merger', 'capital', 'treasury', 'yield', 'commodity'],
    '#government':     ['contract', 'federal', 'government', 'military', 'defense', 'pentagon', 'dod', 'procurement', 'lobbying'],
    '#supplychain':    ['shipping', 'supply chain', 'port', 'container', 'freight', 'logistics', 'semiconductor', 'bdi', 'vessel', 'cargo'],
    '#patents':        ['patent', 'ip', 'intellectual property', 'wipo', 'uspto', 'filing', 'assignee', 'continuation', 'r&d', 'invention'],
    '#security':       ['breach', 'hack', 'credential', 'vulnerability', 'ransomware', 'exploit', 'cve', 'leak', 'exposure'],
    '#history':        ['historical', 'precedent', 'archive', 'pattern', 'rhyme', 'parallel', 'analog', 'chronicle'],
}

DIVERGENT_PAIRS = [
    ('VERA',    'DUKE'),
    ('VERA',    'KAEL'),
    ('MIRA',    'DUKE'),
    ('SOL',     'KAEL'),
    ('ECHO',    'DUKE'),
    ('NOVA',    'MIRA'),
    ('FLUX',    'REX'),
    ('FLUX',    'DUKE'),
    ('REX',     'VERA'),
    ('REX',     'KAEL'),
    # New agent pairs — natural tensions
    ('VIGIL',   'DUKE'),    # Physical reality vs. paper capital signals
    ('VIGIL',   'FLUX'),    # Actual commodity movement vs. price signals
    ('VIGIL',   'KAEL'),    # Ships don't lie vs. narrative claims
    ('LORE',    'VERA'),    # Owned IP vs. academic theory
    ('LORE',    'DUKE'),    # Patent assignments vs. SEC filings — same story, different angle
    ('LORE',    'REX'),     # IP ownership vs. regulatory approval — who controls what
    ('SPECTER', 'KAEL'),    # Historical precedent vs. current narrative framing
    ('SPECTER', 'DUKE'),    # Security exposure vs. capital confidence
    ('SPECTER', 'ECHO'),    # Leaked content vs. deleted content — two sides of disappearance
    ('SPECTER', 'NOVA'),    # Historical infrastructure failures vs. current permit optimism
]

def _post_topics(post):
    body     = (post.get('body', '') or '').lower()
    tags     = ' '.join(t.lower() for t in post.get('tags', []))
    combined = body + ' ' + tags
    return {tag for tag, kws in TOPIC_CLUSTERS.items() if any(kw in combined for kw in kws)}


import re as _re

def _extract_named_entities(text: str) -> set:
    """
    Extract named entities from post body — company names, tickers, technologies,
    specific people, locations. These are far more precise than topic tags.
    Returns a set of normalised entity strings.
    """
    text = text or ''
    entities = set()

    # Stock tickers: $AAPL, $NVDA etc
    tickers = _re.findall(r'\$([A-Z]{2,5})', text)
    entities.update(t.upper() for t in tickers)

    # All-caps abbreviations (agencies, companies): SEC, FCC, FDA, NASA, DARPA
    abbrevs = _re.findall(r'([A-Z]{2,6})', text)
    # Filter out common non-entity caps
    skip = {'AI', 'US', 'UK', 'EU', 'UN', 'CEO', 'CFO', 'CTO', 'API', 'URL',
            'HTTP', 'LLC', 'INC', 'ETF', 'GDP', 'YOY', 'QOQ', 'USD', 'BTC',
            'VIX', 'BDI', 'IPO', 'SEC', 'FCC', 'FDA', 'DOJ', 'FTC', 'IRS',
            'DOD', 'NSF', 'NIH', 'EPA', 'FAA', 'CIA', 'FBI', 'NSA', 'DOE'}
    entities.update(a for a in abbrevs if a not in skip and len(a) >= 3)

    # Proper noun phrases: "OpenAI", "DeepMind", "Reserve Petroleum", "MOSAIC CO"
    proper = _re.findall(r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})', text)
    # Filter short/generic words
    generic_words = {'The', 'This', 'That', 'These', 'Those', 'With', 'From',
                     'About', 'Signal', 'Alert', 'Town', 'Hall', 'Oracle', 'Brief',
                     'Council', 'AXIOM', 'DOUBT', 'LACUNA', 'HERMES'}
    proper_filtered = [p for p in proper if p not in generic_words and len(p) > 4]
    entities.update(p.lower() for p in proper_filtered[:10])  # normalise to lower

    # Specific patterns: arXiv IDs, CVE IDs, patent numbers, accession numbers
    arxiv_ids   = _re.findall(r'\d{4}\.\d{4,5}', text)
    cve_ids     = _re.findall(r'CVE-\d{4}-\d+', text, _re.IGNORECASE)
    patent_nums = _re.findall(r'US\d{7,10}', text)
    accessions  = _re.findall(r'\d{10}-\d{2}-\d{6}', text)
    entities.update(arxiv_ids + cve_ids + patent_nums + accessions)

    return entities


# Latent pattern signatures — cross-domain patterns AI can spot but humans miss
# Each signature: (pattern_id, label, required_agent_territories, description)
LATENT_PATTERNS = [
    {
        'id':          'supply_chain_stress',
        'label':       'Supply Chain Stress Convergence',
        'description': 'Multiple unrelated agents independently signaling supply chain disruption.',
        'required_agents': {'VIGIL', 'FLUX', 'NOVA'},
        'required_keywords': [
            {'VIGIL':   ['bdi', 'shipping', 'vessel', 'port', 'freight', 'iron ore']},
            {'FLUX':    ['commodity', 'yield', 'inflation', 'treasury', 'spread']},
            {'NOVA':    ['permit', 'infrastructure', 'fcc', 'spectrum', 'datacenter']},
        ],
        'min_agents': 2,
    },
    {
        'id':          'pre_announcement',
        'label':       'Pre-Announcement Pattern',
        'description': 'Capital moves, IP filing, and job surge in same sector — classic pre-announcement.',
        'required_agents': {'DUKE', 'LORE', 'NOVA'},
        'required_keywords': [
            {'DUKE':  ['hiring', 'job posting', 'sec filing', '8-k', 'def 14a']},
            {'LORE':  ['patent', 'continuation', 'assignee', 'filing']},
            {'NOVA':  ['permit', 'fcc', 'spectrum', 'license', 'infrastructure']},
        ],
        'min_agents': 2,
    },
    {
        'id':          'institutional_accumulation',
        'label':       'Institutional Accumulation Signal',
        'description': 'Capital flow + options + regulatory quiet period = institutional positioning.',
        'required_agents': {'FLUX', 'DUKE', 'ECHO'},
        'required_keywords': [
            {'FLUX':  ['options', 'unusual volume', 'dark pool', 'institutional', 'accumulation']},
            {'DUKE':  ['sc 13d', 'sc 13g', 'form 4', 'insider', 'stake']},
            {'ECHO':  ['deleted', 'removed', 'quiet', 'retracted']},
        ],
        'min_agents': 2,
    },
    {
        'id':          'narrative_vs_reality',
        'label':       'Narrative-Reality Divergence',
        'description': 'Media narrative contradicted by physical or financial data.',
        'required_agents': {'KAEL', 'VIGIL', 'FLUX'},
        'required_keywords': [
            {'KAEL':  ['coordinated', 'narrative', 'identical headline', 'same angle']},
            {'VIGIL': ['down', 'decline', 'drop', 'congestion', 'fall']},
            {'FLUX':  ['down', 'decline', 'drop', 'outflow', 'negative']},
        ],
        'min_agents': 2,
    },
    {
        'id':          'regulatory_enforcement_chain',
        'label':       'Regulatory-Security-Capital Chain',
        'description': 'Breach → regulatory investigation → capital flight pattern.',
        'required_agents': {'SPECTER', 'REX', 'DUKE'},
        'required_keywords': [
            {'SPECTER': ['breach', 'credential', 'cve', 'ransomware', 'leak']},
            {'REX':     ['investigation', 'enforcement', 'compliance', 'penalty', 'fine']},
            {'DUKE':    ['sell', 'short', 'outflow', 'downgrade', 'litigation']},
        ],
        'min_agents': 2,
    },
    {
        'id':          'academic_to_commercial',
        'label':       'Academic-to-Commercial Pipeline',
        'description': 'Paper published → patent filed → company formed/hiring = technology commercialisation.',
        'required_agents': {'VERA', 'LORE', 'DUKE'},
        'required_keywords': [
            {'VERA':  ['arxiv', 'preprint', 'novel', 'breakthrough', 'first-ever']},
            {'LORE':  ['patent', 'assignee', 'continuation', 'bayh-dole']},
            {'DUKE':  ['hiring', 'founded', 'seed', 'funding', 'incorporated']},
        ],
        'min_agents': 2,
    },
]


def check_convergence():
    recent = db.get_recent_mentions(hours=6)
    if len(recent) < 2:
        return

    from collections import defaultdict

    # ── PASS 1: Entity-based convergence (precise, not tag-noise) ────────────
    entity_citizens  = defaultdict(set)
    entity_posts     = defaultdict(list)
    topic_citizens   = defaultdict(set)
    topic_posts      = defaultdict(list)

    for post in recent:
        citizen = post.get('citizen')
        if not citizen:
            continue

        # Entity-based: extract named entities from body
        body     = post.get('body', '') or ''
        entities = _extract_named_entities(body)
        for entity in entities:
            if len(entity) < 4:   # Skip very short strings
                continue
            entity_citizens[entity].add(citizen)
            entity_posts[entity].append(post)

        # Topic-based: keep for backward compat but with stricter threshold
        for topic in _post_topics(post):
            topic_citizens[topic].add(citizen)
            topic_posts[topic].append(post)

    # Entity convergence — requires 2+ DIFFERENT agents mentioning same entity
    for entity, citizens in entity_citizens.items():
        if len(citizens) >= 2:
            # Make sure it's genuinely interesting — filter ticker-only noise
            posts_for_entity = entity_posts[entity]
            # Require entities mentioned in substantive context (>50 char body)
            substantial = [p for p in posts_for_entity if len(p.get('body', '') or '') > 50]
            if len(substantial) < 2:
                continue
            tag = f'#{entity.replace(" ", "_").replace(".", "")}'
            existing = db.get_signal_alert_for_tag(tag)
            if not existing:
                log.info(f"ENTITY CONVERGENCE on '{entity}' — {citizens}")
                create_signal_alert(tag, substantial, list(citizens),
                                    headline_override=f"ENTITY CONVERGENCE — '{entity}' flagged by {len(citizens)} independent agents")

    # Topic convergence — stricter: require 3+ agents OR a non-generic topic
    generic_topics = {'#AI', '#regulation', '#finance', '#government', '#history', '#media'}
    for topic_tag, citizens in topic_citizens.items():
        if topic_tag in generic_topics and len(citizens) < 3:
            continue  # Skip broad topics unless 3+ agents agree
        if len(citizens) >= 2:
            existing = db.get_signal_alert_for_tag(topic_tag)
            if not existing:
                # Filter: check posts share specific context, not just a broad tag
                specific_posts = topic_posts[topic_tag]
                if len(specific_posts) >= 2:
                    # Sample check: first two posts must be semantically related
                    if not _posts_are_semantically_related(specific_posts[0], specific_posts[-1]):
                        log.debug(f"Skipping topic convergence on {topic_tag} — broad tag only")
                        continue
                log.info(f"TOPIC CONVERGENCE on {topic_tag} — {citizens}")
                create_signal_alert(topic_tag, topic_posts[topic_tag], list(citizens))

    # ── PASS 2: Latent pattern detection ─────────────────────────────────────
    # Look for cross-domain patterns no human would spot from the feed
    by_citizen = defaultdict(list)
    for post in recent:
        c = post.get('citizen')
        if c:
            by_citizen[c].append(post)

    for pattern in LATENT_PATTERNS:
        matched_agents = {}
        for agent in pattern['required_agents']:
            agent_posts = by_citizen.get(agent, [])
            if not agent_posts:
                continue
            # Check if any of this agent's posts match its required keywords
            agent_kw_sets = next(
                (kw_dict[agent] for kw_dict in pattern['required_keywords'] if agent in kw_dict),
                []
            )
            for post in agent_posts:
                body = (post.get('body', '') or '').lower()
                if any(kw in body for kw in agent_kw_sets):
                    matched_agents[agent] = post
                    break

        if len(matched_agents) >= pattern['min_agents']:
            tag      = f"#latent-{pattern['id']}"
            existing = db.get_signal_alert_for_tag(tag)
            if not existing:
                log.info(f"LATENT PATTERN: {pattern['label']} — {list(matched_agents.keys())}")
                all_posts = list(matched_agents.values())
                create_signal_alert(
                    tag, all_posts, list(matched_agents.keys()),
                    headline_override=f"⬡ LATENT PATTERN — {pattern['label']}: "
                                      f"{pattern['description']}"
                )

def create_signal_alert(tag, matching_posts, citizens=None, headline_override=None):
    if citizens is None:
        citizens = list({p['citizen'] for p in matching_posts})
    citizens = citizens[:4]

    # One entry per citizen only — prevents "4-way" showing 3x same agent in thread
    seen_in_thread = set()
    thread = []
    for p in matching_posts:
        c = p.get('citizen')
        if c and c not in seen_in_thread and c in citizens:
            seen_in_thread.add(c)
            body = (p.get('body', '') or '')
            thread.append({'citizen': c, 'text': body[:280]})
        if len(thread) >= len(citizens):
            break

    default_headline = f'SIGNAL ALERT — {len(citizens)}-WAY CONVERGENCE on {tag}'
    alert = {
        'type':      'signal_alert',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  citizens,
        'headline':  headline_override or default_headline,
        'body':      f'Multiple independent data streams independently converged on: {tag}.',
        'tags':      [tag, '#convergence'],
        'thread':    thread,
    }
    alert_id = db.save_post(alert)
    log.info(f"Signal Alert created: {tag} (id: {alert_id})")
    # Note: Council is NOT triggered here. Council only debates Town Halls,
    # which are higher-quality structured debates worth synthesising.
    # Signal Alerts go directly to ORACLE's fallback path if no council session exists.

def _posts_are_semantically_related(post_a, post_b) -> bool:
    """
    Check if two posts are genuinely about the same subject, not just sharing a broad tag.
    Uses entity overlap + keyword specificity — no Groq call, pure text analysis.
    """
    import re
    def extract_signals(post):
        body = (post.get('body', '') or '').lower()
        # Extract specific signals: tickers, named entities, numbers, acronyms
        tickers   = set(re.findall(r'\$([a-z]{2,5})\b', body))
        numbers   = set(re.findall(r'\b(\d+\.?\d*[%$bmk]?)\b', body))
        # Filter generic numbers (1,2,3) and keep specific ones (18.3%, $2.1B)
        specific_nums = {n for n in numbers if '%' in n or '$' in n or 'b' in n or 'm' in n}
        # Named entities: capitalised multi-word or all-caps 3+ letter
        entities  = set(re.findall(r'\b([a-z]{3,20}(?:\s[a-z]{3,20}){0,2})\b',
                                    (post.get('body', '') or '')))
        # Extract domain-specific terms (not generic stop words)
        stopwords = {'the','and','for','with','from','this','that','have','been',
                     'are','was','were','will','has','had','its','our','their',
                     'which','about','after','before','under','over','into',
                     'signal','alert','convergence','data','report','shows'}
        key_terms = {e for e in entities if e not in stopwords and len(e) > 5}
        return tickers | specific_nums | key_terms

    signals_a = extract_signals(post_a)
    signals_b = extract_signals(post_b)

    if not signals_a or not signals_b:
        return False

    overlap = signals_a & signals_b
    # Need at least 2 shared specific signals, or 1 ticker/entity match
    tickers_a = set(re.findall(r'\$([a-z]{2,5})\b', (post_a.get('body','') or '').lower()))
    tickers_b = set(re.findall(r'\$([a-z]{2,5})\b', (post_b.get('body','') or '').lower()))
    if tickers_a & tickers_b:  # Same ticker = definitely related
        return True
    if len(overlap) >= 2:      # 2+ shared specific terms = related
        return True

    # Check tag overlap beyond the trigger tag — if they share a specific sub-tag, related
    tags_a = set(t.lower() for t in (post_a.get('tags') or []))
    tags_b = set(t.lower() for t in (post_b.get('tags') or []))
    specific_tags = tags_a & tags_b - {'#convergence','#divergence','#ai','#regulation',
                                        '#finance','#government','#history','#media','#labor'}
    if specific_tags:
        return True

    return False


def create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag):
    """Generate a Town Hall debate post from two conflicting agent posts."""
    import uuid
    th = {
        'id':        str(uuid.uuid4()),
        'type':      'town_hall',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  [citizen_a, citizen_b],
        'topic':     f'Divergence detected on {topic_tag} — {citizen_a} vs {citizen_b}',
        'tags':      [topic_tag, '#divergence', '#townhall'],
        'positions': [
            {
                'citizen': citizen_a,
                'stance':  'Signals',
                'text':    (post_a.get('body', '') or '')[:300],
            },
            {
                'citizen': citizen_b,
                'stance':  'Counter',
                'text':    (post_b.get('body', '') or '')[:300],
            },
        ],
        'votes': {citizen_a: 0, citizen_b: 0, 'neutral': 0},
    }
    db.save_post(th)
    log.info(f"Town Hall created: {citizen_a} vs {citizen_b} on {topic_tag}")

    # Town Halls are the quality gate for Council.
    # A Town Hall means two structurally-opposed agents independently flagged
    # the same topic — that's worth a structured 3-voice debate before briefing.
    import threading, time as _t
    def _trigger_council_for_townhall():
        _t.sleep(10)  # Let DB settle
        try:
            sessions = COUNCIL.run_on_unprocessed(db)
            log.info(f"Council auto-triggered by Town Hall: {len(sessions)} session(s)")
        except Exception as e:
            log.error(f"Council auto-trigger (town hall) failed: {e}")
    threading.Thread(target=_trigger_council_for_townhall, daemon=True).start()

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
        # Semantic filter: verify posts are genuinely about the same subject
        if not _posts_are_semantically_related(post_a, post_b):
            log.debug(f"Skipping {citizen_a} vs {citizen_b} on {topic_tag} — not semantically related")
            continue
        log.info(f"DISAGREEMENT: {citizen_a} vs {citizen_b} on {topic_tag}")
        create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag)


# ─────────────────────────────────────────────────────
# CONDITION-TRIGGERED COUNCIL
# ─────────────────────────────────────────────────────
# Each condition maps: (description, keywords_in_body, threshold, subpoena_agents)
# When a single post body matches a condition, the Council is briefed directly
# rather than waiting for tag-overlap convergence between agents.
#
# This covers every agent territory — not just market signals.
# Philosophy: some signals are important enough to debate immediately,
# even if only one agent spotted them. The condition IS the trigger.

COUNCIL_CONDITIONS = [
    # ── MARKET / CAPITAL ──────────────────────────────
    {
        'id':          'vix_spike',
        'label':       'Equity Volatility Spike',
        'description': 'VIX crossed above a significant threshold — equity markets stressed.',
        'keywords':    ['vix', 'volatility index'],
        'value_check': lambda body: any(
            float(s) > 25 for s in __import__('re').findall(r'\b(\d+\.\d+)\b', body)
            if 15 < float(s) < 90
        ),
        'agents':      ['FLUX', 'DUKE', 'SPECTER'],
        'question':    'VIX has spiked above 25. Is this a temporary shock or the start of a structural repricing? What are the historical parallels?',
    },
    {
        'id':          'crypto_fear',
        'label':       'Extreme Crypto Fear',
        'description': 'Crypto Fear & Greed Index in Extreme Fear territory (below 25).',
        'keywords':    ['fear & greed', 'fear and greed', 'extreme fear'],
        'value_check': None,
        'agents':      ['FLUX', 'SPECTER', 'DUKE'],
        'question':    'Crypto sentiment is at Extreme Fear. Is this retail panic creating a buying opportunity, or is this a structural liquidity signal? What specifically triggered the fear — exchange failure, macro, or sentiment?',
    },
    {
        'id':          'yield_inversion',
        'label':       'Treasury Yield Inversion',
        'description': 'Treasury yield curve inverted — historically precedes recession.',
        'keywords':    ['yield spread', 'inverted', 'inversion', '10y2y', '2-year', '10-year'],
        'value_check': lambda body: any(
            float(s) < 0 for s in __import__('re').findall(r'(-\d+\.\d+)', body)
        ),
        'agents':      ['FLUX', 'REX', 'SPECTER'],
        'question':    'Yield curve inversion detected. Historical pattern: recession follows in 6-18 months. What sectors are most exposed? Has REX seen any Federal Register regulatory responses to credit conditions?',
    },
    # ── SUPPLY CHAIN / PHYSICAL ───────────────────────
    {
        'id':          'bdi_collapse',
        'label':       'Baltic Dry Collapse',
        'description': 'Significant BDI or commodity shipping decline — physical demand signal.',
        'keywords':    ['bdi', 'baltic dry', 'iron ore', 'shipping rate', 'freight'],
        'value_check': lambda body: any(
            float(s.replace('%','')) < -10 for s in __import__('re').findall(r'(-\d+(?:\.\d+)?%)', body)
        ),
        'agents':      ['VIGIL', 'DUKE', 'KAEL'],
        'question':    'Physical shipping/commodity data is collapsing. Does this contradict current capital market signals? Is mainstream media covering this, or is it a hidden signal?',
    },
    {
        'id':          'port_congestion',
        'label':       'Port Congestion Signal',
        'description': 'Port congestion or container rate spike — supply chain stress ahead.',
        'keywords':    ['port congestion', 'container rate', 'vessel wait', 'port delay', 'teu'],
        'value_check': None,
        'agents':      ['VIGIL', 'NOVA', 'FLUX'],
        'question':    'Port congestion signal detected. Historical pattern: consumer inflation follows in 6-8 weeks. What infrastructure permits correlate with this region?',
    },
    # ── REGULATORY / GOVERNMENT ───────────────────────
    {
        'id':          'major_regulation',
        'label':       'Major Regulatory Action',
        'description': 'Federal Register final rule, DOJ/FTC enforcement, or major court filing.',
        'keywords':    ['final rule', 'consent decree', 'enforcement action', 'antitrust', 'doj filed', 'ftc filed', 'court order'],
        'value_check': None,
        'agents':      ['REX', 'DUKE', 'LORE'],
        'question':    'A significant regulatory action has been filed. What companies are affected? Does DUKE see capital movement suggesting insider awareness? Does LORE see patent activity that motivated this regulation?',
    },
    {
        'id':          'government_contract',
        'label':       'Large Government Contract',
        'description': 'USASpending contract award above $100M — strategic government signal.',
        'keywords':    ['usaspending', 'contract award', 'task order', 'indefinite delivery'],
        'value_check': lambda body: any(
            float(s.replace(',','')) > 100_000_000
            for s in __import__('re').findall(r'\$([\d,]+(?:\.\d+)?)', body)
        ),
        'agents':      ['REX', 'DUKE', 'NOVA'],
        'question':    'A large government contract has been awarded. Who is the recipient? Does DUKE see related SEC filings? Does NOVA see infrastructure permits that suggest physical buildout?',
    },
    # ── SECURITY / BREACH ─────────────────────────────
    {
        'id':          'critical_breach',
        'label':       'Critical Security Breach',
        'description': 'Critical CVE or significant data breach involving sensitive entity.',
        'keywords':    ['critical', 'cve', 'breach', 'credential', 'ransomware', 'exploit'],
        'value_check': lambda body: 'critical' in body.lower() and any(
            kw in body.lower() for kw in ['government', 'bank', 'hospital', 'infrastructure', 'defense', 'military']
        ),
        'agents':      ['SPECTER', 'DUKE', 'REX'],
        'question':    'A critical security breach involving a sensitive entity has surfaced. What is the blast radius? Does DUKE see capital movement suggesting institutional awareness? What regulatory reporting requirements apply?',
    },
    # ── ACADEMIC / IP ─────────────────────────────────
    {
        'id':          'paradigm_paper',
        'label':       'Paradigm-Shifting Research',
        'description': 'Pre-print paper with potentially paradigm-shifting implications.',
        'keywords':    ['arxiv', 'preprint', 'biorxiv', 'unprecedented', 'breakthrough', 'first-ever', 'novel approach'],
        'value_check': None,
        'agents':      ['VERA', 'LORE', 'DUKE'],
        'question':    'A potentially paradigm-shifting paper has surfaced. Has it been peer-reviewed? Does LORE see patent activity suggesting this was already in commercial development? Has DUKE seen capital movement in the related sector?',
    },
    {
        'id':          'patent_cluster',
        'label':       'Patent Cluster Signal',
        'description': 'Multiple patent assignments to same entity — IP accumulation signal.',
        'keywords':    ['patent assignment', 'continuation', 'patent family', 'bayh-dole', 'wipo pct'],
        'value_check': None,
        'agents':      ['LORE', 'DUKE', 'REX'],
        'question':    'IP accumulation detected. Is this a defensive moat or preparation for an offensive patent campaign? What does the assignee\'s SEC activity look like in the same period?',
    },
    # ── NARRATIVE / MEDIA ─────────────────────────────
    {
        'id':          'coordinated_narrative',
        'label':       'Coordinated Media Narrative',
        'description': 'Multiple outlets publishing identical framing in a tight time window.',
        'keywords':    ['identical headline', 'same angle', 'coordinated', '22-minute', 'wire service', 'same owner'],
        'value_check': None,
        'agents':      ['KAEL', 'ECHO', 'SPECTER'],
        'question':    'Coordinated media narrative detected. Who owns the outlets running this story? Has ECHO seen any content quietly deleted that contradicts the narrative? What is the historical precedent for this kind of coordinated framing?',
    },
    # ── SOCIAL / SENTIMENT ────────────────────────────
    {
        'id':          'sentiment_reversal',
        'label':       'Rapid Sentiment Reversal',
        'description': 'Community sentiment reversed sharply — often precedes mainstream news.',
        'keywords':    ['sentiment reversal', 'spike in posts', '300%', '400%', '500%', 'suddenly',
                       'overnight', 'viral', 'community turned'],
        'value_check': None,
        'agents':      ['MIRA', 'KAEL', 'DUKE'],
        'question':    'Rapid community sentiment reversal detected. Is this organic or manufactured? Has mainstream media covered it yet? Does DUKE see capital positioning that suggests institutional awareness of the trigger?',
    },
]


def _extract_numeric_from_body(body: str):
    """Helper: extract all floats from a post body string."""
    import re
    return [float(x.replace(',','')) for x in re.findall(r'[\$]?([\d,]+(?:\.\d+)?)', body) if x]


def check_condition_triggers(post):
    """
    Check a single post against all COUNCIL_CONDITIONS.
    If a condition matches, auto-trigger a Council session with rich context.
    Returns the condition id if triggered, None otherwise.
    """
    if not post or post.get('type') != 'post':
        return None

    body    = (post.get('body', '') or '').lower()
    citizen = post.get('citizen', '')

    for cond in COUNCIL_CONDITIONS:
        # Check keyword match
        if not any(kw in body for kw in cond['keywords']):
            continue

        # Optional value threshold check
        if cond.get('value_check'):
            try:
                if not cond['value_check'](post.get('body', '') or ''):
                    continue
            except Exception:
                continue  # If value check fails, skip — don't block

        # Avoid re-triggering the same condition within 12 hours
        existing = db.get_council_session_for_condition(cond['id'])
        if existing:
            continue

        log.info(f"CONDITION TRIGGERED: {cond['label']} — by {citizen}")

        # Build a rich Council session directly from the condition
        # Enqueue at CRITICAL priority — goes to front of queue, bypasses backpressure
        def _condition_run(c=cond, p=post):
            import time as _t
            _t.sleep(5)  # Let DB settle
            try:
                session = _build_condition_council_session(c, p)
                if session:
                    session_id = db.save_council_session(session)
                    if session_id:
                        log.info(f"Condition Council session saved: {c['label']} ({session_id})")
            except Exception as e:
                log.error(f"Condition Council trigger failed ({c['id']}): {e}")

        QUEUE.enqueue_condition(
            agent_name=f"COUNCIL:{cond['id']}",
            run_fn=_condition_run,
            reason=f"condition:{cond['id']}",
        )
        return cond['id']

    return None


def _build_condition_council_session(cond, triggering_post):
    """
    Build a pre-seeded Council session for a condition trigger.
    Instead of generic AXIOM/DOUBT/LACUNA responses, the Council is
    seeded with domain-specific context about the exact condition.
    """
    import uuid
    from agents.token_budget import can_spend

    if not can_spend('council', 900):
        log.warning(f"Token budget insufficient for condition Council: {cond['label']}")
        return None

    # Use Groq to generate the actual debate with condition-aware prompts
    session = COUNCIL.debate({
        'id':       triggering_post.get('id', ''),
        'type':     'condition_trigger',
        'headline': f"[{cond['label']}] {cond['description']}",
        'topic':    cond['question'],
        'body':     (
            f"CONDITION: {cond['label']}\n"
            f"TRIGGERED BY: {triggering_post.get('citizen', '')}\n"
            f"POST: {triggering_post.get('body', '')[:400]}\n"
            f"QUESTION FOR COUNCIL: {cond['question']}"
        ),
        'tags':     triggering_post.get('tags', []) + [f"#condition-{cond['id']}"],
        'citizens': cond['agents'],
    })

    if session:
        session['condition_id'] = cond['id']

    return session



# ─────────────────────────────────────────────────────
# EMAIL DIGEST
# ─────────────────────────────────────────────────────
# Uses Python's built-in smtplib — no extra dependency.
# Configure via Render environment variables:
#   DIGEST_EMAIL_TO      — recipient address(es), comma-separated
#   DIGEST_EMAIL_FROM    — sender address  (e.g. digest@yourdomain.com)
#   SMTP_HOST            — e.g. smtp.gmail.com
#   SMTP_PORT            — e.g. 587
#   SMTP_USER            — SMTP username
#   SMTP_PASS            — SMTP password or app password
#
# Gmail quick setup:
#   SMTP_HOST=smtp.gmail.com  SMTP_PORT=587
#   SMTP_USER=you@gmail.com   SMTP_PASS=<16-char app password>
#   (Enable 2FA on Gmail → Security → App Passwords → generate one)

import smtplib, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

DIGEST_TO   = os.environ.get('DIGEST_EMAIL_TO',   '').strip()
DIGEST_FROM = os.environ.get('DIGEST_EMAIL_FROM', '').strip()
SMTP_HOST   = os.environ.get('SMTP_HOST',         'smtp.gmail.com')
SMTP_PORT   = int(os.environ.get('SMTP_PORT',     587))
SMTP_USER   = os.environ.get('SMTP_USER',         '').strip()
SMTP_PASS   = os.environ.get('SMTP_PASS',         '').strip()


def build_digest_html(briefs, stats, convergences):
    """Build a clean HTML email from today's Oracle briefs."""
    today = datetime.utcnow().strftime('%A, %d %B %Y')

    brief_blocks = ''
    for b in briefs[:5]:
        conf_color = {'HIGH':'#0BAF72','MEDIUM':'#CA8A04','LOW':'#888','CONFIRMED':'#6366F1'}.get(
            b.get('confidence','LOW'), '#888')
        evidence = ''.join(
            f'<li style="margin-bottom:4px;color:#555;font-size:13px;">{e}</li>'
            for e in (b.get('evidence') or [])[:3]
        )
        actions = ''.join(
            f'<span style="display:inline-block;background:#f3f4f6;color:#374151;font-size:11px;padding:3px 8px;border-radius:12px;margin:2px;">{a}</span>'
            for a in (b.get('action_items') or [])[:2]
        )
        brief_blocks += f"""
        <div style="border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-bottom:16px;border-left:4px solid {conf_color};">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
            <span style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
              color:{conf_color};background:{conf_color}18;padding:2px 8px;border-radius:10px;">
              {b.get('confidence','?')}
            </span>
            <span style="font-size:10px;color:#9ca3af;">{', '.join(b.get('citizens') or [])}</span>
          </div>
          <div style="font-family:Georgia,serif;font-size:17px;font-weight:600;color:#111;margin-bottom:8px;line-height:1.4;">
            {b.get('headline','')}
          </div>
          <div style="font-size:14px;color:#374151;line-height:1.7;margin-bottom:12px;">
            {b.get('verdict','')}
          </div>
          {"<ul style='padding-left:18px;margin:0 0 12px;'>" + evidence + "</ul>" if evidence else ""}
          {f'<div style="font-style:italic;font-size:13px;color:#6b7280;margin-bottom:12px;">{b.get("implications","")}</div>' if b.get("implications") else ""}
          {f'<div>{actions}</div>' if actions else ""}
        </div>"""

    conv_rows = ''
    for c in (convergences or [])[:3]:
        bar_w = min(100, c.get('probability', 0))
        conv_rows += f"""
        <tr>
          <td style="padding:6px 0;font-size:13px;color:#374151;">{c.get('tag','')}</td>
          <td style="padding:6px 8px;font-size:12px;color:#6b7280;">{', '.join(c.get('citizens',[]))}</td>
          <td style="padding:6px 0;width:80px;">
            <div style="background:#f3f4f6;border-radius:4px;height:6px;">
              <div style="background:{'#0BAF72' if c.get('confirmed') else '#6366F1'};width:{bar_w}%;height:100%;border-radius:4px;"></div>
            </div>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:600px;margin:0 auto;padding:24px 16px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#0f172a,#1e293b);border-radius:16px;padding:28px;margin-bottom:20px;text-align:center;">
      <div style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-.5px;">
        The <span style="color:#60a5fa;">Signal</span> Society
      </div>
      <div style="font-size:12px;color:#94a3b8;margin-top:4px;letter-spacing:.08em;text-transform:uppercase;">
        Intelligence Digest · {today}
      </div>
    </div>

    <!-- Stats row -->
    <div style="display:flex;gap:10px;margin-bottom:20px;">
      {"".join(f'<div style="flex:1;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px;text-align:center;"><div style="font-size:20px;font-weight:700;color:#111;">{v}</div><div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.06em;margin-top:2px;">{l}</div></div>'
        for l, v in [
          ("Dispatches", stats.get("posts_published",0)),
          ("Alerts",     stats.get("signal_alerts",0)),
          ("Town Halls", stats.get("town_halls",0)),
          ("Briefs",     stats.get("briefs",0)),
        ]
      )}
    </div>

    <!-- Briefs -->
    <div style="font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#6b7280;margin-bottom:12px;">
      Oracle Intelligence Briefs
    </div>
    {brief_blocks if brief_blocks else '<div style="color:#9ca3af;font-style:italic;padding:20px 0;">No briefs generated yet today.</div>'}

    <!-- Convergence monitor -->
    {f'''<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin-top:16px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#6b7280;margin-bottom:12px;">Active Convergences</div>
      <table style="width:100%;border-collapse:collapse;">{conv_rows}</table>
    </div>''' if conv_rows else ""}

    <!-- Footer -->
    <div style="text-align:center;margin-top:24px;font-size:11px;color:#9ca3af;">
      Generated by The Signal Society · 12 autonomous agents · Powered by Llama 3.3
    </div>
  </div>
</body></html>"""


def send_digest():
    """Fetch today's data and send the email digest."""
    if not all([DIGEST_TO, DIGEST_FROM, SMTP_USER, SMTP_PASS]):
        log.info("Email digest skipped — SMTP not configured (set DIGEST_EMAIL_TO, SMTP_USER, SMTP_PASS)")
        return False
    try:
        briefs       = db.get_briefs(limit=5)
        stats        = db.get_weekly_stats()
        convergences = db.get_convergence_status()

        html_body = build_digest_html(briefs, stats, convergences)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Signal Society Digest · {datetime.utcnow().strftime('%d %b %Y')}"
        msg['From']    = DIGEST_FROM
        msg['To']      = DIGEST_TO

        # Plain text fallback
        plain = f"""The Signal Society — Daily Digest\n\n"""
        plain += f"Stats: {stats.get('posts_published',0)} dispatches, {stats.get('signal_alerts',0)} alerts, {stats.get('briefs',0)} briefs\n\n"
        for b in briefs[:3]:
            plain += f"[{b.get('confidence','?')}] {b.get('headline','')}\n{b.get('verdict','')}\n\n"

        msg.attach(MIMEText(plain, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            recipients = [r.strip() for r in DIGEST_TO.split(',') if r.strip()]
            server.sendmail(DIGEST_FROM, recipients, msg.as_string())

        log.info(f"Digest sent to {DIGEST_TO}")
        return True
    except Exception as e:
        log.error(f"Digest send failed: {e}")
        return False


@app.route('/api/digest/send', methods=['GET', 'POST'])
def trigger_digest():
    """Manually trigger the email digest."""
    import threading
    threading.Thread(target=send_digest, daemon=True).start()
    configured = all([DIGEST_TO, SMTP_USER, SMTP_PASS])
    return jsonify({'status': 'started', 'configured': configured,
                    'recipient': DIGEST_TO if configured else 'not set'})


# ── AGENT SCHEDULE ────────────────────────────────────────────────────────────
# Each agent has an interval (hours) and a base priority.
# Agents with pending subpoenas are automatically upgraded to NORMAL.
# Council/Oracle are HIGH. Condition triggers are CRITICAL.
AGENT_SCHEDULE = [
    # (name,     interval_hours, priority)
    ('MIRA',     1,   LOW),    # Sentiment moves fast — check hourly
    ('KAEL',     1,   LOW),    # News metadata is time-sensitive
    ('DUKE',     2,   LOW),    # SEC filings, job boards
    ('VERA',     2,   LOW),    # arXiv pre-prints
    ('FLUX',     2,   LOW),    # Capital flows, yields
    ('ECHO',     2,   LOW),    # Deletions, retractions
    ('REX',      2,   LOW),    # Federal Register, courts
    ('SOL',      3,   LOW),    # Cross-domain correlations
    ('SPECTER',  3,   LOW),    # Breaches, historical patterns
    ('VIGIL',    4,   LOW),    # Physical flows — slower signals
    ('NOVA',     6,   LOW),    # Infrastructure permits — slow but impactful
    ('LORE',     6,   LOW),    # Patents — very slow signals
]


def setup_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    # Instantiate QUEUE here — run_agent is now defined
    global QUEUE
    QUEUE = AgentQueue(run_agent, COUNCIL, ORACLE, db)
    QUEUE.start()

    scheduler = BackgroundScheduler()

    # Schedule each agent to enqueue itself at its interval
    # The queue handles budget, backpressure, jitter, and deduplication
    for agent_name, interval_hours, base_priority in AGENT_SCHEDULE:
        def _enqueue(name=agent_name, pri=base_priority):
            # Upgrade priority if agent has pending Council subpoenas
            has_sub = False
            try:
                has_sub = bool(db.get_pending_subpoenas_for_agent(name))
            except Exception:
                pass
            actual_priority = NORMAL if has_sub else pri
            QUEUE.enqueue(name, priority=actual_priority, reason='scheduled')

        scheduler.add_job(
            _enqueue, 'interval', hours=interval_hours,
            id=agent_name.lower(),
            jitter=300,   # APScheduler-level jitter: ±5 minutes on top of queue jitter
        )

    # Council and Oracle enqueue themselves at HIGH priority
    scheduler.add_job(
        lambda: QUEUE.enqueue('COUNCIL', priority=HIGH, reason='scheduled',
                              run_fn=lambda: COUNCIL.run_on_unprocessed(db)),
        'interval', hours=4, id='council', jitter=120,
    )
    scheduler.add_job(
        lambda: QUEUE.enqueue('ORACLE', priority=HIGH, reason='scheduled',
                              run_fn=lambda: ORACLE.run_on_unprocessed(db)),
        'interval', hours=6, id='oracle', jitter=120,
    )

    # HERMES — executes Oracle action items on HIGH/CONFIRMED briefs
    scheduler.add_job(
        lambda: HERMES.run_on_unprocessed_briefs(db),
        'interval', hours=6, id='hermes',
    )
    # Daily digest at 07:00 UTC
    scheduler.add_job(send_digest, 'cron', hour=7, minute=0, id='digest')

    # ── SELF-PING: keeps Render free tier awake ──────────────
    # Render spins down after 15min inactivity. This pings own /api/health
    # every 10 minutes so APScheduler keeps running and agents keep firing.
    import os as _os
    _self_url = _os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')
    if not _self_url:
        _self_url = 'https://ai-signal-community.onrender.com'

    def _self_ping():
        try:
            import requests as _r
            _r.get(f'{_self_url}/api/health', timeout=10)
            log.debug("Self-ping OK")
        except Exception as e:
            log.debug(f"Self-ping failed: {e}")

    scheduler.add_job(_self_ping, 'interval', minutes=10, id='self_ping')
    log.info(f"Self-ping registered → {_self_url}/api/health every 10 minutes")

    scheduler.start()
    log.info(
        f"Scheduler + AgentQueue started — {len(AGENT_SCHEDULE)} agents, "
        f"COUNCIL, ORACLE. Priority: CRITICAL>HIGH>NORMAL>LOW. "
        f"Budget backpressure active."
    )
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

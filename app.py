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
from agents.vera  import VeraAgent
from agents.duke  import DukeAgent
from agents.mira  import MiraAgent
from agents.sol   import SolAgent
from agents.nova  import NovaAgent
from agents.echo  import EchoAgent
from agents.kael  import KaelAgent
from agents.flux  import FluxAgent
from agents.rex   import RexAgent
from agents.oracle import OracleAgent

# ─────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
log = logging.getLogger('signal-society')

AGENTS = {
    'VERA': VeraAgent(),
    'DUKE': DukeAgent(),
    'MIRA': MiraAgent(),
    'SOL':  SolAgent(),
    'NOVA': NovaAgent(),
    'ECHO': EchoAgent(),
    'KAEL': KaelAgent(),
    'FLUX': FluxAgent(),
    'REX':  RexAgent(),
}
ORACLE = OracleAgent()

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

@app.route('/api/oracle/run', methods=['GET', 'POST'])
def trigger_oracle():
    """Manually trigger ORACLE to process all unprocessed posts."""
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
            saved  = 0
            for post in result:
                db.save_post(post)
                saved += 1
            log.info(f"Trigger {name}: {saved} posts saved")
            check_convergence()
            check_for_disagreement()
        except Exception as e:
            log.error(f"Trigger {name} failed: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'agent': name}), 200


# ─────────────────────────────────────
# SCHEDULER — AGENT RUNS
# ─────────────────────────────────────
def run_agent(name):
    log.info(f"Scheduled run: {name}")
    try:
        posts = AGENTS[name].run()
        for post in posts:
            db.save_post(post)
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
}

DIVERGENT_PAIRS = [
    ('VERA', 'DUKE'),
    ('VERA', 'KAEL'),
    ('MIRA', 'DUKE'),
    ('SOL',  'KAEL'),
    ('ECHO', 'DUKE'),
    ('NOVA', 'MIRA'),
    ('FLUX', 'REX'),
    ('FLUX', 'DUKE'),
    ('REX',  'VERA'),
    ('REX',  'KAEL'),
]

def _post_topics(post):
    body     = (post.get('body', '') or '').lower()
    tags     = ' '.join(t.lower() for t in post.get('tags', []))
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
    alert = {
        'id':        str(__import__('uuid').uuid4()),
        'type':      'signal_alert',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  citizens,
        'headline':  f'SIGNAL ALERT — {len(citizens)}-WAY CONVERGENCE on {tag}',
        'body':      f'Multiple independent data streams converged on: {tag}. Cross-referencing now.',
        'tags':      [tag, '#convergence'],
        'thread':    [{'citizen': p['citizen'], 'text': (p.get('body','') or '')[:200] + '...'} for p in matching_posts[:4]],
    }
    db.save_post(alert)
    log.info(f"Signal Alert created: {tag}")
    # ORACLE synthesis is handled by the scheduled 2-hour sweep to avoid rate limits

def create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag):
    """Generate a Town Hall debate post from two conflicting agent posts."""
    th = {
        'id':        str(__import__('uuid').uuid4()),
        'type':      'town_hall',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  [citizen_a, citizen_b],
        'topic':     f'Divergence detected on {topic_tag} — {citizen_a} vs {citizen_b}',
        'tags':      [topic_tag, '#divergence', '#townhall'],
        'positions': [
            {
                'citizen': citizen_a,
                'stance':  'Signals',
                'text':    (post_a.get('body','') or '')[:280],
            },
            {
                'citizen': citizen_b,
                'stance':  'Counter',
                'text':    (post_b.get('body','') or '')[:280],
            },
        ],
        'votes': {citizen_a: 0, citizen_b: 0, 'neutral': 0},
    }
    db.save_post(th)
    log.info(f"Town Hall created: {citizen_a} vs {citizen_b} on {topic_tag}")

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
    scheduler.add_job(lambda: run_agent('VERA'), 'interval', minutes=60,  id='vera')
    scheduler.add_job(lambda: run_agent('DUKE'), 'interval', minutes=45,  id='duke')
    scheduler.add_job(lambda: run_agent('MIRA'), 'interval', minutes=30,  id='mira')
    scheduler.add_job(lambda: run_agent('SOL'),  'interval', minutes=90,  id='sol')
    scheduler.add_job(lambda: run_agent('NOVA'), 'interval', hours=3,     id='nova')
    scheduler.add_job(lambda: run_agent('ECHO'), 'interval', minutes=40,  id='echo')
    scheduler.add_job(lambda: run_agent('KAEL'), 'interval', minutes=20,  id='kael')
    scheduler.add_job(lambda: run_agent('FLUX'), 'interval', minutes=35,  id='flux')
    scheduler.add_job(lambda: run_agent('REX'),  'interval', minutes=50,  id='rex')
    scheduler.add_job(lambda: ORACLE.run_on_unprocessed(db), 'interval', hours=2, id='oracle')
    scheduler.start()
    log.info("Scheduler started — 9 agents + ORACLE active")
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

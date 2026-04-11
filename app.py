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

from database import db
from agents.vera  import VeraAgent
from agents.duke  import DukeAgent
from agents.mira  import MiraAgent
from agents.sol   import SolAgent
from agents.nova  import NovaAgent
from agents.echo  import EchoAgent
from agents.kael  import KaelAgent

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
}

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

# FIX: route param was <n> but function arg was 'name' — Flask TypeError on every request
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
@app.route('/api/trigger/<agent_name>', methods=['POST'])
def trigger_agent(agent_name):
    """Manually fire an agent. POST /api/trigger/vera"""
    name = agent_name.upper()
    if name not in AGENTS:
        return jsonify({'error': 'Unknown agent'}), 404
    try:
        result = AGENTS[name].run()
        for post in result:
            db.save_post(post)
        db.log_agent_run(name, len(result))
        return jsonify({'status': 'ok', 'posts_created': len(result)})
    except Exception as e:
        log.error(f"Agent {name} failed: {e}")
        db.log_agent_run(name, 0, str(e))
        return jsonify({'error': str(e)}), 500

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
    except Exception as e:
        log.error(f"{name} agent error: {e}")
        db.log_agent_run(name, 0, str(e))

def check_convergence():
    """Fire a Signal Alert when 3+ agents independently flag the same tag."""
    recent = db.get_recent_mentions(hours=6)
    from collections import Counter
    tag_counts = Counter()
    for post in recent:
        tags = post.get('tags', [])
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = []
        for tag in tags:
            tag_counts[tag] += 1

    for tag, count in tag_counts.items():
        if count >= 3:
            existing = db.get_signal_alert_for_tag(tag)
            if not existing:
                log.info(f"CONVERGENCE on tag: {tag} ({count} agents)")
                create_signal_alert(tag, recent)

def create_signal_alert(tag, recent_posts):
    matching = [p for p in recent_posts if tag in p.get('tags', [])]
    citizens = list({p['citizen'] for p in matching})[:3]

    alert = {
        'type':      'signal_alert',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  citizens,
        'headline':  f'SIGNAL ALERT — {len(citizens)}-WAY CONVERGENCE',
        'body':      f'Multiple independent data streams converged on: {tag}. Cross-referencing now.',
        'tags':      [tag, '#convergence'],
        'thread':    [{'citizen': p['citizen'], 'text': p['body'][:200] + '...'} for p in matching],
    }
    db.save_post(alert)
    log.info(f"Signal Alert created: {tag}")

def setup_scheduler():
    scheduler = BackgroundScheduler()
    # Week 1: VERA + DUKE. Uncomment others as you progress.
    scheduler.add_job(lambda: run_agent('VERA'), 'interval', minutes=60,  id='vera')
    scheduler.add_job(lambda: run_agent('DUKE'), 'interval', minutes=45,  id='duke')
    # scheduler.add_job(lambda: run_agent('MIRA'), 'interval', minutes=30,  id='mira')
    # scheduler.add_job(lambda: run_agent('SOL'),  'interval', minutes=90,  id='sol')
    # scheduler.add_job(lambda: run_agent('NOVA'), 'interval', hours=3,     id='nova')
    # scheduler.add_job(lambda: run_agent('ECHO'), 'interval', minutes=20,  id='echo')
    # scheduler.add_job(lambda: run_agent('KAEL'), 'interval', minutes=15,  id='kael')
    scheduler.start()
    log.info("Scheduler started")
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

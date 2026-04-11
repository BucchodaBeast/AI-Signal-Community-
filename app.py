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

from anthropic import Anthropic
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

client = Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))

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

    # Special trigger: force disagreement check
    if name == 'TOWNHALL':
        try:
            check_for_disagreement()
            return jsonify({'status': 'ok', 'message': 'Disagreement check complete'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if name not in AGENTS:
        return jsonify({'error': 'Unknown agent'}), 404
    try:
        recent_context = db.get_recent_mentions(hours=6)
        result = AGENTS[name].run(recent_context=recent_context)
        for post in result:
            db.save_post(post)
        check_convergence()
        check_for_disagreement()
        return jsonify({'status': 'ok', 'posts_created': len(result)})
    except Exception as e:
        log.error(f"Agent {name} failed: {e}")
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────
# SCHEDULER — AGENT RUNS
# ─────────────────────────────────────
def run_agent(name):
    log.info(f"Scheduled run: {name}")
    try:
        # Inject recent colleague posts so agents can make real cross-references
        recent_context = db.get_recent_mentions(hours=6)
        posts = AGENTS[name].run(recent_context=recent_context)
        for post in posts:
            db.save_post(post)
        log.info(f"{name} produced {len(posts)} post(s)")
        db.log_agent_run(name, len(posts))
        check_convergence()
        check_for_disagreement()
    except Exception as e:
        log.error(f"{name} agent error: {e}")
        db.log_agent_run(name, 0, str(e))


# ─────────────────────────────────────
# CONVERGENCE — Signal Alert
# ─────────────────────────────────────
def check_convergence():
    """Fire a Signal Alert when 3+ agents independently flag the same tag."""
    recent = db.get_recent_mentions(hours=6)
    from collections import Counter
    tag_counts = Counter()
    for post in recent:
        for tag in post.get('tags', []):
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


# ─────────────────────────────────────
# DISAGREEMENT — Town Hall
# ─────────────────────────────────────

# Pairs whose worldviews are structurally opposed — disagreement between these
# citizens is architecturally load-bearing, not coincidental.
DIVERGENT_PAIRS = [
    ('VERA', 'DUKE'),   # academic rigour vs capital movement
    ('VERA', 'KAEL'),   # cites evidence vs audits narrative
    ('MIRA', 'DUKE'),   # sentiment vs capital
    ('SOL',  'KAEL'),   # cross-domain pattern vs media structure
    ('ECHO', 'DUKE'),   # what was deleted vs what the money says
    ('NOVA', 'MIRA'),   # physical infrastructure vs community sentiment
]

def check_for_disagreement():
    """
    Detect when two structurally-opposed citizens have recently posted about
    the same entity/topic and generate a Town Hall if the framing diverges.
    Only fires once per topic per 24h window.
    """
    recent = db.get_recent_mentions(hours=12)
    if len(recent) < 2:
        return

    # Index posts by citizen
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

        # Find overlapping tags between the two citizens' recent posts
        tags_a = {t for p in posts_a for t in p.get('tags', [])}
        tags_b = {t for p in posts_b for t in p.get('tags', [])}
        shared = tags_a & tags_b - {'#convergence'}  # exclude meta-tags
        if not shared:
            continue

        topic_tag = sorted(shared)[0]

        # Don't fire a Town Hall for this pairing + tag if one exists in last 24h
        if db.get_town_hall_for_pair(citizen_a, citizen_b, topic_tag):
            continue

        # Find the most relevant post from each citizen on this topic
        post_a = next((p for p in posts_a if topic_tag in p.get('tags', [])), posts_a[0])
        post_b = next((p for p in posts_b if topic_tag in p.get('tags', [])), posts_b[0])

        log.info(f"DISAGREEMENT detected: {citizen_a} vs {citizen_b} on {topic_tag}")
        create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag)

def create_town_hall(name_a, post_a, name_b, post_b, topic_tag):
    """
    Use Claude to synthesise a genuine Town Hall from two diverging posts.
    Claude extracts the actual topic, frames each position, and writes
    a neutral debate prompt.
    """
    prompt = f"""Two AI citizens of The Signal Society have posted about the same topic from 
completely different angles. Generate a Town Hall debate entry.

CITIZEN {name_a} posted:
{post_a.get('body', '')}

CITIZEN {name_b} posted:
{post_b.get('body', '')}

Shared topic tag: {topic_tag}

Produce a JSON object with this exact structure:
{{
  "topic": "A single sharp question that captures the genuine tension between these two posts (15 words max, no hedging)",
  "position_a": {{
    "citizen": "{name_a}",
    "stance": "one word that captures their angle (e.g. Skeptical, Bullish, Structural, Irrelevant)",
    "text": "2-3 sentences in {name_a}'s voice summarising their position on this topic"
  }},
  "position_b": {{
    "citizen": "{name_b}",
    "stance": "one word that captures their angle",
    "text": "2-3 sentences in {name_b}'s voice summarising their position on this topic"
  }},
  "tags": ["{topic_tag}", "#townhall"]
}}

The topic question must be genuinely contested — not rhetorical.
Do not include any text outside the JSON object.
"""
    try:
        resp = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=600,
            messages=[{'role': 'user', 'content': prompt}]
        )
        text = resp.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        data = json.loads(text)

        town_hall = {
            'type':      'town_hall',
            'timestamp': datetime.utcnow().isoformat(),
            'topic':     data.get('topic', f'Debate: {topic_tag}'),
            'positions': [data.get('position_a', {}), data.get('position_b', {})],
            'votes':     {name_a: 0, name_b: 0, 'neutral': 0},
            'tags':      data.get('tags', [topic_tag, '#townhall']),
            'citizens':  [name_a, name_b],
        }
        db.save_post(town_hall)
        log.info(f"Town Hall created: {name_a} vs {name_b} on {topic_tag}")
    except Exception as e:
        log.error(f"Town Hall generation failed ({name_a} vs {name_b}): {e}")

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

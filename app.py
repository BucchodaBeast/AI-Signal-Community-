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
    """Fire an agent in a daemon thread — returns immediately so cron-job.org
    never hits 'output too large'. All work runs in the background."""
    name = agent_name.upper()

    if name == 'TOWNHALL':
        import threading
        threading.Thread(target=check_for_disagreement, daemon=True).start()
        return jsonify({'ok': True, 'agent': 'TOWNHALL'}), 200

    if name not in AGENTS:
        return jsonify({'error': 'Unknown agent'}), 404

    import threading
    def _run():
        try:
            recent_context = db.get_recent_mentions(hours=6)
            result = AGENTS[name].run(recent_context=recent_context)
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

def check_convergence():
    """Fire a Signal Alert when 2+ agents independently mention the same topic keyword."""
    recent = db.get_recent_mentions(hours=6)
    if len(recent) < 2:
        return

    # Keyword clusters — if agents hit 2+ words from the same cluster, it's convergence
    TOPIC_CLUSTERS = {
        '#AI':             ['ai', 'llm', 'gpt', 'openai', 'anthropic', 'gemini', 'model', 'neural', 'deepmind', 'artificial intelligence'],
        '#regulation':     ['regulation', 'regulatory', 'sec', 'fcc', 'fda', 'congress', 'legislation', 'policy', 'antitrust', 'compliance'],
        '#crypto':         ['crypto', 'bitcoin', 'ethereum', 'blockchain', 'defi', 'nft', 'stablecoin', 'web3'],
        '#infrastructure': ['infrastructure', 'datacenter', 'data center', 'spectrum', 'fiber', 'permit', 'zoning', 'faa', 'fcc', 'grid'],
        '#biotech':        ['biotech', 'pharma', 'drug', 'fda', 'clinical', 'genome', 'crispr', 'vaccine', 'pandemic'],
        '#labor':          ['layoffs', 'hiring', 'jobs', 'workforce', 'strike', 'union', 'remote', 'return to office'],
        '#climate':        ['climate', 'carbon', 'emissions', 'renewable', 'solar', 'wind', 'fossil', 'epa', 'noaa'],
        '#media':          ['media', 'journalism', 'censorship', 'misinformation', 'propaganda', 'narrative', 'publishing'],
        '#finance':        ['market', 'stocks', 'ipo', 'funding', 'acquisition', 'merger', 'valuation', 'capital'],
    }

    from collections import defaultdict
    # Map each post to matched topic tags
    post_topics = {}
    for post in recent:
        body   = (post.get('body', '') or '').lower()
        tags   = [t.lower() for t in post.get('tags', [])]
        combined = body + ' ' + ' '.join(tags)
        matched = []
        for topic_tag, keywords in TOPIC_CLUSTERS.items():
            if any(kw in combined for kw in keywords):
                matched.append(topic_tag)
        if matched:
            post_topics[post['id']] = {'post': post, 'topics': matched}

    # Count how many DIFFERENT citizens hit each topic
    topic_citizens = defaultdict(set)
    topic_posts    = defaultdict(list)
    for pid, info in post_topics.items():
        citizen = info['post'].get('citizen')
        if not citizen:
            continue
        for topic in info['topics']:
            topic_citizens[topic].add(citizen)
            topic_posts[topic].append(info['post'])

    for topic_tag, citizens in topic_citizens.items():
        if len(citizens) >= 2:
            existing = db.get_signal_alert_for_tag(topic_tag)
            if not existing:
                log.info(f"CONVERGENCE on {topic_tag} — {len(citizens)} citizens: {citizens}")
                create_signal_alert(topic_tag, topic_posts[topic_tag], list(citizens))

def create_signal_alert(tag, matching_posts, citizens=None):
    if citizens is None:
        citizens = list({p['citizen'] for p in matching_posts})[:3]
    citizens = citizens[:3]
    alert = {
        'type':      'signal_alert',
        'timestamp': datetime.utcnow().isoformat(),
        'citizens':  citizens,
        'headline':  f'SIGNAL ALERT — {len(citizens)}-WAY CONVERGENCE on {tag}',
        'body':      f'Multiple independent data streams converged on: {tag}. Cross-referencing now.',
        'tags':      [tag, '#convergence'],
        'thread':    [{'citizen': p['citizen'], 'text': (p.get('body', '') or '')[:200] + '...'} for p in matching_posts[:3]],
    }
    db.save_post(alert)
    log.info(f"Signal Alert created: {tag}")

# ─────────────────────────────────────
# DISAGREEMENT — Town Hall
# ─────────────────────────────────────
DIVERGENT_PAIRS = [
    ('VERA', 'DUKE'),   # academic rigour vs capital movement
    ('VERA', 'KAEL'),   # cites evidence vs audits narrative
    ('MIRA', 'DUKE'),   # sentiment vs capital
    ('SOL',  'KAEL'),   # cross-domain pattern vs media structure
    ('ECHO', 'DUKE'),   # what was deleted vs what the money says
    ('NOVA', 'MIRA'),   # physical infrastructure vs community sentiment
]

def check_for_disagreement():
    recent = db.get_recent_mentions(hours=12)
    if len(recent) < 2:
        return

    TOPIC_KEYWORDS = {
        '#AI':             ['ai', 'llm', 'gpt', 'openai', 'anthropic', 'model', 'neural', 'machine learning'],
        '#regulation':     ['regulation', 'regulatory', 'sec', 'fcc', 'congress', 'legislation', 'policy', 'antitrust'],
        '#crypto':         ['crypto', 'bitcoin', 'ethereum', 'blockchain', 'defi', 'web3'],
        '#infrastructure': ['infrastructure', 'datacenter', 'spectrum', 'fiber', 'permit', 'grid'],
        '#biotech':        ['biotech', 'pharma', 'drug', 'fda', 'clinical', 'genome'],
        '#labor':          ['layoffs', 'hiring', 'jobs', 'workforce', 'strike', 'union'],
        '#finance':        ['market', 'stocks', 'ipo', 'funding', 'acquisition', 'merger', 'capital'],
        '#media':          ['media', 'journalism', 'censorship', 'narrative', 'publishing'],
        '#climate':        ['climate', 'carbon', 'emissions', 'renewable', 'noaa'],
    }

    def post_topics(post):
        body     = (post.get('body', '') or '').lower()
        tags     = [t.lower() for t in post.get('tags', [])]
        combined = body + ' ' + ' '.join(tags)
        return {tag for tag, kws in TOPIC_KEYWORDS.items() if any(kw in combined for kw in kws)}

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

        topics_a = {t for p in posts_a for t in post_topics(p)}
        topics_b = {t for p in posts_b for t in post_topics(p)}
        shared   = topics_a & topics_b - {'#convergence', '#SignalSociety'}
        if not shared:
            continue

        topic_tag = sorted(shared)[0]
        if db.get_town_hall_for_pair(citizen_a, citizen_b, topic_tag):
            continue

        # Pick the most relevant post from each citizen for this topic
        def best_post(posts, tag):
            kws = TOPIC_KEYWORDS.get(tag, [])
            for p in posts:
                body = (p.get('body', '') or '').lower()
                if any(kw in body for kw in kws):
                    return p
            return posts[0]

        post_a = best_post(posts_a, topic_tag)
        post_b = best_post(posts_b, topic_tag)

        log.info(f"DISAGREEMENT detected: {citizen_a} vs {citizen_b} on {topic_tag}")
        create_town_hall(citizen_a, post_a, citizen_b, post_b, topic_tag)

def create_town_hall(name_a, post_a, name_b, post_b, topic_tag):
    import requests as req
    groq_key = os.environ.get('GROQ_API_KEY', '')
    prompt = f"""Two AI citizens of The Signal Society posted about the same topic from different angles.

CITIZEN {name_a} posted:
{post_a.get('body', '')}

CITIZEN {name_b} posted:
{post_b.get('body', '')}

Shared topic tag: {topic_tag}

Produce a JSON object:
{{
  "topic": "A single sharp question capturing the tension (15 words max)",
  "position_a": {{
    "citizen": "{name_a}",
    "stance": "one word angle (e.g. Skeptical, Bullish, Structural)",
    "text": "2-3 sentences in {name_a}'s voice on this topic"
  }},
  "position_b": {{
    "citizen": "{name_b}",
    "stance": "one word angle",
    "text": "2-3 sentences in {name_b}'s voice on this topic"
  }},
  "tags": ["{topic_tag}", "#townhall"]
}}

The topic question must be genuinely contested. No text outside the JSON."""

    try:
        resp = req.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.7,
                'max_tokens': 600,
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()['choices'][0]['message']['content'].strip()
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
    scheduler.add_job(lambda: run_agent('VERA'), 'interval', minutes=60,  id='vera')
    scheduler.add_job(lambda: run_agent('DUKE'), 'interval', minutes=45,  id='duke')
    scheduler.add_job(lambda: run_agent('MIRA'), 'interval', minutes=30,  id='mira')
    scheduler.add_job(lambda: run_agent('SOL'),  'interval', minutes=90,  id='sol')
    scheduler.add_job(lambda: run_agent('NOVA'), 'interval', hours=3,     id='nova')
    scheduler.add_job(lambda: run_agent('ECHO'), 'interval', minutes=40,  id='echo')
    scheduler.add_job(lambda: run_agent('KAEL'), 'interval', minutes=20,  id='kael')
    scheduler.start()
    log.info("Scheduler started — all 7 agents active")
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

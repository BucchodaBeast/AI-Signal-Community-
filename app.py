"""
app.py — The Signal Society Backend (Fixed Scheduler)
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

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/feed', methods=['GET'])
def get_feed():
    limit   = int(request.args.get('limit', 20))
    offset  = int(request.args.get('offset', 0))
    ftype   = request.args.get('type')
    citizen = request.args.get('citizen')
    posts = db.get_posts(limit=limit, offset=offset, post_type=ftype, citizen=citizen)
    return jsonify({'posts': posts, 'total': db.count_posts(ftype, citizen)})

@app.route('/api/briefs', methods=['GET'])
def get_briefs():
    limit      = int(request.args.get('limit', 20))
    tier       = request.args.get('tier')
    confidence = request.args.get('confidence')
    briefs = db.get_briefs(limit=limit, tier=tier, confidence=confidence)
    return jsonify({'briefs': briefs})

@app.route('/api/council', methods=['GET'])
def get_council_sessions():
    limit = int(request.args.get('limit', 20))
    sessions = db.get_council_sessions(limit=limit)
    return jsonify({'sessions': sessions})

@app.route('/api/oracle/run', methods=['GET', 'POST'])
def trigger_oracle():
    import threading
    def _run():
        try:
            briefs = ORACLE.run_on_unprocessed(db)
            log.info(f"Manual ORACLE run completed: {len(briefs)} briefs")
        except Exception as e:
            log.error(f"Manual ORACLE failed: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'started', 'agent': 'ORACLE'})

@app.route('/api/react', methods=['POST'])
def react():
    data = request.json
    post_id = data.get('post_id')
    key = data.get('reaction')
    user_id = data.get('user_id', 'anonymous')
    if key not in ('agree', 'flag', 'save'):
        return jsonify({'error': 'Invalid reaction'}), 400
    result = db.toggle_reaction(post_id, key, user_id)
    return jsonify(result)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify(db.get_weekly_stats())

@app.route('/api/trigger/<agent_name>', methods=['GET'])
def trigger_agent(agent_name):
    name = agent_name.upper()
    if name not in AGENTS and name not in ['COUNCIL', 'ORACLE', 'TOWNHALL']:
        return jsonify({'error': 'Unknown agent'}), 404
    
    import threading
    def _run():
        try:
            if name == 'COUNCIL':
                COUNCIL.run_on_unprocessed(db)
            elif name == 'ORACLE':
                ORACLE.run_on_unprocessed(db)
            else:
                recent = db.get_recent_mentions(hours=6)
                posts = AGENTS[name].run(recent_context=recent)
                for p in posts:
                    db.save_post(p)
                log.info(f"{name} triggered: {len(posts)} posts")
        except Exception as e:
            log.error(f"Trigger {name} failed: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'triggered', 'agent': name})

def setup_scheduler():
    scheduler = BackgroundScheduler()
    # Light agents
    scheduler.add_job(lambda: run_agent('VERA'),    'interval', minutes=60)
    scheduler.add_job(lambda: run_agent('DUKE'),    'interval', minutes=45)
    scheduler.add_job(lambda: run_agent('MIRA'),    'interval', minutes=30)
    scheduler.add_job(lambda: run_agent('SOL'),     'interval', minutes=90)
    scheduler.add_job(lambda: run_agent('NOVA'),    'interval', hours=3)
    scheduler.add_job(lambda: run_agent('ECHO'),    'interval', minutes=40)
    scheduler.add_job(lambda: run_agent('KAEL'),    'interval', minutes=20)
    scheduler.add_job(lambda: run_agent('FLUX'),    'interval', minutes=35)
    scheduler.add_job(lambda: run_agent('REX'),     'interval', minutes=50)
    scheduler.add_job(lambda: run_agent('VIGIL'),   'interval', hours=2)
    scheduler.add_job(lambda: run_agent('LORE'),    'interval', hours=3)
    scheduler.add_job(lambda: run_agent('SPECTER'), 'interval', minutes=75)

    # Heavy layers - FIXED for rate limits
    scheduler.add_job(lambda: COUNCIL.run_on_unprocessed(db), 'interval', hours=8, id='council')
    scheduler.add_job(lambda: ORACLE.run_on_unprocessed(db),  'interval', hours=12, id='oracle')

    scheduler.start()
    log.info("Scheduler started with safe intervals (Council 8h, Oracle 12h)")
    return scheduler

def run_agent(name):
    try:
        recent_context = db.get_recent_mentions(hours=6)
        posts = AGENTS[name].run(recent_context=recent_context)
        for post in posts:
            db.save_post(post)
        db.log_agent_run(name, len(posts))
        check_convergence()
        check_for_disagreement()
    except Exception as e:
        log.error(f"{name} agent error: {e}")
        db.log_agent_run(name, 0, str(e))

# Keep your existing convergence, town_hall, and other helper functions here...
# (They remain unchanged unless you want further tweaks)

if __name__ == '__main__':
    db.init()
    scheduler = setup_scheduler()
    port = int(os.environ.get('PORT', 5000))
    log.info(f"Signal Society running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

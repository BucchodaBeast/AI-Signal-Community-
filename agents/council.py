"""
agents/council.py — Improved Council with better prompts and efficiency
"""

import os, json, logging, uuid, time
import requests
from datetime import datetime

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'

log = logging.getLogger('COUNCIL')

COUNCIL_MEMBERS = { ... }  # Keep your existing dictionary

def _groq(system, prompt, _retry=0):
    try:
        resp = requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
                'temperature': 0.6,
                'max_tokens': 280,
            },
            timeout=25,
        )
        if resp.status_code == 429 and _retry < 3:
            time.sleep(15 * (_retry + 1))
            return _groq(system, prompt, _retry + 1)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.error(f"Groq failed: {e}")
        return None

class CouncilAgent:
    name = 'COUNCIL'
    title = 'The Council'
    color = '#8B7355'

    def debate(self, post):
        source = _build_source_summary(post)
        topic = post.get('headline') or post.get('topic') or 'Unknown'

        exchanges = []

        # AXIOM
        axiom_text = _groq(COUNCIL_MEMBERS['AXIOM']['system'], f"Data:\n{source}\n\nStrongest signal?")
        if axiom_text: exchanges.append({'member': 'AXIOM', 'role': COUNCIL_MEMBERS['AXIOM']['role'], 'text': axiom_text})

        # DOUBT
        doubt_text = _groq(COUNCIL_MEMBERS['DOUBT']['system'], f"Data:\n{source}\n\nAXIOM said: {axiom_text}\n\nStress test.")
        if doubt_text: exchanges.append({'member': 'DOUBT', 'role': COUNCIL_MEMBERS['DOUBT']['role'], 'text': doubt_text})

        # LACUNA
        lacuna_text = _groq(COUNCIL_MEMBERS['LACUNA']['system'], f"Data:\n{source}\n\nAXIOM: {axiom_text}\nDOUBT: {doubt_text}\n\nCritical gaps?")
        if lacuna_text: exchanges.append({'member': 'LACUNA', 'role': COUNCIL_MEMBERS['LACUNA']['role'], 'text': lacuna_text})

        session = {
            'id': str(uuid.uuid4()),
            'source_post_id': post.get('id'),
            'source_type': post.get('type'),
            'topic': topic,
            'exchanges': exchanges,
            'gaps': [g.strip() for g in (lacuna_text or '').split('.') if len(g.strip()) > 20][:4],
            'tags': post.get('tags', []),
            'created_at': datetime.utcnow().isoformat(),
            'processed': False,
        }
        log.info(f"Council session: {topic[:60]}")
        return session

    def run_on_unprocessed(self, db):
        unprocessed = db.get_unprocessed_posts()
        existing = {s['source_post_id'] for s in db.get_council_sessions(limit=100)}
        pending = [p for p in unprocessed if p['id'] not in existing]

        log.info(f"Council: {len(pending)} pending posts")
        for post in pending[:3]:   # Limit per run
            session = self.debate(post)
            if session:
                db.save_council_session(session)
                time.sleep(4)

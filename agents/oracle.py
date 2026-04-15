"""
agents/oracle.py — Upgraded Oracle that uses Council debates when available
"""

import os, json, logging, uuid, time
import requests
from datetime import datetime

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'

log = logging.getLogger('ORACLE')

class OracleAgent:
    name = 'ORACLE'
    title = 'The Signal Synthesiser'
    color = '#F0C040'

    SYSTEM = """You are ORACLE..."""  # Keep your full system prompt

    def synthesise(self, post):
        # Prefer Council debate
        council = None
        try:
            sessions = db.get_council_sessions(limit=50)  # Note: db must be passed or imported
            council = next((s for s in sessions if s.get('source_post_id') == post.get('id')), None)
        except:
            pass

        if council and council.get('exchanges'):
            debate = "\n\n".join([f"{e['member']}: {e['text']}" for e in council['exchanges']])
            source_content = f"COUNCIL DEBATE — {council.get('topic')}\n\n{debate}"
        else:
            source_content = str(post)[:900]

        prompt = f"""Analyse this intelligence:

{source_content}

Return ONLY this JSON:
{{
  "headline": "Short sharp title",
  "verdict": "2-3 sentence conclusion",
  "evidence": ["point 1", "point 2"],
  "implications": "Who cares and why",
  "confidence": "LOW/MEDIUM/HIGH/CONFIRMED",
  "action_items": ["check X", "monitor Y"]
}}
"""

        try:
            resp = requests.post(GROQ_URL, headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'},
                json={'model': 'llama-3.3-70b-versatile', 'messages': [{'role':'system','content':self.SYSTEM}, {'role':'user','content':prompt}], 'temperature':0.3, 'max_tokens':700})
            resp.raise_for_status()
            text = resp.json()['choices'][0]['message']['content'].strip()
            if text.startswith('```'): text = text.split('```')[1].strip()
            data = json.loads(text)

            if len(data.get('verdict','')) < 40:
                log.warning("Oracle output too weak - skipped")
                return None

            brief = {
                'id': str(uuid.uuid4()),
                'source_post_id': post.get('id'),
                'source_type': post.get('type'),
                'headline': data.get('headline',''),
                'verdict': data.get('verdict',''),
                'evidence': data.get('evidence',[]),
                'implications': data.get('implications',''),
                'action_items': data.get('action_items',[]),
                'confidence': data.get('confidence','MEDIUM'),
                'tier': 'premium' if data.get('confidence') in ('HIGH','CONFIRMED') else 'free',
                'citizens': post.get('citizens', [post.get('citizen','')]),
                'tags': post.get('tags', []),
                'created_at': datetime.utcnow().isoformat(),
                'published': True,
            }
            log.info(f"Oracle brief: {brief['headline']}")
            return brief
        except Exception as e:
            log.error(f"Oracle synthesise failed: {e}")
            return None

    def run_on_unprocessed(self, db):
        unprocessed = db.get_unprocessed_posts()
        briefs = []
        for post in unprocessed[:4]:   # Safe limit
            brief = self.synthesise(post)
            if brief:
                db.save_brief(brief)
                briefs.append(brief)
                time.sleep(5)   # Gentle pacing
        log.info(f"Oracle generated {len(briefs)} briefs")
        return briefs

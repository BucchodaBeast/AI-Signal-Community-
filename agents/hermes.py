"""
agents/hermes.py — HERMES, The Executor

HERMES sits above Oracle in the intelligence hierarchy.
Where Oracle produces briefs with action items, HERMES actually executes them.

Flow:
  Oracle brief → HERMES reads action_items → maps each to a field agent →
  triggers targeted fetch → gets verified data → appends findings back to brief

This closes the loop:
  Before: "Check the Delaware LLC registry for the assignee name"
  After:  "VERIFIED by DUKE: Delaware LLC 'Horizon Wireless LLC' registered
           2024-03-14, registered agent: Corporation Trust Company (used by
           Microsoft, Amazon). SEC filing cross-reference: positive."

HERMES does NOT generate text. It coordinates real data fetches.
Runs on MEDIUM, HIGH, and CONFIRMED confidence briefs.
MEDIUM briefs get 1 action item verified. HIGH/CONFIRMED get up to 3.
"""

import os, json, logging, uuid, time, re
from datetime import datetime
import requests

log = logging.getLogger('HERMES')

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL     = 'https://api.groq.com/openai/v1/chat/completions'

def _groq_key():
    try:
        from agents.token_budget import get_key
        return get_key()
    except Exception:
        return os.environ.get('GROQ_API_KEY', '')


# ── ACTION ITEM → AGENT ROUTING MAP ──────────────────────────────────────────
# Maps action item keywords to the field agent that owns that data territory.
# HERMES uses this to know which agent to subpoena for verification.

ACTION_ROUTING = [
    # (keywords_in_action_item, agent_name, fetch_method_hint)
    (['sec filing', 'edgar', 'form ', '8-k', '10-k', 'proxy', 'def 14a', 'corporate filing'],
     'DUKE',    'sec'),
    (['job posting', 'hiring', 'linkedin', 'job listing', 'workforce', 'headcount'],
     'DUKE',    'jobs'),
    (['patent', 'uspto', 'wipo', 'ip ', 'intellectual property', 'assignee', 'patent family'],
     'LORE',    'patent'),
    (['fcc', 'spectrum', 'license', 'frequency', 'radio', 'faa', 'permit', 'zoning', 'infrastructure'],
     'NOVA',    'regulatory'),
    (['federal register', 'doj', 'ftc', 'court', 'regulation', 'compliance', 'antitrust', 'lobbying'],
     'REX',     'federal'),
    (['wayback', 'deleted', 'removed', 'cached', 'archive', 'snapshot', 'retracted'],
     'ECHO',    'archive'),
    (['arxiv', 'paper', 'pre-print', 'research', 'academic', 'study', 'published'],
     'VERA',    'academic'),
    (['reddit', 'community', 'sentiment', 'forum', 'hacker news', 'hn ', 'discussion'],
     'MIRA',    'sentiment'),
    (['shipping', 'vessel', 'bdi', 'port', 'freight', 'container', 'cargo', 'commodity flow'],
     'VIGIL',   'shipping'),
    (['breach', 'credential', 'cve', 'hack', 'vulnerability', 'exploit', 'ransomware'],
     'SPECTER', 'breach'),
    (['crypto', 'bitcoin', 'ethereum', 'on-chain', 'treasury yield', 'vix', 'capital flow'],
     'FLUX',    'capital'),
    (['news', 'media', 'publication', 'outlet', 'narrative', 'gdelt', 'headline'],
     'KAEL',    'media'),
    (['correlation', 'pattern', 'noaa', 'weather', 'seismic', 'cross-domain'],
     'SOL',     'pattern'),
]

def _route_action_item(action_text: str) -> tuple:
    """Map an action item to the best agent for verification."""
    text = action_text.lower()
    for keywords, agent, hint in ACTION_ROUTING:
        if any(kw in text for kw in keywords):
            return agent, hint
    return None, None


# ── TARGETED FETCH STRATEGIES ─────────────────────────────────────────────────
# Each strategy does a real targeted fetch based on the action item context.
# These are lightweight — single API calls, not full agent runs.

def _fetch_sec_targeted(action_text: str, brief_context: str) -> dict:
    """Search SEC EDGAR for entities mentioned in the action item."""
    # Extract company/entity name from action text
    entity = _extract_entity(action_text + ' ' + brief_context)
    if not entity:
        return {'found': False, 'reason': 'No entity identified'}
    try:
        resp = requests.get(
            'https://efts.sec.gov/LATEST/search-index?q=' + requests.utils.quote(f'"{entity}"') +
            '&dateRange=custom&startdt=2024-01-01&forms=8-K,SC+13D,DEF+14A,S-1',
            headers={'User-Agent': 'SignalSociety research@signalsociety.ai'},
            timeout=12,
        )
        if not resp.ok:
            return {'found': False, 'reason': f'SEC search failed: {resp.status_code}'}
        data  = resp.json()
        hits  = data.get('hits', {}).get('hits', [])
        if not hits:
            return {'found': False, 'entity': entity, 'reason': 'No recent SEC filings found'}
        recent = hits[0].get('_source', {})
        return {
            'found':      True,
            'entity':     entity,
            'filing':     recent.get('form_type', ''),
            'filed':      recent.get('file_date', ''),
            'company':    recent.get('display_names', [''])[0] if recent.get('display_names') else '',
            'description':recent.get('description', '')[:200],
            'total_hits': len(hits),
        }
    except Exception as e:
        log.error(f"SEC targeted fetch: {e}")
        return {'found': False, 'reason': str(e)}


def _fetch_patent_targeted(action_text: str, brief_context: str) -> dict:
    """Search PatentsView for entities and technologies mentioned."""
    entity = _extract_entity(action_text + ' ' + brief_context)
    tech   = _extract_technology(brief_context)
    query  = entity or tech or 'artificial intelligence'
    try:
        resp = requests.post(
            'https://api.patentsview.org/patents/query',
            json={
                'q': {'_text_any': {'patent_abstract': query}},
                'f': ['patent_number', 'patent_title', 'patent_date', 'assignee_organization'],
                'o': {'sort': [{'patent_date': 'desc'}], 'per_page': 3},
            },
            headers={'Content-Type': 'application/json'},
            timeout=12,
        )
        resp.raise_for_status()
        patents = resp.json().get('patents') or []
        if not patents:
            return {'found': False, 'query': query, 'reason': 'No recent patents found'}
        results = []
        for p in patents:
            assignees = p.get('assignees') or [{}]
            org = assignees[0].get('assignee_organization', 'Unknown') if assignees else 'Unknown'
            results.append({
                'number':   p.get('patent_number', ''),
                'title':    p.get('patent_title', ''),
                'date':     p.get('patent_date', ''),
                'assignee': org,
            })
        return {'found': True, 'query': query, 'patents': results}
    except Exception as e:
        log.error(f"Patent targeted fetch: {e}")
        return {'found': False, 'reason': str(e)}


def _fetch_federal_targeted(action_text: str, brief_context: str) -> dict:
    """Search Federal Register for regulatory actions."""
    entity = _extract_entity(action_text + ' ' + brief_context)
    try:
        resp = requests.get(
            'https://www.federalregister.gov/api/v1/documents.json',
            params={
                'conditions[term]': entity or action_text[:50],
                'per_page': 3, 'order': 'newest',
                'fields[]': ['document_number', 'title', 'publication_date', 'agency_names', 'type'],
            },
            timeout=12,
        )
        resp.raise_for_status()
        docs = resp.json().get('results', [])
        if not docs:
            return {'found': False, 'reason': 'No Federal Register results'}
        return {
            'found':   True,
            'results': [{'title': d.get('title',''), 'agency': ', '.join(d.get('agency_names',[])),
                         'date': d.get('publication_date',''), 'type': d.get('type','')} for d in docs[:3]],
        }
    except Exception as e:
        log.error(f"Federal Register targeted fetch: {e}")
        return {'found': False, 'reason': str(e)}


def _fetch_archive_targeted(action_text: str, brief_context: str) -> dict:
    """Check Wayback Machine for recent snapshots of mentioned URLs/domains."""
    # Try to extract a domain or URL from context
    urls = re.findall(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})(?:/\S*)?', brief_context)
    domain = urls[0] if urls else None
    if not domain:
        return {'found': False, 'reason': 'No domain found in context'}
    try:
        resp = requests.get(
            'https://archive.org/wayback/available',
            params={'url': domain, 'timestamp': datetime.utcnow().strftime('%Y%m%d')},
            timeout=10,
        )
        resp.raise_for_status()
        data     = resp.json()
        snapshot = data.get('archived_snapshots', {}).get('closest', {})
        if not snapshot:
            return {'found': False, 'domain': domain, 'reason': 'No Wayback snapshot found'}
        return {
            'found':     True,
            'domain':    domain,
            'snapshot':  snapshot.get('url', ''),
            'timestamp': snapshot.get('timestamp', ''),
            'status':    snapshot.get('status', ''),
        }
    except Exception as e:
        log.error(f"Archive targeted fetch: {e}")
        return {'found': False, 'reason': str(e)}


FETCH_STRATEGIES = {
    'sec':       _fetch_sec_targeted,
    'jobs':      _fetch_sec_targeted,   # DUKE handles both
    'patent':    _fetch_patent_targeted,
    'federal':   _fetch_federal_targeted,
    'archive':   _fetch_archive_targeted,
}


# ── ENTITY EXTRACTION ─────────────────────────────────────────────────────────

def _extract_entity(text: str) -> str:
    """Extract the most likely company/org name from text."""
    # Look for quoted names first
    quoted = re.findall(r'"([A-Z][^"]{2,40})"', text)
    if quoted:
        return quoted[0]
    # Look for capitalized multi-word phrases (likely proper nouns)
    caps = re.findall(r'\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){1,3})\b', text)
    # Filter out generic words
    generic = {'The Council', 'Signal Society', 'Oracle Brief', 'Action Item',
               'Federal Register', 'Check The', 'Search For', 'Pull The'}
    caps = [c for c in caps if c not in generic and len(c) > 4]
    return caps[0] if caps else ''


def _extract_technology(text: str) -> str:
    """Extract the main technology domain from brief context."""
    tech_patterns = [
        r'\b(artificial intelligence|machine learning|quantum computing|semiconductor|'
        r'autonomous vehicle|gene therapy|battery storage|satellite|neuromorphic)\b'
    ]
    for pat in tech_patterns:
        m = re.search(pat, text.lower())
        if m:
            return m.group(1)
    return ''


# ── HERMES AGENT CLASS ────────────────────────────────────────────────────────

class HermesAgent:
    """
    HERMES — The Executor.
    Takes Oracle action items and verifies them with real targeted data fetches.
    Appends verified findings to the brief as a new 'verified_findings' section.
    """
    name  = 'HERMES'
    title = 'The Executor'
    color = '#1A3A5C'

    def __init__(self):
        self.log = logging.getLogger('HERMES')

    def execute_brief(self, brief: dict, db) -> dict:
        """
        Main entry point. Takes an Oracle brief, executes its action items,
        and returns an enriched brief with verified_findings.
        Only runs on HIGH or CONFIRMED confidence briefs.
        """
        confidence = brief.get('confidence', 'LOW')
        if confidence == 'LOW':
            self.log.debug(f"Skipping LOW confidence brief — below threshold")
            return brief
        # MEDIUM gets 1 action item max, HIGH/CONFIRMED get up to 3
        max_actions = 1 if confidence == 'MEDIUM' else 3

        action_items = brief.get('action_items', [])
        if not action_items:
            return brief

        self.log.info(f"HERMES executing {len(action_items)} action item(s) for: {brief.get('headline','')[:50]}")

        brief_context = ' '.join([
            brief.get('headline', ''),
            brief.get('verdict', ''),
            ' '.join(brief.get('evidence', [])),
        ])

        verified_findings = []
        max_actions = locals().get('max_actions', 3)
        for action in action_items[:max_actions]:   # MEDIUM=1, HIGH/CONFIRMED=3
            agent_name, hint = _route_action_item(action)
            if not agent_name or hint not in FETCH_STRATEGIES:
                verified_findings.append({
                    'action':  action,
                    'agent':   agent_name or 'UNROUTED',
                    'status':  'unrouted',
                    'finding': 'No matching data source for this action item.',
                })
                continue

            self.log.info(f"  → Routing '{action[:60]}' to {agent_name}")
            try:
                result = FETCH_STRATEGIES[hint](action, brief_context)
                status = 'verified' if result.get('found') else 'not_found'
                verified_findings.append({
                    'action':  action,
                    'agent':   agent_name,
                    'status':  status,
                    'finding': result,
                    'checked_at': datetime.utcnow().isoformat(),
                })
            except Exception as e:
                self.log.error(f"  Action execution failed: {e}")
                verified_findings.append({
                    'action':  action,
                    'agent':   agent_name,
                    'status':  'error',
                    'finding': str(e),
                })
            time.sleep(1)  # Be respectful to APIs

        # Synthesise a refined verdict using verified findings
        if any(f.get('status') == 'verified' for f in verified_findings):
            refined = self._synthesise_refined_verdict(brief, verified_findings)
            if refined:
                brief['refined_verdict']   = refined.get('verdict', brief.get('verdict', ''))
                brief['refined_confidence']= refined.get('confidence', confidence)
                brief['refined_at']        = datetime.utcnow().isoformat()

        brief['verified_findings'] = verified_findings
        brief['hermes_ran']        = True

        # Save enriched brief
        try:
            db.save_brief(brief)
            self.log.info(f"HERMES enriched brief saved: {brief.get('headline','')[:50]}")
        except Exception as e:
            self.log.error(f"Failed to save enriched brief: {e}")

        return brief

    def _synthesise_refined_verdict(self, brief: dict, findings: list) -> dict:
        """
        Use Groq to produce a refined verdict that incorporates verified findings.
        This replaces Oracle's speculative verdict with data-backed conclusions.
        """
        from agents.token_budget import can_spend, record_spend
        if not can_spend('oracle', 500):
            return None

        verified = [f for f in findings if f.get('status') == 'verified']
        if not verified:
            return None

        findings_text = '\n'.join([
            f"ACTION: {f['action']}\nVERIFIED BY: {f['agent']}\nFINDING: {json.dumps(f['finding'], indent=2)[:300]}"
            for f in verified
        ])

        prompt = f"""You are HERMES, the Executor layer of The Signal Society.

Oracle produced this brief:
HEADLINE: {brief.get('headline','')}
ORIGINAL VERDICT: {brief.get('verdict','')}
ORIGINAL CONFIDENCE: {brief.get('confidence','')}

The following action items were executed and VERIFIED with real data:
{findings_text}

Produce a refined JSON object with:
{{
  "verdict": "Updated 2-3 sentence verdict incorporating the verified data. Be specific — cite actual entities, dates, filing numbers where available. This replaces Oracle's speculative verdict with confirmed facts.",
  "confidence": "{brief.get('confidence','MEDIUM')}"
}}

Rules:
- Only assert what the verified data actually shows
- If the data confirms Oracle's conclusion, say so explicitly with evidence
- If the data contradicts Oracle's conclusion, say so
- Do not fabricate details not present in the verified findings
- No markdown. JSON only."""

        try:
            resp = requests.post(
                GROQ_URL,
                headers={'Authorization': f'Bearer {_groq_key()}', 'Content-Type': 'application/json'},
                json={
                    'model':       'llama-3.3-70b-versatile',
                    'messages':    [{'role': 'user', 'content': prompt}],
                    'temperature': 0.2,
                    'max_tokens':  400,
                },
                timeout=25,
            )
            if resp.status_code == 429:
                from agents.token_budget import rotate_key
                rotate_key()
                return None
            resp.raise_for_status()
            data   = resp.json()
            tokens = data.get('usage', {}).get('total_tokens', 500)
            record_spend('oracle', tokens)
            text = data['choices'][0]['message']['content'].strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            return json.loads(text)
        except Exception as e:
            self.log.error(f"HERMES synthesis failed: {e}")
            return None

    def run_on_unprocessed_briefs(self, db):
        """
        Find HIGH/CONFIRMED briefs that haven't been executed yet,
        run HERMES on each one.
        """
        try:
            briefs = db.get_briefs(limit=10)
            pending = [
                b for b in briefs
                if b.get('confidence') in ('HIGH', 'CONFIRMED', 'MEDIUM')
                and not b.get('hermes_ran')
                and b.get('action_items')
            ]
            # Prioritise HIGH/CONFIRMED — process them first
            pending.sort(
                key=lambda b: {'CONFIRMED': 0, 'HIGH': 1, 'MEDIUM': 2}.get(b.get('confidence','MEDIUM'), 2)
            )
            self.log.info(f"HERMES found {len(pending)} unexecuted briefs (incl. MEDIUM)")
            results = []
            for brief in pending[:3]:   # Max 3 per run
                enriched = self.execute_brief(brief, db)
                results.append(enriched)
                time.sleep(2)
            self.log.info(f"HERMES executed {len(results)} brief(s)")
            return results
        except Exception as e:
            self.log.error(f"HERMES run_on_unprocessed_briefs failed: {e}")
            return []

"""
agents/token_budget.py — Shared Groq token budget
Exports: can_spend, record_spend, get_key, rotate_key, status
"""

import json, logging, os
from datetime import date

log = logging.getLogger('token_budget')

HARD_LIMIT   = 100_000
SOFT_LIMIT   = 88_000
_BUDGET_FILE = '/tmp/token_budget.json'

_state = {'date': str(date.today()), 'count': 0}

# ── Key rotation ──────────────────────────────────────────────
_keys = [k.strip() for k in os.environ.get('GROQ_API_KEY', '').split(',') if k.strip()]
_key_index = 0

def get_key():
    global _key_index
    if not _keys:
        return os.environ.get('GROQ_API_KEY', '')
    return _keys[_key_index % len(_keys)]

def rotate_key():
    global _key_index
    _key_index += 1
    log.warning(f"Rotated to key index {_key_index % max(len(_keys),1)}")


# ── Persistence ───────────────────────────────────────────────
def _load():
    global _state
    try:
        if os.path.exists(_BUDGET_FILE):
            data = json.load(open(_BUDGET_FILE))
            if data.get('date') == str(date.today()):
                _state = data
                return
    except Exception:
        pass
    _state = {'date': str(date.today()), 'count': 0}

def _save():
    try:
        json.dump(_state, open(_BUDGET_FILE, 'w'))
    except Exception:
        pass

def _reset_if_new_day():
    global _state
    if _state['date'] != str(date.today()):
        _state = {'date': str(date.today()), 'count': 0}
        _save()

_load()


# ── Public API ────────────────────────────────────────────────
def used():
    _reset_if_new_day()
    return _state['count']

def remaining():
    return max(0, SOFT_LIMIT - used())

def can_spend(caller, n):
    """Check if budget allows n more tokens. caller = 'council' | 'oracle'"""
    _reset_if_new_day()
    return (_state['count'] + n) <= SOFT_LIMIT

def record_spend(caller, n):
    """Record actual tokens used. caller = 'council' | 'oracle'"""
    _reset_if_new_day()
    _state['count'] += n
    _save()
    if _state['count'] > SOFT_LIMIT * 0.9:
        log.warning(f"token_budget: {_state['count']}/{HARD_LIMIT} used ({remaining()} remaining)")

# Alias — oracle.py uses record_spend, older code may use record
record = record_spend

def status():
    _reset_if_new_day()
    return {
        'date':       _state['date'],
        'used':       _state['count'],
        'soft_limit': SOFT_LIMIT,
        'hard_limit': HARD_LIMIT,
        'remaining':  remaining(),
        'pct_used':   round(_state['count'] / HARD_LIMIT * 100, 1),
        'warning':    _state['count'] > SOFT_LIMIT * 0.8,
    }

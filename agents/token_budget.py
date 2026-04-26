"""
token_budget.py — Shared Groq token budget for Council + ORACLE

FIX 6+7: Single source of truth for daily token consumption.
Both council.py and oracle.py import this module so they share one counter
instead of each maintaining their own, which could silently allow 2× the limit.

FIX 6 (persistence): On Render free tier the process restarts regularly
(cold starts, deploys) which resets any in-memory counter to 0. To survive
restarts, this module optionally persists the daily count to /tmp/token_budget.json.
/tmp persists within a single Render instance session (not across deploys, but
across cold-start wakeups within the same deploy — good enough to prevent the
worst burst scenarios).
"""

import json, logging, os
from datetime import datetime, date

log = logging.getLogger('token_budget')

HARD_LIMIT   = 100_000   # Groq free tier daily limit
SOFT_LIMIT   = 88_000    # Stop spending above this (12K buffer for bursts)
_BUDGET_FILE = '/tmp/token_budget.json'

# ── In-memory state ──────────────────────────────────────────────────────────
_state = {
    'date':  str(date.today()),
    'count': 0,
}


def _load():
    """Load persisted state from /tmp if it exists and is from today."""
    global _state
    try:
        if os.path.exists(_BUDGET_FILE):
            with open(_BUDGET_FILE) as f:
                data = json.load(f)
            if data.get('date') == str(date.today()):
                _state = data
                log.info(f"token_budget: loaded {_state['count']} tokens from disk for {_state['date']}")
                return
    except Exception as e:
        log.warning(f"token_budget: could not load from disk: {e}")
    # Fresh day or no file
    _state = {'date': str(date.today()), 'count': 0}


def _save():
    """Persist current state to /tmp."""
    try:
        with open(_BUDGET_FILE, 'w') as f:
            json.dump(_state, f)
    except Exception as e:
        log.warning(f"token_budget: could not persist to disk: {e}")


def _reset_if_new_day():
    """Reset counter at midnight."""
    global _state
    today = str(date.today())
    if _state['date'] != today:
        log.info(f"token_budget: new day ({today}), resetting from {_state['count']}")
        _state = {'date': today, 'count': 0}
        _save()


# Load on import
_load()


# ── Public API ────────────────────────────────────────────────────────────────

def used() -> int:
    """Return tokens consumed today."""
    _reset_if_new_day()
    return _state['count']


def remaining() -> int:
    """Return tokens remaining under soft limit."""
    return max(0, SOFT_LIMIT - used())


def can_spend(estimated: int) -> bool:
    """Return True if we have budget for this estimated spend."""
    _reset_if_new_day()
    return (_state['count'] + estimated) <= SOFT_LIMIT


def record(actual: int):
    """Record actual tokens consumed after an API call."""
    _reset_if_new_day()
    _state['count'] += actual
    _save()
    if _state['count'] > SOFT_LIMIT * 0.9:
        log.warning(f"token_budget: {_state['count']}/{HARD_LIMIT} tokens used today ({remaining()} remaining)")


def status() -> dict:
    """Return full budget status dict for /api/health."""
    _reset_if_new_day()
    return {
        'date':          _state['date'],
        'used':          _state['count'],
        'soft_limit':    SOFT_LIMIT,
        'hard_limit':    HARD_LIMIT,
        'remaining':     remaining(),
        'pct_used':      round(_state['count'] / HARD_LIMIT * 100, 1),
        'warning':       _state['count'] > SOFT_LIMIT * 0.8,
        'critical':      _state['count'] >= SOFT_LIMIT,
        'note':          'Persisted to /tmp — survives cold starts within same deploy, resets on new deploy.',
    }

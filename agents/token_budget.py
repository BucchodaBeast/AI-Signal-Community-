"""
agents/token_budget.py — Shared Groq token budget across Council and Oracle.

Both Council and Oracle make Groq calls. Without a shared counter they can
independently consume up to 80K tokens each — potentially 160K on a fresh
process start, blowing the 100K daily cap.

This module is the single source of truth for daily token usage.
Note: resets on process restart (Render free tier cold starts). This is acceptable
— the real guard is the Groq API's own rate limiting; this is a best-effort
local governor to reduce noisy over-spending.
"""

from datetime import datetime
import threading

_lock              = threading.Lock()
_daily_tokens      = 0
_reset_date        = datetime.utcnow().date()
DAILY_CAP          = 90_000   # Hard cap shared across ALL Groq consumers
COUNCIL_RESERVE    = 40_000   # Council gets this slice of the daily budget
ORACLE_RESERVE     = 40_000   # Oracle gets this slice
_council_used      = 0
_oracle_used       = 0


def _maybe_reset():
    global _daily_tokens, _reset_date, _council_used, _oracle_used
    today = datetime.utcnow().date()
    if today != _reset_date:
        _daily_tokens  = 0
        _council_used  = 0
        _oracle_used   = 0
        _reset_date    = today


def can_spend(consumer: str, estimated: int) -> bool:
    """Return True if `consumer` ('council'|'oracle'|'agent') can spend `estimated` tokens."""
    with _lock:
        _maybe_reset()
        if _daily_tokens + estimated > DAILY_CAP:
            return False
        if consumer == 'council' and _council_used + estimated > COUNCIL_RESERVE:
            return False
        if consumer == 'oracle' and _oracle_used + estimated > ORACLE_RESERVE:
            return False
        return True


def record_spend(consumer: str, tokens: int):
    """Record `tokens` spent by `consumer`."""
    global _daily_tokens, _council_used, _oracle_used
    with _lock:
        _maybe_reset()
        _daily_tokens += tokens
        if consumer == 'council':
            _council_used += tokens
        elif consumer == 'oracle':
            _oracle_used += tokens


def status() -> dict:
    """Return current budget status — used by /api/health."""
    with _lock:
        _maybe_reset()
        return {
            'daily_cap':      DAILY_CAP,
            'daily_used':     _daily_tokens,
            'daily_remaining': max(0, DAILY_CAP - _daily_tokens),
            'council_used':   _council_used,
            'council_remaining': max(0, COUNCIL_RESERVE - _council_used),
            'oracle_used':    _oracle_used,
            'oracle_remaining': max(0, ORACLE_RESERVE - _oracle_used),
            'reset_date':     str(_reset_date),
        }

"""
agents/token_budget.py — Shared Groq token budget + dual API key rotation.

TWO API KEYS = DOUBLE THE DAILY LIMIT
Set both keys as environment variables on Render:
  GROQ_API_KEY    — your primary key   (100K tokens/day)
  GROQ_API_KEY_2  — your secondary key (100K tokens/day)
  GROQ_API_KEY_3  — your third key     (100K tokens/day)
Combined daily cap: 180K tokens (leaving a safety buffer below the 200K total).

Key rotation logic:
- Keys rotate per-call in round-robin order
- If key 1 hits its daily cap, all calls shift to key 2 automatically
- If key 2 also hits its cap, calls stop (budget exhausted for the day)
- 429 rate-limit responses trigger an immediate switch to the other key

Budget is per-process (resets on Render cold start) — this is best-effort.
The real enforcement is Groq's own rate limits; this reduces wasteful overspend.
"""

import os, threading
from datetime import datetime

# ── KEY POOL ──────────────────────────────────────────────────────────────────
# ── GLOBAL RATE LIMITER ──────────────────────────────────────────────────────
# Groq free tier = 30 requests/minute = 1 request per 2 seconds max.
# This enforces a minimum gap between ALL Groq calls across all modules.
# Set MIN_CALL_INTERVAL_SECS = 3 to be safe (20 calls/min instead of 30).

MIN_CALL_INTERVAL_SECS = 3.0   # 3s gap = 20 calls/min — safe under 30/min limit
_last_call_time  = 0.0
_rate_lock       = threading.Lock()


def wait_for_rate_limit():
    """
    Block until it is safe to make a Groq API call.
    Call this BEFORE every requests.post() to Groq.
    Ensures globally at most 1 call per MIN_CALL_INTERVAL_SECS.
    """
    global _last_call_time
    with _rate_lock:
        now     = _time.time()
        elapsed = now - _last_call_time
        if elapsed < MIN_CALL_INTERVAL_SECS:
            wait = MIN_CALL_INTERVAL_SECS - elapsed
            _time.sleep(wait)
        _last_call_time = _time.time()


def wait_and_retry_on_429(func, max_retries=4):
    """
    Wrapper that retries a Groq call on 429 with exponential backoff.
    Usage: result = wait_and_retry_on_429(lambda: requests.post(...))
    """
    for attempt in range(max_retries):
        wait_for_rate_limit()
        resp = func()
        if resp.status_code == 429:
            wait = min(60, 15 * (attempt + 1))  # 15s, 30s, 45s, 60s
            import logging
            logging.getLogger('token_budget').warning(
                f"429 on attempt {attempt+1}/{max_retries} — waiting {wait}s then retrying"
            )
            rotate_key()
            _time.sleep(wait)
            continue
        return resp
    return resp  # Return last response even if still 429


def _load_keys():
    """Load all configured Groq API keys from environment."""
    keys = []
    k1 = os.environ.get('GROQ_API_KEY', '').strip()
    k2 = os.environ.get('GROQ_API_KEY_2', '').strip()
    k3 = os.environ.get('GROQ_API_KEY_3', '').strip()
    if k1: keys.append(k1)
    if k2: keys.append(k2)
    if k3: keys.append(k3)
    if not keys:
        import logging
        logging.getLogger('token_budget').warning(
            "No GROQ_API_KEY found in environment. Groq calls will fail."
        )
    return keys

_KEYS            = _load_keys()
_PER_KEY_CAP     = 90_000   # Safety cap per key (Groq allows 100K — we stop at 90K)
_DAILY_CAP       = _PER_KEY_CAP * max(1, len(_KEYS))  # 90K × number of keys
COUNCIL_RESERVE  = min(40_000 * max(1, len(_KEYS)), _DAILY_CAP // 2)
ORACLE_RESERVE   = min(40_000 * max(1, len(_KEYS)), _DAILY_CAP // 2)

# ── STATE ─────────────────────────────────────────────────────────────────────
_lock        = threading.Lock()
_reset_date  = datetime.utcnow().date()
_key_index   = 0          # current key index (round-robin)
_key_tokens  = {}         # tokens used per key: {key_index: int}
_council_used = 0
_oracle_used  = 0

def _maybe_reset():
    global _reset_date, _key_tokens, _council_used, _oracle_used, _key_index
    today = datetime.utcnow().date()
    if today != _reset_date:
        _reset_date   = today
        _key_tokens   = {}
        _council_used = 0
        _oracle_used  = 0
        _key_index    = 0

def _total_tokens() -> int:
    return sum(_key_tokens.values())

# ── PUBLIC API ────────────────────────────────────────────────────────────────

def get_key() -> str:
    """
    Return the best available API key using round-robin rotation.
    Automatically skips keys that have hit their per-key cap.
    Returns empty string if all keys are exhausted.
    """
    global _key_index
    with _lock:
        _maybe_reset()
        if not _KEYS:
            return ''
        # Try each key in order starting from current index
        for offset in range(len(_KEYS)):
            idx  = (_key_index + offset) % len(_KEYS)
            used = _key_tokens.get(idx, 0)
            if used < _PER_KEY_CAP:
                _key_index = idx  # stay on this key for next call too
                return _KEYS[idx]
        # All keys exhausted
        return ''

def rotate_key():
    """
    Force rotation to the next key — call this on a 429 rate-limit response
    so we immediately try the other key instead of waiting.
    """
    global _key_index
    with _lock:
        if len(_KEYS) > 1:
            _key_index = (_key_index + 1) % len(_KEYS)

def can_spend(consumer: str, estimated: int) -> bool:
    """Return True if `consumer` can spend `estimated` tokens right now."""
    with _lock:
        _maybe_reset()
        if _total_tokens() + estimated > _DAILY_CAP:
            return False
        if consumer == 'council' and _council_used + estimated > COUNCIL_RESERVE:
            return False
        if consumer == 'oracle' and _oracle_used + estimated > ORACLE_RESERVE:
            return False
        # Also check the current key hasn't hit its per-key cap
        used = _key_tokens.get(_key_index, 0)
        if used + estimated > _PER_KEY_CAP:
            # Current key is full — check if another key is available
            for idx in range(len(_KEYS)):
                if _key_tokens.get(idx, 0) + estimated <= _PER_KEY_CAP:
                    return True
            return False  # No key has enough budget
        return True

def record_spend(consumer: str, tokens: int):
    """Record tokens spent by consumer against the current key."""
    global _council_used, _oracle_used
    with _lock:
        _maybe_reset()
        _key_tokens[_key_index] = _key_tokens.get(_key_index, 0) + tokens
        if consumer == 'council':
            _council_used += tokens
        elif consumer == 'oracle':
            _oracle_used  += tokens

def status() -> dict:
    """Return full budget status — used by /api/health."""
    with _lock:
        _maybe_reset()
        flat = {}
        for i in range(len(_KEYS)):
            flat[f'key_{i+1}_used']      = _key_tokens.get(i, 0)
            flat[f'key_{i+1}_remaining'] = max(0, _PER_KEY_CAP - _key_tokens.get(i, 0))
        return {
            'keys_configured':   len(_KEYS),
            'daily_cap':         _DAILY_CAP,
            'daily_used':        _total_tokens(),
            'daily_remaining':   max(0, _DAILY_CAP - _total_tokens()),
            'council_used':      _council_used,
            'council_remaining': max(0, COUNCIL_RESERVE - _council_used),
            'oracle_used':       _oracle_used,
            'oracle_remaining':  max(0, ORACLE_RESERVE - _oracle_used),
            'current_key_index': _key_index + 1,
            'reset_date':        str(_reset_date),
            **flat,
        }

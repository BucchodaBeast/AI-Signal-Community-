"""
agents/llm_gateway.py — Central LLM Gateway

Shared module imported by BaseAgent. Provides:
  - Single point of Groq API access for all 13 agents
  - Rolling per-minute token counter (prevents 429s)
  - Daily token budget with per-agent allocation
  - Response cache keyed on prompt hash (saves tokens on repeated similar items)
  - Exponential backoff on rate limits
  - Structured logging per agent per run

No separate service — just a module. Zero infrastructure cost.
"""

import os, time, json, hashlib, logging, threading
from datetime import datetime, date
from collections import deque

log = logging.getLogger('llm_gateway')

# ── GROQ KEYS ─────────────────────────────────────────────────────────────────
def _load_keys() -> list:
    keys = []
    # Primary key
    k = os.environ.get('GROQ_API_KEY', '')
    if k: keys.append(k)
    # Additional keys (GROQ_API_KEY_2, _3, etc.)
    for i in range(2, 6):
        k = os.environ.get(f'GROQ_API_KEY_{i}', '')
        if k: keys.append(k)
    return keys

_KEYS = _load_keys()
_key_index = 0
_key_lock  = threading.Lock()

def _next_key() -> str:
    global _key_index
    with _key_lock:
        if not _KEYS:
            return ''
        key = _KEYS[_key_index % len(_KEYS)]
        _key_index = (_key_index + 1) % len(_KEYS)
        return key

def rotate_key() -> str:
    """Force rotation to next key — call after a 429."""
    return _next_key()

def get_key() -> str:
    return _KEYS[0] if _KEYS else ''

# ── TOKEN BUDGET ───────────────────────────────────────────────────────────────
# Groq free tier: 100,000 tokens/day on llama-3.3-70b-versatile
# We allocate per-agent to prevent any one agent consuming the whole budget.

DAILY_BUDGET_TOTAL = int(os.environ.get('GROQ_DAILY_BUDGET', '95000'))  # 5k safety margin

# Per-agent daily token allocation (tokens/day)
AGENT_DAILY_ALLOCATION = {
    'VERA':     8000,
    'DUKE':     7000,
    'MIRA':     4000,   # Capped — she over-consumes
    'SOL':      6000,
    'NOVA':     6000,
    'ECHO':     6000,
    'KAEL':     7000,
    'FLUX':     6000,
    'REX':      6000,
    'VIGIL':    6000,
    'LORE':     6000,
    'SPECTER':  6000,
    'CASSANDRA':6000,
    'ORACLE':   8000,
    'COUNCIL':  6000,
    'HERMES':   5000,
}

# Token estimates (input + expected output per call)
TOKEN_ESTIMATE_PER_CALL = 900  # conservative: 600 prompt + 300 output

# Thread-safe state
_lock = threading.Lock()

# Rolling per-minute window (token timestamps)
_minute_window: deque = deque()
TOKENS_PER_MINUTE_LIMIT = 14000  # Groq free tier TPM limit with margin

# Daily counters keyed by (agent, date)
_daily_used: dict = {}
_daily_date: str  = ''

def _reset_daily_if_needed():
    global _daily_date, _daily_used
    today = date.today().isoformat()
    if today != _daily_date:
        _daily_date  = today
        _daily_used  = {}
        log.info(f"Daily token budget reset for {today}")

def can_spend(agent: str, estimated_tokens: int = TOKEN_ESTIMATE_PER_CALL) -> bool:
    """Returns True if agent has budget remaining for this call."""
    with _lock:
        _reset_daily_if_needed()
        used     = _daily_used.get(agent, 0)
        alloc    = AGENT_DAILY_ALLOCATION.get(agent, 5000)
        can      = (used + estimated_tokens) <= alloc
        if not can:
            log.warning(f"{agent}: daily budget exhausted ({used}/{alloc} tokens used)")
        return can

def record_spend(agent: str, tokens_used: int):
    """Record actual token usage after a call."""
    with _lock:
        _reset_daily_if_needed()
        _daily_used[agent] = _daily_used.get(agent, 0) + tokens_used
        log.debug(f"{agent}: spent {tokens_used} tokens (total today: {_daily_used[agent]})")

def get_budget_status() -> dict:
    """Return current budget usage for all agents — used by /api/health endpoint."""
    with _lock:
        _reset_daily_if_needed()
        return {
            'date':    _daily_date,
            'agents':  {a: {'used': _daily_used.get(a, 0), 'alloc': AGENT_DAILY_ALLOCATION.get(a, 5000)}
                       for a in AGENT_DAILY_ALLOCATION},
            'total_used': sum(_daily_used.values()),
            'total_budget': DAILY_BUDGET_TOTAL,
        }

def _check_per_minute_limit(estimated_tokens: int) -> bool:
    """Check and enforce per-minute token rate limit. Returns True if OK."""
    now = time.time()
    with _lock:
        # Remove entries older than 60 seconds
        while _minute_window and _minute_window[0][0] < now - 60:
            _minute_window.popleft()
        # Sum tokens in current window
        window_tokens = sum(t for _, t in _minute_window)
        if window_tokens + estimated_tokens > TOKENS_PER_MINUTE_LIMIT:
            return False
        _minute_window.append((now, estimated_tokens))
        return True

def _wait_for_minute_limit(estimated_tokens: int):
    """Block until per-minute window clears enough space."""
    while not _check_per_minute_limit(estimated_tokens):
        wait = 5
        log.info(f"Per-minute TPM limit approaching — waiting {wait}s")
        time.sleep(wait)

# ── PER-MINUTE REQUEST RATE LIMIT ───────────────────────────────────────────────
# Groq's 429s are driven by REQUESTS-per-minute, not just tokens-per-minute.
# The original gateway only tracked TPM (_minute_window below), which is why
# agents kept getting 429'd even while comfortably under their token budget.
#
# With N rotating keys, each key gets its own RPM allowance from Groq, so the
# *effective* combined capacity scales with key count. REQUESTS_PER_MINUTE_LIMIT
# is set per-key and multiplied by the number of configured keys, with a safety
# margin, so adding more keys (GROQ_API_KEY_2, _3, ...) automatically raises the
# ceiling without needing another code change.

REQUESTS_PER_MINUTE_LIMIT_PER_KEY = int(os.environ.get('GROQ_RPM_PER_KEY', '25'))  # conservative free-tier margin

def _effective_rpm_limit() -> int:
    """Total allowed requests/minute across all configured keys, with a 1-key floor."""
    n_keys = max(len(_KEYS), 1)
    return REQUESTS_PER_MINUTE_LIMIT_PER_KEY * n_keys

_request_window: deque = deque()

def _check_request_rate_limit() -> bool:
    """Check and enforce per-minute REQUEST count limit. Returns True if OK to proceed."""
    now = time.time()
    with _lock:
        while _request_window and _request_window[0] < now - 60:
            _request_window.popleft()
        if len(_request_window) >= _effective_rpm_limit():
            return False
        _request_window.append(now)
        return True

def _wait_for_request_limit():
    """Block until the per-minute request window clears enough space."""
    while not _check_request_rate_limit():
        wait = 5
        log.info(f"Per-minute REQUEST limit approaching ({_effective_rpm_limit()}/min across {len(_KEYS)} key(s)) — waiting {wait}s")
        time.sleep(wait)


# ── RESPONSE CACHE ─────────────────────────────────────────────────────────────
# Cache keyed on SHA256 of prompt. TTL: 3600s (1 hour).
# Prevents re-spending tokens on identical items within the same hour.

_cache: dict = {}
_cache_lock  = threading.Lock()
CACHE_TTL    = 3600  # seconds

def _cache_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]

def cache_get(prompt: str):
    with _cache_lock:
        k = _cache_key(prompt)
        if k in _cache:
            ts, val = _cache[k]
            if time.time() - ts < CACHE_TTL:
                return val
            del _cache[k]
    return None

def cache_set(prompt: str, value):
    with _cache_lock:
        _cache[_cache_key(prompt)] = (time.time(), value)

def cache_clear_expired():
    with _cache_lock:
        now = time.time()
        expired = [k for k, (ts, _) in _cache.items() if now - ts >= CACHE_TTL]
        for k in expired:
            del _cache[k]

# ── MAIN CALL FUNCTION ─────────────────────────────────────────────────────────

def call(
    agent:           str,
    system_prompt:   str,
    user_prompt:     str,
    max_tokens:      int   = 600,
    temperature:     float = 0.6,
    use_cache:       bool  = True,
    model:           str   = 'llama-3.3-70b-versatile',
) -> str | None:
    """
    Make a Groq API call through the gateway.

    Returns the response text or None on failure.
    Handles: budget check, rate limiting, caching, retry, key rotation.
    """
    estimated = max_tokens + 400  # rough input estimate

    # 1. Daily budget check
    if not can_spend(agent, estimated):
        return None

    # 2. Cache check
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    if use_cache:
        cached = cache_get(full_prompt)
        if cached is not None:
            log.debug(f"{agent}: cache hit — saved ~{estimated} tokens")
            return cached

    # 3. Per-minute rate limits — both dimensions matter independently:
    #    tokens-per-minute (existing) AND requests-per-minute (the actual
    #    cause of the 429 storm, since Groq enforces both).
    _wait_for_minute_limit(estimated)
    _wait_for_request_limit()

    # 4. API call with retry + key rotation
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        key = _next_key()
        if not key:
            log.error(f"{agent}: No GROQ_API_KEY configured")
            return None
        try:
            import requests as _req
            resp = _req.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {key}',
                    'Content-Type':  'application/json',
                },
                json={
                    'model':       model,
                    'max_tokens':  max_tokens,
                    'temperature': temperature,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user',   'content': user_prompt},
                    ],
                },
                timeout=45,
            )
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                log.warning(
                    f"{agent}: 429 on attempt {attempt+1} (key #{(_key_index - 1) % max(len(_KEYS),1)}) "
                    f"— rotating key and waiting {wait}s"
                )
                time.sleep(wait)
                continue  # _next_key() at top of next loop iteration rotates to the next key
            if resp.status_code == 401:
                log.error(f"{agent}: 401 — invalid key, rotating")
                continue
            resp.raise_for_status()
            data  = resp.json()
            text  = data['choices'][0]['message']['content'].strip()
            usage = data.get('usage', {})
            actual_tokens = usage.get('total_tokens', estimated)
            record_spend(agent, actual_tokens)
            if use_cache:
                cache_set(full_prompt, text)
            log.info(f"{agent}: OK — {actual_tokens} tokens used")
            return text
        except Exception as e:
            log.error(f"{agent}: attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(5 * (attempt + 1))

    log.error(f"{agent}: all {MAX_RETRIES} attempts failed")
    return None

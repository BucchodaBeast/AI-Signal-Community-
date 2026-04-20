"""
agents/agent_queue.py — Intelligent Agent Queue Manager

Replaces the flat APScheduler stampede with a priority-aware, budget-conscious
dispatch system. This is the difference between a news scanner and an
intelligence platform.

DESIGN PRINCIPLES:
─────────────────
1. Priority tiers — not all work is equal:
     CRITICAL  (0) : Condition triggers (VIX spike, breach, paradigm paper)
     HIGH      (1) : Council sessions, Oracle synthesis
     NORMAL    (2) : Field agents with pending subpoenas
     LOW       (3) : Routine scheduled field agent scans

2. Budget awareness — check before firing:
     Each job estimates its token cost. If the shared budget can't cover it,
     the job is deferred to the next cycle rather than silently wasting a call.

3. Backpressure — protect synthesis layers:
     If token budget falls below 20%, only CRITICAL and HIGH jobs run.
     If budget falls below 5%, everything stops except condition triggers.

4. Jitter — prevent the thundering herd:
     Jobs due at the same tick are staggered by a small random delay (0-15s)
     so they don't all hit Groq simultaneously and trigger rate limits.

5. Observability — every dispatch is logged with priority and budget context.
"""

import threading, time, random, logging
from datetime import datetime
from queue import PriorityQueue, Empty
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger('AgentQueue')


# ── PRIORITY CONSTANTS ────────────────────────────────────────────────────────
CRITICAL = 0   # condition triggers — VIX spike, critical breach, etc.
HIGH     = 1   # Council debate, Oracle synthesis
NORMAL   = 2   # field agent with pending subpoena
LOW      = 3   # routine scheduled field agent scan


# ── AGENT COST ESTIMATES (tokens per run) ────────────────────────────────────
# Conservative estimates. Actual spend tracked by token_budget.py.
# Field agents: ~400 tokens per post × 3 posts max = ~1200
# Council: ~300 tokens × 3 members = ~900
# Oracle: ~700 tokens per brief
AGENT_COSTS = {
    # Field agents
    'VERA':    1200, 'DUKE':    1200, 'MIRA':    800,
    'SOL':     1000, 'NOVA':    1000, 'ECHO':    800,
    'KAEL':    800,  'FLUX':    1000, 'REX':     1200,
    'VIGIL':   1000, 'LORE':    1200, 'SPECTER': 1000,
    # Synthesis
    'COUNCIL': 900,
    'ORACLE':  700,
}

# Budget thresholds — what fraction of daily budget triggers backpressure
BACKPRESSURE_MEDIUM = 0.20   # below 20% remaining: only HIGH+ runs
BACKPRESSURE_SEVERE = 0.05   # below 5% remaining: only CRITICAL runs


@dataclass(order=True)
class QueueJob:
    """A single unit of work in the queue."""
    priority:    int             # lower = higher priority (0 = CRITICAL)
    agent_name:  str = field(compare=False)
    run_fn:      Callable = field(compare=False)
    estimated_tokens: int = field(compare=False, default=1000)
    reason:      str = field(compare=False, default='scheduled')
    enqueued_at: float = field(compare=False, default_factory=time.time)

    def age_seconds(self) -> float:
        return time.time() - self.enqueued_at


class AgentQueue:
    """
    Priority queue dispatcher for all agent work.

    Usage:
        queue = AgentQueue(run_agent_fn, council, oracle, db)
        queue.start()

        # Enqueue work at any priority
        queue.enqueue('VERA',    priority=LOW,      reason='scheduled')
        queue.enqueue('COUNCIL', priority=HIGH,     reason='town_hall_trigger')
        queue.enqueue('FLUX',    priority=CRITICAL, reason='vix_spike_condition')
    """

    def __init__(self, run_agent_fn, council_obj, oracle_obj, db_obj):
        self._q            = PriorityQueue()
        self._run_agent    = run_agent_fn
        self._council      = council_obj
        self._oracle       = oracle_obj
        self._db           = db_obj
        self._running      = False
        self._worker       = None
        self._lock         = threading.Lock()
        self._active_jobs  = set()   # names currently running
        self._stats        = {
            'dispatched': 0, 'deferred_budget': 0,
            'deferred_backpressure': 0, 'errors': 0,
        }

    # ── PUBLIC API ────────────────────────────────────────────────────────────

    def enqueue(self, agent_name: str, priority: int = LOW,
                reason: str = 'scheduled', run_fn: Optional[Callable] = None):
        """
        Add a job to the queue.
        If run_fn is None, uses the standard run_agent(agent_name) function.
        """
        cost = AGENT_COSTS.get(agent_name, 1000)
        fn   = run_fn or (lambda n=agent_name: self._run_agent(n))
        job  = QueueJob(
            priority=priority, agent_name=agent_name,
            run_fn=fn, estimated_tokens=cost, reason=reason,
        )
        self._q.put(job)
        log.debug(f"Enqueued {agent_name} [P{priority}] reason={reason} "
                  f"cost≈{cost} queue_size={self._q.qsize()}")

    def enqueue_condition(self, agent_name: str, run_fn: Callable, reason: str):
        """Shortcut for condition-triggered CRITICAL priority jobs."""
        self.enqueue(agent_name, priority=CRITICAL, reason=reason, run_fn=run_fn)

    def start(self):
        """Start the background worker thread."""
        self._running = True
        self._worker  = threading.Thread(target=self._work_loop, daemon=True, name='AgentQueue')
        self._worker.start()
        log.info("AgentQueue started")

    def stop(self):
        self._running = False
        if self._worker:
            self._worker.join(timeout=5)

    def status(self) -> dict:
        """Return queue status — used by /api/health."""
        try:
            from agents.token_budget import status as budget_status
            budget = budget_status()
        except Exception:
            budget = {}
        return {
            'queue_depth':   self._q.qsize(),
            'active_jobs':   list(self._active_jobs),
            'stats':         dict(self._stats),
            'token_budget':  budget,
        }

    # ── INTERNAL WORKER ───────────────────────────────────────────────────────

    def _work_loop(self):
        """
        Main worker loop. Pulls jobs from the queue one at a time,
        applies budget checks and backpressure, then dispatches with jitter.
        """
        log.info("AgentQueue worker loop started")
        while self._running:
            try:
                job = self._q.get(timeout=2)
            except Empty:
                continue

            try:
                if self._should_defer(job):
                    # Put back at the end of its priority tier
                    self._q.task_done()
                    time.sleep(5)
                    self._q.put(job)  # re-queue — will be tried next cycle
                    continue

                # Apply jitter: stagger concurrent jobs by 0–15 seconds
                jitter = random.uniform(0, 15)
                if jitter > 1:
                    log.debug(f"Jitter {jitter:.1f}s before {job.agent_name}")
                    time.sleep(jitter)

                self._dispatch(job)

            except Exception as e:
                log.error(f"Queue worker error on {job.agent_name}: {e}")
                self._stats['errors'] += 1
            finally:
                try:
                    self._q.task_done()
                except Exception:
                    pass

            # Small gap between dispatches — prevents thundering herd
            time.sleep(1)

    def _should_defer(self, job: QueueJob) -> bool:
        """
        Apply backpressure. Returns True if this job should be re-queued.
        """
        try:
            from agents.token_budget import status as budget_status, can_spend
            budget = budget_status()
            remaining = budget.get('daily_remaining', 0)
            daily_cap = budget.get('daily_cap', 90_000)
            fraction_remaining = remaining / daily_cap if daily_cap else 1.0
        except Exception:
            return False  # If budget check fails, let it through

        # SEVERE backpressure — only CRITICAL jobs run
        if fraction_remaining < BACKPRESSURE_SEVERE:
            if job.priority > CRITICAL:
                log.warning(f"SEVERE backpressure: deferring {job.agent_name} "
                            f"[P{job.priority}] ({remaining} tokens left)")
                self._stats['deferred_backpressure'] += 1
                return True

        # MEDIUM backpressure — only HIGH+ jobs run
        if fraction_remaining < BACKPRESSURE_MEDIUM:
            if job.priority > HIGH:
                log.info(f"Medium backpressure: deferring {job.agent_name} "
                         f"[P{job.priority}] ({remaining} tokens left)")
                self._stats['deferred_backpressure'] += 1
                return True

        # Budget check — can this specific job afford to run?
        try:
            from agents.token_budget import can_spend
            consumer = 'council' if job.agent_name == 'COUNCIL' else \
                       'oracle'  if job.agent_name == 'ORACLE'  else 'agent'
            if not can_spend(consumer, job.estimated_tokens):
                log.info(f"Budget insufficient for {job.agent_name} "
                         f"(needs ≈{job.estimated_tokens}). Deferring.")
                self._stats['deferred_budget'] += 1
                return True
        except Exception:
            pass

        # Don't run the same agent twice concurrently
        with self._lock:
            if job.agent_name in self._active_jobs:
                log.debug(f"{job.agent_name} already running — deferring duplicate")
                return True

        return False

    def _dispatch(self, job: QueueJob):
        """Run a job in a new thread, tracking active state."""
        with self._lock:
            self._active_jobs.add(job.agent_name)

        self._stats['dispatched'] += 1
        age = job.age_seconds()
        log.info(f"DISPATCH {job.agent_name} [P{job.priority}] "
                 f"reason={job.reason} age={age:.0f}s cost≈{job.estimated_tokens}")

        def _run():
            try:
                job.run_fn()
            except Exception as e:
                log.error(f"Job {job.agent_name} failed: {e}")
                self._stats['errors'] += 1
            finally:
                with self._lock:
                    self._active_jobs.discard(job.agent_name)

        threading.Thread(target=_run, daemon=True, name=f'job-{job.agent_name}').start()

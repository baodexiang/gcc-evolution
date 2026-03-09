"""
GCC v5.300 — L0 Fault Tolerance & Graceful Degradation (IRS-005)

Apache 2.0 — open-source interface layer.
The private engine registers concrete Phase implementations and wires
the degradation policy into the GCC orchestrator.

Theory grounding (Structured Search Space Theorem, Brenner et al. 2026):
    "A fault in any single Phase must not collapse the entire pipeline."

    GCC L0 runs Phase1~Phase4 sequentially.  Without fault isolation,
    a single API timeout or model error kills the whole cycle.

    IRS-005 adds three layers of protection:
        1. Retry      — exponential back-off up to 3 attempts per Phase
        2. Fallback   — Phase failure → use last cached result + alert
        3. Bypass     — critical module failure → EMA-only signal path

    Degradation is tracked per Phase; when failure_rate > 10% the
    Phase is automatically downgraded (ACTIVE → DEGRADED → BYPASSED).

Open-core boundary:
    Apache 2.0 (this file):
        - PhaseStatus enum
        - PhaseResult / HeartbeatRecord dataclasses
        - RetryPolicy: exponential back-off with configurable parameters
        - FaultIsolator: per-Phase degradation state machine
        - PhaseGuard: wraps any Phase callable with retry + fallback
        - HeartbeatMonitor: tracks liveness and failure rates

    BUSL 1.1 (private engine):
        - Concrete Phase1~Phase4 implementations
        - EMA-only bypass signal path
        - DuckDB persistence of fault events
        - Dashboard fault indicator badges

Usage::

    from gcc_evolution.fault_tolerance import (
        PhaseGuard, FaultIsolator, HeartbeatMonitor, RetryPolicy
    )

    isolator = FaultIsolator()
    monitor  = HeartbeatMonitor()
    policy   = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=8.0)

    # Wrap any Phase callable
    def phase1_run(ctx):
        ...  # may raise

    guard = PhaseGuard(
        phase_id="Phase1",
        isolator=isolator,
        monitor=monitor,
        retry_policy=policy,
        fallback_cache={},   # last known good result
    )

    result = guard.run(phase1_run, ctx)
    if result.degraded:
        print(f"Phase1 degraded: {result.reason}")
    else:
        print(result.value)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Enumerations
# ═══════════════════════════════════════════════════════════════════

class PhaseStatus(str, Enum):
    """
    Degradation state of a GCC Phase.

    ACTIVE:    Phase running normally
    DEGRADED:  Phase failing intermittently; using cached fallback
    BYPASSED:  Phase fully bypassed; EMA-only fallback in effect
    RECOVERING: Phase recovering after a BYPASSED period
    """
    ACTIVE     = "active"
    DEGRADED   = "degraded"
    BYPASSED   = "bypassed"
    RECOVERING = "recovering"


# ═══════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PhaseResult:
    """
    Result of a guarded Phase execution.

    phase_id:  which Phase produced this result
    value:     return value from the Phase callable (None if failed)
    degraded:  True = Phase used fallback / cache; result is stale
    bypassed:  True = Phase fully skipped; downstream uses EMA-only
    attempts:  number of tries before success or final failure
    reason:    human-readable failure reason (empty on success)
    duration:  wall-clock seconds for the execution
    executed_at: ISO timestamp
    """
    phase_id:    str
    value:       Any    = None
    degraded:    bool   = False
    bypassed:    bool   = False
    attempts:    int    = 1
    reason:      str    = ""
    duration:    float  = 0.0
    executed_at: str    = field(default_factory=_now)

    @property
    def ok(self) -> bool:
        """True when Phase ran successfully without fallback."""
        return not self.degraded and not self.bypassed


@dataclass
class HeartbeatRecord:
    """
    One liveness record for a Phase heartbeat check.

    phase_id:  Phase identifier
    alive:     True = Phase responded within timeout
    latency:   response time in seconds (None if timed out)
    status:    current PhaseStatus at time of check
    checked_at: ISO timestamp
    """
    phase_id:   str
    alive:      bool
    latency:    float | None = None
    status:     PhaseStatus  = PhaseStatus.ACTIVE
    checked_at: str          = field(default_factory=_now)


@dataclass
class RetryPolicy:
    """
    Exponential back-off retry configuration.

    max_retries: maximum number of retry attempts (default 3)
    base_delay:  initial delay in seconds (default 1.0)
    max_delay:   upper bound on delay in seconds (default 8.0)
    backoff:     multiplicative factor per retry (default 2.0)

    Delay schedule: base_delay × backoff^attempt, capped at max_delay.
    Example with defaults: 1s → 2s → 4s (max 8s)
    """
    max_retries: int   = 3
    base_delay:  float = 1.0
    max_delay:   float = 8.0
    backoff:     float = 2.0

    def delay_for(self, attempt: int) -> float:
        """Delay in seconds before the given retry attempt (0-indexed)."""
        return min(self.base_delay * (self.backoff ** attempt), self.max_delay)


# ═══════════════════════════════════════════════════════════════════
# FaultIsolator — per-Phase degradation state machine (S41~S45)
# ═══════════════════════════════════════════════════════════════════

class FaultIsolator:
    """
    Tracks per-Phase failure rates and manages degradation state.

    IRS-005 S45: failure_rate > 10% → auto-downgrade to DEGRADED.
    IRS-005 S45: failure_rate > 50% → auto-downgrade to BYPASSED.

    Open-source (Apache 2.0).  The private engine hooks on_status_change()
    to update the Dashboard fault badge and trigger EMA-only fallback.

    Args:
        degraded_threshold: failure rate above this → DEGRADED (default 0.10)
        bypassed_threshold: failure rate above this → BYPASSED (default 0.50)
        window_size: sliding window of recent Phase calls (default 50)
    """

    def __init__(
        self,
        degraded_threshold: float = 0.10,
        bypassed_threshold: float = 0.50,
        window_size: int = 50,
    ):
        self.degraded_threshold = degraded_threshold
        self.bypassed_threshold = bypassed_threshold
        self.window_size = window_size
        # phase_id → list[bool] (True=success)
        self._history: dict[str, list[bool]] = {}
        # phase_id → PhaseStatus
        self._status: dict[str, PhaseStatus] = {}

    def record(self, phase_id: str, success: bool) -> PhaseStatus:
        """
        Record the outcome of one Phase execution.

        Returns the current PhaseStatus after updating the state machine.
        """
        history = self._history.setdefault(phase_id, [])
        history.append(success)
        if len(history) > self.window_size:
            self._history[phase_id] = history[-self.window_size:]

        rate = self.failure_rate(phase_id)
        old_status = self._status.get(phase_id, PhaseStatus.ACTIVE)

        if rate > self.bypassed_threshold:
            new_status = PhaseStatus.BYPASSED
        elif rate > self.degraded_threshold:
            new_status = PhaseStatus.DEGRADED
        else:
            new_status = (
                PhaseStatus.RECOVERING
                if old_status in (PhaseStatus.DEGRADED, PhaseStatus.BYPASSED)
                else PhaseStatus.ACTIVE
            )

        self._status[phase_id] = new_status
        if new_status != old_status:
            logger.warning(
                "[FAULT_ISOLATOR] %s: %s → %s (failure_rate=%.1f%%)",
                phase_id, old_status.value, new_status.value, rate * 100,
            )
            self.on_status_change(phase_id, old_status, new_status)

        return new_status

    def failure_rate(self, phase_id: str) -> float:
        """Current failure rate for phase_id over the sliding window."""
        history = self._history.get(phase_id, [])
        if not history:
            return 0.0
        return sum(1 for ok in history if not ok) / len(history)

    def status(self, phase_id: str) -> PhaseStatus:
        """Current degradation status of phase_id."""
        return self._status.get(phase_id, PhaseStatus.ACTIVE)

    def on_status_change(
        self,
        phase_id: str,
        old_status: PhaseStatus,
        new_status: PhaseStatus,
    ) -> None:
        """
        Hook called when a Phase transitions between degradation states.

        Override in the private engine to update Dashboard badge,
        trigger EMA-only fallback path, and send alerts.
        """

    def summary(self) -> dict[str, dict]:
        """Per-Phase summary of failure_rate and current status."""
        return {
            pid: {
                "status":       self._status.get(pid, PhaseStatus.ACTIVE).value,
                "failure_rate": round(self.failure_rate(pid), 4),
                "n_records":    len(self._history.get(pid, [])),
            }
            for pid in self._history
        }


# ═══════════════════════════════════════════════════════════════════
# PhaseGuard — retry + fallback wrapper (S41~S43)
# ═══════════════════════════════════════════════════════════════════

class PhaseGuard:
    """
    Wraps a GCC Phase callable with retry + cached-fallback protection.

    IRS-005 contract:
        1. Attempt execution up to retry_policy.max_retries times
           with exponential back-off between attempts.
        2. On final failure, return the last cached result (stale)
           and mark result.degraded = True.
        3. When FaultIsolator status is BYPASSED, skip execution
           entirely and return result.bypassed = True.

    Open-source (Apache 2.0).  The private engine's EMA-only fallback
    path is invoked by the orchestrator when result.bypassed is True.

    Args:
        phase_id:       identifier for this Phase (e.g. "Phase1")
        isolator:       FaultIsolator tracking failure rates
        monitor:        HeartbeatMonitor for liveness tracking
        retry_policy:   RetryPolicy with exponential back-off parameters
        fallback_cache: mutable dict; key "last_result" holds cached value
        sleep_fn:       injectable sleep (default time.sleep; override in tests)
    """

    def __init__(
        self,
        phase_id:       str,
        isolator:       FaultIsolator | None      = None,
        monitor:        "HeartbeatMonitor | None" = None,
        retry_policy:   RetryPolicy | None        = None,
        fallback_cache: dict | None               = None,
        sleep_fn:       Callable[[float], None]   = time.sleep,
    ):
        self.phase_id      = phase_id
        self._isolator     = isolator     if isolator     is not None else FaultIsolator()
        self._monitor      = monitor      if monitor      is not None else HeartbeatMonitor()
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._cache        = fallback_cache if fallback_cache is not None else {}
        self._sleep        = sleep_fn

    def run(self, phase_fn: Callable, *args, **kwargs) -> PhaseResult:
        """
        Execute phase_fn with retry + fallback protection.

        Returns PhaseResult — inspect .ok / .degraded / .bypassed.
        """
        status = self._isolator.status(self.phase_id)

        if status == PhaseStatus.BYPASSED:
            logger.warning("[PHASE_GUARD] %s BYPASSED — skipping", self.phase_id)
            return PhaseResult(
                phase_id=self.phase_id,
                bypassed=True,
                reason=f"{self.phase_id} is BYPASSED (failure rate exceeded threshold)",
            )

        p = self._retry_policy
        last_exc: Exception | None = None
        t0 = time.monotonic()

        for attempt in range(p.max_retries + 1):
            try:
                value = phase_fn(*args, **kwargs)
                duration = time.monotonic() - t0
                self._isolator.record(self.phase_id, success=True)
                self._monitor.record(HeartbeatRecord(
                    phase_id=self.phase_id, alive=True, latency=duration,
                    status=self._isolator.status(self.phase_id),
                ))
                self._cache["last_result"] = value
                logger.debug(
                    "[PHASE_GUARD] %s OK (attempt %d/%d, %.2fs)",
                    self.phase_id, attempt + 1, p.max_retries + 1, duration,
                )
                return PhaseResult(
                    phase_id=self.phase_id, value=value,
                    attempts=attempt + 1, duration=duration,
                )

            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[PHASE_GUARD] %s attempt %d/%d failed: %s",
                    self.phase_id, attempt + 1, p.max_retries + 1, exc,
                )
                if attempt < p.max_retries:
                    delay = p.delay_for(attempt)
                    logger.debug("[PHASE_GUARD] retrying in %.1fs", delay)
                    self._sleep(delay)

        # All retries exhausted — use fallback
        duration = time.monotonic() - t0
        self._isolator.record(self.phase_id, success=False)
        self._monitor.record(HeartbeatRecord(
            phase_id=self.phase_id, alive=False,
            status=self._isolator.status(self.phase_id),
        ))
        cached = self._cache.get("last_result")
        reason = f"{self.phase_id} failed after {p.max_retries + 1} attempts: {last_exc}"
        logger.error("[PHASE_GUARD] %s — using cached fallback. %s", self.phase_id, reason)

        return PhaseResult(
            phase_id=self.phase_id,
            value=cached,
            degraded=True,
            attempts=p.max_retries + 1,
            reason=reason,
            duration=duration,
        )


# ═══════════════════════════════════════════════════════════════════
# HeartbeatMonitor — Phase liveness tracking (S44~S46)
# ═══════════════════════════════════════════════════════════════════

class HeartbeatMonitor:
    """
    Tracks Phase heartbeat records for liveness monitoring.

    IRS-005 S44: each Phase module records a heartbeat on every execution.
    IRS-005 S46: aggregate stats feed into the Dashboard fault panel.

    Open-source (Apache 2.0).  The private engine additionally:
        - Exposes real-time liveness via Dashboard WebSocket
        - Alerts via Slack/email when a Phase goes dead

    Args:
        window_size: number of recent heartbeats to retain per Phase (default 100)
    """

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._records: dict[str, list[HeartbeatRecord]] = {}

    def record(self, hb: HeartbeatRecord) -> None:
        """Record one heartbeat for a Phase."""
        records = self._records.setdefault(hb.phase_id, [])
        records.append(hb)
        if len(records) > self.window_size:
            self._records[hb.phase_id] = records[-self.window_size:]

    def is_alive(self, phase_id: str) -> bool:
        """True when the most recent heartbeat for phase_id is alive."""
        records = self._records.get(phase_id, [])
        return records[-1].alive if records else True  # assume alive if no data

    def availability(self, phase_id: str) -> float:
        """Fraction of heartbeats where the Phase was alive."""
        records = self._records.get(phase_id, [])
        if not records:
            return 1.0
        return sum(1 for r in records if r.alive) / len(records)

    def mean_latency(self, phase_id: str) -> float | None:
        """Mean response latency in seconds; None if no successful records."""
        records = self._records.get(phase_id, [])
        latencies = [r.latency for r in records if r.latency is not None]
        return sum(latencies) / len(latencies) if latencies else None

    def recent(self, phase_id: str, n: int = 10) -> list[HeartbeatRecord]:
        """Return the n most recent heartbeat records for phase_id."""
        return self._records.get(phase_id, [])[-n:]

    def summary(self) -> dict[str, dict]:
        """Per-Phase availability and latency summary for Dashboard."""
        return {
            pid: {
                "alive":        self.is_alive(pid),
                "availability": round(self.availability(pid), 4),
                "mean_latency": self.mean_latency(pid),
                "n_records":    len(self._records.get(pid, [])),
            }
            for pid in self._records
        }

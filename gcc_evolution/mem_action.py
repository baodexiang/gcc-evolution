"""
GCC v5.300 — Mem-as-Action Interface (IRS-001)

Apache 2.0 — open-source interface layer.
The KNN-based memory evolution algorithm is private (BUSL 1.1).

Theory grounding (arXiv:2601.12538 — Mem-as-Action, Self-Evolving Memory):
    Fixed memory management rules (write/forget windows determined by
    calendar time) cannot adapt when market regime shifts from trending
    to ranging — stale memories are preserved while fresh memories are
    discarded at the wrong rate.

    IRS-001 reframes the four core memory operations as learnable actions:
        write      → store a new experience card in L1 memory
        retrieve   → fetch relevant cards for current decision context
        forget     → evict a card from active memory
        consolidate → merge or summarize a cluster of cards

    The L4 KNN evolution engine optimizes the *policy* that selects
    among these actions — not just the signal weights.

    Reward signal:
        r_t = Δ IC_t+1   (IC improvement after memory action)
        positive reward → action was beneficial
        negative reward → action should be avoided in similar context

    Verification Priority Theorem implication (Brenner et al. 2026):
        Memory *write* must be validated before committing.
        A bad write (pollution) degrades all subsequent retrievals.
        Contamination rate target: < 2% of writes.

Open-core boundary:
    Apache 2.0 (this file):
        - MemAction enum and MemActionRequest dataclass
        - MemActionResult dataclass with reward interface
        - MemoryPolicy abstract base class (implement to plug in)
        - MemActionLog for audit trail
        - PollutionGuard — contamination rate tracker

    BUSL 1.1 (private engine):
        - KNN-based policy that selects optimal action from context
        - walk-forward optimization of policy over IC history
        - Adaptive forgetting rate tuned to regime transitions

Usage::

    from gcc_evolution.mem_action import (
        MemAction, MemActionRequest, MemActionResult,
        MemoryPolicy, MemActionLog, PollutionGuard,
    )

    class MyPolicy(MemoryPolicy):
        def decide(self, request):
            # Return which action to take and optional params
            if request.confidence < 0.4:
                return MemActionRequest(
                    action=MemAction.FORGET,
                    card_id=request.card_id,
                    context=request.context,
                )
            return MemActionRequest(
                action=MemAction.WRITE,
                card_id=request.card_id,
                context=request.context,
                payload=request.payload,
            )

    policy = MyPolicy()
    req = MemActionRequest(
        action=MemAction.WRITE,
        card_id="EXP-001",
        context={"regime": "trending", "symbol": "TSLA"},
        payload={"ic": 0.07, "signal": "breakout"},
    )
    result = policy.execute(req)
    print(result.reward)   # IC delta after action
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Core Enumerations
# ═══════════════════════════════════════════════════════════════════

class MemAction(str, Enum):
    """
    The four learnable memory operations.

    These are the action space A for the L4 memory policy.
    Each action has a cost and an expected IC impact; the KNN
    evolution engine learns the optimal mapping: context → action.
    """
    WRITE       = "write"       # Store new experience card
    RETRIEVE    = "retrieve"    # Fetch relevant cards for current context
    FORGET      = "forget"      # Evict a card from active memory
    CONSOLIDATE = "consolidate" # Merge / summarize a cluster of cards


class MemActionStatus(str, Enum):
    """Execution status of a memory action."""
    SUCCESS   = "success"   # Action completed normally
    BLOCKED   = "blocked"   # Blocked by PollutionGuard or validation
    SKIPPED   = "skipped"   # No-op (e.g. retrieve found nothing)
    ERROR     = "error"     # Unexpected failure


# ═══════════════════════════════════════════════════════════════════
# Request / Result
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MemActionRequest:
    """
    A request to execute one memory action.

    action:      which of the four operations to perform
    card_id:     target card identifier (may be empty for RETRIEVE)
    context:     current system state snapshot used for policy decision
                 (regime, symbol, market_state, session_id, etc.)
    payload:     data to write or consolidate (for WRITE / CONSOLIDATE)
    confidence:  caller's confidence in this request (0.0–1.0)
    source:      who is making the request (e.g. "L4_knn", "L5_orchestrator")
    requested_at: ISO timestamp
    """
    action:       MemAction
    card_id:      str  = ""
    context:      dict = field(default_factory=dict)
    payload:      dict = field(default_factory=dict)
    confidence:   float = 1.0
    source:       str   = "L4_knn"
    requested_at: str   = field(default_factory=_now)


@dataclass
class MemActionResult:
    """
    Result of executing a memory action.

    action:      the action that was executed
    card_id:     the card that was operated on
    status:      SUCCESS / BLOCKED / SKIPPED / ERROR
    reward:      Δ IC after action (positive = helpful, negative = harmful)
                 None = not yet measured (requires walk-forward verification)
    retrieved:   cards returned by RETRIEVE actions
    reason:      human-readable explanation (especially for BLOCKED)
    metadata:    additional data from the engine
    executed_at: ISO timestamp
    """
    action:      MemAction
    card_id:     str
    status:      MemActionStatus
    reward:      float | None = None
    retrieved:   list[dict]  = field(default_factory=list)
    reason:      str          = ""
    metadata:    dict         = field(default_factory=dict)
    executed_at: str          = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "action":      self.action.value,
            "card_id":     self.card_id,
            "status":      self.status.value,
            "reward":      self.reward,
            "n_retrieved": len(self.retrieved),
            "reason":      self.reason,
            "executed_at": self.executed_at,
        }


# ═══════════════════════════════════════════════════════════════════
# MemoryPolicy — abstract base  (implement to plug in)
# ═══════════════════════════════════════════════════════════════════

class MemoryPolicy(ABC):
    """
    Abstract base for memory action policies.

    Open-source contract (Apache 2.0).  Implement this to plug a custom
    policy into the GCC framework.  The private KNN evolution engine
    subclasses this and optimizes policy weights via walk-forward IC.

    Subclass must implement:
        execute(request) → MemActionResult

    Optional override:
        on_reward(result, reward) — called when IC feedback arrives
            (used by the private engine to update KNN weights)
    """

    @abstractmethod
    def execute(self, request: MemActionRequest) -> MemActionResult:
        """
        Execute a memory action and return the result.

        The implementation is responsible for:
          WRITE:       persisting the payload under card_id
          RETRIEVE:    returning relevant cards in result.retrieved
          FORGET:      evicting card_id from active memory
          CONSOLIDATE: merging cards and returning the consolidated card_id

        The caller will later supply reward via on_reward() once the
        IC impact of this action is measurable (after walk-forward verification).
        """

    def on_reward(self, result: MemActionResult, reward: float) -> None:
        """
        Receive IC reward feedback for a previously executed action.

        Called by the walk-forward optimizer after it has measured
        the IC impact of this action on subsequent signals.

        Default: log only.  Private engine updates KNN policy weights here.
        """
        logger.debug(
            "[MEM_POLICY] reward=%.4f for action=%s card=%s",
            reward, result.action.value, result.card_id
        )

    def action_space(self) -> list[MemAction]:
        """Return the set of actions this policy supports (default: all four)."""
        return list(MemAction)


# ═══════════════════════════════════════════════════════════════════
# MemActionLog — audit trail
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MemActionLogEntry:
    """One entry in the memory action audit trail."""
    request:  MemActionRequest
    result:   MemActionResult
    logged_at: str = field(default_factory=_now)


class MemActionLog:
    """
    In-memory audit trail for memory actions.

    Open-source (Apache 2.0).  The private engine persists this to DuckDB
    and computes aggregate IC-reward statistics per action type.

    Example::

        log = MemActionLog(max_entries=1000)
        log.record(request, result)
        stats = log.stats()
        print(stats["write"]["mean_reward"])
    """

    def __init__(self, max_entries: int = 500):
        self._entries: list[MemActionLogEntry] = []
        self.max_entries = max_entries

    def record(self, request: MemActionRequest, result: MemActionResult) -> None:
        """Append a completed action to the log (evict oldest if full)."""
        entry = MemActionLogEntry(request=request, result=result)
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

    def recent(self, n: int = 50) -> list[MemActionLogEntry]:
        """Return the n most recent entries."""
        return self._entries[-n:]

    def stats(self) -> dict[str, dict]:
        """
        Compute per-action statistics over all logged entries.

        Returns dict keyed by action name with:
            count, success_rate, mean_reward, blocked_count
        """
        result: dict[str, dict] = {}
        for action in MemAction:
            entries = [e for e in self._entries if e.result.action == action]
            if not entries:
                continue
            successes  = sum(1 for e in entries if e.result.status == MemActionStatus.SUCCESS)
            blocked    = sum(1 for e in entries if e.result.status == MemActionStatus.BLOCKED)
            rewards    = [e.result.reward for e in entries if e.result.reward is not None]
            mean_reward = sum(rewards) / len(rewards) if rewards else None
            result[action.value] = {
                "count":        len(entries),
                "success_rate": successes / len(entries),
                "blocked_count": blocked,
                "mean_reward":  mean_reward,
            }
        return result

    def __len__(self) -> int:
        return len(self._entries)


# ═══════════════════════════════════════════════════════════════════
# PollutionGuard — contamination rate tracker
# ═══════════════════════════════════════════════════════════════════

class PollutionGuard:
    """
    Tracks and enforces the memory contamination rate threshold.

    IRS-001 acceptance criterion: contamination rate (bad writes) < 2%.

    A write is "polluted" if the experience card it stores turns out to
    have negative IC impact — i.e. it degrades subsequent signal quality.
    The private engine detects this via walk-forward IC regression.

    This open-source class provides:
        - Sliding-window contamination rate tracking
        - Threshold enforcement (block writes if rate is too high)
        - Rate reporting for Dashboard

    Args:
        threshold:   max allowed contamination rate (default 0.02 = 2%)
        window_size: number of recent writes to track (default 200)
    """

    def __init__(self, threshold: float = 0.02, window_size: int = 200):
        self.threshold   = threshold
        self.window_size = window_size
        self._writes: list[bool] = []   # True = clean, False = polluted

    def record_write(self, is_clean: bool) -> None:
        """Record the outcome of a write action (clean or polluted)."""
        self._writes.append(is_clean)
        if len(self._writes) > self.window_size:
            self._writes = self._writes[-self.window_size:]

    @property
    def contamination_rate(self) -> float:
        """Current contamination rate over the sliding window."""
        if not self._writes:
            return 0.0
        polluted = sum(1 for w in self._writes if not w)
        return polluted / len(self._writes)

    @property
    def n_writes(self) -> int:
        return len(self._writes)

    def is_safe(self) -> bool:
        """True when contamination rate is within threshold."""
        return self.contamination_rate <= self.threshold

    def check_write(self) -> tuple[bool, str]:
        """
        Pre-flight check before allowing a write.

        Returns (allowed, reason).  If contamination rate exceeds threshold,
        returns (False, reason) — the caller should set status=BLOCKED.
        """
        rate = self.contamination_rate
        if rate > self.threshold and self.n_writes >= 10:
            return False, (
                f"Contamination rate {rate:.1%} exceeds threshold {self.threshold:.1%} "
                f"— write blocked until rate recovers"
            )
        return True, ""

    def summary(self) -> dict:
        return {
            "n_writes":           self.n_writes,
            "contamination_rate": round(self.contamination_rate, 4),
            "threshold":          self.threshold,
            "is_safe":            self.is_safe(),
        }

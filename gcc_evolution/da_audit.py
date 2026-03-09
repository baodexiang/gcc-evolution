"""
GCC v5.340 — DA Transition Guard & Violation Audit Trail (IRS-002 S13~S16)

Apache 2.0 — open-source interface layer.
DuckDB write logic and Dashboard rendering are private (BUSL 1.1).

Design (POMDP Safety Constraint Theorem, arXiv:2601.12538):
    Every L4→L5 state transition must pass all DA-01~06 checks.
    When any check fails the transition must be:
        1. Refused — callback is not executed
        2. Logged  — violation written to DuckDB audit trail
        3. Notified — human notified via registered handler
        4. Flagged  — decision path marked "DA_VIOLATION" in L1 Memory

    DATransitionGuard wraps any L4→L5 callable and enforces this contract.
    It calls DirectionAnchorValidator.validate() before every execution.

DuckDB schema (private engine creates table; this file defines the schema):
    CREATE TABLE da_violations (
        id            TEXT PRIMARY KEY,
        checked_at    TEXT,
        da_codes      TEXT,   -- JSON array of violated codes
        reason        TEXT,
        anchor_dir    TEXT,
        action        TEXT,
        subject       TEXT,
        market_state  TEXT,
        blocked       BOOLEAN,
        session_id    TEXT
    );

Usage::

    from gcc_evolution.da_audit import DATransitionGuard, DAViolationLog
    from gcc_evolution.direction_anchor import DirectionAnchorValidator

    validator = DirectionAnchorValidator()
    log = DAViolationLog(max_entries=500)

    class AlertHook(DANotifyHook):
        def notify(self, record): print(f"[DA ALERT] {record.summary}")

    guard = DATransitionGuard(
        validator=validator,
        violation_log=log,
        notify_hooks=[AlertHook()],
    )

    # Wrap any L4→L5 callable
    def execute_trade(action, subject, params):
        ...  # actual execution

    result = guard.run(
        transition_fn=execute_trade,
        fn_args=("BUY", "TSLA", {}),
        anchor=anchor_dict,
        proposed_action={"action": "BUY", "subject": "TSLA"},
        state={"market_regime": "trending_up"},
    )

    if result.blocked:
        print(result.violations)   # list of DAViolation
    else:
        print(result.fn_result)    # return value of execute_trade
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .direction_anchor import (
    DACheckResult,
    DAContext,
    DAViolation,
    DirectionAnchorValidator,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Violation Record
# ═══════════════════════════════════════════════════════════════════

@dataclass
class DAViolationRecord:
    """
    Structured record of one DA violation event.

    Stored to DuckDB by the private engine; schema matches the
    CREATE TABLE definition in this module's docstring.

    Fields:
        id:           UUID for this violation event
        checked_at:   ISO timestamp of the check
        da_codes:     list of violated DA condition codes (e.g. ["DA-01", "DA-03"])
        reason:       combined reason string
        anchor_dir:   anchor direction at violation time
        action:       proposed action (BUY / SELL / HOLD / …)
        subject:      target (symbol, task, etc.)
        market_state: market regime at violation time
        blocked:      True — transition was refused
        session_id:   session identifier for traceability
    """
    id:           str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    checked_at:   str   = field(default_factory=_now)
    da_codes:     list  = field(default_factory=list)
    reason:       str   = ""
    anchor_dir:   str   = ""
    action:       str   = ""
    subject:      str   = ""
    market_state: str   = ""
    blocked:      bool  = True
    session_id:   str   = ""

    @property
    def summary(self) -> str:
        codes = ", ".join(self.da_codes)
        return f"[DA_VIOLATION] {self.action}/{self.subject} blocked by {codes}: {self.reason}"

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "checked_at":   self.checked_at,
            "da_codes":     self.da_codes,
            "reason":       self.reason,
            "anchor_dir":   self.anchor_dir,
            "action":       self.action,
            "subject":      self.subject,
            "market_state": self.market_state,
            "blocked":      self.blocked,
            "session_id":   self.session_id,
        }

    def to_duckdb_row(self) -> dict:
        """Row dict ready for DuckDB INSERT (da_codes serialized as JSON)."""
        d = self.to_dict()
        d["da_codes"] = json.dumps(d["da_codes"])
        return d


# ═══════════════════════════════════════════════════════════════════
# Violation Log
# ═══════════════════════════════════════════════════════════════════

class DAViolationLog:
    """
    In-memory violation audit trail.

    Open-source (Apache 2.0).  The private engine subclasses this to
    flush records to DuckDB and serve them via the Dashboard query API.

    Provides:
        - append() / recent() / stats()
        - DuckDB CREATE TABLE DDL
        - 100% traceability: every violation has a unique ID + timestamp

    Args:
        max_entries: sliding-window size (default 500)
    """

    DUCKDB_DDL = """
CREATE TABLE IF NOT EXISTS da_violations (
    id            TEXT PRIMARY KEY,
    checked_at    TEXT    NOT NULL,
    da_codes      TEXT    NOT NULL,  -- JSON array
    reason        TEXT,
    anchor_dir    TEXT,
    action        TEXT,
    subject       TEXT,
    market_state  TEXT,
    blocked       BOOLEAN NOT NULL DEFAULT TRUE,
    session_id    TEXT
);
""".strip()

    def __init__(self, max_entries: int = 500):
        self._records: list[DAViolationRecord] = []
        self.max_entries = max_entries

    def append(self, record: DAViolationRecord) -> None:
        """Add a violation record (evict oldest if window full)."""
        self._records.append(record)
        if len(self._records) > self.max_entries:
            self._records = self._records[-self.max_entries:]
        logger.warning("[DA_AUDIT] %s", record.summary)

    def recent(self, n: int = 20) -> list[DAViolationRecord]:
        """Return the n most recent violation records."""
        return self._records[-n:]

    def stats(self) -> dict:
        """
        Aggregate statistics over all logged violations.

        Returns:
            total_violations, by_code (count per DA code),
            blocked_rate, most_recent_at
        """
        total = len(self._records)
        by_code: dict[str, int] = {}
        for r in self._records:
            for code in r.da_codes:
                by_code[code] = by_code.get(code, 0) + 1
        blocked = sum(1 for r in self._records if r.blocked)
        most_recent = self._records[-1].checked_at if self._records else ""
        return {
            "total_violations": total,
            "by_code":          by_code,
            "blocked_rate":     blocked / total if total else 0.0,
            "most_recent_at":   most_recent,
        }

    def coverage_rate(self, total_transitions: int) -> float:
        """
        Fraction of transitions where a DA check was performed.
        IRS-002 acceptance: coverage = 100% → rate should equal 1.0
        if the guard is correctly inserted at every L4→L5 point.
        """
        if total_transitions == 0:
            return 0.0
        # NOTE: This log only stores blocked transitions.  The private engine
        # subclasses DAViolationLog to also log passed transitions, making
        # coverage_rate meaningful (target 1.0 = every L4→L5 was guarded).
        return min(1.0, len(self._records) / total_transitions)

    def __len__(self) -> int:
        return len(self._records)


# ═══════════════════════════════════════════════════════════════════
# Transition Result
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TransitionResult:
    """
    Result of a guarded L4→L5 transition attempt.

    blocked:    True = DA validation failed, transition refused
    da_result:  the full DACheckResult
    violations: shortcut to da_result.violations
    fn_result:  return value of the transition callable (None if blocked)
    record:     the DAViolationRecord written to the log (None if passed)
    """
    blocked:    bool
    da_result:  DACheckResult
    fn_result:  Any                        = None
    record:     DAViolationRecord | None   = None

    @property
    def violations(self) -> list[DAViolation]:
        return self.da_result.violations

    @property
    def passed(self) -> bool:
        return not self.blocked


# ═══════════════════════════════════════════════════════════════════
# DA Notification Hook
# ═══════════════════════════════════════════════════════════════════

class DANotifyHook:
    """
    Abstract notification hook for DA violations.

    Open-source interface (Apache 2.0).  The private engine registers
    concrete implementations (email, Slack, Dashboard badge, etc.).

    Override notify() to implement custom alerting.
    """

    def notify(self, record: DAViolationRecord) -> None:
        """Called immediately when a DA violation is detected."""
        logger.warning("[DA_NOTIFY] %s", record.summary)


# ═══════════════════════════════════════════════════════════════════
# DATransitionGuard — core integration point (S13)
# ═══════════════════════════════════════════════════════════════════

class DATransitionGuard:
    """
    Wraps any L4→L5 transition callable and enforces DA-01~06 validation.

    This is the integration point for IRS-002:
        "在L4→L5每次转移时自动调用DA验证器"

    Every call to run() automatically:
        1. Builds a DAContext from the supplied anchor / action / state
        2. Runs DirectionAnchorValidator.validate()
        3. If passed  → executes transition_fn and returns result
        4. If blocked → logs violation, notifies, returns TransitionResult(blocked=True)

    Open-source (Apache 2.0).  The private engine additionally:
        - Flushes DAViolationRecord to DuckDB
        - Marks decision path in L1 Memory as "DA_VIOLATION"
        - Updates Dashboard violation counter

    Args:
        validator:     DirectionAnchorValidator instance (injectable)
        violation_log: DAViolationLog to append violations to
        notify_hooks:  list of DANotifyHook to call on violation
        session_id:    session identifier for audit trail
    """

    def __init__(
        self,
        validator:     DirectionAnchorValidator | None = None,
        violation_log: DAViolationLog | None           = None,
        notify_hooks:  list[DANotifyHook] | None       = None,
        session_id:    str                             = "",
    ):
        self._validator     = validator     if validator     is not None else DirectionAnchorValidator()
        self._log           = violation_log if violation_log is not None else DAViolationLog()
        self._hooks         = notify_hooks  if notify_hooks  is not None else [DANotifyHook()]
        self._session_id    = session_id
        self._total_checks  = 0
        self._total_blocked = 0

    def run(
        self,
        transition_fn:   Callable,
        fn_args:         tuple          = (),
        fn_kwargs:       dict           = None,
        anchor:          dict           = None,
        proposed_action: dict           = None,
        state:           dict           = None,
    ) -> TransitionResult:
        """
        Execute transition_fn only if all DA conditions pass.

        Args:
            transition_fn:   the L4→L5 callable (e.g. execute_trade)
            fn_args:         positional args for transition_fn
            fn_kwargs:       keyword args for transition_fn
            anchor:          active HumanAnchor dict (required for DA-01~06)
            proposed_action: the action being requested
            state:           current system state

        Returns:
            TransitionResult — inspect .blocked and .fn_result
        """
        fn_kwargs       = fn_kwargs       or {}
        anchor          = anchor          or {}
        proposed_action = proposed_action or {}
        state           = state           or {}

        ctx = DAContext(
            anchor=anchor,
            proposed_action=proposed_action,
            state=state,
        )

        self._total_checks += 1
        da_result = self._validator.validate(ctx)

        if da_result.passed:
            fn_result = transition_fn(*fn_args, **fn_kwargs)
            return TransitionResult(blocked=False, da_result=da_result, fn_result=fn_result)

        # Transition blocked — build violation record
        self._total_blocked += 1
        record = DAViolationRecord(
            da_codes    = [v.code.value for v in da_result.violations],
            reason      = "; ".join(v.reason for v in da_result.violations),
            anchor_dir  = anchor.get("direction", ""),
            action      = proposed_action.get("action", ""),
            subject     = proposed_action.get("subject", ""),
            market_state= state.get("market_regime", ""),
            blocked     = True,
            session_id  = self._session_id,
        )

        self._log.append(record)
        for hook in self._hooks:
            try:
                hook.notify(record)
            except Exception as e:
                logger.error("[DA_AUDIT] notify hook failed: %s", e)

        return TransitionResult(blocked=True, da_result=da_result, record=record)

    @property
    def violation_log(self) -> DAViolationLog:
        return self._log

    def metrics(self) -> dict:
        """
        Guard-level metrics for acceptance validation (IRS-002 S18~S19).

        total_checks:   number of L4→L5 transitions guarded
        total_blocked:  number of transitions refused
        block_rate:     fraction of transitions blocked (target: < 5% false-positive)
        violation_log:  log.stats() summary
        """
        return {
            "total_checks":   self._total_checks,
            "total_blocked":  self._total_blocked,
            "block_rate":     (
                self._total_blocked / self._total_checks
                if self._total_checks else 0.0
            ),
            "violation_stats": self._log.stats(),
        }

"""
GCC v5.405 — Reasoning Trace Logger (IRS-008)

Apache 2.0 — open-source interface layer.
DuckDB persistence and Dashboard query interface are private (BUSL 1.1).

Theory grounding (Verification Priority Theorem, Brenner et al. 2026):
    "Verifiability requires that every decision has a complete, queryable
     audit trail — not just the final action, but the full reasoning path."

    Current GCC logs signals and trades, but the intermediate reasoning
    is scattered across log lines and not queryable.

    IRS-008 defines a structured reasoning trace captured at every
    L4→L5 transition:

        TraceRecord fields (IRS-008 S72):
            timestamp        — when the decision was made
            market_state     — market regime + symbol at decision time
            signals_considered — list of plugin signals considered
            skeptic_verdict  — OverfitCheckResult from Skeptic gate
            da_checks_passed — list of DA conditions that passed
            final_decision   — BUY / SELL / HOLD / BLOCKED
            confidence       — confidence score [0, 1]

    Every trace has a unique ID for cross-referencing with DA violation
    logs, Shapley attributions, and Fleiss Kappa snapshots.

Open-core boundary:
    Apache 2.0 (this file):
        - TraceRecord dataclass (IRS-008 S71~S72)
        - ReasoningTraceLog: in-memory sliding-window storage
        - TraceQuery: filter / search interface

    BUSL 1.1 (private engine):
        - DuckDB flush (IRS-008 S73)
        - L4/L5 instrumentation hooks (IRS-008 S74)
        - Dashboard query UI by time / ticker / decision type (IRS-008 S75)
        - Periodic pattern mining over trace history (IRS-008 S76)

DuckDB schema (private engine creates table; this file defines the schema):
    CREATE TABLE reasoning_traces (
        id                TEXT PRIMARY KEY,
        timestamp         TEXT NOT NULL,
        symbol            TEXT,
        market_state      TEXT,
        signals_considered TEXT,  -- JSON array
        skeptic_verdict   TEXT,
        da_checks_passed  TEXT,   -- JSON array
        final_decision    TEXT    NOT NULL,
        confidence        REAL,
        session_id        TEXT
    );

Usage::

    from gcc_evolution.reasoning_trace import ReasoningTraceLog, TraceRecord

    log = ReasoningTraceLog(max_entries=2000)

    trace = TraceRecord(
        symbol="TSLA",
        market_state="trending_up",
        signals_considered=[
            {"plugin": "KNN",    "signal": "BUY",  "confidence": 0.72},
            {"plugin": "Vision", "signal": "BUY",  "confidence": 0.81},
            {"plugin": "Chan",   "signal": "HOLD", "confidence": 0.55},
        ],
        skeptic_verdict="PASS",
        da_checks_passed=["DA-01", "DA-02", "DA-03", "DA-04", "DA-05", "DA-06"],
        final_decision="BUY",
        confidence=0.76,
    )
    log.append(trace)

    results = log.query(symbol="TSLA", decision="BUY", limit=10)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


# ═══════════════════════════════════════════════════════════════════
# TraceRecord — structured decision audit entry (S71~S72)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TraceRecord:
    """
    Structured reasoning trace for one L4→L5 decision (IRS-008 S72).

    Fields:
        id:                   unique 12-char identifier
        timestamp:            ISO timestamp of the decision
        symbol:               trading symbol (e.g. "TSLA", "BTC")
        market_state:         market regime at decision time
        signals_considered:   list of plugin signal dicts
                              [{"plugin": str, "signal": str, "confidence": float}]
        skeptic_verdict:      "PASS" / "BLOCK" / "SKIP" from Skeptic gate
        da_checks_passed:     list of DA condition codes that passed (e.g. ["DA-01", ...])
        final_decision:       "BUY" / "SELL" / "HOLD" / "BLOCKED"
        confidence:           final decision confidence [0, 1]
        session_id:           session identifier for grouping
        metadata:             any additional context from the private engine
    """
    symbol:             str        = ""
    market_state:       str        = ""
    signals_considered: list[dict] = field(default_factory=list)
    skeptic_verdict:    str        = ""
    da_checks_passed:   list[str]  = field(default_factory=list)
    final_decision:     str        = ""
    confidence:         float      = 0.0
    session_id:         str        = ""
    metadata:           dict       = field(default_factory=dict)
    id:                 str        = field(default_factory=_short_id)
    timestamp:          str        = field(default_factory=_now)

    @property
    def n_signals(self) -> int:
        """Number of plugin signals considered."""
        return len(self.signals_considered)

    @property
    def da_passed_all(self) -> bool:
        """True when all 6 DA conditions are in the passed list."""
        return len(self.da_checks_passed) == 6

    def to_dict(self) -> dict:
        return {
            "id":                   self.id,
            "timestamp":            self.timestamp,
            "symbol":               self.symbol,
            "market_state":         self.market_state,
            "signals_considered":   self.signals_considered,
            "skeptic_verdict":      self.skeptic_verdict,
            "da_checks_passed":     self.da_checks_passed,
            "final_decision":       self.final_decision,
            "confidence":           self.confidence,
            "session_id":           self.session_id,
            "metadata":             self.metadata,
        }

    def to_duckdb_row(self) -> dict:
        """Row dict ready for DuckDB INSERT (JSON-serialized list fields)."""
        d = self.to_dict()
        d["signals_considered"] = json.dumps(d["signals_considered"])
        d["da_checks_passed"]   = json.dumps(d["da_checks_passed"])
        d.pop("metadata")   # metadata stored separately in private engine
        return d

    @property
    def summary(self) -> str:
        return (
            f"[TRACE] {self.symbol} {self.final_decision} "
            f"(conf={self.confidence:.2f}, DA={'OK' if self.da_passed_all else 'PARTIAL'}, "
            f"skeptic={self.skeptic_verdict})"
        )


# ═══════════════════════════════════════════════════════════════════
# DuckDB DDL
# ═══════════════════════════════════════════════════════════════════

REASONING_TRACE_DDL = """
CREATE TABLE IF NOT EXISTS reasoning_traces (
    id                TEXT    PRIMARY KEY,
    timestamp         TEXT    NOT NULL,
    symbol            TEXT,
    market_state      TEXT,
    signals_considered TEXT,
    skeptic_verdict   TEXT,
    da_checks_passed  TEXT,
    final_decision    TEXT    NOT NULL,
    confidence        REAL,
    session_id        TEXT
);
""".strip()


# ═══════════════════════════════════════════════════════════════════
# ReasoningTraceLog — in-memory audit trail (S73~S74)
# ═══════════════════════════════════════════════════════════════════

class ReasoningTraceLog:
    """
    In-memory sliding-window audit trail for reasoning traces.

    IRS-008 S73: traces are persisted to DuckDB by the private engine.
    IRS-008 S74: L4/L5 instrumentation hooks call append() on every transition.

    Acceptance criteria (IRS-008 S77~S79):
        - 100% of L4→L5 transitions produce a TraceRecord
        - Query latency < 1 second (enforced at private engine layer)
        - 500~2000 traces/day on DuckDB: stable (tested by private engine)

    Args:
        max_entries: sliding window size (default 2000)
    """

    DDL = REASONING_TRACE_DDL

    def __init__(self, max_entries: int = 2000):
        self._traces: list[TraceRecord] = []
        self.max_entries = max_entries

    def append(self, trace: TraceRecord) -> None:
        """Add one trace to the log (evict oldest if window full)."""
        self._traces.append(trace)
        if len(self._traces) > self.max_entries:
            self._traces = self._traces[-self.max_entries:]
        logger.debug("[REASONING_TRACE] %s", trace.summary)

    def query(
        self,
        symbol:   str | None = None,
        decision: str | None = None,
        limit:    int        = 50,
    ) -> list[TraceRecord]:
        """
        Filter traces by symbol and/or decision type.

        IRS-008 S75: Dashboard query by time / ticker / decision type.
        Returns up to `limit` most recent matching traces.
        """
        results = self._traces
        if symbol is not None:
            results = [t for t in results if t.symbol == symbol]
        if decision is not None:
            results = [t for t in results if t.final_decision == decision]
        return results[-limit:]

    def recent(self, n: int = 20) -> list[TraceRecord]:
        """Return the n most recent traces."""
        return self._traces[-n:]

    def stats(self) -> dict:
        """
        Aggregate statistics over the sliding window.

        Returns decision distribution, mean confidence, DA pass rate.
        """
        total = len(self._traces)
        if total == 0:
            return {"total": 0}

        decision_counts: dict[str, int] = {}
        for t in self._traces:
            decision_counts[t.final_decision] = decision_counts.get(t.final_decision, 0) + 1

        mean_conf = sum(t.confidence for t in self._traces) / total
        da_pass_rate = sum(1 for t in self._traces if t.da_passed_all) / total

        return {
            "total":            total,
            "decision_counts":  decision_counts,
            "mean_confidence":  round(mean_conf, 4),
            "da_pass_rate":     round(da_pass_rate, 4),
        }

    def __len__(self) -> int:
        return len(self._traces)


# ═══════════════════════════════════════════════════════════════════
# TraceQuery — programmatic filter builder (S75~S76)
# ═══════════════════════════════════════════════════════════════════

class TraceQuery:
    """
    Fluent builder for filtering TraceRecord collections.

    IRS-008 S75~S76: supports Dashboard query UI and pattern mining.

    Usage::

        results = (
            TraceQuery(log.recent(500))
            .by_symbol("TSLA")
            .by_decision("BUY")
            .min_confidence(0.7)
            .with_da_pass()
            .execute()
        )
    """

    def __init__(self, traces: list[TraceRecord]):
        self._traces = list(traces)

    def by_symbol(self, symbol: str) -> "TraceQuery":
        self._traces = [t for t in self._traces if t.symbol == symbol]
        return self

    def by_decision(self, decision: str) -> "TraceQuery":
        self._traces = [t for t in self._traces if t.final_decision == decision]
        return self

    def min_confidence(self, threshold: float) -> "TraceQuery":
        self._traces = [t for t in self._traces if t.confidence >= threshold]
        return self

    def with_da_pass(self) -> "TraceQuery":
        """Keep only traces where all 6 DA conditions passed."""
        self._traces = [t for t in self._traces if t.da_passed_all]
        return self

    def by_skeptic(self, verdict: str) -> "TraceQuery":
        self._traces = [t for t in self._traces if t.skeptic_verdict == verdict]
        return self

    def by_regime(self, regime: str) -> "TraceQuery":
        self._traces = [t for t in self._traces if t.market_state == regime]
        return self

    def execute(self, limit: int | None = None) -> list[TraceRecord]:
        """Return filtered traces (optionally limited, most recent first)."""
        result = self._traces
        if limit is not None:
            result = result[-limit:]
        return result

    def __len__(self) -> int:
        return len(self._traces)

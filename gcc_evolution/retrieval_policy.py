"""
GCC v5.405 — Agentic Retrieval Interface (IRS-004)

Apache 2.0 — open-source interface layer.
The retrieval decision strategy (counterfactual IC scoring, adaptive thresholds)
is private (BUSL 1.1).

Theory grounding (arXiv:2601.12538 — Agentic RAG):
    "Unlike static RAG, agentic RAG decides WHEN and WHAT to retrieve."

    Current GCC L2 Retrieval is passive: it executes the full retrieval
    pipeline on every inference, regardless of whether retrieval is needed.
    This causes two problems:
        1. Wasted compute on repeated patterns that are already cached
        2. Inability to dynamically adjust retrieval depth based on uncertainty

    IRS-004 adds a "retrieval decision gate" at the L2 entry point.
    Before retrieving, the gate evaluates three strategies:

        FORCE     — always retrieve (new signal, first run, high-stakes decision)
        CONDITION — retrieve only when uncertainty exceeds threshold
        SKIP      — use cached result (repeated pattern, low uncertainty)

    The strategy choice is itself learnable: the private engine optimizes
    the gate policy using counterfactual IC estimation:
        IC_with_retrieval  − IC_without_retrieval → retrieval value signal

    Acceptance criteria (IRS-004):
        - Retrieval calls reduced by ≥ 30%
        - Retrieval relevance NDCG@5 improved by ≥ 15%
        - Conditional retrieval trigger accuracy > 75%

Open-core boundary:
    Apache 2.0 (this file):
        - RetrievalStrategy enum (FORCE / CONDITION / SKIP)
        - RetrievalRequest / RetrievalResult dataclasses
        - RetrievalGate abstract base class
        - CounterfactualEstimate dataclass
        - SimpleThresholdGate — rule-based reference implementation
        - RetrievalStats — aggregate metrics tracker

    BUSL 1.1 (private engine):
        - KNN-based gate that learns optimal strategy from IC history
        - Counterfactual IC estimation pipeline
        - DuckDB persistence of retrieval decisions
        - NDCG@5 computation and Dashboard reporting

Usage::

    from gcc_evolution.retrieval_policy import (
        RetrievalStrategy, RetrievalRequest, RetrievalGate,
        SimpleThresholdGate,
    )

    gate = SimpleThresholdGate(uncertainty_threshold=0.5)

    req = RetrievalRequest(
        query="TSLA breakout signal",
        context={"is_new_signal": True, "uncertainty": 0.3, "symbol": "TSLA"},
        session_id="sess_001",
    )

    decision = gate.decide(req)
    print(decision.strategy)   # FORCE / CONDITION / SKIP

    if decision.strategy != RetrievalStrategy.SKIP:
        results = my_retriever.search(req.query, top_k=decision.top_k)
        gate.record_outcome(decision, results_ic=0.07)
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
# Enumerations
# ═══════════════════════════════════════════════════════════════════

class RetrievalStrategy(str, Enum):
    """
    Three retrieval strategies for the L2 Agentic RAG gate.

    FORCE:     Always retrieve — used for new signals, first-time patterns,
               high-stakes decisions, or when uncertainty is very high.
    CONDITION: Retrieve only when uncertainty exceeds a learned threshold.
               The private engine computes uncertainty from KNN distance.
    SKIP:      Use cached result — repeated pattern within session,
               low uncertainty, or recent retrieval already covered this.
    """
    FORCE     = "force"
    CONDITION = "condition"
    SKIP      = "skip"


class RetrievalTrigger(str, Enum):
    """Why this retrieval decision was made (for audit trail)."""
    NEW_SIGNAL       = "new_signal"       # First time seeing this pattern
    HIGH_UNCERTAINTY = "high_uncertainty" # Uncertainty above threshold
    HIGH_STAKES      = "high_stakes"      # Critical decision (e.g. large position)
    CACHE_HIT        = "cache_hit"        # Recent retrieval already covers this
    REPEATED_PATTERN = "repeated_pattern" # Same context seen recently
    POLICY           = "policy"           # Private engine policy decision


# ═══════════════════════════════════════════════════════════════════
# Request / Decision / Result
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RetrievalRequest:
    """
    A retrieval request arriving at the L2 gate.

    query:      semantic query string for the retrieval system
    context:    current system state (symbol, regime, uncertainty, etc.)
    session_id: current session identifier (for cache invalidation)
    top_k:      maximum number of results to retrieve (default 5)
    is_new_signal: hint — True forces FORCE strategy
    uncertainty:   caller's estimate of current decision uncertainty (0–1)
    stakes:        importance of this decision (0–1, higher = more likely FORCE)
    requested_at:  ISO timestamp
    """
    query:         str
    context:       dict  = field(default_factory=dict)
    session_id:    str   = ""
    top_k:         int   = 5
    is_new_signal: bool  = False
    uncertainty:   float = 0.5
    stakes:        float = 0.5
    requested_at:  str   = field(default_factory=_now)


@dataclass
class RetrievalDecision:
    """
    The gate's decision: whether and how to retrieve.

    strategy:    FORCE / CONDITION / SKIP
    trigger:     why this decision was made
    top_k:       how many results to fetch (0 if SKIP)
    cache_key:   key to use for cache lookup / storage
    reason:      human-readable explanation
    confidence:  gate's confidence in this decision (0–1)
    decided_at:  ISO timestamp
    """
    strategy:    RetrievalStrategy
    trigger:     RetrievalTrigger
    top_k:       int   = 5
    cache_key:   str   = ""
    reason:      str   = ""
    confidence:  float = 1.0
    decided_at:  str   = field(default_factory=_now)

    def should_retrieve(self) -> bool:
        return self.strategy != RetrievalStrategy.SKIP

    def to_dict(self) -> dict:
        return {
            "strategy":   self.strategy.value,
            "trigger":    self.trigger.value,
            "top_k":      self.top_k,
            "cache_key":  self.cache_key,
            "reason":     self.reason,
            "confidence": self.confidence,
            "decided_at": self.decided_at,
        }


@dataclass
class CounterfactualEstimate:
    """
    Estimated IC value of retrieving vs. not retrieving.

    Used by the private engine to optimize the gate policy.
    The private engine computes these via walk-forward IC regression.

    ic_with:    estimated IC when retrieval is used
    ic_without: estimated IC when retrieval is skipped (cache / fallback)
    delta:      ic_with - ic_without (retrieval value signal)
    confidence: estimation confidence
    """
    ic_with:    float
    ic_without: float
    confidence: float = 0.5

    @property
    def delta(self) -> float:
        return self.ic_with - self.ic_without

    @property
    def retrieval_is_beneficial(self) -> bool:
        return self.delta > 0


# ═══════════════════════════════════════════════════════════════════
# RetrievalGate — abstract base
# ═══════════════════════════════════════════════════════════════════

class RetrievalGate(ABC):
    """
    Abstract base for the L2 retrieval decision gate.

    Open-source contract (Apache 2.0).  Implement this to replace the
    default rule-based gate with a learned policy.

    The private KNN gate subclasses this and:
        1. Uses embedding distance to compute uncertainty
        2. Learns strategy → IC mapping via walk-forward optimization
        3. Updates gate weights via on_outcome() callback
        4. Persists decisions to DuckDB for Dashboard reporting

    Subclass must implement:
        decide(request) → RetrievalDecision

    Optional override:
        on_outcome(decision, results_ic) — called after retrieval completes
            (private engine uses this to update counterfactual IC estimates)
    """

    @abstractmethod
    def decide(self, request: RetrievalRequest) -> RetrievalDecision:
        """
        Decide the retrieval strategy for this request.

        Called at the L2 entry point before any retrieval is performed.
        Must be fast (< 10ms) as it runs on every inference.
        """

    def on_outcome(
        self,
        decision: RetrievalDecision,
        results_ic: float | None = None,
        counterfactual: CounterfactualEstimate | None = None,
    ) -> None:
        """
        Receive retrieval outcome feedback.

        Called after the retrieval (or cache hit) completes and the
        downstream signal IC is measured.

        Default: log only.  Private engine updates KNN gate weights here.
        """
        logger.debug(
            "[RETRIEVAL_GATE] outcome strategy=%s ic=%s",
            decision.strategy.value,
            f"{results_ic:.4f}" if results_ic is not None else "n/a",
        )


# ═══════════════════════════════════════════════════════════════════
# SimpleThresholdGate — rule-based reference implementation
# ═══════════════════════════════════════════════════════════════════

class SimpleThresholdGate(RetrievalGate):
    """
    Rule-based retrieval gate — reference implementation.

    Decision rules (evaluated in order):
        1. is_new_signal → FORCE (new pattern, must retrieve)
        2. uncertainty > force_threshold → FORCE (too uncertain, must retrieve)
        3. stakes > stakes_threshold → FORCE (high-stakes decision)
        4. uncertainty < skip_threshold → SKIP (confident, use cache)
        5. otherwise → CONDITION (retrieve conditionally)

    Open-source (Apache 2.0).  The private engine replaces this with
    a learned KNN policy.  The rules here serve as a sensible baseline
    and a reference for understanding the private policy's behavior.

    Args:
        force_threshold: uncertainty above this → FORCE (default 0.7)
        skip_threshold:  uncertainty below this → SKIP  (default 0.3)
        stakes_threshold: stakes above this → FORCE     (default 0.8)
    """

    def __init__(
        self,
        force_threshold:  float = 0.7,
        skip_threshold:   float = 0.3,
        stakes_threshold: float = 0.8,
    ):
        if skip_threshold >= force_threshold:
            raise ValueError(
                f"skip_threshold ({skip_threshold}) must be < force_threshold ({force_threshold})"
            )
        self.force_threshold  = force_threshold
        self.skip_threshold   = skip_threshold
        self.stakes_threshold = stakes_threshold
        self._stats = RetrievalStats()

    def decide(self, request: RetrievalRequest) -> RetrievalDecision:
        u = request.uncertainty
        s = request.stakes

        # Rule 1: new signal → always retrieve
        if request.is_new_signal:
            decision = RetrievalDecision(
                strategy=RetrievalStrategy.FORCE,
                trigger=RetrievalTrigger.NEW_SIGNAL,
                top_k=request.top_k,
                reason="New signal pattern — retrieval required",
                confidence=1.0,
            )

        # Rule 2: very high uncertainty → force retrieve
        elif u > self.force_threshold:
            decision = RetrievalDecision(
                strategy=RetrievalStrategy.FORCE,
                trigger=RetrievalTrigger.HIGH_UNCERTAINTY,
                top_k=request.top_k,
                reason=f"Uncertainty {u:.2f} > force threshold {self.force_threshold}",
                confidence=0.9,
            )

        # Rule 3: high stakes → force retrieve
        elif s > self.stakes_threshold:
            decision = RetrievalDecision(
                strategy=RetrievalStrategy.FORCE,
                trigger=RetrievalTrigger.HIGH_STAKES,
                top_k=request.top_k,
                reason=f"Stakes {s:.2f} > stakes threshold {self.stakes_threshold}",
                confidence=0.85,
            )

        # Rule 4: low uncertainty → skip (use cache)
        elif u < self.skip_threshold:
            decision = RetrievalDecision(
                strategy=RetrievalStrategy.SKIP,
                trigger=RetrievalTrigger.CACHE_HIT,
                top_k=0,
                reason=f"Uncertainty {u:.2f} < skip threshold {self.skip_threshold} — use cache",
                confidence=0.8,
            )

        # Rule 5: moderate uncertainty → conditional
        else:
            decision = RetrievalDecision(
                strategy=RetrievalStrategy.CONDITION,
                trigger=RetrievalTrigger.POLICY,
                top_k=request.top_k,
                reason=f"Uncertainty {u:.2f} in conditional band [{self.skip_threshold}, {self.force_threshold}]",
                confidence=0.7,
            )

        self._stats.record(decision)
        logger.debug("[RETRIEVAL_GATE] %s → %s (%s)", request.query[:40], decision.strategy.value, decision.reason)
        return decision

    @property
    def stats(self) -> "RetrievalStats":
        return self._stats


# ═══════════════════════════════════════════════════════════════════
# RetrievalStats — aggregate metrics tracker
# ═══════════════════════════════════════════════════════════════════

class RetrievalStats:
    """
    Tracks retrieval gate decisions for performance monitoring.

    Provides the raw metrics needed to validate IRS-004 acceptance criteria:
        - skip_rate ≥ 30% reduction in retrieval calls
        - force/condition trigger accuracy (computed externally from IC outcomes)

    Open-source (Apache 2.0).  The private engine additionally computes
    NDCG@5 per retrieved set and persists stats to DuckDB.
    """

    def __init__(self):
        self._counts: dict[str, int] = {s.value: 0 for s in RetrievalStrategy}
        self._total = 0

    def record(self, decision: RetrievalDecision) -> None:
        self._counts[decision.strategy.value] += 1
        self._total += 1

    @property
    def total(self) -> int:
        return self._total

    def rate(self, strategy: RetrievalStrategy) -> float:
        if self._total == 0:
            return 0.0
        return self._counts[strategy.value] / self._total

    @property
    def skip_rate(self) -> float:
        return self.rate(RetrievalStrategy.SKIP)

    @property
    def force_rate(self) -> float:
        return self.rate(RetrievalStrategy.FORCE)

    @property
    def condition_rate(self) -> float:
        return self.rate(RetrievalStrategy.CONDITION)

    def summary(self) -> dict:
        return {
            "total":          self._total,
            "force_rate":     round(self.force_rate, 4),
            "condition_rate": round(self.condition_rate, 4),
            "skip_rate":      round(self.skip_rate, 4),
            "retrieval_rate": round(1 - self.skip_rate, 4),
        }


# ═══════════════════════════════════════════════════════════════════
# CounterfactualEvaluator — IRS-004 S6 (反事实IC评估作为决策奖励)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RetrievalOutcome:
    """
    Records the IC outcome of one retrieval decision.

    decision:     the gate's RetrievalDecision
    ic_observed:  IC measured after using this retrieval result
    ic_baseline:  IC measured when retrieval was skipped (EMA baseline)
    symbol:       trading symbol for this outcome
    window_id:    walk-forward window identifier
    recorded_at:  ISO timestamp
    """
    decision:    RetrievalDecision
    ic_observed: float
    ic_baseline: float
    symbol:      str = ""
    window_id:   str = ""
    recorded_at: str = field(default_factory=_now)

    @property
    def ic_delta(self) -> float:
        """IC improvement from retrieval vs. baseline (reward signal)."""
        return self.ic_observed - self.ic_baseline

    def to_estimate(self) -> CounterfactualEstimate:
        return CounterfactualEstimate(
            ic_with=self.ic_observed,
            ic_without=self.ic_baseline,
            confidence=min(1.0, max(0.0, 0.5 + abs(self.ic_delta) * 5)),
        )


class CounterfactualEvaluator:
    """
    Estimates the IC value of retrieval decisions using counterfactual comparison.

    IRS-004 S6: 反事实IC评估作为决策奖励
    Theory (arXiv:2601.12538): counterfactual rewards prevent the gate
    from exploiting spurious correlations in the retrieved context.

    Design:
        baseline_ic = exponential moving average of IC when retrieval was SKIPPED
        reward_t    = ic_with_retrieval_t − baseline_ic   (counterfactual delta)

        Positive reward → retrieval helped → gate should prefer FORCE/CONDITION
        Negative reward → retrieval hurt   → gate should prefer SKIP

    The private engine feeds these rewards into the KNN gate policy update.
    This open-source class provides the estimation interface and aggregation.

    Open-source (Apache 2.0).  Private engine uses this to drive gate learning.

    Args:
        baseline_alpha: EMA decay for baseline IC (default 0.1, slow-moving)
        min_samples:    minimum outcomes before estimates are reliable (default 10)
    """

    def __init__(self, baseline_alpha: float = 0.1, min_samples: int = 10):
        if not 0 < baseline_alpha < 1:
            raise ValueError(f"baseline_alpha must be in (0, 1), got {baseline_alpha}")
        self.baseline_alpha = baseline_alpha
        self.min_samples    = min_samples
        self._baseline_ic:  float | None        = None
        self._outcomes:     list[RetrievalOutcome] = []

    def update_baseline(self, ic: float) -> None:
        """
        Update the skip-IC baseline with a new observation.

        Call this after every SKIP decision with the resulting IC.
        The EMA slowly tracks the "no-retrieval" performance floor.
        """
        if self._baseline_ic is None:
            self._baseline_ic = ic
        else:
            self._baseline_ic = (
                self.baseline_alpha * ic
                + (1 - self.baseline_alpha) * self._baseline_ic
            )
        logger.debug("[CF_EVAL] baseline_ic updated → %.4f", self._baseline_ic)

    def record_outcome(
        self,
        decision: RetrievalDecision,
        ic_observed: float,
        symbol: str = "",
        window_id: str = "",
    ) -> RetrievalOutcome:
        """
        Record the IC outcome of a retrieval decision.

        Args:
            decision:    the RetrievalDecision that was made
            ic_observed: IC measured in the walk-forward window after this decision
            symbol:      trading symbol
            window_id:   walk-forward window identifier

        Returns:
            RetrievalOutcome with ic_delta computed against current baseline
        """
        baseline = self._baseline_ic if self._baseline_ic is not None else 0.0

        # If this was a SKIP, update baseline with observed IC
        if decision.strategy == RetrievalStrategy.SKIP:
            self.update_baseline(ic_observed)

        outcome = RetrievalOutcome(
            decision=decision,
            ic_observed=ic_observed,
            ic_baseline=baseline,
            symbol=symbol,
            window_id=window_id,
        )
        self._outcomes.append(outcome)
        logger.debug(
            "[CF_EVAL] strategy=%s ic_obs=%.4f baseline=%.4f delta=%.4f",
            decision.strategy.value, ic_observed, baseline, outcome.ic_delta,
        )
        return outcome

    def reward_for_strategy(self, strategy: RetrievalStrategy) -> float | None:
        """
        Mean counterfactual IC delta for a given strategy.

        Returns None if fewer than min_samples outcomes are available.
        Used by the private KNN gate to update strategy preference weights.
        """
        relevant = [o for o in self._outcomes if o.decision.strategy == strategy]
        if len(relevant) < self.min_samples:
            return None
        return sum(o.ic_delta for o in relevant) / len(relevant)

    def is_retrieval_beneficial(self, strategy: RetrievalStrategy = RetrievalStrategy.FORCE) -> bool | None:
        """
        Returns True if the given strategy has positive mean IC delta.
        Returns None when insufficient data.
        """
        reward = self.reward_for_strategy(strategy)
        if reward is None:
            return None
        return reward > 0

    def summary(self) -> dict:
        """
        Aggregate counterfactual IC statistics per strategy.

        Returns per-strategy mean IC delta and whether retrieval is beneficial.
        IRS-004 acceptance: conditional retrieval trigger accuracy > 75%.
        """
        result: dict = {
            "total_outcomes": len(self._outcomes),
            "baseline_ic":    round(self._baseline_ic, 6) if self._baseline_ic is not None else None,
            "strategies":     {},
        }
        for strategy in RetrievalStrategy:
            reward = self.reward_for_strategy(strategy)
            count  = sum(1 for o in self._outcomes if o.decision.strategy == strategy)
            result["strategies"][strategy.value] = {
                "count":       count,
                "mean_delta":  round(reward, 6) if reward is not None else None,
                "beneficial":  self.is_retrieval_beneficial(strategy),
            }
        return result

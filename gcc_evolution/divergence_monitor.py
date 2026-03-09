"""
GCC v5.340 — Multi-Agent Divergence Monitor (IRS-007)

Apache 2.0 — open-source interface layer.
The private engine integrates Fleiss Kappa into the three-way voting
cycle and manages perturbation scheduling (BUSL 1.1).

Theory grounding (Human-AI Handoff Theorem, Brenner et al. 2026):
    "A system where AI/Human always agree is not providing independent
     verification — it is providing confirmation bias."

    GCC uses three-way voting: AI signal, Human rule, Technical indicator.
    When all three always agree, information cascade is occurring:
        - The system behaves as if there is one voter, not three
        - Novel market regimes trigger no divergence = detection failure
        - Overfitting to a narrow consensus view degrades generalization

    IRS-007 monitors the *divergence rate* of the three-way vote.
    Metric: Fleiss's Kappa (κ) over a rolling window of decisions.

    κ = (P̄ − P̄_e) / (1 − P̄_e)
    where P̄ = mean observed agreement, P̄_e = expected agreement by chance.

    Interpretation:
        κ > 0.7  → high agreement (normal/expected)
        0.3 ≤ κ ≤ 0.7 → moderate agreement (healthy divergence exists)
        κ < 0.3  → low agreement OR near-zero agreement (homogenization alert)

    IRS-007 acceptance: normal market Fleiss Kappa in [0.3, 0.7].

Open-core boundary:
    Apache 2.0 (this file):
        - VoteRecord dataclass (one three-way vote event)
        - FleissKappaCalculator: compute κ from vote history
        - DivergenceMonitor: sliding-window κ tracker + alert threshold
        - PerturbationLog: track divergence response to injected perturbations

    BUSL 1.1 (private engine):
        - Perturbation scheduler (when and how to inject test disagreements)
        - Information cascade detection algorithm
        - Dashboard κ time-series visualization
        - Automatic alert via Slack/email when κ < 0.3

Usage::

    from gcc_evolution.divergence_monitor import DivergenceMonitor, VoteRecord

    monitor = DivergenceMonitor(window_size=50, alert_threshold=0.3)

    # After each three-way vote:
    vote = VoteRecord(
        ai_vote="BUY",
        human_vote="HOLD",
        technical_vote="BUY",
        symbol="TSLA",
        market_regime="trending_up",
    )
    monitor.record(vote)

    kappa = monitor.kappa
    if monitor.is_homogenized:
        print(f"[IRS-007] Homogenization detected: κ={kappa:.3f}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class VoteRecord:
    """
    One three-way voting event.

    ai_vote:        AI signal vote (e.g. "BUY" / "SELL" / "HOLD")
    human_vote:     Human rule vote
    technical_vote: Technical indicator vote
    symbol:         trading symbol
    market_regime:  market regime at vote time
    voted_at:       ISO timestamp
    """
    ai_vote:        str
    human_vote:     str
    technical_vote: str
    symbol:         str = ""
    market_regime:  str = ""
    voted_at:       str = field(default_factory=_now)

    @property
    def votes(self) -> list[str]:
        return [self.ai_vote, self.human_vote, self.technical_vote]

    @property
    def is_unanimous(self) -> bool:
        """True when all three voters agree."""
        return len(set(self.votes)) == 1

    @property
    def n_unique(self) -> int:
        """Number of distinct vote values."""
        return len(set(self.votes))


@dataclass
class PerturbationRecord:
    """
    Record of one injected perturbation test.

    A perturbation forces one voter to disagree, then measures whether
    the system correctly distinguishes the minority opinion from noise.

    perturbed_voter:  which voter was overridden ("ai" / "human" / "technical")
    original_vote:    the voter's natural vote
    injected_vote:    the artificially different vote
    system_responded: True when the system produced a different outcome
                      (i.e. the perturbation was detected / acted upon)
    symbol:           trading symbol
    tested_at:        ISO timestamp
    """
    perturbed_voter:  str
    original_vote:    str
    injected_vote:    str
    system_responded: bool = False
    symbol:           str  = ""
    tested_at:        str  = field(default_factory=_now)


# ═══════════════════════════════════════════════════════════════════
# FleissKappaCalculator — κ from vote history (S61~S62)
# ═══════════════════════════════════════════════════════════════════

class FleissKappaCalculator:
    """
    Compute Fleiss's Kappa for a set of vote records.

    Assumes 3 raters (AI / Human / Technical) with categorical votes.
    Kappa is computed over a provided list of VoteRecord objects.

    κ = (P̄ − P̄_e) / (1 − P̄_e)

    P̄:   mean proportion of agreeing pairs per subject
    P̄_e: expected agreement by chance (based on marginal distributions)

    Open-source (Apache 2.0).  IRS-007 acceptance: κ in [0.3, 0.7]
    for normal market sessions.
    """

    N_RATERS = 3   # AI, Human, Technical

    @classmethod
    def compute(cls, records: list[VoteRecord]) -> float:
        """
        Compute Fleiss's Kappa over the given vote records.

        Returns κ in [-1, 1]; returns 0.0 if records is empty or all agree.
        """
        if not records:
            return 0.0

        n = len(records)                  # number of subjects (decisions)
        k = cls.N_RATERS                  # raters per subject
        categories: set[str] = set()

        for rec in records:
            categories.update(rec.votes)

        if len(categories) <= 1:
            return 1.0   # perfect agreement by construction

        cats = sorted(categories)

        # n_ij[i][j] = number of raters who assigned category j to subject i
        n_ij: list[dict[str, int]] = []
        for rec in records:
            counts: dict[str, int] = {c: 0 for c in cats}
            for v in rec.votes:
                counts[v] = counts.get(v, 0) + 1
            n_ij.append(counts)

        # P_i = proportion of agreeing pairs for subject i
        # P_i = (1 / (k*(k-1))) * Σ_j n_ij*(n_ij - 1)
        p_bar = sum(
            sum(counts[c] * (counts[c] - 1) for c in cats)
            / (k * (k - 1))
            for counts in n_ij
        ) / n

        # p_j = marginal proportion of category j across all raters
        total_ratings = n * k
        p_e_bar = sum(
            (sum(counts[c] for counts in n_ij) / total_ratings) ** 2
            for c in cats
        )

        denom = 1 - p_e_bar
        if abs(denom) < 1e-12:
            return 1.0   # degenerate case: all chance agreement = 1

        return (p_bar - p_e_bar) / denom


# ═══════════════════════════════════════════════════════════════════
# DivergenceMonitor — sliding-window κ + homogenization alert (S62~S65)
# ═══════════════════════════════════════════════════════════════════

class DivergenceMonitor:
    """
    Tracks Fleiss Kappa over a rolling window of three-way vote records.

    IRS-007 S62: sets alert threshold — κ < 0.3 triggers homogenization alert.
    IRS-007 S64: tracks per-market-regime mean κ history.
    IRS-007 S65: logs homogenization events with root cause analysis.

    Args:
        window_size:     number of recent votes to compute κ over (default 50)
        alert_threshold: κ below this → homogenization alert (default 0.3)
        target_max:      κ above this → may indicate suppressed divergence (default 0.7)
    """

    def __init__(
        self,
        window_size:     int   = 50,
        alert_threshold: float = 0.3,
        target_max:      float = 0.7,
    ):
        self.window_size     = window_size
        self.alert_threshold = alert_threshold
        self.target_max      = target_max
        self._records: list[VoteRecord] = []
        self._homogenization_events: list[dict] = []  # capped at 1000
        self._max_events = 1000

    def record(self, vote: VoteRecord) -> float:
        """
        Record one vote and return current Fleiss Kappa.

        Triggers homogenization alert if κ < alert_threshold.
        """
        self._records.append(vote)
        if len(self._records) > self.window_size:
            self._records = self._records[-self.window_size:]

        kappa = self.kappa

        if kappa < self.alert_threshold and len(self._records) >= 5:
            event = {
                "kappa":        kappa,
                "n_records":    len(self._records),
                "unanimous_rate": self.unanimous_rate,
                "detected_at":  _now(),
            }
            self._homogenization_events.append(event)
            if len(self._homogenization_events) > self._max_events:
                self._homogenization_events = self._homogenization_events[-self._max_events:]
            logger.warning(
                "[IRS-007] Homogenization detected: κ=%.3f < threshold=%.2f "
                "(unanimous_rate=%.1f%%)",
                kappa, self.alert_threshold, self.unanimous_rate * 100,
            )

        return kappa

    @property
    def kappa(self) -> float:
        """Current Fleiss Kappa over the sliding window."""
        return FleissKappaCalculator.compute(self._records)

    @property
    def is_homogenized(self) -> bool:
        """True when current κ is below the alert threshold."""
        return len(self._records) >= 5 and self.kappa < self.alert_threshold

    @property
    def unanimous_rate(self) -> float:
        """Fraction of votes where all three raters agreed."""
        if not self._records:
            return 0.0
        return sum(1 for r in self._records if r.is_unanimous) / len(self._records)

    def kappa_by_regime(self) -> dict[str, float]:
        """
        IRS-007 S64 — mean κ per market regime.

        Groups records by market_regime and computes κ independently.
        """
        regimes: dict[str, list[VoteRecord]] = {}
        for rec in self._records:
            regime = rec.market_regime or "unknown"
            regimes.setdefault(regime, []).append(rec)
        return {
            regime: FleissKappaCalculator.compute(recs)
            for regime, recs in regimes.items()
        }

    @property
    def homogenization_events(self) -> list[dict]:
        """History of detected homogenization events (IRS-007 S65)."""
        return list(self._homogenization_events)

    def report(self) -> dict:
        """Aggregate report for Dashboard."""
        return {
            "n_votes":             len(self._records),
            "kappa":               round(self.kappa, 4),
            "is_homogenized":      self.is_homogenized,
            "unanimous_rate":      round(self.unanimous_rate, 4),
            "alert_threshold":     self.alert_threshold,
            "target_range":        [self.alert_threshold, self.target_max],
            "homogenization_count": len(self._homogenization_events),
            "kappa_by_regime":     {
                k: round(v, 4) for k, v in self.kappa_by_regime().items()
            },
        }

    def __len__(self) -> int:
        return len(self._records)


# ═══════════════════════════════════════════════════════════════════
# PerturbationLog — divergence response tracking (S63)
# ═══════════════════════════════════════════════════════════════════

class PerturbationLog:
    """
    Tracks perturbation tests and measures system response rate.

    IRS-007 S63: periodically inject a forced disagreement and verify
    that the system does not suppress minority opinions.

    A successful perturbation test means the system:
        - Logged the disagreement (kappa changes)
        - Did NOT automatically override the minority voter

    Args:
        max_entries: sliding window size (default 200)
    """

    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self._entries: list[PerturbationRecord] = []

    def record(self, entry: PerturbationRecord) -> None:
        """Record one perturbation test result."""
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

    @property
    def response_rate(self) -> float:
        """Fraction of perturbations where the system responded correctly."""
        if not self._entries:
            return 0.0
        return sum(1 for e in self._entries if e.system_responded) / len(self._entries)

    def summary(self) -> dict:
        return {
            "n_tests":       len(self._entries),
            "response_rate": round(self.response_rate, 4),
        }

    def __len__(self) -> int:
        return len(self._entries)

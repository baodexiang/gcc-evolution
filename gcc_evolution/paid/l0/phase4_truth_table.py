"""Canonical paid L0 program: Phase 4 decision truth table with P003 acceptance scoring."""
from __future__ import annotations

from dataclasses import dataclass

from gcc.papers.formulas.P003_alphaforgebench import (
    eq_1_offline_pattern_score,
    eq_2_precision_recall_f1,
    eq_3_composite_benchmark_score,
)

from ..common import PaidBoundary


PHASE4_TRUTH_TABLE = PaidBoundary(
    "L0",
    "Paid",
    ("decision_truth_table", "truth replay", "acceptance audit"),
    "Phase 4 truth-table generation is paid.",
)

TRUTH_ACCEPTANCE_SPEC = {
    "version": "5.330",
    "paper": "P003_alphaforgebench",
    "fields": (
        "candidate_id",
        "pattern_score",
        "precision",
        "recall",
        "f1",
        "composite_score",
        "latency_ms",
        "latency_budget_ms",
        "accepted",
    ),
}


@dataclass(frozen=True)
class TruthTableRecord:
    candidate_id: str
    pattern_score: float
    precision: float
    recall: float
    f1: float
    composite_score: float
    latency_ms: float
    latency_budget_ms: float
    accepted: bool

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "pattern_score": self.pattern_score,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "composite_score": self.composite_score,
            "latency_ms": self.latency_ms,
            "latency_budget_ms": self.latency_budget_ms,
            "accepted": self.accepted,
        }


def build_truth_table_record(
    *,
    candidate_id: str,
    hit_rate: float,
    novelty: float,
    stability: float,
    tp: int,
    fp: int,
    fn: int,
    latency_ms: float,
    latency_budget_ms: float = 50.0,
    acceptance_threshold: float = 0.55,
) -> TruthTableRecord:
    """
    Build a Phase 4 acceptance record using P003 benchmark formulas.

    This turns P003 from a formula asset into a paid acceptance/truth-table entrypoint.
    """
    pattern_score = float(eq_1_offline_pattern_score(hit_rate=hit_rate, novelty=novelty, stability=stability))
    precision, recall, f1 = eq_2_precision_recall_f1(tp=tp, fp=fp, fn=fn)
    composite = float(
        eq_3_composite_benchmark_score(
            pattern_score=pattern_score,
            f1_score=f1,
            latency_ms=latency_ms,
            latency_budget_ms=latency_budget_ms,
        )
    )
    accepted = composite >= float(acceptance_threshold)
    return TruthTableRecord(
        candidate_id=str(candidate_id),
        pattern_score=pattern_score,
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        composite_score=composite,
        latency_ms=float(latency_ms),
        latency_budget_ms=float(latency_budget_ms),
        accepted=accepted,
    )


def build_truth_table_row(**kwargs) -> dict:
    """Return the canonical Phase 4 truth-table row payload."""
    return build_truth_table_record(**kwargs).to_dict()


__all__ = [
    "PHASE4_TRUTH_TABLE",
    "TRUTH_ACCEPTANCE_SPEC",
    "TruthTableRecord",
    "build_truth_table_record",
    "build_truth_table_row",
]

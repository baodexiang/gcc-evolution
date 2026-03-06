"""
Paper Formula Implementation: AlphaForgeBench
=============================================
Layer : Retrieval

Source mapping:
- Eq.(1): offline pattern discovery score
- Eq.(2): benchmark metric tuple (precision/recall/f1)
- Eq.(3): composite benchmark score
"""

from __future__ import annotations

import math
from typing import Tuple

BENCH_EPSILON: float = 1e-8


def _safe_div(numerator: float, denominator: float) -> float:
    d = float(denominator)
    if abs(d) <= BENCH_EPSILON:
        return 0.0
    return float(numerator) / d


def eq_1_offline_pattern_score(hit_rate: float, novelty: float, stability: float) -> float:
    """
    Eq.(1) offline pattern score.

    Weighted geometric aggregation with non-negative clamp.
    """
    h = max(0.0, float(hit_rate))
    n = max(0.0, float(novelty))
    s = max(0.0, float(stability))
    # Geometric blend to penalize weak dimensions.
    return (h * n * s) ** (1.0 / 3.0) if h > 0 and n > 0 and s > 0 else 0.0


def eq_2_precision_recall_f1(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    """
    Eq.(2) benchmark quality metrics.
    """
    tp_f = float(max(tp, 0))
    fp_f = float(max(fp, 0))
    fn_f = float(max(fn, 0))
    precision = _safe_div(tp_f, tp_f + fp_f)
    recall = _safe_div(tp_f, tp_f + fn_f)
    f1 = _safe_div(2.0 * precision * recall, precision + recall)
    return precision, recall, f1


def eq_3_composite_benchmark_score(
    pattern_score: float,
    f1_score: float,
    latency_ms: float,
    latency_budget_ms: float = 50.0,
) -> float:
    """
    Eq.(3) composite benchmark score.

    score = 0.6*pattern + 0.4*f1 - latency_penalty
    """
    p = max(0.0, float(pattern_score))
    f = max(0.0, float(f1_score))
    latency = max(0.0, float(latency_ms))
    budget = max(float(latency_budget_ms), BENCH_EPSILON)
    latency_penalty = max(0.0, (latency - budget) / budget)
    return 0.6 * p + 0.4 * f - latency_penalty


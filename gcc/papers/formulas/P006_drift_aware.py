"""
Paper Formula Implementation: History Is Not Enough (Drift-Aware Streaming)
============================================================================
Layer : Evolution

Source mapping:
- Eq.(1): STL residual term, Y_t = T_t + S_t + R_t
- Eq.(2): Population Stability Index (PSI)
- Eq.(3): KS-test statistic
- Eq.(4): adaptive window-size update
- Eq.(5): drift-threshold decision
"""

from __future__ import annotations

import math
from typing import Iterable, List

DRIFT_EPSILON: float = 1e-8


def eq_1_stl_residual(observed: float, trend: float, seasonal: float) -> float:
    """
    Eq.(1) STL decomposition residual.

    R_t = Y_t - T_t - S_t
    """
    return float(observed) - float(trend) - float(seasonal)


def eq_2_psi_score(actual_dist: Iterable[float], expected_dist: Iterable[float]) -> float:
    """
    Eq.(2) Population Stability Index.

    PSI = sum((A_i - E_i) * ln(A_i / E_i))
    """
    a = [max(float(x), 0.0) for x in actual_dist]
    e = [max(float(x), 0.0) for x in expected_dist]
    n = min(len(a), len(e))
    if n == 0:
        return 0.0
    score = 0.0
    for i in range(n):
        ai = max(a[i], DRIFT_EPSILON)
        ei = max(e[i], DRIFT_EPSILON)
        score += (ai - ei) * math.log(ai / ei)
    return max(0.0, score)


def _ecdf(sample: List[float], x: float) -> float:
    if not sample:
        return 0.0
    count = 0
    for v in sample:
        if v <= x:
            count += 1
    return count / len(sample)


def eq_3_ks_statistic(sample_a: Iterable[float], sample_b: Iterable[float]) -> float:
    """
    Eq.(3) Kolmogorov-Smirnov statistic.

    D = sup_x |F_a(x) - F_b(x)|
    """
    a = [float(x) for x in sample_a]
    b = [float(x) for x in sample_b]
    if not a or not b:
        return 0.0
    xs = sorted(set(a + b))
    d = 0.0
    for x in xs:
        d = max(d, abs(_ecdf(a, x) - _ecdf(b, x)))
    return d


def eq_4_adaptive_window_size(
    base_window: int,
    psi_score: float,
    ks_stat: float,
    min_window: int = 20,
    max_window: int = 500,
) -> int:
    """
    Eq.(4) adaptive window-size update.

    Larger drift signal -> smaller window for faster adaptation.
    """
    base = max(1, int(base_window))
    drift_strength = max(0.0, float(psi_score)) + max(0.0, float(ks_stat))
    factor = 1.0 / (1.0 + drift_strength)
    size = int(round(base * factor))
    return max(int(min_window), min(int(max_window), size))


def eq_5_drift_detected(
    psi_score: float,
    ks_stat: float,
    psi_threshold: float = 0.2,
    ks_threshold: float = 0.1,
) -> bool:
    """
    Eq.(5) drift-threshold decision logic.
    """
    return (float(psi_score) >= float(psi_threshold)) or (float(ks_stat) >= float(ks_threshold))


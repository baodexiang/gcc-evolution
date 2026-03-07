"""
Paper Formula Implementation: Drift-Aware Streaming
====================================================
Layer : Evolution

Source mapping:
- Eq.(1): STL trend component (EWMA-based level extraction)
- Eq.(2): PSI (Population Stability Index) — distribution drift score
- Eq.(3): KS-test statistic (empirical CDF max divergence)
- Eq.(4): adaptive window size (shrinks under drift pressure)
- Eq.(5): drift threshold (PSI + KS composite gate)
"""

from __future__ import annotations

import math
from typing import List, Sequence

DRIFT_EPSILON: float = 1e-8
PSI_DRIFT_THRESHOLD: float = 0.2   # standard PSI warning level
KS_DRIFT_THRESHOLD: float = 0.1    # KS statistic drift threshold
WINDOW_MIN: int = 10
WINDOW_MAX: int = 500


def eq_1_stl_trend(series: Sequence[float], alpha: float = 0.3) -> float:
    """
    Eq.(1) EWMA-based trend level estimate.

    level_t = alpha * x_t + (1 - alpha) * level_{t-1}
    Returns final level after processing the full series.
    """
    if not series:
        return 0.0
    a = max(DRIFT_EPSILON, min(1.0, float(alpha)))
    level = float(series[0])
    for x in series[1:]:
        level = a * float(x) + (1.0 - a) * level
    return level


def eq_2_psi(
    expected: Sequence[float],
    actual: Sequence[float],
    n_bins: int = 10,
) -> float:
    """
    Eq.(2) Population Stability Index.

    PSI = sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))
    Uses equal-width binning over the union range.
    """
    exp = [float(x) for x in expected]
    act = [float(x) for x in actual]
    if not exp or not act:
        return 0.0
    lo = min(min(exp), min(act))
    hi = max(max(exp), max(act))
    if abs(hi - lo) <= DRIFT_EPSILON:
        return 0.0
    bins = n_bins
    width = (hi - lo) / bins

    def _bin_counts(data: List[float]) -> List[int]:
        counts = [0] * bins
        for v in data:
            idx = int((v - lo) / width)
            idx = min(idx, bins - 1)
            counts[idx] += 1
        return counts

    exp_counts = _bin_counts(exp)
    act_counts = _bin_counts(act)
    n_exp = max(len(exp), 1)
    n_act = max(len(act), 1)
    psi = 0.0
    for e, a in zip(exp_counts, act_counts):
        ep = max(e / n_exp, DRIFT_EPSILON)
        ap = max(a / n_act, DRIFT_EPSILON)
        psi += (ap - ep) * math.log(ap / ep)
    return max(0.0, psi)


def eq_3_ks_statistic(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
) -> float:
    """
    Eq.(3) Kolmogorov-Smirnov statistic.

    D = max|F_a(x) - F_b(x)| over all x in the union of both samples.
    """
    if not sample_a or not sample_b:
        return 0.0
    sa = sorted(float(x) for x in sample_a)
    sb = sorted(float(x) for x in sample_b)
    all_points = sorted(set(sa + sb))
    na, nb = len(sa), len(sb)

    def _ecdf(sorted_sample: List[float], x: float) -> float:
        lo, hi = 0, len(sorted_sample)
        while lo < hi:
            mid = (lo + hi) // 2
            if sorted_sample[mid] <= x:
                lo = mid + 1
            else:
                hi = mid
        return lo / len(sorted_sample)

    d_max = 0.0
    for x in all_points:
        diff = abs(_ecdf(sa, x) - _ecdf(sb, x))
        if diff > d_max:
            d_max = diff
    return d_max


def eq_4_adaptive_window(
    base_window: int,
    psi: float,
    ks: float,
) -> int:
    """
    Eq.(4) Adaptive window size.

    window = base_window / (1 + drift_pressure)
    drift_pressure = psi / PSI_DRIFT_THRESHOLD + ks / KS_DRIFT_THRESHOLD
    Clamped to [WINDOW_MIN, base_window].
    """
    pressure = psi / max(PSI_DRIFT_THRESHOLD, DRIFT_EPSILON) + ks / max(KS_DRIFT_THRESHOLD, DRIFT_EPSILON)
    shrunk = int(base_window / (1.0 + max(0.0, pressure)))
    return max(WINDOW_MIN, min(base_window, shrunk))


def eq_5_drift_detected(psi: float, ks: float) -> bool:
    """
    Eq.(5) Composite drift gate.

    Drift flagged when PSI >= PSI_DRIFT_THRESHOLD OR KS >= KS_DRIFT_THRESHOLD.
    """
    return psi >= PSI_DRIFT_THRESHOLD or ks >= KS_DRIFT_THRESHOLD

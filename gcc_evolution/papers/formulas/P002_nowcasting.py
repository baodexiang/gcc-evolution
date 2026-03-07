"""
Paper Formula Implementation: Chen & Pu Nowcasting
==================================================
Layer : Orchestration

Source mapping:
- Eq.(1): real-time state estimate (EWMA nowcast)
- Eq.(2): multi-signal fusion weights (softmax-normalized)
- Eq.(3): confidence interval estimate (normal approximation)
"""

from __future__ import annotations

import math
from typing import Iterable, List, Tuple

NOWCAST_EPSILON: float = 1e-8
Z_95: float = 1.96


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def eq_1_realtime_state_estimate(prev_state: float, observation: float, alpha: float) -> float:
    """
    Eq.(1) real-time nowcast update.

    state_t = alpha * obs_t + (1 - alpha) * state_{t-1}
    """
    a = _clamp01(alpha)
    return a * float(observation) + (1.0 - a) * float(prev_state)


def eq_2_fusion_weights(signal_scores: Iterable[float], temperature: float = 1.0) -> List[float]:
    """
    Eq.(2) multi-signal fusion weight calculation.

    softmax(score / temperature), normalized to sum=1.
    """
    scores = [float(s) for s in signal_scores]
    if not scores:
        return []
    temp = max(float(temperature), NOWCAST_EPSILON)
    scaled = [s / temp for s in scores]
    pivot = max(scaled)
    exps = [math.exp(s - pivot) for s in scaled]
    denom = sum(exps)
    if denom <= NOWCAST_EPSILON:
        return [1.0 / len(scores)] * len(scores)
    return [e / denom for e in exps]


def eq_3_confidence_interval(
    mean: float,
    variance: float,
    sample_size: int,
    z_score: float = Z_95,
) -> Tuple[float, float]:
    """
    Eq.(3) confidence interval (normal approximation).

    CI = mean ± z * sqrt(variance / n)
    """
    n = max(int(sample_size), 1)
    var = max(float(variance), 0.0)
    z = abs(float(z_score))
    margin = z * math.sqrt(var / n)
    m = float(mean)
    return (m - margin, m + margin)


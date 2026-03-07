"""
Paper Formula Implementation: Prompt Repetition
===============================================
Layer : Orchestration

Source mapping:
- Eq.(1): repetition-count to performance gain curve
- Eq.(2): optimal repetition count estimate by maximizing utility
"""

from __future__ import annotations

import math

REP_EPSILON: float = 1e-8


def eq_1_repetition_performance_gain(
    repetition_count: int,
    max_gain: float = 1.0,
    decay_rate: float = 0.35,
) -> float:
    """
    Eq.(1) diminishing-return gain curve.

    gain(n) = max_gain * (1 - exp(-decay_rate * n))
    """
    n = max(0, int(repetition_count))
    mg = max(0.0, float(max_gain))
    rate = max(float(decay_rate), REP_EPSILON)
    return mg * (1.0 - math.exp(-rate * n))


def eq_2_optimal_repetition_count(
    max_search: int = 12,
    max_gain: float = 1.0,
    decay_rate: float = 0.35,
    cost_per_repeat: float = 0.05,
) -> int:
    """
    Eq.(2) utility-maximizing repetition count.

    utility(n) = gain(n) - n * cost_per_repeat
    """
    upper = max(1, int(max_search))
    cost = max(0.0, float(cost_per_repeat))
    best_n = 0
    best_u = -1e18
    for n in range(upper + 1):
        g = eq_1_repetition_performance_gain(
            repetition_count=n,
            max_gain=max_gain,
            decay_rate=decay_rate,
        )
        u = g - n * cost
        if u > best_u:
            best_u = u
            best_n = n
    return best_n


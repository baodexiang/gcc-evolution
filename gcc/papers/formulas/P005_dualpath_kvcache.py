"""
Paper Formula Implementation: DualPath KV-Cache
===============================================
Layer : Data

Source mapping:
- Eq.(1): dual-path allocation ratio
- Eq.(2): cache hit-rate optimization objective
- Eq.(3): inference latency estimate
"""

from __future__ import annotations

KV_EPSILON: float = 1e-8


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def eq_1_dualpath_allocation_ratio(hot_score: float, cold_score: float) -> float:
    """
    Eq.(1) hot-path allocation ratio.

    ratio_hot = hot / (hot + cold)
    """
    h = max(0.0, float(hot_score))
    c = max(0.0, float(cold_score))
    denom = h + c
    if denom <= KV_EPSILON:
        return 0.5
    return _clamp01(h / denom)


def eq_2_cache_hit_objective(hit_rate_hot: float, hit_rate_cold: float, ratio_hot: float) -> float:
    """
    Eq.(2) weighted cache hit objective.

    objective = ratio_hot * hit_hot + (1-ratio_hot) * hit_cold
    """
    rh = _clamp01(ratio_hot)
    hh = _clamp01(hit_rate_hot)
    hc = _clamp01(hit_rate_cold)
    return rh * hh + (1.0 - rh) * hc


def eq_3_inference_latency_estimate(
    base_latency_ms: float,
    hit_rate_objective: float,
    miss_penalty_ms: float,
) -> float:
    """
    Eq.(3) latency estimate with miss penalty.

    latency = base + (1-hit_rate) * miss_penalty
    """
    base = max(0.0, float(base_latency_ms))
    hit = _clamp01(hit_rate_objective)
    penalty = max(0.0, float(miss_penalty_ms))
    return base + (1.0 - hit) * penalty


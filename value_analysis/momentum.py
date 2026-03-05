from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


@dataclass(frozen=True)
class MomentumResult:
    raw_score: float
    raw_max_abs: float
    normalized_score: float
    contributions: Dict[str, float]
    missing_fields: List[str]


def compute_momentum_layer(
    indicator_scores: Mapping[str, Optional[float]],
    indicator_weights: Mapping[str, float],
) -> MomentumResult:
    """
    KEY-003-T03 baseline implementation.

    Formula follows PRD v1.1:
    - Momentum_Raw = sum(indicator_score_j * indicator_weight_j)
    - indicator_score_j clipped to [-2, +2]
    - Raw_MaxAbs = sum(2 * indicator_weight_j)
    - Momentum_Score = clip(10 * Raw / Raw_MaxAbs, -10, +10)
    """

    raw_score = 0.0
    raw_max_abs = 0.0
    contributions: Dict[str, float] = {}
    missing_fields: List[str] = []

    for indicator, weight in indicator_weights.items():
        w = float(weight)
        if w <= 0.0:
            continue

        raw_max_abs += 2.0 * w
        value = indicator_scores.get(indicator)
        if value is None:
            missing_fields.append(indicator)
            contributions[indicator] = 0.0
            continue

        clipped_score = _clip(float(value), -2.0, 2.0)
        contribution = clipped_score * w
        contributions[indicator] = contribution
        raw_score += contribution

    if raw_max_abs <= 0.0:
        normalized_score = 0.0
    else:
        normalized_score = _clip(10.0 * raw_score / raw_max_abs, -10.0, 10.0)

    return MomentumResult(
        raw_score=raw_score,
        raw_max_abs=raw_max_abs,
        normalized_score=normalized_score,
        contributions=contributions,
        missing_fields=missing_fields,
    )

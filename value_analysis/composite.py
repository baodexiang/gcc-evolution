from __future__ import annotations

from dataclasses import dataclass


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


@dataclass(frozen=True)
class CompositeResult:
    base_composite: float
    composite_score: float
    valuation_label: str
    position_modifier: float


def score_to_label(score: float) -> str:
    if score >= 6.0:
        return "Strong Undervalued"
    if score >= 2.0:
        return "Undervalued"
    if score >= -1.0:
        return "Neutral"
    if score >= -5.0:
        return "Overvalued"
    return "Severe Overvalued"


def score_to_position_modifier(score: float) -> float:
    """GCC-0004: 连续线性position modifier (替代固定阶梯)
    score -10 → 0.00, -5 → 0.50, 0 → 1.00, 5 → 1.25, 10 → 1.50
    比旧阶梯更平滑, 避免阈值附近跳变"""
    if score <= -10.0:
        return 0.00
    if score <= 0.0:
        # -10→0.0, 0→1.0 线性
        return _clip(1.0 + score / 10.0, 0.0, 1.0)
    # 0→1.0, 10→1.5 线性
    return _clip(1.0 + score * 0.05, 1.0, 1.50)


def compute_composite_score(
    valuation_score: float,
    momentum_score: float,
    quality_factor: float,
    fundamental_score: float | None = None,
    risk_penalty: float = 0.0,
    fundamental_weight: float = 0.90,
    momentum_weight: float = 0.00,
    risk_weight: float = 0.10,
) -> CompositeResult:
    """KEY-003 composite score fixed for value-investing mode.

    In value-investing mode we lock momentum contribution to zero and
    rely on fundamentals with a small risk penalty for data quality.
    """
    core_fundamental = float(valuation_score) if fundamental_score is None else float(fundamental_score)
    base = (
        float(fundamental_weight) * core_fundamental
        + float(momentum_weight) * float(momentum_score)
        - float(risk_weight) * float(risk_penalty)
    )
    final = _clip(base * float(quality_factor), -10.0, 10.0)
    return CompositeResult(
        base_composite=base,
        composite_score=final,
        valuation_label=score_to_label(final),
        position_modifier=score_to_position_modifier(final),
    )

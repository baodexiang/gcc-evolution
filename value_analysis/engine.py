from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Mapping, Optional

from .valuation import ValuationResult, compute_valuation_layer
from .momentum import MomentumResult, compute_momentum_layer
from .quality import QualityResult, evaluate_quality_layer
from .composite import CompositeResult, compute_composite_score


@dataclass(frozen=True)
class ValueAnalysisResult:
    valuation: ValuationResult
    momentum: MomentumResult
    quality: QualityResult
    composite: CompositeResult
    profitability_score: float
    balance_score: float
    cashflow_score: float
    fundamental_score: float
    risk_penalty: float
    confidence_score: float

    def effective_max_units(self, base_max_units: int) -> int:
        return max(0, math.floor(int(base_max_units) * self.composite.position_modifier))


def analyze_value_profile(
    valuation_scores: Mapping[str, Optional[float]],
    valuation_weights: Mapping[str, float],
    momentum_scores: Mapping[str, Optional[float]],
    momentum_weights: Mapping[str, float],
    audit_opinion: Optional[str],
    altman_z: Optional[float],
    profitability_scores: Optional[Mapping[str, Optional[float]]] = None,
    profitability_weights: Optional[Mapping[str, float]] = None,
    balance_scores: Optional[Mapping[str, Optional[float]]] = None,
    balance_weights: Optional[Mapping[str, float]] = None,
    cashflow_scores: Optional[Mapping[str, Optional[float]]] = None,
    cashflow_weights: Optional[Mapping[str, float]] = None,
    dcf_score: Optional[float] = None,
    macro_risk: float = 0.0,
    confidence_score: float = 1.0,
    quality_key_missing: bool = False,
) -> ValueAnalysisResult:
    """KEY-003-T06 baseline integration in value-analysis pipeline."""

    valuation = compute_valuation_layer(valuation_scores, valuation_weights)
    momentum = compute_momentum_layer(momentum_scores, momentum_weights)

    def _weighted_normalized(
        scores: Mapping[str, Optional[float]],
        weights: Mapping[str, float],
    ) -> tuple[float, int, int]:
        if not weights:
            return 0.0, 0, 0
        raw = 0.0
        total_abs = 0.0
        missing = 0
        for key, weight in weights.items():
            w = max(0.0, float(weight))
            total_abs += 2.0 * w
            val = scores.get(key)
            if val is None:
                missing += 1
                continue
            x = max(-2.0, min(2.0, float(val)))
            raw += x * w
        if total_abs <= 0.0:
            return 0.0, missing, len(weights)
        return max(-10.0, min(10.0, 10.0 * raw / total_abs)), missing, len(weights)

    profitability_norm, profitability_missing, profitability_total = _weighted_normalized(
        profitability_scores or {},
        profitability_weights or {},
    )
    balance_norm, balance_missing, balance_total = _weighted_normalized(
        balance_scores or {},
        balance_weights or {},
    )
    cashflow_norm, cashflow_missing, cashflow_total = _weighted_normalized(
        cashflow_scores or {},
        cashflow_weights or {},
    )

    # GCC-0004: 机构级多维加权
    # 有DCF: val30% + prof25% + bal15% + cf10% + dcf15% + mom5%
    # 无DCF: val35% + prof30% + bal20% + cf10% + mom5% (重分配dcf权重)
    dcf_norm = 0.0
    if dcf_score is not None:
        dcf_norm = max(-10.0, min(10.0, float(dcf_score) * 5.0))
        fundamental_score = (
            0.30 * valuation.normalized_score
            + 0.25 * profitability_norm
            + 0.15 * balance_norm
            + 0.10 * cashflow_norm
            + 0.15 * dcf_norm
            + 0.05 * momentum.normalized_score
        )
    else:
        fundamental_score = (
            0.35 * valuation.normalized_score
            + 0.30 * profitability_norm
            + 0.20 * balance_norm
            + 0.10 * cashflow_norm
            + 0.05 * momentum.normalized_score
        )

    total_fund_fields = len(valuation_weights) + profitability_total + balance_total + cashflow_total
    total_fund_missing = len(valuation.missing_fields) + profitability_missing + balance_missing + cashflow_missing
    missing_ratio = (total_fund_missing / total_fund_fields) if total_fund_fields > 0 else 0.0
    confidence = max(0.10, min(1.00, float(confidence_score)))
    data_penalty = max(4.0 * missing_ratio, (1.0 - confidence) * 4.0)
    # GCC-0006: 宏观风险叠加 (VIX高+利率高→penalty加重)
    risk_penalty = max(0.0, min(6.0, data_penalty + float(macro_risk)))

    quality = evaluate_quality_layer(audit_opinion, altman_z, key_missing=quality_key_missing)
    composite = compute_composite_score(
        valuation_score=valuation.normalized_score,
        momentum_score=momentum.normalized_score,
        quality_factor=quality.factor,
        fundamental_score=fundamental_score,
        risk_penalty=risk_penalty,
    )
    return ValueAnalysisResult(
        valuation=valuation,
        momentum=momentum,
        quality=quality,
        composite=composite,
        profitability_score=profitability_norm,
        balance_score=balance_norm,
        cashflow_score=cashflow_norm,
        fundamental_score=fundamental_score,
        risk_penalty=risk_penalty,
        confidence_score=confidence,
    )

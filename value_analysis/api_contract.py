from __future__ import annotations

from typing import Dict, List, Optional

from .engine import ValueAnalysisResult


def build_single_symbol_response(
    ticker: str,
    as_of: str,
    result: ValueAnalysisResult,
    alerts: Optional[List[str]] = None,
) -> Dict[str, object]:
    """KEY-003-T07 single API contract payload."""

    missing_fields = sorted(
        set(result.valuation.missing_fields + result.momentum.missing_fields)
    )
    payload: Dict[str, object] = {
        "ticker": ticker,
        "as_of": as_of,
        "valuation_score": result.valuation.normalized_score,
        "momentum_score": result.momentum.normalized_score,
        "fundamental_score": result.fundamental_score,
        "profitability_score": result.profitability_score,
        "balance_score": result.balance_score,
        "cashflow_score": result.cashflow_score,
        "risk_penalty": result.risk_penalty,
        "confidence_score": result.confidence_score,
        "quality_status": result.quality.status,
        "composite_score": result.composite.composite_score,
        "position_modifier": result.composite.position_modifier,
        "is_tradeable": result.quality.is_tradeable,
        "missing_fields": missing_fields,
        "alerts": alerts or [],
    }
    return payload

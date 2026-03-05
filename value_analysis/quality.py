from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class QualityResult:
    status: str
    factor: float
    is_tradeable: bool
    reasons: Dict[str, str]


def evaluate_quality_layer(
    audit_opinion: Optional[str],
    altman_z: Optional[float],
    key_missing: bool = False,
) -> QualityResult:
    """
    KEY-003-T04 baseline implementation.

    Rules from PRD v1.1:
    - Fail if audit_opinion == 否定 OR Altman_Z < 1.8
    - Fail => factor=0.0 and is_tradeable=false
    - Warning => factor=0.7
    - Pass => factor=1.0
    """

    reasons: Dict[str, str] = {}
    if audit_opinion == "否定":
        reasons["audit_opinion"] = "negative_audit"
    if altman_z is not None and altman_z < 1.8:
        reasons["altman_z"] = "below_1_8"

    if reasons:
        return QualityResult(status="Fail", factor=0.0, is_tradeable=False, reasons=reasons)

    if key_missing:
        return QualityResult(
            status="Warning",
            factor=0.7,
            is_tradeable=True,
            reasons={"data_quality": "missing_key_fields"},
        )

    return QualityResult(status="Pass", factor=1.0, is_tradeable=True, reasons={})

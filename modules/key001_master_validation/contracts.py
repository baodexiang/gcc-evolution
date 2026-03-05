from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MasterContext:
    symbol: str
    direction: str
    signal_type: str
    signal_strength: float
    filter_passed: bool
    blocked_reason: Optional[str]
    market: Dict[str, Any] = field(default_factory=dict)
    macro: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    experience_db: Dict[str, Any] = field(default_factory=dict)
    blocked_gate_count: int = 0


@dataclass
class MasterOpinion:
    master: str
    score: float
    verdict: str
    veto: bool
    reasons: List[str]
    subscores: Dict[str, float] = field(default_factory=dict)
    version: str = "v1"


@dataclass
class MasterDecision:
    action: str
    final_score: float
    reasons: List[str]
    opinions: List[MasterOpinion]
    policy_version: str = "key001-master-policy-v1"


def clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def safe_float(value: Any, default: float = 0.5) -> float:
    try:
        return float(value)
    except Exception:
        return default

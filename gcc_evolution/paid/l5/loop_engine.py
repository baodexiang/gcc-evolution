"""Canonical paid L5 program: advanced orchestration loop boundary."""
from ...L5_orchestration.loop_engine_base import SelfImprovementLoop, LoopPhase, QueryType
from ..common import PaidBoundary
from .drift_gate import DriftGateResult, drift_thresholds, evaluate_drift_gate

L5_ADVANCED = PaidBoundary("L5", "Paid", ("multi-system coordination", "advanced orchestration", "full output integration"))

__all__ = [
    "SelfImprovementLoop",
    "LoopPhase",
    "QueryType",
    "L5_ADVANCED",
    "DriftGateResult",
    "evaluate_drift_gate",
    "drift_thresholds",
]

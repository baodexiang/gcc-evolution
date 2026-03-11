"""Canonical paid L5 program: closed-loop orchestration."""
from ...L5_orchestration.loop_engine_base import (
    CommunitySelfImprovementLoop as LegacySelfImprovementLoop,
    LoopPhase,
)
from ..common import PaidBoundary

L5_ADVANCED = PaidBoundary("L5", "Paid", ("multi-system coordination", "advanced orchestration", "full output integration"))


class SelfImprovementLoop(LegacySelfImprovementLoop):
    """Canonical paid-core wrapper for the orchestration loop."""

__all__ = [
    "SelfImprovementLoop",
    "LoopPhase",
    "L5_ADVANCED",
]

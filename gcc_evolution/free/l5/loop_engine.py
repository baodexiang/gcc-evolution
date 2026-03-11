"""Canonical free L5 program: runnable community loop engine."""

from ...L5_orchestration.loop_engine_base import (
    CommunitySelfImprovementLoop,
    LoopPhase,
    SimpleImprovementLoop,
)

SelfImprovementLoop = CommunitySelfImprovementLoop

__all__ = ["SelfImprovementLoop", "CommunitySelfImprovementLoop", "SimpleImprovementLoop", "LoopPhase"]

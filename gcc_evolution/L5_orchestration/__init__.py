"""
L5 Orchestration — gcc-evo Open Core
License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Execution layer: 6-step self-improvement loop and DAG scheduling.
Community: base loop + simple sequential DAG
Enterprise: adaptive DAG + multi-arm bandit scheduling
"""

from .pipeline import DAGPipeline, PipelineStage
from .loop_engine_base import SelfImprovementLoop, LoopPhase

__all__ = [
    "DAGPipeline",
    "PipelineStage",
    "SelfImprovementLoop",
    "LoopPhase",
]

__version__ = "1.0.0"

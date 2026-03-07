"""Paid L5 layer: advanced orchestration boundary."""

from ...L5_orchestration import DAGPipeline, PipelineStage, SelfImprovementLoop, LoopPhase
from ...enterprise import adaptive_dag
from ..common import PaidBoundary
from .drift_gate import DriftGateResult, drift_thresholds, evaluate_drift_gate

L5_BOUNDARY = PaidBoundary(
    layer='L5',
    tier='Paid',
    features=(
        'Multi-system task coordination',
        'Advanced DAG orchestration',
        'Full output integration',
    ),
    note='Base orchestration remains in free/l5; advanced orchestration belongs here.',
)

__all__ = [
    'L5_BOUNDARY',
    'DAGPipeline',
    'PipelineStage',
    'SelfImprovementLoop',
    'LoopPhase',
    'adaptive_dag',
    'DriftGateResult',
    'evaluate_drift_gate',
    'drift_thresholds',
]

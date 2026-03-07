"""Paid L5 layer: advanced orchestration boundary."""

from ...L5_orchestration import DAGPipeline, PipelineStage, SelfImprovementLoop, LoopPhase
from ...enterprise import adaptive_dag
from ..common import PaidBoundary

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

__all__ = ['L5_BOUNDARY', 'DAGPipeline', 'PipelineStage', 'SelfImprovementLoop', 'LoopPhase', 'adaptive_dag']

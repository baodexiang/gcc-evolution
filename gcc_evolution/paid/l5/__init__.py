"""Paid L5 layer: canonical closed-loop orchestration core."""

from importlib import import_module

from .pipeline import DAGPipeline, PipelineStage
from .loop_engine import SelfImprovementLoop, LoopPhase
from ...enterprise import adaptive_dag
from ..common import PaidBoundary

L5_BOUNDARY = PaidBoundary(
    layer='L5',
    tier='Paid',
    features=(
        'Closed-loop orchestration',
        'Advanced DAG orchestration',
        'Full output integration',
        'Drift-aware adaptive scheduling',
    ),
    note='L5 is part of the canonical paid core in the 5 Free + 3 Paid model.',
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


def __getattr__(name):
    if name in {'DriftGateResult', 'evaluate_drift_gate', 'drift_thresholds'}:
        module = import_module('gcc_evolution.paid.l5.drift_gate')
        return getattr(module, name)
    raise AttributeError(name)

"""Paid L4 layer: canonical decision/evolution engine."""

from ...L4_decision import MultiModelEnsemble, ModelPrediction, SkepticValidator, ValidationResult
from ...enterprise import adaptive_dag, bandit_scheduler, knn_evolution, walk_forward
from ..common import PaidBoundary

L4_BOUNDARY = PaidBoundary(
    layer='L4',
    tier='Paid',
    features=(
        'Skeptic Agent',
        'Multi-model consensus',
        'KNN evolution engine',
        'Walk-forward optimization',
        'Adaptive scheduling / drift-sensitive evolution',
    ),
    note='Canonical paid-only layer in v5.300. Legacy direct imports remain for compatibility only.',
)

__all__ = [
    'L4_BOUNDARY',
    'SkepticValidator', 'ValidationResult',
    'MultiModelEnsemble', 'ModelPrediction',
    'adaptive_dag', 'bandit_scheduler', 'knn_evolution', 'walk_forward',
]

"""Paid L0 layer: Phase 2-4 execution boundary."""

from ..common import PaidBoundary
from .phase3_math import (
    PHASE3_MATH,
    STATE_VECTOR_SPEC,
    Phase3NowcastResult,
    build_phase3_nowcast_model,
    build_phase3_state_vector,
)
from .phase4_truth_table import (
    PHASE4_TRUTH_TABLE,
    TRUTH_ACCEPTANCE_SPEC,
    TruthTableRecord,
    build_truth_table_record,
    build_truth_table_row,
)

L0_BOUNDARY = PaidBoundary(
    layer='L0',
    tier='Paid',
    features=(
        'Phase 2 quality validation',
        'Phase 3 deterministic mathematical modeling',
        'Phase 4 decision truth table',
    ),
    note='Canonical paid boundary for v5.300 L0 after free Phase 1.',
)

__all__ = [
    'L0_BOUNDARY',
    'PHASE3_MATH',
    'STATE_VECTOR_SPEC',
    'Phase3NowcastResult',
    'build_phase3_nowcast_model',
    'build_phase3_state_vector',
    'PHASE4_TRUTH_TABLE',
    'TRUTH_ACCEPTANCE_SPEC',
    'TruthTableRecord',
    'build_truth_table_record',
    'build_truth_table_row',
]

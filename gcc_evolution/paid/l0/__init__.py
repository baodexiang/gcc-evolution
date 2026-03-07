"""Paid L0 layer: Phase 2-4 execution boundary."""

from ..common import PaidBoundary

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

__all__ = ['L0_BOUNDARY']

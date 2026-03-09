"""Paid L2 layer: full retrieval boundary."""

from ..common import PaidBoundary

L2_BOUNDARY = PaidBoundary(
    layer='L2',
    tier='Paid',
    features=(
        'Planning/execution dual retrieval',
        'Quality-weighted recall',
        'Higher-order similarity orchestration',
    ),
    note='Base retrieval remains in free/l2; advanced retrieval belongs here.',
)

__all__ = ['L2_BOUNDARY']

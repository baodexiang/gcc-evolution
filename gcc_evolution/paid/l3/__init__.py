"""Paid L3 layer: full distillation boundary."""

from ..common import PaidBoundary

L3_BOUNDARY = PaidBoundary(
    layer='L3',
    tier='Paid',
    features=(
        'Invalid input source exclusion',
        'Cross-session knowledge distillation',
        'Quality-aware compression workflows',
    ),
    note='Base distillation remains in free/l3; advanced distillation belongs here.',
)

__all__ = ['L3_BOUNDARY']

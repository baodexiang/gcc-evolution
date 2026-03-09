"""Paid L1 layer: full memory stack boundary."""

from ..common import PaidBoundary

L1_BOUNDARY = PaidBoundary(
    layer='L1',
    tier='Paid',
    features=(
        'Cross-session persistent memory enhancements',
        'U-shaped sparse optimization',
        'Session prefetch and higher-capacity memory workflows',
    ),
    note='Base memory remains in free/l1; advanced memory belongs here.',
)

__all__ = ['L1_BOUNDARY']

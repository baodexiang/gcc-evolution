"""Paid Direction Anchor boundary."""

from ...direction_anchor import DirectionAnchor, PrincipleSet
from ..common import PaidBoundary

DA_BOUNDARY = PaidBoundary(
    layer='DA',
    tier='Paid',
    features=(
        'Constitutional gating from L4 to L5',
        'Human final decision enforcement',
        'Manual override guarantees',
    ),
    note='Canonical paid-only DA layer in v5.300.',
)

__all__ = ['DA_BOUNDARY', 'DirectionAnchor', 'PrincipleSet']

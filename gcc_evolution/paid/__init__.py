"""Canonical paid surface for gcc-evo v5.405.

This package intentionally avoids eager imports so lightweight commands remain
stable even when optional paid submodules are not exercised.
"""

from .common import PaidBoundary, EnterpriseRequired, upgrade_prompt, unavailable

__all__ = [
    'PaidBoundary', 'EnterpriseRequired', 'upgrade_prompt', 'unavailable',
    'l0', 'l1', 'l2', 'l3', 'l4', 'l5', 'da',
]

"""
Enterprise Features - Requires License
License: BUSL 1.1 (Enterprise license required)
Commercial: gcc-evo.dev/licensing

Canonical free tier: UI + L0 + L1 + L2 + L3.
Canonical paid core: L4 + L5 + DA.
Commercial add-ons: paid/l0, paid/l1, paid/l2, paid/l3 enhancement packs.
Enterprise features degrade gracefully: warning + fallback behavior.
"""

import warnings


def upgrade_prompt(feature: str, tier: str = "Evolve", fallback: str = "") -> str:
    """Generate a friendly upgrade prompt."""
    msg = (
        f"[gcc-evo] '{feature}' requires {tier} tier or higher.\n"
        f"  Canonical free tier: UI + L0 + L1 + L2 + L3.\n"
        f"  Canonical paid core: L4 + L5 + DA.\n"
        f"  Commercial add-ons: paid/l0, paid/l1, paid/l2, paid/l3.\n"
        f"  Upgrade: https://gcc-evo.dev/pricing"
    )
    if fallback:
        msg += f"\n  Fallback: {fallback}"
    warnings.warn(msg, stacklevel=3)
    return msg


class EnterpriseRequired(Exception):
    """Raised only in strict mode. Default behavior is warning + fallback."""

    def __init__(self, feature: str, tier: str = "Evolve"):
        self.feature = feature
        self.tier = tier
        message = (
            f"Feature '{feature}' requires {tier} tier or higher.\n"
            f"Canonical free tier: UI + L0 + L1 + L2 + L3.\n"
            f"Canonical paid core: L4 + L5 + DA.\n"
            f"Commercial add-ons: paid/l0, paid/l1, paid/l2, paid/l3.\n"
            f"Learn more: https://gcc-evo.dev/pricing"
        )
        super().__init__(message)


try:
    from . import knn_evolution
    from . import walk_forward
    from . import bandit_scheduler
    from . import adaptive_dag
    from . import skillbank_content
except ImportError:
    pass


__all__ = [
    "EnterpriseRequired",
    "upgrade_prompt",
    "knn_evolution",
    "walk_forward",
    "bandit_scheduler",
    "adaptive_dag",
    "skillbank_content",
]

__version__ = "1.0.0"

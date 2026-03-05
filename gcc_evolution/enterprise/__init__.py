"""
Enterprise Features — Requires License
License: BUSL 1.1 (Enterprise license required)
Commercial: gcc-evo.dev/licensing

Community features (L1-L5, Direction Anchor) are always free.
Enterprise features degrade gracefully: warning + fallback behavior.
"""

import warnings


def upgrade_prompt(feature: str, tier: str = "Evolve", fallback: str = "") -> str:
    """
    Generate friendly upgrade prompt.

    Instead of crashing, prints a warning and returns a fallback description.
    """
    msg = (
        f"[gcc-evo] '{feature}' requires {tier} tier or higher.\n"
        f"  Community features (L1-L5, Direction Anchor) are always free.\n"
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
            f"Community features (L1-L5, Direction Anchor) are always free.\n"
            f"Learn more: https://gcc-evo.dev/pricing"
        )
        super().__init__(message)


# Import stubs (prevent ImportError, but degrade at usage time)
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

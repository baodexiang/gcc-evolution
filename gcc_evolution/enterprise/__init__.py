"""
Enterprise Features — Requires License
License: BUSL 1.1 (Enterprise license required)
Commercial: gcc-evo.dev/licensing

⚠️  These modules are for enterprise customers only.
Community features (L1-L5, Direction Anchor) are always free.

To use enterprise features, obtain a license from: gcc-evo.dev/pricing
"""


class EnterpriseRequired(Exception):
    """
    Raised when accessing enterprise-only features without proper license.

    Enterprise features include:
      • KNN evolutionary optimization
      • Walk-forward backtesting
      • Signal evolution framework
      • Adaptive DAG scheduling
      • SkillBank commercial library

    For information on licensing, visit: gcc-evo.dev/pricing
    """

    def __init__(self, feature: str, tier: str = "Evolve"):
        self.feature = feature
        self.tier = tier
        message = (
            f"Feature '{feature}' requires {tier} tier or higher.\n"
            f"Community features (L1-L5, Direction Anchor) are always free.\n"
            f"Learn more: https://gcc-evo.dev/pricing"
        )
        super().__init__(message)


def _raise_enterprise_required(feature: str) -> None:
    """Helper to raise EnterpriseRequired with proper context."""
    raise EnterpriseRequired(feature)


# Import stubs (prevent ImportError, but raise at usage time)
try:
    from . import knn_evolution
    from . import walk_forward
    from . import bandit_scheduler
    from . import adaptive_dag
    from . import skillbank_content
except ImportError:
    # Stubs not yet loaded
    pass


__all__ = [
    "EnterpriseRequired",
    "knn_evolution",
    "walk_forward",
    "bandit_scheduler",
    "adaptive_dag",
    "skillbank_content",
]

__version__ = "1.0.0"

"""Community fallbacks for multi-arm bandit helpers."""

from . import unavailable_result


def MultiArmBandit(*args, **kwargs):
    """Optimized exploration-exploitation scheduling."""
    return unavailable_result(
        "MultiArmBandit",
        tier="Evolve",
        fallback="Using random selection instead",
        value=None,
    )


def thompson_sampling(*args, **kwargs):
    """Thompson sampling strategy for bandit optimization."""
    return unavailable_result(
        "thompson_sampling",
        tier="Pro",
        fallback="Using uniform sampling instead",
        value=[],
    )


def context_bandit(*args, **kwargs):
    """Contextual bandit for state-dependent actions."""
    return unavailable_result(
        "context_bandit",
        tier="Enterprise",
        fallback="Using static policy instead",
        value=[],
    )


__all__ = ["MultiArmBandit", "thompson_sampling", "context_bandit"]

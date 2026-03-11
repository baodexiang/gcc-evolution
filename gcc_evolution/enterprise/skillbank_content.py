"""Community fallbacks for commercial SkillBank helpers."""

from . import unavailable_result


def load_skillbank(*args, **kwargs):
    """Load commercial SkillBank content."""
    return unavailable_result(
        "load_skillbank",
        tier="Pro",
        fallback="Using community skill cards instead",
        value=[],
    )


def vertical_skillbank(*args, **kwargs):
    """Load vertical-specific SkillBank (crypto, stocks, forex, etc)."""
    return unavailable_result(
        "vertical_skillbank",
        tier="Enterprise",
        fallback="No vertical skills available",
        value=[],
    )


def custom_skillbank(*args, **kwargs):
    """Deploy custom SkillBank for enterprise customer."""
    return unavailable_result(
        "custom_skillbank",
        tier="Enterprise",
        fallback="No custom skills available",
        value=[],
    )


def skillbank_version(*args, **kwargs):
    """Get current SkillBank version and update manifest."""
    return unavailable_result(
        "skillbank_version",
        tier="Pro",
        fallback="Version info unavailable",
        value={"version": "community", "tier": "free"},
    )


__all__ = [
    "load_skillbank",
    "vertical_skillbank",
    "custom_skillbank",
    "skillbank_version",
]

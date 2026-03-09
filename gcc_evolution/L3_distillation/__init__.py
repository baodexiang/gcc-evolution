"""
L3 Distillation — gcc-evo Open Core
License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Knowledge distillation framework converting experience into reusable cards.
Framework is open-source; content library is available in Evolve+ tier.
"""

from .distiller import ExperienceDistiller, CardGenerator
from .experience_card import ExperienceCard, CardVersion, CardMetadata, CardType

__all__ = [
    "ExperienceDistiller",
    "CardGenerator",
    "ExperienceCard",
    "CardVersion",
    "CardMetadata",
    "CardType",
]

__version__ = "1.0.0"

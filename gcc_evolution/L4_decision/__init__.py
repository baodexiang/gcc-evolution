"""
L4 Decision — gcc-evo Open Core
License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Decision layer combining skeptic validation and multi-model ensemble.
Community: base skeptic + dual-model comparison
Enterprise: full multi-model ensemble + specialized validators
"""

from .skeptic import SkepticValidator, HallucinationDetector
from .multi_model import MultiModelEnsemble, ModelComparator

__all__ = [
    "SkepticValidator",
    "HallucinationDetector",
    "MultiModelEnsemble",
    "ModelComparator",
]

__version__ = "1.0.0"

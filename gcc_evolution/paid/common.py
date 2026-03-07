"""Common helpers for canonical paid-layer boundaries."""
from __future__ import annotations

from dataclasses import dataclass

from ..enterprise import EnterpriseRequired, upgrade_prompt


@dataclass(frozen=True)
class PaidBoundary:
    layer: str
    tier: str
    features: tuple[str, ...]
    note: str = ''

    def to_dict(self) -> dict:
        return {
            'layer': self.layer,
            'tier': self.tier,
            'features': list(self.features),
            'note': self.note,
        }


def unavailable(feature: str, tier: str = 'Paid') -> None:
    raise EnterpriseRequired(feature, tier=tier)


__all__ = ['PaidBoundary', 'EnterpriseRequired', 'upgrade_prompt', 'unavailable']

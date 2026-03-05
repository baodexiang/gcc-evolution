from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class ValidationSummary:
    ic_mean: float
    ic_min: float
    ic_max: float
    sample_size: int


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n == 0 or n != len(y):
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denx = sqrt(sum((a - mx) ** 2 for a in x))
    deny = sqrt(sum((b - my) ** 2 for b in y))
    if denx == 0 or deny == 0:
        return 0.0
    return num / (denx * deny)


def compute_ic(scores: Sequence[float], future_returns: Sequence[float]) -> float:
    """Cross-sectional Information Coefficient (Pearson)."""
    return _pearson(scores, future_returns)


def summarize_ic(ics: Iterable[float]) -> ValidationSummary:
    values = list(ics)
    if not values:
        return ValidationSummary(0.0, 0.0, 0.0, 0)
    return ValidationSummary(
        ic_mean=sum(values) / len(values),
        ic_min=min(values),
        ic_max=max(values),
        sample_size=len(values),
    )


def acceptance_gate(summary: ValidationSummary, threshold: float = 0.05) -> Dict[str, object]:
    return {
        "ic_mean": summary.ic_mean,
        "threshold": threshold,
        "passed": summary.ic_mean >= threshold,
        "sample_size": summary.sample_size,
    }

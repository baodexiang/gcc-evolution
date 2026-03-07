"""
Paper Formula Implementation: DeepSeek Engram
=============================================
arXiv : 2601.07372
DOI   : N/A
URL   : https://arxiv.org/abs/2601.07372
Layer : Memory

Source mapping:
- Eq.(3): memory update rule
- Eq.(5): memory decay / forgetting
- Eq.(7): context-key normalization
- Eq.(9): soft gating
- Eq.(11): session prefetch priority score
"""

from __future__ import annotations

import math
import re

# Constants from paper-oriented implementation contract.
ALPHA: float = 0.1
BETA: float = 0.9
GAMMA: float = 0.95
EPSILON: float = 1e-8
DECAY_LAMBDA: float = 0.08


def _clamp01(value: float) -> float:
    """Clamp a numeric value into [0, 1]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def eq_3_memory_update(old: float, new: float, decay: float, gate: float) -> float:
    """
    DeepSeek Engram — Equation (3): memory update.

    A gated/decayed interpolation:
        updated = old + decay * gate * (new - old)
    """
    d = _clamp01(decay)
    g = _clamp01(gate)
    return float(old) + d * g * (float(new) - float(old))


def eq_5_decay_factor(age_days: float, lambda_decay: float = DECAY_LAMBDA) -> float:
    """
    DeepSeek Engram — Equation (5): forgetting factor.

    Exponential decay:
        decay(age) = exp(-lambda * age)
    """
    age = max(0.0, float(age_days))
    lam = max(EPSILON, float(lambda_decay))
    return _clamp01(math.exp(-lam * age))


def eq_7_normalize_key(context: str) -> str:
    """
    DeepSeek Engram — Equation (7): context-key normalization.

    Rules:
    - trim head/tail spaces
    - collapse internal spaces
    - lowercase
    """
    if context is None:
        return ""
    text = re.sub(r"\s+", " ", str(context).strip().lower())
    return text


def eq_9_soft_gate(confidence: float, center: float = 0.5, temperature: float = 0.15) -> float:
    """
    DeepSeek Engram — Equation (9): soft gating weight.

    Logistic gate:
        g = sigmoid((confidence - center) / temperature)
    """
    temp = max(float(temperature), EPSILON)
    x = (float(confidence) - float(center)) / temp
    # Numerically stable sigmoid.
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def eq_11_session_prefetch_priority(
    recency_hours: float,
    access_count: int,
    confidence: float,
) -> float:
    """
    DeepSeek Engram — Equation (11): session prefetch priority score.

    Priority blends recency, historical access frequency and confidence gate.
    """
    recency = max(0.0, float(recency_hours))
    count = max(0, int(access_count))
    recency_term = math.exp(-recency / 24.0)
    freq_term = math.log1p(count)
    gate = eq_9_soft_gate(confidence)
    return max(0.0, recency_term * freq_term * gate)


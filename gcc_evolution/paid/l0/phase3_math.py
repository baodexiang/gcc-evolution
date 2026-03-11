"""Canonical paid L0 program: Phase 3 mathematical modeling with P002 nowcasting."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Iterable, Sequence

from gcc.papers.formulas.P002_nowcasting import (
    Z_95,
    eq_1_realtime_state_estimate,
    eq_2_fusion_weights,
    eq_3_confidence_interval,
)

from ..common import PaidBoundary


PHASE3_MATH = PaidBoundary(
    "L0",
    "Paid",
    ("input_math_models", "state_vector_spec", "filter math spec"),
    "Phase 3 deterministic modeling is paid.",
)

STATE_VECTOR_SPEC = {
    "version": "5.400",
    "paper": "P002_nowcasting",
    "fields": (
        "prev_state",
        "observation",
        "signal_scores",
        "fusion_weights",
        "nowcast_state",
        "confidence_low",
        "confidence_high",
        "sample_size",
        "variance",
        "temperature",
        "z_score",
    ),
}


@dataclass(frozen=True)
class Phase3NowcastResult:
    prev_state: float
    observation: float
    signal_scores: tuple[float, ...]
    fusion_weights: tuple[float, ...]
    nowcast_state: float
    confidence_interval: tuple[float, float]
    sample_size: int
    variance: float
    temperature: float
    z_score: float = Z_95

    def to_state_vector(self) -> dict:
        return {
            "prev_state": self.prev_state,
            "observation": self.observation,
            "signal_scores": list(self.signal_scores),
            "fusion_weights": list(self.fusion_weights),
            "nowcast_state": self.nowcast_state,
            "confidence_low": self.confidence_interval[0],
            "confidence_high": self.confidence_interval[1],
            "sample_size": self.sample_size,
            "variance": self.variance,
            "temperature": self.temperature,
            "z_score": self.z_score,
        }


def _coerce_scores(signal_scores: Iterable[float]) -> tuple[float, ...]:
    scores = tuple(float(score) for score in signal_scores)
    if not scores:
        raise ValueError("signal_scores must not be empty")
    return scores


def _default_observation(signal_scores: Sequence[float]) -> float:
    return float(fmean(signal_scores))


def build_phase3_nowcast_model(
    *,
    prev_state: float,
    signal_scores: Iterable[float],
    observation: float | None = None,
    alpha: float = 0.35,
    variance: float = 0.0,
    sample_size: int | None = None,
    temperature: float = 1.0,
    z_score: float = Z_95,
) -> Phase3NowcastResult:
    """
    Build a deterministic Phase 3 model from validated inputs using P002 formulas.

    This is the first concrete paid L0 math entrypoint:
      - Eq.(1): real-time state estimate
      - Eq.(2): fusion weights
      - Eq.(3): confidence interval
    """
    scores = _coerce_scores(signal_scores)
    obs = float(observation) if observation is not None else _default_observation(scores)
    n = int(sample_size) if sample_size is not None else len(scores)
    weights = tuple(eq_2_fusion_weights(scores, temperature=temperature))
    nowcast = float(eq_1_realtime_state_estimate(prev_state=prev_state, observation=obs, alpha=alpha))
    ci = tuple(
        eq_3_confidence_interval(
            mean=nowcast,
            variance=variance,
            sample_size=n,
            z_score=z_score,
        )
    )
    return Phase3NowcastResult(
        prev_state=float(prev_state),
        observation=obs,
        signal_scores=scores,
        fusion_weights=weights,
        nowcast_state=nowcast,
        confidence_interval=(float(ci[0]), float(ci[1])),
        sample_size=max(n, 1),
        variance=max(float(variance), 0.0),
        temperature=float(temperature),
        z_score=float(z_score),
    )


def build_phase3_state_vector(**kwargs) -> dict:
    """Return the canonical Phase 3 state-vector payload for downstream truth-table work."""
    return build_phase3_nowcast_model(**kwargs).to_state_vector()


__all__ = [
    "PHASE3_MATH",
    "STATE_VECTOR_SPEC",
    "Phase3NowcastResult",
    "build_phase3_nowcast_model",
    "build_phase3_state_vector",
]

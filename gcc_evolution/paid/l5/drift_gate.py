"""Canonical paid L5 program: drift-aware orchestration gate with P006 formulas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from gcc.papers.formulas.P006_drift_aware_streaming import (
    KS_DRIFT_THRESHOLD,
    PSI_DRIFT_THRESHOLD,
    eq_2_psi,
    eq_3_ks_statistic,
    eq_4_adaptive_window,
    eq_5_drift_detected,
)


@dataclass(frozen=True)
class DriftGateResult:
    baseline_window: int
    adaptive_window: int
    psi: float
    ks: float
    drift_detected: bool
    expected_count: int
    actual_count: int

    def to_dict(self) -> dict:
        return {
            "baseline_window": self.baseline_window,
            "adaptive_window": self.adaptive_window,
            "psi": self.psi,
            "ks": self.ks,
            "drift_detected": self.drift_detected,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
        }


def evaluate_drift_gate(
    *,
    expected_series: Sequence[float],
    actual_series: Sequence[float],
    base_window: int = 100,
) -> DriftGateResult:
    """
    Build a paid L5 orchestration gate from P006 drift-aware formulas.

    Uses:
      - Eq.(2): PSI drift score
      - Eq.(3): KS statistic
      - Eq.(4): adaptive window size
      - Eq.(5): drift gate decision
    """
    psi = float(eq_2_psi(expected_series, actual_series))
    ks = float(eq_3_ks_statistic(expected_series, actual_series))
    adaptive_window = int(eq_4_adaptive_window(base_window=base_window, psi=psi, ks=ks))
    drift = bool(eq_5_drift_detected(psi=psi, ks=ks))
    return DriftGateResult(
        baseline_window=int(base_window),
        adaptive_window=adaptive_window,
        psi=psi,
        ks=ks,
        drift_detected=drift,
        expected_count=len(expected_series),
        actual_count=len(actual_series),
    )


def drift_thresholds() -> dict:
    """Expose canonical thresholds used by the paid drift gate."""
    return {
        "psi_threshold": float(PSI_DRIFT_THRESHOLD),
        "ks_threshold": float(KS_DRIFT_THRESHOLD),
    }


__all__ = ["DriftGateResult", "evaluate_drift_gate", "drift_thresholds"]

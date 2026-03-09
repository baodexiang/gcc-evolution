"""
GCC v5.300 — Shapley Attribution Framework (IRS-006)

Apache 2.0 — open-source interface layer.
The private engine implements the full walk-forward Shapley optimization
and wires attribution weights into the L4 evolution engine (BUSL 1.1).

Theory grounding (Structured Search Space Theorem, Brenner et al. 2026):
    "Credit assignment across modules must be objective, not heuristic."

    When multiple GCC modules contribute to a signal (KNN, Vision,
    Chan theory, Volume analyzer, etc.), it is unclear which modules
    are genuinely adding IC and which are adding noise.

    IRS-006 reframes module credit assignment as a Shapley value problem:
        φ_i = Σ_{S ⊆ N∖{i}} [|S|!(|N|-|S|-1)!/|N|!] × [v(S∪{i}) − v(S)]

    Where:
        N = set of all active modules
        v(S) = IC achieved by coalition S (measured via walk-forward)
        φ_i = Shapley value (marginal IC contribution) of module i

    Exact Shapley is O(2^|N|) — intractable for |N| > 20.
    IRS-006 uses Monte Carlo sampling with random permutations.

Open-core boundary:
    Apache 2.0 (this file):
        - ShapleyValue dataclass
        - MonteCarloShapley: approximate Shapley via random permutations
        - ShapleySnapshot / ShapleyLog: sliding-window attribution history

    BUSL 1.1 (private engine):
        - Walk-forward IC measurement pipeline
        - Shapley-guided evolution weight updates
        - Dashboard time-series of per-module Shapley trends
        - Automatic module pruning when φ_i < 0 consistently

Usage::

    from gcc_evolution.shapley import MonteCarloShapley, ShapleyLog

    def measure_ic(active_modules: frozenset) -> float:
        # Call your signal pipeline with only these modules active
        return compute_ic(active_modules)

    shapley = MonteCarloShapley(
        modules=["KNN", "Vision", "Chan", "Volume"],
        ic_fn=measure_ic,
        n_samples=200,
    )

    values = shapley.compute()
    for name, phi in sorted(values.items(), key=lambda x: -x[1]):
        print(f"  {name}: φ = {phi:.4f}")

    log = ShapleyLog()
    log.record(values, window_id="W-042")
    print(log.top_contributors(n=3))
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ShapleyValue:
    """
    Shapley attribution result for one walk-forward window.

    module_id:   module name / identifier
    phi:         Shapley value (estimated marginal IC contribution)
    std_err:     Monte Carlo standard error of the estimate
    n_samples:   number of random permutations used
    window_id:   walk-forward window identifier
    computed_at: ISO timestamp
    """
    module_id:   str
    phi:         float
    std_err:     float = 0.0
    n_samples:   int   = 0
    window_id:   str   = ""
    computed_at: str   = field(default_factory=_now)

    @property
    def is_beneficial(self) -> bool:
        """True when Shapley value is positive (module adds IC)."""
        return self.phi > 0

    def to_dict(self) -> dict:
        return {
            "module_id":   self.module_id,
            "phi":         round(self.phi, 6),
            "std_err":     round(self.std_err, 6),
            "n_samples":   self.n_samples,
            "window_id":   self.window_id,
            "computed_at": self.computed_at,
        }


# ═══════════════════════════════════════════════════════════════════
# MonteCarloShapley — approximate Shapley via random permutations (S51~S53)
# ═══════════════════════════════════════════════════════════════════

class MonteCarloShapley:
    """
    Approximate Shapley value estimator using Monte Carlo permutation sampling.

    IRS-006 S51~S52: randomly mask subsets of modules to measure marginal IC.
    IRS-006 S53: use Shapley values as module importance weights in the
                 L4 evolution engine.

    Algorithm (Strumbelj & Kononenko 2010):
        For each sample:
            1. Draw a random permutation π of all modules
            2. For each module i, compute:
               marginal_i = v(prefix_π ∪ {i}) − v(prefix_π)
            3. Average marginals across samples → Shapley estimate

    Computation cost: O(n_samples × |N|) IC evaluations.
    Acceptance criterion (IRS-006 S57): overhead < 5% of total pipeline time.

    Open-source (Apache 2.0).  The private engine supplies ic_fn as the
    walk-forward IC measurement pipeline, which is BUSL 1.1.

    Args:
        modules:   list of module identifiers
        ic_fn:     callable: frozenset[str] → float (IC for that coalition)
        n_samples: number of random permutations (default 200)
        seed:      random seed for reproducibility (None = non-deterministic)
    """

    def __init__(
        self,
        modules:   Sequence[str],
        ic_fn:     Callable[[frozenset], float],
        n_samples: int = 200,
        seed:      int | None = None,
    ):
        if len(modules) == 0:
            raise ValueError("modules must not be empty")
        self.modules   = list(modules)
        self._ic_fn    = ic_fn
        self.n_samples = n_samples
        self._rng      = random.Random(seed)

    def compute(self, window_id: str = "") -> dict[str, ShapleyValue]:
        """
        Estimate Shapley values for all modules.

        Returns dict mapping module_id → ShapleyValue.
        Each value's phi is the estimated marginal IC contribution.
        """
        # marginals accumulates per-module marginal contributions across samples
        marginals: dict[str, list[float]] = {m: [] for m in self.modules}

        for _ in range(self.n_samples):
            perm = self.modules[:]
            self._rng.shuffle(perm)

            prefix: frozenset[str] = frozenset()
            v_prefix = self._ic_fn(prefix)

            for mod in perm:
                v_with = self._ic_fn(prefix | {mod})
                marginals[mod].append(v_with - v_prefix)
                prefix = prefix | {mod}
                v_prefix = v_with

        result: dict[str, ShapleyValue] = {}
        for mod in self.modules:
            samples = marginals[mod]
            phi = sum(samples) / len(samples)
            variance = sum((s - phi) ** 2 for s in samples) / max(len(samples) - 1, 1)
            std_err = variance ** 0.5 / (len(samples) ** 0.5)
            result[mod] = ShapleyValue(
                module_id=mod,
                phi=phi,
                std_err=std_err,
                n_samples=self.n_samples,
                window_id=window_id,
            )
            logger.debug(
                "[SHAPLEY] %s: φ=%.4f ± %.4f (window=%s)",
                mod, phi, std_err, window_id,
            )

        return result


# ═══════════════════════════════════════════════════════════════════
# ShapleyLog — sliding-window attribution history (S54~S56)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ShapleySnapshot:
    """One window's worth of Shapley values across all modules."""
    window_id:   str
    values:      dict[str, ShapleyValue]
    recorded_at: str = field(default_factory=_now)


class ShapleyLog:
    """
    Sliding-window history of Shapley attribution results.

    IRS-006 S54: Dashboard time-series of per-module Shapley contributions.
    IRS-006 S55: Open-source interface; private engine wires attribution
                 weights into the L4 evolution engine (BUSL 1.1).
    IRS-006 S56: Long-horizon attribution across multiple walk-forward windows.

    Args:
        max_snapshots: number of windows to retain (default 100)
    """

    def __init__(self, max_snapshots: int = 100):
        self.max_snapshots = max_snapshots
        self._snapshots: list[ShapleySnapshot] = []

    def record(self, values: dict[str, ShapleyValue], window_id: str = "") -> None:
        """Record one walk-forward window's Shapley values."""
        snap = ShapleySnapshot(window_id=window_id, values=values)
        self._snapshots.append(snap)
        if len(self._snapshots) > self.max_snapshots:
            self._snapshots = self._snapshots[-self.max_snapshots:]

    def mean_phi(self, module_id: str) -> float | None:
        """Mean Shapley value for module_id across all recorded windows."""
        phis = [
            snap.values[module_id].phi
            for snap in self._snapshots
            if module_id in snap.values
        ]
        return sum(phis) / len(phis) if phis else None

    def top_contributors(self, n: int = 3) -> list[tuple[str, float]]:
        """
        Return the top-n modules by mean Shapley value (descending).

        Returns list of (module_id, mean_phi) tuples.
        """
        all_modules: set[str] = set()
        for snap in self._snapshots:
            all_modules.update(snap.values.keys())

        ranked = [
            (mod, self.mean_phi(mod))
            for mod in all_modules
            if self.mean_phi(mod) is not None
        ]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:n]

    def trend(self, module_id: str) -> list[float]:
        """
        Historical Shapley values for module_id across windows (oldest first).

        Used by Dashboard to render the per-module contribution time series.
        """
        return [
            snap.values[module_id].phi
            for snap in self._snapshots
            if module_id in snap.values
        ]

    def summary(self) -> dict:
        """Aggregate summary for Dashboard reporting."""
        all_modules: set[str] = set()
        for snap in self._snapshots:
            all_modules.update(snap.values.keys())
        return {
            "n_windows": len(self._snapshots),
            "modules":   {
                mod: {
                    "mean_phi": round(self.mean_phi(mod) or 0, 6),
                    "n_windows": sum(
                        1 for s in self._snapshots if mod in s.values
                    ),
                }
                for mod in sorted(all_modules)
            },
        }

    def __len__(self) -> int:
        return len(self._snapshots)

"""Community walk-forward validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from ..holdout import HoldoutSplitter
from .knn_evolution import KNNEvolver


@dataclass
class PhaseGateResult:
    """Simple rollout gate for staged KNN changes."""

    approved: bool
    phase: str
    reason: str
    metrics: dict = field(default_factory=dict)


@dataclass
class WindowBacktestResult:
    """Per-window WFO outcome."""

    window_id: int
    train_size: int
    validate_size: int
    test_size: int
    old_accuracy: float
    new_accuracy: float
    delta_accuracy: float
    trades: list[dict] = field(default_factory=list)


def out_of_sample_metrics(trades: Sequence[dict]) -> dict:
    """Aggregate simple OOS classification metrics."""

    trades = list(trades)
    if not trades:
        return {
            "accuracy": 0.0,
            "count": 0,
            "wins": 0,
            "losses": 0,
            "avg_confidence": 0.0,
        }
    wins = sum(1 for item in trades if item.get("correct"))
    confidences = [float(item.get("confidence", 0.0)) for item in trades]
    total = len(trades)
    return {
        "accuracy": wins / total,
        "count": total,
        "wins": wins,
        "losses": total - wins,
        "avg_confidence": sum(confidences) / total if confidences else 0.0,
    }


class WalkForwardAnalyzer:
    """Community walk-forward analyzer for baseline vs adaptive KNN."""

    def __init__(
        self,
        *,
        baseline_factory: Callable[[], KNNEvolver] | None = None,
        adaptive_factory: Callable[[], KNNEvolver] | None = None,
        splitter: HoldoutSplitter | None = None,
        window_size: int = 60,
    ) -> None:
        self.baseline_factory = baseline_factory or (
            lambda: KNNEvolver(base_forgetting=0.01, recent_window=20, drift_psi_threshold=999.0, drift_ks_threshold=999.0)
        )
        self.adaptive_factory = adaptive_factory or (
            lambda: KNNEvolver(base_forgetting=0.015, recent_window=20)
        )
        self.splitter = splitter or HoldoutSplitter(validate_ratio=0.2, test_ratio=0.2, min_train=12)
        self.window_size = max(20, int(window_size))

    def evaluate(self, records: Iterable[dict]) -> dict:
        ordered = sorted(list(records), key=lambda item: item["timestamp"])
        windows = self.splitter.split(ordered, window_size=self.window_size)
        results: list[WindowBacktestResult] = []
        all_old_trades: list[dict] = []
        all_new_trades: list[dict] = []

        for window in windows:
            baseline = self.baseline_factory()
            adaptive = self.adaptive_factory()
            baseline.fit(window.train)
            adaptive.fit(window.train)

            old_trades = self._score_window(baseline, window.validate + window.test)
            new_trades = self._score_window(adaptive, window.validate + window.test)
            old_metrics = out_of_sample_metrics(old_trades)
            new_metrics = out_of_sample_metrics(new_trades)
            all_old_trades.extend(old_trades)
            all_new_trades.extend(new_trades)
            results.append(
                WindowBacktestResult(
                    window_id=window.window_id,
                    train_size=len(window.train),
                    validate_size=len(window.validate),
                    test_size=len(window.test),
                    old_accuracy=old_metrics["accuracy"],
                    new_accuracy=new_metrics["accuracy"],
                    delta_accuracy=new_metrics["accuracy"] - old_metrics["accuracy"],
                    trades=new_trades,
                )
            )

        baseline_metrics = out_of_sample_metrics(all_old_trades)
        adaptive_metrics = out_of_sample_metrics(all_new_trades)
        phase_gate = self.phase_gate(
            old_metrics=baseline_metrics,
            new_metrics=adaptive_metrics,
            windows=results,
        )
        return {
            "windows": [item.__dict__ for item in results],
            "old_metrics": baseline_metrics,
            "new_metrics": adaptive_metrics,
            "delta_accuracy": adaptive_metrics["accuracy"] - baseline_metrics["accuracy"],
            "phase_gate": phase_gate.__dict__,
        }

    def _score_window(self, engine: KNNEvolver, records: Sequence[dict]) -> list[dict]:
        trades: list[dict] = []
        for item in records:
            prediction = engine.predict(
                item["features"],
                timestamp=item["timestamp"],
                volatility=item.get("volatility", 1.0),
                baseline_volatility=item.get("baseline_volatility", item.get("volatility", 1.0)),
                trend=item.get("trend", 0.0),
                shock=item.get("shock", 0.0),
            )
            label = prediction.get("label")
            trades.append(
                {
                    "timestamp": item["timestamp"],
                    "expected": item["label"],
                    "predicted": label,
                    "correct": label == item["label"],
                    "confidence": float(prediction.get("confidence", 0.0)),
                }
            )
            engine.add_sample(
                item["features"],
                label=item["label"],
                timestamp=item["timestamp"],
                volatility=item.get("volatility", 1.0),
                baseline_volatility=item.get("baseline_volatility", item.get("volatility", 1.0)),
                trend=item.get("trend", 0.0),
                shock=item.get("shock", 0.0),
                regime=item.get("regime"),
                meta=item.get("meta"),
            )
        return trades

    @staticmethod
    def phase_gate(*, old_metrics: dict, new_metrics: dict, windows: Sequence[WindowBacktestResult]) -> PhaseGateResult:
        delta = float(new_metrics.get("accuracy", 0.0)) - float(old_metrics.get("accuracy", 0.0))
        window_deltas = [item.delta_accuracy for item in windows]
        stable_windows = sum(1 for value in window_deltas if value >= 0.0)
        phase = "phase2" if delta >= 0.03 and stable_windows == len(window_deltas) else "phase1"
        approved = delta >= 0.0 and stable_windows >= max(1, len(window_deltas) // 2)
        reason = (
            "adaptive weights outperform baseline and pass rollout gate"
            if approved
            else "adaptive weights require observe-only rollout"
        )
        return PhaseGateResult(
            approved=approved,
            phase=phase,
            reason=reason,
            metrics={
                "delta_accuracy": round(delta, 6),
                "stable_windows": stable_windows,
                "total_windows": len(window_deltas),
                "old_accuracy": round(float(old_metrics.get("accuracy", 0.0)), 6),
                "new_accuracy": round(float(new_metrics.get("accuracy", 0.0)), 6),
            },
        )


def walk_forward_backtest(
    records: Iterable[dict],
    *,
    baseline_factory: Callable[[], KNNEvolver] | None = None,
    adaptive_factory: Callable[[], KNNEvolver] | None = None,
    window_size: int = 60,
) -> dict:
    """Execute community walk-forward backtest for old vs new KNN weights."""

    analyzer = WalkForwardAnalyzer(
        baseline_factory=baseline_factory,
        adaptive_factory=adaptive_factory,
        window_size=window_size,
    )
    report = analyzer.evaluate(records)
    report["mode"] = "walk_forward"
    return report


__all__ = [
    "PhaseGateResult",
    "WalkForwardAnalyzer",
    "WindowBacktestResult",
    "walk_forward_backtest",
    "out_of_sample_metrics",
]

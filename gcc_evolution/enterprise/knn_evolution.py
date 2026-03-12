"""Community KNN evolution helpers.

This module provides a deterministic community-safe KNN engine with:
- Phase 1: volatility-aware forgetting and 5-bucket regime tagging
- Phase 2: recent-window TTA normalization and drift-aware old-sample downweight

It is intentionally lightweight and avoids external ML dependencies so the
open-source package can still expose a usable adaptive baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, sqrt
from statistics import mean
from typing import Iterable, Sequence


REGIME_BULL = "bull"
REGIME_BEAR = "bear"
REGIME_SIDE = "side"
REGIME_HIGH_VOL = "high_vol"
REGIME_CRISIS = "crisis"
REGIME_ORDER = (
    REGIME_BULL,
    REGIME_SIDE,
    REGIME_BEAR,
    REGIME_HIGH_VOL,
    REGIME_CRISIS,
)
_REGIME_DISTANCE = {
    REGIME_BULL: 0,
    REGIME_SIDE: 1,
    REGIME_BEAR: 2,
    REGIME_HIGH_VOL: 3,
    REGIME_CRISIS: 4,
}
_REGIME_DECAY = {
    REGIME_BULL: 0.7,
    REGIME_SIDE: 1.0,
    REGIME_BEAR: 1.2,
    REGIME_HIGH_VOL: 1.7,
    REGIME_CRISIS: 2.4,
}


@dataclass
class Neighbor:
    """Search result with ranking metadata."""

    label: str
    distance: float
    score: float
    regime: str
    timestamp: int
    meta: dict


@dataclass
class Sample:
    """Single KNN history item."""

    features: list[float]
    label: str
    timestamp: int
    regime: str
    volatility: float
    meta: dict
    drift_epoch: int


def _coerce_features(features: Sequence[float]) -> list[float]:
    return [float(v) for v in features]


def _safe_mean(values: Iterable[float], default: float = 0.0) -> float:
    items = list(values)
    return float(mean(items)) if items else float(default)


def _safe_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 1.0
    avg = _safe_mean(values)
    var = sum((float(v) - avg) ** 2 for v in values) / float(len(values))
    return max(sqrt(var), 1e-6)


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = max(0.0, min(1.0, q)) * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def _histogram(
    values: Sequence[float],
    bins: int = 10,
    *,
    lo: float | None = None,
    hi: float | None = None,
) -> list[float]:
    if not values:
        return [1.0 / bins] * bins
    lo = min(values) if lo is None else lo
    hi = max(values) if hi is None else hi
    if abs(hi - lo) < 1e-9:
        counts = [0.0] * bins
        counts[bins // 2] = 1.0
        return counts
    width = (hi - lo) / bins
    counts = [0.0] * bins
    for raw in values:
        idx = int((raw - lo) / width)
        idx = max(0, min(bins - 1, idx if idx < bins else bins - 1))
        counts[idx] += 1.0
    total = sum(counts) or 1.0
    return [c / total for c in counts]


def _psi(expected: Sequence[float], actual: Sequence[float], bins: int = 10) -> float:
    if not expected and not actual:
        return 0.0
    combined = list(expected) + list(actual)
    lo = min(combined) if combined else 0.0
    hi = max(combined) if combined else 1.0
    exp_hist = _histogram(expected, bins=bins, lo=lo, hi=hi)
    act_hist = _histogram(actual, bins=bins, lo=lo, hi=hi)
    psi = 0.0
    for e, a in zip(exp_hist, act_hist):
        e = max(e, 1e-6)
        a = max(a, 1e-6)
        psi += (a - e) * __import__("math").log(a / e)
    return float(psi)


def _ks(expected: Sequence[float], actual: Sequence[float]) -> float:
    if not expected or not actual:
        return 0.0
    left = sorted(float(v) for v in expected)
    right = sorted(float(v) for v in actual)
    points = sorted(set(left + right))
    max_gap = 0.0
    for point in points:
        cdf_left = sum(1 for v in left if v <= point) / len(left)
        cdf_right = sum(1 for v in right if v <= point) / len(right)
        max_gap = max(max_gap, abs(cdf_left - cdf_right))
    return float(max_gap)


class KNNEvolver:
    """Lightweight adaptive KNN baseline for the open-source package."""

    def __init__(
        self,
        *,
        k: int = 5,
        recent_window: int = 50,
        base_forgetting: float = 0.015,
        drift_psi_threshold: float = 0.2,
        drift_ks_threshold: float = 0.1,
        cleanup_age: int = 60,
        min_regime_trend: float = 0.15,
    ) -> None:
        self.k = max(1, int(k))
        self.recent_window = max(3, int(recent_window))
        self.base_forgetting = max(1e-4, float(base_forgetting))
        self.drift_psi_threshold = max(0.01, float(drift_psi_threshold))
        self.drift_ks_threshold = max(0.01, float(drift_ks_threshold))
        self.cleanup_age = max(5, int(cleanup_age))
        self.min_regime_trend = float(min_regime_trend)
        self.samples: list[Sample] = []
        self.drift_epoch = 0
        self.consecutive_drifts = 0
        self.last_drift_report: dict = {
            "drift": False,
            "psi": 0.0,
            "ks": 0.0,
            "epoch": 0,
            "cleaned": 0,
        }

    @staticmethod
    def infer_regime(
        *,
        volatility: float,
        baseline_volatility: float,
        trend: float,
        shock: float = 0.0,
    ) -> str:
        baseline = max(abs(float(baseline_volatility)), 1e-6)
        vol_ratio = abs(float(volatility)) / baseline
        trend = float(trend)
        shock = float(shock)
        if vol_ratio >= 2.0 or shock <= -2.5 * baseline:
            return REGIME_CRISIS
        if vol_ratio >= 1.5:
            return REGIME_HIGH_VOL
        if trend >= 0.15:
            return REGIME_BULL
        if trend <= -0.15:
            return REGIME_BEAR
        return REGIME_SIDE

    def dynamic_forgetting_factor(
        self,
        *,
        regime: str,
        volatility: float,
        baseline_volatility: float,
    ) -> float:
        baseline = max(abs(float(baseline_volatility)), 1e-6)
        vol_ratio = max(0.25, abs(float(volatility)) / baseline)
        regime_factor = _REGIME_DECAY.get(regime, 1.0)
        return self.base_forgetting * regime_factor * min(max(vol_ratio, 0.5), 3.0)

    def add_sample(
        self,
        features: Sequence[float],
        *,
        label: str,
        timestamp: int,
        volatility: float,
        baseline_volatility: float,
        trend: float,
        shock: float = 0.0,
        regime: str | None = None,
        meta: dict | None = None,
    ) -> Sample:
        resolved_regime = regime or self.infer_regime(
            volatility=volatility,
            baseline_volatility=baseline_volatility,
            trend=trend,
            shock=shock,
        )
        sample = Sample(
            features=_coerce_features(features),
            label=str(label),
            timestamp=int(timestamp),
            regime=resolved_regime,
            volatility=float(volatility),
            meta=dict(meta or {}),
            drift_epoch=self.drift_epoch,
        )
        self.samples.append(sample)
        self.samples.sort(key=lambda item: item.timestamp)
        return sample

    def fit(self, samples: Iterable[dict]) -> "KNNEvolver":
        self.samples = []
        self.drift_epoch = 0
        self.consecutive_drifts = 0
        for raw in samples:
            self.add_sample(
                raw["features"],
                label=raw["label"],
                timestamp=raw["timestamp"],
                volatility=raw.get("volatility", 1.0),
                baseline_volatility=raw.get("baseline_volatility", raw.get("volatility", 1.0)),
                trend=raw.get("trend", 0.0),
                shock=raw.get("shock", 0.0),
                regime=raw.get("regime"),
                meta=raw.get("meta"),
            )
        return self

    def _recent_samples(self) -> list[Sample]:
        if not self.samples:
            return []
        return self.samples[-self.recent_window :]

    def _tta_stats(self) -> tuple[list[float], list[float]]:
        recent = self._recent_samples()
        if not recent:
            return ([], [])
        dims = len(recent[0].features)
        means = []
        stds = []
        for idx in range(dims):
            values = [sample.features[idx] for sample in recent]
            means.append(_safe_mean(values))
            stds.append(_safe_std(values))
        return means, stds

    def _normalize_with_tta(self, features: Sequence[float]) -> list[float]:
        values = _coerce_features(features)
        means, stds = self._tta_stats()
        if not means:
            return values
        return [(val - means[idx]) / stds[idx] for idx, val in enumerate(values)]

    def _regime_similarity(self, left: str, right: str) -> float:
        distance = abs(_REGIME_DISTANCE.get(left, 1) - _REGIME_DISTANCE.get(right, 1))
        return 1.0 / (1.0 + 0.5 * distance)

    def _drift_penalty(self, sample: Sample) -> float:
        if self.drift_epoch <= 0 or sample.drift_epoch >= self.drift_epoch:
            return 1.0
        return 0.5

    def _cleanup_on_consecutive_drift(self, current_time: int) -> int:
        if self.consecutive_drifts < 2:
            return 0
        cutoff = int(current_time) - self.cleanup_age
        before = len(self.samples)
        self.samples = [sample for sample in self.samples if sample.timestamp >= cutoff]
        return before - len(self.samples)

    def detect_drift(self) -> dict:
        min_required = max(2 * max(2, self.recent_window), 8)
        if len(self.samples) < min_required:
            self.last_drift_report = {
                "drift": False,
                "psi": 0.0,
                "ks": 0.0,
                "epoch": self.drift_epoch,
                "cleaned": 0,
            }
            return dict(self.last_drift_report)

        window = min(self.recent_window, len(self.samples) // 2)
        previous = self.samples[-2 * window : -window]
        recent = self.samples[-window:]
        psi_values = []
        ks_values = []
        dims = len(recent[0].features)
        for idx in range(dims):
            old_values = [sample.features[idx] for sample in previous]
            new_values = [sample.features[idx] for sample in recent]
            psi_values.append(_psi(old_values, new_values))
            ks_values.append(_ks(old_values, new_values))
        avg_psi = _safe_mean(psi_values)
        avg_ks = _safe_mean(ks_values)
        drift = avg_psi >= self.drift_psi_threshold or avg_ks >= self.drift_ks_threshold
        cleaned = 0
        if drift:
            self.drift_epoch += 1
            self.consecutive_drifts += 1
            cleaned = self._cleanup_on_consecutive_drift(self.samples[-1].timestamp)
        else:
            self.consecutive_drifts = 0
        self.last_drift_report = {
            "drift": bool(drift),
            "psi": round(avg_psi, 6),
            "ks": round(avg_ks, 6),
            "epoch": self.drift_epoch,
            "cleaned": cleaned,
        }
        return dict(self.last_drift_report)

    def query(
        self,
        features: Sequence[float],
        *,
        timestamp: int,
        volatility: float,
        baseline_volatility: float,
        trend: float,
        shock: float = 0.0,
        top_k: int | None = None,
    ) -> list[Neighbor]:
        if not self.samples:
            return []

        current_regime = self.infer_regime(
            volatility=volatility,
            baseline_volatility=baseline_volatility,
            trend=trend,
            shock=shock,
        )
        normalized_query = self._normalize_with_tta(features)
        drift_report = self.detect_drift()
        _ = drift_report
        neighbors: list[Neighbor] = []
        for sample in self.samples:
            normalized_sample = self._normalize_with_tta(sample.features)
            distance = sqrt(
                sum((normalized_query[idx] - normalized_sample[idx]) ** 2 for idx in range(len(normalized_query)))
            )
            forget = self.dynamic_forgetting_factor(
                regime=sample.regime,
                volatility=sample.volatility,
                baseline_volatility=baseline_volatility,
            )
            age = max(0, int(timestamp) - int(sample.timestamp))
            time_weight = exp(-forget * age)
            regime_weight = self._regime_similarity(sample.regime, current_regime)
            drift_penalty = self._drift_penalty(sample)
            score = (1.0 / (1.0 + distance)) * time_weight * regime_weight * drift_penalty
            neighbors.append(
                Neighbor(
                    label=sample.label,
                    distance=distance,
                    score=score,
                    regime=sample.regime,
                    timestamp=sample.timestamp,
                    meta=dict(sample.meta),
                )
            )
        neighbors.sort(key=lambda item: item.score, reverse=True)
        return neighbors[: max(1, int(top_k or self.k))]

    def predict(self, *args, **kwargs) -> dict:
        neighbors = self.query(*args, **kwargs)
        if not neighbors:
            return {"label": None, "confidence": 0.0, "neighbors": []}
        votes: dict[str, float] = {}
        for item in neighbors:
            votes[item.label] = votes.get(item.label, 0.0) + item.score
        label, weight = max(votes.items(), key=lambda pair: pair[1])
        total = sum(votes.values()) or 1.0
        return {
            "label": label,
            "confidence": weight / total,
            "neighbors": neighbors,
            "drift": dict(self.last_drift_report),
        }

    def snapshot(self) -> dict:
        means, stds = self._tta_stats()
        return {
            "samples": len(self.samples),
            "recent_window": self.recent_window,
            "drift_epoch": self.drift_epoch,
            "consecutive_drifts": self.consecutive_drifts,
            "regimes": sorted({sample.regime for sample in self.samples}),
            "tta_mean": means,
            "tta_std": stds,
            "last_drift_report": dict(self.last_drift_report),
        }


def adaptive_knn_search(
    history: Iterable[dict],
    query_features: Sequence[float],
    *,
    timestamp: int,
    volatility: float,
    baseline_volatility: float,
    trend: float,
    shock: float = 0.0,
    k: int = 5,
    recent_window: int = 50,
) -> list[Neighbor]:
    """Convenience wrapper for one-off adaptive KNN search."""

    engine = KNNEvolver(k=k, recent_window=recent_window)
    engine.fit(history)
    return engine.query(
        query_features,
        timestamp=timestamp,
        volatility=volatility,
        baseline_volatility=baseline_volatility,
        trend=trend,
        shock=shock,
        top_k=k,
    )


def knn_feature_importance(history: Iterable[dict]) -> dict[int, float]:
    """Approximate per-feature importance from label separation."""

    samples = list(history)
    if not samples:
        return {}
    dims = len(samples[0]["features"])
    labels = sorted({str(item["label"]) for item in samples})
    if len(labels) < 2:
        return {idx: 0.0 for idx in range(dims)}

    grouped = {label: [] for label in labels}
    for item in samples:
        grouped[str(item["label"])].append(_coerce_features(item["features"]))

    scores: dict[int, float] = {}
    for idx in range(dims):
        per_label_mean = [_safe_mean([row[idx] for row in grouped[label]]) for label in labels]
        center = _safe_mean(per_label_mean)
        scores[idx] = _safe_mean(abs(val - center) for val in per_label_mean)

    total = sum(scores.values()) or 1.0
    return {idx: round(value / total, 6) for idx, value in scores.items()}


__all__ = [
    "KNNEvolver",
    "Neighbor",
    "REGIME_BULL",
    "REGIME_BEAR",
    "REGIME_SIDE",
    "REGIME_HIGH_VOL",
    "REGIME_CRISIS",
    "REGIME_ORDER",
    "adaptive_knn_search",
    "build_accuracy_matrix",
    "build_daily_accuracy_report",
    "build_heatmap_payload",
    "knn_feature_importance",
]


def build_accuracy_matrix(rows: Iterable[dict]) -> dict:
    """Build per-plugin x symbol accuracy matrix."""

    matrix: dict[str, dict[str, dict]] = {}
    for row in rows:
        plugin = str(row.get("plugin", "unknown"))
        symbol = str(row.get("symbol", "unknown"))
        cell = matrix.setdefault(plugin, {}).setdefault(
            symbol,
            {"correct": 0, "total": 0, "accuracy": 0.0},
        )
        cell["total"] += 1
        if row.get("correct"):
            cell["correct"] += 1
    for plugin_cells in matrix.values():
        for cell in plugin_cells.values():
            total = cell["total"] or 1
            cell["accuracy"] = cell["correct"] / total
    return matrix


def build_heatmap_payload(rows: Iterable[dict]) -> dict:
    """Convert accuracy rows into dashboard-friendly heatmap payload."""

    matrix = build_accuracy_matrix(rows)
    plugins = sorted(matrix.keys())
    symbols = sorted({symbol for plugin in plugins for symbol in matrix[plugin].keys()})
    values = []
    for plugin in plugins:
        row_values = []
        for symbol in symbols:
            cell = matrix.get(plugin, {}).get(symbol)
            row_values.append(None if cell is None else round(cell["accuracy"], 4))
        values.append(row_values)
    return {
        "plugins": plugins,
        "symbols": symbols,
        "values": values,
        "matrix": matrix,
    }


def build_daily_accuracy_report(rows: Iterable[dict], *, top_k: int = 5) -> dict:
    """Build top/bottom summary for daily audit mail or dashboard."""

    matrix = build_accuracy_matrix(rows)
    flat = []
    for plugin, symbols in matrix.items():
        for symbol, cell in symbols.items():
            flat.append(
                {
                    "plugin": plugin,
                    "symbol": symbol,
                    "accuracy": round(cell["accuracy"], 4),
                    "correct": cell["correct"],
                    "total": cell["total"],
                }
            )
    flat.sort(key=lambda item: (item["accuracy"], item["total"]))
    bottom = flat[: max(1, top_k)]
    top = list(reversed(flat[-max(1, top_k) :]))
    return {
        "summary": {
            "pairs": len(flat),
            "plugins": len(matrix),
            "symbols": len({item["symbol"] for item in flat}),
            "avg_accuracy": round(_safe_mean(item["accuracy"] for item in flat), 4) if flat else 0.0,
        },
        "top": top,
        "bottom": bottom,
        "heatmap": build_heatmap_payload(rows),
    }

"""
GCC v5.340 — Skeptic Hold-out Framework (IRS-003)

Apache 2.0 — open-source interface layer.
The Skeptic evaluation strategy (thresholds, signal scoring) is private (BUSL 1.1).

Theory grounding (Verification Priority Theorem, Brenner et al. 2026):
    "Quality(output) ≤ f(Precision(verifier), Independence(verifier, generator))"

    The verifier (Skeptic) must be computationally independent from the generator.
    If Skeptic uses the same data the signal was optimized on, it becomes the
    generator's accomplice — Goodhart's Law on the verifier.

    IRS-003 enforces strict data isolation:
        Training set  → signal optimization only  (Skeptic CANNOT access)
        Validation set → Skeptic evaluation only  (15% hold-out per window)
        Test set      → final OOS reporting        (touched once, at release)

Walk-forward split design (per window):
    |<——— 70% train ———>|<— 15% validate —>|<— 15% test —>|
    Signal generator uses train only.
    Skeptic gate evaluates on validate only.
    Test is reserved for the final monthly report.

Overfitting detection criterion:
    IS_IC   = mean IC on training set
    OOS_IC  = mean IC on validation set
    IS/OOS ratio > overfit_threshold (default 2.0) → OVERFIT flag
    Correlation(IS_IC_series, OOS_IC_series) < 0.7  → DRIFT flag

Usage::

    from gcc_evolution.holdout import HoldoutSplitter, SkepticGate, OverfitDetector

    # Split records into walk-forward windows
    splitter = HoldoutSplitter(validate_ratio=0.15, test_ratio=0.15)
    windows = splitter.split(records, window_size=200)

    for w in windows:
        train_data    = w.train      # signal generator sees this
        validate_data = w.validate   # Skeptic sees this ONLY

        gate = SkepticGate(w)
        safe = gate.get_validate()   # always returns validate split
        # gate.get_train() → raises SkepticAccessError (hard block)

    detector = OverfitDetector()
    result = detector.check(is_ic=0.08, oos_ic=0.02)
    if result.is_overfit:
        print(result.reason)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════

class SkepticAccessError(Exception):
    """
    Raised when Skeptic code tries to access training data.
    This is a hard architectural boundary — never catch and ignore.
    """
    def __init__(self, msg: str = "Skeptic cannot access training data"):
        super().__init__(msg)


# ═══════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════

@dataclass
class WalkForwardWindow(Generic[T]):
    """
    One walk-forward window with strict three-way split.

    Attributes:
        window_id:    index of this window (0-based)
        train:        training records — for signal generator only
        validate:     validation records — for Skeptic only (15% hold-out)
        test:         test records — reserved for final OOS report
        train_start:  ISO timestamp of first training record
        train_end:    ISO timestamp of last training record
        validate_end: ISO timestamp of last validation record
        test_end:     ISO timestamp of last test record
        metadata:     optional domain metadata
    """
    window_id:    int
    train:        list[T]
    validate:     list[T]
    test:         list[T]
    train_start:  str = ""
    train_end:    str = ""
    validate_end: str = ""
    test_end:     str = ""
    metadata:     dict = field(default_factory=dict)

    @property
    def n_train(self) -> int:
        return len(self.train)

    @property
    def n_validate(self) -> int:
        return len(self.validate)

    @property
    def n_test(self) -> int:
        return len(self.test)

    @property
    def total(self) -> int:
        return self.n_train + self.n_validate + self.n_test

    def validate_ratio_actual(self) -> float:
        return self.n_validate / self.total if self.total else 0.0

    def summary(self) -> str:
        return (
            f"Window[{self.window_id}] "
            f"train={self.n_train} validate={self.n_validate} test={self.n_test} "
            f"(validate={self.validate_ratio_actual():.0%})"
        )


@dataclass
class OverfitCheckResult:
    """
    Result of an IS/OOS overfitting check.

    is_overfit:  True when signal shows in-sample bias
    flags:       list of triggered flags ('RATIO', 'CORR', 'NEGATIVE_OOS')
    is_ic:       in-sample IC
    oos_ic:      out-of-sample IC
    ratio:       is_ic / oos_ic (or inf if oos_ic ≈ 0)
    correlation: Pearson r of IS vs OOS IC series (when series provided)
    reason:      human-readable explanation
    """
    is_overfit:  bool
    flags:       list[str] = field(default_factory=list)
    is_ic:       float = 0.0
    oos_ic:      float = 0.0
    ratio:       float = 0.0
    correlation: float | None = None
    reason:      str = ""

    def to_dict(self) -> dict:
        return {
            "is_overfit":  self.is_overfit,
            "flags":       self.flags,
            "is_ic":       round(self.is_ic, 6),
            "oos_ic":      round(self.oos_ic, 6),
            "ratio":       round(self.ratio, 4),
            "correlation": round(self.correlation, 4) if self.correlation is not None else None,
            "reason":      self.reason,
        }


# ═══════════════════════════════════════════════════════════════════
# HoldoutSplitter
# ═══════════════════════════════════════════════════════════════════

class HoldoutSplitter:
    """
    Splits a time-ordered sequence into walk-forward windows,
    each with a reserved Skeptic validation set and a final test set.

    Open-source (Apache 2.0).  The private engine adds:
      - Adaptive window sizing based on regime changes
      - Stratified splitting to balance regime distribution
      - DuckDB persistence of split metadata

    Args:
        validate_ratio: fraction reserved for Skeptic (default 0.15)
        test_ratio:     fraction reserved for final OOS test (default 0.15)
        min_train:      minimum training records per window (default 30)
    """

    def __init__(
        self,
        validate_ratio: float = 0.15,
        test_ratio:     float = 0.15,
        min_train:      int   = 30,
    ):
        if validate_ratio + test_ratio >= 1.0:
            raise ValueError(
                f"validate_ratio ({validate_ratio}) + test_ratio ({test_ratio}) must be < 1.0"
            )
        if validate_ratio <= 0 or test_ratio <= 0:
            raise ValueError("validate_ratio and test_ratio must be > 0")
        self.validate_ratio = validate_ratio
        self.test_ratio     = test_ratio
        self.min_train      = min_train

    def split(
        self,
        records: Sequence[T],
        window_size: int | None = None,
        timestamp_fn: Any = None,
    ) -> list[WalkForwardWindow[T]]:
        """
        Split records into walk-forward windows.

        Args:
            records:      time-ordered sequence (oldest first)
            window_size:  records per window; None = single window over all records
            timestamp_fn: optional callable(record) → ISO str for timestamp extraction

        Returns:
            list of WalkForwardWindow, one per walk-forward step
        """
        records = list(records)
        if not records:
            return []

        if window_size is None:
            window_size = len(records)

        windows: list[WalkForwardWindow] = []
        step = max(1, window_size)
        n = len(records)

        for start in range(0, n, step):
            chunk = records[start: start + window_size]
            if len(chunk) < self.min_train + 2:
                logger.debug("[HOLDOUT] Window %d too small (%d records), skipping",
                             len(windows), len(chunk))
                continue

            window = self._make_window(len(windows), chunk, timestamp_fn)
            if window.n_train < self.min_train:
                logger.debug("[HOLDOUT] Window %d train set too small (%d), skipping",
                             len(windows), window.n_train)
                continue

            windows.append(window)
            logger.debug("[HOLDOUT] %s", window.summary())

        logger.info("[HOLDOUT] Created %d walk-forward windows from %d records", len(windows), n)
        return windows

    def _make_window(
        self,
        window_id: int,
        chunk: list[T],
        timestamp_fn: Any,
    ) -> WalkForwardWindow[T]:
        n          = len(chunk)
        n_val      = max(1, math.floor(n * self.validate_ratio))
        n_test     = max(1, math.floor(n * self.test_ratio))
        n_train    = n - n_val - n_test

        train    = chunk[:n_train]
        validate = chunk[n_train: n_train + n_val]
        test     = chunk[n_train + n_val:]

        ts_train_start = ts_train_end = ts_val_end = ts_test_end = ""
        if timestamp_fn and train:
            try:
                ts_train_start = str(timestamp_fn(train[0]))
                ts_train_end   = str(timestamp_fn(train[-1]))
                ts_val_end     = str(timestamp_fn(validate[-1])) if validate else ""
                ts_test_end    = str(timestamp_fn(test[-1]))     if test     else ""
            except Exception as e:
                logger.debug("[HOLDOUT] timestamp_fn failed: %s", e)

        return WalkForwardWindow(
            window_id=window_id,
            train=train,
            validate=validate,
            test=test,
            train_start=ts_train_start,
            train_end=ts_train_end,
            validate_end=ts_val_end,
            test_end=ts_test_end,
        )


# ═══════════════════════════════════════════════════════════════════
# SkepticGate  — hard data access boundary
# ═══════════════════════════════════════════════════════════════════

class SkepticGate:
    """
    Enforces the Skeptic's data access boundary.

    Skeptic is ONLY allowed to read the validation split.
    Any attempt to read training data raises SkepticAccessError.

    This is the open-source architectural contract.  The private
    Skeptic strategy implementation must use SkepticGate; it cannot
    bypass the boundary.

    Open-source (Apache 2.0).  Private Skeptic strategy (BUSL 1.1).

    Example::

        gate = SkepticGate(window)
        data = gate.get_validate()    # OK
        gate.get_train()              # raises SkepticAccessError
    """

    def __init__(self, window: WalkForwardWindow):
        self._window = window

    def get_validate(self) -> list:
        """Return the validation split. Always safe for Skeptic to call."""
        return list(self._window.validate)

    def get_test(self) -> list:
        """Return the test split. Use only for final OOS reporting."""
        return list(self._window.test)

    def get_train(self) -> list:
        """
        Blocked.  Skeptic must never access training data.
        Raises SkepticAccessError unconditionally.
        """
        raise SkepticAccessError(
            f"Skeptic is not allowed to access training data "
            f"(window {self._window.window_id}, "
            f"{self._window.n_train} train records are off-limits)"
        )

    @property
    def window_id(self) -> int:
        return self._window.window_id

    @property
    def n_validate(self) -> int:
        return self._window.n_validate


# ═══════════════════════════════════════════════════════════════════
# OverfitDetector
# ═══════════════════════════════════════════════════════════════════

class OverfitDetector:
    """
    Detects in-sample overfitting using IS/OOS IC comparison.

    Verification Priority Theorem implication:
        A signal improvement that looks good IS but degrades OOS is not
        a real discovery — it is noise that the generator overfitted to.
        The Skeptic must intercept such improvements.

    Detection criteria:
        RATIO flag:        IS_IC / OOS_IC > overfit_threshold (default 2.0)
        NEGATIVE_OOS flag: OOS_IC < negative_oos_floor (default -0.01)
        CORR flag:         correlation(IS_series, OOS_series) < min_corr (default 0.7)
                           (only checked when series are provided)

    Open-source (Apache 2.0).  Private engine adds:
      - Walk-forward IC series computation from DecisionRecord logs
      - PSI/KS test for distribution drift
      - DuckDB persistence + Dashboard display

    Args:
        overfit_threshold:  IS/OOS ratio above which RATIO flag fires (default 2.0)
        negative_oos_floor: OOS IC below this floor fires NEGATIVE_OOS (default -0.01)
        min_corr:           minimum IS/OOS series correlation (default 0.7)
    """

    def __init__(
        self,
        overfit_threshold:  float = 2.0,
        negative_oos_floor: float = -0.01,
        min_corr:           float = 0.7,
    ):
        self.overfit_threshold  = overfit_threshold
        self.negative_oos_floor = negative_oos_floor
        self.min_corr           = min_corr

    def check(
        self,
        is_ic:        float,
        oos_ic:       float,
        is_series:    list[float] | None = None,
        oos_series:   list[float] | None = None,
    ) -> OverfitCheckResult:
        """
        Check a single IS/OOS IC pair for overfitting.

        Args:
            is_ic:      in-sample IC (mean over training window)
            oos_ic:     out-of-sample IC (mean over validation window)
            is_series:  optional time series of IS IC per sub-period (for correlation check)
            oos_series: optional time series of OOS IC per sub-period
        """
        flags: list[str] = []
        reasons: list[str] = []

        # NEGATIVE_OOS: OOS IC is significantly negative
        if oos_ic < self.negative_oos_floor:
            flags.append("NEGATIVE_OOS")
            reasons.append(
                f"OOS IC ({oos_ic:.4f}) below floor ({self.negative_oos_floor:.4f})"
            )

        # RATIO: IS IC is much higher than OOS IC (overfit proxy)
        ratio = 0.0
        if abs(oos_ic) > 1e-9:
            ratio = is_ic / oos_ic
            if ratio > self.overfit_threshold and is_ic > 0 and oos_ic > 0:
                flags.append("RATIO")
                reasons.append(
                    f"IS/OOS ratio ({ratio:.2f}) exceeds threshold ({self.overfit_threshold})"
                )
        elif is_ic > 0.02 and oos_ic <= 0:
            # IS positive but OOS near-zero or negative
            flags.append("RATIO")
            ratio = float("inf")
            reasons.append(
                f"IS IC positive ({is_ic:.4f}) but OOS IC near-zero or negative ({oos_ic:.4f})"
            )

        # CORR: correlation of IS/OOS series below minimum
        corr: float | None = None
        if is_series and oos_series and len(is_series) == len(oos_series) >= 3:
            corr = _pearson(is_series, oos_series)
            if corr < self.min_corr:
                flags.append("CORR")
                reasons.append(
                    f"IS/OOS IC correlation ({corr:.3f}) below minimum ({self.min_corr})"
                )

        is_overfit = len(flags) > 0
        reason = "; ".join(reasons) if reasons else "No overfitting detected"

        result = OverfitCheckResult(
            is_overfit=is_overfit,
            flags=flags,
            is_ic=is_ic,
            oos_ic=oos_ic,
            ratio=ratio,
            correlation=corr,
            reason=reason,
        )

        if is_overfit:
            logger.warning("[OVERFIT_DETECTOR] Overfit detected — flags=%s — %s", flags, reason)
        else:
            logger.debug("[OVERFIT_DETECTOR] No overfitting detected (IS=%.4f OOS=%.4f)", is_ic, oos_ic)

        return result

    def check_series(
        self,
        is_series:  list[float],
        oos_series: list[float],
    ) -> OverfitCheckResult:
        """
        Convenience method: check using full series mean as scalar IC
        and the series themselves for correlation.
        """
        if not is_series or not oos_series:
            raise ValueError("is_series and oos_series must not be empty")
        is_ic  = sum(is_series)  / len(is_series)
        oos_ic = sum(oos_series) / len(oos_series)
        return self.check(is_ic, oos_ic, is_series, oos_series)


# ═══════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════

def _pearson(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation coefficient between two equal-length lists."""
    n = len(x)
    if n < 2:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx  = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy  = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx < 1e-12 or dy < 1e-12:
        return 0.0
    return num / (dx * dy)


# ═══════════════════════════════════════════════════════════════════
# SkepticMonitor — false-positive / false-negative tracking (S24~S25)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SkepticVerdict:
    """
    A single Skeptic evaluation verdict.

    predicted_overfit: True  = Skeptic flagged this window as overfit
    actual_overfit:    True  = actual OOS performance confirmed overfit
                       (measured after the next walk-forward window)
    window_id:         identifier of the walk-forward window
    is_ic:             in-sample IC that triggered (or didn't trigger) the flag
    oos_ic:            out-of-sample IC used for ground-truth confirmation
    """
    predicted_overfit: bool
    actual_overfit:    bool
    window_id:         str   = ""
    is_ic:             float = 0.0
    oos_ic:            float = 0.0
    evaluated_at:      str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_false_positive(self) -> bool:
        """Skeptic flagged overfit, but actual OOS was fine."""
        return self.predicted_overfit and not self.actual_overfit

    @property
    def is_false_negative(self) -> bool:
        """Skeptic passed the window, but actual OOS was overfit."""
        return not self.predicted_overfit and self.actual_overfit

    @property
    def is_true_positive(self) -> bool:
        return self.predicted_overfit and self.actual_overfit

    @property
    def is_true_negative(self) -> bool:
        return not self.predicted_overfit and not self.actual_overfit


class SkepticMonitor:
    """
    Tracks Skeptic gate false-positive and false-negative rates.

    IRS-003 S24 acceptance criterion:
        False-positive rate  < 10%   (Skeptic wrongly blocks good signals)
        False-negative rate  < 5%    (Skeptic misses actual overfits)

    Usage::

        monitor = SkepticMonitor()

        # After each walk-forward window:
        verdict = SkepticVerdict(
            predicted_overfit=detector_result.is_overfit,
            actual_overfit=True,   # measured from next window
            window_id="W-003",
            is_ic=0.08,
            oos_ic=0.001,
        )
        monitor.record(verdict)

        report = monitor.report()
        print(report["false_positive_rate"])   # target < 0.10
        print(report["false_negative_rate"])   # target < 0.05

    IRS-003 S25 — acceptance report::

        print(monitor.acceptance_report())

    Args:
        fp_threshold: max acceptable false-positive rate (default 0.10)
        fn_threshold: max acceptable false-negative rate (default 0.05)
        window_size:  sliding window for rate computation (default 100)
    """

    def __init__(
        self,
        fp_threshold: float = 0.10,
        fn_threshold: float = 0.05,
        window_size:  int   = 100,
    ):
        self.fp_threshold = fp_threshold
        self.fn_threshold = fn_threshold
        self.window_size  = window_size
        self._verdicts: list[SkepticVerdict] = []

    def record(self, verdict: SkepticVerdict) -> None:
        """Record one Skeptic verdict (evict oldest if window full)."""
        self._verdicts.append(verdict)
        if len(self._verdicts) > self.window_size:
            self._verdicts = self._verdicts[-self.window_size:]
        logger.debug(
            "[SKEPTIC_MONITOR] window=%s fp=%s fn=%s",
            verdict.window_id,
            verdict.is_false_positive,
            verdict.is_false_negative,
        )

    def _counts(self) -> dict[str, int]:
        tp = sum(1 for v in self._verdicts if v.is_true_positive)
        tn = sum(1 for v in self._verdicts if v.is_true_negative)
        fp = sum(1 for v in self._verdicts if v.is_false_positive)
        fn = sum(1 for v in self._verdicts if v.is_false_negative)
        return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}

    @property
    def false_positive_rate(self) -> float:
        """FP / (FP + TN) — rate of wrongly blocking good signals."""
        c = self._counts()
        denom = c["fp"] + c["tn"]
        return c["fp"] / denom if denom else 0.0

    @property
    def false_negative_rate(self) -> float:
        """FN / (FN + TP) — rate of missing actual overfits."""
        c = self._counts()
        denom = c["fn"] + c["tp"]
        return c["fn"] / denom if denom else 0.0

    @property
    def precision(self) -> float:
        """TP / (TP + FP)."""
        c = self._counts()
        denom = c["tp"] + c["fp"]
        return c["tp"] / denom if denom else 0.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN) — fraction of actual overfits detected."""
        c = self._counts()
        denom = c["tp"] + c["fn"]
        return c["tp"] / denom if denom else 0.0

    def passes_acceptance(self) -> bool:
        """True when both FP and FN rates are within thresholds."""
        return (
            self.false_positive_rate <= self.fp_threshold
            and self.false_negative_rate <= self.fn_threshold
        )

    def report(self) -> dict:
        """
        Aggregate statistics over the sliding window.

        Returns counts, rates, precision/recall, and threshold pass/fail.
        """
        c = self._counts()
        return {
            "total_verdicts":       len(self._verdicts),
            "true_positives":       c["tp"],
            "true_negatives":       c["tn"],
            "false_positives":      c["fp"],
            "false_negatives":      c["fn"],
            "false_positive_rate":  round(self.false_positive_rate, 4),
            "false_negative_rate":  round(self.false_negative_rate, 4),
            "precision":            round(self.precision, 4),
            "recall":               round(self.recall, 4),
            "fp_threshold":         self.fp_threshold,
            "fn_threshold":         self.fn_threshold,
            "passes_acceptance":    self.passes_acceptance(),
        }

    def acceptance_report(self) -> str:
        """
        IRS-003 S25 — human-readable acceptance report.

        Format matches the IRS-003 acceptance criteria specification.
        """
        r = self.report()
        status = "PASS" if r["passes_acceptance"] else "FAIL"
        lines = [
            "═" * 60,
            f"IRS-003 Skeptic Acceptance Report  [{status}]",
            "═" * 60,
            f"  Total verdicts evaluated : {r['total_verdicts']}",
            f"  True  positives (TP)     : {r['true_positives']}",
            f"  True  negatives (TN)     : {r['true_negatives']}",
            f"  False positives (FP)     : {r['false_positives']}",
            f"  False negatives (FN)     : {r['false_negatives']}",
            "",
            f"  False-positive rate : {r['false_positive_rate']:.1%}  "
            f"(threshold ≤ {r['fp_threshold']:.0%})  "
            f"{'✓' if r['false_positive_rate'] <= r['fp_threshold'] else '✗'}",
            f"  False-negative rate : {r['false_negative_rate']:.1%}  "
            f"(threshold ≤ {r['fn_threshold']:.0%})  "
            f"{'✓' if r['false_negative_rate'] <= r['fn_threshold'] else '✗'}",
            f"  Precision           : {r['precision']:.1%}",
            f"  Recall              : {r['recall']:.1%}",
            "",
            f"  Acceptance: {status}",
            "═" * 60,
        ]
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._verdicts)

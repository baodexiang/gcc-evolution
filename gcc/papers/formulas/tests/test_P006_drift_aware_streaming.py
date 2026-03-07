"""Unit tests for P006 Drift-Aware Streaming hard-rule formulas."""

import pytest

from gcc.papers.formulas.P006_drift_aware_streaming import (
    eq_1_stl_trend,
    eq_2_psi,
    eq_3_ks_statistic,
    eq_4_adaptive_window,
    eq_5_drift_detected,
    PSI_DRIFT_THRESHOLD,
    KS_DRIFT_THRESHOLD,
    WINDOW_MIN,
)


class TestEq1StlTrend:
    def test_single_element_returns_itself(self):
        assert eq_1_stl_trend([5.0]) == pytest.approx(5.0)

    def test_empty_returns_zero(self):
        assert eq_1_stl_trend([]) == pytest.approx(0.0)

    def test_constant_series_returns_constant(self):
        assert eq_1_stl_trend([3.0] * 20) == pytest.approx(3.0)

    def test_rising_series_trend_below_last(self):
        # EWMA lags behind a rising series
        trend = eq_1_stl_trend(list(range(1, 11)))
        assert trend < 10.0


class TestEq2Psi:
    def test_identical_distributions_zero_psi(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert eq_2_psi(data, data) == pytest.approx(0.0, abs=1e-6)

    def test_shifted_distribution_positive_psi(self):
        expected = list(range(1, 21))
        actual = list(range(11, 31))
        psi = eq_2_psi(expected, actual)
        assert psi > 0.0

    def test_empty_input_returns_zero(self):
        assert eq_2_psi([], [1.0, 2.0]) == pytest.approx(0.0)

    def test_constant_range_returns_zero(self):
        data = [5.0] * 10
        assert eq_2_psi(data, data) == pytest.approx(0.0, abs=1e-6)


class TestEq3KsStatistic:
    def test_identical_samples_zero_ks(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert eq_3_ks_statistic(data, data) == pytest.approx(0.0)

    def test_non_overlapping_samples_high_ks(self):
        a = [1.0, 2.0, 3.0]
        b = [10.0, 11.0, 12.0]
        assert eq_3_ks_statistic(a, b) == pytest.approx(1.0)

    def test_empty_returns_zero(self):
        assert eq_3_ks_statistic([], [1.0, 2.0]) == pytest.approx(0.0)

    def test_result_in_unit_interval(self):
        a = [1.0, 3.0, 5.0, 7.0]
        b = [2.0, 4.0, 6.0, 8.0]
        ks = eq_3_ks_statistic(a, b)
        assert 0.0 <= ks <= 1.0


class TestEq4AdaptiveWindow:
    def test_no_drift_keeps_base_window(self):
        result = eq_4_adaptive_window(base_window=100, psi=0.0, ks=0.0)
        assert result == 100

    def test_high_drift_shrinks_window(self):
        result = eq_4_adaptive_window(base_window=100, psi=1.0, ks=0.5)
        assert result < 100

    def test_never_below_window_min(self):
        result = eq_4_adaptive_window(base_window=100, psi=999.0, ks=999.0)
        assert result >= WINDOW_MIN

    def test_result_not_above_base(self):
        result = eq_4_adaptive_window(base_window=50, psi=0.0, ks=0.0)
        assert result <= 50


class TestEq5DriftDetected:
    def test_no_drift_below_thresholds(self):
        assert eq_5_drift_detected(psi=0.0, ks=0.0) is False

    def test_psi_triggers_drift(self):
        assert eq_5_drift_detected(psi=PSI_DRIFT_THRESHOLD, ks=0.0) is True

    def test_ks_triggers_drift(self):
        assert eq_5_drift_detected(psi=0.0, ks=KS_DRIFT_THRESHOLD) is True

    def test_both_high_triggers_drift(self):
        assert eq_5_drift_detected(psi=0.5, ks=0.3) is True

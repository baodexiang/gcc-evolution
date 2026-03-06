"""Unit tests for P006 drift-aware hard-rule formulas."""

import pytest

from gcc.papers.formulas.P006_drift_aware import (
    eq_1_stl_residual,
    eq_2_psi_score,
    eq_3_ks_statistic,
    eq_4_adaptive_window_size,
    eq_5_drift_detected,
)


class TestEq1StlResidual:
    def test_residual_identity(self):
        assert eq_1_stl_residual(observed=10.0, trend=6.0, seasonal=1.5) == pytest.approx(2.5)


class TestEq2PsiScore:
    def test_zero_when_distributions_equal(self):
        s = eq_2_psi_score([0.2, 0.3, 0.5], [0.2, 0.3, 0.5])
        assert s == pytest.approx(0.0)

    def test_positive_when_distributions_shift(self):
        s = eq_2_psi_score([0.1, 0.2, 0.7], [0.3, 0.3, 0.4])
        assert s > 0.0


class TestEq3KsStatistic:
    def test_zero_for_identical_samples(self):
        d = eq_3_ks_statistic([1, 2, 3], [1, 2, 3])
        assert d == pytest.approx(0.0)

    def test_positive_for_shifted_samples(self):
        d = eq_3_ks_statistic([1, 2, 3], [10, 11, 12])
        assert d > 0.0


class TestEq4AdaptiveWindowSize:
    def test_high_drift_shrinks_window(self):
        low = eq_4_adaptive_window_size(base_window=200, psi_score=0.01, ks_stat=0.01)
        high = eq_4_adaptive_window_size(base_window=200, psi_score=0.5, ks_stat=0.3)
        assert high < low

    def test_window_is_bounded(self):
        w = eq_4_adaptive_window_size(base_window=1000, psi_score=0.0, ks_stat=0.0, min_window=20, max_window=300)
        assert 20 <= w <= 300


class TestEq5DriftDetected:
    def test_detected_when_psi_exceeds_threshold(self):
        assert eq_5_drift_detected(psi_score=0.25, ks_stat=0.01) is True

    def test_detected_when_ks_exceeds_threshold(self):
        assert eq_5_drift_detected(psi_score=0.05, ks_stat=0.11) is True

    def test_not_detected_when_both_below(self):
        assert eq_5_drift_detected(psi_score=0.05, ks_stat=0.05) is False


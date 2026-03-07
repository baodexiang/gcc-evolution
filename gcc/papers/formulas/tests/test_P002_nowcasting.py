"""Unit tests for P002 nowcasting formula hard rules."""

import pytest

from gcc.papers.formulas.P002_nowcasting import (
    eq_1_realtime_state_estimate,
    eq_2_fusion_weights,
    eq_3_confidence_interval,
)


class TestEq1RealtimeStateEstimate:
    def test_alpha_zero_keeps_prev(self):
        assert eq_1_realtime_state_estimate(prev_state=10.0, observation=3.0, alpha=0.0) == pytest.approx(10.0)

    def test_alpha_one_uses_observation(self):
        assert eq_1_realtime_state_estimate(prev_state=10.0, observation=3.0, alpha=1.0) == pytest.approx(3.0)

    def test_mid_alpha_weighted_average(self):
        assert eq_1_realtime_state_estimate(prev_state=8.0, observation=4.0, alpha=0.25) == pytest.approx(7.0)

    def test_negative_alpha_clamped_to_zero(self):
        # _clamp01 line 23: value < 0.0 → 0.0
        result = eq_1_realtime_state_estimate(prev_state=5.0, observation=1.0, alpha=-0.5)
        assert result == pytest.approx(5.0)

    def test_alpha_above_one_clamped(self):
        # _clamp01 line 25: value > 1.0 → 1.0
        result = eq_1_realtime_state_estimate(prev_state=5.0, observation=2.0, alpha=3.0)
        assert result == pytest.approx(2.0)


class TestEq2FusionWeights:
    def test_weights_sum_to_one(self):
        w = eq_2_fusion_weights([1.0, 2.0, 3.0])
        assert sum(w) == pytest.approx(1.0)

    def test_largest_score_gets_largest_weight(self):
        w = eq_2_fusion_weights([0.1, 0.2, 0.9])
        assert w[2] > w[1] > w[0]

    def test_empty_input_returns_empty(self):
        assert eq_2_fusion_weights([]) == []

    def test_all_extreme_negative_scores_uniform_fallback(self):
        # line 54: denom ≈ 0 → uniform weights fallback
        import math
        big_neg = -1e308
        w = eq_2_fusion_weights([big_neg, big_neg, big_neg])
        assert len(w) == 3
        assert all(abs(x - 1 / 3) < 1e-9 for x in w)


class TestEq3ConfidenceInterval:
    def test_ci_is_centered_on_mean(self):
        lo, hi = eq_3_confidence_interval(mean=10.0, variance=4.0, sample_size=16)
        assert (lo + hi) / 2.0 == pytest.approx(10.0)

    def test_ci_shrinks_with_larger_sample(self):
        lo1, hi1 = eq_3_confidence_interval(mean=0.0, variance=9.0, sample_size=9)
        lo2, hi2 = eq_3_confidence_interval(mean=0.0, variance=9.0, sample_size=100)
        width1 = hi1 - lo1
        width2 = hi2 - lo2
        assert width2 < width1

    def test_non_negative_variance_guard(self):
        lo, hi = eq_3_confidence_interval(mean=2.0, variance=-1.0, sample_size=10)
        assert lo <= 2.0 <= hi


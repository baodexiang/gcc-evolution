"""Unit tests for P005 DualPath KV-Cache hard-rule formulas."""

import pytest

from gcc.papers.formulas.P005_dualpath_kvcache import (
    eq_1_dualpath_allocation_ratio,
    eq_2_cache_hit_objective,
    eq_3_inference_latency_estimate,
)


class TestEq1DualpathAllocationRatio:
    def test_balanced_when_no_signal(self):
        assert eq_1_dualpath_allocation_ratio(0.0, 0.0) == pytest.approx(0.5)

    def test_hot_higher_gives_higher_ratio(self):
        r1 = eq_1_dualpath_allocation_ratio(8.0, 2.0)
        r2 = eq_1_dualpath_allocation_ratio(2.0, 8.0)
        assert r1 > r2

    def test_ratio_in_range(self):
        r = eq_1_dualpath_allocation_ratio(3.0, 7.0)
        assert 0.0 <= r <= 1.0


class TestEq2CacheHitObjective:
    def test_objective_weighted_average(self):
        obj = eq_2_cache_hit_objective(0.9, 0.5, 0.75)
        assert obj == pytest.approx(0.8)

    def test_objective_range(self):
        obj = eq_2_cache_hit_objective(1.2, -0.5, 0.3)
        assert 0.0 <= obj <= 1.0


class TestEq3InferenceLatencyEstimate:
    def test_higher_hit_lower_latency(self):
        low_hit = eq_3_inference_latency_estimate(base_latency_ms=10, hit_rate_objective=0.2, miss_penalty_ms=20)
        high_hit = eq_3_inference_latency_estimate(base_latency_ms=10, hit_rate_objective=0.9, miss_penalty_ms=20)
        assert high_hit < low_hit

    def test_zero_penalty_means_base_latency(self):
        lat = eq_3_inference_latency_estimate(base_latency_ms=12, hit_rate_objective=0.3, miss_penalty_ms=0)
        assert lat == pytest.approx(12)


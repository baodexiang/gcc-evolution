"""Unit tests for P003 AlphaForgeBench hard-rule formulas."""

import pytest

from gcc.papers.formulas.P003_alphaforgebench import (
    eq_1_offline_pattern_score,
    eq_2_precision_recall_f1,
    eq_3_composite_benchmark_score,
)


class TestEq1OfflinePatternScore:
    def test_zero_component_yields_zero(self):
        assert eq_1_offline_pattern_score(hit_rate=0.0, novelty=0.8, stability=0.9) == pytest.approx(0.0)

    def test_higher_inputs_increase_score(self):
        low = eq_1_offline_pattern_score(0.4, 0.4, 0.4)
        high = eq_1_offline_pattern_score(0.8, 0.8, 0.8)
        assert high > low


class TestEq2PrecisionRecallF1:
    def test_metrics_basic_case(self):
        p, r, f1 = eq_2_precision_recall_f1(tp=8, fp=2, fn=2)
        assert p == pytest.approx(0.8)
        assert r == pytest.approx(0.8)
        assert f1 == pytest.approx(0.8)

    def test_zero_division_safe(self):
        p, r, f1 = eq_2_precision_recall_f1(tp=0, fp=0, fn=0)
        assert p == 0.0 and r == 0.0 and f1 == 0.0


class TestEq3CompositeBenchmarkScore:
    def test_latency_penalty_applies(self):
        fast = eq_3_composite_benchmark_score(pattern_score=0.8, f1_score=0.8, latency_ms=20, latency_budget_ms=50)
        slow = eq_3_composite_benchmark_score(pattern_score=0.8, f1_score=0.8, latency_ms=120, latency_budget_ms=50)
        assert fast > slow

    def test_score_positive_when_quality_high_and_latency_ok(self):
        score = eq_3_composite_benchmark_score(pattern_score=0.9, f1_score=0.85, latency_ms=30)
        assert score > 0.0


"""Unit tests for P004 prompt repetition hard-rule formulas."""

import pytest

from gcc.papers.formulas.P004_prompt_repetition import (
    eq_1_repetition_performance_gain,
    eq_2_optimal_repetition_count,
)


class TestEq1RepetitionPerformanceGain:
    def test_zero_repeat_zero_gain(self):
        assert eq_1_repetition_performance_gain(repetition_count=0) == pytest.approx(0.0)

    def test_gain_is_monotonic(self):
        g1 = eq_1_repetition_performance_gain(1)
        g2 = eq_1_repetition_performance_gain(3)
        g3 = eq_1_repetition_performance_gain(6)
        assert g1 <= g2 <= g3

    def test_gain_has_diminishing_returns(self):
        d1 = eq_1_repetition_performance_gain(2) - eq_1_repetition_performance_gain(1)
        d2 = eq_1_repetition_performance_gain(6) - eq_1_repetition_performance_gain(5)
        assert d2 < d1


class TestEq2OptimalRepetitionCount:
    def test_optimal_with_zero_cost_is_positive(self):
        n = eq_2_optimal_repetition_count(max_search=10, cost_per_repeat=0.0)
        assert n > 0

    def test_optimal_with_high_cost_is_small(self):
        n = eq_2_optimal_repetition_count(max_search=10, cost_per_repeat=0.5)
        assert n <= 2

    def test_optimal_in_range(self):
        n = eq_2_optimal_repetition_count(max_search=8, cost_per_repeat=0.08)
        assert 0 <= n <= 8


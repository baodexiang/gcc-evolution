"""Unit tests for P001 DeepSeek Engram hard-rule formulas."""

import pytest

from gcc.papers.formulas.P001_engram import (
    eq_3_memory_update,
    eq_5_decay_factor,
    eq_7_normalize_key,
    eq_9_soft_gate,
    eq_11_session_prefetch_priority,
)


class TestEq3MemoryUpdate:
    def test_full_decay_returns_old(self):
        result = eq_3_memory_update(old=1.0, new=0.5, decay=0.0, gate=1.0)
        assert result == pytest.approx(1.0)

    def test_no_decay_returns_new(self):
        result = eq_3_memory_update(old=1.0, new=0.5, decay=1.0, gate=1.0)
        assert result == pytest.approx(0.5)

    def test_gate_zero_blocks_update(self):
        result = eq_3_memory_update(old=1.0, new=0.5, decay=0.7, gate=0.0)
        assert result == pytest.approx(1.0)


class TestEq5DecayFactor:
    def test_monotonic_decrease(self):
        decays = [eq_5_decay_factor(t) for t in range(100)]
        assert all(decays[i] >= decays[i + 1] for i in range(99))

    def test_zero_age_no_decay(self):
        assert eq_5_decay_factor(0) == pytest.approx(1.0)

    def test_range_valid(self):
        for t in [0, 1, 10, 100, 1000]:
            d = eq_5_decay_factor(t)
            assert 0.0 <= d <= 1.0


class TestEq7NormalizeKey:
    def test_case_insensitive(self):
        assert eq_7_normalize_key("Python Task") == eq_7_normalize_key("python task")

    def test_whitespace_stripped(self):
        assert eq_7_normalize_key("  task   alpha  ") == "task alpha"

    def test_empty_string(self):
        result = eq_7_normalize_key("")
        assert isinstance(result, str)
        assert result == ""


class TestEq9SoftGate:
    def test_soft_gate_range(self):
        for c in [0.0, 0.2, 0.5, 0.8, 1.0]:
            g = eq_9_soft_gate(c)
            assert 0.0 <= g <= 1.0

    def test_soft_gate_monotonic(self):
        assert eq_9_soft_gate(0.2) < eq_9_soft_gate(0.5) < eq_9_soft_gate(0.8)


class TestEq11PrefetchPriority:
    def test_prefetch_positive(self):
        score = eq_11_session_prefetch_priority(recency_hours=1, access_count=3, confidence=0.8)
        assert score > 0.0

    def test_prefetch_recency_penalty(self):
        recent = eq_11_session_prefetch_priority(recency_hours=1, access_count=5, confidence=0.8)
        stale = eq_11_session_prefetch_priority(recency_hours=48, access_count=5, confidence=0.8)
        assert recent > stale


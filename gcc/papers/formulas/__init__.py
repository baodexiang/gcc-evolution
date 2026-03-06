"""Paper formula modules used by GCC hard rules."""

from .P001_engram import (
    ALPHA,
    BETA,
    GAMMA,
    EPSILON,
    DECAY_LAMBDA,
    eq_3_memory_update,
    eq_5_decay_factor,
    eq_7_normalize_key,
    eq_9_soft_gate,
    eq_11_session_prefetch_priority,
)
from .P002_nowcasting import (
    NOWCAST_EPSILON,
    eq_1_realtime_state_estimate,
    eq_2_fusion_weights,
    eq_3_confidence_interval,
)
from .P003_alphaforgebench import (
    BENCH_EPSILON,
    eq_1_offline_pattern_score,
    eq_2_precision_recall_f1,
    eq_3_composite_benchmark_score,
)
from .P004_prompt_repetition import (
    REP_EPSILON,
    eq_1_repetition_performance_gain,
    eq_2_optimal_repetition_count,
)

__all__ = [
    "ALPHA",
    "BETA",
    "GAMMA",
    "EPSILON",
    "DECAY_LAMBDA",
    "eq_3_memory_update",
    "eq_5_decay_factor",
    "eq_7_normalize_key",
    "eq_9_soft_gate",
    "eq_11_session_prefetch_priority",
    "NOWCAST_EPSILON",
    "eq_1_realtime_state_estimate",
    "eq_2_fusion_weights",
    "eq_3_confidence_interval",
    "BENCH_EPSILON",
    "eq_1_offline_pattern_score",
    "eq_2_precision_recall_f1",
    "eq_3_composite_benchmark_score",
    "REP_EPSILON",
    "eq_1_repetition_performance_gain",
    "eq_2_optimal_repetition_count",
]

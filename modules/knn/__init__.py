"""
modules/knn/ — KNN外挂因子化进化模块
======================================
gcc-evo五层架构:
  L1 数据模型    → models.py + features.py
  L2 记忆检索    → store.py (PluginKNNDB数据I/O) + matcher.py (KNN匹配算法)
  L3 进化引擎    → evolution.py (漂移/增强/WFO/MAB/Bootstrap)
  L4 编排自治    → orchestrator.py (统一接口/Phase2/知识卡/准确率)
  L5 人类对齐    → alignment.py (gcc-evo闭环/经验卡/反向调参/锚点)

向后兼容: 所有公共API从本包re-export, plugin_knn.py薄层转发
"""

__version__ = "1.000"

# ── L1: 数据模型 ──
from .models import PluginKNNResult, plugin_log

# ── L1: 特征提取 ──
from .features import (
    validate_ohlc_bars,
    stl_decompose_residual,
    extract_price_shape,
    extract_volume_shape,
    extract_atr_features,
    extract_regime_feature,
    infer_regime_from_bars,
    extract_supertrend_features,
    extract_supertrend_av2_features,
    extract_chanbs_features,
    extract_double_pattern_features,
    extract_rob_hoffman_features,
    extract_feiyun_features,
    extract_chandelier_features,
    extract_l2_macd_features,
    extract_gcctm_features,
    _append_extended_features,
    _calc_dc_position,
    _calc_vol_ratio,
    _calc_trend_consistency,
)

# ── L2: 历史库 + 匹配算法 ──
from .store import PluginKNNDB
from .matcher import knn_match

# ── L3: 进化引擎 ──
from .evolution import (
    compute_psi,
    detect_drift,
    alpha_schedule,
    augment_feature,
    cutmix_features,
    linear_mix,
    adaptive_k,
    bootstrap_from_yfinance,
    bootstrap_compare,
    wfo_backtest,
    KNNEvolutionMAB,
    get_knn_mab,
    EVOLUTION_ARMS,
)

# ── L4: 编排 ──
from .orchestrator import (
    get_plugin_knn_db,
    load_knn_accuracy,
    should_bypass_knn,
    save_knn_accuracy,
    load_plugin_knowledge_cards,
    apply_knowledge_bias,
    plugin_knn_record_and_query,
    plugin_knn_should_suppress,
    backfill_returns,
    query_knn,
)

# ── L5: 人类对齐 ──
from .alignment import (
    feedback_to_retriever,
    create_knn_experience_cards,
    sync_evo_tuning,
    check_accuracy_drift,
)

__all__ = [
    # L1
    "PluginKNNResult", "plugin_log",
    "validate_ohlc_bars", "stl_decompose_residual",
    "extract_price_shape", "extract_volume_shape", "extract_atr_features",
    "extract_regime_feature", "infer_regime_from_bars",
    "extract_supertrend_features", "extract_supertrend_av2_features",
    "extract_chanbs_features", "extract_double_pattern_features",
    "extract_rob_hoffman_features", "extract_feiyun_features",
    "extract_chandelier_features", "extract_l2_macd_features", "extract_gcctm_features",
    # L2
    "PluginKNNDB", "knn_match",
    # L3
    "compute_psi", "detect_drift", "alpha_schedule", "augment_feature",
    "cutmix_features", "linear_mix", "adaptive_k",
    "bootstrap_from_yfinance", "bootstrap_compare", "wfo_backtest",
    "KNNEvolutionMAB", "get_knn_mab", "EVOLUTION_ARMS",
    # L4
    "get_plugin_knn_db", "load_knn_accuracy", "should_bypass_knn", "save_knn_accuracy",
    "load_plugin_knowledge_cards", "apply_knowledge_bias",
    "plugin_knn_record_and_query", "plugin_knn_should_suppress",
    "backfill_returns", "query_knn",
    # L5
    "feedback_to_retriever", "create_knn_experience_cards",
    "sync_evo_tuning", "check_accuracy_drift",
]

#!/usr/bin/env python3
"""
plugin_knn.py — 向后兼容层
============================
v5.250起KNN模块重构为 modules/knn/ 五层架构:
  L1 models.py + features.py  — 数据模型+特征提取
  L2 store.py + matcher.py    — 历史库+KNN匹配
  L3 evolution.py             — 漂移/增强/WFO/MAB
  L4 orchestrator.py          — 统一接口/Phase2/知识卡
  L5 alignment.py             — gcc-evo闭环

本文件仅re-export, 保持主程序import路径不变。
"""

# 全量re-export from modules.knn
from modules.knn import (
    # L1: 数据模型
    PluginKNNResult,
    # L1: 特征提取
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
    _append_extended_features,
    _calc_dc_position,
    _calc_vol_ratio,
    _calc_trend_consistency,
    # L2: 历史库
    PluginKNNDB,
    # L3: 进化引擎
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
    # L4: 编排
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
    # L5: 人类对齐
    feedback_to_retriever,
    create_knn_experience_cards,
    sync_evo_tuning,
    check_accuracy_drift,
)

# 向后兼容: 旧代码中引用的常量/变量名
from modules.knn.models import PLUGIN_KNN_PHASE2

__all__ = [
    "PluginKNNResult",
    "validate_ohlc_bars", "stl_decompose_residual",
    "extract_price_shape", "extract_volume_shape", "extract_atr_features",
    "extract_regime_feature", "infer_regime_from_bars",
    "extract_supertrend_features", "extract_supertrend_av2_features",
    "extract_chanbs_features", "extract_double_pattern_features",
    "extract_rob_hoffman_features", "extract_feiyun_features",
    "extract_chandelier_features", "extract_l2_macd_features",
    "PluginKNNDB", "get_plugin_knn_db",
    "compute_psi", "detect_drift", "adaptive_k",
    "bootstrap_from_yfinance", "bootstrap_compare", "wfo_backtest",
    "KNNEvolutionMAB", "get_knn_mab", "EVOLUTION_ARMS",
    "load_knn_accuracy", "should_bypass_knn", "save_knn_accuracy",
    "load_plugin_knowledge_cards", "apply_knowledge_bias",
    "plugin_knn_record_and_query", "plugin_knn_should_suppress",
    "backfill_returns", "query_knn",
    "PLUGIN_KNN_PHASE2",
    # L5: 人类对齐
    "feedback_to_retriever", "create_knn_experience_cards",
    "sync_evo_tuning", "check_accuracy_drift",
]

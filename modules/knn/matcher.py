"""
modules/knn/matcher.py — L2 KNN匹配算法
========================================
纯算法: 加权距离匹配 → PluginKNNResult。
gcc-evo五层架构: L2 记忆检索层(算法部分)
依赖: 仅L1 models
"""

import numpy as np

from .models import PluginKNNResult, KNN_MIN_SAMPLES


def _rate_to_bias(win_rate: float, sample_count: int, best_dist: float) -> str:
    """根据胜率+样本数+最近距离 → bias"""
    if sample_count < KNN_MIN_SAMPLES:
        return "NEUTRAL"
    if best_dist > 5.0:
        return "NEUTRAL"
    if win_rate > 0.60:
        return "BUY"
    if win_rate < 0.40:
        return "SELL"
    return "NEUTRAL"


def knn_match(current: np.ndarray, history_feats: np.ndarray,
              history_returns: np.ndarray, k: int = 30,
              feature_weights: np.ndarray = None,
              sample_ages_days: np.ndarray = None,
              decay_rate: float = 0.05,
              rerank: bool = True,
              sample_regimes: list = None,
              current_regime: str = "unknown") -> PluginKNNResult:
    """
    加权距离匹配 → PluginKNNResult

    四层加权:
    1. 特征维度加权: indicator维度×3.0, price_shape维度×1.0
    2. 距离反比加权: 越近的邻居投票权重越高 (1/distance)
    3. 时间衰减加权: 老样本降权 (Ebbinghaus遗忘曲线)
    4. Regime感知: 同regime邻居权重1.0, 不同regime 0.3
    """
    if feature_weights is not None:
        diff = (history_feats - current) * feature_weights
    else:
        diff = history_feats - current
    distances = np.sqrt(np.sum(diff ** 2, axis=1))

    candidate_k = min(k * 3, len(distances)) if rerank else k
    top_k_idx = np.argsort(distances)[:candidate_k]

    if rerank and len(top_k_idx) > k:
        d_scores = 1.0 / (distances[top_k_idx] + 1e-6)
        d_scores = d_scores / (d_scores.max() + 1e-6)
        r_scores = np.abs(history_returns[top_k_idx])
        r_scores = r_scores / (r_scores.max() + 1e-6)
        div_scores = np.linspace(0, 1, len(top_k_idx))
        if sample_regimes and current_regime != "unknown" and len(sample_regimes) == len(history_returns):
            reg_scores = np.array([1.0 if sample_regimes[i] == current_regime else 0.3
                                   for i in top_k_idx])
        else:
            reg_scores = np.ones(len(top_k_idx))
        combined = 0.35 * d_scores + 0.25 * r_scores + 0.20 * div_scores + 0.20 * reg_scores
        reranked = np.argsort(-combined)[:k]
        top_k_idx = top_k_idx[reranked]

    top_k_rets = history_returns[top_k_idx]
    top_k_dists = distances[top_k_idx]
    best_dist = float(top_k_dists[0])

    _eps = 1e-6
    inv_dists = 1.0 / (top_k_dists + _eps)

    if sample_ages_days is not None and len(sample_ages_days) > 0:
        age_weights = np.exp(-decay_rate * sample_ages_days[top_k_idx])
    else:
        age_weights = np.ones(len(top_k_idx))

    combined_weights = inv_dists * age_weights
    weights = combined_weights / (combined_weights.sum() + _eps)

    win_mask = (top_k_rets > 0).astype(float)
    win_rate = float(np.dot(weights, win_mask))
    avg_ret = float(np.dot(weights, top_k_rets))

    actual_k = len(top_k_idx)
    bias = _rate_to_bias(win_rate, actual_k, best_dist)
    confidence = abs(win_rate - 0.5) * 2
    return PluginKNNResult(
        win_rate=win_rate,
        avg_return=avg_ret,
        sample_count=actual_k,
        best_match_dist=best_dist,
        bias=bias,
        confidence=confidence,
        reason=f"历史{actual_k}次相似(加权): 胜率{win_rate:.0%} 均收益{avg_ret:.2%} dist={best_dist:.2f}",
    )

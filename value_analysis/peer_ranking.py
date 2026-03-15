"""
GCC-0002: Peer-Relative Percentile Ranking for KEY-003
Comps方法论 — 用百分位排名替代绝对线性评分

数据源: Schwab API(美股) / Coinbase API(加密)
方法论: anthropics/financial-services-plugins comps-analysis

核心思路:
- 绝对评分(PE good=15, bad=45)→ 在peer group中排第几名
- 百分位转评分: top 25% → +2, bottom 25% → -2, 中间线性
- 美股11只一个peer group, 加密4只一个peer group
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _percentile(values: List[float], pct: float) -> float:
    """计算百分位值 (0-100)"""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    k = (pct / 100.0) * (n - 1)
    f = int(k)
    c = f + 1
    if c >= n:
        return float(s[-1])
    return float(s[f] + (k - f) * (s[c] - s[f]))


def _percentile_rank(value: float, values: List[float]) -> float:
    """计算value在values中的百分位排名 (0.0-1.0)
    0.0 = 最小, 1.0 = 最大"""
    if not values or len(values) < 2:
        return 0.5
    n = len(values)
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (below + 0.5 * equal) / n


def _percentile_to_score(pct_rank: float, higher_is_better: bool) -> float:
    """百分位排名(0-1)转评分(-2 to +2)
    higher_is_better=True: 排名越高(pct_rank越大)评分越高
    higher_is_better=False: 排名越低(pct_rank越小)评分越高(如PE越低越好)
    """
    if not higher_is_better:
        pct_rank = 1.0 - pct_rank
    # 线性映射: 0.0 → -2.0, 0.5 → 0.0, 1.0 → +2.0
    return _clip(4.0 * pct_rank - 2.0, -2.0, 2.0)


# 指标方向定义: True=越高越好, False=越低越好
METRIC_DIRECTION: Dict[str, bool] = {
    # valuation — 越低越好
    "pe": False,
    "pb": False,
    "ev_ebitda": False,
    # valuation — 越高越好
    "fcf_yield": True,
    # profitability — 越高越好
    "roe": True,
    "roa": True,
    "operating_margin": True,
    "gross_margin": True,
    # balance — 混合
    "current_ratio": True,
    "debt_to_equity": False,
    "debt_to_assets": False,
    # cashflow — 越高越好
    "ocf_margin": True,
    # momentum — 越高越好
    "ret_1m": True,
    "ret_3m": True,
    "ret_6m": True,
    # GCC-0003: DCF折价率 — 越高越好(正=低估)
    "dcf_discount_pct": True,
    # GCC-0005: 加密基本面
    "market_cap_rank": False,  # 排名越低(数字越小)越好
    "dev_commits_4w": True,
    "tvl_usd": True,
    "total_volume_24h": True,
}

# 原始指标到评分桶的映射
METRIC_TO_BUCKET: Dict[str, str] = {
    "pe": "valuation_scores",
    "pb": "valuation_scores",
    "ev_ebitda": "valuation_scores",
    "fcf_yield": "valuation_scores",
    "roe": "profitability_scores",
    "roa": "profitability_scores",
    "operating_margin": "profitability_scores",
    "gross_margin": "profitability_scores",
    "current_ratio": "balance_scores",
    "debt_to_equity": "balance_scores",
    "debt_to_assets": "balance_scores",
    "ocf_margin": "cashflow_scores",
    "ret_1m": "momentum_scores",
    "ret_3m": "momentum_scores",
    "ret_6m": "momentum_scores",
    # GCC-0003: DCF折价率独立桶
    "dcf_discount_pct": "dcf_scores",
    # GCC-0005: 加密基本面桶
    "market_cap_rank": "crypto_scores",
    "dev_commits_4w": "crypto_scores",
    "tvl_usd": "crypto_scores",
    "total_volume_24h": "crypto_scores",
}


def compute_peer_stats(values: List[float]) -> Dict[str, float]:
    """计算peer group统计 (comps风格: Max/75th/Median/25th/Min)"""
    if not values:
        return {"max": 0.0, "p75": 0.0, "median": 0.0, "p25": 0.0, "min": 0.0, "count": 0}
    return {
        "max": max(values),
        "p75": _percentile(values, 75),
        "median": _percentile(values, 50),
        "p25": _percentile(values, 25),
        "min": min(values),
        "count": len(values),
    }


def compute_peer_ranking(
    symbols: List[str],
    profiles: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    对所有品种按peer group做百分位排名，替换绝对评分。

    - 美股和加密分开排名(不同peer group)
    - 修改profiles中的*_scores为peer-relative评分
    - 返回peer_stats供dashboard显示

    Args:
        symbols: 品种列表
        profiles: {symbol: profile_dict}, 会被原地修改

    Returns:
        {
            "equity_stats": {metric: {max, p75, median, p25, min}},
            "crypto_stats": {metric: {max, p75, median, p25, min}},
            "peer_ranks": {symbol: {metric: percentile_rank}},
        }
    """
    # 分组
    equity_syms = [s for s in symbols if s in profiles and not _is_crypto(s)]
    crypto_syms = [s for s in symbols if s in profiles and _is_crypto(s)]

    equity_stats: Dict[str, Dict[str, float]] = {}
    crypto_stats: Dict[str, Dict[str, float]] = {}
    peer_ranks: Dict[str, Dict[str, float]] = {}

    # 美股 peer ranking
    if len(equity_syms) >= 2:
        _rank_group(equity_syms, profiles, equity_stats, peer_ranks)

    # 加密 peer ranking (momentum only)
    if len(crypto_syms) >= 2:
        _rank_group(crypto_syms, profiles, crypto_stats, peer_ranks)

    return {
        "equity_stats": equity_stats,
        "crypto_stats": crypto_stats,
        "peer_ranks": peer_ranks,
    }


def _rank_group(
    group_syms: List[str],
    profiles: Dict[str, Dict[str, Any]],
    stats_out: Dict[str, Dict[str, float]],
    ranks_out: Dict[str, Dict[str, float]],
) -> None:
    """对一组品种做peer ranking并修改profiles"""
    for metric, higher_is_better in METRIC_DIRECTION.items():
        bucket = METRIC_TO_BUCKET.get(metric)
        if not bucket:
            continue

        # 收集该指标的所有有效值
        sym_vals: List[Tuple[str, float]] = []
        for sym in group_syms:
            profile = profiles[sym]
            raw = profile.get("raw_metrics", {}) or {}
            val = raw.get(metric)
            if val is not None and isinstance(val, (int, float)):
                sym_vals.append((sym, float(val)))

        if len(sym_vals) < 2:
            continue

        # 计算peer统计
        raw_values = [v for _, v in sym_vals]
        stats_out[metric] = compute_peer_stats(raw_values)

        # 计算每只股票的百分位排名并转评分
        for sym, val in sym_vals:
            pct_rank = _percentile_rank(val, raw_values)
            score = _percentile_to_score(pct_rank, higher_is_better)

            # 更新profile中的评分
            score_map = profiles[sym].get(bucket)
            if isinstance(score_map, dict):
                score_map[metric] = score

            # 记录排名
            if sym not in ranks_out:
                ranks_out[sym] = {}
            ranks_out[sym][metric] = round(pct_rank, 4)

        # 标记peer ranking已应用
        for sym, _ in sym_vals:
            raw = profiles[sym].get("raw_metrics", {})
            if isinstance(raw, dict):
                pr_fields = raw.get("peer_ranked_fields")
                if not isinstance(pr_fields, list):
                    pr_fields = []
                if metric not in pr_fields:
                    pr_fields.append(metric)
                raw["peer_ranked_fields"] = pr_fields
                raw["peer_ranking_applied"] = True


def _is_crypto(symbol: str) -> bool:
    return symbol.endswith("USDC") or symbol.endswith("USDT")

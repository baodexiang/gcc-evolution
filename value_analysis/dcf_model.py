"""
GCC-0003: Simplified DCF Model for KEY-003
方法论: anthropics/financial-services-plugins dcf-model skill (简化版)

输入: Schwab API raw_metrics (fcf_yield, market_cap, beta, eps, revenue growth proxy)
输出: 内在价值估算 + 市价偏离度(premium/discount%) + sanity flags

简化假设:
- 投影期: 5年
- 终端增长率: 2.5%
- WACC: risk_free(4.5%) + beta * ERP(5.5%)
- FCF = fcf_yield * market_cap
- FCF增长率: 用eps_growth或revenue momentum推断
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


# 常量
DEFAULT_RISK_FREE = 0.045      # 10Y Treasury近似
DEFAULT_ERP = 0.055            # Equity Risk Premium
DEFAULT_TERMINAL_G = 0.025     # 终端增长率
DEFAULT_PROJECTION_YEARS = 5
MIN_WACC = 0.06                # WACC下限(防止terminal value爆炸)
MAX_WACC = 0.25                # WACC上限


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


@dataclass(frozen=True)
class DCFResult:
    intrinsic_value: float       # 内在价值(总市值)
    market_cap: float            # 当前市值
    discount_pct: float          # 折价率: 正=低估, 负=高估
    dcf_score: float             # 折价率转评分(-2 to +2)
    wacc: float                  # 使用的WACC
    fcf_current: float           # 当前FCF
    fcf_growth: float            # 使用的FCF增长率
    terminal_value: float        # 终端价值
    sanity_flags: list           # 红旗列表


def estimate_fcf_growth(raw_metrics: Dict[str, Any]) -> float:
    """从可用数据推断FCF增长率

    优先链:
    1. EPS增长 (如果有多期EPS)
    2. Revenue momentum (ret_6m年化)
    3. ROE * (1 - payout) 可持续增长率近似
    4. 默认5%
    """
    # 尝试用6个月动量年化
    ret_6m = raw_metrics.get("ret_6m")
    if ret_6m is not None and isinstance(ret_6m, (int, float)):
        annual_growth = float(ret_6m) * 2.0  # 简化年化
        return _clip(annual_growth, -0.20, 0.40)

    # 尝试ROE可持续增长
    roe = raw_metrics.get("roe")
    if roe is not None and isinstance(roe, (int, float)):
        # 假设payout=30%, retention=70%
        sustainable = float(roe) / 100.0 * 0.70
        return _clip(sustainable, -0.10, 0.30)

    return 0.05  # 默认5%


def compute_wacc(beta: Optional[float],
                 risk_free: float = DEFAULT_RISK_FREE,
                 erp: float = DEFAULT_ERP) -> float:
    """CAPM简化WACC (纯股权, 无债务调整)"""
    if beta is None or not isinstance(beta, (int, float)):
        beta = 1.0
    b = _clip(float(beta), 0.3, 4.0)
    wacc = risk_free + b * erp
    return _clip(wacc, MIN_WACC, MAX_WACC)


def compute_dcf(raw_metrics: Dict[str, Any]) -> Optional[DCFResult]:
    """
    简化DCF估值

    Returns None if insufficient data (no market_cap or no fcf_yield)
    """
    market_cap = raw_metrics.get("market_cap")
    fcf_yield = raw_metrics.get("fcf_yield")

    if market_cap is None or fcf_yield is None:
        return None
    if not isinstance(market_cap, (int, float)) or market_cap <= 0:
        return None
    if not isinstance(fcf_yield, (int, float)):
        return None

    market_cap = float(market_cap)
    fcf_yield = float(fcf_yield)

    # 当前FCF
    fcf_current = fcf_yield * market_cap
    if fcf_current <= 0:
        # 负FCF → 无法做正常DCF
        return DCFResult(
            intrinsic_value=0.0,
            market_cap=market_cap,
            discount_pct=-1.0,  # 100%高估
            dcf_score=-2.0,
            wacc=0.0,
            fcf_current=fcf_current,
            fcf_growth=0.0,
            terminal_value=0.0,
            sanity_flags=["negative_fcf"],
        )

    # 增长率和WACC
    fcf_growth = estimate_fcf_growth(raw_metrics)
    beta = raw_metrics.get("beta")
    wacc = compute_wacc(beta)

    # 确保WACC > terminal_g (否则terminal value为负/无穷)
    terminal_g = DEFAULT_TERMINAL_G
    if wacc <= terminal_g + 0.01:
        wacc = terminal_g + 0.02

    # 5年FCF投影 + 现值
    pv_fcfs = 0.0
    projected_fcf = fcf_current
    for year in range(1, DEFAULT_PROJECTION_YEARS + 1):
        projected_fcf *= (1.0 + fcf_growth)
        pv_fcfs += projected_fcf / ((1.0 + wacc) ** year)

    # 终端价值
    terminal_fcf = projected_fcf * (1.0 + terminal_g)
    terminal_value = terminal_fcf / (wacc - terminal_g)
    pv_terminal = terminal_value / ((1.0 + wacc) ** DEFAULT_PROJECTION_YEARS)

    # 内在价值
    intrinsic_value = pv_fcfs + pv_terminal

    # 折价率: 正=低估(便宜), 负=高估(贵)
    discount_pct = (intrinsic_value - market_cap) / market_cap

    # Sanity flags
    sanity_flags = []
    pe = raw_metrics.get("pe")
    if pe is not None and isinstance(pe, (int, float)) and float(pe) > 100:
        sanity_flags.append("pe_over_100")
    if pe is not None and isinstance(pe, (int, float)) and float(pe) < 0:
        sanity_flags.append("negative_pe")

    op_margin = raw_metrics.get("op_margin")
    if op_margin is not None and isinstance(op_margin, (int, float)) and float(op_margin) < 0:
        sanity_flags.append("negative_operating_margin")

    if abs(discount_pct) > 5.0:
        sanity_flags.append("extreme_discount_ratio")

    if fcf_growth > 0.30:
        sanity_flags.append("high_growth_assumption")

    # 折价率→评分: >=50%低估→+2, 0%→0, <=-50%高估→-2
    dcf_score = _clip(discount_pct * 4.0, -2.0, 2.0)

    return DCFResult(
        intrinsic_value=intrinsic_value,
        market_cap=market_cap,
        discount_pct=round(discount_pct, 4),
        dcf_score=round(dcf_score, 4),
        wacc=round(wacc, 4),
        fcf_current=round(fcf_current, 2),
        fcf_growth=round(fcf_growth, 4),
        terminal_value=round(pv_terminal, 2),
        sanity_flags=sanity_flags,
    )

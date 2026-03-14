#!/usr/bin/env python3
"""
Timeframe Parameters Module v3.600
===================================
共享周期参数计算模块 — 所有程序从这里读取派生参数。

设计原则:
- X4乘数固定为4（当前周期×4=大趋势周期）
- 所有回看窗口按"天数"定义，自动换算为bar数
- 向后兼容: get_timeframe_params(240, True) 输出与v3.590硬编码值一致

使用方式:
    from timeframe_params import get_timeframe_params, read_symbol_timeframe, is_crypto_symbol

    params = get_timeframe_params(60, is_crypto=True)
    # params["dow_lookback"] = 240  (24 bars/day * 10 days)
    # params["ohlcv_buffer_size"] = 480  (24 bars/day * 20 days)
    # params["current_label"] = "1-hour"
    # params["x4_label"] = "4-hour"
"""

import json
import os


def get_timeframe_params(timeframe_minutes: int, is_crypto: bool = True) -> dict:
    """
    中心函数: 根据周期(分钟)返回所有派生参数。

    Args:
        timeframe_minutes: 基础周期 (60=1H, 120=2H, 240=4H, 1440=日线)
        is_crypto: True=加密货币(24h交易), False=美股(6.5h交易日)

    Returns:
        dict 包含所有派生值
    """
    tf = max(1, timeframe_minutes)

    # 每天交易小时数
    hours_per_day = 24.0 if is_crypto else 6.5
    bars_per_day = (hours_per_day * 60) / tf

    # X4参数 (乘数固定为4)
    x4_factor = 4
    x4_timeframe_minutes = tf * x4_factor

    # DOW回看窗口: 目标~10个交易日
    dow_lookback = max(16, int(round(bars_per_day * 10)))
    short_lookback = max(8, int(round(bars_per_day * 5)))
    long_lookback = max(25, int(round(bars_per_day * 15)))

    # OHLCV缓冲区: 目标~20天
    ohlcv_buffer_size = max(120, int(round(bars_per_day * 20)))

    # 周期标签 (Vision提示词用)
    current_label = _make_label(tf)
    x4_label = _make_label(x4_timeframe_minutes)

    # yfinance 区间和周期
    yf_interval, yf_period = _get_yfinance_mapping(tf)

    # 扫描引擎周期字符串
    scan_timeframe_str = _minutes_to_scan_str(tf)

    # Vision冷却4小时 (趋势分析不需高频, 节省API成本)
    vision_cooldown_minutes = 240

    return {
        "timeframe_minutes": tf,
        "bars_per_day": bars_per_day,
        "x4_factor": x4_factor,
        "x4_timeframe_minutes": x4_timeframe_minutes,
        "dow_lookback": dow_lookback,
        "short_lookback": short_lookback,
        "long_lookback": long_lookback,
        "ohlcv_buffer_size": ohlcv_buffer_size,
        "current_label": current_label,
        "x4_label": x4_label,
        "yf_interval": yf_interval,
        "yf_period": yf_period,
        "scan_timeframe_str": scan_timeframe_str,
        "vision_cooldown_minutes": vision_cooldown_minutes,
        "is_crypto": is_crypto,
    }


def read_symbol_timeframe(symbol: str, config_file: str = "state/symbol_config.json",
                          default: int = 240) -> int:
    """从共享配置文件读取symbol的当前周期(分钟)"""
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return int(config.get("symbols", {}).get(symbol, default))
    except Exception:
        pass
    return default


# v21.7: 扫描间隔配置 (秒) — 基于主交易周期
# 4H=30分钟, 2H/1H=10分钟, 30m/15m=5分钟
SCAN_INTERVAL_BY_TF = {
    240: 1800,  # 4H → 30分钟 (每根K线扫8次, API调用量减半)
    120: 600,   # 2H → 10分钟 (每根K线扫12次)
    60:  600,   # 1H → 10分钟 (每根K线扫6次)
    30:  300,   # 30m → 5分钟 (不变)
    15:  300,   # 15m → 5分钟 (不变)
}

# v21.8: 跨周期共识度权重 — 4源加权投票 (v3.676: 去掉L2,权重重分配)
# consensus_score = Σ(weight × vote), vote ∈ {+1, -1, 0}
# score范围 [-1.0, +1.0], |score|>=0.3 允许执行
# GCC-0194: 外挂激活不受L1趋势/supertrend过滤，共识度全部归零(Phase1仅记录不拦截)
CONSENSUS_WEIGHTS = {
    "x4_trend":       0.00,   # GCC-0194: 归零 (原0.30)
    "current_trend":  0.00,   # GCC-0194: 归零 (原0.20)
    "vision":         0.00,   # GCC-0194: 归零 (原0.35) — 外挂不需要vision过滤
    "supertrend":     0.00,   # GCC-0194: 归零 (原0.15) — 外挂不需要supertrend过滤
}
CONSENSUS_BLOCK_THRESHOLD = 0.30   # |score| < 此值 → 阻止执行
CONSENSUS_BOOST_THRESHOLD = 0.60   # |score| >= 此值 → 高共识加分


def is_crypto_symbol(symbol: str) -> bool:
    """判断是否为加密货币品种"""
    if not symbol:
        return True
    return symbol.endswith("USDC") or symbol.endswith("USDT") or symbol.endswith("-USD")


def _make_label(minutes: int) -> str:
    """分钟数转可读标签"""
    if minutes >= 1440:
        days = minutes // 1440
        return f"{days}-day" if days > 1 else "daily"
    elif minutes >= 60:
        hours = minutes // 60
        return f"{hours}-hour"
    else:
        return f"{minutes}-minute"


def _minutes_to_scan_str(tf: int) -> str:
    """分钟数转扫描引擎格式字符串 (60→'1h', 240→'4h')"""
    if tf >= 1440:
        return f"{tf // 1440}d"
    if tf >= 60:
        return f"{tf // 60}h"
    return f"{tf}m"


def _get_yfinance_mapping(tf: int) -> tuple:
    """返回 (yfinance_interval, yfinance_period)"""
    if tf <= 30:
        return ("30m", "5d")
    if tf <= 60:
        return ("1h", "7d")
    if tf <= 90:
        return ("90m", "7d")
    if tf <= 240:
        return ("1h", "1mo")  # 需要重采样
    if tf <= 1440:
        return ("1d", "60d")
    return ("1wk", "2y")


# ============================================================
# 自检 (python timeframe_params.py)
# ============================================================
if __name__ == "__main__":
    # 向后兼容验证
    p240c = get_timeframe_params(240, is_crypto=True)
    assert p240c["dow_lookback"] == 60, f"Expected 60, got {p240c['dow_lookback']}"
    assert p240c["ohlcv_buffer_size"] == 120, f"Expected 120, got {p240c['ohlcv_buffer_size']}"
    assert p240c["current_label"] == "4-hour"
    assert p240c["x4_label"] == "16-hour"
    assert p240c["x4_timeframe_minutes"] == 960
    print(f"[OK] 240min/crypto: dow={p240c['dow_lookback']}, buf={p240c['ohlcv_buffer_size']}, "
          f"label={p240c['current_label']}/{p240c['x4_label']}")

    # 美股验证
    p240s = get_timeframe_params(240, is_crypto=False)
    assert p240s["dow_lookback"] == 16, f"Expected 16, got {p240s['dow_lookback']}"
    print(f"[OK] 240min/stock: dow={p240s['dow_lookback']}, buf={p240s['ohlcv_buffer_size']}")

    # 1H验证
    p60c = get_timeframe_params(60, is_crypto=True)
    assert p60c["dow_lookback"] == 240, f"Expected 240, got {p60c['dow_lookback']}"
    assert p60c["ohlcv_buffer_size"] == 480, f"Expected 480, got {p60c['ohlcv_buffer_size']}"
    assert p60c["current_label"] == "1-hour"
    assert p60c["x4_label"] == "4-hour"
    print(f"[OK] 60min/crypto: dow={p60c['dow_lookback']}, buf={p60c['ohlcv_buffer_size']}, "
          f"label={p60c['current_label']}/{p60c['x4_label']}")

    # 2H验证
    p120c = get_timeframe_params(120, is_crypto=True)
    assert p120c["current_label"] == "2-hour"
    assert p120c["x4_label"] == "8-hour"
    print(f"[OK] 120min/crypto: dow={p120c['dow_lookback']}, buf={p120c['ohlcv_buffer_size']}, "
          f"label={p120c['current_label']}/{p120c['x4_label']}")

    # 日线验证
    p1440 = get_timeframe_params(1440, is_crypto=True)
    assert p1440["current_label"] == "daily"
    assert p1440["x4_label"] == "4-day"
    print(f"[OK] 1440min/crypto: dow={p1440['dow_lookback']}, buf={p1440['ohlcv_buffer_size']}, "
          f"label={p1440['current_label']}/{p1440['x4_label']}")

    print("\n✅ All assertions passed!")

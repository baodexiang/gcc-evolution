# ========================================================================
# L1 REGIME ENHANCEMENT v3.170
# ========================================================================
# 目标: 提升趋势/震荡识别准确率，特别是Human模块
#
# 改进点:
# 1. Human模块多周期斜率融合 (解决单周期噪音问题)
# 2. 趋势结构确认 (HH/HL/LH/LL检测)
# 3. 动态阈值校准 (根据品种波动率调整)
# 4. 增强版Choppiness检测
# 5. 三方投票权重优化
# 6. 大周期趋势保护
# 7. [v3.170] K线形态检测 (基于云聪13买卖点规则)
#    - 大K线识别 (阈值: 加密2%, 美股1.5%)
#    - 吞没/孕线/刺透形态检测
#    - 连续同向K线趋势确认
# 8. [v3.170] 量价模式验证 (基于云聪13买卖点规则)
#    - 缩量回调/反弹检测
#    - 强弱量价配合模式
#    - 巨量警示 (>2x MA20)
#    - 量价背离检测
#
# 作者: AI Trading System
# 版本: v3.170 (2026-01-06)
# v3.170: 集成云聪13买卖点K线形态+量价验证模块
# v3.050: 加入大周期趋势保护，修复震荡市场高位逆势SELL问题
# ========================================================================

import json
import math
import os
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

# 导入L1规则追踪器
try:
    from l1_rule_tracker import get_tracker
    L1_TRACKER_ENABLED = True
except ImportError:
    L1_TRACKER_ENABLED = False
    print("[L1Enhancement] 警告: l1_rule_tracker未找到，追踪功能禁用")

# ========================================================================
# 配置常量
# ========================================================================

class RegimeConfig:
    """趋势/震荡识别配置"""

    # 多周期斜率配置
    SLOPE_PERIODS = [10, 20, 30, 60]  # 多周期
    SLOPE_WEIGHTS = [0.15, 0.25, 0.35, 0.25]  # 权重(近期略低，中期最高)

    # 斜率阈值 (标准化后的百分比)
    SLOPE_STEEP_UP = 0.12      # 陡峭上涨
    SLOPE_UP = 0.04            # 上涨
    SLOPE_STEEP_DOWN = -0.12   # 陡峭下跌
    SLOPE_DOWN = -0.04         # 下跌

    # 趋势结构确认
    SWING_LOOKBACK = 5         # Swing点回溯
    MIN_HH_HL_COUNT = 2        # 最小HH+HL数量确认上涨
    MIN_LL_LH_COUNT = 2        # 最小LL+LH数量确认下跌

    # Choppiness动态阈值
    CHOP_TRENDING_BASE = 38.2   # 趋势阈值基准
    CHOP_RANGING_BASE = 61.8    # 震荡阈值基准
    CHOP_ATR_ADJUST_FACTOR = 2.0  # ATR调整因子

    # 一致性检测
    CONSISTENCY_THRESHOLD = 0.6  # 60%以上周期同向=一致

    # 品种特定调整
    HIGH_VOL_SYMBOLS = ["ZECUSDC", "SOLUSDC", "RKLB", "RDDT"]  # 高波动品种
    LOW_VOL_SYMBOLS = ["BTCUSDC", "ETHUSDC", "AMD", "TSLA"]    # 低波动品种


class TrendDirection(Enum):
    """趋势方向"""
    STRONG_UP = "STRONG_UP"
    UP = "UP"
    FLAT = "FLAT"
    DOWN = "DOWN"
    STRONG_DOWN = "STRONG_DOWN"


class MarketRegime(Enum):
    """市场状态"""
    STRONG_TRENDING = "STRONG_TRENDING"  # 强趋势
    TRENDING = "TRENDING"                 # 趋势
    TRANSITIONING = "TRANSITIONING"       # 过渡
    RANGING = "RANGING"                   # 震荡
    CHOPPY = "CHOPPY"                     # 剧烈震荡


# ========================================================================
# 模块1: 多周期斜率融合 (解决Human模块单周期噪音问题)
# ========================================================================

def compute_linear_regression_slope(closes: List[float]) -> float:
    """
    计算线性回归斜率 (标准化为每根K线的百分比变化)

    Returns:
        float: 标准化斜率 (正=上涨, 负=下跌)
    """
    n = len(closes)
    if n < 3:
        return 0.0

    x_mean = (n - 1) / 2
    y_mean = sum(closes) / n

    if y_mean == 0:
        return 0.0

    numerator = sum((i - x_mean) * (closes[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return 0.0

    slope = numerator / denominator
    # 标准化: 斜率 / 平均价格 * 100 = 每根K线的百分比变化
    normalized_slope = (slope / y_mean) * 100

    return normalized_slope


def compute_multi_period_slope(ohlcv_bars: List[dict]) -> Dict:
    """
    多周期斜率融合计算

    核心改进:
    - 10/20/30/60 四个周期
    - 加权平均，中期(30)权重最高
    - 一致性检测: 多周期同向增强信号

    Returns:
        {
            "slopes": {10: float, 20: float, 30: float, 60: float},
            "weighted_slope": float,
            "direction": TrendDirection,
            "consistency": float,  # 0-1, 越高越一致
            "confidence": float,
        }
    """
    result = {
        "slopes": {},
        "weighted_slope": 0.0,
        "direction": TrendDirection.FLAT,
        "consistency": 0.0,
        "confidence": 0.5,
    }

    if not ohlcv_bars or len(ohlcv_bars) < 10:
        return result

    closes = [float(bar.get("close", bar.get("c", 0))) for bar in ohlcv_bars]

    # 计算各周期斜率
    slopes = {}
    for period in RegimeConfig.SLOPE_PERIODS:
        if len(closes) >= period:
            slopes[period] = compute_linear_regression_slope(closes[-period:])
        else:
            slopes[period] = 0.0

    result["slopes"] = slopes

    # 加权平均
    weighted_sum = 0.0
    weight_sum = 0.0
    for i, period in enumerate(RegimeConfig.SLOPE_PERIODS):
        if period in slopes:
            weighted_sum += slopes[period] * RegimeConfig.SLOPE_WEIGHTS[i]
            weight_sum += RegimeConfig.SLOPE_WEIGHTS[i]

    weighted_slope = weighted_sum / weight_sum if weight_sum > 0 else 0.0
    result["weighted_slope"] = weighted_slope

    # 一致性检测: 统计同向周期比例
    up_count = sum(1 for s in slopes.values() if s > 0.02)
    down_count = sum(1 for s in slopes.values() if s < -0.02)
    total = len(slopes)

    consistency = max(up_count, down_count) / total if total > 0 else 0.0
    result["consistency"] = consistency

    # 方向判断 (结合加权斜率和一致性)
    if weighted_slope > RegimeConfig.SLOPE_STEEP_UP and consistency >= 0.75:
        result["direction"] = TrendDirection.STRONG_UP
        result["confidence"] = min(0.95, 0.7 + consistency * 0.25)
    elif weighted_slope > RegimeConfig.SLOPE_UP:
        result["direction"] = TrendDirection.UP
        result["confidence"] = 0.6 + consistency * 0.2
    elif weighted_slope < RegimeConfig.SLOPE_STEEP_DOWN and consistency >= 0.75:
        result["direction"] = TrendDirection.STRONG_DOWN
        result["confidence"] = min(0.95, 0.7 + consistency * 0.25)
    elif weighted_slope < RegimeConfig.SLOPE_DOWN:
        result["direction"] = TrendDirection.DOWN
        result["confidence"] = 0.6 + consistency * 0.2
    else:
        result["direction"] = TrendDirection.FLAT
        result["confidence"] = 0.5 + (1 - consistency) * 0.2  # 不一致时FLAT更可信

    return result


# ========================================================================
# 模块2: 趋势结构确认 (HH/HL/LH/LL检测)
# ========================================================================

def find_swing_points(ohlcv_bars: List[dict], lookback: int = 5) -> Dict:
    """
    识别Swing High/Low点

    Returns:
        {
            "swing_highs": [(index, price), ...],
            "swing_lows": [(index, price), ...],
        }
    """
    if len(ohlcv_bars) < lookback * 2 + 1:
        return {"swing_highs": [], "swing_lows": []}

    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(ohlcv_bars) - lookback):
        high = float(ohlcv_bars[i].get("high", ohlcv_bars[i].get("h", 0)))
        low = float(ohlcv_bars[i].get("low", ohlcv_bars[i].get("l", 0)))

        # 检查是否是Swing High
        is_swing_high = True
        for j in range(i - lookback, i + lookback + 1):
            if j != i:
                other_high = float(ohlcv_bars[j].get("high", ohlcv_bars[j].get("h", 0)))
                if other_high >= high:
                    is_swing_high = False
                    break

        if is_swing_high:
            swing_highs.append((i, high))

        # 检查是否是Swing Low
        is_swing_low = True
        for j in range(i - lookback, i + lookback + 1):
            if j != i:
                other_low = float(ohlcv_bars[j].get("low", ohlcv_bars[j].get("l", 0)))
                if other_low <= low:
                    is_swing_low = False
                    break

        if is_swing_low:
            swing_lows.append((i, low))

    return {"swing_highs": swing_highs, "swing_lows": swing_lows}


def analyze_trend_structure(ohlcv_bars: List[dict]) -> Dict:
    """
    分析趋势结构: HH/HL (上涨) vs LL/LH (下跌)

    核心逻辑:
    - 连续2+个HH且2+个HL = 确认上涨趋势
    - 连续2+个LL且2+个LH = 确认下跌趋势
    - 混合 = 震荡

    Returns:
        {
            "structure": "UPTREND" | "DOWNTREND" | "RANGING",
            "hh_count": int,  # Higher High数量
            "hl_count": int,  # Higher Low数量
            "ll_count": int,  # Lower Low数量
            "lh_count": int,  # Lower High数量
            "confidence": float,
            "last_swing_high": float,
            "last_swing_low": float,
        }
    """
    result = {
        "structure": "RANGING",
        "hh_count": 0,
        "hl_count": 0,
        "ll_count": 0,
        "lh_count": 0,
        "confidence": 0.5,
        "last_swing_high": 0.0,
        "last_swing_low": 0.0,
    }

    if len(ohlcv_bars) < 20:
        return result

    swings = find_swing_points(ohlcv_bars, lookback=RegimeConfig.SWING_LOOKBACK)
    swing_highs = swings["swing_highs"]
    swing_lows = swings["swing_lows"]

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return result

    # 取最近5个swing点分析
    recent_highs = swing_highs[-5:] if len(swing_highs) >= 5 else swing_highs
    recent_lows = swing_lows[-5:] if len(swing_lows) >= 5 else swing_lows

    # 统计HH/HL/LL/LH
    hh_count = 0
    lh_count = 0
    for i in range(1, len(recent_highs)):
        if recent_highs[i][1] > recent_highs[i-1][1]:
            hh_count += 1
        elif recent_highs[i][1] < recent_highs[i-1][1]:
            lh_count += 1

    hl_count = 0
    ll_count = 0
    for i in range(1, len(recent_lows)):
        if recent_lows[i][1] > recent_lows[i-1][1]:
            hl_count += 1
        elif recent_lows[i][1] < recent_lows[i-1][1]:
            ll_count += 1

    result["hh_count"] = hh_count
    result["hl_count"] = hl_count
    result["ll_count"] = ll_count
    result["lh_count"] = lh_count
    result["last_swing_high"] = recent_highs[-1][1] if recent_highs else 0.0
    result["last_swing_low"] = recent_lows[-1][1] if recent_lows else 0.0

    # 判断结构
    if hh_count >= RegimeConfig.MIN_HH_HL_COUNT and hl_count >= RegimeConfig.MIN_HH_HL_COUNT:
        result["structure"] = "UPTREND"
        result["confidence"] = 0.7 + min(0.25, (hh_count + hl_count) * 0.05)
    elif ll_count >= RegimeConfig.MIN_LL_LH_COUNT and lh_count >= RegimeConfig.MIN_LL_LH_COUNT:
        result["structure"] = "DOWNTREND"
        result["confidence"] = 0.7 + min(0.25, (ll_count + lh_count) * 0.05)
    else:
        result["structure"] = "RANGING"
        # 混乱程度越高，震荡越确定
        chaos = (hh_count + lh_count + hl_count + ll_count)
        if chaos >= 4:
            result["confidence"] = 0.8  # 高混乱 = 确定震荡
        else:
            result["confidence"] = 0.55

    return result


# ========================================================================
# 模块3: 动态阈值校准 (根据品种波动率调整)
# ========================================================================

def calculate_atr_percentage(ohlcv_bars: List[dict], period: int = 14) -> float:
    """
    计算ATR百分比 (ATR / 当前价格 * 100)
    """
    if len(ohlcv_bars) < period + 1:
        return 2.0  # 默认2%

    bars = ohlcv_bars[-(period + 1):]
    tr_list = []

    for i in range(1, len(bars)):
        h = float(bars[i].get("high", bars[i].get("h", 0)))
        l = float(bars[i].get("low", bars[i].get("l", 0)))
        prev_c = float(bars[i-1].get("close", bars[i-1].get("c", 0)))

        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    if not tr_list:
        return 2.0

    atr = sum(tr_list) / len(tr_list)
    current_price = float(ohlcv_bars[-1].get("close", ohlcv_bars[-1].get("c", 1)))

    if current_price == 0:
        return 2.0

    return (atr / current_price) * 100


def get_dynamic_choppiness_thresholds(symbol: str, ohlcv_bars: List[dict]) -> Tuple[float, float]:
    """
    根据品种波动率动态调整Choppiness阈值

    核心逻辑:
    - 高波动品种: 收紧阈值 (更难判定为趋势)
    - 低波动品种: 放宽阈值 (更容易判定为趋势)

    Returns:
        (trending_threshold, ranging_threshold)
    """
    atr_pct = calculate_atr_percentage(ohlcv_bars)

    # 基础阈值
    trending_base = RegimeConfig.CHOP_TRENDING_BASE
    ranging_base = RegimeConfig.CHOP_RANGING_BASE

    # 高波动品种调整
    if symbol in RegimeConfig.HIGH_VOL_SYMBOLS or atr_pct > 4.0:
        # 高波动: 收紧趋势阈值 (更难被判定为趋势)
        adjustment = min(8, (atr_pct - 2.0) * RegimeConfig.CHOP_ATR_ADJUST_FACTOR)
        trending_threshold = trending_base - adjustment  # 更低才算趋势
        ranging_threshold = ranging_base - adjustment
    elif symbol in RegimeConfig.LOW_VOL_SYMBOLS or atr_pct < 1.5:
        # 低波动: 放宽趋势阈值
        adjustment = min(5, (2.0 - atr_pct) * RegimeConfig.CHOP_ATR_ADJUST_FACTOR)
        trending_threshold = trending_base + adjustment  # 更高也能算趋势
        ranging_threshold = ranging_base + adjustment
    else:
        # 正常波动: 使用基础阈值
        trending_threshold = trending_base
        ranging_threshold = ranging_base

    # 确保阈值合理
    trending_threshold = max(25, min(50, trending_threshold))
    ranging_threshold = max(50, min(75, ranging_threshold))

    return trending_threshold, ranging_threshold


def calculate_choppiness_enhanced(ohlcv_bars: List[dict], symbol: str, period: int = 14) -> Dict:
    """
    增强版Choppiness计算 (动态阈值)

    Returns:
        {
            "value": float,
            "trending_threshold": float,
            "ranging_threshold": float,
            "regime": MarketRegime,
            "confidence": float,
        }
    """
    result = {
        "value": 50.0,
        "trending_threshold": 38.2,
        "ranging_threshold": 61.8,
        "regime": MarketRegime.TRANSITIONING,
        "confidence": 0.5,
    }

    if len(ohlcv_bars) < period + 1:
        return result

    # 计算Choppiness Index
    bars = ohlcv_bars[-(period + 1):]
    atr_sum = 0
    highest = float('-inf')
    lowest = float('inf')

    for i in range(1, len(bars)):
        h = float(bars[i].get("high", bars[i].get("h", 0)))
        l = float(bars[i].get("low", bars[i].get("l", 0)))
        prev_c = float(bars[i-1].get("close", bars[i-1].get("c", 0)))

        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        atr_sum += tr
        highest = max(highest, h)
        lowest = min(lowest, l)

    range_hl = highest - lowest
    if range_hl <= 0 or atr_sum <= 0:
        return result

    try:
        chop = 100 * math.log10(atr_sum / range_hl) / math.log10(period)
        chop = max(0, min(100, chop))
    except:
        chop = 50.0

    result["value"] = chop

    # 获取动态阈值
    trending_th, ranging_th = get_dynamic_choppiness_thresholds(symbol, ohlcv_bars)
    result["trending_threshold"] = trending_th
    result["ranging_threshold"] = ranging_th

    # 判断regime
    if chop < trending_th:
        result["regime"] = MarketRegime.STRONG_TRENDING
        result["confidence"] = 0.85
    elif chop < (trending_th + ranging_th) / 2:
        result["regime"] = MarketRegime.TRENDING
        result["confidence"] = 0.7
    elif chop > ranging_th:
        result["regime"] = MarketRegime.CHOPPY
        result["confidence"] = 0.85
    elif chop > (trending_th + ranging_th) / 2:
        result["regime"] = MarketRegime.RANGING
        result["confidence"] = 0.7
    else:
        result["regime"] = MarketRegime.TRANSITIONING
        result["confidence"] = 0.5

    return result


# ========================================================================
# 模块4: 增强版Human信号计算
# ========================================================================

def compute_human_signals_enhanced(
    ohlcv_bars: List[dict],
    pos_ratio: float = 0.5,
    trend_x4: str = None,
    symbol: str = None,
) -> Dict:
    """
    增强版Human信号计算

    改进点:
    1. 多周期斜率融合 (替代单周期visual_slope)
    2. 趋势结构确认 (HH/HL/LL/LH)
    3. 一致性检测增强信号
    4. 动态置信度
    5. [v3.170] K线形态检测 (模块7)
    6. [v3.170] 量价模式验证 (模块8)

    Returns:
        {
            # 原有字段 (兼容)
            "visual_slope": str,
            "human_signal": str,
            "confidence": float,

            # 新增增强字段
            "multi_slope": dict,      # 多周期斜率详情
            "structure": dict,        # 趋势结构分析
            "regime_vote": str,       # TRENDING / RANGING
            "regime_direction": str,  # UP / DOWN / SIDE
            "regime_confidence": float,
            "enhancement_used": bool,

            # v3.170新增: K线形态和量价分析
            "kline_patterns": dict,   # K线形态检测结果
            "volume_patterns": dict,  # 量价模式检测结果
        }
    """
    result = {
        # 兼容字段
        "visual_slope": "FLAT",
        "human_signal": "HOLD",
        "confidence": 0.5,
        "recent_impact": "MIXED",
        "volume_feel": "NORMAL",
        "position_feel": "MID",

        # 增强字段
        "multi_slope": {},
        "structure": {},
        "regime_vote": "RANGING",
        "regime_direction": "SIDE",
        "regime_confidence": 0.5,
        "enhancement_used": True,

        # v3.170新增
        "kline_patterns": {},
        "volume_patterns": {},
    }

    if not ohlcv_bars or len(ohlcv_bars) < 10:
        result["enhancement_used"] = False
        return result

    # ========== 1. 多周期斜率融合 ==========
    multi_slope = compute_multi_period_slope(ohlcv_bars)
    result["multi_slope"] = multi_slope

    # 映射到visual_slope (兼容原有逻辑)
    direction = multi_slope["direction"]
    if direction == TrendDirection.STRONG_UP:
        result["visual_slope"] = "STEEP_UP"
    elif direction == TrendDirection.UP:
        result["visual_slope"] = "UP"
    elif direction == TrendDirection.STRONG_DOWN:
        result["visual_slope"] = "STEEP_DOWN"
    elif direction == TrendDirection.DOWN:
        result["visual_slope"] = "DOWN"
    else:
        result["visual_slope"] = "FLAT"

    # ========== 2. 趋势结构确认 ==========
    structure = analyze_trend_structure(ohlcv_bars)
    result["structure"] = structure

    # ========== 2.5 [v3.170] K线形态检测 (模块7) ==========
    # 判断市场类型: 加密货币阈值2%, 美股阈值1.5%
    market_type = "crypto" if symbol and "USD" in symbol.upper() else "stock"
    kline_patterns = detect_kline_patterns(ohlcv_bars, market_type)
    result["kline_patterns"] = kline_patterns

    # ========== 2.6 [v3.170] 量价模式验证 (模块8) ==========
    volume_patterns = detect_volume_patterns(ohlcv_bars)
    result["volume_patterns"] = volume_patterns

    # ========== 3. 综合判断Regime ==========
    # 斜率投票
    slope_vote_trending = direction in [TrendDirection.STRONG_UP, TrendDirection.UP,
                                         TrendDirection.STRONG_DOWN, TrendDirection.DOWN]
    slope_vote_up = direction in [TrendDirection.STRONG_UP, TrendDirection.UP]
    slope_vote_down = direction in [TrendDirection.STRONG_DOWN, TrendDirection.DOWN]

    # 结构投票
    structure_vote_trending = structure["structure"] in ["UPTREND", "DOWNTREND"]
    structure_vote_up = structure["structure"] == "UPTREND"
    structure_vote_down = structure["structure"] == "DOWNTREND"

    # 一致性增强
    consistency_boost = multi_slope["consistency"] >= RegimeConfig.CONSISTENCY_THRESHOLD

    # v3.170: Human增强诊断日志 (同时输出到文件)
    from datetime import datetime
    diag_lines = []
    diag_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] [v3.170 Human增强] {symbol}")
    diag_lines.append(f"  多周期斜率: weighted={multi_slope['weighted_slope']:.4f}, direction={direction.value}, consistency={multi_slope['consistency']:.2f}")
    slopes_str = ", ".join([f"{k}={v:.4f}" for k, v in multi_slope.get('slopes', {}).items()])
    diag_lines.append(f"  斜率各周期: {slopes_str}")
    diag_lines.append(f"  结构分析: {structure['structure']}, hh={structure.get('hh_count', 0)}, hl={structure.get('hl_count', 0)}, ll={structure.get('ll_count', 0)}, lh={structure.get('lh_count', 0)}")
    diag_lines.append(f"  斜率投票趋势={slope_vote_trending}, 结构投票趋势={structure_vote_trending}")

    # v3.170新增: K线形态和量价模式诊断
    kp = kline_patterns
    diag_lines.append(f"  [v3.170] K线形态: signal={kp.get('pattern_signal', 'N/A')}, strength={kp.get('pattern_strength', 0):.2f}")
    if kp.get('engulfing', {}).get('detected'):
        diag_lines.append(f"    - 吞没: {kp['engulfing']['type']}")
    if kp.get('harami', {}).get('detected'):
        diag_lines.append(f"    - 孕线: {kp['harami']['type']}, 反转概率={kp['harami']['reversal_probability']:.0%}")
    if kp.get('trend_confirm', {}).get('confirmed'):
        diag_lines.append(f"    - 趋势确认: {kp['trend_confirm']['direction']}, 连续{kp['trend_confirm']['consecutive_count']}根")

    vp = volume_patterns
    diag_lines.append(f"  [v3.170] 量价模式: signal={vp.get('volume_signal', 'N/A')}, conf={vp.get('volume_confidence', 0):.2f}")
    if vp.get('strong_weak', {}).get('pattern') not in ['UNKNOWN', None]:
        diag_lines.append(f"    - 强弱: {vp['strong_weak']['pattern']}")
    if vp.get('volume_warning', {}).get('warning'):
        diag_lines.append(f"    - 巨量警示: {vp['volume_warning']['type']}, ratio={vp['volume_warning']['volume_ratio']:.1f}x")
    if vp.get('divergence', {}).get('divergence'):
        diag_lines.append(f"    - 量价背离: {vp['divergence']['type']}")

    for line in diag_lines:
        print(line)

    try:
        with open("logs/regime_diagnosis.txt", "a", encoding="utf-8") as f:
            f.write("\n".join(diag_lines) + "\n\n")
    except:
        pass

    # ========== v3.170: K线形态和量价模式投票 ==========
    # K线形态投票
    kline_vote_up = kline_patterns.get("pattern_signal") == "BUY_SIGNAL"
    kline_vote_down = kline_patterns.get("pattern_signal") == "SELL_SIGNAL"
    kline_strength = kline_patterns.get("pattern_strength", 0)

    # 量价模式投票
    volume_vote_up = volume_patterns.get("volume_signal") == "BULLISH"
    volume_vote_down = volume_patterns.get("volume_signal") == "BEARISH"
    volume_warning = volume_patterns.get("volume_signal") == "WARNING"
    volume_conf = volume_patterns.get("volume_confidence", 0.5)

    # 综合判断
    if slope_vote_trending and structure_vote_trending:
        # 斜率+结构都确认趋势
        result["regime_vote"] = "TRENDING"
        if slope_vote_up and structure_vote_up:
            result["regime_direction"] = "UP"
        elif slope_vote_down and structure_vote_down:
            result["regime_direction"] = "DOWN"
        else:
            result["regime_direction"] = "SIDE"  # 方向冲突

        # 高置信度
        base_conf = (multi_slope["confidence"] + structure["confidence"]) / 2
        result["regime_confidence"] = min(0.95, base_conf + (0.1 if consistency_boost else 0))

        # v3.170: K线形态增强置信度
        if result["regime_direction"] == "UP" and kline_vote_up and kline_strength > 0.6:
            result["regime_confidence"] = min(0.98, result["regime_confidence"] + 0.05)
        elif result["regime_direction"] == "DOWN" and kline_vote_down and kline_strength > 0.6:
            result["regime_confidence"] = min(0.98, result["regime_confidence"] + 0.05)

        # v3.170: 量价验证
        if volume_warning:
            result["regime_confidence"] = max(0.5, result["regime_confidence"] - 0.15)  # 巨量警示降低置信度

    elif slope_vote_trending or structure_vote_trending:
        # 只有一方确认趋势
        result["regime_vote"] = "TRENDING"
        if slope_vote_up or structure_vote_up:
            result["regime_direction"] = "UP"
        elif slope_vote_down or structure_vote_down:
            result["regime_direction"] = "DOWN"
        else:
            result["regime_direction"] = "SIDE"

        # 中等置信度
        result["regime_confidence"] = 0.6

        # v3.170: K线形态可以增强弱趋势判断
        if result["regime_direction"] == "UP" and kline_vote_up:
            result["regime_confidence"] += kline_strength * 0.1
        elif result["regime_direction"] == "DOWN" and kline_vote_down:
            result["regime_confidence"] += kline_strength * 0.1

    else:
        # 都没确认趋势 = 震荡
        result["regime_vote"] = "RANGING"
        result["regime_direction"] = "SIDE"
        result["regime_confidence"] = max(multi_slope["confidence"], structure["confidence"])

        # v3.170: K线形态可能暗示趋势即将形成
        if kline_vote_up and kline_strength > 0.7:
            result["regime_direction"] = "UP"  # 暗示可能向上
            result["pending_breakout"] = "UP"
        elif kline_vote_down and kline_strength > 0.7:
            result["regime_direction"] = "DOWN"  # 暗示可能向下
            result["pending_breakout"] = "DOWN"

    # ========== 4. 生成Human信号 ==========
    # 结合regime和位置
    if result["regime_vote"] == "TRENDING":
        if result["regime_direction"] == "UP":
            if pos_ratio < 0.3:  # 低位+上涨趋势
                result["human_signal"] = "STRONG_BUY"
                result["confidence"] = result["regime_confidence"]
            elif pos_ratio < 0.6:
                result["human_signal"] = "BUY"
                result["confidence"] = result["regime_confidence"] * 0.9
            else:  # 高位谨慎
                result["human_signal"] = "HOLD"
                result["confidence"] = 0.6
        elif result["regime_direction"] == "DOWN":
            if pos_ratio > 0.7:  # 高位+下跌趋势
                result["human_signal"] = "STRONG_SELL"
                result["confidence"] = result["regime_confidence"]
            elif pos_ratio > 0.4:
                result["human_signal"] = "SELL"
                result["confidence"] = result["regime_confidence"] * 0.9
            else:  # 低位谨慎
                result["human_signal"] = "HOLD"
                result["confidence"] = 0.6
        else:
            result["human_signal"] = "HOLD"
            result["confidence"] = 0.5
    else:
        # 震荡市场
        # v3.050修复: 加入大周期趋势保护，避免逆势操作
        trend_x4_lower = trend_x4.lower() if trend_x4 else ""

        if trend_x4_lower == "up" and pos_ratio > 0.6:
            # 大周期上涨 + 高位震荡 = 不应该卖，等待回调
            result["human_signal"] = "HOLD"
            result["confidence"] = 0.55
            result["big_trend_protection"] = "UP_HIGH_NO_SELL"
            print(f"[v3.050] 大周期保护触发: trend_x4=UP, pos={pos_ratio:.1%} → HOLD (原本会SELL)")
            # R4追踪: 记录大周期保护触发
            if L1_TRACKER_ENABLED and symbol and ohlcv_bars:
                entry_price = float(ohlcv_bars[-1].get("close", ohlcv_bars[-1].get("c", 0)))
                get_tracker().record_big_trend_protection(symbol, trend_x4, pos_ratio, "SELL", entry_price)
        elif trend_x4_lower == "down" and pos_ratio < 0.4:
            # 大周期下跌 + 低位震荡 = 不应该买，等待反弹
            result["human_signal"] = "HOLD"
            result["confidence"] = 0.55
            result["big_trend_protection"] = "DOWN_LOW_NO_BUY"
            print(f"[v3.050] 大周期保护触发: trend_x4=DOWN, pos={pos_ratio:.1%} → HOLD (原本会BUY)")
            # R4追踪: 记录大周期保护触发
            if L1_TRACKER_ENABLED and symbol and ohlcv_bars:
                entry_price = float(ohlcv_bars[-1].get("close", ohlcv_bars[-1].get("c", 0)))
                get_tracker().record_big_trend_protection(symbol, trend_x4, pos_ratio, "BUY", entry_price)
        elif pos_ratio < 0.2:
            # 只有大周期不是下跌时才在低位买
            if trend_x4_lower != "down":
                result["human_signal"] = "BUY"  # 震荡低位买
                result["confidence"] = 0.6
            else:
                result["human_signal"] = "HOLD"
                result["confidence"] = 0.5
        elif pos_ratio > 0.8:
            # 只有大周期不是上涨时才在高位卖
            if trend_x4_lower != "up":
                result["human_signal"] = "SELL"  # 震荡高位卖
                result["confidence"] = 0.6
            else:
                result["human_signal"] = "HOLD"
                result["confidence"] = 0.5
        else:
            result["human_signal"] = "HOLD"
            result["confidence"] = 0.7  # 震荡中间观望

    # 位置感受
    if pos_ratio < 0.25:
        result["position_feel"] = "LOW"
    elif pos_ratio > 0.75:
        result["position_feel"] = "HIGH"
    else:
        result["position_feel"] = "MID"

    return result


# ========================================================================
# 模块5: 增强版三方投票
# ========================================================================

def get_human_regime_vote_enhanced(human_signals: Dict) -> Dict:
    """
    增强版Human趋势投票 (使用多周期斜率+结构)

    Returns:
        {"vote": str, "direction": str, "confidence": float}
    """
    if human_signals.get("enhancement_used"):
        return {
            "vote": human_signals.get("regime_vote", "RANGING"),
            "direction": human_signals.get("regime_direction", "SIDE"),
            "confidence": human_signals.get("regime_confidence", 0.5),
        }
    else:
        # 回退到原有逻辑
        slope = human_signals.get("visual_slope", "FLAT").upper()
        if slope == "STEEP_UP":
            return {"vote": "TRENDING", "direction": "UP", "confidence": 0.9}
        elif slope == "UP":
            return {"vote": "TRENDING", "direction": "UP", "confidence": 0.6}
        elif slope == "STEEP_DOWN":
            return {"vote": "TRENDING", "direction": "DOWN", "confidence": 0.9}
        elif slope == "DOWN":
            return {"vote": "TRENDING", "direction": "DOWN", "confidence": 0.6}
        else:
            return {"vote": "RANGING", "direction": "SIDE", "confidence": 0.7}


def get_tech_regime_vote_enhanced(
    ohlcv_bars: List[dict],
    symbol: str,
    adx: float,
    plus_di: float,
    minus_di: float,
) -> Dict:
    """
    增强版Tech趋势投票 (动态Choppiness阈值)

    Returns:
        {"vote": str, "direction": str, "confidence": float, "choppiness": dict}
    """
    # 计算增强版Choppiness
    chop_result = calculate_choppiness_enhanced(ohlcv_bars, symbol)

    # DI方向
    di_diff = plus_di - minus_di
    if di_diff > 5:
        di_direction = "UP"
    elif di_diff < -5:
        di_direction = "DOWN"
    else:
        di_direction = "SIDE"

    # ADX强度
    adx_strong = adx > 25
    adx_medium = adx > 18

    # 综合判断
    if chop_result["regime"] in [MarketRegime.STRONG_TRENDING, MarketRegime.TRENDING]:
        if adx_strong or adx_medium:
            return {
                "vote": "TRENDING",
                "direction": di_direction,
                "confidence": chop_result["confidence"],
                "choppiness": chop_result,
            }
        else:
            return {
                "vote": "TRENDING",
                "direction": di_direction,
                "confidence": chop_result["confidence"] * 0.8,
                "choppiness": chop_result,
            }
    elif chop_result["regime"] in [MarketRegime.RANGING, MarketRegime.CHOPPY]:
        return {
            "vote": "RANGING",
            "direction": "SIDE",
            "confidence": chop_result["confidence"],
            "choppiness": chop_result,
        }
    else:
        return {
            "vote": "RANGING",
            "direction": "SIDE",
            "confidence": 0.5,
            "choppiness": chop_result,
        }


def determine_market_regime_enhanced(
    ai_signals: Dict,
    human_signals: Dict,
    tech_signals: Dict,
    ohlcv_bars: List[dict],
    symbol: str,
) -> Dict:
    """
    增强版市场状态判断

    改进点:
    1. Human使用多周期斜率融合投票
    2. Tech使用动态Choppiness阈值
    3. 增加结构确认权重

    Returns:
        {
            "regime": str,           # TRENDING / RANGING
            "direction": str,        # UP / DOWN / SIDE
            "strength": float,       # 0-1
            "votes": dict,
            "consensus": str,
            "confidence": float,
            "enhancement_details": dict,
        }
    """
    # 1. AI投票 (保持原有逻辑)
    trend120 = ai_signals.get("trend120", "UNKNOWN").upper()
    if trend120 in ("UP",):
        ai_vote = {"vote": "TRENDING", "direction": "UP", "confidence": 0.7}
    elif trend120 in ("DOWN",):
        ai_vote = {"vote": "TRENDING", "direction": "DOWN", "confidence": 0.7}
    elif trend120 in ("RANGE", "CHOPPY", "SIDEWAYS"):
        ai_vote = {"vote": "RANGING", "direction": "SIDE", "confidence": 0.7}
    else:
        ai_vote = {"vote": "UNKNOWN", "direction": "SIDE", "confidence": 0.3}

    # 2. Human增强投票
    human_vote = get_human_regime_vote_enhanced(human_signals)

    # 3. Tech增强投票
    raw = tech_signals.get("raw", {})
    adx = raw.get("adx", 20)
    plus_di = raw.get("plus_di", 0)
    minus_di = raw.get("minus_di", 0)
    tech_vote = get_tech_regime_vote_enhanced(ohlcv_bars, symbol, adx, plus_di, minus_di)

    votes = {
        "ai": ai_vote,
        "human": human_vote,
        "tech": tech_vote,
    }

    # 4. 统计投票
    trending_votes = sum(1 for v in votes.values() if v["vote"] == "TRENDING")
    ranging_votes = sum(1 for v in votes.values() if v["vote"] == "RANGING")

    up_votes = sum(1 for v in votes.values() if v["direction"] == "UP")
    down_votes = sum(1 for v in votes.values() if v["direction"] == "DOWN")

    # 5. 结构确认加权 (如果有)
    structure_bonus = 0
    if human_signals.get("structure", {}).get("structure") in ["UPTREND", "DOWNTREND"]:
        structure_bonus = 0.5  # 结构确认加0.5票
        if human_signals["structure"]["structure"] == "UPTREND":
            up_votes += structure_bonus
        else:
            down_votes += structure_bonus
        trending_votes += structure_bonus

    # 6. 综合判断
    result = {
        "regime": "RANGING",
        "direction": "SIDE",
        "strength": 0.5,
        "votes": votes,
        "consensus": "SPLIT",
        "confidence": 0.5,
        "enhancement_details": {
            "structure_bonus": structure_bonus,
            "choppiness": tech_vote.get("choppiness", {}),
            "multi_slope": human_signals.get("multi_slope", {}),
        },
    }

    if trending_votes >= 2.5:
        result["regime"] = "TRENDING"
        result["consensus"] = "STRONG" if trending_votes >= 3 else "TWO_AGREE"
        result["strength"] = 0.8 + (trending_votes - 2) * 0.1

        if up_votes > down_votes:
            result["direction"] = "UP"
        elif down_votes > up_votes:
            result["direction"] = "DOWN"
        else:
            result["direction"] = "SIDE"

        # 加权置信度
        result["confidence"] = (
            ai_vote["confidence"] * 0.35 +
            human_vote["confidence"] * 0.35 +
            tech_vote["confidence"] * 0.30
        )

    elif trending_votes >= 2:
        result["regime"] = "TRENDING"
        result["consensus"] = "TWO_AGREE"
        result["strength"] = 0.65

        if up_votes > down_votes:
            result["direction"] = "UP"
        elif down_votes > up_votes:
            result["direction"] = "DOWN"
        else:
            result["direction"] = "SIDE"

        result["confidence"] = 0.6

    else:
        result["regime"] = "RANGING"
        result["consensus"] = "RANGING_CONSENSUS" if ranging_votes >= 2 else "SPLIT"
        result["strength"] = 0.5 + ranging_votes * 0.1
        result["direction"] = "SIDE"
        result["confidence"] = 0.7 if ranging_votes >= 2 else 0.5

    return result


# ========================================================================
# 模块6: 集成入口
# ========================================================================

def compute_l1_regime_enhanced(
    ohlcv_bars: List[dict],
    ai_signals: Dict,
    symbol: str,
    pos_ratio: float = 0.5,
    trend_x4: str = None,
) -> Dict:
    """
    L1趋势/震荡识别增强版主入口

    Args:
        ohlcv_bars: K线数据
        ai_signals: AI模块信号
        symbol: 品种代码
        pos_ratio: 位置比率
        trend_x4: 4倍周期趋势

    Returns:
        {
            "regime": str,
            "direction": str,
            "strength": float,
            "confidence": float,

            "human_signals": dict,   # 增强版Human信号
            "tech_signals": dict,    # 增强版Tech信号
            "votes": dict,
            "consensus": str,

            "recommendations": {
                "l1_strategy": str,  # TREND_FOLLOW / RANGE_TRADE / NEUTRAL
                "l2_strategy": str,
            }
        }
    """
    # 1. 计算增强版Human信号
    human_signals = compute_human_signals_enhanced(
        ohlcv_bars=ohlcv_bars,
        pos_ratio=pos_ratio,
        trend_x4=trend_x4,
        symbol=symbol,
    )

    # 2. 构建Tech信号 (需要外部计算ADX等)
    # 这里简化处理，实际应该复用现有的compute_tech_signals_v2900
    tech_signals = {
        "adx_strength": "MEDIUM",
        "choppiness": "MIXED",
        "di_direction": "NEUTRAL",
        "raw": {
            "adx": 20,
            "plus_di": 15,
            "minus_di": 15,
            "choppiness": 50,
        }
    }

    # 3. 综合判断
    regime_result = determine_market_regime_enhanced(
        ai_signals=ai_signals,
        human_signals=human_signals,
        tech_signals=tech_signals,
        ohlcv_bars=ohlcv_bars,
        symbol=symbol,
    )

    # 4. 策略建议
    if regime_result["regime"] == "TRENDING":
        if regime_result["direction"] == "UP":
            l1_strategy = "TREND_FOLLOW_LONG"
            l2_strategy = "PULLBACK_BUY"
        elif regime_result["direction"] == "DOWN":
            l1_strategy = "TREND_FOLLOW_SHORT"
            l2_strategy = "RALLY_SELL"
        else:
            l1_strategy = "TREND_FOLLOW_WAIT"
            l2_strategy = "NEUTRAL"
    else:
        l1_strategy = "RANGE_TRADE"
        l2_strategy = "MEAN_REVERSION"

    # ========== L1规则追踪 ==========
    if L1_TRACKER_ENABLED and ohlcv_bars and symbol:
        try:
            tracker = get_tracker()
            entry_price = float(ohlcv_bars[-1].get("close", ohlcv_bars[-1].get("c", 0)))

            # R1: 多周期斜率 (只在有明确方向时记录)
            multi_slope = human_signals.get("multi_slope", {})
            direction = multi_slope.get("direction")
            if direction and hasattr(direction, 'value'):
                direction_str = direction.value
            else:
                direction_str = str(direction) if direction else "FLAT"

            if direction_str in ["STRONG_UP", "UP", "STRONG_DOWN", "DOWN"]:
                tracker.record_multi_slope(
                    symbol=symbol,
                    weighted_slope=multi_slope.get("weighted_slope", 0),
                    direction=direction_str,
                    consistency=multi_slope.get("consistency", 0),
                    entry_price=entry_price,
                )

            # R2: 趋势结构 (只在确认上涨/下跌时记录)
            structure = human_signals.get("structure", {})
            if structure.get("structure") in ["UPTREND", "DOWNTREND"]:
                tracker.record_structure(
                    symbol=symbol,
                    structure=structure["structure"],
                    hh=structure.get("hh_count", 0),
                    hl=structure.get("hl_count", 0),
                    ll=structure.get("ll_count", 0),
                    lh=structure.get("lh_count", 0),
                    entry_price=entry_price,
                )

            # R3: 动态Choppiness (只在强趋势/震荡时记录)
            chop_result = regime_result.get("enhancement_details", {}).get("choppiness", {})
            chop_regime = chop_result.get("regime")
            if chop_regime:
                if hasattr(chop_regime, 'value'):
                    regime_str = chop_regime.value
                else:
                    regime_str = str(chop_regime)

                if regime_str in ["STRONG_TRENDING", "CHOPPY"]:
                    tracker.record_choppiness(
                        symbol=symbol,
                        chop_value=chop_result.get("value", 50),
                        regime=regime_str,
                        entry_price=entry_price,
                    )

            # R5: 一致性加成 (只在高一致性时记录)
            consistency = multi_slope.get("consistency", 0)
            if consistency >= 0.75:  # 高一致性
                regime_direction = regime_result.get("direction", "SIDE")
                if regime_direction in ["UP", "DOWN"]:
                    tracker.record_consistency_boost(
                        symbol=symbol,
                        consistency=consistency,
                        boosted_direction=regime_direction,
                        entry_price=entry_price,
                    )

            # R6: 三方投票 (每次都记录最终决策)
            votes = regime_result.get("votes", {})
            tracker.record_voting(
                symbol=symbol,
                ai_vote=votes.get("ai", {}).get("direction", "SIDE"),
                human_vote=votes.get("human", {}).get("direction", "SIDE"),
                tech_vote=votes.get("tech", {}).get("direction", "SIDE"),
                final_regime=regime_result.get("regime", "RANGING"),
                final_direction=regime_result.get("direction", "SIDE"),
                entry_price=entry_price,
            )
        except Exception as e:
            print(f"[L1Tracker] 追踪记录失败: {e}")

    return {
        "regime": regime_result["regime"],
        "direction": regime_result["direction"],
        "strength": regime_result["strength"],
        "confidence": regime_result["confidence"],

        "human_signals": human_signals,
        "tech_signals": tech_signals,
        "votes": regime_result["votes"],
        "consensus": regime_result["consensus"],
        "enhancement_details": regime_result.get("enhancement_details", {}),

        "recommendations": {
            "l1_strategy": l1_strategy,
            "l2_strategy": l2_strategy,
        }
    }


# ========================================================================
# 模块7: K线形态检测 (基于云聪13买卖点规则)
# ========================================================================
# 核心规则:
# - 大K线阈值: 加密>=2%, 美股>=1.5%
# - 吞没形态: 实体完全覆盖前一根
# - 孕线形态: 80%概率反转
# - 刺透/乌云: 突破50%位置
# - 连续确认: 3根同向=趋势确认
# ========================================================================

def get_bar_body(bar: dict) -> Tuple[float, float, float]:
    """
    获取K线实体信息
    Returns: (open, close, body_size)
    """
    o = float(bar.get("open", bar.get("o", 0)))
    c = float(bar.get("close", bar.get("c", 0)))
    body = abs(c - o)
    return o, c, body


def is_significant_bar(bar: dict, threshold: float = 0.02) -> dict:
    """
    判断是否为显著K线 (大阳/大阴)

    Args:
        bar: K线数据
        threshold: 涨跌幅阈值 (默认2%)

    Returns:
        {"is_significant": bool, "direction": str, "change_pct": float, "bar_type": str}
    """
    o, c, body = get_bar_body(bar)
    if o == 0:
        return {"is_significant": False, "direction": "NEUTRAL", "change_pct": 0, "bar_type": "NORMAL"}

    change_pct = (c - o) / o

    result = {
        "is_significant": False,
        "direction": "NEUTRAL",
        "change_pct": change_pct,
        "bar_type": "NORMAL",
    }

    if change_pct >= threshold:
        result["is_significant"] = True
        result["direction"] = "UP"
        result["bar_type"] = "BIG_YANG"  # 大阳线
    elif change_pct <= -threshold:
        result["is_significant"] = True
        result["direction"] = "DOWN"
        result["bar_type"] = "BIG_YIN"  # 大阴线
    elif abs(change_pct) < threshold * 0.3:
        result["bar_type"] = "DOJI"  # 十字星

    return result


def detect_engulfing(bars: List[dict]) -> dict:
    """
    检测吞没形态 (Engulfing Pattern)

    规则:
    - 当前实体完全覆盖前一根实体
    - 方向相反

    Returns:
        {"detected": bool, "type": str, "strength": float}
    """
    if len(bars) < 2:
        return {"detected": False, "type": None, "strength": 0}

    prev_bar = bars[-2]
    curr_bar = bars[-1]

    prev_o, prev_c, prev_body = get_bar_body(prev_bar)
    curr_o, curr_c, curr_body = get_bar_body(curr_bar)

    if prev_body == 0 or curr_body == 0:
        return {"detected": False, "type": None, "strength": 0}

    prev_is_bullish = prev_c > prev_o
    curr_is_bullish = curr_c > curr_o

    # 看涨吞没: 前阴后阳，当前实体覆盖前一根
    if not prev_is_bullish and curr_is_bullish:
        if curr_o <= prev_c and curr_c >= prev_o:
            strength = curr_body / prev_body
            return {"detected": True, "type": "BULLISH_ENGULFING", "strength": min(1.0, strength / 2)}

    # 看跌吞没: 前阳后阴，当前实体覆盖前一根
    if prev_is_bullish and not curr_is_bullish:
        if curr_o >= prev_c and curr_c <= prev_o:
            strength = curr_body / prev_body
            return {"detected": True, "type": "BEARISH_ENGULFING", "strength": min(1.0, strength / 2)}

    return {"detected": False, "type": None, "strength": 0}


def detect_harami(bars: List[dict]) -> dict:
    """
    检测孕线形态 (Harami Pattern) - 80%概率反转

    规则:
    - 当前实体完全被前一根实体包含
    - 通常预示反转

    Returns:
        {"detected": bool, "type": str, "reversal_probability": float}
    """
    if len(bars) < 2:
        return {"detected": False, "type": None, "reversal_probability": 0}

    prev_bar = bars[-2]
    curr_bar = bars[-1]

    prev_o, prev_c, prev_body = get_bar_body(prev_bar)
    curr_o, curr_c, curr_body = get_bar_body(curr_bar)

    if prev_body == 0:
        return {"detected": False, "type": None, "reversal_probability": 0}

    prev_is_bullish = prev_c > prev_o
    prev_top = max(prev_o, prev_c)
    prev_bottom = min(prev_o, prev_c)
    curr_top = max(curr_o, curr_c)
    curr_bottom = min(curr_o, curr_c)

    # 孕线: 当前实体完全在前一根实体内
    if curr_top <= prev_top and curr_bottom >= prev_bottom:
        # 孕线大小比例影响反转概率
        size_ratio = curr_body / prev_body if prev_body > 0 else 1
        # 孕线越小，反转概率越高
        reversal_prob = 0.80 - size_ratio * 0.3  # 基础80%
        reversal_prob = max(0.5, min(0.9, reversal_prob))

        if prev_is_bullish:
            return {"detected": True, "type": "BEARISH_HARAMI", "reversal_probability": reversal_prob}
        else:
            return {"detected": True, "type": "BULLISH_HARAMI", "reversal_probability": reversal_prob}

    return {"detected": False, "type": None, "reversal_probability": 0}


def detect_piercing(bars: List[dict]) -> dict:
    """
    检测刺透/乌云盖顶形态

    规则:
    - 刺透: 阴线后阳线，收盘突破前一根50%以上
    - 乌云: 阳线后阴线，收盘跌破前一根50%以上

    Returns:
        {"detected": bool, "type": str, "penetration": float}
    """
    if len(bars) < 2:
        return {"detected": False, "type": None, "penetration": 0}

    prev_bar = bars[-2]
    curr_bar = bars[-1]

    prev_o, prev_c, prev_body = get_bar_body(prev_bar)
    curr_o, curr_c, curr_body = get_bar_body(curr_bar)

    if prev_body == 0:
        return {"detected": False, "type": None, "penetration": 0}

    prev_is_bullish = prev_c > prev_o
    curr_is_bullish = curr_c > curr_o

    # 刺透: 前阴后阳，开盘低于前低，收盘突破前一根50%以上
    if not prev_is_bullish and curr_is_bullish:
        prev_mid = (prev_o + prev_c) / 2
        if curr_o < prev_c and curr_c > prev_mid:
            penetration = (curr_c - prev_c) / prev_body
            return {"detected": True, "type": "PIERCING", "penetration": min(1.0, penetration)}

    # 乌云盖顶: 前阳后阴，开盘高于前高，收盘跌破前一根50%以上
    if prev_is_bullish and not curr_is_bullish:
        prev_mid = (prev_o + prev_c) / 2
        if curr_o > prev_c and curr_c < prev_mid:
            penetration = (prev_c - curr_c) / prev_body
            return {"detected": True, "type": "DARK_CLOUD", "penetration": min(1.0, penetration)}

    return {"detected": False, "type": None, "penetration": 0}


def detect_trend_confirmation(bars: List[dict], threshold: float = 0.02) -> dict:
    """
    检测趋势确认 (连续3根同向K线)

    规则:
    - 连续3根阳线/阴线 = 趋势确认
    - 配合成交量递增更可靠

    Returns:
        {"confirmed": bool, "direction": str, "consecutive_count": int, "volume_support": bool}
    """
    if len(bars) < 3:
        return {"confirmed": False, "direction": "NEUTRAL", "consecutive_count": 0, "volume_support": False}

    recent_bars = bars[-5:]  # 看最近5根

    # 统计连续同向K线
    bullish_count = 0
    bearish_count = 0
    max_bullish_streak = 0
    max_bearish_streak = 0
    current_bullish_streak = 0
    current_bearish_streak = 0

    volumes = []
    for bar in recent_bars:
        o, c, body = get_bar_body(bar)
        v = float(bar.get("volume", bar.get("v", 0)))
        volumes.append(v)

        if c > o:
            current_bullish_streak += 1
            current_bearish_streak = 0
            max_bullish_streak = max(max_bullish_streak, current_bullish_streak)
        elif c < o:
            current_bearish_streak += 1
            current_bullish_streak = 0
            max_bearish_streak = max(max_bearish_streak, current_bearish_streak)
        else:
            current_bullish_streak = 0
            current_bearish_streak = 0

    # 检查成交量是否递增
    volume_support = False
    if len(volumes) >= 3:
        last_3_vols = volumes[-3:]
        if last_3_vols[0] < last_3_vols[1] < last_3_vols[2]:
            volume_support = True

    if max_bullish_streak >= 3:
        return {
            "confirmed": True,
            "direction": "UP",
            "consecutive_count": max_bullish_streak,
            "volume_support": volume_support,
        }
    elif max_bearish_streak >= 3:
        return {
            "confirmed": True,
            "direction": "DOWN",
            "consecutive_count": max_bearish_streak,
            "volume_support": volume_support,
        }

    return {"confirmed": False, "direction": "NEUTRAL", "consecutive_count": 0, "volume_support": False}


def detect_kline_patterns(bars: List[dict], market_type: str = "crypto") -> dict:
    """
    K线形态检测主入口 (模块7入口)

    Args:
        bars: K线数据列表
        market_type: "crypto" (阈值2%) 或 "stock" (阈值1.5%)

    Returns:
        {
            "significant_bar": dict,   # 当前K线是否显著
            "engulfing": dict,         # 吞没形态
            "harami": dict,            # 孕线形态
            "piercing": dict,          # 刺透/乌云
            "trend_confirm": dict,     # 趋势确认
            "pattern_signal": str,     # BUY_SIGNAL / SELL_SIGNAL / NEUTRAL
            "pattern_strength": float, # 0-1
        }
    """
    threshold = 0.02 if market_type == "crypto" else 0.015

    result = {
        "significant_bar": {"is_significant": False},
        "engulfing": {"detected": False},
        "harami": {"detected": False},
        "piercing": {"detected": False},
        "trend_confirm": {"confirmed": False},
        "pattern_signal": "NEUTRAL",
        "pattern_strength": 0,
    }

    if not bars or len(bars) < 3:
        return result

    # 检测各种形态
    result["significant_bar"] = is_significant_bar(bars[-1], threshold)
    result["engulfing"] = detect_engulfing(bars)
    result["harami"] = detect_harami(bars)
    result["piercing"] = detect_piercing(bars)
    result["trend_confirm"] = detect_trend_confirmation(bars, threshold)

    # 综合信号判断
    buy_signals = []
    sell_signals = []

    # 吞没形态
    if result["engulfing"]["detected"]:
        if result["engulfing"]["type"] == "BULLISH_ENGULFING":
            buy_signals.append(("engulfing", result["engulfing"]["strength"]))
        elif result["engulfing"]["type"] == "BEARISH_ENGULFING":
            sell_signals.append(("engulfing", result["engulfing"]["strength"]))

    # 孕线形态 (反转信号)
    if result["harami"]["detected"]:
        prob = result["harami"]["reversal_probability"]
        if result["harami"]["type"] == "BULLISH_HARAMI":
            buy_signals.append(("harami", prob))
        elif result["harami"]["type"] == "BEARISH_HARAMI":
            sell_signals.append(("harami", prob))

    # 刺透/乌云
    if result["piercing"]["detected"]:
        pen = result["piercing"]["penetration"]
        if result["piercing"]["type"] == "PIERCING":
            buy_signals.append(("piercing", pen))
        elif result["piercing"]["type"] == "DARK_CLOUD":
            sell_signals.append(("piercing", pen))

    # 趋势确认
    if result["trend_confirm"]["confirmed"]:
        strength = 0.7 + (0.2 if result["trend_confirm"]["volume_support"] else 0)
        if result["trend_confirm"]["direction"] == "UP":
            buy_signals.append(("trend_confirm", strength))
        elif result["trend_confirm"]["direction"] == "DOWN":
            sell_signals.append(("trend_confirm", strength))

    # 计算最终信号
    buy_strength = sum(s[1] for s in buy_signals) / len(buy_signals) if buy_signals else 0
    sell_strength = sum(s[1] for s in sell_signals) / len(sell_signals) if sell_signals else 0

    if buy_strength > sell_strength and buy_strength > 0.5:
        result["pattern_signal"] = "BUY_SIGNAL"
        result["pattern_strength"] = buy_strength
    elif sell_strength > buy_strength and sell_strength > 0.5:
        result["pattern_signal"] = "SELL_SIGNAL"
        result["pattern_strength"] = sell_strength

    return result


# ========================================================================
# 模块8: 量价模式验证 (基于云聪13买卖点规则)
# ========================================================================
# 核心规则:
# - 缩量验证: 回调/反弹成交量≤前期50%
# - 强弱结合: 放量上涨+缩量回调=健康上涨
# - 巨量警示: 单根成交量>MA20的2倍需警惕
# - 量价背离: 价格新高但成交量递减=见顶信号
# ========================================================================

def calculate_volume_ma(bars: List[dict], period: int = 20) -> float:
    """计算成交量移动平均"""
    if len(bars) < period:
        return 0

    volumes = [float(bar.get("volume", bar.get("v", 0))) for bar in bars[-period:]]
    return sum(volumes) / len(volumes) if volumes else 0


def detect_volume_shrink(bars: List[dict], threshold: float = 0.5) -> dict:
    """
    检测缩量回调/反弹

    规则:
    - 回调时成交量 ≤ 前期上涨成交量的50%
    - 缩量回调后继续上涨概率高

    Returns:
        {"detected": bool, "shrink_ratio": float, "context": str}
    """
    if len(bars) < 5:
        return {"detected": False, "shrink_ratio": 1.0, "context": "INSUFFICIENT_DATA"}

    # 分析最近5根K线
    recent = bars[-5:]
    volumes = [float(bar.get("volume", bar.get("v", 0))) for bar in recent]

    # 找到成交量最高点和当前成交量
    max_vol = max(volumes[:-1]) if len(volumes) > 1 else volumes[0]
    curr_vol = volumes[-1]

    if max_vol == 0:
        return {"detected": False, "shrink_ratio": 1.0, "context": "NO_VOLUME"}

    shrink_ratio = curr_vol / max_vol

    # 判断是回调还是反弹
    last_bar = bars[-1]
    o, c, body = get_bar_body(last_bar)
    is_pullback = c < o  # 阴线=回调

    if shrink_ratio <= threshold:
        context = "PULLBACK_SHRINK" if is_pullback else "RALLY_SHRINK"
        return {"detected": True, "shrink_ratio": shrink_ratio, "context": context}

    return {"detected": False, "shrink_ratio": shrink_ratio, "context": "NORMAL"}


def detect_strong_weak_pattern(bars: List[dict], lookback: int = 10) -> dict:
    """
    检测强弱量价配合模式

    规则:
    - 健康上涨: 放量阳线 + 缩量阴线
    - 健康下跌: 放量阴线 + 缩量阳线
    - 不健康: 放量阴线 + 放量阳线 (多空激战)

    Returns:
        {"pattern": str, "health_score": float, "detail": dict}
    """
    if len(bars) < lookback:
        return {"pattern": "UNKNOWN", "health_score": 0.5, "detail": {}}

    recent = bars[-lookback:]

    bullish_volumes = []
    bearish_volumes = []

    for bar in recent:
        o, c, body = get_bar_body(bar)
        v = float(bar.get("volume", bar.get("v", 0)))

        if c > o:
            bullish_volumes.append(v)
        elif c < o:
            bearish_volumes.append(v)

    if not bullish_volumes or not bearish_volumes:
        return {"pattern": "ONE_SIDED", "health_score": 0.6, "detail": {}}

    avg_bullish_vol = sum(bullish_volumes) / len(bullish_volumes)
    avg_bearish_vol = sum(bearish_volumes) / len(bearish_volumes)

    detail = {
        "avg_bullish_vol": avg_bullish_vol,
        "avg_bearish_vol": avg_bearish_vol,
        "bullish_count": len(bullish_volumes),
        "bearish_count": len(bearish_volumes),
    }

    # 判断模式
    if avg_bullish_vol > avg_bearish_vol * 1.3:
        # 阳线成交量明显大于阴线 = 健康上涨
        health_score = min(1.0, avg_bullish_vol / avg_bearish_vol / 2)
        return {"pattern": "HEALTHY_UP", "health_score": health_score, "detail": detail}
    elif avg_bearish_vol > avg_bullish_vol * 1.3:
        # 阴线成交量明显大于阳线 = 健康下跌
        health_score = min(1.0, avg_bearish_vol / avg_bullish_vol / 2)
        return {"pattern": "HEALTHY_DOWN", "health_score": health_score, "detail": detail}
    else:
        # 多空激战
        return {"pattern": "CONTESTED", "health_score": 0.4, "detail": detail}


def detect_volume_warning(bars: List[dict], lookback: int = 3) -> dict:
    """
    检测巨量警示

    规则:
    - 单根成交量 > MA20的2倍 = 巨量
    - 巨量阳线在高位 = 可能见顶
    - 巨量阴线在低位 = 可能见底

    Returns:
        {"warning": bool, "type": str, "volume_ratio": float}
    """
    if len(bars) < 21:
        return {"warning": False, "type": None, "volume_ratio": 1.0}

    vol_ma = calculate_volume_ma(bars, 20)
    if vol_ma == 0:
        return {"warning": False, "type": None, "volume_ratio": 1.0}

    # 检查最近几根K线
    for i in range(-lookback, 0):
        bar = bars[i]
        v = float(bar.get("volume", bar.get("v", 0)))
        ratio = v / vol_ma

        if ratio >= 2.0:
            o, c, body = get_bar_body(bar)
            is_bullish = c > o

            return {
                "warning": True,
                "type": "HUGE_BULLISH" if is_bullish else "HUGE_BEARISH",
                "volume_ratio": ratio,
            }

    return {"warning": False, "type": None, "volume_ratio": 1.0}


def detect_volume_price_divergence(bars: List[dict]) -> dict:
    """
    检测量价背离

    规则:
    - 顶背离: 价格创新高，成交量递减
    - 底背离: 价格创新低，成交量递减

    Returns:
        {"divergence": bool, "type": str, "confidence": float}
    """
    if len(bars) < 10:
        return {"divergence": False, "type": None, "confidence": 0}

    recent = bars[-10:]

    # 找价格极值点
    highs = [float(bar.get("high", bar.get("h", 0))) for bar in recent]
    lows = [float(bar.get("low", bar.get("l", 0))) for bar in recent]
    volumes = [float(bar.get("volume", bar.get("v", 0))) for bar in recent]

    # 检查顶背离: 最近价格高点 > 前期高点，但成交量递减
    if highs[-1] == max(highs) and highs[-3] < highs[-1]:
        # 价格创新高
        if volumes[-1] < volumes[-3] and volumes[-3] < volumes[-5]:
            # 成交量递减
            return {"divergence": True, "type": "TOP_DIVERGENCE", "confidence": 0.75}

    # 检查底背离: 最近价格低点 < 前期低点，但成交量递减
    if lows[-1] == min(lows) and lows[-3] > lows[-1]:
        # 价格创新低
        if volumes[-1] < volumes[-3] and volumes[-3] < volumes[-5]:
            # 成交量递减
            return {"divergence": True, "type": "BOTTOM_DIVERGENCE", "confidence": 0.75}

    return {"divergence": False, "type": None, "confidence": 0}


def detect_volume_patterns(bars: List[dict]) -> dict:
    """
    量价模式检测主入口 (模块8入口)

    Returns:
        {
            "volume_shrink": dict,     # 缩量检测
            "strong_weak": dict,       # 强弱模式
            "volume_warning": dict,    # 巨量警示
            "divergence": dict,        # 量价背离
            "volume_signal": str,      # BULLISH / BEARISH / NEUTRAL / WARNING
            "volume_confidence": float,# 0-1
        }
    """
    result = {
        "volume_shrink": {"detected": False},
        "strong_weak": {"pattern": "UNKNOWN"},
        "volume_warning": {"warning": False},
        "divergence": {"divergence": False},
        "volume_signal": "NEUTRAL",
        "volume_confidence": 0.5,
    }

    if not bars or len(bars) < 10:
        return result

    # 检测各种量价模式
    result["volume_shrink"] = detect_volume_shrink(bars)
    result["strong_weak"] = detect_strong_weak_pattern(bars)
    result["volume_warning"] = detect_volume_warning(bars)
    result["divergence"] = detect_volume_price_divergence(bars)

    # 综合信号判断
    signals = []

    # 强弱模式
    sw = result["strong_weak"]
    if sw["pattern"] == "HEALTHY_UP":
        signals.append(("BULLISH", sw["health_score"]))
    elif sw["pattern"] == "HEALTHY_DOWN":
        signals.append(("BEARISH", sw["health_score"]))

    # 缩量回调
    vs = result["volume_shrink"]
    if vs["detected"]:
        if vs["context"] == "PULLBACK_SHRINK":
            signals.append(("BULLISH", 0.7))  # 缩量回调利好
        elif vs["context"] == "RALLY_SHRINK":
            signals.append(("BEARISH", 0.7))  # 缩量反弹利空

    # 巨量警示
    vw = result["volume_warning"]
    if vw["warning"]:
        if vw["type"] == "HUGE_BULLISH":
            signals.append(("WARNING", 0.8))  # 巨量阳线需警惕
        elif vw["type"] == "HUGE_BEARISH":
            signals.append(("WARNING", 0.8))  # 巨量阴线需警惕

    # 量价背离
    dv = result["divergence"]
    if dv["divergence"]:
        if dv["type"] == "TOP_DIVERGENCE":
            signals.append(("BEARISH", dv["confidence"]))
        elif dv["type"] == "BOTTOM_DIVERGENCE":
            signals.append(("BULLISH", dv["confidence"]))

    # 计算最终信号
    if not signals:
        return result

    bullish_score = sum(s[1] for s in signals if s[0] == "BULLISH")
    bearish_score = sum(s[1] for s in signals if s[0] == "BEARISH")
    warning_score = sum(s[1] for s in signals if s[0] == "WARNING")

    if warning_score > 0.5:
        result["volume_signal"] = "WARNING"
        result["volume_confidence"] = warning_score
    elif bullish_score > bearish_score and bullish_score > 0.5:
        result["volume_signal"] = "BULLISH"
        result["volume_confidence"] = bullish_score / (bullish_score + bearish_score + 0.1)
    elif bearish_score > bullish_score and bearish_score > 0.5:
        result["volume_signal"] = "BEARISH"
        result["volume_confidence"] = bearish_score / (bullish_score + bearish_score + 0.1)

    return result


# ========================================================================
# 测试用例
# ========================================================================

if __name__ == "__main__":
    # 模拟测试数据
    print("=" * 60)
    print("L1 Regime Enhancement v3.170 - 单元测试")
    print("=" * 60)

    # 生成模拟上涨趋势数据
    import random

    def generate_uptrend_bars(n=60):
        bars = []
        price = 100
        for i in range(n):
            change = random.uniform(0.5, 1.5)  # 偏向上涨
            price += change
            bars.append({
                "open": price - change,
                "high": price + random.uniform(0, 0.5),
                "low": price - change - random.uniform(0, 0.5),
                "close": price,
                "volume": random.randint(1000, 5000),
            })
        return bars

    def generate_ranging_bars(n=60):
        bars = []
        price = 100
        for i in range(n):
            change = random.uniform(-1, 1)  # 随机涨跌
            price += change
            price = max(95, min(105, price))  # 限制在区间内
            bars.append({
                "open": price - change,
                "high": price + random.uniform(0, 0.5),
                "low": price - 0.5 - random.uniform(0, 0.5),
                "close": price,
                "volume": random.randint(1000, 5000),
            })
        return bars

    # 测试1: 上涨趋势
    print("\n[TEST 1] 上涨趋势数据:")
    uptrend_bars = generate_uptrend_bars(60)
    result = compute_l1_regime_enhanced(
        ohlcv_bars=uptrend_bars,
        ai_signals={"trend120": "UP"},
        symbol="BTCUSDC",
        pos_ratio=0.3,
    )
    print(f"  Regime: {result['regime']}")
    print(f"  Direction: {result['direction']}")
    print(f"  Confidence: {result['confidence']:.2%}")
    print(f"  Consensus: {result['consensus']}")
    print(f"  L1 Strategy: {result['recommendations']['l1_strategy']}")

    # 测试2: 震荡数据
    print("\n[TEST 2] 震荡数据:")
    ranging_bars = generate_ranging_bars(60)
    result = compute_l1_regime_enhanced(
        ohlcv_bars=ranging_bars,
        ai_signals={"trend120": "RANGE"},
        symbol="ZECUSDC",
        pos_ratio=0.5,
    )
    print(f"  Regime: {result['regime']}")
    print(f"  Direction: {result['direction']}")
    print(f"  Confidence: {result['confidence']:.2%}")
    print(f"  Consensus: {result['consensus']}")
    print(f"  L1 Strategy: {result['recommendations']['l1_strategy']}")

    # 测试3: 多周期斜率
    print("\n[TEST 3] 多周期斜率分析:")
    slope_result = compute_multi_period_slope(uptrend_bars)
    print(f"  10期斜率: {slope_result['slopes'].get(10, 0):.4f}")
    print(f"  30期斜率: {slope_result['slopes'].get(30, 0):.4f}")
    print(f"  60期斜率: {slope_result['slopes'].get(60, 0):.4f}")
    print(f"  加权斜率: {slope_result['weighted_slope']:.4f}")
    print(f"  一致性: {slope_result['consistency']:.2%}")
    print(f"  方向: {slope_result['direction'].value}")

    # 测试4: 趋势结构
    print("\n[TEST 4] 趋势结构分析:")
    structure = analyze_trend_structure(uptrend_bars)
    print(f"  结构: {structure['structure']}")
    print(f"  HH数量: {structure['hh_count']}")
    print(f"  HL数量: {structure['hl_count']}")
    print(f"  置信度: {structure['confidence']:.2%}")

    # 测试5: [v3.170] K线形态检测
    print("\n[TEST 5] K线形态检测 (v3.170):")

    # 生成包含吞没形态的数据
    def generate_engulfing_bars():
        bars = []
        price = 100
        for i in range(8):
            bars.append({
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + 0.3,
                "volume": 1000,
            })
            price += 0.3
        # 添加一根阴线
        bars.append({
            "open": price,
            "high": price + 0.2,
            "low": price - 1.5,
            "close": price - 1.2,
            "volume": 1500,
        })
        # 添加一根看涨吞没阳线
        bars.append({
            "open": price - 1.5,
            "high": price + 0.5,
            "low": price - 1.8,
            "close": price + 0.3,
            "volume": 2000,
        })
        return bars

    engulfing_bars = generate_engulfing_bars()
    kline_result = detect_kline_patterns(engulfing_bars, "crypto")
    print(f"  形态信号: {kline_result['pattern_signal']}")
    print(f"  信号强度: {kline_result['pattern_strength']:.2f}")
    print(f"  吞没检测: {kline_result['engulfing']}")
    print(f"  趋势确认: {kline_result['trend_confirm']}")

    # 测试6: [v3.170] 量价模式检测
    print("\n[TEST 6] 量价模式检测 (v3.170):")

    # 生成健康上涨数据 (阳线放量，阴线缩量)
    def generate_healthy_uptrend_bars():
        bars = []
        price = 100
        for i in range(20):
            if i % 3 == 0:  # 每3根有一根阴线
                bars.append({
                    "open": price,
                    "high": price + 0.3,
                    "low": price - 0.8,
                    "close": price - 0.5,
                    "volume": 500,  # 缩量
                })
                price -= 0.5
            else:
                bars.append({
                    "open": price,
                    "high": price + 1.2,
                    "low": price - 0.2,
                    "close": price + 1.0,
                    "volume": 1500,  # 放量
                })
                price += 1.0
        return bars

    healthy_bars = generate_healthy_uptrend_bars()
    volume_result = detect_volume_patterns(healthy_bars)
    print(f"  量价信号: {volume_result['volume_signal']}")
    print(f"  置信度: {volume_result['volume_confidence']:.2f}")
    print(f"  强弱模式: {volume_result['strong_weak']['pattern']}")
    print(f"  缩量检测: {volume_result['volume_shrink']}")

    # 测试7: 综合Human信号 (包含v3.170增强)
    print("\n[TEST 7] 综合Human信号 (v3.170增强):")
    human_result = compute_human_signals_enhanced(
        ohlcv_bars=healthy_bars,
        pos_ratio=0.3,
        trend_x4="up",
        symbol="BTCUSDC",
    )
    print(f"  Regime投票: {human_result['regime_vote']}")
    print(f"  方向: {human_result['regime_direction']}")
    print(f"  置信度: {human_result['regime_confidence']:.2%}")
    print(f"  K线形态信号: {human_result['kline_patterns'].get('pattern_signal', 'N/A')}")
    print(f"  量价模式信号: {human_result['volume_patterns'].get('volume_signal', 'N/A')}")

    print("\n" + "=" * 60)
    print("v3.170 测试完成!")
    print("=" * 60)

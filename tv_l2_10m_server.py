#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tv_l2_10m_server.py v3.120
10m小周期分析服务 - 增强版

v3.120更新 (2026-01-04):
- 新增短期趋势判断(_compute_short_term_trend)
- 修改_detect_micro_reversal，解决FORCE_HOLD过多问题
- 当没有明确信号时，根据K线趋势给出方向(BUY_OK/SELL_OK)
- 实现L2小周期验证功能

核心功能：
1. 假突破/假跌破检测（只看当前K线+历史20根）
2. 美股暴跌预警（10m快速检测，只对美股生效）
3. 简单的顶部/底部判断
4. 短期趋势判断（v3.120新增）

输出信号给主程序L2使用：
- fake_break_tag: FAKE_BREAKOUT（可卖） / FAKE_BREAKDOWN（可买）
- micro_reversal_10m: MICRO_TOP（顶部） / MICRO_BOTTOM（底部）
- crash_alert_10m: 美股暴跌预警（WARN/CRASH/PANIC）
- short_term_trend: UP / DOWN / SIDE（v3.120新增）
"""

import json
import os
from typing import Any, Dict, List, Optional

try:
    from flask import Flask, request, jsonify
except Exception:
    Flask = None
    request = None
    jsonify = None


STATE_PATH_DEFAULT = os.environ.get("L2_10M_STATE_PATH", "l2_10m_state.json")

# ===== 10m分析配置 =====
CONFIG_10M = {
    # 假突破/假跌破检测
    "fake_break": {
        "lookback_bars": 20,          # 回溯窗口
        "breakout_threshold": 1.003,  # 突破阈值：前高的0.3%
        "breakdown_threshold": 0.997, # 跌破阈值：前低的0.3%
        "pullback_ratio": 0.5,        # 回撤比例：至少回撤突破幅度的50%
        "volume_spike_min": 1.2,      # 放量确认：至少1.2倍
    },
    
    # 美股暴跌预警（只对美股生效）
    "crash_us_stock": {
        "enabled": True,
        "lookback_bars": 3,           # 看最近3根10m K线
        "warn_threshold": -0.015,     # WARN: 10m累计跌幅 -1.5%
        "crash_threshold": -0.03,     # CRASH: 10m累计跌幅 -3.0%
        "panic_threshold": -0.05,     # PANIC: 10m累计跌幅 -5.0%
        "atr_multiplier": 2.5,        # ATR异常倍数
        "volume_spike_min": 1.5,      # 成交量异常倍数
    },
    
    # 顶部/底部判断
    "reversal": {
        "extreme_high_ratio": 0.85,   # 价格在区间85%以上算极高位
        "extreme_low_ratio": 0.15,    # 价格在区间15%以下算极低位
        "volume_climax_ratio": 1.8,   # 成交量1.8倍算放量
    },
}


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def _safe_mean(values: List[float]) -> float:
    """安全计算均值"""
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _compute_atr_simple(closes: List[float], window: int = 10) -> float:
    """简化版ATR计算（使用收盘价范围近似）"""
    if len(closes) < window + 1:
        return 0.0
    
    ranges = []
    for i in range(len(closes) - window, len(closes)):
        if i > 0:
            high = max(closes[i], closes[i-1])
            low = min(closes[i], closes[i-1])
            ranges.append(high - low)
    
    return _safe_mean(ranges) if ranges else 0.0


def _volume_state(vols: List[float]) -> str:
    """判断成交量状态
    
    Returns:
        CLIMAX: 极度放量（2倍以上）
        RISING: 温和放量（1.2-2倍）
        FALLING: 缩量（0.5倍以下）
        NORMAL: 正常
    """
    vols = [float(v) for v in vols if v is not None]
    if len(vols) < 3:
        return "UNKNOWN"

    if len(vols) <= 5:
        recent_mean = _safe_mean(vols)
        base_mean = recent_mean
    else:
        recent = vols[-5:]
        history = vols[:-5]
        recent_mean = _safe_mean(recent)
        base_mean = _safe_mean(history) or recent_mean

    if base_mean <= 0:
        return "UNKNOWN"

    ratio = recent_mean / base_mean
    if ratio >= 2.0:
        return "CLIMAX"
    if ratio >= 1.2:
        return "RISING"
    if ratio <= 0.5:
        return "FALLING"
    return "NORMAL"


# v3.120: 短期趋势判断函数
def _compute_short_term_trend(closes: List[float], lookback: int = 5) -> str:
    """计算短期趋势方向

    v3.120新增：用于10m小周期验证

    看最近N根K线的整体方向：
    - 收盘价连续上涨 → UP
    - 收盘价连续下跌 → DOWN
    - 震荡无方向 → SIDE

    Args:
        closes: 收盘价数组（旧→新）
        lookback: 回溯K线数量，默认5根

    Returns:
        "UP" / "DOWN" / "SIDE" / "UNKNOWN"
    """
    if not closes or len(closes) < lookback:
        return "UNKNOWN"

    recent = closes[-lookback:]  # 最近N根

    # 计算涨跌幅
    if recent[0] <= 0:
        return "UNKNOWN"
    change_pct = (recent[-1] - recent[0]) / recent[0]

    # 计算方向一致性（连续上涨或下跌的比例）
    up_count = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
    down_count = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])

    # 判断趋势（要求涨跌幅>0.5% 且 至少3/4根同向）
    min_bars = max(2, lookback - 2)  # 至少需要的同向K线数

    if change_pct > 0.005 and up_count >= min_bars:
        return "UP"
    elif change_pct < -0.005 and down_count >= min_bars:
        return "DOWN"
    else:
        return "SIDE"


def _pos_zone_from_range(last_close: float, lows: List[float], highs: List[float]) -> Dict[str, Any]:
    """计算价格在20根K线区间中的相对位置
    
    Returns:
        {
            "pos_ratio": 0.0-1.0,
            "pos_zone": "EXTREME_LOW" / "LOW" / "MID" / "HIGH" / "EXTREME_HIGH"
        }
    """
    lows = [float(x) for x in lows if x is not None]
    highs = [float(x) for x in highs if x is not None]

    if not lows or not highs:
        return {"pos_ratio": 0.5, "pos_zone": "MID"}

    window_low = min(lows)
    window_high = max(highs)
    if window_high <= window_low:
        return {"pos_ratio": 0.5, "pos_zone": "MID"}

    last_close = float(last_close)
    pos_ratio = (last_close - window_low) / (window_high - window_low)
    pos_ratio = max(0.0, min(1.0, pos_ratio))

    # 分区阈值
    if pos_ratio <= 0.15:
        zone = "EXTREME_LOW"
    elif pos_ratio <= 0.35:
        zone = "LOW"
    elif pos_ratio <= 0.65:
        zone = "MID"
    elif pos_ratio <= 0.85:
        zone = "HIGH"
    else:
        zone = "EXTREME_HIGH"

    return {"pos_ratio": pos_ratio, "pos_zone": zone}


# ----------------------------------------------------------------------
# 核心功能1: 假突破/假跌破检测（增强版）
# ----------------------------------------------------------------------
def _detect_fake_break_pattern(
    closes: List[float], 
    highs: List[float], 
    lows: List[float],
    volumes: List[float],
) -> Dict[str, Any]:
    """检测假突破/假跌破模式
    
    逻辑：
    1. 找到前19根K线的最高点/最低点
    2. 检查最后1根K线是否突破/跌破
    3. 检查是否快速回撤（假突破/假跌破）
    4. 检查是否有成交量确认
    
    Returns:
        {
            "tag": "FAKE_BREAKOUT" / "FAKE_BREAKDOWN" / "NONE",
            "signal": "CAN_SELL" / "CAN_BUY" / "NONE",
            "confidence": "HIGH" / "MEDIUM" / "LOW",
            "details": {...}
        }
    """
    config = CONFIG_10M["fake_break"]
    
    n = min(len(closes), len(highs), len(lows))
    if n < 3:
        return {
            "tag": "NONE",
            "signal": "NONE",
            "confidence": "LOW",
            "details": {"reason": "insufficient_data"}
        }

    # 转换为float
    closes = [float(c) for c in closes[-n:]]
    highs = [float(h) for h in highs[-n:]]
    lows = [float(l) for l in lows[-n:]]
    volumes = [float(v) for v in volumes[-n:]] if volumes and len(volumes) >= n else []

    # 前19根的极值
    prev_closes = closes[:-1]
    prev_highs = highs[:-1]
    prev_lows = lows[:-1]
    
    prev_high = max(prev_highs)
    prev_low = min(prev_lows)
    
    # 最后1根K线
    last_close = closes[-1]
    last_high = highs[-1]
    last_low = lows[-1]
    last_open = closes[-2]  # 简化：用上一根收盘作为当前开盘
    
    # 计算成交量状态
    volume_spike = 1.0
    if volumes and len(volumes) >= 10:
        recent_vol = volumes[-1]
        avg_vol = _safe_mean(volumes[-10:-1])
        if avg_vol > 0:
            volume_spike = recent_vol / avg_vol
    
    result = {
        "tag": "NONE",
        "signal": "NONE",
        "confidence": "LOW",
        "details": {
            "prev_high": prev_high,
            "prev_low": prev_low,
            "last_close": last_close,
            "last_high": last_high,
            "last_low": last_low,
            "volume_spike": volume_spike,
        }
    }
    
    # ===== 检测假突破 =====
    # 条件1: 高点突破前高
    if last_high > prev_high * config["breakout_threshold"]:
        # 条件2: 收盘价回撤到突破点以下
        breakout_extent = last_high - prev_high
        pullback_extent = last_high - last_close
        
        if last_close < prev_high and pullback_extent >= breakout_extent * config["pullback_ratio"]:
            # 条件3: 有成交量确认（放量失败）
            confidence = "LOW"
            if volume_spike >= config["volume_spike_min"]:
                confidence = "MEDIUM"
                if volume_spike >= 1.8:
                    confidence = "HIGH"
            
            result["tag"] = "FAKE_BREAKOUT"
            result["signal"] = "CAN_SELL"
            result["confidence"] = confidence
            result["details"]["breakout_extent"] = breakout_extent
            result["details"]["pullback_extent"] = pullback_extent
            result["details"]["reason"] = f"突破{prev_high:.2f}后回落至{last_close:.2f}"
            
            return result
    
    # ===== 检测假跌破 =====
    # 条件1: 低点跌破前低
    if last_low < prev_low * config["breakdown_threshold"]:
        # 条件2: 收盘价反弹到跌破点以上
        breakdown_extent = prev_low - last_low
        bounce_extent = last_close - last_low
        
        if last_close > prev_low and bounce_extent >= breakdown_extent * config["pullback_ratio"]:
            # 条件3: 有成交量确认（放量反转）
            confidence = "LOW"
            if volume_spike >= config["volume_spike_min"]:
                confidence = "MEDIUM"
                if volume_spike >= 1.8:
                    confidence = "HIGH"
            
            result["tag"] = "FAKE_BREAKDOWN"
            result["signal"] = "CAN_BUY"
            result["confidence"] = confidence
            result["details"]["breakdown_extent"] = breakdown_extent
            result["details"]["bounce_extent"] = bounce_extent
            result["details"]["reason"] = f"跌破{prev_low:.2f}后反弹至{last_close:.2f}"
            
            return result
    
    return result


# ----------------------------------------------------------------------
# 核心功能2: 美股暴跌预警（新增）
# ----------------------------------------------------------------------
def _detect_crash_alert_us_stock(
    symbol: str,
    closes: List[float],
    volumes: List[float],
    is_us_stock: bool = True,
) -> Dict[str, Any]:
    """检测美股10m级别暴跌预警
    
    只对美股生效，crypto不触发
    
    Returns:
        {
            "crash_level": "NONE" / "WARN" / "CRASH" / "PANIC",
            "crash_reason": str,
            "crash_metrics": {
                "ret_1bar": float,
                "ret_3bar": float,
                "atr_ratio": float,
                "volume_spike": float,
            }
        }
    """
    config = CONFIG_10M["crash_us_stock"]
    
    # 非美股或功能关闭，直接返回
    if not config["enabled"] or not is_us_stock:
        return {
            "crash_level": "NONE",
            "crash_reason": "not_us_stock_or_disabled",
            "crash_metrics": {},
        }
    
    if len(closes) < 4:
        return {
            "crash_level": "NONE",
            "crash_reason": "insufficient_data",
            "crash_metrics": {},
        }
    
    closes = [float(c) for c in closes]
    volumes = [float(v) for v in volumes] if volumes else []
    
    # 计算跌幅指标
    # 最近1根K线跌幅
    ret_1bar = (closes[-1] - closes[-2]) / max(closes[-2], 1e-8)
    
    # 最近3根K线累计跌幅
    lookback = min(config["lookback_bars"], len(closes) - 1)
    ret_Nbar = (closes[-1] - closes[-(lookback+1)]) / max(closes[-(lookback+1)], 1e-8)
    
    # ATR异常比率
    atr = _compute_atr_simple(closes, window=10)
    atr_ratio = abs(ret_1bar) / atr if atr > 0 else 0.0
    
    # 成交量异常
    volume_spike = 1.0
    if volumes and len(volumes) >= 10:
        recent_vol = volumes[-1]
        avg_vol = _safe_mean(volumes[-10:-1])
        if avg_vol > 0:
            volume_spike = recent_vol / avg_vol
    
    crash_metrics = {
        "ret_1bar": ret_1bar,
        "ret_3bar": ret_Nbar,
        "atr_ratio": atr_ratio,
        "volume_spike": volume_spike,
    }
    
    # 判定crash_level
    crash_level = "NONE"
    reason_parts = []
    
    # PANIC级别（10m累计跌幅很大）
    if ret_Nbar < config["panic_threshold"]:
        crash_level = "PANIC"
        reason_parts.append(f"10m累计跌幅{ret_Nbar:.1%}")
        if atr_ratio > config["atr_multiplier"]:
            reason_parts.append(f"ATR异常{atr_ratio:.1f}x")
        if volume_spike > config["volume_spike_min"]:
            reason_parts.append(f"放量{volume_spike:.1f}x")
    
    # CRASH级别
    elif ret_Nbar < config["crash_threshold"]:
        crash_level = "CRASH"
        reason_parts.append(f"10m累计跌幅{ret_Nbar:.1%}")
        if atr_ratio > config["atr_multiplier"]:
            reason_parts.append(f"ATR异常{atr_ratio:.1f}x")
    
    # WARN级别
    elif ret_Nbar < config["warn_threshold"]:
        crash_level = "WARN"
        reason_parts.append(f"10m累计跌幅{ret_Nbar:.1%}")
    
    crash_reason = f"{crash_level}: " + ", ".join(reason_parts) if reason_parts else "normal"
    
    return {
        "crash_level": crash_level,
        "crash_reason": crash_reason,
        "crash_metrics": crash_metrics,
    }


# ----------------------------------------------------------------------
# 核心功能3: 顶部/底部判断（简化版）
# ----------------------------------------------------------------------
def _detect_micro_reversal(
    pos_zone: str,
    pos_ratio: float,
    volume_state: str,
    fake_break_result: Dict[str, Any],
    pa_buy_edge: bool,
    pa_sell_edge: bool,
    closes: List[float] = None,  # v3.120新增：用于短期趋势判断
) -> Dict[str, str]:
    """判断10m级别的微观反转信号

    v3.120更新：增加短期趋势判断，解决FORCE_HOLD过多问题

    Returns:
        {
            "micro_reversal_10m": "MICRO_TOP" / "MICRO_BOTTOM" / "NONE",
            "exec_bias_10m": "STRONG_BUY" / "STRONG_SELL" / "BUY_OK" / "SELL_OK" / "FORCE_HOLD",
            "short_term_trend": "UP" / "DOWN" / "SIDE" / "UNKNOWN"  # v3.120新增
        }
    """
    config = CONFIG_10M["reversal"]

    micro_reversal = "NONE"
    exec_bias = "FORCE_HOLD"

    # v3.120: 计算短期趋势
    short_trend = _compute_short_term_trend(closes or [])

    fake_tag = fake_break_result.get("tag", "NONE")
    fake_confidence = fake_break_result.get("confidence", "LOW")

    # ===== MICRO_BOTTOM（底部反转） =====
    # 条件1: 价格在极低位
    if pos_zone in {"EXTREME_LOW", "LOW"}:
        # 条件2: 假跌破（高置信度）或 PA买入信号
        if (fake_tag == "FAKE_BREAKDOWN" and fake_confidence in {"HIGH", "MEDIUM"}) or pa_buy_edge:
            # 条件3: 成交量放量确认
            if volume_state in {"RISING", "CLIMAX"}:
                micro_reversal = "MICRO_BOTTOM"
                exec_bias = "STRONG_BUY"
            else:
                # 成交量不足，降级为BUY_OK
                exec_bias = "BUY_OK"

    # ===== MICRO_TOP（顶部反转） =====
    # 条件1: 价格在极高位
    if pos_zone in {"EXTREME_HIGH", "HIGH"}:
        # 条件2: 假突破（高置信度）或 PA卖出信号
        if (fake_tag == "FAKE_BREAKOUT" and fake_confidence in {"HIGH", "MEDIUM"}) or pa_sell_edge:
            # 条件3: 成交量放量确认
            if volume_state in {"RISING", "CLIMAX"}:
                micro_reversal = "MICRO_TOP"
                exec_bias = "STRONG_SELL"
            else:
                # 成交量不足，降级为SELL_OK
                exec_bias = "SELL_OK"

    # ===== 非极端位置处理（v3.120增强） =====
    if micro_reversal == "NONE":
        if fake_tag == "FAKE_BREAKDOWN" and pos_zone in {"LOW"}:
            exec_bias = "BUY_OK"
        elif fake_tag == "FAKE_BREAKOUT" and pos_zone in {"HIGH"}:
            exec_bias = "SELL_OK"
        elif pa_buy_edge and pos_zone in {"LOW", "EXTREME_LOW"}:
            exec_bias = "BUY_OK"
        elif pa_sell_edge and pos_zone in {"HIGH", "EXTREME_HIGH"}:
            exec_bias = "SELL_OK"
        # ===== v3.120新增：短期趋势判断 =====
        elif short_trend == "UP":
            exec_bias = "BUY_OK"
        elif short_trend == "DOWN":
            exec_bias = "SELL_OK"
        else:
            exec_bias = "FORCE_HOLD"

    return {
        "micro_reversal_10m": micro_reversal,
        "exec_bias_10m": exec_bias,
        "short_term_trend": short_trend,  # v3.120新增
    }


# ----------------------------------------------------------------------
# 主分析函数：整合所有功能
# ----------------------------------------------------------------------
def analyze_l2_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """10m快照分析主函数
    
    Args:
        payload: TradingView webhook数据
    
    Returns:
        完整的10m分析结果，包含：
        - 假突破/假跌破信号
        - 美股暴跌预警
        - 顶部/底部判断
    """
    symbol = str(payload.get("symbol", "UNKNOWN"))
    timeframe = str(payload.get("timeframe", "10"))
    last_close = float(payload.get("last_close") or payload.get("close") or 0.0)

    # 判断是否为美股（简单规则：不含"USDT"/"BUSD"等关键词）
    is_us_stock = not any(x in symbol.upper() for x in ["USDT", "BUSD", "BTC", "ETH", "CRYPTO"])

    # 兼容不同字段名
    highs = payload.get("highs") or []
    lows = payload.get("lows") or []
    closes = payload.get("close_prices") or payload.get("closes") or []
    vols = payload.get("volumes") or payload.get("volume") or []

    # TradingView 一般是"最新在前"，翻转为"旧→新"
    if highs:
        highs = list(reversed(highs))
    if lows:
        lows = list(reversed(lows))
    if closes:
        closes = list(reversed(closes))
    if vols:
        vols = list(reversed(vols))

    # 只取最近20根（节省计算）
    lookback = CONFIG_10M["fake_break"]["lookback_bars"]
    if closes and len(closes) > lookback:
        closes = closes[-lookback:]
        highs = highs[-lookback:] if highs else []
        lows = lows[-lookback:] if lows else []
        vols = vols[-lookback:] if vols else []

    # ===== 1. 计算基础指标 =====
    vol_state = _volume_state(vols) if vols else "UNKNOWN"
    pos_info = _pos_zone_from_range(
        last_close, lows or [last_close], highs or [last_close]
    )
    pos_ratio = pos_info["pos_ratio"]
    pos_zone = pos_info["pos_zone"]

    # ===== 2. 假突破/假跌破检测 =====
    fake_break_result = _detect_fake_break_pattern(closes, highs, lows, vols)

    # ===== 3. 美股暴跌预警 =====
    crash_alert = _detect_crash_alert_us_stock(symbol, closes, vols, is_us_stock)

    # ===== 4. 读取PA信号（来自TradingView） =====
    signal = str(payload.get("signal", "none") or "none").lower()
    level = str(payload.get("level", "none") or "none").lower()
    pa_buy_edge = bool(payload.get("pa_buy_edge"))
    pa_sell_edge = bool(payload.get("pa_sell_edge"))

    # ===== 5. 顶部/底部判断（v3.120增强：传入closes用于趋势判断） =====
    reversal_result = _detect_micro_reversal(
        pos_zone, pos_ratio, vol_state, fake_break_result, pa_buy_edge, pa_sell_edge,
        closes=closes  # v3.120: 传入closes用于短期趋势判断
    )

    # ===== 6. 组装返回结果 =====
    result: Dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "last_close": last_close,
        "is_us_stock": is_us_stock,
        
        # 基础指标
        "volume_state_10m": vol_state,
        "pos_zone_10m": pos_zone,
        "pos_ratio_10m": pos_ratio,
        
        # 假突破/假跌破信号
        "fake_break_tag": fake_break_result["tag"],
        "fake_break_signal": fake_break_result["signal"],
        "fake_break_confidence": fake_break_result["confidence"],
        "fake_break_details": fake_break_result["details"],
        
        # 顶部/底部判断
        "micro_reversal_10m": reversal_result["micro_reversal_10m"],
        "exec_bias_10m": reversal_result["exec_bias_10m"],
        "short_term_trend": reversal_result.get("short_term_trend", "UNKNOWN"),  # v3.120新增

        # 美股暴跌预警
        "crash_alert_10m": {
            "crash_level": crash_alert["crash_level"],
            "crash_reason": crash_alert["crash_reason"],
            "crash_metrics": crash_alert["crash_metrics"],
        },
    }

    # 保留原始PA信号（调试用）
    result["raw_signal_10m"] = {
        "signal": signal,
        "level": level,
        "pa_buy_edge": pa_buy_edge,
        "pa_sell_edge": pa_sell_edge,
        "n_bars": len(closes),
    }

    return result


# ----------------------------------------------------------------------
# 状态文件读写
# ----------------------------------------------------------------------
def _load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(path: str, state: Dict[str, Any]) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def update_state_file(payload: Dict[str, Any], state_path: Optional[str] = None) -> Dict[str, Any]:
    """更新 l2_10m_state.json 中某个 symbol 的快照，并返回最新结果"""
    if state_path is None:
        state_path = STATE_PATH_DEFAULT

    snapshot = analyze_l2_snapshot(payload)
    symbol = snapshot.get("symbol", "UNKNOWN")

    state = _load_state(state_path)
    snapshot["updated_at_ms"] = int(payload.get("time_ms") or 0)
    state[symbol] = snapshot
    _save_state(state_path, snapshot)
    return snapshot


# ----------------------------------------------------------------------
# Flask 服务封装
# ----------------------------------------------------------------------
def create_app(state_path: Optional[str] = None):
    if Flask is None:
        raise RuntimeError("Flask 未安装，无法以服务模式运行。")

    app = Flask(__name__)

    @app.route("/tv_l2_10m", methods=["POST"])
    def handle_tv_l2_10m():
        data = request.get_json(force=True, silent=True) or {}
        snapshot = update_state_file(data, state_path=state_path)
        return jsonify({"ok": True, "snapshot": snapshot})

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify(
            {
                "ok": True,
                "component": "tv_l2_10m_server",
                "version": "2.1-enhanced",
                "state_path": state_path or STATE_PATH_DEFAULT,
            }
        )

    return app


if __name__ == "__main__":
    # 独立服务模式
    if Flask is None:
        print(
            "Flask 未安装，本文件只能作为工具模块使用。\n"
            "请先 `pip install flask` 后再以服务方式运行。"
        )
    else:
        app = create_app()
        port = int(os.environ.get("L2_10M_PORT", "5000"))
        print(f"[tv_l2_10m_server] v2.1 Listening on http://0.0.0.0:{port}/tv_l2_10m")
        app.run(host="0.0.0.0", port=port, debug=False)
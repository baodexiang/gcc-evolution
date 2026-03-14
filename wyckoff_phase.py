"""
wyckoff_phase.py  —  B通道: 数学驱动的Wyckoff Phase检测
GCC-0261 S4: 与A通道(Vision LLM)组成双通道门控

输入: OHLCV bars (list[dict], 需50+根)
输出: {"phase": "A-E/X", "structure": "ACCUMULATION/DISTRIBUTION/MARKUP/MARKDOWN/UNKNOWN",
        "confidence": 0.0-1.0, "details": {...}}

Phase判断逻辑:
  1. 检测是否处于交易区间 (support/resistance水平线)
  2. Phase A: 前趋势停止 — 极端放量+价格急反转(Selling/Buying Climax)
  3. Phase B: 区间内震荡 — 多次测试支撑阻力, 无突破
  4. Phase C: Spring/Upthrust — 低量假突破支撑/阻力后快速回收
  5. Phase D: 突破确认 — 放量突破区间, 方向明确
  6. Phase E: 趋势执行 — 持续趋势, 回调浅
"""

import statistics
from typing import Dict, List, Optional, Tuple


# ─── 参数 ───
MIN_BARS = 30                  # 最少需要的K线数
RANGE_LOOKBACK = 40            # 检测区间用的回看窗口
VOLUME_CLIMAX_MULT = 2.0       # 量 > 均量*mult = 放量高潮
VOLUME_LOW_MULT = 0.7          # 量 < 均量*mult = 缩量
SPRING_PIERCE_ATR = 0.3        # Spring穿透深度 < ATR*mult
BREAKOUT_ATR_MULT = 0.5        # 突破距离 > ATR*mult
TREND_PULLBACK_RATIO = 0.38    # Phase E回调幅度 < 前腿*ratio


def _extract_arrays(bars: List[dict]) -> Tuple[list, list, list, list, list]:
    """从bars提取 highs, lows, closes, opens, volumes 数组。"""
    highs, lows, closes, opens, volumes = [], [], [], [], []
    for b in bars:
        highs.append(float(b.get("high") or b.get("h") or 0))
        lows.append(float(b.get("low") or b.get("l") or 0))
        closes.append(float(b.get("close") or b.get("c") or 0))
        opens.append(float(b.get("open") or b.get("o") or 0))
        volumes.append(float(b.get("volume") or b.get("v") or 0))
    return highs, lows, closes, opens, volumes


def _calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """简易ATR计算。"""
    if len(highs) < 2:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if not trs:
        return 0.0
    # EMA-style ATR
    atr = sum(trs[:period]) / min(period, len(trs))
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _detect_range(highs: list, lows: list, closes: list, atr: float,
                  lookback: int = RANGE_LOOKBACK) -> Optional[Dict]:
    """检测最近N根K线是否形成交易区间。
    返回 {"support", "resistance", "width", "in_range": True} 或 None。
    """
    n = min(lookback, len(highs))
    if n < 10 or atr <= 0:
        return None

    recent_highs = highs[-n:]
    recent_lows = lows[-n:]
    recent_closes = closes[-n:]

    resistance = max(recent_highs)
    support = min(recent_lows)
    width = resistance - support

    # 区间太窄(< 1 ATR) 或太宽(> 6 ATR) 都不算有效区间
    if width < atr or width > atr * 6:
        return None

    # 价格大部分时间在区间中部 — 检查收盘价分布
    mid = (support + resistance) / 2
    quarter = width / 4
    in_middle = sum(1 for c in recent_closes if support + quarter < c < resistance - quarter)
    middle_ratio = in_middle / n

    # 至少30%的K线收在中间50%区域才算震荡区间
    if middle_ratio < 0.3:
        return None

    # 检查是否有多次触碰支撑/阻力 (至少2次各)
    touch_zone = atr * 0.3
    support_touches = sum(1 for l in recent_lows if l <= support + touch_zone)
    resistance_touches = sum(1 for h in recent_highs if h >= resistance - touch_zone)

    if support_touches < 2 or resistance_touches < 2:
        return None

    return {
        "support": support,
        "resistance": resistance,
        "width": width,
        "middle_ratio": middle_ratio,
        "support_touches": support_touches,
        "resistance_touches": resistance_touches,
        "in_range": True,
    }


def _detect_climax(highs: list, lows: list, closes: list, opens: list,
                   volumes: list, atr: float) -> Optional[Dict]:
    """检测Phase A: 前趋势停止的高潮事件。
    Selling Climax: 最近10根内有极端放量+大阴线, 随后反弹
    Buying Climax: 最近10根内有极端放量+大阳线, 随后回落
    """
    if len(volumes) < 10:
        return None

    avg_vol = statistics.mean(volumes[-20:]) if len(volumes) >= 20 else statistics.mean(volumes)
    if avg_vol <= 0:
        return None

    # 检查最近10根K线中是否有高潮事件
    for i in range(max(len(closes) - 10, 1), len(closes) - 1):
        vol_ratio = volumes[i] / avg_vol
        body = closes[i] - opens[i]
        body_size = abs(body)

        if vol_ratio < VOLUME_CLIMAX_MULT or body_size < atr * 0.5:
            continue

        # Selling Climax: 大阴线(body < 0) + 极端量 + 之后反弹
        if body < 0 and i + 1 < len(closes):
            # 后续K线反弹(收盘高于高潮K线收盘)
            if closes[i + 1] > closes[i]:
                return {"type": "SELLING_CLIMAX", "bar_index": i,
                        "volume_ratio": vol_ratio, "structure_hint": "ACCUMULATION"}

        # Buying Climax: 大阳线(body > 0) + 极端量 + 之后回落
        if body > 0 and i + 1 < len(closes):
            if closes[i + 1] < closes[i]:
                return {"type": "BUYING_CLIMAX", "bar_index": i,
                        "volume_ratio": vol_ratio, "structure_hint": "DISTRIBUTION"}

    return None


def _detect_spring(highs: list, lows: list, closes: list, volumes: list,
                   tr: dict, atr: float) -> Optional[Dict]:
    """检测Phase C: Spring(假跌破支撑) 或 Upthrust(假突破阻力)。
    条件: 价格穿透支撑/阻力 → 缩量 → 快速回收到区间内。
    """
    if not tr or len(closes) < 5:
        return None

    support = tr["support"]
    resistance = tr["resistance"]
    avg_vol = statistics.mean(volumes[-20:]) if len(volumes) >= 20 else statistics.mean(volumes)
    if avg_vol <= 0:
        return None

    # 检查最近5根K线
    for i in range(max(len(closes) - 5, 0), len(closes)):
        # Spring: 低点穿破支撑, 但收盘回到支撑上方
        if lows[i] < support - atr * 0.05:
            pierce_depth = support - lows[i]
            if pierce_depth < atr * SPRING_PIERCE_ATR:
                vol_ratio = volumes[i] / avg_vol
                # 缩量穿透 + 收盘回收
                if vol_ratio < VOLUME_LOW_MULT and closes[i] > support:
                    return {"type": "SPRING", "bar_index": i,
                            "pierce_depth": pierce_depth,
                            "volume_ratio": vol_ratio,
                            "structure_hint": "ACCUMULATION"}
                # 或者: 穿透后下一根强力回收
                if i + 1 < len(closes) and closes[i + 1] > support + atr * 0.2:
                    if vol_ratio < 1.2:  # 穿透时量不大
                        return {"type": "SPRING", "bar_index": i,
                                "pierce_depth": pierce_depth,
                                "volume_ratio": vol_ratio,
                                "structure_hint": "ACCUMULATION"}

        # Upthrust: 高点突破阻力, 但收盘回到阻力下方
        if highs[i] > resistance + atr * 0.05:
            pierce_depth = highs[i] - resistance
            if pierce_depth < atr * SPRING_PIERCE_ATR:
                vol_ratio = volumes[i] / avg_vol
                if vol_ratio < VOLUME_LOW_MULT and closes[i] < resistance:
                    return {"type": "UPTHRUST", "bar_index": i,
                            "pierce_depth": pierce_depth,
                            "volume_ratio": vol_ratio,
                            "structure_hint": "DISTRIBUTION"}
                if i + 1 < len(closes) and closes[i + 1] < resistance - atr * 0.2:
                    if vol_ratio < 1.2:
                        return {"type": "UPTHRUST", "bar_index": i,
                                "pierce_depth": pierce_depth,
                                "volume_ratio": vol_ratio,
                                "structure_hint": "DISTRIBUTION"}

    return None


def _detect_breakout(closes: list, volumes: list, tr: dict, atr: float) -> Optional[Dict]:
    """检测Phase D: 放量突破区间。
    条件: 最近3根收盘明确在区间外 + 量比 > 1。
    """
    if not tr or len(closes) < 3:
        return None

    support = tr["support"]
    resistance = tr["resistance"]
    avg_vol = statistics.mean(volumes[-20:]) if len(volumes) >= 20 else statistics.mean(volumes)
    if avg_vol <= 0:
        return None

    # 最近3根全在阻力上方 = 向上突破
    recent_closes = closes[-3:]
    recent_vols = volumes[-3:]
    threshold = atr * BREAKOUT_ATR_MULT

    if all(c > resistance + threshold for c in recent_closes):
        avg_recent_vol = statistics.mean(recent_vols)
        if avg_recent_vol > avg_vol:
            return {"type": "BREAKOUT_UP", "structure_hint": "ACCUMULATION",
                    "volume_ratio": avg_recent_vol / avg_vol}

    if all(c < support - threshold for c in recent_closes):
        avg_recent_vol = statistics.mean(recent_vols)
        if avg_recent_vol > avg_vol:
            return {"type": "BREAKOUT_DOWN", "structure_hint": "DISTRIBUTION",
                    "volume_ratio": avg_recent_vol / avg_vol}

    return None


def _detect_trend(highs: list, lows: list, closes: list, lookback: int = 15) -> Optional[Dict]:
    """检测Phase E: 持续趋势（回调浅, 方向一致）。
    检查最近N根是否有HH/HL(上升) 或 LH/LL(下降) 序列。
    """
    n = min(lookback, len(closes))
    if n < 8:
        return None

    recent_closes = closes[-n:]
    recent_highs = highs[-n:]
    recent_lows = lows[-n:]

    # 简单线性回归斜率判断趋势强度
    x_mean = (n - 1) / 2
    y_mean = statistics.mean(recent_closes)
    numerator = sum((i - x_mean) * (recent_closes[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return None
    slope = numerator / denominator

    # 斜率归一化 (相对价格)
    if y_mean <= 0:
        return None
    norm_slope = slope / y_mean * n  # N根的总变化率

    # 上升趋势: 正斜率 + 检查回调深度
    if norm_slope > 0.02:
        # 最高点到最近收盘的回撤
        peak = max(recent_highs)
        trough = min(recent_lows[-5:])  # 最近5根的最低
        leg = peak - min(recent_lows[:n // 2])  # 前半段起点到峰值
        pullback = peak - trough
        if leg > 0 and pullback / leg < TREND_PULLBACK_RATIO:
            return {"type": "UPTREND", "slope": norm_slope,
                    "pullback_ratio": pullback / leg,
                    "structure_hint": "MARKUP"}

    if norm_slope < -0.02:
        trough = min(recent_lows)
        peak = max(recent_highs[-5:])
        leg = max(recent_highs[:n // 2]) - trough
        pullback = peak - trough
        if leg > 0 and pullback / leg < TREND_PULLBACK_RATIO:
            return {"type": "DOWNTREND", "slope": norm_slope,
                    "pullback_ratio": pullback / leg,
                    "structure_hint": "MARKDOWN"}

    return None


# ─── 主入口 ───

def detect_phase(bars: List[dict]) -> Dict:
    """B通道Wyckoff Phase检测。

    Args:
        bars: OHLCV数据 list[dict], 需50+根, 越多越好

    Returns:
        {"phase": "A-E/X", "structure": str, "confidence": float, "details": dict}
    """
    if not bars or len(bars) < MIN_BARS:
        return {"phase": "X", "structure": "UNKNOWN", "confidence": 0.0,
                "details": {"reason": f"insufficient bars ({len(bars) if bars else 0} < {MIN_BARS})"}}

    highs, lows, closes, opens, volumes = _extract_arrays(bars)
    atr = _calc_atr(highs, lows, closes)
    if atr <= 0:
        return {"phase": "X", "structure": "UNKNOWN", "confidence": 0.0,
                "details": {"reason": "ATR=0, invalid data"}}

    # Step 1: 检测交易区间
    tr = _detect_range(highs, lows, closes, atr)

    # Step 2: 检测持续趋势 (Phase E) — 不在区间中
    trend = _detect_trend(highs, lows, closes)
    if trend and not tr:
        structure = trend["structure_hint"]
        return {"phase": "E", "structure": structure, "confidence": 0.7,
                "details": {"trend": trend, "reason": "sustained trend, no range"}}

    # Step 3: 没有区间也没有趋势 → 无法判断
    if not tr:
        # 尝试检测高潮事件(Phase A可能刚开始, 还没形成区间)
        climax = _detect_climax(highs, lows, closes, opens, volumes, atr)
        if climax:
            structure = climax["structure_hint"]
            return {"phase": "A", "structure": structure, "confidence": 0.55,
                    "details": {"climax": climax, "reason": "climax detected, range not yet formed"}}
        return {"phase": "X", "structure": "UNKNOWN", "confidence": 0.0,
                "details": {"reason": "no range, no trend, no climax"}}

    # 有区间 → 判断区间内的Phase

    # Step 4: 检测突破 (Phase D)
    breakout = _detect_breakout(closes, volumes, tr, atr)
    if breakout:
        structure = breakout["structure_hint"]
        return {"phase": "D", "structure": structure, "confidence": 0.7,
                "details": {"breakout": breakout, "range": tr,
                            "reason": "range breakout confirmed"}}

    # Step 5: 检测Spring/Upthrust (Phase C)
    spring = _detect_spring(highs, lows, closes, volumes, tr, atr)
    if spring:
        structure = spring["structure_hint"]
        return {"phase": "C", "structure": structure, "confidence": 0.65,
                "details": {"spring": spring, "range": tr,
                            "reason": f"{spring['type']} detected"}}

    # Step 6: 检测高潮 (Phase A) — 区间刚形成
    climax = _detect_climax(highs, lows, closes, opens, volumes, atr)
    if climax:
        # 区间已形成但高潮还在近期 → 可能是A→B过渡
        bar_age = len(closes) - 1 - climax["bar_index"]
        if bar_age <= 5:
            structure = climax["structure_hint"]
            return {"phase": "A", "structure": structure, "confidence": 0.55,
                    "details": {"climax": climax, "range": tr,
                                "reason": "recent climax with forming range"}}

    # Step 7: 默认 Phase B — 在区间内震荡, 无特殊事件
    # structure推导: 区间在价格历史的什么位置
    overall_mid = (max(highs) + min(lows)) / 2
    range_mid = (tr["support"] + tr["resistance"]) / 2
    if range_mid < overall_mid - atr:
        structure = "ACCUMULATION"
    elif range_mid > overall_mid + atr:
        structure = "DISTRIBUTION"
    else:
        structure = "UNKNOWN"

    return {"phase": "B", "structure": structure, "confidence": 0.5,
            "details": {"range": tr, "reason": "in range, no spring/breakout/climax"}}


def reconcile_ab(a_phase: str, a_structure: str,
                 b_result: Dict) -> Tuple[str, str, str]:
    """双通道A+B结果调和。

    Args:
        a_phase: A通道Phase (from Vision LLM)
        a_structure: A通道structure
        b_result: B通道 detect_phase() 完整返回

    Returns:
        (final_bias, final_phase, source):
          final_bias: "BUY"|"SELL"|"HOLD"
          final_phase: "A"-"E"|"X"
          source: "A"|"B"|"AB" (来源标记)
    """
    b_phase = b_result.get("phase", "X")
    b_structure = b_result.get("structure", "UNKNOWN")
    b_conf = b_result.get("confidence", 0.0)

    # 如果一方是X(无法判断), 用另一方
    if a_phase == "X" and b_phase == "X":
        return "HOLD", "X", "AB"
    if a_phase == "X":
        return _phase_to_bias(b_phase, b_structure), b_phase, "B"
    if b_phase == "X":
        return _phase_to_bias(a_phase, a_structure), a_phase, "A"

    # 两方都有判断 → 取共识或保守
    if a_phase == b_phase:
        # 完全一致 → 高置信
        structure = a_structure if a_structure != "UNKNOWN" else b_structure
        return _phase_to_bias(a_phase, structure), a_phase, "AB"

    # 不一致 → 取更保守的(Phase序号更小 = 更早 = 更保守)
    phase_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    a_ord = phase_order.get(a_phase, -1)
    b_ord = phase_order.get(b_phase, -1)

    # 特殊: 一方说C(入场), 另一方说B(等待) → 保守取B
    # 特殊: 一方说D/E(趋势), 另一方说B(等待) → 如果B通道置信高, 取B
    if b_conf >= 0.6 and b_ord < a_ord:
        structure = b_structure if b_structure != "UNKNOWN" else a_structure
        return _phase_to_bias(b_phase, structure), b_phase, "B"
    elif a_ord <= b_ord:
        structure = a_structure if a_structure != "UNKNOWN" else b_structure
        return _phase_to_bias(a_phase, structure), a_phase, "A"
    else:
        structure = b_structure if b_structure != "UNKNOWN" else a_structure
        return _phase_to_bias(b_phase, structure), b_phase, "B"


def _phase_to_bias(phase: str, structure: str) -> str:
    """Phase + structure → 门控方向。与A通道 _read_wyckoff_phase 规则一致。"""
    if phase in ("A", "B", "X"):
        return "HOLD"
    # C/D/E → 跟随structure
    if structure in ("ACCUMULATION", "MARKUP"):
        return "BUY"
    elif structure in ("DISTRIBUTION", "MARKDOWN"):
        return "SELL"
    return "HOLD"

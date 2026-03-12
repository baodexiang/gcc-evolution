"""
modules/knn/features.py — L1 特征提取
======================================
8个外挂特征提取器 + 价格形状/量/ATR/Regime特征。
gcc-evo五层架构: L1 数据模型层(特征工程)
"""

import numpy as np

from .models import (
    PRICE_SHAPE_WINDOW, VOL_SHAPE_WINDOW, ATR_WINDOW,
    USE_STL_RESIDUAL, STL_PERIOD,
)


# ============================================================
# GCC-0137: OHLC一致性约束清洗
# ============================================================
def validate_ohlc_bars(bars: list) -> list:
    """强制 L <= min(O,C) <= max(O,C) <= H, volume >= 0"""
    for b in bars:
        o, h, l, c = b.get("open", 0), b.get("high", 0), b.get("low", 0), b.get("close", 0)
        b["high"] = max(o, h, l, c)
        b["low"] = min(o, h, l, c)
        if "volume" in b and (b["volume"] or 0) < 0:
            b["volume"] = 0
    return bars


# ============================================================
# GCC-0136: STL分解残差
# ============================================================
def stl_decompose_residual(series: np.ndarray, period: int = STL_PERIOD) -> np.ndarray:
    """STL分解取残差; 数据不足或异常时回退到一阶差分"""
    if len(series) < period * 2:
        return np.diff(series, prepend=series[0])
    try:
        from statsmodels.tsa.seasonal import STL
        stl = STL(series, period=period, robust=True)
        result = stl.fit()
        return result.resid
    except Exception:
        return np.diff(series, prepend=series[0])


# ============================================================
# 基础形状特征
# ============================================================
def extract_price_shape(bars: list, window: int = PRICE_SHAPE_WINDOW) -> np.ndarray:
    """最近window根K线收盘价归一化为[0,1]形状; STL模式下用残差归一化"""
    if not bars or len(bars) < window:
        return np.zeros(window)
    closes = np.array([b["close"] for b in bars[-window:]], dtype=float)
    if USE_STL_RESIDUAL:
        closes = stl_decompose_residual(closes, STL_PERIOD)
    lo, hi = closes.min(), closes.max()
    if hi <= lo:
        return np.zeros(window)
    return (closes - lo) / (hi - lo)


def extract_volume_shape(bars: list, window: int = VOL_SHAPE_WINDOW) -> np.ndarray:
    """最近window根K线成交量归一化为[0,1]形状 (20维)"""
    if not bars or len(bars) < window:
        return np.zeros(window)
    vols = np.array([b.get("volume", 0) or 0 for b in bars[-window:]], dtype=float)
    lo, hi = vols.min(), vols.max()
    if hi <= lo:
        return np.zeros(window)
    return (vols - lo) / (hi - lo)


def extract_atr_features(bars: list, window: int = ATR_WINDOW) -> np.ndarray:
    """最近window根K线 ATR/price 比值 → 波动率特征 (20维)"""
    if not bars or len(bars) < window:
        return np.zeros(window)
    recent = bars[-window:]
    atr_ratios = []
    for b in recent:
        tr = b["high"] - b["low"]
        mid = (b["high"] + b["low"]) / 2.0
        atr_ratios.append(tr / mid if mid > 0 else 0.0)
    return np.array(atr_ratios, dtype=float)


def extract_regime_feature(bars: list) -> np.ndarray:
    """市场Regime编码: bull=1.0, bear=-1.0, sideways=0.0 (1维)"""
    regime = infer_regime_from_bars(bars)
    _map = {"bull": 1.0, "bear": -1.0, "sideways": 0.0, "unknown": 0.0}
    return np.array([_map.get(regime, 0.0)])


# ============================================================
# 辅助函数
# ============================================================
def _calc_dc_position(bars: list, window: int = 20) -> float:
    """当前价在最近window根K线高低区间的位置 [0,1]"""
    if not bars or len(bars) < 2:
        return 0.5
    recent = bars[-min(window, len(bars)):]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]
    hi, lo = max(highs), min(lows)
    if hi <= lo:
        return 0.5
    current = bars[-1]["close"]
    return max(0.0, min(1.0, (current - lo) / (hi - lo)))


def _calc_vol_ratio(bars: list) -> float:
    """最后一根K线成交量 / 最近20根均量, 裁剪到[0,3]"""
    if not bars or len(bars) < 5:
        return 1.0
    vols = [b.get("volume", 0) or 0 for b in bars[-20:]]
    avg_vol = np.mean(vols) if vols else 1
    if avg_vol <= 0:
        return 1.0
    return min(3.0, float(bars[-1].get("volume", 0) or 0) / avg_vol)


def infer_regime_from_bars(bars: list) -> str:
    """从K线推断regime: bull/bear/sideways"""
    if not bars or len(bars) < 10:
        return "unknown"
    dc_pos = _calc_dc_position(bars, 20)
    trend = _calc_trend_consistency(bars)
    if dc_pos > 0.7 and trend > 0.6:
        return "bull"
    if dc_pos < 0.3 and trend < 0.4:
        return "bear"
    return "sideways"


def _calc_trend_consistency(bars: list) -> float:
    """最近10根K线中阳线占比 → [0,1], 0.5=中性"""
    if not bars or len(bars) < 3:
        return 0.5
    recent = bars[-min(10, len(bars)):]
    ups = sum(1 for b in recent if b["close"] > b["open"])
    return float(ups) / len(recent)


# ============================================================
# 统一拼接
# ============================================================
def _append_extended_features(indicator: np.ndarray, bars: list) -> np.ndarray:
    """统一拼接: indicator + price_shape(20) + vol_shape(20) + atr(20) + regime(1)"""
    bars = validate_ohlc_bars(bars)
    shape = extract_price_shape(bars)
    vol = extract_volume_shape(bars)
    atr = extract_atr_features(bars)
    regime = extract_regime_feature(bars)
    return np.concatenate([indicator, shape, vol, atr, regime])


# ============================================================
# 8个外挂特征提取器
# ============================================================
def extract_supertrend_features(result, bars: list, market_data: dict) -> np.ndarray:
    """SuperTrend: st_direction + qqe_hist + macd_hist + position_pct + dc_position → 5维 + 61维扩展"""
    st_dir = 1.0 if getattr(result, 'supertrend_trend', 1) == 1 else -1.0
    qqe = float(getattr(result, 'qqe_hist', 0) or 0)
    macd = float(getattr(result, 'macd_hist', 0) or 0)
    pos_pct = float(market_data.get('position_pct', 50)) / 100.0
    dc_pos = _calc_dc_position(bars, 20)
    indicator = np.array([st_dir, qqe, macd, pos_pct, dc_pos])
    return _append_extended_features(indicator, bars)


def extract_supertrend_av2_features(result, bars: list, market_data: dict) -> np.ndarray:
    """SuperTrend+AV2: st_direction + qqe_hist + av2_state + position_pct → 4维 + 61维扩展"""
    st_dir = 1.0 if getattr(result, 'supertrend_direction', '') == 'UP' else -1.0
    qqe = float(getattr(result, 'qqe_value', 0) or 0)
    av2_state = 1.0 if getattr(result, 'av2_color', '') == 'GREEN' else -1.0
    pos_pct = float(getattr(result, 'position_pct', 50) or 50) / 100.0
    indicator = np.array([st_dir, qqe, av2_state, pos_pct])
    return _append_extended_features(indicator, bars)


def extract_chanbs_features(result, bars: list, dc_regime=None) -> np.ndarray:
    """缠论BS: bs_type_encoded + strength + bi_count + zs_count + dc_position → 5维 + 61维"""
    _bs_map = {"一买": 1, "二买": 2, "三买": 3, "一卖": 4, "二卖": 5, "三卖": 6,
               "FIRST_BUY": 1, "SECOND_BUY": 2, "THIRD_BUY": 3,
               "FIRST_SELL": 4, "SECOND_SELL": 5, "THIRD_SELL": 6}
    bs_val = getattr(result, 'bs_type', None)
    bs_str = bs_val.value if hasattr(bs_val, 'value') else str(bs_val or '')
    bs_encoded = float(_bs_map.get(bs_str, 0)) / 6.0
    strength = float(getattr(result, 'strength', 0) or 0)
    bi_count = min(float(getattr(result, 'bi_count', 0) or 0), 20) / 20.0
    zs_count = min(float(getattr(result, 'zs_count', 0) or 0), 5) / 5.0
    dc_pos = _calc_dc_position(bars, 20)
    indicator = np.array([bs_encoded, strength, bi_count, zs_count, dc_pos])
    return _append_extended_features(indicator, bars)


def extract_double_pattern_features(result, bars: list) -> np.ndarray:
    """VisionPattern: pattern_type_encoded + confidence + stage_encoded + volume_ratio → 4维 + 61维"""
    _pat_map = {"DOUBLE_BOTTOM": 1, "DOUBLE_TOP": 2, "HEAD_SHOULDERS": 3,
                "INV_HEAD_SHOULDERS": 4, "FLAG_BULL": 5, "FLAG_BEAR": 6,
                "TRIANGLE": 7, "CUP_HANDLE": 8}
    pat_val = getattr(result, 'pattern', None)
    pat_str = pat_val.value if hasattr(pat_val, 'value') else str(pat_val or '')
    pat_encoded = float(_pat_map.get(pat_str, 0)) / 8.0
    confidence = float(getattr(result, 'confidence', 0) or 0)
    stage_val = getattr(result, 'stage', None)
    stage_str = stage_val.value if hasattr(stage_val, 'value') else str(stage_val or '')
    _stage_map = {"EARLY": 0.25, "MID": 0.5, "LATE": 0.75, "COMPLETE": 1.0}
    stage_encoded = _stage_map.get(stage_str, 0.5)
    vol_ratio = _calc_vol_ratio(bars)
    indicator = np.array([pat_encoded, confidence, stage_encoded, vol_ratio])
    return _append_extended_features(indicator, bars)


def extract_rob_hoffman_features(result, bars: list, market_data: dict) -> np.ndarray:
    """RobHoffman: alignment_encoded + er_value + pullback_depth + position_pct → 4维 + 61维"""
    align_val = getattr(result, 'alignment', None)
    align_str = align_val.value if hasattr(align_val, 'value') else str(align_val or '')
    _align_map = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0, "TANGLED": 0.0}
    align_encoded = _align_map.get(align_str, 0.0)
    er_value = float(getattr(result, 'er_value', 0) or 0)
    pullback = float(getattr(result, 'confidence', 0) or 0)
    pos_pct = float(market_data.get('position_pct', 50)) / 100.0
    indicator = np.array([align_encoded, er_value, pullback, pos_pct])
    return _append_extended_features(indicator, bars)


def extract_feiyun_features(result, bars: list) -> np.ndarray:
    """飞云: break_type_encoded + confidence + is_double + trend_consistency → 4维 + 61维"""
    sig_val = getattr(result, 'signal', None)
    sig_str = sig_val.value if hasattr(sig_val, 'value') else str(sig_val or '')
    _break_map = {"BUY": 1.0, "SELL": -1.0, "HOLD": 0.0, "STRONG_BUY": 1.0, "STRONG_SELL": -1.0}
    break_encoded = _break_map.get(sig_str, 0.0)
    confidence = float(getattr(result, 'confidence', 0) or 0)
    is_double = 1.0 if getattr(result, 'is_double', False) else 0.0
    trend_consistency = _calc_trend_consistency(bars)
    indicator = np.array([break_encoded, confidence, is_double, trend_consistency])
    return _append_extended_features(indicator, bars)


def extract_chandelier_features(result, bars: list) -> np.ndarray:
    """Chandelier+ZLSMA: ha_direction + zlsma_slope + ce_direction + er_value → 4维 + 61维"""
    brooks_state = getattr(result, 'brooks_state', {}) or {}
    always_in = brooks_state.get('always_in', 'NEUTRAL')
    _ai_map = {"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0}
    ha_dir = _ai_map.get(always_in, 0.0)
    strength = float(getattr(result, 'strength', 0) or 0)
    setup = getattr(result, 'setup_type', '') or ''
    _setup_map = {"TREND_BAR": 1.0, "REVERSAL": -1.0, "BREAKOUT": 0.5, "PULLBACK": 0.3}
    ce_dir = _setup_map.get(setup, 0.0)
    dc_pos = _calc_dc_position(bars, 20)
    indicator = np.array([ha_dir, strength, ce_dir, dc_pos])
    return _append_extended_features(indicator, bars)


def extract_l2_macd_features(div_result, bars: list, position_pct: float = 50.0) -> np.ndarray:
    """L2-MACD: div_type + strength_pct + kline_count + position_pct → 4维 + 61维"""
    divergence = getattr(div_result, 'divergence', None)
    if divergence:
        div_type_val = getattr(divergence, 'div_type', None)
        div_str = div_type_val.value if hasattr(div_type_val, 'value') else str(div_type_val or '')
        div_encoded = 1.0 if div_str == "BULLISH" else -1.0
        strength = min(float(getattr(divergence, 'strength_pct', 0) or 0), 100) / 100.0
        kline_count = min(float(getattr(divergence, 'kline_count', 0) or 0), 30) / 30.0
    else:
        div_encoded = 0.0
        strength = 0.0
        kline_count = 0.0
    pos_norm = float(position_pct) / 100.0
    indicator = np.array([div_encoded, strength, kline_count, pos_norm])
    return _append_extended_features(indicator, bars)


def extract_gcctm_features(result: dict, bars: list) -> np.ndarray:
    """GCC-TM: tree_score + consensus + topology/geometry/algebra + signal_pool → 8维 + 61维
    GCC-0254: 接入统一KNN，让gcc-evo循环能看到GCC-TM决策数据"""
    tree_score = min(float(result.get("tree_score", 0)), 1.0)
    consensus = min(float(result.get("consensus", 0)), 3.0) / 3.0  # 0~3 → 0~1
    topo = 1.0 if result.get("topology") == "PASS" else 0.0
    geom = 1.0 if result.get("geometry") == "PASS" else 0.0
    algb = 1.0 if result.get("algebra") == "PASS" else 0.0
    buy_sig = min(float(result.get("buy_signals", 0)), 10) / 10.0
    sell_sig = min(float(result.get("sell_signals", 0)), 10) / 10.0
    sig_count = min(float(result.get("signals_count", 0)), 20) / 20.0
    indicator = np.array([tree_score, consensus, topo, geom, algb,
                          buy_sig, sell_sig, sig_count])
    return _append_extended_features(indicator, bars)

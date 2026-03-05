# ========================================================================
# 飞云双突破外挂模块 v1.0
# ========================================================================
#
# 版本: 1.0
# 日期: 2026-01-25
#
# 核心策略 (飞云交易系统):
#   1. 趋势线突破: 价格突破下降趋势线(买)/上升趋势线(卖)
#   2. 形态突破: 价格突破近期箱体高点(买)/低点(卖)
#   3. 双突破: 同时满足趋势线突破+形态突破 → 高置信度信号
#
# 特性:
#   - L1层级，1小时周期
#   - 趋势专用外挂，需配合L1趋势方向
#   - 双突破=强信号，单突破=弱信号
#   - 量能确认增强信号置信度
#
# 激活条件:
#   - is_double=True (双突破)
#   - L1趋势方向一致 (UP+DOUBLE_BREAK_BUY 或 DOWN+DOUBLE_BREAK_SELL)
#
# ========================================================================

import numpy as np
import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ========================================================================
# 配置常量
# ========================================================================

LOG_DIR = "logs"
FEIYUN_LOG_FILE = "feiyun_plugin.log"

# 趋势线突破阈值
TRENDLINE_BREAK_PCT = 0.5  # 突破趋势线0.5%以上

# 箱体突破参数
BOX_LOOKBACK = 20  # 箱体回看K线数
BOX_BREAK_PCT = 0.02  # 箱体突破阈值 (箱体高度的2%)

# 放量确认
VOLUME_CONFIRM_RATIO = 1.3  # 放量比例 (>=130%视为放量)

# 位置过滤
BUY_MAX_POSITION_PCT = 80  # 买入位置上限
SELL_MIN_POSITION_PCT = 20  # 卖出位置下限

# 最小K线数
MIN_BARS_FOR_ANALYSIS = 20


# ========================================================================
# 枚举定义
# ========================================================================

class FeiyunSignal(Enum):
    """飞云信号类型"""
    DOUBLE_BREAK_BUY = "DOUBLE_BREAK_BUY"    # 双突破买入
    DOUBLE_BREAK_SELL = "DOUBLE_BREAK_SELL"  # 双突破卖出
    SINGLE_UP = "SINGLE_UP"                   # 单突破向上
    SINGLE_DOWN = "SINGLE_DOWN"               # 单突破向下
    NONE = "NONE"                             # 无信号


class PluginMode(Enum):
    """外挂工作模式"""
    ACTIVE = "ACTIVE"           # 激活 (双突破+趋势一致)
    SINGLE_BREAK = "SINGLE_BREAK"  # 单突破 (弱信号)
    FILTERED = "FILTERED"       # 过滤 (位置/趋势不符)
    WAITING = "WAITING"         # 等待 (条件未满足)


# ========================================================================
# 数据结构
# ========================================================================

@dataclass
class FeiyunResult:
    """飞云外挂分析结果"""
    signal: FeiyunSignal = FeiyunSignal.NONE
    mode: PluginMode = PluginMode.WAITING
    is_double: bool = False
    confidence: float = 0.0
    score: int = 0  # -3 to +3

    # 趋势线突破详情
    trendline_break_type: str = "NONE"
    trendline_slope: float = 0.0
    trendline_value: float = 0.0

    # 形态突破详情
    pattern_break_type: str = "NONE"
    box_high: float = 0.0
    box_low: float = 0.0
    volume_confirmed: bool = False

    # 入场参考
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    reason: str = ""
    reasons: List[str] = field(default_factory=list)
    timestamp: str = ""


# ========================================================================
# 辅助函数
# ========================================================================

def log_to_file(message: str):
    """写入日志文件"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, FEIYUN_LOG_FILE)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def find_swing_points(highs: List[float], lows: List[float], n: int = 2) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """
    识别摆动高点和摆动低点

    摆动高点(Swing High): 左右各n根的High都比它低
    摆动低点(Swing Low): 左右各n根的Low都比它高

    Args:
        highs: K线高点序列
        lows: K线低点序列
        n: 左右确认K线数量（默认2）

    Returns:
        (swing_highs, swing_lows) - 每个元素是(索引, 价格)
    """
    swing_highs = []
    swing_lows = []

    if len(highs) < 2 * n + 1 or len(lows) < 2 * n + 1:
        return swing_highs, swing_lows

    for i in range(n, len(highs) - n):
        # 检查是否为摆动高点
        is_swing_high = True
        for j in range(1, n + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing_high = False
                break
        if is_swing_high:
            swing_highs.append((i, highs[i]))

        # 检查是否为摆动低点
        is_swing_low = True
        for j in range(1, n + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_swing_low = False
                break
        if is_swing_low:
            swing_lows.append((i, lows[i]))

    return swing_highs, swing_lows


def fit_trendline(points: List[Tuple[int, float]], is_descending: bool = True) -> Tuple[float, float]:
    """
    拟合趋势线（简单线性回归）

    Args:
        points: [(index, price), ...] - 摆动点列表
        is_descending: True=下降趋势线(连接高点)

    Returns:
        (slope, intercept) - 斜率和截距
    """
    if len(points) < 2:
        return (0.0, 0.0)

    recent_points = points[-3:] if len(points) >= 3 else points[-2:]
    n = len(recent_points)

    sum_x = sum(p[0] for p in recent_points)
    sum_y = sum(p[1] for p in recent_points)
    sum_xy = sum(p[0] * p[1] for p in recent_points)
    sum_x2 = sum(p[0] ** 2 for p in recent_points)

    denominator = n * sum_x2 - sum_x ** 2
    if abs(denominator) < 1e-10:
        return (0.0, sum_y / n if n > 0 else 0.0)

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n

    return (slope, intercept)


# ========================================================================
# 飞云外挂类
# ========================================================================

class FeiyunPlugin:
    """
    飞云双突破外挂

    用于L1层级，检测双突破信号(趋势线+形态)
    """

    VERSION = "1.0"

    def __init__(self):
        self._state_lock = threading.Lock()
        self._last_results: Dict[str, FeiyunResult] = {}
        self._log(f"Feiyun Plugin v{self.VERSION} initialized")

    def _log(self, message: str):
        """写入日志"""
        log_to_file(message)

    # ====================================================================
    # 趋势线突破检测
    # ====================================================================

    def _detect_trendline_break(self, ohlcv_bars: List[Dict], swing_highs: List, swing_lows: List) -> dict:
        """检测趋势线突破"""
        result = {
            "break_type": "NONE",
            "trendline_slope": 0.0,
            "trendline_value": 0.0,
            "price_diff_pct": 0.0,
            "confidence": 0.0,
            "reasons": []
        }

        if not ohlcv_bars or len(ohlcv_bars) < 10:
            return result

        try:
            current_idx = len(ohlcv_bars) - 1
            current_close = ohlcv_bars[-1].get('close', 0)
            current_high = ohlcv_bars[-1].get('high', 0)
            current_low = ohlcv_bars[-1].get('low', 0)

            if current_close <= 0:
                return result

            # 检查下降趋势线突破（用swing highs拟合）
            if len(swing_highs) >= 2:
                slope_desc, intercept_desc = fit_trendline(swing_highs, is_descending=True)

                if slope_desc < 0:  # 趋势线必须下降
                    trendline_value = slope_desc * current_idx + intercept_desc
                    result["trendline_value"] = trendline_value
                    result["trendline_slope"] = slope_desc

                    diff_pct = (current_close - trendline_value) / trendline_value * 100 if trendline_value > 0 else 0
                    result["price_diff_pct"] = diff_pct

                    if diff_pct > TRENDLINE_BREAK_PCT:
                        result["break_type"] = "UP"
                        result["confidence"] = min(0.9, 0.5 + diff_pct * 0.1)
                        result["reasons"].append(f"break_desc_trendline_{diff_pct:.1f}%")

                        if current_low > trendline_value:
                            result["confidence"] = min(0.95, result["confidence"] + 0.1)
                            result["reasons"].append("full_bar_above_trendline")
                        return result

            # 检查上升趋势线跌破（用swing lows拟合）
            if len(swing_lows) >= 2:
                slope_asc, intercept_asc = fit_trendline(swing_lows, is_descending=False)

                if slope_asc > 0:  # 趋势线必须上升
                    trendline_value = slope_asc * current_idx + intercept_asc
                    result["trendline_value"] = trendline_value
                    result["trendline_slope"] = slope_asc

                    diff_pct = (trendline_value - current_close) / trendline_value * 100 if trendline_value > 0 else 0
                    result["price_diff_pct"] = -diff_pct

                    if diff_pct > TRENDLINE_BREAK_PCT:
                        result["break_type"] = "DOWN"
                        result["confidence"] = min(0.9, 0.5 + diff_pct * 0.1)
                        result["reasons"].append(f"break_asc_trendline_{diff_pct:.1f}%")

                        if current_high < trendline_value:
                            result["confidence"] = min(0.95, result["confidence"] + 0.1)
                            result["reasons"].append("full_bar_below_trendline")
                        return result

        except Exception as e:
            result["reasons"].append(f"error:{str(e)[:20]}")

        return result

    # ====================================================================
    # 形态突破检测
    # ====================================================================

    def _detect_pattern_break(self, ohlcv_bars: List[Dict], lookback: int = BOX_LOOKBACK) -> dict:
        """检测形态突破（箱体突破）"""
        result = {
            "break_type": "NONE",
            "box_high": 0.0,
            "box_low": 0.0,
            "box_mid": 0.0,
            "volume_confirmed": False,
            "confidence": 0.0,
            "reasons": []
        }

        if not ohlcv_bars or len(ohlcv_bars) < lookback:
            return result

        try:
            # 计算箱体范围（排除最近2根K线）
            box_bars = ohlcv_bars[-(lookback):-2]
            if len(box_bars) < 10:
                return result

            highs = [b.get('high', 0) for b in box_bars]
            lows = [b.get('low', 0) for b in box_bars]

            if not highs or not lows:
                return result

            box_high = max(highs)
            box_low = min(lows)
            box_mid = (box_high + box_low) / 2
            box_range = box_high - box_low

            result["box_high"] = box_high
            result["box_low"] = box_low
            result["box_mid"] = box_mid

            # 当前K线
            current = ohlcv_bars[-1]
            current_close = current.get('close', 0)
            current_high = current.get('high', 0)
            current_low = current.get('low', 0)
            current_vol = current.get('volume', 0)

            # 检查放量
            volumes = [b.get('volume', 0) for b in box_bars]
            avg_vol = sum(volumes) / len(volumes) if volumes else 1
            if avg_vol > 0 and current_vol > avg_vol * VOLUME_CONFIRM_RATIO:
                result["volume_confirmed"] = True
                result["reasons"].append(f"volume_{current_vol/avg_vol:.1f}x")

            # 突破阈值
            min_abs_threshold = current_close * 0.005
            break_threshold = max(box_range * BOX_BREAK_PCT, min_abs_threshold)

            # 向上突破
            if current_close > box_high + break_threshold:
                result["break_type"] = "UP"
                diff_pct = (current_close - box_high) / box_high * 100 if box_high > 0 else 0
                result["confidence"] = min(0.85, 0.5 + diff_pct * 0.05)
                result["reasons"].append(f"break_box_high_{diff_pct:.1f}%")

                if result["volume_confirmed"]:
                    result["confidence"] = min(0.95, result["confidence"] + 0.15)
                if current_low > box_high:
                    result["confidence"] = min(0.95, result["confidence"] + 0.1)
                    result["reasons"].append("gap_above_box")
                return result

            # 向下突破
            if current_close < box_low - break_threshold:
                result["break_type"] = "DOWN"
                diff_pct = (box_low - current_close) / box_low * 100 if box_low > 0 else 0
                result["confidence"] = min(0.85, 0.5 + diff_pct * 0.05)
                result["reasons"].append(f"break_box_low_{diff_pct:.1f}%")

                if result["volume_confirmed"]:
                    result["confidence"] = min(0.95, result["confidence"] + 0.15)
                if current_high < box_low:
                    result["confidence"] = min(0.95, result["confidence"] + 0.1)
                    result["reasons"].append("gap_below_box")
                return result

        except Exception as e:
            result["reasons"].append(f"error:{str(e)[:20]}")

        return result

    # ====================================================================
    # 主处理函数
    # ====================================================================

    def process(
        self,
        symbol: str,
        ohlcv_bars: List[Dict],
        current_trend: str = "SIDE",
        pos_in_channel: float = 0.5,
        position_units: int = 0,  # v1.1: 实际持仓数量
    ) -> FeiyunResult:
        """
        处理K线数据，生成双突破信号

        Args:
            symbol: 交易标的
            ohlcv_bars: K线数据列表 [{open, high, low, close, volume}, ...]
            current_trend: L1当前周期趋势 (UP/DOWN/SIDE)
            pos_in_channel: 当前价格在通道中的位置 (0-1)
            position_units: 实际持仓数量 (0-5)，用于退出卖出判断

        Returns:
            FeiyunResult: 分析结果
        """
        self._position_units = position_units  # v1.1: 保存持仓供过滤时使用
        result = FeiyunResult(timestamp=datetime.now().isoformat())

        # 检查数据量
        if not ohlcv_bars or len(ohlcv_bars) < MIN_BARS_FOR_ANALYSIS:
            result.mode = PluginMode.WAITING
            result.reason = f"Insufficient bars: {len(ohlcv_bars) if ohlcv_bars else 0} < {MIN_BARS_FOR_ANALYSIS}"
            return result

        try:
            # 提取高低点序列
            highs = [b.get('high', 0) for b in ohlcv_bars]
            lows = [b.get('low', 0) for b in ohlcv_bars]

            if len(highs) < 15 or len(lows) < 15:
                result.mode = PluginMode.WAITING
                result.reason = "Insufficient price data"
                return result

            # 找摆动点
            swing_highs, swing_lows = find_swing_points(highs, lows, n=2)

            # 检测趋势线突破
            tl_result = self._detect_trendline_break(ohlcv_bars, swing_highs, swing_lows)
            result.trendline_break_type = tl_result["break_type"]
            result.trendline_slope = tl_result["trendline_slope"]
            result.trendline_value = tl_result["trendline_value"]
            result.reasons.extend(tl_result.get("reasons", []))

            # 检测形态突破
            pt_result = self._detect_pattern_break(ohlcv_bars)
            result.pattern_break_type = pt_result["break_type"]
            result.box_high = pt_result["box_high"]
            result.box_low = pt_result["box_low"]
            result.volume_confirmed = pt_result["volume_confirmed"]
            result.reasons.extend(pt_result.get("reasons", []))

            tl_break = tl_result["break_type"]
            pt_break = pt_result["break_type"]

            # 双突破判断
            if tl_break == "UP" and pt_break == "UP":
                result.signal = FeiyunSignal.DOUBLE_BREAK_BUY
                result.is_double = True
                result.confidence = min(0.95, (tl_result["confidence"] + pt_result["confidence"]) / 2 + 0.15)
                result.score = 3
                result.reasons.append("double_break_buy")

            elif tl_break == "DOWN" and pt_break == "DOWN":
                result.signal = FeiyunSignal.DOUBLE_BREAK_SELL
                result.is_double = True
                result.confidence = min(0.95, (tl_result["confidence"] + pt_result["confidence"]) / 2 + 0.15)
                result.score = -3
                result.reasons.append("double_break_sell")

            elif tl_break == "UP" or pt_break == "UP":
                result.signal = FeiyunSignal.SINGLE_UP
                result.is_double = False
                conf = tl_result["confidence"] if tl_break == "UP" else pt_result["confidence"]
                result.confidence = conf * 0.6
                result.score = 1
                result.reasons.append("single_break_up")

            elif tl_break == "DOWN" or pt_break == "DOWN":
                result.signal = FeiyunSignal.SINGLE_DOWN
                result.is_double = False
                conf = tl_result["confidence"] if tl_break == "DOWN" else pt_result["confidence"]
                result.confidence = conf * 0.6
                result.score = -1
                result.reasons.append("single_break_down")

            # 设置入场价格
            if ohlcv_bars:
                result.entry_price = ohlcv_bars[-1].get('close', 0)
                atr = self._calculate_atr(ohlcv_bars, 14)
                if result.signal in (FeiyunSignal.DOUBLE_BREAK_BUY, FeiyunSignal.SINGLE_UP):
                    result.stop_loss = result.entry_price - atr * 1.5
                    result.take_profit = result.entry_price + atr * 3.0
                elif result.signal in (FeiyunSignal.DOUBLE_BREAK_SELL, FeiyunSignal.SINGLE_DOWN):
                    result.stop_loss = result.entry_price + atr * 1.5
                    result.take_profit = result.entry_price - atr * 3.0

            # 位置过滤
            pos_pct = pos_in_channel * 100 if pos_in_channel <= 1 else pos_in_channel

            if result.signal in (FeiyunSignal.DOUBLE_BREAK_BUY, FeiyunSignal.SINGLE_UP):
                if pos_pct > BUY_MAX_POSITION_PCT:
                    result.mode = PluginMode.FILTERED
                    result.reason = f"BUY filtered: position {pos_pct:.0f}% > {BUY_MAX_POSITION_PCT}%"
                    self._log(f"[{symbol}] {result.reason}")
                    return result

            if result.signal in (FeiyunSignal.DOUBLE_BREAK_SELL, FeiyunSignal.SINGLE_DOWN):
                if pos_pct < SELL_MIN_POSITION_PCT:
                    # v1.1: 有持仓时允许退出卖出
                    if getattr(self, '_position_units', 0) > 0:
                        self._log(f"[{symbol}] SELL: 持仓退出模式 (position_units={self._position_units})，跳过位置过滤")
                    else:
                        result.mode = PluginMode.FILTERED
                        result.reason = f"SELL filtered: position {pos_pct:.0f}% < {SELL_MIN_POSITION_PCT}%"
                        self._log(f"[{symbol}] {result.reason}")
                        return result

            # 趋势一致性检查（仅双突破需要）
            # KEY-006: conf>=0.70 的双突破信号绕过趋势过滤
            # 原因: 双突破本身是反转信号, 历史分析显示 conf 0.73~0.82 的信号被100%过滤
            HIGH_CONF_BYPASS = 0.70
            if result.is_double:
                if result.signal == FeiyunSignal.DOUBLE_BREAK_BUY and current_trend == "UP":
                    result.mode = PluginMode.ACTIVE
                    result.reason = f"DOUBLE_BREAK_BUY confirmed (trend={current_trend})"
                elif result.signal == FeiyunSignal.DOUBLE_BREAK_SELL and current_trend == "DOWN":
                    result.mode = PluginMode.ACTIVE
                    result.reason = f"DOUBLE_BREAK_SELL confirmed (trend={current_trend})"
                elif result.confidence >= HIGH_CONF_BYPASS:
                    # 高置信度反转信号: 绕过趋势过滤, 降级为 SINGLE_BREAK 强度
                    result.mode = PluginMode.SINGLE_BREAK
                    result.reason = (f"Trend mismatch bypassed: conf={result.confidence:.2f}>={HIGH_CONF_BYPASS}"
                                     f" signal={result.signal.value} trend={current_trend}")
                else:
                    result.mode = PluginMode.FILTERED
                    result.reason = f"Trend mismatch: signal={result.signal.value}, trend={current_trend} conf={result.confidence:.2f}<{HIGH_CONF_BYPASS}"
            else:
                result.mode = PluginMode.SINGLE_BREAK
                result.reason = f"Single break only: {result.signal.value}"

            # 记录结果
            self._last_results[symbol] = result
            self._log(f"[{symbol}] {result.signal.value} | mode={result.mode.value} | conf={result.confidence:.2f} | {result.reason}")

        except Exception as e:
            result.mode = PluginMode.WAITING
            result.reason = f"Error: {str(e)[:50]}"
            self._log(f"[{symbol}] ERROR: {e}")

        return result

    def _calculate_atr(self, ohlcv_bars: List[Dict], period: int = 14) -> float:
        """计算ATR"""
        if len(ohlcv_bars) < period + 1:
            return 0.0

        tr_list = []
        for i in range(1, len(ohlcv_bars)):
            high = ohlcv_bars[i].get('high', 0)
            low = ohlcv_bars[i].get('low', 0)
            prev_close = ohlcv_bars[i-1].get('close', 0)

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        if len(tr_list) < period:
            return sum(tr_list) / len(tr_list) if tr_list else 0.0

        return sum(tr_list[-period:]) / period

    def should_activate(self, result: FeiyunResult) -> bool:
        """判断是否应该激活外挂执行"""
        return result.mode == PluginMode.ACTIVE and result.is_double

    def get_last_result(self, symbol: str) -> Optional[FeiyunResult]:
        """获取上次分析结果"""
        return self._last_results.get(symbol)


# ========================================================================
# 单例模式
# ========================================================================

_feiyun_plugin_instance = None
_feiyun_plugin_lock = threading.Lock()


def get_feiyun_plugin() -> FeiyunPlugin:
    """获取飞云外挂单例"""
    global _feiyun_plugin_instance
    if _feiyun_plugin_instance is None:
        with _feiyun_plugin_lock:
            if _feiyun_plugin_instance is None:
                _feiyun_plugin_instance = FeiyunPlugin()
    return _feiyun_plugin_instance


# ========================================================================
# 测试代码
# ========================================================================

if __name__ == "__main__":
    print("Feiyun Plugin v1.0 - Test")

    # 模拟K线数据
    bars = []
    base_price = 100.0
    for i in range(30):
        # 模拟向上突破形态
        if i < 20:
            price = base_price + i * 0.1
        else:
            price = base_price + 20 * 0.1 + (i - 20) * 0.5  # 突破加速

        bars.append({
            "open": price - 0.2,
            "high": price + 0.3,
            "low": price - 0.4,
            "close": price,
            "volume": 1000 + i * 50,
        })

    plugin = get_feiyun_plugin()
    result = plugin.process(
        symbol="TEST",
        ohlcv_bars=bars,
        current_trend="UP",
        pos_in_channel=0.5,
    )

    print(f"Signal: {result.signal.value}")
    print(f"Mode: {result.mode.value}")
    print(f"Is Double: {result.is_double}")
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Score: {result.score}")
    print(f"Reason: {result.reason}")
    print(f"Reasons: {result.reasons}")
    print(f"Should Activate: {plugin.should_activate(result)}")

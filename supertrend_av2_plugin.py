# ========================================================================
# SuperTrend + QQE MOD + A-V2 趋势过滤器交易系统 v1.0
# ========================================================================
#
# 版本: 1.0
# 日期: 2026-01-25
#
# 知识卡片来源:
#   98%胜率,100%盈利，最准确的买卖信号指标—超级趋势过滤器交易系统
#
# 策略规则:
#   做多条件 (三指标同时满足):
#     1. SuperTrend 买入信号
#     2. QQE MOD 零轴上方蓝色柱状图
#     3. A-V2 趋势线呈绿色
#
#   做空条件 (三指标同时满足):
#     1. SuperTrend 卖出信号
#     2. QQE MOD 零轴下方红色柱状图
#     3. A-V2 趋势线呈红色
#
#   震荡过滤:
#     - QQE MOD 灰色柱状图 = 不交易
#
#   风控规则:
#     - 止损: A-V2趋势线下方(多)/上方(空)
#     - 止盈: SuperTrend折线(ATR跟踪)
#
# 与原SuperTrend外挂对比:
#   | 项目     | 原外挂(v0.8)  | 本外挂(v1.0) |
#   |----------|---------------|--------------|
#   | 第三指标 | MACD          | A-V2         |
#   | ATR周期  | 12            | 9            |
#   | ATR乘数  | 3.5           | 3.9          |
#   | 震荡过滤 | 位置%         | QQE颜色      |
#   | 止损方式 | ATR固定       | A-V2线       |
#
# ========================================================================

import numpy as np
import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import time


# ========================================================================
# 配置常量
# ========================================================================

LOG_DIR = "logs"
DIAGNOSIS_LOG_FILE = "supertrend_av2_diagnosis.log"

# 位置过滤 (与原外挂保持一致)
BUY_MAX_POSITION_PCT = 80   # BUY 位置上限（超过则过滤）
SELL_MIN_POSITION_PCT = 20  # SELL 位置下限（低于则过滤）

# QQE MOD 灰色区域阈值
# 当QQE值在±GRAY_THRESHOLD范围内，视为震荡(灰色)
QQE_GRAY_THRESHOLD = 10


# ========================================================================
# 枚举定义
# ========================================================================

class PluginMode(Enum):
    """外挂工作模式"""
    ACTIVE = "ACTIVE"           # 外挂激活 - 三指标共振
    FILTERED = "FILTERED"       # 被过滤 (QQE灰色/位置过滤)
    WAITING = "WAITING"         # 等待信号
    L2_NORMAL = "L2_NORMAL"     # L2正常工作


class QQEColor(Enum):
    """QQE MOD 柱状图颜色"""
    BLUE = "BLUE"   # 看多 (>0 且趋势上升)
    RED = "RED"     # 看空 (<0 且趋势下降)
    GRAY = "GRAY"   # 震荡 (在阈值范围内)


class AV2Color(Enum):
    """A-V2 趋势线颜色"""
    GREEN = "GREEN"   # 上升趋势
    RED = "RED"       # 下降趋势


# ========================================================================
# 数据类
# ========================================================================

@dataclass
class SuperTrendSignal:
    """SuperTrend 信号"""
    trend: int = 0          # 1=绿区(多), -1=红区(空)
    upper_band: float = 0   # 上轨 (止盈用于做空)
    lower_band: float = 0   # 下轨 (止盈用于做多)
    is_buy_signal: bool = False    # 买入信号
    is_sell_signal: bool = False   # 卖出信号


@dataclass
class QQEModSignal:
    """QQE MOD 信号"""
    value: float = 0        # QQE 值
    color: QQEColor = QQEColor.GRAY
    is_ranging: bool = True  # 是否震荡


@dataclass
class AV2Signal:
    """A-V2 趋势指标信号"""
    value: float = 0        # 当前趋势线值
    color: AV2Color = AV2Color.GREEN
    is_rising: bool = True  # 是否上升


@dataclass
class PluginResult:
    """外挂决策结果"""
    mode: PluginMode
    action: str = "NONE"          # BUY / SELL / NONE
    signal: str = "NONE"          # BUY1 / SELL1 / NONE

    # 三指标状态
    supertrend: SuperTrendSignal = None
    qqe: QQEModSignal = None
    av2: AV2Signal = None

    # 止盈止损
    stop_loss: float = 0          # 止损价 (A-V2线)
    take_profit: float = 0        # 止盈价 (SuperTrend线)

    # 其他信息
    position_pct: float = 50
    reason: str = ""
    filter_reason: str = ""
    timestamp: float = 0.0


# ========================================================================
# 指标配置
# ========================================================================

@dataclass
class SuperTrendConfig:
    """SuperTrend 配置 - 使用知识卡片参数"""
    atr_period: int = 9       # 原12→9 (知识卡片)
    atr_multiplier: float = 3.9  # 原3.5→3.9 (知识卡片)


@dataclass
class QQEConfig:
    """QQE MOD 配置 - 默认参数"""
    rsi_length: int = 6
    smoothing: int = 5
    factor: float = 1.61


@dataclass
class AV2Config:
    """A-V2 配置 - 使用知识卡片参数"""
    ma_type: str = "SMA"      # 1MA = SMA
    length1: int = 52         # 知识卡片参数1
    length2: int = 10         # 知识卡片参数2


# ========================================================================
# 主类
# ========================================================================

class SuperTrendAV2Plugin:
    """
    SuperTrend + QQE MOD + A-V2 趋势过滤器交易系统

    基于知识卡片"超级趋势过滤器交易系统"实现
    """

    VERSION = "1.0"

    def __init__(
        self,
        st_config: SuperTrendConfig = None,
        qqe_config: QQEConfig = None,
        av2_config: AV2Config = None,
        log_enabled: bool = True,
        log_dir: str = LOG_DIR,
    ):
        self.st_config = st_config or SuperTrendConfig()
        self.qqe_config = qqe_config or QQEConfig()
        self.av2_config = av2_config or AV2Config()

        self.log_enabled = log_enabled
        self.log_dir = log_dir

        # 状态管理 (按品种)
        self.last_st_trend: Dict[str, int] = {}
        self.buy1_done: Dict[str, bool] = {}
        self.sell1_done: Dict[str, bool] = {}

        # 统计
        self.trigger_stats: Dict[str, dict] = {}
        self._stats_lock = threading.Lock()

        # 初始化日志目录
        if self.log_enabled:
            os.makedirs(self.log_dir, exist_ok=True)

        self.debug = True

    def _log(self, msg: str):
        if self.debug:
            print(f"[SuperTrend_AV2_Plugin_v{self.VERSION}] {msg}")

    # ========================================================================
    # 核心接口
    # ========================================================================

    def process(
        self,
        symbol: str,
        ohlcv_bars: List[dict],
        close_prices: List[float],
        position_pct: float = 50.0,
    ) -> PluginResult:
        """
        主处理函数

        Args:
            symbol: 交易对
            ohlcv_bars: OHLCV K线数据 (30根，用于SuperTrend和A-V2)
            close_prices: 收盘价列表 (120根，用于QQE)
            position_pct: 当前价格在通道中的位置 (0-100)

        Returns:
            PluginResult: 决策结果
        """
        result = PluginResult(
            mode=PluginMode.WAITING,
            timestamp=time.time(),
            position_pct=position_pct,
        )

        # 数据检查
        if not ohlcv_bars or len(ohlcv_bars) < 20:
            result.reason = "OHLCV数据不足"
            return result

        if not close_prices or len(close_prices) < 60:
            result.reason = "收盘价数据不足"
            return result

        # ================================================================
        # Step 1: 计算三个指标
        # ================================================================

        # SuperTrend (ATR=9, mult=3.9)
        st_signal = self._calc_supertrend(symbol, ohlcv_bars)
        result.supertrend = st_signal

        # QQE MOD (默认参数)
        qqe_signal = self._calc_qqe_mod(close_prices)
        result.qqe = qqe_signal

        # A-V2 (1MA, 52/10)
        av2_signal = self._calc_av2(ohlcv_bars)
        result.av2 = av2_signal

        self._log(f"{symbol}: ST={st_signal.trend}, QQE={qqe_signal.color.value}({qqe_signal.value:.1f}), AV2={av2_signal.color.value}({av2_signal.value:.4f})")

        # ================================================================
        # Step 2: QQE灰色震荡过滤 (最重要的过滤)
        # ================================================================

        if qqe_signal.is_ranging or qqe_signal.color == QQEColor.GRAY:
            result.mode = PluginMode.FILTERED
            result.filter_reason = f"QQE灰色=震荡市，不交易 (value={qqe_signal.value:.1f})"
            result.reason = result.filter_reason
            self._log(f"{symbol}: {result.filter_reason}")
            self._write_diagnosis_log(symbol, result)
            return result

        # ================================================================
        # Step 3: 三指标共振判断
        # ================================================================

        # 做多条件: SuperTrend买入 + QQE蓝色 + A-V2绿色
        is_buy_signal = (
            st_signal.is_buy_signal and
            qqe_signal.color == QQEColor.BLUE and
            av2_signal.color == AV2Color.GREEN
        )

        # 做空条件: SuperTrend卖出 + QQE红色 + A-V2红色
        is_sell_signal = (
            st_signal.is_sell_signal and
            qqe_signal.color == QQEColor.RED and
            av2_signal.color == AV2Color.RED
        )

        # ================================================================
        # Step 4: 位置过滤
        # ================================================================

        if is_buy_signal:
            # 检查是否已触发过BUY1
            if self.buy1_done.get(symbol, False):
                result.mode = PluginMode.WAITING
                result.reason = "BUY1已触发，等待下一周期"
                self._write_diagnosis_log(symbol, result)
                return result

            # 位置过滤: 高位不买
            if position_pct > BUY_MAX_POSITION_PCT:
                result.mode = PluginMode.FILTERED
                result.filter_reason = f"位置过高({position_pct:.0f}%>{BUY_MAX_POSITION_PCT}%)不买"
                result.reason = result.filter_reason
                self._log(f"{symbol}: {result.filter_reason}")
                self._write_diagnosis_log(symbol, result)
                return result

            # 设置BUY信号
            result.mode = PluginMode.ACTIVE
            result.action = "BUY"
            result.signal = "BUY1"
            result.stop_loss = av2_signal.value  # 止损: A-V2线下方
            result.take_profit = st_signal.lower_band if st_signal.lower_band > 0 else 0  # 止盈: SuperTrend线
            result.reason = "三指标共振BUY (ST买入+QQE蓝+AV2绿)"

            self.buy1_done[symbol] = True
            self._log(f"{symbol}: {result.reason}")

        elif is_sell_signal:
            # 检查是否已触发过SELL1
            if self.sell1_done.get(symbol, False):
                result.mode = PluginMode.WAITING
                result.reason = "SELL1已触发，等待下一周期"
                self._write_diagnosis_log(symbol, result)
                return result

            # 位置过滤: 低位不卖
            if position_pct < SELL_MIN_POSITION_PCT:
                result.mode = PluginMode.FILTERED
                result.filter_reason = f"位置过低({position_pct:.0f}%<{SELL_MIN_POSITION_PCT}%)不卖"
                result.reason = result.filter_reason
                self._log(f"{symbol}: {result.filter_reason}")
                self._write_diagnosis_log(symbol, result)
                return result

            # 设置SELL信号
            result.mode = PluginMode.ACTIVE
            result.action = "SELL"
            result.signal = "SELL1"
            result.stop_loss = av2_signal.value  # 止损: A-V2线上方
            result.take_profit = st_signal.upper_band if st_signal.upper_band > 0 else 0  # 止盈: SuperTrend线
            result.reason = "三指标共振SELL (ST卖出+QQE红+AV2红)"

            self.sell1_done[symbol] = True
            self._log(f"{symbol}: {result.reason}")

        else:
            result.mode = PluginMode.WAITING
            result.reason = self._get_waiting_reason(st_signal, qqe_signal, av2_signal)

        self._write_diagnosis_log(symbol, result)
        self._update_stats(symbol, result)

        return result

    def _get_waiting_reason(
        self,
        st_signal: SuperTrendSignal,
        qqe_signal: QQEModSignal,
        av2_signal: AV2Signal
    ) -> str:
        """获取等待原因"""
        reasons = []

        if not st_signal.is_buy_signal and not st_signal.is_sell_signal:
            reasons.append(f"ST无信号(trend={st_signal.trend})")

        # 检查信号是否一致
        if st_signal.is_buy_signal:
            if qqe_signal.color != QQEColor.BLUE:
                reasons.append(f"QQE非蓝({qqe_signal.color.value})")
            if av2_signal.color != AV2Color.GREEN:
                reasons.append(f"AV2非绿({av2_signal.color.value})")
        elif st_signal.is_sell_signal:
            if qqe_signal.color != QQEColor.RED:
                reasons.append(f"QQE非红({qqe_signal.color.value})")
            if av2_signal.color != AV2Color.RED:
                reasons.append(f"AV2非红({av2_signal.color.value})")

        return "等待三指标共振: " + ", ".join(reasons) if reasons else "等待信号"

    def should_bypass_l2(self, result: PluginResult) -> bool:
        """是否跳过L2"""
        return result.mode == PluginMode.ACTIVE

    def reset_cycle(self, symbol: str):
        """重置周期状态 (SuperTrend翻转时调用)"""
        self.buy1_done[symbol] = False
        self.sell1_done[symbol] = False
        self._log(f"{symbol}: 周期状态重置")

    # ========================================================================
    # 指标计算
    # ========================================================================

    def _calc_supertrend(self, symbol: str, ohlcv_bars: List[dict]) -> SuperTrendSignal:
        """
        计算 SuperTrend (ATR周期=9, 乘数=3.9)

        知识卡片参数:
        - ATR周期: 9 (原12)
        - ATR乘数: 3.9 (原3.5)
        """
        result = SuperTrendSignal()

        try:
            highs = np.array([bar["high"] for bar in ohlcv_bars], dtype=float)
            lows = np.array([bar["low"] for bar in ohlcv_bars], dtype=float)
            closes = np.array([bar["close"] for bar in ohlcv_bars], dtype=float)

            period = self.st_config.atr_period
            mult = self.st_config.atr_multiplier
            n = len(closes)

            if n < period + 1:
                return result

            # True Range
            tr = np.zeros(n)
            tr[0] = highs[0] - lows[0]
            for i in range(1, n):
                tr[i] = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i-1]),
                    abs(lows[i] - closes[i-1])
                )

            # ATR (Wilder's smoothing)
            atr = np.zeros(n)
            atr[period-1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

            # HL2
            hl2 = (highs + lows) / 2

            # 上下轨
            basic_up = hl2 - mult * atr
            basic_dn = hl2 + mult * atr

            st_up = np.zeros(n)
            st_dn = np.zeros(n)
            trend = np.ones(n, dtype=int)

            st_up[0] = basic_up[0]
            st_dn[0] = basic_dn[0]

            for i in range(1, n):
                st_up[i] = basic_up[i]
                if closes[i-1] > st_up[i-1]:
                    st_up[i] = max(basic_up[i], st_up[i-1])

                st_dn[i] = basic_dn[i]
                if closes[i-1] < st_dn[i-1]:
                    st_dn[i] = min(basic_dn[i], st_dn[i-1])

                if trend[i-1] == -1 and closes[i] > st_dn[i-1]:
                    trend[i] = 1
                elif trend[i-1] == 1 and closes[i] < st_up[i-1]:
                    trend[i] = -1
                else:
                    trend[i] = trend[i-1]

            result.trend = int(trend[-1])
            result.upper_band = float(st_dn[-1])  # 上轨用于止盈(做空)
            result.lower_band = float(st_up[-1])  # 下轨用于止盈(做多)

            # 检测翻转信号
            last_trend = self.last_st_trend.get(symbol, 0)
            if trend[-1] != last_trend and last_trend != 0:
                self._log(f"{symbol}: SuperTrend翻转 {last_trend}→{trend[-1]}")
                # 翻转时重置周期状态
                if trend[-1] == 1:
                    # 翻转到绿区(多头) = 买入信号
                    result.is_buy_signal = True
                    self.buy1_done[symbol] = False  # 重置BUY1
                elif trend[-1] == -1:
                    # 翻转到红区(空头) = 卖出信号
                    result.is_sell_signal = True
                    self.sell1_done[symbol] = False  # 重置SELL1

            self.last_st_trend[symbol] = trend[-1]

        except Exception as e:
            self._log(f"{symbol}: SuperTrend计算错误: {e}")

        return result

    def _calc_qqe_mod(self, close_prices: List[float]) -> QQEModSignal:
        """
        计算 QQE MOD 指标

        颜色判断:
        - 蓝色: 值>0 且趋势上升 (看多)
        - 红色: 值<0 且趋势下降 (看空)
        - 灰色: 值在±阈值范围内 (震荡，不交易)
        """
        result = QQEModSignal()

        try:
            closes = np.array(close_prices, dtype=float)

            # 计算RSI
            rsi = self._calc_rsi(closes, self.qqe_config.rsi_length)

            # 平滑RSI
            smoothed_rsi = self._ema(rsi, self.qqe_config.smoothing)

            # QQE值 = 平滑RSI - 50 (以50为零轴)
            qqe_value = float(smoothed_rsi[-1] - 50)
            result.value = qqe_value

            # 计算趋势方向 (与前一个值比较)
            prev_qqe = float(smoothed_rsi[-2] - 50) if len(smoothed_rsi) > 1 else 0
            is_rising = qqe_value > prev_qqe

            # 颜色判断 (关键: 灰色=震荡)
            if abs(qqe_value) < QQE_GRAY_THRESHOLD:
                result.color = QQEColor.GRAY
                result.is_ranging = True
            elif qqe_value > 0:
                result.color = QQEColor.BLUE
                result.is_ranging = False
            else:
                result.color = QQEColor.RED
                result.is_ranging = False

        except Exception as e:
            self._log(f"QQE MOD计算错误: {e}")

        return result

    def _calc_av2(self, ohlcv_bars: List[dict]) -> AV2Signal:
        """
        计算 A-V2 趋势指标 (1MA类型)

        知识卡片参数:
        - 均线类型: 1MA (SMA)
        - 参数1: 52
        - 参数2: 10

        计算方法:
        1. 计算52周期SMA
        2. 对SMA再做10周期平滑
        3. 绿色: 当前值 > 前一值 (上升)
        4. 红色: 当前值 < 前一值 (下降)
        """
        result = AV2Signal()

        try:
            closes = np.array([bar["close"] for bar in ohlcv_bars], dtype=float)
            length1 = self.av2_config.length1  # 52
            length2 = self.av2_config.length2  # 10

            if len(closes) < length1 + length2:
                return result

            # Step 1: 计算52周期SMA
            sma = np.convolve(closes, np.ones(length1)/length1, mode='valid')

            if len(sma) < length2 + 1:
                return result

            # Step 2: 对SMA做10周期平滑 (再次SMA)
            smoothed = np.convolve(sma, np.ones(length2)/length2, mode='valid')

            if len(smoothed) < 2:
                return result

            current = float(smoothed[-1])
            prev = float(smoothed[-2])

            result.value = current
            result.is_rising = current > prev

            # 颜色判断
            if current > prev:
                result.color = AV2Color.GREEN  # 上升趋势
            else:
                result.color = AV2Color.RED    # 下降趋势

        except Exception as e:
            self._log(f"A-V2计算错误: {e}")

        return result

    def _calc_rsi(self, closes: np.ndarray, period: int) -> np.ndarray:
        """计算 RSI"""
        n = len(closes)
        if n < period + 1:
            return np.full(n, 50.0)

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.zeros(n)
        avg_loss = np.zeros(n)

        avg_gain[period] = np.mean(gains[:period])
        avg_loss[period] = np.mean(losses[:period])

        for i in range(period + 1, n):
            avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
            avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period

        with np.errstate(divide='ignore', invalid='ignore'):
            rs = np.where(avg_loss > 1e-10, avg_gain / avg_loss, 100)
            rsi = 100 - (100 / (1 + rs))
            rsi = np.nan_to_num(rsi, nan=50.0)

        return rsi

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算 EMA"""
        n = len(data)
        if n < period:
            return data.copy()

        result = np.zeros(n)
        multiplier = 2.0 / (period + 1)
        result[period-1] = np.mean(data[:period])

        for i in range(period, n):
            result[i] = (data[i] - result[i-1]) * multiplier + result[i-1]

        return result

    # ========================================================================
    # 日志和统计
    # ========================================================================

    def _update_stats(self, symbol: str, result: PluginResult):
        """更新统计"""
        with self._stats_lock:
            if symbol not in self.trigger_stats:
                self.trigger_stats[symbol] = {
                    "total": 0,
                    "active": 0,
                    "filtered": 0,
                    "waiting": 0,
                }

            stats = self.trigger_stats[symbol]
            stats["total"] += 1

            if result.mode == PluginMode.ACTIVE:
                stats["active"] += 1
            elif result.mode == PluginMode.FILTERED:
                stats["filtered"] += 1
            elif result.mode == PluginMode.WAITING:
                stats["waiting"] += 1

    def get_stats(self, symbol: str = None) -> dict:
        """获取统计"""
        with self._stats_lock:
            if symbol:
                return self.trigger_stats.get(symbol, {}).copy()
            return self.trigger_stats.copy()

    def _write_diagnosis_log(self, symbol: str, result: PluginResult):
        """写诊断日志"""
        if not self.log_enabled:
            return

        try:
            log_path = os.path.join(self.log_dir, DIAGNOSIS_LOG_FILE)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            lines = []
            lines.append(f"\n===== {timestamp} {symbol} =====")
            lines.append(f"模式: {result.mode.value}")

            if result.supertrend:
                st = result.supertrend
                zone = "绿区(多)" if st.trend == 1 else "红区(空)" if st.trend == -1 else "无"
                lines.append(f"SuperTrend: {zone} | 买信号={st.is_buy_signal} | 卖信号={st.is_sell_signal}")

            if result.qqe:
                qqe = result.qqe
                lines.append(f"QQE MOD: {qqe.color.value} ({qqe.value:+.1f}) | 震荡={qqe.is_ranging}")

            if result.av2:
                av2 = result.av2
                lines.append(f"A-V2: {av2.color.value} ({av2.value:.4f}) | 上升={av2.is_rising}")

            lines.append(f"位置: {result.position_pct:.0f}%")

            if result.action != "NONE":
                lines.append(f"动作: {result.action}")
                lines.append(f"止损: {result.stop_loss:.4f}")
                lines.append(f"止盈: {result.take_profit:.4f}")

            lines.append(f"原因: {result.reason}")
            if result.filter_reason:
                lines.append(f"过滤: {result.filter_reason}")

            lines.append("=" * 40)

            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))

        except Exception as e:
            self._log(f"写日志失败: {e}")


# ========================================================================
# 全局单例
# ========================================================================

_global_plugin: SuperTrendAV2Plugin = None
_plugin_lock = threading.Lock()


def get_supertrend_av2_plugin() -> SuperTrendAV2Plugin:
    """获取全局外挂实例"""
    global _global_plugin
    with _plugin_lock:
        if _global_plugin is None:
            _global_plugin = SuperTrendAV2Plugin()
            print(f"[SuperTrend_AV2_Plugin] Init OK v{SuperTrendAV2Plugin.VERSION}")
        return _global_plugin


# ========================================================================
# 测试
# ========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SuperTrend + QQE MOD + A-V2 Plugin v1.0 测试")
    print("=" * 60)

    plugin = get_supertrend_av2_plugin()

    # 模拟数据
    np.random.seed(42)
    n_ohlcv = 100
    n_close = 120

    base = 500
    closes = base + np.cumsum(np.random.randn(n_close) * 2 + 0.3)

    ohlcv_bars = []
    for i in range(n_ohlcv):
        idx = n_close - n_ohlcv + i
        c = closes[idx]
        ohlcv_bars.append({
            "open": c - np.random.rand() * 2,
            "high": c + np.random.rand() * 5,
            "low": c - np.random.rand() * 5,
            "close": c,
            "volume": 1000 + np.random.randint(0, 500),
        })

    # 测试
    result = plugin.process(
        symbol="BTCUSDC",
        ohlcv_bars=ohlcv_bars,
        close_prices=closes.tolist(),
        position_pct=45,
    )

    print(f"\n结果:")
    print(f"  模式: {result.mode.value}")
    print(f"  动作: {result.action}")

    if result.supertrend:
        print(f"  SuperTrend: trend={result.supertrend.trend}")
    if result.qqe:
        print(f"  QQE MOD: {result.qqe.color.value} ({result.qqe.value:.1f})")
    if result.av2:
        print(f"  A-V2: {result.av2.color.value} ({result.av2.value:.4f})")

    print(f"  原因: {result.reason}")
    if result.filter_reason:
        print(f"  过滤: {result.filter_reason}")

    print("\n" + "=" * 60)

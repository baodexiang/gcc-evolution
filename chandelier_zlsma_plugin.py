# ========================================================================
# Chandelier Exit + ZLSMA 剥头皮策略外挂模块 v1.2
# ========================================================================
#
# 版本: 1.2
# 日期: 2026-01-31
#
# v1.2更新 (2026-01-31):
#   - 新增动态ER阈值支持，从state/er_threshold_state.json读取
#   - 每日8AM自动分析并调整阈值
#
# v1.1更新 (2026-01-31):
#   - 新增KAMA效率比(ER)微观震荡过滤
#   - ER < 0.25 时跳过信号，减少震荡中的假信号
#   - 增强日志输出，显示ER值和过滤原因
#
# 基于知识卡片: 最佳剥头皮指标—Chandelier Exit+ZLSMA
#
# 核心策略:
#   1. 使用Heikin-Ashi K线（平均K线）
#   2. ZLSMA(50) - 零滞后最小二乘移动平均线判断趋势
#   3. Chandelier Exit(ATR=1, mult=2) - 吊灯止损指标触发信号
#   4. KAMA ER过滤 - 效率比<0.25时跳过（微观震荡）
#   5. BUY: CE买入信号 + HA收盘>ZLSMA + 大阳线
#   6. SELL: CE卖出信号 + HA收盘<ZLSMA + 大阴线
#   7. 止损: 关键K线高低点外侧
#   8. 止盈: 1:1.5 盈亏比
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

# v1.1: 导入KAMA效率比计算模块
try:
    from kama_indicator import calculate_efficiency_ratio
    _kama_available = True
except ImportError:
    _kama_available = False
    print("[ChandelierZLSMA] 警告: kama_indicator.py 未找到，KAMA ER过滤禁用")

# v1.2: 导入动态阈值分析器
try:
    from er_threshold_analyzer import get_dynamic_threshold
    _dynamic_threshold_available = True
except ImportError:
    _dynamic_threshold_available = False
    print("[ChandelierZLSMA] 警告: er_threshold_analyzer.py 未找到，使用静态阈值")


# ========================================================================
# 配置常量
# ========================================================================

LOG_DIR = "logs"
SCALPING_LOG_FILE = "chandelier_zlsma.log"

# Chandelier Exit参数 (知识卡片指定)
CE_ATR_PERIOD = 1
CE_ATR_MULTIPLIER = 2.0
CE_LOOKBACK = 22

# ZLSMA参数
ZLSMA_LENGTH = 50

# 关键K线判断
KEY_CANDLE_BODY_PCT = 0.6
MIN_CANDLE_BODY_ATR = 0.5

# 止盈参数
TAKE_PROFIT_RATIO = 1.5

# 位置过滤
BUY_MAX_POSITION_PCT = 80
SELL_MIN_POSITION_PCT = 20

MIN_BARS_FOR_ANALYSIS = 60

# v1.1: KAMA效率比参数
KAMA_ER_PERIOD = 10           # ER计算周期
KAMA_ER_THRESHOLD = 0.25      # 低于此值视为微观震荡
KAMA_ER_ENABLED = True        # 开关 (可运行时关闭)


# ========================================================================
# 枚举和数据类
# ========================================================================

class SignalType(Enum):
    NONE = "NONE"
    BUY = "BUY"
    SELL = "SELL"


class PluginMode(Enum):
    SIGNAL_FOUND = "SIGNAL_FOUND"
    FILTERED = "FILTERED"
    NO_SIGNAL = "NO_SIGNAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class HeikinAshiBar:
    open: float
    high: float
    low: float
    close: float
    timestamp: str = ""

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return self.high - self.low

    @property
    def body_pct(self) -> float:
        if self.range_size == 0:
            return 0
        return self.body_size / self.range_size

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class ScalpingResult:
    mode: PluginMode = PluginMode.NO_SIGNAL
    action: str = "NONE"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_amount: float = 0.0
    zlsma: float = 0.0
    ce_long_stop: float = 0.0
    ce_short_stop: float = 0.0
    ce_direction: int = 0
    atr: float = 0.0
    key_candle_body_pct: float = 0.0
    key_candle_is_bullish: bool = False
    l1_trend: str = ""
    position_pct: float = 0.0
    filter_reason: str = ""
    reason: str = ""
    timestamp: float = 0.0
    atr_period: int = CE_ATR_PERIOD
    atr_multiplier: float = CE_ATR_MULTIPLIER
    zlsma_length: int = ZLSMA_LENGTH
    efficiency_ratio: float = 0.0  # v1.1: KAMA效率比

    def should_execute(self) -> bool:
        return self.mode == PluginMode.SIGNAL_FOUND and self.action in ("BUY", "SELL")


# ========================================================================
# 主类
# ========================================================================

class ChandelierZLSMAPlugin:
    VERSION = "1.2"

    def __init__(
        self,
        ce_atr_period: int = CE_ATR_PERIOD,
        ce_atr_multiplier: float = CE_ATR_MULTIPLIER,
        ce_lookback: int = CE_LOOKBACK,
        zlsma_length: int = ZLSMA_LENGTH,
        key_candle_body_pct: float = KEY_CANDLE_BODY_PCT,
        take_profit_ratio: float = TAKE_PROFIT_RATIO,
        log_enabled: bool = True,
    ):
        self.ce_atr_period = ce_atr_period
        self.ce_atr_multiplier = ce_atr_multiplier
        self.ce_lookback = ce_lookback
        self.zlsma_length = zlsma_length
        self.key_candle_body_pct = key_candle_body_pct
        self.take_profit_ratio = take_profit_ratio
        self.log_enabled = log_enabled

        self.stats = {
            "total_signals": 0,
            "buy_signals": 0,
            "sell_signals": 0,
            "filtered_by_trend": 0,
            "filtered_by_position": 0,
            "filtered_by_zlsma": 0,
            "filtered_by_candle": 0,
            "filtered_by_kama_er": 0,  # v1.1: KAMA ER过滤
            "executed": 0,
        }
        self._stats_lock = threading.Lock()

    def compute_heikin_ashi(self, bars: List[Dict]) -> List[HeikinAshiBar]:
        """计算Heikin-Ashi K线"""
        if not bars:
            return []

        ha_bars = []
        for i, bar in enumerate(bars):
            o = float(bar.get("open", 0))
            h = float(bar.get("high", 0))
            l = float(bar.get("low", 0))
            c = float(bar.get("close", 0))
            ts = bar.get("timestamp", "")

            ha_close = (o + h + l + c) / 4
            if i == 0:
                ha_open = (o + c) / 2
            else:
                ha_open = (ha_bars[i-1].open + ha_bars[i-1].close) / 2

            ha_high = max(h, ha_open, ha_close)
            ha_low = min(l, ha_open, ha_close)

            ha_bars.append(HeikinAshiBar(
                open=ha_open, high=ha_high, low=ha_low, close=ha_close, timestamp=ts
            ))
        return ha_bars

    def _linreg(self, data: np.ndarray, length: int) -> np.ndarray:
        """线性回归移动平均"""
        n = len(data)
        result = np.full(n, np.nan)
        if n < length:
            return result
        for i in range(length - 1, n):
            window = data[i - length + 1:i + 1]
            x = np.arange(length)
            slope, intercept = np.polyfit(x, window, 1)
            result[i] = slope * (length - 1) + intercept
        return result

    def compute_zlsma(self, closes: np.ndarray, length: int = ZLSMA_LENGTH) -> np.ndarray:
        """计算ZLSMA (Zero Lag Smoothed Moving Average)"""
        lsma = self._linreg(closes, length)
        lsma_clean = np.where(np.isnan(lsma), closes, lsma)
        lsma_lsma = self._linreg(lsma_clean, length)
        zlsma = 2 * lsma - lsma_lsma
        return zlsma

    def compute_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
        """计算ATR"""
        n = len(closes)
        tr = np.zeros(n)
        atr = np.zeros(n)

        for i in range(n):
            if i == 0:
                tr[i] = highs[i] - lows[i]
            else:
                tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))

        for i in range(period - 1, n):
            atr[i] = np.mean(tr[i - period + 1:i + 1])
        if period > 1:
            atr[:period-1] = tr[:period-1]
        return atr

    def compute_chandelier_exit(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        atr_period: int, multiplier: float, lookback: int
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """计算Chandelier Exit"""
        n = len(closes)
        atr = self.compute_atr(highs, lows, closes, atr_period)

        long_stop = np.zeros(n)
        short_stop = np.zeros(n)
        direction = np.zeros(n)

        for i in range(lookback, n):
            highest = np.max(highs[i - lookback + 1:i + 1])
            lowest = np.min(lows[i - lookback + 1:i + 1])

            long_stop[i] = highest - atr[i] * multiplier
            short_stop[i] = lowest + atr[i] * multiplier

            if i == lookback:
                direction[i] = 1 if closes[i] > (highest + lowest) / 2 else -1
            else:
                prev_dir = direction[i - 1]
                if prev_dir == 1:
                    if closes[i] < long_stop[i - 1]:
                        direction[i] = -1
                    else:
                        direction[i] = 1
                        long_stop[i] = max(long_stop[i], long_stop[i - 1])
                else:
                    if closes[i] > short_stop[i - 1]:
                        direction[i] = 1
                    else:
                        direction[i] = -1
                        short_stop[i] = min(short_stop[i], short_stop[i - 1])

        buy_signal = np.zeros(n, dtype=bool)
        sell_signal = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if direction[i - 1] != 1 and direction[i] == 1:
                buy_signal[i] = True
            if direction[i - 1] != -1 and direction[i] == -1:
                sell_signal[i] = True

        return long_stop, short_stop, direction, buy_signal, sell_signal

    def is_key_candle(self, ha_bar: HeikinAshiBar, atr: float) -> Tuple[bool, str]:
        """检测关键K线"""
        body_pct = ha_bar.body_pct
        body_size = ha_bar.body_size
        min_body_size = atr * MIN_CANDLE_BODY_ATR

        if body_pct < self.key_candle_body_pct or body_size < min_body_size:
            return False, "NONE"

        if ha_bar.is_bullish:
            return True, "BULLISH"
        elif ha_bar.is_bearish:
            return True, "BEARISH"
        return False, "NONE"

    def process(self, symbol: str, bars: List[Dict], l1_trend: str = "SIDE", position_pct: float = 50.0) -> ScalpingResult:
        """主处理函数"""
        result = ScalpingResult(timestamp=time.time(), l1_trend=l1_trend, position_pct=position_pct)

        if not bars or len(bars) < MIN_BARS_FOR_ANALYSIS:
            result.mode = PluginMode.INSUFFICIENT_DATA
            result.reason = f"K线数据不足: {len(bars) if bars else 0} < {MIN_BARS_FOR_ANALYSIS}"
            return result

        try:
            ha_bars = self.compute_heikin_ashi(bars)
            if not ha_bars:
                result.mode = PluginMode.INSUFFICIENT_DATA
                result.reason = "Heikin-Ashi计算失败"
                return result

            highs = np.array([float(b.get("high", 0)) for b in bars])
            lows = np.array([float(b.get("low", 0)) for b in bars])
            closes = np.array([float(b.get("close", 0)) for b in bars])

            zlsma = self.compute_zlsma(closes, self.zlsma_length)
            current_zlsma = zlsma[-1]
            result.zlsma = current_zlsma

            # === v1.1+v1.2: KAMA效率比过滤 (微观震荡检测) ===
            if KAMA_ER_ENABLED and _kama_available:
                er = calculate_efficiency_ratio(closes, KAMA_ER_PERIOD)
                result.efficiency_ratio = er

                # v1.2: 使用动态阈值
                if _dynamic_threshold_available:
                    er_threshold = get_dynamic_threshold("chandelier")
                else:
                    er_threshold = KAMA_ER_THRESHOLD

                # 详细日志输出 (便于/check监测)
                er_status = "趋势" if er >= er_threshold else "震荡"
                print(f"[Scalping] {symbol} KAMA ER={er:.3f} ({er_status}) 阈值={er_threshold}")

                if er < er_threshold:
                    result.mode = PluginMode.FILTERED
                    result.filter_reason = f"微观震荡(ER={er:.2f}<{er_threshold})"
                    result.reason = f"KAMA效率比过低，短期震荡，跳过信号"
                    with self._stats_lock:
                        self.stats["filtered_by_kama_er"] += 1
                    # 日志输出
                    print(f"[Scalping] {symbol} FILTERED by KAMA ER: {er:.3f} < {er_threshold}")
                    self._log_observation(symbol, result, "KAMA_ER_FILTERED")
                    return result
            # === v1.2 结束 ===

            long_stop, short_stop, direction, buy_signal, sell_signal = self.compute_chandelier_exit(
                highs, lows, closes, self.ce_atr_period, self.ce_atr_multiplier, self.ce_lookback
            )
            result.ce_long_stop = long_stop[-1]
            result.ce_short_stop = short_stop[-1]
            result.ce_direction = int(direction[-1])

            atr = self.compute_atr(highs, lows, closes, self.ce_atr_period)
            current_atr = atr[-1]
            result.atr = current_atr

            current_ha = ha_bars[-1]
            has_buy_signal = buy_signal[-1]
            has_sell_signal = sell_signal[-1]

            is_key, candle_type = self.is_key_candle(current_ha, current_atr)
            result.key_candle_body_pct = current_ha.body_pct
            result.key_candle_is_bullish = current_ha.is_bullish

            signal_type = SignalType.NONE

            if has_buy_signal:
                if current_ha.close > current_zlsma:
                    if is_key and candle_type == "BULLISH":
                        signal_type = SignalType.BUY
                    else:
                        result.filter_reason = f"非关键阳线(body_pct={current_ha.body_pct:.1%})"
                        with self._stats_lock:
                            self.stats["filtered_by_candle"] += 1
                else:
                    result.filter_reason = f"HA收盘({current_ha.close:.2f})<ZLSMA({current_zlsma:.2f})"
                    with self._stats_lock:
                        self.stats["filtered_by_zlsma"] += 1

            elif has_sell_signal:
                if current_ha.close < current_zlsma:
                    if is_key and candle_type == "BEARISH":
                        signal_type = SignalType.SELL
                    else:
                        result.filter_reason = f"非关键阴线(body_pct={current_ha.body_pct:.1%})"
                        with self._stats_lock:
                            self.stats["filtered_by_candle"] += 1
                else:
                    result.filter_reason = f"HA收盘({current_ha.close:.2f})>ZLSMA({current_zlsma:.2f})"
                    with self._stats_lock:
                        self.stats["filtered_by_zlsma"] += 1

            if signal_type == SignalType.NONE:
                if not has_buy_signal and not has_sell_signal:
                    result.mode = PluginMode.NO_SIGNAL
                    result.reason = "无Chandelier Exit信号"
                else:
                    result.mode = PluginMode.FILTERED
                    result.reason = result.filter_reason or "信号条件不满足"
                return result

            # L1趋势过滤
            l1 = l1_trend.upper()
            if l1 == "SIDE":
                result.mode = PluginMode.FILTERED
                result.action = signal_type.value
                result.filter_reason = "L1趋势SIDE，不触发剥头皮"
                result.reason = f"{signal_type.value}信号被L1=SIDE过滤"
                with self._stats_lock:
                    self.stats["filtered_by_trend"] += 1
                return result

            if l1 == "UP" and signal_type == SignalType.SELL:
                result.mode = PluginMode.FILTERED
                result.action = "SELL"
                result.filter_reason = "L1=UP，不允许SELL"
                result.reason = "SELL信号被L1=UP过滤"
                with self._stats_lock:
                    self.stats["filtered_by_trend"] += 1
                return result

            if l1 == "DOWN" and signal_type == SignalType.BUY:
                result.mode = PluginMode.FILTERED
                result.action = "BUY"
                result.filter_reason = "L1=DOWN，不允许BUY"
                result.reason = "BUY信号被L1=DOWN过滤"
                with self._stats_lock:
                    self.stats["filtered_by_trend"] += 1
                return result

            # 位置过滤
            if signal_type == SignalType.BUY and position_pct > BUY_MAX_POSITION_PCT:
                result.mode = PluginMode.FILTERED
                result.action = "BUY"
                result.filter_reason = f"位置过高({position_pct:.1f}%>{BUY_MAX_POSITION_PCT}%)"
                result.reason = "BUY信号被高位过滤"
                with self._stats_lock:
                    self.stats["filtered_by_position"] += 1
                return result

            if signal_type == SignalType.SELL and position_pct < SELL_MIN_POSITION_PCT:
                result.mode = PluginMode.FILTERED
                result.action = "SELL"
                result.filter_reason = f"位置过低({position_pct:.1f}%<{SELL_MIN_POSITION_PCT}%)"
                result.reason = "SELL信号被低位过滤"
                with self._stats_lock:
                    self.stats["filtered_by_position"] += 1
                return result

            # 计算入场价、止损、止盈
            entry_price = closes[-1]
            if signal_type == SignalType.BUY:
                stop_loss = lows[-1] - current_atr
                risk = entry_price - stop_loss
                take_profit = entry_price + risk * self.take_profit_ratio
            else:
                stop_loss = highs[-1] + current_atr
                risk = stop_loss - entry_price
                take_profit = entry_price - risk * self.take_profit_ratio

            result.mode = PluginMode.SIGNAL_FOUND
            result.action = signal_type.value
            result.entry_price = entry_price
            result.stop_loss = stop_loss
            result.take_profit = take_profit
            result.risk_amount = abs(entry_price - stop_loss)
            result.reason = f"CE{signal_type.value}信号 + HA{'阳' if signal_type == SignalType.BUY else '阴'}线(body={current_ha.body_pct:.0%}) + ZLSMA确认"

            with self._stats_lock:
                self.stats["total_signals"] += 1
                if signal_type == SignalType.BUY:
                    self.stats["buy_signals"] += 1
                else:
                    self.stats["sell_signals"] += 1
                self.stats["executed"] += 1

            self._log(symbol, result)
            return result

        except Exception as e:
            result.mode = PluginMode.NO_SIGNAL
            result.reason = f"处理异常: {str(e)}"
            return result

    def _log(self, symbol: str, result: ScalpingResult):
        """记录信号日志"""
        if not self.log_enabled:
            return
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            log_path = os.path.join(LOG_DIR, SCALPING_LOG_FILE)
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "action": result.action,
                "mode": result.mode.value,
                "entry_price": result.entry_price,
                "stop_loss": result.stop_loss,
                "take_profit": result.take_profit,
                "zlsma": result.zlsma,
                "ce_direction": result.ce_direction,
                "atr": result.atr,
                "l1_trend": result.l1_trend,
                "position_pct": result.position_pct,
                "efficiency_ratio": result.efficiency_ratio,  # v1.1
                "reason": result.reason,
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[ChandelierZLSMA] 日志写入失败: {e}")

    def _log_observation(self, symbol: str, result: ScalpingResult, event_type: str):
        """
        v1.1: 记录观察日志 (便于/check监测)

        日志文件: logs/chandelier_zlsma_observation.log
        格式: JSON Lines, 每行一条记录
        """
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            log_path = os.path.join(LOG_DIR, "chandelier_zlsma_observation.log")
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "event_type": event_type,
                "mode": result.mode.value,
                "action": result.action,
                "efficiency_ratio": round(result.efficiency_ratio, 3),
                "kama_er_threshold": KAMA_ER_THRESHOLD,
                "zlsma": round(result.zlsma, 2) if result.zlsma else 0,
                "ce_direction": result.ce_direction,
                "l1_trend": result.l1_trend,
                "position_pct": round(result.position_pct, 1),
                "filter_reason": result.filter_reason,
                "reason": result.reason,
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[ChandelierZLSMA] 观察日志写入失败: {e}")

    def get_stats(self) -> Dict:
        with self._stats_lock:
            return dict(self.stats)


# ========================================================================
# 单例
# ========================================================================

_plugin_instance: Optional[ChandelierZLSMAPlugin] = None
_plugin_lock = threading.Lock()


def get_chandelier_zlsma_plugin() -> ChandelierZLSMAPlugin:
    global _plugin_instance
    if _plugin_instance is None:
        with _plugin_lock:
            if _plugin_instance is None:
                _plugin_instance = ChandelierZLSMAPlugin()
    return _plugin_instance


if __name__ == "__main__":
    print("=" * 60)
    print("Chandelier+ZLSMA Plugin v1.2 loaded")
    print("=" * 60)
    print(f"  KAMA ER过滤: {'启用' if KAMA_ER_ENABLED and _kama_available else '禁用'}")
    if _dynamic_threshold_available:
        threshold = get_dynamic_threshold("chandelier")
        print(f"  ER阈值: {threshold} (动态)")
    else:
        print(f"  ER阈值: {KAMA_ER_THRESHOLD} (静态)")
    print(f"  ER周期: {KAMA_ER_PERIOD}")
    print("=" * 60)

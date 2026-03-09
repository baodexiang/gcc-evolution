# ========================================================================
# Rob Hoffman 冠军策略外挂模块 v2.0
# ========================================================================
#
# 版本: 2.0
# 日期: 2026-02-27
#
# v2.0更新 (2026-02-27):
#   - 核心修正: IRB定义从"实体占比>=50%"改为标准"影线占比>=45%"
#   - 入场改为两根K线模式: 前一根=IRB(影线>=45%), 当前根=突破确认
#   - 新增EMA20趋势过滤 (标准Rob Hoffman方法)
#   - 非完美EMA排列判定从emas[0]vsemas[-1]改为多数票制(3/4)
#   - 移除SELL额外ER门槛 (IRB修正后BUY/SELL自然对称)
#   - 参考: GitHub m-marqx/IRB.APP + TradingView UCSgears/Noski实现
#
# v1.3更新 (2026-01-31):
#   - 新增动态ER阈值支持，从state/er_threshold_state.json读取
#   - 每日8AM自动分析并调整阈值
#
# v1.2更新 (2026-01-31):
#   - 新增KAMA效率比(ER)检测纠缠，替代ATR阈值方法
#   - ER < 0.30 自动判定为震荡市(TANGLED)
#   - 增强日志输出，显示ER值和纠缠判断原因
#
# v1.1更新 (2026-01-25):
#   - 新增扫描引擎接口 (should_activate_for_scan)
#   - 新增 current_trend 参数支持
#   - 适配 price_scan_engine_v15 集成
#
# 基于知识卡片: 实盘国际比赛-冠军交易策略-Rob Hoffman，传奇交易员的23次夺冠
#
# 核心策略:
#   1. 叠加指标: 多条EMA排列检测趋势方向
#   2. 多头排列: 紫色EMA > 绿色EMA > 所有白色EMA → 上升趋势
#   3. 空头排列: 紫色EMA < 绿色EMA < 所有白色EMA → 下降趋势
#   4. 均线纠缠: EMA相互穿插 → 震荡行情，不交易
#   5. 入场信号: 回调到快速EMA后的反转K线
#
# 特性:
#   - 趋势专用外挂，自动过滤震荡行情 (EMA纠缠=震荡)
#   - L1层级，1小时周期
#   - 与SuperTrend、飞云双突破并列
#
# 参数来源 (知识卡片):
#   - 原始周期: 15分钟 (本外挂调整为1小时适配L1)
#   - 固定盈亏比: 1:2
#   - 测试胜率: 62% (BTC/USDT 100次测试)
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
import time

# v1.2: 导入KAMA效率比计算模块
try:
    from kama_indicator import calculate_efficiency_ratio
    _kama_available = True
except ImportError:
    _kama_available = False
    print("[RobHoffman] 警告: kama_indicator.py 未找到，KAMA ER检测禁用")

# v1.3: 导入动态阈值分析器
try:
    from er_threshold_analyzer import get_dynamic_threshold
    _dynamic_threshold_available = True
except ImportError:
    _dynamic_threshold_available = False
    print("[RobHoffman] 警告: er_threshold_analyzer.py 未找到，使用静态阈值")


# ========================================================================
# 配置常量
# ========================================================================

LOG_DIR = "logs"
HOFFMAN_LOG_FILE = "rob_hoffman_plugin.log"

# EMA参数 (基于知识卡片的叠加指标)
EMA_PURPLE = 5       # 紫色EMA (最快)
EMA_GREEN = 13       # 绿色EMA (中速)
EMA_WHITE_1 = 21     # 白色EMA 1 (慢速)
EMA_WHITE_2 = 34     # 白色EMA 2 (更慢)
EMA_WHITE_3 = 55     # 白色EMA 3 (最慢)

# 所有EMA周期列表
ALL_EMA_PERIODS = [EMA_PURPLE, EMA_GREEN, EMA_WHITE_1, EMA_WHITE_2, EMA_WHITE_3]

# 纠缠检测参数
TANGLE_ATR_THRESHOLD = 0.5   # EMA间距小于 ATR * 此值 视为纠缠
MIN_BARS_FOR_ANALYSIS = 60   # 分析所需最小K线数 (需要计算55 EMA)

# 位置过滤 (防止极端位置入场)
BUY1_MAX_POSITION_PCT = 80   # BUY1 位置上限
SELL1_MIN_POSITION_PCT = 20  # SELL1 位置下限

# v2.0: IRB (Inventory Retracement Bar) 参数 — 标准Rob Hoffman定义
# IRB = 影线占K线振幅 >= 45% 的K线 (机构库存回补留下的长影线)
IRB_WICK_PCT = 0.38          # v2.1: 0.45→0.38 dashboard显示22698扫描0触发,45%标准过严
EMA_TREND = 20               # 趋势过滤EMA周期 (标准EMA20)

# v1.2: KAMA效率比参数
KAMA_ER_PERIOD = 10              # ER计算周期
KAMA_ER_TANGLED_THRESHOLD = 0.22 # v2.1: 0.30→0.22 ER阈值过高导致大量信号被判为震荡
# v2.0: SELL额外ER门槛已移除 — IRB修正后BUY/SELL触发条件对称
KAMA_ER_ENABLED = True           # 开关 (可运行时关闭)
DAILY_SIGNAL_CAP = 3             # KEY-006: 每品种每天最大信号数 (BUY+SELL合计)
                                 # 原因: HIMS历史7条/天, 重复信号信噪比低


# ========================================================================
# 枚举定义
# ========================================================================

class TrendAlignment(Enum):
    """EMA排列状态"""
    BULLISH = "BULLISH"       # 多头排列 (紫>绿>白)
    BEARISH = "BEARISH"       # 空头排列 (紫<绿<白)
    TANGLED = "TANGLED"       # 纠缠 (无序)


class HoffmanSignal(Enum):
    """外挂信号类型"""
    BUY1 = "BUY1"             # 做多信号
    SELL1 = "SELL1"          # 做空信号
    NONE = "NONE"             # 无信号


class PluginMode(Enum):
    """外挂工作模式"""
    ACTIVE = "ACTIVE"         # 激活 (趋势明确)
    FILTERED = "FILTERED"     # 过滤 (震荡/纠缠)
    WAITING = "WAITING"       # 等待 (条件未满足)


# ========================================================================
# 数据结构
# ========================================================================

@dataclass
class EMAValues:
    """EMA值集合"""
    purple: float = 0.0       # EMA(5)
    green: float = 0.0        # EMA(13)
    white_1: float = 0.0      # EMA(21)
    white_2: float = 0.0      # EMA(34)
    white_3: float = 0.0      # EMA(55)

    def as_list(self) -> List[float]:
        """返回所有EMA值列表 (从快到慢)"""
        return [self.purple, self.green, self.white_1, self.white_2, self.white_3]


@dataclass
class HoffmanResult:
    """外挂分析结果"""
    signal: HoffmanSignal = HoffmanSignal.NONE
    mode: PluginMode = PluginMode.WAITING
    alignment: TrendAlignment = TrendAlignment.TANGLED
    ema_values: EMAValues = field(default_factory=EMAValues)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    confidence: float = 0.0
    er_value: float = 0.0         # v2.0: KAMA效率比 (供plugin_knn使用)
    reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict:
        return {
            "signal": self.signal.value,
            "mode": self.mode.value,
            "alignment": self.alignment.value,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "confidence": self.confidence,
            "er_value": self.er_value,
            "reason": self.reason,
            "timestamp": self.timestamp
        }


# ========================================================================
# Rob Hoffman 外挂主类
# ========================================================================

class RobHoffmanPlugin:
    """
    Rob Hoffman 冠军策略外挂

    用于L1层级，检测多EMA排列趋势并生成入场信号
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._state_lock = threading.Lock()

        # 状态跟踪 (按symbol)
        self._signal_cache: Dict[str, HoffmanResult] = {}
        self._last_signal_time: Dict[str, datetime] = {}
        self._buy1_done: Dict[str, bool] = {}
        self._sell1_done: Dict[str, bool] = {}
        # KEY-006: 每日信号计数 {symbol: {"date": "YYYY-MM-DD", "count": N}}
        self._daily_signal_count: Dict[str, Dict] = {}

        # 确保日志目录存在
        os.makedirs(LOG_DIR, exist_ok=True)

        self._log(f"Rob Hoffman Plugin v2.0 initialized")

    # ====================================================================
    # 核心方法
    # ====================================================================

    def process(
        self,
        symbol: str,
        bars: List[Dict],
        pos_in_channel: float = 0.5,
        l1_trend: str = "SIDE",
        position_units: int = 0,  # v1.2: 实际持仓数量
    ) -> HoffmanResult:
        """
        处理K线数据，生成交易信号

        Args:
            symbol: 交易标的
            bars: K线数据列表 [{open, high, low, close, volume, timestamp}, ...]
            pos_in_channel: 当前价格在通道中的位置 (0-1)
            l1_trend: L1层判断的趋势 (UP/DOWN/SIDE)
            position_units: 实际持仓数量 (0-5)，用于退出卖出判断

        Returns:
            HoffmanResult: 分析结果
        """
        self._position_units = position_units  # v1.2: 保存持仓供过滤时使用
        result = HoffmanResult(timestamp=datetime.now().isoformat())

        # 检查数据量
        if len(bars) < MIN_BARS_FOR_ANALYSIS:
            result.mode = PluginMode.WAITING
            result.reason = f"Insufficient bars: {len(bars)} < {MIN_BARS_FOR_ANALYSIS}"
            return result

        try:
            # 1. 计算所有EMA
            ema_values = self._calculate_emas(bars)
            result.ema_values = ema_values

            # 2. 检测EMA排列状态
            alignment, er_val = self._detect_alignment(ema_values, bars)
            result.alignment = alignment
            result.er_value = er_val

            # 3. 如果纠缠，过滤不交易
            if alignment == TrendAlignment.TANGLED:
                result.mode = PluginMode.FILTERED
                result.reason = "EMA tangled - ranging market filtered"
                self._log(f"[{symbol}] FILTERED: EMA tangled")
                return result

            # 4. 检测入场信号
            signal, entry_price, confidence, reason = self._detect_entry_signal(
                bars, ema_values, alignment, pos_in_channel
            )

            result.signal = signal
            result.entry_price = entry_price
            result.confidence = confidence
            result.reason = reason

            # 5. 检查是否已执行过
            with self._state_lock:
                if signal == HoffmanSignal.BUY1:
                    if self._buy1_done.get(symbol, False):
                        result.signal = HoffmanSignal.NONE
                        result.reason = "BUY1 already executed, waiting for reset"
                        result.mode = PluginMode.WAITING
                        return result
                elif signal == HoffmanSignal.SELL1:
                    if self._sell1_done.get(symbol, False):
                        result.signal = HoffmanSignal.NONE
                        result.reason = "SELL1 already executed, waiting for reset"
                        result.mode = PluginMode.WAITING
                        return result

            # 6. 位置过滤
            pos_pct = pos_in_channel * 100
            if signal == HoffmanSignal.BUY1 and pos_pct > BUY1_MAX_POSITION_PCT:
                result.signal = HoffmanSignal.NONE
                result.reason = f"BUY1 filtered: position {pos_pct:.0f}% > {BUY1_MAX_POSITION_PCT}%"
                result.mode = PluginMode.FILTERED
                self._log(f"[{symbol}] BUY1 filtered by position")
                return result

            if signal == HoffmanSignal.SELL1 and pos_pct < SELL1_MIN_POSITION_PCT:
                # v1.2: 有持仓时允许退出卖出
                if getattr(self, '_position_units', 0) > 0:
                    self._log(f"[{symbol}] SELL1: 持仓退出模式 (position_units={self._position_units})，跳过位置过滤")
                else:
                    result.signal = HoffmanSignal.NONE
                    result.reason = f"SELL1 filtered: position {pos_pct:.0f}% < {SELL1_MIN_POSITION_PCT}%"
                    result.mode = PluginMode.FILTERED
                    self._log(f"[{symbol}] SELL1 filtered by position")
                    return result

            # v2.0: SELL额外ER门槛已移除 — IRB修正后BUY/SELL触发条件对称

            # 7b. KEY-006: 每日信号上限 (防止同品种重复触发)
            if signal != HoffmanSignal.NONE:
                today = datetime.now().strftime("%Y-%m-%d")
                with self._state_lock:
                    rec = self._daily_signal_count.get(symbol, {})
                    if rec.get("date") != today:
                        rec = {"date": today, "count": 0}
                    if rec["count"] >= DAILY_SIGNAL_CAP:
                        result.signal = HoffmanSignal.NONE
                        result.reason = f"日信号上限({rec['count']}/{DAILY_SIGNAL_CAP}),跳过"
                        result.mode = PluginMode.FILTERED
                        self._log(f"[{symbol}] filtered: daily cap {rec['count']}/{DAILY_SIGNAL_CAP}")
                        self._daily_signal_count[symbol] = rec
                        return result
                    rec["count"] += 1
                    self._daily_signal_count[symbol] = rec

            # 7. 计算止损止盈
            if signal != HoffmanSignal.NONE:
                result.mode = PluginMode.ACTIVE
                atr = self._calculate_atr(bars, 14)

                if signal == HoffmanSignal.BUY1:
                    result.stop_loss = ema_values.green - atr
                    result.take_profit = entry_price + (entry_price - result.stop_loss) * 2
                else:  # SELL1
                    result.stop_loss = ema_values.green + atr
                    result.take_profit = entry_price - (result.stop_loss - entry_price) * 2

                self._log(f"[{symbol}] SIGNAL: {signal.value}, alignment={alignment.value}, "
                         f"entry={entry_price:.2f}, SL={result.stop_loss:.2f}, TP={result.take_profit:.2f}")
            else:
                result.mode = PluginMode.WAITING

            # 缓存结果
            with self._state_lock:
                self._signal_cache[symbol] = result

            return result

        except Exception as e:
            result.mode = PluginMode.WAITING
            result.reason = f"Error: {str(e)}"
            self._log(f"[{symbol}] ERROR: {e}")
            return result

    def mark_executed(self, symbol: str, signal: HoffmanSignal):
        """标记信号已执行"""
        with self._state_lock:
            if signal == HoffmanSignal.BUY1:
                self._buy1_done[symbol] = True
                self._log(f"[{symbol}] BUY1 marked as executed")
            elif signal == HoffmanSignal.SELL1:
                self._sell1_done[symbol] = True
                self._log(f"[{symbol}] SELL1 marked as executed")

    def reset_on_exit(self, symbol: str, exit_type: str):
        """退出时重置状态"""
        with self._state_lock:
            if exit_type in ["EXIT_LONG", "STOP_LOSS_LONG"]:
                self._buy1_done[symbol] = False
                self._log(f"[{symbol}] BUY1 reset after {exit_type}")
            elif exit_type in ["EXIT_SHORT", "STOP_LOSS_SHORT"]:
                self._sell1_done[symbol] = False
                self._log(f"[{symbol}] SELL1 reset after {exit_type}")

    def reset_on_alignment_change(self, symbol: str, new_alignment: TrendAlignment):
        """排列变化时重置状态"""
        with self._state_lock:
            old_result = self._signal_cache.get(symbol)
            if old_result and old_result.alignment != new_alignment:
                self._buy1_done[symbol] = False
                self._sell1_done[symbol] = False
                self._log(f"[{symbol}] Reset on alignment change: {old_result.alignment.value} -> {new_alignment.value}")

    # ====================================================================
    # EMA 计算
    # ====================================================================

    def _calculate_emas(self, bars: List[Dict]) -> EMAValues:
        """计算所有EMA值"""
        closes = np.array([float(bar["close"]) for bar in bars])

        ema_values = EMAValues(
            purple=self._ema(closes, EMA_PURPLE)[-1],
            green=self._ema(closes, EMA_GREEN)[-1],
            white_1=self._ema(closes, EMA_WHITE_1)[-1],
            white_2=self._ema(closes, EMA_WHITE_2)[-1],
            white_3=self._ema(closes, EMA_WHITE_3)[-1]
        )

        return ema_values

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        alpha = 2 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]

        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]

        return ema

    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """计算ATR"""
        if len(bars) < period + 1:
            return 0.0

        trs = []
        for i in range(1, len(bars)):
            high = float(bars[i]["high"])
            low = float(bars[i]["low"])
            prev_close = float(bars[i-1]["close"])

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        if len(trs) < period:
            return np.mean(trs) if trs else 0.0

        return np.mean(trs[-period:])

    # ====================================================================
    # 排列检测
    # ====================================================================

    def _detect_alignment(self, ema_values: EMAValues, bars: List[Dict]) -> Tuple[TrendAlignment, float]:
        """
        检测EMA排列状态 - v1.2+v1.3: 使用KAMA效率比检测纠缠 (动态阈值)

        多头排列: 紫色 > 绿色 > 白色1 > 白色2 > 白色3
        空头排列: 紫色 < 绿色 < 白色1 < 白色2 < 白色3
        纠缠: ER < 阈值 或 EMA无序
        """
        emas = ema_values.as_list()
        er_out = 0.0  # v2.0: 记录ER值供外部使用

        # === v1.2+v1.3: 先用KAMA ER判断是否震荡 (动态阈值) ===
        if KAMA_ER_ENABLED and _kama_available:
            closes = np.array([float(bar["close"]) for bar in bars])
            er = calculate_efficiency_ratio(closes, KAMA_ER_PERIOD)
            er_out = er

            # v1.3: 使用动态阈值
            if _dynamic_threshold_available:
                er_threshold = get_dynamic_threshold("hoffman")
            else:
                er_threshold = KAMA_ER_TANGLED_THRESHOLD

            # 详细日志输出 (便于/check监测)
            er_status = "趋势" if er >= er_threshold else "震荡"
            self._log(f"KAMA ER={er:.3f} ({er_status}) 阈值={er_threshold}")

            if er < er_threshold:
                self._log(f"KAMA ER={er:.3f} < {er_threshold}, 判定为震荡市(TANGLED)")
                return TrendAlignment.TANGLED, er_out
        # === v1.3 结束 ===

        # 检查是否完美多头排列
        is_bullish = all(emas[i] > emas[i+1] for i in range(len(emas)-1))
        if is_bullish:
            self._log(f"EMA完美多头排列: {[f'{e:.2f}' for e in emas]}")
            return TrendAlignment.BULLISH, er_out

        # 检查是否完美空头排列
        is_bearish = all(emas[i] < emas[i+1] for i in range(len(emas)-1))
        if is_bearish:
            self._log(f"EMA完美空头排列: {[f'{e:.2f}' for e in emas]}")
            return TrendAlignment.BEARISH, er_out

        # v2.0: 非完美排列用多数票判定 (4对相邻EMA中>=3对保持顺序)
        # 防止短期回调(EMA5跌破EMA55)误判为BEARISH
        bullish_pairs = sum(1 for i in range(len(emas)-1) if emas[i] > emas[i+1])
        if bullish_pairs >= 3:
            self._log(f"EMA多数票多头({bullish_pairs}/4): {[f'{e:.2f}' for e in emas]}")
            return TrendAlignment.BULLISH, er_out
        elif bullish_pairs <= 1:
            self._log(f"EMA多数票空头({bullish_pairs}/4): {[f'{e:.2f}' for e in emas]}")
            return TrendAlignment.BEARISH, er_out

        # bullish_pairs == 2: 真正纠缠 (2对多头2对空头)
        self._log(f"EMA纠缠({bullish_pairs}/4): {[f'{e:.2f}' for e in emas]}")
        return TrendAlignment.TANGLED, er_out

    # ====================================================================
    # 入场信号检测
    # ====================================================================

    def _detect_entry_signal(
        self,
        bars: List[Dict],
        ema_values: EMAValues,
        alignment: TrendAlignment,
        pos_in_channel: float
    ) -> Tuple[HoffmanSignal, float, float, str]:
        """
        v2.0: 标准IRB (Inventory Retracement Bar) 两根K线入场

        IRB定义: 影线占K线振幅 >= 45%，代表机构库存回补(逆势挂单被吃掉)
        入场: IRB出现后的下一根K线突破IRB高/低点

        做多条件:
        1. 多头排列
        2. 前一根K线 = 多头IRB (上影线 >= 45%振幅, 机构在高位回补卖出)
        3. 当前K线收盘 > 前一根K线高点 (突破确认)
        4. 价格在EMA20上方

        做空条件:
        1. 空头排列
        2. 前一根K线 = 空头IRB (下影线 >= 45%振幅, 机构在低位回补买入)
        3. 当前K线收盘 < 前一根K线低点 (突破确认)
        4. 价格在EMA20下方

        Returns:
            (signal, entry_price, confidence, reason)
        """
        if len(bars) < 3:
            return HoffmanSignal.NONE, 0.0, 0.0, "Insufficient bars"

        current_bar = bars[-1]
        prev_bar = bars[-2]

        # 当前K线
        cur_close = float(current_bar["close"])

        # 前一根K线 (IRB候选)
        prev_open = float(prev_bar["open"])
        prev_high = float(prev_bar["high"])
        prev_low = float(prev_bar["low"])
        prev_close = float(prev_bar["close"])
        prev_range = prev_high - prev_low

        if prev_range <= 0:
            return HoffmanSignal.NONE, 0.0, 0.0, "Prev bar zero range"

        # 计算前一根K线的影线占比
        prev_upper_wick = prev_high - max(prev_open, prev_close)
        prev_lower_wick = min(prev_open, prev_close) - prev_low
        prev_upper_wick_pct = prev_upper_wick / prev_range
        prev_lower_wick_pct = prev_lower_wick / prev_range

        # EMA20趋势过滤
        closes = np.array([float(bar["close"]) for bar in bars])
        ema20 = self._ema(closes, EMA_TREND)[-1]

        # ============ 做多信号 (多头IRB + 突破确认) ============
        if alignment == TrendAlignment.BULLISH:
            # 多头IRB: 上影线 >= 45% (机构在高位回补卖出，但趋势仍向上)
            is_bullish_irb = prev_upper_wick_pct >= IRB_WICK_PCT

            if is_bullish_irb and cur_close > prev_high and cur_close > ema20:
                confidence = self._calculate_confidence(
                    alignment, prev_upper_wick_pct * 100, True, pos_in_channel, "BUY"
                )
                reason = (f"Bullish IRB(上影线{prev_upper_wick_pct:.0%}) + "
                         f"突破前高{prev_high:.2f} + EMA20={ema20:.2f}")
                return HoffmanSignal.BUY1, cur_close, confidence, reason

        # ============ 做空信号 (空头IRB + 突破确认) ============
        elif alignment == TrendAlignment.BEARISH:
            # 空头IRB: 下影线 >= 45% (机构在低位回补买入，但趋势仍向下)
            is_bearish_irb = prev_lower_wick_pct >= IRB_WICK_PCT

            if is_bearish_irb and cur_close < prev_low and cur_close < ema20:
                confidence = self._calculate_confidence(
                    alignment, prev_lower_wick_pct * 100, True, pos_in_channel, "SELL"
                )
                reason = (f"Bearish IRB(下影线{prev_lower_wick_pct:.0%}) + "
                         f"跌破前低{prev_low:.2f} + EMA20={ema20:.2f}")
                return HoffmanSignal.SELL1, cur_close, confidence, reason

        return HoffmanSignal.NONE, 0.0, 0.0, "No valid IRB entry signal"

    def _calculate_confidence(
        self,
        alignment: TrendAlignment,
        wick_pct: float,
        irb_confirmed: bool,
        pos_in_channel: float,
        direction: str
    ) -> float:
        """计算信号置信度 (0-1)

        Args:
            wick_pct: IRB影线占比 (0-100)
            irb_confirmed: IRB+突破确认是否成立
        """
        confidence = 0.5  # 基础分

        # 排列清晰度 (+0.2)
        confidence += 0.2

        # v2.0: IRB影线强度 (+0.15) — wick越长信号越强
        if wick_pct >= 60:
            confidence += 0.15
        elif wick_pct >= 50:
            confidence += 0.10

        # IRB+突破确认 (+0.1)
        if irb_confirmed:
            confidence += 0.1

        # 位置合理性 (+0.05)
        if direction == "BUY" and pos_in_channel < 0.5:
            confidence += 0.05
        elif direction == "SELL" and pos_in_channel > 0.5:
            confidence += 0.05

        return min(confidence, 1.0)

    # ====================================================================
    # 日志
    # ====================================================================

    def _log(self, message: str):
        """写入日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"

        try:
            log_path = os.path.join(LOG_DIR, HOFFMAN_LOG_FILE)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception:
            pass

    def _log_observation(self, symbol: str, event_type: str, details: Dict):
        """
        v1.2: 记录观察日志 (便于/check监测)

        日志文件: logs/rob_hoffman_observation.log
        格式: JSON Lines, 每行一条记录
        """
        try:
            log_path = os.path.join(LOG_DIR, "rob_hoffman_observation.log")
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "event_type": event_type,
                **details
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ====================================================================
    # v1.1: 扫描引擎接口
    # ====================================================================

    def should_activate_for_scan(self, result: 'HoffmanResult') -> bool:
        """
        v1.1: 扫描引擎判断是否激活外挂

        Returns:
            True if BUY1/SELL1 signal and mode is ACTIVE
        """
        if result is None:
            return False
        return (
            result.signal in (HoffmanSignal.BUY1, HoffmanSignal.SELL1) and
            result.mode == PluginMode.ACTIVE
        )

    def get_action_for_scan(self, result: 'HoffmanResult') -> str:
        """
        v1.1: 获取扫描引擎动作

        Returns:
            "BUY" / "SELL" / "NONE"
        """
        if result is None or result.signal == HoffmanSignal.NONE:
            return "NONE"
        if result.signal == HoffmanSignal.BUY1:
            return "BUY"
        if result.signal == HoffmanSignal.SELL1:
            return "SELL"
        return "NONE"

    def process_for_scan(
        self,
        symbol: str,
        ohlcv_bars: List[Dict],
        current_trend: str = "SIDE",
        pos_in_channel: float = 0.5,
        position_units: int = 0,  # v1.2: 实际持仓数量
    ) -> 'HoffmanResult':
        """
        v1.1: 扫描引擎专用处理接口
        v1.2: 添加position_units支持持仓退出

        与 process() 相同，但参数名与其他外挂统一

        Args:
            symbol: 交易标的
            ohlcv_bars: K线数据 (1小时周期)
            current_trend: L1当前周期趋势 (UP/DOWN/SIDE)
            pos_in_channel: 位置 (0-1)
            position_units: 实际持仓数量 (0-5)

        Returns:
            HoffmanResult
        """
        return self.process(
            symbol=symbol,
            bars=ohlcv_bars,
            pos_in_channel=pos_in_channel,
            l1_trend=current_trend,
            position_units=position_units,
        )


# ========================================================================
# 单例获取函数
# ========================================================================

_plugin_instance: Optional[RobHoffmanPlugin] = None
_plugin_lock = threading.Lock()

def get_rob_hoffman_plugin() -> RobHoffmanPlugin:
    """获取 Rob Hoffman 外挂单例"""
    global _plugin_instance
    if _plugin_instance is None:
        with _plugin_lock:
            if _plugin_instance is None:
                _plugin_instance = RobHoffmanPlugin()
    return _plugin_instance


# ========================================================================
# 便捷函数
# ========================================================================

def check_hoffman_signal(
    symbol: str,
    bars: List[Dict],
    pos_in_channel: float = 0.5,
    l1_trend: str = "SIDE"
) -> Dict:
    """
    便捷函数：检查 Rob Hoffman 信号

    Args:
        symbol: 交易标的
        bars: K线数据
        pos_in_channel: 位置 (0-1)
        l1_trend: L1趋势

    Returns:
        dict: 包含 signal, mode, alignment, entry_price 等
    """
    plugin = get_rob_hoffman_plugin()
    result = plugin.process(symbol, bars, pos_in_channel, l1_trend)
    return result.to_dict()


# ========================================================================
# 测试入口
# ========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Rob Hoffman Plugin v2.0 loaded (IRB标准修正)")
    print("=" * 60)
    print(f"  KAMA ER检测: {'启用' if KAMA_ER_ENABLED and _kama_available else '禁用'}")
    if _dynamic_threshold_available:
        threshold = get_dynamic_threshold("hoffman")
        print(f"  ER纠缠阈值: {threshold} (动态)")
    else:
        print(f"  ER纠缠阈值: {KAMA_ER_TANGLED_THRESHOLD} (静态)")
    print(f"  ER周期: {KAMA_ER_PERIOD}")
    print("=" * 60)

    # 测试数据 (模拟上升趋势)
    test_bars = []
    base_price = 100.0

    for i in range(100):
        # 模拟上升趋势
        trend = i * 0.5
        noise = np.random.uniform(-1, 1)

        open_p = base_price + trend + noise
        close_p = open_p + np.random.uniform(0, 2)  # 阳线为主
        high_p = max(open_p, close_p) + np.random.uniform(0, 0.5)
        low_p = min(open_p, close_p) - np.random.uniform(0, 0.5)

        test_bars.append({
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": np.random.uniform(1000, 5000),
            "timestamp": datetime.now().isoformat()
        })

    # 测试
    print("\n测试: 模拟上升趋势数据")
    result = check_hoffman_signal("TEST", test_bars, pos_in_channel=0.4)
    print(f"Test Result: {json.dumps(result, indent=2)}")

# ========================================================================
# MACD背离策略外挂模块 v0.4
# ========================================================================
#
# 版本: 0.4
# 日期: 2026-01-25
#
# v0.4更新 (2026-01-25):
#   - 添加每日买卖限制: 买1次+卖1次后冻结到次日8AM (纽约时间)
#   - 保持10分钟周期不变
#   - L2层级外挂，不接入扫描引擎，保留在llm_server中调用
#   - 配合 llm_server_v3545 使用
#
# v0.3更新 (2026-01-25):
#   - 保持10分钟周期不变 (用户要求)
#   - L2层级外挂，不接入扫描引擎，保留在llm_server中调用
#   - 配合 llm_server_v3545 使用
#
# v0.2更新 (2026-01-23):
#   - 修正趋势过滤逻辑：移除错误的趋势方向过滤
#   - 背离是逆趋势策略，不应该用趋势过滤阻止信号
#   - 保留位置过滤（80%/20%）作为主要过滤条件
#
# 基于知识卡片: 93%胜率MACD背离策略（半木夏）
#
# 核心策略:
#   1. MACD(13,34,9) 背离检测
#   2. 底背离: 价格创新低 + MACD柱状图波峰升高 → BUY
#   3. 顶背离: 价格创新高 + MACD柱状图波峰降低 → SELL
#   4. 关键K线: MACD柱子从深色变浅色的第一根
#   5. 止损: 关键K线高低点 ± ATR(13)
#   6. 止盈: 1:1.5 盈亏比
#
# 特性:
#   - 绕过L2 Gate限制，不需要大周期STRONG信号
#   - 位置过滤: 底背离<80%才买, 顶背离>20%才卖
#   - 背离强度过滤: 波峰高度差 >= 30%
#   - v0.2: 移除趋势方向过滤（背离是逆趋势策略，抓反转用）
#   - v0.3: 保持10分钟周期
#
# ========================================================================

import numpy as np
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
import pytz


# ========================================================================
# 配置常量
# ========================================================================

LOG_DIR = "logs"
DIVERGENCE_LOG_FILE = "macd_divergence.log"

# MACD参数 (知识卡片指定)
MACD_FAST = 13
MACD_SLOW = 34
MACD_SIGNAL = 9

# ATR参数 (知识卡片指定)
ATR_PERIOD = 13
ATR_MULTIPLIER = 1.0

# 过滤参数
MIN_DIVERGENCE_PCT = 40      # 背离高度差最小阈值 (%) — KEY-006: 从30提高到40, 过滤底部24%弱信号
MIN_SWING_BARS = 5           # swing点之间最小K线数
MAX_SWING_BARS = 50          # swing点之间最大K线数
MIN_BARS_FOR_ANALYSIS = 50   # 分析所需最小K线数

# 止盈参数
TAKE_PROFIT_RATIO = 1.5      # 盈亏比 1:1.5

# 位置过滤
BUY_MAX_POSITION_PCT = 80    # 买入位置上限
SELL_MIN_POSITION_PCT = 20   # 卖出位置下限

# v0.4: 每日限制状态文件
MACD_DAILY_STATE_FILE = "macd_daily_state.json"


# ========================================================================
# v0.4: 纽约时间辅助函数
# ========================================================================

def get_ny_now() -> datetime:
    """获取纽约当前时间"""
    return datetime.now(pytz.timezone('America/New_York'))


def get_today_date_ny() -> str:
    """获取纽约时间今天的日期字符串 YYYY-MM-DD"""
    return get_ny_now().strftime("%Y-%m-%d")


def get_next_8am_ny() -> datetime:
    """获取下一个纽约时间8AM"""
    now = get_ny_now()
    today_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)

    if now < today_8am:
        return today_8am
    else:
        return today_8am + timedelta(days=1)


# ========================================================================
# 枚举定义
# ========================================================================

class DivergenceType(Enum):
    """背离类型"""
    NONE = "NONE"
    BULLISH = "BULLISH"      # 底背离 (看涨)
    BEARISH = "BEARISH"      # 顶背离 (看跌)


class PluginMode(Enum):
    """外挂工作模式"""
    SIGNAL_FOUND = "SIGNAL_FOUND"       # 检测到背离信号
    FILTERED = "FILTERED"               # 被过滤
    NO_SIGNAL = "NO_SIGNAL"             # 无信号
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # 数据不足


# ========================================================================
# 数据类
# ========================================================================

@dataclass
class SwingPoint:
    """Swing点（波峰/波谷）"""
    index: int              # K线索引
    price: float            # 价格
    macd_hist: float        # 对应MACD柱状图值
    is_high: bool           # True=波峰, False=波谷


@dataclass
class DivergenceSignal:
    """背离信号"""
    div_type: DivergenceType = DivergenceType.NONE
    strength_pct: float = 0.0       # 背离强度 (波峰高度差百分比)
    swing_count: int = 0            # 背离次数 (2=双重背离, 3=三重背离)
    key_candle_idx: int = -1        # 关键K线索引
    debug_info: str = ""            # v3.610: 诊断信息

    # 价格swing点
    price_swings: List[SwingPoint] = field(default_factory=list)
    # MACD swing点
    macd_swings: List[SwingPoint] = field(default_factory=list)


@dataclass
class DivergenceResult:
    """外挂决策结果"""
    mode: PluginMode = PluginMode.NO_SIGNAL
    action: str = "NONE"              # BUY / SELL / NONE

    # 背离信息
    divergence: DivergenceSignal = None

    # 交易参数
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_amount: float = 0.0

    # 指标值
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    atr: float = 0.0

    # 过滤信息
    l1_trend: str = ""
    position_pct: float = 0.0
    filter_reason: str = ""

    reason: str = ""
    timestamp: float = 0.0

    def should_execute(self) -> bool:
        """是否应该执行交易"""
        return self.mode == PluginMode.SIGNAL_FOUND and self.action in ("BUY", "SELL")

    def has_signal(self) -> bool:
        """是否有信号（包括被过滤的）"""
        return self.divergence is not None and self.divergence.div_type != DivergenceType.NONE


# ========================================================================
# 主类
# ========================================================================

class MACDDivergencePlugin:
    """
    MACD背离策略外挂

    基于知识卡片的93%胜率策略:
    - MACD(13,34,9)背离检测
    - L1趋势过滤
    - ATR止损
    - 1:1.5盈亏比止盈
    """

    VERSION = "0.4"

    def __init__(
        self,
        macd_fast: int = MACD_FAST,
        macd_slow: int = MACD_SLOW,
        macd_signal: int = MACD_SIGNAL,
        atr_period: int = ATR_PERIOD,
        atr_multiplier: float = ATR_MULTIPLIER,
        min_divergence_pct: float = MIN_DIVERGENCE_PCT,
        min_swing_bars: int = MIN_SWING_BARS,
        log_enabled: bool = True,
        log_dir: str = LOG_DIR,
    ):
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.min_divergence_pct = min_divergence_pct
        self.min_swing_bars = min_swing_bars

        self.log_enabled = log_enabled
        self.log_dir = log_dir

        # 统计
        self.stats = {
            "total_signals": 0,
            "bullish_signals": 0,
            "bearish_signals": 0,
            "filtered_by_trend": 0,
            "filtered_by_position": 0,
            "filtered_by_strength": 0,
            "filtered_by_daily_limit": 0,  # v0.4
            "executed": 0,
        }
        self._stats_lock = threading.Lock()

        # 信号缓存 (避免重复触发)
        self.last_signal: Dict[str, dict] = {}

        self.debug = True

        # v0.4: 每日状态 {symbol: {buy_used, sell_used, reset_date, freeze_until}}
        self.daily_state: Dict[str, dict] = {}
        self._daily_state_lock = threading.RLock()
        self._load_daily_state()

        # 初始化日志目录
        if self.log_enabled:
            os.makedirs(self.log_dir, exist_ok=True)

    def _log(self, msg: str):
        if self.debug:
            print(f"[MACD_Div_v{self.VERSION}] {msg}")

    # ========================================================================
    # v0.4: 每日限制管理
    # ========================================================================

    def _load_daily_state(self):
        """加载每日状态"""
        state_path = os.path.join(self.log_dir, MACD_DAILY_STATE_FILE)
        try:
            if os.path.exists(state_path):
                with open(state_path, 'r', encoding='utf-8') as f:
                    self.daily_state = json.load(f)
                self._log(f"加载每日状态: {len(self.daily_state)} 个币种")
        except Exception as e:
            self._log(f"加载每日状态失败: {e}")
            self.daily_state = {}

    def _save_daily_state(self):
        """保存每日状态"""
        state_path = os.path.join(self.log_dir, MACD_DAILY_STATE_FILE)
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(self.daily_state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._log(f"保存每日状态失败: {e}")

    def _get_symbol_state(self, symbol: str) -> dict:
        """获取币种的每日状态"""
        with self._daily_state_lock:
            if symbol not in self.daily_state:
                self.daily_state[symbol] = {
                    "buy_used": False,
                    "sell_used": False,
                    "reset_date": None,
                    "freeze_until": None,
                }
            return self.daily_state[symbol]

    def _check_daily_limit(self, symbol: str, action: str) -> Tuple[bool, str]:
        """
        v0.4: 检查每日买卖限制

        规则:
        - 每天允许买1次+卖1次
        - 只有买卖都用完后才冻结到次日8AM
        - 单独买或卖不冻结

        Returns:
            (can_trade: bool, reason: str)
        """
        with self._daily_state_lock:
            state = self._get_symbol_state(symbol)
            today = get_today_date_ny()
            now = get_ny_now()

            # 检查是否需要重置 (新的一天)
            if state.get("reset_date") != today:
                # 检查冻结是否解除
                freeze_until = state.get("freeze_until")
                if freeze_until:
                    freeze_time = datetime.fromisoformat(freeze_until)
                    if freeze_time.tzinfo is None:
                        freeze_time = pytz.timezone('America/New_York').localize(freeze_time)
                    if now < freeze_time:
                        remaining = freeze_time - now
                        hours = remaining.total_seconds() / 3600
                        return False, f"冻结中 (剩余 {hours:.1f}h, 至{freeze_time.strftime('%H:%M')})"

                # 重置状态
                state["buy_used"] = False
                state["sell_used"] = False
                state["reset_date"] = today
                state["freeze_until"] = None
                self._save_daily_state()
                self._log(f"{symbol} 每日状态已重置")

            # 检查冻结
            freeze_until = state.get("freeze_until")
            if freeze_until:
                freeze_time = datetime.fromisoformat(freeze_until)
                if freeze_time.tzinfo is None:
                    freeze_time = pytz.timezone('America/New_York').localize(freeze_time)
                if now < freeze_time:
                    remaining = freeze_time - now
                    hours = remaining.total_seconds() / 3600
                    return False, f"冻结中 (剩余 {hours:.1f}h, 至{freeze_time.strftime('%H:%M')})"

            # 检查该方向是否已用完
            if action == "BUY" and state.get("buy_used"):
                return False, "今日买入额度已用"
            if action == "SELL" and state.get("sell_used"):
                return False, "今日卖出额度已用"

            return True, ""

    def _update_daily_state(self, symbol: str, action: str) -> str:
        """
        v0.4: 更新每日状态

        - 记录买卖使用情况
        - 买卖都用完后设置冻结到次日8AM

        Returns:
            状态描述字符串
        """
        with self._daily_state_lock:
            state = self._get_symbol_state(symbol)

            # 标记使用
            if action == "BUY":
                state["buy_used"] = True
            elif action == "SELL":
                state["sell_used"] = True

            state["reset_date"] = get_today_date_ny()

            # 检查是否需要冻结 (买卖都用完)
            if state.get("buy_used") and state.get("sell_used"):
                next_8am = get_next_8am_ny()
                state["freeze_until"] = next_8am.isoformat()
                self._save_daily_state()
                return f"买[✓] 卖[✓] → 冻结至{next_8am.strftime('%m/%d %H:%M')}"
            else:
                self._save_daily_state()
                buy_mark = "✓" if state.get("buy_used") else "○"
                sell_mark = "✓" if state.get("sell_used") else "○"
                return f"买[{buy_mark}] 卖[{sell_mark}]"

    # ========================================================================
    # 核心接口
    # ========================================================================

    def process(
        self,
        symbol: str,
        bars: List[dict],
        l1_trend: str = "SIDE",
        position_pct: float = 50.0,
        position_units: int = 0,  # v1.1: 实际持仓数量
        min_swing_bars: int = None,        # v3.610: 可覆盖swing判定
        min_divergence_pct: float = None,  # v3.610: 可覆盖强度阈值
    ) -> DivergenceResult:
        """
        主处理函数

        Args:
            symbol: 交易对
            bars: K线数据 [{open, high, low, close, volume}, ...]
            l1_trend: L1大周期趋势 (UP/DOWN/SIDE)
            position_pct: 价格在通道中的位置 (0-100)
            position_units: 实际持仓数量 (0-5)，用于退出卖出判断

        Returns:
            DivergenceResult: 决策结果
        """
        self._position_units = position_units  # v1.1: 保存持仓供过滤时使用
        _swing_bars = min_swing_bars if min_swing_bars is not None else self.min_swing_bars
        _div_pct = min_divergence_pct if min_divergence_pct is not None else self.min_divergence_pct
        result = DivergenceResult(
            mode=PluginMode.NO_SIGNAL,
            l1_trend=l1_trend,
            position_pct=position_pct,
            timestamp=time.time(),
        )

        # ================================================================
        # Step 1: 数据检查
        # ================================================================
        if not bars or len(bars) < MIN_BARS_FOR_ANALYSIS:
            result.mode = PluginMode.INSUFFICIENT_DATA
            result.reason = f"数据不足: {len(bars) if bars else 0} < {MIN_BARS_FOR_ANALYSIS}"
            return result

        # ================================================================
        # Step 2: 计算指标
        # ================================================================
        closes = np.array([bar["close"] for bar in bars], dtype=float)
        highs = np.array([bar["high"] for bar in bars], dtype=float)
        lows = np.array([bar["low"] for bar in bars], dtype=float)

        macd_line, macd_signal_line, macd_hist = self._calc_macd(closes)
        atr = self._calc_atr(highs, lows, closes)

        result.macd_line = macd_line[-1]
        result.macd_signal = macd_signal_line[-1]
        result.macd_hist = macd_hist[-1]
        result.atr = atr[-1]

        # ================================================================
        # Step 3: 检测背离
        # ================================================================
        divergence = self._detect_divergence(closes, highs, lows, macd_hist, min_swing_bars=_swing_bars)
        result.divergence = divergence

        if divergence.div_type == DivergenceType.NONE:
            _dbg = getattr(divergence, 'debug_info', '')
            result.mode = PluginMode.NO_SIGNAL
            result.reason = f"未检测到背离 ({_dbg})" if _dbg else "未检测到背离"
            return result

        # ================================================================
        # Step 3.5 (v0.4): 每日限制检查
        # ================================================================
        # 确定动作方向
        pending_action = "BUY" if divergence.div_type == DivergenceType.BULLISH else "SELL"
        can_trade, limit_reason = self._check_daily_limit(symbol, pending_action)
        if not can_trade:
            result.mode = PluginMode.FILTERED
            result.filter_reason = f"每日限制: {limit_reason}"
            result.reason = result.filter_reason
            self._update_stats("filtered_by_daily_limit")
            self._log(f"{symbol}: MACD背离 {pending_action} 被限制 - {limit_reason}")
            return result

        # ================================================================
        # Step 4: 背离强度过滤
        # ================================================================
        if divergence.strength_pct < _div_pct:
            result.mode = PluginMode.FILTERED
            result.filter_reason = f"背离强度不足: {divergence.strength_pct:.1f}% < {_div_pct}%"
            result.reason = result.filter_reason
            self._update_stats("filtered_by_strength")
            self._write_log(symbol, result)
            return result

        # ================================================================
        # Step 5: L1趋势过滤
        # ================================================================
        filter_result = self._apply_trend_filter(divergence.div_type, l1_trend, position_pct)
        if filter_result:
            result.mode = PluginMode.FILTERED
            result.filter_reason = filter_result
            result.reason = filter_result
            self._update_stats("filtered_by_trend")
            self._write_log(symbol, result)
            return result

        # ================================================================
        # Step 6: 位置过滤
        # ================================================================
        if divergence.div_type == DivergenceType.BULLISH and position_pct > BUY_MAX_POSITION_PCT:
            result.mode = PluginMode.FILTERED
            result.filter_reason = f"位置过高不买: {position_pct:.0f}% > {BUY_MAX_POSITION_PCT}%"
            result.reason = result.filter_reason
            self._update_stats("filtered_by_position")
            self._write_log(symbol, result)
            return result

        if divergence.div_type == DivergenceType.BEARISH and position_pct < SELL_MIN_POSITION_PCT:
            # v1.1: 有持仓时允许退出卖出
            if getattr(self, '_position_units', 0) > 0:
                self._log(f"[{symbol}] SELL: 持仓退出模式 (position_units={self._position_units})，跳过位置过滤")
            else:
                result.mode = PluginMode.FILTERED
                result.filter_reason = f"位置过低不卖: {position_pct:.0f}% < {SELL_MIN_POSITION_PCT}%"
                result.reason = result.filter_reason
                self._update_stats("filtered_by_position")
                self._write_log(symbol, result)
                return result

        # ================================================================
        # Step 7: 检测关键K线
        # ================================================================
        key_candle_idx = self._find_key_candle(macd_hist, divergence.div_type)
        if key_candle_idx < 0:
            result.mode = PluginMode.FILTERED
            result.filter_reason = "未检测到关键K线"
            result.reason = result.filter_reason
            self._write_log(symbol, result)
            return result

        divergence.key_candle_idx = key_candle_idx

        # ================================================================
        # Step 8: 检查是否是最新信号 (避免重复触发)
        # ================================================================
        if not self._is_new_signal(symbol, divergence, key_candle_idx):
            result.mode = PluginMode.FILTERED
            result.filter_reason = "信号已触发过"
            result.reason = result.filter_reason
            return result

        # ================================================================
        # Step 9: 计算止损止盈
        # ================================================================
        key_bar = bars[key_candle_idx]
        current_close = closes[-1]
        current_atr = atr[-1]

        if divergence.div_type == DivergenceType.BULLISH:
            # 做多
            result.action = "BUY"
            result.entry_price = current_close
            result.stop_loss = key_bar["low"] - current_atr * self.atr_multiplier
            result.risk_amount = result.entry_price - result.stop_loss
            result.take_profit = result.entry_price + result.risk_amount * TAKE_PROFIT_RATIO

            self._update_stats("bullish_signals")
        else:
            # 做空
            result.action = "SELL"
            result.entry_price = current_close
            result.stop_loss = key_bar["high"] + current_atr * self.atr_multiplier
            result.risk_amount = result.stop_loss - result.entry_price
            result.take_profit = result.entry_price - result.risk_amount * TAKE_PROFIT_RATIO

            self._update_stats("bearish_signals")

        # ================================================================
        # Step 10: 设置结果
        # ================================================================
        result.mode = PluginMode.SIGNAL_FOUND

        div_name = "底背离" if divergence.div_type == DivergenceType.BULLISH else "顶背离"
        result.reason = (
            f"MACD{div_name} | 强度{divergence.strength_pct:.0f}% | "
            f"L1={l1_trend} | 止损={result.stop_loss:.2f} | 止盈={result.take_profit:.2f}"
        )

        # 记录信号
        self._cache_signal(symbol, divergence, key_candle_idx)
        self._update_stats("total_signals")
        self._write_log(symbol, result)

        # v0.5: 不在process()内消耗配额，由调用方执行成功后调用mark_executed()
        self._log(f"{symbol}: {result.action} | {result.reason}")

        return result

    def mark_executed(self, symbol: str, action: str):
        """
        v0.5: 执行成功后调用 — 消耗每日配额 + 更新统计

        调用方在send_signalstack_order()/send_3commas_signal()成功后调用此方法。
        避免信号被发现但未执行时浪费配额。
        """
        self._update_stats("executed")
        status_msg = self._update_daily_state(symbol, action)
        self._log(f"[v0.5] {symbol} MACD {action} 执行确认, 状态: {status_msg}")

    # ========================================================================
    # 指标计算
    # ========================================================================

    def _calc_macd(self, closes: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算MACD(13,34,9)"""
        fast_ema = self._ema(closes, self.macd_fast)
        slow_ema = self._ema(closes, self.macd_slow)
        macd_line = fast_ema - slow_ema
        signal_line = self._ema(macd_line, self.macd_signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _calc_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
        """计算ATR(13)"""
        n = len(closes)
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]

        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )

        # Wilder's smoothing
        atr = np.zeros(n)
        atr[self.atr_period - 1] = np.mean(tr[:self.atr_period])

        for i in range(self.atr_period, n):
            atr[i] = (atr[i-1] * (self.atr_period - 1) + tr[i]) / self.atr_period

        return atr

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """指数移动平均"""
        n = len(data)
        if n < period:
            return data.copy()

        result = np.zeros(n)
        multiplier = 2.0 / (period + 1)
        result[period - 1] = np.mean(data[:period])

        for i in range(period, n):
            result[i] = (data[i] - result[i-1]) * multiplier + result[i-1]

        return result

    # ========================================================================
    # 背离检测
    # ========================================================================

    def _detect_divergence(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        macd_hist: np.ndarray,
        min_swing_bars: int = None,
    ) -> DivergenceSignal:
        """
        检测MACD背离

        底背离: 价格低点越来越低，MACD柱状图波峰越来越高
        顶背离: 价格高点越来越高，MACD柱状图波峰越来越低
        """
        _swing_bars = min_swing_bars if min_swing_bars is not None else self.min_swing_bars
        result = DivergenceSignal()

        n = len(closes)
        if n < MIN_BARS_FOR_ANALYSIS:
            return result

        # 只检测最近的K线区域
        lookback = min(n, 120)
        start_idx = n - lookback

        # 检测底背离 (MACD在零轴下方)
        if macd_hist[-1] < 0:
            bullish = self._detect_bullish_divergence(
                lows[start_idx:],
                macd_hist[start_idx:],
                start_idx,
                min_swing_bars=_swing_bars,
            )
            if bullish.div_type != DivergenceType.NONE:
                return bullish

        # 检测顶背离 (MACD在零轴上方)
        if macd_hist[-1] > 0:
            bearish = self._detect_bearish_divergence(
                highs[start_idx:],
                macd_hist[start_idx:],
                start_idx,
                min_swing_bars=_swing_bars,
            )
            if bearish.div_type != DivergenceType.NONE:
                return bearish

        return result

    def _detect_bullish_divergence(
        self,
        lows: np.ndarray,
        macd_hist: np.ndarray,
        offset: int,
        min_swing_bars: int = None,
    ) -> DivergenceSignal:
        """
        检测底背离

        条件:
        1. 价格低点连续创新低 (至少2个低点)
        2. MACD柱状图波峰连续升高 (在零轴下方，绝对值变小)
        3. 背离高度差 >= 30%
        """
        _swing_bars = min_swing_bars if min_swing_bars is not None else self.min_swing_bars
        result = DivergenceSignal()

        # 找价格低点 (swing lows)
        price_lows = self._find_swing_lows(lows, _swing_bars)
        if len(price_lows) < 2:
            result.debug_info = f"swing_lows={len(price_lows)}"
            return result

        # 找MACD柱状图的波谷 (零轴下方的最低点)
        macd_troughs = self._find_macd_troughs(macd_hist, price_lows)
        if len(macd_troughs) < 2:
            result.debug_info = f"swings={len(price_lows)},macd_troughs={len(macd_troughs)}"
            return result

        # 检查背离条件
        # 取最近的两个点
        p1, p2 = price_lows[-2], price_lows[-1]  # p2是更新的
        m1, m2 = macd_troughs[-2], macd_troughs[-1]

        # 价格创新低: p2.price < p1.price
        if p2.price >= p1.price:
            return result

        # MACD波谷升高: m2.macd_hist > m1.macd_hist (负值，绝对值变小)
        if m2.macd_hist <= m1.macd_hist:
            return result

        # 计算背离强度
        if abs(m1.macd_hist) > 1e-10:
            strength = abs((m2.macd_hist - m1.macd_hist) / m1.macd_hist) * 100
        else:
            strength = 0

        result.div_type = DivergenceType.BULLISH
        result.strength_pct = strength
        result.swing_count = 2
        result.price_swings = [
            SwingPoint(p1.index + offset, p1.price, m1.macd_hist, False),
            SwingPoint(p2.index + offset, p2.price, m2.macd_hist, False),
        ]
        result.macd_swings = [
            SwingPoint(m1.index + offset, p1.price, m1.macd_hist, False),
            SwingPoint(m2.index + offset, p2.price, m2.macd_hist, False),
        ]

        return result

    def _detect_bearish_divergence(
        self,
        highs: np.ndarray,
        macd_hist: np.ndarray,
        offset: int,
        min_swing_bars: int = None,
    ) -> DivergenceSignal:
        """
        检测顶背离

        条件:
        1. 价格高点连续创新高 (至少2个高点)
        2. MACD柱状图波峰连续降低 (在零轴上方，值变小)
        3. 背离高度差 >= 30%
        """
        _swing_bars = min_swing_bars if min_swing_bars is not None else self.min_swing_bars
        result = DivergenceSignal()

        # 找价格高点 (swing highs)
        price_highs = self._find_swing_highs(highs, _swing_bars)
        if len(price_highs) < 2:
            result.debug_info = f"swing_highs={len(price_highs)}"
            return result

        # 找MACD柱状图的波峰 (零轴上方的最高点)
        macd_peaks = self._find_macd_peaks(macd_hist, price_highs)
        if len(macd_peaks) < 2:
            result.debug_info = f"swings={len(price_highs)},macd_peaks={len(macd_peaks)}"
            return result

        # 检查背离条件
        p1, p2 = price_highs[-2], price_highs[-1]
        m1, m2 = macd_peaks[-2], macd_peaks[-1]

        # 价格创新高: p2.price > p1.price
        if p2.price <= p1.price:
            return result

        # MACD波峰降低: m2.macd_hist < m1.macd_hist
        if m2.macd_hist >= m1.macd_hist:
            return result

        # 计算背离强度
        if abs(m1.macd_hist) > 1e-10:
            strength = abs((m1.macd_hist - m2.macd_hist) / m1.macd_hist) * 100
        else:
            strength = 0

        result.div_type = DivergenceType.BEARISH
        result.strength_pct = strength
        result.swing_count = 2
        result.price_swings = [
            SwingPoint(p1.index + offset, p1.price, m1.macd_hist, True),
            SwingPoint(p2.index + offset, p2.price, m2.macd_hist, True),
        ]
        result.macd_swings = [
            SwingPoint(m1.index + offset, p1.price, m1.macd_hist, True),
            SwingPoint(m2.index + offset, p2.price, m2.macd_hist, True),
        ]

        return result

    def _find_swing_lows(self, data: np.ndarray, min_bars: int) -> List[SwingPoint]:
        """找波谷（局部最低点）"""
        swings = []
        n = len(data)

        for i in range(min_bars, n - min_bars):
            # 检查是否是局部最低点
            is_low = True
            for j in range(1, min_bars + 1):
                if data[i] > data[i - j] or data[i] > data[i + j]:
                    is_low = False
                    break

            if is_low:
                swings.append(SwingPoint(i, data[i], 0, False))

        # 过滤太近的点
        filtered = []
        for s in swings:
            if not filtered or s.index - filtered[-1].index >= min_bars:
                filtered.append(s)

        return filtered

    def _find_swing_highs(self, data: np.ndarray, min_bars: int) -> List[SwingPoint]:
        """找波峰（局部最高点）"""
        swings = []
        n = len(data)

        for i in range(min_bars, n - min_bars):
            is_high = True
            for j in range(1, min_bars + 1):
                if data[i] < data[i - j] or data[i] < data[i + j]:
                    is_high = False
                    break

            if is_high:
                swings.append(SwingPoint(i, data[i], 0, True))

        filtered = []
        for s in swings:
            if not filtered or s.index - filtered[-1].index >= min_bars:
                filtered.append(s)

        return filtered

    def _find_macd_troughs(
        self,
        macd_hist: np.ndarray,
        price_swings: List[SwingPoint]
    ) -> List[SwingPoint]:
        """找MACD柱状图在价格低点附近的波谷"""
        troughs = []

        for swing in price_swings:
            idx = swing.index
            # 在价格低点附近找MACD最低值
            start = max(0, idx - 5)
            end = min(len(macd_hist), idx + 5)

            if end <= start:
                continue

            local_min_idx = start + np.argmin(macd_hist[start:end])
            local_min_val = macd_hist[local_min_idx]

            # 只考虑零轴下方的值
            if local_min_val < 0:
                troughs.append(SwingPoint(local_min_idx, swing.price, local_min_val, False))

        return troughs

    def _find_macd_peaks(
        self,
        macd_hist: np.ndarray,
        price_swings: List[SwingPoint]
    ) -> List[SwingPoint]:
        """找MACD柱状图在价格高点附近的波峰"""
        peaks = []

        for swing in price_swings:
            idx = swing.index
            start = max(0, idx - 5)
            end = min(len(macd_hist), idx + 5)

            if end <= start:
                continue

            local_max_idx = start + np.argmax(macd_hist[start:end])
            local_max_val = macd_hist[local_max_idx]

            # 只考虑零轴上方的值
            if local_max_val > 0:
                peaks.append(SwingPoint(local_max_idx, swing.price, local_max_val, True))

        return peaks

    # ========================================================================
    # 关键K线检测
    # ========================================================================

    def _find_key_candle(self, macd_hist: np.ndarray, div_type: DivergenceType) -> int:
        """
        找关键K线

        定义: MACD柱子从深色变浅色的第一根
        - 底背离: 红柱变短（负值绝对值变小）的第一根
        - 顶背离: 绿柱变短（正值变小）的第一根
        """
        n = len(macd_hist)

        if div_type == DivergenceType.BULLISH:
            # 底背离: 找MACD从深红变浅红的第一根 (负值开始变大)
            for i in range(n - 1, max(n - 10, 0), -1):
                if macd_hist[i] < 0 and macd_hist[i - 1] < 0:
                    # 当前柱比前一根短（绝对值小）
                    if macd_hist[i] > macd_hist[i - 1]:
                        return i

        elif div_type == DivergenceType.BEARISH:
            # 顶背离: 找MACD从深绿变浅绿的第一根 (正值开始变小)
            for i in range(n - 1, max(n - 10, 0), -1):
                if macd_hist[i] > 0 and macd_hist[i - 1] > 0:
                    # 当前柱比前一根短
                    if macd_hist[i] < macd_hist[i - 1]:
                        return i

        return -1

    # ========================================================================
    # 过滤逻辑
    # ========================================================================

    def _apply_trend_filter(
        self,
        div_type: DivergenceType,
        l1_trend: str,
        position_pct: float,
    ) -> Optional[str]:
        """
        背离策略趋势过滤（v0.2修正）

        背离是逆趋势策略，用于抓反转：
        - 底背离 = 下跌末期动能衰竭 → 在DOWN趋势中找买点
        - 顶背离 = 上涨末期动能衰竭 → 在UP趋势中找卖点

        位置过滤已在Step 6处理（80%/20%），这里不再重复。
        背离本身就是逆趋势信号，不应该用趋势方向过滤。
        """
        # v0.2: 移除趋势过滤，背离策略本意是抓反转
        # 位置过滤已在外层处理（BUY_MAX_POSITION_PCT=80, SELL_MIN_POSITION_PCT=20）
        return None

    # ========================================================================
    # 信号缓存
    # ========================================================================

    def _is_new_signal(self, symbol: str, divergence: DivergenceSignal, key_idx: int) -> bool:
        """检查是否是新信号（避免同一个背离重复触发）"""
        last = self.last_signal.get(symbol)
        if not last:
            return True

        # 如果关键K线索引不同，或者背离类型不同，认为是新信号
        if last.get("key_idx") != key_idx or last.get("div_type") != divergence.div_type.value:
            return True

        # 如果距离上次信号超过10根K线，认为是新信号
        if key_idx - last.get("key_idx", 0) > 10:
            return True

        return False

    def _cache_signal(self, symbol: str, divergence: DivergenceSignal, key_idx: int):
        """缓存信号"""
        self.last_signal[symbol] = {
            "div_type": divergence.div_type.value,
            "key_idx": key_idx,
            "timestamp": time.time(),
        }

    # ========================================================================
    # 统计和日志
    # ========================================================================

    def _update_stats(self, key: str):
        """更新统计"""
        with self._stats_lock:
            self.stats[key] = self.stats.get(key, 0) + 1

    def get_stats(self) -> dict:
        """获取统计"""
        with self._stats_lock:
            return self.stats.copy()

    def _write_log(self, symbol: str, result: DivergenceResult):
        """写日志"""
        if not self.log_enabled:
            return

        try:
            log_path = os.path.join(self.log_dir, DIVERGENCE_LOG_FILE)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            lines = []
            lines.append(f"\n===== {timestamp} {symbol} =====")
            lines.append(f"模式: {result.mode.value}")

            if result.divergence and result.divergence.div_type != DivergenceType.NONE:
                div_name = "底背离" if result.divergence.div_type == DivergenceType.BULLISH else "顶背离"
                lines.append(f"背离: {div_name} | 强度: {result.divergence.strength_pct:.1f}%")

            lines.append(f"L1趋势: {result.l1_trend} | 位置: {result.position_pct:.0f}%")
            lines.append(f"MACD: {result.macd_hist:.4f} | ATR: {result.atr:.4f}")

            if result.action != "NONE":
                lines.append(f"动作: {result.action}")
                lines.append(f"入场: {result.entry_price:.2f}")
                lines.append(f"止损: {result.stop_loss:.2f}")
                lines.append(f"止盈: {result.take_profit:.2f}")

            if result.filter_reason:
                lines.append(f"过滤: {result.filter_reason}")

            lines.append(f"原因: {result.reason}")
            lines.append("=" * 40)

            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))

        except Exception as e:
            self._log(f"写日志失败: {e}")

    def save_summary(self):
        """保存统计汇总"""
        if not self.log_enabled:
            return

        try:
            summary_path = os.path.join(self.log_dir, "macd_divergence_summary.json")
            summary = {
                "timestamp": datetime.now().isoformat(),
                "version": self.VERSION,
                "stats": self.get_stats(),
            }

            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            self._log(f"统计汇总已保存: {summary_path}")

        except Exception as e:
            self._log(f"保存汇总失败: {e}")


# ========================================================================
# 全局单例
# ========================================================================

_global_plugin: MACDDivergencePlugin = None
_plugin_lock = threading.Lock()


def get_macd_divergence_plugin() -> MACDDivergencePlugin:
    """获取全局外挂实例"""
    global _global_plugin
    with _plugin_lock:
        if _global_plugin is None:
            _global_plugin = MACDDivergencePlugin()
            print(f"[MACD_Divergence_Plugin] Init OK v{MACDDivergencePlugin.VERSION}")
        return _global_plugin


# ========================================================================
# GCC-0173: MACD背离信号回测 + 按品种×方向准确率追踪
# ========================================================================

import logging as _logging173
from pathlib import Path as _Path173
from zoneinfo import ZoneInfo as _ZoneInfo173

def _gcc173_log(msg: str):
    """GCC-0173审计日志 — 同时写logger和log_to_server"""
    _logging173.getLogger("MACDDivergence").info(msg)
    try:
        from llm_server_v3640 import log_to_server
        log_to_server(msg)
    except Exception:
        pass

_MACD_ACC_FILE = _Path173("state/macd_signal_accuracy.json")
_MACD_LOG_FILE = _Path173("state/macd_signal_log.jsonl")
_MACD_ACC_LAST_RUN = 0.0
_MACD_ACC_LOCK = threading.Lock()
_MACD_PHASE_CACHE: dict = {}
_MACD_PHASE_CACHE_TS: float = 0.0


def macd_acc_price_backfill():
    """
    GCC-0173: 回填 macd_signal_log.jsonl 中 pending 记录的 price_4h_later。
    信号产生4H后，用yfinance获取实际价格，判断CORRECT/INCORRECT，原地更新JSONL。
    """
    if not _MACD_LOG_FILE.exists():
        return 0

    lines = []
    changed = 0
    now_ts = time.time()

    try:
        with open(_MACD_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return 0

    updated_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            updated_lines.append(line + "\n")
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            updated_lines.append(line + "\n")
            continue

        # 只处理pending且超过4h的记录
        if r.get("result") != "pending" or r.get("price_4h_later") is not None:
            updated_lines.append(json.dumps(r, ensure_ascii=False) + "\n")
            continue

        sig_ts = r.get("ts", 0)
        if now_ts - sig_ts < 4 * 3600:
            # 还没到4h, 跳过
            updated_lines.append(json.dumps(r, ensure_ascii=False) + "\n")
            continue

        # 获取当前价格
        sym = r.get("symbol", "")
        try:
            import yfinance as yf
            crypto_map = {"BTCUSDC": "BTC-USD", "ETHUSDC": "ETH-USD",
                          "SOLUSDC": "SOL-USD", "ZECUSDC": "ZEC-USD"}
            yf_sym = crypto_map.get(sym, sym)
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period="5d", interval="1h")
            if hist is not None and not hist.empty:
                current_price = float(hist["Close"].iloc[-1])
                r["price_4h_later"] = round(current_price, 4)

                sig_price = r.get("price", 0)
                if sig_price > 0:
                    pct = (current_price - sig_price) / sig_price
                    direction = r.get("direction", "BUY")
                    if direction == "BUY":
                        r["result"] = "CORRECT" if pct > 0.005 else ("INCORRECT" if pct < -0.005 else "NEUTRAL")
                    else:
                        r["result"] = "CORRECT" if pct < -0.005 else ("INCORRECT" if pct > 0.005 else "NEUTRAL")
                    r["pct_change"] = round(pct * 100, 2)
                    changed += 1
                    _gcc173_log(
                        f"[GCC-0173][MACD_EVAL] {sym} {direction} "
                        f"→ {r['result']} (信号价{sig_price:.2f} 4H后{current_price:.2f} "
                        f"变动{r['pct_change']:+.2f}%)")
        except Exception as e:
            _gcc173_log(f"[GCC-0173][MACD_EVAL] {sym} 价格获取失败: {e}")

        updated_lines.append(json.dumps(r, ensure_ascii=False) + "\n")

    if changed > 0:
        try:
            with open(_MACD_LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(updated_lines)
            _gcc173_log(f"[GCC-0173][MACD_BACKFILL] 回填{changed}条价格数据")
        except Exception as e:
            _gcc173_log(f"[GCC-0173][MACD_BACKFILL] 写入失败: {e}")

    return changed


def macd_acc_backfill():
    """
    解析 macd_signal_log.jsonl + macd_backtest_results.json,
    按 symbol × direction(底背离/顶背离) 统计4H准确率。
    结果写入 state/macd_signal_accuracy.json。
    5分钟最多跑一次。
    """
    global _MACD_ACC_LAST_RUN
    with _MACD_ACC_LOCK:
        now = time.time()
        if now - _MACD_ACC_LAST_RUN < 300:
            return
        _MACD_ACC_LAST_RUN = now

    records = []

    # 源1: macd_backtest_results.json (历史回测, 已有价格)
    bt_path = _Path173("state/macd_backtest_results.json")
    if bt_path.exists():
        try:
            bt_data = json.loads(bt_path.read_text(encoding="utf-8"))
            for r in bt_data:
                records.append({
                    "symbol": r["symbol"], "direction": r["direction"],
                    "type": r["type"], "result": r["result"],
                    "strength": r.get("strength", 0),
                })
        except Exception:
            pass

    # 源2: macd_signal_log.jsonl (运行时记录, 需回填价格)
    if _MACD_LOG_FILE.exists():
        try:
            with open(_MACD_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("price_4h_later") is not None and r.get("result") != "pending" and r.get("executed", True):
                        records.append({
                            "symbol": r["symbol"], "direction": r["direction"],
                            "type": r.get("div_type", "底背离"),
                            "result": r["result"],
                            "strength": r.get("strength", 0),
                        })
        except Exception:
            pass

    if not records:
        return

    # 统计: symbol × direction
    stats = {}
    overall = {"correct": 0, "incorrect": 0, "neutral": 0, "decisive": 0}

    for r in records:
        result = r.get("result", "NEUTRAL").upper()
        sym = r["symbol"]
        div_type = r.get("div_type") or r.get("type", "底背离")
        key = f"{sym}_{div_type}"

        if key not in stats:
            stats[key] = {"symbol": sym, "div_type": div_type,
                          "correct": 0, "incorrect": 0, "neutral": 0, "decisive": 0}

        if result == "CORRECT":
            stats[key]["correct"] += 1
            stats[key]["decisive"] += 1
            overall["correct"] += 1
            overall["decisive"] += 1
        elif result == "INCORRECT":
            stats[key]["incorrect"] += 1
            stats[key]["decisive"] += 1
            overall["incorrect"] += 1
            overall["decisive"] += 1
        else:
            stats[key]["neutral"] += 1
            overall["neutral"] += 1

    # 计算准确率 + Phase建议
    entries = {}
    for key, s in stats.items():
        decisive = s["decisive"]
        acc = s["correct"] / decisive if decisive > 0 else 0
        if decisive >= 8 and acc >= 0.60:
            suggested_phase = 2
        elif decisive >= 5 and acc < 0.30:
            suggested_phase = 1  # 收紧
        else:
            suggested_phase = 0  # 样本不足
        entries[key] = {
            "symbol": s["symbol"], "div_type": s["div_type"],
            "correct": s["correct"], "incorrect": s["incorrect"],
            "neutral": s["neutral"], "decisive": decisive,
            "accuracy": round(acc, 4),
            "suggested_phase": suggested_phase,
        }

    ov_decisive = overall["decisive"]
    result_data = {
        "updated_at": datetime.now(tz=_ZoneInfo173("America/New_York")).strftime("%Y-%m-%d %H:%M:%S"),
        "overall": {
            "correct": overall["correct"], "incorrect": overall["incorrect"],
            "neutral": overall["neutral"], "decisive": ov_decisive,
            "accuracy": round(overall["correct"] / ov_decisive, 4) if ov_decisive > 0 else 0,
        },
        "entries": entries,
    }

    try:
        _MACD_ACC_FILE.parent.mkdir(parents=True, exist_ok=True)
        _MACD_ACC_FILE.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
        _gcc173_log(
            f"[GCC-0173][MACD_ACC] 回测完成: {ov_decisive}decisive, "
            f"acc={result_data['overall']['accuracy']:.1%}")
    except Exception as _e:
        _gcc173_log(f"[GCC-0173][MACD_ACC] 写入失败: {_e}")


def macd_acc_get_phase(symbol: str, div_type: str) -> int:
    """获取指定品种×背离类型的Phase。0=样本不足, 1=收紧, 2=信任。5分钟缓存"""
    global _MACD_PHASE_CACHE, _MACD_PHASE_CACHE_TS
    now = time.time()
    if now - _MACD_PHASE_CACHE_TS > 300 or not _MACD_PHASE_CACHE:
        if not _MACD_ACC_FILE.exists():
            _MACD_PHASE_CACHE = {}
            _MACD_PHASE_CACHE_TS = now
            return 0
        try:
            data = json.loads(_MACD_ACC_FILE.read_text(encoding="utf-8"))
            _MACD_PHASE_CACHE = data.get("entries", {})
            _MACD_PHASE_CACHE_TS = now
        except Exception:
            _MACD_PHASE_CACHE = {}
            _MACD_PHASE_CACHE_TS = now
            return 0
    key = f"{symbol}_{div_type}"
    entry = _MACD_PHASE_CACHE.get(key, {})
    return entry.get("suggested_phase", 0)


# ========================================================================
# 测试
# ========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("MACD Divergence Plugin v0.1 测试")
    print("=" * 60)

    plugin = get_macd_divergence_plugin()

    # 模拟数据 - 创建一个底背离场景
    np.random.seed(42)
    n = 60

    # 模拟下跌趋势中的底背离
    # 价格创新低，但MACD柱状图抬高
    base_price = 100
    prices = []
    for i in range(n):
        if i < 20:
            price = base_price - i * 0.5 + np.random.randn() * 0.2
        elif i < 40:
            price = base_price - 10 - (i - 20) * 0.3 + np.random.randn() * 0.2
        else:
            price = base_price - 16 - (i - 40) * 0.2 + np.random.randn() * 0.2
        prices.append(price)

    # 构造K线数据
    bars = []
    for i, close in enumerate(prices):
        bars.append({
            "open": close + np.random.randn() * 0.1,
            "high": close + abs(np.random.randn() * 0.5),
            "low": close - abs(np.random.randn() * 0.5),
            "close": close,
            "volume": 1000 + np.random.randint(0, 500),
        })

    # 测试处理
    result = plugin.process(
        symbol="TEST",
        bars=bars,
        l1_trend="DOWN",  # 下跌趋势
        position_pct=30,   # 低位
    )

    print(f"\n结果:")
    print(f"  模式: {result.mode.value}")
    print(f"  动作: {result.action}")
    print(f"  MACD: {result.macd_hist:.4f}")
    print(f"  ATR: {result.atr:.4f}")

    if result.divergence:
        print(f"  背离类型: {result.divergence.div_type.value}")
        print(f"  背离强度: {result.divergence.strength_pct:.1f}%")

    if result.action != "NONE":
        print(f"  入场: {result.entry_price:.2f}")
        print(f"  止损: {result.stop_loss:.2f}")
        print(f"  止盈: {result.take_profit:.2f}")

    print(f"  原因: {result.reason}")

    # 测试L1过滤
    print("\n" + "=" * 60)
    print("测试L1趋势过滤")
    print("=" * 60)

    # 底背离 + UP趋势 = 允许
    result2 = plugin.process("TEST2", bars, l1_trend="UP", position_pct=30)
    print(f"底背离+UP趋势: {result2.mode.value} | {result2.filter_reason or result2.action}")

    # 底背离 + DOWN趋势 = 禁止
    result3 = plugin.process("TEST3", bars, l1_trend="DOWN", position_pct=30)
    print(f"底背离+DOWN趋势: {result3.mode.value} | {result3.filter_reason or result3.action}")

    print("\n统计:")
    print(json.dumps(plugin.get_stats(), indent=2))

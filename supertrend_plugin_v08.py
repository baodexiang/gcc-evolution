# ========================================================================
# SuperTrend + QQE + MACD 趋势策略外挂模块 v0.8.8
# ========================================================================
#
# 版本: 0.8.8
# 日期: 2026-02-27
#
# v0.8.8修复 (3项):
#   P1: QQE算法完整实现，匹配TradingView原版
#     - 之前: EMA(RSI,5)-50 (简化版，等于RSI>50判断，丢失自适应过滤)
#     - 现在: RSI→EMA→|Delta|→双重EMA→×factor→trailing line→趋势判断
#     - factor=1.61参数终于被使用，自适应波动带宽过滤噪音
#     - 返回值从 RsiMa-50 改为 RsiMa-FastAtrRsiTL (真正的QQE信号)
#   P2: 入场信号即时执行，去除1周期延迟
#     - 之前: 本周期计算→缓存→下周期(5min后)才与L1对比→执行
#     - 现在: 本周期计算→即时与L1对比→立即执行(退出信号仍走缓存确认)
#   P3: MACD slow period 34→26 匹配标准参数，减少信号滞后
#
# v0.8.7新增:
#   - 持仓退出优先：有持仓时允许SELL退出，跳过跌幅保护
#   - 问题：RDDT跌27%后跌幅保护激活，但用户有仓位无法退出
#   - 解决：检查position_units，有持仓时跳过跌幅保护，允许止损退出
#   - 跌幅保护仅用于防止"追空"（无仓位时低位做空）
#
# v0.8.6新增:
#   - 跌幅保护机制：大跌后追空保护
#   - 场景：价格30根K线内跌幅>25%时，提高SELL1位置过滤阈值(20%→35%)
#   - 原因：大幅下跌后追空容易被超卖反弹打脸
#   - 配置：DRAWDOWN_THRESHOLD_PCT=25%, SELL1_MIN_POSITION_PROTECTED=35%
#
# v0.8.5修复:
#   - 修复退出后buy1_done/sell1_done未重置的bug
#   - 问题: 外挂激活后设置done=True，退出时未重置，导致后续信号被抑制
#   - 解决: 在_verify_and_execute_exit中退出确认后重置对应的done标记
#
# v0.8.4更新 (v3.442):
#   - 移除趋势限制，外挂在趋势和震荡行情都能激活
#   - 美股和加密货币都适用
#   - 只保留位置过滤（防止极端高位追高、极端低位杀跌）
#   - 原因：SuperTrend指标本身就能判断方向，不需要依赖L1趋势判断
#
# v0.8.2更新:
#   - 放宽触发条件，解决外挂信号被忽略问题
#   - 新增触发条件:
#     * L1有任一模块投票TRENDING且方向不冲突 → 允许
#     * 位置极端（BUY1: pos<35%, SELL1: pos>65%） → 允许
#   - 之前问题: 缓存=BUY1但使用=NONE，被Regime=RANGING过滤
#   - 现在: 只要满足放宽条件就允许触发
#
# v0.8.1更新:
#   - 增加trend_state快速趋势响应，解决震荡转趋势滞后问题
#   - 趋势判断: Regime=TRENDING 或 trend_state=STRONG_UP/STRONG_DOWN
#   - 当Wyckoff还判断为RANGE但trend_state已是STRONG时，允许外挂触发
#
# v0.8更新:
#   - 新增趋势过滤（积极版）：必须是趋势市才触发
#   - BUY1: Regime=TRENDING 且 位置<80%
#   - SELL1: Regime=TRENDING 且 位置>20%
#   - 防止震荡市高位追高、低位杀跌
#
# v0.7更新:
#   - 执行后立即退出，L2正常接管
#   - 只在进场(Buy1)和反转出场(Sell1)时介入
#   - 中间加仓/减仓由L2处理
#   - 保留信号缓存机制
#   - 修复: 内部追踪positions(用于退出检测)，但result.position=NONE
#
# 功能:
#   1. 独立计算 SuperTrend/QQE/MACD 指标信号
#   2. 与 L1 三方协商结果对比验证
#   3. L1一致时激活外挂，L1冲突时听指标并记录失效模块
#   4. v0.8.4: 移除趋势限制，所有行情都能激活
#   5. 执行1次后退出，L2正常工作
#   6. 详细诊断日志，定位 L1 哪个模块失效
#
# ========================================================================

import numpy as np
import json
import os
import threading
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

_st_logger = logging.getLogger("supertrend_plugin")


# ========================================================================
# 配置常量
# ========================================================================

LOG_DIR = "logs"
DIAGNOSIS_LOG_FILE = "l1_module_diagnosis.log"
SUMMARY_LOG_FILE = "l1_diagnosis_summary.json"

# 信号分类
BUY_SIGNALS = ("BUY", "STRONG_BUY", "WEAK_BUY")
SELL_SIGNALS = ("SELL", "STRONG_SELL", "WEAK_SELL")
HOLD_SIGNALS = ("HOLD", "FORCE_HOLD")

# v0.8: 趋势过滤配置
TREND_FILTER_ENABLED = True
BUY1_MAX_POSITION_PCT = 80   # BUY1 位置上限（超过则过滤）
SELL1_MIN_POSITION_PCT = 20  # SELL1 位置下限（低于则过滤）

# v0.8.6: 跌幅保护配置 - 大跌后追空保护
DRAWDOWN_PROTECTION_ENABLED = True
DRAWDOWN_LOOKBACK_BARS = 30       # 计算跌幅的K线数量
DRAWDOWN_THRESHOLD_PCT = 25       # 跌幅阈值：超过25%触发保护
SELL1_MIN_POSITION_PROTECTED = 35 # 保护模式下SELL1位置下限提高到35%


# ========================================================================
# 枚举定义
# ========================================================================

class PluginMode(Enum):
    """外挂工作模式"""
    PLUGIN_AGREE = "PLUGIN_AGREE"       # 外挂激活 - L1一致
    PLUGIN_CONFLICT = "PLUGIN_CONFLICT" # 外挂激活 - L1冲突，听指标
    L2_NORMAL = "L2_NORMAL"             # L2正常工作
    PLUGIN_EXIT = "PLUGIN_EXIT"         # 外挂退出
    PLUGIN_FILTERED = "PLUGIN_FILTERED" # v0.8: 被趋势过滤


class PluginPosition(Enum):
    """外挂持仓状态"""
    NONE = "NONE"
    LONG = "LONG"
    SHORT = "SHORT"


class ErrorType(Enum):
    """L1模块错误类型"""
    MATCH = "MATCH"           # 一致
    OPPOSITE = "OPPOSITE"     # 方向相反
    MISS = "MISS"             # 该动没动
    FALSE_ALARM = "FALSE_ALARM"  # 不该动乱动


# ========================================================================
# 数据类
# ========================================================================

@dataclass
class IndicatorSignal:
    """指标信号"""
    signal: str = "NONE"          # BUY1 / SELL1 / NONE
    supertrend_trend: int = 0     # 1=绿区, -1=红区
    qqe_hist: float = 0.0         # >0 蓝, <0 红
    macd_hist: float = 0.0        # >0 蓝, <0 红

    def is_buy1(self) -> bool:
        return self.signal == "BUY1"

    def is_sell1(self) -> bool:
        return self.signal == "SELL1"

    def has_signal(self) -> bool:
        return self.signal in ("BUY1", "SELL1")


@dataclass
class ModuleDiagnosis:
    """单个模块诊断结果"""
    name: str
    signal: str
    confidence: float
    error_type: ErrorType

    def is_match(self) -> bool:
        return self.error_type == ErrorType.MATCH


@dataclass
class PluginResult:
    """外挂决策结果"""
    mode: PluginMode
    action: str = "NONE"              # BUY / SELL / HOLD / NONE
    indicator_signal: str = "NONE"    # BUY1 / SELL1 / NONE
    l1_signal: str = "NONE"           # L1综合信号
    position: PluginPosition = PluginPosition.NONE

    # 诊断信息
    ai_diagnosis: ModuleDiagnosis = None
    human_diagnosis: ModuleDiagnosis = None
    tech_diagnosis: ModuleDiagnosis = None

    # 指标详情
    supertrend_trend: int = 0
    qqe_hist: float = 0.0
    macd_hist: float = 0.0

    reason: str = ""
    filter_reason: str = ""  # v0.8: 过滤原因
    timestamp: float = 0.0


# ========================================================================
# 指标配置
# ========================================================================

@dataclass
class SuperTrendConfig:
    atr_period: int = 12
    atr_multiplier: float = 3.5


@dataclass
class QQEConfig:
    rsi_length: int = 6
    smoothing: int = 5
    factor: float = 1.61


@dataclass
class MACDConfig:
    fast_length: int = 13
    slow_length: int = 26   # v0.8.8: 34→26 匹配标准MACD，减少信号滞后
    signal_length: int = 9


# ========================================================================
# 主类
# ========================================================================

class SuperTrendPlugin:
    """
    SuperTrend + QQE + MACD 趋势策略外挂
    v0.8: 新增趋势过滤（积极版）
    """

    VERSION = "0.8.8"  # v0.8.8: QQE完整实现(匹配TradingView)

    def __init__(
        self,
        st_config: SuperTrendConfig = None,
        qqe_config: QQEConfig = None,
        macd_config: MACDConfig = None,
        log_enabled: bool = True,
        log_dir: str = LOG_DIR,
    ):
        self.st_config = st_config or SuperTrendConfig()
        self.qqe_config = qqe_config or QQEConfig()
        self.macd_config = macd_config or MACDConfig()

        self.log_enabled = log_enabled
        self.log_dir = log_dir

        # 状态管理 (按品种)
        self.positions: Dict[str, PluginPosition] = {}
        self.entry_times: Dict[str, float] = {}
        self.last_st_trend: Dict[str, int] = {}

        # Buy1/Sell1 触发追踪 (每个ST周期只触发一次)
        self.buy1_done: Dict[str, bool] = {}
        self.sell1_done: Dict[str, bool] = {}

        # v0.6.1: 信号缓存机制 - 当前周期计算的信号保存，下一周期使用
        # 结构: {symbol: {"signal": "BUY1/SELL1/NONE", "cached_at": timestamp, "indicator": IndicatorSignal}}
        self.cached_signals: Dict[str, dict] = {}

        # v0.8: 过滤统计
        self.filter_stats: Dict[str, dict] = {}

        # 诊断统计
        self.diagnosis_stats: Dict[str, dict] = {}
        self._stats_lock = threading.Lock()

        # 初始化日志目录
        if self.log_enabled:
            os.makedirs(self.log_dir, exist_ok=True)

        self.debug = True

    def _log(self, msg: str):
        if self.debug:
            _st_logger.info(f"[SuperTrend_Plugin_v{self.VERSION}] {msg}")

    # ========================================================================
    # 核心接口
    # ========================================================================

    def process(
        self,
        symbol: str,
        ohlcv_bars: List[dict],
        close_prices: List[float],
        l1_signals: dict,
        market_data: dict = None,  # v0.8新增: 市场环境数据
    ) -> PluginResult:
        """
        主处理函数 (v0.8: 新增趋势过滤)

        流程:
            1. 读取上一周期缓存的信号 (用于本周期L1对比)
            2. 计算当前周期的指标信号 (保存到缓存，供下一周期使用)
            3. 用缓存信号与L1对比，执行后续逻辑
            4. v0.8: 趋势过滤检查

        Args:
            symbol: 交易对
            ohlcv_bars: OHLCV K线数据 (30根，用于SuperTrend)
            close_prices: 收盘价列表 (120根，用于QQE/MACD)
            l1_signals: L1三方协商结果
            market_data: v0.8新增，市场环境数据
                {
                    "regime": "TRENDING" / "RANGING",
                    "direction": "UP" / "DOWN" / "SIDE",
                    "position_pct": 0-100,
                }

        Returns:
            PluginResult: 决策结果
        """
        result = PluginResult(
            mode=PluginMode.L2_NORMAL,
            timestamp=time.time(),
        )

        # ================================================================
        # Step 1: 计算当前周期的指标信号 (用于缓存)
        # ================================================================
        current_indicator = self._calc_indicator_signal(symbol, ohlcv_bars, close_prices)

        # 填充当前指标值到结果 (用于显示)
        result.supertrend_trend = current_indicator.supertrend_trend
        result.qqe_hist = current_indicator.qqe_hist
        result.macd_hist = current_indicator.macd_hist

        # ================================================================
        # Step 2: 检查SuperTrend翻转 → 缓存退出信号(不立即退出)
        # ================================================================
        exit_signal = self._detect_exit_signal(symbol, current_indicator)
        if exit_signal:
            # 缓存退出信号，供下一周期验证
            self._cache_exit_signal(symbol, exit_signal, current_indicator)
            self._log(f"{symbol}: 检测到翻转，缓存退出信号 {exit_signal}")

        # ================================================================
        # Step 3: 读取缓存信号 (上一周期保存的)
        # ================================================================
        cached = self.cached_signals.get(symbol, {})
        cached_signal = cached.get("signal", "NONE")
        cached_indicator = cached.get("indicator", None)

        self._log(f"{symbol}: 缓存信号={cached_signal}, 当前计算={current_indicator.signal}")

        # ================================================================
        # Step 3.1: 处理缓存的退出信号
        # ================================================================
        if cached_signal in ("EXIT_LONG", "EXIT_SHORT"):
            exit_result = self._verify_and_execute_exit(symbol, cached_signal, current_indicator, l1_signals)
            if exit_result:
                # 验证通过，执行退出
                del self.cached_signals[symbol]
                self._write_diagnosis_log(symbol, exit_result, l1_signals, current_indicator)
                return exit_result
            else:
                # 验证不通过(SuperTrend翻转回来了)，取消退出信号
                self._log(f"{symbol}: 退出信号取消(SuperTrend翻转回来)")
                del self.cached_signals[symbol]
                # 继续正常流程

        # ================================================================
        # Step 4: v0.8.8 即时入场 — 当前有信号直接用，不等下一周期
        # (退出信号仍走缓存确认机制，入场信号无需等待)
        # ================================================================
        if current_indicator.has_signal():
            # 当前周期有BUY1/SELL1 → 直接使用，无1周期延迟
            use_signal = current_indicator.signal
            use_indicator = current_indicator
            self._log(f"{symbol}: 即时入场模式 signal={use_signal}")
        elif cached_signal in ("BUY1", "SELL1"):
            # 兼容: 上周期有缓存但当前无信号(罕见，信号刚消失) → 用缓存
            use_signal = cached_signal
            use_indicator = cached_indicator if cached_indicator else current_indicator
            self._log(f"{symbol}: 缓存入场模式 signal={use_signal}")
        else:
            use_signal = "NONE"
            use_indicator = current_indicator

        result.indicator_signal = use_signal

        # 保存当前信号到缓存 (仅作为下周期兼容备用)
        self._cache_signal(symbol, current_indicator)

        # ================================================================
        # Step 4.5: v0.8 趋势过滤（积极版）+ v0.8.6 跌幅保护
        # ================================================================
        if TREND_FILTER_ENABLED and use_signal in ("BUY1", "SELL1") and market_data:
            # v0.8.6: 传递ohlcv_bars用于跌幅保护计算
            market_data["ohlcv_bars"] = ohlcv_bars
            filter_result = self._apply_trend_filter(symbol, use_signal, market_data)
            if filter_result:
                # 被过滤，返回L2_NORMAL
                result.mode = PluginMode.PLUGIN_FILTERED
                result.reason = filter_result
                result.filter_reason = filter_result
                result.l1_signal = l1_signals.get("signal", "HOLD")
                self._log(f"{symbol}: {filter_result}")
                # 清除缓存，避免下周期重复触发
                if symbol in self.cached_signals:
                    del self.cached_signals[symbol]
                self._update_filter_stats(symbol, use_signal, filter_result)
                self._write_diagnosis_log(symbol, result, l1_signals, current_indicator)
                return result

        # ================================================================
        # Step 5: 无信号 → L2 正常工作
        # ================================================================
        if use_signal == "NONE":
            result.mode = PluginMode.L2_NORMAL
            result.reason = "无信号，L2正常接管"
            result.l1_signal = l1_signals.get("signal", "HOLD")
            self._write_diagnosis_log(symbol, result, l1_signals, current_indicator)
            return result

        # ================================================================
        # Step 6: 有信号 → 与L1对比
        # ================================================================
        ai_diag = self._diagnose_module("AI", l1_signals.get("ai_signal", "HOLD"),
                                         l1_signals.get("ai_confidence", 0.5), use_indicator)
        human_diag = self._diagnose_module("Human", l1_signals.get("human_signal", "HOLD"),
                                            l1_signals.get("human_confidence", 0.5), use_indicator)
        tech_diag = self._diagnose_module("Tech", l1_signals.get("tech_signal", "HOLD"),
                                           l1_signals.get("tech_confidence", 0.5), use_indicator)

        result.ai_diagnosis = ai_diag
        result.human_diagnosis = human_diag
        result.tech_diagnosis = tech_diag
        result.l1_signal = l1_signals.get("signal", "HOLD")

        # 判断L1是否一致
        ai_sig = l1_signals.get("ai_signal", "HOLD")
        human_sig = l1_signals.get("human_signal", "HOLD")
        tech_sig = l1_signals.get("tech_signal", "HOLD")

        is_buy_signal = (use_signal == "BUY1")

        if is_buy_signal:
            ai_ok = ai_sig in BUY_SIGNALS
            tech_ok = tech_sig in BUY_SIGNALS
            human_ok = human_sig in BUY_SIGNALS or human_sig in HOLD_SIGNALS
            l1_agree = ai_ok and tech_ok and human_ok
        else:  # Sell1
            ai_ok = ai_sig in SELL_SIGNALS
            tech_ok = tech_sig in SELL_SIGNALS
            human_ok = human_sig in SELL_SIGNALS or human_sig in HOLD_SIGNALS
            l1_agree = ai_ok and tech_ok and human_ok

        # ================================================================
        # Step 7: 设置结果
        # ================================================================
        if l1_agree:
            result.mode = PluginMode.PLUGIN_AGREE
            result.reason = "L1一致，外挂激活(即时信号)"
        else:
            result.mode = PluginMode.PLUGIN_CONFLICT
            # 找出失效模块
            failed_modules = []
            if not ai_diag.is_match():
                failed_modules.append(f"AI({ai_diag.error_type.value})")
            if not human_diag.is_match():
                failed_modules.append(f"Human({human_diag.error_type.value})")
            if not tech_diag.is_match():
                failed_modules.append(f"Tech({tech_diag.error_type.value})")
            result.reason = f"L1冲突，听指标(即时)。失效: {', '.join(failed_modules)}"

        # ================================================================
        # Step 8: 设置动作 (v0.7: 执行后L2接管，但内部追踪用于退出检测)
        # ================================================================
        if is_buy_signal:
            result.action = "BUY"
            self.buy1_done[symbol] = True
            # v0.7: 内部追踪(用于退出检测)，但不影响result返回
            self.positions[symbol] = PluginPosition.LONG
            self.entry_times[symbol] = time.time()
        else:
            result.action = "SELL"
            self.sell1_done[symbol] = True
            # v0.7: 内部追踪(用于退出检测)，但不影响result返回
            self.positions[symbol] = PluginPosition.SHORT
            self.entry_times[symbol] = time.time()

        # v0.7: result.position=NONE让主程序L2正常工作
        # (内部self.positions仍追踪，用于SuperTrend翻转时触发Sell1)
        result.position = PluginPosition.NONE

        # ================================================================
        # Step 9: 清除已使用的缓存信号 (一次性使用)
        # ================================================================
        if symbol in self.cached_signals:
            del self.cached_signals[symbol]
            self._log(f"{symbol}: 缓存信号已使用并清除")

        # ================================================================
        # Step 10: 记录日志和统计
        # ================================================================
        self._write_diagnosis_log(symbol, result, l1_signals, current_indicator)
        self._update_stats(symbol, ai_diag, human_diag, tech_diag)

        # v0.7: 执行后立即退出，让L2接管后续
        self._log(f"{symbol}: {result.mode.value} | {result.action} | {result.reason} → 执行后L2接管")

        return result

    # ========================================================================
    # v0.8: 趋势过滤
    # v0.8.2: 放宽过滤条件，允许L1有TRENDING投票或极端位置时触发
    # ========================================================================

    def _apply_trend_filter(self, symbol: str, signal: str, market_data: dict) -> Optional[str]:
        """
        v0.8.4: 应用位置过滤（移除趋势限制）

        v3.442修改: 移除current_trend限制，外挂在趋势和震荡行情都能激活
        - 美股和加密货币都适用
        - 只保留位置过滤防止极端追高杀跌

        过滤条件:
            - BUY1: 位置不能超过80%（防止高位追高）
            - SELL1: 位置不能低于20%（防止低位杀跌）

        Returns:
            过滤原因字符串，如果不过滤则返回 None
        """
        position_pct = market_data.get("position_pct", 50)
        current_trend = market_data.get("current_trend", "SIDE")

        # v3.442: 移除趋势限制，所有行情都允许触发
        # 原v3.391逻辑: current_trend必须是UP/DOWN才触发
        # 新逻辑: 无论趋势还是震荡都允许触发，依靠SuperTrend指标本身判断方向

        # ====== 位置过滤 + 跌幅保护 ======

        # 过滤: BUY1 只过滤极端高位
        if signal == "BUY1":
            if position_pct > BUY1_MAX_POSITION_PCT:
                return f"过滤: 极端高位({position_pct:.0f}%>{BUY1_MAX_POSITION_PCT}%)不买"

        # 过滤: SELL1 - 位置过滤 + 跌幅保护
        elif signal == "SELL1":
            # v0.8.7: 检查实际持仓 - 有持仓时允许退出卖出
            position_units = market_data.get("position_units", 0)
            if position_units > 0:
                # 有持仓，允许SELL退出（跳过跌幅保护）
                self._log(f"{symbol}: 持仓退出模式 (position_units={position_units})，跳过跌幅保护")
                # 通过过滤
            else:
                # 无持仓，应用跌幅保护（防止追空）
                # v0.8.6: 跌幅保护 - 计算近期跌幅
                sell_min_position = SELL1_MIN_POSITION_PCT  # 默认20%
                drawdown_pct = 0

                if DRAWDOWN_PROTECTION_ENABLED:
                    ohlcv_bars = market_data.get("ohlcv_bars", [])
                    if len(ohlcv_bars) >= DRAWDOWN_LOOKBACK_BARS:
                        recent_bars = ohlcv_bars[-DRAWDOWN_LOOKBACK_BARS:]
                        highest = max(bar.get("high", bar.get("close", 0)) for bar in recent_bars)
                        current_close = recent_bars[-1].get("close", 0) if recent_bars else 0
                        if highest > 0:
                            drawdown_pct = (highest - current_close) / highest * 100

                            # 跌幅超过阈值，提高位置过滤阈值
                            if drawdown_pct >= DRAWDOWN_THRESHOLD_PCT:
                                sell_min_position = SELL1_MIN_POSITION_PROTECTED
                                self._log(f"{symbol}: 跌幅保护激活! 近{DRAWDOWN_LOOKBACK_BARS}根K线跌幅={drawdown_pct:.1f}%>{DRAWDOWN_THRESHOLD_PCT}%, SELL位置阈值提高到{sell_min_position}%")

                # 应用位置过滤
                if position_pct < sell_min_position:
                    protection_note = f"(跌幅保护:{drawdown_pct:.0f}%)" if drawdown_pct >= DRAWDOWN_THRESHOLD_PCT else ""
                    return f"过滤: 低位({position_pct:.0f}%<{sell_min_position}%)不卖{protection_note}"

        # 通过过滤
        self._log(f"{symbol}: 外挂触发! {signal} | current_trend={current_trend} | pos={position_pct:.0f}%")
        return None

    def _update_filter_stats(self, symbol: str, signal: str, reason: str):
        """更新过滤统计"""
        with self._stats_lock:
            if symbol not in self.filter_stats:
                self.filter_stats[symbol] = {"total": 0, "by_reason": {}}
            self.filter_stats[symbol]["total"] += 1
            self.filter_stats[symbol]["by_reason"][reason] = \
                self.filter_stats[symbol]["by_reason"].get(reason, 0) + 1

    def get_filter_stats(self) -> dict:
        """获取过滤统计"""
        with self._stats_lock:
            return self.filter_stats.copy()

    # ========================================================================
    # 缓存相关
    # ========================================================================

    def _cache_signal(self, symbol: str, indicator: IndicatorSignal):
        """缓存当前信号供下一周期使用"""
        if indicator.has_signal():
            self.cached_signals[symbol] = {
                "signal": indicator.signal,
                "cached_at": time.time(),
                "indicator": indicator,
            }
            self._log(f"{symbol}: 缓存信号 {indicator.signal} (ST={indicator.supertrend_trend}, QQE={indicator.qqe_hist:.2f}, MACD={indicator.macd_hist:.4f})")
        # 如果当前无信号，不覆盖已有缓存 (保留上一周期的信号)

    def get_cached_signal(self, symbol: str) -> dict:
        """获取缓存的信号 (供外部查询)"""
        return self.cached_signals.get(symbol, {"signal": "NONE", "cached_at": 0})

    def should_bypass_l2(self, result: PluginResult) -> bool:
        """是否跳过L2"""
        return result.mode in (PluginMode.PLUGIN_AGREE, PluginMode.PLUGIN_CONFLICT)

    def get_position(self, symbol: str) -> PluginPosition:
        """获取当前持仓"""
        return self.positions.get(symbol, PluginPosition.NONE)

    # ========================================================================
    # 指标计算
    # ========================================================================

    def _calc_indicator_signal(
        self,
        symbol: str,
        ohlcv_bars: List[dict],
        close_prices: List[float],
    ) -> IndicatorSignal:
        """计算指标信号"""
        result = IndicatorSignal()

        # 数据检查
        if not ohlcv_bars or len(ohlcv_bars) < 15:
            return result
        if not close_prices or len(close_prices) < 50:  # v0.6.1: 40→50 确保MACD稳定
            return result

        try:
            # SuperTrend (用 ohlcv_bars)
            highs = np.array([bar["high"] for bar in ohlcv_bars], dtype=float)
            lows = np.array([bar["low"] for bar in ohlcv_bars], dtype=float)
            closes_ohlcv = np.array([bar["close"] for bar in ohlcv_bars], dtype=float)

            st_trend, _, _ = self._calc_supertrend(highs, lows, closes_ohlcv)
            result.supertrend_trend = st_trend

            # QQE 和 MACD (用 close_prices)
            closes = np.array(close_prices, dtype=float)
            result.qqe_hist = self._calc_qqe(closes)
            result.macd_hist = self._calc_macd(closes)

            # 检测 SuperTrend 翻转，重置信号
            # v0.8.4: 修复 - 匹配TradingView原版逻辑
            # TradingView: stSellSignal重置buy1Done, stBuySignal重置sell1Done
            # 之前错误: 任何翻转同时重置两个标记
            last_trend = self.last_st_trend.get(symbol, 0)
            if st_trend != last_trend and last_trend != 0:
                self._log(f"{symbol}: SuperTrend翻转 {last_trend}→{st_trend}")
                if st_trend == -1:
                    # 翻转到红区 = stSellSignal → 只重置buy1_done（准备寻找BUY1信号）
                    self.buy1_done[symbol] = False
                    self._log(f"{symbol}: 进入红区，重置buy1_done")
                elif st_trend == 1:
                    # 翻转到绿区 = stBuySignal → 只重置sell1_done（准备寻找SELL1信号）
                    self.sell1_done[symbol] = False
                    self._log(f"{symbol}: 进入绿区，重置sell1_done")
            self.last_st_trend[symbol] = st_trend

            # 信号判断
            in_red = (st_trend == -1)
            in_green = (st_trend == 1)
            qqe_up = (result.qqe_hist > 0)
            qqe_down = (result.qqe_hist < 0)
            macd_up = (result.macd_hist > 0)
            macd_down = (result.macd_hist < 0)

            # Buy1: 红区 + QQE蓝 + MACD蓝
            if in_red and qqe_up and macd_up and not self.buy1_done.get(symbol, False):
                result.signal = "BUY1"

            # Sell1: 绿区 + QQE红 + MACD红
            elif in_green and qqe_down and macd_down and not self.sell1_done.get(symbol, False):
                result.signal = "SELL1"

        except Exception as e:
            self._log(f"{symbol}: 指标计算错误: {e}")

        return result

    def _calc_supertrend(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> Tuple[int, float, float]:
        """计算 SuperTrend"""
        period = self.st_config.atr_period
        mult = self.st_config.atr_multiplier

        n = len(closes)
        if n < period + 1:
            return 0, 0, 0

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

        return int(trend[-1]), float(st_up[-1]), float(st_dn[-1])

    def _calc_qqe(self, closes: np.ndarray) -> float:
        """
        计算 QQE (完整版，匹配TradingView)

        TradingView QQE 算法:
        1. RSI → EMA平滑 = RsiMa
        2. |Delta RsiMa| → EMA(2*RSI_Period-1) = MaAtrRsi
        3. EMA(MaAtrRsi) × factor = DeltaFastAtrRsi (双重EMA自适应波动带宽)
        4. RsiMa ± DeltaFastAtrRsi → longband/shortband (trailing lines)
        5. RsiMa vs trailing line → trend 方向
        6. 返回 RsiMa - FastAtrRsiTL (正=多, 负=空)

        之前简化版只返回 EMA(RSI)-50，丢失了factor自适应过滤。
        """
        rsi = self._calc_rsi(closes, self.qqe_config.rsi_length)
        rsi_ma = self._ema(rsi, self.qqe_config.smoothing)

        n = len(rsi_ma)
        if n < 3:
            return 0.0

        # Step 2: |Delta of RsiMa| → EMA平滑
        atr_rsi = np.zeros(n)
        for i in range(1, n):
            atr_rsi[i] = abs(rsi_ma[i] - rsi_ma[i - 1])

        wilder_period = 2 * self.qqe_config.rsi_length - 1  # RSI=6 → EMA(11), 等价Wilder(6)
        ma_atr_rsi = self._ema(atr_rsi, wilder_period)  # 第一次EMA平滑

        # Step 3: 自适应波动带宽 (TV原版: dar = ema(MaAtrRsi, Wilders) * QQE → 双重EMA)
        dar = self._ema(ma_atr_rsi, wilder_period) * self.qqe_config.factor

        # Step 4-5: Trailing lines + trend
        longband = np.zeros(n)
        shortband = np.zeros(n)
        trend = np.ones(n, dtype=int)

        for i in range(1, n):
            new_longband = rsi_ma[i] - dar[i]
            new_shortband = rsi_ma[i] + dar[i]

            # longband: 只能上移(当RsiMa在其上方时)
            if rsi_ma[i - 1] > longband[i - 1] and rsi_ma[i] > longband[i - 1]:
                longband[i] = max(longband[i - 1], new_longband)
            else:
                longband[i] = new_longband

            # shortband: 只能下移(当RsiMa在其下方时)
            if rsi_ma[i - 1] < shortband[i - 1] and rsi_ma[i] < shortband[i - 1]:
                shortband[i] = min(shortband[i - 1], new_shortband)
            else:
                shortband[i] = new_shortband

            # trend: RsiMa穿越shortband→多, 穿越longband→空
            if rsi_ma[i] > shortband[i - 1]:
                trend[i] = 1
            elif rsi_ma[i] < longband[i - 1]:
                trend[i] = -1
            else:
                trend[i] = trend[i - 1]

        # FastAtrRsiTL = 多头时用longband, 空头时用shortband
        fast_tl = np.where(trend == 1, longband, shortband)

        # 返回 RsiMa - FastAtrRsiTL (正=多头, 负=空头)
        return float(rsi_ma[-1] - fast_tl[-1])

    def _calc_macd(self, closes: np.ndarray) -> float:
        """计算 MACD Histogram"""
        fast = self._ema(closes, self.macd_config.fast_length)
        slow = self._ema(closes, self.macd_config.slow_length)
        macd_line = fast - slow
        signal_line = self._ema(macd_line, self.macd_config.signal_length)
        histogram = macd_line - signal_line
        return float(histogram[-1])

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
        """EMA"""
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
    # 退出检测 (v0.6.1: 缓存机制)
    # ========================================================================

    def _detect_exit_signal(self, symbol: str, indicator: IndicatorSignal) -> Optional[str]:
        """检测是否需要退出(只检测，不执行)，返回退出信号类型"""
        position = self.positions.get(symbol, PluginPosition.NONE)

        if position == PluginPosition.NONE:
            return None

        st_trend = indicator.supertrend_trend

        # 做多 + SuperTrend翻红 → 需要退出
        if position == PluginPosition.LONG and st_trend == -1:
            return "EXIT_LONG"

        # 做空 + SuperTrend翻绿 → 需要退出
        if position == PluginPosition.SHORT and st_trend == 1:
            return "EXIT_SHORT"

        return None

    def _cache_exit_signal(self, symbol: str, exit_signal: str, indicator: IndicatorSignal):
        """缓存退出信号供下一周期验证"""
        self.cached_signals[symbol] = {
            "signal": exit_signal,
            "cached_at": time.time(),
            "indicator": indicator,
            "entry_time": self.entry_times.get(symbol, time.time()),
        }
        self._log(f"{symbol}: 缓存退出信号 {exit_signal}")

    def _verify_and_execute_exit(
        self,
        symbol: str,
        cached_exit_signal: str,
        current_indicator: IndicatorSignal,
        l1_signals: dict,
    ) -> Optional[PluginResult]:
        """验证并执行退出(下一周期调用)"""
        position = self.positions.get(symbol, PluginPosition.NONE)
        st_trend = current_indicator.supertrend_trend

        # 验证: 当前SuperTrend是否仍然确认退出
        if cached_exit_signal == "EXIT_LONG":
            # 做多退出需要ST仍然是红(-1)
            if st_trend != -1:
                self._log(f"{symbol}: EXIT_LONG验证失败，ST已翻回绿区")
                return None  # 翻转回来了，不退出
        elif cached_exit_signal == "EXIT_SHORT":
            # 做空退出需要ST仍然是绿(1)
            if st_trend != 1:
                self._log(f"{symbol}: EXIT_SHORT验证失败，ST已翻回红区")
                return None  # 翻转回来了，不退出

        # 验证通过，执行退出
        cached = self.cached_signals.get(symbol, {})
        entry_time = cached.get("entry_time", time.time())
        duration = time.time() - entry_time

        if cached_exit_signal == "EXIT_LONG":
            reason = f"SuperTrend翻转(绿→红)确认，退出做多，持仓{duration/60:.1f}分钟"
        else:
            reason = f"SuperTrend翻转(红→绿)确认，退出做空，持仓{duration/60:.1f}分钟"

        result = PluginResult(
            mode=PluginMode.PLUGIN_EXIT,
            action=cached_exit_signal,
            position=PluginPosition.NONE,
            reason=reason,
            timestamp=time.time(),
            supertrend_trend=st_trend,
            qqe_hist=current_indicator.qqe_hist,
            macd_hist=current_indicator.macd_hist,
        )

        # 清除持仓状态
        self.positions[symbol] = PluginPosition.NONE

        # v0.8.5修复: 退出时重置done标记，允许下次信号触发
        if cached_exit_signal == "EXIT_LONG":
            self.buy1_done[symbol] = False
            self._log(f"{symbol}: 重置buy1_done，允许下次BUY1触发")
        elif cached_exit_signal == "EXIT_SHORT":
            self.sell1_done[symbol] = False
            self._log(f"{symbol}: 重置sell1_done，允许下次SELL1触发")

        self._log(f"{symbol}: {reason} → L2正常接管")

        return result

    def _check_exit(self, symbol: str, indicator: IndicatorSignal) -> Optional[PluginResult]:
        """[已废弃] 原立即退出逻辑，保留兼容性"""
        # v0.6.1: 改用 _detect_exit_signal + _verify_and_execute_exit
        return None

    # ========================================================================
    # 诊断功能
    # ========================================================================

    def _get_l1_direction(self, l1_signals: dict) -> str:
        """获取L1综合方向"""
        sig = l1_signals.get("signal", "HOLD")
        if sig in BUY_SIGNALS:
            return "BUY"
        elif sig in SELL_SIGNALS:
            return "SELL"
        return "HOLD"

    def _diagnose_module(
        self,
        name: str,
        signal: str,
        confidence: float,
        indicator: IndicatorSignal,
    ) -> ModuleDiagnosis:
        """诊断单个模块"""

        if indicator.is_buy1():
            # 指标说买
            if signal in BUY_SIGNALS:
                error_type = ErrorType.MATCH
            elif signal in SELL_SIGNALS:
                error_type = ErrorType.OPPOSITE
            else:
                error_type = ErrorType.MISS

        elif indicator.is_sell1():
            # 指标说卖
            if signal in SELL_SIGNALS:
                error_type = ErrorType.MATCH
            elif signal in BUY_SIGNALS:
                error_type = ErrorType.OPPOSITE
            else:
                error_type = ErrorType.MISS

        else:
            # 指标无信号
            if signal in HOLD_SIGNALS:
                error_type = ErrorType.MATCH
            else:
                error_type = ErrorType.FALSE_ALARM

        return ModuleDiagnosis(
            name=name,
            signal=signal,
            confidence=confidence,
            error_type=error_type,
        )

    def _update_stats(
        self,
        symbol: str,
        ai_diag: ModuleDiagnosis,
        human_diag: ModuleDiagnosis,
        tech_diag: ModuleDiagnosis,
    ):
        """更新统计数据"""
        with self._stats_lock:
            if symbol not in self.diagnosis_stats:
                self.diagnosis_stats[symbol] = {
                    "total": 0,
                    "ai": {"match": 0, "opposite": 0, "miss": 0, "false_alarm": 0},
                    "human": {"match": 0, "opposite": 0, "miss": 0, "false_alarm": 0},
                    "tech": {"match": 0, "opposite": 0, "miss": 0, "false_alarm": 0},
                }

            stats = self.diagnosis_stats[symbol]
            stats["total"] += 1

            for diag, key in [(ai_diag, "ai"), (human_diag, "human"), (tech_diag, "tech")]:
                error_key = diag.error_type.value.lower()
                stats[key][error_key] = stats[key].get(error_key, 0) + 1

    def get_stats_summary(self, symbol: str = None) -> dict:
        """获取统计汇总"""
        with self._stats_lock:
            if symbol:
                stats = self.diagnosis_stats.get(symbol, {})
            else:
                # 汇总所有品种
                stats = {"total": 0, "ai": {}, "human": {}, "tech": {}}
                for s in self.diagnosis_stats.values():
                    stats["total"] += s.get("total", 0)
                    for module in ["ai", "human", "tech"]:
                        for k, v in s.get(module, {}).items():
                            stats[module][k] = stats[module].get(k, 0) + v

            # 计算准确率
            result = {"total": stats.get("total", 0), "modules": {}}
            for module in ["ai", "human", "tech"]:
                m_stats = stats.get(module, {})
                total = sum(m_stats.values())
                match = m_stats.get("match", 0)
                result["modules"][module] = {
                    "total": total,
                    "match": match,
                    "accuracy": round(match / total, 3) if total > 0 else 0,
                    "errors": {
                        "OPPOSITE": m_stats.get("opposite", 0),
                        "MISS": m_stats.get("miss", 0),
                        "FALSE_ALARM": m_stats.get("false_alarm", 0),
                    }
                }

            return result

    # ========================================================================
    # 日志
    # ========================================================================

    def _write_diagnosis_log(
        self,
        symbol: str,
        result: PluginResult,
        l1_signals: dict,
        indicator: IndicatorSignal,
    ):
        """写诊断日志"""
        if not self.log_enabled:
            return

        try:
            log_path = os.path.join(self.log_dir, DIAGNOSIS_LOG_FILE)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            lines = []
            lines.append(f"\n===== {timestamp} {symbol} =====")

            # 模式标题
            if result.mode == PluginMode.PLUGIN_AGREE:
                lines.append("【外挂激活 - L1一致】")
            elif result.mode == PluginMode.PLUGIN_CONFLICT:
                lines.append("【外挂激活 - L1冲突】")
            elif result.mode == PluginMode.L2_NORMAL:
                lines.append("【L2正常工作】")
            elif result.mode == PluginMode.PLUGIN_EXIT:
                lines.append("【外挂退出】")
            elif result.mode == PluginMode.PLUGIN_FILTERED:
                lines.append("【外挂过滤 - 趋势条件不满足】")

            lines.append("")

            # v0.8: 如果被过滤，显示过滤原因
            if result.filter_reason:
                lines.append(f"过滤原因: {result.filter_reason}")
                lines.append("")

            # 指标信号
            lines.append(f"指标信号: {indicator.signal}")
            st_zone = "红区" if indicator.supertrend_trend == -1 else "绿区"
            qqe_color = "蓝" if indicator.qqe_hist > 0 else "红"
            macd_color = "蓝" if indicator.macd_hist > 0 else "红"
            lines.append(f"  SuperTrend: {st_zone} (trend={indicator.supertrend_trend})")
            lines.append(f"  QQE: {indicator.qqe_hist:+.2f} ({qqe_color})")
            lines.append(f"  MACD: {indicator.macd_hist:+.4f} ({macd_color})")
            lines.append("")

            # L1各模块 (仅在有信号时显示)
            if indicator.has_signal() and result.ai_diagnosis:
                lines.append("L1 各模块:")
                for diag in [result.ai_diagnosis, result.human_diagnosis, result.tech_diagnosis]:
                    if diag:
                        mark = "[OK] MATCH" if diag.is_match() else f"[X] {diag.error_type.value}"
                        if diag.error_type == ErrorType.MISS:
                            mark = f"[!] {diag.error_type.value}"
                        lines.append(f"  {diag.name:6}: {diag.signal:6} (conf={diag.confidence:.2f}) → {mark}")
                lines.append("")

            # L1综合和决策
            lines.append(f"L1综合: {result.l1_signal}")
            lines.append(f"决策: {result.reason}")

            lines.append("=" * 40)

            # 写入文件
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))

        except Exception as e:
            self._log(f"写日志失败: {e}")

    def save_summary(self):
        """保存统计汇总到JSON"""
        if not self.log_enabled:
            return

        try:
            summary_path = os.path.join(self.log_dir, SUMMARY_LOG_FILE)
            summary = {
                "timestamp": datetime.now().isoformat(),
                "version": self.VERSION,
                "overall": self.get_stats_summary(),
                "by_symbol": {s: self.get_stats_summary(s) for s in self.diagnosis_stats},
                "filter_stats": self.get_filter_stats(),  # v0.8新增
            }

            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            self._log(f"统计汇总已保存: {summary_path}")

        except Exception as e:
            self._log(f"保存汇总失败: {e}")


# ========================================================================
# 全局单例
# ========================================================================

_global_plugin: SuperTrendPlugin = None
_plugin_lock = threading.Lock()

def get_supertrend_plugin() -> SuperTrendPlugin:
    """获取全局外挂实例"""
    global _global_plugin
    with _plugin_lock:
        if _global_plugin is None:
            _global_plugin = SuperTrendPlugin()
            _st_logger.info(f"[SuperTrend_Plugin] Init OK v{SuperTrendPlugin.VERSION}")
        return _global_plugin


# ========================================================================
# 测试
# ========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SuperTrend Plugin v0.8 测试 (趋势过滤)")
    print("=" * 60)

    plugin = get_supertrend_plugin()

    # 模拟数据
    np.random.seed(42)
    n_ohlcv = 30
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

    # 模拟L1信号
    l1_signals = {
        "ai_signal": "BUY",
        "ai_confidence": 0.72,
        "human_signal": "HOLD",
        "human_confidence": 0.55,
        "tech_signal": "BUY",
        "tech_confidence": 0.78,
        "signal": "BUY",
    }

    # v0.8: 模拟市场数据
    market_data = {
        "regime": "TRENDING",  # 趋势市
        "direction": "UP",
        "position_pct": 60,  # 60%位置
    }

    # 处理
    result = plugin.process(
        symbol="ZECUSDC",
        ohlcv_bars=ohlcv_bars,
        close_prices=closes.tolist(),
        l1_signals=l1_signals,
        market_data=market_data,
    )

    print(f"\n结果:")
    print(f"  模式: {result.mode.value}")
    print(f"  动作: {result.action}")
    print(f"  指标: {result.indicator_signal}")
    print(f"  原因: {result.reason}")
    if result.filter_reason:
        print(f"  过滤: {result.filter_reason}")
    print(f"  ST趋势: {result.supertrend_trend}")
    print(f"  QQE: {result.qqe_hist:.2f}")
    print(f"  MACD: {result.macd_hist:.4f}")

    # 测试过滤
    print("\n" + "=" * 60)
    print("测试过滤场景")
    print("=" * 60)

    # 场景1: 震荡市
    market_data_ranging = {"regime": "RANGING", "direction": "SIDE", "position_pct": 50}
    result2 = plugin.process("TEST1", ohlcv_bars, closes.tolist(), l1_signals, market_data_ranging)
    print(f"\n场景1 震荡市: {result2.mode.value} | {result2.filter_reason}")

    # 场景2: 高位买入
    market_data_high = {"regime": "TRENDING", "direction": "UP", "position_pct": 85}
    result3 = plugin.process("TEST2", ohlcv_bars, closes.tolist(), l1_signals, market_data_high)
    print(f"场景2 高位85%: {result3.mode.value} | {result3.filter_reason}")

    print("\n" + "=" * 60)

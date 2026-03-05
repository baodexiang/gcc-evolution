# ========================================================================
# Vision形态外挂模块 v2.0 (原双底双顶外挂 v1.1)
# ========================================================================
#
# 版本: 2.0
# 日期: 2026-02-07
#
# v2.0更新 (2026-02-07):
#   - 完全重写: 删除代码检测逻辑(swing point/偏差/颈线计算)
#   - 改为读取 state/vision/pattern_latest.json (Vision形态识别结果)
#   - 扩展PatternType: 8种形态(双底/双顶/头肩底/头肩顶/123反转/2B假突破)
#   - confidence→quality映射: >=0.8→3, >=0.7→2, >=0.6→1
#   - stage=BREAKOUT时才生成BUY1/SELL1信号
#
# 核心功能:
#   读取Vision v3.1的形态识别结果，转换为扫描引擎可用的信号格式
#
# 支持形态:
#   1. DOUBLE_BOTTOM (W形) → BUY
#   2. DOUBLE_TOP (M形) → SELL
#   3. HEAD_SHOULDERS_BOTTOM → BUY
#   4. HEAD_SHOULDERS_TOP → SELL
#   5. REVERSAL_123_BUY → BUY
#   6. REVERSAL_123_SELL → SELL
#   7. FALSE_BREAK_BUY (2B) → BUY
#   8. FALSE_BREAK_SELL (2B) → SELL
#
# ========================================================================

import json
import os
import threading
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from enum import Enum


# ========================================================================
# 配置常量
# ========================================================================

LOG_DIR = "logs"
DOUBLE_PATTERN_LOG_FILE = "double_pattern_plugin.log"

# Vision形态结果文件 (由 vision_analyzer.py v3.1 写入)
PATTERN_LATEST_FILE = os.path.join("state", "vision", "pattern_latest.json")

# 结果过期时间 (秒) — 超过此时间的结果视为过期
PATTERN_RESULT_MAX_AGE_SECONDS = 14400  # 4小时

# 触发阈值
MIN_PATTERN_CONFIDENCE = 0.70
REQUIRE_VOLUME_CONFIRM_ON_BREAKOUT = True
PATTERN_MIN_CONFIDENCE_MAP = {
    "DOUBLE_BOTTOM": 0.70,
    "DOUBLE_TOP": 0.70,
    "HEAD_SHOULDERS_BOTTOM": 0.72,
    "HEAD_SHOULDERS_TOP": 0.72,
    "REVERSAL_123_BUY": 0.74,
    "REVERSAL_123_SELL": 0.74,
    "FALSE_BREAK_BUY": 0.76,
    "FALSE_BREAK_SELL": 0.76,
    # v2.1 Phase I: 固定方向形态
    "ASC_TRIANGLE": 0.72,
    "DESC_TRIANGLE": 0.72,
    "WEDGE_RISING": 0.74,
    "WEDGE_FALLING": 0.74,
}

# 二次确认: BREAKOUT需连续命中2次才放行
CONSISTENCY_CONFIRM_COUNT = 2

# P2: 数值二次确认（图像识别 + 价格约束）
ENABLE_NUMERIC_CONFIRM = True
NUMERIC_CONFIRM_EMA_PERIOD = 20

# 形态风控统计
PATTERN_GUARD_STATS_FILE = os.path.join("state", "vision", "pattern_guard_stats.json")


# ========================================================================
# 枚举定义
# ========================================================================

class PatternType(Enum):
    """形态类型 (v2.1: 扩展到12种, +4固定方向形态)"""
    DOUBLE_BOTTOM = "DOUBLE_BOTTOM"
    DOUBLE_TOP = "DOUBLE_TOP"
    HEAD_SHOULDERS_BOTTOM = "HEAD_SHOULDERS_BOTTOM"
    HEAD_SHOULDERS_TOP = "HEAD_SHOULDERS_TOP"
    REVERSAL_123_BUY = "REVERSAL_123_BUY"
    REVERSAL_123_SELL = "REVERSAL_123_SELL"
    FALSE_BREAK_BUY = "FALSE_BREAK_BUY"
    FALSE_BREAK_SELL = "FALSE_BREAK_SELL"
    # v2.1 Phase I: 固定方向形态
    ASC_TRIANGLE = "ASC_TRIANGLE"
    DESC_TRIANGLE = "DESC_TRIANGLE"
    WEDGE_RISING = "WEDGE_RISING"
    WEDGE_FALLING = "WEDGE_FALLING"
    NONE = "NONE"


class PatternStage(Enum):
    """形态阶段"""
    FORMING = "FORMING"
    BREAKOUT = "BREAKOUT"
    NONE = "NONE"


class PluginSignal(Enum):
    """外挂信号类型"""
    BUY1 = "BUY1"
    SELL1 = "SELL1"
    WAITING = "WAITING"
    NONE = "NONE"


# 形态→信号方向映射
PATTERN_SIGNAL_MAP = {
    "DOUBLE_BOTTOM": "BUY",
    "HEAD_SHOULDERS_BOTTOM": "BUY",
    "REVERSAL_123_BUY": "BUY",
    "FALSE_BREAK_BUY": "BUY",
    "ASC_TRIANGLE": "BUY",
    "WEDGE_FALLING": "BUY",
    "DOUBLE_TOP": "SELL",
    "HEAD_SHOULDERS_TOP": "SELL",
    "REVERSAL_123_SELL": "SELL",
    "FALSE_BREAK_SELL": "SELL",
    "DESC_TRIANGLE": "SELL",
    "WEDGE_RISING": "SELL",
}


# ========================================================================
# 数据结构
# ========================================================================

@dataclass
class PatternResult:
    """形态检测结果 (保持与v1.1兼容的接口)"""
    pattern: PatternType = PatternType.NONE
    stage: PatternStage = PatternStage.NONE
    signal: PluginSignal = PluginSignal.NONE
    quality_score: int = 0        # 1-3, 3最高
    neckline: float = 0.0
    target: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "pattern": self.pattern.value,
            "stage": self.stage.value,
            "signal": self.signal.value,
            "quality_score": self.quality_score,
            "neckline": self.neckline,
            "target": self.target,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "confidence": self.confidence,
            "reason": self.reason,
            "details": self.details
        }


# ========================================================================
# 辅助函数
# ========================================================================

def log_to_file(message: str):
    """写入日志文件"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, DOUBLE_PATTERN_LOG_FILE)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def _read_pattern_latest(symbol: str) -> Optional[Dict]:
    """
    读取 state/vision/pattern_latest.json 中指定品种的形态结果
    Returns: {pattern, stage, confidence, volume_confirmed, reason, timestamp} or None
    """
    try:
        if not os.path.exists(PATTERN_LATEST_FILE):
            return None
        with open(PATTERN_LATEST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data.get(symbol)
    except Exception as e:
        log_to_file(f"[{symbol}] 读取pattern_latest.json失败: {e}")
        return None


def _confidence_to_quality(confidence: float) -> int:
    """confidence→quality映射: >=0.8→3, >=0.7→2, >=0.6→1"""
    if confidence >= 0.8:
        return 3
    elif confidence >= 0.7:
        return 2
    elif confidence >= 0.6:
        return 1
    return 0


def _get_min_confidence(pattern_str: str) -> float:
    return PATTERN_MIN_CONFIDENCE_MAP.get(pattern_str, MIN_PATTERN_CONFIDENCE)


def _calc_ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return float(ema)


def _numeric_confirm(action: str, ohlcv_bars: Optional[List[Dict]], current_price: float):
    if not ENABLE_NUMERIC_CONFIRM:
        return True, "numeric confirm disabled"
    if not ohlcv_bars or len(ohlcv_bars) < NUMERIC_CONFIRM_EMA_PERIOD:
        return False, f"K线不足{NUMERIC_CONFIRM_EMA_PERIOD}根，无法做数值确认"

    closes = []
    for bar in ohlcv_bars:
        try:
            closes.append(float(bar.get("close", 0)))
        except (TypeError, ValueError):
            closes.append(0.0)

    ema20 = _calc_ema(closes, NUMERIC_CONFIRM_EMA_PERIOD)
    if ema20 is None:
        return False, "EMA20计算失败"

    prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
    curr_close = closes[-1]

    if action == "BUY":
        if current_price <= ema20:
            return False, f"BUY数值确认失败: 价格{current_price:.2f}<=EMA{NUMERIC_CONFIRM_EMA_PERIOD}{ema20:.2f}"
        if curr_close < prev_close:
            return False, f"BUY数值确认失败: 短动量转弱({curr_close:.2f}<{prev_close:.2f})"
    elif action == "SELL":
        if current_price >= ema20:
            return False, f"SELL数值确认失败: 价格{current_price:.2f}>=EMA{NUMERIC_CONFIRM_EMA_PERIOD}{ema20:.2f}"
        if curr_close > prev_close:
            return False, f"SELL数值确认失败: 短动量转强({curr_close:.2f}>{prev_close:.2f})"

    return True, f"EMA{NUMERIC_CONFIRM_EMA_PERIOD}确认通过"


# ========================================================================
# Vision形态外挂主类
# ========================================================================

class DoublePatternPlugin:
    """
    Vision形态外挂 v2.0

    读取Vision v3.1的形态识别结果，
    转换为扫描引擎可用的PatternResult信号格式。
    """

    def __init__(self, config: Dict = None):
        self._lock = threading.Lock()
        self._last_results: Dict[str, PatternResult] = {}
        self._pending_confirm: Dict[str, Dict] = {}
        self._guard_stats = self._load_guard_stats()
        log_to_file("DoublePatternPlugin v2.0 initialized (Vision mode)")

    def _load_guard_stats(self) -> Dict:
        try:
            if os.path.exists(PATTERN_GUARD_STATS_FILE):
                with open(PATTERN_GUARD_STATS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"symbols": {}, "updated_at": None}

    def _save_guard_stats(self):
        try:
            os.makedirs(os.path.dirname(PATTERN_GUARD_STATS_FILE), exist_ok=True)
            self._guard_stats["updated_at"] = datetime.now().isoformat()
            tmp = f"{PATTERN_GUARD_STATS_FILE}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._guard_stats, f, ensure_ascii=False, indent=2)
            os.replace(tmp, PATTERN_GUARD_STATS_FILE)
        except Exception:
            pass

    def _record_guard_stat(self, symbol: str, event: str):
        symbols = self._guard_stats.setdefault("symbols", {})
        sym = symbols.setdefault(symbol, {})
        sym[event] = int(sym.get(event, 0)) + 1
        self._save_guard_stats()

    def process_for_scan(
        self,
        symbol: str,
        ohlcv_bars=None,
        current_trend: str = "SIDE",
        pos_in_channel: float = 0.5,
        current_price: float = None,
    ) -> PatternResult:
        """
        v2.0: 扫描引擎专用处理接口 (读取Vision结果)

        参数保持与v1.1兼容(ohlcv_bars/current_trend/pos_in_channel),
        但内部不再使用代码检测, 改为读取pattern_latest.json

        Args:
            symbol: 交易标的
            ohlcv_bars: 不再使用, 保留兼容
            current_trend: 不再使用, 保留兼容
            pos_in_channel: 不再使用, 保留兼容
            current_price: 当前价格 (可选)

        Returns:
            PatternResult
        """
        result = PatternResult()

        with self._lock:
            try:
                # 1. 读取Vision形态结果
                vision_data = _read_pattern_latest(symbol)
                if not vision_data:
                    result.reason = "无Vision形态数据"
                    self._record_guard_stat(symbol, "skip_no_data")
                    return result

                # 2. 检查结果是否过期
                ts_str = vision_data.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        age_seconds = (datetime.now() - ts).total_seconds()
                        if age_seconds > PATTERN_RESULT_MAX_AGE_SECONDS:
                            result.reason = f"Vision结果已过期 ({int(age_seconds/60)}分钟前)"
                            self._record_guard_stat(symbol, "skip_stale")
                            return result
                    except (ValueError, TypeError):
                        pass

                # 3. 解析形态
                pattern_str = vision_data.get("pattern", "NONE").upper()
                if pattern_str == "NONE":
                    result.reason = "Vision未检测到形态"
                    self._record_guard_stat(symbol, "skip_pattern_none")
                    return result

                # 验证是否为已知形态
                try:
                    pattern_type = PatternType(pattern_str)
                except ValueError:
                    result.reason = f"未知形态类型: {pattern_str}"
                    self._record_guard_stat(symbol, "skip_unknown_pattern")
                    return result

                # 4. 解析confidence和stage
                confidence = float(vision_data.get("confidence", 0))
                stage_str = vision_data.get("stage", "NONE").upper()
                volume_confirmed = vision_data.get("volume_confirmed", False)
                reason = vision_data.get("reason", "")

                # confidence阈值检查
                min_conf = _get_min_confidence(pattern_str)
                if confidence < min_conf:
                    result.reason = f"形态置信度不足: {confidence:.2f} < {min_conf:.2f}"
                    self._record_guard_stat(symbol, "skip_low_confidence")
                    return result

                # stage解析
                try:
                    stage = PatternStage(stage_str)
                except ValueError:
                    stage = PatternStage.NONE

                # 5. quality评分
                quality_score = _confidence_to_quality(confidence)

                # 6. 信号方向
                signal_direction = PATTERN_SIGNAL_MAP.get(pattern_str)
                if not signal_direction:
                    result.reason = f"形态无对应信号: {pattern_str}"
                    self._record_guard_stat(symbol, "skip_no_direction")
                    return result

                # 7. 只有BREAKOUT阶段才生成交易信号
                signal = PluginSignal.NONE
                if stage == PatternStage.BREAKOUT:
                    if REQUIRE_VOLUME_CONFIRM_ON_BREAKOUT and not volume_confirmed:
                        result.reason = "BREAKOUT缺少量能确认(volume_confirmed=false)"
                        self._record_guard_stat(symbol, "skip_no_volume_confirm")
                        return result

                    confirm_key = f"{pattern_str}:{stage_str}:{signal_direction}"
                    pending = self._pending_confirm.get(symbol)
                    if not pending or pending.get("key") != confirm_key:
                        self._pending_confirm[symbol] = {
                            "key": confirm_key,
                            "seen_count": 1,
                            "vision_timestamp": ts_str,
                        }
                        result.reason = f"形态待二次确认: {pattern_str} conf={confidence:.2f}"
                        self._record_guard_stat(symbol, "pending_consistency_confirm")
                        return result

                    pending["seen_count"] = int(pending.get("seen_count", 1)) + 1
                    pending["vision_timestamp"] = ts_str
                    if pending["seen_count"] < CONSISTENCY_CONFIRM_COUNT:
                        result.reason = f"形态待二次确认: {pattern_str}({pending['seen_count']}/{CONSISTENCY_CONFIRM_COUNT})"
                        self._record_guard_stat(symbol, "pending_consistency_confirm")
                        return result

                    self._pending_confirm.pop(symbol, None)
                    probe_price = float(current_price) if current_price is not None else 0.0
                    numeric_ok, numeric_reason = _numeric_confirm(signal_direction, ohlcv_bars, probe_price)
                    if not numeric_ok:
                        result.reason = numeric_reason
                        self._record_guard_stat(symbol, "skip_numeric_confirm")
                        return result
                    signal = PluginSignal.BUY1 if signal_direction == "BUY" else PluginSignal.SELL1
                elif stage == PatternStage.FORMING:
                    self._pending_confirm.pop(symbol, None)
                    signal = PluginSignal.WAITING
                    self._record_guard_stat(symbol, "skip_stage_forming")

                # 8. 构建结果
                result.pattern = pattern_type
                result.stage = stage
                result.signal = signal
                result.quality_score = quality_score
                result.confidence = confidence
                result.entry_price = round(current_price, 2) if current_price else 0.0
                result.reason = f"Vision形态: {pattern_str} stage={stage_str} conf={confidence:.2f} vol={volume_confirmed}"
                result.details = {
                    "source": "vision_gpt4o",
                    "volume_confirmed": volume_confirmed,
                    "vision_reason": reason,
                    "vision_timestamp": ts_str,
                }

                log_to_file(f"[{symbol}] {result.reason}")
                self._last_results[symbol] = result
                if signal in (PluginSignal.BUY1, PluginSignal.SELL1):
                    self._record_guard_stat(symbol, "pass_confirmed_signal")

            except Exception as e:
                result.reason = f"检测异常: {e}"
                log_to_file(f"[{symbol}] ERROR: {e}")

        return result

    # 保持v1.1兼容接口
    def process(self, symbol, ohlcv_bars, l1_trend, pos_in_channel, current_price=None):
        return self.process_for_scan(symbol, ohlcv_bars, l1_trend, pos_in_channel, current_price)

    def should_activate_for_scan(self, result: PatternResult) -> bool:
        if result is None:
            return False
        return result.signal in (PluginSignal.BUY1, PluginSignal.SELL1)

    def get_action_for_scan(self, result: PatternResult) -> str:
        if result is None or result.signal == PluginSignal.NONE:
            return "NONE"
        if result.signal == PluginSignal.BUY1:
            return "BUY"
        if result.signal == PluginSignal.SELL1:
            return "SELL"
        return "NONE"

    def should_bypass_l2(self, result: PatternResult) -> bool:
        return result.signal in (PluginSignal.BUY1, PluginSignal.SELL1)

    def get_last_result(self, symbol: str) -> Optional[PatternResult]:
        return self._last_results.get(symbol)


# ========================================================================
# 单例实例
# ========================================================================

_plugin_instance: Optional[DoublePatternPlugin] = None
_plugin_lock = threading.Lock()


def get_double_pattern_plugin() -> DoublePatternPlugin:
    """获取外挂单例"""
    global _plugin_instance
    if _plugin_instance is None:
        with _plugin_lock:
            if _plugin_instance is None:
                _plugin_instance = DoublePatternPlugin()
    return _plugin_instance


# ========================================================================
# 便捷函数
# ========================================================================

def process_double_pattern(symbol, ohlcv_bars, l1_trend, pos_in_channel, current_price=None):
    plugin = get_double_pattern_plugin()
    result = plugin.process(symbol, ohlcv_bars, l1_trend, pos_in_channel, current_price)
    return result.to_dict()


# ========================================================================
# 测试入口
# ========================================================================

if __name__ == "__main__":
    print("DoublePatternPlugin v2.0 (Vision mode) - Test")
    plugin = get_double_pattern_plugin()

    # 测试读取Vision结果
    result = plugin.process_for_scan(
        symbol="BTCUSDC",
        current_price=97000
    )
    print(f"Result: {result.to_dict()}")

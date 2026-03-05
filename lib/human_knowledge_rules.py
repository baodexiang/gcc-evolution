#!/usr/bin/env python3
"""
Human Knowledge Rules v1.0
==========================
来源: 云聪13买点交易系统 (NotebookLM)

5个核心规则:
1. RULE_001: 第二天原则 - 大K线次日验证
2. RULE_002: 巨量三天法则 - 巨量后三天不创新高
3. RULE_003: 连续反向大K线预警 - 趋势反转预警
4. RULE_004: 三段式结构 - 放量大阳+缩量小K线群+再度放量大阳
5. RULE_005: 45度角理想趋势 - 趋势角度分析

作者: AI Trading System
日期: 2026-01-01
"""

import sys
import math
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, Exception):
        pass

# 导入规则验证器
try:
    from lib.human_rule_validator import is_rule_enabled, get_rule_params, record_rule_trigger
    VALIDATOR_LOADED = True
except ImportError:
    try:
        from human_rule_validator import is_rule_enabled, get_rule_params, record_rule_trigger
        VALIDATOR_LOADED = True
    except ImportError:
        VALIDATOR_LOADED = False
        def is_rule_enabled(rule_id): return False
        def get_rule_params(rule_id): return {}
        def record_rule_trigger(*args, **kwargs): pass


class HumanKnowledgeRules:
    """Human知识点规则引擎"""

    def __init__(self, symbol: str = None, bar_index: int = 0):
        """
        初始化规则引擎

        Args:
            symbol: 品种代码
            bar_index: 当前K线索引 (用于延迟验证)
        """
        self.symbol = symbol or "UNKNOWN"
        self.bar_index = bar_index
        self.triggered_rules = []  # 记录触发的规则

    def analyze_all_rules(self, ohlcv_bars: List[Dict]) -> Dict[str, Any]:
        """
        分析所有启用的规则

        Args:
            ohlcv_bars: K线数据列表

        Returns:
            {
                "bull_adjustment": int,    # 多头因素调整 (-5 to +5)
                "bear_adjustment": int,    # 空头因素调整 (-5 to +5)
                "signals": List[str],      # 触发的信号
                "warnings": List[str],     # 警告信息
                "rule_details": Dict,      # 各规则详情
            }
        """
        result = {
            "bull_adjustment": 0,
            "bear_adjustment": 0,
            "signals": [],
            "warnings": [],
            "rule_details": {},
        }

        if not ohlcv_bars or len(ohlcv_bars) < 5:
            return result

        # RULE_001: 第二天原则
        if is_rule_enabled("RULE_001_SECOND_DAY_VERIFY"):
            r1 = self._rule_001_second_day_verify(ohlcv_bars)
            result["rule_details"]["RULE_001"] = r1
            if r1["triggered"]:
                result["signals"].append(r1["signal"])
                if r1["signal"] == "INVALIDATE_BULLISH":
                    result["bear_adjustment"] += 2
                elif r1["signal"] == "INVALIDATE_BEARISH":
                    result["bull_adjustment"] += 2

        # RULE_002: 巨量三天法则
        if is_rule_enabled("RULE_002_VOLUME_THREE_DAY"):
            r2 = self._rule_002_volume_three_day(ohlcv_bars)
            result["rule_details"]["RULE_002"] = r2
            if r2["triggered"]:
                result["signals"].append(r2["signal"])
                if r2["signal"] == "VOLUME_TOP_WARNING":
                    result["bear_adjustment"] += 3
                    result["warnings"].append("巨量三天法则触发：可能见顶")

        # RULE_003: 连续反向大K线预警
        if is_rule_enabled("RULE_003_TWO_REVERSE_CANDLES"):
            r3 = self._rule_003_two_reverse_candles(ohlcv_bars)
            result["rule_details"]["RULE_003"] = r3
            if r3["triggered"]:
                result["signals"].append(r3["signal"])
                if r3["signal"] == "TREND_REVERSAL_BEAR":
                    result["bear_adjustment"] += 3
                    result["warnings"].append("连续反向大阴线：趋势反转预警")
                elif r3["signal"] == "TREND_REVERSAL_BULL":
                    result["bull_adjustment"] += 3
                    result["warnings"].append("连续反向大阳线：趋势反转预警")

        # RULE_004: 三段式结构
        if is_rule_enabled("RULE_004_THREE_STAGE_PATTERN"):
            r4 = self._rule_004_three_stage_pattern(ohlcv_bars)
            result["rule_details"]["RULE_004"] = r4
            if r4["triggered"]:
                result["signals"].append(r4["signal"])
                if r4["signal"] == "THREE_STAGE_BULLISH":
                    result["bull_adjustment"] += 4
                elif r4["signal"] == "THREE_STAGE_BEARISH":
                    result["bear_adjustment"] += 4

        # RULE_005: 45度角理想趋势
        if is_rule_enabled("RULE_005_ANGLE_45_IDEAL"):
            r5 = self._rule_005_angle_analysis(ohlcv_bars)
            result["rule_details"]["RULE_005"] = r5
            if r5["triggered"]:
                result["signals"].append(r5["signal"])
                if r5["signal"] == "IDEAL_UPTREND":
                    result["bull_adjustment"] += 2
                elif r5["signal"] == "OVERHEAT_WARNING":
                    result["warnings"].append(f"趋势过热警告：角度{r5.get('angle', 0):.1f}°>70°")
                    result["bear_adjustment"] += 1
                elif r5["signal"] == "IDEAL_DOWNTREND":
                    result["bear_adjustment"] += 2

        return result

    def _get_candle_body_ratio(self, bar: Dict) -> float:
        """计算K线实体占比"""
        o = float(bar.get("open", bar.get("o", 0)))
        h = float(bar.get("high", bar.get("h", 0)))
        l = float(bar.get("low", bar.get("l", 0)))
        c = float(bar.get("close", bar.get("c", 0)))

        if h == l or o == 0:
            return 0

        body = abs(c - o)
        range_hl = h - l
        return body / range_hl if range_hl > 0 else 0

    def _is_big_candle(self, bar: Dict, threshold: float = 0.03) -> Tuple[bool, str]:
        """
        判断是否为大K线

        Returns:
            (is_big, direction) - direction: "BULLISH" / "BEARISH" / "NONE"
        """
        o = float(bar.get("open", bar.get("o", 0)))
        c = float(bar.get("close", bar.get("c", 0)))

        if o == 0:
            return False, "NONE"

        change = (c - o) / o

        if change >= threshold:
            return True, "BULLISH"
        elif change <= -threshold:
            return True, "BEARISH"
        return False, "NONE"

    def _rule_001_second_day_verify(self, ohlcv_bars: List[Dict]) -> Dict:
        """
        RULE_001: 第二天原则

        规则：
        - 大阴线次日高开或不跌 → 下跌无效
        - 大阳线次日不涨反跌 → 上涨无效
        """
        result = {"triggered": False, "signal": None, "reason": ""}

        if len(ohlcv_bars) < 2:
            return result

        params = get_rule_params("RULE_001_SECOND_DAY_VERIFY")
        threshold = params.get("big_candle_threshold_crypto", 0.03)

        # 检查前一天是否大K线
        prev_bar = ohlcv_bars[-2]
        curr_bar = ohlcv_bars[-1]

        is_big, direction = self._is_big_candle(prev_bar, threshold)

        if not is_big:
            return result

        prev_close = float(prev_bar.get("close", prev_bar.get("c", 0)))
        curr_open = float(curr_bar.get("open", curr_bar.get("o", 0)))
        curr_close = float(curr_bar.get("close", curr_bar.get("c", 0)))

        if prev_close == 0:
            return result

        # 大阴线 + 次日高开或不跌 → 下跌无效
        if direction == "BEARISH":
            gap = (curr_open - prev_close) / prev_close
            change = (curr_close - curr_open) / curr_open if curr_open > 0 else 0

            if gap > 0.005 or change > 0:  # 高开0.5%或收涨
                result["triggered"] = True
                result["signal"] = "INVALIDATE_BEARISH"
                result["reason"] = f"大阴线次日{('高开' if gap > 0 else '收涨')}，下跌无效"
                self._record_trigger("RULE_001_SECOND_DAY_VERIFY", "INVALIDATE_BEARISH",
                                    {"prev_direction": direction, "gap": gap, "change": change})

        # 大阳线 + 次日不涨反跌 → 上涨无效
        elif direction == "BULLISH":
            change = (curr_close - curr_open) / curr_open if curr_open > 0 else 0

            if change < -0.005:  # 收跌0.5%
                result["triggered"] = True
                result["signal"] = "INVALIDATE_BULLISH"
                result["reason"] = f"大阳线次日收跌{change:.1%}，上涨无效"
                self._record_trigger("RULE_001_SECOND_DAY_VERIFY", "INVALIDATE_BULLISH",
                                    {"prev_direction": direction, "change": change})

        return result

    def _rule_002_volume_three_day(self, ohlcv_bars: List[Dict]) -> Dict:
        """
        RULE_002: 巨量三天法则

        规则：巨量后三天不创新高 → 卖出信号
        """
        result = {"triggered": False, "signal": None, "reason": ""}

        if len(ohlcv_bars) < 10:
            return result

        params = get_rule_params("RULE_002_VOLUME_THREE_DAY")
        volume_spike_ratio = params.get("volume_spike_ratio", 2.0)
        verify_bars = params.get("verify_window_bars", 3)
        new_high_tolerance = params.get("new_high_tolerance", 0.002)

        # 计算历史平均成交量
        vol_history = [float(bar.get("volume", bar.get("v", 0))) for bar in ohlcv_bars[-30:-4]]
        if not vol_history:
            return result
        avg_vol = sum(vol_history) / len(vol_history)

        if avg_vol == 0:
            return result

        # 检查4天前是否巨量
        check_bar = ohlcv_bars[-4]
        check_vol = float(check_bar.get("volume", check_bar.get("v", 0)))
        check_high = float(check_bar.get("high", check_bar.get("h", 0)))

        if check_vol / avg_vol < volume_spike_ratio:
            return result  # 不是巨量

        # 检查后3天是否创新高
        made_new_high = False
        for i in range(-3, 0):
            bar_high = float(ohlcv_bars[i].get("high", ohlcv_bars[i].get("h", 0)))
            if bar_high > check_high * (1 + new_high_tolerance):
                made_new_high = True
                break

        if not made_new_high:
            result["triggered"] = True
            result["signal"] = "VOLUME_TOP_WARNING"
            result["reason"] = f"巨量({check_vol/avg_vol:.1f}x)后{verify_bars}天未创新高，可能见顶"
            self._record_trigger("RULE_002_VOLUME_THREE_DAY", "VOLUME_TOP_WARNING",
                                {"volume_ratio": check_vol/avg_vol, "check_high": check_high})

        return result

    def _rule_003_two_reverse_candles(self, ohlcv_bars: List[Dict]) -> Dict:
        """
        RULE_003: 连续反向大K线预警

        规则：连续两根反向大K线 → 趋势反转预警
        """
        result = {"triggered": False, "signal": None, "reason": ""}

        if len(ohlcv_bars) < 3:
            return result

        params = get_rule_params("RULE_003_TWO_REVERSE_CANDLES")
        min_body_ratio = params.get("min_candle_body_ratio", 0.03)

        # 检查最近两根K线
        bar1 = ohlcv_bars[-2]
        bar2 = ohlcv_bars[-1]

        is_big1, dir1 = self._is_big_candle(bar1, min_body_ratio)
        is_big2, dir2 = self._is_big_candle(bar2, min_body_ratio)

        if not (is_big1 and is_big2):
            return result

        # 检查是否同向大K线（反转预警）
        if dir1 == "BEARISH" and dir2 == "BEARISH":
            result["triggered"] = True
            result["signal"] = "TREND_REVERSAL_BEAR"
            result["reason"] = "连续两根大阴线，趋势可能反转向下"
            self._record_trigger("RULE_003_TWO_REVERSE_CANDLES", "TREND_REVERSAL_BEAR",
                                {"bar1_dir": dir1, "bar2_dir": dir2})
        elif dir1 == "BULLISH" and dir2 == "BULLISH":
            result["triggered"] = True
            result["signal"] = "TREND_REVERSAL_BULL"
            result["reason"] = "连续两根大阳线，趋势可能反转向上"
            self._record_trigger("RULE_003_TWO_REVERSE_CANDLES", "TREND_REVERSAL_BULL",
                                {"bar1_dir": dir1, "bar2_dir": dir2})

        return result

    def _rule_004_three_stage_pattern(self, ohlcv_bars: List[Dict]) -> Dict:
        """
        RULE_004: 三段式结构

        规则：放量大阳 + 缩量小K线群 + 再度放量大阳 = 强延续信号
        """
        result = {"triggered": False, "signal": None, "reason": "", "stage": 0}

        if len(ohlcv_bars) < 10:
            return result

        params = get_rule_params("RULE_004_THREE_STAGE_PATTERN")
        stage1_vol_ratio = params.get("stage1_volume_ratio", 1.5)
        stage2_vol_shrink = params.get("stage2_volume_shrink", 0.5)
        stage2_max_bars = params.get("stage2_max_bars", 5)
        stage3_vol_ratio = params.get("stage3_volume_ratio", 1.5)

        # 计算平均成交量
        vol_history = [float(bar.get("volume", bar.get("v", 0))) for bar in ohlcv_bars[-20:-5]]
        if not vol_history:
            return result
        avg_vol = sum(vol_history) / len(vol_history)
        if avg_vol == 0:
            return result

        # 状态机检测三段式
        # 倒序扫描寻找模式
        state = 0  # 0=寻找阶段3, 1=验证阶段2, 2=验证阶段1
        stage3_idx = -1
        stage2_bars = 0
        stage1_idx = -1

        for i in range(-1, -len(ohlcv_bars), -1):
            bar = ohlcv_bars[i]
            vol = float(bar.get("volume", bar.get("v", 0)))
            is_big, direction = self._is_big_candle(bar, 0.02)

            if state == 0:
                # 寻找阶段3: 放量大阳
                if is_big and direction == "BULLISH" and vol / avg_vol >= stage3_vol_ratio:
                    stage3_idx = i
                    state = 1
            elif state == 1:
                # 验证阶段2: 缩量小K线
                if vol / avg_vol <= stage2_vol_shrink and not is_big:
                    stage2_bars += 1
                    if stage2_bars > stage2_max_bars:
                        state = 0  # 重新开始
                        stage2_bars = 0
                elif is_big and direction == "BULLISH" and vol / avg_vol >= stage1_vol_ratio:
                    # 找到阶段1
                    if stage2_bars >= 2:  # 至少2根缩量小K线
                        stage1_idx = i
                        state = 2
                        break
                else:
                    state = 0  # 模式打破
                    stage2_bars = 0

        if state == 2 and stage1_idx is not None:
            result["triggered"] = True
            result["signal"] = "THREE_STAGE_BULLISH"
            result["reason"] = f"三段式结构完成: 放量大阳→{stage2_bars}根缩量→再度放量"
            result["stage"] = 3
            self._record_trigger("RULE_004_THREE_STAGE_PATTERN", "THREE_STAGE_BULLISH",
                                {"stage1_idx": stage1_idx, "stage2_bars": stage2_bars, "stage3_idx": stage3_idx})

        return result

    def _rule_005_angle_analysis(self, ohlcv_bars: List[Dict]) -> Dict:
        """
        RULE_005: 45度角理想趋势

        规则：
        - 30-55度为理想上涨趋势
        - >70度为过热警告
        - 使用ATR标准化角度计算
        """
        result = {"triggered": False, "signal": None, "reason": "", "angle": 0}

        if len(ohlcv_bars) < 15:
            return result

        params = get_rule_params("RULE_005_ANGLE_45_IDEAL")
        ideal_min = params.get("ideal_angle_min", 30)
        ideal_max = params.get("ideal_angle_max", 55)
        overheat = params.get("overheat_angle", 70)
        calc_bars = params.get("calculation_bars", 10)

        bars = ohlcv_bars[-calc_bars:]

        # 计算ATR用于标准化
        tr_list = []
        for i in range(1, len(bars)):
            h = float(bars[i].get("high", bars[i].get("h", 0)))
            l = float(bars[i].get("low", bars[i].get("l", 0)))
            prev_c = float(bars[i-1].get("close", bars[i-1].get("c", 0)))
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_list.append(tr)

        if not tr_list:
            return result
        atr = sum(tr_list) / len(tr_list)
        if atr == 0:
            return result

        # 计算价格变化 (用ATR标准化)
        first_close = float(bars[0].get("close", bars[0].get("c", 0)))
        last_close = float(bars[-1].get("close", bars[-1].get("c", 0)))

        price_change_atr = (last_close - first_close) / atr  # 用ATR标准化
        time_units = len(bars) - 1

        if time_units == 0:
            return result

        # 计算斜率和角度
        slope = price_change_atr / time_units
        angle = math.degrees(math.atan(slope))

        result["angle"] = angle

        # 判断趋势质量
        abs_angle = abs(angle)

        if angle > 0:  # 上涨趋势
            if abs_angle >= overheat:
                result["triggered"] = True
                result["signal"] = "OVERHEAT_WARNING"
                result["reason"] = f"趋势过热: 角度{angle:.1f}°>70°"
            elif ideal_min <= abs_angle <= ideal_max:
                result["triggered"] = True
                result["signal"] = "IDEAL_UPTREND"
                result["reason"] = f"理想上涨趋势: 角度{angle:.1f}°"
        elif angle < 0:  # 下跌趋势
            if abs_angle >= overheat:
                result["triggered"] = True
                result["signal"] = "OVERHEAT_DOWN_WARNING"
                result["reason"] = f"下跌过急: 角度{angle:.1f}°"
            elif ideal_min <= abs_angle <= ideal_max:
                result["triggered"] = True
                result["signal"] = "IDEAL_DOWNTREND"
                result["reason"] = f"稳定下跌趋势: 角度{angle:.1f}°"

        if result["triggered"]:
            self._record_trigger("RULE_005_ANGLE_45_IDEAL", result["signal"],
                                {"angle": angle, "atr": atr, "price_change": last_close - first_close})

        return result

    def _record_trigger(self, rule_id: str, signal: str, context: Dict):
        """记录规则触发 (Shadow模式)"""
        if VALIDATOR_LOADED:
            record_rule_trigger(
                rule_id=rule_id,
                symbol=self.symbol,
                signal=signal,
                context=context,
                bar_index=self.bar_index
            )
        self.triggered_rules.append({
            "rule_id": rule_id,
            "signal": signal,
            "context": context
        })


# ============================================================
# 便捷函数
# ============================================================

def analyze_human_knowledge_rules(ohlcv_bars: List[Dict],
                                   symbol: str = None,
                                   bar_index: int = 0) -> Dict[str, Any]:
    """
    分析Human知识点规则

    Args:
        ohlcv_bars: K线数据
        symbol: 品种代码
        bar_index: K线索引

    Returns:
        规则分析结果
    """
    engine = HumanKnowledgeRules(symbol=symbol, bar_index=bar_index)
    return engine.analyze_all_rules(ohlcv_bars)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    # 简单测试
    print("Human Knowledge Rules v1.0")
    print("=" * 40)

    # 模拟K线数据
    test_bars = []
    base_price = 100
    for i in range(30):
        o = base_price + i * 0.5
        c = o + 1.5 if i % 3 == 0 else o - 0.5
        h = max(o, c) + 0.3
        l = min(o, c) - 0.3
        v = 1000 * (2 if i == 25 else 1)  # 第25根放量
        test_bars.append({"open": o, "high": h, "low": l, "close": c, "volume": v})

    result = analyze_human_knowledge_rules(test_bars, symbol="TEST", bar_index=30)
    print(f"Bull adjustment: {result['bull_adjustment']}")
    print(f"Bear adjustment: {result['bear_adjustment']}")
    print(f"Signals: {result['signals']}")
    print(f"Warnings: {result['warnings']}")

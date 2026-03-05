"""
L2 Signal Analysis Module
=========================
Synced from v3.498 main program

Features:
- RSI analysis
- Volume price divergence (v3.160 Wyckoff)
- 2B pattern detection (v3.290)
- K-line pattern recognition
- Quality scoring system (v3.400)
- Reversal pattern detection (v3.420)
  * Double Bottom (W底)
  * Double Top (M头)
  * Head-Shoulders Bottom (头肩底)
  * Head-Shoulders Top (头肩顶)
- Form-Spirit Analysis (v5.440 形神分析法)
  * 来源: 量价理论第3集
  * 四种状态: 形神兼备/形散神聚/形不散神散/形神皆散
- v5.455: L2评分重构 + K线形态分
  * 解决分数膨胀问题 (原27% → 新50%触发STRONG)
  * 新增单根K线形态评分 (大阳/大阴/锤子/射击之星/十字星)
  * 权重压缩: -12 ~ +12 范围
- v5.465: P1改善项
  * 20 EMA趋势过滤器 (来源: THE 20 EMA)
  * Power Candle力量K线检测 (来源: THE POWER CANDLE)
  * 量堆式拉升检测 (来源: 量价理论第29集)
- v5.480: L2四大类评分 + Wyckoff策略分
  * 【形态分】(±6) - PA + 2B + 123 + K线形态, Donchian乘数
  * 【位置分】(±4) - pos_in_channel直接映射
  * 【量能分】(±2) - 量价配合验证
  * 【Wyckoff策略分】(±2) - 形态与阶段匹配度
  * 总分范围: -14 ~ +14, STRONG阈值: ±7 (50%)
- v5.487: Wyckoff稳定性 + 回调检测 + 底部保护
  * P0-1: Wyckoff阶段确认机制 (连续2根K线确认)
  * P0-2: 短期回调企稳检测 (跌幅>5%+企稳K线→暂停SELL)
  * P1-3: MARKUP_PULLBACK子状态 (连续2阴线=PULLBACK, 反向权重×0.5)
  * P1-4: 底部反转保护 (RSI<30/看涨吞没/锤子→暂停SELL)
  * P2-5: UNCLEAR阶段Wyckoff分归零 → v5.498更新为纯位置策略
  * P2-6: 双周期位置确认 (长期120+短期20, 背离时权重×0.7)
- v5.498: UNCLEAR阶段纯位置策略
  * UNCLEAR时不再归零，改为纯位置策略:
  * pos<20% → +2分 (极低位倾向买入)
  * pos>80% → -2分 (极高位倾向卖出)
  * 中间位置 → 0分 (等待)
"""

import logging
from typing import List, Dict, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class L2Analyzer:
    """L2 Signal Analyzer - Execution Timing"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.rsi_period = self.config.get("rsi_period", 14)
        self.rsi_overbought = self.config.get("rsi_overbought", 70)
        self.rsi_oversold = self.config.get("rsi_oversold", 30)
        self.volume_ma_period = self.config.get("volume_ma_period", 20)
        self.volume_spike = self.config.get("volume_spike_threshold", 1.5)
        self.volume_climax = self.config.get("volume_climax_threshold", 2.5)

    def analyze(self, bars: List[Dict], l1_trend: str = "SIDE", l1_regime: str = "RANGING") -> Dict:
        """
        Execute L2 signal analysis

        Returns:
            {
                "signal": "BUY" | "SELL" | "HOLD",
                "score": float (-100 to 100),
                "quality_score": float (1-9),
                "rsi": float,
                "volume_ratio": float,
                "divergence": str,
                "patterns": List[str],
                "wyckoff": Dict,
                "details": {...}
            }
        """
        if not bars or len(bars) < self.rsi_period + 5:
            return self._default_result()

        try:
            closes = np.array([float(b["close"]) for b in bars])
            volumes = np.array([float(b.get("volume", 0)) for b in bars])
            highs = np.array([float(b["high"]) for b in bars])
            lows = np.array([float(b["low"]) for b in bars])
            opens = np.array([float(b["open"]) for b in bars])

            # RSI
            rsi = self._calculate_rsi(closes)

            # Volume analysis
            volume_ratio = self._calculate_volume_ratio(volumes)

            # Volume-price divergence (v3.160 Wyckoff)
            divergence = self._detect_divergence(closes, volumes)

            # Wyckoff signals (v3.160)
            wyckoff = self._wyckoff_analysis(bars, closes, volumes, highs, lows)

            # K-line patterns
            patterns = self._detect_patterns(bars[-5:])

            # 2B pattern detection (v3.290)
            pattern_2b = self._detect_2b_strict(bars)

            # Reversal pattern detection (v3.420)
            reversal_pattern = self._detect_reversal_patterns(bars, volumes)

            # v5.440: Form-Spirit Analysis (形神分析法)
            form_spirit = self.analyze_form_spirit(bars)

            # v5.455: Single candle shape score
            candle_shape_score, candle_shape_name = compute_candle_shape_score(bars[-1])

            # Calculate score (v5.455: compressed scoring)
            score = self._calculate_score(
                rsi, volume_ratio, divergence, patterns, pattern_2b,
                wyckoff, l1_trend, l1_regime, reversal_pattern, candle_shape_score
            )

            # v5.440: Apply form-spirit quality multiplier
            if not form_spirit.get("tradeable", True):
                original_score = score
                score = score * form_spirit.get("quality_multiplier", 1.0)
                logger.info(f"[v5.440] Form-spirit weakened: {original_score:.1f}->{score:.1f} ({form_spirit.get('state')})")

            # Quality score (v3.400)
            quality_score = self._calculate_quality_score(
                patterns, volume_ratio, divergence, wyckoff
            )

            # Generate signal
            signal = self._generate_signal(score, l1_trend, l1_regime, rsi, quality_score)

            return {
                "signal": signal,
                "score": round(score, 1),
                "quality_score": quality_score,
                "rsi": round(rsi, 1),
                "volume_ratio": round(volume_ratio, 2),
                "divergence": divergence,
                "patterns": patterns,
                "pattern_2b": pattern_2b,
                "reversal_pattern": reversal_pattern,  # v3.420
                "form_spirit": form_spirit,  # v5.440
                "candle_shape_score": candle_shape_score,  # v5.455
                "candle_shape_name": candle_shape_name,  # v5.455
                "wyckoff": wyckoff,
                "details": {
                    "rsi_zone": self._rsi_zone(rsi),
                    "volume_status": self._volume_status(volume_ratio),
                }
            }

        except Exception as e:
            logger.error(f"L2 analysis error: {e}")
            return self._default_result()

    def _calculate_rsi(self, closes: np.ndarray) -> float:
        """Calculate RSI"""
        if len(closes) < self.rsi_period + 1:
            return 50.0

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-self.rsi_period:])
        avg_loss = np.mean(losses[-self.rsi_period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_volume_ratio(self, volumes: np.ndarray) -> float:
        """Calculate volume ratio"""
        if len(volumes) < self.volume_ma_period + 1:
            return 1.0

        volume_ma = np.mean(volumes[-self.volume_ma_period-1:-1])
        if volume_ma == 0:
            return 1.0
        return float(volumes[-1] / volume_ma)

    def _detect_divergence(self, closes: np.ndarray, volumes: np.ndarray) -> str:
        """
        Detect volume-price divergence (v3.160 Wyckoff Rule 1)
        """
        if len(closes) < 5:
            return "NONE"

        price_change = (closes[-1] - closes[-5]) / closes[-5]
        vol_change = (volumes[-1] - volumes[-5]) / (volumes[-5] + 1e-10)

        # Price up, volume down = Bearish divergence
        if price_change > 0.02 and vol_change < -0.3:
            return "BEARISH_DIVERGENCE"

        # Price down, volume up = Potential bottom
        if price_change < -0.02 and vol_change > 0.3:
            return "BULLISH_DIVERGENCE"

        return "NONE"

    def _wyckoff_analysis(
        self,
        bars: List[Dict],
        closes: np.ndarray,
        volumes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray
    ) -> Dict:
        """
        Wyckoff analysis (v3.160)

        Detects:
        - Intention bars (Rule 5)
        - Spring/shakeout (Rule 4)
        - Stopping action (Rule 9)
        """
        result = {
            "intention_bar": None,
            "spring": False,
            "stopping_action": False,
            "signals": []
        }

        if len(bars) < 10:
            return result

        recent_bar = bars[-1]
        body = abs(recent_bar["close"] - recent_bar["open"])
        range_ = recent_bar["high"] - recent_bar["low"]

        if range_ == 0:
            return result

        body_ratio = body / range_

        # Intention Bar (large body, high volume)
        if body_ratio > 0.6 and volumes[-1] > np.mean(volumes[-20:]) * 1.5:
            if recent_bar["close"] > recent_bar["open"]:
                result["intention_bar"] = "BULLISH"
                result["signals"].append("BULLISH_INTENTION_BAR")
            else:
                result["intention_bar"] = "BEARISH"
                result["signals"].append("BEARISH_INTENTION_BAR")

        # Spring detection (false breakdown)
        if len(lows) >= 10:
            recent_low = min(lows[-10:-1])
            if lows[-1] < recent_low and closes[-1] > recent_low:
                result["spring"] = True
                result["signals"].append("SPRING")

        # Stopping action (climax volume at extreme)
        if volumes[-1] > np.mean(volumes[-20:]) * self.volume_climax:
            rsi_zone = self._rsi_zone(self._calculate_rsi(closes))
            if closes[-1] > opens[-1] and rsi_zone == "OVERSOLD":
                result["stopping_action"] = True
                result["signals"].append("STOPPING_ACTION_BUY")
            elif closes[-1] < opens[-1] and rsi_zone == "OVERBOUGHT":
                result["stopping_action"] = True
                result["signals"].append("STOPPING_ACTION_SELL")

        return result

    def _detect_patterns(self, bars: List[Dict]) -> List[str]:
        """Detect K-line patterns"""
        patterns = []
        if len(bars) < 3:
            return patterns

        curr = bars[-1]
        prev = bars[-2]

        body = curr["close"] - curr["open"]
        range_ = curr["high"] - curr["low"]

        if range_ == 0:
            return patterns

        body_ratio = abs(body) / range_

        # Lower shadow
        lower_shadow = min(curr["open"], curr["close"]) - curr["low"]
        if lower_shadow > range_ * 0.6 and body_ratio < 0.3:
            patterns.append("HAMMER")

        # Upper shadow
        upper_shadow = curr["high"] - max(curr["open"], curr["close"])
        if upper_shadow > range_ * 0.6 and body_ratio < 0.3:
            patterns.append("SHOOTING_STAR")

        # Engulfing
        prev_body = prev["close"] - prev["open"]
        if body > 0 and prev_body < 0 and abs(body) > abs(prev_body) * 1.2:
            patterns.append("BULLISH_ENGULFING")
        elif body < 0 and prev_body > 0 and abs(body) > abs(prev_body) * 1.2:
            patterns.append("BEARISH_ENGULFING")

        # Doji
        if body_ratio < 0.1:
            patterns.append("DOJI")

        # Long lower shadow (v3.290)
        if lower_shadow > range_ * 0.5:
            patterns.append("LONG_LOWER_SHADOW")

        return patterns

    def _detect_2b_strict(self, bars: List[Dict]) -> str:
        """
        2B pattern detection (v3.290 enhanced)

        2B Buy: Break below support then recover
        2B Sell: Break above resistance then fall back
        """
        if len(bars) < 10:
            return "NONE"

        highs = [b["high"] for b in bars[-10:]]
        lows = [b["low"] for b in bars[-10:]]
        closes = [b["close"] for b in bars[-10:]]

        # Find recent extreme
        recent_low = min(lows[-8:-1])
        recent_high = max(highs[-8:-1])

        curr = bars[-1]

        # 2B Buy: Broke recent low but closed above
        if lows[-1] < recent_low and curr["close"] > recent_low:
            # Verify with body ratio (v3.290)
            body = curr["close"] - curr["open"]
            range_ = curr["high"] - curr["low"]
            if range_ > 0 and body / range_ > 0.4:
                return "2B_BUY"

        # 2B Sell: Broke recent high but closed below
        if highs[-1] > recent_high and curr["close"] < recent_high:
            body = curr["close"] - curr["open"]
            range_ = curr["high"] - curr["low"]
            if range_ > 0 and abs(body) / range_ > 0.4:
                return "2B_SELL"

        return "NONE"

    def _calculate_score(
        self,
        rsi: float,
        volume_ratio: float,
        divergence: str,
        patterns: List[str],
        pattern_2b: str,
        wyckoff: Dict,
        l1_trend: str,
        l1_regime: str,
        reversal_pattern: Dict = None,
        candle_shape_score: float = 0.0
    ) -> float:
        """
        Calculate comprehensive score

        v5.455: 评分重构 - 压缩范围到-12~12
        解决分数膨胀问题，使STRONG阈值(±6)需要50%而非27%

        核心层(±6): Pattern(-3~+3), RSI(-2~+2), K线形态(-1~+1)
        辅助层(±6): Volume(-1~+1), Divergence(-1~+1), Wyckoff(-1~+1), Reversal(-1~+1)
        """
        score = 0.0

        # === 核心层 ===

        # v5.455: K线形态分 (-1 to +1) 与主程序v3.455一致
        score += candle_shape_score

        # Pattern分 (-3 to +3): 2B + K线形态模式
        pattern_score = 0.0

        # 2B Pattern (-1.5 to +1.5) - v3.290 压缩
        if pattern_2b == "2B_BUY":
            pattern_score += 1.5
        elif pattern_2b == "2B_SELL":
            pattern_score -= 1.5

        # K-line patterns (-1.5 to +1.5) - 压缩
        bullish_patterns = ["HAMMER", "BULLISH_ENGULFING", "LONG_LOWER_SHADOW"]
        bearish_patterns = ["SHOOTING_STAR", "BEARISH_ENGULFING"]

        for p in patterns:
            if p in bullish_patterns:
                pattern_score += 0.75
            elif p in bearish_patterns:
                pattern_score -= 0.75

        # 限制Pattern分范围
        score += max(-3, min(3, pattern_score))

        # === 辅助层 ===

        # RSI position score (-2 to +2) - 压缩
        if rsi < 30:
            score += min(2, (30 - rsi) / 15)  # 极度超卖时+2
        elif rsi > 70:
            score -= min(2, (rsi - 70) / 15)  # 极度超买时-2
        else:
            score += (50 - rsi) / 50  # 中性区域微调

        # Volume (-1 to +1) - 压缩
        if volume_ratio > self.volume_spike:
            if l1_trend == "UP":
                score += 1
            elif l1_trend == "DOWN":
                score -= 1
        elif volume_ratio < 0.5:
            score -= 0.5

        # Divergence (-1 to +1) - 压缩
        if divergence == "BULLISH_DIVERGENCE":
            score += 1
        elif divergence == "BEARISH_DIVERGENCE":
            score -= 1

        # Wyckoff signals (-1 to +1) - 压缩
        wyckoff_score = 0
        for sig in wyckoff.get("signals", []):
            if "BULLISH" in sig or sig == "SPRING" or sig == "STOPPING_ACTION_BUY":
                wyckoff_score += 0.5
            elif "BEARISH" in sig or sig == "STOPPING_ACTION_SELL":
                wyckoff_score -= 0.5
        score += max(-1, min(1, wyckoff_score))

        # Reversal pattern (-1 to +1) - v3.420 压缩
        if reversal_pattern and reversal_pattern.get("pattern"):
            pattern_name = reversal_pattern.get("pattern", "")
            quality = reversal_pattern.get("quality_score", 1)
            quality_multiplier = {1: 0.7, 2: 1.0, 3: 1.3}.get(quality, 1.0)

            # Base score reduced
            if "HEAD_SHOULDERS" in pattern_name or "头肩" in pattern_name:
                base_score = 0.8
            else:  # Double patterns
                base_score = 0.6

            # Apply direction
            if "BOTTOM" in pattern_name or "底" in pattern_name:
                score += min(1, base_score * quality_multiplier)
            elif "TOP" in pattern_name or "顶" in pattern_name:
                score -= min(1, base_score * quality_multiplier)

        # v5.455: 最终范围限制 -12 ~ +12
        return max(-12, min(12, score))

    def _calculate_quality_score(
        self,
        patterns: List[str],
        volume_ratio: float,
        divergence: str,
        wyckoff: Dict
    ) -> float:
        """
        Quality score (v3.400)

        1-3: Low quality
        4-6: Medium quality
        7-9: High quality
        """
        score = 3.0  # Base

        # Pattern quality (+0 to +2)
        high_quality_patterns = ["BULLISH_ENGULFING", "BEARISH_ENGULFING", "HAMMER"]
        for p in patterns:
            if p in high_quality_patterns:
                score += 1.0
                break

        # Volume confirmation (+0 to +2)
        if volume_ratio > 1.5:
            score += 2.0
        elif volume_ratio > 1.2:
            score += 1.0

        # Divergence (+0 to +1.5)
        if divergence != "NONE":
            score += 1.5

        # Wyckoff signals (+0 to +1.5)
        if wyckoff.get("signals"):
            score += min(len(wyckoff["signals"]) * 0.5, 1.5)

        return min(9.0, round(score, 1))

    def _generate_signal(
        self,
        score: float,
        l1_trend: str,
        l1_regime: str,
        rsi: float,
        quality_score: float
    ) -> str:
        """
        Generate trading signal based on all factors

        v5.455: 阈值调整适配新的-12~12评分范围
        - STRONG_BUY: score >= 6
        - BUY: score >= 3
        - HOLD: -3 < score < 3
        - SELL: score <= -3
        - STRONG_SELL: score <= -6
        """

        # Quality threshold (v3.400)
        min_quality = 4.0 if l1_regime == "RANGING" else 3.0

        # v5.455: 调整阈值适配新评分范围
        # Trending market - follow the trend
        if l1_regime == "TRENDING":
            if l1_trend == "UP":
                if score >= 3 and rsi < 65 and quality_score >= min_quality:
                    return "BUY"
                elif score <= -6 or rsi > 80:
                    return "SELL"
            elif l1_trend == "DOWN":
                if score <= -3 and rsi > 35 and quality_score >= min_quality:
                    return "SELL"
                elif score >= 6 or rsi < 20:
                    return "BUY"

        # Ranging market - mean reversion
        else:
            if score >= 4 and rsi < 35 and quality_score >= min_quality:
                return "BUY"
            elif score <= -4 and rsi > 65 and quality_score >= min_quality:
                return "SELL"

        return "HOLD"

    def _rsi_zone(self, rsi: float) -> str:
        if rsi >= self.rsi_overbought:
            return "OVERBOUGHT"
        elif rsi <= self.rsi_oversold:
            return "OVERSOLD"
        return "NEUTRAL"

    def _volume_status(self, volume_ratio: float) -> str:
        if volume_ratio > self.volume_climax:
            return "CLIMAX"
        elif volume_ratio > self.volume_spike:
            return "SPIKE"
        elif volume_ratio < 0.5:
            return "LOW"
        return "NORMAL"

    # =========================================================================
    # v3.420: Reversal Pattern Detection (Double Bottom/Top + Head-Shoulders)
    # =========================================================================

    def _detect_reversal_patterns(self, bars: List[Dict], volumes: np.ndarray, tolerance: float = 0.05) -> Dict:
        """
        v3.420: Detect reversal patterns

        Patterns detected:
        - DOUBLE_BOTTOM (W底): Two lows at similar level, bullish
        - DOUBLE_TOP (M头): Two highs at similar level, bearish
        - HEAD_SHOULDERS_BOTTOM (头肩底): Three lows with middle lowest, bullish
        - HEAD_SHOULDERS_TOP (头肩顶): Three highs with middle highest, bearish

        Returns:
            {
                "pattern": str,  # Pattern name or None
                "stage": str,    # "FORMING" | "CONFIRMED" | "BREAKOUT"
                "quality_score": int,  # 1-3
                "neckline": float,
                "target": float,
                "score_adjustment": int,  # Base score adjustment
            }
        """
        result = {
            "pattern": None,
            "stage": "",
            "quality_score": 0,
            "neckline": 0,
            "target": 0,
            "score_adjustment": 0,
        }

        if not bars or len(bars) < 25:
            return result

        # Find swing points
        swing_highs, swing_lows = self._find_swing_points(bars)

        if len(swing_lows) < 2 or len(swing_highs) < 2:
            return result

        closes = np.array([b["close"] for b in bars])
        current_price = closes[-1]

        # Try to detect patterns in order of priority
        # Head-shoulders patterns first (more significant)
        if len(swing_lows) >= 3:
            hs_bottom = self._detect_hs_bottom(bars, swing_lows, swing_highs, volumes, current_price)
            if hs_bottom["pattern"]:
                return hs_bottom

        if len(swing_highs) >= 3:
            hs_top = self._detect_hs_top(bars, swing_highs, swing_lows, volumes, current_price)
            if hs_top["pattern"]:
                return hs_top

        # Double patterns
        double_bottom = self._detect_double_bottom(bars, swing_lows, swing_highs, volumes, current_price, tolerance)
        if double_bottom["pattern"]:
            return double_bottom

        double_top = self._detect_double_top(bars, swing_highs, swing_lows, volumes, current_price, tolerance)
        if double_top["pattern"]:
            return double_top

        return result

    def _find_swing_points(self, bars: List[Dict], window: int = 3) -> Tuple[List[Dict], List[Dict]]:
        """Find swing high and low points"""
        swing_highs = []
        swing_lows = []

        if len(bars) < window * 2 + 1:
            return swing_highs, swing_lows

        for i in range(window, len(bars) - window):
            # Check for swing high
            is_high = True
            for j in range(1, window + 1):
                if bars[i]["high"] <= bars[i - j]["high"] or bars[i]["high"] <= bars[i + j]["high"]:
                    is_high = False
                    break
            if is_high:
                swing_highs.append({"index": i, "price": bars[i]["high"], "bar": bars[i]})

            # Check for swing low
            is_low = True
            for j in range(1, window + 1):
                if bars[i]["low"] >= bars[i - j]["low"] or bars[i]["low"] >= bars[i + j]["low"]:
                    is_low = False
                    break
            if is_low:
                swing_lows.append({"index": i, "price": bars[i]["low"], "bar": bars[i]})

        return swing_highs, swing_lows

    def _detect_double_bottom(self, bars, swing_lows, swing_highs, volumes, current_price, tolerance) -> Dict:
        """Detect double bottom (W底) pattern"""
        result = {"pattern": None, "stage": "", "quality_score": 0, "neckline": 0, "target": 0, "score_adjustment": 0}

        if len(swing_lows) < 2:
            return result

        # Get last two swing lows
        low1 = swing_lows[-2]
        low2 = swing_lows[-1]

        # Check if two lows are at similar level (within tolerance)
        price_diff = abs(low1["price"] - low2["price"]) / low1["price"]
        if price_diff > tolerance:
            return result

        # Find neckline (highest point between two lows)
        neckline = 0
        for sh in swing_highs:
            if low1["index"] < sh["index"] < low2["index"]:
                neckline = max(neckline, sh["price"])

        if neckline == 0:
            return result

        # Calculate quality score
        quality = 1

        # Volume shrink on right bottom = higher quality
        if len(volumes) > low2["index"]:
            vol_left = volumes[low1["index"]] if low1["index"] < len(volumes) else 1
            vol_right = volumes[low2["index"]] if low2["index"] < len(volumes) else 1
            if vol_left > 0 and vol_right < vol_left * 0.8:
                quality += 1

        # Breakout confirmation
        if current_price > neckline:
            quality += 1
            stage = "BREAKOUT"
        elif current_price > (low2["price"] + neckline) / 2:
            stage = "CONFIRMED"
        else:
            stage = "FORMING"

        # Target price
        target = neckline + (neckline - min(low1["price"], low2["price"]))

        return {
            "pattern": "DOUBLE_BOTTOM",
            "stage": stage,
            "quality_score": min(3, quality),
            "neckline": round(neckline, 2),
            "target": round(target, 2),
            "score_adjustment": 8,  # Bullish
        }

    def _detect_double_top(self, bars, swing_highs, swing_lows, volumes, current_price, tolerance) -> Dict:
        """Detect double top (M头) pattern"""
        result = {"pattern": None, "stage": "", "quality_score": 0, "neckline": 0, "target": 0, "score_adjustment": 0}

        if len(swing_highs) < 2:
            return result

        # Get last two swing highs
        high1 = swing_highs[-2]
        high2 = swing_highs[-1]

        # Check if two highs are at similar level
        price_diff = abs(high1["price"] - high2["price"]) / high1["price"]
        if price_diff > tolerance:
            return result

        # Find neckline (lowest point between two highs)
        neckline = float('inf')
        for sl in swing_lows:
            if high1["index"] < sl["index"] < high2["index"]:
                neckline = min(neckline, sl["price"])

        if neckline == float('inf'):
            return result

        # Calculate quality score
        quality = 1

        # Volume shrink on right top = higher quality (rule from knowledge card)
        if len(volumes) > high2["index"]:
            vol_left = volumes[high1["index"]] if high1["index"] < len(volumes) else 1
            vol_right = volumes[high2["index"]] if high2["index"] < len(volumes) else 1
            if vol_left > 0 and vol_right < vol_left * 0.7:  # Right volume < 70% of left
                quality += 1

        # Breakdown confirmation
        if current_price < neckline:
            quality += 1
            stage = "BREAKOUT"
        elif current_price < (high2["price"] + neckline) / 2:
            stage = "CONFIRMED"
        else:
            stage = "FORMING"

        # Target price
        target = neckline - (max(high1["price"], high2["price"]) - neckline)

        return {
            "pattern": "DOUBLE_TOP",
            "stage": stage,
            "quality_score": min(3, quality),
            "neckline": round(neckline, 2),
            "target": round(target, 2),
            "score_adjustment": -8,  # Bearish
        }

    def _detect_hs_bottom(self, bars, swing_lows, swing_highs, volumes, current_price) -> Dict:
        """Detect head-shoulders bottom (头肩底) pattern"""
        result = {"pattern": None, "stage": "", "quality_score": 0, "neckline": 0, "target": 0, "score_adjustment": 0}

        if len(swing_lows) < 3:
            return result

        # Get last three swing lows
        left_shoulder = swing_lows[-3]
        head = swing_lows[-2]
        right_shoulder = swing_lows[-1]

        # Head must be lowest
        if not (head["price"] < left_shoulder["price"] and head["price"] < right_shoulder["price"]):
            return result

        # Shoulders should be at similar level (within 5%)
        shoulder_diff = abs(left_shoulder["price"] - right_shoulder["price"]) / left_shoulder["price"]
        if shoulder_diff > 0.05:
            return result

        # Find neckline
        neckline_points = []
        for sh in swing_highs:
            if left_shoulder["index"] < sh["index"] < head["index"]:
                neckline_points.append(sh["price"])
            elif head["index"] < sh["index"] < right_shoulder["index"]:
                neckline_points.append(sh["price"])

        if len(neckline_points) < 2:
            return result

        neckline = sum(neckline_points) / len(neckline_points)

        # Quality score
        quality = 1

        # Volume pattern check
        if len(volumes) > right_shoulder["index"]:
            vol_head = volumes[head["index"]] if head["index"] < len(volumes) else 1
            vol_rs = volumes[right_shoulder["index"]] if right_shoulder["index"] < len(volumes) else 1
            if vol_rs > vol_head:  # Volume increase on right shoulder
                quality += 1

        # Breakout confirmation
        if current_price > neckline:
            quality += 1
            stage = "BREAKOUT"
        elif current_price > right_shoulder["price"]:
            stage = "CONFIRMED"
        else:
            stage = "FORMING"

        # Target price
        target = neckline + (neckline - head["price"])

        return {
            "pattern": "HEAD_SHOULDERS_BOTTOM",
            "stage": stage,
            "quality_score": min(3, quality),
            "neckline": round(neckline, 2),
            "target": round(target, 2),
            "score_adjustment": 10,  # Strong bullish
        }

    def _detect_hs_top(self, bars, swing_highs, swing_lows, volumes, current_price) -> Dict:
        """Detect head-shoulders top (头肩顶) pattern"""
        result = {"pattern": None, "stage": "", "quality_score": 0, "neckline": 0, "target": 0, "score_adjustment": 0}

        if len(swing_highs) < 3:
            return result

        # Get last three swing highs
        left_shoulder = swing_highs[-3]
        head = swing_highs[-2]
        right_shoulder = swing_highs[-1]

        # Head must be highest
        if not (head["price"] > left_shoulder["price"] and head["price"] > right_shoulder["price"]):
            return result

        # Shoulders should be at similar level
        shoulder_diff = abs(left_shoulder["price"] - right_shoulder["price"]) / left_shoulder["price"]
        if shoulder_diff > 0.05:
            return result

        # Find neckline
        neckline_points = []
        for sl in swing_lows:
            if left_shoulder["index"] < sl["index"] < head["index"]:
                neckline_points.append(sl["price"])
            elif head["index"] < sl["index"] < right_shoulder["index"]:
                neckline_points.append(sl["price"])

        if len(neckline_points) < 2:
            return result

        neckline = sum(neckline_points) / len(neckline_points)

        # Quality score
        quality = 1

        # Volume diminishing pattern
        if len(volumes) > right_shoulder["index"]:
            vol_left = volumes[left_shoulder["index"]] if left_shoulder["index"] < len(volumes) else 1
            vol_head = volumes[head["index"]] if head["index"] < len(volumes) else 1
            vol_rs = volumes[right_shoulder["index"]] if right_shoulder["index"] < len(volumes) else 1
            if vol_head < vol_left and vol_rs < vol_head:
                quality += 1

        # Breakdown confirmation
        if current_price < neckline:
            quality += 1
            stage = "BREAKOUT"
        elif current_price < right_shoulder["price"]:
            stage = "CONFIRMED"
        else:
            stage = "FORMING"

        # Target price
        target = neckline - (head["price"] - neckline)

        return {
            "pattern": "HEAD_SHOULDERS_TOP",
            "stage": stage,
            "quality_score": min(3, quality),
            "neckline": round(neckline, 2),
            "target": round(target, 2),
            "score_adjustment": -10,  # Strong bearish
        }

    def _default_result(self) -> Dict:
        return {
            "signal": "HOLD",
            "score": 0.0,
            "quality_score": 3.0,
            "rsi": 50.0,
            "volume_ratio": 1.0,
            "divergence": "NONE",
            "patterns": [],
            "pattern_2b": "NONE",
            "reversal_pattern": {},  # v3.420
            "form_spirit": {},  # v5.440
            "candle_shape_score": 0.0,  # v5.455
            "candle_shape_name": "-",  # v5.455
            "wyckoff": {"signals": []},
            "details": {}
        }

    # =========================================================================
    # v5.440: 形神分析法 (来源: 量价理论第3集)
    # =========================================================================
    def analyze_form_spirit(self, bars: List[Dict], lookback: int = 20) -> Dict:
        """
        形神分析法

        形(K线流畅度):
            - 影线比率 < 0.5 = 流畅
            - 波动率(ATR/价格) < 2% = 稳定

        神(成交量均衡):
            - 变异系数 < 0.3 = 均衡
            - 无爆量(>2倍均量) = 稳定

        四种状态:
            - 形神兼备: 可交易，主力控盘良好
            - 形散神聚: 回避，阶段顶部特征
            - 形不散神散: 回避，诱多出货特征
            - 形神皆散: 观望，无主力控盘

        Returns:
            {"form_score": 1-3, "spirit_score": 1-3, "state": str,
             "tradeable": bool, "quality_multiplier": float, "warning": str}
        """
        result = {
            "form_score": 2,
            "spirit_score": 2,
            "state": "FORM_SPIRIT_BALANCED",
            "tradeable": True,
            "quality_multiplier": 1.0,
            "warning": None
        }

        if not bars or len(bars) < lookback:
            return result

        recent = bars[-lookback:]

        # ===== 形(K线流畅度) =====
        shadow_ratios = []
        true_ranges = []
        closes = []

        for i, bar in enumerate(recent):
            o = float(bar.get('open', 0))
            h = float(bar.get('high', 0))
            l = float(bar.get('low', 0))
            c = float(bar.get('close', 0))

            if c <= 0 or h <= 0:
                continue

            closes.append(c)

            # 影线比率
            body = abs(c - o)
            upper_shadow = h - max(c, o)
            lower_shadow = min(c, o) - l
            if body > 0:
                shadow_ratios.append((upper_shadow + lower_shadow) / body)

            # True Range
            if i > 0:
                prev_c = float(recent[i-1].get('close', 0))
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                true_ranges.append(tr)

        # 平均影线比率
        avg_shadow_ratio = sum(shadow_ratios) / len(shadow_ratios) if shadow_ratios else 0

        # 波动率 (ATR / 价格)
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0
        avg_price = sum(closes) / len(closes) if closes else 1
        volatility = atr / avg_price if avg_price > 0 else 0

        # 形评分
        if avg_shadow_ratio < 0.5 and volatility < 0.02:
            form_score = 3  # 形不散
        elif avg_shadow_ratio < 1.0 and volatility < 0.04:
            form_score = 2  # 形中等
        else:
            form_score = 1  # 形散

        # ===== 神(成交量均衡) =====
        volumes = []
        for bar in recent:
            v = float(bar.get('volume', 0))
            if v > 0:
                volumes.append(v)

        vol_cv = 0
        spike_count = 0

        if volumes:
            vol_mean = sum(volumes) / len(volumes)
            vol_variance = sum((v - vol_mean) ** 2 for v in volumes) / len(volumes)
            vol_std = vol_variance ** 0.5
            vol_cv = vol_std / vol_mean if vol_mean > 0 else 0  # 变异系数

            # 检测爆量 (>2倍均量)
            spike_count = sum(1 for v in volumes if v > vol_mean * 2)

            # 神评分
            if vol_cv < 0.3 and spike_count == 0:
                spirit_score = 3  # 神不散
            elif vol_cv < 0.6 and spike_count <= 2:
                spirit_score = 2  # 神中等
            else:
                spirit_score = 1  # 神散
        else:
            spirit_score = 2  # 无量能数据，默认中等

        # ===== State determination =====
        if form_score >= 2 and spirit_score >= 2:
            state = "FORM_SPIRIT_BALANCED"
            tradeable = True
            quality_multiplier = 1.0 + (form_score + spirit_score - 4) * 0.1
            warning = None
        elif form_score <= 1 and spirit_score >= 2:
            state = "FORM_SCATTERED_SPIRIT_FOCUSED"
            tradeable = False
            quality_multiplier = 0.5
            warning = "Potential top pattern, avoid trading"
        elif form_score >= 2 and spirit_score <= 1:
            state = "FORM_FOCUSED_SPIRIT_SCATTERED"
            tradeable = False
            quality_multiplier = 0.3
            warning = "Potential distribution pattern, high risk"
        else:
            state = "FORM_SPIRIT_SCATTERED"
            tradeable = False
            quality_multiplier = 0.5
            warning = "No institutional control, stay out"

        result.update({
            "form_score": form_score,
            "spirit_score": spirit_score,
            "state": state,
            "tradeable": tradeable,
            "quality_multiplier": quality_multiplier,
            "warning": warning,
            "details": {
                "avg_shadow_ratio": round(avg_shadow_ratio, 2),
                "volatility": f"{volatility*100:.2f}%",
                "vol_cv": round(vol_cv, 2) if volumes else "N/A",
                "spike_count": spike_count
            }
        })

        return result


# ============================================================================
# v5.440: MACD背驰检测 (来源: 缠论第11集)
# ============================================================================

def detect_macd_divergence(bars: List[Dict], trend: str, lookback: int = 30) -> Dict:
    """
    MACD背驰检测

    关键规则: "无趋势无背驰" - 盘整中不检测背驰

    顶背驰(bearish): 价格新高但MACD未新高 → 趋势可能反转下跌
    底背驰(bullish): 价格新低但MACD未新低 → 趋势可能反转上涨

    Returns:
        {"has_divergence": bool, "divergence_type": str, "strength": 0-1, "warning": str}
    """
    result = {
        "has_divergence": False,
        "divergence_type": None,
        "strength": 0,
        "warning": None
    }

    # Rule: No divergence in ranging market ("no trend = no divergence")
    if trend in ["SIDE", "RANGING", "side", "ranging"]:
        result["warning"] = "No divergence in ranging market"
        return result

    if not bars or len(bars) < 35:  # MACD(12,26,9) needs at least 35 bars
        result["warning"] = "Insufficient data for MACD calculation"
        return result

    # Extract close prices
    closes = []
    for bar in bars:
        c = float(bar.get('close', 0))
        if c > 0:
            closes.append(c)

    if len(closes) < 35:
        result["warning"] = "Insufficient valid bar data"
        return result

    # 计算MACD (12, 26, 9)
    def ema(data, period):
        if len(data) < period:
            return [sum(data) / len(data)] * len(data)
        multiplier = 2 / (period + 1)
        ema_values = [sum(data[:period]) / period]
        for i in range(period, len(data)):
            ema_values.append((data[i] - ema_values[-1]) * multiplier + ema_values[-1])
        return [ema_values[0]] * (period - 1) + ema_values

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(closes))]
    signal_line = ema(macd_line, 9)
    histogram = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]

    # 检测最近lookback根K线的高低点
    recent_closes = closes[-lookback:]
    recent_hist = histogram[-lookback:]

    # 找局部高点和低点 (窗口=5)
    def find_swing_points(data, window=5):
        highs = []
        lows = []
        for i in range(window, len(data) - window):
            if data[i] == max(data[i-window:i+window+1]):
                highs.append((i, data[i]))
            if data[i] == min(data[i-window:i+window+1]):
                lows.append((i, data[i]))
        return highs, lows

    price_highs, price_lows = find_swing_points(recent_closes)
    hist_highs, hist_lows = find_swing_points(recent_hist)

    divergence_type = None
    strength = 0

    # 上涨趋势中检测顶背驰
    if trend.upper() in ["UP", "TREND_UP"]:
        if len(price_highs) >= 2 and len(hist_highs) >= 2:
            # 价格新高
            price_higher = price_highs[-1][1] > price_highs[-2][1]
            # MACD未新高
            macd_higher = hist_highs[-1][1] > hist_highs[-2][1]

            if price_higher and not macd_higher:
                divergence_type = "bearish"
                price_diff = (price_highs[-1][1] - price_highs[-2][1]) / price_highs[-2][1] if price_highs[-2][1] > 0 else 0
                macd_diff = (hist_highs[-2][1] - hist_highs[-1][1]) / abs(hist_highs[-2][1]) if hist_highs[-2][1] != 0 else 0
                strength = min(abs(price_diff) + abs(macd_diff), 1.0)

    # 下跌趋势中检测底背驰
    elif trend.upper() in ["DOWN", "TREND_DOWN"]:
        if len(price_lows) >= 2 and len(hist_lows) >= 2:
            # 价格新低
            price_lower = price_lows[-1][1] < price_lows[-2][1]
            # MACD未新低
            macd_lower = hist_lows[-1][1] < hist_lows[-2][1]

            if price_lower and not macd_lower:
                divergence_type = "bullish"
                price_diff = (price_lows[-2][1] - price_lows[-1][1]) / price_lows[-2][1] if price_lows[-2][1] > 0 else 0
                macd_diff = (hist_lows[-1][1] - hist_lows[-2][1]) / abs(hist_lows[-2][1]) if hist_lows[-2][1] != 0 else 0
                strength = min(abs(price_diff) + abs(macd_diff), 1.0)

    # Generate warning
    warning = None
    if divergence_type == "bearish":
        warning = f"Bearish divergence: Potential trend reversal down (strength {strength*100:.0f}%)"
    elif divergence_type == "bullish":
        warning = f"Bullish divergence: Potential trend reversal up (strength {strength*100:.0f}%)"

    result.update({
        "has_divergence": divergence_type is not None,
        "divergence_type": divergence_type,
        "strength": round(strength, 2),
        "warning": warning
    })

    return result


# ============================================================================
# v5.455: 单根K线形态评分 (来源: 量价理论)
# ============================================================================

def compute_candle_shape_score(bar: Dict) -> Tuple[float, str]:
    """
    v5.455: 计算单根K线形态分 (与主程序v3.455一致)

    Returns: (score, shape_name)
    score: -1.0 ~ +1.0
        +1.0: 大阳线(实体≥70%) / 锤子线(下影>2倍实体+收上半区)
        +0.5: 普通阳线(30%<实体<70%)
         0.0: 十字星/纺锤(实体≤30%)
        -0.5: 普通阴线(30%<实体<70%)
        -1.0: 大阴线(实体≥70%) / 射击之星(上影>2倍实体+收下半区)
    """
    if not bar:
        return 0.0, "UNKNOWN"

    o = float(bar.get('open', 0))
    h = float(bar.get('high', 0))
    l = float(bar.get('low', 0))
    c = float(bar.get('close', 0))

    if h <= l or c <= 0 or o <= 0:
        return 0.0, "INVALID"

    body = abs(c - o)
    bar_range = h - l if h > l else 0.0001
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l

    body_ratio = body / bar_range
    is_bullish = c > o
    is_bearish = c < o

    # Hammer: lower shadow > 2x body + close in upper half
    if lower_shadow > body * 2 and c > (h + l) / 2:
        return 1.0, "HAMMER"

    # Shooting Star: upper shadow > 2x body + close in lower half
    if upper_shadow > body * 2 and c < (h + l) / 2:
        return -1.0, "SHOOTING_STAR"

    # Strong Bull: body >= 70% + bullish
    if body_ratio >= 0.7 and is_bullish:
        return 1.0, "STRONG_BULL"

    # Strong Bear: body >= 70% + bearish
    if body_ratio >= 0.7 and is_bearish:
        return -1.0, "STRONG_BEAR"

    # Normal Bull: 30% < body < 70%
    if 0.3 < body_ratio < 0.7 and is_bullish:
        return 0.5, "BULL"

    # Normal Bear: 30% < body < 70%
    if 0.3 < body_ratio < 0.7 and is_bearish:
        return -0.5, "BEAR"

    # Doji: body <= 30%
    if body_ratio <= 0.3:
        return 0.0, "DOJI"

    return 0.0, "UNKNOWN"


# ============================================================================
# v5.465: 20 EMA趋势过滤器 (来源: THE 20 EMA)
# ============================================================================

def calculate_ema(data: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average"""
    if len(data) < period:
        return [sum(data) / len(data)] * len(data) if data else []

    multiplier = 2 / (period + 1)
    ema_values = [sum(data[:period]) / period]

    for i in range(period, len(data)):
        ema_values.append((data[i] - ema_values[-1]) * multiplier + ema_values[-1])

    return [ema_values[0]] * (period - 1) + ema_values


def analyze_ema20_trend(bars: List[Dict], lookback: int = 30) -> Dict:
    """
    v5.465: 20 EMA趋势过滤器

    来源: THE 20 EMA - How To Use The 20-Period Exponential Moving Average

    核心原则:
    - 价格在20 EMA上方 + EMA斜率上升 = BULLISH (短线看涨)
    - 价格在20 EMA下方 + EMA斜率下降 = BEARISH (短线看跌)
    - 价格触及20 EMA = 潜在买点/卖点

    Returns:
        {
            "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
            "price_vs_ema": "ABOVE" | "BELOW" | "TOUCHING",
            "ema_slope": float,  # 正=上升, 负=下降
            "ema_slope_strength": "STRONG" | "MODERATE" | "WEAK",
            "pullback_signal": bool,  # 回调到EMA附近的买点信号
            "ema20": float,
            "score": float  # -1 to +1
        }
    """
    result = {
        "bias": "NEUTRAL",
        "price_vs_ema": "TOUCHING",
        "ema_slope": 0.0,
        "ema_slope_strength": "WEAK",
        "pullback_signal": False,
        "ema20": 0.0,
        "score": 0.0
    }

    if not bars or len(bars) < 25:
        return result

    closes = [float(b.get("close", 0)) for b in bars if float(b.get("close", 0)) > 0]
    if len(closes) < 25:
        return result

    # Calculate 20 EMA
    ema20_values = calculate_ema(closes, 20)
    if not ema20_values:
        return result

    current_price = closes[-1]
    current_ema20 = ema20_values[-1]

    # Calculate EMA slope (last 5 periods)
    if len(ema20_values) >= 5:
        ema_slope = (ema20_values[-1] - ema20_values[-5]) / ema20_values[-5] * 100  # Percentage
    else:
        ema_slope = 0.0

    # Price vs EMA position
    price_diff_pct = (current_price - current_ema20) / current_ema20 * 100

    if price_diff_pct > 1.0:
        price_vs_ema = "ABOVE"
    elif price_diff_pct < -1.0:
        price_vs_ema = "BELOW"
    else:
        price_vs_ema = "TOUCHING"

    # Slope strength
    if abs(ema_slope) > 2.0:
        ema_slope_strength = "STRONG"
    elif abs(ema_slope) > 1.0:
        ema_slope_strength = "MODERATE"
    else:
        ema_slope_strength = "WEAK"

    # Determine bias
    score = 0.0

    if price_vs_ema == "ABOVE" and ema_slope > 0:
        bias = "BULLISH"
        score = 0.5 + min(0.5, abs(ema_slope) / 4)  # Max 1.0
    elif price_vs_ema == "BELOW" and ema_slope < 0:
        bias = "BEARISH"
        score = -0.5 - min(0.5, abs(ema_slope) / 4)  # Min -1.0
    elif price_vs_ema == "TOUCHING":
        bias = "NEUTRAL"
        score = 0.0
    elif price_vs_ema == "ABOVE" and ema_slope <= 0:
        bias = "NEUTRAL"  # Price above but EMA turning down = caution
        score = 0.2
    elif price_vs_ema == "BELOW" and ema_slope >= 0:
        bias = "NEUTRAL"  # Price below but EMA turning up = potential reversal
        score = -0.2
    else:
        bias = "NEUTRAL"

    # Pullback signal: price touching EMA in a trending market
    pullback_signal = False
    if abs(price_diff_pct) < 2.0:  # Within 2% of EMA
        if ema_slope > 0.5:  # Uptrend
            pullback_signal = True
            score += 0.3  # Bonus for pullback buy opportunity
        elif ema_slope < -0.5:  # Downtrend
            pullback_signal = True
            score -= 0.3  # Bonus for pullback sell opportunity

    result.update({
        "bias": bias,
        "price_vs_ema": price_vs_ema,
        "ema_slope": round(ema_slope, 2),
        "ema_slope_strength": ema_slope_strength,
        "pullback_signal": pullback_signal,
        "ema20": round(current_ema20, 4),
        "score": round(max(-1, min(1, score)), 2)
    })

    return result


# ============================================================================
# v5.465: Power Candle检测 (来源: THE POWER CANDLE)
# ============================================================================

def detect_power_candle(bar: Dict) -> Dict:
    """
    v5.465: Power Candle检测

    来源: THE POWER CANDLE - One Candle, Any Time Frame, Unbelievable Results

    Power Candle定义:
    - Bullish Power Candle: HIGH = CLOSE (无上影线) + 大实体
    - Bearish Power Candle: LOW = CLOSE (无下影线) + 大实体

    核心特征:
    - 显示单方力量的极端控制
    - 收盘价在K线范围的极端位置
    - 实体占比大 (>= 60%)

    Returns:
        {
            "is_power_candle": bool,
            "type": "BULLISH_POWER" | "BEARISH_POWER" | None,
            "strength": 1-3,  # 1=弱, 2=中, 3=强
            "score": float,  # -2 to +2
            "details": {...}
        }
    """
    result = {
        "is_power_candle": False,
        "type": None,
        "strength": 0,
        "score": 0.0,
        "details": {}
    }

    if not bar:
        return result

    o = float(bar.get('open', 0))
    h = float(bar.get('high', 0))
    l = float(bar.get('low', 0))
    c = float(bar.get('close', 0))

    if h <= l or c <= 0 or o <= 0:
        return result

    body = abs(c - o)
    bar_range = h - l
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l

    body_ratio = body / bar_range if bar_range > 0 else 0
    upper_shadow_ratio = upper_shadow / bar_range if bar_range > 0 else 0
    lower_shadow_ratio = lower_shadow / bar_range if bar_range > 0 else 0

    is_bullish = c > o
    is_bearish = c < o

    # Bullish Power Candle: Close at high (no upper shadow), large body
    # Tolerance: upper shadow < 5% of range
    if is_bullish and upper_shadow_ratio < 0.05 and body_ratio >= 0.6:
        strength = 1
        if body_ratio >= 0.8:
            strength = 3
        elif body_ratio >= 0.7:
            strength = 2

        result.update({
            "is_power_candle": True,
            "type": "BULLISH_POWER",
            "strength": strength,
            "score": 1.0 + (strength - 1) * 0.5,  # 1.0, 1.5, or 2.0
            "details": {
                "body_ratio": round(body_ratio, 2),
                "upper_shadow_ratio": round(upper_shadow_ratio, 3),
                "condition": "HIGH=CLOSE (Bulls in total control)"
            }
        })
        return result

    # Bearish Power Candle: Close at low (no lower shadow), large body
    # Tolerance: lower shadow < 5% of range
    if is_bearish and lower_shadow_ratio < 0.05 and body_ratio >= 0.6:
        strength = 1
        if body_ratio >= 0.8:
            strength = 3
        elif body_ratio >= 0.7:
            strength = 2

        result.update({
            "is_power_candle": True,
            "type": "BEARISH_POWER",
            "strength": strength,
            "score": -(1.0 + (strength - 1) * 0.5),  # -1.0, -1.5, or -2.0
            "details": {
                "body_ratio": round(body_ratio, 2),
                "lower_shadow_ratio": round(lower_shadow_ratio, 3),
                "condition": "LOW=CLOSE (Bears in total control)"
            }
        })
        return result

    return result


# ============================================================================
# v5.465: 量堆式拉升检测 (来源: 量价理论第29集)
# ============================================================================

def detect_volume_heap_rally(bars: List[Dict], lookback: int = 20) -> Dict:
    """
    v5.465: 量堆式拉升检测

    来源: 量价理论第29集 - 量堆与脉冲量

    核心规则:
    - 量堆式拉升: 连续3根以上放量柱形成"堆"状 (vs 单根脉冲量)
    - 形神兼备: 上涨角度陡 + 调整次数少
    - 日内2次以上量堆 = 动能持续性强

    风险识别:
    - 脉冲量陷阱: 单根 >= 3倍平均量的巨量可能是诱多
    - 量堆式下跌: 连续放量下跌 = 避免做多

    Returns:
        {
            "has_volume_heap": bool,
            "heap_count": int,  # 量堆出现次数
            "heap_type": "RALLY" | "DECLINE" | None,
            "momentum_strength": "STRONG" | "MODERATE" | "WEAK",
            "pulse_volume_warning": bool,  # 脉冲量陷阱警告
            "score": float,  # -2 to +2
            "details": {...}
        }
    """
    result = {
        "has_volume_heap": False,
        "heap_count": 0,
        "heap_type": None,
        "momentum_strength": "WEAK",
        "pulse_volume_warning": False,
        "score": 0.0,
        "details": {}
    }

    if not bars or len(bars) < lookback:
        return result

    recent = bars[-lookback:]

    # Extract data
    closes = [float(b.get('close', 0)) for b in recent]
    volumes = [float(b.get('volume', 0)) for b in recent]

    if not volumes or sum(volumes) == 0:
        return result

    avg_volume = sum(volumes) / len(volumes)

    # Find volume heaps (consecutive bars with above-average volume)
    rally_heaps = []  # [(start_idx, end_idx, avg_vol_ratio)]
    decline_heaps = []

    current_heap_start = None
    current_heap_type = None
    heap_volumes = []

    for i in range(len(recent)):
        vol = volumes[i]
        price_change = (closes[i] - closes[i-1]) / closes[i-1] * 100 if i > 0 and closes[i-1] > 0 else 0

        is_above_avg = vol > avg_volume * 1.2  # 20% above average

        if is_above_avg:
            bar_type = "RALLY" if price_change > 0.1 else ("DECLINE" if price_change < -0.1 else "NEUTRAL")

            if current_heap_start is None:
                current_heap_start = i
                current_heap_type = bar_type
                heap_volumes = [vol]
            elif bar_type == current_heap_type or bar_type == "NEUTRAL":
                heap_volumes.append(vol)
            else:
                # Heap ended
                if len(heap_volumes) >= 3:  # Minimum 3 bars for heap
                    heap_info = (current_heap_start, i-1, sum(heap_volumes)/len(heap_volumes)/avg_volume)
                    if current_heap_type == "RALLY":
                        rally_heaps.append(heap_info)
                    elif current_heap_type == "DECLINE":
                        decline_heaps.append(heap_info)
                # Start new heap
                current_heap_start = i
                current_heap_type = bar_type
                heap_volumes = [vol]
        else:
            # Volume dropped below threshold
            if current_heap_start is not None and len(heap_volumes) >= 3:
                heap_info = (current_heap_start, i-1, sum(heap_volumes)/len(heap_volumes)/avg_volume)
                if current_heap_type == "RALLY":
                    rally_heaps.append(heap_info)
                elif current_heap_type == "DECLINE":
                    decline_heaps.append(heap_info)
            current_heap_start = None
            current_heap_type = None
            heap_volumes = []

    # Check for heap in progress at the end
    if current_heap_start is not None and len(heap_volumes) >= 3:
        heap_info = (current_heap_start, len(recent)-1, sum(heap_volumes)/len(heap_volumes)/avg_volume)
        if current_heap_type == "RALLY":
            rally_heaps.append(heap_info)
        elif current_heap_type == "DECLINE":
            decline_heaps.append(heap_info)

    # Check for pulse volume warning (single spike >= 3x average)
    pulse_warning = False
    for i in range(len(volumes)):
        if volumes[i] >= avg_volume * 3:
            # Check if it's isolated (not part of a heap)
            neighbors_low = True
            for j in range(max(0, i-2), min(len(volumes), i+3)):
                if j != i and volumes[j] > avg_volume * 1.5:
                    neighbors_low = False
                    break
            if neighbors_low:
                pulse_warning = True
                break

    # Determine result
    has_heap = len(rally_heaps) > 0 or len(decline_heaps) > 0
    heap_count = len(rally_heaps) + len(decline_heaps)

    score = 0.0

    if len(rally_heaps) > 0:
        heap_type = "RALLY"
        # Momentum strength based on heap count
        if len(rally_heaps) >= 2:
            momentum = "STRONG"
            score = 2.0
        elif rally_heaps[-1][2] > 1.8:  # High volume ratio
            momentum = "STRONG"
            score = 1.5
        else:
            momentum = "MODERATE"
            score = 1.0
    elif len(decline_heaps) > 0:
        heap_type = "DECLINE"
        if len(decline_heaps) >= 2:
            momentum = "STRONG"
            score = -2.0
        else:
            momentum = "MODERATE"
            score = -1.0
    else:
        heap_type = None
        momentum = "WEAK"

    # Reduce score if pulse warning
    if pulse_warning:
        score *= 0.5

    result.update({
        "has_volume_heap": has_heap,
        "heap_count": heap_count,
        "heap_type": heap_type,
        "momentum_strength": momentum,
        "pulse_volume_warning": pulse_warning,
        "score": round(score, 1),
        "details": {
            "rally_heaps": len(rally_heaps),
            "decline_heaps": len(decline_heaps),
            "avg_volume": round(avg_volume, 0),
            "heap_info": {
                "rally": [(h[0], h[1], round(h[2], 2)) for h in rally_heaps],
                "decline": [(h[0], h[1], round(h[2], 2)) for h in decline_heaps]
            }
        }
    })

    return result


# ============================================================================
# v5.480: Wyckoff策略评分矩阵 (来源: v3.485主程序)
# ============================================================================

# Wyckoff阶段 × 形态 评分矩阵
# 同一形态在不同阶段有不同价值
WYCKOFF_PATTERN_SCORE_MATRIX = {
    # MARKUP (上涨期): 回调企稳形态加分，反转下跌形态减分
    "MARKUP": {
        "bullish_patterns": ["HAMMER", "BULL_ENGULF", "MORNING_STAR", "PIERCING", "TWO_B_BOTTOM", "ONE23_BUY", "BULLISH_ENGULFING"],
        "bearish_patterns": ["SHOOTING_STAR", "BEAR_ENGULF", "EVENING_STAR", "DARK_CLOUD", "TWO_B_TOP", "ONE23_SELL", "BEARISH_ENGULFING"],
        "bullish_bonus": 2,    # 顺势形态加分
        "bearish_penalty": -2,  # 逆势形态减分
    },
    # MARKDOWN (下跌期): 反弹衰竭形态加分，反转上涨形态减分
    "MARKDOWN": {
        "bullish_patterns": ["HAMMER", "BULL_ENGULF", "MORNING_STAR", "PIERCING", "TWO_B_BOTTOM", "ONE23_BUY", "BULLISH_ENGULFING"],
        "bearish_patterns": ["SHOOTING_STAR", "BEAR_ENGULF", "EVENING_STAR", "DARK_CLOUD", "TWO_B_TOP", "ONE23_SELL", "BEARISH_ENGULFING"],
        "bullish_bonus": -2,   # 逆势形态减分
        "bearish_penalty": 2,  # 顺势形态加分
    },
    # ACCUMULATION (吸筹期): 底部反转形态加分
    "ACCUMULATION": {
        "bullish_patterns": ["HAMMER", "BULL_ENGULF", "MORNING_STAR", "PIERCING", "TWO_B_BOTTOM", "ONE23_BUY", "DOUBLE_BOTTOM", "SPRING", "BULLISH_ENGULFING"],
        "bearish_patterns": ["SHOOTING_STAR", "BEAR_ENGULF", "EVENING_STAR", "DARK_CLOUD", "TWO_B_TOP", "ONE23_SELL", "BEARISH_ENGULFING"],
        "bullish_bonus": 2,    # 底部反转加分
        "bearish_penalty": -1,  # 破坏吸筹减分
    },
    # DISTRIBUTION (派发期): 顶部反转形态加分
    "DISTRIBUTION": {
        "bullish_patterns": ["HAMMER", "BULL_ENGULF", "MORNING_STAR", "PIERCING", "TWO_B_BOTTOM", "ONE23_BUY", "BULLISH_ENGULFING"],
        "bearish_patterns": ["SHOOTING_STAR", "BEAR_ENGULF", "EVENING_STAR", "DARK_CLOUD", "TWO_B_TOP", "ONE23_SELL", "DOUBLE_TOP", "UTAD", "BEARISH_ENGULFING"],
        "bullish_bonus": -1,   # 高位追多减分
        "bearish_penalty": 2,  # 派发确认加分
    },
    # RANGING (震荡期): 极端位置反转加分，中间位置中性
    "RANGING": {
        "bullish_patterns": ["HAMMER", "BULL_ENGULF", "TWO_B_BOTTOM", "BULLISH_ENGULFING"],
        "bearish_patterns": ["SHOOTING_STAR", "BEAR_ENGULF", "TWO_B_TOP", "BEARISH_ENGULFING"],
        "bullish_bonus": 1,    # 震荡中多头形态小加分
        "bearish_penalty": 1,  # 震荡中空头形态小加分(做空方向)
    },
}


def compute_wyckoff_strategy_score(wyckoff_phase: str, patterns: List[str],
                                     pattern_2b: str, pos_in_channel: float) -> Tuple[int, str]:
    """
    v5.498: 计算Wyckoff策略评分 (更新: UNCLEAR纯位置策略)

    Args:
        wyckoff_phase: Wyckoff阶段 (MARKUP/MARKDOWN/ACCUMULATION/DISTRIBUTION/RANGING)
        patterns: K线形态列表 ["HAMMER", "BULLISH_ENGULFING", ...]
        pattern_2b: 2B形态 ("2B_BUY" / "2B_SELL" / "NONE")
        pos_in_channel: Donchian位置 (0~1)

    Returns: (score, reason)
        score: -2 ~ +2
        reason: 评分原因说明
    """
    # v5.498 P0-2: UNCLEAR阶段纯位置策略 (替代v5.487的归零)
    if not wyckoff_phase or wyckoff_phase == "UNCLEAR":
        if pos_in_channel is not None:
            if pos_in_channel < 0.20:
                logger.debug(f"[v5.498] UNCLEAR阶段纯位置策略: pos={pos_in_channel:.2%} → UNCLEAR_LOW_BUY (+2)")
                return 2, "UNCLEAR_LOW_BUY"      # 极低位→倾向买
            elif pos_in_channel > 0.80:
                logger.debug(f"[v5.498] UNCLEAR阶段纯位置策略: pos={pos_in_channel:.2%} → UNCLEAR_HIGH_SELL (-2)")
                return -2, "UNCLEAR_HIGH_SELL"   # 极高位→倾向卖
        return 0, "UNCLEAR_MID_HOLD"     # 中间位置→等待

    if wyckoff_phase not in WYCKOFF_PATTERN_SCORE_MATRIX:
        return 0, "WYCKOFF_UNKNOWN"

    matrix = WYCKOFF_PATTERN_SCORE_MATRIX[wyckoff_phase]
    bullish_patterns = matrix["bullish_patterns"]
    bearish_patterns = matrix["bearish_patterns"]
    bullish_bonus = matrix["bullish_bonus"]
    bearish_penalty = matrix["bearish_penalty"]

    score = 0
    reasons = []

    # 检查K线形态
    for p in patterns:
        p_upper = p.upper()
        if any(bp in p_upper for bp in bullish_patterns):
            score += bullish_bonus
            reasons.append(f"PATTERN_{p}_{wyckoff_phase}")
            break
        if any(sp in p_upper for sp in bearish_patterns):
            score += bearish_penalty
            reasons.append(f"PATTERN_{p}_{wyckoff_phase}")
            break

    # 检查2B形态
    two_b_upper = (pattern_2b or "").upper()
    if "2B_BUY" in two_b_upper or "TWO_B_BOTTOM" in two_b_upper:
        if wyckoff_phase in ("MARKUP", "ACCUMULATION"):
            score += 1
            reasons.append(f"2B_BOTTOM_{wyckoff_phase}")
        elif wyckoff_phase == "MARKDOWN":
            score -= 1
            reasons.append(f"2B_BOTTOM_COUNTER_{wyckoff_phase}")
    elif "2B_SELL" in two_b_upper or "TWO_B_TOP" in two_b_upper:
        if wyckoff_phase in ("MARKDOWN", "DISTRIBUTION"):
            score += 1
            reasons.append(f"2B_TOP_{wyckoff_phase}")
        elif wyckoff_phase == "MARKUP":
            score -= 1
            reasons.append(f"2B_TOP_COUNTER_{wyckoff_phase}")

    # RANGING阶段的极端位置bonus
    if wyckoff_phase == "RANGING":
        if pos_in_channel is not None:
            if pos_in_channel < 0.20:
                score += 1  # 极低位多头加分
                reasons.append("RANGING_EXTREME_LOW")
            elif pos_in_channel > 0.80:
                score += 1  # 极高位空头加分(空头方向已由形态决定)
                reasons.append("RANGING_EXTREME_HIGH")

    # 限制分数范围
    score = max(-2, min(2, score))

    reason_str = "+".join(reasons) if reasons else "NEUTRAL"
    return score, reason_str


def compute_position_score(pos_in_channel: float) -> Tuple[int, str]:
    """
    v5.480: 计算位置分

    Args:
        pos_in_channel: Donchian位置 (0~1)

    Returns: (score, reason)
        score: -4 ~ +4
        reason: 位置描述
    """
    if pos_in_channel is None:
        return 0, "UNKNOWN"

    pos = pos_in_channel

    if pos < 0.10:
        return 4, "EXTREME_OVERSOLD"
    elif pos < 0.20:
        return 3, "VERY_OVERSOLD"
    elif pos < 0.30:
        return 2, "OVERSOLD"
    elif pos < 0.40:
        return 1, "SLIGHTLY_OVERSOLD"
    elif pos <= 0.60:
        return 0, "NEUTRAL"
    elif pos <= 0.70:
        return -1, "SLIGHTLY_OVERBOUGHT"
    elif pos <= 0.80:
        return -2, "OVERBOUGHT"
    elif pos <= 0.90:
        return -3, "VERY_OVERBOUGHT"
    else:
        return -4, "EXTREME_OVERBOUGHT"


def compute_volume_score(volume_ratio: float, l1_trend: str, divergence: str) -> Tuple[int, str]:
    """
    v5.480: 计算量能分

    Args:
        volume_ratio: 当前成交量/均量
        l1_trend: L1趋势 (UP/DOWN/SIDE)
        divergence: 背离类型 ("BULLISH_DIVERGENCE" / "BEARISH_DIVERGENCE" / "NONE")

    Returns: (score, reason)
        score: -2 ~ +2
        reason: 量能描述
    """
    score = 0
    reasons = []

    # 放量配合趋势
    if volume_ratio > 1.5:
        if l1_trend == "UP":
            score += 1
            reasons.append("VOL_UP_TREND")
        elif l1_trend == "DOWN":
            score -= 1
            reasons.append("VOL_DOWN_TREND")
        else:
            reasons.append("VOL_SPIKE_SIDE")
    elif volume_ratio < 0.5:
        score -= 0.5
        reasons.append("LOW_VOL")

    # 背离加分
    if divergence == "BULLISH_DIVERGENCE":
        score += 1
        reasons.append("BULLISH_DIV")
    elif divergence == "BEARISH_DIVERGENCE":
        score -= 1
        reasons.append("BEARISH_DIV")

    # 限制范围
    score = max(-2, min(2, int(score)))
    reason_str = "+".join(reasons) if reasons else "NORMAL"
    return score, reason_str


def compute_l2_four_category_score(
    patterns: List[str],
    pattern_2b: str,
    pos_in_channel: float,
    volume_ratio: float,
    divergence: str,
    wyckoff_phase: str,
    l1_trend: str,
    candle_shape_score: float = 0.0
) -> Dict:
    """
    v5.480: L2四大类评分

    总分范围: -14 ~ +14
    - 【形态分】: ±6 (patterns + 2B + K线形态)
    - 【位置分】: ±4 (pos_in_channel)
    - 【量能分】: ±2 (volume + divergence)
    - 【Wyckoff策略分】: ±2 (阶段×形态匹配)

    Returns:
        {
            "total_score": float,
            "pattern_score": float,
            "position_score": float,
            "volume_score": float,
            "wyckoff_score": float,
            "signal": str,  # STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL
            "details": {...}
        }
    """
    # 1. 形态分 (±6)
    pattern_score = 0.0

    # 2B形态 (±1.5)
    if pattern_2b == "2B_BUY":
        pattern_score += 1.5
    elif pattern_2b == "2B_SELL":
        pattern_score -= 1.5

    # K线形态 (±1.5)
    bullish_patterns = ["HAMMER", "BULLISH_ENGULFING", "LONG_LOWER_SHADOW"]
    bearish_patterns = ["SHOOTING_STAR", "BEARISH_ENGULFING"]
    for p in patterns:
        if p in bullish_patterns:
            pattern_score += 0.75
        elif p in bearish_patterns:
            pattern_score -= 0.75

    # K线形态分 (±1)
    pattern_score += candle_shape_score

    # 限制形态分范围
    pattern_score = max(-6, min(6, pattern_score))

    # 2. 位置分 (±4)
    position_score, position_reason = compute_position_score(pos_in_channel)

    # 3. 量能分 (±2)
    volume_score, volume_reason = compute_volume_score(volume_ratio, l1_trend, divergence)

    # 4. Wyckoff策略分 (±2)
    wyckoff_score, wyckoff_reason = compute_wyckoff_strategy_score(
        wyckoff_phase, patterns, pattern_2b, pos_in_channel
    )

    # 总分
    total_score = pattern_score + position_score + volume_score + wyckoff_score
    total_score = max(-14, min(14, total_score))

    # 信号判定
    if total_score >= 7:
        signal = "STRONG_BUY"
    elif total_score >= 4:
        signal = "BUY"
    elif total_score <= -7:
        signal = "STRONG_SELL"
    elif total_score <= -4:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "total_score": round(total_score, 1),
        "pattern_score": round(pattern_score, 1),
        "position_score": position_score,
        "volume_score": volume_score,
        "wyckoff_score": wyckoff_score,
        "signal": signal,
        "percentage": round(abs(total_score) / 14 * 100, 0),
        "details": {
            "position_reason": position_reason,
            "volume_reason": volume_reason,
            "wyckoff_reason": wyckoff_reason,
            "wyckoff_phase": wyckoff_phase,
            "candle_shape_score": candle_shape_score,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# v5.487: 新增函数 - Wyckoff稳定性 + 回调检测 + 底部保护
# ═══════════════════════════════════════════════════════════════════════════════

# v5.487 P0-1: Wyckoff阶段确认缓存 (防止跳变)
_wyckoff_phase_cache = {}  # {"SYMBOL": {"phase": str, "confirm_count": int, "pending_phase": str}}


def get_confirmed_wyckoff_phase_v5487(symbol: str, trend_x4: str, pos_in_channel: float) -> Tuple[str, str, Dict]:
    """
    v5.487 P0-1: Wyckoff阶段确认机制 (防止ZEC等品种阶段跳变)
    v5.494 增强: 极端位置覆盖趋势判断

    核心逻辑:
    - 连续2根K线确认才切换阶段
    - UNCLEAR可立即切换 (无历史状态)
    - v5.494: 极端位置修正 (EXTREME_LOW+down→ACCUMULATION, EXTREME_HIGH+up→DISTRIBUTION)

    返回: (confirmed_phase, sub_state, confirm_info)
    """
    global _wyckoff_phase_cache

    # 计算原始阶段
    x4 = (trend_x4 or "side").lower()
    pos = pos_in_channel if pos_in_channel is not None else 0.5

    # v5.494: 极端位置修正 - 位置比趋势更重要
    if pos < 0.15:  # EXTREME_LOW
        if x4 == "down":
            # 极低位置 + 下跌趋势 = 可能是底部吸筹，不是下跌趋势
            raw_phase = "ACCUMULATION"
            logger.info(f"[v5.494] Wyckoff位置修正: EXTREME_LOW+down → ACCUMULATION (底部吸筹)")
        elif x4 == "up":
            raw_phase = "MARKUP"
        else:
            raw_phase = "ACCUMULATION"
    elif pos > 0.85:  # EXTREME_HIGH
        if x4 == "up":
            # 极高位置 + 上涨趋势 = 可能是顶部派发，不是上涨趋势
            raw_phase = "DISTRIBUTION"
            logger.info(f"[v5.494] Wyckoff位置修正: EXTREME_HIGH+up → DISTRIBUTION (顶部派发)")
        elif x4 == "down":
            raw_phase = "MARKDOWN"
        else:
            raw_phase = "DISTRIBUTION"
    elif x4 == "up":
        raw_phase = "MARKUP"
    elif x4 == "down":
        raw_phase = "MARKDOWN"
    elif pos < 0.30:
        raw_phase = "ACCUMULATION"
    elif pos > 0.70:
        raw_phase = "DISTRIBUTION"
    else:
        raw_phase = "RANGING"

    # 获取或初始化缓存
    if symbol not in _wyckoff_phase_cache:
        _wyckoff_phase_cache[symbol] = {
            "phase": raw_phase,
            "confirm_count": 1,
            "pending_phase": None,
        }
        logger.info(f"[v5.487] Wyckoff确认初始化: {symbol} → {raw_phase}")
        return raw_phase, "NONE", {"pending": None, "count": 1, "switched": True}

    cache = _wyckoff_phase_cache[symbol]
    current_phase = cache["phase"]
    pending_phase = cache.get("pending_phase")

    # 如果阶段与当前确认阶段相同
    if raw_phase == current_phase:
        cache["pending_phase"] = None
        cache["confirm_count"] = 0
        return current_phase, "NONE", {"pending": None, "count": 0, "switched": False}

    # 阶段不同，检查是否需要确认
    if raw_phase == pending_phase:
        # 连续第二次 → 确认切换
        cache["phase"] = raw_phase
        cache["pending_phase"] = None
        cache["confirm_count"] = 0
        logger.info(f"[v5.487] Wyckoff阶段确认: {symbol} {current_phase} → {raw_phase}")
        return raw_phase, "NONE", {"pending": None, "count": 2, "switched": True}
    else:
        # 新的待确认阶段
        cache["pending_phase"] = raw_phase
        cache["confirm_count"] = 1
        logger.debug(f"[v5.487] Wyckoff待确认: {symbol} 当前={current_phase}, 待确认={raw_phase}")
        return current_phase, "NONE", {"pending": raw_phase, "count": 1, "switched": False}


def detect_pullback_stabilization_v5487(bars: List[Dict], lookback: int = 10, threshold: float = 0.05) -> Dict:
    """
    v5.487 P0-2: 检测短期回调后的企稳信号

    核心逻辑:
    - 计算从近lookback根K线高点的回调幅度
    - 回调>threshold(5%) + 企稳K线(锤子/十字星/长下影) → 暂停SELL

    返回: {"is_stabilizing": bool, "pullback_pct": float, "stabilization_pattern": str}
    """
    if not bars or len(bars) < 3:
        return {"is_stabilizing": False, "pullback_pct": 0.0, "stabilization_pattern": "NONE"}

    # 获取回溯期间的高点
    bars_to_check = bars[-lookback:] if len(bars) >= lookback else bars
    recent_high = max(float(bar.get("high", 0)) for bar in bars_to_check)
    current_close = float(bars[-1].get("close", 0))

    if recent_high <= 0 or current_close <= 0:
        return {"is_stabilizing": False, "pullback_pct": 0.0, "stabilization_pattern": "NONE"}

    # 计算回调幅度
    pullback_pct = (recent_high - current_close) / recent_high

    if pullback_pct < threshold:
        return {"is_stabilizing": False, "pullback_pct": pullback_pct, "stabilization_pattern": "NONE"}

    # 检测最后一根K线是否是企稳形态
    last_bar = bars[-1]
    open_p = float(last_bar.get("open", 0))
    high_p = float(last_bar.get("high", 0))
    low_p = float(last_bar.get("low", 0))
    close_p = float(last_bar.get("close", 0))

    body = abs(close_p - open_p)
    full_range = high_p - low_p if high_p > low_p else 0.0001
    lower_shadow = min(open_p, close_p) - low_p
    upper_shadow = high_p - max(open_p, close_p)

    stabilization_pattern = "NONE"

    if lower_shadow >= 2 * body and upper_shadow < body:
        stabilization_pattern = "HAMMER"
    elif body < 0.15 * full_range:
        stabilization_pattern = "DOJI"
    elif lower_shadow > 0.5 * full_range:
        stabilization_pattern = "LONG_LOWER_SHADOW"

    is_stabilizing = stabilization_pattern != "NONE"

    return {
        "is_stabilizing": is_stabilizing,
        "pullback_pct": pullback_pct,
        "stabilization_pattern": stabilization_pattern
    }


def check_bottom_reversal_protection_v5487(rsi14: float, bars: List[Dict]) -> Dict:
    """
    v5.487 P1-4: 检测底部反转保护条件

    满足任一条件阻止SELL:
    - RSI < 30 (超卖)
    - 看涨吞没K线
    - 锤子线

    返回: {"should_protect": bool, "reason": str}
    """
    reasons = []

    # 条件1: RSI超卖
    if rsi14 is not None and rsi14 < 30:
        reasons.append(f"RSI_OVERSOLD_{rsi14:.1f}")

    # 条件2&3: K线形态
    if bars and len(bars) >= 2:
        curr = bars[-1]
        prev = bars[-2]

        c_open = float(curr.get("open", 0))
        c_close = float(curr.get("close", 0))
        c_high = float(curr.get("high", 0))
        c_low = float(curr.get("low", 0))
        p_open = float(prev.get("open", 0))
        p_close = float(prev.get("close", 0))

        # 看涨吞没
        if p_close < p_open and c_close > c_open:
            if c_close > p_open and c_open < p_close:
                reasons.append("BULL_ENGULFING")

        # 锤子线
        body = abs(c_close - c_open)
        full_range = c_high - c_low if c_high > c_low else 0.0001
        lower_shadow = min(c_open, c_close) - c_low
        upper_shadow = c_high - max(c_open, c_close)

        if lower_shadow >= 2 * body and upper_shadow < body:
            reasons.append("HAMMER")

    should_protect = len(reasons) > 0
    return {
        "should_protect": should_protect,
        "reason": "+".join(reasons) if reasons else "NONE"
    }


def detect_wyckoff_sub_state_v5487(wyckoff_phase: str, bars: List[Dict]) -> Tuple[str, float]:
    """
    v5.487 P1-3: 检测Wyckoff子状态

    规则:
    - MARKUP + 连续2根阴线 → sub_state="PULLBACK"
    - MARKDOWN + 连续2根阳线 → sub_state="RALLY"
    - 子状态时降低反向交易权重50%

    返回: (sub_state, weight_multiplier)
    """
    if not bars or len(bars) < 2:
        return "NONE", 1.0

    last_bar = bars[-1]
    prev_bar = bars[-2]

    last_close = float(last_bar.get("close", 0))
    last_open = float(last_bar.get("open", 0))
    prev_close = float(prev_bar.get("close", 0))
    prev_open = float(prev_bar.get("open", 0))

    last_is_bearish = last_close < last_open
    prev_is_bearish = prev_close < prev_open
    last_is_bullish = last_close > last_open
    prev_is_bullish = prev_close > prev_open

    if wyckoff_phase == "MARKUP" and last_is_bearish and prev_is_bearish:
        return "PULLBACK", 0.5

    if wyckoff_phase == "MARKDOWN" and last_is_bullish and prev_is_bullish:
        return "RALLY", 0.5

    return "NONE", 1.0


def compute_dual_period_position_v5487(bars: List[Dict], long_period: int = 120, short_period: int = 20) -> Dict:
    """
    v5.487 P2-6: 双周期位置确认

    计算长期位置(120根) + 短期位置(20根)，识别以下场景:
    - PULLBACK_IN_UPTREND: 长期UPPER_HALF + 短期LOWER_HALF → SELL权重-30%
    - RALLY_IN_DOWNTREND: 长期LOWER_HALF + 短期UPPER_HALF → BUY权重-30%

    返回: {"long_pos", "short_pos", "context", "weight_adjustment"}
    """
    if not bars or len(bars) < short_period:
        return {
            "long_pos": 0.5, "short_pos": 0.5,
            "long_bucket": "MIDDLE", "short_bucket": "MIDDLE",
            "context": "INSUFFICIENT_DATA",
            "weight_adjustment": {"BUY": 1.0, "SELL": 1.0}
        }

    last_close = float(bars[-1].get("close", 0))

    # 长期位置
    long_bars = bars[-min(len(bars), long_period):]
    long_high = max(float(b.get("high", 0)) for b in long_bars)
    long_low = min(float(b.get("low", float('inf'))) for b in long_bars)
    if long_low == float('inf'):
        long_low = 0
    long_range = max(long_high - long_low, 1e-9)
    long_pos = (last_close - long_low) / long_range
    long_pos = max(0.0, min(1.0, long_pos))

    # 短期位置
    short_bars = bars[-short_period:]
    short_high = max(float(b.get("high", 0)) for b in short_bars)
    short_low = min(float(b.get("low", float('inf'))) for b in short_bars)
    if short_low == float('inf'):
        short_low = 0
    short_range = max(short_high - short_low, 1e-9)
    short_pos = (last_close - short_low) / short_range
    short_pos = max(0.0, min(1.0, short_pos))

    long_bucket = "UPPER_HALF" if long_pos >= 0.5 else "LOWER_HALF"
    short_bucket = "UPPER_HALF" if short_pos >= 0.5 else "LOWER_HALF"

    weight_adjustment = {"BUY": 1.0, "SELL": 1.0}

    if long_bucket == "UPPER_HALF" and short_bucket == "LOWER_HALF":
        context = "PULLBACK_IN_UPTREND"
        weight_adjustment["SELL"] = 0.7
    elif long_bucket == "LOWER_HALF" and short_bucket == "UPPER_HALF":
        context = "RALLY_IN_DOWNTREND"
        weight_adjustment["BUY"] = 0.7
    elif long_bucket == short_bucket:
        context = "ALIGNED"
    else:
        context = "DIVERGENT"

    return {
        "long_pos": round(long_pos, 3),
        "short_pos": round(short_pos, 3),
        "long_bucket": long_bucket,
        "short_bucket": short_bucket,
        "context": context,
        "weight_adjustment": weight_adjustment
    }

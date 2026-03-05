"""
Signal Generator
================
Combines L1, L2, and DeepSeek analysis for final signal.
Synced from v3.498 main program.

v5.498 Update (HOLD门卫开放 + UNCLEAR位置策略):
- UNCLEAR阶段纯位置策略 (替代v5.487的归零):
  * pos<20% → +2分 (极低位倾向买入)
  * pos>80% → -2分 (极高位倾向卖出)
  * 中间位置 → 0分 (等待)

v3.430 Update (Review-Driven Optimization):
- Handle FORCE_DOWN consensus: Drop >= 30% forces DOWN trend
- Handle dynamic ADX threshold adjustments
- Handle strong stock protection (PROTECTED_HIGH)
- Enhanced confidence adjustments based on consensus type

v5.487 Update (Wyckoff稳定性 + 回调检测 + 底部保护):
- P0-1: Wyckoff阶段确认机制 (连续2根确认防跳变)
- P0-2: 短期回调企稳检测 (跌幅>5%+企稳K线→暂停SELL)
- P1-3: MARKUP_PULLBACK子状态 (反向权重×0.5)
- P1-4: 底部反转保护 (RSI<30/吞没/锤子→暂停SELL)
- P2-5: UNCLEAR阶段Wyckoff分归零 → v5.498更新为纯位置策略
- P2-6: 双周期位置确认 (背离时权重×0.7)

v5.480 Update (L1 Wyckoff定位 + L2四大类评分):
- L1 Wyckoff阶段定位 (trend_x4 + pos_in_channel → 5种阶段)
- L2四大类评分: 形态分(±6) + 位置分(±4) + 量能分(±2) + Wyckoff策略分(±2) = ±14
- 信号阈值: STRONG_BUY≥7 | BUY≥4 | HOLD[-3,+3] | SELL≤-4 | STRONG_SELL≤-7
"""

import logging
from typing import List, Dict
from datetime import datetime

from .l1_analysis import L1Analyzer, determine_wyckoff_phase, get_wyckoff_l2_strategy
from .l2_analysis import L2Analyzer, compute_l2_four_category_score
from .deepseek_analyzer import DeepSeekAnalyzer

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Comprehensive Signal Generator with AI Arbitration"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.l1_analyzer = L1Analyzer(config)
        self.l2_analyzer = L2Analyzer(config)
        self.deepseek = DeepSeekAnalyzer(config=config)

    def generate(
        self,
        bars: List[Dict],
        symbol: str = "",
        timeframe: str = "30m"
    ) -> Dict:
        """
        Generate comprehensive trading signal

        Flow:
        1. L1 trend analysis
        2. L2 signal analysis
        3. DeepSeek arbitration (if conflict)
        4. Final signal negotiation

        Returns complete analysis result
        """
        result = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": datetime.now(),
            "action": "HOLD",
            "confidence": 0.0,
            "current_price": 0.0,
            "l1": {},
            "l2": {},
            "deepseek": {},
            "reason": "",
            "source": "L1_L2_NEGOTIATION",
            "consensus": "",  # v3.430: Consensus type (AGREE/FORCE_DOWN/DOW_OVERRIDE/etc.)
            "protected": False,  # v3.430: Strong stock protection active
            # v5.480: Wyckoff and four-category scoring
            "wyckoff_phase": "",
            "l2_strategy": "",
            "four_category_score": {}
        }

        if not bars or len(bars) < 20:
            result["reason"] = "Insufficient data"
            return result

        try:
            # L1 Trend Analysis
            l1_result = self.l1_analyzer.analyze(bars)

            # v5.455: Calculate L1 decision (STRONG BUY/BUY/HOLD/SELL/STRONG SELL)
            l1_decision = self._calculate_l1_decision(l1_result)
            l1_result["decision"] = l1_decision

            result["l1"] = l1_result

            # v3.430: Extract consensus and protection status
            result["consensus"] = l1_result.get("consensus", "")
            result["protected"] = l1_result.get("protected", False)

            # v5.480: Wyckoff phase positioning
            # Use dow_trend as trend_x4 approximation (cloud version doesn't have exact x4 timeframe)
            trend_x4 = l1_result.get("dow_trend", "UNKNOWN")
            if trend_x4 == "UNKNOWN":
                trend_x4 = l1_result.get("trend", "SIDE")

            # pos_in_channel - calculate from bars (cloud version approximation)
            pos_in_channel = self._calculate_pos_in_channel(bars)

            wyckoff_phase = determine_wyckoff_phase(trend_x4, pos_in_channel)
            l2_strategy = get_wyckoff_l2_strategy(wyckoff_phase)

            result["wyckoff_phase"] = wyckoff_phase
            result["l2_strategy"] = l2_strategy
            l1_result["wyckoff_phase"] = wyckoff_phase
            l1_result["l2_strategy"] = l2_strategy

            # L2 Signal Analysis
            l2_result = self.l2_analyzer.analyze(
                bars,
                l1_trend=l1_result.get("trend", "SIDE"),
                l1_regime=l1_result.get("regime", "RANGING")
            )

            # v5.455: Calculate L2 decision (STRONG BUY/BUY/HOLD/SELL/STRONG SELL)
            l2_decision = self._calculate_l2_decision(l2_result)
            l2_result["decision"] = l2_decision

            # v5.480: Compute four-category score
            four_cat_score = compute_l2_four_category_score(
                patterns=l2_result.get("patterns", []),
                pattern_2b=l2_result.get("pattern_2b", "NONE"),
                pos_in_channel=pos_in_channel,
                volume_ratio=l2_result.get("volume_ratio", 1.0),
                divergence=l2_result.get("divergence", "NONE"),
                wyckoff_phase=wyckoff_phase,
                l1_trend=l1_result.get("trend", "SIDE"),
                candle_shape_score=l2_result.get("candle_shape_score", 0.0)
            )
            result["four_category_score"] = four_cat_score
            l2_result["four_category_score"] = four_cat_score

            result["l2"] = l2_result

            # Current price
            result["current_price"] = float(bars[-1]["close"])

            # Check if DeepSeek arbitration needed
            if self.deepseek.should_arbitrate(l1_result, l2_result):
                logger.info(f"{symbol}: Triggering DeepSeek arbitration")
                ds_result = self.deepseek.analyze_trend(
                    symbol, l1_result, l2_result, bars
                )
                result["deepseek"] = ds_result

                # Arbitrate with tech signal
                tech_signal = l2_result.get("signal", "HOLD")
                tech_conf = l1_result.get("confidence", 0.5) * 0.6 + \
                           (l2_result.get("quality_score", 3) / 9) * 0.4

                final = self.deepseek.arbitrate(tech_signal, tech_conf, ds_result)

                result["action"] = final["final_signal"]
                result["confidence"] = final["final_confidence"]
                result["source"] = final["source"]
                result["reason"] = ds_result.get("ai_reason", "AI arbitration")

            else:
                # Standard L1-L2 negotiation
                negotiated = self._negotiate_signal(l1_result, l2_result)
                result["action"] = negotiated["action"]
                result["confidence"] = negotiated["confidence"]
                result["reason"] = negotiated["reason"]
                result["source"] = "L1_L2_NEGOTIATION"

                # v3.430: Adjust for FORCE_DOWN - higher confidence for sell signals
                if result["consensus"] == "FORCE_DOWN":
                    if result["action"] == "SELL":
                        result["confidence"] = min(0.95, result["confidence"] * 1.2)
                        result["reason"] += " [FORCE_DOWN active]"
                    elif result["action"] == "BUY":
                        # Reduce confidence for buy signals when FORCE_DOWN is active
                        result["confidence"] *= 0.7
                        result["reason"] += " [FORCE_DOWN warning]"

                # v3.430: Handle strong stock protection
                if result["protected"]:
                    if result["action"] == "SELL":
                        # Don't sell protected strong stocks on small pullback
                        result["action"] = "HOLD"
                        result["confidence"] = 0.5
                        result["reason"] = "Strong stock protected (small pullback)"

            return result

        except Exception as e:
            logger.error(f"Signal generation error {symbol}: {e}")
            result["reason"] = f"Analysis error: {str(e)}"
            return result

    def _negotiate_signal(self, l1: Dict, l2: Dict) -> Dict:
        """
        L1-L2 signal negotiation (without DeepSeek)

        Rules based on v3.455:
        - Trending market: Follow L1, L2 for timing
        - Ranging market: High sell, low buy
        - FORCE_DOWN and strong stock protection handled in generate()
        - v3.455: Confidence based on L2 score strength
        """
        trend = l1.get("trend", "SIDE")
        regime = l1.get("regime", "RANGING")
        strength = l1.get("strength", "WEAK")
        l1_conf = l1.get("confidence", 0.5)

        l2_signal = l2.get("signal", "HOLD")
        l2_score = l2.get("score", 0)
        rsi = l2.get("rsi", 50)
        quality = l2.get("quality_score", 3)

        action = "HOLD"
        reason = ""

        # v3.455: Calculate confidence based on L2 score strength
        # score range: -12 ~ +12, map to confidence 30% ~ 90%
        score_abs = abs(l2_score)
        base_confidence = 0.3 + (score_abs / 12) * 0.6  # 0.3 ~ 0.9
        confidence = base_confidence

        # Trending market strategy
        if regime == "TRENDING":
            if trend == "UP":
                if l2_signal == "BUY":
                    action = "BUY"
                    confidence = max(base_confidence, 0.8 if strength == "STRONG" else 0.7)
                    reason = "Uptrend pullback buy"
                elif l2_signal == "HOLD" and rsi < 40:
                    action = "BUY"
                    confidence = max(base_confidence, 0.6)
                    reason = "Uptrend RSI oversold"
                elif l2_signal == "SELL" and rsi > 75:
                    action = "SELL"
                    confidence = max(base_confidence, 0.55)
                    reason = "Uptrend extreme overbought"
                else:
                    reason = "Uptrend waiting"

            elif trend == "DOWN":
                if l2_signal == "SELL":
                    action = "SELL"
                    confidence = max(base_confidence, 0.8 if strength == "STRONG" else 0.7)
                    reason = "Downtrend bounce sell"
                elif l2_signal == "HOLD" and rsi > 60:
                    action = "SELL"
                    confidence = max(base_confidence, 0.6)
                    reason = "Downtrend RSI overbought"
                elif l2_signal == "BUY" and rsi < 25:
                    action = "BUY"
                    confidence = max(base_confidence, 0.55)
                    reason = "Downtrend extreme oversold"
                else:
                    reason = "Downtrend waiting"

            else:  # SIDE in trending
                if l2_signal != "HOLD" and quality >= 5:
                    action = l2_signal
                    confidence = max(base_confidence, 0.6)
                    reason = f"Sideways with L2 {l2_signal}"
                else:
                    reason = "Sideways watching"

        # Ranging market strategy
        else:
            if l2_signal == "BUY" and rsi < 35:
                action = "BUY"
                confidence = max(base_confidence, 0.65 if quality >= 5 else 0.55)
                reason = "Ranging low buy"
            elif l2_signal == "SELL" and rsi > 65:
                action = "SELL"
                confidence = max(base_confidence, 0.65 if quality >= 5 else 0.55)
                reason = "Ranging high sell"
            else:
                reason = "Ranging wait for extremes"

        # Quality adjustment
        if action != "HOLD" and quality < 4:
            confidence *= 0.85

        return {
            "action": action,
            "confidence": round(confidence, 2),
            "reason": reason
        }

    def _calculate_l1_decision(self, l1: Dict) -> str:
        """
        v5.455: Calculate L1 decision based on trend and strength

        Logic:
        - UP + STRONG → STRONG BUY
        - UP + MODERATE → BUY
        - UP + WEAK → HOLD (weak trend, no action)
        - DOWN + STRONG → STRONG SELL
        - DOWN + MODERATE → SELL
        - DOWN + WEAK → HOLD
        - SIDE → HOLD
        """
        trend = l1.get("trend", "SIDE")
        strength = l1.get("strength", "WEAK")

        if trend == "UP":
            if strength == "STRONG":
                return "STRONG BUY"
            elif strength == "MODERATE":
                return "BUY"
            else:  # WEAK
                return "HOLD"
        elif trend == "DOWN":
            if strength == "STRONG":
                return "STRONG SELL"
            elif strength == "MODERATE":
                return "SELL"
            else:  # WEAK
                return "HOLD"
        else:  # SIDE
            return "HOLD"

    def _calculate_l2_decision(self, l2: Dict) -> str:
        """
        v5.455: Calculate L2 decision based on signal and score

        Logic (v5.455 score range: -12 ~ +12):
        - BUY + score >= 6 (50% threshold) → STRONG BUY
        - BUY → BUY
        - SELL + score <= -6 → STRONG SELL
        - SELL → SELL
        - HOLD → HOLD
        """
        signal = l2.get("signal", "HOLD")
        score = l2.get("score", 0)

        if signal == "BUY":
            if score >= 6:  # v5.455: 50% of max score triggers STRONG
                return "STRONG BUY"
            else:
                return "BUY"
        elif signal == "SELL":
            if score <= -6:  # v5.455: 50% of min score triggers STRONG
                return "STRONG SELL"
            else:
                return "SELL"
        else:
            return "HOLD"

    def _calculate_pos_in_channel(self, bars: List[Dict], lookback: int = 20) -> float:
        """
        v5.480: Calculate position in Donchian channel (0 ~ 1)

        Position shows where current price sits within the recent range:
        - 0.0 = At lowest point (extremely oversold)
        - 0.5 = Middle of range (neutral)
        - 1.0 = At highest point (extremely overbought)

        Args:
            bars: OHLCV bar data
            lookback: Number of bars to calculate Donchian channel

        Returns:
            Position in channel (0.0 ~ 1.0)
        """
        if not bars or len(bars) < lookback:
            return 0.5  # Default to neutral

        try:
            recent = bars[-lookback:]
            highs = [float(b.get("high", 0)) for b in recent]
            lows = [float(b.get("low", 0)) for b in recent]

            highest = max(highs)
            lowest = min(lows)
            current = float(bars[-1].get("close", 0))

            if highest <= lowest:
                return 0.5

            pos = (current - lowest) / (highest - lowest)
            return max(0.0, min(1.0, pos))

        except Exception:
            return 0.5

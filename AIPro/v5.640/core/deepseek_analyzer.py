"""
DeepSeek AI Arbitration Module
==============================
Synced from v3.411 main program (v3.330 DeepSeek Trend Arbitration)

Features:
- AI + Tech conflict arbitration
- Trend/Ranging market judgment
- Multi-factor analysis
- Token-efficient prompts
"""

import os
import logging
import json
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("openai library not installed, DeepSeek disabled")


class DeepSeekAnalyzer:
    """DeepSeek AI Arbitrator for trend analysis"""

    def __init__(self, api_key: str = None, config: Dict = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.config = config or {}
        self.enabled = bool(self.api_key) and OPENAI_AVAILABLE
        self.client = None
        self.timeout = self.config.get("deepseek_timeout", 30)

        if self.enabled:
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=DEEPSEEK_BASE_URL
                )
                logger.info("DeepSeek AI Arbitrator enabled")
            except Exception as e:
                logger.error(f"DeepSeek init failed: {e}")
                self.enabled = False

    def should_arbitrate(self, l1_result: Dict, l2_result: Dict) -> bool:
        """
        Determine if arbitration is needed (v3.330)

        Triggers:
        1. L1 trend conflicts with L2 signal
        2. Confidence difference > threshold
        3. L1 regime unclear
        """
        if not self.enabled:
            return False

        l1_trend = l1_result.get("trend", "SIDE")
        l1_confidence = l1_result.get("confidence", 0.5)
        l2_signal = l2_result.get("signal", "HOLD")
        l2_score = l2_result.get("score", 0)

        # Conflict detection
        if l1_trend == "UP" and l2_signal == "SELL" and l2_score < -20:
            return True
        if l1_trend == "DOWN" and l2_signal == "BUY" and l2_score > 20:
            return True

        # Low confidence
        if l1_confidence < 0.5 and l2_signal != "HOLD":
            return True

        # Unclear regime
        if l1_result.get("regime") == "RANGING" and abs(l2_score) > 30:
            return True

        return False

    def analyze_trend(
        self,
        symbol: str,
        l1_result: Dict,
        l2_result: Dict,
        bars: List[Dict]
    ) -> Dict:
        """
        DeepSeek trend analysis and arbitration

        Returns:
            {
                "ai_trend": "UP" | "DOWN" | "SIDE",
                "ai_signal": "BUY" | "SELL" | "HOLD",
                "ai_confidence": float,
                "ai_reason": str,
                "arbitration_type": str
            }
        """
        if not self.enabled:
            return self._disabled_result()

        try:
            # Prepare data
            recent_bars = bars[-20:] if len(bars) >= 20 else bars
            price_data = self._format_price_data(recent_bars)

            # Build prompt
            prompt = self._build_arbitration_prompt(
                symbol, l1_result, l2_result, price_data
            )

            # Call API
            response = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=400,
                timeout=self.timeout
            )

            raw_response = response.choices[0].message.content
            result = self._parse_response(raw_response)

            logger.info(f"DeepSeek arbitration {symbol}: {result.get('ai_signal')} "
                       f"(conf={result.get('ai_confidence')})")

            return result

        except Exception as e:
            logger.error(f"DeepSeek analysis failed: {e}")
            return self._error_result(str(e))

    def _get_system_prompt(self) -> str:
        """System prompt for DeepSeek"""
        return """You are an expert quantitative trading analyst specializing in technical analysis and trend identification.

Your task is to arbitrate between conflicting signals from L1 (trend) and L2 (execution) analysis modules.

Rules:
1. Prioritize trend direction over short-term signals
2. In ranging markets, favor mean reversion
3. High volume signals are more reliable
4. Dow Theory confirmation strengthens the signal
5. Be conservative when signals conflict

Always respond in JSON format only."""

    def _build_arbitration_prompt(
        self,
        symbol: str,
        l1_result: Dict,
        l2_result: Dict,
        price_data: List[Dict]
    ) -> str:
        """Build arbitration prompt (token-efficient)"""

        # Extract key data
        l1_trend = l1_result.get("trend", "UNKNOWN")
        l1_strength = l1_result.get("strength", "UNKNOWN")
        l1_regime = l1_result.get("regime", "UNKNOWN")
        l1_adx = l1_result.get("adx", 0)
        l1_dow = l1_result.get("dow_trend", "UNKNOWN")
        l1_conf = l1_result.get("confidence", 0.5)

        l2_signal = l2_result.get("signal", "HOLD")
        l2_score = l2_result.get("score", 0)
        l2_rsi = l2_result.get("rsi", 50)
        l2_vol = l2_result.get("volume_ratio", 1)
        l2_divergence = l2_result.get("divergence", "NONE")
        l2_patterns = l2_result.get("patterns", [])
        l2_quality = l2_result.get("quality_score", 3)

        # Conflict type
        conflict = "NONE"
        if l1_trend == "UP" and l2_signal == "SELL":
            conflict = "TREND_VS_SIGNAL"
        elif l1_trend == "DOWN" and l2_signal == "BUY":
            conflict = "TREND_VS_SIGNAL"
        elif l1_regime == "RANGING":
            conflict = "UNCLEAR_REGIME"

        prompt = f"""## Arbitration Request: {symbol}

### L1 Trend Analysis
- Trend: {l1_trend} (Strength: {l1_strength})
- Regime: {l1_regime}
- ADX: {l1_adx:.1f}
- Dow Theory: {l1_dow}
- Confidence: {l1_conf:.2f}

### L2 Signal Analysis
- Signal: {l2_signal} (Score: {l2_score:.1f})
- RSI: {l2_rsi:.1f}
- Volume Ratio: {l2_vol:.2f}x
- Divergence: {l2_divergence}
- Patterns: {', '.join(l2_patterns) if l2_patterns else 'None'}
- Quality Score: {l2_quality}/9

### Conflict Type: {conflict}

### Recent Price Action (Last 5 bars)
{self._format_recent_bars(price_data[-5:])}

### Task
Analyze the conflict and provide your arbitration. Respond in JSON:
{{
    "trend": "UP" or "DOWN" or "SIDE",
    "signal": "BUY" or "SELL" or "HOLD",
    "confidence": 0.0-1.0,
    "reason": "Brief explanation (max 50 chars)"
}}"""

        return prompt

    def _format_price_data(self, bars: List[Dict]) -> List[Dict]:
        """Format price data for prompt"""
        formatted = []
        for b in bars:
            ts = b.get("timestamp", "")
            if hasattr(ts, "strftime"):
                ts = ts.strftime("%m-%d %H:%M")
            formatted.append({
                "t": str(ts)[-11:],  # Truncate
                "o": round(float(b["open"]), 2),
                "h": round(float(b["high"]), 2),
                "l": round(float(b["low"]), 2),
                "c": round(float(b["close"]), 2),
            })
        return formatted

    def _format_recent_bars(self, bars: List[Dict]) -> str:
        """Format recent bars as compact string"""
        lines = []
        for b in bars:
            change = ((b["c"] - b["o"]) / b["o"] * 100) if b["o"] != 0 else 0
            direction = "+" if change >= 0 else ""
            lines.append(f"{b['t']}: {b['o']}->{b['c']} ({direction}{change:.1f}%)")
        return "\n".join(lines)

    def _parse_response(self, response: str) -> Dict:
        """Parse DeepSeek response"""
        result = {
            "ai_trend": "SIDE",
            "ai_signal": "HOLD",
            "ai_confidence": 0.5,
            "ai_reason": "",
            "arbitration_type": "DEEPSEEK",
            "raw_response": response
        }

        try:
            # Clean JSON
            text = response.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            data = json.loads(text.strip())

            result["ai_trend"] = data.get("trend", "SIDE").upper()
            result["ai_signal"] = data.get("signal", "HOLD").upper()
            result["ai_confidence"] = float(data.get("confidence", 0.5))
            result["ai_reason"] = data.get("reason", "")[:100]

            # Validate
            if result["ai_trend"] not in ["UP", "DOWN", "SIDE"]:
                result["ai_trend"] = "SIDE"
            if result["ai_signal"] not in ["BUY", "SELL", "HOLD"]:
                result["ai_signal"] = "HOLD"
            result["ai_confidence"] = max(0.1, min(0.95, result["ai_confidence"]))

        except json.JSONDecodeError:
            logger.warning(f"DeepSeek response parse failed: {response[:100]}")
            result["ai_reason"] = "Parse error"

        return result

    def arbitrate(
        self,
        tech_signal: str,
        tech_confidence: float,
        ai_result: Dict
    ) -> Dict:
        """
        Final arbitration between Tech and AI signals

        Priority:
        1. Consensus -> Boost confidence
        2. AI higher confidence -> AI wins
        3. Tech higher confidence -> Tech wins
        4. Equal -> Conservative HOLD
        """
        ai_signal = ai_result.get("ai_signal")
        ai_confidence = ai_result.get("ai_confidence", 0)

        if not ai_signal or ai_signal == "HOLD":
            return {
                "final_signal": tech_signal,
                "final_confidence": tech_confidence,
                "source": "TECH_ONLY",
                "ai_used": False
            }

        # Consensus
        if tech_signal == ai_signal:
            boosted_conf = min((tech_confidence + ai_confidence) / 2 + 0.1, 0.95)
            return {
                "final_signal": tech_signal,
                "final_confidence": boosted_conf,
                "source": "CONSENSUS",
                "ai_used": True
            }

        # Conflict resolution
        conf_diff = ai_confidence - tech_confidence

        if conf_diff > 0.15:
            return {
                "final_signal": ai_signal,
                "final_confidence": ai_confidence * 0.9,
                "source": "AI_OVERRIDE",
                "ai_used": True
            }
        elif conf_diff < -0.15:
            return {
                "final_signal": tech_signal,
                "final_confidence": tech_confidence * 0.9,
                "source": "TECH_OVERRIDE",
                "ai_used": True
            }
        else:
            # Conservative
            return {
                "final_signal": "HOLD",
                "final_confidence": 0.5,
                "source": "CONFLICT_HOLD",
                "ai_used": True
            }

    def _disabled_result(self) -> Dict:
        return {
            "ai_trend": None,
            "ai_signal": None,
            "ai_confidence": 0,
            "ai_reason": "DeepSeek disabled",
            "arbitration_type": "DISABLED"
        }

    def _error_result(self, error: str) -> Dict:
        return {
            "ai_trend": None,
            "ai_signal": None,
            "ai_confidence": 0,
            "ai_reason": f"Error: {error[:50]}",
            "arbitration_type": "ERROR"
        }

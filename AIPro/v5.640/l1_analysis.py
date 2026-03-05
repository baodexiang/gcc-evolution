"""
L1 Trend Analysis Module
========================
Synced from v3.498 main program

Features:
- ADX/DI trend detection
- Dow Theory swing point analysis (v3.280)
- Weighted direction ratio (v3.240)
- Multi-timeframe support
- v3.430: FORCE_DOWN rule (drop >= 30% forces DOWN)
- v3.430: Dynamic ADX threshold (price change >= 5% lowers threshold)
- v3.430: Strong stock protection (high position + small pullback)
- v3.435: FORCE_DOWN_MID (drop >= 30% forces dow_trend to DOWN)
- v3.435: FORCE_UP_MID (rise >= 50% forces dow_trend to UP)
- v3.435: PRICE_OVERRIDE (30-bar change >= 5% overrides dow_trend SIDE)
- v3.441: FORCE_DOWN恢复检测 (大跌后企稳→current_trend转RANGING)
- v3.442: 加密货币专用ADX阈值 (默认20, 低于美股的25)
- v5.440: MACD背驰检测 (来源: 缠论第11集)
- v5.480: L1 Wyckoff阶段定位 (trend_x4 + pos_in_channel → 5种阶段)
  - MARKUP (上涨期) / MARKDOWN (下跌期)
  - ACCUMULATION (吸筹期) / DISTRIBUTION (派发期) / RANGING (震荡期)
- v5.487: Wyckoff阶段确认机制 (防止跳变)
  - 连续2根K线确认才切换阶段
  - 使用 l2_analysis.get_confirmed_wyckoff_phase_v5487()
- v5.493: L1趋势判断修复
  - DOW-Swing参数标准化: n_swing=2, min_swings=2 (道氏理论标准)
  - side→整体趋势兜底: 整体涨跌>=5%时用整体方向判定
  - ADX>=40强制判定方向: 极强趋势不返回SIDE
- v5.493: 价格强制判断阈值优化
  - 加密货币: 5%触发强制判断 (原10%)
  - 美股: 8%触发强制判断 (原10%)
"""

import logging
from typing import List, Dict, Tuple
import numpy as np

from .l2_analysis import detect_macd_divergence

logger = logging.getLogger(__name__)


class L1Analyzer:
    """L1 Trend Analyzer - Big Picture Trend Detection"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.adx_period = self.config.get("adx_period", 14)
        self.adx_threshold = self.config.get("adx_threshold", 25)
        self.adx_strong = self.config.get("adx_strong_threshold", 30)
        self.swing_window = self.config.get("swing_point_window", 5)
        self.lookback = self.config.get("l1_lookback", 120)

        # v3.430: Dynamic ADX threshold config
        self.dynamic_adx_price_change = self.config.get("dynamic_adx_price_change_threshold", 5.0)
        self.dynamic_adx_low = self.config.get("dynamic_adx_low_threshold", 15)

        # v3.442: Crypto-specific ADX threshold (lower than stocks)
        self.crypto_adx_threshold = self.config.get("crypto_adx_threshold", 20)
        self.crypto_symbols = {"BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC"}

        # v3.430: FORCE_DOWN config
        self.force_down_lookback = self.config.get("force_down_lookback", 120)
        self.force_down_threshold = self.config.get("force_down_threshold", 30.0)

        # v3.430: Strong stock protection config
        self.strong_stock_high_pos = self.config.get("strong_stock_high_position", 0.85)
        self.strong_stock_max_pullback = self.config.get("strong_stock_max_pullback", 3.0)

    def analyze(self, bars: List[Dict], symbol: str = None) -> Dict:
        """
        Execute L1 trend analysis

        Args:
            bars: OHLCV bar data
            symbol: Trading symbol (v3.442: used for crypto-specific ADX threshold)

        Returns:
            {
                "trend": "UP" | "DOWN" | "SIDE",
                "strength": "STRONG" | "MODERATE" | "WEAK",
                "regime": "TRENDING" | "RANGING",
                "adx": float,
                "plus_di": float,
                "minus_di": float,
                "confidence": float,
                "dow_trend": str,
                "slope": float,
                "consensus": str,  # v3.430: AGREE, FORCE_DOWN, etc.
                "details": {...}
            }
        """
        if not bars or len(bars) < self.adx_period + 5:
            return self._default_result()

        try:
            highs = np.array([float(b["high"]) for b in bars])
            lows = np.array([float(b["low"]) for b in bars])
            closes = np.array([float(b["close"]) for b in bars])

            # v3.442: Calculate dynamic ADX threshold (crypto uses lower base)
            effective_adx_threshold = self._calculate_dynamic_adx_threshold(closes, symbol)

            # ADX/DI Calculation
            adx, plus_di, minus_di = self._calculate_adx(highs, lows, closes)

            # ADX-based trend (using dynamic threshold)
            adx_trend = self._determine_trend_adx(plus_di, minus_di, adx, effective_adx_threshold)

            # Dow Theory (Swing Points) - v3.280
            dow_trend = self._dow_theory_swing_points(highs, lows)

            # Slope calculation - v3.240
            slope = self._calculate_slope(closes)

            # Weighted direction ratio - v3.240
            weighted_dr = self._weighted_dir_ratio(closes)

            # Trend strength
            strength = self._determine_strength(adx)

            # Market regime (using dynamic threshold)
            regime = "TRENDING" if adx >= effective_adx_threshold else "RANGING"

            # Final trend reconciliation
            final_trend = self._reconcile_trends(adx_trend, dow_trend, slope, weighted_dr, adx)

            # v3.430: Apply strong stock protection
            final_trend, dow_trend, protected = self._apply_strong_stock_protection(
                final_trend, dow_trend, highs, lows, closes
            )

            # v3.435: Apply trend_mid force rules
            dow_trend, force_mid_info = self._apply_trend_mid_force_rules(
                dow_trend, highs, lows, closes
            )

            # Confidence calculation
            confidence = self._calculate_confidence(adx, plus_di, minus_di, dow_trend, final_trend)

            # v3.430: Check FORCE_DOWN rule
            consensus = "AGREE"
            force_down_info = self._check_force_down(highs, closes)
            if force_down_info["triggered"]:
                final_trend = "DOWN"
                consensus = "FORCE_DOWN"
                logger.info(f"[v3.430] FORCE_DOWN activated: drop {force_down_info['drop_pct']:.1f}% >= 30%")

            # v5.440: MACD Divergence Detection (Chan Theory: no divergence without trend)
            macd_divergence = {"has_divergence": False, "divergence_type": None, "strength": 0, "warning": None}
            try:
                if len(bars) >= 35:
                    macd_divergence = detect_macd_divergence(bars, final_trend)
                    if macd_divergence.get("has_divergence"):
                        logger.info(f"[v5.440] MACD divergence: {macd_divergence.get('divergence_type')} "
                                   f"({macd_divergence.get('strength')*100:.0f}%)")
            except Exception as e:
                logger.warning(f"[v5.440] MACD divergence detection error: {e}")

            return {
                "trend": final_trend,
                "strength": strength,
                "regime": regime,
                "adx": float(adx),
                "plus_di": float(plus_di),
                "minus_di": float(minus_di),
                "confidence": confidence,
                "dow_trend": dow_trend,
                "slope": float(slope),
                "weighted_dr": float(weighted_dr),
                "consensus": consensus,
                "macd_divergence": macd_divergence,  # v5.440
                "details": {
                    "adx_trend": adx_trend,
                    "di_diff": float(abs(plus_di - minus_di)),
                    "adx_threshold": effective_adx_threshold,
                    "adx_threshold_base": self.adx_threshold,
                    "dynamic_adx_applied": effective_adx_threshold != self.adx_threshold,
                    "force_down": force_down_info,
                    "strong_stock_protected": protected,
                    "force_mid": force_mid_info,  # v3.435
                }
            }

        except Exception as e:
            logger.error(f"L1 analysis error: {e}")
            return self._default_result()

    def _calculate_adx(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray
    ) -> Tuple[float, float, float]:
        """Calculate ADX and DI indicators"""
        period = self.adx_period
        n = len(highs)

        if n < period + 1:
            return 0.0, 0.0, 0.0

        # True Range
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )

        # +DM and -DM
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            if up_move > down_move and up_move > 0:
                plus_dm[i] = up_move
            if down_move > up_move and down_move > 0:
                minus_dm[i] = down_move

        # Wilder Smoothing
        atr = self._wilder_smooth(tr, period)
        smooth_plus_dm = self._wilder_smooth(plus_dm, period)
        smooth_minus_dm = self._wilder_smooth(minus_dm, period)

        # +DI and -DI
        plus_di = 100 * smooth_plus_dm / (atr + 1e-10)
        minus_di = 100 * smooth_minus_dm / (atr + 1e-10)

        # DX and ADX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = self._wilder_smooth(dx, period)

        return float(adx[-1]), float(plus_di[-1]), float(minus_di[-1])

    def _wilder_smooth(self, data: np.ndarray, period: int) -> np.ndarray:
        """Wilder smoothing"""
        result = np.zeros_like(data)
        if len(data) < period:
            return result
        result[period-1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = (result[i-1] * (period - 1) + data[i]) / period
        return result

    def _determine_trend_adx(self, plus_di: float, minus_di: float, adx: float,
                              threshold: float = None) -> str:
        """Determine trend from ADX/DI"""
        effective_threshold = threshold if threshold is not None else self.adx_threshold
        if adx < effective_threshold:
            return "SIDE"

        di_diff = plus_di - minus_di
        if di_diff > 5:
            return "UP"
        elif di_diff < -5:
            return "DOWN"
        return "SIDE"

    def _dow_theory_swing_points(self, highs: np.ndarray, lows: np.ndarray) -> str:
        """
        Dow Theory using Swing Points (v3.280, v3.493)

        Swing High: Local maximum (higher than neighbors)
        Swing Low: Local minimum (lower than neighbors)

        v3.493: n_swing=2, min_swings=2 (Dow Theory standard)
        - 2 peaks + 2 troughs is enough to confirm trend
        """
        if len(highs) < 20:
            return "UNKNOWN"

        swing_highs = []
        swing_lows = []
        window = self.swing_window

        for i in range(window, len(highs) - window):
            # Swing High
            if highs[i] == max(highs[i-window:i+window+1]):
                swing_highs.append((i, highs[i]))
            # Swing Low
            if lows[i] == min(lows[i-window:i+window+1]):
                swing_lows.append((i, lows[i]))

        # v3.493: n_swing=2, min_swings=2 (already correct)
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            # v3.493: Side fallback - check overall trend when swings insufficient
            if len(highs) >= 30:
                overall_change = (highs[-1] - lows[0]) / lows[0] * 100 if lows[0] > 0 else 0
                side_fallback = self.config.get("side_fallback_threshold", 5.0)
                if overall_change >= side_fallback:
                    return "UP"
                elif overall_change <= -side_fallback:
                    return "DOWN"
            return "UNKNOWN"

        # Recent 2 swing points
        last_highs = [h[1] for h in swing_highs[-2:]]
        last_lows = [l[1] for l in swing_lows[-2:]]

        # Higher highs + Higher lows = UP
        if last_highs[-1] > last_highs[-2] and last_lows[-1] > last_lows[-2]:
            return "UP"
        # Lower highs + Lower lows = DOWN
        elif last_highs[-1] < last_highs[-2] and last_lows[-1] < last_lows[-2]:
            return "DOWN"

        # v3.493: Side fallback - check overall trend when DOW returns SIDE
        if len(highs) >= 30:
            first_close = (highs[0] + lows[0]) / 2
            last_close = (highs[-1] + lows[-1]) / 2
            overall_change = (last_close - first_close) / first_close * 100 if first_close > 0 else 0
            side_fallback = self.config.get("side_fallback_threshold", 5.0)
            if overall_change >= side_fallback:
                return "UP"
            elif overall_change <= -side_fallback:
                return "DOWN"

        return "SIDE"

    def _calculate_slope(self, closes: np.ndarray, window: int = 20) -> float:
        """Calculate price slope (normalized)"""
        if len(closes) < window:
            return 0.0

        recent = closes[-window:]
        x = np.arange(window)
        slope = np.polyfit(x, recent, 1)[0]

        # Normalize by average price
        avg_price = np.mean(recent)
        if avg_price > 0:
            return slope / avg_price
        return 0.0

    def _weighted_dir_ratio(self, closes: np.ndarray, window: int = 20) -> float:
        """
        Weighted direction ratio (v3.240)

        Weight by magnitude of change, not just count
        """
        if len(closes) < window + 1:
            return 0.5

        recent = closes[-window-1:]
        changes = np.diff(recent)

        up_sum = np.sum(changes[changes > 0])
        down_sum = abs(np.sum(changes[changes < 0]))
        total = up_sum + down_sum

        if total == 0:
            return 0.5
        return up_sum / total

    def _reconcile_trends(
        self,
        adx_trend: str,
        dow_trend: str,
        slope: float,
        weighted_dr: float,
        adx: float
    ) -> str:
        """
        Reconcile multiple trend signals (v3.240, v3.280, v3.493)

        Priority:
        1. v3.493: ADX>=40 forces direction judgment (extreme trend)
        2. Strong ADX (>30) with clear direction
        3. Dow Theory confirmation
        4. Slope + weighted_dr fallback
        """
        # v3.493: ADX>=40 forces direction judgment, not SIDE
        if adx >= 40:
            # Even if adx_trend is SIDE, use slope to determine direction
            if adx_trend in ["UP", "DOWN"]:
                return adx_trend
            # ADX>=40 but DI unclear, use slope as tiebreaker
            if slope > 0:
                return "UP"
            elif slope < 0:
                return "DOWN"
            # Last resort: use weighted_dr
            if weighted_dr > 0.55:
                return "UP"
            elif weighted_dr < 0.45:
                return "DOWN"

        # Strong ADX trend takes priority
        if adx >= self.adx_strong and adx_trend != "SIDE":
            return adx_trend

        # ADX + Dow agreement
        if adx >= self.adx_threshold:
            if adx_trend == dow_trend and dow_trend != "UNKNOWN":
                return adx_trend
            if adx_trend != "SIDE":
                return adx_trend

        # Dow Theory standalone
        if dow_trend in ["UP", "DOWN"]:
            return dow_trend

        # Slope + weighted_dr fallback (v3.240)
        if abs(slope) > 0.003:  # >0.3% slope
            if slope > 0 and weighted_dr > 0.55:
                return "UP"
            elif slope < 0 and weighted_dr < 0.45:
                return "DOWN"

        return "SIDE"

    def _determine_strength(self, adx: float) -> str:
        """Determine trend strength"""
        if adx >= 40:
            return "STRONG"
        elif adx >= 25:
            return "MODERATE"
        return "WEAK"

    def _calculate_confidence(
        self,
        adx: float,
        plus_di: float,
        minus_di: float,
        dow_trend: str,
        final_trend: str
    ) -> float:
        """Calculate confidence score"""
        confidence = 0.3  # Base

        # ADX contribution (0-0.35)
        adx_score = min(adx / 100, 0.35)
        confidence += adx_score

        # DI separation (0-0.2)
        di_diff = abs(plus_di - minus_di)
        di_score = min(di_diff / 50, 0.2)
        confidence += di_score

        # Dow confirmation (0-0.15)
        if dow_trend == final_trend and dow_trend != "UNKNOWN":
            confidence += 0.15

        return round(min(confidence, 0.95), 2)

    def _default_result(self) -> Dict:
        """Default result"""
        return {
            "trend": "SIDE",
            "strength": "WEAK",
            "regime": "RANGING",
            "adx": 0.0,
            "plus_di": 0.0,
            "minus_di": 0.0,
            "confidence": 0.3,
            "dow_trend": "UNKNOWN",
            "slope": 0.0,
            "weighted_dr": 0.5,
            "consensus": "AGREE",
            "details": {}
        }

    # =========================================================================
    # v3.430 New Methods
    # =========================================================================

    def _calculate_dynamic_adx_threshold(self, closes: np.ndarray, symbol: str = None) -> float:
        """
        v3.430: Dynamic ADX threshold based on price change.
        v3.442: Crypto uses lower base threshold (20 vs 25 for stocks).

        If 30-bar price change >= 5%, lower ADX threshold to 15.
        Rationale: Strong price movement is itself a trend signal.
        """
        # v3.442: Crypto-specific base threshold
        is_crypto = symbol in self.crypto_symbols if symbol else False
        base_threshold = self.crypto_adx_threshold if is_crypto else self.adx_threshold

        if is_crypto:
            logger.debug(f"[v3.442] Crypto ADX: {symbol} using base threshold {base_threshold} (stocks use {self.adx_threshold})")

        if len(closes) < 30:
            return base_threshold

        try:
            first_close = closes[-30]
            last_close = closes[-1]

            if first_close > 0:
                price_change_pct = abs((last_close - first_close) / first_close * 100)

                if price_change_pct >= self.dynamic_adx_price_change:
                    logger.debug(f"[v3.430] Dynamic ADX: price change {price_change_pct:.1f}% >= {self.dynamic_adx_price_change}%, threshold {base_threshold} -> {self.dynamic_adx_low}")
                    return self.dynamic_adx_low

        except Exception:
            pass

        return base_threshold

    def _check_force_down(self, highs: np.ndarray, closes: np.ndarray) -> Dict:
        """
        v3.430: FORCE_DOWN rule - force DOWN when drop >= 30% from high.

        Fixes issue where stocks like COIN(-38%), OPEN(-40%) were judged UP.
        """
        result = {
            "triggered": False,
            "drop_pct": 0.0,
            "high_120": 0.0,
            "current_price": 0.0,
        }

        lookback = min(self.force_down_lookback, len(highs))
        if lookback < 20:
            return result

        try:
            highs_period = highs[-lookback:]
            high_120 = float(np.max(highs_period))
            current_price = float(closes[-1])

            result["high_120"] = high_120
            result["current_price"] = current_price

            if high_120 > 0:
                drop_pct = (high_120 - current_price) / high_120 * 100
                result["drop_pct"] = drop_pct

                if drop_pct >= self.force_down_threshold:
                    result["triggered"] = True

        except Exception:
            pass

        return result

    def _apply_strong_stock_protection(
        self,
        final_trend: str,
        dow_trend: str,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray
    ) -> Tuple[str, str, bool]:
        """
        v3.430: Strong stock protection - high position + small pullback.

        If big_trend=UP + dow_trend=down + position>85% + pullback<3%,
        protect dow_trend as SIDE to avoid false DOWN signal.
        """
        protected = False

        if final_trend != "UP" or dow_trend != "DOWN":
            return final_trend, dow_trend, protected

        if len(closes) < 30:
            return final_trend, dow_trend, protected

        try:
            recent_highs = highs[-30:]
            recent_lows = lows[-30:]
            high_30 = float(np.max(recent_highs))
            low_30 = float(np.min(recent_lows))
            current_price = float(closes[-1])

            if high_30 > low_30:
                # Calculate relative position (0-1)
                relative_pos = (current_price - low_30) / (high_30 - low_30)
                # Calculate pullback from high
                pullback_pct = (high_30 - current_price) / high_30 * 100

                # High position (>85%) + small pullback (<3%) -> protect
                if relative_pos > self.strong_stock_high_pos and pullback_pct < self.strong_stock_max_pullback:
                    dow_trend = "SIDE"  # Protect as SIDE, not DOWN
                    protected = True
                    logger.debug(f"[v3.430] Strong stock protection: pos {relative_pos*100:.0f}% > 85%, pullback {pullback_pct:.1f}% < 3%")

        except Exception:
            pass

        return final_trend, dow_trend, protected

    def _apply_trend_mid_force_rules(
        self,
        dow_trend: str,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray
    ) -> Tuple[str, Dict]:
        """
        v3.435: Apply force rules to trend_mid (dow_trend).
        v3.441: Add FORCE_DOWN recovery detection.

        Rules:
        - FORCE_DOWN_MID: Drop from 120-bar high >= 30% -> force DOWN
        - FORCE_UP_MID: Rise from 120-bar low >= 50% -> force UP
        - PRICE_OVERRIDE: 30-bar price change >= 5% -> override SIDE
        - v3.441 RECOVERY: After FORCE_DOWN, if recovery detected -> RANGING

        Returns:
            (dow_trend, info_dict)
        """
        info = {
            "force_down_mid": False,
            "force_up_mid": False,
            "price_override": False,
            "recovery_detected": False,  # v3.441
            "original_dow": dow_trend,
        }

        if len(closes) < 30:
            return dow_trend, info

        try:
            lookback = min(120, len(closes))
            high_120 = float(np.max(highs[-lookback:]))
            low_120 = float(np.min(lows[-lookback:]))
            current_price = float(closes[-1])

            # P0-1: FORCE_DOWN_MID - drop >= 30% forces DOWN
            if dow_trend != "DOWN" and high_120 > 0:
                drop_from_high = (high_120 - current_price) / high_120
                if drop_from_high >= 0.30:
                    # v3.441: Check recovery before forcing DOWN
                    recovery = self._check_force_down_recovery(lows, closes)
                    if recovery["detected"]:
                        dow_trend = "RANGING"  # Recovery -> RANGING, not DOWN
                        info["force_down_mid"] = True
                        info["recovery_detected"] = True
                        info["recovery_reason"] = recovery["reason"]
                        info["drop_from_high"] = drop_from_high
                        logger.info(f"[v3.441] FORCE_DOWN_RECOVERY: drop {drop_from_high*100:.1f}% but {recovery['reason']} -> RANGING")
                        return dow_trend, info
                    else:
                        dow_trend = "DOWN"
                        info["force_down_mid"] = True
                        info["drop_from_high"] = drop_from_high
                        logger.info(f"[v3.435] FORCE_DOWN_MID: drop {drop_from_high*100:.1f}% >= 30%")
                        return dow_trend, info

            # P0-2: FORCE_UP_MID - rise >= 50% forces UP
            if dow_trend != "UP" and low_120 > 0:
                rise_from_low = (current_price - low_120) / low_120
                if rise_from_low >= 0.50:
                    dow_trend = "UP"
                    info["force_up_mid"] = True
                    info["rise_from_low"] = rise_from_low
                    logger.info(f"[v3.435] FORCE_UP_MID: rise {rise_from_low*100:.1f}% >= 50%")
                    return dow_trend, info

            # P1: PRICE_OVERRIDE - 30-bar change >= 5% overrides SIDE
            if dow_trend == "SIDE" and len(closes) >= 30:
                first_close = float(closes[-30])
                last_close = float(closes[-1])

                if first_close > 0:
                    price_change = (last_close - first_close) / first_close

                    if price_change >= 0.05:
                        dow_trend = "UP"
                        info["price_override"] = True
                        info["price_change_30bar"] = price_change
                        logger.info(f"[v3.435] PRICE_OVERRIDE: 30-bar rise {price_change*100:.1f}% >= 5%")
                    elif price_change <= -0.05:
                        dow_trend = "DOWN"
                        info["price_override"] = True
                        info["price_change_30bar"] = price_change
                        logger.info(f"[v3.435] PRICE_OVERRIDE: 30-bar drop {abs(price_change)*100:.1f}% >= 5%")

        except Exception as e:
            logger.error(f"[v3.435] trend_mid force rules error: {e}")

        return dow_trend, info

    def _check_force_down_recovery(
        self,
        lows: np.ndarray,
        closes: np.ndarray
    ) -> Dict:
        """
        v3.441: Check if FORCE_DOWN condition shows recovery signs.

        Recovery conditions (any one triggers):
        1. Price rebounded >= 10% from recent low (30 bars)
        2. 3 consecutive rising closes

        Returns:
            {"detected": bool, "reason": str}
        """
        result = {"detected": False, "reason": ""}

        if len(closes) < 10:
            return result

        try:
            current_price = float(closes[-1])

            # Condition 1: Rebound >= 10% from 30-bar low
            lookback_30 = min(30, len(lows))
            low_30 = float(np.min(lows[-lookback_30:]))
            if low_30 > 0:
                rebound_pct = (current_price - low_30) / low_30
                if rebound_pct >= 0.10:
                    result["detected"] = True
                    result["reason"] = f"Rebound {rebound_pct*100:.1f}%>=10%"
                    return result

            # Condition 2: 3 consecutive rising closes
            if len(closes) >= 4:
                last_4 = closes[-4:]
                rising_count = sum(1 for i in range(1, len(last_4)) if last_4[i] > last_4[i-1])
                if rising_count >= 3:
                    result["detected"] = True
                    result["reason"] = "3 consecutive rising bars"
                    return result

        except Exception as e:
            logger.debug(f"[v3.441] Recovery check error: {e}")

        return result


# =========================================================================
# v5.480: L1 Wyckoff阶段定位 (来源: v3.485主程序)
# =========================================================================

def determine_wyckoff_phase(trend_x4: str, pos_in_channel: float) -> str:
    """
    v5.480: 纯L1大周期定位法 - 简洁可靠

    原始设计思想: L1大周期判断位置

    输入:
        trend_x4: x4周期道氏趋势 (up/down/side)
        pos_in_channel: Donchian位置 (0~1)

    输出: Wyckoff阶段
        MARKUP       - 上涨期 (趋势向上)
        MARKDOWN     - 下跌期 (趋势向下)
        ACCUMULATION - 吸筹期 (震荡+低位)
        DISTRIBUTION - 派发期 (震荡+高位)
        RANGING      - 震荡期 (震荡+中间位置)
    """
    x4 = (trend_x4 or "side").lower()
    pos = pos_in_channel if pos_in_channel is not None else 0.5

    if x4 == "up":
        return "MARKUP"           # 上涨期
    elif x4 == "down":
        return "MARKDOWN"         # 下跌期
    elif pos < 0.30:
        return "ACCUMULATION"     # 吸筹期 (低位震荡)
    elif pos > 0.70:
        return "DISTRIBUTION"     # 派发期 (高位震荡)
    else:
        return "RANGING"          # 震荡期 (中间位置)


def get_wyckoff_l2_strategy(wyckoff_phase: str) -> str:
    """
    v5.480: 根据Wyckoff阶段返回L2策略

    Returns:
        TREND_PULLBACK - 趋势策略 (顺大逆小)
        RANGE_REVERSAL - 震荡策略 (高抛低吸)
        NEUTRAL - 未知阶段
    """
    strategy_map = {
        "MARKUP": "TREND_PULLBACK",        # 上涨期 → 等回调买入
        "MARKDOWN": "TREND_PULLBACK",      # 下跌期 → 等反弹卖出
        "ACCUMULATION": "RANGE_REVERSAL",  # 吸筹期 → 低位积极买入
        "DISTRIBUTION": "RANGE_REVERSAL",  # 派发期 → 高位积极卖出
        "RANGING": "RANGE_REVERSAL",       # 震荡期 → 高抛低吸
    }
    return strategy_map.get(wyckoff_phase, "NEUTRAL")

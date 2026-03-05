"""
计算信号外挂 v1.0
==================
职责：纯数值计算产生交易信号（不依赖图像/AI模型）

属于「信号层」，与 N字外挂/缠论外挂 并行运行。
输出 PluginSignal（方向+信号类型+强度），由主程序合并后决定是否执行。

计算内容：
  1. EMA趋势确认（EMA8/21交叉）
  2. RSI超买超卖（动态阈值）
  3. MACD方向（零轴上下+背离简化版）

与 Vision 的职责区分：
  Vision 过滤层 → vision_pre_filter.py → 判断"位置对不对"（看图）
  计算信号外挂 → compute_signal_plugin.py → 判断"信号有没有"（算数值）
  两者在主程序里串联：先过滤，再看外挂信号。

用法：
    from compute_signal_plugin import ComputeSignalPlugin
    plugin = ComputeSignalPlugin("AMD")
    result = plugin.evaluate(closes, highs, lows, volumes)
    if result.action != "NONE":
        # 有信号，再走 vision_pre_filter 检查位置
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np


# ============================================================
# 输出结构
# ============================================================

@dataclass
class PluginSignal:
    source: str          # 信号来源，如 "compute_ema_cross"
    action: str          # "BUY" / "SELL" / "NONE"
    strength: float      # 0~1，信号强度
    reason: str          # 触发原因（1句话）
    entry: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    position_pct: float = 0.5  # 建议仓位比例


NONE_SIGNAL = PluginSignal(source="compute", action="NONE", strength=0.0, reason="无信号")


# ============================================================
# 计算工具
# ============================================================

def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    """指数移动平均"""
    alpha = 2.0 / (period + 1)
    result = np.zeros_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


def _rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI"""
    delta = np.diff(closes)
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    ag = np.convolve(gain, np.ones(period) / period, mode='valid')
    al = np.convolve(loss, np.ones(period) / period, mode='valid')
    rs = np.where(al > 0, ag / al, np.inf)
    return 100 - (100 / (1 + rs))


def _macd(closes: np.ndarray, fast=12, slow=26, signal=9):
    """MACD → (macd_line, signal_line, histogram)"""
    ema_fast   = _ema(closes, fast)
    ema_slow   = _ema(closes, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist       = macd_line - signal_line
    return macd_line, signal_line, hist


# ============================================================
# 主插件类
# ============================================================

class ComputeSignalPlugin:
    """
    纯数值计算信号外挂。

    检测三类信号，任一触发则产生 PluginSignal：
      1. EMA 交叉（EMA8/EMA21 金叉/死叉）
      2. RSI 超卖/超买确认反转（+价格结构辅助）
      3. MACD 方向突破（零轴穿越）
    """

    def __init__(self, symbol: str, atr_mult: float = 1.5):
        self.symbol   = symbol
        self.atr_mult = atr_mult  # 止损 ATR 倍数

    def evaluate(
        self,
        closes:  list,
        highs:   list,
        lows:    list,
        volumes: list,
    ) -> PluginSignal:
        """
        评估当前K线数据，返回 PluginSignal。
        closes/highs/lows/volumes 均为近期K线（建议60~120根）。
        """
        if len(closes) < 30:
            return NONE_SIGNAL

        c = np.array(closes, dtype=float)
        h = np.array(highs,  dtype=float)
        l = np.array(lows,   dtype=float)
        v = np.array(volumes, dtype=float)

        # ── 基础指标 ─────────────────────────────────────
        ema8   = _ema(c, 8)
        ema21  = _ema(c, 21)
        rsi14  = _rsi(c, 14)
        macd, sig_line, hist = _macd(c)
        atr    = self._atr(h, l, c)

        price  = float(c[-1])

        # ── 信号1: EMA 交叉 ──────────────────────────────
        ema_signal = self._check_ema_cross(ema8, ema21, price, atr)
        if ema_signal.action != "NONE":
            return ema_signal

        # ── 信号2: RSI 反转 ───────────────────────────────
        rsi_signal = self._check_rsi(rsi14, c, atr, price)
        if rsi_signal.action != "NONE":
            return rsi_signal

        # ── 信号3: MACD 零轴穿越 ─────────────────────────
        macd_signal = self._check_macd(macd, sig_line, price, atr)
        if macd_signal.action != "NONE":
            return macd_signal

        return NONE_SIGNAL

    # ── 内部检测逻辑 ─────────────────────────────────────

    def _check_ema_cross(self, ema8, ema21, price, atr) -> PluginSignal:
        """金叉/死叉检测（最近2根K线确认）"""
        if len(ema8) < 3:
            return NONE_SIGNAL

        prev_diff = ema8[-2] - ema21[-2]
        curr_diff = ema8[-1] - ema21[-1]

        if prev_diff < 0 and curr_diff > 0:  # 金叉
            return PluginSignal(
                source="compute_ema_cross",
                action="BUY",
                strength=min(abs(curr_diff) / (atr + 1e-9), 1.0),
                reason=f"EMA8金叉EMA21 @ {price:.2f}",
                entry=price,
                stop_loss=price - atr * self.atr_mult,
                target=price + atr * self.atr_mult * 2,
                position_pct=0.5,
            )

        if prev_diff > 0 and curr_diff < 0:  # 死叉
            return PluginSignal(
                source="compute_ema_cross",
                action="SELL",
                strength=min(abs(curr_diff) / (atr + 1e-9), 1.0),
                reason=f"EMA8死叉EMA21 @ {price:.2f}",
                entry=price,
                stop_loss=price + atr * self.atr_mult,
                target=price - atr * self.atr_mult * 2,
                position_pct=0.5,
            )

        return NONE_SIGNAL

    def _check_rsi(self, rsi_arr, closes, atr, price) -> PluginSignal:
        """RSI 超卖回升 / 超买回落"""
        if len(rsi_arr) < 3:
            return NONE_SIGNAL

        rsi_prev, rsi_curr = float(rsi_arr[-2]), float(rsi_arr[-1])
        oversold  = 30
        overbought = 70

        # 超卖回升：RSI从低于30回升
        if rsi_prev < oversold and rsi_curr > rsi_prev and closes[-1] > closes[-2]:
            return PluginSignal(
                source="compute_rsi",
                action="BUY",
                strength=(oversold - min(rsi_prev, oversold)) / oversold,
                reason=f"RSI超卖回升 {rsi_prev:.0f}→{rsi_curr:.0f}",
                entry=price,
                stop_loss=price - atr * self.atr_mult,
                target=price + atr * 2,
                position_pct=0.4,
            )

        # 超买回落：RSI从高于70回落
        if rsi_prev > overbought and rsi_curr < rsi_prev and closes[-1] < closes[-2]:
            return PluginSignal(
                source="compute_rsi",
                action="SELL",
                strength=(min(rsi_prev, 100) - overbought) / (100 - overbought),
                reason=f"RSI超买回落 {rsi_prev:.0f}→{rsi_curr:.0f}",
                entry=price,
                stop_loss=price + atr * self.atr_mult,
                target=price - atr * 2,
                position_pct=0.4,
            )

        return NONE_SIGNAL

    def _check_macd(self, macd, sig_line, price, atr) -> PluginSignal:
        """MACD 零轴上方金叉 / 零轴下方死叉"""
        if len(macd) < 3:
            return NONE_SIGNAL

        # MACD金叉（histogram从负转正，且在零轴附近）
        h_prev = macd[-2] - sig_line[-2]
        h_curr = macd[-1] - sig_line[-1]

        if h_prev < 0 and h_curr > 0 and abs(macd[-1]) < atr * 0.5:
            return PluginSignal(
                source="compute_macd",
                action="BUY",
                strength=min(abs(h_curr) / (atr + 1e-9), 1.0),
                reason=f"MACD金叉（零轴附近） macd={macd[-1]:.4f}",
                entry=price,
                stop_loss=price - atr * self.atr_mult,
                target=price + atr * 2,
                position_pct=0.4,
            )

        if h_prev > 0 and h_curr < 0 and abs(macd[-1]) < atr * 0.5:
            return PluginSignal(
                source="compute_macd",
                action="SELL",
                strength=min(abs(h_curr) / (atr + 1e-9), 1.0),
                reason=f"MACD死叉（零轴附近） macd={macd[-1]:.4f}",
                entry=price,
                stop_loss=price + atr * self.atr_mult,
                target=price - atr * 2,
                position_pct=0.4,
            )

        return NONE_SIGNAL

    @staticmethod
    def _atr(highs, lows, closes, period: int = 14) -> float:
        """ATR（平均真实波幅）"""
        if len(highs) < period + 1:
            return float(np.mean(highs - lows))
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:]  - closes[:-1]),
            )
        )
        return float(np.mean(tr[-period:]))


# ============================================================
# 快速测试
# ============================================================

if __name__ == "__main__":
    import yfinance as yf
    from datetime import datetime, timedelta

    for sym, yf_sym in [("AMD", "AMD"), ("BTCUSDC", "BTC-USD")]:
        df = yf.Ticker(yf_sym).history(
            start=(datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d"),
            end=datetime.now().strftime("%Y-%m-%d"),
            interval="1d"
        )
        if df.empty:
            continue

        plugin = ComputeSignalPlugin(sym)
        result = plugin.evaluate(
            closes=df["Close"].tolist(),
            highs=df["High"].tolist(),
            lows=df["Low"].tolist(),
            volumes=df["Volume"].tolist(),
        )
        icon = "⬆" if result.action == "BUY" else ("⬇" if result.action == "SELL" else "─")
        print(f"{icon} {sym:10s} {result.action:4s} [{result.source}] {result.reason}"
              + (f"  entry={result.entry:.2f} SL={result.stop_loss:.2f} TP={result.target:.2f}"
                 if result.action != "NONE" else ""))

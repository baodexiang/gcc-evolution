"""
order_flow/of_filter.py — 量价过滤模块 (GCC-0255 S1)
=====================================================
CVD背离 / OBI反向 / RVOL缩量 三规则拦截引擎。

独立运行，通过 state/filter_chain_state.json 与 gcc-tn 通信。
gcc-tn S09 _read_filter_chain() 自动读取 passed/volume_score 等字段。

Phase 0: passed=None（观察模式，不拦截）
Phase 1: passed=True/False（真实判断，观察拦截准确率）
Phase 2: passed=False 生效（gcc-tn filter 维度受影响）
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("of_filter")

# ══════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════
def _is_crypto(symbol: str) -> bool:
    """复用主程序逻辑判断加密货币（BTCUSDC / BTC-USD 均识别）。"""
    if not symbol:
        return True
    return (symbol.endswith("USDC") or symbol.endswith("USDT")
            or symbol.endswith("-USD"))

_STATE_DIR = Path("state")
_STATE_FILE = _STATE_DIR / "filter_chain_state.json"

# Phase 控制 — Phase 0 观察模式
_PHASE = 0  # 0=观察(passed=None), 1=判断(passed=True/False但不拦截), 2=生效


class OFFilter:
    """OF-Filter: CVD / OBI / RVOL 拦截引擎"""

    # ── 阈值 ──
    OBI_THRESHOLD = 0.30    # ±0.3 触发拦截
    RVOL_LOW = 0.50         # 突破场景下的缩量阈值
    CACHE_TTL_CRYPTO = 30   # 加密 TTL 秒
    CACHE_TTL_STOCK = 60    # 美股 TTL 秒

    def __init__(self):
        self._cache: dict = {}
        self._cache_ts: dict = {}

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════
    def run(self, symbol: str, direction: str,
            signal_type: str = "any") -> dict:
        """
        对 symbol+direction 执行 R1-R4 规则。

        Args:
            symbol: 品种代码 (BTCUSDC / TSLA 等)
            direction: "BUY" 或 "SELL"
            signal_type: "breakout" / "reversal" / "any"

        Returns:
            {"passed": bool/None, "blocked_by": str, "obi": float,
             "cvd_bias": str, "rvol": float, "volume_score": float,
             "micro_go": str, "updated_ts": str}
        """
        if direction not in ("BUY", "SELL"):
            return self._default_result()

        # 获取数据
        obi_cvd = self._get_obi_cvd(symbol)
        rvol = self._get_rvol(symbol)

        obi = obi_cvd.get("obi", 0.0)
        obi_bias = obi_cvd.get("obi_bias", "UNKNOWN")
        cvd_bias = obi_cvd.get("cvd_bias", "UNKNOWN")

        # 执行规则
        rule_passed, blocked_by = self._apply_rules(
            direction, obi, cvd_bias, rvol, signal_type
        )

        # micro_go 综合判断
        if obi_bias == "UNKNOWN" and cvd_bias == "UNKNOWN":
            micro_go = None
        elif rule_passed:
            micro_go = "GO"
        else:
            micro_go = "NO_GO"

        # volume_score 归一化
        volume_score = self._calc_volume_score(
            direction, obi, obi_bias, cvd_bias, rvol
        )

        # Phase 控制
        if _PHASE == 0:
            effective_passed = None  # 观察模式，不拦截
        else:
            effective_passed = rule_passed

        result = {
            "passed": effective_passed,
            "vision": None,            # 不覆盖 Vision 字段
            "volume_score": volume_score,
            "micro_go": micro_go,
            "blocked_by": blocked_by if not rule_passed else "",
            "obi": round(obi, 4),
            "cvd_bias": cvd_bias,
            "rvol": round(rvol, 4),
            "updated_ts": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }

        # 日志 — 无论 Phase 都记录真实判断
        if not rule_passed:
            logger.info(
                "[OF-FILTER] %s %s → BLOCKED by %s "
                "(obi=%.3f cvd=%s rvol=%.2f) Phase=%d%s",
                symbol, direction, blocked_by,
                obi, cvd_bias, rvol, _PHASE,
                " [观察模式]" if _PHASE == 0 else "",
            )
        else:
            logger.debug(
                "[OF-FILTER] %s %s → PASS (obi=%.3f cvd=%s rvol=%.2f)",
                symbol, direction, obi, cvd_bias, rvol,
            )

        # 写入 state
        self._write_state(symbol, direction, result)

        return result

    # ══════════════════════════════════════════════════════════
    # R1-R4 规则引擎
    # ══════════════════════════════════════════════════════════
    def _apply_rules(self, direction: str, obi: float,
                     cvd_bias: str, rvol: float,
                     signal_type: str) -> Tuple[bool, str]:
        """
        执行 R1-R4 规则。
        返回: (passed, blocked_by)
        """
        blocks = []

        # R1: CVD 方向背离拦截（最核心）
        if direction == "BUY" and cvd_bias == "SELL_DOMINANT":
            blocks.append("CVD_SELL_DOMINANT")
        elif direction == "SELL" and cvd_bias == "BUY_DOMINANT":
            blocks.append("CVD_BUY_DOMINANT")

        # R2: OBI 反向拦截
        if direction == "BUY" and obi < -self.OBI_THRESHOLD:
            blocks.append("OBI_SELL_PRESSURE")
        elif direction == "SELL" and obi > self.OBI_THRESHOLD:
            blocks.append("OBI_BUY_PRESSURE")

        # R3: RVOL 极度缩量拦截（仅突破类信号）
        if rvol < self.RVOL_LOW and signal_type == "breakout":
            blocks.append("RVOL_TOO_LOW_FOR_BREAKOUT")

        # R4: 多条触发取最严 — 逗号拼接
        if blocks:
            return False, ",".join(blocks)

        # 数据不足判断
        if cvd_bias == "UNKNOWN" and obi == 0.0:
            return True, ""  # 数据不足不拦截

        return True, ""

    # ══════════════════════════════════════════════════════════
    # volume_score 计算
    # ══════════════════════════════════════════════════════════
    def _calc_volume_score(self, direction: str, obi: float,
                           obi_bias: str, cvd_bias: str,
                           rvol: float) -> float:
        """
        归一化 volume_score [0, 1]。
        方向一致时量能质量高，方向相反时大幅压缩。
        """
        rvol_score = min(rvol / 2.0, 1.0)
        obi_strength = abs(obi) if obi != 0 else 0

        # 判断方向一致性
        direction_consistent = True
        if direction == "BUY":
            if cvd_bias == "SELL_DOMINANT" or obi_bias == "SELL_PRESSURE":
                direction_consistent = False
        elif direction == "SELL":
            if cvd_bias == "BUY_DOMINANT" or obi_bias == "BUY_PRESSURE":
                direction_consistent = False

        if direction_consistent:
            volume_score = rvol_score * 0.6 + obi_strength * 0.4
        else:
            volume_score = rvol_score * 0.2

        return round(max(0.0, min(1.0, volume_score)), 4)

    # ══════════════════════════════════════════════════════════
    # 数据获取 — 加密 / 美股 双路
    # ══════════════════════════════════════════════════════════
    def _get_obi_cvd(self, symbol: str) -> dict:
        """读取 OBI + CVD（区分加密/美股路径）。"""
        default = {"obi": 0.0, "obi_bias": "UNKNOWN",
                    "cvd": 0.0, "cvd_bias": "UNKNOWN"}

        cache_key = f"obi_cvd_{symbol}"
        ttl = (self.CACHE_TTL_CRYPTO if _is_crypto(symbol)
               else self.CACHE_TTL_STOCK)
        if (cache_key in self._cache
                and time.time() - self._cache_ts.get(cache_key, 0) < ttl):
            return self._cache[cache_key]

        if _is_crypto(symbol):
            result = self._get_coinbase_obi_cvd(symbol)
        else:
            result = self._get_schwab_obi_cvd(symbol)

        self._cache[cache_key] = result
        self._cache_ts[cache_key] = time.time()
        return result

    def _get_coinbase_obi_cvd(self, symbol: str) -> dict:
        """Coinbase: level2 OBI + market_trades CVD (真实 aggressor side)。"""
        try:
            from coinbase_data_provider import get_obi, get_cvd
            obi_data = get_obi(symbol)
            cvd_data = get_cvd(symbol)
            return {
                "obi": obi_data.get("obi", 0.0),
                "obi_bias": obi_data.get("obi_bias", "UNKNOWN"),
                "cvd": cvd_data.get("cvd", 0.0),
                "cvd_bias": cvd_data.get("cvd_bias", "UNKNOWN"),
            }
        except Exception as e:
            logger.debug("[OF-FILTER] Coinbase OBI/CVD %s: %s", symbol, e)
            return {"obi": 0.0, "obi_bias": "UNKNOWN",
                    "cvd": 0.0, "cvd_bias": "UNKNOWN"}

    def _get_schwab_obi_cvd(self, symbol: str) -> dict:
        """Schwab: bid_size/ask_size 伪OBI + Tick-Rule 伪CVD (~75%准确率)。"""
        try:
            from schwab_data_provider import SchwabDataProvider
            provider = SchwabDataProvider()
            quote = provider.get_quote(symbol)

            # 伪 OBI: bid/ask price 差异近似
            bid = float(quote.get("bid", 0))
            ask = float(quote.get("ask", 0))
            last = float(quote.get("last", 0))

            if bid > 0 and ask > 0 and last > 0:
                # 价格偏向 bid 侧 = 卖压, 偏向 ask 侧 = 买压
                mid = (bid + ask) / 2.0
                obi = (last - mid) / (ask - bid) if ask > bid else 0.0
                obi = max(-1.0, min(1.0, obi))
                if obi > 0.15:
                    obi_bias = "BUY_PRESSURE"
                elif obi < -0.15:
                    obi_bias = "SELL_PRESSURE"
                else:
                    obi_bias = "NEUTRAL"
            else:
                obi, obi_bias = 0.0, "UNKNOWN"

            # Tick-Rule 伪 CVD: 价格在 bid/ask 哪侧近似推导
            # Phase 0 简化: 用 VWAP bias 近似
            vwap_bias = quote.get("vwap_bias", "UNKNOWN")
            if vwap_bias == "ABOVE":
                cvd_bias = "BUY_DOMINANT"
            elif vwap_bias == "BELOW":
                cvd_bias = "SELL_DOMINANT"
            else:
                cvd_bias = "BALANCED"

            return {
                "obi": round(obi, 4), "obi_bias": obi_bias,
                "cvd": 0.0, "cvd_bias": cvd_bias,
            }
        except Exception as e:
            logger.debug("[OF-FILTER] Schwab OBI/CVD %s: %s", symbol, e)
            return {"obi": 0.0, "obi_bias": "UNKNOWN",
                    "cvd": 0.0, "cvd_bias": "UNKNOWN"}

    def _get_rvol(self, symbol: str) -> float:
        """计算 RVOL = current_4h_volume / avg_20bar_4h_volume。"""
        cache_key = f"rvol_{symbol}"
        ttl = (self.CACHE_TTL_CRYPTO if _is_crypto(symbol)
               else self.CACHE_TTL_STOCK)
        if (cache_key in self._cache
                and time.time() - self._cache_ts.get(cache_key, 0) < ttl):
            return self._cache[cache_key]

        rvol = self._calc_rvol(symbol)
        self._cache[cache_key] = rvol
        self._cache_ts[cache_key] = time.time()
        return rvol

    def _calc_rvol(self, symbol: str) -> float:
        """RVOL 实际计算。数据不足返回 1.0（默认均值）。"""
        try:
            if _is_crypto(symbol):
                return self._calc_rvol_coinbase(symbol)
            else:
                return self._calc_rvol_schwab(symbol)
        except Exception as e:
            logger.debug("[OF-FILTER] RVOL %s: %s", symbol, e)
            return 1.0

    def _calc_rvol_coinbase(self, symbol: str) -> float:
        """yfinance 4H OHLCV → RVOL（coinbase无candle API，复用主程序数据源）。"""
        try:
            from price_scan_engine_v21 import YFinanceDataFetcher
            df = YFinanceDataFetcher.get_ohlcv(symbol, 240, 21)
            if df is None or len(df) < 5:
                return 1.0
            vols = df["volume"].tolist()
            current = vols[-1]
            avg = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 1
            if avg <= 0:
                return 1.0
            return round(current / avg, 4)
        except Exception:
            return 1.0

    def _calc_rvol_schwab(self, symbol: str) -> float:
        """Schwab 5m K线 → 聚合4H → RVOL。"""
        try:
            from schwab_data_provider import SchwabDataProvider
            provider = SchwabDataProvider()
            df = provider.get_kline(symbol, interval="5m", bars=240)
            if df is None or df.empty or len(df) < 48:
                return 1.0
            # 每48根5m = 1根4H
            vols_4h = []
            for i in range(0, len(df) - 47, 48):
                chunk = df.iloc[i:i + 48]
                vols_4h.append(float(chunk["volume"].sum()))
            if len(vols_4h) < 2:
                return 1.0
            current = vols_4h[-1]
            avg = sum(vols_4h[:-1]) / len(vols_4h[:-1])
            if avg <= 0:
                return 1.0
            return round(current / avg, 4)
        except Exception:
            return 1.0

    # ══════════════════════════════════════════════════════════
    # 状态文件 I/O — 原子写入
    # ══════════════════════════════════════════════════════════
    def _write_state(self, symbol: str, direction: str,
                     result: dict) -> None:
        """原子写入 filter_chain_state.json（先 tmp 再 replace）。"""
        _STATE_DIR.mkdir(parents=True, exist_ok=True)

        # 读取现有
        existing = {}
        if _STATE_FILE.exists():
            try:
                existing = json.loads(
                    _STATE_FILE.read_text(encoding="utf-8")
                )
            except Exception:
                existing = {}

        # 只更新 OF-Filter 负责的字段，保留 vision 等
        if symbol not in existing:
            existing[symbol] = {}
        if direction not in existing[symbol]:
            existing[symbol][direction] = {}

        entry = existing[symbol][direction]
        # 保留 vision 字段（由 Vision 模块独立写入）
        for key in ("passed", "volume_score", "micro_go", "blocked_by",
                     "obi", "cvd_bias", "rvol", "updated_ts"):
            entry[key] = result.get(key)

        # 原子写入
        tmp_file = _STATE_FILE.with_suffix(".tmp.json")
        tmp_file.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(str(tmp_file), str(_STATE_FILE))

    # ══════════════════════════════════════════════════════════
    # 辅助
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def _default_result() -> dict:
        return {
            "passed": None, "vision": None, "volume_score": 0.5,
            "micro_go": None, "blocked_by": "", "obi": 0.0,
            "cvd_bias": "UNKNOWN", "rvol": 1.0,
            "updated_ts": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }


# ══════════════════════════════════════════════════════════════
# 便捷函数 — 供 llm_server / gcc_observe 调用
# ══════════════════════════════════════════════════════════════
_singleton: Optional[OFFilter] = None


def get_of_filter() -> OFFilter:
    """获取单例 OFFilter。"""
    global _singleton
    if _singleton is None:
        _singleton = OFFilter()
    return _singleton


def run_of_filter(symbol: str, direction: str,
                  signal_type: str = "any") -> dict:
    """快捷调用入口。"""
    return get_of_filter().run(symbol, direction, signal_type)


# ══════════════════════════════════════════════════════════════
# 独立运行测试
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s")
    of = OFFilter()
    # 测试加密
    for sym in ("BTCUSDC", "ETHUSDC"):
        for d in ("BUY", "SELL"):
            r = of.run(sym, d)
            print(f"{sym} {d}: passed={r['passed']} "
                  f"blocked={r['blocked_by']} "
                  f"vol_score={r['volume_score']:.3f} "
                  f"rvol={r['rvol']:.2f}")
    # 测试美股
    for sym in ("TSLA", "ONDS"):
        for d in ("BUY", "SELL"):
            r = of.run(sym, d)
            print(f"{sym} {d}: passed={r['passed']} "
                  f"blocked={r['blocked_by']} "
                  f"vol_score={r['volume_score']:.3f} "
                  f"rvol={r['rvol']:.2f}")

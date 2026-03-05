#!/usr/bin/env python3
"""
Signal Gate Worker — 本地预热脚本 (v1.0)
=========================================
在本地运行, 计算微观结构过滤结果并写入 state/signal_gate_state.json.
远程服务器通过 OneDrive 同步读取该文件, 无需安装 OpenBB.

运行方式:
    python signal_gate_worker.py          # 运行一次
    python signal_gate_worker.py --loop   # 每4小时循环
"""

import json
import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SGWorker")

# 品种映射: 主程序符号 → yfinance/OpenBB符号
CRYPTO_SYMBOLS = {
    "BTCUSDC": "BTC-USD",
    "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD",
    "ZECUSDC": "ZEC-USD",
}

STOCK_SYMBOLS = [
    "TSLA", "COIN", "RDDT", "NBIS", "CRWV",
    "RKLB", "HIMS", "OPEN", "AMD", "ONDS", "PLTR",
]

STATE_PATH = os.path.join("state", "signal_gate_state.json")
REFRESH_INTERVAL = 4 * 3600  # 4小时


def run_once():
    """计算所有品种的 signal gate 结果并写入 JSON"""
    from improvement.signal_gate import SignalGate

    gate_equity = SignalGate(provider="yfinance", fallback="yfinance",
                             lookback_days=30, cache_ttl=REFRESH_INTERVAL, asset_type="equity")
    gate_crypto = SignalGate(provider="yfinance", fallback="yfinance",
                             lookback_days=30, cache_ttl=REFRESH_INTERVAL, asset_type="crypto")

    result = {}
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 加密货币
    for main_sym, yf_sym in CRYPTO_SYMBOLS.items():
        log.info(f"Computing {main_sym} ({yf_sym}) crypto...")
        result[main_sym] = {}
        for direction in ("BUY", "SELL"):
            try:
                r = gate_crypto.check(yf_sym, direction.lower())
                result[main_sym][direction] = {
                    "go": r.go,
                    "regime": r.regime,
                    "vr": round(r.variance_ratio, 4) if r.variance_ratio == r.variance_ratio else None,
                    "flow": r.flow_direction,
                    "alignment": r.alignment,
                    "reason": r.reason,
                    "ts": ts_now,
                }
                log.info(f"  {main_sym} {direction}: go={r.go} regime={r.regime} vr={r.variance_ratio:.3f}")
            except Exception as e:
                log.warning(f"  {main_sym} {direction} 失败: {e}")
                result[main_sym][direction] = {"go": None, "regime": "error", "reason": str(e), "ts": ts_now}

    # 美股
    for sym in STOCK_SYMBOLS:
        log.info(f"Computing {sym} stock...")
        result[sym] = {}
        for direction in ("BUY", "SELL"):
            try:
                r = gate_equity.check(sym, direction.lower())
                result[sym][direction] = {
                    "go": r.go,
                    "regime": r.regime,
                    "vr": round(r.variance_ratio, 4) if r.variance_ratio == r.variance_ratio else None,
                    "flow": r.flow_direction,
                    "alignment": r.alignment,
                    "reason": r.reason,
                    "ts": ts_now,
                }
                log.info(f"  {sym} {direction}: go={r.go} regime={r.regime} vr={r.variance_ratio:.3f}")
            except Exception as e:
                log.warning(f"  {sym} {direction} 失败: {e}")
                result[sym][direction] = {"go": None, "regime": "error", "reason": str(e), "ts": ts_now}

    result["_meta"] = {
        "updated_at": ts_now,
        "version": "v3",
        "symbols": list(CRYPTO_SYMBOLS.keys()) + STOCK_SYMBOLS,
    }

    os.makedirs("state", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    log.info(f"已写入 {STATE_PATH} ({len(result)-1} 个品种)")


def main():
    ap = argparse.ArgumentParser(description="Signal Gate Worker v1.0")
    ap.add_argument("--loop", action="store_true", help="每4小时循环运行")
    args = ap.parse_args()

    if args.loop:
        log.info(f"循环模式: 每 {REFRESH_INTERVAL//3600} 小时刷新")
        while True:
            try:
                run_once()
            except Exception as e:
                log.error(f"run_once 失败: {e}", exc_info=True)
            log.info(f"下次刷新: {REFRESH_INTERVAL//3600} 小时后")
            time.sleep(REFRESH_INTERVAL)
    else:
        run_once()


if __name__ == "__main__":
    main()

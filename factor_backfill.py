#!/usr/bin/env python3
"""
factor_backfill.py — KEY-004 因子观测台 · Layer 2 (v1.0)
=========================================================
定时从 SQLite 读取未回填记录，通过 yfinance 拉取历史价格，
计算对数收益率并写回数据库。

回填字段:
  ret_1d    = ln(close_price_t+1  / close_price_t)
  ret_5d    = ln(close_price_t+5  / close_price_t)
  filled_at = 回填完成时间

运行方式:
    python factor_backfill.py          # 单次
    python factor_backfill.py --loop   # 每日循环
    python factor_backfill.py --status # 查看回填状态
"""

import argparse
import logging
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("FactorBackfill")

from factor_db import DB_PATH, _get_conn, _ensure_tables, _lock

LOOP_INTERVAL = 24 * 3600  # 每日一次

# 品种映射: 主程序符号 → yfinance 符号
SYM_MAP = {
    "BTCUSDC": "BTC-USD",
    "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD",
    "ZECUSDC": "ZEC-USD",
}

# yfinance 价格缓存 {yf_sym: DataFrame}
_price_cache: dict = {}
_cache_loaded: set = set()


def _yf_sym(symbol: str) -> str:
    return SYM_MAP.get(symbol, symbol)


def _load_price_history(symbol: str) -> "pd.DataFrame | None":
    """拉取最近60天1h OHLCV，带会话级缓存"""
    yf_sym = _yf_sym(symbol)
    if yf_sym in _cache_loaded:
        return _price_cache.get(yf_sym)
    try:
        import pandas as pd
        import yfinance as yf
        df = yf.download(yf_sym, period="60d", interval="1h",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            _cache_loaded.add(yf_sym)
            return None
        df.index = pd.to_datetime(df.index, utc=True)
        _price_cache[yf_sym] = df
        _cache_loaded.add(yf_sym)
        log.info(f"  已拉取 {yf_sym} 历史数据 {len(df)} 根K线")
        return df
    except Exception as e:
        log.warning(f"  拉取 {yf_sym} 失败: {e}")
        _cache_loaded.add(yf_sym)
        return None


def _price_at_offset(symbol: str, signal_ts: datetime, offset_days: int) -> "float | None":
    """返回 signal_ts + offset_days 处的收盘价（允许±4小时误差）"""
    df = _load_price_history(symbol)
    if df is None or df.empty:
        return None
    target = signal_ts + timedelta(days=offset_days)
    try:
        diff = abs(df.index - target)
        idx = diff.argmin()
        if diff[idx].total_seconds() > 4 * 3600:
            return None
        return float(df["Close"].iloc[idx])
    except Exception:
        return None


def _log_ret(base: float, target: float) -> "float | None":
    """对数收益率 ln(target/base)"""
    if not base or not target or base <= 0 or target <= 0:
        return None
    try:
        return math.log(target / base)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# 主逻辑
# ═══════════════════════════════════════════════════════════════

def run_once():
    _ensure_tables()
    _price_cache.clear()
    _cache_loaded.clear()

    # 读取所有待回填记录
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT id, symbol, close_price, ts
               FROM factor_signals
               WHERE ret_1d IS NULL AND close_price IS NOT NULL
               ORDER BY ts ASC"""
        ).fetchall()
        conn.close()

    if not rows:
        log.info("无待回填记录，退出")
        return

    log.info(f"待回填记录: {len(rows)} 条")
    now_utc = datetime.now(timezone.utc)
    updated = 0

    for row_id, symbol, close_price, ts_str in rows:
        try:
            signal_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue

        age_days = (now_utc - signal_ts).total_seconds() / 86400

        ret_1d, ret_5d = None, None

        # 回填 1d (需至少过了1天)
        if age_days >= 1.0:
            p1d = _price_at_offset(symbol, signal_ts, 1)
            ret_1d = _log_ret(close_price, p1d)

        # 回填 5d (需至少过了5天)
        if age_days >= 5.0:
            p5d = _price_at_offset(symbol, signal_ts, 5)
            ret_5d = _log_ret(close_price, p5d)

        # 只要有任一回填就更新
        if ret_1d is not None or ret_5d is not None:
            filled_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            with _lock:
                conn = _get_conn()
                conn.execute(
                    """UPDATE factor_signals
                       SET ret_1d=?, ret_5d=?, filled_at=?
                       WHERE id=?""",
                    (ret_1d, ret_5d, filled_at, row_id)
                )
                conn.commit()
                conn.close()
            updated += 1

    log.info(f"本轮回填完成: {updated}/{len(rows)} 条")


def show_status():
    """打印回填状态摘要"""
    _ensure_tables()
    with _lock:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM factor_signals").fetchone()[0]
        filled = conn.execute(
            "SELECT COUNT(*) FROM factor_signals WHERE ret_1d IS NOT NULL"
        ).fetchone()[0]
        by_factor = conn.execute(
            """SELECT factor_name, COUNT(*), SUM(ret_1d IS NOT NULL)
               FROM factor_signals GROUP BY factor_name"""
        ).fetchall()
        conn.close()

    log.info(f"=== 因子观测台 回填状态 ===")
    log.info(f"总记录: {total} | 已回填(1d): {filled} | 待回填: {total-filled}")
    for factor, cnt, f_cnt in by_factor:
        log.info(f"  {factor:<20} 总={cnt:>5} 已回填={f_cnt or 0:>5}")


def main():
    ap = argparse.ArgumentParser(description="factor_backfill v1.0")
    ap.add_argument("--loop",   action="store_true", help="每日循环")
    ap.add_argument("--status", action="store_true", help="查看状态")
    args = ap.parse_args()

    if args.status:
        show_status()
        return

    if args.loop:
        log.info(f"循环模式: 每 {LOOP_INTERVAL//3600} 小时刷新")
        while True:
            try:
                run_once()
            except Exception as e:
                log.error(f"run_once 失败: {e}", exc_info=True)
            time.sleep(LOOP_INTERVAL)
    else:
        run_once()


if __name__ == "__main__":
    main()

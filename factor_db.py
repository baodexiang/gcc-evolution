#!/usr/bin/env python3
"""
factor_db.py — KEY-004 因子观测台 · Layer 1 (v1.0)
====================================================
SQLite 数据库 + record_signal() 接口

设计原则:
  - 非阻塞: 目标 <5ms，不影响交易主流程
  - 线程安全: WAL 模式 + 连接池锁
  - Fail-silent: 所有调用处用 try/except 包裹，不能让 DB 错误影响信号
  - 零信号丢失: WAL + timeout=5 保证写入

数据库: state/factor_observatory.db

三张表:
  factor_signals   — 每次外挂信号原始记录 (Layer 1)
  factor_stats     — 因子统计快照 (Layer 3 写入)
  factor_evolution — LLM 进化记录 (Phase 2)

外挂接入最小改动:
    # 改动前
    signal = compute_chan_bi_signal(df)
    execute_trade(signal)

    # 改动后 (仅加一行)
    signal = compute_chan_bi_signal(df)
    from factor_db import record_signal
    record_signal('BTCUSDC', 'chan_bi', 1 if signal=='BUY' else -1)
    execute_trade(signal)
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone

# ── 路径 ─────────────────────────────────────────────────────
DB_PATH = os.path.join("state", "factor_observatory.db")

# ── 已接入的因子名称 (文档化) ──────────────────────────────
# P1: chan_bi, supertrend
# P2: rob_hoffman, double_pattern, supertrend_av2
# P3: scalping, feiyun

# ── 连接管理 ────────────────────────────────────────────────
_lock = threading.Lock()
_inited = False


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_tables():
    global _inited
    if _inited:
        return
    os.makedirs("state", exist_ok=True)
    with _lock:
        if _inited:
            return
        conn = _get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS factor_signals (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts             TEXT    NOT NULL,
                symbol         TEXT    NOT NULL,
                factor_name    TEXT    NOT NULL,
                factor_version TEXT    DEFAULT 'v1.0',
                signal         INTEGER NOT NULL,
                market_regime  TEXT,
                close_price    REAL,
                ret_1d         REAL,
                ret_5d         REAL,
                ret_custom     REAL,
                custom_days    INTEGER,
                filled_at      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fs_sym_factor
                ON factor_signals(symbol, factor_name, ts);

            CREATE TABLE IF NOT EXISTS factor_stats (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                calc_ts        TEXT NOT NULL,
                factor_name    TEXT NOT NULL,
                factor_version TEXT,
                period_days    INTEGER NOT NULL,
                market_regime  TEXT,
                n_samples      INTEGER,
                ic_mean        REAL,
                ic_std         REAL,
                icir           REAL,
                win_rate       REAL,
                t_stat         REAL,
                p_value        REAL
            );

            CREATE TABLE IF NOT EXISTS factor_evolution (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                created_ts       TEXT NOT NULL,
                parent_factor    TEXT NOT NULL,
                parent_version   TEXT NOT NULL,
                evolution_type   TEXT NOT NULL,
                llm_proposal     TEXT,
                new_factor_code  TEXT,
                backtest_icir    REAL,
                backtest_winrate REAL,
                status           TEXT DEFAULT 'pending',
                approved_by      TEXT,
                approved_ts      TEXT
            );
        """)
        conn.commit()
        conn.close()
        _inited = True


# ═══════════════════════════════════════════════════════════════
# 公开接口
# ═══════════════════════════════════════════════════════════════

def record_signal(
    symbol: str,
    factor_name: str,
    signal: int,
    factor_version: str = "v1.0",
    market_regime: str = None,
    close_price: float = None,
    custom_days: int = None,
) -> int:
    """
    记录一次外挂信号。非阻塞目标 <5ms。

    Args:
        symbol:         品种代码 (如 BTCUSDC)
        factor_name:    因子名称 (如 chan_bi / supertrend / rob_hoffman)
        signal:         +1=BUY, -1=SELL, 0=HOLD
        factor_version: 因子版本 (默认 v1.0)
        market_regime:  市场状态 (来自 detect_dc_regime 或 CNN)
        close_price:    当前收盘价 (用于计算未来收益)
        custom_days:    自定义回填天数

    Returns:
        inserted row id (失败时返回 -1)
    """
    try:
        _ensure_tables()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with _lock:
            conn = _get_conn()
            cur = conn.execute(
                """INSERT INTO factor_signals
                   (ts, symbol, factor_name, factor_version, signal,
                    market_regime, close_price, custom_days)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ts, symbol, factor_name, factor_version,
                 int(signal), market_regime, close_price, custom_days)
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
    except Exception:
        return -1


def get_signal_count(factor_name: str = None) -> int:
    """查询已记录信号数（验证用）"""
    try:
        _ensure_tables()
        with _lock:
            conn = _get_conn()
            if factor_name:
                n = conn.execute(
                    "SELECT COUNT(*) FROM factor_signals WHERE factor_name=?",
                    (factor_name,)
                ).fetchone()[0]
            else:
                n = conn.execute(
                    "SELECT COUNT(*) FROM factor_signals"
                ).fetchone()[0]
            conn.close()
            return n
    except Exception:
        return -1


def get_unfilled_count() -> int:
    """查询待回填记录数（给 factor_backfill 用）"""
    try:
        _ensure_tables()
        with _lock:
            conn = _get_conn()
            n = conn.execute(
                "SELECT COUNT(*) FROM factor_signals WHERE ret_1d IS NULL"
            ).fetchone()[0]
            conn.close()
            return n
    except Exception:
        return -1


if __name__ == "__main__":
    # 快速自检
    print("factor_db 自检...")
    rid = record_signal("BTCUSDC", "test_factor", 1,
                        market_regime="trend_up", close_price=50000.0)
    print(f"  写入 row_id={rid}")
    n = get_signal_count()
    print(f"  总记录数={n}")
    uf = get_unfilled_count()
    print(f"  待回填={uf}")
    print("  OK" if rid > 0 else "  FAIL")

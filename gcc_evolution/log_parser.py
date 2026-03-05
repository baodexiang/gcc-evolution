"""
GCC Log Parser — 解析 server.log ACTION_LOG 导入 trade_events 表
"""
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_action_logs(log_path: Path, db_path: Path, limit: int = 0):
    """
    解析 server.log 里的 ACTION_LOG JSON 行，导入 trade_events 表。
    limit=0 表示全部导入。
    """
    log_path = Path(log_path)
    db_path = Path(db_path)

    if not log_path.exists():
        raise FileNotFoundError(f"日志文件不存在: {log_path}")

    conn = sqlite3.connect(db_path)
    _ensure_table(conn)

    inserted = 0
    skipped = 0
    errors = 0

    with open(log_path, encoding='utf-8', errors='ignore') as f:
        for line in f:
            if 'ACTION_LOG:' not in line:
                continue

            # 提取 JSON 部分
            m = re.search(r'ACTION_LOG:\s*(\{.+\})', line)
            if not m:
                continue

            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                errors += 1
                continue

            symbol = data.get('symbol', '')
            timestamp_ms = data.get('timestamp', 0)
            if not symbol or not timestamp_ms:
                skipped += 1
                continue

            # 转换时间戳
            try:
                dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                event_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                event_date = dt.strftime('%Y-%m-%d')
            except (ValueError, TypeError) as e:
                logger.warning("[LOG_PARSER] Failed to parse timestamp %s: %s", timestamp_ms, e)
                skipped += 1
                continue

            row = {
                'symbol': symbol,
                'event_time': event_time,
                'event_date': event_date,
                'timeframe': data.get('timeframe', ''),
                'version': data.get('version', ''),
                'trade_mode': data.get('trade_mode', ''),
                'llm_raw_action': data.get('llm_raw_action', ''),
                'ai_action': data.get('ai_action', ''),
                'final_action': data.get('final_action', ''),
                'l1_action': data.get('l1_action_before_l2', ''),
                'l2_exec_bias': data.get('l2_exec_bias', ''),
                'l2_zone_tag': data.get('l2_zone_tag', ''),
                'signal_raw': data.get('signal_raw', ''),
                'signal_norm': data.get('signal_norm', ''),
                'level_str': data.get('level_str', ''),
                'last_close': data.get('last_close', 0),
                'wyckoff_phase': data.get('wyckoff_phase', ''),
                'wyckoff_regime': data.get('wyckoff_meta_regime', ''),
                'wyckoff_age': data.get('wyckoff_phase_age_bars', 0),
                'pos_zone': data.get('pos_zone', ''),
                'pos_ratio': data.get('pos_ratio', 0),
                'n_gate_result': data.get('n_gate_result', ''),
                'n_gate_reason': data.get('n_gate_reason', ''),
                'cycle_pnl': data.get('cycle_realized_pnl', 0),
                'raw_json': m.group(1),
            }

            try:
                _insert_row(conn, row)
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1  # 重复

            if limit and inserted >= limit:
                break

    conn.commit()
    conn.close()

    return {'inserted': inserted, 'skipped': skipped, 'errors': errors}


def _ensure_table(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trade_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            event_date TEXT NOT NULL,
            timeframe TEXT,
            version TEXT,
            trade_mode TEXT,
            llm_raw_action TEXT,
            ai_action TEXT,
            final_action TEXT,
            l1_action TEXT,
            l2_exec_bias TEXT,
            l2_zone_tag TEXT,
            signal_raw TEXT,
            signal_norm TEXT,
            level_str TEXT,
            last_close REAL,
            wyckoff_phase TEXT,
            wyckoff_regime TEXT,
            wyckoff_age INTEGER,
            pos_zone TEXT,
            pos_ratio REAL,
            n_gate_result TEXT,
            n_gate_reason TEXT,
            cycle_pnl REAL,
            raw_json TEXT,
            UNIQUE(symbol, event_time, timeframe)
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_te_symbol ON trade_events(symbol)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_te_date ON trade_events(event_date)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_te_action ON trade_events(final_action)')
    conn.commit()


def _insert_row(conn, row):
    conn.execute('''
        INSERT OR IGNORE INTO trade_events
        (symbol, event_time, event_date, timeframe, version, trade_mode,
         llm_raw_action, ai_action, final_action, l1_action, l2_exec_bias,
         l2_zone_tag, signal_raw, signal_norm, level_str, last_close,
         wyckoff_phase, wyckoff_regime, wyckoff_age, pos_zone, pos_ratio,
         n_gate_result, n_gate_reason, cycle_pnl, raw_json)
        VALUES
        (:symbol, :event_time, :event_date, :timeframe, :version, :trade_mode,
         :llm_raw_action, :ai_action, :final_action, :l1_action, :l2_exec_bias,
         :l2_zone_tag, :signal_raw, :signal_norm, :level_str, :last_close,
         :wyckoff_phase, :wyckoff_regime, :wyckoff_age, :pos_zone, :pos_ratio,
         :n_gate_result, :n_gate_reason, :cycle_pnl, :raw_json)
    ''', row)


def query_summary(db_path: Path):
    """按品种汇总 trade_events"""
    conn = sqlite3.connect(db_path)
    rows = conn.execute('''
        SELECT
            symbol,
            COUNT(*) as total,
            SUM(CASE WHEN final_action='BUY' THEN 1 ELSE 0 END) as buys,
            SUM(CASE WHEN final_action='SELL' THEN 1 ELSE 0 END) as sells,
            SUM(CASE WHEN final_action='HOLD' THEN 1 ELSE 0 END) as holds,
            SUM(CASE WHEN n_gate_result='BLOCK' THEN 1 ELSE 0 END) as blocked,
            ROUND(SUM(cycle_pnl), 4) as total_pnl,
            MIN(event_date) as first_date,
            MAX(event_date) as last_date
        FROM trade_events
        GROUP BY symbol
        ORDER BY total DESC
    ''').fetchall()
    conn.close()
    return rows

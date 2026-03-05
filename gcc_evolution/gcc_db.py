"""
GCC v4.9 — Unified Database Module
统一数据库：产品参数 + 知识卡片 + Handoff Session + 改善台账

设计原则：
- 老数据不动，数据库是读取视图，不是替代品
- yaml → products 表 (当前参数快照 + 历史变更)
- card_*.md → cards 表 (知识卡片)
- handoff.md → sessions 表 (session历史)
- improvements.json → improvements 表 (KEY台账)
- 回溯默认120天，支持更多

存储位置: .gcc/gcc.db

Usage:
    from gcc_evolution.gcc_db import GccDb
    db = GccDb()
    db.import_yaml("AMD", "/path/to/AMD.yaml")
    db.import_improvements("/path/to/improvements.json")
    db.query_product("AMD")
    db.query_improvements(key="KEY-001")
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gcc_root() -> Path:
    """找到 .gcc 目录"""
    p = Path.cwd()
    for _ in range(10):
        if (p / ".gcc").exists():
            return p / ".gcc"
        if p.parent == p:
            break
        p = p.parent
    d = Path.cwd() / ".gcc"
    d.mkdir(exist_ok=True)
    return d


# ── Schema ─────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ══════════════════════════════════════════════════════════
-- 核心数据域（各自独立，通过关联表连接）
-- ══════════════════════════════════════════════════════════

-- 1. 改善台账（核心研究记录）
--    from: improvements.json
CREATE TABLE IF NOT EXISTS improvements (
    id                TEXT PRIMARY KEY,   -- KEY-001 / SYS-011
    parent_key        TEXT,               -- 父级KEY（子项时有值）
    title             TEXT,
    status            TEXT,               -- IN_PROGRESS/TESTING/FOUND/COMPLETED/CLOSED
    phase_text        TEXT,
    observations_json TEXT,
    note              TEXT,
    item_type         TEXT DEFAULT 'key', -- key/sub/res/sys/aud/deferred
    imported_at       TEXT
);

-- 2. 知识卡（研究沉淀，独立存储）
--    from: improvement/*.md / card_*.md
CREATE TABLE IF NOT EXISTS cards (
    id              TEXT PRIMARY KEY,   -- KEY-001 / card_001
    key_id          TEXT,               -- 关联改善点（可空，允许通用知识卡）
    title           TEXT,
    content_md      TEXT,
    phases_json     TEXT,
    why_text        TEXT,
    lessons_text    TEXT,
    verify_cmds     TEXT,
    card_type       TEXT DEFAULT 'knowledge',
    layer_priority  INTEGER DEFAULT 2,
    imported_at     TEXT,
    file_path       TEXT
);

-- 3. 产品参数（独立，不从属于任何改善点）
--    from: params/*.yaml
--    多个改善点可能共同影响同一产品参数
CREATE TABLE IF NOT EXISTS products (
    symbol          TEXT PRIMARY KEY,
    version         TEXT,
    last_updated    TEXT,
    market          TEXT DEFAULT 'US_STOCK',
    n_gate_json     TEXT,       -- n_gate 参数段
    entry_json      TEXT,       -- entry 参数段
    risk_json       TEXT,       -- risk 参数段
    timing_json     TEXT,       -- timing 参数段
    quantity_json   TEXT,       -- quantity 参数段
    extra_json      TEXT,       -- 其他参数段
    backtest_json   TEXT,       -- 最近回测结果
    imported_at     TEXT,
    yaml_path       TEXT
);

-- 3a. 产品参数变更历史（每次 yaml 更新自动 diff）
CREATE TABLE IF NOT EXISTS product_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    changed_at      TEXT NOT NULL,
    section         TEXT,       -- n_gate/entry/risk/timing/quantity
    field_key       TEXT,       -- 具体字段名
    old_value       TEXT,
    new_value       TEXT,
    source          TEXT,       -- manual/suggest/gcc-evo
    note            TEXT
);

-- 4. 外部知识输入（独立，审核后生成知识卡）
--    from: .gcc/knowledge_index.jsonl
CREATE TABLE IF NOT EXISTS knowledge_sources (
    source_id       TEXT PRIMARY KEY,
    source_type     TEXT,   -- paper/notes/url/doc
    title           TEXT,
    draft_status    TEXT DEFAULT 'draft',  -- draft/approved/rejected
    imported_at     TEXT,
    approved_at     TEXT,
    card_path       TEXT    -- 审核通过后写入的知识卡路径
);

-- 5. 任务台账（跨会话任务，独立存储）
--    from: .gcc/tasks.jsonl
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    title           TEXT,
    status          TEXT,   -- pending/running/paused/completed/failed
    priority        TEXT DEFAULT 'normal',
    progress        TEXT,   -- "2/4"
    current_step    TEXT,
    steps_json      TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    finished_at     TEXT,
    result_summary  TEXT
);

-- 6. 参数建议台账（分析产生，人类审核）
--    from: .gcc/suggestions.jsonl
CREATE TABLE IF NOT EXISTS suggestions (
    suggestion_id   TEXT PRIMARY KEY,
    source          TEXT,   -- retrospective/analyze/human
    description     TEXT,
    current_value   TEXT,
    suggested_value TEXT,
    evidence        TEXT,
    status          TEXT DEFAULT 'pending',
    priority        TEXT DEFAULT 'normal',
    created_at      TEXT,
    reviewed_at     TEXT,
    review_note     TEXT
);

-- 7. 回溯分析报告
--    from: .gcc/analysis/*.md
CREATE TABLE IF NOT EXISTS analysis_reports (
    report_id       TEXT PRIMARY KEY,
    period          TEXT,   -- 12h/24h/7d
    generated_at    TEXT,
    executed_total  INTEGER DEFAULT 0,
    executed_win_rate REAL DEFAULT 0,
    intercepted_total INTEGER DEFAULT 0,
    intercept_false_rate REAL DEFAULT 0,
    findings_json   TEXT,
    suggestions_generated INTEGER DEFAULT 0,
    report_path     TEXT
);

-- 8. 会话历史
--    from: handoff.md
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_num     INTEGER,
    session_date    TEXT,
    agent           TEXT,
    title           TEXT,
    summary_md      TEXT,
    commits_json    TEXT,
    key_anchor      TEXT,
    imported_at     TEXT
);

-- 9. Commit 记录
CREATE TABLE IF NOT EXISTS commits (
    hash            TEXT PRIMARY KEY,
    session_id      INTEGER,
    committed_at    TEXT,
    message         TEXT,
    key_id          TEXT,
    files_json      TEXT
);

-- 10. 交易信号事件
--     from: server.log ACTION_LOG
CREATE TABLE IF NOT EXISTS trade_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT,
    signal_raw      TEXT,
    ai_action       TEXT,
    final_action    TEXT,
    wyckoff_phase   TEXT,
    l2_zone_tag     TEXT,
    pos_zone        TEXT,
    pos_ratio       REAL,
    last_close      REAL,
    raw_json        TEXT
);

-- 11. 方向锚定历史
CREATE TABLE IF NOT EXISTS anchor_log (
    anchor_id       TEXT PRIMARY KEY,
    direction       TEXT,
    confidence      REAL,
    trigger_text    TEXT,
    constraints_json TEXT,
    created_at      TEXT,
    expires_after   TEXT,
    sessions_used   INTEGER DEFAULT 0
);

-- ══════════════════════════════════════════════════════════
-- 关联表（连接独立数据域）
-- ══════════════════════════════════════════════════════════

-- 改善点 → 知识卡（一对多，一个改善点有多张知识卡）
CREATE TABLE IF NOT EXISTS improvement_card_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    card_id     TEXT NOT NULL,
    linked_at   TEXT NOT NULL
);

-- 改善点 → 产品参数变更（多对多）
-- 记录：哪几个改善点共同导致了某产品某次参数变更
CREATE TABLE IF NOT EXISTS improvement_product_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,      -- KEY-001
    symbol      TEXT NOT NULL,      -- AMD
    history_id  INTEGER,            -- product_history.id（可空）
    section     TEXT,               -- n_gate/entry/risk
    field_key   TEXT,
    linked_at   TEXT NOT NULL,
    note        TEXT
);

-- 改善点 → 任务（一个改善点下可有多个任务）
CREATE TABLE IF NOT EXISTS improvement_task_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    linked_at   TEXT NOT NULL
);

-- 改善点 → 外部知识输入
CREATE TABLE IF NOT EXISTS improvement_knowledge_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    linked_at   TEXT NOT NULL
);

-- 改善点 → 参数建议
CREATE TABLE IF NOT EXISTS improvement_suggestion_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    suggestion_id TEXT NOT NULL,
    linked_at   TEXT NOT NULL
);

-- 改善点 → 回溯分析报告
CREATE TABLE IF NOT EXISTS improvement_analysis_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    report_id   TEXT NOT NULL,
    linked_at   TEXT NOT NULL
);

-- ══════════════════════════════════════════════════════════
-- 索引
-- ══════════════════════════════════════════════════════════

CREATE INDEX IF NOT EXISTS idx_improvements_status   ON improvements(status);
CREATE INDEX IF NOT EXISTS idx_improvements_parent   ON improvements(parent_key);
CREATE INDEX IF NOT EXISTS idx_cards_key             ON cards(key_id);
CREATE INDEX IF NOT EXISTS idx_products_symbol       ON products(symbol);
CREATE INDEX IF NOT EXISTS idx_product_history_sym   ON product_history(symbol);
CREATE INDEX IF NOT EXISTS idx_product_history_at    ON product_history(changed_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status          ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_suggestions_status    ON suggestions(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_status      ON knowledge_sources(draft_status);
CREATE INDEX IF NOT EXISTS idx_analysis_at           ON analysis_reports(generated_at);
CREATE INDEX IF NOT EXISTS idx_sessions_num          ON sessions(session_num);
CREATE INDEX IF NOT EXISTS idx_trade_events_symbol   ON trade_events(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_events_at       ON trade_events(event_time);
CREATE INDEX IF NOT EXISTS idx_anchor_at             ON anchor_log(created_at);
-- 关联表索引
CREATE INDEX IF NOT EXISTS idx_link_card_key         ON improvement_card_links(key_id);
CREATE INDEX IF NOT EXISTS idx_link_product_key      ON improvement_product_links(key_id);
CREATE INDEX IF NOT EXISTS idx_link_product_sym      ON improvement_product_links(symbol);
CREATE INDEX IF NOT EXISTS idx_link_task_key         ON improvement_task_links(key_id);
CREATE INDEX IF NOT EXISTS idx_link_know_key         ON improvement_knowledge_links(key_id);
CREATE INDEX IF NOT EXISTS idx_link_sug_key          ON improvement_suggestion_links(key_id);
CREATE INDEX IF NOT EXISTS idx_link_ana_key          ON improvement_analysis_links(key_id);
"""



# ── GccDb ──────────────────────────────────────────────────

class GccDb:
    """统一数据库接口。读取老数据，不修改老数据。"""

    def __init__(self, gcc_root: Path | None = None):
        self._root = gcc_root or _gcc_root()
        self._db_path = self._root / "gcc.db"
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self):
        conn = self._connect()
        conn.executescript(SCHEMA)
        conn.commit()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Import: YAML ──────────────────────────────────────

    def import_yaml(self, symbol: str, yaml_path: str | Path) -> bool:
        """导入产品yaml文件到 products 表"""
        p = Path(yaml_path)
        if not p.exists():
            return False

        if HAS_YAML:
            with open(p, encoding="utf-8") as f:
                data = _yaml.safe_load(f) or {}
        else:
            # 简单解析
            data = _parse_yaml_simple(p)

        if not data:
            return False

        conn = self._connect()

        # 检查是否已存在，记录变更
        existing = conn.execute(
            "SELECT * FROM products WHERE symbol=?", (symbol,)
        ).fetchone()

        def _j(v): return json.dumps(v, ensure_ascii=False) if v else None

        row = {
            "symbol": symbol,
            "version": str(data.get("version", "1.0")),
            "last_updated": str(data.get("last_updated", "")),
            "market": _detect_market(symbol),
            "n_gate_json": _j(data.get("n_gate")),
            "entry_json": _j(data.get("entry")),
            "risk_json": _j(data.get("risk")),
            "timing_json": _j(data.get("timing")),
            "quantity_json": _j(data.get("quantity")),
            "extra_json": _j({k: v for k, v in data.items()
                               if k not in ("symbol", "version", "last_updated",
                                            "n_gate", "entry", "risk", "timing",
                                            "quantity", "backtest")}),
            "backtest_json": _j(data.get("backtest")),
            "imported_at": _now(),
            "yaml_path": str(p),
        }

        conn.execute("""
            INSERT OR REPLACE INTO products
            (symbol, version, last_updated, market,
             n_gate_json, entry_json, risk_json, timing_json, quantity_json,
             extra_json, backtest_json, imported_at, yaml_path)
            VALUES
            (:symbol, :version, :last_updated, :market,
             :n_gate_json, :entry_json, :risk_json, :timing_json, :quantity_json,
             :extra_json, :backtest_json, :imported_at, :yaml_path)
        """, row)

        # 如果已存在，记录变更历史
        if existing:
            _record_yaml_diff(conn, symbol, existing, row)

        conn.commit()
        return True

    def import_yaml_dir(self, params_dir: str | Path) -> int:
        """批量导入目录下所有yaml文件"""
        d = Path(params_dir)
        if not d.exists():
            return 0
        count = 0
        for p in d.glob("*.yaml"):
            symbol = p.stem.upper()
            if self.import_yaml(symbol, p):
                count += 1
        return count

    # ── Import: improvements.json ─────────────────────────

    def import_improvements(self, json_path: str | Path) -> int:
        """导入 improvements.json 到 improvements 表"""
        p = Path(json_path)
        if not p.exists():
            return 0

        with open(p, encoding="utf-8") as f:
            data = json.load(f)

        conn = self._connect()
        count = 0
        now = _now()

        keys = data.get("keys", {})
        for key_id, key_data in keys.items():
            # 主KEY
            conn.execute("""
                INSERT OR REPLACE INTO improvements
                (id, parent_key, title, status, phase_text,
                 observations_json, note, item_type, imported_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                key_id, None,
                key_data.get("title", ""),
                key_data.get("status", ""),
                key_data.get("phase", ""),
                json.dumps(key_data.get("observations", []), ensure_ascii=False),
                "",
                "key", now
            ))
            count += 1

            # sub_items
            for sub in key_data.get("sub_items", []):
                item_type = _classify_item_type(sub["id"])
                conn.execute("""
                    INSERT OR REPLACE INTO improvements
                    (id, parent_key, title, status, phase_text,
                     observations_json, note, item_type, imported_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    sub["id"], key_id,
                    sub.get("title", ""),
                    sub.get("status", ""),
                    "",
                    "[]",
                    sub.get("note", ""),
                    item_type, now
                ))
                count += 1

        # deferred
        for item in data.get("deferred", []):
            conn.execute("""
                INSERT OR REPLACE INTO improvements
                (id, parent_key, title, status, item_type, imported_at)
                VALUES (?,?,?,?,?,?)
            """, (item["id"], None, item.get("title", ""),
                  "DEFERRED", "deferred", now))
            count += 1

        conn.commit()
        return count

    # ── Import: card_*.md / knowledge md ─────────────────

    def import_card_md(self, md_path: str | Path,
                       card_id: str | None = None,
                       key_id: str | None = None) -> bool:
        """导入单个知识卡片md文件"""
        p = Path(md_path)
        if not p.exists():
            return False

        content = p.read_text(encoding="utf-8", errors="replace")

        # 自动推断 card_id
        if not card_id:
            card_id = p.stem  # e.g. KEY-001_N字门控 → KEY-001_N字门控

        # 自动推断 key_id
        if not key_id:
            m = re.search(r'KEY-(\d+)', p.stem)
            if m:
                key_id = f"KEY-{m.group(1).zfill(3)}"

        # 提取结构化内容
        title = _extract_md_title(content)
        why_text = _extract_md_section(content, ["为什么做", "Why"])
        lessons_text = _extract_md_section(content, ["教训", "Lessons"])
        verify_cmds = _extract_md_section(content, ["验证方法", "验证", "Verification"])
        phases_json = _extract_phases_table(content)

        # 判断层级
        layer = 3 if key_id and key_id in ("KEY-001", "KEY-002") else 2

        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO cards
            (id, key_id, title, content_md, phases_json,
             why_text, lessons_text, verify_cmds,
             card_type, layer_priority, imported_at, file_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            card_id, key_id, title, content,
            phases_json, why_text, lessons_text, verify_cmds,
            "knowledge", layer, _now(), str(p)
        ))
        conn.commit()
        return True

    def import_cards_dir(self, cards_dir: str | Path) -> int:
        """批量导入目录下所有 .md 文件"""
        d = Path(cards_dir)
        if not d.exists():
            return 0
        count = 0
        for p in d.rglob("*.md"):
            if self.import_card_md(p):
                count += 1
        return count

    # ── Import: handoff.md ────────────────────────────────

    def import_handoff_md(self, handoff_path: str | Path) -> int:
        """解析 handoff.md，提取 session 历史"""
        p = Path(handoff_path)
        if not p.exists():
            return 0

        content = p.read_text(encoding="utf-8", errors="replace")
        sessions = _parse_handoff_sessions(content)

        conn = self._connect()
        count = 0
        now = _now()

        for s in sessions:
            conn.execute("""
                INSERT INTO sessions
                (session_num, session_date, agent, title,
                 summary_md, commits_json, key_anchor, imported_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                s.get("session_num"),
                s.get("date"),
                s.get("agent"),
                s.get("title"),
                s.get("summary"),
                json.dumps(s.get("commits", []), ensure_ascii=False),
                s.get("key_anchor"),
                now
            ))
            count += 1

            # 提取commits
            for commit in s.get("commits", []):
                if commit.get("hash"):
                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO commits
                            (hash, session_id, committed_at, message, key_id)
                            VALUES (?,last_insert_rowid(),?,?,?)
                        """, (
                            commit["hash"],
                            s.get("date"),
                            commit.get("message", ""),
                            s.get("key_anchor")
                        ))
                    except Exception as e:
                        logger.warning("[GCC_DB] insert session commit failed: %s", e)

        conn.commit()
        return count

    # ── Query ─────────────────────────────────────────────

    def query_product(self, symbol: str) -> dict | None:
        """查询产品参数"""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM products WHERE symbol=?", (symbol.upper(),)
        ).fetchone()
        if not row:
            return None
        return _row_to_dict(row)

    def query_all_products(self) -> list[dict]:
        """所有产品列表"""
        conn = self._connect()
        rows = conn.execute(
            "SELECT symbol, version, last_updated, market, imported_at FROM products ORDER BY symbol"
        ).fetchall()
        return [dict(r) for r in rows]

    def query_improvements(self,
                           key: str | None = None,
                           status: str | None = None,
                           item_type: str | None = None) -> list[dict]:
        """查询改善台账"""
        conn = self._connect()
        sql = "SELECT * FROM improvements WHERE 1=1"
        args = []
        if key:
            sql += " AND (id=? OR parent_key=?)"
            args += [key, key]
        if status:
            sql += " AND status=?"
            args.append(status)
        if item_type:
            sql += " AND item_type=?"
            args.append(item_type)
        sql += " ORDER BY id"
        rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def query_cards(self, key_id: str | None = None) -> list[dict]:
        """查询知识卡片"""
        conn = self._connect()
        if key_id:
            rows = conn.execute(
                "SELECT * FROM cards WHERE key_id=? ORDER BY id", (key_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, key_id, title, card_type, layer_priority, imported_at FROM cards ORDER BY key_id, id"
            ).fetchall()
        return [dict(r) for r in rows]

    def query_sessions(self, limit: int = 20) -> list[dict]:
        """查询最近session历史"""
        conn = self._connect()
        rows = conn.execute(
            "SELECT session_num, session_date, agent, title, key_anchor FROM sessions ORDER BY session_num DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def query_trade_events(self, symbol: str | None = None,
                           days: int = 120) -> list[dict]:
        """查询交易事件（默认120天）"""
        conn = self._connect()
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        if symbol:
            rows = conn.execute(
                "SELECT * FROM trade_events WHERE symbol=? AND event_time>=? ORDER BY event_time DESC",
                (symbol.upper(), cutoff)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_events WHERE event_time>=? ORDER BY event_time DESC",
                (cutoff,)
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """数据库统计信息"""
        conn = self._connect()
        return {
            "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "improvements": conn.execute("SELECT COUNT(*) FROM improvements").fetchone()[0],
            "cards": conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            "trade_events": conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0],
            "db_path": str(self._db_path),
        }


# ── 批量导入入口 ──────────────────────────────────────────

def auto_import(gcc_root: Path | None = None) -> dict:
    """
    自动扫描 .gcc/ 目录，导入所有已知数据。
    老数据不动，只是读取建立索引。
    """
    root = gcc_root or _gcc_root()
    db = GccDb(root)
    result = {
        "products": 0,
        "improvements": 0,
        "cards": 0,
        "sessions": 0,
    }

    # 产品yaml (两个可能位置)
    for params_dir in [root / "params", root.parent / ".GCC" / "params",
                       root.parent / "params"]:
        if params_dir.exists():
            result["products"] += db.import_yaml_dir(params_dir)

    # improvements.json
    for imp_path in [root.parent / "state" / "improvements.json",
                     root / "improvements.json"]:
        if imp_path.exists():
            result["improvements"] = db.import_improvements(imp_path)
            break

    # 知识卡片
    for cards_dir in [root.parent / "improvement",
                      root / "knowledge",
                      root / "cards"]:
        if cards_dir.exists():
            result["cards"] += db.import_cards_dir(cards_dir)

    # handoff
    for hf_path in [root / "handoff.md",
                    root.parent / ".GCC" / "handoff.md"]:
        if hf_path.exists():
            result["sessions"] = db.import_handoff_md(hf_path)
            break

    return result


# ── 辅助函数 ──────────────────────────────────────────────

def _detect_market(symbol: str) -> str:
    crypto_patterns = ["USDC", "USDT", "BTC", "ETH", "SOL", "ZEC", "XRP"]
    s = symbol.upper()
    if any(p in s for p in crypto_patterns):
        return "CRYPTO"
    return "US_STOCK"


def _classify_item_type(item_id: str) -> str:
    if item_id.startswith("RES-"):
        return "res"
    if item_id.startswith("SYS-"):
        return "sys"
    if item_id.startswith("AUD-"):
        return "aud"
    if re.match(r"KEY-\d+-", item_id):
        return "sub"
    return "sub"


def _record_yaml_diff(conn, symbol: str, old_row, new_row):
    """记录参数变更历史"""
    sections = ["n_gate_json", "entry_json", "risk_json", "timing_json", "quantity_json"]
    for sec in sections:
        old_val = dict(old_row).get(sec)
        new_val = new_row.get(sec)
        if old_val != new_val and new_val:
            conn.execute("""
                INSERT INTO product_history
                (symbol, changed_at, section, old_value, new_value, source)
                VALUES (?,?,?,?,?,?)
            """, (symbol, _now(), sec.replace("_json", ""),
                  old_val, new_val, "import"))


def _extract_md_title(content: str) -> str:
    m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_md_section(content: str, headings: list[str]) -> str:
    for h in headings:
        pattern = rf'##\s+{re.escape(h)}.*?\n(.*?)(?=\n##|\Z)'
        m = re.search(pattern, content, re.DOTALL)
        if m:
            return m.group(1).strip()
    return ""


def _extract_phases_table(content: str) -> str | None:
    """提取Phase状态表"""
    if "Phase" not in content:
        return None
    phases = []
    for line in content.split("\n"):
        if re.search(r'\|\s*\d+\s*\|', line) or re.search(r'Phase\s*\d', line):
            phases.append(line)
    return json.dumps(phases, ensure_ascii=False) if phases else None


def _parse_yaml_simple(path: Path) -> dict:
    """简单yaml解析（无pyyaml时的后备）"""
    result = {}
    current_section = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line_stripped = line.rstrip()
            if not line_stripped or line_stripped.startswith("#"):
                continue
            # 顶级key
            if not line.startswith(" ") and ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()
                if val:
                    # 简单值
                    if val.startswith('"') or val.startswith("'"):
                        val = val.strip('"\'')
                    result[key] = val
                    current_section = None
                else:
                    # 开始一个section
                    current_section = key
                    result[current_section] = {}
            elif current_section and line.startswith("  ") and ":" in line:
                key, _, val = line.strip().partition(":")
                val = val.strip()
                if val.startswith('"') or val.startswith("'"):
                    val = val.strip('"\'')
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        pass
                result[current_section][key.strip()] = val
    return result


def _parse_handoff_sessions(content: str) -> list[dict]:
    """从 handoff.md 解析 session 历史"""
    sessions = []

    # 匹配多种格式: 本轮交接/本轮工作/上一轮交接
    # 支持 2026-02-20 和 2/19 两种日期格式
    pattern = re.compile(
        r'##\s+(?:本轮交接|上一轮交接|本轮工作|上轮工作)\s*'
        r'\((\d{4}[-/]\d{1,2}[-/]\d{1,2})\s+Session\s+(\d+)\)'
        r'[^\n]*?[\u2014\u2013\-—]+\s*([^\n]+)\n'
        r'(.*?)(?=\n##\s+(?:本轮交接|上一轮交接|本轮工作|上轮工作)|\n##\s+Session History|\Z)',
        re.DOTALL
    )

    for m in pattern.finditer(content):
        date_str, session_num, agent_or_title, body = m.groups()

        # 提取agent（括号里可能是"agent — title"）
        agent = agent_or_title.strip()

        # 提取commits
        commits = []
        for cm in re.finditer(r'`([0-9a-f]{7,})`\s*[–—]\s*([^\n|]+)', body):
            commits.append({
                "hash": cm.group(1),
                "message": cm.group(2).strip()
            })
        # 也匹配表格格式
        for cm in re.finditer(r'\|\s*`([0-9a-f]{7,})`\s*\|\s*([^|\n]+)', body):
            commits.append({
                "hash": cm.group(1),
                "message": cm.group(2).strip()
            })

        # 提取KEY anchor
        key_anchor = None
        for km in re.finditer(r'KEY-(\d+)', body):
            key_anchor = f"KEY-{km.group(1).zfill(3)}"
            break

        sessions.append({
            "session_num": int(session_num),
            "date": date_str,
            "agent": agent,
            "title": agent,
            "summary": body.strip()[:2000],  # 截断避免太大
            "commits": commits[:20],
            "key_anchor": key_anchor,
        })

    return sessions


def _row_to_dict(row) -> dict:
    d = dict(row)
    # 解析JSON字段
    for k in list(d.keys()):
        if k.endswith("_json") and d[k]:
            try:
                d[k.replace("_json", "")] = json.loads(d[k])
            except Exception as e:
                logger.warning("[GCC_DB] parse JSON field %s failed: %s", k, e)
    return d


# ══════════════════════════════════════════════════════════════
# v4.89 — 目录对齐与全量同步
# ══════════════════════════════════════════════════════════════

# GCC 标准目录结构，每次版本更新后验证
EXPECTED_LAYOUT = {
    ".gcc/gcc.db":                "数据库主文件",
    ".gcc/tasks.jsonl":           "任务台账",
    ".gcc/suggestions.jsonl":     "参数建议",
    ".gcc/schedule.json":         "定时任务配置",
    ".gcc/state.json":            "系统状态",
    ".gcc/anchor_today.json":     "今日方向锚定",
    ".gcc/anchor_log.jsonl":      "锚定历史",
    ".gcc/knowledge_index.jsonl": "外部知识索引",
    ".gcc/knowledge_drafts/":     "待审核知识草稿",
    ".gcc/analysis/":             "回溯分析报告",
    ".gcc/snapshots/":            "状态快照",
    "improvement/":               "知识卡目录",
    "handoff.md":                 "交接文件",
}


def check_layout(project_root: Path | None = None) -> dict:
    """
    检查项目目录结构是否与当前版本对齐。
    每次 pip install 新版本后运行一次。

    返回：
      { "ok": [...], "missing": [...], "version": "4.89.0" }
    """
    root = project_root or Path.cwd()
    ok      = []
    missing = []

    for rel_path, desc in EXPECTED_LAYOUT.items():
        full = root / rel_path
        if full.exists():
            ok.append(rel_path)
        else:
            missing.append((rel_path, desc))

    return {
        "version":  "4.89.0",
        "root":     str(root),
        "ok":       ok,
        "missing":  missing,
        "aligned":  len(missing) == 0,
    }


def sync_all(gcc_root: Path | None = None) -> dict:
    """
    全量同步：把文件系统里的所有数据同步进数据库。
    每次版本更新后运行一次，确保数据库与实际目录对齐。

    同步顺序（依赖顺序）：
      1. improvements  ← 先建立改善点锚点
      2. cards         ← 知识卡关联到改善点
      3. products/yaml ← 产品参数独立入库
      4. tasks         ← 任务同步
      5. suggestions   ← 建议同步
      6. knowledge     ← 外部知识同步
      7. analysis      ← 分析报告同步
      8. handoff/sessions ← 会话历史
    """
    root    = gcc_root or _gcc_root()
    proj    = root.parent
    db      = GccDb(root)
    conn    = db._connect()
    results = {
        "improvements": 0, "cards": 0, "products": 0,
        "tasks": 0, "suggestions": 0, "knowledge": 0,
        "analysis": 0, "sessions": 0, "errors": [],
    }

    # ── 1. improvements ───────────────────────────────────
    for f in ["state/improvements.json", "improvements.json", ".gcc/improvements.json"]:
        p = proj / f
        if p.exists():
            try:
                n = db.import_improvements(p)
                results["improvements"] = n
            except Exception as e:
                results["errors"].append(f"improvements: {e}")
            break

    # ── 2. cards ──────────────────────────────────────────
    for d in ["improvement", "cards", ".gcc/cards", ".GCC/knowledge"]:
        p = proj / d
        if p.is_dir():
            try:
                n = db.import_cards_dir(p)
                results["cards"] += n
            except Exception as e:
                results["errors"].append(f"cards/{d}: {e}")

    # ── 3. products/yaml ──────────────────────────────────
    for d in ["params", "config", ".GCC/params"]:
        p = proj / d
        if p.is_dir():
            try:
                n = db.import_yaml_dir(p)
                results["products"] += n
            except Exception as e:
                results["errors"].append(f"yaml/{d}: {e}")

    # ── 4. tasks ──────────────────────────────────────────
    tasks_file = root / "tasks.jsonl"
    if tasks_file.exists():
        try:
            n = _sync_tasks(conn, tasks_file)
            results["tasks"] = n
        except Exception as e:
            results["errors"].append(f"tasks: {e}")

    # ── 5. suggestions ────────────────────────────────────
    sug_file = root / "suggestions.jsonl"
    if sug_file.exists():
        try:
            n = _sync_suggestions(conn, sug_file)
            results["suggestions"] = n
        except Exception as e:
            results["errors"].append(f"suggestions: {e}")

    # ── 6. knowledge ──────────────────────────────────────
    know_file = root / "knowledge_index.jsonl"
    if know_file.exists():
        try:
            n = _sync_knowledge(conn, know_file)
            results["knowledge"] = n
        except Exception as e:
            results["errors"].append(f"knowledge: {e}")

    # ── 7. analysis reports ───────────────────────────────
    ana_dir = root / "analysis"
    if ana_dir.is_dir():
        try:
            n = _sync_analysis(conn, ana_dir)
            results["analysis"] = n
        except Exception as e:
            results["errors"].append(f"analysis: {e}")

    # ── 8. handoff/sessions ───────────────────────────────
    for f in ["handoff.md", ".gcc/handoff.md"]:
        p = proj / f
        if p.exists():
            try:
                n = db.import_handoff_md(p)
                results["sessions"] = n
            except Exception as e:
                results["errors"].append(f"sessions: {e}")
            break

    conn.commit()
    return results


def _sync_tasks(conn, tasks_file: Path) -> int:
    """同步 tasks.jsonl → tasks 表"""
    n = 0
    for line in tasks_file.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            t = json.loads(line)
            # 计算 progress 和 current_step
            steps = t.get("steps", [])
            done  = sum(1 for s in steps if s.get("status") in ("completed", "skipped"))
            progress = f"{done}/{len(steps)}"
            cur_step = ""
            for s in steps:
                if s.get("status") in ("pending", "running"):
                    cur_step = s.get("description", "")
                    break

            conn.execute("""
                INSERT OR REPLACE INTO tasks
                  (task_id, title, status, priority, progress,
                   current_step, steps_json, created_at, updated_at,
                   finished_at, result_summary)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                t.get("task_id"), t.get("title"), t.get("status"),
                t.get("priority", "normal"), progress, cur_step,
                json.dumps(steps, ensure_ascii=False),
                t.get("created_at"), t.get("updated_at"),
                t.get("finished_at"), t.get("result_summary", ""),
            ))

            # 同步改善点关联
            key_id = t.get("key", "")
            if key_id:
                conn.execute("""
                    INSERT OR IGNORE INTO improvement_task_links
                      (key_id, task_id, linked_at)
                    VALUES (?,?,?)
                """, (key_id, t.get("task_id"), _now()))

            n += 1
        except Exception as e:
            logger.warning("[GCC_DB] sync task %s failed: %s", t.get("task_id", "?"), e)
    return n


def _sync_suggestions(conn, sug_file: Path) -> int:
    """同步 suggestions.jsonl → suggestions 表"""
    n = 0
    for line in sug_file.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            s = json.loads(line)
            conn.execute("""
                INSERT OR REPLACE INTO suggestions
                  (suggestion_id, source, description, current_value,
                   suggested_value, evidence, status, priority,
                   created_at, reviewed_at, review_note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                s.get("suggestion_id"), s.get("source"),
                s.get("description"), s.get("current_value"),
                s.get("suggested_value"), s.get("evidence"),
                s.get("status", "pending"), s.get("priority", "normal"),
                s.get("created_at"), s.get("reviewed_at"),
                s.get("review_note", ""),
            ))

            # 同步改善点关联
            key_id = s.get("related_key", "")
            if key_id:
                conn.execute("""
                    INSERT OR IGNORE INTO improvement_suggestion_links
                      (key_id, suggestion_id, linked_at)
                    VALUES (?,?,?)
                """, (key_id, s.get("suggestion_id"), _now()))

            n += 1
        except Exception as e:
            logger.warning("[GCC_DB] sync suggestion %s failed: %s", s.get("suggestion_id", "?"), e)
    return n


def _sync_knowledge(conn, know_file: Path) -> int:
    """同步 knowledge_index.jsonl → knowledge_sources 表

    jsonl 有三种记录格式:
      1) 来源: {source_id, source_type, title, imported_at}
      2) 关联: {source_id, linked_key, linked_at}  — 仅关联，不含元数据
      3) 审批: {draft_id, card_path, approved_at, key} — 无 source_id

    Bug fix: 第2种记录不应覆盖已有的 source_type/title。
    改用两阶段: 先收集所有来源元数据，再写入 + 处理关联/审批。
    """
    # ── 第一阶段: 收集所有来源元数据 ──
    sources: dict = {}      # source_id → {source_type, title, imported_at, ...}
    links: list = []        # (key_id, source_id)
    approvals: list = []    # (source_id, card_path, approved_at)

    for line in know_file.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            k = json.loads(line)
        except Exception as e:
            logger.warning("[GCC_DB] parse knowledge line failed: %s", e)
            continue

        sid = k.get("source_id", "")

        # 记录类型1: 来源(有 source_type)
        if sid and k.get("source_type"):
            sources[sid] = {
                "source_type": k["source_type"],
                "title":       k.get("title", ""),
                "imported_at": k.get("imported_at", ""),
            }

        # 记录类型2: 关联(有 linked_key)
        if sid and k.get("linked_key"):
            links.append((k["linked_key"], sid))

        # 记录类型3: 审批(有 draft_id + card_path)
        did = k.get("draft_id", "")
        if did and k.get("card_path"):
            # draft_id 格式 KD_xxx，对应 source_id 格式 KS_xxx
            approx_sid = did.replace("KD_", "KS_", 1)
            approvals.append((approx_sid, k["card_path"], k.get("approved_at", "")))

    # ── 第二阶段: 写入 knowledge_sources ──
    n = 0
    for sid, meta in sources.items():
        conn.execute("""
            INSERT INTO knowledge_sources
              (source_id, source_type, title, draft_status, imported_at, approved_at, card_path)
            VALUES (?,?,?,'draft',?,NULL,'')
            ON CONFLICT(source_id) DO UPDATE SET
              source_type = COALESCE(excluded.source_type, knowledge_sources.source_type),
              title       = COALESCE(excluded.title, knowledge_sources.title),
              imported_at = COALESCE(excluded.imported_at, knowledge_sources.imported_at)
        """, (sid, meta["source_type"], meta["title"], meta["imported_at"]))
        n += 1

    # ── 第三阶段: 处理审批(更新状态和card_path) ──
    for sid, card_path, approved_at in approvals:
        conn.execute("""
            UPDATE knowledge_sources
            SET draft_status = 'approved',
                approved_at  = COALESCE(?, approved_at),
                card_path    = COALESCE(?, card_path)
            WHERE source_id = ?
        """, (approved_at, card_path, sid))

    # ── 第四阶段: 处理关联 ──
    for key_id, sid in links:
        conn.execute("""
            INSERT OR IGNORE INTO improvement_knowledge_links
              (key_id, source_id, linked_at)
            VALUES (?,?,?)
        """, (key_id, sid, _now()))

    return n


def _sync_analysis(conn, ana_dir: Path) -> int:
    """同步 analysis/*.md → analysis_reports 表"""
    n = 0
    for f in sorted(ana_dir.glob("*.md")):
        try:
            report_id = f.stem
            # 从文件名提取时间 analyze_20260220_1430
            generated_at = _now()
            period = "24h"
            parts = report_id.split("_")
            if len(parts) >= 3:
                try:
                    dt = parts[1] + parts[2] if len(parts) > 2 else parts[1]
                    generated_at = dt
                except (IndexError, ValueError) as e:
                    logger.warning("[GCC_DB] parse report date from %s failed: %s", report_id, e)

            conn.execute("""
                INSERT OR IGNORE INTO analysis_reports
                  (report_id, period, generated_at, report_path)
                VALUES (?,?,?,?)
            """, (report_id, period, generated_at, str(f)))
            n += 1
        except Exception as e:
            logger.warning("[GCC_DB] sync analysis report %s failed: %s", f.name, e)
    return n

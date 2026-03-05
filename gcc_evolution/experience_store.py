"""
GCC v4.0 — Experience Store
v4.0: + experience graph fields, downstream tracking, card compression,
      DB migration, quality-gated storage
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CardStatus, ExperienceCard, ExperienceType, CardQuality


# ════════════════════════════════════════════════════════════
# Local Memory (session-scoped)
# ════════════════════════════════════════════════════════════

class LocalMemory:
    def __init__(self, session_id: str, storage_dir: str = ".gcc/local_memory"):
        self.session_id = session_id
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / f"{session_id}.json"
        self._data: dict[str, Any] = {"failed_patterns": [], "notes": []}
        if self._file.exists():
            self._data = json.loads(self._file.read_text("utf-8"))

    def _save(self):
        self._file.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), "utf-8")

    def record_failure(self, pattern: str) -> None:
        if pattern not in self._data["failed_patterns"]:
            self._data["failed_patterns"].append(pattern)
            self._save()

    def is_known_failure(self, pattern: str) -> bool:
        return pattern in self._data["failed_patterns"]

    def get_failures(self) -> list[str]:
        return list(self._data["failed_patterns"])

    def add_note(self, note: str) -> None:
        self._data["notes"].append(note)
        self._save()

    def cleanup(self) -> None:
        if self._file.exists():
            self._file.unlink()


# ════════════════════════════════════════════════════════════
# Schema & Migrations
# ════════════════════════════════════════════════════════════

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS experiences (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    source_session  TEXT DEFAULT '',
    exp_type        TEXT DEFAULT 'success',
    trigger_task    TEXT DEFAULT '',
    trigger_symptom TEXT DEFAULT '',
    trigger_kw      TEXT DEFAULT '[]',
    strategy        TEXT DEFAULT '',
    key_insight     TEXT DEFAULT '',
    metrics_before  TEXT DEFAULT '{}',
    metrics_after   TEXT DEFAULT '{}',
    confidence      REAL DEFAULT 0.0,
    pitfalls        TEXT DEFAULT '[]',
    original_step   TEXT DEFAULT '',
    revised_step    TEXT DEFAULT '',
    source_sessions TEXT DEFAULT '[]',
    merged_steps    TEXT DEFAULT '[]',
    key             TEXT DEFAULT '',
    project         TEXT DEFAULT '',
    tags            TEXT DEFAULT '[]',
    use_count       INTEGER DEFAULT 0,
    last_used       TEXT DEFAULT '',
    embedding       TEXT DEFAULT '[]',
    attachments     TEXT DEFAULT '[]',
    status          TEXT DEFAULT 'draft',
    status_history  TEXT DEFAULT '[]',
    source_ref      TEXT DEFAULT '',
    last_validated  TEXT DEFAULT '',
    decay_rate      REAL DEFAULT 0.05,
    -- v4.0: experience graph
    parent_id       TEXT DEFAULT '',
    supersedes_id   TEXT DEFAULT '',
    related_ids     TEXT DEFAULT '[]',
    -- v4.0: downstream impact
    downstream_sessions TEXT DEFAULT '[]',
    downstream_scores   TEXT DEFAULT '[]',
    downstream_avg      REAL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_type ON experiences(exp_type);
CREATE INDEX IF NOT EXISTS idx_project ON experiences(project);
CREATE INDEX IF NOT EXISTS idx_confidence ON experiences(confidence);
CREATE INDEX IF NOT EXISTS idx_key ON experiences(key);
CREATE INDEX IF NOT EXISTS idx_status ON experiences(status);
CREATE INDEX IF NOT EXISTS idx_parent ON experiences(parent_id);

CREATE TABLE IF NOT EXISTS session_scores (
    session_id  TEXT PRIMARY KEY,
    key         TEXT DEFAULT '',
    task        TEXT DEFAULT '',
    score       REAL DEFAULT 0.0,
    created_at  TEXT DEFAULT '',
    card_ids    TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_ss_key ON session_scores(key);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT DEFAULT ''
);
"""

_MIGRATIONS = [
    # Migration 1: v3.x → v4.0 (add graph + downstream columns)
    [
        "ALTER TABLE experiences ADD COLUMN parent_id TEXT DEFAULT ''",
        "ALTER TABLE experiences ADD COLUMN supersedes_id TEXT DEFAULT ''",
        "ALTER TABLE experiences ADD COLUMN related_ids TEXT DEFAULT '[]'",
        "ALTER TABLE experiences ADD COLUMN downstream_sessions TEXT DEFAULT '[]'",
        "ALTER TABLE experiences ADD COLUMN downstream_scores TEXT DEFAULT '[]'",
        "ALTER TABLE experiences ADD COLUMN downstream_avg REAL DEFAULT 0.0",
        """CREATE TABLE IF NOT EXISTS session_scores (
            session_id TEXT PRIMARY KEY, key TEXT DEFAULT '',
            task TEXT DEFAULT '', score REAL DEFAULT 0.0,
            created_at TEXT DEFAULT '', card_ids TEXT DEFAULT '[]')""",
        "CREATE INDEX IF NOT EXISTS idx_ss_key ON session_scores(key)",
        "CREATE INDEX IF NOT EXISTS idx_key ON experiences(key)",
        "CREATE INDEX IF NOT EXISTS idx_status ON experiences(status)",
        "CREATE INDEX IF NOT EXISTS idx_parent ON experiences(parent_id)",
    ],
]


# ════════════════════════════════════════════════════════════
# Global Memory
# ════════════════════════════════════════════════════════════

class GlobalMemory:
    def __init__(self, db_path: str = ".gcc/experiences/global.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables or migrate existing DB."""
        # Check if DB already has tables
        tables = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r["name"] for r in tables}

        if "experiences" not in table_names:
            # Fresh DB: create v4.0 schema directly
            self._conn.executescript(_SCHEMA_V1)
            self._set_meta("schema_version", "4.0")
        else:
            # Existing DB: check if migration needed
            version = self._get_meta("schema_version") or "3.0"
            if version < "4.0":
                self._migrate(version)

        self._conn.commit()

    def _migrate(self, from_version: str):
        """Apply migrations to upgrade DB schema."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(experiences)").fetchall()}
        for migration in _MIGRATIONS:
            for stmt in migration:
                # Skip ALTER if column already exists
                if stmt.strip().upper().startswith("ALTER"):
                    col_match = re.search(r'ADD COLUMN\s+(\w+)', stmt, re.IGNORECASE)
                    if col_match and col_match.group(1) in cols:
                        continue
                try:
                    self._conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # index/table already exists
        self._set_meta("schema_version", "4.0")
        self._conn.commit()

    def _get_meta(self, key: str) -> str | None:
        try:
            r = self._conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
            return r["v"] if r else None
        except sqlite3.OperationalError:
            return None

    def _set_meta(self, key: str, value: str):
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (key, value))
        except sqlite3.OperationalError:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT DEFAULT '')")
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (key, value))

    def close(self):
        self._conn.close()

    # ── Write ──

    def store(self, card: ExperienceCard) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO experiences
               (id,created_at,source_session,exp_type,
                trigger_task,trigger_symptom,trigger_kw,
                strategy,key_insight,
                metrics_before,metrics_after,confidence,
                pitfalls,original_step,revised_step,
                source_sessions,merged_steps,
                key,project,tags,use_count,last_used,embedding,
                attachments,status,status_history,source_ref,
                last_validated,decay_rate,
                parent_id,supersedes_id,related_ids,
                downstream_sessions,downstream_scores,downstream_avg)
               VALUES (?,?,?,?, ?,?,?, ?,?, ?,?,?, ?,?,?, ?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?,
                       ?,?,?, ?,?,?)""",
            (
                card.id, card.created_at, card.source_session, card.exp_type.value,
                card.trigger_task_type, card.trigger_symptom,
                json.dumps(card.trigger_keywords, ensure_ascii=False),
                card.strategy, card.key_insight,
                json.dumps(card.metrics_before, ensure_ascii=False),
                json.dumps(card.metrics_after, ensure_ascii=False),
                card.confidence,
                json.dumps(card.pitfalls, ensure_ascii=False),
                card.original_step, card.revised_step,
                json.dumps(card.source_sessions, ensure_ascii=False),
                json.dumps(card.merged_steps, ensure_ascii=False),
                card.key, card.project,
                json.dumps(card.tags, ensure_ascii=False),
                card.use_count, card.last_used,
                json.dumps(card.embedding),
                json.dumps(card.attachments, ensure_ascii=False),
                card.status.value,
                json.dumps(card.status_history, ensure_ascii=False),
                card.source_ref,
                card.last_validated, card.decay_rate,
                card.parent_id, card.supersedes_id,
                json.dumps(card.related_ids, ensure_ascii=False),
                json.dumps(card.downstream_sessions, ensure_ascii=False),
                json.dumps(card.downstream_scores),
                card.downstream_avg,
            ),
        )
        self._conn.commit()
        return card.id

    def store_with_gate(self, card: ExperienceCard) -> tuple[bool, CardQuality]:
        """v4.0: Store card only if it passes quality gate."""
        existing = [c.key_insight for c in self.get_all(limit=200)]
        quality = CardQuality()
        passed = quality.check(card, existing)
        if passed:
            self.store(card)
        return passed, quality

    def store_many(self, cards: list[ExperienceCard]) -> int:
        for c in cards:
            self.store(c)
        return len(cards)

    def delete(self, exp_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM experiences WHERE id=?", (exp_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def increment_use(self, exp_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE experiences SET use_count=use_count+1, last_used=? WHERE id=?",
            (now, exp_id))
        self._conn.commit()

    # ── v4.0: Downstream Impact Tracking ──

    def record_session_score(self, session_id: str, key: str, task: str,
                             score: float, card_ids: list[str]) -> None:
        """Record a session's score and which cards it used."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO session_scores
               (session_id, key, task, score, created_at, card_ids)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, key, task, score, now, json.dumps(card_ids)))

        # Update downstream impact for each card used
        for cid in card_ids:
            card = self.get(cid)
            if card:
                if session_id not in card.downstream_sessions:
                    card.downstream_sessions.append(session_id)
                    card.downstream_scores.append(score)
                    card.compute_downstream_avg()
                    self.store(card)

        self._conn.commit()

    def get_key_score_history(self, key: str) -> list[dict]:
        """Get all session scores for a KEY, ordered by time."""
        rows = self._conn.execute(
            "SELECT * FROM session_scores WHERE key=? ORDER BY created_at",
            (key,)).fetchall()
        return [{"session_id": r["session_id"], "score": r["score"],
                 "task": r["task"], "created_at": r["created_at"]}
                for r in rows]

    # ── v4.0: Card Compression ──

    def compress(self, overlap_threshold: float = 0.70) -> int:
        """
        Merge similar cards. Keep highest confidence, deprecate others.
        Returns number of cards deprecated.
        """
        cards = self.get_all(limit=10000)
        if len(cards) < 2:
            return 0

        deprecated = 0
        seen: list[ExperienceCard] = []

        # Sort by confidence descending — keep the best
        cards.sort(key=lambda c: c.confidence, reverse=True)

        for card in cards:
            if card.status == CardStatus.DEPRECATED:
                continue

            is_dup = False
            for existing in seen:
                overlap = self._word_overlap(card.key_insight, existing.key_insight)
                if overlap > overlap_threshold:
                    # Deprecate the weaker card, link it
                    card.status = CardStatus.DEPRECATED
                    card.supersedes_id = existing.id
                    if card.id not in existing.related_ids:
                        existing.related_ids.append(card.id)
                    self.store(card)
                    self.store(existing)
                    deprecated += 1
                    is_dup = True
                    break

            if not is_dup:
                seen.append(card)

        return deprecated

    @staticmethod
    def _word_overlap(a: str, b: str) -> float:
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    # ── Read ──

    def get(self, exp_id: str) -> ExperienceCard | None:
        row = self._conn.execute(
            "SELECT * FROM experiences WHERE id=?", (exp_id,)).fetchone()
        return self._to_card(row) if row else None

    def search(self, keywords: list[str], limit: int = 10,
               project: str | None = None,
               exp_type: ExperienceType | None = None) -> list[ExperienceCard]:
        conds = []
        params: list[Any] = []
        for kw in keywords:
            pat = f"%{kw}%"
            conds.append(
                "(trigger_task LIKE ? OR trigger_symptom LIKE ? "
                "OR strategy LIKE ? OR key_insight LIKE ? OR tags LIKE ?)")
            params.extend([pat] * 5)
        if project:
            conds.append("project LIKE ?")
            params.append(f"%{project}%")
        if exp_type:
            conds.append("exp_type=?")
            params.append(exp_type.value)

        where = " AND ".join(conds) if conds else "1=1"
        rows = self._conn.execute(
            f"SELECT * FROM experiences WHERE {where} "
            f"ORDER BY confidence DESC, use_count DESC LIMIT ?",
            [*params, limit]).fetchall()
        return [self._to_card(r) for r in rows]

    def get_all(self, limit: int = 200) -> list[ExperienceCard]:
        rows = self._conn.execute(
            "SELECT * FROM experiences ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [self._to_card(r) for r in rows]

    def get_by_key(self, key: str) -> list[ExperienceCard]:
        rows = self._conn.execute(
            "SELECT * FROM experiences WHERE key=? ORDER BY created_at",
            (key,)).fetchall()
        return [self._to_card(r) for r in rows]

    def get_children(self, parent_id: str) -> list[ExperienceCard]:
        """v4.0: Get cards that evolved from this parent."""
        rows = self._conn.execute(
            "SELECT * FROM experiences WHERE parent_id=?",
            (parent_id,)).fetchall()
        return [self._to_card(r) for r in rows]

    def count(self) -> int:
        r = self._conn.execute("SELECT COUNT(*) FROM experiences").fetchone()
        return r[0] if r else 0

    def stats(self) -> dict:
        total = self.count()
        by_type = {}
        for t in ExperienceType:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM experiences WHERE exp_type=?",
                (t.value,)).fetchone()
            by_type[t.value] = r[0] if r else 0
        by_status = {}
        for s in CardStatus:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM experiences WHERE status=?",
                (s.value,)).fetchone()
            by_status[s.value] = r[0] if r else 0
        avg = self._conn.execute(
            "SELECT AVG(confidence) FROM experiences").fetchone()
        avg_downstream = self._conn.execute(
            "SELECT AVG(downstream_avg) FROM experiences WHERE downstream_avg > 0"
        ).fetchone()
        return {
            "total": total,
            "by_type": by_type,
            "by_status": by_status,
            "avg_confidence": round(avg[0] or 0, 3),
            "avg_downstream_impact": round((avg_downstream[0] or 0), 3),
        }

    # ── Export / Import ──

    def export_json(self, path: str = ".gcc/experiences/export.json") -> int:
        cards = self.get_all(limit=100000)
        data = []
        for c in cards:
            data.append({
                "id": c.id, "type": c.exp_type.value,
                "status": c.status.value,
                "trigger_task": c.trigger_task_type,
                "trigger_symptom": c.trigger_symptom,
                "keywords": c.trigger_keywords,
                "strategy": c.strategy,
                "key_insight": c.key_insight,
                "metrics_before": c.metrics_before,
                "metrics_after": c.metrics_after,
                "confidence": c.confidence,
                "pitfalls": c.pitfalls,
                "project": c.project,
                "tags": c.tags,
                "parent_id": c.parent_id,
                "supersedes_id": c.supersedes_id,
                "related_ids": c.related_ids,
                "downstream_avg": c.downstream_avg,
            })
        Path(path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        return len(data)

    def import_json(self, path: str) -> int:
        data = json.loads(Path(path).read_text("utf-8"))
        count = 0
        for d in data:
            card = ExperienceCard(
                id=d.get("id", ""),
                exp_type=ExperienceType(d.get("type", "success")),
                trigger_task_type=d.get("trigger_task", ""),
                trigger_symptom=d.get("trigger_symptom", ""),
                trigger_keywords=d.get("keywords", []),
                strategy=d.get("strategy", ""),
                key_insight=d.get("key_insight", ""),
                metrics_before=d.get("metrics_before", {}),
                metrics_after=d.get("metrics_after", {}),
                confidence=d.get("confidence", 0.5),
                pitfalls=d.get("pitfalls", []),
                project=d.get("project", ""),
                tags=d.get("tags", []),
            )
            self.store(card)
            count += 1
        return count

    # ── Internal ──

    def _to_card(self, row: sqlite3.Row) -> ExperienceCard:
        def _safe_json(val, default):
            try:
                return json.loads(val or json.dumps(default))
            except (json.JSONDecodeError, TypeError):
                return default

        def _safe_col(name, default=""):
            try:
                return row[name] or default
            except (IndexError, KeyError):
                return default

        return ExperienceCard(
            id=row["id"],
            created_at=row["created_at"],
            source_session=row["source_session"],
            exp_type=ExperienceType(row["exp_type"]),
            trigger_task_type=row["trigger_task"],
            trigger_symptom=row["trigger_symptom"],
            trigger_keywords=_safe_json(row["trigger_kw"], []),
            strategy=row["strategy"],
            key_insight=row["key_insight"],
            metrics_before=_safe_json(row["metrics_before"], {}),
            metrics_after=_safe_json(row["metrics_after"], {}),
            confidence=row["confidence"],
            pitfalls=_safe_json(row["pitfalls"], []),
            original_step=row["original_step"] or "",
            revised_step=row["revised_step"] or "",
            source_sessions=_safe_json(row["source_sessions"], []),
            merged_steps=_safe_json(row["merged_steps"], []),
            key=row["key"] or "",
            project=row["project"],
            tags=_safe_json(row["tags"], []),
            use_count=row["use_count"],
            last_used=row["last_used"] or "",
            embedding=_safe_json(row["embedding"], []),
            attachments=_safe_json(row["attachments"], []),
            status=CardStatus(row["status"] or "draft"),
            status_history=_safe_json(row["status_history"], []),
            source_ref=row["source_ref"] or "",
            last_validated=row["last_validated"] or "",
            decay_rate=float(row["decay_rate"] or 0.05),
            parent_id=_safe_col("parent_id"),
            supersedes_id=_safe_col("supersedes_id"),
            related_ids=_safe_json(_safe_col("related_ids", "[]"), []),
            downstream_sessions=_safe_json(_safe_col("downstream_sessions", "[]"), []),
            downstream_scores=_safe_json(_safe_col("downstream_scores", "[]"), []),
            downstream_avg=float(_safe_col("downstream_avg", 0)),
        )

"""
GCC v4.87 — Suggest & Review
参数调整建议管理，人类审核后才生效。

设计原则：
  分析产生建议，不自动执行。
  人类逐条审核：应用/拒绝/跳过。
  所有决定都有记录，可追溯。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sid() -> str:
    return f"SUG_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


@dataclass
class Suggestion:
    """一条参数调整建议"""
    suggestion_id: str = field(default_factory=_sid)
    source:        str = ""       # 来源：retrospective / analyze / human
    related_key:   str = ""       # 关联 KEY
    subject:       str = ""       # 调整对象（品种、模块等）
    description:   str = ""       # 建议内容描述
    current_value: str = ""       # 当前值
    suggested_value: str = ""     # 建议值
    evidence:      str = ""       # 支撑证据（胜率、样本数等）
    status:        str = "pending"  # pending / applied / rejected / skipped
    created_at:    str = field(default_factory=_now)
    reviewed_at:   str = ""
    review_note:   str = ""
    priority:      str = "normal"   # high / normal / low


class SuggestStore:
    """建议存储和审核管理"""

    def __init__(self, gcc_dir: Path | str = ".gcc"):
        self.gcc_dir = Path(gcc_dir)
        self.gcc_dir.mkdir(exist_ok=True)
        self.store_file = self.gcc_dir / "suggestions.jsonl"

    def add(self, suggestion: Suggestion) -> Suggestion:
        """添加一条建议"""
        with open(self.store_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(self._to_dict(suggestion), ensure_ascii=False) + "\n")
        return suggestion

    def add_many(self, suggestions: list[Suggestion]):
        for s in suggestions:
            self.add(s)

    def list_pending(self) -> list[Suggestion]:
        return [s for s in self._load_all() if s.status == "pending"]

    def list_all(self, status: str = "") -> list[Suggestion]:
        all_s = self._load_all()
        if status:
            return [s for s in all_s if s.status == status]
        return all_s

    def apply(self, suggestion_id: str, note: str = "") -> bool:
        return self._update_status(suggestion_id, "applied", note)

    def reject(self, suggestion_id: str, note: str = "") -> bool:
        return self._update_status(suggestion_id, "rejected", note)

    def skip(self, suggestion_id: str) -> bool:
        return self._update_status(suggestion_id, "skipped", "")

    def stats(self) -> dict:
        all_s = self._load_all()
        return {
            "total":    len(all_s),
            "pending":  sum(1 for s in all_s if s.status == "pending"),
            "applied":  sum(1 for s in all_s if s.status == "applied"),
            "rejected": sum(1 for s in all_s if s.status == "rejected"),
            "skipped":  sum(1 for s in all_s if s.status == "skipped"),
        }

    def detect_conflicts(self) -> list[tuple[Suggestion, Suggestion, str]]:
        """GCC-0166: 检测pending建议中的互矛盾对。

        规则:
          1. 同subject不同suggested_value → 参数冲突
          2. 同subject一个增大一个减小 → 方向冲突

        Returns: [(sug_a, sug_b, reason), ...]
        """
        pending = self.list_pending()
        conflicts = []
        for i, a in enumerate(pending):
            for b in pending[i + 1:]:
                if not a.subject or a.subject != b.subject:
                    continue
                # 同subject但建议值不同
                if (a.suggested_value and b.suggested_value
                        and a.suggested_value != b.suggested_value):
                    reason = (f"同一对象'{a.subject}'有不同建议值: "
                              f"'{a.suggested_value}' vs '{b.suggested_value}'")
                    conflicts.append((a, b, reason))
                    logger.warning("[SUGGEST] conflict: %s [%s] vs [%s]",
                                   reason, a.suggestion_id, b.suggestion_id)
        return conflicts

    # ── 内部 ──────────────────────────────────────────────────

    def _load_all(self) -> list[Suggestion]:
        if not self.store_file.exists():
            return []
        items = []
        for line in self.store_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                items.append(self._from_dict(json.loads(line)))
            except Exception as e:
                logger.warning("[SUGGEST] Failed to parse suggestion line: %s", e)
        return items

    def _update_status(self, sid: str, status: str, note: str) -> bool:
        all_s = self._load_all()
        found = False
        for s in all_s:
            if s.suggestion_id == sid:
                s.status = status
                s.reviewed_at = _now()
                s.review_note = note
                found = True
        if found:
            with open(self.store_file, "w", encoding="utf-8") as f:
                for s in all_s:
                    f.write(json.dumps(self._to_dict(s), ensure_ascii=False) + "\n")
        return found

    def _to_dict(self, s: Suggestion) -> dict:
        return s.__dict__.copy()

    def _from_dict(self, data: dict) -> Suggestion:
        return Suggestion(**{k: v for k, v in data.items()
                              if k in Suggestion.__dataclass_fields__})

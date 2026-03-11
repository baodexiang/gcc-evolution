"""Minimal SkillBank implementation for community SkillRL workflows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.utcnow().isoformat()


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


@dataclass
class SkillEntry:
    skill_id: str
    name: str
    content: str
    skill_type: str = "general"
    symbol: str = ""
    key_id: str = ""
    source: str = "learning"
    confidence: float = 0.8
    success_rate: float = 0.5
    use_count: int = 0
    version: int = 1
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SkillBank:
    """File-backed two-layer SkillBank: general + task_specific."""

    def __init__(self, path: str | Path = "state/skillbank.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _load(self) -> list[SkillEntry]:
        entries: list[SkillEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                entries.append(SkillEntry(**payload))
            except Exception:
                continue
        return entries

    def _save_all(self, entries: list[SkillEntry]) -> None:
        content = "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in entries)
        if content:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")

    def add(self, entry: SkillEntry) -> SkillEntry:
        entries = self._load()
        for idx, existing in enumerate(entries):
            if existing.skill_id == entry.skill_id:
                entry.version = max(existing.version + 1, entry.version)
                entry.use_count = max(existing.use_count, entry.use_count)
                entry.updated_at = _now()
                entries[idx] = entry
                self._save_all(entries)
                return entry
        entries.append(entry)
        self._save_all(entries)
        return entry

    def status(self) -> dict[str, Any]:
        entries = self._load()
        symbols = sorted({e.symbol for e in entries if e.symbol})
        avg_conf = sum(e.confidence for e in entries) / len(entries) if entries else 0.0
        return {
            "total": len(entries),
            "general": sum(1 for e in entries if e.skill_type == "general"),
            "task_specific": sum(1 for e in entries if e.skill_type == "task_specific"),
            "symbols": symbols,
            "avg_confidence": avg_conf,
        }

    def retrieve(self, query: str, symbol: str = "", top_k: int = 5) -> list[SkillEntry]:
        entries = self._load()
        q = _normalize(query)
        terms = set(q.split())
        ranked: list[tuple[float, SkillEntry]] = []
        for entry in entries:
            hay = _normalize(f"{entry.name} {entry.content} {entry.key_id} {entry.symbol}")
            token_set = set(hay.split())
            overlap = len(terms & token_set)
            if not overlap and q not in hay:
                continue
            score = float(overlap)
            if q and q in hay:
                score += 1.0
            if symbol and entry.symbol and _normalize(entry.symbol) == _normalize(symbol):
                score += 2.0
            if entry.skill_type == "general":
                score += 0.5
            score += entry.confidence + entry.success_rate + min(entry.use_count / 10.0, 1.0)
            ranked.append((score, entry))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in ranked[:top_k]]

    def top_skills(self, skill_type: str = "", symbol: str = "", top_k: int = 5) -> list[SkillEntry]:
        entries = self._load()
        if skill_type:
            entries = [e for e in entries if e.skill_type == skill_type]
        if symbol:
            entries = [e for e in entries if _normalize(e.symbol) == _normalize(symbol)]
        entries.sort(
            key=lambda e: (e.confidence, e.success_rate, e.use_count, e.updated_at),
            reverse=True,
        )
        return entries[:top_k]

    def auto_redist_marked(self) -> int:
        return 0

    def distill_from_cards(self) -> int:
        """Build skills from promoted long-term patterns."""
        state_dir = self.path.parent
        created = 0
        for fp in state_dir.glob("long_term*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            for key, value in data.items():
                if not key.startswith("promoted::") or not isinstance(value, dict):
                    continue
                task_id = str(value.get("task_id", ""))
                conditions = value.get("conditions", {})
                skill_type = "task_specific" if task_id else "general"
                entry = SkillEntry(
                    skill_id=f"SK_{abs(hash(key)) % 1000000:06d}",
                    name=f"Promoted pattern {task_id or 'general'}",
                    content=f"conditions={conditions}; success_rate={value.get('success_rate', 0):.2f}",
                    skill_type=skill_type,
                    symbol=task_id if skill_type == "task_specific" else "",
                    key_id=task_id,
                    source=value.get("source", "short_term_promotion"),
                    confidence=float(value.get("success_rate", 0.5)),
                    success_rate=float(value.get("success_rate", 0.5)),
                    use_count=int(value.get("count", 0)),
                    metadata={"conditions": conditions},
                )
                self.add(entry)
                created += 1
        return created

    def distill_from_suggestions(self) -> int:
        """Build task-specific skills from reflections and blocked causal outcomes."""
        state_dir = self.path.parent / "audit"
        created = 0
        for fp in state_dir.glob("*_reflections.jsonl"):
            task_id = fp.stem.replace("_reflections", "")
            for line in fp.read_text(encoding="utf-8").splitlines()[-10:]:
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                reflection = payload.get("reflection", "")
                if not reflection:
                    continue
                entry = SkillEntry(
                    skill_id=f"RF_{abs(hash((task_id, reflection))) % 1000000:06d}",
                    name=f"Reflection guard {task_id}",
                    content=reflection,
                    skill_type="task_specific",
                    symbol=task_id,
                    key_id=task_id,
                    source="reflection",
                    confidence=0.75,
                    success_rate=0.5,
                    use_count=1,
                    metadata={"issues": payload.get("issues", [])},
                )
                self.add(entry)
                created += 1
        return created

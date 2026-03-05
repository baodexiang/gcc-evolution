"""
GCC v4.89 — State Manager
系统全局状态持久化，跨会话不丢失。

核心概念：
  Agent 有持久状态，不依赖单次会话。
  每个状态键值对都有版本号、来源、过期时间。
  状态变更自动记录 diff，可追溯。

使用方式：
  sm = StateManager()
  sm.set("current_task", "KEY-001", source="orchestrator")
  sm.set("phase", "analysis", ttl_hours=24)
  val = sm.get("current_task")
  sm.snapshot("before_update")
  history = sm.diff("before_update")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _nowdt() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StateEntry:
    key:        str
    value:      Any
    version:    int = 1
    source:     str = "system"      # 谁写入的
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    expires_at: str = ""            # 空=永不过期
    tags:       list = field(default_factory=list)

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return _nowdt() > exp
        except (ValueError, TypeError) as e:
            logger.warning("[STATE_MANAGER] Failed to parse expiry timestamp: %s", e)
            return False


class StateManager:
    """
    全局状态管理器，持久化到 .gcc/state.json。
    跨会话保持，不依赖内存。
    """

    def __init__(self, gcc_dir: Path | str = ".gcc"):
        self.gcc_dir   = Path(gcc_dir)
        self.gcc_dir.mkdir(exist_ok=True)
        self.state_file = self.gcc_dir / "state.json"
        self.snap_dir   = self.gcc_dir / "snapshots"
        self.snap_dir.mkdir(exist_ok=True)
        self._cache: dict[str, StateEntry] = {}
        self._load()

    # ── 读写 ──────────────────────────────────────────────────

    def set(self, key: str, value: Any,
            source: str = "system",
            ttl_hours: float = 0,
            tags: list = None) -> StateEntry:
        """写入状态"""
        expires_at = ""
        if ttl_hours > 0:
            exp = _nowdt() + timedelta(hours=ttl_hours)
            expires_at = exp.isoformat()

        existing = self._cache.get(key)
        version  = (existing.version + 1) if existing else 1

        entry = StateEntry(
            key=key, value=value, version=version,
            source=source, updated_at=_now(),
            expires_at=expires_at,
            tags=tags or [],
        )
        if existing:
            entry.created_at = existing.created_at

        self._cache[key] = entry
        self._save()
        return entry

    def get(self, key: str, default: Any = None) -> Any:
        """读取状态，过期返回 default"""
        entry = self._cache.get(key)
        if entry is None or entry.is_expired():
            return default
        return entry.value

    def get_entry(self, key: str) -> StateEntry | None:
        """读取完整 StateEntry"""
        entry = self._cache.get(key)
        if entry and entry.is_expired():
            return None
        return entry

    def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            self._save()
            return True
        return False

    def exists(self, key: str) -> bool:
        entry = self._cache.get(key)
        return entry is not None and not entry.is_expired()

    def keys(self, tag: str = "") -> list[str]:
        result = []
        for k, e in self._cache.items():
            if e.is_expired():
                continue
            if tag and tag not in e.tags:
                continue
            result.append(k)
        return result

    def get_all(self, tag: str = "") -> dict:
        return {k: self.get(k) for k in self.keys(tag)}

    # ── 快照与 Diff ────────────────────────────────────────────

    def snapshot(self, name: str) -> str:
        """保存当前状态快照"""
        snap = {
            "name": name,
            "taken_at": _now(),
            "state": {
                k: {"value": e.value, "version": e.version, "source": e.source}
                for k, e in self._cache.items()
                if not e.is_expired()
            }
        }
        path = self.snap_dir / f"{name}_{_nowdt().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def diff(self, snapshot_name: str) -> dict:
        """对比当前状态与快照的差异"""
        snaps = sorted(self.snap_dir.glob(f"{snapshot_name}_*.json"))
        if not snaps:
            return {"error": f"快照 {snapshot_name} 不存在"}

        snap_data = json.loads(snaps[-1].read_text(encoding="utf-8"))
        old_state = snap_data.get("state", {})
        new_state = {
            k: {"value": e.value, "version": e.version}
            for k, e in self._cache.items()
            if not e.is_expired()
        }

        added    = {k: new_state[k] for k in new_state if k not in old_state}
        removed  = {k: old_state[k] for k in old_state if k not in new_state}
        changed  = {
            k: {"old": old_state[k]["value"], "new": new_state[k]["value"]}
            for k in new_state
            if k in old_state and new_state[k]["value"] != old_state[k]["value"]
        }

        return {
            "snapshot": snap_data["taken_at"],
            "added":   added,
            "removed": removed,
            "changed": changed,
        }

    # ── 常用状态键（语义化封装）─────────────────────────────────

    @property
    def current_task(self) -> str:
        return self.get("system.current_task", "")

    @current_task.setter
    def current_task(self, value: str):
        self.set("system.current_task", value, source="orchestrator")

    @property
    def current_key(self) -> str:
        return self.get("system.current_key", "")

    @current_key.setter
    def current_key(self, value: str):
        self.set("system.current_key", value, source="orchestrator")

    @property
    def phase(self) -> str:
        return self.get("system.phase", "idle")

    @phase.setter
    def phase(self, value: str):
        self.set("system.phase", value, source="orchestrator")

    @property
    def last_analyze(self) -> str:
        return self.get("system.last_analyze", "")

    @property
    def last_anchor(self) -> str:
        return self.get("system.last_anchor", "")

    # ── 持久化 ────────────────────────────────────────────────

    def _save(self):
        data = {}
        for k, e in self._cache.items():
            data[k] = {
                "value":      e.value,
                "version":    e.version,
                "source":     e.source,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
                "expires_at": e.expires_at,
                "tags":       e.tags,
            }
        self.state_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self):
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            for k, v in data.items():
                self._cache[k] = StateEntry(
                    key=k,
                    value=v.get("value"),
                    version=v.get("version", 1),
                    source=v.get("source", "system"),
                    created_at=v.get("created_at", _now()),
                    updated_at=v.get("updated_at", _now()),
                    expires_at=v.get("expires_at", ""),
                    tags=v.get("tags", []),
                )
        except Exception as e:
            logger.warning("[STATE_MANAGER] Failed to load state file: %s", e)

    def summary(self) -> str:
        """简短状态摘要，供 handoff 使用"""
        lines = ["=== System State ==="]
        for k in sorted(self.keys()):
            e = self.get_entry(k)
            if e:
                lines.append(f"  {k}: {e.value}  (v{e.version}, by {e.source})")
        return "\n".join(lines)

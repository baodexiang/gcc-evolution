"""
GCC v4.89 — Scheduler
定时触发管理，支持 analyze / anchor / calibrate 等周期性任务。

设计原则：
  不依赖系统 cron，自身维护触发记录。
  每次 gcc-evo 运行时检查是否有到期任务需要提醒。
  人类决定是否执行，不自动执行。

使用方式：
  sch = Scheduler()
  sch.register("daily_anchor", interval_hours=24, command="gcc-evo anchor calibrate")
  sch.register("analyze_12h",  interval_hours=12, command="gcc-evo analyze run --period 12h")
  due = sch.check_due()   # 返回到期任务列表
  sch.mark_done("daily_anchor")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _nowdt() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScheduleEntry:
    name:           str
    command:        str             # 建议执行的命令
    interval_hours: float           # 触发间隔（小时）
    description:    str = ""
    enabled:        bool = True
    last_run:       str = ""        # 上次执行时间
    next_due:       str = ""        # 下次到期时间
    run_count:      int = 0
    tags:           list = field(default_factory=list)

    def is_due(self) -> bool:
        if not self.enabled:
            return False
        if not self.next_due:
            return True
        try:
            due = datetime.fromisoformat(self.next_due)
            return _nowdt() >= due
        except (ValueError, TypeError):
            return True

    def time_until_due(self) -> str:
        if not self.next_due:
            return "立即"
        try:
            due = datetime.fromisoformat(self.next_due)
            diff = due - _nowdt()
            if diff.total_seconds() <= 0:
                return "已到期"
            h = int(diff.total_seconds() // 3600)
            m = int((diff.total_seconds() % 3600) // 60)
            if h > 0:
                return f"{h}h{m}m 后"
            return f"{m}m 后"
        except (ValueError, TypeError):
            return "未知"


class Scheduler:
    """
    定时任务调度器，持久化到 .gcc/schedule.json。
    """

    def __init__(self, gcc_dir: Path | str = ".gcc"):
        self.gcc_dir       = Path(gcc_dir)
        self.gcc_dir.mkdir(exist_ok=True)
        self.schedule_file = self.gcc_dir / "schedule.json"
        self._entries: dict[str, ScheduleEntry] = {}
        self._load()
        self._ensure_defaults()

    # ── 注册与管理 ────────────────────────────────────────────

    def register(self, name: str,
                 interval_hours: float,
                 command: str,
                 description: str = "",
                 tags: list = None,
                 enabled: bool = True) -> ScheduleEntry:
        """注册定时任务"""
        entry = ScheduleEntry(
            name=name,
            command=command,
            interval_hours=interval_hours,
            description=description,
            enabled=enabled,
            tags=tags or [],
        )
        if name not in self._entries:
            # 首次注册，立即到期（提醒用户执行一次）
            entry.next_due = _now()
        else:
            # 更新配置，保留执行历史
            existing = self._entries[name]
            entry.last_run  = existing.last_run
            entry.next_due  = existing.next_due
            entry.run_count = existing.run_count

        self._entries[name] = entry
        self._save()
        return entry

    def mark_done(self, name: str) -> bool:
        """标记任务已执行，计算下次到期时间"""
        entry = self._entries.get(name)
        if not entry:
            return False
        now = _nowdt()
        entry.last_run  = now.isoformat()
        entry.run_count += 1
        entry.next_due  = (now + timedelta(hours=entry.interval_hours)).isoformat()
        self._save()
        return True

    def enable(self, name: str) -> bool:
        entry = self._entries.get(name)
        if entry:
            entry.enabled = True
            self._save()
            return True
        return False

    def disable(self, name: str) -> bool:
        entry = self._entries.get(name)
        if entry:
            entry.enabled = False
            self._save()
            return True
        return False

    def set_interval(self, name: str, hours: float) -> bool:
        entry = self._entries.get(name)
        if entry:
            entry.interval_hours = hours
            self._save()
            return True
        return False

    # ── 查询 ──────────────────────────────────────────────────

    def check_due(self) -> list[ScheduleEntry]:
        """返回所有已到期的任务"""
        return [e for e in self._entries.values() if e.is_due()]

    def list_all(self) -> list[ScheduleEntry]:
        return sorted(self._entries.values(), key=lambda e: e.next_due or "")

    def get(self, name: str) -> ScheduleEntry | None:
        return self._entries.get(name)

    def startup_check(self) -> str:
        """
        每次 gcc-evo 启动时调用，返回到期提醒。
        """
        due = self.check_due()
        if not due:
            return ""
        lines = [f"\n  ⏰ 有 {len(due)} 个定时任务待执行："]
        for e in due:
            lines.append(f"    [{e.name}] {e.description or e.command}")
        lines.append("")
        return "\n".join(lines)

    # ── 默认任务 ──────────────────────────────────────────────

    def _ensure_defaults(self):
        """确保默认定时任务存在"""
        defaults = [
            {
                "name": "aipro_update_30m",
                "interval_hours": 0.5,
                "command": "gcc-evo ask \"/aipro update\"",
                "description": "/aipro 文档与结构口径30分钟更新提醒",
                "tags": ["aipro", "update", "30m"],
            },
            {
                "name": "daily_anchor",
                "interval_hours": 24,
                "command": "gcc-evo anchor calibrate",
                "description": "每日方向校正",
                "tags": ["daily", "anchor"],
            },
            {
                "name": "analyze_12h",
                "interval_hours": 12,
                "command": "gcc-evo analyze run --period 12h",
                "description": "12小时回溯分析",
                "tags": ["analyze"],
            },
            {
                "name": "analyze_24h",
                "interval_hours": 24,
                "command": "gcc-evo analyze run --period 24h",
                "description": "24小时回溯分析",
                "tags": ["analyze"],
            },
            {
                "name": "suggest_review",
                "interval_hours": 48,
                "command": "gcc-evo suggest review",
                "description": "审核待处理参数建议",
                "tags": ["suggest"],
            },
        ]
        changed = False
        for d in defaults:
            if d["name"] not in self._entries:
                self.register(**d)
                changed = True
        if changed:
            self._save()

    # ── 持久化 ────────────────────────────────────────────────

    def _save(self):
        data = {}
        for name, e in self._entries.items():
            data[name] = {
                "command":        e.command,
                "interval_hours": e.interval_hours,
                "description":    e.description,
                "enabled":        e.enabled,
                "last_run":       e.last_run,
                "next_due":       e.next_due,
                "run_count":      e.run_count,
                "tags":           e.tags,
            }
        self.schedule_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self):
        if not self.schedule_file.exists():
            return
        try:
            data = json.loads(self.schedule_file.read_text(encoding="utf-8"))
            for name, v in data.items():
                self._entries[name] = ScheduleEntry(
                    name=name,
                    command=v.get("command", ""),
                    interval_hours=v.get("interval_hours", 24),
                    description=v.get("description", ""),
                    enabled=v.get("enabled", True),
                    last_run=v.get("last_run", ""),
                    next_due=v.get("next_due", ""),
                    run_count=v.get("run_count", 0),
                    tags=v.get("tags", []),
                )
        except Exception as e:
            logger.warning("[SCHEDULER] load schedule failed: %s", e)

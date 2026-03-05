"""
GCC v4.89 — Orchestrator
多任务编排，跨会话任务状态持久化。

核心概念（来自 Cornell 2505.10468）：
  Agentic AI = 持久记忆 + 编排自治
  Orchestrator 是 GCC v5.0 的 Agentic AI 层核心。

职责：
  - 任务生命周期管理（创建/暂停/恢复/完成）
  - 跨会话状态持久化（配合 StateManager）
  - 子任务依赖编排
  - 与 HumanAnchor 对齐，不偏离方向

使用方式：
  orc = Orchestrator()
  task = orc.create_task("分析信号质量", key="KEY-001")
  orc.add_step(task.task_id, "提取日志数据")
  orc.add_step(task.task_id, "Vision 回溯评估")
  orc.complete_step(task.task_id, 0, result="1876条导入完成")
  status = orc.status()
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _tid() -> str:
    return f"T{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"


class TaskStatus(str, Enum):
    PENDING    = "pending"     # 创建未开始
    RUNNING    = "running"     # 进行中
    PAUSED     = "paused"      # 暂停（跨会话等待）
    COMPLETED  = "completed"   # 完成
    FAILED     = "failed"      # 失败
    CANCELLED  = "cancelled"   # 取消


class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


@dataclass
class TaskStep:
    """任务中的单个步骤"""
    step_index:  int
    description: str
    status:      StepStatus = StepStatus.PENDING
    result:      str = ""
    started_at:  str = ""
    finished_at: str = ""
    error:       str = ""
    metadata:    dict = field(default_factory=dict)


@dataclass
class Task:
    """一个可跨会话持久化的任务"""
    task_id:     str = field(default_factory=_tid)
    title:       str = ""
    key:         str = ""           # 关联 KEY
    status:      TaskStatus = TaskStatus.PENDING
    priority:    str = "normal"     # high / normal / low
    steps:       list[TaskStep] = field(default_factory=list)
    created_at:  str = field(default_factory=_now)
    updated_at:  str = field(default_factory=_now)
    started_at:  str = ""
    finished_at: str = ""
    created_by:  str = "human"
    context:     dict = field(default_factory=dict)  # 任务上下文
    depends_on:  list[str] = field(default_factory=list)  # 依赖的任务ID
    result_summary: str = ""

    @property
    def current_step_index(self) -> int:
        for i, s in enumerate(self.steps):
            if s.status in (StepStatus.PENDING, StepStatus.RUNNING):
                return i
        return len(self.steps)

    @property
    def progress(self) -> str:
        total = len(self.steps)
        done  = sum(1 for s in self.steps
                    if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED))
        return f"{done}/{total}"

    @property
    def is_blocked(self) -> bool:
        """有未完成的依赖任务"""
        return bool(self.depends_on)


class Orchestrator:
    """
    任务编排器，持久化到 .gcc/tasks.jsonl。
    跨会话恢复，任务不丢失。
    """

    def __init__(self, gcc_dir: Path | str = ".gcc"):
        self.gcc_dir    = Path(gcc_dir)
        self.gcc_dir.mkdir(exist_ok=True)
        self.tasks_file = self.gcc_dir / "tasks.jsonl"
        self._tasks: dict[str, Task] = {}
        self._load()

    # ── 任务管理 ──────────────────────────────────────────────

    def create_task(self, title: str,
                    key: str = "",
                    priority: str = "normal",
                    steps: list[str] = None,
                    depends_on: list[str] = None,
                    context: dict = None,
                    created_by: str = "human") -> Task:
        """创建新任务"""
        task = Task(
            title=title,
            key=key,
            priority=priority,
            created_by=created_by,
            depends_on=depends_on or [],
            context=context or {},
        )
        for i, desc in enumerate(steps or []):
            task.steps.append(TaskStep(step_index=i, description=desc))

        self._tasks[task.task_id] = task
        self._save_task(task)
        return task

    def add_step(self, task_id: str, description: str) -> TaskStep | None:
        """向任务添加步骤"""
        task = self._tasks.get(task_id)
        if not task:
            return None
        step = TaskStep(step_index=len(task.steps), description=description)
        task.steps.append(step)
        task.updated_at = _now()
        self._save_task(task)
        return step

    def start_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.status not in (TaskStatus.PENDING, TaskStatus.PAUSED):
            return False
        task.status     = TaskStatus.RUNNING
        task.started_at = task.started_at or _now()
        task.updated_at = _now()
        if task.steps:
            task.steps[task.current_step_index].status = StepStatus.RUNNING
            task.steps[task.current_step_index].started_at = _now()
        self._save_task(task)
        return True

    def complete_step(self, task_id: str,
                      step_index: int,
                      result: str = "",
                      metadata: dict = None) -> bool:
        """完成一个步骤，自动推进到下一步"""
        task = self._tasks.get(task_id)
        if not task or step_index >= len(task.steps):
            return False

        step = task.steps[step_index]
        step.status      = StepStatus.COMPLETED
        step.result      = result
        step.finished_at = _now()
        if metadata:
            step.metadata.update(metadata)

        # 推进到下一步
        next_idx = step_index + 1
        if next_idx < len(task.steps):
            task.steps[next_idx].status     = StepStatus.RUNNING
            task.steps[next_idx].started_at = _now()
        else:
            # 所有步骤完成
            task.status      = TaskStatus.COMPLETED
            task.finished_at = _now()

        task.updated_at = _now()
        self._save_task(task)
        return True

    def fail_step(self, task_id: str, step_index: int, error: str = "") -> bool:
        task = self._tasks.get(task_id)
        if not task or step_index >= len(task.steps):
            return False
        task.steps[step_index].status      = StepStatus.FAILED
        task.steps[step_index].error       = error
        task.steps[step_index].finished_at = _now()
        task.status     = TaskStatus.FAILED
        task.updated_at = _now()
        self._save_task(task)
        return True

    def pause_task(self, task_id: str, reason: str = "") -> bool:
        """暂停任务（跨会话等待）"""
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.RUNNING:
            return False
        task.status     = TaskStatus.PAUSED
        task.updated_at = _now()
        if reason:
            task.context["pause_reason"] = reason
        self._save_task(task)
        return True

    def complete_task(self, task_id: str, summary: str = "") -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status         = TaskStatus.COMPLETED
        task.finished_at    = _now()
        task.updated_at     = _now()
        task.result_summary = summary
        self._save_task(task)
        return True

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status     = TaskStatus.CANCELLED
        task.updated_at = _now()
        self._save_task(task)
        return True

    def resolve_dependency(self, task_id: str, dep_task_id: str) -> bool:
        """标记某个依赖已解除"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if dep_task_id in task.depends_on:
            task.depends_on.remove(dep_task_id)
            task.updated_at = _now()
            self._save_task(task)
        return True

    # ── 查询 ──────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: str = "",
                   key: str = "") -> list[Task]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        if key:
            tasks = [t for t in tasks if t.key == key]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def active_tasks(self) -> list[Task]:
        return self.list_tasks(status="running") + self.list_tasks(status="paused")

    def pending_tasks(self) -> list[Task]:
        return self.list_tasks(status="pending")

    def status(self) -> dict:
        """系统任务状态概览"""
        all_tasks = list(self._tasks.values())
        return {
            "total":     len(all_tasks),
            "running":   sum(1 for t in all_tasks if t.status == TaskStatus.RUNNING),
            "paused":    sum(1 for t in all_tasks if t.status == TaskStatus.PAUSED),
            "pending":   sum(1 for t in all_tasks if t.status == TaskStatus.PENDING),
            "completed": sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED),
            "failed":    sum(1 for t in all_tasks if t.status == TaskStatus.FAILED),
            "active":    [t.task_id for t in self.active_tasks()],
        }

    def handoff_summary(self) -> str:
        """生成供 handoff 使用的任务摘要"""
        active = self.active_tasks()
        pending = self.pending_tasks()
        lines = ["=== Orchestrator State ==="]

        if active:
            lines.append(f"\n进行中任务 ({len(active)}):")
            for t in active:
                lines.append(f"  [{t.status.value.upper()}] {t.task_id} — {t.title}")
                lines.append(f"    KEY: {t.key}  进度: {t.progress}")
                if t.steps:
                    cur = t.current_step_index
                    if cur < len(t.steps):
                        lines.append(f"    当前步骤: {t.steps[cur].description}")

        if pending:
            lines.append(f"\n待开始任务 ({len(pending)}):")
            for t in pending[:5]:
                lines.append(f"  {t.task_id} — {t.title} [{t.priority}]")

        return "\n".join(lines)

    # ── 持久化 ────────────────────────────────────────────────

    def _save_task(self, task: Task):
        """重写整个文件（任务数量有限，可接受）"""
        lines = []
        for t in self._tasks.values():
            lines.append(json.dumps(self._task_to_dict(t), ensure_ascii=False))
        self.tasks_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load(self):
        if not self.tasks_file.exists():
            return
        for line in self.tasks_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                task = self._task_from_dict(data)
                self._tasks[task.task_id] = task
            except Exception as e:
                logger.warning("[ORCHESTRATOR] failed to parse task line: %s", e)

    def _task_to_dict(self, t: Task) -> dict:
        return {
            "task_id":      t.task_id,
            "title":        t.title,
            "key":          t.key,
            "status":       t.status.value,
            "priority":     t.priority,
            "steps":        [
                {
                    "step_index":  s.step_index,
                    "description": s.description,
                    "status":      s.status.value,
                    "result":      s.result,
                    "started_at":  s.started_at,
                    "finished_at": s.finished_at,
                    "error":       s.error,
                    "metadata":    s.metadata,
                }
                for s in t.steps
            ],
            "created_at":   t.created_at,
            "updated_at":   t.updated_at,
            "started_at":   t.started_at,
            "finished_at":  t.finished_at,
            "created_by":   t.created_by,
            "context":      t.context,
            "depends_on":   t.depends_on,
            "result_summary": t.result_summary,
        }

    def _task_from_dict(self, data: dict) -> Task:
        task = Task(
            task_id=data["task_id"],
            title=data.get("title", ""),
            key=data.get("key", ""),
            status=TaskStatus(data.get("status", "pending")),
            priority=data.get("priority", "normal"),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""),
            created_by=data.get("created_by", "human"),
            context=data.get("context", {}),
            depends_on=data.get("depends_on", []),
            result_summary=data.get("result_summary", ""),
        )
        for s in data.get("steps", []):
            task.steps.append(TaskStep(
                step_index=s["step_index"],
                description=s["description"],
                status=StepStatus(s.get("status", "pending")),
                result=s.get("result", ""),
                started_at=s.get("started_at", ""),
                finished_at=s.get("finished_at", ""),
                error=s.get("error", ""),
                metadata=s.get("metadata", {}),
            ))
        return task

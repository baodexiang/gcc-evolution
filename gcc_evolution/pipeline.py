"""
GCC v4.4 — Task Pipeline
Multi-stage pipeline with gate checks and feedback loops.
Inspired by FARS Ideation → Planning → Experiment → Writing flow.

Pipeline stages for coding tasks:
    ANALYZE → DESIGN → IMPLEMENT → TEST → INTEGRATE

Each stage has:
    - Entry conditions (what's needed to start)
    - Exit gate (verification before proceeding)
    - Feedback loop (auto-review with max iterations)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Enums ──────────────────────────────────────────────────

class PipelineStage(str, Enum):
    PENDING = "pending"
    ANALYZE = "analyze"
    DESIGN = "design"
    IMPLEMENT = "implement"
    TEST = "test"
    INTEGRATE = "integrate"
    DONE = "done"
    FAILED = "failed"
    SUSPENDED = "suspended"


class GateResult(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


STAGE_ORDER = [
    PipelineStage.PENDING,
    PipelineStage.ANALYZE,
    PipelineStage.DESIGN,
    PipelineStage.IMPLEMENT,
    PipelineStage.TEST,
    PipelineStage.INTEGRATE,
    PipelineStage.DONE,
]


# ── Gate Check ─────────────────────────────────────────────

@dataclass
class GateCheck:
    """Single verification check within a gate."""
    name: str = ""
    passed: bool = False
    score: float = 0.0
    detail: str = ""
    required: bool = True     # if True, failure blocks progression

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": self.score,
            "detail": self.detail,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GateCheck:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GateVerification:
    """Complete gate verification for a pipeline stage."""
    stage: str = ""
    timestamp: str = field(default_factory=_now)
    checks: list[GateCheck] = field(default_factory=list)
    result: GateResult = GateResult.FAILED
    iteration: int = 1

    def evaluate(self) -> GateResult:
        """Evaluate gate: pass if all required checks pass."""
        required_checks = [c for c in self.checks if c.required]
        if not required_checks:
            self.result = GateResult.PASSED
        elif all(c.passed for c in required_checks):
            self.result = GateResult.PASSED
        elif any(c.passed for c in required_checks):
            self.result = GateResult.NEEDS_REVIEW
        else:
            self.result = GateResult.FAILED
        return self.result

    @property
    def pass_rate(self) -> float:
        if not self.checks:
            return 0.0
        return sum(1 for c in self.checks if c.passed) / len(self.checks)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "timestamp": self.timestamp,
            "checks": [c.to_dict() for c in self.checks],
            "result": self.result.value,
            "iteration": self.iteration,
            "pass_rate": round(self.pass_rate, 2),
        }

    @classmethod
    def from_dict(cls, d: dict) -> GateVerification:
        v = cls(
            stage=d.get("stage", ""),
            timestamp=d.get("timestamp", ""),
            result=GateResult(d.get("result", "failed")),
            iteration=d.get("iteration", 1),
        )
        v.checks = [GateCheck.from_dict(c) for c in d.get("checks", [])]
        return v


# ── Stage Checklists ───────────────────────────────────────

# Default checklists per stage — can be overridden in config
DEFAULT_CHECKLISTS: dict[str, list[dict]] = {
    "analyze": [
        {"name": "requirements_complete", "required": True,
         "detail": "All requirements documented with acceptance criteria"},
        {"name": "scope_defined", "required": True,
         "detail": "Task scope clearly bounded"},
        {"name": "dependencies_identified", "required": False,
         "detail": "External dependencies and blockers listed"},
    ],
    "design": [
        {"name": "requirements_coverage", "required": True,
         "detail": "Design addresses all requirements"},
        {"name": "api_compatibility", "required": True,
         "detail": "No breaking changes to existing APIs"},
        {"name": "performance_impact", "required": False,
         "detail": "Performance implications assessed"},
        {"name": "edge_cases_considered", "required": True,
         "detail": "Edge cases and error handling planned"},
    ],
    "implement": [
        {"name": "code_compiles", "required": True,
         "detail": "Code compiles/parses without errors"},
        {"name": "lint_clean", "required": True,
         "detail": "No linting errors"},
        {"name": "design_consistent", "required": True,
         "detail": "Implementation matches design document"},
        {"name": "error_handling", "required": True,
         "detail": "Proper error handling in place"},
    ],
    "test": [
        {"name": "tests_pass", "required": True,
         "detail": "All tests pass"},
        {"name": "coverage_adequate", "required": False,
         "detail": "Test coverage meets threshold"},
        {"name": "edge_cases_tested", "required": True,
         "detail": "Edge cases have test coverage"},
        {"name": "no_regressions", "required": True,
         "detail": "Existing tests still pass"},
    ],
    "integrate": [
        {"name": "no_merge_conflicts", "required": True,
         "detail": "Clean merge with target branch"},
        {"name": "dependencies_compatible", "required": True,
         "detail": "All dependencies resolve correctly"},
        {"name": "docs_updated", "required": False,
         "detail": "Documentation reflects changes"},
    ],
}


# ── Pipeline Task ──────────────────────────────────────────

@dataclass
class PipelineTask:
    """
    A task managed by the pipeline with full lifecycle tracking.
    """
    task_id: str = ""
    title: str = ""
    description: str = ""
    priority: str = "P2"      # P0-P4
    stage: PipelineStage = PipelineStage.PENDING
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # Pipeline tracking
    stage_history: list[dict] = field(default_factory=list)
    gate_results: list[dict] = field(default_factory=list)  # GateVerification dicts
    current_iteration: int = 0
    max_iterations: int = 3

    # Context
    requirements: str = ""
    design_doc: str = ""
    dependencies: list[str] = field(default_factory=list)
    key: str = ""              # GCC evolution key (Layer 1)
    module: str = ""           # v5.010: 改善要求/模块 (Layer 2, e.g. "vision-cache")

    # Metrics
    tokens_used: int = 0
    cost: float = 0.0
    started_at: str = ""
    completed_at: str = ""

    # Pipeline steps (三级结构第三层)
    steps: list[dict] = field(default_factory=list)

    def advance_stage(self) -> PipelineStage | None:
        """Move to next stage. Returns new stage or None if already done."""
        try:
            idx = STAGE_ORDER.index(self.stage)
        except ValueError:
            return None
        if idx >= len(STAGE_ORDER) - 1:
            return None
        old_stage = self.stage
        self.stage = STAGE_ORDER[idx + 1]
        self.updated_at = _now()
        self.current_iteration = 0
        self.stage_history.append({
            "from": old_stage.value,
            "to": self.stage.value,
            "at": self.updated_at,
        })
        if self.stage == PipelineStage.ANALYZE and not self.started_at:
            self.started_at = self.updated_at
        if self.stage == PipelineStage.DONE:
            self.completed_at = self.updated_at
        return self.stage

    def suspend(self, reason: str = "") -> None:
        old = self.stage
        self.stage = PipelineStage.SUSPENDED
        self.updated_at = _now()
        self.stage_history.append({
            "from": old.value, "to": "suspended",
            "at": self.updated_at, "reason": reason,
        })

    def resume(self) -> PipelineStage | None:
        """Resume from suspension, returning to previous stage."""
        if self.stage != PipelineStage.SUSPENDED:
            return None
        # Find last non-suspended stage
        for entry in reversed(self.stage_history):
            if entry["from"] != "suspended":
                self.stage = PipelineStage(entry["from"])
                self.updated_at = _now()
                self.stage_history.append({
                    "from": "suspended", "to": self.stage.value,
                    "at": self.updated_at,
                })
                return self.stage
        return None

    def fail(self, reason: str = "") -> None:
        old = self.stage
        self.stage = PipelineStage.FAILED
        self.updated_at = _now()
        self.stage_history.append({
            "from": old.value, "to": "failed",
            "at": self.updated_at, "reason": reason,
        })

    def add_gate_result(self, gate: GateVerification) -> None:
        self.gate_results.append(gate.to_dict())
        self.current_iteration = gate.iteration

    @property
    def duration_sec(self) -> int:
        if not self.started_at:
            return 0
        end = self.completed_at or _now()
        try:
            start = datetime.fromisoformat(self.started_at)
            finish = datetime.fromisoformat(end)
            return int((finish - start).total_seconds())
        except (ValueError, TypeError):
            return 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "stage": self.stage.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stage_history": self.stage_history,
            "gate_results": self.gate_results,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "requirements": self.requirements,
            "design_doc": self.design_doc,
            "dependencies": self.dependencies,
            "key": self.key,
            "module": self.module,
            "tokens_used": self.tokens_used,
            "cost": self.cost,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "steps": self.steps,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PipelineTask:
        t = cls(
            task_id=d.get("task_id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            priority=d.get("priority", "P2"),
            stage=PipelineStage(d.get("stage", "pending")),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            stage_history=d.get("stage_history", []),
            gate_results=d.get("gate_results", []),
            current_iteration=d.get("current_iteration", 0),
            max_iterations=d.get("max_iterations", 3),
            requirements=d.get("requirements", ""),
            design_doc=d.get("design_doc", ""),
            dependencies=d.get("dependencies", []),
            key=d.get("key", ""),
            module=d.get("module", ""),
            tokens_used=d.get("tokens_used", 0),
            cost=d.get("cost", 0.0),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            steps=d.get("steps", []),
        )
        return t


# ── Pipeline Manager ───────────────────────────────────────

class TaskPipeline:
    """
    Manages the task queue and pipeline execution.
    Persists state to .gcc/pipeline/ directory.
    """

    PIPELINE_DIR = ".gcc/pipeline"
    TASKS_FILE = ".gcc/pipeline/tasks.json"

    def __init__(self, max_concurrent: int = 3, gate_strict: bool = True):
        self.max_concurrent = max_concurrent
        self.gate_strict = gate_strict
        self.tasks: dict[str, PipelineTask] = {}
        self._counter = 0
        self._load()

    def _load(self) -> None:
        """Load tasks from disk."""
        path = Path(self.TASKS_FILE)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception as e:
            logger.warning("[PIPELINE] load tasks.json failed: %s", e)
            return
        # 兼容两种格式: list [...] 或 dict {"tasks": [...]}
        task_list = data if isinstance(data, list) else data.get("tasks", [])
        for td in task_list:
            try:
                task = PipelineTask.from_dict(td)
                self.tasks[task.task_id] = task
            except Exception as e:
                logger.warning("[PIPELINE] skip invalid task: %s", e)
        self._counter = len(self.tasks) if isinstance(data, list) else data.get("counter", len(self.tasks))

    def _save(self) -> None:
        """Persist tasks to disk."""
        path = Path(self.TASKS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "4.4",
            "counter": self._counter,
            "tasks": [t.to_dict() for t in self.tasks.values()],
        }
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Task Management ────────────────────────────────────

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "P2",
        requirements: str = "",
        key: str = "",
        dependencies: list[str] | None = None,
    ) -> PipelineTask:
        """Create a new pipeline task."""
        self._counter += 1
        task_id = f"GCC-{self._counter:04d}"
        task = PipelineTask(
            task_id=task_id,
            title=title,
            description=description,
            priority=priority,
            requirements=requirements,
            key=key,
            dependencies=dependencies or [],
        )
        self.tasks[task_id] = task
        self._save()
        return task

    def get_task(self, task_id: str) -> PipelineTask | None:
        return self.tasks.get(task_id)

    def get_active(self) -> list[PipelineTask]:
        """Get tasks currently in progress (not pending, done, failed, or suspended)."""
        active_stages = {
            PipelineStage.ANALYZE, PipelineStage.DESIGN,
            PipelineStage.IMPLEMENT, PipelineStage.TEST,
            PipelineStage.INTEGRATE,
        }
        return [t for t in self.tasks.values() if t.stage in active_stages]

    def get_next(self) -> PipelineTask | None:
        """Get next task to work on based on priority and dependencies."""
        pending = [
            t for t in self.tasks.values()
            if t.stage == PipelineStage.PENDING
        ]
        if not pending:
            return None

        # Check concurrent limit
        active = self.get_active()
        if len(active) >= self.max_concurrent:
            return None

        # Sort by priority (P0 first), then creation time
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
        pending.sort(key=lambda t: (
            priority_order.get(t.priority, 5),
            t.created_at,
        ))

        # Check dependencies
        for task in pending:
            if self._deps_met(task):
                return task
        return None

    def _deps_met(self, task: PipelineTask) -> bool:
        """Check if all dependencies are completed."""
        for dep_id in task.dependencies:
            dep = self.tasks.get(dep_id)
            if not dep or dep.stage != PipelineStage.DONE:
                return False
        return True

    # ── Stage Progression ──────────────────────────────────

    def advance(self, task_id: str) -> PipelineStage | None:
        """Advance a task to its next stage."""
        task = self.tasks.get(task_id)
        if not task:
            return None
        result = task.advance_stage()
        self._save()
        return result

    def run_gate(self, task_id: str,
                 check_results: list[dict] | None = None) -> GateVerification:
        """
        Run gate verification for current stage.
        check_results: list of {"name": str, "passed": bool, "score": float, "detail": str}
        If not provided, uses default checklist with all-pass (for manual override).
        """
        task = self.tasks.get(task_id)
        if not task:
            return GateVerification(result=GateResult.FAILED)

        stage_name = task.stage.value
        task.current_iteration += 1

        # Build checks
        checks = []
        if check_results:
            for cr in check_results:
                checks.append(GateCheck(
                    name=cr.get("name", ""),
                    passed=cr.get("passed", False),
                    score=cr.get("score", 0.0),
                    detail=cr.get("detail", ""),
                    required=cr.get("required", True),
                ))
        else:
            # Default: use checklist template
            checklist = DEFAULT_CHECKLISTS.get(stage_name, [])
            for item in checklist:
                checks.append(GateCheck(
                    name=item["name"],
                    passed=True,  # default pass for manual mode
                    required=item.get("required", True),
                    detail=item.get("detail", ""),
                ))

        gate = GateVerification(
            stage=stage_name,
            checks=checks,
            iteration=task.current_iteration,
        )
        gate.evaluate()
        task.add_gate_result(gate)
        self._save()

        # Save verification file
        self._save_verification(task, gate)

        return gate

    def _save_verification(self, task: PipelineTask, gate: GateVerification) -> None:
        """Save gate verification to .gcc/verification/ directory."""
        ver_dir = Path(".gcc/verification")
        ver_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{task.task_id}_{gate.stage}_v{gate.iteration}.json"
        path = ver_dir / filename
        data = {
            "task_id": task.task_id,
            "task_title": task.title,
            **gate.to_dict(),
        }
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def should_retry(self, task_id: str) -> bool:
        """Check if task can retry current stage (under max iterations)."""
        task = self.tasks.get(task_id)
        if not task:
            return False
        return task.current_iteration < task.max_iterations

    # ── Queue Summary ──────────────────────────────────────

    def summary(self) -> dict:
        """Pipeline status summary."""
        by_stage: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        by_key: dict[str, dict[str, int]] = {}
        for t in self.tasks.values():
            by_stage[t.stage.value] = by_stage.get(t.stage.value, 0) + 1
            by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
            # 按 KEY 拆分统计（仅统计 key 非空的任务）
            if t.key:
                if t.key not in by_key:
                    by_key[t.key] = {"total": 0, "completed": 0}
                by_key[t.key]["total"] += 1
                if t.stage == PipelineStage.DONE:
                    by_key[t.key]["completed"] += 1

        total_tokens = sum(t.tokens_used for t in self.tasks.values())
        total_cost = sum(t.cost for t in self.tasks.values())
        completed = [t for t in self.tasks.values() if t.stage == PipelineStage.DONE]
        avg_duration = 0
        if completed:
            avg_duration = sum(t.duration_sec for t in completed) // len(completed)

        # 计算全局完成率
        completion_rate = 0.0
        if len(self.tasks) > 0:
            completion_rate = len(completed) / len(self.tasks)

        return {
            "total_tasks": len(self.tasks),
            "by_stage": by_stage,
            "by_priority": by_priority,
            "by_key": by_key,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 2),
            "completed": len(completed),
            "avg_duration_sec": avg_duration,
            "completion_rate": round(completion_rate, 2),
        }

    def stale_tasks(self, days: int = 7) -> list[str]:
        """
        返回非终态且 updated_at 距今 >= days 天的 task_id 列表。
        用于检测长期停滞的任务。
        """
        stale = []
        now = datetime.now(timezone.utc)
        for task_id, task in self.tasks.items():
            # 跳过已完成或已暂停的任务
            if task.stage in [PipelineStage.DONE, PipelineStage.SUSPENDED]:
                continue
            # 解析 updated_at，计算时间差
            try:
                updated = datetime.fromisoformat(task.updated_at.replace('Z', '+00:00'))
                delta_days = (now - updated).days
                if delta_days >= days:
                    stale.append(task_id)
            except Exception:
                # 如果解析失败，跳过
                pass
        return stale

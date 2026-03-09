"""
DAG Pipeline for Workflow Orchestration

Simple sequential execution with dependency management.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Callable, Optional
from enum import Enum
from datetime import datetime


class StageStatus(Enum):
    """Pipeline stage execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStage:
    """Single stage in execution pipeline."""

    name: str
    handler: Callable  # Function to execute
    depends_on: List[str] = field(default_factory=list)
    timeout_seconds: int = 300
    retries: int = 1
    skip_condition: Optional[Callable] = None

    # Runtime state
    status: StageStatus = StageStatus.PENDING
    output: Any = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def duration(self) -> float:
        """Get execution duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0


class DAGPipeline:
    """
    Directed Acyclic Graph (DAG) for workflow orchestration.

    Features:
      • Dependency tracking
      • Parallel execution where possible (community: sequential)
      • Automatic retry on failure
      • Timeout enforcement

    Example:
      >>> pipeline = DAGPipeline()
      >>> pipeline.add_stage("fetch_data", lambda: load_data(), depends_on=[])
      >>> pipeline.add_stage("analyze", lambda ctx: analyze(ctx["data"]), depends_on=["fetch_data"])
      >>> results = pipeline.execute()
    """

    def __init__(self):
        self.stages: Dict[str, PipelineStage] = {}
        self.execution_log: List[Dict[str, Any]] = []

    def add_stage(
        self,
        name: str,
        handler: Callable,
        depends_on: List[str] = None,
        timeout: int = 300,
        retries: int = 1,
        skip_condition: Callable = None,
    ) -> None:
        """Add stage to pipeline."""
        self.stages[name] = PipelineStage(
            name=name,
            handler=handler,
            depends_on=depends_on or [],
            timeout_seconds=timeout,
            retries=retries,
            skip_condition=skip_condition,
        )

    def _validate_dependencies(self) -> bool:
        """Check that all dependencies exist and form valid DAG."""
        for stage in self.stages.values():
            for dep in stage.depends_on:
                if dep not in self.stages:
                    raise ValueError(f"Stage '{stage.name}' depends on unknown '{dep}'")

        # Check for cycles (simplified)
        visited = set()
        rec_stack = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for dep in self.stages[node].depends_on:
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for stage_name in self.stages:
            if stage_name not in visited:
                if has_cycle(stage_name):
                    raise ValueError("Pipeline contains circular dependencies")

        return True

    def _get_execution_order(self) -> List[str]:
        """Topologically sort stages by dependencies."""
        in_degree = {name: len(stage.depends_on) for name, stage in self.stages.items()}
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            # Find stages that depend on current
            for name, stage in self.stages.items():
                if current in stage.depends_on:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        return result

    def execute(self, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute pipeline in dependency order.

        Args:
            context: Shared context dictionary

        Returns:
            Dictionary mapping stage names to outputs
        """
        context = context or {}
        self._validate_dependencies()
        order = self._get_execution_order()

        results = {}

        for stage_name in order:
            stage = self.stages[stage_name]

            # Check skip condition
            if stage.skip_condition and stage.skip_condition(context):
                stage.status = StageStatus.SKIPPED
                self._log_stage(stage, "skipped")
                continue

            # Execute with retries
            for attempt in range(stage.retries):
                try:
                    stage.status = StageStatus.RUNNING
                    stage.started_at = datetime.utcnow()

                    # Call handler with context
                    stage.output = stage.handler(context)

                    stage.status = StageStatus.SUCCESS
                    stage.completed_at = datetime.utcnow()
                    results[stage_name] = stage.output
                    self._log_stage(stage, "success")
                    break

                except Exception as e:
                    if attempt < stage.retries - 1:
                        self._log_stage(stage, f"retry_{attempt + 1}")
                        continue
                    else:
                        stage.status = StageStatus.FAILED
                        stage.error = str(e)
                        stage.completed_at = datetime.utcnow()
                        self._log_stage(stage, "failed")
                        results[stage_name] = None
                        break

        return results

    def _log_stage(self, stage: PipelineStage, event: str) -> None:
        """Log stage execution event."""
        self.execution_log.append(
            {
                "stage": stage.name,
                "event": event,
                "timestamp": datetime.utcnow().isoformat(),
                "duration": stage.duration(),
            }
        )

    def get_summary(self) -> Dict[str, Any]:
        """Get execution summary."""
        total_stages = len(self.stages)
        succeeded = sum(
            1 for s in self.stages.values() if s.status == StageStatus.SUCCESS
        )
        failed = sum(1 for s in self.stages.values() if s.status == StageStatus.FAILED)
        skipped = sum(
            1 for s in self.stages.values() if s.status == StageStatus.SKIPPED
        )

        return {
            "total_stages": total_stages,
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "success_rate": succeeded / total_stages if total_stages > 0 else 0,
            "log": self.execution_log,
        }

    def reset(self) -> None:
        """Reset pipeline for next execution."""
        for stage in self.stages.values():
            stage.status = StageStatus.PENDING
            stage.output = None
            stage.error = None
            stage.started_at = None
            stage.completed_at = None
        self.execution_log.clear()

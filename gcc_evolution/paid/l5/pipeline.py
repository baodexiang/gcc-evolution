"""Canonical paid L5 program: orchestration pipeline."""
from ...L5_orchestration.pipeline import DAGPipeline as LegacyDAGPipeline, PipelineStage
from ...enterprise.adaptive_dag import *  # noqa: F401,F403


class DAGPipeline(LegacyDAGPipeline):
    """Canonical paid-core wrapper for orchestration pipelines."""


__all__ = ["DAGPipeline", "PipelineStage"]

"""
gcc-evo - AI Self-Evolution Engine v5.401

Open-source framework for LLM agent persistent memory + continuous learning.

License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Canonical v5.401 split:
  UI: free
  L0: free foundation layer
  L1: free foundation layer
  L2: free foundation layer
  L3: free foundation layer
  L4: paid core
  L5: paid core
  DA: paid core

Commercial enhancement modules may still exist under paid/l0-l3,
but the release-facing core split is Free 5 layers + Paid 3 layers.

This package keeps root import lightweight. Public symbols are resolved lazily
so basic commands such as `gcc-evo version` do not fail during package import.
"""

from importlib import import_module

__version__ = "5.401"
__author__ = "baodexiang"
__license__ = "BUSL-1.1"

_LAZY_EXPORTS = {
    'SessionConfig': ('gcc_evolution.free.l0.session_config', 'SessionConfig'),
    'run_setup_wizard': ('gcc_evolution.free.l0.setup_wizard', 'run_setup_wizard'),
    'evaluate_l0_governance': ('gcc_evolution.free.l0.governance', 'evaluate_l0_governance'),
    'format_governance_summary': ('gcc_evolution.free.l0.governance', 'format_governance_summary'),
    'load_governance_state': ('gcc_evolution.free.l0.governance', 'load_governance_state'),
    'save_governance_state': ('gcc_evolution.free.l0.governance', 'save_governance_state'),
    'scaffold_required_artifacts': ('gcc_evolution.free.l0.governance', 'scaffold_required_artifacts'),
    'set_prerequisite_status': ('gcc_evolution.free.l0.governance', 'set_prerequisite_status'),
    'SensoryMemory': ('gcc_evolution.free.l1', 'SensoryMemory'),
    'ShortTermMemory': ('gcc_evolution.free.l1', 'ShortTermMemory'),
    'LongTermMemory': ('gcc_evolution.free.l1', 'LongTermMemory'),
    'JSONStorage': ('gcc_evolution.free.l1', 'JSONStorage'),
    'SQLiteStorage': ('gcc_evolution.free.l1', 'SQLiteStorage'),
    'HybridRetriever': ('gcc_evolution.free.l2', 'HybridRetriever'),
    'SemanticRetriever': ('gcc_evolution.free.l2', 'SemanticRetriever'),
    'KeywordRetriever': ('gcc_evolution.free.l2', 'KeywordRetriever'),
    'RAGPipeline': ('gcc_evolution.free.l2', 'RAGPipeline'),
    'ExperienceDistiller': ('gcc_evolution.free.l3', 'ExperienceDistiller'),
    'CardGenerator': ('gcc_evolution.free.l3', 'CardGenerator'),
    'ExperienceCard': ('gcc_evolution.free.l3', 'ExperienceCard'),
    'CardType': ('gcc_evolution.free.l3', 'CardType'),
    'SkepticValidator': ('gcc_evolution.paid.l4', 'SkepticValidator'),
    'ValidationResult': ('gcc_evolution.paid.l4', 'ValidationResult'),
    'MultiModelEnsemble': ('gcc_evolution.paid.l4', 'MultiModelEnsemble'),
    'ModelPrediction': ('gcc_evolution.paid.l4', 'ModelPrediction'),
    'DAGPipeline': ('gcc_evolution.paid.l5', 'DAGPipeline'),
    'PipelineStage': ('gcc_evolution.paid.l5', 'PipelineStage'),
    'SelfImprovementLoop': ('gcc_evolution.paid.l5', 'SelfImprovementLoop'),
    'LoopPhase': ('gcc_evolution.paid.l5', 'LoopPhase'),
    'EventBus': ('gcc_evolution.free.ui', 'EventBus'),
    'GCCEvent': ('gcc_evolution.free.ui', 'GCCEvent'),
    'LayerEmitter': ('gcc_evolution.free.ui', 'LayerEmitter'),
    'RunTracer': ('gcc_evolution.free.ui', 'RunTracer'),
    'Tracer': ('gcc_evolution.free.ui', 'Tracer'),
    'DashboardServer': ('gcc_evolution.free.ui', 'DashboardServer'),
    'DirectionAnchor': ('gcc_evolution.paid.da', 'DirectionAnchor'),
    'PrincipleSet': ('gcc_evolution.paid.da', 'PrincipleSet'),
    'LAYER_TIER_MATRIX': ('gcc_evolution.layer_manifest', 'LAYER_TIER_MATRIX'),
    'canonical_layers': ('gcc_evolution.layer_manifest', 'canonical_layers'),
}

__all__ = [
    '__version__', '__author__', '__license__',
    'SessionConfig', 'run_setup_wizard',
    'evaluate_l0_governance', 'format_governance_summary',
    'load_governance_state', 'save_governance_state',
    'scaffold_required_artifacts', 'set_prerequisite_status',
    'SensoryMemory', 'ShortTermMemory', 'LongTermMemory',
    'JSONStorage', 'SQLiteStorage',
    'HybridRetriever', 'SemanticRetriever', 'KeywordRetriever', 'RAGPipeline',
    'ExperienceDistiller', 'CardGenerator', 'ExperienceCard', 'CardType',
    'SkepticValidator', 'ValidationResult', 'MultiModelEnsemble', 'ModelPrediction',
    'DAGPipeline', 'PipelineStage', 'SelfImprovementLoop', 'LoopPhase',
    'EventBus', 'GCCEvent', 'LayerEmitter', 'RunTracer', 'Tracer', 'DashboardServer',
    'DirectionAnchor', 'PrincipleSet', 'LAYER_TIER_MATRIX', 'canonical_layers',
    'free', 'paid',
]


def __getattr__(name):
    if name in ('free', 'paid'):
        return import_module(f'gcc_evolution.{name}')
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        module = import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(name)


# ═══════════════════════════════════════════════════════════════════
# IRS-001~008: GCC Theoretical Framework v2.0 open-source interfaces
# GCC-0241 (Apache 2.0)
# ═══════════════════════════════════════════════════════════════════
from .mem_action import (
    MemAction, MemActionStatus, MemActionRequest, MemActionResult,
    MemoryPolicy, MemActionLog, PollutionGuard,
)
from .retrieval_policy import (
    RetrievalStrategy, RetrievalTrigger, RetrievalRequest, RetrievalDecision,
    CounterfactualEstimate, RetrievalGate, SimpleThresholdGate, RetrievalStats,
)
from .direction_anchor import (
    DACode, DAContext, DACheckResult, DAViolation, DABlockedError,
    DirectionAnchorValidator,
)
from .da_audit import (
    DAViolationRecord, DAViolationLog, DANotifyHook, DATransitionGuard, TransitionResult,
)
from .holdout import (
    HoldoutSplitter, SkepticGate, SkepticAccessError, OverfitDetector,
    OverfitCheckResult, WalkForwardWindow, SkepticVerdict, SkepticMonitor,
)
from .fault_tolerance import (
    PhaseStatus, PhaseResult, HeartbeatRecord, RetryPolicy,
    FaultIsolator, PhaseGuard, HeartbeatMonitor,
)
from .shapley import (
    ShapleyValue, MonteCarloShapley, ShapleySnapshot, ShapleyLog,
)
from .divergence_monitor import (
    VoteRecord, PerturbationRecord, FleissKappaCalculator,
    DivergenceMonitor, PerturbationLog,
)
from .reasoning_trace import (
    TraceRecord, ReasoningTraceLog, TraceQuery, REASONING_TRACE_DDL,
)

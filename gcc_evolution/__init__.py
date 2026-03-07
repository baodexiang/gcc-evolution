"""
gcc-evo - AI Self-Evolution Engine v5.325

Open-source framework for LLM agent persistent memory + continuous learning.

License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Canonical v5.325 split:
  UI: free
  L0: Phase 1 free, Phase 2-4 paid
  L1: base free, full paid
  L2: base free, full paid
  L3: base free, full paid
  L4: paid
  L5: base free, full paid
  DA: paid

Legacy packages remain temporarily for backward compatibility:
  L0_setup, L1_memory, L2_retrieval, L3_distillation, L4_decision,
  L5_orchestration, observer, direction_anchor
"""

__version__ = "5.325"
__author__ = "baodexiang"
__license__ = "BUSL-1.1"

from .free.l0.session_config import SessionConfig
from .free.l0.setup_wizard import run_setup_wizard
from .free.l0.governance import (
    evaluate_l0_governance,
    format_governance_summary,
    load_governance_state,
    save_governance_state,
    scaffold_required_artifacts,
    set_prerequisite_status,
)
from . import free, paid
from .layer_manifest import LAYER_TIER_MATRIX, canonical_layers

from .free.l1 import SensoryMemory, ShortTermMemory, LongTermMemory
from .free.l1 import JSONStorage, SQLiteStorage

from .free.l2 import HybridRetriever, SemanticRetriever, KeywordRetriever
from .free.l2 import RAGPipeline

from .free.l3 import ExperienceDistiller, CardGenerator
from .free.l3 import ExperienceCard, CardType

from .paid.l4 import SkepticValidator, ValidationResult
from .paid.l4 import MultiModelEnsemble, ModelPrediction

from .free.l5 import DAGPipeline, PipelineStage
from .free.l5 import SelfImprovementLoop, LoopPhase

from .free.ui import EventBus, GCCEvent, LayerEmitter, RunTracer, Tracer
from .free.ui import DashboardServer

from .paid.da import DirectionAnchor, PrincipleSet

__all__ = [
    "SessionConfig", "run_setup_wizard",
    "evaluate_l0_governance", "format_governance_summary",
    "load_governance_state", "save_governance_state",
    "scaffold_required_artifacts", "set_prerequisite_status",
    "free", "paid", "LAYER_TIER_MATRIX", "canonical_layers",
    "SensoryMemory", "ShortTermMemory", "LongTermMemory",
    "JSONStorage", "SQLiteStorage",
    "HybridRetriever", "SemanticRetriever", "KeywordRetriever",
    "RAGPipeline",
    "ExperienceDistiller", "CardGenerator",
    "ExperienceCard", "CardType",
    "SkepticValidator", "ValidationResult",
    "MultiModelEnsemble", "ModelPrediction",
    "DAGPipeline", "PipelineStage",
    "SelfImprovementLoop", "LoopPhase",
    "EventBus", "GCCEvent", "LayerEmitter", "RunTracer", "Tracer",
    "DashboardServer",
    "DirectionAnchor", "PrincipleSet",
]

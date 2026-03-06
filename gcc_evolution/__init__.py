"""
gcc-evo â€” AI Self-Evolution Engine v5.310

Open-source framework for LLM agent persistent memory + continuous learning.

License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Layers:
  L0: Setup (session config + L0 gate before loop)
  L1: Memory (persistent 3-tier storage)
  L2: Retrieval (hybrid semantic + temporal + keyword)
  L3: Distillation (experience cards + SkillBank)
  L4: Decision (skeptic gate + multi-model ensemble)
  L5: Orchestration (6-step loop + DAG pipeline)
  L6: Observation (EventBus + SSE Dashboard + RunTracer)
  Direction Anchor (constitutional principles)
"""

__version__ = "5.310"
__author__ = "baodexiang"
__license__ = "BUSL-1.1"

# L0: Setup
from .session_config import SessionConfig
from .setup_wizard import run_setup_wizard

# L1: Memory
from .L1_memory import SensoryMemory, ShortTermMemory, LongTermMemory
from .L1_memory import JSONStorage, SQLiteStorage

# L2: Retrieval
from .L2_retrieval import HybridRetriever, SemanticRetriever, KeywordRetriever
from .L2_retrieval import RAGPipeline

# L3: Distillation
from .L3_distillation import ExperienceDistiller, CardGenerator
from .L3_distillation import ExperienceCard, CardType

# L4: Decision
from .L4_decision import SkepticValidator, ValidationResult
from .L4_decision import MultiModelEnsemble, ModelPrediction

# L5: Orchestration
from .L5_orchestration import DAGPipeline, PipelineStage
from .L5_orchestration import SelfImprovementLoop, LoopPhase

# L6: Observation
from .observer import EventBus, GCCEvent, LayerEmitter, RunTracer, Tracer
from .dashboard_server import DashboardServer

# Direction Anchor
from .direction_anchor import DirectionAnchor, PrincipleSet

__all__ = [
    # L0
    "SessionConfig", "run_setup_wizard",
    # L1
    "SensoryMemory", "ShortTermMemory", "LongTermMemory",
    "JSONStorage", "SQLiteStorage",
    # L2
    "HybridRetriever", "SemanticRetriever", "KeywordRetriever",
    "RAGPipeline",
    # L3
    "ExperienceDistiller", "CardGenerator",
    "ExperienceCard", "CardType",
    # L4
    "SkepticValidator", "ValidationResult",
    "MultiModelEnsemble", "ModelPrediction",
    # L5
    "DAGPipeline", "PipelineStage",
    "SelfImprovementLoop", "LoopPhase",
    # L6
    "EventBus", "GCCEvent", "LayerEmitter", "RunTracer", "Tracer",
    "DashboardServer",
    # Anchor
    "DirectionAnchor", "PrincipleSet",
]



"""
gcc-evo — AI Self-Evolution Engine v5.295

Open-source framework for LLM agent persistent memory + continuous learning.

License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Layers:
  L1: Memory (persistent 3-tier storage)
  L2: Retrieval (hybrid semantic + temporal + keyword)
  L3: Distillation (experience cards + SkillBank)
  L4: Decision (skeptic gate + multi-model ensemble)
  L5: Orchestration (6-step loop + DAG pipeline)
  Direction Anchor (constitutional principles)
"""

__version__ = "5.295"
__author__ = "baodexiang"
__license__ = "BUSL-1.1"

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

# Direction Anchor
from .direction_anchor import DirectionAnchor, PrincipleSet

__all__ = [
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
    # Anchor
    "DirectionAnchor", "PrincipleSet",
]

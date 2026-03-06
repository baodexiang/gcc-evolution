"""
GCC v4.95 — Agentic AI Layer with Hierarchical Memory, RAG Retrieval & SkillBank
从被动记录到主动进化：跨会话记忆闭环 + 双通道约束 + 方向可控进化

v4.96: + gcc-evo dashboard（单文件 HTML 看板，自动内嵌 .gcc/ 数据，零依赖浏览器打开）
v4.93: + RESEARCH.md 审查修正（5篇内部设计标注，3篇独立收敛验证）
v4.92: v4.92 三项关键修复（skeptic/memory/crossover）
       + backtest_store (回撤历史数据基石)
       + retriever层次优先级权重 (AdaptiveNN coarse-to-fine)
       + context_chain Human Anchor主动注入与暂停
v5.000: + KEY-007 KNN六项改善(多维特征66维/自适应K/准确率反哺Retriever/Regime重排序/MAB调度器/WFO防过拟合)
v4.992: + 双KNN交叉验证+Plugin KNN反哺Vision过滤 + VP anchor optimization + Dashboard状态环固定排序
v4.991: + KEY-006 Vision Radar影子观察系统 + knn_evolve解包修复
v4.990: + 论文19Gap实施: KNN进化×GCC框架全链路打通(ContextChain/Constraints/Skeptic/Distiller/Retriever配置化)
v4.98: + KNN历史对比库(KEY-007)绑定gcc-evo进化核心, bootstrap+增量, 主程序boot共享实例
v4.8:  + context_chain (L1/L2/L3), memory_tiers (sensory/short/long)
v4.75: + migrate, improvements/, smart commit, auto-push, auto-card
v4.7:  + Skeptic deterministic gate, Watchdog auto-commit daemon
v4.6:  + Constraints, Skill Registry, Self-Check, STATUS.md
v4.5:  Smart handoff + params
"""

__version__ = "5.305"

from .models import (
    CardStatus,
    ExperienceCard,
    ExperienceType,
    MemoryDiagnostic,
    SessionTrajectory,
    TrajectoryEvaluation,
    TrajectoryStep,
)
from .normalizer import Normalizer
from .session_manager import SessionManager
from .handoff import HandoffProtocol, HandoffManifest, HandoffTask
from .pipeline import TaskPipeline, PipelineTask, PipelineStage, GateVerification
from .params import ParamStore, ParamGate, ParamGateResult
from .constraints import Constraint, ConstraintStore
from .skill_registry import SkillRegistry, SkillResult
from .selfcheck import run_self_check, generate_status_md
from .human_anchor import HumanAnchor, HumanAnchorStore, AnchorPauseSignal, NLQParser
try:
    from .backtest_store import (
        TradeEvent, BacktestStore,
        CounterfactualEngine, CounterfactualResult,
        DrawdownAnalyzer, DrawdownAttribution, PatternStats,
    )
except (ImportError, AttributeError):
    pass  # backtest_store 部分符号缺失时降级跳过

__all__ = [
    "CardStatus",
    "MemoryDiagnostic",
    "Normalizer",
    "SessionManager",
    "ExperienceCard",
    "ExperienceType",
    "SessionTrajectory",
    "TrajectoryEvaluation",
    "TrajectoryStep",
    "HandoffProtocol",
    "HandoffManifest",
    "HandoffTask",
    "TaskPipeline",
    "PipelineTask",
    "PipelineStage",
    "GateVerification",
    "ParamStore",
    "ParamGate",
    "ParamGateResult",
    "Constraint",
    "ConstraintStore",
    "SkillRegistry",
    "SkillResult",
    "run_self_check",
    "generate_status_md",
    # v4.85
    "HumanAnchor",
    "HumanAnchorStore",
    "AnchorPauseSignal",
    "NLQParser",
    "TradeEvent",
    "BacktestStore",
    "CounterfactualEngine",
    "CounterfactualResult",
    "DrawdownAnalyzer",
    "DrawdownAttribution",
    "PatternStats",
]

from gcc_evolution.gcc_db import GccDb, auto_import

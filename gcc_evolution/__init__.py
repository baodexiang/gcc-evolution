"""
GCC v5.295 — Agentic AI Layer with Hierarchical Memory, RAG Retrieval & SkillBank
从被动记录到主动进化：跨会话记忆闭环 + 双通道约束 + 方向可控进化 + 五层框架

v5.295: GCC-0197 外挂信号准确率闭环(plugin_accuracy→经验卡增强+retrospective信号维度+dashboard注入)
v5.290: gcc-evo loop闭环命令(绑定GCC任务+Audit+Distill+Rules+Dashboard) + KEY-009 fixed标记+每日distill自动化
v5.280: GCC-0155 开源代码清理(交易专用文件分离+通用引擎logging补全+静默异常P0归零)
v5.250: KEY-007 KNN gcc-evo双向闭环(GCC-0190~0192经验卡/反向调参/人类锚点) + L2深度审计(GCC-0189)
v5.210: GCC-0184~0186 L1数据模型+L2幻觉防护(FactSelfCheck)+L3数据优化筛选+五层核心指标
v5.200: GCC-0175 REQ-01~10自进化引擎 + GCC-0174 CardBridge因果记忆 + GCC-0171管线审计
v5.190: KEY-008 代码品质强化 — bare except硬化142处+P1全5项+P2全4项完成
        LLM retry指数退避+建议冲突检测+跨卡一致性检验+SkillBank接口对齐+Knowledge LLM修正+Crossover放宽
v5.180: KEY-008 bare except hardening — gcc_evolution/全35文件142处except细化
v5.150: KEY-007 全量同步 — 73项task完成(P0/P1/P2 final-review + 10模块审查 + Prompt Repetition)
v5.050: KEY-007 23项论文驱动改善完成 (GA/StockMem/THGNN/SF-SEP/SkillRL)
        P0: importance评分+causal triplet+cross_key检索+TYPE_WEIGHTS+exp衰减+幻觉门控+s⁻蒸馏
        P1: increment_use+reflection+权重重构+skeptic失败追踪+delta z-score+市场状态+eval忠实度+grounding+embedding检索+KEY成功率
        P2: 相似卡片合并+多样性监控+graph展开限制+faithfulness字段+when_to_apply
v4.97: + LightMem话题分组 + ExpeL跨卡归纳 + RAG Re-ranking + SkillRL递归共进化
v4.96: + gcc-evo dashboard（单文件 HTML 看板，自动内嵌 .gcc/ 数据，零依赖浏览器打开）
v4.93: + RESEARCH.md 审查修正（5篇内部设计标注，3篇独立收敛验证）
v4.92: v4.92 三项关键修复（skeptic/memory/crossover）
       + backtest_store (回撤历史数据基石)
       + retriever层次优先级权重 (AdaptiveNN coarse-to-fine)
       + context_chain Human Anchor主动注入与暂停
v4.8:  + context_chain (L1/L2/L3), memory_tiers (sensory/short/long)
v4.75: + migrate, improvements/, smart commit, auto-push, auto-card
v4.7:  + Skeptic deterministic gate, Watchdog auto-commit daemon
v4.6:  + Constraints, Skill Registry, Self-Check, STATUS.md
v4.5:  Smart handoff + params
"""

__version__ = "5.295"

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
from .backtest_store import (
    TradeEvent, BacktestStore,
    CounterfactualEngine, CounterfactualResult,
    DrawdownAnalyzer, DrawdownAttribution, PatternStats,
)

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

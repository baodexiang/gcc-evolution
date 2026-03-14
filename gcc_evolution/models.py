"""
GCC v4.0 — Data Models
Milestone: "Quality Gate"
New: CardQuality, downstream_impact, experience graph, delta evaluation
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ── Enums ──────────────────────────────────────────────────

class ExperienceType(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    MUTATION = "mutation"
    CROSSOVER = "crossover"


class CardStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    VALIDATED = "validated"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


class StepResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    SKIP = "skip"


# ── Trajectory ─────────────────────────────────────────────

@dataclass
class TrajectoryStep:
    step_id: int = 0
    description: str = ""
    result: StepResult = StepResult.PASS
    feedback: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now)
    step_goal: str = ""  # v4.98: SkillRL步骤目标, 可从外部配置传入


@dataclass
class SessionTrajectory:
    session_id: str = field(default_factory=lambda: _uid("s_"))
    task: str = ""
    project: str = ""
    key: str = ""
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    steps: list[TrajectoryStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    plan_selected: str = ""

    def add_step(self, description: str, result: str = "pass",
                 feedback: str = "", metrics: dict | None = None) -> TrajectoryStep:
        step = TrajectoryStep(
            step_id=len(self.steps) + 1,
            description=description,
            result=StepResult(result),
            feedback=feedback,
            metrics=metrics or {},
        )
        self.steps.append(step)
        return step

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.result == StepResult.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if s.result == StepResult.FAIL)

    @property
    def efficiency(self) -> float:
        return self.passed / max(len(self.steps), 1)


# ── Evaluation ─────────────────────────────────────────────

@dataclass
class TrajectoryEvaluation:
    session_id: str = ""
    evaluated_at: str = field(default_factory=_now)

    outcome_score: float = 0.0
    efficiency_score: float = 0.0
    novelty_score: float = 0.0
    overall_score: float = 0.0

    # v4.0: delta vs previous session on same KEY
    delta_score: float = 0.0
    prev_session_id: str = ""

    key_improvements: list[str] = field(default_factory=list)
    key_regressions: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    raw_analysis: dict = field(default_factory=dict)

    def compute_overall(self, weights: dict[str, float] | None = None) -> float:
        w = weights or {"outcome": 0.5, "efficiency": 0.3, "novelty": 0.2}
        self.overall_score = round(
            self.outcome_score * w.get("outcome", 0.5)
            + self.efficiency_score * w.get("efficiency", 0.3)
            + self.novelty_score * w.get("novelty", 0.2),
            3,
        )
        return self.overall_score


# ── Card Quality Gate (v4.0) ──────────────────────────────

@dataclass
class CardQuality:
    """
    v4.0: Quality gate before card enters global memory.
    Inspired by CL-bench (17% utilization) — garbage cards are the root cause.
    """
    insight_length_ok: bool = False
    not_duplicate: bool = False
    confidence_ok: bool = False
    has_actionable_content: bool = False
    overall_pass: bool = False
    rejection_reasons: list[str] = field(default_factory=list)

    def check(self, card: ExperienceCard,
              existing_insights: list[str] | None = None) -> bool:
        """Run quality checks. Returns True if card passes gate."""
        self.rejection_reasons = []

        # Check 1: insight not trivial
        insight = card.key_insight.strip()
        self.insight_length_ok = len(insight) >= 15
        if not self.insight_length_ok:
            self.rejection_reasons.append(
                f"insight too short ({len(insight)} chars, need ≥15)")

        # Check 2: not duplicate of existing card
        self.not_duplicate = True
        if existing_insights:
            for existing in existing_insights:
                if self._word_overlap(insight, existing) > 0.70:
                    self.not_duplicate = False
                    self.rejection_reasons.append(
                        f"duplicate ({existing[:40]}...)")
                    break

        # Check 3: minimum confidence
        self.confidence_ok = card.confidence >= 0.3
        if not self.confidence_ok:
            self.rejection_reasons.append(
                f"low confidence ({card.confidence:.0%})")

        # Check 4: has actionable content (strategy, pitfalls, or revision)
        self.has_actionable_content = bool(
            (card.strategy and len(card.strategy) > 10)
            or (card.pitfalls and any(len(p) > 5 for p in card.pitfalls))
            or (card.revised_step and len(card.revised_step) > 10)
            or (card.merged_steps and len(card.merged_steps) > 0)
        )
        if not self.has_actionable_content:
            self.rejection_reasons.append("no actionable content")

        # Overall: must pass insight_length + at least 2 others
        checks = [self.not_duplicate, self.confidence_ok,
                  self.has_actionable_content]
        self.overall_pass = self.insight_length_ok and sum(checks) >= 2

        return self.overall_pass

    @staticmethod
    def _word_overlap(a: str, b: str) -> float:
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)


# ── Experience Card ────────────────────────────────────────

@dataclass
class ExperienceCard:
    """
    v4.0: + quality gate, downstream impact, experience graph
    """
    id: str = field(default_factory=lambda: _uid("exp_"))
    created_at: str = field(default_factory=_now)
    source_session: str = ""
    exp_type: ExperienceType = ExperienceType.SUCCESS

    # WHEN
    trigger_task_type: str = ""
    trigger_symptom: str = ""
    trigger_keywords: list[str] = field(default_factory=list)

    # WHAT
    strategy: str = ""
    key_insight: str = ""

    # HOW
    metrics_before: dict[str, Any] = field(default_factory=dict)
    metrics_after: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    # AVOID
    pitfalls: list[str] = field(default_factory=list)

    # v4.97 Reflexion: 失败后的语言自我反思 (#07 Reflexion NeurIPS 2023)
    self_reflection: str = ""

    # Mutation
    original_step: str = ""
    revised_step: str = ""

    # Crossover
    source_sessions: list[str] = field(default_factory=list)
    merged_steps: list[str] = field(default_factory=list)

    # Metadata
    key: str = ""
    project: str = ""
    tags: list[str] = field(default_factory=list)
    use_count: int = 0
    last_used: str = ""
    embedding: list[float] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)

    # Lifecycle
    status: CardStatus = CardStatus.DRAFT
    status_history: list[dict] = field(default_factory=list)
    source_ref: str = ""

    # Decay (AMemGym)
    last_validated: str = ""
    decay_rate: float = 0.05

    # v5.050 P2-StockMem: 因果三元组 (Skeptic失败时写入, 检索时匹配同类失败)
    causal_trigger: str = ""    # 触发条件 (key=xxx symbol=xxx)
    causal_action: str = ""     # 执行动作 (Skeptic verdict)
    causal_outcome: str = ""    # 结果 (metrics below threshold)

    # v4.0: Experience Graph (from ARG-Designer insight)
    parent_id: str = ""
    supersedes_id: str = ""
    related_ids: list[str] = field(default_factory=list)

    # v4.0: Downstream Impact (from HGM CMP)
    downstream_sessions: list[str] = field(default_factory=list)
    downstream_scores: list[float] = field(default_factory=list)
    downstream_avg: float = 0.0

    # v4.85: Hierarchical Priority (AdaptiveNN coarse-to-fine)
    layer_priority: int = 2             # 1=执行层 2=项目层 3=方向层(最高)
    is_human_anchor: bool = False       # True=Human Anchor，永不降权
    anchor_aligned: bool = True         # 是否与当前Human Anchor方向对齐
    anchor_id: str = ""                 # 关联的Human Anchor ID

    def compute_downstream_avg(self) -> float:
        if self.downstream_scores:
            self.downstream_avg = round(
                sum(self.downstream_scores) / len(self.downstream_scores), 3)
        return self.downstream_avg

    def to_context_string(self) -> str:
        icon = {
            "success": "+", "failure": "!", "partial": "~",
            "mutation": "↻", "crossover": "★",
        }[self.exp_type.value]

        status_icon = {
            "draft": "◇", "active": "○", "validated": "●",
            "archived": "◆", "deprecated": "✕",
        }.get(self.status.value, "?")

        impact = ""
        if self.downstream_scores:
            impact = f" [↑{self.downstream_avg:.0%}×{len(self.downstream_scores)}]"

        lines = [f"[{icon}|{status_icon}] {self.key_insight}{impact}"]

        if self.trigger_symptom:
            lines.append(f"    When: {self.trigger_symptom}")
        if self.strategy:
            lines.append(f"    How:  {self.strategy}")

        if self.exp_type == ExperienceType.MUTATION and self.original_step:
            lines.append(f"    Was:  {self.original_step}")
            lines.append(f"    Should: {self.revised_step}")

        if self.exp_type == ExperienceType.CROSSOVER and self.merged_steps:
            lines.append(f"    Best practice: {' → '.join(self.merged_steps)}")

        if self.pitfalls:
            lines.append(f"    Avoid: {'; '.join(self.pitfalls[:3])}")
        if self.metrics_after:
            deltas = []
            for k, v in self.metrics_after.items():
                b = self.metrics_before.get(k, "?")
                deltas.append(f"{k}: {b}→{v}")
            if deltas:
                lines.append(f"    Metrics: {', '.join(deltas)}")
        if self.attachments:
            lines.append(f"    Refs: {', '.join(self.attachments[:3])}")
        lines.append(f"    Confidence: {self.confidence:.0%}")
        return "\n".join(lines)

    def searchable_text(self) -> str:
        parts = [
            self.trigger_task_type, self.trigger_symptom,
            " ".join(self.trigger_keywords),
            self.strategy, self.key_insight,
            " ".join(self.pitfalls), " ".join(self.tags),
            self.key, self.original_step, self.revised_step,
            " ".join(self.merged_steps),
            " ".join(self.attachments),
            self.source_ref,
            # v5.050 StockMem: 因果三元组纳入检索 (同品种/同key失败模式匹配)
            self.causal_trigger, self.causal_action, self.causal_outcome,
        ]
        return " ".join(p for p in parts if p)


# ── Plan ───────────────────────────────────────────────────

@dataclass
class ImprovementPlan:
    plan_id: str = field(default_factory=lambda: _uid("plan_"))
    name: str = ""
    approach: str = ""
    reasoning: str = ""
    confidence: float = 0.0

    def to_context_string(self) -> str:
        return f"[Plan: {self.name}] {self.approach} (confidence: {self.confidence:.0%})"


# ── Memory Diagnostic ─────────────────────────────────────

@dataclass
class MemoryDiagnostic:
    write_total: int = 0
    write_success: int = 0
    write_failures: list[str] = field(default_factory=list)

    read_queries: int = 0
    read_hits: int = 0
    read_misses: list[str] = field(default_factory=list)

    util_injected: int = 0
    util_applied: int = 0
    util_ignored: list[str] = field(default_factory=list)

    # v4.0: quality gate stats
    quality_submitted: int = 0
    quality_passed: int = 0
    quality_rejected: int = 0
    quality_reasons: list[str] = field(default_factory=list)

    @property
    def write_rate(self) -> float:
        return self.write_success / max(self.write_total, 1)

    @property
    def read_rate(self) -> float:
        return self.read_hits / max(self.read_queries, 1)

    @property
    def util_rate(self) -> float:
        return self.util_applied / max(self.util_injected, 1)

    @property
    def quality_rate(self) -> float:
        return self.quality_passed / max(self.quality_submitted, 1)

    def summary(self) -> str:
        base = (
            f"Write: {self.write_success}/{self.write_total} ({self.write_rate:.0%}) | "
            f"Read: {self.read_hits}/{self.read_queries} ({self.read_rate:.0%}) | "
            f"Util: {self.util_applied}/{self.util_injected} ({self.util_rate:.0%})"
        )
        if self.quality_submitted > 0:
            base += f" | QGate: {self.quality_passed}/{self.quality_submitted}"
        return base


# ── Session Summary ────────────────────────────────────────

@dataclass
class SessionSummary:
    session_id: str = ""
    task: str = ""
    key: str = ""
    total_steps: int = 0
    passed_steps: int = 0
    failed_steps: int = 0
    evaluation: TrajectoryEvaluation = field(default_factory=TrajectoryEvaluation)
    experiences_distilled: list[ExperienceCard] = field(default_factory=list)
    mutations_generated: list[ExperienceCard] = field(default_factory=list)
    crossovers_generated: list[ExperienceCard] = field(default_factory=list)
    plans_offered: list[ImprovementPlan] = field(default_factory=list)
    experiences_used: list[str] = field(default_factory=list)

    diagnostic: MemoryDiagnostic = field(default_factory=MemoryDiagnostic)
    experience_feedback: list[dict] = field(default_factory=list)

    def format_commit_message(self) -> str:
        result = "pass" if self.evaluation.outcome_score > 0.6 else (
            "partial" if self.evaluation.outcome_score > 0.3 else "fail"
        )
        key_tag = f":{self.key}" if self.key else ""
        new_count = len(self.experiences_distilled)
        mut_count = len(self.mutations_generated)
        cross_count = len(self.crossovers_generated)
        used = ", ".join(self.experiences_used[:3]) if self.experiences_used else "none"

        lines = [
            f"[EVO{key_tag}] {self.task}",
            "",
            f"Outcome: {result} (score: {self.evaluation.overall_score:.2f})",
            f"Steps: {self.passed_steps} pass / {self.failed_steps} fail / {self.total_steps} total",
            f"Experience: +{new_count} new, {mut_count} mutations, {cross_count} crossovers | used: {used}",
        ]

        if self.evaluation.delta_score != 0:
            d = self.evaluation.delta_score
            lines.append(f"Delta: {'↑' if d > 0 else '↓'}{abs(d):.2f} vs prev")

        if self.evaluation.key_improvements:
            lines.append(f"Improved: {'; '.join(self.evaluation.key_improvements[:3])}")
        if self.evaluation.key_regressions:
            lines.append(f"Regressed: {'; '.join(self.evaluation.key_regressions[:3])}")
        if self.diagnostic.write_total > 0:
            lines.append(f"Memory: {self.diagnostic.summary()}")

        return "\n".join(lines)

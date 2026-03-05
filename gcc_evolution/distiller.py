"""
GCC v4.05 — Distiller
Extracts experience cards + trajectory mutations from sessions.
v3.7: Mutation — revises failed steps into "what should have been done"
"""

from __future__ import annotations

import json
import re

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import (
    ExperienceCard,
    ExperienceType,
    SessionTrajectory,
    StepResult,
    TrajectoryEvaluation,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class InsightCard:
    """
    v4.97 — ExpeL跨卡归纳的通用规律（#06 ExpeL AAAI 2024）。
    多张 ExperienceCard → distill_insights() → InsightCard 列表。
    可存入 SkillBank（skill_type="general"）或注入 agents.md。
    """
    insight:          str   = ""          # 一句话通用规律
    evidence_count:   int   = 1           # 支撑卡片数量
    confidence:       float = 0.7
    applies_to:       list  = field(default_factory=list)   # ["gcc", "domain"]
    tags:             list  = field(default_factory=list)
    source_card_count: int  = 0           # 参与归纳的总卡片数
    created_at:       str   = field(default_factory=_now_iso)

    def to_skill_content(self) -> str:
        """格式化为 SkillEntry.content 格式。"""
        parts = [self.insight]
        if self.evidence_count > 1:
            parts.append(f"（来自 {self.evidence_count} 次经验）")
        return " ".join(parts)[:200]

# ── Prompts ────────────────────────────────────────────────

DISTILL_SYSTEM = """You are the experience distiller for GCC v4.05.
Extract 1-3 reusable experience cards from a completed session.

Output ONLY a JSON array:
[
  {
    "type": "success|failure|partial",
    "trigger_task": "<task category>",
    "trigger_symptom": "<what the problem looked like>",
    "keywords": ["kw1", "kw2"],
    "strategy": "<what approach was used>",
    "key_insight": "<ONE actionable sentence>",
    "metrics_before": {},
    "metrics_after": {},
    "confidence": <0.0-1.0>,
    "pitfalls": ["<specific thing to avoid>"],
    "tags": ["tag1", "tag2"]
  }
]"""

DISTILL_USER = """Distill experience cards from this session:

Task: {task}
Project: {project}
Outcome score: {outcome:.2f} | Efficiency: {efficiency:.2f}

Steps:
{steps}

Evaluation insights:
  Improvements: {improvements}
  Regressions: {regressions}
  Recommendations: {recommendations}

Extract 1-3 experience cards as JSON array."""

MUTATION_SYSTEM = """You are the trajectory mutation engine for GCC v4.05.
Given a FAILED step in a coding session, generate a REVISED approach.

Output ONLY a JSON object:
{
  "original_step": "<what was done>",
  "revised_step": "<what SHOULD have been done>",
  "key_insight": "<ONE sentence: the lesson>",
  "confidence": <0.0-1.0>,
  "reasoning": "<why the revision is better>"
}"""

MUTATION_USER = """This step FAILED during task: {task}

Failed step: {step_desc}
Feedback: {feedback}

Context — other steps in the session:
{context}

What should have been done instead? Output JSON only."""


class Distiller:
    """
    v4.0: Extracts experience cards AND trajectory mutations.
    """

    def __init__(self, llm=None, project: str = ""):
        self.llm = llm
        self.project = project

    def distill(
        self,
        trajectory: SessionTrajectory,
        evaluation: TrajectoryEvaluation,
    ) -> list[ExperienceCard]:
        """Extract experience cards (success/failure/partial)."""
        cards: list[ExperienceCard] = []
        cards.extend(self._extract_from_rules(trajectory, evaluation))
        if self.llm:
            cards.extend(self._extract_with_llm(trajectory, evaluation))
        cards = self._dedupe(cards)
        for c in cards:
            c.source_session = trajectory.session_id
            c.project = self.project or trajectory.project
            c.key = trajectory.key
        return cards

    def mutate(
        self,
        trajectory: SessionTrajectory,
    ) -> list[ExperienceCard]:
        """
        v3.7: Generate mutations for failed steps.
        For each failed step, produce a "what should have been done" card.
        """
        failed_steps = [s for s in trajectory.steps if s.result == StepResult.FAIL]
        if not failed_steps:
            return []

        mutations = []

        # Context: all steps for LLM
        context_lines = []
        for s in trajectory.steps:
            icon = "✓" if s.result == StepResult.PASS else "✗"
            context_lines.append(f"  {icon} {s.description}")

        for step in failed_steps:
            if self.llm:
                card = self._mutate_with_llm(trajectory, step, "\n".join(context_lines))
            else:
                card = self._mutate_rule_based(trajectory, step)
            if card:
                card.source_session = trajectory.session_id
                card.project = self.project or trajectory.project
                card.key = trajectory.key
                mutations.append(card)

        return mutations

    # ── Mutation (LLM) ──

    def _mutate_with_llm(self, traj: SessionTrajectory,
                         step, context: str) -> ExperienceCard | None:
        prompt = MUTATION_USER.format(
            task=traj.task,
            step_desc=step.description,
            feedback=step.feedback or "(no feedback)",
            context=context,
        )
        try:
            raw = self.llm.generate(system=MUTATION_SYSTEM, user=prompt, temperature=0.3)
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            d = json.loads(text)
            return ExperienceCard(
                exp_type=ExperienceType.MUTATION,
                trigger_task_type=traj.task.split()[0] if traj.task else "",
                trigger_symptom=f"Failed: {step.description}",
                trigger_keywords=self._extract_keywords(step.description),
                strategy=d.get("revised_step", ""),
                key_insight=d.get("key_insight", f"Instead of '{step.description}', do '{d.get('revised_step','')}'"),
                original_step=d.get("original_step", step.description),
                revised_step=d.get("revised_step", ""),
                confidence=float(d.get("confidence", 0.6)),
                pitfalls=[step.description],
                tags=["mutation", "revision"],
            )
        except Exception:
            return self._mutate_rule_based(traj, step)

    # ── Mutation (rule-based fallback) ──

    def _mutate_rule_based(self, traj: SessionTrajectory, step) -> ExperienceCard:
        return ExperienceCard(
            exp_type=ExperienceType.MUTATION,
            trigger_task_type=traj.task.split()[0] if traj.task else "",
            trigger_symptom=f"Failed: {step.description}",
            trigger_keywords=self._extract_keywords(step.description),
            key_insight=f"Avoid: {step.description}" + (f" ({step.feedback})" if step.feedback else ""),
            original_step=step.description,
            revised_step=f"Find alternative to: {step.description}",
            confidence=0.5,
            pitfalls=[step.description + (f": {step.feedback}" if step.feedback else "")],
            tags=["mutation", "revision"],
        )

    # ── Rule-based distillation ──

    def _extract_from_rules(self, traj, ev) -> list[ExperienceCard]:
        cards = []

        for step in traj.steps:
            if step.result == StepResult.PASS and step.metrics:
                has_ba = any(isinstance(v, dict) and "before" in v and "after" in v
                            for v in step.metrics.values())
                if has_ba:
                    mb = {k: v["before"] for k, v in step.metrics.items()
                          if isinstance(v, dict) and "before" in v}
                    ma = {k: v["after"] for k, v in step.metrics.items()
                          if isinstance(v, dict) and "after" in v}
                    cards.append(ExperienceCard(
                        exp_type=ExperienceType.SUCCESS,
                        trigger_task_type=traj.task.split()[0] if traj.task else "",
                        trigger_symptom=f"Step: {step.description}",
                        trigger_keywords=self._extract_keywords(step.description),
                        strategy=step.description,
                        key_insight=f"Approach worked: {step.description}",
                        metrics_before=mb, metrics_after=ma,
                        confidence=0.8,
                        tags=self._extract_keywords(step.description),
                    ))

        failed = [s for s in traj.steps if s.result == StepResult.FAIL]
        if failed:
            pitfalls = [f.description + (f" ({f.feedback})" if f.feedback else "") for f in failed[:5]]
            cards.append(ExperienceCard(
                exp_type=ExperienceType.FAILURE,
                trigger_task_type=traj.task.split()[0] if traj.task else "",
                trigger_symptom=f"{len(failed)} steps failed during: {traj.task}",
                trigger_keywords=["failure", "avoid"] + self._extract_keywords(traj.task),
                key_insight=f"Avoid: {failed[0].description}",
                confidence=0.7,
                pitfalls=pitfalls,
                tags=["failure", "pitfall"],
            ))

        if ev.overall_score > 0.6 and not cards:
            cards.append(ExperienceCard(
                exp_type=ExperienceType.SUCCESS,
                trigger_task_type=traj.task.split()[0] if traj.task else "",
                trigger_symptom=traj.task,
                trigger_keywords=self._extract_keywords(traj.task),
                strategy=f"Session approach for: {traj.task}",
                key_insight=(ev.key_improvements[0] if ev.key_improvements
                            else f"Completed: {traj.task}"),
                confidence=ev.overall_score,
                tags=self._extract_keywords(traj.task),
            ))

        return cards

    # ── LLM distillation ──

    def _extract_with_llm(self, traj, ev) -> list[ExperienceCard]:
        if not self.llm:
            return []
        steps_text = []
        for s in traj.steps:
            line = f"  {s.step_id}. [{s.result.value}] {s.description}"
            if s.feedback:
                line += f"  (feedback: {s.feedback})"
            if s.metrics:
                line += f"  metrics: {json.dumps(s.metrics)}"
            steps_text.append(line)

        prompt = DISTILL_USER.format(
            task=traj.task, project=traj.project or self.project,
            outcome=ev.outcome_score, efficiency=ev.efficiency_score,
            steps="\n".join(steps_text) or "(no steps)",
            improvements="; ".join(ev.key_improvements) or "none",
            regressions="; ".join(ev.key_regressions) or "none",
            recommendations="; ".join(ev.recommendations) or "none",
        )
        try:
            raw = self.llm.generate(system=DISTILL_SYSTEM, user=prompt, temperature=0.3)
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            items = json.loads(text)
            return [self._parse_card(d) for d in items if isinstance(d, dict)]
        except Exception:
            return []

    def _parse_card(self, d: dict) -> ExperienceCard:
        return ExperienceCard(
            exp_type=ExperienceType(d.get("type", "partial")),
            trigger_task_type=d.get("trigger_task", ""),
            trigger_symptom=d.get("trigger_symptom", ""),
            trigger_keywords=d.get("keywords", []),
            strategy=d.get("strategy", ""),
            key_insight=d.get("key_insight", ""),
            metrics_before=d.get("metrics_before", {}),
            metrics_after=d.get("metrics_after", {}),
            confidence=float(d.get("confidence", 0.5)),
            pitfalls=d.get("pitfalls", []),
            tags=d.get("tags", []),
        )

    # ── ExpeL: Cross-card Insight Extraction (#06) ──────────

    def distill_insights(
        self,
        cards: list["ExperienceCard"],
        max_insights: int = 5,
    ) -> list["InsightCard"]:
        """
        v4.97 — ExpeL Insights Extraction (#06 ExpeL: Zhao et al. AAAI 2024)

        跨 card 归纳高层通用规则（InsightCard）。
        单次失败生成 self_reflection（失败原因）；
        多次积累后 distill_insights 归纳跨卡通用规律。

        流程：
          读取近30天 ExperienceCard → LLM 归纳 3-5 条通用规则
          → InsightCard 列表（可存入 SkillBank / 注入 agents.md）

        Args:
            cards:        近期 ExperienceCard 列表（建议30天内）
            max_insights: 最多归纳几条（默认5条）

        Returns:
            list[InsightCard]
        """
        if not cards:
            return []

        # 规则提取：无 LLM 时用高频关键词规则
        if not self.llm:
            return self._insights_rule_based(cards, max_insights)

        # ── LLM 归纳 ──────────────────────────────────────
        card_summaries = []
        for i, c in enumerate(cards[:40], 1):   # 最多取40张避免超 token
            t = c.exp_type.value if hasattr(c.exp_type, "value") else str(c.exp_type)
            sr = c.self_reflection if hasattr(c, "self_reflection") and c.self_reflection else ""
            line = f"[{i}] [{t}] {c.key_insight}"
            if c.pitfalls:
                line += f" | pitfalls: {'; '.join(c.pitfalls[:2])}"
            if sr:
                line += f" | reflection: {sr[:80]}"
            card_summaries.append(line)

        system = """你是 GCC 经验蒸馏引擎（ExpeL Insights Extraction）。
从多张经验卡中归纳跨任务的通用规律。

输出 ONLY JSON 数组（{max_n} 条以内）：
[
  {{
    "insight": "一句话通用规律（可跨品种/任务直接使用）",
    "evidence_count": 支撑这条规律的卡片数量,
    "confidence": 0.0-1.0,
    "applies_to": ["gcc", "domain"],
    "tags": ["tag1", "tag2"]
  }}
]
要求：
- 必须是跨卡归纳的通用规律，不是单卡复述
- 有量化数据时必须写进 insight
- 避免空洞建议（如"要仔细测试"），要具体可操作
""".replace("{max_n}", str(max_insights))

        user = (
            f"共 {len(cards)} 张经验卡（截取前{len(card_summaries)}张）：\n\n"
            + "\n".join(card_summaries)
            + f"\n\n请归纳 {min(max_insights, len(cards))} 条跨卡通用规律，JSON 数组输出。"
        )

        try:
            raw = self.llm.generate(system=system, user=user,
                                    temperature=0.3, max_tokens=800)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            items = json.loads(raw)
            insights = []
            for d in items[:max_insights]:
                if isinstance(d, dict) and d.get("insight"):
                    insights.append(InsightCard(
                        insight=d["insight"],
                        evidence_count=int(d.get("evidence_count", 1)),
                        confidence=float(d.get("confidence", 0.7)),
                        applies_to=d.get("applies_to", []),
                        tags=d.get("tags", []),
                        source_card_count=len(cards),
                    ))
            return insights
        except Exception:
            return self._insights_rule_based(cards, max_insights)

    def _insights_rule_based(
        self,
        cards: list,
        max_insights: int,
    ) -> list["InsightCard"]:
        """无 LLM 时：提取高频 key_insight 作为规律（简单回退）。"""
        from collections import Counter
        kw_counter: Counter = Counter()
        insight_groups: dict[str, list[str]] = {}

        for c in cards:
            ki = c.key_insight.strip()
            if not ki:
                continue
            words = self._extract_keywords(ki)
            for w in words[:3]:
                kw_counter[w] += 1
                insight_groups.setdefault(w, []).append(ki)

        insights = []
        for kw, count in kw_counter.most_common(max_insights):
            if count < 2:
                break
            representative = insight_groups[kw][0]
            insights.append(InsightCard(
                insight=representative,
                evidence_count=count,
                confidence=min(0.5 + count * 0.05, 0.85),
                tags=[kw],
                source_card_count=len(cards),
            ))
        return insights

    # ── v4.98: Auto Distill to Cards (Step 16) ──

    def auto_distill_to_cards(
        self,
        insights: list["InsightCard"],
        key: str = "",
    ) -> int:
        """
        v4.98: 自动将InsightCard转为ExperienceCard存入GlobalMemory。
        distill_insights()后调用, 实现 insights→experience 闭环。
        """
        if not insights:
            return 0
        try:
            from .experience_store import GlobalMemory
            gm = GlobalMemory()
            stored = 0
            for ic in insights:
                card = ExperienceCard(
                    exp_type=ExperienceType.CROSSOVER,
                    trigger_task_type="auto_distill",
                    trigger_symptom=f"Cross-card insight from {ic.source_card_count} cards",
                    trigger_keywords=ic.tags[:5],
                    strategy=ic.insight,
                    key_insight=ic.insight,
                    confidence=ic.confidence,
                    key=key,
                    tags=["auto_distill", "insight"] + ic.tags[:3],
                )
                passed, _ = gm.store_with_gate(card)
                if passed:
                    stored += 1
            gm.close()
            return stored
        except Exception:
            return 0

    # ── Helpers ──

    def _dedupe(self, cards):
        if len(cards) <= 1:
            return cards
        seen, out = [], []
        for c in cards:
            sig = c.key_insight.lower().strip()[:80]
            if sig and any(self._overlap(sig, s) > 0.7 for s in seen):
                continue
            out.append(c)
            if sig:
                seen.append(sig)
        return out

    @staticmethod
    def _overlap(a, b):
        wa, wb = set(a.split()), set(b.split())
        return len(wa & wb) / len(wa | wb) if wa and wb else 0.0

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        stop = {"the","a","an","is","was","are","to","in","of","for","and","or","on","at","by",
                "with","from","this","that","it","be","as","do","not","but","if","no","so"}
        words = re.findall(r'[a-zA-Z_]{3,}', text.lower())
        return list(dict.fromkeys(w for w in words if w not in stop))[:10]

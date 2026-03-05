"""
GCC v4.0 — Evaluator
v4.0: + DeltaEvaluator (cross-session comparison on same KEY)
      + Downstream impact update after evaluation
From HGM paper: CMP tracks descendant performance, not just current session.
"""

from __future__ import annotations

import json

from .models import (
    SessionTrajectory,
    StepResult,
    TrajectoryEvaluation,
)

# ── Prompts ────────────────────────────────────────────────

EVAL_SYSTEM = """You are the evaluation engine for GCC v4.0.
Analyze a coding session trajectory and output ONLY valid JSON:
{
  "outcome_score": <0.0-1.0, did the task succeed?>,
  "outcome_reasoning": "<brief>",
  "efficiency_score": <0.0-1.0, how direct was the path?>,
  "efficiency_reasoning": "<brief>",
  "novelty_score": <0.0-1.0, were new approaches tried?>,
  "novelty_reasoning": "<brief>",
  "key_improvements": ["<what worked>", ...],
  "key_regressions": ["<what regressed>", ...],
  "recommendations": ["<what to do next time>", ...]
}
No markdown, no explanation, only the JSON object."""

EVAL_USER = """Evaluate this session:

Task: {task}
Project: {project}

Steps taken:
{steps}

Summary: {passed} passed, {failed} failed, {total} total steps."""


class Evaluator:
    """
    v4.0: Rule-based + optional LLM + delta comparison.
    """

    def __init__(self, llm=None, weights: dict[str, float] | None = None):
        self.llm = llm
        self.weights = weights or {"outcome": 0.5, "efficiency": 0.3, "novelty": 0.2}

    def evaluate(self, trajectory: SessionTrajectory) -> TrajectoryEvaluation:
        ev = TrajectoryEvaluation(session_id=trajectory.session_id)

        ev.efficiency_score = self._efficiency(trajectory)
        ev.outcome_score = self._outcome(trajectory)
        ev.novelty_score = self._novelty(trajectory)

        if self.llm:
            llm_eval = self._llm_evaluate(trajectory)
            ev = self._merge(ev, llm_eval)

        ev.compute_overall(self.weights)
        return ev

    def evaluate_quick(self, trajectory: SessionTrajectory) -> TrajectoryEvaluation:
        ev = TrajectoryEvaluation(session_id=trajectory.session_id)
        ev.efficiency_score = self._efficiency(trajectory)
        ev.outcome_score = self._outcome(trajectory)
        ev.novelty_score = self._novelty(trajectory)
        ev.compute_overall(self.weights)
        return ev

    def evaluate_with_delta(self, trajectory: SessionTrajectory,
                            prev_scores: list[dict]) -> TrajectoryEvaluation:
        """
        v4.0: Evaluate + compute delta vs previous sessions on same KEY.
        prev_scores: [{session_id, score, ...}] from experience_store.get_key_score_history()
        """
        ev = self.evaluate(trajectory)

        if prev_scores:
            prev_latest = prev_scores[-1]
            ev.delta_score = round(ev.overall_score - prev_latest["score"], 3)
            ev.prev_session_id = prev_latest["session_id"]

        return ev

    # ── Rule-based scoring ──

    def _outcome(self, traj: SessionTrajectory) -> float:
        if not traj.steps:
            return 0.0
        total_weight = 0.0
        weighted_pass = 0.0
        for i, step in enumerate(traj.steps):
            w = 1.0 + (i / len(traj.steps))
            total_weight += w
            if step.result == StepResult.PASS:
                weighted_pass += w
        return round(weighted_pass / total_weight, 3) if total_weight > 0 else 0.0

    def _efficiency(self, traj: SessionTrajectory) -> float:
        if not traj.steps:
            return 0.0
        base = traj.passed / len(traj.steps)
        fail_penalty = (traj.failed / len(traj.steps)) * 0.3
        return round(max(0.0, min(1.0, base - fail_penalty)), 3)

    def _novelty(self, traj: SessionTrajectory) -> float:
        if not traj.steps:
            return 0.0
        descriptions = [s.description.lower().strip() for s in traj.steps if s.description]
        if not descriptions:
            return 0.0
        unique = len(set(descriptions))
        return round(min(unique / max(len(descriptions), 1), 1.0), 3)

    # ── LLM evaluation ──

    def _llm_evaluate(self, traj: SessionTrajectory) -> dict:
        if not self.llm:
            return {}
        steps_text = []
        for s in traj.steps:
            line = f"  {s.step_id}. [{s.result.value}] {s.description}"
            if s.feedback:
                line += f"\n     Feedback: {s.feedback}"
            if s.metrics:
                line += f"\n     Metrics: {json.dumps(s.metrics)}"
            steps_text.append(line)

        prompt = EVAL_USER.format(
            task=traj.task, project=traj.project,
            steps="\n".join(steps_text) or "(no steps)",
            passed=traj.passed, failed=traj.failed, total=len(traj.steps))

        try:
            raw = self.llm.generate(system=EVAL_SYSTEM, user=prompt, temperature=0.1)
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except Exception as e:
            return {"_error": str(e)}

    def _merge(self, ev: TrajectoryEvaluation, llm: dict) -> TrajectoryEvaluation:
        if "_error" in llm:
            return ev
        for field in ("outcome_score", "efficiency_score", "novelty_score"):
            if field in llm:
                rule_val = getattr(ev, field)
                llm_val = float(llm[field])
                setattr(ev, field, round((rule_val + llm_val) / 2, 3))

        ev.key_improvements = llm.get("key_improvements", ev.key_improvements)
        ev.key_regressions = llm.get("key_regressions", ev.key_regressions)
        ev.recommendations = llm.get("recommendations", ev.recommendations)
        ev.raw_analysis = llm
        return ev

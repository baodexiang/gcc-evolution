"""
GCC v4.05 — Planner
Generates 2-3 structurally different improvement plans at session start.
Inspired by QuantaAlpha's Diversified Planning Initialization.
"""

from __future__ import annotations

import json

from .models import ExperienceCard, ImprovementPlan


PLAN_SYSTEM = """You are the planning engine for GCC v4.05.
Generate 2-3 STRUCTURALLY DIFFERENT improvement plans for a coding task.

Each plan must take a fundamentally different approach, not just a variation.

Output ONLY a JSON array:
[
  {
    "name": "<2-3 word label>",
    "approach": "<what to do, 1-2 sentences>",
    "reasoning": "<why this might work>",
    "confidence": <0.0-1.0>
  }
]

Diversity examples:
- Incremental optimization vs full refactor
- Algorithm change vs data structure change
- Add new component vs reconfigure existing"""

PLAN_USER = """Generate 2-3 diverse plans for this task:

Task: {task}

Past experience:
{experience}

Known pitfalls:
{pitfalls}

Output JSON array only."""


class Planner:
    """
    Generates diverse improvement plans at session start.
    Uses past experience to inform plans and avoid known pitfalls.
    """

    def __init__(self, llm=None):
        self.llm = llm

    def generate_plans(
        self,
        task: str,
        experiences: list[ExperienceCard] | None = None,
    ) -> list[ImprovementPlan]:
        """Generate 2-3 diverse plans. Returns empty list if no LLM."""
        if not self.llm:
            return self._default_plans(task)

        # Format experience context
        exp_text = "(none yet)"
        pitfall_text = "(none known)"

        if experiences:
            exp_lines = []
            pitfalls = []
            for e in experiences[:5]:
                exp_lines.append(f"  [{e.exp_type.value}] {e.key_insight}")
                pitfalls.extend(e.pitfalls)
            exp_text = "\n".join(exp_lines)
            if pitfalls:
                pitfall_text = "\n".join(f"  - {p}" for p in pitfalls[:5])

        prompt = PLAN_USER.format(
            task=task,
            experience=exp_text,
            pitfalls=pitfall_text,
        )

        try:
            raw = self.llm.generate(system=PLAN_SYSTEM, user=prompt, temperature=0.5)
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            items = json.loads(text)
            plans = []
            for d in items:
                if isinstance(d, dict):
                    plans.append(ImprovementPlan(
                        name=d.get("name", ""),
                        approach=d.get("approach", ""),
                        reasoning=d.get("reasoning", ""),
                        confidence=float(d.get("confidence", 0.5)),
                    ))
            return plans[:3]
        except Exception:
            return self._default_plans(task)

    def _default_plans(self, task: str) -> list[ImprovementPlan]:
        """Fallback: generate generic plans without LLM."""
        return [
            ImprovementPlan(
                name="Incremental",
                approach=f"Make targeted improvements to existing implementation of: {task}",
                confidence=0.6,
            ),
            ImprovementPlan(
                name="Structural",
                approach=f"Redesign the architecture for: {task}",
                confidence=0.4,
            ),
        ]

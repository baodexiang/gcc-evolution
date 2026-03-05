"""
GCC v4.05 — Crossover (v3.8)
Merges best steps from multiple sessions into "best practice" cards.
Inspired by QuantaAlpha's trajectory crossover.
"""

from __future__ import annotations

import json
import logging

from .models import ExperienceCard, ExperienceType

logger = logging.getLogger(__name__)


CROSSOVER_SYSTEM = """You are the trajectory crossover engine for GCC v4.05.
Given successful steps from MULTIPLE sessions working on the same improvement,
combine the best steps into a single "best practice" sequence.

Output ONLY a JSON object:
{
  "merged_steps": ["step1", "step2", "step3"],
  "key_insight": "<ONE sentence: the combined best practice>",
  "confidence": <0.0-1.0>,
  "reasoning": "<why this combination is optimal>"
}"""

CROSSOVER_USER = """These successful steps come from {n} different sessions on the same task:

Task: {task}

{sessions}

Merge the best steps into one optimal sequence. Output JSON only."""


class Crossover:
    """
    Recombines successful steps from multiple sessions on the same KEY
    into a single "best practice" experience card.
    """

    def __init__(self, llm=None):
        self.llm = llm

    def crossover(
        self,
        key: str,
        task: str,
        success_cards: list[ExperienceCard],
    ) -> ExperienceCard | None:
        """
        Generate a crossover card from multiple success cards.

        Only runs when there are 2+ success cards (GCC-0170: same session OK).
        """
        # GCC-0170: 放宽触发条件 — 2+张卡即可（不再强制不同session）
        if len(success_cards) < 2:
            return None

        if self.llm:
            return self._crossover_llm(key, task, success_cards)
        else:
            return self._crossover_rules(key, task, success_cards)

    def _crossover_llm(self, key, task, cards) -> ExperienceCard | None:
        # Group by session
        by_session: dict[str, list[str]] = {}
        for c in cards:
            sid = c.source_session or "unknown"
            if sid not in by_session:
                by_session[sid] = []
            by_session[sid].append(c.key_insight)

        session_text = []
        for i, (sid, insights) in enumerate(by_session.items(), 1):
            steps = "\n".join(f"    ✓ {ins}" for ins in insights)
            session_text.append(f"  Session {i} ({sid[:12]}):\n{steps}")

        prompt = CROSSOVER_USER.format(
            task=task,
            n=len(by_session),
            sessions="\n\n".join(session_text),
        )

        try:
            raw = self.llm.generate(system=CROSSOVER_SYSTEM, user=prompt, temperature=0.3, repeat=2)
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            d = json.loads(text)

            return ExperienceCard(
                exp_type=ExperienceType.CROSSOVER,
                trigger_task_type=task.split()[0] if task else "",
                trigger_symptom=f"Best practice for: {task}",
                trigger_keywords=[key.lower()] if key else [],
                strategy="merged best practice from multiple sessions",
                key_insight=d.get("key_insight", ""),
                merged_steps=d.get("merged_steps", []),
                source_sessions=list(set(c.source_session for c in cards)),
                confidence=float(d.get("confidence", 0.7)),
                key=key,
                tags=["crossover", "best_practice"],
            )
        except Exception as e:
            logger.warning("[CROSSOVER] LLM crossover failed, falling back to rules: %s", e)
            return self._crossover_rules(key, task, cards)

    def _crossover_rules(self, key, task, cards) -> ExperienceCard:
        """Rule-based: pick highest confidence insight from each session."""
        by_session: dict[str, ExperienceCard] = {}
        for c in cards:
            sid = c.source_session or "unknown"
            if sid not in by_session or c.confidence > by_session[sid].confidence:
                by_session[sid] = c

        best_insights = [c.key_insight for c in by_session.values() if c.key_insight]
        merged = best_insights[:5]

        return ExperienceCard(
            exp_type=ExperienceType.CROSSOVER,
            trigger_task_type=task.split()[0] if task else "",
            trigger_symptom=f"Best practice for: {task}",
            trigger_keywords=[key.lower()] if key else [],
            strategy="merged best practice from multiple sessions",
            key_insight=f"Combined approach: {'; '.join(merged[:3])}",
            merged_steps=merged,
            source_sessions=list(by_session.keys()),
            confidence=sum(c.confidence for c in by_session.values()) / max(len(by_session), 1),
            key=key,
            tags=["crossover", "best_practice"],
        )

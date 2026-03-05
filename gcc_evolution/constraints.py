"""
GCC v4.6 — Failure Constraints Memory
Inspired by FactorMiner: dual-channel memory (success patterns + failure constraints).

Failure cards auto-generate DO NOT rules that prune search space.
Retriever injects constraints alongside positive experiences.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Constraint:
    """A learned DO NOT rule from failure experience."""
    id: str = ""
    source_card_id: str = ""
    rule: str = ""                  # "DO NOT use fixed ATR in choppy markets"
    context: str = ""               # "PROD_A ER<0.3 Choppiness>61.8"
    key: str = ""                   # improvement KEY
    confidence: float = 0.0         # from failure card
    violation_count: int = 0        # times agent violated this
    adoption_count: int = 0         # times agent followed this
    active: bool = True
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def effectiveness(self) -> float:
        """How effective is this constraint (adoption / total)."""
        total = self.adoption_count + self.violation_count
        if total == 0:
            return 0.5  # no data yet
        return self.adoption_count / total

    def to_rule_string(self) -> str:
        """Format for injection into LLM context."""
        conf = f" (confidence: {self.confidence:.0%})" if self.confidence > 0 else ""
        ctx = f" | When: {self.context}" if self.context else ""
        return f"DO NOT: {self.rule}{conf}{ctx}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source_card_id": self.source_card_id,
            "rule": self.rule, "context": self.context, "key": self.key,
            "confidence": self.confidence,
            "violation_count": self.violation_count,
            "adoption_count": self.adoption_count,
            "active": self.active, "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Constraint':
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ConstraintStore:
    """
    Manages failure constraints.
    Storage: .gcc/constraints.json (flat file, expected <200 constraints).
    """

    STORE_PATH = ".gcc/constraints.json"

    def __init__(self, path: str | None = None):
        self._path = Path(path or self.STORE_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._constraints: list[Constraint] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text("utf-8"))
                self._constraints = [Constraint.from_dict(d) for d in data]
            except Exception:
                self._constraints = []

    def _save(self):
        self._path.write_text(
            json.dumps([c.to_dict() for c in self._constraints],
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def constraints(self) -> list[Constraint]:
        return list(self._constraints)

    def active_constraints(self, key: str = "") -> list[Constraint]:
        """Get active constraints, optionally filtered by KEY."""
        result = [c for c in self._constraints if c.active]
        if key:
            # Return constraints matching KEY + global constraints (no key)
            result = [c for c in result if not c.key or c.key.upper() == key.upper()]
        return result

    def add(self, constraint: Constraint) -> Constraint:
        """Add a new constraint. Auto-assigns ID if empty."""
        if not constraint.id:
            idx = len(self._constraints) + 1
            constraint.id = f"C-{idx:04d}"

        # Check for duplicate rules (fuzzy)
        for existing in self._constraints:
            if self._rule_overlap(constraint.rule, existing.rule) > 0.7:
                # Merge: update confidence if higher
                if constraint.confidence > existing.confidence:
                    existing.confidence = constraint.confidence
                    existing.context = constraint.context or existing.context
                    existing.updated_at = _now()
                    self._save()
                return existing

        self._constraints.append(constraint)
        self._save()
        return constraint

    def record_violation(self, constraint_id: str):
        """Record that an agent violated this constraint."""
        for c in self._constraints:
            if c.id == constraint_id:
                c.violation_count += 1
                c.updated_at = _now()
                self._save()
                return

    def record_adoption(self, constraint_id: str):
        """Record that an agent followed this constraint."""
        for c in self._constraints:
            if c.id == constraint_id:
                c.adoption_count += 1
                c.updated_at = _now()
                self._save()
                return

    def deactivate(self, constraint_id: str):
        """Deactivate a constraint (proven wrong or irrelevant)."""
        for c in self._constraints:
            if c.id == constraint_id:
                c.active = False
                c.updated_at = _now()
                self._save()
                return

    def generate_from_failure_card(self, card) -> list[Constraint]:
        """
        Auto-generate constraints from a failure ExperienceCard.
        Extracts DO NOT rules from pitfalls, key_insight, and strategy.
        """
        constraints = []

        # From pitfalls (most direct source)
        for pitfall in getattr(card, 'pitfalls', []):
            if pitfall and len(pitfall) > 5:
                c = Constraint(
                    source_card_id=card.id,
                    rule=pitfall,
                    context=getattr(card, 'trigger_symptom', ''),
                    key=getattr(card, 'key', ''),
                    confidence=getattr(card, 'confidence', 0.5),
                )
                constraints.append(self.add(c))

        # From key_insight of failure card
        insight = getattr(card, 'key_insight', '')
        if insight and len(insight) > 10:
            exp_type = getattr(card, 'exp_type', None)
            if exp_type and hasattr(exp_type, 'value') and exp_type.value == 'failure':
                c = Constraint(
                    source_card_id=card.id,
                    rule=insight,
                    context=getattr(card, 'trigger_symptom', ''),
                    key=getattr(card, 'key', ''),
                    confidence=getattr(card, 'confidence', 0.5),
                )
                constraints.append(self.add(c))

        return constraints

    def format_for_injection(self, key: str = "", max_constraints: int = 10) -> str:
        """
        Format active constraints for LLM context injection.
        Returns DO NOT section for VF-style retrieval.
        """
        active = self.active_constraints(key)
        if not active:
            return ""

        # Sort by confidence desc, then violation_count desc, then most-recently-updated first
        active.sort(key=lambda c: (-c.confidence, -c.violation_count, c.updated_at), reverse=False)
        active = active[:max_constraints]

        lines = ["═══ CONSTRAINTS (DO NOT) ═══"]
        for c in active:
            lines.append(c.to_rule_string())

        return "\n".join(lines)

    def stats(self) -> dict:
        """Summary statistics."""
        total = len(self._constraints)
        active = sum(1 for c in self._constraints if c.active)
        avg_eff = 0.0
        if active:
            effs = [c.effectiveness() for c in self._constraints if c.active]
            avg_eff = sum(effs) / len(effs)
        return {
            "total": total, "active": active,
            "avg_effectiveness": round(avg_eff, 3),
        }

    @staticmethod
    def _rule_overlap(a: str, b: str) -> float:
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

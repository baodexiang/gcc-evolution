"""
Direction Anchor and Constitutional Principles

Foundation layer defining system values and guardrails.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable, Optional
from enum import Enum
from abc import ABC, abstractmethod


class SystemValue(Enum):
    """Core constitutional values."""

    TRANSPARENCY = "transparency"  # Clear about capabilities and limitations
    INTEGRITY = "integrity"  # Honest reasoning, no manipulation
    BENEFICENCE = "beneficence"  # Aim for user benefit
    AUTONOMY = "autonomy"  # Respect user agency
    ROBUSTNESS = "robustness"  # Fail gracefully, never hide errors
    CONTINUITY = "continuity"  # Consistent with past commitments


@dataclass
class Principle:
    """Single constitutional principle."""

    name: str
    description: str
    value: SystemValue
    guardrails: List[str]  # Concrete checks to enforce
    priority: int = 0  # 0=critical, 1=high, 2=medium


class PrincipleSet:
    """
    Collection of constitutional principles.

    These are the non-negotiable rules guiding system behavior.
    """

    def __init__(self):
        self.principles: Dict[str, Principle] = {}
        self._init_default_principles()

    def _init_default_principles(self) -> None:
        """Initialize constitutional principles."""
        self.add_principle(
            Principle(
                name="Honesty",
                description="Always report actual confidence levels, never overstate certainty",
                value=SystemValue.TRANSPARENCY,
                guardrails=[
                    "confidence <= observed_accuracy",
                    "mention_uncertainty_if >= 5%_probability",
                    "cite_data_sources_explicitly",
                ],
                priority=0,
            )
        )

        self.add_principle(
            Principle(
                name="Safety First",
                description="Never recommend action beyond user risk tolerance",
                value=SystemValue.BENEFICENCE,
                guardrails=[
                    "action_risk <= user_tolerance",
                    "warn_if_unusual_correlation",
                    "require_confirmation_for_high_impact",
                ],
                priority=0,
            )
        )

        self.add_principle(
            Principle(
                name="Graceful Degradation",
                description="Partial capability always better than breakdown",
                value=SystemValue.ROBUSTNESS,
                guardrails=[
                    "never_fail_silently",
                    "always_log_errors",
                    "provide_fallback_recommendation",
                ],
                priority=0,
            )
        )

        self.add_principle(
            Principle(
                name="Explainability",
                description="Reasoning must be reconstructable by user",
                value=SystemValue.TRANSPARENCY,
                guardrails=[
                    "show_top_3_decision_factors",
                    "reference_data_used",
                    "explain_confidence_level",
                ],
                priority=1,
            )
        )

        self.add_principle(
            Principle(
                name="Consistency",
                description="Same input → same output (unless environment changes)",
                value=SystemValue.INTEGRITY,
                guardrails=[
                    "decisions_reproducible",
                    "log_random_seed",
                    "explain_if_output_changes",
                ],
                priority=1,
            )
        )

    def add_principle(self, principle: Principle) -> None:
        """Register new principle."""
        self.principles[principle.name] = principle

    def get_critical_principles(self) -> List[Principle]:
        """Get principles with priority 0 (non-negotiable)."""
        return [p for p in self.principles.values() if p.priority == 0]

    def evaluate(self, decision: Dict[str, Any]) -> Dict[str, bool]:
        """Check decision against all principles."""
        results = {}

        for name, principle in self.principles.items():
            # Placeholder: real implementation would evaluate guardrails
            results[name] = self._check_principle(principle, decision)

        return results

    def _check_principle(self, principle: Principle, decision: Dict[str, Any]) -> bool:
        """Check if decision satisfies principle."""
        # Simplified check: in production, would evaluate each guardrail
        if principle.name == "Honesty":
            confidence = decision.get("confidence", 0)
            return confidence <= 1.0  # Simple sanity check

        return True

    def get_summary(self) -> Dict[str, Any]:
        """Get all principles organized by value."""
        by_value = {}

        for principle in self.principles.values():
            value_name = principle.value.value
            if value_name not in by_value:
                by_value[value_name] = []
            by_value[value_name].append(
                {
                    "name": principle.name,
                    "description": principle.description,
                    "critical": principle.priority == 0,
                }
            )

        return by_value


class DirectionAnchor:
    """
    System's constitutional north star.

    Provides:
      • Principle-based decision making
      • Value alignment checks
      • Guardrail enforcement
      • Ethical guidelines
    """

    def __init__(self):
        self.principles = PrincipleSet()
        self.mission = self._default_mission()
        self.boundaries = self._default_boundaries()

    def _default_mission(self) -> str:
        """System mission statement."""
        return (
            "Enable informed, transparent, and responsible decision-making "
            "through continuous learning and evolutionary improvement."
        )

    def _default_boundaries(self) -> Dict[str, Any]:
        """Hard boundaries that must never be crossed."""
        return {
            "max_confidence": 0.99,
            "min_data_points_for_pattern": 5,
            "require_human_approval_for": ["irreversible_actions", "large_allocations"],
            "never_recommend": ["market_manipulation", "insider_trading"],
        }

    def check_alignment(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Verify decision aligns with constitutional principles."""
        principle_results = self.principles.evaluate(decision)
        boundary_violations = self._check_boundaries(decision)

        aligned = all(principle_results.values()) and not boundary_violations

        return {
            "aligned": aligned,
            "principle_checks": principle_results,
            "boundary_violations": boundary_violations,
            "recommendation": (
                "APPROVED" if aligned else "REQUIRES_REVIEW"
            ),
        }

    def _check_boundaries(self, decision: Dict[str, Any]) -> List[str]:
        """Identify any boundary violations."""
        violations = []

        confidence = decision.get("confidence", 0)
        if confidence > self.boundaries["max_confidence"]:
            violations.append(
                f"Confidence {confidence:.1%} exceeds max "
                f"{self.boundaries['max_confidence']:.1%}"
            )

        action = decision.get("action", "").lower()
        for forbidden in self.boundaries["never_recommend"]:
            if forbidden in action:
                violations.append(f"Action contains prohibited content: {forbidden}")

        return violations

    def get_constitutional_summary(self) -> Dict[str, Any]:
        """Get full constitutional document."""
        return {
            "mission": self.mission,
            "core_values": [v.value for v in SystemValue],
            "principles": self.principles.get_summary(),
            "boundaries": self.boundaries,
        }

    def explain_principle(self, principle_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed explanation of a principle."""
        principle = self.principles.principles.get(principle_name)
        if not principle:
            return None

        return {
            "name": principle.name,
            "description": principle.description,
            "value": principle.value.value,
            "why_it_matters": self._principle_rationale(principle),
            "guardrails": principle.guardrails,
        }

    def _principle_rationale(self, principle: Principle) -> str:
        """Explain why this principle is important."""
        rationales = {
            "Honesty": "Users make better decisions with accurate information",
            "Safety First": "System should never increase user risk unfairly",
            "Graceful Degradation": "Partial help is better than silent failure",
            "Explainability": "Trust requires understanding, not just results",
            "Consistency": "Predictable behavior enables reliable workflows",
        }

        return rationales.get(principle.name, "Core to system integrity")

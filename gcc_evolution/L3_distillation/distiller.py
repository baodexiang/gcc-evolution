"""
Experience Distillation Engine

Converts raw experiences into structured knowledge cards for reuse.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import hashlib
import json

try:
    from gcc_evolution.L4_decision import HallucinationDetector
except ImportError:  # pragma: no cover - fallback for stripped builds
    HallucinationDetector = None


@dataclass
class DistillationResult:
    """Output of distillation process."""

    card_id: str
    title: str
    category: str
    confidence: float
    summary: str
    conditions: List[str]
    actions: List[str]
    metadata: Dict[str, Any]


class ExperienceDistiller:
    """
    Distills raw experiences into reusable knowledge cards.

    Process:
      1. Input: Sequence of observations + outcomes
      2. Extract patterns (rules, conditions)
      3. Generate card with generalization
      4. Validate against other experiences
      5. Output: Reusable card
    """

    def __init__(self, min_confidence: float = 0.7):
        self.min_confidence = min_confidence
        self.experience_log = []
        self.generated_cards = []
        self.hallucination_detector = HallucinationDetector() if HallucinationDetector else None
        self.rejected_patterns: List[Dict[str, Any]] = []

    def add_experience(self, experience: Dict[str, Any]) -> None:
        """Log an experience for later distillation."""
        experience["timestamp"] = datetime.utcnow().isoformat()
        self.experience_log.append(experience)

    def distill(self) -> List[DistillationResult]:
        """
        Extract patterns from experience log.

        Returns:
            List of generated cards meeting confidence threshold
        """
        if not self.experience_log:
            return []

        cards = []

        # Group experiences by pattern
        patterns = self._extract_patterns()

        for pattern in patterns:
            confidence = pattern["confidence"]
            if confidence < self.min_confidence:
                continue
            if not self._passes_hallucination_gate(pattern):
                continue

            card = DistillationResult(
                card_id=self._generate_card_id(pattern),
                title=pattern.get("title", "Unknown Pattern"),
                category=pattern.get("category", "general"),
                confidence=confidence,
                summary=pattern.get("summary", ""),
                conditions=pattern.get("conditions", []),
                actions=pattern.get("actions", []),
                metadata=pattern.get("metadata", {}),
            )
            cards.append(card)
            self.generated_cards.append(card)

        return cards

    def _passes_hallucination_gate(self, pattern: Dict[str, Any]) -> bool:
        """Run a lightweight L4 hallucination gate before finalizing a card."""
        if not self.hallucination_detector:
            return True

        reasoning = " | ".join(
            [
                str(pattern.get("summary", "")),
                json.dumps(pattern.get("conditions", {}), ensure_ascii=False, sort_keys=True, default=str),
                json.dumps(pattern.get("actions", []), ensure_ascii=False, default=str),
            ]
        )
        decision_like = {
            "signal": "DISTILL",
            "action": "STORE_CARD",
            "confidence": pattern.get("confidence", 0.0),
            "reasoning": reasoning,
            "data_references": list((pattern.get("metadata") or {}).keys()),
        }
        context = dict(pattern.get("metadata") or {})
        issues = []
        for detector in (
            self.hallucination_detector.detect_overconfidence,
            self.hallucination_detector.detect_contradictions,
        ):
            issue = detector(decision_like)
            if issue:
                issues.append(issue)
        data_issue = self.hallucination_detector.detect_data_hallucination(decision_like, context)
        if data_issue:
            issues.append(data_issue)
        if issues:
            self.rejected_patterns.append(
                {
                    "title": pattern.get("title", "Unknown Pattern"),
                    "issues": issues,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            return False
        return True

    def _extract_patterns(self) -> List[Dict[str, Any]]:
        """Find recurring patterns in experience log."""
        patterns = {}

        for exp in self.experience_log:
            conditions = tuple(sorted(exp.get("conditions", {}).items()))
            key = conditions

            if key not in patterns:
                patterns[key] = {
                    "conditions": dict(conditions),
                    "outcomes": [],
                    "count": 0,
                }

            outcome = exp.get("outcome")
            if outcome:
                patterns[key]["outcomes"].append(outcome)
                patterns[key]["count"] += 1

        # Convert to scored patterns
        result = []
        for key, pattern in patterns.items():
            if pattern["count"] < 2:  # Need min 2 observations
                continue

            # Simple accuracy metric
            outcomes = pattern["outcomes"]
            positive = sum(1 for o in outcomes if o.get("success"))
            accuracy = positive / len(outcomes) if outcomes else 0

            result.append(
                {
                    "conditions": pattern["conditions"],
                    "confidence": accuracy,
                    "count": pattern["count"],
                    "category": "learned_pattern",
                    "title": f"Pattern {key[:2]}",
                    "summary": f"Observed {pattern['count']} times with {accuracy:.1%} success rate",
                    "actions": [o.get("action") for o in outcomes if o.get("action")],
                    "metadata": {"observations": pattern["count"]},
                }
            )

        return result

    def _generate_card_id(self, pattern: Dict[str, Any]) -> str:
        """Generate unique card ID from pattern."""
        pattern_str = json.dumps(pattern, sort_keys=True, default=str)
        hash_obj = hashlib.sha256(pattern_str.encode())
        return f"CARD-{hash_obj.hexdigest()[:8].upper()}"

    def validate_card(self, card: DistillationResult, new_experience: Dict[str, Any]) -> bool:
        """Check if card prediction matches new experience."""
        conditions_match = all(
            new_experience.get(k) == v for k, v in card.metadata.get("conditions", {}).items()
        )
        return conditions_match


class CardGenerator:
    """
    High-level API for generating experience cards.

    Combines distillation with version management.
    """

    def __init__(self):
        self.distiller = ExperienceDistiller()
        self.card_versions = {}

    def from_experiences(self, experiences: List[Dict[str, Any]]) -> List[DistillationResult]:
        """Generate cards from list of experiences."""
        for exp in experiences:
            self.distiller.add_experience(exp)

        return self.distiller.distill()

    def from_timeseries(
        self,
        data: List[Dict[str, Any]],
        lookback: int = 10,
    ) -> List[DistillationResult]:
        """
        Generate cards from time-series data.

        Automatically extracts conditions and outcomes from sequential data.
        """
        experiences = []

        for i in range(lookback, len(data)):
            window = data[i - lookback : i]
            current = data[i]

            # Extract features as conditions
            conditions = {f"lag_{j}": window[j].get("price") for j in range(len(window))}

            experience = {
                "conditions": conditions,
                "outcome": {
                    "success": current.get("price", 0) > window[-1].get("price", 0),
                    "price_change": (
                        current.get("price", 0) - window[-1].get("price", 0)
                    ),
                },
            }
            experiences.append(experience)

        return self.from_experiences(experiences)

    def update_card_version(
        self, card: DistillationResult, version: str, changes: str
    ) -> None:
        """Track card version history."""
        if card.card_id not in self.card_versions:
            self.card_versions[card.card_id] = []

        self.card_versions[card.card_id].append(
            {
                "version": version,
                "timestamp": datetime.utcnow().isoformat(),
                "changes": changes,
                "card": asdict(card),
            }
        )

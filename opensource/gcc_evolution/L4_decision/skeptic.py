"""
Skeptic Gate for Hallucination Detection

Validates decision quality before execution.
"""

from typing import Dict, List, Any, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
import re


@dataclass
class ValidationResult:
    """Output of skeptic validation."""

    is_valid: bool
    confidence: float  # 0-1, higher = more confident in validity
    issues: List[str]
    suggestions: List[str]


class ValidatorRule(ABC):
    """Abstract validation rule."""

    @abstractmethod
    def check(self, decision: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Return (is_valid, issue_description)."""
        pass


class ConsistencyValidator(ValidatorRule):
    """Check internal consistency of decision."""

    def check(self, decision: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Verify decision components align."""
        signal = decision.get("signal", "").upper()
        action = decision.get("action", "").upper()
        confidence = decision.get("confidence", 0)

        # Signal-action alignment
        if signal == "BUY" and "SELL" in action:
            return False, "Signal-action mismatch: BUY signal but SELL action"

        if signal == "SELL" and "BUY" in action:
            return False, "Signal-action mismatch: SELL signal but BUY action"

        # Low confidence should not trigger high-risk actions
        if confidence < 0.5 and "AGGRESSIVE" in action:
            return False, f"Low confidence ({confidence:.1%}) with aggressive action"

        return True, None


class FactValidator(ValidatorRule):
    """Check decision against known facts."""

    def __init__(self, facts: Dict[str, Any] = None):
        self.facts = facts or {}

    def check(self, decision: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Verify decision uses correct facts."""
        for fact_key, fact_value in self.facts.items():
            if fact_key in decision:
                decision_value = decision[fact_key]
                if decision_value != fact_value:
                    return (
                        False,
                        f"Decision uses incorrect {fact_key}: {decision_value} != {fact_value}",
                    )
        return True, None


class RangeValidator(ValidatorRule):
    """Check numeric values are in reasonable ranges."""

    VALID_RANGES = {
        "confidence": (0.0, 1.0),
        "allocation": (0.0, 1.0),
        "stop_loss": (-0.5, 0.0),
        "take_profit": (0.0, 10.0),
    }

    def check(self, decision: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Verify numeric ranges."""
        for key, (min_val, max_val) in self.VALID_RANGES.items():
            if key in decision:
                value = decision[key]
                if value < min_val or value > max_val:
                    return (
                        False,
                        f"{key} out of range: {value} not in [{min_val}, {max_val}]",
                    )
        return True, None


class LogicalValidator(ValidatorRule):
    """Check logical coherence of conditions and conclusions."""

    def check(self, decision: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Verify logical chain."""
        conditions = decision.get("conditions", [])
        conclusion = decision.get("signal", "")

        if not conditions:
            return False, "Decision lacks supporting conditions"

        if not conclusion:
            return False, "Decision lacks clear conclusion"

        # Check for contradictory conditions
        positive_conditions = [c for c in conditions if "+" in c]
        negative_conditions = [c for c in conditions if "-" in c]

        if len(positive_conditions) > 0 and len(negative_conditions) > 0:
            # Ensure signals align
            if conclusion == "HOLD":
                return (
                    False,
                    "Mixed conditions suggest indecision, but HOLD is not a strong signal",
                )

        return True, None


class HallucinationDetector:
    """
    Detects LLM hallucinations in decisions.

    Common patterns:
      • Unfounded high confidence
      • Contradictory justifications
      • Referencing non-existent data
    """

    def __init__(self):
        self.baseline_confidence = 0.5

    def detect_overconfidence(self, decision: Dict[str, Any]) -> Optional[str]:
        """Check for unrealistically high confidence."""
        confidence = decision.get("confidence", 0)

        if confidence > 0.95:
            reasoning = decision.get("reasoning", "")
            # If high confidence but weak reasoning, likely hallucination
            if len(reasoning) < 50:
                return "High confidence with insufficient justification"

        return None

    def detect_contradictions(self, decision: Dict[str, Any]) -> Optional[str]:
        """Detect logical contradictions in justification."""
        reasoning = decision.get("reasoning", "")

        patterns = [
            (r"bullish.*bearish", "Contradictory directional signals"),
            (r"up.*down.*trend", "Contradictory trend assessment"),
            (r"strong.*weak", "Contradictory strength assessment"),
        ]

        for pattern, description in patterns:
            if re.search(pattern, reasoning, re.IGNORECASE):
                return description

        return None

    def detect_data_hallucination(self, decision: Dict[str, Any], context: Dict[str, Any]) -> Optional[str]:
        """Check if decision references non-existent data."""
        references = decision.get("data_references", [])

        for ref in references:
            if ref not in context:
                return f"References non-existent data: {ref}"

        return None


class SkepticValidator:
    """
    Main skeptic gate combining all validators.

    Validates decisions before execution to prevent hallucinations.
    """

    def __init__(self):
        self.rules: List[ValidatorRule] = [
            ConsistencyValidator(),
            RangeValidator(),
            LogicalValidator(),
        ]
        self.hallucination_detector = HallucinationDetector()

    def add_rule(self, rule: ValidatorRule) -> None:
        """Add custom validation rule."""
        self.rules.append(rule)

    def validate(
        self,
        decision: Dict[str, Any],
        context: Dict[str, Any] = None,
    ) -> ValidationResult:
        """
        Validate decision against all rules.

        Returns:
            ValidationResult with validity flag and issues
        """
        context = context or {}
        issues = []
        confidence = 1.0

        # Check logical rules
        for rule in self.rules:
            is_valid, issue = rule.check(decision)
            if not is_valid and issue:
                issues.append(issue)
                confidence -= 0.2

        # Check for hallucinations
        overconf_issue = self.hallucination_detector.detect_overconfidence(decision)
        if overconf_issue:
            issues.append(overconf_issue)
            confidence -= 0.15

        contradiction = self.hallucination_detector.detect_contradictions(decision)
        if contradiction:
            issues.append(contradiction)
            confidence -= 0.15

        data_hal = self.hallucination_detector.detect_data_hallucination(decision, context)
        if data_hal:
            issues.append(data_hal)
            confidence -= 0.25

        # Generate suggestions
        suggestions = self._generate_suggestions(issues, decision)

        return ValidationResult(
            is_valid=confidence >= 0.5,
            confidence=max(0.0, confidence),
            issues=issues,
            suggestions=suggestions,
        )

    def _generate_suggestions(self, issues: List[str], decision: Dict[str, Any]) -> List[str]:
        """Generate remediation suggestions."""
        suggestions = []

        for issue in issues:
            if "mismatch" in issue.lower():
                suggestions.append("Review signal and action alignment")
            elif "confidence" in issue.lower():
                suggestions.append("Lower confidence or provide stronger justification")
            elif "contradictory" in issue.lower():
                suggestions.append("Resolve logical contradictions in reasoning")
            elif "range" in issue.lower():
                suggestions.append("Adjust numeric values to valid ranges")

        return suggestions

    def require_validation(self, decision: Dict[str, Any], context: Dict[str, Any] = None) -> None:
        """
        Strict validation mode: raise if invalid.

        Args:
            decision: Decision to validate
            context: Supporting context

        Raises:
            ValueError if decision fails validation
        """
        result = self.validate(decision, context)
        if not result.is_valid:
            msg = f"Decision validation failed: {'; '.join(result.issues)}"
            raise ValueError(msg)

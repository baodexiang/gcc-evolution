"""
GCC v5.405 — Direction Anchor Formal Verification (IRS-002)

Apache 2.0 — open-source interface layer.
The private BUSL 1.1 engine builds on top of these definitions.

Theory grounding (arXiv:2601.12538, POMDP Safety Constraint Theorem):
    Every L4→L5 state transition must satisfy the Direction Anchor
    condition set DA-01~DA-06.

    Formal definition:
        Transition(s_L4, a) → s_L5  is valid  iff
            ∀i∈{1..6}: DA_i(s_L4, a) = TRUE

    Any violation causes:
        1. Execution refused (transition blocked)
        2. Violation logged to audit trail
        3. Human notification triggered
        4. Decision path flagged in L1 Memory as "DA_VIOLATION"

Human-AI Handoff Theorem (Brenner et al. 2026, Sec.6.2):
    "AI optimizes within a given objective space.
     AI cannot define that objective space without triggering Goodhart dynamics."
    → Direction Anchors encode the boundary between what AI optimizes and what
      humans define. This boundary is a permanent structural requirement of any
      non-degenerating autonomous system.

Usage::

    from gcc_evolution.direction_anchor import DirectionAnchorValidator, DAContext

    validator = DirectionAnchorValidator()

    ctx = DAContext(
        anchor={"direction": "LONG", "constraints": [...], ...},
        proposed_action={"action": "BUY", "subject": "TSLA"},
        state={"market_regime": "trending_up"},
    )

    result = validator.validate(ctx)
    if not result.passed:
        print(result.violations)   # list of DAViolation
        raise DABlockedError(result)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════

class DACode(str, Enum):
    """The six Direction Anchor conditions."""
    DA_01 = "DA-01"   # Anchor presence   — a valid anchor must exist
    DA_02 = "DA-02"   # Direction align   — action must align with anchor direction
    DA_03 = "DA-03"   # Constraint clear  — no anchor constraint violated
    DA_04 = "DA-04"   # Pattern clean     — no negative pattern matched
    DA_05 = "DA-05"   # Objective stable  — no objective drift detected
    DA_06 = "DA-06"   # Anchor fresh      — anchor not stale beyond TTL


@dataclass
class DAViolation:
    """One DA condition that failed."""
    code:    DACode
    reason:  str
    detail:  dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.reason}"


@dataclass
class DAContext:
    """
    All inputs required for a full DA-01~06 check.

    anchor: the active HumanAnchor snapshot (dict or HumanAnchor object).
        Keys: direction, constraints, negative_patterns,
              main_concern, expires_after, created_at
    proposed_action: the action L4 Decision wants to take.
        Keys: action (str), subject (str), params (dict)
    state: current system state (market_state, market_regime, etc.)
    timestamp: check time (defaults to now UTC)
    """
    anchor:          dict
    proposed_action: dict
    state:           dict = field(default_factory=dict)
    timestamp:       str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DACheckResult:
    """
    Outcome of a full Direction Anchor validation pass.

    passed:     True only when all DA-01~06 pass.
    violations: list of DAViolation for failed conditions.
    checks:     dict mapping DACode → bool for every condition checked.
    context:    the DAContext that was evaluated.
    checked_at: ISO-8601 timestamp of this check.
    """
    passed:     bool
    violations: list[DAViolation] = field(default_factory=list)
    checks:     dict[str, bool]   = field(default_factory=dict)
    context:    DAContext | None  = None
    checked_at: str               = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def summary(self) -> str:
        if self.passed:
            return "DA OK — all 6 conditions satisfied"
        codes = ", ".join(v.code.value for v in self.violations)
        return f"DA BLOCKED — violated: {codes}"

    def to_dict(self) -> dict:
        return {
            "passed":     self.passed,
            "summary":    self.summary(),
            "violations": [{"code": v.code.value, "reason": v.reason, "detail": v.detail}
                           for v in self.violations],
            "checks":     self.checks,
            "checked_at": self.checked_at,
        }


class DABlockedError(Exception):
    """Raised when an L4→L5 transition is blocked by DA validation."""

    def __init__(self, result: DACheckResult):
        self.result = result
        super().__init__(result.summary())


# ═══════════════════════════════════════════════════════════════════
# DA-01~06 Precondition Functions  (open-source, Apache 2.0)
# ═══════════════════════════════════════════════════════════════════
# Each function: (anchor, proposed_action, state) → (bool, str, dict)
#   bool   — True = condition satisfied
#   str    — reason string (empty on pass)
#   dict   — optional detail for logging

def _da01_anchor_present(anchor: dict, action: dict, state: dict) -> tuple[bool, str, dict]:
    """
    DA-01: A valid, non-expired human anchor must exist.

    Prevents the system from operating without human direction.
    Corresponds to A-3 (目标不可变) — the objective space must be
    defined by a human before the AI optimizes within it.
    """
    if not anchor:
        return False, "No active anchor found", {}
    direction = anchor.get("direction", "")
    if not direction:
        return False, "Anchor has no direction set", {"anchor": anchor}
    # Check expiry if tracking_status present
    status = anchor.get("tracking_status", "")
    if status == "EXPIRED":
        return False, "Anchor has expired — human recalibration required", {"status": status}
    return True, "", {}


def _da02_direction_aligned(anchor: dict, action: dict, state: dict) -> tuple[bool, str, dict]:
    """
    DA-02: The proposed action must align with the anchor direction,
    or the anchor must be NEUTRAL (any action allowed).

    Direction mapping:
        Anchor LONG  → action must be BUY / HOLD / REDUCE (not SELL-to-short)
        Anchor SHORT → action must be SELL / HOLD / COVER  (not BUY-to-long)
        Anchor NEUTRAL → any action allowed
    """
    anchor_dir  = anchor.get("direction", "NEUTRAL").upper()
    action_type = action.get("action", "").upper()

    if anchor_dir == "NEUTRAL":
        return True, "", {}

    LONG_ALLOWED  = {"BUY", "HOLD", "REDUCE", "LONG", ""}
    SHORT_ALLOWED = {"SELL", "HOLD", "COVER", "SHORT", ""}

    if anchor_dir in ("LONG", "UP") and action_type in SHORT_ALLOWED - LONG_ALLOWED:
        return False, (
            f"Action '{action_type}' conflicts with LONG anchor direction"
        ), {"anchor_direction": anchor_dir, "action": action_type}

    if anchor_dir in ("SHORT", "DOWN") and action_type in LONG_ALLOWED - SHORT_ALLOWED:
        return False, (
            f"Action '{action_type}' conflicts with SHORT anchor direction"
        ), {"anchor_direction": anchor_dir, "action": action_type}

    return True, "", {}


def _da03_constraints_respected(anchor: dict, action: dict, state: dict) -> tuple[bool, str, dict]:
    """
    DA-03: The proposed action must not violate any active anchor constraint.

    Constraints are natural-language rules stored on the anchor
    (e.g. "LOW位SELL → 强制HOLD").  This open-source check applies a
    simple keyword scan; the private engine may use an LLM for richer
    semantic matching.
    """
    constraints: list[str] = anchor.get("constraints", [])
    if not constraints:
        return True, "", {}

    for constraint in constraints:
        c_upper = constraint.upper()
        # Simple heuristic: if constraint mentions blocking a pattern present in action
        # Private engine overrides this with semantic matching
        if "SELL" in c_upper and "HOLD" in c_upper and action.get("action", "").upper() == "SELL":
            return False, f"Constraint violated: '{constraint}'", {
                "constraint": constraint, "action": action
            }

    return True, "", {}


def _da04_no_negative_pattern(anchor: dict, action: dict, state: dict) -> tuple[bool, str, dict]:
    """
    DA-04: The proposed action must not match any recorded negative pattern.

    Negative patterns describe failure modes the human has identified
    (e.g. {"pattern": "chasing breakouts at ATH", "context": "low volume"}).
    This open-source version checks for exact condition overlap.
    """
    patterns: list[dict] = anchor.get("negative_patterns", [])
    if not patterns:
        return True, "", {}

    action_action  = action.get("action", "").upper()
    state_regime   = state.get("market_regime", "").lower()

    for pat in patterns:
        pat_action  = str(pat.get("action",  "")).upper()
        pat_context = str(pat.get("context", "")).lower()
        if pat_action and pat_action == action_action:
            if not pat_context or pat_context in state_regime:
                return False, f"Negative pattern matched: {pat}", {
                    "pattern": pat, "state": state
                }

    return True, "", {}


def _da05_no_objective_drift(anchor: dict, action: dict, state: dict) -> tuple[bool, str, dict]:
    """
    DA-05: The system's apparent objective must not have drifted from
    the anchor's main concern.

    Goodhart Theorem (Brenner et al. Sec.6.2):
        An AI system cannot redefine the objective space without triggering
        Goodhart dynamics.  DA-05 detects when the optimization target appears
        to have shifted away from what the human intended.

    This open-source implementation uses a confidence threshold check.
    The private engine computes semantic drift using embedding distance.
    """
    concern = anchor.get("main_concern", "")
    if not concern:
        return True, "", {}

    # Check system confidence hasn't dropped below a stability floor
    # The full private validator computes semantic embedding distance
    anchor_confidence = anchor.get("confidence", 1.0)
    if isinstance(anchor_confidence, (int, float)) and anchor_confidence < 0.1:
        return False, (
            f"Anchor confidence too low ({anchor_confidence:.0%}) — "
            "objective may have drifted, human recalibration required"
        ), {"confidence": anchor_confidence}

    return True, "", {}


def _da06_anchor_fresh(anchor: dict, action: dict, state: dict) -> tuple[bool, str, dict]:
    """
    DA-06: The anchor must not be stale beyond its freshness window.

    An anchor that was written too long ago may no longer reflect the
    human's current intent — especially after significant market regime
    changes.  The default staleness threshold is 72 hours.
    """
    created_at = anchor.get("created_at", "")
    if not created_at:
        return True, "", {}   # No timestamp → cannot determine staleness; allow

    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_hours = (now - created).total_seconds() / 3600
        # Respect the anchor's own expires_after if it encodes hours
        expires_after = anchor.get("expires_after", "72_hours")
        max_age_hours = _parse_max_age_hours(expires_after)
        if age_hours > max_age_hours:
            return False, (
                f"Anchor is {age_hours:.0f}h old, exceeds freshness limit of {max_age_hours:.0f}h"
            ), {"age_hours": age_hours, "max_hours": max_age_hours}
    except (ValueError, TypeError) as e:
        logger.debug("[DA-06] Could not parse anchor timestamp: %s", e)

    return True, "", {}


def _parse_max_age_hours(expires_after: str) -> float:
    """Parse 'N_trading_days' / 'N_sessions' / 'N_hours' → float hours."""
    if not expires_after:
        return 72.0
    s = expires_after.lower()
    if "trading_day" in s:
        try:
            return float(s.split("_")[0]) * 7.0   # ~7h per trading day
        except ValueError:
            return 72.0
    if "session" in s:
        try:
            return float(s.split("_")[0]) * 4.0   # ~4h per session
        except ValueError:
            return 72.0
    if "hour" in s:
        try:
            return float(s.split("_")[0])
        except ValueError:
            return 72.0
    return 72.0


# ═══════════════════════════════════════════════════════════════════
# DirectionAnchorValidator
# ═══════════════════════════════════════════════════════════════════

_DA_CHECKS: list[tuple[DACode, Callable]] = [
    (DACode.DA_01, _da01_anchor_present),
    (DACode.DA_02, _da02_direction_aligned),
    (DACode.DA_03, _da03_constraints_respected),
    (DACode.DA_04, _da04_no_negative_pattern),
    (DACode.DA_05, _da05_no_objective_drift),
    (DACode.DA_06, _da06_anchor_fresh),
]


class DirectionAnchorValidator:
    """
    Validates an L4→L5 state transition against all six Direction Anchor
    conditions (DA-01~DA-06).

    Open-source interface (Apache 2.0).  The private BUSL 1.1 engine
    subclasses this to override individual DA checks with richer
    semantic implementations (LLM-based constraint matching, embedding
    drift detection, DuckDB audit logging, human notification hooks).

    Example::

        validator = DirectionAnchorValidator()
        result = validator.validate(ctx)
        if not result.passed:
            raise DABlockedError(result)

    Subclassing for private extensions::

        class PrivateDAValidator(DirectionAnchorValidator):
            def _check_da03(self, anchor, action, state):
                # Override with LLM semantic constraint matching
                ...
    """

    def validate(self, ctx: DAContext) -> DACheckResult:
        """
        Run all DA-01~06 checks.

        Returns DACheckResult with passed=True only when every check passes.
        Evaluation is fail-fast per check but all violations are collected.
        """
        anchor = ctx.anchor if isinstance(ctx.anchor, dict) else vars(ctx.anchor)
        action = ctx.proposed_action
        state  = ctx.state

        violations: list[DAViolation] = []
        checks: dict[str, bool] = {}

        for code, fn in _DA_CHECKS:
            ok, reason, detail = fn(anchor, action, state)
            checks[code.value] = ok
            if not ok:
                violations.append(DAViolation(code=code, reason=reason, detail=detail))
                logger.warning("[DA_VALIDATOR] %s failed: %s", code.value, reason)

        passed = len(violations) == 0
        result = DACheckResult(
            passed=passed,
            violations=violations,
            checks=checks,
            context=ctx,
        )

        if passed:
            logger.debug("[DA_VALIDATOR] All DA checks passed")
        else:
            logger.warning("[DA_VALIDATOR] Transition BLOCKED — %s", result.summary())

        return result

    def validate_or_raise(self, ctx: DAContext) -> DACheckResult:
        """Validate and raise DABlockedError if any condition fails."""
        result = self.validate(ctx)
        if not result.passed:
            raise DABlockedError(result)
        return result

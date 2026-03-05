from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .contracts import MasterContext, MasterDecision, MasterOpinion, clamp01

logger = logging.getLogger(__name__)


@dataclass
class DecisionThresholds:
    downgrade_composite_lt: float = 0.30
    downgrade_low_count_min: int = 2
    downgrade_low_score_lt: float = 0.30
    upgrade_all_score_min: float = 0.70
    upgrade_composite_min: float = 0.75
    upgrade_signal_strength_min: float = 0.70
    max_blocked_gates_for_upgrade: int = 2
    macro_veto_enabled: bool = True
    reject_if_blocked_reason_contains: Optional[List[str]] = None
    require_nonempty_context_for_trade: bool = True
    policy_version: str = "key001-master-policy-v1"

    def __post_init__(self) -> None:
        if self.reject_if_blocked_reason_contains is None:
            self.reject_if_blocked_reason_contains = ["DANGER"]


def compute_weighted_score(opinions: List[MasterOpinion], weights: Dict[str, float]) -> float:
    if not opinions:
        return 0.0
    total_w = 0.0
    score = 0.0
    for op in opinions:
        w = float(weights.get(op.master, 1.0))
        total_w += w
        score += w * clamp01(op.score)
    if total_w <= 0:
        return 0.0
    return round(score / total_w, 4)


def evaluate_decision(
    ctx: MasterContext,
    opinions: List[MasterOpinion],
    weights: Dict[str, float],
    cfg: DecisionThresholds,
) -> MasterDecision:
    """Apply asymmetric validation policy and output final master decision."""
    reasons: List[str] = []
    final_score = compute_weighted_score(opinions, weights)

    veto = next((op for op in opinions if op.master == "Druckenmiller" and op.veto), None)
    low_count = sum(1 for op in opinions if op.score < cfg.downgrade_low_score_lt)
    has_data = _has_nonempty_context_data(ctx)

    direction = ctx.direction.upper()
    if direction in ("BUY", "SELL"):
        if cfg.require_nonempty_context_for_trade and not has_data:
            reasons.append("DOWNGRADE_NO_CONTEXT_DATA")
            logger.warning("Master policy downgraded %s due to empty context data", direction)
            return MasterDecision(
                action="DOWNGRADE",
                final_score=final_score,
                reasons=reasons,
                opinions=opinions,
                policy_version=cfg.policy_version,
            )
        if cfg.macro_veto_enabled and veto is not None:
            reasons.append("DOWNGRADE_D1_VETO")
            return MasterDecision(
                action="DOWNGRADE",
                final_score=final_score,
                reasons=reasons,
                opinions=opinions,
                policy_version=cfg.policy_version,
            )
        if final_score < cfg.downgrade_composite_lt:
            reasons.append("DOWNGRADE_COMPOSITE_LOW")
            return MasterDecision(
                action="DOWNGRADE",
                final_score=final_score,
                reasons=reasons,
                opinions=opinions,
                policy_version=cfg.policy_version,
            )
        if low_count >= cfg.downgrade_low_count_min:
            reasons.append("DOWNGRADE_MULTI_MASTER_LOW")
            return MasterDecision(
                action="DOWNGRADE",
                final_score=final_score,
                reasons=reasons,
                opinions=opinions,
                policy_version=cfg.policy_version,
            )
        reasons.append(f"CONFIRM_{direction}")
        return MasterDecision(
            action="CONFIRM",
            final_score=final_score,
            reasons=reasons,
            opinions=opinions,
            policy_version=cfg.policy_version,
        )

    if direction == "HOLD":
        all_high = all(op.score >= cfg.upgrade_all_score_min for op in opinions)
        blocked_by_keyword = _blocked_reason_contains(
            ctx.blocked_reason, cfg.reject_if_blocked_reason_contains
        )
        strong_signal = ctx.signal_strength >= cfg.upgrade_signal_strength_min
        gate_ok = ctx.blocked_gate_count <= cfg.max_blocked_gates_for_upgrade
        composite_ok = final_score >= cfg.upgrade_composite_min
        veto_block = cfg.macro_veto_enabled and (veto is not None)

        if all_high and composite_ok and strong_signal and gate_ok and not blocked_by_keyword and not veto_block:
            reasons.append("UPGRADE_ALL_CONDITIONS_MET")
            return MasterDecision(
                action="UPGRADE",
                final_score=final_score,
                reasons=reasons,
                opinions=opinions,
                policy_version=cfg.policy_version,
            )
        reasons.append("CONFIRM_HOLD")
        return MasterDecision(
            action="CONFIRM_HOLD",
            final_score=final_score,
            reasons=reasons,
            opinions=opinions,
            policy_version=cfg.policy_version,
        )

    reasons.append("CONFIRM_NON_STANDARD_DIRECTION")
    return MasterDecision(
        action="CONFIRM",
        final_score=final_score,
        reasons=reasons,
        opinions=opinions,
        policy_version=cfg.policy_version,
    )


def _has_nonempty_context_data(ctx: MasterContext) -> bool:
    return bool((ctx.market and len(ctx.market) > 0) or (ctx.macro and len(ctx.macro) > 0) or (ctx.stats and len(ctx.stats) > 0))


def _blocked_reason_contains(blocked_reason: str | None, keywords: List[str]) -> bool:
    if not blocked_reason:
        return False
    normalized = blocked_reason.upper().replace("-", "_")
    tokens = {tok for tok in normalized.split("_") if tok}
    for keyword in keywords:
        key = str(keyword).upper().strip()
        if key and key in tokens:
            return True
    return False

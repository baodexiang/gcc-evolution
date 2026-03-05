from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from ..contracts import MasterContext, MasterOpinion, clamp01, safe_float

logger = logging.getLogger(__name__)


@dataclass
class DruckenmillerConfig:
    d1_veto_score: float = 0.2
    max_macro_ttl_sec: int = 3 * 24 * 3600
    m2_support_min: float = 0.0
    spread_risk_max: float = 0.025
    vix_risk_high: float = 30.0
    asym_rr_min: float = 1.8
    stale_downweight: float = 0.85
    version: str = "druckenmiller-v1"


class DruckenmillerModule:
    """Macro advisor with policy-alignment veto capability."""

    def __init__(self, cfg: DruckenmillerConfig | None = None):
        self.cfg = cfg or DruckenmillerConfig()

    def evaluate(self, ctx: MasterContext) -> MasterOpinion:
        """Score macro alignment and return Druckenmiller opinion."""
        macro = ctx.macro or {}
        if not macro:
            logger.warning("Druckenmiller evaluate with empty macro context: symbol=%s", ctx.symbol)
        reasons: List[str] = []
        subscores: Dict[str, float] = {}

        ttl_sec = int(safe_float(macro.get("ttl_sec"), self.cfg.max_macro_ttl_sec + 1))
        stale = ttl_sec > self.cfg.max_macro_ttl_sec

        fed_stance = str(macro.get("fed_stance", "NEUTRAL")).upper()
        direction = ctx.direction.upper()
        d1_align = 1.0
        if direction == "BUY" and fed_stance in ("HAWKISH", "TIGHTENING"):
            d1_align = 0.1
        elif direction == "SELL" and fed_stance in ("DOVISH", "EASING"):
            d1_align = 0.1
        elif fed_stance == "NEUTRAL":
            d1_align = 0.55
        subscores["D1_POLICY_ALIGN"] = d1_align

        m2_yoy = safe_float(macro.get("m2_yoy"), 0.0)
        credit_spread = safe_float(macro.get("credit_spread"), 0.03)
        d2_liquidity = clamp01((m2_yoy - self.cfg.m2_support_min + 0.06) / 0.12)
        d2_liquidity *= clamp01((self.cfg.spread_risk_max + 0.02 - credit_spread) / 0.04)
        subscores["D2_LIQUIDITY"] = d2_liquidity

        vix = safe_float(macro.get("vix"), 24.0)
        d4_asym_rr = safe_float(macro.get("macro_rr_ratio"), 1.4)
        d4 = clamp01(d4_asym_rr / max(0.1, self.cfg.asym_rr_min))
        if vix > self.cfg.vix_risk_high:
            d4 *= 0.75
        subscores["D4_ASYMMETRY"] = d4

        d5_alignment = safe_float(macro.get("macro_tech_alignment"), 0.5)
        subscores["D5_ALIGNMENT"] = clamp01(d5_alignment)

        d7_risk_discipline = safe_float(macro.get("risk_discipline"), 0.55)
        subscores["D7_DISCIPLINE"] = clamp01(d7_risk_discipline)

        if stale:
            reasons.append("D_MACRO_STALE")
            for key in list(subscores.keys()):
                subscores[key] = round(subscores[key] * self.cfg.stale_downweight, 4)

        veto = subscores["D1_POLICY_ALIGN"] < self.cfg.d1_veto_score
        if veto:
            reasons.append("D1_POLICY_VETO")
        if subscores["D2_LIQUIDITY"] < 0.35:
            reasons.append("D2_LIQUIDITY_WEAK")
        if subscores["D4_ASYMMETRY"] < 0.35:
            reasons.append("D4_ASYMMETRY_POOR")

        score = round(sum(subscores.values()) / max(1, len(subscores)), 4)
        verdict = "GO" if score >= 0.64 else "NEUTRAL" if score >= 0.36 else "AVOID"

        if not reasons:
            reasons.append("D_OK")

        return MasterOpinion(
            master="Druckenmiller",
            score=score,
            verdict=verdict,
            veto=veto,
            reasons=reasons,
            subscores=subscores,
            version=self.cfg.version,
        )

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from ..contracts import MasterContext, MasterOpinion, clamp01, safe_float

logger = logging.getLogger(__name__)


@dataclass
class LivermoreConfig:
    weak_breakout_rvol: float = 1.05
    max_breakout_distance_pct: float = 0.035
    pullback_max_pct: float = 0.055
    late_entry_zone_pct: float = 0.85
    min_rr: float = 1.6
    signal_freq_5d_warn: int = 8
    min_key_level_score: float = 0.35
    market_missing_default: float = 0.50
    version: str = "livermore-v1"


class LivermoreModule:
    """Timing advisor focusing on entry quality and trend position."""

    def __init__(self, cfg: LivermoreConfig | None = None):
        self.cfg = cfg or LivermoreConfig()

    def evaluate(self, ctx: MasterContext) -> MasterOpinion:
        """Score timing quality and return Livermore opinion."""
        market = ctx.market or {}
        if not market:
            logger.warning("Livermore evaluate with empty market context: symbol=%s", ctx.symbol)
            score = clamp01(self.cfg.market_missing_default)
            return MasterOpinion(
                master="Livermore",
                score=score,
                verdict="NEUTRAL",
                veto=False,
                reasons=["L_MISSING_MARKET_DATA"],
                subscores={"L_MISSING_MARKET_DATA": score},
                version=self.cfg.version,
            )
        reasons: List[str] = []
        subscores: Dict[str, float] = {}

        pivot_distance = abs(safe_float(market.get("pivot_distance_pct"), 0.08))
        s_l1 = clamp01(1.0 - pivot_distance / 0.10)
        subscores["L1_KEY_LEVEL"] = s_l1
        if s_l1 < self.cfg.min_key_level_score:
            reasons.append("L1_KEY_LEVEL_FAR")

        rvol = safe_float(market.get("rvol"), 1.0)
        breakout_distance = abs(safe_float(market.get("breakout_distance_pct"), 0.0))
        breakout_ok = (rvol >= self.cfg.weak_breakout_rvol) and (
            breakout_distance <= self.cfg.max_breakout_distance_pct
        )
        s_l5 = 0.8 if breakout_ok else 0.25
        subscores["L5_BREAKOUT"] = s_l5
        if not breakout_ok:
            reasons.append("L5_BREAKOUT_WEAK")

        pullback_pct = abs(safe_float(market.get("pullback_pct"), 0.06))
        pullback_rvol = safe_float(market.get("pullback_rvol"), 1.1)
        pullback_ok = pullback_pct <= self.cfg.pullback_max_pct and pullback_rvol <= 1.0
        s_l4 = 0.75 if pullback_ok else 0.30
        subscores["L4_PULLBACK_HEALTH"] = s_l4
        if not pullback_ok:
            reasons.append("L4_PULLBACK_DIRTY")

        trend_position = safe_float(market.get("trend_position_pct"), 0.5)
        s_l6 = clamp01(1.0 - max(0.0, trend_position - self.cfg.late_entry_zone_pct) / 0.2)
        subscores["L6_LATE_ENTRY"] = s_l6
        if s_l6 < 0.4:
            reasons.append("L6_LATE_ENTRY_RISK")

        rr_ratio = safe_float(market.get("rr_ratio"), 1.2)
        s_l7 = clamp01(rr_ratio / max(0.1, self.cfg.min_rr))
        subscores["L7_RR"] = s_l7
        if rr_ratio < self.cfg.min_rr:
            reasons.append("L7_RR_WEAK")

        signal_freq_5d = int(safe_float(market.get("signal_freq_5d"), 0))
        s_l8 = clamp01(1.0 - max(0, signal_freq_5d - self.cfg.signal_freq_5d_warn) / 8.0)
        subscores["L8_OVERTRADING"] = s_l8
        if signal_freq_5d > self.cfg.signal_freq_5d_warn:
            reasons.append("L8_OVERTRADING")

        score = round(sum(subscores.values()) / max(1, len(subscores)), 4)
        verdict = "GO" if score >= 0.62 else "NEUTRAL" if score >= 0.35 else "AVOID"

        if not reasons:
            reasons.append("L_OK")

        return MasterOpinion(
            master="Livermore",
            score=score,
            verdict=verdict,
            veto=False,
            reasons=reasons,
            subscores=subscores,
            version=self.cfg.version,
        )

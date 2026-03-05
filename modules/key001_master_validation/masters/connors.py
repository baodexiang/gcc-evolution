from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from ..contracts import MasterContext, MasterOpinion, clamp01, safe_float

logger = logging.getLogger(__name__)


@dataclass
class ConnorsConfig:
    rsi2_buy_max: float = 12.0
    rsi2_sell_min: float = 88.0
    crsi_buy_max: float = 15.0
    crsi_sell_min: float = 85.0
    min_sample_size: int = 80
    winrate_floor: float = 0.55
    low_sample_default: float = 0.45
    version: str = "connors-v1"


class ConnorsModule:
    """Statistical advisor for mean-reversion edge and discipline."""

    def __init__(self, cfg: ConnorsConfig | None = None):
        self.cfg = cfg or ConnorsConfig()

    def evaluate(self, ctx: MasterContext) -> MasterOpinion:
        """Score statistical edge and return Connors opinion."""
        stats = ctx.stats or {}
        macro = ctx.macro or {}
        if not stats:
            logger.warning("Connors evaluate with empty stats context: symbol=%s", ctx.symbol)
        reasons: List[str] = []
        subscores: Dict[str, float] = {}
        direction = ctx.direction.upper()

        rsi2 = safe_float(stats.get("rsi2"), 50.0)
        crsi = safe_float(stats.get("connors_rsi"), 50.0)
        streak_days = abs(int(safe_float(stats.get("streak_days"), 0)))

        if direction == "BUY":
            s_c1 = clamp01((self.cfg.rsi2_buy_max + 20.0 - rsi2) / 20.0)
            s_c5 = clamp01((self.cfg.crsi_buy_max + 25.0 - crsi) / 25.0)
        else:
            s_c1 = clamp01((rsi2 - self.cfg.rsi2_sell_min + 20.0) / 20.0)
            s_c5 = clamp01((crsi - self.cfg.crsi_sell_min + 25.0) / 25.0)
        subscores["C1_RSI2"] = s_c1
        subscores["C5_CRSI"] = s_c5

        s_c2 = clamp01(streak_days / 6.0)
        subscores["C2_STREAK"] = s_c2

        above_ma200 = bool(stats.get("above_ma200", True))
        if direction == "BUY":
            s_c3 = 0.8 if above_ma200 else 0.25
        else:
            s_c3 = 0.8 if not above_ma200 else 0.25
        subscores["C3_MA200_SIDE"] = s_c3

        exp = ctx.experience_db or {}
        sample_size = int(
            safe_float(stats.get("pattern_sample_size", exp.get("pattern_sample_size", 0)), 0)
        )
        hist_winrate = safe_float(stats.get("pattern_winrate", exp.get("pattern_winrate", 0.5)), 0.5)
        if sample_size < self.cfg.min_sample_size:
            s_c4 = self.cfg.low_sample_default
            reasons.append("C4_SAMPLE_LOW")
        else:
            s_c4 = clamp01((hist_winrate - self.cfg.winrate_floor + 0.15) / 0.25)
        subscores["C4_HIST_EDGE"] = s_c4

        vix = safe_float(macro.get("vix", stats.get("vix", 22.0)), 22.0)
        if vix >= 35:
            s_c6 = 0.30 if direction == "BUY" else 0.55
        elif vix <= 16:
            s_c6 = 0.70 if direction == "BUY" else 0.55
        else:
            s_c6 = 0.55
        subscores["C6_VIX_REGIME"] = s_c6

        has_exit_plan = bool(stats.get("has_exit_plan", True))
        subscores["C7_EXIT_PLAN"] = 0.8 if has_exit_plan else 0.2
        if not has_exit_plan:
            reasons.append("C7_EXIT_PLAN_MISSING")

        pos_discipline = safe_float(stats.get("position_discipline"), 0.6)
        subscores["C8_POSITION_DISCIPLINE"] = clamp01(pos_discipline)

        if s_c1 < 0.35:
            reasons.append("C1_RSI2_NOT_EXTREME")
        if s_c5 < 0.35:
            reasons.append("C5_CRSI_NOT_EXTREME")

        score = round(sum(subscores.values()) / max(1, len(subscores)), 4)
        verdict = "GO" if score >= 0.63 else "NEUTRAL" if score >= 0.35 else "AVOID"

        if not reasons:
            reasons.append("C_OK")

        return MasterOpinion(
            master="Connors",
            score=score,
            verdict=verdict,
            veto=False,
            reasons=reasons,
            subscores=subscores,
            version=self.cfg.version,
        )

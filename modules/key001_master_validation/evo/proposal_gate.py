from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass
class GateMetrics:
    samples: int
    p_value: float
    max_drawdown_not_worse: bool
    winrate_lift: float
    discordant_pairs: int = 0


@dataclass
class GateThresholds:
    min_samples: int = 50
    max_p_value: float = 0.05
    min_winrate_lift: float = 0.05
    min_discordant_pairs: int = 10


def evaluate_gate(metrics: GateMetrics, cfg: GateThresholds | None = None) -> Dict[str, object]:
    cfg = cfg or GateThresholds()
    checks = {
        "samples_ok": metrics.samples >= cfg.min_samples,
        "p_value_ok": metrics.p_value < cfg.max_p_value,
        "drawdown_ok": bool(metrics.max_drawdown_not_worse),
        "lift_ok": metrics.winrate_lift >= cfg.min_winrate_lift,
        "discordant_ok": metrics.discordant_pairs >= cfg.min_discordant_pairs,
    }
    approved = all(checks.values())
    reasons = [k for k, ok in checks.items() if not ok]
    logger.info("Proposal gate evaluated: approved=%s reasons=%s", approved, reasons)
    return {"approved": approved, "checks": checks, "reasons": reasons}

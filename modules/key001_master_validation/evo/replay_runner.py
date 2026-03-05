from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, Iterable, List

logger = logging.getLogger(__name__)


@dataclass
class ReplayResult:
    samples: int
    winrate_before: float
    winrate_after: float
    p_value: float
    max_drawdown_not_worse: bool
    discordant_pairs: int


def run_replay(records: Iterable[Dict]) -> ReplayResult:
    data: List[Dict] = list(records)
    if not data:
        return ReplayResult(0, 0.0, 0.0, 1.0, True, 0)

    before_wins = 0
    after_wins = 0
    improve = 0
    regress = 0
    before_series: List[float] = []
    after_series: List[float] = []
    for rec in data:
        try:
            pnl_before = float(rec.get("pnl_before", 0.0))
            pnl_after = float(rec.get("pnl_after", pnl_before))
        except Exception:
            logger.warning("Invalid replay record skipped: %s", rec)
            continue

        before_series.append(pnl_before)
        after_series.append(pnl_after)
        if pnl_before > 0:
            before_wins += 1
        if pnl_after > 0:
            after_wins += 1
        if pnl_before <= 0 < pnl_after:
            improve += 1
        elif pnl_before > 0 >= pnl_after:
            regress += 1

    samples = len(before_series)
    if samples == 0:
        return ReplayResult(0, 0.0, 0.0, 1.0, True, 0)

    winrate_before = before_wins / samples
    winrate_after = after_wins / samples
    discordant = improve + regress

    p_value = _mcnemar_exact_pvalue(improve, regress)

    dd_before = _max_drawdown(before_series)
    dd_after = _max_drawdown(after_series)
    max_drawdown_not_worse = dd_after <= dd_before + 1e-12

    logger.info(
        "Replay evaluated: samples=%s winrate_before=%.4f winrate_after=%.4f p=%.6f dd_before=%.4f dd_after=%.4f",
        samples,
        winrate_before,
        winrate_after,
        p_value,
        dd_before,
        dd_after,
    )

    return ReplayResult(
        samples=samples,
        winrate_before=round(winrate_before, 4),
        winrate_after=round(winrate_after, 4),
        p_value=p_value,
        max_drawdown_not_worse=max_drawdown_not_worse,
        discordant_pairs=discordant,
    )


def _max_drawdown(pnl_series: List[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_series:
        equity += pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 6)


def _mcnemar_exact_pvalue(improve: int, regress: int) -> float:
    n = improve + regress
    if n <= 0:
        return 1.0
    k = min(improve, regress)
    tail = 0.0
    for i in range(0, k + 1):
        tail += math.comb(n, i)
    p = min(1.0, 2.0 * tail / (2.0**n))
    return round(p, 8)

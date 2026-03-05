from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import Dict, Iterable, List

from zoneinfo import ZoneInfo

from .contracts import MasterContext, MasterDecision

logger = logging.getLogger(__name__)


class MasterAuditLogger:
    """Persist master decisions and aggregate a daily quality summary."""

    def __init__(
        self,
        log_path: str = "state/audit/key001_master_validation.jsonl",
        summary_path: str = "state/audit/key001_master_daily_summary.json",
    ):
        self.log_path = log_path
        self.summary_path = summary_path

    def log(self, ctx: MasterContext, decision: MasterDecision) -> bool:
        """Append one decision record into JSONL audit log."""
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        rec = {
            "ts": time.time(),
            "symbol": ctx.symbol,
            "direction": ctx.direction,
            "signal_type": ctx.signal_type,
            "signal_strength": ctx.signal_strength,
            "filter_passed": ctx.filter_passed,
            "blocked_reason": ctx.blocked_reason,
            "blocked_gate_count": ctx.blocked_gate_count,
            "market": ctx.market,
            "macro": ctx.macro,
            "stats": ctx.stats,
            "experience_db": ctx.experience_db,
            "decision": asdict(decision),
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return True
        except Exception:
            logger.exception("Failed to write KEY001 audit log: %s", self.log_path)
            return False

    def build_daily_summary(self, records: Iterable[Dict] | None = None) -> Dict:
        """Build daily aggregate metrics for actions and master verdicts."""
        if records is None:
            records = self._read_records()

        day = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        bucket = defaultdict(int)
        symbol_bucket: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        master_bucket: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        score_sum = 0.0
        count = 0

        for r in records:
            action = r.get("decision", {}).get("action", "UNKNOWN")
            bucket[action] += 1
            symbol = str(r.get("symbol", "UNKNOWN"))
            symbol_bucket[symbol][action] += 1
            for opinion in r.get("decision", {}).get("opinions", []):
                m = str(opinion.get("master", "UNKNOWN"))
                v = str(opinion.get("verdict", "UNKNOWN"))
                master_bucket[m][v] += 1
            score = float(r.get("decision", {}).get("final_score", 0.0))
            score_sum += score
            count += 1

        summary = {
            "date": day,
            "samples": count,
            "avg_final_score": round(score_sum / count, 4) if count else 0.0,
            "actions": dict(bucket),
            "by_symbol": {k: dict(v) for k, v in symbol_bucket.items()},
            "by_master_verdict": {k: dict(v) for k, v in master_bucket.items()},
        }
        os.makedirs(os.path.dirname(self.summary_path), exist_ok=True)
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        return summary

    def _read_records(self) -> List[Dict]:
        if not os.path.exists(self.log_path):
            return []
        out: List[Dict] = []
        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    logger.warning("Skip malformed audit line in %s", self.log_path)
                    continue
        return out

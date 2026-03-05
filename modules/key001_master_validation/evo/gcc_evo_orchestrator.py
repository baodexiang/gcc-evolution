from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from typing import Dict, List

from .proposal_gate import GateMetrics, evaluate_gate
from .replay_runner import run_replay

logger = logging.getLogger(__name__)


class GccEvoOrchestrator:
    """Run replay and gate evaluation, then persist evo artifacts."""

    def __init__(
        self,
        state_path: str = "state/key001_master_evo_state.json",
        proposal_path: str = "state/key001_master_proposals.jsonl",
    ):
        self.state_path = state_path
        self.proposal_path = proposal_path

    def observe(self, records: List[Dict]) -> Dict:
        """Evaluate replay metrics and proposal gate in observe phase."""
        replay = run_replay(records)
        metrics = GateMetrics(
            samples=replay.samples,
            p_value=replay.p_value,
            max_drawdown_not_worse=replay.max_drawdown_not_worse,
            winrate_lift=(replay.winrate_after - replay.winrate_before),
            discordant_pairs=replay.discordant_pairs,
        )
        gate = evaluate_gate(metrics)

        result = {
            "ts": time.time(),
            "phase": "observe",
            "replay": asdict(replay),
            "gate": gate,
        }
        self._write_state(result)
        self._append_proposal(result)
        logger.info("KEY001 evo observe completed: approved=%s", gate.get("approved"))
        return result

    def _write_state(self, payload: Dict) -> None:
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to write evo state: %s", self.state_path)
            raise

    def _append_proposal(self, payload: Dict) -> None:
        os.makedirs(os.path.dirname(self.proposal_path), exist_ok=True)
        try:
            with open(self.proposal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Failed to append evo proposal: %s", self.proposal_path)
            raise

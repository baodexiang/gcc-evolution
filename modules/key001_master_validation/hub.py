from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List

from .contracts import MasterContext, MasterDecision, MasterOpinion
from .decision_policy import DecisionThresholds, evaluate_decision
from .masters import ConnorsModule, DruckenmillerModule, LivermoreModule
from .masters.connors import ConnorsConfig
from .masters.druckenmiller import DruckenmillerConfig
from .masters.livermore import LivermoreConfig

logger = logging.getLogger(__name__)


@dataclass
class MasterHubConfig:
    weights: Dict[str, float] = field(
        default_factory=lambda: {
            "Livermore": 1.0,
            "Druckenmiller": 1.2,
            "Connors": 1.0,
        }
    )
    fail_open_score: float = 0.5
    max_workers: int = 3


class MasterValidationHub:
    """Orchestrate the three master evaluators and return one unified decision."""

    def __init__(
        self,
        livermore: LivermoreModule | None = None,
        druckenmiller: DruckenmillerModule | None = None,
        connors: ConnorsModule | None = None,
        hub_cfg: MasterHubConfig | None = None,
        decision_cfg: DecisionThresholds | None = None,
    ):
        self.livermore = livermore or LivermoreModule()
        self.druckenmiller = druckenmiller or DruckenmillerModule()
        self.connors = connors or ConnorsModule()
        self.hub_cfg = hub_cfg or MasterHubConfig()
        self.decision_cfg = decision_cfg or DecisionThresholds()

    @classmethod
    def from_config_files(
        cls,
        policy_path: str = "modules/key001_master_validation/config/key001_master_policy.yaml",
        weights_path: str = "modules/key001_master_validation/config/key001_master_weights.yaml",
    ) -> "MasterValidationHub":
        """Build a hub instance from policy and weight config files."""
        policy_cfg = _load_yaml_or_json(policy_path)
        weights_cfg = _load_yaml_or_json(weights_path).get("masters", {})
        missing_cfg = policy_cfg.get("missing_data", {}) if isinstance(policy_cfg, dict) else {}
        market_default = _to_float(missing_cfg.get("market_default"), 0.50)
        macro_stale_downweight = _to_float(missing_cfg.get("macro_stale_downweight"), 0.85)
        stats_low_sample_default = _to_float(missing_cfg.get("stats_low_sample_default"), 0.45)

        hub_cfg = MasterHubConfig(
            weights={
                "Livermore": _to_float(weights_cfg.get("Livermore"), 1.0),
                "Druckenmiller": _to_float(weights_cfg.get("Druckenmiller"), 1.2),
                "Connors": _to_float(weights_cfg.get("Connors"), 1.0),
            }
        )

        decision_cfg = DecisionThresholds(
            downgrade_composite_lt=float(
                _to_float(
                    _read_nested(policy_cfg, ["decision", "downgrade", "composite_lt"], 0.30),
                    0.30,
                )
            ),
            downgrade_low_count_min=_to_int(
                _read_nested(policy_cfg, ["decision", "downgrade", "low_count_min"], 2), 2
            ),
            downgrade_low_score_lt=float(
                _to_float(
                    _read_nested(policy_cfg, ["decision", "downgrade", "low_score_lt"], 0.30),
                    0.30,
                )
            ),
            upgrade_all_score_min=float(
                _to_float(
                    _read_nested(policy_cfg, ["decision", "upgrade", "all_score_min"], 0.70),
                    0.70,
                )
            ),
            upgrade_composite_min=float(
                _to_float(
                    _read_nested(policy_cfg, ["decision", "upgrade", "composite_min"], 0.75),
                    0.75,
                )
            ),
            upgrade_signal_strength_min=float(
                _to_float(
                    _read_nested(
                        policy_cfg, ["decision", "upgrade", "signal_strength_min"], 0.70
                    ),
                    0.70,
                )
            ),
            max_blocked_gates_for_upgrade=_to_int(
                _read_nested(policy_cfg, ["decision", "upgrade", "max_blocked_gates"], 2), 2
            ),
            macro_veto_enabled=_to_bool(
                _read_nested(policy_cfg, ["decision", "downgrade", "macro_veto"], True), True
            ),
            reject_if_blocked_reason_contains=_to_str_list(
                _read_nested(
                    policy_cfg,
                    ["decision", "upgrade", "reject_if_blocked_reason_contains"],
                    ["DANGER"],
                )
            ),
            policy_version=str(policy_cfg.get("version", "key001-master-policy-v1")),
        )

        livermore_cfg = LivermoreConfig(market_missing_default=market_default)
        druckenmiller_cfg = DruckenmillerConfig(stale_downweight=macro_stale_downweight)
        connors_cfg = ConnorsConfig(low_sample_default=stats_low_sample_default)

        return cls(
            livermore=LivermoreModule(cfg=livermore_cfg),
            druckenmiller=DruckenmillerModule(cfg=druckenmiller_cfg),
            connors=ConnorsModule(cfg=connors_cfg),
            hub_cfg=hub_cfg,
            decision_cfg=decision_cfg,
        )

    def _safe_eval(self, name: str, fn, ctx: MasterContext) -> MasterOpinion:
        try:
            return fn(ctx)
        except Exception as exc:
            logger.exception("Master evaluator failed and switched to fail-open: %s", name)
            return MasterOpinion(
                master=name,
                score=self.hub_cfg.fail_open_score,
                verdict="NEUTRAL",
                veto=False,
                reasons=[f"{name}_ERROR:{type(exc).__name__}"],
                subscores={"fallback": self.hub_cfg.fail_open_score},
                version="fallback-v1",
            )

    def evaluate(self, ctx: MasterContext) -> MasterDecision:
        """Run parallel master scoring and apply decision policy."""
        tasks = {
            "Livermore": self.livermore.evaluate,
            "Druckenmiller": self.druckenmiller.evaluate,
            "Connors": self.connors.evaluate,
        }

        opinions_map: Dict[str, MasterOpinion] = {}
        with ThreadPoolExecutor(max_workers=self.hub_cfg.max_workers) as pool:
            futures = {
                pool.submit(self._safe_eval, name, fn, ctx): name
                for name, fn in tasks.items()
            }
            for fut in as_completed(futures):
                op = fut.result()
                opinions_map[op.master] = op

        opinions: List[MasterOpinion] = [
            opinions_map.get("Livermore")
            or self._safe_eval("Livermore", self.livermore.evaluate, ctx),
            opinions_map.get("Druckenmiller")
            or self._safe_eval("Druckenmiller", self.druckenmiller.evaluate, ctx),
            opinions_map.get("Connors")
            or self._safe_eval("Connors", self.connors.evaluate, ctx),
        ]

        return evaluate_decision(ctx, opinions, self.hub_cfg.weights, self.decision_cfg)


def _read_nested(data: Dict, keys: List[str], default):
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _load_yaml_or_json(path: str) -> Dict:
    if not os.path.exists(path):
        logger.warning("Master config file not found: %s", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        logger.exception("Failed reading config file: %s", path)
        return {}

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.debug("YAML parser unavailable or failed for %s, fallback to JSON", path)

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Config parsing failed for %s", path)
        return {}


def _to_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _to_str_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return ["DANGER"]

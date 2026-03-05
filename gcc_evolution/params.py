"""
GCC v5.050 — Product Parameters Module
KEY-001 P0: Parameter configuration infrastructure.

Manages per-product YAML parameter files with:
- Structured schema (entry / risk / regime / targets / backtest)
- Loader with validation and fallback defaults
- Gate checker comparing backtest results vs targets
- CLI integration (gcc-evo params)

Usage:
    # Load params for a product
    params = ParamStore.load("product_A")

    # Run gate check after backtest
    gate = ParamGate.check("product_A")
    if gate.passed:
        print("Ready to deploy")
    else:
        print(gate.report())

    # Update backtest results
    ParamStore.update_backtest("product_A", {
        "sharpe": 2.3, "max_dd_pct": 12, "win_rate": 0.58, ...
    })
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Default Schema ──────────────────────────────────────────

DEFAULT_PARAMS = {
    "product_id": "",
    "category": "default",
    "timeframe": "4h",
    "trend_tf": "16h",

    "strategy": {},

    "risk": {
        "max_position_pct": 80,
        "stop_loss_atr_mult": 1.5,
        "trailing_atr_mult": 2.0,
        "max_drawdown_pct": 15,
        "position_scaling": True,
        "scale_steps": [20, 40, 60, 80],
    },

    "regime": {
        "regime_lookback": 60,
        "vwma_period": 20,
        "trend_strength_min": 0.6,
    },

    "targets": {
        "sharpe_min": 2.0,
        "max_dd_pct": 15,
        "win_rate_min": 0.55,
        "calmar_min": 1.5,
        "profit_factor_min": 1.5,
        "sortino_min": 2.0,
        "cagr_min": 0.25,
    },

    "backtest": {
        "sharpe": None,
        "max_dd_pct": None,
        "win_rate": None,
        "calmar": None,
        "profit_factor": None,
        "sortino": None,
        "cagr": None,
        "total_trades": None,
        "period": None,
        "updated_at": None,
    },
}


# ── Param Store ─────────────────────────────────────────────

class ParamStore:
    """
    Per-product YAML parameter manager.
    Files stored in .gcc/params/{PRODUCT_ID}.yaml
    """

    PARAMS_DIR = ".gcc/params"

    @classmethod
    def path_for(cls, product_id: str) -> Path:
        return Path(cls.PARAMS_DIR) / f"{product_id.upper()}.yaml"

    @classmethod
    def exists(cls, product_id: str) -> bool:
        return cls.path_for(product_id).exists()

    @classmethod
    def list_products(cls) -> list[str]:
        """List all products with param files."""
        d = Path(cls.PARAMS_DIR)
        if not d.exists():
            return []
        return sorted(
            f.stem.upper() for f in d.glob("*.yaml") if f.stem.upper() != "TEMPLATE"
        )

    @classmethod
    def load(cls, product_id: str) -> dict:
        """
        Load params for a product.
        Falls back to defaults if file missing or fields incomplete.
        """
        product_id = product_id.upper()
        path = cls.path_for(product_id)

        # Start with defaults
        params = copy.deepcopy(DEFAULT_PARAMS)
        params["product_id"] = product_id

        # Load from file if exists
        if path.exists() and yaml:
            try:
                file_data = yaml.safe_load(path.read_text("utf-8"))
                if file_data and isinstance(file_data, dict):
                    cls._deep_merge(params, file_data)
            except Exception:
                pass  # fall back to defaults

        return params

    @classmethod
    def save(cls, product_id: str, params: dict) -> Path:
        """Save params to YAML file."""
        product_id = product_id.upper()
        path = cls.path_for(product_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        if yaml:
            content = yaml.dump(
                params, allow_unicode=True, default_flow_style=False,
                sort_keys=False,
            )
        else:
            content = json.dumps(params, indent=2, ensure_ascii=False)

        path.write_text(content, encoding="utf-8")
        return path

    @classmethod
    def init_product(cls, product_id: str, category: str = "default") -> Path:
        """Initialize a new product YAML from defaults."""
        product_id = product_id.upper()

        params = copy.deepcopy(DEFAULT_PARAMS)
        params["product_id"] = product_id
        params["category"] = "default"

    @classmethod
    def update_backtest(cls, product_id: str, results: dict) -> Path:
        """Update backtest results in YAML after optimization."""
        params = cls.load(product_id)
        bt = params.get("backtest", {})
        bt.update(results)
        bt["updated_at"] = _now()
        params["backtest"] = bt
        return cls.save(product_id, params)

    @classmethod
    def update_param(cls, product_id: str, section: str, key: str, value: Any) -> Path:
        """Update a single parameter."""
        params = cls.load(product_id)
        if section in params and isinstance(params[section], dict):
            params[section][key] = value
        return cls.save(product_id, params)

    @classmethod
    def diff(cls, product_id: str, old_params: dict | None = None) -> list[dict]:
        """
        Compare current params vs previous version.
        Returns list of changes.
        """
        current = cls.load(product_id)
        if old_params is None:
            # Compare against defaults
            old_params = copy.deepcopy(DEFAULT_PARAMS)
            old_params = copy.deepcopy(DEFAULT_PARAMS)
    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        """Deep merge override into base (in-place)."""
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                ParamStore._deep_merge(base[k], v)
            else:
                base[k] = v


# ── Gate Check ──────────────────────────────────────────────

@dataclass
class GateCheckResult:
    """Single gate check item."""
    name: str
    passed: bool
    required: bool = True
    current: float | None = None
    target: float | None = None
    direction: str = ">="  # >= or <=
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "passed": self.passed,
            "required": self.required,
            "current": self.current, "target": self.target,
            "direction": self.direction, "detail": self.detail,
        }


@dataclass
class ParamGateResult:
    """Complete gate check result for a product."""
    product_id: str
    checks: list[GateCheckResult] = field(default_factory=list)
    checked_at: str = field(default_factory=_now)
    passed: bool = False
    pass_rate: float = 0.0
    required_pass_rate: float = 0.0
    no_regression: bool = True
    regression_details: list[str] = field(default_factory=list)

    def evaluate(self) -> 'ParamGateResult':
        """Compute pass/fail from individual checks."""
        if not self.checks:
            self.passed = False
            return self

        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        self.pass_rate = passed / total

        required = [c for c in self.checks if c.required]
        required_passed = sum(1 for c in required if c.passed)
        self.required_pass_rate = required_passed / len(required) if required else 1.0

        # Must pass: all required checks + no regression
        self.passed = (
            all(c.passed for c in self.checks if c.required)
            and self.no_regression
        )
        return self

    def report(self) -> str:
        """Human-readable gate report."""
        lines = [
            f"═══ Gate Check: {self.product_id} ═══",
            f"Result: {'PASSED PASSED' if self.passed else 'FAILED FAILED'}",
            f"Pass Rate: {self.pass_rate:.0%} (Required: {self.required_pass_rate:.0%})",
            "",
        ]
        for c in self.checks:
            icon = "+" if c.passed else "-"
            req = " *" if c.required else ""
            if c.current is not None and c.target is not None:
                lines.append(
                    f"  {icon} {c.name}{req}: {c.current:.4g} {c.direction} {c.target:.4g}"
                    f"  {'OK' if c.passed else 'FAIL'}"
                )
            else:
                lines.append(f"  {icon} {c.name}{req}: {c.detail or 'no data'}")

        if not self.no_regression:
            lines.append("")
            lines.append("  WARNING: Regression detected:")
            for d in self.regression_details:
                lines.append(f"    - {d}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "required_pass_rate": self.required_pass_rate,
            "no_regression": self.no_regression,
            "regression_details": self.regression_details,
            "checked_at": self.checked_at,
            "checks": [c.to_dict() for c in self.checks],
        }


class ParamGate:
    """
    Gate checker: compare backtest results vs targets.
    Seven core metrics, three mandatory (Sharpe, MaxDD, WinRate).
    """

    # (metric_name, backtest_key, target_key, direction, required)
    METRICS = [
        ("Sharpe Ratio",    "sharpe",        "sharpe_min",        ">=", True),
        ("Max Drawdown",    "max_dd_pct",    "max_dd_pct",        "<=", True),
        ("Win Rate",        "win_rate",      "win_rate_min",      ">=", True),
        ("Calmar Ratio",    "calmar",        "calmar_min",        ">=", False),
        ("Profit Factor",   "profit_factor", "profit_factor_min", ">=", False),
        ("Sortino Ratio",   "sortino",       "sortino_min",       ">=", False),
        ("CAGR",            "cagr",          "cagr_min",          ">=", False),
    ]

    @classmethod
    def check(cls, product_id: str, previous_backtest: dict | None = None) -> ParamGateResult:
        """
        Run full gate check for a product.
        Compares backtest results vs targets.
        Optionally checks regression vs previous backtest.
        """
        params = ParamStore.load(product_id)
        targets = params.get("targets", {})
        backtest = params.get("backtest", {})

        result = ParamGateResult(product_id=product_id.upper())

        for name, bt_key, tgt_key, direction, required in cls.METRICS:
            current = backtest.get(bt_key)
            target = targets.get(tgt_key)

            if current is None or target is None:
                result.checks.append(GateCheckResult(
                    name=name, passed=False, required=required,
                    current=current, target=target, direction=direction,
                    detail="no backtest data" if current is None else "no target",
                ))
                continue

            if direction == ">=":
                passed = current >= target
            else:  # <=
                passed = current <= target

            result.checks.append(GateCheckResult(
                name=name, passed=passed, required=required,
                current=current, target=target, direction=direction,
            ))

        # No-regression check
        if previous_backtest:
            result.no_regression = True
            for name, bt_key, _, direction, required in cls.METRICS:
                if not required:
                    continue
                prev_val = previous_backtest.get(bt_key)
                curr_val = backtest.get(bt_key)
                if prev_val is None or curr_val is None:
                    continue

                regressed = False
                if direction == ">=" and curr_val < prev_val * 0.9:
                    regressed = True
                elif direction == "<=" and curr_val > prev_val * 1.1:
                    regressed = True

                if regressed:
                    result.no_regression = False
                    result.regression_details.append(
                        f"{name}: {prev_val:.4g} → {curr_val:.4g} "
                        f"(>{10}% regression)"
                    )

        result.evaluate()

        # Save verification
        cls._save_verification(result)

        return result

    @classmethod
    def _save_verification(cls, result: ParamGateResult) -> Path:
        """Save gate result for audit trail."""
        vdir = Path(".gcc/verification")
        vdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = vdir / f"params_{result.product_id}_{ts}.json"
        path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def quick_status(cls, product_id: str) -> str:
        """One-line status for dashboard display."""
        params = ParamStore.load(product_id)
        bt = params.get("backtest", {})
        targets = params.get("targets", {})

        if bt.get("sharpe") is None:
            return f"{product_id}: no backtest data"

        checks = []
        for name, bt_key, tgt_key, direction, required in cls.METRICS:
            if not required:
                continue
            v = bt.get(bt_key)
            t = targets.get(tgt_key)
            if v is None or t is None:
                checks.append("?")
                continue
            if direction == ">=":
                checks.append("+" if v >= t else "-")
            else:
                checks.append("+" if v <= t else "-")

        sharpe = bt.get("sharpe", 0)
        dd = bt.get("max_dd_pct", 0)
        wr = bt.get("win_rate", 0)

        status = "".join(checks)
        return f"{product_id} [{status}] Sharpe={sharpe:.2f} DD={dd:.1f}% WR={wr:.0%}"


# ── Batch Operations ────────────────────────────────────────

def gate_check_all() -> dict[str, ParamGateResult]:
    """Run gate check on all products with backtest data."""
    results = {}
    for product_id in ParamStore.list_products():
        params = ParamStore.load(product_id)
        if params.get("backtest", {}).get("sharpe") is not None:
            results[product_id] = ParamGate.check(product_id)
    return results

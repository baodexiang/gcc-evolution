"""
GCC v4.5 — Product Parameters Module
KEY-001 P0: Parameter configuration infrastructure.

Manages per-product YAML parameter files with:
- Structured schema (entry / risk / regime / targets / backtest)
- Loader with validation and fallback defaults
- Gate checker comparing backtest results vs targets
- CLI integration (gcc-evo params)

Usage:
    # Load params for a product
    params = ParamStore.load("SPY")

    # Run gate check after backtest
    gate = ParamGate.check("SPY")
    if gate.passed:
        print("Ready to deploy")
    else:
        print(gate.report())

    # Update backtest results
    ParamStore.update_backtest("SPY", {
        "sharpe": 2.3, "max_dd_pct": 12, "win_rate": 0.58, ...
    })
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Default Schema ──────────────────────────────────────────

DEFAULT_PARAMS = {
    "symbol": "",
    "market": "US_STOCK",       # US_STOCK | CRYPTO
    "timeframe": "4h",
    "trend_tf": "16h",

    "entry": {
        "atr_period": 14,
        "atr_multiplier": 2.0,
        "efficiency_ratio_period": 10,
        "kama_fast": 2,
        "kama_slow": 30,
        "chan_buy_signals": [1, 2],
        "chan_divergence": True,
        "choppiness_threshold": 61.8,
        "x4_lookback": 20,
        "n_structure_enabled": True,
        "n_structure_min_ratio": 0.5,
    },

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

# Crypto products get relaxed defaults
CRYPTO_OVERRIDES = {
    "targets": {
        "sharpe_min": 1.5,
        "max_dd_pct": 20,
        "win_rate_min": 0.50,
        "calmar_min": 1.0,
        "sortino_min": 1.5,
        "cagr_min": 0.30,
    },
    "risk": {
        "max_position_pct": 60,
        "stop_loss_atr_mult": 2.0,
        "trailing_atr_mult": 2.5,
        "max_drawdown_pct": 20,
    },
}

# Known products with market type
KNOWN_PRODUCTS = {
    "SPY": "US_STOCK", "QQQ": "US_STOCK", "IWM": "US_STOCK",
    "DIA": "US_STOCK", "AAPL": "US_STOCK", "MSFT": "US_STOCK",
    "BTC": "CRYPTO", "ETH": "CRYPTO", "SOL": "CRYPTO",
    "DOGE": "CRYPTO", "ADA": "CRYPTO", "AVAX": "CRYPTO",
}


# ── Param Store ─────────────────────────────────────────────

class ParamStore:
    """
    Per-product YAML parameter manager.
    Files stored in .gcc/params/{SYMBOL}.yaml
    """

    PARAMS_DIR = ".gcc/params"

    @classmethod
    def path_for(cls, symbol: str) -> Path:
        return Path(cls.PARAMS_DIR) / f"{symbol.upper()}.yaml"

    @classmethod
    def exists(cls, symbol: str) -> bool:
        return cls.path_for(symbol).exists()

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
    def load(cls, symbol: str) -> dict:
        """
        Load params for a product.
        Falls back to defaults if file missing or fields incomplete.
        """
        symbol = symbol.upper()
        path = cls.path_for(symbol)

        # Start with defaults
        params = copy.deepcopy(DEFAULT_PARAMS)
        params["symbol"] = symbol

        # Auto-detect market
        market = KNOWN_PRODUCTS.get(symbol, "US_STOCK")
        params["market"] = market

        # Apply crypto overrides if applicable
        if market == "CRYPTO":
            for section, overrides in CRYPTO_OVERRIDES.items():
                if section in params:
                    params[section].update(overrides)

        # Load from file if exists
        if path.exists() and yaml:
            try:
                file_data = yaml.safe_load(path.read_text("utf-8"))
                if file_data and isinstance(file_data, dict):
                    cls._deep_merge(params, file_data)
            except Exception as e:
                logger.warning("[PARAMS] Failed to load params file for %s, using defaults: %s", symbol, e)

        return params

    @classmethod
    def save(cls, symbol: str, params: dict) -> Path:
        """Save params to YAML file."""
        symbol = symbol.upper()
        path = cls.path_for(symbol)
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
    def init_product(cls, symbol: str, market: str = "") -> Path:
        """Initialize a new product YAML from defaults."""
        symbol = symbol.upper()
        if not market:
            market = KNOWN_PRODUCTS.get(symbol, "US_STOCK")

        params = copy.deepcopy(DEFAULT_PARAMS)
        params["symbol"] = symbol
        params["market"] = market

        if market == "CRYPTO":
            for section, overrides in CRYPTO_OVERRIDES.items():
                if section in params:
                    params[section].update(overrides)

        return cls.save(symbol, params)

    @classmethod
    def update_backtest(cls, symbol: str, results: dict) -> Path:
        """Update backtest results in YAML after optimization."""
        params = cls.load(symbol)
        bt = params.get("backtest", {})
        bt.update(results)
        bt["updated_at"] = _now()
        params["backtest"] = bt
        return cls.save(symbol, params)

    @classmethod
    def update_param(cls, symbol: str, section: str, key: str, value: Any) -> Path:
        """Update a single parameter."""
        params = cls.load(symbol)
        if section in params and isinstance(params[section], dict):
            params[section][key] = value
        return cls.save(symbol, params)

    @classmethod
    def diff(cls, symbol: str, old_params: dict | None = None) -> list[dict]:
        """
        Compare current params vs previous version.
        Returns list of changes.
        """
        current = cls.load(symbol)
        if old_params is None:
            # Compare against defaults
            market = current.get("market", "US_STOCK")
            old_params = copy.deepcopy(DEFAULT_PARAMS)
            if market == "CRYPTO":
                for s, o in CRYPTO_OVERRIDES.items():
                    if s in old_params:
                        old_params[s].update(o)

        changes = []
        for section in ("entry", "risk", "regime", "targets"):
            curr_sec = current.get(section, {})
            old_sec = old_params.get(section, {})
            for k in set(list(curr_sec.keys()) + list(old_sec.keys())):
                cv = curr_sec.get(k)
                ov = old_sec.get(k)
                if cv != ov:
                    changes.append({
                        "section": section, "param": k,
                        "old": ov, "new": cv,
                    })
        return changes

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
    symbol: str
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
            f"═══ Gate Check: {self.symbol} ═══",
            f"Result: {'✅ PASSED' if self.passed else '❌ FAILED'}",
            f"Pass Rate: {self.pass_rate:.0%} (Required: {self.required_pass_rate:.0%})",
            "",
        ]
        for c in self.checks:
            icon = "✓" if c.passed else "✗"
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
            lines.append("  ⚠ Regression detected:")
            for d in self.regression_details:
                lines.append(f"    - {d}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
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
    def check(cls, symbol: str, previous_backtest: dict | None = None) -> ParamGateResult:
        """
        Run full gate check for a product.
        Compares backtest results vs targets.
        Optionally checks regression vs previous backtest.
        """
        params = ParamStore.load(symbol)
        targets = params.get("targets", {})
        backtest = params.get("backtest", {})

        result = ParamGateResult(symbol=symbol.upper())

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
        path = vdir / f"params_{result.symbol}_{ts}.json"
        path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def quick_status(cls, symbol: str) -> str:
        """One-line status for dashboard display."""
        params = ParamStore.load(symbol)
        bt = params.get("backtest", {})
        targets = params.get("targets", {})

        if bt.get("sharpe") is None:
            return f"{symbol}: no backtest data"

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
                checks.append("✓" if v >= t else "✗")
            else:
                checks.append("✓" if v <= t else "✗")

        sharpe = bt.get("sharpe", 0)
        dd = bt.get("max_dd_pct", 0)
        wr = bt.get("win_rate", 0)

        status = "".join(checks)
        return f"{symbol} [{status}] Sharpe={sharpe:.2f} DD={dd:.1f}% WR={wr:.0%}"


# ── Batch Operations ────────────────────────────────────────

def init_all_products() -> list[str]:
    """Initialize param files for all known products."""
    created = []
    for symbol, market in KNOWN_PRODUCTS.items():
        if not ParamStore.exists(symbol):
            ParamStore.init_product(symbol, market)
            created.append(symbol)
    return created


def gate_check_all() -> dict[str, ParamGateResult]:
    """Run gate check on all products with backtest data."""
    results = {}
    for symbol in ParamStore.list_products():
        params = ParamStore.load(symbol)
        if params.get("backtest", {}).get("sharpe") is not None:
            results[symbol] = ParamGate.check(symbol)
    return results

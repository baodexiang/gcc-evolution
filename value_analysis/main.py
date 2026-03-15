from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .api_contract import build_single_symbol_response
from .batch_jobs import BatchJobStore
from .composite import compute_composite_score
from .data_fetcher import (
    QuotaBudget,
    ValueDataCache,
    fetch_live_profile,
    fetch_openbb_profile,
    mark_degraded,
)
from .engine import analyze_value_profile
from .dcf_model import compute_dcf, DCFResult
from .peer_ranking import compute_peer_ranking
from .momentum import compute_momentum_layer
from .quality import evaluate_quality_layer
from .validation import acceptance_gate, compute_ic, summarize_ic
from .valuation import compute_valuation_layer


ROOT = Path(__file__).resolve().parent.parent
LOG_SERVER = ROOT / "logs" / "server.log"
LOG_VALUE = ROOT / "logs" / "value_analysis.log"
STATE_FILE = ROOT / "state" / "value_analysis_validation.json"
INPUTS_FILE = ROOT / "state" / "value_analysis_inputs.json"
LATEST_FILE = ROOT / "state" / "value_analysis_latest.json"


DEFAULT_VALUATION_WEIGHTS: Dict[str, float] = {
    "pe": 0.30,
    "pb": 0.20,
    "ev_ebitda": 0.25,
    "fcf_yield": 0.25,
}

DEFAULT_MOMENTUM_WEIGHTS: Dict[str, float] = {
    "ret_1m": 0.30,
    "ret_3m": 0.35,
    "ret_6m": 0.35,
}

DEFAULT_PROFITABILITY_WEIGHTS: Dict[str, float] = {
    "roe": 0.30,
    "roa": 0.20,
    "operating_margin": 0.25,
    "gross_margin": 0.25,
}

DEFAULT_BALANCE_WEIGHTS: Dict[str, float] = {
    "current_ratio": 0.40,
    "debt_to_equity": 0.40,
    "debt_to_assets": 0.20,
}

DEFAULT_CASHFLOW_WEIGHTS: Dict[str, float] = {
    "fcf_yield": 0.50,
    "ocf_margin": 0.50,
}

DEFAULT_SYMBOL_PROFILES: Dict[str, Dict[str, Any]] = {
    "TSLA": {
        "valuation_scores": {"pe": -0.6, "pb": -1.0, "ev_ebitda": -0.3, "fcf_yield": 0.2},
        "momentum_scores": {"ret_1m": 0.6, "ret_3m": 0.3, "ret_6m": 0.2},
        "audit_opinion": "standard",
        "altman_z": 3.4,
    },
    "AMD": {
        "valuation_scores": {"pe": -0.2, "pb": -0.6, "ev_ebitda": -0.1, "fcf_yield": 0.4},
        "momentum_scores": {"ret_1m": 0.5, "ret_3m": 0.4, "ret_6m": 0.6},
        "audit_opinion": "standard",
        "altman_z": 2.9,
    },
    "PLTR": {
        "valuation_scores": {"pe": -1.4, "pb": -1.6, "ev_ebitda": -0.8, "fcf_yield": 0.3},
        "momentum_scores": {"ret_1m": 0.7, "ret_3m": 0.8, "ret_6m": 1.1},
        "audit_opinion": "standard",
        "altman_z": 2.2,
    },
    "BTCUSDC": {
        "valuation_scores": {"pe": 0.0, "pb": 0.0, "ev_ebitda": 0.0, "fcf_yield": 0.0},
        "momentum_scores": {"ret_1m": 1.0, "ret_3m": 1.1, "ret_6m": 0.8},
        "audit_opinion": "standard",
        "altman_z": 3.0,
    },
    "ETHUSDC": {
        "valuation_scores": {"pe": 0.0, "pb": 0.0, "ev_ebitda": 0.0, "fcf_yield": 0.0},
        "momentum_scores": {"ret_1m": 0.7, "ret_3m": 0.9, "ret_6m": 0.6},
        "audit_opinion": "standard",
        "altman_z": 3.0,
    },
}


@dataclass(frozen=True)
class ModuleCheck:
    task_id: str
    name: str
    run: Callable[[], str]


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(line: str) -> None:
    LOG_SERVER.parent.mkdir(parents=True, exist_ok=True)
    LOG_VALUE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_SERVER.open("a", encoding="utf-8") as f_server:
        f_server.write(line + "\n")
    with LOG_VALUE.open("a", encoding="utf-8") as f_value:
        f_value.write(line + "\n")


def _log_key003(message: str) -> None:
    _append_log(f"{_now_local()} [INFO] {message}")


def _safe_json_load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _coerce_score_map(value: Any) -> Dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, float] = {}
    for key, item in value.items():
        try:
            out[str(key)] = float(item)
        except Exception:
            continue
    return out


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _cross_section_impute_profiles(symbols: List[str], profiles: Dict[str, Dict[str, Any]]) -> None:
    metric_to_score: List[Tuple[str, str, str]] = [
        ("pe", "valuation_scores", "pe"),
        ("pb", "valuation_scores", "pb"),
        ("ev_ebitda", "valuation_scores", "ev_ebitda"),
        ("fcf_yield", "valuation_scores", "fcf_yield"),
        ("roe", "profitability_scores", "roe"),
        ("roa", "profitability_scores", "roa"),
        ("operating_margin", "profitability_scores", "operating_margin"),
        ("gross_margin", "profitability_scores", "gross_margin"),
        ("current_ratio", "balance_scores", "current_ratio"),
        ("debt_to_equity", "balance_scores", "debt_to_equity"),
        ("debt_to_assets", "balance_scores", "debt_to_assets"),
        ("ocf_margin", "cashflow_scores", "ocf_margin"),
    ]

    medians: Dict[Tuple[str, str], float] = {}
    for raw_key, score_bucket, score_key in metric_to_score:
        pool: List[float] = []
        for symbol in symbols:
            profile = profiles[symbol]
            if symbol.endswith("USDC"):
                continue
            raw = profile.get("raw_metrics", {}) or {}
            if raw.get(raw_key) is None:
                continue
            score_map = profile.get(score_bucket, {}) or {}
            val = score_map.get(score_key)
            if isinstance(val, (int, float)):
                pool.append(float(val))
        medians[(score_bucket, score_key)] = _median(pool)

    for symbol in symbols:
        profile = profiles[symbol]
        if symbol.endswith("USDC"):
            continue
        raw = profile.get("raw_metrics", {}) or {}
        imputed: List[str] = []
        for raw_key, score_bucket, score_key in metric_to_score:
            if raw.get(raw_key) is not None:
                continue
            score_map = profile.get(score_bucket, {})
            if not isinstance(score_map, dict):
                continue
            score_map[score_key] = float(medians.get((score_bucket, score_key), 0.0))
            imputed.append(raw_key)

        if imputed:
            raw["imputed_fields"] = sorted(imputed)
            raw["imputation_mode"] = "cross_section_median"


def _rank(values: List[float]) -> List[float]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j - 1) / 2.0 + 1.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def _pearson(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n == 0 or n != len(y):
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den_x = sum((a - mx) ** 2 for a in x)
    den_y = sum((b - my) ** 2 for b in y)
    den = (den_x * den_y) ** 0.5
    if den == 0:
        return 0.0
    return num / den


def _spearman(x: List[float], y: List[float]) -> float:
    return _pearson(_rank(x), _rank(y))


def _stddev(values: List[float]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return var ** 0.5


def _apply_sector_neutral_adjustment(symbols: List[str], profiles: Dict[str, Dict[str, Any]]) -> None:
    sector_groups: Dict[str, List[str]] = {}
    for symbol in symbols:
        if symbol.endswith("USDC"):
            continue
        profile = profiles.get(symbol)
        if not isinstance(profile, dict):
            continue
        raw = profile.get("raw_metrics", {}) or {}
        sector = raw.get("sector")
        if not isinstance(sector, str) or not sector.strip():
            sector = "UNKNOWN"
        sector_groups.setdefault(sector, []).append(symbol)

    target_metrics: List[Tuple[str, str]] = [
        ("valuation_scores", "pe"),
        ("valuation_scores", "pb"),
        ("valuation_scores", "ev_ebitda"),
        ("valuation_scores", "fcf_yield"),
        ("profitability_scores", "roe"),
        ("profitability_scores", "roa"),
        ("profitability_scores", "operating_margin"),
        ("profitability_scores", "gross_margin"),
    ]

    for sector, members in sector_groups.items():
        if len(members) < 3:
            continue

        for bucket, key in target_metrics:
            vals: List[float] = []
            for symbol in members:
                profile = profiles[symbol]
                score_map = profile.get(bucket, {}) or {}
                val = score_map.get(key)
                if isinstance(val, (int, float)):
                    vals.append(float(val))

            if len(vals) < 3:
                continue

            mu = sum(vals) / len(vals)
            sigma = _stddev(vals)
            if sigma < 1e-6:
                continue

            for symbol in members:
                profile = profiles[symbol]
                score_map = profile.get(bucket, {}) or {}
                val = score_map.get(key)
                if not isinstance(val, (int, float)):
                    continue
                z = (float(val) - mu) / sigma
                score_map[key] = _clip(z, -2.0, 2.0)
                raw = profile.get("raw_metrics", {}) or {}
                fields = raw.get("sector_neutralized_fields")
                if not isinstance(fields, list):
                    fields = []
                field_key = f"{bucket}.{key}"
                if field_key not in fields:
                    fields.append(field_key)
                raw["sector_neutralized_fields"] = fields
                raw["sector_neutralized"] = True
                raw["sector_group_size"] = len(members)
                raw["sector_name"] = sector


def _profile_for_symbol(
    ticker: str,
    source: str = "template",
    strict_live: bool = False,
) -> Dict[str, Any]:
    symbol = _normalize_ticker(ticker)

    if source == "openbb":
        try:
            profile_ob = fetch_openbb_profile(symbol)
            valuation_weights = _coerce_score_map(profile_ob.get("valuation_weights")) or dict(DEFAULT_VALUATION_WEIGHTS)
            momentum_weights = _coerce_score_map(profile_ob.get("momentum_weights")) or dict(DEFAULT_MOMENTUM_WEIGHTS)
            return {
                "source": str(profile_ob.get("source", "openbb")),
        "valuation_scores": _coerce_score_map(profile_ob.get("valuation_scores")),
        "valuation_weights": valuation_weights,
        "momentum_scores": _coerce_score_map(profile_ob.get("momentum_scores")),
        "momentum_weights": momentum_weights,
        "profitability_scores": _coerce_score_map(profile_ob.get("profitability_scores")),
        "profitability_weights": _coerce_score_map(profile_ob.get("profitability_weights"))
        or dict(DEFAULT_PROFITABILITY_WEIGHTS),
        "balance_scores": _coerce_score_map(profile_ob.get("balance_scores")),
        "balance_weights": _coerce_score_map(profile_ob.get("balance_weights"))
        or dict(DEFAULT_BALANCE_WEIGHTS),
        "cashflow_scores": _coerce_score_map(profile_ob.get("cashflow_scores")),
        "cashflow_weights": _coerce_score_map(profile_ob.get("cashflow_weights"))
        or dict(DEFAULT_CASHFLOW_WEIGHTS),
                "audit_opinion": str(profile_ob.get("audit_opinion", "standard")),
                "altman_z": float(profile_ob.get("altman_z", 2.0)),
                "quality_key_missing": bool(profile_ob.get("quality_key_missing", False)),
                "confidence_score": float(profile_ob.get("confidence_score", 0.60)),
                "missing_raw_fields": list(profile_ob.get("missing_raw_fields", [])),
                "raw_metrics": profile_ob.get("raw_metrics", {}),
            }
        except Exception as exc:
            if strict_live:
                raise
            _log_key003(
                f"[KEY-003][OPENBB][FALLBACK] ticker={symbol} reason={exc} -> template"
            )
            source = "template"

    if source == "live":
        try:
            live_profile = fetch_live_profile(symbol)
            valuation_weights = _coerce_score_map(live_profile.get("valuation_weights")) or dict(DEFAULT_VALUATION_WEIGHTS)
            momentum_weights = _coerce_score_map(live_profile.get("momentum_weights")) or dict(DEFAULT_MOMENTUM_WEIGHTS)
            return {
                "source": str(live_profile.get("source", "live")),
                "valuation_scores": _coerce_score_map(live_profile.get("valuation_scores")),
                "valuation_weights": valuation_weights,
                "momentum_scores": _coerce_score_map(live_profile.get("momentum_scores")),
                "momentum_weights": momentum_weights,
                "profitability_scores": _coerce_score_map(live_profile.get("profitability_scores")),
                "profitability_weights": _coerce_score_map(live_profile.get("profitability_weights"))
                or dict(DEFAULT_PROFITABILITY_WEIGHTS),
                "balance_scores": _coerce_score_map(live_profile.get("balance_scores")),
                "balance_weights": _coerce_score_map(live_profile.get("balance_weights"))
                or dict(DEFAULT_BALANCE_WEIGHTS),
                "cashflow_scores": _coerce_score_map(live_profile.get("cashflow_scores")),
                "cashflow_weights": _coerce_score_map(live_profile.get("cashflow_weights"))
                or dict(DEFAULT_CASHFLOW_WEIGHTS),
                "audit_opinion": str(live_profile.get("audit_opinion", "standard")),
                "altman_z": float(live_profile.get("altman_z", 2.0)),
                "quality_key_missing": bool(live_profile.get("quality_key_missing", False)),
                "confidence_score": float(live_profile.get("confidence_score", 0.60)),
                "missing_raw_fields": list(live_profile.get("missing_raw_fields", [])),
                "raw_metrics": live_profile.get("raw_metrics", {}),
            }
        except Exception as exc:
            if strict_live:
                raise
            _log_key003(
                f"[KEY-003][LIVE][FALLBACK] ticker={symbol} reason={exc} -> template"
            )
            source = "template"

    custom = _safe_json_load(INPUTS_FILE)
    profile: Dict[str, Any] = {}
    source = "default"

    if symbol in custom and isinstance(custom[symbol], dict):
        profile = dict(custom[symbol])
        source = "state.value_analysis_inputs"
    elif symbol in DEFAULT_SYMBOL_PROFILES:
        profile = dict(DEFAULT_SYMBOL_PROFILES[symbol])
    else:
        profile = {
            "valuation_scores": {"pe": 0.0, "pb": 0.0, "ev_ebitda": 0.0, "fcf_yield": 0.0},
            "momentum_scores": {"ret_1m": 0.0, "ret_3m": 0.0, "ret_6m": 0.0},
            "profitability_scores": {},
            "balance_scores": {},
            "cashflow_scores": {},
            "audit_opinion": "standard",
            "altman_z": 2.0,
            "quality_key_missing": True,
        }

    valuation_weights = _coerce_score_map(profile.get("valuation_weights")) or dict(DEFAULT_VALUATION_WEIGHTS)
    momentum_weights = _coerce_score_map(profile.get("momentum_weights")) or dict(DEFAULT_MOMENTUM_WEIGHTS)
    profitability_weights = _coerce_score_map(profile.get("profitability_weights")) or dict(DEFAULT_PROFITABILITY_WEIGHTS)
    balance_weights = _coerce_score_map(profile.get("balance_weights")) or dict(DEFAULT_BALANCE_WEIGHTS)
    cashflow_weights = _coerce_score_map(profile.get("cashflow_weights")) or dict(DEFAULT_CASHFLOW_WEIGHTS)

    return {
        "source": source,
        "valuation_scores": _coerce_score_map(profile.get("valuation_scores")),
        "valuation_weights": valuation_weights,
        "momentum_scores": _coerce_score_map(profile.get("momentum_scores")),
        "momentum_weights": momentum_weights,
        "profitability_scores": _coerce_score_map(profile.get("profitability_scores")),
        "profitability_weights": profitability_weights,
        "balance_scores": _coerce_score_map(profile.get("balance_scores")),
        "balance_weights": balance_weights,
        "cashflow_scores": _coerce_score_map(profile.get("cashflow_scores")),
        "cashflow_weights": cashflow_weights,
        "audit_opinion": str(profile.get("audit_opinion", "standard")),
        "altman_z": float(profile.get("altman_z", 2.0)),
        "quality_key_missing": bool(profile.get("quality_key_missing", False)),
        "confidence_score": float(profile.get("confidence_score", 0.70 if source == "state.value_analysis_inputs" else 0.55)),
        "missing_raw_fields": list(profile.get("missing_raw_fields", [])),
        "raw_metrics": profile.get("raw_metrics", {}),
    }


def _build_symbol_payload(
    ticker: str,
    as_of: str,
    source: str = "template",
    strict_live: bool = False,
) -> Dict[str, Any]:
    symbol = _normalize_ticker(ticker)
    profile = _profile_for_symbol(symbol, source=source, strict_live=strict_live)
    return _build_symbol_payload_from_profile(symbol=symbol, as_of=as_of, profile=profile)


def _build_symbol_payload_from_profile(
    symbol: str,
    as_of: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    # GCC-0004: 提取DCF peer-ranked score (如有)
    _dcf_scores = profile.get("dcf_scores", {}) or {}
    _dcf_peer_score = _dcf_scores.get("dcf_discount_pct")

    result = analyze_value_profile(
        valuation_scores=profile["valuation_scores"],
        valuation_weights=profile["valuation_weights"],
        momentum_scores=profile["momentum_scores"],
        momentum_weights=profile["momentum_weights"],
        profitability_scores=profile["profitability_scores"],
        profitability_weights=profile["profitability_weights"],
        balance_scores=profile["balance_scores"],
        balance_weights=profile["balance_weights"],
        cashflow_scores=profile["cashflow_scores"],
        cashflow_weights=profile["cashflow_weights"],
        dcf_score=_dcf_peer_score,
        confidence_score=float(profile.get("confidence_score", 1.0)),
        audit_opinion=profile["audit_opinion"],
        altman_z=profile["altman_z"],
        quality_key_missing=profile["quality_key_missing"],
    )
    payload = build_single_symbol_response(
        ticker=symbol,
        as_of=as_of,
        result=result,
        alerts=[],
    )
    payload["value_label"] = result.composite.valuation_label
    payload["profile_source"] = profile["source"]
    payload["confidence_score"] = float(profile.get("confidence_score", 0.0))
    payload["missing_raw_fields"] = list(profile.get("missing_raw_fields", []))
    payload["inputs"] = {
        "valuation_scores": profile["valuation_scores"],
        "valuation_weights": profile["valuation_weights"],
        "momentum_scores": profile["momentum_scores"],
        "momentum_weights": profile["momentum_weights"],
        "profitability_scores": profile["profitability_scores"],
        "profitability_weights": profile["profitability_weights"],
        "balance_scores": profile["balance_scores"],
        "balance_weights": profile["balance_weights"],
        "cashflow_scores": profile["cashflow_scores"],
        "cashflow_weights": profile["cashflow_weights"],
        "audit_opinion": profile["audit_opinion"],
        "altman_z": profile["altman_z"],
        "quality_key_missing": profile["quality_key_missing"],
        "confidence_score": profile.get("confidence_score", 0.0),
    }
    payload["raw_metrics"] = profile.get("raw_metrics", {})

    # GCC-0003: DCF简化内在价值估算
    raw = profile.get("raw_metrics", {})
    if raw and not symbol.endswith("USDC") and not symbol.endswith("USDT"):
        dcf = compute_dcf(raw)
        if dcf is not None:
            payload["dcf"] = {
                "intrinsic_value": dcf.intrinsic_value,
                "market_cap": dcf.market_cap,
                "discount_pct": dcf.discount_pct,
                "dcf_score": dcf.dcf_score,
                "wacc": dcf.wacc,
                "fcf_current": dcf.fcf_current,
                "fcf_growth": dcf.fcf_growth,
                "terminal_value": dcf.terminal_value,
                "sanity_flags": dcf.sanity_flags,
            }

    return payload


def run_symbol_query(
    ticker: str,
    as_of: str,
    pretty: bool,
    source: str,
    strict_live: bool,
) -> int:
    try:
        payload = _build_symbol_payload(
            ticker=ticker,
            as_of=as_of,
            source=source,
            strict_live=strict_live,
        )
    except Exception as exc:
        print(json.dumps({"ticker": _normalize_ticker(ticker), "source": source, "error": str(exc)}, ensure_ascii=False))
        return 2
    _log_key003(
        f"[KEY-003][SYMBOL] ticker={payload['ticker']} composite={payload['composite_score']:.2f} "
        f"label={payload['value_label']}"
    )
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def run_batch_query(
    tickers: List[str],
    as_of: str,
    pretty: bool,
    source: str,
    strict_live: bool,
) -> int:
    symbols = [_normalize_ticker(item) for item in tickers if item.strip()]
    if not symbols:
        print("No tickers provided")
        return 2

    store = BatchJobStore()
    job_id = f"key003-{int(time.time())}"
    store.create(job_id, symbols)
    store.transition(job_id, "running")

    outputs: List[Dict[str, Any]] = []
    profiles: Dict[str, Dict[str, Any]] = {}
    peer_result: Optional[Dict[str, Any]] = None
    failed = 0

    for symbol in symbols:
        try:
            profiles[symbol] = _profile_for_symbol(symbol, source=source, strict_live=strict_live)
        except Exception as exc:
            failed += 1
            outputs.append({"ticker": symbol, "error": str(exc)})

    if source in {"openbb", "live"} and profiles:
        _cross_section_impute_profiles(symbols=[s for s in symbols if s in profiles], profiles=profiles)
        # GCC-0003: 在peer ranking前计算DCF, 注入raw_metrics供peer ranking排名
        for sym in symbols:
            if sym not in profiles or sym.endswith("USDC") or sym.endswith("USDT"):
                continue
            raw = profiles[sym].get("raw_metrics", {})
            if raw:
                dcf = compute_dcf(raw)
                if dcf is not None:
                    raw["dcf_discount_pct"] = dcf.discount_pct
                    raw["dcf_intrinsic_value"] = dcf.intrinsic_value
                    raw["dcf_sanity_flags"] = dcf.sanity_flags
                    # 初始化dcf_scores桶(peer_ranking会填充)
                    profiles[sym].setdefault("dcf_scores", {})
                    profiles[sym]["dcf_scores"]["dcf_discount_pct"] = dcf.dcf_score
        # GCC-0002: Peer-relative percentile ranking (replaces sector-neutral z-score)
        # comps方法论: 在peer group内百分位排名, 替代绝对线性阈值评分
        valid_syms = [s for s in symbols if s in profiles]
        peer_result = compute_peer_ranking(valid_syms, profiles)
        _log_key003(
            f"[KEY-003][PEER-RANK] equity_metrics={len(peer_result['equity_stats'])} "
            f"crypto_metrics={len(peer_result['crypto_stats'])} "
            f"ranked_symbols={len(peer_result['peer_ranks'])}"
        )

    for symbol in symbols:
        if symbol not in profiles:
            continue
        try:
            outputs.append(_build_symbol_payload_from_profile(symbol=symbol, as_of=as_of, profile=profiles[symbol]))
        except Exception as exc:
            failed += 1
            outputs.append({"ticker": symbol, "error": str(exc)})

    outputs.sort(
        key=lambda item: (
            0 if "composite_score" in item else 1,
            -float(item.get("composite_score", -1e9)),
        )
    )

    status = "success" if failed == 0 else ("partial_success" if failed < len(symbols) else "failed")
    store.transition(job_id, status)
    snapshot = {
        "job": store.snapshot(job_id),
        "as_of": as_of,
        "source": source,
        "strict_live": strict_live,
        "results": outputs,
    }
    # GCC-0002: 附加peer统计和排名到输出
    if peer_result is not None:
        snapshot["peer_stats"] = {
            "equity": peer_result.get("equity_stats", {}),
            "crypto": peer_result.get("crypto_stats", {}),
        }
        snapshot["peer_ranks"] = peer_result.get("peer_ranks", {})
    LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    LATEST_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    _log_key003(
        f"[KEY-003][BATCH] job_id={job_id} symbols={len(symbols)} failed={failed} status={status}"
    )
    if pretty:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(snapshot, ensure_ascii=False))
    return 0 if failed == 0 else 2


def run_calibration(
    tickers: List[str],
    as_of: str,
    source: str,
    strict_live: bool,
    pretty: bool,
) -> int:
    symbols = [_normalize_ticker(item) for item in tickers if item.strip()]
    if not symbols:
        print("No tickers provided")
        return 2

    profiles: Dict[str, Dict[str, Any]] = {}
    errors: List[Dict[str, str]] = []
    for symbol in symbols:
        try:
            profiles[symbol] = _profile_for_symbol(symbol, source=source, strict_live=strict_live)
        except Exception as exc:
            errors.append({"ticker": symbol, "error": str(exc)})

    if source in {"openbb", "live"} and profiles:
        _cross_section_impute_profiles(symbols=[s for s in symbols if s in profiles], profiles=profiles)
        # GCC-0002: calibration也用peer ranking
        compute_peer_ranking([s for s in symbols if s in profiles], profiles)

    rows: List[Dict[str, Any]] = []
    for symbol in symbols:
        profile = profiles.get(symbol)
        if profile is None:
            continue
        result = analyze_value_profile(
            valuation_scores=profile["valuation_scores"],
            valuation_weights=profile["valuation_weights"],
            momentum_scores=profile["momentum_scores"],
            momentum_weights=profile["momentum_weights"],
            profitability_scores=profile["profitability_scores"],
            profitability_weights=profile["profitability_weights"],
            balance_scores=profile["balance_scores"],
            balance_weights=profile["balance_weights"],
            cashflow_scores=profile["cashflow_scores"],
            cashflow_weights=profile["cashflow_weights"],
            confidence_score=float(profile.get("confidence_score", 1.0)),
            audit_opinion=profile["audit_opinion"],
            altman_z=profile["altman_z"],
            quality_key_missing=profile["quality_key_missing"],
        )
        rows.append(
            {
                "ticker": symbol,
                "fundamental": float(result.fundamental_score),
                "momentum": float(result.momentum.normalized_score),
                "risk": float(result.risk_penalty),
                "quality": float(result.quality.factor),
            }
        )

    if len(rows) < 3:
        print(json.dumps({"error": "need at least 3 successful symbols for calibration", "errors": errors}, ensure_ascii=False))
        return 2

    candidates: List[Dict[str, float]] = []
    for fw in [0.60, 0.65, 0.70, 0.75, 0.80]:
        for mw in [0.10, 0.15, 0.20, 0.25, 0.30]:
            rw = round(1.0 - fw - mw, 2)
            if rw < 0.05 or rw > 0.20:
                continue
            comps: List[float] = []
            funds: List[float] = []
            for row in rows:
                raw = fw * row["fundamental"] + mw * row["momentum"] - rw * row["risk"]
                comp = _clip(raw * row["quality"], -10.0, 10.0)
                comps.append(comp)
                funds.append(row["fundamental"])
            corr = _spearman(comps, funds)
            spread = max(comps) - min(comps)
            mean_abs = sum(abs(v) for v in comps) / len(comps)
            objective = corr + 0.05 * spread - 0.03 * mean_abs
            candidates.append(
                {
                    "fundamental_weight": fw,
                    "momentum_weight": mw,
                    "risk_weight": rw,
                    "objective": objective,
                    "spearman_vs_fundamental": corr,
                    "spread": spread,
                    "mean_abs": mean_abs,
                }
            )

    candidates.sort(key=lambda x: x["objective"], reverse=True)
    best = candidates[0]

    payload = {
        "as_of": as_of,
        "source": source,
        "strict_live": strict_live,
        "sample_size": len(rows),
        "recommended_weights": {
            "fundamental": best["fundamental_weight"],
            "momentum": best["momentum_weight"],
            "risk": best["risk_weight"],
        },
        "diagnostics": {
            "spearman_vs_fundamental": best["spearman_vs_fundamental"],
            "spread": best["spread"],
            "mean_abs": best["mean_abs"],
            "objective": best["objective"],
        },
        "top_candidates": candidates[:5],
        "errors": errors,
    }
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def _check_t01_scope_doc() -> str:
    candidates = [
        ROOT / "valueanalysis" / "KEY-003-T01_MVP_scope.md",
        ROOT / "value_analysis" / "valueanalysis" / "KEY-003-T01_MVP_scope.md",
    ]
    scope_doc = next((path for path in candidates if path.exists()), None)
    if scope_doc is None:
        raise AssertionError(f"missing scope doc: {candidates[0]}")
    return "scope doc exists"


def _check_t02_valuation() -> str:
    res = compute_valuation_layer(
        indicator_scores={"pe": 2.0, "pb": -2.0},
        indicator_weights={"pe": 1.0, "pb": 1.0},
    )
    if round(res.raw_score, 6) != 0.0:
        raise AssertionError(f"unexpected raw_score={res.raw_score}")
    if round(res.normalized_score, 6) != 0.0:
        raise AssertionError(f"unexpected normalized_score={res.normalized_score}")
    return "valuation formula validated"


def _check_t03_momentum() -> str:
    res = compute_momentum_layer(
        indicator_scores={"ret_6m": 1.5, "ret_1m": 0.5},
        indicator_weights={"ret_6m": 2.0, "ret_1m": 1.0},
    )
    if res.normalized_score <= 0.0:
        raise AssertionError("momentum normalized score should be positive")
    return "momentum formula validated"


def _check_t04_quality() -> str:
    fail_res = evaluate_quality_layer(audit_opinion="否定", altman_z=2.5)
    if fail_res.is_tradeable:
        raise AssertionError("quality veto failed for negative audit")
    warn_res = evaluate_quality_layer(audit_opinion="标准", altman_z=2.5, key_missing=True)
    if warn_res.status != "Warning":
        raise AssertionError(f"unexpected warning status={warn_res.status}")
    return "quality veto and warning validated"


def _check_t05_composite() -> str:
    res = compute_composite_score(valuation_score=10.0, momentum_score=10.0, quality_factor=1.0)
    if res.valuation_label != "Strong Undervalued":
        raise AssertionError(f"unexpected label={res.valuation_label}")
    # GCC-0004: position_modifier改为连续线性(score=9→1.45, score=10→1.50)
    if not (1.0 <= res.position_modifier <= 1.50):
        raise AssertionError(f"unexpected position_modifier={res.position_modifier}")
    return "composite mapping validated"


def _check_t06_engine() -> str:
    result = analyze_value_profile(
        valuation_scores={"pe": 1.0},
        valuation_weights={"pe": 1.0},
        momentum_scores={"ret_6m": 1.0},
        momentum_weights={"ret_6m": 1.0},
        audit_opinion="标准",
        altman_z=2.2,
        quality_key_missing=False,
    )
    effective = result.effective_max_units(base_max_units=5)
    if not (0 <= effective <= 7):
        raise AssertionError(f"invalid effective_max_units={effective}")
    return "engine integration validated"


def _check_t07_api_contract() -> str:
    result = analyze_value_profile(
        valuation_scores={"pe": 0.5},
        valuation_weights={"pe": 1.0},
        momentum_scores={"ret_6m": 0.5},
        momentum_weights={"ret_6m": 1.0},
        audit_opinion="标准",
        altman_z=2.2,
    )
    payload = build_single_symbol_response(
        ticker="TSLA",
        as_of="2026-02-16",
        result=result,
        alerts=["demo"],
    )
    required = {
        "ticker",
        "as_of",
        "valuation_score",
        "momentum_score",
        "quality_status",
        "composite_score",
        "position_modifier",
        "is_tradeable",
        "missing_fields",
        "alerts",
    }
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise AssertionError(f"missing payload fields: {missing}")
    return "single-symbol api contract validated"


def _check_t08_batch_jobs() -> str:
    store = BatchJobStore()
    store.create("job-1", ["TSLA", "AMD"])
    store.transition("job-1", "running")
    store.transition("job-1", "success")
    snap = store.snapshot("job-1")
    if snap["status"] != "success":
        raise AssertionError(f"unexpected batch status={snap['status']}")
    return "batch job state machine validated"


def _check_t09_data_fetcher() -> str:
    budget = QuotaBudget(daily_limit=2)
    if not budget.consume(1):
        raise AssertionError("quota consume 1 failed")
    if not budget.consume(1):
        raise AssertionError("quota consume 2 failed")
    if budget.consume(1):
        raise AssertionError("quota should be exhausted")
    cache = ValueDataCache()
    cache.set("TSLA", {"ok": True}, ttl_seconds=10)
    if cache.get("TSLA") is None:
        raise AssertionError("cache miss right after set")
    if mark_degraded(0.5) != "degraded":
        raise AssertionError("degraded threshold check failed")
    return "cache quota degraded behavior validated"


def _check_t10_validation() -> str:
    scores = [0.1, 0.2, 0.3, 0.4]
    fwd = [0.01, 0.02, 0.03, 0.04]
    ic = compute_ic(scores, fwd)
    summary = summarize_ic([ic, ic])
    gate = acceptance_gate(summary, threshold=0.05)
    if not gate["passed"]:
        raise AssertionError(f"acceptance gate failed: {gate}")
    return "ic baseline and acceptance gate validated"


def _build_checks() -> List[ModuleCheck]:
    return [
        ModuleCheck("T01", "scope_freeze", _check_t01_scope_doc),
        ModuleCheck("T02", "valuation_layer", _check_t02_valuation),
        ModuleCheck("T03", "momentum_layer", _check_t03_momentum),
        ModuleCheck("T04", "quality_layer", _check_t04_quality),
        ModuleCheck("T05", "composite_mapping", _check_t05_composite),
        ModuleCheck("T06", "engine_integration", _check_t06_engine),
        ModuleCheck("T07", "api_contract", _check_t07_api_contract),
        ModuleCheck("T08", "batch_state_machine", _check_t08_batch_jobs),
        ModuleCheck("T09", "data_fetcher", _check_t09_data_fetcher),
        ModuleCheck("T10", "validation_baseline", _check_t10_validation),
    ]


def run_validation_once() -> Dict[str, object]:
    checks = _build_checks()
    results: List[Dict[str, str]] = []

    _log_key003("[KEY-003][VALIDATION][START] standalone runner started")
    for check in checks:
        try:
            detail = check.run()
            status = "PASS"
            _log_key003(
                f"[KEY-003][VALIDATION][MODULE] {check.task_id} {status} name={check.name} detail={detail}"
            )
        except Exception as exc:
            status = "FAIL"
            detail = str(exc)
            _log_key003(
                f"[KEY-003][VALIDATION][MODULE] {check.task_id} {status} name={check.name} detail={detail}"
            )
            _log_key003(f"[KEY-003][VALIDATION][FAIL] {check.task_id} reason={detail}")

        results.append(
            {
                "task_id": check.task_id,
                "name": check.name,
                "status": status,
                "detail": detail,
            }
        )

    passed = sum(1 for item in results if item["status"] == "PASS")
    total = len(results)
    overall = "PASS" if passed == total else "FAIL"
    _log_key003(f"[KEY-003][VALIDATION][SUMMARY] passed={passed}/{total} overall={overall}")

    payload: Dict[str, object] = {
        "key": "KEY-003",
        "runner": "value_analysis.main",
        "last_run": _now_utc(),
        "passed_modules": passed,
        "total_modules": total,
        "overall": overall,
        "modules": results,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def print_report() -> int:
    if not STATE_FILE.exists():
        print("KEY-003 report unavailable: state/value_analysis_validation.json not found")
        return 1
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    print(
        f"KEY-003 overall={data.get('overall')} passed={data.get('passed_modules')}/{data.get('total_modules')} "
        f"last_run={data.get('last_run')}"
    )
    for item in data.get("modules", []):
        print(f"- {item.get('task_id')} {item.get('status')} {item.get('name')}: {item.get('detail')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="KEY-003 standalone validation runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="run KEY-003 validation")
    validate.add_argument("--watch", action="store_true", help="run validation in loop")
    validate.add_argument("--interval", type=int, default=30, help="watch interval seconds")

    subparsers.add_parser("report", help="print latest validation report")

    symbol = subparsers.add_parser("symbol", help="query one ticker value-analysis result")
    symbol.add_argument("--ticker", required=True, help="ticker code, e.g. TSLA")
    symbol.add_argument("--as-of", default=_now_local()[:10], help="as-of date, e.g. 2026-02-16")
    symbol.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    symbol.add_argument(
        "--source",
        choices=["openbb", "live", "template"],
        default="live",
        help="data source mode (default: live)",
    )
    symbol.add_argument(
        "--strict-live",
        action="store_true",
        help="fail instead of fallback when live source is unavailable",
    )

    batch = subparsers.add_parser("batch", help="query multiple tickers and persist latest snapshot")
    batch.add_argument("--tickers", required=True, help="comma-separated tickers, e.g. TSLA,AMD,PLTR")
    batch.add_argument("--as-of", default=_now_local()[:10], help="as-of date, e.g. 2026-02-16")
    batch.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    batch.add_argument(
        "--source",
        choices=["openbb", "live", "template"],
        default="live",
        help="data source mode (default: live)",
    )
    batch.add_argument(
        "--strict-live",
        action="store_true",
        help="fail per ticker instead of fallback when live source is unavailable",
    )

    calibrate = subparsers.add_parser("calibrate", help="calibrate fundamental/momentum/risk weights")
    calibrate.add_argument("--tickers", required=True, help="comma-separated tickers")
    calibrate.add_argument("--as-of", default=_now_local()[:10], help="as-of date")
    calibrate.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    calibrate.add_argument(
        "--source",
        choices=["openbb", "live", "template"],
        default="openbb",
        help="data source mode for calibration",
    )
    calibrate.add_argument(
        "--strict-live",
        action="store_true",
        help="fail instead of fallback when live source is unavailable",
    )

    args = parser.parse_args()
    if args.command == "report":
        return print_report()

    if args.command == "symbol":
        return run_symbol_query(
            ticker=args.ticker,
            as_of=args.as_of,
            pretty=args.pretty,
            source=args.source,
            strict_live=bool(args.strict_live),
        )

    if args.command == "batch":
        tickers = [item.strip() for item in str(args.tickers).split(",") if item.strip()]
        return run_batch_query(
            tickers=tickers,
            as_of=args.as_of,
            pretty=args.pretty,
            source=args.source,
            strict_live=bool(args.strict_live),
        )

    if args.command == "calibrate":
        tickers = [item.strip() for item in str(args.tickers).split(",") if item.strip()]
        return run_calibration(
            tickers=tickers,
            as_of=args.as_of,
            source=args.source,
            strict_live=bool(args.strict_live),
            pretty=bool(args.pretty),
        )

    if args.command == "validate" and args.watch:
        while True:
            payload = run_validation_once()
            print(
                f"KEY-003 validate overall={payload['overall']} "
                f"passed={payload['passed_modules']}/{payload['total_modules']}"
            )
            time.sleep(max(1, int(args.interval)))

    payload = run_validation_once()
    print(
        f"KEY-003 validate overall={payload['overall']} "
        f"passed={payload['passed_modules']}/{payload['total_modules']}"
    )
    return 0 if payload["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

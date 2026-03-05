"""
KEY-005 Behavioral Finance Enhancement Layer

M01: sentiment ingestion (VIX/FearGreed/LSR/Funding)
M02: feature engineering (normalize/impute/outlier handling)
M03: CSI engine + five-state mapping
M08: DQS scoring + execution gate
M10: A/B attribution counters
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


STATE_DIR = "state"
RUNTIME_FILE = os.path.join(STATE_DIR, "behavior_finance_runtime.json")
AB_FILE = os.path.join(STATE_DIR, "behavior_ab_metrics.json")
DIAG_FILE = os.path.join(STATE_DIR, "behavior_diagnostics.json")


def _safe_json_read(path: str) -> Dict[str, Any]:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _safe_json_write(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _clip(value: float, low: float, high: float) -> float:
    """Clip value to [low, high] range. Handles inverted ranges by normalizing."""
    if low > high:
        low, high = high, low
    return max(low, min(high, value))


def _scale(value: float, low: float, high: float, invert: bool = False) -> float:
    if high <= low:
        return 50.0
    value = _clip(value, low, high)
    ratio = (value - low) / (high - low)
    scaled = ratio * 100.0
    return 100.0 - scaled if invert else scaled


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _get_symbol_value(data: Dict[str, Any], symbol: str, default: float) -> float:
    if not isinstance(data, dict):
        return default
    if symbol in data:
        return _to_float(data.get(symbol), default)
    symbols = data.get("symbols")
    if isinstance(symbols, dict) and symbol in symbols:
        return _to_float(symbols.get(symbol), default)
    return _to_float(data.get("value", default), default)


@dataclass
class RawSentiment:
    vix: float
    fear_greed: float
    long_short_ratio: float
    funding_rate: float
    missing_count: int


def _load_sentiment_sources(symbol: str) -> RawSentiment:
    base = os.path.join(STATE_DIR, "behavior_sources")
    vix_data = _safe_json_read(os.path.join(base, "vix.json"))
    fg_data = _safe_json_read(os.path.join(base, "fear_greed.json"))
    lsr_data = _safe_json_read(os.path.join(base, "lsr.json"))
    fr_data = _safe_json_read(os.path.join(base, "funding_rate.json"))

    # neutral fallbacks when source file not ready
    # Neutral fallback targets to keep CSI near 50 when sources are missing
    vix = _get_symbol_value(vix_data, symbol, 27.5)
    fear_greed = _get_symbol_value(fg_data, symbol, 50.0)
    lsr = _get_symbol_value(lsr_data, symbol, 1.1)
    funding_rate = _get_symbol_value(fr_data, symbol, 0.0)

    missing_count = 0
    if not vix_data:
        missing_count += 1
    if not fg_data:
        missing_count += 1
    if not lsr_data:
        missing_count += 1
    if not fr_data:
        missing_count += 1

    return RawSentiment(
        vix=vix,
        fear_greed=fear_greed,
        long_short_ratio=lsr,
        funding_rate=funding_rate,
        missing_count=missing_count,
    )


def _feature_engineering(raw: RawSentiment) -> Dict[str, float]:
    # outlier handling (winsorization)
    vix = _clip(raw.vix, 8.0, 80.0)
    fear_greed = _clip(raw.fear_greed, 0.0, 100.0)
    lsr = _clip(raw.long_short_ratio, 0.4, 2.2)
    funding = _clip(raw.funding_rate, -0.01, 0.01)

    # normalization to 0..100
    vix_score = _scale(vix, 10.0, 45.0, invert=True)
    fg_score = _scale(fear_greed, 0.0, 100.0, invert=False)

    # contrarian mapping: crowding up means lower score
    lsr_score = _scale(lsr, 0.7, 1.5, invert=True)
    funding_score = _scale(funding, -0.004, 0.004, invert=True)

    return {
        "vix_score": round(vix_score, 2),
        "fear_greed_score": round(fg_score, 2),
        "lsr_score": round(lsr_score, 2),
        "funding_score": round(funding_score, 2),
        "vix_clean": round(vix, 4),
        "fear_greed_clean": round(fear_greed, 4),
        "lsr_clean": round(lsr, 4),
        "funding_clean": round(funding, 6),
    }


def _csi_state(csi: float) -> str:
    if csi < 20:
        return "EXTREME_FEAR"
    if csi < 40:
        return "FEAR"
    if csi < 60:
        return "NEUTRAL"
    if csi < 80:
        return "GREED"
    return "EXTREME_GREED"


def _compute_csi(features: Dict[str, float]) -> Dict[str, Any]:
    weights = {
        "vix_score": 0.30,
        "fear_greed_score": 0.30,
        "lsr_score": 0.20,
        "funding_score": 0.20,
    }
    csi = 0.0
    component = {}
    for k, w in weights.items():
        score = _to_float(features.get(k), 50.0)
        csi += score * w
        component[k] = round(score * w, 2)
    csi = round(_clip(csi, 0.0, 100.0), 2)
    return {
        "csi": csi,
        "csi_state": _csi_state(csi),
        "components": component,
        "weights": weights,
    }


def _compute_hii(symbol: str, features: Dict[str, float]) -> Dict[str, Any]:
    """Herd Intensity Index (M05).

    Scale 0..100, extreme zones:
    - >85 extreme crowding
    - <15 panic capitulation
    """
    base = os.path.join(STATE_DIR, "behavior_sources")
    src = _safe_json_read(os.path.join(base, "herding_inputs.json"))
    symbol_map = src.get("symbols", {}) if isinstance(src, dict) else {}
    row = symbol_map.get(symbol, {}) if isinstance(symbol_map, dict) else {}

    social_sentiment = _clip(_to_float(row.get("social_sentiment"), 50.0), 0.0, 100.0)
    fund_flow_bias = _clip(_to_float(row.get("fund_flow_bias"), 50.0), 0.0, 100.0)

    fear_greed = _to_float(features.get("fear_greed_score"), 50.0)
    lsr_contrarian = _to_float(features.get("lsr_score"), 50.0)
    lsr_crowding = 100.0 - lsr_contrarian

    weights = {
        "fear_greed": 0.35,
        "lsr_crowding": 0.30,
        "social_sentiment": 0.20,
        "fund_flow_bias": 0.15,
    }
    hii = (
        fear_greed * weights["fear_greed"]
        + lsr_crowding * weights["lsr_crowding"]
        + social_sentiment * weights["social_sentiment"]
        + fund_flow_bias * weights["fund_flow_bias"]
    )
    hii = round(_clip(hii, 0.0, 100.0), 2)

    if hii > 85.0:
        state = "EXTREME_CROWDING"
    elif hii < 15.0:
        state = "PANIC_CAPITULATION"
    elif hii >= 65.0:
        state = "CROWDING"
    elif hii <= 35.0:
        state = "UNDEROWNED"
    else:
        state = "BALANCED"

    return {
        "hii": hii,
        "hii_state": state,
        "weights": weights,
        "components": {
            "fear_greed": round(fear_greed, 2),
            "lsr_crowding": round(lsr_crowding, 2),
            "social_sentiment": round(social_sentiment, 2),
            "fund_flow_bias": round(fund_flow_bias, 2),
        },
    }


def _compute_anchor_map(symbol: str) -> Dict[str, Any]:
    """Anchor Map (M06): integer levels + 52w + cost basis anchors."""
    base = os.path.join(STATE_DIR, "behavior_sources")
    src = _safe_json_read(os.path.join(base, "anchor_inputs.json"))
    symbol_map = src.get("symbols", {}) if isinstance(src, dict) else {}
    row = symbol_map.get(symbol, {}) if isinstance(symbol_map, dict) else {}

    current_price = _to_float(row.get("current_price"), 0.0)
    high_52w = _to_float(row.get("high_52w"), current_price)
    low_52w = _to_float(row.get("low_52w"), current_price)
    cost_basis = _to_float(row.get("cost_basis"), current_price)

    if current_price <= 0.0:
        return {
            "enabled": False,
            "reason": "missing current_price",
            "nearest": {},
            "anchors": [],
            "score": 50.0,
        }

    # Integer anchor around current price by magnitude.
    step = 100.0 if current_price >= 1000 else (10.0 if current_price >= 100 else 1.0)
    int_anchor = round(current_price / step) * step

    anchors = [
        {"name": "INTEGER", "price": int_anchor, "base_strength": 0.85},
        {"name": "HIGH_52W", "price": high_52w, "base_strength": 0.75},
        {"name": "LOW_52W", "price": low_52w, "base_strength": 0.75},
        {"name": "COST_BASIS", "price": cost_basis, "base_strength": 0.65},
    ]

    for a in anchors:
        dist_pct = abs(current_price - a["price"]) / max(current_price, 1e-9)
        proximity = _clip(1.0 - dist_pct / 0.08, 0.0, 1.0)  # within 8% keeps influence
        a["distance_pct"] = round(dist_pct * 100.0, 2)
        a["strength"] = round(_clip(a["base_strength"] * 100.0 * proximity, 0.0, 100.0), 2)

    nearest = min(anchors, key=lambda x: abs(current_price - x["price"]))
    score = round(max((a["strength"] for a in anchors), default=0.0), 2)

    return {
        "enabled": True,
        "current_price": round(current_price, 6),
        "nearest": {
            "name": nearest["name"],
            "price": round(_to_float(nearest.get("price"), current_price), 6),
            "distance_pct": nearest["distance_pct"],
            "strength": nearest["strength"],
        },
        "anchors": [
            {
                "name": a["name"],
                "price": round(_to_float(a.get("price"), current_price), 6),
                "distance_pct": a["distance_pct"],
                "strength": a["strength"],
            }
            for a in anchors
        ],
        "score": score,
    }


def _compute_dqs(base_confidence: float, csi: float, action: str) -> Dict[str, Any]:
    base = _clip(base_confidence, 0.0, 1.0) * 100.0
    regime_alignment = 100.0 - abs(csi - 50.0) * 1.6

    action_penalty = 0.0
    if action in ("BUY", "SELL") and (csi < 20.0 or csi > 80.0):
        action_penalty += 8.0
    if base > 85.0 and (csi < 25.0 or csi > 75.0):
        action_penalty += 6.0

    dqs = 0.6 * base + 0.4 * regime_alignment - action_penalty
    dqs = round(_clip(dqs, 0.0, 100.0), 2)

    gate = {
        "half_position": dqs < 60.0,
        "block_new_entry": dqs < 40.0,
    }

    confidence_factor = 1.0
    if dqs <= 40.0:
        confidence_factor = 0.7
    elif dqs < 60.0:
        confidence_factor = 0.85

    return {
        "dqs": dqs,
        "gate": gate,
        "confidence_factor": confidence_factor,
        "base_score": round(base, 2),
        "alignment_score": round(regime_alignment, 2),
        "penalty": round(action_penalty, 2),
    }


def _update_ab_metrics(symbol: str, result: Dict[str, Any], action: str) -> None:
    data = _safe_json_read(AB_FILE)
    if not data:
        data = {
            "version": "1.0",
            "updated_at": "",
            "global": {
                "total_decisions": 0,
                "treatment_decisions": 0,
                "blocked_new_entry": 0,
                "half_position": 0,
            },
            "by_symbol": {},
        }

    by_symbol = data.setdefault("by_symbol", {})
    sym = by_symbol.setdefault(
        symbol,
        {
            "total_decisions": 0,
            "treatment_decisions": 0,
            "blocked_new_entry": 0,
            "half_position": 0,
            "last_action": "",
            "last_dqs": 0.0,
            "last_csi": 50.0,
        },
    )

    gate = result.get("dqs_gate", {})
    is_treatment = bool(gate.get("half_position")) or bool(gate.get("block_new_entry"))

    for bucket in (data["global"], sym):
        bucket["total_decisions"] += 1
        if is_treatment:
            bucket["treatment_decisions"] += 1
        if gate.get("block_new_entry"):
            bucket["blocked_new_entry"] += 1
        if gate.get("half_position"):
            bucket["half_position"] += 1

    sym["last_action"] = action
    sym["last_dqs"] = result.get("dqs", 0.0)
    sym["last_csi"] = result.get("csi", 50.0)

    data["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    _safe_json_write(AB_FILE, data)


def _save_runtime(symbol: str, payload: Dict[str, Any]) -> None:
    state = _safe_json_read(RUNTIME_FILE)
    symbols = state.setdefault("symbols", {})
    symbols[symbol] = payload
    state["updated_at"] = payload.get("updated_at")
    _safe_json_write(RUNTIME_FILE, state)


def _load_diag_state(symbol: str) -> Dict[str, Any]:
    state = _safe_json_read(DIAG_FILE)
    symbols = state.get("symbols", {}) if isinstance(state, dict) else {}
    rec = symbols.get(symbol, {}) if isinstance(symbols, dict) else {}
    history = rec.get("history", []) if isinstance(rec, dict) else []
    if not isinstance(history, list):
        history = []
    return {
        "history": history[-120:],
        "stats": rec.get("stats", {}) if isinstance(rec, dict) else {},
    }


def _save_diag_state(symbol: str, event: Dict[str, Any]) -> None:
    state = _safe_json_read(DIAG_FILE)
    if not state:
        state = {"version": "1.0", "updated_at": "", "timestamp": "", "summary": {}, "symbols": {}}

    symbols = state.setdefault("symbols", {})
    rec = symbols.setdefault(symbol, {"history": [], "stats": {"events": 0, "anti_cheat_fail": 0}})
    
    # Anti-cheat: ensure history is a list (handle malformed state)
    history = rec.get("history", [])
    if not isinstance(history, list):
        history = []
    
    history.append(event)
    if len(history) > 300:
        rec["history"] = history[-300:]
    else:
        rec["history"] = history

    stats = rec.setdefault("stats", {})
    stats["events"] = int(stats.get("events", 0)) + 1
    if event.get("anti_cheat", {}).get("pass", True) is False:
        stats["anti_cheat_fail"] = int(stats.get("anti_cheat_fail", 0)) + 1

    state["updated_at"] = event.get("updated_at")
    state["timestamp"] = event.get("updated_at")
    state["summary"] = {
        "symbols": len(symbols),
        "events": sum(int((v.get("stats", {}) if isinstance(v, dict) else {}).get("events", 0)) for v in symbols.values()),
        "anti_cheat_fail": sum(int((v.get("stats", {}) if isinstance(v, dict) else {}).get("anti_cheat_fail", 0)) for v in symbols.values()),
    }
    _safe_json_write(DIAG_FILE, state)


def _load_bias_inputs(symbol: str) -> Dict[str, float]:
    base = os.path.join(STATE_DIR, "behavior_sources")
    src = _safe_json_read(os.path.join(base, "bias_inputs.json"))
    symbol_map = src.get("symbols", {}) if isinstance(src, dict) else {}
    data = symbol_map.get(symbol, {}) if isinstance(symbol_map, dict) else {}

    return {
        "turnover_deviation": _to_float(data.get("turnover_deviation"), 1.0),
        "volume_deviation": _to_float(data.get("volume_deviation"), 0.0),
        "iv_hv_spread": _to_float(data.get("iv_hv_spread"), 0.0),
        "disposition_index": _to_float(data.get("disposition_index"), 1.0),
        "floating_loss_ratio": _to_float(data.get("floating_loss_ratio"), 0.0),
        "state_age_ratio": _to_float(data.get("state_age_ratio"), 1.0),
    }


def _compute_bias_detectors(
    symbol: str,
    action: str,
    csi: float,
    hii: float,
    dqs: float,
) -> Dict[str, Any]:
    src = _load_bias_inputs(symbol)

    # Confirmation bias: strong action with weak quality alignment.
    confirmation_bias = (action in ("BUY", "SELL")) and (dqs < 55.0) and (abs(csi - 50.0) < 10.0)

    # Overconfidence: elevated turnover + volume + volatility spread.
    overconfidence_bias = (
        src["turnover_deviation"] > 2.0
        or src["volume_deviation"] > 0.8
        or src["iv_hv_spread"] > 0.1
    )

    # Loss aversion: disposition effect + high floating loss.
    loss_aversion_bias = (src["disposition_index"] > 1.5) or (src["floating_loss_ratio"] > 0.6)

    # Herding: from CSI extremes and side-loaded sentiment crowding.
    herding_bias = (hii >= 85.0) or (hii <= 15.0)

    # Anchoring: action taken close to neutral CSI with poor quality can indicate anchor stickiness.
    anchoring_bias = (abs(csi - 50.0) <= 4.0) and (action in ("BUY", "SELL")) and (dqs < 60.0)

    # Recency: state persistence ratio indicates potential over-extrapolation.
    recency_bias = src["state_age_ratio"] > 1.5

    active = {
        "overconfidence": overconfidence_bias,
        "loss_aversion": loss_aversion_bias,
        "herding": herding_bias,
        "anchoring": anchoring_bias,
        "confirmation": confirmation_bias,
        "recency": recency_bias,
    }
    active_count = sum(1 for v in active.values() if v)

    # Bias pressure 0..100, higher means stronger caution.
    pressure = _clip(active_count * 16.0 + max(0.0, abs(hii - 50.0) - 20.0) * 0.6, 0.0, 100.0)

    return {
        "active": active,
        "active_count": active_count,
        "pressure": round(pressure, 2),
        "inputs": src,
    }


def _compute_signal_modulation(
    action: str,
    base_confidence: float,
    csi: float,
    hii: float,
    bias_result: Dict[str, Any],
) -> Dict[str, Any]:
    """M07 signal enhancement and risk modulation.

    Constraint: confidence adjustment per trade must stay within +/-30%.
    """
    pressure = _to_float(bias_result.get("pressure"), 0.0)
    active_count = int(bias_result.get("active_count", 0))

    extreme_penalty = 0.0
    if hii >= 85.0 or hii <= 15.0:
        extreme_penalty += 0.10
    if csi >= 85.0 or csi <= 15.0:
        extreme_penalty += 0.08
    extreme_penalty += min(active_count * 0.03, 0.12)
    extreme_penalty += min(pressure / 500.0, 0.10)

    confidence_multiplier = _clip(1.0 - extreme_penalty, 0.70, 1.30)
    adjusted_confidence = _clip(base_confidence * confidence_multiplier, 0.0, 1.0)

    # Position/risk params only; no independent signal generation.
    position_cap_factor = 1.0
    if pressure >= 70.0:
        position_cap_factor = 0.5
    elif pressure >= 50.0:
        position_cap_factor = 0.75

    stoploss_atr_delta = -0.5 if bias_result.get("active", {}).get("overconfidence", False) else 0.0

    return {
        "enabled": True,
        "action": action,
        "confidence_multiplier": round(confidence_multiplier, 4),
        "adjusted_confidence": round(adjusted_confidence, 4),
        "position_cap_factor": round(position_cap_factor, 2),
        "stoploss_atr_delta": stoploss_atr_delta,
        "risk_mode": "DEFENSIVE" if pressure >= 60.0 else "NORMAL",
    }


def _compute_self_debias_and_anti_cheat(
    symbol: str,
    action: str,
    base_confidence: float,
    adjusted_confidence: float,
    bias_result: Dict[str, Any],
    modulation: Dict[str, Any],
    diag_state: Dict[str, Any],
    csi: float = 50.0,
    hii: float = 50.0,
) -> Dict[str, Any]:
    """M09 self-debias + anti-cheat checks."""
    history = diag_state.get("history", []) if isinstance(diag_state, dict) else []

    # Self-debias: devil's advocate checks.
    recent_actions = [h.get("action") for h in history if isinstance(h, dict) and h.get("action") in ("BUY", "SELL")]
    same_action_streak = 0
    for a in reversed(recent_actions):
        if a == action and action in ("BUY", "SELL"):
            same_action_streak += 1
        else:
            break

    pressure = _to_float(bias_result.get("pressure"), 0.0)
    
    debias_flags = {
        "streak_risk": same_action_streak >= 5,
        "high_bias_pressure": pressure >= 65.0,
        "low_quality_force_action": action in ("BUY", "SELL") and pressure >= 70.0,
        "extreme_csi": csi < 20.0 or csi > 80.0,
        "extreme_hii": hii >= 85.0 or hii <= 15.0,
    }
    debias_score = _clip(100.0 - sum(1 for v in debias_flags.values() if v) * 15.0, 0.0, 100.0)

    # Anti-cheat: ensure modulation stays in contract and no independent signal generated.
    anti_cheat_reasons = []
    conf_delta = abs(adjusted_confidence - base_confidence)
    if conf_delta > 0.30 + 1e-9:
        anti_cheat_reasons.append("confidence_delta_exceeds_30pct")

    conf_mul = _to_float(modulation.get("confidence_multiplier"), 1.0)
    if conf_mul < 0.70 or conf_mul > 1.30:
        anti_cheat_reasons.append("confidence_multiplier_out_of_bounds")

    cap = _to_float(modulation.get("position_cap_factor"), 1.0)
    if cap < 0.5 or cap > 1.0:
        anti_cheat_reasons.append("position_cap_out_of_bounds")

    anti_cheat_pass = len(anti_cheat_reasons) == 0

    return {
        "self_debias": {
            "flags": debias_flags,
            "score": round(debias_score, 2),
            "same_action_streak": same_action_streak,
            "recommendation": "HOLD_OR_REDUCE" if debias_score < 60.0 else "ALLOW",
        },
        "anti_cheat": {
            "pass": anti_cheat_pass,
            "reasons": anti_cheat_reasons,
            "confidence_delta": round(conf_delta, 4),
        },
    }


def evaluate_behavior_finance(
    symbol: str,
    action: str,
    base_confidence: float,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Main entry used by llm_server.

    Returns normalized and persisted behavior assessment.
    """
    now = datetime.utcfromtimestamp(now_ts) if now_ts else datetime.utcnow()
    updated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    raw = _load_sentiment_sources(symbol)
    features = _feature_engineering(raw)
    csi_payload = _compute_csi(features)
    hii_payload = _compute_hii(symbol, features)
    anchor_map = _compute_anchor_map(symbol)
    dqs_payload = _compute_dqs(base_confidence, csi_payload["csi"], action)
    bias_result = _compute_bias_detectors(
        symbol,
        action,
        csi_payload["csi"],
        hii_payload["hii"],
        dqs_payload["dqs"],
    )
    modulation = _compute_signal_modulation(
        action,
        base_confidence,
        csi_payload["csi"],
        hii_payload["hii"],
        bias_result,
    )

    adjusted_confidence = _clip(modulation["adjusted_confidence"] * dqs_payload["confidence_factor"], 0.0, 1.0)
    diag_state = _load_diag_state(symbol)
    m09 = _compute_self_debias_and_anti_cheat(
        symbol,
        action,
        base_confidence,
        adjusted_confidence,
        bias_result,
        modulation,
        diag_state,
        csi_payload["csi"],
        hii_payload["hii"],
    )
    result = {
        "enabled": True,
        "symbol": symbol,
        "action": action,
        "updated_at": updated_at,
        "raw": {
            "vix": raw.vix,
            "fear_greed": raw.fear_greed,
            "long_short_ratio": raw.long_short_ratio,
            "funding_rate": raw.funding_rate,
            "missing_count": raw.missing_count,
        },
        "features": features,
        "csi": csi_payload["csi"],
        "csi_state": csi_payload["csi_state"],
        "csi_components": csi_payload["components"],
        "hii": hii_payload["hii"],
        "hii_state": hii_payload["hii_state"],
        "hii_components": hii_payload["components"],
        "anchor_map": anchor_map,
        "dqs": dqs_payload["dqs"],
        "dqs_gate": dqs_payload["gate"],
        "dqs_explain": {
            "base_score": dqs_payload["base_score"],
            "alignment_score": dqs_payload["alignment_score"],
            "penalty": dqs_payload["penalty"],
        },
        "bias": bias_result,
        "signal_modulation": modulation,
        "self_debias": m09["self_debias"],
        "anti_cheat": m09["anti_cheat"],
        "base_confidence": round(base_confidence, 4),
        "adjusted_confidence": round(adjusted_confidence, 4),
    }

    _save_runtime(symbol, result)
    _update_ab_metrics(symbol, result, action)
    _save_diag_state(
        symbol,
        {
            "updated_at": updated_at,
            "action": action,
            "base_confidence": round(base_confidence, 4),
            "adjusted_confidence": round(adjusted_confidence, 4),
            "bias_pressure": bias_result.get("pressure", 0.0),
            "self_debias": m09["self_debias"],
            "anti_cheat": m09["anti_cheat"],
        },
    )
    return result

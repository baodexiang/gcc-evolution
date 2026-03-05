#!/usr/bin/env python3
"""
modules/key002_regime.py
v1.0  KEY-002 Regime 自适应节奏与止损 (opencode 2026-02-21)

目标：降低 whipsaw 反复反向交易，同时避免系统进入"全 HOLD 低活跃"状态。

5种 Regime：
  REGIME_TREND_LOW_VOL  — 趋势+低波动，宽松节奏
  REGIME_TREND_HIGH_VOL — 趋势+高波动，适度收紧
  REGIME_SIDE_LOW_VOL   — 震荡+低波动，严格节奏
  REGIME_SIDE_HIGH_VOL  — 震荡+高波动，最严格
  REGIME_EVENT_RISK     — 数据异常/突发高波动，全冻结

Phase A: observe-only（phase2_enforce=False），仅记录日志，不真实拦截。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, Literal, Optional, Tuple


Regime = Literal[
    "REGIME_TREND_LOW_VOL",
    "REGIME_TREND_HIGH_VOL",
    "REGIME_SIDE_LOW_VOL",
    "REGIME_SIDE_HIGH_VOL",
    "REGIME_EVENT_RISK",
]

_KEY002_REGIME_STATE  = "state/key002_regime_state.json"
_KEY002_REGIME_LOG    = "state/audit/key002_regime_log.jsonl"
_KEY002_DAILY_REPORT  = "state/key002_daily_report.json"

# Phase B: 真实拦截
_KEY002_PHASE2_ENFORCE = True

# ── 参数矩阵 ────────────────────────────────────────────────────────────────

_REGIME_PARAMS: Dict[str, Dict] = {
    "REGIME_TREND_LOW_VOL": {
        "side_cooldown_hours":   2,
        "entry_threshold":       0.56,
        "atr_multiplier":        1.00,
        "max_trades_per_cycle":  3,
    },
    "REGIME_TREND_HIGH_VOL": {
        "side_cooldown_hours":   4,
        "entry_threshold":       0.62,
        "atr_multiplier":        1.18,
        "max_trades_per_cycle":  2,
    },
    "REGIME_SIDE_LOW_VOL": {
        "side_cooldown_hours":   6,
        "entry_threshold":       0.66,
        "atr_multiplier":        1.12,
        "max_trades_per_cycle":  1,
    },
    "REGIME_SIDE_HIGH_VOL": {
        "side_cooldown_hours":   8,
        "entry_threshold":       0.70,
        "atr_multiplier":        1.28,
        "max_trades_per_cycle":  1,
    },
    "REGIME_EVENT_RISK": {
        "side_cooldown_hours":   12,
        "entry_threshold":       0.75,
        "atr_multiplier":        1.45,
        "max_trades_per_cycle":  0,
    },
}


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class Key002RegimeFeatures:
    symbol:             str
    atr_pct:            float  # ATR / price
    trend_persistence:  float  # 近N根方向一致性 0~1
    flip_count_24h:     int    # 24h 方向翻转次数
    data_staleness_sec: int = 0


@dataclass
class Key002RuntimeParams:
    regime:                 str
    side_cooldown_hours:    int
    entry_threshold:        float
    atr_multiplier:         float
    max_trades_per_cycle:   int
    version:                str = "k002-ra-v1"


# ── Regime 判定 ──────────────────────────────────────────────────────────────

def detect_regime(feat: Key002RegimeFeatures) -> str:
    """
    输入特征 → Regime 字符串。
    data_staleness >= 900s 或 flip_count 异常高 → EVENT_RISK。
    """
    if feat.data_staleness_sec >= 900:
        return "REGIME_EVENT_RISK"

    # atr_pct >= 2.8% → 高波动
    high_vol   = feat.atr_pct >= 0.028
    # trend_persistence < 0.45 或 flip_count >= 3 → 震荡
    side_market = (feat.trend_persistence < 0.45) or (feat.flip_count_24h >= 3)

    if side_market and high_vol:
        return "REGIME_SIDE_HIGH_VOL"
    if side_market and not high_vol:
        return "REGIME_SIDE_LOW_VOL"
    if (not side_market) and high_vol:
        return "REGIME_TREND_HIGH_VOL"
    return "REGIME_TREND_LOW_VOL"


def load_key002_runtime_params(symbol: str, regime: str) -> Key002RuntimeParams:
    cfg = _REGIME_PARAMS.get(regime, _REGIME_PARAMS["REGIME_TREND_LOW_VOL"])
    return Key002RuntimeParams(
        regime=regime,
        side_cooldown_hours=cfg["side_cooldown_hours"],
        entry_threshold=cfg["entry_threshold"],
        atr_multiplier=cfg["atr_multiplier"],
        max_trades_per_cycle=cfg["max_trades_per_cycle"],
    )


# ── 入场门控 ─────────────────────────────────────────────────────────────────

def key002_apply_entry_gate(
    symbol: str,
    raw_conf: float,
    params: Key002RuntimeParams,
) -> Tuple[bool, str]:
    """
    Phase A: observe-only。
    返回 (allowed: bool, reason: str)。
    """
    decision = "pass"

    if params.max_trades_per_cycle == 0:
        decision = "blocked:event_risk_freeze"
    elif raw_conf < params.entry_threshold:
        decision = f"blocked:entry_threshold({raw_conf:.3f}<{params.entry_threshold:.3f})"

    # 写日志（fail-silent）
    _write_regime_log(symbol, params, raw_conf, decision)

    if not _KEY002_PHASE2_ENFORCE:
        return True, f"observe_only:{decision}"

    return (decision == "pass"), decision


def key002_adjust_stoploss(base_atr_stop: float, params: Key002RuntimeParams) -> float:
    """高波动 regime 下放大 ATR 止损距离，减少来回止损。"""
    return round(base_atr_stop * params.atr_multiplier, 6)


# ── 从 market_regime 构建特征 ────────────────────────────────────────────────

def build_features_from_market_regime(
    symbol: str,
    market_regime: Optional[Dict] = None,
) -> Key002RegimeFeatures:
    """
    从 market_regime dict（主程序传入）提取 Key002RegimeFeatures。
    缺字段时用安全默认值。
    """
    if market_regime is None:
        market_regime = {}

    atr_pct = float(market_regime.get("atr_pct", 0.020))
    trend   = str(market_regime.get("current_trend", "SIDE")).upper()
    # trend_persistence: UP/DOWN → 0.65，SIDE → 0.35
    trend_persistence = 0.65 if trend in ("UP", "DOWN") else 0.35
    flip_count = int(market_regime.get("flip_count_24h", 0))
    staleness  = int(market_regime.get("data_staleness_sec", 0))

    return Key002RegimeFeatures(
        symbol=symbol,
        atr_pct=atr_pct,
        trend_persistence=trend_persistence,
        flip_count_24h=flip_count,
        data_staleness_sec=staleness,
    )


# ── 主入口（供 llm_server 调用）─────────────────────────────────────────────

def run_key002_observe(
    symbol: str,
    raw_conf: float,
    market_regime: Optional[Dict] = None,
    base_atr_stop: float = 0.0,
) -> Dict:
    """
    Phase A 入口：evaluate + log，不影响执行。
    返回 dict 含 regime/params/gate_decision/adjusted_stop。
    """
    feat   = build_features_from_market_regime(symbol, market_regime)
    regime = detect_regime(feat)
    params = load_key002_runtime_params(symbol, regime)

    allowed, reason = key002_apply_entry_gate(symbol, raw_conf, params)
    adj_stop = key002_adjust_stoploss(base_atr_stop, params) if base_atr_stop > 0 else None

    result = {
        "symbol":          symbol,
        "ts":              time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "regime":          regime,
        "entry_threshold": params.entry_threshold,
        "atr_multiplier":  params.atr_multiplier,
        "max_trades":      params.max_trades_per_cycle,
        "cooldown_hours":  params.side_cooldown_hours,
        "raw_conf":        raw_conf,
        "gate_decision":   reason,
        "gate_allowed":    allowed,
        "adjusted_stop":   adj_stop,
        "enforce":         _KEY002_PHASE2_ENFORCE,
    }
    return result


# ── 日报分析 ─────────────────────────────────────────────────────────────────

def analyze_key002_daily(day: Optional[str] = None) -> Dict:
    """读取 regime_log，统计当天 regime 分布、拦截原因分布。"""
    regime_dist: Dict[str, int] = {}
    reason_dist: Dict[str, int] = {}

    try:
        if not os.path.exists(_KEY002_REGIME_LOG):
            return {}
        with open(_KEY002_REGIME_LOG, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            try:
                d = json.loads(line.strip())
            except Exception:
                continue
            if day and not d.get("ts", "").startswith(day):
                continue
            r = d.get("regime", "UNKNOWN")
            regime_dist[r] = regime_dist.get(r, 0) + 1
            reason = d.get("gate_decision", "pass")
            reason_dist[reason] = reason_dist.get(reason, 0) + 1

        report = {
            "day":          day or "all",
            "regime_dist":  regime_dist,
            "reason_dist":  reason_dist,
            "total":        sum(regime_dist.values()),
        }
        os.makedirs("state", exist_ok=True)
        with open(_KEY002_DAILY_REPORT, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return report
    except Exception:
        return {}


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _write_regime_log(
    symbol: str,
    params: Key002RuntimeParams,
    raw_conf: float,
    gate_decision: str,
) -> None:
    try:
        os.makedirs(os.path.dirname(_KEY002_REGIME_LOG), exist_ok=True)
        entry = {
            "ts":            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol":        symbol,
            "regime":        params.regime,
            "entry_threshold": params.entry_threshold,
            "atr_multiplier":  params.atr_multiplier,
            "max_trades":    params.max_trades_per_cycle,
            "raw_conf":      raw_conf,
            "gate_decision": gate_decision,
            "enforce":       _KEY002_PHASE2_ENFORCE,
        }
        with open(_KEY002_REGIME_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

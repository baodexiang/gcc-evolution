#!/usr/bin/env python3
"""
KEY-005 ES risk backtest helper.
v2.0  多分位 ES 风控校验 (opencode 2026-02-21)

v1.x: 单 alpha VaR/ES，输出 NORMAL/TIGHTEN
v2.0 新增:
  - 双分位 VaR(97.5%) / VaR(99%) / ES(97.5%)
  - 多分位一致性检验分数 mq_test_score
  - GREEN / YELLOW / RED 三级风险状态
  - 下游联动：YELLOW/RED 自动收紧 KEY-001/002 参数（Phase A observe-only）
  - 按品种独立计算 snapshot
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return f
    except Exception:
        return None


def _quantile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    q = max(0.0, min(1.0, q))
    idx = int((len(sorted_vals) - 1) * q)
    return sorted_vals[idx]


def run_es_risk_backtest(
    log_path: str = "logs/signal_decisions.jsonl",
    out_path: str = "state/risk_es_state.json",
    window_rows: int = 800,
    alpha: float = 0.05,
    breach_alert: float = 0.10,
) -> Dict:
    rows = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue

    if window_rows > 0 and len(rows) > window_rows:
        rows = rows[-window_rows:]

    by_symbol: Dict[str, List[float]] = {}
    for r in rows:
        sym = str(r.get("symbol") or "").strip()
        px = _safe_float(r.get("price"))
        if not sym or px is None or px <= 0:
            continue
        by_symbol.setdefault(sym, []).append(px)

    returns: List[float] = []
    symbol_stats: Dict[str, Dict] = {}
    for sym, prices in by_symbol.items():
        if len(prices) < 2:
            continue
        rs = []
        for i in range(1, len(prices)):
            prev_px = prices[i - 1]
            cur_px = prices[i]
            if prev_px <= 0:
                continue
            ret = (cur_px - prev_px) / prev_px
            rs.append(ret)
            returns.append(ret)
        if rs:
            symbol_stats[sym] = {
                "samples": len(rs),
                "mean_return": round(sum(rs) / len(rs), 6),
            }

    returns_sorted = sorted(returns)
    sample_n = len(returns_sorted)

    if sample_n == 0:
        result = {
            "version": "es-v1",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "no_data",
            "samples": 0,
            "alpha": alpha,
            "var_alpha": None,
            "es_alpha": None,
            "tail_breach_rate": None,
            "model_fail_flag": False,
            "suggested_risk_mode": "NORMAL",
            "source": {"log_path": log_path, "window_rows": window_rows},
            "by_symbol": {},
        }
    else:
        var_alpha = _quantile(returns_sorted, alpha)
        tail = [x for x in returns_sorted if x <= var_alpha]
        es_alpha = sum(tail) / len(tail) if tail else var_alpha
        breach_rate = (len(tail) / sample_n) if sample_n > 0 else 0.0
        model_fail = breach_rate > breach_alert

        result = {
            "version": "es-v1",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "ok",
            "samples": sample_n,
            "alpha": alpha,
            "var_alpha": round(var_alpha, 6),
            "es_alpha": round(es_alpha, 6),
            "tail_breach_rate": round(breach_rate, 6),
            "breach_alert_threshold": breach_alert,
            "model_fail_flag": model_fail,
            "suggested_risk_mode": "TIGHTEN" if model_fail else "NORMAL",
            "source": {"log_path": log_path, "window_rows": window_rows},
            "by_symbol": symbol_stats,
        }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# KEY-005 v2.0: 多分位 ES 风控校验 (opencode 2026-02-21)
# Phase A: observe-only — enforce=False
# ═══════════════════════════════════════════════════════════════════════════

RiskLevel = Literal["GREEN", "YELLOW", "RED"]

_KEY005_ES_STATE   = "state/risk_es_state_v2.json"
_KEY005_ES_LOG     = "state/audit/key005_es_log.jsonl"
_KEY005_OVERRIDES  = "state/key005_overrides.json"

# Phase A: observe-only
_KEY005_ENFORCE = False

# 阈值配置
_YELLOW_MQ_SCORE      = 0.55
_YELLOW_BREACH_975    = 0.040
_RED_MQ_SCORE         = 0.70
_RED_BREACH_975       = 0.060

# 联动参数增量
_YELLOW_ACTIONS = {
    "key002_entry_threshold_delta": +0.03,
    "key002_side_cooldown_delta_h": +2,
    "key001_soft_hold_delta":       -0.02,
}
_RED_ACTIONS = {
    "key002_entry_threshold_delta": +0.06,
    "key002_side_cooldown_delta_h": +4,
    "key001_soft_hold_delta":       -0.04,
    "freeze_new_entry":             True,
}


@dataclass
class Key005RiskSnapshot:
    symbol:          str
    window:          int
    var_975:         float
    var_99:          float
    es_975:          float
    breach_975_rate: float
    breach_99_rate:  float
    mq_test_score:   float
    risk_level:      str   # GREEN / YELLOW / RED
    version:         str = "k005-esmq-v1"
    ts:              str = ""


def calc_var(returns: List[float], alpha: float) -> float:
    """损失视角：返回负收益分位阈值（正数）。alpha=0.975 → 尾部 2.5%。"""
    if not returns:
        return 0.0
    sorted_r = sorted(returns)
    idx = int((1 - alpha) * len(sorted_r))
    idx = max(0, min(idx, len(sorted_r) - 1))
    return abs(sorted_r[idx])


def calc_es(returns: List[float], alpha: float) -> float:
    """Expected Shortfall：超过 VaR 的平均损失。"""
    var = calc_var(returns, alpha)
    tail = [abs(r) for r in returns if r <= -var]
    if not tail:
        return var
    return sum(tail) / len(tail)


def calc_multi_quantile_test_score(
    returns: List[float],
    var_975: float,
    var_99: float,
) -> float:
    """
    多分位一致性检验分数。
    目标理论值：breach_975 ≈ 2.5%，breach_99 ≈ 1%。
    实际超出越多 → score 越高 → 模型越偏乐观。
    score 范围约 0~1。
    """
    n = len(returns)
    if n == 0:
        return 0.0
    b975 = sum(1 for r in returns if r <= -var_975) / n
    b99  = sum(1 for r in returns if r <= -var_99)  / n

    err_975 = max(0.0, b975 - 0.025) / 0.025
    err_99  = max(0.0, b99  - 0.010) / 0.010

    score = 0.6 * min(1.0, err_975) + 0.4 * min(1.0, err_99)
    return round(score, 4)


def classify_risk_level(mq_score: float, breach_975_rate: float) -> str:
    if mq_score >= _RED_MQ_SCORE or breach_975_rate >= _RED_BREACH_975:
        return "RED"
    if mq_score >= _YELLOW_MQ_SCORE or breach_975_rate >= _YELLOW_BREACH_975:
        return "YELLOW"
    return "GREEN"


def build_key005_snapshot(
    symbol: str,
    returns: List[float],
    window: int = 120,
    min_samples: int = 40,
) -> Optional[Key005RiskSnapshot]:
    """
    用滚动窗口 returns[-window:] 构建 Key005RiskSnapshot。
    样本不足 min_samples 返回 None。
    """
    ret = returns[-window:]
    if len(ret) < min_samples:
        return None

    var_975  = calc_var(ret, 0.975)
    var_99   = calc_var(ret, 0.99)
    es_975   = calc_es(ret, 0.975)
    mq_score = calc_multi_quantile_test_score(ret, var_975, var_99)

    n = len(ret)
    b975 = sum(1 for r in ret if r <= -var_975) / n
    b99  = sum(1 for r in ret if r <= -var_99)  / n

    risk = classify_risk_level(mq_score, b975)

    return Key005RiskSnapshot(
        symbol=symbol,
        window=window,
        var_975=round(var_975, 6),
        var_99=round(var_99, 6),
        es_975=round(es_975, 6),
        breach_975_rate=round(b975, 4),
        breach_99_rate=round(b99, 4),
        mq_test_score=mq_score,
        risk_level=risk,
        ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def apply_key005_risk_actions(snapshot: Key005RiskSnapshot) -> Dict:
    """
    Phase A: 只记录联动动作，不真实修改 KEY-001/002 参数。
    返回 action_dict 供观察。
    """
    if snapshot.risk_level == "GREEN":
        actions = {"type": "clear", "symbol": snapshot.symbol}
    elif snapshot.risk_level == "YELLOW":
        actions = {"type": "yellow", "symbol": snapshot.symbol, **_YELLOW_ACTIONS}
    else:
        actions = {"type": "red", "symbol": snapshot.symbol, **_RED_ACTIONS}

    # 写日志（fail-silent）
    try:
        os.makedirs(os.path.dirname(_KEY005_ES_LOG), exist_ok=True)
        entry = {
            "ts":              snapshot.ts,
            "symbol":          snapshot.symbol,
            "risk_level":      snapshot.risk_level,
            "mq_test_score":   snapshot.mq_test_score,
            "breach_975_rate": snapshot.breach_975_rate,
            "var_975":         snapshot.var_975,
            "es_975":          snapshot.es_975,
            "actions":         actions,
            "enforce":         _KEY005_ENFORCE,
        }
        with open(_KEY005_ES_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Phase A: 不实际写 overrides
    if _KEY005_ENFORCE and snapshot.risk_level != "GREEN":
        _write_key005_overrides(snapshot.symbol, actions)

    return actions


def _write_key005_overrides(symbol: str, actions: Dict) -> None:
    """写入 KEY-001/002 override 文件（Phase B+ 才实际生效）。"""
    try:
        existing = {}
        if os.path.exists(_KEY005_OVERRIDES):
            with open(_KEY005_OVERRIDES, encoding="utf-8") as f:
                existing = json.load(f)
        existing[symbol] = actions
        with open(_KEY005_OVERRIDES, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def run_key005_multi_quantile(
    symbol: str,
    returns: List[float],
    window: int = 120,
    min_samples: int = 40,
) -> Dict:
    """
    Phase A 主入口：构建 snapshot，写日志，返回结果 dict。
    """
    snapshot = build_key005_snapshot(symbol, returns, window, min_samples)
    if snapshot is None:
        return {
            "symbol":  symbol,
            "status":  "insufficient_data",
            "enforce": _KEY005_ENFORCE,
        }

    actions = apply_key005_risk_actions(snapshot)

    result = {
        "symbol":          snapshot.symbol,
        "risk_level":      snapshot.risk_level,
        "mq_test_score":   snapshot.mq_test_score,
        "breach_975_rate": snapshot.breach_975_rate,
        "breach_99_rate":  snapshot.breach_99_rate,
        "var_975":         snapshot.var_975,
        "var_99":          snapshot.var_99,
        "es_975":          snapshot.es_975,
        "window":          snapshot.window,
        "samples":         window,
        "actions":         actions,
        "enforce":         _KEY005_ENFORCE,
        "ts":              snapshot.ts,
    }

    # 写到 v2 状态文件
    try:
        os.makedirs("state", exist_ok=True)
        all_state = {}
        if os.path.exists(_KEY005_ES_STATE):
            with open(_KEY005_ES_STATE, encoding="utf-8") as f:
                all_state = json.load(f)
        all_state[symbol] = result
        with open(_KEY005_ES_STATE, "w", encoding="utf-8") as f:
            json.dump(all_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return result

"""
modules/vision_adaptive.py
v1.3  KEY-001 Phase B: Vision AdaptiveNN 真实拦截 + Vision无信号bypass

从 state/vision/pattern_latest.json 读取既有 Vision 输出，
应用 L1→L2→L3 序列门控，产出 KEY-001 审计字段。

Phase A: observe-only，不影响执行链，结果写入 adaptive_log_YYYY-MM-DD.jsonl。

v1.1 审查修复:
  HIGH-1: 修复文件句柄泄漏 (open → with open)
  HIGH-2: 修复同源 confidence 平方问题 (l2_conf 直接用 l1_conf 不再乘 pat_conf)
  HIGH-3: 移除 vision_analyzer.py 中不存在的 BULL_FLAG
  HIGH-4: 集成点异常改为 log_to_server (在 llm_server 侧)
  HIGH-5: JSONL 写入失败记录到结果 dict
  MEDIUM-2: adaptive_log 改为按日期轮转文件
  MEDIUM-4: vol_suspicious 因 HIGH-2 修复后不再是死代码
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

STATE_DIR = "state"
PATTERN_FILE = os.path.join(STATE_DIR, "vision", "pattern_latest.json")


def _adaptive_log_path() -> str:
    """按 NY 日期轮转，避免单文件无限增长"""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        date_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        date_str = time.strftime("%Y-%m-%d")
    return os.path.join(STATE_DIR, "vision", f"adaptive_log_{date_str}.jsonl")


# ── Pattern → signal 映射 (仅含 vision_analyzer.py v3.3 实际输出的 12 种形态) ──
PATTERN_SIGNAL: Dict[str, str] = {
    "DOUBLE_BOTTOM":         "BUY",
    "HEAD_SHOULDERS_BOTTOM": "BUY",
    "REVERSAL_123_BUY":      "BUY",
    "FALSE_BREAK_BUY":       "BUY",
    "ASC_TRIANGLE":          "BUY",
    "WEDGE_FALLING":         "BUY",
    "DOUBLE_TOP":            "SELL",
    "HEAD_SHOULDERS_TOP":    "SELL",
    "REVERSAL_123_SELL":     "SELL",
    "FALSE_BREAK_SELL":      "SELL",
    "DESC_TRIANGLE":         "SELL",
    "WEDGE_RISING":          "SELL",
    "NONE":                  "HOLD",
}

# ── L2 fixation 表 (全 4×3 structure×position 覆盖，无空洞) ──────────────
L2_FIXATION: Dict[tuple, Dict] = {
    ("MARKUP",       "HIGH"): {"bars": 15, "focus": ["HEAD_SHOULDERS_TOP",    "DOUBLE_TOP",            "WEDGE_RISING"]},
    ("MARKUP",       "MID"):  {"bars": 20, "focus": ["ASC_TRIANGLE",          "FALSE_BREAK_BUY",       "REVERSAL_123_BUY"]},
    ("MARKUP",       "LOW"):  {"bars": 30, "focus": ["DOUBLE_BOTTOM",         "REVERSAL_123_BUY",      "FALSE_BREAK_BUY"]},
    ("ACCUMULATION", "HIGH"): {"bars": 25, "focus": ["FALSE_BREAK_SELL",      "REVERSAL_123_SELL",     "DOUBLE_TOP"]},
    ("ACCUMULATION", "MID"):  {"bars": 30, "focus": ["ASC_TRIANGLE",          "DOUBLE_BOTTOM",         "REVERSAL_123_BUY"]},
    ("ACCUMULATION", "LOW"):  {"bars": 40, "focus": ["DOUBLE_BOTTOM",         "HEAD_SHOULDERS_BOTTOM", "REVERSAL_123_BUY"]},
    ("DISTRIBUTION", "HIGH"): {"bars": 30, "focus": ["DOUBLE_TOP",            "HEAD_SHOULDERS_TOP",    "WEDGE_RISING"]},
    ("DISTRIBUTION", "MID"):  {"bars": 25, "focus": ["DESC_TRIANGLE",         "WEDGE_RISING",          "FALSE_BREAK_SELL"]},
    ("DISTRIBUTION", "LOW"):  {"bars": 20, "focus": ["FALSE_BREAK_BUY",       "DOUBLE_BOTTOM",         "REVERSAL_123_BUY"]},
    ("MARKDOWN",     "HIGH"): {"bars": 20, "focus": ["HEAD_SHOULDERS_TOP",    "FALSE_BREAK_SELL",      "DESC_TRIANGLE"]},
    ("MARKDOWN",     "MID"):  {"bars": 20, "focus": ["REVERSAL_123_SELL",     "FALSE_BREAK_SELL",      "WEDGE_FALLING"]},
    ("MARKDOWN",     "LOW"):  {"bars": 15, "focus": ["WEDGE_FALLING",         "FALSE_BREAK_BUY",       "REVERSAL_123_BUY"]},
}
# 兜底（UNKNOWN 或未列举的组合）
L2_DEFAULT = {"bars": 25, "focus": []}


@dataclass
class VisionAdaptiveConfig:
    l1_min_conf:      float = 0.60
    # Phase A: L2 直接继承 L1 conf (l2_conf = l1_conf)，不再乘同源 pat_conf
    # 避免 conf^2 导致几乎所有信号在 FINAL_LOW_CONF 处终止
    l2_min_conf:      float = 0.55
    final_min_conf:   float = 0.55
    reduced_low:      float = 0.55
    reduced_high:     float = 0.75
    none_l3_weight:   float = 0.80
    agree_boost:      float = 1.10
    conflict_penalty: float = 0.70


_DEFAULT_CFG = VisionAdaptiveConfig()


# ── 内部工具函数 ───────────────────────────────────────────────────────────

def _pattern_to_signal(pattern: str) -> str:
    return PATTERN_SIGNAL.get((pattern or "NONE").upper(), "HOLD")


def _stage_to_l3(stage: str, pat_signal: str, vol_ok: bool) -> Tuple[str, float]:
    """从 stage+volume 推导 L3 信号和基础置信度"""
    s = (stage or "NONE").upper()
    if s == "BREAKOUT" and vol_ok:
        return pat_signal, 0.80
    if s == "BREAKOUT" and not vol_ok:
        return pat_signal, 0.60
    if s == "FORMING":
        return "HOLD", 0.50
    return "HOLD", 0.45   # NONE stage


def _fuse(l2_sig: str, l3_sig: str, cfg: VisionAdaptiveConfig) -> Tuple[str, float]:
    """合并 L2/L3 信号，返回 (raw_signal, weight_mult)。覆盖全部 5 种组合：
    1. BUY==BUY 或 SELL==SELL → agree boost
    2. L2 有信号，L3 HOLD → L2 直通，无加权
    3. L2 HOLD，L3 有信号 → 无形态支撑，压制
    4. L2 BUY，L3 SELL（或反向）→ 方向冲突，惩罚
    5. 其余（均 HOLD）→ HOLD
    """
    if l2_sig == l3_sig and l2_sig in ("BUY", "SELL"):
        return l2_sig, cfg.agree_boost
    if l2_sig in ("BUY", "SELL") and l3_sig == "HOLD":
        return l2_sig, 1.0
    if l2_sig == "HOLD" and l3_sig in ("BUY", "SELL"):
        return "HOLD", 1.0
    if {l2_sig, l3_sig} == {"BUY", "SELL"}:
        return "HOLD", cfg.conflict_penalty
    return "HOLD", 1.0


def _terminate(reason: str, layer: str = "?", extra: Optional[Dict] = None) -> Dict:
    """构建终止结果 dict。extra 仅允许覆盖 final_confidence/raw_signal，
    不应覆盖 active_terminated / terminate_reason 等核心字段。"""
    r: Dict[str, Any] = {
        "active_terminated":  True,
        "terminate_reason":   reason,
        "vision_stop_layer":  layer,
        "vision_stop_code":   reason,
        "final_signal":       "HOLD",
        "execution_size":     "SKIP",
        "final_confidence":   0.0,
    }
    if extra:
        # 只允许非核心字段被覆盖
        allowed = {"final_confidence", "raw_signal"}
        r.update({k: v for k, v in extra.items() if k in allowed})
    return r


# ── 主评估函数 ─────────────────────────────────────────────────────────────

def analyze_vision_adaptive(
    symbol: str,
    vision_data: Optional[Dict] = None,
    cfg: VisionAdaptiveConfig = _DEFAULT_CFG,
) -> Dict[str, Any]:
    """
    Phase A: 从既有 Vision pattern_latest 结果派生 L1/L2/L3 审计字段。
    不影响执行，仅供 KEY-001 观察。

    vision_data: 传入则直接用，否则从 pattern_latest.json 读取。
    """
    if vision_data is None:
        try:
            # HIGH-1: 使用 with 确保文件句柄关闭
            with open(PATTERN_FILE, encoding="utf-8", errors="replace") as fh:
                all_p = json.load(fh)
            vision_data = all_p.get(symbol, {})
        except Exception:
            vision_data = {}

    if not vision_data:
        return {"symbol": symbol, "error": "no_vision_data",
                **_terminate("NO_VISION_DATA", "L1")}

    out: Dict[str, Any] = {
        "symbol": symbol,
        "ts":     time.time(),
        "phase":  "A_OBSERVE",
    }

    # ── L1 ─────────────────────────────────────────────────────────────────
    l1_struct = str(vision_data.get("overall_structure", "UNKNOWN")).upper()
    l1_pos    = str(vision_data.get("position",          "MID")).upper()
    l1_conf   = float(vision_data.get("confidence",      0.0))

    out.update({
        "vision_l1_structure":   l1_struct,
        "vision_l1_position":    l1_pos,
        "vision_l1_confidence":  round(l1_conf, 3),
        "vision_l1_terminated":  False,
    })

    if l1_struct == "UNKNOWN" or l1_conf < cfg.l1_min_conf:
        out["vision_l1_terminated"] = True
        out.update(_terminate("L1_UNKNOWN_OR_LOW_CONF", "L1"))
        return out

    # ── L2 ─────────────────────────────────────────────────────────────────
    l2_plan   = L2_FIXATION.get((l1_struct, l1_pos), L2_DEFAULT)
    pattern   = str(vision_data.get("pattern",          "NONE")).upper()
    stage     = str(vision_data.get("stage",            "NONE")).upper()
    vol_ok    = bool(vision_data.get("volume_confirmed", False))

    l2_signal = _pattern_to_signal(pattern)
    # HIGH-2: Phase A 同源限制 — l2_conf 直接继承 l1_conf，
    # 不再乘 pat_conf（同一个 "confidence" 字段），避免 conf^2 虚低
    l2_conf   = l1_conf
    in_focus  = (not l2_plan["focus"]) or (pattern in l2_plan["focus"]) or (pattern == "NONE")

    out.update({
        "vision_l2_fixation_range":   l2_plan["bars"],
        "vision_l2_pattern":          pattern,
        "vision_l2_signal":           l2_signal,
        "vision_l2_in_focus":         in_focus,
        "vision_l2_stage":            stage,
        "vision_l2_volume_confirmed": vol_ok,
        "vision_l2_confidence":       round(l2_conf, 3),
        "vision_l2_terminated":       False,
        # Phase A 注记：L1/L2 使用同一 confidence 字段，Phase B 接独立调用后替换此值
        "vision_l2_phase_a_note":     "same_source_conf",
    })

    # NONE pattern + BREAKOUT stage = 矛盾，终止
    if pattern == "NONE" and stage == "BREAKOUT":
        out["vision_l2_terminated"] = True
        out.update(_terminate("L2_NONE_PATTERN_BREAKOUT", "L2"))
        return out

    if l2_conf < cfg.l2_min_conf and l2_signal != "HOLD":
        out["vision_l2_terminated"] = True
        out.update(_terminate("L2_LOW_CONF", "L2"))
        return out

    # ── L3 ─────────────────────────────────────────────────────────────────
    l3_signal, l3_base_conf = _stage_to_l3(stage, l2_signal, vol_ok)
    l3_conf = l3_base_conf * l2_conf
    if pattern == "NONE":
        l3_conf *= cfg.none_l3_weight

    # vol_suspicious: BREAKOUT 但量能未确认（高-2 修复后此路径可达）
    vol_suspicious = (stage == "BREAKOUT" and not vol_ok)

    out.update({
        "vision_l3_focus":      stage,
        "vision_l3_signal":     l3_signal,
        "vision_l3_confidence": round(l3_conf, 3),
        "volume_suspicious":    vol_suspicious,
    })

    # ── Fusion ─────────────────────────────────────────────────────────────
    raw_signal, weight_mult = _fuse(l2_signal, l3_signal, cfg)
    final_conf = l3_conf * weight_mult

    # vol_suspicious 优先于低置信终止（需先判断，否则 FINAL_LOW_CONF 会提前拦截）
    if vol_suspicious and raw_signal in ("BUY", "SELL"):
        out.update(_terminate("L3_VOLUME_SUSPICIOUS", "L3",
                              {"raw_signal": raw_signal}))
        return out

    if final_conf < cfg.final_min_conf:
        out.update(_terminate("FINAL_LOW_CONF", "FINAL",
                              {"raw_signal": raw_signal,
                               "final_confidence": round(final_conf, 3)}))
        return out

    final_signal = raw_signal if raw_signal in ("BUY", "SELL") else "HOLD"
    exec_size    = "SKIP" if final_signal == "HOLD" else (
                   "REDUCED" if cfg.reduced_low <= final_conf < cfg.reduced_high else "FULL")

    out.update({
        "raw_signal":            raw_signal,
        "final_signal":          final_signal,
        "final_confidence":      round(final_conf, 3),
        "execution_size":        exec_size,
        "active_terminated":     False,
        "terminate_reason":      None,
        "vision_stop_layer":     "NONE",
        "vision_stop_code":      None,
        "vision_conf_band":      ("HIGH" if final_conf >= cfg.reduced_high else
                                  "MID"  if final_conf >= cfg.reduced_low  else "LOW"),
        "vision_decision_chain": "L1->L2->L3",
    })
    return out


def run_phase_a_observe(
    symbol: str,
    vision_data: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Phase A 入口：运行评估并追加写入日期轮转的 JSONL 日志，不影响执行。
    """
    result = analyze_vision_adaptive(symbol, vision_data)
    result["phase_a_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # HIGH-5: 写入失败记录到结果，不再静默吞掉
    try:
        log_path = _adaptive_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    except Exception as e:
        result["log_write_error"] = str(e)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# KEY-001 v1.2: 动态门控误杀控制 (opencode 2026-02-21)
# Phase A: observe-only — phase2_enforce=False
# ═══════════════════════════════════════════════════════════════════════════

Phase   = Literal["ACCUM", "MARKUP", "DISTRIB", "MARKDOWN", "REDIST", "UNKNOWN"]
Action  = Literal["BUY", "SELL"]
GateDecision = Literal["PASS", "HOLD", "BLOCK"]

# Vision L1 structure → Phase 映射
_STRUCT_TO_PHASE: Dict[str, str] = {
    "ACCUMULATION": "ACCUM",
    "MARKUP":       "MARKUP",
    "DISTRIBUTION": "DISTRIB",
    "MARKDOWN":     "MARKDOWN",
    "REDISTRIBUTION": "REDIST",
}

# 默认策略：phase+action → 阈值
_DEFAULT_POLICY: Dict[str, Dict] = {
    "default": {
        "hard_block_threshold": 0.72,
        "soft_hold_threshold":  0.58,
        "max_trades_per_cycle": 2,
        "cooldown_hours":       4,
    },
    "ACCUM_BUY": {
        "hard_block_threshold": 0.80,
        "soft_hold_threshold":  0.64,
        "max_trades_per_cycle": 3,
    },
    "DISTRIB_SELL": {
        "hard_block_threshold": 0.78,
        "soft_hold_threshold":  0.60,
        "max_trades_per_cycle": 3,
    },
    "REDIST_SELL": {
        "hard_block_threshold": 0.76,
        "soft_hold_threshold":  0.59,
        "max_trades_per_cycle": 3,
    },
}

_KEY001_GATE_STATE = "state/key001_gate_state.json"
_KEY001_FALSE_BLOCK = "state/key001_false_block_stats.json"
_KEY001_GATE_LOG = "state/audit/key001_gate_log.jsonl"

# Phase B: 真实拦截
_KEY001_PHASE2_ENFORCE = True


@dataclass
class Key001GateInput:
    symbol:            str
    action:            str   # BUY / SELL
    phase:             str   # ACCUM / MARKUP / DISTRIB / MARKDOWN / REDIST / UNKNOWN
    signal_conf:       float # Vision L1→L2→L3 final_confidence
    risk_score:        float = 0.30  # 0~1，越高风险越高，默认中低风险
    n_state_strength:  float = 0.50  # N字结构强度（从 n_structure_state.json 读取）
    trend_consistency: float = 0.60  # 多周期方向一致性


@dataclass
class Key001GateResult:
    decision:       GateDecision
    score:          float
    reason_code:    str
    reason_text:    str
    policy_version: str = "k001-dg-v1"


def _load_n_state_strength(symbol: str) -> float:
    """从 n_structure_state.json 读取 N字强度，失败返回 0.5"""
    try:
        with open("state/n_structure_state.json", encoding="utf-8") as f:
            data = json.load(f)
        st = data.get(symbol, {})
        state = st.get("state", "SIDE")
        # 状态 → 强度映射
        strength_map = {
            "UP_BREAK": 0.85, "DOWN_BREAK": 0.85,
            "PERFECT_N": 0.70,
            "PULLBACK": 0.45, "DEEP_PULLBACK": 0.30,
            "SIDE": 0.40,
        }
        return strength_map.get(state, 0.50)
    except Exception:
        return 0.50


def _resolve_policy(phase: str, action: str) -> Dict:
    key = f"{phase}_{action}"
    base = dict(_DEFAULT_POLICY["default"])
    override = _DEFAULT_POLICY.get(key, {})
    base.update(override)
    return base


def compute_key001_gate_score(inp: Key001GateInput) -> float:
    """
    gate_score = signal_conf×0.35 + n_state×0.25 + trend_consistency×0.20 - risk×0.20
    范围 0~1，越高越倾向 PASS。
    """
    raw = (
        0.35 * inp.signal_conf
        + 0.25 * inp.n_state_strength
        + 0.20 * inp.trend_consistency
        - 0.20 * inp.risk_score
    )
    return round(max(0.0, min(1.0, raw)), 4)


def evaluate_key001_gate(inp: Key001GateInput) -> Key001GateResult:
    """核心决策：PASS / HOLD / BLOCK"""
    policy = _resolve_policy(inp.phase, inp.action)
    score  = compute_key001_gate_score(inp)

    hard_thresh = policy["hard_block_threshold"]
    soft_thresh = policy["soft_hold_threshold"]

    if score < soft_thresh:
        return Key001GateResult(
            decision="BLOCK", score=score,
            reason_code="K001_SCORE_HARD_BLOCK",
            reason_text=f"score {score:.3f} < soft_thresh {soft_thresh:.3f}",
        )
    if score < hard_thresh:
        return Key001GateResult(
            decision="HOLD", score=score,
            reason_code="K001_SCORE_SOFT_HOLD",
            reason_text=f"score {score:.3f} in hold band [{soft_thresh:.3f}, {hard_thresh:.3f})",
        )
    return Key001GateResult(
        decision="PASS", score=score,
        reason_code="K001_PASS",
        reason_text=f"score {score:.3f} >= hard_thresh {hard_thresh:.3f}",
    )


def apply_key001_gate(
    symbol: str,
    action: str,
    vision_result: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Phase B 入口：enforcing（真实拦截）。
    返回 (allowed: bool, reason: str)。
    allowed=False 时上层 send 函数 return None 拦截信号。
    """
    # vision_result 为空时自动从 pattern_latest.json 读取
    if not vision_result or not vision_result.get("vision_l1_structure"):
        vision_result = analyze_vision_adaptive(symbol)

    # Vision 无有效判断时(L1 terminate)，KEY-001 不拦截，直接放行
    # 原因: Vision看不懂市场结构 ≠ 信号质量差，不应杀死所有外挂信号
    if vision_result.get("active_terminated", True) or not vision_result.get("final_confidence"):
        return True, "vision_no_signal:bypass"

    # 推导 phase（从 Vision L1 结构）
    l1_struct = str(vision_result.get("vision_l1_structure", "UNKNOWN")).upper()
    phase = _STRUCT_TO_PHASE.get(l1_struct, "UNKNOWN")

    signal_conf = float(vision_result.get("final_confidence", 0.0))
    n_strength  = _load_n_state_strength(symbol)

    inp = Key001GateInput(
        symbol=symbol,
        action=action,
        phase=phase,
        signal_conf=signal_conf,
        n_state_strength=n_strength,
    )
    res = evaluate_key001_gate(inp)

    # 写审计日志（fail-silent）
    try:
        os.makedirs(os.path.dirname(_KEY001_GATE_LOG), exist_ok=True)
        entry = {
            "ts":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol":   symbol,
            "action":   action,
            "phase":    phase,
            "score":    res.score,
            "decision": res.decision,
            "reason":   res.reason_code,
            "signal_conf":       inp.signal_conf,
            "n_state_strength":  inp.n_state_strength,
            "trend_consistency": inp.trend_consistency,
            "risk_score":        inp.risk_score,
            "enforce":  _KEY001_PHASE2_ENFORCE,
        }
        with open(_KEY001_GATE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Phase A: observe-only，永远放行
    if not _KEY001_PHASE2_ENFORCE:
        return True, f"observe_only:{res.decision}:{res.reason_code}"

    # Phase B+: 真实拦截
    if res.decision in ("BLOCK", "HOLD"):
        return False, f"blocked_by_key001:{res.reason_code}"
    return True, "pass"


def update_key001_false_block_stats(day: Optional[str] = None) -> Dict:
    """
    读取 key001_gate_log.jsonl，统计各 symbol/phase/action 分桶的 BLOCK 率。
    Phase A: 仅统计，不调参。
    """
    stats: Dict[str, Dict] = {}
    try:
        if not os.path.exists(_KEY001_GATE_LOG):
            return stats
        with open(_KEY001_GATE_LOG, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            try:
                d = json.loads(line.strip())
            except Exception:
                continue
            if day and not d.get("ts", "").startswith(day):
                continue
            key = f"{d.get('symbol','?')}_{d.get('phase','?')}_{d.get('action','?')}"
            if key not in stats:
                stats[key] = {"total": 0, "block": 0, "hold": 0, "pass": 0}
            stats[key]["total"] += 1
            dec = d.get("decision", "PASS")
            if dec == "BLOCK":
                stats[key]["block"] += 1
            elif dec == "HOLD":
                stats[key]["hold"] += 1
            else:
                stats[key]["pass"] += 1
        # 计算 block_rate
        for k in stats:
            t = stats[k]["total"]
            stats[k]["block_rate"] = round(stats[k]["block"] / t, 3) if t else 0.0
        # 写入文件
        os.makedirs("state", exist_ok=True)
        with open(_KEY001_FALSE_BLOCK, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return stats


def suggest_key001_threshold_update(stats: Optional[Dict] = None) -> List[Dict]:
    """
    基于 false_block_stats 建议阈值调整。
    block_rate >= 0.35 且 samples >= 20 → relax
    block_rate <= 0.10 且 samples >= 20 → tighten
    """
    if stats is None:
        try:
            with open(_KEY001_FALSE_BLOCK, encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            return []

    changes = []
    for bucket, v in stats.items():
        if v["total"] < 20:
            continue
        if v["block_rate"] >= 0.35:
            changes.append({
                "bucket": bucket,
                "action": "relax",
                "soft_hold_threshold_delta": +0.03,
                "hard_block_threshold_delta": +0.02,
                "block_rate": v["block_rate"],
                "samples": v["total"],
            })
        elif v["block_rate"] <= 0.10:
            changes.append({
                "bucket": bucket,
                "action": "tighten",
                "soft_hold_threshold_delta": -0.02,
                "hard_block_threshold_delta": -0.01,
                "block_rate": v["block_rate"],
                "samples": v["total"],
            })
    return changes

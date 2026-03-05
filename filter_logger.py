#!/usr/bin/env python3
"""
filter_logger.py — KEY-001 T07 审计日志落盘 (v1.1)
===================================================
Phase1: 只记录，不影响任何决策逻辑。

输出文件:
  state/audit/signal_log.jsonl   — N字门控信号日志 (SignalLog)
  state/audit/filter_log.jsonl   — FilterChain三道闸门决策日志 (FilterLog)

调用方：
  llm_server_v3640.py  → write_signal_log()  (N字gate每次判断后)
  filter_chain_worker.py → write_filter_log() (三道闸门计算后)

注意：
  - 所有写入均 fail-silent，不会影响主流程
  - signal_id / filter_id 格式: {symbol}_{direction}_{YYYYMMDD_HHMMSS}
  - retrospective 字段默认 "pending"，由 backfill.py 回填

v1.1 Schema 扩展 (Phase A — retrospective spec 字段对齐):
  - passed: bool — allowed 的规范化别名 (两者并存保持向后兼容)
  - chan_type/chan_divergence/chan_direction: 为 ChanBS 信号接入预留 (N字记录置 None)
  - trade_executed: bool — 是否实际下单 (默认 False，由执行层事后回填)
  - trade_id: str|None — 关联交易 ID (执行层回填)
  - filter_id: str|None — 关联 FilterLog ID (FilterChain 回填)
"""

import json
import os
import threading
from datetime import datetime, timezone

# ── 输出目录 ──────────────────────────────────────────────────
_AUDIT_DIR = os.path.join("state", "audit")
_SIGNAL_LOG = os.path.join(_AUDIT_DIR, "signal_log.jsonl")
_FILTER_LOG = os.path.join(_AUDIT_DIR, "filter_log.jsonl")

_write_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_id(symbol: str, direction: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{symbol}_{direction}_{ts}"


def _append(path: str, record: dict):
    """线程安全 JSONL 追加"""
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        with _write_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # fail-silent — 不影响主流程


# ═══════════════════════════════════════════════════════════════
# SignalLog — N字门控信号记录
# ═══════════════════════════════════════════════════════════════

def write_signal_log(
    symbol: str,
    direction: str,
    n_state,           # NState dataclass from n_structure.py
    current_price: float,
    timeframe: str,
    allowed: bool,
    reason: str,
    # v1.1: Phase A 新增字段 (均有默认值，调用方无需修改)
    filter_id: str = None,       # 关联 FilterLog ID (FilterChain 回填)
    trade_executed: bool = False, # 是否实际下单 (执行层回填)
    trade_id: str = None,         # 关联交易 ID (执行层回填)
    chan_type: str = None,         # ChanBS 信号类型 (预留，N字记录置 None)
    chan_divergence: bool = None,  # ChanBS 背驰标志 (预留)
    chan_direction: str = None,    # ChanBS 方向 (预留)
) -> str:
    """
    N字门控每次 check_n_structure_gate() 调用后记录。

    v1.1: 扩展 schema 对齐 retrospective analysis spec。
    新增字段均有默认值，现有调用方无需修改。

    Returns: signal_id (用于关联 FilterLog)
    """
    signal_id = _make_id(symbol, direction)
    ts = _ts_now()

    # 估算入场/止损/目标 (基于ABC结构)
    n_entry = getattr(n_state, "C", 0.0) or 0.0
    n_stop  = getattr(n_state, "B", 0.0) or 0.0
    leg1    = getattr(n_state, "leg1_range", 0.0) or 0.0
    # 目标: C方向延伸 leg1
    if direction == "BUY":
        n_target = n_entry + leg1 if leg1 > 0 else 0.0
    else:
        n_target = n_entry - leg1 if leg1 > 0 else 0.0

    record = {
        # 基础
        "signal_id":   signal_id,
        "ts":          ts,
        "symbol":      symbol,
        "timeframe":   timeframe,
        "source":      "n_structure",
        "direction":   direction,
        # N字专属
        "n_pattern":           getattr(n_state, "state", "UNKNOWN"),
        "n_direction":         getattr(n_state, "direction", "NONE"),
        "n_quality":           round(getattr(n_state, "quality", 0.0) or 0.0, 3),
        "n_wave_position":     "unknown",       # 未追踪，backfill候选
        "n_wave5_divergence":  False,           # 未追踪
        "n_entry":             round(n_entry, 4),
        "n_stop_loss":         round(n_stop, 4),
        "n_target":            round(n_target, 4),
        "n_retrace_ratio":     round(getattr(n_state, "retrace_ratio", 0.0) or 0.0, 3),
        "n_extension_ok":      getattr(n_state, "extension_ok", True),
        "n_leg1":              round(getattr(n_state, "leg1_range", 0.0) or 0.0, 4),
        "n_leg2":              round(getattr(n_state, "leg2_range", 0.0) or 0.0, 4),
        "n_leg3":              round(getattr(n_state, "leg3_range", 0.0) or 0.0, 4),
        # 信号
        "signal_strength":  round(getattr(n_state, "quality", 0.0) or 0.0, 3),
        "signal_price":     round(current_price, 4),
        "allowed":          allowed,
        "passed":           allowed,   # v1.1: retrospective spec 规范化别名
        "reason":           reason,
        # v1.1: 多源字段 (N字记录置 None，ChanBS 接入后填充)
        "chan_type":        chan_type,
        "chan_divergence":  chan_divergence,
        "chan_direction":   chan_direction,
        # v1.1: 执行链路关联 (默认值，由执行层事后回填)
        "filter_id":        filter_id,
        "trade_executed":   trade_executed,
        "trade_id":         trade_id,
        # 事后回填 (由 backfill.py 填入)
        "price_after_1h":   None,
        "price_after_4h":   None,
        "price_after_1d":   None,
        "price_after_3d":   None,
        "retrospective":    "pending",
        "retrospective_reason": "",
    }

    _append(_SIGNAL_LOG, record)
    return signal_id


# ═══════════════════════════════════════════════════════════════
# FilterLog — FilterChain 三道闸门决策记录
# ═══════════════════════════════════════════════════════════════

def write_filter_log(
    symbol: str,
    direction: str,
    passed: bool,
    blocked_by: str,
    reason: str,
    vision_result,         # VisionResult or None
    vision_decision: str,
    vision_reason: str,
    vol_score: float,
    vol_reason: str,
    vol_rvol: float = 0.0,
    vol_pv_alignment: float = 0.0,
    vol_obv_direction: int = 0,
    micro_go: bool = False,
    micro_regime: str = "",
    micro_flow: str = "",
    micro_alignment: str = "",
    micro_vr: float = 0.0,
    micro_h0: float = 0.0,
    micro_reason: str = "",
    current_price: float = 0.0,
) -> str:
    """
    FilterChain 计算完三道闸门后记录。

    Returns: filter_id
    """
    filter_id = _make_id(symbol, direction)
    ts = _ts_now()

    # Vision 字段
    v_pattern    = getattr(vision_result, "pattern",    "NONE") if vision_result else "NONE"
    v_bias       = getattr(vision_result, "bias",       "NEUTRAL") if vision_result else "NEUTRAL"
    v_confidence = getattr(vision_result, "confidence", 0.0) if vision_result else 0.0

    record = {
        # 基础
        "filter_id":  filter_id,
        "signal_id":  "pending",   # 主程序日志未直接关联，由 audit.py 事后关联
        "ts":         ts,
        "symbol":     symbol,
        "direction":  direction,
        # 决策
        "passed":     passed,
        "blocked_by": blocked_by,
        "reason":     reason,
        # 闸门1 Vision
        "vision_pattern":    v_pattern,
        "vision_bias":       v_bias,
        "vision_confidence": round(float(v_confidence), 3),
        "vision_decision":   vision_decision,
        "vision_reason":     vision_reason,
        # 闸门2 Volume
        "volume_score":         round(float(vol_score), 3),
        "volume_rvol":          round(float(vol_rvol), 3),
        "volume_pv_alignment":  round(float(vol_pv_alignment), 3),
        "volume_obv_direction": int(vol_obv_direction),
        "volume_reason":        vol_reason,
        # 闸门3 Micro
        "micro_go":             micro_go,
        "micro_regime":         micro_regime,
        "micro_flow_direction": micro_flow,
        "micro_alignment":      micro_alignment,
        "micro_variance_ratio": round(float(micro_vr) if micro_vr == micro_vr else 0.0, 4),
        "micro_h0":             round(float(micro_h0) if micro_h0 == micro_h0 else 0.0, 4),
        "micro_reason":         micro_reason,
        # 市场快照 (filter_chain_worker 传入的最新收盘价)
        "price_at_signal": round(float(current_price), 4),
        "atr_14":   None,   # 暂不采集，backfill.py 候选
        "rsi_14":   None,
        "ema_10":   None,
        "ema_50":   None,
        # 事后回填
        "price_after_1h":  None,
        "price_after_4h":  None,
        "price_after_1d":  None,
        "price_after_3d":  None,
        "retrospective":       "pending",
        "retrospective_reason": "",
    }

    _append(_FILTER_LOG, record)
    return filter_id

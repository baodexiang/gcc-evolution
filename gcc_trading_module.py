"""
gcc_trading_module.py  —  GCC交易决策模块 v0.1
基于 arXiv:2603.04735 (树状搜索) + arXiv:2407.09468 (三视角验证)

Phase 1: 观察模式 — 只记录决策日志，不干扰现有交易逻辑
Phase 2: 执行模式 — BUY→下一K线市价买入 / SELL→市价卖出 / HOLD→不动

GCC-0244 实施步骤:
  S01 ✅ 复制 gcc_decision_engine.py
  S02-S05 ✅ 所有 import 验证通过
  S06-S12 ✅ 数据读取层 (本文件)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger("gcc.trading")

# ── 路径常量 ──────────────────────────────────────────────────
_STATE_DIR       = Path("state")
_GCC_DIR         = Path(".GCC")

_VISION_SNAP_DIR = _STATE_DIR / "vision_cache" / "snapshots"
_N_GATE_FILE     = _STATE_DIR / "n_gate_active.json"
_N_STRUCT_FILE   = _STATE_DIR / "n_structure_state.json"
_FILTER_FILE     = _STATE_DIR / "filter_chain_state.json"
_SIGNAL_LOG      = _STATE_DIR / "audit" / "signal_log.jsonl"
_GCC_MODE_FILE   = _GCC_DIR / "signal_filter" / "mode_state.json"
_PLUGIN_KNN_ACC  = _STATE_DIR / "plugin_knn_accuracy.json"
_KNN_ACC_MAP     = _STATE_DIR / "knn_accuracy_map.json"
_LOG_FILE        = _STATE_DIR / "gcc_trading_decisions.jsonl"

# ── 决策输出日志 ───────────────────────────────────────────────
def _log_decision(record: dict) -> None:
    """Phase1观察模式：追加决策记录到 JSONL。"""
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[GCC-TRADE] log_decision failed: %s", e)


# ══════════════════════════════════════════════════════════════
# S06  _read_vision(symbol) → (bias, confidence)
# 读 state/vision_cache/snapshots/{symbol}/latest.json
# bias: "BUY" | "SELL" | "HOLD"  confidence: 0.0~1.0
# ══════════════════════════════════════════════════════════════
def _read_vision(symbol: str) -> Tuple[str, float]:
    """从 vision_cache 读取最新 Vision 判断。"""
    snap_file = _VISION_SNAP_DIR / symbol / "latest.json"
    if not snap_file.exists():
        return "HOLD", 0.5
    try:
        d = json.loads(snap_file.read_text(encoding="utf-8"))
        bias = (d.get("bias") or "HOLD").upper()
        if bias not in ("BUY", "SELL", "HOLD"):
            bias = "HOLD"
        conf = float(d.get("confidence") or 0.5)
        conf = max(0.0, min(1.0, conf))
        return bias, conf
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_vision %s: %s", symbol, e)
        return "HOLD", 0.5


# ══════════════════════════════════════════════════════════════
# S07  _read_scan_signal(symbol) → (direction, confidence)
# 读 state/n_structure_state.json 作为扫描信号代理
# direction: "BUY" | "SELL" | "NONE"   confidence: 0.0~1.0
# 注: scan_signals.json 由主程序运行时生成，离线时回退到 n_structure
# ══════════════════════════════════════════════════════════════
def _read_scan_signal(symbol: str) -> Tuple[str, float]:
    """读扫描信号方向。优先 scan_signals.json，无则用 n_structure_state。"""
    # 优先检查实时 scan_signals
    scan_file = _STATE_DIR / "scan_signals.json"
    if scan_file.exists():
        try:
            d = json.loads(scan_file.read_text(encoding="utf-8"))
            entry = d.get(symbol, {})
            direction = (entry.get("direction") or "NONE").upper()
            conf = float(entry.get("confidence") or 0.5)
            if direction in ("BUY", "SELL"):
                return direction, max(0.0, min(1.0, conf))
        except Exception:
            pass

    # 回退: n_structure_state
    if _N_STRUCT_FILE.exists():
        try:
            d = json.loads(_N_STRUCT_FILE.read_text(encoding="utf-8"))
            entry = d.get(symbol, {})
            n_dir = (entry.get("direction") or "NONE").upper()
            quality = float(entry.get("quality") or 0.0)
            if n_dir == "UP":
                return "BUY", min(0.8, 0.5 + quality * 0.3)
            if n_dir == "DOWN":
                return "SELL", min(0.8, 0.5 + quality * 0.3)
        except Exception as e:
            logger.debug("[GCC-TRADE] _read_scan_signal n_struct %s: %s", symbol, e)

    return "NONE", 0.0


# ══════════════════════════════════════════════════════════════
# S08  _read_n_gate(symbol, direction) → "BLOCK" | "OBSERVE" | "INACTIVE"
# 读 state/n_gate_active.json → {symbol_BUY: {block, reason}}
# ══════════════════════════════════════════════════════════════
def _read_n_gate(symbol: str, direction: str) -> str:
    """读取 N字门控状态。"""
    if not _N_GATE_FILE.exists():
        return "INACTIVE"
    try:
        d = json.loads(_N_GATE_FILE.read_text(encoding="utf-8"))
        key = f"{symbol}_{direction.upper()}"
        entry = d.get(key, {})
        if not entry:
            return "INACTIVE"
        blocked = entry.get("block", False)
        return "BLOCK" if blocked else "OBSERVE"
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_n_gate %s %s: %s", symbol, direction, e)
        return "INACTIVE"


# ══════════════════════════════════════════════════════════════
# S09  _read_filter_chain(symbol, direction) → dict
# 读 state/filter_chain_state.json
# 返回: {passed, vision, volume_score, micro_go, blocked_by}
# ══════════════════════════════════════════════════════════════
def _read_filter_chain(symbol: str, direction: str) -> dict:
    """读取三道过滤链结果。"""
    default = {"passed": None, "vision": None, "volume_score": 0.5,
                "micro_go": None, "blocked_by": ""}
    if not _FILTER_FILE.exists():
        return default
    try:
        d = json.loads(_FILTER_FILE.read_text(encoding="utf-8"))
        entry = d.get(symbol, {}).get(direction.upper(), {})
        if not entry:
            return default
        return {
            "passed":       entry.get("passed"),
            "vision":       entry.get("vision"),           # "PASS"/"HOLD"/None
            "volume_score": float(entry.get("volume_score") or 0.5),
            "micro_go":     entry.get("micro_go"),
            "blocked_by":   entry.get("blocked_by") or "",
        }
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_filter_chain %s %s: %s", symbol, direction, e)
        return default


# ══════════════════════════════════════════════════════════════
# S10  _read_win_rate(symbol, direction) → float
# 读 state/audit/signal_log.jsonl → 统计 symbol+direction 历史胜率
# retrospective: "correct_pass"=胜, "false_pass"/"wrong_block"=败
# 最多读取最近 200 条，至少 5 条才给有效值
# ══════════════════════════════════════════════════════════════
def _read_win_rate(symbol: str, direction: str = "") -> float:
    """读取历史胜率，无足够数据返回 0.5。"""
    if not _SIGNAL_LOG.exists():
        return 0.5
    correct = 0
    total = 0
    try:
        lines = _SIGNAL_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
        # 取最近 200 条倒序扫描
        for line in reversed(lines[-400:]):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("symbol") != symbol:
                continue
            if direction and r.get("direction", "").upper() != direction.upper():
                continue
            retro = r.get("retrospective") or ""
            if retro in ("correct_pass", "correct_block"):
                correct += 1
                total += 1
            elif retro in ("false_pass", "wrong_block", "false_block"):
                total += 1
            if total >= 200:
                break
        if total < 5:
            return 0.5
        return round(correct / total, 4)
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_win_rate %s: %s", symbol, e)
        return 0.5


# ══════════════════════════════════════════════════════════════
# S11  _read_volume(bars) → vol_ratio
# 计算当前成交量相对近 20 根均量的倍数
# bars: list of {"volume": float, ...}，最新在末尾
# ══════════════════════════════════════════════════════════════
def _read_volume(bars: list) -> float:
    """计算量比 (current_vol / avg_vol_20)。"""
    if not bars or len(bars) < 2:
        return 1.0
    try:
        vols = [float(b.get("volume") or 0) for b in bars if b.get("volume")]
        if len(vols) < 2:
            return 1.0
        current = vols[-1]
        lookback = vols[-21:-1] if len(vols) >= 21 else vols[:-1]
        avg = sum(lookback) / len(lookback) if lookback else 1.0
        if avg <= 0:
            return 1.0
        return round(current / avg, 4)
    except Exception:
        return 1.0


# ══════════════════════════════════════════════════════════════
# S12  _read_signal_direction() → str
# 读 .GCC/signal_filter/mode_state.json → "ENFORCE" | "OBSERVE" | "OFF"
# ══════════════════════════════════════════════════════════════
def _read_signal_direction() -> str:
    """读取 GCC 信号方向过滤模式。"""
    if not _GCC_MODE_FILE.exists():
        return "OFF"
    try:
        d = json.loads(_GCC_MODE_FILE.read_text(encoding="utf-8"))
        mode = (d.get("mode") or "OFF").upper()
        # observe_only 覆盖
        if d.get("observe_only"):
            return "OBSERVE"
        return mode if mode in ("ENFORCE", "OBSERVE", "OFF") else "OFF"
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_signal_direction: %s", e)
        return "OFF"


# ══════════════════════════════════════════════════════════════
# 自测 (直接运行时)
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sym = "BTCUSDC"
    print(f"=== gcc_trading_module 数据读取层自测 ({sym}) ===")
    print(f"S06 Vision:         {_read_vision(sym)}")
    print(f"S07 ScanSignal:     {_read_scan_signal(sym)}")
    print(f"S08 N-Gate BUY:     {_read_n_gate(sym, 'BUY')}")
    print(f"S08 N-Gate SELL:    {_read_n_gate(sym, 'SELL')}")
    print(f"S09 FilterChain BUY:{_read_filter_chain(sym, 'BUY')}")
    print(f"S10 WinRate BUY:    {_read_win_rate(sym, 'BUY')}")
    bars_mock = [{"volume": 100 + i * 10} for i in range(22)]
    print(f"S11 VolRatio:       {_read_volume(bars_mock)}")
    print(f"S12 GCC Mode:       {_read_signal_direction()}")

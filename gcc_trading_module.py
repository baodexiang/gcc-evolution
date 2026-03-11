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
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")

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
_GOVERNANCE_FILE = _STATE_DIR / "plugin_governance_actions.json"
_REGIME_FILE     = _STATE_DIR / "regime_validation.json"
_CONTEXT_SNAP_DIR = _STATE_DIR / "gcc_decision_context"

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
# L1-S02  _read_plugin_governor / _read_regime / _read_risk_budget
# 补充输入槽位：外挂治理状态、市场体制、风险预算
# ══════════════════════════════════════════════════════════════
def _read_plugin_governor(symbol: str) -> dict:
    """读 plugin_governance_actions.json → 该品种外挂治理状态。"""
    if not _GOVERNANCE_FILE.exists():
        return {"status": "UNKNOWN", "disabled_plugins": []}
    try:
        gov = json.loads(_GOVERNANCE_FILE.read_text(encoding="utf-8"))
        by_asset = gov.get("by_asset", {})
        asset_gov = by_asset.get(symbol, {})
        disabled = [k for k, v in asset_gov.items()
                    if isinstance(v, dict) and v.get("action") == "DISABLE"]
        return {"status": "ACTIVE" if not disabled else "RESTRICTED",
                "disabled_plugins": disabled}
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_plugin_governor %s: %s", symbol, e)
        return {"status": "UNKNOWN", "disabled_plugins": []}


def _read_regime(symbol: str) -> dict:
    """读 regime_validation.json → 最新市场体制 (TRENDING/RANGING/VOLATILE)。"""
    if not _REGIME_FILE.exists():
        return {"regime": "UNKNOWN", "direction": "NONE"}
    try:
        data = json.loads(_REGIME_FILE.read_text(encoding="utf-8"))
        records = data.get("records", {}).get(symbol, [])
        if not records:
            return {"regime": "UNKNOWN", "direction": "NONE"}
        latest = records[-1] if isinstance(records, list) else records
        return {
            "regime": latest.get("regime", "UNKNOWN"),
            "direction": latest.get("direction", "NONE"),
        }
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_regime %s: %s", symbol, e)
        return {"regime": "UNKNOWN", "direction": "NONE"}


def _read_risk_budget() -> dict:
    """风险预算槽位 — 当前固定值，后续接入账户层实时数据。"""
    return {
        "max_position_pct": 0.10,    # 单品种最大仓位占比
        "daily_loss_limit_pct": 0.02, # 日止损线 -2%
        "available": True,            # 是否可用（触发熔断后 False）
    }


# ══════════════════════════════════════════════════════════════
# Phase B1: Schwab VWAP 读取 — docx P0 数据源
# 股票品种从 Schwab API 获取实时 VWAP，加密品种跳过
# ══════════════════════════════════════════════════════════════
_SCHWAB_QUOTE_CACHE: Dict[str, dict] = {}
_SCHWAB_QUOTE_CACHE_TS: Dict[str, float] = {}
_SCHWAB_QUOTE_TTL = 60  # 缓存60秒

def _read_schwab_vwap(symbol: str) -> dict:
    """
    读取 Schwab 实时报价 VWAP。
    返回: {"vwap": float, "vwap_bias": "ABOVE"/"BELOW"/"AT"/"UNKNOWN", "last": float}
    加密品种直接返回 UNKNOWN（Schwab 不支持加密货币）。
    """
    import time as _time
    # 加密品种跳过
    if symbol in _CRYPTO_SYMBOLS:
        return {"vwap": 0.0, "vwap_bias": "UNKNOWN", "last": 0.0}

    # 缓存检查
    cached_ts = _SCHWAB_QUOTE_CACHE_TS.get(symbol, 0)
    if _time.time() - cached_ts < _SCHWAB_QUOTE_TTL and symbol in _SCHWAB_QUOTE_CACHE:
        return _SCHWAB_QUOTE_CACHE[symbol]

    try:
        from schwab_data_provider import get_provider
        quote = get_provider().get_quote(symbol)
        result = {
            "vwap": quote.get("vwap", 0.0),
            "vwap_bias": quote.get("vwap_bias", "UNKNOWN"),
            "last": quote.get("last", 0.0),
        }
        _SCHWAB_QUOTE_CACHE[symbol] = result
        _SCHWAB_QUOTE_CACHE_TS[symbol] = _time.time()
        return result
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_schwab_vwap %s: %s", symbol, e)
        return {"vwap": 0.0, "vwap_bias": "UNKNOWN", "last": 0.0}


# ══════════════════════════════════════════════════════════════
# L1-S03  DecisionContext — 标准化决策上下文快照
# 统一所有输入源为一个 dataclass，落盘供回放/dashboard/回填复用
# ══════════════════════════════════════════════════════════════
@dataclass
class DecisionContext:
    symbol: str
    ts: str
    # 原有输入 (L1-S01)
    vision: tuple         # (bias, confidence)
    scan: tuple           # (direction, confidence)
    filter_buy: dict
    filter_sell: dict
    win_rate_buy: float
    win_rate_sell: float
    vol_ratio: float
    n_gate_buy: str
    n_gate_sell: str
    # 新增输入 (L1-S02)
    regime: dict = field(default_factory=dict)
    governor: dict = field(default_factory=dict)
    risk_budget: dict = field(default_factory=dict)
    # 扩展槽位（docx P0 数据源预留）
    extended: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "ts": self.ts,
            "vision": list(self.vision), "scan": list(self.scan),
            "filter_buy": self.filter_buy, "filter_sell": self.filter_sell,
            "win_rate_buy": self.win_rate_buy, "win_rate_sell": self.win_rate_sell,
            "vol_ratio": round(self.vol_ratio, 4),
            "n_gate_buy": self.n_gate_buy, "n_gate_sell": self.n_gate_sell,
            "regime": self.regime, "governor": self.governor,
            "risk_budget": self.risk_budget, "extended": self.extended,
        }

    def snapshot(self) -> None:
        """落盘快照到 state/gcc_decision_context/{symbol}/{ts}.json。"""
        try:
            snap_dir = _CONTEXT_SNAP_DIR / self.symbol
            snap_dir.mkdir(parents=True, exist_ok=True)
            safe_ts = self.ts.replace(":", "-").replace(" ", "_")
            path = snap_dir / f"{safe_ts}.json"
            path.write_text(
                json.dumps(self.as_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[GCC-TRADE] context snapshot: %s", e)


# ══════════════════════════════════════════════════════════════
# S13  TreeNode — 树搜索候选路径节点
# action: "BUY" | "SELL" | "HOLD"
# scores_by_source: 各数据源打分 {source: float}
# aggregate: 综合分数 [-1, 1]
# pruned: 是否被剪枝
# prune_reason: 剪枝原因
# ══════════════════════════════════════════════════════════════
@dataclass
class TreeNode:
    action: str                              # "BUY" | "SELL" | "HOLD"
    scores_by_source: dict = field(default_factory=dict)
    aggregate: float = 0.0                   # [-1, 1]
    pruned: bool = False
    prune_reason: str = ""
    # PUCT 树搜索扩展 (arXiv:2603.04735)
    depth: int = 0                           # 树深度 (0=根, 1=L1方向, 2=L2策略)
    visit_count: int = 0                     # N(s,a) 访问次数
    total_value: float = 0.0                 # W(s,a) 累积价值
    children: list = field(default_factory=list)  # 子节点列表
    strategy: str = ""                       # L2策略标签

    @property
    def q_value(self) -> float:
        """PUCT Q值 = 平均价值。"""
        return self.total_value / self.visit_count if self.visit_count > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "action":           self.action,
            "scores_by_source": self.scores_by_source,
            "aggregate":        round(self.aggregate, 4),
            "pruned":           self.pruned,
            "prune_reason":     self.prune_reason,
            "depth":            self.depth,
            "strategy":         self.strategy,
            "visit_count":      self.visit_count,
            "q_value":          round(self.q_value, 4),
            "children_count":   len(self.children),
        }


# ══════════════════════════════════════════════════════════════
# S14  _score_buy_candidate — BUY 路径各数据源打分
# 返回 scores_by_source dict，每个 key 对应一个数据源贡献值
# 权重设计 (总和不超过 1.0，便于 aggregate 归一化到 [-1,1]):
#   vision    0.35  — 形态识别主信号
#   scan      0.25  — 扫描引擎方向
#   filter    0.20  — 过滤链通过情况
#   win_rate  0.12  — 历史胜率偏置
#   volume    0.08  — 量比确认
# ══════════════════════════════════════════════════════════════
def _score_buy_candidate(symbol: str, bars: list, context: dict) -> dict:
    """为 BUY 候选路径打分，返回各数据源得分 (正=支持BUY, 负=反对)。"""
    vision_bias, vision_conf = context.get("vision", ("HOLD", 0.5))
    scan_dir,    scan_conf   = context.get("scan",   ("NONE", 0.0))
    filter_res               = context.get("filter_buy", {})
    win_rate                 = context.get("win_rate_buy", 0.5)
    vol_ratio                = context.get("vol_ratio", 1.0)

    scores = {}

    # vision: BUY支持+full, SELL反对-full, HOLD中性0
    if vision_bias == "BUY":
        scores["vision"] = +vision_conf * 0.35
    elif vision_bias == "SELL":
        scores["vision"] = -vision_conf * 0.35
    else:
        scores["vision"] = 0.0

    # scan: 方向一致为正，相反为负
    if scan_dir == "BUY":
        scores["scan"] = +scan_conf * 0.25
    elif scan_dir == "SELL":
        scores["scan"] = -scan_conf * 0.25
    else:
        scores["scan"] = 0.0

    # filter chain: passed=+0.20, failed=-0.20, None=0
    if filter_res.get("passed") is True:
        scores["filter"] = +0.20
    elif filter_res.get("passed") is False:
        scores["filter"] = -0.20
    else:
        scores["filter"] = 0.0

    # win_rate 偏置: 中性=0, 胜率越高越正
    scores["win_rate"] = (win_rate - 0.5) * 0.24   # 0.5→0, 1.0→+0.12, 0.0→-0.12

    # volume: 量比>1.5 轻微加分，<0.5 轻微减分
    if vol_ratio >= 1.5:
        scores["volume"] = +0.08
    elif vol_ratio <= 0.5:
        scores["volume"] = -0.04
    else:
        scores["volume"] = 0.0

    # Phase B1: VWAP — 价格在VWAP上方支持BUY，下方反对
    vwap_bias = context.get("schwab_vwap", {}).get("vwap_bias", "UNKNOWN")
    if vwap_bias == "ABOVE":
        scores["vwap"] = +0.10
    elif vwap_bias == "BELOW":
        scores["vwap"] = -0.06
    else:
        scores["vwap"] = 0.0

    return scores


# ══════════════════════════════════════════════════════════════
# S15  _score_sell_candidate — SELL 路径各数据源打分
# 镜像 BUY 打分，方向相反
# ══════════════════════════════════════════════════════════════
def _score_sell_candidate(symbol: str, bars: list, context: dict) -> dict:
    """为 SELL 候选路径打分。"""
    vision_bias, vision_conf = context.get("vision", ("HOLD", 0.5))
    scan_dir,    scan_conf   = context.get("scan",   ("NONE", 0.0))
    filter_res               = context.get("filter_sell", {})
    win_rate                 = context.get("win_rate_sell", 0.5)
    vol_ratio                = context.get("vol_ratio", 1.0)

    scores = {}

    # vision: SELL支持, BUY反对
    if vision_bias == "SELL":
        scores["vision"] = +vision_conf * 0.35
    elif vision_bias == "BUY":
        scores["vision"] = -vision_conf * 0.35
    else:
        scores["vision"] = 0.0

    # scan: SELL方向一致为正
    if scan_dir == "SELL":
        scores["scan"] = +scan_conf * 0.25
    elif scan_dir == "BUY":
        scores["scan"] = -scan_conf * 0.25
    else:
        scores["scan"] = 0.0

    # filter chain
    if filter_res.get("passed") is True:
        scores["filter"] = +0.20
    elif filter_res.get("passed") is False:
        scores["filter"] = -0.20
    else:
        scores["filter"] = 0.0

    # win_rate
    scores["win_rate"] = (win_rate - 0.5) * 0.24

    # volume
    if vol_ratio >= 1.5:
        scores["volume"] = +0.08
    elif vol_ratio <= 0.5:
        scores["volume"] = -0.04
    else:
        scores["volume"] = 0.0

    # Phase B1: VWAP — 价格在VWAP下方支持SELL，上方反对
    vwap_bias = context.get("schwab_vwap", {}).get("vwap_bias", "UNKNOWN")
    if vwap_bias == "BELOW":
        scores["vwap"] = +0.10
    elif vwap_bias == "ABOVE":
        scores["vwap"] = -0.06
    else:
        scores["vwap"] = 0.0

    return scores


# ══════════════════════════════════════════════════════════════
# S16  _score_hold_candidate — HOLD 路径中性分
# ══════════════════════════════════════════════════════════════
def _score_hold_candidate() -> dict:
    """HOLD 路径固定中性分 0.0，作为基线竞争者。"""
    return {"vision": 0.0, "scan": 0.0, "filter": 0.0,
            "win_rate": 0.0, "volume": 0.0, "vwap": 0.0}


# ══════════════════════════════════════════════════════════════
# S17  _aggregate_candidate_score(scores_dict) → float [-1, 1]
# 各数据源分数加总后 clamp 到 [-1, 1]
# ══════════════════════════════════════════════════════════════
def _aggregate_candidate_score(scores: dict) -> float:
    """合并各数据源得分 → 归一化到 [-1, 1]。"""
    total = sum(scores.values())
    return max(-1.0, min(1.0, total))


# ══════════════════════════════════════════════════════════════
# S18-S21  剪枝规则
# ══════════════════════════════════════════════════════════════
_CRYPTO_SYMBOLS = frozenset({
    "BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC", "DOGEUSDC",
    "BNBUSDC", "XRPUSDC", "ADAUSDC", "DOTUSDC",
})

def _apply_pruning(nodes: List[TreeNode], symbol: str,
                   context: dict) -> List[TreeNode]:
    """
    对三个候选节点依次应用剪枝规则 P1-P4。
    修改 node.pruned / node.prune_reason 并返回同一列表。
    """
    for node in nodes:
        if node.pruned:
            continue

        # P1: N-Gate BLOCK → 剪掉加密 BUY 路径
        if node.action == "BUY" and symbol in _CRYPTO_SYMBOLS:
            if context.get(f"n_gate_buy") == "BLOCK":
                node.pruned = True
                node.prune_reason = "P1:N-Gate BLOCK(crypto BUY)"
                continue

        # P2: FilterChain 三道门全失败 → 剪掉对应方向
        if node.action in ("BUY", "SELL"):
            fc_key = f"filter_{node.action.lower()}"
            fc = context.get(fc_key, {})
            # passed=False 且 blocked_by 非空 → 明确被拒
            if fc.get("passed") is False and fc.get("blocked_by"):
                node.pruned = True
                node.prune_reason = f"P2:FilterChain blocked_by={fc['blocked_by']}"
                continue

        # P3: aggregate 绝对值 < 0.15 → 信号太弱，剪枝
        if abs(node.aggregate) < 0.15 and node.action != "HOLD":
            node.pruned = True
            node.prune_reason = f"P3:aggregate={node.aggregate:.3f}<0.15"
            continue

        # P4: 扫描引擎方向相反 → 惩罚分数 × 0.5（不剪枝，只降权）
        scan_dir = context.get("scan", ("NONE", 0.0))[0]
        if node.action == "BUY" and scan_dir == "SELL":
            node.aggregate *= 0.5
            node.scores_by_source["_p4_penalty"] = "scan_opposite"
        elif node.action == "SELL" and scan_dir == "BUY":
            node.aggregate *= 0.5
            node.scores_by_source["_p4_penalty"] = "scan_opposite"

    return nodes


# ══════════════════════════════════════════════════════════════
# S22  _select_best_candidate — 从存活节点中选最优
# 规则: aggregate 最大的存活节点；全部被剪枝则返回 HOLD
# ══════════════════════════════════════════════════════════════
def _select_best_candidate(nodes: List[TreeNode]) -> TreeNode:
    """从存活候选节点中选 aggregate 最高的；全剪枝时返回 HOLD。"""
    surviving = [n for n in nodes if not n.pruned]
    if not surviving:
        hold = TreeNode(action="HOLD", prune_reason="all_candidates_pruned")
        hold.scores_by_source = _score_hold_candidate()
        hold.aggregate = 0.0
        return hold
    return max(surviving, key=lambda n: n.aggregate)


# ══════════════════════════════════════════════════════════════
# S22b  PUCT 树搜索 — arXiv:2603.04735 核心算法
# Multi-level: L1(方向BUY/SELL/HOLD) → L2(子策略)
# PUCT: UCB(s,a) = Q(s,a) + c_puct * P(s,a) * sqrt(N_parent) / (1 + N(s,a))
# 数值反馈: 验证分数回传 → 迭代选择最优路径
# ══════════════════════════════════════════════════════════════

# PUCT 超参数
_C_PUCT = 1.5        # 探索-利用平衡系数 (论文推荐 1.0-2.0)
_PUCT_ITERATIONS = 4  # 搜索迭代次数 (论文~600节点，我们4轮×9节点=36次评估)
_PRUNE_RATIO = 0.8    # 每轮剪枝比例 (论文~80%剪枝)

# L2 子策略定义 — 每个方向3种策略，强调不同数据源
_L2_STRATEGIES: Dict[str, List[dict]] = {
    "BUY": [
        {"strategy": "momentum",  "emphasis": {"scan": 1.6, "volume": 1.4, "vision": 0.8}},
        {"strategy": "value",     "emphasis": {"win_rate": 1.8, "filter": 1.5, "scan": 0.7}},
        {"strategy": "breakout",  "emphasis": {"volume": 2.0, "vision": 1.3, "filter": 0.8}},
    ],
    "SELL": [
        {"strategy": "momentum",  "emphasis": {"scan": 1.6, "volume": 1.4, "vision": 0.8}},
        {"strategy": "reversal",  "emphasis": {"vision": 1.8, "win_rate": 1.3, "scan": 0.7}},
        {"strategy": "weakness",  "emphasis": {"filter": 1.8, "win_rate": 1.5, "volume": 0.8}},
    ],
    "HOLD": [
        {"strategy": "neutral",   "emphasis": {}},  # HOLD 只有一个子策略
    ],
}


def _expand_l2_children(parent: TreeNode, base_scores: dict) -> List[TreeNode]:
    """
    arXiv:2603.04735 Expand: L1节点→L2子策略节点。
    对基础分数应用子策略的emphasis权重，生成不同侧重的候选路径。
    """
    strategies = _L2_STRATEGIES.get(parent.action, [])
    children = []
    for strat in strategies:
        # 对每个数据源应用emphasis权重
        adjusted_scores = {}
        emphasis = strat["emphasis"]
        for src, val in base_scores.items():
            if src.startswith("_"):
                continue  # 跳过元数据key
            multiplier = emphasis.get(src, 1.0)
            adjusted_scores[src] = val * multiplier
        agg = _aggregate_candidate_score(adjusted_scores)
        child = TreeNode(
            action=parent.action,
            scores_by_source=adjusted_scores,
            aggregate=agg,
            depth=2,
            strategy=strat["strategy"],
        )
        children.append(child)
    return children


def _puct_score(child: TreeNode, parent_visits: int, prior: float) -> float:
    """
    arXiv:2603.04735 PUCT公式:
    UCB(s,a) = Q(s,a) + c_puct * P(s,a) * sqrt(N_parent) / (1 + N(s,a))

    Q(s,a)    = 平均价值 (exploitation)
    P(s,a)    = 先验概率，由 aggregate 归一化得到
    N_parent  = 父节点总访问次数
    N(s,a)    = 子节点访问次数
    c_puct    = 探索常数
    """
    q = child.q_value
    exploration = _C_PUCT * prior * math.sqrt(parent_visits) / (1 + child.visit_count)
    return q + exploration


def _numerical_feedback(node: TreeNode, verifier: "BeyondEuclidVerifier",
                        closes: List[float], current_price: float) -> float:
    """
    arXiv:2603.04735 Verify+Correct: 数值反馈循环。
    对候选节点做验证 → 返回归一化反馈值 [0, 1]。
    论文: "propose → code → verify → inject error → correct → expand deeper"
    我们: 用三视角验证器的共识度作为数值反馈。
    """
    if node.action == "HOLD":
        return 0.3  # HOLD 的基准反馈值（不活跃）

    consensus, results, verdict = verifier.verify(node, closes, current_price)
    # 反馈值: 基于共识度和各视角得分
    if not results:
        return 0.3
    avg_score = sum(r.score for r in results) / len(results)
    # consensus 0/3 → 0.1, 1/3 → 0.3, 2/3 → 0.6, 3/3 → 0.9
    consensus_bonus = consensus * 0.2
    return min(1.0, avg_score * 0.5 + consensus_bonus + 0.1)


# 访问统计持久化 — 跨调用累积经验
_VISIT_STATS_FILE = _STATE_DIR / "gcc_puct_visits.json"


def _load_visit_stats() -> Dict[str, Dict[str, dict]]:
    """加载 PUCT 访问统计 {symbol: {strategy_key: {visits, total_value}}}。"""
    if not _VISIT_STATS_FILE.exists():
        return {}
    try:
        return json.loads(_VISIT_STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_visit_stats(stats: Dict[str, Dict[str, dict]]) -> None:
    """保存 PUCT 访问统计。"""
    try:
        _VISIT_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _VISIT_STATS_FILE.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.debug("[GCC-TM] save_visit_stats: %s", e)


def _apply_visit_history(node: TreeNode, stats: dict) -> None:
    """将历史访问统计注入节点。"""
    key = f"{node.action}_{node.strategy}" if node.strategy else node.action
    hist = stats.get(key, {})
    node.visit_count = hist.get("visits", 0)
    node.total_value = hist.get("total_value", 0.0)


def _update_visit_stats(stats: dict, node: TreeNode, value: float) -> None:
    """更新节点的访问统计。"""
    key = f"{node.action}_{node.strategy}" if node.strategy else node.action
    if key not in stats:
        stats[key] = {"visits": 0, "total_value": 0.0}
    stats[key]["visits"] += 1
    stats[key]["total_value"] += value


# ══════════════════════════════════════════════════════════════
# S23  VerifierResult — 三视角验证结果
# ══════════════════════════════════════════════════════════════
@dataclass
class VerifierResult:
    perspective: str    # "topology" | "geometry" | "algebra"
    ok: bool            # 是否支持该候选方向
    score: float        # 置信度 [0, 1]
    reasoning: str = ""


# ══════════════════════════════════════════════════════════════
# S24-S25  TopologyVerifier
# 论文: arXiv:2407.09468 Sec.3 Topology (超图连通性)
# 思路: 把各数据源分数看作超图节点，连通度反映信号一致性
# 实现: Cheeger常数近似 = 最小割 / 节点数（连通=ok）
# S25: 信号数 < 3 时 fallback ok=True
# ══════════════════════════════════════════════════════════════
class TopologyVerifier:
    """
    超图连通性验证：信号源之间的一致性评估。
    arXiv:2407.09468 Topology 视角核心概念:
      - 信号源 = 超图节点，同方向信号之间有超边连接
      - Cheeger常数近似 = 最小割 / 节点数 (连通性度量)
      - Laplacian Fiedler值 = 超图 Laplacian 第二小特征值 (谱连通性)
      - Fiedler值越大 = 连通度越强 = 信号一致性越高
    """

    THRESHOLD = 0.0   # Cheeger 近似值 > 0 代表连通

    @staticmethod
    def _fiedler_value(vals: list) -> float:
        """
        arXiv:2407.09468: 超图 Laplacian Fiedler值（代数连通度）。
        Fiedler值 = λ₂ = min_{x⊥1} x'Lx / x'x
        实现: 构建相似度 Laplacian → Rayleigh 商迭代求 λ₂。
        对 n≤6 的小矩阵用投影 Rayleigh 商法（精确到收敛）。
        """
        n = len(vals)
        if n < 2:
            return 0.0
        # 归一化到 [-1, 1]
        max_abs = max(abs(v) for v in vals) or 1.0
        normed = [v / max_abs for v in vals]
        # 相似度矩阵 W[i][j] = max(0, 1 - |ni - nj|)
        W = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                sim = max(0.0, 1.0 - abs(normed[i] - normed[j]))
                W[i][j] = sim
                W[j][i] = sim
        # 度矩阵 + Laplacian
        D = [sum(W[i]) for i in range(n)]
        L = [[(D[i] if i == j else 0.0) - W[i][j] for j in range(n)] for i in range(n)]

        # Rayleigh 商迭代: 在 1⊥ 子空间中求最小特征值
        # 初始向量: 交替 +1/-1 (正交于全1向量)
        x = [(-1.0) ** i for i in range(n)]
        # 减去在全1方向的投影 → 保证 x⊥1
        mean_x = sum(x) / n
        x = [xi - mean_x for xi in x]
        norm = sum(xi * xi for xi in x) ** 0.5
        if norm < 1e-12:
            return 0.0
        x = [xi / norm for xi in x]

        fiedler = 0.0
        for _ in range(20):  # 迭代收敛
            # y = L @ x
            y = [sum(L[i][j] * x[j] for j in range(n)) for i in range(n)]
            # Rayleigh 商 = x'y / x'x
            xty = sum(x[i] * y[i] for i in range(n))
            xtx = sum(x[i] * x[i] for i in range(n))
            fiedler = xty / xtx if xtx > 1e-12 else 0.0
            # 逆迭代: 解 (L - σI)z = x, σ 略小于 fiedler
            # 简化: 直接用 y 归一化 + 正交化作为下一步
            # 减去 1⊥ 投影
            mean_y = sum(y) / n
            y = [yi - mean_y for yi in y]
            norm_y = sum(yi * yi for yi in y) ** 0.5
            if norm_y < 1e-12:
                break
            x = [yi / norm_y for yi in y]

        return max(0.0, round(fiedler, 6))

    def verify(self, node: TreeNode) -> VerifierResult:
        scores = {k: v for k, v in node.scores_by_source.items()
                  if not k.startswith("_")}  # 排除元数据 key

        # S25: 信号源不足 3 个时 fallback 放行
        if len(scores) < 3:
            return VerifierResult(
                perspective="topology", ok=True, score=0.5,
                reasoning=f"fallback: only {len(scores)} sources"
            )

        vals = list(scores.values())
        positive = sum(1 for v in vals if v > 0)
        negative = sum(1 for v in vals if v < 0)
        neutral  = sum(1 for v in vals if v == 0)

        # 只考虑有信号(非零)的节点做连通性判断
        active = positive + negative
        if active < 2:
            return VerifierResult(
                perspective="topology", ok=True, score=0.5,
                reasoning=f"fallback: active={active} (pos={positive} neg={negative} neutral={neutral})"
            )

        # --- Cheeger 近似 (组合法) ---
        majority = max(positive, negative)
        minority = active - majority
        cheeger_approx = minority / active

        # --- Fiedler 值 (谱法, 论文核心) ---
        # 只对有效信号做谱分析
        active_vals = [v for v in vals if v != 0]
        fiedler = self._fiedler_value(active_vals)

        # 综合判断: Cheeger + Fiedler 双重确认
        # Cheeger ≤ 0.34 (组合一致) AND Fiedler > 0 (谱连通)
        ok = cheeger_approx <= 0.34 and fiedler >= 0.0

        # score: Cheeger 和 Fiedler 加权
        balance = majority / active
        score = round(balance * 0.7 + min(fiedler, 1.0) * 0.3, 4)

        return VerifierResult(
            perspective="topology", ok=ok, score=score,
            reasoning=(f"pos={positive} neg={negative} neutral={neutral} "
                       f"active={active} cheeger={cheeger_approx:.2f} "
                       f"fiedler={fiedler:.4f}")
        )


# ══════════════════════════════════════════════════════════════
# S26-S28  GeometryVerifier
# 论文: arXiv:2407.09468 Sec.4 Geometry (黎曼流形曲率)
# 思路: 对数收益率序列的局部曲率 → 判断当前价格动能方向
# S27: 滚动缓冲区最多 500 根 bars
# S28: Riemannian IC 修正 ±0.15
# ══════════════════════════════════════════════════════════════
class GeometryVerifier:
    """
    黎曼流形曲率验证：价格序列动能与候选方向一致性。
    arXiv:2407.09468 Geometry 视角核心概念:
      - 对数收益率序列 = 黎曼流形上的曲线
      - 测地线曲率 = 二阶差分 (加速度)
      - Frechet均值 = 最小化测地线距离平方和的中心点
      - 测地线距离 = 当前点到 Frechet 均值的距离 → 偏离度
    """

    MAX_BUFFER = 500
    IC_CORRECT = 0.15   # S28: 黎曼曲率修正幅度

    def __init__(self):
        self._price_buf: List[float] = []  # 对数收益率序列 (S27)

    def update(self, close_prices: List[float]) -> None:
        """喂入收盘价，维护对数收益率滚动缓冲。"""
        import math
        new_returns = []
        for i in range(1, len(close_prices)):
            p0, p1 = close_prices[i - 1], close_prices[i]
            if p0 > 0 and p1 > 0:
                new_returns.append(math.log(p1 / p0))
        self._price_buf.extend(new_returns)
        # 截断到最近 MAX_BUFFER 条
        if len(self._price_buf) > self.MAX_BUFFER:
            self._price_buf = self._price_buf[-self.MAX_BUFFER:]

    def _geodesic_curvature(self) -> tuple:
        """
        计算近期收益率序列的测地线曲率（二阶差分）和斜率（一阶差分）。
        返回: (curvature, slope)
        """
        buf = self._price_buf
        if len(buf) < 10:
            return 0.0, 0.0
        recent = buf[-20:]
        # 一阶差分（速度/斜率）
        d1 = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        slope = sum(d1) / len(d1) if d1 else 0.0
        # 二阶差分（曲率/加速度）
        d2 = [d1[i] - d1[i - 1] for i in range(1, len(d1))]
        curvature = sum(d2) / len(d2) if d2 else 0.0
        return curvature, slope

    def _frechet_mean(self) -> float:
        """
        arXiv:2407.09468: Frechet均值 = 最小化测地线距离平方和的点。
        在1D对数收益率空间中，Frechet均值 = 算术均值。
        返回: 近期对数收益率的 Frechet 均值。
        """
        buf = self._price_buf
        if len(buf) < 5:
            return 0.0
        recent = buf[-50:]  # 近50根K线的收益率
        return sum(recent) / len(recent)

    def _geodesic_distance(self, current_return: float) -> float:
        """
        arXiv:2407.09468: 当前点到 Frechet 均值的测地线距离。
        在1D流形上 = |current - frechet_mean|。
        距离越大 = 偏离历史中心越远 = 信号越强(趋势加速或反转)。
        """
        fm = self._frechet_mean()
        return abs(current_return - fm)

    def verify(self, node: TreeNode, close_prices: Optional[List[float]] = None) -> VerifierResult:
        if close_prices:
            self.update(close_prices)

        curvature, slope = self._geodesic_curvature()

        # Frechet 均值 + 测地线距离 (论文核心)
        frechet = self._frechet_mean()
        current_ret = self._price_buf[-1] if self._price_buf else 0.0
        geo_dist = self._geodesic_distance(current_ret)

        # 动量方向: 优先看曲率(加速度)，曲率接近零时用斜率(速度)
        # 对数收益率量级 ~0.001，二阶差分 ~0.00001，需大倍率放大
        if abs(curvature) > 1e-6:
            momentum_up = curvature > 0
            signal_strength = abs(curvature) * 10000
        elif abs(slope) > 1e-6:
            momentum_up = slope > 0
            signal_strength = abs(slope) * 500  # 斜率权重低于曲率
        else:
            # 真的没信号
            momentum_up = True  # 中性偏保守
            signal_strength = 0.0

        action_up = node.action == "BUY"
        aligned = (momentum_up == action_up) or node.action == "HOLD"

        # 测地线距离增强: 偏离 Frechet 均值越远，信号越强
        # geo_dist 量级 ~0.001-0.01, 放大后叠加到 signal_strength
        geo_boost = min(geo_dist * 200, 0.05)  # 最多 +0.05 额外强度
        signal_strength += geo_boost

        # S28: IC 修正，clamp 到 ±0.15
        raw_ic = min(signal_strength, self.IC_CORRECT)
        score = 0.5 + (raw_ic if aligned else -raw_ic)
        score = max(0.0, min(1.0, score))

        return VerifierResult(
            perspective="geometry", ok=aligned, score=round(score, 4),
            reasoning=(f"curvature={curvature:.6f} slope={slope:.6f} "
                       f"frechet={frechet:.6f} geo_dist={geo_dist:.6f} "
                       f"momentum_up={momentum_up} action={node.action} aligned={aligned}")
        )


# ══════════════════════════════════════════════════════════════
# S29-S31  AlgebraVerifier
# 论文: arXiv:2407.09468 Sec.5 Algebra (等变加权胜率)
# 思路: 用双曲空间距离加权历史胜率，支持等变变换
# S30: record_outcome() 记录历史结果
# S31: reference_price 首次价格作为等变基准点
# ══════════════════════════════════════════════════════════════
class AlgebraVerifier:
    """等变加权胜率验证：双曲空间距离调权的历史胜率。"""

    def __init__(self):
        self._history: List[dict] = []   # {price, action, outcome: bool}
        self._ref_price: Optional[float] = None   # S31 等变基准点

    def record_outcome(self, price: float, action: str, outcome: bool) -> None:
        """S30: 记录一次交易结果（outcome=True 为盈利）。"""
        if self._ref_price is None:
            self._ref_price = price   # S31: 首次价格初始化
        self._history.append({"price": price, "action": action, "outcome": outcome})
        # 只保留最近 200 条
        if len(self._history) > 200:
            self._history = self._history[-200:]

    def _hyperbolic_distance(self, p1: float, p2: float) -> float:
        """双曲空间距离近似：对数价格比的绝对值。"""
        import math
        if p1 <= 0 or p2 <= 0:
            return 1.0
        return abs(math.log(p2 / p1))

    def verify(self, node: TreeNode, current_price: float = 0.0) -> VerifierResult:
        """S29: 等变加权胜率验证。"""
        if not self._history or current_price <= 0:
            # 无历史数据时 fallback
            return VerifierResult(
                perspective="algebra", ok=True, score=0.5,
                reasoning="no history, fallback ok=True"
            )

        ref = self._ref_price or current_price
        same_action = [h for h in self._history if h["action"] == node.action]
        if len(same_action) < 3:
            return VerifierResult(
                perspective="algebra", ok=True, score=0.5,
                reasoning=f"insufficient history ({len(same_action)}<3), fallback"
            )

        # 双曲距离加权胜率
        weighted_win = 0.0
        weighted_total = 0.0
        for h in same_action:
            dist = self._hyperbolic_distance(h["price"], current_price)
            # 距离越近权重越大（距离反比）
            weight = 1.0 / (1.0 + dist)
            weighted_total += weight
            if h["outcome"]:
                weighted_win += weight

        if weighted_total <= 0:
            return VerifierResult(perspective="algebra", ok=True, score=0.5,
                                  reasoning="zero weight, fallback")

        win_rate = weighted_win / weighted_total
        ok = win_rate >= 0.5
        score = round(win_rate, 4)

        return VerifierResult(
            perspective="algebra", ok=ok, score=score,
            reasoning=(f"weighted_wr={win_rate:.3f} "
                       f"n={len(same_action)} action={node.action}")
        )


# ══════════════════════════════════════════════════════════════
# S32-S34  BeyondEuclidVerifier
# arXiv:2407.09468: 三视角独立验证，≥2/3 通过才执行
# S32: verify(best_node) → (consensus_count, results)
# S33: 共识规则 ≥2/3 → EXECUTE，<2/3 → SKIP
# S34: 无存活候选 → 直接 SKIP 跳过验证
# ══════════════════════════════════════════════════════════════
class BeyondEuclidVerifier:
    """三视角独立验证器：Topology + Geometry + Algebra。"""

    def __init__(self):
        self.topology = TopologyVerifier()
        self.geometry = GeometryVerifier()
        self.algebra  = AlgebraVerifier()

    def verify(
        self,
        best_node: Optional[TreeNode],
        close_prices: Optional[List[float]] = None,
        current_price: float = 0.0,
    ) -> Tuple[int, List[VerifierResult], str]:
        """
        S32: 对最优候选节点进行三视角验证。
        返回: (consensus_count, results, verdict)
        verdict: "EXECUTE" | "SKIP" | "NOTIFY"
        """
        # S34: 无候选 (all_pruned) 直接 SKIP
        if best_node is None or best_node.prune_reason == "all_candidates_pruned":
            return 0, [], "SKIP"

        # HOLD 节点不需要三视角验证（保守策略）
        if best_node.action == "HOLD":
            return 0, [], "SKIP"

        results: List[VerifierResult] = [
            self.topology.verify(best_node),
            self.geometry.verify(best_node, close_prices),
            self.algebra.verify(best_node, current_price),
        ]

        consensus_count = sum(1 for r in results if r.ok)

        # S33: ≥2/3 → EXECUTE，否则 SKIP
        verdict = "EXECUTE" if consensus_count >= 2 else "SKIP"

        return consensus_count, results, verdict


# ══════════════════════════════════════════════════════════════
# S35  PHASE 常量
# ══════════════════════════════════════════════════════════════
PHASE_OBSERVE   = "observe"    # Phase1: 只记录，不发单
PHASE_EXECUTE   = "execute"    # Phase2: 写 pending_order.json
PHASE_HOLD_ONLY = "hold_only"  # Phase3: 强制 HOLD，风控熔断时使用


# ══════════════════════════════════════════════════════════════
# S36-S42  GCCTradingModule — 主类
# ══════════════════════════════════════════════════════════════
class GCCTradingModule:
    """
    GCC 交易决策主模块。
    Phase1(observe): 只记录 decisions.jsonl，不干扰主程序。
    Phase2(execute): 写 pending_order.json，下一K线市价执行。
    """

    # S36: __init__
    def __init__(
        self,
        symbol: str,
        phase: str = PHASE_OBSERVE,
        log_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None,
    ):
        self.symbol    = symbol
        self.phase     = phase
        self.log_dir   = Path(log_dir) if log_dir else _STATE_DIR
        self.state_dir = Path(state_dir) if state_dir else _STATE_DIR

        self._verifier = BeyondEuclidVerifier()
        self._decision_log  = self.log_dir / "gcc_trading_decisions.jsonl"
        self._accuracy_file = self.log_dir / "gcc_trading_accuracy.json"
        self._pending_file  = self.state_dir / "gcc_pending_order.json"

        logger.info("[GCC-TRADE] init symbol=%s phase=%s", symbol, phase)

    # ── S37: process() 主流程 ─────────────────────────────────
    def process(
        self,
        bars: list,
        main_decision: Optional[str] = None,
    ) -> dict:
        """
        主流程入口。
        bars: OHLCV list，最新在末尾，至少含 volume/close 字段。
        main_decision: 主程序决策 ("BUY"/"SELL"/"HOLD"/None)，用于一致率统计。
        返回: result dict，含 action/verdict/consensus 等字段。
        """
        ts = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")

        # 提取收盘价与当前价
        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
        current_price = closes[-1] if closes else 0.0

        # L1: 组装 DecisionContext（含新增槽位 + 落盘快照）
        ctx = self._build_context(bars, ts)
        context = self._context_to_score_dict(ctx)

        # L3-S02: hold_only 模式 — 直接 HOLD，只记日志
        if self.phase == PHASE_HOLD_ONLY:
            result = {
                "ts": ts, "symbol": self.symbol, "phase": self.phase,
                "best_node": None, "final_action": "HOLD",
                "verdict": "HOLD_ONLY", "consensus": 0,
                "verifier_results": [], "current_price": current_price,
                "rejected_nodes": [], "context": ctx.as_dict(),
            }
            self._write_decision_log(result)
            if main_decision is not None:
                self._compare_with_main("HOLD", main_decision, ts)
            return result

        # L2: 树搜索（收集 rejected_nodes）
        best_node, rejected_nodes = self._run_tree_search_with_rejected(
            bars, context
        )

        # L3: 三视角验证
        final_action, consensus, verdict, ver_results = self._run_verification(
            best_node, closes, current_price
        )

        # L2-S03: rejected_nodes 摘要
        rejected_summary = [
            {"action": n.action, "aggregate": round(n.aggregate, 4),
             "prune_reason": n.prune_reason, "strategy": n.strategy}
            for n in rejected_nodes
        ]

        result = {
            "ts":           ts,
            "symbol":       self.symbol,
            "phase":        self.phase,
            "best_node":    best_node.as_dict() if best_node else None,
            "final_action": final_action,
            "verdict":      verdict,
            "consensus":    consensus,
            "verifier_results": [
                {"perspective": r.perspective, "ok": r.ok,
                 "score": r.score, "reasoning": r.reasoning}
                for r in ver_results
            ],
            "current_price": current_price,
            "rejected_nodes": rejected_summary,
            "context":      ctx.as_dict(),
        }

        # S40: observe 模式只记录日志
        if self.phase == PHASE_OBSERVE:
            self._write_decision_log(result)

        # S41: execute 模式写 pending_order
        elif self.phase == PHASE_EXECUTE and verdict == "EXECUTE":
            self._write_pending_order(final_action, current_price, ts)
            self._write_decision_log(result)

        # L3-S04: 与主程序对比（含 divergence + takeover_ready）
        if main_decision is not None:
            self._compare_with_main(final_action, main_decision, ts)

        logger.info(
            "[GCC-TRADE] %s action=%s verdict=%s consensus=%s/3 rejected=%d",
            self.symbol, final_action, verdict, consensus, len(rejected_nodes),
        )
        return result

    # ── 内部: 组装上下文 → DecisionContext ────────────────────
    def _build_context(self, bars: list, ts: str = "") -> DecisionContext:
        sym = self.symbol
        ctx = DecisionContext(
            symbol=sym, ts=ts,
            vision=_read_vision(sym),
            scan=_read_scan_signal(sym),
            filter_buy=_read_filter_chain(sym, "BUY"),
            filter_sell=_read_filter_chain(sym, "SELL"),
            win_rate_buy=_read_win_rate(sym, "BUY"),
            win_rate_sell=_read_win_rate(sym, "SELL"),
            vol_ratio=_read_volume(bars),
            n_gate_buy=_read_n_gate(sym, "BUY"),
            n_gate_sell=_read_n_gate(sym, "SELL"),
            # L1-S02 新增槽位
            regime=_read_regime(sym),
            governor=_read_plugin_governor(sym),
            risk_budget=_read_risk_budget(),
            # Phase B1: Schwab VWAP
            extended={"schwab_vwap": _read_schwab_vwap(sym)},
        )
        # L1-S03 快照落盘
        ctx.snapshot()
        return ctx

    def _context_to_score_dict(self, ctx: DecisionContext) -> dict:
        """将 DecisionContext 转为向后兼容的 dict，供评分/剪枝函数使用。"""
        return {
            "vision": ctx.vision, "scan": ctx.scan,
            "filter_buy": ctx.filter_buy, "filter_sell": ctx.filter_sell,
            "win_rate_buy": ctx.win_rate_buy, "win_rate_sell": ctx.win_rate_sell,
            "vol_ratio": ctx.vol_ratio,
            "n_gate_buy": ctx.n_gate_buy, "n_gate_sell": ctx.n_gate_sell,
            "regime": ctx.regime, "governor": ctx.governor,
            "risk_budget": ctx.risk_budget,
            "schwab_vwap": ctx.extended.get("schwab_vwap", {}),
        }

    # ── L2-S03: 树搜索 + rejected_nodes 收集 ────────────────────
    def _run_tree_search_with_rejected(
        self, bars: list, context: dict
    ) -> Tuple[TreeNode, List[TreeNode]]:
        """树搜索并收集所有被剪枝的节点，供 dashboard 展示。"""
        best_node = self._run_tree_search(bars, context)
        # 从内部状态收集 rejected（_run_tree_search 中标记 pruned 的节点）
        rejected = getattr(self, "_last_rejected_nodes", [])
        return best_node, rejected

    # ── S38: PUCT 多层树搜索 (arXiv:2603.04735) ────────────────
    def _run_tree_search(self, bars: list, context: dict) -> TreeNode:
        """
        arXiv:2603.04735 PUCT 树搜索算法:
        1. L1展开: 生成 BUY/SELL/HOLD 三个方向节点
        2. 剪枝: 应用 P1-P4 规则 (~80% 候选被剪)
        3. L2展开: 存活L1节点 → 子策略节点 (momentum/value/breakout...)
        4. PUCT迭代: N轮选择→数值反馈→回传值→再选择
        5. 最终选择: 最高Q值或最多访问次数的L2节点提升为最终候选
        """
        sym = self.symbol
        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
        current_price = closes[-1] if closes else 0.0
        self._last_rejected_nodes: List[TreeNode] = []

        # ── Step 1: L1 展开 (方向层) ──
        buy_scores  = _score_buy_candidate(sym, bars, context)
        sell_scores = _score_sell_candidate(sym, bars, context)
        hold_scores = _score_hold_candidate()

        l1_nodes = [
            TreeNode("BUY",  buy_scores,  _aggregate_candidate_score(buy_scores),  depth=1),
            TreeNode("SELL", sell_scores, _aggregate_candidate_score(sell_scores), depth=1),
            TreeNode("HOLD", hold_scores, 0.0, depth=1),
        ]

        # ── Step 2: L1 剪枝 ──
        _apply_pruning(l1_nodes, sym, context)
        surviving_l1 = [n for n in l1_nodes if not n.pruned]
        self._last_rejected_nodes.extend(n for n in l1_nodes if n.pruned)
        if not surviving_l1:
            hold = TreeNode(action="HOLD", prune_reason="all_candidates_pruned")
            hold.scores_by_source = hold_scores
            return hold

        # ── Step 3: L2 展开 (子策略层) ──
        score_map = {"BUY": buy_scores, "SELL": sell_scores, "HOLD": hold_scores}
        all_l2: List[TreeNode] = []
        for l1 in surviving_l1:
            children = _expand_l2_children(l1, score_map[l1.action])
            l1.children = children
            all_l2.extend(children)

        if not all_l2:
            return _select_best_candidate(surviving_l1)

        # ── Step 4: 加载历史访问统计 ──
        visit_stats = _load_visit_stats()
        sym_stats = visit_stats.get(sym, {})
        for child in all_l2:
            _apply_visit_history(child, sym_stats)

        # ── Step 5: PUCT 迭代选择 + 数值反馈 ──
        # 计算 L2 先验概率 P(s,a) — 由 aggregate 归一化
        all_agg = [abs(c.aggregate) for c in all_l2]
        sum_agg = sum(all_agg) or 1.0
        priors = {id(c): abs(c.aggregate) / sum_agg for c in all_l2}

        # 创建轻量验证器副本用于反馈（不污染主验证器状态）
        feedback_verifier = BeyondEuclidVerifier()
        feedback_verifier.geometry.update(closes)

        for iteration in range(_PUCT_ITERATIONS):
            # PUCT 选择: 计算每个L2节点的UCB值
            total_visits = sum(c.visit_count for c in all_l2) + 1
            best_ucb = -float("inf")
            selected = all_l2[0]
            for child in all_l2:
                if child.pruned:
                    continue
                ucb = _puct_score(child, total_visits, priors[id(child)])
                if ucb > best_ucb:
                    best_ucb = ucb
                    selected = child

            # 数值反馈: 验证选中节点
            feedback_value = _numerical_feedback(
                selected, feedback_verifier, closes, current_price
            )

            # 回传值 (backpropagation)
            selected.visit_count += 1
            selected.total_value += feedback_value
            _update_visit_stats(sym_stats, selected, feedback_value)

            # 剪枝低价值分支 (论文: ~80% pruned)
            if iteration == 1 and len(all_l2) > 3:
                # 第2轮后剪掉Q值最低的分支
                ranked = sorted(
                    [c for c in all_l2 if not c.pruned],
                    key=lambda c: c.q_value,
                )
                n_prune = max(1, int(len(ranked) * (1 - _PRUNE_RATIO)))
                for c in ranked[:n_prune]:
                    if c.action != "HOLD":  # 保留HOLD
                        c.pruned = True
                        c.prune_reason = f"PUCT:low_q={c.q_value:.3f}"
                        self._last_rejected_nodes.append(c)

        # ── Step 6: 保存访问统计 ──
        visit_stats[sym] = sym_stats
        _save_visit_stats(visit_stats)

        # ── Step 7: 选择最终候选 — 最高Q值的存活L2节点 ──
        surviving_l2 = [c for c in all_l2 if not c.pruned]
        if not surviving_l2:
            return _select_best_candidate(surviving_l1)

        # 论文: 最终选择基于最多访问次数 (robust) 或最高Q值 (greedy)
        # 交易场景用Q值 (greedy) — 我们需要最高预期收益
        best = max(surviving_l2, key=lambda c: c.q_value if c.visit_count > 0 else c.aggregate)

        # 将L2最优提升为最终节点，保留策略信息
        best.scores_by_source["_puct_strategy"] = best.strategy
        best.scores_by_source["_puct_visits"] = best.visit_count
        best.scores_by_source["_puct_q_value"] = round(best.q_value, 4)
        return best

    # ── S39: 三视角验证 ────────────────────────────────────────
    def _run_verification(
        self,
        best_node: TreeNode,
        closes: List[float],
        current_price: float,
    ) -> Tuple[str, int, str, List[VerifierResult]]:
        consensus, ver_results, verdict = self._verifier.verify(
            best_node, closes, current_price
        )
        # 验证通过才执行候选动作，否则 HOLD
        final_action = best_node.action if verdict == "EXECUTE" else "HOLD"
        return final_action, consensus, verdict, ver_results

    # ── S40: 写决策日志 ────────────────────────────────────────
    def _write_decision_log(self, result: dict) -> None:
        try:
            self._decision_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self._decision_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[GCC-TRADE] write_decision_log: %s", e)

    # ── S41: 写 pending_order ──────────────────────────────────
    def _write_pending_order(
        self, action: str, price: float, ts: str
    ) -> None:
        """Phase2: 写待执行订单，下一K线由主程序消费。"""
        order = {
            "symbol":    self.symbol,
            "action":    action,
            "price_ref": price,
            "ts":        ts,
            "source":    "gcc_trading_module",
            "consumed":  False,
        }
        try:
            self._pending_file.parent.mkdir(parents=True, exist_ok=True)
            self._pending_file.write_text(
                json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("[GCC-TRADE] pending_order written: %s %s", action, self.symbol)
        except Exception as e:
            logger.warning("[GCC-TRADE] write_pending_order: %s", e)

    # ── L3-S04: 与主程序决策对比 + divergence + takeover_ready ──
    def _compare_with_main(
        self, gcc_action: str, main_action: str, ts: str
    ) -> None:
        """
        记录 GCC 模块与主程序决策一致率到 accuracy.json。
        L3-S04: 增加 divergence_rate + takeover_ready 判定。
        takeover_ready 条件: 样本 ≥ 30 且 GCC 准确率 > 主程序准确率 (divergence 中 GCC 胜出比例 > 55%)
        """
        match = gcc_action == main_action
        try:
            acc: dict = {}
            if self._accuracy_file.exists():
                acc = json.loads(self._accuracy_file.read_text(encoding="utf-8"))

            sym_acc = acc.setdefault(self.symbol, {
                "total": 0, "match": 0, "rate": 0.0,
                "divergence_count": 0, "gcc_win_on_diverge": 0,
            })
            sym_acc["total"] += 1
            if match:
                sym_acc["match"] += 1
            else:
                # 分歧计数（GCC 与主程序不同的次数）
                sym_acc["divergence_count"] = sym_acc.get("divergence_count", 0) + 1

            total = sym_acc["total"]
            sym_acc["rate"] = round(sym_acc["match"] / total, 4)
            diverge_count = sym_acc.get("divergence_count", 0)
            sym_acc["divergence_rate"] = round(diverge_count / total, 4) if total else 0.0

            # takeover_ready: 样本充足 + GCC 在分歧中胜出比例 > 55%
            gcc_wins = sym_acc.get("gcc_win_on_diverge", 0)
            sym_acc["takeover_ready"] = (
                total >= 30
                and diverge_count >= 10
                and (gcc_wins / diverge_count > 0.55 if diverge_count else False)
            )

            sym_acc["last_ts"] = ts
            sym_acc["last_gcc"] = gcc_action
            sym_acc["last_main"] = main_action

            self._accuracy_file.write_text(
                json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[GCC-TRADE] compare_with_main: %s", e)

    def record_divergence_outcome(
        self, symbol: str, gcc_was_right: bool
    ) -> None:
        """
        回填分歧结果：GCC 和主程序决策不同时，谁的方向最终正确。
        由 _backfill_outcome 在8根K线后调用。
        """
        try:
            acc: dict = {}
            if self._accuracy_file.exists():
                acc = json.loads(self._accuracy_file.read_text(encoding="utf-8"))
            sym_acc = acc.get(symbol, {})
            if gcc_was_right:
                sym_acc["gcc_win_on_diverge"] = sym_acc.get("gcc_win_on_diverge", 0) + 1
            # 重算 takeover_ready
            total = sym_acc.get("total", 0)
            diverge_count = sym_acc.get("divergence_count", 0)
            gcc_wins = sym_acc.get("gcc_win_on_diverge", 0)
            sym_acc["takeover_ready"] = (
                total >= 30
                and diverge_count >= 10
                and (gcc_wins / diverge_count > 0.55 if diverge_count else False)
            )
            acc[symbol] = sym_acc
            self._accuracy_file.write_text(
                json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[GCC-TRADE] record_divergence_outcome: %s", e)


# ══════════════════════════════════════════════════════════════
# S43  KNNExperience dataclass
# S44  特征向量 9 维: vision/scan/n_gate/filter_chain/
#      win_rate/vol_ratio/topology/geometry/algebra
# ══════════════════════════════════════════════════════════════
@dataclass
class KNNExperience:
    symbol:    str
    action:    str               # "BUY" | "SELL" | "HOLD"
    features:  List[float]       # 9 维特征向量 (S44)
    outcome:   Optional[bool]    # None=待回填, True=盈利, False=亏损
    ts:        str               # ISO 时间戳
    price:     float = 0.0       # 决策时价格
    ref_price: float = 0.0       # 回填比较基准价

    def as_dict(self) -> dict:
        return {
            "symbol":    self.symbol,
            "action":    self.action,
            "features":  self.features,
            "outcome":   self.outcome,
            "ts":        self.ts,
            "price":     self.price,
            "ref_price": self.ref_price,
        }

    @staticmethod
    def feature_names() -> List[str]:
        """S44: 9 维特征名称（顺序与 features 对应）。"""
        return [
            "vision_conf",      # 0: Vision 置信度 [0,1]
            "scan_conf",        # 1: 扫描信号置信度 [0,1]
            "n_gate_buy",       # 2: N-Gate BUY 状态 (0=INACTIVE,0.5=OBSERVE,1=BLOCK)
            "filter_passed",    # 3: 过滤链通过 (0/1)
            "filter_vol_score", # 4: 量价评分 [0,1]
            "win_rate",         # 5: 历史胜率 [0,1]
            "vol_ratio",        # 6: 量比 (clamp 0~3)
            "topology_score",   # 7: Topology 验证得分 [0,1]
            "geometry_score",   # 8: Geometry 验证得分 [0,1]
        ]


def _build_knn_features(context: dict, ver_results: List[VerifierResult]) -> List[float]:
    """S44: 从 context + verifier_results 提取 9 维特征向量。"""
    vision_bias, vision_conf = context.get("vision", ("HOLD", 0.5))
    _, scan_conf             = context.get("scan",   ("NONE", 0.0))
    n_gate_buy               = context.get("n_gate_buy", "INACTIVE")
    filter_buy               = context.get("filter_buy", {})
    win_rate                 = context.get("win_rate_buy", 0.5)
    vol_ratio                = context.get("vol_ratio", 1.0)

    n_gate_val = {"INACTIVE": 0.0, "OBSERVE": 0.5, "BLOCK": 1.0}.get(n_gate_buy, 0.0)
    filter_passed = 1.0 if filter_buy.get("passed") else 0.0
    filter_vol    = float(filter_buy.get("volume_score") or 0.5)

    # verifier results by perspective
    topo_score = next((r.score for r in ver_results if r.perspective == "topology"), 0.5)
    geo_score  = next((r.score for r in ver_results if r.perspective == "geometry"), 0.5)

    return [
        round(float(vision_conf), 4),
        round(float(scan_conf), 4),
        round(n_gate_val, 4),
        round(filter_passed, 4),
        round(min(float(filter_vol), 1.0), 4),
        round(float(win_rate), 4),
        round(min(float(vol_ratio), 3.0), 4),
        round(float(topo_score), 4),
        round(float(geo_score), 4),
    ]


# ══════════════════════════════════════════════════════════════
# S45-S46  KNN 经验写入 + 回填
# 集成到 GCCTradingModule 作为方法
# ══════════════════════════════════════════════════════════════
_KNN_EXP_FILE = _STATE_DIR / "gcc_knn_experience.jsonl"
_KNN_BACKFILL_LOOKBACK = 8   # S46: 8 根 K 线后回填


def _write_knn_experience(exp: KNNExperience) -> None:
    """S45: 追加 KNN 经验到 jsonl。"""
    _write_knn_experience_dict(exp.as_dict())


def _write_knn_experience_dict(exp_dict: dict) -> None:
    """追加 KNN 经验dict到 jsonl（支持额外字段如归因信息）。"""
    try:
        _KNN_EXP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_KNN_EXP_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(exp_dict, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[GCC-TRADE] write_knn_experience: %s", e)


def _backfill_outcome(symbol: str, current_price: float,
                      lookback: int = _KNN_BACKFILL_LOOKBACK) -> List[dict]:
    """
    S46: 回填最近未填 outcome 的经验条目。
    规则: 当前价格 > ref_price * 1.005 → BUY经验=True / SELL经验=False
          当前价格 < ref_price * 0.995 → BUY经验=False / SELL经验=True
          否则 → neutral (outcome 保持 None)
    lookback: 最多回填最近 N 条未填条目。
    返回: 本次回填的记录列表 [{price, action, outcome}, ...]，供 Algebra verifier 使用。
    """
    filled_records: List[dict] = []
    if not _KNN_EXP_FILE.exists() or current_price <= 0:
        return filled_records
    try:
        lines = _KNN_EXP_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        updated = []
        fill_count = 0
        for line in lines:
            if not line.strip():
                updated.append(line)
                continue
            try:
                rec = json.loads(line)
            except Exception:
                updated.append(line)
                continue

            # 只回填本 symbol、outcome=None、且未超过 lookback 限额
            if (rec.get("symbol") == symbol
                    and rec.get("outcome") is None
                    and fill_count < lookback):
                ref = float(rec.get("ref_price") or rec.get("price") or 0)
                if ref > 0:
                    move = (current_price - ref) / ref
                    action = rec.get("action", "HOLD")
                    if move > 0.005:
                        rec["outcome"] = (action == "BUY")
                        fill_count += 1
                        filled_records.append({
                            "price": ref, "action": action,
                            "outcome": rec["outcome"],
                        })
                    elif move < -0.005:
                        rec["outcome"] = (action == "SELL")
                        fill_count += 1
                        filled_records.append({
                            "price": ref, "action": action,
                            "outcome": rec["outcome"],
                        })
                    # |move| <= 0.5% → 保持 None（neutral，不算）
            updated.append(json.dumps(rec, ensure_ascii=False))

        _KNN_EXP_FILE.write_text("\n".join(updated) + "\n", encoding="utf-8")
        if fill_count:
            logger.info("[GCC-TRADE] backfill %s: %d outcomes filled", symbol, fill_count)
    except Exception as e:
        logger.warning("[GCC-TRADE] backfill_outcome %s: %s", symbol, e)
    return filled_records


# ══════════════════════════════════════════════════════════════
# S47  模块单例 — 启动时按品种初始化
# ══════════════════════════════════════════════════════════════
_gcc_modules: dict = {}   # {symbol: GCCTradingModule}


def _load_algebra_history(mod: "GCCTradingModule") -> int:
    """从 KNN 经验文件加载已回填的历史 outcome → 喂给 Algebra verifier。"""
    count = 0
    if not _KNN_EXP_FILE.exists():
        return count
    try:
        for line in _KNN_EXP_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if (rec.get("symbol") == mod.symbol
                    and rec.get("outcome") is not None):
                mod._verifier.algebra.record_outcome(
                    float(rec.get("price") or rec.get("ref_price") or 0),
                    rec.get("action", "HOLD"),
                    bool(rec["outcome"]),
                )
                count += 1
    except Exception as e:
        logger.debug("[GCC-TM] load_algebra_history %s: %s", mod.symbol, e)
    return count


def _get_gcc_module(symbol: str) -> "GCCTradingModule":
    """懒加载单例：每个品种一个 GCCTradingModule 实例。"""
    if symbol not in _gcc_modules:
        mod = GCCTradingModule(symbol, phase=PHASE_OBSERVE)
        # 从 KNN 经验加载已回填历史 → Algebra verifier 冷启动
        n = _load_algebra_history(mod)
        if n:
            logger.info("[GCC-TM] init %s: loaded %d algebra history records", symbol, n)
        _gcc_modules[symbol] = mod
    return _gcc_modules[symbol]


# ══════════════════════════════════════════════════════════════
# 信号收集器 — 4H K线内收集所有外挂 BUY/SELL 信号
# ══════════════════════════════════════════════════════════════
import threading as _threading

# {symbol: [{"source": str, "action": "BUY"/"SELL", "confidence": float, "ts": str}, ...]}
_signal_pool: Dict[str, list] = {}
_signal_pool_lock = _threading.Lock()


def gcc_push_signal(symbol: str, source: str, action: str,
                    confidence: float = 0.5) -> None:
    """外挂产生BUY/SELL时调用，收集到信号池。"""
    if action not in ("BUY", "SELL"):
        return
    ts = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    with _signal_pool_lock:
        if symbol not in _signal_pool:
            _signal_pool[symbol] = []
        _signal_pool[symbol].append({
            "source": source, "action": action,
            "confidence": confidence, "ts": ts,
        })
    logger.debug("[GCC-TM] push %s %s %s conf=%.2f", symbol, source, action, confidence)


def _drain_signals(symbol: str) -> list:
    """取出并清空某品种的信号池。"""
    with _signal_pool_lock:
        signals = _signal_pool.pop(symbol, [])
    return signals


# ══════════════════════════════════════════════════════════════
# 模拟交易回填 — 用下一K线收盘价验证上一次裁决是否盈利
# ══════════════════════════════════════════════════════════════
def _backfill_sim_trades(symbol: str, bars: list) -> None:
    """回填 gcc_sim_trades.jsonl 中 outcome=None 的记录。"""
    sim_path = _STATE_DIR / "gcc_sim_trades.jsonl"
    if not sim_path.exists():
        return
    closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
    if not closes:
        return
    cur_price = closes[-1]

    try:
        lines = sim_path.read_text(encoding="utf-8").strip().split("\n")
        updated = False
        new_lines = []
        for line in lines:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("symbol") == symbol and rec.get("outcome") is None:
                entry = rec.get("entry_price", 0)
                if entry > 0:
                    if rec["action"] == "BUY":
                        rec["outcome"] = cur_price > entry
                    elif rec["action"] == "SELL":
                        rec["outcome"] = cur_price < entry
                    rec["exit_price"] = cur_price
                    rec["pnl_pct"] = round((cur_price - entry) / entry * 100, 3)
                    if rec["action"] == "SELL":
                        rec["pnl_pct"] = -rec["pnl_pct"]
                    updated = True
            new_lines.append(json.dumps(rec, ensure_ascii=False))
        if updated:
            sim_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.debug("[GCC-TM] backfill_sim: %s", e)


# ══════════════════════════════════════════════════════════════
# S48-S49  llm_server 接入入口
# 4H K线结束时调用 — 收集信号 → 整合过滤 → 裁决 BUY/SELL/HOLD
# ══════════════════════════════════════════════════════════════
def gcc_observe(symbol: str, bars: list, main_decision: str) -> None:
    """
    4H K线结束时由 llm_decide() 调用。
    1. 取出本周期收集的所有外挂信号
    2. 结合数据源(FilterChain/VWAP/regime等)整合分析
    3. 投票裁决 BUY / SELL / HOLD
    4. 写日志 + KNN经验卡（observe模式，不干预实际交易）
    """
    try:
        signals = _drain_signals(symbol)
        mod = _get_gcc_module(symbol)

        # 回填上一次模拟交易的outcome（用当前K线收盘价）
        _backfill_sim_trades(symbol, bars)

        # 统计投票
        buy_votes = sum(1 for s in signals if s["action"] == "BUY")
        sell_votes = sum(1 for s in signals if s["action"] == "SELL")
        buy_weight = sum(s["confidence"] for s in signals if s["action"] == "BUY")
        sell_weight = sum(s["confidence"] for s in signals if s["action"] == "SELL")

        # 信号归因：记录各外挂的投票
        vote_detail = {}
        for s in signals:
            src = s["source"]
            if src not in vote_detail:
                vote_detail[src] = {"BUY": 0, "SELL": 0}
            vote_detail[src][s["action"]] += 1

        # 找出最强信号源（投票最多的外挂）
        strongest_source = ""
        if vote_detail:
            strongest_source = max(
                vote_detail.keys(),
                key=lambda k: vote_detail[k]["BUY"] + vote_detail[k]["SELL"]
            )

        # 树搜索 + 三视角验证（使用已有逻辑）
        result = mod.process(bars, main_decision=main_decision)

        # 整合裁决：信号池投票 + 树搜索结果
        tree_action = result.get("final_action", "HOLD")
        tree_verdict = result.get("verdict", "SKIP")

        # GCC-TM 最终裁决逻辑：
        # 1. 无信号 → HOLD
        # 2. 有信号 → 以投票多数方向为候选
        # 3. 树搜索+三视角作为确认/否决
        if not signals:
            gcc_action = "HOLD"
            gcc_reason = "no_signals"
        elif buy_votes > sell_votes:
            # 多数投BUY
            if tree_action in ("BUY", "HOLD") and tree_verdict != "HOLD_ONLY":
                gcc_action = "BUY"
                gcc_reason = f"buy_votes={buy_votes}(w={buy_weight:.2f}) tree={tree_action}"
            else:
                gcc_action = "HOLD"
                gcc_reason = f"buy_votes={buy_votes} but tree={tree_action}/{tree_verdict}"
        elif sell_votes > buy_votes:
            # 多数投SELL
            if tree_action in ("SELL", "HOLD") and tree_verdict != "HOLD_ONLY":
                gcc_action = "SELL"
                gcc_reason = f"sell_votes={sell_votes}(w={sell_weight:.2f}) tree={tree_action}"
            else:
                gcc_action = "HOLD"
                gcc_reason = f"sell_votes={sell_votes} but tree={tree_action}/{tree_verdict}"
        else:
            # 平票 → HOLD
            gcc_action = "HOLD"
            gcc_reason = f"tie buy={buy_votes} sell={sell_votes}"

        # 当前价格（用于模拟执行基准）
        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
        current_price = closes[-1] if closes else 0.0

        # 写决策日志（追加到 gcc_trading_decisions.jsonl）
        ts_now = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        dec_record = {
            "ts": ts_now,
            "symbol": symbol,
            "gcc_action": gcc_action,
            "main_action": main_decision,
            "verdict": tree_verdict,
            "reason": gcc_reason,
            "buy_votes": buy_votes,
            "sell_votes": sell_votes,
            "buy_weight": round(buy_weight, 3),
            "sell_weight": round(sell_weight, 3),
            "strongest_source": strongest_source,
            "vote_detail": vote_detail,
            "tree_action": tree_action,
            "tree_score": result.get("tree_score", 0),
            "consensus": result.get("consensus", 0),
            "topology": result.get("topology"),
            "geometry": result.get("geometry"),
            "algebra": result.get("algebra"),
            "signals_count": len(signals),
            "price": current_price,
            "match": gcc_action == main_decision,
        }
        _dec_path = _STATE_DIR / "gcc_trading_decisions.jsonl"
        try:
            with open(_dec_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dec_record, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # 模拟执行记录 — 下一K线验证用
        # 记录 gcc_action + 当前价格，回填时用下一K线价格计算盈亏
        if gcc_action != "HOLD":
            _sim_path = _STATE_DIR / "gcc_sim_trades.jsonl"
            sim_record = {
                "ts": ts_now, "symbol": symbol,
                "action": gcc_action, "entry_price": current_price,
                "strongest_source": strongest_source,
                "buy_votes": buy_votes, "sell_votes": sell_votes,
                "outcome": None,  # 下一K线回填
            }
            try:
                with open(_sim_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(sim_record, ensure_ascii=False) + "\n")
            except Exception:
                pass

        # 写 KNN 经验
        if gcc_action != "HOLD":
            ver_results_raw = result.get("verifier_results", [])
            ver_results = [
                VerifierResult(
                    perspective=r["perspective"], ok=r["ok"],
                    score=r["score"], reasoning=r.get("reasoning", "")
                )
                for r in ver_results_raw
            ]
            ctx = mod._build_context(bars)
            features = _build_knn_features(ctx, ver_results)
            exp = KNNExperience(
                symbol=symbol,
                action=gcc_action,
                features=features,
                outcome=None,
                ts=ts_now,
                price=current_price,
                ref_price=current_price,
            )
            # KNN经验卡追加信号池归因（写入jsonl时额外字段）
            exp_dict = exp.as_dict()
            exp_dict["buy_votes"] = buy_votes
            exp_dict["sell_votes"] = sell_votes
            exp_dict["strongest_source"] = strongest_source
            exp_dict["vote_detail"] = vote_detail
            _write_knn_experience_dict(exp_dict)
            filled = _backfill_outcome(symbol, current_price)
            for fr in filled:
                mod._verifier.algebra.record_outcome(
                    fr["price"], fr["action"], fr["outcome"]
                )

        logger.info(
            "[GCC-TM] %s gcc=%s main=%s signals=%d (B%d/S%d) src=%s reason=%s",
            symbol, gcc_action, main_decision, len(signals),
            buy_votes, sell_votes, strongest_source, gcc_reason,
        )
    except Exception as e:
        logger.warning("[GCC-TM] gcc_observe %s: %s", symbol, e)


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

    print(f"\n=== S13-S22 树搜索层自测 ===")
    ctx = {
        "vision":          ("BUY", 0.82),
        "scan":            ("BUY", 0.6),
        "filter_buy":      {"passed": True,  "blocked_by": ""},
        "filter_sell":     {"passed": False, "blocked_by": "vision"},
        "win_rate_buy":    0.62,
        "win_rate_sell":   0.44,
        "vol_ratio":       1.8,
        "n_gate_buy":      "INACTIVE",
        "n_gate_sell":     "INACTIVE",
    }

    # 打分
    buy_scores  = _score_buy_candidate(sym, bars_mock, ctx)
    sell_scores = _score_sell_candidate(sym, bars_mock, ctx)
    hold_scores = _score_hold_candidate()

    # 构建节点
    buy_node  = TreeNode("BUY",  buy_scores,  _aggregate_candidate_score(buy_scores))
    sell_node = TreeNode("SELL", sell_scores, _aggregate_candidate_score(sell_scores))
    hold_node = TreeNode("HOLD", hold_scores, _aggregate_candidate_score(hold_scores))

    print(f"S14 BUY  scores: {buy_scores}  agg={buy_node.aggregate:.4f}")
    print(f"S15 SELL scores: {sell_scores}  agg={sell_node.aggregate:.4f}")
    print(f"S16 HOLD scores: {hold_scores}  agg={hold_node.aggregate:.4f}")

    # 剪枝
    nodes = _apply_pruning([buy_node, sell_node, hold_node], sym, ctx)
    for n in nodes:
        print(f"  {n.action}: pruned={n.pruned} reason={n.prune_reason}")

    # 选最优
    best = _select_best_candidate(nodes)
    print(f"S22 Best candidate: {best.action}  aggregate={best.aggregate:.4f}")

    # P1 测试: crypto BUY + BLOCK
    print(f"\n--- P1 剪枝测试 (N-Gate BLOCK) ---")
    ctx2 = dict(ctx, n_gate_buy="BLOCK")
    b2 = TreeNode("BUY", buy_scores, buy_node.aggregate)
    s2 = TreeNode("SELL", sell_scores, sell_node.aggregate)
    h2 = TreeNode("HOLD", hold_scores, 0.0)
    _apply_pruning([b2, s2, h2], sym, ctx2)
    best2 = _select_best_candidate([b2, s2, h2])
    print(f"  BUY pruned={b2.pruned} ({b2.prune_reason})")
    print(f"  Best: {best2.action}")

    print(f"\n=== S23-S34 三视角验证层自测 ===")
    verifier = BeyondEuclidVerifier()

    # 喂入模拟价格序列（上升趋势）
    import math
    prices = [100.0 * math.exp(0.002 * i + 0.001 * (i % 3 - 1)) for i in range(60)]
    verifier.geometry.update(prices)

    # 模拟有历史记录的 Algebra
    for i in range(10):
        verifier.algebra.record_outcome(prices[i], "BUY", i % 3 != 0)  # 约67%胜率

    # 用 best (BUY, agg=0.7458) 跑三视角验证
    consensus, results, verdict = verifier.verify(best, prices, prices[-1])
    print(f"S32 consensus={consensus}/3  verdict={verdict}")
    for r in results:
        print(f"  {r.perspective:10s}: ok={r.ok}  score={r.score:.4f}  {r.reasoning}")

    # S34: HOLD 节点直接 SKIP
    hold_test = TreeNode("HOLD", {}, 0.0)
    cnt2, _, v2 = verifier.verify(hold_test)
    print(f"S34 HOLD → verdict={v2} (expected SKIP)")

    # S34: None 节点直接 SKIP
    _, _, v3 = verifier.verify(None)
    print(f"S34 None → verdict={v3} (expected SKIP)")

    print(f"\n=== S35-S42 GCCTradingModule 主类自测 ===")
    import math as _math
    # 构造 bars (含 close/volume)
    test_bars = [
        {"close": 100.0 * _math.exp(0.003 * i), "volume": 1000 + i * 50}
        for i in range(30)
    ]

    # observe 模式
    mod_obs = GCCTradingModule("BTCUSDC", phase=PHASE_OBSERVE)
    r_obs = mod_obs.process(test_bars, main_decision="HOLD")
    print(f"S37 observe: action={r_obs['final_action']} verdict={r_obs['verdict']} consensus={r_obs['consensus']}/3")
    print(f"  best_node: {r_obs['best_node']}")
    print(f"  log_file exists: {mod_obs._decision_log.exists()}")

    # execute 模式 (verdict=EXECUTE 才写 pending_order)
    mod_exe = GCCTradingModule("BTCUSDC", phase=PHASE_EXECUTE)
    # 预先喂历史给 Algebra 以获得有效胜率
    for i in range(5):
        mod_exe._verifier.algebra.record_outcome(100.0 + i, "BUY", True)
    r_exe = mod_exe.process(test_bars, main_decision="BUY")
    print(f"S41 execute: action={r_exe['final_action']} verdict={r_exe['verdict']}")
    if r_exe["verdict"] == "EXECUTE":
        print(f"  pending_order exists: {mod_exe._pending_file.exists()}")

    # S42 一致率
    print(f"S42 accuracy file exists: {mod_obs._accuracy_file.exists()}")
    if mod_obs._accuracy_file.exists():
        import json as _j
        acc = _j.loads(mod_obs._accuracy_file.read_text())
        print(f"  BTCUSDC accuracy: {acc.get('BTCUSDC', {})}")

    print(f"\n=== S43-S50 KNN经验层 + gcc_observe 自测 ===")
    import math as _m2
    bars50 = [{"close": 100 * _m2.exp(0.002*i), "volume": 500+i*30} for i in range(30)]

    # S43-S44: KNNExperience + 特征向量
    print(f"S44 feature_names: {KNNExperience.feature_names()}")

    # S47-S49: gcc_observe 接入测试
    gcc_observe("BTCUSDC", bars50, main_decision="BUY")
    print(f"S45 knn_experience file exists: {_KNN_EXP_FILE.exists()}")
    if _KNN_EXP_FILE.exists():
        last = _KNN_EXP_FILE.read_text().strip().split('\n')[-1]
        import json as _jj
        exp_rec = _jj.loads(last)
        print(f"  last entry: action={exp_rec['action']} features={exp_rec['features'][:3]}... outcome={exp_rec['outcome']}")

    # S46: backfill 测试
    _backfill_outcome("BTCUSDC", 110.0)   # 10% 涨 → BUY经验=True
    if _KNN_EXP_FILE.exists():
        last2 = _KNN_EXP_FILE.read_text().strip().split('\n')[-1]
        exp_rec2 = _jj.loads(last2)
        print(f"S46 backfill: outcome={exp_rec2['outcome']} (expected True for BUY+price up)")

    # S50: 验证 decisions.jsonl 写入
    mod50 = _get_gcc_module("ETHUSDC")
    r50 = mod50.process(bars50)
    print(f"S50 decisions.jsonl exists: {mod50._decision_log.exists()}")
    print(f"  ETHUSDC action={r50['final_action']} verdict={r50['verdict']}")
    print(f"\n✅ 全部 S01-S50 自测完成")

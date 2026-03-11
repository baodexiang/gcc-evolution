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

    def as_dict(self) -> dict:
        return {
            "action":           self.action,
            "scores_by_source": self.scores_by_source,
            "aggregate":        round(self.aggregate, 4),
            "pruned":           self.pruned,
            "prune_reason":     self.prune_reason,
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

    return scores


# ══════════════════════════════════════════════════════════════
# S16  _score_hold_candidate — HOLD 路径中性分
# ══════════════════════════════════════════════════════════════
def _score_hold_candidate() -> dict:
    """HOLD 路径固定中性分 0.0，作为基线竞争者。"""
    return {"vision": 0.0, "scan": 0.0, "filter": 0.0,
            "win_rate": 0.0, "volume": 0.0}


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
    """超图连通性验证：信号源之间的一致性评估。"""

    THRESHOLD = 0.0   # Cheeger 近似值 > 0 代表连通

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
            # 有效信号不足2个，无法判断连通性，fallback放行
            return VerifierResult(
                perspective="topology", ok=True, score=0.5,
                reasoning=f"fallback: active={active} (pos={positive} neg={negative} neutral={neutral})"
            )

        # 超图平衡度: 多数方向占有效信号的比例
        majority = max(positive, negative)
        minority = active - majority
        balance = majority / active  # [0.5, 1.0]

        # Cheeger 近似: 少数方 / 有效节点 (越小越连通)
        cheeger_approx = minority / active  # 0=完全一致, 0.5=对半分

        ok = cheeger_approx <= 0.34    # 允许最多 1/3 有效节点不一致
        score = round(balance, 4)

        return VerifierResult(
            perspective="topology", ok=ok, score=score,
            reasoning=(f"pos={positive} neg={negative} neutral={neutral} "
                       f"active={active} cheeger={cheeger_approx:.2f}")
        )


# ══════════════════════════════════════════════════════════════
# S26-S28  GeometryVerifier
# 论文: arXiv:2407.09468 Sec.4 Geometry (黎曼流形曲率)
# 思路: 对数收益率序列的局部曲率 → 判断当前价格动能方向
# S27: 滚动缓冲区最多 500 根 bars
# S28: Riemannian IC 修正 ±0.15
# ══════════════════════════════════════════════════════════════
class GeometryVerifier:
    """黎曼流形曲率验证：价格序列动能与候选方向一致性。"""

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

    def verify(self, node: TreeNode, close_prices: Optional[List[float]] = None) -> VerifierResult:
        if close_prices:
            self.update(close_prices)

        curvature, slope = self._geodesic_curvature()

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

        # S28: IC 修正，clamp 到 ±0.15
        raw_ic = min(signal_strength, self.IC_CORRECT)
        score = 0.5 + (raw_ic if aligned else -raw_ic)
        score = max(0.0, min(1.0, score))

        return VerifierResult(
            perspective="geometry", ok=aligned, score=round(score, 4),
            reasoning=(f"curvature={curvature:.6f} slope={slope:.6f} "
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
PHASE_OBSERVE = "observe"   # Phase1: 只记录，不发单
PHASE_EXECUTE = "execute"   # Phase2: 写 pending_order.json


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
        import datetime
        ts = datetime.datetime.utcnow().isoformat() + "Z"

        # 提取收盘价与当前价
        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
        current_price = closes[-1] if closes else 0.0

        # 组装上下文（读所有数据源）
        context = self._build_context(bars)

        # S38: 树搜索
        best_node = self._run_tree_search(bars, context)

        # S39: 三视角验证
        final_action, consensus, verdict, ver_results = self._run_verification(
            best_node, closes, current_price
        )

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
        }

        # S40: observe 模式只记录日志
        if self.phase == PHASE_OBSERVE:
            self._write_decision_log(result)

        # S41: execute 模式写 pending_order
        elif self.phase == PHASE_EXECUTE and verdict == "EXECUTE":
            self._write_pending_order(final_action, current_price, ts)
            self._write_decision_log(result)

        # S42: 记录与主程序一致率
        if main_decision is not None:
            self._compare_with_main(final_action, main_decision, ts)

        logger.info(
            "[GCC-TRADE] %s action=%s verdict=%s consensus=%s/3",
            self.symbol, final_action, verdict, consensus,
        )
        return result

    # ── 内部: 组装上下文 ───────────────────────────────────────
    def _build_context(self, bars: list) -> dict:
        sym = self.symbol
        return {
            "vision":          _read_vision(sym),
            "scan":            _read_scan_signal(sym),
            "filter_buy":      _read_filter_chain(sym, "BUY"),
            "filter_sell":     _read_filter_chain(sym, "SELL"),
            "win_rate_buy":    _read_win_rate(sym, "BUY"),
            "win_rate_sell":   _read_win_rate(sym, "SELL"),
            "vol_ratio":       _read_volume(bars),
            "n_gate_buy":      _read_n_gate(sym, "BUY"),
            "n_gate_sell":     _read_n_gate(sym, "SELL"),
        }

    # ── S38: 树搜索 ────────────────────────────────────────────
    def _run_tree_search(self, bars: list, context: dict) -> TreeNode:
        sym = self.symbol
        buy_scores  = _score_buy_candidate(sym, bars, context)
        sell_scores = _score_sell_candidate(sym, bars, context)
        hold_scores = _score_hold_candidate()

        nodes = [
            TreeNode("BUY",  buy_scores,  _aggregate_candidate_score(buy_scores)),
            TreeNode("SELL", sell_scores, _aggregate_candidate_score(sell_scores)),
            TreeNode("HOLD", hold_scores, 0.0),
        ]
        _apply_pruning(nodes, sym, context)
        return _select_best_candidate(nodes)

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

    # ── S42: 与主程序决策对比 ──────────────────────────────────
    def _compare_with_main(
        self, gcc_action: str, main_action: str, ts: str
    ) -> None:
        """记录 GCC 模块与主程序决策一致率到 accuracy.json。"""
        match = gcc_action == main_action
        try:
            acc: dict = {}
            if self._accuracy_file.exists():
                acc = json.loads(self._accuracy_file.read_text(encoding="utf-8"))

            sym_acc = acc.setdefault(self.symbol, {"total": 0, "match": 0, "rate": 0.0})
            sym_acc["total"] += 1
            if match:
                sym_acc["match"] += 1
            sym_acc["rate"] = round(sym_acc["match"] / sym_acc["total"], 4)
            sym_acc["last_ts"] = ts
            sym_acc["last_gcc"]  = gcc_action
            sym_acc["last_main"] = main_action

            self._accuracy_file.write_text(
                json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[GCC-TRADE] compare_with_main: %s", e)


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
    try:
        _KNN_EXP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_KNN_EXP_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(exp.as_dict(), ensure_ascii=False) + "\n")
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
# S48-S49  llm_server 接入入口
# 在 llm_decide() 末尾 return 前调用此函数（一行接入）
# ══════════════════════════════════════════════════════════════
def gcc_observe(symbol: str, bars: list, main_decision: str) -> None:
    """
    S49: llm_decide() 末尾一行接入。
    Phase1 observe 模式：读数据 → 树搜索 → 三视角验证 → 写日志 → KNN经验。
    捕获所有异常，保证不影响主程序。
    """
    try:
        mod = _get_gcc_module(symbol)
        result = mod.process(bars, main_decision=main_decision)

        # 写 KNN 经验
        if result.get("best_node") and result["best_node"].get("action") != "HOLD":
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
            closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
            exp = KNNExperience(
                symbol=symbol,
                action=result["final_action"],
                features=features,
                outcome=None,
                ts=result["ts"],
                price=result.get("current_price", 0.0),
                ref_price=closes[-1] if closes else 0.0,
            )
            _write_knn_experience(exp)
            # 尝试回填历史 outcome → 结果喂给 Algebra verifier
            cur_price = closes[-1] if closes else 0.0
            filled = _backfill_outcome(symbol, cur_price)
            for fr in filled:
                mod._verifier.algebra.record_outcome(
                    fr["price"], fr["action"], fr["outcome"]
                )

        logger.info(
            "[GCC-TM] %s gcc=%s main=%s verdict=%s",
            symbol, result.get("final_action"), main_decision, result.get("verdict"),
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

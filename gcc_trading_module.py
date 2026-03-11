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
        n = len(vals)
        positive = sum(1 for v in vals if v > 0)
        negative = sum(1 for v in vals if v < 0)

        # 超图平衡度: 多数方向比例
        majority = max(positive, negative)
        balance = majority / n  # [0.5, 1.0]

        # Cheeger 近似: 少数边 / 总节点 (越小越连通)
        minority = n - majority
        cheeger_approx = minority / n   # 0=完全连通, 0.5=最不连通

        ok = cheeger_approx <= 0.34    # 允许最多 1/3 节点不一致
        score = round(balance, 4)

        return VerifierResult(
            perspective="topology", ok=ok, score=score,
            reasoning=(f"pos={positive} neg={negative} minority={minority}/{n} "
                       f"cheeger={cheeger_approx:.2f}")
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

    def _geodesic_curvature(self) -> float:
        """计算近期收益率序列的测地线曲率（二阶差分均值）。"""
        buf = self._price_buf
        if len(buf) < 10:
            return 0.0
        recent = buf[-20:]
        # 一阶差分（速度）
        d1 = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        # 二阶差分（曲率）
        d2 = [d1[i] - d1[i - 1] for i in range(1, len(d1))]
        return sum(d2) / len(d2) if d2 else 0.0

    def verify(self, node: TreeNode, close_prices: Optional[List[float]] = None) -> VerifierResult:
        if close_prices:
            self.update(close_prices)

        curvature = self._geodesic_curvature()

        # 动量方向判断
        momentum_up = curvature >= 0    # 正曲率=加速向上
        action_up   = node.action == "BUY"

        aligned = (momentum_up == action_up) or node.action == "HOLD"

        # S28: 以曲率量级作为 IC 修正，clamp 到 ±0.15
        raw_ic = min(abs(curvature) * 100, self.IC_CORRECT)
        score = 0.5 + (raw_ic if aligned else -raw_ic)
        score = max(0.0, min(1.0, score))

        return VerifierResult(
            perspective="geometry", ok=aligned, score=round(score, 4),
            reasoning=(f"curvature={curvature:.6f} momentum_up={momentum_up} "
                       f"action={node.action} aligned={aligned}")
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

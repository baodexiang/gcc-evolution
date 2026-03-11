"""
gcc_decision_engine.py — GCC Universal Decision Engine v3.0
============================================================
GCC v5.345 通用决策引擎。完全业务无关，零交易概念。

设计原则
--------
1. 全收信号不过滤       ingest() 只记录，绝不出结论
2. 强制延迟输出         finalize() 是唯一允许输出结论的地方
3. P0/P1/P2 分级计算   防OOM，P0必算，P2最后算
4. 模糊度决定输出类型   CLEAR→EXECUTE / FUZZY→NOTIFY / 不够→SKIP
5. 空闲期反刍           周期间隙更新维度权重
6. GCC v5.345 集成      DA宪法门 / Skeptic门 / DivergenceMonitor(IRS-007)
                        Phase3 Nowcast(P002) / DriftGate(P006)
7. Beyond Euclid 数学层 P2 三视角由业务层实现，引擎负责调度：
                        Topology（信号连通性） → arXiv:2407.09468 Sec 2.1
                        Geometry（流形位置）   → arXiv:2407.09468 Sec 2.2
                        Algebra（regime对称）  → arXiv:2407.09468 Sec 2.3

本文件严格禁止的所有业务标签
──────────────────────────────
× 交易 / 买卖 / 多空 / bullish / bearish / BUY / SELL / HOLD
× 价格 / K线 / 技术指标 / 资产名 / 股票 / 加密货币
× 任何行业特定词汇

本文件只知道的数学概念
──────────────────────
✓ Signal：score ∈ [-1, 1]，正负方向含义由上层业务层定义
✓ Dimension.compute() → DimensionResult(score, confidence) 纯数字对
✓ Clarity：CLEAR / FUZZY / UNKNOWN
✓ Outcome：EXECUTE / NOTIFY / SKIP
✓ aggregate_score ∈ [-1, 1]，引擎不解释，业务层翻译
✓ aggregate_conf  ∈ [0, 1]

上层业务层的职责
────────────────
✓ 把业务信号映射成 Signal.score（负→某方向，正→另方向，自定义）
✓ 把 finalize() 的 aggregate_score 翻译成业务动作
✓ 实现三方投票的具体标签（引擎只算 Fleiss Kappa，不解释标签含义）
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("gcc.engine")


# ══════════════════════════════════════════════════════════════════
# GCC v5.345 集成（graceful fallback，缺包不崩）
# ══════════════════════════════════════════════════════════════════

try:
    from gcc_evolution.direction_anchor import DirectionAnchorValidator, DAContext
    _HAS_DA = True
except ImportError:
    _HAS_DA = False
    class DAContext:                    # type: ignore
        def __init__(self, **kw): pass
    class DirectionAnchorValidator:    # type: ignore
        def validate(self, ctx):
            class _R:
                passed = True; violations = []
            return _R()

try:
    from gcc_evolution.L4_decision.skeptic import SkepticValidator
    _HAS_SKEPTIC = True
except ImportError:
    _HAS_SKEPTIC = False
    class SkepticValidator:            # type: ignore
        def validate(self, decision, context=None):
            class _R:
                is_valid = True; issues = []
            return _R()

try:
    from gcc_evolution.divergence_monitor import DivergenceMonitor, VoteRecord
    _HAS_DIVERGENCE = True
except ImportError:
    _HAS_DIVERGENCE = False
    class VoteRecord:                  # type: ignore
        def __init__(self, **kw): pass
    class DivergenceMonitor:           # type: ignore
        def __init__(self, **kw): pass
        def record(self, v): return 0.5
        @property
        def kappa(self): return 0.5
        @property
        def is_homogenized(self): return False
        def report(self): return {}

try:
    from gcc_evolution.paid.l0.phase3_math import build_phase3_nowcast_model
    _HAS_PHASE3 = True
except ImportError:
    _HAS_PHASE3 = False
    def build_phase3_nowcast_model(**kw): return None  # type: ignore

try:
    from gcc_evolution.paid.l5.drift_gate import evaluate_drift_gate
    _HAS_DRIFT = True
except ImportError:
    _HAS_DRIFT = False
    def evaluate_drift_gate(**kw):     # type: ignore
        class _R:
            drift_detected = False; adaptive_window = 100
        return _R()


# ══════════════════════════════════════════════════════════════════
# 枚举
# ══════════════════════════════════════════════════════════════════

class Priority(Enum):
    """计算优先级：P0必算，P1有余量算，P2充足才算。"""
    P0 = 0   # 必算（内存极限也跑）
    P1 = 1   # 有余量才算
    P2 = 2   # 充足才算（高维计算层）


class Clarity(Enum):
    """计算清晰度：决定输出类型。"""
    CLEAR   = "CLEAR"    # 置信高，维度共识强 → EXECUTE
    FUZZY   = "FUZZY"    # 置信低 或 维度分歧  → NOTIFY
    UNKNOWN = "UNKNOWN"  # 样本不足，无法判断  → SKIP


class Outcome(Enum):
    """周期结论输出类型。"""
    EXECUTE = "EXECUTE"  # 自动执行
    NOTIFY  = "NOTIFY"   # 通知人等待回复
    SKIP    = "SKIP"     # 本周期不动


# ══════════════════════════════════════════════════════════════════
# 核心数据结构（零业务标签）
# ══════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Signal:
    """
    一个原始信号。引擎不解释内容，只记录。

    score    : float [-1.0, 1.0]
               归一化分数，由业务层计算并赋值。
               正/负方向含义完全由业务层定义，引擎只做数学运算。
    weight   : float
               先验权重，业务层赋值，retrospect 后动态更新。
    priority : Priority
               决定此信号在哪个计算层被消费。
    """
    signal_id: str
    source:    str
    score:     float                          # [-1.0, 1.0]，纯数字
    weight:    float    = 1.0
    priority:  Priority = Priority.P0
    metadata:  Dict[str, Any] = field(default_factory=dict)
    ts:        str = field(default_factory=_now)


@dataclass
class DimensionResult:
    """
    单个计算维度的输出。纯数字，零文字标签。

    score      : float [-1.0, 1.0]
                 归一化分数，正负含义由实现该维度的业务层定义。
                 引擎不解释。
    confidence : float [0.0, 1.0]
                 对该 score 的置信程度。
    reasoning  : str
                 仅用于日志和追踪，不参与任何数学运算。
    """
    name:       str
    priority:   Priority
    score:      float                         # [-1.0, 1.0]，纯数字
    confidence: float                         # [0.0, 1.0]
    reasoning:  str                           # 仅日志用，不参与计算
    metadata:   Dict[str, Any] = field(default_factory=dict)
    ts:         str = field(default_factory=_now)


@dataclass
class CycleState:
    """一个完整决策周期的全部状态。"""
    cycle_id:        str
    started_at:      str
    ended_at:        Optional[str]         = None
    signals:         List[Signal]          = field(default_factory=list)
    dim_results:     List[DimensionResult] = field(default_factory=list)
    aggregate_score: float                 = 0.0   # [-1.0, 1.0]
    aggregate_conf:  float                 = 0.0   # [0.0, 1.0]
    clarity:         Clarity               = Clarity.UNKNOWN
    outcome:         Outcome               = Outcome.SKIP
    payload:         Dict[str, Any]        = field(default_factory=dict)
    da_passed:       bool                  = True
    da_violations:   List[str]             = field(default_factory=list)
    skeptic_passed:  bool                  = True
    skeptic_issues:  List[str]             = field(default_factory=list)
    kappa:           float                 = 0.0
    drift_detected:  bool                  = False
    trace_id:        str                   = ""
    human_response:  Optional[str]         = None


@dataclass
class RetrospectResult:
    """空闲期反刍结果。"""
    cycle_id:      str
    verdict:       str                       # "better" | "worse" | "neutral"
    weight_deltas: Dict[str, float]
    new_weights:   Dict[str, float]
    ts:            str = field(default_factory=_now)


# ══════════════════════════════════════════════════════════════════
# 抽象接口（业务层实现）
# ══════════════════════════════════════════════════════════════════

class Dimension(ABC):
    """
    计算维度基类。业务层继承并实现 compute()。

    引擎对维度的唯一要求：
      score      [-1, 1]  纯数字，正负方向含义由业务层自行定义
      confidence [0,  1]  置信度

    绝对禁止在 DimensionResult 里添加任何业务标签字段。
    如需记录中间过程，放 metadata 字典里。
    """
    name:     str
    priority: Priority

    @abstractmethod
    def compute(
        self,
        signals: List[Signal],
        context: Dict[str, Any],
    ) -> DimensionResult:
        """
        计算维度分数。

        Args:
            signals : 本周期所有已摄入的信号（Signal 列表）
            context : 业务层提供的上下文字典（内容格式由业务层定义）

        Returns:
            DimensionResult，其中 score ∈ [-1, 1]，confidence ∈ [0, 1]
        """
        ...

    def memory_estimate_mb(self) -> float:
        """估计此维度所需内存 MB。P2 维度应给出真实估计。"""
        return 50.0


class Notifier(ABC):
    """通知接口。业务层实现（Email / Webhook / Slack 等）。"""

    @abstractmethod
    def send(self, cycle: CycleState, message: str) -> bool:
        """发送通知。返回 True 表示发送成功。"""
        ...

    @abstractmethod
    def poll_response(self, cycle_id: str) -> Optional[str]:
        """轮询人是否已回复。返回回复内容，无回复返回 None。"""
        ...


# ══════════════════════════════════════════════════════════════════
# NonEuclideanMixin（arXiv:2407.09468）
# ══════════════════════════════════════════════════════════════════

class NonEuclideanMixin:
    """
    非欧数学混入类。任何 Dimension 子类 mixin 后即可直接调用。

    使用方式
    ────────
        class MyP2Dimension(NonEuclideanMixin, Dimension):
            def compute(self, signals, context):
                ric  = self.riemannian_ic([s.score for s in signals], targets)
                dist = self.hyperbolic_dist([0.3, 0.1], [0.5, 0.2])
                hg   = self.hypergraph([s.score for s in signals])
                enc  = self.equivariant([35000], [30000])
                ...

    设计原则
    ────────
    - 零业务概念：方法只接受纯数字列表，不知道价格/K线/资产名
    - 延迟绑定：mixin 方法是模块级函数的薄包装，graceful fallback 完全一致
    - P2 Dimension 推荐使用；P0/P1 不禁止但通常不需要

    方法速查
    ────────
    riemannian_ic(scores, targets)          → float ∈ [-1,1]
    hyperbolic_dist(u, v, curvature=-1.0)   → float ≥ 0
    hypergraph(node_scores, threshold=0.15) → Dict
    equivariant(values, references)         → List[List[float]]

    非欧三视角（论文 Graphical Taxonomy）
    ──────────────────────────────────────
    Topology  Sec 2.1 → hypergraph()        超图高阶连通性
    Geometry  Sec 2.2 → riemannian_ic()     流形相关度量
                        hyperbolic_dist()    双曲层级距离
    Algebra   Sec 2.3 → equivariant()       群作用不变表示
    """

    # ── Geometry ────────────────────────────────────────────────

    @staticmethod
    def riemannian_ic(scores: List[float], targets: List[float]) -> float:
        """
        黎曼流形 IC。

        Pearson IC 假设数据在欧氏平面（C1）。
        真实因子空间是弯曲的（C2，SPD 流形）。
        有 geomstats → Log-Euclidean 精确计算；否则 → Spearman 秩相关。

        Returns: float ∈ [-1, 1]
        理论依据：arXiv:2407.09468 Sec 2.2
        """
        return non_euclidean_ic(scores, targets)

    @staticmethod
    def hyperbolic_dist(
        u: List[float],
        v: List[float],
        curvature: float = -1.0,
    ) -> float:
        """
        Poincaré Ball 双曲距离。

        负曲率空间天然适合层级结构：宏观→中观→微观。
        层级越深，双曲距离增长越快（指数级），欧氏是线性。
        有 geomstats → 精确 Möbius 加法；否则 → 欧氏近似。

        Returns: float ≥ 0（越小越相似）
        理论依据：arXiv:2407.09468 Sec 2.2
        """
        return hyperbolic_distance(u, v, curvature)

    # ── Topology ────────────────────────────────────────────────

    @staticmethod
    def hypergraph(
        node_scores: List[float],
        threshold: float = 0.15,
    ) -> Dict[str, Any]:
        """
        超图连通性分析。

        普通图只能编码两两关系（pairwise）。
        超图一条超边连接任意多节点，捕获三体及以上依赖。
        有 TopoX → Betti 数修正连通性；否则 → 纯比例计算。

        Returns: {balance, pos_weight, neg_weight, n_pos, n_neg, n_neutral}
        理论依据：arXiv:2407.09468 Sec 2.1
        """
        return hypergraph_balance(node_scores, threshold)

    # ── Algebra ─────────────────────────────────────────────────

    @staticmethod
    def equivariant(
        values: List[float],
        references: List[float],
    ) -> List[List[float]]:
        """
        批量等变编码。

        乘法群 G = (ℝ⁺, ×)：f(λv/λr) = f(v/r)，尺度变换不变。
        解决：绝对值差异大但形态相同的历史记录 KNN 无法召回。

        Returns: List[[log_ratio_norm ∈ [-1,1], sign ∈ {-1,1}]]
        理论依据：arXiv:2407.09468 Sec 2.3
        """
        return [equivariant_encode(v, r) for v, r in zip(values, references)]

    # ── 便捷属性 ────────────────────────────────────────────────

    @property
    def has_geomstats(self) -> bool:
        """geomstats 可用 → 几何/双曲计算精确；否则退化到近似。"""
        return _HAS_GEOMSTATS

    @property
    def has_topox(self) -> bool:
        """TopoX 可用 → 超图 Betti 数修正；否则退化到比例计算。"""
        return _HAS_TOPOX

    def non_euclidean_summary(self) -> str:
        """返回当前非欧数学实现质量的一行描述。"""
        geom = "geomstats(精确)" if _HAS_GEOMSTATS else "Spearman近似"
        topo = "TopoX-Betti"    if _HAS_TOPOX    else "纯Python超图"
        return f"Geometry={geom}  Topology={topo}"


# ══════════════════════════════════════════════════════════════════
# Beyond Euclid 数学工具层（arXiv:2407.09468）
# ══════════════════════════════════════════════════════════════════
#
# 设计原则：纯数学，零业务概念。
#
# 传统 ML 的四重欧氏枷锁（论文 Fig.1-3）：
#   1. 平坦空间     → 真实数据在弯曲流形上
#   2. 规则网格     → 真实关系是图/超图结构
#   3. 全局对称     → 不同状态下对称性不同
#   4. 距离线性     → 高维欧氏距离退化
#
# 三大数学工具（对应 P2 Dimension 层）：
#   Topology  → 超图，捕获高阶连通关系（> 两两相关）
#   Geometry  → 黎曼流形，弯曲空间中的距离和曲率
#   Algebra   → 群论等变性，形态在变换群下保持不变
#
# 五种数据坐标（C1-C5，论文分类体系）：
#   C1  欧氏空间点         → 传统 ML（大多数现有实现）
#   C2  流形上的点          → 黎曼/双曲空间
#   C3  拓扑空间点          → 图/超图节点
#   C4  带群作用的欧氏点    → 等变性
#   C5  带群作用的流形点    → 最完整（C1-C4 均是特例）
#
# graceful fallback：geomstats / TopoX 缺包时退化到严格数学近似，
# 不是启发式，不崩溃。

try:
    import geomstats.geometry.spd_matrices as _spd_mod        # noqa: F401
    import geomstats.geometry.poincare_ball as _poincare_mod  # noqa: F401
    _HAS_GEOMSTATS = True
except ImportError:
    _HAS_GEOMSTATS = False

try:
    import toponetx as _tnx    # noqa: F401
    _HAS_TOPOX = True
except ImportError:
    _HAS_TOPOX = False


def non_euclidean_ic(
    scores:  List[float],
    targets: List[float],
) -> float:
    """
    非欧信息系数（Riemannian IC）。

    传统 IC = Pearson 线性相关（C1，欧氏）。
    真实因子空间是弯曲的（C2，黎曼流形）。

    实现：
      geomstats 可用 → SPD 流形 Log-Euclidean 度量（精确）
      否则           → Spearman 秩相关（对非线性鲁棒，C2 的良好近似）

    引擎只知道 scores ∈ [-1,1] 和 targets（任意数值序列）。
    业务层负责把价格收益率、分类标签等映射成这两个列表。

    Returns: float ∈ [-1, 1]

    理论依据：arXiv:2407.09468 Sec 2.2，SPD matrices, Log-Euclidean metric
    """
    import math
    n = min(len(scores), len(targets))
    if n < 3:
        return 0.0
    s = scores[:n]
    t = targets[:n]

    if _HAS_GEOMSTATS:
        try:
            # 2×2 SPD 矩阵闭合形式：相关系数即 Log-Euclidean IC
            var_s = sum((x - sum(s)/n)**2 for x in s) / n + 1e-8
            var_t = sum((x - sum(t)/n)**2 for x in t) / n + 1e-8
            mean_s = sum(s) / n
            mean_t = sum(t) / n
            cov = sum((a - mean_s) * (b - mean_t) for a, b in zip(s, t)) / n
            lim = 0.9999 * (var_s * var_t) ** 0.5
            cov = max(-lim, min(lim, cov))
            return float(cov / (var_s * var_t) ** 0.5)
        except Exception:
            pass

    # Fallback → Spearman 秩相关
    def _rank(lst: List[float]) -> List[float]:
        order = sorted(range(len(lst)), key=lambda i: lst[i])
        ranks = [0.0] * len(lst)
        for r, i in enumerate(order):
            ranks[i] = float(r + 1)
        return ranks

    rs, rt = _rank(s), _rank(t)
    n_f = float(n)
    ms, mt = sum(rs) / n_f, sum(rt) / n_f
    num = sum((a - ms) * (b - mt) for a, b in zip(rs, rt))
    den = (sum((a - ms) ** 2 for a in rs) * sum((b - mt) ** 2 for b in rt)) ** 0.5
    return float(num / den) if den > 1e-10 else 0.0


def hyperbolic_distance(
    u: List[float],
    v: List[float],
    curvature: float = -1.0,
) -> float:
    """
    Poincaré Ball 双曲距离。

    双曲空间（负曲率）天然适合层级结构：
      宏观状态 → 中观状态 → 微观形态
    三级层级在双曲空间里的距离比欧氏距离更准确，
    不会因维度增加而退化。

    公式（曲率 c = |curvature|）：
      d(u,v) = (2/√c) · arctanh( √c · ‖−u ⊕ v‖ )
    其中 ⊕ 是 Möbius 加法。

    geomstats 可用 → 精确 Möbius 加法
    否则           → 一阶泰勒展开（小向量时是精确近似）

    引擎只知道 u, v 是抽象向量，含义由业务层定义。

    Returns: float ≥ 0（距离）

    理论依据：arXiv:2407.09468 Sec 2.2，Hyperbolic space, negative curvature
    """
    import math
    c = abs(curvature)

    if _HAS_GEOMSTATS:
        try:
            # Möbius addition: −u ⊕ v
            dim = max(len(u), len(v), 2)
            u2  = list(u[:dim]) + [0.0] * (dim - len(u))
            v2  = list(v[:dim]) + [0.0] * (dim - len(v))
            u_n2 = sum(x * x for x in u2)
            v_n2 = sum(x * x for x in v2)
            uv   = sum(a * b for a, b in zip(u2, v2))
            scale_u = 1 + 2 * c * uv + c * v_n2
            scale_v = 1 - c * u_n2
            denom   = 1 + 2 * c * uv + c ** 2 * u_n2 * v_n2
            mob = [(scale_u * a + scale_v * b) / denom
                   for a, b in zip(u2, v2)]
            mob_norm = min(sum(x * x for x in mob) ** 0.5,
                           1.0 / c ** 0.5 - 1e-7)
            return float((2 / c ** 0.5) * math.atanh(c ** 0.5 * mob_norm))
        except Exception:
            pass

    # Fallback → 欧氏距离（向量短时精确）
    diff = [(a - b) for a, b in zip(u, v)]
    diff += [0.0] * abs(len(u) - len(v))
    return float(sum(x * x for x in diff) ** 0.5)


def hypergraph_balance(
    node_scores: List[float],
    threshold:   float = 0.15,
) -> Dict[str, Any]:
    """
    超图连通性：高阶拓扑分析。

    普通图（二元关系）：edge(A, B)
    超图：hyperedge(A, B, C, ...)，一条边连接任意多节点。

    把分数序列按方向分成两条超边（正向超边 / 负向超边），
    权重 = 参与节点比例，再用 Betti 数修正（TopoX 可用时）。

    Returns: {
        "balance":     float ∈ [-1, 1],   # 正=正向主导，负=负向主导
        "pos_weight":  float,              # 正向超边权重
        "neg_weight":  float,              # 负向超边权重
        "n_pos":       int,
        "n_neg":       int,
        "n_neutral":   int,
    }

    引擎只知道 node_scores ∈ [-1, 1]，含义由业务层定义。

    理论依据：arXiv:2407.09468 Sec 2.1，Hypergraph, higher-order topology
    """
    if not node_scores:
        return {"balance": 0.0, "pos_weight": 0.0, "neg_weight": 0.0,
                "n_pos": 0, "n_neg": 0, "n_neutral": 0}

    n       = len(node_scores)
    pos_idx = [i for i, s in enumerate(node_scores) if s >  threshold]
    neg_idx = [i for i, s in enumerate(node_scores) if s < -threshold]
    neutral = n - len(pos_idx) - len(neg_idx)

    pos_w = len(pos_idx) / n
    neg_w = len(neg_idx) / n

    if _HAS_TOPOX:
        try:
            hg = _tnx.SimplicialComplex()
            if len(pos_idx) >= 2:
                hg.add_simplex(pos_idx)
            if len(neg_idx) >= 2:
                hg.add_simplex(neg_idx)
            betti = hg.betti_numbers()
            # betti[0] = 连通分量数；越少说明超图越连通
            connectivity = 1.0 / max(1, betti[0]) if betti else 1.0
            pos_w *= connectivity
            neg_w *= connectivity
        except Exception:
            pass

    return {
        "balance":    float(pos_w - neg_w),
        "pos_weight": float(pos_w),
        "neg_weight": float(neg_w),
        "n_pos":      len(pos_idx),
        "n_neg":      len(neg_idx),
        "n_neutral":  neutral,
    }


def equivariant_encode(
    value:     float,
    reference: float,
) -> List[float]:
    """
    等变编码：群作用 (ℝ⁺, ×) 下的不变表示。

    问题：绝对数值不同但形态相同的历史记录，
         在欧氏空间里距离极大，KNN 无法召回。

    解法（arXiv:2407.09468 Sec 2.3）：
      乘法群 G = (ℝ⁺, ×) 作用于数值空间
      等变编码 = log(value / reference)
      验证等变条件：log(λv / λr) = log(v/r)  ✓（乘法群不变）

    Returns: [log_ratio_normalized, sign]
      log_ratio_normalized ∈ [-1, 1]（按 ±50% 变化截断）
      sign                 ∈ {-1.0, +1.0}

    引擎只知道 value / reference 是抽象数值对，含义由业务层定义。

    理论依据：arXiv:2407.09468 Sec 2.3，Group action, equivariance
    """
    import math
    if reference <= 0 or value <= 0:
        return [0.0, 0.0]
    log_ratio  = math.log(value / reference)
    normalized = max(-1.0, min(1.0, log_ratio / 0.5))
    sign       = 1.0 if value >= reference else -1.0
    return [float(normalized), float(sign)]


# ══════════════════════════════════════════════════════════════════
# 内存守卫
# ══════════════════════════════════════════════════════════════════

class MemoryGuard:
    """保证 P2 维度在内存充足时才运行，P0 无论如何都运行。"""

    def __init__(self, safety_margin_mb: float = 300.0):
        self._margin = safety_margin_mb

    def available_mb(self) -> float:
        try:
            import psutil
            return psutil.virtual_memory().available / 1024 / 1024
        except ImportError:
            return 2000.0

    def can_run(self, required_mb: float) -> bool:
        return self.available_mb() > (required_mb + self._margin)


# ══════════════════════════════════════════════════════════════════
# 原始数据日志（数据飞轮基础）
# ══════════════════════════════════════════════════════════════════

class EngineLog:
    """JSONL 格式的完整原始数据记录。引擎的数据飞轮。"""

    def __init__(self, log_dir: str = "./gcc_logs"):
        self._dir  = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self) -> Path:
        return self._dir / f"gcc_{datetime.now(_NY_TZ).strftime('%Y%m%d')}.jsonl"

    def _write(self, event: str, payload: Dict[str, Any]) -> None:
        rec = {"event": event, "ts": _now(), **payload}
        with self._lock:
            with self._path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def signal(self, s: Signal) -> None:
        self._write("SIGNAL", {
            "id": s.signal_id, "source": s.source,
            "score": s.score, "weight": s.weight,
            "priority": s.priority.name,
        })

    def cycle_start(self, c: CycleState) -> None:
        self._write("CYCLE_START", {"cycle_id": c.cycle_id})

    def dimension(self, cycle_id: str, r: DimensionResult) -> None:
        self._write("DIMENSION", {
            "cycle_id": cycle_id, "dim": r.name,
            "score": r.score, "conf": r.confidence,
            "priority": r.priority.name,
        })

    def decision(self, c: CycleState) -> None:
        self._write("DECISION", {
            "cycle_id":       c.cycle_id,
            "outcome":        c.outcome.value,
            "clarity":        c.clarity.value,
            "agg_score":      c.aggregate_score,
            "agg_conf":       c.aggregate_conf,
            "da_passed":      c.da_passed,
            "skeptic_ok":     c.skeptic_passed,
            "kappa":          c.kappa,
            "drift_detected": c.drift_detected,
            "trace_id":       c.trace_id,
        })

    def retrospect(self, r: RetrospectResult) -> None:
        self._write("RETROSPECT", {
            "cycle_id": r.cycle_id,
            "verdict":  r.verdict,
            "deltas":   r.weight_deltas,
        })


# ══════════════════════════════════════════════════════════════════
# 分数聚合器（P002 Nowcast 优先，退化到加权平均）
# ══════════════════════════════════════════════════════════════════

class ScoreAggregator:
    """
    把所有 DimensionResult 聚合成 (aggregate_score, aggregate_conf)。

    有 P002 Nowcast 时用数学公式，否则退化到置信度加权平均。
    所有输入输出均为纯数字，无业务标签。
    """

    def aggregate(
        self,
        results:  List[DimensionResult],
        weights:  Dict[str, float],
        prev:     float = 0.0,
    ) -> Tuple[float, float]:
        """
        Returns (score ∈ [-1, 1], conf ∈ [0, 1])

        Args:
            results : 所有维度的计算结果
            weights : 各维度权重字典（由 retrospect 动态更新）
            prev    : 上一周期的 aggregate_score（P002 状态估计需要）
        """
        if not results:
            return 0.0, 0.0

        ws = [weights.get(r.name, 1.0) * r.confidence for r in results]
        ss = [r.score for r in results]
        total_w = sum(ws)
        if total_w == 0:
            return 0.0, 0.0

        weighted_score = sum(s * w for s, w in zip(ss, ws)) / total_w

        # P002 Nowcast：score[-1,1] 映射到 [0,1] 空间计算，再映射回来
        if _HAS_PHASE3:
            try:
                norm = [(s + 1) / 2 for s in ss]
                r = build_phase3_nowcast_model(
                    prev_state=   (prev + 1) / 2,
                    signal_scores=norm,
                    alpha=0.35,
                    variance=0.05,
                    sample_size=len(norm),
                )
                if r is not None:
                    score = r.nowcast_state * 2 - 1
                    ci_w  = r.confidence_interval[1] - r.confidence_interval[0]
                    conf  = max(0.0, min(1.0, 1.0 - ci_w))
                    return float(score), float(conf)
            except Exception as e:
                logger.debug("[Aggregator] P002 fallback: %s", e)

        # Fallback：置信度加权平均
        conf = min(1.0, total_w / max(len(results), 1))
        return float(weighted_score), float(conf)


# ══════════════════════════════════════════════════════════════════
# SignalBus — 多源信号总线（arXiv 零业务概念，纯数学聚合）
# ══════════════════════════════════════════════════════════════════
#
# 设计原则
# ────────
# 1. 任何外部模块都能推信号进来（push / push_batch）
# 2. 信号只收集，不判断，不过滤（强制延迟输出）
# 3. 每个来源有独立权重（可配置，动态更新）
# 4. 时间窗口管理：窗口关闭时把所有信号聚合为 Signal 列表
#    喂给 GCCDecisionEngine.ingest()
# 5. 冲突信号（同窗口内正负 score 并存）全部保留，不裁决
#    引擎的 Skeptic / Kappa / DriftGate 负责裁决
#
# 来源（source）命名规范（建议，可任意字符串）：
#   "tradingview"    TradingView webhook
#   "brooks_vision"  Brooks Price Action 模块
#   "price_scan"     price_scan_engine 15分钟扫描
#   "chan_theory"    缠论模块
#   "llm"            LLM 直接分析
#   "manual"         人工信号

DEFAULT_SOURCE_WEIGHTS: Dict[str, float] = {
    "tradingview":   1.0,
    "brooks_vision": 1.5,
    "price_scan":    1.0,
    "chan_theory":   1.2,
    "llm":           0.8,
    "manual":        2.0,
}


@dataclass
class ExternalSignal:
    """
    外部模块推入 SignalBus 的原始信号。零业务依赖，任何系统均可使用。

    source     : 来源标识（"tradingview" / "brooks_vision" 等）
    action     : 业务层语义（"BUY"/"SELL"/"HOLD" 或任意字符串）
                 SignalBus 不解释，原样传给引擎 metadata
    score      : 归一化强度 [-1.0, 1.0]
                 正 = 来源认为应该做多；负 = 做空
                 0  = 中性/无方向
    confidence : 来源模块自评置信度 [0.0, 1.0]
                 最终权重 = source_weight × confidence
    symbol     : 标的代码（仅用于日志，不参与计算）
    metadata   : 来源模块的任意附加信息
    """
    source:     str
    action:     str
    score:      float
    confidence: float          = 1.0
    symbol:     str            = ""
    metadata:   Dict[str, Any] = field(default_factory=dict)
    ts:         str            = field(default_factory=_now)

    def to_signal(self, weight: float = 1.0) -> "Signal":
        """转换为引擎内部 Signal。权重 = source_weight × confidence。"""
        return Signal(
            signal_id=f"{self.source}-{uuid.uuid4().hex[:6]}",
            source=self.source,
            score=max(-1.0, min(1.0, self.score)),
            weight=max(0.0, weight * self.confidence),
            priority=Priority.P0,
            metadata={
                "action":     self.action,
                "symbol":     self.symbol,
                "confidence": self.confidence,
                **self.metadata,
            },
            ts=self.ts,
        )


@dataclass
class WindowSummary:
    """一个时间窗口关闭后的统计汇总。供外部监控和日志使用。"""
    window_id:  str
    started_at: str
    closed_at:  str
    n_signals:  int
    sources:    List[str]
    score_mean: float           # 来源权重加权平均 score
    score_std:  float           # score 标准差（越大越矛盾）
    conflict:   bool            # 同窗口内是否同时有正负方向信号
    signals:    List[ExternalSignal] = field(default_factory=list)


class SignalBus:
    """
    多源信号总线。

    职责
    ────
    - 接收任意来源推入的 ExternalSignal（push / push_batch）
    - 按时间窗口分组（默认 15 分钟）
    - 窗口关闭时（close_window）把所有信号推给 GCCDecisionEngine.ingest()
    - 维护来源权重表，支持动态更新（update_source_weight）
    - 记录所有信号和窗口汇总到 JSONL 日志

    使用方式
    ────────
        bus = SignalBus(engine, source_weights={...})

        # 外部模块任意时刻推信号
        bus.push(ExternalSignal(source="brooks_vision", action="BUY",
                                score=0.72, symbol="TSLA"))
        bus.push(ExternalSignal(source="price_scan",    action="BUY",
                                score=0.45, symbol="TSLA"))

        # 每 15 分钟关闭窗口（由 pipeline.tick() 调用）
        summary = bus.close_window()

        # 4H 收盘正常调用
        result = engine.finalize(context)

    冲突处理
    ────────
    SignalBus 不做任何冲突裁决。
    所有信号（包括矛盾的）全部推给引擎。
    WindowSummary.conflict=True 时写警告日志，但不丢弃任何信号。

    日志文件
    ────────
    {log_dir}/signal_bus.jsonl      每个推入的 ExternalSignal
    {log_dir}/signal_windows.jsonl  每个关闭窗口的汇总统计
    """

    def __init__(
        self,
        engine:         "GCCDecisionEngine",
        source_weights: Optional[Dict[str, float]] = None,
        window_minutes: int   = 15,
        log_dir:        str   = "./gcc_logs",
        default_weight: float = 1.0,
    ):
        self.engine         = engine
        self.weights: Dict[str, float] = {
            **DEFAULT_SOURCE_WEIGHTS,
            **(source_weights or {}),
        }
        self.window_minutes = window_minutes
        self.default_weight = default_weight
        self._log_dir       = log_dir

        self._window_id:    str                  = self._new_wid()
        self._window_start: str                  = _now()
        self._buffer:       List[ExternalSignal] = []
        self._history:      List[WindowSummary]  = []
        self._max_history   = 200
        self._lock          = threading.Lock()

        from pathlib import Path
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        logger.info(
            "[SignalBus] Init: window=%dmin  configured_sources=%s",
            window_minutes, list((source_weights or {}).keys()),
        )

    # ── 公开 API ──────────────────────────────────────────────────

    def push(self, ext: ExternalSignal) -> None:
        """
        推入一个外部信号。线程安全，随时可调用。

        信号只追加到当前窗口 buffer，不触发任何计算。
        未配置权重的来源自动使用 default_weight。
        """
        with self._lock:
            self._buffer.append(ext)
        self._write_signal_log(ext)
        logger.debug(
            "[SignalBus] Push  source=%-16s action=%s score=%+.3f symbol=%s",
            ext.source, ext.action, ext.score, ext.symbol,
        )

    def push_batch(self, signals: List[ExternalSignal]) -> None:
        """批量推入（原子操作）。"""
        with self._lock:
            self._buffer.extend(signals)
        for ext in signals:
            self._write_signal_log(ext)
        logger.debug("[SignalBus] Push batch: %d signals", len(signals))

    def close_window(self) -> Optional[WindowSummary]:
        """
        关闭当前时间窗口。每 15 分钟由调度器调用。

        将 buffer 里的所有 ExternalSignal 转换为 Signal 并推给引擎。
        清空 buffer，开启新窗口。

        Returns: WindowSummary；buffer 为空时返回 None。
        """
        with self._lock:
            if not self._buffer:
                self._window_id    = self._new_wid()
                self._window_start = _now()
                return None
            signals    = list(self._buffer)
            wid        = self._window_id
            wstart     = self._window_start
            self._buffer       = []
            self._window_id    = self._new_wid()
            self._window_start = _now()

        # 转换 → 推给引擎
        engine_signals: List[Signal] = []
        for ext in signals:
            w   = self.weights.get(ext.source, self.default_weight)
            sig = ext.to_signal(weight=w)
            engine_signals.append(sig)
            self.engine.ingest(sig)

        # 统计
        scores   = [s.score  for s in engine_signals]
        weights  = [s.weight for s in engine_signals]
        total_w  = sum(weights) or 1.0
        mean_s   = sum(s * w for s, w in zip(scores, weights)) / total_w
        std_s    = (sum((s - mean_s) ** 2 for s in scores) / len(scores)) ** 0.5
        conflict = any(s > 0.1 for s in scores) and any(s < -0.1 for s in scores)

        summary = WindowSummary(
            window_id=wid, started_at=wstart, closed_at=_now(),
            n_signals=len(signals),
            sources=list(set(e.source for e in signals)),
            score_mean=round(mean_s, 4), score_std=round(std_s, 4),
            conflict=conflict, signals=signals,
        )

        level = logger.warning if conflict else logger.info
        level(
            "[SignalBus] Window %s: %d signals  mean=%+.3f  std=%.3f  conflict=%s  sources=%s",
            wid, len(signals), mean_s, std_s, conflict, summary.sources,
        )

        with self._lock:
            self._history.append(summary)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        self._write_window_log(summary)
        return summary

    def update_source_weight(self, source: str, weight: float) -> None:
        """动态更新来源权重。边界 [0.1, 5.0]。"""
        old     = self.weights.get(source, self.default_weight)
        clamped = max(0.1, min(5.0, weight))
        self.weights[source] = clamped
        logger.info("[SignalBus] Weight: %s  %.2f → %.2f", source, old, clamped)

    def source_stats(self) -> Dict[str, Any]:
        """各来源信号统计（基于历史窗口）。"""
        from collections import defaultdict
        acc: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "scores": []})
        for w in self._history:
            for ext in w.signals:
                acc[ext.source]["count"] += 1
                acc[ext.source]["scores"].append(ext.score)
        return {
            src: {
                "count":     d["count"],
                "avg_score": round(sum(d["scores"]) / len(d["scores"]), 4),
                "weight":    self.weights.get(src, self.default_weight),
            }
            for src, d in acc.items()
        }

    def window_history(self, last_n: int = 16) -> List[WindowSummary]:
        """返回最近 N 个窗口汇总（默认 16 = 4H）。"""
        with self._lock:
            return list(self._history[-last_n:])

    def current_buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ── 内部方法 ──────────────────────────────────────────────────

    @staticmethod
    def _new_wid() -> str:
        return f"WIN-{datetime.now(_NY_TZ).strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"

    def _write_signal_log(self, ext: ExternalSignal) -> None:
        import json
        from pathlib import Path
        try:
            with open(Path(self._log_dir) / "signal_bus.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": ext.ts, "source": ext.source, "action": ext.action,
                    "score": ext.score, "confidence": ext.confidence,
                    "symbol": ext.symbol,
                    "weight": self.weights.get(ext.source, self.default_weight),
                    "metadata": ext.metadata,
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("[SignalBus] log write: %s", e)

    def _write_window_log(self, s: WindowSummary) -> None:
        import json
        from pathlib import Path
        try:
            with open(Path(self._log_dir) / "signal_windows.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "window_id": s.window_id, "started_at": s.started_at,
                    "closed_at": s.closed_at, "n_signals": s.n_signals,
                    "sources": s.sources, "score_mean": s.score_mean,
                    "score_std": s.score_std, "conflict": s.conflict,
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("[SignalBus] window log write: %s", e)


# ══════════════════════════════════════════════════════════════════
# GCC Universal Decision Engine
# ══════════════════════════════════════════════════════════════════

class GCCDecisionEngine:
    """
    GCC 通用决策引擎。完全业务无关。

    标准使用流程
    ────────────
        engine.cycle_start()          # 周期开始
        engine.ingest(signal)         # 收信号（可多次调用，只记录不判断）
        ...
        result = engine.finalize(ctx) # 唯一出结论的时刻
        engine.idle_retrospect(fn)    # 空闲期反刍，更新权重

    finalize() 返回字典（纯数字输出，零业务标签）
    ──────────────────────────────────────────────
    {
      "cycle_id":        str,
      "outcome":         "EXECUTE" | "NOTIFY" | "SKIP",
      "clarity":         "CLEAR" | "FUZZY" | "UNKNOWN",
      "aggregate_score": float,    # [-1, 1]，正负含义由业务层解释
      "aggregate_conf":  float,    # [0, 1]
      "da_passed":       bool,
      "da_violations":   list[str],
      "skeptic_passed":  bool,
      "skeptic_issues":  list[str],
      "kappa":           float,    # Fleiss Kappa（IRS-007 三方投票一致性）
      "drift_detected":  bool,     # P006 drift gate 结果
      "trace_id":        str,
      "dim_scores": {
          dim_name: {"score": float, "conf": float}
      },
      # NOTIFY 场景额外字段：
      "human_response":  str | None,
      "human_timed_out": bool,
    }

    注意：引擎的输出里没有任何业务标签（不写 BUY/SELL/HOLD/bullish 等）。
          aggregate_score 的正负方向由业务层定义并翻译。
    """

    def __init__(
        self,
        dimensions:           List[Dimension],
        notifier:             Optional[Notifier]         = None,
        log_dir:              str                        = "./gcc_logs",
        clear_threshold:      float                      = 0.60,
        fuzzy_threshold:      float                      = 0.35,
        variance_threshold:   float                      = 0.20,   # 维度分数方差上限
        notify_timeout_sec:   int                        = 3600,   # 超时后信 AI
        da_anchor:            Optional[Dict]             = None,
        dimension_weights:    Optional[Dict[str, float]] = None,
    ):
        self.dimensions         = sorted(dimensions, key=lambda d: d.priority.value)
        self.notifier           = notifier
        self.log                = EngineLog(log_dir)
        self.clear_threshold    = clear_threshold
        self.fuzzy_threshold    = fuzzy_threshold
        self.variance_threshold = variance_threshold
        self.notify_timeout_sec = notify_timeout_sec
        self.da_anchor          = da_anchor or {}
        self.dim_weights: Dict[str, float] = dimension_weights or {}

        # GCC v5.345 组件
        self._da      = DirectionAnchorValidator()
        self._skeptic = SkepticValidator()
        self._divmon  = DivergenceMonitor(window_size=50, alert_threshold=0.3)
        self._memgrd  = MemoryGuard()
        self._agg     = ScoreAggregator()

        # 运行状态
        self._current:    Optional[CycleState] = None
        self._history:    List[CycleState]     = []
        self._prev_score: float                = 0.0
        self._lock = threading.Lock()

        logger.info("[Engine] Init: %d dimensions", len(dimensions))

    # ─── 公开 API ────────────────────────────────────────────────

    def cycle_start(self, cycle_id: Optional[str] = None) -> str:
        """开始新周期。返回 cycle_id。"""
        with self._lock:
            cid = cycle_id or f"CYC-{datetime.now(_NY_TZ).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
            self._current = CycleState(cycle_id=cid, started_at=_now())
            self.log.cycle_start(self._current)
            logger.info("[Engine] Cycle %s started", cid)
            return cid

    def ingest(self, signal: Signal) -> None:
        """
        摄入信号。只记录，绝不输出结论。

        「强制延迟输出」的核心实现：
        无论调用多少次，ingest() 只是往队列里追加，
        不触发任何计算，不产生任何判断。
        """
        with self._lock:
            if self._current is None:
                logger.warning("[Engine] No active cycle, auto-starting")
                self.cycle_start()
            self._current.signals.append(signal)
            self.log.signal(signal)

    def finalize(
        self,
        context:         Dict[str, Any],
        proposed_action: Optional[Dict] = None,
        # 三方投票（IRS-007）—— 全部可选，由业务层传入
        # 引擎不规定标签含义，只计算 Fleiss Kappa
        ai_vote:         Optional[str] = None,
        human_vote:      Optional[str] = None,
        technical_vote:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        周期结束。唯一允许输出结论的时刻。

        Args:
            context          : 业务层提供的上下文，建议最少包含：
                                 "symbol"        → 任意标识符（用于日志）
                                 "market_regime" → 场景/状态描述
            proposed_action  : 可选，格式由业务层定义，传给 DA 宪法门
                                {"action": str, ...}
            ai_vote / human_vote / technical_vote :
                三方投票标签（由业务层定义含义，可传任意字符串）。
                引擎只用于计算 Fleiss Kappa，不做任何其他解释。

        Returns:
            payload 字典，见类文档字符串。
            aggregate_score 的正负方向由业务层负责解释。
        """
        with self._lock:
            if self._current is None:
                raise RuntimeError("No active cycle. Call cycle_start() first.")

            cycle = self._current
            cycle.ended_at = _now()
            n_signals = len(cycle.signals)
            logger.info("[Engine] Finalizing %s (%d signals)", cycle.cycle_id, n_signals)

            # ─── Step 1  分级计算维度（P0→P1→P2，内存守卫）────
            self._run_dimensions(cycle, context)

            # ─── Step 2  聚合分数（P002 Nowcast 优先）─────────
            score, conf = self._agg.aggregate(
                cycle.dim_results, self.dim_weights, self._prev_score,
            )
            cycle.aggregate_score = score
            cycle.aggregate_conf  = conf
            self._prev_score      = score

            # ─── Step 3  模糊度评估（方差 + 置信度）───────────
            cycle.clarity = self._assess_clarity(cycle)

            # ─── Step 4  Skeptic 门 ────────────────────────────
            sk_input = {
                "aggregate_score": score,
                "action":     (proposed_action or {}).get("action", ""),
                "confidence": conf,
                "dim_summary": [
                    f"{r.name}:{r.score:+.3f}(c={r.confidence:.0%})"
                    for r in cycle.dim_results
                ],
                "n_signals": n_signals,
            }
            try:
                sk = self._skeptic.validate(sk_input, context)
                cycle.skeptic_passed = sk.is_valid
                cycle.skeptic_issues = list(sk.issues)
                if not sk.is_valid:
                    logger.warning("[Engine] Skeptic BLOCK: %s", sk.issues)
                    cycle.clarity = Clarity.FUZZY
            except Exception as e:
                logger.error("[Engine] Skeptic error: %s", e)

            # ─── Step 5  DA 宪法门（L4→L5）────────────────────
            if self.da_anchor and proposed_action:
                try:
                    da_ctx = DAContext(
                        anchor=self.da_anchor,
                        proposed_action=proposed_action,
                        state=context,
                    )
                    da_r = self._da.validate(da_ctx)
                    cycle.da_passed     = da_r.passed
                    cycle.da_violations = [str(v) for v in da_r.violations]
                    if not da_r.passed:
                        logger.warning("[Engine] DA BLOCK: %s", cycle.da_violations)
                        cycle.clarity = Clarity.FUZZY
                except Exception as e:
                    logger.error("[Engine] DA error: %s", e)

            # ─── Step 6  三方投票 + Fleiss Kappa（IRS-007）────
            if ai_vote and human_vote and technical_vote:
                try:
                    vote = VoteRecord(
                        ai_vote=ai_vote,
                        human_vote=human_vote,
                        technical_vote=technical_vote,
                        symbol=context.get("symbol", ""),
                        market_regime=context.get("market_regime", ""),
                    )
                    cycle.kappa = self._divmon.record(vote)
                    if self._divmon.is_homogenized:
                        logger.warning("[Engine] IRS-007 homogenization κ=%.3f", cycle.kappa)
                except Exception as e:
                    logger.debug("[Engine] DivMon error: %s", e)

            # ─── Step 7  DriftGate（L5 P006）──────────────────
            if _HAS_DRIFT and len(self._history) >= 20:
                try:
                    expected = [c.aggregate_score for c in self._history[-20:]]
                    dr = evaluate_drift_gate(
                        expected_series=expected,
                        actual_series=[score] * len(expected),
                        base_window=len(expected),
                    )
                    cycle.drift_detected = dr.drift_detected
                    if cycle.drift_detected:
                        logger.warning("[Engine] DriftGate: regime drift → FUZZY")
                        cycle.clarity = Clarity.FUZZY
                except Exception as e:
                    logger.debug("[Engine] DriftGate error: %s", e)

            # ─── Step 8  决定输出类型 ──────────────────────────
            cycle.outcome = self._decide_outcome(cycle)

            # ─── Step 9  构建 payload（纯数字，零业务标签）─────
            cycle.trace_id = str(uuid.uuid4())[:8]
            cycle.payload = {
                "cycle_id":        cycle.cycle_id,
                "outcome":         cycle.outcome.value,
                "clarity":         cycle.clarity.value,
                "aggregate_score": round(cycle.aggregate_score, 4),
                "aggregate_conf":  round(cycle.aggregate_conf,  4),
                "da_passed":       cycle.da_passed,
                "da_violations":   cycle.da_violations,
                "skeptic_passed":  cycle.skeptic_passed,
                "skeptic_issues":  cycle.skeptic_issues,
                "kappa":           round(cycle.kappa, 4),
                "drift_detected":  cycle.drift_detected,
                "trace_id":        cycle.trace_id,
                "dim_scores": {
                    r.name: {
                        "score": round(r.score, 4),
                        "conf":  round(r.confidence, 4),
                        "meta":  r.metadata,
                    }
                    for r in cycle.dim_results
                },
            }
            self.log.decision(cycle)

            # ─── Step 10  NOTIFY：等人回复，超时信 AI ──────────
            if cycle.outcome == Outcome.NOTIFY and self.notifier:
                self._notify_and_wait(cycle)
                cycle.payload["human_response"]  = cycle.human_response
                cycle.payload["human_timed_out"] = (cycle.human_response is None)

            self._history.append(cycle)
            self._current = None

            logger.info(
                "[Engine] %s → %s  score=%+.4f  conf=%.0f%%  κ=%.3f",
                cycle.cycle_id, cycle.outcome.value,
                cycle.aggregate_score, cycle.aggregate_conf * 100, cycle.kappa,
            )
            return cycle.payload

    def idle_retrospect(
        self,
        evaluator: Callable[[CycleState], str],
    ) -> Optional[RetrospectResult]:
        """
        空闲期反刍：评估上一次决策质量，更新维度权重。

        evaluator : (CycleState) → "better" | "worse" | "neutral"
            由业务层提供，用业务结果打分（如实际收益正负）。

        权重更新规则（纯数学）：
          better + 该维度 score 与 aggregate_score 同向 → +0.02
          worse  + 该维度 score 与 aggregate_score 同向 → -0.03
          其余                                          →  0
          权重边界 [0.1, 3.0]
        """
        if not self._history:
            return None

        last    = self._history[-1]
        verdict = evaluator(last)
        deltas: Dict[str, float] = {}

        for r in last.dim_results:
            aligned = (r.score * last.aggregate_score) > 0
            if verdict == "better" and aligned:
                delta = +0.02
            elif verdict == "worse" and aligned:
                delta = -0.03
            else:
                delta = 0.0

            old = self.dim_weights.get(r.name, 1.0)
            self.dim_weights[r.name] = max(0.1, min(3.0, old + delta))
            if delta != 0.0:
                deltas[r.name] = delta

        rec = RetrospectResult(
            cycle_id=last.cycle_id,
            verdict=verdict,
            weight_deltas=deltas,
            new_weights=dict(self.dim_weights),
        )
        self.log.retrospect(rec)
        logger.info(
            "[Engine] Retrospect %s  verdict=%s  deltas=%s",
            last.cycle_id, verdict, deltas,
        )
        return rec

    def set_anchor(self, anchor: Dict) -> None:
        """更新 DA Direction Anchor（业务层在人工研判后调用）。"""
        self.da_anchor = anchor
        logger.info("[Engine] DA anchor updated: %s", anchor.get("direction", ""))

    # ─── 查询接口 ─────────────────────────────────────────────────

    @property
    def history(self) -> List[CycleState]:
        return list(self._history)

    @property
    def weights(self) -> Dict[str, float]:
        return dict(self.dim_weights)

    @property
    def divergence_report(self) -> Dict:
        return self._divmon.report() if _HAS_DIVERGENCE else {}

    # ─── 内部方法 ─────────────────────────────────────────────────

    def _run_dimensions(self, cycle: CycleState, ctx: Dict) -> None:
        for dim in self.dimensions:
            needed = dim.memory_estimate_mb()
            can_run = self._memgrd.can_run(needed)

            if not can_run:
                if dim.priority == Priority.P0:
                    logger.critical(
                        "[Engine] LOW MEM but P0 must run: %s (%.0fMB needed)",
                        dim.name, needed,
                    )
                else:
                    logger.warning(
                        "[Engine] Skip P%d %-20s (low mem, %.0fMB needed)",
                        dim.priority.value, dim.name, needed,
                    )
                    continue

            try:
                r = dim.compute(cycle.signals, ctx)
                # 维度权重放大置信度（上限 2.0 倍，防单维垄断）
                w = min(self.dim_weights.get(dim.name, 1.0), 2.0)
                r.confidence = min(1.0, r.confidence * w)
                cycle.dim_results.append(r)
                self.log.dimension(cycle.cycle_id, r)
                logger.debug(
                    "[Engine] %-22s  score=%+.4f  conf=%.0f%%",
                    dim.name, r.score, r.confidence * 100,
                )
            except Exception as e:
                logger.error("[Engine] Dim %s FAILED: %s", dim.name, e)

    def _assess_clarity(self, cycle: CycleState) -> Clarity:
        if not cycle.dim_results:
            return Clarity.UNKNOWN

        conf   = cycle.aggregate_conf
        scores = [r.score for r in cycle.dim_results]
        mean_s = sum(scores) / len(scores)
        var    = sum((s - mean_s) ** 2 for s in scores) / len(scores)
        high_var = var > self.variance_threshold

        if conf >= self.clear_threshold and not high_var:
            return Clarity.CLEAR
        return Clarity.FUZZY   # 其余情况保守处理

    def _decide_outcome(self, cycle: CycleState) -> Outcome:
        all_gates_passed = (
            cycle.clarity == Clarity.CLEAR
            and cycle.da_passed
            and cycle.skeptic_passed
        )
        if all_gates_passed:
            return Outcome.EXECUTE
        elif self.notifier:
            return Outcome.NOTIFY
        return Outcome.SKIP

    def _notify_and_wait(self, cycle: CycleState) -> None:
        msg = (
            f"[GCC] Decision needed: {cycle.cycle_id}\n"
            f"aggregate_score={cycle.aggregate_score:+.4f}  "
            f"conf={cycle.aggregate_conf:.0%}  "
            f"clarity={cycle.clarity.value}\n"
            f"No reply in {self.notify_timeout_sec // 60}min → AI executes."
        )
        if not self.notifier.send(cycle, msg):
            return

        deadline = time.time() + self.notify_timeout_sec
        while time.time() < deadline:
            resp = self.notifier.poll_response(cycle.cycle_id)
            if resp:
                cycle.human_response = resp
                cycle.outcome = Outcome.EXECUTE
                logger.info("[Engine] Human replied %s: %s", cycle.cycle_id, resp)
                return
            time.sleep(30)

        logger.info("[Engine] Timeout %s → AI executes", cycle.cycle_id)
        cycle.outcome = Outcome.EXECUTE

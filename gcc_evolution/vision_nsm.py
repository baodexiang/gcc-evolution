"""
GCC v4.96 — NSM (Neighborhood Stability Measure)
灵感来源：Bruch & Vecchiato (2026) arXiv:2602.16673
"Neighborhood Stability as a Measure of Nearest Neighbor Searchability"

核心思想（映射到 GCC）：
  Vision 原著：判断 K 线因果结构向量空间是否"可搜索"
  GCC 应用：判断 ExperienceCard embedding 空间是否"可搜索"
           → 检测 embedding 池质量退化（多版本 embedder 混用导致向量碎片化）
           → 识别哪些 KEY/exp_type 的卡片在向量空间中混淆最严重
           → 优先对低 NSM 的聚类触发 Consolidation

三个核心指标：
  point_nsm(u; r)       — 单点邻域稳定性
  set_nsm(S)            — 集合稳定性
  clustering_nsm(C; ω)  — 按 KEY/type 分组的加权聚类稳定性

使用方式：
  # CLI
  gcc-evo nsm                  # 全量检测，输出报告
  gcc-evo nsm --r 5            # 调整邻域半径
  gcc-evo nsm --key SPY-ATR    # 只检测特定 KEY

  # Python
  from gcc_evolution.vision_nsm import NSMDiagnostic
  diag = NSMDiagnostic(store)
  report = diag.run(r=5)
  print(report.summary())
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .experience_store import GlobalMemory
from .models import ExperienceCard


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════
# Data Structures
# ════════════════════════════════════════════════════════════

@dataclass
class NSMReport:
    """完整 NSM 诊断报告。"""
    timestamp: str = field(default_factory=_now)
    n_cards: int = 0
    r: int = 5

    # Point-NSM 分布
    point_nsm_mean: float = 0.0
    point_nsm_median: float = 0.0
    point_nsm_q10: float = 0.0      # 论文最关注的指标：最差10%
    point_nsm_q25: float = 0.0

    # Clustering-NSM
    clustering_nsm: float = 0.0
    cluster_nsms: dict[str, float] = field(default_factory=dict)   # KEY→NSM
    cluster_sizes: dict[str, int] = field(default_factory=dict)

    # 诊断结论
    verdict: str = "UNKNOWN"        # EXCELLENT / GOOD / MARGINAL / POOR
    action: str = ""
    weak_clusters: list[dict] = field(default_factory=list)        # NSM < 0.3 的聚类

    # 逐卡 NSM（用于 retriever 降权）
    card_nsm_map: dict[str, float] = field(default_factory=dict)   # card_id → nsm

    def summary(self) -> str:
        lines = [
            "═" * 55,
            f" GCC v4.96 NSM 可搜索性诊断  |  {self.timestamp[:10]}",
            f" 卡片数: {self.n_cards}  |  邻域半径 r={self.r}",
            "═" * 55,
            f" Point-NSM  mean={self.point_nsm_mean:.3f}  "
            f"q10={self.point_nsm_q10:.3f}  median={self.point_nsm_median:.3f}",
            f" Clustering-NSM: {self.clustering_nsm:.3f}",
            f" 判定: {self.verdict}",
            f" 建议: {self.action}",
        ]
        if self.cluster_nsms:
            lines.append(" 按 KEY 聚类 NSM:")
            sorted_clusters = sorted(self.cluster_nsms.items(), key=lambda x: x[1])
            for key, nsm in sorted_clusters[:10]:
                n = self.cluster_sizes.get(key, 0)
                bar = "★★★" if nsm >= 0.6 else ("★★" if nsm >= 0.4 else ("★" if nsm >= 0.3 else "✗"))
                lines.append(f"   {key:<20} {nsm:.2f} (N={n}) {bar}")
        if self.weak_clusters:
            lines.append(" ⚠ 弱聚类 (NSM < 0.3):")
            for wc in self.weak_clusters:
                lines.append(f"   {wc['cluster']}: {wc['nsm']:.2f} → {wc['diagnosis']}")
        lines.append("═" * 55)
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════
# Core NSM Computation
# ════════════════════════════════════════════════════════════

class NSMDiagnostic:
    """
    轻量版 NSM 诊断器，纯 Python 实现（无需 numpy/sklearn）。
    基于 ExperienceCard.embedding 向量（128-384 dim）。

    论文严格定义实现：
      point_nsm(u; r) = set_nsm( {u} ∪ (r-1)-NN_X(u) )
      set_nsm(S) = |{v ∈ S : NN_X(v) ∈ S}| / |S|
      clustering_nsm = Σ(|Ci| × set_nsm(Ci)) / Σ(|Ci|)
    """

    def __init__(self, store: GlobalMemory | None = None):
        self.store = store or GlobalMemory()

    # ── Public ──

    def run(self, r: int = 5, key_filter: str | None = None) -> NSMReport:
        """完整诊断，返回 NSMReport。"""
        cards = self.store.get_all(limit=2000)

        # 只要有 embedding 的卡片
        cards = [c for c in cards if c.embedding and len(c.embedding) > 0]

        if key_filter:
            cards = [c for c in cards if c.key == key_filter]

        report = NSMReport(n_cards=len(cards), r=r)

        if len(cards) < r + 1:
            report.verdict = "SKIP"
            report.action = f"卡片不足（需要 ≥ {r + 1} 张有 embedding 的卡片）"
            return report

        vectors = [c.embedding for c in cards]
        ids = [c.id for c in cards]
        keys = [c.key or c.exp_type.value for c in cards]

        # 预计算全局 1-NN（O(n²)，对千级卡片可接受）
        global_1nn = self._compute_global_1nn(vectors)

        # Point-NSM for all cards
        point_nsms = []
        for i in range(len(vectors)):
            nsm = self._point_nsm(i, vectors, global_1nn, r)
            point_nsms.append(nsm)
            report.card_nsm_map[ids[i]] = round(nsm, 3)

        # 统计
        sorted_nsms = sorted(point_nsms)
        n = len(sorted_nsms)
        report.point_nsm_mean = round(sum(sorted_nsms) / n, 3)
        report.point_nsm_median = round(sorted_nsms[n // 2], 3)
        report.point_nsm_q10 = round(sorted_nsms[max(0, int(n * 0.1))], 3)
        report.point_nsm_q25 = round(sorted_nsms[max(0, int(n * 0.25))], 3)

        # Clustering-NSM by KEY
        clusters: dict[str, list[int]] = {}
        for i, key in enumerate(keys):
            clusters.setdefault(key, []).append(i)

        c_nsm_total = 0.0
        c_weight_total = 0
        for key, members in clusters.items():
            s_nsm = self._set_nsm(members, global_1nn)
            report.cluster_nsms[key] = round(s_nsm, 3)
            report.cluster_sizes[key] = len(members)
            c_nsm_total += len(members) * s_nsm
            c_weight_total += len(members)

        report.clustering_nsm = round(
            c_nsm_total / c_weight_total if c_weight_total > 0 else 0.0, 3)

        # 弱聚类诊断
        for key, nsm in report.cluster_nsms.items():
            if nsm < 0.3 and report.cluster_sizes.get(key, 0) >= 3:
                # 找混淆目标
                members = clusters[key]
                confused = {}
                for i in members:
                    nn_key = keys[global_1nn[i]]
                    if nn_key != key:
                        confused[nn_key] = confused.get(nn_key, 0) + 1
                top = sorted(confused.items(), key=lambda x: x[1], reverse=True)[:2]
                diag = "与 " + ", ".join(f"{k}({v}次)" for k, v in top) if top else "邻域分散"
                report.weak_clusters.append({
                    "cluster": key, "nsm": nsm,
                    "diagnosis": f"全局1-NN在其他聚类的比例{1 - nsm:.0%}，混淆：{diag}"
                })

        # 判定（基于论文 q10 为最佳预测指标）
        q10 = report.point_nsm_q10
        mean = report.point_nsm_mean
        if q10 >= 0.5:
            report.verdict = "EXCELLENT"
            report.action = "向量空间质量优秀，即使最差10%的卡片也有稳定邻域"
        elif mean >= 0.5:
            report.verdict = "GOOD"
            report.action = "整体可搜索，部分聚类邻域不稳定，见弱聚类列表"
        elif mean >= 0.3:
            report.verdict = "MARGINAL"
            report.action = "可搜索性一般，建议对弱聚类执行 consolidate 重新归一化"
        else:
            report.verdict = "POOR"
            report.action = "向量空间严重碎片化（可能是 embedder 版本混用），建议全量重新 embed"

        return report

    def apply_nsm_to_store(self, report: NSMReport) -> int:
        """
        将 NSM 得分写回数据库（nsm_score 字段）。
        低 NSM 卡片在 Retriever._score() 中会得到轻微降权。
        返回更新数量。
        """
        updated = 0
        for card_id, nsm in report.card_nsm_map.items():
            self.store._conn.execute(
                "UPDATE experiences SET nsm_score=? WHERE id=?",
                (nsm, card_id),
            )
            updated += 1
        self.store._conn.commit()
        return updated

    # ── Private ──

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na > 0 and nb > 0 else 0.0

    def _compute_global_1nn(self, vectors: list[list[float]]) -> list[int]:
        """
        O(n²) 全局 1-NN 预计算。
        对 n ≤ 2000 的卡片池（每次约 0.1~1s），完全可接受。
        """
        n = len(vectors)
        nn = []
        for i in range(n):
            best_j, best_sim = -1, -2.0
            for j in range(n):
                if j == i:
                    continue
                sim = self._cosine(vectors[i], vectors[j])
                if sim > best_sim:
                    best_sim, best_j = sim, j
            nn.append(best_j)
        return nn

    def _set_nsm(self, members: list[int], global_1nn: list[int]) -> float:
        """set-NSM(S) = |{v ∈ S : NN_X(v) ∈ S}| / |S|"""
        if not members:
            return 0.0
        member_set = set(members)
        stable = sum(1 for i in members if global_1nn[i] in member_set)
        return stable / len(members)

    def _point_nsm(self, idx: int, vectors: list[list[float]],
                   global_1nn: list[int], r: int) -> float:
        """
        point-NSM(u; r) = set_nsm( {u} ∪ (r-1)-NN_X(u) )
        取 u 和 r-1 个最近邻，组成大小为 r 的集合 S，计算 set-NSM(S)。
        """
        n = len(vectors)
        # 找 r-1 个最近邻（暴力，r 通常 ≤ 10）
        sims = [(self._cosine(vectors[idx], vectors[j]), j)
                for j in range(n) if j != idx]
        sims.sort(reverse=True)
        neighborhood = {idx} | {j for _, j in sims[: r - 1]}
        return self._set_nsm(list(neighborhood), global_1nn)


# ════════════════════════════════════════════════════════════
# Retriever Integration Helper
# ════════════════════════════════════════════════════════════

def nsm_score_penalty(nsm: float) -> float:
    """
    v4.96: 将 nsm_score 转换为 Retriever 的惩罚因子。
    NSM ≥ 0.6 → 无惩罚（×1.0）
    NSM 0.3~0.6 → 轻微惩罚（×0.85~1.0）
    NSM < 0.3  → 降权（×0.70）  ← 邻域不稳定，搜索结果可能不准
    未计算(-1)  → 无影响（×1.0）
    """
    if nsm < 0:
        return 1.0  # -1 = not computed, no penalty
    if nsm >= 0.6:
        return 1.0
    if nsm >= 0.3:
        # 线性插值：0.3→0.85, 0.6→1.0
        return 0.85 + (nsm - 0.3) / 0.3 * 0.15
    return 0.70


# ════════════════════════════════════════════════════════════
# CLI Entry Point
# ════════════════════════════════════════════════════════════

def run_nsm_cli(args: list[str] | None = None) -> None:
    """
    gcc-evo nsm [--r R] [--key KEY] [--apply]
    """
    import argparse
    parser = argparse.ArgumentParser(description="GCC v4.96 NSM 可搜索性诊断")
    parser.add_argument("--r", type=int, default=5, help="邻域半径 (default: 5)")
    parser.add_argument("--key", type=str, default=None, help="只检测指定 KEY")
    parser.add_argument("--apply", action="store_true",
                        help="将 NSM 得分写回数据库 (nsm_score 字段)")
    parsed = parser.parse_args(args)

    store = GlobalMemory()
    diag = NSMDiagnostic(store)
    report = diag.run(r=parsed.r, key_filter=parsed.key)
    print(report.summary())

    if parsed.apply:
        n = diag.apply_nsm_to_store(report)
        print(f"\n✓ 已写入 nsm_score 字段：{n} 张卡片")

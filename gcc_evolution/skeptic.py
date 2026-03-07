"""
GCC v4.7 — Skeptic Agent
灵感来源：Xu & Yang (2026) "Scaling Reproducibility" Skeptic角色
        + FactorMiner 失败约束双通道内存

职责：
  1. improvement执行后运行确定性量化诊断（不依赖LLM主观判断）
  2. 比较 metrics_before → metrics_after，输出结构化SkepticVerdict
  3. 成功 → 自动更新 ExperienceCard（confidence↑, status=validated）
  4. 失败 → 自动生成 Constraint（DO NOT规则），标记 pitfall
  5. 支持 gcc-evo skeptic 命令行入口

设计原则：
  - 确定性：相同输入 → 相同输出，无随机性
  - 版本控制：每次诊断结果写入 .gcc/verification/ audit trail
  - 零LLM依赖：核心判断逻辑全部基于规则，LLM仅用于生成可读摘要

使用方式：
  # 在pipeline INTEGRATE阶段调用
  skeptic = Skeptic(key="SPY-ATR")
  verdict = skeptic.verify(card, metrics_after={...})
  if not verdict.passed:
      print(verdict.report())
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 内部模块导入（与现有GCC接口对齐）──────────────────────────

try:
    from .models import ExperienceCard, ExperienceType, CardStatus
    from .constraints import ConstraintStore, Constraint
    from .experience_store import GlobalMemory
    from .params import ParamStore, ParamGate
except ImportError:
    # 独立运行模式（测试用）
    ExperienceCard = None
    ConstraintStore = None
    GlobalMemory = None
    ParamStore = None
    ParamGate = None

# E4 (Engram#4 P1): soft gating from P001_engram eq.(9)
# 替换硬阈值 confidence >= 0.5 → sigmoid alpha门控（更平滑）
try:
    from .papers.formulas.P001_engram import eq_9_soft_gate as _soft_gate
except Exception:
    import math
    def _soft_gate(confidence: float, center: float = 0.5, temperature: float = 0.15) -> float:
        x = (confidence - center) / max(temperature, 1e-6)
        return 1.0 / (1.0 + math.exp(-x))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:10]


# ══════════════════════════════════════════════════════════════
# Gate指标定义（与 params.py 的7指标体系对齐）
# ══════════════════════════════════════════════════════════════

# 每个指标：(label, higher_is_better, required, default_threshold)
GATE_METRICS: dict[str, tuple[str, bool, bool, float]] = {
    "sharpe":         ("Sharpe Ratio",      True,  True,  2.0),
    "max_dd_pct":     ("Max Drawdown %",    False, True,  15.0),
    "win_rate":       ("Win Rate",          True,  True,  0.55),
    "calmar":         ("Calmar Ratio",      True,  False, 1.5),
    "profit_factor":  ("Profit Factor",     True,  False, 1.5),
    "sortino":        ("Sortino Ratio",     True,  False, 2.0),
    "cagr":           ("CAGR",             True,  False, 0.25),
}

# 判定为"退步"的阈值（相对变化）
REGRESSION_THRESHOLD = 0.05   # 5%相对变化视为退步
IMPROVEMENT_THRESHOLD = 0.03  # 3%相对变化视为改善


# ══════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════

@dataclass
class MetricDelta:
    """单个指标的前后对比结果"""
    name: str
    label: str
    before: float | None
    after: float | None
    higher_is_better: bool
    required: bool
    threshold: float

    @property
    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before

    @property
    def delta_pct(self) -> float | None:
        """相对变化百分比"""
        if self.before is None or self.after is None or self.before == 0:
            return None
        return (self.after - self.before) / abs(self.before)

    @property
    def meets_threshold(self) -> bool:
        """after值是否满足绝对阈值"""
        if self.after is None:
            return False
        if self.higher_is_better:
            return self.after >= self.threshold
        else:
            return self.after <= self.threshold

    @property
    def improved(self) -> bool:
        """相对before是否改善"""
        d = self.delta_pct
        if d is None:
            return False
        if self.higher_is_better:
            return d >= IMPROVEMENT_THRESHOLD
        else:
            return d <= -IMPROVEMENT_THRESHOLD   # 越小越好，所以负delta是改善

    @property
    def regressed(self) -> bool:
        """相对before是否退步"""
        d = self.delta_pct
        if d is None:
            return False
        if self.higher_is_better:
            return d <= -REGRESSION_THRESHOLD
        else:
            return d >= REGRESSION_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
            "delta_pct": round(self.delta_pct, 4) if self.delta_pct is not None else None,
            "meets_threshold": self.meets_threshold,
            "improved": self.improved,
            "regressed": self.regressed,
            "required": self.required,
            "threshold": self.threshold,
        }

    def to_line(self) -> str:
        """单行报告格式"""
        before_s = f"{self.before:.3f}" if self.before is not None else "N/A"
        after_s  = f"{self.after:.3f}"  if self.after  is not None else "N/A"
        delta_s  = ""
        if self.delta_pct is not None:
            sign = "+" if self.delta_pct >= 0 else ""
            delta_s = f" ({sign}{self.delta_pct:.1%})"

        if not self.meets_threshold:
            status = "✗ FAIL"
        elif self.improved:
            status = "↑ BETTER"
        elif self.regressed:
            status = "↓ REGRESS"
        else:
            status = "≈ OK"

        req_tag = "[REQ]" if self.required else "[OPT]"
        return (f"  {req_tag} {self.label:<20} "
                f"{before_s:>8} → {after_s:>8}{delta_s:<12}  {status}")


@dataclass
class SkepticVerdict:
    """Skeptic诊断的最终判决"""
    verdict_id: str = field(default_factory=_uid)
    card_id: str = ""
    key: str = ""
    symbol: str = ""
    created_at: str = field(default_factory=_now)

    # 判决结果
    passed: bool = False
    required_passed: int = 0
    required_total: int = 0
    optional_improved: int = 0
    regressions: list[str] = field(default_factory=list)

    # 详细指标
    deltas: list[MetricDelta] = field(default_factory=list)

    # 自动生成的内容
    auto_constraints: list[str] = field(default_factory=list)   # 生成的DO NOT规则ID
    confidence_delta: float = 0.0                               # 对card confidence的调整量
    new_pitfalls: list[str] = field(default_factory=list)

    # 审计
    verdict_file: str = ""

    @property
    def verdict_label(self) -> str:
        if self.passed and self.optional_improved > 0:
            return "VALIDATED ✓✓"
        elif self.passed:
            return "PASSED ✓"
        elif self.regressions:
            return "REGRESSION ✗"
        else:
            return "FAILED ✗"

    def report(self) -> str:
        lines = [
            f"╔══ SKEPTIC VERDICT: {self.verdict_label} ══",
            f"║  Key: {self.key}  Symbol: {self.symbol}",
            f"║  Card: {self.card_id}  Time: {self.created_at[:19]}",
            f"║  Required: {self.required_passed}/{self.required_total} passed",
            f"╠{'═'*52}",
        ]
        for d in self.deltas:
            lines.append(f"║{d.to_line()}")
        lines.append(f"╠{'═'*52}")

        if self.regressions:
            lines.append(f"║  ⚠ Regressions: {', '.join(self.regressions)}")
        if self.auto_constraints:
            lines.append(f"║  🚫 New constraints generated: {len(self.auto_constraints)}")
        if self.new_pitfalls:
            for p in self.new_pitfalls:
                lines.append(f"║  ✗ Pitfall: {p}")

        conf_sign = "+" if self.confidence_delta >= 0 else ""
        lines.append(f"║  Confidence adjustment: {conf_sign}{self.confidence_delta:+.2f}")
        lines.append(f"╚{'═'*52}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "verdict_id": self.verdict_id,
            "card_id": self.card_id,
            "key": self.key,
            "symbol": self.symbol,
            "created_at": self.created_at,
            "passed": self.passed,
            "verdict_label": self.verdict_label,
            "required_passed": self.required_passed,
            "required_total": self.required_total,
            "optional_improved": self.optional_improved,
            "regressions": self.regressions,
            "confidence_delta": self.confidence_delta,
            "new_pitfalls": self.new_pitfalls,
            "auto_constraints": self.auto_constraints,
            "deltas": [d.to_dict() for d in self.deltas],
        }


# ══════════════════════════════════════════════════════════════
# Skeptic核心类
# ══════════════════════════════════════════════════════════════

class Skeptic:
    """
    确定性improvement验证智能体。

    流程（对应论文Figure 1的Skeptic角色）：
      1. verify()    — 接收 metrics_after，运行确定性诊断
      2. _diagnose() — 逐指标比较，生成 MetricDelta列表
      3. _judge()    — 根据规则判定 passed/failed
      4. _apply()    — 写回 ExperienceCard + 生成 Constraint
      5. _audit()    — 写入 .gcc/verification/ audit trail
    """

    VERIFICATION_DIR = ".gcc/verification"

    def __init__(
        self,
        key: str = "",
        symbol: str = "",
        store: "GlobalMemory | None" = None,
        constraint_store: "ConstraintStore | None" = None,
        verification_dir: str | None = None,
    ):
        self.key = key
        self.symbol = symbol
        self._store = store
        self._cstore = constraint_store
        self._vdir = Path(verification_dir or self.VERIFICATION_DIR)
        self._vdir.mkdir(parents=True, exist_ok=True)

        # 懒加载存储（避免在没有.gcc目录时崩溃）
        self._store_loaded = store is not None
        self._cstore_loaded = constraint_store is not None

    def _lazy_load_stores(self):
        """懒加载全局存储，仅在需要时初始化"""
        if not self._store_loaded and GlobalMemory is not None:
            try:
                self._store = GlobalMemory()
                self._store_loaded = True
            except Exception as e:
                logger.warning("[SKEPTIC] GlobalMemory init failed: %s", e)
        if not self._cstore_loaded and ConstraintStore is not None:
            try:
                self._cstore = ConstraintStore()
                self._cstore_loaded = True
            except Exception as e:
                logger.warning("[SKEPTIC] ConstraintStore init failed: %s", e)

    # ── 主入口 ──────────────────────────────────────────────

    def verify(
        self,
        card: "ExperienceCard",
        metrics_after: dict[str, float],
        thresholds: dict[str, float] | None = None,
        apply_to_card: bool = True,
        regime: str = "",
    ) -> SkepticVerdict:
        """
        对一次improvement执行完整验证。

        Args:
            card:          待验证的ExperienceCard（含metrics_before）
            metrics_after: 执行后的实测指标 {"sharpe": 2.3, "max_dd_pct": 11.2, ...}
            thresholds:    覆盖默认阈值（可选）
            apply_to_card: 是否自动写回card和生成constraints
            regime:        市场体制 (bull/bear/ranging) 用于体制感知阈值

        Returns:
            SkepticVerdict: 完整判决结果
        """
        self._lazy_load_stores()

        # 1. 提取before指标
        metrics_before = getattr(card, "metrics_before", {}) or {}

        # 2. 尝试从params加载阈值（如果有symbol）
        param_thresholds = self._load_param_thresholds()
        # v5.050 P2-DATA-2: 体制感知阈值覆盖
        regime_thresholds = self._load_regime_thresholds(regime)
        effective_thresholds = {**param_thresholds, **regime_thresholds,
                                **(thresholds or {})}

        # 3. 逐指标诊断
        deltas = self._diagnose(metrics_before, metrics_after, effective_thresholds)

        # 4. 判决
        verdict = self._judge(card, deltas)

        # 5. 写回card + 生成constraints
        if apply_to_card:
            self._apply(card, verdict, metrics_after)

        # 6. 写入audit trail
        self._audit(verdict)

        return verdict

    def verify_from_params(
        self,
        card: "ExperienceCard",
        apply_to_card: bool = True,
    ) -> SkepticVerdict | None:
        """
        直接从 params gate check结果验证（无需手动传入metrics）。
        自动读取 .gcc/params/{symbol}.yaml 的 backtest 字段。
        """
        if not self.symbol or ParamStore is None:
            return None

        try:
            params = ParamStore.load(self.symbol)
            bt = params.get("backtest", {})
            if not bt or not any(v is not None for v in bt.values()):
                return None

            metrics_after = {k: v for k, v in bt.items() if v is not None}
            return self.verify(card, metrics_after, apply_to_card=apply_to_card)
        except Exception as e:
            logger.warning("[SKEPTIC] backtest verify failed: %s", e)
            return None

    # ── 诊断层 ──────────────────────────────────────────────

    def _load_param_thresholds(self) -> dict[str, float]:
        """从 params YAML 加载目标阈值"""
        if not self.symbol or ParamStore is None:
            return {}
        try:
            params = ParamStore.load(self.symbol)
            targets = params.get("targets", {})
            mapping = {
                "sharpe_min": "sharpe",
                "max_dd_pct": "max_dd_pct",
                "win_rate_min": "win_rate",
                "calmar_min": "calmar",
                "profit_factor_min": "profit_factor",
                "sortino_min": "sortino",
                "cagr_min": "cagr",
            }
            result = {}
            for yaml_key, metric_key in mapping.items():
                if yaml_key in targets and targets[yaml_key] is not None:
                    result[metric_key] = float(targets[yaml_key])
            return result
        except Exception as e:
            logger.warning("[SKEPTIC] load constraint targets failed: %s", e)
            return {}

    def _load_regime_thresholds(self, regime: str) -> dict[str, float]:
        """v5.050 P2-DATA-2: 体制感知阈值(bear宽松/bull严格/ranging中性)."""
        if not regime:
            return {}
        # 体制默认调整 (bear市宽松, bull市严格)
        REGIME_ADJUSTMENTS: dict[str, dict[str, float]] = {
            "bear":    {"sharpe": 1.5, "max_dd_pct": 20.0, "win_rate": 0.50},
            "bull":    {"sharpe": 2.5, "max_dd_pct": 12.0, "win_rate": 0.58},
            "ranging": {"sharpe": 1.8, "max_dd_pct": 15.0, "win_rate": 0.53},
        }
        return REGIME_ADJUSTMENTS.get(regime.lower(), {})

    def _diagnose(
        self,
        before: dict[str, float],
        after: dict[str, float],
        thresholds: dict[str, float],
    ) -> list[MetricDelta]:
        """逐指标生成 MetricDelta（纯确定性，无LLM）"""
        deltas = []
        for name, (label, higher_is_better, required, default_threshold) in GATE_METRICS.items():
            threshold = thresholds.get(name, default_threshold)
            delta = MetricDelta(
                name=name,
                label=label,
                before=before.get(name),
                after=after.get(name),
                higher_is_better=higher_is_better,
                required=required,
                threshold=threshold,
            )
            deltas.append(delta)
        return deltas

    # ── 判决层 ──────────────────────────────────────────────

    def _judge(self, card: "ExperienceCard", deltas: list[MetricDelta]) -> SkepticVerdict:
        """基于规则的确定性判决"""
        verdict = SkepticVerdict(
            card_id=getattr(card, "id", ""),
            key=self.key or getattr(card, "key", ""),
            symbol=self.symbol,
        )
        verdict.deltas = deltas

        required_deltas = [d for d in deltas if d.required and d.after is not None]
        optional_deltas = [d for d in deltas if not d.required and d.after is not None]

        # 必要指标：必须全部满足阈值
        passed_required = [d for d in required_deltas if d.meets_threshold]
        verdict.required_passed = len(passed_required)
        verdict.required_total = len(required_deltas)

        # 可选指标：统计改善数量
        verdict.optional_improved = sum(1 for d in optional_deltas if d.improved)

        # 退步检测（任意指标退步超过阈值）
        verdict.regressions = [
            d.name for d in deltas
            if d.regressed and d.after is not None
        ]

        # 判决规则：
        #   必须 = 有数据的required指标全部通过阈值
        #   且   = 没有required指标退步
        required_no_regression = all(
            not d.regressed for d in required_deltas
        )
        verdict.passed = (
            verdict.required_passed == verdict.required_total
            and verdict.required_total > 0
            and required_no_regression
        )

        # E4: Confidence调整 — soft gate (eq.9) 替代硬阈值 ≥0.5
        # sigmoid alpha ∈ (0,1) 平滑映射 pass_ratio → confidence_delta
        pass_ratio = (verdict.required_passed / max(verdict.required_total, 1))
        soft_score = _soft_gate(pass_ratio)  # E4: sigmoid gate weight
        if verdict.passed:
            # 基础通过 +0.05 × soft_score 加权，每个可选指标改善额外 +0.02
            verdict.confidence_delta = 0.05 * soft_score + verdict.optional_improved * 0.02
            verdict.confidence_delta = min(verdict.confidence_delta, 0.15)
        else:
            # 失败 soft_score 越低惩罚越重（-0.15 × (1-soft_score)），每个regression额外 -0.05
            verdict.confidence_delta = -0.15 * (1.0 - soft_score) - len(verdict.regressions) * 0.05
            verdict.confidence_delta = max(verdict.confidence_delta, -0.35)

            # 生成pitfall描述
            for d in deltas:
                if d.required and not d.meets_threshold and d.after is not None:
                    verdict.new_pitfalls.append(
                        f"{d.label} below threshold: "
                        f"{d.after:.3f} < {d.threshold:.3f}"
                    )
                if d.regressed and d.after is not None:
                    verdict.new_pitfalls.append(
                        f"{d.label} regressed: "
                        f"{d.before:.3f} → {d.after:.3f} "
                        f"({d.delta_pct:+.1%})"
                    )

        return verdict

    # ── 写回层 ──────────────────────────────────────────────

    def _apply(
        self,
        card: "ExperienceCard",
        verdict: SkepticVerdict,
        metrics_after: dict[str, float],
    ) -> None:
        """将判决结果写回ExperienceCard + 生成Constraints"""

        # 1. 更新 card 的 metrics_after 和 confidence
        if hasattr(card, "metrics_after"):
            card.metrics_after = metrics_after
        if hasattr(card, "confidence"):
            card.confidence = round(
                max(0.0, min(1.0, card.confidence + verdict.confidence_delta)), 3
            )
        if hasattr(card, "last_validated"):
            card.last_validated = _now()

        # 2. 更新 card status
        if hasattr(card, "status") and CardStatus is not None:
            if verdict.passed:
                card.status = CardStatus.VALIDATED
            elif verdict.confidence_delta < -0.2:
                # 严重失败 → 归档
                card.status = CardStatus.ARCHIVED
            else:
                # 中等失败 → 退回草稿(需重审)
                card.status = CardStatus.DRAFT

        # 2b. v5.010 P1-StockMem-2: 失败计数 + 判决记录
        if hasattr(card, "last_skeptic_verdict"):
            card.last_skeptic_verdict = verdict.verdict_label
        if hasattr(card, "skeptic_fail_count") and not verdict.passed:
            card.skeptic_fail_count = getattr(card, "skeptic_fail_count", 0) + 1

        # 3. 追加新pitfalls到card
        if hasattr(card, "pitfalls") and verdict.new_pitfalls:
            existing = set(card.pitfalls or [])
            for p in verdict.new_pitfalls:
                if p not in existing:
                    card.pitfalls.append(p)
                    existing.add(p)

        # 4. v5.050 P2-StockMem: 失败时写因果三元组 (必须在store之前)
        if not verdict.passed:
            self._write_causal_triplet(card, verdict)

        # 5. 写回全局存储
        if self._store:
            try:
                self._store.store(card)
            except Exception as e:
                logger.warning("[SKEPTIC] store card after verify failed: %s", e)

        # 6. 失败时自动生成 Constraints
        if not verdict.passed and self._cstore and ConstraintStore is not None:
            self._generate_constraints(card, verdict)

        # 6b. v4.97 Reflexion: 失败时生成 self_reflection (#07 Reflexion NeurIPS 2023)
        if not verdict.passed:
            self._generate_self_reflection(card, verdict)

        # 7. v4.97 SkillRL: 失败时标记对应 skill 需复审 (#16 SkillRL 2026)
        if not verdict.passed:
            self._mark_skill_needs_revision(card, verdict)

    def _write_causal_triplet(
        self, card: "ExperienceCard", verdict: "SkepticVerdict",
    ) -> None:
        """v5.050 P2-StockMem: Skeptic失败后写causal_context/event/outcome到card."""
        context = f"key={self.key} symbol={self.symbol}"
        event = f"Skeptic verification {verdict.verdict_label}"
        outcomes = []
        for d in verdict.deltas:
            if not d.meets_threshold and d.after is not None:
                outcomes.append(f"{d.label}: {d.after:.3f} (need {d.threshold:.3f})")
        outcome = "; ".join(outcomes[:3]) if outcomes else "metrics below threshold"

        if hasattr(card, "causal_trigger"):
            card.causal_trigger = context
        if hasattr(card, "causal_action"):
            card.causal_action = event
        if hasattr(card, "causal_outcome"):
            card.causal_outcome = outcome

    def _generate_constraints(
        self,
        card: "ExperienceCard",
        verdict: SkepticVerdict,
    ) -> None:
        """从失败判决自动生成DO NOT约束规则"""
        generated_ids = []

        # 从新pitfalls生成
        for pitfall in verdict.new_pitfalls:
            if len(pitfall) < 10:
                continue
            c = Constraint(
                source_card_id=getattr(card, "id", ""),
                rule=pitfall,
                context=(
                    f"symbol={self.symbol} key={self.key} "
                    f"required={verdict.required_passed}/{verdict.required_total}"
                ),
                key=self.key or getattr(card, "key", ""),
                confidence=abs(verdict.confidence_delta),
            )
            added = self._cstore.add(c)
            generated_ids.append(added.id)

        # 从退步指标生成通用约束
        for regression_name in verdict.regressions:
            d = next((x for x in verdict.deltas if x.name == regression_name), None)
            if d and d.delta_pct is not None:
                rule = (
                    f"Last parameter change caused {d.label} regression "
                    f"({d.delta_pct:+.1%}). Review entry/risk params before retry."
                )
                c = Constraint(
                    source_card_id=getattr(card, "id", ""),
                    rule=rule,
                    context=f"symbol={self.symbol} key={self.key}",
                    key=self.key or getattr(card, "key", ""),
                    confidence=0.7,
                )
                added = self._cstore.add(c)
                generated_ids.append(added.id)

        verdict.auto_constraints = generated_ids

    # ── v4.97 Reflexion: Self-Reflection Generation ─────────

    def _generate_self_reflection(
        self,
        card: "ExperienceCard",
        verdict: "SkepticVerdict",
    ) -> None:
        """
        v4.97 — Reflexion: 失败后生成语言自我反思（#07 Reflexion NeurIPS 2023）。

        原论文：Noah Shinn et al., NeurIPS 2023 — 用语言写自我反思，
        存入 episodic buffer，下次执行同类任务时注入，HumanEval 91% pass@1。

        GCC 实现：
          skeptic 判断失败 → 生成 self_reflection 写入 card.self_reflection
          下次 retrieve_dual() / context_chain 自动注入
          多次积累后 distill_insights() 归纳跨卡通用规律（与 ExpeL #06 形成闭环）

        写入位置：card.self_reflection（str 字段，ExperienceCard v4.97 新增）
        """
        # 构建反思内容（LLM 或规则回退）
        reflection = self._compose_reflection(card, verdict)
        if not reflection:
            return

        # 写入 card（兼容旧 card 对象，setattr 安全写入）
        if not hasattr(card, "self_reflection"):
            try:
                object.__setattr__(card, "self_reflection", "")
            except Exception as e:
                logger.warning("[SKEPTIC] clear self_reflection failed: %s", e)

        try:
            card.self_reflection = reflection
        except Exception as e:
            logger.warning("[SKEPTIC] set self_reflection failed: %s", e)
            return

        # 持久化写回 store
        if self._store:
            try:
                self._store.store(card)
            except Exception as e:
                logger.warning("[SKEPTIC] store card after reflection failed: %s", e)

        # 写入 audit trail 附加字段
        verdict_file = getattr(verdict, "verdict_file", "")
        if verdict_file:
            try:
                import json as _json
                p = __import__("pathlib").Path(verdict_file)
                if p.exists():
                    data = _json.loads(p.read_text("utf-8"))
                    data["self_reflection"] = reflection
                    p.write_text(_json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            except Exception as e:
                logger.warning("[SKEPTIC] write reflection to file failed: %s", e)

    def _compose_reflection(
        self,
        card: "ExperienceCard",
        verdict: "SkepticVerdict",
    ) -> str:
        """生成反思文本（LLM 优先，规则回退）。"""
        # ── 构建失败摘要 ──
        failed_metrics = [
            f"{d.label}: {d.before}→{d.after} (threshold={d.threshold})"
            for d in verdict.deltas
            if not d.meets_threshold and d.after is not None
        ]
        regressions = [
            f"{d.label}: {d.delta_pct:+.1%}"
            for d in verdict.deltas
            if d.delta_pct is not None and abs(d.delta_pct) > 0.05 and not d.meets_threshold
        ]

        if not failed_metrics and not verdict.new_pitfalls:
            return ""

        # ── LLM 反思 ──
        llm = self._get_llm_for_reflection()
        if llm:
            system = """你是 GCC Reflexion 反思引擎（Noah Shinn et al. NeurIPS 2023）。
根据一次失败的验证结果，生成一段简短的语言自我反思。

要求：
- 1-2 句话，简洁直接
- 说清楚「哪里错了」和「下次应该怎么做」
- 有量化数据时必须写进来
- 输出纯文本，不要 JSON 不要 markdown"""

            user_parts = [
                f"改善点: {self.key or getattr(card, 'key', '未知')}",
                f"策略: {getattr(card, 'strategy', '') or getattr(card, 'key_insight', '')}",
            ]
            if failed_metrics:
                user_parts.append(f"未达标指标: {'; '.join(failed_metrics[:3])}")
            if regressions:
                user_parts.append(f"退步指标: {'; '.join(regressions[:3])}")
            if verdict.new_pitfalls:
                user_parts.append(f"新发现 pitfall: {verdict.new_pitfalls[0]}")

            try:
                reflection = llm.generate(
                    system=system,
                    user="\n".join(user_parts),
                    temperature=0.4,
                    max_tokens=150,
                ).strip()
                if reflection:
                    return reflection
            except Exception as e:
                logger.warning("[SKEPTIC] LLM reflection generation failed: %s", e)

        # ── 规则回退 ──
        parts = []
        if failed_metrics:
            parts.append(f"指标未达标: {failed_metrics[0]}")
        if regressions:
            parts.append(f"退步: {regressions[0]}")
        if verdict.new_pitfalls:
            parts.append(f"避免: {verdict.new_pitfalls[0]}")
        return "；".join(parts) if parts else ""

    def _mark_skill_needs_revision(
        self,
        card: "ExperienceCard",
        verdict: "SkepticVerdict",
    ) -> None:
        """
        v4.97 — SkillRL Recursive Co-evolution (#16 SkillRL 2026)
        skeptic 失败 → 标记对应 skill 需复审
        consolidate 时 auto_redist_marked() 自动重蒸馏
        """
        try:
            from .skill_registry import SkillBank
            sb = SkillBank(str(self._gcc_dir))
            reason = verdict.new_pitfalls[0] if verdict.new_pitfalls else ""
            card_id = getattr(card, "id", "")
            if card_id:
                sb.mark_needs_revision(f"GEN_{card_id}", reason=reason)
        except Exception as e:
            logger.warning("[SKEPTIC] mark_needs_revision failed: %s", e)

    def _get_llm_for_reflection(self):
        """懒加载 LLM（使用 GCCConfig 配置）。"""
        if hasattr(self, "_llm_client") and self._llm_client:
            return self._llm_client
        try:
            from .config import GCCConfig
            from .llm_client import LLMClient
            cfg = GCCConfig.load()
            if cfg.llm_api_key:
                self._llm_client = LLMClient(cfg)
                return self._llm_client
        except Exception as e:
            logger.warning("[SKEPTIC] LLM client init failed: %s", e)
        return None

    # ── Audit Trail ─────────────────────────────────────────

    def _audit(self, verdict: SkepticVerdict) -> None:
        """写入验证审计记录"""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"skeptic_{ts}_{verdict.verdict_id}.json"
        fpath = self._vdir / fname
        try:
            fpath.write_text(
                json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            verdict.verdict_file = str(fpath)
        except Exception as e:
            logger.warning("[SKEPTIC] save verdict file failed: %s", e)

    # ── 批量验证 ────────────────────────────────────────────

    def batch_verify(
        self,
        cards_and_metrics: list[tuple["ExperienceCard", dict[str, float]]],
        apply_to_cards: bool = True,
    ) -> list[SkepticVerdict]:
        """批量验证多个improvement"""
        return [
            self.verify(card, metrics, apply_to_card=apply_to_cards)
            for card, metrics in cards_and_metrics
        ]

    # ── 历史报告 ────────────────────────────────────────────

    def load_history(self, limit: int = 20) -> list[dict]:
        """读取最近N条验证记录"""
        files = sorted(self._vdir.glob("skeptic_*.json"), reverse=True)[:limit]
        results = []
        for f in files:
            try:
                results.append(json.loads(f.read_text("utf-8")))
            except Exception as e:
                logger.warning("[SKEPTIC] load verdict file %s failed: %s", f.name, e)
        return results

    def summary_report(self, limit: int = 20) -> str:
        """最近N次验证的统计摘要"""
        history = self.load_history(limit)
        if not history:
            return "No verification history found."

        total = len(history)
        passed = sum(1 for v in history if v.get("passed"))
        avg_conf_delta = (
            sum(v.get("confidence_delta", 0) for v in history) / total
        )
        regression_counts: dict[str, int] = {}
        for v in history:
            for r in v.get("regressions", []):
                regression_counts[r] = regression_counts.get(r, 0) + 1

        lines = [
            f"╔══ SKEPTIC HISTORY SUMMARY (last {total} verifications) ══",
            f"║  Pass rate:       {passed}/{total} ({passed/total:.0%})",
            f"║  Avg conf delta:  {avg_conf_delta:+.3f}",
        ]
        if regression_counts:
            top = sorted(regression_counts.items(), key=lambda x: -x[1])[:3]
            lines.append(f"║  Top regressions: {', '.join(f'{k}×{v}' for k,v in top)}")
        lines.append(f"╚{'═'*50}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Pipeline集成辅助：INTEGRATE阶段Gate
# ══════════════════════════════════════════════════════════════

def run_skeptic_gate(
    key: str,
    symbol: str,
    card_id: str | None = None,
    metrics_after: dict[str, float] | None = None,
) -> tuple[bool, str]:
    """
    pipeline.py INTEGRATE阶段调用入口。

    返回: (passed: bool, report: str)
    使用方式:
        passed, report = run_skeptic_gate("SPY-ATR", "SPY", metrics_after={...})
        if not passed:
            raise PipelineGateError(report)
    """
    skeptic = Skeptic(key=key, symbol=symbol)

    # 如果没有传入metrics_after，尝试从params读取
    if metrics_after is None:
        try:
            if ParamStore is not None:
                params = ParamStore.load(symbol)
                bt = params.get("backtest", {})
                metrics_after = {k: v for k, v in bt.items() if v is not None}
        except Exception as e:
            logger.warning("[SKEPTIC] load backtest metrics failed: %s", e)

    if not metrics_after:
        return False, f"[Skeptic] No metrics available for {symbol}. Run backtest first."

    # 如果没有提供card，创建临时卡片仅用于诊断
    if ExperienceCard is not None:
        card = ExperienceCard(
            id=card_id or f"temp_{_uid()}",
            key=key,
            exp_type=ExperienceType.SUCCESS if ExperienceType else "success",
        )
    else:
        card = type("FakeCard", (), {
            "id": card_id or f"temp_{_uid()}",
            "key": key,
            "metrics_before": {},
            "metrics_after": {},
            "confidence": 0.5,
            "pitfalls": [],
            "last_validated": "",
            "status": None,
        })()

    verdict = skeptic.verify(card, metrics_after, apply_to_card=(card_id is not None))
    return verdict.passed, verdict.report()


# ══════════════════════════════════════════════════════════════
# CLI 入口（供 gcc_evo.py 注册命令）
# ══════════════════════════════════════════════════════════════

def cli_skeptic_cmd(symbol: str, key: str = "", show_history: bool = False):
    """
    gcc-evo skeptic SPY [--key SPY-ATR] [--history]

    集成到 gcc_evo.py 方式：
        @cli.command()
        @click.argument("symbol")
        @click.option("--key", "-k", default="")
        @click.option("--history", is_flag=True)
        def skeptic(symbol, key, history):
            cli_skeptic_cmd(symbol, key, history)
    """
    skeptic = Skeptic(key=key, symbol=symbol)

    if show_history:
        print(skeptic.summary_report())
        return

    passed, report = run_skeptic_gate(key=key, symbol=symbol)
    print(report)
    if not passed:
        print("\n[Skeptic] Gate FAILED. Fix regressions before marking DONE.")
    else:
        print("\n[Skeptic] Gate PASSED. Safe to advance to DONE.")


# ══════════════════════════════════════════════════════════════
# 独立测试（python skeptic.py 直接运行）
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Skeptic Self-Test ===\n")

    # 模拟ExperienceCard
    class MockCard:
        id = "exp_test001"
        key = "SPY-ATR"
        confidence = 0.65
        pitfalls = []
        metrics_before = {
            "sharpe": 1.8,
            "max_dd_pct": 16.5,
            "win_rate": 0.52,
            "calmar": 1.2,
        }
        metrics_after = {}
        last_validated = ""
        status = None

    card = MockCard()

    # 测试1：成功案例
    print("--- Test 1: PASS scenario ---")
    skeptic = Skeptic(key="SPY-ATR", symbol="SPY")
    verdict = skeptic.verify(card, {
        "sharpe": 2.3,
        "max_dd_pct": 11.0,
        "win_rate": 0.58,
        "calmar": 1.8,
        "profit_factor": 1.7,
    }, apply_to_card=False)
    print(verdict.report())
    print(f"Card confidence would be: {card.confidence + verdict.confidence_delta:.3f}\n")

    # 测试2：失败案例
    print("--- Test 2: FAIL scenario (regression) ---")
    card2 = MockCard()
    card2.id = "exp_test002"
    verdict2 = skeptic.verify(card2, {
        "sharpe": 1.5,        # 低于阈值2.0
        "max_dd_pct": 18.0,   # 超过阈值15%
        "win_rate": 0.53,     # 低于阈值0.55
    }, apply_to_card=False)
    print(verdict2.report())
    print(f"\nAuto pitfalls generated: {len(verdict2.new_pitfalls)}")
    for p in verdict2.new_pitfalls:
        print(f"  - {p}")

"""
GCC v4.86 — Retrospective Analyzer
数据驱动的知识进化核心机制。

核心思想：
  任何执行系统都会产生两类历史数据：
    A. 执行数据（Executed）  → 规则放行，有结果反馈
    B. 拦截数据（Intercepted）→ 规则拦截，无结果

  通过外部验证器（Validator）对两类数据做回溯评估：
    A × Validator → 执行决策的准确率
    B × Validator → 拦截规则的误杀率

  结论驱动知识更新：
    准确率低 → 决策条件有问题 → 更新参数/知识卡
    误杀率高 → 过滤规则太严   → 放宽条件
    写入知识卡 → 下次决策更好  → 持续进化

适用场景：
  任何有"规则过滤 + 结果反馈"结构的系统
  （编程 Agent、交易系统、内容审核、推荐系统等）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


# ── 数据类型 ──────────────────────────────────────────────────

class DataClass(str, Enum):
    EXECUTED    = "executed"      # 规则放行，有结果
    INTERCEPTED = "intercepted"   # 规则拦截，无结果


class ValidationResult(str, Enum):
    VALID    = "valid"     # 外部验证器认为决策正确
    INVALID  = "invalid"  # 外部验证器认为决策错误
    NEUTRAL  = "neutral"  # 无法判断


@dataclass
class DecisionRecord:
    """
    一条决策记录，可以是执行的或被拦截的。
    与具体领域无关，通过 metadata 扩展。
    """
    record_id:    str
    key:          str            # 关联的 KEY（知识卡/改善项）
    data_class:   DataClass
    decision:     str            # 做出的决策（如 "approve"/"reject"，领域自定义）
    conditions:   dict           # 触发决策的条件（信号、规则、上下文）
    timestamp:    str
    outcome:      Optional[float] = None   # 实际结果（+/-，执行数据才有）
    validation:   Optional[ValidationResult] = None  # 外部验证结果
    validator_reason: str = ""
    metadata:     dict = field(default_factory=dict)


@dataclass
class RetrospectiveReport:
    """回溯分析报告"""
    key:            str
    generated_at:   str
    period_start:   str
    period_end:     str

    # 执行数据分析
    executed_total:     int = 0
    executed_win_rate:  float = 0.0   # 实际结果为正的比例
    executed_valid_rate: float = 0.0  # 验证器认为正确的比例

    # 拦截数据分析
    intercepted_total:      int = 0
    intercept_false_rate:   float = 0.0  # 误杀率（拦截了但验证器认为应该放行）

    # v5.295: 信号准确率分析 (4H回填)
    signal_accuracy:        dict = field(default_factory=dict)
    # {source: {total, correct, acc}} — 各外挂信号级别准确率

    # 条件级别分析
    condition_stats: list = field(default_factory=list)
    # 每条：{condition_key, condition_val, n, win_rate, valid_rate, recommendation}

    # 结论
    findings:       list = field(default_factory=list)   # 关键发现
    suggestions:    list = field(default_factory=list)   # 参数调整建议

    def to_markdown(self) -> str:
        lines = [
            f"# 回溯分析报告 — {self.key}",
            f"> 生成时间：{self.generated_at}",
            f"> 分析周期：{self.period_start} ~ {self.period_end}",
            "",
            "## 执行数据分析",
            f"- 总执行数：{self.executed_total}",
            f"- 实际胜率：{self.executed_win_rate:.1%}",
            f"- 验证器合理率：{self.executed_valid_rate:.1%}",
            "",
            "## 拦截数据分析",
            f"- 总拦截数：{self.intercepted_total}",
            f"- 误杀率：{self.intercept_false_rate:.1%}",
            "",
        ]

        if self.signal_accuracy:
            lines += ["## 信号准确率 (4H回填)", ""]
            lines.append("| 外挂 | 样本 | 正确 | 准确率 |")
            lines.append("|------|------|------|--------|")
            for src, sa in sorted(self.signal_accuracy.items()):
                acc = f"{sa.get('acc', 0):.1%}" if sa.get('acc') is not None else "N/A"
                lines.append(f"| {src} | {sa.get('total', 0)} | {sa.get('correct', 0)} | {acc} |")
            lines.append("")

        if self.condition_stats:
            lines += ["## 条件级别分析", ""]
            lines.append("| 条件 | 值 | 样本 | 胜率 | 验证合理率 | 建议 |")
            lines.append("|------|-----|------|------|-----------|------|")
            for s in self.condition_stats:
                lines.append(
                    f"| {s.get('condition_key','')} "
                    f"| {s.get('condition_val','')} "
                    f"| {s.get('n',0)} "
                    f"| {s.get('win_rate',0):.1%} "
                    f"| {s.get('valid_rate',0):.1%} "
                    f"| {s.get('recommendation','')} |"
                )
            lines.append("")

        if self.findings:
            lines += ["## 关键发现", ""]
            for i, f in enumerate(self.findings, 1):
                lines.append(f"{i}. {f}")
            lines.append("")

        if self.suggestions:
            lines += ["## 参数调整建议", ""]
            for s in self.suggestions:
                lines.append(f"- {s}")

        return "\n".join(lines)


# ── 核心分析器 ───────────────────────────────────────────────

class RetrospectiveAnalyzer:
    """
    通用回溯分析器。

    使用方式：
      analyzer = RetrospectiveAnalyzer(key="KEY-001")
      analyzer.load_records(records)           # 加载决策记录
      analyzer.run_validation(validator_fn)    # 运行外部验证器
      report = analyzer.generate_report()     # 生成报告
      analyzer.save_to_card(card_path)        # 写入知识卡
    """

    def __init__(self, key: str):
        self.key = key
        self.records: list[DecisionRecord] = []

    def load_records(self, records: list[DecisionRecord]):
        self.records = records

    def run_validation(self, validator: Callable[[DecisionRecord], ValidationResult]):
        """
        对所有记录运行外部验证器。
        validator 是一个函数：DecisionRecord → ValidationResult
        领域自定义（Vision、回测、人工审核等）
        """
        for r in self.records:
            r.validation = validator(r)

    def generate_report(self,
                        period_start: str = "",
                        period_end: str = "") -> RetrospectiveReport:
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        executed    = [r for r in self.records if r.data_class == DataClass.EXECUTED]
        intercepted = [r for r in self.records if r.data_class == DataClass.INTERCEPTED]

        # 执行数据分析
        exec_total = len(executed)
        exec_wins  = sum(1 for r in executed if (r.outcome or 0) > 0)
        exec_valid = sum(1 for r in executed if r.validation == ValidationResult.VALID)
        exec_win_rate   = exec_wins  / exec_total if exec_total else 0
        exec_valid_rate = exec_valid / exec_total if exec_total else 0

        # 拦截数据分析（误杀 = 拦截了但验证器认为应该放行）
        int_total     = len(intercepted)
        int_false     = sum(1 for r in intercepted if r.validation == ValidationResult.VALID)
        int_false_rate = int_false / int_total if int_total else 0

        # 条件级别分析
        condition_stats = self._analyze_conditions(executed)

        # 自动生成关键发现
        findings = self._generate_findings(
            exec_win_rate, exec_valid_rate, int_false_rate, condition_stats)

        # 自动生成调整建议
        suggestions = self._generate_suggestions(condition_stats, int_false_rate)

        # v5.295: 加载外挂信号准确率数据
        signal_accuracy = self._load_signal_accuracy()

        return RetrospectiveReport(
            key=self.key,
            generated_at=now,
            period_start=period_start,
            period_end=period_end,
            executed_total=exec_total,
            executed_win_rate=exec_win_rate,
            executed_valid_rate=exec_valid_rate,
            intercepted_total=int_total,
            intercept_false_rate=int_false_rate,
            signal_accuracy=signal_accuracy,
            condition_stats=condition_stats,
            findings=findings,
            suggestions=suggestions,
        )

    def save_to_card(self, card_path: Path, report: RetrospectiveReport):
        """把报告追加写入知识卡"""
        card_path = Path(card_path)
        section = f"\n\n---\n\n## 回溯分析更新 — {report.generated_at}\n\n"
        section += report.to_markdown()

        if card_path.exists():
            existing = card_path.read_text(encoding='utf-8')
            card_path.write_text(existing + section, encoding='utf-8')
        else:
            card_path.write_text(report.to_markdown(), encoding='utf-8')

    # ── 内部方法 ──────────────────────────────────────────────

    def _load_signal_accuracy(self) -> dict:
        """v5.295: 加载外挂信号准确率(4H回填)数据。"""
        sa_path = Path("state") / "plugin_signal_accuracy.json"
        if not sa_path.exists():
            return {}
        try:
            data = json.loads(sa_path.read_text(encoding="utf-8"))
            acc = data.get("accuracy", {})
            result = {}
            for src, syms in acc.items():
                overall = syms.get("_overall", {})
                if overall.get("total", 0) > 0:
                    result[src] = {
                        "total": overall.get("total", 0),
                        "correct": overall.get("correct", 0),
                        "acc": overall.get("acc"),
                    }
            return result
        except Exception:
            return {}

    def _analyze_conditions(self, executed: list) -> list:
        """按条件分组统计胜率和验证率"""
        from collections import defaultdict

        groups: dict = defaultdict(list)
        for r in executed:
            for ck, cv in r.conditions.items():
                key = (ck, str(cv))
                groups[key].append(r)

        stats = []
        for (ck, cv), records in groups.items():
            n = len(records)
            if n < 5:  # 样本不足
                continue
            wins  = sum(1 for r in records if (r.outcome or 0) > 0)
            valid = sum(1 for r in records if r.validation == ValidationResult.VALID)
            win_rate   = wins  / n
            valid_rate = valid / n

            if win_rate < 0.40 and valid_rate < 0.40:
                rec = "建议禁用"
            elif win_rate < 0.40:
                rec = "胜率低，收紧条件"
            elif valid_rate < 0.40:
                rec = "验证率低，观察"
            elif win_rate > 0.55 and valid_rate > 0.55:
                rec = "可放宽限制"
            else:
                rec = "保持现状"

            stats.append({
                'condition_key': ck,
                'condition_val': cv,
                'n': n,
                'win_rate': win_rate,
                'valid_rate': valid_rate,
                'recommendation': rec,
            })

        return sorted(stats, key=lambda x: x['win_rate'])

    def _generate_findings(self, win_rate, valid_rate,
                           false_intercept_rate, condition_stats) -> list:
        findings = []
        if win_rate < 0.40:
            findings.append(f"整体执行胜率偏低（{win_rate:.1%}），决策条件需要优化")
        if valid_rate < 0.50:
            findings.append(f"验证器合理率偏低（{valid_rate:.1%}），可能在错误位置执行")
        if false_intercept_rate > 0.25:
            findings.append(f"拦截误杀率偏高（{false_intercept_rate:.1%}），过滤规则可能过严")
        bad = [s for s in condition_stats if s['win_rate'] < 0.40]
        if bad:
            findings.append(f"发现 {len(bad)} 个低质量条件组合，建议禁用或收紧")
        good = [s for s in condition_stats if s['win_rate'] > 0.55]
        if good:
            findings.append(f"发现 {len(good)} 个高质量条件组合，可以适当放宽限制")
        return findings

    def _generate_suggestions(self, condition_stats, false_intercept_rate) -> list:
        suggestions = []
        for s in condition_stats:
            if s['recommendation'] == '建议禁用':
                suggestions.append(
                    f"禁用条件：{s['condition_key']}={s['condition_val']}"
                    f"（胜率{s['win_rate']:.1%}，样本{s['n']}）"
                )
            elif s['recommendation'] == '可放宽限制':
                suggestions.append(
                    f"放宽条件：{s['condition_key']}={s['condition_val']}"
                    f"（胜率{s['win_rate']:.1%}，样本{s['n']}）"
                )
        if false_intercept_rate > 0.25:
            suggestions.append("考虑放宽拦截规则，误杀率超过25%")
        return suggestions

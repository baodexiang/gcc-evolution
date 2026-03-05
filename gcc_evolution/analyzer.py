"""
GCC v4.92 — Analyzer
analyze run 的核心实现。

理论来源：
  Counterfactual Analysis (#14) — 执行 vs 拦截对比
  FactorMiner (#03)             — 双通道：成功模式 + 失败约束
  RAG (#22)                     — 检索知识卡注入分析上下文

流程：
  1. 从 trade_events 聚合统计（执行率、ai vs final 差异）
  2. 识别异常模式（高拦截、低胜率、特定条件下的偏差）
  3. LLM 基于统计 + 现有知识卡 生成建议
  4. 写入 suggestions，供 suggest review 审核

设计原则：
  - 无数据时明确告知，不产生空建议
  - 建议必须有数据支撑，evidence 字段必填
  - 领域无关：symbol/timeframe 由数据决定，引擎不假设
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 统计结构 ──────────────────────────────────────────────

@dataclass
class SymbolStats:
    """单个 symbol 在时间段内的统计"""
    symbol:         str
    total:          int = 0
    executed:       int = 0        # final_action != HOLD/SKIP
    ai_agree:       int = 0        # ai_action == final_action
    ai_disagree:    int = 0        # 过滤器改变了决策
    by_timeframe:   dict = field(default_factory=dict)   # {tf: count}
    by_wyckoff:     dict = field(default_factory=dict)   # {phase: {exec, total}}
    by_pos_zone:    dict = field(default_factory=dict)   # {zone: {exec, total}}
    filter_rate:    float = 0.0    # ai_disagree / total
    exec_rate:      float = 0.0    # executed / total

    def compute(self):
        if self.total > 0:
            self.filter_rate = self.ai_disagree / self.total
            self.exec_rate   = self.executed / self.total


@dataclass
class AnalysisResult:
    """analyze run 的完整结果"""
    period:         str
    since:          str
    total_events:   int = 0
    symbols:        list[SymbolStats] = field(default_factory=list)
    patterns:       list[dict] = field(default_factory=list)   # 发现的异常模式
    suggestions:    list[dict] = field(default_factory=list)   # 产生的建议
    report_md:      str = ""
    ran_at:         str = field(default_factory=_now)


# ── 核心分析引擎 ──────────────────────────────────────────

class Analyzer:
    """
    回溯分析引擎。
    统计 → 模式识别 → LLM 建议生成 → 写入 suggestions。
    """

    # 阈值配置（可通过 evolution.yaml 覆盖）
    MIN_SAMPLES       = 5      # 低于此样本数不产生建议
    HIGH_FILTER_RATE  = 0.4    # 过滤率超过此值认为异常
    LOW_EXEC_RATE     = 0.2    # 执行率低于此值认为异常

    def __init__(self, gcc_dir: Path | str = ".gcc", llm_client=None):
        self.gcc_dir    = Path(gcc_dir)
        self.llm        = llm_client
        self._db_path   = self.gcc_dir / "gcc.db"

    # ── 主入口 ────────────────────────────────────────────

    def run(self, period: str = "24h",
            key_id: str = "",
            save_report: bool = True) -> AnalysisResult:
        """
        运行完整分析流程。
        period: 12h / 24h / 7d / 30d
        """
        since = self._parse_period(period)
        result = AnalysisResult(period=period, since=since)

        # Step 1: 聚合统计
        stats = self._aggregate(since, key_id)
        if not stats:
            return result

        result.total_events = sum(s.total for s in stats)
        result.symbols       = stats

        # Step 2: 识别异常模式
        patterns = self._detect_patterns(stats)
        result.patterns = patterns

        # Step 3: 产生建议（LLM 或规则）
        suggestions = self._generate_suggestions(stats, patterns, period)
        result.suggestions = suggestions

        # Step 4: 写入 suggest store
        if suggestions:
            self._save_suggestions(suggestions, key_id)

        # Step 5: 生成报告
        result.report_md = self._build_report(result)
        if save_report:
            self._save_report(result)

        return result

    # ── Step 1: 聚合统计 ─────────────────────────────────

    def _aggregate(self, since: str, key_id: str) -> list[SymbolStats]:
        if not self._db_path.exists():
            return []

        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row

        # 基础过滤
        base_where = "WHERE event_time >= ?"
        params: list = [since]

        # 如果指定了 key，通过 product_links 关联
        if key_id:
            rows = conn.execute(f"""
                SELECT te.* FROM trade_events te
                JOIN improvement_product_links ipl ON te.symbol = ipl.symbol
                {base_where} AND ipl.key_id = ?
            """, [since, key_id]).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM trade_events {base_where}", params
            ).fetchall()

        conn.close()

        if not rows:
            return []

        # 按 symbol 聚合
        by_symbol: dict[str, SymbolStats] = {}
        for row in rows:
            sym = row["symbol"] or "UNKNOWN"
            if sym not in by_symbol:
                by_symbol[sym] = SymbolStats(symbol=sym)

            s = by_symbol[sym]
            s.total += 1

            # 兼容不同 schema 的列名
            _row  = dict(row)
            ai    = (_row.get("ai_action")    or _row.get("signal")           or "").upper()
            final = (_row.get("final_action") or _row.get("signal")           or "").upper()
            tf    = _row.get("timeframe")     or _row.get("source")           or "unknown"
            phase = _row.get("wyckoff_phase") or _row.get("overall_structure") or "unknown"
            zone  = _row.get("pos_zone")      or _row.get("position")         or "unknown"

            # 执行判断：final_action 不是 HOLD/SKIP/空
            if final and final not in ("HOLD", "SKIP", ""):
                s.executed += 1

            # AI vs 最终决策一致性
            if ai and final:
                if ai == final:
                    s.ai_agree += 1
                else:
                    s.ai_disagree += 1

            # 分组统计
            s.by_timeframe[tf] = s.by_timeframe.get(tf, 0) + 1

            if phase not in s.by_wyckoff:
                s.by_wyckoff[phase] = {"exec": 0, "total": 0}
            s.by_wyckoff[phase]["total"] += 1
            if final and final not in ("HOLD", "SKIP", ""):
                s.by_wyckoff[phase]["exec"] += 1

            if zone not in s.by_pos_zone:
                s.by_pos_zone[zone] = {"exec": 0, "total": 0}
            s.by_pos_zone[zone]["total"] += 1
            if final and final not in ("HOLD", "SKIP", ""):
                s.by_pos_zone[zone]["exec"] += 1

        for s in by_symbol.values():
            s.compute()

        return list(by_symbol.values())

    # ── Step 2: 模式识别 ─────────────────────────────────

    def _detect_patterns(self, stats: list[SymbolStats]) -> list[dict]:
        """
        识别异常模式，为建议提供数据支撑。
        规则驱动，不依赖 LLM。
        """
        patterns = []

        for s in stats:
            if s.total < self.MIN_SAMPLES:
                continue

            # 模式1：过滤率异常高（过滤器频繁改变AI决策）
            if s.filter_rate > self.HIGH_FILTER_RATE:
                patterns.append({
                    "type":    "high_filter_rate",
                    "symbol":  s.symbol,
                    "value":   s.filter_rate,
                    "samples": s.total,
                    "desc":    f"{s.symbol} 过滤率 {s.filter_rate:.0%}（{s.ai_disagree}/{s.total}），"
                               f"过滤器频繁覆盖 AI 决策",
                })

            # 模式2：执行率极低
            if s.exec_rate < self.LOW_EXEC_RATE and s.total >= 10:
                patterns.append({
                    "type":    "low_exec_rate",
                    "symbol":  s.symbol,
                    "value":   s.exec_rate,
                    "samples": s.total,
                    "desc":    f"{s.symbol} 执行率 {s.exec_rate:.0%}（{s.executed}/{s.total}），"
                               f"大量信号被拦截",
                })

            # 模式3：特定 Wyckoff 阶段执行率异常
            for phase, v in s.by_wyckoff.items():
                if v["total"] < self.MIN_SAMPLES or phase == "unknown":
                    continue
                phase_exec_rate = v["exec"] / v["total"]
                if phase_exec_rate > 0.8:
                    patterns.append({
                        "type":    "phase_concentration",
                        "symbol":  s.symbol,
                        "phase":   phase,
                        "value":   phase_exec_rate,
                        "samples": v["total"],
                        "desc":    f"{s.symbol} 在 {phase} 阶段执行率 {phase_exec_rate:.0%}"
                                   f"（{v['exec']}/{v['total']}），集中度过高",
                    })

            # 模式4：pos_zone 分布极度不均
            zone_totals = {z: v["total"] for z, v in s.by_pos_zone.items()
                          if z != "unknown" and v["total"] >= 3}
            if zone_totals:
                max_zone = max(zone_totals, key=zone_totals.get)
                max_pct  = zone_totals[max_zone] / s.total
                if max_pct > 0.7:
                    patterns.append({
                        "type":    "zone_concentration",
                        "symbol":  s.symbol,
                        "zone":    max_zone,
                        "value":   max_pct,
                        "samples": s.total,
                        "desc":    f"{s.symbol} {max_pct:.0%} 信号集中在 {max_zone} 区域",
                    })

        return patterns

    # ── Step 3: 建议生成 ─────────────────────────────────

    def _generate_suggestions(self, stats: list[SymbolStats],
                               patterns: list[dict],
                               period: str) -> list[dict]:
        """
        LLM 分析 → 生成建议。
        LLM 不可用时走规则生成。
        """
        if not patterns:
            return []

        if self.llm:
            return self._llm_suggestions(stats, patterns, period)
        return self._rule_suggestions(patterns)

    def _llm_suggestions(self, stats: list[SymbolStats],
                          patterns: list[dict],
                          period: str) -> list[dict]:
        """LLM 基于统计数据生成建议"""

        # 构建统计摘要
        stats_text = []
        for s in stats:
            stats_text.append(
                f"  {s.symbol}: 总信号{s.total} 执行率{s.exec_rate:.0%} "
                f"过滤率{s.filter_rate:.0%}"
            )

        patterns_text = "\n".join(f"  - {p['desc']}" for p in patterns)

        # 检索现有知识卡作为上下文（RAG）
        card_context = self._retrieve_card_context(stats)

        system = """你是 GCC 进化引擎的分析器，基于真实运行数据生成参数调整建议。

规则：
1. 每条建议必须有具体数据支撑，直接引用统计数字
2. 建议要具体可操作，不要说"考虑优化"这种废话
3. 最多输出 3 条建议，优先高置信度的
4. 不确定的不要瞎猜，直接说"数据不足"
5. 只返回 JSON 数组，不要任何解释

格式：
[
  {
    "subject": "调整对象（如 AMD 过滤器阈值）",
    "description": "具体建议内容",
    "current_value": "当前值（不知道就写unknown）",
    "suggested_value": "建议值",
    "evidence": "支撑数据（直接引用统计数字）",
    "priority": "high/normal/low"
  }
]"""

        user = f"""分析周期：{period}

统计数据：
{chr(10).join(stats_text)}

发现的异常模式：
{patterns_text}

{card_context}

请基于以上数据生成参数调整建议。"""

        try:
            raw = self.llm.generate(system=system, user=user, max_tokens=800, repeat=2)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.warning("[ANALYZER] LLM suggestion generation failed: %s", e)

        return self._rule_suggestions(patterns)

    def _rule_suggestions(self, patterns: list[dict]) -> list[dict]:
        """规则兜底：根据模式直接生成建议"""
        suggestions = []
        for p in patterns[:3]:  # 最多3条
            if p["type"] == "high_filter_rate":
                suggestions.append({
                    "subject":         f"{p['symbol']} 过滤器阈值",
                    "description":     f"过滤率 {p['value']:.0%} 偏高，考虑放宽过滤条件或检查过滤器逻辑",
                    "current_value":   "unknown",
                    "suggested_value": "检查过滤器条件",
                    "evidence":        f"样本 {p['samples']} 条，{p['value']:.0%} 被过滤器覆盖",
                    "priority":        "high" if p["value"] > 0.6 else "normal",
                })
            elif p["type"] == "low_exec_rate":
                suggestions.append({
                    "subject":         f"{p['symbol']} 信号执行条件",
                    "description":     f"执行率 {p['value']:.0%} 过低，大量信号未被执行",
                    "current_value":   "unknown",
                    "suggested_value": "检查入场条件是否过于严格",
                    "evidence":        f"样本 {p['samples']} 条，仅 {p['value']:.0%} 实际执行",
                    "priority":        "normal",
                })
            elif p["type"] == "phase_concentration":
                suggestions.append({
                    "subject":         f"{p['symbol']} {p['phase']} 阶段参数",
                    "description":     f"信号集中在 {p['phase']} 阶段，需确认该阶段策略是否合理",
                    "current_value":   "unknown",
                    "suggested_value": "审查该阶段的入场逻辑",
                    "evidence":        f"样本 {p['samples']} 条，{p['value']:.0%} 集中在此阶段",
                    "priority":        "normal",
                })
        return suggestions

    def _retrieve_card_context(self, stats: list[SymbolStats]) -> str:
        """RAG：检索相关知识卡作为分析上下文"""
        try:
            from .context_chain import ContextChain
            chain = ContextChain(self.gcc_dir)
            symbols = [s.symbol for s in stats[:3]]
            query   = f"分析优化 {' '.join(symbols)} 参数调整"
            result  = chain.retrieve(query)
            if result and result.cards:
                lines = ["相关历史知识卡："]
                for card in result.cards[:3]:
                    title = card.get("title", "")
                    lesson = card.get("lessons_text", "")[:100]
                    if title:
                        lines.append(f"  - {title}: {lesson}")
                return "\n".join(lines)
        except Exception as e:
            logger.warning("[ANALYZER] card context retrieval failed: %s", e)
        return ""

    # ── Step 4: 写入 suggest store ────────────────────────

    def _save_suggestions(self, suggestions: list[dict], key_id: str):
        from .suggest import Suggestion, SuggestStore

        store = SuggestStore(self.gcc_dir)
        for s in suggestions:
            store.add(Suggestion(
                source          = "analyze",
                related_key     = key_id,
                subject         = s.get("subject", ""),
                description     = s.get("description", ""),
                current_value   = s.get("current_value", ""),
                suggested_value = s.get("suggested_value", ""),
                evidence        = s.get("evidence", ""),
                priority        = s.get("priority", "normal"),
            ))

    # ── Step 5: 报告生成 ─────────────────────────────────

    def _build_report(self, result: AnalysisResult) -> str:
        lines = [
            f"# 回溯分析报告",
            f"> 周期: {result.period}  |  起始: {result.since[:16]}  |  "
            f"总信号: {result.total_events}  |  生成: {result.ran_at[:16]}",
            "",
        ]

        if not result.symbols:
            lines.append("> ⚠ 该时间段内无数据")
            return "\n".join(lines)

        # 统计汇总
        lines.append("## 统计汇总")
        lines.append("")
        lines.append("| 标的 | 总信号 | 执行率 | 过滤率 | AI一致率 |")
        lines.append("|------|--------|--------|--------|---------|")
        for s in result.symbols:
            agree_rate = s.ai_agree / s.total if s.total else 0
            lines.append(
                f"| {s.symbol} | {s.total} | {s.exec_rate:.0%} | "
                f"{s.filter_rate:.0%} | {agree_rate:.0%} |"
            )
        lines.append("")

        # 异常模式
        if result.patterns:
            lines.append("## 发现的异常模式")
            lines.append("")
            for p in result.patterns:
                lines.append(f"- **{p['type']}**：{p['desc']}")
            lines.append("")

        # 产生的建议
        if result.suggestions:
            lines.append(f"## 产生建议（{len(result.suggestions)} 条）")
            lines.append("")
            for i, s in enumerate(result.suggestions, 1):
                priority_icon = {"high": "🔴", "normal": "🟡", "low": "⚪"}.get(
                    s.get("priority", "normal"), "🟡")
                lines.append(f"### {priority_icon} #{i} {s.get('subject', '')}")
                lines.append(f"**建议**：{s.get('description', '')}")
                lines.append(f"**证据**：{s.get('evidence', '')}")
                if s.get("suggested_value") and s["suggested_value"] != "unknown":
                    lines.append(f"**建议值**：{s.get('suggested_value', '')}")
                lines.append("")
            lines.append("> 运行 `gcc-evo suggest review` 审核以上建议")
        else:
            lines.append("## 建议")
            lines.append("")
            lines.append("> 数据正常，未发现需要调整的异常模式。")

        return "\n".join(lines)

    def _save_report(self, result: AnalysisResult):
        report_dir = self.gcc_dir / "analysis"
        report_dir.mkdir(exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M")
        path = report_dir / f"analyze_{ts}.md"
        path.write_text(result.report_md, encoding="utf-8")
        result._report_path = str(path)

    # ── 工具 ──────────────────────────────────────────────

    @staticmethod
    def _parse_period(period: str) -> str:
        import re
        m = re.match(r"(\d+)(h|d)", period.lower())
        if not m:
            raise ValueError(f"无效的 period 格式: {period}，使用如 12h / 24h / 7d")
        n, unit = int(m.group(1)), m.group(2)
        delta = timedelta(hours=n) if unit == "h" else timedelta(days=n)
        return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%d %H:%M:%S")

"""
GCC v4.85 — Backtest Store (回撤历史验证系统)

核心设计：
  L1 数据基石 — 没有历史数据，Human Anchor就是主观判断

三个核心引擎：
  1. BacktestStore    — 事件存储+查询，append-only JSONL
  2. CounterfactualEngine — 给定新规则，重跑历史，计算差异
  3. DrawdownAnalyzer — 回撤归因：哪类信号贡献了多少回撤

使用方式：
  store = BacktestStore()
  store.record(TradeEvent(signal="SELL", position="LOW", pnl_pct=-1.8, ...))
  events = store.query(days=7, position="LOW", signal="SELL")
  stats = store.pattern_stats({"position": "LOW", "signal": "SELL"})

  cf = CounterfactualEngine(store)
  result = cf.run(rule={"position": "LOW", "signal": "SELL", "action": "HOLD"}, days=30)

  da = DrawdownAnalyzer(store)
  attr = da.analyze(period_days=14)
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════
# Data Structures
# ════════════════════════════════════════════════════════════

@dataclass
class TradeEvent:
    """
    单次交易事件，通用格式。
    兼容交易系统信号和GCC进化决策。
    """
    event_id: str = ""
    timestamp: str = field(default_factory=_now)
    adapter: str = "TRADING"               # TRADING / GCC / CUSTOM

    # 信号信息
    symbol: str = ""
    signal: str = "HOLD"                   # BUY / SELL / HOLD
    price_position: str = "MID"           # LOW / MID / HIGH / UNKNOWN
    overall_structure: str = ""           # ACCUMULATION / MARKUP / DISTRIBUTION / MARKDOWN
    volume_status: str = "NORMAL"         # NORMAL / SUSPICIOUS / LOW / HIGH

    # 执行结果
    executed: bool = False
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    holding_bars: int = 0
    exit_reason: str = ""                 # STOP_LOSS / TAKE_PROFIT / SIGNAL / TIMEOUT

    # 结果标签
    result: str = "NEUTRAL"              # SUCCESS / FAIL / NEUTRAL
    result_value: float = 0.0            # 量化结果

    # 关联
    anchor_id: str = ""                  # 关联的Human Anchor
    rule_version: str = ""              # 生成此信号时的规则版本
    tags: list[str] = field(default_factory=list)

    # v4.98: event chain字段 (Step 14 — CounterfactualEngine因果链)
    trigger_event: str = ""              # 触发事件 (e.g. "MACD_CROSS_BULL")
    propagation_path: list[str] = field(default_factory=list)  # 传播路径 ["L2→L1→ORDER"]
    final_outcome: str = ""              # 最终结果 (e.g. "WIN_2.3%", "LOSS_-1.1%")

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "adapter": self.adapter,
            "symbol": self.symbol,
            "signal": self.signal,
            "price_position": self.price_position,
            "overall_structure": self.overall_structure,
            "volume_status": self.volume_status,
            "executed": self.executed,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "holding_bars": self.holding_bars,
            "exit_reason": self.exit_reason,
            "result": self.result,
            "result_value": self.result_value,
            "anchor_id": self.anchor_id,
            "rule_version": self.rule_version,
            "tags": self.tags,
            "trigger_event": self.trigger_event,
            "propagation_path": self.propagation_path,
            "final_outcome": self.final_outcome,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TradeEvent":
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__dataclass_fields__})

    def matches(self, filters: dict) -> bool:
        """检查事件是否匹配过滤条件。"""
        for key, val in filters.items():
            if key == "position":
                if self.price_position != val:
                    return False
            elif key == "signal":
                if self.signal != val:
                    return False
            elif key == "symbol":
                if self.symbol != val:
                    return False
            elif key == "result":
                if self.result != val:
                    return False
            elif key == "structure":
                if self.overall_structure != val:
                    return False
            elif key == "tag":
                if val not in self.tags:
                    return False
        return True


@dataclass
class PatternStats:
    """特定模式的历史统计。"""
    pattern: dict = field(default_factory=dict)
    count: int = 0
    win_count: int = 0
    fail_count: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    max_loss: float = 0.0
    total_pnl: float = 0.0
    period_days: int = 0

    def format(self) -> str:
        pattern_str = " + ".join(f"{k}={v}" for k, v in self.pattern.items())
        return (
            f"模式: {pattern_str}\n"
            f"  出现次数: {self.count}  |  过去{self.period_days}天\n"
            f"  胜率: {self.win_rate:.0%}  "
            f"  均值盈亏: {self.avg_pnl:+.1%}  "
            f"  最大单次亏损: {self.max_loss:.1%}\n"
            f"  总盈亏贡献: {self.total_pnl:+.1%}"
        )


@dataclass
class CounterfactualResult:
    """反事实验证结果。"""
    rule: dict = field(default_factory=dict)
    lookback_days: int = 30
    affected_count: int = 0              # 受影响的事件数量
    delta_pnl: float = 0.0              # 预期收益改善
    delta_drawdown: float = 0.0         # 预期回撤改善
    original_pnl: float = 0.0           # 原始总盈亏
    counterfactual_pnl: float = 0.0     # 新规则下总盈亏
    events_changed: list[str] = field(default_factory=list)  # 变更的event_id
    verdict: str = "NEUTRAL"            # IMPROVE / WORSEN / NEUTRAL

    def format(self) -> str:
        rule_str = " + ".join(f"{k}={v}" for k, v in self.rule.items())
        icon = {"IMPROVE": "✅", "WORSEN": "❌", "NEUTRAL": "➖"}.get(
            self.verdict, "➖")
        return (
            f"{icon} 反事实验证: {rule_str}\n"
            f"  影响事件: {self.affected_count}个  |  回溯{self.lookback_days}天\n"
            f"  原始盈亏: {self.original_pnl:+.1%}  →  "
            f"新规则盈亏: {self.counterfactual_pnl:+.1%}\n"
            f"  预期收益改善: {self.delta_pnl:+.1%}  "
            f"  预期回撤改善: {self.delta_drawdown:+.1%}\n"
            f"  结论: {self.verdict}"
        )


@dataclass
class DrawdownAttribution:
    """回撤归因分析结果。"""
    period_days: int = 14
    total_drawdown: float = 0.0
    by_signal: dict[str, float] = field(default_factory=dict)    # BUY/SELL/HOLD → 贡献%
    by_position: dict[str, float] = field(default_factory=dict)  # LOW/MID/HIGH → 贡献%
    by_structure: dict[str, float] = field(default_factory=dict) # 各市场阶段贡献
    top_culprit: str = ""                # 最大回撤贡献模式
    top_culprit_pct: float = 0.0        # 贡献比例

    def format(self) -> str:
        lines = [
            f"【回撤归因】过去{self.period_days}天  总回撤: {self.total_drawdown:.1%}",
            "",
            "按信号类型:",
        ]
        for sig, pct in sorted(self.by_signal.items(), key=lambda x: x[1], reverse=True):
            bar = "█" * int(pct * 20)
            lines.append(f"  {sig:8s}  {bar:20s}  {pct:.0%}")
        lines.append("")
        lines.append("按价格位置:")
        for pos, pct in sorted(self.by_position.items(), key=lambda x: x[1], reverse=True):
            bar = "█" * int(pct * 20)
            lines.append(f"  {pos:8s}  {bar:20s}  {pct:.0%}")
        lines.append("")
        if self.top_culprit:
            lines.append(f"主要根因: {self.top_culprit}  贡献: {self.top_culprit_pct:.0%}")
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════
# BacktestStore — 事件存储与查询
# ════════════════════════════════════════════════════════════

class BacktestStore:
    """
    交易事件历史存储。
    使用 append-only JSONL 格式，支持快速时间范围查询。

    文件: .gcc/backtest/events.jsonl
    """

    EVENTS_FILE = ".gcc/backtest/events.jsonl"
    INDEX_FILE = ".gcc/backtest/index.json"

    def __init__(self, gcc_dir: str | None = None):
        base = Path(gcc_dir or ".")
        self._events_path = base / "gcc" / "backtest" / "events.jsonl"
        # 支持 .gcc/ 前缀
        alt = base / ".gcc" / "backtest" / "events.jsonl"
        if alt.parent.exists() or not self._events_path.parent.exists():
            self._events_path = alt
        self._events_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: TradeEvent) -> TradeEvent:
        """记录一个交易事件。"""
        if not event.event_id:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:20]
            event.event_id = f"evt_{ts}"

        # 自动设置result
        if event.result == "NEUTRAL" and event.pnl_pct != 0:
            event.result = "SUCCESS" if event.pnl_pct > 0 else "FAIL"
            event.result_value = event.pnl_pct

        # 自动打tag
        if event.price_position and event.signal:
            tag = f"{event.price_position}_{event.signal}"
            if tag not in event.tags:
                event.tags.append(tag)

        with open(self._events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        return event

    def query(
        self,
        days: int = 30,
        symbol: str | None = None,
        signal: str | None = None,
        position: str | None = None,
        result: str | None = None,
        structure: str | None = None,
        limit: int = 1000,
    ) -> list[TradeEvent]:
        """按条件查询历史事件。"""
        if not self._events_path.exists():
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filters = {}
        if symbol:
            filters["symbol"] = symbol
        if signal:
            filters["signal"] = signal
        if position:
            filters["position"] = position
        if result:
            filters["result"] = result
        if structure:
            filters["structure"] = structure

        results = []
        with open(self._events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    # 时间过滤
                    ts_str = d.get("timestamp", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts < cutoff:
                                continue
                        except (ValueError, TypeError):
                            pass
                    event = TradeEvent.from_dict(d)
                    if filters and not event.matches(filters):
                        continue
                    results.append(event)
                    if len(results) >= limit:
                        break
                except Exception as e:
                    logger.warning("[BACKTEST_STORE] failed to parse event line: %s", e)
                    continue

        return results

    def pattern_stats(self, pattern: dict, days: int = 30) -> PatternStats:
        """计算特定模式的历史统计。"""
        events = self.query(days=days)
        matched = [e for e in events if e.matches(pattern)]

        if not matched:
            return PatternStats(pattern=pattern, period_days=days)

        wins = [e for e in matched if e.result == "SUCCESS"]
        fails = [e for e in matched if e.result == "FAIL"]
        pnls = [e.pnl_pct for e in matched if e.pnl_pct != 0]

        return PatternStats(
            pattern=pattern,
            count=len(matched),
            win_count=len(wins),
            fail_count=len(fails),
            win_rate=len(wins) / len(matched) if matched else 0.0,
            avg_pnl=sum(pnls) / len(pnls) if pnls else 0.0,
            max_loss=min(pnls) if pnls else 0.0,
            total_pnl=sum(pnls),
            period_days=days,
        )

    def get_total_count(self, days: int = 30) -> int:
        """获取指定时间内的事件总数。"""
        return len(self.query(days=days))


# ════════════════════════════════════════════════════════════
# CounterfactualEngine — 反事实验证
# ════════════════════════════════════════════════════════════

class CounterfactualEngine:
    """
    反事实引擎：给定新规则，重跑历史，计算结果差异。

    用于 Human Anchor 写入前的验证：
      "如果LOW位SELL一律改为HOLD，历史结果会怎样？"
    """

    def __init__(self, store: BacktestStore):
        self._store = store

    def run(
        self,
        rule: dict,
        lookback_days: int = 30,
    ) -> CounterfactualResult:
        """
        运行反事实验证。

        rule格式:
          {"position": "LOW", "signal": "SELL", "action": "HOLD"}
          → 所有LOW位SELL信号改为HOLD（不执行）

          {"signal": "BUY", "volume_status": "SUSPICIOUS", "action": "HOLD"}
          → 所有可疑成交量BUY改为HOLD
        """
        events = self._store.query(days=lookback_days)
        if not events:
            return CounterfactualResult(rule=rule, lookback_days=lookback_days)

        # 分离匹配规则的事件
        match_filter = {k: v for k, v in rule.items() if k != "action"}
        action = rule.get("action", "HOLD")

        affected = [e for e in events if e.matches(match_filter) and e.executed]
        unaffected = [e for e in events if not e.matches(match_filter) or not e.executed]

        # 原始总盈亏
        original_pnl = sum(e.pnl_pct for e in events if e.executed)

        # 反事实：受影响事件按action处理
        counterfactual_pnl = sum(e.pnl_pct for e in unaffected if e.executed)
        if action == "HOLD":
            # HOLD = 不执行 → 盈亏=0
            pass  # 不加affected的pnl
        elif action == "REVERSE":
            # 反向执行
            counterfactual_pnl += sum(-e.pnl_pct for e in affected)
        else:
            # 其他action暂时等同HOLD
            pass

        delta_pnl = counterfactual_pnl - original_pnl

        # 回撤改善（简化：减少的负盈亏）
        affected_losses = [e.pnl_pct for e in affected if e.pnl_pct < 0]
        delta_drawdown = abs(sum(affected_losses)) if affected_losses else 0.0

        verdict = "NEUTRAL"
        if delta_pnl > 0.005:   # 改善超过0.5%
            verdict = "IMPROVE"
        elif delta_pnl < -0.005:
            verdict = "WORSEN"

        return CounterfactualResult(
            rule=rule,
            lookback_days=lookback_days,
            affected_count=len(affected),
            delta_pnl=delta_pnl,
            delta_drawdown=delta_drawdown,
            original_pnl=original_pnl,
            counterfactual_pnl=counterfactual_pnl,
            events_changed=[e.event_id for e in affected],
            verdict=verdict,
        )

    def validate_anchor_rule(
        self,
        constraints: list[str],
        lookback_days: int = 30,
    ) -> list[CounterfactualResult]:
        """
        验证Human Anchor约束列表中的每条规则。
        返回每条规则的反事实结果列表。
        """
        results = []
        for constraint in constraints:
            rule = self._parse_constraint(constraint)
            if rule:
                results.append(self.run(rule, lookback_days=lookback_days))
        return results

    @staticmethod
    def _parse_constraint(text: str) -> dict | None:
        """简单解析约束文本为规则dict。"""
        import re
        text_lower = text.lower()

        # 模式：LOW位SELL → HOLD
        m = re.search(r"(low|high|mid).*?(buy|sell).*?hold", text_lower)
        if m:
            return {
                "position": m.group(1).upper(),
                "signal": m.group(2).upper(),
                "action": "HOLD",
            }

        # 模式：缩量BUY → HOLD
        if "suspicious" in text_lower and "buy" in text_lower:
            return {"volume_status": "SUSPICIOUS", "signal": "BUY", "action": "HOLD"}
        if "suspicious" in text_lower and "sell" in text_lower:
            return {"volume_status": "SUSPICIOUS", "signal": "SELL", "action": "HOLD"}

        return None


# ════════════════════════════════════════════════════════════
# DrawdownAnalyzer — 回撤归因
# ════════════════════════════════════════════════════════════

class DrawdownAnalyzer:
    """
    回撤归因分析器。
    告诉你这次回撤是哪类信号、哪个位置、哪个市场阶段造成的。
    """

    def __init__(self, store: BacktestStore):
        self._store = store

    def analyze(self, period_days: int = 14) -> DrawdownAttribution:
        """分析指定时间段内的回撤归因。"""
        events = self._store.query(days=period_days)
        failed = [e for e in events if e.result == "FAIL" and e.pnl_pct < 0]

        if not failed:
            return DrawdownAttribution(period_days=period_days)

        total_loss = abs(sum(e.pnl_pct for e in failed))

        # 按信号归因
        by_signal: dict[str, float] = {}
        for e in failed:
            key = e.signal or "UNKNOWN"
            by_signal[key] = by_signal.get(key, 0.0) + abs(e.pnl_pct)

        # 按位置归因
        by_position: dict[str, float] = {}
        for e in failed:
            key = e.price_position or "UNKNOWN"
            by_position[key] = by_position.get(key, 0.0) + abs(e.pnl_pct)

        # 按结构归因
        by_structure: dict[str, float] = {}
        for e in failed:
            key = e.overall_structure or "UNKNOWN"
            by_structure[key] = by_structure.get(key, 0.0) + abs(e.pnl_pct)

        # 转为占比
        def to_pct(d: dict) -> dict:
            if total_loss == 0:
                return d
            return {k: v / total_loss for k, v in d.items()}

        by_signal_pct = to_pct(by_signal)
        by_position_pct = to_pct(by_position)
        by_structure_pct = to_pct(by_structure)

        # 找最大贡献者
        top_culprit = ""
        top_pct = 0.0
        for k, v in {**by_signal_pct, **by_position_pct}.items():
            if v > top_pct:
                top_pct = v
                top_culprit = k

        # 寻找最危险的组合模式
        pattern_losses: dict[str, float] = {}
        for e in failed:
            combo = f"{e.price_position}+{e.signal}"
            pattern_losses[combo] = pattern_losses.get(combo, 0.0) + abs(e.pnl_pct)
        if pattern_losses:
            worst_combo = max(pattern_losses, key=pattern_losses.get)
            worst_pct = pattern_losses[worst_combo] / total_loss if total_loss else 0
            if worst_pct > top_pct:
                top_culprit = worst_combo
                top_pct = worst_pct

        return DrawdownAttribution(
            period_days=period_days,
            total_drawdown=total_loss,
            by_signal=by_signal_pct,
            by_position=by_position_pct,
            by_structure=by_structure_pct,
            top_culprit=top_culprit,
            top_culprit_pct=top_pct,
        )

    def generate_report(
        self,
        period_days: int = 14,
        anchor_id: str | None = None,
    ) -> str:
        """生成完整回撤报告，适合人类阅读。"""
        attr = self.analyze(period_days)
        events = self._store.query(days=period_days)
        total_events = len([e for e in events if e.executed])
        fail_events = [e for e in events if e.result == "FAIL" and e.executed]

        lines = [
            f"【回撤归因报告】过去{period_days}天",
            f"总执行信号: {total_events}  失败: {len(fail_events)}  "
            f"失败率: {len(fail_events)/total_events:.0%}" if total_events else "无数据",
            f"总亏损: {attr.total_drawdown:.1%}",
            "",
        ]

        if attr.by_position:
            lines.append("按价格位置归因:")
            for pos, pct in sorted(attr.by_position.items(), key=lambda x: x[1], reverse=True):
                bar = "█" * max(1, int(pct * 15))
                lines.append(f"  {pos:8s}  {bar:15s}  {pct:.0%}")

        lines.append("")
        if attr.by_signal:
            lines.append("按信号方向归因:")
            for sig, pct in sorted(attr.by_signal.items(), key=lambda x: x[1], reverse=True):
                bar = "█" * max(1, int(pct * 15))
                lines.append(f"  {sig:8s}  {bar:15s}  {pct:.0%}")

        lines.append("")
        if attr.top_culprit:
            lines.append(f"最大根因: {attr.top_culprit}  贡献: {attr.top_culprit_pct:.0%}")
            lines.append(f"建议: 重点审查 {attr.top_culprit} 场景的信号过滤逻辑")

        if anchor_id:
            lines.append(f"\n关联Anchor: {anchor_id}")

        return "\n".join(lines)

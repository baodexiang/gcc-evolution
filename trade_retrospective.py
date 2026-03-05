#!/usr/bin/env python3
"""
trade_retrospective.py - 交易回溯分析模块

信号→执行→盈亏全链路分析:
1. 读取signal_decisions.jsonl (Position Control决策记录)
2. 关联trade_history.json (实际执行交易)
3. 分析Position Control通过/拒绝效率
4. 被拒信号假设分析 (如果执行了会怎样)
5. 生成改善建议

运行方式:
  python trade_retrospective.py --period 1d   # 分析过去1天
  python trade_retrospective.py --period 1w   # 分析过去1周
  python trade_retrospective.py --period 1d --save  # 同时保存Markdown

集成方式:
  from trade_retrospective import run_retrospective
  terminal_str, markdown_str = run_retrospective("1d")
"""

import json
import os
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    import pytz
    NY_TZ = pytz.timezone("America/New_York")
except ImportError:
    NY_TZ = None

logger = logging.getLogger("trade_retrospective")

# 文件路径
SIGNAL_DECISIONS_FILE = "logs/signal_decisions.jsonl"
TRADE_HISTORY_FILE = "logs/trade_history.json"
SCAN_SIGNALS_FILE = "scan_signals.json"
PLUGIN_PROFIT_FILE = "plugin_profit_state.json"
RETROSPECTIVE_DIR = "logs/retrospective"

# ANSI颜色 (终端输出用)
C_G, C_GB = "\033[92m", "\033[92;1m"
C_R, C_RB = "\033[91m", "\033[91;1m"
C_Y, C_C, C_M, C_W, C_0 = "\033[93m", "\033[96m", "\033[95m", "\033[97m", "\033[0m"


# ============================================================
# 数据采集层
# ============================================================

def _get_ny_now() -> datetime:
    if NY_TZ:
        return datetime.now(NY_TZ)
    return datetime.now()


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """解析各种时间戳格式"""
    if not ts_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            return datetime.fromisoformat(ts_str) if "T" in ts_str else datetime.strptime(ts_str, fmt)
        except (ValueError, TypeError):
            continue
    # fallback: fromisoformat
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _make_naive(dt: datetime) -> datetime:
    """转换为无时区datetime用于比较"""
    if dt and dt.tzinfo:
        return dt.replace(tzinfo=None)
    return dt


def _load_json_file(fp: str) -> dict:
    """加载JSON文件 (带Windows文件锁重试)"""
    import time
    if not os.path.exists(fp):
        return {}
    for attempt in range(3):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except PermissionError:
            if attempt < 2:
                time.sleep(0.05 * (2 ** attempt))
        except Exception:
            return {}
    return {}


def _load_json_list(fp: str) -> list:
    """加载JSON列表文件"""
    if not os.path.exists(fp):
        return []
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _load_signal_decisions(since: datetime) -> List[dict]:
    """加载JSONL格式的信号决策记录"""
    decisions = []
    if not os.path.exists(SIGNAL_DECISIONS_FILE):
        return decisions
    since_naive = _make_naive(since)
    try:
        with open(SIGNAL_DECISIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = _parse_ts(entry.get("ts", ""))
                    if ts and _make_naive(ts) >= since_naive:
                        entry["_ts"] = _make_naive(ts)
                        decisions.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"读取signal_decisions.jsonl失败: {e}")
    return decisions


def _load_trade_history(since: datetime) -> List[dict]:
    """加载交易历史"""
    all_trades = _load_json_list(TRADE_HISTORY_FILE)
    since_naive = _make_naive(since)
    trades = []
    for t in all_trades:
        ts = _parse_ts(t.get("ts", ""))
        if ts and _make_naive(ts) >= since_naive:
            t["_ts"] = _make_naive(ts)
            trades.append(t)
    return trades


def _load_trigger_history(since: datetime) -> List[dict]:
    """从scan_signals.json提取trigger_history"""
    data = _load_json_file(SCAN_SIGNALS_FILE)
    tracking = data.get("tracking_state", {})
    since_naive = _make_naive(since)
    triggers = []
    for symbol, state in tracking.items():
        for entry in state.get("trigger_history", []):
            ts = _parse_ts(entry.get("time", ""))
            if ts and _make_naive(ts) >= since_naive:
                triggers.append({
                    "symbol": symbol,
                    "action": entry.get("action", ""),
                    "price": entry.get("price", 0),
                    "ts": _make_naive(ts),
                    "trailing_low": entry.get("trailing_low"),
                    "trailing_high": entry.get("trailing_high"),
                })
    triggers.sort(key=lambda x: x["ts"])
    return triggers


def _get_current_price(symbol: str) -> Optional[float]:
    """获取当前价格 (用于假设分析)"""
    try:
        import yfinance as yf
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1h")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


# ============================================================
# 分析层
# ============================================================

def _analyze_signal_chain(decisions: List[dict], trades: List[dict]) -> List[dict]:
    """
    构建信号→执行→盈亏全链路

    对每个PC决策:
    - 如果通过(allowed=True): 关联最近的trade_history执行记录
    - 计算执行后的P&L
    """
    chain = []
    for d in decisions:
        entry = {
            "ts": d.get("_ts") or d.get("ts"),
            "symbol": d.get("symbol", ""),
            "signal_source": d.get("signal_source", ""),
            "action": d.get("action", ""),
            "position": d.get("position", 0),
            "allowed": d.get("allowed", False),
            "target_pos": d.get("target_pos", 0),
            "reason": d.get("reason", ""),
            "price": d.get("price", 0),
            "big_trend": d.get("big_trend", ""),
            "current_trend": d.get("current_trend", ""),
            "exec_price": None,
            "pnl": None,
            "pnl_pct": None,
        }

        # 关联执行记录
        if entry["allowed"] and entry["price"]:
            symbol = entry["symbol"]
            action = entry["action"]
            ts = entry["ts"]
            # 查找时间最近的匹配交易 (±5分钟)
            for t in trades:
                t_ts = t.get("_ts")
                t_sym = t.get("symbol", "")
                t_act = t.get("action", "")
                # symbol可能格式不同 (BTC-USD vs BTCUSDC)
                sym_match = (t_sym == symbol or
                             t_sym.replace("-", "").replace("USD", "USDC") == symbol or
                             symbol.replace("-", "").replace("USD", "USDC") == t_sym)
                if sym_match and t_act == action and t_ts:
                    diff = abs((t_ts - ts).total_seconds()) if isinstance(ts, datetime) else 999
                    if diff < 300:  # 5分钟内
                        entry["exec_price"] = t.get("price", 0)
                        break

        chain.append(entry)

    return chain


def _analyze_position_control(decisions: List[dict]) -> dict:
    """
    Position Control效率分析

    按仓位档位和信号源统计通过/拒绝率
    """
    # 按档位统计
    by_level = defaultdict(lambda: {
        "buy_pass": 0, "buy_reject": 0,
        "sell_pass": 0, "sell_reject": 0,
        "reject_reasons": defaultdict(int),
    })

    # 按信号源统计
    by_source = defaultdict(lambda: {
        "total": 0, "passed": 0, "rejected": 0,
    })

    for d in decisions:
        pos = d.get("position", 0)
        action = d.get("action", "BUY")
        allowed = d.get("allowed", False)
        source = d.get("signal_source", "unknown")
        reason = d.get("reason", "")

        level = by_level[pos]
        if action == "BUY":
            if allowed:
                level["buy_pass"] += 1
            else:
                level["buy_reject"] += 1
                # 提取简短拒绝原因
                short_reason = _extract_short_reason(reason)
                level["reject_reasons"][short_reason] += 1
        else:
            if allowed:
                level["sell_pass"] += 1
            else:
                level["sell_reject"] += 1
                short_reason = _extract_short_reason(reason)
                level["reject_reasons"][short_reason] += 1

        src = by_source[source]
        src["total"] += 1
        if allowed:
            src["passed"] += 1
        else:
            src["rejected"] += 1

    return {"by_level": dict(by_level), "by_source": dict(by_source)}


def _extract_short_reason(reason: str) -> str:
    """从Position Control reason中提取简短拒绝原因"""
    if not reason:
        return "未知"
    # [v20] 仓位X/5 BUY ✗ | 0→1需前一根阳线 | ...
    parts = reason.split("|")
    if len(parts) >= 2:
        return parts[1].strip()
    return reason[:30]


def _analyze_rejected_signals(decisions: List[dict]) -> List[dict]:
    """
    被拒信号假设分析

    对每个被拒信号, 查询后续价格变化, 判断拒绝是否正确
    """
    rejected = [d for d in decisions if not d.get("allowed", True)]
    if not rejected:
        return []

    # 按symbol分组, 批量获取价格
    symbols = set(d.get("symbol", "") for d in rejected)
    current_prices = {}
    for sym in symbols:
        if sym:
            p = _get_current_price(sym)
            if p:
                current_prices[sym] = p

    results = []
    for d in rejected:
        symbol = d.get("symbol", "")
        action = d.get("action", "BUY")
        price = d.get("price", 0)
        current = current_prices.get(symbol)

        entry = {
            "ts": d.get("_ts") or d.get("ts"),
            "symbol": symbol,
            "action": action,
            "reason": _extract_short_reason(d.get("reason", "")),
            "price": price,
            "signal_source": d.get("signal_source", ""),
            "position": d.get("position", 0),
            "current_price": current,
            "hypothetical_pnl_pct": None,
            "correct_rejection": None,
        }

        if price and current and price > 0:
            if action == "BUY":
                pnl_pct = (current - price) / price * 100
            else:
                pnl_pct = (price - current) / price * 100
            entry["hypothetical_pnl_pct"] = round(pnl_pct, 2)
            # 拒绝正确 = 假设执行后亏损
            entry["correct_rejection"] = pnl_pct < 0

        results.append(entry)

    return results


def _generate_suggestions(pc_stats: dict, rejected_analysis: List[dict]) -> List[str]:
    """基于分析结果生成改善建议"""
    suggestions = []

    by_level = pc_stats.get("by_level", {})
    by_source = pc_stats.get("by_source", {})

    # 分析每个档位的拒绝率
    for level, stats in sorted(by_level.items()):
        buy_total = stats["buy_pass"] + stats["buy_reject"]
        sell_total = stats["sell_pass"] + stats["sell_reject"]

        # 高拒绝率档位
        if buy_total > 0:
            reject_rate = stats["buy_reject"] / buy_total
            if reject_rate > 0.7 and buy_total >= 3:
                top_reasons = sorted(stats["reject_reasons"].items(),
                                     key=lambda x: -x[1])[:2]
                reasons_str = ", ".join(f"{r}({c}次)" for r, c in top_reasons)
                suggestions.append(
                    f"仓位{level}→{level+1} BUY: 拒绝率{reject_rate:.0%}({stats['buy_reject']}/{buy_total}), "
                    f"主要原因: {reasons_str}"
                )

        if sell_total > 0:
            reject_rate = stats["sell_reject"] / sell_total
            if reject_rate > 0.7 and sell_total >= 3:
                top_reasons = sorted(stats["reject_reasons"].items(),
                                     key=lambda x: -x[1])[:2]
                reasons_str = ", ".join(f"{r}({c}次)" for r, c in top_reasons)
                suggestions.append(
                    f"仓位{level} SELL: 拒绝率{reject_rate:.0%}({stats['sell_reject']}/{sell_total}), "
                    f"主要原因: {reasons_str}"
                )

    # 分析被拒信号的假设盈亏
    if rejected_analysis:
        wrong_rejections = [r for r in rejected_analysis
                            if r.get("correct_rejection") is False]
        correct_rejections = [r for r in rejected_analysis
                              if r.get("correct_rejection") is True]
        total = len(rejected_analysis)
        analyzed = len(wrong_rejections) + len(correct_rejections)

        if analyzed > 0:
            correct_pct = len(correct_rejections) / analyzed
            if correct_pct < 0.5 and analyzed >= 3:
                suggestions.append(
                    f"被拒信号假设分析: {len(wrong_rejections)}/{analyzed}个拒绝"
                    f"后价格朝信号方向走, PC可能过于保守"
                )
            elif correct_pct > 0.7:
                suggestions.append(
                    f"被拒信号假设分析: {len(correct_rejections)}/{analyzed}个拒绝"
                    f"正确, PC过滤效果良好"
                )

        # 按信号源分析
        source_wrong = defaultdict(int)
        source_total = defaultdict(int)
        for r in rejected_analysis:
            src = r.get("signal_source", "unknown")
            source_total[src] += 1
            if r.get("correct_rejection") is False:
                source_wrong[src] += 1
        for src, wrong in source_wrong.items():
            total_src = source_total[src]
            if total_src >= 2 and wrong / total_src > 0.6:
                suggestions.append(
                    f"信号源'{src}': {wrong}/{total_src}个被拒信号实际可盈利, "
                    f"考虑对该信号源放宽PC条件"
                )

    if not suggestions:
        suggestions.append("当前周期无明显改善点, Position Control运行正常")

    return suggestions


# ============================================================
# 报告层
# ============================================================

def _display_width(s: str) -> int:
    """计算字符串显示宽度 (中文=2)"""
    w = 0
    for c in str(s):
        if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f' or '\uff00' <= c <= '\uffef':
            w += 2
        else:
            w += 1
    return w


def _pad(text: str, width: int) -> str:
    """左对齐填充"""
    text = str(text)
    return text + ' ' * max(0, width - _display_width(text))


def _rpad(text: str, width: int) -> str:
    """右对齐填充"""
    text = str(text)
    return ' ' * max(0, width - _display_width(text)) + text


def _format_pnl(pnl_pct: Optional[float], colored: bool = True) -> str:
    """格式化P&L百分比"""
    if pnl_pct is None:
        return "—"
    if colored:
        if pnl_pct > 0:
            return f"{C_G}+{pnl_pct:.2f}%{C_0}"
        elif pnl_pct < 0:
            return f"{C_R}{pnl_pct:.2f}%{C_0}"
    else:
        if pnl_pct > 0:
            return f"+{pnl_pct:.2f}%"
        elif pnl_pct < 0:
            return f"{pnl_pct:.2f}%"
    return "0.00%"


def _format_terminal(chain: List[dict], pc_stats: dict,
                     rejected_analysis: List[dict], suggestions: List[str],
                     period: str, period_start: datetime) -> str:
    """生成终端彩色报告"""
    lines = []
    w = 80

    # 标题
    period_label = "1天" if period == "1d" else "1周"
    date_str = period_start.strftime("%Y-%m-%d")
    lines.append("")
    lines.append("=" * w)
    lines.append(f" 交易回溯分析  {date_str} ({period_label})  纽约时间")
    lines.append("=" * w)

    # === 信号全链路 ===
    lines.append("")
    lines.append(f"{C_C}─── 信号全链路 ───{C_0}" + "─" * (w - 19))

    if chain:
        lines.append(f" {'时间':<8} {'品种':<10} {'信号源':<14} {'方向':<5} {'仓位':<7} {'PC':<4} {'执行价':<10} {'假设P&L':<10}")
        lines.append("-" * w)
        for c in chain:
            ts_str = c["ts"].strftime("%H:%M") if isinstance(c["ts"], datetime) else str(c["ts"])[:5]
            symbol = str(c["symbol"])[:9]
            source = str(c["signal_source"])[:12]
            action = c["action"]
            pos_str = f"{c['position']}→{c['target_pos']}" if c["allowed"] else f"{c['position']}"
            pc = f"{C_G}✓{C_0}" if c["allowed"] else f"{C_R}✗{C_0}"
            exec_p = f"{c['exec_price']:.2f}" if c.get("exec_price") else "—"
            pnl_str = _format_pnl(c.get("pnl_pct"))

            action_colored = f"{C_G}{action}{C_0}" if action == "BUY" else f"{C_R}{action}{C_0}"
            lines.append(f" {ts_str:<8} {symbol:<10} {source:<14} {action_colored:<14} {pos_str:<7} {pc:<13} {exec_p:<10} {pnl_str}")
    else:
        lines.append(f" {C_Y}(无信号决策记录 — 请确认signal_decisions.jsonl已启用){C_0}")

    # === Position Control效率 ===
    lines.append("")
    lines.append(f"{C_C}─── Position Control效率 ───{C_0}" + "─" * (w - 28))

    by_level = pc_stats.get("by_level", {})
    if by_level:
        lines.append(f" {'档位':<6} {'BUY✓':>6} {'BUY✗':>6} {'SELL✓':>7} {'SELL✗':>7}  {'主要拒绝原因'}")
        lines.append("-" * w)
        for level in sorted(by_level.keys()):
            stats = by_level[level]
            bp = stats["buy_pass"] or "—"
            br = stats["buy_reject"] or "—"
            sp = stats["sell_pass"] or "—"
            sr = stats["sell_reject"] or "—"
            top_reasons = sorted(stats["reject_reasons"].items(), key=lambda x: -x[1])[:2]
            reasons = ", ".join(f"{r}({c})" for r, c in top_reasons) if top_reasons else "—"
            lines.append(f" {level:<6} {str(bp):>6} {str(br):>6} {str(sp):>7} {str(sr):>7}  {reasons}")
    else:
        lines.append(f" {C_Y}(无数据){C_0}")

    # 按信号源
    by_source = pc_stats.get("by_source", {})
    if by_source:
        lines.append("")
        lines.append(f" {'信号源':<16} {'总数':>5} {'通过':>5} {'拒绝':>5} {'通过率':>7}")
        lines.append("-" * w)
        for src in sorted(by_source.keys()):
            s = by_source[src]
            total = s["total"]
            rate = f"{s['passed']/total:.0%}" if total > 0 else "—"
            lines.append(f" {src:<16} {total:>5} {s['passed']:>5} {s['rejected']:>5} {rate:>7}")

    # === 被拒信号假设分析 ===
    lines.append("")
    lines.append(f"{C_C}─── 被拒信号假设分析 ───{C_0}" + "─" * (w - 24))

    if rejected_analysis:
        analyzed = [r for r in rejected_analysis if r.get("hypothetical_pnl_pct") is not None]
        if analyzed:
            lines.append(f" {'时间':<8} {'品种':<10} {'方向':<5} {'拒绝原因':<20} {'拒绝价':>10} {'当前价':>10} {'判断'}")
            lines.append("-" * w)
            for r in analyzed:
                ts_str = r["ts"].strftime("%H:%M") if isinstance(r["ts"], datetime) else str(r["ts"])[:5]
                symbol = str(r["symbol"])[:9]
                action = r["action"]
                reason = str(r["reason"])[:18]
                price = f"{r['price']:.2f}" if r.get("price") else "—"
                current = f"{r['current_price']:.2f}" if r.get("current_price") else "—"
                pnl = r.get("hypothetical_pnl_pct", 0)
                if r.get("correct_rejection") is True:
                    judgment = f"{C_G}✓ 正确拒绝{C_0}"
                elif r.get("correct_rejection") is False:
                    judgment = f"{C_R}✗ 错过{_format_pnl(pnl, False)}{C_0}"
                else:
                    judgment = "—"
                lines.append(f" {ts_str:<8} {symbol:<10} {action:<5} {reason:<20} {price:>10} {current:>10} {judgment}")
        else:
            lines.append(f" {C_Y}(无法获取当前价格进行假设分析){C_0}")
    else:
        lines.append(f" {C_Y}(无被拒信号){C_0}")

    # === 改善建议 ===
    lines.append("")
    lines.append(f"{C_C}─── 改善建议 ───{C_0}" + "─" * (w - 16))
    for i, s in enumerate(suggestions, 1):
        lines.append(f" {i}. {s}")

    lines.append("=" * w)
    lines.append("")

    return "\n".join(lines)


def _format_markdown(chain: List[dict], pc_stats: dict,
                     rejected_analysis: List[dict], suggestions: List[str],
                     period: str, period_start: datetime) -> str:
    """生成Markdown报告"""
    lines = []
    period_label = "1天" if period == "1d" else "1周"
    date_str = period_start.strftime("%Y-%m-%d")
    now_str = _get_ny_now().strftime("%Y-%m-%d %H:%M")

    lines.append(f"# 交易回溯分析 {date_str} ({period_label})")
    lines.append(f"")
    lines.append(f"> 生成时间: {now_str} 纽约时间")
    lines.append(f"")

    # === 信号全链路 ===
    lines.append(f"## 信号全链路")
    lines.append(f"")
    if chain:
        lines.append(f"| 时间 | 品种 | 信号源 | 方向 | 仓位 | PC | 执行价 |")
        lines.append(f"|------|------|--------|------|------|----|--------|")
        for c in chain:
            ts_str = c["ts"].strftime("%H:%M") if isinstance(c["ts"], datetime) else str(c["ts"])[:5]
            pos_str = f"{c['position']}→{c['target_pos']}" if c["allowed"] else f"{c['position']}"
            pc = "✓" if c["allowed"] else "✗"
            exec_p = f"{c['exec_price']:.2f}" if c.get("exec_price") else "—"
            lines.append(f"| {ts_str} | {c['symbol']} | {c['signal_source']} | {c['action']} | {pos_str} | {pc} | {exec_p} |")
    else:
        lines.append(f"*无信号决策记录 — 请确认signal_decisions.jsonl已启用*")
    lines.append(f"")

    # === Position Control效率 ===
    lines.append(f"## Position Control效率")
    lines.append(f"")
    lines.append(f"### 按档位")
    lines.append(f"")

    by_level = pc_stats.get("by_level", {})
    if by_level:
        lines.append(f"| 档位 | BUY✓ | BUY✗ | SELL✓ | SELL✗ | 主要拒绝原因 |")
        lines.append(f"|------|------|------|-------|-------|-------------|")
        for level in sorted(by_level.keys()):
            stats = by_level[level]
            bp = stats["buy_pass"] or "—"
            br = stats["buy_reject"] or "—"
            sp = stats["sell_pass"] or "—"
            sr = stats["sell_reject"] or "—"
            top_reasons = sorted(stats["reject_reasons"].items(), key=lambda x: -x[1])[:2]
            reasons = ", ".join(f"{r}({c})" for r, c in top_reasons) if top_reasons else "—"
            lines.append(f"| {level} | {bp} | {br} | {sp} | {sr} | {reasons} |")

    by_source = pc_stats.get("by_source", {})
    if by_source:
        lines.append(f"")
        lines.append(f"### 按信号源")
        lines.append(f"")
        lines.append(f"| 信号源 | 总数 | 通过 | 拒绝 | 通过率 |")
        lines.append(f"|--------|------|------|------|--------|")
        for src in sorted(by_source.keys()):
            s = by_source[src]
            total = s["total"]
            rate = f"{s['passed']/total:.0%}" if total > 0 else "—"
            lines.append(f"| {src} | {total} | {s['passed']} | {s['rejected']} | {rate} |")
    lines.append(f"")

    # === 被拒信号假设分析 ===
    lines.append(f"## 被拒信号假设分析")
    lines.append(f"")
    analyzed = [r for r in rejected_analysis if r.get("hypothetical_pnl_pct") is not None]
    if analyzed:
        lines.append(f"| 时间 | 品种 | 方向 | 拒绝原因 | 拒绝价 | 当前价 | 假设P&L | 判断 |")
        lines.append(f"|------|------|------|----------|--------|--------|---------|------|")
        for r in analyzed:
            ts_str = r["ts"].strftime("%H:%M") if isinstance(r["ts"], datetime) else str(r["ts"])[:5]
            price = f"{r['price']:.2f}" if r.get("price") else "—"
            current = f"{r['current_price']:.2f}" if r.get("current_price") else "—"
            pnl_str = _format_pnl(r.get("hypothetical_pnl_pct"), colored=False)
            judgment = "✓ 正确拒绝" if r.get("correct_rejection") else "✗ 错过"
            lines.append(f"| {ts_str} | {r['symbol']} | {r['action']} | {r['reason'][:18]} | {price} | {current} | {pnl_str} | {judgment} |")
    else:
        lines.append(f"*无被拒信号或无法获取当前价格*")
    lines.append(f"")

    # === 改善建议 ===
    lines.append(f"## 改善建议")
    lines.append(f"")
    for i, s in enumerate(suggestions, 1):
        lines.append(f"{i}. {s}")
    lines.append(f"")

    # === 统计摘要 ===
    total_decisions = len(chain)
    total_passed = sum(1 for c in chain if c["allowed"])
    total_rejected = total_decisions - total_passed
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"**统计**: 共{total_decisions}个信号决策, "
                 f"通过{total_passed}({total_passed/total_decisions:.0%}), "
                 f"拒绝{total_rejected}({total_rejected/total_decisions:.0%})"
                 if total_decisions > 0 else "**统计**: 无信号决策记录")
    lines.append(f"")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================

def run_retrospective(period: str = "1d") -> Tuple[str, str]:
    """
    运行回溯分析

    Args:
        period: "1d" (过去1天) 或 "1w" (过去1周)

    Returns:
        (terminal_report, markdown_report)
    """
    now = _get_ny_now()
    if period == "1w":
        since = now - timedelta(days=7)
    else:
        since = now - timedelta(days=1)

    since_naive = _make_naive(since)

    # 数据采集
    decisions = _load_signal_decisions(since_naive)
    trades = _load_trade_history(since_naive)
    triggers = _load_trigger_history(since_naive)

    # 分析
    chain = _analyze_signal_chain(decisions, trades)
    pc_stats = _analyze_position_control(decisions)
    rejected_analysis = _analyze_rejected_signals(decisions)
    suggestions = _generate_suggestions(pc_stats, rejected_analysis)

    # 报告生成
    terminal = _format_terminal(chain, pc_stats, rejected_analysis, suggestions, period, since_naive)
    markdown = _format_markdown(chain, pc_stats, rejected_analysis, suggestions, period, since_naive)

    return terminal, markdown


def cleanup_old_decisions(days: int = 7):
    """清理超过N天的决策记录"""
    if not os.path.exists(SIGNAL_DECISIONS_FILE):
        return
    cutoff = _make_naive(_get_ny_now() - timedelta(days=days))
    kept = []
    try:
        with open(SIGNAL_DECISIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = _parse_ts(entry.get("ts", ""))
                    if ts and _make_naive(ts) >= cutoff:
                        kept.append(line)
                except json.JSONDecodeError:
                    continue
        # 原子写回
        tmp = SIGNAL_DECISIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
        os.replace(tmp, SIGNAL_DECISIONS_FILE)
        logger.info(f"清理signal_decisions.jsonl: 保留{len(kept)}条 (最近{days}天)")
    except Exception as e:
        logger.warning(f"清理signal_decisions失败: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="交易回溯分析")
    parser.add_argument("--period", default="1d", choices=["1d", "1w"],
                        help="分析周期: 1d=过去1天, 1w=过去1周")
    parser.add_argument("--save", action="store_true",
                        help="保存Markdown报告到logs/retrospective/")
    args = parser.parse_args()

    terminal, markdown = run_retrospective(args.period)
    print(terminal)

    if args.save:
        os.makedirs(RETROSPECTIVE_DIR, exist_ok=True)
        date_str = _get_ny_now().strftime("%Y%m%d")
        prefix = "weekly" if args.period == "1w" else "daily"
        filepath = os.path.join(RETROSPECTIVE_DIR, f"{prefix}_{date_str}.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"报告已保存: {filepath}")

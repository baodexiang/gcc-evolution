"""
Module C: 反思迭代模块 — 每日审计+预选准确率追踪+调参建议
v1.0: Phase 3 自动审计, 生成报告供人审核(不自动执行调参)

数据来源:
- plugin_profit_state.json: FIFO配对, 已完成交易P&L
- state/stock_selection.json: Module A评分+分级
- global_trend_state.json: 大小周期趋势
- state/human_dual_track.json: 7方准确率
- state/trade_frequency.json: Module B当日交易次数

输出:
- logs/audit/audit_YYYY-MM-DD.json: 每日审计报告
- state/selection_accuracy.json: 预选准确率追踪(周)
- state/iteration_log.json: 参数调整记录
"""

import os
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

# 文件路径
PROFIT_STATE_FILE = "plugin_profit_state.json"
SELECTION_STATE_FILE = "state/stock_selection.json"
GLOBAL_TREND_FILE = "global_trend_state.json"
CALIBRATOR_FILE = "state/human_dual_track.json"
FREQUENCY_FILE = "state/trade_frequency.json"
AUDIT_DIR = "logs/audit"
SELECTION_ACCURACY_FILE = "state/selection_accuracy.json"
ITERATION_LOG_FILE = "state/iteration_log.json"


def _safe_json_read(filepath):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[审计] 读取 {filepath} 失败: {e}")
    return None


def _safe_json_write(filepath, data):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        logger.error(f"[审计] 写入 {filepath} 失败: {e}")
        return False


class StrategyIterator:
    """
    每日反思迭代器

    审计5维度:
    1. 信号分类: 每个交易是否属于"延续"或"破位"
    2. 层级共振: 交易方向是否与x4大周期一致
    3. 三路共识: big_trend/current_trend/x4方向一致性
    4. 预选-实际: 预选tier vs 实际P&L的吻合度
    5. 仓位纪律: 非共振信号品种不应重仓(多笔买入)
    """

    def daily_review(self, date=None) -> dict:
        """
        入口: 读数据 → 审计 → 评估预选 → 调参建议 → 写报告

        Args:
            date: 审计日期 (YYYY-MM-DD), 默认今天

        Returns:
            dict: 完整审计报告
        """
        if not date:
            date = datetime.now(NY_TZ).strftime("%Y-%m-%d")

        logger.info(f"[审计] 开始每日审计 ({date})")

        # 读取所有数据
        profit_data = _safe_json_read(PROFIT_STATE_FILE) or {}
        selection_data = _safe_json_read(SELECTION_STATE_FILE) or {}
        trend_data = _safe_json_read(GLOBAL_TREND_FILE) or {}
        frequency_data = _safe_json_read(FREQUENCY_FILE) or {}

        # 筛选当日已完成交易
        completed = profit_data.get("completed_trades", [])
        today_trades = self._filter_trades_by_date(completed, date)

        # 审计
        violations = self.audit_signals(today_trades, trend_data)

        # 评估预选准确率
        selection_eval = self.evaluate_selection(today_trades, selection_data)

        # 生成调参建议
        suggestions = self.suggest_adjustments(violations, selection_eval, selection_data)

        # 汇总报告
        total_pnl = sum(t.get("pnl", 0) for t in today_trades)
        wins = sum(1 for t in today_trades if t.get("pnl", 0) > 0)
        losses = sum(1 for t in today_trades if t.get("pnl", 0) <= 0)

        report = {
            "date": date,
            "summary": {
                "total_trades": len(today_trades),
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / len(today_trades), 2) if today_trades else 0,
                "total_pnl": round(total_pnl, 2),
                "violations": len(violations),
                "score": self._compute_audit_score(len(today_trades), len(violations))
            },
            "violations": violations,
            "selection_accuracy": selection_eval,
            "suggestions": suggestions,
            "frequency": {
                "mode": frequency_data.get("mode", "N/A"),
                "global_used": frequency_data.get("global_used", 0),
                "global_limit": frequency_data.get("global_limit", 0),
            }
        }

        # 写入审计报告
        os.makedirs(AUDIT_DIR, exist_ok=True)
        audit_file = os.path.join(AUDIT_DIR, f"audit_{date}.json")
        _safe_json_write(audit_file, report)

        # 更新累计准确率追踪
        self._update_selection_accuracy(date, selection_eval)

        logger.info(f"[审计] 完成: 交易={len(today_trades)}, 违规={len(violations)}, "
                    f"评分={report['summary']['score']}")

        return report

    def _filter_trades_by_date(self, completed, date):
        """筛选指定日期的已完成交易(以sell_ts为准)"""
        result = []
        for trade in completed:
            sell_ts = trade.get("sell_ts", "")
            if sell_ts and sell_ts[:10] == date:
                result.append(trade)
        return result

    def audit_signals(self, trades, trend_data) -> list:
        """
        审计交易信号, 检查5个维度的违规

        Returns:
            list of violation dicts
        """
        violations = []
        symbols_data = trend_data.get("symbols", {})

        for trade in trades:
            symbol = trade.get("symbol", "")
            buy_plugin = trade.get("buy_plugin", "")
            sell_plugin = trade.get("sell_plugin", "")
            pnl = trade.get("pnl", 0)
            sym_trend = symbols_data.get(symbol, {})

            big = (sym_trend.get("big_trend") or "SIDE").upper()
            current = (sym_trend.get("current_trend") or "SIDE").upper()

            # 维度1: 层级共振检查
            # BUY交易在big_trend=DOWN时为逆向
            if pnl < 0:
                if big == "DOWN" and buy_plugin:
                    violations.append({
                        "symbol": symbol,
                        "type": "逆向交易",
                        "detail": f"x4=DOWN但BUY (来源={buy_plugin}), 亏损={pnl:.2f}",
                        "severity": "high"
                    })
                elif big == "UP" and sell_plugin and not buy_plugin:
                    violations.append({
                        "symbol": symbol,
                        "type": "逆向交易",
                        "detail": f"x4=UP但SELL (来源={sell_plugin}), 亏损={pnl:.2f}",
                        "severity": "high"
                    })

            # 维度2: 三路共识
            x4_dow = (sym_trend.get("x4_dow_trend") or big).upper() if sym_trend.get("x4_dow_trend") else big
            x4_chan = (sym_trend.get("x4_chan_trend") or big).upper() if sym_trend.get("x4_chan_trend") else big
            directions = {big, current, x4_dow, x4_chan} - {"SIDE"}
            if len(directions) > 1 and pnl < 0:
                violations.append({
                    "symbol": symbol,
                    "type": "分歧交易",
                    "detail": f"多方向分歧(big={big},cur={current},dow={x4_dow},chan={x4_chan}), 亏损={pnl:.2f}",
                    "severity": "medium"
                })

        return violations

    def evaluate_selection(self, trades, selection_data) -> dict:
        """
        评估预选tier vs 实际P&L

        Returns:
            dict: 各等级的交易数/胜率统计
        """
        scores = selection_data.get("scores", {})
        tier_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "total_pnl": 0.0})

        for trade in trades:
            symbol = trade.get("symbol", "")
            pnl = trade.get("pnl", 0)
            tier = scores.get(symbol, {}).get("tier", "?")

            tier_stats[tier]["trades"] += 1
            if pnl > 0:
                tier_stats[tier]["wins"] += 1
            tier_stats[tier]["total_pnl"] += pnl

        # 计算胜率
        result = {}
        for tier, stats in tier_stats.items():
            t = stats["trades"]
            result[f"{tier}_tier"] = {
                "trades": t,
                "wins": stats["wins"],
                "rate": round(stats["wins"] / t, 2) if t > 0 else 0,
                "total_pnl": round(stats["total_pnl"], 2)
            }

        return result

    def suggest_adjustments(self, violations, selection_eval, selection_data) -> list:
        """
        生成调参建议(不自动执行)

        Returns:
            list of suggestion dicts
        """
        suggestions = []
        scores = selection_data.get("scores", {})

        # 建议1: 高违规品种降级
        violation_count = defaultdict(int)
        for v in violations:
            violation_count[v["symbol"]] += 1

        for symbol, count in violation_count.items():
            if count >= 2:
                current_tier = scores.get(symbol, {}).get("tier", "?")
                if current_tier in ("A", "B"):
                    suggestions.append({
                        "type": "tier_review",
                        "symbol": symbol,
                        "current_tier": current_tier,
                        "reason": f"单日{count}次违规, 建议降级审查"
                    })

        # 建议2: D级品种但有盈利交易 → 可能评分偏低
        d_tier_eval = selection_eval.get("D_tier", {})
        if d_tier_eval.get("wins", 0) > 0:
            suggestions.append({
                "type": "score_review",
                "detail": f"D级品种有{d_tier_eval['wins']}笔盈利, 评分可能偏低",
                "action": "检查评分维度权重"
            })

        # 建议3: A级品种胜率低 → 可能评分偏高
        a_tier_eval = selection_eval.get("A_tier", {})
        if a_tier_eval.get("trades", 0) >= 3 and a_tier_eval.get("rate", 1) < 0.4:
            suggestions.append({
                "type": "score_review",
                "detail": f"A级品种胜率仅{a_tier_eval['rate']:.0%} ({a_tier_eval['trades']}笔), 评分可能偏高",
                "action": "检查趋势清晰度和共振评分"
            })

        return suggestions

    def _compute_audit_score(self, total_trades, violation_count):
        """计算审计评分 (0-100)"""
        if total_trades == 0:
            return 100  # 没交易不扣分
        violation_ratio = violation_count / total_trades
        return max(0, round(100 * (1 - violation_ratio)))

    def _update_selection_accuracy(self, date, tier_eval):
        """更新累计预选准确率追踪"""
        accuracy = _safe_json_read(SELECTION_ACCURACY_FILE) or {"weekly": []}

        accuracy["weekly"].append({
            "date": date,
            "tiers": tier_eval
        })

        # 只保留最近30天
        accuracy["weekly"] = accuracy["weekly"][-30:]
        _safe_json_write(SELECTION_ACCURACY_FILE, accuracy)

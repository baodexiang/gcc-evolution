"""
plugin_profit_tracker.py - 外挂利润分析追踪模块

FIFO匹配法追踪所有外挂的P&L:
- BUY执行 → 追加到 open_entries[symbol] 队列
- SELL执行 → FIFO弹出最早的BUY条目，计算P&L → 归因给买入外挂
- 所有外挂信号(无论是否执行)都计入信号统计
- 统计按 asset_type (crypto/stock) 分开
- P&L = (sell_price - buy_price) * quantity (实际美元盈亏)

状态持久化到 plugin_profit_state.json (原子写入)
"""

import json
import os
import threading
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytz

NY_TZ = pytz.timezone("America/New_York")
STATE_FILE = os.path.join("state", "plugin_profit_state.json")
GOVERNANCE_FILE = os.path.join("state", "plugin_governance_actions.json")

# 每笔交易的数量配置 (与主程序 CryptoConfig.PAIRS / USStockConfig.STOCKS 保持同步)
# crypto: unit_size (每次交易的币数量)
# stock: quantity (每次交易的股数)
QUANTITY_MAP = {
    # 加密货币 (主程序符号)
    "BTCUSDC": 0.025,
    "ETHUSDC": 1.0,
    "SOLUSDC": 10.0,
    "ZECUSDC": 5.0,
    # 加密货币 (扫描引擎符号 yfinance格式)
    "BTC-USD": 0.025,
    "ETH-USD": 1.0,
    "SOL-USD": 10.0,
    "ZEC-USD": 5.0,
    # 美股
    "CRWV": 50,
    "TSLA": 10,
    "NBIS": 40,
    "RDDT": 20,
    "OPEN": 50,
    "HIMS": 50,
    "AMD": 20,
    "COIN": 10,
    "RKLB": 20,
    "ONDS": 100,
    "PLTR": 20,
}

_EMPTY_PLUGIN_STATS = {
    "total_signals": 0,
    "executed_signals": 0,
    "buy_count": 0,
    "sell_count": 0,
    "as_buyer_pnl": 0.0,
    "as_buyer_wins": 0,
    "as_buyer_losses": 0,
    "as_seller_count": 0,
}

_EMPTY_DAILY_STATS = {"signals": 0, "executed": 0, "buy": 0, "sell": 0, "pnl": 0.0}


def _get_ny_now() -> datetime:
    return datetime.now(NY_TZ)


def _today_ny() -> str:
    return _get_ny_now().strftime("%Y-%m-%d")


class PluginProfitTracker:
    """外挂利润追踪器 (线程安全, 原子持久化, 按资产类型分开统计)"""

    def __init__(self, state_file: str = STATE_FILE):
        self._state_file = state_file
        state_dir = os.path.dirname(os.path.abspath(self._state_file))
        os.makedirs(state_dir, exist_ok=True)
        self._lock = threading.Lock()
        self.state = self._load_state()
        self._migrate_quantity_pnl()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        symbol: str,
        plugin_name: str,
        action: str,
        price: float,
        executed: bool,
        asset_type: str = "crypto",
        quantity: Optional[float] = None,
        source: Optional[str] = None,
    ) -> Optional[dict]:
        """记录一次外挂信号。

        asset_type: "crypto" 或 "stock"
        quantity: 交易数量 (crypto=币数量, stock=股数). None时自动从QUANTITY_MAP查找.
        无论是否执行都计入信号统计。
        executed=True 且 action=BUY → 追加 open_entries
        executed=True 且 action=SELL → FIFO匹配计算P&L
        返回匹配到的 completed_trade (仅SELL匹配时), 否则 None。
        """
        if quantity is None:
            quantity = QUANTITY_MAP.get(symbol, 1.0)
        with self._lock:
            today = _today_ny()
            now_iso = _get_ny_now().isoformat()
            source = source or plugin_name

            # --- 累计统计 (按 asset_type 分层) ---
            stats = (
                self.state.setdefault("plugin_stats", {})
                .setdefault(asset_type, {})
                .setdefault(plugin_name, dict(_EMPTY_PLUGIN_STATS))
            )
            stats["total_signals"] += 1

            # --- 每日统计 (按 asset_type 分层) ---
            daily = (
                self.state.setdefault("daily_stats", {})
                .setdefault(today, {})
                .setdefault(asset_type, {})
                .setdefault(plugin_name, dict(_EMPTY_DAILY_STATS))
            )
            daily["signals"] += 1

            if not executed:
                self._save_state()
                return None

            stats["executed_signals"] += 1
            daily["executed"] += 1

            completed = None

            if action.upper() == "BUY":
                stats["buy_count"] += 1
                daily["buy"] += 1
                entries = self.state.setdefault("open_entries", {}).setdefault(
                    symbol, []
                )
                entries.append(
                    {
                        "plugin": plugin_name,
                        "source": source,
                        "price": price,
                        "quantity": quantity,
                        "ts": now_iso,
                        "asset_type": asset_type,
                    }
                )

            elif action.upper() == "SELL":
                stats["sell_count"] += 1
                daily["sell"] += 1
                stats["as_seller_count"] += 1
                completed = self._match_sell(
                    symbol, plugin_name, source, price, now_iso, asset_type
                )
                if completed:
                    # 归因给买入外挂 (使用买入时的 asset_type)
                    buy_plugin = completed["buy_plugin"]
                    buy_asset = completed.get("asset_type", asset_type)
                    buy_stats = (
                        self.state["plugin_stats"]
                        .setdefault(buy_asset, {})
                        .setdefault(buy_plugin, dict(_EMPTY_PLUGIN_STATS))
                    )
                    pnl = completed["pnl"]
                    buy_stats["as_buyer_pnl"] += pnl
                    if pnl > 0:
                        buy_stats["as_buyer_wins"] += 1
                    else:
                        buy_stats["as_buyer_losses"] += 1

                    # 每日P&L也归因给买入外挂
                    buy_daily = (
                        self.state.setdefault("daily_stats", {})
                        .setdefault(today, {})
                        .setdefault(buy_asset, {})
                        .setdefault(buy_plugin, dict(_EMPTY_DAILY_STATS))
                    )
                    buy_daily["pnl"] += pnl

            self.state["updated_at"] = now_iso
            self.state["quality_snapshot"] = self._compute_quality_snapshot_from_state()
            self._save_state()
            self._save_governance_actions(now_iso, self.state["quality_snapshot"])
            return completed

    def get_summary(self) -> dict:
        """返回所有外挂汇总统计 (按asset_type分层)。"""
        with self._lock:
            return dict(self.state.get("plugin_stats", {}))

    def get_daily_summary(self, date_str: Optional[str] = None) -> dict:
        """返回指定日期的汇总 (按asset_type分层)。默认今天。"""
        with self._lock:
            if date_str is None:
                date_str = _today_ny()
            return dict(self.state.get("daily_stats", {}).get(date_str, {}))

    def get_open_entries(self) -> dict:
        """返回所有持仓中的open_entries。"""
        with self._lock:
            return {
                sym: list(entries)
                for sym, entries in self.state.get("open_entries", {}).items()
                if entries
            }

    def generate_daily_report(self, date_str: str) -> Tuple[str, dict]:
        """生成指定日期的日报 → (txt_content, json_data)。"""
        with self._lock:
            daily_all = self.state.get("daily_stats", {}).get(date_str, {})
            cumulative_all = self.state.get("plugin_stats", {})
            completed = self.state.get("completed_trades", [])

            # --- 筛选当日完成的交易 ---
            day_trades = [
                t for t in completed if t.get("sell_ts", "").startswith(date_str)
            ]

            ny_now = _get_ny_now()

            # --- JSON数据 ---
            json_data = {
                "date": date_str,
                "generated_at": ny_now.isoformat(),
                "daily_stats": daily_all,
                "cumulative_stats": cumulative_all,
                "day_trades": day_trades,
                "quality_snapshot": self.compute_quality_snapshot(),
            }

            # --- TXT报告 ---
            W = 78
            lines = [
                "=" * W,
                f"  外挂利润分析日报",
                "=" * W,
                f"  统计日期: {date_str}",
                f"  生成时间: {ny_now.strftime('%Y-%m-%d %H:%M:%S')} (纽约时间)",
                "",
            ]

            grand_sig = 0
            grand_exec = 0
            grand_closed = 0
            grand_wins = 0
            grand_pnl = 0.0

            for atype, atype_label in [("crypto", "加密货币"), ("stock", "美股")]:
                daily = daily_all.get(atype, {})
                cumulative = cumulative_all.get(atype, {})
                if not daily and not cumulative:
                    continue

                lines.append("-" * W)
                lines.append(f"  {atype_label}")
                lines.append("-" * W)
                lines.append(
                    f"  {'外挂名':<18s}| {'今日信号':>8s}| {'今日执行':>8s}"
                    f"| {'累计已平仓':>10s}| {'胜率':>7s}| {'累计盈亏':>12s}"
                )
                lines.append("  " + "-" * (W - 2))

                all_plugins = sorted(
                    set(list(daily.keys()) + list(cumulative.keys()))
                )

                sub_sig = sub_exec = sub_closed = sub_wins = 0
                sub_pnl = 0.0

                for pname in all_plugins:
                    d = daily.get(pname, {})
                    c = cumulative.get(pname, {})
                    t_sig = d.get("signals", 0)
                    t_exec = d.get("executed", 0)
                    wins = c.get("as_buyer_wins", 0)
                    losses = c.get("as_buyer_losses", 0)
                    closed = wins + losses
                    wr = f"{wins / closed * 100:.1f}%" if closed > 0 else "-"
                    pnl = c.get("as_buyer_pnl", 0.0)
                    pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"

                    lines.append(
                        f"  {pname:<18s}| {t_sig:>8d}| {t_exec:>8d}"
                        f"| {closed:>10d}| {wr:>7s}| {pnl_str:>12s}"
                    )
                    sub_sig += t_sig
                    sub_exec += t_exec
                    sub_closed += closed
                    sub_wins += wins
                    sub_pnl += pnl

                lines.append("  " + "-" * (W - 2))
                sub_wr = (
                    f"{sub_wins / sub_closed * 100:.1f}%"
                    if sub_closed > 0 else "-"
                )
                sub_pnl_str = (
                    f"+${sub_pnl:,.2f}" if sub_pnl >= 0 else f"-${abs(sub_pnl):,.2f}"
                )
                lines.append(
                    f"  {atype_label + '小计':<18s}| {sub_sig:>8d}| {sub_exec:>8d}"
                    f"| {sub_closed:>10d}| {sub_wr:>7s}| {sub_pnl_str:>12s}"
                )
                lines.append("")

                grand_sig += sub_sig
                grand_exec += sub_exec
                grand_closed += sub_closed
                grand_wins += sub_wins
                grand_pnl += sub_pnl

            # 质量评分排名 (KEY-004-T01)
            quality_snapshot = json_data.get("quality_snapshot", {})
            if quality_snapshot:
                lines.append("-")
                lines.append("  外挂品质评分排名 (KEY-004, 0-100)")
                lines.append("-" * W)
                for atype, atype_label in [("crypto", "加密货币"), ("stock", "美股")]:
                    rows = quality_snapshot.get(atype, [])
                    if not rows:
                        continue
                    lines.append(f"  {atype_label} Top3:")
                    for row in rows[:3]:
                        lines.append(
                            f"    - {row['plugin']}: {row['quality_score']:.1f} "
                            f"({row['quality_band']})"
                        )
                    if len(rows) > 3:
                        worst = rows[-1]
                        lines.append(
                            f"  {atype_label} 最低分: {worst['plugin']} "
                            f"{worst['quality_score']:.1f} ({worst['quality_band']})"
                        )
                lines.append("=" * W)

            # 总计
            lines.append("=" * W)
            grand_wr = (
                f"{grand_wins / grand_closed * 100:.1f}%"
                if grand_closed > 0 else "-"
            )
            grand_pnl_str = (
                f"+${grand_pnl:,.2f}" if grand_pnl >= 0 else f"-${abs(grand_pnl):,.2f}"
            )
            lines.append(
                f"  {'合计':<18s}| {grand_sig:>8d}| {grand_exec:>8d}"
                f"| {grand_closed:>10d}| {grand_wr:>7s}| {grand_pnl_str:>12s}"
            )
            lines.append("=" * W)

            # 持仓中
            open_entries = self.state.get("open_entries", {})
            open_parts = []
            for sym, entries in open_entries.items():
                if entries:
                    open_parts.append(f"{sym} x{len(entries)}")
            if open_parts:
                lines.append(f"  持仓中(未平仓): {', '.join(open_parts)}")
            else:
                lines.append("  持仓中(未平仓): 无")
            lines.append("=" * W)

            # 当日交易明细
            if day_trades:
                lines.append("")
                lines.append("-" * W)
                lines.append("  当日交易明细")
                lines.append("-" * W)
                for t in day_trades:
                    pnl_v = t.get("pnl", 0)
                    pnl_s = f"+${pnl_v:,.2f}" if pnl_v >= 0 else f"-${abs(pnl_v):,.2f}"
                    at = "[stock]" if t.get("asset_type") == "stock" else ""
                    qty_s = f"x{t.get('quantity', '?')}" if t.get("quantity") else ""
                    lines.append(
                        f"  {t.get('symbol','?')}{at}: "
                        f"BUY({t.get('buy_plugin','?')}) {qty_s}@{t.get('buy_price',0):,.2f} "
                        f"-> SELL({t.get('sell_plugin','?')}) @{t.get('sell_price',0):,.2f} "
                        f"| P&L: {pnl_s} ({t.get('pnl_pct',0):+.2f}%)"
                    )
                lines.append("=" * W)

            txt_content = "\n".join(lines)
            return txt_content, json_data

    def compute_quality_snapshot(self) -> dict:
        """KEY-004-T01: compute plugin quality score and ranking."""
        with self._lock:
            return self._compute_quality_snapshot_from_state()

    def _compute_quality_snapshot_from_state(self) -> dict:
        result = {}
        for atype in ("crypto", "stock"):
            stats_map = self.state.get("plugin_stats", {}).get(atype, {})
            if not isinstance(stats_map, dict) or not stats_map:
                result[atype] = []
                continue

            rows = []
            for plugin_name, pstats in stats_map.items():
                score = self._compute_quality_score(plugin_name, atype, pstats)
                rows.append(score)

            rows.sort(key=lambda x: (-x["quality_score"], x["plugin"]))
            result[atype] = rows
        return result

    def _build_governance_actions_from_snapshot(self, snapshot: dict) -> dict:
        actions = {
            "version": "1.0",
            "updated_at": _get_ny_now().isoformat(),
            "rules": {
                "disable_candidate": "quality_score < 40",
                "observe_or_downweight": "40 <= quality_score < 60",
                "keep": "quality_score >= 60",
            },
            "by_asset": {"crypto": [], "stock": []},
        }

        for atype in ("crypto", "stock"):
            rows = snapshot.get(atype, []) if isinstance(snapshot, dict) else []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                score = float(row.get("quality_score", 0.0))
                if score < 40.0:
                    decision = "DISABLE_CANDIDATE"
                    reason = "quality_score<40"
                elif score < 60.0:
                    decision = "OBSERVE_OR_DOWNWEIGHT"
                    reason = "40<=quality_score<60"
                else:
                    decision = "KEEP"
                    reason = "quality_score>=60"

                actions["by_asset"][atype].append(
                    {
                        "plugin": row.get("plugin", "unknown"),
                        "quality_score": round(score, 2),
                        "quality_band": row.get("quality_band", "N/A"),
                        "decision": decision,
                        "reason": reason,
                    }
                )

        return actions

    def _save_governance_actions(self, updated_at: str, snapshot: dict) -> None:
        actions = self._build_governance_actions_from_snapshot(snapshot)
        actions["updated_at"] = updated_at
        try:
            gov_dir = os.path.dirname(os.path.abspath(GOVERNANCE_FILE))
            os.makedirs(gov_dir, exist_ok=True)
            with open(GOVERNANCE_FILE, "w", encoding="utf-8") as f:
                json.dump(actions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[PluginProfitTracker] 保存治理动作失败: {e}")

    def _compute_quality_score(self, plugin_name: str, asset_type: str, pstats: dict) -> dict:
        """KEY-004-T01 quality model v2 (0-100): accuracy/stability/profit/risk.

        v2 fixes (2026-02-27):
        - Stability: completion_rate(closed/buy) replaces execution_rate(exec/signal)
          Rationale: signals filtered by N_GATE/L2/rhythm is normal system behavior,
          not plugin instability. Measure how often buys reach closure instead.
        - Risk: removed execution_rate<0.20 penalty (was double-counting with stability)
        - Min sample gate: closed<5 → insufficient data, floor score at 50 (OBSERVE)
        """
        wins = int(pstats.get("as_buyer_wins", 0))
        losses = int(pstats.get("as_buyer_losses", 0))
        closed = wins + losses
        total_signals = int(pstats.get("total_signals", 0))
        executed_signals = int(pstats.get("executed_signals", 0))
        pnl = float(pstats.get("as_buyer_pnl", 0.0))
        buy_count = int(pstats.get("buy_count", 0))
        sell_count = int(pstats.get("sell_count", 0))

        win_rate = (wins / closed) if closed > 0 else 0.5
        # v2: completion_rate = how many buys resulted in closed trades
        completion_rate = (closed / buy_count) if buy_count > 0 else 0.5

        gross_profit = 0.0
        gross_loss = 0.0
        for t in self.state.get("completed_trades", []):
            if t.get("buy_plugin") != plugin_name:
                continue
            if t.get("asset_type", "crypto") != asset_type:
                continue
            v = float(t.get("pnl", 0.0))
            if v > 0:
                gross_profit += v
            elif v < 0:
                gross_loss += abs(v)

        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = 2.0
        else:
            profit_factor = 1.0

        # 1) Accuracy (0-30)
        accuracy_score = 30.0 * win_rate

        # 2) Stability (0-25) — v2: use completion_rate instead of execution_rate
        stability_score = 25.0 * min(max(completion_rate, 0.0), 1.0)

        # 3) Profit (0-30)
        pf_component = 15.0 * min(max(profit_factor / 2.0, 0.0), 1.0)
        edge = ((wins - losses) / closed) if closed > 0 else 0.0
        edge_component = 15.0 * (edge + 1.0) / 2.0
        profit_score = pf_component + edge_component

        # 4) Risk compliance proxy (0-15) — v2: removed exec_rate penalty
        risk_score = 15.0
        if total_signals < 20:
            risk_score -= 3.0
        if closed > 0 and win_rate < 0.35:
            risk_score -= 4.0
        if buy_count >= 6 and sell_count == 0:
            risk_score -= 2.0
        risk_score = min(max(risk_score, 0.0), 15.0)

        quality = accuracy_score + stability_score + profit_score + risk_score
        quality = min(max(quality, 0.0), 100.0)

        # v2: min sample gate — closed<5 means insufficient data, floor at 50
        # GCC-0172: BrooksVision用回测数据打破dead lock
        insufficient_data = closed < 5
        if insufficient_data and plugin_name == "brooks_vision":
            bv_acc = self._gcc0172_get_bv_accuracy(plugin_name)
            if bv_acc is not None:
                # 用回测数据重算accuracy_score, 不再floor at 50
                accuracy_score = 30.0 * bv_acc  # 同步breakdown
                quality = accuracy_score + stability_score + profit_score + risk_score
                quality = min(max(quality, 0.0), 100.0)
                # 回测数据只能升到WATCH, 不允许POOR/DISABLE(需实盘验证)
                quality = max(quality, 50.0)
                insufficient_data = False  # 回测提供了足够样本
        if insufficient_data and quality < 50.0:
            quality = 50.0

        if quality >= 75:
            band = "GOOD"
        elif quality >= 55:
            band = "WATCH"
        elif insufficient_data:
            band = "INSUFFICIENT_DATA"
        else:
            band = "POOR"

        return {
            "plugin": plugin_name,
            "quality_score": round(quality, 2),
            "quality_band": band,
            "breakdown": {
                "accuracy": round(accuracy_score, 2),
                "stability": round(stability_score, 2),
                "profit": round(profit_score, 2),
                "risk": round(risk_score, 2),
            },
            "metrics": {
                "win_rate": round(win_rate, 4),
                "completion_rate": round(completion_rate, 4),
                "profit_factor": round(profit_factor, 4),
                "pnl": round(pnl, 4),
                "closed": closed,
                "total_signals": total_signals,
                "executed_signals": executed_signals,
                "insufficient_data": insufficient_data,
            },
        }

    # ------------------------------------------------------------------
    # GCC-0172: BrooksVision 回测数据注入
    # ------------------------------------------------------------------

    def _gcc0172_get_bv_accuracy(self, plugin_name: str) -> Optional[float]:
        """读取BV回测准确率(overall)。返回None表示无数据。"""
        try:
            bv_path = Path("state/bv_signal_accuracy.json")
            if not bv_path.exists():
                return None
            data = json.loads(bv_path.read_text(encoding="utf-8"))
            overall = data.get("overall", {})
            total = overall.get("total", 0)
            if total < 10:  # 至少10条回测数据才有意义
                return None
            return overall.get("accuracy", None)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _migrate_quantity_pnl(self):
        """一次性迁移: 为旧数据补充quantity并重算pnl (幂等, 仅首次执行)。

        旧版本记录的completed_trades/open_entries缺少quantity字段,
        pnl为纯价差(未乘以交易数量), 导致盈亏显示错误。
        """
        if self.state.get("_pnl_migrated"):
            return

        changed = False

        # 1. 修复 completed_trades: 补quantity, 重算pnl
        for trade in self.state.get("completed_trades", []):
            sym = trade.get("symbol", "")
            if "quantity" not in trade or trade["quantity"] is None:
                trade["quantity"] = QUANTITY_MAP.get(sym, 1.0)
                changed = True
            # 重算pnl (始终用 quantity 乘以价差)
            bp = trade.get("buy_price", 0)
            sp = trade.get("sell_price", 0)
            qty = trade["quantity"]
            new_pnl = round((sp - bp) * qty, 4)
            if abs(trade.get("pnl", 0) - new_pnl) > 0.001:
                trade["pnl"] = new_pnl
                trade["pnl_pct"] = round((sp - bp) / bp * 100, 4) if bp else 0.0
                changed = True

        # 2. 修复 open_entries: 补quantity
        for sym, entries in self.state.get("open_entries", {}).items():
            for entry in entries:
                if "quantity" not in entry or entry["quantity"] is None:
                    entry["quantity"] = QUANTITY_MAP.get(sym, 1.0)
                    changed = True

        # 3. 重建 plugin_stats 中 as_buyer_pnl/wins/losses (从completed_trades重算)
        ps = self.state.get("plugin_stats", {})
        for atype_dict in ps.values():
            for pstats in atype_dict.values():
                pstats["as_buyer_pnl"] = 0.0
                pstats["as_buyer_wins"] = 0
                pstats["as_buyer_losses"] = 0

        for trade in self.state.get("completed_trades", []):
            buy_plugin = trade.get("buy_plugin", "")
            buy_asset = trade.get("asset_type", "crypto")
            pnl = trade.get("pnl", 0)
            buy_stats = (
                ps.setdefault(buy_asset, {})
                .setdefault(buy_plugin, dict(_EMPTY_PLUGIN_STATS))
            )
            buy_stats["as_buyer_pnl"] += pnl
            if pnl > 0:
                buy_stats["as_buyer_wins"] += 1
            else:
                buy_stats["as_buyer_losses"] += 1

        # 4. 重建 daily_stats 中 pnl (从completed_trades重算)
        ds = self.state.get("daily_stats", {})
        for date_dict in ds.values():
            for atype_dict in date_dict.values():
                for dstats in atype_dict.values():
                    dstats["pnl"] = 0.0

        for trade in self.state.get("completed_trades", []):
            sell_ts = trade.get("sell_ts", "")
            if not sell_ts:
                continue
            sell_date = sell_ts[:10]  # "YYYY-MM-DD"
            buy_plugin = trade.get("buy_plugin", "")
            buy_asset = trade.get("asset_type", "crypto")
            pnl = trade.get("pnl", 0)
            daily = (
                ds.setdefault(sell_date, {})
                .setdefault(buy_asset, {})
                .setdefault(buy_plugin, dict(_EMPTY_DAILY_STATS))
            )
            daily["pnl"] += pnl

        if changed or True:  # 始终标记已迁移
            self.state["_pnl_migrated"] = True
            self._save_state()
            print("[PluginProfitTracker] 数据迁移完成: quantity/pnl已修正")

    def _match_sell(
        self,
        symbol: str,
        sell_plugin: str,
        sell_source: str,
        sell_price: float,
        sell_ts: str,
        asset_type: str,
    ) -> Optional[dict]:
        """FIFO匹配: 弹出最早的open_entry, 计算P&L, 归因给buy_plugin。

        P&L = (sell_price - buy_price) * quantity  → 实际美元盈亏
        """
        entries = self.state.get("open_entries", {}).get(symbol, [])
        if not entries:
            return None

        buy_entry = entries.pop(0)
        buy_price = buy_entry["price"]
        # 使用买入时记录的数量, 兼容旧数据(无quantity字段)时从QUANTITY_MAP查找
        buy_qty = buy_entry.get("quantity") or QUANTITY_MAP.get(symbol, 1.0)
        price_diff = sell_price - buy_price
        pnl = price_diff * buy_qty  # 实际美元盈亏
        pnl_pct = (price_diff / buy_price * 100) if buy_price != 0 else 0.0

        trade = {
            "symbol": symbol,
            "asset_type": buy_entry.get("asset_type", asset_type),
            "buy_plugin": buy_entry["plugin"],
            "buy_source": buy_entry.get("source", buy_entry.get("plugin", "unknown")),
            "buy_price": buy_price,
            "buy_ts": buy_entry["ts"],
            "sell_plugin": sell_plugin,
            "sell_source": sell_source,
            "sell_price": sell_price,
            "sell_ts": sell_ts,
            "quantity": buy_qty,
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 4),
        }
        self.state.setdefault("completed_trades", []).append(trade)
        return trade

    def _load_state(self) -> dict:
        """从文件加载状态, 不存在则返回空状态。"""
        if not os.path.exists(self._state_file):
            return self._empty_state()
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 基本校验
            if not isinstance(data, dict):
                return self._empty_state()
            return data
        except Exception:
            return self._empty_state()

    def _save_state(self) -> None:
        """原子写入: temp + rename，防止并发写损坏。"""
        self.state["updated_at"] = _get_ny_now().isoformat()
        if "quality_snapshot" not in self.state:
            self.state["quality_snapshot"] = self._compute_quality_snapshot_from_state()
        try:
            dir_name = os.path.dirname(os.path.abspath(self._state_file))
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="ppt_", dir=dir_name
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, ensure_ascii=False, indent=2)
                # Windows: 需要先删除目标再重命名
                if os.path.exists(self._state_file):
                    os.replace(tmp_path, self._state_file)
                else:
                    os.rename(tmp_path, self._state_file)
            except Exception:
                # 清理临时文件
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
        except Exception as e:
            print(f"[PluginProfitTracker] 保存状态失败: {e}")

    @staticmethod
    def _empty_state() -> dict:
        return {
            "open_entries": {},
            "completed_trades": [],
            "plugin_stats": {},
            "daily_stats": {},
            "quality_snapshot": {},
            "updated_at": "",
        }


# ------------------------------------------------------------------
# 便捷函数: 保存日报文件到 外挂利润/ 目录
# ------------------------------------------------------------------

def save_daily_report(tracker: PluginProfitTracker, date_str: str) -> None:
    """生成日报并保存到 外挂利润/ 目录。"""
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "外挂利润")
    os.makedirs(report_dir, exist_ok=True)

    txt_content, json_data = tracker.generate_daily_report(date_str)

    txt_path = os.path.join(report_dir, f"plugin_profit_{date_str}.txt")
    json_path = os.path.join(report_dir, f"plugin_profit_{date_str}.json")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_content)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    print(f"[PluginProfitTracker] 日报已保存: {txt_path}")

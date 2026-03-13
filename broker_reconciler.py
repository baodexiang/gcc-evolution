"""
broker_reconciler.py — SYS-029 券商对账 v2
Schwab API + Coinbase fills API → state/broker_pnl.json
按日/周/月聚合真实P&L，显示在KEY-009 dashboard券商对账标签

用法:
  python broker_reconciler.py          # 手动运行
  (llm_server 每日8AM NY 自动调度)
"""

import json
import os
import logging
from collections import defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    import pytz
    NY_TZ = pytz.timezone("America/New_York")
except ImportError:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")

logger = logging.getLogger("broker_reconciler")

OUTPUT_FILE = "state/broker_pnl.json"

# 日切分: 8AM NY → 次日8AM NY (8AM前的交易算前一天)
_DAY_CUTOFF_HOUR = 8


def _trade_day(utc_time_str: str) -> str:
    """将UTC交易时间转为NY时区，按8AM切分归属到哪一天。
    8AM NY之前的交易算前一天。返回 'YYYY-MM-DD'。"""
    try:
        # 解析UTC时间 "2026-03-12T18:00:15+0000"
        ts = utc_time_str.replace("+0000", "+00:00").replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        # 转NY时区
        dt_ny = dt.astimezone(NY_TZ)
        # 8AM前算前一天
        if dt_ny.hour < _DAY_CUTOFF_HOUR:
            dt_ny -= timedelta(days=1)
        return dt_ny.strftime("%Y-%m-%d")
    except Exception:
        # fallback: 直接用date字段
        return utc_time_str[:10] if utc_time_str else ""


def _trade_week(day_str: str) -> str:
    """按周一8AM切分。返回该周周一日期 'YYYY-MM-DD'。"""
    try:
        dt = datetime.strptime(day_str, "%Y-%m-%d")
        # 周一为起始
        week_start = dt - timedelta(days=dt.weekday())
        return week_start.strftime("%Y-%m-%d")
    except ValueError:
        return day_str[:7]


# ============================================================
# Schwab API 交易历史
# ============================================================

def fetch_schwab_trades(days: int = 60) -> list:
    """通过Schwab API拉取交易记录。

    Returns:
        [{symbol, action, qty, price, amount, fees, net_amount, date, order_id, asset_type}, ...]
    """
    try:
        from schwab_data_provider import get_provider
        provider = get_provider()
        trades = provider.get_transactions(days=days)
        # 用8AM NY切分日期
        for t in trades:
            t["date"] = _trade_day(t.get("time", t.get("date", "")))
        logger.info("[SYS-029] Schwab API: %d trades in %d days", len(trades), days)
        return trades
    except Exception as e:
        logger.error("[SYS-029] Schwab API error: %s", e)
        return []


# ============================================================
# Coinbase fills (复用 coinbase_sync_v6.py 的 auth)
# ============================================================

def _coinbase_available() -> bool:
    try:
        import jwt
        from cryptography.hazmat.primitives import serialization
        import requests
        return True
    except ImportError:
        return False


def fetch_coinbase_trades() -> list:
    """拉取Coinbase成交记录，返回统一格式。

    Returns:
        [{symbol, action, qty, price, amount, fees, date, asset_type}, ...]
    """
    if not _coinbase_available():
        return []

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("coinbase_sync_v6", "coinbase_sync_v6.py")
        cb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cb)

        all_fills = []
        cursor = None
        for _ in range(10):
            path = "/api/v3/brokerage/orders/historical/fills?limit=100"
            if cursor:
                path += f"&cursor={cursor}"
            resp = cb.api_request("GET", path)
            if not resp:
                break
            fills = resp.get("fills", [])
            if not fills:
                break
            all_fills.extend(fills)
            cursor = resp.get("cursor")
            if not cursor:
                break

        trades = []
        for fill in all_fills:
            product = fill.get("product_id", "")
            side = fill.get("side", "").upper()
            size = float(fill.get("size", 0))
            price = float(fill.get("price", 0))
            fee = float(fill.get("commission", 0))
            trade_time = fill.get("trade_time", "")
            trade_date = trade_time[:10] if trade_time else ""

            trades.append({
                "symbol": product,
                "action": side,
                "qty": size,
                "price": round(price, 4),
                "amount": round(size * price, 2),
                "fees": round(fee, 4),
                "net_amount": round(size * price * (1 if side == "SELL" else -1), 2),
                "date": trade_date,
                "time": trade_time,
                "order_id": fill.get("order_id", ""),
                "asset_type": "crypto",
            })

        logger.info("[SYS-029] Coinbase: %d fills", len(trades))
        return trades
    except Exception as e:
        logger.error("[SYS-029] Coinbase error: %s", e)
        return []


# ============================================================
# FIFO P&L 计算
# ============================================================

def _fifo_pnl(trades: list) -> dict:
    """FIFO匹配计算realized P&L。

    Args:
        trades: 按时间排序的交易列表 (已统一格式)

    Returns:
        {
            "by_symbol": {symbol: {buys, sells, realized_pnl, fees}},
            "by_date": {date_str: {realized_pnl, fees, trade_count, details: [...]}},
            "completed_trades": [{symbol, buy_price, sell_price, qty, pnl, pnl_pct, date}],
            "open_positions": {symbol: [{price, qty, date}]},
        }
    """
    # 按品种分组
    open_buys = defaultdict(list)  # symbol → [{price, qty, date, fees}]
    completed = []
    by_date_pnl = defaultdict(lambda: {"realized_pnl": 0.0, "fees": 0.0, "trade_count": 0, "details": []})
    by_symbol = defaultdict(lambda: {"buys": 0, "sells": 0, "realized_pnl": 0.0, "fees": 0.0, "qty_bought": 0.0, "qty_sold": 0.0})

    for t in trades:
        sym = t["symbol"]
        action = t["action"]
        qty = t["qty"]
        price = t["price"]
        fees = t.get("fees", 0)
        trade_date = t.get("date", "")

        by_symbol[sym]["fees"] += fees
        by_date_pnl[trade_date]["fees"] += fees
        by_date_pnl[trade_date]["trade_count"] += 1

        if action == "BUY":
            by_symbol[sym]["buys"] += 1
            by_symbol[sym]["qty_bought"] += qty
            open_buys[sym].append({"price": price, "qty": qty, "date": trade_date})
        elif action == "SELL":
            by_symbol[sym]["sells"] += 1
            by_symbol[sym]["qty_sold"] += qty
            # FIFO match
            remaining = qty
            while remaining > 0 and open_buys[sym]:
                buy = open_buys[sym][0]
                matched = min(remaining, buy["qty"])
                pnl = (price - buy["price"]) * matched
                pnl_pct = ((price - buy["price"]) / buy["price"] * 100) if buy["price"] > 0 else 0

                completed.append({
                    "symbol": sym,
                    "buy_price": buy["price"],
                    "sell_price": price,
                    "qty": matched,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "buy_date": buy["date"],
                    "sell_date": trade_date,
                })
                by_symbol[sym]["realized_pnl"] += pnl
                by_date_pnl[trade_date]["realized_pnl"] += pnl
                by_date_pnl[trade_date]["details"].append({
                    "symbol": sym, "pnl": round(pnl, 2),
                    "qty": matched, "buy_price": buy["price"], "sell_price": price,
                })

                buy["qty"] -= matched
                remaining -= matched
                if buy["qty"] <= 1e-10:
                    open_buys[sym].pop(0)

    # Round
    for sym in by_symbol:
        for k in ("realized_pnl", "fees"):
            by_symbol[sym][k] = round(by_symbol[sym][k], 2)
    for d in by_date_pnl:
        by_date_pnl[d]["realized_pnl"] = round(by_date_pnl[d]["realized_pnl"], 2)
        by_date_pnl[d]["fees"] = round(by_date_pnl[d]["fees"], 4)

    open_positions = {}
    for sym, buys in open_buys.items():
        if buys:
            open_positions[sym] = [{"price": b["price"], "qty": round(b["qty"], 6), "date": b["date"]}
                                   for b in buys if b["qty"] > 1e-10]

    return {
        "by_symbol": dict(by_symbol),
        "by_date": dict(by_date_pnl),
        "completed_trades": completed,
        "open_positions": open_positions,
    }


# ============================================================
# 日/周/月 聚合
# ============================================================

def _aggregate_periods(by_date: dict) -> dict:
    """将by_date聚合为weekly和monthly。

    Returns:
        {"daily": [...], "weekly": [...], "monthly": [...]}
    """
    # Daily: 按日期排序
    daily = []
    for d in sorted(by_date.keys()):
        info = by_date[d]
        daily.append({
            "date": d,
            "pnl": info["realized_pnl"],
            "fees": info["fees"],
            "trades": info["trade_count"],
        })

    # Weekly: 周一8AM → 下周一8AM
    weekly_agg = defaultdict(lambda: {"pnl": 0.0, "fees": 0.0, "trades": 0})
    for d, info in by_date.items():
        week_key = _trade_week(d)
        weekly_agg[week_key]["pnl"] += info["realized_pnl"]
        weekly_agg[week_key]["fees"] += info["fees"]
        weekly_agg[week_key]["trades"] += info["trade_count"]

    weekly = [{"week_start": k, "pnl": round(v["pnl"], 2), "fees": round(v["fees"], 4), "trades": v["trades"]}
              for k, v in sorted(weekly_agg.items())]

    # Monthly
    monthly_agg = defaultdict(lambda: {"pnl": 0.0, "fees": 0.0, "trades": 0})
    for d, info in by_date.items():
        month_key = d[:7]  # "2026-03"
        monthly_agg[month_key]["pnl"] += info["realized_pnl"]
        monthly_agg[month_key]["fees"] += info["fees"]
        monthly_agg[month_key]["trades"] += info["trade_count"]

    monthly = [{"month": k, "pnl": round(v["pnl"], 2), "fees": round(v["fees"], 4), "trades": v["trades"]}
               for k, v in sorted(monthly_agg.items())]

    return {"daily": daily, "weekly": weekly, "monthly": monthly}


# ============================================================
# 主逻辑
# ============================================================

def run(days: int = 60) -> dict:
    """执行对账，输出 state/broker_pnl.json"""
    now = datetime.now(NY_TZ)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S%z")
    ts = ts[:-2] + ":" + ts[-2:]

    # Schwab API
    schwab_trades = fetch_schwab_trades(days=days)
    schwab_result = _fifo_pnl(schwab_trades)
    schwab_periods = _aggregate_periods(schwab_result["by_date"])
    schwab_total = sum(v["realized_pnl"] for v in schwab_result["by_symbol"].values())

    # Coinbase API
    cb_trades = fetch_coinbase_trades()
    cb_result = _fifo_pnl(cb_trades)
    cb_periods = _aggregate_periods(cb_result["by_date"])
    cb_total = sum(v["realized_pnl"] for v in cb_result["by_symbol"].values())

    # 合并daily/weekly/monthly (schwab + coinbase)
    all_by_date = defaultdict(lambda: {"realized_pnl": 0.0, "fees": 0.0, "trade_count": 0})
    for src in (schwab_result["by_date"], cb_result["by_date"]):
        for d, info in src.items():
            all_by_date[d]["realized_pnl"] += info["realized_pnl"]
            all_by_date[d]["fees"] += info["fees"]
            all_by_date[d]["trade_count"] += info["trade_count"]
    combined_periods = _aggregate_periods(dict(all_by_date))

    output = {
        "updated_at": ts,
        "schwab": {
            "symbols": schwab_result["by_symbol"],
            "total_realized": round(schwab_total, 2),
            "total_trades": len(schwab_trades),
            "periods": schwab_periods,
            "open_positions": schwab_result["open_positions"],
            "recent_trades": schwab_result["completed_trades"][-20:],
        },
        "coinbase": {
            "symbols": cb_result["by_symbol"],
            "total_realized": round(cb_total, 2),
            "total_trades": len(cb_trades),
            "periods": cb_periods,
            "open_positions": cb_result["open_positions"],
            "recent_trades": cb_result["completed_trades"][-20:],
        },
        "combined": {
            "total_pnl": round(schwab_total + cb_total, 2),
            "total_trades": len(schwab_trades) + len(cb_trades),
            "periods": combined_periods,
        },
    }

    os.makedirs("state", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[SYS-029] 对账完成 → {OUTPUT_FILE}")
    print(f"  Schwab: {len(schwab_trades)}笔, P&L=${schwab_total:+,.2f}")
    print(f"  Coinbase: {len(cb_trades)}笔, P&L=${cb_total:+,.2f}")
    print(f"  Total: ${schwab_total + cb_total:+,.2f}")
    if combined_periods["daily"]:
        today_str = now.strftime("%Y-%m-%d")
        today_pnl = next((d["pnl"] for d in combined_periods["daily"] if d["date"] == today_str), 0)
        print(f"  Today: ${today_pnl:+,.2f}")
    if combined_periods["weekly"]:
        print(f"  This week: ${combined_periods['weekly'][-1]['pnl']:+,.2f}")
    if combined_periods["monthly"]:
        print(f"  This month: ${combined_periods['monthly'][-1]['pnl']:+,.2f}")

    return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run()

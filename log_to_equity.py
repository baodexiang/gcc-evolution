"""
log_to_equity.py v1.0 — 交易记录 → 权益曲线 → StrategyEvaluator

从 trade_history.json 构建权益曲线，调用 StrategyEvaluator 计算7核心指标。
可独立运行或被 log_analyzer_v3.py 调用。

用法:
  python log_to_equity.py                    # 全量报告
  python log_to_equity.py --json             # JSON输出
  python log_to_equity.py --days 30          # 最近30天
  python log_to_equity.py --symbol BTCUSDC   # 单品种
"""
import json
import os
import sys
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

TRADE_HISTORY_PATH = os.path.join("logs", "trade_history.json")
METRICS_OUTPUT_PATH = os.path.join("state", "strategy_metrics.json")


def load_trades(path: str = TRADE_HISTORY_PATH) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_trades(trades: List[dict], days: int = 0, symbol: str = "") -> List[dict]:
    if symbol:
        trades = [t for t in trades if t.get("symbol") == symbol]
    if days > 0:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        trades = [t for t in trades if t.get("ts", "") >= cutoff]
    return trades


def build_pnl_series(trades: List[dict]) -> Tuple[List[float], List[float]]:
    """
    FIFO匹配法: BUY建仓, SELL平仓, 计算每笔SELL的P&L。
    Returns: (equity_curve, trade_pnls)
    """
    positions = defaultdict(list)  # symbol → [(price, units)]
    trade_pnls = []
    equity = 100000.0  # 初始资金
    equity_curve = [equity]

    for t in trades:
        symbol = t.get("symbol", "")
        action = t.get("action", "")
        price = t.get("price", 0)
        units = t.get("units", 1)
        fee_usd = t.get("fee_usd", 0)

        if not price or price <= 0:
            continue

        if action == "BUY":
            positions[symbol].append((price, units))
            equity -= fee_usd
        elif action == "SELL":
            if positions[symbol]:
                entry_price, entry_units = positions[symbol].pop(0)  # FIFO
                sell_units = min(units, entry_units)
                pnl = (price - entry_price) * sell_units - fee_usd
                trade_pnls.append(pnl)
                equity += pnl
                # 剩余units放回
                remaining = entry_units - sell_units
                if remaining > 0:
                    positions[symbol].insert(0, (entry_price, remaining))
            else:
                equity -= fee_usd

        equity_curve.append(equity)

    return equity_curve, trade_pnls


def compute_metrics(equity_curve: List[float], trade_pnls: List[float],
                    output_json: bool = False) -> Dict:
    """调用 StrategyEvaluator 计算指标"""
    try:
        from improvement.strategy_evaluator import StrategyEvaluator
    except ImportError:
        print("[ERROR] 无法导入 strategy_evaluator, 请确认 .GCC/improvement/strategy_evaluator.py 存在")
        return {}

    if len(equity_curve) < 2:
        print("[WARN] 权益曲线不足2点，跳过")
        return {}

    evaluator = StrategyEvaluator(
        equity_curve=equity_curve,
        trades=trade_pnls,
        risk_free_rate=0.05,
        trading_days_per_year=252,
    )

    if output_json:
        result = evaluator.to_dict()
    else:
        result = evaluator.full_report()
        result = evaluator.to_dict()

    return result


def save_metrics(metrics: Dict, path: str = METRICS_OUTPUT_PATH) -> None:
    metrics["generated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False, default=str)
    print(f"[METRICS] 已保存到 {path}")


def run(days: int = 0, symbol: str = "", output_json: bool = False) -> Dict:
    trades = load_trades()
    if not trades:
        print("[WARN] trade_history.json 为空")
        return {}

    trades = filter_trades(trades, days=days, symbol=symbol)
    if not trades:
        print(f"[WARN] 过滤后无交易 (days={days}, symbol={symbol})")
        return {}

    print(f"[INFO] 交易笔数: {len(trades)} | 期间: {trades[0]['ts'][:10]} ~ {trades[-1]['ts'][:10]}")

    equity_curve, trade_pnls = build_pnl_series(trades)
    print(f"[INFO] 权益曲线: {len(equity_curve)}点 | 已平仓: {len(trade_pnls)}笔")
    print(f"[INFO] 起始: ${equity_curve[0]:,.0f} → 当前: ${equity_curve[-1]:,.0f} "
          f"({'+'if equity_curve[-1]>=equity_curve[0] else ''}{equity_curve[-1]-equity_curve[0]:,.0f})")

    metrics = compute_metrics(equity_curve, trade_pnls, output_json=output_json)
    if metrics:
        metrics["meta"] = {
            "total_trades": len(trades),
            "matched_sells": len(trade_pnls),
            "period_start": trades[0]["ts"][:10],
            "period_end": trades[-1]["ts"][:10],
            "days_filter": days,
            "symbol_filter": symbol or "ALL",
        }
        save_metrics(metrics)

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="交易记录 → 权益曲线 → 策略评估")
    parser.add_argument("--days", type=int, default=0, help="最近N天(0=全量)")
    parser.add_argument("--symbol", default="", help="单品种过滤")
    parser.add_argument("--json", action="store_true", help="仅JSON输出")
    args = parser.parse_args()

    run(days=args.days, symbol=args.symbol, output_json=args.json)

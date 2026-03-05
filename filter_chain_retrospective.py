#!/usr/bin/env python3
"""
FilterChain 历史回测脚本 — KEY-006 GCC-0040~0043
用 1088 条真实交易历史，对 Volume + Micro 两道 Gate 进行回溯，计算净贡献基准。

PRD 来源: .GCC/improvement/02212026/filter_chain_complete_prd.md 第六部分

运行:
    python filter_chain_retrospective.py
    python filter_chain_retrospective.py --symbol SOLUSDC
    python filter_chain_retrospective.py --gate volume   # 只跑 Volume Gate
    python filter_chain_retrospective.py --gate micro    # 只跑 Micro Gate
    python filter_chain_retrospective.py --export csv    # 输出 CSV
    python filter_chain_retrospective.py --min-score 0.35  # 调参对比
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# ─────────────────────────────────────────────
# 路径常量
# ─────────────────────────────────────────────
ROOT = Path(__file__).parent
TRADE_HISTORY_PATH = ROOT / "logs" / "trade_history.json"
REPORT_DIR = ROOT / "logs" / "retrospective"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# GCC-0040: 数据加载 + P&L 匹配
# ─────────────────────────────────────────────
def load_trade_history() -> list[dict]:
    with open(TRADE_HISTORY_PATH) as f:
        trades = json.load(f)
    for t in trades:
        t["dt"] = datetime.fromisoformat(t["ts"]).replace(tzinfo=timezone.utc)
    trades.sort(key=lambda x: x["dt"])
    return trades


def build_pnl_pairs(trades: list[dict]) -> list[dict]:
    """
    匹配 BUY→SELL 对，计算每次买入的 P&L%。
    策略: 同品种按时间序列，BUY 进入队列，遇到 SELL 消耗最早的 BUY。
    """
    queues: dict[str, list] = defaultdict(list)  # symbol → [buy entries]
    pairs = []

    for t in trades:
        sym = t["symbol"]
        if t["action"] == "BUY":
            queues[sym].append(t)
        elif t["action"] == "SELL" and queues[sym]:
            buy = queues[sym].pop(0)
            pnl_pct = (t["price"] - buy["price"]) / buy["price"] * 100
            pairs.append({
                "symbol": sym,
                "buy_ts": buy["ts"],
                "buy_dt": buy["dt"],
                "buy_price": buy["price"],
                "sell_ts": t["ts"],
                "sell_dt": t["dt"],
                "sell_price": t["price"],
                "pnl_pct": pnl_pct,
                "holding_hours": (t["dt"] - buy["dt"]).total_seconds() / 3600,
                "result": "win" if pnl_pct > 0 else "loss",
                "timeframe": buy.get("timeframe", "240"),
            })

    # 未平仓的 BUY（仓位仍然持有）→ 跳过，不影响统计
    unclosed = sum(len(q) for q in queues.values())
    if unclosed:
        print(f"  [INFO] {unclosed} 条 BUY 尚未平仓，已跳过")

    return pairs


# ─────────────────────────────────────────────
# GCC-0041: Volume Gate 历史重算
# ─────────────────────────────────────────────
def _fetch_ohlcv(symbol: str, end_dt: datetime, lookback_bars: int = 60,
                 interval: str = "1h") -> dict | None:
    """拉 yfinance 历史 OHLCV。返回 dict(closes, volumes) 或 None。"""
    try:
        import yfinance as yf
        ticker_sym = _to_yfinance_symbol(symbol)
        start = end_dt - timedelta(hours=lookback_bars * _interval_hours(interval))
        df = yf.download(ticker_sym, start=start, end=end_dt,
                         interval=interval, progress=False, auto_adjust=True)
        if df is None or len(df) < 5:
            return None
        closes = df["Close"].values.flatten().tolist()
        volumes = df["Volume"].values.flatten().tolist()
        return {"closes": closes, "volumes": volumes}
    except Exception as e:
        return None


def _to_yfinance_symbol(sym: str) -> str:
    crypto_map = {
        "BTCUSDC": "BTC-USD", "ETHUSDC": "ETH-USD",
        "SOLUSDC": "SOL-USD", "ZECUSDC": "ZEC-USD",
    }
    return crypto_map.get(sym, sym)


def _interval_hours(interval: str) -> float:
    return {"1h": 1, "4h": 4, "15m": 0.25, "30m": 0.5, "2h": 2}. get(interval, 1)


def volume_gate(closes: list, volumes: list,
                pv_lookback: int = 10,
                rvol_period: int = 20,
                obv_lookback: int = 20,
                min_score: float = 0.5,
                pv_weight: float = 0.4,
                rvol_weight: float = 0.3,
                obv_weight: float = 0.3) -> tuple[str, float, str]:
    """
    返回 (decision, score, reason)
    decision: PASS / SKIP
    """
    if len(closes) < max(pv_lookback, rvol_period, obv_lookback) + 2:
        return "SKIP", 0.0, "数据不足"  # 数据不足 → 中立，不投票

    closes = np.array(closes, dtype=float)
    volumes = np.array(volumes, dtype=float)

    # 1. 量价配合 (权重 40%)
    aligned = 0
    for i in range(-pv_lookback, 0):
        price_up = closes[i] > closes[i - 1]
        vol_up = volumes[i] > volumes[i - 1]
        if price_up == vol_up:
            aligned += 1
    pv_score = aligned / pv_lookback * pv_weight

    # 2. RVOL 相对成交量 (权重 30%)
    avg_vol = np.mean(volumes[-rvol_period - 1:-1])
    rvol = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
    if rvol >= 1.5:
        rvol_score = rvol_weight
    elif rvol >= 0.8:
        rvol_score = rvol_weight * 0.67
    else:
        rvol_score = rvol_weight * 0.17

    # 3. OBV 方向 (权重 30%)
    obv = np.zeros(len(closes))
    obv[0] = volumes[0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    obv_recent = obv[-obv_lookback:]
    slope = np.polyfit(range(len(obv_recent)), obv_recent, 1)[0]
    if slope > 0:
        obv_score = obv_weight
    elif slope < 0:
        obv_score = 0.0
    else:
        obv_score = obv_weight * 0.5

    total = pv_score + rvol_score + obv_score
    # score < 0.5 → HOLD（量价不足，拦截信号）; score >= 0.5 → PASS
    decision = "PASS" if total >= min_score else "HOLD"
    reason = f"pv={pv_score:.2f} rvol={rvol:.2f}({rvol_score:.2f}) obv_slope={'↑' if slope>0 else '↓'} total={total:.2f}"
    return decision, round(total, 3), reason


# ─────────────────────────────────────────────
# GCC-0042: Micro Gate 历史重算（方差比 r）
# ─────────────────────────────────────────────
def _quadratic_variation(x: np.ndarray, lag: int) -> float:
    """QV(lag) = sum((x[t] - x[t-lag])^2)"""
    if lag >= len(x):
        return 0.0
    diffs = x[lag:] - x[:-lag]
    return float(np.sum(diffs ** 2))


def _fit_mixed_fbm(series: np.ndarray) -> tuple[float, float, float]:
    """
    用 QV 估计混合 fBm 参数: H0, sigma_W^2, sigma_B^2
    简化：用 QV(1)/QV(2)/QV(4) 三点拟合
    返回 (H0, sigma_W_sq, sigma_B_sq)
    """
    if len(series) < 8:
        return 0.75, 0.5, 0.5
    qv1 = _quadratic_variation(series, 1)
    qv2 = _quadratic_variation(series, 2)
    qv4 = _quadratic_variation(series, 4)
    if qv1 == 0:
        return 0.75, 0.5, 0.5
    # H0 from QV scaling: QV(2)/QV(1) = 2^(2H0)
    ratio = qv2 / qv1 if qv1 > 0 else 1.0
    H0 = np.log2(max(ratio, 0.01)) / 2
    H0 = float(np.clip(H0, 0.1, 0.99))
    # sigma_W_sq (趋势成分) from QV(1)
    sigma_W_sq = qv1 / len(series) * (2 ** (2 * H0))
    sigma_B_sq = max(qv1 / len(series) - sigma_W_sq, 1e-10)
    return H0, float(sigma_W_sq), float(sigma_B_sq)


def micro_gate(closes_by_scale: dict[str, list],
               volumes_by_scale: dict[str, list],
               signal_direction: str,
               vr_trend_threshold: float = 0.5,
               vr_noise_threshold: float = 0.7,
               flow_slope_threshold: float = 0.3) -> tuple[str, str, float, str]:
    """
    closes_by_scale: {"1h": [...], "4h": [...], ...}
    返回 (decision, regime, variance_ratio, reason)
    decision: PASS / HOLD / SKIP
    """
    scales = [s for s in ["1h", "4h"] if s in closes_by_scale]
    if not scales:
        return "SKIP", "unknown", 0.5, "无多尺度数据"

    vr_list = []
    for scale in scales:
        closes = np.array(closes_by_scale[scale], dtype=float)
        volumes = np.array(volumes_by_scale.get(scale, [1.0] * len(closes)), dtype=float)
        if len(closes) < 8:
            continue
        sig_flow = np.sign(closes[1:] - closes[:-1]) * volumes[1:]
        cum_sig = np.cumsum(sig_flow)
        _, sigma_W_sq, sigma_B_sq = _fit_mixed_fbm(cum_sig)
        denom = sigma_W_sq + sigma_B_sq
        vr = sigma_B_sq / denom if denom > 0 else 0.5
        vr_list.append(float(np.clip(vr, 0.0, 1.0)))

    if not vr_list:
        return "SKIP", "unknown", 0.5, "计算失败"

    avg_vr = float(np.mean(vr_list))

    # 用 4h 签名流斜率判断方向
    if "4h" in closes_by_scale:
        closes_4h = np.array(closes_by_scale["4h"], dtype=float)
        volumes_4h = np.array(volumes_by_scale.get("4h", [1.0] * len(closes_4h)), dtype=float)
        sig_4h = np.sign(closes_4h[1:] - closes_4h[:-1]) * volumes_4h[1:]
        cum_4h = np.cumsum(sig_4h)
        if len(cum_4h) >= 4:
            slope = np.polyfit(range(len(cum_4h[-20:])), cum_4h[-20:], 1)[0]
            norm = max(abs(slope), 1e-10)
            slope_norm = float(slope / norm * min(abs(slope) / (abs(cum_4h).mean() + 1e-10), 1.0))
        else:
            slope_norm = 0.0
        core_flow_up = slope_norm > flow_slope_threshold
        core_flow_dn = slope_norm < -flow_slope_threshold
    else:
        core_flow_up = core_flow_dn = False
        slope_norm = 0.0

    # 决策矩阵
    if avg_vr > vr_noise_threshold:
        decision, regime = "HOLD", "noise"
    elif avg_vr < vr_trend_threshold:
        regime = "trend"
        is_bullish_signal = signal_direction == "BUY"
        trend_up = core_flow_up
        if is_bullish_signal and trend_up:
            decision = "PASS"
        elif not is_bullish_signal and core_flow_dn:
            decision = "PASS"
        else:
            decision = "HOLD"
    else:
        regime = "range"
        # 震荡 → 逆势放行
        is_bullish_signal = signal_direction == "BUY"
        if is_bullish_signal and core_flow_dn:
            decision = "PASS"
        elif not is_bullish_signal and core_flow_up:
            decision = "PASS"
        else:
            decision = "HOLD"

    reason = (f"vr={avg_vr:.3f} regime={regime} "
              f"slope={slope_norm:+.3f} dir={signal_direction}")
    return decision, regime, round(avg_vr, 3), reason


# ─────────────────────────────────────────────
# GCC-0043: 净贡献计算引擎 + 报告输出
# ─────────────────────────────────────────────
def run_retrospective(pairs: list[dict], gate: str = "both",
                      verbose: bool = False,
                      vol_min_score: float = 0.5,
                      vol_pv_weight: float = 0.4,
                      vol_rvol_weight: float = 0.3,
                      vol_obv_weight: float = 0.3) -> dict:
    """
    对每个交易对运行指定 Gate，输出分析结果。
    gate: "volume" | "micro" | "both"
    """
    results = []
    cache: dict[str, dict] = {}  # (symbol, date_hour) → ohlcv

    total = len(pairs)
    print(f"\n  [KEY-006] 开始回溯 {total} 条交易对 | Gate: {gate}")
    print("  " + "─" * 50)

    for i, p in enumerate(pairs):
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{total}] 处理中...")

        sym = p["symbol"]
        buy_dt = p["buy_dt"]
        direction = "BUY"  # 对买入信号做 gate 判断

        # 拉 1h OHLCV (买入时刻往前 60 根)
        cache_key_1h = f"{sym}_1h_{buy_dt.strftime('%Y%m%d%H')}"
        cache_key_4h = f"{sym}_4h_{buy_dt.strftime('%Y%m%d%H')}"

        ohlcv_1h = cache.get(cache_key_1h) or _fetch_ohlcv(sym, buy_dt, 60, "1h")
        ohlcv_4h = cache.get(cache_key_4h) or _fetch_ohlcv(sym, buy_dt, 60, "4h")

        if ohlcv_1h:
            cache[cache_key_1h] = ohlcv_1h
        if ohlcv_4h:
            cache[cache_key_4h] = ohlcv_4h

        row = {
            "symbol": sym,
            "buy_ts": p["buy_ts"],
            "sell_ts": p["sell_ts"],
            "buy_price": p["buy_price"],
            "sell_price": p["sell_price"],
            "pnl_pct": p["pnl_pct"],
            "result": p["result"],
            "holding_hours": p["holding_hours"],
            "vol_decision": "SKIP",
            "vol_score": 0.0,
            "vol_reason": "",
            "micro_decision": "SKIP",
            "micro_regime": "unknown",
            "micro_vr": 0.5,
            "micro_reason": "",
            "chain_decision": "PASS",  # 两道都 PASS → PASS, 任一 HOLD → HOLD
        }

        # Volume Gate
        if gate in ("volume", "both") and ohlcv_1h:
            dec, score, reason = volume_gate(ohlcv_1h["closes"], ohlcv_1h["volumes"],
                                             min_score=vol_min_score,
                                             pv_weight=vol_pv_weight,
                                             rvol_weight=vol_rvol_weight,
                                             obv_weight=vol_obv_weight)
            row.update(vol_decision=dec, vol_score=score, vol_reason=reason)

        # Micro Gate
        if gate in ("micro", "both"):
            closes_by = {}
            vols_by = {}
            if ohlcv_1h:
                closes_by["1h"] = ohlcv_1h["closes"]
                vols_by["1h"] = ohlcv_1h["volumes"]
            if ohlcv_4h:
                closes_by["4h"] = ohlcv_4h["closes"]
                vols_by["4h"] = ohlcv_4h["volumes"]
            if closes_by:
                dec, regime, vr, reason = micro_gate(closes_by, vols_by, direction)
                row.update(micro_decision=dec, micro_regime=regime,
                           micro_vr=vr, micro_reason=reason)

        # Chain 最终决策
        # Volume: PASS/HOLD/SKIP(数据不足=中立)
        # Micro:  PASS/HOLD/SKIP(数据不足=中立)
        # 任一 HOLD → chain HOLD
        blocked = False
        if gate in ("volume", "both") and row["vol_decision"] == "HOLD":
            blocked = True
        if gate in ("micro", "both") and row["micro_decision"] == "HOLD":
            blocked = True
        row["chain_decision"] = "HOLD" if blocked else "PASS"

        results.append(row)
        if verbose:
            print(f"  {sym} {p['buy_ts'][:16]} {row['chain_decision']} "
                  f"pnl={p['pnl_pct']:+.1f}%")

    return _calc_net_contribution(results, gate, vol_min_score)


def _calc_net_contribution(results: list[dict], gate: str,
                           vol_min_score: float = 0.5) -> dict:
    """GCC-0043 核心：计算净贡献 + 分类统计"""

    correct_pass = []    # chain=PASS, result=win
    false_pass = []      # chain=PASS, result=loss  (漏网之鱼)
    correct_block = []   # chain=HOLD, result=loss  (正确拦截)
    false_block = []     # chain=HOLD, result=win   (误杀)
    skipped = []         # 数据不足，未运行 gate

    for r in results:
        dec = r["chain_decision"]
        res = r["result"]
        # 两道 gate 都拿不到数据 → 整条 skipped，不计入统计
        vol_no_data = (r["vol_decision"] == "SKIP")
        mic_no_data = (r["micro_decision"] == "SKIP")
        if gate == "volume" and vol_no_data:
            skipped.append(r); continue
        if gate == "micro" and mic_no_data:
            skipped.append(r); continue
        if gate == "both" and vol_no_data and mic_no_data:
            skipped.append(r); continue
        if dec == "PASS":
            (correct_pass if res == "win" else false_pass).append(r)
        else:  # HOLD
            (correct_block if res == "loss" else false_block).append(r)

    avoided_loss = sum(abs(r["pnl_pct"]) for r in correct_block)
    missed_profit = sum(abs(r["pnl_pct"]) for r in false_block)
    net_contribution = avoided_loss - missed_profit

    total_gated = len(correct_pass) + len(false_pass) + len(correct_block) + len(false_block)
    block_rate = (len(correct_block) + len(false_block)) / max(total_gated, 1)
    pass_win_rate = len(correct_pass) / max(len(correct_pass) + len(false_pass), 1)
    block_accuracy = len(correct_block) / max(len(correct_block) + len(false_block), 1)
    false_block_rate = len(false_block) / max(len(correct_block) + len(false_block), 1)

    return {
        "gate": gate,
        "vol_min_score": vol_min_score,
        "total": len(results),
        "gated": total_gated,
        "skipped": len(skipped),
        "correct_pass": len(correct_pass),
        "false_pass": len(false_pass),
        "correct_block": len(correct_block),
        "false_block": len(false_block),
        "block_rate": round(block_rate, 3),
        "pass_win_rate": round(pass_win_rate, 3),
        "block_accuracy": round(block_accuracy, 3),
        "false_block_rate": round(false_block_rate, 3),
        "avoided_loss_pct": round(avoided_loss, 2),
        "missed_profit_pct": round(missed_profit, 2),
        "net_contribution_pct": round(net_contribution, 2),
        "verdict": "✅ FilterChain 净正贡献" if net_contribution > 0 else "❌ FilterChain 净负贡献",
        "detail": results,
    }


def print_report(stat: dict) -> None:
    d = stat
    w = 52
    print()
    print("  ╔" + "═" * w + "╗")
    print("  ║  FilterChain 历史回测报告 — KEY-006" + " " * (w - 37) + "║")
    gate_line = f"Gate: {d['gate']}  vol_min_score={d.get('vol_min_score', 0.5)}"
    print("  ║  " + gate_line + " " * (w - 2 - len(gate_line)) + "║")
    print("  ╠" + "═" * w + "╣")
    print(f"  ║  总交易对         {d['total']:>6}  " + " " * (w - 26) + "║")
    print(f"  ║  有效评估         {d['gated']:>6}  跳过: {d['skipped']}" + " " * (w - 34 - len(str(d['skipped']))) + "║")
    print("  ╠" + "─" * w + "╣")
    print(f"  ║  ✅ 正确放行 (win)  {d['correct_pass']:>5}" + " " * (w - 25) + "║")
    print(f"  ║  ❌ 错误放行 (loss) {d['false_pass']:>5}" + " " * (w - 25) + "║")
    print(f"  ║  ✅ 正确拦截 (loss) {d['correct_block']:>5}" + " " * (w - 25) + "║")
    print(f"  ║  ❌ 误杀   (win)  {d['false_block']:>5}" + " " * (w - 24) + "║")
    print("  ╠" + "─" * w + "╣")
    print(f"  ║  拦截率           {d['block_rate']*100:>5.1f}%" + " " * (w - 25) + "║")
    print(f"  ║  放行胜率         {d['pass_win_rate']*100:>5.1f}%" + " " * (w - 25) + "║")
    print(f"  ║  拦截准确率       {d['block_accuracy']*100:>5.1f}%" + " " * (w - 25) + "║")
    print(f"  ║  误杀率           {d['false_block_rate']*100:>5.1f}%" + " " * (w - 25) + "║")
    print("  ╠" + "═" * w + "╣")
    print(f"  ║  避免损失 (累计)  {d['avoided_loss_pct']:>+8.2f}%" + " " * (w - 27) + "║")
    print(f"  ║  错过利润 (累计)  {d['missed_profit_pct']:>+8.2f}%" + " " * (w - 27) + "║")
    net = d['net_contribution_pct']
    print(f"  ║  净贡献           {net:>+8.2f}%" + " " * (w - 27) + "║")
    print("  ╠" + "─" * w + "╣")
    verdict = d["verdict"]
    print(f"  ║  {verdict}" + " " * (w - 2 - len(verdict)) + "║")
    print("  ╚" + "═" * w + "╝")

    # PRD 健康度指标对照
    print()
    print("  [健康度指标对照 — PRD §8.1]")
    checks = [
        ("拦截率",       d["block_rate"] * 100,        25, 50,  "目标 25~50%"),
        ("放行胜率",     d["pass_win_rate"] * 100,      60, 100, "目标 >60%"),
        ("拦截准确率",   d["block_accuracy"] * 100,     70, 100, "目标 >70%"),
        ("误杀率",       d["false_block_rate"] * 100,   0,  30,  "目标 <30%"),
        ("净贡献",       d["net_contribution_pct"],      0,  999, "目标 >0"),
    ]
    for name, val, lo, hi, label in checks:
        ok = lo <= val <= hi
        mark = "✅" if ok else "⚠️"
        print(f"    {mark} {name:12s} {val:>+7.2f}%   {label}")


def export_csv(stat: dict, path: Path) -> None:
    import csv
    keys = ["symbol", "buy_ts", "sell_ts", "buy_price", "sell_price",
            "pnl_pct", "result", "holding_hours",
            "vol_decision", "vol_score",
            "micro_decision", "micro_regime", "micro_vr",
            "chain_decision"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(stat["detail"])
    print(f"\n  [导出] CSV → {path}")


def save_json_report(stat: dict) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out = stat.copy()
    out.pop("detail", None)  # JSON 报告不含明细
    path = REPORT_DIR / f"retro_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"  [保存] JSON 报告 → {path}")


# ─────────────────────────────────────────────
# Sweep 模式：多组参数对比
# ─────────────────────────────────────────────

# 预设参数组合（label, min_score, pv, rvol, obv）
SWEEP_CONFIGS = [
    ("baseline  pv=.4 rv=.3 ob=.3 ms=.5", 0.50, 0.4, 0.3, 0.3),
    ("rvol↑     pv=.4 rv=.5 ob=.1 ms=.5", 0.50, 0.4, 0.5, 0.1),
    ("rvol↑↑    pv=.3 rv=.6 ob=.1 ms=.5", 0.50, 0.3, 0.6, 0.1),
    ("pv↑rvol↑  pv=.5 rv=.4 ob=.1 ms=.5", 0.50, 0.5, 0.4, 0.1),
    ("ms=.4     pv=.4 rv=.5 ob=.1 ms=.4", 0.40, 0.4, 0.5, 0.1),
    ("ms=.45    pv=.4 rv=.5 ob=.1 ms=.45",0.45, 0.4, 0.5, 0.1),
]


def run_sweep(pairs: list[dict]) -> None:
    """并行跑所有预设组合，输出对比表"""
    print("\n  ╔══════════════════════════════════════════════════════════════════════════════╗")
    print("  ║  Volume Gate 参数 Sweep — KEY-006                                          ║")
    print("  ╠══════════╦════════╦════════╦════════╦══════════╦══════════╦════════════════╣")
    print("  ║ 方案     ║ 拦截率 ║ 放行胜 ║ 拦截准 ║  误杀率  ║ 净贡献%  ║ 结论           ║")
    print("  ╠══════════╬════════╬════════╬════════╬══════════╬══════════╬════════════════╣")

    best_net = -999999
    best_label = ""
    rows = []

    for label, ms, pv, rv, ob in SWEEP_CONFIGS:
        stat = run_retrospective(pairs, gate="volume",
                                 vol_min_score=ms,
                                 vol_pv_weight=pv,
                                 vol_rvol_weight=rv,
                                 vol_obv_weight=ob)
        d = stat
        net = d["net_contribution_pct"]
        verdict = "✅BEST" if net > best_net else ""
        if net > best_net:
            best_net = net
            best_label = label
        rows.append((label, d, net))

    # 重新过一遍标出 BEST
    for label, d, net in rows:
        tag = "◀BEST" if label == best_label else "      "
        print(f"  ║ {label[:8]:8s} ║ {d['block_rate']*100:5.1f}% ║"
              f" {d['pass_win_rate']*100:5.1f}% ║"
              f" {d['block_accuracy']*100:5.1f}% ║"
              f"   {d['false_block_rate']*100:5.1f}% ║"
              f" {net:+9.1f}% ║ {tag}        ║")

    print("  ╚══════════╩════════╩════════╩════════╩══════════╩══════════╩════════════════╝")
    print(f"\n  最优方案: {best_label}  净贡献={best_net:+.1f}%")

    # 目标对照
    print("\n  [PRD目标] 拦截率25~50% | 放行胜率>60% | 拦截准确率>70% | 误杀率<30% | 净贡献>0")


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="FilterChain 历史回测 — KEY-006")
    parser.add_argument("--symbol", default=None, help="只分析某个品种")
    parser.add_argument("--gate", default="both",
                        choices=["volume", "micro", "both"],
                        help="要测试的 Gate")
    parser.add_argument("--export", default=None,
                        choices=["csv"], help="额外导出格式")
    parser.add_argument("--verbose", action="store_true", help="逐条输出")
    parser.add_argument("--limit", type=int, default=0, help="限制条数（调试用）")
    parser.add_argument("--sweep", action="store_true",
                        help="一次跑所有预设参数组合，输出对比表")
    parser.add_argument("--min-score", type=float, default=0.5,
                        dest="min_score", help="Volume Gate 最低通过分 (default=0.5)")
    parser.add_argument("--pv-weight", type=float, default=0.4,
                        dest="pv_weight", help="量价配合权重 (default=0.4)")
    parser.add_argument("--rvol-weight", type=float, default=0.3,
                        dest="rvol_weight", help="RVOL权重 (default=0.3)")
    parser.add_argument("--obv-weight", type=float, default=0.3,
                        dest="obv_weight", help="OBV权重 (default=0.3)")
    args = parser.parse_args()

    print("\n  ══════════════════════════════════════════════")
    print("  FilterChain 历史回测 — KEY-006 / GCC-0040~0043")
    print("  PRD §6: 双数据流对比 + 净贡献验证")
    print("  ══════════════════════════════════════════════")

    # 加载
    print(f"\n  [GCC-0040] 加载交易历史: {TRADE_HISTORY_PATH}")
    trades = load_trade_history()
    if args.symbol:
        trades = [t for t in trades if t["symbol"] == args.symbol]
        print(f"  过滤品种: {args.symbol} → {len(trades)} 条")

    pairs = build_pnl_pairs(trades)
    print(f"  匹配交易对: {len(pairs)} 条")

    if args.limit:
        pairs = pairs[:args.limit]
        print(f"  DEBUG: 限制 {args.limit} 条")

    if not pairs:
        print("  无有效交易对，退出。"); sys.exit(0)

    # Sweep 模式：直接输出对比表后退出
    if args.sweep:
        run_sweep(pairs)
        print()
        sys.exit(0)

    if not pairs:
        print("  无有效交易对，退出。")
        sys.exit(0)

    # 权重归一化校验
    w_total = args.pv_weight + args.rvol_weight + args.obv_weight
    if abs(w_total - 1.0) > 0.01:
        print(f"  [警告] 权重合计={w_total:.2f}，已自动归一化")
        args.pv_weight /= w_total
        args.rvol_weight /= w_total
        args.obv_weight /= w_total

    defaults = dict(min_score=0.5, pv=0.4, rvol=0.3, obv=0.3)
    changed = []
    if args.min_score != defaults["min_score"]:
        changed.append(f"min_score={args.min_score}")
    if abs(args.pv_weight - defaults["pv"]) > 0.001:
        changed.append(f"pv={args.pv_weight:.2f}")
    if abs(args.rvol_weight - defaults["rvol"]) > 0.001:
        changed.append(f"rvol={args.rvol_weight:.2f}")
    if abs(args.obv_weight - defaults["obv"]) > 0.001:
        changed.append(f"obv={args.obv_weight:.2f}")
    if changed:
        print(f"  [参数] " + "  ".join(changed))

    # 回测
    stat = run_retrospective(pairs, gate=args.gate, verbose=args.verbose,
                             vol_min_score=args.min_score,
                             vol_pv_weight=args.pv_weight,
                             vol_rvol_weight=args.rvol_weight,
                             vol_obv_weight=args.obv_weight)

    # 报告
    print_report(stat)
    save_json_report(stat)

    if args.export == "csv":
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        export_csv(stat, REPORT_DIR / f"retro_{ts}.csv")

    print()


if __name__ == "__main__":
    main()

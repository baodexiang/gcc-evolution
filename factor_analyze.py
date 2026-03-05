#!/usr/bin/env python3
"""
factor_analyze.py — KEY-004 因子观测台 · Layer 3 (v1.0)
=========================================================
读取 factor_signals 表中已回填的记录，计算 IC/ICIR/胜率/t统计，
输出因子质量报告并写入 factor_stats 表。

核心指标 (来自需求规格 v2.0):
  Rank IC    = Spearman(signal, ret_N)      有效阈值 |IC| > 0.05
  ICIR       = IC均值 / IC标准差             有效阈值 > 0.5
  胜率       = sign(signal)==sign(ret) 比例  有效阈值 > 55%
  t统计/p值  = IC均值显著性检验              p < 0.05
  市场机制分层 IC = 按 market_regime 分组计算

进化触发条件:
  ICIR < 0.3 连续4周 → 触发 LLM 进化分析

运行方式:
    python factor_analyze.py               # 全量分析 + 写 factor_stats
    python factor_analyze.py --factor chan_bi  # 单因子
    python factor_analyze.py --period 5       # 用5日收益 (default=5)
    python factor_analyze.py --no-save        # 只打印不写DB
"""

import argparse
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("FactorAnalyze")

from factor_db import DB_PATH, _get_conn, _ensure_tables, _lock

MIN_SAMPLES = 20  # 最小样本量

# GCC-EVO 进化触发阈值
ICIR_WARN_THRESHOLD = 0.3
ICIR_GOOD_THRESHOLD = 0.5
IC_GOOD_THRESHOLD   = 0.05
WINRATE_GOOD        = 0.55


# ═══════════════════════════════════════════════════════════════
# 计算核心
# ═══════════════════════════════════════════════════════════════

def _spearman_ic(signals: list, rets: list) -> "tuple[float, float, float]":
    """
    计算 Rank IC (Spearman ρ), t统计, p值
    Returns: (ic, t_stat, p_value)
    """
    try:
        from scipy.stats import spearmanr
        import numpy as np
        s = np.array(signals, dtype=float)
        r = np.array(rets, dtype=float)
        mask = ~(np.isnan(s) | np.isnan(r))
        s, r = s[mask], r[mask]
        if len(s) < 5:
            return None, None, None
        ic, pv = spearmanr(s, r)
        n = len(s)
        t = ic * ((n - 2) ** 0.5) / max((1 - ic**2) ** 0.5, 1e-10)
        return float(ic), float(t), float(pv)
    except Exception:
        return None, None, None


def _win_rate(signals: list, rets: list) -> float:
    """sign(signal) == sign(ret) 的比例"""
    correct = sum(1 for s, r in zip(signals, rets)
                  if s != 0 and r is not None and (s > 0) == (r > 0))
    total = sum(1 for s, r in zip(signals, rets)
                if s != 0 and r is not None)
    return correct / total if total > 0 else None


def _icir_from_rolling(signals: list, rets: list, window: int = 20) -> "tuple[float, float]":
    """
    滚动 IC 均值/标准差 → ICIR
    Returns: (icir, ic_std)
    """
    try:
        import numpy as np
        n = len(signals)
        if n < window:
            ic, _, _ = _spearman_ic(signals, rets)
            return (ic, 0.0) if ic is not None else (None, None)
        ics = []
        for i in range(0, n - window + 1, max(1, window // 4)):
            ic, _, _ = _spearman_ic(signals[i:i+window], rets[i:i+window])
            if ic is not None:
                ics.append(ic)
        if not ics:
            return None, None
        ic_mean = float(np.mean(ics))
        ic_std  = float(np.std(ics))
        icir = ic_mean / max(ic_std, 1e-10)
        return icir, ic_std
    except Exception:
        return None, None


def _analyze_group(rows: list, ret_col: str = "ret_5d") -> dict:
    """对一组记录计算所有指标"""
    signals = [r["signal"] for r in rows]
    rets    = [r[ret_col] for r in rows if r[ret_col] is not None]

    # 只取 ret 不为 None 的记录
    pairs = [(r["signal"], r[ret_col]) for r in rows if r[ret_col] is not None]
    if len(pairs) < MIN_SAMPLES:
        return {"n": len(pairs), "insufficient": True}

    sigs = [p[0] for p in pairs]
    rets = [p[1] for p in pairs]

    ic, t_stat, p_value = _spearman_ic(sigs, rets)
    icir, ic_std = _icir_from_rolling(sigs, rets)
    wr = _win_rate(sigs, rets)

    return {
        "n":        len(pairs),
        "ic_mean":  ic,
        "ic_std":   ic_std,
        "icir":     icir,
        "win_rate": wr,
        "t_stat":   t_stat,
        "p_value":  p_value,
    }


# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════

def _load_signals(factor_name: str = None) -> list:
    _ensure_tables()
    with _lock:
        conn = _get_conn()
        if factor_name:
            rows = conn.execute(
                """SELECT id, symbol, factor_name, factor_version, signal,
                          market_regime, close_price, ret_1d, ret_5d, ts
                   FROM factor_signals
                   WHERE factor_name=? AND close_price IS NOT NULL
                   ORDER BY ts ASC""",
                (factor_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, symbol, factor_name, factor_version, signal,
                          market_regime, close_price, ret_1d, ret_5d, ts
                   FROM factor_signals
                   WHERE close_price IS NOT NULL
                   ORDER BY ts ASC"""
            ).fetchall()
        conn.close()

    cols = ["id","symbol","factor_name","factor_version","signal",
            "market_regime","close_price","ret_1d","ret_5d","ts"]
    return [dict(zip(cols, r)) for r in rows]


# ═══════════════════════════════════════════════════════════════
# 写入 factor_stats
# ═══════════════════════════════════════════════════════════════

def _write_stat(factor_name, factor_version, period_days, market_regime, m: dict):
    if m.get("insufficient"):
        return
    calc_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _lock:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO factor_stats
               (calc_ts, factor_name, factor_version, period_days, market_regime,
                n_samples, ic_mean, ic_std, icir, win_rate, t_stat, p_value)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (calc_ts, factor_name, factor_version, period_days, market_regime,
             m["n"], m.get("ic_mean"), m.get("ic_std"), m.get("icir"),
             m.get("win_rate"), m.get("t_stat"), m.get("p_value"))
        )
        conn.commit()
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════════

def _badge(v, good, warn=None) -> str:
    if v is None: return "[—]"
    if warn and v < warn: return f"[WEAK:{v:.3f}]"
    if v >= good: return f"[OK:{v:.3f}]"
    return f"[?:{v:.3f}]"


def _print_factor(factor_name: str, rows: list, period_days: int, save: bool):
    by_version = defaultdict(list)
    for r in rows:
        by_version[r["factor_version"]].append(r)

    print(f"\n{'='*60}")
    print(f"  因子: {factor_name}  (总记录={len(rows)})")
    print(f"{'='*60}")

    for version, vrows in sorted(by_version.items()):
        ret_col = f"ret_{period_days}d" if period_days != 1 else "ret_1d"
        # fallback to ret_5d if ret_1d
        if ret_col not in ("ret_1d", "ret_5d"):
            ret_col = "ret_5d"

        # 全量
        m = _analyze_group(vrows, ret_col)
        _print_metric(f"  [{version}] 全量", m, period_days)
        if save and not m.get("insufficient"):
            _write_stat(factor_name, version, period_days, None, m)

        # 按 market_regime 分层
        by_regime = defaultdict(list)
        for r in vrows:
            by_regime[r.get("market_regime") or "unknown"].append(r)

        if len(by_regime) > 1:
            for regime, rrows in sorted(by_regime.items()):
                mr = _analyze_group(rrows, ret_col)
                if not mr.get("insufficient"):
                    _print_metric(f"    [{regime}]", mr, period_days)
                    if save:
                        _write_stat(factor_name, version, period_days, regime, mr)

        # GCC-EVO 进化触发检查
        icir = m.get("icir")
        if icir is not None and icir < ICIR_WARN_THRESHOLD and m["n"] >= MIN_SAMPLES:
            print(f"  [!] GCC-EVO 触发: ICIR={icir:.3f} < {ICIR_WARN_THRESHOLD} "
                  f"→ 建议对 {factor_name} 发起 LLM 进化分析")


def _print_metric(label: str, m: dict, period_days: int):
    if m.get("insufficient"):
        print(f"{label}: 样本不足 n={m.get('n',0)} (需>={MIN_SAMPLES})")
        return
    icir_b  = _badge(m.get("icir"),     ICIR_GOOD_THRESHOLD, ICIR_WARN_THRESHOLD)
    ic_b    = _badge(m.get("ic_mean"),  IC_GOOD_THRESHOLD)
    wr_b    = _badge(m.get("win_rate"), WINRATE_GOOD)
    pv      = m.get("p_value")
    sig     = "**" if pv and pv < 0.05 else ""
    print(f"{label} n={m['n']:>5} | "
          f"IC={m.get('ic_mean') or 0:.3f}{ic_b} "
          f"ICIR={m.get('icir') or 0:.2f}{icir_b} "
          f"WR={m.get('win_rate') or 0:.1%}{wr_b} "
          f"p={pv:.3f}{sig} ({period_days}d收益)")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def run(factor_name: str = None, period_days: int = 5, save: bool = True):
    rows = _load_signals(factor_name)
    if not rows:
        log.info("无数据 (请先运行 factor_backfill.py 回填收益率)")
        return

    log.info(f"共 {len(rows)} 条信号记录")

    # 按因子分组输出
    by_factor = defaultdict(list)
    for r in rows:
        by_factor[r["factor_name"]].append(r)

    for fn, frows in sorted(by_factor.items()):
        _print_factor(fn, frows, period_days, save)

    if save:
        log.info("因子统计已写入 factor_stats 表")


def main():
    ap = argparse.ArgumentParser(description="factor_analyze v1.0")
    ap.add_argument("--factor",   default=None, help="只分析指定因子")
    ap.add_argument("--period",   type=int, default=5, help="收益周期天数(1或5, default=5)")
    ap.add_argument("--no-save",  action="store_true", help="只打印不写DB")
    args = ap.parse_args()

    run(args.factor, args.period, save=not args.no_save)


if __name__ == "__main__":
    main()

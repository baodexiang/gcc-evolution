#!/usr/bin/env python3
"""
backfill.py — KEY-001 T07 价格回填 + retrospective 判定 (v1.0)
==============================================================
定时读取 state/audit/*.jsonl，对 retrospective="pending" 的记录
回填 price_after_1h/4h/1d/3d，并在 4h 窗口满足后完成 retrospective 判定。

判定逻辑:
  allowed/passed=True:
    price 朝信号方向移动 >= threshold → correct_pass
    price 朝反方向移动   >= threshold → false_pass
    价格变动 < threshold              → inconclusive
  allowed/passed=False:
    price 朝信号方向移动 >= threshold → false_block  (错杀了机会)
    price 朝反方向移动   >= threshold → correct_block (正确拦截)
    价格变动 < threshold              → inconclusive

运行方式:
    python backfill.py          # 运行一次
    python backfill.py --loop   # 每小时循环

依赖: yfinance
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("Backfill")

# ── 路径 ────────────────────────────────────────────────────────
SIGNAL_LOG  = os.path.join("state", "audit", "signal_log.jsonl")
FILTER_LOG  = os.path.join("state", "audit", "filter_log.jsonl")

# ── 回填窗口 (秒) ───────────────────────────────────────────────
WINDOWS = {
    "price_after_1h": 1 * 3600,
    "price_after_4h": 4 * 3600,
    "price_after_1d": 24 * 3600,
    "price_after_3d": 72 * 3600,
}

# retrospective 判定最小窗口: 4h
RETRO_MIN_SECONDS = 4 * 3600
# 价格变动判定阈值 (绝对百分比)
RETRO_THRESHOLD_PCT = 0.5  # 0.5%

# ── 品种映射: 主程序符号 → yfinance 符号 ────────────────────────
SYM_MAP = {
    "BTCUSDC": "BTC-USD",
    "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD",
    "ZECUSDC": "ZEC-USD",
}

LOOP_INTERVAL = 3600  # 1小时


# ═══════════════════════════════════════════════════════════════
# 价格获取 (带缓存)
# ═══════════════════════════════════════════════════════════════

# _price_cache[yf_sym] = DataFrame (1h OHLCV, 最近10天)
_price_cache: dict = {}
_cache_ts: dict = {}
_CACHE_TTL = 3600  # 1小时内重用缓存


def _yf_sym(symbol: str) -> str:
    return SYM_MAP.get(symbol, symbol)


def _get_ohlcv(symbol: str) -> "pd.DataFrame | None":
    """拉取最近10天1h OHLCV, 带1小时内存缓存"""
    import pandas as pd
    yf_sym = _yf_sym(symbol)
    now = time.time()

    if yf_sym in _price_cache and now - _cache_ts.get(yf_sym, 0) < _CACHE_TTL:
        return _price_cache[yf_sym]

    try:
        import yfinance as yf
        df = yf.download(yf_sym, period="10d", interval="1h",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index, utc=True)
        _price_cache[yf_sym] = df
        _cache_ts[yf_sym] = now
        return df
    except Exception as e:
        log.warning(f"  yfinance拉取失败({yf_sym}): {e}")
        return None


def _price_at(symbol: str, target_dt: datetime) -> "float | None":
    """返回最接近 target_dt 的收盘价 (允许±2小时误差)"""
    df = _get_ohlcv(symbol)
    if df is None or df.empty:
        return None
    try:
        diff = abs(df.index - target_dt)
        idx = diff.argmin()
        if diff[idx].total_seconds() > 2 * 3600:
            return None  # 没有足够接近的数据点
        return float(df["Close"].iloc[idx])
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# retrospective 判定
# ═══════════════════════════════════════════════════════════════

def _classify(allowed: bool, direction: str, signal_price: float, price_after: float) -> str:
    """
    根据信号方向计算方向性收益，判定 correct_pass/false_pass/
    correct_block/false_block/inconclusive
    """
    if signal_price <= 0 or price_after <= 0:
        return "inconclusive"

    move_pct = (price_after - signal_price) / signal_price * 100
    direction_correct = (
        move_pct >= RETRO_THRESHOLD_PCT  if direction == "BUY"
        else move_pct <= -RETRO_THRESHOLD_PCT
    )
    direction_against = (
        move_pct <= -RETRO_THRESHOLD_PCT if direction == "BUY"
        else move_pct >= RETRO_THRESHOLD_PCT
    )

    if allowed:
        if direction_correct: return "correct_pass"
        if direction_against: return "false_pass"
        return "inconclusive"
    else:
        if direction_correct: return "false_block"
        if direction_against: return "correct_block"
        return "inconclusive"


# ═══════════════════════════════════════════════════════════════
# 单条记录回填
# ═══════════════════════════════════════════════════════════════

def _backfill_record(rec: dict) -> tuple[dict, bool]:
    """
    对一条记录执行回填。
    Returns: (updated_record, was_changed)
    """
    if rec.get("retrospective") not in ("pending", None):
        return rec, False  # 已判定，跳过

    ts_str = rec.get("ts")
    if not ts_str:
        return rec, False

    try:
        signal_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return rec, False

    now_utc = datetime.now(timezone.utc)
    age_sec = (now_utc - signal_ts).total_seconds()
    changed = False

    symbol    = rec.get("symbol", "")
    direction = rec.get("direction", "BUY")
    # signal_log 用 signal_price; filter_log 用 price_at_signal
    signal_price = rec.get("signal_price") or rec.get("price_at_signal") or 0.0
    # signal_log 用 allowed; filter_log 用 passed
    allowed = rec.get("allowed") if rec.get("allowed") is not None else rec.get("passed", False)

    # ── 回填各时间窗口价格 ──
    for field, offset_sec in WINDOWS.items():
        if rec.get(field) is not None:
            continue  # 已有数据
        if age_sec < offset_sec:
            continue  # 时间未到
        target_dt = signal_ts + timedelta(seconds=offset_sec)
        price = _price_at(symbol, target_dt)
        if price is not None:
            rec[field] = round(price, 4)
            changed = True
            log.info(f"  {symbol} {direction} {field}={price:.4f}")

    # ── retrospective 判定 (≥4h 且有 price_after_4h) ──
    if age_sec >= RETRO_MIN_SECONDS and rec.get("price_after_4h"):
        retro = _classify(
            allowed=bool(allowed),
            direction=direction,
            signal_price=float(signal_price),
            price_after=float(rec["price_after_4h"]),
        )
        rec["retrospective"] = retro
        rec["retrospective_reason"] = (
            f"4h_price={rec['price_after_4h']:.4f} "
            f"signal={signal_price:.4f} "
            f"move={((rec['price_after_4h'] - float(signal_price)) / float(signal_price) * 100):.2f}% "
            f"threshold={RETRO_THRESHOLD_PCT}%"
        )
        changed = True
        log.info(f"  {symbol} {direction} retrospective={retro}")

    return rec, changed


# ═══════════════════════════════════════════════════════════════
# 文件级处理
# ═══════════════════════════════════════════════════════════════

def _process_file(path: str) -> tuple[int, int]:
    """
    读取 JSONL → 回填 → 写回。
    Returns: (total_records, updated_count)
    """
    if not os.path.exists(path):
        return 0, 0

    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception as e:
        log.error(f"  读取 {path} 失败: {e}")
        return 0, 0

    updated = 0
    new_records = []
    for rec in records:
        new_rec, changed = _backfill_record(rec)
        new_records.append(new_rec)
        if changed:
            updated += 1

    if updated > 0:
        try:
            with open(path, "w", encoding="utf-8") as f:
                for rec in new_records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.info(f"  {os.path.basename(path)}: {updated}/{len(records)} 条已更新")
        except Exception as e:
            log.error(f"  写回 {path} 失败: {e}")

    return len(records), updated


# ═══════════════════════════════════════════════════════════════
# 统计摘要
# ═══════════════════════════════════════════════════════════════

def _print_summary(path: str):
    """打印当前 retrospective 分布"""
    if not os.path.exists(path):
        return
    counts: dict = {}
    pending = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                r = rec.get("retrospective", "pending")
                if r == "pending":
                    pending += 1
                else:
                    counts[r] = counts.get(r, 0) + 1
    except Exception:
        return

    total_judged = sum(counts.values())
    if total_judged == 0 and pending == 0:
        return

    parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    parts.append(f"pending={pending}")
    log.info(f"  {os.path.basename(path)} 分布: {' | '.join(parts)}")

    # 计算关键指标
    cp = counts.get("correct_pass", 0)
    fp = counts.get("false_pass", 0)
    cb = counts.get("correct_block", 0)
    fb = counts.get("false_block", 0)
    if cp + fp > 0:
        log.info(f"    pass_accuracy={cp/(cp+fp):.1%} ({cp}/{cp+fp})")
    if cb + fb > 0:
        log.info(f"    block_accuracy={cb/(cb+fb):.1%} false_block_rate={fb/(cb+fb):.1%} ({fb}/{cb+fb})")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def run_once():
    log.info("=== backfill 开始 ===")
    _price_cache.clear()  # 每轮清空缓存，拉最新数据

    for path in [SIGNAL_LOG, FILTER_LOG]:
        log.info(f"处理 {path}...")
        total, updated = _process_file(path)
        if total == 0:
            log.info(f"  {path} 不存在或为空，跳过")
        else:
            log.info(f"  共 {total} 条，本轮更新 {updated} 条")
            _print_summary(path)

    log.info("=== backfill 完成 ===")


def main():
    global RETRO_THRESHOLD_PCT
    ap = argparse.ArgumentParser(description="Backfill v1.0 — KEY-001 T07 价格回填")
    ap.add_argument("--loop", action="store_true", help=f"每{LOOP_INTERVAL//3600}小时循环")
    ap.add_argument("--threshold", type=float, default=RETRO_THRESHOLD_PCT,
                    help=f"retrospective 判定阈值%% (default={RETRO_THRESHOLD_PCT})")
    args = ap.parse_args()

    RETRO_THRESHOLD_PCT = args.threshold

    if args.loop:
        log.info(f"循环模式: 每 {LOOP_INTERVAL // 3600} 小时刷新")
        while True:
            try:
                run_once()
            except Exception as e:
                log.error(f"run_once 失败: {e}", exc_info=True)
            log.info(f"下次运行: {LOOP_INTERVAL // 3600} 小时后")
            time.sleep(LOOP_INTERVAL)
    else:
        run_once()


if __name__ == "__main__":
    main()

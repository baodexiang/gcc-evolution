"""
GCC-0019: KNN经验卡历史回填
读signal_log → 拉历史价格 → 算outcome → 写经验卡

数据源: yfinance(美股+加密日线回退) / Coinbase(加密)
"""
import json
import time
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

SIGNAL_LOG = Path("state/audit/signal_log.jsonl")
KNN_FILE = Path("state/gcc_knn_experience.jsonl")
PROGRESS_FILE = Path("state/_knn_backfill_progress.json")

# 加密品种
CRYPTO_SYMBOLS = {"BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC", "OPUSDC"}

# Coinbase product ID映射
COINBASE_PRODUCT_MAP = {
    "BTCUSDC": "BTC-USDC", "ETHUSDC": "ETH-USDC",
    "SOLUSDC": "SOL-USDC", "ZECUSDC": "ZEC-USDC", "OPUSDC": "OP-USDC",
}

# 价格缓存 (避免重复拉同品种同日)
_price_cache = {}  # key="SYMBOL_YYYYMMDD_HH" → price


def _get_price_coinbase(symbol: str, target_ts: datetime) -> float:
    """Coinbase API拉历史K线价格"""
    try:
        from coinbase_data_provider import _public_get, _coin_product_id
        product_id = COINBASE_PRODUCT_MAP.get(symbol)
        if not product_id:
            product_id = _coin_product_id(symbol)
        if not product_id:
            return 0.0
        # 用1小时K线, 拉目标时间前后4小时
        start_ts = int(target_ts.timestamp()) - 14400
        end_ts = int(target_ts.timestamp()) + 14400
        data = _public_get(
            f"/api/v3/brokerage/market/products/{product_id}/candles"
            f"?granularity=ONE_HOUR&start={start_ts}&end={end_ts}&limit=20"
        )
        if data and "candles" in data:
            candles = data["candles"]
            if candles:
                # 找最接近target_ts的K线
                target_epoch = target_ts.timestamp()
                best = min(candles, key=lambda c: abs(int(c.get("start", 0)) - target_epoch))
                price = float(best.get("close", 0))
                if price > 0:
                    return price
    except Exception:
        pass
    return 0.0


def _get_price_schwab(symbol: str, target_ts: datetime) -> float:
    """Schwab API拉历史价格(美股)"""
    try:
        from schwab_data_provider import get_provider
        provider = get_provider()
        df = provider.get_kline(symbol, interval="1h", bars=50,
                                 end_date=target_ts.strftime("%Y-%m-%d"))
        if df is not None and not df.empty and "close" in df.columns:
            df.index = df.index.tz_localize(None) if df.index.tz is None else df.index.tz_convert(None)
            target_naive = target_ts.replace(tzinfo=None)
            diffs = abs(df.index - target_naive)
            closest_idx = diffs.argmin()
            price = float(df["close"].iloc[closest_idx])
            if price > 0:
                return price
    except Exception:
        pass
    return 0.0


def _get_price_yfinance(symbol: str, target_ts: datetime) -> float:
    """yfinance拉历史价格(fallback)"""
    try:
        import yfinance as yf
        start = (target_ts - timedelta(hours=6)).strftime("%Y-%m-%d")
        end = (target_ts + timedelta(hours=6)).strftime("%Y-%m-%d")
        hist = yf.Ticker(symbol).history(start=start, end=end, interval="1h")
        if hist is not None and not hist.empty and "Close" in hist.columns:
            hist.index = hist.index.tz_localize(None) if hist.index.tz is None else hist.index.tz_convert(None)
            target_naive = target_ts.replace(tzinfo=None)
            diffs = abs(hist.index - target_naive)
            closest_idx = diffs.argmin()
            price = float(hist["Close"].iloc[closest_idx])
            if price > 0:
                return price
    except Exception:
        pass
    return 0.0


def _get_price_at(symbol: str, target_ts: datetime) -> float:
    """拉取指定时间点的价格 — 优先链: Coinbase(加密) / Schwab(美股) → yfinance(fallback)"""
    cache_key = f"{symbol}_{target_ts.strftime('%Y%m%d_%H')}"
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    price = 0.0
    if symbol in CRYPTO_SYMBOLS:
        # 加密: Coinbase优先
        price = _get_price_coinbase(symbol, target_ts)
    else:
        # 美股: Schwab优先 → yfinance fallback
        price = _get_price_schwab(symbol, target_ts)
        if price <= 0:
            price = _get_price_yfinance(symbol, target_ts)

    if price > 0:
        _price_cache[cache_key] = price
    return price


def _compute_outcome(direction: str, entry_price: float, future_price: float,
                     threshold_pct: float = 0.5) -> bool:
    """判断信号是否正确
    BUY: 后续涨超threshold → True
    SELL: 后续跌超threshold → True
    """
    if entry_price <= 0 or future_price <= 0:
        return None
    change_pct = (future_price - entry_price) / entry_price * 100
    if direction == "BUY":
        return change_pct > threshold_pct
    elif direction == "SELL":
        return change_pct < -threshold_pct
    return None


def _signal_to_features(sig: dict) -> list:
    """signal_log字段 → 25维KNN特征"""
    return [
        float(sig.get("n_quality", 0) or 0),
        float(sig.get("n_retrace_ratio", 0) or 0),
        1.0 if sig.get("n_extension_ok") else 0.0,
        float(sig.get("n_leg1", 0) or 0),
        float(sig.get("n_leg2", 0) or 0),
        float(sig.get("n_leg3", 0) or 0),
        float(sig.get("signal_strength", 0) or 0),
        float(sig.get("signal_price", 0) or 0),
        1.0 if sig.get("n_wave5_divergence") else 0.0,
        # n_pattern编码
        {"PERFECT_N": 1.0, "SHALLOW_N": 0.8, "DEEP_PULLBACK": 0.6,
         "SIDE": 0.3, "FAILED_N": 0.1}.get(sig.get("n_pattern", ""), 0.5),
        # n_direction编码
        {"UP": 1.0, "DOWN": -1.0, "NONE": 0.0}.get(sig.get("n_direction", ""), 0.0),
        # 信号方向编码
        1.0 if sig.get("direction") == "BUY" else -1.0,
        # allowed
        1.0 if sig.get("allowed") else 0.0,
        # 填充到25维
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    ]


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_processed_idx": 0, "total_written": 0, "errors": 0}


def save_progress(prog: dict):
    PROGRESS_FILE.write_text(json.dumps(prog, indent=2), encoding="utf-8")


def run_backfill(batch_size: int = 100, max_total: int = 0):
    """分批回填, 可中断续跑"""
    # 读signal_log
    with open(SIGNAL_LOG, "r", encoding="utf-8") as f:
        all_signals = [json.loads(l) for l in f if l.strip()]

    prog = load_progress()
    start_idx = prog["last_processed_idx"]
    total_written = prog["total_written"]
    errors = prog["errors"]

    # 已有经验卡的signal_id集合 (去重)
    existing_ids = set()
    if KNN_FILE.exists():
        with open(KNN_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    sid = e.get("signal_id", "")
                    if sid:
                        existing_ids.add(sid)
                except Exception:
                    pass

    print(f"Signal log: {len(all_signals)} total, starting from idx={start_idx}")
    print(f"Existing KNN cards: {len(existing_ids)}")
    print(f"Batch size: {batch_size}")

    batch_count = 0
    new_cards = 0

    for i in range(start_idx, len(all_signals)):
        if max_total > 0 and new_cards >= max_total:
            print(f"Reached max_total={max_total}, stopping")
            break

        sig = all_signals[i]
        signal_id = sig.get("signal_id", "")

        # 跳过已回填的
        if signal_id in existing_ids:
            continue

        symbol = sig.get("symbol", "")
        direction = sig.get("direction", "")
        ts_str = sig.get("ts", "")
        entry_price = float(sig.get("signal_price", 0) or 0)

        if not symbol or direction not in ("BUY", "SELL") or entry_price <= 0:
            continue

        # 解析时间
        try:
            sig_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue

        # 4小时后价格
        target_ts = sig_ts + timedelta(hours=4)

        # 如果4h后的时间还没到(未来), 跳过
        if target_ts > datetime.now(timezone.utc):
            continue

        # 先看signal_log里有没有price_after_4h
        price_4h = sig.get("price_after_4h")
        if price_4h is None:
            # 需要拉价格
            price_4h = _get_price_at(symbol, target_ts.replace(tzinfo=None))
            batch_count += 1
            if batch_count % 10 == 0:
                time.sleep(1)  # 控制API频率

        if not price_4h or price_4h <= 0:
            errors += 1
            continue

        # 算outcome
        outcome = _compute_outcome(direction, entry_price, float(price_4h))
        if outcome is None:
            continue

        # 写经验卡
        card = {
            "symbol": symbol,
            "action": direction,
            "features": _signal_to_features(sig),
            "outcome": outcome,
            "ts": ts_str,
            "price": entry_price,
            "ref_price": float(price_4h),
            "strongest_source": sig.get("source", "signal_log"),
            "source": "backfill_gcc0019",
            "signal_id": signal_id,
            "pnl_pct": round((float(price_4h) - entry_price) / entry_price * 100, 3),
        }

        with open(KNN_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

        existing_ids.add(signal_id)
        new_cards += 1
        total_written += 1

        if new_cards % 50 == 0:
            print(f"  Progress: {new_cards} new cards, idx={i}/{len(all_signals)}, errors={errors}")
            prog["last_processed_idx"] = i
            prog["total_written"] = total_written
            prog["errors"] = errors
            save_progress(prog)

    # 最终保存
    prog["last_processed_idx"] = min(i + 1 if 'i' in dir() else start_idx, len(all_signals))
    prog["total_written"] = total_written
    prog["errors"] = errors
    save_progress(prog)

    print(f"\n=== 回填完成 ===")
    print(f"新写入: {new_cards} 条经验卡")
    print(f"累计: {total_written} 条")
    print(f"错误: {errors}")
    print(f"KNN总量: {len(existing_ids)}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="GCC-0019 KNN经验卡历史回填")
    ap.add_argument("--batch", type=int, default=200, help="每批处理数")
    ap.add_argument("--max", type=int, default=0, help="最大回填数(0=不限)")
    ap.add_argument("--dry-run", action="store_true", help="预览不写入")
    args = ap.parse_args()

    if args.dry_run:
        print("DRY RUN - 只预览不写入")
        with open(SIGNAL_LOG, "r", encoding="utf-8") as f:
            sigs = [json.loads(l) for l in f if l.strip()]
        has_price = sum(1 for s in sigs if s.get("price_after_4h"))
        pending = sum(1 for s in sigs if s.get("retrospective") == "pending")
        print(f"Total: {len(sigs)}, has_4h_price: {has_price}, pending: {pending}")
        print(f"Need price fetch: {pending - has_price}")
    else:
        run_backfill(batch_size=args.batch, max_total=args.max)

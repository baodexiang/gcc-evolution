"""
coinbase_data_provider.py — Coinbase 市场数据提供器
使用公开市场数据端点（无需认证），提供 OBI + CVD 数据。

OBI (Order Book Imbalance): 买卖盘不平衡度
  基于 ticker best_bid/best_ask + 近期成交方向
  > 0 → 买压强, < 0 → 卖压强

CVD (Cumulative Volume Delta): 累积成交量差
  = Σ(buy_volume) - Σ(sell_volume)  (最近N笔成交)
  > 0 → 主买, < 0 → 主卖
"""

import logging
import time
import requests
from typing import Dict, List, Optional

logger = logging.getLogger("coinbase.data")

_BASE_URL = "https://api.coinbase.com"
_TIMEOUT = 10

# 缓存
_cache: Dict[str, dict] = {}
_cache_ts: Dict[str, float] = {}
_CACHE_TTL = 30  # 30秒缓存


def _coin_product_id(symbol: str) -> Optional[str]:
    """转换主程序品种名到 Coinbase product_id。
    BTCUSDC → BTC-USDC, ETHUSDC → ETH-USDC, BTC-USD → BTC-USD
    """
    if "-" in symbol:
        return symbol  # 已经是 product_id 格式
    for suffix in ("USDC", "USDT", "USD"):
        if symbol.endswith(suffix):
            base = symbol[:-len(suffix)]
            return f"{base}-{suffix}"
    return None


def _public_get(path: str) -> Optional[dict]:
    """公开端点 GET 请求（无需认证）。"""
    try:
        r = requests.get(f"{_BASE_URL}{path}", timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
        logger.debug("[COINBASE] GET %s → HTTP %d", path, r.status_code)
        return None
    except Exception as e:
        logger.debug("[COINBASE] GET %s error: %s", path, e)
        return None


def get_ticker(symbol: str) -> dict:
    """公开 ticker: best_bid/best_ask + 最近成交。
    返回: {"best_bid": float, "best_ask": float, "trades": list}
    """
    product_id = _coin_product_id(symbol)
    if not product_id:
        return {"best_bid": 0, "best_ask": 0, "trades": []}

    data = _public_get(
        f"/api/v3/brokerage/market/products/{product_id}/ticker"
    )
    if not data:
        return {"best_bid": 0, "best_ask": 0, "trades": []}

    return {
        "best_bid": float(data.get("best_bid", 0) or 0),
        "best_ask": float(data.get("best_ask", 0) or 0),
        "trades": data.get("trades", []),
    }


def get_recent_trades(symbol: str, limit: int = 100) -> list:
    """获取最近N笔成交（公开 ticker 端点）。
    返回: [{"price": float, "size": float, "side": "BUY"/"SELL", "time": str}, ...]
    """
    ticker = get_ticker(symbol)
    trades = []
    for t in ticker.get("trades", [])[:limit]:
        trades.append({
            "price": float(t.get("price", 0)),
            "size": float(t.get("size", 0)),
            "side": t.get("side", "UNKNOWN"),
            "time": t.get("time", ""),
        })
    return trades


def get_candles(symbol: str, granularity: str = "ONE_HOUR",
                limit: int = 20) -> list:
    """公开 candles 端点。
    返回: [{"open": float, "high": float, "low": float,
            "close": float, "volume": float, "start": str}, ...]
    """
    product_id = _coin_product_id(symbol)
    if not product_id:
        return []

    # 用start/end时间范围确保拿到足够K线
    _gran_seconds = {
        "ONE_MINUTE": 60, "FIVE_MINUTE": 300, "FIFTEEN_MINUTE": 900,
        "THIRTY_MINUTE": 1800, "ONE_HOUR": 3600, "TWO_HOUR": 7200,
        "SIX_HOUR": 21600, "ONE_DAY": 86400,
    }
    _gs = _gran_seconds.get(granularity, 3600)
    import time as _t
    _end = int(_t.time())
    _start = _end - _gs * limit * 2  # 2x余量，应对缺失K线

    data = _public_get(
        f"/api/v3/brokerage/market/products/{product_id}/candles"
        f"?granularity={granularity}&start={_start}&end={_end}&limit={min(limit * 2, 300)}"
    )
    if not data or "candles" not in data:
        return []

    candles = []
    for c in data["candles"]:
        candles.append({
            "open": float(c.get("open", 0)),
            "high": float(c.get("high", 0)),
            "low": float(c.get("low", 0)),
            "close": float(c.get("close", 0)),
            "volume": float(c.get("volume", 0)),
            "start": c.get("start", ""),
        })
    return candles


def get_obi(symbol: str) -> dict:
    """计算 Order Book Imbalance。
    基于 ticker 的 best_bid/best_ask + 成交方向统计。
    返回: {"obi": float [-1,1], "obi_bias": str, "bid_size": float, "ask_size": float}
    """
    cache_key = f"obi_{symbol}"
    now = time.time()
    if cache_key in _cache and now - _cache_ts.get(cache_key, 0) < _CACHE_TTL:
        return _cache[cache_key]

    ticker = get_ticker(symbol)
    trades = ticker.get("trades", [])

    if not trades:
        result = {"obi": 0.0, "obi_bias": "UNKNOWN", "bid_size": 0, "ask_size": 0}
        _cache[cache_key] = result
        _cache_ts[cache_key] = now
        return result

    # 用成交方向统计 OBI: BUY成交量 vs SELL成交量
    buy_size = sum(float(t.get("size", 0)) for t in trades if t.get("side") == "BUY")
    sell_size = sum(float(t.get("size", 0)) for t in trades if t.get("side") == "SELL")
    total = buy_size + sell_size

    if total == 0:
        result = {"obi": 0.0, "obi_bias": "UNKNOWN", "bid_size": 0, "ask_size": 0}
    else:
        obi = (buy_size - sell_size) / total
        if obi > 0.15:
            bias = "BUY_PRESSURE"
        elif obi < -0.15:
            bias = "SELL_PRESSURE"
        else:
            bias = "NEUTRAL"
        result = {
            "obi": round(obi, 4),
            "obi_bias": bias,
            "bid_size": round(buy_size, 6),
            "ask_size": round(sell_size, 6),
        }

    _cache[cache_key] = result
    _cache_ts[cache_key] = now
    return result


def get_cvd(symbol: str) -> dict:
    """计算 Cumulative Volume Delta (最近成交)。
    CVD = Σ(buy_volume) - Σ(sell_volume)
    返回: {"cvd": float, "cvd_bias": str, "buy_vol": float, "sell_vol": float, "trade_count": int}
    """
    cache_key = f"cvd_{symbol}"
    now = time.time()
    if cache_key in _cache and now - _cache_ts.get(cache_key, 0) < _CACHE_TTL:
        return _cache[cache_key]

    trades = get_recent_trades(symbol, limit=100)
    if not trades:
        result = {"cvd": 0.0, "cvd_bias": "UNKNOWN", "buy_vol": 0, "sell_vol": 0, "trade_count": 0}
        _cache[cache_key] = result
        _cache_ts[cache_key] = now
        return result

    buy_vol = sum(t["size"] for t in trades if t["side"] == "BUY")
    sell_vol = sum(t["size"] for t in trades if t["side"] == "SELL")
    cvd = buy_vol - sell_vol
    total = buy_vol + sell_vol

    if total == 0:
        bias = "UNKNOWN"
    elif cvd / total > 0.15:
        bias = "BUY_DOMINANT"
    elif cvd / total < -0.15:
        bias = "SELL_DOMINANT"
    else:
        bias = "BALANCED"

    result = {
        "cvd": round(cvd, 6),
        "cvd_bias": bias,
        "buy_vol": round(buy_vol, 6),
        "sell_vol": round(sell_vol, 6),
        "trade_count": len(trades),
    }
    _cache[cache_key] = result
    _cache_ts[cache_key] = now
    return result


def get_market_data(symbol: str) -> dict:
    """一次获取 OBI + CVD。
    返回: {"obi": {...}, "cvd": {...}}
    """
    return {
        "obi": get_obi(symbol),
        "cvd": get_cvd(symbol),
    }

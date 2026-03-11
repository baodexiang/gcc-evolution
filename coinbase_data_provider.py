"""
coinbase_data_provider.py — Coinbase 市场数据提供器
复用 coinbase_sync_v6.py 的 JWT 认证，提供 OBI + CVD 数据。

OBI (Order Book Imbalance): 买卖盘不平衡度
  = (bid_size - ask_size) / (bid_size + ask_size)
  > 0 → 买压强, < 0 → 卖压强

CVD (Cumulative Volume Delta): 累积成交量差
  = Σ(buy_volume) - Σ(sell_volume)  (最近N笔成交)
  > 0 → 主买, < 0 → 主卖
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("coinbase.data")

# 复用 coinbase_sync_v6 的认证
try:
    from coinbase_sync_v6 import api_request, SYMBOL_MAP
    _HAS_COINBASE = True
except ImportError:
    _HAS_COINBASE = False
    logger.warning("[COINBASE] coinbase_sync_v6 not available")

# 缓存
_cache: Dict[str, dict] = {}
_cache_ts: Dict[str, float] = {}
_CACHE_TTL = 30  # 30秒缓存


def _coin_product_id(symbol: str) -> Optional[str]:
    """转换主程序品种名到 Coinbase product_id。
    BTCUSDC → BTC-USDC, ETHUSDC → ETH-USDC
    """
    # 尝试常见后缀
    for suffix in ("USDC", "USD"):
        if symbol.endswith(suffix):
            base = symbol[:-len(suffix)]
            return f"{base}-{suffix}"
    return None


def get_order_book(symbol: str, level: int = 10) -> dict:
    """获取订单簿前N档。
    返回: {"bids": [(price, size), ...], "asks": [(price, size), ...]}
    """
    if not _HAS_COINBASE:
        return {"bids": [], "asks": []}

    product_id = _coin_product_id(symbol)
    if not product_id:
        return {"bids": [], "asks": []}

    try:
        path = f"/api/v3/brokerage/product_book?product_id={product_id}&limit={level}"
        data = api_request("GET", path)
        if not data or "pricebook" not in data:
            return {"bids": [], "asks": []}

        book = data["pricebook"]
        bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])]
        asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])]
        return {"bids": bids, "asks": asks}
    except Exception as e:
        logger.debug("[COINBASE] get_order_book %s: %s", symbol, e)
        return {"bids": [], "asks": []}


def get_obi(symbol: str) -> dict:
    """计算 Order Book Imbalance。
    OBI = (bid_size - ask_size) / (bid_size + ask_size)
    返回: {"obi": float [-1,1], "obi_bias": "BUY_PRESSURE"/"SELL_PRESSURE"/"NEUTRAL",
            "bid_size": float, "ask_size": float}
    """
    cache_key = f"obi_{symbol}"
    now = time.time()
    if cache_key in _cache and now - _cache_ts.get(cache_key, 0) < _CACHE_TTL:
        return _cache[cache_key]

    book = get_order_book(symbol, level=10)
    bid_size = sum(s for _, s in book["bids"])
    ask_size = sum(s for _, s in book["asks"])
    total = bid_size + ask_size

    if total == 0:
        result = {"obi": 0.0, "obi_bias": "UNKNOWN", "bid_size": 0, "ask_size": 0}
    else:
        obi = (bid_size - ask_size) / total
        if obi > 0.15:
            bias = "BUY_PRESSURE"
        elif obi < -0.15:
            bias = "SELL_PRESSURE"
        else:
            bias = "NEUTRAL"
        result = {
            "obi": round(obi, 4),
            "obi_bias": bias,
            "bid_size": round(bid_size, 6),
            "ask_size": round(ask_size, 6),
        }

    _cache[cache_key] = result
    _cache_ts[cache_key] = now
    return result


def get_recent_trades(symbol: str, limit: int = 100) -> list:
    """获取最近N笔成交。
    返回: [{"price": float, "size": float, "side": "BUY"/"SELL", "time": str}, ...]
    """
    if not _HAS_COINBASE:
        return []

    product_id = _coin_product_id(symbol)
    if not product_id:
        return []

    try:
        path = f"/api/v3/brokerage/market_trades?product_id={product_id}&limit={limit}"
        data = api_request("GET", path)
        if not data or "trades" not in data:
            return []

        trades = []
        for t in data["trades"]:
            trades.append({
                "price": float(t.get("price", 0)),
                "size": float(t.get("size", 0)),
                "side": t.get("side", "UNKNOWN"),
                "time": t.get("time", ""),
            })
        return trades
    except Exception as e:
        logger.debug("[COINBASE] get_recent_trades %s: %s", symbol, e)
        return []


def get_cvd(symbol: str) -> dict:
    """计算 Cumulative Volume Delta (最近100笔)。
    CVD = Σ(buy_volume) - Σ(sell_volume)
    返回: {"cvd": float, "cvd_bias": "BUY_DOMINANT"/"SELL_DOMINANT"/"BALANCED",
            "buy_vol": float, "sell_vol": float, "trade_count": int}
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

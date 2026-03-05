"""
Twelve Data Provider
====================
付费数据源 - 支持股票和加密货币分钟级数据
https://twelvedata.com/

定价: $8/月 (800 API calls/day)

v5.480 Update:
- 非交易时间处理: 使用缓存的历史数据，避免卡死
- 增加缓存时间: 交易时间60秒，非交易时间1小时
- 添加请求超时保护

v5.496 Update:
- 时区修复: 时间戳带东部时区信息
"""

import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional
from .base_provider import BaseDataProvider
import pytz

logger = logging.getLogger(__name__)

# v5.480: 长期缓存存储 (非交易时间使用)
_LONG_TERM_CACHE = {}


class TwelveDataProvider(BaseDataProvider):
    """Twelve Data API 数据提供者"""

    BASE_URL = "https://api.twelvedata.com"

    # 时间周期映射
    # v5.445: 添加2h周期支持
    INTERVAL_MAP = {
        "1m": "1min",
        "5m": "5min",
        "10m": "10min",  # 需要聚合
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "2h": "2h",      # v5.445: Added for crypto 2-hour cycle
        "4h": "4h",
        "1d": "1day",
    }

    def __init__(self, api_key: str, cache_ttl: int = 60):
        """
        初始化 Twelve Data Provider

        Args:
            api_key: Twelve Data API密钥
            cache_ttl: 缓存时间(秒)
        """
        super().__init__(cache_ttl)
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "AI-PRO-Trading/5.0"
        })
        logger.info("TwelveDataProvider initialized")

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "30m",
        limit: int = 100
    ) -> List[Dict]:
        """
        获取OHLCV数据

        Args:
            symbol: 股票代码 (e.g., "TSLA", "AAPL")
            timeframe: 时间周期 (5m, 15m, 30m, 1h, 4h, 1d)
            limit: 数据条数

        Returns:
            K线数据列表

        v5.480: 非交易时间处理
        - 交易时间: 正常请求API，缓存60秒
        - 非交易时间: 优先使用长期缓存，避免卡死
        """
        cache_key = f"twelvedata_{symbol}_{timeframe}_{limit}"
        long_cache_key = f"long_{cache_key}"

        # v5.480: 检查市场是否开盘
        market_open = self.is_market_open(symbol)

        # 短期缓存检查
        if self._is_cache_valid(cache_key):
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        # v5.480: 非交易时间优先使用长期缓存
        if not market_open:
            if long_cache_key in _LONG_TERM_CACHE:
                cached_data = _LONG_TERM_CACHE[long_cache_key]
                logger.info(f"[v5.480] Market closed, using cached data for {symbol} ({len(cached_data)} bars)")
                return cached_data
            logger.info(f"[v5.480] Market closed, no cache for {symbol}, attempting API fetch...")

        # 处理10分钟周期 (聚合5分钟)
        need_aggregate = False
        fetch_timeframe = timeframe
        fetch_limit = limit

        if timeframe == "10m":
            fetch_timeframe = "5m"
            fetch_limit = limit * 2 + 2
            need_aggregate = True

        interval = self.INTERVAL_MAP.get(fetch_timeframe, "30min")

        try:
            url = f"{self.BASE_URL}/time_series"
            params = {
                "symbol": symbol,
                "interval": interval,
                "outputsize": fetch_limit,
                "apikey": self.api_key,
                "format": "JSON"
            }

            logger.info(f"Fetching {symbol} {interval} from Twelve Data")

            # v5.480: 缩短超时时间，避免卡死
            timeout = 10 if market_open else 5
            response = self.session.get(url, params=params, timeout=timeout)

            if response.status_code != 200:
                logger.error(f"Twelve Data API error: {response.status_code}")
                # v5.480: API错误时返回长期缓存
                if long_cache_key in _LONG_TERM_CACHE:
                    logger.info(f"[v5.480] API error, using cached data for {symbol}")
                    return _LONG_TERM_CACHE[long_cache_key]
                return []

            data = response.json()

            # 检查错误
            if "code" in data and data["code"] != 200:
                logger.error(f"Twelve Data error: {data.get('message', 'Unknown error')}")
                # v5.480: API错误时返回长期缓存
                if long_cache_key in _LONG_TERM_CACHE:
                    logger.info(f"[v5.480] API error, using cached data for {symbol}")
                    return _LONG_TERM_CACHE[long_cache_key]
                return []

            values = data.get("values", [])
            if not values:
                logger.warning(f"No data returned for {symbol}")
                # v5.480: 无数据时返回长期缓存
                if long_cache_key in _LONG_TERM_CACHE:
                    logger.info(f"[v5.480] No new data, using cached data for {symbol}")
                    return _LONG_TERM_CACHE[long_cache_key]
                return []

            # 转换为标准格式 (Twelve Data返回最新的在前)
            # v5.496: 添加东部时区信息
            et_tz = pytz.timezone("America/New_York")
            bars = []
            for item in reversed(values):
                try:
                    # v5.496: 解析时间并添加东部时区
                    naive_dt = datetime.fromisoformat(item["datetime"].replace(" ", "T"))
                    aware_dt = et_tz.localize(naive_dt)
                    bars.append({
                        "timestamp": aware_dt,
                        "open": float(item["open"]),
                        "high": float(item["high"]),
                        "low": float(item["low"]),
                        "close": float(item["close"]),
                        "volume": int(float(item.get("volume", 0)))
                    })
                except (KeyError, ValueError) as e:
                    logger.warning(f"Skipping invalid bar: {e}")
                    continue

            # 聚合10分钟数据
            if need_aggregate and bars:
                bars = self._aggregate_bars(bars, 2)

            # 限制返回数量
            if len(bars) > limit:
                bars = bars[-limit:]

            if bars:
                # 短期缓存
                self._set_cache(cache_key, bars)
                # v5.480: 长期缓存 (用于非交易时间)
                _LONG_TERM_CACHE[long_cache_key] = bars
                logger.info(f"Got {len(bars)} bars for {symbol}, cached for off-hours use")

            return bars

        except requests.Timeout:
            logger.error(f"Twelve Data request timeout for {symbol}")
            # v5.480: 超时时返回长期缓存
            if long_cache_key in _LONG_TERM_CACHE:
                logger.info(f"[v5.480] Timeout, using cached data for {symbol}")
                return _LONG_TERM_CACHE[long_cache_key]
            return []
        except requests.RequestException as e:
            logger.error(f"Twelve Data request failed: {e}")
            # v5.480: 请求失败时返回长期缓存
            if long_cache_key in _LONG_TERM_CACHE:
                logger.info(f"[v5.480] Request failed, using cached data for {symbol}")
                return _LONG_TERM_CACHE[long_cache_key]
            return []
        except Exception as e:
            logger.error(f"Twelve Data error: {e}")
            # v5.480: 异常时返回长期缓存
            if long_cache_key in _LONG_TERM_CACHE:
                logger.info(f"[v5.480] Error, using cached data for {symbol}")
                return _LONG_TERM_CACHE[long_cache_key]
            return []

    def _aggregate_bars(self, bars: List[Dict], factor: int) -> List[Dict]:
        """
        聚合K线数据

        Args:
            bars: 原始K线
            factor: 聚合因子 (e.g., 2表示2根合1根)
        """
        if factor <= 1:
            return bars

        aggregated = []
        for i in range(0, len(bars) - factor + 1, factor):
            chunk = bars[i:i+factor]
            if len(chunk) == factor:
                aggregated.append({
                    "timestamp": chunk[0]["timestamp"],
                    "open": chunk[0]["open"],
                    "high": max(b["high"] for b in chunk),
                    "low": min(b["low"] for b in chunk),
                    "close": chunk[-1]["close"],
                    "volume": sum(b["volume"] for b in chunk)
                })

        return aggregated

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格

        Args:
            symbol: 股票代码

        Returns:
            当前价格
        """
        cache_key = f"twelvedata_price_{symbol}"
        if self._is_cache_valid(cache_key):
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        try:
            url = f"{self.BASE_URL}/price"
            params = {
                "symbol": symbol,
                "apikey": self.api_key
            }

            response = self.session.get(url, params=params, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()

            if "price" in data:
                price = float(data["price"])
                self._set_cache(cache_key, price)
                return price

            return None

        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None

    def is_market_open(self, symbol: str) -> bool:
        """
        检查市场是否开盘

        美股交易时间: 9:30 AM - 4:00 PM ET (周一至周五)
        """
        from datetime import datetime
        import pytz

        try:
            et_tz = pytz.timezone("US/Eastern")
            now = datetime.now(et_tz)

            # 周末休市
            if now.weekday() >= 5:
                return False

            # 交易时间 9:30 - 16:00
            market_open = now.replace(hour=9, minute=30, second=0)
            market_close = now.replace(hour=16, minute=0, second=0)

            return market_open <= now <= market_close

        except Exception:
            # 默认返回True，让API自己处理
            return True

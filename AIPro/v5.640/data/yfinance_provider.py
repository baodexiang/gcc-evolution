"""
YFinance Data Provider (Backup)
================================
免费备用数据源 - 当TwelveData失败时使用
https://github.com/ranaroussi/yfinance

v5.496 新增:
- 作为TwelveData的备用数据源
- 支持美股OHLCV数据
- 无需API密钥
- 时区修复: 时间戳带东部时区信息
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .base_provider import BaseDataProvider
import pytz

logger = logging.getLogger(__name__)

# 尝试导入yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed. Run: pip install yfinance")


class YFinanceProvider(BaseDataProvider):
    """YFinance 数据提供者 (免费备用)"""

    # 时间周期映射
    INTERVAL_MAP = {
        "1m": "1m",
        "5m": "5m",
        "10m": "5m",  # 需要聚合
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "2h": "1h",   # 需要聚合
        "4h": "1h",   # 需要聚合
        "1d": "1d",
    }

    # 周期对应的历史天数
    PERIOD_MAP = {
        "1m": "7d",
        "5m": "60d",
        "10m": "60d",
        "15m": "60d",
        "30m": "60d",
        "1h": "730d",
        "2h": "730d",
        "4h": "730d",
        "1d": "max",
    }

    def __init__(self, cache_ttl: int = 60):
        """
        初始化 YFinance Provider

        Args:
            cache_ttl: 缓存时间(秒)
        """
        super().__init__(cache_ttl)
        logger.info(f"YFinanceProvider initialized (available={YFINANCE_AVAILABLE})")

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100
    ) -> List[Dict]:
        """
        获取OHLCV数据

        Args:
            symbol: 股票代码 (e.g., "TSLA", "AAPL")
            timeframe: 时间周期 (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            limit: 数据条数

        Returns:
            K线数据列表
        """
        if not YFINANCE_AVAILABLE:
            logger.error("yfinance not available")
            return []

        cache_key = f"yfinance_{symbol}_{timeframe}_{limit}"

        # 缓存检查
        if self._is_cache_valid(cache_key):
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        try:
            # 确定聚合需求
            need_aggregate = False
            aggregate_factor = 1
            fetch_timeframe = timeframe

            if timeframe == "10m":
                fetch_timeframe = "5m"
                aggregate_factor = 2
                need_aggregate = True
            elif timeframe == "2h":
                fetch_timeframe = "1h"
                aggregate_factor = 2
                need_aggregate = True
            elif timeframe == "4h":
                fetch_timeframe = "1h"
                aggregate_factor = 4
                need_aggregate = True

            interval = self.INTERVAL_MAP.get(fetch_timeframe, "1h")
            period = self.PERIOD_MAP.get(fetch_timeframe, "60d")

            # 计算需要获取的数据量
            fetch_limit = limit * aggregate_factor + 10 if need_aggregate else limit + 10

            logger.info(f"[yfinance] Fetching {symbol} interval={interval} period={period}")

            # 获取数据
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"[yfinance] No data for {symbol}")
                return []

            # 转换为标准格式 (v5.496: 保留东部时区信息)
            et_tz = pytz.timezone("America/New_York")
            bars = []
            for idx, row in df.iterrows():
                try:
                    # v5.496: 转换到东部时区并保留时区信息
                    ts = idx
                    if hasattr(ts, 'tz'):
                        if ts.tz is None:
                            # 无时区 - 假设为东部时间
                            ts = et_tz.localize(ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts)
                        else:
                            # 有时区 - 转换到东部时间
                            ts = ts.astimezone(et_tz)
                            ts = ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts
                    else:
                        # Pandas Timestamp without tz attribute
                        ts = ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts
                        ts = et_tz.localize(ts)

                    bars.append({
                        "timestamp": ts,  # 保留时区信息
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"])
                    })
                except Exception as e:
                    logger.warning(f"Skipping bar: {e}")
                    continue

            # 聚合
            if need_aggregate and bars:
                bars = self._aggregate_bars(bars, aggregate_factor)

            # 限制返回数量
            if len(bars) > limit:
                bars = bars[-limit:]

            if bars:
                self._set_cache(cache_key, bars)
                logger.info(f"[yfinance] Got {len(bars)} bars for {symbol}")

            return bars

        except Exception as e:
            logger.error(f"[yfinance] Error fetching {symbol}: {e}")
            return []

    def _aggregate_bars(self, bars: List[Dict], factor: int) -> List[Dict]:
        """聚合K线数据"""
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
        """获取当前价格"""
        if not YFINANCE_AVAILABLE:
            return None

        cache_key = f"yfinance_price_{symbol}"
        if self._is_cache_valid(cache_key):
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price = info.get("regularMarketPrice") or info.get("currentPrice")

            if price:
                self._set_cache(cache_key, price)
                return float(price)

            return None

        except Exception as e:
            logger.error(f"[yfinance] Error getting price for {symbol}: {e}")
            return None

    def is_market_open(self, symbol: str) -> bool:
        """检查市场是否开盘"""
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
            return True

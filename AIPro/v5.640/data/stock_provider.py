"""
Stock Data Provider with Fallback
==================================
v5.496: TwelveData -> YFinance fallback chain

优先使用 TwelveData (付费，更稳定)
如果失败则回退到 YFinance (免费)
"""

import logging
from typing import List, Dict, Optional
from .base_provider import BaseDataProvider
from .twelvedata_provider import TwelveDataProvider
from .yfinance_provider import YFinanceProvider, YFINANCE_AVAILABLE

logger = logging.getLogger(__name__)


class StockDataProvider(BaseDataProvider):
    """
    股票数据提供者 (带Fallback)

    优先级:
    1. TwelveData (if API key configured)
    2. YFinance (free fallback)
    """

    def __init__(self, twelvedata_api_key: str = "", cache_ttl: int = 60):
        """
        初始化股票数据提供者

        Args:
            twelvedata_api_key: TwelveData API密钥 (可选)
            cache_ttl: 缓存时间(秒)
        """
        super().__init__(cache_ttl)

        self.twelvedata_provider = None
        self.yfinance_provider = None
        self.primary_source = "none"

        # 初始化 TwelveData (如果有API密钥)
        if twelvedata_api_key:
            try:
                self.twelvedata_provider = TwelveDataProvider(
                    api_key=twelvedata_api_key,
                    cache_ttl=cache_ttl
                )
                self.primary_source = "twelvedata"
                logger.info("[v5.496] StockDataProvider: TwelveData as primary")
            except Exception as e:
                logger.warning(f"[v5.496] TwelveData init failed: {e}")

        # 初始化 YFinance (作为备用)
        if YFINANCE_AVAILABLE:
            try:
                self.yfinance_provider = YFinanceProvider(cache_ttl=cache_ttl)
                if not self.twelvedata_provider:
                    self.primary_source = "yfinance"
                logger.info(f"[v5.496] StockDataProvider: YFinance as {'backup' if self.twelvedata_provider else 'primary'}")
            except Exception as e:
                logger.warning(f"[v5.496] YFinance init failed: {e}")

        if self.primary_source == "none":
            logger.error("[v5.496] No stock data provider available!")

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100
    ) -> List[Dict]:
        """
        获取OHLCV数据 (带fallback)

        尝试顺序:
        1. TwelveData (如果配置)
        2. YFinance (备用)
        """
        bars = []

        # 尝试 TwelveData
        if self.twelvedata_provider:
            try:
                bars = self.twelvedata_provider.get_ohlcv(symbol, timeframe, limit)
                if bars:
                    logger.debug(f"[v5.496] {symbol}: Got {len(bars)} bars from TwelveData")
                    return bars
                else:
                    logger.warning(f"[v5.496] {symbol}: TwelveData returned empty, trying fallback...")
            except Exception as e:
                logger.warning(f"[v5.496] {symbol}: TwelveData error: {e}, trying fallback...")

        # Fallback 到 YFinance
        if self.yfinance_provider:
            try:
                bars = self.yfinance_provider.get_ohlcv(symbol, timeframe, limit)
                if bars:
                    logger.info(f"[v5.496] {symbol}: Got {len(bars)} bars from YFinance (fallback)")
                    return bars
                else:
                    logger.warning(f"[v5.496] {symbol}: YFinance also returned empty")
            except Exception as e:
                logger.error(f"[v5.496] {symbol}: YFinance error: {e}")

        return bars

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格 (带fallback)"""
        price = None

        # 尝试 TwelveData
        if self.twelvedata_provider:
            try:
                price = self.twelvedata_provider.get_current_price(symbol)
                if price:
                    return price
            except Exception:
                pass

        # Fallback 到 YFinance
        if self.yfinance_provider:
            try:
                price = self.yfinance_provider.get_current_price(symbol)
                if price:
                    return price
            except Exception:
                pass

        return price

    def is_market_open(self, symbol: str) -> bool:
        """检查市场是否开盘"""
        # 使用任一可用的 provider
        if self.twelvedata_provider:
            return self.twelvedata_provider.is_market_open(symbol)
        if self.yfinance_provider:
            return self.yfinance_provider.is_market_open(symbol)
        return True  # 默认返回开盘

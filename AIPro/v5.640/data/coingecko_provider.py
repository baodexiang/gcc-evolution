"""
CoinGecko 数据源
================
使用CoinGecko免费API获取加密货币数据。
"""

import logging
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
import requests

from .base_provider import BaseDataProvider, get_ohlcv_cache

logger = logging.getLogger(__name__)


class CoinGeckoProvider(BaseDataProvider):
    """CoinGecko数据源 (加密货币)"""

    BASE_URL = "https://api.coingecko.com/api/v3"

    # CoinGecko ID映射 (Symbol → CoinGecko ID)
    SYMBOL_TO_ID = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "XRP": "ripple",
        "ADA": "cardano",
        "DOGE": "dogecoin",
        "DOT": "polkadot",
        "AVAX": "avalanche-2",
        "MATIC": "matic-network",
        "LINK": "chainlink",
        "UNI": "uniswap",
        "ATOM": "cosmos",
        "LTC": "litecoin",
        "BCH": "bitcoin-cash",
        "NEAR": "near",
        "APT": "aptos",
        "ARB": "arbitrum",
        "OP": "optimism",
        "ZEC": "zcash",
        "XLM": "stellar",
        "SUI": "sui",
        "PEPE": "pepe",
        "TRX": "tron",
        "ETC": "ethereum-classic",
        "FIL": "filecoin",
        "XMR": "monero",
        "HBAR": "hedera-hashgraph",
        "ICP": "internet-computer",
        "VET": "vechain",
        "AAVE": "aave",
    }

    # v5.487: 反向映射 (CoinGecko ID → Symbol) 用于处理遗留输入
    ID_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_ID.items()}

    # 时间周期映射 (CoinGecko用天数)
    # CoinGecko OHLC数据粒度规则:
    #   1-2天 → 30分钟间隔
    #   3-30天 → 4小时间隔
    #   31天以上 → 4天间隔
    # v5.445: 添加2h周期支持
    TIMEFRAME_DAYS = {
        "5m": 1,      # 1天数据 → 30分钟间隔 (CoinGecko最小)
        "10m": 1,     # 1天数据 → 30分钟间隔
        "15m": 1,     # 1天数据 → 30分钟间隔
        "30m": 1,     # 1天数据 → 30分钟间隔 (v5.435: 从7改为1)
        "1h": 2,      # 2天数据 → 30分钟间隔，然后聚合
        "2h": 7,      # v5.445: 7天数据 → 4小时间隔，然后聚合为2小时
        "4h": 14,     # 14天数据 → 4小时间隔
        "1d": 90,     # 90天数据 → 4天间隔，然后聚合
    }

    def __init__(self, cache_ttl: int = 60):
        super().__init__(cache_ttl)
        self._last_request_time = 0
        self._request_interval = 3.0  # v5.435: Increased from 1.5 to 3.0 for safer rate limiting
        self._max_retries = 2  # v5.487: Retry count for rate limiting
        self._retry_delay = 5.0  # v5.487: Base delay between retries

    def _rate_limit(self):
        """API速率限制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_interval:
            time.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()

    def _get_coin_id(self, symbol: str) -> str:
        """将交易代码转换为CoinGecko ID

        v5.487: 支持多种输入格式:
        - Symbol代码: "ZEC" → "zcash"
        - CoinGecko ID: "zcash" → "zcash"
        - 带USD后缀: "BTC-USD" → "bitcoin"
        """
        # 清理输入
        symbol_clean = symbol.upper().replace("-USD", "").replace("USD", "")

        # 1. 尝试直接映射 (Symbol → ID)
        if symbol_clean in self.SYMBOL_TO_ID:
            return self.SYMBOL_TO_ID[symbol_clean]

        # 2. 检查是否已经是CoinGecko ID (小写输入)
        symbol_lower = symbol.lower().replace("-usd", "").replace("usd", "")
        if symbol_lower in self.ID_TO_SYMBOL:
            return symbol_lower  # 已经是有效的CoinGecko ID

        # 3. 回退: 返回小写版本作为CoinGecko ID
        logger.debug(f"Unknown symbol {symbol}, using {symbol_lower} as CoinGecko ID")
        return symbol_lower

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "30m",
        limit: int = 100
    ) -> List[Dict]:
        """
        获取加密货币K线数据

        Args:
            symbol: 币种代码 (如 "BTC", "ETH", "bitcoin")
            timeframe: 时间周期
            limit: 返回数据条数

        Returns:
            K线数据列表
        """
        cache_key = self._get_cache_key(symbol, timeframe)
        if self._is_cache_valid(cache_key):
            cached = self._get_cache(cache_key)
            if cached:
                logger.debug(f"CoinGecko cache hit: {symbol} ({len(cached)} bars)")
                return cached[-limit:]

        try:
            coin_id = self._get_coin_id(symbol)
            days = self.TIMEFRAME_DAYS.get(timeframe, 7)
            logger.info(f"CoinGecko API call: {coin_id} ({days} days)")

            # CoinGecko OHLC endpoint with retry logic (v5.487)
            url = f"{self.BASE_URL}/coins/{coin_id}/ohlc"
            params = {
                "vs_currency": "usd",
                "days": days
            }

            data = None
            last_error = None
            for attempt in range(self._max_retries + 1):
                try:
                    self._rate_limit()
                    response = requests.get(url, params=params, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    break  # Success
                except requests.exceptions.HTTPError as e:
                    last_error = e
                    if e.response.status_code == 429:
                        # Rate limited - wait and retry
                        wait_time = self._retry_delay * (attempt + 1)
                        logger.warning(f"CoinGecko rate limited for {symbol}, retry {attempt+1}/{self._max_retries} after {wait_time}s")
                        if attempt < self._max_retries:
                            time.sleep(wait_time)
                            continue
                    raise  # Re-raise for other HTTP errors
                except requests.exceptions.Timeout:
                    last_error = Exception("Timeout")
                    if attempt < self._max_retries:
                        logger.warning(f"CoinGecko timeout for {symbol}, retry {attempt+1}/{self._max_retries}")
                        time.sleep(self._retry_delay)
                        continue
                    raise

            if data is None:
                raise last_error or Exception("No data received")

            if not data:
                logger.warning(f"CoinGecko no data: {symbol}")
                return []

            # 转换格式: [[timestamp, open, high, low, close], ...]
            bars = []
            for item in data:
                if len(item) >= 5:
                    bars.append({
                        # v5.435: 使用UTC时区，确保前端正确转换为纽约时间
                        "timestamp": datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc),
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": 0,  # OHLC endpoint不含volume
                    })

            # v5.487: 跳过volume API调用以减少速率限制问题
            # Volume数据对信号分析不是必需的，跳过可减少50%的API调用
            # 如需要volume，取消下面的注释：
            # bars = self._add_volume_data(coin_id, bars, days)

            # 根据timeframe过滤/聚合
            bars = self._filter_by_timeframe(bars, timeframe)

            # v5.440: 使用累积缓存合并数据
            ohlcv_cache = get_ohlcv_cache(symbol, timeframe)
            merged_bars = ohlcv_cache.merge(bars)
            logger.info(f"[v5.440] {symbol}/{timeframe}: API returned {len(bars)} bars, cache merged to {len(merged_bars)} bars")

            self._set_cache(cache_key, merged_bars)
            return merged_bars[-limit:]

        except requests.exceptions.HTTPError as e:
            error_type = "UNKNOWN"
            if e.response.status_code == 429:
                error_type = "RATE_LIMIT"
                logger.error(f"CoinGecko rate limited for {symbol} (coin_id={coin_id})")
                print(f"[CoinGecko RATE LIMIT] {symbol}: Too many requests, wait 1 minute")
            elif e.response.status_code == 404:
                error_type = "NOT_FOUND"
                logger.error(f"CoinGecko coin not found: {symbol} (coin_id={coin_id})")
                print(f"[CoinGecko NOT FOUND] {symbol}: coin_id '{coin_id}' not found")
            else:
                logger.error(f"CoinGecko HTTP error {symbol}: {e}")
                print(f"[CoinGecko HTTP ERROR] {symbol}: {e.response.status_code}")
            # v5.487: 尝试返回缓存数据
            return self._get_fallback_cache(symbol, timeframe, limit, error_type)
        except requests.exceptions.Timeout:
            logger.error(f"CoinGecko timeout for {symbol} (coin_id={coin_id})")
            print(f"[CoinGecko TIMEOUT] {symbol}: Request timed out")
            return self._get_fallback_cache(symbol, timeframe, limit, "TIMEOUT")
        except Exception as e:
            import traceback
            logger.error(f"CoinGecko fetch failed {symbol} (coin_id={coin_id}): {e}")
            print(f"[CoinGecko ERROR] {symbol}: {e}")
            print(traceback.format_exc())
            return self._get_fallback_cache(symbol, timeframe, limit, "ERROR")

    def _get_fallback_cache(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        error_type: str
    ) -> List[Dict]:
        """v5.487: 获取回退缓存数据"""
        # 尝试从累积缓存获取数据
        try:
            ohlcv_cache = get_ohlcv_cache(symbol, timeframe)
            if ohlcv_cache and ohlcv_cache.bars:
                logger.info(f"[v5.487] Using fallback cache for {symbol}/{timeframe} ({len(ohlcv_cache.bars)} bars) due to {error_type}")
                print(f"[CoinGecko FALLBACK] {symbol}: Using cached data ({len(ohlcv_cache.bars)} bars)")
                return ohlcv_cache.bars[-limit:]
        except Exception as e:
            logger.debug(f"Fallback cache failed for {symbol}: {e}")

        # 尝试从普通缓存获取（即使过期）
        cache_key = self._get_cache_key(symbol, timeframe)
        cached = self._get_cache(cache_key)
        if cached:
            logger.info(f"[v5.487] Using expired cache for {symbol}/{timeframe} ({len(cached)} bars) due to {error_type}")
            print(f"[CoinGecko FALLBACK] {symbol}: Using expired cache ({len(cached)} bars)")
            return cached[-limit:]

        logger.warning(f"No fallback cache available for {symbol}/{timeframe}")
        return []

    def _add_volume_data(
        self,
        coin_id: str,
        bars: List[Dict],
        days: int
    ) -> List[Dict]:
        """添加成交量数据 (v5.487: 优化为可选，失败不影响主数据)"""
        try:
            # v5.487: 跳过volume获取以减少API调用（volume对分析不是必需的）
            # 如果需要volume，取消下面的注释
            # return bars

            self._rate_limit()
            url = f"{self.BASE_URL}/coins/{coin_id}/market_chart"
            params = {
                "vs_currency": "usd",
                "days": days
            }
            response = requests.get(url, params=params, timeout=15)  # v5.487: 缩短超时
            response.raise_for_status()
            data = response.json()

            volumes = data.get("total_volumes", [])
            if not volumes:
                return bars

            # 创建时间戳到volume的映射
            vol_map = {}
            for item in volumes:
                ts = datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc)
                # 按小时聚合
                hour_key = ts.replace(minute=0, second=0, microsecond=0)
                vol_map[hour_key] = item[1]

            # 匹配volume到bars
            for bar in bars:
                hour_key = bar["timestamp"].replace(minute=0, second=0, microsecond=0)
                bar["volume"] = vol_map.get(hour_key, 0)

        except Exception as e:
            logger.debug(f"Failed to get volume: {e}")

        return bars

    def _filter_by_timeframe(
        self,
        bars: List[Dict],
        timeframe: str
    ) -> List[Dict]:
        """根据时间周期过滤/聚合K线"""
        if not bars:
            return bars

        # CoinGecko OHLC间隔:
        # 1-2天: 30分钟
        # 3-30天: 4小时
        # 31天以上: 4天

        # v5.445: 添加2h周期支持
        minutes_map = {
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "2h": 120,   # v5.445: Added
            "4h": 240,
            "1d": 1440,
        }

        target_minutes = minutes_map.get(timeframe, 30)

        # 如果目标周期大于数据周期，需要聚合
        if len(bars) >= 2:
            data_interval = (bars[1]["timestamp"] - bars[0]["timestamp"]).total_seconds() / 60

            if target_minutes > data_interval:
                return self._aggregate_bars(bars, target_minutes)

        return bars

    def _aggregate_bars(
        self,
        bars: List[Dict],
        target_minutes: int
    ) -> List[Dict]:
        """聚合K线到目标周期"""
        if not bars:
            return bars

        aggregated = []
        current_group = []
        group_start = None

        for bar in bars:
            bar_time = bar["timestamp"]

            # 计算所属的时间组
            minutes_since_midnight = bar_time.hour * 60 + bar_time.minute
            group_index = minutes_since_midnight // target_minutes
            group_time = bar_time.replace(
                hour=(group_index * target_minutes) // 60,
                minute=(group_index * target_minutes) % 60,
                second=0,
                microsecond=0
            )

            if group_start is None:
                group_start = group_time
                current_group = [bar]
            elif group_time == group_start:
                current_group.append(bar)
            else:
                # 保存当前组
                if current_group:
                    aggregated.append(self._merge_group(current_group))
                # 开始新组
                group_start = group_time
                current_group = [bar]

        # 保存最后一组
        if current_group:
            aggregated.append(self._merge_group(current_group))

        return aggregated

    def _merge_group(self, group: List[Dict]) -> Dict:
        """合并K线组"""
        return {
            "timestamp": group[0]["timestamp"],
            "open": group[0]["open"],
            "high": max(b["high"] for b in group),
            "low": min(b["low"] for b in group),
            "close": group[-1]["close"],
            "volume": sum(b["volume"] for b in group),
        }

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        cache_key = f"{symbol}_price"
        if self._is_cache_valid(cache_key):
            return self._get_cache(cache_key)

        try:
            coin_id = self._get_coin_id(symbol)
            self._rate_limit()

            url = f"{self.BASE_URL}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd"
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            price = data.get(coin_id, {}).get("usd")
            if price:
                self._set_cache(cache_key, float(price))
                return float(price)

        except Exception as e:
            logger.error(f"CoinGecko price fetch failed {symbol}: {e}")

        return None

    def is_market_open(self, symbol: str) -> bool:
        """加密货币7x24开盘"""
        return True

    def get_coin_info(self, symbol: str) -> Dict:
        """获取币种基本信息"""
        try:
            coin_id = self._get_coin_id(symbol)
            self._rate_limit()

            url = f"{self.BASE_URL}/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false"
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            return {
                "id": coin_id,
                "symbol": data.get("symbol", "").upper(),
                "name": data.get("name", symbol),
                "market_cap_rank": data.get("market_cap_rank"),
                "current_price": data.get("market_data", {}).get("current_price", {}).get("usd"),
                "price_change_24h": data.get("market_data", {}).get("price_change_percentage_24h"),
            }

        except Exception as e:
            logger.error(f"Failed to get coin info {symbol}: {e}")
            return {"symbol": symbol, "name": symbol}

"""
数据源抽象基类
==============
定义统一的数据获取接口。

v5.440: 新增OHLCVCache累积缓存类
- 解决CoinGecko单次请求K线不足问题
- 累积多次请求的数据，保持最近120根K线
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime
import json
import os
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# v5.440: OHLCV累积缓存类
# ============================================================================

class OHLCVCache:
    """
    v5.440: OHLCV累积缓存

    解决CoinGecko单次请求K线不足问题:
    - CoinGecko 30m周期单次只返回~48根K线
    - MACD等指标需要55+根K线
    - 通过累积多次请求数据解决

    来源: 主程序OHLCVWindow模式
    """

    MAX_BARS = 120  # 最大保留K线数
    PERSIST_DIR = "cache"  # 持久化目录

    def __init__(self, symbol: str, timeframe: str):
        self.symbol = symbol
        self.timeframe = timeframe
        self._bars: List[Dict] = []
        self._load_from_file()

    def _get_file_path(self) -> str:
        """获取持久化文件路径"""
        os.makedirs(self.PERSIST_DIR, exist_ok=True)
        return os.path.join(self.PERSIST_DIR, f"ohlcv_{self.symbol}_{self.timeframe}.json")

    def _load_from_file(self):
        """从文件加载缓存"""
        try:
            filepath = self._get_file_path()
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    # 转换时间戳
                    self._bars = []
                    for bar in data:
                        bar_copy = dict(bar)
                        if isinstance(bar_copy.get("timestamp"), str):
                            bar_copy["timestamp"] = datetime.fromisoformat(bar_copy["timestamp"])
                        self._bars.append(bar_copy)
                logger.debug(f"[OHLCVCache] {self.symbol}/{self.timeframe}: Loaded {len(self._bars)} bars from file")
        except Exception as e:
            logger.warning(f"[OHLCVCache] Failed to load cache: {e}")
            self._bars = []

    def _save_to_file(self):
        """保存到文件"""
        try:
            filepath = self._get_file_path()
            # 转换时间戳为字符串
            data = []
            for bar in self._bars:
                bar_copy = dict(bar)
                if isinstance(bar_copy.get("timestamp"), datetime):
                    bar_copy["timestamp"] = bar_copy["timestamp"].isoformat()
                data.append(bar_copy)
            with open(filepath, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"[OHLCVCache] Failed to save cache: {e}")

    def merge(self, new_bars: List[Dict]) -> List[Dict]:
        """
        合并新数据到缓存

        Args:
            new_bars: 新获取的K线数据

        Returns:
            合并后的完整K线列表
        """
        if not new_bars:
            return self._bars

        # 获取新数据的时间范围
        new_timestamps = set()
        for bar in new_bars:
            ts = bar.get("timestamp")
            if isinstance(ts, datetime):
                new_timestamps.add(ts.isoformat())
            elif ts:
                new_timestamps.add(str(ts))

        # 保留旧数据中不在新数据时间范围内的K线
        merged = []
        for bar in self._bars:
            ts = bar.get("timestamp")
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            if ts_str not in new_timestamps:
                merged.append(bar)

        # 添加新数据
        merged.extend(new_bars)

        # 按时间排序
        merged.sort(key=lambda x: x.get("timestamp") or datetime.min)

        # 保留最近MAX_BARS根
        if len(merged) > self.MAX_BARS:
            merged = merged[-self.MAX_BARS:]

        # 更新缓存
        old_count = len(self._bars)
        self._bars = merged
        self._save_to_file()

        if len(self._bars) > old_count:
            logger.info(f"[OHLCVCache] {self.symbol}/{self.timeframe}: {old_count}->{len(self._bars)} bars")

        return self._bars

    def get_bars(self) -> List[Dict]:
        """获取所有缓存的K线"""
        return self._bars

    def size(self) -> int:
        """获取缓存K线数量"""
        return len(self._bars)

    def clear(self):
        """清空缓存"""
        self._bars = []
        try:
            filepath = self._get_file_path()
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass


# ============================================================================
# 全局缓存管理器
# ============================================================================

_ohlcv_caches: Dict[str, OHLCVCache] = {}


def get_ohlcv_cache(symbol: str, timeframe: str) -> OHLCVCache:
    """获取或创建OHLCV缓存"""
    key = f"{symbol}_{timeframe}"
    if key not in _ohlcv_caches:
        _ohlcv_caches[key] = OHLCVCache(symbol, timeframe)
    return _ohlcv_caches[key]


class BaseDataProvider(ABC):
    """数据源抽象基类"""

    def __init__(self, cache_ttl: int = 60):
        """
        初始化数据源

        Args:
            cache_ttl: 缓存过期时间(秒)
        """
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Dict] = {}

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "30m",
        limit: int = 100
    ) -> List[Dict]:
        """
        获取K线数据

        Args:
            symbol: 标的代码 (如 "TSLA", "BTC")
            timeframe: 时间周期 (5m, 15m, 30m, 1h, 4h, 1d)
            limit: 返回数据条数

        Returns:
            K线数据列表，每条包含:
            {
                "timestamp": datetime,
                "open": float,
                "high": float,
                "low": float,
                "close": float,
                "volume": float
            }
        """
        pass

    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格

        Args:
            symbol: 标的代码

        Returns:
            当前价格，获取失败返回None
        """
        pass

    @abstractmethod
    def is_market_open(self, symbol: str) -> bool:
        """
        检查市场是否开盘

        Args:
            symbol: 标的代码

        Returns:
            True=开盘, False=休市
        """
        pass

    def _get_cache_key(self, symbol: str, timeframe: str) -> str:
        """生成缓存键"""
        return f"{symbol}_{timeframe}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        """检查缓存是否有效"""
        if cache_key not in self._cache:
            return False
        cache_entry = self._cache[cache_key]
        cached_time = cache_entry.get("timestamp", datetime.min)
        elapsed = (datetime.now() - cached_time).total_seconds()
        return elapsed < self.cache_ttl

    def _set_cache(self, cache_key: str, data: any):
        """设置缓存"""
        self._cache[cache_key] = {
            "timestamp": datetime.now(),
            "data": data
        }

    def _get_cache(self, cache_key: str) -> any:
        """获取缓存"""
        if cache_key in self._cache:
            return self._cache[cache_key].get("data")
        return None

    def clear_cache(self):
        """清除所有缓存"""
        self._cache.clear()

    @staticmethod
    def normalize_ohlcv(bars: List[Dict]) -> List[Dict]:
        """
        标准化K线数据格式

        确保所有字段都存在且类型正确
        """
        normalized = []
        for bar in bars:
            normalized.append({
                "timestamp": bar.get("timestamp"),
                "open": float(bar.get("open", 0)),
                "high": float(bar.get("high", 0)),
                "low": float(bar.get("low", 0)),
                "close": float(bar.get("close", 0)),
                "volume": float(bar.get("volume", 0)),
            })
        return normalized

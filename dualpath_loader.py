#!/usr/bin/env python3
"""
DualPath Loader v1.0 — GCC-0143 双路径数据加载器+调度器

Path A: YFinanceDataFetcher 直连 (现有，不改)
Path B: 后台线程预加载热门品种OHLCV → 写入 YFinanceDataFetcher._scan_cycle_cache
        使得下轮 scan_once 命中缓存, 跳过 API 调用

TradingScheduler: 根据 profiler baseline 判断是否触发 Path B 预加载

用法:
    from dualpath_loader import loader
    loader.schedule_prefetch()   # 每轮 scan_once 开始时调用
    loader.stop()                # 引擎停止时调用
"""
import threading
import time
import logging
from typing import Optional

logger = logging.getLogger("dualpath_loader")


class TradingDualPathLoader:
    """双路径OHLCV数据加载器"""

    # 拥塞阈值: 上轮scan_once中OHLCV拉取耗时占比>75% → 触发Path B
    CONGESTION_THRESHOLD = 0.75
    # Path B 预加载的周期配置 (interval, lookback)
    PREFETCH_CONFIGS = [
        ("4h", 30),   # 4H 30根 — 外挂主周期
        ("1h", 30),   # 1H 30根 — 子周期
    ]

    def __init__(self):
        self._prefetch_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_prefetch_ts = 0
        self._prefetch_interval = 180  # 最短预加载间隔(秒)
        self._enabled = True

    def schedule_prefetch(self):
        """
        检查是否需要预加载, 需要则启动后台线程。
        在 scan_once 开始时调用(begin_scan_cycle之后)。
        """
        if not self._enabled:
            return

        # 间隔保护
        now = time.time()
        if now - self._last_prefetch_ts < self._prefetch_interval:
            return

        # 检查上轮是否拥塞
        if not self._should_prefetch():
            return

        # 已有预加载线程运行中
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            return

        self._last_prefetch_ts = now
        self._prefetch_thread = threading.Thread(
            target=self._run_prefetch, daemon=True, name="dualpath-prefetch"
        )
        self._prefetch_thread.start()

    def _should_prefetch(self) -> bool:
        """根据profiler数据判断是否拥塞"""
        try:
            from dualpath_profiler import profiler
            data = profiler._load_baseline()
            summary = data.get("summary", {})
            scan_total = summary.get("scan_once_total", {})
            if not scan_total:
                return True  # 无数据时默认预加载

            total_avg = scan_total.get("avg_ms", 0)
            if total_avg <= 0:
                return True

            # 计算所有 price_xxx 的平均耗时之和
            price_total = 0
            for key, stats in summary.items():
                if key.startswith("price_"):
                    price_total += stats.get("avg_ms", 0)

            # 加上所有 plugins_xxx 中的OHLCV部分(估算: 外挂耗时的60%是OHLCV)
            plugin_total = 0
            for key, stats in summary.items():
                if key.startswith("plugins_"):
                    plugin_total += stats.get("avg_ms", 0)
            io_estimate = price_total + plugin_total * 0.6

            ratio = io_estimate / total_avg
            logger.debug(f"[DUALPATH] I/O比: {ratio:.2%} (阈值{self.CONGESTION_THRESHOLD:.0%})")
            return ratio >= self.CONGESTION_THRESHOLD
        except Exception:
            return True  # 出错时保守预加载

    def _run_prefetch(self):
        """Path B: 后台预加载OHLCV到scan_cycle_cache"""
        try:
            from dualpath_traffic import traffic_mgr
            from dualpath_profiler import profiler
        except ImportError:
            return

        symbols = self._get_all_symbols()
        prefetched = 0

        for symbol in symbols:
            if self._stop_event.is_set():
                break

            for interval, lookback in self.PREFETCH_CONFIGS:
                if self._stop_event.is_set():
                    break

                # 用 relay_path 确保不干扰信号通道
                with traffic_mgr.relay_path(f"prefetch_{symbol}_{interval}"):
                    try:
                        profiler.start(f"prefetch_{symbol}_{interval}")
                        self._prefetch_one(symbol, interval, lookback)
                        profiler.stop(f"prefetch_{symbol}_{interval}")
                        prefetched += 1
                    except Exception as e:
                        logger.debug(f"[DUALPATH] 预加载失败 {symbol} {interval}: {e}")
                        try:
                            profiler.stop(f"prefetch_{symbol}_{interval}")
                        except Exception:
                            pass

        if prefetched > 0:
            logger.info(f"[DUALPATH] Path B预加载完成: {prefetched}条OHLCV")

    @staticmethod
    def _prefetch_one(symbol: str, interval: str, lookback: int):
        """预加载单个品种的OHLCV到缓存"""
        # 动态import避免循环依赖
        from price_scan_engine_v21 import YFinanceDataFetcher

        # 检查缓存是否已存在
        if interval == "4h":
            tf_min = 240
        elif interval == "1h":
            tf_min = 60
        else:
            return

        existing = YFinanceDataFetcher._get_ohlcv_cache(symbol, interval, lookback)
        if existing is not None:
            return  # 已有缓存，跳过

        # 拉取并写入缓存
        bars = YFinanceDataFetcher.get_ohlcv(symbol, tf_min, lookback)
        if bars:
            YFinanceDataFetcher._set_ohlcv_cache(symbol, interval, lookback, bars)

    @staticmethod
    def _get_all_symbols() -> list:
        """获取所有监控品种"""
        crypto = ["BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD"]
        stocks = ["TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB",
                  "HIMS", "OPEN", "AMD", "ONDS", "PLTR"]
        return crypto + stocks

    # ── GCC-0144: Vision形态驱动优先预加载 ──

    def vision_prefetch(self, active_symbols: list):
        """
        Vision检测到形态的品种 → 立即后台预加载多周期数据。
        在Brooks Vision scan_all完成后调用。

        Args:
            active_symbols: 有形态信号的品种列表 (如 ["BTC-USD", "TSLA"])
        """
        if not active_symbols or not self._enabled:
            return
        # 已有线程运行中则跳过
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            return

        self._prefetch_thread = threading.Thread(
            target=self._run_vision_prefetch,
            args=(active_symbols,),
            daemon=True,
            name="dualpath-vision-prefetch",
        )
        self._prefetch_thread.start()
        logger.info(f"[DUALPATH][VISION] 形态驱动预加载: {active_symbols}")

    def _run_vision_prefetch(self, symbols: list):
        """Vision触发的优先预加载: 多周期(1H/4H/15m)"""
        try:
            from dualpath_traffic import traffic_mgr
            from dualpath_profiler import profiler
        except ImportError:
            return

        # Vision品种预加载更多周期 (包含15m给MACD背离)
        vision_configs = [
            ("4h", 30),
            ("1h", 30),
        ]
        prefetched = 0
        for symbol in symbols:
            if self._stop_event.is_set():
                break
            for interval, lookback in vision_configs:
                if self._stop_event.is_set():
                    break
                with traffic_mgr.relay_path(f"vision_prefetch_{symbol}"):
                    try:
                        self._prefetch_one(symbol, interval, lookback)
                        prefetched += 1
                    except Exception:
                        pass

        if prefetched > 0:
            logger.info(f"[DUALPATH][VISION] 预加载完成: {prefetched}条")

    def stop(self):
        """停止预加载"""
        self._stop_event.set()
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=5)


# 全局单例
loader = TradingDualPathLoader()

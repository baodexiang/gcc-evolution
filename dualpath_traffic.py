#!/usr/bin/env python3
"""
DualPath TrafficManager v2.0 — GCC-0142 流量隔离 + GCC-0145 P0-P4优先级

Python线程级流量隔离: 信号通道(Path A)最高优先, 旁路(Path B)使用间隙资源。

优先级分层 (GCC-0145):
  P0: 止损/熔断/暴跌 → signal_path(priority=0), 无等待直通
  P1: 外挂BUY/SELL信号 → signal_path(priority=1), 常规Path A
  P2: L2信号/共识度 → signal_path(priority=2), 常规Path A
  P3: Vision预加载 → relay_path, Path B
  P4: KNN backfill/回测 → relay_path, Path B

核心机制:
1. 信号锁(signal_lock): Path A获取后, Path B自动暂停
2. 令牌桶(relay_semaphore): Path B最大并发=1, 防止抢占I/O
3. P0绿色通道: priority=0时跳过所有等待, 保命优先

用法:
    from dualpath_traffic import traffic_mgr

    # P0 止损 — 无等待直通
    with traffic_mgr.signal_path("BTC-USD", priority=0):
        send_stop_loss(...)

    # P1 外挂信号 — 常规Path A
    with traffic_mgr.signal_path("BTC-USD", priority=1):
        send_plugin_signal(...)

    # P3 预加载 — Path B
    with traffic_mgr.relay_path("ohlcv_preload"):
        prefetch_ohlcv(...)
"""
import threading
import time
import functools
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrafficStats:
    """流量统计"""
    signal_count: int = 0          # Path A 进入次数
    relay_count: int = 0           # Path B 进入次数
    relay_wait_ms: float = 0       # Path B 累计等待时间
    relay_blocked_count: int = 0   # Path B 被阻塞次数
    last_signal_ts: float = 0      # 上次Path A活跃时间戳
    p0_count: int = 0              # P0直通次数
    p1_count: int = 0              # P1信号次数
    p2_count: int = 0              # P2信号次数


class TradingTrafficManager:
    """
    交易系统流量隔离管理器 v2.0 (P0-P4优先级)

    Path A (signal_path): P0/P1/P2 信号, 最高优先级
    Path B (relay_path):  P3/P4 预加载/回测, 最低优先级

    隔离机制:
    - signal_active事件: Path A活跃时, Path B等待
    - relay_semaphore: Path B最大并发=1
    - P0绿色通道: priority=0跳过relay等待, 保命优先
    """

    def __init__(self, relay_max_concurrent: int = 1, relay_gap_ms: float = 50):
        # Path A 活跃标志 (set=空闲可用, clear=信号计算中)
        self._signal_idle = threading.Event()
        self._signal_idle.set()  # 初始空闲

        # Path A 计数器 (支持嵌套)
        self._signal_count = 0
        self._signal_lock = threading.Lock()

        # Path B 并发控制
        self._relay_sem = threading.Semaphore(relay_max_concurrent)
        self._relay_gap_s = relay_gap_ms / 1000.0

        # 统计
        self.stats = TrafficStats()
        self._stats_lock = threading.Lock()
        self._last_snapshot: dict = {}  # get_stats_delta() 用

    # ── Path A: 信号通道 ──

    @contextmanager
    def signal_path(self, label: str = "", priority: int = 1):
        """
        信号计算上下文 — 进入时阻塞所有旁路。

        Args:
            label: 标识（日志用）
            priority: 0=P0止损直通, 1=P1外挂信号, 2=P2共识度
        """
        with self._signal_lock:
            self._signal_count += 1
            if self._signal_count == 1:
                self._signal_idle.clear()  # 标记繁忙
        with self._stats_lock:
            self.stats.signal_count += 1
            self.stats.last_signal_ts = time.time()
            if priority == 0:
                self.stats.p0_count += 1
            elif priority == 1:
                self.stats.p1_count += 1
            else:
                self.stats.p2_count += 1
        try:
            yield
        finally:
            with self._signal_lock:
                self._signal_count -= 1
                if self._signal_count == 0:
                    self._signal_idle.set()  # 恢复空闲

    # ── Path B: 旁路通道 ──

    @contextmanager
    def relay_path(self, label: str = "", timeout: float = 30.0):
        """旁路任务上下文 — 信号期间自动等待"""
        t0 = time.perf_counter()

        # 等待信号通道空闲
        if not self._signal_idle.is_set():
            with self._stats_lock:
                self.stats.relay_blocked_count += 1
            self._signal_idle.wait(timeout=timeout)

        # 获取并发令牌
        if not self._relay_sem.acquire(timeout=timeout):
            raise TimeoutError(f"relay_path({label}) semaphore acquire timeout {timeout}s")
        wait_ms = (time.perf_counter() - t0) * 1000

        with self._stats_lock:
            self.stats.relay_count += 1
            self.stats.relay_wait_ms += wait_ms

        try:
            yield
        finally:
            self._relay_sem.release()
            # 让出间隙给信号通道
            if self._relay_gap_s > 0:
                time.sleep(self._relay_gap_s)

    def relay_task(self, func):
        """装饰器: 将函数标记为旁路任务"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self.relay_path(label=func.__name__):
                return func(*args, **kwargs)
        return wrapper

    # ── 查询 ──

    def is_signal_active(self) -> bool:
        """信号通道是否正在使用"""
        return not self._signal_idle.is_set()

    def get_stats(self) -> dict:
        """返回流量统计（累计值）"""
        with self._stats_lock:
            return {
                "signal_count": self.stats.signal_count,
                "relay_count": self.stats.relay_count,
                "relay_wait_ms": round(self.stats.relay_wait_ms, 2),
                "relay_blocked_count": self.stats.relay_blocked_count,
                "last_signal_ts": self.stats.last_signal_ts,
                "p0_count": self.stats.p0_count,
                "p1_count": self.stats.p1_count,
                "p2_count": self.stats.p2_count,
            }

    def get_stats_delta(self) -> dict:
        """返回自上次调用以来的增量统计，用于per-round profiling"""
        with self._stats_lock:
            delta = {
                "signal_count": self.stats.signal_count - self._last_snapshot.get("signal_count", 0),
                "relay_count": self.stats.relay_count - self._last_snapshot.get("relay_count", 0),
                "relay_wait_ms": round(self.stats.relay_wait_ms - self._last_snapshot.get("relay_wait_ms", 0), 2),
                "relay_blocked_count": self.stats.relay_blocked_count - self._last_snapshot.get("relay_blocked_count", 0),
                "p0_count": self.stats.p0_count - self._last_snapshot.get("p0_count", 0),
                "p1_count": self.stats.p1_count - self._last_snapshot.get("p1_count", 0),
                "p2_count": self.stats.p2_count - self._last_snapshot.get("p2_count", 0),
            }
            self._last_snapshot = {
                "signal_count": self.stats.signal_count,
                "relay_count": self.stats.relay_count,
                "relay_wait_ms": self.stats.relay_wait_ms,
                "relay_blocked_count": self.stats.relay_blocked_count,
                "p0_count": self.stats.p0_count,
                "p1_count": self.stats.p1_count,
                "p2_count": self.stats.p2_count,
            }
            return delta


# ── 辅助: 根据signal_type自动判断优先级 ──

def infer_priority(signal_type: str, crash_sell: bool = False) -> int:
    """
    根据信号类型推断DualPath优先级:
      P0: 移动止损/移动止盈/暴跌 → 保命优先
      P1: 外挂信号(SuperTrend/BrooksVision/缠论BS/N字等)
      P2: 其他(共识度/记录型)
    """
    if crash_sell:
        return 0
    if signal_type in ("移动止损", "移动止盈"):
        return 0
    if signal_type in ("SuperTrend", "BrooksVision", "缠论BS", "N字结构",
                        "MACD背离", "P0-Tracking"):
        return 1
    return 2


# 全局单例
traffic_mgr = TradingTrafficManager(relay_max_concurrent=1, relay_gap_ms=50)

"""
GCC v5.295 — L6 Event Bus

线程安全的事件总线，<5ms emit，持久化到 .GCC/logs/events.jsonl。

使用:
    bus = EventBus.get()            # 单例
    bus.emit("L1", "记忆加载完成", {"cards": 12})
    events = bus.recent(50)         # 最近50条
    bus.subscribe(callback)         # 注册回调
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_EVENTS_FILE = Path(".GCC") / "logs" / "events.jsonl"
_MAX_MEMORY  = 500    # 内存最多保留条数
_FLUSH_EVERY = 10     # 每N条写一次磁盘


def _now_ms() -> str:
    """毫秒精度 ISO 时间戳。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class GCCEvent:
    """单条事件。"""
    layer: str       # L0 / L1 / L2 / L3 / L4 / L5 / L6
    message: str
    loop_id: str = ""
    data: dict = field(default_factory=dict)
    level: str = "INFO"   # INFO / WARN / ERROR
    ts: str = field(default_factory=_now_ms)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_sse(self) -> str:
        """Server-Sent Events 格式。"""
        payload = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {payload}\n\n"


class EventBus:
    """
    全局单例事件总线。

    - emit() 保证 <5ms (非阻塞写入队列)
    - 后台线程负责持久化到 .GCC/logs/events.jsonl
    - subscribe() 注册实时回调 (用于 SSE 推送)
    """

    _instance: Optional["EventBus"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._queue: queue.Queue[GCCEvent] = queue.Queue()
        self._buffer: list[GCCEvent] = []
        self._buffer_lock = threading.Lock()
        self._callbacks: list[Callable[[GCCEvent], None]] = []
        self._cb_lock = threading.Lock()
        self._flush_count = 0
        self._running = False
        self._writer_thread: Optional[threading.Thread] = None
        self._start_writer()

    @classmethod
    def get(cls) -> "EventBus":
        """获取单例实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Emit ────────────────────────────────────────────

    def emit(self, layer: str, message: str,
             data: Optional[dict] = None,
             loop_id: str = "",
             level: str = "INFO") -> GCCEvent:
        """
        发布事件。非阻塞，<5ms。
        Returns: 创建的 GCCEvent
        """
        t0 = time.monotonic()
        event = GCCEvent(
            layer=layer,
            message=message,
            loop_id=loop_id,
            data=data or {},
            level=level,
        )
        # 非阻塞入队
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("[EventBus] queue full, dropping event: %s", message)

        # 实时回调 (SSE 推送)
        with self._cb_lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(event)
            except Exception as e:
                logger.debug("[EventBus] callback error: %s", e)

        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > 5:
            logger.debug("[EventBus] emit took %.1fms (>5ms target)", elapsed_ms)

        return event

    # ── Subscribe ────────────────────────────────────────

    def subscribe(self, callback: Callable[[GCCEvent], None]) -> None:
        """注册实时回调 (每次 emit 后调用)。"""
        with self._cb_lock:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[GCCEvent], None]) -> None:
        with self._cb_lock:
            self._callbacks = [c for c in self._callbacks if c is not callback]

    # ── Query ────────────────────────────────────────────

    def recent(self, n: int = 50, layer: str = "",
               loop_id: str = "") -> list[GCCEvent]:
        """返回最近 n 条事件 (已按时间倒序)。"""
        with self._buffer_lock:
            events = list(self._buffer)

        # 过滤
        if layer:
            events = [e for e in events if e.layer == layer]
        if loop_id:
            events = [e for e in events if e.loop_id == loop_id]

        return list(reversed(events[-n:]))

    def layer_status(self) -> dict[str, dict]:
        """每层最新状态快照。"""
        with self._buffer_lock:
            events = list(self._buffer)

        status: dict[str, dict] = {}
        for e in reversed(events):
            if e.layer not in status:
                status[e.layer] = {
                    "layer": e.layer,
                    "last_message": e.message,
                    "last_ts": e.ts,
                    "level": e.level,
                    "loop_id": e.loop_id,
                }
        return status

    # ── Writer Thread ────────────────────────────────────

    def _start_writer(self) -> None:
        if self._running:
            return
        self._running = True
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="EventBus-Writer",
            daemon=True
        )
        self._writer_thread.start()

    def _writer_loop(self) -> None:
        """后台写入线程：消费队列 → 更新缓冲 → 批量写磁盘。"""
        pending: list[GCCEvent] = []

        while self._running:
            # 批量取，最多等 0.1s
            try:
                event = self._queue.get(timeout=0.1)
                pending.append(event)
                # 尽量取完
                while True:
                    try:
                        pending.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                pass

            if not pending:
                continue

            # 更新内存缓冲
            with self._buffer_lock:
                self._buffer.extend(pending)
                # 修剪超出上限
                if len(self._buffer) > _MAX_MEMORY:
                    self._buffer = self._buffer[-_MAX_MEMORY:]

            # 批量写磁盘
            self._flush_count += len(pending)
            if self._flush_count >= _FLUSH_EVERY:
                self._persist(pending)
                self._flush_count = 0

            pending = []

    def _persist(self, events: list[GCCEvent]) -> None:
        """追加写入 events.jsonl。"""
        try:
            _EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _EVENTS_FILE.open("a", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        except Exception as ex:
            logger.warning("[EventBus] persist failed: %s", ex)

    def stop(self) -> None:
        self._running = False

    def clear(self) -> None:
        """清空内存缓冲 (测试用)。"""
        with self._buffer_lock:
            self._buffer.clear()

"""
GCC v5.300 — L6 Event Bus

Thread-safe event bus, <5ms emit, persists to .GCC/logs/events.jsonl.

Usage:
    bus = EventBus.get()            # singleton
    bus.emit("L1", "memory loaded", {"cards": 12})
    events = bus.recent(50)         # last 50 events
    bus.subscribe(callback)         # register callback
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
_MAX_MEMORY  = 500    # max events in memory
_FLUSH_EVERY = 10     # flush to disk every N events


def _now_ms() -> str:
    """Millisecond-precision ISO timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class GCCEvent:
    """Single event."""
    layer: str       # L0 / L1 / L2 / L3 / L4 / L5 / L6
    message: str
    loop_id: str = ""
    data: dict = field(default_factory=dict)
    level: str = "INFO"   # INFO / WARN / ERROR
    ts: str = field(default_factory=_now_ms)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_sse(self) -> str:
        """Server-Sent Events format."""
        payload = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {payload}\n\n"


class EventBus:
    """
    Global singleton event bus.

    - emit() guaranteed <5ms (non-blocking queue write)
    - Background thread handles persistence to .GCC/logs/events.jsonl
    - subscribe() registers real-time callbacks (for SSE push)
    """

    _instance: Optional["EventBus"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._queue: queue.Queue[GCCEvent] = queue.Queue(maxsize=2000)
        self._buffer: list[GCCEvent] = []
        self._buffer_lock = threading.Lock()
        self._callbacks: list[Callable[[GCCEvent], None]] = []
        self._cb_lock = threading.Lock()
        self._running = False
        self._writer_thread: Optional[threading.Thread] = None
        self._start_writer()

    @classmethod
    def get(cls) -> "EventBus":
        """Get singleton instance."""
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
        Publish event. Non-blocking, <5ms.
        Returns: created GCCEvent
        """
        t0 = time.monotonic()
        event = GCCEvent(
            layer=layer,
            message=message,
            loop_id=loop_id,
            data=data or {},
            level=level,
        )
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("[EventBus] queue full, dropping event: %s", message)

        # Real-time callbacks (SSE push)
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
        """Register real-time callback (called after each emit)."""
        with self._cb_lock:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[GCCEvent], None]) -> None:
        with self._cb_lock:
            self._callbacks = [c for c in self._callbacks if c is not callback]

    # ── Query ────────────────────────────────────────────

    def recent(self, n: int = 50, layer: str = "",
               loop_id: str = "") -> list[GCCEvent]:
        """Return last n events (reverse chronological)."""
        with self._buffer_lock:
            events = list(self._buffer)

        if layer:
            events = [e for e in events if e.layer == layer]
        if loop_id:
            events = [e for e in events if e.loop_id == loop_id]

        return list(reversed(events[-n:]))

    def layer_status(self) -> dict[str, dict]:
        """Latest status snapshot per layer."""
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
        """Background writer: consume queue → update buffer → batch write disk."""
        unflushed: list[GCCEvent] = []   # accumulate across batches until FLUSH_EVERY

        while self._running:
            try:
                event = self._queue.get(timeout=0.1)
                batch = [event]
                while True:
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                batch = []

            if not batch:
                continue

            with self._buffer_lock:
                self._buffer.extend(batch)
                if len(self._buffer) > _MAX_MEMORY:
                    self._buffer = self._buffer[-_MAX_MEMORY:]

            unflushed.extend(batch)
            if len(unflushed) >= _FLUSH_EVERY:
                self._persist(unflushed)
                unflushed = []

        # Final flush on thread exit
        if unflushed:
            self._persist(unflushed)

    def _persist(self, events: list[GCCEvent]) -> None:
        """Append-write to events.jsonl."""
        try:
            _EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _EVENTS_FILE.open("a", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        except Exception as ex:
            logger.warning("[EventBus] persist failed: %s", ex)

    def stop(self, timeout: float = 2.0) -> None:
        """Stop EventBus, wait for writer thread to finish final flush."""
        self._running = False
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=timeout)
        # Drain any remaining queue events
        remaining: list[GCCEvent] = []
        while True:
            try:
                remaining.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if remaining:
            with self._buffer_lock:
                self._buffer.extend(remaining)
            self._persist(remaining)

    def clear(self) -> None:
        """Clear memory buffer (for testing)."""
        with self._buffer_lock:
            self._buffer.clear()

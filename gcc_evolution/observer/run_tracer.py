"""
GCC v5.295 — L6 Run Tracer

按 loop_id 追踪每次 loop 运行的全流程快照。

使用:
    tracer = RunTracer(bus)
    tracer.start_run("loop_001", key="KEY-010")
    tracer.mark_layer("loop_001", "L1", "done", {"cards": 12})
    snapshot = tracer.get_run("loop_001")
    runs = tracer.recent_runs(10)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .event_bus import EventBus, GCCEvent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LayerTrace:
    """单层运行状态。"""
    layer: str
    status: str = "pending"   # pending / running / done / error / skipped
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    data: dict = field(default_factory=dict)

    def duration_ms(self) -> Optional[float]:
        if not self.started_at or not self.finished_at:
            return None
        try:
            t0 = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
            return (t1 - t0).total_seconds() * 1000
        except Exception:
            return None


@dataclass
class RunTrace:
    """单次 loop 运行的完整轨迹。"""
    loop_id: str
    key: str = ""
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    status: str = "running"   # running / done / error / paused
    layers: dict[str, LayerTrace] = field(default_factory=dict)
    iteration: int = 1
    notes: str = ""

    def layer(self, name: str) -> LayerTrace:
        if name not in self.layers:
            self.layers[name] = LayerTrace(layer=name)
        return self.layers[name]

    def to_dict(self) -> dict:
        return {
            "loop_id": self.loop_id,
            "key": self.key,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "iteration": self.iteration,
            "notes": self.notes,
            "layers": {
                k: {
                    "layer": v.layer,
                    "status": v.status,
                    "started_at": v.started_at,
                    "finished_at": v.finished_at,
                    "message": v.message,
                    "data": v.data,
                    "duration_ms": v.duration_ms(),
                }
                for k, v in self.layers.items()
            },
        }


class Tracer:
    """
    全局运行追踪器。

    - 监听 EventBus，自动更新 RunTrace
    - 支持查询当前/历史 run
    """

    _MAX_RUNS = 50    # 内存保留最近 N 次 run

    def __init__(self, bus: Optional[EventBus] = None):
        self._bus = bus or EventBus.get()
        self._runs: dict[str, RunTrace] = {}
        self._order: list[str] = []    # 按创建顺序
        self._lock = threading.Lock()
        # 订阅事件总线
        self._bus.subscribe(self._on_event)

    # ── Public API ───────────────────────────────────────

    def start_run(self, loop_id: str, key: str = "",
                  iteration: int = 1) -> RunTrace:
        """注册一次新的 loop 运行。"""
        run = RunTrace(loop_id=loop_id, key=key, iteration=iteration)
        with self._lock:
            self._runs[loop_id] = run
            self._order.append(loop_id)
            # 修剪旧 run
            if len(self._order) > self._MAX_RUNS:
                old_id = self._order.pop(0)
                self._runs.pop(old_id, None)
        return run

    def finish_run(self, loop_id: str, status: str = "done",
                   notes: str = "") -> Optional[RunTrace]:
        with self._lock:
            run = self._runs.get(loop_id)
        if run:
            run.finished_at = _now()
            run.status = status
            run.notes = notes
        return run

    def mark_layer(self, loop_id: str, layer: str, status: str,
                   data: Optional[dict] = None, message: str = "") -> None:
        """更新某层状态。"""
        with self._lock:
            run = self._runs.get(loop_id)
        if not run:
            return
        lt = run.layer(layer)
        if status == "running" and not lt.started_at:
            lt.started_at = _now()
        elif status in ("done", "error", "skipped"):
            lt.finished_at = _now()
        lt.status = status
        if message:
            lt.message = message
        if data:
            lt.data.update(data)

    def get_run(self, loop_id: str) -> Optional[RunTrace]:
        with self._lock:
            return self._runs.get(loop_id)

    def current_run(self) -> Optional[RunTrace]:
        """获取最新的 run。"""
        with self._lock:
            if not self._order:
                return None
            return self._runs.get(self._order[-1])

    def recent_runs(self, n: int = 10) -> list[RunTrace]:
        with self._lock:
            recent_ids = self._order[-n:]
            return [self._runs[lid] for lid in reversed(recent_ids)
                    if lid in self._runs]

    # ── Auto-update from EventBus ────────────────────────

    def _on_event(self, event: GCCEvent) -> None:
        """监听事件总线，自动更新 RunTrace。"""
        if not event.loop_id:
            return

        with self._lock:
            run = self._runs.get(event.loop_id)
        if not run:
            return

        layer = event.layer
        data = event.data or {}
        status_hint = data.get("status", "")
        level = event.level

        # 自动推断状态
        if status_hint in ("started", "running"):
            self.mark_layer(event.loop_id, layer, "running",
                            data=data, message=event.message)
        elif status_hint in ("done", "completed"):
            self.mark_layer(event.loop_id, layer, "done",
                            data=data, message=event.message)
        elif level == "ERROR" or status_hint == "error":
            self.mark_layer(event.loop_id, layer, "error",
                            data=data, message=event.message)
        elif status_hint == "skipped":
            self.mark_layer(event.loop_id, layer, "skipped",
                            data=data, message=event.message)
        else:
            # 收到事件但无明确状态 → 标记为 running
            with self._lock:
                run2 = self._runs.get(event.loop_id)
            if run2:
                lt = run2.layer(layer)
                if lt.status == "pending":
                    lt.status = "running"
                    lt.started_at = lt.started_at or event.ts
                lt.message = event.message

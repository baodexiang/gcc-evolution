"""
GCC v5.295 — L6 Observer Package

事件总线 + 层级发射器 + 运行追踪器。

使用:
    from gcc_evolution.observer import EventBus, LayerEmitter, RunTracer

    bus = EventBus.get()
    emitter = LayerEmitter(bus, loop_id="loop_001")
    tracer = RunTracer(bus)
    emitter.emit_l1("记忆加载完成", {"cards": 12})
"""

from .event_bus import EventBus, GCCEvent
from .layer_emitter import LayerEmitter
from .run_tracer import Tracer as RunTracer, Tracer

__all__ = ["EventBus", "GCCEvent", "LayerEmitter", "RunTracer", "Tracer"]

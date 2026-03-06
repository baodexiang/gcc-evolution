"""
GCC v5.300 — L6 Observer Package

Event bus + layer emitter + run tracer.

Usage:
    from gcc_evolution.observer import EventBus, LayerEmitter, RunTracer

    bus = EventBus.get()
    emitter = LayerEmitter(bus, loop_id="loop_001")
    tracer = RunTracer(bus)
    emitter.emit_l1("memory loaded", {"cards": 12})
"""

from .event_bus import EventBus, GCCEvent
from .layer_emitter import LayerEmitter
from .run_tracer import Tracer as RunTracer, Tracer

__all__ = ["EventBus", "GCCEvent", "LayerEmitter", "RunTracer", "Tracer"]

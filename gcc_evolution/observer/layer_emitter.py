"""
GCC v5.300 — L6 Layer Emitter

Provides semantic emit interfaces for each layer, auto-attaches
layer label and loop_id.

Usage:
    emitter = LayerEmitter(bus, loop_id="loop_001")
    emitter.emit_l0("L0 gate passed", {"key": "KEY-010"})
    emitter.emit_l1("memory loaded", {"cards_loaded": 12})
    emitter.emit_l2("retrieval done", {"hits": 5})
    emitter.emit_l3("distillation done", {"distilled": 3})
    emitter.emit_l4("decision generated", {"action": "IMPLEMENT"})
    emitter.emit_l5("orchestration running", {"step": "S3"})
    emitter.emit_l6("dashboard push", {"clients": 2})
"""
from __future__ import annotations

from typing import Optional
from .event_bus import EventBus, GCCEvent


class LayerEmitter:
    """
    Layer emitter. Each layer has its own emit_lN method.

    Args:
        bus: EventBus instance (defaults to global singleton)
        loop_id: Unique ID for this loop run
    """

    LAYERS = {
        "L0": "Setup",
        "L1": "Memory",
        "L2": "Retrieval",
        "L3": "Distillation",
        "L4": "Decision",
        "L5": "Orchestration",
        "L6": "Observation",
    }

    def __init__(self, bus: Optional[EventBus] = None, loop_id: str = ""):
        self._bus = bus or EventBus.get()
        self.loop_id = loop_id

    def _emit(self, layer: str, message: str,
              data: Optional[dict] = None,
              level: str = "INFO") -> GCCEvent:
        return self._bus.emit(
            layer=layer,
            message=message,
            data=data or {},
            loop_id=self.loop_id,
            level=level,
        )

    # ── Per-layer shortcuts ──────────────────────────────

    def emit_l0(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L0 Setup layer."""
        return self._emit("L0", message, data, level)

    def emit_l1(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L1 Memory layer."""
        return self._emit("L1", message, data, level)

    def emit_l2(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L2 Retrieval layer."""
        return self._emit("L2", message, data, level)

    def emit_l3(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L3 Distillation layer."""
        return self._emit("L3", message, data, level)

    def emit_l4(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L4 Decision layer."""
        return self._emit("L4", message, data, level)

    def emit_l5(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L5 Orchestration layer."""
        return self._emit("L5", message, data, level)

    def emit_l6(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L6 Observation layer."""
        return self._emit("L6", message, data, level)

    # ── Status shortcuts ──────────────────────────────────

    def layer_start(self, layer: str, detail: str = "") -> GCCEvent:
        msg = f"{layer} started" + (f": {detail}" if detail else "")
        return self._emit(layer, msg, {"status": "started"})

    def layer_done(self, layer: str, detail: str = "",
                   result: Optional[dict] = None) -> GCCEvent:
        msg = f"{layer} done" + (f": {detail}" if detail else "")
        data = {"status": "done"}
        if result:
            data.update(result)
        return self._emit(layer, msg, data)

    def layer_error(self, layer: str, error: str,
                    exc: Optional[Exception] = None) -> GCCEvent:
        data = {"status": "error", "error": error}
        if exc:
            data["exc_type"] = type(exc).__name__
        return self._emit(layer, f"{layer} error: {error}", data, level="ERROR")

    def layer_warn(self, layer: str, message: str,
                   data: Optional[dict] = None) -> GCCEvent:
        return self._emit(layer, message, data, level="WARN")

    # ── Human anchor pause ──────────────────────────────

    def human_pause(self, reason: str = "waiting for human confirmation") -> GCCEvent:
        """Emit human confirmation pause event."""
        return self._emit("L0", f"[PAUSE] {reason}",
                          {"type": "human_pause", "reason": reason},
                          level="WARN")

    def human_resume(self, action: str = "y") -> GCCEvent:
        """Emit human resume event."""
        return self._emit("L0", f"[RESUME] action={action}",
                          {"type": "human_resume", "action": action})

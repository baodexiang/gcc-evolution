"""
L6 Observer — GCC Self-Observation Layer (Layer 7)

Persistent web dashboard and event bus for real-time GCC state monitoring.
Subscribes to all layer events via EventBus; serves SSE stream on port 7842.
"""
from ..observer.event_bus import EventBus, GCCEvent
from ..observer.layer_emitter import LayerEmitter
from ..observer.run_tracer import Tracer, RunTrace
from ..dashboard_server import DashboardServer

__all__ = ["DashboardServer", "EventBus", "GCCEvent", "LayerEmitter", "Tracer", "RunTrace"]

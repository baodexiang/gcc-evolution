"""Free UI layer (Setup Dashboard)."""
from pathlib import Path

from ...dashboard_server import DashboardServer
from ...observer import EventBus, GCCEvent, LayerEmitter, RunTracer, Tracer

DASHBOARD_HTML = Path(__file__).resolve().parents[2] / 'dashboard' / 'index.html'

__all__ = [
    'DashboardServer', 'DASHBOARD_HTML',
    'EventBus', 'GCCEvent', 'LayerEmitter', 'RunTracer', 'Tracer',
]

"""
GCC v5.295 — L6 实时 Dashboard 服务器

本地 HTTP 服务，端口 7842。
提供:
  GET /          → dashboard HTML
  GET /events    → SSE 实时事件流
  GET /status    → JSON 快照 (各层最新状态)
  GET /runs      → JSON 最近 run 列表

使用:
    server = DashboardServer(bus=EventBus.get(), tracer=tracer)
    server.start()          # 后台线程启动
    server.stop()           # 停止
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

from .observer.event_bus import EventBus, GCCEvent
from .observer.run_tracer import Tracer

logger = logging.getLogger(__name__)

PORT = 7842
_DASHBOARD_HTML = Path(__file__).parent / "dashboard" / "index.html"


# ── HTML fallback if file missing ──────────────────────────

_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GCC-EVO L6 Dashboard</title>
<style>
  body{background:#0d1117;color:#c9d1d9;font-family:monospace;padding:20px}
  h1{color:#58a6ff}
  .layer{display:flex;gap:10px;align-items:center;padding:8px;margin:4px 0;
         background:#161b22;border-radius:6px;border-left:3px solid #30363d}
  .dot{width:10px;height:10px;border-radius:50%}
  .pending{background:#484f58} .running{background:#f0883e;animation:pulse 1s infinite}
  .done{background:#3fb950} .error{background:#f85149} .skipped{background:#8b949e}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  #log{height:300px;overflow:auto;background:#010409;padding:10px;border-radius:6px;
       font-size:.8rem;border:1px solid #30363d}
  .log-INFO{color:#8b949e} .log-WARN{color:#e3b341} .log-ERROR{color:#f85149}
  .ts{color:#484f58}
</style>
</head>
<body>
<h1>GCC-EVO L6 实时观测 Dashboard</h1>
<div id="layers"></div>
<h3 style="color:#8b949e;margin-top:20px">事件日志</h3>
<div id="log"></div>
<script>
const LAYERS=['L0','L1','L2','L3','L4','L5','L6'];
const NAMES={L0:'预先设置',L1:'记忆',L2:'检索',L3:'蒸馏',L4:'决策',L5:'编排',L6:'观测'};
const state={};
LAYERS.forEach(l=>{
  state[l]={status:'pending',message:'--',ts:''};
  const d=document.createElement('div');
  d.className='layer';d.id='layer-'+l;
  d.innerHTML=`<span class="dot pending" id="dot-${l}"></span>
    <strong style="width:30px">${l}</strong>
    <span style="color:#8b949e;width:80px">${NAMES[l]}</span>
    <span id="msg-${l}" style="flex:1">等待中...</span>
    <span id="ts-${l}" class="ts" style="font-size:.75rem"></span>`;
  document.getElementById('layers').appendChild(d);
});

const log=document.getElementById('log');
function addLog(e){
  const div=document.createElement('div');
  div.className='log-'+(e.level||'INFO');
  div.innerHTML=`<span class="ts">${(e.ts||'').substr(11,8)}</span> `+
    `[${e.layer}] ${e.message}`;
  log.prepend(div);
  if(log.children.length>200) log.removeChild(log.lastChild);
}

const es=new EventSource('/events');
es.onmessage=ev=>{
  try{
    const e=JSON.parse(ev.data);
    const l=e.layer;
    if(l && document.getElementById('dot-'+l)){
      const s=(e.data&&e.data.status)||'running';
      document.getElementById('dot-'+l).className='dot '+(s||'running');
      document.getElementById('msg-'+l).textContent=e.message||'';
      document.getElementById('ts-'+l).textContent=(e.ts||'').substr(11,8);
    }
    addLog(e);
  }catch(err){}
};
es.onerror=()=>{setTimeout(()=>{window.location.reload()},3000)};
</script>
</body>
</html>
"""


# ── SSE Client Manager ───────────────────────────────────

class _SSEClients:
    """管理 SSE 客户端连接。"""

    def __init__(self):
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()

    def add(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.append(q)
        return q

    def remove(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients = [c for c in self._clients if c is not q]

    def broadcast(self, event: GCCEvent) -> None:
        sse_data = event.to_sse()
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.put_nowait(sse_data)
            except queue.Full:
                pass

    def count(self) -> int:
        with self._lock:
            return len(self._clients)


# ── HTTP Handler ─────────────────────────────────────────

def _make_handler(clients: _SSEClients, bus: EventBus, tracer: Tracer):

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # 静默 HTTP 日志

        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                self._serve_dashboard()
            elif self.path == "/events":
                self._serve_sse()
            elif self.path == "/status":
                self._serve_json(bus.layer_status())
            elif self.path == "/runs":
                runs = tracer.recent_runs(20)
                self._serve_json([r.to_dict() for r in runs])
            else:
                self.send_response(404)
                self.end_headers()

        def _serve_dashboard(self):
            if _DASHBOARD_HTML.exists():
                html = _DASHBOARD_HTML.read_bytes()
            else:
                html = _FALLBACK_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def _serve_json(self, data):
            payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _serve_sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            # 推送最近历史
            for e in reversed(bus.recent(20)):
                try:
                    self.wfile.write(e.to_sse().encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    return

            q = clients.add()
            try:
                while True:
                    try:
                        data = q.get(timeout=15)
                        self.wfile.write(data.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        # 心跳
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                clients.remove(q)

    return Handler


# ── Server ───────────────────────────────────────────────

class DashboardServer:
    """
    L6 实时 Dashboard 服务器。

    使用:
        server = DashboardServer()
        server.start()
        print(f"Dashboard: http://localhost:{server.port}")
    """

    def __init__(self, port: int = PORT,
                 bus: Optional[EventBus] = None,
                 tracer: Optional[Tracer] = None):
        self.port = port
        self._bus = bus or EventBus.get()
        self._tracer = tracer or Tracer(self._bus)
        self._clients = _SSEClients()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # 订阅事件广播到所有 SSE 客户端
        self._bus.subscribe(self._clients.broadcast)

    def start(self) -> bool:
        """启动服务（后台线程）。返回是否成功。"""
        try:
            handler = _make_handler(self._clients, self._bus, self._tracer)
            self._server = HTTPServer(("127.0.0.1", self.port), handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="GCC-Dashboard",
                daemon=True,
            )
            self._thread.start()
            logger.info("[L6] Dashboard started: http://localhost:%d", self.port)
            return True
        except OSError as e:
            logger.warning("[L6] Dashboard port %d in use: %s", self.port, e)
            return False

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def client_count(self) -> int:
        return self._clients.count()

"""
GCC Dashboard 本地服务器
运行: python gcc_dashboard_server.py
访问: http://localhost:8765
支持: 锚点删除（写回 .GCC/human_anchors.json + 重新生成 dashboard）
"""
import json, pathlib, subprocess, sys, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8765
BASE = pathlib.Path(__file__).parent
ANCHORS_FILE = BASE / ".GCC" / "human_anchors.json"
DASHBOARD_HTML = BASE / ".GCC" / "dashboard.html"
GEN_SCRIPT = BASE / "gen_dashboard.py"


def regen():
    """重新生成 dashboard.html"""
    subprocess.run([sys.executable, str(GEN_SCRIPT), "--quiet"], cwd=str(BASE), capture_output=True)


def read_anchors():
    if not ANCHORS_FILE.exists():
        return []
    try:
        return json.loads(ANCHORS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def write_anchors(anchors):
    ANCHORS_FILE.write_text(json.dumps(anchors, ensure_ascii=False, indent=2), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[dashboard] {fmt % args}")

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/" or path == "/dashboard":
            # Serve dashboard.html (regenerate first)
            regen()
            html = DASHBOARD_HTML.read_bytes() if DASHBOARD_HTML.exists() else b"<h1>Dashboard not found</h1>"
            self._send(200, "text/html; charset=utf-8", html)

        elif path == "/api/anchors":
            self._send(200, "application/json", json.dumps(read_anchors(), ensure_ascii=False))

        else:
            self._send(404, "text/plain", "Not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/delete_anchor":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                anchor_id = data.get("anchor_id", "")
            except Exception:
                self._send(400, "application/json", '{"error":"bad json"}')
                return

            anchors = read_anchors()
            before = len(anchors)
            anchors = [a for a in anchors if a.get("anchor_id") != anchor_id]
            write_anchors(anchors)
            regen()
            result = {"deleted": before - len(anchors), "remaining": len(anchors)}
            print(f"[dashboard] deleted anchor {anchor_id!r}, remaining={len(anchors)}")
            self._send(200, "application/json", json.dumps(result))
        else:
            self._send(404, "text/plain", "Not found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


if __name__ == "__main__":
    regen()
    server = HTTPServer(("localhost", PORT), Handler)
    print(f"GCC Dashboard 服务器启动: http://localhost:{PORT}")
    print(f"按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")

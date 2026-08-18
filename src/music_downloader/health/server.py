"""Process health-check HTTP endpoint."""

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer

HealthChecker = Callable[[], bool]

_checker: HealthChecker | None = None


def set_health_checker(checker: HealthChecker | None) -> None:
    global _checker
    _checker = checker


def _slskd_ok() -> bool:
    if _checker is None:
        return True
    try:
        return bool(_checker())
    except Exception:
        return False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            ok = _slskd_ok()
            body = {"status": "healthy" if ok else "degraded", "slskd": "ok" if ok else "unreachable"}
            self._json_response(200, body)
        elif self.path == "/ready":
            ok = _slskd_ok()
            body = {"status": "ready" if ok else "degraded", "slskd": "ok" if ok else "unreachable"}
            self._json_response(200 if ok else 503, body)
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):
        pass


def start_health_server(port: int, checker: HealthChecker | None = None):
    if checker is not None:
        set_health_checker(checker)
    server = HTTPServer(("127.0.0.1", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

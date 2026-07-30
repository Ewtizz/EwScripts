"""Локальный HTTP-сервер: отдаёт дашборд и стримит измерения через SSE."""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .connections import ConnectionMonitor
from .sampler import Sampler

WEB_ROOT = Path(__file__).parent / "web"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

MAX_CLIENTS = 8


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, sampler: Sampler, connections: ConnectionMonitor | None):
        super().__init__(address, RequestHandler)
        self.sampler = sampler
        self.connections = connections
        self.clients = 0
        self._clients_lock = threading.Lock()

    def claim_client(self) -> bool:
        with self._clients_lock:
            if self.clients >= MAX_CLIENTS:
                return False
            self.clients += 1
            return True

    def release_client(self) -> None:
        with self._clients_lock:
            self.clients = max(0, self.clients - 1)


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "NetPulse"

    # штатный лог http.server забивает консоль — свои сообщения печатает main
    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------- ответы

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _json(self, data, code: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(code, payload, "application/json; charset=utf-8")

    def _static(self, name: str) -> None:
        path = (WEB_ROOT / name).resolve()
        # защита от выхода за пределы каталога через ../
        if not path.is_file() or WEB_ROOT.resolve() not in path.parents:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(200, path.read_bytes(), content_type)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    # ------------------------------------------------------------ маршруты

    def do_GET(self):  # noqa: N802 — имя задано базовым классом
        route = self.path.split("?", 1)[0]
        sampler: Sampler = self.server.sampler

        if route == "/":
            self._static("index.html")
        elif route in ("/app.js", "/style.css", "/favicon.svg"):
            self._static(route.lstrip("/"))
        elif route == "/api/state":
            self._json(sampler.snapshot())
        elif route == "/api/connections":
            monitor: ConnectionMonitor | None = self.server.connections
            self._json({"connections": monitor.snapshot() if monitor else []})
        elif route == "/api/stream":
            self._stream()
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):  # noqa: N802
        route = self.path.split("?", 1)[0]
        sampler: Sampler = self.server.sampler
        body = self._body()

        if route == "/api/select":
            available = sampler.available_adapters()
            luid = body.get("luid")
            target = next((a for a in available if a["luid"] == luid), None)
            if target is None:
                self._json({"ok": False, "error": "адаптер не найден"}, 404)
                return
            sampler.select(target)
            self._json({"ok": True, "adapter": target["name"]})
        elif route == "/api/reset":
            sampler.reset_session()
            self._json({"ok": True})
        elif route == "/api/interval":
            try:
                interval = float(body.get("interval", 1.0))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "некорректный интервал"}, 400)
                return
            sampler.interval = min(10.0, max(0.2, interval))
            self._json({"ok": True, "interval": sampler.interval})
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    # ----------------------------------------------------------------- SSE

    def _stream(self) -> None:
        server: Dashboard = self.server
        if not server.claim_client():
            self._send(503, b"too many clients", "text/plain; charset=utf-8")
            return

        outbox: queue.Queue = queue.Queue(maxsize=200)

        def on_sample(payload: dict) -> None:
            try:
                outbox.put_nowait(payload)
            except queue.Full:
                # медленный клиент: выкидываем самое старое, актуальность важнее полноты
                try:
                    outbox.get_nowait()
                    outbox.put_nowait(payload)
                except queue.Empty:
                    pass

        sampler: Sampler = server.sampler
        sampler.subscribe(on_sample)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()

            while True:
                try:
                    payload = outbox.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # держим соединение живым
                    self.wfile.flush()
                    continue
                data = json.dumps(payload, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass  # вкладку закрыли — это нормальный сценарий
        finally:
            sampler.unsubscribe(on_sample)
            server.release_client()
            self.close_connection = True


def serve(sampler: Sampler, host: str, port: int, connections: ConnectionMonitor | None):
    """Создаёт сервер. Порт занят — пробуем следующие, чтобы не падать на ровном месте."""
    last_error: OSError | None = None
    for candidate in range(port, port + 10):
        try:
            return Dashboard((host, candidate), sampler, connections)
        except OSError as exc:
            last_error = exc
    raise last_error

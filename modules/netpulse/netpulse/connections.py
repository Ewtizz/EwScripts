"""Кто именно ходит в сеть: активные TCP-соединения, сгруппированные по процессам.

Windows не отдаёт счётчики байт на процесс без ETW и прав администратора, поэтому
здесь честно показываются соединения и их количество, а не объём трафика.
"""

from __future__ import annotations

import ipaddress
import queue
import socket
import threading
import time

from . import winapi

LOOPBACK_PREFIXES = ("127.", "::1", "0.0.0.0", "::")


class ReverseDns:
    """Фоновое разрешение имён: не блокирует опрос, отдаёт имя когда оно готово."""

    def __init__(self, workers: int = 4, ttl: float = 900.0) -> None:
        self.ttl = ttl
        self._cache: dict[str, tuple[str, float]] = {}
        self._queue: queue.Queue[str] = queue.Queue(maxsize=256)
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        for i in range(workers):
            threading.Thread(target=self._worker, name=f"rdns-{i}", daemon=True).start()

    def _worker(self) -> None:
        while True:
            ip = self._queue.get()
            try:
                host = socket.gethostbyaddr(ip)[0]
            except (OSError, socket.herror):
                host = ""
            with self._lock:
                self._cache[ip] = (host, time.time())
                self._pending.discard(ip)

    def lookup(self, ip: str) -> str:
        """Имя из кэша; при промахе ставит задачу в очередь и возвращает пустую строку."""
        now = time.time()
        with self._lock:
            hit = self._cache.get(ip)
            if hit and now - hit[1] < self.ttl:
                return hit[0]
            if ip in self._pending:
                return hit[0] if hit else ""
            self._pending.add(ip)
        try:
            self._queue.put_nowait(ip)
        except queue.Full:
            with self._lock:
                self._pending.discard(ip)
        return hit[0] if hit else ""


class ConnectionMonitor:
    def __init__(self, resolve_names: bool = True, name_ttl: float = 60.0) -> None:
        self._names: dict[int, tuple[str, float]] = {}
        self._name_ttl = name_ttl
        self._rdns = ReverseDns() if resolve_names else None

    def _process_name(self, pid: int) -> str:
        """Кэш имён процессов: PID переиспользуются, поэтому запись живёт ограниченно."""
        now = time.time()
        hit = self._names.get(pid)
        if hit and now - hit[1] < self._name_ttl:
            return hit[0]
        name = winapi.process_name(pid)
        self._names[pid] = (name, now)
        return name

    @staticmethod
    def _is_external(ip: str) -> bool:
        if not ip or ip.startswith(LOOPBACK_PREFIXES):
            return False
        try:
            return not ipaddress.ip_address(ip).is_loopback
        except ValueError:
            return False

    def snapshot(self, limit: int = 12) -> list[dict]:
        """Топ процессов по числу установленных внешних соединений."""
        by_pid: dict[int, dict] = {}
        for conn in winapi.tcp_connections():
            if conn["state"] != "ESTABLISHED":
                continue
            if not self._is_external(conn["remote"]):
                continue
            entry = by_pid.setdefault(
                conn["pid"],
                {"pid": conn["pid"], "process": self._process_name(conn["pid"]),
                 "count": 0, "peers": {}},
            )
            entry["count"] += 1
            key = conn["remote"]
            peer = entry["peers"].setdefault(
                key, {"ip": key, "ports": set(), "count": 0, "host": ""}
            )
            peer["ports"].add(conn["remote_port"])
            peer["count"] += 1

        result = []
        for entry in sorted(by_pid.values(), key=lambda e: -e["count"])[:limit]:
            peers = sorted(entry["peers"].values(), key=lambda p: -p["count"])[:4]
            for peer in peers:
                peer["ports"] = sorted(peer["ports"])[:3]
                if self._rdns:
                    peer["host"] = self._rdns.lookup(peer["ip"])
            result.append(
                {
                    "pid": entry["pid"],
                    "process": entry["process"],
                    "count": entry["count"],
                    "peers": peers,
                }
            )
        return result

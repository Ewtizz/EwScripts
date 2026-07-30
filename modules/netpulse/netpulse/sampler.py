"""Движок опроса: снимает счётчики адаптера с заданным интервалом и считает скорости."""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict

from . import adapters as adapters_mod
from . import winapi


@dataclass(slots=True)
class Sample:
    """Одна точка измерения."""

    t: float  # unix-время конца интервала
    dt: float  # фактическая длительность интервала, с
    rx_bytes: int  # принято за интервал
    tx_bytes: int  # отправлено за интервал
    rx_bps: float  # скорость приёма, байт/с
    tx_bps: float  # скорость отдачи, байт/с
    rx_packets: int
    tx_packets: int


class Sampler:
    """Опрашивает выбранный адаптер в фоновом потоке и рассылает точки подписчикам.

    Подписчик — callable(dict); исключения в нём не должны ронять цикл опроса,
    поэтому они гасятся и подписчик отключается.
    """

    def __init__(
        self,
        interval: float = 1.0,
        history_size: int = 3600,
        include_all: bool = False,
    ) -> None:
        self.interval = max(0.1, interval)
        self.include_all = include_all
        self.history: deque[Sample] = deque(maxlen=history_size)
        self.wlan = winapi.WlanClient()

        self._lock = threading.RLock()
        self._subscribers: list = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self.adapter: dict | None = None  # статическое описание выбранного адаптера
        self.wifi: dict = {}  # текущее состояние Wi-Fi (SSID, сигнал, …)
        self.latest: Sample | None = None

        # накопительная статистика сессии
        self.session_start = time.time()
        self.session_rx = 0
        self.session_tx = 0
        self.session_rx_packets = 0
        self.session_tx_packets = 0
        self.peak_rx = 0.0
        self.peak_tx = 0.0

        self._prev_counters: dict | None = None
        self._prev_time: float | None = None

    # ------------------------------------------------------------- адаптеры

    def available_adapters(self) -> list[dict]:
        return adapters_mod.list_adapters(self.include_all)

    def select(self, adapter: dict) -> None:
        """Переключает мониторинг на другой адаптер и сбрасывает сессию."""
        with self._lock:
            self.adapter = adapter
            self.reset_session()

    def reset_session(self) -> None:
        with self._lock:
            self.history.clear()
            self.session_start = time.time()
            self.session_rx = self.session_tx = 0
            self.session_rx_packets = self.session_tx_packets = 0
            self.peak_rx = self.peak_tx = 0.0
            self._prev_counters = None
            self._prev_time = None
            self.latest = None

    # ---------------------------------------------------------- подписчики

    def subscribe(self, callback) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _broadcast(self, payload: dict) -> None:
        with self._lock:
            targets = list(self._subscribers)
        for callback in targets:
            try:
                callback(payload)
            except Exception as exc:
                # отключаем сломавшегося подписчика, но не молча — иначе можно
                # не заметить, что запись в CSV прекратилась
                print(f"  [!] подписчик отключён из-за ошибки: {exc}", file=sys.stderr)
                self.unsubscribe(callback)

    # --------------------------------------------------------------- опрос

    def _current_row(self) -> dict | None:
        """Свежие счётчики выбранного адаптера (ищем по LUID — он стабилен)."""
        if self.adapter is None:
            return None
        luid = self.adapter["luid"]
        for iface in winapi.list_interfaces():
            if iface["luid"] == luid:
                return iface
        return None

    @staticmethod
    def _delta(current: int, previous: int) -> int:
        """Разница счётчиков. Уход в минус = сброс адаптера, тогда считаем 0."""
        return current - previous if current >= previous else 0

    def _tick(self) -> dict | None:
        row = self._current_row()
        if row is None:
            return None

        now = time.time()
        mono = time.perf_counter()

        # обновляем «живые» поля адаптера — статус, скорость линка, IP
        with self._lock:
            self.adapter.update(
                status=row["status"],
                connected=row["connected"],
                rx_link_bps=row["rx_link_bps"],
                tx_link_bps=row["tx_link_bps"],
            )
            if row["is_wifi"] and self.wlan.available:
                self.wifi = self.wlan.snapshot().get(row["guid"].upper(), {})

        if self._prev_counters is None or self._prev_time is None:
            self._prev_counters, self._prev_time = row, mono
            return None

        dt = mono - self._prev_time
        if dt <= 0:
            return None

        prev = self._prev_counters
        rx = self._delta(row["rx_bytes"], prev["rx_bytes"])
        tx = self._delta(row["tx_bytes"], prev["tx_bytes"])
        rx_pkts = self._delta(row["rx_packets"], prev["rx_packets"])
        tx_pkts = self._delta(row["tx_packets"], prev["tx_packets"])
        self._prev_counters, self._prev_time = row, mono

        sample = Sample(
            t=now,
            dt=dt,
            rx_bytes=rx,
            tx_bytes=tx,
            rx_bps=rx / dt,
            tx_bps=tx / dt,
            rx_packets=rx_pkts,
            tx_packets=tx_pkts,
        )

        with self._lock:
            self.history.append(sample)
            self.latest = sample
            self.session_rx += rx
            self.session_tx += tx
            self.session_rx_packets += rx_pkts
            self.session_tx_packets += tx_pkts
            self.peak_rx = max(self.peak_rx, sample.rx_bps)
            self.peak_tx = max(self.peak_tx, sample.tx_bps)
            totals = self.totals(row)

        return {"type": "sample", "sample": asdict(sample), **totals}

    def totals(self, row: dict | None = None) -> dict:
        """Сводка сессии + состояние адаптера — уходит в каждое SSE-сообщение."""
        adapter = dict(self.adapter) if self.adapter else {}
        if row is not None:
            adapter.update(
                {
                    "rx_bytes_total": row["rx_bytes"],
                    "tx_bytes_total": row["tx_bytes"],
                    "rx_errors": row["rx_errors"],
                    "tx_errors": row["tx_errors"],
                    "rx_discards": row["rx_discards"],
                    "tx_discards": row["tx_discards"],
                }
            )
        return {
            "adapter": adapter,
            "wifi": dict(self.wifi),
            "session": {
                "start": self.session_start,
                "uptime": time.time() - self.session_start,
                "rx": self.session_rx,
                "tx": self.session_tx,
                "rx_packets": self.session_rx_packets,
                "tx_packets": self.session_tx_packets,
                "peak_rx": self.peak_rx,
                "peak_tx": self.peak_tx,
                "avg_rx": self.session_rx / max(1e-9, time.time() - self.session_start),
                "avg_tx": self.session_tx / max(1e-9, time.time() - self.session_start),
                "samples": len(self.history),
            },
            "interval": self.interval,
        }

    def snapshot(self) -> dict:
        """Полное состояние для первичной загрузки страницы."""
        with self._lock:
            data = self.totals(self._prev_counters)
            data["history"] = [asdict(s) for s in self.history]
            data["adapters"] = [
                {
                    "luid": a["luid"],
                    "index": a["index"],
                    "name": a["name"],
                    "description": a["description"],
                    "is_wifi": a["is_wifi"],
                    "status": a["status"],
                    "ipv4": a.get("ipv4", []),
                    "selected": self.adapter is not None and a["luid"] == self.adapter["luid"],
                }
                for a in self.available_adapters()
            ]
            return data

    # ------------------------------------------------------------ жизненный цикл

    def _run(self) -> None:
        next_at = time.perf_counter()
        while not self._stop.is_set():
            next_at += self.interval
            try:
                payload = self._tick()
            except Exception as exc:  # адаптер исчез, служба перезапустилась и т.п.
                payload = {"type": "error", "message": str(exc)}
            if payload:
                self._broadcast(payload)
            # не даём накапливаться дрейфу; при зависании пропускаем просроченные тики
            sleep_for = next_at - time.perf_counter()
            if sleep_for < 0:
                next_at = time.perf_counter()
                sleep_for = 0
            self._stop.wait(sleep_for)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.wlan.close()

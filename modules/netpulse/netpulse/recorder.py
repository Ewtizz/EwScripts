"""Запись измерений в CSV с посуточной ротацией."""

from __future__ import annotations

import csv
import threading
import time
from datetime import datetime
from pathlib import Path

COLUMNS = [
    "timestamp",  # ISO-8601, локальное время
    "epoch",  # unix-время, с
    "interval_s",  # фактическая длительность интервала
    "adapter",
    "rx_bytes",  # принято за интервал
    "tx_bytes",  # отправлено за интервал
    "rx_bytes_per_s",
    "tx_bytes_per_s",
    "rx_packets",
    "tx_packets",
    "session_rx_bytes",
    "session_tx_bytes",
    "ssid",
    "signal_pct",
    "rssi_dbm",
    "channel",
    "link_rx_mbps",
    "link_tx_mbps",
]


class CsvRecorder:
    """Пишет по строке на каждое измерение. Файл на каждые сутки: traffic-YYYY-MM-DD.csv."""

    def __init__(self, log_dir: Path, flush_every: int = 10) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.flush_every = max(1, flush_every)

        self._lock = threading.Lock()
        self._file = None
        self._writer = None
        self._day: str | None = None
        self._pending = 0
        self.rows_written = 0
        self.current_path: Path | None = None

    def _ensure_file(self, when: float) -> None:
        day = datetime.fromtimestamp(when).strftime("%Y-%m-%d")
        if day == self._day and self._file is not None:
            return
        self._close()
        path = self.log_dir / f"traffic-{day}.csv"
        is_new = not path.exists() or path.stat().st_size == 0
        # newline="" — требование csv; utf-8-sig, чтобы Excel не ломал кириллицу
        self._file = path.open("a", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._file, delimiter=";")
        if is_new:
            self._writer.writerow(COLUMNS)
        self._day = day
        self.current_path = path

    def write(self, payload: dict) -> None:
        sample = payload.get("sample")
        if not sample:
            return
        adapter = payload.get("adapter", {})
        wifi = payload.get("wifi", {})
        session = payload.get("session", {})
        when = sample["t"]

        row = [
            datetime.fromtimestamp(when).isoformat(timespec="milliseconds"),
            f"{when:.3f}",
            f"{sample['dt']:.3f}",
            adapter.get("name", ""),
            sample["rx_bytes"],
            sample["tx_bytes"],
            f"{sample['rx_bps']:.1f}",
            f"{sample['tx_bps']:.1f}",
            sample["rx_packets"],
            sample["tx_packets"],
            session.get("rx", 0),
            session.get("tx", 0),
            wifi.get("ssid", ""),
            wifi.get("signal", ""),
            wifi.get("rssi", ""),
            wifi.get("channel", ""),
            round(wifi.get("link_rx_kbps", 0) / 1000, 1) if wifi.get("link_rx_kbps") else "",
            round(wifi.get("link_tx_kbps", 0) / 1000, 1) if wifi.get("link_tx_kbps") else "",
        ]

        with self._lock:
            self._ensure_file(when)
            self._writer.writerow(row)
            self.rows_written += 1
            self._pending += 1
            # буферизуем, чтобы не долбить диск каждую секунду, но не терять много при сбое
            if self._pending >= self.flush_every:
                self._file.flush()
                self._pending = 0

    def _close(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                pass
        self._file = None
        self._writer = None

    def close(self) -> None:
        with self._lock:
            self._close()


def write_session_summary(log_dir: Path, payload: dict) -> Path | None:
    """Итог сессии одной строкой в sessions.csv — удобно смотреть историю запусков."""
    session = payload.get("session")
    if not session or not session.get("samples"):
        return None
    path = Path(log_dir) / "sessions.csv"
    is_new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        if is_new:
            writer.writerow(
                [
                    "started",
                    "finished",
                    "duration_s",
                    "adapter",
                    "ssid",
                    "rx_bytes",
                    "tx_bytes",
                    "total_bytes",
                    "peak_rx_bytes_per_s",
                    "peak_tx_bytes_per_s",
                    "samples",
                ]
            )
        writer.writerow(
            [
                datetime.fromtimestamp(session["start"]).isoformat(timespec="seconds"),
                datetime.fromtimestamp(time.time()).isoformat(timespec="seconds"),
                round(session["uptime"], 1),
                payload.get("adapter", {}).get("name", ""),
                payload.get("wifi", {}).get("ssid", ""),
                session["rx"],
                session["tx"],
                session["rx"] + session["tx"],
                round(session["peak_rx"], 1),
                round(session["peak_tx"], 1),
                session["samples"],
            ]
        )
    return path

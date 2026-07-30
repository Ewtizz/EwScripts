"""Консольный режим: живая сводка прямо в терминале, без браузера."""

from __future__ import annotations

import ctypes
import sys
import threading
from collections import deque

SPARK = "▁▂▃▄▅▆▇█"

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[38;5;44m"
VIOLET = "\033[38;5;141m"
GREY = "\033[38;5;244m"


def enable_ansi() -> None:
    """Включает обработку escape-последовательностей в старых консолях Windows."""
    try:
        kernel32 = ctypes.WinDLL("kernel32.dll")
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except OSError:
        pass


def human_bytes(value: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(value) < 1024 or unit == "ТБ":
            return f"{value:.1f} {unit}" if unit != "Б" else f"{value:.0f} Б"
        value /= 1024
    return f"{value:.1f} ТБ"


def human_rate(value: float) -> str:
    return human_bytes(value) + "/с"


def duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def sparkline(values: deque, width: int = 28) -> str:
    if not values:
        return " " * width
    data = list(values)[-width:]
    top = max(data) or 1
    line = "".join(SPARK[min(len(SPARK) - 1, int(v / top * (len(SPARK) - 1)))] for v in data)
    return line.rjust(width)


class ConsoleView:
    """Перерисовывает фиксированный блок строк на месте, без прокрутки экрана."""

    LINES = 5

    def __init__(self, log_hint: str = "") -> None:
        self.rx_history: deque[float] = deque(maxlen=40)
        self.tx_history: deque[float] = deque(maxlen=40)
        self.log_hint = log_hint
        self._drawn = False
        self._lock = threading.Lock()
        enable_ansi()

    def __call__(self, payload: dict) -> None:
        if payload.get("type") != "sample":
            return
        sample = payload["sample"]
        adapter = payload.get("adapter", {})
        wifi = payload.get("wifi", {})
        session = payload.get("session", {})

        self.rx_history.append(sample["rx_bps"])
        self.tx_history.append(sample["tx_bps"])

        link = ""
        if wifi.get("ssid"):
            rssi = f", {wifi['rssi']} dBm" if wifi.get("rssi") is not None else ""
            channel = f", кан. {wifi['channel']}" if wifi.get("channel") else ""
            link = f" {GREY}·{RESET} {wifi['ssid']} ({wifi.get('signal', 0)}%{rssi}{channel})"

        lines = [
            f"{BOLD}NetPulse{RESET} {GREY}·{RESET} {adapter.get('name', '—')}{link}",
            f"  {CYAN}↓{RESET} {human_rate(sample['rx_bps']):>12}  "
            f"{CYAN}{sparkline(self.rx_history)}{RESET}  "
            f"{GREY}за сессию{RESET} {human_bytes(session.get('rx', 0)):>9}",
            f"  {VIOLET}↑{RESET} {human_rate(sample['tx_bps']):>12}  "
            f"{VIOLET}{sparkline(self.tx_history)}{RESET}  "
            f"{GREY}за сессию{RESET} {human_bytes(session.get('tx', 0)):>9}",
            f"  {GREY}время {duration(session.get('uptime', 0))} · "
            f"пик ↓ {human_rate(session.get('peak_rx', 0))} "
            f"↑ {human_rate(session.get('peak_tx', 0))}{RESET}",
            f"  {DIM}{self.log_hint}{RESET}",
        ]

        with self._lock:
            out = sys.stdout
            if self._drawn:
                out.write(f"\033[{self.LINES}A")
            for line in lines:
                out.write("\033[2K" + line + "\n")
            out.flush()
            self._drawn = True

    def finish(self) -> None:
        if self._drawn:
            sys.stdout.write("\n")
            sys.stdout.flush()

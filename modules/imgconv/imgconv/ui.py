"""Разговор с пользователем.

Из контекстного меню модуль запускается через pythonw.exe, без консоли, поэтому
единственный способ что-то сообщить — окно. При успехе не показываем ничего:
файлы просто появляются рядом, и лишнее окно тут только мешало бы.
"""

from __future__ import annotations

import ctypes

MB_OK = 0x0
MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30

TITLE = "Конвертер изображений"
MAX_LISTED = 12


def message(text: str, icon: int = MB_ICONERROR, title: str = TITLE) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, MB_OK | icon)
    except Exception:
        print(f"{title}: {text}")


def report_failures(failures: list[tuple[str, str]], succeeded: int) -> None:
    """Одно окно на всё выделение, а не по окну на каждый сбойный файл."""
    if not failures:
        return

    lines = []
    if succeeded:
        lines.append(f"Обработано: {succeeded}")
    lines.append(f"Не удалось: {len(failures)}")
    lines.append("")
    for name, reason in failures[:MAX_LISTED]:
        lines.append(f"{name}\n    {reason}")
    if len(failures) > MAX_LISTED:
        lines.append(f"…и ещё {len(failures) - MAX_LISTED}")

    icon = MB_ICONWARNING if succeeded else MB_ICONERROR
    message("\n".join(lines), icon)

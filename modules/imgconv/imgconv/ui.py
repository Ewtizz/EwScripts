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


def _listing(title: str, items: list[tuple[str, str]]) -> list[str]:
    lines = [title, ""]
    for name, reason in items[:MAX_LISTED]:
        lines.append(f"{name}\n    {reason}")
    if len(items) > MAX_LISTED:
        lines.append(f"…и ещё {len(items) - MAX_LISTED}")
    return lines


def report_result(
    failures: list[tuple[str, str]],
    skipped: list[tuple[str, str]],
    succeeded: int,
) -> None:
    """Одно окно на всё выделение, а не по окну на каждый файл.

    Пропуски и сбои разделены: файл, который уже меньше запрошенного размера,
    не ошибка, и пугать пользователя красным крестом из-за него не за что.
    """
    if not failures and not skipped:
        return

    lines: list[str] = []
    if succeeded:
        lines.append(f"Обработано: {succeeded}")
        lines.append("")
    if failures:
        lines += _listing(f"Не удалось: {len(failures)}", failures)
    if skipped:
        if failures:
            lines.append("")
        lines += _listing(f"Пропущено: {len(skipped)}", skipped)

    message("\n".join(lines), MB_ICONERROR if failures else MB_ICONWARNING)

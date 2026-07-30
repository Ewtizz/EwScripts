"""Настройки модуля.

Файл создаётся при первом запуске со значениями по умолчанию. Трогать его
необязательно — умолчания рассчитаны на то, чтобы результат было не отличить
от исходника на глаз.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "quality": {
        "JPEG": 95,
        "WEBP": 90,
        "AVIF": 80,
        "HEIF": 90,
        "JPEG2000": 80,
    },
    # Чем подменяется прозрачность в форматах без альфа-канала.
    "background": "#FFFFFF",
    "keep_exif": True,
    "png_compress_level": 6,
}


def load(data_dir: Path) -> dict:
    """Читает настройки, создавая файл при первом обращении.

    Повреждённый или недописанный файл не должен ломать конвертацию, поэтому
    при ошибке разбора молча берутся умолчания.
    """
    path = data_dir / "settings.json"
    settings = json.loads(json.dumps(DEFAULTS))  # глубокая копия

    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        for key, value in stored.items():
            if key == "quality" and isinstance(value, dict):
                settings["quality"].update(value)
            elif key in settings:
                settings[key] = value
        return settings

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass
    return settings


def background_rgb(settings: dict) -> tuple[int, int, int]:
    """Цвет подложки как тройка каналов. На кривом значении — белый."""
    value = str(settings.get("background", "#FFFFFF")).lstrip("#")
    if len(value) != 6:
        return (255, 255, 255)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return (255, 255, 255)

"""Уменьшение веса картинок.

Замеры на снимке 3000×2000 (за 100% взят экспорт с качеством 95):

    качество 90 — 51%, 85 — 31%, 80 — 22%, 75 — 16%, 70 — 13%, 60 — 10%, 30 — 7%

Весь выигрыш лежит между 95 и 70; ниже 60 кривая плоская — качество рушится,
а вес почти не падает. Поэтому пресеты не опускаются ниже 60, а подгонка под
размер не уходит ниже 40 и вместо этого начинает уменьшать картинку.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from . import formats
from .convert import (
    ConvertError,
    SkipFile,
    open_image,
    prepare_for_format,
    unique_path,
)

PRESETS = {"light": 85, "medium": 75, "strong": 60}

QUALITY_FLOOR = 40
QUALITY_CEILING = 95

# Если даже на нижнем качестве файл не влезает, уменьшаем саму картинку.
SCALES = (1.0, 0.8, 0.64, 0.5, 0.4, 0.32, 0.25)
MIN_SIDE = 160

SUFFIX = " (сжато)"


def _target_format(source_format: str) -> str:
    """Формат результата.

    У форматов без потерь «сжать, оставшись собой» не работает: PNG при
    максимальном сжатии всё равно в 17 раз тяжелее того же кадра в JPEG.
    Поэтому они уходят в WebP — он держит и фотографии, и прозрачность.
    """
    if source_format in formats.LOSSLESS_SOURCES:
        return formats.COMPRESS_FALLBACK
    if source_format in ("JPEG", "WEBP", "AVIF", "HEIF", "JPEG2000"):
        return source_format
    return formats.COMPRESS_FALLBACK


def _encode(image: Image.Image, fmt: str, quality: int, settings: dict) -> bytes:
    prepared = prepare_for_format(image, fmt, settings)
    options: dict = {"quality": int(quality)}
    if fmt == "JPEG":
        options["optimize"] = True
        options["progressive"] = True
    elif fmt == "WEBP":
        options["method"] = 4

    if settings.get("keep_exif", True):
        exif = image.info.get("exif")
        if exif and fmt in ("JPEG", "WEBP", "AVIF", "HEIF"):
            options["exif"] = exif

    buffer = io.BytesIO()
    try:
        prepared.save(buffer, format=fmt, **options)
    except (OSError, ValueError) as exc:
        raise ConvertError(f"{fmt}: {exc}") from None
    return buffer.getvalue()


def _largest_fitting(image: Image.Image, fmt: str, limit: int, settings: dict) -> bytes | None:
    """Наибольшее качество, при котором результат влезает в limit.

    Двоичный поиск: на практике сходится за шесть-семь проб.
    """
    low, high = QUALITY_FLOOR, QUALITY_CEILING
    best: bytes | None = None
    while low <= high:
        middle = (low + high) // 2
        data = _encode(image, fmt, middle, settings)
        if len(data) <= limit:
            best = data
            low = middle + 1
        else:
            high = middle - 1
    return best


def _destination(source: Path, fmt: str) -> Path:
    extension = formats.BY_PILLOW[fmt].ext if fmt in formats.BY_PILLOW else fmt.lower()
    return unique_path(source.with_name(source.stem + SUFFIX + "." + extension))


def _write(destination: Path, data: bytes) -> Path:
    try:
        destination.write_bytes(data)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ConvertError(f"не удалось записать файл ({exc})") from None
    return destination


def compress_preset(source: Path, level: str, settings: dict) -> Path:
    """Сжимает с заданным уровнем качества."""
    quality = PRESETS.get(level)
    if quality is None:
        raise ConvertError(f"неизвестный уровень сжатия {level}")

    original_size = source.stat().st_size
    image, source_format = open_image(source)
    try:
        fmt = _target_format(source_format)
        data = _encode(image, fmt, quality, settings)
    finally:
        image.close()

    # Уже сильно сжатый JPEG на качестве 85 может стать только тяжелее.
    # Класть рядом файл больше исходного — не то, чего просили.
    if len(data) >= original_size:
        raise SkipFile("сжатие не дало выигрыша, файл уже плотный")

    return _write(_destination(source, fmt), data)


def compress_to_size(source: Path, limit: int, settings: dict) -> Path:
    """Подбирает качество, а при нужде и размер, чтобы уложиться в limit байт."""
    original_size = source.stat().st_size
    if original_size <= limit:
        raise SkipFile(f"уже меньше {limit // 1024} КБ")

    image, source_format = open_image(source)
    try:
        fmt = _target_format(source_format)
        for scale in SCALES:
            if scale == 1.0:
                candidate = image
            else:
                width = max(1, round(image.width * scale))
                height = max(1, round(image.height * scale))
                if min(width, height) < MIN_SIDE:
                    break
                candidate = image.resize((width, height), Image.LANCZOS)

            data = _largest_fitting(candidate, fmt, limit, settings)
            if data is not None:
                return _write(_destination(source, fmt), data)
    finally:
        image.close()

    raise ConvertError(
        f"не удалось уместить в {limit // 1024} КБ даже с уменьшением картинки"
    )

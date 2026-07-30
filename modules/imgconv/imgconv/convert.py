"""Конвертация и геометрические преобразования картинок."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

from . import formats
from .settings import background_rgb

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC просто не будет в списке доступного
    pillow_heif = None


class ConvertError(Exception):
    """Ошибка, которую можно показать пользователю.

    Трейсбек Pillow ему ничего не объяснит, поэтому всё, что вылетает из
    библиотеки, заворачивается сюда с человеческим текстом.
    """


class SkipFile(Exception):
    """Не ошибка: делать было нечего.

    Например, файл уже меньше запрошенного размера. Показывать это как сбой
    неправильно — пользователь ничего не сделал не так.
    """


_OPERATIONS = {
    # ROTATE_90 у Pillow — против часовой стрелки, отсюда перекрёстные значения.
    "rotate-cw": Image.Transpose.ROTATE_270,
    "rotate-ccw": Image.Transpose.ROTATE_90,
    "rotate-180": Image.Transpose.ROTATE_180,
    "flip-h": Image.Transpose.FLIP_LEFT_RIGHT,
    "flip-v": Image.Transpose.FLIP_TOP_BOTTOM,
}


def unique_path(path: Path) -> Path:
    """`photo.png` занят — вернёт `photo (2).png`.

    Существующие файлы не перезаписываются никогда: конвертация не должна
    незаметно съедать чужую работу.
    """
    if not path.exists():
        return path
    for number in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise ConvertError("в папке слишком много файлов с таким именем")


def open_image(source: Path) -> tuple[Image.Image, str]:
    """Открывает файл и возвращает его вместе с исходным форматом."""
    try:
        image = Image.open(source)
        image.load()  # повреждённый файл лучше поймать здесь, а не при записи
    except FileNotFoundError:
        raise ConvertError("файл не найден") from None
    except (OSError, ValueError) as exc:
        raise ConvertError(f"не читается как изображение ({exc})") from None
    return image, (image.format or "")


def _normalize_orientation(image: Image.Image) -> Image.Image:
    """Применяет EXIF-ориентацию к пикселям и убирает саму метку.

    Без этого снимок с телефона, повёрнутый только меткой, после нашего поворота
    развернулся бы дважды: один раз нами, второй — просмотрщиком.
    """
    if getattr(image, "n_frames", 1) > 1:
        return image  # у многокадровых это схлопнуло бы анимацию в один кадр
    try:
        return ImageOps.exif_transpose(image) or image
    except (OSError, ValueError, KeyError):
        return image


def _flatten(image: Image.Image, settings: dict) -> Image.Image:
    """Кладёт прозрачность на подложку — для форматов без альфа-канала."""
    rgba = image.convert("RGBA")
    canvas = Image.new("RGB", rgba.size, background_rgb(settings))
    canvas.paste(rgba, mask=rgba.getchannel("A"))
    return canvas


def prepare_for_format(image: Image.Image, fmt: str, settings: dict) -> Image.Image:
    if fmt in formats.BILEVEL:
        return image.convert("1")

    if fmt in formats.NO_ALPHA:
        has_alpha = image.mode in ("RGBA", "LA", "PA") or (
            image.mode == "P" and "transparency" in image.info
        )
        if has_alpha:
            return _flatten(image, settings)
        if image.mode not in ("RGB", "L", "CMYK"):
            return image.convert("RGB")
        return image

    if image.mode == "P":
        return image.convert("RGBA")
    return image


def save_options(image: Image.Image, fmt: str, settings: dict) -> dict:
    quality = settings.get("quality", {})
    options: dict = {}

    if fmt in ("JPEG", "WEBP", "AVIF", "HEIF", "JPEG2000"):
        options["quality"] = int(quality.get(fmt, 90))
    if fmt == "JPEG":
        options["optimize"] = True
        options["progressive"] = True
    if fmt == "PNG":
        options["optimize"] = True
        options["compress_level"] = int(settings.get("png_compress_level", 6))
    if fmt == "TIFF":
        options["compression"] = "tiff_lzw"
    if fmt == "ICO":
        # Сторона ICO не бывает больше 256 пикселей.
        limit = min(256, image.width, image.height)
        sizes = [(s, s) for s in (256, 128, 64, 48, 32, 16) if s <= limit]
        options["sizes"] = sizes or [(limit, limit)]

    if settings.get("keep_exif", True):
        exif = image.info.get("exif")
        if exif and fmt in ("JPEG", "WEBP", "TIFF", "AVIF", "HEIF", "PNG"):
            options["exif"] = exif
    return options


def _save_animation(
    image: Image.Image, destination: Path, fmt: str, settings: dict
) -> None:
    frames = [prepare_for_format(frame.copy(), fmt, settings) for frame in ImageSequence.Iterator(image)]
    options = save_options(frames[0], fmt, settings)
    options["save_all"] = True
    options["append_images"] = frames[1:]
    if fmt in ("GIF", "WEBP", "PNG"):
        options["duration"] = image.info.get("duration", 100)
        options["loop"] = image.info.get("loop", 0)
    try:
        frames[0].save(destination, format=fmt, **options)
    except (OSError, ValueError) as exc:
        raise ConvertError(f"анимация: {exc}") from None


def convert(source: Path, pillow_format: str, settings: dict) -> Path:
    """Создаёт рядом с исходником файл в другом формате и возвращает его путь."""
    target = formats.BY_PILLOW.get(pillow_format)
    if target is None:
        raise ConvertError(f"неизвестный формат {pillow_format}")

    image, _ = open_image(source)
    destination = unique_path(source.with_suffix("." + target.ext))
    try:
        animated = getattr(image, "n_frames", 1) > 1
        if animated and pillow_format in formats.ANIMATED:
            _save_animation(image, destination, pillow_format, settings)
        else:
            prepared = prepare_for_format(_normalize_orientation(image), pillow_format, settings)
            options = save_options(prepared, pillow_format, settings)
            try:
                prepared.save(destination, format=pillow_format, **options)
            except (OSError, ValueError) as exc:
                raise ConvertError(f"{target.label}: {exc}") from None
    except Exception:
        # Недописанный файл хуже отсутствующего: он выглядит как результат.
        destination.unlink(missing_ok=True)
        raise
    finally:
        image.close()
    return destination


def transform(source: Path, operation: str, settings: dict) -> Path:
    """Поворачивает или отражает файл на месте."""
    if operation not in _OPERATIONS:
        raise ConvertError(f"неизвестное действие {operation}")

    image, fmt = open_image(source)
    if not fmt:
        image.close()
        raise ConvertError("не удалось определить формат файла")

    temporary = source.with_name(source.name + ".ewtmp")
    try:
        result = _normalize_orientation(image).transpose(_OPERATIONS[operation])
        options = save_options(result, fmt, settings)
        try:
            result.save(temporary, format=fmt, **options)
        except (OSError, ValueError) as exc:
            raise ConvertError(f"{fmt}: {exc}") from None
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        # Файл нужно закрыть до подмены: Windows не даст заменить открытый.
        image.close()

    try:
        os.replace(temporary, source)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ConvertError(f"не удалось заменить файл ({exc})") from None
    return source

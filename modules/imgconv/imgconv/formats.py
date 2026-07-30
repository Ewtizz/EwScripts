"""Что показываем в меню и на каких файлах.

Pillow пишет 31 формат, но BUFR, GRIB, HDF5, SPIDER, PALM, MSP, IM, BLP, WMF и
MPO — научные и служебные форматы, в контекстном меню это только шум. Здесь их нет.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    key: str      # имя подключа в реестре; порядок в меню — алфавитный по нему
    label: str    # что видит пользователь
    pillow: str   # формат для Image.save
    ext: str      # расширение результата


PRIMARY = (
    Target("01_png", "PNG", "PNG", "png"),
    Target("02_jpeg", "JPEG", "JPEG", "jpg"),
    Target("03_webp", "WebP", "WEBP", "webp"),
    Target("04_avif", "AVIF", "AVIF", "avif"),
    Target("05_heic", "HEIC", "HEIF", "heic"),
    Target("06_gif", "GIF", "GIF", "gif"),
    Target("07_bmp", "BMP", "BMP", "bmp"),
    Target("08_tiff", "TIFF", "TIFF", "tiff"),
    Target("09_ico", "ICO", "ICO", "ico"),
    Target("10_pdf", "PDF", "PDF", "pdf"),
)

SECONDARY = (
    Target("01_jp2", "JPEG 2000", "JPEG2000", "jp2"),
    Target("02_tga", "TGA", "TGA", "tga"),
    Target("03_pcx", "PCX", "PCX", "pcx"),
    Target("04_dds", "DDS", "DDS", "dds"),
    Target("05_icns", "ICNS", "ICNS", "icns"),
    Target("06_qoi", "QOI", "QOI", "qoi"),
    Target("07_ppm", "PPM", "PPM", "ppm"),
    Target("08_sgi", "SGI", "SGI", "sgi"),
    Target("09_eps", "EPS", "EPS", "eps"),
    Target("10_xbm", "XBM", "XBM", "xbm"),
)

ALL_TARGETS = PRIMARY + SECONDARY
BY_PILLOW = {t.pillow: t for t in ALL_TARGETS}

# Расширения, на которых появляется пункт меню. Список шире набора назначений:
# читать Pillow умеет больше форматов, чем писать.
SOURCE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".avif",
    ".heic", ".heif", ".gif", ".bmp", ".dib", ".tif", ".tiff",
    ".ico", ".icns", ".tga", ".pcx", ".ppm", ".pgm", ".pbm", ".pnm",
    ".dds", ".jp2", ".j2k", ".jpf", ".jpx", ".qoi", ".sgi", ".rgb",
    ".xbm", ".xpm", ".psd", ".eps", ".cur", ".fits", ".blp", ".ftex",
)

# У этих форматов нет альфа-канала: прозрачность придётся класть на подложку,
# иначе Pillow падает на попытке сохранить RGBA.
NO_ALPHA = frozenset({"JPEG", "PDF", "EPS", "BMP", "PCX", "PPM", "SGI"})

# Форматы, умеющие хранить несколько кадров.
ANIMATED = frozenset({"GIF", "WEBP", "PNG", "TIFF"})

# Чёрно-белые форматы: всё остальное к ним не приводится напрямую.
BILEVEL = frozenset({"XBM"})

# Форматы без потерь. «Сжать, оставшись собой» у них не работает: PNG при
# максимальном сжатии всё равно в 17 раз тяжелее того же кадра в JPEG и в 35 —
# чем в WebP. Поэтому при сжатии они меняют формат.
LOSSLESS_SOURCES = frozenset({
    "PNG", "BMP", "DIB", "TIFF", "TGA", "PCX", "PPM", "SGI",
    "QOI", "DDS", "ICNS", "ICO", "GIF", "PSD", "XBM", "XPM",
})

COMPRESS_FALLBACK = "WEBP"

COMPRESSION_LEVELS = (
    ("01_light", "Слегка", "light"),
    ("02_medium", "Заметно", "medium"),
    ("03_strong", "Сильно", "strong"),
)

COMPRESSION_TARGETS = (
    ("11_500k", "Уместить в 500 КБ", 512_000),
    ("12_1m", "Уместить в 1 МБ", 1_048_576),
    ("13_2m", "Уместить в 2 МБ", 2_097_152),
    ("14_5m", "Уместить в 5 МБ", 5_242_880),
)

ROTATIONS = (
    ("01_cw", "Вправо на 90°", "rotate-cw"),
    ("02_ccw", "Влево на 90°", "rotate-ccw"),
    ("03_180", "На 180°", "rotate-180"),
)

MIRRORS = (
    ("01_h", "По горизонтали", "flip-h"),
    ("02_v", "По вертикали", "flip-v"),
)

OPERATIONS = tuple(op for _, _, op in ROTATIONS + MIRRORS)

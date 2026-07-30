"""Пункты контекстного меню Проводника.

Всё пишется в HKCU — права администратора не нужны.

Дерево пунктов создаётся один раз, а расширения только ссылаются на него через
ExtendedSubCommandsKey: иначе двадцать пунктов пришлось бы продублировать под
каждым из трёх с лишним десятков расширений.

Про Windows 11: записи из реестра там показываются только под «Показать
дополнительные параметры». Попасть в новое меню верхнего уровня можно лишь
подписанным MSIX-пакетом с COM-обработчиком, а это требует прав администратора —
то есть несовместимо с тем, как устроен EwScripts.
"""

from __future__ import annotations

import ctypes
import sys
import winreg
from pathlib import Path

from . import formats

HKCU = winreg.HKEY_CURRENT_USER

PROGID = "EwScripts.ImgConv"  # путь относительно HKCR, как требует ExtendedSubCommandsKey
MENU_ROOT = rf"Software\Classes\{PROGID}"
ASSOCIATIONS = r"Software\Classes\SystemFileAssociations"

VERBS = (
    ("EwImgConvert", "Конвертировать в", "Formats"),
    ("EwImgRotate", "Повернуть", "Rotate"),
    ("EwImgMirror", "Отразить", "Mirror"),
)

ECF_SEPARATORBEFORE = 0x00000008


def _set(path: str, values: dict[str, str], dwords: dict[str, int] | None = None) -> None:
    with winreg.CreateKey(HKCU, path) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in (dwords or {}).items():
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def _delete_tree(path: str) -> None:
    try:
        key = winreg.OpenKey(HKCU, path, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    with key:
        while True:
            try:
                child = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_tree(f"{path}\\{child}")
    try:
        winreg.DeleteKey(HKCU, path)
    except OSError:
        pass


def _is_empty(path: str) -> bool:
    """Нет ни подключей, ни значений.

    Значения проверять обязательно: ключ без подключей, но со значениями —
    чужие данные, и удалять его нельзя.
    """
    try:
        with winreg.OpenKey(HKCU, path) as key:
            subkeys, values, _ = winreg.QueryInfoKey(key)
            return subkeys == 0 and values == 0
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _launch_prefix() -> str:
    """Начало командной строки: рантайм, шим и папка модуля.

    pythonw.exe вместо python.exe — чтобы при конвертации не мигало окно консоли.
    """
    python_dir = Path(sys.executable).parent
    launcher = python_dir / "pythonw.exe"
    if not launcher.exists():
        launcher = Path(sys.executable)
    shim = python_dir.parent / "launch.py"
    module_dir = Path(__file__).resolve().parent.parent
    return f'"{launcher}" "{shim}" "{module_dir}" "run.py"'


def make_icon(data_dir: Path) -> Path | None:
    """Рисует иконку для пунктов меню.

    Бинарный .ico в репозитории заводить не хочется, а Pillow у нас и так есть.
    """
    from PIL import Image, ImageDraw

    path = data_dir / "menu.ico"
    try:
        # В меню иконка рисуется размером 16 пикселей, поэтому рисунок должен
        # читаться именно там: одна фигура и одна жирная стрелка, без деталей.
        image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        white = (255, 255, 255, 255)
        draw.rounded_rectangle((20, 20, 236, 236), radius=46, fill=(64, 124, 214, 255))
        draw.rectangle((66, 110, 150, 146), fill=white)
        draw.polygon([(138, 68), (206, 128), (138, 188)], fill=white)
        image.save(path, format="ICO", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
        return path
    except Exception:
        return None  # без иконки меню тоже работает


def register(data_dir: Path) -> None:
    prefix = _launch_prefix()
    data = str(data_dir)
    icon = make_icon(data_dir)

    def command(arguments: str) -> str:
        # "%1" остаётся один даже при MultiSelectModel=Player: если Windows
        # подставит все выделенные файлы — run.py примет их все, если один —
        # просто отработает несколько раз. Верно в обоих случаях.
        return f'{prefix} --data "{data}" {arguments} "%1"'

    for target in formats.PRIMARY:
        base = rf"{MENU_ROOT}\Formats\shell\{target.key}"
        _set(base, {"MUIVerb": target.label})
        _set(rf"{base}\command", {"": command(f"--convert {target.pillow}")})

    _set(
        rf"{MENU_ROOT}\Formats\shell\99_more",
        {"MUIVerb": "Ещё форматы", "ExtendedSubCommandsKey": rf"{PROGID}\More"},
        {"CommandFlags": ECF_SEPARATORBEFORE},
    )

    for target in formats.SECONDARY:
        base = rf"{MENU_ROOT}\More\shell\{target.key}"
        _set(base, {"MUIVerb": target.label})
        _set(rf"{base}\command", {"": command(f"--convert {target.pillow}")})

    for tree, items in (("Rotate", formats.ROTATIONS), ("Mirror", formats.MIRRORS)):
        for key, label, operation in items:
            base = rf"{MENU_ROOT}\{tree}\shell\{key}"
            _set(base, {"MUIVerb": label})
            _set(rf"{base}\command", {"": command(f"--transform {operation}")})

    for extension in formats.SOURCE_EXTENSIONS:
        for verb, label, tree in VERBS:
            values = {
                "MUIVerb": label,
                "ExtendedSubCommandsKey": rf"{PROGID}\{tree}",
                "MultiSelectModel": "Player",
            }
            if icon is not None:
                values["Icon"] = str(icon)
            _set(rf"{ASSOCIATIONS}\{extension}\shell\{verb}", values)

    notify_shell()


def unregister() -> None:
    _delete_tree(MENU_ROOT)

    for extension in formats.SOURCE_EXTENSIONS:
        for verb, _, _ in VERBS:
            _delete_tree(rf"{ASSOCIATIONS}\{extension}\shell\{verb}")
        # Пустые ключи, созданные нами, за собой убираем — но только если в них
        # не осталось вообще ничего: там могли оказаться чужие пункты меню.
        for path in (
            rf"{ASSOCIATIONS}\{extension}\shell",
            rf"{ASSOCIATIONS}\{extension}",
        ):
            if _is_empty(path):
                try:
                    winreg.DeleteKey(HKCU, path)
                except OSError:
                    pass

    notify_shell()


def notify_shell() -> None:
    """Просит Проводник перечитать ассоциации, чтобы не перезапускать его руками."""
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass

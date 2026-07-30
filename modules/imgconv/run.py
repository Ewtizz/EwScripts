"""imgconv — конвертация и поворот картинок из контекстного меню Проводника.

    run.py --register --data ПАПКА          записать пункты меню
    run.py --unregister                     убрать их
    run.py --data ПАПКА --convert PNG ФАЙЛ…
    run.py --data ПАПКА --transform rotate-cw ФАЙЛ…

Из меню запускается через pythonw.exe: консоли нет, поэтому всё, что нужно
сказать пользователю, уходит в окно. Код возврата важен только лаунчеру, который
выполняет --register и --unregister.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def default_data_dir() -> Path:
    """Папка данных, выведенная из раскладки установки EwScripts."""
    module_dir = Path(__file__).resolve().parent
    return module_dir.parent.parent / "data" / module_dir.name


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="imgconv",
        description="Конвертация и поворот изображений.",
    )
    parser.add_argument("--data", metavar="ПАПКА", default=None,
                        help="папка данных модуля: настройки и иконка")
    parser.add_argument("--register", action="store_true",
                        help="записать пункты в контекстное меню")
    parser.add_argument("--unregister", action="store_true",
                        help="убрать пункты из контекстного меню")
    parser.add_argument("--convert", metavar="ФОРМАТ",
                        help="сконвертировать файлы в указанный формат")
    parser.add_argument("--transform", metavar="ДЕЙСТВИЕ",
                        help="повернуть или отразить файлы на месте")
    parser.add_argument("files", nargs="*", metavar="ФАЙЛ")
    return parser.parse_args(argv)


def setup_registry(register: bool, data_dir: Path) -> int:
    """Режимы для лаунчера: у него есть консоль, пишем в неё."""
    from imgconv import registry
    from imgconv import settings as settings_mod

    try:
        if register:
            data_dir.mkdir(parents=True, exist_ok=True)
            # Файл настроек создаём сразу, а не при первой конвертации: иначе
            # его негде увидеть и непонятно, что вообще можно настроить.
            settings_mod.load(data_dir)
            registry.register(data_dir)
            print("  пункты контекстного меню добавлены")
        else:
            registry.unregister()
            print("  пункты контекстного меню убраны")
    except OSError as exc:
        print(f"не удалось изменить реестр: {exc}", file=sys.stderr)
        return 1
    return 0


def run_batch(action, files: list[Path], settings: dict) -> int:
    """Прогоняет действие по всем файлам.

    Один сбойный файл не останавливает остальные: при выделении из тридцати
    обидно потерять двадцать девять из-за одного повреждённого.
    """
    from imgconv import ui
    from imgconv.convert import ConvertError

    failures: list[tuple[str, str]] = []
    succeeded = 0

    for path in files:
        try:
            action(path, settings)
            succeeded += 1
        except ConvertError as exc:
            failures.append((path.name, str(exc)))
        except Exception as exc:  # одно неожиданное не должно убить весь пакет
            failures.append((path.name, f"неожиданная ошибка: {exc}"))

    ui.report_failures(failures, succeeded)
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "win32":
        print("imgconv работает только на Windows.", file=sys.stderr)
        return 1

    args = parse_args(sys.argv[1:] if argv is None else argv)
    data_dir = Path(args.data) if args.data else default_data_dir()

    if args.register or args.unregister:
        return setup_registry(args.register, data_dir)

    if not args.convert and not args.transform:
        print("нужен --convert, --transform, --register или --unregister",
              file=sys.stderr)
        return 2

    from imgconv import convert as convert_mod
    from imgconv import formats, ui
    from imgconv import settings as settings_mod

    files = [Path(name) for name in args.files]
    if not files:
        ui.message("Не выбрано ни одного файла.")
        return 2

    settings = settings_mod.load(data_dir)

    if args.convert:
        target = args.convert.upper()
        if target not in formats.BY_PILLOW:
            ui.message(f"Неизвестный формат: {args.convert}")
            return 2

        def action(path: Path, cfg: dict) -> None:
            convert_mod.convert(path, target, cfg)
    else:
        operation = args.transform
        if operation not in formats.OPERATIONS:
            ui.message(f"Неизвестное действие: {operation}")
            return 2

        def action(path: Path, cfg: dict) -> None:
            convert_mod.transform(path, operation, cfg)

    return run_batch(action, files, settings)


if __name__ == "__main__":
    sys.exit(main())

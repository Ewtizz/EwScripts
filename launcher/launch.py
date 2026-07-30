"""Запуск модуля EwScripts на общем рантайме.

    python.exe launch.py <папка модуля> <точка входа> [аргументы модуля...]

Рантайм один на все модули и остаётся нетронутым: путь к модулю и к его
библиотекам подкладывается здесь, а не патчится внутри самой сборки Python.
Так модули не видят друг друга, а обновление рантайма ничего не ломает.
"""

import os
import runpy
import sys

if len(sys.argv) < 3:
    sys.exit("launch.py: нужны папка модуля и точка входа")

mod_dir = os.path.abspath(sys.argv[1])
entry = os.path.join(mod_dir, sys.argv[2])

if not os.path.isfile(entry):
    sys.exit(f"launch.py: не найдена точка входа {entry}")

libs = os.path.join(mod_dir, "libs")
if os.path.isdir(libs):
    sys.path.insert(0, libs)
sys.path.insert(0, mod_dir)

sys.argv = [entry, *sys.argv[3:]]
runpy.run_path(entry, run_name="__main__")

"""NetPulse — монитор и логгер трафика Wi-Fi адаптера в реальном времени.

Запуск:
    python run.py                 дашборд в браузере на http://127.0.0.1:8777
    python run.py --console       живая сводка прямо в терминале
    python run.py --list          показать доступные адаптеры и выйти
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

from netpulse import adapters as adapters_mod
from netpulse import server as server_mod
from netpulse.connections import ConnectionMonitor
from netpulse.console import ConsoleView, duration, human_bytes, human_rate
from netpulse.recorder import CsvRecorder, write_session_summary
from netpulse.sampler import Sampler

DEFAULT_PORT = 8777


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="netpulse",
        description="Логгер входящего и исходящего трафика Wi-Fi адаптера.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--iface", "-i", metavar="ИМЯ|LUID",
                        help="какой адаптер мониторить (по умолчанию активный Wi-Fi)")
    parser.add_argument("--interval", "-n", type=float, default=1.0, metavar="СЕК",
                        help="интервал опроса в секундах (по умолчанию 1.0)")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT,
                        help=f"порт дашборда (по умолчанию {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1",
                        help="адрес прослушивания (по умолчанию только локальный)")
    parser.add_argument("--all", action="store_true",
                        help="показывать и виртуальные адаптеры (VPN, туннели)")
    parser.add_argument("--list", action="store_true",
                        help="вывести список адаптеров и выйти")
    parser.add_argument("--console", "-c", action="store_true",
                        help="консольный режим без веб-дашборда")
    parser.add_argument("--log-dir", default=None, metavar="ПУТЬ",
                        help="куда писать CSV (по умолчанию ./logs рядом со скриптом)")
    parser.add_argument("--no-log", action="store_true", help="не писать CSV")
    parser.add_argument("--no-open", action="store_true", help="не открывать браузер")
    parser.add_argument("--no-dns", action="store_true",
                        help="не резолвить имена хостов в панели соединений")
    parser.add_argument("--history", type=int, default=3600, metavar="N",
                        help="сколько точек держать в памяти для графика (по умолчанию 3600)")
    parser.add_argument("--duration", "-d", type=float, default=0, metavar="СЕК",
                        help="остановиться через N секунд (по умолчанию — до Ctrl+C)")
    return parser.parse_args()


def print_adapter_list(adapters: list[dict]) -> None:
    print(f"\n  Найдено адаптеров: {len(adapters)}\n")
    for a in adapters:
        kind = "Wi-Fi" if a["is_wifi"] else "проводной"
        mark = "●" if a["status"] == "up" else "○"
        ips = ", ".join(a.get("ipv4", [])) or "нет адреса"
        print(f"  {mark} {a['name']}")
        print(f"      {a['description']}")
        print(f"      {kind} · {a['status']} · {ips} · LUID {a['luid']}")
        print(f"      принято {human_bytes(a['rx_bytes'])} / отправлено {human_bytes(a['tx_bytes'])}")
        print()


def main() -> int:
    if sys.platform != "win32":
        print("NetPulse использует Windows API и работает только на Windows.", file=sys.stderr)
        return 1

    # русские имена адаптеров не должны падать на консоли с кодировкой cp866
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    args = parse_args()
    available = adapters_mod.list_adapters(args.all)

    if args.list:
        print_adapter_list(available)
        return 0

    if not available:
        print("Не найдено ни одного адаптера. Попробуйте запустить с ключом --all.",
              file=sys.stderr)
        return 1

    if args.iface:
        adapter = adapters_mod.find(available, args.iface)
        if adapter is None:
            print(f"Адаптер «{args.iface}» не найден. Список: python run.py --list",
                  file=sys.stderr)
            return 1
    else:
        adapter = adapters_mod.pick_default(available)

    sampler = Sampler(
        interval=args.interval, history_size=max(60, args.history), include_all=args.all
    )
    sampler.select(adapter)

    recorder = None
    log_hint = "запись в CSV отключена"
    if not args.no_log:
        log_dir = Path(args.log_dir) if args.log_dir else Path(__file__).parent / "logs"
        recorder = CsvRecorder(log_dir)
        sampler.subscribe(recorder.write)
        log_hint = f"лог: {log_dir}"

    console_view = None
    httpd = None
    url = ""

    print()
    print(f"  NetPulse · адаптер: {adapter['name']}")
    print(f"  {adapter['description']}")
    print(f"  интервал опроса: {sampler.interval:g} с · {log_hint}")

    if args.console:
        console_view = ConsoleView(log_hint)
        sampler.subscribe(console_view)
        print("  Ctrl+C — остановить\n")
    else:
        connections = ConnectionMonitor(resolve_names=not args.no_dns)
        httpd = server_mod.serve(sampler, args.host, args.port, connections)
        host_label = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
        url = f"http://{host_label}:{httpd.server_address[1]}/"
        threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
        print(f"  дашборд: {url}")
        print("  Ctrl+C — остановить\n")
        if not args.no_open:
            webbrowser.open(url)

    sampler.start()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    try:
        while not stop.wait(0.5):
            if deadline is not None and time.monotonic() >= deadline:
                break
    except KeyboardInterrupt:
        pass

    if console_view is not None:
        console_view.finish()
    if httpd is not None:
        httpd.shutdown()
    sampler.stop()

    summary = sampler.totals()
    session = summary["session"]
    if recorder is not None:
        recorder.close()
        path = write_session_summary(recorder.log_dir, summary)
        if path:
            print(f"\n  Итог сессии дописан в {path}")

    print()
    print(f"  Длительность : {duration(session['uptime'])}")
    print(f"  Принято      : {human_bytes(session['rx'])}  "
          f"(в среднем {human_rate(session['avg_rx'])}, пик {human_rate(session['peak_rx'])})")
    print(f"  Отправлено   : {human_bytes(session['tx'])}  "
          f"(в среднем {human_rate(session['avg_tx'])}, пик {human_rate(session['peak_tx'])})")
    print(f"  Всего        : {human_bytes(session['rx'] + session['tx'])}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

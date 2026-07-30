"""Поиск и выбор сетевых адаптеров."""

from __future__ import annotations

from . import winapi


def _is_real(iface: dict) -> bool:
    """Отсеивает фильтр-драйверы (LightWeight Filter, QoS Packet Scheduler и т.п.).

    Такие записи дублируют счётчики настоящего адаптера и только замусоривают список.
    """
    if iface["is_filter"]:
        return False
    if iface["type"] == winapi.IF_TYPE_LOOPBACK:
        return False
    return True


def list_adapters(include_all: bool = False) -> list[dict]:
    """Список адаптеров, пригодных для мониторинга.

    По умолчанию — только физические (hardware) интерфейсы. С ``include_all``
    добавляются виртуальные: VPN-туннели, Wi-Fi Direct, WAN miniport.
    """
    adapters = [a for a in winapi.list_interfaces() if _is_real(a)]
    if not include_all:
        adapters = [a for a in adapters if a["is_hardware"]]

    ips = winapi.ipv4_by_index()
    for a in adapters:
        a["ipv4"] = ips.get(a["index"], [])

    # Wi-Fi и работающие адаптеры — наверх, дальше по объёму трафика
    adapters.sort(
        key=lambda a: (
            not (a["is_wifi"] and a["status"] == "up"),
            a["status"] != "up",
            -(a["rx_bytes"] + a["tx_bytes"]),
        )
    )
    return adapters


def pick_default(adapters: list[dict]) -> dict | None:
    """Wi-Fi адаптер в состоянии up; если такого нет — первый активный; иначе первый."""
    for a in adapters:
        if a["is_wifi"] and a["status"] == "up":
            return a
    for a in adapters:
        if a["status"] == "up":
            return a
    return adapters[0] if adapters else None


def find(adapters: list[dict], query: str) -> dict | None:
    """Поиск адаптера по LUID, индексу или подстроке имени/описания."""
    query = query.strip()
    if not query:
        return None
    if query.isdigit():
        number = int(query)
        for a in adapters:
            if a["luid"] == number or a["index"] == number:
                return a
    lowered = query.lower()
    for a in adapters:
        if lowered in a["name"].lower() or lowered in a["description"].lower():
            return a
    return None

"""Тонкая ctypes-обвязка над Windows API.

Три источника данных, всё без внешних зависимостей и без прав администратора:

* ``iphlpapi.GetIfTable2``       — счётчики байт/пакетов/ошибок по каждому адаптеру;
* ``wlanapi.WlanQueryInterface`` — SSID, качество сигнала, RSSI, канал, скорость линка;
* ``iphlpapi.GetExtendedTcpTable`` — активные TCP-соединения с PID процесса-владельца.
"""

from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes

# ---------------------------------------------------------------- константы

IF_MAX_STRING_SIZE = 256
IF_MAX_PHYS_ADDRESS_LENGTH = 32

IF_TYPE_ETHERNET = 6
IF_TYPE_LOOPBACK = 24
IF_TYPE_IEEE80211 = 71
IF_TYPE_TUNNEL = 131

NDIS_PHYSICAL_MEDIUM_NATIVE_802_11 = 9

# Биты MIB_IF_ROW2.InterfaceAndOperStatusFlags
FLAG_HARDWARE_INTERFACE = 1 << 0
FLAG_FILTER_INTERFACE = 1 << 1

OPER_STATUS = {
    1: "up",
    2: "down",
    3: "testing",
    4: "unknown",
    5: "dormant",
    6: "notpresent",
    7: "lowerlayerdown",
}

PHY_TYPE = {
    0: "unknown",
    1: "FHSS",
    2: "DSSS",
    3: "IR",
    4: "802.11a (OFDM)",
    5: "802.11b (HR-DSSS)",
    6: "802.11g (ERP)",
    7: "802.11n (HT)",
    8: "802.11ac (VHT)",
    9: "802.11ad (DMG)",
    10: "802.11ax (HE)",
    11: "802.11be (EHT)",
}

AUTH_ALGO = {
    1: "Open",
    2: "Shared key",
    3: "WPA",
    4: "WPA-Personal",
    5: "WPA-None",
    6: "WPA2-Enterprise",
    7: "WPA2-Personal",
    8: "WPA3-Enterprise 192",
    9: "WPA3-Personal (SAE)",
    10: "OWE",
    11: "WPA3-Enterprise",
}

CIPHER_ALGO = {
    0x00: "нет",
    0x01: "WEP-40",
    0x02: "TKIP",
    0x04: "AES (CCMP)",
    0x05: "WEP-104",
    0x06: "BIP",
    0x08: "GCMP",
    0x09: "GCMP-256",
    0x0A: "CCMP-256",
    0x100: "группа WPA",
    0x101: "WEP",
}

TCP_STATE = {
    1: "CLOSED",
    2: "LISTEN",
    3: "SYN_SENT",
    4: "SYN_RCVD",
    5: "ESTABLISHED",
    6: "FIN_WAIT1",
    7: "FIN_WAIT2",
    8: "CLOSE_WAIT",
    9: "CLOSING",
    10: "LAST_ACK",
    11: "TIME_WAIT",
    12: "DELETE_TCB",
}

# ------------------------------------------------------------- iphlpapi/DLL

_iphlpapi = ctypes.WinDLL("iphlpapi.dll")
_kernel32 = ctypes.WinDLL("kernel32.dll")
try:
    _wlanapi = ctypes.WinDLL("wlanapi.dll")
except OSError:  # на системе без Wi-Fi службы
    _wlanapi = None


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __str__(self) -> str:
        return "{%08X-%04X-%04X-%s-%s}" % (
            self.Data1,
            self.Data2,
            self.Data3,
            bytes(self.Data4[:2]).hex().upper(),
            bytes(self.Data4[2:]).hex().upper(),
        )


class MIB_IF_ROW2(ctypes.Structure):
    """MIB_IF_ROW2 из netioapi.h (1352 байта на x64)."""

    _fields_ = [
        ("InterfaceLuid", ctypes.c_ulonglong),
        ("InterfaceIndex", ctypes.c_ulong),
        ("InterfaceGuid", GUID),
        ("Alias", ctypes.c_wchar * (IF_MAX_STRING_SIZE + 1)),
        ("Description", ctypes.c_wchar * (IF_MAX_STRING_SIZE + 1)),
        ("PhysicalAddressLength", ctypes.c_ulong),
        ("PhysicalAddress", ctypes.c_ubyte * IF_MAX_PHYS_ADDRESS_LENGTH),
        ("PermanentPhysicalAddress", ctypes.c_ubyte * IF_MAX_PHYS_ADDRESS_LENGTH),
        ("Mtu", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
        ("TunnelType", ctypes.c_int),
        ("MediaType", ctypes.c_int),
        ("PhysicalMediumType", ctypes.c_int),
        ("AccessType", ctypes.c_int),
        ("DirectionType", ctypes.c_int),
        ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),
        ("OperStatus", ctypes.c_int),
        ("AdminStatus", ctypes.c_int),
        ("MediaConnectState", ctypes.c_int),
        ("NetworkGuid", GUID),
        ("ConnectionType", ctypes.c_int),
        ("TransmitLinkSpeed", ctypes.c_ulonglong),
        ("ReceiveLinkSpeed", ctypes.c_ulonglong),
        ("InOctets", ctypes.c_ulonglong),
        ("InUcastPkts", ctypes.c_ulonglong),
        ("InNUcastPkts", ctypes.c_ulonglong),
        ("InDiscards", ctypes.c_ulonglong),
        ("InErrors", ctypes.c_ulonglong),
        ("InUnknownProtos", ctypes.c_ulonglong),
        ("InUcastOctets", ctypes.c_ulonglong),
        ("InMulticastOctets", ctypes.c_ulonglong),
        ("InBroadcastOctets", ctypes.c_ulonglong),
        ("OutOctets", ctypes.c_ulonglong),
        ("OutUcastPkts", ctypes.c_ulonglong),
        ("OutNUcastPkts", ctypes.c_ulonglong),
        ("OutDiscards", ctypes.c_ulonglong),
        ("OutErrors", ctypes.c_ulonglong),
        ("OutUcastOctets", ctypes.c_ulonglong),
        ("OutMulticastOctets", ctypes.c_ulonglong),
        ("OutBroadcastOctets", ctypes.c_ulonglong),
        ("OutQLen", ctypes.c_ulonglong),
    ]


class MIB_IF_TABLE2(ctypes.Structure):
    _fields_ = [("NumEntries", ctypes.c_ulong), ("Table", MIB_IF_ROW2 * 1)]


_iphlpapi.GetIfTable2.argtypes = [ctypes.POINTER(ctypes.POINTER(MIB_IF_TABLE2))]
_iphlpapi.GetIfTable2.restype = ctypes.c_ulong
_iphlpapi.FreeMibTable.argtypes = [ctypes.c_void_p]
_iphlpapi.FreeMibTable.restype = None


class MIB_IPADDRROW(ctypes.Structure):
    _fields_ = [
        ("dwAddr", ctypes.c_ulong),
        ("dwIndex", ctypes.c_ulong),
        ("dwMask", ctypes.c_ulong),
        ("dwBCastAddr", ctypes.c_ulong),
        ("dwReasmSize", ctypes.c_ulong),
        ("unused1", ctypes.c_ushort),
        ("wType", ctypes.c_ushort),
    ]


class MIB_IPADDRTABLE(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_ulong), ("table", MIB_IPADDRROW * 1)]


def _array_at(struct_obj, field, count, row_type):
    """Разворачивает хвостовой массив переменной длины (ANY_SIZE) в питоновский массив."""
    return ctypes.cast(
        ctypes.byref(struct_obj, field.offset), ctypes.POINTER(row_type * count)
    ).contents


def _mac(buf, length) -> str:
    return ":".join(f"{b:02X}" for b in buf[:length]) if length else ""


# --------------------------------------------------------------- интерфейсы


def list_interfaces() -> list[dict]:
    """Снимок всех сетевых интерфейсов с накопительными счётчиками."""
    table = ctypes.POINTER(MIB_IF_TABLE2)()
    if _iphlpapi.GetIfTable2(ctypes.byref(table)) != 0:
        return []
    try:
        count = table.contents.NumEntries
        rows = _array_at(table.contents, MIB_IF_TABLE2.Table, count, MIB_IF_ROW2)
        result = []
        for r in rows:
            flags = r.InterfaceAndOperStatusFlags
            is_wifi = (
                r.Type == IF_TYPE_IEEE80211
                or r.PhysicalMediumType == NDIS_PHYSICAL_MEDIUM_NATIVE_802_11
            )
            result.append(
                {
                    "luid": r.InterfaceLuid,
                    "index": r.InterfaceIndex,
                    "guid": str(r.InterfaceGuid),
                    "name": r.Alias,
                    "description": r.Description,
                    "mac": _mac(r.PhysicalAddress, r.PhysicalAddressLength),
                    "mtu": r.Mtu,
                    "type": r.Type,
                    "is_wifi": is_wifi,
                    "is_hardware": bool(flags & FLAG_HARDWARE_INTERFACE),
                    "is_filter": bool(flags & FLAG_FILTER_INTERFACE),
                    "status": OPER_STATUS.get(r.OperStatus, "unknown"),
                    "connected": r.MediaConnectState == 1,
                    "rx_link_bps": r.ReceiveLinkSpeed,
                    "tx_link_bps": r.TransmitLinkSpeed,
                    # накопительные счётчики (с момента старта адаптера)
                    "rx_bytes": r.InOctets,
                    "tx_bytes": r.OutOctets,
                    "rx_packets": r.InUcastPkts + r.InNUcastPkts,
                    "tx_packets": r.OutUcastPkts + r.OutNUcastPkts,
                    "rx_errors": r.InErrors,
                    "tx_errors": r.OutErrors,
                    "rx_discards": r.InDiscards,
                    "tx_discards": r.OutDiscards,
                    "rx_multicast": r.InMulticastOctets,
                    "rx_broadcast": r.InBroadcastOctets,
                }
            )
        return result
    finally:
        _iphlpapi.FreeMibTable(table)


def ipv4_by_index() -> dict[int, list[str]]:
    """IPv4-адреса, сгруппированные по индексу интерфейса."""
    size = ctypes.c_ulong(0)
    _iphlpapi.GetIpAddrTable(None, ctypes.byref(size), False)
    buf = ctypes.create_string_buffer(size.value)
    if _iphlpapi.GetIpAddrTable(buf, ctypes.byref(size), False) != 0:
        return {}
    table = ctypes.cast(buf, ctypes.POINTER(MIB_IPADDRTABLE)).contents
    rows = _array_at(table, MIB_IPADDRTABLE.table, table.dwNumEntries, MIB_IPADDRROW)
    out: dict[int, list[str]] = {}
    for r in rows:
        if not r.dwAddr:
            continue
        ip = socket.inet_ntoa(r.dwAddr.to_bytes(4, "little"))
        out.setdefault(r.dwIndex, []).append(ip)
    return out


# --------------------------------------------------------------- Wi-Fi (WLAN)


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", ctypes.c_wchar * 256),
        ("isState", ctypes.c_int),
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", ctypes.c_ulong),
        ("dwIndex", ctypes.c_ulong),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", ctypes.c_ulong), ("ucSSID", ctypes.c_ubyte * 32)]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", ctypes.c_int),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11PhyType", ctypes.c_int),
        ("uDot11PhyIndex", ctypes.c_ulong),
        ("wlanSignalQuality", ctypes.c_ulong),
        ("ulRxRate", ctypes.c_ulong),
        ("ulTxRate", ctypes.c_ulong),
    ]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("bSecurityEnabled", ctypes.c_int),
        ("bOneXEnabled", ctypes.c_int),
        ("dot11AuthAlgorithm", ctypes.c_int),
        ("dot11CipherAlgorithm", ctypes.c_int),
    ]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("isState", ctypes.c_int),
        ("wlanConnectionMode", ctypes.c_int),
        ("strProfileName", ctypes.c_wchar * 256),
        ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
        ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
    ]


WLAN_OPCODE_CURRENT_CONNECTION = 7
WLAN_OPCODE_CHANNEL_NUMBER = 8
WLAN_OPCODE_RSSI = 0x10000102

INTERFACE_STATE = {
    0: "не готов",
    1: "подключён",
    2: "нет подключения",
    3: "подключение…",
    4: "ad-hoc",
    5: "отключение…",
    6: "отключён",
    7: "аутентификация…",
    8: "получение адреса…",
}


def _band_from_channel(channel: int, phy: int) -> str:
    if channel <= 0:
        return ""
    if channel <= 14:
        return "2.4 ГГц"
    if phy >= 10 and channel <= 233:
        # 6 ГГц и 5 ГГц у 802.11ax/be нумеруются пересекающимися каналами
        return "5 / 6 ГГц"
    return "5 ГГц"


class WlanClient:
    """Держит открытый хэндл WLAN-службы, чтобы не переоткрывать его каждую секунду."""

    def __init__(self) -> None:
        self._handle = None
        if _wlanapi is None:
            return
        handle = wintypes.HANDLE()
        negotiated = ctypes.c_ulong()
        try:
            rc = _wlanapi.WlanOpenHandle(
                2, None, ctypes.byref(negotiated), ctypes.byref(handle)
            )
        except OSError:
            return
        if rc == 0:
            self._handle = handle

    @property
    def available(self) -> bool:
        return self._handle is not None

    def _query(self, guid: GUID, opcode: int, out_type):
        size = ctypes.c_ulong()
        data = ctypes.c_void_p()
        rc = _wlanapi.WlanQueryInterface(
            self._handle,
            ctypes.byref(guid),
            opcode,
            None,
            ctypes.byref(size),
            ctypes.byref(data),
            None,
        )
        if rc != 0 or not data:
            return None
        try:
            # копируем, т.к. память освобождается ниже; размер режем по факту,
            # чтобы не читать за буфером, если структура вдруг разойдётся с версией ОС
            copy = out_type()
            ctypes.memmove(
                ctypes.byref(copy), data, min(size.value, ctypes.sizeof(out_type))
            )
            return copy
        finally:
            _wlanapi.WlanFreeMemory(data)

    def snapshot(self) -> dict[str, dict]:
        """Состояние всех Wi-Fi интерфейсов, ключ — GUID адаптера в верхнем регистре."""
        if self._handle is None:
            return {}
        plist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        try:
            rc = _wlanapi.WlanEnumInterfaces(self._handle, None, ctypes.byref(plist))
        except OSError:
            return {}
        if rc != 0 or not plist:
            return {}
        try:
            count = plist.contents.dwNumberOfItems
            infos = _array_at(
                plist.contents,
                WLAN_INTERFACE_INFO_LIST.InterfaceInfo,
                count,
                WLAN_INTERFACE_INFO,
            )
            out: dict[str, dict] = {}
            for info in infos:
                entry = {
                    "state": INTERFACE_STATE.get(info.isState, "неизвестно"),
                    "connected": info.isState == 1,
                    "ssid": "",
                    "bssid": "",
                    "signal": 0,
                    "rssi": None,
                    "channel": 0,
                    "band": "",
                    "phy": "",
                    "profile": "",
                    "security": "",
                    "cipher": "",
                    "link_rx_kbps": 0,
                    "link_tx_kbps": 0,
                }
                conn = self._query(
                    info.InterfaceGuid,
                    WLAN_OPCODE_CURRENT_CONNECTION,
                    WLAN_CONNECTION_ATTRIBUTES,
                )
                if conn is not None:
                    assoc = conn.wlanAssociationAttributes
                    sec = conn.wlanSecurityAttributes
                    ssid_len = min(assoc.dot11Ssid.uSSIDLength, 32)
                    entry.update(
                        ssid=bytes(assoc.dot11Ssid.ucSSID[:ssid_len]).decode(
                            "utf-8", "replace"
                        ),
                        bssid=_mac(assoc.dot11Bssid, 6),
                        signal=assoc.wlanSignalQuality,
                        phy=PHY_TYPE.get(assoc.dot11PhyType, "?"),
                        profile=conn.strProfileName,
                        link_rx_kbps=assoc.ulRxRate,
                        link_tx_kbps=assoc.ulTxRate,
                        security=(
                            AUTH_ALGO.get(sec.dot11AuthAlgorithm, "?")
                            if sec.bSecurityEnabled
                            else "открытая сеть"
                        ),
                        cipher=CIPHER_ALGO.get(sec.dot11CipherAlgorithm, "?"),
                        _phy_code=assoc.dot11PhyType,
                    )
                channel = self._query(
                    info.InterfaceGuid, WLAN_OPCODE_CHANNEL_NUMBER, ctypes.c_ulong
                )
                if channel is not None:
                    entry["channel"] = channel.value
                    entry["band"] = _band_from_channel(
                        channel.value, entry.pop("_phy_code", 0)
                    )
                entry.pop("_phy_code", None)
                rssi = self._query(info.InterfaceGuid, WLAN_OPCODE_RSSI, ctypes.c_long)
                if rssi is not None:
                    entry["rssi"] = rssi.value
                out[str(info.InterfaceGuid).upper()] = entry
            return out
        finally:
            _wlanapi.WlanFreeMemory(plist)

    def close(self) -> None:
        if self._handle is not None:
            _wlanapi.WlanCloseHandle(self._handle, None)
            self._handle = None


# ----------------------------------------------------------- TCP-соединения


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", ctypes.c_ulong),
        ("dwLocalAddr", ctypes.c_ulong),
        ("dwLocalPort", ctypes.c_ulong),
        ("dwRemoteAddr", ctypes.c_ulong),
        ("dwRemotePort", ctypes.c_ulong),
        ("dwOwningPid", ctypes.c_ulong),
    ]


class MIB_TCPTABLE_OWNER_PID(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_ulong), ("table", MIB_TCPROW_OWNER_PID * 1)]


class MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("ucLocalAddr", ctypes.c_ubyte * 16),
        ("dwLocalScopeId", ctypes.c_ulong),
        ("dwLocalPort", ctypes.c_ulong),
        ("ucRemoteAddr", ctypes.c_ubyte * 16),
        ("dwRemoteScopeId", ctypes.c_ulong),
        ("dwRemotePort", ctypes.c_ulong),
        ("dwState", ctypes.c_ulong),
        ("dwOwningPid", ctypes.c_ulong),
    ]


class MIB_TCP6TABLE_OWNER_PID(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_ulong), ("table", MIB_TCP6ROW_OWNER_PID * 1)]


TCP_TABLE_OWNER_PID_ALL = 5
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _fetch_tcp_table(family: int, table_type, row_type):
    size = ctypes.c_ulong(0)
    _iphlpapi.GetExtendedTcpTable(
        None, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if size.value == 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    rc = _iphlpapi.GetExtendedTcpTable(
        buf, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if rc != 0:
        return []
    table = ctypes.cast(buf, ctypes.POINTER(table_type)).contents
    return list(_array_at(table, table_type.table, table.dwNumEntries, row_type))


def process_name(pid: int) -> str:
    """Имя exe по PID. Для процессов другого пользователя вернёт 'PID N' без прав админа."""
    if pid == 0:
        return "System Idle"
    if pid == 4:
        return "System"
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return f"PID {pid}"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return f"PID {pid}"
    finally:
        _kernel32.CloseHandle(handle)


def tcp_connections() -> list[dict]:
    """Активные TCP-соединения (IPv4 + IPv6) вместе с PID владельца."""
    out = []
    for row in _fetch_tcp_table(
        socket.AF_INET, MIB_TCPTABLE_OWNER_PID, MIB_TCPROW_OWNER_PID
    ):
        out.append(
            {
                "pid": row.dwOwningPid,
                "state": TCP_STATE.get(row.dwState, "?"),
                "local": socket.inet_ntoa(row.dwLocalAddr.to_bytes(4, "little")),
                "local_port": socket.ntohs(row.dwLocalPort & 0xFFFF),
                "remote": socket.inet_ntoa(row.dwRemoteAddr.to_bytes(4, "little")),
                "remote_port": socket.ntohs(row.dwRemotePort & 0xFFFF),
                "family": 4,
            }
        )
    for row in _fetch_tcp_table(
        socket.AF_INET6, MIB_TCP6TABLE_OWNER_PID, MIB_TCP6ROW_OWNER_PID
    ):
        out.append(
            {
                "pid": row.dwOwningPid,
                "state": TCP_STATE.get(row.dwState, "?"),
                "local": socket.inet_ntop(socket.AF_INET6, bytes(row.ucLocalAddr)),
                "local_port": socket.ntohs(row.dwLocalPort & 0xFFFF),
                "remote": socket.inet_ntop(socket.AF_INET6, bytes(row.ucRemoteAddr)),
                "remote_port": socket.ntohs(row.dwRemotePort & 0xFFFF),
                "family": 6,
            }
        )
    return out

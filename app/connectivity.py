from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class ObserverLinkState:
    status: str
    interface: str | None
    reason: str


def _default_route_interface() -> str | None:
    route_path = Path("/proc/net/route")
    try:
        lines = route_path.read_text(encoding="ascii", errors="ignore").splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 4 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
        except ValueError:
            continue
        if flags & 0x1 and flags & 0x2:
            return fields[0]
    return None


def observer_link_state() -> ObserverLinkState:
    """Return whether this monitoring host can currently reach its LAN gateway.

    This intentionally checks the observer's own link, not any proxy node.  A
    missing carrier, address, or default route makes node test results
    untrustworthy and must therefore be recorded as an observer outage.
    """

    interface = _default_route_interface()
    stats = psutil.net_if_stats()
    addresses = psutil.net_if_addrs()
    if interface is None:
        # Non-Linux development and test environments may not expose
        # /proc/net/route.  Do not suppress monitoring there.
        if not Path("/proc/net").exists():
            return ObserverLinkState("online", None, "platform_without_route_table")
        return ObserverLinkState("offline", None, "default_route_missing")
    interface_stats = stats.get(interface)
    if interface_stats is None:
        return ObserverLinkState("offline", interface, "interface_missing")
    if not interface_stats.isup:
        return ObserverLinkState("offline", interface, "carrier_down")
    has_ipv4 = False
    for address in addresses.get(interface, ()):
        if address.family != 2 or not address.address:
            continue
        try:
            ip = ipaddress.ip_address(address.address.split("%", 1)[0])
        except ValueError:
            continue
        if ip.version == 4 and not ip.is_loopback and not ip.is_unspecified:
            has_ipv4 = True
            break
    if not has_ipv4:
        return ObserverLinkState("offline", interface, "ipv4_missing")
    return ObserverLinkState("online", interface, "link_ready")

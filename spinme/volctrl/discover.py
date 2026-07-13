"""
Optional discovery of Volumio on the local network.
Uses zeroconf (mDNS); not required for core API. On MicroPython use fixed host or simple UDP.
"""

from __future__ import annotations

import socket


def resolve_volumio_local(timeout: float = 2.0) -> str | None:
    """Resolve volumio.local to an IP; returns IP string or None. No extra deps."""
    try:
        infos = socket.getaddrinfo("volumio.local", 3000, socket.AF_INET)
        if infos:
            return infos[0][4][0]
    except (socket.gaierror, OSError):
        pass
    return None


# Volumio registers as _Volumio._tcp (capital V) per mDNS
_VOLUMIO_SERVICE_TYPE = "_Volumio._tcp.local."


def discover_zeroconf() -> list[tuple[str, int]]:
    """Discover Volumio instances via mDNS (_Volumio._tcp). Requires zeroconf."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
        from zeroconf import ServiceListener
    except ImportError:
        return []

    results: list[tuple[str, int]] = []

    class Listener(ServiceListener):
        def add_service(self, zc: object, type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name)
            if info and info.addresses:
                addr = socket.inet_ntoa(info.addresses[0])
                results.append((addr, info.port or 3000))

    zc = Zeroconf()
    try:
        browser = ServiceBrowser(zc, _VOLUMIO_SERVICE_TYPE, Listener())
        import time
        time.sleep(1.5)
    finally:
        zc.close()
    return results


def discover(timeout: float = 2.0) -> list[tuple[str, int]]:
    """Return list of (host, port). Tries volumio.local first, then zeroconf."""
    out: list[tuple[str, int]] = []
    ip = resolve_volumio_local(timeout=timeout)
    if ip:
        out.append((ip, 3000))
    for addr, port in discover_zeroconf():
        if (addr, port) not in out:
            out.append((addr, port))
    return out

"""Wake-on-LAN: build and send the magic packet.

The magic packet is 6 bytes of 0xFF followed by the target MAC repeated 16
times, sent as a UDP broadcast (or to a directed IP) on port 9.
"""

from __future__ import annotations

import socket
from typing import Optional


class WolError(ValueError):
    """Raised on an invalid MAC address."""


def parse_mac(mac: str) -> bytes:
    """Parse a MAC string into 6 bytes. Accepts ':', '-' or no separators."""
    if not isinstance(mac, str):
        raise WolError("MAC must be a string")
    cleaned = mac.strip().lower().replace(":", "").replace("-", "").replace(".", "")
    if len(cleaned) != 12:
        raise WolError(f"invalid MAC length: {mac!r}")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise WolError(f"invalid MAC: {mac!r}") from exc


def magic_packet(mac: str) -> bytes:
    """Build the 102-byte WoL magic packet for the given MAC."""
    b = parse_mac(mac)
    return b"\xff" * 6 + b * 16


def _send_one(sock: socket.socket, packet: bytes, dest: str, port: int) -> None:
    sock.sendto(packet, (dest, port))


def send_wol(mac: str, ip: Optional[str] = None, port: int = 9) -> str:
    """Send the magic packet. Returns the destination address used.

    If ``ip`` is given the packet is also sent directed to that host (in
    addition to the broadcast), which improves reliability across some
    switches.
    """
    packet = magic_packet(mac)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(2.0)
        _send_one(sock, packet, "255.255.255.255", port)
        if ip:
            _send_one(sock, packet, ip, port)
        return "255.255.255.255" + (f",{ip}" if ip else "")
    finally:
        sock.close()

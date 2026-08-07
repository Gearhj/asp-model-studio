"""Exclusive OS-assigned loopback port reservations for isolated ATLAS runs.

The normal ATLAS listeners are deliberately excluded.  Reservations stay open
until an orchestrator releases the named socket immediately before it starts
the corresponding child listener, narrowing the bind race without touching a
live service.
"""

from __future__ import annotations

import socket
from types import MappingProxyType
from typing import Iterable, Mapping


LOOPBACK_HOST = "127.0.0.1"
LIVE_ATLAS_PORTS = frozenset({5174, 8001})
MIN_UNPRIVILEGED_PORT = 1024
MAX_PORT = 65535
MAX_RESERVATION_ATTEMPTS = 64


class IsolatedLoopbackPortError(RuntimeError):
    """A port plan was unsafe or contradicted its held reservations."""


def validate_non_live_ports(
    ports: Iterable[int],
    *,
    excluded_ports: Iterable[int] = LIVE_ATLAS_PORTS,
) -> tuple[int, ...]:
    """Validate distinct, unprivileged, non-live TCP ports."""

    values = tuple(int(port) for port in ports)
    excluded = frozenset(int(port) for port in excluded_ports)
    if not values or len(values) != len(set(values)):
        raise IsolatedLoopbackPortError("Isolated ports must be nonempty and distinct.")
    if any(port < MIN_UNPRIVILEGED_PORT or port > MAX_PORT for port in values):
        raise IsolatedLoopbackPortError("Isolated ports must be unprivileged TCP ports.")
    if set(values).intersection(excluded):
        raise IsolatedLoopbackPortError("A protected ATLAS service port was selected.")
    return values


def _exclusive_loopback_socket() -> socket.socket:
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        reservation.bind((LOOPBACK_HOST, 0))
        reservation.listen(1)
        return reservation
    except BaseException:
        reservation.close()
        raise


class ReservedLoopbackPorts:
    """Own named loopback sockets until each child listener is ready to start."""

    def __init__(self, sockets: Mapping[str, socket.socket]) -> None:
        if not sockets or any(not str(name).strip() for name in sockets):
            raise IsolatedLoopbackPortError("Reservation names must be nonempty.")
        self._sockets = dict(sockets)
        self._ports = {
            name: int(reservation.getsockname()[1])
            for name, reservation in self._sockets.items()
        }
        validate_non_live_ports(self._ports.values())

    @property
    def ports(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._ports))

    def assert_exact(self, expected: Mapping[str, int]) -> None:
        normalized = {str(name): int(port) for name, port in expected.items()}
        if normalized != self._ports or set(self._sockets) != set(self._ports):
            raise IsolatedLoopbackPortError(
                "The orchestrator port plan does not match its held reservations."
            )
        for name, reservation in self._sockets.items():
            if reservation.fileno() < 0:
                raise IsolatedLoopbackPortError(
                    f"The {name} port reservation was released too early."
                )

    def release(self, name: str) -> int:
        try:
            reservation = self._sockets.pop(name)
            port = self._ports[name]
        except KeyError as exc:
            raise IsolatedLoopbackPortError(
                "The requested port reservation is missing or already released."
            ) from exc
        reservation.close()
        return port

    def close(self) -> None:
        for reservation in tuple(self._sockets.values()):
            reservation.close()
        self._sockets.clear()

    def __enter__(self) -> "ReservedLoopbackPorts":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def reserve_dynamic_non_live_ports(
    names: Iterable[str] = ("backend", "frontend"),
) -> ReservedLoopbackPorts:
    """Reserve distinct OS-assigned ports while excluding live ATLAS ports."""

    normalized_names = tuple(str(name).strip() for name in names)
    if (
        not normalized_names
        or any(not name for name in normalized_names)
        or len(normalized_names) != len(set(normalized_names))
    ):
        raise IsolatedLoopbackPortError("Reservation names must be unique and nonempty.")
    sockets: dict[str, socket.socket] = {}
    try:
        for name in normalized_names:
            for _attempt in range(MAX_RESERVATION_ATTEMPTS):
                reservation = _exclusive_loopback_socket()
                port = int(reservation.getsockname()[1])
                if port not in LIVE_ATLAS_PORTS and port >= MIN_UNPRIVILEGED_PORT:
                    sockets[name] = reservation
                    break
                reservation.close()
            else:
                raise IsolatedLoopbackPortError(
                    "The operating system did not provide a safe isolated port."
                )
        return ReservedLoopbackPorts(sockets)
    except BaseException:
        for reservation in sockets.values():
            reservation.close()
        raise


__all__ = [
    "IsolatedLoopbackPortError",
    "LIVE_ATLAS_PORTS",
    "LOOPBACK_HOST",
    "MAX_RESERVATION_ATTEMPTS",
    "ReservedLoopbackPorts",
    "reserve_dynamic_non_live_ports",
    "validate_non_live_ports",
]

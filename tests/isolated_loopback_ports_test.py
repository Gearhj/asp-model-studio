from __future__ import annotations

import socket

import pytest

from scripts.isolated_loopback_ports import (
    IsolatedLoopbackPortError,
    LIVE_ATLAS_PORTS,
    reserve_dynamic_non_live_ports,
    validate_non_live_ports,
)
from scripts import run_bureau_metadata_integrated_closeout as closeout
from scripts import run_bureau_metadata_production_auth_acceptance as production


def _bind_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            candidate.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def test_os_assigned_ports_are_distinct_non_live_and_exclusively_reserved() -> None:
    reservations = reserve_dynamic_non_live_ports()
    ports = dict(reservations.ports)
    try:
        assert set(ports) == {"backend", "frontend"}
        assert len(set(ports.values())) == 2
        assert not set(ports.values()).intersection(LIVE_ATLAS_PORTS)
        assert all(port >= 1024 for port in ports.values())
        assert not _bind_is_available(ports["backend"])
        assert not _bind_is_available(ports["frontend"])

        assert reservations.release("backend") == ports["backend"]
        assert _bind_is_available(ports["backend"])
        assert not _bind_is_available(ports["frontend"])
    finally:
        reservations.close()
    assert _bind_is_available(ports["frontend"])


def test_reservation_plan_fails_closed_for_live_duplicate_or_mismatched_ports() -> None:
    with pytest.raises(IsolatedLoopbackPortError, match="protected"):
        validate_non_live_ports((5174, 19082))
    with pytest.raises(IsolatedLoopbackPortError, match="distinct"):
        validate_non_live_ports((19081, 19081))

    reservations = reserve_dynamic_non_live_ports()
    try:
        ports = dict(reservations.ports)
        with pytest.raises(IsolatedLoopbackPortError, match="does not match"):
            reservations.assert_exact(
                {"backend": ports["frontend"], "frontend": ports["backend"]}
            )
        production._assert_ports(
            ports["backend"],
            ports["frontend"],
            reservations=reservations,
        )
    finally:
        reservations.close()


def test_production_and_closeout_wrappers_release_reservations_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production_reservations = reserve_dynamic_non_live_ports()
    production_ports = dict(production_reservations.ports)

    def fail_production(*_args, **kwargs):
        assert kwargs["port_reservations"] is production_reservations
        production_reservations.assert_exact(production_ports)
        raise RuntimeError("synthetic pre-start failure")

    monkeypatch.setattr(production, "_run_acceptance_with_ports", fail_production)
    with pytest.raises(RuntimeError, match="synthetic pre-start failure"):
        production.run_acceptance(
            production.REPOSITORY_ROOT / "unused-authority-map.json",
            backend_port=production_ports["backend"],
            frontend_port=production_ports["frontend"],
            port_reservations=production_reservations,
        )
    assert all(_bind_is_available(port) for port in production_ports.values())

    closeout_reservations = reserve_dynamic_non_live_ports()
    closeout_ports = dict(closeout_reservations.ports)

    def fail_closeout(*_args, **kwargs):
        assert kwargs["port_reservations"] is closeout_reservations
        closeout_reservations.assert_exact(closeout_ports)
        raise RuntimeError("synthetic closeout pre-start failure")

    monkeypatch.setattr(closeout, "_run_integrated_closeout_with_ports", fail_closeout)
    settings = closeout.IntegratedCloseoutSettings(
        authority_map=closeout.REPOSITORY_ROOT / "unused-authority-map.json",
        backend_port=closeout_ports["backend"],
        frontend_port=closeout_ports["frontend"],
    )
    with pytest.raises(RuntimeError, match="synthetic closeout pre-start failure"):
        closeout.run_integrated_closeout(
            settings,
            port_reservations=closeout_reservations,
        )
    assert all(_bind_is_available(port) for port in closeout_ports.values())


def test_closeout_cli_defaults_to_dynamic_ports_and_rejects_partial_override() -> None:
    for parser in (closeout._parser(), production._parser()):
        dynamic = parser.parse_args(["--authority-map", "isolated-authorities.json"])
        assert dynamic.backend_port == 0
        assert dynamic.frontend_port == 0

    # The shared validator is the public contract used by both orchestrators.
    with pytest.raises(IsolatedLoopbackPortError):
        validate_non_live_ports((0, 19082))

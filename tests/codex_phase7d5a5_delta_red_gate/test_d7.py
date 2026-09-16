"""D7 delta-red gate: temporary data authority must be session-bound."""
from __future__ import annotations

import getpass
import os
import tempfile
from pathlib import Path

import pytest

from tests import _isolated_data_guard as G


_PREFIX = "D7_SESSION_BOUND_TEMP_AUTHORITY:"


def _predictable_pytest_parent() -> Path:
    return (Path(tempfile.gettempdir()) / f"pytest-of-{getpass.getuser()}").resolve()


def _active_session_root() -> Path:
    configured = os.environ.get("ASP_ISOLATED_TEST_TEMP", "").strip()
    assert configured, f"{_PREFIX} active session root was not established by the gate"
    return Path(configured).resolve()


def _assert_rejected_before_io(path: Path, scenario: str) -> None:
    assert G._installed["on"], f"{_PREFIX} production guard was not installed"
    assert not path.exists(), f"{_PREFIX} probe path unexpectedly exists: {path}"
    before = len(G.violations())
    try:
        # Directly exercise the production policy decision.  No reader/open is
        # called, so an accepted decision cannot be hidden by FileNotFoundError.
        G.check_open(path, f"delta-d7:{scenario}")
    except G.IsolatedDataViolation:
        assert len(G.violations()) == before + 1
        assert not path.exists()
        return
    pytest.fail(
        f"{_PREFIX} guard authorized nonexistent {scenario} data by parent/path naming before any I/O: {path}"
    )


def test_predictable_pytest_user_temp_prefix_does_not_grant_data_authority() -> None:
    path = _predictable_pytest_parent() / "unrelated-session" / "arbitrary-data.parquet"
    _assert_rejected_before_io(path, "predictable-pytest-user-prefix")


def test_sibling_pytest_session_root_is_rejected() -> None:
    path = _predictable_pytest_parent() / "pytest-sibling-917" / "arbitrary-data.parquet"
    _assert_rejected_before_io(path, "sibling-pytest-session")


def test_forged_session_directory_name_is_rejected() -> None:
    path = _predictable_pytest_parent() / "pytest-current" / "session-0" / "arbitrary-data.parquet"
    _assert_rejected_before_io(path, "forged-session-name")


def test_active_session_leaf_requires_capability_marker() -> None:
    path = _active_session_root() / "unmarked-leaf" / "arbitrary-data.parquet"
    _assert_rejected_before_io(path, "active-session-leaf-without-capability")


def test_session_capability_is_bound_to_exact_root() -> None:
    active = _active_session_root()
    path = _predictable_pytest_parent() / f"{active.name}-replayed-capability" / "arbitrary-data.parquet"
    _assert_rejected_before_io(path, "capability-replayed-in-different-root")


def test_arbitrary_parquet_under_allowed_parent_is_rejected_before_io() -> None:
    path = _predictable_pytest_parent() / "pytest-999" / "nested" / "sports-model.parquet"
    _assert_rejected_before_io(path, "arbitrary-parquet-under-allowed-parent")

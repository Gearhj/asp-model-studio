"""D7 final-red gate: session data authority must be process- and issued-leaf-bound."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _isolated_data_guard as G


REPO = Path(__file__).resolve().parents[2]
_PREFIX = "D7_PROCESS_AND_LEAF_BOUND_SESSION_AUTHORITY:"
_HARNESS = "PHASE7D5A11_D7_HARNESS_ERROR:"


def _node_signature(name: str) -> str:
    return f"{_PREFIX}{name}:"


def _probe_environment(
    root: Path,
    *,
    capability: str | None = None,
    session_root: Path | None = None,
) -> dict[str, str]:
    runtime = root / "isolated-runtime"
    os_temp = root / "os-temp"
    model_exchange = root / "model-exchange-disabled"
    for path in (runtime, os_temp, model_exchange):
        path.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "ASP_REQUIRE_ISOLATED_RUNTIME": "1",
        "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(runtime),
        "ASP_ISOLATED_TEST_TEMP": str(
            session_root.resolve() if session_root is not None else root / "active-session"
        ),
        "ASP_MODEL_EXCHANGE_ROOT": str(model_exchange),
        "TEMP": str(os_temp),
        "TMP": str(os_temp),
        "PYTHONPATH": os.pathsep.join(
            part for part in (str(REPO), os.environ.get("PYTHONPATH", "")) if part
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    if capability is None:
        env.pop(G.SESSION_CAPABILITY_ENV, None)
    else:
        env[G.SESSION_CAPABILITY_ENV] = capability
    return env


def _run_json_probe(
    root: Path,
    code: str,
    *arguments: Path,
    capability: str | None = None,
    session_root: Path | None = None,
) -> dict[str, object]:
    resolved = root.resolve()
    assert REPO != resolved and REPO not in resolved.parents, (
        f"{_HARNESS} disposable probe root must be outside the repository"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, *(str(path) for path in arguments)],
        cwd=REPO,
        env=_probe_environment(
            resolved,
            capability=capability,
            session_root=session_root,
        ),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, (
        f"{_HARNESS} synthetic child probe failed before reaching the D7 boundary "
        f"(rc={completed.returncode})"
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, f"{_HARNESS} synthetic child probe emitted no result"
    try:
        payload = json.loads(lines[-1])
    except (TypeError, ValueError):
        pytest.fail(f"{_HARNESS} synthetic child probe emitted invalid result JSON")
    assert isinstance(payload, dict), f"{_HARNESS} synthetic child probe result was not an object"
    assert not payload.get("probeError"), (
        f"{_HARNESS} synthetic child probe failed inside {payload.get('probeError')}"
    )
    return payload


def _pin_non_session_roots(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    synthetic_repo = root / "synthetic-repository"
    monkeypatch.setitem(G._installed, "on", True)
    monkeypatch.setattr(G, "_allowed_roots", lambda: [])
    monkeypatch.setattr(G, "_repo_root", lambda: synthetic_repo.resolve())
    monkeypatch.setattr(G, "_real_runtime", lambda: (synthetic_repo / ".runtime").resolve())


def _assert_rejected_before_io(path: Path, scenario: str, node_signature: str) -> None:
    assert not path.exists(), f"{_HARNESS} synthetic probe unexpectedly exists"
    before = len(G.violations())
    try:
        G.check_open(path, f"final-red-d7:{scenario}")
    except G.IsolatedDataViolation:
        assert len(G.violations()) == before + 1
        assert not path.exists()
        return
    pytest.fail(f"{node_signature} guard authorized {scenario} before data I/O")


def _issue_marker(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path]:
    del monkeypatch
    # ``tmp_path`` is created and marked by the real root conftest lifecycle.
    # Reuse that genuinely issued leaf/capability instead of self-minting an env
    # token, so a process-issued-authority repair keeps this setup valid.
    issued_leaf = root.resolve()
    marker = issued_leaf / G.SESSION_MARKER_NAME
    session_root = G._session_root()
    capability = os.environ.get(G.SESSION_CAPABILITY_ENV, "")
    assert session_root is not None and capability, (
        f"{_HARNESS} generic pytest lifecycle did not establish session authority"
    )
    assert marker.is_file() and G._valid_marker(marker, session_root, capability), (
        f"{_HARNESS} tmp_path lacks its genuine lifecycle-issued marker"
    )
    return issued_leaf, marker


def test_marker_with_wrong_process_id_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued_leaf, marker = _issue_marker(monkeypatch, tmp_path)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["sessionProcessId"] = os.getpid() + 1
    marker.write_text(json.dumps(payload), encoding="utf-8")
    _pin_non_session_roots(monkeypatch, tmp_path)

    _assert_rejected_before_io(
        issued_leaf / "never-created.parquet",
        "wrong-process marker",
        _node_signature("test_marker_with_wrong_process_id_is_rejected"),
    )


def test_session_start_does_not_retain_untrusted_preexisting_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inherited = secrets.token_hex(32)
    monkeypatch.setenv(G.SESSION_CAPABILITY_ENV, inherited)
    rejected = False
    result: object = None
    try:
        result = G.establish_session_capability()
    except Exception:
        rejected = True
    active = os.environ.get(G.SESSION_CAPABILITY_ENV, "")
    fresh = bool(active) and active != inherited and (result is None or result == active)

    assert rejected or fresh, (
        f"{_node_signature('test_session_start_does_not_retain_untrusted_preexisting_capability')} "
        "session start silently retained an untrusted inherited capability"
    )


def test_unrelated_temp_path_factory_cannot_rebind_active_session_authority(tmp_path: Path) -> None:
    code = r'''
import json, os, secrets, sys
from pathlib import Path
from types import SimpleNamespace

root = Path(sys.argv[1]).resolve()
active = root / "active-session"
unrelated = root / "unrelated-factory"
active.mkdir(parents=True, exist_ok=True)
unrelated.mkdir(parents=True, exist_ok=True)
os.environ["ASP_ISOLATED_TEST_TEMP"] = str(active)
os.environ.pop("ASP_ISOLATED_SESSION_CAPABILITY", None)

try:
    from tests import _isolated_data_guard as G
    import tests.conftest as C
    C.pytest_configure(SimpleNamespace(option=SimpleNamespace(basetemp=str(active))))
    established = Path(os.environ[G.SESSION_ROOT_ENV]).resolve()
except Exception as exc:
    print(json.dumps({"probeError": type(exc).__name__}))
else:
    from _pytest.tmpdir import TempPathFactory
    rejected = False
    try:
        factory = TempPathFactory(None, 3, "all", lambda *a, **k: None,
                                  basetemp=unrelated, _ispytest=True)
        factory.mktemp("foreign")
    except Exception:
        # A fail-closed production repair may reject an unrelated factory
        # outright; that is a valid corrected outcome, not a probe failure.
        rejected = True
    root_unchanged = Path(os.environ[G.SESSION_ROOT_ENV]).resolve() == established
    try:
        minted_markers = [str(p) for p in unrelated.rglob(G.SESSION_MARKER_NAME)]
    except OSError as exc:
        print(json.dumps({"probeError": f"marker-inventory-{type(exc).__name__}"}))
    else:
        print(json.dumps({"rejected": rejected, "rootUnchanged": root_unchanged,
                          "mintedMarkers": minted_markers}))
'''
    result = _run_json_probe(tmp_path, code, tmp_path)

    assert result["rootUnchanged"] and result["mintedMarkers"] == [], (
        f"{_node_signature('test_unrelated_temp_path_factory_cannot_rebind_active_session_authority')} "
        "an unrelated TempPathFactory rebound or minted active-session authority"
    )


def test_copying_valid_marker_bytes_to_sibling_does_not_authorize_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued_leaf, marker = _issue_marker(monkeypatch, tmp_path)
    sibling = issued_leaf.parent / "manually-created-sibling"
    sibling.mkdir()
    (sibling / G.SESSION_MARKER_NAME).write_bytes(marker.read_bytes())
    _pin_non_session_roots(monkeypatch, tmp_path)

    _assert_rejected_before_io(
        sibling / "never-created.parquet",
        "copied-marker sibling",
        _node_signature("test_copying_valid_marker_bytes_to_sibling_does_not_authorize_sibling"),
    )


def test_child_process_requires_its_own_process_bound_session_issuance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued_leaf, _marker = _issue_marker(monkeypatch, tmp_path)
    capability = os.environ[G.SESSION_CAPABILITY_ENV]
    session_root = G._session_root()
    assert session_root is not None, f"{_HARNESS} lifecycle session root is absent"
    code = r'''
import json, os, sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
synthetic_repo = Path(sys.argv[2]).resolve()
try:
    from tests import _isolated_data_guard as G
    G._installed["on"] = True
    G._allowed_roots = lambda: []
    G._repo_root = lambda: synthetic_repo
    G._real_runtime = lambda: synthetic_repo / ".runtime"
    try:
        G.check_open(target, "final-red-d7:inherited-child")
    except G.IsolatedDataViolation:
        rejected = True
    else:
        rejected = False
    print(json.dumps({"rejected": rejected, "targetExists": target.exists()}))
except Exception as exc:
    print(json.dumps({"probeError": type(exc).__name__}))
'''
    target = issued_leaf / "never-created.parquet"
    result = _run_json_probe(
        tmp_path,
        code,
        target,
        tmp_path / "synthetic-repository",
        capability=capability,
        session_root=session_root,
    )

    assert not result["targetExists"]
    assert result["rejected"], (
        f"{_node_signature('test_child_process_requires_its_own_process_bound_session_issuance')} "
        "child process inherited parent marker authority without child issuance"
    )


def test_marker_from_prior_session_cannot_authorize_new_session(tmp_path: Path) -> None:
    session_root = tmp_path / "reused-session-root"
    issued_leaf = session_root / "prior-issued-leaf"
    issue_code = r'''
import json, os, sys
from pathlib import Path

session_root = Path(sys.argv[1]).resolve()
issued_leaf = Path(sys.argv[2]).resolve()
try:
    session_root.mkdir(parents=True, exist_ok=True)
    os.environ["ASP_ISOLATED_TEST_TEMP"] = str(session_root)
    from tests import _isolated_data_guard as G
    G.establish_session_capability()
    G.write_session_marker(issued_leaf)
    print(json.dumps({"markerWritten": (issued_leaf / G.SESSION_MARKER_NAME).is_file()}))
except Exception as exc:
    print(json.dumps({"probeError": type(exc).__name__}))
'''
    issued = _run_json_probe(tmp_path, issue_code, session_root, issued_leaf)
    assert issued["markerWritten"], f"{_HARNESS} prior synthetic session did not issue its marker"

    marker_path = issued_leaf / G.SESSION_MARKER_NAME
    prior_marker = json.loads(marker_path.read_text(encoding="utf-8"))
    prior_capability = prior_marker.get("capability")
    assert isinstance(prior_capability, str) and prior_capability, (
        f"{_HARNESS} prior synthetic marker did not contain internal authority"
    )

    replay_code = r'''
import json, os, sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
synthetic_repo = Path(sys.argv[2]).resolve()
try:
    from tests import _isolated_data_guard as G
    os.environ[G.SESSION_ROOT_ENV] = str(target.parent.parent)
    establishment_rejected = False
    try:
        G.establish_session_capability()
    except Exception:
        establishment_rejected = True
    if establishment_rejected:
        rejected = True
    else:
        G._installed["on"] = True
        G._allowed_roots = lambda: []
        G._repo_root = lambda: synthetic_repo
        G._real_runtime = lambda: synthetic_repo / ".runtime"
        try:
            G.check_open(target, "final-red-d7:stale-session-replay")
        except G.IsolatedDataViolation:
            rejected = True
        else:
            rejected = False
    print(json.dumps({"rejected": rejected, "targetExists": target.exists()}))
except Exception as exc:
    print(json.dumps({"probeError": type(exc).__name__}))
'''
    target = issued_leaf / "never-created.parquet"
    replayed = _run_json_probe(
        tmp_path,
        replay_code,
        target,
        tmp_path / "synthetic-repository",
        capability=prior_capability,
    )

    assert not replayed["targetExists"]
    assert replayed["rejected"], (
        f"{_node_signature('test_marker_from_prior_session_cannot_authorize_new_session')} "
        "a prior-session marker authorized a new process/session"
    )

"""Phase 7D.5A.2 (Repair 7) — fail-closed external-data access guard for the isolated gate.

Active ONLY when ``ASP_REQUIRE_ISOLATED_RUNTIME`` is set. It wraps the project's high-level data readers (pyarrow /
pandas / polars parquet+csv) and, for every sports/model DATA open, requires the path to live under an allowed root:
the exact-HEAD repository (EXCEPT the real ``.runtime`` data tree), the isolated runtime root, the OS temp tree, or
the Python environment. Any other open — e.g. the real ``C:/Users/james/asp-model-exchange`` corpus or the real
``.runtime`` sealed objects — fails immediately and logs the requesting test, path, reader, allowed roots, and any
detected season/sealed identity. Zero real-2025 access becomes demonstrable, not assumed.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

_DATA_SUFFIXES = {".parquet", ".pq", ".csv", ".feather", ".arrow", ".joblib", ".pkl", ".pickle", ".npy", ".npz"}
_violations: list[dict] = []
_current_nodeid = {"id": "<session>"}
_installed = {"on": False}

# D7 — EXACT ACTIVE-SESSION DATA AUTHORITY. Temporary-root authority is NOT inferred from a predictable pytest/OS
# temp pathname; it is a capability EXPLICITLY established by the active isolated session. The session establishes one
# random capability + one canonical session root (env vars below), and drops a content-bound capability marker into
# each per-test scratch directory it owns. The guard authorizes a data path ONLY when an ancestor between the path
# and the canonical session root carries a marker that binds the exact root + the exact capability. A sibling
# session, a forged/copied root name under another parent, a markerless leaf, or an altered marker/capability all
# fail — filesystem naming grants nothing.
SESSION_ROOT_ENV = "ASP_ISOLATED_TEST_TEMP"
SESSION_CAPABILITY_ENV = "ASP_ISOLATED_SESSION_CAPABILITY"
SESSION_MARKER_NAME = ".asp-isolated-session-capability.json"
SESSION_MARKER_SCHEMA = "ASP_ISOLATED_SESSION_CAPABILITY_V1"


def is_active() -> bool:
    return os.getenv("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes")


def _allowed_roots() -> list[Path]:
    # Non-session, always-governed roots ONLY: the isolated runtime root and the Python environment. The OS temp
    # tree, the ``pytest-of-<user>`` prefix, and even the declared session root are NEVER blanket-authorized here —
    # data under the session root is authorized separately, and only through an exact capability marker (see
    # _session_authorized). Kept as a small stubbable function so the R7 reader-interception probes can pin it.
    from server.sports_cockpit.engine import RUNTIME_ROOT
    return [Path(RUNTIME_ROOT).resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]


def establish_session_capability() -> str:
    """Establish (once) the active isolated session's random capability; return it. Idempotent within a process."""
    cap = os.environ.get(SESSION_CAPABILITY_ENV, "").strip()
    if not cap:
        cap = secrets.token_hex(32)
        os.environ[SESSION_CAPABILITY_ENV] = cap
    return cap


def _session_root() -> Path | None:
    raw = os.environ.get(SESSION_ROOT_ENV, "").strip()
    if not raw:
        return None
    try:
        return Path(raw).resolve()
    except OSError:
        return None


def write_session_marker(session_dir) -> None:
    """Drop a capability marker into a per-test scratch directory the active session owns. The marker binds the exact
    canonical session root, the exact capability, and the process identity — never a display/path pattern."""
    root = _session_root()
    cap = os.environ.get(SESSION_CAPABILITY_ENV, "").strip()
    if root is None or not cap:
        return
    try:
        d = Path(session_dir).resolve()
    except OSError:
        return
    if not _under(d, root):
        return
    marker = {
        "schemaVersion": SESSION_MARKER_SCHEMA,
        "canonicalSessionRoot": str(root),
        "capability": cap,
        "sessionProcessId": os.getpid(),
    }
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / SESSION_MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")
    except OSError:
        pass


def _valid_marker(marker_path: Path, root: Path, cap: str) -> bool:
    try:
        if not marker_path.is_file():
            return False
        data = json.loads(marker_path.read_bytes().decode("utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    try:
        declared_root = Path(str(data.get("canonicalSessionRoot", ""))).resolve()
    except OSError:
        return False
    return (data.get("schemaVersion") == SESSION_MARKER_SCHEMA
            and declared_root == root
            and data.get("capability") == cap)


def _session_authorized(p: Path) -> bool:
    """True iff ``p`` lies under the EXACT capability-marked active session root: some ancestor between p and the
    canonical session root (inclusive) carries a valid marker binding that exact root + the exact capability."""
    root = _session_root()
    cap = os.environ.get(SESSION_CAPABILITY_ENV, "").strip()
    if root is None or not cap or not _under(p, root):
        return False
    cur = p
    while True:
        if _valid_marker(cur / SESSION_MARKER_NAME, root, cap):
            return True
        if cur == root:
            return False
        parent = cur.parent
        if parent == cur:
            return False
        cur = parent


def _real_runtime() -> Path:
    from server.sports_cockpit.engine import REPO_ROOT
    return (Path(REPO_ROOT) / ".runtime").resolve()


def _repo_root() -> Path:
    from server.sports_cockpit.engine import REPO_ROOT
    return Path(REPO_ROOT).resolve()


def _norm(p) -> Path:
    return Path(os.path.normpath(str(Path(p).absolute())))


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def check_open(path, reader: str):
    if not _installed["on"]:
        return
    try:
        p = _norm(path)
    except Exception:
        return
    if p.suffix.lower() not in _DATA_SUFFIXES:
        return
    repo, real_rt = _repo_root(), _real_runtime()
    allowed = _allowed_roots()
    ok = any(_under(p, r) for r in allowed)
    # the repository is allowed EXCEPT its real .runtime data tree (which holds the sealed/real objects)
    if not ok and _under(p, repo) and not _under(p, real_rt):
        ok = True
    # D7 — otherwise the ONLY temporary authority is the exact capability-marked active session root
    if not ok and _session_authorized(p):
        ok = True
    if ok and _under(p, real_rt):
        ok = False       # never the real .runtime under isolation
    if not ok:
        s = str(p)
        rec = {"test": _current_nodeid["id"], "path": s, "reader": reader,
               "allowedRoots": [str(r) for r in allowed] + [f"{repo} (except {real_rt})"],
               "sealedOr2025": ("2025" in s) or ("sealed" in s.lower())}
        _violations.append(rec)
        raise IsolatedDataViolation(
            f"ISOLATED-DATA VIOLATION [{reader}] test={rec['test']} opened non-isolated data path: {s} "
            f"(sealed/2025={rec['sealedOr2025']}); allowed roots: {rec['allowedRoots']}")


class IsolatedDataViolation(RuntimeError):
    pass


def violations() -> list[dict]:
    return list(_violations)


def set_current_nodeid(nodeid: str):
    _current_nodeid["id"] = nodeid


class GuardInstallError(RuntimeError):
    """A REQUIRED data reader could not be wrapped — the guard is not trustworthy, so installation fails closed."""


def _mk_first_arg(orig, rlabel):
    def _g(path, *a, **k):
        if isinstance(path, (str, os.PathLike)):
            check_open(path, rlabel)
        return orig(path, *a, **k)
    return _g


def install():
    """Wrap the high-level data readers. Idempotent. A REQUIRED reader that cannot be wrapped is FATAL: a guard
    that silently fails to cover a reader would let external data through, so it must not report success."""
    if _installed["on"]:
        return
    _installed["on"] = True

    # ---- builtins.open + Path.read_bytes: the lowest-level data readers many others route through ------------
    try:
        import builtins
        _orig_open = builtins.open

        def _guarded_open(file, *a, **k):
            if isinstance(file, (str, os.PathLike)):
                check_open(file, "builtins.open")
            return _orig_open(file, *a, **k)
        builtins.open = _guarded_open

        _orig_read_bytes = Path.read_bytes

        def _guarded_read_bytes(self, *a, **k):
            check_open(self, "Path.read_bytes")
            return _orig_read_bytes(self, *a, **k)
        Path.read_bytes = _guarded_read_bytes
    except Exception as exc:
        raise GuardInstallError(f"required reader builtins.open/Path.read_bytes could not be wrapped: {exc}")

    # ---- pyarrow.parquet + pyarrow.dataset (REQUIRED) --------------------------------------------------------
    try:
        import pyarrow.parquet as _pq
        _pq.read_table = _mk_first_arg(_pq.read_table, "pyarrow.parquet.read_table")
        _pq.ParquetFile = _mk_first_arg(_pq.ParquetFile, "pyarrow.parquet.ParquetFile")
        import pyarrow.dataset as _ds
        _ds.dataset = _mk_first_arg(_ds.dataset, "pyarrow.dataset.dataset")
    except Exception as exc:
        raise GuardInstallError(f"required reader pyarrow.parquet/dataset could not be wrapped: {exc}")

    # ---- pandas + joblib (REQUIRED) --------------------------------------------------------------------------
    try:
        import pandas as _pd
        for name, reader in (("read_parquet", "pandas.read_parquet"), ("read_csv", "pandas.read_csv"),
                             ("read_feather", "pandas.read_feather")):
            if getattr(_pd, name, None) is not None:
                setattr(_pd, name, _mk_first_arg(getattr(_pd, name), reader))
        import joblib as _jl
        _jl.load = _mk_first_arg(_jl.load, "joblib.load")
    except Exception as exc:
        raise GuardInstallError(f"required reader pandas/joblib could not be wrapped: {exc}")

    # ---- polars (OPTIONAL — not installed in every environment) ----------------------------------------------
    try:
        import polars as _pl
        for name, reader in (("read_parquet", "polars.read_parquet"), ("scan_parquet", "polars.scan_parquet"),
                             ("read_csv", "polars.read_csv")):
            if getattr(_pl, name, None) is not None:
                setattr(_pl, name, _mk_first_arg(getattr(_pl, name), reader))
    except ImportError:
        pass

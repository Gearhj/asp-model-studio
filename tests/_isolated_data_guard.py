"""Phase 7D.5A.2 (Repair 7) — fail-closed external-data access guard for the isolated gate.

Active ONLY when ``ASP_REQUIRE_ISOLATED_RUNTIME`` is set. It wraps the project's high-level data readers (pyarrow /
pandas / polars parquet+csv) and, for every sports/model DATA open, requires the path to live under an allowed root:
the exact-HEAD repository (EXCEPT the real ``.runtime`` data tree), the isolated runtime root, the OS temp tree, or
the Python environment. Any other open — e.g. the real ``C:/Users/james/asp-model-exchange`` corpus or the real
``.runtime`` sealed objects — fails immediately and logs the requesting test, path, reader, allowed roots, and any
detected season/sealed identity. Zero real-2025 access becomes demonstrable, not assumed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_DATA_SUFFIXES = {".parquet", ".pq", ".csv", ".feather", ".arrow", ".joblib", ".pkl", ".pickle", ".npy", ".npz"}
_violations: list[dict] = []
_current_nodeid = {"id": "<session>"}
_installed = {"on": False}


def is_active() -> bool:
    return os.getenv("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes")


def _allowed_roots() -> list[Path]:
    # ONLY exact, explicitly-governed roots — NEVER the blanket OS temp tree. The isolated test temp must be
    # declared (ASP_ISOLATED_TEST_TEMP, set by the gate runner to a dir beneath the isolated runtime root).
    from server.sports_cockpit.engine import RUNTIME_ROOT
    roots = [Path(RUNTIME_ROOT).resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    test_temp = os.environ.get("ASP_ISOLATED_TEST_TEMP", "").strip()
    if test_temp:
        try:
            roots.append(Path(test_temp).resolve())
        except OSError:
            pass
    return [r for r in roots if r]


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

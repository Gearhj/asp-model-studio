"""Fresh-child bootstrap for one ATLAS hermetic suite.

Python loads the generated external ``sitecustomize.py`` before this file.  The
bootstrap then repeats the pre-import invariant, captures test output beneath
the child root, and emits a structured result without exposing environment
values.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import re
from typing import Sequence

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from scripts.hermetic_test_authority import (
    HERMETIC_MODE,
    HermeticAuthorityError,
    canonical_path,
    inventory_created_files,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def assert_preimport_state() -> None:
    if os.environ.get("ATLAS_HERMETIC_MODE") != HERMETIC_MODE:
        raise HermeticAuthorityError("mode")
    if os.environ.get("ATLAS_HERMETIC_GUARD_PASSED") != "1":
        raise HermeticAuthorityError("sitecustomize")
    imported = [name for name in sys.modules if name == "server" or name.startswith("server.")]
    if imported:
        raise HermeticAuthorityError("atlas-preimport")


def _write_json_exclusive(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _run_python_test(target: Path) -> int:
    import pytest

    return int(
        pytest.main(
            [
                "-q",
                "-p",
                "no:cacheprovider",
                "--disable-warnings",
                str(target),
            ]
        )
    )


def _run_python_probe(target: Path) -> int:
    original = list(sys.argv)
    sys.argv = [str(target)]
    try:
        runpy.run_path(str(target), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = original
    return 0


def _run_node(target: Path, log_path: Path) -> int:
    # Execute the node:test file directly so the hermetic child remains the
    # only Node process; Node's --test coordinator would spawn another worker.
    command = ["node", str(target)]
    completed = subprocess.run(
        command,
        cwd=target.parents[1],
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=180,
    )
    log_path.write_text(completed.stdout or "", encoding="utf-8", newline="\n")
    return int(completed.returncode)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--kind", choices=("python-test", "python-probe", "node-test"), required=True)
    parser.add_argument("--simulate-unsafe-preimport", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = canonical_path(os.environ.get("ATLAS_HERMETIC_ROOT", ""))
    source = canonical_path(os.environ.get("ATLAS_HERMETIC_SOURCE_ROOT", ""))
    target = canonical_path(args.target)
    if source not in target.parents:
        raise HermeticAuthorityError("target-outside-source")
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    log_path = reports / "suite-output.txt"
    result_path = reports / "child-result.json"
    started_at = now_iso()
    started = time.perf_counter()
    import_occurred = False
    failure_category = None
    failure_detail = None
    exit_code = 1
    try:
        if args.simulate_unsafe_preimport:
            import types

            sys.modules["server.unsafe_preimport_probe"] = types.ModuleType(
                "server.unsafe_preimport_probe"
            )
        assert_preimport_state()
        if args.kind == "node-test":
            exit_code = _run_node(target, log_path)
        else:
            with log_path.open("x", encoding="utf-8", newline="\n") as log:
                with redirect_stdout(log), redirect_stderr(log):
                    import_occurred = True
                    if args.kind == "python-probe":
                        exit_code = _run_python_probe(target)
                    else:
                        exit_code = _run_python_test(target)
    except HermeticAuthorityError as exc:
        failure_category = exc.category
        exit_code = 87
    except BaseException as exc:  # preserve safe type only; full traceback stays out of output
        failure_category = type(exc).__name__
        if isinstance(exc, FileNotFoundError) and exc.filename:
            missing = Path(exc.filename).expanduser().resolve(strict=False)
            if missing == root or root in missing.parents:
                failure_detail = missing.relative_to(root).as_posix()
            else:
                failure_detail = "outside-hermetic-root"
        elif str(exc):
            detail = str(exc).splitlines()[0]
            detail = detail.replace(str(root), "<hermetic-root>")
            detail = detail.replace(str(source), "<source-root>")
            detail = re.sub(r"[A-Za-z]:\\[^\s,;]+", "<path>", detail)
            failure_detail = detail[:240]
        exit_code = 1
    finished_at = now_iso()
    created_files = inventory_created_files(root)["created_file_count"]
    payload = {
        "schema_version": 1,
        "run_id": os.environ.get("ATLAS_RUN_ID", "missing"),
        "suite_name": os.environ.get("ATLAS_TEST_NAME", "missing"),
        "child_id": os.environ.get("ATLAS_CHILD_ID", "missing"),
        "mode": os.environ.get("ATLAS_HERMETIC_MODE", "missing"),
        "pid": os.getpid(),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(time.perf_counter() - started, 6),
        "exit_code": exit_code,
        "test_result": "passed" if exit_code == 0 else "failed",
        "import_occurred": import_occurred,
        "failure_category": failure_category,
        "failure_detail": failure_detail,
        "created_file_count": created_files,
        "authority_manifest": "authority-manifest.json",
        "suite_output": "reports/suite-output.txt" if log_path.exists() else None,
    }
    _write_json_exclusive(result_path, payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

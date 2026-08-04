"""ATLAS hermetic regression launcher.

The parent is pure stdlib and does not import application modules.  Each suite
gets a unique external authority set and source mirror.  Evidence is preserved;
the launcher never removes a run or child root.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import sqlite3
from typing import Sequence

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from scripts.hermetic_test_authority import (
    ChildAuthority,
    HERMETIC_MODE,
    ISOLATED_MIGRATION_FIXTURES,
    REPO_ROOT,
    build_child_environment,
    create_child_authority,
    create_run_authority,
    inventory_created_files,
    prepare_child,
    validate_children_disjoint,
)


@dataclass(frozen=True)
class SuiteSpec:
    name: str
    target: str
    kind: str
    isolated_migrations: tuple[str, ...] = ()


def _python_executable() -> str:
    candidates = (
        REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        REPO_ROOT / ".venv" / "bin" / "python",
    )
    return str(next((path for path in candidates if path.is_file()), Path(sys.executable)))


def _kind_for(target: str) -> str:
    path = Path(target)
    suffix = path.suffix.casefold()
    if suffix == ".mjs":
        return "node-test"
    if path.name.endswith("_probe.py") or (
        suffix == ".py" and path.parts and path.parts[0].casefold() == "scripts"
    ):
        return "python-probe"
    return "python-test"


def _load_manifest(path: Path) -> list[SuiteSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("suites", payload) if isinstance(payload, dict) else payload
    specs: list[SuiteSpec] = []
    for entry in entries:
        target = str(entry["target"])
        isolated_migrations = tuple(
            str(item) for item in entry.get("isolatedMigrations", [])
        )
        unsupported = set(isolated_migrations).difference(
            ISOLATED_MIGRATION_FIXTURES
        )
        if unsupported:
            raise ValueError("Unsupported isolated migration fixture requested.")
        specs.append(
            SuiteSpec(
                name=str(entry.get("name") or Path(target).stem),
                target=target,
                kind=str(entry.get("kind") or _kind_for(target)),
                isolated_migrations=isolated_migrations,
            )
        )
    return specs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=HERMETIC_MODE)
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--manifest")
    parser.add_argument("--temp-parent")
    parser.add_argument("--concurrent", action="store_true")
    return parser.parse_args(argv)


def _exclusive_json(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _run_child(spec: SuiteSpec, child: ChildAuthority) -> dict[str, object]:
    prepare_child(child, isolated_migrations=spec.isolated_migrations)
    target = child.source_root / spec.target
    if not target.is_file():
        return {
            "run_id": child.run_id,
            "suite_name": spec.name,
            "exit_code": 88,
            "test_result": "failed",
            "failure_category": "target-missing",
            "pid": None,
            **inventory_created_files(child),
        }
    environment = build_child_environment(child)
    bootstrap = child.source_root / "scripts" / "hermetic_test_bootstrap.py"
    command = [
        _python_executable(),
        str(bootstrap),
        "--target",
        str(target),
        "--kind",
        spec.kind,
    ]
    completed = subprocess.run(
        command,
        cwd=child.source_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=600,
    )
    reports = child.root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "bootstrap-stdout.txt").write_text(
        completed.stdout or "", encoding="utf-8", newline="\n"
    )
    (reports / "bootstrap-stderr.txt").write_text(
        completed.stderr or "", encoding="utf-8", newline="\n"
    )
    result_path = reports / "child-result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {
            "run_id": child.run_id,
            "suite_name": spec.name,
            "exit_code": completed.returncode,
            "test_result": "failed",
            "failure_category": "bootstrap-no-result",
            "pid": None,
        }
    result.update(inventory_created_files(child))
    result["child_root"] = str(child.root)
    result["target"] = spec.target
    result["isolated_migrations"] = list(spec.isolated_migrations)
    result["launcher_exit_code"] = completed.returncode
    return result


def _verify_cross_child_isolation(
    run_id: str,
    results: list[dict[str, object]],
) -> dict[str, object]:
    probes = [
        result
        for result in results
        if result.get("target") == "tests/hermetic_import_cache_probe.py"
        and result.get("exit_code") == 0
    ]
    if len(probes) < 2:
        return {"status": "not-run", "child_count": len(probes)}
    counts: list[int] = []
    for result in probes:
        database = Path(str(result["child_root"])) / "authorities" / "security" / "atlas_security.db"
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE user_id LIKE ?",
                (f"{run_id}-%-user",),
            ).fetchone()[0]
        counts.append(int(count))
    return {
        "status": "passed" if all(count == 1 for count in counts) else "failed",
        "child_count": len(probes),
        "each_child_fixture_count": counts,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode != HERMETIC_MODE:
        print("HERMETIC_LAUNCH_REJECTED:live-acceptance-mode-not-implemented", file=sys.stderr)
        return 64
    specs: list[SuiteSpec] = []
    if args.manifest:
        specs.extend(_load_manifest(Path(args.manifest).resolve()))
    specs.extend(
        SuiteSpec(Path(target).stem, target, _kind_for(target))
        for target in args.suite
    )
    if not specs:
        print("HERMETIC_LAUNCH_REJECTED:no-suite", file=sys.stderr)
        return 64
    run = create_run_authority(args.temp_parent)
    children = [create_child_authority(run, spec.name) for spec in specs]
    validate_children_disjoint(children)
    started = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, object]] = []
    if args.concurrent and len(specs) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(specs))) as executor:
            futures = {
                executor.submit(_run_child, spec, child): (spec, child)
                for spec, child in zip(specs, children)
            }
            for future in as_completed(futures):
                results.append(future.result())
    else:
        for spec, child in zip(specs, children):
            results.append(_run_child(spec, child))
    results.sort(key=lambda item: str(item.get("suite_name")))
    cross_child = _verify_cross_child_isolation(run.run_id, results)
    if cross_child["status"] == "failed":
        results.append(
            {
                "run_id": run.run_id,
                "suite_name": "cross-child-isolation",
                "exit_code": 89,
                "test_result": "failed",
                "failure_category": "cross-child-record-visibility",
            }
        )
    summary = {
        "schema_version": 1,
        "mode": HERMETIC_MODE,
        "run_id": run.run_id,
        "run_root": str(run.root),
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "suite_count": len(results),
        "passed": sum(item.get("exit_code") == 0 for item in results),
        "failed": sum(item.get("exit_code") != 0 for item in results),
        "evidence_preserved": True,
        "cross_child_isolation": cross_child,
        "children": results,
    }
    _exclusive_json(run.root / "run-summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

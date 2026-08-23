from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
GOVERNANCE = REPO / "scripts" / "phase7d5a_skip_governance.py"


def assert_external_temp(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO)
    except ValueError:
        return resolved
    raise AssertionError(f"red-gate mutable path is inside the repository: {resolved}")


def make_junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        raise AssertionError("Phase 7D.5A.3 R6 requires Windows real-junction execution")
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    from server.sports_cockpit.path_containment import is_reparse_point

    assert is_reparse_point(link), f"mklink succeeded but {link} is not a reparse point"


def remove_junction(link: Path) -> None:
    if not link.exists() and not link.is_symlink():
        return
    result = subprocess.run(
        ["cmd", "/c", "rmdir", str(link)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@contextmanager
def redirected_state(authority_module, state_root: Path):
    old = authority_module.STATE_ROOT
    authority_module.STATE_ROOT = state_root
    try:
        yield
    finally:
        authority_module.STATE_ROOT = old


def collection_digest(nodes: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(nodes)).encode("utf-8")).hexdigest()


def junit_xml(cases: list[tuple[str, str, str]]) -> str:
    chunks: list[str] = []
    for nodeid, status, reason in cases:
        file_name, test_name = nodeid.split("::", 1)
        inner = ""
        if status == "skipped":
            escaped = (
                reason.replace("&", "&amp;")
                .replace('"', "&quot;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            inner = f'<skipped message="{escaped}"/>'
        elif status == "failed":
            inner = "<failure/>"
        elif status == "error":
            inner = "<error/>"
        chunks.append(f'<testcase file="{file_name}" name="{test_name}">{inner}</testcase>')
    return '<?xml version="1.0"?><testsuites><testsuite name="red-gate">' + "".join(chunks) + "</testsuite></testsuites>"


def run_governance(
    root: Path,
    *,
    collected: list[str],
    junit_cases: list[tuple[str, str, str]],
    policy: dict,
    selection: str = "tests/sports_*_test.py",
) -> subprocess.CompletedProcess[str]:
    assert_external_temp(root)
    root.mkdir(parents=True, exist_ok=True)
    collected_path = root / "collected.txt"
    junit_path = root / "junit.xml"
    policy_path = root / "policy.json"
    out_path = root / "manifest.json"
    collected_path.write_text("\n".join(collected), encoding="utf-8")
    junit_path.write_text(junit_xml(junit_cases), encoding="utf-8")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(GOVERNANCE),
            "--collected",
            str(collected_path),
            "--junit",
            str(junit_path),
            "--out",
            str(out_path),
            "--policy",
            str(policy_path),
            "--selection",
            selection,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )


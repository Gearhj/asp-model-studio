"""Canonical ATLAS security release gate.

Behavioral suites are reported separately from structural source checks.
Required files must be present and wired, and skipped required tests fail the
gate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "tests" / "security_test_inventory.json"


def python_executable() -> str:
    configured = os.getenv("ATLAS_PYTHON")
    if configured:
        return configured
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]
    return str(next((candidate for candidate in candidates if candidate.exists()), Path(sys.executable)))


def load_inventory() -> dict:
    with INVENTORY_PATH.open(encoding="utf-8") as handle:
        inventory = json.load(handle)
    wired = {
        entry["path"]
        for category in ("behavioral", "structural")
        for entry in inventory.get(category, [])
    }
    missing = [path for path in inventory.get("requiredFiles", []) if not (ROOT / path).is_file()]
    unwired = [path for path in inventory.get("requiredFiles", []) if path not in wired]
    if missing or unwired:
        if missing:
            print("Missing required security tests:", ", ".join(missing), file=sys.stderr)
        if unwired:
            print("Unwired required security tests:", ", ".join(unwired), file=sys.stderr)
        raise SystemExit(2)
    return inventory


def run_entry(kind: str, entry: dict) -> None:
    path = entry["path"]
    runner = entry.get("runner", "python")
    command = [python_executable(), path] if runner == "python" else [runner, path]
    print(f"\n[{kind}] {path}: {entry['description']}", flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    print(result.stdout, end="")
    if re.search(r"\bskipped(?:\s*=|\s+\()", result.stdout, flags=re.IGNORECASE):
        print(f"Required security suite reported skipped tests: {path}", file=sys.stderr)
        raise SystemExit(3)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    inventory = load_inventory()
    behavioral = inventory["behavioral"]
    structural = inventory["structural"]
    print(
        f"ATLAS security inventory: {len(behavioral)} behavioral suites, "
        f"{len(structural)} structural suite."
    )
    for entry in behavioral:
        run_entry("behavioral", entry)
    for entry in structural:
        run_entry("structural security check", entry)
    print(
        f"\nATLAS security gate passed: {len(behavioral)} behavioral suites and "
        f"{len(structural)} structural suite."
    )


if __name__ == "__main__":
    main()

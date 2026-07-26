"""Governed Python analytical environment inventory (PYENV-001).

Reports what is *actually* installed in the sandbox interpreter. Package
presence and versions come from `importlib.metadata` against the real
environment -- nothing is claimed from a hard-coded list. Packages ATLAS expects
but cannot find are reported explicitly as `not_installed` rather than omitted,
so the UI can distinguish "absent" from "unknown".

No filesystem paths, environment variables, or secrets are returned.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import platform
import sys
from typing import Any, Dict, List

#: Analytical packages ATLAS expects, grouped for the UI. Presence is always
#: verified against the live environment -- this list only defines expectations.
EXPECTED_PACKAGES: Dict[str, List[str]] = {
    "core": ["pandas", "numpy", "scipy", "pyarrow", "polars", "duckdb"],
    "machine_learning": [
        "scikit-learn", "xgboost", "lightgbm", "catboost", "imbalanced-learn",
        "statsmodels", "interpret", "shap", "joblib",
    ],
    "visualization": ["matplotlib", "plotly", "altair"],
    "utilities": ["openpyxl", "sqlalchemy", "optuna", "category-encoders", "feature-engine"],
}

#: Approval status vocabulary. Everything present in the governed base image is
#: "approved"; anything discovered but not expected is "present_unreviewed".
APPROVED = "approved"
PRESENT_UNREVIEWED = "present_unreviewed"
NOT_INSTALLED = "not_installed"


def _resolved_version(name: str) -> str | None:
    """Authoritative version for one distribution.

    `metadata.version()` performs the same resolution an import would, which
    matters because an environment can contain stale leftover `.dist-info`
    directories for a package that has since been upgraded. Scanning
    `distributions()` alone can report the superseded copy.
    """
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - malformed metadata must not break the inventory
        return None


def _installed_distributions() -> Dict[str, str]:
    """Maps normalized distribution name -> version for the running interpreter.

    Discovery uses `distributions()`, but each version is re-resolved through
    `metadata.version()` so a stale duplicate dist-info cannot be reported.
    """
    found: Dict[str, str] = {}
    for distribution in metadata.distributions():
        try:
            name = distribution.metadata["Name"]
        except Exception:  # noqa: BLE001 - a malformed dist must not break the inventory
            continue
        if not name:
            continue
        found[_normalize(name)] = _resolved_version(name) or distribution.version or "unknown"
    return found


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def environment_id(python_version: str, packages: List[Dict[str, Any]]) -> str:
    """Deterministic identity for this exact environment composition.

    Two interpreters with the same Python version and the same installed
    package set produce the same id, so an environment can be referenced and
    compared without exposing any path.
    """
    payload = python_version + "|" + ",".join(
        f"{item['name']}=={item['version']}" for item in sorted(packages, key=lambda row: row["name"])
        if item["status"] != NOT_INSTALLED
    )
    return "env-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_environment_inventory() -> Dict[str, Any]:
    installed = _installed_distributions()
    expected_flat = {_normalize(name): category for category, names in EXPECTED_PACKAGES.items() for name in names}

    packages: List[Dict[str, Any]] = []

    # Expected analytical packages, reported present or explicitly absent.
    for category, names in EXPECTED_PACKAGES.items():
        for name in names:
            key = _normalize(name)
            version = installed.get(key)
            packages.append({
                "name": name,
                "version": version or "",
                "installed": version is not None,
                "status": APPROVED if version else NOT_INSTALLED,
                "category": category,
            })

    # Anything else actually present is reported too, but not claimed as reviewed.
    for key, version in sorted(installed.items()):
        if key in expected_flat:
            continue
        packages.append({
            "name": key,
            "version": version,
            "installed": True,
            "status": PRESENT_UNREVIEWED,
            "category": "other",
        })

    python_version = platform.python_version()
    installed_count = sum(1 for item in packages if item["installed"])
    return {
        "ok": True,
        "environmentId": environment_id(python_version, packages),
        "pythonVersion": python_version,
        "pythonImplementation": platform.python_implementation(),
        "runtimeType": "project_virtualenv",
        # Interpreter identity without leaking its filesystem location.
        "interpreterFingerprint": hashlib.sha256(sys.executable.encode("utf-8")).hexdigest()[:16],
        "packageCount": len(packages),
        "installedCount": installed_count,
        "missingExpectedCount": sum(1 for item in packages if item["status"] == NOT_INSTALLED),
        "packages": packages,
        "categories": list(EXPECTED_PACKAGES.keys()) + ["other"],
        "installationPolicy": (
            "Packages are installed only by an administrator through a reviewed Package Request. "
            "User code cannot install packages, and ordinary execution has no network access."
        ),
    }

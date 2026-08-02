from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


def _root() -> Path:
    configured = os.getenv("ATLAS_FEATURE_MANIFEST_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "artifacts" / "feature_manifests"


def _segment(value: Any) -> str:
    cleaned = _SAFE_SEGMENT.sub("_", str(value or "").strip())
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("Feature Manifest persistence requires a safe canonical identity.")
    return cleaned[:180]


def _identity_dir(identity: dict[str, Any]) -> Path:
    return (
        _root()
        / _segment(identity.get("project_id"))
        / _segment(identity.get("dataset_id"))
        / _segment(identity.get("dataset_version_id"))
    )


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_manifest_version(
    identity: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Persist one exact manifest version and its mutable execution state.

    The version record is append-only: an existing hash must contain the same
    governed definition payload. Runtime stages (preview/materialization/
    confirmation) are stored in ``current.json`` so they can advance without
    rewriting the immutable feature contract.
    """

    manifest_hash = _segment(
        manifest.get("manifest_hash") or manifest.get("manifest_version")
    )
    identity_dir = _identity_dir(identity)
    versions_dir = identity_dir / "versions"
    version_path = versions_dir / f"{manifest_hash}.json"
    feature_keys = (
        "feature_id",
        "feature_name",
        "display_name",
        "origin",
        "source_features",
        "transformation_type",
        "formula_or_rule",
        "output_datatype",
        "config",
        "selected",
        "exclusion_reason",
        "user_rationale",
    )
    pipeline_keys = (
        "step_id",
        "transformation_type",
        "selected_features",
        "config",
        "enabled",
        "fit_scope",
    )
    definition = {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": str(identity["dataset_version_id"]),
        "manifest_hash": manifest_hash,
        "features": [
            {key: row.get(key) for key in feature_keys}
            for row in manifest.get("features") or []
        ],
        "pipeline_steps": [
            {key: row.get(key) for key in pipeline_keys}
            for row in manifest.get("pipeline_steps") or []
        ],
    }
    definition_checksum = hashlib.sha256(
        _stable_json(definition).encode("utf-8")
    ).hexdigest()
    version_record = {
        **definition,
        "definition_checksum": definition_checksum,
        "persisted_at": datetime.now(timezone.utc).isoformat(),
    }
    if version_path.exists():
        existing = json.loads(version_path.read_text(encoding="utf-8"))
        if existing.get("definition_checksum") != definition_checksum:
            raise ValueError(
                "The persisted Feature Manifest version conflicts with the current governed definition."
            )
    else:
        _atomic_write(version_path, version_record)

    state_manifest = deepcopy(manifest)
    state_manifest["persistence_status"] = "persisted"
    state_manifest["definition_checksum"] = definition_checksum
    state_record = {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": str(identity["dataset_version_id"]),
        "manifest_hash": manifest_hash,
        "definition_checksum": definition_checksum,
        "manifest": state_manifest,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write(identity_dir / "current.json", state_record)
    return {
        "manifest_hash": manifest_hash,
        "definition_checksum": definition_checksum,
        "version_path": str(version_path),
        "current_path": str(identity_dir / "current.json"),
    }


def load_current_manifest(identity: dict[str, Any]) -> dict[str, Any] | None:
    path = _identity_dir(identity) / "current.json"
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if any(
        str(record.get(key) or "") != str(identity.get(key) or "")
        for key in ("project_id", "dataset_id", "dataset_version_id")
    ):
        return None
    manifest = record.get("manifest")
    if not isinstance(manifest, dict):
        return None
    manifest_hash = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    )
    if not manifest_hash or manifest_hash != str(record.get("manifest_hash") or ""):
        return None
    manifest["persistence_status"] = "persisted"
    manifest["definition_checksum"] = str(record.get("definition_checksum") or "")
    return manifest

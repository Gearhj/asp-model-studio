"""ATLAS Durable Model Registry -- governed artifact storage for serialized
model objects.

No model-serialization mechanism existed anywhere in this codebase before
this phase (confirmed by inventory: GET /model/export deliberately refuses to
export the executable object, only a JSON manifest). joblib is already a
transitive dependency (scikit-learn requires it) and already pinned in
requirements.txt, so it is used here rather than introducing pickle/onnx/skops
as a new format -- "do not force a new serialization format if one already
exists" and joblib is the closest thing to an existing, idiomatic choice for
these exact object types (fitted sklearn/xgboost estimators and Pipelines).

Mirrors server/scoring_runs/scoring_run_artifacts.py's discipline: one
artifact per model version, written once, never mutated (immutable per Phase
B's domain model requirement).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import joblib

ARTIFACT_ROOT = Path(
    os.getenv("ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT")
    or (Path(__file__).resolve().parent.parent / "artifacts" / "model_registry")
).resolve()


def _within_artifact_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return ARTIFACT_ROOT in resolved.parents or resolved == ARTIFACT_ROOT
    except (OSError, RuntimeError):
        return False


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_model_artifact(model_version_id: str, fitted_object: Any) -> dict:
    """Serializes `fitted_object` (a fitted sklearn/xgboost estimator, Pipeline,
    or the RFE-style dict wrapper already used elsewhere in this codebase) via
    joblib to a governed, per-version, write-once file. Returns the relative
    path (for storage in model_versions.artifact_reference), a sha256
    checksum, and size."""
    version_dir = (ARTIFACT_ROOT / model_version_id).resolve()
    if not _within_artifact_root(version_dir):
        raise ValueError("Resolved model artifact path escapes the governed artifact root.")
    version_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = version_dir / "model.joblib"
    joblib.dump(fitted_object, artifact_path, compress=3)
    checksum = _sha256_of_file(artifact_path)
    return {
        "path": str(artifact_path.relative_to(ARTIFACT_ROOT)),
        "absolutePath": artifact_path,
        "checksum": checksum,
        "sizeBytes": artifact_path.stat().st_size,
        "format": "joblib",
    }


def resolve_model_artifact_path(relative_path: str) -> Path:
    candidate = (ARTIFACT_ROOT / relative_path).resolve()
    if not _within_artifact_root(candidate) or not candidate.exists():
        raise ValueError("Model artifact is unavailable or outside the governed artifact root.")
    return candidate


def load_model_artifact(relative_path: str) -> Any:
    """Loads a previously-written, immutable artifact back into a Python
    object -- used by the scoring fallback path (a fresh process, after
    restart, whose in-memory RESULTS.final_model is None) and by any future
    Monitoring/Deployment consumer that needs the actual fitted object."""
    path = resolve_model_artifact_path(relative_path)
    return joblib.load(path)


def delete_model_artifact(model_version_id: str) -> bool:
    """Used only by test cleanup / explicit retention-policy purges -- never
    called from the normal archive lifecycle (archival, not deletion, is the
    default -- see ModelVersionRepository.archive)."""
    version_dir = (ARTIFACT_ROOT / model_version_id).resolve()
    if not _within_artifact_root(version_dir) or not version_dir.exists():
        return False
    for child in version_dir.glob("*"):
        child.unlink()
    version_dir.rmdir()
    return True

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
import time
from typing import Any
import uuid

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


def _artifact_path(model_version_id: str) -> Path:
    normalized = str(model_version_id or "").strip()
    if not normalized or any(value in normalized for value in ("/", "\\", "..")):
        raise ValueError("A valid exact model_version_id is required for artifact storage.")
    candidate = (ARTIFACT_ROOT / normalized / "model.joblib").resolve()
    if not _within_artifact_root(candidate):
        raise ValueError("Resolved model artifact path escapes the governed artifact root.")
    return candidate


def stage_model_artifact(model_version_id: str, fitted_object: Any) -> dict[str, Any]:
    """Serialize into an unpublished staging file and prove it can be loaded.

    Nothing under the immutable per-version path is created until verification
    succeeds.  The caller must either finalize or discard the returned staging
    record.
    """
    final_path = _artifact_path(model_version_id)
    staging_dir = (ARTIFACT_ROOT / ".staging").resolve()
    if not _within_artifact_root(staging_dir):
        raise ValueError("Resolved staging path escapes the governed artifact root.")
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = (
        staging_dir
        / f"{model_version_id}-{uuid.uuid4().hex}.joblib.part"
    ).resolve()
    if not _within_artifact_root(staging_path):
        raise ValueError("Resolved staging artifact path escapes the governed artifact root.")
    try:
        joblib.dump(fitted_object, staging_path, compress=3)
        # Windows requires a writable descriptor for FlushFileBuffers, which
        # backs Python's os.fsync implementation there.
        with open(staging_path, "rb+") as handle:
            os.fsync(handle.fileno())
        # A successful dump is insufficient: verify deserialization before the
        # artifact is eligible for durable registry publication.
        joblib.load(staging_path)
        checksum = _sha256_of_file(staging_path)
        size_bytes = staging_path.stat().st_size
        if not checksum or size_bytes <= 0:
            raise ValueError("The staged model artifact is empty or has no checksum.")
        return {
            "modelVersionId": model_version_id,
            "stagingPath": staging_path,
            "finalPath": final_path,
            "checksum": checksum,
            "sizeBytes": size_bytes,
            "format": "joblib",
        }
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise


def discard_staged_model_artifact(staged: dict[str, Any] | None) -> None:
    if not staged:
        return
    candidate = Path(staged.get("stagingPath") or "").resolve()
    staging_root = (ARTIFACT_ROOT / ".staging").resolve()
    if _within_artifact_root(candidate) and staging_root in candidate.parents:
        candidate.unlink(missing_ok=True)


def finalize_staged_model_artifact(staged: dict[str, Any]) -> dict[str, Any]:
    """Atomically move a verified staging file into its immutable version path."""
    staging_path = Path(staged.get("stagingPath") or "").resolve()
    final_path = Path(staged.get("finalPath") or "").resolve()
    model_version_id = str(staged.get("modelVersionId") or "")
    expected_final = _artifact_path(model_version_id)
    staging_root = (ARTIFACT_ROOT / ".staging").resolve()
    if (
        not staging_path.exists()
        or not _within_artifact_root(staging_path)
        or staging_root not in staging_path.parents
        or final_path != expected_final
    ):
        raise ValueError("The staged artifact cannot be finalized safely.")
    if _sha256_of_file(staging_path) != str(staged.get("checksum") or ""):
        raise ValueError("The staged artifact checksum changed before finalization.")
    version_dir = final_path.parent
    try:
        version_dir.mkdir(parents=True, exist_ok=False)
        if final_path.exists():
            raise FileExistsError("The immutable model-version artifact already exists.")
        os.replace(staging_path, final_path)
        checksum = _sha256_of_file(final_path)
        if checksum != str(staged.get("checksum") or ""):
            raise ValueError("The finalized artifact checksum does not match staging.")
        return {
            "path": str(final_path.relative_to(ARTIFACT_ROOT)),
            "absolutePath": final_path,
            "checksum": checksum,
            "sizeBytes": final_path.stat().st_size,
            "format": str(staged.get("format") or "joblib"),
        }
    except Exception:
        if final_path.exists():
            final_path.unlink(missing_ok=True)
        try:
            version_dir.rmdir()
        except OSError:
            pass
        raise


def write_model_artifact(model_version_id: str, fitted_object: Any) -> dict:
    """Serializes `fitted_object` (a fitted sklearn/xgboost estimator, Pipeline,
    or the RFE-style dict wrapper already used elsewhere in this codebase) via
    joblib to a governed, per-version, write-once file. Returns the relative
    path (for storage in model_versions.artifact_reference), a sha256
    checksum, and size."""
    staged = stage_model_artifact(model_version_id, fitted_object)
    try:
        return finalize_staged_model_artifact(staged)
    except Exception:
        discard_staged_model_artifact(staged)
        raise


def resolve_model_artifact_path(relative_path: str) -> Path:
    supplied = Path(str(relative_path or ""))
    if supplied.is_absolute():
        raise ValueError("Model artifact references must be relative to the governed root.")
    candidate = (ARTIFACT_ROOT / supplied).resolve()
    if not _within_artifact_root(candidate) or not candidate.exists():
        raise ValueError("Model artifact is unavailable or outside the governed artifact root.")
    return candidate


def verify_model_artifact(
    relative_path: str,
    *,
    expected_checksum: str,
    expected_model_version_id: str,
    deserialize: bool = False,
) -> dict[str, Any]:
    path = resolve_model_artifact_path(relative_path)
    expected_path = _artifact_path(expected_model_version_id)
    if path != expected_path:
        raise ValueError("The artifact reference does not belong to the exact model version.")
    actual_checksum = _sha256_of_file(path)
    if not expected_checksum or actual_checksum != expected_checksum:
        raise ValueError("The model artifact checksum does not match the registry record.")
    loaded = joblib.load(path) if deserialize else None
    return {
        "path": str(path.relative_to(ARTIFACT_ROOT)),
        "checksum": actual_checksum,
        "sizeBytes": path.stat().st_size,
        "format": "joblib",
        "object": loaded,
    }


def load_model_artifact(relative_path: str, *, expected_checksum: str) -> Any:
    """Loads a previously-written, immutable artifact back into a Python
    object -- used by the scoring fallback path (a fresh process, after
    restart, whose in-memory RESULTS.final_model is None) and by any future
    Monitoring/Deployment consumer that needs the actual fitted object.

    Security (untrusted-deserialization defense): ``joblib.load`` executes the
    pickle opcodes in the file, so it is only safe on bytes whose integrity has
    been proven against the registry. This helper therefore REQUIRES the exact
    checksum recorded for the model version (``model_versions.checksum``) and
    refuses to deserialize when it does not match the on-disk file. Without this
    guard, any tampering of the governed artifact root (a future model-bundle
    import, a filesystem compromise, or a stale/substituted artifact) would
    become arbitrary code execution the moment the object is loaded. The
    registry's own verification path (``verify_model_artifact``) already enforces
    this; this bare helper must not be a weaker back door."""
    path = resolve_model_artifact_path(relative_path)
    actual_checksum = _sha256_of_file(path)
    if not expected_checksum or actual_checksum != expected_checksum:
        raise ValueError(
            "The model artifact checksum does not match the registry record; "
            "refusing to deserialize a potentially tampered artifact."
        )
    return joblib.load(path)


def delete_model_artifact(model_version_id: str) -> bool:
    """Used only by test cleanup / explicit retention-policy purges -- never
    called from the normal archive lifecycle (archival, not deletion, is the
    default -- see ModelVersionRepository.archive)."""
    version_dir = _artifact_path(model_version_id).parent
    if not _within_artifact_root(version_dir) or not version_dir.exists():
        return False
    for child in version_dir.glob("*"):
        child.unlink()
    version_dir.rmdir()
    return True


def reconcile_artifact_storage(
    known_model_version_ids: set[str],
    *,
    minimum_age_seconds: float = 300.0,
) -> dict[str, int]:
    """Remove abandoned staging files and crash-window orphan artifacts.

    A minimum age protects another in-flight publisher during the narrow
    filesystem-finalized/database-not-yet-committed window. Only ATLAS-style
    `mv-*` directories with no durable row are eligible for reconciliation.
    """
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    now = time.time()
    minimum_age = max(0.0, float(minimum_age_seconds))
    removed_staging = 0
    removed_orphans = 0
    staging_root = (ARTIFACT_ROOT / ".staging").resolve()
    if staging_root.exists() and _within_artifact_root(staging_root):
        for candidate in staging_root.iterdir():
            try:
                if (
                    candidate.is_file()
                    and now - candidate.stat().st_mtime >= minimum_age
                ):
                    candidate.unlink()
                    removed_staging += 1
            except OSError:
                continue
    for candidate in ARTIFACT_ROOT.iterdir():
        try:
            if (
                not candidate.is_dir()
                or candidate.name == ".staging"
                or not candidate.name.startswith("mv-")
                or candidate.name in known_model_version_ids
                or now - candidate.stat().st_mtime < minimum_age
            ):
                continue
            if delete_model_artifact(candidate.name):
                removed_orphans += 1
        except (OSError, ValueError):
            continue
    return {
        "stagingArtifactsRemoved": removed_staging,
        "orphanArtifactsRemoved": removed_orphans,
    }

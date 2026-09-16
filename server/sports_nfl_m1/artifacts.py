"""Immutable external artifact bundles for the NFL M1 research challenger.

Publication is deliberately disconnected from every product/model registry.  A complete
bundle becomes visible only when its staged directory (canonical manifest plus joblib
bytes) is atomically renamed to its manifest content address.  Verification checks both
addresses and the frozen research disposition *before* invoking ``joblib.load``.

Joblib is an executable serialization format.  Consequently this module never loads an
unaddressed path or trusts a checksum declared only by mutable current state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np

from server.sports_cockpit.path_containment import contained_no_reparse
from server.sports_datasets.consumer import canonical_json_bytes

from .contracts import assert_no_market_predictors, research_only_metadata


ARTIFACT_CONTRACT_VERSION = "ASP_NFL_M1_RESEARCH_ARTIFACT_V1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ResearchArtifactError(RuntimeError):
    """A research artifact failed identity, lineage, or disposition verification."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checked_sha256(value: str, *, label: str) -> str:
    normalized = str(value).lower()
    if _SHA256.fullmatch(normalized) is None:
        raise ResearchArtifactError(f"{label} must be a complete lowercase SHA-256")
    return normalized


def _day(value: str | date | datetime | np.datetime64, *, label: str) -> np.datetime64:
    try:
        parsed = np.datetime64(value, "D")
    except (TypeError, ValueError) as exc:
        raise ResearchArtifactError(f"{label} contains an invalid date") from exc
    if np.isnat(parsed):
        raise ResearchArtifactError(f"{label} contains NaT")
    return parsed


def _canonical_mapping(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Normalize a mapping to strict JSON, including common NumPy scalar values."""

    def normalize(item: Any) -> Any:
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, Enum):
            return normalize(item.value)
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        return item

    normalized = normalize(dict(value))
    try:
        return json.loads(canonical_json_bytes(normalized))
    except Exception as exc:
        raise ResearchArtifactError(f"{label} is not strict canonical JSON") from exc


def _recency_name(value: Any) -> str:
    raw = value.value if isinstance(value, Enum) else value
    name = str(raw).strip()
    if not name:
        raise ResearchArtifactError("recency_strategy is required")
    return name


def _training_lineage(
    *,
    row_ids: Sequence[Any],
    outcome_dates: Sequence[str | date | datetime | np.datetime64],
    training_cutoff: str | date | datetime | np.datetime64,
    training_seasons: Sequence[int] | None = None,
) -> dict[str, Any]:
    ids = tuple(str(item) for item in row_ids)
    if not ids or len(ids) != len(outcome_dates):
        raise ResearchArtifactError("training row IDs and outcome dates must be non-empty and aligned")
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ResearchArtifactError("training row IDs must be non-empty and unique")
    days = np.asarray(
        [_day(item, label="training_outcome_dates") for item in outcome_dates],
        dtype="datetime64[D]",
    )
    cutoff = _day(training_cutoff, label="training_cutoff")
    if np.any(days > cutoff):
        raise ResearchArtifactError("training outcome occurs after the declared cutoff")
    if cutoff != days.max():
        raise ResearchArtifactError("training cutoff must equal the latest included outcome date")
    if training_seasons is None:
        # NFL seasons span calendar years. January/February 2026 postseason
        # games belong to the completed 2025 season and are authorized by the
        # task's exact OOT contract; they are not 2026-season outcomes.
        seasons = np.asarray(
            [int(str(day)[:4]) if int(str(day)[5:7]) >= 7 else int(str(day)[:4]) - 1 for day in days],
            dtype=np.int64,
        )
    else:
        seasons = np.asarray(training_seasons, dtype=np.int64)
        if seasons.ndim != 1 or seasons.size != len(ids):
            raise ResearchArtifactError("training seasons must align with training rows")
    if np.any(seasons >= 2026):
        raise ResearchArtifactError("2026-season training outcomes are prohibited")
    row_id_bytes = canonical_json_bytes(list(ids))
    date_strings = [str(item) for item in days]
    return {
        "outcomeStartDate": str(days.min()),
        "outcomeEndDate": str(days.max()),
        "trainingCutoff": str(cutoff),
        "seasonStart": int(seasons.min()),
        "seasonEnd": int(seasons.max()),
        "rowCount": len(ids),
        "rowIdSha256": _sha256_bytes(row_id_bytes),
        "outcomeDateSha256": _sha256_bytes(canonical_json_bytes(date_strings)),
        "contains2026Outcome": False,
        "contains2026SeasonOutcome": False,
    }


def _manifest_body(
    *,
    candidate_id: str,
    artifact_sha256: str,
    artifact_size: int,
    foundation_sha256: str,
    feature_names: Sequence[str],
    recency_strategy: Any,
    hyperparameters: Mapping[str, Any],
    training_lineage: Mapping[str, Any],
    calibration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    candidate = str(candidate_id).strip()
    if not candidate:
        raise ResearchArtifactError("candidate_id is required")
    features = assert_no_market_predictors(feature_names)
    disposition = research_only_metadata(candidate)
    return {
        "artifactContract": ARTIFACT_CONTRACT_VERSION,
        "artifactFormat": "JOBLIB",
        "candidateId": candidate,
        "status": disposition["status"],
        "promotionState": disposition["promotionState"],
        "deploymentEligible": disposition["deploymentEligible"],
        "marketPredictorsUsed": disposition["marketPredictorsUsed"],
        "foundationManifestSha256": _checked_sha256(
            foundation_sha256, label="foundation_sha256"
        ),
        "featureNames": list(features),
        "featureCount": len(features),
        "recencyStrategy": _recency_name(recency_strategy),
        "hyperparameters": _canonical_mapping(hyperparameters, label="hyperparameters"),
        "calibration": None
        if calibration is None
        else _canonical_mapping(calibration, label="calibration"),
        "training": dict(training_lineage),
        "modelArtifact": {
            "relativePath": "model.joblib",
            "sha256": _checked_sha256(artifact_sha256, label="artifact_sha256"),
            "byteCount": int(artifact_size),
        },
    }


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("artifactContract") != ARTIFACT_CONTRACT_VERSION:
        raise ResearchArtifactError("research artifact contract differs")
    if manifest.get("artifactFormat") != "JOBLIB":
        raise ResearchArtifactError("research artifact format differs")
    candidate = str(manifest.get("candidateId") or "")
    expected = research_only_metadata(candidate)
    for key in ("status", "promotionState", "deploymentEligible", "marketPredictorsUsed"):
        if manifest.get(key) != expected[key]:
            raise ResearchArtifactError(f"research-only disposition differs: {key}")
    _checked_sha256(
        str(manifest.get("foundationManifestSha256") or ""),
        label="foundationManifestSha256",
    )
    features = manifest.get("featureNames")
    if not isinstance(features, list):
        raise ResearchArtifactError("ordered feature contract is missing")
    try:
        checked_features = assert_no_market_predictors(features)
    except Exception as exc:
        raise ResearchArtifactError("ordered feature contract is invalid") from exc
    if manifest.get("featureCount") != len(checked_features):
        raise ResearchArtifactError("feature count differs from ordered feature contract")
    if not isinstance(manifest.get("recencyStrategy"), str) or not manifest["recencyStrategy"]:
        raise ResearchArtifactError("recency strategy is missing")
    if not isinstance(manifest.get("hyperparameters"), dict):
        raise ResearchArtifactError("hyperparameter contract is missing")
    training = manifest.get("training")
    if not isinstance(training, dict):
        raise ResearchArtifactError("training lineage is missing")
    try:
        start = _day(training["outcomeStartDate"], label="outcomeStartDate")
        end = _day(training["outcomeEndDate"], label="outcomeEndDate")
        cutoff = _day(training["trainingCutoff"], label="trainingCutoff")
    except KeyError as exc:
        raise ResearchArtifactError("training date lineage is incomplete") from exc
    if start > end or end != cutoff:
        raise ResearchArtifactError("training dates cross the authorized cutoff")
    if (
        not isinstance(training.get("seasonStart"), int)
        or not isinstance(training.get("seasonEnd"), int)
        or training["seasonStart"] > training["seasonEnd"]
        or training["seasonEnd"] >= 2026
    ):
        raise ResearchArtifactError("training season lineage crosses prospective 2026")
    if (
        training.get("contains2026Outcome") is not False
        or training.get("contains2026SeasonOutcome") is not False
    ):
        raise ResearchArtifactError("2026-season training outcome disposition differs")
    if not isinstance(training.get("rowCount"), int) or training["rowCount"] <= 0:
        raise ResearchArtifactError("training row count is invalid")
    for key in ("rowIdSha256", "outcomeDateSha256"):
        _checked_sha256(str(training.get(key) or ""), label=key)
    artifact = manifest.get("modelArtifact")
    if not isinstance(artifact, dict) or artifact.get("relativePath") != "model.joblib":
        raise ResearchArtifactError("model artifact path contract differs")
    _checked_sha256(str(artifact.get("sha256") or ""), label="modelArtifact.sha256")
    if not isinstance(artifact.get("byteCount"), int) or artifact["byteCount"] <= 0:
        raise ResearchArtifactError("model artifact byte count is invalid")


@dataclass(frozen=True)
class ResearchArtifactPublication:
    root: Path
    bundle_path: Path
    manifest_path: Path
    model_path: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    artifact_sha256: str


@dataclass(frozen=True)
class LoadedResearchArtifact:
    model: Any
    publication: ResearchArtifactPublication


def publish_research_artifact(
    root: Path,
    model: Any,
    *,
    candidate_id: str,
    foundation_sha256: str,
    feature_names: Sequence[str],
    recency_strategy: Any,
    hyperparameters: Mapping[str, Any],
    training_cutoff: str | date | datetime | np.datetime64,
    training_row_ids: Sequence[Any],
    training_outcome_dates: Sequence[str | date | datetime | np.datetime64],
    training_seasons: Sequence[int] | None = None,
    calibration: Mapping[str, Any] | None = None,
) -> ResearchArtifactPublication:
    """Atomically publish one immutable external research-only model bundle."""

    root = Path(root).absolute()
    root.mkdir(parents=True, exist_ok=True)
    contained_no_reparse(root, [root])
    lineage = _training_lineage(
        row_ids=training_row_ids,
        outcome_dates=training_outcome_dates,
        training_cutoff=training_cutoff,
        training_seasons=training_seasons,
    )
    objects_root = root / "objects"
    objects_root.mkdir(parents=True, exist_ok=True)
    staging = objects_root / f".tmp-{uuid.uuid4().hex}"
    contained_no_reparse(staging, [root])
    staging.mkdir(parents=False, exist_ok=False)
    model_path = staging / "model.joblib"
    try:
        joblib.dump(model, model_path, compress=3, protocol=5)
        if not model_path.is_file() or model_path.stat().st_size <= 0:
            raise ResearchArtifactError("joblib did not produce one complete artifact file")
        artifact_sha = _sha256_file(model_path)
        manifest = _manifest_body(
            candidate_id=candidate_id,
            artifact_sha256=artifact_sha,
            artifact_size=model_path.stat().st_size,
            foundation_sha256=foundation_sha256,
            feature_names=feature_names,
            recency_strategy=recency_strategy,
            hyperparameters=hyperparameters,
            training_lineage=lineage,
            calibration=calibration,
        )
        _validate_manifest(manifest)
        manifest_bytes = canonical_json_bytes(manifest)
        manifest_sha = _sha256_bytes(manifest_bytes)
        (staging / "manifest.json").write_bytes(manifest_bytes)
        bundle = objects_root / "sha256" / manifest_sha
        contained_no_reparse(bundle, [root])
        bundle.parent.mkdir(parents=True, exist_ok=True)
        if bundle.exists():
            shutil.rmtree(staging)
        else:
            try:
                os.replace(staging, bundle)
            except OSError:
                # A concurrent identical publisher may have won the content address.
                if not bundle.is_dir():
                    raise
                shutil.rmtree(staging)
        return verify_research_artifact(
            root,
            expected_manifest_sha256=manifest_sha,
            expected_artifact_sha256=artifact_sha,
            expected_foundation_sha256=foundation_sha256,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_research_artifact(
    root: Path,
    *,
    expected_manifest_sha256: str,
    expected_artifact_sha256: str,
    expected_foundation_sha256: str,
) -> ResearchArtifactPublication:
    """Verify exact content and lineage without executing serialized bytes."""

    root = Path(root).absolute()
    manifest_sha = _checked_sha256(
        expected_manifest_sha256, label="expected_manifest_sha256"
    )
    artifact_sha = _checked_sha256(
        expected_artifact_sha256, label="expected_artifact_sha256"
    )
    foundation_sha = _checked_sha256(
        expected_foundation_sha256, label="expected_foundation_sha256"
    )
    bundle = root / "objects" / "sha256" / manifest_sha
    contained_no_reparse(bundle, [root])
    manifest_path = bundle / "manifest.json"
    model_path = bundle / "model.joblib"
    contained_no_reparse(manifest_path, [root])
    contained_no_reparse(model_path, [root])
    if not bundle.is_dir() or not manifest_path.is_file() or not model_path.is_file():
        raise ResearchArtifactError("research artifact bundle is incomplete")
    children = {item.name for item in bundle.iterdir()}
    if children != {"manifest.json", "model.joblib"}:
        raise ResearchArtifactError("research artifact bundle contains unexpected entries")
    raw_manifest = manifest_path.read_bytes()
    if _sha256_bytes(raw_manifest) != manifest_sha:
        raise ResearchArtifactError("canonical manifest checksum differs")
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchArtifactError("research artifact manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or canonical_json_bytes(manifest) != raw_manifest:
        raise ResearchArtifactError("research artifact manifest is not exact canonical JSON")
    _validate_manifest(manifest)
    if manifest.get("foundationManifestSha256") != foundation_sha:
        raise ResearchArtifactError("foundation identity differs from expected authority")
    declared_artifact = manifest["modelArtifact"]
    if declared_artifact.get("sha256") != artifact_sha:
        raise ResearchArtifactError("artifact identity differs from expected authority")
    if model_path.stat().st_size != declared_artifact.get("byteCount"):
        raise ResearchArtifactError("artifact byte count differs")
    if _sha256_file(model_path) != artifact_sha:
        raise ResearchArtifactError("artifact checksum differs")
    return ResearchArtifactPublication(
        root=root,
        bundle_path=bundle,
        manifest_path=manifest_path,
        model_path=model_path,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        artifact_sha256=artifact_sha,
    )


def load_verified_research_artifact(
    root: Path,
    *,
    expected_manifest_sha256: str,
    expected_artifact_sha256: str,
    expected_foundation_sha256: str,
) -> LoadedResearchArtifact:
    """Verify the pinned bundle completely, then and only then deserialize it."""

    publication = verify_research_artifact(
        root,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_artifact_sha256=expected_artifact_sha256,
        expected_foundation_sha256=expected_foundation_sha256,
    )
    model = joblib.load(publication.model_path)
    return LoadedResearchArtifact(model=model, publication=publication)


__all__ = [
    "ARTIFACT_CONTRACT_VERSION",
    "LoadedResearchArtifact",
    "ResearchArtifactError",
    "ResearchArtifactPublication",
    "load_verified_research_artifact",
    "publish_research_artifact",
    "verify_research_artifact",
]

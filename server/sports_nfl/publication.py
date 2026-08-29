"""Immutable content-addressed publication primitives for NFL evidence.

The NFL foundation intentionally shares the repository's existing storage
principles without reusing any MLB authority or current pointer.  Every
published Parquet object is addressed by a manifest that binds the complete
file hash, schema, row count, source lineage, and temporal contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from ..sports_cockpit.interprocess_lock import interprocess_lock
from ..sports_cockpit.path_containment import contained_no_reparse
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes


OBJECT_CONTRACT = "ASP_NFL_CONTENT_ADDRESSED_PARQUET_V1"
FOUNDATION_CONTRACT = "ASP_NFL_DATA_FOUNDATION_MANIFEST_V1"
CURRENT_CONTRACT = "ASP_NFL_DATA_FOUNDATION_CURRENT_V1"


class NflPublicationError(RuntimeError):
    """An immutable NFL object or publication relationship is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NflPublicationError(f"invalid JSON authority: {path}") from exc
    if not isinstance(payload, dict):
        raise NflPublicationError(f"JSON authority must be an object: {path}")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(canonical_json_bytes(payload))
    os.replace(temporary, path)


def parquet_evidence(path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(Path(path))
    fields = [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in parquet.schema_arrow
    ]
    return {
        "rowCount": int(parquet.metadata.num_rows),
        "byteCount": int(Path(path).stat().st_size),
        "fileSha256": sha256_file(Path(path)),
        "schema": fields,
        "schemaSha256": sha256_bytes(canonical_json_bytes(fields)),
    }


def publish_parquet_object(
    root: Path,
    source_path: Path,
    *,
    layer: str,
    table_name: str,
    source_lineage: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    coverage: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish a complete Parquet file without loading its rows into memory."""

    root = Path(root).resolve()
    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise NflPublicationError(f"publication source is missing: {source_path}")
    contained_no_reparse(root, [root])
    evidence = parquet_evidence(source_path)
    body = {
        "manifestContract": OBJECT_CONTRACT,
        "layer": str(layer).upper(),
        "tableName": table_name,
        "objectFile": "object.parquet",
        **evidence,
        "sourceLineage": [dict(item) for item in source_lineage],
        "tableContract": dict(contract),
        "coverage": dict(coverage),
        "quality": dict(quality),
        "governance": {
            "status": "RESEARCH_ONLY",
            "rightsBoundary": "LOCAL_PRIVATE_RESEARCH",
            "modelFitOccurred": False,
            "modelScoringOccurred": False,
            "promotionEligible": False,
        },
    }
    manifest_sha = sha256_bytes(canonical_json_bytes(body))
    manifest = {**body, "manifestSha256": manifest_sha}
    object_dir = root / "objects" / "sha256" / manifest_sha
    contained_no_reparse(object_dir, [root])
    target = object_dir / "object.parquet"
    manifest_path = object_dir / "manifest.json"
    if object_dir.exists():
        verified = verify_parquet_object(root, manifest_sha)
        if canonical_json_bytes(verified["manifest"]) != canonical_json_bytes(manifest):
            raise NflPublicationError(f"content address conflicts for {table_name}")
        return verified

    temporary_dir = root / "objects" / f".tmp-{uuid.uuid4().hex}"
    temporary_dir.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copyfile(source_path, temporary_dir / "object.parquet")
        _atomic_json(temporary_dir / "manifest.json", manifest)
        object_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary_dir, object_dir)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
    return verify_parquet_object(root, manifest_sha)


def verify_parquet_object(root: Path, manifest_sha: str) -> dict[str, Any]:
    root = Path(root).resolve()
    object_dir = (root / "objects" / "sha256" / str(manifest_sha)).resolve()
    contained_no_reparse(object_dir, [root])
    manifest_path = object_dir / "manifest.json"
    parquet_path = object_dir / "object.parquet"
    if not manifest_path.is_file() or not parquet_path.is_file():
        raise NflPublicationError(f"incomplete NFL object: {manifest_sha}")
    manifest = _load_json(manifest_path)
    if manifest.get("manifestContract") != OBJECT_CONTRACT:
        raise NflPublicationError("NFL object contract differs")
    body = {key: value for key, value in manifest.items() if key != "manifestSha256"}
    actual_manifest_sha = sha256_bytes(canonical_json_bytes(body))
    if manifest.get("manifestSha256") != actual_manifest_sha or actual_manifest_sha != manifest_sha:
        raise NflPublicationError("NFL object manifest address differs")
    evidence = parquet_evidence(parquet_path)
    for key in ("rowCount", "byteCount", "fileSha256", "schema", "schemaSha256"):
        if canonical_json_bytes(manifest.get(key)) != canonical_json_bytes(evidence[key]):
            raise NflPublicationError(f"NFL object evidence differs: {key}")
    governance = manifest.get("governance") or {}
    if (
        governance.get("status") != "RESEARCH_ONLY"
        or governance.get("rightsBoundary") != "LOCAL_PRIVATE_RESEARCH"
        or governance.get("modelFitOccurred") is not False
        or governance.get("modelScoringOccurred") is not False
        or governance.get("promotionEligible") is not False
    ):
        raise NflPublicationError("NFL object governance differs")
    return {"manifest": manifest, "manifestPath": manifest_path, "path": parquet_path, **evidence}


def publish_foundation(
    root: Path,
    *,
    dataset_id: str,
    objects: Sequence[Mapping[str, Any]],
    source_manifest: Mapping[str, Any],
    coverage: Mapping[str, Any],
    quality: Mapping[str, Any],
    feature_families: Mapping[str, Sequence[str]],
    limitations: Sequence[Mapping[str, Any]],
    rights: Sequence[Mapping[str, Any]],
    published_at: str,
) -> dict[str, Any]:
    """Publish and atomically select one verified NFL foundation version."""

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    object_refs = sorted(
        [
            {
                "layer": item["manifest"]["layer"],
                "tableName": item["manifest"]["tableName"],
                "manifestSha256": item["manifest"]["manifestSha256"],
                "rowCount": item["manifest"]["rowCount"],
                "fileSha256": item["manifest"]["fileSha256"],
            }
            for item in objects
        ],
        key=lambda value: (value["layer"], value["tableName"]),
    )
    source_sha = str(source_manifest.get("manifestSha256") or source_manifest.get("manifest_sha256") or "")
    if len(source_sha) != 64:
        raise NflPublicationError("source manifest identity is missing")
    body = {
        "manifestContract": FOUNDATION_CONTRACT,
        "datasetId": dataset_id,
        "publishedAt": published_at,
        "sourceManifestSha256": source_sha,
        "objects": object_refs,
        "coverage": dict(coverage),
        "quality": dict(quality),
        "featureFamilies": {name: list(values) for name, values in feature_families.items()},
        "rights": [dict(item) for item in rights],
        "limitations": [dict(item) for item in limitations],
        "governance": {
            "status": "RESEARCH_ONLY",
            "rightsBoundary": "LOCAL_PRIVATE_RESEARCH",
            "workspaceActivationEligible": False,
            "compatibleWorkflowIds": ["nfl-forecasting"],
            "modelFitOccurred": False,
            "modelScoringOccurred": False,
            "promotionEligible": False,
        },
    }
    manifest_sha = sha256_bytes(canonical_json_bytes(body))
    manifest = {
        **body,
        "manifestSha256": manifest_sha,
        "datasetVersionId": f"{dataset_id}:sha256:{manifest_sha}",
    }
    manifest_dir = root / "manifests" / "sha256" / manifest_sha
    manifest_path = manifest_dir / "foundation-manifest.json"
    with interprocess_lock(root / ".foundation.lock", stale_after=12 * 60 * 60):
        if manifest_path.exists():
            existing = _load_json(manifest_path)
            if canonical_json_bytes(existing) != canonical_json_bytes(manifest):
                raise NflPublicationError("existing foundation manifest conflicts")
        else:
            manifest_dir.mkdir(parents=True, exist_ok=False)
            _atomic_json(manifest_path, manifest)
        verified = verify_foundation(root, manifest_sha)
        current = {
            "contract": CURRENT_CONTRACT,
            "datasetId": dataset_id,
            "datasetVersionId": manifest["datasetVersionId"],
            "currentManifestSha256": manifest_sha,
            "relativeManifestPath": f"manifests/sha256/{manifest_sha}/foundation-manifest.json",
            "updatedAt": published_at,
        }
        _atomic_json(root / "current.json", current)
    return verified


def verify_foundation(root: Path, manifest_sha: str | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    if manifest_sha is None:
        current = _load_json(root / "current.json")
        if current.get("contract") != CURRENT_CONTRACT:
            raise NflPublicationError("NFL current pointer contract differs")
        manifest_sha = str(current.get("currentManifestSha256") or "")
    path = (root / "manifests" / "sha256" / manifest_sha / "foundation-manifest.json").resolve()
    contained_no_reparse(path, [root])
    manifest = _load_json(path)
    if manifest.get("manifestContract") != FOUNDATION_CONTRACT:
        raise NflPublicationError("NFL foundation contract differs")
    body = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifestSha256", "datasetVersionId"}
    }
    actual = sha256_bytes(canonical_json_bytes(body))
    if actual != manifest_sha or manifest.get("manifestSha256") != actual:
        raise NflPublicationError("NFL foundation manifest address differs")
    expected_version = f"{manifest['datasetId']}:sha256:{actual}"
    if manifest.get("datasetVersionId") != expected_version:
        raise NflPublicationError("NFL dataset version identity differs")
    verified_objects = []
    for item in manifest.get("objects") or []:
        verified = verify_parquet_object(root, str(item.get("manifestSha256") or ""))
        for key in ("layer", "tableName", "rowCount", "fileSha256", "manifestSha256"):
            if canonical_json_bytes(item.get(key)) != canonical_json_bytes(verified["manifest"].get(key)):
                raise NflPublicationError(f"NFL foundation object relationship differs: {key}")
        verified_objects.append(verified)
    if not verified_objects:
        raise NflPublicationError("NFL foundation contains no objects")
    governance = manifest.get("governance") or {}
    if governance.get("workspaceActivationEligible") is not False or governance.get("modelFitOccurred") is not False:
        raise NflPublicationError("NFL foundation activation/model governance differs")
    return {
        "manifest": manifest,
        "manifestPath": path,
        "objects": verified_objects,
        "datasetVersionId": expected_version,
        "manifestSha256": actual,
    }


__all__ = [
    "CURRENT_CONTRACT",
    "FOUNDATION_CONTRACT",
    "NflPublicationError",
    "OBJECT_CONTRACT",
    "parquet_evidence",
    "publish_foundation",
    "publish_parquet_object",
    "sha256_file",
    "verify_foundation",
    "verify_parquet_object",
]

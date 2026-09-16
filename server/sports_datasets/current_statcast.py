from __future__ import annotations

"""Additive Data Warehouse registration for current Statcast PA evidence.

This adapter deliberately does not change the frozen FD1 consumer.  It accepts one
small, content-addressed manifest whose only physical family is
``plate_appearance`` and writes its metadata to the existing sports dataset
registry tables.  It does not create a research project, a temporal fold, a
population, a model, or a fitted artifact.
"""

import copy
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from ..persistence.db import Database, json_dumps, now_iso
from .constants import PA_CLASS_ORDER
from .consumer import (
    ManifestValidationError,
    canonical_json_bytes,
    load_strict_json,
    parquet_physical_schema as registry_parquet_physical_schema,
    raw_absolute_path,
    reject_reparse_chain,
    sha256_bytes,
    sha256_file,
)


CURRENT_STATCAST_DATASET_ID = "asp.mlb.statcast.current-pa.v1"
CURRENT_STATCAST_MANIFEST_VERSION = "CURRENT_STATCAST_PA_DATASET_MANIFEST_V1"
CURRENT_STATCAST_CANONICALIZATION_VERSION = "SPORTS_CANONICAL_JSON_V1"
CURRENT_STATCAST_FAMILY = "plate_appearance"
CURRENT_STATCAST_MODELING_STATUS = "EVIDENCE_REGISTERED_NO_FIT"
CURRENT_STATCAST_EARLIEST_AUTHORIZED_DATE = date(2023, 3, 30)
CURRENT_STATCAST_LATEST_AUTHORIZED_DATE = date(2026, 12, 31)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_KEYS = {
    "canonicalizationVersion",
    "datasetId",
    "datasetVersionId",
    "dateCoverage",
    "family",
    "league",
    "limitations",
    "manifestId",
    "metadata",
    "partitions",
    "publishedAt",
    "rights",
    "schemaVersion",
    "sport",
}
_DATE_COVERAGE_KEYS = {
    "earliestDate",
    "latestDate",
    "partitionCount",
    "rowCount",
}
_PARTITION_KEYS = {
    "byteCount",
    "family",
    "fileSha256",
    "maximumDate",
    "minimumDate",
    "month",
    "partitionId",
    "physicalSchema",
    "physicalSchemaFingerprint",
    "relativePath",
    "rowCount",
    "schemaId",
    "season",
    "sourceLineage",
    "sourceRightsIds",
    "targetEligibility",
    "temporalClassification",
}
_SOURCE_KEYS = {"sha256", "sourceId"}
_RIGHT_KEYS = {
    "allowedUses",
    "attribution",
    "controls",
    "displayName",
    "metadata",
    "prohibitedUses",
    "rightsControlId",
    "sourceName",
    "status",
}
_LIMITATION_KEYS = {"description", "limitationId", "scope"}
_REQUIRED_METADATA_KEYS = {
    "bronzeManifestSha256",
    "modelFitOccurred",
    "modelPromotionOccurred",
    "normalizationContract",
    "publicationManifestSha256",
    "quarantineStatus",
    "targetClassOrder",
    "targetEventMap",
    "temporalContract",
    "trainingApproval",
}


@dataclass(frozen=True)
class ValidatedCurrentStatcastPackage:
    manifest_path: Path
    package_root: Path
    manifest: dict[str, Any]
    partition_authority_sha: str
    validated_at: str


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise ManifestValidationError(
            "CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID",
            f"{label} keys differ (missing={missing}, extra={extra})",
        )


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"{label} must be an object")
    return value


def _list(value: Any, *, label: str, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "a non-empty list" if nonempty else "a list"
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"{label} must be {qualifier}")
    return value


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"{label} must be non-empty text")
    return value


def _sha(value: Any, *, label: str) -> str:
    text = _text(value, label=label)
    if not _SHA256.fullmatch(text):
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"{label} must be lowercase SHA-256")
    return text


def _date(value: Any, *, label: str) -> date:
    text = _text(value, label=label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"{label} must be an ISO date") from exc
    if parsed.isoformat() != text:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"{label} must be a canonical ISO date")
    return parsed


def _integer(value: Any, *, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"{label} must be an integer >= {minimum}")
    return value


def _relative_file(package_root: Path, spelling: Any, *, label: str) -> tuple[Path, str]:
    text = _text(spelling, label=label)
    posix = PurePosixPath(text)
    if posix.is_absolute() or not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise ManifestValidationError("CURRENT_STATCAST_PATH_INVALID", f"{label} must be a contained POSIX relative path")
    candidate = raw_absolute_path(package_root.joinpath(*posix.parts))
    try:
        candidate.relative_to(package_root)
    except ValueError as exc:
        raise ManifestValidationError("CURRENT_STATCAST_PATH_INVALID", f"{label} escapes the package root") from exc
    reject_reparse_chain(candidate, label="Current Statcast partition")
    if not candidate.is_file():
        raise ManifestValidationError("CURRENT_STATCAST_PARTITION_MISSING", "Declared partition is unavailable", logical_uri=text)
    return candidate, posix.as_posix()


def parquet_physical_schema(path: Path) -> list[dict[str, Any]]:
    """Return the stable Arrow schema representation used by this manifest."""

    schema, _rows = registry_parquet_physical_schema(
        path,
        logical_uri="current-statcast://plate-appearance-partition",
    )
    return schema


def current_statcast_partition_authority_sha(
    partitions: Sequence[Mapping[str, Any]],
) -> str:
    authority = [
        {
            "fileSha256": item["fileSha256"],
            "maximumDate": item["maximumDate"],
            "minimumDate": item["minimumDate"],
            "partitionId": item["partitionId"],
            "rowCount": item["rowCount"],
            "sourceLineage": item["sourceLineage"],
        }
        for item in sorted(partitions, key=lambda row: str(row["partitionId"]))
    ]
    return sha256_bytes(canonical_json_bytes(authority))


def current_statcast_partition_descriptor(
    *,
    package_root: Path,
    relative_path: str,
    partition_id: str,
    source_lineage: Sequence[Mapping[str, str]],
    date_column: str = "gameDate",
    schema_id: str = "CURRENT_STATCAST_PA_SCHEMA_V1",
    source_rights_ids: Sequence[str] = ("MLB_STATCAST",),
    target_eligibility: Sequence[str] = (
        "EVIDENCE_ONLY",
        "QUARANTINED",
        "NOT_APPROVED_FOR_TRAINING",
    ),
    temporal_classification: Sequence[str] = (
        "POINT_IN_TIME_DATE_EXCLUSIVE",
    ),
) -> dict[str, Any]:
    """Describe one explicit contained PA Parquet object from its real bytes."""

    root = raw_absolute_path(Path(package_root))
    path, normalized_relative_path = _relative_file(
        root,
        relative_path,
        label="current Statcast PA relativePath",
    )
    parquet = pq.ParquetFile(path)
    row_count = int(parquet.metadata.num_rows)
    if row_count < 1:
        raise ManifestValidationError(
            "CURRENT_STATCAST_PARTITION_MISSING",
            "Warehouse PA descriptors must contain at least one row",
            logical_uri=normalized_relative_path,
        )
    try:
        raw_dates = pq.read_table(path, columns=[date_column])[date_column].to_pylist()
    except (KeyError, OSError, ValueError) as exc:
        raise ManifestValidationError(
            "CURRENT_STATCAST_PARTITION_SCHEMA_MISMATCH",
            "PA partition must contain gameDate",
            logical_uri=normalized_relative_path,
        ) from exc
    dates = [_date(str(value), label=f"{normalized_relative_path}.gameDate") for value in raw_dates]
    if len(dates) != row_count:
        raise ManifestValidationError(
            "CURRENT_STATCAST_DATE_COVERAGE_INVALID",
            "PA partition gameDate count differs from its row count",
            logical_uri=normalized_relative_path,
        )
    seasons = {value.year for value in dates}
    if len(seasons) != 1:
        raise ManifestValidationError(
            "CURRENT_STATCAST_DATE_COVERAGE_INVALID",
            "One PA partition may not cross a season boundary",
            logical_uri=normalized_relative_path,
        )
    months = {value.month for value in dates}
    physical_schema = parquet_physical_schema(path)
    return {
        "byteCount": path.stat().st_size,
        "family": CURRENT_STATCAST_FAMILY,
        "fileSha256": sha256_file(path, logical_uri=normalized_relative_path),
        "maximumDate": max(dates).isoformat(),
        "minimumDate": min(dates).isoformat(),
        "month": next(iter(months)) if len(months) == 1 else None,
        "partitionId": _text(partition_id, label="partitionId"),
        "physicalSchema": physical_schema,
        "physicalSchemaFingerprint": sha256_bytes(canonical_json_bytes(physical_schema)),
        "relativePath": normalized_relative_path,
        "rowCount": row_count,
        "schemaId": _text(schema_id, label="schemaId"),
        "season": next(iter(seasons)),
        "sourceLineage": copy.deepcopy([dict(item) for item in source_lineage]),
        "sourceRightsIds": list(source_rights_ids),
        "targetEligibility": list(target_eligibility),
        "temporalClassification": list(temporal_classification),
    }


def write_content_addressed_current_statcast_manifest(
    manifest_store: Path,
    payload: Mapping[str, Any],
) -> Path:
    """Write a new immutable manifest envelope without editing an old address."""

    if "manifestSha256" in payload:
        raise ManifestValidationError(
            "CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID",
            "The immutable manifest record must not embed a self-hash",
        )
    store = raw_absolute_path(Path(manifest_store))
    reject_reparse_chain(store, label="Current Statcast manifest store")
    store.mkdir(parents=True, exist_ok=True)
    body = canonical_json_bytes(copy.deepcopy(dict(payload)))
    manifest_sha = sha256_bytes(body)
    destination = store / f"{manifest_sha}.json"
    if destination.exists():
        if destination.read_bytes() != body:
            raise ManifestValidationError(
                "CURRENT_STATCAST_MANIFEST_ADDRESS_CONFLICT",
                "Existing content-addressed manifest bytes differ",
            )
        return destination
    temporary = store / f".{manifest_sha}.tmp-{uuid.uuid4().hex}"
    temporary.write_bytes(body)
    os.replace(temporary, destination)
    return destination


def build_current_statcast_warehouse_manifest(
    output_root: Path,
    publication_manifest_path: Path,
    *,
    extra_partitions: Sequence[Mapping[str, Any]] = (),
    include_current_receipts: bool = True,
    current_silver_root: Path | None = None,
    additional_rights: Sequence[Mapping[str, Any]] = (),
    limitations: Sequence[Mapping[str, Any]] = (),
    sync_health: Mapping[str, Any] | None = None,
    gold_publication: Mapping[str, Any] | None = None,
) -> ValidatedCurrentStatcastPackage:
    """Build the addressed warehouse record from verified current Silver PA receipts.

    ``extra_partitions`` is the explicit integration point for separately verified
    2023/2024 PA evidence. Entries use the same exact partition descriptor schema
    as the resulting manifest and their ``relativePath`` must already be contained
    by ``output_root``. ``current_silver_root`` locates receipt-relative current
    objects when the combined package root is their common parent. Nothing is
    discovered by glob, date inference, or project latest state.
    """

    root = raw_absolute_path(Path(output_root))
    evidence_root = raw_absolute_path(Path(current_silver_root or output_root))
    publication_path = raw_absolute_path(Path(publication_manifest_path))
    reject_reparse_chain(root, label="Current Statcast package root")
    reject_reparse_chain(evidence_root, label="Current Statcast Silver output root")
    reject_reparse_chain(publication_path, label="Current Statcast Silver publication manifest")
    try:
        evidence_root.relative_to(root)
        publication_path.relative_to(root)
    except ValueError as exc:
        raise ManifestValidationError(
            "CURRENT_STATCAST_PATH_INVALID",
            "Current Silver evidence must be contained by the package root",
        ) from exc
    publication_sha = _sha(publication_path.parent.name, label="Current Silver publication address")
    if sha256_file(publication_path, logical_uri="current-statcast-silver://manifest") != publication_sha:
        raise ManifestValidationError(
            "CURRENT_STATCAST_PUBLICATION_HASH_MISMATCH",
            "Current Silver publication manifest differs from its complete-byte address",
        )
    publication = load_strict_json(
        publication_path,
        logical_uri="current-statcast-silver://manifest",
    )
    if (
        publication.get("manifestContract") != "MLB_CURRENT_STATCAST_SILVER_V1"
        or publication.get("datasetId") != CURRENT_STATCAST_DATASET_ID
        or publication.get("status") != "COMPLETE"
        or publication.get("quarantine") != "QUARANTINED"
        or publication.get("selectable") is not False
        or publication.get("modelEligible") is not False
        or publication.get("approvedForTraining") is not False
        or publication.get("modelsFitted") != 0
    ):
        raise ManifestValidationError(
            "CURRENT_STATCAST_PUBLICATION_INVALID",
            "Current Silver publication is not complete quarantined PA evidence",
        )

    source_authorities = _mapping(
        publication.get("sourceAuthorities"),
        label="current Silver sourceAuthorities",
    )
    current_bronze_sha = _sha(
        source_authorities.get("currentBronzeManifestSha256"),
        label="current Silver currentBronzeManifestSha256",
    )
    normalizer_contract = _text(
        publication.get("normalizerContract"),
        label="current Silver normalizerContract",
    )
    partitions: list[dict[str, Any]] = []
    publication_partitions = _list(
        publication.get("partitions"), label="current Silver partitions"
    )
    for index, raw_receipt in enumerate(
        publication_partitions if include_current_receipts else []
    ):
        receipt = _mapping(raw_receipt, label=f"current Silver partitions[{index}]")
        objects = _mapping(receipt.get("objects"), label=f"current Silver partitions[{index}].objects")
        pa_object = _mapping(
            objects.get("plate_appearance"),
            label=f"current Silver partitions[{index}].objects.plate_appearance",
        )
        row_count = _integer(
            pa_object.get("rowCount"),
            label=f"current Silver partitions[{index}].objects.plate_appearance.rowCount",
        )
        is_complete_empty = row_count == 0
        if is_complete_empty:
            if (
                receipt.get("sourceStatus") != "COMPLETE_EMPTY"
                or _integer(
                    receipt.get("sourceRowCount"),
                    label=f"current Silver partitions[{index}].sourceRowCount",
                )
                != 0
                or set(objects) != {"plate_appearance", "pitch", "reject"}
                or any(
                    _integer(
                        _mapping(raw_object, label=f"current Silver partitions[{index}].objects.{family}").get("rowCount"),
                        label=f"current Silver partitions[{index}].objects.{family}.rowCount",
                    )
                    != 0
                    for family, raw_object in objects.items()
                )
            ):
                raise ManifestValidationError(
                    "CURRENT_STATCAST_EMPTY_PARTITION_INVALID",
                    "A zero-row PA object must be backed by an exact COMPLETE_EMPTY Silver receipt",
                )
        relative_path = _text(
            pa_object.get("relativePath"),
            label=f"current Silver partitions[{index}].objects.plate_appearance.relativePath",
        )
        pa_path, _ = _relative_file(
            evidence_root,
            relative_path,
            label=f"current Silver partitions[{index}].objects.plate_appearance.relativePath",
        )
        normalized_relative_path = pa_path.relative_to(root).as_posix()
        object_sha = _sha(
            pa_object.get("sha256"),
            label=f"current Silver partitions[{index}].objects.plate_appearance.sha256",
        )
        if sha256_file(pa_path, logical_uri=normalized_relative_path) != object_sha:
            raise ManifestValidationError(
                "CURRENT_STATCAST_PARTITION_HASH_MISMATCH",
                "Current Silver PA object differs",
                logical_uri=normalized_relative_path,
            )
        if pa_path.stat().st_size != _integer(
            pa_object.get("byteCount"),
            label=f"current Silver partitions[{index}].objects.plate_appearance.byteCount",
            minimum=1,
        ):
            raise ManifestValidationError(
                "CURRENT_STATCAST_PARTITION_SIZE_MISMATCH",
                "Current Silver PA object byte count differs",
                logical_uri=normalized_relative_path,
            )
        partition_date = _date(
            receipt.get("partitionDate"),
            label=f"current Silver partitions[{index}].partitionDate",
        ).isoformat()
        season = _integer(
            receipt.get("season"),
            label=f"current Silver partitions[{index}].season",
            minimum=2000,
        )
        if int(partition_date[:4]) != season:
            raise ManifestValidationError(
                "CURRENT_STATCAST_DATE_COVERAGE_INVALID",
                "Current Silver receipt season differs from its partition date",
            )
        request = _mapping(
            receipt.get("request"),
            label=f"current Silver partitions[{index}].request",
        )
        source_lineage = [
            {
                "sourceId": _text(request.get("sourcePartitionId"), label="request.sourcePartitionId"),
                "sha256": _sha(request.get("sourcePartitionSha256"), label="request.sourcePartitionSha256"),
            },
            {
                "sourceId": "current-statcast-bronze-manifest",
                "sha256": _sha(request.get("sourceManifestSha256"), label="request.sourceManifestSha256"),
            },
            {
                "sourceId": "mlb-stats-api-schedule-final-authority",
                "sha256": _sha(request.get("scheduleManifestSha256"), label="request.scheduleManifestSha256"),
            },
            {
                "sourceId": "governed-player-identity-registration",
                "sha256": _sha(request.get("identityRegistrationSha256"), label="request.identityRegistrationSha256"),
            },
        ]
        physical_schema = parquet_physical_schema(pa_path)
        partitions.append(
            {
                "byteCount": pa_path.stat().st_size,
                "family": CURRENT_STATCAST_FAMILY,
                "fileSha256": object_sha,
                "maximumDate": partition_date,
                "minimumDate": partition_date,
                "month": int(partition_date[5:7]),
                "partitionId": (
                    f"current-statcast-pa:{partition_date}:sha256:{object_sha}"
                ),
                "physicalSchema": physical_schema,
                "physicalSchemaFingerprint": sha256_bytes(
                    canonical_json_bytes(physical_schema)
                ),
                "relativePath": normalized_relative_path,
                "rowCount": row_count,
                "schemaId": "CURRENT_STATCAST_PA_SCHEMA_V1",
                "season": season,
                "sourceLineage": source_lineage,
                "sourceRightsIds": ["MLB_STATCAST"],
                "targetEligibility": [
                    "EVIDENCE_ONLY",
                    "QUARANTINED",
                    "NOT_APPROVED_FOR_TRAINING",
                ],
                "temporalClassification": [
                    "POINT_IN_TIME_DATE_EXCLUSIVE",
                    "CURRENT_SEASON",
                    *(["COMPLETE_EMPTY_DATE"] if is_complete_empty else []),
                ],
            }
        )

    partitions.extend(copy.deepcopy([dict(item) for item in extra_partitions]))
    if not partitions:
        raise ManifestValidationError(
            "CURRENT_STATCAST_PARTITION_MISSING",
            "No non-empty current or explicit historical PA partition was supplied",
        )
    partitions.sort(
        key=lambda item: (
            str(item.get("minimumDate") or ""),
            str(item.get("partitionId") or ""),
        )
    )
    partition_authority_sha = current_statcast_partition_authority_sha(partitions)
    date_coverage = {
        "earliestDate": min(str(item["minimumDate"]) for item in partitions),
        "latestDate": max(str(item["maximumDate"]) for item in partitions),
        "partitionCount": len(partitions),
        "rowCount": sum(int(item["rowCount"]) for item in partitions),
    }
    publication_rights = _mapping(publication.get("rights"), label="current Silver rights")
    rights = [
        {
            "allowedUses": list(publication_rights.get("allowedUses") or []),
            "attribution": "MLB Advanced Media / Baseball Savant Statcast evidence; preserve source attribution.",
            "controls": {
                "commercialRights": "UNCLEAR_REQUIRES_REVIEW",
                "rawRedistribution": "PROHIBITED",
            },
            "displayName": "MLB Statcast current evidence",
            "metadata": {
                "classification": list(publication_rights.get("classification") or []),
                "sourcePublicationManifestSha256": publication_sha,
            },
            "prohibitedUses": list(publication_rights.get("prohibitedUses") or []),
            "rightsControlId": "MLB_STATCAST",
            "sourceName": str(publication_rights.get("source") or "MLB Advanced Media / Baseball Savant"),
            "status": "GOVERNED_LOCAL_RESEARCH_ONLY",
        },
        *copy.deepcopy([dict(item) for item in additional_rights]),
    ]
    governed_limitations = list(limitations) or [
        {
            "description": "This Data Warehouse registration contains quarantined PA evidence only; it does not fit, score, select, or promote a model.",
            "limitationId": "CURRENT_STATCAST_EVIDENCE_ONLY_NO_FIT",
            "scope": "MODELING",
        },
        {
            "description": "Statcast source rights permit bounded local research; commercial use and raw redistribution require separate review.",
            "limitationId": "CURRENT_STATCAST_RIGHTS_REVIEW_REQUIRED",
            "scope": "RIGHTS",
        },
    ]
    payload = {
        "canonicalizationVersion": CURRENT_STATCAST_CANONICALIZATION_VERSION,
        "datasetId": CURRENT_STATCAST_DATASET_ID,
        "datasetVersionId": (
            f"{CURRENT_STATCAST_DATASET_ID}:"
            f"partition-authority-sha256:{partition_authority_sha}"
        ),
        "dateCoverage": date_coverage,
        "family": CURRENT_STATCAST_FAMILY,
        "league": "MLB",
        "limitations": copy.deepcopy([dict(item) for item in governed_limitations]),
        "manifestId": (
            "current-statcast-pa-dataset-manifest:"
            f"partition-authority-sha256:{partition_authority_sha}"
        ),
        "metadata": {
            "bronzeManifestSha256": current_bronze_sha,
            "modelFitOccurred": False,
            "modelPromotionOccurred": False,
            "normalizationContract": normalizer_contract,
            "publicationManifestSha256": publication_sha,
            "publishedAtBasis": "LATEST_ACCEPTED_EVIDENCE_DATE_END_OF_DAY_UTC",
            "quarantineStatus": "QUARANTINED",
            "sourceAuthorities": copy.deepcopy(dict(source_authorities)),
            "identityCoverage": {
                str(season): copy.deepcopy(
                    dict(((publication.get("coverage") or {}).get(str(season)) or {}).get("identityRowCounts") or {})
                )
                for season in (2025, 2026)
            },
            "normalizationCoverage": {
                str(season): copy.deepcopy(
                    dict(((publication.get("coverage") or {}).get(str(season)) or {}).get("normalizationCounts") or {})
                )
                for season in (2025, 2026)
            },
            "targetClassOrder": copy.deepcopy(publication.get("targetClassOrder") or []),
            "targetEventMap": copy.deepcopy(publication.get("targetEventMap") or {}),
            "temporalContract": copy.deepcopy(publication.get("temporalContract") or {}),
            "trainingApproval": "NOT_APPROVED",
            **({"syncHealth": copy.deepcopy(dict(sync_health))} if sync_health is not None else {}),
            **(
                {"goldPublication": copy.deepcopy(dict(gold_publication))}
                if gold_publication is not None
                else {}
            ),
        },
        "partitions": partitions,
        "publishedAt": f"{date_coverage['latestDate']}T23:59:59Z",
        "rights": rights,
        "schemaVersion": CURRENT_STATCAST_MANIFEST_VERSION,
        "sport": "Baseball",
    }
    manifest_path = write_content_addressed_current_statcast_manifest(
        root / "warehouse-manifests" / "sha256",
        payload,
    )
    return validate_current_statcast_manifest(manifest_path, package_root=root)


def _validate_rights(records: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_list(records, label="rights", nonempty=True)):
        record = _mapping(raw, label=f"rights[{index}]")
        _exact_keys(record, _RIGHT_KEYS, label=f"rights[{index}]")
        identifier = _text(record["rightsControlId"], label=f"rights[{index}].rightsControlId")
        if identifier in seen:
            raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", "Duplicate rights control ID")
        seen.add(identifier)
        for key in ("displayName", "sourceName", "status", "attribution"):
            _text(record[key], label=f"rights[{index}].{key}")
        for key in ("allowedUses", "prohibitedUses"):
            values = _list(record[key], label=f"rights[{index}].{key}")
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"rights[{index}].{key} contains invalid text")
        _mapping(record["controls"], label=f"rights[{index}].controls")
        _mapping(record["metadata"], label=f"rights[{index}].metadata")
        result.append(copy.deepcopy(dict(record)))
    return result


def _validate_limitations(records: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_list(records, label="limitations", nonempty=True)):
        record = _mapping(raw, label=f"limitations[{index}]")
        _exact_keys(record, _LIMITATION_KEYS, label=f"limitations[{index}]")
        normalized = {key: _text(record[key], label=f"limitations[{index}].{key}") for key in _LIMITATION_KEYS}
        if normalized["limitationId"] in seen:
            raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", "Duplicate limitation ID")
        seen.add(normalized["limitationId"])
        result.append(normalized)
    return result


def validate_current_statcast_manifest(
    manifest_path: Path,
    *,
    package_root: Path,
) -> ValidatedCurrentStatcastPackage:
    """Validate one exact, content-addressed current-Statcast PA manifest."""

    raw_manifest_path = raw_absolute_path(Path(manifest_path))
    raw_package_root = raw_absolute_path(Path(package_root))
    reject_reparse_chain(raw_manifest_path, label="Current Statcast manifest")
    reject_reparse_chain(raw_package_root, label="Current Statcast package root")
    if not raw_package_root.is_dir():
        raise ManifestValidationError("CURRENT_STATCAST_PACKAGE_MISSING", "Current Statcast package root is unavailable")
    manifest = load_strict_json(raw_manifest_path, logical_uri="current-statcast://manifest")
    _exact_keys(manifest, _MANIFEST_KEYS, label="manifest")

    if manifest["schemaVersion"] != CURRENT_STATCAST_MANIFEST_VERSION:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", "Unsupported current Statcast manifest version")
    if manifest["canonicalizationVersion"] != CURRENT_STATCAST_CANONICALIZATION_VERSION:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", "Unsupported canonicalization version")
    if manifest["datasetId"] != CURRENT_STATCAST_DATASET_ID:
        raise ManifestValidationError("CURRENT_STATCAST_IDENTITY_MISMATCH", f"datasetId must be {CURRENT_STATCAST_DATASET_ID}")
    if manifest["family"] != CURRENT_STATCAST_FAMILY:
        raise ManifestValidationError("CURRENT_STATCAST_FAMILY_REJECTED", "Only plate_appearance may be registered")
    if manifest["sport"] != "Baseball" or manifest["league"] != "MLB":
        raise ManifestValidationError("CURRENT_STATCAST_IDENTITY_MISMATCH", "Sport and league must be Baseball / MLB")

    declared_sha = _sha(raw_manifest_path.stem, label="manifest filename")
    canonical_bytes = canonical_json_bytes(manifest)
    try:
        stored_bytes = raw_manifest_path.read_bytes()
    except OSError as exc:
        raise ManifestValidationError("METADATA_UNREADABLE", "Current Statcast manifest is unreadable") from exc
    if stored_bytes != canonical_bytes:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_NOT_CANONICAL", "Manifest bytes are not exact canonical JSON")
    computed_sha = sha256_bytes(stored_bytes)
    if computed_sha != declared_sha:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_HASH_MISMATCH", "Manifest content address does not match its canonical payload")
    if raw_manifest_path.name != f"{declared_sha}.json":
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_ADDRESS_MISMATCH", "Manifest filename is not its SHA-256 address")
    dataset_version_id = _text(manifest["datasetVersionId"], label="datasetVersionId")
    manifest_id = _text(manifest["manifestId"], label="manifestId")
    _text(manifest["publishedAt"], label="publishedAt")

    metadata = _mapping(manifest["metadata"], label="metadata")
    missing_metadata = sorted(_REQUIRED_METADATA_KEYS - set(metadata))
    if missing_metadata:
        raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"metadata is missing {missing_metadata}")
    _sha(metadata["bronzeManifestSha256"], label="metadata.bronzeManifestSha256")
    _sha(metadata["publicationManifestSha256"], label="metadata.publicationManifestSha256")
    _text(metadata["normalizationContract"], label="metadata.normalizationContract")
    if metadata["modelFitOccurred"] is not False or metadata["modelPromotionOccurred"] is not False:
        raise ManifestValidationError("CURRENT_STATCAST_MODEL_CLAIM_REJECTED", "Evidence registration may not claim a fit or promotion")
    if metadata["quarantineStatus"] != "QUARANTINED" or metadata["trainingApproval"] != "NOT_APPROVED":
        raise ManifestValidationError("CURRENT_STATCAST_MODEL_CLAIM_REJECTED", "Current Statcast evidence must remain quarantined and not approved for training")
    if metadata["targetClassOrder"] != list(PA_CLASS_ORDER):
        raise ManifestValidationError(
            "CURRENT_STATCAST_TARGET_CONTRACT_INVALID",
            "Current Statcast class order differs from the governed eight-class order",
        )
    target_event_map = _mapping(metadata["targetEventMap"], label="metadata.targetEventMap")
    if not target_event_map or set(target_event_map.values()) != set(PA_CLASS_ORDER):
        raise ManifestValidationError(
            "CURRENT_STATCAST_TARGET_CONTRACT_INVALID",
            "Current Statcast event map does not cover exactly the governed outcome classes",
        )
    temporal_contract = _mapping(metadata["temporalContract"], label="metadata.temporalContract")
    required_temporal = {
        "intendedCombinedDevelopmentSelection": ["2023-03-30", "2026-08-13"],
        "intendedCombinedFinalOot": ["2026-08-14", "2026-08-27"],
    }
    for key, expected in required_temporal.items():
        if temporal_contract.get(key) != expected:
            raise ManifestValidationError(
                "CURRENT_STATCAST_TEMPORAL_CONTRACT_INVALID",
                f"metadata.temporalContract.{key} differs from the authorized design",
            )
    eligible_evidence = temporal_contract.get("intendedCombinedEligibleEvidence")
    if (
        not isinstance(eligible_evidence, list)
        or len(eligible_evidence) != 2
        or eligible_evidence[0] != "2023-03-30"
        or _date(eligible_evidence[1], label="intendedCombinedEligibleEvidence.end")
        > CURRENT_STATCAST_LATEST_AUTHORIZED_DATE
    ):
        raise ManifestValidationError(
            "CURRENT_STATCAST_TEMPORAL_CONTRACT_INVALID",
            "Eligible evidence must begin at 2023-03-30 and stay within the authorized 2026 season",
        )
    cutoff_rule = _text(
        temporal_contract.get("featureCutoffRule"),
        label="metadata.temporalContract.featureCutoffRule",
    )
    if "gameDate < target.gameDate" not in cutoff_rule:
        raise ManifestValidationError(
            "CURRENT_STATCAST_TEMPORAL_CONTRACT_INVALID",
            "Feature cutoff must exclude target-date and later source rows",
        )

    coverage = _mapping(manifest["dateCoverage"], label="dateCoverage")
    _exact_keys(coverage, _DATE_COVERAGE_KEYS, label="dateCoverage")
    earliest = _date(coverage["earliestDate"], label="dateCoverage.earliestDate")
    latest = _date(coverage["latestDate"], label="dateCoverage.latestDate")
    if earliest > latest:
        raise ManifestValidationError("CURRENT_STATCAST_DATE_COVERAGE_INVALID", "Earliest date exceeds latest date")
    if (
        earliest < CURRENT_STATCAST_EARLIEST_AUTHORIZED_DATE
        or latest > CURRENT_STATCAST_LATEST_AUTHORIZED_DATE
    ):
        raise ManifestValidationError(
            "CURRENT_STATCAST_DATE_COVERAGE_INVALID",
            "Manifest date coverage exceeds the authorized 2023-03-30 through 2026-12-31 window",
        )
    declared_rows = _integer(coverage["rowCount"], label="dateCoverage.rowCount")
    declared_partition_count = _integer(coverage["partitionCount"], label="dateCoverage.partitionCount", minimum=1)

    rights = _validate_rights(manifest["rights"])
    limitations = _validate_limitations(manifest["limitations"])
    right_ids = {record["rightsControlId"] for record in rights}
    partitions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: dict[str, int] = {}
    for index, raw in enumerate(_list(manifest["partitions"], label="partitions", nonempty=True)):
        partition = _mapping(raw, label=f"partitions[{index}]")
        _exact_keys(partition, _PARTITION_KEYS, label=f"partitions[{index}]")
        partition_id = _text(partition["partitionId"], label=f"partitions[{index}].partitionId")
        if partition_id in seen_ids:
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_DUPLICATE", "Duplicate partition ID")
        seen_ids.add(partition_id)
        if partition["family"] != CURRENT_STATCAST_FAMILY:
            raise ManifestValidationError("CURRENT_STATCAST_FAMILY_REJECTED", "Every partition must be plate_appearance")
        season = _integer(partition["season"], label=f"partitions[{index}].season", minimum=2000)
        month_value = partition["month"]
        month = None if month_value is None else _integer(
            month_value,
            label=f"partitions[{index}].month",
            minimum=1,
        )
        if month is not None and month > 12:
            raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", "Partition month must be null or 1 through 12")
        minimum = _date(partition["minimumDate"], label=f"partitions[{index}].minimumDate")
        maximum = _date(partition["maximumDate"], label=f"partitions[{index}].maximumDate")
        if (
            minimum > maximum
            or minimum.year != season
            or maximum.year != season
            or (
                month is not None
                and (minimum.month != month or maximum.month != month)
            )
        ):
            raise ManifestValidationError("CURRENT_STATCAST_DATE_COVERAGE_INVALID", "Partition date range differs from its season/month")
        row_count = _integer(partition["rowCount"], label=f"partitions[{index}].rowCount")
        byte_count = _integer(partition["byteCount"], label=f"partitions[{index}].byteCount", minimum=1)
        path, relative_path = _relative_file(raw_package_root, partition["relativePath"], label=f"partitions[{index}].relativePath")
        if relative_path in seen_paths and (row_count != 0 or seen_paths[relative_path] != 0):
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_DUPLICATE", "Duplicate partition relative path")
        seen_paths[relative_path] = row_count
        if path.suffix.casefold() != ".parquet":
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_FORMAT_REJECTED", "Only Parquet plate-appearance partitions may be registered")
        if path.stat().st_size != byte_count:
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_SIZE_MISMATCH", "Partition byte count differs", logical_uri=relative_path)
        if sha256_file(path, logical_uri=relative_path) != _sha(partition["fileSha256"], label=f"partitions[{index}].fileSha256"):
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_HASH_MISMATCH", "Partition hash differs", logical_uri=relative_path)
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows != row_count:
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_ROW_COUNT_MISMATCH", "Partition row count differs", logical_uri=relative_path)
        try:
            game_dates = pq.read_table(path, columns=["gameDate"])["gameDate"].to_pylist()
        except (KeyError, OSError, ValueError) as exc:
            raise ManifestValidationError(
                "CURRENT_STATCAST_PARTITION_SCHEMA_MISMATCH",
                "Partition must contain exact gameDate coverage evidence",
                logical_uri=relative_path,
            ) from exc
        if len(game_dates) != row_count or any(value is None for value in game_dates):
            raise ManifestValidationError(
                "CURRENT_STATCAST_DATE_COVERAGE_INVALID",
                "Partition gameDate values are incomplete",
                logical_uri=relative_path,
            )
        temporal_values = _list(
            partition["temporalClassification"],
            label=f"partitions[{index}].temporalClassification",
        )
        empty_marker = "COMPLETE_EMPTY_DATE" in temporal_values
        if row_count == 0:
            expected_empty_id = (
                f"current-statcast-pa:{minimum.isoformat()}:sha256:{partition['fileSha256']}"
            )
            if (
                not empty_marker
                or minimum != maximum
                or partition_id != expected_empty_id
                or game_dates
            ):
                raise ManifestValidationError(
                    "CURRENT_STATCAST_EMPTY_PARTITION_INVALID",
                    "A zero-row partition must be an exact marked current-date Silver PA object",
                    logical_uri=relative_path,
                )
        else:
            if empty_marker:
                raise ManifestValidationError(
                    "CURRENT_STATCAST_EMPTY_PARTITION_INVALID",
                    "A non-empty partition may not claim COMPLETE_EMPTY_DATE",
                    logical_uri=relative_path,
                )
            observed_dates = [
                _date(str(value), label=f"{relative_path}.gameDate")
                for value in game_dates
            ]
            if min(observed_dates) != minimum or max(observed_dates) != maximum:
                raise ManifestValidationError(
                    "CURRENT_STATCAST_DATE_COVERAGE_INVALID",
                    "Partition declared date range differs from its exact gameDate values",
                    logical_uri=relative_path,
                )
        physical_schema = _list(partition["physicalSchema"], label=f"partitions[{index}].physicalSchema", nonempty=True)
        expected_schema = parquet_physical_schema(path)
        if physical_schema != expected_schema:
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_SCHEMA_MISMATCH", "Partition physical schema differs", logical_uri=relative_path)
        schema_sha = sha256_bytes(canonical_json_bytes(physical_schema))
        if schema_sha != _sha(partition["physicalSchemaFingerprint"], label=f"partitions[{index}].physicalSchemaFingerprint"):
            raise ManifestValidationError("CURRENT_STATCAST_PARTITION_SCHEMA_MISMATCH", "Physical schema fingerprint differs", logical_uri=relative_path)
        _text(partition["schemaId"], label=f"partitions[{index}].schemaId")
        lineage = _list(partition["sourceLineage"], label=f"partitions[{index}].sourceLineage", nonempty=True)
        normalized_lineage: list[dict[str, str]] = []
        seen_sources: set[str] = set()
        for source_index, raw_source in enumerate(lineage):
            source = _mapping(raw_source, label=f"partitions[{index}].sourceLineage[{source_index}]")
            _exact_keys(source, _SOURCE_KEYS, label=f"partitions[{index}].sourceLineage[{source_index}]")
            source_id = _text(source["sourceId"], label="sourceLineage.sourceId")
            if source_id in seen_sources:
                raise ManifestValidationError("CURRENT_STATCAST_SOURCE_LINEAGE_INVALID", "Duplicate source ID in partition")
            seen_sources.add(source_id)
            normalized_lineage.append({"sourceId": source_id, "sha256": _sha(source["sha256"], label="sourceLineage.sha256")})
        source_rights_ids = _list(partition["sourceRightsIds"], label=f"partitions[{index}].sourceRightsIds", nonempty=True)
        if any(not isinstance(item, str) or item not in right_ids for item in source_rights_ids):
            raise ManifestValidationError("CURRENT_STATCAST_RIGHTS_BINDING_INVALID", "Partition references an undeclared rights control")
        for list_key in ("targetEligibility", "temporalClassification"):
            values = _list(partition[list_key], label=f"partitions[{index}].{list_key}")
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ManifestValidationError("CURRENT_STATCAST_MANIFEST_SCHEMA_INVALID", f"partitions[{index}].{list_key} contains invalid text")
        expected_empty_lineage = {
            f"statcast/regular/year={season}/{minimum.isoformat()}",
            "current-statcast-bronze-manifest",
            "mlb-stats-api-schedule-final-authority",
            "governed-player-identity-registration",
        }
        if row_count == 0 and {
            item["sourceId"] for item in normalized_lineage
        } != expected_empty_lineage:
            raise ManifestValidationError(
                "CURRENT_STATCAST_EMPTY_PARTITION_INVALID",
                "A COMPLETE_EMPTY partition must retain the exact four governed source authorities",
                logical_uri=relative_path,
            )
        partitions.append({**copy.deepcopy(dict(partition)), "relativePath": relative_path, "sourceLineage": normalized_lineage})

    if len(partitions) != declared_partition_count:
        raise ManifestValidationError("CURRENT_STATCAST_DATE_COVERAGE_INVALID", "Partition count does not reconcile")
    if sum(item["rowCount"] for item in partitions) != declared_rows:
        raise ManifestValidationError("CURRENT_STATCAST_DATE_COVERAGE_INVALID", "Row count does not reconcile")
    if min(_date(item["minimumDate"], label="partition.minimumDate") for item in partitions) != earliest:
        raise ManifestValidationError("CURRENT_STATCAST_DATE_COVERAGE_INVALID", "Earliest date does not reconcile")
    if max(_date(item["maximumDate"], label="partition.maximumDate") for item in partitions) != latest:
        raise ManifestValidationError("CURRENT_STATCAST_DATE_COVERAGE_INVALID", "Latest date does not reconcile")

    partition_authority_sha = current_statcast_partition_authority_sha(partitions)
    expected_dataset_version_id = (
        f"{CURRENT_STATCAST_DATASET_ID}:partition-authority-sha256:{partition_authority_sha}"
    )
    expected_manifest_id = (
        "current-statcast-pa-dataset-manifest:"
        f"partition-authority-sha256:{partition_authority_sha}"
    )
    if dataset_version_id != expected_dataset_version_id or manifest_id != expected_manifest_id:
        raise ManifestValidationError(
            "CURRENT_STATCAST_IDENTITY_MISMATCH",
            "Dataset-version and manifest identities must bind the exact combined PA partition authority",
        )
    normalized_manifest = copy.deepcopy(manifest)
    normalized_manifest["manifestSha256"] = declared_sha
    normalized_manifest["partitions"] = partitions
    normalized_manifest["rights"] = rights
    normalized_manifest["limitations"] = limitations
    return ValidatedCurrentStatcastPackage(
        manifest_path=raw_manifest_path,
        package_root=raw_package_root,
        manifest=normalized_manifest,
        partition_authority_sha=partition_authority_sha,
        validated_at=now_iso(),
    )


class CurrentStatcastDatasetRegistry:
    """Atomic, idempotent metadata registrar for validated current PA evidence."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _registration_id(manifest_sha: str) -> str:
        return f"sports-dataset-current-statcast-{manifest_sha[:16]}"

    def register(self, validated: ValidatedCurrentStatcastPackage, *, user_id: str) -> dict[str, Any]:
        manifest = validated.manifest
        manifest_sha = str(manifest["manifestSha256"])
        registration_id = self._registration_id(manifest_sha)
        registered_at = now_iso()
        coverage = dict(manifest["dateCoverage"])
        partitions = list(manifest["partitions"])
        seasons: list[dict[str, Any]] = []
        for season in sorted({int(item["season"]) for item in partitions}):
            season_parts = [item for item in partitions if int(item["season"]) == season]
            seasons.append(
                {
                    "season": season,
                    "games": None,
                    "plate_appearances": sum(int(item["rowCount"]) for item in season_parts),
                    "transitions": None,
                    "starter_targets": None,
                    "bullpen_appearances": None,
                    "date_range": {
                        "earliestDate": min(item["minimumDate"] for item in season_parts),
                        "latestDate": max(item["maximumDate"] for item in season_parts),
                    },
                }
            )
        totals = {
            "packageFiles": len(partitions) + 1,
            "parquetFiles": len(partitions),
            "rows": coverage["rowCount"],
            "parquetBytes": sum(int(item["byteCount"]) for item in partitions),
            "plateAppearances": coverage["rowCount"],
            "partitions": len(partitions),
        }
        metadata = {
            "adapter": CURRENT_STATCAST_MANIFEST_VERSION,
            "datasetKind": "CURRENT_STATCAST_PLATE_APPEARANCE",
            "dateCoverage": coverage,
            "manifestMetadata": manifest["metadata"],
            "modelFitOccurred": False,
            "modelingBlockers": [],
            "modelingStatus": CURRENT_STATCAST_MODELING_STATUS,
            "partitionAuthoritySha": validated.partition_authority_sha,
        }
        evidence_coverage = [
            {
                "evidence": "plateAppearance",
                "status": "REGISTERED_CURRENT_STATCAST_EVIDENCE",
                "detail": f"Exact accepted PA coverage is {coverage['earliestDate']} through {coverage['latestDate']}.",
            },
            {
                "evidence": "modelFit",
                "status": "NOT_RUN",
                "detail": "This registration contains evidence only and makes no model-fit or promotion claim.",
            },
        ]
        logical_root = (
            "asp-model-studio-runtime://sports-datasets/"
            f"{CURRENT_STATCAST_DATASET_ID}/sha256/{manifest_sha}"
        )

        # Exact re-registration is a true no-op.  In particular, do not delete
        # and rebuild child metadata for an already verified immutable version.
        with self.database.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE manifest_sha = ?",
                (manifest_sha,),
            ).fetchone()
        if existing is not None:
            if (
                existing["registration_id"] != registration_id
                or existing["dataset_id"] != CURRENT_STATCAST_DATASET_ID
                or existing["logical_package_root"] != logical_root
            ):
                raise ManifestValidationError(
                    "CURRENT_STATCAST_REGISTRATION_CONFLICT",
                    "Existing manifest registration has a different immutable identity",
                )
            from .registry import SportsDatasetRegistry

            reused = SportsDatasetRegistry(self.database).get(registration_id)
            if reused is None:
                raise RuntimeError("Current Statcast registration disappeared during exact reuse")
            reused["registration_disposition"] = "REUSED"
            return reused

        with self.database.transaction() as connection:
            prior_rows = connection.execute(
                """
                SELECT registration_id, active, metadata_json
                FROM sports_dataset_registrations
                WHERE dataset_id = ? AND validation_status = 'VALID'
                ORDER BY registered_at DESC, registration_id
                """,
                (CURRENT_STATCAST_DATASET_ID,),
            ).fetchall()
            prior_active = any(bool(row["active"]) for row in prior_rows)
            historical_ids: list[str] = []
            for row in prior_rows:
                prior_id = str(row["registration_id"])
                historical_ids.append(prior_id)
                try:
                    prior_metadata = json.loads(str(row["metadata_json"] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    prior_metadata = {}
                prior_metadata.update(
                    {
                        "authorityState": "HISTORICAL",
                        "supersededByRegistrationId": registration_id,
                    }
                )
                connection.execute(
                    "UPDATE sports_dataset_registrations SET active = 0, metadata_json = ? WHERE registration_id = ?",
                    (json_dumps(prior_metadata, {}), prior_id),
                )

            metadata.update(
                {
                    "authorityState": "CURRENT",
                    "historicalRegistrationIds": historical_ids,
                    "supersedesRegistrationId": historical_ids[0] if historical_ids else None,
                    "syncHealth": (manifest.get("metadata") or {}).get("syncHealth"),
                    "goldPublication": (manifest.get("metadata") or {}).get("goldPublication"),
                }
            )
            connection.execute(
                    """
                    INSERT INTO sports_dataset_registrations (
                      registration_id, dataset_id, dataset_version_id, manifest_id, manifest_sha,
                      package_id, sport, league, evidence_cutoff, published_at, logical_package_root,
                      validation_status, registered_at, last_validated_at, registered_by, rights_status,
                      limitation_count, active, totals_json, seasons_json, evidence_coverage_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 'Baseball', 'MLB', ?, ?, ?, 'VALID', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        registration_id,
                        CURRENT_STATCAST_DATASET_ID,
                        manifest["datasetVersionId"],
                        manifest["manifestId"],
                        manifest_sha,
                        f"current-statcast-pa-sha256-{manifest_sha}",
                        coverage["latestDate"],
                        manifest["publishedAt"],
                        logical_root,
                        registered_at,
                        validated.validated_at,
                        user_id,
                        "GOVERNED_LOCAL_RESEARCH_ONLY",
                        len(manifest["limitations"]),
                        int(prior_active),
                        json_dumps(totals, {}),
                        json_dumps(seasons, []),
                        json_dumps(evidence_coverage, []),
                        json_dumps(metadata, {}),
                    ),
                )

            # Revalidation replaces only the current dataset's governed metadata,
            # repairing stale local rows without touching any FD1 child record.
            for table in (
                "sports_research_projects",
                "sports_dataset_temporal_folds",
                "sports_dataset_populations",
                "sports_dataset_limitations",
                "sports_dataset_rights",
                "sports_dataset_schemas",
                "sports_dataset_partitions",
            ):
                connection.execute(f"DELETE FROM {table} WHERE registration_id = ?", (registration_id,))

            schema_variants: dict[str, dict[str, Any]] = {}
            for partition in partitions:
                fingerprint = partition["physicalSchemaFingerprint"]
                schema_variants.setdefault(
                    fingerprint,
                    {
                        "physicalSchemaFingerprint": fingerprint,
                        "fields": partition["physicalSchema"],
                    },
                )
                source_lineage = list(partition["sourceLineage"])
                # ``sports_dataset_partitions.partition_id`` is globally keyed,
                # while daily source identities legitimately recur in later
                # immutable current-dataset versions.  Namespace the registry
                # key by this manifest and retain the exact source identity in
                # sourceLineage/original_source_logical_identity.
                registry_partition_id = (
                    f"{registration_id}:"
                    f"{sha256_bytes(canonical_json_bytes(partition['partitionId']))[:20]}"
                )
                registry_logical_uri = (
                    f"{logical_root}/{partition['relativePath']}"
                    f"#registration={registration_id}&partition={registry_partition_id.rsplit(':', 1)[-1]}"
                )
                connection.execute(
                    """
                    INSERT INTO sports_dataset_partitions (
                      partition_id, registration_id, family, season, month, logical_uri,
                      row_count, byte_count, minimum_date, maximum_date, schema_id,
                      physical_schema_fingerprint, file_sha, source_key, source_version_id,
                      original_source_logical_identity, checkpoint_lineage_id, governance_checksum,
                      target_eligibility_json, temporal_classification_json, rights_ids_json, physical_schema_json
                    ) VALUES (?, ?, 'plate_appearance', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STATCAST', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        registry_partition_id,
                        registration_id,
                        partition["season"],
                        partition["month"],
                        registry_logical_uri,
                        partition["rowCount"],
                        partition["byteCount"],
                        partition["minimumDate"],
                        partition["maximumDate"],
                        partition["schemaId"],
                        partition["physicalSchemaFingerprint"],
                        partition["fileSha256"],
                        manifest["metadata"]["bronzeManifestSha256"],
                        json_dumps(source_lineage, []),
                        manifest["metadata"]["publicationManifestSha256"],
                        sha256_bytes(canonical_json_bytes(partition)),
                        json_dumps(partition["targetEligibility"], []),
                        json_dumps(partition["temporalClassification"], []),
                        json_dumps(partition["sourceRightsIds"], []),
                        json_dumps(partition["physicalSchema"], []),
                    ),
                )

            first_schema = partitions[0]["physicalSchema"]
            connection.execute(
                """
                INSERT INTO sports_dataset_schemas (
                  registration_id, family, logical_schema_version, compatible_partition_count,
                  physical_variant_count, fields_json, physical_variants_json
                ) VALUES (?, 'plate_appearance', ?, ?, ?, ?, ?)
                """,
                (
                    registration_id,
                    partitions[0]["schemaId"],
                    len(partitions),
                    len(schema_variants),
                    json_dumps(first_schema, []),
                    json_dumps(list(schema_variants.values()), []),
                ),
            )
            for right in manifest["rights"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_rights (
                      registration_id, rights_control_id, display_name, source_name, status,
                      allowed_uses_json, prohibited_uses_json, attribution, controls_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        registration_id,
                        right["rightsControlId"],
                        right["displayName"],
                        right["sourceName"],
                        right["status"],
                        json_dumps(right["allowedUses"], []),
                        json_dumps(right["prohibitedUses"], []),
                        right["attribution"],
                        json_dumps(right["controls"], {}),
                        json_dumps(right["metadata"], {}),
                    ),
                )
            for limitation in manifest["limitations"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_limitations (registration_id, limitation_id, scope, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    (registration_id, limitation["limitationId"], limitation["scope"], limitation["description"]),
                )

        from .registry import SportsDatasetRegistry

        result = SportsDatasetRegistry(self.database).get(registration_id)
        if result is None:
            raise RuntimeError("Current Statcast dataset registration was not persisted")
        result["registration_disposition"] = "CREATED"
        return result


__all__ = [
    "CURRENT_STATCAST_CANONICALIZATION_VERSION",
    "CURRENT_STATCAST_DATASET_ID",
    "CURRENT_STATCAST_FAMILY",
    "CURRENT_STATCAST_EARLIEST_AUTHORIZED_DATE",
    "CURRENT_STATCAST_LATEST_AUTHORIZED_DATE",
    "CURRENT_STATCAST_MANIFEST_VERSION",
    "CURRENT_STATCAST_MODELING_STATUS",
    "CurrentStatcastDatasetRegistry",
    "ValidatedCurrentStatcastPackage",
    "build_current_statcast_warehouse_manifest",
    "current_statcast_partition_authority_sha",
    "current_statcast_partition_descriptor",
    "parquet_physical_schema",
    "validate_current_statcast_manifest",
    "write_content_addressed_current_statcast_manifest",
]

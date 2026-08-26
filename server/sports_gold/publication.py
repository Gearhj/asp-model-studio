"""Immutable Gold V1 publication and verification.

Gold uses the repository's existing content-addressed dataset publisher.  The
small top-level receipt is only a convenience pointer to the one research
object; it is not a model registry and confers no promotion authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_modeling import gen3_publish as GP
from .contracts import (
    EXPECTED_GOLD_SEASON_ROWS,
    EXPECTED_GOLD_TOTAL_ROWS,
    GOLD_CLASS_ORDER,
    GOLD_FEATURES,
    GOLD_GOVERNANCE,
    gold_contract_bundle,
)


GOLD_OBJECT_KIND = "gold_mlb_pa_v1"
GOLD_RECEIPT = "MLB_GOLD_V1_RESEARCH_RECEIPT_V1"


class GoldPublicationError(RuntimeError):
    """The Gold object is incomplete, mutable, or inconsistent with its contract."""


def implementation_identity(paths: Sequence[Path]) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    files: list[dict[str, Any]] = []
    for raw in sorted({Path(path).resolve() for path in paths}, key=lambda value: str(value).lower()):
        try:
            relative = raw.relative_to(root).as_posix()
        except ValueError as exc:
            raise GoldPublicationError(f"implementation file is outside repository: {raw}") from exc
        data = raw.read_bytes()
        files.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {
        "schemaVersion": "MLB_GOLD_IMPLEMENTATION_IDENTITY_V1",
        "files": files,
        "sha256": sha256_bytes(canonical_json_bytes(files)),
    }


def publish_gold(
    gold_root: Path,
    table: pa.Table,
    *,
    source_inputs: Mapping[str, Any],
    connection_report: Mapping[str, Any],
    feature_quality: Mapping[str, Any],
    implementation: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(table, pa.Table) or table.num_rows == 0:
        raise GoldPublicationError("Gold publication requires a non-empty Arrow table")
    required = {
        "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id", "game_date",
        "season", "outcome", "datasetRole", *GOLD_FEATURES,
    }
    missing = sorted(required - set(table.column_names))
    if missing:
        raise GoldPublicationError(f"Gold table columns missing: {missing}")
    seasons = tuple(sorted({int(value) for value in table["season"].to_pylist()}))
    if seasons != (2021, 2022, 2023, 2024):
        raise GoldPublicationError(f"Gold seasons differ: {seasons}")
    bundle = gold_contract_bundle()
    bundle_sha = str(bundle["bundleSha256"])
    contracts = {name: item for name, item in bundle.items() if name != "bundleSha256"}
    provenance = {
        "datasetName": GOLD_OBJECT_KIND,
        **GOLD_GOVERNANCE,
        "seasons": list(seasons),
        "developmentSeasons": [2021, 2022, 2023],
        "validationSeason": 2024,
        "featureNames": list(GOLD_FEATURES),
        "featureCount": len(GOLD_FEATURES),
        "targetColumn": "outcome",
        "classOrder": list(contracts["target"]["payload"]["classOrder"]),
        "sourceInputs": dict(source_inputs),
        "connectionReport": dict(connection_report),
        "featureQuality": dict(feature_quality),
        "implementationIdentity": dict(implementation),
    }
    manifest = GP.publish_object(
        Path(gold_root), table, object_kind=GOLD_OBJECT_KIND, contracts=contracts,
        contract_bundle_sha=bundle_sha, provenance_extra=provenance,
    )
    object_sha = str(manifest["logicalContentSha256"])
    object_dir = Path(gold_root).resolve() / "objects" / "sha256" / object_sha
    stored_manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
    expected_contract_ids = {name: item["id"] for name, item in contracts.items()}
    if stored_manifest.get("contractBundleSha256") != bundle_sha \
            or stored_manifest.get("contracts") != expected_contract_ids:
        raise GoldPublicationError("persisted Gold contract authority differs")
    for key, expected in provenance.items():
        if canonical_json_bytes(stored_manifest.get(key)) != canonical_json_bytes(expected):
            raise GoldPublicationError(f"persisted Gold provenance differs on reuse: {key}")
    receipt_body = {
        "receiptContract": GOLD_RECEIPT,
        "datasetVersionId": f"gold-table:{GOLD_OBJECT_KIND}:sha256:{object_sha}",
        "logicalContentSha256": object_sha,
        "objectKind": GOLD_OBJECT_KIND,
        "relativeObjectPath": f"objects/sha256/{object_sha}",
        "physicalParquetSha256": stored_manifest["physicalParquetSha256"],
        "contractBundleSha256": bundle_sha,
        **GOLD_GOVERNANCE,
    }
    receipt_bytes = canonical_json_bytes(receipt_body)
    receipt_path = Path(gold_root).resolve() / f"{GOLD_OBJECT_KIND}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = receipt_path.parent / f".tmp-{uuid.uuid4().hex}.json"
    tmp.write_bytes(receipt_bytes)
    os.replace(tmp, receipt_path)
    return verify_gold(Path(gold_root), object_sha)


def verify_gold(gold_root: Path, object_sha: str | None = None) -> dict[str, Any]:
    root = Path(gold_root).resolve()
    receipt_path = root / f"{GOLD_OBJECT_KIND}.json"
    if not receipt_path.is_file():
        raise GoldPublicationError("Gold research receipt is missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("receiptContract") != GOLD_RECEIPT:
        raise GoldPublicationError("Gold receipt contract differs")
    addressed = str(receipt.get("logicalContentSha256", ""))
    if object_sha is not None and addressed != object_sha:
        raise GoldPublicationError("requested Gold object differs from receipt")
    object_dir = (root / "objects" / "sha256" / addressed).resolve()
    if root not in object_dir.parents or not object_dir.is_dir():
        raise GoldPublicationError("Gold object path is missing or escapes root")
    manifest_path = object_dir / "manifest.json"
    parquet_path = object_dir / f"{GOLD_OBJECT_KIND}.parquet"
    if not manifest_path.is_file() or not parquet_path.is_file():
        raise GoldPublicationError("Gold object children are incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("logicalContentSha256") != addressed or manifest.get("objectKind") != GOLD_OBJECT_KIND:
        raise GoldPublicationError("Gold manifest identity differs")
    bundle = gold_contract_bundle()
    bundle_sha = str(bundle["bundleSha256"])
    contracts = {name: item for name, item in bundle.items() if name != "bundleSha256"}
    expected_contract_ids = {name: item["id"] for name, item in contracts.items()}
    expected_dataset_id = f"gold-table:{GOLD_OBJECT_KIND}:sha256:{addressed}"
    if receipt.get("datasetVersionId") != expected_dataset_id \
            or receipt.get("relativeObjectPath") != f"objects/sha256/{addressed}":
        raise GoldPublicationError("Gold receipt relationship differs")
    if receipt.get("contractBundleSha256") != bundle_sha \
            or manifest.get("contractBundleSha256") != bundle_sha \
            or manifest.get("contracts") != expected_contract_ids:
        raise GoldPublicationError("Gold contract bundle differs from current authority")
    physical = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    if physical != manifest.get("physicalParquetSha256") or physical != receipt.get("physicalParquetSha256"):
        raise GoldPublicationError("Gold parquet physical hash differs")
    table = pq.read_table(parquet_path)
    schema_sha = GP._schema_sha(table)
    if manifest.get("schemaSha256") != schema_sha or manifest.get("rowCount") != table.num_rows:
        raise GoldPublicationError("Gold schema or row count differs from manifest")
    logical = GP.logical_content_sha(
        table.replace_schema_metadata(None),
        contract_bundle_sha=bundle_sha,
        schema_sha=schema_sha,
    )
    if logical != addressed:
        raise GoldPublicationError("Gold logical content differs from address")
    seasons = tuple(sorted({int(value) for value in table["season"].to_pylist()}))
    if seasons != (2021, 2022, 2023, 2024):
        raise GoldPublicationError(f"Gold season boundary differs: {seasons}")
    required = {
        "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id", "game_date",
        "season", "outcome", "datasetRole", *GOLD_FEATURES,
    }
    if not required.issubset(table.column_names):
        raise GoldPublicationError("Gold table schema is missing contracted columns")
    if table.num_rows != EXPECTED_GOLD_TOTAL_ROWS:
        raise GoldPublicationError(f"Gold row count differs: {table.num_rows}")
    season_rows = {
        int(key): int(value)
        for key, value in table["season"].to_pandas().value_counts().sort_index().items()
    }
    if season_rows != dict(EXPECTED_GOLD_SEASON_ROWS):
        raise GoldPublicationError(f"Gold season row counts differ: {season_rows}")
    if table["canonicalPaId"].to_pandas().duplicated().any() \
            or table["plate_appearance_id"].to_pandas().duplicated().any():
        raise GoldPublicationError("Gold PA identity is duplicated")
    roles = table.select(["season", "datasetRole"]).to_pandas()
    expected_roles = roles["season"].map(
        {2021: "DEVELOPMENT", 2022: "DEVELOPMENT", 2023: "DEVELOPMENT", 2024: "VALIDATION"}
    )
    if not roles["datasetRole"].eq(expected_roles).all():
        raise GoldPublicationError("Gold dataset roles differ from the temporal split")
    if set(table["outcome"].to_pylist()) != set(GOLD_CLASS_ORDER):
        raise GoldPublicationError("Gold target classes differ from the fixed class order")
    metadata = table.schema.metadata or {}
    expected_metadata = {
        b"artifactSchemaVersion": GP.GEN3_PUBLISH_SCHEMA_VERSION,
        b"objectKind": GOLD_OBJECT_KIND,
        b"logicalContentSha256": addressed,
        b"schemaSha256": schema_sha,
        b"contractBundleSha256": bundle_sha,
        b"temporalContractId": contracts["temporal"]["id"],
        b"featureSchemaId": contracts["featureSchema"]["id"],
        b"targetContractId": contracts["target"]["id"],
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key, b"").decode("utf-8", errors="strict") != expected:
            raise GoldPublicationError(f"Gold embedded metadata differs: {key.decode()}")
    if manifest.get("featureNames") != list(GOLD_FEATURES) \
            or manifest.get("featureCount") != len(GOLD_FEATURES) \
            or manifest.get("targetColumn") != "outcome" \
            or manifest.get("classOrder") != list(GOLD_CLASS_ORDER):
        raise GoldPublicationError("Gold manifest feature or target authority differs")
    for required_evidence in ("sourceInputs", "connectionReport", "featureQuality", "implementationIdentity"):
        if not isinstance(manifest.get(required_evidence), dict) or not manifest[required_evidence]:
            raise GoldPublicationError(f"Gold provenance is missing: {required_evidence}")
    if manifest.get("status") != "RESEARCH_ONLY" or manifest.get("promotionEligible") is not False \
            or manifest.get("championEligible") is not False:
        raise GoldPublicationError("Gold research-only governance differs")
    for key, expected in GOLD_GOVERNANCE.items():
        if manifest.get(key) != expected or receipt.get(key) != expected:
            raise GoldPublicationError(f"Gold governance differs: {key}")
    return {
        "datasetVersionId": receipt["datasetVersionId"],
        "logicalContentSha256": addressed,
        "path": parquet_path,
        "manifestPath": manifest_path,
        "rowCount": table.num_rows,
        "seasons": list(seasons),
        "featureCount": len(GOLD_FEATURES),
        "featureNames": list(GOLD_FEATURES),
        **GOLD_GOVERNANCE,
    }


__all__ = [
    "GOLD_OBJECT_KIND",
    "GoldPublicationError",
    "implementation_identity",
    "publish_gold",
    "verify_gold",
]

"""Publish the bounded current Statcast pitch/PA evidence outside Git.

The legacy Advanced Bronze manifest and its Phase 7B1 Silver objects remain
immutable.  This module reads their verified 2023--2024 daily Statcast
partitions, appends separately acquired 2025--2026 daily partitions, and
publishes a new content-addressed evidence object.  Current-season rows are
admitted only when their ``game_pk`` is present in the immutable MLB Stats API
final-game authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_silver import silver_publication as silver_publish
from ..sports_silver.current_statcast_pa import (
    EVENT_TO_OUTCOME,
    FINAL_GAME_AUTHORITY_CONTRACT,
    NORMALIZER_CONTRACT,
    PA_CLASS_ORDER,
    normalize_current_partition,
)
from tools.bronze_acquisition import BRONZE_MANIFEST_CONTRACT


CURRENT_DATASET_ID = "asp.mlb.statcast.current-pa.v1"
CURRENT_SILVER_CONTRACT = "MLB_CURRENT_STATCAST_SILVER_V1"
CURRENT_SILVER_MANIFEST_VERSION = 1
LEGACY_BRONZE_MANIFEST_SHA256 = "fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a"
ELIGIBLE_START = "2023-03-30"
EVIDENCE_END = "2026-08-27"
DEVELOPMENT_END = "2026-08-13"
FINAL_OOT_START = "2026-08-14"
CURRENT_SEASONS = (2025, 2026)
TARGET_SEASONS = (2023, 2024, 2025, 2026)


class CurrentStatcastPipelineError(RuntimeError):
    """The bounded evidence publication is incomplete or inconsistent."""


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentStatcastPipelineError(f"invalid JSON authority: {path}") from exc
    if not isinstance(payload, dict):
        raise CurrentStatcastPipelineError(f"JSON authority is not an object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    body = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temp.write_bytes(body)
    os.replace(temp, path)


def _read_bronze_manifest(root: Path, *, pinned_sha: str | None = None) -> tuple[dict[str, Any], str]:
    path = Path(root) / "manifests" / "bronze-manifest.json"
    if not path.is_file():
        raise CurrentStatcastPipelineError(f"Bronze manifest missing: {path}")
    actual = _sha_file(path)
    if pinned_sha is not None and actual != pinned_sha:
        raise CurrentStatcastPipelineError(
            f"legacy Bronze manifest SHA differs: expected {pinned_sha}, got {actual}"
        )
    manifest = _load_json(path)
    if manifest.get("manifestContract") != BRONZE_MANIFEST_CONTRACT:
        raise CurrentStatcastPipelineError("Bronze manifest contract differs")
    return manifest, actual


def _read_schedule_authority(root: Path) -> tuple[dict[str, Any], str]:
    path = Path(root) / "manifests" / "mlb-stats-api-schedule-authority.json"
    authority = _load_json(path)
    if authority.get("manifestContract") != "MLB_CURRENT_STATCAST_SCHEDULE_AUTHORITY_V1":
        raise CurrentStatcastPipelineError("MLB schedule authority contract differs")
    actual = _sha_file(path)
    completed = authority.get("completedGames")
    if not isinstance(completed, list):
        raise CurrentStatcastPipelineError("MLB schedule authority lacks completedGames")
    return authority, actual


def _load_player_identity(silver_root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    root = Path(silver_root)
    logical = silver_publish.logical_index(root)
    item = logical.get("dim_player")
    if not isinstance(item, Mapping):
        raise CurrentStatcastPipelineError("current dim_player Silver authority is missing")
    registration_sha = str(item.get("currentRegistrationSha256") or "")
    registration = silver_publish._load_registration(root, registration_sha)
    manifest_sha = str(registration.get("publicationManifestSha256") or "")
    verified = silver_publish.verify_silver_table(root, manifest_sha)
    object_path = root / "objects" / "sha256" / manifest_sha / "object.parquet"
    table = pq.read_table(
        object_path,
        columns=["canonicalPlayerId", "mlbamId", "chadwickKeyUuid", "resolutionStatus"],
    )
    mapping: dict[str, str] = {}
    for row in table.to_pylist():
        mlbam = str(row.get("mlbamId") or "").strip()
        canonical = str(row.get("canonicalPlayerId") or "").strip()
        if not mlbam or not canonical or row.get("resolutionStatus") != "MATCHED_EXACT":
            continue
        prior = mapping.get(mlbam)
        if prior is not None and prior != canonical:
            raise CurrentStatcastPipelineError(f"ambiguous governed MLBAM identity: {mlbam}")
        mapping[mlbam] = canonical
    if not mapping:
        raise CurrentStatcastPipelineError("governed MLBAM player identity map is empty")
    return mapping, {
        "tableName": "dim_player",
        "datasetVersionId": registration.get("datasetVersionId"),
        "registrationSha256": registration_sha,
        "publicationManifestSha256": manifest_sha,
        "verifiedRowCount": int(verified.get("rowCount") or table.num_rows),
        "resolvedMlbamCount": len(mapping),
    }


PA_SCHEMA = pa.schema(
    [
        pa.field("canonicalPaId", pa.string(), False),
        pa.field("canonicalGameId", pa.string(), False),
        pa.field("mlbamGamePk", pa.string(), False),
        pa.field("atBatNumber", pa.string(), False),
        pa.field("batterCanonicalPlayerId", pa.string(), False),
        pa.field("pitcherCanonicalPlayerId", pa.string(), False),
        pa.field("batterMlbamId", pa.string(), False),
        pa.field("pitcherMlbamId", pa.string(), False),
        pa.field("season", pa.string(), False),
        pa.field("gameDate", pa.string(), False),
        pa.field("gameType", pa.string()),
        pa.field("homeTeam", pa.string()),
        pa.field("awayTeam", pa.string()),
        pa.field("inning", pa.int64()),
        pa.field("inningTopBot", pa.string()),
        pa.field("outsBeforePa", pa.int64()),
        pa.field("onFirstMlbamIdBeforePa", pa.string()),
        pa.field("onSecondMlbamIdBeforePa", pa.string()),
        pa.field("onThirdMlbamIdBeforePa", pa.string()),
        pa.field("onFirstOccupiedBeforePa", pa.bool_(), False),
        pa.field("onSecondOccupiedBeforePa", pa.bool_(), False),
        pa.field("onThirdOccupiedBeforePa", pa.bool_(), False),
        pa.field("homeScoreBeforePa", pa.int64()),
        pa.field("awayScoreBeforePa", pa.int64()),
        pa.field("batScoreBeforePa", pa.int64()),
        pa.field("fieldScoreBeforePa", pa.int64()),
        pa.field("stand", pa.string()),
        pa.field("pThrows", pa.string()),
        pa.field("paEvent", pa.string(), False),
        pa.field("outcome", pa.string(), False),
        pa.field("pitchCount", pa.int64(), False),
        pa.field("firstPitchNumber", pa.int64(), False),
        pa.field("lastPitchNumber", pa.int64(), False),
        pa.field("terminalSourceRowIndex", pa.int64(), False),
        pa.field("featureCutoffExclusive", pa.string(), False),
        pa.field("sourcePartitionId", pa.string(), False),
        pa.field("sourcePartitionDate", pa.string(), False),
        pa.field("sourceCutoff", pa.string(), False),
        pa.field("sourcePartitionSha256", pa.string(), False),
        pa.field("sourceManifestSha256", pa.string(), False),
        pa.field("finalGameAuthoritySha256", pa.string(), False),
        pa.field("rulesRegime", pa.string(), False),
        pa.field("is2026RulesRegime", pa.bool_(), False),
        pa.field("normalizerContract", pa.string(), False),
    ]
)

PITCH_SCHEMA = pa.schema(
    [
        pa.field(name, pa.string(), nullable=name not in {
            "canonicalPitchId", "canonicalPaId", "canonicalGameId", "mlbamGamePk",
            "atBatNumber", "pitchNumber", "batterCanonicalPlayerId",
            "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId",
            "season", "gameDate", "sourcePartitionId", "sourcePartitionDate",
            "sourceCutoff", "sourcePartitionSha256", "sourceManifestSha256",
            "finalGameAuthoritySha256", "rulesRegime", "normalizerContract",
        })
        for name in (
            "canonicalPitchId", "canonicalPaId", "canonicalGameId", "mlbamGamePk",
            "atBatNumber", "pitchNumber", "batterCanonicalPlayerId",
            "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId", "season",
            "gameDate", "gameType", "inning", "inningTopBot", "stand", "pThrows",
            "homeTeam", "awayTeam", "pitchType", "releaseSpeed", "bbType",
            "pitchResultType", "events", "description", "des", "sourcePartitionId",
            "sourcePartitionDate", "sourceCutoff", "sourcePartitionSha256",
            "sourceManifestSha256", "finalGameAuthoritySha256", "rulesRegime", "normalizerContract",
        )
    ] + [pa.field("is2026RulesRegime", pa.bool_(), False), pa.field("sourceRowIndex", pa.int64(), False)]
)

REJECT_SCHEMA = pa.schema(
    [
        pa.field("mlbamGamePk", pa.string()),
        pa.field("atBatNumber", pa.string()),
        pa.field("gameDate", pa.string()),
        pa.field("batterMlbamId", pa.string()),
        pa.field("pitcherMlbamId", pa.string()),
        pa.field("rawEvent", pa.string()),
        pa.field("normalizedEvent", pa.string()),
        pa.field("observedRawEvents", pa.list_(pa.string()), False),
        pa.field("reason", pa.string(), False),
        pa.field("detail", pa.string(), False),
        pa.field("pitchRowCount", pa.int64(), False),
        pa.field("sourceRowIndices", pa.list_(pa.int64()), False),
        pa.field("sourcePartitionId", pa.string(), False),
        pa.field("sourcePartitionDate", pa.string(), False),
        pa.field("sourceCutoff", pa.string(), False),
        pa.field("sourcePartitionSha256", pa.string(), False),
        pa.field("sourceManifestSha256", pa.string(), False),
        pa.field("finalGameAuthoritySha256", pa.string(), False),
        pa.field("rulesRegime", pa.string()),
        pa.field("is2026RulesRegime", pa.bool_(), False),
        pa.field("normalizerContract", pa.string(), False),
    ]
)


def _parquet_bytes(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> bytes:
    table = pa.Table.from_pylist([dict(row) for row in rows], schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


def _write_object(root: Path, family: str, data: bytes, suffix: str = ".parquet") -> tuple[str, Path]:
    sha = sha256_bytes(data)
    path = Path(root) / "objects" / family / "sha256" / f"{sha}{suffix}"
    if path.exists():
        if _sha_file(path) != sha:
            raise CurrentStatcastPipelineError(f"content-addressed {family} object was modified: {sha}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        temp.write_bytes(data)
        os.replace(temp, path)
    return sha, path


def _receipt_request(
    source: Mapping[str, Any], *, source_manifest_sha: str, schedule_manifest_sha: str,
    identity: Mapping[str, Any], final_game_pks: Iterable[int],
) -> dict[str, Any]:
    return {
        "contract": "MLB_CURRENT_STATCAST_PARTITION_REQUEST_V2",
        "normalizerContract": NORMALIZER_CONTRACT,
        "outputSchemaFingerprints": {
            "plate_appearance": _schema_fingerprint(PA_SCHEMA),
            "pitch": _schema_fingerprint(PITCH_SCHEMA),
            "reject": _schema_fingerprint(REJECT_SCHEMA),
        },
        "sourcePartitionId": source["partitionId"],
        "sourcePartitionSha256": source["fileSha256"],
        "sourceManifestSha256": source_manifest_sha,
        "sourceCutoff": source.get("retrievalUtc") or source.get("recordedAtUtc"),
        "scheduleManifestSha256": schedule_manifest_sha,
        "finalGamePks": sorted(int(value) for value in final_game_pks),
        "identityRegistrationSha256": identity["registrationSha256"],
    }


def _schema_fingerprint(schema: pa.Schema) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            [(field.name, str(field.type), field.nullable) for field in schema]
        )
    )


def _verify_receipt(root: Path, receipt: Mapping[str, Any]) -> bool:
    if receipt.get("receiptContract") != "MLB_CURRENT_STATCAST_PARTITION_RECEIPT_V2":
        return False
    request = receipt.get("request")
    if not isinstance(request, Mapping):
        return False
    if receipt.get("requestSha256") != sha256_bytes(canonical_json_bytes(request)):
        return False
    if (
        not isinstance(receipt.get("rawGamePks"), list)
        or type(receipt.get("rawRowsMissingGamePk")) is not int
        or not isinstance(receipt.get("rawIdentityCounts"), Mapping)
    ):
        return False
    expected_schemas = {
        "plate_appearance": PA_SCHEMA,
        "pitch": PITCH_SCHEMA,
        "reject": REJECT_SCHEMA,
    }
    try:
        final_game_pks = sorted(int(value) for value in request["finalGamePks"])
        expected_lineage = {
            "sourcePartitionId": str(request["sourcePartitionId"]),
            "sourcePartitionDate": str(receipt["partitionDate"]),
            "sourceCutoff": str(request["sourceCutoff"]),
            "sourcePartitionSha256": str(request["sourcePartitionSha256"]),
            "sourceManifestSha256": str(request["sourceManifestSha256"]),
            "finalGameAuthoritySha256": sha256_bytes(
                canonical_json_bytes(
                    {
                        "contract": FINAL_GAME_AUTHORITY_CONTRACT,
                        "partitionDate": str(receipt["partitionDate"]),
                        "finalGamePks": final_game_pks,
                    }
                )
            ),
            "normalizerContract": NORMALIZER_CONTRACT,
        }
    except (KeyError, TypeError, ValueError):
        return False
    object_rows: dict[str, int] = {}
    for family, expected_schema in expected_schemas.items():
        item = receipt.get("objects", {}).get(family)
        if not isinstance(item, Mapping):
            return False
        path = Path(root) / str(item.get("relativePath") or "")
        if (
            not path.is_file()
            or _sha_file(path) != item.get("sha256")
            or path.stat().st_size != item.get("byteCount")
            or item.get("schemaFingerprint") != _schema_fingerprint(expected_schema)
        ):
            return False
        parquet = pq.ParquetFile(path)
        row_count = int(parquet.metadata.num_rows)
        if row_count != item.get("rowCount") or parquet.schema_arrow != expected_schema:
            return False
        if row_count:
            lineage_table = pq.read_table(path, columns=list(expected_lineage))
            for name, expected in expected_lineage.items():
                if set(lineage_table[name].to_pylist()) != {expected}:
                    return False
            if family in {"plate_appearance", "pitch"}:
                game_values = pq.read_table(path, columns=["mlbamGamePk"])["mlbamGamePk"].to_pylist()
                if any(int(value) not in final_game_pks for value in game_values):
                    return False
        object_rows[family] = row_count
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping):
        return False
    try:
        return (
            int(counts["sourcePitchRows"])
            == int(counts["acceptedPitchRows"]) + int(counts["rejectedPitchRows"])
            and int(counts["sourcePlateAppearanceGroups"])
            == int(counts["acceptedPlateAppearances"]) + int(counts["rejectedPlateAppearances"])
            and object_rows["pitch"] == int(counts["acceptedPitchRows"])
            and object_rows["plate_appearance"] == int(counts["acceptedPlateAppearances"])
            and object_rows["reject"] == int(counts["rejectedPlateAppearances"])
            and int(receipt.get("sourceRowCount") or 0) == int(counts["sourcePitchRows"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def _partition_source_records(
    manifest: Mapping[str, Any], *, start: str, end: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in manifest.get("partitions", []):
        if not isinstance(raw, Mapping) or raw.get("source") != "statcast" or raw.get("scope") != "regular":
            continue
        day = str((raw.get("query") or {}).get("date") or "")
        if day < start or day > end:
            continue
        if raw.get("status") not in {"COMPLETE", "COMPLETE_EMPTY"}:
            raise CurrentStatcastPipelineError(
                f"source partition is not complete: {raw.get('partitionId')} status={raw.get('status')}"
            )
        records.append(dict(raw))
    records.sort(key=lambda item: str((item.get("query") or {}).get("date") or ""))
    return records


def _read_csv(path: Path, source: Mapping[str, Any]) -> pa.Table:
    try:
        table = pacsv.read_csv(path, read_options=pacsv.ReadOptions(block_size=1 << 24))
    except pa.ArrowInvalid as exc:
        if source.get("status") != "COMPLETE_EMPTY" or int(source.get("rowCount") or 0) != 0:
            raise CurrentStatcastPipelineError(
                f"nonempty Bronze partition is not parseable: {source.get('partitionId')}"
            ) from exc
        # A governed COMPLETE_EMPTY off day preserves its exact header.
        header = path.read_bytes().lstrip(b"\xef\xbb\xbf").splitlines()[0].decode("utf-8")
        names = [value.strip().strip('"') for value in header.split(",")]
        table = pa.table({name: pa.array([], type=pa.string()) for name in names})
    names = list(table.column_names)
    schema_fingerprint = sha256_bytes(
        canonical_json_bytes(
            names if table.num_rows == 0
            else [{"name": field.name, "type": str(field.type)} for field in table.schema]
        )
    )
    if (
        table.num_rows != int(source.get("rowCount") or 0)
        or names != list(source.get("columnNames") or [])
        or schema_fingerprint != source.get("schemaFingerprint")
    ):
        raise CurrentStatcastPipelineError(
            f"Bronze CSV receipt differs from parsed bytes: {source.get('partitionId')}"
        )
    return table


def _current_expected_by_date(schedule: Mapping[str, Any]) -> tuple[dict[str, set[int]], dict[int, int]]:
    by_date: dict[str, set[int]] = defaultdict(set)
    by_season: Counter[int] = Counter()
    for game in schedule.get("completedGames", []):
        season = int(game["season"])
        if season not in CURRENT_SEASONS:
            continue
        game_pk = int(game["gamePk"])
        by_date[str(game["gameDate"])].add(game_pk)
        by_season[season] += 1
    return by_date, dict(by_season)


def _game_pk(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else None


def _mlbam_id(value: Any) -> str | None:
    parsed = _game_pk(value)
    return str(parsed) if parsed is not None else None


def build_current_silver(
    *,
    legacy_bronze_root: Path,
    current_bronze_root: Path,
    existing_silver_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Build and publish the complete eligible 2023--2026 current PA evidence."""

    legacy, legacy_sha = _read_bronze_manifest(
        Path(legacy_bronze_root), pinned_sha=LEGACY_BRONZE_MANIFEST_SHA256
    )
    current, current_sha = _read_bronze_manifest(Path(current_bronze_root))
    schedule, schedule_sha = _read_schedule_authority(Path(current_bronze_root))
    resolved_mlbam, identity = _load_player_identity(Path(existing_silver_root))
    expected_by_date, expected_by_season = _current_expected_by_date(schedule)
    if set(expected_by_season) != set(CURRENT_SEASONS):
        raise CurrentStatcastPipelineError(
            f"schedule authority lacks both current seasons: {sorted(expected_by_season)}"
        )

    # The frozen 2019--2024 Silver/Gold authorities are reused later as exact
    # historical inputs.  Only the additive 2025--2026 Bronze partitions are
    # normalized here, so no valid historical Silver object is rebuilt.
    sources: list[tuple[Path, dict[str, Any], str, str]] = []
    for record in _partition_source_records(current, start="2025-01-01", end=EVIDENCE_END):
        sources.append((Path(current_bronze_root), record, current_sha, "MLB_STATS_API"))
    if not sources:
        raise CurrentStatcastPipelineError("no governed Statcast partitions were selected")

    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    partition_receipts: list[dict[str, Any]] = []
    accepted_pa_ids: set[str] = set()
    accepted_game_pks: dict[int, set[int]] = defaultdict(set)
    raw_game_pks: dict[int, set[int]] = defaultdict(set)
    raw_rows_missing_game_pk: Counter[int] = Counter()
    event_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    reject_event_counts: Counter[str] = Counter()
    reject_reason_counts: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    totals_by_season: dict[int, Counter[str]] = defaultdict(Counter)
    identity_counts_by_season: dict[int, Counter[str]] = defaultdict(Counter)
    source_natural_key_duplicates: Counter[int] = Counter()

    for source_root, source, source_manifest_sha, final_basis in sources:
        day = str((source.get("query") or {}).get("date") or "")
        season = int(day[:4])
        source_path = source_root / str(source.get("relativePath") or "")
        if not source_path.is_file() or _sha_file(source_path) != source.get("fileSha256"):
            raise CurrentStatcastPipelineError(f"source partition SHA mismatch: {source.get('partitionId')}")
        final_games = expected_by_date.get(day, set())
        request = _receipt_request(
            source,
            source_manifest_sha=source_manifest_sha,
            schedule_manifest_sha=schedule_sha,
            identity=identity,
            final_game_pks=final_games,
        )
        request_sha = sha256_bytes(canonical_json_bytes(request))
        receipt_path = output / "partition-receipts" / "sha256" / f"{request_sha}.json"
        receipt: dict[str, Any] | None = None
        if receipt_path.is_file():
            candidate = _load_json(receipt_path)
            if candidate.get("request") == request and _verify_receipt(output, candidate):
                receipt = candidate
        if receipt is None:
            table = _read_csv(source_path, source)
            partition_raw_game_pks: set[int] = set()
            partition_rows_missing_game_pk = 0
            for raw_game_pk in table["game_pk"].to_pylist():
                parsed_game_pk = _game_pk(raw_game_pk)
                if parsed_game_pk is None:
                    partition_rows_missing_game_pk += 1
                else:
                    partition_raw_game_pks.add(parsed_game_pk)
            raw_identity_counts: Counter[str] = Counter()
            for role, column in (("Batter", "batter"), ("Pitcher", "pitcher")):
                for raw_value in table[column].to_pylist():
                    mlbam = _mlbam_id(raw_value)
                    if mlbam is None:
                        raw_identity_counts[f"missing{role}MlbamPitchRows"] += 1
                    elif mlbam not in resolved_mlbam:
                        raw_identity_counts[f"unresolved{role}MlbamPitchRows"] += 1
            normalized = normalize_current_partition(
                table,
                partition_id=str(source["partitionId"]),
                partition_date=day,
                source_cutoff=str(request["sourceCutoff"]),
                source_partition_sha256=str(source["fileSha256"]),
                source_manifest_sha256=source_manifest_sha,
                final_game_pks=final_games,
                resolved_mlbam=resolved_mlbam,
            )
            for row in normalized.fact_pa:
                row["featureCutoffExclusive"] = row["gameDate"]
            objects: dict[str, dict[str, Any]] = {}
            for family, rows, schema in (
                ("plate_appearance", normalized.fact_pa, PA_SCHEMA),
                ("pitch", normalized.fact_pitch, PITCH_SCHEMA),
                ("reject", normalized.rejects, REJECT_SCHEMA),
            ):
                data = _parquet_bytes(rows, schema)
                sha, path = _write_object(output, family, data)
                objects[family] = {
                    "sha256": sha,
                    "relativePath": path.relative_to(output).as_posix(),
                    "rowCount": len(rows),
                    "byteCount": len(data),
                    "schemaFingerprint": sha256_bytes(
                        canonical_json_bytes([(field.name, str(field.type), field.nullable) for field in schema])
                    ),
                }
            receipt = {
                "receiptContract": "MLB_CURRENT_STATCAST_PARTITION_RECEIPT_V2",
                "requestSha256": request_sha,
                "request": request,
                "partitionDate": day,
                "season": season,
                "finalAuthorityBasis": final_basis,
                "sourceStatus": source.get("status"),
                "sourceRowCount": int(source.get("rowCount") or 0),
                "rawGamePks": sorted(partition_raw_game_pks),
                "rawRowsMissingGamePk": partition_rows_missing_game_pk,
                "rawIdentityCounts": dict(sorted(raw_identity_counts.items())),
                "objects": objects,
                "counts": normalized.counts,
            }
            _write_json_atomic(receipt_path, receipt)

        for raw_game_pk in receipt.get("rawGamePks", []):
            parsed_game_pk = _game_pk(raw_game_pk)
            if parsed_game_pk is not None:
                raw_game_pks[season].add(parsed_game_pk)
        raw_rows_missing_game_pk[season] += int(receipt.get("rawRowsMissingGamePk") or 0)
        for key, value in (receipt.get("rawIdentityCounts") or {}).items():
            identity_counts_by_season[season][str(key)] += int(value)
        source_natural_key_duplicates[season] += int(source.get("naturalKeyDuplicateCount") or 0)

        pa_item = receipt["objects"]["plate_appearance"]
        pa_table = pq.read_table(output / pa_item["relativePath"], columns=["canonicalPaId", "mlbamGamePk", "paEvent", "outcome"])
        for row in pa_table.to_pylist():
            pa_id = str(row["canonicalPaId"])
            if pa_id in accepted_pa_ids:
                raise CurrentStatcastPipelineError(f"duplicate accepted canonical PA identity: {pa_id}")
            accepted_pa_ids.add(pa_id)
            accepted_game_pks[season].add(int(row["mlbamGamePk"]))
            event_counts[str(row["paEvent"])] += 1
            class_counts[str(row["outcome"])] += 1
        reject_item = receipt["objects"]["reject"]
        reject_table = pq.read_table(output / reject_item["relativePath"], columns=["normalizedEvent", "reason"])
        for row in reject_table.to_pylist():
            reject_event_counts[str(row.get("normalizedEvent") or "<NULL>")] += 1
            reject_reason_counts[str(row["reason"])] += 1
        counts = receipt["counts"]
        for key in (
            "sourcePitchRows", "acceptedPitchRows", "rejectedPitchRows",
            "sourcePlateAppearanceGroups", "acceptedPlateAppearances", "rejectedPlateAppearances",
        ):
            totals[key] += int(counts.get(key) or 0)
            totals_by_season[season][key] += int(counts.get(key) or 0)
        partition_receipts.append(receipt)

    current_coverage: dict[str, Any] = {}
    incomplete: list[str] = []
    for season in CURRENT_SEASONS:
        expected = set()
        for day, game_pks in expected_by_date.items():
            if int(day[:4]) == season:
                expected.update(game_pks)
        raw_represented = raw_game_pks.get(season, set())
        accepted_represented = accepted_game_pks.get(season, set())
        accepted_dates = sorted(
            str(receipt["partitionDate"])
            for receipt in partition_receipts
            if int(receipt["season"]) == season
            and int(receipt["objects"]["plate_appearance"]["rowCount"]) > 0
        )
        missing = sorted(expected - raw_represented)
        unexpected = sorted(raw_represented - expected)
        current_coverage[str(season)] = {
            "scheduledRegularSeasonRecords": next(
                int(item["scheduledGameCount"]) for item in schedule["seasonCounts"] if int(item["season"]) == season
            ),
            "finalGamesExpected": len(expected),
            "gamesRepresented": len(raw_represented),
            "gamesWithAcceptedFacts": len(accepted_represented),
            "gamesWithOnlyRejectedFacts": sorted(raw_represented - accepted_represented),
            "gamesMissingFromStatcast": missing,
            "unexpectedStatcastGames": unexpected,
            "rawRowsMissingGamePk": int(raw_rows_missing_game_pk[season]),
            "sourceNaturalKeyDuplicateRows": int(source_natural_key_duplicates[season]),
            "identityRowCounts": dict(sorted(identity_counts_by_season[season].items())),
            "normalizationCounts": dict(sorted(totals_by_season[season].items())),
            "earliestAcceptedDate": accepted_dates[0] if accepted_dates else None,
            "latestAcceptedDate": accepted_dates[-1] if accepted_dates else None,
        }
        if missing or unexpected:
            incomplete.append(
                f"{season}: missing={len(missing)} unexpected={len(unexpected)}"
            )
    if incomplete:
        raise CurrentStatcastPipelineError(
            "current Statcast game completeness failed: " + "; ".join(incomplete)
        )
    if totals["sourcePitchRows"] != totals["acceptedPitchRows"] + totals["rejectedPitchRows"]:
        raise CurrentStatcastPipelineError("pitch row accounting does not reconcile")
    if totals["sourcePlateAppearanceGroups"] != totals["acceptedPlateAppearances"] + totals["rejectedPlateAppearances"]:
        raise CurrentStatcastPipelineError("PA group accounting does not reconcile")

    manifest = {
        "manifestContract": CURRENT_SILVER_CONTRACT,
        "manifestVersion": CURRENT_SILVER_MANIFEST_VERSION,
        "datasetId": CURRENT_DATASET_ID,
        "status": "COMPLETE",
        "quarantine": "QUARANTINED",
        "selectable": False,
        "modelEligible": False,
        "approvedForTraining": False,
        "targetClassOrder": list(PA_CLASS_ORDER),
        "targetEventMap": dict(sorted(EVENT_TO_OUTCOME.items())),
        "normalizerContract": NORMALIZER_CONTRACT,
        "dateCoverage": {"earliestDate": "2025-03-18", "latestDate": EVIDENCE_END},
        "temporalContract": {
            "intendedCombinedEligibleEvidence": [ELIGIBLE_START, EVIDENCE_END],
            "intendedCombinedDevelopmentSelection": [ELIGIBLE_START, DEVELOPMENT_END],
            "intendedCombinedFinalOot": [FINAL_OOT_START, EVIDENCE_END],
            "featureCutoffRule": "source.gameDate < target.gameDate; same-date history excluded",
        },
        "sourceAuthorities": {
            "legacyAdvancedBronzeManifestSha256": legacy_sha,
            "currentBronzeManifestSha256": current_sha,
            "mlbScheduleAuthoritySha256": schedule_sha,
            "playerIdentity": identity,
        },
        "coverage": current_coverage,
        "counts": dict(sorted(totals.items())),
        "countsBySeason": {
            str(season): dict(sorted(totals_by_season[season].items()))
            for season in CURRENT_SEASONS
        },
        "acceptedMappedEventCounts": dict(sorted(event_counts.items())),
        "acceptedClassCounts": {name: int(class_counts[name]) for name in PA_CLASS_ORDER},
        "rejectedEventCounts": dict(sorted(reject_event_counts.items())),
        "rejectReasonCounts": dict(sorted(reject_reason_counts.items())),
        "duplicateCanonicalPaIds": 0,
        "partitions": partition_receipts,
        "rights": {
            "source": "MLB Advanced Media / Baseball Savant",
            "classification": ["PUBLIC RESEARCH SOURCE", "ATTRIBUTION REQUIRED", "COMMERCIAL RIGHTS UNCLEAR"],
            "allowedUses": ["LOCAL_PRIVATE_MODEL_DEVELOPMENT", "READ_ONLY_REGISTRATION"],
            "prohibitedUses": ["PUBLIC_RAW_REDISTRIBUTION", "RAW_DATA_RESALE", "UNREVIEWED_COMMERCIAL_REDISTRIBUTION"],
        },
        "modelsFitted": 0,
    }
    body = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(body)
    publication = output / "publications" / "sha256" / manifest_sha
    publication.mkdir(parents=True, exist_ok=True)
    manifest_path = publication / "manifest.json"
    if manifest_path.exists() and manifest_path.read_bytes() != body:
        raise CurrentStatcastPipelineError("content-addressed current Silver manifest differs")
    manifest_path.write_bytes(body)
    _write_json_atomic(output / "current.json", {
        "datasetId": CURRENT_DATASET_ID,
        "manifestSha256": manifest_sha,
        "manifestRelativePath": manifest_path.relative_to(output).as_posix(),
    })
    return {**manifest, "manifestSha256": manifest_sha, "manifestPath": str(manifest_path)}


def verify_current_silver(output_root: Path, manifest_sha256: str | None = None) -> dict[str, Any]:
    root = Path(output_root).resolve()
    if manifest_sha256 is None:
        locator = _load_json(root / "current.json")
        manifest_sha256 = str(locator.get("manifestSha256") or "")
    path = root / "publications" / "sha256" / str(manifest_sha256) / "manifest.json"
    if not path.is_file() or _sha_file(path) != manifest_sha256:
        raise CurrentStatcastPipelineError("current Silver manifest is missing or not content-addressed")
    manifest = _load_json(path)
    if manifest.get("manifestContract") != CURRENT_SILVER_CONTRACT or manifest.get("status") != "COMPLETE":
        raise CurrentStatcastPipelineError("current Silver manifest contract/status differs")
    if manifest.get("modelsFitted") != 0:
        raise CurrentStatcastPipelineError("current Silver manifest claims a model fit")
    pa_ids: set[str] = set()
    rows = 0
    for receipt in manifest.get("partitions", []):
        if not _verify_receipt(root, receipt):
            raise CurrentStatcastPipelineError(f"partition receipt object failed verification: {receipt.get('requestSha256')}")
        item = receipt["objects"]["plate_appearance"]
        table = pq.read_table(root / item["relativePath"], columns=["canonicalPaId"])
        for value in table["canonicalPaId"].to_pylist():
            if value in pa_ids:
                raise CurrentStatcastPipelineError(f"duplicate canonical PA during verification: {value}")
            pa_ids.add(value)
        rows += table.num_rows
    if rows != int(manifest["counts"]["acceptedPlateAppearances"]):
        raise CurrentStatcastPipelineError("verified PA row count differs from manifest")
    return {
        "datasetId": manifest["datasetId"],
        "manifestSha256": manifest_sha256,
        "manifestPath": str(path),
        "plateAppearanceRows": rows,
        "partitionCount": len(manifest["partitions"]),
        "dateCoverage": manifest["dateCoverage"],
        "verified": True,
    }


__all__ = [
    "CURRENT_DATASET_ID",
    "CURRENT_SILVER_CONTRACT",
    "CurrentStatcastPipelineError",
    "build_current_silver",
    "verify_current_silver",
]

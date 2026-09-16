"""Additive NFL registration in the existing Sports Data Warehouse registry.

NFL foundations are catalog-visible but deliberately inactive and cannot be
selected by the MLB workflow.  This module writes the existing sport-neutral
registry tables; it does not create a second registry or an NFL modeling
project.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..persistence.db import Database, json_dumps, now_iso
from ..sports_datasets.registry import SportsDatasetRegistry


NFL_DATASET_ID = "asp.nfl.gold-data-foundation.v1"
REGISTRATION_NAMESPACE = uuid.UUID("5e8978f5-f105-45d1-8a66-c49511420520")


class NflRegistryError(RuntimeError):
    """A verified NFL foundation cannot be registered safely."""


def _registration_id(manifest_sha: str) -> str:
    return f"nfl-foundation-{uuid.uuid5(REGISTRATION_NAMESPACE, manifest_sha)}"


def _table_map(objects: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(item["manifest"]["tableName"]): item for item in objects}


def _row_count(tables: Mapping[str, Mapping[str, Any]], name: str) -> int:
    item = tables.get(name)
    return int(item["manifest"]["rowCount"]) if item else 0


def register_nfl_foundation(
    database: Database,
    verified: Mapping[str, Any],
    *,
    user_id: str,
    logical_root: str,
) -> dict[str, Any]:
    manifest = verified.get("manifest")
    objects = verified.get("objects")
    if not isinstance(manifest, Mapping) or not isinstance(objects, list):
        raise NflRegistryError("verified NFL foundation is incomplete")
    if manifest.get("datasetId") != NFL_DATASET_ID:
        raise NflRegistryError("NFL foundation dataset identity differs")
    governance = manifest.get("governance") or {}
    if governance.get("workspaceActivationEligible") is not False:
        raise NflRegistryError("NFL foundation must be read-only in the workspace")
    if governance.get("modelFitOccurred") is not False:
        raise NflRegistryError("NFL foundation reports model execution")

    manifest_sha = str(manifest["manifestSha256"])
    registration_id = _registration_id(manifest_sha)
    tables = _table_map(objects)
    required = {"dim_nfl_game", "fact_nfl_play", "gold_nfl_game_pregame_v1", "gold_nfl_play_state_v1"}
    missing = sorted(required - set(tables))
    if missing:
        raise NflRegistryError(f"NFL foundation registration lacks required tables: {missing}")
    coverage = dict(manifest.get("coverage") or {})
    seasons = [int(value) for value in coverage.get("seasons") or []]
    if not seasons:
        raise NflRegistryError("NFL foundation registration lacks season coverage")
    date_start = str(coverage.get("minimumDate") or f"{min(seasons)}-01-01")
    date_end = str(coverage.get("maximumDate") or f"{max(seasons)}-12-31")
    totals = {
        "tables": len(objects),
        "canonicalRows": sum(int(item["manifest"]["rowCount"]) for item in objects),
        "games": _row_count(tables, "dim_nfl_game"),
        "plays": _row_count(tables, "fact_nfl_play"),
        "drives": _row_count(tables, "fact_nfl_drive"),
        "teamGameRows": _row_count(tables, "fact_nfl_team_game"),
        "playerGameRows": _row_count(tables, "fact_nfl_player_game"),
        "goldPregameGames": _row_count(tables, "gold_nfl_game_pregame_v1"),
        "goldPlayStates": _row_count(tables, "gold_nfl_play_state_v1"),
    }
    metadata = {
        "adapter": "ASP_NFL_DATA_FOUNDATION_V1",
        "authorityLayer": "BRONZE_SILVER_GOLD_FOUNDATION",
        "authorityState": "READ_ONLY_RESEARCH",
        "workspaceActivationEligible": False,
        "compatibleWorkflowIds": ["nfl-forecasting"],
        "sourceProvider": "nflverse",
        "sourceManifestSha256": manifest.get("sourceManifestSha256"),
        "sourceFamilies": coverage.get("sourceFamilies") or [],
        "dateCoverage": {"earliestDate": date_start, "latestDate": date_end},
        "featureFamilies": manifest.get("featureFamilies") or {},
        "featureEraContracts": coverage.get("featureEraContracts") or {},
        "quality": manifest.get("quality") or {},
        "modelingStatus": "NOT_CONNECTED",
        "modelFitOccurred": False,
        "manifestMetadata": {"syncHealth": coverage.get("syncHealth")},
    }
    registered_at = now_iso()
    registration_disposition = "CREATED"
    with database.transaction() as connection:
        existing = connection.execute(
            "SELECT * FROM sports_dataset_registrations WHERE manifest_sha = ?", (manifest_sha,)
        ).fetchone()
        if existing is not None:
            if existing["registration_id"] != registration_id or existing["dataset_id"] != NFL_DATASET_ID:
                raise NflRegistryError("existing NFL registration conflicts with immutable identity")
            registration_disposition = "REUSED"
            connection.execute(
                """
                UPDATE sports_dataset_registrations
                SET last_validated_at = ?, validation_status = 'VALID', active = 0,
                    totals_json = ?, seasons_json = ?, evidence_coverage_json = ?, metadata_json = ?
                WHERE registration_id = ?
                """,
                (
                    registered_at, json_dumps(totals, {}),
                    json_dumps([{"season": value} for value in seasons], []),
                    json_dumps(coverage, {}), json_dumps(metadata, {}), registration_id,
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO sports_dataset_registrations (
                  registration_id, dataset_id, dataset_version_id, manifest_id, manifest_sha,
                  package_id, sport, league, evidence_cutoff, published_at, logical_package_root,
                  validation_status, registered_at, last_validated_at, registered_by, rights_status,
                  limitation_count, active, totals_json, seasons_json, evidence_coverage_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VALID', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    registration_id, NFL_DATASET_ID, manifest["datasetVersionId"],
                    f"asp-nfl-foundation-{manifest_sha}", manifest_sha,
                    f"asp-nfl-foundation-{manifest_sha}", "Professional Football", "NFL",
                    date_end, manifest["publishedAt"], logical_root,
                    registered_at, registered_at, user_id, "LOCAL_PRIVATE_RESEARCH",
                    len(manifest.get("limitations") or []), json_dumps(totals, {}),
                    json_dumps([{"season": value} for value in seasons], []),
                    json_dumps(coverage, {}), json_dumps(metadata, {}),
                ),
            )

        for table in (
            "sports_dataset_limitations", "sports_dataset_rights", "sports_dataset_temporal_folds",
            "sports_dataset_populations", "sports_dataset_schemas", "sports_dataset_partitions",
        ):
            connection.execute(f"DELETE FROM {table} WHERE registration_id = ?", (registration_id,))

        for item in objects:
            object_manifest = item["manifest"]
            table_name = str(object_manifest["tableName"])
            object_sha = str(object_manifest["manifestSha256"])
            # ``sports_dataset_partitions.partition_id`` is a global primary
            # key, while an immutable object may legitimately be reused by a
            # later foundation manifest.  The registry row therefore needs a
            # registration-scoped identity.  The exact content identity stays
            # separately bound in the object-addressed logical URI and the
            # governance checksum, so namespacing does not weaken lineage.
            registry_partition_id = f"{registration_id}:{object_sha}"
            object_coverage = object_manifest.get("coverage") or {}
            object_seasons = object_coverage.get("seasons") or []
            minimum_season = int(
                object_coverage.get("minimumSeason")
                or (min(object_seasons) if object_seasons else min(seasons))
            )
            schema = object_manifest.get("schema") or []
            connection.execute(
                """
                INSERT INTO sports_dataset_partitions (
                  partition_id, registration_id, family, season, month, logical_uri,
                  row_count, byte_count, minimum_date, maximum_date, schema_id,
                  physical_schema_fingerprint, file_sha, source_key, source_version_id,
                  original_source_logical_identity, checkpoint_lineage_id, governance_checksum,
                  target_eligibility_json, temporal_classification_json, rights_ids_json, physical_schema_json
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    registry_partition_id, registration_id, table_name, minimum_season,
                    f"nfl-foundation://sha256/{manifest_sha}/objects/{object_sha}",
                    int(object_manifest["rowCount"]), int(object_manifest["byteCount"]),
                    object_coverage.get("minimumDate"), object_coverage.get("maximumDate"),
                    f"{table_name}:{object_manifest['schemaSha256']}", object_manifest["schemaSha256"],
                    object_manifest["fileSha256"], "nflverse", str(manifest.get("sourceManifestSha256")),
                    table_name, object_sha,
                    json_dumps(["RESEARCH_ONLY"] if object_manifest["layer"] == "GOLD" else [], []),
                    json_dumps([{"sourceCutoff": "CONTRACT_BOUND"}], []),
                    json_dumps([right.get("rightsControlId") for right in manifest.get("rights") or []], []),
                    json_dumps(schema, []),
                ),
            )
            connection.execute(
                """
                INSERT INTO sports_dataset_schemas (
                  registration_id, family, logical_schema_version, compatible_partition_count,
                  physical_variant_count, fields_json, physical_variants_json
                ) VALUES (?, ?, ?, 1, 1, ?, ?)
                """,
                (
                    registration_id, table_name,
                    str((object_manifest.get("tableContract") or {}).get("contract") or "ASP_NFL_TABLE_V1"),
                    json_dumps(schema, []), json_dumps([{"schemaSha256": object_manifest["schemaSha256"]}], []),
                ),
            )

        populations = (
            (
                "LONG_HISTORY_CORE",
                totals["goldPregameGames"],
                {"gameType": ["REG", "POST", "WC", "DIV", "CON", "SB"]},
            ),
            ("PLAY_STATE", totals["goldPlayStates"], {"eligiblePlay": True}),
            ("CURRENT_SEASON", int(coverage.get("currentSeasonScheduledGames") or 0), {"season": 2026}),
        )
        for precedence, (population_id, rows, predicate) in enumerate(populations, start=1):
            connection.execute(
                """
                INSERT INTO sports_dataset_populations (
                  registration_id, population_id, row_count, predicate_json, allowed_uses_json,
                  prohibited_uses_json, temporal_meaning, evaluation_precedence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    registration_id, population_id, rows, json_dumps(predicate, {}),
                    json_dumps(["LOCAL_PRIVATE_RESEARCH", "FUTURE_CHRONOLOGICAL_VALIDATION"], []),
                    json_dumps(["MODEL_PROMOTION", "PUBLIC_REDISTRIBUTION", "LIVE_FORECAST_CONTROL"], []),
                    "POINT_IN_TIME_CONTRACT_REQUIRED_BEFORE_MODELING", precedence,
                ),
            )

        for right in manifest.get("rights") or []:
            connection.execute(
                """
                INSERT INTO sports_dataset_rights (
                  registration_id, rights_control_id, display_name, source_name, status,
                  allowed_uses_json, prohibited_uses_json, attribution, controls_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    registration_id, right["rightsControlId"], right["displayName"],
                    right["sourceName"], right["status"], json_dumps(right.get("allowedUses") or [], []),
                    json_dumps(right.get("prohibitedUses") or [], []), right["attribution"],
                    json_dumps(right.get("controls") or {}, {}), json_dumps(right.get("metadata") or {}, {}),
                ),
            )
        for limitation in manifest.get("limitations") or []:
            connection.execute(
                "INSERT INTO sports_dataset_limitations (registration_id, limitation_id, scope, description) VALUES (?, ?, ?, ?)",
                (registration_id, limitation["limitationId"], limitation["scope"], limitation["description"]),
            )

    registry = SportsDatasetRegistry(database)
    registration = registry.get(registration_id)
    if registration is None or registration.get("active") not in {0, False}:
        raise NflRegistryError("NFL foundation did not persist as an inactive registration")
    # Prove global active MLB authority was not changed by this additive write.
    active = registry.get_active()
    if active is not None and active.get("league") != "MLB":
        raise NflRegistryError("NFL registration changed the workspace-global active authority")
    return {
        "status": "COMPLETE", "registrationId": registration_id,
        "registrationDisposition": registration_disposition,
        "datasetVersionId": manifest["datasetVersionId"], "active": False,
        "modelingProjectCreated": False, "modelsFitted": 0,
    }


__all__ = ["NFL_DATASET_ID", "NflRegistryError", "register_nfl_foundation"]

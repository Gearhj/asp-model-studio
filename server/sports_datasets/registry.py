from __future__ import annotations

from collections import OrderedDict
from typing import Any, Mapping, Sequence

from ..persistence.db import Database, json_dumps, now_iso
from .constants import (
    EXPECTED_PROHIBITED_USES,
    LOGICAL_PACKAGE_ROOT,
    MANIFEST_SHA,
    PROJECT_ID,
    PROJECT_NAME,
    REGISTRATION_ID,
)
from .consumer import ManifestValidationError, ValidatedPackage
from .feature_audit import build_mlb_pa_feature_audit


IDENTITY_BRIDGE_BLOCKER = {
    "limitationId": "MLB_PA_PLAYER_PRIOR_IDENTITY_BRIDGE_ABSENT",
    "scope": "CONSUMER_MODELING",
    "description": (
        "The exchange does not contain a governed cross-family identity bridge from "
        "plate-appearance batter/pitcher identifiers to player_prior identifiers; exact "
        "Y−1 joins are therefore blocked rather than inferred."
    ),
    "blocks": ["MLB_PA_FEATURE_VIEW_V1", "plate_appearance_modeling"],
}


def _schema_union(family: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for variant in family["physical_variants"]:
        for field in variant["fields"]:
            name = str(field["name"])
            if name not in fields:
                fields[name] = dict(field)
            else:
                existing_types = fields[name].setdefault("physicalDtypes", [fields[name]["dtype"]])
                if field["dtype"] not in existing_types:
                    existing_types.append(field["dtype"])
    return list(fields.values())


def _dataset_totals(validated: ValidatedPackage) -> dict[str, Any]:
    manifest = validated.manifest
    seasons = manifest["seasons"]
    family_rows = {item["family_id"]: item["row_count"] for item in manifest["data_families"]}
    return {
        "packageFiles": 335,
        "parquetFiles": manifest["totals"]["parquet_files"],
        "rows": manifest["totals"]["rows"],
        "parquetBytes": manifest["totals"]["parquet_bytes"],
        "games": sum(item["games"] for item in seasons),
        "plateAppearances": sum(item["plate_appearances"] for item in seasons),
        "transitions": sum(item["transitions"] for item in seasons),
        "starterTargets": sum(item["starter_targets"] for item in seasons),
        "bullpenAppearances": sum(item["bullpen_appearances"] for item in seasons),
        "playerPriors": family_rows["player_prior"],
        "partitions": len(manifest["partitions"]),
        "playerIdentityCoverage": manifest["identity_coverage"]["primary_2023_2025"]["exact_reference_rate"],
    }


def _evidence_coverage(manifest: Mapping[str, Any]) -> dict[str, Any]:
    seasons = manifest["seasons"]
    return {
        "lineups": {
            "status": "PARTIAL_RETROSPECTIVE_TIMING_RISK",
            "bySeason": [
                {
                    "season": item["season"],
                    "covered": item["complete_lineup_coverage"]["covered"],
                    "eligible": item["complete_lineup_coverage"]["eligible"],
                    "ratio": item["complete_lineup_coverage"]["ratio"],
                }
                for item in seasons
            ],
        },
        "starters": {"status": "RETROSPECTIVE_TARGET_ONLY", "rows": sum(item["starter_targets"] for item in seasons)},
        "bullpen": {"status": "RETROSPECTIVE_TARGET_ONLY", "rows": sum(item["bullpen_appearances"] for item in seasons)},
        "weather": {
            "status": "RETROSPECTIVE_TIMING_RISK",
            "bySeason": [
                {
                    "season": item["season"],
                    "covered": item["weather_coverage"]["covered"],
                    "eligible": item["weather_coverage"]["eligible"],
                    "ratio": item["weather_coverage"]["ratio"],
                }
                for item in seasons
            ],
        },
        "playerIdentity": {
            "status": "MANIFEST_REFERENCE_COVERAGE_VALID",
            "exactReferenceRate": manifest["identity_coverage"]["primary_2023_2025"]["exact_reference_rate"],
            "unresolvedReferences": manifest["identity_coverage"]["primary_2023_2025"]["unresolved_references"],
            "detail": "This is publisher manifest/reference coverage only; it does not authorize a plate-appearance to player_prior canonical join.",
        },
        "transitionCoverage": {"status": "VALID", "rows": sum(item["transitions"] for item in seasons)},
        "taxonomyCoverage": {"status": "VALID", "eightClassTaxonomyComplete": manifest["data_quality_evidence"]["eight_class_taxonomy_complete"]},
    }


class SportsDatasetRegistry:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, validated: ValidatedPackage, *, user_id: str) -> dict[str, Any]:
        manifest = validated.manifest
        if manifest["manifest_sha256"] != MANIFEST_SHA:
            raise ManifestValidationError("REGISTRATION_AUTHORITY_MISMATCH", "Only the approved MLB FD1 manifest can be registered")
        registered_at = now_iso()
        totals = _dataset_totals(validated)
        evidence_coverage = _evidence_coverage(manifest)
        feature_audit = build_mlb_pa_feature_audit(validated)
        metadata = {
            "adapter": "SPORTS_DATASET_CONSUMER_ADAPTER_V1",
            "contractVersion": manifest["contract_version"],
            "canonicalizationVersion": manifest["canonicalization_version"],
            "partitionAuthoritySha": validated.partition_authority_sha,
            "validationRootIdentity": validated.root_identity,
            "validationCache": {"hits": validated.cache_hits, "misses": validated.cache_misses},
            "modelingBlockers": [IDENTITY_BRIDGE_BLOCKER],
            "featureAudit": feature_audit,
        }
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE manifest_sha = ?",
                (MANIFEST_SHA,),
            ).fetchone()
            existing_project = connection.execute(
                """
                SELECT created_by, created_at
                FROM sports_research_projects
                WHERE registration_id = ? AND project_id = ? AND project_name = ?
                LIMIT 1
                """,
                (REGISTRATION_ID, PROJECT_ID, PROJECT_NAME),
            ).fetchone()
            registration_disposition = "REUSED" if existing is not None else "CREATED"
            if existing is not None:
                if existing["registration_id"] != REGISTRATION_ID or existing["logical_package_root"] != LOGICAL_PACKAGE_ROOT:
                    raise ManifestValidationError("REGISTRATION_CONFLICT", "Existing dataset registration conflicts with the approved identity")
                connection.execute(
                    """
                    UPDATE sports_dataset_registrations
                    SET dataset_id = ?, dataset_version_id = ?, manifest_id = ?, package_id = ?,
                        sport = ?, league = ?, evidence_cutoff = ?, published_at = ?,
                        validation_status = 'VALID', last_validated_at = ?, active = 1,
                        rights_status = ?, limitation_count = ?, totals_json = ?, seasons_json = ?,
                        evidence_coverage_json = ?, metadata_json = ?
                    WHERE registration_id = ?
                    """,
                    (
                        manifest["dataset_id"],
                        manifest["dataset_version_id"],
                        manifest["manifest_id"],
                        manifest["package_id"],
                        manifest["sport"],
                        manifest["league"],
                        manifest["evidence_cutoff"],
                        manifest["published_at"],
                        validated.validated_at,
                        "APPROVED_LOCAL_PRIVATE_USE",
                        len(manifest["known_limitations"]),
                        json_dumps(totals, {}),
                        json_dumps(manifest["seasons"], []),
                        json_dumps(evidence_coverage, {}),
                        json_dumps(metadata, {}),
                        REGISTRATION_ID,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE sports_dataset_registrations SET active = 0 WHERE dataset_id = ?",
                    (manifest["dataset_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sports_dataset_registrations (
                      registration_id, dataset_id, dataset_version_id, manifest_id, manifest_sha,
                      package_id, sport, league, evidence_cutoff, published_at, logical_package_root,
                      validation_status, registered_at, last_validated_at, registered_by, rights_status,
                      limitation_count, active, totals_json, seasons_json, evidence_coverage_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VALID', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        manifest["dataset_id"],
                        manifest["dataset_version_id"],
                        manifest["manifest_id"],
                        manifest["manifest_sha256"],
                        manifest["package_id"],
                        manifest["sport"],
                        manifest["league"],
                        manifest["evidence_cutoff"],
                        manifest["published_at"],
                        LOGICAL_PACKAGE_ROOT,
                        registered_at,
                        validated.validated_at,
                        user_id,
                        "APPROVED_LOCAL_PRIVATE_USE",
                        len(manifest["known_limitations"]),
                        json_dumps(totals, {}),
                        json_dumps(manifest["seasons"], []),
                        json_dumps(evidence_coverage, {}),
                        json_dumps(metadata, {}),
                    ),
                )

            # A successful revalidation replaces all governed child metadata
            # atomically.  Idempotency must never preserve corrupt or stale
            # partition/schema/fold/project rows from a prior local write.
            for table in (
                "sports_research_projects",
                "sports_dataset_limitations",
                "sports_dataset_rights",
                "sports_dataset_temporal_folds",
                "sports_dataset_populations",
                "sports_dataset_schemas",
                "sports_dataset_partitions",
            ):
                connection.execute(f"DELETE FROM {table} WHERE registration_id = ?", (REGISTRATION_ID,))

            for partition in manifest["partitions"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_partitions (
                      partition_id, registration_id, family, season, month, logical_uri,
                      row_count, byte_count, minimum_date, maximum_date, schema_id,
                      physical_schema_fingerprint, file_sha, source_key, source_version_id,
                      original_source_logical_identity, checkpoint_lineage_id, governance_checksum,
                      target_eligibility_json, temporal_classification_json, rights_ids_json, physical_schema_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        partition["partition_id"],
                        REGISTRATION_ID,
                        partition["family"],
                        partition["season"],
                        partition["month"],
                        f"{LOGICAL_PACKAGE_ROOT}/{partition['package_relative_uri']}",
                        partition["row_count"],
                        partition["byte_count"],
                        partition["minimum_date"],
                        partition["maximum_date"],
                        partition["schema_id"],
                        partition["physical_schema_fingerprint"],
                        partition["file_sha256"],
                        partition["source_key"],
                        partition["source_version_id"],
                        partition["original_source_logical_identity"],
                        partition["checkpoint_lineage_id"],
                        partition["governance_checksum"],
                        json_dumps(partition["target_eligibility"], []),
                        json_dumps(partition["temporal_classification"], []),
                        json_dumps(partition["source_rights_ids"], []),
                        json_dumps(partition["physical_schema"], []),
                    ),
                )

            schema_families = {item["family"]: item for item in validated.schema_registry["families"]}
            for family_name, family in schema_families.items():
                connection.execute(
                    """
                    INSERT INTO sports_dataset_schemas (
                      registration_id, family, logical_schema_version, compatible_partition_count,
                      physical_variant_count, fields_json, physical_variants_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        family_name,
                        family["logical_schema_version"],
                        family["partition_count"],
                        family["physical_variant_count"],
                        json_dumps(_schema_union(family), []),
                        json_dumps(family["physical_variants"], []),
                    ),
                )

            for population in manifest["populations"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_populations (
                      registration_id, population_id, row_count, predicate_json, allowed_uses_json,
                      prohibited_uses_json, temporal_meaning, evaluation_precedence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        population["population_id"],
                        population["expected_row_count"],
                        json_dumps(population["row_selection"], {}),
                        json_dumps(population["allowed_uses"], []),
                        json_dumps(population["prohibited_uses"], []),
                        population["temporal_meaning"],
                        population["evaluation_precedence"],
                    ),
                )

            for fold in manifest["temporal_contract"]["folds"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_temporal_folds (
                      registration_id, fold_id, training_seasons_json, validation_season,
                      training_end, validation_start, validation_end, training_rows, validation_rows
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        fold["fold_id"],
                        json_dumps(fold["training_seasons"], []),
                        fold["validation_season"],
                        fold["training_end"],
                        fold["validation_start"],
                        fold["validation_end"],
                        fold["training_rows"],
                        fold["validation_rows"],
                    ),
                )

            for right in validated.source_rights["records"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_rights (
                      registration_id, rights_control_id, display_name, source_name, status,
                      allowed_uses_json, prohibited_uses_json, attribution, controls_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        right["rights_control_id"],
                        right["display_name"],
                        right["source_name"],
                        right["fd1_use"]["status"],
                        json_dumps(right["allowed_purposes"], []),
                        json_dumps(EXPECTED_PROHIBITED_USES, []),
                        right.get("required_attribution_text") or right.get("attribution_text") or "No package use; attribution is not activated.",
                        json_dumps(right["controls"], {}),
                        json_dumps(
                            {
                                "fd1Use": right["fd1_use"],
                                "inventoryClassification": right["inventory_classification"],
                                "rightsClassification": right["rights_classification"],
                                "reviewNote": right["review_note"],
                            },
                            {},
                        ),
                    ),
                )

            for limitation in manifest["known_limitations"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_limitations (registration_id, limitation_id, scope, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    (REGISTRATION_ID, limitation["limitation_id"], limitation["scope"], limitation["description"]),
                )

            workflow = {
                "objective_forecast_contract": {"status": "COMPLETE", "evidence": "Exact MLB pregame-final forecast contract registered."},
                "data_evidence_manifest": {"status": "COMPLETE", "evidence": f"Validated {manifest['manifest_id']}."},
                "identity_coverage_leakage": {
                    "status": "BLOCKED",
                    "evidence": "Primary within-family identity coverage is exact, but the package-bound PA-to-prior bridge is absent.",
                    "featureAudit": feature_audit,
                },
                "temporal_validation": {"status": "COMPLETE", "evidence": "Two frozen retrospective rolling-origin folds registered."},
                "player_team_state": {"status": "BLOCKED", "evidence": IDENTITY_BRIDGE_BLOCKER["description"]},
                "participation_usage": {"status": "NOT_CONFIGURED"},
                "event_models": {"status": "NOT_CONFIGURED"},
                "game_simulation": {"status": "NOT_CONFIGURED"},
                "candidate_models_experiments": {"status": "NOT_CONFIGURED"},
                "calibration_reliability": {"status": "NOT_CONFIGURED"},
                "model_graph_decision": {"status": "NOT_CONFIGURED"},
                "export_to_asp": {"status": "NOT_CONFIGURED"},
            }
            connection.execute(
                """
                INSERT INTO sports_research_projects (
                  project_id, registration_id, project_name, sport, league, development_period,
                  prior_history, forecast_lifecycle, primary_target, secondary_targets_json,
                  baseline_population, upper_bound_population, research_purpose, workflow_evidence_json,
                  created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROJECT_ID,
                    REGISTRATION_ID,
                    PROJECT_NAME,
                    "Baseball",
                    "MLB",
                    "2023–2025",
                    "2021–2022",
                    "Pregame — Final",
                    "Plate-Appearance Outcome",
                    json_dumps(
                        [
                            "Joint Score Distribution",
                            "Home Win Probability",
                            "Run Differential",
                            "Total Runs",
                            "Player Outcome Distribution",
                        ],
                        [],
                    ),
                    "Strict Deployable",
                    "Enhanced Research",
                    "Establish the first leakage-safe player-event baseline for the MLB Gen-2 forecasting system.",
                    json_dumps(workflow, {}),
                    existing_project["created_by"] if existing_project is not None else user_id,
                    existing_project["created_at"] if existing_project is not None else registered_at,
                    registered_at,
                ),
            )
        result = self.get(REGISTRATION_ID)
        if result is None:
            raise RuntimeError("Sports dataset registration was not persisted")
        result["registration_disposition"] = registration_disposition
        return result

    @staticmethod
    def _decode_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        from ..persistence.db import decode_row

        return decode_row(row)

    def get(self, registration_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE registration_id = ?",
                (registration_id,),
            ).fetchone()
        return self._decode_row(row)

    def get_active(self) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE active = 1 AND validation_status = 'VALID' ORDER BY registered_at DESC LIMIT 1"
            ).fetchone()
        return self._decode_row(row)

    def list_partitions(self, registration_id: str, *, family: str | None = None, seasons: Sequence[int] = ()) -> list[dict[str, Any]]:
        clauses = ["registration_id = ?"]
        parameters: list[Any] = [registration_id]
        if family:
            clauses.append("family = ?")
            parameters.append(family)
        if seasons:
            placeholders = ",".join("?" for _ in seasons)
            clauses.append(f"season IN ({placeholders})")
            parameters.extend(seasons)
        query = f"SELECT * FROM sports_dataset_partitions WHERE {' AND '.join(clauses)} ORDER BY family, season, month, logical_uri"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def get_schema(self, registration_id: str, family: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_schemas WHERE registration_id = ? AND family = ?",
                (registration_id, family),
            ).fetchone()
        return self._decode_row(row)

    def get_fold(self, registration_id: str, fold_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_temporal_folds WHERE registration_id = ? AND fold_id = ?",
                (registration_id, fold_id),
            ).fetchone()
        return self._decode_row(row)

    def public_dataset(self, registration: Mapping[str, Any]) -> dict[str, Any]:
        registration_id = str(registration["registration_id"])
        with self.database.connection() as connection:
            families = [dict(row) for row in connection.execute(
                "SELECT family, SUM(row_count) AS rows FROM sports_dataset_partitions WHERE registration_id = ? GROUP BY family ORDER BY family",
                (registration_id,),
            ).fetchall()]
            populations = [self._decode_row(row) or {} for row in connection.execute(
                "SELECT * FROM sports_dataset_populations WHERE registration_id = ? ORDER BY evaluation_precedence",
                (registration_id,),
            ).fetchall()]
            folds = [self._decode_row(row) or {} for row in connection.execute(
                "SELECT * FROM sports_dataset_temporal_folds WHERE registration_id = ? ORDER BY validation_season",
                (registration_id,),
            ).fetchall()]
            rights = [self._decode_row(row) or {} for row in connection.execute(
                "SELECT * FROM sports_dataset_rights WHERE registration_id = ? ORDER BY rights_control_id",
                (registration_id,),
            ).fetchall()]
            limitations = [dict(row) for row in connection.execute(
                "SELECT limitation_id, scope, description FROM sports_dataset_limitations WHERE registration_id = ? ORDER BY limitation_id",
                (registration_id,),
            ).fetchall()]
            project = self._decode_row(connection.execute(
                "SELECT * FROM sports_research_projects WHERE registration_id = ? ORDER BY created_at LIMIT 1",
                (registration_id,),
            ).fetchone())
        metadata = registration.get("metadata_json") or {}
        public_limitations = [
            {"limitationId": item["limitation_id"], "scope": item["scope"], "description": item["description"], "source": "EXCHANGE_MANIFEST"}
            for item in limitations
        ]
        public_limitations.extend({**item, "source": "CONSUMER_AUDIT"} for item in metadata.get("modelingBlockers", []))
        seasons = registration.get("seasons_json") or []
        result = {
            "registrationId": registration_id,
            "datasetId": registration["dataset_id"],
            "datasetVersionId": registration["dataset_version_id"],
            "manifestId": registration["manifest_id"],
            "manifestSha": registration["manifest_sha"],
            "packageId": registration["package_id"],
            "sport": registration["sport"],
            "league": registration["league"],
            "evidenceCutoff": registration["evidence_cutoff"],
            "publishedAt": registration["published_at"],
            "logicalRoot": registration["logical_package_root"],
            "partitionAuthoritySha": metadata.get("partitionAuthoritySha"),
            "validationStatus": registration["validation_status"],
            "registeredAt": registration["registered_at"],
            "rightsStatus": registration["rights_status"],
            "limitationCount": registration["limitation_count"],
            "active": bool(registration["active"]),
            "seasons": [item["season"] for item in seasons],
            "totals": registration.get("totals_json") or {},
            "families": [{"family": item["family"], "rows": item["rows"]} for item in families],
            "seasonCoverage": [
                {
                    "season": item["season"],
                    "games": item["games"],
                    "plateAppearances": item["plate_appearances"],
                    "transitions": item["transitions"],
                    "starterTargets": item["starter_targets"],
                    "bullpenAppearances": item["bullpen_appearances"],
                }
                for item in seasons
            ],
            "populations": [
                {
                    "populationId": item["population_id"],
                    "rows": item["row_count"],
                    "predicate": item["predicate_json"],
                    "uses": item["allowed_uses_json"],
                    "prohibitions": item["prohibited_uses_json"],
                }
                for item in populations
            ],
            "folds": [
                {
                    "foldId": item["fold_id"],
                    "trainingSeasons": item["training_seasons_json"],
                    "validationSeason": item["validation_season"],
                    "trainingRows": item["training_rows"],
                    "validationRows": item["validation_rows"],
                }
                for item in folds
            ],
            "evidenceCoverage": registration.get("evidence_coverage_json") or {},
            "rights": [
                {
                    "rightsControlId": item["rights_control_id"],
                    "displayName": item["display_name"],
                    "sourceName": item["source_name"],
                    "source": item["source_name"],
                    "status": item["status"],
                    "allowedUses": item["allowed_uses_json"],
                    "prohibitedUses": item["prohibited_uses_json"],
                    "attribution": item["attribution"],
                }
                for item in rights
            ],
            "limitations": [item["description"] for item in public_limitations],
            "limitationDetails": public_limitations,
            "modelingBlockers": metadata.get("modelingBlockers", []),
            "featureAudit": metadata.get("featureAudit"),
        }
        if project:
            result["project"] = {
                "projectId": project["project_id"],
                "projectName": project["project_name"],
                "name": project["project_name"],
                "status": "REGISTERED_MODELING_BLOCKED",
                "workflowId": "mlb-forecasting",
                "sport": project["sport"],
                "league": project["league"],
                "developmentPeriod": project["development_period"],
                "priorHistory": project["prior_history"],
                "forecastLifecycle": project["forecast_lifecycle"],
                "primaryTarget": project["primary_target"],
                "secondaryTargets": project["secondary_targets_json"],
                "baselinePopulation": project["baseline_population"],
                "upperBoundPopulation": project["upper_bound_population"],
                "researchPurpose": project["research_purpose"],
                "workflowEvidence": project["workflow_evidence_json"],
                "stages": project["workflow_evidence_json"],
                "featureAudit": metadata.get("featureAudit"),
            }
        return result

    def record_query_start(
        self,
        *,
        query_id: str,
        registration_id: str,
        user_id: str,
        operation: str,
        logical_scope: str,
        fields: Sequence[str],
        requested_limit: int | None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sports_dataset_query_audit (
                  query_id, registration_id, user_id, operation, logical_scope, fields_json,
                  requested_limit, status, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?)
                """,
                (query_id, registration_id, user_id, operation, logical_scope, json_dumps(list(fields), []), requested_limit, now_iso()),
            )

    def record_query_finish(
        self,
        query_id: str,
        *,
        status: str,
        rows_scanned: int,
        rows_returned: int,
        error_code: str | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE sports_dataset_query_audit
                SET status = ?, rows_scanned = ?, rows_returned = ?, completed_at = ?, error_code = ?
                WHERE query_id = ?
                """,
                (status, rows_scanned, rows_returned, now_iso(), error_code, query_id),
            )

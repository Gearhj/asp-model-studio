from __future__ import annotations

import copy
import uuid
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

import server.sports_phase4.registry as phase4_registry_module
from server.persistence.db import Database, decode_row, json_dumps
from server.sports_datasets.constants import (
    MANIFEST_SHA,
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    REGISTRATION_ID,
)
from server.sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    ALLOWED_PURPOSES,
    BRIDGE_MANIFEST_ID,
    BRIDGE_MANIFEST_SHA,
    BRIDGE_PACKAGE_ID,
    BRIDGE_REGISTRATION_ID,
    DIMENSION_AUTHORITY_SHA,
    EXPECTED_LIMITATION_IDS,
    LOGICAL_PACKAGE_ROOT as IDENTITY_BRIDGE_LOGICAL_ROOT,
    PROHIBITED_PURPOSES,
    VALIDATION_REPORT_SHA,
)
from server.sports_phase4.dynamic_contract import (
    EXPECTED_SOURCE_PARTITION_COUNT,
    IDENTITY_JOIN_AUDIT_ID,
    PHASE3_FEATURE_ARTIFACT_SHA,
    PHASE3_FEATURE_CONTENT_SHA,
    PHASE3_FEATURE_CONTRACT_SHA,
    PHASE3_FEATURE_MATERIALIZATION_ID,
    PHASE3_FEATURE_VIEW_ID,
    PHASE3_FOLD_2024_PREDICTION_SHA,
    PHASE3_FOLD_2025_PREDICTION_SHA,
    PHASE3_RUN_ID,
    PHASE3_RUN_SHA,
    dynamic_history_index_schema_sha,
    dynamic_state_contract_payload,
    dynamic_state_contract_sha,
    dynamic_state_schema_sha,
)
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_phase4.dynamic_state import FrozenDynamicPolicy
from server.sports_modeling.metrics import PA_CLASS_ORDER, evaluate_multiclass
from server.sports_modeling.registry import SportsPAResearchRegistry
from server.sports_phase4.registry import (
    COMPONENT_POLICIES,
    PHASE3_EXPERIMENT_ID,
    PHASE3_FEATURE_CONTRACT_NAME,
    PHASE3_GRAPH_ID,
    SportsPhase4Registry,
    SportsPhase4RegistryError,
    build_phase4_study_payload,
    semantic_component_sha,
    validate_phase4_study_payload,
)
from tests import sports_pa_registry_test as phase3_fixtures


SCRATCH_ROOT = Path(__file__).resolve().parents[1] / ".tmp"
ARTIFACT_SHA = "1" * 64
HISTORY_ARTIFACT_SHA = "7" * 64
POSTERIOR_ARTIFACT_SHA = "a" * 64
MODEL_CARD_ARTIFACT_SHA = "b" * 64
FINAL_CHECKPOINT_ARTIFACT_SHA = "c" * 64
CONTENT_SHA = "2" * 64
HISTORY_CONTENT_SHA = "8" * 64
ARTIFACT_ID = f"sports-phase4-artifact:dynamic_player_state:sha256:{ARTIFACT_SHA}"
HISTORY_ARTIFACT_ID = (
    f"sports-phase4-artifact:dynamic_history_index:sha256:{HISTORY_ARTIFACT_SHA}"
)
POSTERIOR_ARTIFACT_ID = (
    "sports-phase4-artifact:dynamic_state_posterior_predictive:sha256:"
    f"{POSTERIOR_ARTIFACT_SHA}"
)
MODEL_CARD_ARTIFACT_ID = (
    f"sports-phase4-artifact:dynamic_model_card:sha256:{MODEL_CARD_ARTIFACT_SHA}"
)
FINAL_CHECKPOINT_ARTIFACT_ID = (
    "sports-phase4-artifact:dynamic_final_checkpoint:sha256:"
    f"{FINAL_CHECKPOINT_ARTIFACT_SHA}"
)
ARTIFACT_URI = (
    "asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
    f"objects/sha256/{ARTIFACT_SHA[:2]}/{ARTIFACT_SHA}/mlb-dynamic-player-state-v1.parquet"
)
HISTORY_ARTIFACT_URI = (
    "asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
    f"objects/sha256/{HISTORY_ARTIFACT_SHA[:2]}/{HISTORY_ARTIFACT_SHA}/dynamic-history-index.parquet"
)
POSTERIOR_ARTIFACT_URI = (
    "asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
    f"objects/sha256/{POSTERIOR_ARTIFACT_SHA[:2]}/{POSTERIOR_ARTIFACT_SHA}/"
    "dynamic-state-posterior-predictive.json"
)
MODEL_CARD_ARTIFACT_URI = (
    "asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
    f"objects/sha256/{MODEL_CARD_ARTIFACT_SHA[:2]}/{MODEL_CARD_ARTIFACT_SHA}/"
    "dynamic-model-card.json"
)
FINAL_CHECKPOINT_ARTIFACT_URI = (
    "asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
    f"objects/sha256/{FINAL_CHECKPOINT_ARTIFACT_SHA[:2]}/{FINAL_CHECKPOINT_ARTIFACT_SHA}/"
    "dynamic-final-checkpoint.json"
)
_PA_PARTITION_IDS_BY_SEASON = {
    season: tuple(
        sha256_bytes(f"fixture-pa:{season}:{ordinal}".encode("utf-8"))
        for ordinal in range(count)
    )
    for season, count in ((2021, 7), (2022, 7), (2023, 8), (2024, 7), (2025, 7))
}
_PLAYER_PRIOR_PARTITION_IDS_BY_SEASON = {
    season: sha256_bytes(f"fixture-player-prior:{season}".encode("utf-8"))
    for season in (2021, 2022, 2023, 2024)
}
DYNAMIC_SOURCE_PARTITION_IDS = sorted(
    partition_id
    for rows in _PA_PARTITION_IDS_BY_SEASON.values()
    for partition_id in rows
)
PHASE3_SOURCE_PARTITION_IDS = sorted(
    [
        partition_id
        for season in (2023, 2024, 2025)
        for partition_id in _PA_PARTITION_IDS_BY_SEASON[season]
    ]
    + list(_PLAYER_PRIOR_PARTITION_IDS_BY_SEASON.values())
)


def _phase4_dynamic_reference(
    artifact_type: str,
    filename: str,
    *,
    digest: str | None = None,
    byte_count: int = 100,
) -> dict[str, object]:
    content_sha = digest or sha256_bytes(
        f"phase4-registry-fixture:{artifact_type}:{filename}".encode("utf-8")
    )
    return {
        "artifactId": (
            f"sports-phase4-artifact:{artifact_type.casefold()}:sha256:{content_sha}"
        ),
        "artifactType": artifact_type,
        "logicalUri": (
            "asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
            f"objects/sha256/{content_sha[:2]}/{content_sha}/{filename}"
        ),
        "sha256": content_sha,
        "byteCount": byte_count,
        "mediaType": (
            "application/vnd.apache.parquet"
            if filename.endswith(".parquet")
            else "application/json"
        ),
    }


def _dynamic_artifacts() -> list[dict[str, object]]:
    artifacts = [
        _phase4_dynamic_reference(
            "DYNAMIC_PLAYER_STATE",
            "mlb-dynamic-player-state-v1.parquet",
            digest=ARTIFACT_SHA,
            byte_count=1234,
        ),
        _phase4_dynamic_reference(
            "DYNAMIC_HISTORY_INDEX",
            "dynamic-history-index.parquet",
            digest=HISTORY_ARTIFACT_SHA,
            byte_count=2345,
        ),
    ]
    artifacts.extend(
        _phase4_dynamic_reference(artifact_type, filename)
        for artifact_type, filename in (
            ("DYNAMIC_CONTRACT", "dynamic-contract.json"),
            ("DYNAMIC_STATE_SCHEMA", "dynamic-state-schema.json"),
            ("DYNAMIC_HISTORY_SCHEMA", "dynamic-history-schema.json"),
            ("DYNAMIC_TUNING", "dynamic-tuning.json"),
            (
                "DYNAMIC_STATE_POSTERIOR_PREDICTIVE",
                "dynamic-state-posterior-predictive.json",
            ),
        )
    )
    # Replace the generated posterior digest with the stable ID used by the
    # focused relabel/omission assertions below.
    artifacts[-1] = _phase4_dynamic_reference(
        "DYNAMIC_STATE_POSTERIOR_PREDICTIVE",
        "dynamic-state-posterior-predictive.json",
        digest=POSTERIOR_ARTIFACT_SHA,
        byte_count=3456,
    )
    for season in (2024, 2025):
        for ordinal in range(1, 5):
            artifacts.append(
                _phase4_dynamic_reference(
                    "DYNAMIC_MODEL_STATE",
                    f"model-D{ordinal}-validate-{season}.json",
                )
            )
            artifacts.append(
                _phase4_dynamic_reference(
                    "DYNAMIC_PREPROCESSOR_STATE",
                    f"preprocessor-D{ordinal}-validate-{season}.json",
                )
            )
    artifacts.extend(
        _phase4_dynamic_reference(artifact_type, filename)
        for artifact_type, filename in (
            ("DYNAMIC_FOLD_2024_PREDICTIONS", "dynamic-fold-2024-predictions.parquet"),
            ("DYNAMIC_FOLD_2025_PREDICTIONS", "dynamic-fold-2025-predictions.parquet"),
            ("DYNAMIC_EXPERIMENT_METRICS", "dynamic-experiment-metrics.json"),
            ("DYNAMIC_CALIBRATION", "dynamic-calibration.json"),
            ("DYNAMIC_BOOTSTRAP", "dynamic-bootstrap.json"),
            ("DYNAMIC_COVERAGE", "dynamic-coverage.json"),
            ("DYNAMIC_LINEAGE", "dynamic-lineage.json"),
        )
    )
    artifacts.extend(
        [
            _phase4_dynamic_reference(
                "DYNAMIC_FINAL_CHECKPOINT",
                "dynamic-final-checkpoint.json",
                digest=FINAL_CHECKPOINT_ARTIFACT_SHA,
                byte_count=5678,
            ),
            _phase4_dynamic_reference(
                "DYNAMIC_MODEL_CARD",
                "dynamic-model-card.json",
                digest=MODEL_CARD_ARTIFACT_SHA,
                byte_count=4567,
            ),
        ]
    )
    assert len(artifacts) == 32
    return artifacts


def _seed_parent_authorities(database: Database) -> None:
    timestamp = "2026-08-17T00:00:00+00:00"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO sports_dataset_registrations (
              registration_id, dataset_id, dataset_version_id, manifest_id,
              manifest_sha, package_id, sport, league, evidence_cutoff,
              published_at, logical_package_root, validation_status,
              registered_at, last_validated_at, registered_by, rights_status,
              limitation_count, active, totals_json, seasons_json,
              evidence_coverage_json, metadata_json
            ) VALUES (?, 'mlb-fd1', 'mlb-fd1-v1', 'mlb-fd1-manifest', ?,
              'mlb-fd1-package', 'Baseball', 'MLB', '2026-08-15', ?,
              'asp-model-exchange://datasets/mlb-fd1', 'VALID', ?, ?, 'test',
              'PASS', 0, 1, '{}', '[]', '{}', ?)
            """,
            (
                REGISTRATION_ID,
                MANIFEST_SHA,
                timestamp,
                timestamp,
                timestamp,
                json_dumps({"partitionAuthoritySha": PARTITION_AUTHORITY_SHA}, {}),
            ),
        )
        partition_rows = [
            (partition_id, "plate_appearance", season, ordinal + 1)
            for season, partition_ids in _PA_PARTITION_IDS_BY_SEASON.items()
            for ordinal, partition_id in enumerate(partition_ids)
        ] + [
            (partition_id, "player_prior", season, 1)
            for season, partition_id in _PLAYER_PRIOR_PARTITION_IDS_BY_SEASON.items()
        ]
        connection.executemany(
            """
            INSERT INTO sports_dataset_partitions (
              partition_id, registration_id, family, season, month, logical_uri,
              row_count, byte_count, schema_id, physical_schema_fingerprint,
              file_sha, source_key, source_version_id, target_eligibility_json,
              temporal_classification_json, rights_ids_json, physical_schema_json
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, 'fixture-schema', ?, ?,
              'fixture-source', 'fixture-version', '{}', '{}', '[]', '{}')
            """,
            [
                (
                    partition_id,
                    REGISTRATION_ID,
                    family,
                    season,
                    month,
                    f"asp-model-exchange://datasets/mlb-fd1/{family}/{season}/{month}",
                    sha256_bytes(f"schema:{family}".encode("utf-8")),
                    sha256_bytes(f"file:{partition_id}".encode("utf-8")),
                )
                for partition_id, family, season, month in partition_rows
            ],
        )
        connection.execute(
            """
            INSERT INTO sports_research_projects (
              project_id, registration_id, project_name, sport, league,
              development_period, prior_history, forecast_lifecycle,
              primary_target, secondary_targets_json, baseline_population,
              upper_bound_population, research_purpose, workflow_evidence_json,
              created_by, created_at, updated_at
            ) VALUES (?, ?, 'MLB Forecasting Research', 'Baseball', 'MLB',
              '2023-2025', '2021-2022', 'Pregame - Final',
              'Plate-Appearance Outcome', '[]', 'Strict Deployable',
              'Enhanced Research', 'Research', '{}', 'test', ?, ?)
            """,
            (PROJECT_ID, REGISTRATION_ID, timestamp, timestamp),
        )
        connection.execute(
            "UPDATE sports_research_projects SET workflow_evidence_json = ? WHERE project_id = ?",
            (
                json_dumps(
                    {
                        "pa_research_baseline": {
                            "status": "RESEARCH_BASELINE",
                            "runId": PHASE3_RUN_ID,
                        }
                    },
                    {},
                ),
                PROJECT_ID,
            ),
        )
        connection.execute(
            """
            INSERT INTO sports_identity_bridge_registrations (
              bridge_registration_id, contract_name, contract_version,
              bridge_manifest_id, bridge_manifest_sha, bridge_package_id,
              parent_dataset_registration_id, parent_project_id,
              parent_manifest_sha, parent_partition_authority_sha,
              alias_row_authority_sha, dimension_row_authority_sha,
              validation_report_sha, logical_bridge_root, validation_status,
              package_file_count, package_byte_count, alias_count,
              active_player_count, governed_active_player_count,
              primary_portable_player_count, primary_governed_player_count,
              namespace_count, join_contract_count, join_reference_count,
              rights_status, namespace_evidence_json, y_minus_one_coverage_json,
              rights_json, limitations_json, metadata_json, registered_at,
              last_validated_at, registered_by, active
            ) VALUES (?, 'SPORTS_IDENTITY_BRIDGE', 'SPORTS_IDENTITY_BRIDGE_V1',
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PASS', 7, 2071740, 13460,
              2692, 2693, 2070, 2071, 5, 10, 4633762,
              'APPROVED_FOR_REGISTERED_USES', '[]', '[]', ?, ?, ?, ?, ?, 'test', 1)
            """,
            (
                BRIDGE_REGISTRATION_ID,
                BRIDGE_MANIFEST_ID,
                BRIDGE_MANIFEST_SHA,
                BRIDGE_PACKAGE_ID,
                REGISTRATION_ID,
                PROJECT_ID,
                MANIFEST_SHA,
                PARTITION_AUTHORITY_SHA,
                ALIAS_AUTHORITY_SHA,
                DIMENSION_AUTHORITY_SHA,
                VALIDATION_REPORT_SHA,
                IDENTITY_BRIDGE_LOGICAL_ROOT,
                json_dumps(
                    {
                        "status": "APPROVED_FOR_REGISTERED_USES",
                        "allowedPurposes": list(ALLOWED_PURPOSES),
                        "prohibitedPurposes": list(PROHIBITED_PURPOSES),
                    },
                    {},
                ),
                json_dumps(
                    [{"limitation_id": item} for item in EXPECTED_LIMITATION_IDS],
                    [],
                ),
                json_dumps(
                    {"joinAuditId": IDENTITY_JOIN_AUDIT_ID, "joinAuditBytes": 100},
                    {},
                ),
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO sports_identity_join_audits (
              join_audit_id, bridge_registration_id, artifact_sha,
              artifact_byte_count, logical_uri, status, total_references,
              resolved_references, unresolved_references, ambiguous_references,
              multiply_mapped_references, mapping_rate, evidence_json,
              created_at, code_revision
            ) VALUES (?, ?, ?, 100, ?, 'PASS', 4633762, 4633762, 0, 0, 0,
              1.0, ?, ?, 'test')
            """,
            (
                IDENTITY_JOIN_AUDIT_ID,
                BRIDGE_REGISTRATION_ID,
                IDENTITY_JOIN_AUDIT_ID.rsplit(":", 1)[-1],
                (
                    "asp-model-studio-runtime://sports-modeling/identity-bridges/"
                    f"{BRIDGE_REGISTRATION_ID}/join-audits/sha256-"
                    f"{IDENTITY_JOIN_AUDIT_ID.rsplit(':', 1)[-1]}/join-audit.json"
                ),
                json_dumps(phase3_fixtures._join_audit_evidence(), {}),
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO sports_pa_feature_views (
              feature_view_id, project_id, parent_dataset_registration_id,
              identity_bridge_registration_id, contract_name, contract_version,
              content_sha, row_count, feature_count, feature_names_json,
              population, seasons_json, logical_uri, artifact_sha,
              artifact_byte_count, created_at, contract_sha
            ) VALUES (?, ?, ?, ?, 'MLB_PA_FEATURE_VIEW', 'MLB_PA_FEATURE_VIEW_V1',
              ?, 549479, 22, '[]', 'strict_deployable', '[2023,2024,2025]',
              ?, ?, 1234, ?, ?)
            """,
            (
                PHASE3_FEATURE_VIEW_ID,
                PROJECT_ID,
                REGISTRATION_ID,
                BRIDGE_REGISTRATION_ID,
                PHASE3_FEATURE_CONTENT_SHA,
                (
                    "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/objects/sha256/"
                    f"{PHASE3_FEATURE_ARTIFACT_SHA[:2]}/{PHASE3_FEATURE_ARTIFACT_SHA}/feature.parquet"
                ),
                PHASE3_FEATURE_ARTIFACT_SHA,
                timestamp,
                PHASE3_FEATURE_CONTRACT_SHA,
            ),
        )
        connection.execute(
            """
            INSERT INTO sports_pa_research_runs (
              run_id, run_sha, run_identity_sha, run_created_at, code_revision,
              schema_version, project_id, parent_dataset_registration_id,
              parent_manifest_sha, parent_partition_authority_sha,
              identity_bridge_registration_id, identity_bridge_manifest_sha,
              identity_join_audit_id, feature_view_id, class_order_json,
              terminal_status, selected_candidate_id, selection_metric,
              selection_rationale, calibration_json, bootstrap_comparisons_json,
              research_decision_json, registered_at, last_validated_at,
              registered_by, active
            ) VALUES (?, ?, ?, ?, 'phase3-test', 'MLB_PA_RESEARCH_RUN_V1', ?, ?, ?, ?,
              ?, ?, ?, ?, ?, 'RESEARCH_BASELINE', NULL, NULL, NULL, '{}', '[]',
              ?, ?, ?, 'test', 1)
            """,
            (
                PHASE3_RUN_ID,
                PHASE3_RUN_SHA,
                "4" * 64,
                timestamp,
                PROJECT_ID,
                REGISTRATION_ID,
                MANIFEST_SHA,
                PARTITION_AUTHORITY_SHA,
                BRIDGE_REGISTRATION_ID,
                BRIDGE_MANIFEST_SHA,
                IDENTITY_JOIN_AUDIT_ID,
                PHASE3_FEATURE_VIEW_ID,
                json_dumps(list(PA_CLASS_ORDER), []),
                json_dumps({"terminalStatus": "RESEARCH_BASELINE"}, {}),
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO sports_pa_experiments (
              experiment_id, run_id, objective, seed, training_contract_version
            ) VALUES (?, ?, 'test', 1, 'MLB_PA_FEATURE_VIEW_V1')
            """,
            (PHASE3_EXPERIMENT_ID, PHASE3_RUN_ID),
        )
        connection.execute(
            "INSERT INTO sports_pa_model_graphs (run_id, graph_id) VALUES (?, ?)",
            (PHASE3_RUN_ID, PHASE3_GRAPH_ID),
        )


def _artifact_reference(
    digest: str,
    *,
    artifact_type: str,
    filename: str,
    byte_count: int = 100,
) -> dict[str, object]:
    return {
        "artifactId": f"sports-pa-artifact:{artifact_type.casefold()}:sha256:{digest}",
        "artifactType": artifact_type,
        "logicalUri": (
            "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/objects/sha256/"
            f"{digest[:2]}/{digest}/{filename}"
        ),
        "sha256": digest,
        "byteCount": byte_count,
        "mediaType": "application/vnd.apache.parquet",
    }


def _dynamic_descriptor() -> dict[str, object]:
    authority = dynamic_state_contract_payload()["authorityBindings"]
    source_partitions = list(DYNAMIC_SOURCE_PARTITION_IDS)
    selected_policy = FrozenDynamicPolicy.create(
        half_life_days=60,
        prior_ess=150,
    ).public()
    state_candidates = []
    for half_life_ordinal, half_life in enumerate((30, 60, 120, None)):
        for prior_ess in (50, 150, 300):
            candidate_policy = FrozenDynamicPolicy.create(
                half_life_days=half_life,
                prior_ess=prior_ess,
            )
            state_candidates.append(
                {
                    "policyId": candidate_policy.policy_id,
                    "halfLifeDays": half_life,
                    "halfLifeGridOrdinal": half_life_ordinal,
                    "priorEffectiveSampleSize": prior_ess,
                    "validationRows": 10,
                    "roleObservations": 20,
                    "posteriorPredictiveLogLoss": (
                        0.1 if (half_life, prior_ess) == (60, 150) else 1.0 + half_life_ordinal
                    ),
                }
            )
    split = {
        "schemaVersion": "MLB_PA_DATE_ATOMIC_SPLIT_V1",
        "sourceSeason": 2023,
        "targetTrainingFraction": 0.8,
        "lastTrainingDate": "2023-08-01",
        "firstValidationDate": "2023-08-02",
        "trainingRows": 8,
        "validationRows": 2,
        "realizedTrainingFraction": 0.8,
        "dateAtomic": True,
    }
    logistic_tuning = {
        candidate_id: [
            {"C": 0.05, "metrics": {"logLoss": 0.9, "brierScore": 0.8}},
            {"C": 0.2, "metrics": {"logLoss": 0.8, "brierScore": 0.7}},
            {"C": 1.0, "metrics": {"logLoss": 0.7, "brierScore": 0.6}},
        ]
        for candidate_id in ("D1", "D2", "D3", "D4")
    }
    dynamic_state = {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_ARTIFACT_DESCRIPTOR_V1",
        "contractName": "MLB_DYNAMIC_PLAYER_STATE_V1",
        "contractSha": dynamic_state_contract_sha(),
        "schemaSha": dynamic_state_schema_sha(),
        "contentSha": CONTENT_SHA,
        "artifactId": ARTIFACT_ID,
        "artifactSha": ARTIFACT_SHA,
        "artifactBytes": 1234,
        "logicalUri": ARTIFACT_URI,
        "mediaType": "application/vnd.apache.parquet",
        "rowCount": 30,
        "seasonRows": {"2023": 10, "2024": 10, "2025": 10},
        "selectedPolicy": selected_policy,
        "sourcePartitionIds": source_partitions,
        "stateKinds": ["A_PRESEASON", "B_CUMULATIVE", "C_RECENCY"],
    }
    history_index = {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_HISTORY_DESCRIPTOR_V1",
        "contractName": "MLB_DYNAMIC_PLAYER_STATE_V1",
        "contractSha": dynamic_state_contract_sha(),
        "schemaSha": dynamic_history_index_schema_sha(),
        "contentSha": HISTORY_CONTENT_SHA,
        "artifactId": HISTORY_ARTIFACT_ID,
        "artifactSha": HISTORY_ARTIFACT_SHA,
        "artifactBytes": 2345,
        "logicalUri": HISTORY_ARTIFACT_URI,
        "mediaType": "application/vnd.apache.parquet",
        "rowCount": 100,
        "sourceRowCount": 100,
        "resolvedReferenceCount": 200,
        "sourcePartitionIds": source_partitions,
        "authorityBindings": {
            "dataset": authority["dataset"],
            "identityBridge": authority["identityBridge"],
        },
    }
    return {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_DESCRIPTOR_V1",
        "semanticVersion": "1.0.0",
        "contractSha": dynamic_state_contract_sha(),
        "stateSchemaSha": dynamic_state_schema_sha(),
        "historySchemaSha": dynamic_history_index_schema_sha(),
        "classOrder": list(PA_CLASS_ORDER),
        "referenceClass": "OTHER_REACH",
        "selectedPolicy": selected_policy,
        "tuning": {
            "statePolicy": {
                "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_TUNING_V1",
                "objective": "MEAN_BATTER_PITCHER_POSTERIOR_PREDICTIVE_LOG_LOSS",
                "split": split,
                "selectedPolicy": selected_policy,
                "candidates": state_candidates,
                "selectionUses2024Or2025": False,
            },
            "logisticInner2023Split": split,
            "logisticByCandidate": logistic_tuning,
        },
        "authorityBindings": authority,
        "source": {
            "family": "plate_appearance",
            "seasons": [2021, 2022, 2023, 2024, 2025],
            "partitionIds": source_partitions,
            "rowCount": 100,
            "resolvedReferenceCount": 200,
            "finalAvailabilityField": "final_available_date",
        },
        "phase3": {
            "runId": PHASE3_RUN_ID,
            "runSha": PHASE3_RUN_SHA,
            "featureViewId": PHASE3_FEATURE_VIEW_ID,
            "featureContentSha": PHASE3_FEATURE_CONTENT_SHA,
            "featureArtifact": _artifact_reference(
                PHASE3_FEATURE_ARTIFACT_SHA,
                artifact_type="FEATURE_VIEW",
                filename="mlb-pa-feature-view-v1.parquet",
                byte_count=11_574_290,
            ),
            "featureSourcePartitionIds": list(PHASE3_SOURCE_PARTITION_IDS),
            "d0PredictionArtifacts": {
                "2024": _artifact_reference(
                    PHASE3_FOLD_2024_PREDICTION_SHA,
                    artifact_type="FOLD_2024_PREDICTIONS",
                    filename="fold-2024-predictions.parquet",
                    byte_count=57_339_406,
                ),
                "2025": _artifact_reference(
                    PHASE3_FOLD_2025_PREDICTION_SHA,
                    artifact_type="FOLD_2025_PREDICTIONS",
                    filename="fold-2025-predictions.parquet",
                    byte_count=36_820_708,
                ),
            },
            "d0Candidate": "C4_RAW",
        },
        "dynamicState": dynamic_state,
        "historyIndex": history_index,
        "temporalPolicy": dynamic_state_contract_payload()["temporalPolicy"],
        "rowIdentityPolicy": dynamic_state_contract_payload()["representation"][
            "rowIdentityPolicy"
        ],
        "runtime": {
            "checkpointId": f"mlb-dynamic-player-state-checkpoint:sha256:{'9' * 64}",
            "materializationCodeRevision": "test-revision",
            "currentCodeRevision": "test-revision",
            "crossCodeRevisionImmutableReuseAllowed": True,
            "reuseRequiresExactFreshlyRebuiltBytes": True,
            "maxModelFitSeconds": 5400,
            "maxOverallSeconds": 28800,
            "heartbeatSeconds": 30,
        },
    }


@lru_cache(maxsize=None)
def _dynamic_metric_fixture(candidate_id: str, season: int) -> dict[str, object]:
    rows = {2024: 182_449, 2025: 182_926}[season]
    confidence = {
        "D0": 0.40,
        "D1": 0.50,
        "D2": 0.60,
        "D3": 0.70,
        "D4": 0.80,
    }[candidate_id]
    labels = np.arange(rows, dtype=np.int64) % len(PA_CLASS_ORDER)
    probabilities = np.full(
        (rows, len(PA_CLASS_ORDER)),
        (1.0 - confidence) / (len(PA_CLASS_ORDER) - 1),
        dtype=np.float64,
    )
    probabilities[np.arange(rows), labels] = confidence
    return evaluate_multiclass(labels, probabilities)


def _dynamic_component() -> dict[str, object]:
    policy = COMPONENT_POLICIES["dynamicState"]
    descriptor = _dynamic_descriptor()

    def fold(candidate_id: str, season: int) -> dict[str, object]:
        return {
            "foldId": (
                "dynamic-train-2023-validate-2024"
                if season == 2024
                else "dynamic-train-through-2024-validate-2025"
            ),
            "status": "COMPLETE",
            "trainingSeasons": [2023] if season == 2024 else [2023, 2024],
            "trainingRows": 184_104 if season == 2024 else 366_553,
            "validationSeason": season,
            "validationRows": 182_449 if season == 2024 else 182_926,
            "metrics": copy.deepcopy(_dynamic_metric_fixture(candidate_id, season)),
        }

    candidates: list[dict[str, object]] = []
    for ordinal, candidate_id in enumerate(("D0", "D1", "D2", "D3", "D4")):
        if candidate_id == "D0":
            config = {
                "estimator": "FROZEN_PHASE3_RAW_C4",
                "refit": False,
                "relabelled": False,
                "classOrder": list(PA_CLASS_ORDER),
                "sourceArtifactShas": {
                    "2024": PHASE3_FOLD_2024_PREDICTION_SHA,
                    "2025": PHASE3_FOLD_2025_PREDICTION_SHA,
                },
            }
        else:
            config = {"selectedC": 1.0}
        candidates.append(
            {
                "candidateId": candidate_id,
                "candidateType": (
                    "FROZEN_PHASE3_RAW_C4" if candidate_id == "D0" else "MULTINOMIAL_LOGISTIC_L2"
                ),
                "displayName": candidate_id,
                "ordinal": ordinal,
                "config": config,
                "configSha": sha256_bytes(canonical_json_bytes(config)),
                "runtimeSeconds": 0.0,
                "convergence": {"status": "CONVERGED", "converged": True},
                "foldMetrics": [fold(candidate_id, 2024), fold(candidate_id, 2025)],
                "eligible": True,
                "rejectionReasons": [],
            }
        )

    selected_folds = candidates[-1]["foldMetrics"]
    raw = {str(item["validationSeason"]): item["metrics"] for item in selected_folds}
    scaled = copy.deepcopy(raw)
    calibration = {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_CALIBRATION_V1",
        "method": "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES",
        "candidateId": "D4",
        "fitSeason": 2024,
        "applicationSeason": 2025,
        "fittedTemperature": 1.0,
        "eligibleOn2024": True,
        "nonWorseningOn2025": True,
        "retainedAfter2025Gate": True,
        "finalVariant": "SCALED",
        "raw": raw,
        "scaled": scaled,
        "final": copy.deepcopy(scaled),
        "retentionRule": "fixture frozen gate",
        "rawAndScaledPreserved": True,
    }
    d0_refs = {
        2024: _artifact_reference(
            PHASE3_FOLD_2024_PREDICTION_SHA,
            artifact_type="FOLD_2024_PREDICTIONS",
            filename="fold-2024-predictions.parquet",
        ),
        2025: _artifact_reference(
            PHASE3_FOLD_2025_PREDICTION_SHA,
            artifact_type="FOLD_2025_PREDICTIONS",
            filename="fold-2025-predictions.parquet",
        ),
    }
    common_folds = [
        {
            "foldId": selected_folds[season - 2024]["foldId"],
            "status": "COMPLETE",
            "trainingSeasons": [2023] if season == 2024 else [2023, 2024],
            "validationSeason": season,
            "trainingRows": 184_104 if season == 2024 else 366_553,
            "validationRows": 182_449 if season == 2024 else 182_926,
            "candidateIds": ["D0", "D1", "D2", "D3", "D4"],
            "d0SourceArtifactId": d0_refs[season]["artifactId"],
            "selectionUse": "DYNAMIC_SELECTION" if season == 2024 else "FINAL_EVALUATION_ONLY",
        }
        for season in (2024, 2025)
    ]
    state_posterior_predictive = {
        "schemaVersion": "MLB_DYNAMIC_STATE_POSTERIOR_PREDICTIVE_EVIDENCE_V1",
        "policyId": descriptor["selectedPolicy"]["policyId"],
        "policyFrozenBeforeEvaluation": True,
        "selectionUses2024Or2025": False,
        "probabilitySource": "FROZEN_ROLE_STATE_POSTERIOR",
        "classOrder": list(PA_CLASS_ORDER),
        "byRoleStateFold": [
            {
                "role": role,
                "stateKind": state_kind,
                "validationSeason": season,
                "rowCount": 182_449 if season == 2024 else 182_926,
                "logLoss": 1.0,
                "brierScore": 0.75,
                "brierDefinition": "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR",
            }
            for role in ("BATTER", "PITCHER")
            for state_kind in ("A_PRESEASON", "B_CUMULATIVE", "C_RECENCY")
            for season in (2024, 2025)
        ],
    }
    bootstrap: list[dict[str, object]] = []
    for season in (2024, 2025):
        selected_metric = raw[str(season)]
        baseline_metric = candidates[0]["foldMetrics"][season - 2024]["metrics"]
        for variant in ("RAW", "FINAL"):
            bootstrap.append(
                {
                    "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_BOOTSTRAP_V1",
                    "candidateId": "D4",
                    "baselineCandidateId": "D0",
                    "foldId": common_folds[season - 2024]["foldId"],
                    "validationSeason": season,
                    "probabilityVariant": variant,
                    "clusterUnit": "game_id",
                    "resamples": 500,
                    "seed": 20_260_817,
                    "evidence": {
                        "schemaVersion": "MLB_PA_GAME_CLUSTER_BOOTSTRAP_V1",
                        "classOrder": list(PA_CLASS_ORDER),
                        "differenceConvention": "SELECTED_MINUS_COMPARATOR_NEGATIVE_FAVORS_SELECTED",
                        "resamplingUnit": "game_id",
                        "resamplingMethod": "EQUAL_PROBABILITY_CLUSTERS_WITH_REPLACEMENT",
                        "rowsSampledIndependently": False,
                        "rowCount": 182_449 if season == 2024 else 182_926,
                        "clusterCount": 2_429 if season == 2024 else 2_430,
                        "clusterDrawsPerReplicate": 2_429 if season == 2024 else 2_430,
                        "resampleCount": 500,
                        "seed": 20_260_817,
                        "confidenceLevel": 0.95,
                        "logLossDifference": {
                            "pointEstimate": selected_metric["logLoss"] - baseline_metric["logLoss"],
                            "bootstrapMean": selected_metric["logLoss"] - baseline_metric["logLoss"],
                            "bootstrapStandardError": 0.0,
                            "percentileInterval": {
                                "confidenceLevel": 0.95,
                                "lower": selected_metric["logLoss"] - baseline_metric["logLoss"],
                                "upper": selected_metric["logLoss"] - baseline_metric["logLoss"],
                            },
                            "probabilitySelectedBetter": 1.0,
                            "replicateDifferences": [
                                selected_metric["logLoss"] - baseline_metric["logLoss"]
                            ] * 500,
                        },
                        "brierScoreDifference": {
                            "pointEstimate": selected_metric["brierScore"] - baseline_metric["brierScore"],
                            "bootstrapMean": selected_metric["brierScore"] - baseline_metric["brierScore"],
                            "bootstrapStandardError": 0.0,
                            "percentileInterval": {
                                "confidenceLevel": 0.95,
                                "lower": selected_metric["brierScore"] - baseline_metric["brierScore"],
                                "upper": selected_metric["brierScore"] - baseline_metric["brierScore"],
                            },
                            "probabilitySelectedBetter": 1.0,
                            "replicateDifferences": [
                                selected_metric["brierScore"] - baseline_metric["brierScore"]
                            ] * 500,
                        },
                    },
                }
            )
    subgroups = [
        {"validationSeason": season, "subgroup": name, "rowCount": rows}
        for season in (2024, 2025)
        for name, rows in (
            (
                "MISSING_HISTORY",
                181 if season == 2024 else 181,
            ),
            (
                "HAS_HISTORY_ESS_LT_100",
                60_756 if season == 2024 else 60_915,
            ),
            (
                "HAS_HISTORY_ESS_100_TO_299",
                60_756 if season == 2024 else 60_915,
            ),
            (
                "HAS_HISTORY_ESS_GE_300",
                60_756 if season == 2024 else 60_915,
            ),
        )
    ]
    d0_metrics = {
        season: candidates[0]["foldMetrics"][season - 2024]["metrics"]
        for season in (2024, 2025)
    }
    calibration_defects = {
        str(season): {
            "topLabelEceExcess": raw[str(season)]["topLabelEce"] - d0_metrics[season]["topLabelEce"],
            "classwiseEceExcess": {
                name: raw[str(season)]["classwiseEce"][name]
                - d0_metrics[season]["classwiseEce"][name]
                for name in PA_CLASS_ORDER
            },
        }
        for season in (2024, 2025)
    }
    return {
        "componentId": "",
        "componentType": policy["type"],
        "contractName": policy["contract"],
        "contractSha": policy["sha"],
        "descriptor": descriptor,
        "candidates": candidates,
        "selected": {
            "candidateId": "D4",
            "selectionMetric": "RAW_2024_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
            "selectionSeason": 2024,
            "probabilityVariant": "RAW",
            "rationale": "fixture 2024-only selection",
        },
        "folds": common_folds,
        "metrics": {
            "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_TRAINING_V1",
            "classOrder": list(PA_CLASS_ORDER),
            "governingProbabilityVariant": "RAW",
            "selectedCandidateId": "D4",
            "baselineCandidateId": "D0",
            "statePosteriorPredictive": state_posterior_predictive,
            "byCandidate": [
                {"candidateId": item["candidateId"], "foldMetrics": item["foldMetrics"]}
                for item in candidates
            ],
        },
        "calibration": calibration,
        "bootstrap": bootstrap,
        "coverage": {
            "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_COVERAGE_V1",
            "selectedCandidateId": "D4",
            "selectedStatePrefixes": ["batter_c", "pitcher_c"],
            "roleStateCoverage": [
                {
                    "validationSeason": season,
                    "statePrefix": prefix,
                    "rowCount": 182_449 if season == 2024 else 182_926,
                    "missingHistoryRows": 1,
                    "effectiveSampleSizeMin": 0.0,
                    "effectiveSampleSizeMedian": 150.0,
                    "effectiveSampleSizeMax": 300.0,
                }
                for season in (2024, 2025)
                for prefix in ("batter_c", "pitcher_c")
            ],
            "subgroups": subgroups,
            "missingHistoryDefinition": "any selected role/state has missing_history=true",
            "effectiveSampleSizeDefinition": "minimum ESS across selected role/state inputs",
        },
        "decision": {
            "decision": "DYNAMIC_STATE_RESEARCH_CHALLENGER",
            "selectedCandidateId": "D4",
            "decisionProbabilityVariant": "RAW",
            "rawLossRuleSatisfied": True,
            "noMeaningfulRawCalibrationDefect": True,
            "calibrationDefectTolerance": 0.005,
            "calibrationDefects": calibration_defects,
            "bootstrapUsedAsDecisionGate": False,
            "bootstrapEvidenceRows": 4,
            "scaledEvidenceCanEarnChallenger": False,
            "rejectionRuleSatisfied": False,
            "rationale": "fixture raw evidence satisfies the frozen challenger gate",
            "researchOnly": True,
            "deploymentAuthorized": False,
        },
        "artifactIds": sorted(
            str(item["artifactId"]) for item in _dynamic_artifacts()
        ),
    }


def _payload(*, created_at: str = "2026-08-17T01:00:00+00:00") -> dict[str, object]:
    return build_phase4_study_payload(
        phase3_baseline={
            "runId": PHASE3_RUN_ID,
            "runSha": PHASE3_RUN_SHA,
            "experimentId": PHASE3_EXPERIMENT_ID,
            "featureContractName": PHASE3_FEATURE_CONTRACT_NAME,
            "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
            "featureViewId": PHASE3_FEATURE_VIEW_ID,
            "graphId": PHASE3_GRAPH_ID,
            "status": "RESEARCH_BASELINE",
        },
        dynamic_state=_dynamic_component(),
        artifacts=_dynamic_artifacts(),
        created_at=created_at,
        code_revision="test-revision",
    )


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch) -> SportsPhase4Registry:
    root = SCRATCH_ROOT / f"sports-phase4-registry-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    database = Database(root / "registry.db")
    database.initialize()
    _seed_parent_authorities(database)
    # Most Phase 4 unit cases isolate the Phase 4 registry itself. A dedicated
    # preflight test below exercises the real hardened Phase 3 reconstruction.
    monkeypatch.setattr(
        SportsPhase4Registry,
        "_validated_phase3_parent_payload",
        lambda self: {},
    )
    monkeypatch.setattr(
        SportsPhase4Registry,
        "_assert_phase3_parent_rows",
        lambda self, connection, payload: None,
    )
    return SportsPhase4Registry(database)


def _refinalize(payload: dict[str, object]) -> dict[str, object]:
    # Use the public builder after mutations which intentionally represent a
    # scientifically distinct, internally coherent study.
    components = payload["components"]
    return build_phase4_study_payload(
        phase3_baseline=payload["phase3Baseline"],
        dynamic_state=components["dynamicState"],
        lineup=components["lineup"],
        starter_duration=components["starterDuration"],
        bullpen_usage=components["bullpenUsage"],
        artifacts=payload["artifacts"],
        created_at=payload["studyIdentity"]["createdAt"],
        code_revision=payload["studyIdentity"]["codeRevision"],
        dataset=payload["dataset"],
        identity_bridge=payload["identityBridge"],
        decision=payload["decision"],
    )


def test_registers_metadata_only_and_reuses_exact_a_b_a(registry: SportsPhase4Registry) -> None:
    study_a = _payload()
    first = registry.register(study_a, "analyst-a")
    assert first["phase4"] == study_a

    study_b = _payload(created_at="2026-08-17T02:00:00+00:00")
    registry.register(study_b, "analyst-b")
    assert registry.public_active()["phase4"]["studyId"] == study_b["studyId"]

    reused = registry.register(study_a, "analyst-a")
    assert reused["phase4"] == study_a
    assert registry.public_active()["phase4"]["studyId"] == study_a["studyId"]
    with registry.database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sports_phase4_studies WHERE active = 1"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sports_phase4_artifact_references"
        ).fetchone()[0] == 64
        assert connection.execute(
            "SELECT COUNT(*) FROM sports_phase4_artifact_references WHERE typeof(payload_json) = 'blob'"
        ).fetchone()[0] == 0
        project = decode_row(
            connection.execute(
                "SELECT workflow_evidence_json FROM sports_research_projects WHERE project_id = ?",
                (PROJECT_ID,),
            ).fetchone()
        )
        workflow = project["workflow_evidence_json"]
        assert workflow["player_team_state"]["studyId"] == study_a["studyId"]
        assert workflow["player_team_state"]["componentId"] == study_a["components"]["dynamicState"]["componentId"]
        assert workflow["participation_usage"]["status"] == "NOT_CONFIGURED"
        assert workflow["event_models"]["status"] == "COMPLETE"
        assert workflow["candidate_models_experiments"]["status"] == "PARTIAL"
        assert workflow["temporal_validation"]["status"] == "PARTIAL"
        assert workflow["calibration_reliability"]["status"] == "PARTIAL"
        assert workflow["model_graph_decision"]["status"] == "COMPLETE"
        assert workflow["game_simulation"]["status"] == "NOT_CONFIGURED"
        assert workflow["export_to_asp"]["status"] == "NOT_CONFIGURED"
        assert workflow["pa_research_baseline"] == {
            "status": "RESEARCH_BASELINE",
            "runId": PHASE3_RUN_ID,
        }


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda payload: payload["dataset"].__setitem__("manifestSha", "f" * 64), "core digest"),
        (lambda payload: payload["phase3Baseline"].__setitem__("runSha", "f" * 64), "core digest"),
        (lambda payload: payload["artifacts"][0].__setitem__("logicalUri", "file:///tmp/state.parquet"), "studySha"),
        (lambda payload: payload["graph"]["nodes"][5].__setitem__("status", "NOT_CONFIGURED"), "studySha"),
    ],
)
def test_rejects_unfinalized_authority_artifact_and_graph_tamper(
    registry: SportsPhase4Registry,
    mutate,
    message: str,
) -> None:
    payload = _payload()
    mutate(payload)
    with pytest.raises(SportsPhase4RegistryError, match=message):
        registry.register(payload, "analyst")


def test_rejects_refinalized_physical_path_and_graph_status_lie(registry: SportsPhase4Registry) -> None:
    payload = _payload()
    payload["components"]["dynamicState"]["descriptor"]["note"] = "C:\\private\\state.parquet"
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match="descriptor .*fields differ|Physical"):
        registry.register(payload, "analyst")

    payload = _payload()
    payload["graph"]["nodes"][5]["status"] = "BLOCKED"
    # Recompute only the full payload hash to prove graph validation is not
    # delegated to studySha.
    from server.sports_phase4.registry import semantic_study_sha

    payload["studySha"] = semantic_study_sha(payload)
    with pytest.raises(SportsPhase4RegistryError, match="graph differs"):
        registry.register(payload, "analyst")


def test_reuse_deep_compares_child_rows(registry: SportsPhase4Registry) -> None:
    payload = _payload()
    registry.register(payload, "analyst")
    with registry.database.transaction() as connection:
        connection.execute(
            "UPDATE sports_phase4_components SET payload_json = '{}' WHERE study_id = ?",
            (payload["studyId"],),
        )
    with pytest.raises(SportsPhase4RegistryError, match="component rows"):
        registry.register(payload, "analyst")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda component: component.__setitem__("selected", {"candidateId": "D1"}),
            "selection .*reconcile|selection differs",
        ),
        (
            lambda component: component["decision"].__setitem__(
                "decision", "DYNAMIC_STATE_RESEARCH_BASELINE"
            ),
            "terminal decision",
        ),
        (
            lambda component: component["bootstrap"][0]["evidence"][
                "logLossDifference"
            ].__setitem__("pointEstimate", 0.25),
            "bootstrap point estimate",
        ),
        (
            lambda component: component["metrics"]["statePosteriorPredictive"][
                "byRoleStateFold"
            ][0].__setitem__("rowCount", 1),
            "posterior-predictive metric",
        ),
    ],
)
def test_rejects_refinalized_scientific_claim_tamper(
    registry: SportsPhase4Registry,
    mutate,
    message: str,
) -> None:
    payload = _payload()
    mutate(payload["components"]["dynamicState"])
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match=message):
        registry.register(payload, "analyst")


def test_dynamic_blocked_is_a_non_persisted_fail_closed_terminal() -> None:
    payload = _payload()
    payload["components"]["dynamicState"]["decision"][
        "decision"
    ] = "DYNAMIC_STATE_BLOCKED"
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match="not registrable"):
        validate_phase4_study_payload(payload)


def test_database_parent_mismatch_fails_closed(registry: SportsPhase4Registry) -> None:
    payload = _payload()
    with registry.database.transaction() as connection:
        connection.execute(
            "UPDATE sports_pa_research_runs SET active = 0 WHERE run_id = ?",
            (PHASE3_RUN_ID,),
        )
    with pytest.raises(SportsPhase4RegistryError, match="Phase 3 parent"):
        registry.register(payload, "analyst")


def test_public_projection_fails_closed_after_parent_deactivation(
    registry: SportsPhase4Registry,
) -> None:
    registry.register(_payload(), "analyst")
    with registry.database.transaction() as connection:
        connection.execute(
            "UPDATE sports_pa_research_runs SET active = 0 WHERE run_id = ?",
            (PHASE3_RUN_ID,),
        )
    with pytest.raises(SportsPhase4RegistryError, match="Phase 3 parent"):
        registry.public_active()


def test_registration_locks_parent_authorities_before_reading_them(
    registry: SportsPhase4Registry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    original = registry._require_authorities

    def assert_writer_snapshot(connection, payload) -> None:
        assert connection.in_transaction
        rival = registry.database.connect()
        try:
            rival.execute("PRAGMA busy_timeout = 0")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                rival.execute(
                    "UPDATE sports_pa_research_runs SET active = 0 WHERE run_id = ?",
                    (PHASE3_RUN_ID,),
                )
        finally:
            rival.close()
        original(connection, payload)

    monkeypatch.setattr(registry, "_require_authorities", assert_writer_snapshot)
    registry.register(_payload(), "analyst")


def test_exact_phase3_artifact_and_registered_partition_lineage_are_required(
    registry: SportsPhase4Registry,
) -> None:
    payload = _payload()
    feature = payload["components"]["dynamicState"]["descriptor"]["phase3"][
        "featureArtifact"
    ]
    feature["logicalUri"] = feature["logicalUri"].replace(
        "mlb-pa-feature-view-v1.parquet", "bogus-feature.parquet"
    )
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match="Phase 3 artifact authority"):
        registry.register(payload, "analyst")

    payload = _payload()
    descriptor = payload["components"]["dynamicState"]["descriptor"]
    substituted = sorted([*DYNAMIC_SOURCE_PARTITION_IDS[1:], "f" * 64])
    descriptor["source"]["partitionIds"] = substituted
    descriptor["dynamicState"]["sourcePartitionIds"] = substituted
    descriptor["historyIndex"]["sourcePartitionIds"] = substituted
    payload = _refinalize(payload)
    # The descriptor is internally self-consistent and content-bound, but it
    # cannot substitute a fabricated inventory for registered dataset rows.
    with pytest.raises(SportsPhase4RegistryError, match="partition lineage"):
        registry.register(payload, "analyst")


def test_read_only_authority_preflight_rejects_fresh_and_substituted_pass_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SportsPhase4Registry,
        "_validated_phase3_parent_payload",
        lambda self: {},
    )
    monkeypatch.setattr(
        SportsPhase4Registry,
        "_assert_phase3_parent_rows",
        lambda self, connection, payload: None,
    )
    fresh_root = SCRATCH_ROOT / f"sports-phase4-fresh-{uuid.uuid4().hex}"
    fresh_root.mkdir(parents=True, exist_ok=False)
    fresh = SportsPhase4Registry(Database(fresh_root / "registry.db"))
    fresh.database.initialize()
    with pytest.raises(SportsPhase4RegistryError, match="parent dataset"):
        fresh.validate_registered_authorities()

    seeded_root = SCRATCH_ROOT / f"sports-phase4-preflight-{uuid.uuid4().hex}"
    seeded_root.mkdir(parents=True, exist_ok=False)
    database = Database(seeded_root / "registry.db")
    database.initialize()
    _seed_parent_authorities(database)
    seeded = SportsPhase4Registry(database)
    summary = seeded.validate_registered_authorities()
    assert summary == {
        "datasetRegistrationId": REGISTRATION_ID,
        "projectId": PROJECT_ID,
        "identityBridgeRegistrationId": BRIDGE_REGISTRATION_ID,
        "joinAuditId": IDENTITY_JOIN_AUDIT_ID,
        "phase3RunId": PHASE3_RUN_ID,
        "phase3FeatureViewId": PHASE3_FEATURE_VIEW_ID,
        "phase3GraphId": PHASE3_GRAPH_ID,
    }
    substituted = phase3_fixtures._join_audit_evidence()
    substituted["classOrder"] = list(reversed(PA_CLASS_ORDER))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE sports_identity_join_audits SET evidence_json = ? WHERE join_audit_id = ?",
            (json_dumps(substituted, {}), IDENTITY_JOIN_AUDIT_ID),
        )
    with pytest.raises(SportsPhase4RegistryError, match="join audit authority differs"):
        seeded.validate_registered_authorities()


def test_preflight_deeply_revalidates_phase3_child_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = SCRATCH_ROOT / f"sports-phase4-deep-phase3-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    database = Database(root / "registry.db")
    database.initialize()
    phase3_case = phase3_fixtures.SportsPAResearchRegistryTests(
        methodName="test_complete_run_is_metadata_only_idempotent_and_public"
    )
    phase3_case.database = database
    phase3_case._seed_authorities()
    phase3_payload = phase3_fixtures._payload(terminal_status="RESEARCH_BASELINE")
    phase3_payload["calibration"]["scaled2024"] = phase3_fixtures._metrics(
        182_449, log_loss=0.57, brier=0.71, ece=0.13
    )
    phase3_payload["calibration"]["scaled2025"] = phase3_fixtures._metrics(
        182_926, log_loss=0.58, brier=0.72, ece=0.14
    )
    phase3_payload["calibration"]["final2025"] = copy.deepcopy(
        phase3_payload["calibration"]["scaled2025"]
    )
    phase3_payload = phase3_fixtures._finalize(phase3_payload)
    SportsPAResearchRegistry(database).register(
        phase3_payload,
        user_id="phase3-test",
    )
    with database.connection() as connection:
        feature_row = decode_row(
            connection.execute(
                "SELECT contract_sha FROM sports_pa_feature_views WHERE feature_view_id = ?",
                (phase3_payload["featureView"]["featureViewId"],),
            ).fetchone()
        )
    frozen_for_fixture = {
        "PHASE3_RUN_ID": phase3_payload["runId"],
        "PHASE3_RUN_SHA": phase3_payload["runSha"],
        "PHASE3_EXPERIMENT_ID": phase3_payload["experiment"]["experimentId"],
        "PHASE3_FEATURE_VIEW_ID": phase3_payload["featureView"]["featureViewId"],
        "PHASE3_FEATURE_CONTENT_SHA": phase3_payload["featureView"]["contentSha"],
        "PHASE3_FEATURE_ARTIFACT_SHA": phase3_payload["featureView"]["artifactSha"],
        "PHASE3_FEATURE_CONTRACT_SHA": feature_row["contract_sha"],
        "PHASE3_GRAPH_ID": phase3_payload["graph"]["graphId"],
        "PHASE4_JOIN_AUDIT_ID": phase3_payload["identityBridge"]["joinAuditId"],
        "PHASE3_TERMINAL_STATUS": "RESEARCH_BASELINE",
    }
    for name, value in frozen_for_fixture.items():
        monkeypatch.setattr(phase4_registry_module, name, value)
    registry = SportsPhase4Registry(database)
    assert registry.validate_registered_authorities()["phase3RunId"] == phase3_payload["runId"]

    mutations = (
        (
            "UPDATE sports_pa_candidates SET config_json = ? WHERE run_id = ? AND candidate_id = 'C4'",
            (json_dumps({"tampered": True}, {}), phase3_payload["runId"]),
        ),
        (
            "UPDATE sports_pa_model_graph_nodes SET status = 'BLOCKED' WHERE run_id = ? AND node_id = 'selected-pa-baseline'",
            (phase3_payload["runId"],),
        ),
        (
            "UPDATE sports_pa_artifact_references SET media_type = 'text/plain' WHERE run_id = ? AND artifact_type = 'MODEL_CARD'",
            (phase3_payload["runId"],),
        ),
    )
    for query, parameters in mutations:
        with database.transaction() as connection:
            connection.execute(query, parameters)
        with pytest.raises(SportsPhase4RegistryError, match="Phase 3 .*evidence differs|Phase 3 persisted child rows differ"):
            registry.validate_registered_authorities()
        # Re-registering is intentionally not used to repair a tampered identity;
        # restore the exact row from the already validated payload for the next
        # independent direct-SQL mutation.
        with database.transaction() as connection:
            if "sports_pa_candidates" in query:
                candidate = next(
                    item for item in phase3_payload["candidates"] if item["candidateId"] == "C4"
                )
                connection.execute(
                    "UPDATE sports_pa_candidates SET config_json = ? WHERE run_id = ? AND candidate_id = 'C4'",
                    (json_dumps(candidate["config"], {}), phase3_payload["runId"]),
                )
            elif "graph_nodes" in query:
                node = next(
                    item for item in phase3_payload["graph"]["nodes"] if item["nodeId"] == "selected-pa-baseline"
                )
                connection.execute(
                    "UPDATE sports_pa_model_graph_nodes SET status = ? WHERE run_id = ? AND node_id = 'selected-pa-baseline'",
                    (node["status"], phase3_payload["runId"]),
                )
            else:
                artifact = next(
                    item for item in phase3_payload["artifacts"] if item["artifactType"] == "MODEL_CARD"
                )
                connection.execute(
                    "UPDATE sports_pa_artifact_references SET media_type = ? WHERE run_id = ? AND artifact_type = 'MODEL_CARD'",
                    (artifact["mediaType"], phase3_payload["runId"]),
                )
        registry.validate_registered_authorities()


def test_graph_preserves_exact_research_decision_and_future_scope() -> None:
    graph = _payload()["graph"]
    by_id = {node["nodeId"]: node for node in graph["nodes"]}
    assert by_id["dynamic-pa-research"]["status"] == "DYNAMIC_STATE_RESEARCH_CHALLENGER"
    assert by_id["retrospective-evaluation"]["status"] == "DYNAMIC_STATE_RESEARCH_CHALLENGER"
    assert by_id["dynamic-batter-state"]["status"] == "COMPLETE"
    assert by_id["phase3-baseline"]["status"] == "RESEARCH_BASELINE"
    assert by_id["phase3-baseline"]["authorityRef"] == PHASE3_RUN_ID
    assert by_id["exact-identity-join"]["authorityRef"] == IDENTITY_JOIN_AUDIT_ID
    for node_id in (
        "confirmed-lineup",
        "probable-starter",
        "injury-feed",
        "platoon",
        "base-out-transition",
        "game-simulator",
        "residual-layer",
        "export-bundle",
        "monitoring",
    ):
        assert by_id[node_id]["status"] == "NOT_CONFIGURED"


def test_frozen_study_narrative_and_artifact_media_are_not_caller_controlled() -> None:
    payload = _payload()
    payload["decision"]["limitations"] = ["Production deployment and betting are authorized."]
    with pytest.raises(SportsPhase4RegistryError, match="registry-governed"):
        _refinalize(payload)

    payload = _payload()
    next(
        item for item in payload["artifacts"] if item["artifactId"] == ARTIFACT_ID
    )["mediaType"] = "application/json"
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match="media type or governed filename"):
        # Validation runs before any database authority or write is consulted.
        validate_phase4_study_payload(payload)

    payload = _payload()
    state_artifact = next(
        item for item in payload["artifacts"] if item["sha256"] == ARTIFACT_SHA
    )
    relabelled_id = (
        f"sports-phase4-artifact:decision_evidence:sha256:{ARTIFACT_SHA}"
    )
    state_artifact["artifactType"] = "DECISION_EVIDENCE"
    state_artifact["artifactId"] = relabelled_id
    component = payload["components"]["dynamicState"]
    component["artifactIds"] = sorted(
        relabelled_id if value == ARTIFACT_ID else value
        for value in component["artifactIds"]
    )
    component["descriptor"]["dynamicState"]["artifactId"] = relabelled_id
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match="governed namespace|media type or governed filename"):
        validate_phase4_study_payload(payload)

    payload = _payload()
    payload["artifacts"] = [
        item
        for item in payload["artifacts"]
        if item["artifactId"] != MODEL_CARD_ARTIFACT_ID
    ]
    payload["components"]["dynamicState"]["artifactIds"].remove(
        MODEL_CARD_ARTIFACT_ID
    )
    payload = _refinalize(payload)
    with pytest.raises(
        SportsPhase4RegistryError,
        match="artifact cardinality|DYNAMIC_MODEL_CARD artifact inventory",
    ):
        validate_phase4_study_payload(payload)


def test_dynamic_artifact_ownership_and_exact_candidate_fold_coverage() -> None:
    payload = _payload()
    payload["components"]["dynamicState"]["artifactIds"].remove(
        MODEL_CARD_ARTIFACT_ID
    )
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match="Every Phase 4 artifact must be owned"):
        validate_phase4_study_payload(payload)

    payload = _payload()
    model = next(
        item
        for item in payload["artifacts"]
        if item["artifactType"] == "DYNAMIC_MODEL_STATE"
        and item["logicalUri"].endswith("model-D1-validate-2024.json")
    )
    model["logicalUri"] = model["logicalUri"].rsplit("/", 1)[0] + "/model-D2-validate-2024.json"
    payload = _refinalize(payload)
    with pytest.raises(
        SportsPhase4RegistryError,
        match="model/preprocessor artifact coverage",
    ):
        validate_phase4_study_payload(payload)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda component: component["bootstrap"][0]["evidence"]["logLossDifference"][
                "replicateDifferences"
            ].__setitem__(0, 0.25),
            "bootstrapMean|standardError|interval",
        ),
        (
            lambda component: component["bootstrap"][0]["evidence"]["logLossDifference"].__setitem__(
                "bootstrapStandardError", 1.0
            ),
            "standardError",
        ),
        (
            lambda component: component["bootstrap"][0]["evidence"].__setitem__(
                "clusterCount", 7
            ),
            "bootstrap evidence policy",
        ),
        (
            lambda component: component["candidates"][4]["foldMetrics"][0]["metrics"].pop(
                "confusionMatrix"
            ),
            "multiclass metric contract",
        ),
        (
            lambda component: component["candidates"][4]["foldMetrics"][0]["metrics"][
                "topLabelReliability"
            ][0].__setitem__("count", 1),
            "multiclass metric contract",
        ),
    ],
)
def test_rejects_replicate_and_full_metric_tamper(mutate, message: str) -> None:
    payload = _payload()
    mutate(payload["components"]["dynamicState"])
    payload = _refinalize(payload)
    with pytest.raises(SportsPhase4RegistryError, match=message):
        validate_phase4_study_payload(payload)


@pytest.mark.parametrize("target", ["component", "graph"])
def test_public_projection_revalidates_direct_sql_child_tamper(
    registry: SportsPhase4Registry,
    target: str,
) -> None:
    payload = _payload()
    registry.register(payload, "analyst")
    with registry.database.transaction() as connection:
        if target == "component":
            row = decode_row(
                connection.execute(
                    "SELECT payload_json FROM sports_phase4_components WHERE study_id = ? AND component_slot = 'dynamicState'",
                    (payload["studyId"],),
                ).fetchone()
            )
            component = row["payload_json"]
            component["candidates"][4]["foldMetrics"][0]["metrics"]["confusionMatrix"][0][0] += 1
            connection.execute(
                "UPDATE sports_phase4_components SET payload_json = ? WHERE study_id = ? AND component_slot = 'dynamicState'",
                (json_dumps(component, {}), payload["studyId"]),
            )
        else:
            row = decode_row(
                connection.execute(
                    "SELECT payload_json FROM sports_phase4_model_graph_nodes WHERE study_id = ? AND node_id = 'dynamic-pa-research'",
                    (payload["studyId"],),
                ).fetchone()
            )
            node = row["payload_json"]
            node["status"] = "COMPLETE"
            connection.execute(
                "UPDATE sports_phase4_model_graph_nodes SET payload_json = ? WHERE study_id = ? AND node_id = 'dynamic-pa-research'",
                (json_dumps(node, {}), payload["studyId"]),
            )
    with pytest.raises(SportsPhase4RegistryError):
        registry.public_active()

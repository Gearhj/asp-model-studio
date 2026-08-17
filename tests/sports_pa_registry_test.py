from __future__ import annotations

import copy
import json
import sqlite3
import unittest
import uuid
from pathlib import Path
from typing import Any

from server.persistence.db import Database, json_dumps
from server.sports_datasets.constants import (
    DATASET_ID,
    DATASET_VERSION_ID,
    MANIFEST_ID,
    MANIFEST_SHA,
    PACKAGE_ID,
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    PROJECT_NAME,
    REGISTRATION_ID,
)
from server.sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    ALLOWED_PURPOSES,
    BRIDGE_MANIFEST_ID,
    BRIDGE_MANIFEST_SHA,
    BRIDGE_PACKAGE_ID,
    BRIDGE_REGISTRATION_ID,
    CONTRACT_NAME as IDENTITY_BRIDGE_CONTRACT_NAME,
    CONTRACT_VERSION as IDENTITY_BRIDGE_CONTRACT_VERSION,
    DIMENSION_AUTHORITY_SHA,
    EXPECTED_ACTIVE_PLAYER_ROWS,
    EXPECTED_ALIAS_ROWS,
    EXPECTED_GOVERNED_ACTIVE_PLAYERS,
    EXPECTED_JOIN_CONTRACTS,
    EXPECTED_JOIN_REFERENCES,
    EXPECTED_JOIN_VALIDATION,
    EXPECTED_LIMITATION_IDS,
    EXPECTED_NAMESPACE_COUNT,
    EXPECTED_PACKAGE_BYTES,
    EXPECTED_PACKAGE_FILES,
    EXPECTED_PRIMARY_GOVERNED_PLAYERS,
    EXPECTED_PRIMARY_PORTABLE_PLAYERS,
    EXPECTED_Y_MINUS_1,
    LOGICAL_PACKAGE_ROOT as IDENTITY_BRIDGE_LOGICAL_ROOT,
    PROHIBITED_PURPOSES,
    VALIDATION_REPORT_SHA,
)
from server.sports_modeling.bootstrap import (
    BOOTSTRAP_SCHEMA_VERSION,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CONFIDENCE_LEVEL,
)
from server.sports_modeling.calibration import CALIBRATION_SCHEMA_VERSION
from server.sports_modeling.feature_contract import CANDIDATE_FEATURES, C_GRID, FEATURE_NAMES
from server.sports_modeling.metrics import (
    DEFAULT_CALIBRATION_BINS,
    METRICS_SCHEMA_VERSION,
    PA_CLASS_ORDER,
)
from server.sports_modeling.registry import (
    RUN_IDENTITY_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    SportsPARegistryError,
    SportsPAResearchRegistry,
    _COMPLETE_DECISION_RATIONALES,
    _GOVERNED_DECISION_LIMITATIONS,
    _GOVERNED_DECISION_NEXT_STEP,
    _complete_graph_authority,
    semantic_run_identity_sha,
    semantic_run_sha,
)
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_datasets.registry import SportsDatasetRegistry
from server.sports_modeling.training import DEFAULT_MAX_ITER, DEFAULT_TOLERANCE


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp"
JOIN_AUDIT_ID = f"sports-identity-join-audit:sha256:{'d' * 64}"
JOIN_AUDIT_BYTES = 100


def _join_audit_evidence() -> dict[str, Any]:
    joins: list[dict[str, Any]] = []
    for contract_id, (references, unique_source_ids, unique_players) in EXPECTED_JOIN_VALIDATION.items():
        source_family, remainder = contract_id.split(".", 1)
        physical_field = remainder.split(".", 1)[0]
        canonical_dimension = contract_id == "player_prior.canonical_player_id.canonical-to-dimension"
        joins.append(
            {
                "joinContractId": contract_id,
                "sourceFamily": source_family,
                "physicalFieldName": physical_field,
                "namespace": "CHADWICK" if canonical_dimension else "RETROSHEET",
                "joinType": "EXACT_CANONICAL_UUID" if canonical_dimension else "EXACT_PARENT_JOIN_KEY_TO_ALIAS",
                "referenceCount": references,
                "resolvedReferenceCount": references,
                "mappingRate": 1.0,
                "unresolvedReferenceCount": 0,
                "ambiguousReferenceCount": 0,
                "multiplyMappedReferenceCount": 0,
                "uniqueSourceIds": unique_source_ids,
                "uniqueCanonicalPlayers": unique_players,
                "seasons": [2021, 2022, 2023, 2024, 2025],
            }
        )
    coverage = [
        {
            "targetSeason": season,
            "role": role,
            "referenceRows": references,
            "rowsWithEligiblePrior": eligible,
            "legitimateMissingPriorRows": missing,
            "eligiblePriorRate": eligible / references,
            "unresolvedIdentityRows": 0,
            "ambiguousIdentityRows": 0,
            "multiplyMappedIdentityRows": 0,
            "maximumEligiblePriorSeason": maximum,
        }
        for (season, role), (references, eligible, missing, maximum) in EXPECTED_Y_MINUS_1.items()
    ]
    return {
        "status": "PASS",
        "parentManifestSha": MANIFEST_SHA,
        "parentPartitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        "bridgeManifestSha": BRIDGE_MANIFEST_SHA,
        "totalReferences": EXPECTED_JOIN_REFERENCES,
        "resolvedReferences": EXPECTED_JOIN_REFERENCES,
        "mappingRate": 1.0,
        "unresolvedReferences": 0,
        "ambiguousReferences": 0,
        "multiplyMappedReferences": 0,
        "joins": joins,
        "yMinus1Coverage": coverage,
        "noNamesOrFuzzyMatching": True,
    }


def _bin_base(index: int, count: int) -> dict[str, Any]:
    return {
        "binIndex": index,
        "lowerBound": index / DEFAULT_CALIBRATION_BINS,
        "upperBound": (index + 1) / DEFAULT_CALIBRATION_BINS,
        "upperBoundInclusive": index == DEFAULT_CALIBRATION_BINS - 1,
        "count": count,
    }


def _reliability_bins(
    rows: int,
    *,
    mean: float,
    outcome: float,
    top_label: bool,
) -> list[dict[str, Any]]:
    populated_index = min(int(mean * DEFAULT_CALIBRATION_BINS), DEFAULT_CALIBRATION_BINS - 1)
    output: list[dict[str, Any]] = []
    mean_key = "meanConfidence" if top_label else "meanProbability"
    outcome_key = "accuracy" if top_label else "realizedFrequency"
    for index in range(DEFAULT_CALIBRATION_BINS):
        count = rows if index == populated_index else 0
        item = _bin_base(index, count)
        if count:
            gap = outcome - mean
            item.update(
                {
                    mean_key: mean,
                    outcome_key: outcome,
                    "gap": gap,
                    "absoluteGap": abs(gap),
                }
            )
        else:
            item.update(
                {
                    mean_key: None,
                    outcome_key: None,
                    "gap": None,
                    "absoluteGap": None,
                }
            )
        output.append(item)
    return output


def _histogram_bins(rows: int, *, mean: float) -> list[dict[str, Any]]:
    populated_index = min(int(mean * DEFAULT_CALIBRATION_BINS), DEFAULT_CALIBRATION_BINS - 1)
    return [
        {
            **_bin_base(index, rows if index == populated_index else 0),
            "populationShare": 1.0 if index == populated_index else 0.0,
        }
        for index in range(DEFAULT_CALIBRATION_BINS)
    ]


def _metrics(rows: int, *, log_loss: float, brier: float, ece: float) -> dict[str, Any]:
    high_support = (rows + 4) // 5
    low_support = (rows - 4 * high_support) // 4
    supports = [high_support] * 4 + [low_support] * 3
    supports.append(rows - sum(supports))
    confusion: list[list[int]] = []
    for index, support in enumerate(supports):
        diagonal = (2 * support) // 5
        row = [0] * len(PA_CLASS_ORDER)
        row[index] = diagonal
        row[(index + 1) % len(PA_CLASS_ORDER)] = support - diagonal
        confusion.append(row)
    columns = [sum(row[index] for row in confusion) for index in range(len(PA_CLASS_ORDER))]
    per_class: dict[str, dict[str, Any]] = {}
    f1_values: list[float] = []
    recalls: list[float] = []
    for index, class_name in enumerate(PA_CLASS_ORDER):
        true_positive = confusion[index][index]
        precision = true_positive / columns[index] if columns[index] else 0.0
        recall = true_positive / supports[index]
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[class_name] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": supports[index],
        }
        f1_values.append(f1)
        recalls.append(recall)
    top1_accuracy = sum(confusion[index][index] for index in range(len(PA_CLASS_ORDER))) / rows
    realized = {
        class_name: supports[index] / rows
        for index, class_name in enumerate(PA_CLASS_ORDER)
    }
    predicted = {
        class_name: realized[class_name] + (-ece if index < 4 else ece)
        for index, class_name in enumerate(PA_CLASS_ORDER)
    }
    argmax = {
        class_name: columns[index] / rows
        for index, class_name in enumerate(PA_CLASS_ORDER)
    }
    classwise_reliability = {
        class_name: _reliability_bins(
            rows,
            mean=predicted[class_name],
            outcome=realized[class_name],
            top_label=False,
        )
        for class_name in PA_CLASS_ORDER
    }
    probability_histograms = {
        class_name: _histogram_bins(rows, mean=predicted[class_name])
        for class_name in PA_CLASS_ORDER
    }
    return {
        "schemaVersion": METRICS_SCHEMA_VERSION,
        "classOrder": list(PA_CLASS_ORDER),
        "rowCount": rows,
        "binCount": DEFAULT_CALIBRATION_BINS,
        "binningRule": "FIXED_EQUAL_WIDTH_LEFT_CLOSED_FINAL_RIGHT_CLOSED",
        "logLoss": log_loss,
        "brierScore": brier,
        "brierDefinition": "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR",
        "classwiseBrier": {name: brier / len(PA_CLASS_ORDER) for name in PA_CLASS_ORDER},
        "topLabelEce": ece,
        "top1Accuracy": top1_accuracy,
        "balancedAccuracy": sum(recalls) / len(recalls),
        "macroF1": sum(f1_values) / len(f1_values),
        "weightedF1": sum(f1 * support for f1, support in zip(f1_values, supports, strict=True)) / rows,
        "classwiseEce": {name: ece for name in PA_CLASS_ORDER},
        "perClass": per_class,
        "confusionMatrix": confusion,
        "confusionMatrixAxes": {"rows": "realized", "columns": "predicted"},
        "realizedPrevalence": realized,
        "predictedPrevalence": predicted,
        "argmaxPrevalence": argmax,
        "topLabelReliability": _reliability_bins(
            rows,
            mean=top1_accuracy + ece,
            outcome=top1_accuracy,
            top_label=True,
        ),
        "classwiseReliability": classwise_reliability,
        "probabilityHistograms": probability_histograms,
    }


def _fold(
    fold_id: str,
    training_seasons: list[int],
    validation_season: int,
    training_rows: int,
    validation_rows: int,
    metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "foldId": fold_id,
        "status": "COMPLETE" if metrics is not None else "NOT_RUN_BY_POLICY",
        "trainingSeasons": training_seasons,
        "validationSeason": validation_season,
        "trainingRows": training_rows,
        "validationRows": validation_rows,
        "metrics": metrics,
    }


def _comparison(
    *,
    selected: str,
    comparator: str,
    fold_id: str,
    season: int,
    rows: int,
    log_loss_point: float,
    brier_point: float,
) -> dict[str, Any]:
    def summary(point: float) -> dict[str, Any]:
        return {
            "pointEstimate": point,
            "bootstrapMean": point,
            "bootstrapStandardError": 0.0,
            "percentileInterval": {
                "confidenceLevel": DEFAULT_CONFIDENCE_LEVEL,
                "lower": point,
                "upper": point,
            },
            "probabilitySelectedBetter": 1.0 if point < 0.0 else 0.0,
            "replicateDifferences": [point] * DEFAULT_BOOTSTRAP_RESAMPLES,
        }
    return {
        "schemaVersion": BOOTSTRAP_SCHEMA_VERSION,
        "candidateId": selected,
        "baselineCandidateId": comparator,
        "foldId": fold_id,
        "validationSeason": season,
        "clusterUnit": "game_id",
        "seed": DEFAULT_BOOTSTRAP_SEED,
        "resamples": DEFAULT_BOOTSTRAP_RESAMPLES,
        "confidenceLevel": DEFAULT_CONFIDENCE_LEVEL,
        "evidence": {
            "schemaVersion": BOOTSTRAP_SCHEMA_VERSION,
            "classOrder": list(PA_CLASS_ORDER),
            "differenceConvention": "SELECTED_MINUS_COMPARATOR_NEGATIVE_FAVORS_SELECTED",
            "resamplingUnit": "game_id",
            "resamplingMethod": "EQUAL_PROBABILITY_CLUSTERS_WITH_REPLACEMENT",
            "rowsSampledIndependently": False,
            "rowCount": rows,
            "clusterCount": 2_429 if season == 2024 else 2_430,
            "clusterDrawsPerReplicate": 2_429 if season == 2024 else 2_430,
            "resampleCount": DEFAULT_BOOTSTRAP_RESAMPLES,
            "seed": DEFAULT_BOOTSTRAP_SEED,
            "confidenceLevel": DEFAULT_CONFIDENCE_LEVEL,
            "logLossDifference": summary(log_loss_point),
            "brierScoreDifference": summary(brier_point),
        },
    }


def _finalize(payload: dict[str, Any]) -> dict[str, Any]:
    payload["runId"] = ""
    payload["runSha"] = ""
    identity = payload.setdefault(
        "runIdentity",
        {
            "schemaVersion": RUN_IDENTITY_SCHEMA_VERSION,
            "coreSha": "",
            "createdAt": "2026-08-17T00:00:00+00:00",
            "codeRevision": "test-revision",
        },
    )
    identity["coreSha"] = semantic_run_identity_sha(
        payload,
        created_at=identity["createdAt"],
        code_revision=identity["codeRevision"],
    )
    payload["runId"] = f"sports-pa-research-run:sha256:{identity['coreSha']}"
    digest = semantic_run_sha(payload)
    payload["runSha"] = digest
    return payload


def _payload(
    *,
    terminal_status: str = "RESEARCH_CHALLENGER",
    selected_candidate: str = "C4",
) -> dict[str, Any]:
    feature_sha = "a" * 64
    feature_artifact_sha = "b" * 64
    feature_uri = (
        "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/objects/sha256/"
        f"{feature_artifact_sha[:2]}/{feature_artifact_sha}/feature-view.parquet"
    )
    fold_2024 = {
        "C0": _metrics(182_449, log_loss=0.72, brier=0.86, ece=0.12),
        "C1": _metrics(182_449, log_loss=0.66, brier=0.80, ece=0.10),
        "C2": _metrics(182_449, log_loss=0.63, brier=0.77, ece=0.09),
        "C3": _metrics(182_449, log_loss=0.61, brier=0.75, ece=0.08),
        "C4": _metrics(182_449, log_loss=0.59, brier=0.73, ece=0.07),
    }
    fold_2025 = {
        "C0": _metrics(182_926, log_loss=0.73, brier=0.87, ece=0.13),
        "C1": _metrics(182_926, log_loss=0.67, brier=0.81, ece=0.11),
        "C4": _metrics(182_926, log_loss=0.60, brier=0.74, ece=0.08),
    }
    if selected_candidate == "C1":
        fold_2024["C1"] = _metrics(182_449, log_loss=0.58, brier=0.72, ece=0.06)
        fold_2025.pop("C4")
    candidates: list[dict[str, Any]] = []
    for ordinal, candidate_id in enumerate(("C0", "C1", "C2", "C3", "C4")):
        tuning = (
            []
            if candidate_id == "C0"
            else [
                {
                    "C": c_value,
                    "trainingRows": 147_283,
                    "validationRows": 36_821,
                    "metrics": _metrics(
                        36_821,
                        log_loss=fold_2024[candidate_id]["logLoss"] + adjustment,
                        brier=fold_2024[candidate_id]["brierScore"] + adjustment,
                        ece=0.05,
                    ),
                    "nIter": 10 + index,
                }
                for index, (c_value, adjustment) in enumerate(
                    zip(C_GRID, (0.03, 0.02, 0.01), strict=True)
                )
            ]
        )
        config = (
            {
                "estimator": "GLOBAL_TRAINING_CLASS_FREQUENCY",
                "classOrder": list(PA_CLASS_ORDER),
                "featureNames": [],
                "trainingScope": "2023",
            }
            if candidate_id == "C0"
            else {
                "estimator": "sklearn.linear_model.LogisticRegression",
                "multiclass": "TRUE_MULTINOMIAL",
                "penalty": "l2",
                "solver": "lbfgs",
                "CGrid": list(C_GRID),
                "selectedC": 1.0,
                "maxIter": DEFAULT_MAX_ITER,
                "tolerance": DEFAULT_TOLERANCE,
                "featureNames": list(CANDIDATE_FEATURES[candidate_id]),
                "preprocessing": "FOLD_LOCAL_MEAN_IMPUTE_STANDARDIZE_FIXED_ONE_HOT",
            }
        )
        config_sha = sha256_bytes(canonical_json_bytes(config))
        second = fold_2025.get(candidate_id)
        candidates.append(
            {
                "candidateId": candidate_id,
                "candidateType": "GLOBAL_CLASS_FREQUENCY" if candidate_id == "C0" else "MULTINOMIAL_LOGISTIC_L2",
                "displayName": {
                    "C0": "Global eight-class frequency",
                    "C1": "Conditional PA-state context",
                    "C2": "PA-state context plus batter prior",
                    "C3": "PA-state context plus pitcher prior",
                    "C4": "Combined PA-state and batter/pitcher priors",
                }[candidate_id],
                "ordinal": ordinal,
                "config": config,
                "configSha": config_sha,
                "runtimeSeconds": float(ordinal + 1),
                "convergence": (
                    {
                        "status": "NOT_APPLICABLE",
                        "converged": None,
                        "nIter": None,
                        "maxIter": None,
                        "solver": None,
                    }
                    if candidate_id == "C0"
                    else {
                        "status": "CONVERGED",
                        "converged": True,
                        "nIter": 20 + ordinal,
                        "maxIter": DEFAULT_MAX_ITER,
                        "solver": "lbfgs",
                    }
                ),
                "foldMetrics": [
                    _fold(
                        "train-2023-validate-2024",
                        [2023],
                        2024,
                        184_104,
                        182_449,
                        fold_2024[candidate_id],
                    ),
                    _fold(
                        "train-through-2024-validate-2025",
                        [2023, 2024],
                        2025,
                        366_553,
                        182_926,
                        second,
                    ),
                ],
                "aggregateMetrics": {
                    "selection2024": copy.deepcopy(fold_2024[candidate_id]),
                    "inner2023Tuning": tuning,
                    "final2025": copy.deepcopy(second),
                },
                "eligible": True,
                "rejectionReasons": [],
            }
        )

    raw_2024 = copy.deepcopy(fold_2024[selected_candidate])
    scaled_2024 = _metrics(
        182_449,
        log_loss=raw_2024["logLoss"] - 0.02,
        brier=raw_2024["brierScore"] - 0.02,
        ece=raw_2024["topLabelEce"] - 0.01,
    )
    raw_2025 = copy.deepcopy(fold_2025[selected_candidate])
    scaled_2025 = _metrics(
        182_926,
        log_loss=raw_2025["logLoss"] - 0.02,
        brier=raw_2025["brierScore"] - 0.02,
        ece=raw_2025["topLabelEce"] - 0.01,
    )
    nodes, edges = _complete_graph_authority(
        {item["candidateId"]: item for item in candidates},
        selected_id=selected_candidate,
    )
    graph_sha = sha256_bytes(
        canonical_json_bytes(
            {
                "featureContentSha": feature_sha,
                "nodes": nodes,
                "edges": edges,
            }
        )
    )
    experiment_semantic = {
        "featureContentSha": feature_sha,
        "objective": "Eight-class conditional terminal plate-appearance outcome research",
        "seed": DEFAULT_BOOTSTRAP_SEED,
        "trainingContractVersion": "MLB_PA_FEATURE_VIEW_V1",
    }
    payload: dict[str, Any] = {
        "schemaVersion": RUN_SCHEMA_VERSION,
        "runId": "",
        "runSha": "",
        "runIdentity": {
            "schemaVersion": RUN_IDENTITY_SCHEMA_VERSION,
            "coreSha": "",
            "createdAt": "2026-08-17T00:00:00+00:00",
            "codeRevision": "test-revision",
        },
        "projectId": PROJECT_ID,
        "parent": {
            "registrationId": REGISTRATION_ID,
            "manifestSha": MANIFEST_SHA,
            "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        },
        "identityBridge": {
            "registrationId": BRIDGE_REGISTRATION_ID,
            "manifestSha": BRIDGE_MANIFEST_SHA,
            "joinAuditId": JOIN_AUDIT_ID,
        },
        "classOrder": list(PA_CLASS_ORDER),
        "featureView": {
            "featureViewId": f"sports-pa-feature-view:sha256:{feature_sha}",
            "contractName": "MLB_PA_FEATURE_VIEW",
            "contractVersion": "MLB_PA_FEATURE_VIEW_V1",
            "contentSha": feature_sha,
            "rowCount": 549_479,
            "featureCount": len(FEATURE_NAMES),
            "featureNames": list(FEATURE_NAMES),
            "population": "strict_deployable",
            "seasons": [2023, 2024, 2025],
            "logicalUri": feature_uri,
            "artifactSha": feature_artifact_sha,
            "artifactBytes": 1234,
        },
        "experiment": {
            "experimentId": (
                "mlb-pa-experiment:sha256:"
                + sha256_bytes(canonical_json_bytes(experiment_semantic))
            ),
            "objective": experiment_semantic["objective"],
            "seed": experiment_semantic["seed"],
            "trainingContractVersion": experiment_semantic["trainingContractVersion"],
        },
        "candidates": candidates,
        "selected": {
            "candidateId": selected_candidate,
            "selectionMetric": "2024_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
            "rationale": f"{selected_candidate} is selected using the frozen 2024 fold only.",
        },
        "calibration": {
            "schemaVersion": CALIBRATION_SCHEMA_VERSION,
            "decision": "RETAINED",
            "method": "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES",
            "sourceSeason": 2024,
            "candidateId": selected_candidate,
            "fittedTemperature": 1.2,
            "retainedTemperature": 1.2,
            "retained": True,
            "raw2024": raw_2024,
            "scaled2024": scaled_2024,
            "raw2025": raw_2025,
            "scaled2025": scaled_2025,
            "final2025": copy.deepcopy(scaled_2025),
            "rationale": "Frozen 2024 temperature improves both governing calibration metrics.",
        },
        "bootstrapComparisons": [
            _comparison(
                selected=selected_candidate,
                comparator=comparator,
                fold_id=fold_id,
                season=season,
                rows=rows,
                log_loss_point=(
                    (fold_2024 if season == 2024 else fold_2025)[selected_candidate]["logLoss"]
                    - (fold_2024 if season == 2024 else fold_2025)[comparator]["logLoss"]
                ),
                brier_point=(
                    (fold_2024 if season == 2024 else fold_2025)[selected_candidate]["brierScore"]
                    - (fold_2024 if season == 2024 else fold_2025)[comparator]["brierScore"]
                ),
            )
            for fold_id, season, rows in (
                ("train-2023-validate-2024", 2024, 182_449),
                ("train-through-2024-validate-2025", 2025, 182_926),
            )
            for comparator in ("C0", "C1")
        ],
        "artifacts": [],
        "graph": {
            "graphId": f"mlb-pa-model-graph:sha256:{graph_sha}",
            "nodes": nodes,
            "edges": edges,
        },
        "decision": {
            "terminalStatus": terminal_status,
            "rationale": (
                _COMPLETE_DECISION_RATIONALES[terminal_status]
                if terminal_status != "BLOCKED"
                else "The governed research run is blocked pending sanitized diagnostic review."
            ),
            "researchOnly": True,
            "deploymentAuthorized": False,
            "limitations": copy.deepcopy(_GOVERNED_DECISION_LIMITATIONS),
            "recommendedNextStep": _GOVERNED_DECISION_NEXT_STEP,
        },
    }
    artifact_types = (
        ["FEATURE_VIEW", "FEATURE_VIEW_RUN_BINDING", "FEATURE_CONTRACT", "FEATURE_SCHEMA", "CLASS_ORDER"]
        + ["MODEL_STATE"] * (7 if selected_candidate == "C1" else 8)
        + ["PREPROCESSOR_STATE"] * (5 if selected_candidate == "C1" else 6)
        + ["FOLD_2024_PREDICTIONS", "FOLD_2025_PREDICTIONS"]
        + [
            "EXPERIMENT_METRICS",
            "CONFUSION_MATRICES",
            "CALIBRATION_EVIDENCE",
            "BOOTSTRAP_EVIDENCE",
            "LINEAGE",
            "MODEL_CARD",
            "FINAL_CHECKPOINT",
        ]
    )
    for index, artifact_type in enumerate(artifact_types):
        digest = feature_artifact_sha if artifact_type == "FEATURE_VIEW" else sha256_bytes(
            f"{artifact_type}-{index}".encode("utf-8")
        )
        extension = (
            "parquet"
            if artifact_type in {"FEATURE_VIEW", "FOLD_2024_PREDICTIONS", "FOLD_2025_PREDICTIONS"}
            else "json"
        )
        filename = "feature-view.parquet" if artifact_type == "FEATURE_VIEW" else f"artifact-{index}.{extension}"
        payload["artifacts"].append(
            {
                "artifactId": f"sports-pa-artifact:{artifact_type.lower()}:sha256:{digest}",
                "artifactType": artifact_type,
                "logicalUri": (
                    "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/objects/sha256/"
                    f"{digest[:2]}/{digest}/{filename}"
                ),
                "sha256": digest,
                "byteCount": 1234 + index,
                "mediaType": (
                    "application/vnd.apache.parquet" if extension == "parquet" else "application/json"
                ),
            }
        )
    return _finalize(payload)


class SportsPAResearchRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        root = SCRATCH_ROOT / f"sports-pa-registry-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.database = Database(root / "registry.db")
        self.database.initialize()
        self._seed_authorities()
        self.registry = SportsPAResearchRegistry(self.database)

    def _seed_authorities(self) -> None:
        recorded_at = "2026-08-17T00:00:00+00:00"
        workflow = {
            "player_team_state": {"status": "READY_FOR_BASELINE"},
            "event_models": {"status": "READY_FOR_BASELINE"},
            "candidate_models_experiments": {"status": "NOT_CONFIGURED"},
        }
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sports_dataset_registrations (
                  registration_id, dataset_id, dataset_version_id, manifest_id,
                  manifest_sha, package_id, sport, league, evidence_cutoff,
                  published_at, logical_package_root, validation_status,
                  registered_at, last_validated_at, registered_by, rights_status,
                  limitation_count, active, totals_json, seasons_json,
                  evidence_coverage_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'Baseball', 'MLB', '2026-08-15', ?, ?,
                  'VALID', ?, ?, 'test', 'PASS', 12, 1, '{}', '[]', '{}', ?)
                """,
                (
                    REGISTRATION_ID,
                    DATASET_ID,
                    DATASET_VERSION_ID,
                    MANIFEST_ID,
                    MANIFEST_SHA,
                    PACKAGE_ID,
                    recorded_at,
                    "asp-model-exchange://datasets/mlb-fd1/exact",
                    recorded_at,
                    recorded_at,
                    json_dumps({"partitionAuthoritySha": PARTITION_AUTHORITY_SHA}, {}),
                ),
            )
            connection.execute(
                """
                INSERT INTO sports_research_projects (
                  project_id, registration_id, project_name, sport, league,
                  development_period, prior_history, forecast_lifecycle,
                  primary_target, secondary_targets_json, baseline_population,
                  upper_bound_population, research_purpose, workflow_evidence_json,
                  created_by, created_at, updated_at
                ) VALUES (?, ?, ?, 'Baseball', 'MLB', '2023-2025', '2021-2022',
                  'Pregame - Final', 'Plate-Appearance Outcome', '[]',
                  'Strict Deployable', 'Enhanced Research', 'Research baseline', ?,
                  'test', ?, ?)
                """,
                (PROJECT_ID, REGISTRATION_ID, PROJECT_NAME, json_dumps(workflow, {}), recorded_at, recorded_at),
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
                  rights_status, namespace_evidence_json,
                  y_minus_one_coverage_json, rights_json, limitations_json,
                  metadata_json, registered_at, last_validated_at, registered_by, active
                ) VALUES (?, 'SPORTS_IDENTITY_BRIDGE', 'SPORTS_IDENTITY_BRIDGE_V1',
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PASS', 7, 2071740, 13460,
                  2692, 2693, 2070, 2071, 5, 10, 4633762,
                  'APPROVED_FOR_REGISTERED_USES', '[]', '[]',
                  ?, ?, ?, ?, ?, 'test', 1)
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
                        {
                            "joinAuditId": JOIN_AUDIT_ID,
                            "joinAuditBytes": JOIN_AUDIT_BYTES,
                        },
                        {},
                    ),
                    recorded_at,
                    recorded_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO sports_identity_join_audits (
                  join_audit_id, bridge_registration_id, artifact_sha,
                  artifact_byte_count, logical_uri, status, total_references,
                  resolved_references, unresolved_references,
                  ambiguous_references, multiply_mapped_references,
                  mapping_rate, evidence_json, created_at, code_revision
                ) VALUES (?, ?, ?, ?, ?, 'PASS', 4633762, 4633762, 0, 0, 0,
                  1.0, ?, ?, 'test')
                """,
                (
                    JOIN_AUDIT_ID,
                    BRIDGE_REGISTRATION_ID,
                    "d" * 64,
                    JOIN_AUDIT_BYTES,
                    (
                        "asp-model-studio-runtime://sports-modeling/identity-bridges/"
                        f"{BRIDGE_REGISTRATION_ID}/join-audits/sha256-{'d' * 64}/join-audit.json"
                    ),
                    json_dumps(_join_audit_evidence(), {}),
                    recorded_at,
                ),
            )

    def test_complete_run_is_metadata_only_idempotent_and_public(self) -> None:
        payload = _payload()
        first = self.registry.register(payload, user_id="research-admin")
        second = self.registry.register(payload, user_id="different-admin")
        self.assertEqual(first["paBaseline"]["registry"]["registrationDisposition"], "CREATED")
        self.assertEqual(second["paBaseline"]["registry"]["registrationDisposition"], "REUSED")
        baseline = first["paBaseline"]
        self.assertEqual(baseline["run"]["terminalStatus"], "RESEARCH_CHALLENGER")
        self.assertEqual(baseline["run"]["runIdentity"], payload["runIdentity"])
        self.assertEqual(len(baseline["candidates"]), 5)
        self.assertEqual(len(baseline["bootstrapComparisons"]), 4)
        self.assertEqual(baseline["bootstrap"], baseline["bootstrapComparisons"])
        self.assertEqual(
            baseline["featureView"]["contractSha"],
            "fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e",
        )
        self.assertEqual(baseline["candidates"][1]["convergence"]["status"], "CONVERGED")
        for candidate in baseline["candidates"]:
            for fold in candidate["foldMetrics"]:
                prediction = fold["predictionArtifact"]
                if fold["status"] == "NOT_RUN_BY_POLICY":
                    self.assertIsNone(prediction)
                else:
                    self.assertEqual(
                        prediction["artifactType"],
                        f"FOLD_{fold['validationSeason']}_PREDICTIONS",
                    )
        self.assertEqual(baseline["decision"]["deploymentAuthorized"], False)
        self.assertEqual(len(baseline["decision"]["limitations"]), 4)
        serialized = json.dumps(first, sort_keys=True)
        self.assertNotIn("C:\\", serialized)
        self.assertNotIn("physicalPath", serialized)
        self.assertNotIn("predictionRows", serialized)

        expected_counts = {
            "sports_pa_feature_views": 1,
            "sports_pa_research_runs": 1,
            "sports_pa_experiments": 1,
            "sports_pa_candidates": 5,
            "sports_pa_candidate_fold_metrics": 10,
            "sports_pa_artifact_references": 28,
            "sports_pa_model_graphs": 1,
            "sports_pa_model_graph_nodes": 20,
            "sports_pa_model_graph_edges": 28,
        }
        with self.database.connection() as connection:
            observed = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in expected_counts
            }
            workflow = json.loads(
                connection.execute(
                    "SELECT workflow_evidence_json FROM sports_research_projects WHERE project_id = ?",
                    (PROJECT_ID,),
                ).fetchone()[0]
            )
            registered_by = connection.execute(
                "SELECT registered_by FROM sports_pa_research_runs"
            ).fetchone()[0]
            identity_metadata = connection.execute(
                "SELECT run_identity_sha, run_created_at, code_revision FROM sports_pa_research_runs"
            ).fetchone()
        self.assertEqual(observed, expected_counts)
        self.assertEqual(registered_by, "research-admin")
        self.assertEqual(tuple(identity_metadata), (
            payload["runIdentity"]["coreSha"],
            payload["runIdentity"]["createdAt"],
            payload["runIdentity"]["codeRevision"],
        ))
        for stage in (
            "player_team_state",
            "event_models",
            "candidate_models_experiments",
            "temporal_validation",
            "calibration_reliability",
            "model_graph_decision",
        ):
            self.assertEqual(workflow[stage]["status"], "COMPLETE")
        for stage in ("participation_usage", "game_simulation", "export_to_asp", "monitoring"):
            self.assertEqual(workflow[stage]["status"], "NOT_CONFIGURED")

        dataset_registry = SportsDatasetRegistry(self.database)
        active = dataset_registry.get_active()
        self.assertIsNotNone(active)
        public_dataset = dataset_registry.public_dataset(active or {})
        self.assertEqual(
            public_dataset["paBaseline"],
            self.registry.public_active()["paBaseline"],
        )
        self.assertEqual(
            public_dataset["project"]["status"],
            "REGISTERED_PA_RESEARCH_CHALLENGER",
        )
        public_serialized = json.dumps(public_dataset, sort_keys=True)
        self.assertNotIn("C:\\", public_serialized)
        self.assertNotIn("physicalPath", public_serialized)

    def test_false_challenger_claim_is_rejected_without_partial_rows(self) -> None:
        payload = _payload()
        worse = _metrics(182_926, log_loss=0.80, brier=0.90, ece=0.20)
        payload["calibration"]["scaled2025"] = worse
        payload["calibration"]["final2025"] = copy.deepcopy(worse)
        _finalize(payload)
        with self.assertRaisesRegex(SportsPARegistryError, "RESEARCH_CHALLENGER"):
            self.registry.register(payload, user_id="research-admin")
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_pa_research_runs").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_pa_feature_views").fetchone()[0], 0)

    def test_c0_selection_and_unreconciled_calibration_are_rejected(self) -> None:
        selected_c0 = _payload()
        selected_c0["selected"]["candidateId"] = "C0"
        selected_c0["calibration"]["candidateId"] = "C0"
        _finalize(selected_c0)
        with self.assertRaises(SportsPARegistryError):
            self.registry.register(selected_c0, user_id="research-admin")

        unreconciled = _payload()
        unreconciled["calibration"]["raw2024"]["logLoss"] -= 0.001
        _finalize(unreconciled)
        with self.assertRaisesRegex(SportsPARegistryError, "raw2024"):
            self.registry.register(unreconciled, user_id="research-admin")

    def test_false_rejected_baseline_claim_is_rejected(self) -> None:
        payload = _payload(terminal_status="REJECTED_BASELINE")
        _finalize(payload)
        with self.assertRaisesRegex(SportsPARegistryError, "REJECTED_BASELINE"):
            self.registry.register(payload, user_id="research-admin")

    def test_research_baseline_requires_mixed_evidence(self) -> None:
        false_baseline = _payload(terminal_status="RESEARCH_BASELINE")
        _finalize(false_baseline)
        with self.assertRaisesRegex(SportsPARegistryError, "RESEARCH_BASELINE"):
            self.registry.register(false_baseline, user_id="research-admin")

        mixed = _payload(terminal_status="RESEARCH_BASELINE")
        mixed["calibration"]["scaled2024"] = _metrics(
            182_449, log_loss=0.57, brier=0.71, ece=0.13
        )
        mixed["calibration"]["scaled2025"] = _metrics(
            182_926, log_loss=0.58, brier=0.72, ece=0.14
        )
        mixed["calibration"]["final2025"] = copy.deepcopy(
            mixed["calibration"]["scaled2025"]
        )
        _finalize(mixed)
        result = self.registry.register(mixed, user_id="research-admin")
        self.assertEqual(
            result["paBaseline"]["decision"]["terminalStatus"],
            "RESEARCH_BASELINE",
        )

    def test_tampered_class_order_physical_paths_and_model_bytes_fail_closed(self) -> None:
        cases: list[dict[str, Any]] = []
        changed = _payload()
        changed["classOrder"] = list(reversed(PA_CLASS_ORDER))
        cases.append(_finalize(changed))
        changed = _payload()
        changed["artifacts"][0]["logicalUri"] = "C:/private/feature-view.json"
        cases.append(_finalize(changed))
        changed = _payload()
        changed["artifacts"][0]["logicalUri"] = (
            "asp-model-studio-runtime://sports-modeling/C:/private/feature-view.json"
        )
        cases.append(_finalize(changed))
        changed = _payload()
        changed["candidates"][1]["config"]["modelBytes"] = "opaque"
        changed["candidates"][1]["configSha"] = sha256_bytes(
            canonical_json_bytes(changed["candidates"][1]["config"])
        )
        cases.append(_finalize(changed))
        changed = _payload()
        changed["graph"]["nodes"][-1]["label"] = "Deployment Bundle"
        changed_graph_semantic = {
            "featureContentSha": changed["featureView"]["contentSha"],
            "nodes": changed["graph"]["nodes"],
            "edges": changed["graph"]["edges"],
        }
        changed["graph"]["graphId"] = (
            "mlb-pa-model-graph:sha256:"
            + sha256_bytes(canonical_json_bytes(changed_graph_semantic))
        )
        cases.append(_finalize(changed))
        for payload in cases:
            with self.subTest(case=payload["runSha"]), self.assertRaises(SportsPARegistryError):
                self.registry.register(payload, user_id="research-admin")

    def test_embedded_drive_unc_and_posix_paths_fail_closed(self) -> None:
        for embedded in (
            "failure at C:\\private\\model.bin",
            "evidence='\\\\server\\share\\artifact.json'",
            "source=[/etc/passwd]",
            "path=/var/tmp/evidence.json",
            "artifact=file:///tmp/model.bin",
            (
                "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/evidence.json\n"
                "/etc/passwd"
            ),
        ):
            payload = _payload()
            payload["decision"]["rationale"] = embedded
            _finalize(payload)
            with self.subTest(embedded=embedded), self.assertRaisesRegex(
                SportsPARegistryError, "Physical or runtime path"
            ):
                self.registry.register(payload, user_id="research-admin")

    def test_run_identity_core_and_full_payload_digests_are_independent_gates(self) -> None:
        core_tamper = _payload()
        core_tamper["selected"]["rationale"] += " tampered"
        core_tamper["runSha"] = semantic_run_sha(core_tamper)
        with self.assertRaisesRegex(SportsPARegistryError, "core digest"):
            self.registry.register(core_tamper, user_id="research-admin")

        artifact_tamper = _payload()
        artifact_tamper["artifacts"][1]["byteCount"] += 1
        with self.assertRaisesRegex(SportsPARegistryError, "content identity"):
            self.registry.register(artifact_tamper, user_id="research-admin")

    def test_metric_schema_and_internal_evidence_tampering_fail_closed(self) -> None:
        cases: list[dict[str, Any]] = []
        omitted = _payload()
        omitted["calibration"]["scaled2024"].pop("confusionMatrix")
        cases.append(_finalize(omitted))
        confusion_tamper = _payload()
        confusion_tamper["calibration"]["scaled2024"]["confusionMatrix"][0][0] += 1
        cases.append(_finalize(confusion_tamper))
        class_tamper = _payload()
        class_tamper["calibration"]["scaled2024"]["perClass"].pop(PA_CLASS_ORDER[-1])
        cases.append(_finalize(class_tamper))
        bin_tamper = _payload()
        bin_tamper["calibration"]["scaled2024"]["probabilityHistograms"][PA_CLASS_ORDER[0]][0]["count"] += 1
        cases.append(_finalize(bin_tamper))
        for payload in cases:
            with self.subTest(run=payload["runSha"]), self.assertRaises(SportsPARegistryError):
                self.registry.register(payload, user_id="research-admin")

    def test_candidate_config_aggregate_and_selection_tampering_fail_closed(self) -> None:
        cases: list[dict[str, Any]] = []
        leakage = _payload()
        leakage["candidates"][1]["config"]["featureNames"].append("terminal_outcome")
        cases.append(leakage)
        grid = _payload()
        grid["candidates"][2]["config"]["CGrid"] = [0.05, 1.0]
        cases.append(grid)
        tolerance = _payload()
        tolerance["candidates"][3]["config"]["tolerance"] = 1e-5
        cases.append(tolerance)
        max_iter = _payload()
        max_iter["candidates"][4]["convergence"]["maxIter"] = DEFAULT_MAX_ITER - 1
        cases.append(max_iter)
        aggregate = _payload()
        aggregate["candidates"][2]["aggregateMetrics"]["selection2024"]["logLoss"] += 0.01
        cases.append(aggregate)
        wrong_argmin = _payload()
        improved = _metrics(182_449, log_loss=0.50, brier=0.70, ece=0.05)
        wrong_argmin["candidates"][3]["foldMetrics"][0]["metrics"] = improved
        wrong_argmin["candidates"][3]["aggregateMetrics"]["selection2024"] = copy.deepcopy(improved)
        cases.append(wrong_argmin)
        for payload in cases:
            for candidate in payload["candidates"]:
                candidate["configSha"] = sha256_bytes(canonical_json_bytes(candidate["config"]))
            _finalize(payload)
            with self.subTest(run=payload["runSha"]), self.assertRaises(SportsPARegistryError):
                self.registry.register(payload, user_id="research-admin")

    def test_complete_candidate_eligibility_and_2025_execution_are_exact(self) -> None:
        ineligible = _payload()
        ineligible["candidates"][2]["eligible"] = False
        ineligible["candidates"][2]["rejectionReasons"] = ["tampered"]
        _finalize(ineligible)
        with self.assertRaisesRegex(SportsPARegistryError, "eligible"):
            self.registry.register(ineligible, user_id="research-admin")

        extra_fold = _payload()
        metrics = _metrics(182_926, log_loss=0.62, brier=0.76, ece=0.09)
        extra_fold["candidates"][2]["foldMetrics"][1]["status"] = "COMPLETE"
        extra_fold["candidates"][2]["foldMetrics"][1]["metrics"] = metrics
        extra_fold["candidates"][2]["aggregateMetrics"]["final2025"] = copy.deepcopy(metrics)
        _finalize(extra_fold)
        with self.assertRaisesRegex(SportsPARegistryError, "2025 fold execution"):
            self.registry.register(extra_fold, user_id="research-admin")

    def test_artifact_inventory_identity_media_and_namespace_fail_closed(self) -> None:
        cases: list[dict[str, Any]] = []
        omitted = _payload()
        omitted["artifacts"] = [item for item in omitted["artifacts"] if item["artifactType"] != "MODEL_CARD"]
        cases.append(omitted)
        extra = _payload()
        cloned = copy.deepcopy(next(item for item in extra["artifacts"] if item["artifactType"] == "MODEL_CARD"))
        digest = sha256_bytes(b"extra-model-card")
        cloned.update(
            {
                "artifactId": f"sports-pa-artifact:model_card:sha256:{digest}",
                "logicalUri": (
                    "asp-model-studio-runtime://sports-modeling/mlb-pa-v1/objects/sha256/"
                    f"{digest[:2]}/{digest}/extra-model-card.json"
                ),
                "sha256": digest,
            }
        )
        extra["artifacts"].append(cloned)
        cases.append(extra)
        wrong_count = _payload()
        changed = next(item for item in wrong_count["artifacts"] if item["artifactType"] == "MODEL_STATE")
        changed["artifactType"] = "PREPROCESSOR_STATE"
        changed["artifactId"] = f"sports-pa-artifact:preprocessor_state:sha256:{changed['sha256']}"
        cases.append(wrong_count)
        wrong_id = _payload()
        wrong_id["artifacts"][0]["artifactId"] = f"sports-pa-artifact:sha256:{wrong_id['artifacts'][0]['sha256']}"
        cases.append(wrong_id)
        wrong_media = _payload()
        wrong_media["artifacts"][0]["mediaType"] = "application/json"
        cases.append(wrong_media)
        wrong_namespace = _payload()
        wrong_namespace["artifacts"][1]["logicalUri"] += "/nested.json"
        cases.append(wrong_namespace)
        for payload in cases:
            _finalize(payload)
            with self.subTest(run=payload["runSha"]), self.assertRaises(SportsPARegistryError):
                self.registry.register(payload, user_id="research-admin")

    def test_bootstrap_point_dispersion_interval_and_cluster_tampering_fail_closed(self) -> None:
        cases: list[dict[str, Any]] = []
        point = _payload()
        point["bootstrapComparisons"][0]["evidence"]["logLossDifference"]["pointEstimate"] += 0.001
        cases.append(point)
        standard_error = _payload()
        standard_error["bootstrapComparisons"][0]["evidence"]["logLossDifference"]["bootstrapStandardError"] = 0.1
        cases.append(standard_error)
        interval = _payload()
        interval["bootstrapComparisons"][0]["evidence"]["logLossDifference"]["percentileInterval"]["lower"] -= 0.01
        cases.append(interval)
        clusters = _payload()
        clusters["bootstrapComparisons"][0]["evidence"]["clusterCount"] = 100
        clusters["bootstrapComparisons"][0]["evidence"]["clusterDrawsPerReplicate"] = 100
        cases.append(clusters)
        for payload in cases:
            _finalize(payload)
            with self.subTest(run=payload["runSha"]), self.assertRaises(SportsPARegistryError):
                self.registry.register(payload, user_id="research-admin")

    def test_temperature_bounds_and_c1_selected_artifact_branch(self) -> None:
        for fitted in (0.049, 20.001):
            payload = _payload()
            payload["calibration"]["fittedTemperature"] = fitted
            payload["calibration"]["retainedTemperature"] = fitted
            _finalize(payload)
            with self.subTest(fitted=fitted), self.assertRaisesRegex(
                SportsPARegistryError, "temperatures"
            ):
                self.registry.register(payload, user_id="research-admin")

        c1 = _payload(selected_candidate="C1")
        result = self.registry.register(c1, user_id="research-admin")["paBaseline"]
        self.assertEqual(result["selected"]["candidateId"], "C1")
        self.assertEqual(len(result["registry"]["artifacts"]), 26)

    def test_complete_decision_prose_and_blocked_suitability_are_governed(self) -> None:
        cases: list[dict[str, Any]] = []
        rationale = _payload()
        rationale["decision"]["rationale"] = "Plausible but ungoverned public summary."
        cases.append(rationale)
        limitations = _payload()
        limitations["decision"]["limitations"][0] += " Arbitrary addendum."
        cases.append(limitations)
        next_step = _payload()
        next_step["decision"]["recommendedNextStep"] = "Ship this model."
        cases.append(next_step)
        for payload in cases:
            _finalize(payload)
            with self.subTest(run=payload["runSha"]), self.assertRaisesRegex(
                SportsPARegistryError, "decision prose"
            ):
                self.registry.register(payload, user_id="research-admin")

        blocked = _payload(terminal_status="BLOCKED")
        blocked["selected"] = None
        blocked["calibration"] = None
        blocked["bootstrapComparisons"] = []
        blocked["decision"]["rationale"] = "This blocked model is production-ready and suitable for deployment."
        _finalize(blocked)
        with self.assertRaisesRegex(SportsPARegistryError, "BLOCKED diagnostics"):
            self.registry.register(blocked, user_id="research-admin")

    def test_bridge_companion_count_and_rights_mutation_fail_closed(self) -> None:
        payload = _payload()
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE sports_identity_bridge_registrations
                SET alias_count = ?, rights_status = ?
                WHERE bridge_registration_id = ?
                """,
                (EXPECTED_ALIAS_ROWS - 1, "PASS", BRIDGE_REGISTRATION_ID),
            )
        with self.assertRaisesRegex(SportsPARegistryError, "identity-bridge registration"):
            self.registry.register(payload, user_id="research-admin")

    def test_alternate_fabricated_pass_join_audit_is_not_substitutable(self) -> None:
        digest = "f" * 64
        alternate_id = f"sports-identity-join-audit:sha256:{digest}"
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sports_identity_join_audits (
                  join_audit_id, bridge_registration_id, artifact_sha,
                  artifact_byte_count, logical_uri, status, total_references,
                  resolved_references, unresolved_references,
                  ambiguous_references, multiply_mapped_references,
                  mapping_rate, evidence_json, created_at, code_revision
                ) VALUES (?, ?, ?, ?, ?, 'PASS', ?, ?, 0, 0, 0, 1.0, ?, ?, 'fabricated')
                """,
                (
                    alternate_id,
                    BRIDGE_REGISTRATION_ID,
                    digest,
                    JOIN_AUDIT_BYTES,
                    (
                        "asp-model-studio-runtime://sports-modeling/identity-bridges/"
                        f"{BRIDGE_REGISTRATION_ID}/join-audits/sha256-{digest}/join-audit.json"
                    ),
                    EXPECTED_JOIN_REFERENCES,
                    EXPECTED_JOIN_REFERENCES,
                    json_dumps(_join_audit_evidence(), {}),
                    "2026-08-17T00:00:00+00:00",
                ),
            )
        payload = _payload()
        payload["identityBridge"]["joinAuditId"] = alternate_id
        _finalize(payload)
        with self.assertRaisesRegex(SportsPARegistryError, "artifact binding"):
            self.registry.register(payload, user_id="research-admin")

    def test_reused_run_deep_verifies_same_count_child_rows(self) -> None:
        payload = _payload()
        self.registry.register(payload, user_id="research-admin")
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE sports_pa_candidates SET display_name = ? WHERE run_id = ? AND candidate_id = 'C2'",
                ("tampered same-count row", payload["runId"]),
            )
        with self.assertRaisesRegex(SportsPARegistryError, "candidate evidence"):
            self.registry.register(payload, user_id="research-admin")

    def test_new_execution_identity_reuses_feature_and_experiment_authority_safely(self) -> None:
        first = _payload()
        self.registry.register(first, user_id="research-admin")
        second = copy.deepcopy(first)
        second["runIdentity"]["createdAt"] = "2026-08-18T00:00:00Z"
        second["runIdentity"]["codeRevision"] = "test-revision-2"
        _finalize(second)
        self.registry.register(second, user_id="research-admin")
        reused = self.registry.register(first, user_id="research-admin")

        self.assertNotEqual(first["runId"], second["runId"])
        self.assertEqual(
            reused["paBaseline"]["registry"]["registrationDisposition"],
            "REUSED",
        )
        self.assertEqual(
            self.registry.public_active()["paBaseline"]["run"]["runId"],
            second["runId"],
        )
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_pa_feature_views").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_pa_research_runs").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sports_pa_experiments").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT SUM(active) FROM sports_pa_research_runs").fetchone()[0], 1)
            workflow = json.loads(
                connection.execute(
                    "SELECT workflow_evidence_json FROM sports_research_projects WHERE project_id = ?",
                    (PROJECT_ID,),
                ).fetchone()[0]
            )
        for stage in (
            "player_team_state",
            "event_models",
            "candidate_models_experiments",
            "temporal_validation",
            "calibration_reliability",
            "model_graph_decision",
        ):
            self.assertEqual(workflow[stage]["runId"], second["runId"])

    def test_blocked_run_is_publicly_honest_and_does_not_complete_workflow(self) -> None:
        payload = _payload(terminal_status="BLOCKED")
        payload["selected"] = None
        payload["calibration"] = None
        payload["bootstrapComparisons"] = []
        _finalize(payload)
        result = self.registry.register(payload, user_id="research-admin")["paBaseline"]
        self.assertEqual(result["run"]["terminalStatus"], "BLOCKED")
        self.assertIsNone(result["selected"])
        self.assertIsNone(result["calibration"])
        self.assertEqual(result["bootstrapComparisons"], [])
        self.assertEqual(result["workflow"]["pa_research_baseline"]["status"], "BLOCKED")
        with self.database.connection() as connection:
            workflow = json.loads(
                connection.execute(
                    "SELECT workflow_evidence_json FROM sports_research_projects WHERE project_id = ?",
                    (PROJECT_ID,),
                ).fetchone()[0]
            )
        self.assertEqual(workflow["event_models"]["status"], "READY_FOR_BASELINE")
        self.assertEqual(workflow["candidate_models_experiments"]["status"], "NOT_CONFIGURED")

    def test_migration_foreign_keys_reject_orphan_feature_view(self) -> None:
        with self.assertRaises(Exception):
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO sports_pa_feature_views (
                      feature_view_id, project_id, parent_dataset_registration_id,
                      identity_bridge_registration_id, contract_name, contract_version,
                      content_sha, row_count, feature_count, feature_names_json,
                      population, seasons_json, logical_uri, artifact_sha,
                      artifact_byte_count, created_at
                    ) VALUES ('orphan', 'missing', ?, ?, 'x', 'x', ?, 1, 1,
                      '["x"]', 'strict_deployable', '[2023]', ?, ?, 1, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        BRIDGE_REGISTRATION_ID,
                        "e" * 64,
                        "target-local://orphan/feature.json",
                        "f" * 64,
                        "2026-08-17T00:00:00+00:00",
                    ),
            )

    def test_database_rejects_nonfrozen_feature_contract_authority(self) -> None:
        payload = _payload()
        self.registry.register(payload, user_id="research-admin")
        with self.database.transaction() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE sports_pa_feature_views SET contract_sha = ?",
                    ("0" * 64,),
                )


if __name__ == "__main__":
    unittest.main()

from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone
import copy
import hashlib
import json
import re

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.result_store import RESULTS
from ..governance.selection_integrity import (
    SelectionIntegrityError,
    assert_evaluation_package_integrity,
    assert_locked_candidate_decision,
    assert_selection_integrity,
)
from ..persistence.service import PersistenceService, get_persistence_service
from ..training.candidate_contract import (
    CandidateContractError,
    assert_candidate_contract_intact,
)


EXACT_EVALUATION_CONTEXT_FIELDS = (
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "candidate_id",
    "training_job_id",
    "training_run_id",
    "feature_manifest_version",
    "validation_design_id",
    "validation_design_version",
    "split_id",
    "target",
    "problem_type",
)


def _lineage_value(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _frozen_candidate_threshold_policy(
    candidate_contract: Dict[str, Any],
) -> tuple[float | None, str]:
    """Read the exact pre-exposure threshold from the frozen candidate."""

    configuration = candidate_contract.get("threshold_configuration")
    if not isinstance(configuration, dict):
        raise CandidateContractError(
            "The candidate has no frozen threshold configuration."
        )
    source = _lineage_value(configuration.get("threshold_source"))
    problem_type = _lineage_value(
        candidate_contract.get("problem_type")
        or (candidate_contract.get("target_definition") or {}).get(
            "problem_type"
        )
    ).casefold()
    if problem_type == "regression" and source == "not_applicable":
        return None, source
    raw_value = configuration.get("locked_threshold")
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        raise CandidateContractError(
            "The candidate has no numeric threshold locked before holdout use."
        )
    if (
        not source
        or source == "final_holdout"
        or not np.isfinite(value)
        or value < 0.0
        or value > 1.0
    ):
        raise CandidateContractError(
            "The candidate threshold policy is invalid or holdout-derived."
        )
    return value, source

try:
    from scipy import stats as scipy_stats
except Exception:  # pragma: no cover
    scipy_stats = None

try:
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        brier_score_loss,
        confusion_matrix,
        f1_score,
        mean_absolute_error,
        mean_squared_error,
        r2_score,
        precision_recall_curve,
        precision_score,
        recall_score,
        roc_auc_score,
        roc_curve,
    )
    from sklearn.inspection import permutation_importance
    from sklearn.base import clone
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import train_test_split
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.decomposition import PCA
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import LabelEncoder
except Exception:  # pragma: no cover
    accuracy_score = None
    average_precision_score = None
    brier_score_loss = None
    confusion_matrix = None
    f1_score = None
    mean_absolute_error = None
    mean_squared_error = None
    r2_score = None
    precision_score = None
    recall_score = None
    precision_recall_curve = None
    roc_auc_score = None
    roc_curve = None
    permutation_importance = None
    clone = None
    CalibratedClassifierCV = None
    train_test_split = None
    LinearRegression = None
    LogisticRegression = None
    PCA = None
    KMeans = None
    silhouette_score = None
    NearestNeighbors = None
    LabelEncoder = None


def _normalized_feature_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _target_aliases() -> set[str]:
    aliases = {
        _normalized_feature_name(DATASTORE.target),
        "bad_flag",
        "riskperformance",
    }
    source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta, dict) else {}
    if isinstance(source, dict):
        for key in ("target", "targetColumn", "originalTargetLabelColumn", "originalTargetLabel", "labelColumn"):
            aliases.add(_normalized_feature_name(source.get(key)))
    return {alias for alias in aliases if alias}


def _is_target_derived_feature(feature: Any) -> bool:
    name = _normalized_feature_name(str(feature).replace("num__", "").replace("cat__", ""))
    return any(name == alias or name.startswith(f"{alias}_") for alias in _target_aliases())


def _filter_target_derived_rows(rows: List[Dict[str, Any]], feature_key: str = "feature") -> List[Dict[str, Any]]:
    return [row for row in rows if not _is_target_derived_feature(row.get(feature_key, ""))]


class EvaluationService:
    def __init__(self, persistence_service: PersistenceService | None = None) -> None:
        # Resolve the process service lazily in production so tests can inject
        # an isolated temporary SQLite database without touching runtime state.
        self._persistence_service = persistence_service

    def _governance_repository(self):
        service = self._persistence_service or get_persistence_service()
        return service.holdout_governance

    @staticmethod
    def _runtime_decision_from_durable(record: Dict[str, Any]) -> Dict[str, Any]:
        selection_metric = {
            "selection_metric_name": record.get("selection_metric_name"),
            "selection_metric_value": record.get("selection_metric_value"),
            "selection_metric_source": record.get("selection_metric_source"),
            "selection_partition_id": record.get("selection_partition_id"),
            "fold_definition_id": record.get("fold_definition_id"),
            "fold_count": record.get("fold_count"),
            "fold_values": list(record.get("fold_values_json") or []),
            "mean": record.get("selection_metric_mean"),
            "standard_deviation": record.get("selection_metric_std"),
            "out_of_fold_prediction_artifact_id": record.get(
                "out_of_fold_prediction_artifact_id"
            ),
            "threshold_source": record.get("threshold_source"),
            "calibration_source": record.get("calibration_source"),
            "created_at": record.get("selection_metric_created_at"),
        }
        return {
            "decision_id": record.get("candidate_decision_id"),
            "status": record.get("decision_status"),
            "selected_candidate_id": record.get("candidate_id"),
            "project_id": record.get("project_id"),
            "dataset_id": record.get("dataset_id"),
            "dataset_version_id": record.get("dataset_version_id"),
            "feature_manifest_id": record.get("feature_manifest_id"),
            "feature_manifest_version": record.get("feature_manifest_hash"),
            "treatment_manifest_id": record.get("treatment_manifest_id"),
            "treatment_manifest_hash": record.get("treatment_manifest_hash"),
            "materialization_id": record.get("materialization_id"),
            "validation_design_id": record.get("validation_design_id"),
            "validation_design_version": record.get(
                "validation_design_version_id"
            ),
            "split_id": record.get("split_id"),
            "final_holdout_partition_id": record.get(
                "final_holdout_partition_id"
            ),
            "training_job_id": record.get("training_job_id"),
            "training_run_id": record.get("training_run_id"),
            "selected_candidate_contract_hash": record.get(
                "selected_candidate_contract_hash"
            ),
            "locked_threshold": record.get("locked_threshold"),
            "threshold_source": record.get("threshold_source"),
            "threshold_locked_at": record.get("threshold_locked_at"),
            "threshold_policy_hash": record.get("threshold_policy_hash"),
            "selection_metric": selection_metric,
            "selection_ranking_snapshot": list(
                record.get("ranking_snapshot_json") or []
            ),
            "selection_ranking_snapshot_hash": record.get(
                "ranking_snapshot_hash"
            ),
            "selection_rationale": record.get("selection_rationale"),
            "selection_locked_at": record.get("selection_locked_at"),
            "actor": {"user_id": record.get("actor")},
            "selection_integrity_status": record.get(
                "selection_integrity_status"
            ),
            "holdout_isolation_status": record.get(
                "holdout_isolation_status"
            ),
            "decision_contract_hash": record.get("decision_contract_hash"),
            "created_at": record.get("created_at"),
        }

    @staticmethod
    def _lineage_error(message: str, model_name: str = "") -> Dict[str, Any]:
        return {
            "ok": False,
            "error": message,
            "lineage_error": True,
            "candidate_id": _lineage_value(model_name),
        }

    def _locked_decision_for_candidate(
        self,
        candidate: Dict[str, Any],
        context: Dict[str, Any] | None,
    ) -> tuple[Dict[str, Any] | None, str]:
        requested_decision_id = _lineage_value(
            (context or {}).get("candidate_decision_id")
        )
        if not requested_decision_id:
            return None, (
                "Evaluation requires the exact candidate_decision_id. "
                "The final holdout remains sealed until selection is locked."
            )
        contract = candidate.get("candidate_contract")
        contract = contract if isinstance(contract, dict) else candidate
        exact = {
            "candidate_decision_id": requested_decision_id,
            "project_id": _lineage_value(contract.get("project_id")),
            "dataset_id": _lineage_value(contract.get("dataset_id")),
            "dataset_version_id": _lineage_value(
                contract.get("dataset_version_id")
            ),
            "validation_design_id": _lineage_value(
                contract.get("validation_design_id")
            ),
            "validation_design_version_id": _lineage_value(
                contract.get("validation_design_version")
                or contract.get("validation_design_version_id")
            ),
            "split_id": _lineage_value(contract.get("split_id")),
            "training_run_id": _lineage_value(contract.get("training_run_id")),
            "candidate_id": _lineage_value(contract.get("candidate_id")),
        }
        if any(not value for value in exact.values()):
            return None, (
                "The candidate contract is missing exact lineage required to "
                "recover its durable selection lock."
            )
        try:
            durable = self._governance_repository().get_selection_decision_exact(
                **exact
            )
        except Exception:
            return None, (
                "The durable candidate-decision registry is unavailable; the "
                "final holdout remains sealed."
            )
        if not isinstance(durable, dict):
            return None, (
                "No exact durable locked candidate decision exists; the final "
                "holdout remains sealed."
            )
        decision = self._runtime_decision_from_durable(durable)
        mirror = DATASTORE.meta.get("model_selection_decision")
        if isinstance(mirror, dict) and (
            _lineage_value(mirror.get("decision_id")) != requested_decision_id
            or _lineage_value(mirror.get("selected_candidate_id"))
            != _lineage_value(decision.get("selected_candidate_id"))
        ):
            return None, (
                "The browser/session candidate-decision mirror conflicts with "
                "the exact durable lock."
            )
        try:
            assert_locked_candidate_decision(decision, candidate)
        except SelectionIntegrityError as exc:
            return None, str(exc)
        return copy.deepcopy(decision), ""

    @staticmethod
    def _active_evaluation_lineage() -> tuple[Dict[str, str], str]:
        meta = DATASTORE.meta if isinstance(DATASTORE.meta, dict) else {}
        dataset_identity_status = _lineage_value(
            meta.get("dataset_identity_status")
        ).casefold()
        if dataset_identity_status != "current":
            return {}, (
                _lineage_value(meta.get("dataset_identity_error"))
                or "The active Dataset Library identity is not current. Reactivate the exact version and retrain."
            )

        manifest = meta.get("feature_manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        split_record = meta.get("split_record")
        split_record = split_record if isinstance(split_record, dict) else {}
        validation_design = split_record.get("validation_design")
        validation_design = validation_design if isinstance(validation_design, dict) else {}
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()

        lineage = {
            "project_id": _lineage_value(meta.get("project_id")),
            "dataset_id": _lineage_value(meta.get("dataset_id")),
            "dataset_version_id": _lineage_value(meta.get("dataset_version_id")),
            "feature_manifest_version": _lineage_value(manifest.get("manifest_hash")),
            "validation_design_id": _lineage_value(validation_design.get("validation_design_id")),
            "validation_design_version": _lineage_value(validation_design.get("design_version")),
            "split_id": _lineage_value(split_record.get("split_id")),
            "target": _lineage_value(DATASTORE.target),
        }
        missing = [field for field, value in lineage.items() if not value]
        if missing:
            return {}, (
                "The active evaluation workspace is missing exact canonical lineage: "
                + ", ".join(missing)
                + ". Reconfirm preparation, recreate the governed split, and retrain."
            )
        if _lineage_value(meta.get("split_status")).casefold() != "current":
            return {}, "The governed split is stale. Recreate it and retrain before evaluation."
        if not all(value is not None for value in (X_train, X_test, y_train, y_test)):
            return {}, "The exact governed train/holdout split is not materialized. Retrain before evaluation."
        if _lineage_value(manifest.get("confirmation_status")).casefold() != "confirmed":
            return {}, "The active feature manifest is not confirmed. Confirm and retrain before evaluation."
        if _lineage_value(manifest.get("materialization_status")).casefold() != "current":
            return {}, "The active feature manifest is stale. Materialize and retrain before evaluation."
        if _lineage_value(validation_design.get("status")).casefold() != "approved":
            return {}, "The active validation design is not approved. Approve it and retrain before evaluation."

        for field in ("project_id", "dataset_id", "dataset_version_id"):
            split_value = _lineage_value(split_record.get(field))
            if not split_value or split_value != lineage[field]:
                return {}, f"The governed split does not match the active {field}. Recreate it and retrain."
        split_manifest = _lineage_value(split_record.get("feature_manifest_version"))
        if not split_manifest or split_manifest != lineage["feature_manifest_version"]:
            return {}, "The governed split does not match the active feature manifest. Recreate it and retrain."
        design_dataset = validation_design.get("development_dataset")
        design_dataset = design_dataset if isinstance(design_dataset, dict) else {}
        if (
            _lineage_value(design_dataset.get("dataset_id")) != lineage["dataset_id"]
            or _lineage_value(design_dataset.get("dataset_version_id"))
            != lineage["dataset_version_id"]
        ):
            return {}, "The validation design does not bind the exact active Dataset Library version."
        return lineage, ""

    @staticmethod
    def _resolve_registered_candidate_lineage(
        requested: Dict[str, str],
        active: Dict[str, str],
        context: Dict[str, Any],
    ) -> tuple[Dict[str, Any] | None, str]:
        """Recover one explicit durable version without volatile result state."""

        version = context.get("_registered_version")
        artifact = context.get("_registered_artifact")
        requested_version_id = _lineage_value(context.get("model_version_id"))
        if not requested_version_id:
            return None, (
                "An explicit model_version_id is required for registered-model recovery; "
                "ATLAS will not load the latest or current model automatically."
            )
        if not isinstance(version, dict) or artifact is None:
            return None, "The explicit registered model version or its verified artifact is unavailable."
        if _lineage_value(version.get("modelVersionId")) != requested_version_id:
            return None, "The registry returned a different model_version_id."
        if (
            _lineage_value(version.get("publicationStatus")).casefold() != "finalized"
            or _lineage_value(version.get("lineageStatus")).casefold() != "verified"
        ):
            return None, "The explicit registered model version is not finalized with verified lineage."

        version_lineage = version.get("lineage")
        version_lineage = version_lineage if isinstance(version_lineage, dict) else {}
        model_contract = version.get("modelContract")
        model_contract = model_contract if isinstance(model_contract, dict) else {}
        contract_candidates = [
            source.get("candidateContract")
            for source in (version, version_lineage, model_contract)
            if isinstance(source.get("candidateContract"), dict)
        ]
        if not contract_candidates:
            return None, "The registered model version is missing its frozen candidate contract."
        contract_hashes: set[str] = set()
        canonical_contracts: set[str] = set()
        for contract in contract_candidates:
            try:
                assert_candidate_contract_intact(contract)
            except CandidateContractError as exc:
                return None, f"The registered candidate contract is invalid: {exc}"
            contract_hashes.add(_lineage_value(contract.get("contract_hash")))
            canonical_contracts.add(
                json.dumps(
                    contract,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    default=str,
                )
            )
        if "" in contract_hashes or len(contract_hashes) != 1:
            return None, "The registered model version contains conflicting candidate contracts."
        if len(canonical_contracts) != 1:
            return None, "The registered model version contains contradictory candidate-contract content."
        candidate_contract = copy.deepcopy(contract_candidates[0])

        sources = (version, version_lineage, model_contract, candidate_contract)
        aliases = {
            "project_id": ("projectId", "project_id"),
            "dataset_id": (
                "datasetId", "dataset_id", "trainingDatasetId", "training_dataset_id"
            ),
            "dataset_version_id": (
                "datasetVersionId", "dataset_version_id",
                "trainingDatasetVersionId", "training_dataset_version_id",
            ),
            "candidate_id": ("candidateId", "candidate_id"),
            "training_job_id": ("trainingJobId", "training_job_id"),
            "training_run_id": ("trainingRunId", "training_run_id"),
            "feature_manifest_version": (
                "featureManifestVersion", "featureManifestHash",
                "feature_manifest_version", "feature_manifest_hash",
            ),
            "validation_design_id": ("validationDesignId", "validation_design_id"),
            "validation_design_version": (
                "validationDesignVersion", "validation_design_version"
            ),
            "split_id": ("splitId", "split_id"),
            "target": ("target", "targetName", "target_name"),
            "problem_type": ("problemType", "problem_type"),
        }
        for field, field_aliases in aliases.items():
            values = {
                _lineage_value(source.get(alias))
                for source in sources
                for alias in field_aliases
                if _lineage_value(source.get(alias))
            }
            if field == "problem_type":
                target_definition = candidate_contract.get("target_definition")
                if isinstance(target_definition, dict):
                    problem_type = _lineage_value(target_definition.get("problem_type"))
                    if problem_type:
                        values.add(problem_type)
            if not values:
                return None, f"The registered model version is missing its exact {field} binding."
            if values != {requested[field]}:
                return None, f"The registered model version does not match the exact {field}."
            if field in active and requested[field] != active[field]:
                return None, f"The registered model version does not match the active {field}."

        contract_hash = next(iter(contract_hashes))
        published_contract_hashes = {
            _lineage_value(source.get(key))
            for source in (version, version_lineage, model_contract)
            for key in ("candidateContractHash", "candidate_contract_hash")
            if _lineage_value(source.get(key))
        }
        if published_contract_hashes and published_contract_hashes != {contract_hash}:
            return None, "The registered model version candidate-contract hash is inconsistent."

        algorithm_id = _lineage_value(candidate_contract.get("algorithm_id"))
        if not algorithm_id:
            return None, "The registered candidate contract is missing its algorithm_id."
        interpretation_summary = version.get("interpretationSummary")
        interpretation_summary = (
            interpretation_summary if isinstance(interpretation_summary, dict) else {}
        )
        trained_feature_names = interpretation_summary.get("selectedFeatures")
        if not isinstance(trained_feature_names, list):
            X_train, _, _, _ = DATASTORE.get_splits()
            trained_feature_names = list(X_train.columns) if X_train is not None else []
        metrics = version.get("metricsSummary")
        metrics = metrics if isinstance(metrics, dict) else {}
        hyperparameters = candidate_contract.get("hyperparameter_manifest")
        hyperparameters = hyperparameters if isinstance(hyperparameters, dict) else {}
        candidate = {
            **metrics,
            "key": algorithm_id,
            "name": _lineage_value(version.get("algorithm")) or algorithm_id,
            "candidate_id": requested["candidate_id"],
            "candidate_contract": candidate_contract,
            "best_params": copy.deepcopy(hyperparameters),
            "kind": "supervised",
            "target_usage": "supervised",
            "champion_eligible": True,
        }
        raw_result = {
            "task": requested["problem_type"],
            "metrics": copy.deepcopy(metrics),
            "best_params": copy.deepcopy(hyperparameters),
        }
        summary = {
            **{field: value for field, value in requested.items() if field != "candidate_id"},
            "ranked": [candidate],
            "raw": {algorithm_id: raw_result},
        }
        artifact_metadata = {
            **requested,
            "model_key": algorithm_id,
            "candidate_contract": candidate_contract,
            "trained_feature_names": [str(value) for value in trained_feature_names],
            "registry_model_version_id": requested_version_id,
        }
        return {
            "lineage": requested,
            "active_lineage": active,
            "summary": summary,
            "candidate": candidate,
            "candidate_contract": candidate_contract,
            "algorithm_id": algorithm_id,
            "raw_result": raw_result,
            "artifact": artifact,
            "artifact_metadata": artifact_metadata,
            "registered_version": version,
        }, ""

    def _resolve_candidate_lineage(
        self,
        model_name: str,
        context: Dict[str, Any] | None,
    ) -> tuple[Dict[str, Any] | None, str]:
        requested = {
            field: _lineage_value((context or {}).get(field))
            for field in EXACT_EVALUATION_CONTEXT_FIELDS
        }
        missing = [field for field, value in requested.items() if not value]
        if missing:
            return None, (
                "Evaluation requires exact lineage fields: "
                + ", ".join(missing)
                + ". Reload the governed candidate context."
            )
        if requested["candidate_id"] != _lineage_value(model_name):
            return None, "The requested candidate_id does not match the selected model candidate."
        if requested["problem_type"] not in {"classification", "regression"}:
            return None, "The selected candidate has an unsupported problem type."

        active, active_error = self._active_evaluation_lineage()
        if active_error:
            return None, active_error
        for field, active_value in active.items():
            if requested.get(field) != active_value:
                return None, f"The requested {field} does not match the exact active evaluation workspace."

        if (context or {}).get("_registered_version") is not None or (
            context or {}
        ).get("_registered_artifact") is not None:
            resolved, registered_error = self._resolve_registered_candidate_lineage(
                requested,
                active,
                context or {},
            )
            if registered_error or not resolved:
                return resolved, registered_error
            guarded_candidate = {
                **resolved["candidate_contract"],
                **resolved["candidate"],
            }
            try:
                assert_selection_integrity(guarded_candidate)
            except SelectionIntegrityError as exc:
                return None, str(exc)
            decision, decision_error = self._locked_decision_for_candidate(
                guarded_candidate,
                context,
            )
            if decision_error:
                return None, decision_error
            resolved["candidate_decision"] = decision
            resolved["lineage"] = {
                **resolved["lineage"],
                "candidate_decision_id": _lineage_value(
                    decision.get("decision_id")
                ),
            }
            return self._attach_final_holdout(resolved, context)

        # The scoped result cache is not treated as "latest" selection. It is
        # usable only when its immutable job id and every lineage field exactly
        # match the request and active workspace below.
        summary = RESULTS.get_last_summary()
        if not isinstance(summary, dict):
            return None, "The exact requested training run is unavailable. Retrain the selected candidate."
        summary_lineage = {
            "project_id": _lineage_value(summary.get("project_id")),
            "dataset_id": _lineage_value(summary.get("dataset_id")),
            "dataset_version_id": _lineage_value(summary.get("dataset_version_id")),
            "training_job_id": _lineage_value(summary.get("training_job_id")),
            "training_run_id": _lineage_value(summary.get("training_run_id")),
            "feature_manifest_version": _lineage_value(summary.get("feature_manifest_version")),
            "validation_design_id": _lineage_value(summary.get("validation_design_id")),
            "validation_design_version": _lineage_value(summary.get("validation_design_version")),
            "split_id": _lineage_value(summary.get("split_id")),
            "target": _lineage_value(summary.get("target")),
            "problem_type": _lineage_value(summary.get("problem_type")),
        }
        for field, requested_value in requested.items():
            if field == "candidate_id":
                continue
            actual = summary_lineage.get(field, "")
            if not actual:
                return None, f"The requested training run is missing its {field} binding. Retrain it."
            if actual != requested_value:
                return None, f"The requested training run does not match the exact {field}."

        ranked_matches = []
        for row in summary.get("ranked") or []:
            if not isinstance(row, dict):
                continue
            row_contract = row.get("candidate_contract")
            contract_candidate_id = (
                _lineage_value(row_contract.get("candidate_id"))
                if isinstance(row_contract, dict)
                else ""
            )
            row_candidate_id = _lineage_value(row.get("candidate_id"))
            if row_candidate_id and contract_candidate_id and row_candidate_id != contract_candidate_id:
                return None, "A candidate row contains conflicting immutable candidate identifiers."
            if (row_candidate_id or contract_candidate_id) == requested["candidate_id"]:
                ranked_matches.append(row)
        if len(ranked_matches) != 1:
            return None, "The requested candidate is not uniquely present in the exact training run."
        candidate = ranked_matches[0]
        candidate_contract = candidate.get("candidate_contract")
        if not isinstance(candidate_contract, dict):
            return None, "The requested candidate is missing its frozen candidate contract."
        try:
            assert_candidate_contract_intact(candidate_contract)
        except CandidateContractError as exc:
            return None, f"The requested candidate contract is invalid: {exc}"
        try:
            assert_selection_integrity({**candidate_contract, **candidate})
        except SelectionIntegrityError as exc:
            return None, str(exc)
        if _lineage_value(candidate.get("candidate_id")) != requested["candidate_id"]:
            return None, "The candidate row does not match the requested immutable candidate_id."
        if _lineage_value(candidate_contract.get("candidate_id")) != requested["candidate_id"]:
            return None, "The frozen candidate contract does not match the requested candidate_id."

        algorithm_id = _lineage_value(candidate_contract.get("algorithm_id"))
        if not algorithm_id or _lineage_value(candidate.get("key")) != algorithm_id:
            return None, "The candidate algorithm binding is missing or contradictory."
        training_run_id = _lineage_value(summary.get("training_run_id"))
        if not training_run_id:
            return None, "The exact requested training run is missing its immutable training_run_id."
        candidate_contract_lineage = {
            "project_id": _lineage_value(candidate_contract.get("project_id")),
            "dataset_id": _lineage_value(candidate_contract.get("dataset_id")),
            "dataset_version_id": _lineage_value(candidate_contract.get("dataset_version_id")),
            "candidate_id": _lineage_value(candidate_contract.get("candidate_id")),
            "training_job_id": _lineage_value(candidate_contract.get("training_job_id")),
            "training_run_id": _lineage_value(candidate_contract.get("training_run_id")),
            "feature_manifest_version": _lineage_value(candidate_contract.get("feature_manifest_hash")),
            "validation_design_id": _lineage_value(candidate_contract.get("validation_design_id")),
            "validation_design_version": _lineage_value(candidate_contract.get("validation_design_version")),
            "split_id": _lineage_value(candidate_contract.get("split_id")),
            "target": _lineage_value(candidate_contract.get("target_name")),
            "problem_type": _lineage_value(
                (candidate_contract.get("target_definition") or {}).get("problem_type")
                if isinstance(candidate_contract.get("target_definition"), dict)
                else ""
            ),
        }
        for field, actual in candidate_contract_lineage.items():
            if not actual:
                return None, f"The frozen candidate contract is missing its {field} binding."
            if actual != requested[field]:
                return None, f"The frozen candidate contract does not match the exact {field}."
        if _lineage_value(candidate_contract.get("candidate_state")).casefold() != "complete":
            return None, "The requested candidate is not in the immutable complete state."
        if (
            candidate.get("champion_eligible") is False
            or candidate_contract.get("champion_eligible") is False
            or _lineage_value(candidate.get("kind")).casefold() == "anomaly"
            or _lineage_value(candidate.get("target_usage")).casefold() in {"none", "unsupervised"}
        ):
            return None, "The requested candidate is unsupported for governed Evaluation and Interpretation."

        raw_results = summary.get("raw")
        raw_results = raw_results if isinstance(raw_results, dict) else {}
        raw_result = raw_results.get(algorithm_id)
        if not isinstance(raw_result, dict):
            return None, "The requested candidate has no exact persisted training result."
        if _lineage_value(raw_result.get("task")) not in ("", requested["problem_type"]):
            return None, "The candidate training result has a conflicting problem type."

        metadata = RESULTS.get_model_artifact_metadata(algorithm_id)
        artifact = RESULTS.get_model_artifact(algorithm_id)
        if artifact is None or not isinstance(metadata, dict) or not metadata:
            return None, "The requested candidate artifact is unavailable for the exact training run."
        artifact_training_job = _lineage_value(metadata.get("training_job_id"))
        artifact_training_run = _lineage_value(metadata.get("training_run_id"))
        if artifact_training_job != requested["training_job_id"]:
            return None, "The candidate artifact does not match the exact training_job_id."
        if artifact_training_run != training_run_id:
            return None, "The candidate artifact does not match the exact training_run_id."
        metadata_contract = metadata.get("candidate_contract")
        if not isinstance(metadata_contract, dict):
            return None, "The candidate artifact is missing its frozen candidate contract."
        try:
            assert_candidate_contract_intact(metadata_contract)
        except CandidateContractError as exc:
            return None, f"The candidate artifact contract is invalid: {exc}"
        if _lineage_value(metadata_contract.get("contract_hash")) != _lineage_value(candidate_contract.get("contract_hash")):
            return None, "The candidate artifact contract does not match the ranked candidate contract."
        artifact_lineage = {
            "project_id": _lineage_value(metadata.get("project_id")),
            "dataset_id": _lineage_value(metadata.get("dataset_id")),
            "dataset_version_id": _lineage_value(metadata.get("dataset_version_id")),
            "candidate_id": _lineage_value(metadata.get("candidate_id")),
            "training_job_id": artifact_training_job,
            "training_run_id": artifact_training_run,
            "feature_manifest_version": _lineage_value(metadata.get("feature_manifest_version")),
            "validation_design_id": _lineage_value(metadata.get("validation_design_id")),
            "validation_design_version": _lineage_value(metadata.get("validation_design_version")),
            "split_id": _lineage_value(metadata.get("split_id")),
            "target": _lineage_value(metadata.get("target")),
            "problem_type": _lineage_value(metadata.get("problem_type")),
        }
        for field, requested_value in requested.items():
            actual = artifact_lineage.get(field, "")
            if not actual:
                return None, f"The candidate artifact is missing its {field} binding. Retrain it."
            if actual != requested_value:
                return None, f"The candidate artifact does not match the exact {field}."
        if _lineage_value(metadata.get("model_key")) != algorithm_id:
            return None, "The candidate artifact does not match the frozen algorithm_id."

        guarded_candidate = {**candidate_contract, **candidate}
        decision, decision_error = self._locked_decision_for_candidate(
            guarded_candidate,
            context,
        )
        if decision_error:
            return None, decision_error
        resolved = {
            "lineage": {
                **requested,
                "candidate_decision_id": _lineage_value(
                    decision.get("decision_id")
                ),
            },
            "active_lineage": active,
            "summary": summary,
            "candidate": candidate,
            "candidate_contract": candidate_contract,
            "algorithm_id": algorithm_id,
            "raw_result": raw_result,
            "artifact": artifact,
            "artifact_metadata": metadata,
            "candidate_decision": decision,
        }
        return self._attach_final_holdout(resolved, context)

    @staticmethod
    def _holdout_metrics(
        task: str,
        y_true: np.ndarray,
        y_score: np.ndarray,
        *,
        n_features: int,
        threshold: float | None,
    ) -> Dict[str, Any]:
        if task == "regression":
            mse = float(mean_squared_error(y_true, y_score)) if mean_squared_error else None
            r2 = float(r2_score(y_true, y_score)) if r2_score else None
            n_obs = int(len(y_true))
            adjusted_r2 = (
                float(1 - (1 - r2) * (n_obs - 1) / (n_obs - n_features - 1))
                if r2 is not None and n_obs > n_features + 1
                else None
            )
            return {
                "mae": float(mean_absolute_error(y_true, y_score)) if mean_absolute_error else None,
                "mse": mse,
                "rmse": float(np.sqrt(mse)) if mse is not None else None,
                "r2": r2,
                "adjusted_r2": adjusted_r2,
            }
        if threshold is None:
            raise ValueError(
                "A classification final-holdout evaluation requires the exact "
                "pre-exposure threshold lock."
            )
        predicted = (y_score >= threshold).astype(int)
        auc = (
            float(roc_auc_score(y_true, y_score))
            if roc_auc_score is not None and len(np.unique(y_true)) == 2
            else None
        )
        pr_auc = (
            float(average_precision_score(y_true, y_score))
            if average_precision_score is not None and len(np.unique(y_true)) == 2
            else None
        )
        return {
            "auc": auc,
            "roc_auc": auc,
            "pr_auc": pr_auc,
            "accuracy": float(accuracy_score(y_true, predicted)) if accuracy_score else None,
            "precision": float(precision_score(y_true, predicted, zero_division=0)) if precision_score else None,
            "recall": float(recall_score(y_true, predicted, zero_division=0)) if recall_score else None,
            "f1": float(f1_score(y_true, predicted, zero_division=0)) if f1_score else None,
            "confusion_matrix": (
                confusion_matrix(y_true, predicted, labels=[0, 1]).tolist()
                if confusion_matrix is not None
                else None
            ),
        }

    def _open_final_holdout(
        self,
        resolved: Dict[str, Any],
        context: Dict[str, Any] | None,
    ) -> tuple[Dict[str, Any] | None, str]:
        """Open one exact final holdout only after immutable candidate lock.

        This is the sole boundary that turns the sealed DatasetStore holdout
        into candidate predictions.  It writes a separate exposure record and
        never mutates the training summary, ranking row, or selection decision.
        """

        lineage = resolved["lineage"]
        candidate_id = lineage["candidate_id"]
        decision = resolved.get("candidate_decision") or {}
        decision_id = _lineage_value(decision.get("decision_id"))
        candidate_contract = resolved["candidate_contract"]
        scoped_store = DATASTORE.current()
        scoped_results = RESULTS.current()
        algorithm_id = _lineage_value(resolved.get("algorithm_id"))
        registered_candidate = isinstance(resolved.get("registered_version"), dict)

        # Snapshot the exact workspace, candidate artifact, and holdout under
        # the same store -> result lock order used by preparation invalidation.
        # The durable exposure is opened before either lock is released, so a
        # split rebuild cannot interleave a new population with old lineage.
        with scoped_store.state_lock:
            with scoped_results.state_lock:
                active, active_error = self._active_evaluation_lineage()
                if active_error:
                    return None, active_error
                for field, active_value in active.items():
                    if _lineage_value(lineage.get(field)) != active_value:
                        return None, (
                            f"The active {field} changed before final-holdout "
                            "exposure. Reopen the exact governed candidate."
                        )

                split_record = scoped_store.meta.get("split_record")
                split_record = (
                    copy.deepcopy(split_record)
                    if isinstance(split_record, dict)
                    else {}
                )
                partition_id = _lineage_value(
                    split_record.get("holdout_population_id")
                    or split_record.get("final_holdout_partition_id")
                )
                if not partition_id:
                    return None, (
                        "The governed split has no exact final-holdout "
                        "partition identity."
                    )
                _, live_holdout, _, live_target = scoped_store.get_splits()
                if (
                    live_holdout is None
                    or live_target is None
                    or len(live_target) == 0
                ):
                    return None, (
                        "The exact final holdout is unavailable. Recreate the "
                        "governed split."
                    )
                X_holdout = live_holdout.copy(deep=True)
                y_holdout = pd.Series(live_target).copy(deep=True)
                snapshot_revision = int(scoped_store.data_revision)

                if registered_candidate:
                    artifact = resolved.get("artifact")
                    metadata = copy.deepcopy(
                        resolved.get("artifact_metadata") or {}
                    )
                else:
                    current_summary = scoped_results.last_training_summary
                    if (
                        not isinstance(current_summary, dict)
                        or _lineage_value(
                            current_summary.get("training_job_id")
                        )
                        != lineage["training_job_id"]
                        or _lineage_value(
                            current_summary.get("training_run_id")
                        )
                        != lineage["training_run_id"]
                    ):
                        return None, (
                            "The exact training run changed before final-holdout "
                            "exposure. Retrain the candidate."
                        )
                    current_matches = [
                        row
                        for row in current_summary.get("ranked") or []
                        if isinstance(row, dict)
                        and _lineage_value(row.get("candidate_id"))
                        == candidate_id
                    ]
                    if len(current_matches) != 1:
                        return None, (
                            "The exact candidate changed before final-holdout "
                            "exposure. Retrain the candidate."
                        )
                    current_ranked_contract = current_matches[0].get(
                        "candidate_contract"
                    )
                    if (
                        not isinstance(current_ranked_contract, dict)
                        or _lineage_value(
                            current_ranked_contract.get("contract_hash")
                        )
                        != _lineage_value(
                            candidate_contract.get("contract_hash")
                        )
                    ):
                        return None, (
                            "The ranked candidate contract changed before "
                            "final-holdout exposure. Retrain the candidate."
                        )
                    artifact = scoped_results.model_artifacts.get(algorithm_id)
                    metadata = copy.deepcopy(
                        scoped_results.model_artifact_metadata.get(
                            algorithm_id
                        )
                        or {}
                    )
                    current_contract = metadata.get("candidate_contract")
                    if (
                        artifact is None
                        or not isinstance(current_contract, dict)
                        or _lineage_value(current_contract.get("contract_hash"))
                        != _lineage_value(candidate_contract.get("contract_hash"))
                    ):
                        return None, (
                            "The exact candidate artifact changed before "
                            "final-holdout exposure. Retrain the candidate."
                        )
                if artifact is None:
                    return None, (
                        "The exact candidate artifact is unavailable for "
                        "final-holdout evaluation."
                    )

                try:
                    threshold, threshold_source = (
                        _frozen_candidate_threshold_policy(
                            candidate_contract
                        )
                    )
                except CandidateContractError as exc:
                    return None, str(exc)
                decision_threshold = decision.get("locked_threshold")
                threshold_locked_at = _lineage_value(
                    decision.get("threshold_locked_at")
                )
                if (
                    not threshold_locked_at
                    or _lineage_value(decision.get("threshold_source"))
                    != threshold_source
                    or (
                        threshold_source != "not_applicable"
                        and (
                            isinstance(decision_threshold, bool)
                            or not isinstance(
                                decision_threshold, (int, float)
                            )
                            or float(decision_threshold) != threshold
                        )
                    )
                ):
                    return None, (
                        "The exact candidate threshold does not match the "
                        "durable pre-exposure decision lock."
                    )
                exposure_identity = {
                    "project_id": lineage["project_id"],
                    "dataset_id": lineage["dataset_id"],
                    "dataset_version_id": lineage["dataset_version_id"],
                    "validation_design_id": lineage["validation_design_id"],
                    "validation_design_version_id": lineage[
                        "validation_design_version"
                    ],
                    "split_id": lineage["split_id"],
                    "final_holdout_partition_id": partition_id,
                    "candidate_decision_id": decision_id,
                    "candidate_id": candidate_id,
                    "feature_manifest_id": candidate_contract.get(
                        "feature_manifest_id"
                    ),
                    "feature_manifest_hash": candidate_contract.get(
                        "feature_manifest_hash"
                    ),
                    "treatment_manifest_id": candidate_contract.get(
                        "treatment_manifest_id"
                    ),
                    "treatment_manifest_hash": candidate_contract.get(
                        "treatment_manifest_hash"
                    ),
                    "materialization_id": candidate_contract.get(
                        "materialization_id"
                    ),
                }
                exposure_contract_hash = self._canonical_content_hash(
                    exposure_identity
                )
                exposure_id = "holdout-exposure-" + exposure_contract_hash[:24]
                opened_by = (
                    _lineage_value((context or {}).get("_actor_user_id"))
                    or "authenticated_user"
                )
                now = _utc_now_iso()
                try:
                    governance = self._governance_repository()
                    durable_exposure = governance.seal_holdout_exposure_if_absent(
                        {
                            "holdout_exposure_id": exposure_id,
                            **exposure_identity,
                            "final_holdout_status": "sealed",
                            "selection_locked_at": _lineage_value(
                                decision.get("selection_locked_at")
                            ),
                            "sealed_at": now,
                            "exposure_contract_hash": exposure_contract_hash,
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
                    durable_status = _lineage_value(
                        durable_exposure.get("final_holdout_status")
                    ).casefold()
                    if durable_status == "invalidated":
                        return None, (
                            "The exact final-holdout exposure was invalidated. "
                            "Create a new governed holdout before further "
                            "candidate work."
                        )
                    if durable_status == "sealed":
                        durable_exposure = governance.mark_holdout_opened(
                            exposure_id,
                            opened_by=opened_by,
                            opened_at=now,
                        )
                        durable_status = "opened"
                    if durable_status not in {"opened", "evaluated"}:
                        return None, (
                            "The exact final holdout is not available for "
                            "governed Evaluation."
                        )
                except Exception:
                    return None, (
                        "The durable final-holdout exposure could not be "
                        "recorded; no holdout result is available."
                    )

        existing = RESULTS.get_holdout_evaluation(candidate_id)
        if isinstance(existing, dict):
            if _lineage_value(existing.get("status")).casefold() == "invalidated":
                return None, "The final holdout exposure for this candidate was invalidated. Create a new governed holdout."
            expected = {
                "candidate_id": candidate_id,
                "candidate_decision_id": decision_id,
                "final_holdout_partition_id": partition_id,
                "project_id": lineage["project_id"],
                "dataset_id": lineage["dataset_id"],
                "dataset_version_id": lineage["dataset_version_id"],
                "split_id": lineage["split_id"],
                "holdout_exposure_id": exposure_id,
            }
            if any(_lineage_value(existing.get(key)) != value for key, value in expected.items()):
                return None, "The persisted final-holdout exposure conflicts with the exact locked candidate."
            existing["status"] = durable_status
            existing["evaluation_package_id"] = durable_exposure.get(
                "evaluation_package_id"
            )
            return existing, ""

        prior_partition_exposures = RESULTS.get_holdout_evaluations_for_partition(
            partition_id
        )
        conflicting_exposures = [
            value
            for key, value in prior_partition_exposures.items()
            if key != candidate_id
            and _lineage_value(value.get("status")).casefold()
            in {"opened", "evaluated", "invalidated"}
        ]
        if conflicting_exposures:
            return None, (
                "This final-holdout partition was already exposed for another "
                "candidate decision. Create a newly governed final holdout or "
                "classify the subsequent work as development-only."
            )

        trained_features = [
            str(value)
            for value in metadata.get("trained_feature_names") or []
        ]
        if trained_features:
            missing = [name for name in trained_features if name not in X_holdout.columns]
            if missing:
                return None, "The final holdout is missing trained predictors: " + ", ".join(missing)
            holdout_frame = X_holdout.loc[:, trained_features].copy()
        else:
            holdout_frame = X_holdout.copy()

        task = _lineage_value(lineage.get("problem_type")).casefold()
        if task == "regression":
            y_true = pd.to_numeric(pd.Series(y_holdout), errors="coerce").to_numpy(dtype=float)
            if np.isnan(y_true).any():
                return None, "The final-holdout regression target contains non-numeric or missing values."
            y_score = np.asarray(artifact.predict(holdout_frame), dtype=float)
        elif task == "classification":
            target_definition = candidate_contract.get("target_definition")
            target_definition = target_definition if isinstance(target_definition, dict) else {}
            positive_class = target_definition.get("positive_class")
            if positive_class is None:
                positive_class = candidate_contract.get("positive_class")
            if positive_class is None:
                return None, "The frozen candidate contract has no positive-class definition."
            y_true = np.asarray(
                [int(str(value) == str(positive_class)) for value in pd.Series(y_holdout)],
                dtype=int,
            )
            if len(np.unique(y_true)) != 2:
                return None, "The final holdout does not contain both governed target classes."
            positive_index = int(candidate_contract.get("positive_class_index", 1) or 1)
            if hasattr(artifact, "predict_proba"):
                probabilities = np.asarray(artifact.predict_proba(holdout_frame), dtype=float)
                artifact_classes = list(getattr(artifact, "classes_", []))
                if artifact_classes and positive_index in artifact_classes:
                    column = artifact_classes.index(positive_index)
                else:
                    column = min(max(positive_index, 0), probabilities.shape[1] - 1)
                y_score = probabilities[:, column]
            elif hasattr(artifact, "decision_function"):
                raw = np.asarray(artifact.decision_function(holdout_frame), dtype=float)
                y_score = 1.0 / (1.0 + np.exp(-np.clip(raw, -40.0, 40.0)))
            else:
                y_score = np.asarray(artifact.predict(holdout_frame), dtype=float)
            y_score = np.clip(y_score, 0.0, 1.0)
        else:
            return None, "The selected candidate has an unsupported supervised task."

        if len(y_true) != len(y_score):
            return None, "Final-holdout predictions do not match the governed population size."
        metrics = self._holdout_metrics(
            task,
            y_true,
            y_score,
            n_features=len(holdout_frame.columns),
            threshold=threshold,
        )
        opened_at = _lineage_value(durable_exposure.get("first_opened_at")) or now
        digest_payload = {
            "candidate_id": candidate_id,
            "candidate_decision_id": decision_id,
            "final_holdout_partition_id": partition_id,
            "y_true": y_true.tolist(),
            "y_score": y_score.tolist(),
        }
        prediction_digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        exposure = {
            **lineage,
            "holdout_exposure_id": exposure_id,
            "candidate_decision_id": decision_id,
            "final_holdout_partition_id": partition_id,
            "status": durable_status,
            "first_opened_at": opened_at,
            "opened_by": durable_exposure.get("opened_by") or opened_by,
            "evaluation_package_id": durable_exposure.get(
                "evaluation_package_id"
            ),
            "threshold": threshold,
            "threshold_source": threshold_source,
            "threshold_locked_at": threshold_locked_at,
            "recommendations_derived_from_final_holdout": False,
            "holdout_prediction_digest": prediction_digest,
            "metrics": metrics,
            "y_true": y_true.tolist(),
            "y_score": y_score.tolist(),
            "created_at": opened_at,
        }
        # Prediction can be expensive, so it runs outside the workspace locks.
        # Before publishing even the volatile cache, revalidate the revision,
        # exact artifact, active lineage, and durable exposure while holding
        # the same lock order as invalidation.
        with scoped_store.state_lock:
            with scoped_results.state_lock:
                if int(scoped_store.data_revision) != snapshot_revision:
                    return None, (
                        "The governed dataset changed during final-holdout "
                        "evaluation. The result was discarded."
                    )
                current_active, current_error = self._active_evaluation_lineage()
                if current_error or any(
                    _lineage_value(lineage.get(field)) != value
                    for field, value in current_active.items()
                ):
                    return None, (
                        "The governed lineage changed during final-holdout "
                        "evaluation. The result was discarded."
                    )
                if (
                    not registered_candidate
                    and scoped_results.model_artifacts.get(algorithm_id)
                    is not artifact
                ):
                    return None, (
                        "The candidate artifact changed during final-holdout "
                        "evaluation. The result was discarded."
                    )
                if not registered_candidate:
                    final_summary = scoped_results.last_training_summary
                    final_matches = [
                        row
                        for row in (
                            (final_summary or {}).get("ranked") or []
                        )
                        if isinstance(row, dict)
                        and _lineage_value(row.get("candidate_id"))
                        == candidate_id
                    ]
                    final_contract = (
                        final_matches[0].get("candidate_contract")
                        if len(final_matches) == 1
                        else None
                    )
                    if (
                        not isinstance(final_contract, dict)
                        or _lineage_value(final_contract.get("contract_hash"))
                        != _lineage_value(
                            candidate_contract.get("contract_hash")
                        )
                    ):
                        return None, (
                            "The candidate contract changed during final-holdout "
                            "evaluation. The result was discarded."
                        )
                try:
                    durable_latest = governance.get_holdout_exposure_exact(
                        holdout_exposure_id=exposure_id,
                        project_id=lineage["project_id"],
                        dataset_version_id=lineage["dataset_version_id"],
                        split_id=lineage["split_id"],
                        final_holdout_partition_id=partition_id,
                        candidate_decision_id=decision_id,
                        candidate_id=candidate_id,
                    )
                except Exception:
                    durable_latest = None
                latest_status = _lineage_value(
                    (durable_latest or {}).get("final_holdout_status")
                ).casefold()
                if latest_status not in {"opened", "evaluated"}:
                    return None, (
                        "The durable final-holdout exposure changed during "
                        "evaluation. The result was discarded."
                    )
                exposure["status"] = latest_status
                exposure["evaluation_package_id"] = (
                    durable_latest or {}
                ).get("evaluation_package_id")
                persisted, _ = scoped_results.set_holdout_evaluation_if_absent(
                    candidate_id,
                    exposure,
                )
        return persisted, ""

    def _attach_final_holdout(
        self,
        resolved: Dict[str, Any],
        context: Dict[str, Any] | None,
    ) -> tuple[Dict[str, Any] | None, str]:
        exposure, error = self._open_final_holdout(resolved, context)
        if error or not exposure:
            return None, error
        attached = dict(resolved)
        attached["holdout_exposure"] = exposure
        attached["raw_result"] = {
            **(resolved.get("raw_result") or {}),
            "task": resolved["lineage"]["problem_type"],
            "metrics": copy.deepcopy(exposure.get("metrics") or {}),
            "y_true": list(exposure.get("y_true") or []),
            "y_score": list(exposure.get("y_score") or []),
            "metric_class": "final_holdout",
            "metric_source": "final_holdout",
        }
        return attached, ""

    @staticmethod
    def _lineage_digest(prefix: str, payload: Dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"

    @staticmethod
    def _canonical_content_hash(payload: Dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _evaluation_package_identity(
        self,
        lineage: Dict[str, str],
        payload: Dict[str, Any],
        analysis_type: str,
    ) -> tuple[str, str, Dict[str, Any], str]:
        normalized_analysis_type = _lineage_value(analysis_type)
        completion_content_hash = self._canonical_content_hash(payload)
        evaluation_configuration = (
            copy.deepcopy(payload.get("evaluation_configuration"))
            if isinstance(payload.get("evaluation_configuration"), dict)
            else {}
        )
        holdout_prediction_digest = _lineage_value(
            payload.get("holdout_prediction_digest")
        )
        identity: Dict[str, Any] = {
            **lineage,
            "candidate_decision_id": _lineage_value(
                payload.get("candidate_decision_id")
            ),
            "final_holdout_partition_id": _lineage_value(
                payload.get("final_holdout_partition_id")
            ),
            "selection_evidence": copy.deepcopy(
                payload.get("selection_evidence") or {}
            ),
            "holdout_exposure": copy.deepcopy(
                payload.get("holdout_exposure") or {}
            ),
            "analysis_type": normalized_analysis_type,
            "completion_content_hash": completion_content_hash,
        }
        if normalized_analysis_type == "command_center":
            identity.update(
                {
                    "evaluation_configuration": evaluation_configuration,
                    "holdout_prediction_digest": holdout_prediction_digest,
                }
            )
        return (
            self._lineage_digest("evalpkg", identity),
            completion_content_hash,
            evaluation_configuration,
            holdout_prediction_digest,
        )

    @staticmethod
    def _command_center_is_complete(payload: Any) -> bool:
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return False
        problem_type = _lineage_value(payload.get("problem_type")).casefold()
        if problem_type == "regression":
            stability = payload.get("stability")
            metrics = (
                stability.get("test_metrics")
                if isinstance(stability, dict)
                else None
            )
            return bool(
                isinstance(metrics, dict)
                and all(metrics.get(key) is not None for key in ("rmse", "mae", "r2"))
                and _lineage_value(payload.get("holdout_prediction_digest"))
                and int(payload.get("observation_count") or 0) > 0
            )
        threshold = payload.get("threshold")
        lift = payload.get("lift")
        calibration = payload.get("calibration")
        stability = payload.get("stability")
        return bool(
            isinstance(threshold, dict)
            and isinstance(threshold.get("confusion"), list)
            and isinstance(lift, dict)
            and isinstance(lift.get("deciles"), list)
            and isinstance(calibration, dict)
            and isinstance(stability, dict)
            and isinstance(stability.get("test_metrics"), dict)
            and _lineage_value(payload.get("holdout_prediction_digest"))
            and int(payload.get("observation_count") or 0) > 0
        )

    @staticmethod
    def _evaluation_contract_bindings(
        candidate_contract: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "target_contract_id": _lineage_value(
                candidate_contract.get("target_contract_id")
            ),
            "target_definition": copy.deepcopy(
                candidate_contract.get("target_definition")
            ),
            "feature_manifest_id": _lineage_value(
                candidate_contract.get("feature_manifest_id")
            ),
            "feature_manifest_hash": _lineage_value(
                candidate_contract.get("feature_manifest_hash")
            ),
            "predictor_manifest_hash": _lineage_value(
                candidate_contract.get("predictor_manifest_hash")
            ),
            "treatment_manifest_hash": _lineage_value(
                candidate_contract.get("treatment_manifest_hash")
            ),
            "selection_metric": copy.deepcopy(
                candidate_contract.get("selection_metric") or {}
            ),
            "selection_integrity_status": _lineage_value(
                candidate_contract.get("selection_integrity_status")
            ),
            "holdout_isolation_status": _lineage_value(
                candidate_contract.get("holdout_isolation_status")
            ),
        }

    def _persist_completed_evaluation_package(
        self,
        *,
        package: Dict[str, Any],
        lineage: Dict[str, str],
        candidate_contract: Dict[str, Any],
        decision: Dict[str, Any],
        exposure: Dict[str, Any],
        actor_user_id: str,
    ) -> tuple[Dict[str, Any] | None, str]:
        """Durably commit package evidence before the UI can report success."""

        package_id = _lineage_value(package.get("evaluation_package_id"))
        exposure_id = _lineage_value(exposure.get("holdout_exposure_id"))
        selection_metric = package.get("selection_metric")
        selection_metric = (
            selection_metric if isinstance(selection_metric, dict) else {}
        )
        final_evidence = package.get("final_holdout_evidence")
        final_evidence = (
            final_evidence if isinstance(final_evidence, dict) else {}
        )
        selection_evidence = package.get("selection_evidence")
        selection_evidence = (
            selection_evidence if isinstance(selection_evidence, dict) else {}
        )
        threshold_locked_at = _lineage_value(
            decision.get("threshold_locked_at")
        )
        threshold_policy = package.get("threshold_policy")
        threshold_policy = (
            threshold_policy if isinstance(threshold_policy, dict) else {}
        )
        threshold_policy_hash = self._canonical_content_hash(
            threshold_policy
        )
        selection_metric_created_at = _lineage_value(
            selection_metric.get("created_at")
        )
        out_of_fold_artifact_id = _lineage_value(
            selection_metric.get("out_of_fold_prediction_artifact_id")
        )
        selected_candidate_contract_hash = _lineage_value(
            candidate_contract.get("contract_hash")
        )
        holdout_exposed_at = _lineage_value(exposure.get("first_opened_at"))
        required = {
            "evaluation_package_id": package_id,
            "holdout_exposure_id": exposure_id,
            "selection metric name": selection_metric.get(
                "selection_metric_name"
            )
            or selection_metric.get("name"),
            "selection metric value": selection_metric.get(
                "selection_metric_value"
            )
            if selection_metric.get("selection_metric_value") is not None
            else selection_metric.get("value"),
            "selection metric source": selection_metric.get(
                "selection_metric_source"
            )
            or selection_metric.get("source"),
            "selection metric created_at": selection_metric_created_at,
            "out-of-fold prediction artifact": out_of_fold_artifact_id,
            "selected candidate contract hash": selected_candidate_contract_hash,
            "threshold_locked_at": threshold_locked_at,
            "threshold policy hash": threshold_policy_hash,
            "holdout_exposed_at": holdout_exposed_at,
        }
        if any(value is None or value == "" for value in required.values()):
            return None, (
                "The completed Evaluation package is missing durable governance "
                "evidence: "
                + ", ".join(
                    label
                    for label, value in required.items()
                    if value is None or value == ""
                )
                + "."
            )
        if (
            threshold_policy
            != {
                "locked_threshold": decision.get("locked_threshold"),
                "threshold_source": decision.get("threshold_source"),
                "threshold_locked_at": decision.get(
                    "threshold_locked_at"
                ),
                "selection_threshold_tuned": False,
            }
            or threshold_policy_hash
            != _lineage_value(decision.get("threshold_policy_hash"))
            or _lineage_value(package.get("threshold_policy_hash"))
            != threshold_policy_hash
            or final_evidence.get("locked_threshold")
            != decision.get("locked_threshold")
            or _lineage_value(final_evidence.get("threshold_source"))
            != _lineage_value(decision.get("threshold_source"))
        ):
            return None, (
                "The completed Evaluation package threshold policy does not "
                "match the immutable pre-exposure candidate decision."
            )
        final_metrics = final_evidence.get("metrics")
        final_metrics = final_metrics if isinstance(final_metrics, dict) else {}
        selection_metric_name = required["selection metric name"]
        selection_metric_value = required["selection metric value"]
        selection_metric_source = required["selection metric source"]
        selection_partition_id = selection_metric.get(
            "selection_partition_id"
        ) or selection_metric.get("partition_id")
        metric_definitions = {
            "selection": {
                "name": selection_metric_name,
                "metric_class": "selection",
                "source": selection_metric_source,
                "partition_id": selection_partition_id,
            },
            "final_holdout": {
                str(name): {
                    "metric_class": "final_holdout",
                    "source": "final_holdout",
                    "partition_id": exposure.get(
                        "final_holdout_partition_id"
                    ),
                }
                for name in sorted(final_metrics)
            },
        }
        content_hash = self._canonical_content_hash(package)
        package_contract_hash = self._canonical_content_hash(
            {
                "evaluation_package_id": package_id,
                "completion_content_hash": package.get(
                    "completion_content_hash"
                ),
                "holdout_prediction_digest": package.get(
                    "holdout_prediction_digest"
                ),
                "candidate_decision_id": decision.get("decision_id"),
                "holdout_exposure_id": exposure_id,
                "content_hash": content_hash,
            }
        )
        decision_actor = decision.get("actor")
        if isinstance(decision_actor, dict):
            decision_actor = decision_actor.get("user_id")
        canonical_lineage = {
            **dict(lineage),
            "validation_design_version_id": lineage[
                "validation_design_version"
            ],
            "feature_manifest_id": candidate_contract.get(
                "feature_manifest_id"
            ),
            "feature_manifest_hash": candidate_contract.get(
                "feature_manifest_hash"
            ),
            "treatment_manifest_id": candidate_contract.get(
                "treatment_manifest_id"
            ),
            "treatment_manifest_hash": candidate_contract.get(
                "treatment_manifest_hash"
            ),
            "materialization_id": candidate_contract.get("materialization_id")
            or decision.get("materialization_id"),
            "evaluation_package_id": package_id,
            "holdout_exposure_id": exposure_id,
            "final_holdout_partition_id": exposure.get(
                "final_holdout_partition_id"
            ),
        }
        record = {
            "evaluation_package_id": package_id,
            "package_status": "complete",
            "project_id": lineage["project_id"],
            "dataset_id": lineage["dataset_id"],
            "dataset_version_id": lineage["dataset_version_id"],
            "feature_manifest_id": candidate_contract.get(
                "feature_manifest_id"
            ),
            "feature_manifest_hash": candidate_contract.get(
                "feature_manifest_hash"
            ),
            "treatment_manifest_id": candidate_contract.get(
                "treatment_manifest_id"
            ),
            "treatment_manifest_hash": candidate_contract.get(
                "treatment_manifest_hash"
            ),
            "materialization_id": candidate_contract.get("materialization_id"),
            "validation_design_id": lineage["validation_design_id"],
            "validation_design_version_id": lineage[
                "validation_design_version"
            ],
            "split_id": lineage["split_id"],
            "training_job_id": lineage["training_job_id"],
            "training_run_id": lineage["training_run_id"],
            "candidate_id": lineage["candidate_id"],
            "selected_candidate_contract_hash": selected_candidate_contract_hash,
            "candidate_decision_id": decision.get("decision_id"),
            "holdout_exposure_id": exposure_id,
            "final_holdout_partition_id": exposure.get(
                "final_holdout_partition_id"
            ),
            "selection_metric_name": selection_metric_name,
            "selection_metric_value": selection_metric_value,
            "selection_metric_source": selection_metric_source,
            "selection_metric_created_at": selection_metric_created_at,
            "out_of_fold_prediction_artifact_id": out_of_fold_artifact_id,
            "selection_integrity_status": "verified",
            "selection_evidence_json": {
                **selection_evidence,
                "selection_metric_created_at": selection_metric_created_at,
                "out_of_fold_prediction_artifact_id": out_of_fold_artifact_id,
            },
            "final_holdout_evidence_json": final_evidence,
            "metric_definitions_json": metric_definitions,
            "threshold_policy_json": {
                **threshold_policy,
                "threshold_policy_hash": threshold_policy_hash,
            },
            "locked_threshold": decision.get("locked_threshold"),
            "threshold_source": decision.get("threshold_source"),
            "threshold_policy_hash": threshold_policy_hash,
            "isolation_evidence_json": {
                "candidate_decision_status": decision.get("status"),
                "selection_locked_at": decision.get("selection_locked_at"),
                "final_holdout_status": "evaluated",
                "holdout_exposed_at": holdout_exposed_at,
                "recommendations_derived_from_final_holdout": False,
                "ranking_or_tuning_consumed_final_holdout": False,
            },
            "canonical_lineage_json": canonical_lineage,
            "holdout_isolation_status": "verified",
            "final_holdout_status": "evaluated",
            "threshold_locked_at": threshold_locked_at,
            "holdout_exposed_at": holdout_exposed_at,
            "recommendations_derived_from_final_holdout": False,
            "package_integrity_status": "verified",
            "evaluation_package_contract_hash": package_contract_hash,
            "content_hash": content_hash,
            "package_payload_json": package,
            "created_by": _lineage_value(actor_user_id)
            or _lineage_value(decision_actor),
            "created_at": package.get("created_at"),
        }
        try:
            governance = self._governance_repository()
            durable_package = governance.complete_evaluation_package(
                record,
                exposure_id=exposure_id,
                evaluated_at=package.get("completed_at"),
            )
            durable_exposure = governance.get_holdout_exposure_exact(
                holdout_exposure_id=exposure_id,
                project_id=lineage["project_id"],
                dataset_version_id=lineage["dataset_version_id"],
                split_id=lineage["split_id"],
                final_holdout_partition_id=exposure.get(
                    "final_holdout_partition_id"
                ),
                candidate_decision_id=decision.get("decision_id"),
                candidate_id=lineage["candidate_id"],
            )
        except Exception:
            return None, (
                "The completed Evaluation package could not be committed to the "
                "authoritative governance registry."
            )
        if (
            _lineage_value(durable_package.get("package_status")).casefold()
            != "complete"
            or _lineage_value(
                durable_package.get("package_integrity_status")
            ).casefold()
            != "verified"
            or _lineage_value(
                durable_exposure.get("final_holdout_status")
            ).casefold()
            != "evaluated"
            or _lineage_value(durable_exposure.get("evaluation_package_id"))
            != package_id
        ):
            return None, (
                "The durable Evaluation package or final-holdout exposure did "
                "not reach its verified terminal state."
            )
        return durable_package, ""

    def _completed_evaluation_package(
        self,
        lineage: Dict[str, str],
        evaluation_package_id: str,
        registered_version: Dict[str, Any] | None = None,
        candidate_contract: Dict[str, Any] | None = None,
    ) -> tuple[Dict[str, Any] | None, str]:
        requested_package_id = _lineage_value(evaluation_package_id)
        if not requested_package_id:
            return None, (
                "An explicit evaluation_package_id is required; ATLAS will not select "
                "a latest or lineage-only evaluation package."
            )
        package = RESULTS.get_evaluation_package(requested_package_id)
        try:
            governance = self._governance_repository()
            durable_row = governance.get_evaluation_package(
                requested_package_id
            )
        except Exception:
            return None, "The durable Evaluation-package registry is unavailable."
        if not isinstance(durable_row, dict):
            if isinstance(registered_version, dict) and _lineage_value(
                registered_version.get("evaluationPackageId")
            ) != requested_package_id:
                return None, (
                    "The registered model version does not bind the requested "
                    "evaluation_package_id."
                )
            return None, (
                "The requested Evaluation package is absent from the "
                "authoritative governance registry."
            )
        expected = {
            "project_id": lineage.get("project_id"),
            "dataset_id": lineage.get("dataset_id"),
            "dataset_version_id": lineage.get("dataset_version_id"),
            "training_run_id": lineage.get("training_run_id"),
            "candidate_id": lineage.get("candidate_id"),
            "candidate_decision_id": lineage.get("candidate_decision_id"),
        }
        if any(
            _lineage_value(durable_row.get(field))
            != _lineage_value(value)
            for field, value in expected.items()
        ):
            return None, (
                "The durable Evaluation package does not match the exact "
                "candidate lineage."
            )
        durable_payload = durable_row.get("package_payload_json")
        if not isinstance(durable_payload, dict):
            return None, (
                "The durable Evaluation package has no recoverable immutable "
                "evidence payload."
            )
        durable_exposure = governance.get_holdout_exposure(
            _lineage_value(durable_row.get("holdout_exposure_id"))
        )
        if (
            not isinstance(durable_exposure, dict)
            or _lineage_value(
                durable_exposure.get("final_holdout_status")
            ).casefold()
            != "evaluated"
            or _lineage_value(
                durable_exposure.get("evaluation_package_id")
            )
            != requested_package_id
        ):
            return None, (
                "The durable Evaluation package is not bound to an exact "
                "evaluated, non-invalidated holdout exposure."
            )
        if package is not None and package != durable_payload:
            return None, (
                "The volatile Evaluation package conflicts with its immutable "
                "durable payload."
            )
        if package is None:
            persisted, _ = RESULTS.set_evaluation_package_if_absent(
                requested_package_id,
                durable_payload,
            )
            package = persisted
        command_center = (
            ((package or {}).get("analyses") or {}).get("command_center") or {}
        ).get("payload")
        if not isinstance(package, dict):
            return None, "A completed exact evaluation package is required before promotion or interpretation."
        if not isinstance(command_center, dict):
            return None, "The requested evaluation package has no completed command-center payload."
        if not isinstance(candidate_contract, dict):
            return None, "The requested evaluation package cannot be verified without its frozen candidate contract."
        expected_contract_bindings = self._evaluation_contract_bindings(
            candidate_contract
        )
        (
            expected_package_id,
            expected_content_hash,
            expected_configuration,
            expected_holdout_digest,
        ) = self._evaluation_package_identity(
            lineage,
            command_center,
            "command_center",
        )
        if (
            requested_package_id != expected_package_id
            or package.get("evaluation_package_id") != expected_package_id
            or package.get("status") != "complete"
            or package.get("completion_analysis") != "command_center"
            or package.get("evaluation_population") != "governed_holdout"
            or package.get("completion_content_hash") != expected_content_hash
            or package.get("evaluation_configuration") != expected_configuration
            or package.get("governed_candidate_contract")
            != expected_contract_bindings
            or command_center.get("governed_candidate_contract")
            != expected_contract_bindings
            or _lineage_value(package.get("holdout_prediction_digest"))
            != expected_holdout_digest
            or not self._command_center_is_complete(command_center)
            or any(
                _lineage_value(package.get(field)) != value
                for field, value in lineage.items()
            )
        ):
            return None, "The persisted evaluation package is incomplete or does not match the exact candidate lineage."
        guarded_candidate = {**candidate_contract}
        decision, decision_error = self._locked_decision_for_candidate(
            guarded_candidate,
            {
                "candidate_decision_id": lineage.get(
                    "candidate_decision_id"
                )
            },
        )
        if decision_error or not decision:
            return None, decision_error
        try:
            assert_evaluation_package_integrity(
                package,
                decision=decision,
                candidate=guarded_candidate,
            )
        except SelectionIntegrityError as exc:
            return None, str(exc)
        return package, ""

    def bind_evaluation_package(
        self,
        model_name: str,
        context: Dict[str, Any] | None,
        payload: Dict[str, Any],
        analysis_type: str,
        actor_user_id: str = "",
    ) -> Dict[str, Any]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return self._lineage_error(error, model_name)
        if not payload.get("ok"):
            return payload
        lineage = dict(resolved["lineage"])
        normalized_analysis_type = _lineage_value(analysis_type)
        immutable_payload = copy.deepcopy(payload)
        decision = resolved.get("candidate_decision") or {}
        exposure = resolved.get("holdout_exposure") or {}
        selection_metric = copy.deepcopy(
            resolved["candidate_contract"].get("selection_metric") or {}
        )
        if not selection_metric:
            return self._lineage_error(
                "The candidate has no verified selection evidence.",
                model_name,
            )
        final_metrics = copy.deepcopy(
            ((immutable_payload.get("stability") or {}).get("test_metrics") or {})
        )
        exposure_status = (
            "evaluated"
            if normalized_analysis_type == "command_center"
            and self._command_center_is_complete(immutable_payload)
            else "opened"
        )
        threshold_configuration = resolved["candidate_contract"].get(
            "threshold_configuration"
        )
        threshold_configuration = (
            threshold_configuration
            if isinstance(threshold_configuration, dict)
            else {}
        )
        threshold_policy = {
            "locked_threshold": threshold_configuration.get(
                "locked_threshold"
            ),
            "threshold_source": threshold_configuration.get(
                "threshold_source"
            ),
            "threshold_locked_at": threshold_configuration.get(
                "threshold_locked_at"
            ),
            "selection_threshold_tuned": False,
        }
        threshold_policy_hash = self._canonical_content_hash(
            threshold_policy
        )
        if (
            _lineage_value(decision.get("threshold_policy_hash"))
            != threshold_policy_hash
        ):
            return self._lineage_error(
                "The candidate threshold policy does not match the immutable decision lock.",
                model_name,
            )
        immutable_payload.update(
            {
                "candidate_decision_id": _lineage_value(decision.get("decision_id")),
                "selection_evidence": {
                    "selection_metric": selection_metric,
                    "selection_metric_created_at": selection_metric.get(
                        "created_at"
                    ),
                    "out_of_fold_prediction_artifact_id": selection_metric.get(
                        "out_of_fold_prediction_artifact_id"
                    ),
                    "selection_integrity_status": "verified",
                    "holdout_isolation_status": "verified",
                },
                "final_holdout_partition_id": _lineage_value(
                    exposure.get("final_holdout_partition_id")
                ),
                "final_holdout_evidence": {
                    "metric_source": "final_holdout",
                    "metric_class": "final_holdout",
                    "final_holdout_partition_id": _lineage_value(
                        exposure.get("final_holdout_partition_id")
                    ),
                    "metrics": final_metrics,
                    "locked_threshold": exposure.get("threshold"),
                    "threshold_source": exposure.get("threshold_source"),
                    "holdout_prediction_digest": exposure.get(
                        "holdout_prediction_digest"
                    ),
                    "created_by": exposure.get("opened_by"),
                    "created_at": exposure.get("first_opened_at"),
                },
                "holdout_exposure": {
                    "holdout_exposure_id": exposure.get(
                        "holdout_exposure_id"
                    ),
                    "status": exposure_status,
                    "first_opened_at": exposure.get("first_opened_at"),
                    "opened_by": exposure.get("opened_by"),
                    "candidate_decision_id": exposure.get(
                        "candidate_decision_id"
                    ),
                    "evaluation_package_id": None,
                },
                "selection_integrity_status": "verified",
                "holdout_isolation_status": "verified",
                "isolation_status": "verified",
                "recommendations_derived_from_final_holdout": False,
                "threshold_policy": threshold_policy,
                "threshold_policy_hash": threshold_policy_hash,
            }
        )
        contract_bindings = self._evaluation_contract_bindings(
            resolved["candidate_contract"]
        )
        supplied_bindings = immutable_payload.get("governed_candidate_contract")
        if supplied_bindings not in (None, contract_bindings):
            return self._lineage_error(
                "The evaluation payload conflicts with the frozen target or feature-manifest contract.",
                model_name,
            )
        immutable_payload["governed_candidate_contract"] = contract_bindings
        (
            package_id,
            completion_content_hash,
            evaluation_configuration,
            holdout_prediction_digest,
        ) = self._evaluation_package_identity(
            lineage,
            immutable_payload,
            normalized_analysis_type,
        )
        bound_exposure_package_id = _lineage_value(
            exposure.get("evaluation_package_id")
        )
        if (
            bound_exposure_package_id
            and bound_exposure_package_id != package_id
        ):
            return self._lineage_error(
                "The final holdout is already bound to another Evaluation package; its locked reporting configuration is immutable.",
                model_name,
            )
        now = _utc_now_iso()
        existing = RESULTS.get_evaluation_package(package_id) or {}
        if existing:
            existing_analysis = (
                ((existing.get("analyses") or {}).get(normalized_analysis_type) or {}).get("payload")
            )
            if (
                any(
                    _lineage_value(existing.get(field)) != value
                    for field, value in lineage.items()
                )
                or existing.get("completion_content_hash") != completion_content_hash
                or existing_analysis != immutable_payload
            ):
                return self._lineage_error(
                    "The content-addressed evaluation package conflicts with persisted immutable content.",
                    model_name,
                )
            if _lineage_value(existing.get("status")).casefold() == "complete":
                _, durable_error = self._persist_completed_evaluation_package(
                    package=existing,
                    lineage=lineage,
                    candidate_contract=resolved["candidate_contract"],
                    decision=decision,
                    exposure=exposure,
                    actor_user_id=actor_user_id,
                )
                if durable_error:
                    return self._lineage_error(durable_error, model_name)
            return {
                **immutable_payload,
                **lineage,
                "evaluation_package_id": package_id,
                "lineage": lineage,
                "evaluation_package": existing,
            }
        try:
            durable_existing = self._governance_repository().get_evaluation_package(
                package_id
            )
        except Exception:
            return self._lineage_error(
                "The durable Evaluation-package registry is unavailable.",
                model_name,
            )
        if isinstance(durable_existing, dict):
            durable_payload = durable_existing.get("package_payload_json")
            durable_analysis = (
                ((durable_payload or {}).get("analyses") or {}).get(
                    normalized_analysis_type
                )
                or {}
            ).get("payload")
            expected_durable = {
                "project_id": lineage["project_id"],
                "dataset_id": lineage["dataset_id"],
                "dataset_version_id": lineage["dataset_version_id"],
                "training_run_id": lineage["training_run_id"],
                "candidate_id": lineage["candidate_id"],
                "candidate_decision_id": immutable_payload[
                    "candidate_decision_id"
                ],
                "holdout_exposure_id": exposure.get(
                    "holdout_exposure_id"
                ),
            }
            if (
                not isinstance(durable_payload, dict)
                or any(
                    _lineage_value(durable_existing.get(field))
                    != _lineage_value(value)
                    for field, value in expected_durable.items()
                )
                or durable_payload.get("completion_content_hash")
                != completion_content_hash
                or durable_analysis != immutable_payload
            ):
                return self._lineage_error(
                    "The durable content-addressed Evaluation package conflicts with the exact request.",
                    model_name,
                )
            _, durable_error = self._persist_completed_evaluation_package(
                package=durable_payload,
                lineage=lineage,
                candidate_contract=resolved["candidate_contract"],
                decision=decision,
                exposure=exposure,
                actor_user_id=actor_user_id,
            )
            if durable_error:
                return self._lineage_error(durable_error, model_name)
            persisted, _ = RESULTS.set_evaluation_package_if_absent(
                package_id,
                durable_payload,
            )
            try:
                RESULTS.mark_holdout_evaluated(
                    lineage["candidate_id"],
                    evaluation_package_id=package_id,
                    evaluated_at=durable_payload.get("completed_at") or now,
                )
            except ValueError as exc:
                return self._lineage_error(str(exc), model_name)
            return {
                **immutable_payload,
                **lineage,
                "evaluation_package_id": package_id,
                "lineage": lineage,
                "evaluation_package": persisted,
            }
        analyses = {
            normalized_analysis_type: {
            "analysis_type": normalized_analysis_type,
            "completed_at": now,
                "payload": immutable_payload,
            }
        }
        command_center = (
            (analyses.get("command_center") or {}).get("payload")
            if isinstance(analyses.get("command_center"), dict)
            else None
        )
        complete = self._command_center_is_complete(command_center)
        package = {
            "evaluation_package_id": package_id,
            "artifact_type": "evaluation_package",
            "status": "complete" if complete else "in_progress",
            "completion_analysis": "command_center" if complete else None,
            "evaluation_population": "governed_holdout",
            "created_at": now,
            "updated_at": now,
            "completed_at": now if complete else None,
            "actor_user_id": _lineage_value(actor_user_id) or None,
            "completion_content_hash": completion_content_hash,
            "evaluation_configuration": evaluation_configuration,
            "governed_candidate_contract": contract_bindings,
            "holdout_prediction_digest": holdout_prediction_digest,
            "candidate_decision_id": immutable_payload[
                "candidate_decision_id"
            ],
            "holdout_exposure_id": exposure.get("holdout_exposure_id"),
            "final_holdout_partition_id": immutable_payload[
                "final_holdout_partition_id"
            ],
            "selection_evidence": immutable_payload["selection_evidence"],
            "final_holdout_evidence": immutable_payload[
                "final_holdout_evidence"
            ],
            "holdout_exposure": immutable_payload["holdout_exposure"],
            "selection_metric": selection_metric,
            "selection_integrity_status": "verified",
            "holdout_isolation_status": "verified",
            "isolation_status": "verified",
            "recommendations_derived_from_final_holdout": False,
            "threshold_policy": immutable_payload["threshold_policy"],
            "threshold_policy_hash": immutable_payload[
                "threshold_policy_hash"
            ],
            "analysis_types": sorted(analyses),
            "analyses": analyses,
            "holdout": {
                "observation_count": (command_center or {}).get("observation_count"),
                "event_count": (command_center or {}).get("event_count"),
                "event_rate": (command_center or {}).get("event_rate"),
                "test_status": (command_center or {}).get("test_status"),
                "oot_status": (command_center or {}).get("oot_status"),
            },
            "metrics": ((command_center or {}).get("stability") or {}).get("test_metrics") or {},
            "threshold": (command_center or {}).get("threshold") or {},
            "confusion": ((command_center or {}).get("threshold") or {}).get("confusion") or [],
            "calibration": (command_center or {}).get("calibration") or {},
            "lift": (command_center or {}).get("lift") or {},
            **lineage,
        }
        if complete:
            _, durable_error = self._persist_completed_evaluation_package(
                package=package,
                lineage=lineage,
                candidate_contract=resolved["candidate_contract"],
                decision=decision,
                exposure=exposure,
                actor_user_id=actor_user_id,
            )
            if durable_error:
                return self._lineage_error(durable_error, model_name)
        persisted_package, created = RESULTS.set_evaluation_package_if_absent(
            package_id,
            package,
        )
        if not created:
            persisted_analysis = (
                ((persisted_package.get("analyses") or {}).get(normalized_analysis_type) or {}).get("payload")
            )
            if (
                persisted_package.get("completion_content_hash")
                != completion_content_hash
                or persisted_analysis != immutable_payload
            ):
                return self._lineage_error(
                    "The content-addressed evaluation package conflicts with concurrently persisted immutable content.",
                    model_name,
                )
        package = persisted_package
        if complete:
            try:
                RESULTS.mark_holdout_evaluated(
                    lineage["candidate_id"],
                    evaluation_package_id=package_id,
                    evaluated_at=now,
                )
            except ValueError as exc:
                return self._lineage_error(str(exc), model_name)
        return {
            **immutable_payload,
            **lineage,
            "evaluation_package_id": package_id,
            "lineage": lineage,
            "evaluation_package": package,
        }

    def bind_interpretation_artifact(
        self,
        model_name: str,
        context: Dict[str, Any] | None,
        payload: Dict[str, Any],
        analysis_type: str,
        evaluation_package_id: str,
    ) -> Dict[str, Any]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return self._lineage_error(error, model_name)
        if not payload.get("ok"):
            return payload
        lineage = dict(resolved["lineage"])
        completed_package, package_error = self._completed_evaluation_package(
            lineage,
            evaluation_package_id,
            (context or {}).get("_registered_version"),
            resolved["candidate_contract"],
        )
        if package_error:
            return self._lineage_error(package_error, model_name)
        evaluation_package_id = str(completed_package["evaluation_package_id"])
        artifact_id = self._lineage_digest(
            "interpretation",
            {
                **lineage,
                "evaluation_package_id": evaluation_package_id,
                "analysis_type": _lineage_value(analysis_type),
            },
        )
        artifact = {
            "interpretation_artifact_id": artifact_id,
            "artifact_type": "interpretation_artifact",
            "analysis_type": _lineage_value(analysis_type),
            "evaluation_package_id": evaluation_package_id,
            "evaluation_package": completed_package,
            "evaluation_population": "governed_holdout",
            **lineage,
        }
        return {
            **payload,
            **lineage,
            "evaluation_package_id": evaluation_package_id,
            "interpretation_artifact_id": artifact_id,
            "lineage": lineage,
            "interpretation_artifact": artifact,
        }

    def registry_promotion_handoff(
        self,
        model_name: str,
        context: Dict[str, Any] | None,
        metadata: Dict[str, Any],
        evaluation_package_id: str,
    ) -> Dict[str, Any]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return {"ready": False, "error": error}
        lineage = dict(resolved["lineage"])
        completed_package, package_error = self._completed_evaluation_package(
            lineage,
            evaluation_package_id,
            candidate_contract=resolved["candidate_contract"],
        )
        if package_error:
            return {"ready": False, "error": package_error}
        evaluation_package_id = str(completed_package["evaluation_package_id"])
        candidate_decision_id = _lineage_value(
            (resolved.get("candidate_decision") or {}).get("decision_id")
        )
        idempotency_key = self._lineage_digest(
            "promotion",
            {
                **lineage,
                "candidate_decision_id": candidate_decision_id,
                "evaluation_package_id": evaluation_package_id,
            },
        )
        candidate = resolved["candidate"]
        candidate_contract = resolved["candidate_contract"]
        summary = resolved["summary"]
        return {
            "ready": True,
            "registry_persistence": "delegated",
            "idempotency_key": idempotency_key,
            "evaluation_package_id": evaluation_package_id,
            "evaluation_package": completed_package,
            "exact_version_contract": {
                **lineage,
                "candidate_decision_id": candidate_decision_id,
            },
            "lineage": {
                "projectId": lineage["project_id"],
                "datasetId": lineage["dataset_id"],
                "datasetVersionId": lineage["dataset_version_id"],
                "candidateId": lineage["candidate_id"],
                "trainingJobId": lineage["training_job_id"],
                "trainingRunId": lineage["training_run_id"],
                "featureManifestVersion": lineage["feature_manifest_version"],
                "validationDesignId": lineage["validation_design_id"],
                "validationDesignVersion": lineage["validation_design_version"],
                "splitId": lineage["split_id"],
                "target": lineage["target"],
                "problemType": lineage["problem_type"],
                "evaluationPackageId": evaluation_package_id,
                "candidateDecisionId": candidate_decision_id,
            },
            "candidate_decision_id": candidate_decision_id,
            "candidate_id": lineage["candidate_id"],
            "training_job_id": lineage["training_job_id"],
            "training_run_id": lineage["training_run_id"],
            "algorithm_id": resolved["algorithm_id"],
            "algorithm_version": candidate_contract.get("algorithm_version"),
            "candidate_contract": candidate_contract,
            "hyperparameters": candidate_contract.get("hyperparameter_manifest") or candidate.get("best_params") or {},
            "training_parameters": {
                "kFolds": summary.get("k_folds"),
                "calibrate": summary.get("calibrate"),
                "gridSearch": summary.get("grid_search"),
                "gridSearchLevel": summary.get("grid_search_level"),
            },
            "evaluation_summary": completed_package,
            "promotion_metadata": {
                "source": "evaluation",
                "status": "proposed",
                "model_name": metadata.get("name") or lineage["candidate_id"],
                "metrics": metadata.get("metrics") or {},
            },
            "consume_response_fields": ["modelVersion", "promotion"],
        }

    @staticmethod
    def _active_model_binding(expected: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Return the governed workspace identity that a model may be bound to.

        Canonical active state is authoritative. Legacy source metadata and a
        resident training summary never fill missing dataset identity fields.
        """
        expected = expected or {}
        manifest = DATASTORE.meta.get("feature_manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        split_record = DATASTORE.meta.get("split_record")
        split_record = split_record if isinstance(split_record, dict) else {}
        validation_design = split_record.get("validation_design")
        validation_design = validation_design if isinstance(validation_design, dict) else {}
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        split_materialized = all(value is not None for value in (X_train, X_test, y_train, y_test))

        dataset_version_id = _lineage_value(DATASTORE.meta.get("dataset_version_id"))

        return {
            "project_id": _lineage_value(DATASTORE.meta.get("project_id")),
            "dataset_id": _lineage_value(DATASTORE.meta.get("dataset_id")),
            "dataset_version_id": dataset_version_id,
            "dataset_version": dataset_version_id,
            "target": _lineage_value(DATASTORE.target),
            "problem_type": _lineage_value(expected.get("problem_type")),
            "feature_manifest_version": _lineage_value(manifest.get("manifest_hash")),
            "split_id": _lineage_value(split_record.get("split_id")) if split_materialized else "",
            "split_materialized": split_materialized,
            "validation_design_id": _lineage_value(validation_design.get("validation_design_id")),
            "validation_design_version": _lineage_value(validation_design.get("design_version")),
            "training_job_id": _lineage_value(expected.get("training_job_id")),
        }

    def _final_model_context_mismatch(
        self,
        metadata: Dict[str, Any] | None,
        expected: Dict[str, Any] | None = None,
    ) -> str:
        """Fail closed when a final artifact is detached from active lineage."""
        metadata = metadata or {}
        binding = self._active_model_binding(expected)

        for key, label in (
            ("project_id", "project"),
            ("dataset_id", "dataset"),
            ("dataset_version_id", "dataset version"),
            ("target", "target"),
        ):
            requested = _lineage_value((expected or {}).get(key))
            if requested and requested != _lineage_value(binding.get(key)):
                return f"The requested final-model {label} does not match the exact active workspace."

        active_requirements = [
            ("project_id", "project"),
            ("dataset_id", "dataset"),
            ("dataset_version_id", "dataset version"),
            ("target", "target"),
            ("feature_manifest_version", "feature manifest"),
            ("split_id", "governed split"),
        ]
        for key, label in active_requirements:
            if not str(binding.get(key) or "").strip():
                return (
                    f"The active workspace has no current {label} binding. "
                    "Reconfirm preparation, recreate the governed split, and retrain before using a final model."
                )

        artifact_requirements = [
            ("project_id", "project"),
            ("dataset_id", "dataset"),
            ("dataset_version_id", "dataset version"),
            ("target", "target"),
            ("problem_type", "problem type"),
            ("feature_manifest_version", "feature manifest"),
            ("split_id", "governed split"),
        ]
        for key, label in artifact_requirements:
            actual = str(metadata.get(key) or "").strip()
            current = str(binding.get(key) or "").strip()
            if not actual:
                return (
                    f"The final model is missing its {label} binding. "
                    "Retrain and save a new final model before scoring or export."
                )
            if current and actual != current:
                return (
                    f"The final model is stale because its {label} does not match the active workspace. "
                    "Retrain and save a new final model."
                )

        training_job_id = str(
            metadata.get("training_job_id")
            or metadata.get("training_run_id")
            or ""
        ).strip()
        if not training_job_id:
            return (
                "The final model is missing its training job binding. "
                "Retrain and save a new final model before scoring or export."
            )

        for key, label in (
            ("validation_design_id", "validation design"),
            ("validation_design_version", "validation design version"),
        ):
            current = str(binding.get(key) or "").strip()
            actual = str(metadata.get(key) or "").strip()
            if current and not actual:
                return (
                    f"The final model is missing its {label} binding. "
                    "Retrain under the approved validation design."
                )
            if current and actual != current:
                return (
                    f"The final model is stale because its {label} does not match the active workspace. "
                    "Retrain under the current validation design."
                )
        return ""

    def _promotion_context_mismatch(
        self,
        model_name: str,
        expected: Dict[str, Any] | None = None,
    ) -> str:
        """Validate one opaque candidate contract before final-model handoff."""
        _, error = self._resolve_candidate_lineage(model_name, expected)
        return error

    def _final_binding_metadata(
        self,
        model_name: str,
        context: Dict[str, Any] | None = None,
        evaluation_package_id: str = "",
    ) -> Dict[str, Any]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            raise ValueError(error)
        lineage = resolved["lineage"]
        completed_package, package_error = self._completed_evaluation_package(
            lineage,
            evaluation_package_id,
            candidate_contract=resolved["candidate_contract"],
        )
        if package_error:
            raise ValueError(package_error)
        return {
            **lineage,
            "dataset_version": lineage["dataset_version_id"],
            "evaluation_package_id": completed_package["evaluation_package_id"],
        }

    def _artifact_context_mismatch(self, model_name: str, expected: Dict[str, Any] | None = None) -> str:
        _, error = self._resolve_candidate_lineage(model_name, expected)
        return error

    def _artifact_debug(self, model_name: str, expected: Dict[str, Any] | None = None) -> Dict[str, Any]:
        expected = expected or {}
        summary = RESULTS.get_last_summary() or {}
        ranked_matches = [
            row for row in (summary.get("ranked") or [])
            if isinstance(row, dict)
            and _lineage_value(row.get("candidate_id")) == _lineage_value(model_name)
        ]
        algorithm_id = (
            _lineage_value((ranked_matches[0].get("candidate_contract") or {}).get("algorithm_id"))
            if len(ranked_matches) == 1 and isinstance(ranked_matches[0].get("candidate_contract"), dict)
            else ""
        )
        metadata = RESULTS.get_model_artifact_metadata(algorithm_id) if algorithm_id else {}
        result = ((summary.get("raw") or {}).get(algorithm_id) or {}) if algorithm_id else {}
        return {
            "selected_candidate_id": model_name,
            "resolved_algorithm_id": algorithm_id,
            "requested_project_id": expected.get("project_id") or "",
            "requested_dataset_id": expected.get("dataset_id") or "",
            "requested_dataset_version_id": expected.get("dataset_version_id") or "",
            "requested_training_job_id": expected.get("training_job_id") or "",
            "requested_feature_manifest_version": expected.get("feature_manifest_version") or "",
            "requested_validation_design_id": expected.get("validation_design_id") or "",
            "requested_validation_design_version": expected.get("validation_design_version") or "",
            "requested_split_id": expected.get("split_id") or "",
            "requested_target": expected.get("target") or "",
            "requested_problem_type": expected.get("problem_type") or "",
            "returned_candidate_id": metadata.get("candidate_id") or "",
            "returned_model_key": metadata.get("model_key") or "",
            "returned_project_id": metadata.get("project_id") or "",
            "returned_dataset_id": metadata.get("dataset_id") or "",
            "returned_dataset_version_id": metadata.get("dataset_version_id") or "",
            "returned_target": metadata.get("target") or "",
            "returned_problem_type": metadata.get("problem_type") or result.get("task") or "",
            "training_run_id": metadata.get("training_job_id") or metadata.get("training_run_id") or "",
            "artifact_has_metadata": bool(metadata),
            "summary_training_job_id": summary.get("training_job_id") or "",
        }

    def _model_result(
        self,
        model_name: str,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any] | None:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        return None if error else resolved["raw_result"]

    def get_curves(
        self,
        model_name: str,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return self._lineage_error(error, model_name)
        result = resolved["raw_result"]

        metrics = result.get("metrics") or {}
        task = result.get("task") or resolved["lineage"]["problem_type"]
        y_true = np.asarray(result.get("y_true") or [], dtype=float)
        y_score = np.asarray(result.get("y_score") or [], dtype=float)

        if task == "regression":
            response: Dict[str, Any] = {
                "ok": True,
                "task": "regression",
                "metrics": {
                    "mae": metrics.get("mae"),
                    "mse": metrics.get("mse"),
                    "rmse": metrics.get("rmse"),
                    "r2": metrics.get("r2"),
                    "adjusted_r2": metrics.get("adjusted_r2"),
                },
            }
            if len(y_true) and len(y_score):
                residuals = y_true - y_score
                abs_residuals = np.abs(residuals)
                response["residuals"] = {
                    "points": [
                        {
                            "actual": float(actual),
                            "predicted": float(predicted),
                            "residual": float(residual),
                        }
                        for actual, predicted, residual in zip(y_true[:1200], y_score[:1200], residuals[:1200])
                    ],
                    "summary": {
                        "mean_residual": float(np.mean(residuals)),
                        "median_residual": float(np.median(residuals)),
                        "std_residual": float(np.std(residuals)),
                        "mean_abs_residual": float(np.mean(abs_residuals)),
                        "p95_abs_residual": float(np.percentile(abs_residuals, 95)),
                    },
                }
                bins = np.histogram(residuals, bins=min(24, max(8, int(np.sqrt(len(residuals))))))
                response["residual_histogram"] = {
                    "counts": bins[0].astype(int).tolist(),
                    "edges": bins[1].astype(float).tolist(),
                }
            return response

        response: Dict[str, Any] = {
            "ok": True,
            "task": "classification",
            "metrics": {
                "precision": metrics.get("precision"),
                "recall": metrics.get("recall"),
                "f1": metrics.get("f1"),
                "auc": metrics.get("auc"),
                "pr_auc": metrics.get("pr_auc"),
            },
            "confusion": metrics.get("confusion_matrix"),
        }

        if len(y_true) and len(y_score) and roc_curve is not None:
            fpr, tpr, _ = roc_curve(y_true, y_score)
            response["roc"] = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}

        if len(y_true) and len(y_score) and precision_recall_curve is not None:
            precision, recall, _ = precision_recall_curve(y_true, y_score)
            response["pr"] = {
                "precision": precision.tolist(),
                "recall": recall.tolist(),
            }

        return response

    def get_deciles(
        self,
        model_name: str,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return {**self._lineage_error(error, model_name), "deciles": []}
        result = resolved["raw_result"]

        y_true = np.asarray(result.get("y_true") or [], dtype=float)
        y_score = np.asarray(result.get("y_score") or [], dtype=float)
        if not len(y_true) or not len(y_score):
            return {"ok": True, "deciles": []}

        order = np.argsort(-y_score)
        y_sorted = y_true[order]
        base_rate = float(np.mean(y_sorted)) if len(y_sorted) else 0.0

        rows: List[Dict[str, Any]] = []
        for idx, bucket in enumerate(np.array_split(y_sorted, 10), start=1):
            if not len(bucket):
                continue
            event_rate = float(np.mean(bucket))
            rows.append(
                {
                    "decile": idx,
                    "n": int(len(bucket)),
                    "positives": int(np.sum(bucket)),
                    "event_rate": event_rate,
                    "lift": float(event_rate / base_rate) if base_rate > 0 else 0.0,
                }
            )

        return {"ok": True, "deciles": rows}

    def get_evaluation_command_center(
        self,
        model_name: str,
        threshold: float | None = None,
        review_capacity: float = 0.1,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Build reporting-only diagnostics from the fitted final holdout.

        Threshold recommendations never use final-holdout labels or scores.
        The supplied threshold is an already governed/user-selected deployment
        threshold used only to report the final-holdout operating result.
        """
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return self._lineage_error(error, model_name)
        result = resolved["raw_result"]
        y_true = np.asarray(result.get("y_true") or [], dtype=float)
        y_score = np.asarray(result.get("y_score") or [], dtype=float)
        if not len(y_true) or not len(y_score) or len(y_true) != len(y_score):
            return {"ok": False, "error": "Persisted holdout labels and scores are unavailable for this model."}

        task = _lineage_value(result.get("task") or resolved["lineage"]["problem_type"]).casefold()
        selection_metric = copy.deepcopy(
            resolved["candidate_contract"].get("selection_metric") or {}
        )
        holdout_prediction_digest = _lineage_value(
            (resolved.get("holdout_exposure") or {}).get(
                "holdout_prediction_digest"
            )
        )
        if not holdout_prediction_digest:
            return {
                "ok": False,
                "error": "The final-holdout exposure has no immutable prediction digest.",
            }
        if task == "regression":
            feature_count = len(resolved["artifact_metadata"].get("trained_feature_names") or [])
            metrics = self._regression_metrics(
                pd.Series(y_true),
                y_score,
                n_features=feature_count,
            )
            residuals = y_true - y_score
            return {
                "ok": True,
                "model": model_name,
                "problem_type": "regression",
                "evaluation_role": "TEST",
                "final_holdout_role": "reporting_only",
                "test_status": "Available - final holdout (reporting only)",
                "oot_status": "Not loaded",
                "observation_count": int(len(y_true)),
                "evaluation_configuration": {
                    "problem_type": "regression",
                    "final_holdout_role": "reporting_only",
                },
                "holdout_prediction_digest": holdout_prediction_digest,
                "residual_diagnostics": {
                    "mean": float(np.mean(residuals)),
                    "standard_deviation": float(np.std(residuals)),
                    "minimum": float(np.min(residuals)),
                    "p05": float(np.quantile(residuals, 0.05)),
                    "median": float(np.median(residuals)),
                    "p95": float(np.quantile(residuals, 0.95)),
                    "maximum": float(np.max(residuals)),
                },
                "prediction_range": {
                    "actual_minimum": float(np.min(y_true)),
                    "actual_maximum": float(np.max(y_true)),
                    "predicted_minimum": float(np.min(y_score)),
                    "predicted_maximum": float(np.max(y_score)),
                },
                "stability": {
                    "internal_validation_status": "Available - verified training-only selection",
                    "internal_validation_score": selection_metric.get("value", selection_metric.get("mean")),
                    "selection_metric": selection_metric,
                    "test_metrics": metrics,
                    "oot_metrics": None,
                },
            }
        if task != "classification":
            return {"ok": False, "error": "The selected candidate has an unsupported supervised task."}

        y_true = (y_true > 0.5).astype(int)
        y_score = np.clip(y_score.astype(float), 0.0, 1.0)
        governed_threshold, governed_threshold_source = (
            _frozen_candidate_threshold_policy(resolved["candidate_contract"])
        )
        active_threshold = (
            governed_threshold
            if threshold is None
            else float(np.clip(threshold, 0.0, 1.0))
        )
        active_threshold_source = (
            governed_threshold_source
            if threshold is None
            else "user_supplied_reporting_value"
        )
        capacity = float(np.clip(review_capacity, 0.001, 1.0))

        def threshold_row(value: float) -> Dict[str, Any]:
            predicted = (y_score >= value).astype(int)
            tn = int(np.sum((y_true == 0) & (predicted == 0)))
            fp = int(np.sum((y_true == 0) & (predicted == 1)))
            fn = int(np.sum((y_true == 1) & (predicted == 0)))
            tp = int(np.sum((y_true == 1) & (predicted == 1)))
            predicted_positives = tp + fp
            positives = tp + fn
            precision = float(tp / predicted_positives) if predicted_positives else 0.0
            recall = float(tp / positives) if positives else 0.0
            fpr = float(fp / (fp + tn)) if fp + tn else 0.0
            f1 = float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0
            alert_rate = float(predicted_positives / len(y_true)) if len(y_true) else 0.0
            return {
                "threshold": float(value),
                "predicted_positives": predicted_positives,
                "review_volume": predicted_positives,
                "precision": precision,
                "recall": recall,
                "false_positives": fp,
                "false_negatives": fn,
                "true_positives": tp,
                "true_negatives": tn,
                "fraud_capture": recall,
                "false_positive_rate": fpr,
                "f1": f1,
                "expected_alert_rate": alert_rate,
                "confusion": [[tn, fp], [fn, tp]],
            }

        order = np.argsort(-y_score)
        sorted_true = y_true[order]
        sorted_score = y_score[order]
        positives = int(np.sum(sorted_true))
        base_rate = float(np.mean(sorted_true)) if len(sorted_true) else 0.0
        deciles: List[Dict[str, Any]] = []
        cumulative_positives = 0
        for index, positions in enumerate(np.array_split(np.arange(len(sorted_true)), 10), start=1):
            if not len(positions):
                continue
            bucket = sorted_true[positions]
            bucket_scores = sorted_score[positions]
            bucket_positives = int(np.sum(bucket))
            cumulative_positives += bucket_positives
            event_rate = float(np.mean(bucket))
            deciles.append({
                "decile": index,
                "n": int(len(bucket)),
                "positives": bucket_positives,
                "event_rate": event_rate,
                "lift": float(event_rate / base_rate) if base_rate else 0.0,
                "cumulative_positives": cumulative_positives,
                "capture_rate": float(cumulative_positives / positives) if positives else 0.0,
                "population_rate": float(np.max(positions) + 1) / len(sorted_true),
                "min_score": float(np.min(bucket_scores)),
                "max_score": float(np.max(bucket_scores)),
                "mean_score": float(np.mean(bucket_scores)),
            })

        top_capture: Dict[str, Dict[str, Any]] = {}
        for pct in (0.01, 0.03, 0.05, 0.10):
            count = max(1, int(np.ceil(len(sorted_true) * pct)))
            top_events = int(np.sum(sorted_true[:count]))
            top_rate = float(np.mean(sorted_true[:count])) if count else 0.0
            top_capture[f"{int(pct * 100)}%"] = {
                "rows": count,
                "events": top_events,
                "capture_rate": float(top_events / positives) if positives else 0.0,
                "lift": float(top_rate / base_rate) if base_rate else 0.0,
            }

        calibration_rows: List[Dict[str, Any]] = []
        for bucket in np.array_split(np.argsort(y_score), 10):
            if not len(bucket):
                continue
            calibration_rows.append({
                "predicted": float(np.mean(y_score[bucket])),
                "observed": float(np.mean(y_true[bucket])),
                "n": int(len(bucket)),
            })
        if len(calibration_rows) >= 2:
            predicted_means = np.asarray([row["predicted"] for row in calibration_rows], dtype=float)
            observed_means = np.asarray([row["observed"] for row in calibration_rows], dtype=float)
            slope, intercept = np.polyfit(predicted_means, observed_means, 1)
            calibration_slope = float(slope)
            calibration_intercept = float(intercept)
        else:
            calibration_slope = None
            calibration_intercept = None

        metrics = result.get("metrics") or {}
        ranked_row = resolved["candidate"]
        return {
            "ok": True,
            "model": model_name,
            "problem_type": "classification",
            "evaluation_role": "TEST",
            "final_holdout_role": "reporting_only",
            "test_status": "Available - final holdout (reporting only)",
            "oot_status": "Not loaded",
            "observation_count": int(len(y_true)),
            "event_count": positives,
            "event_rate": base_rate,
            "evaluation_configuration": {
                "problem_type": "classification",
                "threshold": active_threshold,
                "review_capacity": capacity,
                "threshold_source": active_threshold_source,
                "final_holdout_role": "reporting_only",
            },
            "holdout_prediction_digest": holdout_prediction_digest,
            "threshold": threshold_row(active_threshold),
            "presets": {
                "current_governed": governed_threshold,
            },
            "threshold_policy": {
                "active_threshold": active_threshold,
                "active_source": active_threshold_source,
                "governed_threshold": governed_threshold,
                "governed_source": governed_threshold_source,
                "final_holdout_role": "reporting_only",
                "recommendations_derived_from_final_holdout": False,
            },
            "lift": {
                "base_rate": base_rate,
                "deciles": deciles,
                "top_capture": top_capture,
            },
            "calibration": {
                "rows": calibration_rows,
                "brier_score": float(np.mean((y_score - y_true) ** 2)),
                "slope": calibration_slope,
                "intercept": calibration_intercept,
                "method": ranked_row.get("calibration_method") or ("Applied" if ranked_row.get("calibration_applied") else "Not applied"),
                "prevalence_correction": "Not applied during Evaluation",
            },
            "stability": {
                "internal_validation_status": "Available - verified training-only selection",
                "internal_validation_score": selection_metric.get("value", selection_metric.get("mean")),
                "selection_metric": selection_metric,
                "test_metrics": {
                    "roc_auc": metrics.get("auc"),
                    "pr_auc": metrics.get("pr_auc"),
                    "precision": metrics.get("precision"),
                    "recall": metrics.get("recall"),
                    "f1": metrics.get("f1"),
                },
                "oot_metrics": None,
            },
        }

    def _artifact(self, model_name: str, expected: Dict[str, Any] | None = None):
        # Scoring/export still pass their already-governed internal algorithm
        # key. Evaluation and Interpretation always provide exact context and
        # resolve the opaque candidate_id before accessing that key.
        if expected is None:
            return RESULTS.get_model_artifact(model_name)
        resolved, error = self._resolve_candidate_lineage(model_name, expected)
        if error:
            return None
        return resolved["artifact"]

    def _test_data(self):
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_test is None or y_test is None:
            raise ValueError("No evaluation split is available. Train models first.")
        return X_train, X_test, y_train, y_test

    def _prepare_final_feature_frame(self, model: Dict[str, Any], X: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], List[str]]:
        features = [str(feature) for feature in model["features"]]
        if model.get("dummy_columns"):
            encoded = pd.get_dummies(X.copy(), dummy_na=True)
            dummy_columns = [str(feature) for feature in model.get("dummy_columns", [])]
            prepared = encoded.reindex(columns=dummy_columns, fill_value=0)
            matched = [feature for feature in features if feature in prepared.columns]
            missing = [feature for feature in features if feature not in encoded.columns and "__" not in feature]
            for feature in features:
                if feature not in prepared.columns:
                    prepared[feature] = np.nan
            prepared = prepared[features].apply(pd.to_numeric, errors="coerce")
            prepared = prepared.fillna(model["medians"])
            prepared = (prepared - model["means"]) / model["stds"]
            return prepared[features], matched, missing
        normalized_columns = {str(col).strip().lower(): col for col in X.columns}
        prepared = pd.DataFrame(index=X.index)
        matched: List[str] = []
        missing: List[str] = []
        for feature in features:
            source_col = feature if feature in X.columns else normalized_columns.get(feature.strip().lower())
            if source_col is None:
                prepared[feature] = np.nan
                missing.append(feature)
            else:
                prepared[feature] = X[source_col]
                matched.append(feature)
            prepared[feature] = pd.to_numeric(prepared[feature], errors="coerce")
        prepared = prepared.fillna(model["medians"])
        prepared = (prepared - model["means"]) / model["stds"]
        return prepared[features], matched, missing

    def _predict_score(self, model: Any, X: pd.DataFrame) -> np.ndarray:
        if isinstance(model, dict) and model.get("kind") in {"rfe_logistic", "rfe_classifier"}:
            prepared, _, _ = self._prepare_final_feature_frame(model, X)
            return np.asarray(model["model"].predict_proba(prepared)[:, 1], dtype=float)
        if isinstance(model, dict) and model.get("kind") in {"rfe_regression", "rfe_regressor"}:
            prepared, _, _ = self._prepare_final_feature_frame(model, X)
            return np.asarray(model["model"].predict(prepared), dtype=float)
        if hasattr(model, "predict_proba"):
            return np.asarray(model.predict_proba(X)[:, 1], dtype=float)
        if hasattr(model, "decision_function"):
            raw = np.asarray(model.decision_function(X), dtype=float)
            return (raw - np.min(raw)) / (np.max(raw) - np.min(raw) + 1e-9)
        return np.asarray(model.predict(X), dtype=float)

    def _predict_label(self, model: Any, X: pd.DataFrame) -> np.ndarray:
        scores = self._predict_score(model, X)
        return (scores >= 0.5).astype(int)

    def feature_importance(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, y_test = self._test_data()
        if X_test is None or X_test.empty:
            return {"ok": False, "error": "No governed holdout data is available for feature importance."}

        sample = X_test.sample(n=5_000, random_state=42) if len(X_test) > 5_000 else X_test
        y_series = pd.Series(np.asarray(y_test), index=X_test.index)
        y_sample = y_series.loc[sample.index]
        estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
        preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
        transformed_names = (
            list(preprocess.get_feature_names_out())
            if preprocess is not None and hasattr(preprocess, "get_feature_names_out")
            else list(X_test.columns)
        )
        raw_columns = [str(column) for column in X_test.columns]

        def original_feature(name: Any) -> str:
            cleaned = str(name).replace("num__", "").replace("cat__", "")
            if cleaned in raw_columns:
                return cleaned
            matches = [column for column in raw_columns if cleaned.startswith(f"{column}_")]
            return max(matches, key=len) if matches else cleaned

        def aggregate(values: Any, source: str) -> List[Dict[str, Any]]:
            grouped: Dict[str, Dict[str, Any]] = {}
            for name, value in zip(transformed_names, np.asarray(values).ravel()):
                feature = original_feature(name)
                row = grouped.setdefault(feature, {"feature": feature, "importance": 0.0, "direction": 0.0, "source": source})
                row["importance"] += abs(float(value))
                row["direction"] += float(value)
            return list(grouped.values())

        rows: List[Dict[str, Any]] = []
        method = "unavailable"
        coefficients = getattr(estimator, "coef_", None)
        native = getattr(estimator, "feature_importances_", None)
        if coefficients is not None:
            coef = np.asarray(coefficients, dtype=float)
            if coef.ndim > 1:
                coef = np.mean(coef, axis=0)
            rows = aggregate(coef, "coefficient magnitude")
            method = "coefficient magnitude"
        elif native is not None:
            rows = aggregate(native, "native feature importance")
            method = "native feature importance"
        elif permutation_importance is not None:
            scoring = "neg_root_mean_squared_error" if self._is_regression_problem() else "roc_auc"
            result = permutation_importance(
                model,
                sample,
                y_sample,
                n_repeats=3,
                random_state=42,
                n_jobs=1,
                scoring=scoring,
            )
            rows = [
                {
                    "feature": str(feature),
                    "importance": abs(float(value)),
                    "direction": float(value),
                    "source": "holdout permutation importance",
                }
                for feature, value in zip(sample.columns, result.importances_mean)
            ]
            method = "holdout permutation importance"

        rows = _filter_target_derived_rows(rows)
        rows.sort(key=lambda row: row["importance"], reverse=True)
        return {"ok": True, "rows": rows[:30], "method": method, "sample_count": int(len(sample))}

    def hyperparameters(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return {"ok": False, "error": error, "lineage_error": True, "debug": self._artifact_debug(model_name, context)}
        result = resolved["raw_result"]
        row = resolved["candidate"]
        params = result.get("best_params") or row.get("best_params") or {}
        score = result.get("best_score") or row.get("best_score")
        if not params:
            model = resolved["artifact"]
            estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
            if estimator is not None and hasattr(estimator, "get_params"):
                raw_params = estimator.get_params(deep=False)
                params = {
                    key: value
                    for key, value in raw_params.items()
                    if isinstance(value, (str, int, float, bool, type(None), tuple))
                }
        rows = [{"parameter": str(key), "value": str(value)} for key, value in sorted(params.items())]
        return {"ok": True, "best_score": score, "rows": rows}

    def model_details(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
        preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
        names = (
            preprocess.get_feature_names_out()
            if preprocess is not None and hasattr(preprocess, "get_feature_names_out")
            else []
        )

        if hasattr(estimator, "coef_"):
            coef = np.asarray(estimator.coef_).ravel()
            intercept = float(np.asarray(getattr(estimator, "intercept_", [0])).ravel()[0])
            is_classifier = hasattr(estimator, "classes_")
            inference = None if is_classifier else self._linear_regression_inference(model, estimator, names)
            inference_by_feature = {
                str(row.get("feature")): row
                for row in (inference or {}).get("coefficient_rows", [])
            }
            rows = [
                {
                    "feature": str(name).replace("num__", "").replace("cat__", ""),
                    "coefficient": float(value),
                    "standardized_coefficient": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("standardized_coefficient"),
                    "standardized_weight": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("standardized_weight"),
                    "standard_error": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("standard_error"),
                    "t_statistic": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("t_statistic"),
                    "p_value": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("p_value"),
                    "ci_lower": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("ci_lower"),
                    "ci_upper": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("ci_upper"),
                    "confidence_interval_lower": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("confidence_interval_lower"),
                    "confidence_interval_upper": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("confidence_interval_upper"),
                    "odds_ratio": float(np.exp(value)) if is_classifier else None,
                }
                for name, value in zip(names, coef)
            ]
            rows = _filter_target_derived_rows(rows)
            rows.sort(key=lambda row: abs(row["coefficient"]), reverse=True)
            for rank, row in enumerate(rows, start=1):
                row["absolute_rank"] = rank
            return {
                "ok": True,
                "kind": "equation",
                "model_type": "classification" if is_classifier else "regression",
                "debug": self._artifact_debug(model_name, context),
                "intercept": intercept,
                "coefficients": rows[:40],
                "inference_available": bool((inference or {}).get("ok")),
                "inference_message": (inference or {}).get("message"),
                "model_fit": (inference or {}).get("model_fit"),
            }

        if estimator.__class__.__name__.lower().startswith("decisiontree"):
            try:
                from sklearn.tree import export_text

                tree_text = export_text(estimator, feature_names=[str(n) for n in names], max_depth=4)
            except Exception as exc:
                tree_text = f"Unable to export tree text: {exc}"
            return {"ok": True, "kind": "tree", "tree_text": tree_text}

        return {"ok": True, "kind": "generic", "message": f"{estimator.__class__.__name__} uses model-agnostic interpretation panels below."}

    def _linear_regression_inference(self, model: Any, estimator: Any, names: Any) -> Dict[str, Any]:
        try:
            X_train, _, y_train, _ = self._test_data()
            if X_train is None or y_train is None:
                return {"ok": False, "message": "Statistical inference unavailable because training data is unavailable."}
            preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
            if preprocess is None or not hasattr(preprocess, "transform"):
                return {"ok": False, "message": "Statistical inference unavailable because the fitted preprocessing design matrix is unavailable."}
            matrix = preprocess.transform(X_train)
            if hasattr(matrix, "toarray"):
                matrix = matrix.toarray()
            X = np.asarray(matrix, dtype=float)
            y = np.asarray(y_train, dtype=float).ravel()
            if X.ndim != 2 or len(y) != X.shape[0]:
                return {"ok": False, "message": "Statistical inference unavailable because the transformed design matrix does not align to the target vector."}
            n_obs, n_predictors = X.shape
            residual_df = int(n_obs - n_predictors - 1)
            if residual_df <= 0 or n_obs < 3:
                return {"ok": False, "message": "Statistical inference unavailable because residual degrees of freedom are invalid."}

            X_design = np.column_stack([np.ones(n_obs), X])
            rank = int(np.linalg.matrix_rank(X_design))
            if rank < X_design.shape[1]:
                return {"ok": False, "message": "Statistical inference unavailable because the transformed design matrix is singular."}

            coef = np.asarray(estimator.coef_, dtype=float).ravel()
            intercept = float(np.asarray(getattr(estimator, "intercept_", [0])).ravel()[0])
            params = np.concatenate([[intercept], coef])
            y_hat = X_design @ params
            residuals = y - y_hat
            rss = float(np.sum(residuals ** 2))
            mse = rss / residual_df
            xtx_inv = np.linalg.inv(X_design.T @ X_design)
            covariance = mse * xtx_inv
            std_errors = np.sqrt(np.maximum(np.diag(covariance), 0))
            t_stats = np.divide(params, std_errors, out=np.full_like(params, np.nan, dtype=float), where=std_errors > 0)

            if scipy_stats is None:
                p_values = np.full_like(t_stats, np.nan, dtype=float)
                critical = np.nan
                message = "Statistical inference unavailable because SciPy is unavailable."
            else:
                p_values = 2 * scipy_stats.t.sf(np.abs(t_stats), residual_df)
                critical = float(scipy_stats.t.ppf(0.975, residual_df))
                message = "OLS inference computed from the transformed design matrix used by the fitted pipeline."

            y_std = float(np.std(y, ddof=1)) or 1.0
            x_stds = np.std(X, axis=0, ddof=1)
            feature_names = [str(name).replace("num__", "").replace("cat__", "") for name in names]
            coefficient_rows = []
            for idx, (feature, coefficient) in enumerate(zip(feature_names, coef), start=1):
                se = float(std_errors[idx])
                ci_delta = float(critical * se) if np.isfinite(critical) else np.nan
                coefficient_rows.append(
                    {
                        "feature": feature,
                        "variable": feature,
                        "coefficient": float(coefficient),
                        "standardized_coefficient": float(coefficient * (x_stds[idx - 1] / y_std)) if np.isfinite(x_stds[idx - 1]) else None,
                        "standardized_weight": float(coefficient * (x_stds[idx - 1] / y_std)) if np.isfinite(x_stds[idx - 1]) else None,
                        "standard_error": se if np.isfinite(se) else None,
                        "t_statistic": float(t_stats[idx]) if np.isfinite(t_stats[idx]) else None,
                        "p_value": float(p_values[idx]) if np.isfinite(p_values[idx]) else None,
                        "ci_lower": float(coefficient - ci_delta) if np.isfinite(ci_delta) else None,
                        "ci_upper": float(coefficient + ci_delta) if np.isfinite(ci_delta) else None,
                        "confidence_interval_lower": float(coefficient - ci_delta) if np.isfinite(ci_delta) else None,
                        "confidence_interval_upper": float(coefficient + ci_delta) if np.isfinite(ci_delta) else None,
                    }
                )

            y_mean = float(np.mean(y))
            tss = float(np.sum((y - y_mean) ** 2))
            r2 = float(1 - rss / tss) if tss > 0 else 0.0
            adjusted_r2 = float(1 - (1 - r2) * ((n_obs - 1) / residual_df)) if residual_df > 0 else 0.0
            ess = max(tss - rss, 0.0)
            f_statistic = None
            prob_f_statistic = None
            if n_predictors > 0 and residual_df > 0 and rss > 0:
                f_statistic = float((ess / n_predictors) / (rss / residual_df))
                if scipy_stats is not None and np.isfinite(f_statistic):
                    prob_f_statistic = float(scipy_stats.f.sf(f_statistic, n_predictors, residual_df))
            sigma2_mle = max(rss / n_obs, np.finfo(float).eps)
            log_likelihood = float(-0.5 * n_obs * (np.log(2 * np.pi * sigma2_mle) + 1))
            parameter_count = int(n_predictors + 1)
            aic = float(2 * parameter_count - 2 * log_likelihood)
            bic = float(np.log(n_obs) * parameter_count - 2 * log_likelihood)
            try:
                condition_number = float(np.linalg.cond(X_design))
            except Exception:
                condition_number = None
            return {
                "ok": scipy_stats is not None,
                "message": message,
                "coefficient_rows": coefficient_rows,
                "model_fit": {
                    "dependent_variable": str(getattr(y_train, "name", "Target") or "Target"),
                    "model_type": "Linear Regression",
                    "r2": r2,
                    "adjusted_r2": adjusted_r2,
                    "rmse": float(np.sqrt(np.mean(residuals ** 2))),
                    "mae": float(np.mean(np.abs(residuals))),
                    "mse": float(np.mean(residuals ** 2)),
                    "n_observations": int(n_obs),
                    "n_predictors": int(n_predictors),
                    "residual_df": residual_df,
                    "residual_standard_error": float(np.sqrt(mse)),
                    "f_statistic": f_statistic,
                    "prob_f_statistic": prob_f_statistic,
                    "aic": aic,
                    "bic": bic,
                    "log_likelihood": log_likelihood,
                    "condition_number": condition_number,
                },
            }
        except Exception:
            return {"ok": False, "message": "Statistical inference unavailable because the fitted pipeline could not be evaluated for OLS inference."}

    def decision_tree(self, model_name: str, max_depth: int = 4, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
        preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
        names = (
            preprocess.get_feature_names_out()
            if preprocess is not None and hasattr(preprocess, "get_feature_names_out")
            else []
        )
        if not estimator.__class__.__name__.lower().startswith("decisiontree"):
            return {"ok": False, "error": "The selected model is not a decision tree."}
        tree = getattr(estimator, "tree_", None)
        if tree is None:
            return {"ok": False, "error": "Decision tree structure is unavailable."}

        feature_names = [str(name).replace("num__", "").replace("cat__", "") for name in names]
        classes = [str(item) for item in getattr(estimator, "classes_", [])]
        is_classifier = bool(classes)
        max_depth = max(1, min(int(max_depth or 4), 5))
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        def walk(node_id: int, depth: int, x_min: float, x_max: float) -> None:
            left = int(tree.children_left[node_id])
            right = int(tree.children_right[node_id])
            samples = int(tree.n_node_samples[node_id])
            values = np.asarray(tree.value[node_id]).ravel()
            total = float(values.sum()) or 1.0
            positive_rate = float(values[-1] / total) if is_classifier and len(values) else 0.0
            prediction_value = float(values[0]) if len(values) else 0.0
            predicted_index = int(np.argmax(values)) if is_classifier and len(values) else 0
            feature_index = int(tree.feature[node_id])
            feature = feature_names[feature_index] if 0 <= feature_index < len(feature_names) else ""
            threshold = float(tree.threshold[node_id]) if feature else None
            is_leaf = left == -1 or right == -1 or depth >= max_depth
            x = (x_min + x_max) / 2
            nodes.append(
                {
                    "id": int(node_id),
                    "depth": int(depth),
                    "x": float(x),
                    "leaf": bool(is_leaf),
                    "feature": feature,
                    "threshold": threshold,
                    "samples": samples,
                    "positive_rate": positive_rate,
                    "prediction": classes[predicted_index] if is_classifier and predicted_index < len(classes) else f"{prediction_value:.4f}",
                    "prediction_value": prediction_value,
                    "model_type": "classification" if is_classifier else "regression",
                }
            )
            if is_leaf:
                return
            mid = (x_min + x_max) / 2
            edges.extend(
                [
                    {"source": int(node_id), "target": left, "label": "Yes"},
                    {"source": int(node_id), "target": right, "label": "No"},
                ]
            )
            walk(left, depth + 1, x_min, mid)
            walk(right, depth + 1, mid, x_max)

        walk(0, 0, 0.0, 1.0)
        return {"ok": True, "nodes": nodes, "edges": edges, "max_depth": max_depth, "model_type": "classification" if is_classifier else "regression"}

    def knn_clusters(
        self,
        model_name: str,
        max_points: int = 900,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        resolved, lineage_error = self._resolve_candidate_lineage(model_name, context)
        if lineage_error:
            return self._lineage_error(lineage_error, model_name)
        try:
            model = resolved["artifact"]
            estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
            if "kneighbors" not in estimator.__class__.__name__.lower() and not hasattr(estimator, "kneighbors"):
                return {"ok": False, "error": "The selected model is not a KNN model."}
            _, X_test, _, y_test = self._test_data()
            if X_test is None or X_test.empty:
                return {"ok": False, "error": "No holdout data is available for KNN visualization."}
            if PCA is None or NearestNeighbors is None:
                return {"ok": False, "error": "PCA is unavailable for KNN visualization."}

            sample = X_test.copy()
            y_full = pd.Series(y_test, index=X_test.index)
            if len(sample) > max_points:
                sample = sample.sample(n=max_points, random_state=42)
            y_sample = y_full.loc[sample.index].reset_index(drop=True)
            sample = sample.reset_index(drop=True)

            preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
            if preprocess is not None and hasattr(preprocess, "transform"):
                matrix = preprocess.transform(sample)
                if hasattr(matrix, "toarray"):
                    matrix = matrix.toarray()
                matrix = np.asarray(matrix, dtype=float)
            else:
                numeric_cols = [col for col in sample.columns if pd.api.types.is_numeric_dtype(sample[col])]
                if len(numeric_cols) < 2:
                    return {"ok": False, "error": "KNN cluster view requires at least two numeric features."}
                numeric = sample[numeric_cols].apply(pd.to_numeric, errors="coerce")
                numeric = numeric.fillna(numeric.median(numeric_only=True))
                matrix = ((numeric - numeric.mean()) / numeric.std().replace(0, 1).fillna(1)).to_numpy()

            if matrix.shape[1] < 2:
                return {"ok": False, "error": "KNN cluster view requires at least two transformed features."}
            pca = PCA(n_components=2)
            coords = pca.fit_transform(matrix)
            model_neighbors = int(getattr(estimator, "n_neighbors", 5) or 5)
            display_neighbors = max(2, min(5, model_neighbors))
            nn = NearestNeighbors(n_neighbors=min(display_neighbors + 1, len(matrix)))
            nn.fit(matrix)
            distances, neighbor_indices = nn.kneighbors(matrix)
            scores = self._predict_score(model, sample)
            predictions = (scores >= 0.5).astype(int)
            try:
                _, y_arr = self._encode_binary_target(y_sample, y_sample)
            except Exception:
                y_arr = np.zeros(len(sample), dtype=int)

            x_vals = coords[:, 0]
            y_vals = coords[:, 1]
            x_min, x_max = float(np.quantile(x_vals, 0.01)), float(np.quantile(x_vals, 0.99))
            y_min, y_max = float(np.quantile(y_vals, 0.01)), float(np.quantile(y_vals, 0.99))
            if x_min == x_max:
                x_min -= 1
                x_max += 1
            if y_min == y_max:
                y_min -= 1
                y_max += 1
            x_pad = (x_max - x_min) * 0.08
            y_pad = (y_max - y_min) * 0.08
            x_min -= x_pad
            x_max += x_pad
            y_min -= y_pad
            y_max += y_pad

            grid_resolution = 82
            xs = np.linspace(x_min, x_max, grid_resolution)
            ys = np.linspace(y_min, y_max, grid_resolution)
            xx, yy = np.meshgrid(xs, ys)
            pca_grid = np.column_stack([xx.ravel(), yy.ravel()])
            feature_grid = pca.inverse_transform(pca_grid)
            if hasattr(estimator, "predict_proba"):
                grid_scores = np.asarray(estimator.predict_proba(feature_grid)[:, -1], dtype=float)
            elif hasattr(estimator, "decision_function"):
                raw = np.asarray(estimator.decision_function(feature_grid), dtype=float)
                grid_scores = (raw - np.min(raw)) / (np.max(raw) - np.min(raw) + 1e-9)
            else:
                grid_scores = np.asarray(estimator.predict(feature_grid), dtype=float)
            grid_predictions = (grid_scores >= 0.5).astype(int)
            region_labels = np.zeros(len(pca_grid), dtype=int)
            cluster_count = 1
            cluster_method = "nearest-neighbor"
            cluster_diagnostics: List[Dict[str, Any]] = []
            if KMeans is not None and silhouette_score is not None and len(coords) >= 30:
                best_score = -1.0
                best_model = None
                max_clusters = min(8, max(2, len(coords) // 25))
                try:
                    one_cluster = KMeans(n_clusters=1, n_init=10, random_state=42)
                    one_cluster.fit(coords)
                    cluster_diagnostics.append(
                        {"k": 1, "inertia": float(one_cluster.inertia_), "silhouette": None}
                    )
                except Exception:
                    pass
                for candidate_k in range(2, max_clusters + 1):
                    try:
                        candidate = KMeans(n_clusters=candidate_k, n_init=10, random_state=42)
                        labels = candidate.fit_predict(coords)
                        if len(set(labels)) < 2:
                            continue
                        score = float(silhouette_score(coords, labels))
                        cluster_diagnostics.append(
                            {"k": int(candidate_k), "inertia": float(candidate.inertia_), "silhouette": score}
                        )
                        if score > best_score:
                            best_score = score
                            best_model = candidate
                    except Exception:
                        continue
                if best_model is not None:
                    region_labels = best_model.predict(pca_grid)
                    cluster_count = int(best_model.n_clusters)
                    cluster_method = "silhouette-kmeans-on-pca"
            if cluster_count <= 1:
                nearest_grid = NearestNeighbors(n_neighbors=1)
                nearest_grid.fit(coords)
                nearest_indices = nearest_grid.kneighbors(pca_grid, return_distance=False).ravel()
                region_labels = np.asarray(nearest_indices % 8, dtype=int)
                cluster_count = int(min(8, len(coords)))
            grid_rows = [
                {
                    "x": float(pca_grid[index, 0]),
                    "y": float(pca_grid[index, 1]),
                    "score": float(grid_scores[index]),
                    "prediction": int(grid_predictions[index]),
                    "region": int(region_labels[index]),
                }
                for index in range(len(pca_grid))
            ]
            points = [
                {
                    "id": int(index),
                    "x": float(x),
                    "y": float(y),
                    "class": int(y_arr[index]) if index < len(y_arr) else 0,
                    "prediction": int(predictions[index]) if index < len(predictions) else 0,
                    "score": float(scores[index]) if index < len(scores) else 0.0,
                }
                for index, (x, y) in enumerate(coords)
            ]
            edges: List[Dict[str, Any]] = []
            seen_edges = set()
            max_edges = 1600
            for source, neighbors in enumerate(neighbor_indices):
                for neighbor in neighbors[1:]:
                    a, b = sorted((int(source), int(neighbor)))
                    if a == b or (a, b) in seen_edges:
                        continue
                    seen_edges.add((a, b))
                    edges.append(
                        {
                            "source": int(source),
                            "target": int(neighbor),
                            "same_prediction": bool(predictions[source] == predictions[neighbor]),
                            "same_class": bool(y_arr[source] == y_arr[neighbor]) if source < len(y_arr) and neighbor < len(y_arr) else False,
                            "distance": float(distances[source][list(neighbors).index(neighbor)]),
                        }
                    )
                    if len(edges) >= max_edges:
                        break
                if len(edges) >= max_edges:
                    break
            return {
                "ok": True,
                "points": points,
                "grid": grid_rows,
                "neighbor_edges": edges,
                "x_domain": [x_min, x_max],
                "y_domain": [y_min, y_max],
                "neighbor_count": model_neighbors,
                "display_neighbors": display_neighbors,
                "grid_resolution": grid_resolution,
                "cluster_count": cluster_count,
                "cluster_method": cluster_method,
                "cluster_diagnostics": cluster_diagnostics,
                "sample_size": int(len(points)),
            }
        except Exception as exc:
            return {"ok": False, "error": f"KNN cluster visualization failed: {exc}"}

    def pdp(self, model_name: str, feature: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if feature not in X_test.columns:
            return {"ok": False, "error": f"Feature '{feature}' was not found."}

        x = X_test.sample(n=2_500, random_state=42).copy() if len(X_test) > 2_500 else X_test.copy()
        s = x[feature]
        if pd.api.types.is_numeric_dtype(s):
            grid = np.quantile(pd.to_numeric(s, errors="coerce").dropna(), np.linspace(0.05, 0.95, 20))
        else:
            grid = s.astype(str).value_counts().head(12).index.to_numpy()

        rows = []
        for value in grid:
            x_mod = x.copy()
            x_mod[feature] = value
            rows.append(
                {
                    "value": float(value) if pd.api.types.is_numeric_dtype(s) else str(value),
                    "label": f"{float(value):,.4g}" if pd.api.types.is_numeric_dtype(s) else str(value),
                    "prediction": float(np.mean(self._predict_score(model, x_mod))),
                }
            )
        return {
            "ok": True,
            "feature": feature,
            "kind": "numeric" if pd.api.types.is_numeric_dtype(s) else "categorical",
            "sample_count": int(len(x)),
            "rows": rows,
        }

    def sensitivity(self, model_name: str, feature: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if feature not in X_test.columns:
            return {"ok": False, "error": f"Feature '{feature}' was not found."}
        sample = X_test.sample(n=2_500, random_state=42).copy() if len(X_test) > 2_500 else X_test.copy()
        baseline = float(np.mean(self._predict_score(model, sample)))
        rows = []
        if pd.api.types.is_numeric_dtype(sample[feature]):
            for pct in [-0.2, -0.1, 0.0, 0.1, 0.2]:
                x_mod = sample.copy()
                x_mod[feature] = pd.to_numeric(x_mod[feature], errors="coerce") * (1 + pct)
                pred = float(np.mean(self._predict_score(model, x_mod)))
                rows.append({"scenario": f"{pct:+.0%}", "prediction": pred, "delta": pred - baseline})
        else:
            for value in sample[feature].astype(str).value_counts().head(8).index:
                x_mod = sample.copy()
                x_mod[feature] = value
                pred = float(np.mean(self._predict_score(model, x_mod)))
                rows.append({"scenario": str(value), "prediction": pred, "delta": pred - baseline})
        return {"ok": True, "baseline": baseline, "sample_count": int(len(sample)), "rows": rows}

    def sensitivity_summary(
        self,
        model_name: str,
        top_n: int = 12,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        excluded_sensitivity_features = {"riskperformance", "bad_flag", "atlas_split"}
        resolved, lineage_error = self._resolve_candidate_lineage(model_name, context)
        if lineage_error:
            return self._lineage_error(lineage_error, model_name)
        model = resolved["artifact"]
        artifact_features = [
            str(feature)
            for feature in (resolved["artifact_metadata"].get("trained_feature_names") or [])
            if str(feature).lower() not in excluded_sensitivity_features
        ]
        _, X_test, _, _ = self._test_data()
        if X_test is None or X_test.empty:
            return {"ok": False, "error": "No holdout data is available."}

        baseline = float(np.mean(self._predict_score(model, X_test)))
        if artifact_features:
            ordered = [feature for feature in artifact_features if feature in X_test.columns]
        else:
            importance = self.feature_importance(model_name, context).get("rows", [])
            ordered = [str(row.get("feature", "")).replace("num__", "").replace("cat__", "") for row in importance]
            ordered += [str(col) for col in X_test.columns if str(col) not in ordered]

        rows: List[Dict[str, Any]] = []
        for feature in ordered:
            if feature not in X_test.columns:
                continue
            if str(feature).lower() in excluded_sensitivity_features:
                continue
            series = X_test[feature]
            scenarios: List[Dict[str, Any]] = []
            special_value_note = ""
            if pd.api.types.is_numeric_dtype(series):
                numeric = pd.to_numeric(series, errors="coerce")
                if numeric.dropna().empty:
                    continue
                special_mask = numeric.isin([-7, -8, -9])
                if bool(special_mask.any()):
                    special_value_note = (
                        "Sensitivity analysis excludes special bureau values from percentage perturbation. "
                        "Special values require separate bin-level or reason-code review."
                    )
                for pct in [-0.2, 0.2]:
                    x_mod = X_test.copy()
                    x_mod[feature] = numeric.where(special_mask, numeric * (1 + pct))
                    pred = float(np.mean(self._predict_score(model, x_mod)))
                    scenarios.append({"scenario": f"{pct:+.0%}", "prediction": pred, "delta": pred - baseline})
            else:
                for value in series.astype(str).value_counts().head(3).index:
                    x_mod = X_test.copy()
                    x_mod[feature] = value
                    pred = float(np.mean(self._predict_score(model, x_mod)))
                    scenarios.append({"scenario": str(value), "prediction": pred, "delta": pred - baseline})
            if not scenarios:
                continue
            max_row = max(scenarios, key=lambda row: abs(float(row["delta"])))
            negative_row = next((row for row in scenarios if row["scenario"] == "-20%"), None)
            positive_row = next((row for row in scenarios if row["scenario"] == "+20%"), None)
            positive_delta = float(positive_row["delta"]) if positive_row else float(max_row["delta"])
            if positive_delta > 0:
                direction = "increases_bad_risk"
                direction_explanation = "Increasing this feature increases predicted bad risk."
            elif positive_delta < 0:
                direction = "decreases_bad_risk"
                direction_explanation = "Increasing this feature decreases predicted bad risk."
            else:
                direction = "neutral"
                direction_explanation = "Increasing this feature has no material direction in the selected sensitivity scenarios."
            largest_direction = (
                "Largest impact occurs when this feature is decreased."
                if max_row["scenario"] == "-20%"
                else "Largest impact occurs when this feature is increased."
                if max_row["scenario"] == "+20%"
                else f"Largest impact occurs at scenario {max_row['scenario']}."
            )
            rows.append(
                {
                    "feature": feature,
                    "baseline": baseline,
                    "baseline_prediction": baseline,
                    "negative_scenario_prediction": negative_row["prediction"] if negative_row else None,
                    "positive_scenario_prediction": positive_row["prediction"] if positive_row else None,
                    "max_abs_delta": abs(float(max_row["delta"])),
                    "worst_scenario": max_row["scenario"],
                    "worst_prediction": max_row["prediction"],
                    "worst_delta": max_row["delta"],
                    "largest_scenario": max_row["scenario"],
                    "delta": max_row["delta"],
                    "direction": direction,
                    "direction_explanation": f"{direction_explanation} {largest_direction}",
                    "special_value_note": special_value_note,
                    "scenarios": scenarios,
                }
            )
            if len(rows) >= max(1, min(int(top_n or 12), 30)):
                break

        rows.sort(key=lambda row: row["max_abs_delta"], reverse=True)
        return {"ok": True, "baseline": baseline, "rows": rows}

    def vif_summary(
        self,
        model_name: str,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if LinearRegression is None:
            return {"ok": False, "error": "scikit-learn LinearRegression is unavailable."}
        resolved, lineage_error = self._resolve_candidate_lineage(model_name, context)
        if lineage_error:
            return self._lineage_error(lineage_error, model_name)
        X_train, _, _, _ = DATASTORE.get_splits()
        if X_train is None or X_train.empty:
            return {"ok": False, "error": "No training split is available."}

        metadata = resolved["artifact_metadata"]
        features = [
            str(feature)
            for feature in (metadata.get("trained_feature_names") or X_train.columns)
            if str(feature) in X_train.columns
        ]
        if not features:
            return {"ok": False, "error": "The exact candidate has no governed feature contract for VIF."}

        numeric_features = []
        work = pd.DataFrame(index=X_train.index)
        for feature in features:
            series = pd.to_numeric(X_train[feature], errors="coerce")
            if series.notna().sum() >= 2:
                work[feature] = series
                numeric_features.append(feature)
        if len(numeric_features) < 2:
            return {"ok": True, "rows": [], "message": "VIF requires at least two numeric final-model variables."}

        if len(work) > 10000:
            work = work.sample(n=10000, random_state=42)
        work = work.fillna(work.median(numeric_only=True))

        rows: List[Dict[str, Any]] = []
        for feature in numeric_features:
            other_features = [col for col in numeric_features if col != feature]
            y = work[feature].to_numpy(dtype=float)
            x = work[other_features].to_numpy(dtype=float)
            if x.shape[1] == 0 or float(np.std(y)) == 0:
                r2 = 0.0
            else:
                reg = LinearRegression()
                reg.fit(x, y)
                r2 = float(reg.score(x, y))
            tolerance = max(1.0 - r2, 1e-9)
            vif = float(1.0 / tolerance)
            if vif < 5:
                status = "pass"
            elif vif < 10:
                status = "warning"
            else:
                status = "fail"
            rows.append(
                {
                    "feature": feature,
                    "vif": vif,
                    "tolerance": tolerance,
                    "r_squared": r2,
                    "status": status,
                }
            )
        rows.sort(key=lambda row: row["vif"], reverse=True)
        return {
            "ok": True,
            "model": metadata,
            "features": numeric_features,
            "rows": rows,
        }

    def vsi_summary(
        self,
        model_name: str,
        top_n: int = 40,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        resolved, lineage_error = self._resolve_candidate_lineage(model_name, context)
        if lineage_error:
            return self._lineage_error(lineage_error, model_name)
        X_train, X_test, _, _ = DATASTORE.get_splits()
        if X_train is None or X_test is None:
            return {"ok": False, "error": "No train/holdout split is available."}

        metadata_features = resolved["artifact_metadata"].get("trained_feature_names") or []
        features = [
            str(feature)
            for feature in (metadata_features or [])
            if str(feature) in X_train.columns and str(feature) in X_test.columns
        ]
        if not features:
            importance = self.feature_importance(model_name, context).get("rows", [])
            features = [
                str(row.get("feature", "")).replace("num__", "").replace("cat__", "")
                for row in importance
                if str(row.get("feature", "")).replace("num__", "").replace("cat__", "") in X_train.columns
                and str(row.get("feature", "")).replace("num__", "").replace("cat__", "") in X_test.columns
            ]
        features += [str(col) for col in X_train.columns if str(col) in X_test.columns and str(col) not in features]

        rows: List[Dict[str, Any]] = []
        for feature in features:
            if pd.api.types.is_numeric_dtype(X_train[feature]):
                value = self._stability_index_numeric(X_train[feature], X_test[feature])
            else:
                value = self._stability_index_categorical(X_train[feature], X_test[feature])
            rows.append({"feature": feature, "value": value, "status": self._status(value)})
            if len(rows) >= max(1, min(int(top_n or 40), 100)):
                break
        rows.sort(key=lambda row: row["value"], reverse=True)
        return {"ok": True, "reference": "development_train", "comparison": "development_holdout", "rows": rows}

    def shap_summary(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if X_test.empty:
            return {"ok": True, "method": "Holdout replacement impact", "rows": []}

        sample = X_test
        if len(sample) > 1000:
            sample = sample.sample(n=1000, random_state=42)
        baseline = self._predict_score(model, sample)
        rows: List[Dict[str, Any]] = []
        for feature in sample.columns:
            x_mod = sample.copy()
            series = x_mod[feature]
            if pd.api.types.is_numeric_dtype(series):
                replacement = pd.to_numeric(series, errors="coerce").median()
            else:
                mode = series.astype(str).mode(dropna=True)
                replacement = mode.iloc[0] if len(mode) else ""
            x_mod[feature] = replacement
            perturbed = self._predict_score(model, x_mod)
            impact = float(np.mean(np.abs(baseline - perturbed)))
            signed = float(np.mean(baseline - perturbed))
            rows.append(
                {
                    "feature": str(feature),
                    "importance": impact,
                    "source": "replacement impact",
                    "signed_effect": signed,
                }
            )
        rows = _filter_target_derived_rows(rows)
        rows.sort(key=lambda row: abs(row["importance"]), reverse=True)
        return {
            "ok": True,
            "method": "Holdout replacement impact",
            "sample_count": int(len(sample)),
            "rows": rows[:30],
        }

    def _score_feature_subset(
        self,
        train: pd.DataFrame,
        test: pd.DataFrame,
        y_train: np.ndarray,
        y_test: np.ndarray,
        features: List[str],
    ) -> float:
        estimator = LogisticRegression(max_iter=3000, n_jobs=1, class_weight="balanced")
        estimator.fit(train[features], y_train)
        scores = estimator.predict_proba(test[features])[:, 1]
        return float(roc_auc_score(y_test, scores))

    def _score_regression_feature_subset(
        self,
        train: pd.DataFrame,
        test: pd.DataFrame,
        y_train: np.ndarray,
        y_test: np.ndarray,
        features: List[str],
    ) -> float:
        estimator = LinearRegression()
        estimator.fit(train[features], y_train)
        preds = estimator.predict(test[features])
        mse = float(mean_squared_error(y_test, preds)) if mean_squared_error is not None else float(np.mean((y_test - preds) ** 2))
        return float(np.sqrt(mse))

    def _prepare_rfe_design(self, X_train: pd.DataFrame, X_test: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
        train = X_train.copy()
        test = X_test.copy()
        combined = pd.concat([train, test], axis=0, ignore_index=True)
        encoded = pd.get_dummies(combined, dummy_na=True)
        encoded.columns = [str(col) for col in encoded.columns]
        encoded = encoded.apply(pd.to_numeric, errors="coerce")
        encoded = encoded.loc[:, encoded.notna().any(axis=0)]
        if encoded.empty:
            return pd.DataFrame(index=X_train.index), pd.DataFrame(index=X_test.index), []
        train_encoded = encoded.iloc[: len(train)].copy()
        test_encoded = encoded.iloc[len(train) :].copy()
        train_encoded.index = X_train.index
        test_encoded.index = X_test.index
        medians = train_encoded.median(numeric_only=True)
        train_encoded = train_encoded.fillna(medians)
        test_encoded = test_encoded.fillna(medians)
        variable_cols = [
            str(col)
            for col in train_encoded.columns
            if float(train_encoded[col].std(skipna=True) or 0.0) > 1e-12
        ]
        return train_encoded[variable_cols], test_encoded[variable_cols], variable_cols

    def _encode_binary_target(self, y_train: pd.Series, y_test: pd.Series):
        if LabelEncoder is None:
            raise ValueError("scikit-learn label encoding is unavailable.")
        encoder = LabelEncoder()
        encoder.fit(pd.concat([pd.Series(y_train), pd.Series(y_test)], ignore_index=True).astype(str))
        if len(encoder.classes_) != 2:
            raise ValueError("This analysis requires a binary target.")
        return encoder.transform(pd.Series(y_train).astype(str)), encoder.transform(pd.Series(y_test).astype(str))

    def _source_estimator_for_refit(
        self,
        model_name: str,
        task: str,
        context: Dict[str, Any] | None,
    ) -> Tuple[Any, Dict[str, Any]]:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            raise ValueError(error)
        artifact = resolved["artifact"]
        metadata: Dict[str, Any] = {
            "source_model": resolved["algorithm_id"],
            "source_candidate_id": model_name,
            "feature_selection_method": "bounded backward elimination with a logistic surrogate" if task == "classification" else "bounded backward elimination with a linear surrogate",
            "source_estimator_class": "",
            "final_estimator_class": "",
            "calibration_preserved": False,
            "refit_fallback": False,
        }
        if clone is None:
            raise ValueError(
                "The selected candidate cannot be refit because estimator cloning is unavailable."
            )

        candidate = artifact.get("model") if isinstance(artifact, dict) else artifact
        outer_calibrated = candidate.__class__.__name__ == "CalibratedClassifierCV"
        if outer_calibrated:
            base = getattr(candidate, "estimator", None) or getattr(candidate, "base_estimator", None)
            if base is not None:
                candidate = base
        if hasattr(candidate, "named_steps"):
            candidate = candidate.named_steps.get("model", candidate)

        metadata["source_estimator_class"] = candidate.__class__.__name__
        try:
            estimator = clone(candidate)
            if outer_calibrated and task == "classification" and CalibratedClassifierCV is not None:
                estimator = CalibratedClassifierCV(
                    estimator,
                    method=str(getattr(artifact, "method", "sigmoid") or "sigmoid"),
                    cv=3,
                )
                metadata["calibration_preserved"] = True
            metadata["final_estimator_class"] = estimator.__class__.__name__
            return estimator, metadata
        except Exception as exc:
            raise ValueError(
                f"The selected candidate estimator is unsupported for governed RFE refit: {exc}"
            ) from exc

    def _source_model_label(
        self,
        model_name: str,
        context: Dict[str, Any] | None,
    ) -> str:
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            raise ValueError(error)
        row = resolved["candidate"]
        return str(row.get("name") or model_name or "Selected Estimator")

    def rfe(self, model_name: str = "", keep: int = 10, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context) if model_name else None
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        if train_test_split is None:
            return {"ok": False, "error": "scikit-learn training-only validation splitting is unavailable."}
        X_full_train = DATASTORE.X_train
        y_full_train = DATASTORE.y_train
        if X_full_train is None or y_full_train is None:
            return {"ok": False, "error": "No training split is available. Train models first."}
        full_train_rows = int(len(X_full_train))
        if full_train_rows < 4:
            return {"ok": False, "error": "RFE requires at least four training rows for internal validation."}
        y_full_series = pd.Series(np.asarray(y_full_train), index=X_full_train.index)
        validation_rows = max(2, int(np.ceil(full_train_rows * 0.2)))
        validation_rows = min(validation_rows, full_train_rows - 2)
        problem_type = _lineage_value((context or {}).get("problem_type")).casefold()
        stratify = None
        if problem_type == "classification":
            class_counts = y_full_series.astype(str).value_counts()
            if (
                len(class_counts) >= 2
                and int(class_counts.min()) >= 2
                and validation_rows >= len(class_counts)
                and full_train_rows - validation_rows >= len(class_counts)
            ):
                stratify = y_full_series
        train_positions, validation_positions = train_test_split(
            np.arange(full_train_rows),
            test_size=validation_rows,
            random_state=42,
            shuffle=True,
            stratify=stratify,
        )
        X_train = X_full_train.iloc[train_positions].copy()
        X_test = X_full_train.iloc[validation_positions].copy()
        y_train = y_full_series.iloc[train_positions].copy()
        y_test = y_full_series.iloc[validation_positions].copy()
        full_train_index = X_train.index
        validation_index = X_test.index
        if len(X_train) > 15_000:
            X_train = X_train.sample(n=15_000, random_state=42)
            y_train = pd.Series(np.asarray(y_train), index=full_train_index).loc[X_train.index]
        if len(X_test) > 8_000:
            X_test = X_test.sample(n=8_000, random_state=42)
            y_test = pd.Series(np.asarray(y_test), index=validation_index).loc[X_test.index]
        prepared_train_all, prepared_test_all, feature_cols = self._prepare_rfe_design(X_train, X_test)
        if len(feature_cols) < 2:
            return {"ok": False, "error": "RFE requires at least two usable features after encoding. Confirm feature selection and preprocessing."}
        if self._is_regression_problem():
            result = self._rfe_regression(
                model_name=model_name,
                keep=keep,
                numeric_cols=feature_cols,
                prepared_train=prepared_train_all,
                prepared_test=prepared_test_all,
                y_train=y_train,
                y_test=y_test,
            )
            result.update({
                "full_train_rows": full_train_rows,
                "analysis_train_rows": int(len(X_train)),
                "analysis_validation_rows": int(len(X_test)),
                "selection_population": "training_internal_validation",
                "holdout_used": False,
            })
            return result
        if LogisticRegression is None or LabelEncoder is None or roc_auc_score is None:
            return {"ok": False, "error": "scikit-learn logistic regression metrics are unavailable."}

        numeric_cols = list(feature_cols)
        screened_feature_count = len(numeric_cols)
        if len(numeric_cols) > 14:
            single_feature_scores: List[Dict[str, Any]] = []
            for feature in numeric_cols:
                try:
                    y_train_tmp, y_test_tmp = self._encode_binary_target(y_train, y_test)
                    single_feature_scores.append(
                        {
                            "feature": feature,
                            "auc": self._score_feature_subset(prepared_train_all, prepared_test_all, y_train_tmp, y_test_tmp, [feature]),
                        }
                    )
                except Exception:
                    single_feature_scores.append({"feature": feature, "auc": 0.5})
            numeric_cols = [
                row["feature"]
                for row in sorted(single_feature_scores, key=lambda row: row["auc"], reverse=True)[:14]
            ]

        prepared_train = prepared_train_all[numeric_cols].copy()
        prepared_test = prepared_test_all[numeric_cols].copy()
        means = prepared_train.mean()
        stds = prepared_train.std().replace(0, 1).fillna(1)
        prepared_train = (prepared_train - means) / stds
        prepared_test = (prepared_test - means) / stds

        try:
            y_train_arr, y_test_arr = self._encode_binary_target(y_train, y_test)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        remaining = list(numeric_cols)
        elimination_path: List[Dict[str, Any]] = [
            {
                "feature_count": len(remaining),
                "auc": self._score_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, remaining),
                "removed_feature": None,
                "features": list(remaining),
            }
        ]
        removal_auc: Dict[str, float] = {}

        while len(remaining) > 1:
            candidates: List[Dict[str, Any]] = []
            for feature in remaining:
                subset = [col for col in remaining if col != feature]
                auc = self._score_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, subset)
                candidates.append({"feature": feature, "auc": auc, "subset": subset})
            best = max(candidates, key=lambda item: item["auc"])
            removed = str(best["feature"])
            removal_auc[removed] = float(best["auc"])
            remaining = list(best["subset"])
            elimination_path.append(
                {
                    "feature_count": len(remaining),
                    "auc": float(best["auc"]),
                    "removed_feature": removed,
                    "features": list(remaining),
                }
            )

        if remaining:
            removal_auc[remaining[0]] = float(elimination_path[-1]["auc"])

        ascending = sorted(elimination_path, key=lambda row: row["feature_count"])
        curve_rows: List[Dict[str, Any]] = []
        previous_display_auc = None
        best_seen = 0.0
        for row in ascending:
            actual_auc = float(row["auc"])
            best_seen = max(best_seen, actual_auc)
            marginal = None if previous_display_auc is None else float(best_seen - previous_display_auc)
            features = list(row["features"])
            added_feature = ""
            if curve_rows:
                previous_features = set(curve_rows[-1]["features"])
                added = [feature for feature in features if feature not in previous_features]
                added_feature = added[0] if added else ""
            elif features:
                added_feature = features[0]
            curve_rows.append(
                {
                    "feature_count": int(row["feature_count"]),
                    "auc": actual_auc,
                    "display_auc": float(best_seen),
                    "marginal_auc": marginal,
                    "added_feature": added_feature,
                    "removed_feature": row.get("removed_feature"),
                    "features": features,
                }
            )
            previous_display_auc = best_seen

        best_row = max(curve_rows, key=lambda row: row["auc"])
        best_auc = float(best_row["auc"])
        best_count = int(best_row["feature_count"])

        # Recommend the smallest model that is effectively tied with the best
        # observed internal-validation AUC. Do not stop at the first small marginal change:
        # RFE curves can dip early and then improve again after noisy features
        # are removed.
        auc_tolerance = 0.001
        recommended_count = min(
            int(row["feature_count"])
            for row in curve_rows
            if float(row["auc"]) >= best_auc - auc_tolerance
        )

        selected_curve = min(
            curve_rows,
            key=lambda row: abs(int(row["feature_count"]) - max(1, min(int(keep), len(numeric_cols)))),
        )
        selected_feature_set = set(selected_curve.get("features", []))
        final_order = [feature for feature in numeric_cols if feature in selected_feature_set]
        final_order += [feature for feature in numeric_cols if feature not in selected_feature_set]

        requested_keep = max(1, min(int(keep), len(final_order)))
        ranked_rows = [
            {
                "feature": feature,
                "importance": float(removal_auc.get(feature, 0.0)),
                "rank": index,
                "selected": index <= requested_keep,
            }
            for index, feature in enumerate(final_order, start=1)
        ]

        return {
            "ok": True,
            "task": "classification",
            "metric": "auc",
            "model": model_name,
            "recommended_count": recommended_count,
            "best_count": best_count,
            "best_auc": best_auc,
            "auc_tolerance": auc_tolerance,
            "selected_count": requested_keep,
            "screened_feature_count": screened_feature_count,
            "rfe_candidate_limit": 14,
            "full_train_rows": full_train_rows,
            "analysis_train_rows": int(len(X_train)),
            "analysis_validation_rows": int(len(X_test)),
            "selection_population": "training_internal_validation",
            "holdout_used": False,
            "rows": ranked_rows,
            "curve": curve_rows,
        }

    def _rfe_regression(
        self,
        model_name: str,
        keep: int,
        numeric_cols: List[str],
        prepared_train: pd.DataFrame | None = None,
        prepared_test: pd.DataFrame | None = None,
        y_train: pd.Series | None = None,
        y_test: pd.Series | None = None,
    ) -> Dict[str, Any]:
        if LinearRegression is None:
            return {"ok": False, "error": "scikit-learn LinearRegression is unavailable."}
        if (
            prepared_train is None
            or prepared_test is None
            or y_train is None
            or y_test is None
        ):
            return {
                "ok": False,
                "error": (
                    "Regression RFE requires the deterministic training-only internal-validation "
                    "design; final holdout data cannot be used for feature selection."
                ),
            }

        y_train_arr = pd.to_numeric(pd.Series(y_train), errors="coerce").to_numpy(dtype=float)
        y_test_arr = pd.to_numeric(pd.Series(y_test), errors="coerce").to_numpy(dtype=float)
        screened_feature_count = len(numeric_cols)
        if len(numeric_cols) > 16:
            single_feature_scores: List[Dict[str, Any]] = []
            for feature in numeric_cols:
                try:
                    single_feature_scores.append(
                        {
                            "feature": feature,
                            "rmse": self._score_regression_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, [feature]),
                        }
                    )
                except Exception:
                    single_feature_scores.append({"feature": feature, "rmse": float("inf")})
            numeric_cols = [
                row["feature"]
                for row in sorted(single_feature_scores, key=lambda row: row["rmse"])[:16]
            ]

        prepared_train = prepared_train[numeric_cols].copy()
        prepared_test = prepared_test[numeric_cols].copy()
        means = prepared_train.mean()
        stds = prepared_train.std().replace(0, 1).fillna(1)
        prepared_train = (prepared_train - means) / stds
        prepared_test = (prepared_test - means) / stds

        remaining = list(numeric_cols)
        elimination_path: List[Dict[str, Any]] = [
            {
                "feature_count": len(remaining),
                "rmse": self._score_regression_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, remaining),
                "removed_feature": None,
                "features": list(remaining),
            }
        ]
        removal_rmse: Dict[str, float] = {}

        while len(remaining) > 1:
            candidates: List[Dict[str, Any]] = []
            for feature in remaining:
                subset = [col for col in remaining if col != feature]
                rmse = self._score_regression_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, subset)
                candidates.append({"feature": feature, "rmse": rmse, "subset": subset})
            best = min(candidates, key=lambda item: item["rmse"])
            removed = str(best["feature"])
            removal_rmse[removed] = float(best["rmse"])
            remaining = list(best["subset"])
            elimination_path.append(
                {
                    "feature_count": len(remaining),
                    "rmse": float(best["rmse"]),
                    "removed_feature": removed,
                    "features": list(remaining),
                }
            )

        if remaining:
            removal_rmse[remaining[0]] = float(elimination_path[-1]["rmse"])

        ascending = sorted(elimination_path, key=lambda row: row["feature_count"])
        curve_rows: List[Dict[str, Any]] = []
        previous_display_rmse = None
        best_seen = float("inf")
        for row in ascending:
            actual_rmse = float(row["rmse"])
            best_seen = min(best_seen, actual_rmse)
            marginal = None if previous_display_rmse is None else float(previous_display_rmse - best_seen)
            features = list(row["features"])
            added_feature = ""
            if curve_rows:
                previous_features = set(curve_rows[-1]["features"])
                added = [feature for feature in features if feature not in previous_features]
                added_feature = added[0] if added else ""
            elif features:
                added_feature = features[0]
            curve_rows.append(
                {
                    "feature_count": int(row["feature_count"]),
                    "rmse": actual_rmse,
                    "display_rmse": float(best_seen),
                    "marginal_rmse": marginal,
                    "added_feature": added_feature,
                    "removed_feature": row.get("removed_feature"),
                    "features": features,
                }
            )
            previous_display_rmse = best_seen

        best_row = min(curve_rows, key=lambda row: row["rmse"])
        best_rmse = float(best_row["rmse"])
        best_count = int(best_row["feature_count"])
        rmse_tolerance = max(best_rmse * 0.005, 1e-6)
        recommended_count = min(
            int(row["feature_count"])
            for row in curve_rows
            if float(row["rmse"]) <= best_rmse + rmse_tolerance
        )

        final_order = []
        for step in curve_rows:
            added = step.get("added_feature")
            if added and added not in final_order:
                final_order.append(added)
        if len(final_order) != len(numeric_cols):
            final_order = final_order + [feature for feature in numeric_cols if feature not in final_order]

        requested_keep = max(1, min(int(keep), len(final_order)))
        ranked_rows = [
            {
                "feature": feature,
                "importance": float(removal_rmse.get(feature, best_rmse)),
                "rank": index,
                "selected": index <= requested_keep,
            }
            for index, feature in enumerate(final_order, start=1)
        ]

        return {
            "ok": True,
            "task": "regression",
            "metric": "rmse",
            "model": model_name,
            "recommended_count": recommended_count,
            "best_count": best_count,
            "best_rmse": best_rmse,
            "rmse_tolerance": rmse_tolerance,
            "selected_count": requested_keep,
            "screened_feature_count": screened_feature_count,
            "rfe_candidate_limit": 16,
            "rows": ranked_rows,
            "curve": curve_rows,
        }

    def save_rfe_model(
        self,
        model_name: str = "",
        keep: int = 10,
        context: Dict[str, Any] | None = None,
        evaluation_package_id: str = "",
    ) -> Dict[str, Any]:
        if not model_name:
            return self._lineage_error(
                "An exact candidate_id is required; ATLAS will not infer a candidate for RFE.",
            )
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return self._lineage_error(error, model_name)
        _, package_error = self._completed_evaluation_package(
            resolved["lineage"],
            evaluation_package_id,
            candidate_contract=resolved["candidate_contract"],
        )
        if package_error:
            return self._lineage_error(package_error, model_name)
        return self._lineage_error(
            (
                "RFE is training-only analysis and cannot publish a derived model artifact. "
                "Promote the exact frozen candidate through /model/save_final."
            ),
            model_name,
        )

    def _save_rfe_regression_model(self, model_name: str = "", keep: int = 10, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self._lineage_error(
            (
                "RFE is training-only analysis and cannot publish a derived model artifact. "
                "Promote the exact frozen candidate through /model/save_final."
            ),
            model_name,
        )

    def final_model_status(self, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        artifact = RESULTS.get_final_model()
        metadata = RESULTS.get_final_model_metadata() or {}
        mismatch = self._final_model_context_mismatch(metadata, context) if artifact is not None else ""
        if artifact is not None:
            summary = RESULTS.get_last_summary() or {}
            ranked = summary.get("ranked") or []
            source = next((row for row in ranked if row.get("key") == metadata.get("source_model")), {})
            X_train, _, y_train, _ = DATASTORE.get_splits()
            enriched = dict(metadata)
            enriched.setdefault("final_model_version", "final-model-v1")
            enriched.setdefault("feature_selection_method", "Recursive Feature Elimination")
            enriched.setdefault("preprocessing_pipeline", "Governed encoding, median imputation, and standardization")
            enriched.setdefault("calibration_method", source.get("calibration_method") or ("Applied" if source.get("calibration_applied") else "Not applied"))
            if y_train is not None:
                y_numeric = pd.to_numeric(pd.Series(y_train), errors="coerce").dropna()
                if len(y_numeric) and set(np.unique(y_numeric)).issubset({0, 1}):
                    enriched.setdefault("modeled_event_rate", float(np.mean(y_numeric)))
            source_meta = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta, dict) else {}
            if isinstance(source_meta, dict):
                for key in ("natural_event_rate", "original_event_rate", "population_event_rate"):
                    value = source_meta.get(key)
                    if isinstance(value, (int, float)):
                        enriched.setdefault("natural_event_rate", float(value))
                        break
            hash_payload = json.dumps(enriched, sort_keys=True, default=str).encode("utf-8")
            enriched["artifact_hash"] = hashlib.sha256(hash_payload).hexdigest()
            metadata = enriched
        return {
            "ok": True,
            "ready": artifact is not None and not mismatch,
            "artifact_present": artifact is not None,
            "stale": bool(artifact is not None and mismatch),
            "blocker": mismatch or None,
            "metadata": metadata if artifact is not None else {},
        }

    def save_selected_model_as_final(
        self,
        model_name: str = "",
        context: Dict[str, Any] | None = None,
        evaluation_package_id: str = "",
    ) -> Dict[str, Any]:
        if not model_name:
            return self._lineage_error(
                "An exact candidate_id is required; ATLAS will not select the first or latest candidate.",
            )
        mismatch = self._promotion_context_mismatch(model_name, context) if model_name else ""
        if mismatch:
            return {
                **self._lineage_error(mismatch, model_name),
                "debug": self._artifact_debug(model_name, {**self._active_model_binding(context), **(context or {})}),
            }
        resolved, error = self._resolve_candidate_lineage(model_name, context)
        if error:
            return self._lineage_error(error, model_name)
        artifact = resolved["artifact"]
        row = resolved["candidate"]
        algorithm_id = resolved["algorithm_id"]
        _, package_error = self._completed_evaluation_package(
            resolved["lineage"],
            evaluation_package_id,
            candidate_contract=resolved["candidate_contract"],
        )
        if package_error:
            return self._lineage_error(package_error, model_name)
        X_train, _, _, _ = DATASTORE.get_splits()
        metadata = {
            "source_model": algorithm_id,
            "source_candidate_id": model_name,
            "model_key": algorithm_id,
            "name": row.get("name") or algorithm_id,
            **self._final_binding_metadata(
                model_name,
                context,
                evaluation_package_id=evaluation_package_id,
            ),
            "source_estimator_class": artifact.__class__.__name__,
            "final_estimator_class": artifact.__class__.__name__,
            "feature_count": int(len(X_train.columns)) if X_train is not None else None,
            "features": list(X_train.columns) if X_train is not None else [],
            "metrics": {
                key: row.get(key)
                for key in ("auc", "pr_auc", "accuracy", "f1", "mae", "mse", "rmse", "r2", "adjusted_r2")
                if row.get(key) is not None
            },
        }
        return {
            "ok": True,
            "metadata": metadata,
            # Private transport only: the router passes this exact candidate
            # object directly into durable publication and never rereads the
            # mutable scoped final-model slot.
            "_fitted_object": artifact,
        }

    def _stability_index_numeric(self, expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
        exp = pd.to_numeric(expected, errors="coerce").dropna()
        act = pd.to_numeric(actual, errors="coerce").dropna()
        if exp.empty or act.empty:
            return 0.0
        quantiles = np.unique(np.quantile(exp, np.linspace(0, 1, bins + 1)))
        internal_edges = quantiles[1:-1]
        if len(internal_edges) < 1:
            min_value = float(exp.min())
            max_value = float(exp.max())
            if min_value == max_value:
                internal_edges = np.asarray([min_value], dtype=float)
            else:
                internal_edges = np.linspace(min_value, max_value, min(bins, 4) + 1)[1:-1]
        edges = np.concatenate(([-np.inf], np.unique(internal_edges), [np.inf]))
        exp_counts = pd.cut(exp, edges, include_lowest=True, duplicates="drop").value_counts(sort=False)
        act_counts = pd.cut(act, edges, include_lowest=True, duplicates="drop").value_counts(sort=False)
        return self._psi_from_counts(exp_counts.to_numpy(), act_counts.to_numpy())

    def _stability_index_categorical(self, expected: pd.Series, actual: pd.Series) -> float:
        exp = expected.astype(str).fillna("__missing__")
        act = actual.astype(str).fillna("__missing__")
        cats = sorted(set(exp.unique()).union(set(act.unique())))
        exp_counts = np.asarray([(exp == cat).sum() for cat in cats], dtype=float)
        act_counts = np.asarray([(act == cat).sum() for cat in cats], dtype=float)
        return self._psi_from_counts(exp_counts, act_counts)

    def _psi_from_counts(self, expected_counts: np.ndarray, actual_counts: np.ndarray) -> float:
        expected_pct = expected_counts.astype(float) / max(float(expected_counts.sum()), 1.0)
        actual_pct = actual_counts.astype(float) / max(float(actual_counts.sum()), 1.0)
        expected_pct = np.clip(expected_pct, 1e-6, None)
        actual_pct = np.clip(actual_pct, 1e-6, None)
        return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))

    def _status(self, value: float) -> str:
        if value < 0.10:
            return "pass"
        if value < 0.25:
            return "warning"
        return "fail"

    def _positive_rate(self, y: pd.Series) -> float | None:
        labels = pd.Series(y).dropna().astype(str)
        classes = sorted(labels.unique())
        if len(classes) != 2:
            return None
        return float((labels == classes[-1]).mean())

    def _is_regression_problem(self) -> bool:
        summary = RESULTS.get_last_summary() or {}
        if summary.get("problem_type") == "regression":
            return True
        ranked = summary.get("ranked") or []
        return any(row.get("task") == "regression" for row in ranked)

    def _regression_metrics(self, y_true: pd.Series, predictions: np.ndarray, n_features: int = 0) -> Dict[str, Any]:
        y = pd.to_numeric(pd.Series(y_true), errors="coerce")
        pred = pd.Series(np.asarray(predictions, dtype=float), index=y.index)
        valid = y.notna() & pred.notna()
        if not valid.any():
            return {}
        y_arr = y[valid].to_numpy(dtype=float)
        pred_arr = pred[valid].to_numpy(dtype=float)
        mse = float(mean_squared_error(y_arr, pred_arr)) if mean_squared_error is not None else float(np.mean((y_arr - pred_arr) ** 2))
        mae = float(mean_absolute_error(y_arr, pred_arr)) if mean_absolute_error is not None else float(np.mean(np.abs(y_arr - pred_arr)))
        r2 = float(r2_score(y_arr, pred_arr)) if r2_score is not None else None
        n_obs = int(len(y_arr))
        p = int(max(n_features, 0))
        adjusted_r2 = (
            float(1 - (1 - r2) * (n_obs - 1) / max(n_obs - p - 1, 1))
            if r2 is not None and n_obs > p + 1
            else None
        )
        residuals = y_arr - pred_arr
        return {
            "mae": mae,
            "mse": mse,
            "rmse": float(np.sqrt(mse)),
            "r2": r2,
            "adjusted_r2": adjusted_r2,
            "mean_residual": float(np.mean(residuals)),
            "mean_abs_residual": float(np.mean(np.abs(residuals))),
        }

    def _default_priors(self) -> Dict[str, Any]:
        prevalence = DATASTORE.meta.get("target_prevalence") or {}
        X_train, _, y_train, _ = DATASTORE.get_splits()
        model_prior = prevalence.get("train")
        if model_prior is None and y_train is not None:
            model_prior = self._positive_rate(y_train)
        original_prior = prevalence.get("original")
        if original_prior is None:
            df = DATASTORE.get_active_df()
            target = DATASTORE.target
            if df is not None and target and target in df.columns:
                original_prior = self._positive_rate(df[target])
        return {
            "original_prior": original_prior,
            "model_prior": model_prior,
            "split_config": DATASTORE.meta.get("split_config") or {},
            "train_rows": int(len(X_train)) if X_train is not None else None,
        }

    def _prior_correct_scores(
        self,
        scores: np.ndarray,
        method: str = "none",
        original_prior: float | None = None,
        model_prior: float | None = None,
    ) -> np.ndarray:
        method = str(method or "none").lower()
        scores = np.asarray(scores, dtype=float)
        if method in ("none", "raw", ""):
            return scores
        if method not in ("prior_odds", "pozzolo"):
            return scores
        if original_prior is None or model_prior is None:
            return scores
        original_prior = float(np.clip(original_prior, 1e-6, 1 - 1e-6))
        model_prior = float(np.clip(model_prior, 1e-6, 1 - 1e-6))
        score_odds = np.clip(scores, 1e-9, 1 - 1e-9) / np.clip(1 - scores, 1e-9, 1)
        prior_factor = (original_prior / (1 - original_prior)) / (model_prior / (1 - model_prior))
        corrected_odds = score_odds * prior_factor
        return corrected_odds / (1 + corrected_odds)

    def _lift_table(self, y_true: pd.Series, scores: np.ndarray, deciles: int = 10) -> List[Dict[str, Any]]:
        labels = pd.Series(y_true).astype(str)
        classes = sorted(pd.Series(y_true).dropna().astype(str).unique())
        if len(classes) != 2:
            return []
        y_arr = (labels == classes[-1]).astype(int).to_numpy()
        scores = np.asarray(scores, dtype=float)
        if len(scores) != len(y_arr):
            return []
        order = np.argsort(-scores)
        y_sorted = y_arr[order]
        score_sorted = scores[order]
        total_positives = int(np.sum(y_sorted))
        base_rate = float(np.mean(y_sorted)) if len(y_sorted) else 0.0
        cumulative_positives = 0
        rows: List[Dict[str, Any]] = []
        for decile, indices in enumerate(np.array_split(np.arange(len(y_sorted)), deciles), start=1):
            if not len(indices):
                continue
            bucket_y = y_sorted[indices]
            bucket_scores = score_sorted[indices]
            positives = int(np.sum(bucket_y))
            cumulative_positives += positives
            event_rate = float(np.mean(bucket_y)) if len(bucket_y) else 0.0
            rows.append(
                {
                    "decile": int(decile),
                    "n": int(len(indices)),
                    "positives": positives,
                    "event_rate": event_rate,
                    "lift": float(event_rate / base_rate) if base_rate > 0 else 0.0,
                    "cumulative_positives": int(cumulative_positives),
                    "capture_rate": float(cumulative_positives / total_positives) if total_positives > 0 else 0.0,
                    "min_score": float(np.min(bucket_scores)),
                    "max_score": float(np.max(bucket_scores)),
                    "mean_score": float(np.mean(bucket_scores)),
                }
            )
        return rows

    def _resolve_scoring_model(self, model_name: str = "") -> Tuple[Any, Dict[str, Any]]:
        if model_name in ("", "final", "final_rfe"):
            final_model = RESULTS.get_final_model()
            metadata = RESULTS.get_final_model_metadata() or {}
            if final_model is not None:
                mismatch = self._final_model_context_mismatch(metadata)
                if mismatch:
                    raise ValueError(mismatch)
                return final_model, metadata
            raise ValueError("No governed final model is available for scoring. Save a current trained model as final first.")
        artifact = self._artifact(model_name)
        if artifact is None:
            raise ValueError("No model artifact is available for scoring.")
        mismatch = self._promotion_context_mismatch(model_name)
        if mismatch:
            raise ValueError(mismatch)
        metadata = RESULTS.get_model_artifact_metadata(model_name) or {}
        summary = RESULTS.get_last_summary() or {}
        X_train, _, _, _ = DATASTORE.get_splits()
        return artifact, {
            **metadata,
            "model_key": model_name,
            "name": next(
                (row.get("name") for row in (summary.get("ranked") or []) if row.get("key") == model_name),
                model_name,
            ),
            "features": list(X_train.columns) if X_train is not None else [],
        }

    def export_model_bundle(self, model_name: str = "final") -> Tuple[bytes, str]:
        _, metadata = self._resolve_scoring_model(model_name)
        summary = RESULTS.get_last_summary() or {}
        X_train, _, _, _ = DATASTORE.get_splits()
        ranked = summary.get("ranked") or []
        selected_key = metadata.get("model_key") or model_name
        selected_summary = next((row for row in ranked if row.get("key") == selected_key), {})
        manifest = {
            "schema": "atlas.model_manifest.v1",
            "metadata": {
                **metadata,
                "target": DATASTORE.target,
                "problem_type": summary.get("problem_type"),
                "feature_columns": list(X_train.columns) if X_train is not None else metadata.get("features", []),
                "selected_model_summary": selected_summary,
                "exported_at": datetime.now().isoformat(),
                "export_format": "json_manifest",
            },
            "deployment_status": "manifest_only",
            "scoring_note": "ATLAS does not export executable model objects through this endpoint. Use the manifest for governed review and deploy through a signed model registry or approved ONNX/skops pipeline.",
            "metrics": selected_summary.get("metrics") or {},
            "hyperparameters": selected_summary.get("best_params") or {},
            "ranked_models": ranked,
        }
        raw_name = str(metadata.get("name") or selected_key or "model")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_name).strip("_").lower() or "model"
        return json.dumps(manifest, indent=2, sort_keys=True, default=str).encode("utf-8"), f"{safe_name}_manifest.json"

    def score_dataset(
        self,
        df: pd.DataFrame,
        dataset_type: str = "test",
        model_name: str = "final",
        correction_method: str = "none",
        original_prior: float | None = None,
        model_prior: float | None = None,
    ) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"ok": False, "error": "Uploaded scoring dataset is empty."}
        try:
            model, metadata = self._resolve_scoring_model(model_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "stale_model": True}
        target = DATASTORE.target
        y_true = None
        original_df = df.reset_index(drop=True).copy()
        X = df.copy()
        if target and target in X.columns:
            y_true = X[target].copy()
            X = X.drop(columns=[target])

        task = "regression" if self._is_regression_problem() else "classification"
        model_features = [str(feature) for feature in (metadata.get("features") or [])]
        matched_features: List[str] = []
        missing_features: List[str] = []
        if isinstance(model, dict) and model.get("kind") in ("rfe_logistic", "rfe_regression", "rfe_classifier", "rfe_regressor"):
            _, matched_features, missing_features = self._prepare_final_feature_frame(model, X)
            model_features = [str(feature) for feature in model.get("features", model_features)]
        else:
            normalized_columns = {str(col).strip().lower(): col for col in X.columns}
            for feature in model_features:
                if feature in X.columns or feature.strip().lower() in normalized_columns:
                    matched_features.append(feature)
                else:
                    missing_features.append(feature)
        scores = self._predict_score(model, X)
        priors = self._default_priors()
        if original_prior is None:
            original_prior = priors.get("original_prior")
        if model_prior is None:
            model_prior = priors.get("model_prior")
        adjusted_scores = (
            scores
            if task == "regression"
            else self._prior_correct_scores(scores, correction_method, original_prior, model_prior)
        )
        labels = (adjusted_scores >= 0.5).astype(int) if task == "classification" else adjusted_scores
        scored_df = build_full_scored_output_frame(
            original_df=original_df,
            target=str(target) if target else None,
            y_true=y_true,
            scores=np.asarray(scores),
            adjusted_scores=np.asarray(adjusted_scores),
            labels=np.asarray(labels),
            task=task,
            split=dataset_type,
        )
        response: Dict[str, Any] = {
            "ok": True,
            "task": task,
            "dataset_type": dataset_type,
            "model": metadata,
            "rows": int(len(X)),
            "score_summary": {
                "min": float(np.min(scores)) if len(scores) else None,
                "mean": float(np.mean(scores)) if len(scores) else None,
                "max": float(np.max(scores)) if len(scores) else None,
            },
            "scoring_diagnostics": {
                "model_feature_count": int(len(model_features)),
                "matched_feature_count": int(len(matched_features)),
                "missing_features": missing_features,
                "prediction_std": float(np.std(scores)) if len(scores) else None,
                "constant_prediction": bool(len(scores) > 1 and float(np.std(scores)) < 1e-10),
            },
            "adjusted_score_summary": {
                "min": float(np.min(adjusted_scores)) if len(adjusted_scores) else None,
                "mean": float(np.mean(adjusted_scores)) if len(adjusted_scores) else None,
                "max": float(np.max(adjusted_scores)) if len(adjusted_scores) else None,
            },
            "probability_correction": {
                "method": correction_method,
                "original_prior": original_prior,
                "model_prior": model_prior,
                "default_original_prior": priors.get("original_prior"),
                "default_model_prior": priors.get("model_prior"),
                "split_config": priors.get("split_config"),
            },
            "target_column": str(target) if target else None,
            "scored_rows": dataframe_to_json_records(scored_df),
            "scored_columns": [str(column) for column in scored_df.columns],
            "scored_row_scope": "full_scored_output",
            "preview": [
                {
                    "row": int(i + 1),
                    "score": float(score),
                    "adjusted_score": float(adjusted),
                    "prediction": float(label),
                    **(
                        {"actual": safe_numeric_preview_value(pd.Series(y_true).iloc[i]), str(target): safe_numeric_preview_value(pd.Series(y_true).iloc[i])}
                        if y_true is not None and i < len(pd.Series(y_true))
                        else {}
                    ),
                }
                for i, (score, adjusted, label) in enumerate(zip(scores[:25], adjusted_scores[:25], labels[:25]))
            ],
        }

        if task == "regression":
            response["probability_correction"] = {"method": "not_applicable"}

        if dataset_type.lower() == "test":
            RESULTS.set_scoring_reference(
                {
                    "kind": "uploaded_test",
                    "model_key": metadata.get("model_key") or model_name,
                    "model_name": metadata.get("name") or model_name,
                    "features": list(metadata.get("features") or []),
                    "X": X.copy(),
                    "scores": np.asarray(adjusted_scores, dtype=float),
                }
            )

        if y_true is not None and task == "regression":
            response["metrics"] = self._regression_metrics(y_true, adjusted_scores, n_features=X.shape[1])
        elif y_true is not None and LabelEncoder is not None:
            try:
                encoder = LabelEncoder()
                y_arr = encoder.fit_transform(pd.Series(y_true).astype(str))
                if len(encoder.classes_) == 2:
                    response["metrics"] = {
                        "auc": float(roc_auc_score(y_arr, adjusted_scores)) if roc_auc_score is not None else None,
                        "pr_auc": float(average_precision_score(y_arr, adjusted_scores)) if average_precision_score is not None else None,
                        "accuracy": float(accuracy_score(y_arr, labels)) if accuracy_score is not None else None,
                        "precision": float(precision_score(y_arr, labels, zero_division=0)) if precision_score is not None else None,
                        "recall": float(recall_score(y_arr, labels, zero_division=0)) if recall_score is not None else None,
                        "f1": float(f1_score(y_arr, labels, zero_division=0)) if f1_score is not None else None,
                        "brier_score": float(brier_score_loss(y_arr, adjusted_scores)) if brier_score_loss is not None else None,
                        "event_rate": float(np.mean(y_arr)) if len(y_arr) else None,
                        "confusion": confusion_matrix(y_arr, labels).tolist() if confusion_matrix is not None else None,
                    }
                    if roc_curve is not None:
                        fpr, tpr, _ = roc_curve(y_arr, adjusted_scores)
                        response["metrics"]["ks"] = float(np.max(tpr - fpr)) if len(fpr) else None
                    response["lift"] = self._lift_table(y_true, adjusted_scores)
            except Exception as exc:
                response["metrics_error"] = str(exc)

        if dataset_type.lower() in {"test", "oot"}:
            X_train, X_test, _, _ = DATASTORE.get_splits()
            reference = X_train if X_train is not None else X_test
            if reference is not None:
                ref_scores = self._prior_correct_scores(
                    self._predict_score(model, reference),
                    correction_method,
                    original_prior,
                    model_prior,
                )
                response["psi"] = {
                    "name": "score",
                    "value": self._stability_index_numeric(pd.Series(ref_scores), pd.Series(adjusted_scores)),
                }
                response["psi"]["status"] = self._status(response["psi"]["value"])
                vsi_rows = []
                model_features = [
                    str(feature)
                    for feature in (metadata.get("features") or [])
                    if str(feature) in reference.columns and str(feature) in X.columns
                ]
                common = model_features or [col for col in reference.columns if col in X.columns]
                for col in common:
                    if pd.api.types.is_numeric_dtype(reference[col]):
                        value = self._stability_index_numeric(reference[col], X[col])
                    else:
                        value = self._stability_index_categorical(reference[col], X[col])
                    vsi_rows.append({"feature": col, "value": value, "status": self._status(value)})
                vsi_rows.sort(key=lambda row: row["value"], reverse=True)
                response["vsi"] = vsi_rows[:50]
                response["vsi_scope"] = "model_features" if model_features else "all_common_features"
                response["stability_reference"] = "development_train"
        return response

    def score_development_split(
        self,
        dataset_type: str = "train",
        model_name: str = "final",
        correction_method: str = "none",
        original_prior: float | None = None,
        model_prior: float | None = None,
    ) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        split_key = str(dataset_type or "train").lower()
        if split_key == "test":
            X, y = X_test, y_test
        else:
            X, y = X_train, y_train
            split_key = "train"
        if X is None or y is None:
            return {"ok": False, "error": f"No {split_key.upper()} development split is available. Train models first."}
        df = X.copy()
        target = DATASTORE.target or getattr(y, "name", None) or "target"
        df[str(target)] = pd.Series(y).reset_index(drop=True).values
        result = self.score_dataset(
            df=df,
            dataset_type=split_key,
            model_name=model_name,
            correction_method=correction_method,
            original_prior=original_prior,
            model_prior=model_prior,
        )
        if result.get("ok"):
            result["dataset_identity"] = f"Governed development {split_key.upper()} split"
            result["dataset_version"] = DATASTORE.meta.get("dataset_version") or "Not recorded"
        return result

    def decision_boundary(
        self,
        model_name: str,
        x_feature: str = "",
        y_feature: str = "",
        resolution: int = 60,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, y_test = self._test_data()
        numeric_cols = [col for col in X_test.columns if pd.api.types.is_numeric_dtype(X_test[col])]
        if len(numeric_cols) < 2:
            return {"ok": False, "error": "Decision boundary requires at least two numeric features."}

        if PCA is not None and (not x_feature or not y_feature or x_feature.startswith("PCA") or y_feature.startswith("PCA")):
            numeric = X_test[numeric_cols].copy()
            for col in numeric_cols:
                numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
            medians = numeric.median(numeric_only=True)
            numeric = numeric.fillna(medians)
            means = numeric.mean()
            stds = numeric.std().replace(0, 1).fillna(1)
            scaled = (numeric - means) / stds
            pca = PCA(n_components=2)
            coords = pca.fit_transform(scaled)
            x_vals = coords[:, 0]
            y_vals = coords[:, 1]
            x_min, x_max = float(np.quantile(x_vals, 0.02)), float(np.quantile(x_vals, 0.98))
            y_min, y_max = float(np.quantile(y_vals, 0.02)), float(np.quantile(y_vals, 0.98))
            resolution = max(25, min(80, int(resolution or 60)))
            xs = np.linspace(x_min, x_max, resolution)
            ys = np.linspace(y_min, y_max, resolution)
            grid_rows: List[Dict[str, Any]] = []
            base = pd.DataFrame([X_test.iloc[0].copy() for _ in range(resolution)])
            for y_val in ys:
                pca_batch = np.column_stack([xs, np.full_like(xs, y_val)])
                inverse_scaled = pca.inverse_transform(pca_batch)
                numeric_batch = pd.DataFrame(inverse_scaled, columns=numeric_cols) * stds + means
                batch = base.copy()
                for col in numeric_cols:
                    batch[col] = numeric_batch[col].to_numpy()
                scores = self._predict_score(model, batch)
                for x_val, score in zip(xs, scores):
                    grid_rows.append({"x": float(x_val), "y": float(y_val), "score": float(score)})
            try:
                _, y_test_arr = self._encode_binary_target(y_test, y_test)
            except Exception:
                y_test_arr = np.zeros(len(X_test), dtype=int)
            points = [
                {"x": float(px), "y": float(py), "class": int(y_test_arr[i]) if i < len(y_test_arr) else 0}
                for i, (px, py) in enumerate(coords[:500])
            ]
            return {
                "ok": True,
                "x_feature": "PCA 1",
                "y_feature": "PCA 2",
                "x_domain": [x_min, x_max],
                "y_domain": [y_min, y_max],
                "resolution": resolution,
                "grid": grid_rows,
                "points": points,
                "numeric_features": ["PCA 1", "PCA 2"] + numeric_cols,
            }

        importance = self.feature_importance(model_name, context).get("rows", [])
        ordered = [row["feature"] for row in importance if row.get("feature") in numeric_cols]
        ordered += [col for col in numeric_cols if col not in ordered]
        x_name = x_feature if x_feature in numeric_cols else ordered[0]
        y_name = y_feature if y_feature in numeric_cols and y_feature != x_name else ordered[1]

        work = X_test.copy()
        base_row: Dict[str, Any] = {}
        for col in work.columns:
            if pd.api.types.is_numeric_dtype(work[col]):
                base_row[col] = float(pd.to_numeric(work[col], errors="coerce").median())
            else:
                mode = work[col].astype(str).mode(dropna=True)
                base_row[col] = mode.iloc[0] if len(mode) else ""

        x_values = pd.to_numeric(work[x_name], errors="coerce").dropna()
        y_values = pd.to_numeric(work[y_name], errors="coerce").dropna()
        if x_values.empty or y_values.empty:
            return {"ok": False, "error": "Selected boundary features do not have numeric values."}
        x_min, x_max = float(x_values.quantile(0.02)), float(x_values.quantile(0.98))
        y_min, y_max = float(y_values.quantile(0.02)), float(y_values.quantile(0.98))
        if x_min == x_max:
            x_min -= 1
            x_max += 1
        if y_min == y_max:
            y_min -= 1
            y_max += 1

        resolution = max(25, min(80, int(resolution or 60)))
        xs = np.linspace(x_min, x_max, resolution)
        ys = np.linspace(y_min, y_max, resolution)
        grid_rows: List[Dict[str, Any]] = []
        for y_val in ys:
            batch = pd.DataFrame([base_row.copy() for _ in xs])
            batch[x_name] = xs
            batch[y_name] = y_val
            scores = self._predict_score(model, batch)
            for x_val, score in zip(xs, scores):
                grid_rows.append({"x": float(x_val), "y": float(y_val), "score": float(score)})

        try:
            _, y_test_arr = self._encode_binary_target(y_test, y_test)
        except Exception:
            y_test_arr = np.zeros(len(work), dtype=int)
        points_df = work[[x_name, y_name]].copy()
        points_df[x_name] = pd.to_numeric(points_df[x_name], errors="coerce")
        points_df[y_name] = pd.to_numeric(points_df[y_name], errors="coerce")
        points = []
        for idx, row in points_df.dropna().head(500).iterrows():
            pos = list(work.index).index(idx) if idx in work.index else 0
            points.append(
                {
                    "x": float(row[x_name]),
                    "y": float(row[y_name]),
                    "class": int(y_test_arr[pos]) if pos < len(y_test_arr) else 0,
                }
            )

        return {
            "ok": True,
            "x_feature": x_name,
            "y_feature": y_name,
            "x_domain": [x_min, x_max],
            "y_domain": [y_min, y_max],
            "resolution": resolution,
            "grid": grid_rows,
            "points": points,
            "numeric_features": numeric_cols,
        }

def safe_numeric_preview_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return float(value)
        if isinstance(value, (int, float, str, bool)):
            return value
        return float(value)
    except Exception:
        return str(value)


def dataframe_to_json_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return records
    for raw in df.to_dict(orient="records"):
        records.append({str(key): safe_numeric_preview_value(value) for key, value in raw.items()})
    return records


def build_full_scored_output_frame(
    original_df: pd.DataFrame,
    target: str | None,
    y_true: pd.Series | None,
    scores: np.ndarray,
    adjusted_scores: np.ndarray,
    labels: np.ndarray,
    task: str,
    split: str,
) -> pd.DataFrame:
    scored = original_df.reset_index(drop=True).copy()
    if "row" not in {str(column).lower() for column in scored.columns}:
        scored.insert(0, "row", np.arange(1, len(scored) + 1))

    if task == "regression":
        predictions = pd.Series(adjusted_scores, index=scored.index, dtype="float64")
        scored["predicted_value"] = predictions
        scored["prediction"] = predictions
        if y_true is not None:
            actual = pd.to_numeric(pd.Series(y_true).reset_index(drop=True), errors="coerce")
            if target:
                scored[target] = pd.Series(y_true).reset_index(drop=True)
            scored["actual"] = actual
            residual = actual - predictions
            scored["atlas_residual"] = residual
            scored["atlas_abs_residual"] = residual.abs()
            scored["atlas_squared_residual"] = residual * residual
            scored["atlas_percent_error"] = residual.where(actual != 0) / actual.where(actual != 0)
        else:
            scored["actual"] = None
            scored["atlas_residual"] = None
            scored["atlas_abs_residual"] = None
            scored["atlas_squared_residual"] = None
            scored["atlas_percent_error"] = None
    else:
        scored["score"] = pd.Series(scores, index=scored.index, dtype="float64")
        scored["adjusted_score"] = pd.Series(adjusted_scores, index=scored.index, dtype="float64")
        scored["prediction"] = pd.Series(labels, index=scored.index)
        if y_true is not None:
            if target:
                scored[target] = pd.Series(y_true).reset_index(drop=True)
            scored["actual"] = pd.Series(y_true).reset_index(drop=True)

    scored["split"] = str(split or "").upper()
    return scored


EVAL = EvaluationService()

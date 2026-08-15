"""Governed preprocessing policy validation and fold-local execution.

Preparation pages approve a *recipe*.  They do not own a reusable fitted
dataset.  This module is the execution boundary used by training and final
reporting: every estimator is fitted from the rows explicitly supplied to
``fit`` and can only apply those frozen parameters in ``transform``.

The implementation intentionally contains no DatasetStore access.  That makes
validation-fold or final-holdout influence impossible unless a caller passes
those rows as the fit population, which the training/evaluation boundaries
forbid and test independently.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .preprocessing_contract import (
    FIT_SCOPE_CANDIDATE_DEVELOPMENT,
    FIT_SCOPE_FINAL_DEVELOPMENT,
    FIT_SCOPE_FOLD_TRAINING,
    PREPROCESSING_CONTRACT_VERSION,
    apply_missing_recipe,
    apply_outlier_recipe,
    canonical_hash,
    classify_preprocessing_record,
    fit_metadata,
    fit_missing_recipe,
    fit_outlier_recipe,
    special_mask,
)

try:  # pragma: no cover - import failure is reported at the execution boundary
    from sklearn.base import BaseEstimator, TransformerMixin
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
except Exception:  # pragma: no cover
    BaseEstimator = object  # type: ignore[assignment]
    TransformerMixin = object  # type: ignore[assignment]
    ColumnTransformer = None
    Pipeline = None
    OneHotEncoder = None
    StandardScaler = None


LEGACY_PREPROCESSING_STALE_REASON = (
    "legacy_preprocessing_fit_scope_unverified"
)
VALID_MISSING_STRATEGIES = {"NONE", "MEAN", "MEDIAN", "MODE", "CONSTANT"}


class PreprocessingContractError(ValueError):
    """Raised when governed preparation lineage is absent or unverifiable."""

    def __init__(self, message: str, *, code: str = "preprocessing_contract_invalid"):
        super().__init__(message)
        self.code = code


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, np.generic):
        return _json_scalar(value.item())
    if isinstance(value, Mapping):
        return {str(key): _json_scalar(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_scalar(item) for item in value]
    return str(value)


def canonical_preprocessing_hash(value: Mapping[str, Any]) -> str:
    return canonical_hash(dict(value))


def _identity_projection(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": _text(source.get("project_id")),
        "dataset_id": _text(source.get("dataset_id")),
        "dataset_version_id": _text(source.get("dataset_version_id")),
        "analysis_partition_id": _text(source.get("analysis_partition_id")),
        "analysis_partition_revision": int(
            source.get("analysis_partition_revision")
            or source.get("revision")
            or 0
        ),
    }


def default_no_treatment_contract(
    *,
    identity: Mapping[str, Any] | None = None,
    feature_names: Sequence[str] = (),
    source: str = "direct_test_no_treatment",
) -> dict[str, Any]:
    """Return an explicit v2 NONE recipe for isolated direct engine callers.

    HTTP training never uses this compatibility constructor; its preflight
    requires a persisted approved recipe.  Keeping direct unit/CLI callers
    explicit avoids reintroducing a hidden generic imputation policy.
    """

    identity_fields = _identity_projection(identity or {})
    seed = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "approved_preprocessing_policy",
        **identity_fields,
        "lineage": dict(identity_fields),
        "status": "approved",
        "executable": True,
        "stage_status": {
            "outlier_policy": "approved",
            "missing_policy": "approved",
        },
        "policy_scope": "governed_recipe",
        "preprocessing_policy_revision": 1,
        "source": source,
        "feature_names": [str(value) for value in feature_names],
        "special_value_contract": {
            "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
            "status": "not_required",
            "special_value_review_id": None,
            "revision": 0,
            "detection_fingerprint": None,
            "features": {},
        },
        "outlier_policy": {
            "global_method": "NONE",
            "features": {},
        },
        "missing_policy": {
            "active_treatment": "NONE",
            "zero_null_validated": True,
            "true_null_cell_count": 0,
            "materialization_required": False,
            "processed_frame_created": False,
            "features": {},
        },
        "sealed_holdout_used_for_fit": False,
        "sealed_holdout_transformed": False,
        "backend_materialization": False,
        "processed_frame_materialized": False,
    }
    policy_payload = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "lineage": identity_fields,
        "special_value_contract": seed["special_value_contract"],
        "outlier_policy": seed["outlier_policy"],
        "missing_policy": seed["missing_policy"],
    }
    checksum = canonical_preprocessing_hash(policy_payload)
    return {
        **seed,
        "preprocessing_policy_id": f"preprocessing-policy-{checksum[:20]}",
        "preprocessing_policy_hash": checksum,
    }


def validate_preprocessing_contract(
    contract: Mapping[str, Any],
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one current approved recipe without inferring missing lineage."""

    if not isinstance(contract, Mapping):
        raise PreprocessingContractError(
            "A governed preprocessing recipe is required before training."
        )
    try:
        version = int(contract.get("preprocessing_contract_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version != PREPROCESSING_CONTRACT_VERSION:
        raise PreprocessingContractError(
            "The stored preparation artifact predates the governed fit-scope contract and must be reconfirmed and recomputed.",
            code=LEGACY_PREPROCESSING_STALE_REASON,
        )
    if _text(contract.get("artifact_kind")) != "approved_preprocessing_policy":
        raise PreprocessingContractError(
            "Both Outliers and Missing Values must be explicitly completed before training; a partial preparation policy is not executable.",
            code="preprocessing_policy_incomplete",
        )
    if contract.get("executable") is not True:
        raise PreprocessingContractError(
            "The governed preprocessing policy is incomplete and cannot be executed.",
            code="preprocessing_policy_incomplete",
        )
    if _text(contract.get("status")).casefold() not in {
        "approved",
        "current",
        "confirmed",
    }:
        raise PreprocessingContractError(
            "The governed preprocessing recipe is not approved and current."
        )
    required = (
        "preprocessing_policy_id",
        "preprocessing_policy_revision",
        "preprocessing_policy_hash",
    )
    missing = [name for name in required if contract.get(name) in (None, "")]
    if missing:
        raise PreprocessingContractError(
            "The governed preprocessing recipe is missing: " + ", ".join(missing) + "."
        )

    resolved = deepcopy(dict(contract))
    resolved.setdefault("policy_id", resolved["preprocessing_policy_id"])
    resolved.setdefault(
        "policy_revision", resolved["preprocessing_policy_revision"]
    )
    resolved.setdefault("policy_checksum", resolved["preprocessing_policy_hash"])
    expected_identity = _identity_projection(identity or {})
    if identity:
        for field in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "analysis_partition_id",
        ):
            expected = _text(expected_identity.get(field))
            actual = _text(resolved.get(field))
            if expected and actual != expected:
                raise PreprocessingContractError(
                    f"The governed preprocessing recipe does not match {field}."
                )
        expected_revision = int(
            expected_identity.get("analysis_partition_revision") or 0
        )
        if expected_revision and int(
            resolved.get("analysis_partition_revision") or 0
        ) != expected_revision:
            raise PreprocessingContractError(
                "The governed preprocessing recipe does not match the Analysis Partition revision."
            )

    if bool(
        resolved.get("final_holdout_parameter_influence")
        or resolved.get("sealed_holdout_used_for_fit")
    ):
        raise PreprocessingContractError(
            "The preprocessing recipe is invalid because final-holdout values influenced fitted parameters."
        )
    if bool(
        resolved.get("final_holdout_transformed_or_materialized_prelock")
        or resolved.get("sealed_holdout_transformed")
    ):
        raise PreprocessingContractError(
            "The preprocessing recipe is invalid because the final holdout was transformed before candidate lock."
        )

    outlier = resolved.get("outlier_policy")
    missing_policy = resolved.get("missing_policy")
    if (
        not isinstance(outlier, Mapping)
        or not outlier
        or not isinstance(missing_policy, Mapping)
        or not missing_policy
    ):
        raise PreprocessingContractError(
            "The governed preprocessing recipe must contain outlier_policy and missing_policy."
        )
    stage_status = (
        resolved.get("stage_status")
        if isinstance(resolved.get("stage_status"), Mapping)
        else {}
    )
    if not stage_status or any(
        _text(stage_status.get(name)).casefold() != "approved"
        for name in ("outlier_policy", "missing_policy")
    ):
        raise PreprocessingContractError(
            "Outliers and Missing Values must each have an approved governed policy before training.",
            code="preprocessing_policy_incomplete",
        )
    if "active_treatment" not in missing_policy:
        raise PreprocessingContractError(
            "The Missing Values stage lacks an explicit active_treatment decision.",
            code="missing_policy_decision_unverified",
        )
    active_missing = _text(missing_policy.get("active_treatment")).upper()
    if active_missing not in VALID_MISSING_STRATEGIES | {"FEATURE_SPECIFIC"}:
        raise PreprocessingContractError(
            f"Unsupported governed missing-value treatment: {active_missing}."
        )
    if active_missing == "NONE" and not (
        int(missing_policy.get("true_null_cell_count") or 0) == 0
        and missing_policy.get("materialization_required") is False
        and missing_policy.get("processed_frame_created") is False
        and bool(missing_policy.get("zero_null_validated"))
    ):
        raise PreprocessingContractError(
            "An active NONE missing-value decision requires explicit zero-null validation and proof that no processed frame was created.",
            code="missing_policy_zero_null_evidence_unverified",
        )
    declared_hash = _text(resolved.get("preprocessing_policy_hash"))
    policy_payload = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "lineage": dict(resolved.get("lineage") or {}),
        "special_value_contract": dict(
            resolved.get("special_value_contract") or {}
        ),
        "outlier_policy": dict(outlier),
        "missing_policy": dict(missing_policy),
    }
    if declared_hash != canonical_preprocessing_hash(policy_payload):
        raise PreprocessingContractError(
            "The governed preprocessing policy checksum does not match its executable recipe.",
            code="preprocessing_policy_checksum_mismatch",
        )
    return resolved


def resolve_preprocessing_contract(
    store_meta: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the sole persisted v2 recipe; classify old applications stale."""

    for key in ("preprocessing_policy", "preprocessing_contract"):
        candidate = store_meta.get(key)
        if isinstance(candidate, Mapping):
            status, reasons = classify_preprocessing_record(
                candidate,
                lineage=identity,
            )
            if status != "current":
                code = (
                    LEGACY_PREPROCESSING_STALE_REASON
                    if status == "stale_legacy_unverified"
                    else "preprocessing_policy_stale"
                )
                raise PreprocessingContractError(
                    "The governed preprocessing policy is stale: "
                    + "; ".join(reasons or [status]),
                    code=code,
                )
            return validate_preprocessing_contract(candidate, identity)

    legacy_records = [
        store_meta.get("outlier_application"),
        store_meta.get("missing_application"),
        store_meta.get("missing_validation"),
    ]
    if any(isinstance(record, Mapping) and record for record in legacy_records):
        raise PreprocessingContractError(
            "Legacy preparation fit scope cannot be verified. Preserve the historical record, reconfirm the treatment recipe, and recompute preparation before training.",
            code=LEGACY_PREPROCESSING_STALE_REASON,
        )
    raise PreprocessingContractError(
        "An approved governed preprocessing recipe is required before training.",
        code="preprocessing_policy_required",
    )


def duplicate_exclusion_blocker(store_meta: Mapping[str, Any]) -> str | None:
    """Return a fail-closed reason for unresolved post-partition row deletion."""

    candidates: list[Mapping[str, Any]] = []
    for key in (
        "eda_completion_contract",
        "completion_contract",
        "duplicate_authority",
        "duplicate_disposition",
    ):
        value = store_meta.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    for candidate in candidates:
        authority = candidate.get("duplicate_authority")
        authority = authority if isinstance(authority, Mapping) else candidate
        disposition = _text(
            authority.get("disposition")
            or authority.get("decision")
            or authority.get("resolution_action")
        ).casefold()
        exclusion_requested = disposition in {
            "exclude",
            "exclude_duplicates",
            "exclude_duplicate_rows",
            "exclude_upstream_and_repartition",
        }
        materialized = bool(
            authority.get("materialized_upstream")
            or authority.get("new_analysis_partition_created")
        )
        if exclusion_requested and not materialized:
            return (
                "Duplicate exclusion changes governed population membership. "
                "Create an upstream population revision and a new Analysis "
                "Partition before split creation or training."
            )
    return None


class GovernedPreprocessor(BaseEstimator, TransformerMixin):
    """Sklearn-compatible recipe executor with inspectable fitted lineage."""

    def __init__(
        self,
        recipe: Mapping[str, Any],
        *,
        encode_and_scale: bool = True,
        fit_scope: str = FIT_SCOPE_FOLD_TRAINING,
        fit_population_id: str = "",
        actor: str = "backend_training_engine",
        application_scope: str = "cv_validation_fold",
        application_population_id: str = "unbound-validation-fold",
        application_population_rows: int = 0,
    ) -> None:
        # Keep constructor parameters unmodified for sklearn.clone.
        self.recipe = recipe
        self.encode_and_scale = encode_and_scale
        self.fit_scope = fit_scope
        self.fit_population_id = fit_population_id
        self.actor = actor
        self.application_scope = application_scope
        self.application_population_id = application_population_id
        self.application_population_rows = application_population_rows

    def fit(self, X: Any, y: Any = None):
        del y
        frame = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        self.recipe_ = validate_preprocessing_contract(self.recipe)
        self.feature_names_in_ = np.asarray(
            [str(column) for column in frame.columns], dtype=object
        )
        self.special_value_contract_ = deepcopy(
            self.recipe_.get("special_value_contract") or {}
        )
        population_id = str(self.fit_population_id or "").strip()
        if not population_id:
            population_id = "direct-training-population"
        lineage = {
            key: self.recipe_.get(key)
            for key in (
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "target_contract_id",
                "predictor_authorization_id",
                "analysis_partition_id",
                "analysis_partition_revision",
                "source_checksum",
                "special_value_review_id",
                "special_value_review_revision",
                "special_value_detection_fingerprint",
            )
        }
        fit = fit_metadata(
            fit_scope=str(self.fit_scope),
            population_id=population_id,
            population_count=int(len(frame)),
            lineage=lineage,
            fold_id=(
                population_id
                if str(self.fit_scope) == FIT_SCOPE_FOLD_TRAINING
                else None
            ),
            actor=str(self.actor),
            application_scope=str(self.application_scope),
            application_population_id=str(self.application_population_id),
            application_population_rows=int(self.application_population_rows),
            evidence_references=list(
                self.recipe_.get("evidence_references") or []
            ),
        )
        try:
            self.outlier_recipe_ = fit_outlier_recipe(
                frame,
                policy=self.recipe_["outlier_policy"],
                fit=fit,
                special_value_contract=self.special_value_contract_,
            )
            outlier_applied, self.outlier_fit_application_ = apply_outlier_recipe(
                frame,
                recipe=self.outlier_recipe_,
                special_value_contract=self.special_value_contract_,
            )
            self.missing_recipe_ = fit_missing_recipe(
                outlier_applied,
                policy=self.recipe_["missing_policy"],
                fit=fit,
                special_value_contract=self.special_value_contract_,
            )
            policy_frame, self.missing_fit_application_ = apply_missing_recipe(
                outlier_applied,
                recipe=self.missing_recipe_,
                special_value_contract=self.special_value_contract_,
            )
        except ValueError as exc:
            raise PreprocessingContractError(str(exc)) from exc
        remaining_nulls = int(policy_frame.isna().sum().sum())
        if remaining_nulls:
            raise PreprocessingContractError(
                f"{remaining_nulls} true-null predictor cell(s) remain after the approved preparation recipe."
            )
        self.numeric_columns_ = [
            str(column)
            for column in policy_frame.columns
            if pd.api.types.is_numeric_dtype(policy_frame[column])
        ]
        self.categorical_columns_ = [
            str(column)
            for column in policy_frame.columns
            if str(column) not in self.numeric_columns_
        ]
        self.encoder_ = None
        if self.encode_and_scale:
            if any(
                component is None
                for component in (
                    ColumnTransformer,
                    Pipeline,
                    OneHotEncoder,
                    StandardScaler,
                )
            ):
                raise ImportError(
                    "scikit-learn preprocessing components are required for training."
                )
            transformers: list[tuple[str, Any, list[str]]] = []
            if self.numeric_columns_:
                transformers.append(
                    (
                        "num",
                        Pipeline(steps=[("scaler", StandardScaler())]),
                        self.numeric_columns_,
                    )
                )
            if self.categorical_columns_:
                transformers.append(
                    (
                        "cat",
                        Pipeline(
                            steps=[
                                (
                                    "onehot",
                                    OneHotEncoder(
                                        handle_unknown="ignore",
                                        sparse_output=False,
                                        max_categories=50,
                                    ),
                                )
                            ]
                        ),
                        self.categorical_columns_,
                    )
                )
            if not transformers:
                raise PreprocessingContractError(
                    "No usable feature columns remain after governed preparation."
                )
            self.encoder_ = ColumnTransformer(
                transformers=transformers,
                remainder="drop",
            )
            self.encoder_.fit(policy_frame)

        self.fit_population_rows_ = int(len(frame))
        self.fit_excluded_true_null_cells_ = int(frame.isna().sum().sum())
        self.fit_excluded_special_value_cells_ = int(
            sum(
                int(
                    special_mask(
                        frame[column],
                        str(column),
                        self.special_value_contract_,
                    ).sum()
                )
                for column in frame.columns
            )
        )
        self.fitted_at_ = datetime.now(timezone.utc).isoformat()
        self.last_application_: dict[str, Any] = {}
        artifact_seed = self._artifact_seed()
        self.artifact_checksum_ = canonical_preprocessing_hash(artifact_seed)
        self.preprocessing_artifact_ = {
            **artifact_seed,
            "artifact_checksum": self.artifact_checksum_,
            "artifact_id": f"fitted-preprocessing-{self.artifact_checksum_[:20]}",
            "fitted_at": self.fitted_at_,
        }
        return self

    def _apply_policy(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
        try:
            outlier_applied, outlier_audit = apply_outlier_recipe(
                frame,
                recipe=self.outlier_recipe_,
                special_value_contract=self.special_value_contract_,
            )
            work, missing_audit = apply_missing_recipe(
                outlier_applied,
                recipe=self.missing_recipe_,
                special_value_contract=self.special_value_contract_,
            )
        except ValueError as exc:
            raise PreprocessingContractError(str(exc)) from exc
        for feature in getattr(self, "categorical_columns_", []):
            if feature in work.columns:
                work[feature] = work[feature].astype(str)
        return work, {
            "outlier": outlier_audit,
            "missing": missing_audit,
        }

    def transform(self, X: Any):
        if not hasattr(self, "artifact_checksum_"):
            raise PreprocessingContractError(
                "The governed preprocessing artifact must be fitted before application."
            )
        frame = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(
            X, columns=list(self.feature_names_in_)
        )
        expected = [str(value) for value in self.feature_names_in_]
        if [str(column) for column in frame.columns] != expected:
            raise PreprocessingContractError(
                "The preprocessing application columns do not match the fitted feature order."
            )
        before = frame.copy()
        policy_frame, application_audit = self._apply_policy(frame)
        if int(policy_frame.isna().sum().sum()):
            raise PreprocessingContractError(
                "True nulls remain during preprocessing application; no estimator was refitted."
            )
        changed_cells = 0
        for feature in frame.columns:
            left = before[feature]
            right = policy_frame[feature]
            equal = left.eq(right) | (left.isna() & right.isna())
            changed_cells += int((~equal).sum())
        self.last_application_ = {
            "application_population_rows": int(len(frame)),
            "changed_cell_count": changed_cells,
            "policy_application": application_audit,
            "final_holdout_parameter_influence": False,
            "refit_during_application": False,
        }
        if self.encoder_ is not None:
            return self.encoder_.transform(policy_frame)
        return policy_frame

    def _artifact_seed(self) -> dict[str, Any]:
        return {
            "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
            "preprocessing_policy_id": _text(
                self.recipe_.get("preprocessing_policy_id")
                or self.recipe_.get("policy_id")
            ),
            "preprocessing_policy_revision": int(
                self.recipe_.get("preprocessing_policy_revision")
                or self.recipe_.get("policy_revision")
                or 0
            ),
            "preprocessing_policy_hash": _text(
                self.recipe_.get("preprocessing_policy_hash")
                or self.recipe_.get("policy_checksum")
            ),
            "project_id": _text(self.recipe_.get("project_id")),
            "dataset_id": _text(self.recipe_.get("dataset_id")),
            "dataset_version_id": _text(self.recipe_.get("dataset_version_id")),
            "analysis_partition_id": _text(
                self.recipe_.get("analysis_partition_id")
            ),
            "analysis_partition_revision": int(
                self.recipe_.get("analysis_partition_revision") or 0
            ),
            "fit_scope": str(self.fit_scope),
            "fit_population_id": str(self.fit_population_id),
            "fit_population_count": int(self.fit_population_rows_),
            "fit_population_rows": int(self.fit_population_rows_),
            "fit_excluded_true_null_cells": int(
                self.fit_excluded_true_null_cells_
            ),
            "fit_excluded_special_value_cells": int(
                self.fit_excluded_special_value_cells_
            ),
            "outlier_fitted_recipe": deepcopy(self.outlier_recipe_),
            "missing_fitted_recipe": deepcopy(self.missing_recipe_),
            "encoding_scaling_parameters": self._encoding_scaling_parameters(),
            "encoding_scaling_fitted": bool(self.encoder_ is not None),
            "feature_names": [str(value) for value in self.feature_names_in_],
            "policy_scope": "governed_recipe",
            "application_scope": str(self.application_scope),
            "application_population_id": str(self.application_population_id),
            "application_population_rows": int(self.application_population_rows),
            "actor": str(self.actor),
            "upstream_evidence_references": list(
                self.recipe_.get("evidence_references") or []
            ),
            "downstream_model_training_references": [],
            "final_holdout_target_accessed": False,
            "final_holdout_predictors_included_in_structural_profile": False,
            "final_holdout_parameter_influence": False,
            "final_holdout_used_for_selection": False,
            "final_holdout_transformed_or_materialized_prelock": False,
            "final_holdout_opened_for_final_reporting": False,
            "validation_fold_parameter_influence": False,
        }

    def _encoding_scaling_parameters(self) -> dict[str, Any]:
        if self.encoder_ is None:
            return {"status": "not_requested"}
        payload: dict[str, Any] = {
            "status": "fitted_on_declared_fit_population",
            "numeric": {},
            "categorical": {},
        }
        numeric = getattr(self.encoder_, "named_transformers_", {}).get("num")
        scaler = (
            numeric.named_steps.get("scaler")
            if hasattr(numeric, "named_steps")
            else None
        )
        if scaler is not None:
            for position, feature in enumerate(self.numeric_columns_):
                payload["numeric"][feature] = {
                    "mean": _json_scalar(scaler.mean_[position]),
                    "scale": _json_scalar(scaler.scale_[position]),
                    "variance": _json_scalar(scaler.var_[position]),
                }
        categorical = getattr(self.encoder_, "named_transformers_", {}).get(
            "cat"
        )
        onehot = (
            categorical.named_steps.get("onehot")
            if hasattr(categorical, "named_steps")
            else None
        )
        if onehot is not None:
            for position, feature in enumerate(self.categorical_columns_):
                payload["categorical"][feature] = {
                    "categories": [
                        _json_scalar(value)
                        for value in onehot.categories_[position]
                    ]
                }
        return payload

    def fitted_artifact(
        self,
        *,
        application_scope: str,
        application_population_id: str,
        application_population_rows: int,
    ) -> dict[str, Any]:
        artifact = deepcopy(self.preprocessing_artifact_)
        artifact.update(
            {
                "application_scope": str(application_scope),
                "application_population_id": str(application_population_id),
                "application_population_rows": int(application_population_rows),
                "application": deepcopy(self.last_application_),
                "refit_during_application": False,
            }
        )
        return artifact


def extract_fitted_preprocessing_artifacts(estimator: Any) -> list[dict[str, Any]]:
    """Collect fitted recipe artifacts from pipelines/calibration wrappers."""

    found: list[dict[str, Any]] = []
    seen_objects: set[int] = set()

    def visit(value: Any) -> None:
        if value is None or id(value) in seen_objects:
            return
        seen_objects.add(id(value))
        artifact = getattr(value, "preprocessing_artifact_", None)
        if isinstance(artifact, Mapping):
            found.append(deepcopy(dict(artifact)))
        for name in ("preprocess_", "estimator", "estimator_", "base_estimator"):
            child = getattr(value, name, None)
            if child is not value:
                visit(child)
        named_steps = getattr(value, "named_steps", None)
        if isinstance(named_steps, Mapping):
            for child in named_steps.values():
                visit(child)
        for calibrated in getattr(value, "calibrated_classifiers_", []) or []:
            visit(getattr(calibrated, "estimator", None))

    visit(estimator)
    unique: dict[str, dict[str, Any]] = {}
    for artifact in found:
        checksum = _text(artifact.get("artifact_checksum"))
        if checksum:
            unique.setdefault(checksum, artifact)
    return list(unique.values())


def extract_final_preprocessing_artifact(estimator: Any) -> dict[str, Any]:
    """Return the one final Development-fitted artifact embedded in a model.

    Registry/scoring recovery must not infer a fit scope from an estimator's
    shape or from legacy preparation metadata.  The executable model itself is
    therefore required to carry one explicit, checksummed final artifact.
    """

    artifacts = [
        artifact
        for artifact in extract_fitted_preprocessing_artifacts(estimator)
        if _text(artifact.get("artifact_kind"))
        == "final_development_fitted_preprocessing"
    ]
    if len(artifacts) != 1:
        raise PreprocessingContractError(
            "The executable model does not contain exactly one final Development-fitted preprocessing artifact.",
            code="final_preprocessing_artifact_unverified",
        )
    return artifacts[0]


def validate_final_preprocessing_artifact(
    artifact: Mapping[str, Any],
    candidate_contract: Mapping[str, Any],
    *,
    candidate_decision_id: str | None = None,
) -> dict[str, Any]:
    """Validate exact final-fit lineage without normalizing missing fields."""

    if not isinstance(artifact, Mapping):
        raise PreprocessingContractError(
            "The final Development-fitted preprocessing artifact is unavailable.",
            code="final_preprocessing_artifact_unverified",
        )
    resolved = deepcopy(dict(artifact))
    if (
        int(resolved.get("preprocessing_contract_version") or 0)
        != PREPROCESSING_CONTRACT_VERSION
        or _text(resolved.get("artifact_kind"))
        != "final_development_fitted_preprocessing"
        or _text(resolved.get("fit_scope")) != FIT_SCOPE_FINAL_DEVELOPMENT
    ):
        raise PreprocessingContractError(
            "The executable model was not fitted under the final Development Population preprocessing contract.",
            code="final_preprocessing_fit_scope_unverified",
        )
    required_text = (
        "preprocessing_policy_id",
        "preprocessing_policy_hash",
        "fit_population_id",
        "candidate_decision_id",
        "candidate_id",
        "final_artifact_checksum",
    )
    missing = [field for field in required_text if not _text(resolved.get(field))]
    if missing:
        raise PreprocessingContractError(
            "The final preprocessing artifact is missing exact lineage: "
            + ", ".join(missing)
            + ".",
            code="final_preprocessing_artifact_unverified",
        )
    if int(resolved.get("fit_population_rows") or 0) <= 0:
        raise PreprocessingContractError(
            "The final preprocessing artifact has no positive Development fit row count.",
            code="final_preprocessing_artifact_unverified",
        )
    expected_fit_population_id = _text(
        candidate_contract.get("training_population_id")
        or candidate_contract.get("selection_partition_id")
    )
    if expected_fit_population_id and _text(
        resolved.get("fit_population_id")
    ) != expected_fit_population_id:
        raise PreprocessingContractError(
            "The final preprocessing artifact does not match the complete Development Population identity.",
            code="final_preprocessing_artifact_lineage_mismatch",
        )
    expected_fit_rows = int(
        candidate_contract.get("training_population_rows") or 0
    )
    if expected_fit_rows and int(
        resolved.get("fit_population_rows") or 0
    ) != expected_fit_rows:
        raise PreprocessingContractError(
            "The final preprocessing artifact does not match the complete Development Population row count.",
            code="final_preprocessing_artifact_lineage_mismatch",
        )
    exact_pairs = (
        ("project_id", "project_id"),
        ("dataset_id", "dataset_id"),
        ("dataset_version_id", "dataset_version_id"),
        ("analysis_partition_id", "analysis_partition_id"),
        ("candidate_id", "candidate_id"),
        ("preprocessing_policy_id", "preprocessing_policy_id"),
        ("preprocessing_policy_hash", "preprocessing_policy_hash"),
    )
    for artifact_field, contract_field in exact_pairs:
        expected = _text(candidate_contract.get(contract_field))
        actual = _text(resolved.get(artifact_field))
        if expected and actual != expected:
            raise PreprocessingContractError(
                f"The final preprocessing artifact does not match {contract_field}.",
                code="final_preprocessing_artifact_lineage_mismatch",
            )
    expected_revision = int(
        candidate_contract.get("analysis_partition_revision") or 0
    )
    if expected_revision and int(
        resolved.get("analysis_partition_revision") or 0
    ) != expected_revision:
        raise PreprocessingContractError(
            "The final preprocessing artifact does not match the Analysis Partition revision.",
            code="final_preprocessing_artifact_lineage_mismatch",
        )
    expected_policy_revision = int(
        candidate_contract.get("preprocessing_policy_revision") or 0
    )
    if expected_policy_revision and int(
        resolved.get("preprocessing_policy_revision") or 0
    ) != expected_policy_revision:
        raise PreprocessingContractError(
            "The final preprocessing artifact does not match the preprocessing policy revision.",
            code="final_preprocessing_artifact_lineage_mismatch",
        )
    if candidate_decision_id and _text(
        resolved.get("candidate_decision_id")
    ) != _text(candidate_decision_id):
        raise PreprocessingContractError(
            "The final preprocessing artifact does not match the locked candidate decision.",
            code="final_preprocessing_artifact_lineage_mismatch",
        )
    expected_application_id = _text(
        candidate_contract.get("final_holdout_partition_id")
        or candidate_contract.get("holdout_population_id")
    )
    if expected_application_id and _text(
        resolved.get("application_population_id")
    ) != expected_application_id:
        raise PreprocessingContractError(
            "The final preprocessing artifact does not bind the exact sealed final-holdout population.",
            code="final_preprocessing_artifact_lineage_mismatch",
        )
    expected_application_rows = int(
        candidate_contract.get("final_holdout_population_rows") or 0
    )
    if expected_application_rows and int(
        resolved.get("application_population_rows") or 0
    ) != expected_application_rows:
        raise PreprocessingContractError(
            "The final preprocessing artifact does not bind the exact sealed final-holdout row count.",
            code="final_preprocessing_artifact_lineage_mismatch",
        )
    if any(
        bool(resolved.get(field))
        for field in (
            "final_holdout_parameter_influence",
            "final_holdout_used_for_selection",
            "final_holdout_transformed_or_materialized_prelock",
        )
    ):
        raise PreprocessingContractError(
            "The final preprocessing artifact records prohibited final-holdout influence or pre-lock materialization.",
            code="final_preprocessing_holdout_contamination",
        )
    if bool(resolved.get("refit_during_application")):
        raise PreprocessingContractError(
            "The final preprocessing artifact records a refit during application.",
            code="final_preprocessing_holdout_contamination",
        )
    expected_checksum = canonical_preprocessing_hash(
        {
            key: value
            for key, value in resolved.items()
            if key not in {"fitted_at", "final_artifact_checksum"}
        }
    )
    if _text(resolved.get("final_artifact_checksum")) != expected_checksum:
        raise PreprocessingContractError(
            "The final preprocessing artifact checksum does not match its immutable content.",
            code="final_preprocessing_artifact_checksum_mismatch",
        )
    return resolved

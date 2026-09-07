"""Exact project-bound Stage 3 Model Laboratory execution.

This module is deliberately separate from the retired ``sports_cockpit``
global-matrix execution path.  It resolves every scientific input through the
current project's immutable Stage 3 registrations, reads only the registered
development date range, fits preprocessing independently inside each
chronological training fold, and never exposes the final-OOT target.

No route in this module promotes or activates a model.  A completed run is an
immutable development-only comparison receipt stored outside Git under the
local runtime root.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import platform
import tempfile
import time
import uuid
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn import __version__ as sklearn_version
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import f1_score, log_loss, roc_auc_score
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier
from threadpoolctl import threadpool_limits

from ..persistence.db import Database, json_dumps, now_iso
from ..persistence.repositories.project_repository import ProjectRepository
from ..persistence.repositories.stage3_feature_set_repository import (
    Stage3FeatureSetRepository,
)
from ..persistence.repositories.stage3_split_contract_repository import (
    Stage3SplitContractRepository,
)
from ..persistence.repositories.stage3_treatment_repository import (
    Stage3TreatmentRepository,
)
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_gold.contracts import GOLD_CLASS_ORDER
from . import stage3_eda as eda
from . import stage3_player_prior_authority as player_prior
from . import stage3_player_prior_authority_v2 as player_prior_v2
from . import sufficient_stats
from .gold import CURRENT_GOLD_DATASET_ID
from .stage3_player_prior_artifact_store_v2 import load_artifact, load_current_bundle
from .stage3_model_catalog import catalog_public, model_catalog
from .stage3_model_eligibility import assess_feature_set, build_model_eligibility
from .stage3_prior_publication_v2 import runtime_prior_root


MODEL_LAB_SCHEMA_VERSION = "SPORTS_STAGE3_PROJECT_MODEL_LAB_V1"
RUN_RECEIPT_SCHEMA_VERSION = "SPORTS_STAGE3_MODEL_LAB_RUN_RECEIPT_V1"
RUN_RECEIPT_SCHEMA_VERSION_V2 = "SPORTS_STAGE3_MODEL_DEVELOPMENT_RUN_RECEIPT_V2"

EXPECTED_SOURCE_DATASET_ID = "asp.mlb.statcast.current-pa.v1"
EXPECTED_GOLD_MANIFEST_SHA = (
    "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758"
)
EXPECTED_DEVELOPMENT = ("2023-03-30", "2026-08-13", 683_662)
EXPECTED_FINAL_OOT = ("2026-08-14", "2026-08-27", 14_067)

EXPECTED_OUTLIER_POLICY = {
    "policyId": "stage3-outlier-policy-facf3b3cb90348e68fd349d14733d87a",
    "policyVersion": 2,
    "checksum": "89cf839e9780f796b0317222b555f255f26b3e2270c0590751123345782c2ab8",
}
EXPECTED_MISSING_POLICY = {
    "policyId": "stage3-imputation-policy-75a1080b57b14165b22ed348f11d6896",
    "policyVersion": 2,
    "checksum": "e6b4e187d24dc4c7960b3d76ffbf8b88df67d4a845a5810588259e1f097aee06",
}
EXPECTED_FEATURE_SET_IDS = (
    "stage3-feature-set-9e8ade8098814fc08d4bfd63e7c60a4f",
    "stage3-feature-set-f39a3891c2684d2b95361597a03c19de",
    "stage3-feature-set-d7f38d8b7bc640f7853c1beffb63f9f6",
)
EXPECTED_SPLIT = {
    "splitContractId": "stage3-split-contract-ae8cd433f1b44e528bb82e81ae68fd6b",
    "version": 2,
    "checksum": "488ac1a6a6a1d97c88829a251f7e0d9e48e1b561797e7c750d7d2576aa9b11ac",
}
EXPECTED_FOLDS = (
    (1, "2023-03-30", "2023-10-01", 182_072, 2_406, "2024-03-20", "2024-07-06", 99_782, 1_330),
    (2, "2023-03-30", "2024-07-06", 281_854, 3_736, "2024-07-07", "2025-04-15", 100_269, 1_338),
    (3, "2023-03-30", "2025-04-15", 382_123, 5_074, "2025-04-16", "2025-07-27", 99_968, 1_327),
    (4, "2023-03-30", "2025-07-27", 482_091, 6_401, "2025-07-28", "2026-05-01", 100_304, 1_327),
    (5, "2023-03-30", "2026-05-01", 582_395, 7_728, "2026-05-02", "2026-08-13", 101_267, 1_342),
)

DEFAULT_SEED = 2026_0831
RAW_PROBABILITY_ROW_SUM_RTOL = 0.0
RAW_PROBABILITY_ROW_SUM_ATOL = 1e-6
_ALLOWED_MODEL_FAMILIES = {
    "class_frequency_null",
    "multinomial_logistic",
    "histogram_gradient_boosting",
    "xgboost",
}


class Stage3ModelLaboratoryError(RuntimeError):
    """A project-bound Model Laboratory authority or execution failed closed."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class _UnknownCategoryMapper(BaseEstimator, TransformerMixin):
    """Map fold-unseen categorical values to the registered UNKNOWN level."""

    def __init__(self, categories: tuple[tuple[str, ...], ...]) -> None:
        self.categories = categories

    def fit(self, values: Any, labels: Any = None) -> "_UnknownCategoryMapper":
        array = np.asarray(values, dtype=object)
        if array.ndim != 2 or array.shape[1] != len(self.categories):
            raise ValueError("Categorical input does not match the registered contract.")
        self.n_features_in_ = int(array.shape[1])
        return self

    def transform(self, values: Any) -> np.ndarray:
        array = np.asarray(values, dtype=object).copy()
        if array.ndim != 2 or array.shape[1] != len(self.categories):
            raise ValueError("Categorical input does not match the registered contract.")
        for index, levels in enumerate(self.categories):
            allowed = set(levels)
            column = array[:, index]
            array[:, index] = [
                value if value in allowed else "UNKNOWN" for value in column
            ]
        return array

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        if input_features is None:
            return np.asarray(
                [f"x{index}" for index in range(len(self.categories))], dtype=object
            )
        return np.asarray(input_features, dtype=object)


class Stage3FittedPipeline:
    """Serialization-safe fitted Stage 3 preprocessing/model boundary.

    The wrapper deliberately owns the ordered source-feature and target-class
    contracts.  A caller cannot accidentally score a reordered, partial, or
    expanded frame, and estimator-native class ordering is reconciled before a
    probability matrix leaves the trusted artifact boundary.
    """

    def __init__(
        self,
        *,
        ordered_features: Sequence[str],
        target_order: Sequence[str],
        preprocessor: Any,
        estimator: Any,
    ) -> None:
        self.ordered_features = tuple(str(value) for value in ordered_features)
        self.target_order = tuple(str(value) for value in target_order)
        self.preprocessor = preprocessor
        self.estimator = estimator

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        if not isinstance(frame, pd.DataFrame):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_FEATURE_FRAME_REQUIRED",
                "Stage 3 artifact scoring requires a pandas DataFrame.",
            )
        columns = [str(value) for value in frame.columns]
        if columns != list(self.ordered_features) or len(columns) != len(set(columns)):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_FEATURE_ORDER_MISMATCH",
                "The scoring frame must contain exactly the artifact's ordered source features.",
                status_code=409,
            )
        if self.target_order != tuple(GOLD_CLASS_ORDER):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_TARGET_ORDER_MISMATCH",
                "The fitted artifact target order differs from the governed eight-class order.",
                status_code=409,
            )
        transformed = self.preprocessor.transform(frame)
        raw_probabilities = _aligned_probabilities(self.estimator, transformed)
        validated = _validate_probability_matrix(
            raw_probabilities, expected_rows=len(frame)
        )
        return _normalize_executable_probabilities(validated)


@dataclass(frozen=True)
class ModelLabAuthority:
    eda_authority: Any
    project_name: str
    outlier_policy: Mapping[str, Any]
    missing_policy: Mapping[str, Any]
    feature_sets: tuple[Mapping[str, Any], ...]
    split: Mapping[str, Any]
    treatment_specification: Mapping[str, Any] | None = None
    governed_prior_runtime: Mapping[str, Any] | None = None

    @property
    def project_id(self) -> str:
        """Expose the canonical project identity used by queued-job checks.

        The project id is owned by the resolved EDA authority.  Keeping this
        compatibility property on the aggregate authority prevents background
        workers from depending on the EDA object's internal nesting while still
        retaining one source of truth for project identity.
        """

        return str(self.eda_authority.project_id)

    @property
    def authority_key(self) -> str:
        authority = self.eda_authority
        return ":".join(
            (
                str(authority.source_manifest_sha),
                str(authority.gold_manifest_sha),
                str(authority.contextual_manifest_sha),
                str(authority.review_digest),
            )
        )


def _runtime_root() -> Path:
    configured = os.getenv("ATLAS_STAGE3_MODEL_LAB_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[2]
    return repository_root / ".runtime" / "asp-model-studio" / "stage3-model-laboratory"


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _policy_by_exact_identity(
    database: Database,
    authority: Any,
    *,
    kind: str,
    expected: Mapping[str, Any],
) -> Mapping[str, Any]:
    rows = Stage3TreatmentRepository(database).list_versions(
        authority.project_id, kind, authority.review_digest
    )
    policy = next(
        (row for row in rows if row.get("policyId") == expected["policyId"]),
        None,
    )
    if policy is None:
        raise Stage3ModelLaboratoryError(
            f"{kind}_POLICY_MISSING",
            f"The exact adopted {kind.lower()} policy is unavailable.",
            status_code=409,
        )
    if (
        policy.get("status") != "ADOPTED"
        or int(policy.get("policyVersion") or 0) != int(expected["policyVersion"])
        or policy.get("checksum") != expected["checksum"]
        or policy.get("projectId") != authority.project_id
        or policy.get("goldManifestSha") != authority.gold_manifest_sha
        or policy.get("authorityReviewDigest") != authority.review_digest
        or int((policy.get("development") or {}).get("rows") or 0) <= 0
        or (policy.get("finalOot") or {}).get("locked") is not True
    ):
        raise Stage3ModelLaboratoryError(
            f"{kind}_POLICY_AUTHORITY_MISMATCH",
            f"The exact {kind.lower()} policy does not match the current project/Gold authority.",
            status_code=409,
        )
    fitting = policy.get("fittingRule") or {}
    if (
        fitting.get("fitScope")
        != "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY"
        or fitting.get("validationTransform")
        != "PARAMETERS_FROM_CORRESPONDING_TRAINING_FOLD_ONLY"
        or fitting.get("finalOotParameterFittingProhibited") is not True
        or fitting.get("targetOutcomeInputsProhibited") is not True
    ):
        raise Stage3ModelLaboratoryError(
            f"{kind}_POLICY_FOLD_LOCAL_RULE_MISSING",
            f"The exact {kind.lower()} policy lacks the required fold-local fitting rule.",
            status_code=409,
        )
    return policy


def _feature_sets_by_exact_identity(
    database: Database, authority: Any, split: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    rows = Stage3FeatureSetRepository(database).list_versions(authority.project_id, authority.review_digest)
    by_id = {str(row.get("featureSetId")): row for row in rows}
    ids = list(split.get("selectedFeatureSetIds") or [])
    bindings = {str(item.get("featureSetId")): item.get("checksum")
                for item in (split.get("contract") or {}).get("selectedFeatureSets") or []}
    if not ids or len(ids) != len(set(ids)):
        raise Stage3ModelLaboratoryError("MODEL_LAB_FEATURE_SET_MISSING", "The registered split has no exact project feature bindings.", status_code=409)
    output = []
    for feature_set_id in ids:
        item = by_id.get(feature_set_id)
        if item is None:
            raise Stage3ModelLaboratoryError("MODEL_LAB_FEATURE_SET_MISSING", "A split-bound registered project feature set is unavailable.", status_code=409)
        ordered = list(item.get("orderedFeatures") or [])
        if (item.get("status") != "REGISTERED" or item.get("projectId") != authority.project_id
            or (item.get("authority") or {}).get("goldManifestSha") != authority.gold_manifest_sha
            or (item.get("authority") or {}).get("reviewDigest") != authority.review_digest
            or bindings.get(feature_set_id) != item.get("checksum")
            or (item.get("finalOot") or {}).get("locked") is not True
            or item.get("development") != split.get("development")
            or not ordered or len(ordered) != len(set(ordered))
            or set(ordered) - set(authority.schema.names) or item.get("unavailableExclusions")):
            raise Stage3ModelLaboratoryError("MODEL_LAB_FEATURE_SET_AUTHORITY_MISMATCH", "A feature registration differs from its exact project/split/Gold binding.", status_code=409)
        _transformation_groups(item, ordered)
        output.append(item)
    return tuple(output)


def _fold_signature(fold: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(fold.get("foldNumber") or 0),
        str(fold.get("trainStart") or ""),
        str(fold.get("trainEnd") or ""),
        int(fold.get("trainRows") or 0),
        int(fold.get("trainGames") or 0),
        str(fold.get("validationStart") or ""),
        str(fold.get("validationEnd") or ""),
        int(fold.get("validationRows") or 0),
        int(fold.get("validationGames") or 0),
    )


def _split_by_exact_identity(database: Database, authority: Any) -> Mapping[str, Any]:
    rows = Stage3SplitContractRepository(database).list_versions(authority.project_id, authority.review_digest)
    registered = [row for row in rows if row.get("status") == "REGISTERED"]
    if not registered:
        raise Stage3ModelLaboratoryError("MODEL_LAB_SPLIT_MISSING", "Register a project-bound split before model execution.", status_code=409)
    registered.sort(key=lambda row: int(row.get("contractVersion") or 0), reverse=True)
    split = registered[0]
    if len(registered) > 1 and registered[1].get("contractVersion") == split.get("contractVersion"):
        raise Stage3ModelLaboratoryError("MODEL_LAB_SPLIT_AUTHORITY_MISMATCH", "The project has ambiguous current split authority.", status_code=409)
    contract = split.get("contract") or {}
    folds = list(contract.get("folds") or [])
    development = split.get("development") or {}
    oot = split.get("finalOot") or {}
    blocked = [gate for gate in contract.get("qualityGates") or [] if gate.get("blocking") is True and gate.get("status") != "PASS"]
    valid_folds = bool(folds) and all(
        str(development.get("startDate") or "") <= str(fold.get("trainStart") or "")
        <= str(fold.get("trainEnd") or "") < str(fold.get("validationStart") or "")
        <= str(fold.get("validationEnd") or "") <= str(development.get("endDate") or "")
        and int(fold.get("trainRows") or 0) > 0 and int(fold.get("validationRows") or 0) > 0
        and int(fold.get("foldNumber") or 0) == index
        for index, fold in enumerate(folds, 1))
    if (split.get("projectId") != authority.project_id
        or split.get("goldManifestSha") != authority.gold_manifest_sha
        or split.get("authorityReviewDigest") != authority.review_digest
        or oot.get("locked") is not True or not oot.get("startDate")
        or str(development.get("endDate") or "") >= str(oot.get("startDate"))
        or int(split.get("foldCount") or 0) != len(folds) or not valid_folds
        or contract.get("preprocessingScope") != "FIT_INSIDE_EACH_TRAINING_FOLD_ONLY"
        or contract.get("allBlockingGatesPass") is not True or blocked):
        raise Stage3ModelLaboratoryError("MODEL_LAB_SPLIT_AUTHORITY_MISMATCH", "The registered split does not authenticate this project's chronological development-only contract.", status_code=409)
    return split


def resolve_model_lab_authority(database: Database, project_id: str) -> ModelLabAuthority:
    if not isinstance(project_id, str) or not project_id.strip():
        raise Stage3ModelLaboratoryError("MODEL_LAB_PROJECT_REQUIRED", "Select an authorized project.", status_code=409)
    authority = eda._resolve_authority(database, project_id)
    if authority.project_id != project_id:
        raise Stage3ModelLaboratoryError("MODEL_LAB_PROJECT_GOLD_AUTHORITY_MISMATCH", "The dataset authority belongs to another project.", status_code=409)
    project = ProjectRepository(database).get(project_id)
    if not project:
        raise Stage3ModelLaboratoryError("MODEL_LAB_PROJECT_MISSING", "The canonical project record is unavailable.", status_code=404)
    treatment_state = Stage3TreatmentRepository(database).combined_spec_state(
        project_id, authority.review_digest
    )
    if treatment_state.get("latestDraft"):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_TREATMENT_DRAFT_PENDING",
            "Adopt or explicitly resolve the current combined treatment specification before model execution.",
            status_code=409,
        )
    combined = treatment_state.get("adopted")
    manifest = (combined or {}).get("manifest") or {}
    if (
        not combined
        or combined.get("status") != "ADOPTED"
        or combined.get("projectId") != project_id
        or combined.get("goldManifestSha") != authority.gold_manifest_sha
        or combined.get("authorityReviewDigest") != authority.review_digest
        or _sha(manifest) != combined.get("manifestChecksum")
        or (combined.get("finalOot") or {}).get("locked") is not True
        or (manifest.get("coreChallengerDecision") or {}).get("disposition")
        != "DEFERRED_CONTEXT_AUTHORITY"
    ):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_TREATMENT_AUTHORITY_MISMATCH",
            "The adopted Core Challenger treatment authority is absent or stale.",
            status_code=409,
        )
    split = _split_by_exact_identity(database, authority)
    features = _feature_sets_by_exact_identity(database, authority, split)
    refs = features[0].get("treatmentPolicies") or {}
    for item in features:
        if item.get("treatmentPolicies") != refs:
            raise Stage3ModelLaboratoryError("MODEL_LAB_POLICY_AUTHORITY_MISMATCH", "The split's feature sets bind different treatment authorities.", status_code=409)
    if not refs.get("outlier") or not refs.get("missing"):
        raise Stage3ModelLaboratoryError("MODEL_LAB_TREATMENT_MISSING", "Exact adopted treatment policy references are required.", status_code=409)
    outlier = _policy_by_exact_identity(database, authority, kind="OUTLIER", expected=refs["outlier"])
    missing = _policy_by_exact_identity(database, authority, kind="IMPUTATION", expected=refs["missing"])
    combined_refs = combined.get("linkedPolicies") or {}
    if any(
        (combined_refs.get(kind) or {}).get("policyId") != policy.get("policyId")
        or (combined_refs.get(kind) or {}).get("checksum") != policy.get("checksum")
        for kind, policy in (("outlier", outlier), ("missing", missing))
    ):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_COMBINED_TREATMENT_BINDING_MISMATCH",
            "The feature set policies do not match the adopted combined treatment receipt.",
            status_code=409,
        )
    prior_manifest = manifest.get("priorAuthority") or {}
    treatment_source = prior_manifest.get("treatmentSpecificationSource") or {}
    registered_statistics = sufficient_stats.registered_sufficient_statistics_authority(
        database,
        expected_gold_manifest_sha256=authority.gold_manifest_sha,
        output_root=eda._gold_root(),
    )
    v1_authority = player_prior.project_authority_manifest(
        authority,
        treatment_specification_key=str(treatment_source.get("key") or ""),
        treatment_source_sha256=str(
            treatment_source.get("sourceContentSha256") or ""
        ),
        sufficient_statistics_authority=registered_statistics,
    )
    if (
        v1_authority.get("authorityId") != prior_manifest.get("wave1AuthorityId")
        or v1_authority.get("authorityChecksum")
        != prior_manifest.get("wave1AuthorityChecksum")
    ):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_WAVE1_PRIOR_AUTHORITY_MISMATCH",
            "The adopted treatment no longer authenticates the executable Wave 1 prior engine.",
            status_code=409,
        )
    v2_root = runtime_prior_root()
    v2_bundle = load_current_bundle(project_id, root=v2_root)
    if v2_bundle is None:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_WAVE2_PRIOR_BUNDLE_MISSING",
            "The adopted treatment requires a current content-addressed Wave 2 prior bundle.",
            status_code=409,
        )
    definition_ref = v2_bundle.get("definition") or {}
    v2_definition = load_artifact(
        str(definition_ref.get("artifactSha256") or ""), root=v2_root
    )
    v2_bundle = player_prior_v2._validate_bundle(
        v2_bundle, expected_definition=v2_definition, root=v2_root
    )
    if (
        v2_bundle.get("authorityId") != prior_manifest.get("authorityId")
        or v2_bundle.get("authorityChecksum") != prior_manifest.get("authorityChecksum")
    ):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_WAVE2_PRIOR_AUTHORITY_MISMATCH",
            "The adopted treatment and the current Wave 2 prior fit bundle differ.",
            status_code=409,
        )
    companion = player_prior_v2.authenticate_companion(database, authority)
    fitted_v2: dict[int, Mapping[str, Any]] = {}
    for fold_number, reference in enumerate(v2_bundle.get("foldAuthorities") or [], 1):
        fitted_v2[fold_number] = load_artifact(
            str(reference.get("artifactSha256") or ""), root=v2_root
        )
    prior_bindings = {
        str(item.get("feature") or ""): dict(item)
        for item in prior_manifest.get("bindings") or []
        if item.get("feature")
    }
    prior_runtime = {
        "v1Authority": v1_authority,
        "v1Features": tuple(v1_authority.get("featureSets", {}).get("executable") or ()),
        "v2Features": tuple(player_prior_v2.WAVE2_FEATURES),
        "v2Bundle": v2_bundle,
        "v2FittedByFold": fitted_v2,
        "v2DevelopmentPaths": tuple(
            str(path) for path in companion.get("_developmentPaths") or ()
        ),
        "bindings": prior_bindings,
        "companionAuthenticationChecksum": companion.get("authenticationChecksum"),
    }
    return ModelLabAuthority(eda_authority=authority, project_name=str(project.get("project_name") or project_id),
        outlier_policy=outlier, missing_policy=missing, feature_sets=features, split=split,
        treatment_specification=combined, governed_prior_runtime=prior_runtime)


def _model_families() -> list[dict[str, Any]]:
    xgboost_available = importlib.util.find_spec("xgboost") is not None
    return [
        {
            "id": "class_frequency_null",
            "label": "Class-frequency null",
            "available": True,
            "status": "AVAILABLE",
            "hyperparameters": {},
        },
        {
            "id": "multinomial_logistic",
            "label": "Regularized multinomial logistic regression",
            "available": True,
            "status": "AVAILABLE",
            "hyperparameters": {"C": 1.0, "maxIter": 300, "solver": "lbfgs"},
        },
        {
            "id": "histogram_gradient_boosting",
            "label": "Histogram Gradient Boosting",
            "available": True,
            "status": "AVAILABLE",
            "hyperparameters": {
                "learningRate": 0.07,
                "maxIter": 150,
                "maxLeafNodes": 31,
                "l2Regularization": 1.0,
                "earlyStopping": False,
            },
        },
        {
            "id": "xgboost",
            "label": "XGBoost",
            "available": xgboost_available,
            "status": "AVAILABLE" if xgboost_available else "NOT_INSTALLED",
            "hyperparameters": {
                "nEstimators": 200,
                "maxDepth": 6,
                "learningRate": 0.05,
                "subsample": 0.9,
                "columnSample": 0.9,
                "nJobs": 1,
            }
            if xgboost_available
            else {},
        },
    ]


def _fixed_hyperparameters(model_family: str) -> dict[str, Any]:
    family = next((item for item in model_catalog() if item["id"] == model_family), None)
    return dict((family or {}).get("fixedHyperparameters") or {})


def _policy_ref(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "policyId": policy.get("policyId"),
        "version": int(policy.get("policyVersion") or 0),
        "checksum": policy.get("checksum"),
        "status": policy.get("status"),
        "fitScope": (policy.get("fittingRule") or {}).get("fitScope"),
    }


def _feature_ref(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "featureSetId": item.get("featureSetId"),
        "key": item.get("featureSetKey"),
        "name": item.get("name"),
        "version": int(item.get("version") or 0),
        "featureCount": len(item.get("orderedFeatures") or []),
        "orderedFeatures": list(item.get("orderedFeatures") or []),
        "status": item.get("status"),
        "checksum": item.get("checksum"),
        "unavailableExclusions": list(item.get("unavailableExclusions") or []),
        "simulationGeneratedStateFeatures": [
            name
            for name in item.get("orderedFeatures") or []
            if name
            in {
                "context_inning",
                "context_top_bottom",
                "context_outs_before",
                "context_base_mask_before",
                "context_batting_score_diff_before",
            }
        ],
    }


def _split_ref(split: Mapping[str, Any]) -> dict[str, Any]:
    contract = split.get("contract") or {}
    return {
        "splitContractId": split.get("contractId"),
        "version": int(split.get("contractVersion") or 0),
        "checksum": split.get("checksum"),
        "status": split.get("status"),
        "foldCount": int(split.get("foldCount") or 0),
        "folds": [
            {
                "foldNumber": fold.get("foldNumber"),
                "trainingStart": fold.get("trainStart"),
                "trainingEnd": fold.get("trainEnd"),
                "trainRows": fold.get("trainRows"),
                "trainGames": fold.get("trainGames"),
                "validationStart": fold.get("validationStart"),
                "validationEnd": fold.get("validationEnd"),
                "validationRows": fold.get("validationRows"),
                "validationGames": fold.get("validationGames"),
            }
            for fold in contract.get("folds") or []
        ],
        "preprocessingScope": contract.get("preprocessingScope"),
        "groupingUnit": contract.get("groupingUnit"),
        "dateAtomic": contract.get("dateAtomic") is True,
        "randomSplit": False,
    }


def _candidate_matrix(
    feature_sets: Sequence[Mapping[str, Any]], families: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    available = {str(item["id"]): bool(item["available"]) for item in families}
    output = [
        {
            "candidateKey": "class_frequency_null:NOT_APPLICABLE",
            "modelFamily": "class_frequency_null",
            "featureSetId": None,
            "featureSetName": "Feature-independent null reference",
            "status": "READY",
        }
    ]
    for family in (
        "multinomial_logistic",
        "histogram_gradient_boosting",
        "xgboost",
    ):
        for feature_set in feature_sets:
            feature_executable = feature_set.get("executable", True) is True
            output.append(
                {
                    "candidateKey": f"{family}:{feature_set['featureSetId']}",
                    "modelFamily": family,
                    "featureSetId": feature_set["featureSetId"],
                    "featureSetName": feature_set["name"],
                    "status": (
                        "NOT_INSTALLED"
                        if not available.get(family)
                        else "READY"
                        if feature_executable
                        else str(feature_set.get("executionStatus") or "NON_EXECUTABLE")
                    ),
                }
            )
    return output




def require_model_execution_authority(database: Database, resolved: ModelLabAuthority, actor_user_id: str | None) -> None:
    """Recheck live user permission and draft holds at the execution boundary."""
    from ..security.security_store import get_user
    from ..persistence.service import PersistenceService
    from ..sharing.sharing_service import SharingService
    user = get_user(str(actor_user_id or "")) if actor_user_id else None
    if (not user or user.get("status") != "active"
        or not SharingService(PersistenceService(database)).check_permission(user, "project", resolved.project_id, "edit").get("allowed")):
        raise Stage3ModelLaboratoryError("MODEL_EXECUTION_AUTHORIZATION_REVOKED", "The originating user no longer has authority to execute this project.", status_code=403)
    state = Stage3TreatmentRepository(database).combined_spec_state(resolved.project_id, resolved.eda_authority.review_digest)
    if state.get("latestDraft"):
        raise Stage3ModelLaboratoryError("MODEL_LAB_TREATMENT_DRAFT_PENDING", "The project's treatment specification is DRAFT; execution is blocked pending governed adoption.", status_code=409)


def _missing_project_workflow_state(database: Database, project_id: str, reason: str) -> dict[str, Any]:
    """Describe missing authority without inventing population or reading data partitions."""
    project = ProjectRepository(database).get(project_id)
    if not project:
        raise Stage3ModelLaboratoryError("MODEL_LAB_PROJECT_MISSING", "The canonical project record is unavailable.", status_code=404)
    return {"ok": True, "workflowBlocked": True,
        "authority": {"projectId": project_id, "projectName": project.get("project_name") or project_id,
            "authorityKey": None, "status": "PREREQUISITES_MISSING", "legacyGlobalMatrixUsed": False},
        "population": {"scope": "NOT_AUTHENTICATED", "developmentRows": None, "finalOotRows": None,
            "finalOotLocked": True, "finalOotTargetsMaterialized": False},
        "readiness": {"ready": False, "status": "PROJECT_PREREQUISITES_BLOCKED", "blockers": [reason]},
        "treatment": {"status": "NOT_AUTHENTICATED", "canAdopt": False, "adoptionPerformed": False},
        "candidateEvidence": {"status": "PREREQUISITES_BLOCKED", "foreignEvidenceUsed": False},
        "audit": {"legacyGlobalMatrixUsed": False, "base22FallbackAvailable": False, "globalMatrixFallbackAvailable": False,
            "finalOotTargetAccessed": False, "finalOotUsedForSelection": False, "providerCalls": 0,
            "autoPromotion": False, "goldPartitionsOpened": 0}}


def _authenticate_stored_project_registration(connection: Any, row: Mapping[str, Any], project_id: str) -> None:
    from ..persistence.db import json_loads
    current = connection.execute("SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?", (project_id,)).fetchone()
    if current is None or current["activation_status"] != "active" or current["dataset_version_id"] != row["dataset_version_id"] or int(current["activation_revision"]) != int(row["activation_revision"]):
        raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_AUTHORITY_STALE", "The stored treatment receipt is stale for the selected project dataset.", status_code=409)
    link = connection.execute("SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?", (project_id, current["dataset_id"])).fetchone()
    if link is None or link["link_status"] != "active":
        raise Stage3ModelLaboratoryError("MODEL_LAB_DATASET_AUTHORITY_REVOKED", "The project dataset registration is no longer linked.", status_code=409)
    registration = connection.execute("SELECT * FROM sports_dataset_registrations WHERE registration_id = ? AND dataset_id = ? AND dataset_version_id = ? AND manifest_sha = ? AND validation_status = 'VALID'", (row["registration_id"], row["source_dataset_id"], row["dataset_version_id"], row["source_manifest_sha"])).fetchone()
    if registration is not None and json_loads(dict(registration).get("metadata_json"), {}).get("authorityState") == "HISTORICAL":
        raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_REGISTRATION_HISTORICAL", "The source registration is historical and cannot authorize current execution.", status_code=409)
    metadata = [json_loads(dict(item).get("metadata_json"), {}) for item in (current, link)]
    if (current["dataset_id"] != row["source_dataset_id"] or registration is None
        or any(item.get("registrationId") not in (None, "", row["registration_id"]) or item.get("manifestSha") not in (None, "", row["source_manifest_sha"]) for item in metadata)):
        raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_REGISTRATION_MISMATCH", "The immutable treatment receipt does not match the project's validated source registration.", status_code=409)
    if not any(item.get("registrationId") for item in metadata):
        registrations = connection.execute("SELECT registration_id FROM sports_dataset_registrations WHERE dataset_id = ? AND dataset_version_id = ? AND validation_status = 'VALID'", (row["source_dataset_id"], row["dataset_version_id"])).fetchall()
        if len(registrations) != 1:
            raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_REGISTRATION_AMBIGUOUS", "The legacy project selection does not identify one source registration.", status_code=409)


def _registered_project_workflow_state(database: Database, project_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Authenticate historical metadata and JSON receipts without resolving row data."""
    import re
    from ..persistence.db import decode_row
    from ..persistence.repositories import stage3_split_contract_repository as splits
    from ..persistence.repositories import stage3_feature_set_repository as features
    from ..persistence.repositories import stage3_treatment_repository as policies
    split = splits._public_contract(decode_row(row))
    shared = ("project_id", "registration_id", "dataset_version_id", "activation_revision", "source_dataset_id",
        "source_manifest_sha", "gold_manifest_sha", "contextual_manifest_sha", "authority_review_digest",
        "development_start_date", "development_end_date", "development_rows", "final_oot_start_date", "final_oot_end_date", "final_oot_rows")
    registered_features = []
    adopted = {}
    with database.connection() as connection:
        _authenticate_stored_project_registration(connection, row, project_id)
        selected = split["selectedFeatureSetIds"]
        bindings = {item["featureSetId"]: item["checksum"] for item in split["contract"].get("selectedFeatureSets", [])}
        if not selected or len(set(selected)) != len(selected) or set(selected) != set(bindings):
            raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_FEATURE_BINDING_MISMATCH", "The historical split has no exact selected feature bindings.", status_code=409)
        for feature_id in selected:
            feature_row = connection.execute("SELECT * FROM stage3_feature_set_versions WHERE project_id = ? AND feature_set_id = ? AND feature_set_status = 'REGISTERED'", (project_id, feature_id)).fetchone()
            if feature_row is None or any(feature_row[key] != row[key] for key in shared):
                raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_FEATURE_BINDING_MISMATCH", "A historical selected feature set belongs to another authority.", status_code=409)
            feature = features._public_feature_set(decode_row(feature_row))
            identity = {key: feature[key] for key in ("projectId", "featureSetKey", "name", "orderedFeatures", "familyMemberships", "transformationContracts", "interactionContracts", "unavailableExclusions", "treatmentPolicies", "description", "notes")}
            identity["authorityReviewDigest"] = row["authority_review_digest"]
            if features._sha256(identity) != feature["checksum"] or feature["checksum"] != bindings[feature_id]:
                raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_FEATURE_CHECKSUM_MISMATCH", "A historical selected feature definition failed its content checksum.", status_code=409)
            for kind, ref in feature["treatmentPolicies"].items():
                policy_row = connection.execute("SELECT * FROM stage3_treatment_policy_versions WHERE project_id = ? AND treatment_policy_id = ? AND policy_status = 'ADOPTED'", (project_id, (ref or {}).get("policyId"))).fetchone()
                if policy_row is None or any(policy_row[key] != row[key] for key in shared):
                    raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_POLICY_BINDING_MISMATCH", "A historical adopted treatment belongs to another authority.", status_code=409)
                policy = policies._public_policy(decode_row(policy_row))
                checksum = Stage3TreatmentRepository(database)._draft_checksum(authority={"projectId": project_id, "reviewDigest": row["authority_review_digest"]}, policy_kind=policy["policyKind"], global_method=policy["globalMethod"], policy=policy["policy"], fitting_rule=policy["fittingRule"], notes=policy["notes"])
                if checksum != policy["checksum"] or any(policy.get(key) != ref.get(key) for key in ("policyId", "policyVersion", "checksum")) or (kind in adopted and adopted[kind]["policyId"] != policy["policyId"]):
                    raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_POLICY_CHECKSUM_MISMATCH", "A historical treatment policy failed its exact checksum binding.", status_code=409)
                adopted[kind] = policy
            registered_features.append({"featureSetId": feature_id, "name": feature["name"], "checksum": feature["checksum"], "featureCount": len(feature["orderedFeatures"])})
    contract = split["contract"]
    if contract.get("finalOot", {}).get("locked") is not True or contract.get("finalOot", {}).get("targetsAccessed") is not False:
        raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_OOT_BOUNDARY_MISMATCH", "The historical split does not preserve a sealed final-OOT boundary.", status_code=409)
    project = ProjectRepository(database).get(project_id)
    if not project: raise Stage3ModelLaboratoryError("MODEL_LAB_PROJECT_MISSING", "The canonical project record is unavailable.", status_code=404)
    authority = {"projectId": project_id, "projectName": project.get("project_name") or project_id,
        "registrationId": row["registration_id"], "datasetVersionId": row["dataset_version_id"], "activationRevision": row["activation_revision"],
        "sourceDatasetId": row["source_dataset_id"], "sourceManifestSha": row["source_manifest_sha"], "goldManifestSha": row["gold_manifest_sha"], "contextualManifestSha": row["contextual_manifest_sha"],
        "reviewDigest": row["authority_review_digest"], "authorityKey": ":".join(str(row[key]) for key in ("source_manifest_sha", "gold_manifest_sha", "contextual_manifest_sha", "authority_review_digest")),
        "splitContractId": split["contractId"], "splitVersion": split["contractVersion"], "splitChecksum": split["checksum"], "legacyGlobalMatrixUsed": False}
    receipt_identity = {key: authority[key] for key in ("projectId", "registrationId", "datasetVersionId", "authorityKey", "sourceDatasetId", "sourceManifestSha", "goldManifestSha", "contextualManifestSha", "splitContractId", "splitVersion", "splitChecksum")}
    for name, kind in (("outlier", "outlier"), ("missing", "missing")):
        receipt_identity.update({name+"PolicyId": adopted[kind]["policyId"], name+"PolicyVersion": adopted[kind]["policyVersion"], name+"PolicyChecksum": adopted[kind]["checksum"]})
    receipts = []
    for path in (_runtime_root() / "objects" / "sha256").glob("*.json"):
        if not re.fullmatch(r"[0-9a-f]{64}", path.stem) or path.stat().st_size > 64 * 1024 * 1024: continue
        try: data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        identity = data.get("identity") or {}
        if _sha(data) != path.stem or any(identity.get(key) != value for key, value in receipt_identity.items()): continue
        if data.get("schemaVersion") not in {RUN_RECEIPT_SCHEMA_VERSION, RUN_RECEIPT_SCHEMA_VERSION_V2}: continue
        population = data.get("population") or {}
        if (any(data.get(key, False) is not False for key in ("finalOotAccessed", "finalOotTargetsMaterialized", "autoPromoted"))
            or data.get("providerCalls") != 0 or data.get("legacyGlobalMatrixUsed") is not False
            or data.get("promotionStatus") != "NOT_PROMOTED" or identity.get("targetOrder") != list(GOLD_CLASS_ORDER)
            or population.get("finalOotLocked") is not True or population.get("finalOotTargetAccessed") is not False or population.get("finalOotScored") is not False): continue
        candidates = [{"candidateId": item.get("candidateId"), "modelFamily": item.get("modelFamily"), "featureSetId": item.get("featureSetId"), "status": item.get("status"), "meanOofLogLoss": item.get("meanOofLogLoss"), "foldsCompleted": item.get("foldsCompleted")} for item in data.get("candidates", []) if isinstance(item, Mapping)]
        receipts.append({"runId": data.get("runId"), "receiptSha256": path.stem, "schemaVersion": data.get("schemaVersion"), "createdAt": data.get("createdAt"), "candidates": candidates,
            "verificationScope": "CONTENT_HASH_AND_PROJECT_REGISTERED_AUTHORITY_ONLY", "rowDerivedFeatureUniverseRecomputed": False})
    return {"ok": True, "workflowBlocked": True, "metadataOnly": True, "authority": authority,
        "population": {"scope": "DEVELOPMENT_ONLY", "developmentRows": split["development"]["rows"], "finalOotRows": split["finalOot"]["rows"], "finalOotLocked": True, "finalOotTargetsMaterialized": False},
        "readiness": {"ready": False, "status": "HISTORICAL_EVIDENCE_READ_ONLY", "blockers": ["This view verifies historical receipt metadata. New execution requires a separately reviewed plan and current project authorization."]},
        "treatment": {"status": "ADOPTED_REGISTERED_HISTORY", "canAdopt": False, "adoptionPerformed": False},
        "historicalEvidence": {"status": "AUTHENTICATED_METADATA", "split": {"contractId": split["contractId"], "checksum": split["checksum"], "version": split["contractVersion"], "foldCount": split["foldCount"]}, "featureSets": registered_features,
            "treatmentPolicies": {kind: {key: item[key] for key in ("policyId", "policyVersion", "checksum")} for kind, item in adopted.items()}, "runs": receipts,
            "limitation": "Historical receipt metrics are displayed from sealed JSON. Row-derived feature-universe compatibility and a new executable plan have not been recomputed by this read-only view."},
        "audit": {"legacyGlobalMatrixUsed": False, "base22FallbackAvailable": False, "globalMatrixFallbackAvailable": False, "finalOotTargetAccessed": False, "finalOotUsedForSelection": False, "providerCalls": 0, "autoPromotion": False, "goldPartitionsOpened": 0}}


def persisted_project_workflow_state(database: Database, project_id: str, *, include_registered_history: bool = False) -> dict[str, Any] | None:
    """Read a sealed DRAFT receipt before any Gold/Parquet resolution or model action."""
    if database is None:
        return None
    from ..persistence.db import json_loads
    from .stage3_prior_publication_v2 import runtime_prior_root
    from .stage3_player_prior_artifact_store_v2 import load_current_bundle, load_artifact
    from . import stage3_player_prior_authority_v2 as prior_science
    import sqlite3
    with database.connection() as connection:
        try:
            row = connection.execute("SELECT * FROM stage3_feature_treatment_spec_versions WHERE project_id = ? ORDER BY specification_version DESC, created_at DESC LIMIT 1", (project_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower(): return None
            raise
        if row is None:
            registered = connection.execute("SELECT * FROM stage3_split_contract_versions WHERE project_id = ? AND contract_status = 'REGISTERED' ORDER BY contract_version DESC, created_at DESC LIMIT 1", (project_id,)).fetchone()
            if registered is None:
                return _missing_project_workflow_state(database, project_id, "Register this project's governed treatment, feature-set, and chronological split authorities before model development.")
            return _registered_project_workflow_state(database, project_id, dict(registered)) if include_registered_history else None
        if row["specification_status"] != "DRAFT": return None
        row = dict(row)
        _authenticate_stored_project_registration(connection, row, project_id)
    project = ProjectRepository(database).get(project_id)
    manifest = json_loads(row.get("manifest_json"), {})
    identity = manifest.get("projectAuthority") or {}
    expected = {"projectId": project_id, "registrationId": row["registration_id"],
        "datasetVersionId": row["dataset_version_id"], "activationRevision": int(row["activation_revision"]),
        "sourceDatasetId": row["source_dataset_id"], "sourceManifestSha": row["source_manifest_sha"],
        "goldManifestSha": row["gold_manifest_sha"], "contextualManifestSha": row["contextual_manifest_sha"],
        "reviewDigest": row["authority_review_digest"]}
    development = {"startDate": row["development_start_date"], "endDate": row["development_end_date"], "rows": int(row["development_rows"])}
    oot = {"startDate": row["final_oot_start_date"], "endDate": row["final_oot_end_date"], "rows": int(row["final_oot_rows"]), "locked": True, "targetsAccessed": False}
    if not project or _sha(manifest) != row["manifest_sha256"] or any(identity.get(k) != v for k, v in expected.items()) or manifest.get("developmentBoundary") != development or manifest.get("finalOotIdentity") != oot:
        raise Stage3ModelLaboratoryError("MODEL_LAB_STORED_AUTHORITY_MISMATCH", "The immutable project treatment metadata does not authenticate.", status_code=409)
    prior_root = runtime_prior_root()
    bundle = load_current_bundle(project_id, root=prior_root)
    wave2 = None
    if bundle is not None:
        definition = load_artifact(bundle["definition"]["artifactSha256"], root=prior_root)
        definition_project = definition.get("projectAuthority") or {}
        if not definition_project or any(identity.get(k) != v for k, v in definition_project.items()):
            raise Stage3ModelLaboratoryError("MODEL_LAB_PRIOR_PROJECT_MISMATCH", "The fitted prior belongs to another project authority.", status_code=409)
        verified = prior_science._validate_bundle(bundle, expected_definition=definition, root=prior_root)
        wave2 = {"authorityId": verified["authorityId"], "authorityChecksum": verified["authorityChecksum"],
            "foldAuthorities": [{k: item.get(k) for k in ("foldNumber", "fittedId", "fittedChecksum")} for item in verified["foldAuthorities"]],
            "finalDevelopmentAuthority": {k: verified["finalDevelopmentAuthority"].get(k) for k in ("fittedId", "fittedChecksum")}}
    blockers = ["The project's treatment specification is DRAFT; execution remains blocked pending governed adoption."]
    blockers += list(dict.fromkeys(str(item.get("detail")) for item in manifest.get("exceptions", []) if item.get("disposition") == "BLOCKING"))
    return {"ok": True, "workflowBlocked": True,
        "authority": {**identity, "projectName": project.get("project_name") or project_id, "legacyGlobalMatrixUsed": False},
        "population": {"scope": "DEVELOPMENT_ONLY", "developmentRows": development["rows"], "startDate": development["startDate"], "endDate": development["endDate"], "finalOotRows": oot["rows"], "finalOotStartDate": oot["startDate"], "finalOotEndDate": oot["endDate"], "finalOotLocked": True, "finalOotTargetsMaterialized": False},
        "readiness": {"ready": False, "status": "PROJECT_PREREQUISITES_BLOCKED", "blockers": blockers},
        "treatment": {"status": "DRAFT", "canAdopt": False, "adoptionPerformed": False},
        "priorAuthority": {"status": "AUTHENTICATED" if wave2 else "CANONICAL_WAVE2_NOT_AVAILABLE", "wave2": wave2, "v1": {k: (manifest.get("priorAuthority") or {}).get(k) for k in ("authorityId", "authorityChecksum", "readyV1FeatureCount", "readyV2FeatureCount", "retiredFeatureCount", "blockedFeatureCount")}, "featureCounts": {display: (manifest.get("priorAuthority") or {}).get(source) for display, source in (("readyGovernedPriorV1", "readyV1FeatureCount"), ("readyGovernedPriorV2", "readyV2FeatureCount"), ("retiredByScientificDecision", "retiredFeatureCount"))}, "source": "IMMUTABLE_PROJECT_TREATMENT_RECEIPT_AND_CONTENT_ADDRESSED_PRIOR"},
        "modelCatalog": catalog_public(), "candidateEvidence": {"status": "PREREQUISITES_BLOCKED", "foreignEvidenceUsed": False},
        "audit": {"legacyGlobalMatrixUsed": False, "base22FallbackAvailable": False, "globalMatrixFallbackAvailable": False, "finalOotTargetAccessed": False, "finalOotUsedForSelection": False, "providerCalls": 0, "autoPromotion": False, "goldPartitionsOpened": 0}}


def project_workflow_blocked(database: Database, project_id: str, error: Stage3ModelLaboratoryError) -> dict[str, Any]:
    state = persisted_project_workflow_state(database, project_id)
    if state is not None: return state
    return _missing_project_workflow_state(database, project_id, str(error))


def project_read_view(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Only expected missing prerequisites become a blocked page, never tamper failures."""
    from functools import wraps
    @wraps(function)
    def read(database: Database, project_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        stored = persisted_project_workflow_state(database, project_id)
        if stored is not None: return stored
        try:
            return function(database, project_id, *args, **kwargs)
        except Stage3ModelLaboratoryError as exc:
            if exc.code not in {"MODEL_LAB_SPLIT_MISSING", "MODEL_LAB_FEATURE_SET_MISSING",
                "MODEL_LAB_TREATMENT_MISSING", "OUTLIER_POLICY_MISSING", "IMPUTATION_POLICY_MISSING",
                "CANDIDATE_FINALISTS_REQUIRED", "MODEL_REFINEMENT_FINALIST_REQUIRED",
                "STAGE3_RESEARCH_CHALLENGER_REQUIRED"}:
                raise
            return project_workflow_blocked(database, project_id, exc)
    return read


@project_read_view
def model_laboratory_summary(database: Database, project_id: str) -> dict[str, Any]:
    resolved = resolve_model_lab_authority(database, project_id)
    authority = resolved.eda_authority
    eligibility = build_model_eligibility(resolved)
    combined_treatment = resolved.treatment_specification or {}
    treatment_manifest = combined_treatment.get("manifest") or {}
    core_decision = treatment_manifest.get("coreChallengerDecision") or {}
    prior_manifest = treatment_manifest.get("priorAuthority") or {}
    prior_bindings = list(prior_manifest.get("bindings") or [])
    feature_sets = []
    for item in resolved.feature_sets:
        feature_sets.append(
            {
                **_feature_ref(item),
                **assess_feature_set(item, eligibility),
                "workflowRole": "ABLATION_RESEARCH_PRESET",
            }
        )
    families = _model_families()
    historical_runs = _read_runs(project_id, resolved)
    return {
        "ok": True,
        "schemaVersion": MODEL_LAB_SCHEMA_VERSION,
        "authority": {
            "projectId": project_id,
            "projectName": resolved.project_name,
            "registrationId": authority.registration_id,
            "datasetVersionId": authority.dataset_version_id,
            "sourceDatasetId": authority.source_dataset_id,
            "sourceManifestSha": authority.source_manifest_sha,
            "goldDatasetId": CURRENT_GOLD_DATASET_ID,
            "goldManifestSha": authority.gold_manifest_sha,
            "contextualDatasetId": authority.public().get("contextualDatasetId"),
            "contextualManifestSha": authority.contextual_manifest_sha,
            "authorityKey": resolved.authority_key,
            "legacyGlobalMatrixUsed": False,
        },
        "population": {
            "scope": "DEVELOPMENT_ONLY",
            "developmentRows": int(resolved.split["development"]["rows"]),
            "startDate": str(resolved.split["development"]["startDate"]),
            "endDate": str(resolved.split["development"]["endDate"]),
            "finalOotRows": int(resolved.split["finalOot"]["rows"]),
            "finalOotStartDate": str(resolved.split["finalOot"]["startDate"]),
            "finalOotEndDate": str(resolved.split["finalOot"]["endDate"]),
            "finalOotLocked": True,
            "finalOotTargetsMaterialized": False,
        },
        "target": {
            "name": "outcome",
            "orderedClasses": list(GOLD_CLASS_ORDER),
            "primaryMetric": "MULTICLASS_LOG_LOSS",
        },
        "policies": {
            "outlier": _policy_ref(resolved.outlier_policy),
            "missing": _policy_ref(resolved.missing_policy),
            "draftOutlierPoliciesUsed": False,
        },
        "treatment": {
            "name": treatment_manifest.get("treatmentName") or "MLB Core Challenger",
            "specificationId": combined_treatment.get("specificationId"),
            "version": int(combined_treatment.get("specificationVersion") or 0),
            "checksum": combined_treatment.get("checksum"),
            "manifestChecksum": combined_treatment.get("manifestChecksum"),
            "status": combined_treatment.get("status") or "UNAVAILABLE",
            "predecessor": core_decision.get("predecessor") or {},
            "decisionId": core_decision.get("decisionId"),
            "decisionStatus": core_decision.get("decisionStatus"),
            "governedPriorFeatureCount": sum(
                1
                for item in prior_bindings
                if item.get("status")
                in {"READY_GOVERNED_PRIOR_V1", "READY_GOVERNED_PRIOR_V2"}
            ),
            "deferredContextFeatureCount": len(core_decision.get("deferredFeatures") or []),
            "deferredContextFeatures": list(core_decision.get("deferredFeatures") or []),
            "retiredFeatureCount": sum(
                1
                for item in prior_bindings
                if item.get("status")
                == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
            ),
            "includedFeatureCount": int(eligibility["featureCount"]),
            "finalOotLocked": True,
        },
        "split": _split_ref(resolved.split),
        "featureSets": feature_sets,
        "featureUniverse": eligibility,
        "featureUniverseChoices": [
            {
                "id": eligibility["featureSetId"],
                "key": "FULL_ELIGIBLE",
                "label": "Full Eligible Feature Set",
                "featureCount": eligibility["featureCount"],
                "status": "RECOMMENDED",
                "default": True,
                "executable": True,
            },
            {
                "id": resolved.feature_sets[0]["featureSetId"],
                "key": resolved.feature_sets[0].get("featureSetKey")
                or "MLB_CORE_CHALLENGER_V1",
                "label": resolved.feature_sets[0].get("name")
                or "MLB Core Challenger",
                "featureCount": len(resolved.feature_sets[0].get("orderedFeatures") or []),
                "status": "REGISTERED_CORE_CHALLENGER",
                "default": False,
                "executable": True,
            },
            {
                "id": "CUSTOM_SUBSET",
                "key": "CUSTOM_SUBSET",
                "label": "Custom eligible subset",
                "featureCount": None,
                "status": "SCIENTIST_DEFINED_DEVELOPMENT_ONLY",
                "default": False,
                "executable": True,
            },
            {
                "id": "SAVED_GOVERNED_FEATURE_SET",
                "key": "SAVED_GOVERNED_FEATURE_SET",
                "label": "Saved governed feature set",
                "featureCount": None,
                "status": "SELECT_FROM_PROJECT_REGISTRATIONS",
                "default": False,
                "executable": True,
            },
        ],
        "modelFamilies": families,
        "modelCatalog": catalog_public(),
        "candidateMatrix": _candidate_matrix(feature_sets, families),
        "readiness": {
            "ready": True,
            "blockers": [],
            "status": "READY_FOR_FIRST_CHALLENGER_COMPETITION",
        },
        "latestRun": _latest_run(project_id, resolved),
        "historicalEvidence": {
            "label": "INITIAL BASELINE / ABLATION EVIDENCE",
            "immutable": True,
            "runCount": len(historical_runs),
            "runs": historical_runs,
            "failedCandidatesRemainVisible": True,
        },
        "audit": {
            "legacyGlobalMatrixUsed": False,
            "base22FallbackAvailable": False,
            "globalMatrixFallbackAvailable": False,
            "finalOotTargetAccessed": False,
            "finalOotUsedForSelection": False,
            "providerCalls": 0,
            "autoPromotion": False,
        },
    }


def _validate_run_request(
    resolved: ModelLabAuthority, payload: Mapping[str, Any]
) -> tuple[list[dict[str, str]], int]:
    if payload.get("projectId", resolved.project_id) != resolved.project_id:
        raise Stage3ModelLaboratoryError("MODEL_LAB_PROJECT_IDENTITY_MISMATCH", "The payload project differs from the authorized project.", status_code=409)
    if str(payload.get("authorityKey") or "") != resolved.authority_key:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_AUTHORITY_STALE",
            "The run request does not match the exact current project/Gold authority.",
            status_code=409,
        )
    exact = {
        "splitContractId": resolved.split["contractId"],
        "outlierPolicyId": resolved.outlier_policy["policyId"],
        "missingPolicyId": resolved.missing_policy["policyId"],
    }
    for key, expected in exact.items():
        if str(payload.get(key) or "") != str(expected):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_RUN_IDENTITY_MISMATCH",
                f"The run request must bind exact {key}={expected}.",
                status_code=409,
            )
    seed = payload.get("seed", DEFAULT_SEED)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_SEED_INVALID", "Seed must be an unsigned 32-bit integer."
        )
    feature_by_id = {
        str(item.get("featureSetId")): item for item in resolved.feature_sets
    }
    eligibility = build_model_eligibility(resolved)
    model_families = _model_families()
    availability = {str(item["id"]): bool(item["available"]) for item in model_families}
    allowed_candidates = {
        (
            str(item["modelFamily"]),
            str(item.get("featureSetId") or ""),
        )
        for item in _candidate_matrix(
            [_feature_ref(feature_set) for feature_set in resolved.feature_sets],
            model_families,
        )
        if item["status"] == "READY"
    }
    raw = payload.get("candidates")
    if raw is None:
        requested: list[dict[str, str]] = [
            {
                "modelFamily": "class_frequency_null",
                "featureSetId": "",
            }
        ]
        for family in (
            "multinomial_logistic",
            "histogram_gradient_boosting",
            "xgboost",
        ):
            if availability[family]:
                requested.extend(
                    {"modelFamily": family, "featureSetId": feature_set_id}
                    for feature_set_id in (str(item["featureSetId"]) for item in resolved.feature_sets)
                )
    elif not isinstance(raw, list) or not raw:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_CANDIDATES_REQUIRED", "At least one candidate is required."
        )
    else:
        requested = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise Stage3ModelLaboratoryError(
                    "MODEL_LAB_CANDIDATE_INVALID", "Each candidate must be an object."
                )
            requested.append(
                {
                    "modelFamily": str(item.get("modelFamily") or ""),
                    "featureSetId": str(item.get("featureSetId") or ""),
                }
            )
    seen: set[tuple[str, str]] = set()
    raw_overrides = payload.get("eligibilityOverrides") or {}
    overrides = raw_overrides if isinstance(raw_overrides, Mapping) else {}
    for item in requested:
        family = item["modelFamily"]
        feature_set_id = item["featureSetId"]
        if family not in _ALLOWED_MODEL_FAMILIES:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_MODEL_FAMILY_UNSUPPORTED",
                f"Unsupported first-pass model family: {family}.",
            )
        if family == "class_frequency_null" and feature_set_id:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_NULL_FEATURE_SET_PROHIBITED",
                "The class-frequency null reference is feature-independent and must not bind a feature set.",
                status_code=409,
            )
        if family != "class_frequency_null" and feature_set_id not in feature_by_id:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_FEATURE_SET_IDENTITY_INVALID",
                f"Candidate references an unregistered feature set: {feature_set_id}.",
                status_code=409,
            )
        if not availability.get(family):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_MODEL_FAMILY_UNAVAILABLE",
                f"{family} is not installed in this environment; no dependency was added automatically.",
                status_code=409,
            )
        key = (family, feature_set_id)
        if key not in allowed_candidates:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_CANDIDATE_MATRIX_MISMATCH",
                f"Candidate tuple is outside the exact governed matrix: {family}/{feature_set_id or 'NOT_APPLICABLE'}.",
                status_code=409,
            )
        if key in seen:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_CANDIDATE_DUPLICATE", f"Duplicate candidate: {family}/{feature_set_id}."
            )
        seen.add(key)
        if family != "class_frequency_null":
            assessment = assess_feature_set(feature_by_id[feature_set_id], eligibility)
            if assessment["blockingFeatures"]:
                names = ", ".join(
                    str(feature["name"]) for feature in assessment["blockingFeatures"]
                )
                raise Stage3ModelLaboratoryError(
                    "MODEL_LAB_FEATURE_SET_NON_EXECUTABLE",
                    f"Feature set {feature_set_id} is preserved historical evidence but is not executable under the current source authority; blocking features: {names}.",
                    status_code=409,
                )
            if assessment["reviewRequiredFeatures"]:
                rationale = str(overrides.get(feature_set_id) or "").strip()
                if len(rationale) < 20:
                    names = ", ".join(
                        str(feature["name"])
                        for feature in assessment["reviewRequiredFeatures"]
                    )
                    raise Stage3ModelLaboratoryError(
                        "MODEL_LAB_FEATURE_SET_REVIEW_REQUIRED",
                        f"Feature set {feature_set_id} contains default-excluded semantic-sparse features ({names}); a written prospective-semantics rationale is required.",
                        status_code=409,
                    )
    return requested, int(seed)


def _date_mask(frame: pd.DataFrame, start: str, end: str) -> np.ndarray:
    dates = frame["game_date"].astype(str)
    return dates.between(start, end).to_numpy(dtype=bool)


def _fold_frame(
    resolved: ModelLabAuthority,
    features: Sequence[str],
    *,
    include_oof_identity: bool = False,
) -> pd.DataFrame:
    runtime = resolved.governed_prior_runtime or {}
    selected_v1 = sorted(set(features) & set(runtime.get("v1Features") or ()))
    selected_v2 = sorted(set(features) & set(runtime.get("v2Features") or ()))
    requested = [*features, "game_date", "outcome", "canonicalGameId"]
    if selected_v1:
        requested.extend(player_prior.required_input_columns(selected_v1))
    if selected_v2:
        requested.append("canonicalPaId")
    if include_oof_identity:
        requested.append("canonicalPaId")
    requested = list(dict.fromkeys(requested))
    frame = eda._scan(
        resolved.eda_authority,
        requested,
        {"startDate": str(resolved.split["development"]["startDate"]), "endDate": str(resolved.split["development"]["endDate"])},
    )
    if len(frame) != int(resolved.split["development"]["rows"]):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_DEVELOPMENT_ROW_MISMATCH",
            f"Expected {int(resolved.split["development"]["rows"]):,} development rows, found {len(frame):,}.",
            status_code=409,
        )
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if dates.isna().any() or dates.min().date().isoformat() != str(resolved.split["development"]["startDate"]) or dates.max().date().isoformat() != str(resolved.split["development"]["endDate"]):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_DEVELOPMENT_DATE_MISMATCH",
            "The scanned execution population differs from the registered development dates.",
            status_code=409,
        )
    outcomes = frame["outcome"].astype(str)
    invalid = sorted(set(outcomes.unique()) - set(GOLD_CLASS_ORDER))
    if invalid:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_TARGET_TAXONOMY_MISMATCH",
            "Development rows contain values outside the governed target order: " + ", ".join(invalid),
            status_code=409,
        )
    frame = frame.copy()
    frame["game_date"] = dates.dt.date.astype(str)
    if selected_v2:
        paths = [Path(value) for value in runtime.get("v2DevelopmentPaths") or ()]
        if not paths:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_WAVE2_COMPANION_MISSING",
                "The authenticated Wave 2 Development companion partitions are unavailable.",
                status_code=409,
            )
        required_v2 = list(player_prior_v2.required_input_columns(selected_v2))
        companion_columns = set(pq.ParquetFile(paths[0]).schema_arrow.names)
        companion_requested = [
            name for name in required_v2 if name in companion_columns
        ]
        companion = pa.concat_tables(
            [pq.read_table(path, columns=companion_requested) for path in paths]
        ).to_pandas(split_blocks=True)
        if (
            len(companion) != len(frame)
            or bool(companion["canonicalPaId"].duplicated().any())
            or set(companion["canonicalPaId"].astype(str))
            != set(frame["canonicalPaId"].astype(str))
        ):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_WAVE2_COMPANION_ROW_IDENTITY_MISMATCH",
                "Wave 2 Development sufficient statistics do not match the registered Development population one-to-one.",
                status_code=409,
            )
        overlap = [
            name
            for name in companion_requested
            if name != "canonicalPaId" and name in frame.columns
        ]
        by_key = companion.set_index("canonicalPaId", verify_integrity=True)
        aligned = by_key.reindex(frame["canonicalPaId"])
        if bool(aligned.index.isna().any()):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_WAVE2_COMPANION_ALIGNMENT_FAILED",
                "Wave 2 Development sufficient statistics could not be aligned by canonical PA identity.",
                status_code=409,
            )
        aligned.index = frame.index
        for name in overlap:
            left = frame[name].astype("string").fillna("<NULL>")
            right = aligned[name].astype("string").fillna("<NULL>")
            if not left.equals(right):
                raise Stage3ModelLaboratoryError(
                    "MODEL_LAB_WAVE2_SHARED_COLUMN_MISMATCH",
                    f"Wave 2 companion column {name} differs from Current Gold.",
                    status_code=409,
                )
        additions = [
            name
            for name in companion_requested
            if name != "canonicalPaId" and name not in frame.columns
        ]
        frame = pd.concat([frame, aligned[additions]], axis=1)
    frame.attrs["governedPriorRuntime"] = runtime
    frame.attrs["selectedV1PriorFeatures"] = selected_v1
    frame.attrs["selectedV2PriorFeatures"] = selected_v2
    return frame


def _transformation_groups(
    feature_set: Mapping[str, Any], features: Sequence[str] | None = None
) -> dict[str, Any]:
    """Resolve the exact registered fold-local transformation contract.

    Current immutable registrations use four supported contracts: raw numeric
    values (fold-median when physically missing), complete binary passthrough,
    physically-missing binary fold-mode imputation, and categorical UNKNOWN +
    one-hot.  Anything else fails closed instead of receiving a dtype-derived
    substitute.
    """

    ordered_features = list(features or feature_set.get("orderedFeatures") or [])
    raw_contract = feature_set.get("transformationContracts") or {}
    raw_ordered = raw_contract.get("ordered") if isinstance(raw_contract, Mapping) else None
    if not isinstance(raw_ordered, list):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_TRANSFORMATION_CONTRACT_MISSING",
            f"Feature set {feature_set.get('featureSetId')} lacks an ordered transformation contract.",
            status_code=409,
        )
    entries: dict[str, tuple[str, ...]] = {}
    contract_order: list[str] = []
    for raw in raw_ordered:
        if not isinstance(raw, Mapping):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_TRANSFORMATION_CONTRACT_INVALID",
                "A registered transformation entry is not an object.",
                status_code=409,
            )
        name = str(raw.get("feature") or "")
        steps = tuple(str(step) for step in (raw.get("steps") or []))
        if not name or name in entries:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_TRANSFORMATION_CONTRACT_INVALID",
                "The registered transformation contract has a missing or duplicate feature.",
                status_code=409,
            )
        entries[name] = steps
        contract_order.append(name)
    if contract_order != ordered_features:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_TRANSFORMATION_ORDER_MISMATCH",
            "The ordered predictor list and ordered transformation contract do not match exactly.",
            status_code=409,
        )

    groups: dict[str, list[str]] = {
        "numeric": [],
        "governed_prior": [],
        "binary": [],
        "binary_mode": [],
        "categorical": [],
    }
    for name in ordered_features:
        steps = entries[name]
        if steps == ("RETAIN_RAW",):
            groups["numeric"].append(name)
        elif steps == ("GOVERNED_PRIOR_POSTERIOR_MEAN",):
            groups["numeric"].append(name)
            groups["governed_prior"].append(name)
        elif steps == ("BINARY_PASSTHROUGH",):
            groups["binary"].append(name)
        elif steps == ("BINARY_MODE_IMPUTE",):
            groups["binary_mode"].append(name)
        elif steps == ("CATEGORICAL_UNKNOWN", "ONE_HOT"):
            groups["categorical"].append(name)
        else:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_TRANSFORMATION_STEP_UNSUPPORTED",
                f"Feature {name} has unsupported registered steps: {list(steps)}.",
                status_code=409,
            )
    return {**groups, "ordered": [{"feature": name, "steps": list(entries[name])} for name in ordered_features]}


def _apply_fold_local_governed_priors(
    frame: pd.DataFrame,
    *,
    train_mask: np.ndarray,
    validation_mask: np.ndarray,
    fold: Mapping[str, Any],
    feature_set: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Replace governed raw statistics with authenticated posterior means.

    Wave 1 population parameters are fit from the exact registered training
    prefix for this fold. Wave 2 consumes the already content-addressed child
    fitted for that same prefix. Validation values are transformed only after
    both authorities are frozen; no target is passed to either engine.
    """

    features = list(feature_set.get("orderedFeatures") or [])
    groups = _transformation_groups(feature_set, features)
    governed = list(groups["governed_prior"])
    train = frame.loc[train_mask].copy()
    validation = frame.loc[validation_mask].copy()
    if not governed:
        return train, validation, {
            "status": "NOT_REQUIRED",
            "features": [],
            "validationRowsUsedForFit": 0,
            "finalOotRowsRead": 0,
        }
    runtime = frame.attrs.get("governedPriorRuntime") or {}
    bindings = runtime.get("bindings") or {}
    v1_features = sorted(set(governed) & set(runtime.get("v1Features") or ()))
    v2_features = sorted(set(governed) & set(runtime.get("v2Features") or ()))
    unknown = sorted(set(governed) - set(v1_features) - set(v2_features))
    if unknown:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_GOVERNED_PRIOR_BINDING_MISSING",
            "No executable prior binding exists for: " + ", ".join(unknown),
            status_code=409,
        )
    evidence: dict[str, Any] = {
        "status": "APPLIED",
        "features": governed,
        "wave1Features": v1_features,
        "wave2Features": v2_features,
        "fitRows": int(train_mask.sum()),
        "validationRowsUsedForFit": 0,
        "targetColumnsRead": [],
        "finalOotRowsRead": 0,
        "companionAuthenticationChecksum": runtime.get(
            "companionAuthenticationChecksum"
        ),
    }
    if v1_features:
        fitted_v1 = player_prior.fit_prior_authority(
            frame,
            training_end=str(fold["trainEnd"]),
            authority_manifest=runtime["v1Authority"],
            fold_id=f"CORE_CHALLENGER_FOLD_{int(fold['foldNumber'])}",
            features=v1_features,
        )
        for target in (train, validation):
            transformed = player_prior.transform_prior_features(
                target, fitted_v1, features=v1_features
            )
            for feature in v1_features:
                output = str((bindings[feature].get("derivedOutputs") or {}).get("posteriorMean") or "")
                if output not in transformed:
                    raise Stage3ModelLaboratoryError(
                        "MODEL_LAB_WAVE1_PRIOR_OUTPUT_MISSING",
                        f"Wave 1 posterior output is missing for {feature}.",
                        status_code=409,
                    )
                target[feature] = transformed[output].to_numpy(dtype=np.float64)
        evidence["wave1FittedId"] = fitted_v1["fittedId"]
        evidence["wave1FittedChecksum"] = fitted_v1["fittedChecksum"]
        evidence["wave1AuthorityId"] = fitted_v1["authorityId"]
    if v2_features:
        fitted_v2 = (runtime.get("v2FittedByFold") or {}).get(
            int(fold["foldNumber"])
        )
        if not fitted_v2 or fitted_v2.get("trainingEnd") != fold.get("trainEnd"):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_WAVE2_FOLD_AUTHORITY_MISMATCH",
                "The Wave 2 fitted child does not match this registered chronological fold.",
                status_code=409,
            )
        for target in (train, validation):
            transformed = player_prior_v2.transform_prior_features(
                target, fitted_v2, features=v2_features
            )
            for feature in v2_features:
                output = str((bindings[feature].get("derivedOutputs") or {}).get("posteriorMean") or "")
                if output not in transformed:
                    raise Stage3ModelLaboratoryError(
                        "MODEL_LAB_WAVE2_PRIOR_OUTPUT_MISSING",
                        f"Wave 2 posterior output is missing for {feature}.",
                        status_code=409,
                    )
                target[feature] = transformed[output].to_numpy(dtype=np.float64)
        evidence["wave2FittedId"] = fitted_v2["fittedId"]
        evidence["wave2FittedChecksum"] = fitted_v2["fittedChecksum"]
        evidence["wave2AuthorityId"] = (runtime.get("v2Bundle") or {}).get(
            "authorityId"
        )
    evidence["evidenceChecksum"] = _sha(evidence)
    return train, validation, evidence


def _categorical_strings_with_nan(values: Any) -> Any:
    """Normalize categories without allowing nulls to become the string 'None'."""

    if isinstance(values, pd.DataFrame):
        output = values.astype("string").astype(object)
        return output.mask(pd.isna(output), np.nan)
    output = pd.DataFrame(values).astype("string").astype(object)
    return output.mask(pd.isna(output), np.nan).to_numpy(dtype=object)


def _column_groups(
    frame: pd.DataFrame, feature_set: Mapping[str, Any]
) -> dict[str, Any]:
    features = list(feature_set.get("orderedFeatures") or [])
    groups = _transformation_groups(feature_set, features)
    for name in features:
        if name not in frame.columns:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_FEATURE_COLUMN_MISSING",
                f"Registered feature {name} is absent from the execution frame.",
                status_code=409,
            )
        if frame[name].notna().sum() == 0:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_SOURCE_UNAVAILABLE_FEATURE",
                f"Registered feature {name} is entirely unavailable in the training population; zeros were not fabricated and ordinary imputation was refused.",
                status_code=409,
            )
    for name in groups["numeric"]:
        if not pd.api.types.is_numeric_dtype(frame[name]):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_NUMERIC_CONTRACT_TYPE_MISMATCH",
                f"Registered numeric feature {name} is not numeric in the execution frame.",
                status_code=409,
            )
    for name in groups["binary"]:
        if frame[name].isna().any():
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_BINARY_PASSTHROUGH_MISSING",
                f"Binary passthrough feature {name} contains missing values; the registered contract authorizes no imputation.",
                status_code=409,
            )
        if not (
            pd.api.types.is_numeric_dtype(frame[name])
            or pd.api.types.is_bool_dtype(frame[name])
        ):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_BINARY_CONTRACT_TYPE_MISMATCH",
                f"Binary passthrough feature {name} is not numeric/boolean in the execution frame.",
                status_code=409,
            )
    for name in groups["binary_mode"]:
        if not (
            pd.api.types.is_numeric_dtype(frame[name])
            or pd.api.types.is_bool_dtype(frame[name])
        ):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_BINARY_CONTRACT_TYPE_MISMATCH",
                f"Fold-mode binary feature {name} is not numeric/boolean in the execution frame.",
                status_code=409,
            )
    return groups


def _categorical_levels(frame: pd.DataFrame, features: Sequence[str]) -> list[list[str]]:
    levels: list[list[str]] = []
    for name in features:
        observed = {
            str(value)
            for value in frame[name].tolist()
            if not pd.isna(value)
        }
        observed.discard("UNKNOWN")
        levels.append([*sorted(observed), "UNKNOWN"])
    return levels


def _preprocessor(
    frame: pd.DataFrame,
    feature_set: Mapping[str, Any],
    *,
    dense_categoricals: bool,
) -> tuple[ColumnTransformer, dict[str, Any]]:
    groups = _column_groups(frame, feature_set)
    numeric = groups["numeric"]
    binary = groups["binary"]
    binary_mode = groups["binary_mode"]
    categorical = groups["categorical"]
    transformers: list[tuple[str, Any, list[str]]] = []
    if numeric:
        transformers.append(
            (
                "numeric",
                Pipeline([("imputer", SimpleImputer(strategy="median"))]),
                numeric,
            )
        )
    if binary:
        transformers.append(("binary", "passthrough", binary))
    if binary_mode:
        transformers.append(
            (
                "binary_mode",
                Pipeline([("imputer", SimpleImputer(strategy="most_frequent"))]),
                binary_mode,
            )
        )
    if categorical:
        # The registered categorical contract is CATEGORICAL_UNKNOWN +
        # ONE_HOT for every candidate family.  Dense learners receive the same
        # one-hot columns as a dense array; they are never silently changed to
        # ordinal codes.
        categorical_levels = _categorical_levels(frame, categorical)
        frozen_levels = tuple(tuple(levels) for levels in categorical_levels)
        encoder: Any = OneHotEncoder(
            categories=categorical_levels,
            handle_unknown="error",
            sparse_output=not dense_categoricals,
        )
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        (
                            "normalize",
                            FunctionTransformer(
                                _categorical_strings_with_nan,
                                validate=False,
                                feature_names_out="one-to-one",
                            ),
                        ),
                        (
                            "imputer",
                            SimpleImputer(strategy="constant", fill_value="UNKNOWN"),
                        ),
                        ("unknown", _UnknownCategoryMapper(frozen_levels)),
                        ("encoder", encoder),
                    ]
                ),
                categorical,
            )
        )
    return (
        ColumnTransformer(transformers, remainder="drop", sparse_threshold=0.3),
        groups,
    )


def _bounded_native_workers(requested: Any) -> int:
    """Return a safe runtime-only native worker count.

    Native parallelism is execution metadata, not a scientific
    hyperparameter.  Keep it out of candidate identity while bounding direct
    callers as well as resource-aware queued jobs.
    """

    if isinstance(requested, bool):
        return 1
    try:
        count = int(requested)
    except (TypeError, ValueError, OverflowError):
        return 1
    logical_cpus = max(1, int(os.cpu_count() or 1))
    return max(1, min(count, logical_cpus, 4))


def _model(
    family: str,
    seed: int,
    hyperparameters: Mapping[str, Any] | None = None,
    *,
    native_workers: int = 1,
) -> Any:
    parameters = _fixed_hyperparameters(family)
    parameters.update(dict(hyperparameters or {}))
    # Older immutable plans included these runtime knobs in their estimator
    # dictionaries.  They are not scientific hyperparameters: discard them
    # from the local constructor copy and inject the current bounded execution
    # budget without mutating the recorded configuration.
    parameters.pop("n_jobs", None)
    parameters.pop("thread_count", None)
    runtime_workers = _bounded_native_workers(native_workers)
    if family == "multinomial_logistic":
        return LogisticRegression(
            C=float(parameters["C"]),
            max_iter=int(parameters["max_iter"]),
            tol=float(parameters["tol"]),
            solver=str(parameters["solver"]),
            class_weight=parameters.get("class_weight"),
            random_state=seed,
        )
    if family == "elastic_net_logistic":
        return LogisticRegression(
            C=float(parameters["C"]),
            l1_ratio=float(parameters["l1_ratio"]),
            penalty="elasticnet",
            max_iter=int(parameters["max_iter"]),
            tol=float(parameters["tol"]),
            solver="saga",
            class_weight=parameters.get("class_weight"),
            random_state=seed,
        )
    if family == "decision_tree":
        return DecisionTreeClassifier(
            max_depth=parameters.get("max_depth"),
            min_samples_split=int(parameters["min_samples_split"]),
            min_samples_leaf=int(parameters["min_samples_leaf"]),
            criterion=str(parameters["criterion"]),
            class_weight=parameters.get("class_weight"),
            random_state=seed,
        )
    if family == "random_forest":
        return RandomForestClassifier(
            n_estimators=int(parameters["n_estimators"]),
            max_depth=parameters.get("max_depth"),
            min_samples_leaf=int(parameters["min_samples_leaf"]),
            max_features=parameters.get("max_features"),
            bootstrap=bool(parameters["bootstrap"]),
            class_weight=parameters.get("class_weight"),
            n_jobs=runtime_workers,
            random_state=seed,
        )
    if family == "extra_trees":
        return ExtraTreesClassifier(
            n_estimators=int(parameters["n_estimators"]),
            max_depth=parameters.get("max_depth"),
            min_samples_leaf=int(parameters["min_samples_leaf"]),
            max_features=parameters.get("max_features"),
            class_weight=parameters.get("class_weight"),
            n_jobs=runtime_workers,
            random_state=seed,
        )
    if family == "histogram_gradient_boosting":
        return HistGradientBoostingClassifier(
            learning_rate=float(parameters["learning_rate"]),
            max_iter=int(parameters["max_iter"]),
            max_leaf_nodes=int(parameters["max_leaf_nodes"]),
            max_depth=parameters.get("max_depth"),
            min_samples_leaf=int(parameters["min_samples_leaf"]),
            l2_regularization=float(parameters["l2_regularization"]),
            early_stopping=False,
            random_state=seed,
        )
    if family == "xgboost":
        try:
            from xgboost import XGBClassifier
        except ImportError as exc:  # pragma: no cover - guarded by availability
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_MODEL_FAMILY_UNAVAILABLE",
                "XGBoost is not installed; no dependency was added automatically.",
                status_code=409,
            ) from exc
        return XGBClassifier(
            objective="multi:softprob",
            num_class=len(GOLD_CLASS_ORDER),
            n_estimators=int(parameters["n_estimators"]),
            max_depth=int(parameters["max_depth"]),
            learning_rate=float(parameters["learning_rate"]),
            min_child_weight=float(parameters["min_child_weight"]),
            subsample=float(parameters["subsample"]),
            colsample_bytree=float(parameters["colsample_bytree"]),
            gamma=float(parameters["gamma"]),
            reg_alpha=float(parameters["reg_alpha"]),
            reg_lambda=float(parameters["reg_lambda"]),
            random_state=seed,
            n_jobs=runtime_workers,
            eval_metric="mlogloss",
        )
    if family == "lightgbm":
        try:
            from lightgbm import LGBMClassifier
        except ImportError as exc:  # pragma: no cover - guarded by catalog
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_MODEL_FAMILY_UNAVAILABLE", "LightGBM is not installed.", status_code=409
            ) from exc
        parameters["n_jobs"] = runtime_workers
        return LGBMClassifier(
            objective="multiclass",
            num_class=len(GOLD_CLASS_ORDER),
            random_state=seed,
            verbosity=-1,
            **parameters,
        )
    if family == "catboost":
        try:
            from catboost import CatBoostClassifier
        except ImportError as exc:  # pragma: no cover - guarded by catalog
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_MODEL_FAMILY_UNAVAILABLE", "CatBoost is not installed.", status_code=409
            ) from exc
        parameters["thread_count"] = runtime_workers
        return CatBoostClassifier(
            loss_function="MultiClass",
            random_seed=seed,
            allow_writing_files=False,
            **parameters,
        )
    if family == "linear_svm":
        calibration_cv = int(parameters.pop("calibration_cv", 3))
        return CalibratedClassifierCV(
            estimator=LinearSVC(random_state=seed, **parameters),
            method="sigmoid",
            cv=calibration_cv,
            n_jobs=1,
        )
    if family == "sgd_classifier":
        loss = str(parameters.get("loss") or "log_loss")
        estimator = SGDClassifier(random_state=seed, **parameters)
        if loss == "hinge":
            return CalibratedClassifierCV(
                estimator=estimator, method="sigmoid", cv=3, n_jobs=1
            )
        return estimator
    if family == "knn":
        parameters["n_jobs"] = runtime_workers
        return KNeighborsClassifier(**parameters)
    if family == "gaussian_naive_bayes":
        return GaussianNB(**parameters)
    if family == "mlp":
        hidden = parameters.get("hidden_layer_sizes")
        if isinstance(hidden, list):
            parameters["hidden_layer_sizes"] = tuple(int(value) for value in hidden)
        parameters["early_stopping"] = True
        return MLPClassifier(random_state=seed, **parameters)
    raise Stage3ModelLaboratoryError(
        "MODEL_LAB_MODEL_FAMILY_UNSUPPORTED", f"Unsupported model family: {family}."
    )


def _aligned_probabilities(model: Any, values: Any) -> np.ndarray:
    raw = np.asarray(model.predict_proba(values), dtype=float)
    classes = [int(value) for value in model.classes_]
    expected_classes = list(range(len(GOLD_CLASS_ORDER)))
    if (
        raw.ndim != 2
        or raw.shape[1] != len(classes)
        or len(classes) != len(set(classes))
        or sorted(classes) != expected_classes
    ):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_ESTIMATOR_CLASS_ORDER_INVALID",
            "The estimator must expose every governed target class exactly once.",
            status_code=409,
        )
    aligned = np.zeros((raw.shape[0], len(GOLD_CLASS_ORDER)), dtype=float)
    for source_index, class_index in enumerate(classes):
        aligned[:, class_index] = raw[:, source_index]
    return aligned


def _validate_probability_matrix(
    probabilities: Any, *, expected_rows: int | None = None
) -> np.ndarray:
    values = np.asarray(probabilities, dtype=float)
    shape_valid = (
        values.ndim == 2
        and values.shape[0] > 0
        and values.shape[1] == len(GOLD_CLASS_ORDER)
        and (expected_rows is None or values.shape[0] == int(expected_rows))
    )
    finite = bool(np.isfinite(values).all()) if values.size else False
    minimum = float(np.min(values)) if finite and values.size else None
    maximum = float(np.max(values)) if finite and values.size else None
    row_sums = (
        values.sum(axis=1, dtype=np.float64)
        if shape_valid and finite
        else np.asarray([], dtype=np.float64)
    )
    maximum_sum_deviation = (
        float(np.max(np.abs(row_sums - 1.0))) if row_sums.size else None
    )
    valid = (
        shape_valid
        and finite
        and minimum is not None
        and maximum is not None
        and minimum >= 0.0
        and maximum <= 1.0
        and maximum_sum_deviation is not None
        and maximum_sum_deviation <= RAW_PROBABILITY_ROW_SUM_ATOL
    )
    if not valid:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_PROBABILITY_RECONCILIATION_FAILED",
            "The estimator produced an invalid governed multiclass probability "
            f"matrix: shape={values.shape}, expectedRows={expected_rows}, "
            f"finite={finite}, minimum={minimum}, maximum={maximum}, "
            "maximumAbsoluteRowSumDeviation="
            f"{maximum_sum_deviation}, rowSumRtol="
            f"{RAW_PROBABILITY_ROW_SUM_RTOL}, rowSumAtol="
            f"{RAW_PROBABILITY_ROW_SUM_ATOL}.",
        )
    # This array is intentionally not normalized.  The accepted Model Lab
    # metrics and legacy OOF digest are defined over the class-aligned raw
    # estimator values (represented as float64 without changing their scalar
    # values), including ordinary float32 softmax summation roundoff.
    return values


def _normalize_executable_probabilities(probabilities: np.ndarray) -> np.ndarray:
    """Normalize already-valid raw rows only at the executable scoring boundary."""

    values = np.asarray(probabilities, dtype=np.float64).copy()
    row_sums = values.sum(axis=1, dtype=np.float64)
    values /= row_sums[:, np.newaxis]

    # Make NumPy float64 row sums exactly 1.0.  Correcting columns in stable
    # descending-probability order avoids creating a negative residual for
    # tiny classes while accommodating the reduction tree used by np.sum.
    rows = np.arange(values.shape[0])
    correction_order = np.argsort(-values, axis=1, kind="stable")
    for rank in range(values.shape[1]):
        incorrect = values.sum(axis=1, dtype=np.float64) != 1.0
        if not incorrect.any():
            break
        selected_rows = rows[incorrect]
        selected_columns = correction_order[incorrect, rank]
        without_selected = values[incorrect].copy()
        without_selected[np.arange(len(selected_rows)), selected_columns] = 0.0
        values[selected_rows, selected_columns] = 1.0 - without_selected.sum(
            axis=1, dtype=np.float64
        )
    exact_sums = values.sum(axis=1, dtype=np.float64)
    if (
        not np.isfinite(values).all()
        or (values < 0.0).any()
        or not np.equal(exact_sums, 1.0).all()
    ):
        maximum_deviation = float(np.max(np.abs(exact_sums - 1.0)))
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_EXECUTABLE_PROBABILITY_NORMALIZATION_FAILED",
            "Already-valid raw probabilities could not be normalized to exact "
            f"float64 row sums; maximumAbsoluteRowSumDeviation={maximum_deviation}.",
            status_code=409,
        )
    return values


def fit_stage3_pipeline(
    frame: pd.DataFrame,
    *,
    model_family: str,
    feature_set: Mapping[str, Any],
    seed: int,
    hyperparameters: Mapping[str, Any] | None = None,
    native_workers: int = 1,
) -> tuple[Stage3FittedPipeline, dict[str, Any]]:
    """Fit one exact preprocessing-plus-estimator pipeline on ``frame``.

    This seam is shared by fold reproduction and the final development-only
    fit.  It never performs a data scan and therefore cannot broaden the
    caller's authorized population.
    """

    features = list(feature_set.get("orderedFeatures") or [])
    if not features or len(features) != len(set(features)):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_FEATURE_ORDER_INVALID",
            "The fitted pipeline requires one non-empty unique ordered feature contract.",
            status_code=409,
        )
    missing = [name for name in [*features, "outcome"] if name not in frame.columns]
    if missing:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_FIT_COLUMNS_MISSING",
            "The authorized fit frame is missing: " + ", ".join(missing),
            status_code=409,
        )
    labels = frame["outcome"].map(
        {name: index for index, name in enumerate(GOLD_CLASS_ORDER)}
    )
    if labels.isna().any():
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_TARGET_ENCODING_FAILED",
            "A governed target could not be encoded.",
        )
    dense = model_family in {
        "histogram_gradient_boosting",
        "gaussian_naive_bayes",
        "mlp",
        "catboost",
    }
    preprocessor, transformation_groups = _preprocessor(
        frame.loc[:, features], feature_set, dense_categoricals=dense
    )
    runtime_workers = _bounded_native_workers(native_workers)
    train_values = preprocessor.fit_transform(frame.loc[:, features])
    estimator = _model(
        model_family,
        int(seed),
        hyperparameters=hyperparameters,
        native_workers=runtime_workers,
    )
    with threadpool_limits(limits=runtime_workers):
        estimator.fit(train_values, labels.to_numpy(dtype=np.int64))
    pipeline = Stage3FittedPipeline(
        ordered_features=features,
        target_order=GOLD_CLASS_ORDER,
        preprocessor=preprocessor,
        estimator=estimator,
    )
    return pipeline, {
        "fitRows": int(len(frame)),
        "seed": int(seed),
        "nativeWorkers": runtime_workers,
        "registeredOrderedTransformations": transformation_groups["ordered"],
        "transformedFeatureCount": int(train_values.shape[1]),
        "validationRowsUsedForParameters": 0,
        "finalOotRowsUsedForParameters": 0,
    }


def _ece(probabilities: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    confidence = probabilities.max(axis=1)
    predictions = probabilities.argmax(axis=1)
    correct = predictions == labels
    result = 0.0
    for lower in np.linspace(0.0, 1.0, bins, endpoint=False):
        upper = lower + 1.0 / bins
        selected = (confidence >= lower) & (
            confidence <= upper if math.isclose(upper, 1.0) else confidence < upper
        )
        if selected.any():
            result += float(selected.mean()) * abs(
                float(confidence[selected].mean()) - float(correct[selected].mean())
            )
    return float(result)


def _metrics(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    truth = np.eye(len(GOLD_CLASS_ORDER), dtype=float)[labels]
    class_calibration = []
    for index, class_name in enumerate(GOLD_CLASS_ORDER):
        observed = truth[:, index]
        predicted = probabilities[:, index]
        class_calibration.append(
            {
                "class": class_name,
                "support": int(observed.sum()),
                "observedRate": float(observed.mean()),
                "meanPredictedProbability": float(predicted.mean()),
                "absoluteCalibrationError": float(
                    abs(predicted.mean() - observed.mean())
                ),
                "oneVsRestBrier": float(np.mean((predicted - observed) ** 2)),
                "oneVsRestRocAuc": (
                    float(roc_auc_score(observed, predicted))
                    if 0 < int(observed.sum()) < int(observed.size)
                    else None
                ),
            }
        )
    predicted_labels = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = predicted_labels == labels
    reliability_bands = []
    for lower in np.linspace(0.0, 1.0, 10, endpoint=False):
        upper = lower + 0.1
        selected = (confidence >= lower) & (
            confidence <= upper if math.isclose(upper, 1.0) else confidence < upper
        )
        reliability_bands.append(
            {
                "lowerBound": float(lower),
                "upperBound": float(upper),
                "observations": int(selected.sum()),
                "meanConfidence": (
                    float(confidence[selected].mean()) if selected.any() else None
                ),
                "observedAccuracy": (
                    float(correct[selected].mean()) if selected.any() else None
                ),
                "absoluteCalibrationGap": (
                    float(abs(confidence[selected].mean() - correct[selected].mean()))
                    if selected.any()
                    else None
                ),
            }
        )
    return {
        "multiclassLogLoss": float(
            log_loss(labels, probabilities, labels=list(range(len(GOLD_CLASS_ORDER))))
        ),
        "summedBrier": float(np.mean(np.sum((probabilities - truth) ** 2, axis=1))),
        "ece": _ece(probabilities, labels),
        "accuracy": float(np.mean(predicted_labels == labels)),
        "macroF1": float(
            f1_score(
                labels,
                predicted_labels,
                labels=list(range(len(GOLD_CLASS_ORDER))),
                average="macro",
                zero_division=0,
            )
        ),
        "macroOvrRocAuc": float(
            roc_auc_score(
                labels,
                probabilities,
                labels=list(range(len(GOLD_CLASS_ORDER))),
                multi_class="ovr",
                average="macro",
            )
        ),
        "reliabilityBands": reliability_bands,
        "classCalibration": class_calibration,
        "rareClass": min(class_calibration, key=lambda item: item["support"]),
    }


def _probability_reconciliation(probabilities: np.ndarray) -> dict[str, Any]:
    tolerance = 1e-8
    finite_mask = np.isfinite(probabilities)
    non_finite_values = int((~finite_mask).sum())
    negative_values = int((finite_mask & (probabilities < 0.0)).sum())
    above_one_values = int((finite_mask & (probabilities > 1.0)).sum())
    row_sums = probabilities.sum(axis=1)
    finite_values = probabilities[finite_mask]
    maximum_row_sum_error = (
        float(np.max(np.abs(row_sums - 1.0)))
        if bool(np.isfinite(row_sums).all())
        else None
    )
    passed = (
        non_finite_values == 0
        and negative_values == 0
        and above_one_values == 0
        and maximum_row_sum_error is not None
        and maximum_row_sum_error <= tolerance
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "rows": int(probabilities.shape[0]),
        "classCount": int(probabilities.shape[1]),
        "nonFiniteValues": non_finite_values,
        "negativeValues": negative_values,
        "aboveOneValues": above_one_values,
        "minimumProbability": float(finite_values.min()) if finite_values.size else None,
        "maximumProbability": float(finite_values.max()) if finite_values.size else None,
        "maximumAbsoluteRowSumError": maximum_row_sum_error,
        "tolerance": tolerance,
    }


def _process_memory_evidence() -> dict[str, Any]:
    """Return local-process working-set evidence where the host exposes it."""

    if os.name != "nt":
        return {
            "status": "UNAVAILABLE_ON_HOST",
            "measurementScope": "LOCAL_MODEL_JOB_PROCESS",
        }
    try:
        import ctypes

        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        if not ctypes.windll.psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        ):
            raise OSError("GetProcessMemoryInfo returned false")
        return {
            "status": "MEASURED",
            "measurementScope": "LOCAL_MODEL_JOB_PROCESS",
            "measurementKind": "PROCESS_LIFETIME_PEAK_WORKING_SET",
            "workingSetBytes": int(counters.working_set_size),
            "peakWorkingSetBytes": int(counters.peak_working_set_size),
        }
    except Exception as exc:  # pragma: no cover - host instrumentation only
        return {
            "status": "UNAVAILABLE_ON_HOST",
            "measurementScope": "LOCAL_MODEL_JOB_PROCESS",
            "reason": type(exc).__name__,
        }


def _persist_oof_predictions(
    *,
    canonical_pa_ids: Sequence[str],
    canonical_game_ids: Sequence[str],
    fold_numbers: np.ndarray,
    labels: np.ndarray,
    probabilities: np.ndarray,
    model_family: str,
    feature_set_id: str | None,
    seed: int,
) -> dict[str, Any]:
    """Persist reloadable row-level Development OOF predictions by content hash."""

    row_count = int(labels.size)
    if (
        len(canonical_pa_ids) != row_count
        or len(canonical_game_ids) != row_count
        or int(fold_numbers.size) != row_count
        or probabilities.shape != (row_count, len(GOLD_CLASS_ORDER))
    ):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_OOF_ARTIFACT_SHAPE_MISMATCH",
            "The row-level OOF evidence is not aligned one-to-one.",
            status_code=409,
        )
    if len(set(canonical_pa_ids)) != row_count:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_OOF_ARTIFACT_KEY_DUPLICATE",
            "The row-level OOF evidence contains duplicate canonical plate-appearance keys.",
            status_code=409,
        )
    if any(not str(value) for value in canonical_game_ids):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_OOF_GAME_KEY_MISSING",
            "The row-level OOF evidence contains a missing game-cluster key.",
            status_code=409,
        )
    metadata = {
        "schemaVersion": "SPORTS_STAGE3_DEVELOPMENT_OOF_PREDICTIONS_V2",
        "scope": "FIVE_FOLD_OOF_DEVELOPMENT_ONLY",
        "clusterResamplingKey": "canonicalGameId",
        "modelFamily": model_family,
        "featureSetId": feature_set_id,
        "seed": int(seed),
        "orderedClasses": list(GOLD_CLASS_ORDER),
        "finalOotTargetAccessed": False,
        "finalOotScored": False,
    }
    columns: dict[str, pa.Array] = {
        "canonicalPaId": pa.array(canonical_pa_ids, type=pa.string()),
        "canonicalGameId": pa.array(canonical_game_ids, type=pa.string()),
        "foldNumber": pa.array(fold_numbers, type=pa.int8()),
        "observedClassIndex": pa.array(labels, type=pa.int8()),
    }
    for class_index, class_name in enumerate(GOLD_CLASS_ORDER):
        columns[f"probability_{class_name}"] = pa.array(
            probabilities[:, class_index], type=pa.float64()
        )
    table = pa.table(columns).replace_schema_metadata(
        {b"asp_oof_contract": canonical_json_bytes(metadata)}
    )
    root = _runtime_root()
    object_dir = root / "objects" / "oof" / "sha256"
    object_dir.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix="model-lab-oof-", suffix=".parquet.tmp", dir=object_dir
    )
    os.close(handle)
    temporary_path = Path(temporary_name)
    try:
        pq.write_table(
            table,
            temporary_path,
            compression="zstd",
            use_dictionary=["canonicalPaId"],
            write_statistics=True,
        )
        digest = hashlib.sha256()
        with temporary_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        artifact_sha = digest.hexdigest()
        artifact_path = object_dir / f"{artifact_sha}.parquet"
        if artifact_path.exists():
            if artifact_path.read_bytes() != temporary_path.read_bytes():
                raise Stage3ModelLaboratoryError(
                    "MODEL_LAB_OOF_OBJECT_COLLISION",
                    "An OOF content address contains different bytes.",
                    status_code=409,
                )
            temporary_path.unlink()
        else:
            os.replace(temporary_path, artifact_path)
        return {
            "reloadableArtifactSha256": artifact_sha,
            "reloadableArtifactRelativePath": str(
                artifact_path.relative_to(root)
            ).replace("\\", "/"),
            "reloadableArtifactBytes": int(artifact_path.stat().st_size),
            "reloadableArtifactFormat": "PARQUET_ZSTD",
            "reloadableArtifactSchemaVersion": metadata["schemaVersion"],
        }
    finally:
        temporary_path.unlink(missing_ok=True)


def _evaluation_evidence(
    probabilities: np.ndarray,
    labels: np.ndarray,
    *,
    oof_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Create bounded development-only diagnostics for later Evaluation.

    V2 receipts retain aggregate confusion and one-vs-rest lift/gains evidence
    plus the content address of the separately persisted row-level artifact.
    """

    class_count = len(GOLD_CLASS_ORDER)
    predicted = probabilities.argmax(axis=1)
    confusion = np.zeros((class_count, class_count), dtype=np.int64)
    np.add.at(confusion, (labels, predicted), 1)
    totals = confusion.sum(axis=1, keepdims=True)
    normalized = np.divide(
        confusion,
        totals,
        out=np.zeros_like(confusion, dtype=float),
        where=totals != 0,
    )
    lift_by_class: dict[str, list[dict[str, Any]]] = {}
    for class_index, class_name in enumerate(GOLD_CLASS_ORDER):
        observed = (labels == class_index).astype(np.int8)
        order = np.argsort(-probabilities[:, class_index], kind="stable")
        bins = np.array_split(order, 10)
        prevalence = float(observed.mean())
        cumulative_observed = 0
        total_observed = int(observed.sum())
        rows: list[dict[str, Any]] = []
        for bin_index, indices in enumerate(bins, start=1):
            positives = int(observed[indices].sum())
            cumulative_observed += positives
            rate = float(positives / len(indices)) if len(indices) else 0.0
            rows.append(
                {
                    "decile": bin_index,
                    "observations": int(len(indices)),
                    "positives": positives,
                    "observedRate": rate,
                    "lift": float(rate / prevalence) if prevalence else None,
                    "cumulativeGain": (
                        float(cumulative_observed / total_observed)
                        if total_observed
                        else None
                    ),
                }
            )
        lift_by_class[class_name] = rows
    digest = hashlib.sha256()
    digest.update(np.asarray(labels, dtype="<i2").tobytes(order="C"))
    digest.update(np.asarray(probabilities, dtype="<f8").tobytes(order="C"))
    return {
        "status": "AVAILABLE_AGGREGATED_DEVELOPMENT_ONLY",
        "scope": "FIVE_FOLD_OOF_DEVELOPMENT_ONLY",
        "rowCount": int(labels.size),
        "orderedClasses": list(GOLD_CLASS_ORDER),
        "confusionMatrix": confusion.tolist(),
        "normalizedConfusionMatrix": normalized.tolist(),
        "oneVsRestLiftByClass": lift_by_class,
        "oofPredictionEvidenceSha256": digest.hexdigest(),
        **dict(oof_artifact),
        "reloadableArtifactStatus": "PERSISTED_CONTENT_ADDRESSED_DEVELOPMENT_ONLY",
        "finalOotTargetAccessed": False,
    }


def _model_complexity(estimator: Any, transformed_values: Any) -> dict[str, Any]:
    transformed_features = int(transformed_values.shape[1])
    result: dict[str, Any] = {
        "estimatorClass": estimator.__class__.__name__,
        "transformedFeatureCount": transformed_features,
        "parameterCount": None,
    }
    coefficients = getattr(estimator, "coef_", None)
    intercept = getattr(estimator, "intercept_", None)
    if coefficients is not None:
        result["parameterCount"] = int(np.asarray(coefficients).size) + int(
            np.asarray(intercept).size if intercept is not None else 0
        )
    if hasattr(estimator, "n_iter_"):
        iterations = np.asarray(getattr(estimator, "n_iter_"))
        result["optimizationIterations"] = int(iterations.max())
    if hasattr(estimator, "get_booster"):
        try:
            result["treeCount"] = len(estimator.get_booster().get_dump())
        except Exception:  # pragma: no cover - diagnostic only
            result["treeCount"] = None
    return result


def _native_interpretability(
    estimator: Any, preprocessor: ColumnTransformer
) -> dict[str, Any]:
    """Persist bounded fold evidence that Evaluation can inspect later.

    This is deliberately diagnostic evidence, not a feature-selection
    authority.  The complete coefficient/importance vector is content hashed;
    the review payload keeps only the strongest effects so receipts stay
    bounded even when categorical expansion is large.  Permutation importance
    remains an Evaluation-stage calculation on governed validation rows.
    """

    feature_names = [str(value) for value in preprocessor.get_feature_names_out()]
    selection_constraint = (
        "DIAGNOSTIC_ONLY_NATIVE_IMPORTANCE_IS_NEVER_SOLE_FEATURE_SELECTION_AUTHORITY"
    )
    coefficients = getattr(estimator, "coef_", None)
    if coefficients is not None:
        matrix = np.asarray(coefficients, dtype=float)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.shape[1] != len(feature_names) or not np.isfinite(matrix).all():
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_INTERPRETABILITY_RECONCILIATION_FAILED",
                "The fitted coefficient matrix did not reconcile to transformed features.",
            )
        magnitudes = np.mean(np.abs(matrix), axis=0)
        order = np.argsort(-magnitudes, kind="stable")[:50]
        class_names = (
            list(GOLD_CLASS_ORDER)
            if matrix.shape[0] == len(GOLD_CLASS_ORDER)
            else [f"COEFFICIENT_ROW_{index + 1}" for index in range(matrix.shape[0])]
        )
        full_evidence = {
            "featureNames": feature_names,
            "coefficientRows": class_names,
            "coefficients": matrix.tolist(),
        }
        return {
            "status": "AVAILABLE_NATIVE",
            "method": "COEFFICIENT_ABSOLUTE_MEAN",
            "transformedFeatureCount": len(feature_names),
            "completeEvidenceSha256": hashlib.sha256(
                canonical_json_bytes(full_evidence)
            ).hexdigest(),
            "topFeatures": [
                {
                    "feature": feature_names[int(index)],
                    "meanAbsoluteCoefficient": float(magnitudes[int(index)]),
                }
                for index in order
            ],
            "coefficientRows": class_names,
            "perClassTopFeatures": [
                {
                    "class": class_name,
                    "features": [
                        {
                            "feature": feature_names[int(index)],
                            "coefficient": float(matrix[row_index, int(index)]),
                            "absoluteCoefficient": float(
                                abs(matrix[row_index, int(index)])
                            ),
                        }
                        for index in np.argsort(
                            -np.abs(matrix[row_index]), kind="stable"
                        )[:20]
                    ],
                }
                for row_index, class_name in enumerate(class_names)
            ],
            "permutationImportance": "DEFERRED_TO_GOVERNED_EVALUATION",
            "selectionConstraint": selection_constraint,
        }

    native = getattr(estimator, "feature_importances_", None)
    if native is not None:
        importance = np.asarray(native, dtype=float).reshape(-1)
        if importance.size != len(feature_names) or not np.isfinite(importance).all():
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_INTERPRETABILITY_RECONCILIATION_FAILED",
                "The fitted native-importance vector did not reconcile to transformed features.",
            )
        order = np.argsort(-importance, kind="stable")[:50]
        full_evidence = {
            "featureNames": feature_names,
            "nativeImportance": importance.tolist(),
        }
        return {
            "status": "AVAILABLE_NATIVE",
            "method": "NATIVE_TREE_IMPORTANCE",
            "transformedFeatureCount": len(feature_names),
            "completeEvidenceSha256": hashlib.sha256(
                canonical_json_bytes(full_evidence)
            ).hexdigest(),
            "topFeatures": [
                {
                    "feature": feature_names[int(index)],
                    "nativeImportance": float(importance[int(index)]),
                }
                for index in order
            ],
            "permutationImportance": "DEFERRED_TO_GOVERNED_EVALUATION",
            "selectionConstraint": selection_constraint,
        }

    return {
        "status": "DEFERRED_TO_EVALUATION",
        "method": "PERMUTATION_IMPORTANCE_REQUIRED",
        "transformedFeatureCount": len(feature_names),
        "completeEvidenceSha256": None,
        "topFeatures": [],
        "permutationImportance": "REQUIRED_IN_GOVERNED_EVALUATION",
        "selectionConstraint": selection_constraint,
    }


def _interpretability_stability(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evidence = [dict(fold.get("interpretabilityEvidence") or {}) for fold in folds]
    appearances: dict[str, list[float]] = {}
    for fold_evidence in evidence:
        for item in fold_evidence.get("topFeatures") or []:
            feature = str(item.get("feature") or "")
            if not feature:
                continue
            value = item.get("nativeImportance", item.get("meanAbsoluteCoefficient"))
            if value is not None:
                appearances.setdefault(feature, []).append(float(value))
    stable = sorted(
        (
            {
                "feature": feature,
                "topFoldAppearances": len(values),
                "meanNativeMagnitude": float(np.mean(values)),
                "nativeMagnitudeStdDev": float(np.std(values, ddof=0)),
            }
            for feature, values in appearances.items()
        ),
        key=lambda item: (-item["topFoldAppearances"], -item["meanNativeMagnitude"], item["feature"]),
    )[:50]
    class_coefficients: dict[tuple[str, str], list[float]] = {}
    for fold_evidence in evidence:
        for class_row in fold_evidence.get("perClassTopFeatures") or []:
            class_name = str(class_row.get("class") or "")
            for feature_row in class_row.get("features") or []:
                feature = str(feature_row.get("feature") or "")
                coefficient = feature_row.get("coefficient")
                if class_name and feature and coefficient is not None:
                    class_coefficients.setdefault((class_name, feature), []).append(
                        float(coefficient)
                    )
    per_class: dict[str, list[dict[str, Any]]] = {}
    for class_name in GOLD_CLASS_ORDER:
        rows = [
            {
                "feature": feature,
                "topFoldAppearances": len(values),
                "meanCoefficient": float(np.mean(values)),
                "coefficientStdDev": float(np.std(values, ddof=0)),
                "directionStability": float(
                    max(
                        np.mean(np.asarray(values) >= 0),
                        np.mean(np.asarray(values) <= 0),
                    )
                ),
            }
            for (candidate_class, feature), values in class_coefficients.items()
            if candidate_class == class_name
        ]
        rows.sort(
            key=lambda item: (
                -item["topFoldAppearances"],
                -abs(item["meanCoefficient"]),
                item["feature"],
            )
        )
        per_class[class_name] = rows[:30]
    return {
        "foldStatuses": [item.get("status") for item in evidence],
        "foldMethods": [item.get("method") for item in evidence],
        "nativeTopFeatureStability": stable,
        "perClassCoefficientStability": per_class,
        "permutationImportance": "DEFERRED_TO_GOVERNED_EVALUATION",
        "selectionConstraint": (
            "DIAGNOSTIC_ONLY_NATIVE_IMPORTANCE_IS_NEVER_SOLE_FEATURE_SELECTION_AUTHORITY"
        ),
    }


def _subset_feature_contract(
    feature_set: Mapping[str, Any], features: Sequence[str]
) -> dict[str, Any]:
    raw = (feature_set.get("transformationContracts") or {}).get("ordered") or []
    by_name = {
        str(item.get("feature")): dict(item)
        for item in raw
        if isinstance(item, Mapping) and item.get("feature")
    }
    missing = [name for name in features if name not in by_name]
    if missing:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_SELECTOR_TRANSFORMATION_MISSING",
            "Fold-local selection could not bind transformations for: "
            + ", ".join(missing),
        )
    return {
        **dict(feature_set),
        "orderedFeatures": list(features),
        "transformationContracts": {
            **dict(feature_set.get("transformationContracts") or {}),
            "ordered": [by_name[name] for name in features],
        },
    }


def _source_feature_importance(
    estimator: Any,
    preprocessor: ColumnTransformer,
    source_features: Sequence[str],
) -> dict[str, float]:
    transformed = [str(value) for value in preprocessor.get_feature_names_out()]
    coefficients = getattr(estimator, "coef_", None)
    native = getattr(estimator, "feature_importances_", None)
    if coefficients is not None:
        matrix = np.asarray(coefficients, dtype=float)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        values = np.mean(np.abs(matrix), axis=0)
    elif native is not None:
        values = np.abs(np.asarray(native, dtype=float).reshape(-1))
    else:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_SELECTOR_ESTIMATOR_INCOMPATIBLE",
            "This estimator exposes neither coefficients nor native feature importance for fold-local elimination.",
            status_code=409,
        )
    if len(transformed) != len(values) or not np.isfinite(values).all():
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_SELECTOR_IMPORTANCE_RECONCILIATION_FAILED",
            "Fold-local selector importance did not reconcile to transformed features.",
        )
    importance = {name: 0.0 for name in source_features}
    for transformed_name, value in zip(transformed, values, strict=True):
        clean = transformed_name.split("__", 1)[-1]
        matches = [
            name
            for name in source_features
            if clean == name or clean.startswith(name + "_")
        ]
        if not matches:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_SELECTOR_SOURCE_MAPPING_FAILED",
                f"Transformed selector feature {transformed_name} did not map to one governed source predictor.",
            )
        source = max(matches, key=len)
        importance[source] += float(abs(value))
    return importance


def _fold_local_recursive_selection(
    training: pd.DataFrame,
    labels: np.ndarray,
    *,
    feature_set: Mapping[str, Any],
    model_family: str,
    seed: int,
    hyperparameters: Mapping[str, Any] | None,
    selector: Mapping[str, Any],
    fold_number: int,
    native_workers: int,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> tuple[list[str], ColumnTransformer, Any, Any, dict[str, Any], dict[str, Any]]:
    current = list(feature_set.get("orderedFeatures") or [])
    minimum = int(selector["minimumRetainedFeatures"])
    step = int(selector["eliminationStep"])
    dense = model_family in {
        "histogram_gradient_boosting", "gaussian_naive_bayes", "mlp", "catboost",
    }
    rounds: list[dict[str, Any]] = []
    while True:
        contract = _subset_feature_contract(feature_set, current)
        preprocessor, groups = _preprocessor(
            training[current], contract, dense_categoricals=dense
        )
        values = preprocessor.fit_transform(training[current])
        estimator = _model(
            model_family,
            seed + fold_number + len(rounds),
            hyperparameters=hyperparameters,
            native_workers=native_workers,
        )
        with threadpool_limits(limits=native_workers):
            estimator.fit(values, labels)
        importance = _source_feature_importance(estimator, preprocessor, current)
        ranking = sorted(current, key=lambda name: (-importance[name], name))
        if len(current) <= minimum:
            rounds.append(
                {
                    "round": len(rounds) + 1,
                    "inputFeatureCount": len(current),
                    "removedFeatures": [],
                    "retainedFeatures": list(current),
                    "trainingRows": int(len(training)),
                    "validationRowsUsedForSelection": 0,
                    "ranking": [
                        {"feature": name, "trainingOnlyMagnitude": importance[name]}
                        for name in ranking
                    ],
                }
            )
            return current, preprocessor, estimator, values, groups, {
                "method": selector["method"],
                "fold": fold_number,
                "rounds": rounds,
                "retainedFeatures": list(current),
                "removedFeatures": [
                    name
                    for name in feature_set.get("orderedFeatures") or []
                    if name not in set(current)
                ],
                "validationRowsUsedForSelection": 0,
                "finalOotRowsUsedForSelection": 0,
            }
        remove_count = min(step, len(current) - minimum)
        removed = sorted(current, key=lambda name: (importance[name], name))[:remove_count]
        rounds.append(
            {
                "round": len(rounds) + 1,
                "inputFeatureCount": len(current),
                "removedFeatures": removed,
                "retainedFeatureCount": len(current) - len(removed),
                "trainingRows": int(len(training)),
                "validationRowsUsedForSelection": 0,
                "rankingSha256": hashlib.sha256(
                    canonical_json_bytes(
                        {"ranking": [{"feature": name, "magnitude": importance[name]} for name in ranking]}
                    )
                ).hexdigest(),
            }
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "state": "RUNNING",
                    "modelFamily": model_family,
                    "fold": fold_number,
                    "event": "FOLD_SELECTOR_FIT_COMPLETED",
                    "selectorRound": len(rounds),
                    "retainedFeatureCount": len(current) - len(removed),
                }
            )
        removed_set = set(removed)
        current = [name for name in current if name not in removed_set]


def _evaluate_candidate(
    frame: pd.DataFrame,
    *,
    model_family: str,
    feature_set: Mapping[str, Any] | None,
    split: Mapping[str, Any],
    seed: int,
    hyperparameters: Mapping[str, Any] | None = None,
    fold_local_selector: Mapping[str, Any] | None = None,
    native_workers: int = 1,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    artifact_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    memory_at_start = _process_memory_evidence()
    runtime_workers = _bounded_native_workers(native_workers)
    features = list((feature_set or {}).get("orderedFeatures") or [])
    labels = frame["outcome"].map({name: index for index, name in enumerate(GOLD_CLASS_ORDER)})
    if labels.isna().any():
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_TARGET_ENCODING_FAILED", "A governed target could not be encoded."
        )
    y = labels.to_numpy(dtype=np.int64)
    fold_results: list[dict[str, Any]] = []
    all_probabilities: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []
    all_oof_keys: list[str] = []
    all_oof_game_ids: list[str] = []
    all_oof_fold_numbers: list[np.ndarray] = []
    fold_selection_evidence: list[dict[str, Any]] = []
    contract_folds = list((split.get("contract") or {}).get("folds") or [])
    for fold in contract_folds:
        if progress_callback is not None:
            progress_callback(
                {
                    "state": "RUNNING",
                    "modelFamily": model_family,
                    "hyperparameters": dict(hyperparameters or _fixed_hyperparameters(model_family)),
                    "fold": int(fold["foldNumber"]),
                    "foldCount": len(contract_folds),
                    "event": "FOLD_STARTED",
                }
            )
        train_mask = _date_mask(frame, str(fold["trainStart"]), str(fold["trainEnd"]))
        validation_mask = _date_mask(
            frame, str(fold["validationStart"]), str(fold["validationEnd"])
        )
        train_games = int(frame.loc[train_mask, "canonicalGameId"].nunique())
        validation_games = int(frame.loc[validation_mask, "canonicalGameId"].nunique())
        if (
            int(train_mask.sum()) != int(fold["trainRows"])
            or int(validation_mask.sum()) != int(fold["validationRows"])
            or train_games != int(fold["trainGames"])
            or validation_games != int(fold["validationGames"])
        ):
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_FOLD_ROW_MISMATCH",
                f"Fold {fold['foldNumber']} row/game counts differ from the registered split.",
                status_code=409,
            )
        train_labels = y[train_mask]
        validation_labels = y[validation_mask]
        fold_started = time.perf_counter()
        fold_warnings: list[dict[str, str]] = []
        governed_prior_evidence: dict[str, Any] | None = None
        if model_family == "class_frequency_null":
            counts = np.bincount(train_labels, minlength=len(GOLD_CLASS_ORDER)).astype(float)
            probabilities = np.tile(counts / counts.sum(), (int(validation_mask.sum()), 1))
            preprocessing = {
                "kind": "NONE_REQUIRED_FOR_CLASS_FREQUENCY_REFERENCE",
                "fitRows": int(train_mask.sum()),
                "validationRowsUsedForParameters": 0,
                "finalOotRowsUsedForParameters": 0,
            }
            complexity = {
                "estimatorClass": "ClassFrequencyNull",
                "transformedFeatureCount": 0,
                "parameterCount": len(GOLD_CLASS_ORDER),
            }
            interpretability = {
                "status": "NOT_APPLICABLE_REFERENCE",
                "method": "NONE",
                "transformedFeatureCount": 0,
                "completeEvidenceSha256": None,
                "topFeatures": [],
                "permutationImportance": "NOT_APPLICABLE_REFERENCE",
                "selectionConstraint": "REFERENCE_MODEL_NOT_A_FEATURE_SELECTION_AUTHORITY",
            }
        else:
            train_frame, validation_frame, governed_prior_evidence = (
                _apply_fold_local_governed_priors(
                    frame,
                    train_mask=train_mask,
                    validation_mask=validation_mask,
                    fold=fold,
                    feature_set=feature_set or {},
                )
            )
            selector = fold_local_selector or (feature_set or {}).get("foldLocalSelector")
            selection_evidence: dict[str, Any] | None = None
            if selector:
                if governed_prior_evidence.get("status") == "APPLIED":
                    raise Stage3ModelLaboratoryError(
                        "MODEL_LAB_PRIOR_SELECTOR_NOT_AUTHORIZED",
                        "Fold-local recursive selection over governed prior outputs requires a separately registered refinement authority.",
                        status_code=409,
                    )
                selected_features, preprocessor, estimator, train_values, transformation_groups, selection_evidence = _fold_local_recursive_selection(
                    train_frame[features],
                    train_labels,
                    feature_set=feature_set or {},
                    model_family=model_family,
                    seed=seed,
                    hyperparameters=hyperparameters,
                    selector=selector,
                    fold_number=int(fold["foldNumber"]),
                    native_workers=runtime_workers,
                    progress_callback=progress_callback,
                )
                fold_selection_evidence.append(selection_evidence)
                if progress_callback is not None:
                    progress_callback(
                        {
                            "state": "RUNNING",
                            "modelFamily": model_family,
                            "fold": int(fold["foldNumber"]),
                            "foldCount": len(contract_folds),
                            "event": "FOLD_ESTIMATOR_FIT_COMPLETED",
                        }
                    )
                validation_values = preprocessor.transform(
                    validation_frame[selected_features]
                )
                with threadpool_limits(limits=runtime_workers):
                    probabilities = _aligned_probabilities(estimator, validation_values)
            else:
                selected_features = features
                dense = model_family in {
                    "histogram_gradient_boosting",
                    "gaussian_naive_bayes",
                    "mlp",
                    "catboost",
                }
                preprocessor, transformation_groups = _preprocessor(
                    train_frame[features],
                    feature_set or {},
                    dense_categoricals=dense,
                )
                train_values = preprocessor.fit_transform(train_frame[features])
                validation_values = preprocessor.transform(validation_frame[features])
                estimator = _model(
                    model_family,
                    seed + int(fold["foldNumber"]),
                    hyperparameters=hyperparameters,
                    native_workers=runtime_workers,
                )
                # Keep native numerical libraries bounded and reproducible; HGB
                # otherwise chooses an environment-sized thread pool internally.
                with warnings.catch_warnings(record=True) as caught_warnings:
                    warnings.simplefilter("always", ConvergenceWarning)
                    with threadpool_limits(limits=runtime_workers):
                        estimator.fit(train_values, train_labels)
                fold_warnings = [
                    {
                        "code": item.category.__name__,
                        "message": str(item.message),
                    }
                    for item in caught_warnings
                    if issubclass(item.category, ConvergenceWarning)
                ]
                if progress_callback is not None:
                    progress_callback(
                        {
                            "state": "RUNNING",
                            "modelFamily": model_family,
                            "fold": int(fold["foldNumber"]),
                            "foldCount": len(contract_folds),
                            "event": "FOLD_ESTIMATOR_FIT_COMPLETED",
                        }
                    )
                with threadpool_limits(limits=runtime_workers):
                    probabilities = _aligned_probabilities(estimator, validation_values)
            complexity = _model_complexity(estimator, train_values)
            interpretability = _native_interpretability(estimator, preprocessor)
            numeric_medians: dict[str, float] = {}
            if transformation_groups["numeric"]:
                statistics = preprocessor.named_transformers_["numeric"].named_steps[
                    "imputer"
                ].statistics_
                numeric_medians = {
                    name: float(value)
                    for name, value in zip(
                        transformation_groups["numeric"], statistics, strict=True
                    )
                }
            binary_modes: dict[str, float] = {}
            if transformation_groups["binary_mode"]:
                statistics = preprocessor.named_transformers_["binary_mode"].named_steps[
                    "imputer"
                ].statistics_
                binary_modes = {
                    name: float(value)
                    for name, value in zip(
                        transformation_groups["binary_mode"], statistics, strict=True
                    )
                }
            categorical_levels: dict[str, list[str]] = {}
            if transformation_groups["categorical"]:
                fitted_encoder = preprocessor.named_transformers_[
                    "categorical"
                ].named_steps["encoder"]
                categorical_levels = {
                    name: [str(value) for value in levels.tolist()]
                    for name, levels in zip(
                        transformation_groups["categorical"],
                        fitted_encoder.categories_,
                        strict=True,
                    )
                }
            preprocessing_artifact = {
                "fold": int(fold["foldNumber"]),
                "featureSetId": (feature_set or {}).get("featureSetId"),
                "featureSetChecksum": (feature_set or {}).get("checksum"),
                "modelFamily": model_family,
                "selectedOrderedFeatures": selected_features,
                "fitRows": int(train_mask.sum()),
                "registeredOrderedTransformations": transformation_groups["ordered"],
                "numericFoldMedians": numeric_medians,
                "binaryPassthrough": transformation_groups["binary"],
                "binaryFoldModes": binary_modes,
                "binaryModeImputed": transformation_groups["binary_mode"],
                "categoricalLevelsIncludingUnknown": categorical_levels,
                "governedPrior": governed_prior_evidence,
            }
            preprocessing = {
                "kind": "FOLD_LOCAL_REGISTERED_TRANSFORMATION_CONTRACT",
                "fitRows": int(train_mask.sum()),
                "validationRowsUsedForParameters": 0,
                "finalOotRowsUsedForParameters": 0,
                "outlierTreatment": "RETAIN",
                "numericMissingTreatment": "TRAINING_FOLD_MEDIAN",
                "binaryTreatment": (
                    "REGISTERED_PASSTHROUGH_PLUS_TRAINING_FOLD_MODE"
                    if transformation_groups["binary"] and transformation_groups["binary_mode"]
                    else "TRAINING_FOLD_MODE"
                    if transformation_groups["binary_mode"]
                    else "REGISTERED_BINARY_PASSTHROUGH"
                ),
                "categoricalMissingTreatment": "CONSTANT_UNKNOWN_THEN_ONE_HOT",
                "registeredOrderedTransformations": transformation_groups["ordered"],
                "governedPriorTreatment": governed_prior_evidence,
                "artifactSha256": hashlib.sha256(
                    canonical_json_bytes(preprocessing_artifact)
                ).hexdigest(),
                "foldLocalSelection": selection_evidence if selector else None,
            }
        probabilities = _validate_probability_matrix(
            probabilities, expected_rows=int(validation_mask.sum())
        )
        metrics = _metrics(probabilities, validation_labels)
        fold_results.append(
            {
                "foldNumber": int(fold["foldNumber"]),
                "trainStart": fold["trainStart"],
                "trainEnd": fold["trainEnd"],
                "trainRows": int(train_mask.sum()),
                "trainGames": train_games,
                "validationStart": fold["validationStart"],
                "validationEnd": fold["validationEnd"],
                "validationRows": int(validation_mask.sum()),
                "validationGames": validation_games,
                "metrics": metrics,
                "probabilityReconciliation": _probability_reconciliation(
                    probabilities
                ),
                "preprocessing": preprocessing,
                "modelComplexity": complexity,
                "interpretabilityEvidence": interpretability,
                "warnings": fold_warnings,
                "runtimeMs": int((time.perf_counter() - fold_started) * 1000),
            }
        )
        all_probabilities.append(probabilities)
        all_labels.append(validation_labels)
        all_oof_keys.extend(
            frame.loc[validation_mask, "canonicalPaId"].astype(str).tolist()
        )
        all_oof_game_ids.extend(
            frame.loc[validation_mask, "canonicalGameId"].astype(str).tolist()
        )
        all_oof_fold_numbers.append(
            np.full(int(validation_mask.sum()), int(fold["foldNumber"]), dtype=np.int8)
        )
        if artifact_callback is not None:
            if model_family == "class_frequency_null":
                raise Stage3ModelLaboratoryError(
                    "MODEL_LAB_REFERENCE_ARTIFACT_UNSUPPORTED",
                    "The class-frequency reference has no executable fitted pipeline.",
                    status_code=409,
                )
            if governed_prior_evidence and governed_prior_evidence.get("status") == "APPLIED":
                raise Stage3ModelLaboratoryError(
                    "MODEL_LAB_PRIOR_ARTIFACT_EXPORT_NOT_AUTHORIZED",
                    "This Development-only competition does not authorize export of a scoring artifact with governed-prior state.",
                    status_code=409,
                )
            artifact_callback(
                {
                    "fold": dict(fold),
                    "validationMask": validation_mask.copy(),
                    "validationLabels": validation_labels.copy(),
                    "probabilities": probabilities.copy(),
                    "pipeline": Stage3FittedPipeline(
                        ordered_features=selected_features,
                        target_order=GOLD_CLASS_ORDER,
                        preprocessor=preprocessor,
                        estimator=estimator,
                    ),
                    "preprocessing": dict(preprocessing),
                    "metrics": dict(metrics),
                }
            )
        if progress_callback is not None:
            progress_callback(
                {
                    "state": "RUNNING",
                    "modelFamily": model_family,
                    "hyperparameters": dict(hyperparameters or _fixed_hyperparameters(model_family)),
                    "fold": int(fold["foldNumber"]),
                    "foldCount": len(contract_folds),
                    "event": "FOLD_COMPLETED",
                    "foldLogLoss": metrics["multiclassLogLoss"],
                }
            )
    stable_features = list(features)
    refinement_evidence: dict[str, Any] | None = None
    if fold_selection_evidence:
        retain_counts = {
            name: sum(name in set(item["retainedFeatures"]) for item in fold_selection_evidence)
            for name in features
        }
        mean_rank: dict[str, float] = {}
        for name in features:
            ranks = []
            for item in fold_selection_evidence:
                final_ranking = item["rounds"][-1].get("ranking") or []
                rank_by_name = {row["feature"]: index for index, row in enumerate(final_ranking)}
                ranks.append(float(rank_by_name.get(name, len(features))))
            mean_rank[name] = float(np.mean(ranks))
        target_count = int((fold_local_selector or (feature_set or {}).get("foldLocalSelector"))["minimumRetainedFeatures"])
        stable_features = sorted(
            features,
            key=lambda name: (-retain_counts[name], mean_rank[name], features.index(name)),
        )[:target_count]
        stable_set_payload = {
            "schemaVersion": "SPORTS_STAGE3_STABLE_REDUCED_FEATURE_SET_V1",
            "parentFeatureSetId": (feature_set or {}).get("parentFeatureSetId") or (feature_set or {}).get("featureSetId"),
            "selectorContractChecksum": (feature_set or {}).get("checksum"),
            "orderedFeatures": stable_features,
            "selectionRule": "RETENTION_FREQUENCY_THEN_MEAN_TRAINING_ONLY_RANK",
            "foldCount": len(fold_selection_evidence),
            "validationRowsUsedForSelection": 0,
            "finalOotTargetAccessed": False,
        }
        stable_checksum = hashlib.sha256(canonical_json_bytes(stable_set_payload)).hexdigest()
        refinement_evidence = {
            "status": "FOLD_LOCAL_SELECTION_COMPLETE",
            "method": (fold_local_selector or (feature_set or {}).get("foldLocalSelector"))["method"],
            "folds": fold_selection_evidence,
            "stabilityCounts": retain_counts,
            "stableRetainedFeatures": stable_features,
            "stableRemovedFeatures": [name for name in features if name not in set(stable_features)],
            "reducedFeatureSetId": f"stage3-stable-reduced-feature-set-{stable_checksum[:32]}",
            "reducedFeatureSetChecksum": stable_checksum,
            "validationRowsUsedForSelection": 0,
            "finalOotTargetAccessed": False,
        }
    combined_probabilities = np.vstack(all_probabilities)
    combined_labels = np.concatenate(all_labels)
    combined_fold_numbers = np.concatenate(all_oof_fold_numbers)
    combined = _metrics(combined_probabilities, combined_labels)
    oof_artifact = _persist_oof_predictions(
        canonical_pa_ids=all_oof_keys,
        canonical_game_ids=all_oof_game_ids,
        fold_numbers=combined_fold_numbers,
        labels=combined_labels,
        probabilities=combined_probabilities,
        model_family=model_family,
        feature_set_id=(feature_set or {}).get("featureSetId"),
        seed=seed,
    )
    candidate_warnings = [
        {
            "foldNumber": fold["foldNumber"],
            **warning,
        }
        for fold in fold_results
        for warning in fold.get("warnings") or []
    ]
    return {
        "candidateId": "stage3-candidate-" + uuid.uuid4().hex,
        "modelFamily": model_family,
        "hyperparameters": dict(hyperparameters or _fixed_hyperparameters(model_family)),
        "featureSetId": refinement_evidence["reducedFeatureSetId"] if refinement_evidence else (feature_set or {}).get("featureSetId"),
        "featureSetName": "Stable fold-local reduced challenger" if refinement_evidence else (feature_set or {}).get("name") or "Feature-independent null reference",
        "featureSetVersion": int((feature_set or {}).get("version") or 0) or None,
        "featureSetChecksum": refinement_evidence["reducedFeatureSetChecksum"] if refinement_evidence else (feature_set or {}).get("checksum"),
        "featureCount": len(stable_features),
        "sourceFeatureCount": len(features),
        "orderedFeatures": stable_features,
        "refinementEvidence": refinement_evidence,
        "status": "COMPLETE",
        "foldsCompleted": len(fold_results),
        "meanOofLogLoss": combined["multiclassLogLoss"],
        "summedBrier": combined["summedBrier"],
        "ece": combined["ece"],
        "accuracyDiagnostic": combined["accuracy"],
        "macroF1Diagnostic": combined["macroF1"],
        "macroOvrRocAuc": combined["macroOvrRocAuc"],
        "reliabilityBands": combined["reliabilityBands"],
        "classCalibration": combined["classCalibration"],
        "probabilityReconciliation": _probability_reconciliation(
            combined_probabilities
        ),
        "rareClassStability": {
            "class": combined["rareClass"]["class"],
            "totalOofSupport": combined["rareClass"]["support"],
            "oneVsRestBrier": combined["rareClass"]["oneVsRestBrier"],
            "foldSupports": [
                next(
                    item["support"]
                    for item in fold["metrics"]["classCalibration"]
                    if item["class"] == combined["rareClass"]["class"]
                )
                for fold in fold_results
            ],
        },
        "foldStability": {
            "logLossStdDev": float(
                np.std(
                    [fold["metrics"]["multiclassLogLoss"] for fold in fold_results],
                    ddof=0,
                )
            ),
            "minimumFoldLogLoss": float(
                min(fold["metrics"]["multiclassLogLoss"] for fold in fold_results)
            ),
            "maximumFoldLogLoss": float(
                max(fold["metrics"]["multiclassLogLoss"] for fold in fold_results)
            ),
        },
        "modelComplexity": fold_results[-1]["modelComplexity"],
        "interpretabilityEvidence": _interpretability_stability(fold_results),
        "evaluationEvidence": _evaluation_evidence(
            combined_probabilities,
            combined_labels,
            oof_artifact=oof_artifact,
        ),
        "warnings": candidate_warnings,
        "folds": fold_results,
        "runtimeMs": int((time.perf_counter() - started) * 1000),
        "memoryEvidence": {
            "atStart": memory_at_start,
            "atCompletion": _process_memory_evidence(),
            "candidateSpecificPeakAvailable": False,
            "limitation": (
                "The governed executor uses one local process; Windows exposes the "
                "process-lifetime peak rather than an isolated per-configuration peak."
            ),
        },
        "errorReason": None,
    }


def _environment_identity() -> dict[str, Any]:
    xgboost_version = None
    if importlib.util.find_spec("xgboost") is not None:
        try:
            import xgboost

            xgboost_version = xgboost.__version__
        except Exception:  # pragma: no cover - informational only
            xgboost_version = "AVAILABLE_VERSION_UNREADABLE"
    module_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikitLearn": sklearn_version,
        "xgboost": xgboost_version,
        "modelLabImplementationSha256": module_sha,
    }


def _persist_run(run: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(run)
    payload_sha = _sha(payload)
    root = _runtime_root()
    object_dir = root / "objects" / "sha256"
    object_dir.mkdir(parents=True, exist_ok=True)
    path = object_dir / f"{payload_sha}.json"
    serialized = canonical_json_bytes(payload)
    if path.exists():
        if path.read_bytes() != serialized:
            raise Stage3ModelLaboratoryError(
                "MODEL_LAB_RUN_OBJECT_COLLISION",
                "An immutable run object address contains different bytes.",
                status_code=409,
            )
    else:
        handle, temporary_name = tempfile.mkstemp(prefix="model-lab-run-", suffix=".tmp", dir=object_dir)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
    return {**payload, "runReceiptSha256": payload_sha}


def _receipt_matches_current_authority(
    data: Mapping[str, Any], resolved: ModelLabAuthority
) -> bool:
    identity = data.get("identity") or {}
    authority = resolved.eda_authority
    if not isinstance(identity, Mapping):
        return False
    expected = {
        "projectId": authority.project_id,
        "sourceDatasetId": authority.source_dataset_id,
        "sourceManifestSha": authority.source_manifest_sha,
        "goldDatasetId": CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": authority.gold_manifest_sha,
        "contextualManifestSha": authority.contextual_manifest_sha,
        "authorityKey": resolved.authority_key,
        "splitContractId": resolved.split["contractId"],
        "splitVersion": int(resolved.split["contractVersion"]),
        "splitChecksum": resolved.split["checksum"],
        "outlierPolicyId": resolved.outlier_policy["policyId"],
        "outlierPolicyVersion": int(resolved.outlier_policy["policyVersion"]),
        "outlierPolicyChecksum": resolved.outlier_policy["checksum"],
        "missingPolicyId": resolved.missing_policy["policyId"],
        "missingPolicyVersion": int(resolved.missing_policy["policyVersion"]),
        "missingPolicyChecksum": resolved.missing_policy["checksum"],
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        return False
    if list(identity.get("targetOrder") or []) != list(GOLD_CLASS_ORDER):
        return False
    feature_ids = set(identity.get("featureSetIds") or [])
    if data.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION:
        return feature_ids.issubset({str(item["featureSetId"]) for item in resolved.feature_sets})
    if data.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION_V2:
        eligibility = build_model_eligibility(resolved)
        if (
            identity.get("featureUniverseId") != eligibility["featureSetId"]
            or identity.get("featureUniverseChecksum") != eligibility["checksum"]
            or (data.get("population") or {}).get("finalOotTargetAccessed") is not False
            or (data.get("population") or {}).get("finalOotScored") is not False
            or data.get("finalOotAccessed") is not False
            or data.get("finalOotTargetsMaterialized") is not False
            or data.get("autoPromoted") is not False
            or data.get("promotionStatus") != "NOT_PROMOTED"
            or data.get("providerCalls") != 0
            or data.get("legacyGlobalMatrixUsed") is not False
        ):
            return False
        allowed = {str(item["featureSetId"]) for item in resolved.feature_sets} | {eligibility["featureSetId"]}
        return all(
            item in allowed
            or str(item).startswith("stage3-custom-modeling-subset-")
            or str(item).startswith("stage3-stable-reduced-feature-set-")
            for item in feature_ids
        )
    return False


def _read_runs(
    project_id: str, resolved: ModelLabAuthority
) -> list[dict[str, Any]]:
    object_dir = _runtime_root() / "objects" / "sha256"
    if not object_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in object_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            data.get("schemaVersion")
            in {RUN_RECEIPT_SCHEMA_VERSION, RUN_RECEIPT_SCHEMA_VERSION_V2}
            and (data.get("identity") or {}).get("projectId") == project_id
            and _receipt_matches_current_authority(data, resolved)
            and hashlib.sha256(canonical_json_bytes(data)).hexdigest() == path.stem
        ):
            rows.append({**data, "runReceiptSha256": path.stem})
    rows.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return rows


def _latest_run(
    project_id: str, resolved: ModelLabAuthority
) -> dict[str, Any] | None:
    rows = _read_runs(project_id, resolved)
    return rows[0] if rows else None


def list_model_laboratory_runs(database: Database, project_id: str) -> dict[str, Any]:
    # Resolve current authority first so stale/foreign project requests cannot
    # use the object directory as a side channel.
    resolved = resolve_model_lab_authority(database, project_id)
    return {"ok": True, "runs": _read_runs(project_id, resolved)}


def run_model_laboratory(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_RUN_REQUEST_INVALID", "The run request must be an object."
        )
    forbidden = {
        "finalOot",
        "finalOotTarget",
        "holdout",
        "randomSplit",
        "globalMatrix",
        "base22",
        "promote",
        "champion",
        "calibrateOnOot",
    }
    present = sorted(forbidden & set(payload))
    if present:
        raise Stage3ModelLaboratoryError(
            "MODEL_LAB_FORBIDDEN_RUN_OPTION",
            "Forbidden run options were supplied: " + ", ".join(present),
        )
    resolved = resolve_model_lab_authority(database, project_id)
    require_model_execution_authority(database, resolved, actor_user_id)
    requested, seed = _validate_run_request(resolved, payload)
    feature_by_id = {
        str(item.get("featureSetId")): item for item in resolved.feature_sets
    }
    required_features = list(
        dict.fromkeys(
            feature
            for candidate in requested
            if candidate["modelFamily"] != "class_frequency_null"
            for feature in feature_by_id[candidate["featureSetId"]].get("orderedFeatures") or []
        )
    )
    frame = _fold_frame(resolved, required_features, include_oof_identity=True)
    candidates: list[dict[str, Any]] = []
    run_started = time.perf_counter()
    for item in requested:
        feature_set = (
            None
            if item["modelFamily"] == "class_frequency_null"
            else feature_by_id[item["featureSetId"]]
        )
        try:
            result = _evaluate_candidate(
                frame,
                model_family=item["modelFamily"],
                feature_set=feature_set,
                split=resolved.split,
                seed=seed,
            )
        except Stage3ModelLaboratoryError as exc:
            result = {
                "candidateId": "stage3-candidate-" + uuid.uuid4().hex,
                "modelFamily": item["modelFamily"],
                "hyperparameters": _fixed_hyperparameters(item["modelFamily"]),
                "featureSetId": item["featureSetId"] or None,
                "featureSetName": (feature_set or {}).get("name") or "Feature-independent null reference",
                "featureSetVersion": int((feature_set or {}).get("version") or 0) or None,
                "featureSetChecksum": (feature_set or {}).get("checksum"),
                "featureCount": len((feature_set or {}).get("orderedFeatures") or []),
                "status": "FAILED",
                "foldsCompleted": 0,
                "meanOofLogLoss": None,
                "summedBrier": None,
                "ece": None,
                "accuracyDiagnostic": None,
                "folds": [],
                "runtimeMs": 0,
                "errorCode": exc.code,
                "errorReason": str(exc),
            }
        except Exception as exc:  # one failed estimator must not erase sibling evidence
            result = {
                "candidateId": "stage3-candidate-" + uuid.uuid4().hex,
                "modelFamily": item["modelFamily"],
                "hyperparameters": _fixed_hyperparameters(item["modelFamily"]),
                "featureSetId": item["featureSetId"] or None,
                "featureSetName": (feature_set or {}).get("name") or "Feature-independent null reference",
                "featureSetVersion": int((feature_set or {}).get("version") or 0) or None,
                "featureSetChecksum": (feature_set or {}).get("checksum"),
                "featureCount": len((feature_set or {}).get("orderedFeatures") or []),
                "status": "FAILED",
                "foldsCompleted": 0,
                "meanOofLogLoss": None,
                "summedBrier": None,
                "ece": None,
                "accuracyDiagnostic": None,
                "folds": [],
                "runtimeMs": 0,
                "errorCode": "MODEL_LAB_CANDIDATE_EXECUTION_FAILED",
                "errorReason": str(exc),
            }
        candidates.append(result)
    completed = [item for item in candidates if item["status"] == "COMPLETE"]
    run = {
        "schemaVersion": RUN_RECEIPT_SCHEMA_VERSION,
        "runId": "stage3-model-lab-run-" + uuid.uuid4().hex,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "status": "COMPLETE" if len(completed) == len(candidates) else "PARTIAL",
        "identity": {
            "projectId": project_id,
            "projectName": resolved.project_name,
            "registrationId": resolved.eda_authority.registration_id,
            "datasetVersionId": resolved.eda_authority.dataset_version_id,
            "sourceDatasetId": resolved.eda_authority.source_dataset_id,
            "sourceManifestSha": resolved.eda_authority.source_manifest_sha,
            "goldDatasetId": CURRENT_GOLD_DATASET_ID,
            "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
            "contextualManifestSha": resolved.eda_authority.contextual_manifest_sha,
            "authorityKey": resolved.authority_key,
            "splitContractId": resolved.split["contractId"],
            "splitVersion": int(resolved.split["contractVersion"]),
            "splitChecksum": resolved.split["checksum"],
            "outlierPolicyId": resolved.outlier_policy["policyId"],
            "outlierPolicyVersion": int(resolved.outlier_policy["policyVersion"]),
            "outlierPolicyChecksum": resolved.outlier_policy["checksum"],
            "missingPolicyId": resolved.missing_policy["policyId"],
            "missingPolicyVersion": int(resolved.missing_policy["policyVersion"]),
            "missingPolicyChecksum": resolved.missing_policy["checksum"],
            "featureSetIds": sorted(
                {
                    str(item["featureSetId"])
                    for item in candidates
                    if item.get("featureSetId")
                }
            ),
            "candidateSpecifications": [
                {
                    "modelFamily": item["modelFamily"],
                    "featureSetId": item.get("featureSetId"),
                    "featureSetChecksum": item.get("featureSetChecksum"),
                    "hyperparameters": dict(item.get("hyperparameters") or {}),
                }
                for item in candidates
            ],
            "targetOrder": list(GOLD_CLASS_ORDER),
            "seed": seed,
        },
        "population": {
            "scope": "DEVELOPMENT_ONLY",
            "rows": len(frame),
            "startDate": str(resolved.split["development"]["startDate"]),
            "endDate": str(resolved.split["development"]["endDate"]),
            "foldCount": 5,
            "finalOotRows": int(resolved.split["finalOot"]["rows"]),
            "finalOotLocked": True,
            "finalOotTargetAccessed": False,
            "finalOotScored": False,
        },
        "environment": _environment_identity(),
        "candidates": candidates,
        "runtimeMs": int((time.perf_counter() - run_started) * 1000),
        "rankingMetric": "MULTICLASS_LOG_LOSS",
        "autoPromoted": False,
        "promotionStatus": "NOT_PROMOTED",
        "finalOotAccessed": False,
        "finalOotTargetsMaterialized": False,
        "legacyGlobalMatrixUsed": False,
        "providerCalls": 0,
    }
    persisted = _persist_run(run)
    return {"ok": True, "run": persisted}


__all__ = [
    "Stage3FittedPipeline",
    "Stage3ModelLaboratoryError",
    "fit_stage3_pipeline",
    "list_model_laboratory_runs",
    "model_laboratory_summary",
    "resolve_model_lab_authority",
    "run_model_laboratory",
]

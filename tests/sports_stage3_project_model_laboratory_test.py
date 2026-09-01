from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from server.persistence.db import Database
from server.persistence import persistence_router
from server.sports_current_statcast import stage3_model_laboratory as lab


PROJECT_ID = lab.EXPECTED_PROJECT_ID


def test_model_laboratory_routes_require_authenticated_users() -> None:
    routes = {route.path: route for route in persistence_router.router.routes}
    for method, path in (
        ("GET", "/projects/{project_id}/sports/stage3-model-laboratory/summary"),
        ("GET", "/projects/{project_id}/sports/stage3-model-laboratory/runs"),
        ("POST", "/projects/{project_id}/sports/stage3-model-laboratory/run"),
    ):
        route = routes[path]
        assert method in route.methods
        assert any(
            dependency.call is persistence_router.require_user
            for dependency in route.dependant.dependencies
        )


def _authority() -> SimpleNamespace:
    public = {
        "projectId": PROJECT_ID,
        "sourceDatasetId": lab.EXPECTED_SOURCE_DATASET_ID,
        "sourceManifestSha": "1" * 64,
        "goldDatasetId": lab.CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": lab.EXPECTED_GOLD_MANIFEST_SHA,
        "contextualDatasetId": "gold-table:gold_mlb_current_pa_context_v2",
        "contextualManifestSha": "3" * 64,
        "reviewDigest": "4" * 64,
    }
    return SimpleNamespace(
        project_id=PROJECT_ID,
        registration_id="registration-current",
        dataset_version_id="current-pa-version",
        activation_revision=7,
        source_dataset_id=lab.EXPECTED_SOURCE_DATASET_ID,
        source_manifest_sha=public["sourceManifestSha"],
        gold_manifest_sha=lab.EXPECTED_GOLD_MANIFEST_SHA,
        contextual_manifest_sha=public["contextualManifestSha"],
        review_digest=public["reviewDigest"],
        schema=pa.schema(
            [
                pa.field("feature_numeric", pa.float64()),
                pa.field("feature_category", pa.string()),
                pa.field("game_date", pa.string()),
                pa.field("outcome", pa.string()),
                pa.field("canonicalGameId", pa.string()),
            ]
        ),
        public=lambda: dict(public),
    )


def _policy(authority: SimpleNamespace, kind: str, expected: dict[str, object]) -> dict[str, object]:
    return {
        "policyId": expected["policyId"],
        "projectId": PROJECT_ID,
        "policyKind": kind,
        "policyVersion": expected["policyVersion"],
        "status": "ADOPTED",
        "authorityReviewDigest": authority.review_digest,
        "goldManifestSha": authority.gold_manifest_sha,
        "development": {
            "startDate": lab.EXPECTED_DEVELOPMENT[0],
            "endDate": lab.EXPECTED_DEVELOPMENT[1],
            "rows": lab.EXPECTED_DEVELOPMENT[2],
        },
        "finalOot": {
            "startDate": lab.EXPECTED_FINAL_OOT[0],
            "endDate": lab.EXPECTED_FINAL_OOT[1],
            "rows": lab.EXPECTED_FINAL_OOT[2],
            "locked": True,
        },
        "globalMethod": "IQR_1_5" if kind == "OUTLIER" else "DATA_TYPE_AWARE",
        "policy": {
            "globalTreatment": "RETAIN",
            "sourceFailureDefault": "REVIEW_REQUIRED",
        },
        "fittingRule": {
            "fitScope": "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY",
            "validationTransform": "PARAMETERS_FROM_CORRESPONDING_TRAINING_FOLD_ONLY",
            "finalOotParameterFittingProhibited": True,
            "targetOutcomeInputsProhibited": True,
        },
        "checksum": expected["checksum"],
    }


def _feature_set(authority: SimpleNamespace, feature_set_id: str, index: int) -> dict[str, object]:
    return {
        "featureSetId": feature_set_id,
        "projectId": PROJECT_ID,
        "featureSetKey": ["BASELINE_CORE_48", "CORE_PLUS_CALENDAR", "CORE_PLUS_REST_TRAVEL"][index],
        "name": ["A CORE_GOLD_48", "B CORE_PLUS_CALENDAR", "C CORE_PLUS_REST_TRAVEL"][index],
        "version": 2,
        "status": "REGISTERED",
        "authority": {
            "goldManifestSha": authority.gold_manifest_sha,
            "reviewDigest": authority.review_digest,
        },
        "development": {"rows": lab.EXPECTED_DEVELOPMENT[2]},
        "finalOot": {"rows": lab.EXPECTED_FINAL_OOT[2], "locked": True},
        "orderedFeatures": ["feature_numeric", "feature_category"],
        "transformationContracts": {
            "ordered": [
                {"feature": "feature_numeric", "steps": ["RETAIN_RAW"]},
                {
                    "feature": "feature_category",
                    "steps": ["CATEGORICAL_UNKNOWN", "ONE_HOT"],
                },
            ]
        },
        "unavailableExclusions": [],
        "treatmentPolicies": {
            "outlier": {"policyId": lab.EXPECTED_OUTLIER_POLICY["policyId"]},
            "missing": {"policyId": lab.EXPECTED_MISSING_POLICY["policyId"]},
        },
        "checksum": str(index + 5) * 64,
    }


def _split(authority: SimpleNamespace) -> dict[str, object]:
    folds = [
        {
            "foldNumber": row[0],
            "trainStart": row[1],
            "trainEnd": row[2],
            "trainRows": row[3],
            "trainGames": row[4],
            "validationStart": row[5],
            "validationEnd": row[6],
            "validationRows": row[7],
            "validationGames": row[8],
        }
        for row in lab.EXPECTED_FOLDS
    ]
    return {
        "contractId": lab.EXPECTED_SPLIT["splitContractId"],
        "projectId": PROJECT_ID,
        "contractVersion": lab.EXPECTED_SPLIT["version"],
        "status": "REGISTERED",
        "goldManifestSha": authority.gold_manifest_sha,
        "authorityReviewDigest": authority.review_digest,
        "development": {"rows": lab.EXPECTED_DEVELOPMENT[2]},
        "finalOot": {"rows": lab.EXPECTED_FINAL_OOT[2], "locked": True},
        "foldCount": 5,
        "selectedFeatureSetIds": list(lab.EXPECTED_FEATURE_SET_IDS),
        "checksum": lab.EXPECTED_SPLIT["checksum"],
        "contract": {
            "folds": folds,
            "preprocessingScope": "FIT_INSIDE_EACH_TRAINING_FOLD_ONLY",
            "allBlockingGatesPass": True,
            "qualityGates": [{"code": "FINAL_OOT_EXCLUDED", "status": "PASS", "blocking": True}],
            "groupingUnit": "CANONICAL_GAME",
            "dateAtomic": True,
        },
    }


@pytest.fixture()
def resolved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Database, lab.ModelLabAuthority]:
    authority = _authority()
    outlier = _policy(authority, "OUTLIER", lab.EXPECTED_OUTLIER_POLICY)
    missing = _policy(authority, "IMPUTATION", lab.EXPECTED_MISSING_POLICY)
    # Later records intentionally precede v2.  Exact-ID resolution must not
    # substitute either a draft v3 or a semantically-equal later adoption.
    later_outlier = {
        **outlier,
        "policyId": "stage3-outlier-policy-later-v5",
        "policyVersion": 5,
    }
    draft_v3 = {
        **outlier,
        "policyId": "stage3-outlier-policy-draft-v3",
        "policyVersion": 3,
        "status": "DRAFT",
        "policy": {"globalTreatment": "CAP_IQR"},
    }
    feature_sets = [
        _feature_set(authority, feature_set_id, index)
        for index, feature_set_id in enumerate(lab.EXPECTED_FEATURE_SET_IDS)
    ]
    split = _split(authority)

    class Projects:
        def __init__(self, _database: Database) -> None:
            pass

        def get(self, project_id: str) -> dict[str, str] | None:
            return {"project_id": project_id, "project_name": "MLB Current Challenger"}

    class Policies:
        def __init__(self, _database: Database) -> None:
            pass

        def list_versions(self, _project: str, kind: str, _digest: str) -> list[dict[str, object]]:
            return [later_outlier, draft_v3, outlier] if kind == "OUTLIER" else [missing]

    class Features:
        def __init__(self, _database: Database) -> None:
            pass

        def list_versions(self, _project: str, _digest: str) -> list[dict[str, object]]:
            return feature_sets

    class Splits:
        def __init__(self, _database: Database) -> None:
            pass

        def get(self, contract_id: str) -> dict[str, object] | None:
            return split if contract_id == split["contractId"] else None

    monkeypatch.setattr(lab.eda, "_resolve_authority", lambda *_args: authority)
    monkeypatch.setattr(lab, "ProjectRepository", Projects)
    monkeypatch.setattr(lab, "Stage3TreatmentRepository", Policies)
    monkeypatch.setattr(lab, "Stage3FeatureSetRepository", Features)
    monkeypatch.setattr(lab, "Stage3SplitContractRepository", Splits)
    monkeypatch.setattr(lab, "_runtime_root", lambda: tmp_path / "runs")
    database = Database(tmp_path / "unused.db")
    current = lab.resolve_model_lab_authority(database, PROJECT_ID)
    return database, current


def test_summary_uses_exact_stage3_authorities_and_does_not_fit_or_open_oot(
    resolved: tuple[Database, lab.ModelLabAuthority], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, _current = resolved
    monkeypatch.setattr(
        lab.eda,
        "_scan",
        lambda *_args, **_kwargs: pytest.fail("opening Model Laboratory must not scan or fit"),
    )
    summary = lab.model_laboratory_summary(database, PROJECT_ID)
    assert summary["authority"]["goldManifestSha"] == lab.EXPECTED_GOLD_MANIFEST_SHA
    assert summary["authority"]["legacyGlobalMatrixUsed"] is False
    assert summary["population"] == {
        "scope": "DEVELOPMENT_ONLY",
        "developmentRows": 683_662,
        "startDate": "2023-03-30",
        "endDate": "2026-08-13",
        "finalOotRows": 14_067,
        "finalOotStartDate": "2026-08-14",
        "finalOotEndDate": "2026-08-27",
        "finalOotLocked": True,
        "finalOotTargetsMaterialized": False,
    }
    assert summary["policies"]["outlier"]["policyId"] == lab.EXPECTED_OUTLIER_POLICY["policyId"]
    assert summary["policies"]["outlier"]["version"] == 2
    assert summary["policies"]["draftOutlierPoliciesUsed"] is False
    assert summary["policies"]["missing"]["policyId"] == lab.EXPECTED_MISSING_POLICY["policyId"]
    assert [item["featureSetId"] for item in summary["featureSets"]] == list(lab.EXPECTED_FEATURE_SET_IDS)
    assert summary["split"]["splitContractId"] == lab.EXPECTED_SPLIT["splitContractId"]
    assert summary["split"]["foldCount"] == 5
    assert summary["split"]["folds"][0]["trainRows"] == lab.EXPECTED_FOLDS[0][3]
    assert "trainingRows" not in summary["split"]["folds"][0]
    assert len(summary["candidateMatrix"]) == (10 if summary["modelFamilies"][-1]["available"] else 7)
    null = summary["candidateMatrix"][0]
    assert null["modelFamily"] == "class_frequency_null"
    assert null["featureSetId"] is None
    assert summary["audit"]["base22FallbackAvailable"] is False
    assert summary["audit"]["autoPromotion"] is False


def test_run_request_is_exact_and_null_is_feature_independent(
    resolved: tuple[Database, lab.ModelLabAuthority]
) -> None:
    _database, current = resolved
    base = {
        "authorityKey": current.authority_key,
        "splitContractId": lab.EXPECTED_SPLIT["splitContractId"],
        "outlierPolicyId": lab.EXPECTED_OUTLIER_POLICY["policyId"],
        "missingPolicyId": lab.EXPECTED_MISSING_POLICY["policyId"],
        "candidates": [{"modelFamily": "class_frequency_null", "featureSetId": None}],
    }
    requested, seed = lab._validate_run_request(current, base)
    assert requested == [{"modelFamily": "class_frequency_null", "featureSetId": ""}]
    assert seed == lab.DEFAULT_SEED
    with pytest.raises(lab.Stage3ModelLaboratoryError) as bound_null:
        lab._validate_run_request(
            current,
            {
                **base,
                "candidates": [
                    {
                        "modelFamily": "class_frequency_null",
                        "featureSetId": lab.EXPECTED_FEATURE_SET_IDS[0],
                    }
                ],
            },
        )
    assert bound_null.value.code == "MODEL_LAB_NULL_FEATURE_SET_PROHIBITED"
    with pytest.raises(lab.Stage3ModelLaboratoryError) as fallback:
        lab._validate_run_request(
            current,
            {
                **base,
                "candidates": [
                    {"modelFamily": "multinomial_logistic", "featureSetId": "BASE_22"}
                ],
            },
        )
    assert fallback.value.code == "MODEL_LAB_FEATURE_SET_IDENTITY_INVALID"


def test_xgboost_absence_is_reported_without_dependency_or_candidate_fallback(
    resolved: tuple[Database, lab.ModelLabAuthority], monkeypatch: pytest.MonkeyPatch
) -> None:
    _database, current = resolved
    real_find_spec = lab.importlib.util.find_spec
    monkeypatch.setattr(
        lab.importlib.util,
        "find_spec",
        lambda name: None if name == "xgboost" else real_find_spec(name),
    )
    with pytest.raises(lab.Stage3ModelLaboratoryError) as caught:
        lab._validate_run_request(
            current,
            {
                "authorityKey": current.authority_key,
                "splitContractId": lab.EXPECTED_SPLIT["splitContractId"],
                "outlierPolicyId": lab.EXPECTED_OUTLIER_POLICY["policyId"],
                "missingPolicyId": lab.EXPECTED_MISSING_POLICY["policyId"],
                "candidates": [
                    {
                        "modelFamily": "xgboost",
                        "featureSetId": lab.EXPECTED_FEATURE_SET_IDS[0],
                    }
                ],
            },
        )
    assert caught.value.code == "MODEL_LAB_MODEL_FAMILY_UNAVAILABLE"


def _small_frame_and_split() -> tuple[pd.DataFrame, dict[str, object]]:
    dates = pd.date_range("2024-01-01", periods=6, freq="D").strftime("%Y-%m-%d").tolist()
    rows: list[dict[str, object]] = []
    for date_index, game_date in enumerate(dates):
        for class_index, outcome in enumerate(lab.GOLD_CLASS_ORDER):
            rows.append(
                {
                    "game_date": game_date,
                    "canonicalGameId": f"game-{date_index}",
                    "outcome": outcome,
                    "feature_numeric": float(class_index + date_index),
                    "feature_category": "EVEN" if class_index % 2 == 0 else "ODD",
                }
            )
    frame = pd.DataFrame(rows)
    folds = []
    for index in range(1, 6):
        folds.append(
            {
                "foldNumber": index,
                "trainStart": dates[0],
                "trainEnd": dates[index - 1],
                "trainRows": 8 * index,
                "trainGames": index,
                "validationStart": dates[index],
                "validationEnd": dates[index],
                "validationRows": 8,
                "validationGames": 1,
            }
        )
    return frame, {"contract": {"folds": folds}}


@pytest.mark.parametrize(
    "family",
    ["class_frequency_null", "multinomial_logistic", "histogram_gradient_boosting"],
)
def test_null_logistic_and_hgb_run_all_five_folds_with_fold_local_preprocessing(
    family: str,
) -> None:
    frame, split = _small_frame_and_split()
    feature_set = None if family == "class_frequency_null" else {
        "featureSetId": lab.EXPECTED_FEATURE_SET_IDS[0],
        "name": "A CORE_GOLD_48",
        "version": 2,
        "checksum": "5" * 64,
        "orderedFeatures": ["feature_numeric", "feature_category"],
        "transformationContracts": {
            "ordered": [
                {"feature": "feature_numeric", "steps": ["RETAIN_RAW"]},
                {
                    "feature": "feature_category",
                    "steps": ["CATEGORICAL_UNKNOWN", "ONE_HOT"],
                },
            ]
        },
    }
    result = lab._evaluate_candidate(
        frame,
        model_family=family,
        feature_set=feature_set,
        split=split,
        seed=731_026,
    )
    assert result["status"] == "COMPLETE"
    assert result["foldsCompleted"] == 5
    assert np.isfinite(result["meanOofLogLoss"])
    assert np.isfinite(result["summedBrier"])
    assert len(result["classCalibration"]) == 8
    assert result["rareClassStability"]["totalOofSupport"] == 5
    assert result["modelComplexity"]["parameterCount"] is not None or family == "histogram_gradient_boosting"
    assert all(fold["preprocessing"]["validationRowsUsedForParameters"] == 0 for fold in result["folds"])
    assert all(fold["preprocessing"]["finalOotRowsUsedForParameters"] == 0 for fold in result["folds"])
    if family != "class_frequency_null":
        assert all(
            fold["preprocessing"]["kind"]
            == "FOLD_LOCAL_REGISTERED_TRANSFORMATION_CONTRACT"
            for fold in result["folds"]
        )
        assert all(
            fold["preprocessing"]["categoricalMissingTreatment"]
            == "CONSTANT_UNKNOWN_THEN_ONE_HOT"
            for fold in result["folds"]
        )


def test_registered_categorical_contract_maps_null_and_fold_unseen_to_unknown() -> None:
    training = pd.DataFrame(
        {
            "holiday_name": ["CHRISTMAS", None, "CHRISTMAS"],
            "feature_numeric": [1.0, np.nan, 3.0],
        }
    )
    feature_set = {
        "featureSetId": lab.EXPECTED_FEATURE_SET_IDS[1],
        "orderedFeatures": ["feature_numeric", "holiday_name"],
        "transformationContracts": {
            "ordered": [
                {"feature": "feature_numeric", "steps": ["RETAIN_RAW"]},
                {
                    "feature": "holiday_name",
                    "steps": ["CATEGORICAL_UNKNOWN", "ONE_HOT"],
                },
            ]
        },
    }
    preprocessor, groups = lab._preprocessor(
        training, feature_set, dense_categoricals=True
    )
    preprocessor.fit(training)
    validation = pd.DataFrame(
        {
            "holiday_name": ["UNSEEN_HOLIDAY", None],
            "feature_numeric": [4.0, 5.0],
        }
    )
    transformed = np.asarray(preprocessor.transform(validation), dtype=float)
    names = preprocessor.get_feature_names_out().tolist()
    unknown_index = names.index("categorical__holiday_name_UNKNOWN")
    categorical_indices = [
        index for index, name in enumerate(names) if name.startswith("categorical__")
    ]
    assert groups["categorical"] == ["holiday_name"]
    assert transformed[:, unknown_index].tolist() == [1.0, 1.0]
    assert transformed[:, categorical_indices].sum(axis=1).tolist() == [1.0, 1.0]


def test_registered_binary_passthrough_is_not_imputed_or_one_hot_encoded() -> None:
    training = pd.DataFrame({"is_home": [0, 1, 1], "feature_numeric": [1.0, 2.0, 3.0]})
    feature_set = {
        "featureSetId": lab.EXPECTED_FEATURE_SET_IDS[0],
        "orderedFeatures": ["feature_numeric", "is_home"],
        "transformationContracts": {
            "ordered": [
                {"feature": "feature_numeric", "steps": ["RETAIN_RAW"]},
                {"feature": "is_home", "steps": ["BINARY_PASSTHROUGH"]},
            ]
        },
    }
    preprocessor, groups = lab._preprocessor(
        training, feature_set, dense_categoricals=True
    )
    transformed = np.asarray(preprocessor.fit_transform(training), dtype=float)
    assert groups["binary"] == ["is_home"]
    assert preprocessor.get_feature_names_out().tolist()[-1] == "binary__is_home"
    assert transformed[:, -1].tolist() == [0.0, 1.0, 1.0]
    with pytest.raises(lab.Stage3ModelLaboratoryError) as caught:
        lab._preprocessor(
            training.assign(is_home=[0.0, np.nan, 1.0]),
            feature_set,
            dense_categoricals=True,
        )
    assert caught.value.code == "MODEL_LAB_BINARY_PASSTHROUGH_MISSING"


def test_hgb_disables_internal_random_early_stopping_split() -> None:
    estimator = lab._model("histogram_gradient_boosting", 42)
    assert estimator.early_stopping is False
    declared = next(
        item
        for item in lab._model_families()
        if item["id"] == "histogram_gradient_boosting"
    )
    assert declared["hyperparameters"]["earlyStopping"] is False


def test_source_unavailable_column_fails_instead_of_becoming_zero() -> None:
    frame, split = _small_frame_and_split()
    frame["unavailable"] = np.nan
    with pytest.raises(lab.Stage3ModelLaboratoryError) as caught:
        lab._evaluate_candidate(
            frame,
            model_family="multinomial_logistic",
            feature_set={
                "featureSetId": lab.EXPECTED_FEATURE_SET_IDS[0],
                "name": "A",
                "version": 2,
                "checksum": "5" * 64,
                "orderedFeatures": ["unavailable"],
                "transformationContracts": {
                    "ordered": [
                        {"feature": "unavailable", "steps": ["RETAIN_RAW"]}
                    ]
                },
            },
            split=split,
            seed=1,
        )
    assert caught.value.code == "MODEL_LAB_SOURCE_UNAVAILABLE_FEATURE"


def test_run_receipt_echoes_exact_identity_and_never_promotes_or_opens_oot(
    resolved: tuple[Database, lab.ModelLabAuthority], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, current = resolved
    frame, _split_value = _small_frame_and_split()
    monkeypatch.setattr(lab, "_fold_frame", lambda *_args, **_kwargs: frame)

    def candidate(*_args, model_family: str, feature_set: object, **_kwargs) -> dict[str, object]:
        return {
            "candidateId": "candidate-null",
            "modelFamily": model_family,
            "hyperparameters": {},
            "featureSetId": None,
            "featureSetName": "Feature-independent null reference",
            "featureSetVersion": None,
            "featureSetChecksum": None,
            "featureCount": 0,
            "status": "COMPLETE",
            "foldsCompleted": 5,
            "meanOofLogLoss": 2.0,
            "summedBrier": 0.8,
            "ece": 0.01,
            "accuracyDiagnostic": 0.2,
            "folds": [],
            "runtimeMs": 1,
            "errorReason": None,
        }

    monkeypatch.setattr(lab, "_evaluate_candidate", candidate)
    response = lab.run_model_laboratory(
        database,
        PROJECT_ID,
        {
            "authorityKey": current.authority_key,
            "splitContractId": lab.EXPECTED_SPLIT["splitContractId"],
            "outlierPolicyId": lab.EXPECTED_OUTLIER_POLICY["policyId"],
            "missingPolicyId": lab.EXPECTED_MISSING_POLICY["policyId"],
            "candidates": [{"modelFamily": "class_frequency_null", "featureSetId": None}],
            "seed": 99,
        },
        actor_user_id="scientist-1",
    )
    run = response["run"]
    assert run["identity"]["projectId"] == PROJECT_ID
    assert run["identity"]["goldManifestSha"] == lab.EXPECTED_GOLD_MANIFEST_SHA
    assert run["identity"]["splitContractId"] == lab.EXPECTED_SPLIT["splitContractId"]
    assert run["identity"]["outlierPolicyId"] == lab.EXPECTED_OUTLIER_POLICY["policyId"]
    assert run["identity"]["missingPolicyId"] == lab.EXPECTED_MISSING_POLICY["policyId"]
    assert run["identity"]["candidateSpecifications"] == [
        {
            "modelFamily": "class_frequency_null",
            "featureSetId": None,
            "featureSetChecksum": None,
            "hyperparameters": {},
        }
    ]
    assert run["autoPromoted"] is False
    assert run["promotionStatus"] == "NOT_PROMOTED"
    assert run["finalOotAccessed"] is False
    assert run["finalOotTargetsMaterialized"] is False
    assert run["population"]["finalOotTargetAccessed"] is False
    assert run["legacyGlobalMatrixUsed"] is False
    assert len(run["runReceiptSha256"]) == 64
    listed = lab.list_model_laboratory_runs(database, PROJECT_ID)
    assert listed["runs"][0]["runReceiptSha256"] == run["runReceiptSha256"]

    # A valid content-addressed receipt from a superseded authority must not
    # appear as the current project's latest run merely because projectId is
    # unchanged.
    stale = deepcopy({key: value for key, value in run.items() if key != "runReceiptSha256"})
    stale["runId"] = "stage3-model-lab-run-stale-authority"
    stale["createdAt"] = "2099-01-01T00:00:00Z"
    stale["identity"]["authorityKey"] = "superseded-authority"
    stale_receipt = lab._persist_run(stale)
    assert stale_receipt["runReceiptSha256"] != run["runReceiptSha256"]
    listed_after_stale = lab.list_model_laboratory_runs(database, PROJECT_ID)
    assert [item["runId"] for item in listed_after_stale["runs"]] == [run["runId"]]
    assert lab.model_laboratory_summary(database, PROJECT_ID)["latestRun"]["runId"] == run["runId"]


def test_final_oot_target_is_filtered_before_materialization(
    resolved: tuple[Database, lab.ModelLabAuthority], monkeypatch: pytest.MonkeyPatch
) -> None:
    _database, current = resolved
    source = pd.DataFrame(
        [
            {
                "game_date": "2026-08-13",
                "outcome": lab.GOLD_CLASS_ORDER[0],
                "canonicalGameId": "dev-game",
                "feature_numeric": 1.0,
            },
            {
                "game_date": "2026-08-14",
                "outcome": "FINAL_OOT_POISON",
                "canonicalGameId": "oot-game",
                "feature_numeric": 2.0,
            },
        ]
    )
    observed: list[dict[str, object]] = []

    def scan(_authority: object, columns: list[str], filters: dict[str, object]) -> pd.DataFrame:
        observed.append(dict(filters))
        assert filters["endDate"] == "2026-08-13"
        scoped = source.loc[source["game_date"] <= str(filters["endDate"])]
        return scoped[list(dict.fromkeys(columns))].copy()

    monkeypatch.setattr(lab.eda, "_scan", scan)
    monkeypatch.setattr(lab, "EXPECTED_DEVELOPMENT", ("2026-08-13", "2026-08-13", 1))
    frame = lab._fold_frame(current, ["feature_numeric"])
    assert observed
    assert frame["outcome"].tolist() == [lab.GOLD_CLASS_ORDER[0]]
    assert "FINAL_OOT_POISON" not in set(frame["outcome"])

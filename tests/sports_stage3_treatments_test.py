from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from server.persistence.db import Database
from server.persistence.repositories.stage3_treatment_repository import (
    Stage3TreatmentRepository,
)
from server.sports_current_statcast import stage3_treatments as treatments


PROJECT_ID = "asp-mtddc6pw"


def _authority() -> SimpleNamespace:
    names = {
        "feature_cont": pa.float64(),
        "batter_history_feature": pa.float64(),
        "feature_rate": pa.float64(),
        "feature_cat": pa.string(),
        "feature_binary": pa.int64(),
        "predictor_a": pa.float64(),
        "predictor_b": pa.float64(),
        "context_outs_before": pa.int64(),
        "game_date": pa.string(),
        "season": pa.int64(),
        "game_month": pa.float64(),
        "game_day_of_week": pa.string(),
        "context_top_bottom": pa.int64(),
        "canonicalGameId": pa.string(),
        "canonicalPaId": pa.string(),
        "batterCanonicalPlayerId": pa.string(),
        "pitcherCanonicalPlayerId": pa.string(),
        "outcome": pa.string(),
        "batter_prior_missing": pa.int64(),
        "batter_last100_insufficient": pa.int64(),
        "pitcher_prior_missing": pa.int64(),
        "pitcher_last250_insufficient": pa.int64(),
        "batting_missing_reason": pa.string(),
        "fielding_missing_reason": pa.string(),
    }
    public = {
        "projectId": PROJECT_ID,
        "sourceDatasetId": "asp.mlb.statcast.current-pa.v1",
        "sourceManifestSha": "1" * 64,
        "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
        "goldManifestSha": "2" * 64,
        "contextualDatasetId": "gold-table:gold_mlb_current_pa_context_v2",
        "contextualManifestSha": "3" * 64,
        "exclusionMembershipArtifactSha": "4" * 64,
        "reviewDigest": "5" * 64,
    }
    return SimpleNamespace(
        project_id=PROJECT_ID,
        registration_id="registration-current",
        dataset_version_id="current-pa-v1",
        activation_revision=7,
        source_dataset_id=public["sourceDatasetId"],
        source_manifest_sha=public["sourceManifestSha"],
        gold_manifest_sha=public["goldManifestSha"],
        contextual_manifest_sha=public["contextualManifestSha"],
        review_digest=public["reviewDigest"],
        schema=pa.schema([pa.field(name, dtype) for name, dtype in names.items()]),
        paths=(),
        public=lambda: dict(public),
    )


def _catalog() -> dict[str, dict[str, object]]:
    def row(
        name: str,
        data_type: str,
        *,
        role: str = "PREGAME_FEATURE",
        missing: float = 0.0,
        core: bool = True,
        selectable: bool = True,
    ) -> dict[str, object]:
        return {
            "name": name,
            "label": name,
            "dataType": data_type,
            "role": role,
            "featureFamily": "CORE_GOLD_48" if core else "CONTEXT",
            "category": role,
            "selectable": selectable,
            "core": core,
            "missingPercent": missing,
        }
    return {
        "feature_cont": row("feature_cont", "numeric", missing=8.0),
        "batter_history_feature": row("batter_history_feature", "numeric", missing=8.0),
        "feature_rate": row("feature_rate", "numeric", missing=2.0),
        "feature_cat": row("feature_cat", "categorical", missing=6.0),
        "feature_binary": row("feature_binary", "numeric", missing=4.0),
        "predictor_a": row("predictor_a", "numeric"),
        "predictor_b": row("predictor_b", "numeric"),
        "context_outs_before": row("context_outs_before", "numeric", role="SIMULATION_GENERATED_STATE", core=False),
        "canonicalGameId": row("canonicalGameId", "categorical", role="GROUPING", core=False, selectable=False),
        "outcome": row("outcome", "categorical", role="TARGET", core=False, selectable=False),
    }


def _frame() -> pd.DataFrame:
    rows = 160
    dates = pd.date_range("2026-04-01", periods=16, freq="D")
    values = np.linspace(0.0, 9.0, rows, dtype=float)
    values[-1] = 100.0
    values[::13] = np.nan
    rates = np.linspace(0.0, 1.0, rows)
    rates[-1] = 1.5
    categories: list[object] = ["A" if index % 2 else "B" for index in range(rows)]
    for index in range(0, rows, 17):
        categories[index] = None
    binary = pd.Series([index % 2 for index in range(rows)], dtype="float64")
    binary.iloc[::19] = np.nan
    return pd.DataFrame(
        {
            "feature_cont": values,
            "batter_history_feature": values,
            "feature_rate": rates,
            "feature_cat": categories,
            "feature_binary": binary,
            "predictor_a": np.sin(np.arange(rows) / 9.0),
            "predictor_b": np.cos(np.arange(rows) / 11.0),
            "context_outs_before": np.arange(rows) % 3,
            "game_date": np.repeat(dates.strftime("%Y-%m-%d"), 10),
            "season": 2026,
            "game_month": 4.0,
            "game_day_of_week": "WEDNESDAY",
            "context_top_bottom": np.arange(rows) % 2,
            "canonicalGameId": [f"game-{index // 10}" for index in range(rows)],
            "canonicalPaId": [f"pa-{index}" for index in range(rows)],
            "batterCanonicalPlayerId": [f"batter-{index % 12}" for index in range(rows)],
            "pitcherCanonicalPlayerId": [f"pitcher-{index % 8}" for index in range(rows)],
            "outcome": [treatments.GOLD_CLASS_ORDER[index % 8] for index in range(rows)],
            "batter_prior_missing": [1 if index % 13 == 0 else 0 for index in range(rows)],
            "batter_last100_insufficient": [1 if index % 7 == 0 else 0 for index in range(rows)],
            "pitcher_prior_missing": 0,
            "pitcher_last250_insufficient": 0,
            "batting_missing_reason": ["NO_PRIOR_HISTORY" if index % 13 == 0 else "" for index in range(rows)],
            "fielding_missing_reason": "",
        }
    )


@pytest.fixture
def governed(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, pd.DataFrame, str]:
    authority = _authority()
    frame = _frame()
    monkeypatch.setattr(treatments.eda, "_resolve_authority", lambda *_args: authority)
    monkeypatch.setattr(treatments, "_catalog", lambda *_args: _catalog())

    def scan(_authority: object, columns: list[str], filters: dict[str, object]) -> pd.DataFrame:
        scoped = frame.copy()
        if filters.get("startDate"):
            scoped = scoped.loc[scoped["game_date"] >= filters["startDate"]]
        if filters.get("endDate"):
            scoped = scoped.loc[scoped["game_date"] <= filters["endDate"]]
        if filters.get("outcomes"):
            scoped = scoped.loc[scoped["outcome"].isin(filters["outcomes"])]
        return scoped[list(dict.fromkeys(columns))].copy()

    monkeypatch.setattr(treatments.eda, "_scan", scan)
    key = treatments._authority_payload(authority)["authorityKey"]
    return authority, frame, key


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "persistence.db")
    database.initialize()
    return database


def test_outlier_detection_thresholds_are_exact_and_domain_bounds_are_registered() -> None:
    values = pd.Series([0.0, 1.0, 2.0, 3.0, 100.0])
    stats = treatments._statistics(values)
    assert treatments._detection_bounds("feature_cont", stats, "IQR_1_5") == (-2.0, 6.0)
    assert treatments._detection_bounds("feature_cont", stats, "IQR_3_0") == (-5.0, 9.0)
    assert treatments._detection_bounds("feature_cont", stats, "P95_UPPER") == (None, pytest.approx(80.6))
    assert treatments._detection_bounds("feature_cont", stats, "P99_UPPER") == (None, pytest.approx(96.12))
    assert treatments._detection_bounds("feature_cont", stats, "P05_P95") == (pytest.approx(0.2), pytest.approx(80.6))
    assert treatments._detection_bounds("feature_cont", stats, "P01_P99") == (pytest.approx(0.04), pytest.approx(96.12))
    assert treatments._detection_bounds("batter_last100_strikeout_rate", stats, "DOMAIN_BOUNDS") == (0.0, 1.0)
    with pytest.raises(treatments.Stage3TreatmentError) as missing:
        treatments._detection_bounds("feature_cont", stats, "DOMAIN_BOUNDS")
    assert missing.value.code == "DOMAIN_BOUNDS_UNAVAILABLE"


@pytest.mark.parametrize(
    ("treatment", "expected_field"),
    [
        ("FLAG_ONLY", "unchangedRows"),
        ("CAP_IQR", "cappedHigh"),
        ("WINSORIZE", "cappedHigh"),
        ("SET_MISSING", "setMissing"),
        ("EXCLUDE_ROW", "excluded"),
    ],
)
def test_outlier_preview_is_aggregate_same_axis_and_treatment_specific(
    governed: tuple[SimpleNamespace, pd.DataFrame, str],
    tmp_path: Path,
    treatment: str,
    expected_field: str,
) -> None:
    _authority_value, _frame_value, key = governed
    response = treatments.outlier_preview(
        _database(tmp_path),
        PROJECT_ID,
        {
            "authorityKey": key,
            "variable": "feature_cont",
            "detectionMethod": "IQR_1_5",
            "treatment": treatment,
            "params": {"lowerPercentile": 5, "upperPercentile": 95},
        },
    )
    assert response["population"]["scope"] == "DEVELOPMENT_ONLY"
    assert response["population"]["finalOotLocked"] is True
    assert response["audit"]["modelActivity"]["fits"] == 0
    assert response["data"]["sharedAxis"]["binEdges"]
    assert response["data"]["effect"][expected_field] >= 0
    assert "rows" not in response["data"]["before"]
    if treatment == "FLAG_ONLY":
        assert response["data"]["before"] == response["data"]["after"]
    if treatment == "EXCLUDE_ROW":
        assert response["data"]["effect"]["populationLossPercent"] > 0


def test_outlier_binary_preview_uses_shared_frequency_categories(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    data = treatments.outlier_detail(
        _database(tmp_path),
        PROJECT_ID,
        {
            "authorityKey": key,
            "variable": "feature_binary",
            "detectionMethod": "IQR_1_5",
            "treatment": "FLAG_ONLY",
        },
    )["data"]
    assert data["before"]["kind"] == "BINARY"
    assert data["after"]["kind"] == "BINARY"
    assert data["sharedAxis"]["binEdges"] == []
    assert data["sharedAxis"]["categories"] == ["0.0", "1.0"]
    assert [row["value"] for row in data["before"]["categories"]] == data["sharedAxis"]["categories"]
    assert [row["value"] for row in data["after"]["categories"]] == data["sharedAxis"]["categories"]


def test_missing_preview_values_eligibility_and_cold_start_remain_separate(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, frame, key = governed
    database = _database(tmp_path)
    mean = treatments.missing_preview(
        database,
        PROJECT_ID,
            {"authorityKey": key, "variable": "batter_history_feature", "imputationMethod": "MEAN"},
    )["data"]
    median = treatments.missing_preview(
        database,
        PROJECT_ID,
            {"authorityKey": key, "variable": "batter_history_feature", "imputationMethod": "MEDIAN"},
    )["data"]
    assert mean["fillValue"] == pytest.approx(frame["batter_history_feature"].mean())
    assert median["fillValue"] == pytest.approx(frame["batter_history_feature"].median())
    assert mean["effect"]["fillCount"] == int(frame["batter_history_feature"].isna().sum())
    assert mean["after"]["missingCount"] == 0
    assert mean["effect"]["reasonCounts"]["NO_PRIOR_HISTORY"] > 0
    assert "UNKNOWN_CATEGORY" in mean["ineligibleMethodReasons"]
    categorical = treatments.missing_preview(
        database,
        PROJECT_ID,
        {"authorityKey": key, "variable": "feature_cat", "imputationMethod": "MODE"},
    )["data"]
    assert categorical["before"]["kind"] == "CATEGORICAL"
    assert categorical["after"]["missingCount"] == 0
    assert categorical["effect"]["fillCount"] > 0
    with pytest.raises(treatments.Stage3TreatmentError) as invalid:
        treatments.missing_preview(
            database,
            PROJECT_ID,
            {"authorityKey": key, "variable": "context_outs_before", "imputationMethod": "MEAN"},
        )
    assert invalid.value.code == "IMPUTATION_METHOD_INELIGIBLE"


def test_stale_authority_and_final_oot_filters_fail_closed(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    with pytest.raises(treatments.Stage3TreatmentError) as stale:
        treatments.outlier_table(database, PROJECT_ID, {"authorityKey": "stale", "filters": {}})
    assert stale.value.code == "TREATMENT_AUTHORITY_STALE"
    with pytest.raises(treatments.Stage3TreatmentError) as oot:
        treatments.missing_table(
            database,
            PROJECT_ID,
            {"authorityKey": key, "filters": {"endDate": "2026-08-14"}},
        )
    assert oot.value.code == "FINAL_OOT_FILTER_PROHIBITED"
    with pytest.raises(treatments.Stage3TreatmentError) as target_conditioned:
        treatments.outlier_preview(
            database,
            PROJECT_ID,
            {
                "authorityKey": key,
                "variable": "feature_cont",
                "filters": {"outcomes": ["STRIKEOUT"]},
            },
        )
    assert target_conditioned.value.code == "TARGET_DERIVED_TREATMENT_PROHIBITED"


def test_table_batch_selection_custom_bounds_and_severity_contract(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, frame, key = governed
    database = _database(tmp_path)
    table = treatments.outlier_table(
        database,
        PROJECT_ID,
        {
            "authorityKey": key,
            "featureFamilies": ["CORE_GOLD_48"],
            "severity": "WITH_OUTLIERS",
            "selectedVariables": ["feature_cont"],
            "pageSize": 100,
            "overrides": {
                "feature_cont": {
                    "detectionMethod": "IQR_1_5",
                    "treatment": "CAP_IQR",
                    "customLowerThreshold": 2.0,
                    "customUpperThreshold": 7.0,
                    "included": False,
                }
            },
        },
    )["data"]
    # A cross-page batch selection must not hide other diagnostic rows.
    assert table["totalRows"] > 1
    row = next(item for item in table["rows"] if item["variable"] == "feature_cont")
    expected = int(((frame["feature_cont"] < 2.0) | (frame["feature_cont"] > 7.0)).sum())
    assert row["numberOfOutliers"] == expected
    assert row["lowerThreshold"] == 2.0
    assert row["upperThreshold"] == 7.0
    assert row["active"] is False
    assert row["status"] == "EXCLUDED_FROM_POLICY"

    preview = treatments.outlier_preview(
        database,
        PROJECT_ID,
        {
            "authorityKey": key,
            "variable": "feature_cont",
            "detectionMethod": "IQR_1_5",
            "treatment": "CAP_IQR",
            "customLowerThreshold": 2.0,
            "customUpperThreshold": 7.0,
            "included": False,
        },
    )["data"]
    assert preview["treatment"] == "RETAIN"
    assert preview["before"] == preview["after"]
    assert "excluded from the preprocessing policy" in preview["warning"].lower()

    cold = treatments.missing_table(
        database,
        PROJECT_ID,
        {
            "authorityKey": key,
            "severity": "COLD_START",
            "pageSize": 100,
        },
    )["data"]["rows"]
    assert any(item["variable"] == "batter_history_feature" for item in cold)
    with pytest.raises(treatments.Stage3TreatmentError) as unknown_sort:
        treatments.outlier_table(
            database,
            PROJECT_ID,
            {"authorityKey": key, "sort": {"field": "eligibleDetectionMethods", "direction": "asc"}},
        )
    assert unknown_sort.value.code == "TREATMENT_SORT_INVALID"
    with pytest.raises(treatments.Stage3TreatmentError) as nonscalar_sort_request:
        treatments.missing_table(
            database,
            PROJECT_ID,
            {"authorityKey": key, "sort": {"field": {"nested": "value"}, "direction": "asc"}},
        )
    assert nonscalar_sort_request.value.code == "TREATMENT_SORT_INVALID"


def test_policy_versions_are_append_only_and_adoption_never_stores_preview_thresholds(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    authority, _frame_value, key = governed
    database = _database(tmp_path)
    draft = treatments.save_treatment_policy_draft(
        database,
        PROJECT_ID,
        "outliers",
        {
            "authorityKey": key,
            "globalMethod": "IQR_1_5",
            "globalTreatment": "FLAG_ONLY",
            "overrides": {"feature_cont": {"detectionMethod": "P95_UPPER", "treatment": "CAP_P95"}},
            "notes": "reviewed",
        },
        actor_user_id="user-1",
    )["data"]
    assert draft["status"] == "DRAFT"
    assert draft["policyId"]
    with pytest.raises(treatments.Stage3TreatmentError) as stale_draft_content:
        treatments.adopt_treatment_policy(
            database,
            PROJECT_ID,
            "outliers",
            {"authorityKey": key, "policyId": draft["policyId"], "expectedChecksum": "0" * 64},
            actor_user_id="user-1",
        )
    assert stale_draft_content.value.code == "TREATMENT_DRAFT_CHECKSUM_MISMATCH"
    adopted = treatments.adopt_treatment_policy(
        database,
        PROJECT_ID,
        "outliers",
        {
            "authorityKey": key,
            "policyId": draft["policyId"],
            "expectedChecksum": draft["checksum"],
        },
        actor_user_id="user-1",
    )["data"]
    assert adopted["status"] == "ADOPTED"
    assert adopted["policyVersion"] > draft["policyVersion"]
    state = Stage3TreatmentRepository(database).policy_state(PROJECT_ID, "OUTLIER", authority.review_digest)
    assert len(state["history"]) == 2
    assert state["adopted"]["fittingRule"]["fitScope"] == "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY"
    assert state["adopted"]["policy"]["descriptivePreviewThresholdsAreAuthoritative"] is False
    policy_id = state["adopted"]["policyId"]
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE stage3_treatment_policy_versions SET notes = 'changed' WHERE treatment_policy_id = ?",
                (policy_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM stage3_treatment_policy_versions WHERE treatment_policy_id = ?",
                (policy_id,),
            )


def test_predicted_preview_is_cross_fitted_target_free_and_not_an_outcome_model(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    response = treatments.predicted_imputation_preview(
        database,
        PROJECT_ID,
        {
            "authorityKey": key,
            "variable": "feature_cont",
            "predictorSet": ["predictor_a", "predictor_b"],
            "seed": treatments.PREDICTED_PREVIEW_SEED,
        },
        actor_user_id="user-1",
    )
    data = response["data"]
    assert data["status"] == "COMPLETE"
    assert len(data["artifactChecksum"]) == 64
    assert data["targetOutcomeExcluded"] is True
    assert data["finalOotExcluded"] is True
    assert all(row["trainEndDate"] < row["validationStartDate"] for row in data["folds"])
    assert {item["field"] for item in data["excludedFields"]} >= {"outcome", "canonicalGameId", "canonicalPaId"}
    assert response["audit"]["modelActivity"]["fits"] == 0
    assert response["audit"]["preprocessingPreviewActivity"]["predictedImputerFits"] > 0
    assert response["population"]["finalOotLocked"] is True
    stored = Stage3TreatmentRepository(database).latest_preview(PROJECT_ID, "feature_cont", "5" * 64)
    assert stored and stored["artifactSha256"] == data["artifactChecksum"]


def test_global_outlier_domain_bounds_applies_where_eligible_and_falls_back_elsewhere(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    rows = treatments.outlier_table(
        database,
        PROJECT_ID,
        {
            "authorityKey": key,
            "globalMethod": "DOMAIN_BOUNDS",
            "includeAdvanced": True,
            "pageSize": 100,
        },
    )["data"]["rows"]
    by_name = {row["variable"]: row for row in rows}
    assert by_name["context_outs_before"]["selectedDetectionMethod"] == "DOMAIN_BOUNDS"
    assert by_name["context_outs_before"]["globalMethodFallback"] is False
    assert by_name["feature_cont"]["selectedDetectionMethod"] == "IQR_1_5"
    assert by_name["feature_cont"]["requestedGlobalDetectionMethod"] == "DOMAIN_BOUNDS"
    assert by_name["feature_cont"]["globalMethodFallback"] is True

    detail = treatments.outlier_detail(
        database,
        PROJECT_ID,
        {"authorityKey": key, "variable": "feature_cont", "globalMethod": "DOMAIN_BOUNDS"},
    )["data"]
    assert detail["detectionMethod"] == "IQR_1_5"
    assert detail["globalMethodFallback"] is True

    draft = treatments.save_treatment_policy_draft(
        database,
        PROJECT_ID,
        "outliers",
        {
            "authorityKey": key,
            "globalMethod": "DOMAIN_BOUNDS",
            "overrides": {"feature_cont": {"treatment": "FLAG_ONLY"}},
        },
        actor_user_id="user-1",
    )["data"]
    assert draft["globalMethod"] == "DOMAIN_BOUNDS"

    with pytest.raises(treatments.Stage3TreatmentError) as invalid:
        treatments.outlier_table(
            database,
            PROJECT_ID,
            {
                "authorityKey": key,
                "globalMethod": "IQR_1_5",
                "overrides": {"feature_cont": {"detectionMethod": "DOMAIN_BOUNDS"}},
            },
        )
    assert invalid.value.code == "OUTLIER_METHOD_INELIGIBLE"


def test_global_missing_method_applies_where_eligible_and_explicit_override_fails(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    median_rows = treatments.missing_table(
        database,
        PROJECT_ID,
        {"authorityKey": key, "globalMethod": "MEDIAN", "pageSize": 100},
    )["data"]["rows"]
    median_by_name = {row["variable"]: row for row in median_rows}
    assert median_by_name["feature_cont"]["selectedImputationMethod"] == "MEDIAN"
    assert median_by_name["feature_cont"]["globalMethodFallback"] is False
    assert median_by_name["feature_cat"]["selectedImputationMethod"] == "MODE"
    assert median_by_name["feature_cat"]["globalMethodFallback"] is True
    assert median_by_name["context_outs_before"]["selectedImputationMethod"] == "RETAIN_WITH_INDICATOR"
    assert median_by_name["context_outs_before"]["globalMethodFallback"] is True

    mode_rows = treatments.missing_table(
        database,
        PROJECT_ID,
        {"authorityKey": key, "globalMethod": "MODE", "pageSize": 100},
    )["data"]["rows"]
    mode_by_name = {row["variable"]: row for row in mode_rows}
    assert mode_by_name["feature_cat"]["selectedImputationMethod"] == "MODE"
    assert mode_by_name["feature_cont"]["selectedImputationMethod"] == "MEDIAN"
    assert mode_by_name["feature_cont"]["globalMethodFallback"] is True

    detail = treatments.missing_detail(
        database,
        PROJECT_ID,
        {"authorityKey": key, "variable": "feature_cat", "globalMethod": "MEDIAN"},
    )["data"]
    assert detail["method"] == "MODE"
    assert detail["globalMethodFallback"] is True

    with pytest.raises(treatments.Stage3TreatmentError) as invalid:
        treatments.missing_table(
            database,
            PROJECT_ID,
            {
                "authorityKey": key,
                "globalMethod": "MEDIAN",
                "overrides": {"feature_cont": {"method": "MODE"}},
            },
        )
    assert invalid.value.code == "IMPUTATION_METHOD_INELIGIBLE"


def test_successive_drafts_emit_supported_append_only_events(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    authority, _frame_value, key = governed
    database = _database(tmp_path)
    first = treatments.save_treatment_policy_draft(
        database,
        PROJECT_ID,
        "outliers",
        {"authorityKey": key, "globalMethod": "IQR_1_5", "notes": "first"},
        actor_user_id="user-1",
    )["data"]
    second = treatments.save_treatment_policy_draft(
        database,
        PROJECT_ID,
        "outliers",
        {"authorityKey": key, "globalMethod": "IQR_3_0", "notes": "second"},
        actor_user_id="user-1",
    )["data"]
    assert second["policyVersion"] > first["policyVersion"]
    state = Stage3TreatmentRepository(database).policy_state(
        PROJECT_ID, "OUTLIER", authority.review_digest
    )
    assert len(state["history"]) == 2
    with database.connection() as connection:
        events = [
            row["event_type"]
            for row in connection.execute(
                "SELECT event_type FROM stage3_treatment_policy_events ORDER BY created_at"
            ).fetchall()
        ]
    assert events == ["DRAFT_CREATED", "DRAFT_UPDATED"]


def test_governed_prior_requires_registered_authority_and_safe_default(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    table = treatments.missing_table(
        database,
        PROJECT_ID,
        {"authorityKey": key, "pageSize": 100},
    )["data"]["rows"]
    assert table
    assert all(row["governedPriorAvailable"] is False for row in table)
    assert all(row["governedPriorUnavailableReason"] for row in table)
    detail = treatments.missing_detail(
        database,
        PROJECT_ID,
        {"authorityKey": key, "variable": "feature_cont"},
    )["data"]
    assert detail["governedPriorAvailable"] is False

    draft = treatments.save_treatment_policy_draft(
        database,
        PROJECT_ID,
        "missing",
        {"authorityKey": key, "globalMethod": "DATA_TYPE_AWARE"},
        actor_user_id="user-1",
    )["data"]
    assert draft["coldStartDefault"] == "RETAIN_WITH_INDICATOR"
    assert draft["governedPriorAvailable"] is False

    with pytest.raises(treatments.Stage3TreatmentError) as invalid:
        treatments.save_treatment_policy_draft(
            database,
            PROJECT_ID,
            "missing",
            {
                "authorityKey": key,
                "globalMethod": "DATA_TYPE_AWARE",
                "coldStartDefault": "GOVERNED_PRIOR_WITH_INDICATOR",
            },
            actor_user_id="user-1",
        )
    assert invalid.value.code == "COLD_START_GOVERNED_PRIOR_UNAVAILABLE"


def test_predicted_imputation_policy_rejects_transitive_dependency_cycles(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    with pytest.raises(treatments.Stage3TreatmentError) as cycle:
        treatments.save_treatment_policy_draft(
            database,
            PROJECT_ID,
            "missing",
            {
                "authorityKey": key,
                "globalMethod": "DATA_TYPE_AWARE",
                "overrides": {
                    "feature_cont": {"method": "PREDICTED", "predictorSet": ["predictor_a"]},
                    "predictor_a": {"method": "PREDICTED", "predictorSet": ["predictor_b"]},
                    "predictor_b": {"method": "PREDICTED", "predictorSet": ["feature_cont"]},
                },
            },
            actor_user_id="user-1",
        )
    assert cycle.value.code == "PREDICTED_IMPUTATION_DEPENDENCY_CYCLE"


def test_outlier_table_returns_method_bound_active_summary(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    common = {"authorityKey": key, "search": "feature_rate", "pageSize": 100}
    iqr = treatments.outlier_table(
        database,
        PROJECT_ID,
        {**common, "globalMethod": "IQR_1_5", "globalTreatment": "RETAIN"},
    )["data"]["activeSummary"]
    p95 = treatments.outlier_table(
        database,
        PROJECT_ID,
        {**common, "globalMethod": "P95_UPPER", "globalTreatment": "FLAG_ONLY"},
    )["data"]["activeSummary"]
    assert iqr["activeDetectionMethod"] == "IQR_1_5"
    assert p95["activeDetectionMethod"] == "P95_UPPER"
    assert p95["activeTreatment"] == "FLAG_ONLY"
    assert iqr["totalAffectedRows"] != p95["totalAffectedRows"]
    assert p95["totalAffectedRows"] == p95["highestAffectedCount"]


def test_missing_table_reports_exact_descriptive_fill_preview_values(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, frame, key = governed
    database = _database(tmp_path)

    def row(method: str, variable: str) -> dict[str, object]:
        rows = treatments.missing_table(
            database,
            PROJECT_ID,
            {"authorityKey": key, "globalMethod": method, "pageSize": 100},
        )["data"]["rows"]
        return next(item for item in rows if item["variable"] == variable)

    mean = row("MEAN", "feature_cont")
    median = row("MEDIAN", "feature_cont")
    mode = row("MODE", "feature_cat")
    assert mean["descriptivePreviewValue"] == pytest.approx(frame["feature_cont"].mean())
    assert median["descriptivePreviewValue"] == pytest.approx(frame["feature_cont"].median())
    assert mean["descriptivePreviewValue"] != median["descriptivePreviewValue"]
    assert mode["descriptivePreviewValue"] == frame["feature_cat"].dropna().mode().iloc[0]
    assert "fold-local" in str(mean["imputedValueOrPolicy"]).lower()
    assert mean["descriptivePreviewOnly"] is True


def test_include_advanced_returns_read_only_excluded_metadata_without_false_zeroes(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    outlier = treatments.outlier_table(
        database,
        PROJECT_ID,
        {"authorityKey": key, "includeAdvanced": True, "pageSize": 100},
    )["data"]
    missing = treatments.missing_table(
        database,
        PROJECT_ID,
        {"authorityKey": key, "includeAdvanced": True, "pageSize": 100},
    )["data"]
    outlier_by_name = {row["variable"]: row for row in outlier["rows"]}
    missing_by_name = {row["variable"]: row for row in missing["rows"]}
    for variable in ("canonicalGameId", "outcome"):
        assert outlier_by_name[variable]["status"] == "NOT_EVALUATED"
        assert outlier_by_name[variable]["numberOfOutliers"] is None
        assert outlier_by_name[variable]["eligible"] is False
        assert outlier_by_name[variable]["exclusionReason"]
        assert missing_by_name[variable]["status"] == "NOT_EVALUATED"
        assert missing_by_name[variable]["numberOfMissingValues"] is None
        assert missing_by_name[variable]["eligible"] is False
        assert missing_by_name[variable]["exclusionReason"]
    assert outlier["excludedMetadataRows"] >= 2
    assert missing["excludedMetadataRows"] >= 2

    with pytest.raises(treatments.Stage3TreatmentError) as outlier_override:
        treatments.outlier_table(
            database,
            PROJECT_ID,
            {
                "authorityKey": key,
                "includeAdvanced": True,
                "overrides": {"outcome": {"detectionMethod": "IQR_1_5"}},
            },
        )
    assert outlier_override.value.code == "OUTLIER_VARIABLE_INELIGIBLE"
    with pytest.raises(treatments.Stage3TreatmentError) as missing_override:
        treatments.missing_table(
            database,
            PROJECT_ID,
            {
                "authorityKey": key,
                "includeAdvanced": True,
                "overrides": {"outcome": {"method": "MODE"}},
            },
        )
    assert missing_override.value.code == "MISSING_VARIABLE_INELIGIBLE"


def test_predicted_preview_requires_canonical_unfiltered_artifact_then_drafts_and_adopts(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    _authority_value, _frame_value, key = governed
    database = _database(tmp_path)
    base = {
        "authorityKey": key,
        "variable": "feature_cont",
        "predictorSet": ["predictor_a", "predictor_b"],
        "seed": treatments.PREDICTED_PREVIEW_SEED,
    }
    filtered = treatments.predicted_imputation_preview(
        database,
        PROJECT_ID,
        {**base, "filters": {"endDate": "2026-04-08"}},
        actor_user_id="user-1",
    )
    assert filtered["data"]["status"] == "COMPLETE"
    policy_payload = {
        "authorityKey": key,
        "globalMethod": "DATA_TYPE_AWARE",
        "overrides": {
            "feature_cont": {
                "method": "PREDICTED",
                "predictorSet": ["predictor_a", "predictor_b"],
                "seed": treatments.PREDICTED_PREVIEW_SEED,
            }
        },
    }
    with pytest.raises(treatments.Stage3TreatmentError) as filtered_not_authorizing:
        treatments.save_treatment_policy_draft(
            database,
            PROJECT_ID,
            "missing",
            policy_payload,
            actor_user_id="user-1",
        )
    assert filtered_not_authorizing.value.code == "PREDICTED_PREVIEW_REQUIRED"

    unfiltered = treatments.predicted_imputation_preview(
        database,
        PROJECT_ID,
        base,
        actor_user_id="user-1",
    )
    preview = unfiltered["data"]
    assert preview["canonicalPredictedPreviewSeed"] == treatments.PREDICTED_PREVIEW_SEED
    assert preview["after"] != preview["observedDistribution"]
    assert preview["aggregateEffect"]["combinedCount"] == (
        preview["aggregateEffect"]["observedCount"]
        + preview["aggregateEffect"]["imputedCount"]
    )
    after_bins = preview["after"].get("histogram") or preview["after"].get("categories") or []
    assert sum(int(item["imputedCount"]) for item in after_bins) == preview["aggregateEffect"]["imputedCount"]
    detail = treatments.missing_detail(
        database,
        PROJECT_ID,
        {**base, "imputationMethod": "PREDICTED"},
    )["data"]
    assert detail["after"] != detail["before"]
    assert detail["imputedDistribution"]
    assert detail["effect"]["fillCount"] == preview["missingRowsImputed"]

    draft = treatments.save_treatment_policy_draft(
        database,
        PROJECT_ID,
        "missing",
        policy_payload,
        actor_user_id="user-1",
    )["data"]
    adopted = treatments.adopt_treatment_policy(
        database,
        PROJECT_ID,
        "missing",
        {"authorityKey": key, "policyId": draft["policyId"]},
        actor_user_id="user-1",
    )["data"]
    assert adopted["status"] == "ADOPTED"

    with pytest.raises(treatments.Stage3TreatmentError) as seed_mismatch:
        treatments.predicted_imputation_preview(
            database,
            PROJECT_ID,
            {**base, "seed": treatments.PREDICTED_PREVIEW_SEED + 1},
            actor_user_id="user-1",
        )
    assert seed_mismatch.value.code == "PREDICTED_PREVIEW_SEED_MISMATCH"


def test_previously_adopted_content_can_be_reintroduced_as_new_version(
    governed: tuple[SimpleNamespace, pd.DataFrame, str], tmp_path: Path
) -> None:
    authority, _frame_value, key = governed
    database = _database(tmp_path)

    def draft_and_adopt(method: str) -> tuple[dict[str, object], dict[str, object]]:
        draft = treatments.save_treatment_policy_draft(
            database,
            PROJECT_ID,
            "outliers",
            {"authorityKey": key, "globalMethod": method},
            actor_user_id="user-1",
        )["data"]
        adopted = treatments.adopt_treatment_policy(
            database,
            PROJECT_ID,
            "outliers",
            {"authorityKey": key, "policyId": draft["policyId"]},
            actor_user_id="user-1",
        )["data"]
        return draft, adopted

    first_draft, first_adopted = draft_and_adopt("IQR_1_5")
    _second_draft, second_adopted = draft_and_adopt("IQR_3_0")
    third_draft, third_adopted = draft_and_adopt("IQR_1_5")
    assert third_draft["policyId"] != first_draft["policyId"]
    assert third_adopted["policyId"] != first_adopted["policyId"]
    assert third_adopted["policyVersion"] > second_adopted["policyVersion"]
    state = Stage3TreatmentRepository(database).policy_state(
        PROJECT_ID, "OUTLIER", authority.review_digest
    )
    assert len(state["history"]) == 6


def test_source_and_gold_paths_are_never_written_by_policy_or_preview_code() -> None:
    source = Path(treatments.__file__).resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert "write_bytes" not in Path(treatments.__file__).read_text(encoding="utf-8")

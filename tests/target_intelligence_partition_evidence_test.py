from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from server.analytics import target_intelligence_router as router
from server.analytics import target_intelligence_service as legacy_service
from server.core.dataset_store import DatasetStore
from server.eda import workspace_service as workspace_module
from server.eda.workspace_service import eda_workspace_service
from tests.analysis_partition_fixture import GovernedAnalysisFixture


PROJECT_ID = "project-target-evidence-development"
DATASET_ID = "dataset-target-evidence-development"
VERSION_ID = "version-target-evidence-development"
TARGET = "bad_flag"
PREDICTORS = ["risk", "inquiries"]


def _canonical_lineage_with_bureau_semantics(**updates):
    lineage = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "activation_revision": 1,
        "target_contract_id": "target-contract-exact",
        "target": TARGET,
        "positive_value": 1,
        "negative_value": 0,
        "event_value": 1,
        "non_event_value": 0,
        "predictor_authorization_id": "predictor-auth-exact",
        "analysis_partition_id": "analysis-partition-exact",
        "analysis_partition_revision": 2,
        "special_value_review_id": "special-review-exact",
        "special_value_review_revision": 3,
        "expected_dataset_id": DATASET_ID,
        "expected_dataset_version_id": VERSION_ID,
        "dataset_version": VERSION_ID,
        "bureau_semantic_annotation_state": "available",
        "bureau_semantic_annotation_set_id": "bureau-annotations-exact",
        "bureau_semantic_annotation_set_checksum": "annotations-checksum",
        "bureau_metadata_schema_checksum": "schema-checksum",
        "bureau_metadata_binding_id": "binding-exact",
        "bureau_metadata_binding_revision": 4,
        "bureau_metadata_binding_revision_checksum": "binding-checksum",
        "bureau_metadata_crosswalk_id": "crosswalk-exact",
        "bureau_metadata_crosswalk_revision": 5,
        "bureau_metadata_crosswalk_revision_checksum": "crosswalk-checksum",
        "bureau_metadata_catalog_version_id": "catalog-version-exact",
        "bureau_metadata_catalog_checksum": "catalog-checksum",
    }
    lineage.update(updates)
    return lineage


class _StoreProxy:
    def __init__(self, store: DatasetStore) -> None:
        self._store = store

    def current(self) -> DatasetStore:
        return self._store

    def __getattr__(self, name: str):
        return getattr(self._store, name)


def _source() -> pd.DataFrame:
    rng = np.random.default_rng(781)
    rows = 200
    risk = np.linspace(20.0, 95.0, rows)
    inquiries = rng.poisson(3, rows).astype(float)
    target = ((risk < 53.0) | (inquiries > 5)).astype(int)
    return pd.DataFrame(
        {"risk": risk, "inquiries": inquiries, TARGET: target}
    )


@pytest.fixture()
def governed_target():
    source = _source()
    store = DatasetStore()
    store.set_raw(source)
    store.set_target(TARGET)
    store.meta.update(
        {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "source": {"kind": "dataset_library", "filename": "target.csv"},
            "selected_columns": list(PREDICTORS),
        }
    )
    fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
    installed = fixture.install(
        store,
        dataset_id=DATASET_ID,
        dataset_version_id=VERSION_ID,
        target=TARGET,
        authorized_predictors=PREDICTORS,
        positive_value=1,
        negative_value=0,
        development_share=0.8,
        random_seed=42,
    )
    eda_workspace_service._cache.clear()
    eda_workspace_service._contract_cache.clear()
    proxy = _StoreProxy(store)
    with (
        patch.object(workspace_module, "DATASTORE", proxy),
        patch.object(
            workspace_module,
            "assert_expected_active_identity",
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                # The EDA authority now requires the durable activation
                # revision before it resolves Special-Value Review lineage.
                # GovernedAnalysisFixture installs revision 1 for this exact
                # synthetic dataset version.
                "activation_revision": 1,
            },
        ),
    ):
        try:
            yield store, fixture, installed
        finally:
            eda_workspace_service._cache.clear()
            eda_workspace_service._contract_cache.clear()
            fixture.close()


def _assessment():
    return router._development_target_assessment(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        version_id=VERSION_ID,
        target=TARGET,
        event_value=1,
        artifact={"versionId": VERSION_ID, "checksum": "dataset-checksum"},
        operation="test",
    )


def test_target_evidence_counts_are_holdout_mutation_invariant(governed_target):
    store, _fixture, installed = governed_target
    baseline, _workspace = _assessment()
    holdout_positions = installed["record"]["row_assignments_json"][
        "holdout_positions"
    ]
    store.raw_df.loc[holdout_positions, TARGET] = (
        1 - store.raw_df.loc[holdout_positions, TARGET].astype(int)
    )
    eda_workspace_service._cache.clear()
    eda_workspace_service._contract_cache.clear()

    changed, _workspace = _assessment()
    assert changed["classBalance"] == baseline["classBalance"]
    assert changed["imbalance"] == baseline["imbalance"]
    assert changed["confidenceInterval"] == baseline["confidenceInterval"]
    scope = changed["analysisScope"]
    assert scope["populationRows"] == installed["record"]["development_count"]
    assert scope["analysisPartitionId"] == installed["record"][
        "analysis_partition_id"
    ]
    assert scope["analysisPartitionRevision"] == installed["record"]["revision"]
    assert scope["finalHoldoutAccessed"] is False


def test_target_export_fails_closed_while_partition_documentation_is_pending(
    governed_target,
):
    _store, fixture, installed = governed_target
    with fixture.database.transaction() as connection:
        connection.execute(
            """
            UPDATE analysis_partitions
            SET evidence_status = 'pending', evidence_ref = NULL,
                mdd_status = 'pending', mdd_ref = NULL
            WHERE analysis_partition_id = ?
            """,
            (installed["record"]["analysis_partition_id"],),
        )
    eda_workspace_service._cache.clear()
    eda_workspace_service._contract_cache.clear()

    active = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
    }
    with (
        patch.object(router, "_check_project_access"),
        patch.object(router, "require_dataset", return_value={"name": "Target"}),
        patch.object(router, "_require_active_version", return_value=active),
        patch.object(
            router,
            "_assert_target_exists_in_version",
            return_value={"versionId": VERSION_ID, "checksum": "dataset-checksum"},
        ),
        pytest.raises(HTTPException) as captured,
    ):
        router.target_summary_export(
            router.TargetSummaryExportRequest(
                projectId=PROJECT_ID,
                datasetId=DATASET_ID,
                versionId=VERSION_ID,
                target=TARGET,
                eventValue=1,
            ),
            {"userId": "target-evidence-test"},
        )
    assert captured.value.status_code == 409
    assert captured.value.detail["ok"] is False
    assert captured.value.detail["code"] == "analysis_partition_documentation_pending"
    assert captured.value.detail["operation"] == "target_summary_export"


def test_evidence_and_export_never_call_legacy_full_artifact_compute(
    governed_target,
):
    _store, _fixture, installed = governed_target
    active = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
    }
    artifact = {"versionId": VERSION_ID, "checksum": "dataset-checksum"}
    normalized_records: list[dict] = []

    def _normalize(record, _user):
        normalized_records.append(record)
        return record

    def _persist(record):
        return {**record, "createdAt": "2026-08-03T00:00:00+00:00"}

    common_patches = (
        patch.object(router, "_check_project_access"),
        patch.object(router, "require_dataset", return_value={"name": "Target"}),
        patch.object(router, "_require_active_version", return_value=active),
        patch.object(router, "_assert_target_exists_in_version", return_value=artifact),
        patch.object(router, "audit_event"),
        patch.object(
            legacy_service,
            "compute_target_assessment",
            side_effect=AssertionError("legacy target assessment was called"),
        ),
        patch.object(
            legacy_service,
            "compute_target_by_predictor",
            side_effect=AssertionError("legacy target-by-predictor was called"),
        ),
    )
    with ExitStack() as stack:
        for active_patch in common_patches:
            stack.enter_context(active_patch)
        stack.enter_context(
            patch.object(
                router,
                "authorize_and_normalize_evidence",
                side_effect=_normalize,
            )
        )
        stack.enter_context(
            patch.object(router, "upsert_evidence", side_effect=_persist)
        )
        evidence = router.save_target_evidence(
            router.TargetEvidenceRequest(
                projectId=PROJECT_ID,
                datasetId=DATASET_ID,
                versionId=VERSION_ID,
                target=TARGET,
                eventValue=1,
                nonEventValue=0,
                predictor="risk",
                predictorAnalysisType="numeric_quantile",
            ),
            {"userId": "target-evidence-test"},
        )
        export = router.target_summary_export(
            router.TargetSummaryExportRequest(
                projectId=PROJECT_ID,
                datasetId=DATASET_ID,
                versionId=VERSION_ID,
                target=TARGET,
                eventValue=1,
                nonEventValue=0,
            ),
            {"userId": "target-evidence-test"},
        )

    assert evidence["ok"] is True
    assert export["ok"] is True
    assert export["populationScope"] == "development_population"
    assert export["populationRows"] == installed["record"]["development_count"]
    assert export["analysisPartitionId"] == installed["record"][
        "analysis_partition_id"
    ]
    assert export["finalHoldoutAccessed"] is False
    saved = normalized_records[0]["payload"]
    assert saved["datasetIdentity"]["developmentPopulationRows"] == installed[
        "record"
    ]["development_count"]
    assert saved["analysisSpecification"]["populationScope"] == (
        "development_population"
    )
    assert saved["analysisSpecification"]["finalHoldoutAccessed"] is False
    predictor = saved["selectedPredictorAnalysis"]
    assert predictor is not None
    assert sum(row["population"] for row in predictor["rows"]) <= installed[
        "record"
    ]["development_count"]


def test_public_target_by_predictor_accepts_and_propagates_exact_bureau_lineage():
    captured = []
    active = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
    }

    def _target_by_predictor(request):
        captured.append(request)
        return {
            "ok": True,
            "scope": "development_population",
            "finalHoldoutAccessed": False,
        }

    lineage = _canonical_lineage_with_bureau_semantics()
    payload = router.TargetByPredictorRequest(
        projectId=PROJECT_ID,
        datasetId=DATASET_ID,
        versionId=VERSION_ID,
        target=TARGET,
        predictor="risk",
        analysisType="numeric_quantile",
        eventValue=1,
        canonicalLineage=lineage,
    )
    user = {"userId": "target-evidence-test"}
    with (
        patch.object(router, "_check_project_access") as access,
        patch.object(
            router,
            "_require_active_version",
            return_value=active,
        ) as active_version,
        patch.object(
            eda_workspace_service,
            "target_by_predictor",
            side_effect=_target_by_predictor,
        ),
        patch.object(
            legacy_service,
            "compute_target_by_predictor",
            side_effect=AssertionError("legacy predictor fallback was called"),
        ) as legacy,
    ):
        result = router.target_by_predictor(payload, user)

    access.assert_called_once_with(user, PROJECT_ID)
    active_version.assert_called_once_with(
        user,
        PROJECT_ID,
        DATASET_ID,
        VERSION_ID,
    )
    legacy.assert_not_called()
    assert result["scope"] == "development_population"
    assert result["finalHoldoutAccessed"] is False
    assert len(captured) == 1
    forwarded = captured[0]
    for field in (
        "bureau_semantic_annotation_state",
        "bureau_semantic_annotation_set_id",
        "bureau_semantic_annotation_set_checksum",
        "bureau_metadata_schema_checksum",
        "bureau_metadata_binding_id",
        "bureau_metadata_binding_revision",
        "bureau_metadata_binding_revision_checksum",
        "bureau_metadata_crosswalk_id",
        "bureau_metadata_crosswalk_revision",
        "bureau_metadata_crosswalk_revision_checksum",
        "bureau_metadata_catalog_version_id",
        "bureau_metadata_catalog_checksum",
    ):
        assert getattr(forwarded, field) == lineage[field]
    assert not any("holdout" in field.casefold() for field in forwarded.model_fields)


@pytest.mark.parametrize(
    "updates",
    [
        {"bureau_metadata_catalog_checksum": None},
        {"bureau_semantic_annotation_state": "unavailable"},
        {"bureau_metadata_crosswalk_revision": 0},
    ],
)
def test_public_target_by_predictor_rejects_malformed_bureau_lineage(updates):
    with pytest.raises(ValidationError):
        router.TargetByPredictorRequest(
            projectId=PROJECT_ID,
            datasetId=DATASET_ID,
            versionId=VERSION_ID,
            target=TARGET,
            predictor="risk",
            canonicalLineage=_canonical_lineage_with_bureau_semantics(**updates),
        )


@pytest.mark.parametrize(
    ("lineage_updates", "expected_code"),
    [
        ({"project_id": "cross-project"}, "eda_project_scope_mismatch"),
        ({"target": "other_target"}, "target_contract_stale"),
    ],
)
def test_public_target_by_predictor_rejects_contradictory_lineage_before_analysis(
    lineage_updates,
    expected_code,
):
    payload = router.TargetByPredictorRequest(
        projectId=PROJECT_ID,
        datasetId=DATASET_ID,
        versionId=VERSION_ID,
        target=TARGET,
        predictor="risk",
        canonicalLineage=_canonical_lineage_with_bureau_semantics(
            **lineage_updates
        ),
    )
    with (
        patch.object(router, "_check_project_access"),
        patch.object(
            router,
            "_require_active_version",
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
            },
        ),
        patch.object(eda_workspace_service, "target_by_predictor") as analysis,
        pytest.raises(HTTPException) as captured,
    ):
        router.target_by_predictor(payload, {"userId": "target-evidence-test"})
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == expected_code
    analysis.assert_not_called()

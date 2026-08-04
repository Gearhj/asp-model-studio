from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import json
from pathlib import Path
import uuid
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from server.analysis_partition.service import AnalysisPartitionService
from server.analysis_partition.types import (
    ANALYSIS_PARTITION_CONTRADICTORY,
    ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
    ANALYSIS_PARTITION_PREVIEW_STALE,
    ANALYSIS_PARTITION_SUFFICIENCY_FAILED,
    AnalysisPartitionConfirmRequest,
    AnalysisPartitionDocumentationRequest,
    AnalysisPartitionError,
    AnalysisPartitionPreviewRequest,
    AnalysisPartitionResetPreviewRequest,
)
from server.core.dataset_store import DatasetStore
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.persistence.repositories.analysis_partition_repository import (
    AnalysisPartitionConflictError,
)
from server.persistence.repositories.model_registry_repository import (
    ModelRegistryConflictError,
    _assert_durable_promotion_governance,
)
from server.preprocessing.predictor_authorization import (
    PredictorAuthorizationIntegrityError,
)


partition_router = importlib.import_module("server.analysis_partition.router")


class IsolatedPartitionAuthority:
    def __init__(
        self,
        frame: pd.DataFrame,
        *,
        project_id: str | None = None,
        target: str = "target",
        authorized_predictors: list[str] | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[1] / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"analysis_partition_product_{uuid.uuid4().hex}.db"
        self.database = Database(self.path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.project_id = project_id or f"project-{uuid.uuid4().hex}"
        self.persistence.projects.upsert(
            {
                "project_id": self.project_id,
                "project_name": "Isolated Analysis Partition Product Test",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": "partition-owner",
                "created_by": "partition-owner",
                "updated_by": "partition-owner",
            }
        )
        self.service = AnalysisPartitionService(self.persistence.analysis_partitions)
        self.store = DatasetStore()
        self.store.raw_df = frame.copy(deep=True)
        self.store.target = target
        predictors = authorized_predictors or [
            str(column) for column in frame.columns if str(column) != target
        ]
        self.store.meta.update(
            {
                "project_id": self.project_id,
                "dataset_id": "dataset-isolated",
                "dataset_version_id": "version-isolated-1",
                "target_contract_id": "target-contract-isolated",
                "predictor_authorization_id": "predictor-auth-isolated",
                "selected_columns": predictors,
                "predictor_authorization": {
                    "predictor_authorization_id": "predictor-auth-isolated",
                    "target_contract_id": "target-contract-isolated",
                    "authorized_predictors": predictors,
                },
            }
        )

    def preview_request(self, **changes) -> AnalysisPartitionPreviewRequest:
        payload = {
            "project_id": self.project_id,
            "dataset_id": "dataset-isolated",
            "dataset_version_id": "version-isolated-1",
            "target_contract_id": "target-contract-isolated",
            "target": self.store.target,
            "positive_value": 1,
            "negative_value": 0,
            "predictor_authorization_id": "predictor-auth-isolated",
            "problem_type": "classification",
            "development_share": 0.8,
            "holdout_share": 0.2,
            "random_seed": 42,
            "stratification_policy": "target",
            "stratification_field": self.store.target,
        }
        payload.update(changes)
        return AnalysisPartitionPreviewRequest(**payload)

    def preview(self, **changes):
        request = self.preview_request(**changes)
        return self.service.preview(self.store, request)["preview"]

    def reset_preview_request(self, current, **changes):
        payload = self.preview_request(**changes).model_dump()
        payload.update(
            {
                "expected_current_partition_id": current["analysis_partition_id"],
                "expected_current_revision": current["revision"],
            }
        )
        return AnalysisPartitionResetPreviewRequest(**payload)

    def confirm(self, **changes):
        preview_changes = {
            key: value
            for key, value in changes.items()
            if key
            in {
                "positive_value",
                "negative_value",
                "problem_type",
                "development_share",
                "holdout_share",
                "random_seed",
                "stratification_policy",
                "stratification_field",
                "partition_method",
            }
        }
        preview = self.preview(**preview_changes)
        payload = self.preview_request(**preview_changes).model_dump()
        payload.update(
            {
                "preview_fingerprint": preview["preview_fingerprint"],
                "selection_rationale": "",
                **changes,
            }
        )
        return self.service.confirm(
            self.store,
            AnalysisPartitionConfirmRequest(**payload),
            {"userId": "partition-owner"},
        )

    def close(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)


@pytest.fixture
def binary_authority():
    frame = pd.DataFrame(
        {
            "feature": [float(value) for value in range(200)],
            "group_id": [f"group-{value // 2}" for value in range(200)],
            "target": [value % 2 for value in range(200)],
        },
        index=[f"row-{value}" for value in range(200)],
    )
    authority = IsolatedPartitionAuthority(frame)
    try:
        yield authority
    finally:
        authority.close()


def test_only_three_standard_ratios_are_accepted(binary_authority):
    for development, holdout in ((0.7, 0.3), (0.8, 0.2), (0.9, 0.1)):
        request = binary_authority.preview_request(
            development_share=development,
            holdout_share=holdout,
        )
        preview = binary_authority.service.preview(
            binary_authority.store, request
        )["preview"]
        assert preview["development_rows"] + preview["holdout_rows"] == 200
        assert preview["ratio_label"] == (
            f"{int(development * 100)}/{int(holdout * 100)}"
        )

    with pytest.raises(ValidationError, match="70/30, 80/20, or 90/10"):
        binary_authority.preview_request(
            development_share=0.75,
            holdout_share=0.25,
        )


def test_classification_preview_is_deterministic_complete_and_nonmutating(
    binary_authority,
):
    before_meta = dict(binary_authority.store.meta)
    before_revision = binary_authority.store.data_revision
    first = binary_authority.preview()
    second = binary_authority.preview()

    assert first == second
    assert first["preview_fingerprint"] == second["preview_fingerprint"]
    assert first["total_eligible_rows"] == 200
    assert first["development_rows"] == 160
    assert first["holdout_rows"] == 40
    assert first["development_event_count"] == 80
    assert first["holdout_event_count"] == 20
    assert first["development_non_event_count"] == 80
    assert first["holdout_non_event_count"] == 20
    assert first["absolute_event_rate_difference"] == 0.0
    assert first["partition_method"] == "deterministic_random"
    assert first["sufficiency"]["policy_id"].startswith(
        "atlas.analysis_partition"
    )
    assert first["recommendation_status"] == "acceptable_with_warning"
    assert any("group" in warning.lower() for warning in first["warnings"])
    assert binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    ) is None
    assert binary_authority.store.data_revision == before_revision
    assert binary_authority.store.meta == before_meta


def test_preview_can_resolve_optional_contract_expectations(binary_authority):
    request = binary_authority.preview_request(
        target_contract_id="",
        predictor_authorization_id="",
    )
    preview = binary_authority.service.preview(
        binary_authority.store, request
    )["preview"]
    assert preview["target_contract_id"] == "target-contract-isolated"
    assert preview["predictor_authorization_id"] == "predictor-auth-isolated"


def test_regression_preview_reports_coverage_and_sparse_extreme_warnings():
    target = [float(value) for value in range(99)] + [10_000.0]
    frame = pd.DataFrame(
        {"feature": range(100), "target": target},
        index=[f"reg-{value}" for value in range(100)],
    )
    authority = IsolatedPartitionAuthority(frame)
    try:
        preview = authority.preview(
            problem_type="regression",
            positive_value=None,
            negative_value=None,
            stratification_policy="none",
            stratification_field="",
        )
        assert preview["problem_type"] == "regression"
        assert preview["stratification_field"] is None
        assert preview["target_minimum"] == 0.0
        assert preview["target_maximum"] == 10_000.0
        assert preview["full_target_summary"]["count"] == 100
        assert preview["development_target_summary"]["count"] == 80
        assert preview["holdout_target_summary"]["count"] == 20
        assert 0.0 <= preview["target_band_coverage"]["coverage_rate"] <= 1.0
        assert set(preview["extreme_value_coverage"]) == {
            "low_extreme_represented",
            "high_extreme_represented",
            "status",
        }
        assert preview["preview_fingerprint"] == authority.preview(
            problem_type="regression",
            positive_value=None,
            negative_value=None,
            stratification_policy="none",
            stratification_field="",
        )["preview_fingerprint"]
    finally:
        authority.close()


def test_blocked_preview_cannot_be_sealed_and_stale_fingerprint_is_rejected():
    small = pd.DataFrame(
        {"feature": range(4), "target": [0, 0, 1, 1]},
        index=[f"small-{value}" for value in range(4)],
    )
    authority = IsolatedPartitionAuthority(small)
    try:
        preview = authority.preview(
            development_share=0.9,
            holdout_share=0.1,
        )
        assert preview["recommendation_status"] == "blocked"
        assert preview["blockers"]
        with pytest.raises(AnalysisPartitionError) as captured:
            authority.confirm(
                development_share=0.9,
                holdout_share=0.1,
                selection_rationale="Small holdout requested for test.",
            )
        assert captured.value.code == ANALYSIS_PARTITION_SUFFICIENCY_FAILED
        assert authority.persistence.analysis_partitions.get_current(
            authority.project_id
        ) is None
    finally:
        authority.close()

    frame = pd.DataFrame({"feature": range(100), "target": [0, 1] * 50})
    authority = IsolatedPartitionAuthority(frame)
    try:
        request = authority.preview_request()
        preview = authority.service.preview(authority.store, request)["preview"]
        payload = request.model_dump()
        payload["preview_fingerprint"] = "stale-" + preview["preview_fingerprint"]
        with pytest.raises(AnalysisPartitionError) as captured:
            authority.service.confirm(
                authority.store,
                AnalysisPartitionConfirmRequest(**payload),
                {"userId": "partition-owner"},
            )
        assert captured.value.code == ANALYSIS_PARTITION_PREVIEW_STALE
        assert authority.persistence.analysis_partitions.get_current(
            authority.project_id
        ) is None
    finally:
        authority.close()


def test_nonrecommended_preview_requires_rationale_on_new_contract():
    frame = pd.DataFrame({"feature": range(200), "target": [0, 1] * 100})
    authority = IsolatedPartitionAuthority(frame)
    try:
        preview = authority.preview(
            development_share=0.7,
            holdout_share=0.3,
        )
        assert preview["rationale_required"] is True
        request = authority.preview_request(
            development_share=0.7,
            holdout_share=0.3,
        )
        payload = request.model_dump()
        payload["preview_fingerprint"] = preview["preview_fingerprint"]
        with pytest.raises(AnalysisPartitionError) as captured:
            authority.service.confirm(
                authority.store,
                AnalysisPartitionConfirmRequest(**payload),
                {"userId": "partition-owner"},
            )
        assert captured.value.code == ANALYSIS_PARTITION_SUFFICIENCY_FAILED

        payload["selection_rationale"] = (
            "A larger independent evaluation population is required."
        )
        result = authority.service.confirm(
            authority.store,
            AnalysisPartitionConfirmRequest(**payload),
            {"userId": "partition-owner"},
        )
        assert result["analysis_partition"]["selection_rationale"]
    finally:
        authority.close()


def test_duplicate_and_concurrent_confirmation_is_single_revision(binary_authority):
    request = binary_authority.preview_request()
    preview = binary_authority.service.preview(
        binary_authority.store, request
    )["preview"]
    payload = request.model_dump()
    payload.update(
        {
            "preview_fingerprint": preview["preview_fingerprint"],
            "selection_rationale": (
                "Repeated observation groups are accepted for this fixture."
            ),
        }
    )

    def create():
        return binary_authority.service.confirm(
            binary_authority.store,
            AnalysisPartitionConfirmRequest(**payload),
            {"userId": "partition-owner"},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _value: create(), range(16)))
    identifiers = {
        result["analysis_partition"]["analysis_partition_id"]
        for result in results
    }
    revisions = {
        result["analysis_partition"]["revision"] for result in results
    }
    assert len(identifiers) == 1
    assert revisions == {1}
    assert len(binary_authority.persistence.analysis_partitions.history(
        binary_authority.project_id
    )) == 1


def test_reset_preview_route_is_the_only_postseal_preview_and_is_read_only(
    binary_authority,
):
    current = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )["analysis_partition"]
    ordinary_request = binary_authority.preview_request(
        development_share=0.9,
        holdout_share=0.1,
        random_seed=17,
    )
    reset_request = binary_authority.reset_preview_request(
        current,
        development_share=0.9,
        holdout_share=0.1,
        random_seed=17,
    )
    before_current = deepcopy(
        binary_authority.persistence.analysis_partitions.get_current(
            binary_authority.project_id
        )
    )
    before_history = deepcopy(
        binary_authority.persistence.analysis_partitions.history(
            binary_authority.project_id
        )
    )
    before_meta = deepcopy(binary_authority.store.meta)
    before_revision = binary_authority.store.data_revision
    before_frame = binary_authority.store.raw_df.copy(deep=True)

    def authorize(request, _user, **_kwargs):
        return (
            binary_authority.store,
            request.model_dump(),
            {"activation_revision": 1},
        )

    with (
        patch.object(
            partition_router,
            "analysis_partition_service",
            binary_authority.service,
        ),
        patch.object(
            partition_router,
            "_authoritative_partition_request",
            side_effect=authorize,
        ),
    ):
        with pytest.raises(HTTPException) as ordinary_failure:
            partition_router.preview_analysis_partition(
                ordinary_request,
                {"userId": "partition-owner"},
            )
        first = partition_router.reset_preview_analysis_partition(
            reset_request,
            {"userId": "partition-owner"},
        )
        second = partition_router.reset_preview_analysis_partition(
            reset_request,
            {"userId": "partition-owner"},
        )

    assert ordinary_failure.value.status_code == 409
    assert ordinary_failure.value.detail["code"] == ANALYSIS_PARTITION_CONTRADICTORY
    assert first == second
    assert first["ok"] is True
    assert first["readiness"] == "preview"
    assert first["code"].startswith("analysis_partition_reset_preview_")
    preview = first["preview"]
    assert preview["reset_preview"] is True
    assert preview["expected_current_partition_id"] == current[
        "analysis_partition_id"
    ]
    assert preview["expected_current_revision"] == current["revision"]
    assert preview["preview_fingerprint"] != preview[
        "candidate_preview_fingerprint"
    ]

    assert binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    ) == before_current
    assert binary_authority.persistence.analysis_partitions.history(
        binary_authority.project_id
    ) == before_history
    assert binary_authority.store.meta == before_meta
    assert binary_authority.store.data_revision == before_revision
    pd.testing.assert_frame_equal(binary_authority.store.raw_df, before_frame)


@pytest.mark.parametrize("authority_change", ["wrong_id", "stale_revision"])
def test_reset_preview_rejects_wrong_or_stale_current_authority_before_calculation(
    binary_authority,
    authority_change,
):
    current = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )["analysis_partition"]
    payload = binary_authority.reset_preview_request(
        current,
        random_seed=17,
    ).model_dump()
    if authority_change == "wrong_id":
        payload["expected_current_partition_id"] = "partition-not-current"
    else:
        payload["expected_current_revision"] = current["revision"] + 1
    request = AnalysisPartitionResetPreviewRequest(**payload)
    before_current = deepcopy(
        binary_authority.persistence.analysis_partitions.get_current(
            binary_authority.project_id
        )
    )
    before_history = deepcopy(
        binary_authority.persistence.analysis_partitions.history(
            binary_authority.project_id
        )
    )

    with (
        patch.object(
            partition_router,
            "analysis_partition_service",
            binary_authority.service,
        ),
        patch.object(
            partition_router,
            "_authoritative_partition_request",
            return_value=(binary_authority.store, request.model_dump(), {}),
        ),
        patch.object(
            binary_authority.service,
            "_build_preview",
            wraps=binary_authority.service._build_preview,
        ) as build_preview,
    ):
        with pytest.raises(HTTPException) as captured:
            partition_router.reset_preview_analysis_partition(
                request,
                {"userId": "partition-owner"},
            )

    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == ANALYSIS_PARTITION_CONTRADICTORY
    build_preview.assert_not_called()
    assert binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    ) == before_current
    assert binary_authority.persistence.analysis_partitions.history(
        binary_authority.project_id
    ) == before_history


def test_strict_reset_confirmation_requires_and_accepts_bound_fingerprint(
    binary_authority,
):
    current = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )["analysis_partition"]
    reset_request = binary_authority.reset_preview_request(
        current,
        development_share=0.9,
        holdout_share=0.1,
        random_seed=17,
    )
    reset_preview = binary_authority.service.reset_preview(
        binary_authority.store,
        reset_request,
    )["preview"]
    payload = reset_request.model_dump()
    payload.update(
        {
            "selection_rationale": (
                "The smaller final holdout is sufficient for this isolated test."
            ),
            "reset_existing": True,
            "reset_reason": "An approved deterministic partition redesign is required.",
            "acknowledge_invalidation": True,
        }
    )
    before_current = deepcopy(
        binary_authority.persistence.analysis_partitions.get_current(
            binary_authority.project_id
        )
    )
    before_history = deepcopy(
        binary_authority.persistence.analysis_partitions.history(
            binary_authority.project_id
        )
    )

    with pytest.raises(AnalysisPartitionError) as stale:
        binary_authority.service.confirm(
            binary_authority.store,
            AnalysisPartitionConfirmRequest(
                **{
                    **payload,
                    "preview_fingerprint": reset_preview[
                        "candidate_preview_fingerprint"
                    ],
                }
            ),
            {"userId": "partition-owner"},
            require_preview_contract=True,
        )
    assert stale.value.code == ANALYSIS_PARTITION_PREVIEW_STALE
    assert binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    ) == before_current
    assert binary_authority.persistence.analysis_partitions.history(
        binary_authority.project_id
    ) == before_history

    result = binary_authority.service.confirm(
        binary_authority.store,
        AnalysisPartitionConfirmRequest(
            **{
                **payload,
                "preview_fingerprint": reset_preview["preview_fingerprint"],
            }
        ),
        {"userId": "partition-owner"},
        require_preview_contract=True,
    )
    replacement = result["analysis_partition"]
    durable = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert replacement["analysis_partition_id"] != current[
        "analysis_partition_id"
    ]
    assert replacement["revision"] == current["revision"] + 1
    assert replacement["development_count"] == 180
    assert replacement["holdout_count"] == 20
    assert result["preview"]["preview_fingerprint"] == reset_preview[
        "preview_fingerprint"
    ]
    assert durable["preview_fingerprint"] == reset_preview[
        "candidate_preview_fingerprint"
    ]


def test_reset_requires_exact_current_id_and_revision(binary_authority):
    first = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )["analysis_partition"]
    next_preview = binary_authority.preview(random_seed=17)
    payload = binary_authority.preview_request(random_seed=17).model_dump()
    payload.update(
        {
            "preview_fingerprint": next_preview["preview_fingerprint"],
            "selection_rationale": (
                "Repeated observation groups are accepted for this fixture."
            ),
            "reset_existing": True,
            "reset_reason": "A newly approved deterministic seed is required.",
            "acknowledge_invalidation": True,
            "expected_current_partition_id": first["analysis_partition_id"],
            "expected_current_revision": first["revision"] + 1,
        }
    )
    with pytest.raises(AnalysisPartitionError) as captured:
        binary_authority.service.confirm(
            binary_authority.store,
            AnalysisPartitionConfirmRequest(**payload),
            {"userId": "partition-owner"},
        )
    assert captured.value.code == ANALYSIS_PARTITION_CONTRADICTORY
    assert binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )["analysis_partition_id"] == first["analysis_partition_id"]

    payload["expected_current_revision"] = first["revision"]
    reset = binary_authority.service.confirm(
        binary_authority.store,
        AnalysisPartitionConfirmRequest(**payload),
        {"userId": "partition-owner"},
    )["analysis_partition"]
    assert reset["revision"] == 2
    assert reset["analysis_partition_id"] != first["analysis_partition_id"]


def test_evidence_and_mdd_references_are_durable_and_safe(binary_authority):
    result = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )
    with (
        patch.object(
            partition_router,
            "get_persistence_service",
            return_value=binary_authority.persistence,
        ),
        patch.object(partition_router, "audit_event"),
    ):
        evidence_ref = partition_router._record_partition_evidence(
            result, {"userId": "partition-owner"}
        )
        mdd_ref = partition_router._record_partition_mdd(
            result, {"userId": "partition-owner"}, evidence_ref
        )
    documentation_authority = (
        binary_authority.persistence.analysis_partitions.get_current(
            binary_authority.project_id
        )
    )
    assert documentation_authority is not None
    updated = binary_authority.persistence.analysis_partitions.update_documentation_status(
        result["analysis_partition"]["analysis_partition_id"],
        expected_current=documentation_authority,
        evidence_status="recorded",
        evidence_ref=evidence_ref,
        mdd_status="recorded",
        mdd_ref=mdd_ref,
    )
    safe = binary_authority.service.safe_record(updated)
    assert safe["evidence_status"] == "recorded"
    assert safe["evidence_ref"] == evidence_ref
    assert safe["mdd_status"] == "recorded"
    assert safe["mdd_ref"] == mdd_ref
    with binary_authority.database.connection() as connection:
        section = connection.execute(
            "SELECT * FROM mdd_sections WHERE mdd_section_id = ?", (mdd_ref,)
        ).fetchone()
        link = connection.execute(
            "SELECT * FROM mdd_evidence_links WHERE mdd_section_id = ?",
            (mdd_ref,),
        ).fetchone()
    assert section is not None
    assert link is not None


def test_operational_readiness_waits_for_exact_evidence_and_mdd(binary_authority):
    result = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )
    partition_id = result["analysis_partition"]["analysis_partition_id"]

    with pytest.raises(AnalysisPartitionError) as captured:
        binary_authority.service.current(
            binary_authority.project_id,
            "dataset-isolated",
            "version-isolated-1",
            target="target",
            target_contract_id="target-contract-isolated",
            predictor_authorization_id="predictor-auth-isolated",
            require_documentation_ready=True,
        )
    assert captured.value.code == ANALYSIS_PARTITION_DOCUMENTATION_PENDING
    assert captured.value.identifiers["durable_partition_created"] is True

    # Simulate evidence succeeding before MDD persistence fails.  A retry must
    # preserve the original creation preview rather than replace it with the
    # service's abbreviated idempotent-reuse status.
    with (
        patch.object(
            partition_router,
            "get_persistence_service",
            return_value=binary_authority.persistence,
        ),
        patch.object(partition_router, "audit_event"),
    ):
        first_evidence_ref = partition_router._record_partition_evidence(
            result, {"userId": "partition-owner"}
        )
    original_evidence = binary_authority.persistence.evidence.get(
        first_evidence_ref
    )
    assert original_evidence["payload_json"]["partition_preview"][
        "class_counts"
    ]["holdout"]["event"] > 0

    replay = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )
    assert replay["reused"] is True
    assert replay["analysis_partition"]["analysis_partition_id"] == partition_id
    assert replay["analysis_partition"]["revision"] == 1

    with (
        patch.object(
            partition_router,
            "get_persistence_service",
            return_value=binary_authority.persistence,
        ),
        patch.object(partition_router, "audit_event"),
    ):
        evidence_ref = partition_router._record_partition_evidence(
            replay, {"userId": "partition-owner"}
        )
        assert evidence_ref == first_evidence_ref
        mdd_ref = partition_router._record_partition_mdd(
            replay, {"userId": "partition-owner"}, evidence_ref
        )
    replayed_evidence = binary_authority.persistence.evidence.get(evidence_ref)
    assert replayed_evidence["payload_json"]["partition_preview"][
        "class_counts"
    ]["holdout"]["event"] > 0
    documentation_authority = (
        binary_authority.persistence.analysis_partitions.get_current(
            binary_authority.project_id
        )
    )
    assert documentation_authority is not None
    binary_authority.persistence.analysis_partitions.update_documentation_status(
        partition_id,
        expected_current=documentation_authority,
        evidence_status="recorded",
        evidence_ref=evidence_ref,
        mdd_status="recorded",
        mdd_ref=mdd_ref,
    )

    ready = binary_authority.service.current(
        binary_authority.project_id,
        "dataset-isolated",
        "version-isolated-1",
        target="target",
        target_contract_id="target-contract-isolated",
        predictor_authorization_id="predictor-auth-isolated",
        require_documentation_ready=True,
    )
    assert ready["analysis_partition_id"] == partition_id


def _documentation_request(authority, record):
    return AnalysisPartitionDocumentationRequest(
        project_id=authority.project_id,
        dataset_id=record["dataset_id"],
        dataset_version_id=record["dataset_version_id"],
        target=record["target_column"],
        target_contract_id=record["target_contract_id"],
        predictor_authorization_id=record["predictor_authorization_id"],
        analysis_partition_id=record["analysis_partition_id"],
        revision=record["revision"],
    )


def _documentation_route_patches(authority, record):
    authoritative = {
        "target": record["target_column"],
        "target_contract_id": record["target_contract_id"],
        "predictor_authorization_id": record["predictor_authorization_id"],
    }
    return (
        patch.object(
            partition_router,
            "analysis_partition_service",
            authority.service,
        ),
        patch.object(
            partition_router,
            "get_persistence_service",
            return_value=authority.persistence,
        ),
        patch.object(partition_router, "audit_event"),
        patch.object(
            partition_router,
            "_authoritative_partition_request",
            return_value=(authority.store, authoritative, {}),
        ),
        patch.object(
            partition_router,
            "_authorize_partition_documentation_retry",
            return_value=(authority.store, record),
        ),
    )


def _reset_current_partition(authority, current, *, random_seed=17):
    return authority.confirm(
        random_seed=random_seed,
        selection_rationale=(
            "Repeated observation groups are accepted for this isolated reset."
        ),
        reset_existing=True,
        reset_reason="An isolated race test replaces deterministic membership.",
        acknowledge_invalidation=True,
        expected_current_partition_id=current["analysis_partition_id"],
        expected_current_revision=current["revision"],
    )["analysis_partition"]


def test_status_returns_exact_read_only_partition_while_documentation_is_pending(
    binary_authority,
):
    result = binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    record = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert record is not None
    with (
        _documentation_route_patches(binary_authority, record)[0],
        _documentation_route_patches(binary_authority, record)[3],
    ):
        status = partition_router.analysis_partition_status(
            project_id=binary_authority.project_id,
            dataset_id=record["dataset_id"],
            dataset_version_id=record["dataset_version_id"],
            target=record["target_column"],
            target_contract_id=record["target_contract_id"],
            predictor_authorization_id=record["predictor_authorization_id"],
            user={"userId": "partition-owner"},
        )
    assert status["readiness"] == "documentation_pending"
    assert status["code"] == "analysis_partition_documentation_pending"
    assert "Complete Partition Documentation" in status["recovery"]
    assert status["analysis_partition"]["analysis_partition_id"] == result[
        "analysis_partition"
    ]["analysis_partition_id"]
    assert status["analysis_partition"]["revision"] == 1
    assert status["documentation"]["retryable"] is True
    with pytest.raises(AnalysisPartitionError) as captured:
        binary_authority.service.preview(
            binary_authority.store,
            binary_authority.preview_request(),
            enforce_sealed_holdout=True,
        )
    assert captured.value.code == ANALYSIS_PARTITION_CONTRADICTORY


def test_documentation_retry_is_idempotent_and_never_changes_membership(
    binary_authority,
):
    binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    before = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert before is not None
    request = _documentation_request(binary_authority, before)
    immutable_before = {
        key: before[key]
        for key in (
            "analysis_partition_id",
            "revision",
            "assignment_hash",
            "artifact_hash",
            "row_assignments_json",
        )
    }
    patches = _documentation_route_patches(binary_authority, before)
    with patches[0], patches[1], patches[2], patches[4]:
        first = partition_router.complete_analysis_partition_documentation(
            request,
            user={"userId": "partition-owner"},
        )
        duplicate_results = list(
            ThreadPoolExecutor(max_workers=4).map(
                lambda _index: partition_router.complete_analysis_partition_documentation(
                    request,
                    user={"userId": "partition-owner"},
                ),
                range(4),
            )
        )
    assert first["readiness"] == "current"
    assert first["partition_mutated"] is False
    assert all(item["readiness"] == "current" for item in duplicate_results)
    after = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert after is not None
    assert {
        key: after[key]
        for key in immutable_before
    } == immutable_before
    assert len(binary_authority.persistence.analysis_partitions.history(binary_authority.project_id)) == 1
    assert binary_authority.persistence.analysis_partitions.documentation_readiness(after)[
        "ready"
    ] is True


def test_documentation_retry_failure_stays_pending_with_safe_stage(
    binary_authority,
):
    binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    before = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert before is not None
    request = _documentation_request(binary_authority, before)
    patches = _documentation_route_patches(binary_authority, before)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[4],
        patch.object(
            partition_router,
            "_record_partition_mdd",
            side_effect=RuntimeError("synthetic safe MDD failure"),
        ),
    ):
        with pytest.raises(HTTPException) as captured:
            partition_router.complete_analysis_partition_documentation(
                request,
                user={"userId": "partition-owner"},
            )
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "analysis_partition_documentation_pending"
    assert captured.value.detail["documentation_stage"] == "mdd"
    assert "synthetic" not in str(captured.value.detail)
    after = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert after is not None
    assert after["analysis_partition_id"] == before["analysis_partition_id"]
    assert after["revision"] == before["revision"]
    assert after["assignment_hash"] == before["assignment_hash"]
    assert after["artifact_hash"] == before["artifact_hash"]
    assert after["row_assignments_json"] == before["row_assignments_json"]
    assert after["evidence_status"] == "recorded"
    assert after["mdd_status"] == "pending"


def test_documentation_status_occ_rejects_a_superseded_partition(
    binary_authority,
):
    binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    prior = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert prior is not None
    replacement = _reset_current_partition(binary_authority, prior)
    assert replacement["revision"] == prior["revision"] + 1

    with pytest.raises(AnalysisPartitionConflictError):
        binary_authority.persistence.analysis_partitions.update_documentation_status(
            prior["analysis_partition_id"],
            expected_current=prior,
            evidence_status="pending",
            evidence_ref="",
            mdd_status="pending",
            mdd_ref="",
        )
    durable_prior = binary_authority.persistence.analysis_partitions.get(
        prior["analysis_partition_id"]
    )
    assert durable_prior is not None
    assert durable_prior["status"] == "superseded"
    assert durable_prior["evidence_status"] == "pending"
    assert durable_prior["mdd_status"] == "pending"


def test_documentation_retry_content_never_reads_holdout_target_aggregates(
    binary_authority,
):
    binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    current = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert current is not None

    class HoldoutAggregateGuard(dict):
        def get(self, key, default=None):
            if key == "event_counts_json":
                raise AssertionError(
                    "documentation retry must not read holdout target aggregates"
                )
            return super().get(key, default)

    content = binary_authority.persistence.analysis_partitions.build_mdd_content(
        HoldoutAggregateGuard(current),
        f"ev-{current['analysis_partition_id']}",
        {},
        include_target_distribution=False,
    )
    assert content["target_distribution_or_coverage"] == {
        "status": "retained_in_original_partition_decision_evidence",
        "final_holdout_accessed_during_documentation_retry": False,
    }


def test_documentation_retry_reports_contradictory_when_reset_wins_during_evidence(
    binary_authority,
):
    binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    prior = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert prior is not None
    request = _documentation_request(binary_authority, prior)
    patches = _documentation_route_patches(binary_authority, prior)
    original_record_evidence = partition_router._record_partition_evidence
    replacement = {}

    def record_then_reset(*args, **kwargs):
        evidence_ref = original_record_evidence(*args, **kwargs)
        replacement.update(_reset_current_partition(binary_authority, prior))
        return evidence_ref

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[4],
        patch.object(
            partition_router,
            "_record_partition_evidence",
            side_effect=record_then_reset,
        ),
    ):
        with pytest.raises(HTTPException) as captured:
            partition_router.complete_analysis_partition_documentation(
                request,
                user={"userId": "partition-owner"},
            )
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == ANALYSIS_PARTITION_CONTRADICTORY
    assert replacement["revision"] == prior["revision"] + 1
    assert (
        captured.value.detail["identifiers"]["current_analysis_partition_id"]
        == replacement["analysis_partition_id"]
    )


def test_documentation_retry_final_readback_detects_a_concurrent_reset(
    binary_authority,
):
    binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    prior = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert prior is not None
    request = _documentation_request(binary_authority, prior)
    patches = _documentation_route_patches(binary_authority, prior)
    repository = binary_authority.persistence.analysis_partitions
    original_readiness = repository.documentation_readiness
    calls = {"count": 0}
    replacement = {}

    def reset_after_final_readiness(record):
        result = original_readiness(record)
        calls["count"] += 1
        if calls["count"] == 3:
            replacement.update(
                _reset_current_partition(binary_authority, prior, random_seed=19)
            )
        return result

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[4],
        patch.object(
            repository,
            "documentation_readiness",
            side_effect=reset_after_final_readiness,
        ),
    ):
        with pytest.raises(HTTPException) as captured:
            partition_router.complete_analysis_partition_documentation(
                request,
                user={"userId": "partition-owner"},
            )
    assert calls["count"] == 3
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == ANALYSIS_PARTITION_CONTRADICTORY
    assert replacement["revision"] == prior["revision"] + 1


def test_legacy_v1_pending_documentation_recovers_without_a_new_partition(
    binary_authority,
):
    binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    record = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert record is not None
    service_module = importlib.import_module("server.analysis_partition.service")
    legacy = dict(record)
    legacy["preview_fingerprint"] = ""
    # The additive product column has a NOT NULL default on upgraded stores;
    # v1 lineage is identified by the absent preview fingerprint.
    legacy["problem_type"] = "classification"
    legacy["sufficiency_json"] = {}
    legacy["artifact_hash"] = service_module._stable_hash(
        service_module._artifact_payload(legacy)
    )
    with binary_authority.database.transaction() as connection:
        # Emulate a row created before the v2 columns/immutability trigger
        # existed. This isolated database is deleted by the fixture.
        connection.execute(
            "DROP TRIGGER IF EXISTS trg_analysis_partitions_immutable_contract"
        )
        connection.execute(
            """
            UPDATE analysis_partitions
            SET preview_fingerprint = '', problem_type = 'classification',
                sufficiency_json = '{}', artifact_hash = ?
            WHERE analysis_partition_id = ?
            """,
            (legacy["artifact_hash"], legacy["analysis_partition_id"]),
        )
    legacy = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert legacy is not None
    request = _documentation_request(binary_authority, legacy)
    patches = _documentation_route_patches(binary_authority, legacy)
    with patches[0], patches[1], patches[2], patches[4]:
        completed = partition_router.complete_analysis_partition_documentation(
            request,
            user={"userId": "partition-owner"},
        )
    assert completed["readiness"] == "current"
    assert completed["analysis_partition"]["lineage_contract"] == "analysis_partition_v1"
    after = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert after is not None
    assert after["analysis_partition_id"] == legacy["analysis_partition_id"]
    assert after["revision"] == legacy["revision"]
    assert after["artifact_hash"] == legacy["artifact_hash"]
    assert after["assignment_hash"] == legacy["assignment_hash"]


def test_post_seal_payload_hides_holdout_target_aggregates(binary_authority):
    preview = binary_authority.preview()
    assert preview["holdout_event_count"] > 0
    assert preview["class_counts"]["holdout"]["event"] > 0

    result = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )
    safe = result["analysis_partition"]
    assert set(safe["event_counts"]) == {"development"}
    assert "checks" not in safe["sufficiency"]
    for forbidden in (
        "holdout_event_count",
        "holdout_non_event_count",
        "holdout_event_rate",
        "full_population_event_rate",
        "holdout_target_summary",
        "full_target_summary",
    ):
        assert forbidden not in safe

    durable = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert durable is not None
    assert durable["event_counts_json"]["holdout"]["event"] > 0


def _document_partition(authority, result):
    with (
        patch.object(
            partition_router,
            "get_persistence_service",
            return_value=authority.persistence,
        ),
        patch.object(partition_router, "audit_event"),
    ):
        evidence_ref = partition_router._record_partition_evidence(
            result, {"userId": "partition-owner"}
        )
        mdd_ref = partition_router._record_partition_mdd(
            result, {"userId": "partition-owner"}, evidence_ref
        )
    documentation_authority = authority.persistence.analysis_partitions.get_current(
        authority.project_id
    )
    assert documentation_authority is not None
    return authority.persistence.analysis_partitions.update_documentation_status(
        result["analysis_partition"]["analysis_partition_id"],
        expected_current=documentation_authority,
        evidence_status="recorded",
        evidence_ref=evidence_ref,
        mdd_status="recorded",
        mdd_ref=mdd_ref,
    )


def test_documentation_readiness_rejects_corrupt_mdd_content_and_retry_stays_pending(
    binary_authority,
):
    result = binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    documented = _document_partition(binary_authority, result)
    partition_id = documented["analysis_partition_id"]
    immutable_before = {
        key: documented[key]
        for key in (
            "analysis_partition_id",
            "revision",
            "assignment_hash",
            "artifact_hash",
            "row_assignments_json",
        )
    }
    with binary_authority.database.transaction() as connection:
        row = connection.execute(
            "SELECT content_json FROM mdd_content_blocks WHERE block_id = ?",
            (f"mdd-block-{partition_id}",),
        ).fetchone()
        assert row is not None
        corrupt_content = json.loads(str(row["content_json"] or "{}"))
        corrupt_content["development_count"] = (
            int(corrupt_content["development_count"]) + 1
        )
        connection.execute(
            "UPDATE mdd_content_blocks SET content_json = ? WHERE block_id = ?",
            (
                json.dumps(corrupt_content, sort_keys=True, separators=(",", ":")),
                f"mdd-block-{partition_id}",
            ),
        )

    readiness = binary_authority.persistence.analysis_partitions.documentation_readiness(
        documented
    )
    assert readiness["evidence_ready"] is True
    assert readiness["mdd_section_ready"] is True
    assert readiness["mdd_content_ready"] is False
    assert readiness["mdd_ready"] is False
    assert readiness["ready"] is False

    request = _documentation_request(binary_authority, documented)
    patches = _documentation_route_patches(binary_authority, documented)
    with patches[0], patches[1], patches[2], patches[4]:
        with pytest.raises(HTTPException) as captured:
            partition_router.complete_analysis_partition_documentation(
                request,
                user={"userId": "partition-owner"},
            )
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == ANALYSIS_PARTITION_DOCUMENTATION_PENDING
    assert captured.value.detail["documentation_stage"] == "mdd"
    after = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert after is not None
    assert {key: after[key] for key in immutable_before} == immutable_before


def test_documentation_readiness_rejects_wrong_section_link_and_evidence_hash(
    binary_authority,
):
    result = binary_authority.confirm(
        selection_rationale="Repeated observation groups are accepted for this fixture."
    )
    documented = _document_partition(binary_authority, result)
    partition_id = documented["analysis_partition_id"]
    mdd_ref = documented["mdd_ref"]
    evidence_ref = documented["evidence_ref"]
    repository = binary_authority.persistence.analysis_partitions

    with binary_authority.database.transaction() as connection:
        connection.execute(
            "UPDATE mdd_sections SET title = 'Wrong section' WHERE mdd_section_id = ?",
            (mdd_ref,),
        )
    wrong_section = repository.documentation_readiness(documented)
    assert wrong_section["mdd_section_ready"] is False
    assert wrong_section["ready"] is False

    with binary_authority.database.transaction() as connection:
        connection.execute(
            "UPDATE mdd_sections SET title = ? WHERE mdd_section_id = ?",
            ("Development and Final Evaluation Populations", mdd_ref),
        )
        connection.execute(
            "UPDATE mdd_evidence_links SET evidence_reference_json = ? WHERE mdd_section_id = ?",
            ('{"evidence_id":"wrong-evidence"}', mdd_ref),
        )
    wrong_link = repository.documentation_readiness(documented)
    assert wrong_link["mdd_section_ready"] is True
    assert wrong_link["mdd_evidence_link_ready"] is False
    assert wrong_link["ready"] is False

    with binary_authority.database.transaction() as connection:
        connection.execute(
            "UPDATE mdd_evidence_links SET evidence_reference_json = ? WHERE mdd_section_id = ?",
            (json.dumps({"evidence_id": evidence_ref}), mdd_ref),
        )
        connection.execute(
            "UPDATE evidence_artifacts SET artifact_hash = 'wrong-hash' WHERE evidence_id = ?",
            (evidence_ref,),
        )
    wrong_hash = repository.documentation_readiness(documented)
    assert wrong_hash["evidence_ready"] is False
    assert wrong_hash["mdd_evidence_link_ready"] is False
    assert wrong_hash["ready"] is False


def _seed_exact_partition_derivatives(authority, partition):
    project_id = authority.project_id
    dataset_id = partition["dataset_id"]
    dataset_version_id = partition["dataset_version_id"]
    partition_id = partition["analysis_partition_id"]
    holdout_id = partition["sealed_holdout_partition_id"]
    timestamp = "2026-08-03T12:00:00+00:00"

    authority.persistence.evidence.upsert(
        {
            "evidence_id": "evidence-downstream",
            "project_id": project_id,
            "workflow_type": "predictive_modeling",
            "step_id": "step08",
            "artifact_type": "evaluation",
            "status": "approved",
            "title": "Current evaluation evidence",
            "source_ref": "evaluation-package-1",
            "created_at": timestamp,
            "payload_json": {
                "analysis_partition_id": partition_id,
                "sealed_holdout_partition_id": holdout_id,
            },
        }
    )
    authority.persistence.runs.upsert(
        {
            "run_id": "training-run-1",
            "project_id": project_id,
            "run_type": "model_training",
            "status": "completed",
            "parameters_json": {"analysis_partition_id": partition_id},
            "artifacts_json": {"sealed_holdout_partition_id": holdout_id},
        }
    )
    authority.persistence.decisions.upsert(
        {
            "decision_id": "model-decision-1",
            "project_id": project_id,
            "decision_type": "candidate_selection",
            "title": "Current candidate",
            "status": "approved",
            "created_at": timestamp,
            "updated_at": timestamp,
            "payload_json": {"analysis_partition_id": partition_id},
        }
    )

    with authority.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO candidate_selection_decisions (
              candidate_decision_id, decision_status, project_id, dataset_id,
              dataset_version_id, feature_manifest_id, validation_design_id,
              validation_design_version_id, split_id, training_job_id,
              training_run_id, candidate_id, selection_metric_name,
              selection_metric_value, selection_metric_source,
              selection_partition_id, threshold_source, calibration_source,
              ranking_snapshot_hash, decision_contract_hash,
              final_holdout_partition_id, created_at
            ) VALUES (?, 'legacy_proposal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, 'not_applicable', 'development_only', ?, ?, ?, ?)
            """,
            (
                "candidate-decision-1",
                project_id,
                dataset_id,
                dataset_version_id,
                "feature-manifest-1",
                "validation-design-1",
                "validation-design-version-1",
                "split-1",
                "training-job-1",
                "training-run-1",
                "candidate-1",
                "roc_auc",
                0.75,
                "development_validation",
                "development-partition-1",
                "ranking-hash-1",
                "decision-contract-hash-1",
                holdout_id,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO holdout_exposures (
              holdout_exposure_id, project_id, dataset_id, dataset_version_id,
              validation_design_id, validation_design_version_id, split_id,
              final_holdout_partition_id, candidate_decision_id, candidate_id,
              final_holdout_status, sealed_at, exposure_contract_hash,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sealed', ?, ?, ?, ?)
            """,
            (
                "holdout-exposure-1",
                project_id,
                dataset_id,
                dataset_version_id,
                "validation-design-1",
                "validation-design-version-1",
                "split-1",
                holdout_id,
                "candidate-decision-1",
                "candidate-1",
                timestamp,
                "exposure-contract-hash-1",
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO evaluation_packages (
              evaluation_package_id, package_status, project_id, dataset_id,
              dataset_version_id, feature_manifest_id, validation_design_id,
              validation_design_version_id, split_id, training_job_id,
              training_run_id, candidate_id, candidate_decision_id,
              holdout_exposure_id, final_holdout_partition_id,
              selection_metric_name, selection_metric_value,
              selection_metric_source, evaluation_package_contract_hash,
              content_hash, created_at
            ) VALUES (?, 'legacy_unresolved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evaluation-package-1",
                project_id,
                dataset_id,
                dataset_version_id,
                "feature-manifest-1",
                "validation-design-1",
                "validation-design-version-1",
                "split-1",
                "training-job-1",
                "training-run-1",
                "candidate-1",
                "candidate-decision-1",
                "holdout-exposure-1",
                holdout_id,
                "roc_auc",
                0.75,
                "development_validation",
                "evaluation-contract-hash-1",
                "evaluation-content-hash-1",
                timestamp,
            ),
        )

        document = connection.execute(
            "SELECT mdd_document_id FROM mdd_documents WHERE project_id = ? LIMIT 1",
            (project_id,),
        ).fetchone()
        assert document is not None
        connection.execute(
            """
            INSERT INTO mdd_document_versions (
              mdd_document_version_id, mdd_document_id, version_number,
              status, created_by_user_id, created_at, metadata_json
            ) VALUES (?, ?, 'downstream-1', 'validated', ?, ?, '{}')
            """,
            (
                "mdd-version-downstream",
                document["mdd_document_id"],
                "partition-owner",
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO mdd_sections (
              mdd_section_id, mdd_document_version_id, section_id,
              section_number, title, status, metadata_json
            ) VALUES (?, ?, 'model.evaluation', '8.1', ?, 'approved', ?)
            """,
            (
                "mdd-section-downstream",
                "mdd-version-downstream",
                "Evaluation",
                '{"owner_step":"step08"}',
            ),
        )
        connection.execute(
            """
            UPDATE mdd_documents
            SET current_validated_version_id = ?
            WHERE mdd_document_id = ?
            """,
            ("mdd-version-downstream", document["mdd_document_id"]),
        )

    authority.persistence.models.upsert(
        {
            "model_id": "model-1",
            "project_id": project_id,
            "name": "Current model",
            "problem_type": "classification",
            "status": "active",
            "created_at": timestamp,
        }
    )
    authority.persistence.model_versions.insert(
        {
            "model_version_id": "model-version-1",
            "model_id": "model-1",
            "version_number": 1,
            "training_run_id": "training-run-1",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "feature_manifest_version": "feature-manifest-1",
            "algorithm": "logistic_regression",
            "publication_status": "finalized",
            "lineage_status": "verified",
            "candidate_id": "candidate-1",
            "evaluation_package_id": "evaluation-package-1",
            "candidate_decision_id": "candidate-decision-1",
            "final_holdout_partition_id": holdout_id,
            "created_at": timestamp,
        }
    )
    authority.persistence.models.upsert(
        {
            "model_id": "model-1",
            "project_id": project_id,
            "name": "Current model",
            "problem_type": "classification",
            "status": "active",
            "current_version_id": "model-version-1",
            "current_version_generation": 1,
            "created_at": timestamp,
        }
    )
    authority.persistence.scoring_runs.upsert(
        {
            "scoring_run_id": "scoring-run-1",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "partition": "test",
            "model_id": "model-1",
            "model_version_id": "model-version-1",
            "status": "completed",
            "created_at": timestamp,
        }
    )


def test_reset_is_revisioned_and_invalidates_exact_durable_inventory(binary_authority):
    initial_result = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )
    initial = _document_partition(binary_authority, initial_result)
    _seed_exact_partition_derivatives(binary_authority, initial)

    assert binary_authority.persistence.holdout_governance.get_selection_decision(
        "candidate-decision-1"
    ) is not None
    assert binary_authority.persistence.holdout_governance.get_evaluation_package(
        "evaluation-package-1"
    ) is not None

    preview = binary_authority.preview(random_seed=17)
    payload = binary_authority.preview_request(random_seed=17).model_dump()
    payload.update(
        {
            "preview_fingerprint": preview["preview_fingerprint"],
            "selection_rationale": "A new governed deterministic seed is required.",
            "reset_existing": True,
            "reset_reason": "Approved isolated reset test.",
            "acknowledge_invalidation": True,
            "expected_current_partition_id": initial["analysis_partition_id"],
            "expected_current_revision": initial["revision"],
        }
    )
    external_inventory = [
        {
            "artifact_type": artifact_type,
            "artifact_id": f"{artifact_type}-current",
            "source_authority": source,
            "prior_status": "current",
            "invalidation_status": "invalidated",
        }
        for artifact_type, source in (
            ("eda_document", "file:eda"),
            ("feature_manifest", "file:feature_manifest"),
            ("validation_design", "runtime:result_store"),
            ("training_job", "runtime:result_store"),
        )
    ]
    response = binary_authority.service.confirm(
        binary_authority.store,
        AnalysisPartitionConfirmRequest(**payload),
        {"userId": "partition-owner"},
        before_reset_persist=lambda: {"inventory": external_inventory},
    )
    replacement = response["analysis_partition"]
    reset_transition = response["reset_invalidation"]
    receipt = reset_transition["receipt"]

    assert replacement["revision"] == initial["revision"] + 1
    assert replacement["analysis_partition_id"] != initial["analysis_partition_id"]
    assert receipt["atomic_sqlite_transaction"] is True
    assert receipt["external_state_compensation_required"] is True

    history = binary_authority.persistence.analysis_partitions.history(
        binary_authority.project_id
    )
    assert [row["status"] for row in history] == ["superseded", "current"]
    assert history[0]["final_holdout_status"] == "sealed"
    assert history[0]["event_counts_json"] == initial["event_counts_json"]
    assert history[0]["evidence_ref"] == initial["evidence_ref"]
    assert history[0]["mdd_ref"] == initial["mdd_ref"]

    operations = binary_authority.persistence.analysis_partitions.reset_operations(
        binary_authority.project_id
    )
    assert len(operations) == 1
    operation = operations[0]
    assert operation["operation_kind"] == "reset_replace"
    assert operation["operation_status"] == "committed"
    assert operation["actor_user_id"] == "partition-owner"
    assert operation["rationale"] == "Approved isolated reset test."
    ledger = binary_authority.persistence.analysis_partitions.derivative_invalidations(
        operation["reset_operation_id"]
    )
    ledger_types = {row["artifact_type"] for row in ledger}
    assert {
        "analysis_partition_evidence",
        "analysis_partition_mdd_section",
        "evidence",
        "run_record",
        "decision",
        "candidate_decision",
        "holdout_exposure",
        "evaluation_package",
        "model_version",
        "model_current_binding",
        "scoring_run",
        "mdd_section",
        "eda_document",
        "feature_manifest",
        "validation_design",
        "training_job",
    }.issubset(ledger_types)
    preserved = {
        row["artifact_type"]: row["invalidation_status"] for row in ledger
    }
    assert preserved["analysis_partition_evidence"] == "preserved_history"
    assert preserved["analysis_partition_mdd_section"] == "preserved_history"

    assert binary_authority.persistence.evidence.get(initial["evidence_ref"])[
        "status"
    ] == "approved"
    assert binary_authority.persistence.evidence.get("evidence-downstream")[
        "status"
    ] == "stale"
    assert binary_authority.persistence.runs.get("training-run-1")["status"] == "invalidated"
    assert binary_authority.persistence.decisions.get("model-decision-1")["status"] == "stale"
    assert binary_authority.persistence.holdout_governance.get_holdout_exposure(
        "holdout-exposure-1"
    )["final_holdout_status"] == "invalidated"
    assert binary_authority.persistence.holdout_governance.get_selection_decision(
        "candidate-decision-1"
    ) is None
    assert binary_authority.persistence.holdout_governance.get_evaluation_package(
        "evaluation-package-1"
    ) is None
    with binary_authority.database.connection() as connection:
        with pytest.raises(
            ModelRegistryConflictError,
            match="invalidated by an Analysis Partition reset",
        ):
            _assert_durable_promotion_governance(
                connection,
                {
                    "lineage_json": {},
                    "candidate_decision_id": "candidate-decision-1",
                    "evaluation_package_id": "evaluation-package-1",
                },
            )
    assert binary_authority.persistence.model_versions.get("model-version-1")[
        "publication_status"
    ] == "invalidated"
    assert binary_authority.persistence.models.get("model-1")["current_version_id"] is None
    assert binary_authority.persistence.scoring_runs.get("scoring-run-1")[
        "status"
    ] == "invalidated"
    with binary_authority.database.connection() as connection:
        partition_mdd = connection.execute(
            "SELECT status FROM mdd_sections WHERE mdd_section_id = ?",
            (initial["mdd_ref"],),
        ).fetchone()
        downstream_mdd = connection.execute(
            "SELECT status FROM mdd_sections WHERE mdd_section_id = 'mdd-section-downstream'"
        ).fetchone()
        immutable_candidate = connection.execute(
            "SELECT decision_status FROM candidate_selection_decisions WHERE candidate_decision_id = 'candidate-decision-1'"
        ).fetchone()
        immutable_package = connection.execute(
            "SELECT package_status FROM evaluation_packages WHERE evaluation_package_id = 'evaluation-package-1'"
        ).fetchone()
    assert partition_mdd["status"] == "working_draft"
    assert downstream_mdd["status"] == "stale"
    assert immutable_candidate["decision_status"] == "legacy_proposal"
    assert immutable_package["package_status"] == "legacy_unresolved"

    replacement_durable = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    next_inventory = binary_authority.persistence.analysis_partitions.inventory_downstream(
        replacement_durable
    )
    next_ids = {row["artifact_id"] for row in next_inventory}
    assert "candidate-decision-1" not in next_ids
    assert "evaluation-package-1" not in next_ids
    assert initial["evidence_ref"] not in next_ids
    assert initial["mdd_ref"] not in next_ids


def test_reset_compensates_external_state_when_relational_commit_fails(binary_authority):
    initial = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )["analysis_partition"]
    preview = binary_authority.preview(random_seed=17)
    payload = binary_authority.preview_request(random_seed=17).model_dump()
    payload.update(
        {
            "preview_fingerprint": preview["preview_fingerprint"],
            "selection_rationale": "A new governed deterministic seed is required.",
            "reset_existing": True,
            "reset_reason": "Injected persistence failure.",
            "acknowledge_invalidation": True,
            "expected_current_partition_id": initial["analysis_partition_id"],
            "expected_current_revision": initial["revision"],
        }
    )
    external = {"state": "current", "compensations": 0}

    def transition():
        external["state"] = "invalidated"

        def compensate():
            external["state"] = "current"
            external["compensations"] += 1

        return {
            "inventory": [
                {
                    "artifact_type": "eda_document",
                    "artifact_id": "eda-current",
                    "source_authority": "file:eda",
                    "prior_status": "current",
                    "invalidation_status": "invalidated",
                }
            ],
            "compensate": compensate,
        }

    with patch.object(
        binary_authority.persistence.analysis_partitions,
        "create_or_reuse",
        side_effect=RuntimeError("injected relational failure"),
    ):
        with pytest.raises(RuntimeError, match="injected relational failure"):
            binary_authority.service.confirm(
                binary_authority.store,
                AnalysisPartitionConfirmRequest(**payload),
                {"userId": "partition-owner"},
                before_reset_persist=transition,
            )

    assert external == {"state": "current", "compensations": 1}
    current = binary_authority.persistence.analysis_partitions.get_current(
        binary_authority.project_id
    )
    assert current["analysis_partition_id"] == initial["analysis_partition_id"]
    assert current["revision"] == 1
    assert binary_authority.persistence.analysis_partitions.reset_operations(
        binary_authority.project_id
    ) == []


def test_standalone_invalidation_uses_same_coordinated_ledger(binary_authority):
    initial = binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )["analysis_partition"]
    external = {"state": "current"}

    def transition():
        external["state"] = "invalidated"
        return {
            "inventory": [
                {
                    "artifact_type": "feature_manifest",
                    "artifact_id": "feature-manifest-current",
                    "source_authority": "file:feature_manifest",
                    "prior_status": "current",
                    "invalidation_status": "invalidated",
                }
            ],
            "compensate": lambda: external.update(state="current"),
        }

    result = binary_authority.service.invalidate(
        binary_authority.project_id,
        "Exact target contract was withdrawn.",
        {"userId": "partition-owner"},
        expected_dataset_id="dataset-isolated",
        expected_dataset_version_id="version-isolated-1",
        target="target",
        store=binary_authority.store,
        expected_current_partition_id=initial["analysis_partition_id"],
        expected_current_revision=initial["revision"],
        before_invalidation_persist=transition,
    )

    assert result["code"] == "analysis_partition_invalidated"
    assert external["state"] == "invalidated"
    operations = binary_authority.persistence.analysis_partitions.reset_operations(
        binary_authority.project_id
    )
    assert len(operations) == 1
    assert operations[0]["operation_kind"] == "invalidate_only"
    ledger = binary_authority.persistence.analysis_partitions.derivative_invalidations(
        operations[0]["reset_operation_id"]
    )
    assert any(
        row["artifact_type"] == "feature_manifest"
        and row["artifact_id"] == "feature-manifest-current"
        for row in ledger
    )


def test_mapping_is_bound_to_fingerprint_and_missing_predictors_fail_closed(
    binary_authority,
):
    first = binary_authority.preview()
    swapped = binary_authority.preview(positive_value=0, negative_value=1)
    assert first["preview_fingerprint"] != swapped["preview_fingerprint"]

    binary_authority.store.meta["predictor_authorization"][
        "authorized_predictors"
    ] = ["feature", "missing_authorized_field"]
    with pytest.raises(AnalysisPartitionError) as captured:
        binary_authority.preview()
    assert captured.value.code == "predictor_authorization_required"
    assert captured.value.identifiers["missing_authorized_predictors"] == [
        "missing_authorized_field"
    ]


def test_nonfinite_regression_is_a_structured_blocker_not_a_binning_crash():
    frame = pd.DataFrame(
        {
            "feature": range(80),
            "target": [float(value) for value in range(77)]
            + [float("nan"), float("inf"), float("-inf")],
        }
    )
    authority = IsolatedPartitionAuthority(frame)
    try:
        preview = authority.preview(
            problem_type="regression",
            positive_value=None,
            negative_value=None,
            stratification_policy="none",
            stratification_field="",
        )
        assert preview["invalid_target_value_count"] == 3
        assert preview["recommendation_status"] == "blocked"
        assert any("non-finite" in item for item in preview["blockers"])
    finally:
        authority.close()


def test_production_boundary_requires_fingerprint_and_disables_postseal_preview(
    binary_authority,
):
    with pytest.raises(AnalysisPartitionError) as missing:
        binary_authority.service.confirm(
            binary_authority.store,
            AnalysisPartitionConfirmRequest(
                **binary_authority.preview_request().model_dump()
            ),
            {"userId": "partition-owner"},
            require_preview_contract=True,
        )
    assert missing.value.code == ANALYSIS_PARTITION_PREVIEW_STALE
    assert missing.value.status_code == 422

    binary_authority.confirm(
        selection_rationale=(
            "Repeated observation groups are accepted for this fixture."
        )
    )
    with pytest.raises(AnalysisPartitionError) as sealed:
        binary_authority.service.preview(
            binary_authority.store,
            binary_authority.preview_request(random_seed=99),
            enforce_sealed_holdout=True,
        )
    assert sealed.value.code == ANALYSIS_PARTITION_CONTRADICTORY
    assert "alternate" in sealed.value.message.lower()


def _mock_durable_manifest(authority: IsolatedPartitionAuthority) -> dict:
    return {
        "project_id": authority.project_id,
        "dataset_id": "dataset-isolated",
        "dataset_version_id": "version-isolated-1",
        "target_contract_id": "target-contract-isolated",
        "target": "target",
        "positive_value": 1,
        "negative_value": 0,
        "predictor_authorization_id": "predictor-auth-isolated",
        "authorized_predictors": ["feature", "group_id"],
    }


def test_router_authority_rejects_inactive_stale_and_spoofed_contracts(
    binary_authority,
):
    identity = {
        "project_id": binary_authority.project_id,
        "dataset_id": "dataset-isolated",
        "dataset_version_id": "version-isolated-1",
        "activation_revision": 3,
    }
    persistence = Mock()
    persistence.predictor_authorizations.get_current_exact.return_value = {}
    datastore = Mock(current=Mock(return_value=binary_authority.store))
    request = binary_authority.preview_request()

    with (
        patch.object(partition_router, "authorize_modeling_scope"),
        patch.object(partition_router, "DATASTORE", datastore),
        patch.object(
            partition_router,
            "assert_expected_active_identity",
            side_effect=HTTPException(status_code=409, detail="inactive exact version"),
        ),
    ):
        with pytest.raises(HTTPException) as inactive:
            partition_router._authoritative_partition_request(
                request, {"userId": "partition-owner"}, permission="view"
            )
    assert inactive.value.status_code == 409

    with (
        patch.object(partition_router, "authorize_modeling_scope"),
        patch.object(partition_router, "DATASTORE", datastore),
        patch.object(
            partition_router,
            "assert_expected_active_identity",
            return_value=identity,
        ),
        patch.object(
            partition_router, "get_persistence_service", return_value=persistence
        ),
        patch.object(
            partition_router,
            "verify_durable_predictor_authorization",
            side_effect=PredictorAuthorizationIntegrityError("stale checksum"),
        ),
    ):
        with pytest.raises(AnalysisPartitionError) as stale:
            partition_router._authoritative_partition_request(
                request, {"userId": "partition-owner"}, permission="view"
            )
    assert stale.value.code == "predictor_authorization_required"

    manifest = _mock_durable_manifest(binary_authority)
    before_meta = dict(binary_authority.store.meta)
    before_target = binary_authority.store.target
    with (
        patch.object(partition_router, "authorize_modeling_scope"),
        patch.object(partition_router, "DATASTORE", datastore),
        patch.object(
            partition_router,
            "assert_expected_active_identity",
            return_value=identity,
        ),
        patch.object(
            partition_router, "get_persistence_service", return_value=persistence
        ),
        patch.object(
            partition_router,
            "verify_durable_predictor_authorization",
            return_value=manifest,
        ),
    ):
        calculation_store, authoritative, _ = (
            partition_router._authoritative_partition_request(
                request, {"userId": "partition-owner"}, permission="view"
            )
        )
        assert calculation_store is not binary_authority.store
        assert authoritative["problem_type"] == "classification"
        assert binary_authority.store.meta == before_meta
        assert binary_authority.store.target == before_target

        spoofed = request.model_copy(
            update={"problem_type": "regression", "positive_value": 0}
        )
        with pytest.raises(AnalysisPartitionError) as spoof:
            partition_router._authoritative_partition_request(
                spoofed, {"userId": "partition-owner"}, permission="view"
            )
    assert spoof.value.code == "target_contract_stale"

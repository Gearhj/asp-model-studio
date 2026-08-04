from __future__ import annotations

import copy
import importlib
import inspect
import math
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from server.analysis_partition.service import (
    AnalysisPartitionService,
    analysis_partition_service,
)
from server.analysis_partition.types import (
    ANALYSIS_PARTITION_CONTRADICTORY,
    PREDICTOR_AUTHORIZATION_REQUIRED,
    AnalysisPartitionConfirmRequest,
    AnalysisPartitionError,
    AnalysisPartitionPreviewRequest,
)
from server.core.dataset_store import DatasetStore
from server.persistence.db import Database
from server.persistence.service import PersistenceService


RATIOS = ((0.7, 0.3), (0.8, 0.2), (0.9, 0.1))
PREVIEW_REPETITIONS = 25
CREATE_REPETITIONS = 10
RELOAD_REPETITIONS = 10
RESTART_REPETITIONS = 5


@dataclass
class IsolatedScope:
    project_id: str
    dataset_id: str
    dataset_version_id: str
    target_contract_id: str
    predictor_authorization_id: str
    target: str
    problem_type: str
    positive_value: Any
    negative_value: Any
    predictors: list[str]
    store: DatasetStore


def _classification_frames() -> dict[str, Callable[[], pd.DataFrame]]:
    return {
        "balanced_binary": lambda: pd.DataFrame(
            {
                "feature": np.arange(600, dtype=float),
                "companion": np.sin(np.arange(600) / 11.0),
                "target": np.tile([0, 1], 300),
            }
        ),
        "moderately_imbalanced_binary": lambda: pd.DataFrame(
            {
                "feature": np.arange(800, dtype=float),
                "companion": np.cos(np.arange(800) / 17.0),
                "target": (np.arange(800) % 5 == 0).astype(int),
            }
        ),
        "rare_event_binary": lambda: pd.DataFrame(
            {
                "feature": np.arange(1_200, dtype=float),
                "companion": np.log1p(np.arange(1_200)),
                "target": (np.arange(1_200) % 40 == 0).astype(int),
            }
        ),
        "small_binary": lambda: pd.DataFrame(
            {
                "feature": np.arange(40, dtype=float),
                "companion": np.arange(40, dtype=float) ** 2,
                "target": np.tile([0, 1], 20),
            }
        ),
        "grouped_observations": lambda: pd.DataFrame(
            {
                "feature": np.arange(600, dtype=float),
                "companion": np.repeat(np.arange(200), 3),
                "group_id": np.repeat([f"group-{index:03d}" for index in range(200)], 3),
                "target": np.tile([0, 0, 1], 200),
            }
        ),
    }


def _regression_frames() -> dict[str, Callable[[], pd.DataFrame]]:
    return {
        "well_distributed_continuous": lambda: pd.DataFrame(
            {
                "feature": np.arange(600, dtype=float),
                "companion": np.cos(np.arange(600) / 13.0),
                "target": np.linspace(-4.0, 8.0, 600),
            }
        ),
        "skewed_target": lambda: pd.DataFrame(
            {
                "feature": np.arange(720, dtype=float),
                "companion": np.sin(np.arange(720) / 19.0),
                "target": np.exp(np.linspace(0.0, 5.0, 720)),
            }
        ),
        "small_regression": lambda: pd.DataFrame(
            {
                "feature": np.arange(42, dtype=float),
                "companion": np.arange(42, dtype=float) % 7,
                "target": np.linspace(0.25, 9.75, 42),
            }
        ),
        "sparse_extremes": lambda: pd.DataFrame(
            {
                "feature": np.arange(640, dtype=float),
                "companion": np.sqrt(np.arange(640)),
                "target": np.concatenate(
                    [np.linspace(-1.0, 1.0, 632), np.array([-25.0, -18.0, -12.0, -8.0, 9.0, 14.0, 21.0, 30.0])]
                ),
            }
        ),
    }


class TestAnalysisPartitionProductMatrix:
    def setup_method(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        isolated_temp_root = repository_root / ".tmp" / "analysis-partition-product-matrix"
        isolated_temp_root.mkdir(parents=True, exist_ok=True)
        self.root = (
            isolated_temp_root / f"atlas-analysis-partition-product-{uuid.uuid4().hex}"
        ).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.database_path = self.root / "authority.sqlite3"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.service = AnalysisPartitionService(self.persistence.analysis_partitions)

        assert self.root != repository_root
        assert isolated_temp_root.resolve() in self.database_path.parents
        assert self.database_path.name == "authority.sqlite3"
        assert self.database_path != (repository_root / "server" / "data" / "atlas.sqlite3")

    def teardown_method(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _scope(
        self,
        frame: pd.DataFrame,
        *,
        problem_type: str,
        owner: str = "analysis-partition-matrix-owner",
        project_id: str | None = None,
    ) -> IsolatedScope:
        token = uuid.uuid4().hex
        project = project_id or f"project-{token}"
        dataset_id = f"dataset-{token}"
        dataset_version_id = f"version-{token}"
        target_contract_id = f"target-contract-{token}"
        predictor_authorization_id = f"predictor-auth-{token}"
        target = "target"
        predictors = [column for column in frame.columns if column != target]
        self.persistence.projects.upsert(
            {
                "project_id": project,
                "project_name": f"Isolated matrix {token}",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": owner,
                "created_by": owner,
                "updated_by": owner,
            }
        )
        store = DatasetStore()
        store.raw_df = frame.copy(deep=True)
        store.target = target
        authorization = {
            "project_id": project,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "target_contract_id": target_contract_id,
            "target": target,
            "predictor_authorization_id": predictor_authorization_id,
            "authorized_predictors": predictors,
            "selected_predictors": predictors,
            "status": "current",
        }
        store.meta.update(
            {
                "project_id": project,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "target_contract_id": target_contract_id,
                "predictor_authorization_id": predictor_authorization_id,
                "predictor_authorization": authorization,
                "selected_columns": predictors,
                "problem_type": problem_type,
            }
        )
        return IsolatedScope(
            project_id=project,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            target_contract_id=target_contract_id,
            predictor_authorization_id=predictor_authorization_id,
            target=target,
            problem_type=problem_type,
            positive_value=1 if problem_type == "classification" else None,
            negative_value=0 if problem_type == "classification" else None,
            predictors=predictors,
            store=store,
        )

    @staticmethod
    def _clone_store(source: DatasetStore) -> DatasetStore:
        clone = DatasetStore()
        clone.raw_df = source.raw_df.copy(deep=True)
        clone.processed_df = (
            source.processed_df.copy(deep=True)
            if isinstance(source.processed_df, pd.DataFrame)
            else None
        )
        clone.target = source.target
        clone.meta = copy.deepcopy(source.meta)
        return clone

    @staticmethod
    def _preview_request(
        scope: IsolatedScope,
        development_share: float,
        holdout_share: float,
    ) -> AnalysisPartitionPreviewRequest:
        return AnalysisPartitionPreviewRequest(
            project_id=scope.project_id,
            dataset_id=scope.dataset_id,
            dataset_version_id=scope.dataset_version_id,
            target_contract_id=scope.target_contract_id,
            target=scope.target,
            problem_type=scope.problem_type,
            positive_value=scope.positive_value,
            negative_value=scope.negative_value,
            predictor_authorization_id=scope.predictor_authorization_id,
            development_share=development_share,
            holdout_share=holdout_share,
            random_seed=42,
            stratification_policy=(
                "target" if scope.problem_type == "classification" else "none"
            ),
            stratification_field=(
                scope.target if scope.problem_type == "classification" else ""
            ),
            partition_method="deterministic_random",
        )

    @staticmethod
    def _confirm_request(
        scope: IsolatedScope,
        development_share: float,
        holdout_share: float,
    ) -> AnalysisPartitionConfirmRequest:
        return AnalysisPartitionConfirmRequest(
            project_id=scope.project_id,
            dataset_id=scope.dataset_id,
            dataset_version_id=scope.dataset_version_id,
            target_contract_id=scope.target_contract_id,
            target=scope.target,
            problem_type=scope.problem_type,
            positive_value=scope.positive_value,
            negative_value=scope.negative_value,
            predictor_authorization_id=scope.predictor_authorization_id,
            development_share=development_share,
            holdout_share=holdout_share,
            random_seed=42,
            stratification_policy=(
                "target" if scope.problem_type == "classification" else "none"
            ),
            stratification_field=(
                scope.target if scope.problem_type == "classification" else ""
            ),
            partition_method="deterministic_random",
            selection_rationale=(
                "Isolated matrix exercise of a supported standard ratio."
            ),
            # The button is the affirmative governed action. A second mandatory
            # acknowledgement is intentionally absent from this test contract.
            confirmation_acknowledged=False,
        )

    def _preview(
        self,
        store: DatasetStore,
        request: AnalysisPartitionPreviewRequest,
    ) -> dict[str, Any]:
        response = self.service.preview(store, request)
        assert response["ok"] is True
        assert response["readiness"] == "preview"
        assert response["code"] in {
            "analysis_partition_preview_ready",
            "analysis_partition_preview_blocked",
        }
        return response["preview"]

    def _assert_common_preview(
        self,
        preview: dict[str, Any],
        *,
        scope: IsolatedScope,
        development_share: float,
        holdout_share: float,
    ) -> None:
        assert preview["project_id"] == scope.project_id
        assert preview["dataset_id"] == scope.dataset_id
        assert preview["dataset_version_id"] == scope.dataset_version_id
        assert preview["target_contract_id"] == scope.target_contract_id
        assert preview["target"] == scope.target
        assert preview["problem_type"] == scope.problem_type
        assert preview["development_share"] == pytest.approx(development_share)
        assert preview["holdout_share"] == pytest.approx(holdout_share)
        assert preview["random_seed"] == 42
        assert preview["partition_method"] == "deterministic_random"
        assert preview["total_eligible_rows"] == len(scope.store.raw_df)
        assert preview["development_rows"] + preview["holdout_rows"] == len(
            scope.store.raw_df
        )
        assert preview["holdout_rows"] == math.ceil(
            len(scope.store.raw_df) * holdout_share
        )
        assert preview["recommendation_status"] in {
            "recommended",
            "acceptable",
            "acceptable_with_warning",
            "blocked",
        }
        assert isinstance(preview["rationale_required"], bool)
        assert isinstance(preview["warnings"], list)
        assert isinstance(preview["blockers"], list)
        assert isinstance(preview["preview_fingerprint"], str)
        assert len(preview["preview_fingerprint"]) >= 40
        assert preview["sufficiency"]["policy_id"]
        assert preview["sufficiency"]["policy_version"]
        if preview["recommendation_status"] == "blocked":
            assert preview["blockers"]

    def test_preview_matrix_is_deterministic_backend_authoritative_and_nonmutating(
        self,
    ) -> None:
        fixtures: list[tuple[str, str, Callable[[], pd.DataFrame]]] = [
            *(('classification', name, factory) for name, factory in _classification_frames().items()),
            *(('regression', name, factory) for name, factory in _regression_frames().items()),
        ]
        for problem_type, fixture_name, factory in fixtures:
            for development_share, holdout_share in RATIOS:
                scope = self._scope(factory(), problem_type=problem_type)
                request = self._preview_request(
                    scope, development_share, holdout_share
                )
                meta_before = copy.deepcopy(scope.store.meta)
                revision_before = int(scope.store.data_revision)
                frame_before = scope.store.raw_df.copy(deep=True)
                previews = [
                    self._preview(scope.store, request)
                    for _ in range(PREVIEW_REPETITIONS)
                ]
                fingerprints = {
                    preview["preview_fingerprint"] for preview in previews
                }
                assert len(fingerprints) == 1, (
                    problem_type,
                    fixture_name,
                    holdout_share,
                )
                preview = previews[0]
                self._assert_common_preview(
                    preview,
                    scope=scope,
                    development_share=development_share,
                    holdout_share=holdout_share,
                )
                assert scope.store.meta == meta_before
                assert scope.store.data_revision == revision_before
                pd.testing.assert_frame_equal(scope.store.raw_df, frame_before)
                assert all(part is None for part in scope.store.get_splits())
                assert self.persistence.analysis_partitions.get_current(
                    scope.project_id
                ) is None
                assert self.persistence.evidence.list_for_project(
                    scope.project_id
                ) == []
                assert self.persistence.documentation.list_for_project(
                    scope.project_id
                ) == []

                if problem_type == "classification":
                    for population in ("development", "holdout"):
                        assert preview[f"{population}_event_count"] >= 0
                        assert preview[f"{population}_non_event_count"] >= 0
                        assert preview[f"{population}_event_rate"] is not None
                    assert preview["full_population_event_rate"] is not None
                    assert preview["absolute_event_rate_difference"] >= 0
                    assert preview["minimum_event_count_status"]
                    assert preview["minimum_non_event_count_status"]
                    assert preview["stratification_field"] == scope.target
                else:
                    assert preview["target_minimum"] is not None
                    assert preview["target_maximum"] is not None
                    assert preview["target_mean"] is not None
                    assert preview["target_standard_deviation"] is not None
                    assert preview["target_quantiles"]
                    assert preview["target_band_coverage"]
                    assert preview["extreme_value_coverage"]

                if fixture_name == "grouped_observations":
                    assert preview["warnings"], (
                        "A row-random standard partition must warn when repeated "
                        "group identifiers can cross populations."
                    )

    def test_ratio_change_changes_preview_while_default_is_recommended(self) -> None:
        scope = self._scope(
            _classification_frames()["balanced_binary"](),
            problem_type="classification",
        )
        previews = {
            holdout_share: self._preview(
                scope.store,
                self._preview_request(scope, development_share, holdout_share),
            )
            for development_share, holdout_share in RATIOS
        }
        assert previews[0.2]["recommendation_status"] == "recommended"
        assert previews[0.2]["rationale_required"] is False
        assert previews[0.3]["preview_fingerprint"] != previews[0.2]["preview_fingerprint"]
        assert previews[0.1]["preview_fingerprint"] != previews[0.2]["preview_fingerprint"]
        assert previews[0.3]["holdout_rows"] > previews[0.2]["holdout_rows"]
        assert previews[0.1]["holdout_rows"] < previews[0.2]["holdout_rows"]
        for share in (0.3, 0.1):
            if previews[share]["recommendation_status"] != "blocked":
                assert previews[share]["rationale_required"] is True

    def test_creation_reload_and_service_reconstruction_matrix(self) -> None:
        factories = {
            "classification": _classification_frames()["balanced_binary"],
            "regression": _regression_frames()["well_distributed_continuous"],
        }
        for problem_type, factory in factories.items():
            for development_share, holdout_share in RATIOS:
                for _ in range(CREATE_REPETITIONS):
                    scope = self._scope(factory(), problem_type=problem_type)
                    preview = self._preview(
                        scope.store,
                        self._preview_request(
                            scope, development_share, holdout_share
                        ),
                    )
                    assert preview["recommendation_status"] != "blocked"
                    response = self.service.confirm(
                        scope.store,
                        self._confirm_request(
                            scope, development_share, holdout_share
                        ),
                        {"userId": "analysis-partition-matrix-owner"},
                    )
                    partition = response["analysis_partition"]
                    assert response["reused"] is False
                    assert partition["revision"] == 1
                    assert partition["preview_fingerprint"] == preview["preview_fingerprint"]
                    assert partition["development_count"] == preview["development_rows"]
                    assert partition["holdout_count"] == preview["holdout_rows"]
                    assert partition["final_holdout_status"] == "sealed"
                    assert partition["holdout_isolation_status"] == "verified"

                    for _ in range(RELOAD_REPETITIONS):
                        current = self.service.current(
                            scope.project_id,
                            scope.dataset_id,
                            scope.dataset_version_id,
                            target=scope.target,
                            target_contract_id=scope.target_contract_id,
                            predictor_authorization_id=scope.predictor_authorization_id,
                        )
                        assert current["analysis_partition_id"] == partition["analysis_partition_id"]
                        assert current["revision"] == 1

                    for _ in range(RESTART_REPETITIONS):
                        reconstructed = AnalysisPartitionService(
                            PersistenceService(Database(self.database_path)).analysis_partitions
                        )
                        current = reconstructed.current(
                            scope.project_id,
                            scope.dataset_id,
                            scope.dataset_version_id,
                            target=scope.target,
                            target_contract_id=scope.target_contract_id,
                            predictor_authorization_id=scope.predictor_authorization_id,
                        )
                        assert current["analysis_partition_id"] == partition["analysis_partition_id"]
                        assert current["artifact_hash"] == partition["artifact_hash"]

                    retry = self.service.confirm(
                        scope.store,
                        self._confirm_request(
                            scope, development_share, holdout_share
                        ),
                        {"userId": "analysis-partition-matrix-owner"},
                    )
                    assert retry["reused"] is True
                    assert retry["analysis_partition"]["analysis_partition_id"] == partition["analysis_partition_id"]
                    history = self.persistence.analysis_partitions.history(scope.project_id)
                    assert len(history) == 1
                    assert history[0]["revision"] == 1

    def test_identical_and_conflicting_concurrent_creates_are_single_flight(self) -> None:
        frame = _classification_frames()["balanced_binary"]()
        first_scope = self._scope(frame, problem_type="classification")
        second_store = self._clone_store(first_scope.store)
        request = self._confirm_request(first_scope, 0.8, 0.2)
        barrier = threading.Barrier(2)

        def identical(store: DatasetStore, actor: str) -> dict[str, Any]:
            barrier.wait(timeout=10)
            return AnalysisPartitionService(
                PersistenceService(Database(self.database_path)).analysis_partitions
            ).confirm(store, request, {"userId": actor})

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda values: identical(*values),
                    [
                        (first_scope.store, "analysis-partition-matrix-owner"),
                        (second_store, "analysis-partition-matrix-collaborator"),
                    ],
                )
            )
        ids = {
            result["analysis_partition"]["analysis_partition_id"]
            for result in results
        }
        assert len(ids) == 1
        assert sorted(result["reused"] for result in results) == [False, True]
        assert len(self.persistence.analysis_partitions.history(first_scope.project_id)) == 1

        conflict_scope = self._scope(frame, problem_type="classification")
        competing_store = self._clone_store(conflict_scope.store)
        barrier = threading.Barrier(2)
        requests = [
            self._confirm_request(conflict_scope, 0.8, 0.2),
            self._confirm_request(conflict_scope, 0.7, 0.3),
        ]

        def conflicting(index: int) -> tuple[str, Any]:
            barrier.wait(timeout=10)
            try:
                result = AnalysisPartitionService(
                    PersistenceService(Database(self.database_path)).analysis_partitions
                ).confirm(
                    conflict_scope.store if index == 0 else competing_store,
                    requests[index],
                    {"userId": f"actor-{index}"},
                )
                return "success", result
            except AnalysisPartitionError as exc:
                return "error", exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(conflicting, [0, 1]))
        assert sorted(kind for kind, _ in outcomes) == ["error", "success"]
        conflict = next(value for kind, value in outcomes if kind == "error")
        assert conflict.code == ANALYSIS_PARTITION_CONTRADICTORY
        assert conflict.identifiers["analysis_partition_id"]
        assert conflict.identifiers["revision"] == 1
        assert len(self.persistence.analysis_partitions.history(conflict_scope.project_id)) == 1

    def test_multi_project_preview_isolation_and_authorization_gate(self) -> None:
        partition_router = importlib.import_module("server.analysis_partition.router")

        scope_a = self._scope(
            _classification_frames()["balanced_binary"](),
            problem_type="classification",
        )
        scope_b = self._scope(
            _classification_frames()["moderately_imbalanced_binary"](),
            problem_type="classification",
        )
        request_a = self._preview_request(scope_a, 0.8, 0.2)
        request_b = self._preview_request(scope_b, 0.8, 0.2)

        def preview(scope: IsolatedScope, request: AnalysisPartitionPreviewRequest) -> dict[str, Any]:
            return self._preview(scope.store, request)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(preview, scope_a, request_a)
            future_b = executor.submit(preview, scope_b, request_b)
            result_a = future_a.result(timeout=20)
            result_b = future_b.result(timeout=20)
        assert result_a["project_id"] == scope_a.project_id
        assert result_b["project_id"] == scope_b.project_id
        assert result_a["preview_fingerprint"] != result_b["preview_fingerprint"]
        assert self.persistence.analysis_partitions.get_current(scope_a.project_id) is None
        assert self.persistence.analysis_partitions.get_current(scope_b.project_id) is None

        with pytest.raises(AnalysisPartitionError) as wrong_scope:
            self._preview(scope_a.store, request_b)
        assert wrong_scope.value.code == PREDICTOR_AUTHORIZATION_REQUIRED
        assert wrong_scope.value.identifiers["project_id"] == scope_b.project_id
        assert wrong_scope.value.identifiers["dataset_id"] == scope_b.dataset_id
        assert wrong_scope.value.identifiers["dataset_version_id"] == scope_b.dataset_version_id

        with (
            patch.object(
                partition_router,
                "authorize_modeling_scope",
                side_effect=HTTPException(status_code=403, detail="forbidden"),
            ),
            patch.object(partition_router.analysis_partition_service, "preview") as preview_call,
            patch.object(
                partition_router,
                "DATASTORE",
                Mock(current=Mock(return_value=scope_a.store)),
            ),
        ):
            with pytest.raises(HTTPException) as denied:
                partition_router.preview_analysis_partition(
                    request_a,
                    {"userId": "unauthorized-user"},
                )
        assert denied.value.status_code == 403
        preview_call.assert_not_called()

    def test_eda_materializes_development_only_and_never_opens_holdout(self) -> None:
        from server.eda.analytical_contract import resolve_development_partition
        partition_router = importlib.import_module("server.analysis_partition.router")

        scope = self._scope(
            _classification_frames()["balanced_binary"](),
            problem_type="classification",
        )
        response = self.service.confirm(
            scope.store,
            self._confirm_request(scope, 0.8, 0.2),
            {"userId": "analysis-partition-matrix-owner"},
        )
        with (
            patch.object(
                partition_router,
                "get_persistence_service",
                return_value=self.persistence,
            ),
            patch.object(partition_router, "audit_event"),
        ):
            evidence_ref = partition_router._record_partition_evidence(
                response,
                {"userId": "analysis-partition-matrix-owner"},
            )
            mdd_ref = partition_router._record_partition_mdd(
                response,
                {"userId": "analysis-partition-matrix-owner"},
                evidence_ref,
            )
        self.persistence.analysis_partitions.update_documentation_status(
            response["analysis_partition"]["analysis_partition_id"],
            expected_current=self.persistence.analysis_partitions.get_current(
                scope.project_id
            ),
            evidence_status="recorded",
            evidence_ref=evidence_ref,
            mdd_status="recorded",
            mdd_ref=mdd_ref,
        )
        record = self.persistence.analysis_partitions.get(
            response["analysis_partition"]["analysis_partition_id"]
        )
        original = scope.store.raw_df.copy(deep=True)
        holdout_positions = record["row_assignments_json"]["holdout_positions"]
        scope.store.raw_df.iloc[
            holdout_positions,
            scope.store.raw_df.columns.get_loc("target"),
        ] = 999
        scope.store.raw_df.iloc[
            holdout_positions,
            scope.store.raw_df.columns.get_loc("feature"),
        ] = -999_999

        with (
            patch.object(analysis_partition_service, "_repository", self.persistence.analysis_partitions),
            patch.object(
                analysis_partition_service,
                "materialize_validation",
                side_effect=AssertionError("EDA must not materialize final holdout"),
            ),
        ):
            features, target, analytical_scope = resolve_development_partition(
                store=scope.store,
                identity={
                    "project_id": scope.project_id,
                    "dataset_id": scope.dataset_id,
                    "dataset_version_id": scope.dataset_version_id,
                },
                target=scope.target,
                authorized_predictors=scope.predictors,
                predictor_manifest_id=scope.predictor_authorization_id,
            )
        assert len(features) == response["analysis_partition"]["development_count"]
        assert len(target) == len(features)
        assert -999_999 not in features["feature"].tolist()
        assert 999 not in target.tolist()
        assert analytical_scope["analysis_scope"] == "development_population"
        assert analytical_scope["final_holdout_accessed"] is False
        assert analytical_scope["final_holdout_used_for_selection"] is False
        assert analytical_scope["rows_excluded"] == len(holdout_positions)
        # Confirm that the deliberate holdout mutation did not affect any row
        # selected into the EDA development frame.
        development_positions = record["row_assignments_json"]["development_positions"]
        assert features["feature"].tolist() == original.iloc[development_positions]["feature"].tolist()

    def test_router_creation_records_step01_evidence_and_partition_mdd_reference(self) -> None:
        partition_router = importlib.import_module("server.analysis_partition.router")

        scope = self._scope(
            _classification_frames()["balanced_binary"](),
            problem_type="classification",
        )
        preview = self._preview(
            scope.store,
            self._preview_request(scope, 0.8, 0.2),
        )
        request = self._confirm_request(scope, 0.8, 0.2).model_copy(
            update={"preview_fingerprint": preview["preview_fingerprint"]}
        )
        with (
            patch.object(analysis_partition_service, "_repository", self.persistence.analysis_partitions),
            patch.object(
                partition_router,
                "DATASTORE",
                Mock(current=Mock(return_value=scope.store)),
            ),
            patch.object(partition_router, "get_persistence_service", return_value=self.persistence),
            patch.object(partition_router, "authorize_modeling_scope"),
            patch.object(
                partition_router,
                "_authoritative_partition_request",
                return_value=(
                    scope.store,
                    request.model_dump(),
                    {
                        "project_id": scope.project_id,
                        "dataset_id": scope.dataset_id,
                        "dataset_version_id": scope.dataset_version_id,
                        "activation_revision": 1,
                    },
                ),
            ),
            patch.object(partition_router, "audit_event"),
        ):
            response = partition_router.confirm_analysis_partition(
                request,
                {"userId": "analysis-partition-matrix-owner"},
            )
        partition = response["analysis_partition"]
        assert partition["evidence_status"] == "recorded"
        assert partition["evidence_ref"] == f"ev-{partition['analysis_partition_id']}"
        assert partition["mdd_status"] == "recorded"
        assert partition["mdd_ref"]
        evidence = self.persistence.evidence.get(partition["evidence_ref"])
        assert evidence is not None
        assert evidence["project_id"] == scope.project_id
        assert evidence["step_id"] == "step01"
        assert evidence["artifact_type"] == "analysis_partition"
        assert evidence["source_ref"] == partition["analysis_partition_id"]
        assert evidence["payload_json"]["analysis_partition_id"] == partition["analysis_partition_id"]
        assert evidence["payload_json"]["revision"] == partition["revision"]
        assert evidence["payload_json"]["final_holdout_accessed"] is False

    def test_exact_identity_and_legacy_unresolved_boundaries_never_use_latest_or_first(self) -> None:
        from server.persistence.repositories.analysis_partition_repository import (
            AnalysisPartitionRepository,
        )
        from server.splitting import split_router

        scope = self._scope(
            _classification_frames()["balanced_binary"](),
            problem_type="classification",
        )
        partition = self.service.confirm(
            scope.store,
            self._confirm_request(scope, 0.8, 0.2),
            {"userId": "analysis-partition-matrix-owner"},
        )["analysis_partition"]
        exact_identity = {
            "project_id": scope.project_id,
            "dataset_id": scope.dataset_id,
            "dataset_version_id": scope.dataset_version_id,
        }
        assert split_router._record_identity_is_current(
            {
                **exact_identity,
                "dataset_version": scope.dataset_version_id,
            },
            exact_identity,
        )
        for conflicting in (
            {**exact_identity, "project_id": "other-project"},
            {**exact_identity, "dataset_id": "other-dataset"},
            {**exact_identity, "dataset_version_id": "other-version"},
        ):
            assert not split_router._record_identity_is_current(
                conflicting,
                exact_identity,
            )
        with pytest.raises(AnalysisPartitionError):
            self.service.current(
                scope.project_id,
                scope.dataset_id,
                "unverified-legacy-version",
            )

        repository_source = inspect.getsource(
            AnalysisPartitionRepository.get_current_exact
        ).lower()
        assert "dataset_id = ?" in repository_source
        assert "dataset_version_id = ?" in repository_source
        assert "limit 1" not in repository_source
        assert "order by" not in repository_source
        assert partition["analysis_partition_id"]


__all__ = ["TestAnalysisPartitionProductMatrix"]

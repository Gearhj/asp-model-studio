"""Phase 1 EDA predictor authorization and target-source exclusion tests.

These tests intentionally model a stale or crafted browser state:

* ``bad_flag`` is the modeling target.
* ``RiskPerformance`` is its categorical deterministic source.
* ``outcome_code`` is a numeric deterministic source, so direct histogram and
  correlation paths cannot rely on dtype to make the unsafe field disappear.
* the in-memory ``selected_columns`` list contains both sources even though the
  feature manifest marks them excluded.

Every EDA surface must derive its predictor set on the server and fail closed.
Client-supplied ``selected_features`` and ``pairwise_features`` are requests,
not authorization.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, Iterable
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException


# Keep this standalone suite from writing the live development checkpoint when
# it is invoked directly from the repository root.
os.environ.setdefault(
    "ATLAS_CHECKPOINT_PATH",
    os.path.join(
        tempfile.gettempdir(),
        f"atlas_eda_phase1_authorization_{uuid.uuid4().hex[:8]}.json",
    ),
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.dataset_store import DATASTORE  # noqa: E402
from server.eda import eda_router  # noqa: E402
from server.eda.workspace_service import (  # noqa: E402
    EDAWorkspaceService,
    RelationshipSampleValidationError,
    eda_workspace_service,
)
from server.eda.analytical_contract import EDAAnalyticalContractError  # noqa: E402
from server.eda.workspace_types import (  # noqa: E402
    EDAWorkspaceRequest,
    EDAVifSimulationRequest,
    EDARelationshipSampleRequest,
)
from tests.analysis_partition_fixture import GovernedAnalysisFixture  # noqa: E402


PROJECT_ID = "eda-phase1-authorization-project"
TARGET = "bad_flag"
TARGET_SOURCES = {"RiskPerformance", "outcome_code"}
SAFE_PREDICTORS = {"age", "balance", "balance_shadow", "segment"}


def _frame(rows: int = 240) -> pd.DataFrame:
    """Synthetic classification population with two deterministic sources."""

    target = [index % 2 for index in range(rows)]
    balance = [
        None if index % 23 == 0 else float((index * 7) % 101)
        for index in range(rows)
    ]
    return pd.DataFrame(
        {
            "RiskPerformance": [
                "Bad" if value == 1 else "Good"
                for value in target
            ],
            "outcome_code": [
                900.0 if value == 1 else 100.0
                for value in target
            ],
            # The odd periods ensure repeated values occur in both target
            # classes; these are legitimate predictors, not target sources.
            "age": [20.0 + float(index % 31) for index in range(rows)],
            "balance": balance,
            "balance_shadow": [
                None
                if value is None
                else value * 1.015 + float((index % 5) - 2) / 10.0
                for index, value in enumerate(balance)
            ],
            "segment": [
                ("north", "south", "west")[index % 3]
                for index in range(rows)
            ],
            TARGET: target,
        }
    )


def _all_profiled_features(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("numeric", "categorical", "missingness"):
        for row in payload.get(key, []) or []:
            if row.get("feature") is not None:
                names.add(str(row["feature"]))
    return names


def _target_source_excluded(payload: dict[str, Any]) -> set[str]:
    """Accept the repository's snake_case EDA or governed-profile casing."""

    candidates: Iterable[Any] | None = payload.get("target_source_excluded")
    if candidates is None:
        candidates = payload.get("targetSourceExcluded")
    authorization = payload.get("predictor_authorization")
    if candidates is None and isinstance(authorization, dict):
        candidates = (
            authorization.get("target_source_excluded")
            or authorization.get("targetSourceExcluded")
        )
    if candidates is None:
        raise AssertionError(
            "EDA response must disclose which deterministic target sources were "
            "excluded from predictor analysis."
        )
    return {str(value) for value in candidates}


def _selection_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("selected_subset", "selected_range", "selection"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    raise AssertionError(
        "The distribution response must expose selected-subset metrics separately "
        "from full-population metrics."
    )


def _metric(metrics: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in metrics:
            return metrics[name]
    raise AssertionError(
        f"Missing required distribution metric; accepted names were {names!r}."
    )


class EDAPhase1PredictorAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        DATASTORE.reset_all()
        frame = _frame()
        DATASTORE.set_raw(frame)
        DATASTORE.set_target(TARGET)
        DATASTORE.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": "ds-eda-phase1-synthetic",
                "dataset_version_id": "eda-phase1-synthetic-v1",
            }
        )

        # Deliberately unsafe legacy/crafted state. Production must sanitize it
        # against the authoritative manifest and server-derived target lineage.
        DATASTORE.meta["selected_columns"] = [
            "RiskPerformance",
            "outcome_code",
            "age",
            "balance",
            "balance_shadow",
            "segment",
        ]
        DATASTORE.meta["dataset_version"] = "eda-phase1-synthetic-v1"
        DATASTORE.meta["source"] = {
            "kind": "dataset_library",
            "datasetId": "ds-eda-phase1-synthetic",
            "version": "eda-phase1-synthetic-v1",
            "filename": "eda-phase1-synthetic.csv",
        }
        DATASTORE.meta["feature_manifest"] = {
            "manifest_version": "fm-eda-phase1-synthetic-v1",
            "dataset_version": "eda-phase1-synthetic-v1",
            "features": [
                {
                    "feature_name": feature,
                    "selected": True,
                    "eligibility_status": "eligible",
                    "origin": "original",
                }
                for feature in sorted(SAFE_PREDICTORS)
            ]
            + [
                {
                    "feature_name": feature,
                    "selected": False,
                    "eligibility_status": "excluded",
                    "exclusion_reason": "Deterministic source of modeling target",
                    "origin": "original",
                }
                for feature in sorted(TARGET_SOURCES)
            ],
        }
        selected = sorted(SAFE_PREDICTORS)
        self.governed_fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
        self.partition_fixture = self.governed_fixture.install(
            DATASTORE.current(),
            dataset_id="ds-eda-phase1-synthetic",
            dataset_version_id="eda-phase1-synthetic-v1",
            target=TARGET,
            authorized_predictors=selected,
            target_sources=TARGET_SOURCES,
            development_share=0.8,
        )
        # Retain the deliberately unsafe browser/checkpoint projection. The
        # durable Data Acquisition manifest above remains the only authority.
        DATASTORE.meta["selected_columns"] = [
            "RiskPerformance",
            "outcome_code",
            "age",
            "balance",
            "balance_shadow",
            "segment",
        ]
        self.identity_patch = patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": "ds-eda-phase1-synthetic",
                "dataset_version_id": "eda-phase1-synthetic-v1",
            },
        )
        self.identity_patch.start()
        eda_workspace_service._cache.clear()
        eda_workspace_service._contract_cache.clear()
        for attribute in ("_fingerprint_key", "_fingerprint_value"):
            if hasattr(eda_workspace_service, attribute):
                delattr(eda_workspace_service, attribute)

    def tearDown(self) -> None:
        self.identity_patch.stop()
        eda_workspace_service._cache.clear()
        eda_workspace_service._contract_cache.clear()
        DATASTORE.reset_all()
        self.governed_fixture.close()

    def _request(
        self,
        *,
        selected_features: list[str] | None = None,
        pairwise_features: list[str] | None = None,
        **extra: Any,
    ) -> EDAWorkspaceRequest:
        return EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            target=TARGET,
            event_value=1,
            problem_type="classification",
            selected_features=selected_features or [],
            pairwise_features=pairwise_features or [],
            histogram_bins=12,
            rendered_sample_limit=180,
            **extra,
        )

    def test_overview_inventory_is_authorized_and_discloses_target_sources(self) -> None:
        payload = eda_workspace_service.section("overview", self._request())
        available = payload["available_fields"]
        exposed = set(available.get("numeric", [])) | set(
            available.get("categorical", [])
        )

        self.assertSetEqual(exposed, SAFE_PREDICTORS)
        self.assertNotIn(TARGET, exposed)
        self.assertTrue(TARGET_SOURCES.isdisjoint(exposed))
        self.assertSetEqual(_target_source_excluded(payload), TARGET_SOURCES)
        self.assertEqual(
            payload["headline"]["predictors"],
            len(SAFE_PREDICTORS),
            "headline predictor count must use the authorized inventory",
        )

    def test_predictor_profile_cannot_reenable_sources_from_request(self) -> None:
        payload = eda_workspace_service.section(
            "predictors",
            self._request(
                selected_features=[
                    "RiskPerformance",
                    "outcome_code",
                    TARGET,
                    "age",
                    "balance",
                    "does_not_exist",
                ]
            ),
        )
        exposed = _all_profiled_features(payload)

        self.assertSetEqual(exposed, {"age", "balance"})
        self.assertNotIn(TARGET, exposed)
        self.assertTrue(TARGET_SOURCES.isdisjoint(exposed))
        self.assertSetEqual(_target_source_excluded(payload), TARGET_SOURCES)

    def test_relationships_exclude_sources_from_matrix_vif_and_pairwise(self) -> None:
        with self.assertRaises(RelationshipSampleValidationError) as rejected:
            eda_workspace_service.section(
                "relationships",
                self._request(
                    selected_features=[
                        "RiskPerformance",
                        "outcome_code",
                        TARGET,
                        "age",
                        "balance",
                        "balance_shadow",
                    ],
                    pairwise_features=[
                        "outcome_code",
                        TARGET,
                        "balance",
                        "age",
                    ],
                ),
            )
        rejected_names = {
            row["field"] for row in rejected.exception.rejected_fields
        }
        self.assertSetEqual(rejected_names, {"outcome_code", TARGET})

        payload = eda_workspace_service.section(
            "relationships",
            self._request(
                selected_features=[
                    "RiskPerformance",
                    "outcome_code",
                    TARGET,
                    "age",
                    "balance",
                    "balance_shadow",
                ],
                pairwise_features=[
                    "balance",
                    "age",
                ],
            ),
        )

        correlation_columns = set(payload.get("correlation_columns", []))
        self.assertSetEqual(
            correlation_columns,
            {"age", "balance", "balance_shadow"},
        )
        self.assertNotIn(TARGET, correlation_columns)
        self.assertTrue(TARGET_SOURCES.isdisjoint(correlation_columns))
        n_matrix = payload.get("correlation_n_matrix")
        self.assertEqual(len(n_matrix), len(payload["correlation_columns"]))
        self.assertTrue(
            all(len(row) == len(payload["correlation_columns"]) for row in n_matrix)
        )

        for row in payload.get("strong_pairs", []):
            self.assertNotIn(row.get("feature_a"), TARGET_SOURCES | {TARGET})
            self.assertNotIn(row.get("feature_b"), TARGET_SOURCES | {TARGET})
        for row in payload.get("vif", []):
            self.assertNotIn(row.get("feature"), TARGET_SOURCES | {TARGET})

        self.assertEqual(payload.get("pairwise_features"), ["balance", "age"])
        for row in payload.get("pairwise_sample", []):
            self.assertNotIn(TARGET, row)
            self.assertNotIn("__target__", row)
            self.assertTrue(TARGET_SOURCES.isdisjoint(row))
        vif_scope = payload.get("vif_scope") or {}
        self.assertEqual(vif_scope.get("analysis_population"), "development_population")
        self.assertLessEqual(int(vif_scope.get("rows_used", 0)), 192)
        self.assertFalse(payload["analysis_scope"]["finalHoldoutAccessed"])
        self.assertSetEqual(_target_source_excluded(payload), TARGET_SOURCES)

    def test_relationship_sample_is_bounded_deterministic_and_target_safe(self) -> None:
        request = EDARelationshipSampleRequest(
            project_id=PROJECT_ID,
            target=TARGET,
            event_value=1,
            problem_type="classification",
            dataset_version="eda-phase1-synthetic-v1",
            predictor_manifest_id=DATASTORE.meta[
                "predictor_authorization_id"
            ],
            x_feature="age",
            y_feature="balance",
            z_feature="balance_shadow",
            selection_feature="age",
            sample_limit=100,
        )
        first = eda_workspace_service.relationship_sample(request)
        second = eda_workspace_service.relationship_sample(request)

        self.assertEqual(first["scope"], "rendered_sample")
        self.assertEqual(first["returned_rows"], 100)
        self.assertLessEqual(first["returned_rows"], 5000)
        self.assertTrue(first["sampled"])
        self.assertEqual(second["cache_status"], "hit")
        self.assertEqual(first["points"], second["points"])
        self.assertEqual(
            first["sampling"]["method"],
            "deterministic_proportional_stratified",
        )
        self.assertSetEqual(
            set(first["target_encoding"]["groups"]),
            {"event", "non_event", "missing"},
        )
        for point in first["points"]:
            self.assertSetEqual(
                set(point),
                {
                    "id",
                    "x",
                    "y",
                    "z",
                    "size",
                    "target_group",
                    "segment_group",
                    "selection_value",
                },
            )
            self.assertNotIn(TARGET, point)
            self.assertNotIn("__target__", point)

        for metric in first["pair_metrics"]:
            self.assertGreaterEqual(metric["n"], first["eligible_rows"])

    def test_relationship_sample_rejects_every_forbidden_role(self) -> None:
        base = {
            "project_id": PROJECT_ID,
            "target": TARGET,
            "event_value": 1,
            "problem_type": "classification",
            "x_feature": "age",
            "y_feature": "balance",
            "z_feature": "balance_shadow",
            "sample_limit": 100,
        }
        for role in (
            "x_feature",
            "y_feature",
            "z_feature",
            "point_size_feature",
            "segment_feature",
            "selection_feature",
        ):
            for forbidden in (TARGET, "RiskPerformance", "outcome_code"):
                with self.subTest(role=role, forbidden=forbidden):
                    payload = {**base, role: forbidden}
                    if role == "x_feature":
                        payload["x_feature"] = forbidden
                    elif role == "y_feature":
                        payload["y_feature"] = forbidden
                    with self.assertRaises(
                        RelationshipSampleValidationError
                    ) as raised:
                        eda_workspace_service.relationship_sample(
                            EDARelationshipSampleRequest(**payload)
                        )
                    rejected = raised.exception.rejected_fields
                    self.assertTrue(
                        any(
                            row["field"] == forbidden
                            and row["role"]
                            == {
                                "x_feature": "x",
                                "y_feature": "y",
                                "z_feature": "z",
                                "point_size_feature": "point_size",
                                "segment_feature": "segment",
                                "selection_feature": "selection",
                            }[role]
                            for row in rejected
                        )
                    )

    def test_relationship_sample_route_returns_structured_422(self) -> None:
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ):
            with self.assertRaises(HTTPException) as raised:
                eda_router.eda_relationship_sample(
                    EDARelationshipSampleRequest(
                        project_id=PROJECT_ID,
                        target=TARGET,
                        event_value=1,
                        problem_type="classification",
                        x_feature=TARGET,
                        y_feature="balance",
                        z_feature="outcome_code",
                        sample_limit=100,
                    ),
                    user={"userId": "eda-phase1-test-owner"},
                )
        self.assertEqual(raised.exception.status_code, 422)
        detail = raised.exception.detail
        self.assertEqual(detail["code"], "relationship_fields_not_authorized")
        self.assertSetEqual(
            {row["field"] for row in detail["rejected_fields"]},
            {TARGET, "outcome_code"},
        )

    def test_target_source_lineage_survives_upstream_selection_exclusion(self) -> None:
        DATASTORE.meta["selected_columns"] = sorted(SAFE_PREDICTORS)
        payload = eda_workspace_service.section("overview", self._request())
        self.assertSetEqual(_target_source_excluded(payload), TARGET_SOURCES)
        exposed = set(payload["available_fields"].get("numeric", [])) | set(
            payload["available_fields"].get("categorical", [])
        )
        self.assertTrue(TARGET_SOURCES.isdisjoint(exposed))

    def test_request_target_is_never_used_as_server_authority(self) -> None:
        DATASTORE.set_target(None)
        restored = eda_workspace_service.section("overview", self._request())
        self.assertEqual(restored["target"], TARGET)
        self.assertEqual(DATASTORE.target, TARGET)
        self.assertEqual(
            DATASTORE.meta["target_contract_id"],
            self.partition_fixture["authorization"]["target_contract_id"],
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            eda_workspace_service.section(
                "overview",
                EDAWorkspaceRequest(
                    project_id=PROJECT_ID,
                    target="age",
                    event_value=1,
                    problem_type="classification",
                ),
            )

    def test_same_shape_replacement_cannot_reuse_distribution_cache(self) -> None:
        first = eda_workspace_service.section(
            "distribution",
            self._request(feature="balance"),
        )
        metadata = dict(DATASTORE.meta)
        replacement = _frame()
        replacement["balance"] = replacement["balance"].map(
            lambda value: value if pd.isna(value) else float(value) + 1_000.0
        )
        replacement["balance_shadow"] = replacement["balance"].map(
            lambda value: value if pd.isna(value) else float(value) * 1.015
        )
        DATASTORE.set_raw(replacement)
        DATASTORE.set_target(TARGET)
        DATASTORE.meta.update(metadata)

        second = eda_workspace_service.section(
            "distribution",
            self._request(feature="balance"),
        )
        self.assertAlmostEqual(
            second["statistics"]["mean"],
            first["statistics"]["mean"] + 1_000.0,
            places=10,
        )

    def test_vif_simulation_is_bounded_authorized_and_non_mutating(self) -> None:
        before = DATASTORE.get_base_df().copy(deep=True)
        result = eda_workspace_service.vif_simulation(
            EDAVifSimulationRequest(
                project_id=PROJECT_ID,
                target=TARGET,
                event_value=1,
                problem_type="classification",
                excluded_feature="balance",
            )
        )
        self.assertTrue(result["non_mutating"])
        self.assertEqual(result["vif_scope"]["required_feature"], "balance")
        self.assertLessEqual(
            result["vif_scope"]["rows_used"],
            result["vif_scope"]["maximum_rows"],
        )
        pd.testing.assert_frame_equal(DATASTORE.get_base_df(), before)

        for forbidden in (TARGET, *sorted(TARGET_SOURCES)):
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(ValueError, "not authorized"):
                    eda_workspace_service.vif_simulation(
                        EDAVifSimulationRequest(
                            project_id=PROJECT_ID,
                            target=TARGET,
                            event_value=1,
                            problem_type="classification",
                            excluded_feature=forbidden,
                        )
                    )

    def test_direct_histogram_rejects_target_and_numeric_target_source(self) -> None:
        # Call the route handler directly so this remains a fast behavioral
        # service test; authorization of the project itself is outside this
        # suite and is replaced only for the duration of the call.
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ):
            safe = eda_router.histogram(
                "balance",
                project_id=PROJECT_ID,
                bins=12,
                user={"userId": "eda-phase1-test-owner"},
            )
            self.assertTrue(safe["ok"])
            self.assertEqual(sum(safe["counts"]), safe["row_count"])

            for forbidden in (TARGET, "outcome_code", "RiskPerformance"):
                with self.subTest(forbidden=forbidden):
                    with self.assertRaises(
                        HTTPException,
                        msg=(
                            "Direct histogram requests must fail closed before "
                            f"reading forbidden field {forbidden!r}."
                        ),
                    ) as raised:
                        eda_router.histogram(
                            forbidden,
                            project_id=PROJECT_ID,
                            bins=12,
                            user={"userId": "eda-phase1-test-owner"},
                        )
                    self.assertIn(raised.exception.status_code, {400, 403, 422})
                    self.assertIn(
                        forbidden.lower(),
                        str(raised.exception.detail).lower(),
                    )

    def test_legacy_sample_and_d3_histogram_are_development_only(self) -> None:
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ):
            sample = eda_router.sample(
                project_id=PROJECT_ID,
                max_rows=10_000,
                user={"userId": "eda-phase1-test-owner"},
            )
            histogram = eda_router.d3_histogram(
                {
                    "project_id": PROJECT_ID,
                    "feature": "balance",
                    "bins": 12,
                    "sample_pct": 100,
                },
                user={"userId": "eda-phase1-test-owner"},
            )

        development_rows = int(
            self.partition_fixture["record"]["development_count"]
        )
        self.assertEqual(len(sample["rows"]), development_rows)
        self.assertNotIn(TARGET, sample["headers"])
        self.assertEqual(sample["scope"], "development_population")
        self.assertTrue(sample["target_excluded"])
        self.assertFalse(sample["final_holdout_accessed"])
        self.assertEqual(
            sample["analysis_partition_id"],
            self.partition_fixture["record"]["analysis_partition_id"],
        )

        development_positions = self.partition_fixture["record"][
            "row_assignments_json"
        ]["development_positions"]
        expected_numeric = int(
            pd.to_numeric(
                _frame().iloc[development_positions]["balance"],
                errors="coerce",
            )
            .notna()
            .sum()
        )
        self.assertEqual(int(sum(histogram["overall"])), expected_numeric)
        self.assertEqual(histogram["scope"], "development_population")
        self.assertFalse(histogram["final_holdout_accessed"])
        self.assertFalse(histogram["final_holdout_used_for_selection"])
        self.assertEqual(
            histogram["analysis_partition_id"],
            self.partition_fixture["record"]["analysis_partition_id"],
        )

    def test_empty_durable_predictor_inventory_never_expands_to_active_schema(self) -> None:
        current = dict(self.partition_fixture["authorization"])
        empty_base = {
            key: current[key]
            for key in (
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "target",
                "positive_value",
                "negative_value",
                "target_contract_id",
                "excluded_predictors",
                "target_source_excluded",
                "target_source_detection_scope",
                "source",
            )
        }
        empty_base.update(
            {
                "authorized_predictors": [],
                "selected_predictors": [],
            }
        )
        empty_id = (
            "predictor-auth-"
            + self.governed_fixture._hash(empty_base)[:20]
        )
        empty = {
            **current,
            **empty_base,
            "predictor_authorization_id": empty_id,
            "manifest_version": empty_id,
            "artifact_hash": empty_id.removeprefix("predictor-auth-"),
        }
        self.governed_fixture.persistence.predictor_authorizations.set_current(
            empty
        )
        DATASTORE.meta.update(
            {
                "predictor_authorization_id": empty_id,
                "predictor_authorization": empty,
                "predictor_authorization_manifest": empty,
            }
        )

        service = EDAWorkspaceService()
        frame, target, _y, _problem, _event, authorization = (
            service.authorized_dataset(self._request())
        )
        self.assertEqual(target, TARGET)
        self.assertEqual(list(frame.columns), [TARGET])
        self.assertEqual(authorization["authorized_predictors"], [])
        self.assertEqual(
            authorization["source"],
            "data_acquisition_predictor_authorization",
        )
        with self.assertRaises(EDAAnalyticalContractError) as raised:
            service.section("predictors", self._request())
        self.assertEqual(
            raised.exception.code,
            "predictor_authorization_required",
        )
        self.assertIn("no model-eligible predictors", str(raised.exception))

    def test_distribution_range_is_full_population_and_authorized(self) -> None:
        """Brush-range aggregation must not fall back to the rendered sample."""

        model_fields = getattr(EDAWorkspaceRequest, "model_fields", {})
        required_fields = {"feature", "selection_min", "selection_max"}
        self.assertTrue(
            required_fields.issubset(model_fields),
            "EDAWorkspaceRequest must carry feature/selection_min/selection_max "
            "for the on-demand full-population distribution section.",
        )

        payload = eda_workspace_service.section(
            "distribution",
            self._request(
                feature="balance",
                selection_min=20.0,
                selection_max=40.0,
            ),
        )
        population = _frame()
        numeric = pd.to_numeric(population["balance"], errors="coerce")
        mask = numeric.between(20.0, 40.0, inclusive="both")
        selected_values = numeric[mask]
        development = population.loc[DATASTORE.y_train.index]
        development_numeric = pd.to_numeric(
            development["balance"], errors="coerce"
        )
        development_mask = development_numeric.between(
            20.0, 40.0, inclusive="both"
        )
        selected_target = development.loc[development_mask, TARGET]
        metrics = _selection_metrics(payload)

        self.assertEqual(payload["scope"], "development_population")
        self.assertEqual(payload["descriptive_scope"], "full_governed_population")
        self.assertEqual(payload["row_count"], len(population))
        self.assertEqual(
            int(_metric(metrics, "row_count", "selected_row_count", "count")),
            int(mask.sum()),
        )
        self.assertAlmostEqual(
            float(_metric(metrics, "population_share", "share")),
            float(mask.sum() / len(population)),
            places=12,
        )
        self.assertAlmostEqual(
            float(_metric(metrics, "mean")),
            float(selected_values.mean()),
            places=12,
        )
        self.assertAlmostEqual(
            float(_metric(metrics, "median")),
            float(selected_values.median()),
            places=12,
        )
        self.assertAlmostEqual(
            float(_metric(metrics, "target_rate", "event_rate")),
            float(selected_target.mean()),
            places=12,
        )
        self.assertEqual(metrics["target_rate_scope"], "development_population")
        self.assertEqual(metrics["descriptive_scope"], "full_governed_population")

        bins = payload.get("bins") or payload.get("histogram") or []
        missing = payload.get("missing_bucket") or payload.get("missingBucket")
        self.assertTrue(bins, "The distribution response must include bounded bins.")
        self.assertIsInstance(
            missing,
            dict,
            "Missing values must be returned as an explicit separate bucket.",
        )
        binned_count = sum(int(row.get("count", 0)) for row in bins)
        missing_count = int(
            _metric(
                missing,
                "count",
                "row_count",
                "population",
            )
        )
        self.assertEqual(
            binned_count + missing_count,
            len(population),
            "Histogram bins plus the explicit missing bucket must reconcile to "
            "the full population.",
        )
        self.assertSetEqual(_target_source_excluded(payload), TARGET_SOURCES)

    def test_distribution_range_rejects_target_and_target_sources(self) -> None:
        model_fields = getattr(EDAWorkspaceRequest, "model_fields", {})
        self.assertIn(
            "feature",
            model_fields,
            "The distribution request must identify one server-authorized feature.",
        )
        for forbidden in (TARGET, "outcome_code", "RiskPerformance"):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(
                    (ValueError, HTTPException),
                    msg=(
                        "A crafted distribution request must not re-enable "
                        f"forbidden field {forbidden!r}."
                    ),
                ):
                    eda_workspace_service.section(
                        "distribution",
                        self._request(
                            feature=forbidden,
                            selection_min=0.0,
                            selection_max=1000.0,
                        ),
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)

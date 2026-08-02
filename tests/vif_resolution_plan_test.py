from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
RUN_ID = uuid.uuid4().hex[:10]
ROOT = REPO_ROOT / ".tmp" / f"atlas-vif-plan-{RUN_ID}"
ROOT.mkdir(parents=True, exist_ok=True)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(ROOT / "checkpoint.json")
os.environ["ATLAS_VIF_PLAN_ROOT"] = str(ROOT / "plans")
os.environ["ATLAS_EVIDENCE_ROOT"] = str(ROOT / "evidence")

from server.core.dataset_store import DATASTORE  # noqa: E402
from server.eda.vif_plan_store import get_feature_recommendations  # noqa: E402
from server.eda.vif_resolution import build_vif_resolution_plan  # noqa: E402
from server.eda.workspace_service import eda_workspace_service  # noqa: E402
from server.eda.workspace_types import (  # noqa: E402
    EDAVifSimulationRequest,
    EDAVifPreferenceWeights,
    EDAVifResolutionDecisionRequest,
    EDAVifResolutionPlanRequest,
    EDAWorkspaceRequest,
)
from server.evidence import evidence_store  # noqa: E402


PROJECT_ID = "atlas-vif-resolution-test"
DATASET_ID = "ds-vif-resolution-test"
VERSION_ID = "v-vif-resolution-test"
PREDICTORS = [
    "NumInqLast6M",
    "NumInqLast6Mexcl7days",
    "Balance",
    "BalanceShadow",
    "Age",
]


def frame(rows: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    inquiry = rng.normal(5, 1.2, rows)
    inquiry_excluding = inquiry + rng.normal(0, 0.05, rows)
    balance = rng.normal(50, 12, rows)
    balance_shadow = balance * 0.985 + rng.normal(0, 0.4, rows)
    age = rng.normal(42, 8, rows)
    target = (0.5 * age - 0.35 * balance + rng.normal(0, 8, rows) > 2).astype(int)
    training_rows = int(rows * 0.75)
    return pd.DataFrame(
        {
            "NumInqLast6M": inquiry,
            "NumInqLast6Mexcl7days": inquiry_excluding,
            "Balance": balance,
            "BalanceShadow": balance_shadow,
            "Age": age,
            "RiskPerformance": np.where(target == 1, "Bad", "Good"),
            "bad_flag": target,
            "atlas_split": ["TRAIN"] * training_rows + ["TEST"] * (rows - training_rows),
        }
    )


class VifResolutionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        DATASTORE.reset_all()
        source = frame()
        DATASTORE.set_raw(source)
        DATASTORE.set_target("bad_flag")
        DATASTORE.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "dataset_version": VERSION_ID,
                "selected_columns": PREDICTORS,
                "source": {
                    "kind": "dataset_library",
                    "datasetId": DATASET_ID,
                    "version": VERSION_ID,
                    "filename": "HELOC_TEST.csv",
                },
                "feature_manifest": {
                    "manifest_version": "fm-vif-test",
                    "dataset_version": VERSION_ID,
                    "features": [
                        {
                            "feature_name": name,
                            "selected": True,
                            "eligibility_status": "eligible",
                            "origin": "original",
                        }
                        for name in PREDICTORS
                    ]
                    + [
                        {
                            "feature_name": "RiskPerformance",
                            "selected": False,
                            "eligibility_status": "excluded",
                            "exclusion_reason": "Deterministic source of modeling target",
                            "origin": "original",
                        }
                    ],
                },
            }
        )
        self.install_exact_split(source, training_rows=180)
        evidence_store.EVIDENCE_ROOT = ROOT / "evidence"
        evidence_store.ITEMS_ROOT = evidence_store.EVIDENCE_ROOT / "items"
        evidence_store.REGISTRY_PATH = evidence_store.EVIDENCE_ROOT / "evidence_registry.json"
        self.identity = patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
            },
        )
        self.identity.start()

    def install_exact_split(self, source: pd.DataFrame, *, training_rows: int) -> None:
        train = source.iloc[:training_rows]
        holdout = source.iloc[training_rows:]
        DATASTORE.set_splits(
            train.loc[:, PREDICTORS],
            holdout.loc[:, PREDICTORS],
            train["bad_flag"],
            holdout["bad_flag"],
        )
        DATASTORE.meta.update(
            {
                "split_status": "current",
                "split_record": {
                    "project_id": PROJECT_ID,
                    "dataset_id": DATASET_ID,
                    "dataset_version_id": VERSION_ID,
                    "split_id": "split-vif-exact-development",
                    "n_train": training_rows,
                    "n_test": len(holdout),
                    "final_holdout_partition_id": "population-final-holdout-vif",
                    "final_holdout_status": "sealed",
                    "holdout_isolation_status": "verified",
                },
            }
        )

    def tearDown(self) -> None:
        self.identity.stop()
        DATASTORE.reset_all()

    def request(self, **overrides):
        values = {
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "dataset_version": VERSION_ID,
            "target": "bad_flag",
            "event_value": 1,
            "problem_type": "classification",
            "intended_model_family": "linear_scorecard",
            "target_vif_threshold": 10,
            "resolution_objective": "balanced",
            "correlation_threshold": 0.9,
            "maximum_removals": 2,
        }
        values.update(overrides)
        return EDAVifResolutionPlanRequest(**values)

    def test_plan_is_clustered_iterative_comparative_and_non_mutating(self) -> None:
        before = DATASTORE.get_base_df().copy(deep=True)
        manifest_before = deepcopy(DATASTORE.meta["feature_manifest"])
        result = eda_workspace_service.vif_resolution_plan(self.request())

        self.assertEqual(result["current"]["predictor_count"], 5)
        self.assertLess(result["proposed"]["predictor_count"], 5)
        self.assertGreater(result["calculation_count"]["simulated_complete_vif_recalculations"], 5)
        self.assertEqual(result["calculation_count"]["governed_feature_set_calculations"], 1)
        self.assertTrue(result["per_feature_vif_deltas"])
        self.assertGreaterEqual(len(result["clusters"]), 2)
        self.assertGreaterEqual(len(result["proposed"]["illustrative_path"]), 2)
        self.assertFalse(result["governed_feature_set_changed"])
        self.assertFalse(result["dataset_mutated"])
        self.assertTrue(result["input_frame_unchanged"])
        self.assertEqual(result["analysis_scope"]["development_rows"], 180)
        self.assertEqual(result["analysis_scope"]["sealed_final_holdout_rows_excluded"], 60)
        self.assertEqual(
            result["analysis_scope"]["target_informed_evidence"],
            "exact_development_partition_only",
        )
        self.assertTrue(result["analysis_scope"]["exact_development_partition_resolved"])
        self.assertEqual(
            result["analysis_scope"]["split_id"],
            "split-vif-exact-development",
        )
        self.assertFalse(result["analysis_scope"]["final_holdout_accessed"])
        pd.testing.assert_frame_equal(DATASTORE.get_base_df(), before)
        self.assertEqual(DATASTORE.meta["feature_manifest"], manifest_before)

    def test_inquiry_alternatives_are_an_explicit_tie(self) -> None:
        result = eda_workspace_service.vif_resolution_plan(self.request())
        inquiry_tie = next(
            tie
            for tie in result["ties"]
            if {"NumInqLast6M", "NumInqLast6Mexcl7days"}.issubset(tie["features"])
        )
        self.assertIn("VIF alone cannot distinguish", inquiry_tie["message"])
        self.assertIn("development-population signal", inquiry_tie["required_tie_breakers"])
        cluster = next(row for row in result["clusters"] if row["cluster_id"] == inquiry_tie["cluster_id"])
        self.assertEqual(cluster["recommended_action"], "defer")

    def test_protected_predictor_is_never_proposed_for_exclusion(self) -> None:
        protected = "NumInqLast6M"
        result = eda_workspace_service.vif_resolution_plan(
            self.request(protected_predictors=[protected])
        )
        proposed = {row["feature"] for row in result["proposed_exclusions"]}
        self.assertNotIn(protected, proposed)
        self.assertIn(protected, result["protected_predictors"])

    def test_model_family_changes_recommendation_policy(self) -> None:
        linear = eda_workspace_service.vif_resolution_plan(
            self.request(intended_model_family="linear_scorecard")
        )
        tree = eda_workspace_service.vif_resolution_plan(
            self.request(intended_model_family="tree_ensemble")
        )
        self.assertNotEqual(linear["model_family"]["implication"], tree["model_family"]["implication"])
        self.assertNotEqual(
            linear["model_family"]["recommended_posture"],
            tree["model_family"]["recommended_posture"],
        )

    def test_holdout_values_cannot_influence_plan_selection(self) -> None:
        baseline = eda_workspace_service.vif_resolution_plan(self.request())
        holdout = DATASTORE.raw_df["atlas_split"].eq("TEST")
        for feature in [
            "NumInqLast6M",
            "NumInqLast6Mexcl7days",
            "Balance",
            "BalanceShadow",
            "Age",
        ]:
            DATASTORE.raw_df.loc[holdout, feature] = np.linspace(
                -1_000_000,
                1_000_000,
                int(holdout.sum()),
            )
        DATASTORE.raw_df.loc[holdout, "bad_flag"] = 1 - DATASTORE.raw_df.loc[
            holdout,
            "bad_flag",
        ]
        # The durable holdout artifacts themselves are also adversarially
        # changed.  A VIF plan may inspect their governed row count from the
        # split contract, but must never read these feature or target values.
        for feature in PREDICTORS:
            DATASTORE.X_test.loc[:, feature] = np.linspace(
                5_000_000,
                -5_000_000,
                len(DATASTORE.X_test),
            )
        DATASTORE.y_test.loc[:] = 1 - DATASTORE.y_test

        perturbed = eda_workspace_service.vif_resolution_plan(self.request())

        self.assertEqual(perturbed["plan_hash"], baseline["plan_hash"])
        self.assertEqual(perturbed["current"], baseline["current"])
        self.assertEqual(perturbed["proposed"], baseline["proposed"])
        self.assertEqual(
            perturbed["per_feature_vif_deltas"],
            baseline["per_feature_vif_deltas"],
        )
        self.assertEqual(perturbed["analysis_scope"]["sealed_final_holdout_rows_excluded"], 60)
        self.assertFalse(perturbed["analysis_scope"]["final_holdout_used_for_selection"])

    def test_relationships_plan_and_simulator_share_exact_governed_vif_basis(self) -> None:
        workspace = eda_workspace_service.section(
            "relationships",
            EDAWorkspaceRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                dataset_version=VERSION_ID,
                target="bad_flag",
                event_value=1,
                problem_type="classification",
            ),
        )
        plan = eda_workspace_service.vif_resolution_plan(self.request())
        simulation = eda_workspace_service.vif_simulation(
            EDAVifSimulationRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                dataset_version=VERSION_ID,
                target="bad_flag",
                event_value=1,
                problem_type="classification",
                excluded_feature="NumInqLast6M",
            )
        )

        governed = workspace["governed_relationship_artifact"]
        self.assertEqual(plan["current"]["vif"], governed["vif"])
        self.assertEqual(simulation["before"], governed["vif"])
        self.assertEqual(
            plan["analysis_scope"]["governed_relationship_artifact_id"],
            governed["artifact_id"],
        )
        self.assertEqual(
            simulation["governed_relationship_artifact_id"],
            governed["artifact_id"],
        )
        self.assertEqual(
            plan["analysis_scope"]["current_vif_artifact_basis"],
            "governed_development_ordinary_numeric_complete_case",
        )
        self.assertFalse(simulation["final_holdout_accessed"])

    def test_exact_heloc_sized_split_scopes_plan_to_5020_and_excludes_1255(self) -> None:
        metadata = deepcopy(DATASTORE.meta)
        source = frame(6_275)
        DATASTORE.set_raw(source)
        DATASTORE.set_target("bad_flag")
        DATASTORE.meta.update(
            {
                key: value
                for key, value in metadata.items()
                if key not in {"split_record", "split_status"}
            }
        )
        self.install_exact_split(source, training_rows=5_020)

        result = eda_workspace_service.vif_resolution_plan(self.request())

        self.assertEqual(result["analysis_scope"]["development_rows"], 5_020)
        self.assertEqual(
            result["analysis_scope"]["sealed_final_holdout_rows_excluded"],
            1_255,
        )
        self.assertEqual(
            result["analysis_scope"]["development_population"],
            "exact_materialized_development_partition_only",
        )
        self.assertFalse(result["analysis_scope"]["final_holdout_accessed"])
        self.assertTrue(
            all(
                profile["signal_scope"]
                == "exact_materialized_development_partition_only"
                for profile in result["feature_profiles"].values()
            )
        )

    def test_pre_split_plan_fails_closed_without_full_population_fallback(self) -> None:
        DATASTORE.reset_splits()
        DATASTORE.meta.pop("split_record", None)
        DATASTORE.meta.pop("split_status", None)

        with self.assertRaisesRegex(
            ValueError,
            "current durable development split",
        ):
            eda_workspace_service.vif_resolution_plan(self.request())

    def test_stale_or_unmaterialized_split_fails_closed(self) -> None:
        DATASTORE.reset_splits()

        with self.assertRaisesRegex(
            ValueError,
            "materialized development partition is missing",
        ):
            eda_workspace_service.vif_resolution_plan(self.request())

    def test_acceptance_creates_draft_recommendations_and_evidence_only(self) -> None:
        before = DATASTORE.get_base_df().copy(deep=True)
        manifest_before = deepcopy(DATASTORE.meta["feature_manifest"])
        plan = eda_workspace_service.vif_resolution_plan(self.request())
        result = eda_workspace_service.vif_resolution_decision(
            EDAVifResolutionDecisionRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                dataset_version=VERSION_ID,
                plan_id=plan["plan_id"],
                action="accept_complete",
                rationale="Carry recommendations forward for governed review.",
            ),
            actor_id="vif-test-owner",
        )
        queue = get_feature_recommendations(PROJECT_ID, DATASET_ID, VERSION_ID, plan["plan_id"])
        carry_forward = eda_workspace_service.vif_feature_recommendations(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
        )
        self.assertEqual(result["status"], "accepted")
        self.assertIsNotNone(result["evidence"])
        self.assertEqual(queue["recommendation_contract"], "draft_feature_engineering_recommendations")
        self.assertTrue(queue["recommendations"])
        self.assertEqual(carry_forward["count"], len(queue["recommendations"]))
        self.assertEqual(
            carry_forward["recommendation_contract"],
            "draft_feature_engineering_recommendations",
        )
        self.assertFalse(queue["governed_feature_set_changed"])
        self.assertFalse(queue["dataset_mutated"])
        pd.testing.assert_frame_equal(DATASTORE.get_base_df(), before)
        self.assertEqual(DATASTORE.meta["feature_manifest"], manifest_before)

    def test_send_to_feature_engineering_cannot_broaden_partial_acceptance(self) -> None:
        plan = eda_workspace_service.vif_resolution_plan(
            self.request(resolution_objective="preserve_signal")
        )
        selected_cluster = plan["clusters"][0]["cluster_id"]
        accepted = eda_workspace_service.vif_resolution_decision(
            EDAVifResolutionDecisionRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                dataset_version=VERSION_ID,
                plan_id=plan["plan_id"],
                action="accept_selected",
                selected_cluster_ids=[selected_cluster],
            ),
            actor_id="vif-test-owner",
        )
        sent = eda_workspace_service.vif_resolution_decision(
            EDAVifResolutionDecisionRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                dataset_version=VERSION_ID,
                plan_id=plan["plan_id"],
                action="send_to_feature_engineering",
            ),
            actor_id="vif-test-owner",
        )

        self.assertEqual(accepted["status"], "partially_accepted")
        self.assertEqual(sent["status"], "sent_to_feature_engineering")
        self.assertEqual(sent["decision"]["selected_cluster_ids"], [selected_cluster])
        self.assertEqual(len(sent["feature_recommendations"]["recommendations"]), 1)
        self.assertEqual(
            sent["feature_recommendations"]["recommendations"][0]["cluster_id"],
            selected_cluster,
        )
        self.assertFalse(sent["governed_feature_set_changed"])
        self.assertFalse(sent["dataset_mutated"])


class PureVifPolicyTests(unittest.TestCase):
    def test_calculator_recomputes_complete_vif_for_every_path(self) -> None:
        source = frame(120)[
            ["NumInqLast6M", "NumInqLast6Mexcl7days", "Balance", "BalanceShadow", "Age"]
        ]
        calls: list[tuple[str, ...]] = []

        def calculator(work: pd.DataFrame):
            calls.append(tuple(work.columns))
            return eda_workspace_service._vif(work)

        result = build_vif_resolution_plan(
            frame=source,
            vif_calculator=calculator,
            profiles={name: {"development_signal": 0.1, "interpretability": 1.0, "production_availability": 1.0} for name in source},
            model_family="linear_scorecard",
            target_threshold=5,
            objective="reduce_max_vif",
            protected_predictors=[],
            allowed_actions=["retain", "exclude", "combine", "defer"],
            correlation_threshold=0.9,
            preference_weights=EDAVifPreferenceWeights().model_dump(),
            maximum_removals=2,
        )
        self.assertEqual(len(calls), result["calculation_count"]["total_complete_vif_calculations"])
        self.assertTrue(any(len(columns) == 4 for columns in calls))
        self.assertTrue(any(len(columns) == 3 for columns in calls))


def tearDownModule() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.dataset_store import DatasetStore  # noqa: E402
from server.preprocessing.execution_contract import (  # noqa: E402
    default_no_treatment_contract,
)
from server.training.training_job_service import (  # noqa: E402
    TrainingJobService,
    _governed_validation_execution_policy,
)
from server.training.candidate_contract import complete_training_contract  # noqa: E402
from server.training.training_preflight_service import (  # noqa: E402
    _governed_training_target_semantics,
)
from tests.analysis_partition_fixture import GovernedAnalysisFixture  # noqa: E402


class TrainingJobScopeIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = {
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
        }
        self.store = DatasetStore()
        self.store.set_raw(
            pd.DataFrame(
                {
                    "feature_a": [float(index % 7) for index in range(40)],
                    "bad_flag": [index % 2 for index in range(40)],
                }
            )
        )
        self.store.set_target("bad_flag")
        self.governed_fixture = GovernedAnalysisFixture(
            project_id=self.identity["project_id"],
            owner="user-1",
        )
        installed = self.governed_fixture.install(
            self.store,
            dataset_id=self.identity["dataset_id"],
            dataset_version_id=self.identity["dataset_version_id"],
            target="bad_flag",
            authorized_predictors=["feature_a"],
        )
        # Candidate training keeps only the Development Population resident;
        # the sealed holdout is opened later at the final-reporting boundary.
        self.store.set_splits(
            self.store.X_train,
            None,
            self.store.y_train,
            None,
        )
        partition = installed["record"]
        validation_design = {
            **self.identity,
            "validation_design_id": "design-1",
            "design_version": "design-version-1",
            "status": "approved",
            "analysis_partition_id": partition["analysis_partition_id"],
            "analysis_partition_revision": partition["revision"],
            "target_contract_id": partition["target_contract_id"],
            "target": "bad_flag",
            "problem_type": "classification",
            "event_value": 1,
            "non_event_value": 0,
            "fold_local_preprocessing": "fit_transform_per_fold",
            "target_definition": {
                "target": "bad_flag",
                "problem_type": "classification",
                "positive_value": 1,
                "negative_value": 0,
                "target_contract_id": partition["target_contract_id"],
                "authority_source": "sealed_analysis_partition",
            },
        }
        split_record = {
            **self.identity,
            "split_id": "split-1",
            "analysis_partition_id": partition["analysis_partition_id"],
            "analysis_partition_revision": partition["revision"],
            "target_contract_id": partition["target_contract_id"],
            "target": "bad_flag",
            "problem_type": "classification",
            "event_value": 1,
            "non_event_value": 0,
            "validation_design": validation_design,
            "fold_definition_id": "fold-definition-1",
            "cv_design": {"random_seed": 42},
            "balancing_policy": {
                "method": "none",
                "class_weight_policy": "none",
                "selection_resampling_status": "not_applied",
            },
        }
        preprocessing_policy = default_no_treatment_contract(
            identity={
                **self.identity,
                "analysis_partition_id": partition[
                    "analysis_partition_id"
                ],
                "analysis_partition_revision": partition["revision"],
            },
            feature_names=["feature_a"],
            source="training_job_scope_identity_fixture",
        )
        self.store.meta.update(
            {
                "split_status": "current",
                "analysis_partition": partition,
                "feature_manifest": {
                    **self.identity,
                    "manifest_hash": "manifest-1",
                },
                "split_record": split_record,
                "preprocessing_policy": preprocessing_policy,
            }
        )
        self.target_authority = _governed_training_target_semantics(
            split_record=split_record,
            active_target=self.store.target or "",
            analysis_partition=partition,
            active_identity=self.identity,
        )
        self.validation_execution_policy = _governed_validation_execution_policy(
            {
                "validation_design": validation_design,
                "validation_design_id": validation_design[
                    "validation_design_id"
                ],
                "validation_design_version": validation_design[
                    "design_version"
                ],
                "fold_definition_id": split_record["fold_definition_id"],
                "cv_design": split_record["cv_design"],
                "balancing_configuration": split_record[
                    "balancing_policy"
                ],
            }
        )
        self.job = {
            **self.identity,
            "job_id": "job-1",
            "owner_user_id": "user-1",
            "data_revision": self.store.data_revision,
            "feature_manifest_version": "manifest-1",
            "split_id": "split-1",
            "validation_design_id": "design-1",
            "validation_design_version": "design-version-1",
            "target_semantics_authority": self.target_authority,
            "target_authority_hash": self.target_authority[
                "target_authority_hash"
            ],
            "source_target_contract_id": self.target_authority[
                "source_target_contract_id"
            ],
            "analysis_partition_id": self.target_authority[
                "analysis_partition_id"
            ],
            "analysis_partition_revision": self.target_authority[
                "analysis_partition_revision"
            ],
            "validation_execution_policy": self.validation_execution_policy,
            "governed_preprocessing_contract": preprocessing_policy,
            "preprocessing_contract_version": preprocessing_policy[
                "preprocessing_contract_version"
            ],
            "preprocessing_policy_id": preprocessing_policy[
                "preprocessing_policy_id"
            ],
            "preprocessing_policy_revision": preprocessing_policy[
                "preprocessing_policy_revision"
            ],
            "preprocessing_policy_hash": preprocessing_policy[
                "preprocessing_policy_hash"
            ],
            "_dataset_store": self.store,
            "overall_status": "running",
            "completed_at": None,
            "user_message": "",
            "message": "",
            "developer_details": [],
            "per_model_status": {
                "logreg": {"status": "running", "state": "running"}
            },
            "per_model_history": {"logreg": []},
        }
        self.job["contract"] = complete_training_contract(
            {
                **self.identity,
                "data_revision": self.store.data_revision,
                "target": "bad_flag",
                "problem_type": "classification",
                "event_value": 1,
                "non_event_value": 0,
                "target_semantics_authority": self.target_authority,
                "target_authority_hash": self.target_authority[
                    "target_authority_hash"
                ],
                "source_target_contract_id": self.target_authority[
                    "source_target_contract_id"
                ],
                "analysis_partition_id": self.target_authority[
                    "analysis_partition_id"
                ],
                "analysis_partition_revision": self.target_authority[
                    "analysis_partition_revision"
                ],
                "feature_manifest_version": "manifest-1",
                "selected_original_features": ["feature_a"],
                "selected_engineered_features": [],
                "preprocessing_pipeline": [],
                "split_id": "split-1",
                "validation_design_id": "design-1",
                "validation_design_version": "design-version-1",
                "training_population_id": "training-population-1",
                "selection_partition_id": "training-population-1",
                "holdout_population_id": "holdout-population-1",
                "final_holdout_partition_id": "holdout-population-1",
                "fold_definition_id": "fold-definition-1",
                "final_holdout_status": "sealed",
                "holdout_isolation_status": "verified",
                "selection_resampling_status": "not_applied",
                "random_seed": 42,
                "calibration_configuration": {"requested": False},
                "runtime_environment": {},
            },
            feature_manifest=self.store.meta["feature_manifest"],
            store_meta=self.store.meta,
            training_job_id="job-1",
            training_run_id="run-1",
            created_by="user-1",
            created_at="2026-07-31T12:00:00+00:00",
            primary_metric="roc_auc",
        )

    def tearDown(self) -> None:
        self.governed_fixture.close()

    def checkpoint_result(self, *_args, **_kwargs):
        return True, "", dict(self.identity)

    def test_current_validation_design_keeps_job_running(self):
        with patch(
            "server.training.training_job_service.validate_checkpoint_identity",
            side_effect=self.checkpoint_result,
        ):
            current, reason = TrainingJobService._scope_matches_job(self.job)

        self.assertTrue(current)
        self.assertEqual(reason, "")

    def test_design_change_interrupts_job_before_persistence(self):
        service = TrainingJobService()
        service._jobs[self.job["job_id"]] = self.job
        service._cancel_events[self.job["job_id"]] = Event()
        self.store.meta["split_record"]["validation_design"][
            "validation_design_id"
        ] = "design-2"

        with patch(
            "server.training.training_job_service.validate_checkpoint_identity",
            side_effect=self.checkpoint_result,
        ):
            interrupted = service._interrupt_if_scope_changed(
                self.job["job_id"]
            )

        self.assertTrue(interrupted)
        self.assertTrue(service._cancel_events[self.job["job_id"]].is_set())
        self.assertEqual(self.job["overall_status"], "interrupted")
        self.assertEqual(
            self.job["per_model_status"]["logreg"]["status"],
            "interrupted",
        )
        self.assertEqual(
            self.job["developer_details"][-1]["stage"],
            "canonical_scope_revalidation",
        )


if __name__ == "__main__":
    unittest.main()

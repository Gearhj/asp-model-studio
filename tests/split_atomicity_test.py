"""Focused regression coverage for governed split/training atomicity."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.core.dataset_store import DatasetStore
from server.core.result_store import ResultStore
from server.splitting import split_router
from server.training import trainer_router, training_preflight_service
from server.training.training_job_types import TrainingJobRequest


IDENTITY = {
    "project_id": "project-split-atomic",
    "dataset_id": "dataset-development",
    "dataset_version_id": "version-development-exact",
}
MANIFEST_ID = "manifest-exact"


def _frame(rows: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "predictor": [float(index % 17) for index in range(rows)],
            "bad_flag": [index % 2 for index in range(rows)],
        }
    )


def _manifest() -> dict:
    return {
        **IDENTITY,
        "dataset_version": IDENTITY["dataset_version_id"],
        "manifest_hash": MANIFEST_ID,
        "manifest_version": MANIFEST_ID,
        "validation_status": "passed",
        "materialization_status": "current",
        "materialized_manifest_hash": MANIFEST_ID,
        "confirmation_status": "confirmed",
        "confirmed_manifest_hash": MANIFEST_ID,
        "split_status": "current",
        "features": [
            {
                "feature_name": "predictor",
                "selected": True,
                "eligibility_status": "eligible",
                "origin": "original",
            }
        ],
    }


def _seed_store() -> DatasetStore:
    store = DatasetStore()
    store.set_raw(_frame())
    store.set_target("bad_flag")
    store.meta.update(
        {
            **IDENTITY,
            "dataset_version": IDENTITY["dataset_version_id"],
            "dataset_identity_status": "current",
            "selected_columns": ["predictor"],
            "feature_manifest": _manifest(),
        }
    )
    return store


def _seed_current_split(store: DatasetStore) -> None:
    frame = _frame(20)
    store.set_splits(
        frame.loc[:14, ["predictor"]],
        frame.loc[15:, ["predictor"]],
        frame.loc[:14, "bad_flag"],
        frame.loc[15:, "bad_flag"],
    )
    design = {
        **IDENTITY,
        "dataset_version": IDENTITY["dataset_version_id"],
        "data_revision": store.data_revision,
        "validation_design_id": "design-old",
        "design_version": "design-version-old",
        "feature_manifest_hash": MANIFEST_ID,
        "status": "approved",
    }
    store.meta.update(
        {
            "split_record": {
                **IDENTITY,
                "dataset_version": IDENTITY["dataset_version_id"],
                "data_revision": store.data_revision,
                "split_id": "split-old",
                "feature_manifest_version": MANIFEST_ID,
                "selected_features": ["predictor"],
                "validation_design": design,
                "distributions": {
                    "train_after_balancing": {"events": 8},
                    "holdout_untouched": {"events": 2},
                },
                "completion_gates": {},
            },
            "split_config": {"split_id": "split-old"},
            "validation_design": design,
            "target_prevalence": {"original": 0.5},
            "training_execution": {"training_job_id": "job-old"},
            "model_selection_decision": {"champion_model": "logreg"},
            "active_training_job_id": "job-old",
            "split_status": "current",
        }
    )


def _split_payload() -> split_router.SplitConfigPayload:
    return split_router.SplitConfigPayload(
        project_id=IDENTITY["project_id"],
        split_strategy="holdout",
        test_size=0.2,
        random_seed=42,
        stratify=True,
        balance_method="none",
        problem_type="classification",
        event_value=1,
        selected_features=["predictor"],
        feature_manifest_version=MANIFEST_ID,
        dataset_id=IDENTITY["dataset_id"],
        dataset_version_id=IDENTITY["dataset_version_id"],
        dataset_version=IDENTITY["dataset_version_id"],
        development_dataset_id=IDENTITY["dataset_id"],
        development_dataset_version_id=IDENTITY["dataset_version_id"],
        fold_method="none",
        holdout_protection_confirmed=True,
        approval_note="Focused atomic split regression.",
    )


class SplitAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _seed_store()
        self.results = ResultStore()

    @staticmethod
    def _assert_identity(
        project_id: str,
        *,
        expected_dataset_id: str = "",
        expected_dataset_version_id: str = "",
        legacy_dataset_version: str = "",
        **_: object,
    ) -> dict[str, str]:
        if (
            project_id != IDENTITY["project_id"]
            or (
                expected_dataset_id
                and expected_dataset_id != IDENTITY["dataset_id"]
            )
            or (
                expected_dataset_version_id
                and expected_dataset_version_id
                != IDENTITY["dataset_version_id"]
            )
            or (
                legacy_dataset_version
                and legacy_dataset_version != IDENTITY["dataset_version_id"]
            )
        ):
            raise HTTPException(status_code=409, detail="Identity mismatch.")
        return dict(IDENTITY)

    @contextmanager
    def _patched_split(self):
        with (
            patch.object(split_router, "DATASTORE", self.store),
            patch.object(split_router, "RESULTS", self.results),
            patch.object(split_router, "authorize_modeling_scope"),
            patch.object(
                split_router,
                "assert_expected_active_identity",
                side_effect=self._assert_identity,
            ),
            patch.object(split_router, "audit_event"),
            patch.object(split_router, "schedule_checkpoint_save"),
        ):
            yield

    def test_rebuild_invalidates_old_results_then_publishes_one_current_split(
        self,
    ) -> None:
        _seed_current_split(self.store)
        old_revision = self.store.data_revision
        self.results.set_last_summary({"training_job_id": "job-old"})
        self.results.set_model_artifacts({"logreg": object()})
        self.results.set_model_availability({"logreg": True})
        self.results.set_final_model(object(), {"training_job_id": "job-old"})
        self.results.set_scoring_reference({"training_job_id": "job-old"})

        with self._patched_split():
            response = split_router.balancing_split_config(
                _split_payload(),
                user={},
            )

        self.assertTrue(response["ready"])
        self.assertEqual(self.store.data_revision, old_revision + 1)
        self.assertEqual(self.store.meta["split_status"], "current")
        self.assertEqual(
            self.store.meta["feature_manifest"]["split_status"],
            "current",
        )
        self.assertTrue(all(part is not None for part in self.store.get_splits()))
        record = self.store.meta["split_record"]
        design = self.store.meta["validation_design"]
        self.assertNotEqual(record["split_id"], "split-old")
        self.assertEqual(record["data_revision"], self.store.data_revision)
        self.assertEqual(design["data_revision"], self.store.data_revision)
        self.assertEqual(
            self.store.meta["split_config"]["data_revision"],
            self.store.data_revision,
        )
        self.assertEqual(
            record["validation_design"]["validation_design_id"],
            design["validation_design_id"],
        )
        for stale_key in (
            "training_execution",
            "model_selection_decision",
            "active_training_job_id",
        ):
            self.assertNotIn(stale_key, self.store.meta)
        self.assertIsNone(self.results.get_last_summary())
        self.assertEqual(self.results.get_model_artifacts(), {})
        self.assertEqual(self.results.get_model_availability(), {})
        self.assertIsNone(self.results.get_final_model())
        self.assertIsNone(self.results.get_scoring_reference())

    def test_manifest_change_during_computation_rejects_without_partial_commit(
        self,
    ) -> None:
        _seed_current_split(self.store)
        old_splits = self.store.get_splits()
        self.results.set_last_summary({"training_job_id": "job-old"})
        original = split_router.split_service.make_validation_split

        def compute_then_change_manifest(*args, **kwargs):
            result = original(*args, **kwargs)
            with self.store.state_lock:
                self.store.meta["feature_manifest"][
                    "confirmation_status"
                ] = "changed-during-compute"
            return result

        with (
            self._patched_split(),
            patch.object(
                split_router.split_service,
                "make_validation_split",
                side_effect=compute_then_change_manifest,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                split_router.balancing_split_config(
                    _split_payload(),
                    user={},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.store.meta["split_record"]["split_id"], "split-old")
        self.assertEqual(
            self.results.get_last_summary(),
            {"training_job_id": "job-old"},
        )
        current_splits = self.store.get_splits()
        for before, after in zip(old_splits, current_splits):
            if isinstance(before, pd.DataFrame):
                pd.testing.assert_frame_equal(before, after)
            else:
                pd.testing.assert_series_equal(before, after)

    def test_status_marks_revoked_or_missing_external_pin_stale(self) -> None:
        _seed_current_split(self.store)
        self.store.meta["split_record"]["test_reference"] = {
            "role": "TEST",
            "dataset_id": "dataset-test",
            "dataset_version_id": "version-test",
            "version_id": "version-test",
        }
        with (
            patch.object(split_router, "DATASTORE", self.store),
            patch.object(
                split_router,
                "active_dataset_identity",
                return_value=dict(IDENTITY),
            ),
            patch.object(
                split_router,
                "resolve_registered_version",
                side_effect=HTTPException(
                    status_code=403,
                    detail="Dataset ACL denied.",
                ),
            ),
        ):
            status = split_router._current_status(
                IDENTITY["project_id"],
                user={"userId": "owner"},
            )

        self.assertEqual(status["status"], "stale")
        self.assertFalse(status["ready"])
        self.assertIn("TEST", status["readiness_reason"])
        self.assertIn("Rebuild Validation Design", status["readiness_reason"])

    def test_training_preflight_blocks_stale_external_pin(self) -> None:
        _seed_current_split(self.store)
        self.store.meta["split_record"]["test_reference"] = {
            "role": "TEST",
            "dataset_id": "dataset-test",
            "dataset_version_id": "version-test",
            "version_id": "version-test",
        }
        request = TrainingJobRequest(
            models=["logreg"],
            project_id=IDENTITY["project_id"],
            dataset_id=IDENTITY["dataset_id"],
            dataset_version_id=IDENTITY["dataset_version_id"],
            target="bad_flag",
            event_value=1,
            non_event_value=0,
            problem_type="classification",
            feature_manifest_version=MANIFEST_ID,
            split_id="split-old",
            validation_design_id="design-old",
            validation_design_version="design-version-old",
        )
        acl_calls: list[tuple[str, str, dict]] = []

        def revoked(
            dataset_id: str,
            dataset_version_id: str,
            *,
            user: dict,
        ):
            acl_calls.append((dataset_id, dataset_version_id, user))
            raise HTTPException(
                status_code=403,
                detail="Dataset ACL was revoked.",
            )

        authenticated_user = {
            "userId": "split-owner",
            "role": "data_scientist",
        }
        with (
            patch.object(
                training_preflight_service,
                "DATASTORE",
                SimpleNamespace(
                    current=lambda: self.store,
                    meta=self.store.meta,
                    target=self.store.target,
                ),
            ),
            patch.object(
                training_preflight_service,
                "assert_expected_active_identity",
                return_value=dict(IDENTITY),
            ),
            patch.object(
                training_preflight_service,
                "resolve_registered_version",
                side_effect=revoked,
            ),
            patch.object(
                training_preflight_service,
                "active_user",
                return_value=authenticated_user,
            ),
            patch.object(
                training_preflight_service,
                "_model_available",
                return_value=(True, "Available"),
            ),
        ):
            preflight = training_preflight_service.training_preflight(request)

        self.assertFalse(preflight["ready"])
        self.assertEqual(preflight["split_status"], "stale")
        self.assertTrue(
            any(
                "pinned TEST dataset version is stale" in error
                for error in preflight["blocking_errors"]
            )
        )
        self.assertEqual(
            acl_calls,
            [
                (
                    "dataset-test",
                    "version-test",
                    authenticated_user,
                )
            ],
        )

    def test_last_summary_requires_current_revision_manifest_split_and_design(
        self,
    ) -> None:
        _seed_current_split(self.store)
        valid_summary = {
            **IDENTITY,
            "dataset_version": IDENTITY["dataset_version_id"],
            "data_revision": self.store.data_revision,
            "feature_manifest_version": MANIFEST_ID,
            "split_id": "split-old",
            "validation_design_id": "design-old",
            "validation_design_version": "design-version-old",
            "target": "bad_flag",
            "problem_type": "classification",
        }
        self.results.set_last_summary(dict(valid_summary))

        with (
            patch.object(trainer_router, "DATASTORE", self.store),
            patch.object(trainer_router, "RESULTS", self.results),
            patch.object(trainer_router, "authorize_modeling_scope"),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self._assert_identity,
            ),
        ):
            valid = trainer_router.get_last_train(
                project_id=IDENTITY["project_id"],
                dataset_id=IDENTITY["dataset_id"],
                dataset_version_id=IDENTITY["dataset_version_id"],
                dataset_version=IDENTITY["dataset_version_id"],
                target="bad_flag",
                problem_type="classification",
                user={},
            )
            self.assertEqual(valid["summary"], valid_summary)

            for field in (
                "data_revision",
                "feature_manifest_version",
                "split_id",
                "validation_design_id",
                "validation_design_version",
            ):
                stale = dict(valid_summary)
                stale[field] = (
                    self.store.data_revision - 1
                    if field == "data_revision"
                    else f"stale-{field}"
                )
                self.results.set_last_summary(stale)
                response = trainer_router.get_last_train(
                    project_id=IDENTITY["project_id"],
                    dataset_id=IDENTITY["dataset_id"],
                    dataset_version_id=IDENTITY["dataset_version_id"],
                    dataset_version=IDENTITY["dataset_version_id"],
                    target="bad_flag",
                    problem_type="classification",
                    user={},
                )
                self.assertIsNone(response["summary"], field)
                self.assertTrue(response.get("context_error"), field)

    def test_legacy_synchronous_training_route_is_gone(self) -> None:
        with (
            patch.object(trainer_router, "authorize_modeling_scope"),
            patch.object(trainer_router.TRAINER, "train") as train,
        ):
            with self.assertRaises(HTTPException) as raised:
                trainer_router.train_models(
                    {"project_id": IDENTITY["project_id"], "models": ["logreg"]},
                    user={},
                )
        self.assertEqual(raised.exception.status_code, 410)
        train.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEMP_PARENT = _REPO_ROOT / ".tmp"
_TEMP_PARENT.mkdir(parents=True, exist_ok=True)
_TEST_ROOT = (
    _TEMP_PARENT / f"atlas_data_validation_simplification_{uuid.uuid4().hex}"
).resolve()
_SECURITY_ROOT = _TEST_ROOT / "security"
_SECURITY_DB = _SECURITY_ROOT / "atlas_security.db"
_PERSISTENCE_DB = _TEST_ROOT / "persistence" / "atlas_local.db"
_CHECKPOINT_PATH = _TEST_ROOT / "checkpoint" / "workflow_checkpoint.json"
_DATASET_LIBRARY_ROOT = _TEST_ROOT / "dataset-library"
_EVIDENCE_ROOT = _TEST_ROOT / "evidence"
_MODEL_ARTIFACT_ROOT = _TEST_ROOT / "model-registry"
_SCORING_ARTIFACT_ROOT = _TEST_ROOT / "scoring-runs"
_ISOLATED_ENVIRONMENT = {
    "ATLAS_SECURITY_ROOT": str(_SECURITY_ROOT),
    "ATLAS_SECURITY_DB_PATH": str(_SECURITY_DB),
    "ATLAS_SQLITE_PATH": str(_PERSISTENCE_DB),
    "ATLAS_CHECKPOINT_PATH": str(_CHECKPOINT_PATH),
    "ATLAS_DATASET_LIBRARY_ROOT": str(_DATASET_LIBRARY_ROOT),
    "ATLAS_EVIDENCE_ROOT": str(_EVIDENCE_ROOT),
    "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": str(_MODEL_ARTIFACT_ROOT),
    "ATLAS_SCORING_RUN_ARTIFACT_ROOT": str(_SCORING_ARTIFACT_ROOT),
}
os.environ.update(_ISOLATED_ENVIRONMENT)

from server.core import session_checkpoint  # noqa: E402
from server.core.dataset_store import DATASTORE  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402
from server.evidence import evidence_store  # noqa: E402
from server.model_registry import model_artifacts  # noqa: E402
from server.persistence import db as persistence_db  # noqa: E402
from server.persistence import service as persistence_service  # noqa: E402
from server.preprocessing.bureau_detection_service import (  # noqa: E402
    detect_bureau_data,
)
from server.preprocessing.bureau_detection_types import (  # noqa: E402
    BureauDetectionRequest,
    BureauMetadataInput,
)
from server.splitting import split_router  # noqa: E402
from server.splitting.split_router import _current_status  # noqa: E402
from server.splitting.split_service import split_service  # noqa: E402
from server.scoring_runs import scoring_run_artifacts  # noqa: E402
from server.security import security_store  # noqa: E402


def _rebind_isolated_runtime() -> None:
    os.environ.update(_ISOLATED_ENVIRONMENT)
    dataset_registry.ARTIFACT_ROOT = _DATASET_LIBRARY_ROOT
    dataset_registry.REGISTRY_PATH = _DATASET_LIBRARY_ROOT / "registry.json"
    dataset_registry.USERS_PATH = _DATASET_LIBRARY_ROOT / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = _DATASET_LIBRARY_ROOT / "project_links.json"
    session_checkpoint.CHECKPOINT_PATH = _CHECKPOINT_PATH
    evidence_store.EVIDENCE_ROOT = _EVIDENCE_ROOT
    evidence_store.ITEMS_ROOT = _EVIDENCE_ROOT / "items"
    evidence_store.REGISTRY_PATH = _EVIDENCE_ROOT / "evidence_registry.json"
    model_artifacts.ARTIFACT_ROOT = _MODEL_ARTIFACT_ROOT
    scoring_run_artifacts.ARTIFACT_ROOT = _SCORING_ARTIFACT_ROOT
    security_store.SECURITY_ROOT = _SECURITY_ROOT
    security_store.DB_PATH = _SECURITY_DB
    persistence_db._database = persistence_db.Database(_PERSISTENCE_DB)
    persistence_service._service = None

    forbidden_roots = (
        _REPO_ROOT / ".runtime",
        _REPO_ROOT / "server" / "data",
        _REPO_ROOT / "server" / "artifacts" / "datasets",
        _REPO_ROOT / "server" / "artifacts" / "security",
        _REPO_ROOT / "server" / "artifacts" / "evidence",
        _REPO_ROOT / "server" / "artifacts" / "model_registry",
        _REPO_ROOT / "server" / "artifacts" / "scoring_runs",
    )
    for label, path in (
        ("security database", security_store.DB_PATH),
        ("persistence database", persistence_db.get_database().path),
        ("checkpoint", session_checkpoint.CHECKPOINT_PATH),
        ("dataset library", dataset_registry.ARTIFACT_ROOT),
        ("evidence root", evidence_store.EVIDENCE_ROOT),
        ("model artifact root", model_artifacts.ARTIFACT_ROOT),
        ("scoring artifact root", scoring_run_artifacts.ARTIFACT_ROOT),
    ):
        resolved = Path(path).resolve()
        if resolved != _TEST_ROOT and _TEST_ROOT not in resolved.parents:
            raise AssertionError(f"{label} escaped the suite-owned temporary root: {resolved}")
        if any(
            resolved == forbidden.resolve() or forbidden.resolve() in resolved.parents
            for forbidden in forbidden_roots
        ):
            raise AssertionError(f"{label} targets checked-in runtime state: {resolved}")


def governed_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ExternalRiskEstimate": [
                -9,
                -8,
                -7,
                64,
                67,
                70,
                None,
                "parse-failure",
                72,
                74,
            ],
            "MSinceMostRecentDelq": [
                -9,
                12,
                18,
                -8,
                22,
                25,
                29,
                31,
                35,
                40,
            ],
            "NumTotalTrades": [10, 11, 9, 12, 15, 14, 8, 17, 19, 16],
            "bad_flag": [1, 0, 1, 0, 1, 0, 0, 1, 0, 1],
        }
    )


class SpecialValueContractTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(_TEST_ROOT, ignore_errors=True)

    def setUp(self) -> None:
        _rebind_isolated_runtime()

    def tearDown(self):
        DATASTORE.reset_all()

    def test_detection_exposes_table_counts_without_merging_semantics(self):
        frame = governed_frame()
        DATASTORE.reset_all()
        DATASTORE.set_raw(frame)
        DATASTORE.set_target("bad_flag")
        DATASTORE.meta["event_value"] = 1

        result = detect_bureau_data(
            BureauDetectionRequest(
                project_id="special-value-contract",
                target="bad_flag",
                event_value=1,
                metadata=[
                    BureauMetadataInput(
                        variableName="ExternalRiskEstimate",
                        bureauSource="HELOC data dictionary",
                    ),
                    BureauMetadataInput(
                        variableName="MSinceMostRecentDelq",
                        bureauSource="HELOC data dictionary",
                    ),
                ],
            )
        )

        self.assertTrue(result["detected"])
        self.assertEqual(result["row_count"], 10)
        # The same row can carry specials in two variables and is counted once.
        self.assertEqual(result["rows_with_special_values"], 4)
        by_name = {row["variable"]: row for row in result["variables"]}
        risk = by_name["ExternalRiskEstimate"]
        self.assertEqual(risk["special_value_count"], 3)
        self.assertEqual(risk["ordinary_value_count"], 5)
        self.assertEqual(risk["null_count"], 1)
        self.assertEqual(risk["parse_failure_count"], 1)
        for special in risk["special_values"]:
            self.assertIn("event_count", special)
            self.assertIn("event_rate", special)
            self.assertIn("regular_event_rate", special)
            self.assertIn("event_rate_delta", special)


class ValidationDefaultContractTests(unittest.TestCase):
    def tearDown(self):
        DATASTORE.reset_all()

    def test_target_distribution_is_available_before_a_split_exists(self):
        frame = governed_frame()
        project_id = "validation-default-contract"
        dataset_id = "heloc-target-contract"
        dataset_version_id = "heloc-target-contract-v1"
        DATASTORE.reset_all()
        DATASTORE.set_raw(frame)
        DATASTORE.set_target("bad_flag")
        DATASTORE.meta.update(
            {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "dataset_version": dataset_version_id,
                "feature_manifest": {
                    "project_id": project_id,
                    "dataset_id": dataset_id,
                    "dataset_version_id": dataset_version_id,
                    "manifest_hash": "manifest-validation-default",
                    "features": [
                        {
                            "feature_name": column,
                            "selected": True,
                            "eligibility_status": "eligible",
                            "origin": "original",
                        }
                        for column in frame.columns
                        if column != "bad_flag"
                    ],
                },
            }
        )
        DATASTORE.meta["event_value"] = 1

        with patch.object(
            split_router,
            "active_dataset_identity",
            return_value={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
            },
        ):
            status = _current_status(project_id)
        self.assertEqual(status["status"], "not_created")
        self.assertFalse(status["has_split"])
        distribution = status["distributions"]["full_dataset"]
        self.assertEqual(distribution["rows"], 10)
        self.assertEqual(distribution["events"], 5)
        self.assertEqual(distribution["non_events"], 5)
        self.assertAlmostEqual(distribution["event_rate"], 0.5)

    def test_standard_hybrid_design_keeps_cv_inside_untouched_holdout_split(self):
        rows = 200
        frame = pd.DataFrame(
            {
                "bureau_score": [500 + index % 100 for index in range(rows)],
                "trade_count": [5 + index % 20 for index in range(rows)],
                "bad_flag": [index % 2 for index in range(rows)],
            }
        )
        result = split_service.make_validation_split(
            frame,
            "bad_flag",
            ["bureau_score", "trade_count"],
            {
                "split_strategy": "hybrid",
                "test_size": 0.2,
                "random_seed": 42,
                "stratify": True,
                "problem_type": "classification",
                "event_value": 1,
                "balance_method": "none",
                "minority_share": 0.5,
                "fold_method": "stratified_k_fold",
                "fold_count": 5,
                "repeats": 1,
                "shuffle": True,
            },
        )

        self.assertEqual(len(result.y_train), 160)
        self.assertEqual(len(result.y_test), 40)
        self.assertEqual(result.evaluation_population_role, "untouched_holdout")
        self.assertEqual(result.fold_architecture["fold_count"], 5)
        self.assertEqual(result.synthetic_rows_added, 0)
        self.assertEqual(result.rows_removed, 0)
        for fold in result.fold_architecture["folds"]:
            self.assertGreater(fold["validation_distribution"]["events"], 0)
            self.assertGreater(
                fold["validation_distribution"]["non_events"],
                0,
            )


if __name__ == "__main__":
    unittest.main()

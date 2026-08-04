from __future__ import annotations

import sys
import unittest
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.credit_risk.governed_scope import (  # noqa: E402
    artifact_scope_payload,
    canonical_scope_fields,
    require_artifact_scope,
    resolve_credit_risk_scope,
)
from server.credit_risk.ml_engine import (  # noqa: E402
    get_project_ml_model_exact,
    train_ml_model,
)
from server.credit_risk.scorecard_engine import (  # noqa: E402
    generate_scorecard_code,
    get_project_scorecard_exact,
    train_scorecard,
)
from server.credit_risk.woe_iv_engine import (  # noqa: E402
    apply_manual_bins,
    generate_code,
    get_project_analysis_exact,
    run_woe_iv,
)


def fake_scope(*, revision: int = 3, rows: int = 60):
    features = pd.DataFrame(
        {
            "income": [float(20 + index * 2) for index in range(rows)],
            "utilization": [float((index * 7) % 41) for index in range(rows)],
        }
    )
    target = pd.Series([index % 2 for index in range(rows)], name="bad_flag")
    metadata = {
        "scope": "development_population",
        "analysis_scope": "development_population",
        "analytical_scope": "development_population",
        "target_directed_scope": "development_population",
        "structural_scope": "full_governed_population_predictors_only",
        "scope_resolution": "durable_current_exact",
        "row_selection_method": "verified_positional_assignment",
        "project_id": "project-1",
        "dataset_id": "dataset-1",
        "dataset_version_id": "version-1",
        "target": "bad_flag",
        "target_contract_id": "target-contract-1",
        "predictor_authorization_id": "predictors-1",
        "analysis_partition_id": "analysis-partition-1",
        "analysis_partition_revision": revision,
        "development_partition_id": f"development-{revision}",
        "sealed_holdout_partition_id": f"holdout-{revision}",
        "full_governed_population_rows": rows + 20,
        "development_rows": rows,
        "sealed_holdout_rows": 20,
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "isolated",
        "final_holdout_accessed": False,
        "final_holdout_used_for_selection": False,
        "raw_dataset_target_fallback_used": False,
        "browser_target_semantics_used": False,
        "population_id": f"development-{revision}",
        "population_count": rows,
        "partition_id": "analysis-partition-1",
        "partition_revision": revision,
        "holdout_excluded": True,
        "source_checksum": "sha256:dataset-1-version-1",
        "actor": "user-1",
        "actor_source": "authenticated_request",
        "timestamp": "2026-08-04T12:00:00+00:00",
    }
    return SimpleNamespace(
        identity={
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
            "dataset": {"datasetId": "dataset-1", "name": "Synthetic"},
        },
        target="bad_flag",
        problem_type="classification",
        event_value=1,
        non_event_value=0,
        development_features=features,
        development_target=target,
        authorized_predictors=["income", "utilization"],
        metadata=lambda: dict(metadata),
    )


def woe_request() -> dict:
    return {
        "projectId": "project-1",
        "datasetId": "dataset-1",
        "datasetVersionId": "version-1",
        "targetColumn": "bad_flag",
        "eventValue": 1,
        "predictorColumns": ["income", "utilization"],
        "binningMethod": "quantile",
        "maxBins": 5,
        "minBinPct": 0.05,
        "smoothing": 0.5,
    }


class CreditRiskGovernedScopeTests(unittest.TestCase):
    def test_woe_uses_only_development_population_and_stamps_lineage(self) -> None:
        scope = fake_scope(rows=60)
        with patch(
            "server.credit_risk.woe_iv_engine.save_analysis",
            side_effect=lambda artifact: artifact,
        ):
            result = run_woe_iv(woe_request(), scope)

        self.assertEqual(result["rowCount"], 60)
        self.assertEqual(result["eventCount"], 30)
        self.assertEqual(result["analysis_scope"], "development_population")
        self.assertEqual(result["population_id"], "development-3")
        self.assertEqual(result["partition_revision"], 3)
        self.assertTrue(result["holdout_excluded"])
        self.assertFalse(result["final_holdout_accessed"])

    def test_woe_rejects_predictor_outside_exact_authorization(self) -> None:
        request = {**woe_request(), "predictorColumns": ["income", "browser_guess"]}
        with self.assertRaises(HTTPException) as raised:
            run_woe_iv(request, fake_scope())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("authorization", str(raised.exception.detail))

    def test_credit_risk_scope_rejects_nonclassification_authority(self) -> None:
        scope = fake_scope()
        scope.problem_type = "regression"
        store = SimpleNamespace(state_lock=RLock())
        with patch(
            "server.credit_risk.governed_scope.authorize_modeling_scope",
            return_value="project-1",
        ), patch(
            "server.credit_risk.governed_scope.DATASTORE",
            SimpleNamespace(current=lambda: store),
        ), patch(
            "server.credit_risk.governed_scope.assert_expected_active_identity",
            return_value=scope.identity,
        ), patch(
            "server.credit_risk.governed_scope.resolve_development_analysis_scope",
            return_value=scope,
        ), self.assertRaises(HTTPException) as raised:
            resolve_credit_risk_scope(woe_request(), {"userId": "user-1"})
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("binary-classification", str(raised.exception.detail))

    def test_credit_risk_scope_rejects_browser_non_event_contradiction(self) -> None:
        scope = fake_scope()
        store = SimpleNamespace(state_lock=RLock())
        request = {**woe_request(), "nonEventValue": 9}
        with patch(
            "server.credit_risk.governed_scope.authorize_modeling_scope",
            return_value="project-1",
        ), patch(
            "server.credit_risk.governed_scope.DATASTORE",
            SimpleNamespace(current=lambda: store),
        ), patch(
            "server.credit_risk.governed_scope.assert_expected_active_identity",
            return_value=scope.identity,
        ), patch(
            "server.credit_risk.governed_scope.resolve_development_analysis_scope",
            return_value=scope,
        ), self.assertRaises(HTTPException) as raised:
            resolve_credit_risk_scope(request, {"userId": "user-1"})
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("non-event", str(raised.exception.detail))

    def test_partition_revision_changes_woe_artifact_id(self) -> None:
        with patch(
            "server.credit_risk.woe_iv_engine.save_analysis",
            side_effect=lambda artifact: artifact,
        ):
            first = run_woe_iv(woe_request(), fake_scope(revision=3))
            second = run_woe_iv(woe_request(), fake_scope(revision=4))
        self.assertNotEqual(first["analysisId"], second["analysisId"])

    def test_manual_generated_code_has_no_full_frame_target_fallback(self) -> None:
        settings = {
            **woe_request(),
            **canonical_scope_fields(fake_scope()),
        }
        code = generate_code(settings)
        self.assertIn("df.iloc[list(DEVELOPMENT_POSITIONS)]", code["python"])
        self.assertIn("governed_development_input", code["sql"])
        self.assertNotIn("from input_table", code["sql"])
        self.assertIn("final holdout excluded", code["python"])

    def test_manual_bin_recalculation_remains_development_bound(self) -> None:
        scope = fake_scope(rows=60)
        with patch(
            "server.credit_risk.woe_iv_engine.save_analysis",
            side_effect=lambda artifact: artifact,
        ):
            analysis = run_woe_iv(woe_request(), scope)
        payload = {
            "analysisId": analysis["analysisId"],
            "variable": "income",
            "bins": [
                {"binId": "low", "label": "Low", "lowerBound": 0, "upperBound": 80},
                {"binId": "high", "label": "High", "lowerBound": 80, "upperBound": 200},
            ],
            "allowNumericGaps": False,
        }
        with patch(
            "server.credit_risk.woe_iv_engine.get_analysis",
            return_value=analysis,
        ), patch(
            "server.credit_risk.woe_iv_engine.save_analysis",
            side_effect=lambda artifact: artifact,
        ):
            updated = apply_manual_bins(payload, scope)
        income = next(
            row for row in updated["variableSummaries"] if row["variable"] == "income"
        )
        self.assertEqual(sum(int(row["totalCount"]) for row in income["bins"]), 60)
        self.assertEqual(updated["population_count"], 60)
        self.assertTrue(updated["holdout_excluded"])

    def test_scorecard_and_ml_fit_and_rank_on_development_only(self) -> None:
        scope = fake_scope(rows=60)
        scorecard_payload = {
            **woe_request(),
            "selectedVariables": ["income", "utilization"],
            "trainRawBaseline": True,
            "crossValidationFolds": 5,
            "modelType": "Logistic Scorecard",
            "regularization": "l2",
            "regularizationC": 1.0,
            "pdo": 20,
            "baseScore": 600,
            "baseOdds": "50:1",
        }
        ml_payload = {
            **woe_request(),
            "selectedVariables": ["income", "utilization"],
            "modelType": "Logistic Regression Baseline",
        }
        with patch(
            "server.credit_risk.scorecard_engine.save_scorecard_model",
            side_effect=lambda artifact: artifact,
        ), patch(
            "server.credit_risk.ml_engine.save_ml_model",
            side_effect=lambda artifact: artifact,
        ):
            scorecard = train_scorecard(scorecard_payload, scope)
            ml_model = train_ml_model(ml_payload, scope)

        for artifact in (scorecard, ml_model):
            self.assertEqual(artifact["rowCount"] if "rowCount" in artifact else artifact["transformSummary"]["rows"], 60)
            self.assertEqual(artifact["analysis_scope"], "development_population")
            self.assertEqual(artifact["splitSource"], "governed_development_stratified_fold")
            self.assertTrue(artifact["holdout_excluded"])
            self.assertFalse(artifact["final_holdout_used_for_selection"])

    def test_scorecard_generated_code_requires_exact_development_positions(self) -> None:
        code = generate_scorecard_code(
            {
                **canonical_scope_fields(fake_scope()),
                "targetColumn": "bad_flag",
                "eventValue": 1,
                "selectedVariables": ["woe_income"],
            }
        )
        self.assertIn("woe_frame.iloc[list(DEVELOPMENT_POSITIONS)]", code["python"])
        self.assertNotIn("X = woe_train", code["python"])

    def test_artifact_scope_rejects_stale_and_conflicting_aliases(self) -> None:
        scope = fake_scope()
        artifact = {
            **canonical_scope_fields(scope),
            "projectId": "project-1",
            "datasetId": "dataset-1",
            "datasetVersionId": "version-1",
        }
        require_artifact_scope(artifact, scope, artifact_label="fixture")

        stale = {**artifact, "datasetVersionId": "stale-version"}
        with self.assertRaises(HTTPException) as stale_error:
            require_artifact_scope(stale, scope, artifact_label="fixture")
        self.assertEqual(stale_error.exception.status_code, 409)

        contradictory = {**artifact, "analysis_partition_id": "other-partition"}
        with self.assertRaises(HTTPException) as alias_error:
            require_artifact_scope(contradictory, scope, artifact_label="fixture")
        self.assertEqual(alias_error.exception.status_code, 409)
        self.assertIn("contradictory aliases", str(alias_error.exception.detail))

        for flag in (
            "final_holdout_accessed",
            "final_holdout_used_for_selection",
            "raw_dataset_target_fallback_used",
            "browser_target_semantics_used",
        ):
            with self.subTest(flag=flag), self.assertRaises(HTTPException):
                require_artifact_scope(
                    {**artifact, flag: True},
                    scope,
                    artifact_label="fixture",
                )

    def test_artifact_scope_requires_exact_target_contract_semantics(self) -> None:
        scope = fake_scope()
        artifact = {
            **canonical_scope_fields(scope),
            "projectId": "project-1",
            "datasetId": "dataset-1",
            "datasetVersionId": "version-1",
        }

        for field, stale_value in (
            ("targetColumn", "browser_target"),
            ("eventValue", 0),
            ("nonEventValue", 1),
            ("targetContractId", "stale-target-contract"),
        ):
            with self.subTest(field=field), self.assertRaises(HTTPException) as raised:
                require_artifact_scope(
                    {**artifact, field: stale_value},
                    scope,
                    artifact_label="fixture",
                )
            self.assertEqual(raised.exception.status_code, 409)

    def test_artifact_scope_payload_forwards_non_event_contradiction_check(self) -> None:
        payload = artifact_scope_payload(
            {
                **canonical_scope_fields(fake_scope()),
                "projectId": "project-1",
                "datasetId": "dataset-1",
                "datasetVersionId": "version-1",
            }
        )
        self.assertEqual(payload["targetColumn"], "bad_flag")
        self.assertEqual(payload["eventValue"], 1)
        self.assertEqual(payload["nonEventValue"], 0)

    def test_project_scoped_reads_fail_on_ambiguous_exact_artifacts(self) -> None:
        common = {
            "projectId": "project-1",
            "datasetId": "dataset-1",
            "datasetVersionId": "version-1",
            "analysis_partition_id": "analysis-partition-1",
            "analysis_partition_revision": 3,
            "analysis_scope": "development_population",
            "holdout_excluded": True,
        }
        with patch(
            "server.credit_risk.woe_iv_engine.load_registry",
            return_value=[
                {**common, "analysisId": "analysis-a"},
                {**common, "analysisId": "analysis-b"},
            ],
        ), self.assertRaises(HTTPException):
            get_project_analysis_exact(
                "project-1", "dataset-1", "version-1", "analysis-partition-1", 3
            )
        with patch(
            "server.credit_risk.scorecard_engine.load_registry",
            return_value=[
                {**common, "modelId": "scorecard-a"},
                {**common, "modelId": "scorecard-b"},
            ],
        ), self.assertRaises(HTTPException):
            get_project_scorecard_exact(
                "project-1", "dataset-1", "version-1", "analysis-partition-1", 3
            )
        with patch(
            "server.credit_risk.ml_engine._load_registry",
            return_value=[
                {**common, "modelId": "ml-a"},
                {**common, "modelId": "ml-b"},
            ],
        ), self.assertRaises(HTTPException):
            get_project_ml_model_exact(
                "project-1", "dataset-1", "version-1", "analysis-partition-1", 3
            )

    def test_credit_risk_sources_contain_no_latest_full_or_random_split_fallback(self) -> None:
        sources = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "server/credit_risk/woe_iv_engine.py",
                "server/credit_risk/scorecard_engine.py",
                "server/credit_risk/ml_engine.py",
                "server/credit_risk/credit_risk_router.py",
            )
        )
        self.assertNotIn("latest_version_id", sources)
        self.assertNotIn("data_full.csv", sources)
        self.assertNotIn("train_test_split", sources)
        self.assertNotIn("split_source = \"random\"", sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)

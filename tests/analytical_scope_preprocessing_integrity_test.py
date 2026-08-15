from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.population_contract import (
    build_population_contract,
    calculate_duplicate_contract,
    primary_scope_projection,
)
from server.core.dataset_store import DatasetStore
from server.preprocessing.preprocessing_contract import (
    FIT_SCOPE_DEVELOPMENT_PREVIEW,
    analytical_type,
    apply_missing_recipe,
    apply_outlier_recipe,
    fit_metadata,
    fit_missing_recipe,
    fit_outlier_recipe,
)


def _special_contract() -> dict:
    return {
        "preprocessing_contract_version": 2,
        "status": "confirmed",
        "special_value_review_id": "special-review-1",
        "revision": 1,
        "detection_fingerprint": "special-detection-1",
        "contract_hash": "special-contract-1",
        "features": {
            "continuous": {
                "values": [-7, -8, -9],
                "policy": "preserve_informative",
                "replacement_value": None,
                "overrides": [],
            },
            "missing_numeric": {
                "values": [-7, -8, -9],
                "policy": "preserve_informative",
                "replacement_value": None,
                "overrides": [],
            },
        },
    }


def _fit(rows: int, *, population_id: str = "development-1") -> dict:
    return fit_metadata(
        fit_scope=FIT_SCOPE_DEVELOPMENT_PREVIEW,
        population_id=population_id,
        population_count=rows,
        lineage={
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
            "analysis_partition_id": "partition-1",
            "analysis_partition_revision": 1,
        },
        actor="analyst-1",
        application_scope="development_preview",
        application_population_id=population_id,
        application_population_rows=rows,
        fitted_at="2026-08-11T12:00:00+00:00",
    )


class CanonicalPopulationAndDuplicateContractTest(unittest.TestCase):
    def test_predictor_only_store_projection_excludes_target_without_selection(self) -> None:
        store = DatasetStore()
        store.set_raw(pd.DataFrame({"feature": [1, 2], "target": [0, 1]}))
        store.set_target("target")
        projected = store.get_raw_active_df(include_target=False)
        self.assertEqual(list(projected.columns), ["feature"])

    def test_scope_and_row_count_are_inseparable(self) -> None:
        contract = build_population_contract(
            registered_rows=100,
            development_rows=80,
            holdout_rows=20,
            primary_scope="development_population",
            primary_purpose="target_directed_test",
            project_id="project-1",
            dataset_id="dataset-1",
            dataset_version_id="version-1",
            analysis_partition_id="partition-1",
            analysis_partition_revision=1,
        )
        projected = primary_scope_projection(contract)
        self.assertEqual(projected["scope"], "development_population")
        self.assertEqual(projected["row_count"], 80)
        self.assertEqual(projected["population_counts"]["registered_population_rows"], 100)
        self.assertEqual(projected["population_counts"]["sealed_final_holdout_rows"], 20)

        structural = build_population_contract(
            registered_rows=100,
            development_rows=80,
            holdout_rows=20,
            primary_scope="registered_structural_population",
            primary_purpose="predictor_structure_test",
            final_holdout_predictors_included_in_structural_profile=True,
        )
        structural_projection = primary_scope_projection(structural)
        self.assertEqual(structural_projection["row_count"], 100)
        self.assertFalse(
            structural_projection["holdout_truth"]["final_holdout_target_accessed"]
        )
        self.assertTrue(
            structural_projection["holdout_truth"]
            ["final_holdout_predictors_included_in_structural_profile"]
        )

    def test_duplicate_groups_participants_and_redundant_rows(self) -> None:
        frame = pd.DataFrame(
            {
                "feature": [10, 10, 20, 20, 20, 30, 40],
                "category": ["a", "a", "b", "b", "b", "c", "d"],
                "target": [1, 1, 0, 0, 0, 1, None],
            }
        )
        registered = calculate_duplicate_contract(
            frame,
            scope="registered_population",
            comparison_columns=["feature", "category", "target"],
            target_column="target",
            target_included=True,
            writable_authority=False,
            purpose="registered_test",
        )
        self.assertEqual(registered["duplicate_group_count"], 2)
        self.assertEqual(registered["duplicate_participant_rows"], 5)
        self.assertEqual(registered["redundant_duplicate_rows"], 3)
        self.assertEqual(registered["unique_rows_after_deduplication"], 4)
        self.assertEqual(registered["redundant_duplicate_valid_target_rows"], 3)
        self.assertEqual(registered["redundant_duplicate_missing_target_rows"], 0)
        self.assertEqual(registered["keep_semantics"], "first")

        development = calculate_duplicate_contract(
            frame.iloc[:5],
            scope="development_population",
            comparison_columns=["feature", "category", "target"],
            target_column="target",
            target_included=True,
            writable_authority=True,
            purpose="eda_completion_decision",
        )
        self.assertEqual(development["row_count"], 5)
        self.assertNotEqual(registered["row_count"], development["row_count"])


class LeakageSafePreprocessingContractTest(unittest.TestCase):
    def test_outlier_fit_is_invariant_to_holdout_poisoning_and_preserves_specials(self) -> None:
        development = pd.DataFrame(
            {
                "continuous": [1.0, 2.0, 3.0, 4.0, 100.0, -7.0, -8.0, -9.0, None],
                "binary": [False, True, False, True, False, True, False, True, False],
            }
        )
        policy = {
            "global_method": "IQR_1_5",
            "config": {"continuous": "USE_GLOBAL", "binary": "USE_GLOBAL"},
            "analytical_types": {
                "continuous": {
                    "analytical_type": "continuous",
                    "source": "data_dictionary",
                    "reason": "Governed continuous bureau measurement.",
                    "authoritative_support": "dictionary-field-continuous",
                }
            },
            "rationales": {},
        }
        recipe = fit_outlier_recipe(
            development,
            policy=policy,
            fit=_fit(len(development)),
            special_value_contract=_special_contract(),
        )
        continuous = next(
            row for row in recipe["treatments"] if row["feature"] == "continuous"
        )
        binary = next(row for row in recipe["treatments"] if row["feature"] == "binary")
        self.assertEqual(continuous["fit_special_excluded_count"], 3)
        self.assertEqual(continuous["fit_null_excluded_count"], 1)
        self.assertEqual(binary["applied_method"], "NONE")

        poisoned_holdout = pd.DataFrame(
            {"continuous": [10**12, -(10**12), -7.0], "binary": [True, False, True]}
        )
        transformed, audit = apply_outlier_recipe(
            poisoned_holdout,
            recipe=recipe,
            special_value_contract=_special_contract(),
        )
        self.assertEqual(transformed.loc[2, "continuous"], -7.0)
        self.assertGreaterEqual(audit["counts"]["flagged_cell_count"], 2)
        self.assertEqual(audit["counts"]["affected_row_count"], 2)
        self.assertEqual(
            audit["counts"]["maximum_flagged_features_on_one_row"], 1
        )
        self.assertFalse(recipe.get("final_holdout_parameter_influence", False))

        changed_holdout = poisoned_holdout.copy()
        changed_holdout["continuous"] = [10**20, -(10**20), -7.0]
        recipe_again = fit_outlier_recipe(
            development,
            policy=copy.deepcopy(policy),
            fit=_fit(len(development)),
            special_value_contract=_special_contract(),
        )
        self.assertEqual(recipe["recipe_hash"], recipe_again["recipe_hash"])
        self.assertFalse(changed_holdout.equals(poisoned_holdout))

    def test_missing_fit_uses_ordinary_values_and_only_fills_true_nulls(self) -> None:
        development = pd.DataFrame(
            {"missing_numeric": [1.0, 2.0, 100.0, -7.0, -8.0, -9.0, None]}
        )
        policy = {
            "active_treatment": "FEATURE_SPECIFIC",
            "config": {"missing_numeric": {"strategy": "Median"}},
            "analytical_types": {},
        }
        recipe = fit_missing_recipe(
            development,
            policy=policy,
            fit=_fit(len(development)),
            special_value_contract=_special_contract(),
        )
        treatment = recipe["treatments"][0]
        self.assertEqual(treatment["fit_special_excluded_count"], 3)
        self.assertEqual(treatment["fitted_value"], {"kind": "number", "value": 2.0})
        transformed, audit = apply_missing_recipe(
            development,
            recipe=recipe,
            special_value_contract=_special_contract(),
        )
        self.assertEqual(transformed.iloc[-1, 0], 2.0)
        self.assertEqual(transformed.iloc[3:6, 0].tolist(), [-7.0, -8.0, -9.0])
        self.assertEqual(audit["counts"]["flagged_cell_count"], 1)
        self.assertEqual(audit["counts"]["affected_row_count"], 1)

    def test_zero_nulls_do_not_fit_an_inactive_contingency_estimator(self) -> None:
        frame = pd.DataFrame({"missing_numeric": [1.0, 2.0, -7.0, -8.0, -9.0]})
        recipe = fit_missing_recipe(
            frame,
            policy={
                "active_treatment": "NONE",
                "config": {
                    "missing_numeric": {
                        "strategy": "Median",
                        "status": "inactive_contingency",
                    }
                },
            },
            fit=_fit(len(frame)),
            special_value_contract=_special_contract(),
        )
        self.assertEqual(recipe["treatments"], [])

    def test_numeric_storage_defaults_to_none_without_semantic_authority(self) -> None:
        profile = analytical_type(pd.Series([1, 2, 3, 4], dtype="int64"))
        self.assertEqual(profile["analytical_type"], "unknown_review_required")
        self.assertFalse(profile["outlier_eligible"])
        self.assertEqual(profile["safe_default_method"], "NONE")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import pandas as pd

from server.preprocessing.preprocessing_contract import (
    FIT_SCOPE_DEVELOPMENT_PREVIEW,
    PREPROCESSING_CONTRACT_VERSION,
    analytical_type,
    apply_missing_recipe,
    apply_outlier_recipe,
    build_preprocessing_policy_record,
    duplicate_exclusion_blockers,
    fit_metadata,
    fit_missing_recipe,
    fit_outlier_recipe,
)


def _fit(rows: int) -> dict:
    result = fit_metadata(
        fit_scope=FIT_SCOPE_DEVELOPMENT_PREVIEW,
        population_id="development-1",
        population_count=rows,
        actor="contract-test",
        application_scope="development_population_preview",
        application_population_id="development-1",
        application_population_rows=rows,
    )
    assert result["fit_population_rows"] == rows
    return result


class PreprocessingV2RecipeContractTest(unittest.TestCase):
    def test_numeric_storage_defaults_to_none_without_semantic_authority(self):
        profile = analytical_type(pd.Series([1.0, 2.0, 3.0]))
        self.assertEqual(profile["analytical_type"], "unknown_review_required")
        self.assertFalse(profile["outlier_eligible"])
        self.assertEqual(profile["safe_default_method"], "NONE")

        governed = analytical_type(
            pd.Series([1.0, 2.0, 3.0]),
            {
                "analytical_type": "numeric_continuous",
                "source": "analyst_override",
                "authoritative_support": "confirmed continuous semantics",
                "reason": "Reviewed against the provider definition.",
            },
        )
        self.assertTrue(governed["outlier_eligible"])
        self.assertEqual(governed["safe_default_method"], "IQR_1_5")

    def test_percentile_fit_uses_development_ordinary_values_only(self):
        frame = pd.DataFrame(
            {"score": pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, -7.0])}
        )
        recipe = fit_outlier_recipe(
            frame,
            policy={
                "global_method": "NONE",
                "config": {"score": "PCT_01_99"},
                "rationales": {"score": "Continuous provider score."},
                "analytical_types": {
                    "score": {
                        "analytical_type": "numeric_continuous",
                        "source": "data_dictionary",
                        "authoritative_support": "provider score definition",
                        "reason": "Continuous provider score.",
                    }
                },
            },
            fit=_fit(len(frame)),
        )
        treatment = recipe["treatments"][0]
        ordinary = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0])
        self.assertAlmostEqual(
            treatment["lower_threshold"], float(ordinary.quantile(0.01))
        )
        self.assertAlmostEqual(
            treatment["upper_threshold"], float(ordinary.quantile(0.99))
        )
        transformed, audit = apply_outlier_recipe(frame, recipe=recipe)
        self.assertEqual(float(transformed.loc[5, "score"]), -7.0)
        self.assertEqual(audit["counts"]["flagged_cell_count"], 2)
        self.assertEqual(audit["counts"]["affected_row_count"], 2)
        self.assertEqual(
            audit["counts"]["maximum_flagged_features_on_one_row"], 1
        )

    def test_authoritative_bounded_rate_intersects_statistical_thresholds(self):
        frame = pd.DataFrame({"rate": [-20.0, 0.1, 0.2, 0.8, 1.4]})
        recipe = fit_outlier_recipe(
            frame,
            policy={
                "global_method": "IQR_1_5",
                "config": {"rate": "USE_GLOBAL"},
                "rationales": {},
                "analytical_types": {
                    "rate": {
                        "analytical_type": "bounded_rate",
                        "source": "data_dictionary",
                        "authoritative_support": "Contract rate in [0, 1]",
                        "business_min": 0.0,
                        "business_max": 1.0,
                    }
                },
            },
            fit=_fit(len(frame)),
        )
        treatment = recipe["treatments"][0]
        self.assertTrue(treatment["business_bounds_enforced"])
        self.assertGreaterEqual(treatment["lower_threshold"], 0.0)
        self.assertLessEqual(treatment["upper_threshold"], 1.0)
        transformed, _ = apply_outlier_recipe(frame, recipe=recipe)
        self.assertEqual(float(transformed.loc[0, "rate"]), 0.0)
        self.assertEqual(float(transformed.loc[4, "rate"]), 1.0)

    def test_global_iqr_respects_the_complete_analytical_type_eligibility_matrix(self):
        frame = pd.DataFrame(
            {
                "continuous": [1.0, 2.0, 3.0, 4.0, 100.0],
                "count": [0, 1, 2, 3, 100],
                "ordinal": [1, 2, 3, 4, 5],
                "low_cardinality_integer": [1, 1, 2, 2, 3],
                "bounded_percentage": [-10.0, 10.0, 50.0, 90.0, 110.0],
                "identifier": [1001, 1002, 1003, 1004, 999999],
                "binary": pd.Series([False, True, False, True, False], dtype="bool"),
                "constant": [7, 7, 7, 7, 7],
                "bureau_special_coded": [-9.0, -8.0, -7.0, 10.0, 1000.0],
            }
        )
        authoritative = {
            name: {
                "analytical_type": kind,
                "source": "data_dictionary",
                "authoritative_support": f"dictionary-{name}",
                "reason": f"Governed {kind} semantics.",
                **(
                    {"business_min": 0.0, "business_max": 100.0}
                    if kind == "bounded_percentage"
                    else {}
                ),
            }
            for name, kind in {
                "continuous": "numeric_continuous",
                "count": "count",
                "ordinal": "ordinal",
                "bounded_percentage": "bounded_percentage",
                "identifier": "identifier",
                "constant": "constant",
                "bureau_special_coded": "bureau_special_coded_numeric",
            }.items()
        }
        special_contract = {
            "contract_hash": "special-contract-matrix",
            "features": {
                "bureau_special_coded": {
                    "values": [-7, -8, -9],
                    "policy": "preserve_informative",
                }
            },
        }
        recipe = fit_outlier_recipe(
            frame,
            policy={
                "global_method": "IQR_1_5",
                "config": {feature: "USE_GLOBAL" for feature in frame.columns},
                "analytical_types": authoritative,
                "rationales": {},
            },
            fit=_fit(len(frame)),
            special_value_contract=special_contract,
        )
        by_feature = {row["feature"]: row for row in recipe["treatments"]}
        self.assertEqual(by_feature["continuous"]["applied_method"], "IQR_1_5")
        self.assertEqual(
            by_feature["bounded_percentage"]["applied_method"], "IQR_1_5"
        )
        self.assertTrue(
            by_feature["bounded_percentage"]["business_bounds_enforced"]
        )
        for feature in (
            "count",
            "ordinal",
            "low_cardinality_integer",
            "identifier",
            "binary",
            "constant",
            "bureau_special_coded",
        ):
            self.assertEqual(by_feature[feature]["applied_method"], "NONE")
            self.assertFalse(by_feature[feature]["outlier_eligible"])
        self.assertEqual(
            by_feature["low_cardinality_integer"]["analytical_type"],
            "unknown_review_required",
        )
        self.assertEqual(
            by_feature["bureau_special_coded"]["fit_special_excluded_count"], 3
        )
        transformed, _ = apply_outlier_recipe(
            frame,
            recipe=recipe,
            special_value_contract=special_contract,
        )
        self.assertEqual(
            transformed["bureau_special_coded"].iloc[:3].tolist(),
            [-9.0, -8.0, -7.0],
        )

    def test_semantic_override_requires_authoritative_support_and_rationale(self):
        frame = pd.DataFrame({"reviewed_integer": [1, 2, 3, 4, 100]})
        base_policy = {
            "global_method": "NONE",
            "config": {"reviewed_integer": "IQR_1_5"},
            "analytical_types": {
                "reviewed_integer": {
                    "analytical_type": "numeric_continuous",
                    "source": "analyst_override",
                    "authoritative_support": "reviewed provider definition",
                    "reason": "Provider documentation establishes a continuous measure.",
                }
            },
            "rationales": {},
        }
        with self.assertRaisesRegex(ValueError, "requires analyst rationale"):
            fit_outlier_recipe(frame, policy=base_policy, fit=_fit(len(frame)))
        base_policy["rationales"] = {
            "reviewed_integer": "Confirmed continuous semantics against provider documentation."
        }
        recipe = fit_outlier_recipe(
            frame,
            policy=base_policy,
            fit=_fit(len(frame)),
        )
        self.assertEqual(recipe["treatments"][0]["applied_method"], "IQR_1_5")

    def test_missing_recipe_fills_only_governed_true_nulls(self):
        frame = pd.DataFrame(
            {"code": pd.Series(["1", None, -7, "bad", "missing"], dtype="object")}
        )
        policy = {
            "config": {
                "code": {"strategy": "Constant", "constantValue": "FILL"}
            },
            "missing_tokens": {"code": ["missing", "-7"]},
        }
        recipe = fit_missing_recipe(frame, policy=policy, fit=_fit(len(frame)))
        transformed, audit = apply_missing_recipe(frame, recipe=recipe)
        self.assertEqual(transformed.loc[1, "code"], "FILL")
        self.assertEqual(transformed.loc[4, "code"], "FILL")
        self.assertEqual(transformed.loc[2, "code"], -7)
        self.assertEqual(transformed.loc[3, "code"], "bad")
        self.assertEqual(audit["counts"]["flagged_cell_count"], 2)
        self.assertEqual(audit["counts"]["affected_row_count"], 2)

    def test_zero_null_contingency_does_not_create_an_estimator(self):
        frame = pd.DataFrame({"score": [1.0, 2.0, 3.0]})
        recipe = fit_missing_recipe(
            frame,
            policy={"config": {"score": {"strategy": "Median"}}},
            fit=_fit(len(frame)),
        )
        self.assertEqual(recipe["treatments"], [])

    def test_active_none_missing_policy_rejects_true_nulls(self):
        with self.assertRaisesRegex(ValueError, "active NONE"):
            fit_missing_recipe(
                pd.DataFrame({"score": [1.0, None]}),
                policy={"active_treatment": "NONE", "config": {}},
                fit=_fit(2),
            )

    def test_combined_policy_is_executable_only_after_both_stage_approvals(self):
        lineage = {
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
            "analysis_partition_id": "partition-1",
            "analysis_partition_revision": 1,
            "predictor_authorization_id": "authorization-1",
        }
        outlier = {
            "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
            "artifact_kind": "approved_outlier_policy",
            "status": "approved",
            "outlier_policy_id": "op-1",
            "outlier_policy_revision": 1,
        }
        partial = build_preprocessing_policy_record(
            lineage=lineage,
            special_value_contract={},
            actor="contract-test",
            outlier_policy=outlier,
            missing_policy=None,
            outlier_development_preview_fit=None,
            missing_development_preview_fit=None,
        )
        self.assertFalse(partial["executable"])
        self.assertEqual(partial["status"], "incomplete_missing_policy")

        missing = {
            "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
            "artifact_kind": "approved_missing_policy",
            "status": "approved",
            "missing_policy_id": "mp-1",
            "missing_policy_revision": 1,
            "active_treatment": "NONE",
            "zero_null_validated": True,
            "true_null_cell_count": 0,
            "materialization_required": False,
            "processed_frame_created": False,
        }
        complete = build_preprocessing_policy_record(
            lineage=lineage,
            special_value_contract={},
            actor="contract-test",
            outlier_policy=outlier,
            missing_policy=missing,
            outlier_development_preview_fit=None,
            missing_development_preview_fit=None,
            previous=partial,
        )
        self.assertTrue(complete["executable"])
        self.assertEqual(complete["status"], "approved")

    def test_duplicate_exclusion_requires_a_revised_registered_population(self):
        blockers = duplicate_exclusion_blockers(
            {"duplicate_decision": "Exclude exact duplicates"},
            executable_duplicate_recipe={"status": "approved"},
        )
        self.assertEqual(len(blockers), 1)
        self.assertEqual(
            blockers[0]["code"],
            "approved_duplicate_exclusion_requires_population_revision",
        )


if __name__ == "__main__":
    unittest.main()

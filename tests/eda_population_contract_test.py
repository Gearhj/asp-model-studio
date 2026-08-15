from __future__ import annotations

import pandas as pd

from server.core.population_contract import (
    build_eda_completion_contract,
    build_population_contract,
    calculate_duplicate_contract,
    primary_scope_projection,
)


def test_duplicate_contract_distinguishes_groups_participants_and_redundancy() -> None:
    frame = pd.DataFrame(
        {
            "x": [1, 1, 1, 2, 3, 3],
            "target": [0, 0, 0, 1, None, None],
        }
    )

    contract = calculate_duplicate_contract(
        frame,
        scope="development_population",
        target_column="target",
        target_included=True,
        writable_authority=True,
        purpose="test",
    )

    assert contract["duplicate_group_count"] == 2
    assert contract["duplicate_participant_rows"] == 5
    assert contract["redundant_duplicate_rows"] == 3
    assert contract["duplicate_rows"] == 3
    assert contract["unique_rows_after_deduplication"] == 3
    assert contract["duplicate_participant_valid_target_rows"] == 3
    assert contract["duplicate_participant_missing_target_rows"] == 2
    assert contract["redundant_duplicate_valid_target_rows"] == 2
    assert contract["redundant_duplicate_missing_target_rows"] == 1
    assert contract["target_count_unit"] == "redundant_duplicate_rows"
    assert contract["keep_semantics"] == "first"


def test_population_and_completion_contract_bind_scope_counts_and_authority() -> None:
    registered = calculate_duplicate_contract(
        pd.DataFrame({"x": [1, 1, 2, 3]}),
        scope="registered_structural_population",
        target_column=None,
        target_included=False,
        writable_authority=False,
        purpose="test_registered",
    )
    development = calculate_duplicate_contract(
        pd.DataFrame({"x": [1, 1, 2], "target": [0, 0, 1]}),
        scope="development_population",
        target_column="target",
        target_included=True,
        writable_authority=True,
        purpose="test_development",
    )
    contract = build_population_contract(
        registered_rows=4,
        development_rows=3,
        holdout_rows=1,
        primary_scope="development_population",
        primary_purpose="test",
        project_id="project-a",
        dataset_id="dataset-a",
        dataset_version_id="version-a",
        target="target",
        target_contract_id="target-contract-a",
        predictor_authorization_id="predictor-auth-a",
        analysis_partition_id="partition-a",
        analysis_partition_revision=2,
        analysis_population_id="development-a",
        population_policy_id="policy-a",
        treatment_policy_id="non_mutating",
        analysis_rows=3,
        fit_rows=3,
        application_rows=None,
        materialization_rows=None,
        registered_duplicate_contract=registered,
        development_duplicate_contract=development,
        descriptive_scope="registered_structural_population",
        analysis_scope="development_population",
        target_scope="development_population",
        fit_scope="development_population",
        application_scope="not_applicable",
        materialization_scope="not_applicable",
        render_scope="development_aggregate",
        registered_structural_predictors_accessed=True,
        final_holdout_predictors_included_in_structural_profile=True,
        final_holdout_target_accessed=False,
        final_holdout_parameter_influence=False,
        final_holdout_used_for_selection=False,
        final_holdout_transformed_or_materialized_prelock=False,
        final_holdout_opened_for_final_reporting=False,
    )

    projection = primary_scope_projection(contract)
    assert projection["scope"] == "development_population"
    assert projection["row_count"] == 3
    assert contract["counts"] == {
        "registered_rows": 4,
        "development_rows": 3,
        "holdout_rows": 1,
        "analysis_rows": 3,
        "fit_rows": 3,
        "application_rows": None,
        "materialization_rows": None,
        "rendered_rows": None,
        "reconciled": True,
        "registered_population_rows": 4,
        "development_population_rows": 3,
        "sealed_final_holdout_rows": 1,
        "analysis_population_rows": 3,
        "fit_population_rows": 3,
        "application_population_rows": None,
        "rendered_sample_rows": None,
    }
    for field in (
        "final_holdout_target_accessed",
        "final_holdout_parameter_influence",
        "final_holdout_used_for_selection",
        "final_holdout_transformed_or_materialized_prelock",
        "final_holdout_opened_for_final_reporting",
    ):
        assert contract["holdout_truth"][field] is False

    completion = build_eda_completion_contract(contract)
    assert completion["population_contract_id"] == contract["contract_id"]
    assert completion["duplicate_authority"]["writable_source"] == (
        "governed_parent_finding"
    )
    assert completion["duplicate_authority"]["duplicate_rows"] == 1
    assert completion["exclude_upstream_and_repartition"] == {
        "allowed_in_current_confirmation": False,
        "requires_registered_population_revision": True,
        "requires_analysis_partition_revision": True,
        "current_analysis_partition_id": "partition-a",
        "current_analysis_partition_revision": 2,
    }


def test_legacy_duplicate_count_fallback_does_not_invent_group_lineage() -> None:
    contract = build_population_contract(
        registered_rows=10,
        development_rows=8,
        holdout_rows=2,
        primary_scope="development_population",
        primary_purpose="legacy_compatibility_test",
        target="target",
        registered_predictor_duplicate_rows=2,
        development_analysis_duplicate_rows=1,
    )

    registered = contract["duplicates"]["registered_predictor_frame"]
    development = contract["duplicates"]["development_analysis_frame"]
    for duplicate_scope, expected_redundant in ((registered, 2), (development, 1)):
        assert duplicate_scope["duplicate_rows"] == expected_redundant
        assert duplicate_scope["redundant_duplicate_rows"] == expected_redundant
        assert duplicate_scope["duplicate_group_count"] is None
        assert duplicate_scope["duplicate_participant_rows"] is None
        assert duplicate_scope["comparison_columns"] is None
        assert duplicate_scope["writable_authority"] is False
        assert duplicate_scope["verified"] is False
        assert duplicate_scope["calculation_status"] == (
            "unverified_legacy_redundant_count_only"
        )


def test_missing_legacy_duplicate_counts_remain_unknown() -> None:
    contract = build_population_contract(
        registered_rows=10,
        development_rows=8,
        holdout_rows=2,
        primary_scope="development_population",
        primary_purpose="unknown_legacy_count_test",
    )

    assert contract["duplicates"]["registered_predictor_frame"] is None
    assert contract["duplicates"]["development_analysis_frame"] is None

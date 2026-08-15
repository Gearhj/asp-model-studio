"""Shared keys for dataset-bound workflow state.

This module deliberately has no imports from DatasetStore or the Dataset
Library.  Both layers can therefore use the same invalidation contract without
creating the ``dataset_store -> dataset_identity -> dataset_store`` cycle that
would result from defining these keys in either implementation module.
"""
from __future__ import annotations


PRETRAINING_STATE_KEYS = (
    # Data-quality and governed preparation state.
    "bureau_review",
    "predictor_authorization",
    "target_source_excluded",
    "target_source_exclusions",
    "prohibited_columns",
    "system_columns",
    "split_columns",
    "processed_stage",
    "outlier_policy",
    "outlier_application",
    "missing_policy",
    "missing_application",
    "missing_config",
    "missing_validation",
    "preprocessing_policy",
    "preprocessing_state_status",
    "preprocessing_state_reason",
    # Feature-contract state.
    "materialized_feature_names",
    "feature_manifest",
    "feature_preview",
    "selected_columns",
    # Validation-design and training state.
    "split_record",
    "split_config",
    "split_status",
    "validation_design",
    "target_prevalence",
    "training_execution",
    "training_model_portfolio",
    "training_preflight",
    "model_selection_decision",
    "active_training_job_id",
)

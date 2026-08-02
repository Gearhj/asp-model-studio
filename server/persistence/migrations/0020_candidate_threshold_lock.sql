-- Freeze the numeric candidate threshold independently from the ranking
-- metric and preserve its own pre-exposure lock timestamp.
ALTER TABLE candidate_selection_decisions
  ADD COLUMN locked_threshold REAL;

ALTER TABLE candidate_selection_decisions
  ADD COLUMN threshold_locked_at TEXT;

ALTER TABLE candidate_selection_decisions
  ADD COLUMN selected_candidate_contract_hash TEXT;

ALTER TABLE candidate_selection_decisions
  ADD COLUMN final_holdout_partition_id TEXT;

ALTER TABLE candidate_selection_decisions
  ADD COLUMN selection_metric_created_at TEXT;

ALTER TABLE candidate_selection_decisions
  ADD COLUMN threshold_policy_hash TEXT;

ALTER TABLE holdout_exposures
  ADD COLUMN feature_manifest_id TEXT;

ALTER TABLE holdout_exposures
  ADD COLUMN feature_manifest_hash TEXT;

ALTER TABLE holdout_exposures
  ADD COLUMN treatment_manifest_id TEXT;

ALTER TABLE holdout_exposures
  ADD COLUMN treatment_manifest_hash TEXT;

ALTER TABLE holdout_exposures
  ADD COLUMN materialization_id TEXT;

ALTER TABLE evaluation_packages
  ADD COLUMN selected_candidate_contract_hash TEXT;

ALTER TABLE evaluation_packages
  ADD COLUMN selection_metric_created_at TEXT;

ALTER TABLE evaluation_packages
  ADD COLUMN out_of_fold_prediction_artifact_id TEXT;

ALTER TABLE evaluation_packages
  ADD COLUMN locked_threshold REAL;

ALTER TABLE evaluation_packages
  ADD COLUMN threshold_source TEXT;

ALTER TABLE evaluation_packages
  ADD COLUMN threshold_policy_hash TEXT;

ALTER TABLE model_versions
  ADD COLUMN locked_threshold REAL;

ALTER TABLE model_versions
  ADD COLUMN threshold_source TEXT;

ALTER TABLE model_versions
  ADD COLUMN threshold_policy_hash TEXT;

ALTER TABLE model_versions
  ADD COLUMN selected_candidate_contract_hash TEXT;

ALTER TABLE model_versions
  ADD COLUMN selection_metric_created_at TEXT;

ALTER TABLE model_versions
  ADD COLUMN out_of_fold_prediction_artifact_id TEXT;

ALTER TABLE model_versions
  ADD COLUMN evaluation_package_content_hash TEXT;

-- Backend-authoritative preview, sufficiency, and documentation lineage for
-- the durable pre-EDA Analysis Partition.

ALTER TABLE analysis_partitions ADD COLUMN problem_type TEXT NOT NULL DEFAULT 'classification';
ALTER TABLE analysis_partitions ADD COLUMN partition_method TEXT NOT NULL DEFAULT 'deterministic_random';
ALTER TABLE analysis_partitions ADD COLUMN selection_rationale TEXT NOT NULL DEFAULT '';
ALTER TABLE analysis_partitions ADD COLUMN preview_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE analysis_partitions ADD COLUMN sufficiency_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE analysis_partitions ADD COLUMN evidence_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE analysis_partitions ADD COLUMN evidence_ref TEXT;
ALTER TABLE analysis_partitions ADD COLUMN mdd_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE analysis_partitions ADD COLUMN mdd_ref TEXT;

-- The decision contract remains immutable. Evidence and MDD linkage are
-- intentionally excluded so their pending -> recorded transitions can be
-- completed idempotently after the partition transaction succeeds.
DROP TRIGGER IF EXISTS trg_analysis_partitions_immutable_contract;
CREATE TRIGGER trg_analysis_partitions_immutable_contract
BEFORE UPDATE ON analysis_partitions
WHEN
  NEW.analysis_partition_id IS NOT OLD.analysis_partition_id OR
  NEW.project_id IS NOT OLD.project_id OR
  NEW.dataset_id IS NOT OLD.dataset_id OR
  NEW.dataset_version_id IS NOT OLD.dataset_version_id OR
  NEW.target_contract_id IS NOT OLD.target_contract_id OR
  NEW.target_column IS NOT OLD.target_column OR
  NEW.positive_value_json IS NOT OLD.positive_value_json OR
  NEW.negative_value_json IS NOT OLD.negative_value_json OR
  NEW.predictor_authorization_id IS NOT OLD.predictor_authorization_id OR
  NEW.problem_type IS NOT OLD.problem_type OR
  NEW.partition_method IS NOT OLD.partition_method OR
  NEW.selection_rationale IS NOT OLD.selection_rationale OR
  NEW.preview_fingerprint IS NOT OLD.preview_fingerprint OR
  NEW.sufficiency_json IS NOT OLD.sufficiency_json OR
  NEW.development_partition_id IS NOT OLD.development_partition_id OR
  NEW.sealed_holdout_partition_id IS NOT OLD.sealed_holdout_partition_id OR
  NEW.development_share IS NOT OLD.development_share OR
  NEW.holdout_share IS NOT OLD.holdout_share OR
  NEW.random_seed IS NOT OLD.random_seed OR
  NEW.stratification_policy IS NOT OLD.stratification_policy OR
  NEW.stratification_field IS NOT OLD.stratification_field OR
  NEW.population_count IS NOT OLD.population_count OR
  NEW.development_count IS NOT OLD.development_count OR
  NEW.holdout_count IS NOT OLD.holdout_count OR
  NEW.event_counts_json IS NOT OLD.event_counts_json OR
  NEW.row_assignments_json IS NOT OLD.row_assignments_json OR
  NEW.assignment_hash IS NOT OLD.assignment_hash OR
  NEW.population_fingerprint IS NOT OLD.population_fingerprint OR
  NEW.artifact_hash IS NOT OLD.artifact_hash OR
  NEW.revision IS NOT OLD.revision OR
  NEW.final_holdout_status IS NOT OLD.final_holdout_status OR
  NEW.holdout_isolation_status IS NOT OLD.holdout_isolation_status OR
  NEW.created_by IS NOT OLD.created_by OR
  NEW.created_at IS NOT OLD.created_at OR
  NEW.sealed_at IS NOT OLD.sealed_at
BEGIN
  SELECT RAISE(ABORT, 'analysis partition contract is immutable');
END;

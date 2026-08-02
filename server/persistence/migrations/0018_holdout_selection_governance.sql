-- ATLAS P0: durable candidate-selection and final-holdout governance.
--
-- This migration is deliberately additive. Existing model versions predate
-- selection-provenance and holdout-exposure enforcement, so they remain
-- durable but are fail-closed as legacy-unresolved until explicitly reviewed.

CREATE TABLE IF NOT EXISTS candidate_selection_decisions (
  candidate_decision_id TEXT PRIMARY KEY,
  decision_status TEXT NOT NULL DEFAULT 'locked'
    CHECK (decision_status IN ('locked', 'legacy_proposal')),
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  feature_manifest_id TEXT NOT NULL,
  feature_manifest_hash TEXT,
  treatment_manifest_id TEXT,
  treatment_manifest_hash TEXT,
  materialization_id TEXT,
  validation_design_id TEXT NOT NULL,
  validation_design_version_id TEXT NOT NULL,
  split_id TEXT NOT NULL,
  training_job_id TEXT NOT NULL,
  training_run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  selection_metric_name TEXT NOT NULL,
  selection_metric_value REAL NOT NULL,
  selection_metric_source TEXT NOT NULL,
  selection_partition_id TEXT NOT NULL,
  fold_definition_id TEXT,
  fold_count INTEGER,
  fold_values_json TEXT NOT NULL DEFAULT '[]',
  selection_metric_mean REAL,
  selection_metric_std REAL,
  out_of_fold_prediction_artifact_id TEXT,
  threshold_source TEXT NOT NULL,
  calibration_source TEXT NOT NULL,
  ranking_snapshot_json TEXT NOT NULL DEFAULT '[]',
  ranking_snapshot_hash TEXT NOT NULL,
  selection_rationale TEXT,
  selection_locked_at TEXT,
  actor TEXT,
  selection_integrity_status TEXT NOT NULL DEFAULT 'legacy_unresolved'
    CHECK (
      selection_integrity_status IN (
        'legacy_unresolved',
        'verified',
        'invalid_final_holdout_ranking',
        'invalid_selection_provenance',
        'invalid_holdout_isolation'
      )
    ),
  selection_integrity_reason TEXT,
  holdout_isolation_status TEXT NOT NULL DEFAULT 'legacy_unresolved'
    CHECK (holdout_isolation_status IN ('legacy_unresolved', 'verified', 'invalid')),
  holdout_isolation_reason TEXT,
  integrity_classified_at TEXT,
  integrity_classified_by TEXT,
  decision_contract_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  UNIQUE(project_id, dataset_version_id, validation_design_version_id, split_id, training_run_id),
  UNIQUE(project_id, training_run_id, candidate_id),
  CHECK (decision_status <> 'locked' OR (selection_locked_at IS NOT NULL AND actor IS NOT NULL)),
  CHECK (
    selection_metric_source <> 'final_holdout'
    OR selection_integrity_status = 'invalid_final_holdout_ranking'
  ),
  CHECK (
    selection_integrity_status <> 'verified'
    OR holdout_isolation_status = 'verified'
  ),
  CHECK (
    (selection_integrity_status = 'legacy_unresolved' AND holdout_isolation_status = 'legacy_unresolved')
    OR (
      selection_integrity_status <> 'legacy_unresolved'
      AND holdout_isolation_status <> 'legacy_unresolved'
      AND selection_integrity_reason IS NOT NULL
      AND holdout_isolation_reason IS NOT NULL
      AND integrity_classified_at IS NOT NULL
      AND integrity_classified_by IS NOT NULL
    )
  )
);

CREATE INDEX IF NOT EXISTS idx_candidate_selection_decisions_exact
  ON candidate_selection_decisions(
    project_id, dataset_id, dataset_version_id, training_run_id, candidate_id
  );

CREATE INDEX IF NOT EXISTS idx_candidate_selection_decisions_integrity
  ON candidate_selection_decisions(
    project_id, selection_integrity_status, holdout_isolation_status
  );

CREATE TRIGGER IF NOT EXISTS trg_candidate_selection_decisions_immutable
BEFORE UPDATE OF
  candidate_decision_id, decision_status, project_id, dataset_id,
  dataset_version_id, feature_manifest_id, feature_manifest_hash,
  treatment_manifest_id, treatment_manifest_hash, materialization_id,
  validation_design_id, validation_design_version_id, split_id,
  training_job_id, training_run_id, candidate_id, selection_metric_name,
  selection_metric_value, selection_metric_source, selection_partition_id,
  fold_definition_id, fold_count, fold_values_json, selection_metric_mean,
  selection_metric_std, out_of_fold_prediction_artifact_id,
  threshold_source, calibration_source, ranking_snapshot_json,
  ranking_snapshot_hash, selection_rationale, selection_locked_at, actor,
  decision_contract_hash, created_at
ON candidate_selection_decisions
BEGIN
  SELECT RAISE(ABORT, 'candidate selection decision contract is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_candidate_selection_decisions_no_delete
BEFORE DELETE ON candidate_selection_decisions
BEGIN
  SELECT RAISE(ABORT, 'candidate selection decisions are durable governance records');
END;

CREATE TRIGGER IF NOT EXISTS trg_candidate_selection_decisions_integrity_transition
BEFORE UPDATE OF
  selection_integrity_status, selection_integrity_reason,
  holdout_isolation_status, holdout_isolation_reason,
  integrity_classified_at, integrity_classified_by
ON candidate_selection_decisions
WHEN NOT (
  (
    NEW.selection_integrity_status IS OLD.selection_integrity_status
    AND NEW.selection_integrity_reason IS OLD.selection_integrity_reason
    AND NEW.holdout_isolation_status IS OLD.holdout_isolation_status
    AND NEW.holdout_isolation_reason IS OLD.holdout_isolation_reason
    AND NEW.integrity_classified_at IS OLD.integrity_classified_at
    AND NEW.integrity_classified_by IS OLD.integrity_classified_by
  )
  OR (
    OLD.selection_integrity_status = 'legacy_unresolved'
    AND OLD.holdout_isolation_status = 'legacy_unresolved'
    AND NEW.selection_integrity_status IN (
      'verified',
      'invalid_final_holdout_ranking',
      'invalid_selection_provenance',
      'invalid_holdout_isolation'
    )
    AND NEW.holdout_isolation_status IN ('verified', 'invalid')
    AND (
      NEW.selection_integrity_status <> 'verified'
      OR NEW.holdout_isolation_status = 'verified'
    )
    AND NEW.selection_integrity_reason IS NOT NULL
    AND NEW.holdout_isolation_reason IS NOT NULL
    AND NEW.integrity_classified_at IS NOT NULL
    AND NEW.integrity_classified_by IS NOT NULL
  )
)
BEGIN
  SELECT RAISE(ABORT, 'candidate selection integrity classification is one-way');
END;

CREATE TABLE IF NOT EXISTS holdout_exposures (
  holdout_exposure_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  validation_design_id TEXT NOT NULL,
  validation_design_version_id TEXT NOT NULL,
  split_id TEXT NOT NULL,
  final_holdout_partition_id TEXT NOT NULL,
  candidate_decision_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  final_holdout_status TEXT NOT NULL DEFAULT 'sealed'
    CHECK (final_holdout_status IN ('sealed', 'opened', 'evaluated', 'invalidated')),
  selection_locked_at TEXT,
  sealed_at TEXT NOT NULL,
  first_opened_at TEXT,
  opened_by TEXT,
  evaluated_at TEXT,
  evaluation_package_id TEXT,
  invalidated_at TEXT,
  invalidated_by TEXT,
  invalidation_reason TEXT,
  exposure_contract_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(candidate_decision_id)
    REFERENCES candidate_selection_decisions(candidate_decision_id) ON DELETE RESTRICT,
  UNIQUE(project_id, dataset_version_id, split_id, final_holdout_partition_id),
  CHECK (final_holdout_status <> 'opened' OR first_opened_at IS NOT NULL),
  CHECK (
    final_holdout_status <> 'evaluated'
    OR (
      first_opened_at IS NOT NULL
      AND evaluated_at IS NOT NULL
      AND evaluation_package_id IS NOT NULL
    )
  ),
  CHECK (
    final_holdout_status <> 'invalidated'
    OR (invalidated_at IS NOT NULL AND invalidation_reason IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_holdout_exposures_exact
  ON holdout_exposures(
    project_id, dataset_id, dataset_version_id, split_id,
    final_holdout_partition_id, candidate_decision_id
  );

CREATE INDEX IF NOT EXISTS idx_holdout_exposures_status
  ON holdout_exposures(project_id, final_holdout_status);

CREATE TRIGGER IF NOT EXISTS trg_holdout_exposures_identity_immutable
BEFORE UPDATE OF
  holdout_exposure_id, project_id, dataset_id, dataset_version_id,
  validation_design_id, validation_design_version_id, split_id,
  final_holdout_partition_id, candidate_decision_id, candidate_id,
  selection_locked_at, sealed_at, exposure_contract_hash, created_at
ON holdout_exposures
BEGIN
  SELECT RAISE(ABORT, 'holdout exposure identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_holdout_exposures_valid_transition
BEFORE UPDATE OF final_holdout_status ON holdout_exposures
WHEN NOT (
  OLD.final_holdout_status = NEW.final_holdout_status
  OR (OLD.final_holdout_status = 'sealed' AND NEW.final_holdout_status IN ('opened', 'invalidated'))
  OR (OLD.final_holdout_status = 'opened' AND NEW.final_holdout_status IN ('evaluated', 'invalidated'))
  OR (OLD.final_holdout_status = 'evaluated' AND NEW.final_holdout_status = 'invalidated')
)
BEGIN
  SELECT RAISE(ABORT, 'invalid final holdout exposure transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_holdout_exposures_no_delete
BEFORE DELETE ON holdout_exposures
BEGIN
  SELECT RAISE(ABORT, 'holdout exposures are durable governance records');
END;

CREATE TABLE IF NOT EXISTS evaluation_packages (
  evaluation_package_id TEXT PRIMARY KEY,
  package_status TEXT NOT NULL DEFAULT 'complete'
    CHECK (package_status IN ('complete', 'legacy_unresolved', 'invalid')),
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  feature_manifest_id TEXT NOT NULL,
  feature_manifest_hash TEXT,
  treatment_manifest_id TEXT,
  treatment_manifest_hash TEXT,
  materialization_id TEXT,
  validation_design_id TEXT NOT NULL,
  validation_design_version_id TEXT NOT NULL,
  split_id TEXT NOT NULL,
  training_job_id TEXT NOT NULL,
  training_run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  candidate_decision_id TEXT NOT NULL,
  holdout_exposure_id TEXT NOT NULL,
  final_holdout_partition_id TEXT NOT NULL,
  selection_metric_name TEXT NOT NULL,
  selection_metric_value REAL NOT NULL,
  selection_metric_source TEXT NOT NULL,
  selection_integrity_status TEXT NOT NULL DEFAULT 'legacy_unresolved'
    CHECK (
      selection_integrity_status IN (
        'legacy_unresolved',
        'verified',
        'invalid_final_holdout_ranking',
        'invalid_selection_provenance',
        'invalid_holdout_isolation'
      )
    ),
  selection_evidence_json TEXT NOT NULL DEFAULT '{}',
  final_holdout_evidence_json TEXT NOT NULL DEFAULT '{}',
  metric_definitions_json TEXT NOT NULL DEFAULT '{}',
  threshold_policy_json TEXT NOT NULL DEFAULT '{}',
  isolation_evidence_json TEXT NOT NULL DEFAULT '{}',
  canonical_lineage_json TEXT NOT NULL DEFAULT '{}',
  holdout_isolation_status TEXT NOT NULL DEFAULT 'legacy_unresolved'
    CHECK (holdout_isolation_status IN ('legacy_unresolved', 'verified', 'invalid')),
  final_holdout_status TEXT NOT NULL DEFAULT 'evaluated'
    CHECK (final_holdout_status IN ('evaluated', 'invalidated', 'legacy_unresolved')),
  threshold_locked_at TEXT,
  holdout_exposed_at TEXT,
  recommendations_derived_from_final_holdout INTEGER NOT NULL DEFAULT 0
    CHECK (recommendations_derived_from_final_holdout IN (0, 1)),
  package_integrity_status TEXT NOT NULL DEFAULT 'legacy_unresolved'
    CHECK (package_integrity_status IN ('legacy_unresolved', 'verified', 'invalid')),
  evaluation_package_contract_hash TEXT NOT NULL UNIQUE,
  content_hash TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(candidate_decision_id)
    REFERENCES candidate_selection_decisions(candidate_decision_id) ON DELETE RESTRICT,
  FOREIGN KEY(holdout_exposure_id)
    REFERENCES holdout_exposures(holdout_exposure_id) ON DELETE RESTRICT,
  UNIQUE(candidate_decision_id, holdout_exposure_id),
  CHECK (
    selection_metric_source <> 'final_holdout'
    OR selection_integrity_status = 'invalid_final_holdout_ranking'
  ),
  CHECK (
    package_status <> 'complete'
    OR (
      selection_integrity_status = 'verified'
      AND holdout_isolation_status = 'verified'
      AND final_holdout_status = 'evaluated'
      AND package_integrity_status = 'verified'
      AND threshold_locked_at IS NOT NULL
      AND holdout_exposed_at IS NOT NULL
      AND recommendations_derived_from_final_holdout = 0
    )
  )
);

CREATE INDEX IF NOT EXISTS idx_evaluation_packages_exact
  ON evaluation_packages(
    project_id, dataset_id, dataset_version_id, training_run_id,
    candidate_id, candidate_decision_id
  );

CREATE INDEX IF NOT EXISTS idx_evaluation_packages_integrity
  ON evaluation_packages(
    project_id, selection_integrity_status, holdout_isolation_status,
    package_integrity_status
  );

CREATE TRIGGER IF NOT EXISTS trg_evaluation_packages_immutable
BEFORE UPDATE ON evaluation_packages
BEGIN
  SELECT RAISE(ABORT, 'evaluation package contract is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_evaluation_packages_no_delete
BEFORE DELETE ON evaluation_packages
BEGIN
  SELECT RAISE(ABORT, 'evaluation packages are durable governance records');
END;

ALTER TABLE model_versions ADD COLUMN candidate_decision_id TEXT;
ALTER TABLE model_versions ADD COLUMN candidate_decision_status TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN candidate_decision_contract_hash TEXT;
ALTER TABLE model_versions ADD COLUMN selection_metric_name TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN selection_metric_value REAL;
ALTER TABLE model_versions ADD COLUMN selection_metric_source TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN selection_integrity_status TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN selection_locked_at TEXT;
ALTER TABLE model_versions ADD COLUMN holdout_exposure_id TEXT;
ALTER TABLE model_versions ADD COLUMN final_holdout_partition_id TEXT;
ALTER TABLE model_versions ADD COLUMN final_holdout_status TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN holdout_isolation_status TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN threshold_locked_at TEXT;
ALTER TABLE model_versions ADD COLUMN evaluation_package_contract_hash TEXT;
ALTER TABLE model_versions ADD COLUMN evaluation_package_integrity_status TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN promotion_readiness_status TEXT NOT NULL DEFAULT 'legacy_unresolved';

CREATE INDEX IF NOT EXISTS idx_model_versions_candidate_decision
  ON model_versions(project_id, candidate_decision_id);

CREATE INDEX IF NOT EXISTS idx_model_versions_selection_integrity
  ON model_versions(
    project_id, candidate_decision_status, selection_integrity_status, holdout_isolation_status,
    evaluation_package_integrity_status, promotion_readiness_status
  );

CREATE INDEX IF NOT EXISTS idx_model_versions_holdout_exposure
  ON model_versions(project_id, holdout_exposure_id, final_holdout_status);

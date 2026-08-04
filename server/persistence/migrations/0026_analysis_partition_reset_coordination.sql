-- Governed Analysis Partition reset coordination.
--
-- Reset never rewrites or deletes an immutable derivative.  This ledger is
-- the durable current-state overlay for immutable candidate/evaluation rows
-- and the audit receipt for mutable rows that are marked stale in the same
-- SQLite transaction as partition supersession/replacement.

CREATE TABLE IF NOT EXISTS analysis_partition_reset_operations (
  reset_operation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  prior_analysis_partition_id TEXT NOT NULL,
  prior_revision INTEGER NOT NULL CHECK (prior_revision > 0),
  replacement_analysis_partition_id TEXT,
  replacement_revision INTEGER,
  operation_kind TEXT NOT NULL
    CHECK (operation_kind IN ('reset_replace', 'invalidate_only')),
  operation_status TEXT NOT NULL
    CHECK (operation_status IN ('committed')),
  actor_user_id TEXT NOT NULL,
  rationale TEXT NOT NULL,
  inventory_json TEXT NOT NULL DEFAULT '[]',
  invalidation_receipt_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  UNIQUE(project_id, prior_analysis_partition_id, replacement_analysis_partition_id)
);

CREATE INDEX IF NOT EXISTS idx_analysis_partition_reset_operations_project
  ON analysis_partition_reset_operations(project_id, committed_at DESC);

CREATE TABLE IF NOT EXISTS analysis_partition_derivative_invalidations (
  derivative_invalidation_id TEXT PRIMARY KEY,
  reset_operation_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  prior_analysis_partition_id TEXT NOT NULL,
  prior_revision INTEGER NOT NULL CHECK (prior_revision > 0),
  artifact_type TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  source_authority TEXT NOT NULL,
  prior_status TEXT,
  invalidation_status TEXT NOT NULL DEFAULT 'invalidated'
    CHECK (invalidation_status IN ('invalidated', 'preserved_history')),
  rationale TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  invalidated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(reset_operation_id)
    REFERENCES analysis_partition_reset_operations(reset_operation_id)
    ON DELETE RESTRICT,
  UNIQUE(reset_operation_id, artifact_type, artifact_id, source_authority)
);

CREATE INDEX IF NOT EXISTS idx_analysis_partition_derivative_invalidations_exact
  ON analysis_partition_derivative_invalidations(
    project_id, dataset_id, dataset_version_id,
    prior_analysis_partition_id, artifact_type
  );

CREATE TRIGGER IF NOT EXISTS trg_analysis_partition_reset_operations_no_update
BEFORE UPDATE ON analysis_partition_reset_operations
BEGIN
  SELECT RAISE(ABORT, 'analysis partition reset operations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_analysis_partition_reset_operations_no_delete
BEFORE DELETE ON analysis_partition_reset_operations
BEGIN
  SELECT RAISE(ABORT, 'analysis partition reset operations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_analysis_partition_derivative_invalidations_no_update
BEFORE UPDATE ON analysis_partition_derivative_invalidations
BEGIN
  SELECT RAISE(ABORT, 'analysis partition derivative invalidations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_analysis_partition_derivative_invalidations_no_delete
BEFORE DELETE ON analysis_partition_derivative_invalidations
BEGIN
  SELECT RAISE(ABORT, 'analysis partition derivative invalidations are append-only');
END;

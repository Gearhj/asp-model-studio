-- Durable pre-EDA Analysis Partition authority.
--
-- The row assignments stored here are the sole authority for the development
-- population and sealed final holdout.  They are intentionally independent of
-- browser state, workflow checkpoints, feature-engineering manifests, and the
-- later Validation Design.  A current partition is unique per project; reset
-- supersedes (but never deletes) the previous immutable assignment.

CREATE TABLE IF NOT EXISTS analysis_partitions (
  analysis_partition_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  target_contract_id TEXT NOT NULL,
  target_column TEXT NOT NULL,
  positive_value_json TEXT NOT NULL,
  negative_value_json TEXT NOT NULL,
  predictor_authorization_id TEXT NOT NULL,
  development_partition_id TEXT NOT NULL UNIQUE,
  sealed_holdout_partition_id TEXT NOT NULL UNIQUE,
  development_share REAL NOT NULL CHECK (development_share > 0 AND development_share < 1),
  holdout_share REAL NOT NULL CHECK (holdout_share > 0 AND holdout_share < 1),
  random_seed INTEGER NOT NULL CHECK (random_seed >= 0),
  stratification_policy TEXT NOT NULL
    CHECK (stratification_policy IN ('target', 'none')),
  stratification_field TEXT NOT NULL,
  population_count INTEGER NOT NULL CHECK (population_count > 0),
  development_count INTEGER NOT NULL CHECK (development_count > 0),
  holdout_count INTEGER NOT NULL CHECK (holdout_count > 0),
  event_counts_json TEXT NOT NULL DEFAULT '{}',
  row_assignments_json TEXT NOT NULL,
  assignment_hash TEXT NOT NULL,
  population_fingerprint TEXT NOT NULL,
  artifact_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'current'
    CHECK (status IN ('current', 'stale', 'superseded')),
  revision INTEGER NOT NULL CHECK (revision > 0),
  final_holdout_status TEXT NOT NULL DEFAULT 'sealed'
    CHECK (final_holdout_status = 'sealed'),
  holdout_isolation_status TEXT NOT NULL DEFAULT 'verified'
    CHECK (holdout_isolation_status = 'verified'),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  sealed_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  stale_reason TEXT,
  superseded_by_partition_id TEXT,
  UNIQUE (project_id, revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_partitions_current_project
  ON analysis_partitions(project_id)
  WHERE status = 'current';

CREATE INDEX IF NOT EXISTS idx_analysis_partitions_exact_identity
  ON analysis_partitions(
    project_id, dataset_id, dataset_version_id, target_contract_id, status
  );

CREATE INDEX IF NOT EXISTS idx_analysis_partitions_artifact_hash
  ON analysis_partitions(artifact_hash);

-- Lifecycle state may change, but the governed identity, configuration,
-- assignment, counts, and integrity hashes are immutable after insertion.
CREATE TRIGGER IF NOT EXISTS trg_analysis_partitions_immutable_contract
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

CREATE TRIGGER IF NOT EXISTS trg_analysis_partitions_no_delete
BEFORE DELETE ON analysis_partitions
BEGIN
  SELECT RAISE(ABORT, 'analysis partitions are append-only');
END;

CREATE TABLE IF NOT EXISTS analysis_partition_events (
  analysis_partition_event_id TEXT PRIMARY KEY,
  analysis_partition_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  event_type TEXT NOT NULL
    CHECK (event_type IN ('confirmed', 'reused', 'invalidated', 'superseded')),
  event_status TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_analysis_partition_events_project
  ON analysis_partition_events(project_id, created_at DESC);

CREATE TRIGGER IF NOT EXISTS trg_analysis_partition_events_no_update
BEFORE UPDATE ON analysis_partition_events
BEGIN
  SELECT RAISE(ABORT, 'analysis partition events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_analysis_partition_events_no_delete
BEFORE DELETE ON analysis_partition_events
BEGIN
  SELECT RAISE(ABORT, 'analysis partition events are append-only');
END;

-- Data Acquisition owns a separate predictor-authorization authority.  It is
-- exact-version scoped and may change without changing row membership.
CREATE TABLE IF NOT EXISTS predictor_authorization_manifests (
  predictor_authorization_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  target_contract_id TEXT NOT NULL,
  target_column TEXT NOT NULL,
  authorized_predictors_json TEXT NOT NULL,
  excluded_predictors_json TEXT NOT NULL DEFAULT '{}',
  manifest_json TEXT NOT NULL,
  artifact_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'current'
    CHECK (status IN ('current', 'superseded', 'stale')),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  superseded_by_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_predictor_authorization_current_project
  ON predictor_authorization_manifests(project_id)
  WHERE status = 'current';

CREATE INDEX IF NOT EXISTS idx_predictor_authorization_exact_identity
  ON predictor_authorization_manifests(
    project_id, dataset_id, dataset_version_id, target_contract_id, status
  );

CREATE TRIGGER IF NOT EXISTS trg_predictor_authorization_immutable_contract
BEFORE UPDATE ON predictor_authorization_manifests
WHEN
  NEW.predictor_authorization_id IS NOT OLD.predictor_authorization_id OR
  NEW.project_id IS NOT OLD.project_id OR
  NEW.dataset_id IS NOT OLD.dataset_id OR
  NEW.dataset_version_id IS NOT OLD.dataset_version_id OR
  NEW.target_contract_id IS NOT OLD.target_contract_id OR
  NEW.target_column IS NOT OLD.target_column OR
  NEW.authorized_predictors_json IS NOT OLD.authorized_predictors_json OR
  NEW.excluded_predictors_json IS NOT OLD.excluded_predictors_json OR
  NEW.manifest_json IS NOT OLD.manifest_json OR
  NEW.artifact_hash IS NOT OLD.artifact_hash OR
  NEW.created_by IS NOT OLD.created_by OR
  NEW.created_at IS NOT OLD.created_at
BEGIN
  SELECT RAISE(ABORT, 'predictor authorization contract is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_predictor_authorization_no_delete
BEFORE DELETE ON predictor_authorization_manifests
BEGIN
  SELECT RAISE(ABORT, 'predictor authorization manifests are append-only');
END;

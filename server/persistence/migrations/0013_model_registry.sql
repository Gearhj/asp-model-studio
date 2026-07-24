-- ATLAS Durable Model Registry and Model Versioning, Phase 1.
--
-- Two tables: `models` (the durable, mutable-lifecycle parent -- name, status,
-- currentVersionId, archived) and `model_versions` (immutable once created --
-- see model_registry_service.py's docstring for what "immutable" means in
-- practice: content columns are never updated after INSERT; only the three
-- governance status columns and archived_at may change later, exactly like a
-- real model registry's stage transitions).
--
-- project_id uses ON DELETE SET NULL (not CASCADE), mirroring scoring_runs'
-- precedent (0011_scoring_runs.sql): a Model/ModelVersion is a durable
-- governance artifact that must survive its originating project's deletion.
CREATE TABLE IF NOT EXISTS models (
  model_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  problem_type TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  owner_user_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  current_version_id TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  archived_at TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]',
  description TEXT
);

CREATE TABLE IF NOT EXISTS model_versions (
  model_version_id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL REFERENCES models(model_id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  training_run_id TEXT,
  project_id TEXT,
  dataset_id TEXT,
  dataset_version_id TEXT,
  feature_manifest_version TEXT,
  algorithm TEXT,
  algorithm_version TEXT,
  hyperparameters_json TEXT NOT NULL DEFAULT '{}',
  training_parameters_json TEXT NOT NULL DEFAULT '{}',
  metrics_summary_json TEXT NOT NULL DEFAULT '{}',
  evaluation_summary_json TEXT NOT NULL DEFAULT '{}',
  interpretation_summary_json TEXT NOT NULL DEFAULT '{}',
  artifact_reference TEXT,
  artifact_format TEXT,
  training_timestamp TEXT,
  checksum TEXT,
  approval_status TEXT NOT NULL DEFAULT 'unreviewed',
  validation_status TEXT NOT NULL DEFAULT 'not_validated',
  documentation_status TEXT NOT NULL DEFAULT 'not_documented',
  lineage_json TEXT NOT NULL DEFAULT '{}',
  archived_at TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_models_project ON models(project_id);
CREATE INDEX IF NOT EXISTS idx_models_status ON models(status);
CREATE INDEX IF NOT EXISTS idx_model_versions_model ON model_versions(model_id);
CREATE INDEX IF NOT EXISTS idx_model_versions_training_run ON model_versions(training_run_id);
CREATE INDEX IF NOT EXISTS idx_model_versions_dataset ON model_versions(dataset_id);

-- Phase F: ScoringRun must reference a real modelVersionId, not a synthesized
-- timestamp. Additive column -- the existing model_id/model_version TEXT
-- columns are untouched (model_id already held a usable value; model_version
-- keeps working as a display string for pre-registry rows and remains
-- populated going forward, now sourced from the registry when available).
ALTER TABLE scoring_runs ADD COLUMN model_version_id TEXT;
CREATE INDEX IF NOT EXISTS idx_scoring_runs_model_version ON scoring_runs(model_version_id);

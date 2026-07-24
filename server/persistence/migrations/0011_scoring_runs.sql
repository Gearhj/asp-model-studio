-- ATLAS Persistent Scoring Runs and Analytical Result History, Phase 1.
--
-- Durable, immutable record of one TRAIN/TEST/OOT/external-validation scoring
-- execution. Row-level scored output is NOT stored here (Phase C: "Do NOT
-- automatically persist massive prediction tables in SQLite") -- it lives in a
-- governed Parquet artifact under server/artifacts/scoring_runs/{scoring_run_id}/,
-- referenced by output_artifact_path. Only metadata, bounded metrics/diagnostic
-- summaries, and artifact references live in this table.
--
-- project_id uses ON DELETE SET NULL (not CASCADE): a scoring run is a durable
-- governance artifact, matching the existing Dataset Library precedent where a
-- registered dataset survives project deletion (unlinked, not destroyed). See
-- persistence_router.py's delete_project, which archives (not deletes) a
-- project's scoring runs before the project row itself is removed.
CREATE TABLE IF NOT EXISTS scoring_runs (
  scoring_run_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
  user_id TEXT,
  dataset_id TEXT,
  dataset_version_id TEXT,
  dataset_identity TEXT,
  partition TEXT NOT NULL,
  model_id TEXT,
  model_version TEXT,
  feature_manifest_version TEXT,
  problem_type TEXT,
  target TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  started_by TEXT,
  execution_engine TEXT,
  query_version TEXT,
  row_count INTEGER,
  prediction_column TEXT,
  probability_column TEXT,
  residual_column TEXT,
  output_artifact_id TEXT,
  output_artifact_path TEXT,
  output_artifact_format TEXT,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  diagnostics_json TEXT NOT NULL DEFAULT '{}',
  psi_json TEXT NOT NULL DEFAULT '{}',
  vsi_json TEXT NOT NULL DEFAULT '{}',
  evidence_links_json TEXT NOT NULL DEFAULT '[]',
  documentation_links_json TEXT NOT NULL DEFAULT '[]',
  lineage_json TEXT NOT NULL DEFAULT '{}',
  retention_policy TEXT NOT NULL DEFAULT 'standard',
  archived_at TEXT,
  checksum TEXT,
  error_message TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scoring_runs_project ON scoring_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_scoring_runs_dataset ON scoring_runs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_scoring_runs_model ON scoring_runs(model_id);
CREATE INDEX IF NOT EXISTS idx_scoring_runs_partition ON scoring_runs(partition);
CREATE INDEX IF NOT EXISTS idx_scoring_runs_status ON scoring_runs(status);
CREATE INDEX IF NOT EXISTS idx_scoring_runs_created ON scoring_runs(created_at);

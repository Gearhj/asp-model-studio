-- Metadata-only registry for governed MLB plate-appearance research runs.
-- Prediction rows, fitted model bytes, exchange paths, and deployment state are
-- deliberately outside this schema.

CREATE TABLE IF NOT EXISTS sports_pa_feature_views (
  feature_view_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL
    REFERENCES sports_research_projects(project_id) ON DELETE RESTRICT,
  parent_dataset_registration_id TEXT NOT NULL
    REFERENCES sports_dataset_registrations(registration_id) ON DELETE RESTRICT,
  identity_bridge_registration_id TEXT NOT NULL
    REFERENCES sports_identity_bridge_registrations(bridge_registration_id) ON DELETE RESTRICT,
  contract_name TEXT NOT NULL,
  contract_version TEXT NOT NULL,
  content_sha TEXT NOT NULL UNIQUE,
  row_count INTEGER NOT NULL CHECK (row_count >= 0),
  feature_count INTEGER NOT NULL CHECK (feature_count >= 0),
  feature_names_json TEXT NOT NULL,
  population TEXT NOT NULL,
  seasons_json TEXT NOT NULL,
  logical_uri TEXT NOT NULL UNIQUE,
  artifact_sha TEXT NOT NULL,
  artifact_byte_count INTEGER NOT NULL CHECK (artifact_byte_count >= 0),
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sports_pa_feature_view_project
  ON sports_pa_feature_views(project_id, created_at);

CREATE TABLE IF NOT EXISTS sports_pa_research_runs (
  run_id TEXT PRIMARY KEY,
  run_sha TEXT NOT NULL UNIQUE,
  run_identity_sha TEXT NOT NULL UNIQUE,
  run_created_at TEXT NOT NULL,
  code_revision TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  project_id TEXT NOT NULL
    REFERENCES sports_research_projects(project_id) ON DELETE RESTRICT,
  parent_dataset_registration_id TEXT NOT NULL
    REFERENCES sports_dataset_registrations(registration_id) ON DELETE RESTRICT,
  parent_manifest_sha TEXT NOT NULL,
  parent_partition_authority_sha TEXT NOT NULL,
  identity_bridge_registration_id TEXT NOT NULL
    REFERENCES sports_identity_bridge_registrations(bridge_registration_id) ON DELETE RESTRICT,
  identity_bridge_manifest_sha TEXT NOT NULL,
  identity_join_audit_id TEXT NOT NULL
    REFERENCES sports_identity_join_audits(join_audit_id) ON DELETE RESTRICT,
  feature_view_id TEXT NOT NULL
    REFERENCES sports_pa_feature_views(feature_view_id) ON DELETE RESTRICT,
  class_order_json TEXT NOT NULL,
  terminal_status TEXT NOT NULL CHECK (
    terminal_status IN (
      'RESEARCH_CHALLENGER',
      'RESEARCH_BASELINE',
      'REJECTED_BASELINE',
      'BLOCKED'
    )
  ),
  selected_candidate_id TEXT,
  selection_metric TEXT,
  selection_rationale TEXT,
  calibration_json TEXT,
  bootstrap_comparisons_json TEXT NOT NULL,
  research_decision_json TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  last_validated_at TEXT NOT NULL,
  registered_by TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  FOREIGN KEY (run_id, selected_candidate_id)
    REFERENCES sports_pa_candidates(run_id, candidate_id)
    DEFERRABLE INITIALLY DEFERRED
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sports_pa_active_project
  ON sports_pa_research_runs(project_id)
  WHERE active = 1;

CREATE INDEX IF NOT EXISTS idx_sports_pa_run_project_status
  ON sports_pa_research_runs(project_id, terminal_status, registered_at);

CREATE TABLE IF NOT EXISTS sports_pa_experiments (
  experiment_id TEXT NOT NULL,
  run_id TEXT NOT NULL UNIQUE
    REFERENCES sports_pa_research_runs(run_id) ON DELETE CASCADE,
  objective TEXT NOT NULL,
  seed INTEGER NOT NULL,
  training_contract_version TEXT NOT NULL,
  PRIMARY KEY (run_id, experiment_id)
);

CREATE TABLE IF NOT EXISTS sports_pa_candidates (
  run_id TEXT NOT NULL
    REFERENCES sports_pa_research_runs(run_id) ON DELETE CASCADE,
  candidate_id TEXT NOT NULL,
  experiment_id TEXT NOT NULL,
  candidate_type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
  config_sha TEXT NOT NULL,
  config_json TEXT NOT NULL,
  runtime_seconds REAL NOT NULL CHECK (runtime_seconds >= 0.0),
  convergence_json TEXT NOT NULL,
  aggregate_metrics_json TEXT,
  eligible INTEGER NOT NULL CHECK (eligible IN (0, 1)),
  selected INTEGER NOT NULL CHECK (selected IN (0, 1)),
  rejection_reasons_json TEXT NOT NULL,
  PRIMARY KEY (run_id, candidate_id),
  FOREIGN KEY (run_id, experiment_id)
    REFERENCES sports_pa_experiments(run_id, experiment_id) ON DELETE CASCADE,
  UNIQUE (run_id, ordinal),
  UNIQUE (run_id, config_sha)
);

CREATE INDEX IF NOT EXISTS idx_sports_pa_candidate_experiment
  ON sports_pa_candidates(experiment_id, ordinal);

CREATE TABLE IF NOT EXISTS sports_pa_candidate_fold_metrics (
  run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  fold_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('COMPLETE', 'NOT_RUN_BY_POLICY')),
  training_seasons_json TEXT NOT NULL,
  validation_season INTEGER NOT NULL,
  training_rows INTEGER NOT NULL CHECK (training_rows >= 0),
  validation_rows INTEGER NOT NULL CHECK (validation_rows >= 0),
  metrics_json TEXT,
  PRIMARY KEY (run_id, candidate_id, fold_id),
  FOREIGN KEY (run_id, candidate_id)
    REFERENCES sports_pa_candidates(run_id, candidate_id) ON DELETE CASCADE,
  CHECK (
    (status = 'COMPLETE' AND metrics_json IS NOT NULL)
    OR (status = 'NOT_RUN_BY_POLICY' AND metrics_json IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_sports_pa_fold_metric_run_fold
  ON sports_pa_candidate_fold_metrics(run_id, fold_id, candidate_id);

CREATE TABLE IF NOT EXISTS sports_pa_artifact_references (
  run_id TEXT NOT NULL
    REFERENCES sports_pa_research_runs(run_id) ON DELETE CASCADE,
  artifact_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  logical_uri TEXT NOT NULL,
  artifact_sha TEXT NOT NULL,
  artifact_byte_count INTEGER NOT NULL CHECK (artifact_byte_count >= 0),
  media_type TEXT NOT NULL,
  PRIMARY KEY (run_id, artifact_id),
  UNIQUE (run_id, logical_uri),
  UNIQUE (run_id, artifact_sha)
);

CREATE TABLE IF NOT EXISTS sports_pa_model_graphs (
  run_id TEXT NOT NULL UNIQUE
    REFERENCES sports_pa_research_runs(run_id) ON DELETE CASCADE,
  graph_id TEXT NOT NULL,
  PRIMARY KEY (run_id, graph_id)
);

CREATE TABLE IF NOT EXISTS sports_pa_model_graph_nodes (
  run_id TEXT NOT NULL,
  graph_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  node_type TEXT NOT NULL,
  label TEXT NOT NULL,
  status TEXT NOT NULL,
  candidate_id TEXT,
  PRIMARY KEY (run_id, graph_id, node_id),
  FOREIGN KEY (run_id, graph_id)
    REFERENCES sports_pa_model_graphs(run_id, graph_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sports_pa_model_graph_edges (
  run_id TEXT NOT NULL,
  graph_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  source_node_id TEXT NOT NULL,
  target_node_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  PRIMARY KEY (run_id, graph_id, edge_id),
  FOREIGN KEY (run_id, graph_id, source_node_id)
    REFERENCES sports_pa_model_graph_nodes(run_id, graph_id, node_id) ON DELETE CASCADE,
  FOREIGN KEY (run_id, graph_id, target_node_id)
    REFERENCES sports_pa_model_graph_nodes(run_id, graph_id, node_id) ON DELETE CASCADE
);

-- Additive, metadata-only registry for MLB Phase 4 research studies.
--
-- Phase 3 remains immutable and is referenced as an exact parent. Runtime
-- artifacts are represented only by content hashes and governed logical URIs;
-- prediction rows, model bytes, and physical paths do not belong in SQLite.

CREATE TABLE IF NOT EXISTS sports_phase4_studies (
  study_id TEXT PRIMARY KEY,
  study_sha TEXT NOT NULL UNIQUE,
  core_sha TEXT NOT NULL UNIQUE,
  identity_schema_version TEXT NOT NULL,
  study_created_at TEXT NOT NULL,
  code_revision TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  project_id TEXT NOT NULL
    REFERENCES sports_research_projects(project_id) ON DELETE RESTRICT,
  dataset_registration_id TEXT NOT NULL
    REFERENCES sports_dataset_registrations(registration_id) ON DELETE RESTRICT,
  dataset_manifest_sha TEXT NOT NULL,
  dataset_partition_authority_sha TEXT NOT NULL,
  identity_bridge_registration_id TEXT NOT NULL
    REFERENCES sports_identity_bridge_registrations(bridge_registration_id) ON DELETE RESTRICT,
  identity_bridge_manifest_sha TEXT NOT NULL,
  identity_join_audit_id TEXT NOT NULL
    REFERENCES sports_identity_join_audits(join_audit_id) ON DELETE RESTRICT,
  phase3_run_id TEXT NOT NULL
    REFERENCES sports_pa_research_runs(run_id) ON DELETE RESTRICT,
  phase3_run_sha TEXT NOT NULL,
  phase3_experiment_id TEXT NOT NULL,
  phase3_feature_contract_name TEXT NOT NULL,
  phase3_feature_contract_sha TEXT NOT NULL,
  phase3_feature_view_id TEXT NOT NULL
    REFERENCES sports_pa_feature_views(feature_view_id) ON DELETE RESTRICT,
  phase3_graph_id TEXT NOT NULL,
  phase3_status TEXT NOT NULL CHECK (phase3_status = 'RESEARCH_BASELINE'),
  decision_json TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  last_validated_at TEXT NOT NULL,
  registered_by TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  FOREIGN KEY (phase3_run_id, phase3_experiment_id)
    REFERENCES sports_pa_experiments(run_id, experiment_id) ON DELETE RESTRICT,
  FOREIGN KEY (phase3_run_id, phase3_graph_id)
    REFERENCES sports_pa_model_graphs(run_id, graph_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sports_phase4_active_project
  ON sports_phase4_studies(project_id)
  WHERE active = 1;

CREATE INDEX IF NOT EXISTS idx_sports_phase4_parent_run
  ON sports_phase4_studies(phase3_run_id, registered_at);

CREATE TABLE IF NOT EXISTS sports_phase4_components (
  study_id TEXT NOT NULL
    REFERENCES sports_phase4_studies(study_id) ON DELETE CASCADE,
  component_slot TEXT NOT NULL CHECK (
    component_slot IN ('dynamicState', 'lineup', 'starterDuration', 'bullpenUsage')
  ),
  component_id TEXT NOT NULL,
  component_type TEXT NOT NULL,
  contract_name TEXT NOT NULL,
  contract_sha TEXT NOT NULL,
  terminal_status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (study_id, component_slot),
  UNIQUE (study_id, component_id)
);

CREATE INDEX IF NOT EXISTS idx_sports_phase4_component_contract
  ON sports_phase4_components(contract_name, contract_sha, terminal_status);

CREATE TABLE IF NOT EXISTS sports_phase4_artifact_references (
  study_id TEXT NOT NULL
    REFERENCES sports_phase4_studies(study_id) ON DELETE CASCADE,
  artifact_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  logical_uri TEXT NOT NULL,
  artifact_sha TEXT NOT NULL,
  artifact_byte_count INTEGER NOT NULL CHECK (artifact_byte_count >= 0),
  media_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (study_id, artifact_id),
  UNIQUE (study_id, logical_uri),
  UNIQUE (study_id, artifact_sha)
);

CREATE TABLE IF NOT EXISTS sports_phase4_model_graphs (
  study_id TEXT NOT NULL UNIQUE
    REFERENCES sports_phase4_studies(study_id) ON DELETE CASCADE,
  graph_id TEXT NOT NULL,
  parent_phase3_graph_id TEXT NOT NULL,
  PRIMARY KEY (study_id, graph_id)
);

CREATE TABLE IF NOT EXISTS sports_phase4_model_graph_nodes (
  study_id TEXT NOT NULL,
  graph_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  node_type TEXT NOT NULL,
  label TEXT NOT NULL,
  status TEXT NOT NULL,
  component_id TEXT,
  authority_ref TEXT,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (study_id, graph_id, node_id),
  FOREIGN KEY (study_id, graph_id)
    REFERENCES sports_phase4_model_graphs(study_id, graph_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sports_phase4_model_graph_edges (
  study_id TEXT NOT NULL,
  graph_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  source_node_id TEXT NOT NULL,
  target_node_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (study_id, graph_id, edge_id),
  FOREIGN KEY (study_id, graph_id, source_node_id)
    REFERENCES sports_phase4_model_graph_nodes(study_id, graph_id, node_id) ON DELETE CASCADE,
  FOREIGN KEY (study_id, graph_id, target_node_id)
    REFERENCES sports_phase4_model_graph_nodes(study_id, graph_id, node_id) ON DELETE CASCADE
);

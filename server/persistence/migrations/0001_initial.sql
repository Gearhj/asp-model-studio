CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  email TEXT,
  role TEXT NOT NULL DEFAULT 'data_scientist',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  project_name TEXT NOT NULL,
  project_type TEXT NOT NULL,
  workflow_type TEXT NOT NULL,
  template_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  owner_user_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workflow_state (
  project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
  current_step_id TEXT,
  completed_steps_json TEXT NOT NULL DEFAULT '[]',
  workflow_status_json TEXT NOT NULL DEFAULT '{}',
  step_evidence_status_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
  dataset_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  dataset_name TEXT NOT NULL,
  source_type TEXT,
  source_label TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS dataset_versions (
  dataset_version_id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
  version_label TEXT,
  row_count INTEGER,
  column_count INTEGER,
  dataset_hash TEXT,
  created_at TEXT NOT NULL,
  profile_json TEXT NOT NULL DEFAULT '{}',
  schema_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evidence_artifacts (
  evidence_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  workflow_type TEXT,
  step_id TEXT,
  artifact_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  title TEXT NOT NULL,
  summary TEXT,
  source_ref TEXT,
  artifact_hash TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  captured_at TEXT,
  approved_at TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_records (
  run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  run_type TEXT NOT NULL,
  workflow_type TEXT,
  status TEXT NOT NULL DEFAULT 'created',
  started_at TEXT,
  completed_at TEXT,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  artifacts_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decision_journal (
  decision_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  decision_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  owner TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS documentation_packages (
  package_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  package_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  readiness_score REAL,
  section_count INTEGER,
  completed_section_count INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS export_artifacts (
  export_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  export_type TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_path TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  artifact_hash TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_datasets_project_id ON datasets(project_id);
CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset_id ON dataset_versions(dataset_id);
CREATE INDEX IF NOT EXISTS idx_evidence_project_id ON evidence_artifacts(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_project_id ON run_records(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_project_id ON decision_journal(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_documentation_project_id ON documentation_packages(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_exports_project_id ON export_artifacts(project_id, created_at DESC);

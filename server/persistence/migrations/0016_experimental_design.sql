CREATE TABLE IF NOT EXISTS experimental_design_studies (
  study_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL UNIQUE,
  current_version INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  contract_hash TEXT,
  contract_json TEXT NOT NULL DEFAULT '{}',
  artifacts_json TEXT NOT NULL DEFAULT '{}',
  blockers_json TEXT NOT NULL DEFAULT '[]',
  created_by TEXT,
  updated_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experimental_design_versions (
  study_version_id TEXT PRIMARY KEY,
  study_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  contract_hash TEXT NOT NULL,
  change_summary TEXT,
  contract_json TEXT NOT NULL DEFAULT '{}',
  artifacts_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(study_id, version_number),
  FOREIGN KEY(study_id) REFERENCES experimental_design_studies(study_id) ON DELETE CASCADE,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experimental_design_simulation_jobs (
  simulation_job_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  study_id TEXT NOT NULL,
  study_version INTEGER NOT NULL,
  design_version TEXT NOT NULL,
  owner_user_id TEXT NOT NULL,
  status TEXT NOT NULL,
  progress REAL NOT NULL DEFAULT 0,
  seed INTEGER NOT NULL,
  iterations INTEGER NOT NULL,
  parameters_json TEXT NOT NULL DEFAULT '{}',
  results_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}',
  cancellation_requested INTEGER NOT NULL DEFAULT 0,
  retry_parent_job_id TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
  FOREIGN KEY(study_id) REFERENCES experimental_design_studies(study_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_experimental_design_versions_project
  ON experimental_design_versions(project_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_experimental_design_jobs_project
  ON experimental_design_simulation_jobs(project_id, created_at DESC);

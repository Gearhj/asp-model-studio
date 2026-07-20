ALTER TABLE users ADD COLUMN last_active_at TEXT;

ALTER TABLE projects ADD COLUMN created_by TEXT;
ALTER TABLE projects ADD COLUMN updated_by TEXT;

ALTER TABLE workflow_state ADD COLUMN completed_by TEXT;

ALTER TABLE run_records ADD COLUMN created_by TEXT;

ALTER TABLE documentation_packages ADD COLUMN created_by TEXT;

ALTER TABLE export_artifacts ADD COLUMN storage_mode TEXT NOT NULL DEFAULT 'client_generated';

CREATE TABLE IF NOT EXISTS audit_log (
  audit_id TEXT PRIMARY KEY,
  project_id TEXT,
  user_id TEXT,
  action_type TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  title TEXT,
  summary TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS demo_feedback (
  feedback_id TEXT PRIMARY KEY,
  project_id TEXT,
  user_id TEXT,
  route TEXT NOT NULL,
  workflow_type TEXT,
  step_id TEXT,
  issue_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  expected_behavior TEXT,
  actual_behavior TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_users_last_active_at ON users(last_active_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_project ON audit_log(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_demo_feedback_created_at ON demo_feedback(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_demo_feedback_project ON demo_feedback(project_id, created_at DESC);

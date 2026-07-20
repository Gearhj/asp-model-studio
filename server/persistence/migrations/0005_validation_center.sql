CREATE TABLE IF NOT EXISTS validation_cases (
  validation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  asset_type TEXT NOT NULL,
  validation_template_id TEXT NOT NULL,
  status TEXT NOT NULL,
  business_status_label TEXT NOT NULL,
  risk_tier TEXT,
  assigned_validator_user_id TEXT,
  assigned_validator_name TEXT,
  submitted_by TEXT,
  submitted_at TEXT,
  review_started_at TEXT,
  review_completed_at TEXT,
  final_disposition TEXT,
  final_score REAL,
  next_review_date TEXT,
  summary TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_cases_project ON validation_cases(project_id);
CREATE INDEX IF NOT EXISTS idx_validation_cases_status ON validation_cases(status);
CREATE INDEX IF NOT EXISTS idx_validation_cases_validator ON validation_cases(assigned_validator_user_id);

CREATE TABLE IF NOT EXISTS validation_findings (
  finding_id TEXT PRIMARY KEY,
  validation_id TEXT NOT NULL REFERENCES validation_cases(validation_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  evidence_reference TEXT,
  remediation_owner TEXT,
  remediation_due_date TEXT,
  validator_notes TEXT,
  management_response_required INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_findings_case ON validation_findings(validation_id);
CREATE INDEX IF NOT EXISTS idx_validation_findings_project ON validation_findings(project_id);
CREATE INDEX IF NOT EXISTS idx_validation_findings_status ON validation_findings(status);

CREATE TABLE IF NOT EXISTS validation_checklist_items (
  checklist_item_id TEXT PRIMARY KEY,
  validation_id TEXT NOT NULL REFERENCES validation_cases(validation_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  template_id TEXT NOT NULL,
  category TEXT NOT NULL,
  item_key TEXT NOT NULL,
  item_label TEXT NOT NULL,
  item_description TEXT,
  status TEXT NOT NULL,
  result TEXT,
  evidence_reference TEXT,
  reviewer_notes TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  updated_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT,
  UNIQUE(validation_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_validation_checklist_case ON validation_checklist_items(validation_id);

CREATE TABLE IF NOT EXISTS validation_challenges (
  challenge_id TEXT PRIMARY KEY,
  validation_id TEXT NOT NULL REFERENCES validation_cases(validation_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  challenge_type TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT NOT NULL,
  challenge_question TEXT,
  validator_position TEXT,
  severity TEXT,
  due_date TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_challenges_case ON validation_challenges(validation_id);
CREATE INDEX IF NOT EXISTS idx_validation_challenges_status ON validation_challenges(status);

CREATE TABLE IF NOT EXISTS validation_responses (
  response_id TEXT PRIMARY KEY,
  challenge_id TEXT NOT NULL REFERENCES validation_challenges(challenge_id) ON DELETE CASCADE,
  validation_id TEXT NOT NULL REFERENCES validation_cases(validation_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  response_text TEXT NOT NULL,
  response_type TEXT,
  status TEXT NOT NULL,
  responder_user_id TEXT,
  responder_name TEXT,
  evidence_reference TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_responses_challenge ON validation_responses(challenge_id);

CREATE TABLE IF NOT EXISTS validation_approvals (
  approval_id TEXT PRIMARY KEY,
  validation_id TEXT NOT NULL REFERENCES validation_cases(validation_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  approver_user_id TEXT,
  approver_name TEXT,
  approver_role TEXT,
  decision TEXT NOT NULL,
  decision_rationale TEXT,
  conditions_json TEXT,
  approved_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_approvals_case ON validation_approvals(validation_id);

CREATE TABLE IF NOT EXISTS validation_case_events (
  event_id TEXT PRIMARY KEY,
  validation_id TEXT NOT NULL REFERENCES validation_cases(validation_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  user_id TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_events_case ON validation_case_events(validation_id);
CREATE INDEX IF NOT EXISTS idx_validation_events_project ON validation_case_events(project_id);

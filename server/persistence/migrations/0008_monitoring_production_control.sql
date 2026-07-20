CREATE TABLE IF NOT EXISTS monitoring_plans (
  monitoring_plan_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  asset_type TEXT,
  workflow_type TEXT,
  template_id TEXT,
  plan_name TEXT NOT NULL,
  plan_status TEXT NOT NULL DEFAULT 'draft',
  monitoring_owner_user_id TEXT,
  monitoring_owner_name TEXT,
  business_owner_user_id TEXT,
  business_owner_name TEXT,
  monitoring_cadence TEXT,
  first_monitoring_date TEXT,
  next_monitoring_date TEXT,
  production_start_date TEXT,
  monitoring_scope TEXT,
  data_source_ref TEXT,
  notes TEXT,
  created_by_user_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitoring_metrics (
  monitoring_metric_id TEXT PRIMARY KEY,
  monitoring_plan_id TEXT NOT NULL REFERENCES monitoring_plans(monitoring_plan_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  metric_category TEXT NOT NULL,
  metric_definition TEXT,
  metric_direction TEXT,
  warning_threshold REAL,
  breach_threshold REAL,
  lower_warning_threshold REAL,
  lower_breach_threshold REAL,
  unit TEXT,
  cadence TEXT,
  owner_user_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitoring_runs (
  monitoring_run_id TEXT PRIMARY KEY,
  monitoring_plan_id TEXT NOT NULL REFERENCES monitoring_plans(monitoring_plan_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  run_name TEXT,
  run_status TEXT NOT NULL DEFAULT 'draft',
  run_period_start TEXT,
  run_period_end TEXT,
  data_version_ref TEXT,
  executed_by_user_id TEXT,
  executed_at TEXT,
  completed_at TEXT,
  summary TEXT,
  overall_status TEXT,
  breach_count INTEGER DEFAULT 0,
  warning_count INTEGER DEFAULT 0,
  evidence_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitoring_observations (
  observation_id TEXT PRIMARY KEY,
  monitoring_run_id TEXT NOT NULL REFERENCES monitoring_runs(monitoring_run_id) ON DELETE CASCADE,
  monitoring_metric_id TEXT NOT NULL REFERENCES monitoring_metrics(monitoring_metric_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  observed_value REAL,
  baseline_value REAL,
  comparison_value REAL,
  status TEXT NOT NULL,
  threshold_used TEXT,
  interpretation TEXT,
  period_start TEXT,
  period_end TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitoring_alerts (
  alert_id TEXT PRIMARY KEY,
  monitoring_run_id TEXT,
  monitoring_plan_id TEXT,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  alert_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  title TEXT NOT NULL,
  description TEXT,
  metric_name TEXT,
  observed_value REAL,
  threshold_value REAL,
  owner_user_id TEXT,
  owner_name TEXT,
  due_date TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  resolved_at TEXT,
  resolution_notes TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitoring_actions (
  action_id TEXT PRIMARY KEY,
  alert_id TEXT,
  monitoring_plan_id TEXT,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  action_type TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  owner_user_id TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  due_date TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitoring_baselines (
  baseline_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  baseline_name TEXT NOT NULL,
  baseline_type TEXT NOT NULL,
  baseline_period_start TEXT,
  baseline_period_end TEXT,
  data_version_ref TEXT,
  metric_summary_json TEXT NOT NULL DEFAULT '{}',
  created_by_user_id TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitoring_events (
  event_id TEXT PRIMARY KEY,
  monitoring_plan_id TEXT,
  monitoring_run_id TEXT,
  project_id TEXT,
  user_id TEXT,
  event_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_monitoring_plans_project_id ON monitoring_plans(project_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_plans_plan_status ON monitoring_plans(plan_status);
CREATE INDEX IF NOT EXISTS idx_monitoring_plans_owner ON monitoring_plans(monitoring_owner_user_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_metrics_plan ON monitoring_metrics(monitoring_plan_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_plan ON monitoring_runs(monitoring_plan_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_project ON monitoring_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_observations_run ON monitoring_observations(monitoring_run_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_project ON monitoring_alerts(project_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_status ON monitoring_alerts(status);
CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_severity ON monitoring_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_monitoring_actions_project ON monitoring_actions(project_id);
CREATE INDEX IF NOT EXISTS idx_monitoring_actions_status ON monitoring_actions(status);
CREATE INDEX IF NOT EXISTS idx_monitoring_events_project ON monitoring_events(project_id);

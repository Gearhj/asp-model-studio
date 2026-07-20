CREATE TABLE IF NOT EXISTS analytical_runs (
  analytical_run_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
  workflow_type TEXT,
  analysis_type TEXT NOT NULL,
  analysis_version TEXT NOT NULL,
  dataset_id TEXT,
  dataset_version_id TEXT,
  source_run_record_id TEXT,
  status TEXT NOT NULL,
  requested_by_user_id TEXT,
  started_at TEXT,
  completed_at TEXT,
  parameter_json TEXT NOT NULL DEFAULT '{}',
  input_reference_json TEXT NOT NULL DEFAULT '{}',
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  warning_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  reproducibility_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytical_results (
  analytical_result_id TEXT PRIMARY KEY,
  analytical_run_id TEXT NOT NULL REFERENCES analytical_runs(analytical_run_id) ON DELETE CASCADE,
  result_type TEXT NOT NULL,
  result_name TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  sequence_number INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS analytical_tables (
  analytical_table_id TEXT PRIMARY KEY,
  analytical_run_id TEXT NOT NULL REFERENCES analytical_runs(analytical_run_id) ON DELETE CASCADE,
  table_name TEXT NOT NULL,
  table_title TEXT,
  table_json TEXT NOT NULL DEFAULT '{}',
  row_count INTEGER,
  column_count INTEGER,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS analytical_charts (
  analytical_chart_id TEXT PRIMARY KEY,
  analytical_run_id TEXT NOT NULL REFERENCES analytical_runs(analytical_run_id) ON DELETE CASCADE,
  chart_type TEXT NOT NULL,
  chart_title TEXT NOT NULL,
  chart_spec_json TEXT NOT NULL DEFAULT '{}',
  chart_data_json TEXT NOT NULL DEFAULT '[]',
  documentation_caption TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS analytical_interpretations (
  interpretation_id TEXT PRIMARY KEY,
  analytical_run_id TEXT NOT NULL REFERENCES analytical_runs(analytical_run_id) ON DELETE CASCADE,
  interpretation_type TEXT NOT NULL,
  severity TEXT,
  title TEXT,
  interpretation_text TEXT NOT NULL,
  supporting_statistic_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_analytical_runs_project ON analytical_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_analytical_runs_type ON analytical_runs(analysis_type);
CREATE INDEX IF NOT EXISTS idx_analytical_runs_status ON analytical_runs(status);
CREATE INDEX IF NOT EXISTS idx_analytical_runs_dataset ON analytical_runs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_analytical_results_run ON analytical_results(analytical_run_id);
CREATE INDEX IF NOT EXISTS idx_analytical_tables_run ON analytical_tables(analytical_run_id);
CREATE INDEX IF NOT EXISTS idx_analytical_charts_run ON analytical_charts(analytical_run_id);
CREATE INDEX IF NOT EXISTS idx_analytical_interpretations_run ON analytical_interpretations(analytical_run_id);

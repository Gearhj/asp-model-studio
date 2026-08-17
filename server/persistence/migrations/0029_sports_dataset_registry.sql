-- Metadata-only registry for immutable sports dataset exchanges.
-- Physical exchange paths and source rows are deliberately excluded.

CREATE TABLE IF NOT EXISTS sports_dataset_registrations (
  registration_id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL UNIQUE,
  manifest_id TEXT NOT NULL UNIQUE,
  manifest_sha TEXT NOT NULL UNIQUE,
  package_id TEXT NOT NULL UNIQUE,
  sport TEXT NOT NULL,
  league TEXT NOT NULL,
  evidence_cutoff TEXT NOT NULL,
  published_at TEXT NOT NULL,
  logical_package_root TEXT NOT NULL,
  validation_status TEXT NOT NULL CHECK (validation_status IN ('VALID', 'INVALID')),
  registered_at TEXT NOT NULL,
  last_validated_at TEXT NOT NULL,
  registered_by TEXT NOT NULL,
  rights_status TEXT NOT NULL,
  limitation_count INTEGER NOT NULL CHECK (limitation_count >= 0),
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  totals_json TEXT NOT NULL,
  seasons_json TEXT NOT NULL,
  evidence_coverage_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sports_dataset_active_identity
  ON sports_dataset_registrations(dataset_id, manifest_sha)
  WHERE active = 1;

CREATE TABLE IF NOT EXISTS sports_dataset_partitions (
  partition_id TEXT PRIMARY KEY,
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id) ON DELETE CASCADE,
  family TEXT NOT NULL,
  season INTEGER NOT NULL,
  month INTEGER,
  logical_uri TEXT NOT NULL UNIQUE,
  row_count INTEGER NOT NULL CHECK (row_count >= 0),
  byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
  minimum_date TEXT,
  maximum_date TEXT,
  schema_id TEXT NOT NULL,
  physical_schema_fingerprint TEXT NOT NULL,
  file_sha TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_version_id TEXT NOT NULL,
  original_source_logical_identity TEXT,
  checkpoint_lineage_id TEXT,
  governance_checksum TEXT,
  target_eligibility_json TEXT NOT NULL,
  temporal_classification_json TEXT NOT NULL,
  rights_ids_json TEXT NOT NULL,
  physical_schema_json TEXT NOT NULL,
  UNIQUE (registration_id, family, season, month, partition_id)
);

CREATE INDEX IF NOT EXISTS idx_sports_partitions_family_season
  ON sports_dataset_partitions(registration_id, family, season, month);

CREATE TABLE IF NOT EXISTS sports_dataset_schemas (
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id) ON DELETE CASCADE,
  family TEXT NOT NULL,
  logical_schema_version TEXT NOT NULL,
  compatible_partition_count INTEGER NOT NULL,
  physical_variant_count INTEGER NOT NULL,
  fields_json TEXT NOT NULL,
  physical_variants_json TEXT NOT NULL,
  PRIMARY KEY (registration_id, family)
);

CREATE TABLE IF NOT EXISTS sports_dataset_populations (
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id) ON DELETE CASCADE,
  population_id TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  predicate_json TEXT NOT NULL,
  allowed_uses_json TEXT NOT NULL,
  prohibited_uses_json TEXT NOT NULL,
  temporal_meaning TEXT NOT NULL,
  evaluation_precedence INTEGER NOT NULL,
  PRIMARY KEY (registration_id, population_id)
);

CREATE TABLE IF NOT EXISTS sports_dataset_temporal_folds (
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id) ON DELETE CASCADE,
  fold_id TEXT NOT NULL,
  training_seasons_json TEXT NOT NULL,
  validation_season INTEGER NOT NULL,
  training_end TEXT NOT NULL,
  validation_start TEXT NOT NULL,
  validation_end TEXT NOT NULL,
  training_rows INTEGER NOT NULL,
  validation_rows INTEGER NOT NULL,
  PRIMARY KEY (registration_id, fold_id)
);

CREATE TABLE IF NOT EXISTS sports_dataset_rights (
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id) ON DELETE CASCADE,
  rights_control_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  source_name TEXT NOT NULL,
  status TEXT NOT NULL,
  allowed_uses_json TEXT NOT NULL,
  prohibited_uses_json TEXT NOT NULL,
  attribution TEXT NOT NULL,
  controls_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  PRIMARY KEY (registration_id, rights_control_id)
);

CREATE TABLE IF NOT EXISTS sports_dataset_limitations (
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id) ON DELETE CASCADE,
  limitation_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  description TEXT NOT NULL,
  PRIMARY KEY (registration_id, limitation_id)
);

CREATE TABLE IF NOT EXISTS sports_research_projects (
  project_id TEXT PRIMARY KEY,
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id),
  project_name TEXT NOT NULL,
  sport TEXT NOT NULL,
  league TEXT NOT NULL,
  development_period TEXT NOT NULL,
  prior_history TEXT NOT NULL,
  forecast_lifecycle TEXT NOT NULL,
  primary_target TEXT NOT NULL,
  secondary_targets_json TEXT NOT NULL,
  baseline_population TEXT NOT NULL,
  upper_bound_population TEXT NOT NULL,
  research_purpose TEXT NOT NULL,
  workflow_evidence_json TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (registration_id, project_name)
);

CREATE TABLE IF NOT EXISTS sports_dataset_query_audit (
  query_id TEXT PRIMARY KEY,
  registration_id TEXT NOT NULL REFERENCES sports_dataset_registrations(registration_id),
  user_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  logical_scope TEXT NOT NULL,
  fields_json TEXT NOT NULL,
  requested_limit INTEGER,
  rows_scanned INTEGER NOT NULL DEFAULT 0,
  rows_returned INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  error_code TEXT
);

CREATE INDEX IF NOT EXISTS idx_sports_query_audit_registration
  ON sports_dataset_query_audit(registration_id, started_at DESC);

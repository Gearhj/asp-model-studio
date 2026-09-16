-- Immutable, project-bound Stage 3 feature-set definitions.  These records
-- freeze candidate predictor and preprocessing contracts only; they do not
-- contain source rows, transformed matrices, fitted preprocessors, or models.

CREATE TABLE IF NOT EXISTS stage3_feature_set_versions (
  feature_set_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  feature_set_key TEXT NOT NULL,
  feature_set_name TEXT NOT NULL,
  feature_set_version INTEGER NOT NULL CHECK (feature_set_version > 0),
  feature_set_status TEXT NOT NULL CHECK (
    feature_set_status IN ('DRAFT', 'REGISTERED', 'RETIRED')
  ),
  prior_feature_set_id TEXT,
  registered_from_feature_set_id TEXT,
  retired_feature_set_id TEXT,
  registration_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  activation_revision INTEGER NOT NULL CHECK (activation_revision > 0),
  source_dataset_id TEXT NOT NULL,
  source_manifest_sha TEXT NOT NULL,
  gold_manifest_sha TEXT NOT NULL,
  contextual_manifest_sha TEXT NOT NULL,
  authority_review_digest TEXT NOT NULL,
  development_start_date TEXT NOT NULL,
  development_end_date TEXT NOT NULL,
  development_rows INTEGER NOT NULL CHECK (development_rows > 0),
  final_oot_start_date TEXT NOT NULL,
  final_oot_end_date TEXT NOT NULL,
  final_oot_rows INTEGER NOT NULL CHECK (final_oot_rows > 0),
  ordered_features_json TEXT NOT NULL,
  family_memberships_json TEXT NOT NULL,
  transformation_contracts_json TEXT NOT NULL,
  interaction_contracts_json TEXT NOT NULL,
  unavailable_exclusions_json TEXT NOT NULL DEFAULT '[]',
  adopted_outlier_policy_id TEXT,
  adopted_outlier_policy_version INTEGER,
  adopted_outlier_policy_checksum TEXT,
  adopted_missing_policy_id TEXT,
  adopted_missing_policy_version INTEGER,
  adopted_missing_policy_checksum TEXT,
  description TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  content_sha256 TEXT NOT NULL,
  created_by_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (
    project_id, feature_set_key, authority_review_digest,
    feature_set_version
  )
);

CREATE INDEX IF NOT EXISTS idx_stage3_feature_set_current
  ON stage3_feature_set_versions(
    project_id, authority_review_digest, feature_set_key,
    feature_set_version DESC, created_at DESC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_set_no_update
BEFORE UPDATE ON stage3_feature_set_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-set versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_set_no_delete
BEFORE DELETE ON stage3_feature_set_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-set versions are immutable');
END;

CREATE TABLE IF NOT EXISTS stage3_feature_set_events (
  feature_set_event_id TEXT PRIMARY KEY,
  feature_set_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  feature_set_key TEXT NOT NULL,
  feature_set_version INTEGER NOT NULL CHECK (feature_set_version > 0),
  event_type TEXT NOT NULL CHECK (
    event_type IN (
      'DRAFT_CREATED', 'DRAFT_REVISED', 'FEATURE_SET_REGISTERED',
      'FEATURE_SET_SUPERSEDED', 'FEATURE_SET_RETIRED'
    )
  ),
  actor_user_id TEXT NOT NULL,
  prior_feature_set_id TEXT,
  authority_review_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_stage3_feature_set_events
  ON stage3_feature_set_events(
    project_id, authority_review_digest, feature_set_key,
    feature_set_version ASC, created_at ASC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_set_events_no_update
BEFORE UPDATE ON stage3_feature_set_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-set events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_set_events_no_delete
BEFORE DELETE ON stage3_feature_set_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-set events are append-only');
END;

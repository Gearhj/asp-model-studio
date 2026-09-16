-- Immutable, project-bound Stage 3 preprocessing-policy and predicted-preview
-- evidence.  These records authorize later fold-local fitting; they never
-- contain transformed source/Gold rows and they never identify a fitted
-- outcome model.

CREATE TABLE IF NOT EXISTS stage3_treatment_policy_versions (
  treatment_policy_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  policy_kind TEXT NOT NULL CHECK (policy_kind IN ('OUTLIER', 'IMPUTATION')),
  policy_version INTEGER NOT NULL CHECK (policy_version > 0),
  policy_status TEXT NOT NULL CHECK (policy_status IN ('DRAFT', 'ADOPTED')),
  prior_policy_id TEXT,
  adopted_from_policy_id TEXT,
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
  global_method TEXT NOT NULL,
  policy_json TEXT NOT NULL,
  fitting_rule_json TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  content_sha256 TEXT NOT NULL,
  created_by_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (project_id, policy_kind, authority_review_digest, policy_version)
);

CREATE INDEX IF NOT EXISTS idx_stage3_treatment_policy_current
  ON stage3_treatment_policy_versions(
    project_id, policy_kind, authority_review_digest,
    policy_version DESC, created_at DESC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_treatment_policy_no_update
BEFORE UPDATE ON stage3_treatment_policy_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 treatment policy versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_treatment_policy_no_delete
BEFORE DELETE ON stage3_treatment_policy_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 treatment policy versions are immutable');
END;

CREATE TABLE IF NOT EXISTS stage3_treatment_policy_events (
  treatment_policy_event_id TEXT PRIMARY KEY,
  treatment_policy_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  policy_kind TEXT NOT NULL CHECK (policy_kind IN ('OUTLIER', 'IMPUTATION')),
  policy_version INTEGER NOT NULL CHECK (policy_version > 0),
  event_type TEXT NOT NULL CHECK (
    event_type IN (
      'DRAFT_CREATED', 'DRAFT_UPDATED', 'POLICY_ADOPTED', 'POLICY_SUPERSEDED',
      'ROW_EXCLUSION_SELECTED', 'VARIABLE_DROP_SELECTED',
      'SOURCE_FAILURE_OVERRIDE_SELECTED'
    )
  ),
  actor_user_id TEXT NOT NULL,
  prior_policy_id TEXT,
  authority_review_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_stage3_treatment_policy_events
  ON stage3_treatment_policy_events(
    project_id, policy_kind, authority_review_digest,
    policy_version ASC, created_at ASC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_treatment_policy_events_no_update
BEFORE UPDATE ON stage3_treatment_policy_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 treatment policy events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_treatment_policy_events_no_delete
BEFORE DELETE ON stage3_treatment_policy_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 treatment policy events are append-only');
END;

CREATE TABLE IF NOT EXISTS stage3_predicted_imputation_previews (
  predicted_preview_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  variable_name TEXT NOT NULL,
  registration_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  authority_review_digest TEXT NOT NULL,
  development_end_date TEXT NOT NULL,
  final_oot_start_date TEXT NOT NULL,
  specification_json TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  seed INTEGER NOT NULL,
  requested_by_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (
    project_id, variable_name, authority_review_digest,
    artifact_sha256
  )
);

CREATE INDEX IF NOT EXISTS idx_stage3_predicted_preview_history
  ON stage3_predicted_imputation_previews(
    project_id, variable_name, authority_review_digest, created_at DESC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_predicted_preview_no_update
BEFORE UPDATE ON stage3_predicted_imputation_previews
BEGIN
  SELECT RAISE(ABORT, 'stage3 predicted-imputation previews are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_predicted_preview_no_delete
BEFORE DELETE ON stage3_predicted_imputation_previews
BEGIN
  SELECT RAISE(ABORT, 'stage3 predicted-imputation previews are immutable');
END;

CREATE TABLE IF NOT EXISTS stage3_predicted_imputation_preview_events (
  predicted_preview_event_id TEXT PRIMARY KEY,
  predicted_preview_id TEXT,
  project_id TEXT NOT NULL,
  variable_name TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (
    event_type IN ('PREDICTED_PREVIEW_REQUESTED', 'PREDICTED_PREVIEW_COMPLETED')
  ),
  actor_user_id TEXT NOT NULL,
  authority_review_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_stage3_predicted_preview_events
  ON stage3_predicted_imputation_preview_events(
    project_id, variable_name, authority_review_digest, created_at ASC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_predicted_preview_events_no_update
BEFORE UPDATE ON stage3_predicted_imputation_preview_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 predicted-imputation preview events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_predicted_preview_events_no_delete
BEFORE DELETE ON stage3_predicted_imputation_preview_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 predicted-imputation preview events are append-only');
END;

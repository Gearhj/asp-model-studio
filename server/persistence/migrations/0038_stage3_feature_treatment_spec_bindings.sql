-- Immutable receipts binding one reconciled Stage 3 feature-treatment
-- specification to its exact OUTLIER and IMPUTATION policy drafts.  The
-- manifest is a review/compilation authority only: it neither mutates Gold nor
-- authorizes model fitting.  Adoption, when implemented, must append a new
-- ADOPTED receipt and exact ADOPTED child policies.

CREATE TABLE IF NOT EXISTS stage3_feature_treatment_spec_versions (
  feature_treatment_spec_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  specification_version INTEGER NOT NULL CHECK (specification_version > 0),
  specification_status TEXT NOT NULL CHECK (
    specification_status IN ('DRAFT', 'ADOPTED')
  ),
  prior_specification_id TEXT,
  adopted_from_specification_id TEXT,
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
  final_oot_identity_json TEXT NOT NULL DEFAULT '{}',
  source_workbook_filename TEXT NOT NULL,
  source_workbook_sha256 TEXT NOT NULL CHECK (length(source_workbook_sha256) = 64),
  feature_inventory_sha256 TEXT NOT NULL CHECK (length(feature_inventory_sha256) = 64),
  manifest_id TEXT NOT NULL,
  manifest_name TEXT NOT NULL,
  compiler_version TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
  manifest_json TEXT NOT NULL,
  outlier_policy_id TEXT NOT NULL,
  outlier_policy_checksum TEXT NOT NULL CHECK (length(outlier_policy_checksum) = 64),
  missing_policy_id TEXT NOT NULL,
  missing_policy_checksum TEXT NOT NULL CHECK (length(missing_policy_checksum) = 64),
  notes TEXT NOT NULL DEFAULT '',
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  created_by_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (project_id, authority_review_digest, specification_version),
  FOREIGN KEY (outlier_policy_id)
    REFERENCES stage3_treatment_policy_versions(treatment_policy_id),
  FOREIGN KEY (missing_policy_id)
    REFERENCES stage3_treatment_policy_versions(treatment_policy_id)
);

CREATE INDEX IF NOT EXISTS idx_stage3_feature_treatment_spec_current
  ON stage3_feature_treatment_spec_versions (
    project_id, authority_review_digest,
    specification_version DESC, created_at DESC
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_stage3_feature_treatment_spec_adoption_once
  ON stage3_feature_treatment_spec_versions (adopted_from_specification_id)
  WHERE specification_status = 'ADOPTED'
    AND adopted_from_specification_id IS NOT NULL;

-- The receipt must bind exact immutable policies from the same project and
-- authority.  Draft receipts may bind only drafts; a future adopted receipt
-- must bind only adopted policies.  Duplicated checksums make the receipt
-- independently auditable and are verified here at insertion time.
CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_treatment_spec_policy_binding
BEFORE INSERT ON stage3_feature_treatment_spec_versions
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM stage3_treatment_policy_versions
    WHERE treatment_policy_id = NEW.outlier_policy_id
      AND project_id = NEW.project_id
      AND authority_review_digest = NEW.authority_review_digest
      AND registration_id = NEW.registration_id
      AND dataset_version_id = NEW.dataset_version_id
      AND activation_revision = NEW.activation_revision
      AND source_dataset_id = NEW.source_dataset_id
      AND source_manifest_sha = NEW.source_manifest_sha
      AND gold_manifest_sha = NEW.gold_manifest_sha
      AND contextual_manifest_sha = NEW.contextual_manifest_sha
      AND development_start_date = NEW.development_start_date
      AND development_end_date = NEW.development_end_date
      AND development_rows = NEW.development_rows
      AND final_oot_start_date = NEW.final_oot_start_date
      AND final_oot_end_date = NEW.final_oot_end_date
      AND final_oot_rows = NEW.final_oot_rows
      AND policy_kind = 'OUTLIER'
      AND content_sha256 = NEW.outlier_policy_checksum
      AND policy_status = NEW.specification_status
  ) THEN RAISE(ABORT, 'stage3 combined-spec outlier policy authority mismatch') END;

  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM stage3_treatment_policy_versions
    WHERE treatment_policy_id = NEW.missing_policy_id
      AND project_id = NEW.project_id
      AND authority_review_digest = NEW.authority_review_digest
      AND registration_id = NEW.registration_id
      AND dataset_version_id = NEW.dataset_version_id
      AND activation_revision = NEW.activation_revision
      AND source_dataset_id = NEW.source_dataset_id
      AND source_manifest_sha = NEW.source_manifest_sha
      AND gold_manifest_sha = NEW.gold_manifest_sha
      AND contextual_manifest_sha = NEW.contextual_manifest_sha
      AND development_start_date = NEW.development_start_date
      AND development_end_date = NEW.development_end_date
      AND development_rows = NEW.development_rows
      AND final_oot_start_date = NEW.final_oot_start_date
      AND final_oot_end_date = NEW.final_oot_end_date
      AND final_oot_rows = NEW.final_oot_rows
      AND policy_kind = 'IMPUTATION'
      AND content_sha256 = NEW.missing_policy_checksum
      AND policy_status = NEW.specification_status
  ) THEN RAISE(ABORT, 'stage3 combined-spec missing policy authority mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_treatment_spec_no_update
BEFORE UPDATE ON stage3_feature_treatment_spec_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-treatment specification versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_treatment_spec_no_delete
BEFORE DELETE ON stage3_feature_treatment_spec_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-treatment specification versions are immutable');
END;

CREATE TABLE IF NOT EXISTS stage3_feature_treatment_spec_events (
  feature_treatment_spec_event_id TEXT PRIMARY KEY,
  feature_treatment_spec_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  specification_version INTEGER NOT NULL CHECK (specification_version > 0),
  event_type TEXT NOT NULL CHECK (
    event_type IN (
      'DRAFT_CREATED', 'DRAFT_REVISED',
      'SPECIFICATION_ADOPTED', 'SPECIFICATION_SUPERSEDED'
    )
  ),
  actor_user_id TEXT NOT NULL,
  prior_specification_id TEXT,
  authority_review_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (feature_treatment_spec_id)
    REFERENCES stage3_feature_treatment_spec_versions(feature_treatment_spec_id)
);

CREATE INDEX IF NOT EXISTS idx_stage3_feature_treatment_spec_events
  ON stage3_feature_treatment_spec_events (
    project_id, authority_review_digest,
    specification_version ASC, created_at ASC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_treatment_spec_events_no_update
BEFORE UPDATE ON stage3_feature_treatment_spec_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-treatment specification events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_feature_treatment_spec_events_no_delete
BEFORE DELETE ON stage3_feature_treatment_spec_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 feature-treatment specification events are append-only');
END;

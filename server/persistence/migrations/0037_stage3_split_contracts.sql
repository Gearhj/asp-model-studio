-- Immutable, project-bound Stage 3 Split & Balance contracts.  A draft and
-- its registered successor are separate append-only records.  Registration
-- never mutates Gold, opens final OOT targets, or starts model activity.

CREATE TABLE IF NOT EXISTS stage3_split_contract_versions (
  split_contract_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  contract_version INTEGER NOT NULL CHECK (contract_version > 0),
  contract_status TEXT NOT NULL CHECK (contract_status IN ('DRAFT', 'REGISTERED')),
  prior_contract_id TEXT,
  registered_from_contract_id TEXT,
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
  split_mode TEXT NOT NULL CHECK (split_mode IN ('AUTOMATIC', 'MANUAL')),
  fold_count INTEGER NOT NULL CHECK (fold_count > 0),
  contract_json TEXT NOT NULL,
  selected_feature_set_ids_json TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  content_sha256 TEXT NOT NULL,
  created_by_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (project_id, authority_review_digest, contract_version)
);

CREATE INDEX IF NOT EXISTS idx_stage3_split_contract_current
  ON stage3_split_contract_versions (
    project_id, authority_review_digest, contract_version DESC, created_at DESC
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_stage3_split_contract_registration_once
  ON stage3_split_contract_versions (registered_from_contract_id)
  WHERE contract_status = 'REGISTERED' AND registered_from_contract_id IS NOT NULL;

-- Exact project-bound feature-set authority for each split version.  The
-- checksum is duplicated intentionally so an auditor need not infer which
-- immutable feature-set content a split selected.  The trigger below verifies
-- it against the registered feature-set record at insert time.
CREATE TABLE IF NOT EXISTS stage3_split_contract_feature_sets (
  split_contract_id TEXT NOT NULL,
  feature_set_id TEXT NOT NULL,
  feature_set_checksum TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
  PRIMARY KEY (split_contract_id, feature_set_id),
  UNIQUE (split_contract_id, ordinal),
  FOREIGN KEY (split_contract_id)
    REFERENCES stage3_split_contract_versions(split_contract_id),
  FOREIGN KEY (feature_set_id)
    REFERENCES stage3_feature_set_versions(feature_set_id)
);

CREATE TRIGGER IF NOT EXISTS trg_stage3_split_feature_set_checksum
BEFORE INSERT ON stage3_split_contract_feature_sets
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM stage3_feature_set_versions
    WHERE feature_set_id = NEW.feature_set_id
      AND content_sha256 = NEW.feature_set_checksum
      AND feature_set_status = 'REGISTERED'
  ) THEN RAISE(ABORT, 'stage3 split feature-set authority mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_split_feature_sets_no_update
BEFORE UPDATE ON stage3_split_contract_feature_sets
BEGIN
  SELECT RAISE(ABORT, 'stage3 split feature-set bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_split_feature_sets_no_delete
BEFORE DELETE ON stage3_split_contract_feature_sets
BEGIN
  SELECT RAISE(ABORT, 'stage3 split feature-set bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_split_contract_no_update
BEFORE UPDATE ON stage3_split_contract_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 split contract versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_split_contract_no_delete
BEFORE DELETE ON stage3_split_contract_versions
BEGIN
  SELECT RAISE(ABORT, 'stage3 split contract versions are immutable');
END;

CREATE TABLE IF NOT EXISTS stage3_split_contract_events (
  split_contract_event_id TEXT PRIMARY KEY,
  split_contract_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  contract_version INTEGER NOT NULL CHECK (contract_version > 0),
  event_type TEXT NOT NULL CHECK (
    event_type IN (
      'DRAFT_CREATED', 'DRAFT_UPDATED', 'CONTRACT_REGISTERED',
      'CONTRACT_SUPERSEDED'
    )
  ),
  actor_user_id TEXT NOT NULL,
  prior_contract_id TEXT,
  authority_review_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_stage3_split_contract_events
  ON stage3_split_contract_events (
    project_id, authority_review_digest, contract_version ASC, created_at ASC
  );

CREATE TRIGGER IF NOT EXISTS trg_stage3_split_contract_events_no_update
BEFORE UPDATE ON stage3_split_contract_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 split contract events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_stage3_split_contract_events_no_delete
BEFORE DELETE ON stage3_split_contract_events
BEGIN
  SELECT RAISE(ABORT, 'stage3 split contract events are append-only');
END;

-- Exact-version Data Acquisition Special-Value Review authority.
--
-- Browser persistence is never authoritative for this contract. One durable
-- row is maintained for each project + dataset + dataset-version identity,
-- while append-only events preserve every analytical refresh and reviewer
-- decision revision.

CREATE TABLE IF NOT EXISTS special_value_reviews (
  special_value_review_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  activation_revision INTEGER NOT NULL CHECK (activation_revision > 0),
  predictor_authorization_id TEXT NOT NULL,
  target_contract_id TEXT NOT NULL,
  detection_fingerprint TEXT NOT NULL,
  detection_json TEXT NOT NULL,
  decisions_json TEXT NOT NULL DEFAULT '[]',
  reviewer_rationale TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (
    status IN (
      'not_required', 'not_started', 'in_review',
      'ready_for_confirmation', 'confirmed'
    )
  ),
  detected_count INTEGER NOT NULL CHECK (detected_count >= 0),
  reviewed_count INTEGER NOT NULL CHECK (reviewed_count >= 0),
  open_count INTEGER NOT NULL CHECK (open_count >= 0),
  blocks_confirmation INTEGER NOT NULL CHECK (blocks_confirmation IN (0, 1)),
  blocks_continuation INTEGER NOT NULL CHECK (blocks_continuation IN (0, 1)),
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  confirmed_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  confirmed_at TEXT,
  UNIQUE (project_id, dataset_id, dataset_version_id),
  CHECK (reviewed_count + open_count = detected_count),
  CHECK (status <> 'confirmed' OR (open_count = 0 AND blocks_continuation = 0))
);

CREATE INDEX IF NOT EXISTS idx_special_value_review_exact_identity
  ON special_value_reviews(project_id, dataset_id, dataset_version_id);

CREATE INDEX IF NOT EXISTS idx_special_value_review_status
  ON special_value_reviews(project_id, status, updated_at DESC);

-- The exact dataset scope may never be reassigned. A new dataset version
-- receives a different row. Upstream analytical-lineage changes on the same
-- exact version are handled only as revisioned invalidations by the repository.
CREATE TRIGGER IF NOT EXISTS trg_special_value_review_scope_immutable
BEFORE UPDATE ON special_value_reviews
WHEN
  NEW.special_value_review_id IS NOT OLD.special_value_review_id OR
  NEW.project_id IS NOT OLD.project_id OR
  NEW.dataset_id IS NOT OLD.dataset_id OR
  NEW.dataset_version_id IS NOT OLD.dataset_version_id OR
  NEW.created_by IS NOT OLD.created_by OR
  NEW.created_at IS NOT OLD.created_at
BEGIN
  SELECT RAISE(ABORT, 'special-value review scope is immutable');
END;

CREATE TABLE IF NOT EXISTS special_value_review_events (
  special_value_review_event_id TEXT PRIMARY KEY,
  special_value_review_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  event_type TEXT NOT NULL CHECK (
    event_type IN ('detection_initialized', 'detection_refreshed', 'draft_saved', 'confirmed')
  ),
  actor_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_special_value_review_events_identity
  ON special_value_review_events(
    project_id, dataset_id, dataset_version_id, revision ASC
  );

CREATE TRIGGER IF NOT EXISTS trg_special_value_review_events_no_update
BEFORE UPDATE ON special_value_review_events
BEGIN
  SELECT RAISE(ABORT, 'special-value review events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_special_value_review_events_no_delete
BEFORE DELETE ON special_value_review_events
BEGIN
  SELECT RAISE(ABORT, 'special-value review events are append-only');
END;

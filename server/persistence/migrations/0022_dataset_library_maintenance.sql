-- Durable, append-only audit records for offline Dataset Library maintenance.
--
-- Recovery metadata intentionally lives outside the JSON registry so an
-- operator can prove what was inspected and changed even when registry
-- metadata was the damaged store.  These rows never grant Dataset Library
-- access and never create an active modeling dataset selection.

CREATE TABLE IF NOT EXISTS dataset_library_maintenance_events (
  maintenance_event_id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  operation_type TEXT NOT NULL
    CHECK (operation_type IN ('reconcile', 'recover', 'verify', 'quarantine')),
  event_status TEXT NOT NULL
    CHECK (event_status IN ('started', 'complete', 'failed', 'refused')),
  actor_user_id TEXT NOT NULL,
  project_id TEXT,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence_report_sha256 TEXT NOT NULL,
  backup_manifest_sha256 TEXT,
  registry_before_sha256 TEXT,
  registry_after_sha256 TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

-- Every attempt and state transition is append-only.  In particular, a retry
-- must never overwrite the prior attempt's started/failed evidence.
CREATE INDEX IF NOT EXISTS idx_dataset_library_maintenance_operation_event
  ON dataset_library_maintenance_events(operation_id, event_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dataset_library_maintenance_attempt
  ON dataset_library_maintenance_events(attempt_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_dataset_library_maintenance_identity
  ON dataset_library_maintenance_events(
    dataset_id,
    dataset_version_id,
    created_at DESC
  );

CREATE INDEX IF NOT EXISTS idx_dataset_library_maintenance_project
  ON dataset_library_maintenance_events(project_id, created_at DESC);

-- Durable project-to-dataset authorization and exact active modeling version.
--
-- Dataset Library metadata and immutable artifacts remain in the Dataset
-- Library store.  These tables persist the project-scoped authorization and
-- active-selection contracts that must survive a backend restart.  A workflow
-- checkpoint is only a cache and is deliberately not referenced here.

CREATE TABLE IF NOT EXISTS project_dataset_links (
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  dataset_id TEXT NOT NULL,
  link_status TEXT NOT NULL DEFAULT 'active'
    CHECK (link_status IN ('active', 'unlinked', 'revoked')),
  linked_by TEXT NOT NULL,
  linked_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (project_id, dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_project_dataset_links_status
  ON project_dataset_links(project_id, link_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS active_modeling_dataset_versions (
  project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  activation_revision INTEGER NOT NULL CHECK (activation_revision > 0),
  activation_status TEXT NOT NULL DEFAULT 'active'
    CHECK (activation_status IN ('active', 'inactive', 'contradictory')),
  activated_by TEXT NOT NULL,
  activated_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (project_id, dataset_id)
    REFERENCES project_dataset_links(project_id, dataset_id)
    ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_active_modeling_exact_revision
  ON active_modeling_dataset_versions(project_id, activation_revision);

CREATE INDEX IF NOT EXISTS idx_active_modeling_dataset_version
  ON active_modeling_dataset_versions(dataset_id, dataset_version_id, activation_status);

-- Activation events intentionally do not cascade with project deletion.  They
-- are the durable audit trail proving which exact version was selected and by
-- whom even after the project workspace itself is retired.
CREATE TABLE IF NOT EXISTS project_dataset_activation_events (
  activation_event_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT,
  activation_revision INTEGER,
  event_type TEXT NOT NULL,
  event_status TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_project_dataset_activation_events
  ON project_dataset_activation_events(project_id, created_at DESC);

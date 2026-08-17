-- Metadata-only registry for immutable sports identity companions and exact
-- join-audit evidence. Physical exchange paths, alias rows, dimension rows,
-- and prediction/model bytes are deliberately excluded.

CREATE TABLE IF NOT EXISTS sports_identity_bridge_registrations (
  bridge_registration_id TEXT PRIMARY KEY,
  contract_name TEXT NOT NULL,
  contract_version TEXT NOT NULL,
  bridge_manifest_id TEXT NOT NULL UNIQUE,
  bridge_manifest_sha TEXT NOT NULL UNIQUE,
  bridge_package_id TEXT NOT NULL UNIQUE,
  parent_dataset_registration_id TEXT NOT NULL
    REFERENCES sports_dataset_registrations(registration_id) ON DELETE RESTRICT,
  parent_project_id TEXT NOT NULL
    REFERENCES sports_research_projects(project_id) ON DELETE RESTRICT,
  parent_manifest_sha TEXT NOT NULL,
  parent_partition_authority_sha TEXT NOT NULL,
  alias_row_authority_sha TEXT NOT NULL,
  dimension_row_authority_sha TEXT NOT NULL,
  validation_report_sha TEXT NOT NULL,
  logical_bridge_root TEXT NOT NULL,
  validation_status TEXT NOT NULL CHECK (validation_status IN ('PASS', 'INVALID')),
  package_file_count INTEGER NOT NULL CHECK (package_file_count >= 0),
  package_byte_count INTEGER NOT NULL CHECK (package_byte_count >= 0),
  alias_count INTEGER NOT NULL CHECK (alias_count >= 0),
  active_player_count INTEGER NOT NULL CHECK (active_player_count >= 0),
  governed_active_player_count INTEGER NOT NULL CHECK (governed_active_player_count >= 0),
  primary_portable_player_count INTEGER NOT NULL CHECK (primary_portable_player_count >= 0),
  primary_governed_player_count INTEGER NOT NULL CHECK (primary_governed_player_count >= 0),
  namespace_count INTEGER NOT NULL CHECK (namespace_count >= 0),
  join_contract_count INTEGER NOT NULL CHECK (join_contract_count >= 0),
  join_reference_count INTEGER NOT NULL CHECK (join_reference_count >= 0),
  rights_status TEXT NOT NULL,
  namespace_evidence_json TEXT NOT NULL DEFAULT '[]',
  y_minus_one_coverage_json TEXT NOT NULL DEFAULT '[]',
  rights_json TEXT NOT NULL DEFAULT '{}',
  limitations_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  registered_at TEXT NOT NULL,
  last_validated_at TEXT NOT NULL,
  registered_by TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sports_identity_bridge_active_parent
  ON sports_identity_bridge_registrations(parent_dataset_registration_id, bridge_manifest_sha)
  WHERE active = 1;

CREATE INDEX IF NOT EXISTS idx_sports_identity_bridge_parent_project
  ON sports_identity_bridge_registrations(parent_project_id, active, registered_at);

CREATE TABLE IF NOT EXISTS sports_identity_join_audits (
  join_audit_id TEXT PRIMARY KEY,
  bridge_registration_id TEXT NOT NULL
    REFERENCES sports_identity_bridge_registrations(bridge_registration_id) ON DELETE CASCADE,
  artifact_sha TEXT NOT NULL UNIQUE,
  artifact_byte_count INTEGER NOT NULL CHECK (artifact_byte_count >= 0),
  logical_uri TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
  total_references INTEGER NOT NULL CHECK (total_references >= 0),
  resolved_references INTEGER NOT NULL CHECK (resolved_references >= 0),
  unresolved_references INTEGER NOT NULL CHECK (unresolved_references >= 0),
  ambiguous_references INTEGER NOT NULL CHECK (ambiguous_references >= 0),
  multiply_mapped_references INTEGER NOT NULL CHECK (multiply_mapped_references >= 0),
  mapping_rate REAL NOT NULL CHECK (mapping_rate >= 0.0 AND mapping_rate <= 1.0),
  evidence_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  code_revision TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sports_identity_join_audit_bridge
  ON sports_identity_join_audits(bridge_registration_id, created_at);

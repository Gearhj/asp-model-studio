-- ATLAS Phase 2B1: durable, recoverable Model Registry publication.
--
-- Existing rows predate staged verification and exact lineage enforcement.
-- They are deliberately quarantined as legacy-unresolved; this migration does
-- not guess at an artifact, checksum, dataset version, or project identity.

ALTER TABLE models ADD COLUMN current_version_generation INTEGER NOT NULL DEFAULT 0;
ALTER TABLE models ADD COLUMN champion_updated_at TEXT;
ALTER TABLE models ADD COLUMN champion_updated_by TEXT;

ALTER TABLE model_versions ADD COLUMN artifact_size_bytes INTEGER;
ALTER TABLE model_versions ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN artifact_verified_at TEXT;
ALTER TABLE model_versions ADD COLUMN finalized_at TEXT;
ALTER TABLE model_versions ADD COLUMN idempotency_key TEXT;
ALTER TABLE model_versions ADD COLUMN publication_fingerprint TEXT;
ALTER TABLE model_versions ADD COLUMN lineage_status TEXT NOT NULL DEFAULT 'legacy_unresolved';
ALTER TABLE model_versions ADD COLUMN quarantine_reason TEXT;
ALTER TABLE model_versions ADD COLUMN quarantined_at TEXT;
ALTER TABLE model_versions ADD COLUMN candidate_id TEXT;
ALTER TABLE model_versions ADD COLUMN evaluation_package_id TEXT;
ALTER TABLE model_versions ADD COLUMN target_name TEXT;
ALTER TABLE model_versions ADD COLUMN validation_design_id TEXT;
ALTER TABLE model_versions ADD COLUMN split_id TEXT;
ALTER TABLE model_versions ADD COLUMN candidate_contract_hash TEXT;
ALTER TABLE model_versions ADD COLUMN model_contract_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE model_versions ADD COLUMN previous_champion_version_id TEXT;

UPDATE model_versions
SET publication_status = 'legacy_unresolved',
    lineage_status = 'legacy_unresolved',
    quarantine_reason = COALESCE(
      quarantine_reason,
      'Legacy model version predates verified atomic publication; exact recovery is blocked.'
    ),
    quarantined_at = COALESCE(quarantined_at, created_at)
WHERE publication_status = 'legacy_unresolved'
   OR lineage_status = 'legacy_unresolved';

UPDATE models
SET current_version_id = NULL,
    current_version_generation = current_version_generation + 1,
    champion_updated_at = updated_at,
    champion_updated_by = 'migration:0017'
WHERE current_version_id IN (
  SELECT model_version_id
  FROM model_versions
  WHERE publication_status = 'legacy_unresolved'
     OR lineage_status = 'legacy_unresolved'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_project_idempotency
  ON model_versions(project_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_model_versions_publication
  ON model_versions(project_id, publication_status, lineage_status);

CREATE INDEX IF NOT EXISTS idx_model_versions_exact_candidate
  ON model_versions(project_id, candidate_id, training_run_id);

CREATE INDEX IF NOT EXISTS idx_model_versions_evaluation_package
  ON model_versions(project_id, evaluation_package_id);

CREATE INDEX IF NOT EXISTS idx_model_versions_split
  ON model_versions(project_id, validation_design_id, split_id);

CREATE INDEX IF NOT EXISTS idx_model_versions_exact_current_context
  ON model_versions(
    project_id, dataset_id, dataset_version_id, target_name,
    publication_status, lineage_status
  );

CREATE INDEX IF NOT EXISTS idx_models_current_version
  ON models(current_version_id);

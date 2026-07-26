-- ATLAS EDA Governed Analysis Scope, Phase 1 -- target finding scope.
--
-- 0014 allowed dataset_id and dataset_version_id to default to '', so a finding
-- written against an unregistered workspace upload was stored with blank
-- governance identity while the surrounding comments and UI implied every
-- finding was pinned to an immutable dataset version. That is the honesty
-- defect this migration closes.
--
-- A finding now declares its scope explicitly:
--
--   governed_version  -- pinned to a resolved, authorized, immutable version
--   workspace_draft   -- pinned to a workspace dataset fingerprint, not a version
--   legacy_unscoped   -- written before this contract existed; identity unknown
--
-- Existing rows are classified conservatively: a row is only backfilled as
-- governed when it actually carries BOTH a dataset id and a version id. Blank
-- rows become legacy_unscoped and are labeled as such in the UI -- they are
-- never silently reinterpreted as governed.
ALTER TABLE target_findings ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy_unscoped';
ALTER TABLE target_findings ADD COLUMN workspace_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE target_findings ADD COLUMN artifact_checksum TEXT NOT NULL DEFAULT '';

-- Controlled carry-forward provenance: a governed finding copied from a draft
-- keeps a pointer to the draft it came from. The draft record is never mutated.
ALTER TABLE target_findings ADD COLUMN promoted_from_finding_id TEXT;
ALTER TABLE target_findings ADD COLUMN promoted_at TEXT;

UPDATE target_findings
   SET scope_mode = CASE
       WHEN COALESCE(dataset_id, '') <> '' AND COALESCE(dataset_version_id, '') <> ''
         THEN 'governed_version'
       ELSE 'legacy_unscoped'
   END;

CREATE INDEX IF NOT EXISTS idx_target_findings_scope_mode
  ON target_findings(project_id, scope_mode, target);
CREATE INDEX IF NOT EXISTS idx_target_findings_workspace
  ON target_findings(project_id, workspace_fingerprint, target);

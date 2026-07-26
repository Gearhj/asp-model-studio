-- ATLAS EDA Target Intelligence, Phase 1 -- durable target findings.
--
-- The EDA Findings tab previously stored a single free-text commentary blob in
-- one unscoped browser key ("atlas-predictive-eda-findings-v2"), so a finding
-- did not survive a different browser, a different user, or even a different
-- project in the same tab, and it carried no record of WHICH dataset version
-- and target it was written against.
--
-- A target finding is a governance record: it must name the immutable
-- (dataset, version, target) it describes, the analysis that produced it, its
-- author, and its review status. ON DELETE CASCADE follows the evidence_artifacts
-- precedent in 0001_initial.sql -- a finding has no meaning without its project.
CREATE TABLE IF NOT EXISTS target_findings (
  target_finding_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  dataset_id TEXT NOT NULL DEFAULT '',
  dataset_version_id TEXT NOT NULL DEFAULT '',
  target TEXT NOT NULL DEFAULT '',
  analysis_type TEXT NOT NULL DEFAULT 'target_intelligence',
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'review',
  status TEXT NOT NULL DEFAULT 'open',
  created_by_user_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_target_findings_scope
  ON target_findings(project_id, dataset_id, dataset_version_id, target);
CREATE INDEX IF NOT EXISTS idx_target_findings_updated_at
  ON target_findings(updated_at DESC);

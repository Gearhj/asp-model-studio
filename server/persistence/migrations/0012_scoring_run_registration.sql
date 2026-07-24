-- Visual Intelligence Production Integration, Phase K: ScoringRun-to-Scored-Dataset
-- cross-link. Additive columns only -- existing scoring_runs rows are unaffected
-- (all new columns default to NULL / 'not_registered', matching every existing
-- row's true state: not yet registered).
ALTER TABLE scoring_runs ADD COLUMN output_dataset_id TEXT;
ALTER TABLE scoring_runs ADD COLUMN output_dataset_version_id TEXT;
ALTER TABLE scoring_runs ADD COLUMN registration_status TEXT NOT NULL DEFAULT 'not_registered';
ALTER TABLE scoring_runs ADD COLUMN registered_at TEXT;
ALTER TABLE scoring_runs ADD COLUMN registered_by TEXT;

CREATE INDEX IF NOT EXISTS idx_scoring_runs_output_dataset ON scoring_runs(output_dataset_id);

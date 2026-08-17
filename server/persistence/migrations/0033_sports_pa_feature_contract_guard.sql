-- Enforce the frozen MLB_PA_FEATURE_VIEW_V1 semantic authority for databases
-- that applied the initial 0032 length-only check before commit closeout.

CREATE TRIGGER IF NOT EXISTS trg_sports_pa_feature_contract_insert
BEFORE INSERT ON sports_pa_feature_views
WHEN NEW.contract_sha <> 'fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e'
BEGIN
  SELECT RAISE(ABORT, 'sports_pa_feature_views contract_sha differs');
END;

CREATE TRIGGER IF NOT EXISTS trg_sports_pa_feature_contract_update
BEFORE UPDATE OF contract_sha ON sports_pa_feature_views
WHEN NEW.contract_sha <> 'fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e'
BEGIN
  SELECT RAISE(ABORT, 'sports_pa_feature_views contract_sha differs');
END;

-- Force every row that predates this guard through the update trigger. A
-- mismatched authority aborts the migration transaction instead of becoming a
-- silently grandfathered feature view.
UPDATE sports_pa_feature_views SET contract_sha = contract_sha;

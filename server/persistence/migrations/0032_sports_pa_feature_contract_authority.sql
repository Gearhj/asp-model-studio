-- Persist the semantic feature-contract authority separately from the runtime
-- artifact-envelope digest. The exact value is frozen for MLB_PA_FEATURE_VIEW_V1.

ALTER TABLE sports_pa_feature_views
  ADD COLUMN contract_sha TEXT NOT NULL
    DEFAULT 'fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e'
    CHECK (contract_sha = 'fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e');

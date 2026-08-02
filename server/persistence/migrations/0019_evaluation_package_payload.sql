-- Preserve the complete immutable Evaluation package for exact recovery after
-- a backend restart.  The governance summary columns added in 0018 remain
-- queryable; this payload is the byte-stable evidence object consumed by
-- Interpretation and Model Registry promotion.

ALTER TABLE evaluation_packages
  ADD COLUMN package_payload_json TEXT NOT NULL DEFAULT '{}';


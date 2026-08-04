-- Preserve append-only Analysis Partition and predictor-authorization records
-- during ordinary operations while allowing the project's explicit physical
-- deletion to execute its declared ON DELETE CASCADE atomically.
--
-- SQLite evaluates these child triggers after the parent row has left the
-- projects table.  A direct child DELETE still sees its live owning project
-- and fails with the original governed error.  Immutable event ledgers do not
-- have cascade foreign keys and therefore survive project retirement.

DROP TRIGGER IF EXISTS trg_analysis_partitions_no_delete;
CREATE TRIGGER trg_analysis_partitions_no_delete
BEFORE DELETE ON analysis_partitions
WHEN EXISTS (
  SELECT 1 FROM projects WHERE project_id = OLD.project_id
)
BEGIN
  SELECT RAISE(ABORT, 'analysis partitions are append-only');
END;

DROP TRIGGER IF EXISTS trg_predictor_authorization_no_delete;
CREATE TRIGGER trg_predictor_authorization_no_delete
BEFORE DELETE ON predictor_authorization_manifests
WHEN EXISTS (
  SELECT 1 FROM projects WHERE project_id = OLD.project_id
)
BEGIN
  SELECT RAISE(ABORT, 'predictor authorization manifests are append-only');
END;

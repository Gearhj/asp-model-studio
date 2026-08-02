-- Enforce the immutable audit contract introduced after migration 0022.
-- This is intentionally a distinct migration: deployed databases may already
-- have recorded 0022 and therefore will never execute an edited 0022 file.

CREATE TRIGGER IF NOT EXISTS trg_dataset_library_maintenance_events_no_update
BEFORE UPDATE ON dataset_library_maintenance_events
BEGIN
  SELECT RAISE(ABORT, 'dataset_library_maintenance_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_dataset_library_maintenance_events_no_delete
BEFORE DELETE ON dataset_library_maintenance_events
BEGIN
  SELECT RAISE(ABORT, 'dataset_library_maintenance_events is append-only');
END;

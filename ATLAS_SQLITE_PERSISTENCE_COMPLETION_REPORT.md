# ATLAS SQLite Persistence Completion Report

Date: 2026-07-15

## Outcome

ATLAS now has a local server-backed SQLite persistence layer with additive migrations, centralized JSON handling, repository/service boundaries, authenticated CRUD APIs, and gradual frontend write-through integration. Existing browser persistence remains available as a compatibility and outage fallback.

The validated database is:

```text
C:\Users\james\ds-workflow-starter\server\data\atlas_local.db
```

The database file and SQLite WAL sidecars are ignored by git. `ATLAS_SQLITE_PATH` can override the location.

## Files Created

- `ATLAS_SQLITE_PERSISTENCE.md`
- `ATLAS_SQLITE_PERSISTENCE_COMPLETION_REPORT.md`
- `server/data/.gitignore`
- `server/persistence/__init__.py`
- `server/persistence/db.py`
- `server/persistence/schema.sql`
- `server/persistence/service.py`
- `server/persistence/persistence_router.py`
- `server/persistence/migrations/0001_initial.sql`
- `server/persistence/migrations/README.md`
- `server/persistence/repositories/__init__.py`
- `server/persistence/repositories/base_repository.py`
- `server/persistence/repositories/project_repository.py`
- `server/persistence/repositories/dataset_repository.py`
- `server/persistence/repositories/evidence_repository.py`
- `server/persistence/repositories/run_repository.py`
- `server/persistence/repositories/decision_journal_repository.py`
- `server/persistence/repositories/documentation_repository.py`
- `server/persistence/repositories/export_repository.py`
- `server/persistence/repositories/user_repository.py`
- `src/lib/serverPersistence.ts`
- `tests/sqlitePersistence.test.mjs`
- `tests/sqlite_persistence_backend_test.py`

## Files Modified

- `.gitignore`: ignores local SQLite files and sidecars.
- `package.json`: adds `test:sqlite-persistence`.
- `server/main.py`: initializes SQLite on startup, registers the persistence router, and keeps startup available when persistence is unavailable.
- `scripts/sync-atlas-clean-copy.ps1`: excludes SQLite databases and WAL sidecars from clean-copy synchronization.
- `src/lib/projectPersistence.ts`: adds database-specific save states.
- `src/lib/localProjects.ts`: mirrors normal, thin-fallback, rename, duplicate, and import saves while retaining local persistence.
- `src/lib/evidenceGraph.ts`: mirrors evidence creation and updates.
- `src/lib/modelDocumentation.ts`: mirrors documentation package state and generated exports.
- `src/lib/decisionJournal.ts`: mirrors decision journal records.
- `src/components/ProjectSaveStatus.tsx`: displays the four requested persistence outcomes.
- `src/steps/ModelDocumentationStudio.tsx`: supplies project context when recording documentation exports.
- `src/steps/WorkflowPlaceholderStep.tsx`: records generated workflow exports.
- `tests/persistence.test.mjs`: includes the new persistence client dependency in its isolated harness.
- `tests/openProjectRoute.test.mjs`: validates existing local-project compatibility with the write-through client present.
- `tests/regression.test.mjs`: includes the new persistence client dependency in the broad regression harness.

## Database Initialization

Backend startup now:

1. Resolves the configured database path.
2. Creates the parent folder and SQLite file when missing.
3. Enables foreign keys, a 10-second busy timeout, and WAL mode.
4. Bootstraps `schema_migrations` from `schema.sql`.
5. Applies unapplied, ordered SQL files from `server/persistence/migrations/`.
6. Records each migration filename and application time.
7. Logs the resolved path in local/development environments.
8. Catches persistence startup failures so legacy browser persistence remains usable.

No initialization or migration path drops existing tables or records.

## Tables Created

- `schema_migrations`
- `users`
- `projects`
- `workflow_state`
- `datasets`
- `dataset_versions`
- `evidence_artifacts`
- `run_records`
- `decision_journal`
- `documentation_packages`
- `export_artifacts`

All flexible payload fields use centralized, safe JSON serialization into SQLite `TEXT` columns. Row decoding is also centralized.

## API Endpoints Added

Public diagnostics:

- `GET /api/persistence/health`

Authenticated project persistence:

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}`
- `PUT /api/projects/{project_id}`
- `GET /api/projects/{project_id}/workflow-state`
- `PUT /api/projects/{project_id}/workflow-state`
- `GET /api/projects/{project_id}/evidence`
- `POST /api/projects/{project_id}/evidence`
- `PUT /api/projects/{project_id}/evidence/{evidence_id}`
- `GET /api/projects/{project_id}/runs`
- `POST /api/projects/{project_id}/runs`
- `GET /api/projects/{project_id}/decisions`
- `POST /api/projects/{project_id}/decisions`
- `GET /api/projects/{project_id}/documentation`
- `POST /api/projects/{project_id}/documentation`
- `GET /api/projects/{project_id}/exports`
- `POST /api/projects/{project_id}/exports`

Persistence driver errors are converted to controlled API responses. Record-integrity errors return a client-safe validation response; unavailable database errors return HTTP 503.

## Frontend Integration

Project snapshots remain saved locally first. ATLAS then queues a short, debounced database write for the project and workflow state. This covers ordinary project saves plus thin-snapshot recovery, rename, duplicate, and import paths.

The frontend also mirrors:

- evidence creation and evidence status updates;
- decision journal creation;
- documentation package creation and updates;
- workflow, evidence, and documentation export manifests.

The header save indicator now reports:

- `Local only`
- `Saved to ATLAS database`
- `Backend unavailable`
- `Save failed`

A failed backend write does not remove or invalidate the browser-local project.

## Tests Run

### Static and build validation

- `npx tsc -b --pretty false`: passed.
- `.venv Python compileall server/persistence server/main.py`: passed.
- `npm run build`: passed; 1,721 modules transformed.

The build retained existing informational warnings for stale browser compatibility data and chunks over 500 kB. These warnings are unrelated to SQLite persistence.

### Persistence tests

- `npm run test:sqlite-persistence`: passed.
  - Frontend persistence tests: 3 passed.
  - Backend SQLite tests: 6 passed.
  - Covered initialization, additive migration behavior, project create/read/update, workflow state, evidence, run records, decision records, documentation, exports, route-level health/reload, and unavailable-database fallback.
- `npm run test:persistence`: 9 passed.
- `npm run test:open-project`: 15 passed.
- `npm run test:regression`: 18 passed.

The Open Project and regression harnesses were updated only to transpile/mock the newly imported persistence client. Existing local-project behavior remained green.

### Runtime and browser validation

- Started the current FastAPI application with an empty/create-if-missing SQLite path.
- Confirmed `GET /api/persistence/health` returned `ok: true`, `engine: sqlite`, schema version `0001`, and all required tables.
- Opened an existing browser-saved optimization project from Recent Projects.
- Confirmed navigation returned to `/workflow/optimization/14`.
- Confirmed the visible header state changed from `Local only` to `Saved to ATLAS database`.
- Queried SQLite directly and confirmed project `atlas-mrlgel4o` plus workflow state `optimization-14` with all 14 completed steps.
- Reloaded the same project through `GET /api/projects/atlas-mrlgel4o` in an authenticated browser tab and confirmed the stored project payload.
- Stopped all validation backend/frontend processes after QA.

The repository-wide `git diff --check` still reports a pre-existing trailing space in `tests/evidenceGraph.test.mjs`. The persistence-scoped diff check passed; the unrelated file was not modified for this task.

## Known Limitations

- Recent Projects still reads the browser compatibility registry. SQLite projects can be listed/reloaded through the API, but backend-first Open Project reconciliation is deferred.
- Write-through synchronization is best effort and asynchronous. There is no durable browser outbox, retry scheduler, conflict resolution, or multi-device merge yet.
- Existing historical browser evidence, documentation, exports, and decisions are not automatically backfilled. New or subsequently updated records are mirrored.
- Dataset tables and repositories are available, but the existing Dataset Library has not been fully migrated to SQLite in this first pass.
- Delete APIs and retention workflows are not included.
- SQLite is appropriate for local/single-node development; production concurrency, encryption, backup, retention, and high availability require a managed database design.
- JSON payloads remain flexible `TEXT`, so frequently queried attributes should be normalized as production access patterns stabilize.
- The application-facing `users` table stores ownership references. Authentication remains in the separate ATLAS security store.

## SQL Server Migration Notes

The route layer calls a service, and the service calls domain repositories. Raw SQL is confined to repositories and migration files. A SQL Server version can preserve these interfaces while replacing the connection/transaction adapter and repository SQL dialect.

A production migration should:

1. Add a SQL Server connection provider with pooled connections and managed credentials.
2. Port parameterized repository statements to T-SQL or a shared query builder.
3. Adopt a production migration tool and release-controlled migration policy.
4. Map timestamp text to `datetime2` or `datetimeoffset`.
5. Keep JSON payloads in `NVARCHAR(MAX)` initially, then add JSON constraints or normalize high-value fields.
6. Backfill SQLite data through repository-level export/import rather than changing API consumers.
7. Add production encryption, backup, recovery, retention, audit, and least-privilege controls.

Full SQL Server support was intentionally not implemented in this phase.

## Clean-Copy Sync

`npm run sync:atlas` was run after validation on 2026-07-15. The sync completed successfully with Robocopy code 3 from:

```text
C:\Users\james\ds-workflow-starter
```

to:

```text
C:\Users\james\Projects\ATLAS\atlas-app
```

The completion report is followed by a final sync so this document and the database exclusions are present in the clean copy. Runtime `*.db`, `*.db-wal`, and `*.db-shm` files are excluded; the validation database remains only in the source workspace.

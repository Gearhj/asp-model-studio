# ATLAS Enterprise Foundation Overnight Report

Run completed: July 15-16, 2026  
Source workspace: `C:\Users\james\ds-workflow-starter`  
Clean synced copy: `C:\Users\james\Projects\ATLAS\atlas-app`

## 1. Executive Summary

ATLAS now has a tested local enterprise foundation for trusted private evaluation. The work hardened package-aware backend startup, local development identity, SQLite repositories, user attribution, audit logging, persisted evidence readiness, explicit export metadata, private demo safety messaging, tester feedback capture, database inspection, and guarded demo reset tooling.

The completed Transportation / Logistics Optimization project remains intact with `template_id = transportation_logistics`. Live API verification loaded that project with 14 completed workflow steps, 22 evidence artifacts, 5 run records, 1 complete documentation package at 100% readiness, 6 export artifacts, and 8 decision journal records.

No workflow was added or broadly redesigned during this run. No real artifact was replaced with a mock, and no synthetic feedback record was inserted merely to populate a count.

## 2. User-Context API Fix

- Located the `no user selected` failure in `server/security/security_store.py`.
- Added local development support for `X-ATLAS-USER-ID` while retaining hosted and production authentication boundaries.
- Preserved the seeded admin ID `user_eecc3a44ed694307`.
- Validates that the supplied user exists and has `status = active`.
- Rejects unknown users with a useful header hint and rejects inactive users with a specific status error.
- Attaches a valid local user to request context and updates last activity.
- Keeps `/api/persistence/health` public and includes service identity, header availability, and a local header example.
- Verified live `GET /api/auth/me` and `GET /api/projects` with the seeded admin header.

## 3. Persistence Validation Summary

SQLite initialization and migrations were validated for:

- `projects`
- `workflow_state`
- `datasets`
- `dataset_versions`
- `evidence_artifacts`
- `run_records`
- `decision_journal`
- `documentation_packages`
- `export_artifacts`
- `users`
- `schema_migrations`
- `audit_log`
- `demo_feedback`

Repository round trips cover projects, workflow state, evidence, runs, decisions, documentation, exports, users, audit records, and feedback. Project, evidence, run, document, export, decision, and feedback writes use stable IDs or upsert behavior where repeat capture should update rather than create uncontrolled duplicates.

Optimization contract tests cover all required evidence, run, export, and decision types. The active Transportation project loaded successfully from SQLite through the live API.

## 4. User Management Changes

The persistence user model now includes `last_active_at`, and the security-to-persistence synchronization preserves the required fields and roles.

Verified local users include:

- ATLAS Local Admin: `user_eecc3a44ed694307`, admin
- Demo Data Scientist: `demo_ds_1`, data_scientist
- Demo Validator: `demo_validator`, validator
- Demo Manager: `demo_manager`, manager

The User Administration table now displays display name, email, role, status, created date, last active date, project count, evidence count, validation count, and export count. Live verification returned seven existing active local users and preserved every pre-existing account.

New persistence writes support attribution for project creation and update, workflow completion, evidence capture, run initiation, documentation creation, and export generation. Historical records created before attribution columns existed were not rewritten.

## 5. Audit Log Changes

Migration `0003_enterprise_foundation.sql` adds an indexed immutable `audit_log` table. The audit repository supports latest-event retrieval and filtering by project, user, and action type.

Persistence routes emit lifecycle audit events for:

- user context establishment
- project creation, open, save, and completion
- template selection
- workflow step completion
- evidence generation and capture
- run start and completion
- validation completion
- recommendation status changes
- documentation generation
- export generation
- private demo feedback submission

The existing Audit Log page supports project, user, action, resource, and outcome filters with timestamps and summaries. Live verification returned persisted audit entries under the seeded admin context.

## 6. Evidence Center Consistency Changes

Added `src/lib/persistedEvidenceStatus.ts` as the shared evidence status and readiness source for:

- Project Overview
- Evidence Center
- Model Documentation Studio
- Optimization workflow status
- Transportation Optimization evidence summary
- Atlas Guide and Copilot optimization context

Supported persisted statuses are `generated`, `captured`, `ready`, `approved`, `stale`, and `rejected`. Legacy statuses are normalized through one helper. Readiness uses a consistent weighted calculation, so generated evidence no longer presents as zero coverage while stale or rejected evidence cannot incorrectly satisfy a ready gate.

The active Optimization project contains 22 persisted evidence artifacts. Two are approved and the remaining retained artifacts are represented by their actual persisted status.

## 7. Export Artifact Strategy

ATLAS uses the client-generated download strategy for the current Optimization exports. The browser creates the downloaded file while SQLite stores governed metadata, filename, creator, timestamp, artifact hash, payload summary, and explicit storage mode.

New and historical client downloads now use:

- `storage_mode = client_generated`
- `file_path = not_applicable_client_download`

Migration `0004_export_storage_backfill.sql` replaced ambiguous historical `-` paths without modifying payloads. Real server-file paths, if supplied, are retained with `storage_mode = server_file`.

All six active Optimization exports have non-empty artifact hashes and explicit client-download paths. Export types are governed JSON, allocation CSV, reproducibility evidence, Optimization report, Python code, and SAS-compatible code.

## 8. Demo and Tester Readiness Changes

Added a visible private demo banner with the exact safety message:

> Private ATLAS demo. Use synthetic or non-sensitive data only.

Added an in-app feedback form and SQLite-backed feedback API with route, project, workflow, step, issue type, severity, expected behavior, actual behavior, notes, timestamp, and user attribution. A local browser fallback remains available when the backend cannot be reached.

The active database currently contains zero feedback records because no fake tester submission was introduced. Live admin retrieval of `/api/demo-feedback` succeeded.

## 9. Documentation Updates

Created or updated:

- `ATLAS_PRIVATE_DEMO_SETUP.md`
- `ATLAS_TESTER_FEEDBACK_GUIDE.md`
- `ATLAS_BACKEND_PERSISTENCE_TEST_PLAN.md`
- `ATLAS_SQLITE_PERSISTENCE.md`
- this completion report

The documentation uses the package-aware backend command from the repository root and includes PowerShell API examples with the actual seeded admin ID.

## 10. Scripts Added or Modified

### `scripts/inspect_atlas_db.py`

Reports the database path, table counts, users, projects, workflow states, evidence, runs, documentation, exports with storage mode, decisions, audit events, and feedback.

### `scripts/reset_atlas_db.py`

Provides a guarded local reset implementation. It refuses to run without `--yes`, creates a timestamped backup by default, deletes only the resolved target SQLite database and its WAL/SHM companions, reinitializes migrations, and synchronizes local demo users.

### `scripts/reset_atlas_demo_db.py`

Provides the requested demo-specific wrapper. It is never invoked automatically.

### `scripts/sync-atlas-clean-copy.ps1`

Synchronizes source code to the clean copy while excluding Git metadata, dependencies, build output, virtual environments, runtime databases, environment files, and runtime artifact directories.

## 11. Tests Added

Backend coverage now includes:

- required schema and migration initialization
- project and Transportation template persistence
- workflow state round trips
- evidence, run, documentation, export, and decision repositories
- complete Optimization artifact contracts
- user activity summaries and seeded roles
- audit repository filters
- demo feedback idempotence
- legacy export metadata backfill
- inspect output and reset refusal guard
- package-aware Uvicorn startup from the repository root
- public and authenticated health checks
- seeded admin identity
- authenticated project access
- missing, invalid, and inactive local user behavior

Frontend and source integration coverage includes persisted evidence readiness, project mirroring, explicit export contracts, User Administration fields, Audit Log integration, Evidence Center consistency, and Optimization workflow evidence semantics.

## 12. Tests Run

The following validation commands were run successfully:

- `npx tsc -b --pretty false`
- `npm run build`
- `npm run test:sqlite-persistence`
- `npm run test:user-management`
- `npm run test:evidence-graph`
- `npm run test:project-types`
- `npm run test:workflow-navigation-state`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:dataset-library`
- `npm run test:regression`
- `npm run test:model-documentation`
- `npm run test:credit-risk-studio`
- `npm run test:experimental-design`
- `npm run test:experimentation`
- `npm run test:optimization`
- Python compile validation for the changed backend modules
- `python scripts/inspect_atlas_db.py --limit 8`

## 13. Test Results

- TypeScript compilation: passed
- Production build: passed
- SQLite frontend tests: 5 passed
- SQLite backend and live HTTP tests: 13 passed
- User management: 30 assertions passed
- Workflow navigation state: 3 tests passed
- Open Project: 15 tests passed
- Browser persistence: 9 tests passed
- Regression suite: 18 tests passed
- Credit Risk Studio: 26 tests passed
- Experimental Design: 14 tests passed
- Optimization frontend: 32 tests passed
- Optimization backend: 17 tests passed
- Experimentation frontend and backend: passed
- Dataset Library, Model Documentation, Evidence Graph, and project type tests: passed

The build reports only existing Browserslist age and bundle-size advisories. No compile or test failure remains in the required matrix.

## 14. Manual Validation Results

Live API validation on the current package-aware ATLAS backend confirmed:

- health status is available
- service fingerprint is `atlas-backend`
- health does not require user context
- the local development header is enabled
- seeded admin `user_eecc3a44ed694307` resolves as active
- `GET /api/projects` returns the persisted project
- the active project is `Cash Logistics Transportation QA`
- its template is `transportation_logistics`
- workflow state is at `optimization-14` with 14 completed steps
- evidence count is 22
- run count is 5
- documentation count is 1 with complete status and 100% readiness
- export count is 6 with 6 explicit client-download paths
- decision count is 8
- audit retrieval succeeds
- user administration retrieval succeeds
- demo feedback retrieval succeeds

## 15. Known Failures

No required implementation or regression test remains failing.

The documented port `8000` was occupied during final manual validation by an unrelated `python -m src` service. That process was not stopped. ATLAS was therefore validated live on port `8001`. The package-aware repository-root command itself was also exercised by the automated live HTTP test on an isolated available port.

## 16. Known Limitations

- Existing historical run records and the existing documentation package predate the attribution migration and therefore have no `created_by` value. New writes are attributed.
- Some historical evidence records use `ATLAS` as creator rather than a user ID. They were preserved as recorded.
- Optimization downloads are browser-generated, so the backend persists metadata and hashes rather than a server file path.
- The persistence database currently has no rows in `datasets` or `dataset_versions`. Existing Dataset Library file-backed artifacts were preserved and no fake database registrations were added.
- `demo_feedback` remains empty until a tester submits real feedback.
- Backend import can take roughly 15 to 25 seconds on this workstation because scientific and workflow modules are loaded during application startup.
- Existing build advisories remain for Browserslist data age and large JavaScript chunks.

## 17. Startup Commands Verified

Backend, from repository root:

```powershell
cd C:\Users\james\ds-workflow-starter
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```powershell
cd C:\Users\james\ds-workflow-starter
npm run dev
```

Local API identity:

```powershell
$headers = @{
  "X-ATLAS-USER-ID" = "user_eecc3a44ed694307"
}

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/projects" `
  -Headers $headers `
  -Method GET
```

The server must be started from the repository root. `cd server` followed by `uvicorn main:app` is not supported because the backend uses package-relative imports.

## 18. Database Inspection Output Summary

Final inspection before clean-copy synchronization reported:

| Table | Rows |
| --- | ---: |
| projects | 1 |
| workflow_state | 1 |
| evidence_artifacts | 22 |
| run_records | 5 |
| documentation_packages | 1 |
| export_artifacts | 6 |
| decision_journal | 8 |
| audit_log | 7 |
| users | 7 |
| demo_feedback | 0 |
| datasets | 0 |
| dataset_versions | 0 |
| schema_migrations | 4 |

All six exports have hashes. All 22 evidence records have a recorded creator value. Historical run attribution remains blank as documented above.

## 19. Confirmation That No Workflows Were Regressed

No workflow was added, removed, reordered, or broadly redesigned in this foundation run. Existing project type, workflow navigation, open-project, persistence, Predictive Modeling regression, Dataset Library, Model Documentation, Evidence Center, Credit Risk Studio, Experimental Design, A/B Testing, and Optimization tests passed.

The completed Transportation / Logistics Optimization project still opens from SQLite and retains its formulation, runs, evidence, documentation, exports, decisions, workflow state, and `transportation_logistics` template.

## 20. Confirmation That No Fake Artifacts Were Introduced

No fake dataset, evidence artifact, solver run, model run, decision, export, audit event, or tester feedback record was added to the active database. Automated tests use isolated disposable SQLite files and remove them after execution. The reset guard test uses only a disposable test path and does not reset the active ATLAS database.

## 21. Confirmation That the Source Workspace Was Used

All implementation, migration, test, script, and documentation changes were made in:

`C:\Users\james\ds-workflow-starter`

The clean synced copy was not edited directly.

## 22. Confirmation That `npm run sync:atlas` Was Run

Confirmed. `npm run sync:atlas` completed successfully from the source workspace on July 16, 2026 at 12:45 AM local time.

Robocopy returned success code 3 with 76 files copied, 1,769 files already current, zero mismatches, and zero failures. Runtime artifacts, SQLite databases, environment files, dependencies, build output, and Git metadata remained excluded by policy. A final synchronization was then run after this confirmation was written so the clean copy contains the completed report.

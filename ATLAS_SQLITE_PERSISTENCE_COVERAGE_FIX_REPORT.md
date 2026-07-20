# ATLAS SQLite Persistence Coverage Fix Report

Date: 2026-07-15  
Source workspace: `C:\Users\james\ds-workflow-starter`  
Clean synced copy: `C:\Users\james\Projects\ATLAS\atlas-app`

## 1. Root Cause of the PowerShell API Error

Persistence routes require an ATLAS user context. Browser requests normally receive that context through the selected authenticated user, but direct PowerShell requests supplied neither a session user nor a development header. The security dependency therefore returned `no user selected`, even though user rows existed in SQLite.

## 2. User Context Solution

ATLAS now supports `X-ATLAS-USER-ID` only while `ATLAS_DEV_MODE=true`. `local-dev-user` is resolved or created as an active local admin. Production mode does not honor this bypass. Requests without context return a helpful hint and, in development only, the available development users.

Validated behavior:

- No header: helpful `no user selected` response with remediation guidance.
- `X-ATLAS-USER-ID: local-dev-user`: persistence APIs succeed.
- Existing local admin users remain available and unchanged.

## 3. Existing Database Findings

The original SQLite schema and project/workflow rows existed, but the Transportation project had a blank `template_id`, while evidence, run, and export tables had no records. The final inspected database is:

`C:\Users\james\ds-workflow-starter\server\data\atlas_local.db`

Final meaningful row counts:

| Table | Rows |
|---|---:|
| projects | 1 |
| workflow_state | 1 |
| evidence_artifacts | 22 |
| run_records | 5 |
| documentation_packages | 1 |
| export_artifacts | 6 |
| decision_journal | 8 |
| users | 1 |
| schema_migrations | 2 |

## 4. Template ID Persistence Fix

The frontend save contract now includes `templateId`, the persistence client maps it to the backend contract, and the repository writes and restores `projects.template_id`. Migration `0002_optimization_template_id.sql` safely backfills Transportation projects only when transportation-specific metadata or workflow state supports the inference.

Validated project:

- Project: `atlas-mrlgel4o`
- Type/workflow: `optimization`
- Template: `transportation_logistics`
- Current step: `optimization-14`
- Completed steps: `optimization-1` through `optimization-14`

Template changes also clear incompatible formulation artifacts before the new template state is persisted.

## 5. Evidence Persistence Changes

The Transportation workflow now mirrors governed step evidence to SQLite when evidence is produced or the study is completed. Persisted major artifact types include the decision charter, input bundle, route normalization, formulation readiness, objective, variables, constraints, solver configuration, scenarios, solution, sensitivity, validation, recommendation, implementation, monitoring, documentation package, and reproducibility code.

Statuses use the governed set (`generated`, `captured`, `ready`, `approved`, `stale`, `rejected`). The completed study produced 17 major workflow artifacts plus 5 export-related evidence artifacts, for 22 database rows.

## 6. Run Record Persistence Changes

Actual workflow actions now create five auditable records:

1. `optimization_input_normalization`
2. `optimization_solver`
3. `optimization_scenarios`
4. `optimization_sensitivity`
5. `optimization_validation`

The records include action-specific metrics and artifacts such as normalization/formulation hashes, route and allocation details, scenario results, perturbation diagnostics, validator notes, and validation gates. The validated solver record reports an optimal, business-valid solution with all 480 demand units fulfilled.

## 7. Export Persistence Changes

Every Transportation Documentation export action records one of the required export types:

- `governed_json`
- `allocation_csv`
- `reproducibility_evidence`
- `optimization_report`
- `python_code`
- `sas_compatible_code`

Browser-generated downloads are explicitly stored as `clientOnly: true` and `fileExists: false`; ATLAS does not claim a server file path that does not exist. Export filename, hash, project, user, timestamp, and generation metadata are persisted.

## 8. Documentation Package Persistence Changes

Completing the study persists an `optimization_study` package with:

- Status: `complete`
- Readiness score: `100`
- Sections: `20`
- Completed sections: `20`

The package payload contains the executive, business, formulation, solver, scenario, sensitivity, validation, recommendation, implementation, monitoring, approval, and reproducibility content required by the workflow.

## 9. Decision Journal Persistence Changes

Eight governed decisions were persisted for the validated study, including input confirmation, formulation strategy, solver acceptance, validation completion, and study completion. Entries include decision type, title, summary, status, owner, timestamps, creator, and structured payload. ATLAS does not create noisy audit events for every incidental click.

## 10. Project Overview Backend Evidence Changes

Project Overview now loads the backend persistence bundle and uses persisted workflow, evidence, run, documentation, export, and decision records when available. The validated project displays:

- Workflow completion: `100%`
- Evidence coverage: `100%`
- Evidence package: `Ready`
- Documentation: `100%` / complete
- Solver solution: `Business-valid`
- Validation score: `100%`
- Recommendation: `Recommended`
- Implementation: `Plan complete`

When no backend evidence exists, the Overview uses an explicit not-yet-captured state and offers a direct evidence action instead of showing a misleading zero as completed evidence.

## 11. Inspection Script Usage

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_atlas_db.py
```

Optional arguments:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_atlas_db.py --limit 30
.\.venv\Scripts\python.exe scripts\inspect_atlas_db.py --db C:\path\to\atlas_local.db
```

The script prints the resolved database path, table counts, users, projects, workflow states, evidence, runs, documentation, exports, and decision journal entries.

## 12. Updated Manual Test Commands

`ATLAS_BACKEND_PERSISTENCE_TEST_PLAN.md` now contains complete PowerShell examples for health, users, projects, workflow state, evidence, runs, exports, and direct SQLite verification. The local header is:

```powershell
$headers = @{ "X-ATLAS-USER-ID" = "local-dev-user" }
```

Direct SQLite verification uses the unambiguous full path:

```powershell
sqlite3 C:\Users\james\ds-workflow-starter\server\data\atlas_local.db ".tables"
```

## 13. Tests Added

Coverage was added for development user resolution, helpful missing-user responses, template save/restore/migration, workflow state, evidence status and retrieval, all required optimization runs, the 20-section documentation package, export metadata/client-only semantics, backend-driven Overview/evidence coverage, and persistence source integration.

Test harnesses were also updated to compile the new optimization-template and persistence dependencies used by Open Project, project persistence, and Decision Journal tests.

## 14. Tests Run

The following validation commands were run from the source workspace:

```powershell
npm run test:sqlite-persistence
npm run test:optimization
npm run test:open-project
npm run test:persistence
npm run test:decision-journal
npm run test:evidence-graph
npm run build
```

## 15. Test Results

- SQLite persistence: 4 Node tests passed; 9 Python tests passed.
- Optimization: 32 Node tests passed; 17 Python tests passed.
- Open Project: 15 tests passed.
- General persistence: 9 tests passed.
- Decision Journal: 2 tests passed.
- Evidence graph: passed.
- TypeScript and production Vite build: passed; 1,721 modules transformed.

The build emitted existing advisory warnings about browser metadata age and large chunks; neither is a correctness failure for this persistence change.

## 16. Manual Validation Results

The source backend (`http://127.0.0.1:8001`) and frontend (`http://127.0.0.1:5174`) were used for browser QA. The following visible UI actions were executed:

- Normalize and validate bundle
- Run optimization
- Run transportation scenarios
- Run sensitivity analysis
- Run validation scorecard
- All six documentation/export actions
- Complete Optimization Study

Project Overview and Model Evidence Center were checked in the browser. The backend and frontend were restarted. A separate fresh browser origin with no project-local cache opened the project from the Backend Registry and restored `/workflow/optimization/14` with the full completed workflow, 480 fulfilled demand, 30 route variables, validation score 100, documentation 20/20, Recommendation, implementation state, evidence state, and export controls.

Final service checks returned backend status `available`, schema `0002`, the expected absolute SQLite path, and frontend HTTP `200`.

## 17. Remaining Limitations

- The existing browser/local persistence fallback remains intentionally enabled.
- Browser downloads do not have a server filesystem path. Their backend records explicitly identify them as client-only rather than inventing a path. A future server-side export service can materialize regulated files under an approved artifact-retention policy.
- The development user header is deliberately unavailable outside development mode.
- The production build still reports advisory code-splitting and browsers-list freshness warnings unrelated to persistence correctness.

## 18. Confirmation That No Fake Artifacts Were Introduced

No production database rows were inserted with synthetic SQL or fabricated server file paths. The final project rows were generated by the actual Transportation Optimization UI controls and persistence APIs. Automated tests use isolated temporary databases. Browser-only exports are truthfully labeled as client-only with no server file claim.

## 19. Confirmation of Source Workspace

All code and documentation changes were made in:

`C:\Users\james\ds-workflow-starter`

The clean copy was not edited directly.

## 20. Confirmation of Clean-Copy Sync

After validation, `npm run sync:atlas` was run with access to the clean-copy directory. Robocopy completed with code `3` (files copied plus existing destination files), `0` failed files, and synchronized the source workspace to:

`C:\Users\james\Projects\ATLAS\atlas-app`

The command was run again after this report was added, and a SHA-256 comparison confirmed that the source and clean-copy reports are identical.

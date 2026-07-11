# ATLAS Project Persistence Recovery Report

## Summary

This emergency fix addresses the Open Project failure caused by browser `localStorage` quota errors while saving the Recent Projects index.

ATLAS now treats Recent Projects registry writes as recoverable registry maintenance, not as a hard project-save failure. If browser storage rejects the registry write, the active project is preserved in an in-session recovery registry and the Open Project page remains usable.

## Root Cause

The Recent Projects registry writer threw an exception when `localStorage.setItem("atlas-local-projects", ...)` failed, even after compacting and thinning the registry. That exception caused:

- `/projects/open` to show no local projects.
- active projects to appear lost even when workflow state still existed.
- save status to report a generic save failure.
- navigation/save flows to treat registry maintenance failure as full project persistence failure.

## Changes Made

- Added `safeSetLocalStorage()` for quota-safe browser storage writes.
- Added an in-session Recent Projects recovery registry fallback.
- Updated project save status to distinguish `registry_warning` from hard `save_failed`.
- Prevented quota failures from erasing the active workflow state.
- Added recovery actions on `/projects/open`:
  - Recover Current Project
  - Export Current Project Backup
  - Rebuild Recent Projects Index
  - Compact Browser Project Storage
  - Open Project From File / Import Project
- Added Project Storage Diagnostics on `/projects/open`.
- Added storage compaction that avoids deleting active project workflow-node state.
- Added test coverage for quota failure, recovery registry, diagnostics, and safe storage writes.

## Files Changed

- `src/lib/localProjects.ts`
- `src/lib/projectPersistence.ts`
- `src/components/ProjectSaveStatus.tsx`
- `src/steps/ProjectUtilityPages.tsx`
- `tests/openProjectRoute.test.mjs`
- `PROJECT_PERSISTENCE_RECOVERY_REPORT.md`

## Recovery Behavior

If the browser cannot write the Recent Projects index:

1. ATLAS keeps the active project in memory for the current session.
2. `/projects/open` shows a Project Recovery panel.
3. The user can export a backup immediately.
4. The user can compact browser storage and rebuild the Recent Projects index.
5. The save badge shows a registry warning instead of implying the whole project vanished.

## Storage Bloat Guardrails

Recent Projects remains compact and avoids embedding full datasets, full simulation arrays, and large chart payloads. Existing snapshot compaction continues to preserve summaries and references rather than full artifacts.

The new compaction action removes large stale ATLAS browser artifacts but protects the active project snapshot and active project workflow-node state.

## Tests Run

- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:model-diagnostics`
- `npm run test:chart-studio`
- `npm run test:analytics-workbench`
- `npm run test:dataset-library`
- `npm run test:regression`
- `npx tsc -b`
- `npm run build:modeling`
- `npm run build`

## Clean-Copy Sync

- Synced verified source changes to `C:\Users\james\Projects\ATLAS\atlas-app` with `npm run sync:atlas`.
- `server/artifacts` remained intentionally excluded from sync.
- Clean copy verification passed:
  - `npm run test:open-project`
  - `npm run build`

## Known Limitations

- The emergency fallback is in-session only if browser storage rejects all registry writes. Users should export a backup or compact storage before closing the browser.
- Backend filesystem project registry is not yet the primary project registry. This pass stabilizes browser recovery first.
- IndexedDB project persistence remains a future hardening step if large browser-side project artifacts continue to grow.

## Phase 10H: Predictive Project Recovery and Detailed List Views

ATLAS now includes a deeper project recovery path for Predictive Modeling projects that do not appear in Recent Projects.

### Added Recovery Sources

- Browser Recent Projects registry.
- Legacy browser project migration utilities.
- Backend project registry: `server/artifacts/projects/project_registry.json`.
- Dataset Library registry and project links.
- Dataset artifact naming patterns for `REG_*`, `CLASS_*`, and scored-output datasets.

### Critical Recovery Answer

The original Home Prices Regression Test Model and classification/fraud projects can be partially reconstructed from server artifacts and Dataset Library evidence if their full browser snapshots are missing.

Evidence found:

- Regression artifacts exist for `REG_TRAIN`, `REG_TEST`, and `REG_OOT`.
- Home Prices Regression Test Model scored train/test/OOT output artifacts exist.
- Dataset links exist for the regression project shell.
- Classification artifacts exist for `CLASS_TRAIN`, `CLASS_TEST`, and `CLASS_OOT`.

Recovery status:

- Full recovery: possible only if the full browser snapshot is still present.
- Partial recovery: available from Dataset Library links and server artifacts.
- Required user action: run Deep Recovery Scan on `/projects/open`, select the desired candidates, and recover them into Recent Projects.

### Open Project Enhancements

- Added Deep Recovery Scan controls.
- Added selected-candidate recovery instead of automatic bulk import.
- Added exportable `PROJECT_RECOVERY_SCAN_REPORT.md`.
- Added Card View and Detailed View.
- Added search by project name, target, dataset, and project type.
- Added filters for All, Predictive Modeling, Experimental Design, Regression, Classification, Recovered, and Incomplete.

### Dataset Library Enhancements

- Added Card View and Detailed View.
- Added detailed dataset columns for rows, columns, versions, ownership, linked projects, source type, status, and actions.
- Added filters for Training, Test, OOT, Scored Outputs, Regression, Classification, Uploaded, Metadata-only, Linked to Current Project, and Unlinked.
- Added actions for Open, Open in Analytics, Open in Chart Studio, Open in Model Diagnostics, Link to Project, Delete, and Export Metadata.

### Phase 10H Files Added / Changed

- `server/projects/__init__.py`
- `server/projects/project_registry.py`
- `server/projects/project_router.py`
- `server/main.py`
- `src/lib/projectRecovery.ts`
- `src/lib/datasetLibrary.ts`
- `src/steps/ProjectUtilityPages.tsx`
- `src/steps/DatasetLibrary.tsx`
- `tests/openProjectRoute.test.mjs`
- `tests/datasetLibrary.test.mjs`
- `PROJECT_RECOVERY_SCAN_REPORT.md`

## Phase 10I Open Project Recovery UX Cleanup

Recovery tooling is now treated as an advanced support path instead of the normal Open Project experience.

### Behavior Changed

- The Open Project page renders browser-saved projects, search, filters, and Card/Detailed View controls before recovery tooling.
- Project Recovery, Project Storage Diagnostics, and Deep Recovery Scan now live under `Advanced Recovery Tools`.
- Advanced Recovery Tools defaults to collapsed when projects are visible and browser storage is healthy.
- Advanced Recovery Tools auto-expands when:
  - no Recent Projects are registered,
  - the registry is corrupted,
  - browser storage is using the volatile recovery fallback,
  - a registry write/quota warning exists,
  - recovery candidates are present after a scan.

### Normal Launcher Behavior

- Search still filters by project name, target, dataset, and workflow type.
- Filters still support Predictive Modeling, Experimental Design, Regression, Classification, Recovered, and Incomplete.
- Card View and Detailed View remain the primary project-management views.
- Recovery actions remain available without dominating normal project reopening.

### Tests Run

- `npm run test:open-project`
- `npm run test:persistence`
- `npm run build:modeling`
- `npm run build`

Clean-copy sync and clean-copy verification are recorded in `PREDICTIVE_MODELING_WORKFLOW_QA_REPORT.md`.

## Phase 10J Open Project Table-First UX

Open Project now defaults to an enterprise Detailed View instead of a card gallery.

### Behavior Changed

- Default view is `Detailed View`, persisted with `atlas-open-project-view-mode`.
- `Card View` remains available as a secondary option for small demos.
- More than six projects strongly prefer Detailed View.
- The normal project table appears before `Advanced Recovery Tools`.
- `Advanced Recovery Tools` stays collapsed by default unless storage/recovery attention is required.

### Enterprise Project Table

The table now shows one row per project with:

- Project Name
- Project Type
- Task
- Target
- Current Stage
- Progress with compact progress bar
- Linked Datasets
- Last Modified
- Created
- Storage Location
- Recovery Status
- Actions

### Sorting / Filtering / Search

- Default sort: Last Modified descending.
- Sortable fields: Project Name, Project Type, Task, Target, Progress, Last Modified, Created, and Recovery Status.
- Search matches project name, type, task, target, linked datasets, storage location, and recovery status.
- Existing filters remain available for Predictive Modeling, Experimental Design, Regression, Classification, Recovered, and Incomplete.

### Tests Run

- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:dataset-library`
- `npm run test:model-diagnostics`
- `npm run test:chart-studio`
- `npm run test:analytics-workbench`
- `npm run test:regression`
- `npm run build:modeling`
- `npm run build`

### Manual QA Status

Manual browser QA was not completed in this automated pass. Static tests, TypeScript compilation, and production builds passed in the source workspace.

### Clean-Copy Sync

- Synced verified source changes to `C:\Users\james\Projects\ATLAS\atlas-app` with `npm run sync:atlas`.
- `server/artifacts` remained intentionally excluded from sync.
- Clean copy verification passed:
  - `npm run test:open-project`
  - `npm run test:dataset-library`
  - `npm run build`

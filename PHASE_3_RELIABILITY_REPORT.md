# ATLAS Phase 3 Reliability Report

## Scope Completed

Phase 3 was started with project save/reopen reliability as the top priority. This pass focused on making Recent Projects restore usable workflow state, making project saves visible and quota-safe, widening TypeScript coverage, and fixing direct bottom-navigation buttons that bypassed save behavior.

## Root Cause

ATLAS project state was split across the active Zustand workflow store, localStorage keys, sessionStorage keys, workflow-node keys, and the Recent Projects registry. Recent Projects primarily preserved project metadata and workflow-step status, while many page-level artifacts stayed in scattered browser keys. Some page buttons navigated directly without saving a project snapshot first. Large artifacts also risked localStorage quota failures.

## Persistence Architecture After Fix

- `src/lib/projectPersistence.ts` now builds a compact persisted project state from known ATLAS storage keys.
- Recent Projects snapshots now include compact workflow artifacts under `persistedLocalState`.
- Project reopen restores:
  - project metadata
  - current workflow step
  - completed workflow state
  - workflow node states
  - compact localStorage artifacts
  - compact sessionStorage artifacts such as dataset preview/training summary
- Large artifacts are compacted before persistence:
  - dataset rows are limited to a small preview
  - training summaries are limited to compact ranked output
  - Monte Carlo iteration arrays are removed
  - chart curves and feature-importance arrays are bounded
  - decision journal history is bounded
- Save status is emitted through a shared browser event and displayed in the ATLAS header.
- Settings now includes a Project Persistence Debug panel with Save Now, Export Project, Repair Recent Projects, and local cache controls.

## Bugs Fixed

- Recent Projects now stores and restores compact workflow artifacts instead of only metadata.
- Opening a project now rehydrates persisted local/session artifacts.
- Save failures are surfaced through a visible header status and inline navigation errors.
- Save attempts retry with compacted snapshots when localStorage quota errors occur.
- Experimental Design `Save Draft` now updates the project snapshot registry.
- Shared step navigation now saves before advancing and scrolls the next page to the top.
- Direct predictive workflow bottom buttons were patched to save before advancing:
  - EDA to Outliers
  - Evaluation to Interpretation
  - Scoring to Model Development Document
  - Model Development Document to Implementation
- Model Training and Interpretation direct buttons already patched in this pass save before advancing.
- TypeScript coverage now includes ATLAS source files instead of only three entry files.
- Hidden TypeScript issues fixed in D3 grouped chart helpers and workflow schema.

## Files Changed in This Pass

- `src/lib/projectPersistence.ts`
- `src/lib/localProjects.ts`
- `src/state/useWorkflowStore.ts`
- `src/components/ProjectSaveStatus.tsx`
- `src/components/StepShell.tsx`
- `src/apps/ModelingApp.tsx`
- `src/steps/WorkflowPlaceholderStep.tsx`
- `src/steps/ProjectUtilityPages.tsx`
- `src/steps/Step02_EDA.tsx`
- `src/steps/Step06_Train.tsx`
- `src/steps/Step08_Evaluation.tsx`
- `src/steps/Step09_Interpretation.tsx`
- `src/steps/Step10_Scoring.tsx`
- `src/steps/Step11_ModelDevelopmentDocument.tsx`
- `src/components/D3GroupedBar.tsx`
- `src/components/D3GroupedHistogram.tsx`
- `src/config/workflow.schema.ts`
- `tsconfig.json`
- `PHASE_3_RELIABILITY_REPORT.md`

## Verification

Commands run:

- `npm run build:modeling` - passed
- `npm run test:experimental-design` - passed, 7 tests
- `npm run build` - initially failed with a local `EPERM` esbuild spawn error inside the sandbox; rerun elevated and passed

Manual smoke test:

- Loaded ATLAS at `http://127.0.0.1:5174`.
- Created a new project and verified it appeared in Recent Projects.
- Opened the project from Recent Projects and confirmed project metadata restored.
- Filled Project Context, clicked the bottom next-step CTA, and verified navigation to Data Acquisition with scroll position at top.
- Opened Settings and confirmed the Project Persistence Debug panel shows project ID, storage keys, and save/repair controls.
- Verified Model Development Document bottom CTA saves and advances to Implementation with scroll position at top.
- Verified Scoring bottom CTA saves and advances to Model Development Document with visible saved/restored status.
- Verified the Outliers page loads without a blank page/crash state.
- Verified the Model Training page exposes selectable model toggles, Grid Search, Search Depth, and Train Selected controls.
- Verified the stale `KNN (k=7)` label is no longer displayed.
- Verified the Interpretation page shows `Recursive Feature Elimination`, `Run RFE`, and `Save as Final Model`.

## Clean Copy Sync

Verified Phase 3 files were synced to:

`C:\Users\james\Projects\ATLAS\atlas-app`

The clean copy does not currently have `node_modules`, so builds were verified in the original git-tracked workspace:

`C:\Users\james\ds-workflow-starter`

## Known Limitations

- The persistent snapshot restores compact previews and summaries, not full raw datasets or full model artifacts. Users may need to reload a dataset before retraining or scoring.
- Automated project persistence tests have not been added yet; this pass used build validation plus manual browser smoke tests.
- Some broader Phase 3 requests remain for follow-up:
  - full predictive workflow smoke with upload/train/evaluate/score
  - deeper documentation cleanup
  - import schema validation hardening
  - report HTML sanitization audit
  - performance caching for EDA, SHAP, RFE, scoring, and Monte Carlo

## Recommended Phase 4 Tasks

- Add automated save/reopen tests for predictive and experimental projects.
- Add explicit storage quota simulation tests.
- Move large artifacts to IndexedDB or backend artifact references.
- Add user-facing restore warnings for “dataset reload required” and “model artifact requires rerun.”
- Continue Phase 3 predictive bug sweep with a full backend training run: model queue payload validation, RFE backend prerequisites, scoring artifact restore, and outlier analysis using a newly uploaded dataset.

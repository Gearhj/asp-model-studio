# Phase 2 Cleanup Report

Date: 2026-07-03

## Objective

Begin Phase 2 cleanup and project separation while preserving the original `C:\Users\james\ds-workflow-starter` folder as the git-tracked source and backup.

## Source of Truth

All source-code changes were made in:

`C:\Users\james\ds-workflow-starter`

The verified source was then synced to:

`C:\Users\james\Projects\ATLAS\atlas-app`

No changes were made that delete or reset the original project folder.

## ATLAS Runtime Separation

Completed:

- Added `src/AtlasApp.tsx` as the ATLAS-only application boundary.
- Updated `src/main.tsx` to render `AtlasApp` instead of the legacy mixed `App`.
- Removed `guitarist.html` from the ATLAS Vite build input.
- Updated default package scripts so `npm run dev`, `npm run build`, and `npm run preview` target ATLAS/modeling mode.
- Kept `build:modeling` for compatibility.
- Updated `server/main.py` branding from DS Workflow API to ATLAS API.
- Removed STELA router mounting from the ATLAS backend.
- Updated `tsconfig.json` so it no longer references the legacy Guitarist or STELA entry files.

Preserved in original workspace:

- Legacy `src/App.tsx`
- Greatest Guitarist source files
- STELA/tracker source files
- `server/stela_router.py`

These remain available as backup/reference until separated project builds are fully verified.

## Archived, Not Deleted

Moved into `archive/phase2/deprecated`:

- `Startup Instructions.txt`
- `src/state/stepOrder.tx`
- `src/steps/Step07_Eval.tsx`

Reason:

- `Startup Instructions.txt` was superseded by `docs/LOCAL_DEVELOPMENT.md`.
- `stepOrder.tx` was a duplicate typo-suffixed file.
- `Step07_Eval.tsx` was an old unused evaluation step.

## Documentation Added

Added ATLAS documentation:

- `README.md`
- `docs/LOCAL_DEVELOPMENT.md`
- `docs/ARCHITECTURE.md`
- `docs/PERSISTENCE.md`
- `docs/SECURITY_AND_DATA_HANDLING.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/workflows/predictive-modeling.md`
- `docs/workflows/experimental-design.md`

## Standalone Project Scaffolds

Updated Greatest Guitarist scaffold:

`C:\Users\james\Projects\Greatest-Guitarist\guitarist-app`

Added/updated:

- `package.json`
- `vite.config.ts`
- `README.md`

Verified required files exist:

- `guitarist.html`
- `src/guitarist-main.tsx`
- `src/GuitaristApp.tsx`
- `src/guitarist.css`
- `src/data/guitarists.ts`
- `src/data/sourceRankings.ts`
- `src/data/supplementalGuitarists.ts`
- `src/data/wikidataGuitarists.ts`
- `scripts/fetch-wikidata-guitarists.mjs`
- `public/assets/guitar-fretboard.png`

Updated STELA/tracker scaffold:

`C:\Users\james\Projects\Data-Science-Workflow-Tracker\tracker-app`

Added/updated:

- `package.json`
- `vite.config.ts`
- `README.md`
- `src/App.tsx`
- `server/main.py`

Verified required files exist:

- `src/apps/StelaDashboardApp.tsx`
- `src/lib/stelaApi.ts`
- `server/stela_router.py`
- `.env.scheduling`

## Clean ATLAS Copy

Synced verified source into:

`C:\Users\james\Projects\ATLAS\atlas-app`

Excluded generated/local folders:

- `.git`
- `node_modules`
- `.venv`
- `dist`
- `.tmp`
- `.runtime`
- `catboost_info`
- `.agents`
- `.codex`
- `.vscode`
- `archive`
- `server/static`
- `media`

Removed stale unrelated app files from the clean ATLAS copy only:

- `guitarist.html`
- `src/App.tsx`
- `src/guitarist-main.tsx`
- `src/GuitaristApp.tsx`
- `src/guitarist.css`
- `src/data/guitarists.ts`
- `src/data/sourceRankings.ts`
- `src/data/supplementalGuitarists.ts`
- `src/data/wikidataGuitarists.ts`
- `scripts/fetch-wikidata-guitarists.mjs`
- `public/assets/guitar-fretboard.png`
- `src/apps/StelaDashboardApp.tsx`
- `src/lib/stelaApi.ts`
- `server/stela_router.py`
- `.env.scheduling`

## Verification Results

Passed:

- `npm run build:modeling`
- `npm run test:experimental-design`
- `npm run build` with escalation after sandbox-only `esbuild` spawn restriction

Smoke checks passed:

- `http://127.0.0.1:5174/dashboard`
- `http://127.0.0.1:5174/step00`
- `http://127.0.0.1:5174/step01`
- `http://127.0.0.1:5174/step02`
- `http://127.0.0.1:5174/workflow/experimental-design/1`
- `http://127.0.0.1:8001/api/health`

Build note:

- `npm run build` initially failed under the sandbox with `spawn EPERM` while launching `esbuild`.
- The same script passed outside the sandbox.
- `npm run build:modeling` passed repeatedly in the normal workspace.

## Known Limitations

- The clean external ATLAS copy does not currently have `node_modules`, so a clean-copy build requires running `npm install` in `C:\Users\james\Projects\ATLAS\atlas-app`.
- Standalone Greatest Guitarist and STELA project folders now have launch scaffolds, but their independent builds were not run in this phase.
- `server/static` contains generated chart artifacts in the original workspace and was excluded from the clean ATLAS sync.
- `requirements.txt` and `server/requirements.txt` both exist with overlapping backend dependency sets. They were inspected but not consolidated in this phase.
- Some audit documents still mention the pre-cleanup mixed repo state for historical context.

## Recommended Next Phase

1. Run `npm install` and build inside each external project folder.
2. Consolidate Python requirements into a single ATLAS backend dependency file.
3. Continue fixing the critical predictive modeling workflow bugs listed in the Phase 2 task.
4. Implement storage-bloat controls for raw datasets, simulation arrays, chart payloads, and decision journal logs.
5. Harden imports, project schema validation, upload limits, and report sanitization before hosted deployment.

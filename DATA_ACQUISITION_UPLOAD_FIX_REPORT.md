# ATLAS Data Acquisition Upload Fix Report

## Summary

Fixed the blocking Data Acquisition regression where files larger than the 25 MB browser preview limit stopped at a warning and never loaded into ATLAS.

Large CSV/TXT files now route to the FastAPI backend import endpoint, hydrate the browser preview from a governed sample, populate columns and target selection, and preserve the full backend dataset for downstream modeling.

## Changes Made

- Added `src/lib/dataAcquisitionUpload.ts` for upload routing, backend payload normalization, target inference, error messaging, and CTA disabled reasons.
- Updated `src/steps/Step01_DataAcquisition.tsx` so:
  - small CSV/JSON files still parse locally,
  - large CSV/TXT files call `/api/data/upload_csv`,
  - backend import returns full row count plus a preview sample,
  - target dropdown populates after backend import,
  - selecting target after backend import calls `/api/data/set_target` instead of overwriting the backend dataset with preview rows,
  - bottom CTA shows a visible disabled reason.
- Updated `server/main.py`:
  - default upload limit increased from 50 MB to 250 MB via `ATLAS_MAX_UPLOAD_BYTES`,
  - upload response now includes row count, columns, inferred target, selected columns, and `sample_rows`.
- Added `POST /api/data/set_target` in `server/core/metadata_router.py`.
- Added `tests/dataAcquisition.test.mjs`.
- Added `npm run test:data-acquisition`.

## Verification

- Backend health: `http://127.0.0.1:8001/api/health` returned `{"ok":true,"status":"running"}`.
- Frontend dashboard: `http://127.0.0.1:5174/dashboard` returned HTTP 200.
- Repository scan found no stale backend command aliases in package scripts, README, docs, scripts, tests, frontend, or backend source.
- Generated a temporary 60 MB CSV, which is above both the 25 MB browser cap and old 50 MB backend cap.
- Backend import accepted the 60 MB CSV and returned:
  - rows loaded: 94,608
  - columns: 62
  - inferred target: `Class`
  - preview rows: 5,000
  - max upload MB: 250

## Tests Run

- `npm run test:data-acquisition` passed.
- `npm run test:regression` passed.
- `npm run build:modeling` passed.

## Known Limitation

The Codex tool environment cannot operate the native Windows file picker directly. The large-file path was validated through the same backend endpoint the browser upload now calls, and the frontend health route was verified separately.

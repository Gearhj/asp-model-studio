# Phase 4 Architecture and Artifact Stability Report

Date: 2026-07-03

## Summary

Phase 4 focused on artifact stability, security hardening, report quality, and a safe Experimental Design architecture boundary. No existing workflow routes were removed. Predictive and Experimental Design behavior remains compatible with the current application.

## Implemented

### Artifact Storage

- Added `src/lib/artifactStorage.ts`.
- Added restore-status semantics:
  - Fully restored
  - Restored with dataset reload required
  - Restored with model rerun required
  - Restored with simulation summary only
  - Artifact missing
- Added `docs/ARTIFACT_STORAGE.md`.

### Project Import Validation

- Added `src/lib/projectImportValidation.ts`.
- Project imports now validate project name, project type, workflow ID, workflow steps, and current step.
- Invalid imports are rejected with inline UI messaging.

### Security and Data Handling

- Frontend upload guardrails:
  - 25 MB browser-preview limit
  - 250,000 row limit
  - 500 column limit
  - allowed/recognized extension checks
- Backend upload guardrails:
  - configurable byte, row, and column limits
  - CSV/TXT extension checks
  - friendly HTTP errors
- Removed wildcard CORS default; explicit localhost dev origins remain.
- Added report HTML sanitizer for unsafe tags, JavaScript URLs, and event handlers.
- Updated `docs/SECURITY_AND_DATA_HANDLING.md`.

### Report and Governance Cleanup

- Model Development Document now supports:
  - Executive Summary
  - Full Governance Package
  - Technical Appendix
- Added report readiness checklist.
- Added material decision summary.
- Filtered cross-problem experiment records so stale regression runs do not pollute classification documents and vice versa.
- Candidate model and feature-importance sections now render professional report tables.
- Added governance templates and decision journal policy docs.

### Experimental Design Architecture Boundary

- Added `src/features/experimental-design/analysis`.
- Added `src/features/experimental-design/components`.
- Added page modules under `src/features/experimental-design/pages`.
- Top-level route now enters the Experimental Design feature module.
- The existing `WorkflowPlaceholderStep.tsx` implementation is preserved behind the wrapper to avoid behavioral regression.

### Performance Safeguards

- Added in-memory local EDA correlation caching keyed by dataset shape and sample percent.
- Decision Journal localStorage cap reduced to avoid long-term storage bloat.
- Existing compact Monte Carlo and project persistence behavior remains in place.

## Verification

Passed:

- `npm run test:persistence`
- `npm run test:phase4`
- `npm run test:experimental-design`
- `npm run build:modeling`
- `npm run build`
- Clean-copy `npm run build` in `C:\Users\james\Projects\ATLAS\atlas-app`

Backend API smoke test:

- `GET /api/health`
- `POST /api/data/set_sample`
- `POST /api/model/train`
- `GET /api/eval/curves?model=logreg`

See `PHASE_4_BACKEND_WORKFLOW_VALIDATION.md`.

## Build Warnings

The Vite build still reports:

- large main chunk warning
- stale Browserslist/caniuse-lite data
- stale baseline-browser-mapping data

These are warnings, not build failures. Code splitting should be addressed in a later phase after the Experimental Design page bodies are fully extracted.

The clean ATLAS copy initially lacked `node_modules`; `npm install` was run there before the clean-copy build. `npm audit` reports 9 dependency vulnerabilities from the current package tree. No automated `npm audit fix` was applied because it may change dependency versions and should be reviewed separately.

A stale clean-copy file, `src/steps/Step07_Eval.tsx`, was removed because it was already deleted in the verified source workspace and caused the clean-copy TypeScript build to fail.

## Known Limitations

- Experimental Design page files currently wrap the existing implementation. The safe boundary is created, but full page-body extraction remains future work.
- Large model binaries and full row-level artifacts still need backend artifact registry support.
- Browser file-picker smoke testing was not performed from the shell; backend API validation was performed instead.
- True DOCX/PDF generation still relies on Word-compatible HTML and browser print unless a document writer is added.

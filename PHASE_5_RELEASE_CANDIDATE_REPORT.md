# Phase 5 Workflow Completion and Release Candidate Hardening Report

Date: 2026-07-03

## Summary

Phase 5 focused on release-candidate hardening rather than new product expansion. The main improvements were quota-safe persistence, predictive workflow guardrails, report formatting cleanup, material Decision Journal filtering, RFE caching, Experimental Design route splitting, and test coverage for critical restore/navigation behavior.

ATLAS builds successfully. Remaining warnings are documented and non-blocking for local release-candidate use.

## Files Changed

| File | Purpose |
|---|---|
| `src/apps/ModelingApp.tsx` | Lazy-loads the Experimental Design workflow route to reduce initial bundle size. |
| `src/lib/projectPersistence.ts` | Adds thin project fallback snapshots to avoid Recent Projects localStorage quota failures. |
| `src/lib/localProjects.ts` | Adds full -> compact -> thin registry write fallback logic. |
| `src/steps/WorkflowPlaceholderStep.tsx` | Adds minimal workflow-node persistence fallback when full node state exceeds browser quota. |
| `src/steps/Step01_DataAcquisition.tsx` | Adds rare-event target warning near target selection. |
| `src/steps/Step04_Outliers.tsx` | Adds fraud/anomaly guidance warning before outlier treatment decisions. |
| `src/lib/decisionJournal.ts` | Adds material-decision classification helper and uses it in summaries. |
| `src/steps/DecisionJournal.tsx` | Adds material/full timeline toggle and clearer audit-log summary metrics. |
| `src/lib/modelDevelopmentDocument.ts` | Converts experiment appendix from raw dump/Markdown style to professional report tables. |
| `src/lib/governanceReport.ts` | Converts candidate model, feature importance, and experiment appendix outputs to professional tables. |
| `src/lib/experimentalDesign.ts` | Carries Monte Carlo simulation evidence into Experiment Run Plan analysis text and interpretation. |
| `src/steps/Step09_Interpretation.tsx` | Adds RFE result caching per model and clearer RFE prerequisite messaging. |
| `tests/experimentalDesign.test.mjs` | Adds Experimental Design route-order and Monte Carlo -> Run Plan evidence tests. |
| `tests/persistence.test.mjs` | Adds thin-project persistence fallback test. |
| `DEPENDENCY_AUDIT.md` | Documents npm audit result, Python dependency situation, and security posture. |
| `PHASE_5_RELEASE_CANDIDATE_REPORT.md` | This release-candidate hardening report. |

## Bugs Fixed / Hardened

### Project Persistence

- Added a third-stage thin project registry fallback when localStorage quota blocks normal Recent Projects writes.
- Added a minimal workflow-node fallback for large page states such as Monte Carlo results.
- Preserves project metadata, workflow progress, current step, dataset metadata, and governed decisions while avoiding raw datasets, large chart payloads, and full simulation arrays.
- Existing persistence tests now cover thin fallback behavior.

### Predictive Modeling UX

- Data Acquisition now shows a rare-event warning when binary target event rate is below 1%.
- Outlier page now warns that fraud/anomaly tail values may be signal and should be reviewed before removal/capping.
- Model Training behavior already prevents duplicate submissions while training.
- Grid Search state is already sent to the backend as `grid_search` and `grid_search_level`.
- RFE now restores cached results for a selected model run and shows a visible prerequisite note when it cannot run.
- Scoring already includes prior-odds/Pozzolo-style correction language and PSI/VSI scope notes.

### Documentation / Reports

- Model Development Document and Governance Report appendices now avoid raw JSON dumps and raw Markdown pipe-table output in the touched sections.
- Candidate models, feature importance, and experiment appendices render as professional ATLAS tables.
- Material Decision Summary is separated from full audit history.
- Report HTML sanitizer remains active for generated report HTML.

### Decision Journal

- Default Decision Journal view is now material decisions.
- Full timeline remains available for audit review/export.
- Material entries include governed choices such as target selection, preprocessing decisions, split/balancing, model selection, champion selection, final model save, challenge responses, and project context updates.
- Routine UI noise stays out of executive/governance summaries.

### Experimental Design

- Added a route-level lazy split so Experimental Design loads as a separate module.
- Added tests for route progression:
  - Monte Carlo Simulation -> Experiment Run Plan
  - Experiment Run Plan -> ANOVA
  - ANOVA -> Optimization
  - Optimization -> Documentation
- Added shared-analysis coverage that verifies the Experiment Run Plan carries forward Monte Carlo readiness and wrong-winner risk.

## Validation Run

Commands run successfully:

| Command | Result |
|---|---|
| `npm run test:persistence` | Passed, 9 tests |
| `npm run test:phase4` | Passed, 3 tests |
| `npm run test:experimental-design` | Passed, 9 tests |
| `npm run build:modeling` | Passed |
| `npm run build` | Passed |
| `npm audit --json` | Passed, 0 vulnerabilities |

## Build Warning Status

| Warning | Status | Notes |
|---|---|---|
| Large Vite chunk | Improved, not eliminated | Main bundle reduced from about 1,083 KB to about 805 KB by lazy-loading Experimental Design; warning remains. |
| Stale Browserslist / caniuse-lite | Documented | Compatibility metadata is stale, but not a security issue. Defer to controlled dependency refresh. |
| Stale baseline-browser-mapping | Documented | Defer to controlled dependency refresh. |

## Dependency Audit Summary

See `DEPENDENCY_AUDIT.md`.

Key result: `npm audit` reports 0 vulnerabilities.

No automated dependency fixes were applied.

## Manual / Browser QA Status

Automated coverage passed for persistence, Experimental Design analysis, route mapping, report sanitizer, report readiness, and production builds.

The full interactive browser QA checklist from the Phase 5 brief was not completed in this pass. The current validated substitute is:

- Phase 4 backend workflow validation remains documented in `PHASE_4_BACKEND_WORKFLOW_VALIDATION.md`.
- Phase 5 added more persistence, route, report, and RFE hardening.
- A full browser pass should still be run before tagging a formal release candidate:
  - Predictive project creation, CSV upload, target selection, EDA, outliers, missing values, feature engineering, split, training, evaluation, interpretation/RFE, scoring, model document, save/reopen.
  - Experimental Design project creation through Documentation, including Monte Carlo and Run Plan evidence.
  - Project management create/reopen/duplicate/rename/delete/import/reject invalid import.

## Known Limitations

- Full Experimental Design page-body extraction is not complete. The feature boundary exists and the route is now lazy-loaded, but many page bodies still run through `WorkflowPlaceholderStep.tsx`.
- Main bundle warning remains because several predictive pages and shared report/chart utilities still load in the main shell.
- Browser compatibility metadata is stale until a network-enabled dependency-refresh pass updates it.
- Python requirements are split between broad root and narrow backend files; a clean hosted deployment dependency plan is documented but not implemented.
- Full browser file-picker QA was not completed in this pass.
- Backend large-artifact persistence still relies on compact summaries and references; row-level simulation artifacts are intentionally not stored in localStorage.

## Clean-Copy Sync Status

Completed. The verified source workspace was synced to:

`C:\Users\james\Projects\ATLAS\atlas-app`

Clean-copy validation run successfully:

| Command | Result |
|---|---|
| `npm run test:persistence` | Passed, 9 tests |
| `npm run test:experimental-design` | Passed, 9 tests |
| `npm run build` | Passed |

## Release Candidate Readiness

ATLAS is closer to a local release candidate:

- Core automated tests pass.
- Modeling build passes.
- npm dependency audit is clean.
- Storage bloat has stronger fallback handling.
- Decision Journal and report outputs are less noisy and more governance-oriented.

I would not tag a formal release candidate until the full browser QA checklist is completed. The clean ATLAS copy now builds from the synced source.

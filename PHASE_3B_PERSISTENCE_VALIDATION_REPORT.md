# ATLAS Phase 3B Persistence Validation Report

Date: 2026-07-03

## Scope

Phase 3B validated the compact browser persistence system under real workflow usage. The work stayed within the existing architecture and focused on save/reopen behavior, restore warnings, persistence diagnostics, automated coverage, and smoke testing.

## Changes Completed

### Automated Persistence Tests

Added `tests/persistence.test.mjs` and `npm run test:persistence`.

Coverage includes:

- Compact project snapshot creation.
- Quota-safe compaction of oversized registry artifacts.
- Predictive project snapshot save and restore.
- Experimental Design project snapshot save and restore.
- Corrupted Recent Projects registry handling.
- Missing artifact warning handling.
- Recent Projects repair/migration for legacy workflow evidence.

The test fixtures intentionally avoid storing full raw datasets.

### Restore Warning UX

Added a restore warning banner in the modeling app when a project is restored with compact summaries but large artifacts are intentionally absent.

Warnings explain that:

- Workflow decisions and compact summaries were restored.
- Raw dataset rows are not persisted as browser project artifacts.
- Dataset reload is required before retraining, rescoring, or regenerating full diagnostics.
- Model artifacts may require rerun even when champion summaries are restored.

### Settings Debug Panel

Expanded the Project Persistence Debug panel to show:

- Project ID.
- Snapshot size.
- Last saved time.
- Restore status.
- Missing artifacts.
- Local storage keys.
- Session storage keys.
- Workflow node keys.
- Missing workflow steps.
- Existing Save Now, Export Project, Repair Recent Projects, and Clear Local Project Cache controls.

## Predictive Modeling Save/Reopen Smoke Test

Manual UI smoke test performed in the browser:

- Created a new Predictive Modeling project named `Phase 3B Predictive Smoke`.
- Captured model ID `90331`.
- Filled Project Context fields, including business objective, intended use, target definition, population, observation window, performance window, false-positive cost, false-negative cost, AUC, and KS.
- Used the bottom workflow CTA from Project Context to Data Acquisition.
- Verified the project appeared in Recent Projects after browser reload.
- Reopened the project from Recent Projects.
- Confirmed Project Context restored the project name, model ID, and entered context fields.
- Confirmed Settings persistence debug panel displayed required debug fields.

Additional predictive page-load smoke checks:

- Outlier Detection page loaded without application error.
- Model Training page loaded and displayed Logistic Regression, Random Forest, Train Selected, and grid-search control.
- Interpretation page loaded and displayed the Run RFE button.
- Scoring page loaded without application error.
- Model Development Document page loaded without application error.

### Predictive Restore Notes

Native browser file upload could not be automated in this environment because the available browser-control API does not expose file-picker or `setInputFiles` behavior. The persistence layer itself is covered by automated tests that seed compact dataset, selected feature, preprocessing, training summary, and model-summary artifacts into storage and verify restore behavior.

Expected intentional limitations:

- Full raw dataset rows are not persisted in browser project snapshots.
- Full trained model objects are not persisted in browser project snapshots.
- Reloading source data is required before retraining, rescoring, or regenerating full diagnostics.
- Compact dataset previews, selected columns, preprocessing settings, training summaries, and workflow decisions are persisted.

## Experimental Design Save/Reopen Smoke Test

Manual UI smoke test performed in the browser:

- Created a new Experimental Design project named `Phase 3B Experimental Smoke`.
- Captured model ID `90332`.
- Used `Save Draft` on Project Context and confirmed it did not produce a browser alert.
- Used bottom navigation through:
  - Project Context -> Research Question
  - Research Question -> Factors
  - Factors -> Levels
  - Levels -> Blocking
  - Blocking -> Randomization
  - Randomization -> Sample Size
  - Sample Size -> Monte Carlo Simulation
  - Monte Carlo Simulation -> Experiment Run Plan
- Ran Monte Carlo Simulation.
- Confirmed Monte Carlo output rendered readiness/power/wrong-winner/launch recommendation fields.
- Confirmed Experiment Run Plan contained `Simulation Summary from Monte Carlo`, Monte Carlo readiness, and wrong-winner summary language.
- Reloaded the browser and verified the project appeared in Recent Projects.
- Reopened the project from Recent Projects.
- Confirmed it reopened at the current Run Plan route.
- Confirmed restored Factors, Levels, treatment-cell structure, Monte Carlo summary, and Run Plan simulation summary.

Terminal navigation smoke test:

- Experiment Run Plan -> ANOVA passed.
- ANOVA -> Optimization passed.
- Optimization -> Documentation passed.
- Documentation -> Overview passed via the actual terminal CTA label: `Save & Return to Overview`.

## Artifacts Intentionally Not Persisted

To avoid localStorage quota failures, the compact snapshot excludes or compacts:

- Full raw datasets.
- Full simulation iteration arrays.
- Full chart payloads.
- Large analysis snapshots.
- Full decision-journal event history.
- Full model objects.

Persisted instead:

- Project metadata.
- Workflow step completion and current step.
- Compact workflow node state.
- Compact Monte Carlo summaries and chart-ready aggregates.
- Compact training summaries.
- Compact experiment summaries.
- Compact dataset preview and selected columns.
- User decisions and governance text.

## Remaining Limitations

- Browser file-picker upload could not be manually automated with the available in-app browser API.
- Full end-to-end predictive retraining still requires a backend dataset reload after restoring a compact browser project.
- The Documentation final button label is `Save & Return to Overview`; Phase 3B route behavior is correct, but copy differs from the requested label `Documentation -> Overview`.

## Readiness

ATLAS is ready to proceed to Phase 4 architecture work from a persistence standpoint, with the caveat that large artifacts should move to IndexedDB or backend storage when full raw datasets, model binaries, and detailed simulation outputs need to survive browser restarts.

## Verification Results

Passed:

- `npm run test:persistence`
- `npm run test:experimental-design`
- `npm run build:modeling`
- `npm run build`

Build notes:

- Vite reported the existing large JavaScript chunk warning.
- Browserslist/caniuse-lite data is stale.
- These are non-blocking warnings and did not fail the build.

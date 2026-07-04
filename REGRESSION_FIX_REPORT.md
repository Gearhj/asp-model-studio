# ATLAS Regression Fix Report

Date: 2026-07-03

## Scope

This pass addressed the blocking regressions reported for ATLAS:

- Project saves failed because Recent Projects registry writes exceeded browser storage quota.
- Save-before-navigation blocked the user from advancing.
- Data Acquisition local uploads could fail when backend sync was unavailable.
- Atlas Guide rendered below Data Acquisition instead of in the right rail.
- Model Training model toggles were effectively limited by backend package availability.
- Grid Search did not clearly enable Search Depth.
- Go to Evaluation navigation could remain blocked after training.
- Dropdown and method selectors lacked concise decision guidance.

## Root Causes

1. Recent Projects stored full snapshots inline, including compacted workflow artifacts and large page state. This made the registry grow until localStorage quota was exceeded.
2. Navigation used a hard save path that treated save failures as fatal, even when a thin workflow snapshot would be enough to continue.
3. Data Acquisition coupled local browser preview persistence to backend sample sync, so backend failures interrupted the local workflow.
4. ModelingApp special-cased Step 1 into a single-column layout and rendered the Atlas Guide below the page.
5. Model Training excluded optional backend-unavailable algorithms from selectable keys, which made the model selector feel locked down and inconsistent.
6. Some diagnostics still assumed snapshots lived inside the Recent Projects registry.
7. Several dropdowns exposed option labels without explaining definition, use case, or governance impact.

## Changes Made

- Split project persistence into:
  - small Recent Projects registry: `atlas-local-projects`
  - project snapshots: `atlas-project-snapshot:{projectId}`
  - workflow node state: `atlas-workflow-node-state:{projectId}:{stepId}`
- Added compact/thin snapshot fallback for quota-safe saves.
- Changed save-before-navigation to continue after save warnings where possible.
- Updated Project Persistence debug output to read separated snapshot keys.
- Made Data Acquisition backend sync non-blocking when a local preview is already saved.
- Restored Atlas Guide to the right-side rail on Data Acquisition.
- Allowed selected model toggles to include optional algorithms; unavailable packages now show a warning but do not block selecting other models.
- Made Go to Evaluation save with the quota-tolerant path, navigate to `/step08`, and scroll to top.
- Added concise option guidance to:
  - Project Context project/model/deployment selectors
  - Data Acquisition target/provider/sampling selectors
  - Missing Value strategies
  - Outlier methods
  - Feature Engineering polynomial/scaling/encoding selectors
  - Balance & Split strategy and balancing options
  - Experimental Design shared method selectors, including Stratified Randomization
- Added `npm run test:regression`.

## Verification

Automated checks run in the source workspace:

- `npm run test:regression` - passed
- `npm run test:open-project` - passed
- `npm run test:persistence` - passed
- `npm run test:experimental-design` - passed
- `npm run test:phase4` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Automated checks run in the clean copy at `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run test:regression` - passed
- `npm run test:persistence` - passed
- `npm run test:open-project` - passed
- `npm run test:experimental-design` - passed
- `npm run build:modeling` - passed

Browser smoke checks run against `http://127.0.0.1:5174`:

- ATLAS loads at `/dashboard`.
- Data Acquisition shows Atlas Guide in the right column.
- Model Training loads with Train Selected and Go to Evaluation enabled in the current browser project state.
- Grid Search checkbox enables Search Depth.
- Go to Evaluation navigates to `/step08` and lands at top of page.

## Known Limitations

- Browser smoke testing did not open the OS file picker. Local CSV parsing and upload affordances are covered by the regression test.
- Backend model package availability is still environment-dependent. Optional model package failures should be reported per model without blocking the rest of the run.
- Existing Vite chunk-size warnings remain; they are performance warnings, not build failures.
- Browserslist/baseline-browser-mapping dependency freshness warnings remain unchanged.

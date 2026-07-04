# ATLAS Open Project, Save, and Reopen Hotfix Report

Date: 2026-07-03

## Hotfix Scope

This hotfix focused only on Open Project routing, save-before-navigation behavior, Recent Projects resilience, and project reopen reliability.

Out of scope work was intentionally deferred.

## Root Cause

The Open Project flow had three related reliability problems:

1. Some navigation targets pointed to workflow routes instead of the project launcher.
2. Save-before-navigation used stale workflow state instead of the active browser route, so a project opened from `/step01` or `/workflow/experimental-design/8` could be persisted with the wrong current step.
3. The Recent Projects registry did not expose a clear corrupted-registry repair path, and import/open errors could fail noisily instead of returning inline-safe failure states.

## Changes Made

### Project Persistence

File: `src/lib/localProjects.ts`

- Added route-aware step resolution from `window.location.pathname`.
- Added `saveActiveProjectBeforeNavigation(state)` so navigation can save safely without throwing browser alerts.
- Added `getLocalProjectsRegistryStatus()`.
- Added `repairLocalProjectsRegistry()`.
- Added corrupted-registry backup behavior using `atlas-local-projects-corrupt-backup-*`.
- Preserved compact project snapshot behavior and avoided large localStorage payloads.

### Open Project Page

File: `src/steps/ProjectUtilityPages.tsx`

- Open Project now shows Recent Projects from the local project registry.
- Added corrupted Recent Projects repair UI.
- Added inline import validation handling.
- Opening a project now loads the saved snapshot and navigates to the saved workflow stage.
- Removed mount-time save behavior that could overwrite the current route with stale state after landing on `/projects/open`.

### Navigation

Files:

- `src/components/Sidebar.tsx`
- `src/steps/Dashboard.tsx`

Updates:

- Sidebar Open Project link now targets `/projects/open`.
- Dashboard “Open Existing Project” now targets `/projects/open`.
- Both save the active project before navigation.

### Key Warning Cleanup

Files:

- `src/steps/ProjectOverview.tsx`
- `src/steps/WorkflowPlaceholderStep.tsx`

Updates:

- Fixed duplicate React key risks in project overview and model term rendering.

### Tests

Files:

- `tests/openProjectRoute.test.mjs`
- `package.json`

Updates:

- Added `npm run test:open-project`.
- Added 13 focused route/save/reopen tests.

## Automated Validation

Main workspace: `C:\Users\james\ds-workflow-starter`

- `npm run test:open-project`: pass, 13 tests
- `npm run test:persistence`: pass, 9 tests
- `npm run test:phase4`: pass, 3 tests
- `npm run test:experimental-design`: pass, 9 tests
- `npm run build:modeling`: pass
- `npm run build`: pass

Clean ATLAS copy: `C:\Users\james\Projects\ATLAS\atlas-app`

- `npm run test:open-project`: pass, 13 tests
- `npm run test:persistence`: pass, 9 tests
- `npm run test:phase4`: pass, 3 tests
- `npm run test:experimental-design`: pass, 9 tests
- `npm run build:modeling`: pass
- `npm run build`: pass

Build warnings observed in both locations are pre-existing nonblocking warnings:

- `baseline-browser-mapping` data is older than two months.
- `caniuse-lite` browser data is older than recommended.
- Vite reports a large main chunk after minification.

## Manual Browser Validation

Dev server tested at:

- `http://127.0.0.1:5174`

Backend health checked at:

- `http://127.0.0.1:8001/api/health`

Direct route smoke tests passed:

- `/dashboard`
- `/projects/open`
- `/step00`
- `/step01`
- `/step02`
- `/workflow/experimental-design/1`
- `/workflow/experimental-design/8`
- `/workflow/experimental-design/12`

Open Project navigation was manually tested from:

- Dashboard
- Predictive Project Context
- Predictive Data Acquisition
- Predictive Model Training
- Predictive Model Development Document
- Experimental Design Project Context
- Experimental Design Monte Carlo
- Experimental Design Documentation
- Settings

Expected result was confirmed each time:

- User lands on `/projects/open`.
- Recent Projects screen renders.
- No blank page or route error occurs.

## Predictive Save/Reopen Test

Created project:

- Project name: `Hotfix Predictive Save Reopen 20260703`
- Model ID: `73931`
- Workflow: Predictive Modeling

Validated:

- Project Context fields saved.
- Continue advanced to `/step01`.
- Open Project saved current state before navigation.
- Reopening the project returned to `/step01`.
- Saved Project Context language was still present when returning to `/step00`.
- Page scrolled to top after reopen.

## Experimental Design Save/Reopen Test

Created project:

- Project name: `Hotfix Experimental Save Reopen 20260703`
- Model ID: `73932`
- Workflow: Experimental Design

Validated:

- Project Context governance fields saved through Save Draft.
- Factors page fields saved through Save Draft.
- Levels page hierarchy saved through Save Draft.
- Open Project saved current state before navigation.
- Reopening returned to `/workflow/experimental-design/4`.
- Factor levels textarea restored.
- Treatment structure still rendered correctly.
- Page scrolled to top after reopen.

## Clean Copy Sync

The hotfix source files and test files were synced to:

`C:\Users\james\Projects\ATLAS\atlas-app`

The clean copy was then validated independently with the same test and build commands listed above.

## Known Limitations

- The browser console may still show historical messages from earlier testing because the in-app log view aggregates session output.
- The nonblocking Vite dependency-age and chunk-size warnings remain.
- No current Open Project, save-before-navigation, or reopen blocker was observed after this hotfix.


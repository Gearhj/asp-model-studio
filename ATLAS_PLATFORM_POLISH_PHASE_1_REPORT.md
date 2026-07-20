# ATLAS Platform Polish Phase 1 Report

## Scope

Implemented the first visual and UX polish pass across the shared ATLAS shell, Home dashboard, Project Overview, New Project, common step action handling, and reusable UI primitives.

## Completed Changes

- Added shared ATLAS design tokens and component classes in `src/index.css` for page backgrounds, cards, panels, buttons, tabs, metrics, status surfaces, and themed studio accents.
- Added reusable UI components under `src/components/ui`:
  - `AtlasCard`
  - `AtlasMetricCard`
  - `AtlasStatusBadge`
  - `AtlasProgressBar`
  - `AtlasDisclosure`
  - `AtlasEmptyState`
  - `AtlasTabs`
  - `AtlasPageHero`
- Reworked the global app header in `src/apps/ModelingApp.tsx` into a compact project and workflow bar with current step context, progress, mode switching, save status, and account controls.
- Refined `src/components/Sidebar.tsx` into clearer navigation groups with calmer active states, sticky behavior, and internal scrolling.
- Converted `src/components/StepShell.tsx` to use a sticky bottom action dock while preserving existing next-step routing, test IDs, custom click handlers, disabled reasons, and debug panels.
- Updated `src/components/StepPythonPanel.tsx` to match the platform card and button system without changing Python editing behavior.
- Redesigned `src/steps/Dashboard.tsx` as a practical operating home with a dark hero, first-use empty state, quick-access modules, current workflow status, escalation summary, monitoring snapshot, and workflow snapshot.
- Redesigned `src/steps/ProjectOverview.tsx` into tabbed sections for Summary, Workflow, Evidence and Governance, and Assets and Operations while preserving A/B Testing, Credit Risk Studio, analytics insight, evidence, documentation, and monitoring coverage.
- Redesigned `src/steps/NewProject.tsx` with a visual project type selector, sticky project detail panel, preserved Predictive Modeling Model ID requirement, preserved optional auto-generated IDs for other workflows, and preserved the custom workflow editor.
- Adjusted compact project artifact restore so an empty compact artifact snapshot does not wipe existing workflow node state.

## Preserved Behavior

- Existing routes and workflow navigation remain intact.
- Project start logic, project persistence, Recent Projects, access grant, project context save, and decision logging remain intact.
- Predictive Modeling still requires a Model ID before start.
- Non-predictive project types can still start with an automatically generated project identifier.
- Credit Risk Studio and A/B Testing static integration anchors remain available for downstream tests and governance pages.

## Validation

Passed:

- `npx tsc -b`
- `npm run build`
- `npm run test:project-types`
- `npm run test:experimentation`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:workflow-navigation-state`
- `npm run test:regression`
- `npm run test:user-management`
- `npm run test:dataset-library`
- `npm run test:analytics-workbench`
- `npm run test:model-documentation`
- `npm run test:evidence-graph`
- `npm run test:credit-risk-studio`

Build notes:

- Vite reports existing large chunk warnings.
- Browser data packages report existing age warnings for `baseline-browser-mapping` and `caniuse-lite`.

## Sync Status

Completed `npm run sync:atlas` after elevated retry. The first non-elevated attempt reported destination access denied and copied no files; the elevated retry completed with Robocopy code 3 and copied the changed files.

## Manual QA

Authenticated browser smoke QA was attempted against `http://127.0.0.1:5174/dashboard`, but the app was on the sign-in screen. Automated build and regression coverage passed.

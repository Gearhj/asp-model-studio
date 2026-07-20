# Predictive Modeling Project Context Refresh

Date: 2026-07-18

## Scope

Refreshed only the Predictive Modeling Project Context page (`/step00`) into a focused Step 0 mission-definition experience. The page no longer asks users to make premature data, validation, or split decisions before Data Acquisition and Balance & Split.

## Delivered

- Rebuilt the page around `Step 0: Define the Modeling Mission`.
- Added a live five-item readiness model:
  - Business Purpose
  - Intended Use
  - Target and Population
  - Time Windows
  - Reviewer Traceability
- Added a live Model Charter that updates from current user-entered content.
- Replaced generic model-type choices with professional financial-services modeling options.
- Kept the physical target column as `Pending Data Acquisition` until a dataset is selected later.
- Kept validation as `Pending Data Review` until a current Balance & Split contract exists.
- Removed visible `Validation Plan` and premature TRAIN / TEST / OOT selection from Project Context.
- Added grounded ATLAS AI drafting support with explicit proposal, accept, and dismiss flow.
- Added accepted AI draft metadata so accepted language is auditable.
- Added mission summary actions:
  - `Copy Summary`
  - `Save to Evidence Center`
  - `Draft Documentation Language`
- Added page persistence to local project context and backend project-context persistence.
- Added evidence and decision-journal writes when Project Context is marked complete.
- Updated the Atlas Guide so Project Context guidance is specific to the new Step 0 flow.
- Updated workflow copy so shared navigation describes the new mission-first design.

## Files Changed

- `src/steps/Step00_ProjectContext.tsx`
- `src/lib/projectContext.ts`
- `src/components/LLMWritingAssist.tsx`
- `src/components/CopilotCard.tsx`
- `src/config/workflows.ts`
- `tests/predictiveProjectContext.test.mjs`
- `tests/predictiveProjectContextWow.test.mjs`
- `tests/regression.test.mjs`
- `package.json`

## Browser QA

Manual browser QA created a new Predictive Modeling project and verified:

- Blank Project Context starts with all five readiness items incomplete.
- Target column shows `Pending Data Acquisition`.
- Validation shows `Pending Data Review`.
- No visible `Validation Plan` selector is rendered.
- Save, Validate, Mark Page Complete, and Continue affordances render correctly.
- ATLAS AI proposal flow renders `Proposed draft`, `Accept draft`, and `Dismiss`.
- A screenshot was captured at:
  - `artifacts/qa/predictive-project-context-wow/01-new-project-context.png`

## Automated Validation

Passed:

- `npx tsc -b`
- `npm run test:predictive-project-context-wow`
- `npm run test:predictive-project-context`
- `npm run build`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:regression`
- `npm run test:sqlite-persistence`

## Notes

- The legacy `validationDesign` field remains migration-compatible in stored project context, but it is not rendered or used as an authoritative Project Context decision.
- Balance & Split remains the authoritative source for validation design and split status.
- Data Acquisition remains the authoritative source for dataset binding and the physical target column.

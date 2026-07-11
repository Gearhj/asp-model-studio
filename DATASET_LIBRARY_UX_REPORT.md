# Dataset Library UX Report

## Phase 10J Dataset Library Table-First UX

Dataset Library now defaults to an enterprise Detailed View instead of a card-heavy layout.

## Behavior Changed

- Default view is `Detailed View`, persisted with `atlas-dataset-library-view-mode`.
- `Card View` remains available as a secondary option.
- More than nine datasets strongly prefer Detailed View.
- The primary dataset display is now a compact, horizontally scrollable table.

## Enterprise Dataset Table

The table shows one row per dataset with:

- Dataset Name
- Type
- Rows
- Columns
- Versions
- Owner
- Created
- Updated
- Linked Projects
- Latest Version
- Source Type
- Status
- Actions

## Sorting / Filtering / Search

- Default sort: Updated descending.
- Sortable fields: Dataset Name, Type, Rows, Columns, Updated, Created, Owner, and Status.
- Search matches dataset name, owner, source type, linked project, dataset type, and latest version.
- Filters support Training, Test, OOT, Scored Outputs, Regression, Classification, Uploaded, Metadata-only, Linked to Current Project, and Unlinked.
- Owner filter is available when owner metadata exists.

## Actions

Rows use compact actions:

- Open
- Analytics
- Chart
- Diagnostics for scored-output datasets
- Link to Project
- Export Metadata
- Delete

Model Diagnostics remains visible only for scored outputs.

## Tests Run

- `npm run test:dataset-library`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:model-diagnostics`
- `npm run test:chart-studio`
- `npm run test:analytics-workbench`
- `npm run test:regression`
- `npm run build:modeling`
- `npm run build`

## Manual QA Status

Manual browser QA was not completed in this automated pass. Static tests, TypeScript compilation, and production builds passed in the source workspace.

## Clean-Copy Sync

- Synced verified source changes to `C:\Users\james\Projects\ATLAS\atlas-app` with `npm run sync:atlas`.
- `server/artifacts` remained intentionally excluded from sync.
- Clean copy verification passed:
  - `npm run test:open-project`
  - `npm run test:dataset-library`
  - `npm run build`

## Known Limitations

- Dataset table rows use compact inline actions rather than a dedicated row action menu.
- Dataset Library still depends on Dataset Library preview/sample metadata; full warehouse-scale browsing remains a later infrastructure item.

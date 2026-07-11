# SQL Data Studio Phase 12 Report

## Summary

Phase 12A adds the first governed SQL Data Studio capability to ATLAS. The initial release focuses on safe, local Dataset Library preview queries with lineage, reusable saved queries, Excel export, and registration of SQL results back into the governed Dataset Library.

## New Route

- `/sql-data-studio`
- Sidebar label: `SQL Data Studio`
- Placement: Projects navigation, directly after Dataset Library

## Backend Implementation

Added `server/sql_studio/`:

- `sql_engine.py`: read-only SQLite preview execution over Dataset Library preview artifacts.
- `sql_router.py`: FastAPI endpoints for validation, preview execution, saved queries, result registration, and Excel export.
- `sql_store.py`: local saved-query persistence under `server/artifacts/sql_studio/queries`.

Registered router in `server/main.py`.

## API Endpoints

- `POST /api/sql-studio/run-preview`
- `POST /api/sql-studio/validate`
- `POST /api/sql-studio/queries`
- `GET /api/sql-studio/queries`
- `GET /api/sql-studio/queries/{query_id}`
- `DELETE /api/sql-studio/queries/{query_id}`
- `POST /api/sql-studio/register-result`
- `POST /api/sql-studio/export/excel`

## Frontend Implementation

Added:

- `src/steps/SqlDataStudio.tsx`
- `src/lib/sqlDataStudio.ts`

The page includes:

- Data source selector
- Dataset Library preview mode
- External connector placeholders for Snowflake, BigQuery, Postgres, Oracle, SQL Server, Teradata, and SAS/Viya
- Table browser with aliases
- Saved query library
- SQL editor
- Query validation
- Preview results
- Schema profiling
- Lineage summary
- Excel export
- Governed result registration

## Dataset Library Integration

SQL result datasets are registered with:

- `datasetRole=sql_result`
- `sourceType=sql_studio`
- upstream dataset references
- source SQL query
- linked project ID when available

Dataset Library now shows:

- SQL Result filter
- SQL Result badges
- Open in SQL Data Studio action

Dataset Detail now shows:

- SQL Data Studio Lineage panel
- source dataset aliases
- source dataset versions
- registered SQL query
- shortcuts to SQL Data Studio, Analytics Workbench, and Chart Studio

## Guardrails

SQL Preview v1 is intentionally constrained:

- Only read-only `SELECT` and `WITH` queries are allowed.
- Mutating SQL keywords are blocked.
- Multiple statements are blocked.
- Missing limits are wrapped with a preview limit.
- Query execution uses in-memory SQLite over compact Dataset Library preview artifacts.

External warehouse connectors are represented as metadata placeholders only in this phase.

## Known Limitations

- SQL execution is limited to Dataset Library preview/sample rows.
- Full warehouse pushdown is not implemented yet.
- Parameterized SQL execution is not implemented yet.
- Cross-database connector execution is not implemented yet.
- Result registration stores the preview result, not full warehouse-scale output.
- SQL permissions are governed by ATLAS dataset access, not external warehouse access.

## Tests

Added:

- `tests/sqlDataStudio.test.mjs`
- `npm run test:sql-data-studio`

Source verification:

- `npx tsc -b --pretty false` - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:dataset-library` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:user-management` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

## Clean-Copy Sync

The verified source changes should be synced to:

- `C:\Users\james\Projects\ATLAS\atlas-app`

using:

- `npm run sync:atlas`

Clean-copy verification:

- `npm run sync:atlas` - passed
- `npm run test:sql-data-studio` from clean copy - passed
- `npm run build` from clean copy - passed

Runtime artifacts note:

- `server/artifacts` was intentionally excluded by the sync script, consistent with the ATLAS clean-copy policy.

## Phase 12B SQL IDE and Financial Services Template Library

Phase 12B upgrades SQL Data Studio from a page-style form into an IDE-style workbench.

### IDE Layout

The page now uses a three-pane workbench layout:

- Left Object Explorer
- Center SQL editor and bottom results panel
- Right SQL Assistant

The bottom panel includes:

- Results
- Schema
- Profile
- Messages
- Query History
- Lineage

### Object Explorer

The Object Explorer now shows:

- Data Sources
- Dataset Library Tables
- expandable table columns
- SQL Results
- Saved Queries
- External Connectors

Saved queries display query name, description, source type, tables used, created/updated dates, status, tags, and actions.

### SQL Editor Upgrades

The editor now includes:

- query tabs
- larger monospace editor
- line numbers
- cursor position
- current query status
- keyboard shortcut hints
- toolbar actions for validation, preview, formatting, save, registration, export, copy, and reset

Keyboard shortcuts documented in the UI:

- `Ctrl+Enter`: Run Preview
- `Ctrl+S`: Save Query
- `Ctrl+Shift+F`: Format SQL

### SQL Assistant

The right panel includes tabs for:

- Templates
- Financial Services Tasks
- Governance
- Help

The lightweight language assistant includes insertable snippets for:

- SELECT *
- GROUP BY
- LEFT JOIN
- CASE WHEN
- date filters
- count distinct
- window rank

### Financial Services Task Library

Added task categories:

- Customer / Account Analytics
- Credit Risk
- Fraud / AML
- Marketing / Campaigns
- Model Development
- Monitoring
- Data Quality
- Demo Dataset Examples

Template examples include:

- Customer 360 summary
- Account balance snapshot
- Delinquency rate by segment
- Charge-off rate by vintage
- High-risk transaction review
- Velocity rules
- Campaign population waterfall
- Response rate by campaign
- Train/Test/OOT population summary
- Feature missingness summary
- Monthly score distribution
- PSI input table
- Null rate by column
- Duplicate key check
- REG_TRAIN income band profile
- CLASS_TRAIN class distribution
- CLASS_TRAIN rare-event summary

### Column Mapping

Templates now include required-column metadata and a column mapping panel. ATLAS performs best-effort mapping for common financial-services fields such as:

- customer ID
- account ID
- date column
- amount column
- target column
- score column
- segment column
- campaign column

If a template lacks required mapped fields, the UI shows a warning and allows manual mapping.

### Query History

Each preview run records compact local history:

- query text
- timestamp
- status
- runtime
- row count
- tables used
- validation warnings

History does not store result sets.

### Messages Panel

The Messages tab shows validation status, preview caps, selected tables, runtime, row counts, and warnings.

### Governance Panel

The Governance tab documents:

- read-only SELECT-only guardrail
- preview/sample-row limitation
- no production warehouse execution
- lineage requirement
- scored output warning
- PII/sensitive data reminder
- current query lineage

### Register Result UX

Registration now appears in a governed panel showing:

- dataset name
- dataset role: SQL Result
- preview row count
- source datasets
- lineage warning
- post-registration links to Dataset Detail, Analytics Workbench, Chart Studio, and Model Documentation Studio

### Phase 12B Tests

Additional static coverage was added to `tests/sqlDataStudio.test.mjs` for:

- IDE layout
- Object Explorer
- SQL editor toolbar
- bottom panel tabs
- right SQL Assistant tabs
- financial-services task categories
- template required columns
- template insert actions
- column mapping
- messages
- query history
- governance
- saved query actions

Source verification:

- `npx tsc -b --pretty false` - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:dataset-library` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:chart-studio` - passed
- `npm run test:open-project` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Clean-copy verification:

- `npm run sync:atlas` - passed
- `npm run test:sql-data-studio` from `C:\Users\james\Projects\ATLAS\atlas-app` - passed
- `npm run build` from `C:\Users\james\Projects\ATLAS\atlas-app` - passed

Manual browser QA:

- Not run in this pass. Static checks, TypeScript, source build, and clean-copy build passed.

### Phase 12B Known Limitations

- The SQL editor is a styled textarea, not a full Monaco/CodeMirror editor.
- SQL highlighting is limited to formatting and assistant snippets.
- Query history is compact browser state, not a backend audit artifact.
- External connectors remain metadata placeholders.
- Full warehouse-scale SQL execution remains future work.

## Phase 12C SQL Data Studio IDE UX Redesign

Phase 12C converts SQL Data Studio from a vertically stacked workflow page into a compact IDE-style workbench.

### Layout Changes

The page now uses a fixed-height workbench shell with:

- top toolbar for Validate, Run Preview, Format, Save Query, Register Result, Export, Copy SQL, and Focus Mode
- left Object Explorer around 260px wide
- central SQL editor and bottom results panel
- right SQL Assistant around 320px wide
- internal pane scrolling instead of one long page scroll

Focus Mode hides the Object Explorer and SQL Assistant so the editor and results area can use the full workspace.

### Duplicate Interface Cleanup

The previous long-form duplicate action areas were removed. The page now has:

- one central SQL editor
- one primary Run Preview action
- one Register Result entry point
- one compact bottom results panel
- no separate full-page registration section

### Object Explorer

The Object Explorer now has compact tabs:

- Tables
- Saved
- Results
- Connectors

Table columns are shown only when a table is expanded. Saved Queries include Open, Run, Duplicate, Rename, Delete, and Export SQL. External connectors clearly state that connector execution is not configured in the local build, so they do not look broken or like dataset problems.

### Editor Changes

The center pane now includes:

- active query tab
- query title and description
- one SQL editor with line numbers
- keyboard hints for `Ctrl+Enter`, `Ctrl+S`, and `Ctrl+Shift+F`
- cursor and status footer
- bottom tabs for Results, Schema, Profile, Messages, Query History, and Lineage

### Assistant Changes

The SQL Assistant now uses tabs:

- Templates
- Financial
- Mapping
- Governance
- Help

Financial Services SQL Tasks are presented as compact accordions with one category expanded by default. Selecting a task shows required columns, mapping gaps, generated SQL preview, and insert actions in the right pane instead of creating a separate page section.

### Register Result UX

Register Result now opens a compact governed form inside the right pane. The form shows dataset name, role, preview row count, source datasets, linked project, lineage warning, registration action, and post-registration navigation links.

### Phase 12C Tests

Source verification:

- `npx tsc -b --pretty false` - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:dataset-library` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:chart-studio` - passed
- `npm run test:open-project` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Clean-copy verification:

- `npm run sync:atlas` - passed
- `npm run test:sql-data-studio` from `C:\Users\james\Projects\ATLAS\atlas-app` - passed
- `npm run build` from `C:\Users\james\Projects\ATLAS\atlas-app` - passed

### Phase 12C Manual Browser QA

Manual browser QA was not run during this pass. Static test coverage validates the compact IDE shell, object explorer tabs, right assistant tabs, registration panel, focus-mode state, single editor, and single primary Run Preview action.

### Phase 12C Known Limitations

- The SQL editor remains a styled textarea rather than Monaco or CodeMirror.
- External warehouse connectors remain metadata placeholders.
- SQL preview still runs over Dataset Library preview/sample rows.
- Register Result stores preview-scale output, not warehouse-scale output.
- Manual browser QA remains recommended before marking Phase 12 fully product-complete.

## Phase 12D Full IDE Layout Reset

Phase 12D fixes the remaining layout issue from Phase 12C. The SQL Data Studio component had an IDE-style internal layout, but the global modeling app shell still reserved a right-side Atlas Guide column. That constrained SQL Data Studio to a narrow center column and made the page feel stacked instead of like a true IDE.

### Layout Reset

The `/sql-data-studio` route now uses the full workbench width inside the ATLAS app shell. The route intentionally hides the global Copilot side column because SQL Data Studio already has its own purpose-built SQL Assistant pane.

The SQL workbench now uses an explicit grid:

- left Object Explorer: `260px`
- center SQL editor: flexible minimum `520px`
- right SQL Assistant: `320px`
- bottom Results panel: spans the center and assistant columns

The shell height is tied to the viewport with internal pane scrolling, so the page no longer relies on a long stacked document layout.

### One-Editor Rule

The page now keeps exactly one editable SQL editor. Financial Services template SQL is shown as a read-only template preview in the SQL Assistant. Users can insert or replace the editor SQL from that preview, but the preview itself is not editable and does not create a second SQL workspace.

### Object Explorer

Data Source selection is now part of the left Object Explorer instead of a separate top form. The Object Explorer includes:

- Data Source
- tables and columns
- saved queries
- SQL results
- connector placeholders

This keeps data selection, table browsing, saved queries, and connector context in the IDE navigation pane.

### SQL Assistant

The SQL Assistant now contains:

- selected template preview near the top
- Financial Services SQL Tasks as compact assistant content
- required columns and mapping guidance
- governance and help tabs
- compact Register Result form

Financial Services SQL Tasks are no longer a large central page section.

### Results Panel

The bottom panel sits directly below the editor and spans the center and assistant columns. It contains:

- Results
- Schema
- Profile
- Messages
- Query History
- Lineage

### Focus Mode

Focus Mode hides the Object Explorer and SQL Assistant and expands the SQL editor/results workspace. Browser QA confirmed the editor width expands substantially when Focus Mode is enabled.

### Phase 12D Manual Browser QA

Manual browser QA was run against `http://127.0.0.1:5174/sql-data-studio`.

Verified:

- SQL Data Studio opens after sign-in.
- Object Explorer, center SQL editor, and SQL Assistant render side by side.
- Data Source is inside Object Explorer.
- There is exactly one editable SQL textarea.
- There is exactly one `Run Preview` action.
- There is exactly one `Register Result` action.
- Selected Template Preview appears in the SQL Assistant as read-only content.
- Financial Services SQL Tasks appear in the SQL Assistant, not as a central stacked page.
- Results, Schema, Profile, Messages, Query History, and Lineage tabs are visible in the bottom panel.
- `Replace editor SQL` updates the single editor.
- `Run Preview` executes through the preview path and updates page state.
- Messages tab is accessible.
- Register Result opens the governed registration path and shows the lineage warning.
- Focus Mode hides Object Explorer and SQL Assistant and expands the editor.

One app-shell note remains: the persistent ATLAS left navigation can still be taller than the viewport, but the SQL Studio workbench itself now fits as a side-by-side IDE.

### Phase 12D Tests

Source verification:

- `npx tsc -b --pretty false` - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:dataset-library` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:chart-studio` - passed
- `npm run test:open-project` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Clean-copy verification:

- `npm run sync:atlas` - passed
- `npm run test:sql-data-studio` from `C:\Users\james\Projects\ATLAS\atlas-app` - passed
- `npm run build` from `C:\Users\james\Projects\ATLAS\atlas-app` - passed

### Phase 12D Known Limitations

- The SQL editor remains a styled textarea rather than Monaco or CodeMirror.
- External warehouse connectors remain metadata placeholders.
- SQL preview still runs over Dataset Library preview/sample rows.
- Register Result stores preview-scale output, not warehouse-scale output.
- Full warehouse pushdown remains future work.

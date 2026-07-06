# ATLAS Phase 8 Report - Analytics Workbench v1

## Summary

Phase 8 adds the first ATLAS Analytics Workbench capability. The implementation focuses on governed dataset exploration, saved insights, basic charting, rule-based recommendations, and local Python execution against user-provided preview/sample code. This is intentionally not a full Chart Studio, AutoML layer, or warehouse-scale execution engine.

## Implemented

- Added `/analytics` route and sidebar navigation entry named **Analytics Workbench**.
- Added a Workbench page that lists the signed-in user's accessible Dataset Library assets.
- Added dataset version selection, schema/profile summary, preview-driven column explorer, target relationship view, group comparison, correlation/association review, and data quality review.
- Added basic visual outputs:
  - histogram
  - categorical bar chart
  - target relationship ranking
  - group comparison bar chart and table
  - top correlation bars
  - missingness/cardinality/quality status cards
- Added rule-based Insight Assistant with:
  - Generate Key Takeaways
  - Suggest Follow-Up Analysis
  - Generate Python Follow-Up
  - Save Insight
- Added Python follow-up editor using the existing local `/api/python/run` endpoint.
- Added backend analytics insight artifact store under `server/artifacts/analytics`.
- Added analytics endpoints:
  - `GET /api/analytics/insights`
  - `POST /api/analytics/insights`
  - `GET /api/analytics/insights/{insight_id}`
  - `DELETE /api/analytics/insights/{insight_id}`
  - `POST /api/analytics/audit-run`
  - `GET /api/analytics/diagnostics`
- Enforced Dataset Library ACLs before listing, creating, reading, or deleting insights.
- Added analytics audit events for insight save/delete, analysis run, and denied access.
- Added saved analytics insights to Dataset Detail.
- Added project-linked analytics insights to Project Overview.
- Added analytics checks into System Diagnostics through the Dataset Library diagnostics payload.

## UX and Code Workspace Upgrade

- Added explicit Business Question actions:
  - Save Business Question
  - Clean Up with ATLAS LLM
  - Generate Analysis Plan
  - Clear
- Added deterministic ATLAS cleanup for v1. It improves rough question text without relying on a live LLM backend.
- Added structured analysis plan generation based on the question, selected dataset, target, available columns, and secondary dataset status.
- Redesigned the Workbench page around sandbox sections:
  - Question
  - Data
  - Analyze
  - Code
  - Insights
- Added a SQL Workspace with:
  - Generated SQL
  - User-Edited SQL
  - Copy Code
  - Validate SQL Template action
  - Save Code Snippet through the Insight Assistant
- Generated SQL now includes the selected dataset name, version, row/column metadata, and a logical `atlas_dataset.*` reference.
- SQL remains preview-only in v1. The UI no longer presents it as executable SQL; validation confirms the template is non-empty, references the selected logical dataset, and represents selected schema columns.
- Added dataset-aware Python templates with selected dataset name/version and preview/sample context.
- Updated `/api/python/run` to accept a compact `context` payload and inject:
  - `preview_rows`
  - `primary_preview_rows`
  - `secondary_preview_rows`
  - `dataset_name`
  - `version_id`
- Fixed the Analytics Python execution path to use `sys.executable`, inherit the normal environment with `os.environ.copy()`, and avoid `PYTHONHOME` or stripped `PATH` settings that caused `init_import_site` failures.
- The execution endpoint now creates `df = pd.DataFrame(preview_rows)` automatically when pandas is available and returns a clear warning/fallback if pandas cannot initialize.
- Added secondary dataset selection and join-template support for:
  - inner
  - left
  - right
  - outer
  - append/union
- Saved insights now include business question, analysis plan, generated Python, generated SQL, selected dataset references, and linked project metadata.
- Added business-question-driven recommended analyses for regression, classification, time/date, and data quality questions.
- Added **Pivot Table Builder v1** in the Analyze section:
  - Rows selector
  - Optional Columns selector
  - Numeric Values selector
  - Aggregation selector for count, sum, mean, median, min, max, std dev, and event rate
  - Top-N control
  - Auto-bin numeric row fields into quantile bands
  - Pivot result table
  - Pivot summary chart
  - Plain-English readout
- Generated Python now includes pivot code when a pivot is configured, including `pd.qcut(..., duplicates="drop")` for numeric quantile binning.
- Generated SQL now includes a preview-only pivot template with explicit notes that numeric quantile binning syntax depends on the connected SQL engine.
- Added **Save Pivot as Insight**. Saved pivot insights include the business question, dataset/version references, pivot configuration, preview output summary, generated Python, generated SQL, and project metadata.

## Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\main.py server\\analytics\\analytics_router.py server\\analytics\\analytics_store.py server\\datasets\\dataset_registry.py`
- `.\\.venv\\Scripts\\python.exe -m py_compile server\\python_execution.py`
- `npm run test:analytics-workbench`
- `npm run test:user-management`
- `npm run test:dataset-library`
- `npm run test:data-acquisition`
- `npm run test:persistence`
- `npm run test:regression`
- `npm run build:modeling`
- `npm run build`

All listed checks passed. The Vite build still reports the existing large chunk and stale browser data warnings.

## Clean Copy Sync

Verified changes were synced from:

`C:\\Users\\james\\ds-workflow-starter`

to:

`C:\\Users\\james\\Projects\\ATLAS\\atlas-app`

Clean-copy verification after sync:

- `npm run test:analytics-workbench`
- `npm run build`

Both checks passed.

## Manual QA

Manual browser QA passed on the local development instance:

1. `/analytics` loaded after local admin sign-in.
2. `REG_TRAIN` was available and selected.
3. Business question was saved successfully.
4. Run User Python returned successful execution with:
   - `ATLAS Analytics Workbench Python smoke test passed.`
   - `df.shape`
   - `df.head()`
5. Validate SQL Template displayed preview-only guidance and confirmed the selected logical dataset reference.
6. Pivot was configured with Rows = `MedInc`, auto-bin enabled, Values = `MedHouseVal`, Aggregation = `mean`.
7. Pivot result table, chart, and readout rendered.
8. Save Pivot as Insight created a `pivot_table` insight in the Workbench.
9. The saved pivot insight appeared on Dataset Detail for `REG_TRAIN`.

## Known Limitations

- Workbench computations use dataset profile and preview/sample rows, not full warehouse-scale data.
- Python execution is local-development-only and uses the existing `/api/python/run` endpoint.
- SQL execution is preview-only in v1. Generated SQL is a governed analysis template until a backend SQL engine is connected.
- Saved Python snippets are not yet merged into notebook export.
- Charting is intentionally lightweight and component-native for v1.
- Insight artifacts are compact JSON records, not a full collaborative notebook or BI semantic layer.

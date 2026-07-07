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
  - Clean Up Question
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
- SQL now executes `SELECT` statements against selected dataset preview/sample rows using an in-memory SQLite backend endpoint.
- The SQL workspace button is now **Run SQL on Preview**.
- The SQL result panel renders returned columns, rows, row count, runtime, and clear blocked-query errors.
- Full warehouse-scale SQL execution is still deferred; v1 SQL execution is intentionally limited to preview/sample rows.
- Added dataset-aware Python templates with selected dataset name/version and preview/sample context.
- Updated `/api/python/run` to accept a compact `context` payload and inject:
  - `preview_rows`
  - `primary_preview_rows`
  - `secondary_preview_rows`
  - `dataset_name`
  - `version_id`
- Fixed the Analytics Python execution path to use `sys.executable`, inherit the normal environment with `os.environ.copy()`, and avoid `PYTHONHOME` or stripped `PATH` settings that caused `init_import_site` failures.
- The execution endpoint now creates `df = pd.DataFrame(preview_rows)` automatically when pandas is available and returns a clear warning/fallback if pandas cannot initialize.
- Successful Python runs now hide non-fatal bootstrap/import-path stderr noise instead of showing scary traceback text in a green success state.
- If Python returns code 0 with meaningful stderr, the UI labels the result as **Python completed with warnings**.
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
- Generated SQL now uses executable preview table names such as `REG_TRAIN` and keeps the logical `atlas_dataset.*` reference in comments.
- Generated pivot SQL is a single executable `SELECT` against preview rows when possible. Numeric quantile binning remains documented as SQL-engine-dependent.
- Added **Save Pivot as Insight**. Saved pivot insights include the business question, dataset/version references, pivot configuration, preview output summary, generated Python, generated SQL, and project metadata.

## SQL Preview Execution Controls

- Added backend endpoint: `POST /api/analytics/sql/run`.
- Loads primary preview rows into `primary_dataset` and a sanitized dataset alias such as `REG_TRAIN`.
- Loads secondary preview rows into `secondary_dataset` and a sanitized secondary alias when available.
- Maps generated logical references such as `atlas_dataset.REG_TRAIN_v_...` to the in-memory preview table.
- Allows only a single `SELECT`.
- Blocks unsafe or mutating SQL, including `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`, `PRAGMA`, and multiple statements.
- Applies a hard result limit when no explicit `LIMIT` is supplied.

## Phase 8B Multi-Language Code Workspace

- Added shared code workspace foundation:
  - `src/components/code/CodeWorkspacePanel.tsx`
  - `src/components/code/CodeLanguageTabs.tsx`
  - `src/components/code/CodeExecutionResult.tsx`
  - `src/lib/codeExecution.ts`
- Replaced the Analytics Workbench Python/SQL-only code section with tabs for:
  - Python
  - SQL
  - R
  - SAS
- Each language now shows an honest support badge:
  - Python: executable
  - SQL: preview SQL
  - R: executable only if diagnostics detect Rscript; otherwise template only
  - SAS: executable only if SASPy and SAS connection configuration are available; otherwise template only
- R and SAS do not show fake execution. Template-only modes clearly state that code is generated for export or external execution.
- Added language-specific saved code insights:
  - Save Python as Insight
  - Save SQL as Insight
  - Save R as Insight
  - Save SAS as Insight
- Saved code insights include the language, dataset/version references, business question, pivot configuration, selected fields, and generated/user-edited code.

## Python Diagnostics and Browser Execution

- Added backend endpoint: `GET /api/python/diagnostics`.
- Diagnostics return:
  - Python executable
  - Python version
  - platform
  - working directory
  - temp execution directory
  - temp directory status
  - Python subprocess startup status
  - `site` import status
  - pandas import status
  - stdout/stderr capture status
  - Rscript detection
  - SASPy detection
  - environment warnings
- Browser QA confirmed the Analytics Python tab now executes the smoke test successfully.
- Browser stdout included:
  - `ATLAS Analytics Workbench Python smoke test passed.`
  - `(100, 9)`
  - `df.head()` output for `REG_TRAIN`
- No fatal Python startup traceback appeared in the browser output.

## R and SAS Templates

- Generated R now includes:
  - dataset name
  - version ID
  - business question
  - selected target context
  - pivot code using `dplyr`
  - join template when a secondary dataset and join key are selected
- Generated SAS now includes:
  - dataset name
  - version ID
  - business question
  - `PROC CONTENTS`
  - `PROC MEANS`
  - `PROC CORR`
  - `PROC SGPLOT`
  - pivot-style `PROC RANK` and `PROC MEANS`
  - `PROC SQL` join template when a secondary dataset and join key are selected
- SAS remains template-only unless SASPy and a SAS connection are configured.

## Pivot Column Auto-Binning

- Added independent pivot controls:
  - Auto-bin numeric row fields into quantiles
  - Auto-bin numeric column fields into quantiles
- Pivot matrix generation now supports row and column quantile bands.
- Browser QA confirmed:
  - Rows = `MedInc`
  - Auto-bin rows = enabled
  - Columns = `HouseAge`
  - Auto-bin columns = enabled
  - Values = `MedHouseVal`
  - Aggregation = `mean`
  - Result rendered as a `MedInc band` by `HouseAge band` pivot matrix.
- Generated Python, SQL, R, and SAS templates update to reflect row and column binning intent.

## Diagnostics Added

- Added System Diagnostics checks for:
  - SQL preview execution
  - R workspace template/execution status
  - SAS workspace template/SASPy status
  - code insight store writability
- R and SAS unavailability do not fail overall diagnostics; they are reported as template-only or unavailable depending on the local environment.

## Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\main.py server\\analytics\\analytics_router.py server\\analytics\\analytics_store.py server\\datasets\\dataset_registry.py`
- `.\\.venv\\Scripts\\python.exe -m py_compile server\\python_execution.py`
- `npx tsc -b`
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
5. Successful Python output did not show fatal traceback text or a stderr error panel.
6. `SELECT * FROM REG_TRAIN LIMIT 10;` ran successfully and returned a SQL result table.
7. `DROP TABLE REG_TRAIN;` was blocked with a clear SELECT-only error message.
8. Pivot was configured with Rows = `MedInc`, auto-bin enabled, Values = `MedHouseVal`, Aggregation = `mean`.
9. Generated pivot SQL used `FROM REG_TRAIN`, `AVG(MedHouseVal) AS mean_MedHouseVal`, and `COUNT(*) AS n`.
10. Generated pivot SQL ran successfully and returned a SQL result table.
11. Save Pivot as Insight created a `pivot_table` insight in the Workbench.
12. The saved pivot insight appeared on Dataset Detail for `REG_TRAIN`.
13. Python, SQL, R, and SAS tabs appeared in the shared Code Workspace.
14. Python smoke test ran successfully in the browser with `REG_TRAIN` preview context.
15. R tab showed selected dataset/version and honest template/execution availability.
16. SAS tab showed selected dataset/version and honest template-only status.
17. Pivot column auto-binning produced a `MedInc band` by `HouseAge band` matrix.
18. Generated Python, SQL, R, and SAS code reflected row and column binning.
19. Save SAS as Insight created a `sas_code_snippet` insight.
20. The saved SAS code insight appeared on Dataset Detail for `REG_TRAIN`.

## Known Limitations

- Workbench computations and SQL execution use dataset profile and preview/sample rows, not full warehouse-scale data.
- Python execution is local-development-only and uses the existing `/api/python/run` endpoint.
- SQL execution is limited to safe `SELECT` statements over preview/sample rows in local memory.
- R execution is enabled when `Rscript` is detected locally. If `Rscript` is missing, ATLAS remains honest and shows template-only guidance.
- SAS execution is enabled only when SASPy and a licensed/configured SAS runtime are available. Otherwise, ATLAS remains template-only and provides setup guidance.
- Saved Python snippets are not yet merged into notebook export.
- Charting is intentionally lightweight and component-native for v1.
- Insight artifacts are compact JSON records, not a full collaborative notebook or BI semantic layer.
- Future work: replace legacy page-specific Python panels with the shared multi-language Code Workspace component.

## Phase 8C R/SAS Runtime Configuration

Implemented the Phase 8C runtime configuration pass for the Analytics Workbench.

### Language-Specific Result State

- Python, SQL, R, and SAS now maintain independent execution result state.
- SQL preview tables render only inside the SQL tab.
- Switching from SQL to SAS no longer shows stale SQL result rows under the SAS template.
- Switching back to SQL preserves the SQL result under the SQL tab.
- Result summaries now carry language-specific status, runtime, stdout/stderr, and return information.

### Runtime Diagnostics UI

Added a `Code Runtime Configuration` panel to the Analytics Workbench showing:

- Python executable
- Python version
- pandas status
- SQL preview engine status
- `Rscript` path
- R version / R execution availability
- SASPy install status
- SAS configuration status
- SAS execution availability

The `Refresh Runtime Diagnostics` button rechecks local runtime availability without reloading the page.

### R Execution Endpoint

Added:

`POST /api/code/r/run`

Behavior:

- Detects `Rscript` with `shutil.which("Rscript")`.
- Writes selected preview rows to a temporary CSV.
- Prepends an ATLAS R runtime prelude that loads the preview into `df`.
- Runs the submitted R code with timeout protection.
- Captures stdout, stderr, runtime, and return code.
- Returns clear unavailable guidance when `Rscript` is not installed.

Manual browser QA on this machine detected `Rscript`; the R smoke test succeeded with:

- `ATLAS R smoke test passed.`
- `Rows: 100  Columns: 9`
- `head(df)` output.

### SAS Execution Endpoint

Added:

`POST /api/code/sas/run`

Behavior:

- Detects SASPy availability and configuration.
- Does not start a SAS session during normal page load.
- If SASPy/configuration is unavailable, returns `status: "unavailable"` with clear setup guidance.
- If SASPy/configuration is available, the endpoint is prepared to load preview rows into a SAS `WORK` table and submit SAS code.
- The frontend shows SAS as `Template only` unless SASPy and a licensed/configured SAS runtime are available.

Manual browser QA on this machine showed SAS as template-only, which is expected because SASPy/licensed SAS execution is not configured.

### Generated R/SAS Code Updates

Generated R now includes:

- dataset name
- version ID
- `df` usage
- smoke-test output
- `summary(df)`
- pivot code using `dplyr::ntile()` and `dplyr::n()` when pivot settings are configured

Generated SAS now includes:

- dataset name
- version ID
- export table comment such as `atlas.REG_TRAIN`
- preview execution table comment such as `work.reg_train`
- executable preview-oriented `PROC CONTENTS`, `PROC MEANS`, `PROC CORR`, `PROC SGPLOT`, pivot, and join examples using the `WORK` table

### Phase 8C Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\python_execution.py`
- `npx tsc -b`
- `npm run test:analytics-workbench`
- `npm run test:user-management`
- `npm run test:dataset-library`
- `npm run test:persistence`
- `npm run build:modeling`
- `npm run build`

All source-folder checks passed. The Vite build still reports the existing stale browser data and large chunk warnings.

### Phase 8C Manual QA Results

Manual browser QA passed on `http://127.0.0.1:5174/analytics`:

1. Analytics Workbench loaded with `REG_TRAIN` selected.
2. Runtime diagnostics panel rendered Python, SQL, R, and SAS status.
3. SQL `SELECT * FROM REG_TRAIN LIMIT 10;` returned a table under the SQL tab.
4. Switching to SAS removed SQL table output from the visible SAS tab.
5. R tab showed executable status because `Rscript` is available.
6. `Run R` succeeded and returned stdout with the ATLAS R smoke test, row count, column count, and `head(df)`.
7. SAS tab showed template-only status with SASPy/licensed-runtime guidance.
8. `Validate Template` for SAS returned structured unavailable guidance, not a fake execution result.
9. `Refresh Runtime Diagnostics` showed a visible refreshed status.
10. `Save SAS as Insight` showed a visible save confirmation.

### Phase 8C Known Limitations

- R execution depends on local `Rscript` availability and runs only against preview/sample rows.
- SAS execution requires SASPy plus a licensed/configured SAS runtime or SAS Viya environment.
- SAS is intentionally not faked when unavailable.
- Workbench execution remains local-development oriented and is not an enterprise sandbox.
- Full warehouse-scale execution is still deferred; SQL/R/SAS operate against preview/sample context in this phase.

## Phase 8D High-Priority SAS Runtime Setup

Implemented the high-priority SAS runtime setup pass because SAS is a primary coding language for ATLAS users.

### SASPy Installed but Config Missing Diagnosis

The live local backend now reports:

- SASPy installed: yes
- SASPy version: detected from the Python environment
- SASPy module path: detected
- SASPy package config file: detected
- SAS execution: template-only until a real SAS connection test passes

ATLAS no longer treats “SASPy installed” as equivalent to “SAS executable.” A SAS session must start successfully before the Workbench changes from `Validate SAS Template` to `Run SAS`.

### SAS Runtime Setup Panel

Added a dedicated `SAS Runtime Setup` panel inside Analytics Workbench > Code Runtime Configuration.

The panel shows:

- SASPy installed status
- SASPy version
- SASPy module path
- detected SAS config files
- detected SAS config names
- active cfgname
- active cfgfile
- execution mode
- last connection test
- last SAS error
- setup guidance for Local SAS, remote SAS server, SAS Studio / Viya, and export-only usage

Controls added:

- SAS execution mode
- SASPy cfgname
- SASPy cfgfile path
- Save SAS Runtime Settings
- Test SAS Connection
- Reset to Template Only

### SAS Runtime Config Files

Added:

- `server/artifacts/config/sas_runtime.json`
- `server/artifacts/config/sas_runtime.example.json`

The config stores only non-secret runtime metadata:

- cfgname
- cfgfile path
- execution mode
- update timestamp/user
- last connection-test status
- last connection-test error

ATLAS does not store SAS passwords, tokens, or secrets.

### Backend Endpoints

Added:

- `GET /api/code/sas/diagnostics`
- `POST /api/code/sas/settings`
- `POST /api/code/sas/test-connection`

Updated:

- `POST /api/code/sas/run`

Behavior:

- `template_only` and `external_export` modes return neutral template guidance.
- `saspy_config` mode requires SASPy plus a successful `Test SAS Connection`.
- SAS run requests stay unavailable until a real SAS session has passed the connection test.
- cfgfile paths are validated when provided.
- cfgname accepts only safe text.
- error strings are sanitized to avoid exposing secrets.

### Template Validation Neutral State

Changed SAS template validation from a red error-style panel to neutral blue guidance.

Template-only validation now says:

`SAS template validated. SAS execution is not configured. Use this code in your external SAS environment, or configure SASPy to run SAS inside ATLAS.`

This avoids making template-only SAS export look like an application failure.

### Manual QA Results

Manual local QA passed:

1. `/analytics` loaded.
2. `SAS Runtime Setup` appeared in Code Runtime Configuration.
3. SASPy showed installed.
4. SAS execution remained template-only because no connection test has passed.
5. `Validate SAS Template` showed neutral blue guidance, not a red error.
6. SQL output did not appear under the SAS tab.
7. Saving template-only SAS settings succeeded.
8. Saving a nonexistent cfgfile path was rejected with a readable error.
9. Template-only connection test returned neutral guidance.
10. R/Python/SQL behavior remained unchanged.

### Phase 8D Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\python_execution.py server\\analytics\\analytics_store.py`
- `npx tsc -b`
- `npm run test:analytics-workbench`

Additional full test/build verification and clean-copy sync were run after the implementation pass.

### Phase 8D Known Limitations

- SAS execution is not marked executable unless `Test SAS Connection` starts a real SAS session.
- The current machine has SASPy installed, but ATLAS remains template-only until a valid cfgname/cfgfile can start a licensed SAS runtime.
- ATLAS does not store credentials. Credentials must be handled by SASPy configuration or external enterprise authentication.
- The setup flow supports local development/runtime configuration; enterprise secrets management is intentionally out of scope for this phase.

## Phase 8E ATLAS SAS-Compatible Mode

Changed SAS support so the default SAS tab experience is ATLAS SAS-Compatible Mode, not a licensed SASPy runtime assumption.

### Product Decision

Default SAS behavior is now:

- SAS-compatible
- executable
- no SAS license required
- no SASPy required
- no Java, SAS Studio, SAS Viya, or local SAS installation required
- runs a supported SAS-style subset through the local ATLAS Python execution engine

The licensed SAS bridge remains available, but it is now explicitly optional and collapsed under `Advanced: Licensed SAS Bridge`.

### Backend Implementation

Added:

- `server/code_execution/sas_compatible.py`
- `POST /api/code/sas-compatible/run`

The SAS-compatible endpoint accepts submitted SAS-style code and dataset preview context, loads the selected dataset as `work.reg_train`, and returns:

- execution status: `success`, `partial`, or `error`
- stdout/stderr
- rendered result tables
- unsupported statement warnings
- translated Python summary
- runtime in milliseconds

Unsupported syntax does not crash the application. It returns a partial result with an explicit unsupported-statement warning.

### Supported SAS-Compatible Syntax

Supported v1 statements:

- `PROC CONTENTS`
- `PROC MEANS`
- `PROC FREQ`
- `PROC CORR`
- `PROC PRINT`
- limited `PROC SQL SELECT ... FROM ... LIMIT ...`
- `PROC RANK`
- limited `DATA` step with `SET` and simple assignments

Supported DATA step assignments:

- `new_column = existing_column`
- `new_column = numeric_literal`
- `new_column = existing_column + numeric_literal`
- `new_column = existing_column - numeric_literal`
- `new_column = existing_column * numeric_literal`
- `new_column = existing_column / numeric_literal`

This is intentionally not full SAS compatibility.

### Generated SAS Template Updates

Generated SAS now targets ATLAS SAS-Compatible Mode:

- clearly states `no SAS license required`
- uses `work.<dataset>` as the available table
- defaults to supported procedures only
- removes unsupported default `PROC SGPLOT`
- includes optional `PROC RANK` and grouped `PROC MEANS` when pivot binning is configured

### UI Updates

Analytics Workbench now shows:

- `SAS Mode: ATLAS SAS-Compatible`
- `Executable`
- `No SAS license required`
- SAS tab badge: `SAS-compatible`
- button: `Run SAS-Compatible Code`
- result panel with SAS-compatible tables, unsupported warnings, translated Python, runtime, and status

Code Runtime Configuration now distinguishes:

- `SAS-Compatible Engine: Available`
- supported PROCs: `CONTENTS, MEANS, FREQ, CORR, PRINT, SQL, RANK`
- optional `Licensed SAS Bridge`
- SASPy installed/not installed

### Why SASPy Bridge Is Optional

SASPy is still useful for organizations that already have a licensed SAS runtime and want ATLAS to submit code to that environment. It is no longer required for ordinary SAS-tab usage.

### Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\python_execution.py server\\code_execution\\sas_compatible.py server\\analytics\\analytics_store.py`
- `npx tsc -b`
- `npm run test:analytics-workbench`
- direct SAS-compatible executor smoke test for `PROC CONTENTS`, `PROC MEANS`, `PROC FREQ`, `PROC CORR`, `PROC PRINT`, `PROC SQL`, `PROC RANK`, grouped `PROC MEANS`, and unsupported `PROC SGPLOT`
- live backend endpoint smoke test against `POST /api/code/sas-compatible/run`
- `npm run test:user-management`
- `npm run test:dataset-library`
- `npm run test:persistence`
- `npm run build:modeling`
- `npm run build`
- `npm run sync:atlas`
- clean copy: `npm run test:analytics-workbench`
- clean copy: `npm run build`

All source-folder checks passed. The build still reports existing Browserslist/baseline data age and large chunk warnings.

### Manual QA Results

Backend-level manual smoke QA passed for the SAS-compatible executor. The live backend endpoint returned successful `PROC CONTENTS` and `PROC MEANS` result tables from preview rows. Browser UI QA was not completed in this pass.

Recommended browser QA:

1. Open `/analytics`.
2. Select `REG_TRAIN`.
3. Open the SAS tab.
4. Confirm the badge says `SAS-compatible`.
5. Confirm licensed SAS setup is optional/collapsed.
6. Run generated SAS-compatible code.
7. Confirm `PROC CONTENTS` and `PROC MEANS` result tables appear.
8. Run `proc print data=work.reg_train(obs=10); run;`.
9. Confirm 10 rows appear.
10. Run `proc corr data=work.reg_train; var MedInc HouseAge MedHouseVal; run;`.
11. Confirm a correlation table appears.
12. Run unsupported syntax and confirm a partial warning, not an app crash.

### Known Limitations

- ATLAS SAS-Compatible Mode supports only the documented v1 subset.
- It is designed for analytics workflow previews, not full production SAS batch execution.
- `PROC SQL` is limited to simple SELECT statements.
- DATA step support is intentionally narrow.
- Chart-oriented SAS procedures such as `PROC SGPLOT` are not supported yet.
- Optional SASPy bridge still requires a licensed/configured SAS runtime and successful connection test.

### Clean-Copy Sync Confirmation

Verified changes were synced from `C:\Users\james\ds-workflow-starter` to `C:\Users\james\Projects\ATLAS\atlas-app` with `npm run sync:atlas`.

Clean-copy verification passed:

- `npm run test:analytics-workbench`
- `npm run build`

The sync script intentionally excludes `server/artifacts`; SAS runtime artifact config remains managed separately from source sync.

## Phase 8F Insight Assistant Multi-Language Upgrade

Completed the Insight Assistant polish pass after Python, SQL, R, and SAS-compatible execution were available.

### Multi-Language Generated-Code Actions

The Insight Assistant now supports all four workbench languages:

- Use Generated Python
- Use Generated SQL
- Use Generated R
- Use Generated SAS

The action area was reorganized into:

- primary actions: key takeaways and analysis plan
- compact generated-code actions: Python, SQL, R, SAS-compatible
- save/export actions

Each generated-code action switches the Code Workspace to the matching language tab and loads the generated code into the user-edited editor.

### SAS-Compatible Code Path

The SAS generated-code action loads the ATLAS SAS-Compatible template. It does not target the optional licensed SASPy bridge by default.

### Saved Code Snippet Metadata

Saved code snippets now include language-aware metadata:

- language
- language label
- active language
- active code
- generated code
- user-edited code
- generated Python
- generated SQL
- generated R
- generated SAS
- dataset and version references
- business question
- pivot configuration
- active analysis context
- linked project ID
- created timestamp
- created by

Saved snippet titles are readable, including `SAS-compatible code snippet: <dataset>`.

### Saved Findings Cleanup

The Saved Findings panel now includes:

- language badge
- insight type
- created time
- dataset name
- compact title
- simple filters: All, Insights, Code, Pivot, Questions, Plans

SAS snippets are labeled `SAS-compatible`.

### Clean Up Question and LLM Hook

Renamed the question-cleanup button to `Clean Up Question`.

The local build now explains that cleanup uses deterministic ATLAS cleanup unless `ATLAS_LLM_ENDPOINT` is configured.

Added:

- `POST /api/llm/cleanup-question`
- environment variable hook: `ATLAS_LLM_ENDPOINT`

When no endpoint is configured, the endpoint returns:

- `source: deterministic`
- polished deterministic cleanup text
- message: `Question cleaned up using deterministic ATLAS cleanup.`

No LLM behavior is faked.

### Export Insight Payload Readiness

Exported insight payloads now include:

- generated Python
- generated SQL
- generated R
- generated SAS
- user-edited Python
- user-edited SQL
- user-edited R
- user-edited SAS
- active language
- active code
- business question
- analysis plan
- dataset references
- pivot configuration and preview

### Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\python_execution.py`
- `npx tsc -b`
- `npm run test:analytics-workbench`
- direct backend endpoint check for `POST /api/llm/cleanup-question`
- `npm run test:user-management`
- `npm run test:dataset-library`
- `npm run test:persistence`
- `npm run build:modeling`
- `npm run build`

All source-folder checks passed. The build still reports existing Browserslist/baseline data age and large chunk warnings.

### Manual QA Results

Backend-level manual QA passed for deterministic question cleanup:

- request: `How does population density affect home values?`
- response source: `deterministic`
- response message: `Question cleaned up using deterministic ATLAS cleanup.`

Browser UI QA was not completed in this implementation pass.

### Clean-Copy Sync Confirmation

Verified Phase 8F changes were synced from `C:\Users\james\ds-workflow-starter` to `C:\Users\james\Projects\ATLAS\atlas-app`.

Clean-copy verification passed:

- `npm run test:analytics-workbench`
- `npm run build`

### Known Limitations

- `ATLAS_LLM_ENDPOINT` is an optional future hook; no hosted LLM integration is required.
- Saved Findings filters are intentionally lightweight and not a full insight manager.
- PDF/notebook export is out of scope for this pass.

## Phase 8G - Office Export Package

### Backend Export Endpoints

Added real Office export endpoints for the Analytics Workbench:

- `POST /api/analytics/export/excel`
- `POST /api/analytics/export/word`
- `POST /api/analytics/export/powerpoint`

The endpoints generate native Office files without requiring Microsoft Office or LibreOffice.

### Export Dependencies

Added backend dependencies:

- `openpyxl`
- `python-docx`
- `python-pptx`

The active source virtual environment was updated and direct export generation was verified for `.xlsx`, `.docx`, and `.pptx`.

### Export Contents

The export payload now includes:

- business question and cleaned question
- analysis plan
- dataset name, dataset ID, version, target, preview row count, linked project
- pivot configuration and pivot result rows
- SQL preview results
- SAS-compatible result tables
- Python output
- R output
- generated Python, SQL, R, and SAS-compatible code
- user-edited Python, SQL, R, and SAS-compatible code
- saved insight metadata when exporting from Saved Findings
- governance notes and limitations
- created timestamp and created-by field

### Excel Workbook

The Excel export creates these sheets:

- Summary
- Analysis Plan
- Pivot Results
- SQL Results
- SAS-Compatible Results
- Python Output
- R Output
- Generated Code
- Dataset Metadata
- Governance Notes

Sheets use frozen headers, bold header rows, wrapped cells, and basic auto-sizing.

### Word Document

The Word export includes:

- title and creation metadata
- Business Question
- Executive Summary
- Dataset Context
- Analysis Plan
- Key Findings
- Pivot Results
- SQL Results
- SAS-Compatible Results
- Python/R Output Summary
- Generated Code Appendix
- Governance and Limitations

### PowerPoint Deck

The PowerPoint export includes readable summary slides for:

- title
- business question
- dataset context
- executive summary
- analysis plan
- pivot summary
- SAS-compatible summary
- SQL summary
- code appendix overview
- governance and limitations

### Frontend Export Controls

Added Office export controls in:

- Insight Assistant
- Pivot Table Builder output
- Code Workspace result area
- Saved Findings cards

V1 exports the full current analysis package from each button, while including the relevant current result or saved finding context.

The original JSON export remains available from the Insight Assistant for debugging and lightweight interchange.

### Phase 8G Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\analytics\\analytics_router.py server\\analytics\\export_utils.py`
- `npx tsc -b`
- `npm run test:analytics-workbench`
- direct Office export utility smoke test for `.xlsx`, `.docx`, and `.pptx`
- `npm run test:user-management`
- `npm run test:dataset-library`
- `npm run test:persistence`
- `npm run build:modeling`
- `npm run build`
- `npm run sync:atlas`

Clean-copy verification in `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run test:analytics-workbench`
- `npm run build`

All Phase 8G verification commands passed. The Vite build still reports existing stale Browserslist/baseline data and large chunk warnings.

### Phase 8G Known Limitations

- Report-level export buttons generate the full analysis package. Module-level analytical cards now generate result-specific Excel workbooks.
- Word and PowerPoint chart rendering is summary/table oriented in v1; chart images are not embedded yet.
- Exports are based on the current Workbench preview/result state. Warehouse-scale execution output should be connected separately when available.

## Phase 8G Export UX Refinement

### Export Model

Refined the Analytics Workbench export UX so export formats match the artifact type:

- Module-level analytical results export to Excel only.
- Full report exports support Excel, Word, and PowerPoint.
- Saved Findings use a compact Export menu with Excel, Word, and PowerPoint because they are shareable artifact packages.

### Module-Level Excel Exports

Added a reusable module export component:

- `src/components/export/ExportResultActions.tsx`

Added result-level Excel endpoint:

- `POST /api/analytics/export/result/excel`

Supported result types:

- `column_explorer`
- `target_relationship`
- `group_comparison`
- `data_quality`
- `pivot`
- `sql_result`
- `sas_compatible_result`
- `r_result`
- `python_result`

### Analytical Module Coverage

Added `Export to Excel` to:

- Column Explorer
- Target Relationship Explorer
- Group Comparison
- Data Quality Review
- Pivot Table Builder
- active Code Workspace result area when a Python, SQL, R, or SAS-compatible result is available

### Pivot Export Cleanup

The Pivot Table Builder no longer shows Word or PowerPoint buttons. It now exposes a single module-level `Export to Excel` action.

### Result Workbook Structure

Module-level Excel exports include:

- Summary
- Result Data
- Metadata

Where useful, additional sheets are generated:

- Chart Data
- Configuration
- Warnings
- STDOUT
- STDERR
- Translated Python

SAS-compatible exports write each SAS-compatible result table to its own sheet when table data is available.

### Report-Level Exports

The Insight Assistant keeps the report-level `Export Analysis` area with:

- Export to Excel
- Export to Word
- Export to PowerPoint

These exports produce the full current analysis package.

### Tests Run

- `.\\.venv\\Scripts\\python.exe -m py_compile server\\analytics\\analytics_router.py server\\analytics\\export_utils.py`
- `npx tsc -b`
- `npm run test:analytics-workbench`
- direct module-level Excel smoke test for Column Explorer, Target Relationship, Group Comparison, Data Quality, Pivot, and SAS-compatible result exports

### Manual QA Results

Browser QA was not completed in this pass. Backend and static checks confirmed the expected export placement and valid `.xlsx` generation.

### Acceptance Status

- Every primary analytical module has a module-level Excel export action.
- Pivot Table Builder no longer exposes Word or PowerPoint.
- Word and PowerPoint remain available only for full report and saved finding exports.
- SAS-compatible result tables can be exported to Excel.

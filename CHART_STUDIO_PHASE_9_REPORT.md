# ATLAS Chart Studio Phase 9A Report

## Summary

Phase 9A adds ATLAS Chart Studio at `/chart-studio`. Chart Studio lets users select Dataset Library assets, choose chart types, assign data roles, preview analytical charts from preview/sample rows, read a rule-based ATLAS interpretation, generate reproducible Python/SQL/R/SAS-compatible code, save charts as governed insights, and export chart data to Excel.

## Phase 9B SAS-Style Designer Redesign

Phase 9B redesigns Chart Studio into a SAS ODS Graphics Designer-style workspace while preserving the Phase 9A data, save, export, and governance plumbing.

The updated workspace now includes:

- A top Chart Studio header with selected dataset/version, preview-row warning, save status, and compact project context.
- A left designer rail for Dataset, Data Roles, Chart Properties, Filters, and Preview Scope.
- A center Graph Gallery with visual chart thumbnails, gallery tabs, working/coming-soon badges, and best-use guidance.
- A larger Preview Canvas with Refresh Preview, Export Chart Data to Excel, Save Chart as Insight, chart preview, and chart data table.
- A right analytical panel with ATLAS interpretation, recommended next charts, saved charts, and export package actions.
- A compact generated-code drawer with Python, SQL, R, and SAS-compatible tabs plus Copy Code.

## Phase 9B Graph Gallery

The graph gallery is organized into SAS-style families:

- Basic
- Grouped
- Analytical
- Matrix
- Panels
- Custom

Working v1 previews:

- Scatter Plot
- Line Plot
- Histogram
- Box Plot
- Bar Chart
- Correlation Heatmap
- Pareto
- Waterfall
- Control Chart
- Dual Axis
- Sankey

Coming-soon charts remain visible but disabled so users can see the intended roadmap without selecting unsupported chart types.

## Phase 9C Data Role Availability and Numeric Binning

Phase 9C fixes Chart Studio behavior for all-numeric datasets such as `REG_TRAIN`.

Implemented:

- Chart cards now distinguish `Working`, `Coming soon`, `Needs data`, `Needs roles`, `Needs category`, `Needs source and target`, and `Unsupported by current data`.
- Working charts remain selectable even when roles are incomplete; the preview canvas shows a friendly "Select roles to preview this chart" message.
- Only true coming-soon charts are disabled.
- Category and Color Group role selectors now include option groups:
  - Categorical fields
  - Numeric fields as discrete categories
  - Binned numeric fields
  - Generated fields
- Color Group always includes `None`.
- All-numeric datasets can use numeric fields binned into quantiles as category/color roles.
- The left designer rail now includes binning controls:
  - Enable numeric binning for category roles
  - Number of bins
  - Bin method: quantile or equal width
- Binned role selections create generated field names such as `MedInc_band`.

Supported binned-role preview behavior:

- Bar chart groups by generated bands and can aggregate numeric measures.
- Pareto chart groups by generated bands, sorts by value, and calculates cumulative percent.
- Box plot can use generated bands as the group role.
- Scatter plot can use generated bands as the color group role.
- Sankey can use generated bands as source or target roles.

Generated code now reflects binned numeric roles:

- Python uses `pd.qcut`.
- SQL includes production-engine guidance comments for exact binning syntax.
- R uses `dplyr::ntile`.
- SAS-compatible code uses `PROC RANK` before summary procedures.

## Phase 9D Advanced Analytical Chart Families

Phase 9D adds v1 advanced analytical chart families for model development, validation, monitoring, forecasting, EDA, and presentation evidence.

New working analytical charts:

- Residual Diagnostics
- Lift / Decile
- Forecast
- Survival
- Data Profile
- Data Profile Matrix
- Grouped Bar
- Grouped Box Plot
- Grouped Scatter
- Panel by Category
- Small Multiples

Residual Diagnostics:

- Role controls: actual value, predicted value, optional observation/order, optional segment.
- Derived fields: residual, absolute residual, squared residual, percent error.
- Preview includes residual vs predicted, actual vs predicted, residual histogram, and fit summary.
- Fit summary includes N, MAE, RMSE, MSE, R-squared, mean residual, median residual, and residual standard deviation.

Lift / Decile:

- Role controls: score/probability, actual outcome, positive class value, optional weight, number of deciles.
- Preview computes sorted deciles, count, positives, response rate, cumulative positives, cumulative capture rate, and lift.
- Preview includes lift bars and a decile table.

Forecast:

- Role controls: time/order, measure, optional group, aggregation, forecast horizon.
- Preview aggregates historical values and adds a simple linear-trend forecast.
- This is explicitly a preview trend, not a production forecasting model.

Survival:

- Role controls: duration/time-to-event and event indicator.
- Preview computes a basic Kaplan-Meier style survival curve from preview rows.
- This is v1 survival preview support, not a full survival modeling suite.

Data Profile / Matrix:

- Role controls: numeric variables, optional target, optional group.
- Preview summarizes missingness, distinct count, mean, median, standard deviation, min/max, and target correlation.

Grouped and Panel charts:

- Grouped Bar, Grouped Box, and Grouped Scatter support grouped/segmented review.
- Panel by Category and Small Multiples provide a simple faceted preview grid.
- Binned numeric category and color roles remain supported.

Generated code updates:

- Residual diagnostics generate Python, SQL, R, and SAS-compatible residual-prep code.
- Lift / Decile generates Python, SQL, R, and SAS-compatible decile-prep code.
- Forecast generates simple trend/aggregation prep code across Python, SQL, R, and SAS-compatible output.
- Survival generates v1 survival data-prep guidance/code.
- Data Profile generates summary/statistical profile code.

## Implemented Chart Types

Working in v1:

- Bar chart
- Line chart
- Scatter plot
- Histogram
- Box plot
- Correlation heatmap
- Pareto chart
- Waterfall chart
- Control chart
- Dual-axis chart
- Sankey chart

Displayed as coming soon:

- Stacked bar chart
- Heatmap
- Lift / decile chart
- Residual diagnostic chart
- Relationship/network edge list chart

## Dataset Integration

Chart Studio uses Dataset Library metadata, versions, profiles, and preview rows. Users can select a primary dataset and version, optional secondary dataset, optional secondary version, optional join key, and linked project context.

Boundary for this phase: Chart Studio v1 computes previews from Dataset Library preview/sample rows. Warehouse-scale chart execution is intentionally deferred.

## Role Assignment Behavior

Role controls change by chart type. Examples:

- Bar and Pareto: category, measure, aggregation, top-N.
- Scatter: X numeric, Y numeric, optional color and label.
- Histogram: numeric variable and bins.
- Box plot: measure and group.
- Correlation heatmap: numeric variable multi-select.
- Control: time/order and measure.
- Dual-axis: X axis, left Y, right Y, aggregation.
- Sankey: source, target, weight.

## Generated Code Behavior

Chart Studio generates:

- Python: pandas and matplotlib-oriented chart code.
- SQL: chart data-prep query using the selected dataset/version reference.
- R: base R aggregation with optional ggplot2 comments.
- SAS-compatible: PROC MEANS / PROC FREQ style summary code. If ATLAS renders the visual, the SAS-compatible code generates the chart data.

## Saved Chart Insights

Saved chart insights use the existing analytics insight store with `analysisType: chart_studio`. They include chart type, title, dataset ID/name, version, business question, role assignments, chart data, interpretation, generated code, project link, and metadata.

Saved chart insights appear in:

- Chart Studio Saved Charts
- Dataset Detail saved insights
- Project Overview saved insights

## Excel Export Behavior

`POST /api/charts/export/excel` returns an `.xlsx` workbook with:

- Summary
- Chart Data
- Role Assignments
- Generated Code
- Interpretation
- Metadata

Image export is not included in v1.

## Diagnostics

Chart Studio diagnostics are included in System Diagnostics through the dataset diagnostics aggregation. Checks cover:

- Chart Studio route registered
- Chart store writable
- Dataset access enforcement
- Preview computation model
- Chart insight save
- Excel chart data export

## Tests Run

Source workspace `C:\Users\james\ds-workflow-starter`:

- `npx tsc -b` - passed
- `.\\.venv\\Scripts\\python.exe -m py_compile server\\charts\\chart_router.py server\\charts\\chart_store.py server\\main.py server\\datasets\\dataset_registry.py` - passed
- `npm run test:chart-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:user-management` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Phase 9B source verification:

- `npx tsc -b` - passed
- `npm run test:chart-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:user-management` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Phase 9C source verification:

- `npx tsc -b` - passed
- `npm run test:chart-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:user-management` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Phase 9D source verification:

- `npx tsc -b` - passed
- `npm run test:chart-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:user-management` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Clean copy `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run test:chart-studio` - passed
- `npm run build` - passed

Phase 9B clean-copy verification:

- `npm run test:chart-studio` - passed
- `npm run build` - passed

Phase 9C clean-copy verification:

- `npm run test:chart-studio` - passed
- `npm run build` - passed

Phase 9D clean-copy verification:

- `npm run test:chart-studio` - passed
- `npm run build` - passed

## Phase 9F Chart Completion and Executable Code Workspace

Phase 9F completed the remaining feasible preview-row chart cards and replaced the read-only generated-code drawer with an executable code workspace for Chart Studio.

### Remaining Chart Status Audit

Working / role-ready chart cards now include:

- Step Plot
- Density Plot
- Stacked Bar
- Heatmap
- Grouped Line
- Panel by Time
- Comparison Panels
- Scatter Matrix
- Correlation Matrix
- Pair Plot
- Means Plot
- Existing Phase 9D charts such as residual diagnostics, lift/decile, forecast, survival, grouped charts, panels, data profile, Pareto, waterfall, control, dual-axis, and Sankey

True Coming soon cards are limited to infrastructure-dependent chart concepts:

- Custom Chart: custom renderer infrastructure is not implemented yet.
- User-defined Role Mapping: custom visual encoding engine is not implemented yet.
- Saved Templates: governed chart template infrastructure is not implemented yet.

### Newly Enabled Chart Types

The following chart types moved from Coming soon to Working where feasible using Dataset Library preview/sample rows:

- Step Plot: sorted ordered values rendered as a step-style line.
- Density Plot: smoothed histogram approximation.
- Stacked Bar: category-by-segment aggregation using existing grouped preview logic.
- Heatmap: category or binned-numeric by category or binned-numeric matrix.
- Grouped Line: multi-series grouped trend preview.
- Panel by Time and Comparison Panels: small-multiple panel renderer.
- Scatter Matrix, Correlation Matrix, and Pair Plot: compact pairwise relationship matrix.
- Means Plot: grouped mean comparison.

### Executable Generated Code Drawer

Generated Code now includes:

- Python, SQL, R, and SAS-compatible tabs
- Generated read-only code panel
- User-edited code panel
- Run button for the active language
- Copy Code
- Reset to Generated Code
- Save Code Snippet
- Export Result to Excel
- Shared execution result panel with stdout, stderr/errors, runtime, return code, and result tables when returned

### Execution Endpoints

- Python uses `/api/python/run` through `runUserPython`.
- SQL uses `/api/analytics/sql/run` through `runAnalyticsPreviewSql`.
- R uses `/api/code/r/run` through `runUserR`; if Rscript is unavailable, the shared endpoint returns honest unavailable/template guidance.
- SAS-compatible uses `/api/code/sas-compatible/run` through `runUserSasCompatible` and does not require a licensed SAS installation.

### Save Code Snippets

Chart Studio saves generated/user-edited code snippets as analytics insights with:

- `sourcePage: chart_studio`
- chart type
- language
- generated code
- user-edited code
- dataset name/version
- role assignments
- business question
- linked project ID

Saved snippets flow through the existing analytics insight store so they can surface with dataset/project findings.

### Export Code Results to Excel

Execution output can be exported using the existing analytics result Excel export path. SQL and SAS-compatible table outputs are exported as tabular result payloads; Python/R text output is exported as stdout/stderr result payloads.

### Scored Dataset Awareness

Chart Studio now includes a Dataset Type selector with a Scored Outputs filter. Scored-output datasets are detected by dataset metadata/name/source heuristics and receive a recommendation to use lift/decile, residual diagnostics, score distribution, calibration, and stability views. If no scored outputs are registered, the UI explains that scoring workflows must register actual scored rows into the Dataset Library.

### Phase 9F Source Verification

- `npx tsc -b` - passed
- `npm run test:chart-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:user-management` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

### Phase 9F Clean-Copy Verification

- `npm run sync:atlas` - passed
- Clean copy `npm run test:chart-studio` - passed
- Clean copy `npm run build` - passed

### Phase 9F Endpoint Smoke Checks

- Backend health endpoint `http://127.0.0.1:8001/api/health` - returned 200
- Frontend route `http://127.0.0.1:5174/chart-studio` - returned 200
- `/api/python/run` direct smoke - returned `ok: true` and stdout
- `/api/code/r/run` direct smoke - returned `ok: true` and stdout
- `/api/code/sas-compatible/run` direct smoke - returned `ok: true` and a PROC MEANS result table
- `/api/analytics/sql/run` raw shell smoke - returned authentication required without a browser session; Chart Studio uses this endpoint with credentials from the signed-in UI

## Manual QA Results

Manual browser click-through QA was not run in this pass. Static tests, builds, clean-copy verification, and direct endpoint smoke checks verify route registration, chart type availability, binned role support, generated code, executable code controls, saved snippet plumbing, Excel endpoint implementation, scored-output filter visibility, and execution endpoint reachability.

## Clean-Copy Sync Confirmation

`npm run sync:atlas` completed successfully. Runtime artifacts under `server/artifacts` remained intentionally excluded by the sync script. Clean-copy `npm run test:chart-studio` and `npm run build` passed after sync.

## Known Limitations

- Chart previews use preview/sample rows, not full warehouse-scale data.
- Chart image export is not included.
- Custom chart renderers, user-defined role mapping, and governed saved templates remain coming soon.
- Relationship edge-list and full network rendering remain out of scope for this phase.
- Full production forecast, survival modeling, and residual diagnostic panel images remain future enhancements; v1 uses preview-row analytical approximations.
- Hover/readout behavior is limited to the chart data table and visible labels.
- SQL binning remains documented guidance because exact quantile syntax depends on the production SQL engine.

## Phase 9G Final Checkpoint

Phase 9G is the final Chart Studio checkpoint before moving to the next ATLAS build. The focus was stability, honest coming-soon language, executable generated-code status, clean-copy verification, and browser-level QA.

### Final Browser QA Results

Browser QA was run against the local app at `http://127.0.0.1:5174/chart-studio` using the local seeded admin account.

- `/chart-studio` opened after authentication.
- `REG_TRAIN` loaded as the selected dataset with version `v_1783361298379_309ce82d`.
- Basic, Grouped, Analytical, Matrix, Panels, and Custom gallery tabs rendered and were selectable.
- Bar Chart rendered with binned numeric category roles and a visible preview/data table.
- Analytical tab exposed Pareto and Residual Diagnostics.
- Matrix tab exposed Data Profile Matrix.
- Panels tab exposed Panel by Time and Comparison Panels.
- Custom tab clearly showed the infrastructure deferral reasons for Custom Chart, User-defined Role Mapping, and Saved Templates.
- Preview Canvas, Chart data table, Generated Code, Saved Charts, Dataset Type filter, Scored Outputs guidance, Export Chart Data to Excel, and Save Chart as Insight were visible.
- Authenticated save-chart-insight smoke returned HTTP 200.
- Authenticated chart-data Excel export smoke returned HTTP 200 and an `.xlsx` payload.
- Direct Python execution smoke returned `ok: true`, stdout, and return code 0.
- R execution endpoint returned HTTP 200.
- SAS-compatible execution endpoint returned HTTP 200.
- Analytics Workbench route remains covered by `npm run test:analytics-workbench` and the clean build.

### Remaining Coming Soon Items

Only true infrastructure-dependent items remain Coming soon:

- Custom Chart: deferred because custom renderer infrastructure is not implemented yet.
- User-defined Role Mapping: deferred because custom visual encoding is not implemented yet.
- Saved Templates: deferred because governed chart template infrastructure is not implemented yet.

These items are displayed as planned infrastructure enhancements, not data-quality failures or broken charts.

### Generated Code Execution Status

- Python code execution uses the local-development Python execution endpoint.
- SQL preview execution uses the authenticated Analytics Workbench preview SQL endpoint.
- R execution uses the R endpoint when `Rscript` is available and otherwise returns honest validation/unavailable guidance.
- SAS-compatible execution uses the ATLAS SAS-compatible endpoint and does not require a licensed SAS installation.
- Generated code remains editable and can be reset to generated defaults.
- Code snippets can be saved as analytics insights.

### Scored Dataset Support Status

Chart Studio includes a Dataset Type filter with Scored Outputs guidance. Scored-output support is available when scored datasets are registered into the Dataset Library. If no scored outputs are registered, the UI explains the required registration path instead of appearing empty or broken.

### Tests Run

Phase 9G verification suite:

- `npx tsc -b` - passed
- `npm run test:chart-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:user-management` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed
- `npm run sync:atlas` - passed
- Clean copy `npm run test:chart-studio` - passed
- Clean copy `npm run build` - passed

### Clean-Copy Sync Confirmation

Verified source changes are synced from `C:\Users\james\ds-workflow-starter` to `C:\Users\james\Projects\ATLAS\atlas-app` using `npm run sync:atlas`. Runtime artifacts remain intentionally excluded by the sync script.

### Known Limitations

- Chart previews still use Dataset Library preview/sample rows.
- Full warehouse-scale charting is not implemented yet.
- Chart image export is not implemented yet.
- Custom chart renderer is not implemented yet.
- User-defined visual encoding is not implemented yet.
- Governed saved chart templates are not implemented yet.
- Full production forecast, survival modeling, and residual diagnostic image panels remain future enhancements.

### Recommended Next Build

Proceed to the next major ATLAS build after this checkpoint. Recommended next work is whichever area is highest priority for the platform roadmap: warehouse-scale chart execution, governed template infrastructure, or broader workbench/report integration.

## Phase 10A Scored Output Integration Note

Chart Studio now recognizes Dataset Library assets registered as scored outputs and provides a direct link to Model Diagnostics. Scored outputs remain chartable in Chart Studio, but ATLAS now recommends Model Diagnostics for lift/decile, residual diagnostics, calibration, score distribution, actual-vs-predicted, and segment performance review.

Deferred Chart Studio items remain unchanged:

- Custom Chart requires custom renderer infrastructure.
- User-defined Role Mapping requires custom visual encoding infrastructure.
- Saved Templates require governed template storage and approval workflow.

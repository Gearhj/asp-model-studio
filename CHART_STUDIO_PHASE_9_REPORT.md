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

Clean copy `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run test:chart-studio` - passed
- `npm run build` - passed

Phase 9B clean-copy verification:

- `npm run test:chart-studio` - passed
- `npm run build` - passed

Phase 9C clean-copy verification:

- `npm run test:chart-studio` - passed
- `npm run build` - passed

## Manual QA Results

Manual browser QA was not run in this pass. Static tests and builds verify route registration, chart type availability, binned role support, generated code, saved insight plumbing, Excel endpoint implementation, and diagnostics wiring.

## Clean-Copy Sync Confirmation

`npm run sync:atlas` completed successfully. Runtime artifacts under `server/artifacts` remained intentionally excluded by the sync script. Clean-copy `npm run test:chart-studio` and `npm run build` passed after sync.

## Known Limitations

- Chart previews use preview/sample rows, not full warehouse-scale data.
- Chart image export is not included.
- Grouped charts, matrix views, panel layouts, custom templates, density, step, forecast, survival, residual diagnostics, and lift/decile views are marked coming soon.
- Chart Studio does not yet share the full Analytics Workbench code workspace editor; generated code is displayed read-only in this phase.
- Hover/readout behavior is limited to the chart data table and visible labels.
- SQL binning remains documented guidance because exact quantile syntax depends on the production SQL engine.

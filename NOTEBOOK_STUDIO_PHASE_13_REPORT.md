# ATLAS Notebook Studio Phase 13A Report

## Scope

Phase 13A adds a native ATLAS Notebook Studio at `/notebook-studio`. The goal is a governed notebook workspace inside ATLAS, not an embedded JupyterLab instance.

Notebook Studio supports:

- Markdown cells
- Python cells
- SQL cells
- R cells
- SAS-compatible cells
- Dataset Library context
- Notebook save/load/delete
- Cell and full-notebook execution
- Captured stdout, stderr, status, runtime, return code, and tabular outputs
- Export to Jupyter `.ipynb`
- Export to HTML
- Attachment of notebook outputs to Model Documentation Studio evidence

## Files Added

- `src/steps/NotebookStudio.tsx`
- `src/lib/notebookStudio.ts`
- `server/notebooks/__init__.py`
- `server/notebooks/notebook_router.py`
- `server/notebooks/notebook_store.py`
- `server/notebooks/notebook_export.py`
- `tests/notebookStudio.test.mjs`
- `NOTEBOOK_STUDIO_PHASE_13_REPORT.md`

## Integration Points

- `src/apps/ModelingApp.tsx`
  - Adds `/notebook-studio`.
  - Treats Notebook Studio as a full-width studio route.

- `src/components/Sidebar.tsx`
  - Adds primary navigation entry: `Notebook Studio`.

- `server/main.py`
  - Registers the Notebook Studio backend router.

- `server/model_documentation/documentation_store.py`
  - Adds notebook evidence to the Model Documentation Studio evidence library.

- `src/steps/DatasetDetail.tsx`
  - Adds `Open Notebook Studio`.

- `src/steps/AnalyticsWorkbench.tsx`
  - Adds `Send to Notebook Studio`.

- `src/steps/SqlDataStudio.tsx`
  - Adds `Send Query to Notebook Studio`.

- `src/steps/ChartStudio.tsx`
  - Adds `Send Chart Evidence to Notebook Studio`.

- `src/steps/ModelDocumentationStudio.tsx`
  - Adds Notebook Studio as an evidence source and coverage category.

## Execution Behavior

Notebook cell execution is routed through existing ATLAS local-development execution services:

- Python uses `/api/python/run`.
- SQL uses the SQL Data Studio preview engine.
- R uses the existing R execution endpoint.
- SAS-compatible uses the ATLAS SAS-compatible execution endpoint.

Execution persists compact output summaries only. ATLAS does not persist large full simulation arrays, full raw datasets, or unbounded chart payloads in notebook artifacts.

## Governance and Security Notes

Notebook execution is local-development-only in Phase 13A.

Before hosted multi-user deployment, notebook execution must add:

- authentication and authorization enforcement,
- sandbox isolation,
- resource limits,
- secrets isolation,
- filesystem containment,
- audit controls,
- administrator runtime configuration.

Phase 13A intentionally does not implement a full sandboxed notebook kernel or persistent notebook session.

## Known Limitations

- Dataset-backed notebook cells use Dataset Library preview/sample rows.
- Full warehouse-scale notebook execution is not implemented.
- There is no persistent Python/R/SAS kernel state across cells.
- SQL notebook cells are read-only preview SQL.
- The `.ipynb` export preserves non-Python cells as code cells with ATLAS metadata comments.
- Notebook collaboration, version diffing, and governed notebook templates are future enhancements.

## Tests Run

Completed in `C:\Users\james\ds-workflow-starter`:

- `npm run test:notebook-studio` - passed
- `npx tsc -b` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:chart-studio` - passed
- `npm run test:model-documentation` - passed
- `.venv\Scripts\python.exe -m py_compile server\notebooks\notebook_router.py server\notebooks\notebook_store.py server\notebooks\notebook_export.py server\main.py server\model_documentation\documentation_store.py` - passed
- `npm run build:modeling` - passed
- `npm run sync:atlas` - passed

## Manual Browser QA

Static and build verification passed. Manual browser QA still requires a running frontend and backend session:

1. Open `/notebook-studio`.
2. Confirm Notebook Library renders.
3. Select a Dataset Library asset.
4. Add Markdown, Python, SQL, R, and SAS-compatible cells.
5. Run a Python smoke cell.
6. Run a SQL preview cell.
7. Save notebook.
8. Reopen saved notebook.
9. Export `.ipynb`.
10. Export HTML.
11. Attach notebook output to Model Documentation Studio.
12. Confirm notebook evidence appears in Model Documentation Studio.

## Clean-Copy Sync

Completed:

- `npm run sync:atlas` copied verified source changes from `C:\Users\james\ds-workflow-starter` to `C:\Users\james\Projects\ATLAS\atlas-app`.
- `server/artifacts` remained intentionally excluded.
- Clean-copy `npm run test:notebook-studio` passed.
- Clean-copy `npm run build` passed.

## Phase 13B Jupyter-Style UX and Rich Output Checkpoint

Phase 13B upgrades Notebook Studio from a card-based workspace into a Jupyter-style ATLAS notebook surface.

Implemented:

- Jupyter-style cell framing with `In [ ]:` and `Out [ ]:` prompts.
- Execution count, status, runtime, and return code display.
- Per-cell actions for Run, Add below, Move up/down, Duplicate, Delete, Copy, and Clear output.
- Markdown edit/preview behavior with rendered headings, bullets, and paragraph structure.
- Rich notebook output renderer for stdout, stderr, warnings/errors, tables, SAS listings/logs, translated Python, and captured images.
- SQL result visualization controls for bar, line, histogram, and scatter previews using capped table results.
- Notebook Outputs gallery summarizing Tables, Charts, Messages, and Errors.
- Expanded templates for Python, SQL, SAS-compatible, and Markdown analysis workflows.
- Matplotlib chart capture for Notebook Studio Python cells using the existing local-development Python runner.
- Compact persistence caps for tables and images to avoid notebook artifact bloat.
- `.ipynb` export support for `image/png` display outputs.
- HTML export support for inline notebook chart images and rendered markdown cells.
- Notebook evidence tagging as chart, table, markdown, or code evidence based on selected cell outputs.

Python chart output behavior:

- Notebook Python cells request image capture with `captureImages=True`.
- The runner uses the same Python executable and normal environment.
- Matplotlib uses the Agg backend for local-development capture.
- Up to 5 PNG images are persisted per output.
- Oversized base64 images are skipped rather than persisted.

Direct backend smoke tests:

- `print("ATLAS Python integration smoke test passed.")` returned stdout successfully.
- A matplotlib line chart smoke cell returned one captured PNG image.

Phase 13B verification in `C:\Users\james\ds-workflow-starter`:

- `npm run test:notebook-studio` - passed
- `npx tsc -b` - passed
- Direct Python execution smoke - passed
- Direct matplotlib image capture smoke - passed, returned 1 PNG image
- `npm run test:sql-data-studio` - passed
- `npm run test:chart-studio` - passed
- `npm run test:model-documentation` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed
- `npm run sync:atlas` - passed

Clean-copy verification in `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run test:notebook-studio` - passed
- `npm run build` - passed

Known Phase 13B limitations:

- Markdown rendering is intentionally lightweight and not a full CommonMark implementation.
- SQL visualizations are frontend previews from capped result rows, not warehouse-scale charting.
- R plot capture remains deferred; R execution still returns stdout/stderr when Rscript is configured.
- Notebook execution still uses preview/sample rows unless a future warehouse execution mode is added.
- There is still no persistent Python/R/SAS kernel state across cells.

## Phase 13C Browser Wiring, Jupyter Feel, Chart Rendering, and Assistant Checkpoint

Phase 13C completes the first usable Notebook Studio browser workflow.

Implemented:

- Add-cell buttons for Markdown, Python, SQL, R, and SAS-compatible notebook cells.
- Jupyter-style insertion menu between cells with direct cell-type insertion and chart/code templates.
- Focus and scroll behavior after creating a new cell or template cell.
- Dirty-state tracking when cells are added, edited, moved, duplicated, deleted, or run.
- Run All execution from top to bottom with progress display and a continue-on-error option.
- Markdown cells render preview output without backend execution.
- Python cells execute through the local-development Python endpoint and show status, stdout, stderr, runtime, and return code inline.
- Python matplotlib image capture remains available for chart templates that call `plt.show()`.
- `atlas_display()` helper added to Python execution so user code can emit structured table outputs.
- Output renderer actions for chart images: Download PNG, Attach Chart to Documentation, Send Chart to Chart Studio.
- Output renderer actions for tables: Export Table to Excel, Register Table as Dataset, Send Table to Chart Studio.
- Expanded chart templates: Histogram, Scatter Plot, Box Plot, Correlation Heatmap, Group Summary Bar Chart, Residual Plot, and Actual vs Predicted Plot.
- Notebook Assistant panel with deterministic local fallback for Explain Cell, Fix Error, Generate Chart, Generate Summary, and Suggest Next Cell.
- Cell-level `Ask ATLAS` and `Fix with ATLAS` actions.
- Assistant suggestions can be inserted as a new cell or used to replace the current cell.

Python execution status:

- Backend smoke test with `atlas_display()` returned stdout and one structured table.
- Browser smoke test with `print("ATLAS Python integration smoke test passed.")` returned stdout inline with success status, runtime, and return code 0.
- Browser output also surfaced stderr text from the local Python process when present; this is intentionally visible instead of hidden.

Manual browser QA completed against `http://127.0.0.1:5174/notebook-studio`:

1. Notebook Studio route loaded.
2. Phase 13C header and Notebook Assistant rendered.
3. Existing notebook canvas rendered Markdown and Python cells.
4. Add-cell menu opened between cells.
5. Add-cell menu showed Markdown, Python, SQL, R, SAS-compatible, and chart templates.
6. Python smoke cell ran successfully and rendered stdout inline.
7. Output panel showed success status, runtime, and return code.
8. Template list showed the expanded chart examples.

Phase 13C verification in `C:\Users\james\ds-workflow-starter`:

- `npm run test:notebook-studio` - passed
- `npx tsc -b` - passed
- Direct Python `atlas_display()` smoke - passed
- Browser Python smoke cell - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:chart-studio` - passed
- `npm run test:model-documentation` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Clean-copy Phase 13C verification in `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run sync:atlas` - passed
- `npm run test:notebook-studio` - passed
- `npm run build` - passed

Known Phase 13C limitations:

- Notebook Assistant is deterministic unless a future `ATLAS_LLM_ENDPOINT` is connected.
- Notebook execution still uses capped Dataset Library preview/sample rows.
- There is no persistent multi-cell Python/R/SAS kernel state.
- Table actions currently wire browser-side handoff/export affordances; governed backend registration can be deepened later.
- R chart image capture is still deferred.

## Phase 13D Unified Notebook Flow and Language Selector

Phase 13D removes the remaining segmented-language feel from Notebook Studio. The workspace now behaves as one continuous governed notebook where Markdown and Code cells can be interleaved naturally.

Why 13C still felt segmented:

- Primary cell creation exposed each language as a separate first-class add action.
- Templates were grouped by language without a notebook-level language intent.
- New code cells did not clearly inherit a default language.
- Assistant output did not visibly communicate which language it was generating.

Implemented in Phase 13D:

- Added a notebook-level `Default Code Language` selector with Python, SQL, R, and SAS-compatible options.
- Replaced primary language-specific add controls with `+ Markdown`, `+ Code`, and `+ From Template`.
- `+ Code` now creates a code cell using the current default code language.
- Existing code cells keep their own language unless the user changes the compact per-cell `Language` dropdown.
- Code cell headers now show `Code: Python`, `Code: SQL`, `Code: R`, or `Code: SAS-compatible`.
- Right-rail templates now filter to Markdown plus templates for the selected default language.
- Added `Advanced: Show all languages` for power users who want cross-language templates.
- Notebook Assistant now labels `Assistant output language` and generates deterministic fallback code in the selected language.
- Assistant inserted code uses the selected default language unless the output is Markdown.
- New notebooks now start with a Markdown introduction plus one code cell in the default language.
- Existing notebooks are normalized safely by inferring `defaultCodeLanguage` from the first code cell and preserving cell order, source, outputs, and per-cell language.
- Backend notebook payloads now persist `defaultCodeLanguage`.

Manual browser QA completed against `http://127.0.0.1:5174/notebook-studio`:

1. Confirmed the page renders `Phase 13D`, `Default Code Language`, and `Assistant output language`.
2. Confirmed the main add controls are Markdown, Code, and From Template rather than separate Python/SQL/R/SAS primary buttons.
3. Changed default language to SAS-compatible and added a Code cell; the new cell rendered as `Code: SAS-compatible`.
4. Changed default language back to Python.
5. Added the Python Histogram template from the right rail.
6. Ran the generated Python chart cell.
7. Confirmed inline execution success, runtime, return code 0, stdout/stderr panels, and one rendered matplotlib image.

Phase 13D verification in `C:\Users\james\ds-workflow-starter`:

- `npm run test:notebook-studio` - passed
- `npx tsc -b` - passed

Known Phase 13D limitations:

- Notebook save/reopen by explicit notebook route was not re-tested in this final pass; the save API and backend default-language payload were updated and covered by static smoke checks.
- Notebook execution still uses capped Dataset Library preview/sample rows.
- There is still no persistent multi-cell Python/R/SAS kernel state.
- R chart image capture remains deferred.
- Notebook Assistant remains deterministic unless a future LLM endpoint is connected.

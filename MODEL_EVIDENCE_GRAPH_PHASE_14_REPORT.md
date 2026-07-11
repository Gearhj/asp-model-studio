# ATLAS Phase 14A Model Evidence Graph Foundation Report

## Summary

Phase 14A adds the Model Evidence Graph foundation to ATLAS. The implementation creates a central, compact evidence registry that references existing ATLAS artifacts instead of duplicating datasets, notebooks, simulation output, chart payloads, or large files.

## Primary Feature

- New primary route: `/evidence-graph`
- New sidebar entry: `Evidence Graph`
- New frontend page: `src/steps/EvidenceGraph.tsx`
- New typed client: `src/lib/evidenceGraph.ts`
- New backend router: `server/evidence/evidence_router.py`
- New backend store: `server/evidence/evidence_store.py`

## Evidence Object Support

Evidence items support:

- project and dataset links
- evidence type
- source page and source route
- artifact type and artifact ID
- dataset, model, document, and notebook IDs
- documentation section mapping
- financial services tags
- status and importance
- lineage metadata
- governance notes
- compact payload summaries

Large binaries and raw data are intentionally excluded from Evidence Graph storage.

## Backend Endpoints

Implemented:

- `GET /api/evidence`
- `POST /api/evidence`
- `GET /api/evidence/{evidence_id}`
- `PUT /api/evidence/{evidence_id}`
- `DELETE /api/evidence/{evidence_id}`
- `GET /api/evidence/project/{project_id}`
- `GET /api/evidence/dataset/{dataset_id}`
- `GET /api/evidence/graph`
- `GET /api/evidence/coverage/{project_id}`
- `POST /api/evidence/auto-capture`
- `POST /api/evidence/export/excel`

## Storage

Evidence registry storage:

- `server/artifacts/evidence/evidence_registry.json`
- `server/artifacts/evidence/items/<evidence_id>.json`

The registry stores compact metadata and references only.

## UI

The Evidence Graph page includes:

- Project-level evidence count
- Ready evidence count
- Needs review count
- Coverage score
- Filter panel
- Evidence Table
- Evidence Timeline
- Evidence Graph grouped-node view
- Coverage view
- Selected evidence detail panel
- Lineage, documentation mapping, and governance notes
- Capture Evidence action
- Export Evidence Pack action

## Integrations

Added foundation integration hooks:

- Project Overview: Evidence Summary card and Capture Current Project Evidence action.
- Dataset Detail: Evidence linked to this dataset panel and Save Dataset as Evidence action.
- Notebook Studio: Save Notebook Output as Evidence and Open Evidence Graph actions.
- SQL Data Studio: Save Query as Evidence, Save SQL Result as Evidence, and Open Evidence Graph actions.
- Model Documentation Studio: Import from Evidence Graph action and Evidence Graph filter category.

## Evidence Quality

Evidence quality score considers:

- source route or source page
- project link
- dataset link
- summary
- lineage
- documentation section mapping
- governance notes

The backend suggests status based on evidence quality:

- high-quality draft evidence can become ready
- weak evidence can be moved to needs review

## Coverage Categories

Coverage currently tracks:

- dataset
- target
- EDA
- feature engineering
- training
- evaluation
- diagnostics
- interpretation
- scoring
- governance
- documentation

Governance warnings are surfaced when Fair Lending or governance evidence is missing.

## Tests Run

- `npm run test:evidence-graph` passed.
- `npx tsc -b` passed.
- `npm run test:notebook-studio` passed.
- `npm run test:sql-data-studio` passed after avoiding a brittle static label collision with the existing `Data Source` test.
- `npm run test:model-documentation` passed.
- `npm run test:dataset-library` passed.
- `npm run test:analytics-workbench` passed.
- `npm run test:chart-studio` passed.
- `npm run test:persistence` passed.
- `npm run test:regression` passed.
- `npm run build:modeling` passed.
- `npm run build` passed.

Clean copy verification:

- `npm run sync:atlas` passed.
- Clean copy `npm run test:evidence-graph` passed.
- Clean copy `npm run build` passed.

Build warnings observed:

- Vite reported existing large bundle chunk warnings.
- Browserslist / baseline-browser-mapping data is stale.
- These warnings did not block the build.

## Known Limitations

- The graph view is a grouped-node foundation view, not a full interactive graph renderer.
- Auto-capture is intentionally conservative and currently focuses on registered datasets.
- Evidence Graph stores references and compact summaries only; large artifacts remain in their source systems.
- Excel export requires the backend Python environment to include `openpyxl`.
- Fine-grained evidence-to-document auto-attachment can be expanded in later phases.

## Recommended Next Build

Phase 14B should deepen evidence auto-capture across:

- model diagnostics
- chart insights
- notebook cell outputs
- SQL result registrations
- model documentation section readiness
- decision journal material events

---

# Phase 14B Financial Services Evidence Taxonomy and Credit Risk Evidence Pack

## Summary

Phase 14B extends the Model Evidence Graph with a financial-services evidence taxonomy and a first complete Credit Risk / Underwriting evidence pack. The implementation keeps Evidence Graph as the source of truth for governance evidence while adding domain-specific metadata, filters, checklist coverage, documentation mapping, and diagnostic save actions.

## New Files

- `server/evidence/financial_services_taxonomy.py`
- `src/lib/financialServicesEvidence.ts`

## Financial Services Domains

ATLAS now recognizes these domains:

- Credit Risk / Underwriting
- Fraud / AML
- Marketing / Profitability
- Model Risk / Governance
- Portfolio Risk
- Decision Strategy

Credit Risk is implemented as the first full evidence pack. Fraud / AML and Marketing / Profitability are registered as taxonomy placeholders for later domain builds.

## Credit Risk Evidence Pack

The Credit Risk pack covers:

- Underwriting Model Techniques: PDO, WOE, IV, manual characteristic binning, reject inference.
- Portfolio Risk: TTC/PIT context, PSI, challenger/champion.
- Regulatory / Governance: adverse action engineering, fair lending testing, monotonic constraints.
- Decision Strategy: cutoff optimization, strategy trees/rule overlays, risk-based pricing.
- Modern Underwriting: monotonic GBM, surrogate scorecards, scorecard scaling, odds calibration.

Implemented technique tags include:

- `pdo`
- `woe`
- `iv`
- `manual_binning`
- `reject_inference`
- `ttc`
- `pit`
- `psi`
- `challenger_champion`
- `adverse_action`
- `fair_lending`
- `monotonic_constraints`
- `cutoff_optimization`
- `strategy_trees`
- `risk_based_pricing`
- `monotonic_gbm`
- `surrogate_scorecard`
- `scorecard_scaling`
- `odds_calibration`

## Evidence Object Extensions

Evidence items now support:

- `financialDomain`
- `financialTechnique`
- `regulatoryRelevance`
- `creditRiskContext`

The backend compact registry preserves these fields without storing raw datasets or large artifacts.

## Evidence Graph UI Updates

Added:

- Financial Domain filter
- Credit Risk Technique filter
- Product Type filter
- Model Purpose filter
- Regulatory Relevance filter
- Credit Risk badges in the evidence table
- Financial Services Context in the detail panel
- Regulatory Relevance detail panel
- Credit Risk Context detail panel
- Financial Services Coverage section
- Credit Risk Evidence Coverage checklist

## Credit Risk Evidence Capture

The Evidence Graph page now supports credit-risk evidence capture forms for:

- Add Credit Risk Evidence
- WOE / IV
- PDO Scaling
- Manual Binning
- Reject Inference
- Fair Lending
- Adverse Action
- PSI
- Cutoff Optimization
- Risk-Based Pricing

PDO guidance is included:

- `Score = Offset + Factor * ln(odds)`
- `Factor = PDO / ln(2)`
- `Offset = BaseScore - Factor * ln(BaseOdds)`

## Project Overview Integration

Project Overview now includes a Financial Services Evidence card inside Evidence Summary:

- suggested financial-services domain
- credit-risk required evidence readiness
- link to Evidence Graph

## Model Diagnostics Integration

Model Diagnostics now has Credit Risk Evidence Hooks:

- Save PSI Evidence
- Save Cutoff Evidence
- Save Fair Lending Review Note
- Save Challenger/Champion Evidence

These actions create Evidence Graph records with credit-risk metadata and documentation section mappings.

## Model Documentation Studio Integration

Model Documentation Studio now includes a Credit Risk Evidence filter. Evidence Graph credit-risk records carry financial-domain metadata into the documentation evidence preview so reviewers can attach them to model development document sections.

## Backend Updates

Backend evidence filters now support:

- `financialDomain`
- `financialTechnique`
- `productType`
- `modelPurpose`
- `regulatoryRelevance`

Coverage now includes:

- Financial Services suggested domain
- Credit Risk checklist readiness
- Fraud / AML placeholder
- Marketing / Profitability placeholder

## Tests Run

- `npm run test:evidence-graph` passed.
- `npx tsc -b` passed.
- `npm run test:model-diagnostics` passed.
- `npm run test:model-documentation` passed.
- `npm run test:dataset-library` passed.
- `npm run test:notebook-studio` passed.
- `npm run test:sql-data-studio` passed.
- `npm run test:analytics-workbench` passed.
- `npm run test:chart-studio` passed.
- `npm run test:persistence` passed.
- `npm run test:regression` passed.
- `npm run build:modeling` passed.
- `npm run build` passed.

Clean copy verification:

- `npm run sync:atlas` passed.
- Clean copy `npm run test:evidence-graph` passed.
- Clean copy `npm run build` passed.

Build warnings observed:

- Vite reported existing large bundle chunk warnings.
- Browserslist / baseline-browser-mapping data is stale.
- These warnings did not block the build.

## Known Limitations

- Credit Risk evidence capture is rule-based and form-driven; full WOE/IV, reject-inference, fair-lending, and adverse-action engines are not implemented in this phase.
- Fraud / AML and Marketing / Profitability are taxonomy placeholders only.
- Credit-risk checklist status depends on captured evidence records; it does not yet inspect trained-model internals.
- Project domain inference is conservative and can be overridden by user-entered evidence context.

## Recommended Next Build

Expand the evidence graph from domain-specific forms into computed evidence capture from model training, scoring, monitoring, fair-lending diagnostics, and decision strategy workflows.

---

# Phase 14C Model Evidence Center Rename and UX Clarification

## Summary

Phase 14C renames the user-facing Evidence Graph feature to **Model Evidence Center**. The prior name was technically accurate for the internal evidence infrastructure, but browser QA showed that users did not immediately understand what the feature does or why they need it. The new name makes the value clearer: a central workspace for collecting, reviewing, mapping, and exporting model evidence.

## Why the Feature Was Renamed

The feature is not yet a full interactive graph renderer. It currently provides an evidence inventory, timeline, grouped foundation map, coverage checks, selected evidence detail, financial-services coverage, and export actions. **Model Evidence Center** better describes the current product experience and the governance value it provides.

## Internal Infrastructure Retained

The internal implementation remains stable:

- Backend API remains `/api/evidence`.
- Backend package remains `server/evidence`.
- Frontend client remains `src/lib/evidenceGraph.ts`.
- Existing evidence records and internal source references remain backward compatible.

This avoids unnecessary backend churn while correcting the user-facing product language.

## Route and Redirect Behavior

New primary route:

- `/model-evidence-center`

Backward-compatible route:

- `/evidence-graph` redirects to `/model-evidence-center`

Saved links to the older route will continue to work.

## Sidebar Label

The primary sidebar now shows:

- `Model Evidence Center`

It no longer shows `Evidence Graph` as a primary navigation destination.

## Page Header and Explanation

The page now uses plain-language header copy:

- Title: `Model Evidence Center`
- Subtitle: `Collects the proof behind your model: datasets, SQL, notebooks, charts, diagnostics, documentation, governance notes, and financial-services evidence.`

Added explanation cards:

- `Why this matters`
- `What counts as evidence?`

These explain the role of evidence in financial-services validation, audit, governance, and model risk review.

## Updated Tabs

User-facing tabs are now:

- Evidence Inventory
- Timeline
- Evidence Map
- Coverage
- Financial Services

The graph concept is retained only as the `Evidence Map` tab.

## Evidence Map Explanation

The Evidence Map tab now states that it is a `Foundation view` and explains how evidence connects across ATLAS. It also clearly notes that full interactive graph exploration is a later-phase enhancement.

## Landing Screen Improvements

The top of the page now answers:

- What evidence exists?
- What evidence is ready?
- What evidence needs review?
- What evidence is missing?
- What should I do next?

Added:

- Total Evidence
- Ready Evidence
- Needs Review
- Missing Critical Evidence
- Coverage Score
- Recommended Next Actions

## Updated Integration Labels

Updated user-facing links and actions across:

- Project Overview: `Open Model Evidence Center`
- Dataset Detail: `Save Dataset to Model Evidence Center`, `Open Model Evidence Center`
- Notebook Studio: `Save Notebook Output to Model Evidence Center`, `Open Model Evidence Center`
- SQL Data Studio: `Save Query to Model Evidence Center`, `Save SQL Result to Model Evidence Center`, `Open Model Evidence Center`
- Model Documentation Studio: `Import from Model Evidence Center`, `Open Model Evidence Center`
- Model Diagnostics: credit-risk hooks now describe feeding Model Evidence Center

## Evidence Detail Clarification

The selected evidence detail panel now includes:

- What this proves
- Where it came from
- What it supports
- Lineage
- Governance notes
- Financial services context
- Recommended action

Dataset and credit-risk evidence now get clearer plain-language proof statements.

## Tests Run

- `npm run test:evidence-graph` passed.
- `npx tsc -b` passed.
- `npm run test:model-documentation` passed.
- `npm run test:model-diagnostics` passed.
- `npm run test:dataset-library` passed.
- `npm run test:notebook-studio` passed.
- `npm run test:sql-data-studio` passed.
- `npm run test:analytics-workbench` passed.
- `npm run test:chart-studio` passed.
- `npm run test:persistence` passed.
- `npm run test:regression` passed.
- `npm run build:modeling` passed.
- `npm run build` passed.

Build completed with the existing Vite large-chunk warning and stale Browserslist/baseline-browser-mapping notices. No Phase 14C compile or build failures were introduced.

## Clean Copy Sync

- `npm run sync:atlas` passed.
- Source folder: `C:\Users\james\ds-workflow-starter`
- Clean ATLAS copy: `C:\Users\james\Projects\ATLAS\atlas-app`
- Clean copy `npm run test:evidence-graph` passed.
- Clean copy `npm run build` passed with the same existing build warnings noted above.

## Manual Browser QA

Manual browser QA was completed against the local app at `http://127.0.0.1:5174`.

Verified:

1. `/model-evidence-center` opens the renamed page.
2. `/evidence-graph` redirects to `/model-evidence-center`.
3. Sidebar shows `Model Evidence Center`.
4. Page includes `Why this matters`.
5. Page includes `What counts as evidence?`.
6. Tabs/content include `Evidence Map`.
7. Tabs/content include `Financial Services`.

## Known Limitations

- `Evidence Graph` remains in internal API/client/test names for compatibility.
- The Evidence Map is still a foundation grouped-node view, not a full interactive graph renderer.
- Existing evidence records may still contain old internal source labels; Model Documentation Studio accepts both old and new labels.

## Recommended Next Build

Add a richer interactive evidence map renderer once the Model Evidence Center inventory, coverage, and domain-specific evidence packs are stable.

# Phase 14D Interactive Evidence Map Renderer

## Why Phase 14C Was Not Visually Sufficient

Phase 14C renamed and clarified the feature, but the Evidence Map tab still used grouped cards and explanatory copy. That made the page understandable, but it did not feel like an actual graph. Phase 14D replaces the grouped foundation view with a visual node-and-edge renderer inside the Model Evidence Center.

## Graph Renderer Implementation

The Evidence Map tab now renders a lightweight SVG graph canvas in React. No heavy graph dependency was added.

The renderer includes:

- Interactive graph canvas
- Visible nodes and connecting edges
- Node click selection
- Connected-edge highlighting
- Selected node detail panel
- Legend
- Layout selector
- Graph filters
- Reset view
- Zoom control placeholders
- Empty and low-evidence states

## Graph-Ready API

The `/api/evidence/graph` backend response was enhanced to return graph-ready nodes and edges while preserving backward-compatible fields.

Node fields include:

- `id`
- `label`
- `type`
- `kind`
- `status`
- `importance`
- `sourcePage`
- `evidenceId`
- `metadata`

Edge fields include:

- `id`
- `source`
- `target`
- `from`
- `to`
- `label`
- `type`

## Node Types

The map supports:

- Project
- Dataset
- SQL Query
- SQL Result
- Analytics Insight
- Chart
- Notebook
- Model Training
- Evaluation
- Model Diagnostics
- Documentation Section
- Governance Warning
- Credit Risk Evidence
- Export Package

## Edge Types

The map supports:

- uses dataset
- generated from
- produces
- supports section
- documents
- requires review
- linked to project
- derived from
- governance flag

## Layout Modes

The graph controls support:

- Evidence Flow
- Source View
- Documentation View
- Credit Risk View

Evidence Flow is the default left-to-right model evidence chain:

Project -> Datasets -> Analysis Artifacts -> Model Artifacts -> Documentation Sections -> Governance / Export.

Source View groups evidence by ATLAS source area such as Dataset Library, SQL Data Studio, Notebook / Analytics, Chart Studio, Diagnostics, and Governance.

Documentation View groups evidence around document sections.

Credit Risk View groups credit-risk evidence around scorecard, risk evidence, fair lending, monitoring, and governance.

## Legend

The graph includes an ATLAS-styled legend:

- Blue = Dataset
- Purple = Notebook
- Green = Diagnostic
- Orange = Governance
- Red = Needs Review
- Gold = Credit Risk Evidence
- Gray = Documentation Section

## Interaction Behavior

Clicking a node updates the selected node detail panel. Connected nodes and edges remain emphasized while unrelated nodes fade back. The detail panel shows:

- Title
- Type
- Source page
- Status
- Importance
- What this proves
- Where it came from
- What it supports
- Linked datasets
- Linked documentation sections
- Financial-services context
- Recommended action
- Open source
- Attach to documentation

## Documentation Section Nodes

Evidence records that support model documentation sections now connect to documentation section nodes. These nodes are used by both the Evidence Flow and Documentation View layouts.

## Credit-Risk Evidence Nodes

Credit-risk evidence receives distinct styling and is emphasized in Credit Risk View. It connects to the relevant documentation sections through the existing credit-risk documentation mapping.

## Empty and Low-Evidence States

If no evidence exists, the Evidence Map displays:

`No evidence map yet. Capture current project evidence to build the map.`

If only dataset evidence exists, ATLAS explains that the map is incomplete and recommends saving SQL queries, notebook outputs, charts, diagnostics, or documentation sections.

## Tests Run

- `npm run test:evidence-graph` passed.
- `npx tsc -b` passed.
- `npm run test:model-documentation` passed.
- `npm run test:model-diagnostics` passed.
- `npm run test:dataset-library` passed.
- `npm run test:notebook-studio` passed.
- `npm run test:sql-data-studio` passed.
- `npm run test:analytics-workbench` passed.
- `npm run test:chart-studio` passed.
- `npm run test:persistence` passed.
- `npm run test:regression` passed.
- `npm run build:modeling` passed.
- `npm run build` passed.

Build completed with the existing Vite large-chunk warning and stale Browserslist/baseline-browser-mapping notices.

## Manual Browser QA Results

Manual browser QA was completed against the local app at `http://127.0.0.1:5174/model-evidence-center`.

Verified:

1. `/model-evidence-center` opens the Model Evidence Center.
2. Evidence Inventory tab still appears.
3. Evidence Map tab opens.
4. Evidence Map displays an actual SVG graph canvas.
5. Graph nodes are visible.
6. Graph edges are visible.
7. The low-evidence current project displays a Project node and Evidence Pack Export node connected by a `produces` edge.
8. Legend appears with Dataset, Notebook, Diagnostic, Governance, Needs Review, Credit Risk Evidence, and Documentation Section.
9. Layout selector includes Evidence Flow, Source View, Documentation View, and Credit Risk View.
10. Show selector includes All, Ready, Needs Review, and Missing.
11. Focus selector includes Project, Dataset, Documentation, and Credit Risk.
12. Clicking a node updates the selected node detail panel.
13. Node detail shows title, type, status, importance, proof language, origin, support mapping, linked datasets, documentation sections, financial-services context, and recommended action.

The browser session was a low-evidence project, so richer dataset/evidence/documentation relationships were verified through the renderer logic and automated tests rather than by visual inspection of a fully populated evidence map.

## Clean-Copy Sync Confirmation

- `npm run sync:atlas` passed.
- Clean copy `npm run test:evidence-graph` passed.
- Clean copy `npm run build` passed.

## Known Limitations

- Zoom controls are visible but currently act as UI placeholders; the SVG layout is fixed and scrollable.
- The graph is a lightweight SVG renderer, not a force-directed graph engine.
- Large warehouse-scale evidence maps may need clustering, search, and virtualized rendering in a later build.
- The old internal `EvidenceGraph` component/file/API names remain for compatibility.

## Phase 14E Evidence Map Layout Upgrade

### Summary

Phase 14E upgrades the Model Evidence Center Evidence Map into a full-width analytical canvas. The Evidence Map tab now prioritizes the graph, moves selected node details below the canvas, and removes the competing right-side detail rail from the map view.

### Layout Changes

- Evidence Map uses a full-width graph workspace instead of the prior side-by-side graph/detail layout.
- The selected node detail panel now appears directly below the graph as a horizontal summary panel.
- The global right-side Evidence Detail rail is hidden on the Evidence Map tab and remains available on inventory/detail-oriented tabs.
- The graph canvas has a larger minimum height and a scrollable full-width container for complex maps.
- A map focus mode was added with `Expand Map` and `Exit Map Focus` controls. Focus mode hides the filter rail and expands the graph workspace.

### Edge Clutter Controls

Added graph controls:

- Show edge labels: default off.
- Show only selected connections: default off.
- Group documentation sections: default on.

Documentation section grouping collapses repeated documentation section nodes into a single grouped documentation evidence node unless the user explicitly filters by documentation focus.

### Low-Evidence Guidance

The low-evidence state remains explicit: ATLAS shows the evidence that exists and explains that richer relationships appear after users capture SQL queries, notebook outputs, diagnostics, charts, scored datasets, documentation evidence, or governance artifacts.

### Source Files Updated

- `src/steps/EvidenceGraph.tsx`
- `tests/evidenceGraph.test.mjs`
- `MODEL_EVIDENCE_GRAPH_PHASE_14_REPORT.md`

### Tests Run

- `npx tsc -b` passed.
- `npm run test:evidence-graph` passed.
- `npm run test:model-documentation` passed.
- `npm run test:model-diagnostics` passed.
- `npm run test:dataset-library` passed.
- `npm run test:notebook-studio` passed.
- `npm run test:sql-data-studio` passed.
- `npm run test:analytics-workbench` passed.
- `npm run test:chart-studio` passed.
- `npm run test:persistence` passed.
- `npm run test:regression` passed.
- `npm run build:modeling` passed.
- `npm run build` passed.

### Manual Browser QA Results

Manual browser QA was performed against `http://127.0.0.1:5174/model-evidence-center`.

Verified:

1. Evidence Map opens without the right-side Evidence Detail rail.
2. The graph canvas renders as a full-width scrollable workspace.
3. Edge controls are visible.
4. `Expand Map` enters focus mode.
5. `Exit Map Focus` restores the standard Evidence Map layout.
6. Clicking graph nodes updates the selected node detail panel below the graph.
7. Evidence Inventory still retains the right-side Evidence Detail panel.

### Clean-Copy Sync Confirmation

- `npm run sync:atlas` passed.
- Clean copy `npm run test:evidence-graph` passed.
- Clean copy `npm run build` passed.

### Remaining Limitations

- Zoom controls remain visual placeholders.
- The graph renderer is still a lightweight SVG renderer.
- Very large evidence networks may require future clustering, minimap navigation, and virtualized rendering.

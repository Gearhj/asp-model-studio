# ATLAS Functionality Audit

Audit date: 2026-07-03  
Scope: functional review from code inspection and recent known behavior. No functional changes were made in this audit pass.

## Executive Summary

ATLAS has a broad and capable feature set, but it is currently carrying three products in one workspace and several workflow systems in parallel. Predictive Modeling is the most complete end-to-end workflow. Experimental Design is advanced but concentrated in one large component, which makes page-specific bugs harder to isolate. Recent Projects, governance docs, notebook export, experiment tracking, and Decision Journal exist, but need stronger project scoping, clearer report summarization, and more automated verification.

## Product Areas

| Area | Status | Notes |
|---|---|---|
| Predictive Modeling | Mostly functional | Complete guided flow from context through monitoring. Recent fixes improved outliers, model toggles, grid search, RFE, and scroll behavior. Needs manual regression test. |
| Experimental Design | Active build, high complexity | Many pages are implemented in `WorkflowPlaceholderStep.tsx`. Strong visual direction, but large component size increases regression risk. |
| Recent Projects | Partially functional | Browser registry exists. Legacy migration exists. Needs QA across create, close, reopen, duplicate, rename, delete, import. |
| Decision Journal | Functional but noisy | Captures audit trail, exports CSV/Markdown. Needs curated governance summary vs full raw log separation. |
| Experiment Tracking | Functional lightweight MLflow | Stores compact experiment records and champion flag. Needs storage quota safeguards and comparison QA. |
| Governance Report | Functional | Uses report renderer and workflow evidence. Needs final content review and report-specific tests. |
| Model Development Document | Functional | Improved tables in several sections. Still should focus on final model and move raw event history to appendices. |
| Notebook Export | Functional | Exports generated notebook/script. Needs sync validation against workflow state. |
| Model Implementation / Monitoring | Basic functional | Post-development pages exist. Monitoring escalation queue exists on dashboard. Needs deeper production model lifecycle design. |

## Predictive Modeling Workflow

### Current Steps

| Step | Path | Status |
|---|---|---|
| Project Context | `/step00` | Implemented. |
| Data Acquisition | `/step01` | Implemented with local CSV/JSON parse and backend sample sync. |
| Credit Bureau Review | `/step01b` | Implemented. |
| EDA | `/step02` | Implemented with D3 and local fallback plots. |
| Outliers | `/step03` | Implemented. Recent defensive loading fix noted. |
| Missing Values | `/step04` | Implemented. |
| Feature Engineering | `/step05` | Implemented. Target exclusion was requested previously and should be regression-tested. |
| Balance & Split | `/step06` | Implemented. |
| Model Training | `/step07` | Implemented. Recent changes improved toggles, model availability fallback, grid search handling. |
| Evaluation | `/step08` | Implemented for classification and regression branches. |
| Interpretation | `/step09` | Implemented, including RFE and model export. Recent RFE improvements noted. |
| Scoring | `/step10` | Implemented. |
| Model Development Document | `/step11` | Implemented. |
| Model Implementation | `/step12` | Implemented. |
| Model Monitoring | `/step13` | Implemented. |

### Known Predictive Issues From User History

| Issue | Current assessment | Recommended verification |
|---|---|---|
| Outlier page failures | Recent defensive fetch/sample fix exists. | Upload classification dataset, visit outliers before backend is warm, verify no crash. |
| Model toggles failing / models not selectable | Recent fallback availability fix exists. | Toggle logistic, tree, random forest, KNN; train. |
| Grid search not respected | Recent training request path includes `grid_search` and `grid_search_level`. | Compare quick vs off using training summary best params. |
| RFE flat or unavailable | RFE supports classification and regression, but visual scale can look flat when deltas are tiny. | Test with known predictive data and California Housing. Use better y-axis formatting if still flat. |
| Slow EDA pairwise/correlation | Sampling and feature limits exist. | Test wide datasets and confirm no browser lock. |
| Model document too event-history-heavy | Partially improved, but still includes large appendices. | Add executive vs full audit export mode. |
| Classification/regression mode mismatch | Store infers and persists problem type. | Test switching between classification and regression projects in Recent Projects. |

## Experimental Design Workflow

The Experimental Design workflow is defined in `src/config/workflows.ts` and mostly rendered by `src/steps/WorkflowPlaceholderStep.tsx`. It uses `src/lib/experimentalDesign.ts` as the shared analysis object for factors, treatment cells, sample size, ANOVA terms, KPIs, and report evidence.

### Current Steps

| Step | Route | Status |
|---|---|---|
| Project Context | `/workflow/experimental-design/1` | Implemented. Needs ongoing polish. |
| Research Question | `/workflow/experimental-design/2` | Implemented. Needs QA for AI drafting buttons and overflow. |
| Factors | `/workflow/experimental-design/3` | Implemented with factor assistant and design visuals. |
| Levels | `/workflow/experimental-design/4` | Implemented with hierarchical parser and treatment matrix logic. |
| Blocking | `/workflow/experimental-design/5` | Implemented. User requested recommendation-engine direction. |
| Randomization | `/workflow/experimental-design/6` | Implemented with allocation and balance diagnostics. Formatting issues were reported recently. |
| Sample Size | `/workflow/experimental-design/7` | Implemented with power analysis direction. |
| Monte Carlo Simulation | `/workflow/experimental-design/8` | Implemented with compact simulation results. |
| Experiment Run Plan | `/workflow/experimental-design/9` | Implemented; needs simulation summary QA at top. |
| ANOVA | `/workflow/experimental-design/10` | Implemented using factor hierarchy. |
| Optimization | `/workflow/experimental-design/11` | Implemented; recent layout gap issue should be retested. |
| Documentation | `/workflow/experimental-design/12` | Implemented with exports. |

### Known Experimental Issues From User History

| Issue | Current assessment | Recommended verification |
|---|---|---|
| Bottom CTA failed | Code includes navigation and scroll-top in `WorkflowPlaceholderStep.tsx` and `StepShell.tsx`. | Manually click every Experimental Design bottom CTA from step 1 through 12. |
| Save Draft failed due localStorage quota | Compaction exists for node state and journal. | Repeat Monte Carlo-heavy save with large project. Confirm no alert and inline error only. |
| Monte Carlo results too large | `compactSimulationResults` path exists in `WorkflowPlaceholderStep.tsx`. | Verify full iteration arrays are not persisted. |
| Treatment levels promoted to factors | `parseFactorHierarchy`, tests, and treatment matrix are in place. | Run `npm run test:experimental-design`. |
| Report Workflow Definition Markdown raw table | Report renderer now converts pipe tables and `Workflow Definition` uses `professionalTableHtml`. | Export governance report and inspect HTML. |
| Governance fields too low on pages | User requested moving governance documentation to top. | Audit each Experimental Design page visually; many pages may still need consistent placement. |
| Dropdown definitions missing | Must check every governance dropdown. | Add tooltip/helper text map if gaps remain. |
| Optimization blank hole | User reported recently. | Inspect `/workflow/experimental-design/11`. |
| Randomization formatting bleed | User reported recently. | Inspect `/workflow/experimental-design/6` at 1920x1080 and narrower. |
| Simulation summary missing on run plan | Code shows a Simulation Summary card, but user did not see expected values. | Run Monte Carlo, navigate to Run Plan, verify metrics are populated from saved state. |

## Recent Projects and Persistence

### Current Behavior in Code

| Mechanism | Purpose |
|---|---|
| `useWorkflowStore` with `sessionStorage` key `ds-workflow-store` | Active workflow state. |
| `atlas-local-projects` in `localStorage` | Recent Projects registry. |
| `upsertProjectSnapshot` | Saves meaningful project snapshots to registry. |
| `migrateLegacyLocalProjects` | Scans legacy session/local evidence and registers orphan projects. |
| `atlas-workflow-node-state:{projectId}:{stepId}` | Project-scoped workflow evidence. |

### Functional Risks

1. Active workflow state is session-backed, so it can be lost if not upserted to Recent Projects.
2. Some legacy keys are global and not project-scoped, such as missing/outlier configs and experiment tracking.
3. Imported project files and browser-saved projects share UI but should remain distinct concepts.
4. Deleting a project removes only recognized project-scoped workflow node storage.

### Recommended Tests

1. Create a new Predictive Modeling project.
2. Confirm it appears on Open Project immediately.
3. Enter context, upload data, select target, train model.
4. Close/reopen browser.
5. Open Recent Project and confirm workflow state.
6. Repeat for Experimental Design.
7. Duplicate, rename, delete, and import exported project.

## Decision Journal

Current strengths:

- Captures timestamp, step, action type, previous/new values, recommendation context, follow/override status, and rationale.
- Exports Markdown and CSV.
- Model/gov reports use timeline rendering for readability.

Current issues:

- It is too long for normal users.
- Many low-value events can overwhelm important decisions.
- Final model documents should summarize material decisions, not reproduce every click.

Recommended next work:

- Add event severity/materiality.
- Split "Material Decision Journal" from "Full Audit Trail".
- Add filters by step, action type, materiality, and followed/overrode recommendation.
- Use full trail only in appendix exports.

## Experiment Tracking

Current strengths:

- Stores experiment ID, dataset version, selected features, preprocessing, balancing, split, model type, hyperparameters, metrics, confusion matrix, curves, feature importance, calibration, champion flag, notes.
- Compacts ROC/PR curves and feature importance.
- Allows champion promotion.

Risks:

- Stored in browser `localStorage`; quota risk remains.
- Project scoping is weak if multiple projects share global experiment records.
- Runtime and model artifact lineage is browser summary, not a real artifact registry.

Recommended next work:

- Scope experiments by `projectId`.
- Add storage quota handling and export/archive.
- Add run status: queued, running, complete, failed.
- Add deterministic dataset hash display in UI.

## Governance Report and Model Document

Current strengths:

- Reports include ATLAS branding.
- Professional table renderer exists.
- Decision Journal uses timeline rendering.
- Experimental Design report can use shared analysis snapshots.

Issues:

- Markdown exports intentionally include HTML/style snippets, which may be surprising in Markdown viewers.
- Predictive Model Development Document still mixes executive content, final model evidence, and large appendices.
- Report content depends heavily on browser storage state.

Recommended next work:

- Add report validation checklist before export.
- Split executive report, full governance package, and technical appendix.
- Add report tests for no raw Markdown pipe tables in HTML output.
- Add project-scoped report generation.

## Test Coverage

Current explicit test file:

| Test | Coverage |
|---|---|
| `tests/experimentalDesign.test.mjs` | Factor hierarchy parser, treatment cell count, treatment matrix, ANOVA terms, sample size derivation. |

Recommended coverage additions:

- Project persistence and Recent Projects unit tests.
- Governance report renderer tests.
- Predictive mode classification/regression switching tests.
- Training request payload tests.
- Local storage quota compaction tests.
- Workflow navigation route tests for all Experimental Design steps.


# 07 — Frontend Workflow, UX, and Accessibility

**Method:** static review of ~97k LOC across 286 files, `dist/` artifact inspection, and **reading the Playwright screenshots already in the repository** — several findings below are proven by a rendered screenshot, not inferred.

---

## 1. Headline

The Data Acquisition hardening — `deriveDataAcquisitionStatus`, `governedProfile`, `useTargetProfile`, route-derived breadcrumbs — is **genuinely high quality and is the correct reference pattern for the platform.**

It is also **an island.** The same defect class it fixed is live on Data Acquisition itself (a second milestone panel), on Outliers, Missing Values, EDA, Evaluation, and the Documentation gate. And the workflow store actively copies completion marks from the previous project into a brand-new one.

---

## 2. Status integrity — screenshot-proven contradictions

### 2.1 Data Acquisition still renders a second, contradicting readiness derivation

```ts
// src/lib/dataAcquisitionLifecycle.ts:334-348
export function resolveStageStates(progress: DatasetLoadProgress): StageState[] {
  return DATASET_LOAD_STAGES.map((_stage, index) => {
    if (progress.phase === "idle") return "pending";
    if (progress.phase === "loaded") return "complete";   // ALL SEVEN, from one boolean
```

The seven stages include *"Profiling target and predictors"*, *"Evaluating data quality"* and *"Ready for modeling"*. The producer performs **no quality work** between `advance(4)` and `advance(5)`, and stage 3 is only `preferredTarget(preview.columns)` — a regex over column *names*.

**Screenshot `003-ui-03-seven-milestones-version-loaded.png` shows, on one screen at one moment:**

- `DATASET LOAD PROGRESS — 7 of 7 milestones` · `Evaluating data quality: COMPLETE` · `Ready for modeling: COMPLETE`
- hero tile `MODELING READINESS: Not evaluated` · `QUALITY REVIEW: Not started`
- body text *"Quality profiling has not been generated."*
- predictor table: *"Calculating the authoritative predictor profile…"*
- primary action: `Resolve blockers to continue` (disabled)

**"Evaluating data quality — COMPLETE" is a screenshot-able assertion that a data-quality control executed when it demonstrably did not.** This is the single highest-severity misleading-status finding in the audit — and it is the exact contradiction class the `dataAcquisitionStatus.ts` docstring documents as fixed.

> **This directly qualifies the prior phase's completion claim.** The earlier work removed the duplicate *readiness* derivation from the checkpoint badge and summary. It did **not** remove the duplicate derivation in the *milestone panel*, which is the more visible of the two.

### 2.2 A new project inherits the previous project's completion marks

`startProjectFromWorkflow` ([src/state/useWorkflowStore.ts:261-279](src/state/useWorkflowStore.ts#L261-L279)) assigns a fresh `projectId` while passing the **outgoing project's** `state.steps` into `workflowStepsWithStatus`, which maps `"completed"` → `"complete"`. `state.steps` is reset only by `reset()`, which that path never calls.

**Screenshot `002-da-03-unified-readiness-state.png` renders `1 of 14 steps · 7%` on a project whose every scope tile reads `Not selected` / `Blocked`.**

That count feeds the header progress bar and the Step 11 "workflow readiness %".

### 2.3 Project Context leaks into a new project — and is then autosaved into it

`Step00_ProjectContext.tsx:107` hydrates from the **global unscoped** key `modeling-tool-project-context`. When the backend has no context for the new project and no project-scoped draft exists, the autosave hook's `else` branch never calls `onHydrated` — so the previous project's `businessObjective`, `targetDefinition`, `populationDefinition`, `modelType` and `regulatoryEnvironment` remain in state, and the first keystroke fires the debounced autosave that **writes them to the new project's backend record**.

This is not a flash — it is **durable cross-project contamination of governance narrative**. `projectContextPersistence.ts:12-16` documents this key as the known root cause, and **18 call sites still read it**.

### 2.4 Evaluation silently substitutes another project's model metrics

```ts
// src/steps/Step08_Evaluation.tsx:294
const actual = rows.length ? rows : loadLocalRanked();   // governed empty -> browser cache
```

`loadLocalRanked()` reads `modeling-tool-training-summary` — a **global, project-unscoped** `sessionStorage` key. Open Project A → open Project B → backend has no models for B → **Step 8 renders Project A's AUC/PR-AUC/RMSE as Project B's evaluation**, with only a low-prominence message.

Note the contrast: `governedProfile.ts:264-269` enforces a **no-fallback invariant** for the governed profile. The same discipline was not applied here.

### 2.5 Completion is set by navigation; "workflow readiness %" is a click count

`StepShell.tsx:100-105` calls `markComplete(currentStep)` unconditionally on Next for any `/step00`–`/step13` route. Steps 12 and 13 supply **no** `nextDisabled` and no verification. EDA can be marked complete with no findings reviewed.

```ts
// src/steps/Step11_ModelDevelopmentDocument.tsx:32
const readiness = Math.round((completedWorkflowSteps / Math.max(1, workflowSteps.length)) * 100);
```

Rendered as a 2xl figure captioned **"workflow readiness"** on the page that gates the Model Development Document. Combined with §2.5, this number is literally *"how many Next buttons were pressed, as a percentage."* Its sibling `missingEvidenceCount` is a **regex over rendered prose**.

### 2.6 Hardcoded and fabricated statuses elsewhere

| Location | Literal |
| --- | --- |
| `Step04_Outliers.tsx:330-331` | `{ label: "Registered population", state: "complete" }`, `{ label: "Treatment selection", state: "complete" }` — green before the analyst selects anything |
| `Step04_MissingValues.tsx:270-271` | same pattern — two of three green ticks are decoration |
| `Step02_EDA.tsx:323` | `{ label: "Analysis State", value: "Available", tone: "success" }` regardless of section load or review state |
| `CopilotCard.tsx:1617` | `{Math.round((challenge.confidence ?? 0) * 100)}%` — **the Atlas Guide badge was correctly de-fabricated; this Challenge-Mode pill still renders ~60 hardcoded 0.78–0.99 constants** |
| `CopilotCard.tsx:1118-1130` | "Experimental Design Readiness %" from regex tests over free text with invented weights `20,18,17,14,12,8,6` |
| **`src/lib/modelMonitoring.ts:70-119`** | **Three fabricated production models with concrete metrics** — `AUC 0.742 yellow deteriorating`, `PSI 0.18`, `AUC 0.691 red`, `complianceIssues: ["Fair lending review overdue"]` — rendered in Step 13 |

**Step 13 presents fabricated production-monitoring evidence, including a fabricated fair-lending compliance exception, inside the governed workflow's final step.** A reviewer screenshotting Step 13 captures invented monitoring results attributed to the platform.

### 2.7 `Number(null) → 0` confident zeros persist

`Step09_Interpretation.tsx:1282` renders a missing decision-tree root event rate as **"0.0%"**; `ModelDocumentationStudio.tsx:583` renders unknown completeness as **"0%"**; `Step06_BalancingSplit.tsx:637-638` renders null row counts as `0`. Screenshot `003` shows `EVENT RATE (PREVIEW ONLY): 0%` as a metric tile on a 170,884-row rare-event dataset.

The reference modules prove the team knows how to do this correctly — `governedProfile.ts:366-372` and `dataAcquisitionLifecycle.ts:243-252` scale digits so `0.2107%` never becomes `0.00%`, and `IV_STATUS_LABELS` gives ten non-numeric reasons instead of a zero.

### 2.8 Four dead storage keys drive the MDD

`"balanceMethod"`, `"splitStrategy"`, `"balanceRatio"`, `"kFolds"` are read in four modules. **Exhaustive grep finds zero writers** — `Step06_BalancingSplit.tsx` is fully server-backed. Consequences: the MDD reports *"Not documented"* for validation design even though a governed split with a stored seed exists; `experimentTracking.ts:238-239` records `balancingMethod: "none"`, `splitStrategy: "holdout"` **unconditionally**; the exported notebook reproduces a split strategy that may contradict the real one.

Validation design is a mandatory MDD element. Reporting it as "Not documented" understates controls; recording it as "none"/"holdout" **misstates** them.

---

## 3. Scope and persistence

**~20 browser keys carry no project or user segment**, including: `atlas-predictive-eda-findings-v2` (analyst commentary), `modeling-tool-outlier-methods`, `modeling-tool-missing-config`, `modeling-tool-training-config`, `modeling-tool-active-training-job`, `modeling-tool-training-summary`, `modeling-tool-rfe-cache`, `modeling-tool-decision-journal`, `modeling-tool-user-python-code*`, `modeling-tool-bureau-*`.

Worse, **Outliers and Missing Values give the browser copy precedence over the server's record of what was actually applied**:

```ts
const source = Object.keys(stored).length ? stored : payload.application?.config ?? {};
```

A stale browser config silently replaces server truth and drives the `applied` badge. And `readActiveJobId()` ignores the `projectId` it itself stored, so Project B polls Project A's training job.

The correct pattern exists in-repo: `atlas:modeling-dataset:{userId}:{projectId}` and `atlas-proposed-operating-policy:{projectId}`. `localDataset.ts:33-50` even documents this exact defect class as fixed — for one key.

**Critical browser-only state** (no durable server equivalent): workflow step completion statuses (in `sessionStorage`, so lost on a new tab), EDA analyst commentary, the **decision journal** (the override audit trail), user-authored Python/SAS, and bureau special-value treatments.

---

## 4. Accessibility

| Measure | Count |
| --- | --- |
| `<input>` elements | 193 (9 with `aria-label`) |
| `<select>` | 168 (3 with `aria-label`) |
| `<label htmlFor>` in the entire app | **3** |
| Clickable non-interactive elements | 8 (`<tr onClick>` ×5, `<div>`, `<span>`, `<td>`) |
| `aria-live` / `role="status"` regions | 19 files — all in Step00/Step01/eda/visual-intelligence |
| Skip links | **0** |
| `axe-core` / `lighthouse` in deps | **0** |

The **implicit-label** pattern (`<label>Global method<select/></label>`) is used consistently and *is* a valid accessible name — so this is not 184 unlabelled inputs. Residual risk concentrates in **table-cell controls outside any label**: at 20 rows × 2 controls a screen-reader user hears 40 identical "combo box" announcements with no feature name.

**Genuine failures:**

- **Colour is the sole carrier of workflow status.** `Sidebar.tsx:228` renders an 8px coloured dot with **no text, no `aria-label`, no `title`** — WCAG 2.1 SC 1.4.1. Only the Optimization branch gets a text badge.
- **Focus is never managed on route change.** `StepShell.tsx:115` scrolls but never calls `.focus()`. No skip link, no route announcer. A keyboard user re-traverses the 16-item sidebar on every navigation.
- **`<tr onClick>` row selection is mouse-only** — selecting a predictor for the histogram panel is impossible by keyboard.
- **Async status is silent on 12 of 15 steps.** `AtlasStatusStrip` and `AtlasExecutionStatus` have no live region, so a long Apply/Train/Split transitioning `running → complete` is never announced.
- **The governed status strip truncates every label.** `.atlas-status-strip__label` and `__detail` both apply `truncate` in a 6-column grid with **no `title`**. Screenshot `002` shows all six as `Source select…` / `Import com…` / `Dataset regis…` / `Target confir…` / `Quality revie…` / `Predictors ap…`. **The governed status track is unreadable in its default layout.**
- **Contrast:** `text-slate-400` on white = **2.55:1**, failing AA and AA-large, in 60 occurrences.
- The header user menu is a plain `<div>` — no focus trap, no Escape, no outside-click, no `role="menu"`.

**Done well:** `prefers-reduced-motion` is handled globally in CSS *and* respected programmatically in five chart components; the newer chart panels provide `role="status"` and `.sr-only` text summaries. The older hand-rolled charts (`Step02_EDA.tsx:1070-1320`, the D3 components) have no accessible name and no data fallback.

---

## 5. Browser performance

| Asset | Bytes |
| --- | --- |
| `duckdb-mvp.wasm` + `duckdb-eh.wasm` | **73.6 MB** combined |
| `ExperimentalDesignWorkflowPage` chunk | 921,678 (= `WorkflowPlaceholderStep.tsx`, 11,768 LOC) |
| **`main.js` entry chunk** | **525,458 — loaded on every page** |
| `guitar-fretboard.png` | 1,866,415 — **dead asset still emitted** |

Route-level `React.lazy` for all 45 routes, `echarts/core` with explicit registration, and DuckDB behind `await import()` are all **correct**. The entry chunk is inflated by `CopilotCard.tsx` (1,700 LOC) being a **static** import rendered on every non-studio route.

**No virtualization anywhere** — grep for `react-window|react-virtual|virtualiz` returns 0. Outliers and Missing Values are correctly paginated at 20 rows; the **Step 1 predictor table is uncapped** — one row per column, ~10 cells each, inside a component with **54 `useState`**, and there is **zero `useCallback` and zero `React.memo` in the entire step layer**. Every handler is a fresh identity each render, so one keystroke in the search box re-renders the full table.

**StrictMode double-fetch:** `Step04_Outliers.tsx:208` and `Step04_MissingValues.tsx:143` are bare `useEffect(..., [])` with no in-flight guard and no `AbortController` — each mount fires **two** full-dataset scans. (`governedProfile.ts` and `targetDistributionApi.ts` dedupe correctly and cite StrictMode explicitly.) `me()` re-runs on **every** route change.

Two module caches never evict; their `clear*` functions exist with **no production call sites**.

---

## 6. Error recovery

**The ErrorBoundary is defined and never mounted.** `src/components/ErrorBoundary.tsx` exports default and named; exhaustive grep finds **matches only inside that file**. Any render throw in a 3,035-line Step 1 or 1,968-line Step 9 **white-screens the whole application**, taking browser-only step state with it.

**No shared fetch wrapper and no 401/403 interceptor.** Each module echoes raw status text: *"ATLAS request failed with HTTP 401"* with no sign-in affordance; a 403 is indistinguishable from a 500.

**Done well:** the governed 409 `full_artifact_missing` path is handled end-to-end — structured detail → typed error → `phase: "artifact_missing"` → rendered disclosure with an actionable recovery list → plain-language blocker. And `Step02_EDA.tsx:206-231` demonstrates the right structured error shape. **Neither is reused anywhere else.**

---

## 7. Expert-tool round trip

| Tool | Can produce governed evidence? |
| --- | --- |
| SQL Data Studio, Notebook Studio, Model Diagnostics, Visual Intelligence Lab | **Yes** |
| Credit Risk Studio | Partial |
| **Analytics Workbench** (2,311 LOC) | **No — dead end** |
| **Embedded Python / SAS panel** | **No** — the blurb promises to *"preserve the code in notebook and evidence exports"*; the **code** is exported, never the **result** |
| Chart Studio | Indirect only — a manual hop through Notebook Studio |

The best round trip is Step 10 Scoring → `registerScoredDataset` → a registered Dataset Library asset → Visual Intelligence Lab loads it by URL and survives refresh. **That is the model the other tools should follow.**

The two most likely places a data scientist does real work are dead ends with respect to the governed lifecycle. **This does not argue against the guided workflow — it argues that the return path into it is incomplete, which is what pushes users out of it.**

---

## 8. Scope disclosure

**8 of 15 Predictive Modeling pages never state the dataset version they operate on** — Outliers, Missing Values, Encoding/Scaling, Balance/Split, Evaluation, and Steps 11–13. Outliers and Missing Values *hold* `application.dataset_version` and use it only in evidence lineage, never rendering it. Steps 11–13 have no hero metrics at all. `Step00:150` hardcodes `"Predictive Modeling"` rather than reading `projectType`.

A validator reviewing a screenshot of Steps 3–6, 8, or 11–13 cannot tell which dataset version produced it — and those are exactly the steps where transformations occur.

---

## 9. Top user-confusion points

1. `7 of 7 milestones — Ready for modeling: COMPLETE` beside `Modeling Readiness: Not evaluated` and a disabled Continue button *(screenshot-proven)*
2. A brand-new project already reads `1 of 14 steps · 7%` with a green sidebar dot *(screenshot-proven)*
3. Atlas Guide says `TARGET: Not selected` while the hero and dropdown both say `Class` *(screenshot-proven)*
4. Every status-strip label truncated to ~10 characters with no tooltip *(screenshot-proven)*
5. A teal success-styled panel containing a red **Blocked** badge *(screenshot-proven)*
6. Step 8 shows another project's model metrics
7. A new project's Project Context pre-filled with the previous project's narrative, then autosaved into it
8. Steps 12–13 are click-through but set completion marks that feed the readiness %
9. Step 13 shows three fabricated production models with a fair-lending escalation
10. Raw `HTTP 401` on session expiry with no route to sign in
11. A render throw anywhere = white screen

---

## 10. Findings

| ID | Sev | Title |
| --- | --- | --- |
| UX-P0-1 | P0 | New project inherits the previous project's step-completion marks |
| UX-P0-2 | P0 | Project Context leaks into a new project and is autosaved into it |
| UX-P0-3 | P0 | Data Acquisition renders a second, contradicting readiness derivation (milestone panel) |
| UX-P0-4 | P0 | Evaluation silently substitutes another project's model metrics |
| UX-P0-5 | P0 | Sign-out leaves all governed browser state readable by the next user |
| UX-P0-6 | P0 | No error boundary is mounted anywhere |
| UX-P1-7 | P1 | Completion set by navigation; "workflow readiness %" is a click count |
| UX-P1-8 | P1 | Hardcoded/fabricated statuses incl. three fabricated production monitoring models |
| UX-P1-9 | P1 | MDD and Governance Report read four dead storage keys |
| UX-P1-10 | P1 | ~20 unscoped browser keys; browser config overrides server truth |
| UX-P1-11 | P1 | Status strip truncates every label; workflow status is colour-only |
| UX-P1-12 | P1 | No focus management, no skip link; async status unannounced on 12 of 15 steps |
| UX-P2-13 | P2 | 513 KB entry chunk, no virtualization, no memoization, StrictMode double-fetch |
| UX-P2-14 | P2 | Raw HTTP status text on 401/403/500; no shared error contract |
| UX-P2-15 | P2 | Expert-tool results cannot re-enter the governed workflow |
| UX-P3-16 | P3 | 8 of 15 steps never state the dataset version |

**The remedy is largely generalization, not invention.** `dataAcquisitionStatus.ts` is the correct per-step status module; `StepShell` is the correct place for a shared scope header, focus management, and the error boundary; `atlas:modeling-dataset:{userId}:{projectId}` is the correct key pattern; the 409 handling is the correct error contract. Each already exists and works — in one place.

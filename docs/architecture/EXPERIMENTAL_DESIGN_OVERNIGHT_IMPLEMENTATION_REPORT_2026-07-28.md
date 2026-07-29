# Experimental Design Overnight Implementation Report

**Requested report date:** 2026-07-28
**Execution window:** 2026-07-28 through 2026-07-29
**Repository:** `C:\Users\james\ds-workflow-starter`
**Status:** Coherent backend-authoritative premium workflow implemented; automated acceptance is green. Authenticated browser acceptance and protected-state screenshots remain blocked because no authenticated browser session was available.

## 1. Initial architecture findings

The existing Experimental Design surface was a generic workflow implementation with useful calculation helpers but no governed end-to-end study architecture.

Key findings:

- One generic page component served several workflow families and held Experimental Design progress in client-side workflow state.
- Step-specific files were mostly re-exports or placeholders rather than independent analytical workspaces.
- The browser owned important planning state and simulation presentation.
- There was no Experimental Design study table, immutable study version, design artifact, simulation-job table, or dedicated repository.
- There was no dedicated authenticated/authorized API.
- Design-family guidance was coupled to dropdown/form state rather than a persisted analyst decision.
- Matrix generation, randomization, simulation, observed analysis, evidence capture, and documentation were not one version-bound lifecycle.
- Planned, simulated, and observed states were not separated strongly enough for a regulated analytical product.
- The original sequence placed randomization before power and matrix generation, which made the analytical dependency order incoherent.
- The existing front end did not provide a permanently visible completion path, a consistent blocker model, or a version/staleness view.

## 2. Exact workflow before changes

The previous 12-step workflow definition was:

1. Project Context
2. Research Question
3. Factors
4. Levels
5. Blocking
6. Randomization
7. Sample Size
8. Monte Carlo Simulation
9. Experiment Run Plan
10. ANOVA
11. Optimization
12. Documentation

Principal dependency defects:

- Factors and Levels were split without providing a central professional factor table.
- Randomization occurred before the power plan and before a backend-authoritative matrix.
- Simulation preceded a reproducible design/run artifact.
- Execution planning and observed analysis were not clearly separated.
- Optimization could appear before real observed evidence existed.
- Documentation did not capture one immutable study/design identity.

## 3. Final workflow

The final 12-step sequence is:

1. **Study Context** — decision, population, data strategy, dataset-version binding or prospective capture plan.
2. **Objective & Responses** — primary response, response kind/direction, hypotheses, randomization unit, success criterion.
3. **Factors & Levels** — professional factor table and factor structure map.
4. **Nuisance & Blocking** — measured nuisance, blocking variables, and rationale.
5. **Design Selection** — eligible-family comparison, recommendation rationale, analyst selection, confirmation, replicates, and center points.
6. **Power & Sample Size** — explicit assumptions, backend calculation, D3 curve, and exact sensitivity table.
7. **Design Matrix & Alias Review** — backend generation, immutable design version, D3 matrix/alias views, and exact semantic matrix.
8. **Randomization & Run Plan** — seeded complete/within-block randomization and exact operational table.
9. **Simulation & Operating Characteristics** — durable bounded job with progress, cancellation, retry, and restart-recovery state.
10. **Execution & Analysis** — run-ID-matched observed responses, ANOVA, factorial effects, and residual diagnostics.
11. **Optimization & Recommendation** — a bounded best-observed-cell recommendation only when observed evidence exists.
12. **Documentation & Evidence** — version-bound reproducibility and evidence package.

Every page presents:

- the decision being made;
- its analytical purpose;
- the current study/version state;
- blockers through the current step;
- documentation impact;
- one primary action;
- a fixed Back / Save draft / Save & continue (or Save final study) action bar.

## 4. Statistical capabilities implemented

### Study contract

The normalized study contract includes:

- project, study, and schema identity;
- prospective/existing/hybrid data strategy;
- exact dataset/version bindings;
- decision objective, population, response, hypotheses, randomization unit, and success criterion;
- factors, levels, types, units, and controllability;
- nuisance factors and blocking configuration;
- analyst-selected design family, rationale, confirmation, replicates, and center points;
- alpha, target power, MDE, standard deviation/baseline rate, response kind, and multiplicity count;
- randomization seed and restrictions description;
- analysis method/formula;
- limitations and evidence references.

### Design-family recommendation

The backend evaluates eligibility and estimated burden for:

- full factorial;
- two-level fractional factorial;
- randomized complete block;
- central composite response-surface;
- Latin square.

The recommendation is advisory. The API returns `analystDecisionRequired`, and matrix generation is blocked until the analyst explicitly confirms a family and rationale.

### Power and sample size

- Continuous and binary planning approximations.
- Two-sided alpha.
- Target power.
- Minimum detectable effect.
- Standard deviation or baseline rate.
- Bonferroni-style adjustment for the declared number of effects.
- Per-cell and total sample.
- Achieved power.
- A 25-point sensitivity curve.
- Exact assumptions and an explicit approximation warning.

### Design generation

- Full factorial with replication.
- Fractional factorial for four through eight two-level factors, with defining relation and alias strings.
- Randomized complete block.
- Central composite response-surface with center/axial structure.
- Latin square where factor structure supports it.
- Maximum 1,024 generated runs.
- Deterministic design hash/version from the governed contract.
- Natural and coded rows, factor names, blocks, replicates, center points, estimability, and aliases.

### Randomization

- Complete randomization.
- Within-block randomization when blocks are present.
- Deterministic seed.
- Persisted order and randomization version.
- Reproduction of the same order from the same design and seed.

### Simulation

- 100 through 20,000 iterations.
- Seeded normal effect-recovery simulation under declared effect, standard deviation, alpha, and per-cell sample.
- Empirical power, false-negative rate, wrong-direction rate, estimated-effect sample, and standard error.
- Explicit `simulated_operating_characteristics` scope and warning.

### Observed analysis

- Requires at least four finite run-ID/response matches.
- Rejects planned/simulated values as observed evidence.
- Treatment-cell ANOVA with explicit sums of squares, degrees of freedom, mean squares, F statistic, and p-value when available.
- Main effects and two-factor interactions for two-level factors.
- Fitted values and residuals.
- Residual mean/standard deviation and Shapiro p-value when valid.
- Best observed treatment cell with a bounded interpretation.
- Explicit warnings for zero residual degrees of freedom, insufficient replication, and causal reliance on protocol adherence.

## 5. Capabilities intentionally deferred

The UI and report do not present the following as implemented:

- matched pairs and repeated-measures models;
- A/B/n-specific proportion-test workflow;
- Plackett–Burman;
- Box–Behnken;
- Taguchi robust parameter design;
- mixture designs;
- sequential/adaptive designs;
- restricted randomization constraints beyond complete/within-block ordering;
- clustering/ICC, attrition, and unequal allocation in the analytical power formula;
- time-to-event calculations;
- ANCOVA, logistic regression, generalized linear models, and mixed-effects models;
- response-surface fitting, contour/3D surface estimation, and uncertainty-aware optimum search;
- multi-response desirability optimization;
- execution ingestion, deviations, protocol violations, and workflow Sankey;
- signed operational run-plan export or an export evidence record.

These are deferred rather than represented by placeholders that imply statistical support.

## 6. UX changes

- Replaced the generic Experimental Design experience with a dedicated workspace.
- Added a compact premium identity header rather than a large repetitive hero.
- Added a horizontally scrollable, keyboard-accessible 12-step navigator.
- Added current study version, backend-current/unsaved state, and contract hash visibility.
- Added a persistent blocker panel and a concise study-contract summary.
- Added a fixed bottom action bar so progression is always available.
- Added exact failure messages from backend endpoints.
- Added prospective-study capture planning and exact Dataset Library version binding.
- Added central factor and nuisance editors.
- Added design-family comparison cards; no generic dropdown auto-selection.
- Added explicit analyst confirmation.
- Added durable job progress/cancel/retry states.
- Added a deliberately labeled synthetic test-input helper for disposable acceptance only.
- Added an honest “no observed analysis” state and removed any implication of optimization from simulation alone.
- Added sortable, filterable, sticky-header exact tables with bounded rows, live result counts, horizontal scroll, and CSV exports of the current backend artifact.

## 7. D3 visualizations

The dedicated visual module uses D3 for analytical views rather than decoration:

1. `FactorStructureMap` — controllable/nuisance variables connected to the primary response.
2. `PowerCurveChart` — power versus total sample, with the governed target point.
3. `DesignMatrixChart` — coded factor-setting heatmap.
4. `AliasMap` — exact confounding relationships for fractional designs.
5. `EffectParetoChart` — observed main/interaction effect magnitude.
6. `ResidualPlot` — observed residuals versus fitted response.

Each SVG has an accessible role/label. Motion uses the shared reduced-motion hook. Exact values remain available in semantic tables.

## 8. Exact tables

Implemented semantic review surfaces:

- dataset/version bindings;
- factors and levels;
- nuisance variables;
- design-family comparison;
- exact power sensitivity results;
- design matrix;
- alias strings and defining relation;
- randomized run plan;
- ANOVA table;
- effect estimates;
- study version history;
- documentation section readiness.

The shared exact table supports:

- keyboard-focusable sortable column buttons;
- `aria-sort`;
- text filtering;
- CSV export;
- bounded 100/250/all display for matrix/run-plan review;
- sticky headers;
- horizontal scrolling;
- readable exact numeric formatting;
- an `aria-live` result count.

## 9. Backend calculations

All governed analytical operations are server-side:

- design recommendation;
- power and sensitivity curve;
- design generation;
- alias structure;
- randomization;
- simulation;
- observed ANOVA/effects/diagnostics;
- documentation readiness.

The browser edits a draft contract and renders returned artifacts; it does not invent a design matrix, randomize a plan, or declare a simulation complete.

## 10. Persistence model

Migration `0016_experimental_design.sql` adds:

### `experimental_design_studies`

- one current study per project;
- study identity;
- current version;
- status;
- canonical contract hash;
- current normalized contract;
- current artifact map;
- blockers;
- creator/updater and timestamps.

### `experimental_design_versions`

- immutable version identity and number;
- project/study;
- canonical hash;
- change summary;
- exact contract snapshot;
- artifact snapshot;
- actor and timestamp.

### `experimental_design_simulation_jobs`

- project/study/study version/design version;
- owner;
- status/progress;
- seed and iteration count;
- parameters/results/errors;
- cancellation and retry-parent state;
- created/started/completed/updated timestamps.

Indexes cover project/version and project/job history.

## 11. Job architecture

- A two-slot bounded semaphore limits concurrent simulations per backend process.
- Submission returns immediately with a durable queued job.
- A daemon worker updates durable progress/results.
- Jobs are mirrored into the generic run repository.
- Cancellation is explicit and persisted.
- Failed, cancelled, and interrupted jobs can be retried with parent lineage.
- On a new service/database binding, queued/running/cancelling jobs are marked `interrupted` with a recoverable server-restart error rather than being left as phantom running work.
- Results are attached to the study only when the study version is still current.
- Iterations are clamped to 20,000.

Remaining scale work: replace in-process worker threads with the platform’s durable worker service when distributed execution is introduced, and enforce per-user/project queue quotas.

## 12. Documentation integration

Each saved study creates an immutable `study_contract` evidence snapshot. Documentation capture records:

- study ID/version/hash;
- dataset bindings;
- objective/responses/hypotheses;
- factors/nuisance/blocking;
- selected design and confirmation;
- power artifact;
- design version/matrix/aliases;
- randomization version/seed/run plan;
- simulation job/result scope;
- observed analysis;
- limitations;
- section readiness and actor/time identity.

Changing data strategy, dataset bindings, objective, factors, nuisance/blocking, design, power, randomization, or analysis plan invalidates the appropriate downstream artifacts. Historical study versions remain unchanged.

## 13. Evidence and decision integration

Evidence types proven by integration tests:

- `study_contract`;
- `design_matrix`;
- `randomization_plan`;
- `simulation_results`;
- `observed_analysis`;
- `documentation_package`.

The explicit analyst design-family confirmation creates an `experimental_design_family_selection` Decision Journal entry. Backend operations also create audit events with project, study/artifact identity, actor, and relevant parameters.

## 14. Authorization and isolation

- All 12 Experimental Design endpoints require `require_user`.
- Every endpoint resolves project permission through `authorize_modeling_scope`.
- Reads require view permission; mutations require edit permission.
- Simulation job retrieval/cancel/retry verifies both authorized project scope and job/project identity.
- Cross-user integration tests return 403.
- A study is unique to its project; versions and jobs carry project IDs and foreign keys.
- No anonymous or compatibility fallback exists on these endpoints.

## 15. Scale protections

- Maximum eight treatment factors.
- Maximum eight levels per factor.
- Maximum 1,024 matrix rows.
- Maximum 20,000 simulation iterations.
- Two concurrent simulation workers.
- Twenty most recent jobs returned with the study.
- Bounded D3 rendering.
- Matrix/run-plan tables default to 100 rows and allow explicit 250/all selection.
- Residual points and estimate samples are bounded.
- Canonical hashes make artifacts cacheable by study/design identity.
- Version mismatches invalidate downstream state.

The production build still reports the Experimental Design route chunk at **991,996 bytes minified / approximately 243 KB gzip**. Route-level D3/statistical code splitting is the highest-priority front-end performance follow-up.

## 16. Exact files changed for this implementation

### Backend

- `server/experimental_design/__init__.py`
- `server/experimental_design/router.py`
- `server/experimental_design/service.py`
- `server/persistence/migrations/0016_experimental_design.sql`
- `server/persistence/repositories/experimental_design_repository.py`
- `server/persistence/repositories/__init__.py`
- `server/persistence/service.py`
- `server/main.py`

### Frontend

- `src/lib/experimentalDesignApi.ts`
- `src/features/experimental-design/pages/ExperimentalDesignWorkflowPage.tsx`
- `src/features/experimental-design/components/ExperimentalDesignVisuals.tsx`
- `src/features/experimental-design/components/index.ts`
- `src/config/workflows.ts`

### Tests and command registration

- `tests/experimentalDesign.test.mjs`
- `tests/experimental_design_premium_backend_test.py`
- `package.json`

### Reports

- `docs/architecture/PREDICTIVE_MODELING_DEEP_REVIEW_2026-07-28.md`
- `docs/architecture/EXPERIMENTAL_DESIGN_OVERNIGHT_IMPLEMENTATION_REPORT_2026-07-28.md`

The repository was already substantially dirty. This list identifies the focused implementation files, not every pre-existing modified or untracked file in the working tree.

## 17. Tests added

### `tests/experimental_design_premium_backend_test.py`

Proves:

- migration creation;
- two-user isolation;
- default and persisted study retrieval;
- immutable version creation;
- contract blockers;
- recommendation and analyst decision;
- power calculation;
- full and fractional design generation;
- exact alias structure;
- deterministic randomization;
- bounded asynchronous simulation;
- cancellation;
- retry lineage;
- restart interruption recovery;
- observed ANOVA/effects;
- evidence and decision outputs;
- documentation readiness;
- reopen persistence;
- downstream invalidation;
- historical-version immutability;
- endpoint timing bounds.

## 18. Tests changed

### `tests/experimentalDesign.test.mjs`

Now covers:

- coherent 12-step routing;
- dedicated backend-authoritative workspace;
- no browser-local storage;
- fixed progression action;
- advisory design confirmation;
- backend operations and limits;
- planned/simulated/observed separation;
- D3 module and accessible SVGs;
- semantic table counterparts;
- sorting/filtering/CSV export and exact power table;
- authentication and project authorization on every endpoint.

The existing calculation-helper tests remain to prevent factor/level parsing and treatment-cell regressions.

## 19. Test results

| Check | Result |
|---|---|
| Experimental Design source/UI contracts | 16/16 passed |
| Experimental Design backend integration | Passed |
| Study versions | 2, with immutable historical v1 |
| Full-factorial generated runs | 8 |
| Fractional alias test | Passed |
| Simulation | 1,200 iterations; empirical power 0.915 |
| Job cancellation | Passed |
| Retry lineage | Passed |
| Restart recovery | `interrupted`, recoverable |
| Cross-user access | Denied |
| Evidence types | All six expected types present |
| Reopen persistence | Passed |
| Downstream invalidation | power, design, randomization, simulation, analysis, documentation |
| Regression suite | 18/18 passed |
| Monitoring lifecycle after security repair | 8/8 source checks and backend lifecycle passed |
| MDD / Model Documentation | Passed |

## 20. TypeScript result

`npx tsc -b` passed after the final table/filter/export changes.

## 21. Production-build result

`npm run build:modeling` passed:

- Vite 7.2.2;
- 3,414 modules transformed;
- no TypeScript or bundling error;
- Experimental Design route chunk 991,996 bytes minified / approximately 243 KB gzip.

Non-failing warnings:

- several chunks exceed 500 KB;
- one visual-intelligence module is both statically and dynamically imported;
- Browserslist/baseline-browser metadata is stale.

## 22. Security-gate result

The complete security runner passed:

- six behavioral suites;
- 55 behavioral tests;
- one structural suite;
- 30 structural assertions.

The separate Experimental Design two-user integration also proves project isolation. The Predictive governance repair adds focused outsider denial for Monitoring and Model Documentation.

## 23. Browser-acceptance result

**Not completed; no claim of authenticated acceptance is made.**

What ran:

- Backend and frontend were restarted on `127.0.0.1:8001` and `127.0.0.1:5174`.
- `/api/health` returned `{ok: true, status: running}`.
- The app loaded in the in-app browser on both `127.0.0.1` and `localhost`.
- The available session resolved to the ATLAS sign-in page.
- No other browser tab or authenticated session was available to claim.

What did not run:

- creation of the disposable Experimental Design project through the UI;
- the protected 12-step walkthrough;
- console/network inspection of protected pages;
- browser reopen/persistence confirmation;
- viewport/reduced-motion visual acceptance;
- protected-state screenshots.

No credential was accessed, derived, entered, or bypassed. The prefilled administrator identity was not used.

## 24. Screenshots

No protected-state screenshot was captured because the browser was not authenticated. Capturing the sign-in page would not constitute acceptance evidence and risked exposing a prefilled account identifier, so it was intentionally omitted.

Screenshot acceptance remains:

1. Study Context with data strategy/version binding.
2. Design Selection comparison and analyst confirmation.
3. Power curve plus exact table.
4. Design matrix and alias review.
5. Randomized run plan.
6. Completed simulation operating characteristics.
7. Observed ANOVA/effects/diagnostics using clearly marked disposable synthetic input.
8. Documentation readiness.
9. Reopened persisted project.

## 25. Performance measurements

### Isolated API/TestClient integration (two runs)

| Operation | Observed |
|---|---:|
| Power calculation | 265–280 ms |
| Eight-run design generation and persistence | 259–482 ms |
| Simulation job submission | 250–604 ms |
| 1,200-iteration simulation to durable completion | 329–467 ms |
| Persisted study reopen | 112–216 ms |

These timings include local TestClient, authorization, SQLite, evidence/audit writes, and machine contention. They are not production load-test percentiles.

### Live local services

- 20 unauthenticated `/api/health` requests: mean 10.62 ms, p50 2.43 ms, p95 24.48 ms, max 139.61 ms.
- Unauthenticated app-shell reload to DOM content loaded: 737 ms.
- Authenticated Experimental Design route timing was not measurable without an authenticated session.

### Build artifact

- Experimental Design route: 991,996 bytes minified; approximately 243 KB gzip.
- Final production build: 52.51 seconds for the Vite phase on this workstation after TypeScript.

## 26. Remaining defects and limitations

### P1

1. Authenticated browser acceptance/screenshots are outstanding.
2. The Experimental Design route chunk should be split by analytical step/visual module.
3. Simulation workers are process-local threads even though job state is durable; a distributed worker service is needed for multi-instance deployment.
4. CSV export is a browser download of the current backend artifact; it does not yet create a signed export/evidence record.
5. The design-family catalog is intentionally narrower than the product vision.
6. Power does not yet support allocation ratio, attrition, clustering/ICC, one-sided tests, or simulation-based sensitivity.
7. Observed analysis is limited to treatment-cell ANOVA and two-level factorial effects.
8. Execution tracking and protocol-deviation ingestion are not implemented.
9. Response-surface model fitting and uncertainty-aware optimization are not implemented.

### P2

1. Add saved table filters/column visibility and virtualization if matrix limits increase beyond 1,024.
2. Add exact power views by effect size, variance, alpha, and allocation—not only sample size.
3. Add interaction and main-effects plots with confidence intervals.
4. Add Q–Q, residual distribution, run-order, leverage, and variance diagnostics.
5. Add accessible visual legends and richer keyboard-linked selection across charts/tables.
6. Add study comparison/version-diff UI.

## 27. Prioritized next steps

1. Complete the signed-in 12-step browser acceptance and screenshots.
2. Code-split the Experimental Design workspace and establish a route performance budget.
3. Move simulation execution to the platform durable worker service with quotas and multi-instance recovery.
4. Add governed server-side export records for matrix, run plan, power, analysis, and documentation.
5. Add A/B/n/proportion, unequal allocation, attrition, clustering, and simulation-based power.
6. Add Plackett–Burman and Box–Behnken only with exact alias/estimability tests.
7. Add execution data/deviation tracking before any workflow Sankey.
8. Add model-based response-surface analysis and constrained desirability optimization with uncertainty.

## 28. Git and repository confirmation

- Nothing was staged.
- Nothing was committed.
- Nothing was pushed.
- No reset, clean, restore, stash, rebase, or history operation was performed.
- Existing working-tree changes and artifacts were preserved.
- `audit-output` was not modified.

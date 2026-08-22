# ASP Model Studio — Independent GPT-5.6 SOL Ultra Audit

**Security + scientific workflow + modeling architecture + UX/implementation consistency**

**Audit date:** 2026-08-20  
**Repository:** `C:\Users\james\asp-model-studio`  
**Branch:** `phase5-game-replay-foundation`  
**HEAD:** `a95b197841f534a97c16fbfc3e9026d713f4725f`  
**Role:** Independent senior data-science, ML-platform, model-risk/governance, and security reviewer

## 1. Executive Summary

### Independent verdict

The current platform is **not ready for scientist testing as an end-to-end governed workflow**. The direct backend modeling functions are real, the registered data presently reconcile at the row-count level, the core multiclass metric implementation is technically sound, and the base feature/preprocessing pipeline contains meaningful leakage controls. Those strengths do not compensate for failures at the authority and handoff boundaries:

1. The UI can show one dataset, target, temporal policy, and candidate while the backend executes another.
2. The Phase 6G multi-model refactor removed the only active-result handoff. A fresh Model Laboratory run does not populate Evaluation, Calibration, Simulation, Champion/Challenger, or Registry.
3. The supposedly frozen 2025 final holdout is computed, displayed, and used in feature-ablation and promotion decisions. It is therefore not operationally frozen.
4. Experiment evidence is mutable and incomplete. A deterministic 64-bit configuration prefix is reused as the file name; same-configuration retries overwrite evidence, while data, code, target, split, environment, actor, and project are not bound.
5. Cockpit experiment storage is global to the server, not project- or user-scoped. A confirmed Windows path traversal lets an authenticated caller read JSON outside the experiment directory.
6. Important “saved,” “registered,” “governed,” and “adopted” decisions are mutable browser `localStorage` records, often without actor, version, digest, or linked evidence.
7. The wider application has multiple object-authorization gaps. Most critically, the feature described as sandboxed Python is not an OS sandbox. If enabled for untrusted reachable users, it is direct execution as the API service account: a **conditional P0**.

The Phase 6H report's “SCIENTIST TESTING READY,” “no P1,” and 5/5 authority/temporal/Model-Lab/auditability conclusions are overturned. Phase 6H established useful engine-level behavior, but its campaign used `persist=False`, deliberately evaluated 2025, and did not exercise the browser journey, candidate activation, project switching, object authorization, evidence immutability, or concurrency (`PHASE_6H_OVERNIGHT_SCIENTIST_ACCEPTANCE_REPORT.md:209-214,255,280-324`).

### Severity summary

- **P0:** 1 conditional deployment blocker — Python execution is host execution if exposed to untrusted users.
- **P1:** multiple current release blockers across scientific integrity, authority, experiment lineage, tenancy, path containment, resource control, and workflow state.
- **P2:** model-family maturity, feature semantics, segmentation selection, calibration diagnostics, caches, architecture, and test coverage require material improvement.
- **P3:** chart labeling, acronym help, error/path disclosure, and related defense-in-depth work remain.

### What is genuinely strong

- The cockpit does perform real model fitting; it has no fabricated-success path.
- Base preprocessing learns fill values, outlier bounds, and scaling on development data, then transforms later folds without refitting (`server/sports_cockpit/modeling.py:122-212`).
- The governed base feature view validates prior-season timing and excludes terminal target/identity fields (`server/sports_modeling/feature_view.py:262-313,428-540`; `server/sports_modeling/feature_contract.py:332-399`).
- Multiclass probability order, sums, log loss, summed one-vs-rest Brier, accuracy, macro F1, and fixed-bin ECE are implemented correctly (`server/sports_modeling/metrics.py:10-70,121-370`).
- Authentication has useful controls: salted PBKDF2, random expiring sessions, HttpOnly/SameSite cookies, revocation, lockout, loopback-gated development identity, and fail-closed hosted configuration (`server/security/security_store.py:202-240,371-395,595-650,704-790`; `server/security/security_router.py:82-119`).
- Model-artifact and dataset-artifact containment in the canonical registries is substantially stronger than the sports-cockpit evidence layer.

### Scope, method, and limitations

The audit inspected the current tree, history from Phase 6A/6B through Phase 6H, reports, tests, cockpit UI/store/API, modeling engine, feature builder, preprocessing, temporal preview, segmentation, calibration, simulation, registries, persistence, authentication, object authorization, execution features, and artifact paths. No Phase 6G, 6G.1, or 6G.2 report files exist; those phases are represented by commits and tests. Relevant history includes `84a1bf1` (6B), `eddc354` (6G), `74bbe1c` (6G.1), `6a98466` (6G.2), and `a95b197` (6H).

The work combined static execution-path tracing, Git archaeology, representative backend and frontend tests, direct metric recomputation, a development/validation-only information ladder, segmentation-weight sensitivity, configuration-identity probes, schema-boundary probes, and a Windows path-containment proof. It did not promote or retrain the champion, mutate governed artifacts, or perform destructive exploitation. A full deployed browser session and external network perimeter test were out of scope; this makes the current NO-GO conclusions conservative, not dependent on those missing tests.

## 2. Most Important Findings

### 2.1 Conditional P0 — “Sandboxed” Python is not sandboxed

Submitted Python is written to a temporary file and launched with `python -I`; `-I` changes Python import/environment behavior but does not isolate filesystem, network, subprocesses, credentials, memory, or process identity (`server/python_execution.py:101-112,161-165,204-249,323-348`; `server/code_execution/sandbox_policy.py:38-48,139-199,261-271`). A project viewer can reach execution paths (`server/python_execution.py:417-528`). Hosted configuration can disable/fail closed, which is why this is conditional rather than an unconditional current P0. Any private-beta or hosted configuration that enables it for untrusted users grants the API service account's host permissions.

### 2.2 P1 — Frozen 2025 evidence guides iteration

Every cockpit experiment computes 2025 predictions/metrics (`server/sports_cockpit/modeling.py:516-531,613-655`). The UI displays them throughout Model Lab, tuning, evaluation, calibration, simulation, and promotion (`src/sports/cockpit/cockpitSteps2.tsx:61-68,350-406,421-553,594-636`). Engineered-feature ablation explicitly uses 2025 improvement in its verdict (`server/sports_cockpit/modeling.py:720-733`). The final holdout has become a second validation set.

### 2.3 P1 — Dataset, target, and temporal authority are labels rather than execution inputs

Dataset/target confirmation is held in notes/browser state. `ExperimentConfig` contains no project, dataset, target, or temporal contract (`src/sports/cockpit/cockpitApi.ts:160-167`). Cockpit endpoints accept none of those authorities (`server/sports_cockpit/router.py:31-65,139-141`). The backend resolves one fixed MLB feature-view glob and hard-codes target `outcome` and 2023/2024/2025 roles (`server/sports_cockpit/engine.py:54-88,165-204,282-313`). The UI can inherit a six-target forecast contract, including Home Win Probability and alternate years, while execution remains PA outcome on fixed years (`src/sports/sportsConfig.ts:266-274`; `src/sports/cockpit/cockpitSteps1.tsx:41-55`).

### 2.4 P1 — Model Lab no longer hands off an active experiment

`runSuite` records only a compact `labSuite` (`src/sports/cockpit/cockpitSteps2.tsx:52-75`). There is no caller of `setLastResult`; only its store definition remains (`src/sports/cockpit/cockpitApi.ts:224,290`). Evaluation, Calibration, Simulation, Champion/Challenger, and Registry read `lastResult` (`cockpitSteps2.tsx:416-479,515-655`). `git log -S setLastResult` identifies Phase 6G commit `eddc354` as the regression point. A fresh run leaves Steps 11–15 empty, while a stale browser result can populate them with the wrong candidate.

### 2.5 P1 — Experiment records are mutable, projectless, and scientifically incomplete

The ID is the first 16 hexadecimal characters (64 bits) of a hash over a limited client configuration (`server/sports_cockpit/modeling.py:504-505,620-628`). It excludes dataset content/manifest, target, temporal split, seed, code revision, dependencies, calibration, actor, tenant, and project. Same-ID retries overwrite the JSON and index entry with unlocked whole-file writes (`modeling.py:663-689`). No fitted estimator, preprocessor, or prediction artifact is stored. Different raw/no-op hyperparameter dictionaries can produce different IDs for the same effective estimator, while different data/code can reuse the same ID. The truncated collision space is also inappropriate as the sole global artifact key, although no natural collision was observed.

### 2.6 P1 — Confirmed experiment path traversal on Windows

`get_experiment` appends an unvalidated route parameter to the experiment directory (`server/sports_cockpit/modeling.py:755-759`; route at `server/sports_cockpit/router.py:149-154`). Backslash is accepted as a URL path-segment character but is a Windows filesystem separator. A request such as `..\autopilot\latest` normalizes outside `experiments`; a direct endpoint diagnostic returned sibling sports-cockpit JSON. More traversal can reach other predictable runtime JSON. Authentication is required, but project/role authorization and containment are absent.

### 2.7 P1 — Global authenticated namespaces defeat multi-tenancy

The sports cockpit has blanket authentication but no actor/project arguments or checks. All authenticated users share experiment lists, deterministic file names, the index, and `autopilot/latest.json` (`server/main.py:500`; `server/sports_cockpit/router.py:31-260`; `server/sports_cockpit/modeling.py:663-689,745-759,784-841`). Similar object-authorization gaps exist in the Registry Dashboard, Recovery Registry, Analytics Engine, Validation Center, Notebook Studio, and saved SQL/chart/analytics namespaces. Blanket route authentication is not object authorization.

### 2.8 P1 — Browser persistence can disclose or copy state across users/projects

Cockpit keys are `asp-sports-cockpit:${projectId}`, without user/tenant scope (`src/sports/cockpit/cockpitPersistence.ts:17-50`). Hydration does not reset the singleton Zustand store when a newly selected project lacks a snapshot (`cockpitPersistence.ts:81-107`), so Project A state can be autosaved under Project B. Logout does not clear all local project/cockpit/workflow records. On a shared browser, the next user can see prior notes, feature choices, results, simulations, and locally registered sports projects.

### 2.9 P1 — Controls and derived state can disagree silently

Most configuration setters do not invalidate `lastResult` or `lastSim`; only dataset change has a special invalidation path (`src/sports/cockpit/cockpitApi.ts:258-329`). `SimResult` lacks an experiment/config identity, and promotion gates can combine an old experiment with an unrelated simulation (`src/sports/cockpit/cockpitSteps2.tsx:518-531,629-637`). “Send to tuning” stores display keys, while tuning continues to use the generic/default family. Model Lab sends `hyperparameters: {}` for each family and discards candidate settings (`cockpitSteps2.tsx:58-69,350-410`).

### 2.10 P1 — Resource controls are insufficient for multi-user use

Sports hyperparameters are effectively unbounded; trees and boosters use `n_jobs=-1` (`server/sports_cockpit/modeling.py:218-295`). Broader training starts per-job threads without global/user quotas, SQL lacks a progress deadline, uploads may be read and parsed in memory up to 250 MB, and Python subprocesses lack memory/PID/global-concurrency limits. An authenticated user can monopolize CPU/RAM or create denial-of-wallet behavior (`server/training/training_job_types.py:8-50`; `server/training/training_job_service.py:598-744,1096-1101`; `server/sql_studio/sql_engine.py:43-51,140-173`; `server/main.py:248-287`).

## 3. Security Findings

### 3.1 Authentication and sessions

**Positive controls**

- All API routes pass the application's blanket authentication invariant (`server/main.py:105-136,463-519`).
- Passwords use PBKDF2-SHA256 with per-user random salts and 260,000 default iterations (`server/security/security_store.py:54-55,371-395`).
- Session IDs are random, expiring, checked for revocation, and returned in HttpOnly, SameSite=Lax cookies (`security_store.py:595-650`; `server/security/security_router.py:82-90`).
- Logout revokes the server session (`security_router.py:115-119`). Hosted startup rejects default/short secrets, insecure cookies/origins, development headers, and local bootstrap (`security_store.py:202-240`).

**Residual weaknesses (P2)**

- Password change does not revoke existing sessions; bearer session values are stored plaintext in SQLite (`security_store.py:274-283,595-664`).
- Five failed attempts can lock a target account for 15 minutes without layered IP/device throttling, creating a lockout DoS (`security_store.py:51-55,552-592`).
- Password policy is eight characters plus a short denylist; there is no complete MFA/SSO/reset flow (`security_store.py:371-376`; `security_router.py:133-140`).
- Cookie-authenticated mutations have no explicit CSRF token. SameSite=Lax and JSON requests reduce risk, but bank deployment should validate Origin/Referer and use anti-CSRF protection.

### 3.2 Authorization and multi-tenancy

| Route family | Assessment | Principal evidence |
|---|---|---|
| Canonical persistence/model registry/scoring/model artifacts | Substantially protected | Parent-project resolution, project access, artifact containment/checksum exist. |
| Sports cockpit | **Broken** | Global experiments/autopilot; no actor/project/role; deterministic overwrite. |
| Registry Dashboard | **Broken** | Lists/details/owners/activity for all projects without user/project filter (`server/registry/router.py:24-87`; `registry_service.py:458-470,759-857,937-1059`). |
| Project Recovery Registry | **Broken** | Global reads/upserts/recovery scan; leaks dataset metadata and host path (`server/projects/project_router.py:17-51`; `project_registry.py:102-200`). |
| Analytics Engine | **Broken** | Arbitrary run/project read/cancel/evidence; caller supplies project ID (`server/analytics_engine/router.py:8-30`; `service.py:37-76`). |
| Validation Center | **Broken** | Global queue/cases/findings/challenges/approvals; project existence is checked, actor access is not (`server/validation/router.py:26-104`; `validation_service.py:57-61,130-413`). |
| Notebook Studio | **Broken/high risk** | Global CRUD/export; cell request not bound to stored notebook project/dataset (`server/notebooks/notebook_router.py:79-197`; `notebook_store.py:140-327`). |
| Saved SQL / chart / analytics insight | Broken or partial | Global mutable namespaces and caller-controlled project linkage; dataset access is stronger than project linkage. |
| Dataset ACL administration | Partial | Dataset editor may grant/revoke/archive and grant `owner` (`server/datasets/dataset_registry.py:517-531,1056-1124`). |

The release standard must be: resolve the object server-side, derive its immutable tenant/project/dataset parents, authorize the current actor against each parent, and filter every list/aggregate to the same scope. Caller-supplied project IDs are claims, not authority.

### 3.3 Input and path security

- **Confirmed P1:** Windows sports-experiment path traversal, described above.
- Feature formulas are typed operations rather than arbitrary `eval`, which is positive. However, the backend accepts any numeric frame column and unbounded numeric parameters (`server/sports_cockpit/features_builder.py:20-110`); UI dropdowns are not a security boundary.
- SQL dataset loading uses access checks and quoted identifiers and blocks DML/attach/pragma, but regex gating plus output caps do not bound execution time.
- Spreadsheet exports do not neutralize leading `=`, `+`, `-`, or `@`; untrusted values can become formulas in Excel (`server/sql_studio/sql_router.py:156-203`; `server/charts/chart_router.py:102-172`).
- Several routes return raw exception or host-path detail, which aids reconnaissance (`server/sports_cockpit/router.py:22-28`; `server/sql_studio/sql_engine.py:188-198`).

### 3.4 Execution and resource abuse

The Python execution conditional P0 must be resolved at the operating-system boundary, not with more source-token checks. Required controls include disposable container/VM or Windows sandbox, unprivileged identity, read-only staged inputs, no host mounts, denied network/process access, PID/CPU/RAM/time quotas, per-user concurrency, and an explicit role/tenant policy. Default must be off in all modes.

Model training, tuning, Autopilot, uploads, SQL, and repeated simulations need a centralized scheduler with hard schemas and organization/user/project quotas. “Bounded” candidate counts do not protect against a single candidate with extreme estimators, depth, iterations, hidden layers, thread count, or data volume.

### 3.5 Artifact security, secrets, and logging

- The sports cockpit writes JSON, not executable pickle/joblib, which avoids untrusted deserialization there. Canonical model-artifact loading has containment and checksum-before-`joblib.load`; preserve those controls.
- Notebook/query/chart/analytics/sports JSON is mutable, unversioned, and often plaintext under shared roots. Some whole-file indexes have no interprocess lock or optimistic version.
- Tracked `.env.modeling` and `.env.scheduling` contained application target/base/root variables but no credential-looking variable names. This was a targeted check, not an entropy-based secret scan.
- Local defaults include a known development session secret/admin password, but hosted-mode validation rejects them. They remain unsafe if a non-hosted service is made reachable.
- Registry/export endpoints should not disclose absolute server paths. Detailed errors should be protected logs with correlation IDs, not client responses.

## 4. Scientific Findings

### 4.1 Leakage review

| Leakage vector | Finding | Rating |
|---|---|---|
| Direct target / terminal-event leakage in base predictors | Base contract excludes target/terminal identity and validates pre-terminal PA state. | Controlled |
| Same-game future information | Prior source year is constrained to `<= target_year - 1`; pre-PA context checks are present. | Controlled for governed base view |
| Global preprocessing/imputation/outlier/scaling | Cockpit `Preprocessor.fit` uses 2023 and `transform` does not refit. | Controlled |
| Quantile-bin transform | Training materialization fits quantile thresholds on development and applies later. | Controlled in experiment path |
| Base IV/MI/correlation ranking | IV/MI and correlation are development-only. | Controlled |
| Engineered-feature profile | Missing fill for engineered MI uses an all-season median; backend can select reserved/unapproved columns. | **P1** |
| Segmentation recommendation | K-means/grid scoring includes 2024 stability, so the “development-only” recommendation consumes validation. | P2 |
| Calibration | Governed C4 calibration selects on 2024 only, but cockpit calibration is raw/display-only and its copy says reject if frozen worsens. | **P1 workflow** |
| Hyperparameter/model selection | Tuning uses 2024; no nested temporal CV. More importantly, UI exposes 2025 for every candidate. | **P1** |
| Frozen-final leakage | 2025 is evaluated, displayed, and used in ablation/promotion decisions. | **P1** |
| Target-dependent EDA | Target distribution and 2025 target rows are visible before final authorization; all-season descriptive statistics influence choices. | P2 |

The strongest leakage controls apply to the governed base feature view and preprocessing object. They do not make the interactive decision process leakage-safe once frozen outcomes and metrics are repeatedly visible.

### 4.2 Independent null/signal information ladder

This diagnostic read only 2023/2024 rows, asserted those were the only observed seasons, fit the same development-only preprocessor and multinomial logistic model (`C=1`, median fill, no outlier treatment), and independently calculated metrics. It did not persist a run.

| Level | Feature block | Model columns | 2024 log loss | Summed Brier | ECE10 | Top-1 | Macro F1 | LL gain vs null |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| L0 | Development class-frequency null | 0 | 1.500249 | 0.712623 | 0.009000 | 0.452543 | 0.077888 | — |
| L1 | Context | 15 | 1.495842 | 0.711630 | 0.009123 | 0.452543 | 0.077888 | 0.294% |
| L2 | Batter priors | 8 | 1.490999 | 0.708764 | 0.010445 | 0.451523 | 0.081715 | 0.617% |
| L3 | Pitcher priors | 9 | 1.497479 | 0.711526 | 0.010777 | 0.452050 | 0.080323 | 0.185% |
| L4 | Batter + pitcher | 17 | 1.488343 | 0.707717 | 0.011312 | 0.451211 | 0.088256 | 0.794% |
| L5 | All 22 base features | 32 | 1.484253 | 0.706782 | 0.011653 | 0.451562 | 0.089731 | 1.066% |
| L6 | Base + eight Phase 6H engineered features | 40 | 1.484286 | 0.706689 | 0.011848 | 0.451447 | 0.090313 | 1.064% |

The plateau is not evidence of a stale or constant matrix: feature blocks change probabilities coherently, batter priors outperform pitcher priors, and context adds signal. The dominant explanation is **weak, class-imbalanced signal in the current static feature view**, especially for rare outcomes, not an obvious metric or preprocessing failure. L5 gains are concentrated in STRIKEOUT, BIP_OUT, and WALK; DOUBLE is effectively unchanged and TRIPLE slightly worsens. The eight engineered features do not improve validation log loss and slightly worsen ECE. The current engine equality therefore should not be “fixed” by blind hyperparameter breadth or more model families.

A separate `C=0.05` regularization check retained the full per-class validation vector. The metric below is mean true-label log-loss gain within each class: `null class mean loss − model class mean loss`, so positive is improvement. It fit/scored only the 2023/2024 masks; the shared frame loader did load the registered 2025 frame into memory, but no 2025 row entered this fit or calculation.

| Class | L5 base gain vs null | L6 engineered gain vs null |
|---|---:|---:|
| STRIKEOUT | +0.040555 | +0.040120 |
| WALK_HBP_CI | +0.082437 | +0.085970 |
| HOME_RUN | +0.081898 | +0.081819 |
| SINGLE | -0.001820 | -0.000934 |
| DOUBLE | -0.004493 | -0.006788 |
| TRIPLE | +0.003502 | -0.012739 |
| BIP_OUT | -0.009067 | -0.009347 |
| OTHER_REACH | +0.133359 | +0.126490 |

This class view reinforces the aggregate conclusion: some smaller classes gain substantially, but SINGLE/DOUBLE/BIP_OUT do not, and current engineering makes TRIPLE materially worse. Aggregate log loss remains the governed selection metric; these conditional means are diagnostics, not an alternative objective.

| Plateau hypothesis | Audit judgment |
|---|---|
| Weak signal | **Primary explanation.** Only about 1.1% validation log-loss gain over the development-frequency null. |
| Stale/constant feature matrix | Not supported; block additions change loss, Brier, class behavior, and predictions coherently. |
| Excessive regularization | Not primary; `C=0.05` and `C=1` produce essentially the same aggregate plateau. |
| Probability compression | Present in the sense of conservative probabilities, but consistent with weak separability; not evidence of a broken probability path. |
| Preprocessing defect | No obvious aggregate defect; dev-fit transforms and independent metrics reproduce. Feature-kind/schema defects still need repair. |
| Target entropy limit | The null level of 1.500249 is the relevant empirical ceiling; the model extracts only a small fraction of available reduction. |
| Model-family configuration | Family support is immature and can hide convergence/calibration differences, but near-equality across families is plausible on this signal-limited matrix. |

### 4.3 Model-selection and calibration integrity

- There is no nested temporal validation for family/hyperparameter comparisons.
- MLP early stopping uses a non-temporal internal validation fraction; SVM probability calibration uses default non-temporal `cv=3`.
- Raw and calibrated evidence are not consistently labeled. The cockpit never creates a calibrator, even though C4 has a separate governed temperature-calibration implementation (`server/sports_modeling/calibration.py:106-223`).
- The champion comparison refits a surrogate logistic baseline over several C values and caches it, rather than loading one immutable registered estimator/preprocessor artifact (`server/sports_cockpit/modeling.py:558-582`).
- QUICK simulation conditions on observed base/out states and the actual PA sequence/count; it is not a wholly generative counterfactual game. FULL mode is more ambitious, but transition/game-actual caches and hard-coded exchange paths are not bound to the experiment. Impact-verdict thresholds have no reported uncertainty or validated decision utility.

## 5. Data/Temporal Findings

### 5.1 Current role and row-count reconciliation

| Season | Intended role | Rows | Present execution use |
|---:|---|---:|---|
| 2021 | PRIOR_HISTORY | 181,818 | Source-history authority only; not in materialized modeling frame |
| 2022 | PRIOR_HISTORY | 182,052 | Source-history authority only; not in materialized modeling frame |
| 2023 | DEVELOPMENT | 184,104 | Fit preprocessing and models |
| 2024 | VALIDATION | 182,449 | Tuning/comparison/calibration reference |
| 2025 | FROZEN_FINAL | 182,926 | Currently scored/exposed during every run; incorrectly reused for decisions |

Totals:

- Registered rows: **913,349**
- Prior-history rows: **363,870**
- Modeling rows (2023–2025): **549,479**
- Validation rows: **182,449**
- Frozen rows: **182,926**

The current runtime feature view independently reported exactly 184,104/182,449/182,926 for 2023/2024/2025, so there is no present row-count mismatch. That agreement is weaker than it appears: 2021/2022 and total authority values are hard-coded; `_feature_view_path()` takes the first lexicographically sorted matching object; the frame is cached indefinitely under a constant key; and the run does not bind the displayed manifest/content SHA (`server/sports_cockpit/engine.py:67-88,165-204,307-380`). A second compatible object or changed registration can silently break agreement.

### 5.2 Dataset and target authority

Dataset selection is a browser note, not an executable version selection. Target confirmation accepts any non-empty inherited contract target without exact equality to the selected/backend target (`src/sports/cockpit/cockpitSteps1.tsx:41-55,195-353`). No server-issued authority token binds project, dataset version, manifest SHA, feature-view SHA, target contract, and split. The backend's implicit defaults therefore win silently.

Required fail-closed behavior: every run request must include an authorized server-resolved dataset/version/content digest, exact target contract, population contract, temporal contract, project, and actor; the server must reject a mismatch instead of substituting a default.

### 5.3 Temporal policy truth table

| UI policy | Preview | Actual training | Scientific assessment |
|---|---|---|---|
| Season holdout | Displays 2023/2024/2025 | Fixed 2023 fit, 2024 validation, 2025 evaluation | Executable, but 2025 handling is invalid |
| Rolling origin | Displays fold guidance | Still fixed season holdout | Decorative application |
| Expanding window | Same preview branch/folds as rolling (`engine.py:721-726`) | Still fixed season holdout | Decorative and indistinguishable |
| Date holdout | Boundary is component state and not saved in policy | Still fixed season holdout | Decorative; boundary lost |
| Random research | Displays counts/warning, not deterministic row membership | Still fixed season holdout | Non-executable and potentially misleading |

The UI saves temporal policy only into notes (`src/sports/cockpit/cockpitSteps1.tsx:1872-1950`); `ExperimentConfig` has no split field and the backend always masks fixed seasons (`server/sports_cockpit/modeling.py:516-531`). “Create revised temporal experiment” does not create a revised experiment.

## 6. Model-Lab Findings

### 6.1 Propagation audit

| Decision | Reaches fit? | Reaches evidence/downstream? | Finding |
|---|---|---|---|
| Selected base features | Usually yes | Limited config record | Explicit empty list silently falls back to all features (`modeling.py:585-593`). |
| Excluded features | Yes when list non-empty | Limited | Correct in normal path. |
| Missing/outlier policy | Yes | Config JSON only | Fit-local behavior is real; no immutable preprocessor artifact. |
| Engineered specs | Yes | Config JSON/profile browser state | Matrix changes are real; schema/profile issues remain. |
| Model family | Each suite row fits requested family | No selected active family handoff | Suite selection is visual; `setFamily` has no UI caller. |
| Hyperparameters | Direct API can use them | Suite discards them with `{}` | Tuning is logistic-C-only and not tied to selected candidate. |
| Temporal policy | **No** | Notes only | All runs use fixed years. |
| Dataset/target/project | **No** | Not in config/hash | Fixed global backend authority. |
| Segmentation-derived features | No | No artifact | UI honestly labels segmentation exploratory, but there is no downstream support. |
| Calibration | No | No artifact | Page is raw diagnostics, not calibration. |
| Simulation | Retrains/uses config | `lastSim` lacks parent identity | Can be attributed to wrong/stale candidate. |

### 6.2 Model-family implementation audit

| Family | Actual implementation | Probability/multiclass | Reproducibility and compatibility | Product maturity/risk |
|---|---|---|---|---|
| Logistic | Multinomial `lbfgs`; C/maxIter | Native aligned probabilities | Seed not material; scaling appropriate | Best supported; only family with UI tuning, but no temporal inner CV |
| Random Forest | Seeded; trees/depth/min leaf/max features; `n_jobs=-1` | Native raw probabilities | Scaling unnecessary; median fill applied | No calibrated comparison, class weighting, bounded search, or family UI |
| Extra Trees | Seeded analogue of RF | Native raw probabilities | Same | Same maturity gap |
| HistGradientBoosting | Seeded learning rate/iterations/depth/L2 | Native raw probabilities | Scaling unnecessary; standardized anyway | No surfaced convergence/early-stopping evidence |
| MLP | Seeded hidden layers/alpha/lr; max_iter 80; early stopping | Native probabilities | Scaling appropriate | Non-temporal internal validation; warnings/n_iter not captured; convergence risk |
| XGBoost | Seeded `multi:softprob`, histogram tree method | Native multiclass probabilities | Optional dependency/environment-sensitive | Unbounded parameters, no governed search/calibration |
| LightGBM | Seeded estimators/leaves/lr/subsample | Native multiclass probabilities | Optional dependency/environment-sensitive | `subsample` may be inert without bagging frequency; no governed search/calibration |
| Linear SVM | `LinearSVC` wrapped in sigmoid `CalibratedClassifierCV(cv=3)` | Probabilities supplied by calibrator | Base random state not explicit; default folds non-temporal | Calibration treatment is incomparable to other raw families |

All eight are advertised (`server/sports_cockpit/modeling.py:70-82,218-296`), but only logistic is simulation-eligible. “Select recommended” selects every available family, not a scientifically screened subset (`src/sports/cockpit/cockpitSteps2.tsx:47-49`). Availability is therefore broader than governed experimental support.

The backend accepts these raw keys: logistic `C/maxIter`; RF and Extra Trees `nEstimators/maxDepth/minSamplesLeaf/maxFeatures`; HGB `learningRate/maxIter/maxDepth/l2`; MLP `hiddenLayers/alpha/learningRate/maxIter`; XGBoost `nEstimators/maxDepth/learningRate/subsample/colsampleBytree`; LightGBM `nEstimators/numLeaves/learningRate/subsample`; SVM `C/maxIter`. None is range-bounded. The scientist UI exposes a real search control only for logistic `C`; the other keys are API-level capability rather than a governed UI experiment surface.

All families currently receive the same dense, finite matrix after the shared median/fill and scaling path, so native missing-value support is not relied upon. Scaling is required/appropriate for logistic, MLP, and linear SVM but unnecessary for tree families; it is not normally harmful, though it reinforces that family-specific preprocessing is not modeled. Native probability class order is aligned/renormalized for all probability estimators; SVM alone obtains probabilities through its internal sigmoid calibration.

### 6.3 Identity and mutable-state diagnostics

A direct configuration diagnostic confirmed that `{}`, explicit defaults, and an unknown parameter produced hashes `38ea5084911499d9`, `79efbb5e3a6e4e27`, and `b23c7125c9e0be41` while constructing effectively identical estimators; the unknown key was ignored by the estimator but retained in identity. Conversely, data/code/environment changes are absent from the hash. This is not content addressing.

The audit environment reported pandas 2.2.1, scikit-learn 1.6.1, XGBoost 2.1.1, LightGBM 4.5.0, NumPy 1.26.4, and PyArrow 25, while `requirements.txt:8` pins pandas 2.1.4. A run record captures none of these versions, so even the inspected environment cannot be reconstructed from cockpit evidence.

Candidate models do not share a fitted estimator object because each run constructs a new pipeline, which is positive. The more serious mutable-state risks are deterministic file overwrite, unlocked index updates, forever-cached data, stale client results/simulations, and a refitted champion surrogate.

Normal cockpit candidate runs write only the sports-cockpit experiment area and do not overwrite the registered D3/C4 champion artifacts; the promotion control is disabled. That is a positive safety boundary. It does not make the candidate evidence immutable, and the reproduced “champion baseline” is not the registered fitted champion object.

## 7. Metrics Findings

### 7.1 Semantic verification

The metric implementation is one of the stronger areas.

- **Class order:** a fixed eight-class order is validated and model outputs are reordered to it before use (`server/sports_modeling/metrics.py:10-70`; `server/sports_cockpit/modeling.py:299-313`).
- **Probability validity:** finite values, bounds, and row sums are checked; the cockpit alignment path defensively renormalizes.
- **Multiclass log loss:** mean negative log probability of the observed class, with probability clipping.
- **Multiclass Brier:** mean of the **summed** one-vs-rest squared errors across all eight classes. This is valid but must be labeled because some literature reports an averaged-per-class variant.
- **ECE:** fixed ten-bin equal-width top-label and per-class calibration errors. The definition is coherent but bin-sensitive.
- **Classification metrics:** top-1 accuracy plus macro/weighted and class-specific precision, recall, and F1 are correctly mapped.
- **Confusion matrix:** client row normalization is correct; axes are mostly clear, although the y-axis lacks a full name.

### 7.2 Independent recomputation

The registered 2024 final prediction parquet (182,449 rows) was read directly. Metrics were recomputed using NumPy formulas without project metric helpers:

| Check | Independent result |
|---|---:|
| Maximum probability row-sum error | `4.44e-16` |
| Multiclass log loss | `1.4840562071` |
| Summed multiclass Brier | `0.7066613133` |
| Top-1 accuracy | `0.4516440211` |
| Macro F1 | `0.0898044042` |
| Equal-width top-label ECE10 | `0.0047150032` |

Those values are the temperature-scaled C4 predictions and correctly differ from raw registered aggregate evidence (log loss about `1.4842548490`, Brier `0.7067859`, ECE `0.0117307`). They also align with the independent raw cockpit ladder near `1.484253`. The math and class ordering are validated; the workflow still needs explicit **raw vs calibrated** labeling and lineage.

### 7.3 Limitations to fix

- Fixed-bin ECE has no bin-count support warning, uncertainty interval, or sensitivity view; rare classes can look deceptively stable.
- The calibration UI shows only five of eight class curves (`src/sports/cockpit/cockpitSteps2.tsx:500-502`).
- Log loss/Brier/ECE are plotted on a shared scale in places, visually compressing ECE.
- Macro F1 is appropriately harsh for rare classes but needs class supports and confidence intervals to be interpretable.
- Metrics need explicit evaluation-population IDs, probability artifact digests, raw/calibrated status, and uncertainty in governed evidence.

## 8. Feature Engineering Findings

### 8.1 What is real

The builder implements ratio, difference, product/interaction, power, `log1p`, quantile bin, indicator, and calendar operations (`server/sports_cockpit/features_builder.py:20-95`). Safe division avoids zero denominators, and training-time quantile bins derive thresholds from development data. `working_frame` actually materializes engineered specs before training, and base-vs-engineered ablation fits two different matrices (`server/sports_cockpit/modeling.py:49-52,697-733`). The feature comparison is computationally real.

### 8.2 Scientific and security defects

1. **Backend schema boundary (P1):** `col()` accepts any numeric frame column, not only governed source features (`features_builder.py:52-55`). A direct diagnostic successfully selected `season`. Only collisions with base-feature names are rejected (`:109-110`); `outcome`, season, date/IDs, reserved names, and duplicate engineered names are not comprehensively protected.
2. **All-season profile leakage (P1):** engineered-feature MI sampling is development-only, but its missing-value fill uses an all-season median (`features_builder.py:121-142`). This incorporates validation/frozen distributional information.
3. **Semantic mismatch (P2):** the execution engine treats unknown engineered names as continuous, so bins/indicators/calendar features may be standardized and outlier-treated as continuous even when the profiler calls them categorical (`server/sports_cockpit/engine.py:219-224`).
4. **Domain validation (P2):** `log` silently clips negative input to zero; power exponent, bin count, and thresholds lack finite/domain/range bounds. Very large bin counts can cause large allocations (`features_builder.py:81-94`).
5. **Ablation control (P2):** the UI hard-codes all 22 features plus logistic/C=1 instead of the scientist's current control family/features/policies (`src/sports/cockpit/cockpitSteps1.tsx:1588-1601`). Its final verdict then uses frozen 2025.
6. **Empty selection (P2):** an explicitly empty feature list falls back to every base feature rather than failing closed (`modeling.py:585-593`).

The eight current engineered features produce essentially no validation log-loss improvement (L5 `1.484253` vs L6 `1.484286`). They should not be marketed as gains. A scientifically valid ablation must derive the exact current control, change only the intended features, select on permitted validation evidence, and keep 2025 blinded.

## 9. Segmentation Findings

### 9.1 Decision formulas

Segmentation is currently labeled exploratory and is not automatically converted into predictive features. That honesty is important. The recommendations are nevertheless composite heuristics:

- **K-means score:** 35% normalized silhouette + 25% inverse normalized Davies–Bouldin + 20% 2023→2024 membership stability + 10% balance + 10% usable fraction (`server/sports_cockpit/segmentation.py:64-123`).
- **3×3 grid score:** 35% cell balance + 30% non-redundancy + 20% 2024 stability + 15% coverage (`segmentation.py:212-261`).
- **DBSCAN:** treated separately as a density/noise diagnostic, which is scientifically preferable to forcing it into the K-means score.

Concerns:

- Validation-season stability participates in recommendation selection. This is acceptable only as explicitly exploratory research or inside a nested decision design.
- Min-max normalization makes K-means choice relative to the candidate K range; changing the tested range can change the scale and winner.
- Player clusters and PA-weighted reporting answer different questions; the current balance/coverage interpretation needs clearer weighting.
- Composite weights are judgment calls, not validated utilities. Coverage is often constant and contributes no discrimination.
- No out-of-time predictive ablation establishes that segmentation helps the outcome model.

### 9.2 Weight-sensitivity diagnostic

A deterministic 5,000-draw perturbation shifted each nominal weight by at most 0.05 and re-normalized, using only 2023/2024 segmentation inputs.

| Analysis | Nominal winner and score | Runner-up | Winner retained |
|---|---|---|---:|
| Batter K-means | K=2, 0.837 | K=6, 0.462 | 100% |
| Pitcher K-means | K=2, 0.814 | K=6, 0.532 | 100% |
| Batter grid | SO/PA × HR/PA, 0.855 | SO × BB/HBP, 0.849 | 100% |
| Pitcher grid | SO/BFP × BB/BFP, 0.841 | next grid, 0.801 | 100% |

The present winners are locally robust to modest weight changes. That supports keeping the displays as exploratory guidance, not adopting them as governed predictive features. The grid winner's narrow nominal margin and low raw temporal stability still warrant caution. Publish raw components and sensitivity; remove validation from selection or nest it; require predictive ablation before downstream use.

## 10. Persistence Findings

### 10.1 State-location inventory

| State/artifact | Current location | Durability | User/project isolation | Governance assessment |
|---|---|---|---|---|
| Active step, config, notes, engineered profiles, saved-step flags, lab suite, last result/simulation | Zustand + project-keyed `localStorage` | Browser restart only | Project ID only; not user/tenant | Mutable draft, not evidence |
| Forecast contract, data binding, stage adoption/completion | `localStorage` (`workflowState.ts:48-102`) | Browser restart only | Keys are inconsistent and not uniformly user-scoped | Copy overstates “register/govern” |
| Transient tuning trials and segmentation results | React component state | Lost on navigation/remount/refresh | Page-local | Not auditable |
| Cockpit experiment summaries | Global server JSON/index | Survives process restart | No user/project/tenant | Mutable/unlocked/incomplete |
| Autopilot latest | One global server JSON | Survives process restart | No user/project/tenant | Last-writer-wins |
| Core modeling frames/results | Process-local dictionaries keyed user/project | Lost/rebuilt across process | User/project key, but split-brain across collaborators/workers | Not production durability |
| Session checkpoint | One plaintext whole-file checkpoint | Restart recovery | Shared root; process-local lock only | Atomic replace but multi-worker last-writer-wins; final model restored as `None` |
| Canonical registries/evidence | Mixed database/files | Better | Varies by route family | Some strong paths; inconsistent envelope |

### 10.2 Failure-mode assessment

- **Refresh/browser restart:** local cockpit drafts return on the same browser; transient tuning/segmentation does not.
- **Re-login/shared browser:** previous-user cockpit/workflow/local-project state remains accessible because keys omit user/tenant and logout does not clear it all.
- **Project switch:** if Project B has no snapshot, singleton state from A is not reset and can be autosaved under B.
- **Multiple tabs:** last write wins; there is no revision, storage-event reconciliation, conflict warning, or merge.
- **Multiple users:** the browser is split by client, but server experiment/autopilot namespaces are global; collaborators' core scientific states are separate per-user RAM rather than one versioned project workspace.
- **Multiple workers:** process-local stores diverge; whole-file checkpoint/index updates are not protected by distributed transactions.
- **Version mismatch:** snapshot version is checked, but payload shape and backend `schemaVersion` are not consistently validated by frontend types.

Persistence is usable for **individual disposable development with manual discipline**. It is not strong enough for scientist testing, private beta, multi-user production, regulated evidence, or disaster recovery of fitted models.

## 11. Workflow Findings

The table below answers, for every scientist stage, the decision, artifact, consumer, persistence/governance, and whether the UI can imply a choice was applied when it was not.

| Stage | Scientific decision and artifact | Downstream consumer | Persistence / governance | Execution truth and disagreement risk |
|---|---|---|---|---|
| Dataset | Choose exact data population/version; expected artifact is an authorized dataset binding | Target, EDA, all fits | Browser note/binding; displayed counts partly hard-coded | **Decorative selection.** Backend loads fixed first-glob MLB view; UI can name another dataset/version. |
| Target / Objective | Define target, class semantics, hypothesis, intended use | EDA, feature contract, fit, metrics | Forecast/objective records in localStorage; hypothesis absent from run identity | **Mixed/decorative.** Backend always uses `outcome`; six-target contract can disagree. |
| Population | Establish eligible rows and season roles | Split and evaluation denominators | Read-only payload plus browser confirmation; no immutable population digest | Counts agree now, but fixed constants/glob/caches can drift. |
| EDA | Inspect distributions/signal and include/exclude predictors | Experiment config | Predictor list autosaves; profiles are cached server/browser | Feature toggles reach fit. EDA is not linked as immutable selection evidence; frozen target/descriptives are exposed. |
| Outliers | Choose fold-local clipping/winsorization policy | Preprocessor | Autosaved config; saved vs preview is clearly labeled | **Real.** Saved policy reaches development-fitted preprocessor; no immutable fitted artifact. |
| Missing Values | Choose fill/indicator policy | Preprocessor | Autosaved config; saved vs preview labeled | **Real with ambiguity.** “No imputation” can still fall back to median behavior. |
| Feature Engineering | Define typed transforms and selected engineered columns | Working matrix, ablation | Specs/config autosave; profiles/browser state | **Real matrix change**, but backend schema, kind semantics, profile leakage, and ablation control are defective. |
| Segmentation | Explore player archetypes/density/grid | Currently none | Notes plus transient React results; no server artifact | **Honestly exploratory/disconnected.** Recommendation uses validation stability; not predictive evidence. |
| Temporal Split | Choose season/rolling/expanding/date/random folds | Fit/tune/evaluation | Notes only; boundary may be lost | **Decorative application.** All runs execute 2023→2024→2025. |
| Model Laboratory | Compare requested families on common evidence | Tuning/evaluation/active challenger | Backend global JSON; compact `labSuite` locally | Fits are real, but no active-result handoff; candidate hypers discarded. |
| Hyperparameter Tuning | Search candidate-specific settings | New active candidate | Component-local trials; generic config mutation | **Partial/disconnected.** Logistic C only, regardless of selected family; result not activated. |
| Evaluation | Review discrimination/calibration/class diagnostics | Calibration, simulation, promotion | Reads `lastResult` | **Disconnected after fresh runs**; stale restored result may masquerade as current. |
| Calibration | Choose/fit/apply raw vs calibrated policy | Simulation, promotion, registry | No config, endpoint, or artifact | **Decorative diagnostics.** Raw charts only; copy contradicts frozen policy. |
| Simulation Impact | Measure quick/full game impact | Promotion gate | `lastSim` localStorage without parent ID | Backend computation is real, but may use stale/default candidate and hard-coded external paths/cache. |
| Champion / Challenger | Decide promotion under explicit gates | Registry/deployment | Global ledger/reference; button disabled | Gates combine unlinked result/sim and use frozen improvement; no decision artifact. |
| Registry / Evidence | Preserve reproducible run/model card | Governance/review | Mutable global metrics JSON; page reads `lastResult` | **Partial viewer, not registration.** No model/preprocessor/predictions/full lineage/project scope. |

The primary action copy is often clear at the page level, and saved-vs-preview language is good in Outliers and Missing Values. The decisive UX defect is semantic: real-looking controls and “governed” labels imply authority that the execution path does not honor. That is more serious than visual polish.

Additional usability findings:

- The scientist cannot reliably distinguish a current active candidate from a checked leaderboard row or stale restored result.
- The autosave badge conflates browser-cache progress with durable/governed evidence (`src/sports/cockpit/PaModelingCockpit.tsx:131-148`).
- Generic histograms hide x ticks/units; several charts omit axis labels; confusion y-axis is unnamed; CRPS/MAE/Brier/ECE lack a local glossary (`src/sports/cockpit/cockpitUi.tsx:158-166,277-290`; `cockpitSteps2.tsx:536-538`).
- Evaluation charts sometimes compare unlike metric scales on one axis.
- Recovery actions should identify the exact active experiment/dataset/split rather than telling the user only to rerun a challenger.

## 12. Governance/Auditability

### 12.1 Reconstruction matrix

| Decision | Where stored now | Immutable/versioned/content-addressed? | Linked to experiment? | Reproducible later? |
|---|---|---|---|---|
| Dataset/version/content | Display constants, fixed resolver, browser binding | No | No | No |
| Target/class contract | Browser contract plus backend constant | No | No | No |
| Population | Hard-coded roles/counts plus runtime frame | No population digest | No | Partial only while current data remain |
| Predictors/exclusions | Experiment config and local state | Mutable file; limited hash | Yes, but empty fallback/authority ambiguity | Partial |
| Outlier policy | Experiment config | Mutable | Yes | Logic reproducible; fitted bounds not stored |
| Missing policy | Experiment config | Mutable | Yes | Logic reproducible; fitted fills not stored |
| Engineered features | Specs in config; profiles local | Mutable; kind incomplete | Partial | Partial |
| Segmentation | Notes/transient response | No | No | No |
| Temporal split/folds | Notes and fixed backend constants | No | **No** | No for selected UI policy |
| Model family | Config/result | Mutable | Partial | Source-dependent; estimator not stored |
| Effective hyperparameters | Raw client dict | No canonical effective config | Partial | No; ignored/default params confuse identity |
| Code/environment/dependencies/seed | Not recorded | No | No | No |
| Calibration | Governed C4 elsewhere; none in cockpit | Cockpit: no | No | No for cockpit candidate |
| Evaluation/predictions | Summary metrics only | Mutable file | Partial | No independent recomputation from run artifact |
| Simulation | Browser result/global caches | No parent digest | No | No |
| Champion decision | Reference/disabled UI/local gates | No signed decision record | No trustworthy link | No |

### 12.2 Governance-language mismatch

`saveContract`, `saveBinding`, and stage adoption are `localStorage.setItem` operations (`src/sports/workflow/workflowState.ts:48-102`), yet UI actions use “Save & Register,” “governed,” and “adopt.” Stage completion derives from mutable booleans; adoption can occur even when evidence is unavailable (`src/sports/workflow/GuidedStageContent.tsx:157-174`; `GuidedWorkflow.tsx:219-239`). No actor, timestamp, rationale, artifact digest, version, approval, or separation of duties is required.

Required governance object: an append-only adoption/decision record containing tenant/project, actor/role, UTC time, rationale, exact parent artifact IDs/digests, dataset/target/population/split contracts, model/preprocessor/calibrator/prediction/simulation digests, code/environment, policy version, and approval state. A browser flag can remain a draft indicator but must never be presented as registry evidence.

## 13. Architecture Findings

### 13.1 Correctness defects versus architecture debt

The broken result handoff, non-propagating split, frozen reuse, global authorization, path traversal, and mutable experiment identity are correctness/security defects and must be fixed directly. The following are architecture debt that makes those defects likely to recur:

- **Competing scientific engines:** cockpit has its own `Preprocessor`/estimator factory; D3/C4 has `FoldPreprocessor`/training/calibration; general training has another catalog (`server/sports_cockpit/modeling.py:113-296`; `server/sports_modeling/training.py:63-115,306-345`; `server/training/trainer.py:318-535`). Defaults, validation, lineage, and calibration differ.
- **Scattered MLB constants:** dataset root, target, years, class order, feature list, manifests, and UI header are embedded across backend/frontend rather than injected through one domain contract (`server/sports_cockpit/engine.py:54-150`; `src/sports/cockpit/cockpitApi.ts:237-241`; `PaModelingCockpit.tsx:70-83`).
- **Resolver/cache coupling:** first-glob resolution and forever caches are not keyed by authorized dataset version/content digest.
- **Monoliths:** `cockpitSteps1.tsx` is about 1,969 lines, `cockpitSteps2.tsx` 704, `engine.py` 909, and `modeling.py` 842. Domain decisions, requests, persistence, and rendering are intertwined.
- **Weak schemas:** representative seams use `Record<string, any>`, `any` snapshots, and `dict[str, Any]` bodies. Backend `schemaVersion` is returned but generally not validated client-side.
- **Constant/type proliferation:** a read-only scan found 562 literal occurrences of 2021–2025 and 212 `any`/`Any`-style weak-typing occurrences across the sports cockpit/workflow/backend scope. Not every occurrence is wrong, but the density confirms that time/domain authority is duplicated rather than modeled once.
- **Hard-coded paths:** simulation/game prep references `C:/Users/james/asp-model-exchange/...`, blocking portable deployment and tenant isolation (`server/sports_cockpit/game_preps.py:24-27`; `simulation.py:45-48`).
- **Mutable whole-file stores:** experiment indexes, notebooks, queries, analytics, and checkpoints use unlocked or process-local locking, causing lost updates and multi-worker divergence.
- **Split-brain collaboration:** project governance objects can be shared while scientific frames/results remain per-user process memory.

### 13.2 Testability and claim reconciliation

Frontend “acceptance” tests are predominantly source-string assertions. For example, `tests/cockpitModelLab.test.mjs:30-76` checks source substrings but never renders, clicks, selects an active result, or proves `lastResult` identity. `tests/cockpit6g2.test.mjs:112-127` similarly proves copy/wiring tokens rather than behavior. The audit ran 61 such relevant frontend assertions successfully; they still missed the broken Model Lab journey and decorative split.

Backend tests prove useful functions and family execution. They do not establish browser/backend contract integrity, project authorization, immutable evidence, or concurrent behavior. Phase 6B's report says experiment identity includes population and split, but the current hash does not (`docs/PHASE_6B_SCIENTIST_EXPERIMENTATION_LOOP_REPORT.md:176-180`). Phase 6H's `persist=False` campaign cannot validate registry identity or overwrite behavior.

Required integration spine: authenticate as two users, authorize different projects/datasets, select exact dataset/target, choose and execute a split, configure features/policies, run multiple candidates, activate one immutable run, tune/calibrate it, evaluate/simulate using matching parent fingerprints, adopt/register it, refresh/switch project/open another tab, and prove every displayed ID/digest stays consistent. Include negative IDOR, traversal, stale-state, race, and frozen-blinding tests.

## 14. Prioritized Findings Register

Effort uses **S/M/L/XL** as relative implementation size. “NOW” means release-blocking before the named scientist/private-beta use, not merely the next convenient sprint.

| ID | Severity | Domain | Finding | Evidence | Scientific/Product Impact | Exploit/Failure Scenario | Recommended Fix | Effort | Priority |
|---|---|---|---|---|---|---|---|---:|---|
| SEC-00 | **P0 conditional** | Execution security | “Sandboxed” Python is ordinary host subprocess execution when enabled. | `python_execution.py:101-112,161-165,204-249,323-348,417-528`; `sandbox_policy.py:38-48,139-199,261-271` | Full confidentiality/integrity/availability loss under the API service account. | Authenticated viewer reads/mutates host files, starts subprocesses, or exfiltrates via network on a reachable configuration. | Default off everywhere; disposable OS sandbox, unprivileged identity, no host mounts/network/process access, hard quotas, role/tenant policy. | XL | **NOW** |
| SCI-01 | **P1** | Leakage/model risk | Frozen 2025 is computed, displayed, and used for ablation/promotion. | `modeling.py:516-531,613-655,720-733`; `cockpitSteps2.tsx:350-406,421-553,594-636` | Final generalization evidence is biased; reported improvement is no longer independent. | Scientist iterates until 2025 improves and promotes the overfit candidate. | Blind 2025 during interactive work; one-shot authorized immutable final evaluation; no 2025 selection gate. | M-L | **NOW** |
| DATA-01 | **P1** | Data/target authority | UI dataset and target do not bind backend execution. | `cockpitApi.ts:160-167`; `router.py:31-65,139-141`; `engine.py:54-88,165-204,282-313` | Results can be attributed to the wrong population/target. | UI confirms Home Win Probability/dataset A; engine trains PA `outcome` on fixed view. | Mandatory server-resolved project/dataset-version/content/target/population authority token on every run. | L | **NOW** |
| TEMP-01 | **P1** | Temporal integrity | Temporal controls are preview/notes only; all training uses fixed seasons. | `cockpitSteps1.tsx:1872-1950`; `cockpitApi.ts:160-167`; `modeling.py:516-531` | Scientist believes an unexecuted split governed results. | Date/random/rolling is selected, but result remains 2023→2024→2025. | Versioned executable split contract; fail closed on unsupported policy; membership-level tests. | M-L | **NOW** |
| ML-01 | **P1** | Model Lab | Phase 6G removed active-result handoff to Steps 11–15. | `cockpitSteps2.tsx:52-75,416-479,515-655`; no `setLastResult` caller; Git `-S` points to `eddc354` | Core scientist journey is broken or driven by stale evidence. | Fresh leaderboard succeeds but Evaluation is empty; old local result appears instead. | Explicit immutable “activate candidate” transaction and ID-based downstream retrieval; E2E identity test. | M | **NOW** |
| GOV-01 | **P1** | Reproducibility | Experiment ID/hash omits scientific lineage and retries overwrite evidence. | `modeling.py:504-505,620-689` | Run cannot be reproduced or distinguished across data/code/environment changes. | Same config after a data update overwrites prior JSON; concurrent users lose index entries. | Immutable run UUID plus canonical effective-config fingerprint and full lineage; append-only transactional storage. | L | **NOW** |
| SEC-01 | **P1** | Path security | Windows backslash traversal escapes sports experiment directory. | `router.py:149-154`; `modeling.py:755-759`; direct route/Windows normalization proof | Authenticated JSON disclosure beyond authorized experiment. | `..\autopilot\latest` or deeper predictable runtime JSON is returned. | Strict opaque ID allowlist plus resolved `relative_to` containment; preferably DB lookup. | S | **NOW** |
| SEC-02 | **P1** | Cockpit tenancy | Experiments/autopilot are global authenticated namespaces. | `main.py:500`; `sports_cockpit/router.py:31-260`; `modeling.py:663-689,745-759,784-841` | Cross-user read/clobber; no project evidence isolation. | Any authenticated user lists another user's experiments or overwrites same-config evidence/latest Autopilot. | Actor/project ownership on every object/list; tenant-filtered transactional store. | L | **NOW** |
| SEC-03 | **P1** | Object authorization | Registry Dashboard and Recovery Registry bypass project/dataset ACLs. | `registry/router.py:24-87`; `registry_service.py:458-470,759-857,937-1059`; `projects/project_router.py:17-51`; `project_registry.py:102-200` | Cross-tenant metadata/path disclosure and recovery-record mutation. | User enumerates all projects/datasets/owners/activity or reparents recovery metadata. | Canonical parent resolution and ACL filter; admin-only audited recovery; never return host paths. | M | **NOW** |
| SEC-04 | **P1** | Object authorization | Analytics Engine and Validation Center are global authenticated namespaces. | `analytics_engine/router.py:8-30`; `service.py:37-76`; `validation/router.py:26-104`; `validation_service.py:57-413` | Runs/cases/evidence can be read, cancelled, or mutated across projects. | Attacker cancels victim run or adds evidence/findings to victim project/case. | Object→project authorization for every list/read/mutation; derive project server-side; separation of duties. | M | **NOW** |
| SEC-05 | **P1** | Workspace tenancy | Notebook, saved SQL, chart, and analytics objects lack one ownership envelope. | `notebook_router.py:79-197`; `notebook_store.py:140-327`; `sql_router.py:95-152`; `sql_store.py:48-93` | Cross-user read/export/overwrite and evidence misattribution. | Known ID permits notebook export/update; arbitrary project ID attaches attacker result to victim project. | Immutable tenant/owner/project/dataset identity, authorized CRUD/export/attach, revision matching, transactions. | L | **NOW** |
| PERS-01 | **P1** | Browser persistence | LocalStorage is not user/tenant scoped and project hydration can copy state. | `cockpitPersistence.ts:17-50,71-107`; `auth.ts:45-54`; `SportsProjects.tsx:10-40,124-163` | Shared-browser disclosure; cross-project stale science. | User B logs in after A; or unsaved Project B receives Project A config/result. | Namespace by tenant+user+project, clear/lock on logout, reset before hydrate, backend-authorized project list. | M | **NOW** |
| STATE-01 | **P1** | State integrity | Results and simulations lack dependency invalidation/parent fingerprints. | `cockpitApi.ts:258-329`; `cockpitSteps2.tsx:518-531,629-637` | Wrong candidate can satisfy evaluation/promotion gates. | Change features after run, then combine old metrics with unrelated simulation. | Fingerprint every derived artifact; invalidate descendants on any ancestor change; fail on mismatch. | M | **NOW** |
| FE-01 | **P1** | Feature engineering | Backend accepts ungoverned/reserved columns; profile fill uses all seasons. | `features_builder.py:52-55,109-142`; direct `season` selection diagnostic | Leakage/schema corruption and attacker-controlled resource use. | API engineers `season` or target/split column; validation/frozen median affects MI profile. | Server allowlist/reserved names/unique output; dev-only fit/profile; finite/range/type limits. | M | **NOW** |
| CAL-01 | **P1** | Calibration/governance | Cockpit calibration is raw diagnostics with contradictory frozen-based policy copy. | `cockpitSteps2.tsx:476-509`; no calibration API/config/artifact; `sports_modeling/calibration.py:106-223` | Scientist may believe raw probabilities are calibrated/governed. | Promotion or simulation attributes C4-style calibration to an uncalibrated cockpit run. | Relabel diagnostics now; later add explicit dev/validation-fitted calibrator artifact and lineage, never frozen selection. | M | **NOW** |
| GOV-02 | **P1** | Governance UX | “Register/govern/adopt/complete” often means local mutable booleans. | `workflowState.ts:48-102,229-247`; `GuidedStageContent.tsx:157-174`; `GuidedWorkflow.tsx:219-239` | Audit trail can be claimed without evidence. | User completes stages/adopts while artifact is unavailable; no actor/time/digest/rationale. | Backend append-only adoption records linked to immutable artifacts; disable action without evidence/approval fields. | L | **NOW** |
| PERF-01 | **P1** | Resource abuse | Training/Python/SQL/upload limits do not provide tenant CPU/RAM/concurrency containment. | `modeling.py:218-295`; `training_job_service.py:598-744`; `sql_engine.py:43-51,140-173`; `main.py:248-287` | Multi-user outage or denial-of-wallet. | Huge estimator/depth/hidden-layer values with `n_jobs=-1`; many jobs/uploads/queries exhaust host. | Central scheduler; bounded typed schemas; user/org quotas; OS resource limits; SQL progress handler; streaming uploads. | L | **NOW** |
| PERS-02 | **P1** | Multi-worker persistence | Scientific state is process-local; checkpoint/index stores are split-brain. | `dataset_store.py:288-332`; `result_store.py:226-265`; `session_checkpoint.py:269-395,763-907` | Restart loses fitted state; collaborators/workers see divergent workspaces. | Two workers overwrite a shared checkpoint; final model restores as `None`. | Project-owned versioned workspace, transactional DB/object store, optimistic versions, persisted fitted artifacts. | XL | **NOW** before multi-user |
| ML-02 | **P2** | Model family/tuning | Suite discards hyperparameters and “send to tuning” does not select family; tuning is logistic-C-only. | `cockpitSteps2.tsx:58-69,350-410` | Advertised eight-family lab is not an experiment-driven tuning workflow. | RF selected for tuning, but logistic C grid runs. | Typed candidate configs and family-specific validated temporal search spaces. | M-L | NEXT |
| FE-02 | **P2** | Feature semantics | Categorical engineered kinds are lost; empty list falls back; ablation control is hard-coded. | `engine.py:219-224`; `modeling.py:585-593`; `cockpitSteps1.tsx:1588-1601` | Wrong transforms and misleading ablation verdict. | Bin feature is scaled/clipped as continuous; “no features” silently trains all. | Preserve kind contract; reject empty/unknown; derive exact current control. | M | NEXT |
| SEG-01 | **P2** | Segmentation | Composite recommendations use validation stability and relative normalization; no predictive evidence. | `segmentation.py:64-123,212-261` | Plausible-looking score can be mistaken for validated utility. | Scientist adopts K/grid because score is high even though outcome value is unknown. | Keep exploratory; publish components/sensitivity; nest validation; require out-of-time predictive ablation. | M | NEXT |
| DATA-02 | **P2** | Data resolver/cache | First-glob dataset resolution, fixed constants, and forever cache are weak authority. | `engine.py:67-88,165-204,307-380` | Displayed and executed data can diverge after another artifact/registration appears. | Lexicographically earlier feature view is silently selected; process cache ignores update. | Resolve exact authorized manifest/content SHA and key/invalidate caches by it. | M | NEXT |
| DATA-03 | **P2** | Leakage/EDA | Frozen target rows/distribution and all-season descriptives are exposed. | `engine.py:282-299,446-555,581-700` | Repeated visual inspection can guide feature/model choices on final data. | Scientist sees 2025 class changes/extremes and adapts model. | Blind 2025 outcomes/features except provenance/count assertions until final authority. | M | NEXT |
| MODEL-01 | **P2** | Model-family science | Non-logistic families lack governed search/calibration/convergence/runtime controls. | `modeling.py:70-82,218-296` | Family leaderboard overstates comparability and reproducibility. | MLP non-convergence or non-temporal SVM calibration wins without warning. | Narrow supported surface or add family schemas, temporal CV, diagnostics, calibration, deterministic settings. | L | NEXT |
| SEC-06 | **P2** | Session security | Password change leaves sessions active; tokens plaintext; lockout can be abused; policy/MFA/reset incomplete. | `security_store.py:274-283,371-376,552-664`; `security_router.py:133-140` | Account recovery/session assurance below paid/bank standard. | Stolen session survives password reset; attacker locks target account. | Token hashes, session rotation/revocation, modern KDF/MFA/reset, layered throttling. | M | NEXT |
| SEC-07 | **P2** | ACL/export/errors | Dataset editor can grant owner; spreadsheet formula injection and raw error/path disclosure remain. | `dataset_registry.py:517-531,1056-1124`; `sql_router.py:156-203`; `chart_router.py:102-172` | Privilege escalation and client-side export risk. | Editor creates owner; exported cell executes formula on open. | Separate ACL admin role; neutralize formulas; generic correlated errors. | S-M | NEXT |
| ARCH-01 | **P2** | Architecture | Cockpit, governed sports, and general training duplicate scientific logic. | `sports_cockpit/modeling.py:113-296`; `sports_modeling/training.py:63-115,306-345`; `training/trainer.py:318-535` | Fixes and evidence semantics diverge across engines. | Leakage/calibration/default fix lands in one engine only. | Shared typed preprocessing/model/evidence contracts with sport adapters. | XL | NEXT |
| ARCH-02 | **P2** | Extensibility | MLB/years/paths/schema are hard-coded and frontend/backend duplicated. | `engine.py:54-150`; `cockpitApi.ts:237-241`; `game_preps.py:24-27`; `simulation.py:45-48` | NFL/NHL expansion would clone brittle logic and local paths. | Deployment on another machine/sport resolves wrong or missing artifact. | Inject versioned `ModelingDomainSpec`; generate client schema/catalog; portable artifact resolver. | L | NEXT |
| TEST-01 | **P2** | Test coverage | Passing frontend tests are mostly source-string checks and miss the broken journey. | `cockpitModelLab.test.mjs:30-76`; `cockpit6g2.test.mjs:112-127`; Phase 6H no browser automation | Reports overstate readiness despite green tests. | All tests pass while split is ignored and result handoff absent. | Behavioral component/browser E2E plus authorization/race/frozen negative tests. | M-L | **NOW** |
| MET-01 | **P3** | Metrics UX | ECE/bin uncertainty, rare-class support, raw/calibrated labels, and all-class curves are incomplete. | `metrics.py:158-248`; `cockpitSteps2.tsx:500-502` | Correct numbers can still be overinterpreted. | Rare-class ECE looks stable from few cases; raw result mistaken for calibrated. | Bin counts/CIs/adaptive sensitivity, eight-class access, explicit metric definitions/status. | M | LATER |
| UX-01 | **P3** | Scientific UX | Several axes/units/acronyms are missing and autosave wording implies durable evidence. | `cockpitUi.tsx:158-166,277-290`; `PaModelingCockpit.tsx:131-148`; `cockpitSteps2.tsx:536-538` | Slower interpretation and evidence-state confusion. | User reads browser “Saved” as registered or compares unlike metric scales. | Clarify draft vs registered, add axes/units/glossary/small multiples after semantic integrity. | S | LATER |

## 15. Readiness Scorecard

### 15.1 Dimension scores

| Dimension | Score (1–5) | Rationale |
|---|---:|---|
| Scientific correctness | **2** | Base timing/preprocessing and metrics are sound, but frozen selection, decorative calibration, and authority mismatch invalidate the governed workflow. |
| Temporal integrity | **1** | UI policies do not execute; 2025 is operationally reused. |
| Data authority | **1** | Dataset/target/project are not backend run inputs; resolver and counts are weakly bound. |
| Experiment reproducibility | **1** | Mutable partial hash, no data/code/env/seed/model/preprocessor/predictions lineage. |
| Model-lab integrity | **1** | Real fits, but candidate activation and tuning/evaluation handoff are broken. |
| Feature engineering | **2** | Real typed transforms and matrix contrast; schema, profile leakage, kind, validation, and ablation issues. |
| Segmentation | **3** | Transparent exploratory tools and locally robust rankings; validation enters heuristics and predictive value is unproven. |
| Metrics | **4** | Correct semantics/class alignment and independent reproduction; uncertainty/raw-calibrated UX remains. |
| Persistence | **1** | Browser drafts, global mutable JSON, process-local state, and multi-worker split-brain. |
| Security | **1** | Conditional host-code-execution P0, confirmed traversal, broad object-authorization gaps, insufficient resource containment. |
| Multi-user readiness | **1** | Cross-user/global namespaces, localStorage disclosure, missing ownership envelopes and concurrency controls. |
| Auditability | **1** | Key decisions are mutable/unlinked/unversioned; adoption language exceeds evidence. |
| Workflow clarity | **2** | Page-level copy is often good, but authoritative vs preview/saved/current states are materially misleading. |
| Architecture extensibility | **1** | Duplicated engines, hard-coded MLB/years/paths, monoliths, weak schemas. |
| Performance stability | **2** | Bounded normal runs work, but user parameters/threads/jobs/uploads/SQL/Python lack centralized quotas. |

### 15.2 Current readiness

| Deployment/use level | Decision | Conditions / reason |
|---|---|---|
| Local research | **CONDITIONAL** | One trusted user, loopback-only service, Python execution understood as host execution or disabled, 2025 manually blinded, disposable results, and manual lineage. Direct backend exploration is useful under those constraints. |
| Scientist testing | **NO-GO** | A scientist can select a dataset/target/split/model that is not the executed/active identity; frozen evidence guides iteration; Steps 11–15 are disconnected. |
| Private beta | **NO-GO** | Object authorization, shared-browser leakage, execution isolation, persistence/concurrency, and quotas are not sufficient. |
| Paid pilot | **NO-GO** | No reproducible immutable experiment package, reliable tenant envelope, or controlled operational execution. |
| Bank-grade production | **NO-GO** | Fails least privilege, isolation, SoD, immutable lineage, reproducibility, change control, session assurance, evidence retention, and resource containment expectations. |

## 16. Top 10 Recommended Actions

1. **Disable Python execution by default in every mode and keep it unavailable to untrusted users until it runs inside a true disposable OS sandbox with hard resource/network/filesystem controls.**
2. **Immediately close the sports experiment traversal and global namespace:** strict opaque IDs/resolved containment, project/actor ownership, tenant-filtered lists, and transactional storage.
3. **Apply one object-authorization envelope across Registry, Recovery, Analytics Engine, Validation, Notebook, saved SQL/chart/insight, and cockpit routes; add two-user negative tests.**
4. **Blind 2025 from all interactive payloads, UI, ablation, tuning, calibration, and promotion. Create a one-shot authorized final-evaluation service with immutable disclosure/audit records.**
5. **Make dataset version/content SHA, exact target/population, and an executable temporal contract mandatory server-side run inputs. Reject mismatches and unsupported policies.**
6. **Create immutable run identity and evidence:** unique run ID plus canonical effective-config hash, full data/code/environment/seed/actor/project lineage, append-only writes, fitted preprocessor/model/calibrator, and prediction/simulation digests.
7. **Restore the Model Lab handoff through an explicit “activate candidate” transaction; require every downstream result/simulation/gate to verify the same parent fingerprints and invalidate on change.**
8. **Replace regulated `localStorage`/process-local/global-JSON state with a versioned project workspace:** user-scoped drafts, reset-before-hydrate, optimistic concurrency, multi-worker transactions, secure logout behavior, and persisted fitted artifacts.
9. **Enforce backend scientific/resource schemas:** governed feature allowlist/reserved names/kinds, dev-only profiling, bounded hyperparameters/threads/jobs/uploads/SQL, central scheduler, per-user/org quotas, and OS resource limits.
10. **Build one behavioral integration spine before re-rating readiness:** real clicks and API calls from dataset/target/split through candidate activation, tuning/calibration/evaluation/simulation/registration, plus refresh/project-switch/tab/concurrency, IDOR, traversal, and frozen-blinding tests.

## 17. What NOT to Work on Yet

Do **not** spend the next cycle on:

- adding more model families, larger grids, AutoML breadth, or blind hyperparameter sweeps;
- inventing more engineered features or making segmentation clusters predictive;
- retraining, promoting, or replacing D3/C4/champion based on the current cockpit;
- a broad cosmetic redesign, animation, branding, or chart polish beyond copy needed to stop false authority claims;
- NFL/NHL/other-sport expansion while dataset/target/split identity is still hard-coded;
- optimizing the approximately 1.484 plateau before preserving a trustworthy matrix/run/prediction lineage;
- adding a new registry façade over mutable files instead of fixing the ownership/evidence model;
- calling browser autosave “governed persistence” or adding more adoption checkboxes;
- enabling Python execution for beta users under the current `python -I` policy;
- declaring scientist readiness from source-string tests or `persist=False` backend campaigns.

The information ladder says the present plateau is mostly weak signal, not a reason to accelerate model complexity. Authority, isolation, frozen integrity, reproducibility, and the active-result chain must be repaired first.

## 18. Final Verdict

ASP Model Studio contains a credible **local scientific engine foundation**, but it is currently wrapped in an authority, persistence, security, and workflow layer that can tell a materially different story from what the backend executed. That mismatch is the defining risk: the user can receive real numbers from the wrong dataset/target/split/candidate and then preserve mutable summaries as if they were governed evidence.

The correct present classification is:

- **Local research: CONDITIONAL**
- **Scientist testing: NO-GO**
- **Private beta: NO-GO**
- **Paid pilot: NO-GO**
- **Bank-grade production: NO-GO**

The Phase 6H readiness claim should be withdrawn until the NOW register is closed and independently retested. No champion or scientific result should be changed on the basis of this audit; the audit's purpose is to repair the truthfulness and control of the workflow before additional modeling work.

---

**branch:** `phase5-game-replay-foundation`  
**HEAD:** `a95b197841f534a97c16fbfc3e9026d713f4725f`  
**worktree:** clean at audit start; report-only change at completion (`GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`)  
**files created:** `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md` only  
**tests/diagnostics run:** Git/status/history/report/source tracing; 38 relevant Phase 6F/6G/6G.1/6H backend tests effectively passed (37 passed in the restricted sandbox; one HGB test hit a Windows joblib named-pipe permission error and passed alone outside that restriction); 61 relevant frontend assertions passed; security lockout 6 passed; persistence authorization 5 passed; combined security containment reached 8 passes before a test-isolation SQLite-schema failure; model-artifact verification could not run in the restricted temp directory; independent 2023/2024 information ladder; independent 2024 metric recomputation; 5,000-draw segmentation-weight sensitivity; configuration-hash/effective-estimator probe; engineered-column boundary probe; Starlette/Windows traversal proof and read-only endpoint check.  
**whether code changed:** NO — no application or test code changed; only this audit Markdown was created  
**whether science changed:** NO — no model, feature contract, split, calibration, metric, prediction, or decision policy changed  
**whether registry changed:** NO  
**whether D3/C4 changed:** NO  
**whether frozen data was touched:** YES — existing representative tests and authority checks loaded/scored 2025 read-only; it was never used for fitting, persisted by this audit, modified, or written  
**whether any push occurred:** NO

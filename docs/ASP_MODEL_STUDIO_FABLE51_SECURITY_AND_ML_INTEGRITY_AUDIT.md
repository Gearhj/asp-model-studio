# ASP Model Studio — Independent Security, Model-Risk, Leakage, Workflow, Artifact, Isolation and Scalability Audit

Auditor: Claude Fable 5.1 (audit-only mandate; no application source modified).
Date: 2026-09-05.
Repository: `C:\Users\james\asp-model-studio`. AI Sports Predictor was not inspected, queried, restarted, or modified.

**Final verdict: `ASP_MODEL_STUDIO_NOT_READY_TENANT_ISOLATION_BLOCKERS` + `ASP_MODEL_STUDIO_NOT_READY_WORKFLOW_BLOCKERS` + `ASP_MODEL_STUDIO_NOT_READY_SCALE_BLOCKERS` + `ASP_MODEL_STUDIO_NOT_READY_BACKUP_RESTORE_BLOCKERS` + `ASP_MODEL_STUDIO_NOT_READY_DATA_RIGHTS_BLOCKERS`.**
The strongest positive statement the evidence supports is that the build is **private-research ready for a single trusted
operator** (`ASP_MODEL_STUDIO_PRIVATE_RESEARCH_READY`), with one condition: the Wave 2 V2 prior authorities must be republished
into the governed runtime root before the Codex worktree that holds their only copy is removed (F-002).

The scientific core is in good shape: no target, temporal, fold, search, calibration, or final-OOT leakage was found; the Wave 2
empirical-Bayes authorities reproduce exactly from raw evidence; artifacts, receipts, splits, policies and specifications are
content-addressed and fail closed against tampering. What is not ready is everything a second user would touch: a P0 project
takeover, a single-project Model Laboratory, in-process single-slot jobs, no backups, and research-only data rights.

---

## 1. Access classification, base, and lineage (Phase 1)

| Item | Value |
| --- | --- |
| Access classification | Full read access to the repository, runtime roots, staging roots, and both SQLite databases (opened read-only/immutable); write access limited to a new worktree/branch, scratch space, and disposable copies |
| Repository root | `C:\Users\james\asp-model-studio` (independent `.git`, no alternates) |
| Audited base branch / HEAD | `codex/mlb-player-prior-wave2` / `bff19a8a657bc96dea0469fad481acdcb4234386` (expected value confirmed) |
| Main HEAD | `924db29511f93909f9d785855bfa056775443690` (local only; no `origin/main` ref exists) |
| Wave 2 starting parent | `64a74be89b029adc013e118b14aad75e3ddc0232` (confirmed: `bff19a8` is 4 commits ahead of it: 6e26c19, 3f86530, f88f011, bff19a8) |
| Protected primary checkout | `C:\Users\james\asp-model-studio` on `codex/mlb-governed-prior-engine-v1` @ `33cd85fa5074efeec3077036baea9c8b2ef86bdf` (clean, reflog shows only `reset: moving to HEAD` at 11:12 today) |
| Audit branch / HEAD | `claude/fable51-model-studio-security-ml-integrity-audit`, created from `bff19a8` (tree byte-identical); HEAD after committing the deliverables is recorded in the final section |
| Audit worktree | `C:\Users\james\worktrees\asp-model-studio-fable51-audit` |

### Why bff19a8 is the latest coherent authority

Every other branch is an ancestor of `bff19a8`, in a strictly linear chain: `main (924db29)` → phase-7 branches → `codex/multisport-platform-architecture (17e2907)` → `codex/stage3-executable-artifact-game-scoring (5e3a2c6)` → `codex/mlb-feature-treatment-spec-v1 (3b7cad5)` → `codex/mlb-governed-prior-engine-v1 (33cd85f, the primary checkout)` → `codex/mlb-interaction-authority-v1 (0900665)` → `codex/mlb-remaining-feature-authority-wave1 (64a74be)` → `codex/mlb-player-prior-wave2 (bff19a8)`. `git branch --contains bff19a8` returns only `codex/mlb-player-prior-wave2`; no branch descends from it. The single non-ancestor branch, `claude/mlb-remaining-feature-authority-audit (056aca1)`, forks from `33cd85f` and adds three audit documents only (592 insertions, no source). Lineage is therefore unambiguous, and the primary checkout is 15 commits behind the latest coherent authority; the audit did not use the checked-out branch as its base.

### Worktrees, locks, untracked files

Five registered worktrees (primary; `.tmp/asp-interaction-authority-v1` @0900665; `.tmp/asp-player-prior-wave2` @bff19a8; `.tmp/asp-remaining-feature-authority-wave1` @64a74be; `C:\Users\james\worktrees\asp-remaining-authority-audit` @056aca1), all clean, none locked, no `index.lock`. **No untracked files exist in any worktree**; the two named user files (`ASP_MLB_Feature_Treatment_Specification.xlsx`, `docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md`) are absent from this repository (the workbook is referenced by SHA `0e2d5f2b…` inside the compiled specification). Ignored roots: `.env.local` (one variable, `ASP_MODEL_EXCHANGE_ROOT`), `.runtime/` (8.9 GB; 8.5 GB is `sports-modeling/mlb-pa-gen3-v2`), `.tmp/`, `.venv/`, `node_modules/`, `dist/`, `server/data/atlas_local.db`, `server/artifacts/security/`. Nothing was deleted, reset, stashed, rebased, pushed, or merged. Codex (`codex.exe` app-server) was running on the workstation throughout; no file in any Model Studio worktree changed during the audit except through the audit's own scratch/worktree writes.

### Runtime at audit start

The primary Model Studio services (frontend 127.0.0.1:5274, backend 127.0.0.1:8101) were **not running**; ports were free. The listeners on 8000, 5173 and 8010 belong to AI Sports Predictor and were left alone. Tooling: Python 3.12.6 (`.venv`), Node 24.3.0, npm 11.6.4, git 2.47.1, SQLite 3.45.3, Chromium 152 / Playwright 1.61.1 (chromium-1228), Windows 10 Pro 19045, Intel i7-4790 (4c/8t), 32 GB RAM, 105 GB free. No primary service was started or restarted for the audit; all dynamic testing used isolated processes on 8191/5291.

### Persistence baseline (primary, read-only)

| Property | persistence `asp_model_studio.db` | security `asp_model_studio_security.db` |
| --- | --- | --- |
| Path | `.runtime/asp-model-studio/persistence/` | `.runtime/asp-model-studio/security/` |
| Size | 53,698,560 bytes | 5,918,720 bytes |
| Journal | WAL (`synchronous=2`, busy_timeout 5000 at the file, 10000 in code) | **delete** (rollback journal) |
| Foreign keys | OFF at file level; `PRAGMA foreign_keys=ON` per connection in code | same |
| Schema | 114 tables, 316 indexes, 38 migrations (last `0038_stage3_feature_treatment_spec_bindings.sql` applied 2026-09-03) | 5 tables |
| Integrity | `ok` | `ok` |
| Backups | none (`backups/` contains only `datasets/`, empty) | none |

Frozen counts (primary): users 6, projects 5, dataset registrations 6 (FD1, current-Statcast, sufficient-statistics companion, 3 NFL foundations), dataset partitions 1,122, populations 12, rights 19, limitations 32, identity bridges 1, project-dataset links 2, active activations 2, activation events 4, treatment-spec versions 8, treatment policy versions 23, feature-set versions 6, split-contract versions 2, split-contract feature sets 6, predicted-imputation previews 1, run records 30, candidate selection decisions 0, models/model_versions 0, export artifacts 0, holdout exposures **0**, dataset query audit **0**, audit_log 30,396; security users 1, credentials 1, sessions 62 (51 unrevoked, 0 unexpired at audit time), audit_events 30,387. Digest receipt: `docs/ASP_MODEL_STUDIO_FABLE51_PROTECTED_RECEIPT.json`.

### Reconciliation of the Wave 2 handoff against reality

| Claim | Verified? | Evidence |
| --- | --- | --- |
| 21 executable priors (11 V1 + 10 V2), 0 awaiting engine, 3 retired | **Yes on asp-mtlozhdx**, only when the V2 store is reachable (F-002) | feature-engineering summary: readyV1=11, readyV2=10, retired=3, bindingReadyRequiresWave2=0, blocked=0 |
| Treatment spec `stage3-feature-treatment-spec-df0a0d98…`, DRAFT, canAdopt=false, blockers = doubleheader + holiday + 14 rivalry | **Yes** | DB row V8 (manifest `9e38ab91…`), API `canAdopt=false`, 3 blocker classes / 16 fields; rivalry 14 fields HELD_CLOSED |
| Development 683,662 rows 2023-03-30..2026-08-13; final OOT 14,067 sealed | **Yes** | Gold partitions + companion recount; OOT partition key-only, all payload columns NULL |
| Gold `67de02ce…`, companion `98673b65…` | **Yes** (manifest bytes hash to their names) | Section 7 receipt |
| V2 authority `9d9cfaf3…`, final fitted `5ae0f9f5…` | **Yes** — reproduced bit-for-bit | Section 12 |
| "Loaded through an isolated local backend/frontend pair" | Partly: the pair used the **authoritative persistence DB** with the default bootstrap security DB, leaving demo users and `local-user` writes in the authoritative store (F-005) | audit_log/user rows dated 2026-09-05T04:19–04:57Z |

---

## 2. Threat model (Phase 2)

See `docs/ASP_MODEL_STUDIO_FABLE51_THREAT_MODEL.md` (actors, assets, boundaries, attack-path diagram, control matrix, 24 abuse cases). Highest-risk paths: (1) ordinary user → self-grant → takeover of any project; (2) concurrent Codex/developer processes writing the authoritative DB and staging roots with synthetic actors; (3) worker = API process, so any deserialization or memory blow-up takes the API down with it.

---

## 3. Authentication, authorization, tenant isolation (Phase 3)

Environment: isolated backend on 8191 with a copy of both databases, three synthetic accounts (`fable51-admin` admin, `fable51-user-a`, `fable51-user-b` data scientists; test-only passwords generated by the audit), plus two projects per ordinary user.

| Area | Result |
| --- | --- |
| Login / logout / me | PASS. Opaque 43-char session id per login, `HttpOnly; SameSite=lax; Max-Age=28800`, no fixation (attacker-chosen cookie replaced), logout revokes the current session, revoked/forged/expired cookies → 401 |
| Password hashing / policy | PBKDF2-SHA256 260k iterations, per-user salt. Policy weak: 8 chars + small deny list, `aaaaaaaa` accepted (F-019). Reset is a stub. Public registration disabled |
| Lockout / rate limiting | Lockout after 5 failures (900 s) works; **no IP or global throttle**: 150 login attempts in 12.4 s, none refused (F-014) |
| Cookies / storage | No token in browser storage; cookie flags correct for local mode; `Secure` only in hosted mode |
| CSRF / CORS | Preflight from an unlisted origin → 400 with no ACAO; but credentialed CORS is granted to `127.0.0.1:5173/5174/3000` (AISP dev origins) in local mode (F-015); server processes a cross-origin POST carrying a valid cookie (F-017) |
| Route authentication | All 616 routes except six public ones require `require_user` (enforced at startup); anonymous probes of 7 representative routes → 401 |
| Admin routes | Non-admin → 403 on `/admin/*`, `/audit/events`, `/security/diagnostics`; self role escalation → 403 |
| Project membership on nested routes | **PASS on 60+ project-scoped routes** (403 for a foreign project id across EDA, treatments, feature sets, splits, model lab, evaluation, downstream, artifact, scoring, evidence/runs/decisions/exports, sharing status) |
| **Project access grant** | **FAIL (P0, F-001)**: `POST /projects/{id}/access/grant {userId:self, permission:owner}` succeeds for any project without explicit permission rows — which is every project. Demonstrated: rename and delete of User B's project, self-grant on the authoritative `asp-mtlozhdx` and `asp-mtddc6pw` copies |
| ACL read | **FAIL (P2, F-004)**: `GET /projects/{id}/access` → 200 for any project |
| Existence inference | 403 vs 404 distinguishable (F-020) |
| Audit access | `/audit-log` for an ordinary user returns only their own/allowed events (0 foreign rows); admin/audit roles required for `/audit/events` |
| Concurrent identity | Clean rerun (288 probes, no destructive steps): 400 interleaved requests (32 threads) alternating A/B — `/auth/me` and `/projects` returned the right user and only that user's projects 400/400 times (p50 674 ms, p95 5.1 s under that burst; the latency is the per-request session write on the rollback-journal security DB, F-028); `ActiveUserContextMiddleware` + contextvars behave correctly under the thread pool. The only non-"missing-id" failures in the clean rerun were the three ACL reads (F-004) and the catalog 500 (F-007) |
| Implicit project creation | `POST /projects/{unknown}/evidence`, `/runs`, `/exports` and `PUT /projects/{unknown}` create a project owned by the caller for any client-chosen id (F-023); this is why "missing project" probes flip from 404 to 200 mid-sequence in the matrix |
| Cockpit research routes | Authenticated but **unscoped** (F-006) |
| Dataset registry | `/sports/datasets/active` returns FD1 registration metadata to any user; `/sports/datasets/catalog` → 500 in the isolated environment (F-007); row previews were refused (exchange root identity mismatch / registration not active) |

Matrix: `docs/ASP_MODEL_STUDIO_FABLE51_TENANT_ISOLATION_MATRIX.csv`.

---

## 4. Application security (Phase 4)

| Class | Result |
| --- | --- |
| SQL injection / dynamic SQL | No injectable path found. Dynamic SQL is identifier-quoted DDL/DML (`quote_identifier`) with parameterized values; bandit B608 hits (124) reviewed by file — all are table-name interpolation from constants. Sharing `_owner_user_id` interpolates from a fixed table map |
| Command injection / subprocess | No `shell=True`; `subprocess.run` with argument vectors only; sandbox policy allowlists the interpreter; user Python execution disabled by default and blocked in hosted mode |
| File read/write / traversal / symlinks | Artifact loaders enforce `_require_contained` and canonical content-addressed paths (traversal via `relative_path` → `STAGE3_ARTIFACT_PATH_INVALID`); `..%2f` project ids → 404; no `FileResponse` download route exposes arbitrary paths |
| Zip/tar-slip, archive bombs | No archive ingestion endpoint exists; a future `.atlas` importer must add these checks |
| Uploads | `/api/data/upload_csv`: 250 MB / 500k rows / 750 columns / extension allowlist; pandas parser; formula cells are stored raw (CSV formula injection surfaces in the admin audit export, F-030) |
| SSRF / egress | `/llm/cleanup-question` posts user text to `ATLAS_LLM_ENDPOINT` if configured, no allowlist (F-031); no other outbound calls in the API |
| XSS | One `dangerouslySetInnerHTML` (`ReportSectionContent`) renders HTML produced by `governanceReport.ts` with `escapeHtml`; no user-controlled raw HTML path found; `react-router` has a published open-redirect XSS advisory (F-024) |
| Deserialization | All `joblib.load` sites verify content addresses first (model registry: checksum from the registry row; Stage 3 artifacts: every manifest member re-hashed; Gen-3: bytes hashed in memory). **18/18 tamper cases rejected before load** |
| Secrets | No secrets in tree or history (pattern scan of all branches); default session secret and default admin password exist in code but the launcher generates a random secret and bootstrap is disabled; `.env.local` holds only a path |
| Debug routes / error disclosure | No debug routes; malformed JSON → 422 with parser detail only; 500 on `/sports/datasets/catalog` returns a generic body |
| ReDoS / unbounded filters | Inventory page size capped at 100; EDA ≤6 variables / 5,000 sample rows; audit export limit 1,000–5,000; login unbounded (F-014) |
| Dependencies | pip-audit: 18 advisories in 4 packages (starlette 0.36.3, python-multipart 0.0.9, lightgbm 4.5.0, pytest); npm audit: 12 (10 high, incl. react-router runtime) (F-024). `requirements.txt` is unresolvable (F-025) |
| Bandit | 325 results: 1 HIGH (SHA-1 used for a display id, not security), 8 MEDIUM/high-confidence (urlopen in scripts and the LLM endpoint; xml parse in a gate script), rest LOW/B608 |

---

## 5. Formal ML leakage certification (Phase 5)

Full matrix: `docs/ASP_MODEL_STUDIO_FABLE51_LEAKAGE_CERTIFICATION.csv`. Summary:

- **Target leakage: PASS.** `outcome` is not a catalog member (feature detail → 404, EDA variable → `EDA_VARIABLE_UNKNOWN`, feature-set draft → `FEATURE_SET_UNKNOWN_FEATURE`); prior fits read `targetColumnsRead=[]` (the reconstructed fit frame contains no target column); imputation/encoding/class weights/RFE all fit on training rows only (static review of `_evaluate_candidate`, `_preprocessor`, `_fold_local_recursive_selection`, `_class_policy`).
- **Temporal leakage: PASS.** History cutoff `source.gameDate < target.gameDate` (same-date excluded) is encoded in the Gold/companion manifests and enforced in the V2 latest-state selection; same-day conflicting states fail closed (`PRIOR_V2_POINT_IN_TIME_STATE_CONFLICT`); appending future-season rows to a fit frame is refused (`PRIOR_V2_FIT_DATE_INVALID`); mutating validation-window sufficient statistics leaves the fold-1 fitted checksum unchanged.
- **Fold leakage: PASS.** Numeric medians, binary modes, one-hot levels, class frequencies, RFE rankings and interaction parent medians are fitted inside each chronological training fold; receipts record `validationRowsUsedForParameters=0`. Outlier treatment is `RETAIN` in both the adopted policy and the executed pipeline (no transform).
- **Split integrity: PASS.** Independent recomputation over the Gold development rows for all four split contracts (two authoritative, two synthetic): games never span dates, no game or date appears in both train and validation, training strictly precedes validation, 501,590 rows validated exactly once, 182,072 warm-up rows never validated (2023 training-only by contract), no fold touches OOT, design checksums recompute exactly, regeneration is deterministic; random/stratified/SMOTE designs are refused.
- **Search leakage: PASS.** OOF-only metrics; `finalOot`/`holdout`/`globalMatrix`/`promote`/`champion`/`calibrateOnOot`/`randomSplit`/`provider` plan options are forbidden; content-addressed receipts never overwrite; failed/partial/cancelled jobs remain visible; `autoPromoted=false` everywhere.
- **Evaluation/refinement: PASS with held-closed analyses.** Finalist selection and every downstream decision require an explicit POST; two full page-load cycles created 0 runs/policies/feature sets/splits/specs. SHAP is not installed and permutation/sensitivity analyses require a reloadable artifact, so they are `IMPLEMENTED_HELD_CLOSED`.
- **Calibration: PASS (no calibration fit exists).** Decisions are `RETAIN_RAW`/`DEFER` only; class-wise reliability diagnostics are computed from OOF.
- **Simulation: PASS (held closed).** Prohibited fields (`actual_*`, `betting_odds`, `market_odds`) are rejected from the scoring contract; seed/draws/transition-sampler hash are persisted; no scoring job can be created without a confirmed lineup/starter authority, which does not exist.
- **Final-OOT attack paths: ALL FAIL CLOSED.** EDA/treatment filters into 2026-08-14..27 → `FINAL_OOT_FILTER_PROHIBITED`; manual fold ending in OOT → `SPLIT_MANUAL_BOUNDARY_NOT_REPRESENTED`; plan `finalOot` → 422; cockpit 2025 preview → 410; forecast contract overlapping OOT → 422; companion OOT partition is key-only with NULL payload. OOT counters before and after the audit: `holdout_exposures` 0 → 0, `sports_dataset_query_audit` 0 → 0 on the primary; every receipt carries `finalOotTargetAccessed=false`.

---

## 6. Wave 2 science verification (Phase 6)

Independent reproduction (`scratchpad wave2_repro.py`, `wave2_final_replay.py`; disposable outputs only):

| Check | Result |
| --- | --- |
| Ten V2 bindings / eleven V1 / three retired / no raw sufficient-statistic field selectable | Confirmed via the compiled specification and feature inventory on `asp-mtlozhdx` (raw fields absent from the candidate catalog; `pitcher_era9`, `batter_obp`, `batter_last100_contact_rate` INACTIVE) |
| Model-candidate vs audit-only outputs | Transform emits `*__prior_v2__posterior_mean/log1p_effective_n/posterior_reliability/posterior_std` (candidate) separately from `effective_n/prior_strength/posterior_variance/history_state/…` (audit) |
| Fitting population = latest valid player state at or before the training cutoff | Reproduced independently (own implementation): state counts 985 / 847 / 1,134 / 1,332 / 1,348 / 1,348 / 1,134 match the artifact for all seven families |
| Beta-Binomial, Dirichlet-Multinomial, Gamma-Poisson, Normal-Normal hyperparameters | **Max relative difference 0.0** for every family (independent method-of-moments implementation vs artifact) |
| Posterior means, reliability, variance, simplex sums | Independent posteriors: simplex max error ≤ 4.4e-16; batting AVG/SLG medians, WHIP median, velocity posterior range, reliabilities consistent with the diagnostics |
| Velocity precision | `sum`/`sumsq` are float64 in the companion; no clipping (posterior range 51.35–101.83) |
| Zero evidence → reliability zero; source failure / computation failure / sparse / cold distinct | Confirmed in `_family_evidence` states (`TRUE_COLD_START`, `TRUE_NO_OPPORTUNITY`, `SPARSE_HISTORY`, `ESTABLISHED_HISTORY`, `COMPUTATION_FAILURE`, `SOURCE_UNAVAILABLE`) |
| Deterministic fitted checksums | **Exact**: final-development `5ae0f9f5…` (parameters identical), folds 1–5 fitted checksums all identical, membership checksum `252b0b8a…`, bound fold-contract checksum `cd720585…` |
| Future-season rows do not alter fitted artifacts | Refused outright (fail closed) rather than silently ignored |
| Validation values cannot alter training priors | Fold-1 checksum unchanged after mutating validation-window statistics |
| Final OOT key-only | 14,067 rows, `datasetRole=FINAL_OOT`, `materialization_status=UNMATERIALIZED`, every payload column NULL |
| Content addressing of the V2 store | 39/39 manifests hash to their directory names |

**Caveat (F-002):** all of the above was possible only because the V2 store was copied from `.tmp/asp-player-prior-wave2/.runtime`; the primary runtime root does not contain it.

---

## 7. Artifact, registry, and audit integrity (Phase 7)

Matrix: `docs/ASP_MODEL_STUDIO_FABLE51_ARTIFACT_TAMPER_MATRIX.csv`. Executable-artifact bundles are content-addressed with manifest-last atomic publication; **18/18 tamper cases (bytes, manifest fields, feature/target order, project/user identity, environment, path redirect, member SHA rewrite, extra file, deleted member, directory substitution, traversal) are rejected before deserialization**. Run receipts drop out of the ledger when mutated or renamed; Gold manifest/pointer tamper fails every Stage 3 entry point; a real Gold partition byte-flip is rejected by a cold process but served by the in-process cache (F-010); DB triggers make policy/spec/feature-set/split versions immutable while run records, project ownership and audit rows remain mutable (F-021). The summary endpoint for the executable artifact does not re-verify on read (F-009). No manifest can be redirected to an untrusted path without breaking its own address.

---

## 8. End-to-end MLB workflow certification (Phase 8)

Matrix: `docs/ASP_MODEL_STUDIO_FABLE51_WORKFLOW_CERTIFICATION.csv`. Discovered manifest: nine-stage program with a fourteen-step development cockpit (`MLB_GAME_FORECAST_WORKFLOW_V1`, availability ENABLED). Walked on synthetic projects (user A) and the authoritative copies (admin):

- Certified: project creation, forecast objective (season-role and custom-date validation), evidence binding, Stage 2 review, Stage 3 EDA, outliers, missing values, specification draft (adoption held closed), feature engineering (with F-013), split & balance (with quality gates), page-load idempotence, workflow-state persistence, refresh/back/forward/deep links, wrong-user/missing-project/stale-auth states, CAS on drafts, restart idempotence of migrations.
- **Single-project only:** Model Laboratory, tuning, queue, execution progress, candidate evaluation, finalists, refinement, calibration decisions, simulation impact, champion/challenger, registry, executable artifact, prospective scoring (F-003). These were exercised on the isolated copy of `asp-mtddc6pw` (synthetic fits reported in the capacity report); no authoritative project was fitted.
- Held closed: specification adoption (F-008), SHAP/permutation/sensitivity, game scoring (no lineup authority).

---

## 9. Treatment-blocker integrity (Phase 9)

| Requirement | Result |
| --- | --- |
| `canAdopt=false`; exact blockers | PASS: 3 blocker classes (doubleheader schedule PIT, embedded holiday calendar, 14 unapproved rivalry fields = 16 fields) |
| Adoption UI disabled | PASS (frontend gates on `canAdopt`; `TreatmentStudioShell`) |
| Direct API adoption fails closed | PASS: exact V8 ids → `TREATMENT_SPEC_ADOPTION_BLOCKED`; wrong/stale ids → `DRAFT_REQUIRED`/`DRAFT_NOT_CURRENT` |
| Contradictory booleans (`canAdopt:true`, `blockers:[]`, `force`) | PASS: ignored |
| Semantic fields not generically imputed | PASS on projects with a draft (INACTIVE / HELD_CLOSED); **FAIL on a fresh project without a draft** (registered into a feature set; F-013) |
| Rivalry fields inactive/nonselectable | PASS (draft → `FEATURE_SET_INACTIVE_FEATURE` before and after the draft) |
| Zero-variance rivalry-missing flags excluded | PASS with draft; **FAIL without draft** (F-013) |
| Schedule features remain available | PASS (`context_inning`, `context_top_bottom`, `game_month` ELIGIBLE) |
| Browser payload cannot deceive backend | PASS (tampered draft → `TREATMENT_SPEC_CHECKSUM_MISMATCH`) |
| Stale DRAFT cannot authorize | PASS (V6 draft → `DRAFT_NOT_CURRENT`) |
| Another project's adopted policy | Draft accepted, registration should reject as stale; **on a fresh project both draft and registration succeeded** (F-013) |
| Admin bypass creates a new governed version + audit | PASS (admin drafts only through the same checksum-gated path) |

No blocker was resolved or approved.

---

## 10. NFL and multi-sport boundaries (Phase 10)

| Workflow / area | Classification | Evidence |
| --- | --- | --- |
| MLB game forecast workflow | OPERATIONAL through Split & Balance for any project; OPERATIONAL end-to-end only for `asp-mtddc6pw` | this report |
| NFL game forecast workflow | IMPLEMENTED_RESEARCH_ONLY (`RESEARCH_ONLY`, `NOT_EXECUTABLE`, `NO_WORKSPACE_DATASET_ACTIVATION`, project creation not selectable; `/workflows/nfl` renders the readiness page; scripts `run_nfl_m1_benchmark.py`, `run_nfl_2026_prospective_shadow.py`; 3 NFL foundation registrations with rights rows) | `/api/sports/manifests`, registry |
| NFL M1 benchmark / prospective shadow | IMPLEMENTED_RESEARCH_ONLY (script-driven; `joblib.load` gated by frozen disposition) | `server/sports_nfl_m1` |
| NBA / WNBA / UFC | PLANNED_NOT_IMPLEMENTED (manifests with 3 stages, `NOT_SELECTABLE`, `NO_MODELING`) | registry |
| Cross-sport collisions | None found: registrations carry `sport`/`league` and distinct id prefixes; no NFL API routes; no shared jobs/artifacts/champion tables across sports; the cockpit research object is MLB-only | DB, router inventory |
| False readiness claims | None in the registry/manifests; the UI states research-only honestly | browser run |

---

## 11. Job concurrency and multi-user scale (Phase 11)

Measurements are in `docs/ASP_MODEL_STUDIO_FABLE51_CAPACITY_REPORT.md` and `_CAPACITY_RESULTS.json`; everything ran on the isolated stack (8191) against disposable copies, with synthetic fits only on the copy of `asp-mtddc6pw`.

| Measure | Result |
| --- | --- |
| 100 registered synthetic users | created and logged in (0 functional errors); login p50 4.5 s / p95 6.5 s at 25 threads (PBKDF2 260k, ~5 logins/s); security-DB lock errors during bulk creation (F-028) |
| 25 concurrent interactive users | 104 requests in 365 s (0.3 req/s), p50 9.7 s, p95 300 s, 13 timeouts (`outlier_summary`), `list_projects` p50 53 s, backend 2.8 cores and 7.0 GB RSS |
| duplicate submission | 4 simultaneous identical submissions → one job (4 × 202, one job id); distinct plan while active → 409 `MODEL_DEVELOPMENT_JOB_ALREADY_ACTIVE` |
| interactive latency during one job (idle host) | `list_projects` 6.2 s → 8.1 s, health flat, job status 74 ms |
| cancellation | configuration-granular: `cancel-unstarted` at 8/10 fits returned CANCEL_REQUESTED but both configurations had started, 0 fits cancelled, job ran to COMPLETE 95 s later; no API aborts a running configuration |
| coordinator kill mid-job | backend back in 9 s; orphan reconciled to INTERRUPTED (`MODEL_DEVELOPMENT_COORDINATOR_INTERRUPTED`), completed receipt retained, in-flight fit lost, no resume; new job accepted and COMPLETE 5.5 s after restart |
| safe limits (this host, current build) | 100 registered; **2** concurrent interactive (3–5 degraded, 25 unacceptable); **1** heavy job (single in-process slot, one active job per project); envelope = 1 job + 2 scientists |

Architectural facts independent of the numbers: one API process, one in-process job slot per job family, one active job per project, no queue, no quotas, no worker isolation, no resume (F-030); `GET /projects` resolves per-project state for every visible project (~55 ms each) and the EDA/outlier profiles load the full 683,662-row Gold frame per project into process caches, which is the mechanism behind the 25-user collapse. The mandate's 100 / 25 / 4 target is a Tier 2 architecture target, not reachable by tuning the current build.

---

## 12. Database, backup, recovery (Phase 12)

Verified on disposable copies: online backup via the SQLite backup API (0.44 s) reproduces every table count and six logical digests; migrations are idempotent on the restored copy (0 newly applied); a fresh database built from `schema.sql` + 38 migrations has exactly the 312 schema objects of the live file; `integrity_check` ok; WAL preserved. **A naive file copy of the WAL database lost pending writes** (probe table absent) while the backup API captured them; the application never runs `integrity_check` at startup (corruption in a free page went unnoticed by `health()`). No scheduled backup exists (F-022). PostgreSQL requirements: see the architecture plan.

---

## 13. Production architecture (Phase 13)

`docs/ASP_MODEL_STUDIO_FABLE51_PRODUCTION_ARCHITECTURE_PLAN.md`. Recommended tier today: **Tier 0**, moving to Tier 1 after section A of the repair plan.

## 14. Source rights (Phase 14)

`docs/ASP_MODEL_STUDIO_FABLE51_DATA_RIGHTS_MATRIX.csv`. The effective intersection is `GOVERNED_LOCAL_RESEARCH_ONLY` with Statcast commercial rights `UNCLEAR_REQUIRES_REVIEW`, Lahman CC BY-SA share-alike unassessed, Chadwick/Retrosheet attribution obligations, and no rights record for the MLB Stats API. This blocks external beta users, paid subscriptions, public hosted access, exported models/features/training data, public feature displays, and customer-downloadable evidence until provider review and counsel outcomes are recorded. No legal conclusion is given.

## 15. Tests, scanners, build (Phase 15)

`docs/ASP_MODEL_STUDIO_FABLE51_TEST_SCANNER_RECEIPT.json`. Backend: 2,682 passed / 183 failed / 57 errors / 300 skipped (44m30s) at the pristine base; failures are dominated by legacy ATLAS suites (analysis-partition/scoring/model-registry fixtures: MISSING_LOCAL_DATA or PRE_EXISTING_REPRODUCIBLE), Windows temp-ACL PermissionErrors (ENVIRONMENT_DEPENDENT), and Codex red-gate suites that require explicit disposable-root env (INTENTIONALLY_HELD_CLOSED); 8 failures in sports suites (6 held-closed contract gates, `split_atomicity_test`, `sports_cockpit_phase7d4_browser_test` — both pre-existing/environmental). Frontend: 110 test files pass / 53 fail (34 stale source-text contracts, 14 missing `.tmp` fixtures, 1 ENOENT) at the pristine base. TypeScript `tsc -b`: pass. `npm run build:modeling`: pass (2.8 MB main chunk warning). Migration verification: pass. Dependency audits and scanners: section 4. `git diff --check`: clean (deliverables only). No failure was INTRODUCED_BY_AUDIT.

## 16. Browser acceptance (Phase 16)

`docs/ASP_MODEL_STUDIO_FABLE51_BROWSER_ACCEPTANCE.json` (67 checks) and 65 screenshots under `docs/audit-evidence/fable51-screenshots/`. Isolated frontend (5291, Vite dev server proxying to the isolated backend 8191); Playwright 1.61.1 chromium; login performed through the API with cookie injection (no password typed into a page); each page settled for 6 s after `load`, so the ~6.5 s per-page figures are the harness wait, not render time.

| Check | Result |
| --- | --- |
| 14 pages × 4 viewports (1920×1080, 1440×900, 1024×768, 390×844) as admin on `asp-mtlozhdx` | 56/56 rendered (HTTP 200), **0 horizontal overflow**, **0 API 5xx**, 0 page errors |
| pages | dashboard, open projects, project overview, MLB workflow stage 1/2/3 and Stage 3 steps 4/6/8/9, data sources & rights, admin, account, NFL workflow |
| unauthenticated deep link to Stage 3 (4 viewports) and `/login` | redirected to `/login?returnTo=…` with the sign-in form; API calls answered 401 |
| foreign user (no ACL) on `asp-mtlozhdx` workflow / overview | workflow page shows "You do not have permission to perform this action on this project."; overview renders only the shell; all project APIs 403; no project data in the DOM |
| missing project id | page stays on "Loading secure sports modeling workspace…" (no not-found state after 6 s) — cosmetic, consistent with F-022 |
| revoked session | `/dashboard` redirected to `/login?returnTo=%2Fdashboard`; APIs 401 |
| session cookie | `asp_model_studio_session`, HttpOnly, SameSite=Lax, `Secure=false` on the http dev origin (hosted mode sets Secure) |
| history | back/forward restore the previous workflow URL and the login redirect correctly; the harness could not locate a user-menu logout control, so logout was verified through the API session-revocation tests instead |
| console | `/account` logs a React duplicate-key warning at every viewport; `/workflows/nfl` logs two 404 resource loads (NFL endpoints not implemented, page states research-only) |
| writes on page load | Stage 2 and Stage 3 pages issue 1–3 `PUT /api/projects/asp-mtlozhdx` autosave writes on open, before any user action (audit-log and write amplification; not a security defect) |
| focus / keyboard | visible focus outline on the first focusable control on every page checked |

No page failed to render, no server error surfaced in the UI, and the authorization outcomes in the browser match the API matrix (section 3).

---

## 17. Final report (Phase 24 items 1–66)

1. Access classification: full read; write limited to audit branch/worktree, scratch, disposable copies.
2. Repository root: `C:\Users\james\asp-model-studio`.
3. Audited base: `codex/mlb-player-prior-wave2` @ `bff19a8a657bc96dea0469fad481acdcb4234386`.
4. Why: sole tip containing all prior branches (linear chain; only a docs-only Claude audit branch is outside its ancestry).
5. Final audit branch / HEAD: `claude/fable51-model-studio-security-ml-integrity-audit`; deliverables commit `df5c14fd32f986560bb25001a20c1d2a231c3a58`; final HEAD is the receipt commit recorded in section 18 and `ASP_MODEL_STUDIO_FABLE51_COMMIT_RECEIPT.json`.
6. Main HEAD: `924db29511f93909f9d785855bfa056775443690`.
7. Worktree: `C:\Users\james\worktrees\asp-model-studio-fable51-audit`.
8. Git status before: clean (all worktrees); after: clean except the committed `docs/` deliverables on the audit branch; primary checkout untouched (`33cd85f`, clean).
9. Preserved untracked files: none existed; nothing deleted.
10. Files changed: only new files under `docs/` on the audit branch (list in the commit).
11. Commits created: two documentation-only commits on the audit branch — the deliverables commit and a receipt commit that records its SHA (section 18).
12. Pushes: none.
13. Database/migration state: SQLite WAL, 114 tables, 38 migrations, integrity ok, no backups (section 1, 12).
14. Runtime services: primary 5274/8101 not running; audit used 8191/5291 isolated processes, stopped at the end.
15. Threat model: section 2 / threat-model document.
16–19. Findings: **P0 = 1, P1 = 3, P2 = 15, P3 = 13** (`FINDINGS.json`).
20. Authentication: PASS with P2/P3 hardening items.
21. Authorization: FAIL (F-001 P0, F-004, F-006).
22. Cross-user isolation: FAIL via F-001; otherwise PASS.
23. Cross-project isolation: FAIL via F-001; otherwise PASS on 60+ routes.
24. Administrator routes: PASS.
25. Application security: PASS with P2 dependency and CORS items.
26. Target leakage: PASS. 27. Temporal: PASS. 28. Fold: PASS. 29. Search/feature-selection: PASS. 30. Calibration: PASS (no fit). 31. Simulation: PASS (held closed). 32. Final-OOT attack paths: all closed.
33. Wave 2 reproduction: EXACT (all seven families, all six fitted authorities).
34. Artifact tamper: loader 18/18 rejected; read-path and warm-cache gaps (F-009, F-010); DB ledgers mutable (F-021).
35. Complete MLB workflow: certified through Split & Balance for any project; steps 9–14 single-project (F-003); adoption held closed (F-008).
36. Treatment blockers: enforced except on projects without a specification draft (F-013).
37. NFL/multi-sport: research-only/planned, honestly represented; no cross-sport collisions.
38. Job submission integrity: identical concurrent submissions coalesce to one job; a distinct plan while a job is active is rejected (409); plans verify `expectedPlanId`/checksum. 39. Duplicate prevention: PASS. 40. Cancellation: configuration-granular only; a started configuration cannot be aborted through the API (time-to-abort unbounded). 41. Coordinator restart: automatic orphan reconciliation to INTERRUPTED with completed receipts retained; no resume. 42. Job isolation: one in-process slot, no worker isolation, no quotas, no queue (F-030). 43. 100 registered users: created and usable; login ~5/s; security-DB lock errors during bulk writes (F-028). 44. 25 concurrent interactive users: FAIL — 0.3 req/s, p50 9.7 s, p95 300 s, 13 timeouts, 7.0 GB RSS. 45. 4 simultaneous heavy jobs: impossible on the current build (single slot); one running job leaves the API responsive.
46. Safe registered users: 100 on the current build (1 today until F-001/F-005 are fixed, 10 at Tier 1). 47. Safe concurrent interactive users: 2 (3–5 degraded; 25 unacceptable). 48. Safe simultaneous heavy jobs: 1 (envelope: 1 job + 2 scientists on distinct projects).
49. Backup/restore: restore verified; no scheduled backup; naive copy unsafe.
50. Recommended deployment tier: Tier 0 now; Tier 1 after repair-plan section A.
51. Required topology: architecture plan Tier 2 for controlled beta.
52. Source-right blockers: GOVERNED_LOCAL_RESEARCH_ONLY; Statcast/Lahman review; MLB Stats API unregistered.
53. Tests/scanners: section 15.
54. Browser acceptance: 56/56 admin page checks across four viewports with 0 overflow and 0 API 5xx; anonymous/foreign/missing/revoked scenarios behave correctly; cosmetic issues only (section 16).
55. Protected counts/digests before/after: `PROTECTED_RECEIPT.json` — 118 keys compared, verdict IDENTICAL_EXCEPT_BENIGN_SIDECARS (only the persistence `-wal` sidecar size differs, 0 bytes → absent); every table digest, row count, manifest and partition SHA, object count and pointer unchanged.
56. Final-OOT access count before/after: 0 / 0 (`OOT_ACCESS_RECEIPT.json`).
57. Zero authoritative predictive fits: confirmed (synthetic fits only on the isolated copy; deleted with the scratch root).
58. Zero policy adoptions on the authoritative DB: confirmed (adoptions only on synthetic projects in the disposable copy).
59. Zero feature-set registrations on the authoritative DB: confirmed (same).
60. Zero champion mutations: confirmed.
61. Zero provider calls: confirmed (no outbound requests; env endpoints unset).
62. Repairs performed: none.
63. Top ten remediation items: repair plan A1–A4, B1–B6.
64. Rejected busy work: repair plan section G.
65. Exact next action: fix F-001 (grant bootstrap) and republish the V2 store into the primary runtime root (F-002) before the `.tmp/asp-player-prior-wave2` worktree is pruned; then generalize the Model Laboratory (F-003).
66. Verdict: `ASP_MODEL_STUDIO_NOT_READY_TENANT_ISOLATION_BLOCKERS` (+ WORKFLOW, SCALE, BACKUP_RESTORE, DATA_RIGHTS); private research ready for a single operator.

---

## 18. Commit receipt

| Item | Value |
| --- | --- |
| audit branch | `claude/fable51-model-studio-security-ml-integrity-audit` (worktree `C:\Users\james\worktrees\asp-model-studio-fable51-audit`) |
| base | `bff19a8a657bc96dea0469fad481acdcb4234386` (`codex/mlb-player-prior-wave2`) |
| deliverables commit | `df5c14fd32f986560bb25001a20c1d2a231c3a58` — 81 files, 3,804 insertions, all under `docs/` (16 deliverables + 65 screenshots) |
| receipt commit | the commit that adds this section and `ASP_MODEL_STUDIO_FABLE51_COMMIT_RECEIPT.json`; its SHA is the final HEAD reported in the closing message |
| pushes / merges | none; main remains `924db29511f93909f9d785855bfa056775443690`; primary checkout remains `codex/mlb-governed-prior-engine-v1` @ `33cd85f`, clean |
| application source changed | none (`git diff --stat bff19a8..HEAD -- . ':!docs'` is empty) |

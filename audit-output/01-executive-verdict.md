# 01 — Executive Verdict

**Audit date:** 2026-07-26 · **Repository:** `master` @ `4e21fdd` · **Scale:** ~142,000 LOC, 415 API operations, 60 database tables
**Method:** seven read-only lanes, plus independent main-agent verification — live two-user authorization probes against the running backend, read-only database inspection, and one live performance benchmark. **No production source, Git history, database, artifact, or application state was modified.**

---

## Is ATLAS on the right path?

**Yes — the architecture is directionally sound, and the product thesis is the right one. It is not yet safe for anyone but its author.**

Those two statements are both true and neither should be softened. This is not a prototype pretending to be a platform; it is a genuinely substantial system with correct instincts, carrying a specific and nameable class of debt.

The differentiating idea — that a model's dataset version, split, features, training run, evaluation, scoring, evidence, documentation, validation, and monitoring should be **one connected governed chain** rather than a folder of notebooks and a Word document — is the right bet for regulated financial institutions, and large parts of it are genuinely built.

But the audit found the same pattern four separate times, and it is the defining characteristic of the codebase today:

> **The correct design is built, and then not wired into the path users actually take.**

- `analysis_scope.py` is an excellent governed-scope contract. Its enforcement function has **exactly one call site**; 185 of 203 live evidence items carry no scope at all.
- The `mdd_*` schema is a genuine governed-projection design with per-block provenance. It has **zero readers and zero writers**.
- `GET /model-versions/{id}/documentation-bundle` is a correct evidence projection. Its frontend client is **exported and never called**.
- `Deadline` — the query-timeout primitive — is defined and **never instantiated**.

And the same shape at the data layer: `models` = 0 rows, `model_versions` = 0 rows, `artifacts/model_registry/` does not exist — against 127 projects and 15 scoring runs. **The Durable Model Registry, the spine of the entire governance thesis, has never persisted a single model**, because its only write path swallows every exception and its caller still returns `{"ok": true}`.

That is the honest summary: **ATLAS has built most of the right things and connected too few of them.** The remediation is overwhelmingly *connection and generalization*, not invention — which is why the verdict is optimistic despite the finding count.

---

## Top 10 strengths

1. **The governed-scope contract is real and well designed.** `analysis_scope.py` derives scope server-side, treats eligibility as an output never an input, and puts scope identity in cache keys. Where it is enforced, it works.
2. **The modeling core is genuinely isolated — verified live.** 19 of 19 core authorization probes behaved correctly: datasets 403 for non-owners, project and dataset lists correctly filtered, admin 403, audit 403, no-credential 401. `DATASTORE`/`RESULTS` are correctly keyed by `(user_id, project_id)`; training-job ownership is enforced.
3. **`assert_api_routes_authenticated` is an excellent control.** It walks every route's dependency tree at startup and raises if authentication is missing. It needs extending to authorization — but the mechanism is right and rare.
4. **The honest-failure discipline is real.** The 409 `full_artifact_missing` path never substitutes a sample for a full artifact, and the frontend renders it with an actionable recovery list. `governedProfile.ts` enforces a documented **no-fallback invariant**.
5. **Path traversal and deserialization are well defended.** Segment regex plus `relative_to()` containment everywhere; **no `FileResponse`, no archive extraction, and zero hits for `shell=True`, `eval(`, `pickle.load`, `yaml.load`** across the server.
6. **Password hashing, sessions, and lockout are correct.** PBKDF2-HMAC-SHA256 at 260k iterations, per-user salt, constant-time compare, revocable sessions, and a lockout whose transaction-ordering bug was already handled.
7. **SQL is parameter-bound** with a strict identifier allowlist that *raises* on mismatch, and DuckDB extension autoload disabled.
8. **The cache is excellent where it applies** — a **measured 215× speedup** (19.39 s → 0.09 s), with identity keys that include user, project, dataset version, and target.
9. **The scoring-run flow is the best-layered path in the codebase** — single service entry point, re-authorization, idempotency on registration, and an explicit in-code disclosure that execution is synchronous. It is the reference pattern.
10. **`dataAcquisitionStatus.ts` and the two statistical reference tests are genuinely high-quality work** — a tri-dimensional status model with tones locked to states, and Wilson intervals recomputed from an independently expressed formula *"so a regression cannot pass by matching itself."*

---

## Top 10 risks

1. **Cross-user IDOR across ~12 resource families — CONFIRMED LIVE.** A `data_scientist` owning one project and zero datasets read 227 evidence items spanning **112 projects**, the full content of a foreign evidence record, five foreign notebooks including cell source, and 27 foreign projects. No bypass required.
2. **Two independent, default-on paths to full admin.** Public registration accepts a caller-supplied `role` including `admin`; and `X-ATLAS-USER-ID` asserts any identity with **no password**, enabled by default, unsuppressed by `ATLAS_AUTH_ENABLED=true`.
3. **The model registry has never persisted a model.** 0 rows, artifact root absent, all 15 scoring runs unlinked, failure silently swallowed. "Save Final Model" reports success and persists nothing.
4. **Checkpoint saves are failing right now, invisibly.** Four `TypeError: Object of type int64 is not JSON serializable` in one session, a 923 MB file at 8.8× its own critical threshold, and a fire-and-forget caller that returns `True` regardless.
5. **No invalidation exists.** Nothing marks documentation, validation, monitoring, or evidence stale when a dataset or model version changes. ATLAS cannot detect material change, therefore cannot trigger re-review, therefore cannot demonstrate the ongoing validity of any approval.
6. **Segregation of duties is bypassable in one HTTP call**, and approvals name a project and a date — not a model version.
7. **The platform stops serving all traffic somewhere between 10 and 40 concurrent analytical users** — a global lock held for ~19 s on sync handlers occupying a 40-slot shared threadpool, with the concurrency governor never called on that path.
8. **No CI, and the best tests never run.** Zero CI configuration; the documented gate runs **1 of 66** scripts; and **16 test files — every two-user authorization test, segregation of duties, lockout, checkpoint-GC — are orphaned.**
9. **Nine facts have two or more sources of truth**, with measured divergence: evidence 227/203/189, audit 9,136/5,466, users 200/245, links 10 of 44. Plus **312 dangling foreign keys** and no integrity check anywhere.
10. **The MDD is a textarea.** A real 26-section document contains zero `modelVersionId`, `datasetVersionId`, or `evidenceId`; the champion model is derived by **substring-matching a JSON dump**; and the "improve draft" button pastes boilerplate into an editable field — literally the copy-and-paste MDD the product thesis forbids.

---

## Domain scorecard (0–5)

| Domain | Score | Current evidence | Missing evidence | Next threshold | Confidence |
| --- | --- | --- | --- | --- | --- |
| Architecture | **3.5** | Clean domain decomposition; startup auth assertion; good service/repository pattern where applied | Three inconsistent persistence styles; 9 duplicated sources of truth | Reconcile each fact to one store | High |
| Security | **1.0** | Strong hashing, sessions, path-traversal defense, parameter-bound SQL | 4 P0s including two default-on admin paths | Close SEC-P0-1/2/4 | High (verified live) |
| Multi-user isolation | **2.0** | Modeling core verified correct on 19 of 19 probes | ~12 studio families with no resource authorization | Extend the startup assertion to authorization | High (verified live) |
| Data scalability | **2.0** | 170k×31 works; 215× cache speedup; bounded payloads | Parquet path dead; N+1 present; no timeout; no spill | Materialize Parquet; fix the N+1 | High |
| User scalability | **1.0** | Single user works well | **Concurrency never measured**; global lock; 40-slot threadpool | Concurrency ramp with a health probe | Medium (projection) |
| Job orchestration | **2.0** | Job ownership enforced; honest no-false-resume on restart | Threads in-process; no queue; no idempotency; cancellation not real | Idempotency + a real queue | High |
| Persistence | **1.5** | WAL + busy_timeout on the app DB; checkpoint corruption fails safe | 312 dangling FKs; lock-free registries; non-atomic migrations | Integrity check at startup; registry locking | High (verified live) |
| Reproducibility | **1.0** | Deterministic in practice (`random_state=42`) | Seed recorded but ignored; no environment, target mapping, or split indices | Capture the full envelope | High |
| Model lifecycle | **1.0** | Correct schema exists and is well designed | **0 model versions ever persisted** | Make registration transactional and loud | High (verified live) |
| Evidence & lineage | **1.5** | Rich evidence model; scope contract designed | Two stores, mutable, hard-deletable, unauthorized, 0/203 with a model version | One append-only authorized store | High (verified live) |
| MDD | **1.0** | Validator-aligned template and section vocabulary | Free text; dead projection API; three parallel paths | Activate `mdd_*`; wire the bundle | High |
| Validation | **1.5** | Excellent schema: challenge/response/finding/approval-with-conditions | SoD bypassable via PATCH; approvals unbound to a version | State machine + model pin | High |
| Monitoring | **1.0** | Complete 8-entity model; real escalation path | No model binding; hand-typed values; no scheduler; no authorization | Bind to a version; derive from PSI/VSI | High |
| UX | **2.5** | Data Acquisition is genuinely excellent; honest 409 handling | Cross-project leaks; navigation-driven completion; fabricated Step 13 data | Generalize `dataAcquisitionStatus` to all steps | High (screenshot-proven) |
| Accessibility | **1.5** | `prefers-reduced-motion` correct; newer charts have text fallbacks | No skip link, no focus management, colour-only status, 2.55:1 contrast | axe-core in CI | High |
| Testing | **1.5** | Genuinely excellent Python behavioral and statistical reference tests | 37–57% source-text; 16 best files orphaned; 4 domains at zero | Aggregate target + wiring guard | High (verified) |
| Deployment | **1.0** | Lockfile committed | Two conflicting requirements files; 51% not installed; engine undeclared | One lock; clean-install CI job | High (verified) |
| Observability | **0.5** | `audit_event` compliance trail exists | 2 logger calls total; no timestamps, no correlation IDs, no metrics | Structured logging with request IDs | High |
| Backup & DR | **0.5** | Checkpoint corruption fails safe | No backup, no restore, no RPO/RTO, no down-migrations | A tested backup/restore drill | High |
| **Commercial pilot readiness** | **1.0** | Compelling demo; real governed analytics | 4 security P0s reachable by ordinary users | Close SEC-P0-1/2/3/4 | High |
| **Bank production readiness** | **0.5** | Right conceptual model | Lifecycle unpopulated; no invalidation; no DR; no observability | Everything above plus MDD and invalidation | High |

**No single overall number is offered** — the spread from 0.5 to 3.5 is the finding. ATLAS is architecturally further along than it is operationally safe, and the gap between those two is the whole story.

---

## Three target architectures

### A. Local developer edition — *supportable today, with one caveat*

**Can remain:** SQLite, local filesystem artifacts, in-process execution, the process-local cache, synchronous jobs, the browser-first project registry.

**Safe envelope:** one trusted user on loopback · datasets to ~1M rows × ~100 columns · ~20 s cold profiling, sub-second warm · projects in the low hundreds.

**The caveat:** even here, the checkpoint failure means in-progress work is silently unrecoverable. Fix that and this tier is genuinely fine. None of the security P0s has a second party to harm with a single trusted user — but the tier must be **explicitly labelled single-user**, because nothing in the product currently says so.

### B. Single-institution controlled pilot — *blocked, but reachable in a quarter*

**Minimum additions, each mapped to an observed limitation:**

| Requirement | Because |
| --- | --- |
| Resource authorization on all ~190 endpoints + startup assertion + CI-gated two-user suite | SEC-P0-4, confirmed live |
| Registration cannot grant roles; dev header off by default and loopback-bound | SEC-P0-1, SEC-P0-2 |
| Code execution containerized (dropped capabilities, read-only rootfs, no network, non-root, rlimits) **or disabled** | SEC-P0-3 |
| SSO / enterprise identity replacing the local user table | header-asserted identity |
| PostgreSQL replacing both SQLite files | 312 dangling FKs; `journal_mode=delete` on the security DB; single-writer contention |
| Object storage for the artifact tree | 332 MB local and growing; no backup path |
| A real job queue with separate workers | in-process threads; nothing survives restart |
| Shared cache (Redis) | the current cache is process-local, so multi-instance breaks it |
| Backup + tested restore + documented RPO/RTO | none exist |
| Structured logging with correlation IDs | 2 logger calls in the entire server |
| Model registry that actually persists | PJ-P0-2 |
| Committed transaction data removed and history remediated | TO-P1-7 |

**Realistic envelope after these:** 5–25 named users, single tenant, datasets to ~10M rows.

### C. Enterprise production — *a genuinely different data and control plane*

Beyond B: multiple stateless app instances behind a load balancer; queue/worker orchestration with cancellation and restart recovery; **distributed analytical execution behind the connector interface that currently has no engine behind it**; PostgreSQL with read replicas; object storage with lifecycle policies; per-tenant quotas, backpressure, and load shedding (the primitives exist in `resource_governance.py` and are called from one endpoint); secrets/KMS; full observability with SLOs; immutable, hash-chained audit; versioned reproducible environments per model version; blue/green with migration rollback; and DR with a rehearsed RTO.

**And two things that are not infrastructure:** the **lifecycle invalidation service** (nothing marks anything stale today) and **MDD as a true governed projection** (activate the `mdd_*` schema that already exists). Without those two, no amount of infrastructure makes ATLAS a model-risk platform.

---

## What must happen next

1. **Force the lowest role in `register()`** — one line.
2. **Invert the dev-header default** — half a day.
3. **Add an aggregate test target and CI; wire in the 16 orphaned files** — one day, and it makes a large body of existing verification load-bearing.
4. **Fix the checkpoint serializer and surface its failures** — one day, and it stops live silent data loss.

Then the systematic authorization pass, and the model registry.

---

## What should NOT be worked on yet

- The 11,768-line `WorkflowPlaceholderStep.tsx` refactor — real debt, zero user risk.
- Deleting the ~9,300 LOC of dead code — one cleanup pass, not a project.
- Vendor/external model onboarding — a real SR 11-7 gap, but only after the *internal* lifecycle persists a model.
- Distributed analytical execution — the empty connector interface is honest scaffolding.
- New workflows (RL, computer vision, graph analytics) — adding breadth before the core lifecycle is durable compounds the exact problem this audit found.
- The full WCAG remediation programme — add `axe-core` to CI now, defer the rest.

---

## A note on the method being used

**The page-by-page acceptance walkthrough is working and should continue.** It produced `dataAcquisitionStatus.ts`, `analysis_scope.py`, the honest 409, the no-fallback invariant, and the `Number(null)` fix — all of which this audit rates as genuinely good engineering.

**One correction to the method:** every defect class fixed on Data Acquisition was found **still live on four to six other steps** — the duplicate status derivation, the `Number(null)` coercion, the unscoped browser key, the fabricated confidence value. Two of them are still live *on Data Acquisition itself*, in the milestone panel.

**Generalize each fix across all steps before moving to the next page.** The marginal cost is small; the alternative is re-discovering the same defect thirteen more times.

---

## Deliverables

| File | Contents |
| --- | --- |
| [00-audit-manifest.md](audit-output/00-audit-manifest.md) | Snapshot identity, working tree, hardware, restrictions |
| [01-executive-verdict.md](audit-output/01-executive-verdict.md) | This document |
| [02-system-architecture.md](audit-output/02-system-architecture.md) | Component map, request flows, sources of truth, Mermaid diagrams |
| [03-security-and-isolation.md](audit-output/03-security-and-isolation.md) | Threat model, live authorization probes, security findings |
| [04-scalability-and-performance.md](audit-output/04-scalability-and-performance.md) | Measured benchmark, envelopes, capacity model, test harness |
| [05-persistence-jobs-and-recovery.md](audit-output/05-persistence-jobs-and-recovery.md) | Persistence inventory, source-of-truth map, failure matrix |
| [06-model-lifecycle-governance-and-mdd.md](audit-output/06-model-lifecycle-governance-and-mdd.md) | Lineage, reproducibility, evidence, MDD, validation, monitoring |
| [07-frontend-ux-and-accessibility.md](audit-output/07-frontend-ux-and-accessibility.md) | Status integrity, scope leaks, accessibility, performance |
| [08-testing-deployment-and-operations.md](audit-output/08-testing-deployment-and-operations.md) | Test inventory, dependencies, deployment, observability, hygiene |
| [09-findings-register.csv](audit-output/09-findings-register.csv) | **81 findings** (27 P0 · 30 P1 · 18 P2 · 6 P3) with all 18 required columns |
| [10-prioritized-roadmap.md](audit-output/10-prioritized-roadmap.md) | Phased remediation plan |
| [11-validation-harness-plan.md](audit-output/11-validation-harness-plan.md) | Automated suite specification |
| [12-open-questions.md](audit-output/12-open-questions.md) | Everything unverified, and how to settle it |

**Baseline caveat, recorded:** `tests/e2e/data-acquisition-ui-load.spec.ts` remains red in its final predictor-semantics block after the real UI load and reconciliation succeed. Treated throughout as a known localized acceptance item — **not** investigated, **not** fixed, and **not** scored as a P0.

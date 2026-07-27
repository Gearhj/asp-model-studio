# 10 — Prioritized Roadmap

**Principle:** almost every fix below is **connecting or generalizing something that already exists and already works somewhere in this codebase.** Very little needs inventing. Nothing here requires a rebuild.

---

## Immediate P0 containment (this week)

These four change the platform's risk posture more than anything else, and three are small.

| # | Action | Effort | Why first |
| --- | --- | --- | --- |
| 1 | **Force the lowest role in `POST /api/auth/register`**; gate public registration behind a flag defaulting off | **~1 line** | Closes unauthenticated escalation to platform admin (SEC-P0-1) |
| 2 | **Invert the dev-header default** — require affirmative `ATLAS_ENABLE_DEV_USER_HEADER`, default `ATLAS_LOCAL_DEV` to false, bind to loopback, run `enforce_hosted_security_configuration()` unconditionally, strip `available_dev_users` from 401 bodies | ~½ day | Closes password-free impersonation of any user (SEC-P0-2). Today an operator who does both obvious hardening steps is **still** fully exposed |
| 3 | **Add an aggregate test target and a minimal CI workflow; wire in the 16 orphaned test files** | **~1 day** | The best tests in the repo — every two-user authz test, segregation of duties, lockout, checkpoint-GC — **already exist and already pass** and no process runs them (TO-P0-4). Highest value per unit effort in the entire audit |
| 4 | **Fix the checkpoint serializer** — numpy-aware `default=`, per-scope serialization so one bad scope cannot abort the rest, and surface save failure on `/api/persistence/health` | ~1 day | Saves are **failing right now** and no one is told (PJ-P0-1). This is silent data loss in production-shaped runs |

**Also immediate, zero-risk:** `git rm --cached` the two 82.4 MB duplicate transaction-data CSVs and add `server/artifacts/` + `test-results/` to `.gitignore`. Decide separately whether history rewriting is required before any external sharing (TO-P1-7).

---

## Next 30 days

**Authorization — the systematic fix (SEC-P0-4).** Apply `authorize_modeling_scope` as the first statement of every project-scoped route across the 12 studio routers; add service-layer `_get_<resource>_authorized` for id-addressed resources; add per-row filtering to list endpoints. **Then extend `assert_api_routes_authenticated` into `assert_api_routes_authorized`** with a reviewed allowlist — this converts today's false completion signal into a real one and stops the gap reopening as new studios are added. Ship the two-user negative-authorization suite alongside it and gate CI on it.

**Model registry (PJ-P0-2 / LC-P0-1).** Remove the blanket `except Exception: return None` from `_register_model_version`. Make `create_model_version` transactional. Resolve a real `dataset_version_id` or block with a 409. Assert artifact-root writability at startup. Until this lands, **no model has ever been durably saved.**

**Frontend scope leaks (UX-P0-1, P0-2, P0-4, P0-5).** Reset `state.steps` in `startProjectFromWorkflow`; hydrate Project Context from defaults; delete the Evaluation fallback to the unscoped browser cache; sweep all `modeling-tool-*` keys on sign-out.

**Mount the ErrorBoundary** (UX-P0-6) — it exists and is imported nowhere.

**Make the Data Acquisition milestone track a projection** of `deriveDataAcquisitionStatus` rather than of `loadProgress` (UX-P0-3). This closes the acceptance item the previous phase left open.

**Operational basics:** real `/api/ready`; fix the port contradiction in the docs; single client module with `credentials: "include"` and the two wrong-port fallbacks corrected.

---

## Next 60 days

- **Consolidate the requirements files** into one lock generated from the working venv; pin `duckdb`/`polars`/`pyarrow`; drop the 26 unused declarations (which also removes the `ydata-profiling` licence question and the `python-jose` CVE noise). (TO-P0-3)
- **Materialize Parquet at registration** — the single largest performance win available: measured 10× time, ~4.3× memory. (SCALE-P0-4)
- **Fold near-zero variance into the single-pass aggregate** and rename the misleading `datasetScans` field. (SCALE-P0-2)
- **Instantiate `Deadline`** and route governed profiling through the existing `CONCURRENCY` governor; move it onto the `run_async` job pattern already implemented. (SCALE-P0-1, P0-3)
- **Structured logging** with request/user/project correlation IDs via the existing `contextvars` pattern. (TO-P1-10)
- **Evidence consolidation** — one store, append-only with supersession, `createdBy` set server-side, audit events, and `require_evidence_eligible` called inside `upsert_evidence` rather than per-router. (PJ-P0-4, LC-P1-7, LC-P1-8)
- **Behavioral tests for the four uncovered domains** — Evidence, MDD, SQL Studio, Notebooks. (TO-P1-5)
- Per-user quotas and rlimits on code execution; clamp every unbounded `limit` and `max_rows`. (SEC-P1-3, SCALE-P2-1)

---

## Next 90 days

- **Lifecycle invalidation service** — pin every downstream record to `model_version_id`, add a `computed_over` fingerprint, and mark documentation/validation/monitoring stale on upstream change. (LC-P0-4)
- **Reproducibility envelope** — environment id, library versions, code commit, target class mapping, feature order, split indices. Thread `random_seed` through the trainer so the recorded contract stops being false. (LC-P1-10, LC-P1-6)
- **Artifact integrity** — verify checksums on read; enforce write-once; restrict the scoring-run UPSERT to lifecycle columns. (LC-P0-5)
- **Backup and restore** with a tested drill; down-migrations; retention and an orphan sweeper; repair the 312 dangling foreign keys. (TO-P2-11, PJ-P1-7, PJ-P1-8)
- **Accessibility pass** — skip link, focus management, live regions, the truncated status strip, colour-only status, contrast. Add `axe-core` to CI. (UX-P1-11, P1-12)
- Concurrency and reproducibility test suites. (TO-P2-12)

---

## Before a paid design-partner pilot

**Non-negotiable — all four P0 security items plus:**

| Requirement | Finding |
| --- | --- |
| Public registration cannot grant admin | SEC-P0-1 |
| Header impersonation off by default, loopback-bound | SEC-P0-2 |
| Resource-level authorization on all ~190 endpoints, enforced by a startup assertion, CI-gated by a two-user suite | SEC-P0-4 |
| Code execution either behind a real isolation boundary or **disabled** in multi-user deployments | SEC-P0-3 |
| Model registry actually persists; registration failure is loud | PJ-P0-2 |
| Checkpoint saves succeed and failures are visible | PJ-P0-1 |
| Cross-project frontend leaks closed | UX-P0-1/2/4/5 |
| Fabricated Step 13 monitoring models and Challenge-Mode confidence removed | UX-P1-8 |
| Reproducible install; CI green on a full suite | TO-P0-2/3 |
| Committed transaction data removed and its history remediated | TO-P1-7 |
| Secure cookies; CSRF | SEC-P1-2 |
| Backup and restore that works | TO-P2-11 |

> A pilot participant is an *ordinary authenticated user*. SEC-P0-4 needs **no bypass** — that is what makes it the pilot blocker rather than a hardening item.

---

## Before a single-bank controlled production deployment

Everything above, plus:

- **MDD as a governed projection** — activate the `mdd_*` schema, wire `documentation_bundle`, replace substring champion inference. (LC-P0-3)
- **Segregation of duties unbypassable**; approvals bound to an immutable model version. (LC-P0-2)
- **Invalidation live** across documentation, validation, and monitoring. (LC-P0-4)
- **Monitoring bound to a model version**, observations server-derived from the PSI/VSI already computed, with a scheduler. (LC-P1-9)
- **Audit trail unified and tamper-evident** (hash chain, separate permissions). (PJ-P0-3, SEC-P2-2)
- Artifact integrity verified on read; formula-injection neutralization on exports; SSO / enterprise identity; PostgreSQL; object storage; documented RPO/RTO with a rehearsed restore.
- Nine duplicated sources of truth reconciled to one each. (ARCH-P1-1)

---

## Before 50 users

**This is the threshold the platform is furthest from meeting.** Projections put threadpool saturation — where *every* endpoint stops responding — between **25 and 40 concurrent analytical users**.

Required: remove the global profiling lock; async or job-queue the heavy paths; explicit threadpool sizing; a shared (not process-local) cache; per-user quotas and backpressure; WAL + `busy_timeout` on the security DB; **and a real concurrency test, which does not exist today**.

## Before 100 users

Multiple application instances behind a shared cache and session store; PostgreSQL; a real queue with separate workers; object storage for the 332 MB (and growing) artifact tree; per-tenant quotas; horizontal scaling of the analytical plane.

## Before 100 million rows

Parquet mandatory at registration; columnar projection pushdown in the profiler (it currently does `SELECT *`); spill-to-disk configured; the profiler decomposed so statement count stops being O(columns); paginated predictor/missingness payloads; a distributed engine behind the connector interface that currently has none.

## Before 1 billion rows

A genuinely different data plane: external compute (Spark/Trino/Snowflake/BigQuery) behind the existing connector abstraction, sampling-with-disclosure for interactive work, exact computation as governed batch jobs, and partition-aware artifact layout. **The current single-process DuckDB design will not reach this and is not the wrong choice for where the product is today.**

---

## Deferred — do not work on these yet

- **The 11,768-line `WorkflowPlaceholderStep.tsx` refactor.** Real debt, zero user-facing risk. Extract opportunistically when touching a studio.
- **Deleting the ~9,300 LOC of dead code.** Do it in one cleanup pass, not as a project.
- **Vendor/external model onboarding.** A genuine SR 11-7 gap and a hard market requirement — but only after the *internal* lifecycle actually persists a model.
- **Browser-compatibility matrix and the full WCAG programme.** Add `axe-core` to CI now; defer the full remediation.
- **Distributed analytical execution.** The connector interface with no engine behind it is honest scaffolding. Leave it until a real workload demands it.
- **Advanced ML (RL, computer vision, graph analytics).** These are declared in the workflow config with no implementation. Adding breadth before the core lifecycle is durable would compound the problem the audit found.

---

## The one structural recommendation

**Stop the "correct design, never wired in" pattern.** The audit found it four times: `analysis_scope.py` enforced at one endpoint of many; the `mdd_*` schema with zero readers; `documentation_bundle` exported and never called; `Deadline` defined and never instantiated. Add a CI check that fails when a module exports a governance primitive with zero call sites.

**And keep the page-by-page acceptance walkthrough.** It is working — it produced `dataAcquisitionStatus.ts`, `analysis_scope.py`, the honest 409, and the no-fallback invariant, all of which this audit rates as genuinely good. The correction is not to change the method but to **generalize each fix across all steps before moving to the next page**, because every defect class fixed on Data Acquisition was found still live on four to six other steps.

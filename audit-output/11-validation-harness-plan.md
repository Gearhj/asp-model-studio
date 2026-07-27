# 11 — Validation Harness Plan

**Purpose:** specify the automated suites that would convert ATLAS's current assurance — a large body of good tests that nothing runs, plus a large body of source-text assertions that prove little — into a real, continuously-enforced gate.

**Two structural prerequisites, before any new test is written:**

1. **An aggregate target and a CI workflow.** There is none today, and no `npm test`.
2. **A wiring guard.** A CI step that enumerates `tests/*_test.py` and `tests/*.test.mjs` and **fails if any file is unreachable from the aggregate target.** Sixteen of the best tests in this repository are orphaned; without this guard they will orphan again.

---

## 1. Authorization

**Existing foundation:** `tests/persistence_authorization_test.py` is genuinely excellent — 16 denied verbs, asserts the 403 body does not leak, audit event persisted, cross-project hijack → 404, 401 ≠ 403. **It is orphaned.** Wire it first, then generalize its pattern.

| Suite | Specification |
| --- | --- |
| `authz_matrix` | Provision users A and B with no shared grants, 2 projects, 2 datasets, 2 models each. For **every** endpoint in the OpenAPI spec (415 operations), issue B's session against A's ids and assert 403/404 — never 200. Maintain an explicit, reviewed allowlist of endpoints that legitimately need no resource authorization; **fail on any endpoint that is in neither the allowlist nor the pass set.** |
| `authz_startup_assertion` | Unit-test `assert_api_routes_authorized` (the extension of the existing authentication assertion): assert it raises for a synthetic route whose handler reaches no authorization primitive, and for a prefix-less route. |
| `authz_escalation` | Unauthenticated `POST /api/auth/register {"role":"admin"}` → assert the created role is the lowest role and that `GET /api/admin/users` with that session is 403. With no env vars set, `X-ATLAS-USER-ID: <seeded admin>` → assert 401. |
| `authz_substitution` | As B, `POST /api/python/run` with `projectId=projB` and `datasetId=dsA` → 403. `PUT /api/evidence/{B's id}` with `{"projectId": projA}` → assert the stored `projectId` is unchanged. |
| `authz_self_escalation` | As a dataset `editor`, grant self `owner` → 403. |

**Gate:** every PR. This is the suite that makes a pilot defensible.

---

## 2. Isolation

| Suite | Specification |
| --- | --- |
| `scope_isolation` | Extend the existing `modeling_state_characterization_test.py` (already strong) with cache-identity cases: two users, same registered dataset version, different projects → assert each `/api/eda/workspace/*` response carries **its own** `analysis_scope.projectId`. This fails today. |
| `browser_isolation` | Playwright: complete work in project A, create project B → assert zero A values appear (workflow statuses, Project Context, outlier config, EDA commentary, training summary, active job). Sign out, sign in as another user → assert no `modeling-tool-*` key survives. |
| `list_filtering` | For every parameterless list endpoint, assert a non-admin sees only its own rows and that an admin's superset is explained by role, not by absence of filtering. |

---

## 3. Persistence and restart

| Suite | Specification |
| --- | --- |
| `restart_durability` | **Kill and restart a real uvicorn process** (not an in-process TestClient — the current tests explicitly note this as out of scope). Assert: projects, workflow state, evidence, dataset links, and registered model versions all survive; that an in-flight training job is 404 and never falsely "running"; and that scoring after restart loads the fitted object **from the registry artifact**. |
| `checkpoint_integrity` | Seed a scope whose `target` is `numpy.int64` → assert `save_checkpoint()` is `True` and round-trips. Assert one malformed scope does not abort the others. Assert size stays under the warning threshold with N scopes and that GC reclaims deleted-project scopes. Assert failure is reported on `/api/persistence/health`. |
| `integrity_check` | Assert `PRAGMA foreign_key_check` and `integrity_check` return clean on a seeded DB, and that project deletion cascades evidence, decisions, and collaborators. **Returns 312 violations today.** |
| `migration` | Fresh DB → apply `0001`–`0015` → assert the final schema. Inject a failure at statement 3 of a multi-statement migration → assert the schema is unchanged and a clean re-run succeeds. Assert reported `schemaVersion` equals the highest applied migration. |
| `registry_concurrency` | N concurrent dataset registrations and evidence writes → assert all N survive and that index and item files stay consistent. Assert a corrupt registry is quarantined, never overwritten with an empty default. |

---

## 4. Concurrency

**None of this exists today.** The process-global `DATASTORE` / `RESULTS` / `TRAINING_JOBS` dicts are verified single-threaded only — precisely the structure where concurrent access produces cross-tenant leakage.

| Suite | Specification |
| --- | --- |
| `concurrent_isolation` | 10 threads × 2 users × 50 interleaved requests across `set_sample`, profiling, and training submission → assert each user reads back only its own data and that no result is attributed across scopes. |
| `concurrent_load` | Ramp 1/5/10/25/50 concurrent governed profiles from distinct users. Record p50/p95/p100. **Assert `/api/health` p99 stays ≤ 250 ms throughout** — this is the single most important assertion in the whole harness, because it converts "profiling is slow" into "the platform is down". |
| `idempotency` | Duplicate training submit → assert the same job is returned and no second thread starts. Duplicate scoring submit → assert one run. Duplicate dataset upload → assert one dataset, not a `_{ts}`-suffixed second. |
| `db_contention` | 50 concurrent authenticated requests → assert zero `database is locked`. Assert the security store uses WAL and a busy timeout. |

---

## 5. Data scale

Drive over HTTP against a real uvicorn process — in-process clients make the concurrency and threadpool results meaningless. Generate fixtures under a scratch directory and delete them.

| Fixture | Asserts |
| --- | --- |
| 170,884 × 31 CSV **and** Parquet | k constant; Parquet ≥ 5× faster and ≥ 3× lower peak RSS |
| 1M × 31, 10M × 31 | linearity; the OOM wall; that the request **errors** rather than OOMing the process |
| 170,884 × 500 / × 1,000 | statement count = `2E + 12` after the N+1 fix; **`cached: true` on the second identical request** (fails today above ~445 columns); the C-way `COUNT(DISTINCT)` memory bound |
| 170,884 with one 1M-distinct categorical | RSS delta ≤ 100 MB or an honest 422 |

Also assert: exactly one `read_csv` of `data_full.csv` per panel mount (two today); `?max_rows=99999999` returns 422 or a capped result; the correlation payload is bounded; a configured timeout returns 504 within its bound.

---

## 6. Job recovery

Restart mid-training → 404, no false resume (**already covered by a named test — wire it in**). Restart mid-scoring → no orphan Parquet, or a recorded orphan. Kill a worker thread → job reports failed with an honest message. Cancel during a grid search → assert CPU work actually stops within N seconds, not merely that a status flag flipped.

---

## 7. Model and scoring reproducibility

**Nothing here exists today, and this is a core SR 11-7 expectation.**

- Train twice with `random_seed=1` → identical coefficients. Train with seed 1 vs 2 → **different** coefficients. Assert `training_parameters_json.randomSeed` equals the requested seed. *(Fails today: the seed is recorded and ignored.)*
- Score the same input twice → bitwise-identical `y_score` to 1e-12.
- Assert a registered version captures environment id, Python and library versions, code commit, target class mapping, feature order, and a resolvable split and feature manifest.
- Tamper one byte of `model.joblib` → assert the next load raises `ARTIFACT_INTEGRITY_FAILURE` and writes an audit row.

---

## 8. Evidence provenance and MDD traceability

- Capture evidence, then mutate the underlying run → assert the evidence content hash and `createdBy` are unchanged and lineage still resolves.
- Re-capture with identical descriptors → assert a **new** item exists with `supersedes` set and the original still readable. `DELETE` → 405.
- Compute over an unregistered workspace frame → `POST /api/evidence` returns **409** naming the workspace-draft reason. Register a version, re-run → 201 with `analysisScope.mode == governed_version`. Posting `evidenceEligible: true` with a draft scope still returns 409.
- MDD: assert the document contains the exact `modelVersionId` and `evidenceId`; that `championModel` equals the registered algorithm (never a substring guess); that attaching a non-existent `evidenceId` is 404; and that `prior_text_hash` is identical across two process restarts.

---

## 9. Validation independence and monitoring

- Developer A submits; `PATCH /cases/{id} {"status":"approved"}` → **409**. Approval by A → 403. Approval by validator B → succeeds and writes `model_version_id`. `POST /model-versions/{id}/governance-status` as a view-only user → 403.
- Register v1; create MDD, validation case, and monitoring plan bound to v1; register v2 → **assert all three report stale** with a reason naming v1→v2, and that MDD export and approval both return 409 while stale.
- Monitoring plan without `model_version_id` → 422. Observation posted by an ungranted user → 403. Observation with a `scoring_run_id` → `observed_value` is **server-derived** from the run's PSI/VSI.

---

## 10. Browser UX and accessibility

- Playwright across **chromium, firefox, webkit** with a `webServer` block so the suite is self-starting and CI-addable.
- `@axe-core/playwright` on every step route → zero `serious`/`critical` violations.
- Keyboard-only traversal: select a predictor on `/step03`; assert a skip link exists and that focus moves to the step heading on navigation.
- Assert every step exposes a scope header containing the active dataset version id.
- Assert the milestone track never shows "Evaluating data quality: COMPLETE" while readiness reads "Not evaluated".
- Assert no `state: "complete"` literal and no `confidence: 0.` literal exists in `src/`.
- Assert each status-strip label has `scrollWidth <= clientWidth` at 1440×900.

---

## 11. Clean install

CI job on a clean container: `pip install -r requirements.lock` → `pip check` → assert `pip freeze` diff against the lock is empty → **`GET /api/health` returns 200** (fails today: `polars`/`pyarrow` are module-scope imports and appear in neither requirements file) → run the full Python suite. Separately `npm ci` → `tsc -b` → `npm run build`.

---

## 12. Backup and restore

Seed a database and artifact tree → back up → destroy → restore into an empty directory → assert row counts and checksums match across **every** table, `foreign_key_check` is clean, and every `output_artifact_path` / `artifact_reference` / evidence item file resolves. Assert both SQLite files are captured **with their WAL sidecars** and that the artifact tree and checkpoint are included.

---

## 13. Statistical correctness

**Two excellent reference tests already exist** — Wilson intervals recomputed from the formula independently *"so a regression cannot pass by matching itself"*, and regression metrics recomputed from raw arrays to 1e-9. **Both are orphaned.** Wire them in and extend the pattern:

- **IV / WOE have no independent reference test.** Add one: compute IV for a small hand-checkable table and assert against an independently expressed formula including the Laplace smoothing constant.
- Assert `formatIv` never coerces `null` to `0.0000`.
- Assert a high IV never produces a leakage verdict, a progression blocker, or an automatic exclusion — the `V1`–`V28` PCA-component rule.
- Assert the target is excluded from predictor near-zero-variance and constant-column findings while remaining in Target Health.

---

## Execution model

| Tier | Contents | Trigger | Budget |
| --- | --- | --- | --- |
| **Fast** | Node unit + Python unit + structural lint | every PR | < 5 min |
| **Integration** | authorization, isolation, persistence, migration, evidence, validation | every PR | < 20 min |
| **Browser** | Playwright × 3 browsers + axe | every PR to main | < 30 min |
| **Heavy** | concurrency, scale, restart, backup/restore, reproducibility | nightly | unbounded |
| **Release** | clean install + full DR drill | per release | unbounded |

**Reclassify the ~20–31 source-text `.test.mjs` files into `tests/structural/`** and exclude them from every coverage claim. They are useful as lint. They are not evidence of correctness, and counting their ~2,000 assertions as coverage is the single most misleading number in the project's current self-assessment.

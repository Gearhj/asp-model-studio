# 08 — Testing, Deployment, and Operations

**Method:** static inspection of the full test tree, `package.json`, both requirements files, the installed virtualenv, `.gitignore`, and the committed runtime logs. Key counts were independently re-run by the main agent.

---

## 1. Test inventory

| Suite | Count |
| --- | --- |
| Node `tests/*.test.mjs` | **54** |
| Python `tests/*_test.py` | **32** (all `unittest`) |
| Playwright `tests/e2e/*.spec.ts` | **23** specs / ~46 tests / ~622 `expect()` |

### 1.1 Behavioral vs source-text — the priority distinction

A large fraction of the Node suite does not execute anything. It `readFileSync`s a `.tsx`/`.ts`/`.py` file and regex-matches its text.

**Main-agent measurement:** applying a strict test (file uses `readFileSync` **and** contains no `await import(` / `transpileModule` / `pathToFileURL`), **20 of 54** Node test files are pure source-text. The testing lane, using broader exclusion criteria that also required the absence of `fetch(` and `execFileSync`, counted **31 of 54**. **Either way, between 37% and 57% of the Node suite asserts on source text rather than behaviour.**

Supporting counts (lane-reported): `assert.match` / `assert.doesNotMatch` against source text appears **~2,008 times across 43 of the 54 files**. **Zero** `.test.mjs` files import from `src/` via a normal ES import — everything executed is first transpiled into `.tmp/`.

**The most misleading single assertion** — `tests/userManagement.test.mjs:17`:

```js
["passwords are hashed", securityStore.includes("pbkdf2_hmac") && !securityStore.includes("plaintext")],
```

This passes if the substring appears anywhere in the file — in a comment, a disabled branch, or dead code — and would keep passing if hashing were replaced by a no-op that left the import line behind. The file also uses `process.exit(1)` rather than `node:test`, so it produces no structured result.

Others in the same class: `creditRiskStudio.test.mjs` (1,087 lines, 295 `assert.match`, zero execution — it asserts the *label text* `PDO / ln(2)` appears, never computing a scorecard point); `predictiveModelingRepair.test.mjs` (215 regex); `optimization.test.mjs` (197 regex); `modelDiagnostics.test.mjs` (asserts `package.json` contains its own npm script name).

**These are useful as structural lint. They are not evidence of correctness, and their assertion count must not be cited as coverage.**

### 1.2 The genuinely excellent tests

The Python suite is largely behavioral, using `TestClient` against the real app with real routing and real `Depends(require_user)`:

| File | What it proves |
| --- | --- |
| `persistence_authorization_test.py` | **Two-user negative authz** — 16 denied verbs, asserts the 403 body does not leak, audit event persisted, cross-project evidence hijack → 404, 401 ≠ 403 |
| `modeling_state_characterization_test.py` (2,599 lines) | DATASTORE/RESULTS/TRAINING_JOBS scope isolation; job-restart contract |
| `validation_segregation_of_duties_test.py` | Self-approval prevention |
| `security_lockout_test.py` | Lockout counter + audit persistence |
| `target_intelligence_test.py` | **Statistical reference** — textbook Wilson intervals recomputed from the formula independently *"so a regression cannot pass by matching itself"* |
| `regressionMetricValidator.test.mjs` | **Statistical reference** — recomputes MAE/MSE/RMSE/R² from raw arrays to 1e-9 |
| `checkpoint_lifecycle_test.py` | Checkpoint GC and size control |
| `dataset_lifecycle_test.py`, `model_registry_test.py`, `scoring_runs_test.py`, `analytical_data_plane_test.py` | Real lifecycle behaviour |

**These are genuinely good tests — better than most codebases of this size have.**

### 1.3 The central irony: the best tests never run

**16 test files are orphaned** — their filenames appear in none of the 66 `package.json` scripts. They include **every** two-user authorization test, the segregation-of-duties test, the lockout test, the checkpoint-GC test, and both independent statistical-reference tests.

The controls a bank cares about most are verified by excellent tests that **no process executes**.

**Direct proof of the consequence:** `checkpoint_lifecycle_test.py` was written to fix a checkpoint-growth defect (its docstring cites the original 322 MB / 37-scope incident). It is orphaned. The defect it guards against **is currently recurring at 923 MB** — 2.9× the original magnitude, undetected. See [05-persistence-jobs-and-recovery.md](audit-output/05-persistence-jobs-and-recovery.md).

### 1.4 Domains with ZERO behavioral coverage

**Evidence · Documentation/MDD · SQL Studio · Notebooks.**

Their only tests are source-text files totalling ~160 regex assertions against `.tsx` files. Evidence and MDD are **the regulatory output of this platform** — the artifacts a validator and an examiner actually read. SQL Studio and Notebooks **execute user-supplied queries and code**. No test proves an evidence record is immutable, correctly attributed, or provenance-linked.

### 1.5 Missing test classes

| Class | Status |
| --- | --- |
| Two-user negative authz | ✅ exists, **orphaned** |
| Persistence across restart | ⚠️ partial — `scoring_runs_test.py:298-300` explicitly states real process-restart is out of scope |
| **Concurrency** | ❌ **none** — zero threading/`asyncio.gather` in any test; Playwright `workers: 1`. The process-global `DATASTORE`/`RESULTS`/`TRAINING_JOBS` dicts are verified **single-threaded only** |
| **Job recovery** | ❌ none |
| **Model reproducibility** (same seed → same model) | ❌ **none** — a core SR 11-7 expectation, asserted nowhere |
| **Scoring reproducibility** | ❌ none |
| **Evidence provenance** | ❌ none |
| Migration tests | ⚠️ partial — 15 migrations exist, 2 referenced; **no fresh-DB→final-schema assertion, no rollback** |
| Clean-install test | ❌ none — and §3 shows it would fail |
| Statistical reference | ✅ narrow — Wilson and regression metrics only. **IV/WOE have no independent reference test** |
| Accessibility | ❌ none — zero `axe-core`/`lighthouse` in the dependency tree |
| Performance/benchmark | ⚠️ three ad-hoc `perf_counter` assertions |
| Browser compatibility | ❌ chromium only |

---

## 2. CI — there is none

**Verified: `git ls-files` matching `.github/`, `gitlab-ci`, `Jenkinsfile`, `azure-pipelines`, `.circleci` returns 0.**

**Verified: there is no `npm test` aggregate script.** All 66 scripts must be invoked individually.

`docs/RELEASE_CHECKLIST.md` — the only documented gate — runs **exactly one** of the 66: `npm run test:experimental-design`.

> **The actual current gate on a change is a human remembering to type a command — and the documented gate covers 1.5% of the declared suite.** No commit in this repository has demonstrable evidence of having passed its own test suite.

---

## 3. Dependencies — a clean install produces an untested environment

**Two conflicting requirements files** (root: 96 lines / 52 pinned; `server/`: 17 lines), disagreeing on **6 of 17 overlapping packages**:

| Package | root | server/ | **actually installed** |
| --- | --- | --- | --- |
| fastapi | 0.115.0 | 0.110.0 | 0.115.0 (root) |
| pydantic | 2.7.4 | 2.6.1 | 2.7.4 (root) |
| uvicorn | 0.30.6 | 0.27.1 | 0.30.6 (root) |
| pandas | 2.1.4 | 2.2.1 | **2.2.1 (server)** |
| scipy | 1.13.1 | 1.17.1 | **1.17.1 (server)** |
| matplotlib | 3.8.4 | 3.8.3 | **3.8.3 (server)** |

**The working environment is a mixture of both files. Neither describes the environment the tests were validated against.**

**26 of 51 declared packages (51%) are not installed** — including `pytest` (the declared test runner; all Python tests use `unittest`) and `passlib[bcrypt]`/`python-jose` (the declared "production hardening" block; hashing is hand-rolled PBKDF2 instead). Seven installed packages drift from their declared versions.

**Running `pip install -r requirements.txt` would downgrade pandas 2.2.1→2.1.4 and scipy 1.17.1→1.13.1 and install 26 never-present packages.** A regulator asking *"reproduce the environment in which this model was validated"* cannot be answered.

**`duckdb`, `polars`, and `pyarrow` — the analytical engine — appear in neither requirements file** (verified: 0 matches in `server/requirements.txt`). `polars` and `pyarrow` are **module-scope** imports reached at app boot, so a clean install from either file **fails to start the server**, not merely one feature. (`duckdb` is correctly deferred with an honest 503.)

**Licence/SCA noise from unused declarations:** `ydata-profiling` (newer versions require a **paid commercial licence** — a direct question for a bank), `python-jose` (documented CVE history), `psycopg2-binary` (explicitly discouraged for production). All three are **declared but not installed** — they will appear in any SCA scan of `requirements.txt` as findings against software that is not in the running system, consuming review cycles while the real 75-package installed set stays undocumented.

**Node:** `package-lock.json` is committed (lockfileVersion 3), no `latest`/`*` specifiers. Caret ranges are safe **only with `npm ci`** — and `docs/LOCAL_DEVELOPMENT.md` instructs `npm install`.

**Absent entirely:** `engines` field, `.nvmrc`, `.python-version`, `pyproject.toml`, Dockerfile, docker-compose, any Kubernetes/Helm manifest, SBOM, `LICENSE`, `NOTICE`, and any licence-scan output.

---

## 4. Startup and operability

**No backend npm script exists** — startup is manual and documented only in prose, **with `--reload` (a development flag) in the only documented start command**.

**Port contradiction:** the docs say port **8000**; `vite.config.ts` proxies `/api` to **8001**. Following the only startup documentation yields a frontend that cannot reach the backend.

**Health checks:**

```python
# server/main.py:157-159
@app.get("/api/health")
def health(): return {"ok": True, "status": "running"}
```

A **static literal**. It checks nothing — not the database, not disk. Combined with `main.py:169-171`, which catches `PersistenceUnavailableError` and merely `print()`s it, **an instance whose database is entirely dead returns 200 to a load balancer**. `/api/persistence/health` does check the DB but hardcodes `"schemaVersion": "0003"` while **15** migrations exist — actively misinforming operators during triage. There is no readiness/liveness distinction.

**45 `ATLAS_*` environment variables**, all `os.getenv(NAME, default)`. There is exactly one fail-fast path and **its own precondition defaults to off**: `enforce_hosted_security_configuration()` returns immediately unless `ATLAS_HOSTED_MODE` is true, which defaults to `"false"` while `ATLAS_LOCAL_DEV` defaults to `"true"`.

> **A deployment that forgets one variable boots successfully with a hardcoded session secret, a hardcoded admin password, and the `X-ATLAS-USER-ID` impersonation header enabled.** Forgetting a variable does not fail — it silently selects the least-secure configuration. The platform's own diagnostic downgrades the default-secret condition to a `"warning"`.

---

## 5. Observability — effectively absent

Across ~37 server packages:

- `import logging` in **3 files**; `logger.*` calls: **2 total**
- Bare `print()`: **11**, including the persistence-failure path
- **No `basicConfig`, no `dictConfig`, no logging configuration anywhere**
- Zero matches for `request_id | correlation_id | trace_id | opentelemetry | prometheus | sentry | datadog`

`uvicorn.log` (654 lines) is entirely the uvicorn default access format:

```
INFO:     127.0.0.1:<port> - "GET /api/health HTTP/1.1" 200 OK
```

**No timestamp on any line.** No user ID, no session ID, no request ID, no duration, no response size. The only correlation handle is a `project_id` that happens to appear in some query strings — absent from all POST/PUT bodies.

`uvicorn.err.log` contains **15 tracebacks**, including 5× `TypeError: 'numpy.int64' object is not iterable` from a `pd.read_json(json.dumps(payload))` path — a live, consistently reproducing defect (the checkpoint failure of [05](audit-output/05-persistence-jobs-and-recovery.md)) with **no request context attached**.

**What a support engineer could diagnose from a report of "my training failed at 14:30": almost nothing.** Cannot filter by time (no timestamps), by user (no user ID), or by request (no correlation ID); cannot measure latency (durations are returned to clients, never logged). They can see that *some* request to *some* path returned 500.

The one real audit facility — `audit_event()` writing to SQLite, proven behavioral by two named tests — is a compliance trail, not operational telemetry, and is queryable only by direct SQL.

---

## 6. Backup, DR, supportability — all absent

| Item | Status |
| --- | --- |
| Backup script | ❌ only `reset_atlas_db.py`, which copies the DB **before a destructive reset** — and copies only `atlas_local.db`, without WAL sidecars, the security DB, artifacts, or the checkpoint |
| Restore procedure | ❌ none documented, none tested |
| Retention policy | ❌ none — `docs/ARTIFACT_STORAGE.md` is aspirational future tense |
| RPO / RTO | ❌ **zero occurrences of "RPO" or "RTO" in `docs/`** |
| Migration rollback | ❌ 15 forward-only migrations, no down-migrations |
| Rolling upgrade / HA / failover | ❌ none |
| Documented backup target | ⚠️ `docs/ARCHITECTURE.md` names **a developer's local folder sync** as the backup |

---

## 7. Repository hygiene — the bank-review problem

**Measured: 1,802 tracked files, 518.5 MB working tree, 273.6 MB `.git`.**

| Category | Size |
| --- | --- |
| `server/artifacts/` (runtime application state) | **382.1 MB**, 538 files |
| `test-results/` (203 PNG screenshots + JSON) | **93.6 MB** |
| Source + docs | ~43 MB (**~8%**) |

**92% of the tracked repository is generated artifacts, screenshots, and datasets.**

Largest tracked files:

| Size | Content |
| --- | --- |
| 82.4 MB | `data_full.csv` — `Time,V1..V28,Amount,Class`, 170,885 rows |
| 82.4 MB | **byte-identical duplicate** of the above under a different dataset id |
| 30.3 MB | a single evidence record JSON |
| 21.5 MB | `data_full.csv` with an explicit **`user id`** column, 588,102 rows |

**Inference (high confidence):** the `Time,V1..V28,Amount,Class` schema is the Kaggle *Credit Card Fraud Detection* dataset — PCA-transformed **real European cardholder transactions**, under a licence with redistribution restrictions. Two full copies are committed.

> **A bank security review will read this as: real payment-transaction data and per-user identifiers redistributed into source control, in duplicate, with no data-classification label, no `LICENSE`/`NOTICE`, and no DPIA reference.** Because it is already in 273.6 MB of history, `.gitignore` alone is not remediation — a history rewrite is required before any external sharing.

`.gitignore` correctly excludes `node_modules/`, `dist/`, `*.log`, `.env*`, `.venv/`, `.runtime/`, and the DB files — but **not** `server/artifacts/` or `test-results/`, the two largest categories.

**No secret values were found in any tracked `.env*` file** — `.env.modeling` and `.env.scheduling` are deliberately tracked and contain only build-target configuration. That part is fine.

Also present: 94 `*_REPORT.md` / `*_AUDIT.md` files at repo root with no `docs/` organization; residue from a different application (`guitarist.html`, `fetch-wikidata-guitarists.mjs`, `server/stela_router.py`); and 36 stray per-process security DBs in `server/data/`.

---

## 8. Findings

| ID | Sev | Title |
| --- | --- | --- |
| TO-P0-1 | P0 | 37–57% of the Node suite asserts on source text, not behaviour |
| TO-P0-2 | P0 | No CI exists; the documented release gate runs 1 of 66 scripts |
| TO-P0-3 | P0 | A clean install produces an environment that has never been tested; the analytical engine is undeclared |
| TO-P0-4 | P0 | The 16 highest-value behavioral tests (all authz, SoD, lockout, checkpoint-GC) are orphaned and never run |
| TO-P1-5 | P1 | Evidence, MDD, SQL Studio, Notebooks have zero behavioral coverage |
| TO-P1-6 | P1 | Checkpoint growth guard test exists but is orphaned; the defect has recurred at 2.9× scale |
| TO-P1-7 | P1 | 382 MB of runtime artifacts incl. transaction data and user IDs committed to git |
| TO-P1-8 | P1 | Health endpoint is a static literal; no readiness probe; schema version 12 migrations stale |
| TO-P1-9 | P1 | Missing a security env var silently yields the least-secure configuration |
| TO-P1-10 | P1 | No operational logging, no correlation IDs, no metrics, no tracing |
| TO-P2-11 | P2 | No backup, restore, retention, RPO/RTO, rollback, or DR story |
| TO-P2-12 | P2 | No concurrency, job-recovery, or reproducibility tests; process-global state verified single-threaded only |
| TO-P3-13 | P3 | Documented backend port contradicts actual configuration |
| TO-P3-14 | P3 | Chromium-only E2E, no accessibility tooling, no benchmark suite, no self-starting harness |

**The single highest-value, lowest-effort remediation in the entire audit:** add an aggregate test target and wire in the 16 orphaned files. **Those tests already exist and already pass.** Combined with a minimal CI workflow, this converts a large body of genuine verification work from decorative to load-bearing — in perhaps a day.

---

## 9. Baseline caveat, recorded

`tests/e2e/data-acquisition-ui-load.spec.ts` fails in its final predictor-semantics assertion block, after the real UI load and reconciliation have succeeded; one screenshot was never captured. **Recorded as a known localized acceptance item, not investigated, not fixed, and not scored as a P0.**

One additional observation: **that spec is untracked in git** (`?? tests/e2e/data-acquisition-ui-load.spec.ts`). The known-failing test is not in version control.

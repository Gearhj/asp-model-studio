# ASP Model Studio — Capacity Report (Fable 5.1 audit, Phase 11)

Audit base `bff19a8a657bc96dea0469fad481acdcb4234386`. Machine-readable results: `ASP_MODEL_STUDIO_FABLE51_CAPACITY_RESULTS.json`.
Every measurement below was taken on the **isolated** stack (uvicorn on 8191 against disposable copies of the persistence DB, security DB, and staging roots under the scratch directory). The primary services on 8101/5274 were never started, and the authoritative database and Gold/companion/prior stores were not touched. All fits are synthetic audit activity on the disposable copy of `asp-mtddc6pw` (null model and a 6-feature FIXED logistic), produced no champion or promotion, read no final-OOT row, and were deleted with the scratch root.

## 1. Environment

| Item | Value |
| --- | --- |
| Host | Windows 10 Pro workstation, Intel Core i7-4790 (4 cores / 8 threads), 31.9 GB RAM; load client on the same host |
| Backend | single uvicorn process, synchronous handlers on the default thread pool, one in-process job slot (`ThreadPoolExecutor(max_workers=1)`), SQLite persistence (WAL) + SQLite security DB (rollback journal) |
| Population | 103 synthetic users (3 audit users + `f51-load-000..099`), 100 synthetic projects (evidence binding + forecast contract), the disposable copy of `asp-mtddc6pw` for jobs |
| Client | python httpx, one client per user; timeouts 300 s (load phases) / 900 s (patient phase); curl for idle health |

## 2. Registration and login (100 users, 25 threads)

| Measure | p50 | p95 | p99 | max | errors | wall |
| --- | --- | --- | --- | --- | --- | --- |
| login ×100 | 4.53 s | 6.47 s | 7.10 s | 7.10 s | 0 | 19.9 s |
| create project + evidence + contract ×100 | 4.84 s | 5.95 s | 6.64 s | 6.64 s | 0 | — |

Login is CPU-bound by PBKDF2-SHA256 at 260,000 iterations: roughly five logins per second on this host regardless of concurrency. Bulk user creation in a warm-up run produced HTTP 500/401 because the security database (rollback-journal mode, a `last_seen_at` write on every authenticated request) was locked by concurrent session writes (finding F-028). Account storage itself is not a constraint.

## 3. Twenty-five concurrent interactive users

Twenty-five users looped over the Stage 3 workflow reads on their own project (list projects, open project, EDA metadata/overview/distribution, autosave, outlier summary, feature summary, split contracts, Stage 2 review) with a 90 s target window.

| Result | Value |
| --- | --- |
| wall time for the 90 s window | 365 s |
| completed requests / throughput | 104 / 0.3 requests per second |
| overall p50 / p95 / max | 9.7 s / 300 s / 300 s |
| errors | 13 (all client timeouts at 300 s on `outlier_summary`) |
| backend CPU | 999 CPU-seconds over 361 s (2.8 cores average) |
| backend RSS | 863 MB → 7,036 MB |
| backend threads (max) | 64 |
| idle health after load (httpx) | p50 708 ms, p95 1.17 s |

Per operation:

| Operation | n | p50 | p95 | max | errors |
| --- | --- | --- | --- | --- | --- |
| list_projects | 21 | 53.0 s | 65.6 s | 66.2 s | 0 |
| open_project | 17 | 5.2 s | 12.6 s | 12.6 s | 0 |
| eda_metadata | 7 | 4.8 s | 7.6 s | 7.6 s | 0 |
| eda_overview | 7 | 10.5 s | 17.8 s | 17.8 s | 0 |
| eda_distribution | 10 | 8.7 s | 15.6 s | 15.6 s | 0 |
| autosave_put | 6 | 9.7 s | 13.0 s | 13.0 s | 0 |
| outlier_summary | 13 | 300 s | 300 s | 300 s | 13 |
| feature_summary | 10 | 7.7 s | 13.7 s | 13.7 s | 0 |
| split_contracts | 5 | 9.6 s | 12.6 s | 12.6 s | 0 |
| stage2_review | 8 | 7.6 s | 10.6 s | 10.6 s | 0 |

Interpretation. Two mechanisms dominate. First, `GET /projects` performs per-project state resolution for every project the caller can see (about 55 ms per project): 6.2 s idle with 113 projects, 53 s under load, so the landing page alone becomes unusable as the project count grows. Second, the outlier and EDA summaries load and profile the full 683,662-row Gold frame per project and keep the profile in process caches; twenty-five simultaneous profiles saturated the GIL-bound process and drove RSS to 7 GB. The server kept computing profiles for minutes after the clients had timed out, which is why idle health stayed at 0.7 s after the window closed. Nothing failed functionally, and no cross-user data appeared, but the experience is not usable beyond a handful of users.

## 4. Jobs

### 4a. Job submitted while the residual interactive load was still computing

A null + FIXED-logistic plan (10 fits) was submitted at 13:02:58 on the disposable copy of `asp-mtddc6pw`. While it ran, `GET /projects` exceeded the 300 s client timeout and the polling harness aborted; the job continued (330 s elapsed at configuration 2 when last read). A distinct plan submitted at 13:08 returned `409 MODEL_DEVELOPMENT_JOB_ALREADY_ACTIVE`.

### 4b. Coordinator kill and recovery

The backend process was killed at about 13:09:08 with that job RUNNING (one candidate receipt already persisted). The replacement process answered health after 9 s. On the first read after restart the orphaned job was reconciled to `INTERRUPTED` with `MODEL_DEVELOPMENT_COORDINATOR_INTERRUPTED`; its completed null-model receipt was retained and the in-flight logistic fit was lost. Job list 206 ms, runs list and candidate evaluation 200, the interprocess lock file was present but reclaimable, and a new null-only job was accepted (202 QUEUED) and reached COMPLETE in 5.5 s. There is no resume: an interrupted job must be resubmitted and re-runs every fit.

### 4c. Job on an idle host, duplicate submission, distinct plan, cancellation

| Check | Result |
| --- | --- |
| plan | 10 fits / 2 configurations, executable, finalOotLocked=true, finalOotTargetAccessed=false |
| 4 simultaneous identical submissions | 4 × 202, one job id (submissions coalesce), 1 active job |
| distinct plan while active | 409 `MODEL_DEVELOPMENT_JOB_ALREADY_ACTIVE` |
| health during job (httpx) | p50 425 ms (baseline 377 ms; curl idle 3.5 ms) |
| list_projects during job | p50 8.1 s (baseline 6.2 s with 113 projects) |
| job status poll during job | p50 74 ms |
| backend during job | ~1.4 cores, RSS ≈ 650 MB |
| cancel-unstarted at 8/10 fits | 200 `CANCEL_REQUESTED` in 136 ms; both configurations had already started, so cancelledFits = 0 and the job ran to COMPLETE 94.9 s later with 2 receipts |
| post-cancel null job | 202, COMPLETE in 6.9 s |
| after | list_projects 6.3 s, health 440 ms (httpx) |

Cancellation is configuration-granular: `cancel-unstarted` prevents configurations that have not started, and a configuration that has started always runs all of its folds. No API stops a running configuration, so time-to-abort equals the remaining duration of that configuration (a 16-hour grid job on the primary was itself only CANCELLED_PARTIAL). Killing the coordinator is the only abort, and it yields INTERRUPTED with completed receipts retained.

A single running job on an idle host kept the API responsive: interactive latency rose by roughly a third and health stayed flat. The catastrophic latencies in section 3 come from interactive profiling, not from job execution.

## 5. Safe operating limits on the current build (this host)

| Dimension | Safe | Degraded | Unacceptable | Basis |
| --- | --- | --- | --- | --- |
| registered users | 100 | — | — | 100 accounts created and used; constraint is login CPU (~5/s) and security-DB write locking, not storage |
| concurrent interactive users | 2 | 3–5 (5–15 s pages) | 25 | section 3 |
| simultaneous heavy jobs | 1 | — | 2 | one in-process slot, one active job per project; a second heavy job cannot run at all |
| sustainable envelope | 1 heavy job + 2 scientists on distinct projects | | | section 4c |
| memory | ≤ 5 simultaneous profiles | | ≥ 10 on a 16 GB host | 7 GB RSS at 25 |

## 6. Tiers

| Tier | Registered | Concurrent interactive | Heavy jobs | Status |
| --- | --- | --- | --- | --- |
| 0 — today (single operator) | 1 | 1 | 1 | measured |
| 1 — after repair-plan section A | 10 | 3 | 1 | measured envelope |
| 2 — controlled beta | 100 | 25 | 4 | projected only; requires worker separation, a durable queue, PostgreSQL, content-digest profile caching, project-list pagination, and re-measurement |

The 100-user / 25-concurrent / 4-heavy-job target of the mandate is **not achievable on the current build**; it is a Tier 2 architecture target (see `ASP_MODEL_STUDIO_FABLE51_PRODUCTION_ARCHITECTURE_PLAN.md`), and the numbers above are the evidence for that verdict rather than a tuning problem.

## 7. What was not measured

- Sustained multi-hour load, memory growth over days, and SQLite WAL growth under mixed write load.
- Four simultaneous heavy jobs: impossible on the current build (single slot); not simulated with multiple processes because the job coordinator, locks, and receipts are designed for one process per runtime root.
- A remote client: latencies exclude network transit and include Windows local connection setup in the httpx figures.

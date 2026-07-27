# 12 — Open Questions

Everything this audit could **not** verify, with the exact evidence or test that would settle it. Each item is stated as an open question rather than a finding, because asserting it would exceed the evidence.

---

## Deliberately not exercised (read-only constraint)

| # | Question | Why unverified | What would settle it |
| --- | --- | --- | --- |
| 1 | Does `POST /api/auth/register {"role":"admin"}` actually create an admin? | Confirming it would create a real admin account in the user's live database. Reported on **source evidence alone**, which is unambiguous. | One call in a disposable database; assert the returned session can reach `/api/admin/users`. |
| 2 | Are the **write-side** IDOR paths exploitable as predicted? Read-side is confirmed live (227 foreign evidence items, foreign notebook cell source, 27 foreign projects). | `DELETE /api/evidence/{id}`, `PUT /api/monitoring/plans/{id}`, `PATCH /api/validation/cases/{id}` would destroy or alter real records. | Two-user suite in a disposable environment asserting 403/404 on each verb. |
| 3 | Does `ATLAS_CODE_SANDBOX_COMMAND=default` actually permit reading the auth database from user code? | Would require executing code designed to reach credentials. The **capability** is established from source (`subprocess.run` of the venv interpreter with `-I`, no isolation primitives). | A benign probe in a disposable environment reading a sentinel file outside the sandbox directory. |
| 4 | Can a dataset `editor` grant itself `owner`? | Mutating. The guard's absence is visible in source; no upstream constraint was found. | `POST /api/datasets/{id}/access/grant {"role":"owner"}` as an editor → expect 403. |

---

## Contradictions between sources that were not resolved

| # | Question | Evidence |
| --- | --- | --- |
| 5 | **What fraction of the Node suite is source-text-only — 37% or 57%?** The main agent measured **20 of 54** using a strict criterion (`readFileSync` present, no `await import(` / `transpileModule` / `pathToFileURL`). The testing lane counted **31 of 54** using broader criteria that also excluded `fetch(` and `execFileSync`. | Both are defensible; they classify the 11 "mixed" files differently. Settle it by defining the criterion in a CI check and letting it produce the number. The conclusion — a large fraction proves little — holds under either. |
| 6 | Do the 15 Parquet files under `artifacts/scoring_runs/` mean the scoring path *does* use a columnar format while the dataset path does not? The scalability lane reported "0 parquet files"; the main agent found 15, all under `scoring_runs/`, and **0 under `datasets/`**. | The lane's specific claim (`find server/artifacts/datasets -name "*.parquet"` → 0) is correct. The broader "no Parquet anywhere" framing is not. Worth confirming whether the scoring-run Parquet path could be reused for dataset artifacts. |
| 7 | The handoff states the near-zero-variance N+1 was fixed; the code shows it is not. **Was a different N+1 fixed?** | The single-pass aggregate at `governed_profile_service.py:351-355` *is* a real vectorization — of missingness and distinct counts. The claim is probably about that work, applied to the wrong feature in the summary. |

---

## Behaviour that needs a runtime trace

| # | Question | What would settle it |
| --- | --- | --- |
| 8 | **Two parallel dataset ACL systems exist** — the JSON registry (`owner/editor/viewer/auditor`) and the SQLite `resource_permissions` table (`view…admin`). Which is authoritative per endpoint, and can a grant in one be invisible to the other? | Grant access in each store for the same `dataset_id` and trace which is consulted by `require_dataset` vs `SharingService.check_permission`. |
| 9 | Does `renderReportContentHtml` sanitize its input? If not, the `dangerouslySetInnerHTML` sink is stored XSS reachable via cross-tenant-writable documentation. | Locate the function (not found by grep in `src/lib/`) and read it; or store `<img src=x onerror=alert(1)>` in a documentation section and render the report. |
| 10 | **Does DuckDB 1.5.5 spill to disk here, or hard-fail?** The projected OOM wall at ~10–12M rows assumes no spilling (in-memory DB, no `temp_directory`, no `memory_limit`). If it spills, the wall becomes a severe slowdown instead of a crash. | Profile a 10M-row fixture and observe whether the process OOMs or degrades. |
| 11 | What **caused** the 312 dangling foreign keys, given `ON DELETE CASCADE` is declared and `PRAGMA foreign_keys = ON` is issued on every connection? | Candidates: writes through a connection that bypasses `Database.connect` (e.g. `scripts/migrate_legacy_project_access.py`), or deletes performed outside the app. Instrument and reproduce. |
| 12 | Could dataset row content appear in a traceback rendered into `uvicorn.err.log`? The failing frame is `pd.read_json(json.dumps(payload))`. | Deliberately **not** dumped during this audit. Review the committed log's traceback frames for `locals` rendering. |

---

## Claimed but unmeasured

| # | Question | Status |
| --- | --- | --- |
| 13 | **What is the real concurrency envelope?** Every number in §5.4 of the scalability deliverable is *projection* from a measured serialization constant (19.39 s cold, verified) plus a structural argument. | The repository's own performance report states concurrency under real thread contention was **never load-tested**. The `/api/health`-during-load test is the one that matters. |
| 14 | Is threadpool saturation really at 25–40 users? | Depends on AnyIO's default (40) being unchanged — verified — and on per-user request patterns. Measure directly. |
| 15 | Does the frontend's optimistic project-mirror actually diverge in practice? The mechanism is confirmed (browser-first write, debounced fire-and-forget mirror, 404-on-missing guard); the divergence counts (127 SQLite / 36 linked / 112 evidence) are consistent with it but have other explanations. | Fault-inject a failing `PUT /api/projects/{id}` and observe whether the UI still allows the user to proceed. |
| 16 | Is the 82.4 MB dataset **actually** the Kaggle Credit Card Fraud dataset? The schema (`Time,V1..V28,Amount,Class`), row count (170,885), and PCA-component naming match, and the handoff describes `V1`–`V28` as PCA components. | Not confirmed against the original distribution. It matters because the licence restricts redistribution — worth confirming before any external repository sharing. |

---

## Scope not covered by this audit

| # | Area | Why |
| --- | --- | --- |
| 17 | The **other four workflows** — Experimental Design, Optimization, Time Series, LLM — were mapped but not audited in depth. The Predictive Modeling lifecycle was the brief's focus. | Time Series and LLM pages were observed rendering from **static demo data** (`timeSeriesDemoData.ts`, `llmDemoData.ts`), including a hardcoded ±10% band labelled a "90% prediction interval". That warrants its own review before those workflows are shown to a customer. |
| 18 | **Statistical correctness of the ML itself** — trainer, calibration, SHAP, RFE, credit-risk scorecard scaling. | Only IV/WOE/Wilson and the regression metrics were examined. The scorecard scaling math has **no behavioral test** (its 295 assertions are source-text). An independent numerical review is warranted. |
| 19 | **Front-end bundle behaviour under a real browser profile** — actual memory growth, render timings. | Static analysis and `dist/` inspection only; no browser profiling was run. |
| 20 | **Whether any of this has been exploited.** | Out of scope, and the audit trail could not answer it reliably in any case: two divergent trails (~3,900-event gap), no tamper-evidence, and header-forgeable attribution. |

---

## The most important open question

**Question 13.** Every P0 in the security, lifecycle, and persistence domains is verified — most of them live, against the running system. The scalability P0s are verified *structurally* (the lock, the N+1, the missing `Deadline`, the absent Parquet) and one is verified *numerically* (19.39 s cold). But the headline conclusion — *"the platform stops serving all traffic somewhere between 10 and 40 concurrent analytical users"* — rests on a projection.

It is a well-founded projection: a single process-wide lock held for ~19 s, on sync handlers, occupying a 40-slot shared threadpool, with a governor that is never called. But **it has never been measured**, and the repository's own performance report says so explicitly.

**If one test is added before a pilot, make it the concurrency ramp with a `/api/health` probe running throughout.** It either confirms the most consequential claim in this audit or refutes it, in under an hour.

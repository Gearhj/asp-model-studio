# 04 — Scalability and Performance

**Method:** static analysis of the analytical path, archaeology of measurements already recorded in the repository, and **one live benchmark run by the main agent against the running backend**. Measured values and projections are kept strictly separate.

---

## 1. Hardware context — read every number against this

| Item | Value |
| --- | --- |
| CPU | Intel Core i7-4790 @ 3.60 GHz — **4 cores / 8 threads, 2014 silicon** |
| RAM | 31.9 GiB |
| Disk | ≈ 631 GiB free |
| Backend | single uvicorn process, no `--workers` flag anywhere in the repo |

A modern 32-core server would materially improve the absolute numbers below. It would **not** change the structural limits in §5, which are serialization and memory-shape problems, not clock-speed problems.

---

## 2. MEASURED — live benchmark (this audit)

Governed target profile of CLASS_TRAIN (170,884 × 31, 30 predictors), via `POST /api/data/target-profile`:

| Run | Wall clock | Server-reported | Cached |
| --- | --- | --- | --- |
| Phase 1 (`include_iv=false`) | 0.21 s | 0 ms | **true** (pre-warmed) |
| **Phase 2 (`include_iv=true`) — COLD** | **19.39 s** | **19,215 ms** | **false** |
| Phase 2 repeat — warm | **0.09 s** | — | true |
| Phase 1 repeat — warm | 0.30 s | — | true |

**Reconciliation verified in the same responses:** `populationRows=170884`, `columnCount=31`, `duplicateRows=52`, `columnsWithMissingValues=29`, `eventCount=360`. These match the authoritative figures exactly.

**Findings from the measurement:**

1. **The handoff's ~15 s estimate is confirmed and slightly exceeded — 19.4 s cold on this hardware.**
2. **The cache works extremely well** — a 215× speedup (19.39 s → 0.09 s). Warm-path performance is not a concern.
3. **The reported `datasetScans: 1` is misleading.** It counts artifact reads, not SQL statements. Static analysis shows ~187 statements, ~185 of them full scans of the materialized table.

---

## 3. MEASURED — numbers already recorded in the repository

Sourced from module docstrings and `docs/architecture/PERFORMANCE_AND_CONCURRENCY_REPORT.md`. Cited, not re-derived.

| Measurement | Value | Source |
| --- | --- | --- |
| `pd.read_csv` of CLASS_TRAIN (82.4 MB) | ~4.6 s | `target_distribution_service.py:11` |
| pandas full profiling, same asset | ~4.0 s | `target_distribution_service.py:10-11` |
| DuckDB 1-column GROUP BY, cold, **over CSV** | **~1.3 s** | `target_distribution_service.py:19` |
| Same **over Parquet** | **~0.13 s** | `target_distribution_service.py:19-20` |
| Parquet 1M × 20 histogram (20 bins) | 168.8 ms | perf report |
| Parquet 1M × 20 exact quantiles | 487.1 ms | perf report |
| Parquet 5M × 20 histogram | 569.3 ms | perf report |
| Polars schema page, 1,000 cols | 63.1 ms | perf report |
| **Concurrency under real thread contention** | **never measured** | perf report:77 (explicit) |

> The Parquet figures describe a code path **this deployment cannot reach** (§4.1). They are the achievable ceiling, not current behaviour.

---

## 4. Structural findings

### 4.1 The entire Parquet fast path is dead in this deployment — **VERIFIED**

Every resolver prefers Parquet (`governed_profile_service.py:153`, `artifact_resolver.py:78-81`, `target_distribution_service.py:93-95`). Main-agent verification:

```
find server/artifacts/datasets -name "*.parquet"   →  0 files
grep -c "analyticalParquetPath" registry.json      →  0 occurrences
```

(15 Parquet files exist, but all under `artifacts/scoring_runs/` — none is a dataset artifact.)

`materialize_parquet_for_version` is reachable only via an endpoint no frontend code calls. **Every analytical request therefore pays a measured 10× format penalty and a ~4.3× memory penalty** that one unclicked button would remove.

Compounding: the scan is `read_csv(..., all_varchar=true)`, so every cell is stored as a VARCHAR string (~35 B/cell vs ~8.15 B/cell for a typed Parquet DOUBLE), and every numeric operation re-parses it via `TRY_CAST` — roughly 20.5 M string→double parses per profile.

### 4.2 The N+1 the handoff reports as fixed is **still present** — VERIFIED

```python
# server/preprocessing/governed_profile_service.py:381-389 — verbatim
for column in columns:
    if str(column) in constant_columns or str(column) == target: continue
    c = _q(column)
    top = session.one(
        f"SELECT COUNT(*) FROM src WHERE {c} IS NOT NULL GROUP BY CAST({c} AS VARCHAR) ORDER BY COUNT(*) DESC LIMIT 1"
    )
```

One full-table hash aggregate **per column** for near-zero-variance detection. The vectorization that was applied covers *missingness and distinct counts* (`:351-355`), not this.

**Statement count per profile = `C − K + 6 + 5E`.** For CLASS_TRAIN (C=31, E=30): **187 statements, ~185 full scans.** At 1,000 columns: 6,001 statements.

### 4.3 Everything is serialized behind one process-wide lock

`_QUERY_LOCK = threading.Lock()` (`governed_profile_service.py:99`) is acquired at `:747` and held across artifact materialization, target mapping, quality, and the entire IV loop until `:792` — **the full ~19 s**.

The route is a **sync `def`**, so it occupies one of AnyIO's default **40** shared worker threads for that whole period. The per-user/per-project concurrency governor `CONCURRENCY.try_acquire` has **exactly one call site in the codebase** — verified — and it is *not* this path.

### 4.4 There is no timeout enforcement anywhere — VERIFIED

`grep -rn "Deadline(" server` returns **zero hits**. The `Deadline` class is defined and never instantiated. `timeoutSeconds` is accepted by the query contract, passed into `PlannerInputs`, and never read by the planner. `max_query_duration_seconds` is only echoed by a diagnostics endpoint.

**No analytical request in ATLAS has an upper time bound.**

### 4.5 Three of four DuckDB connection sites bypass resource governance

Only `engines/duckdb_engine.py:42-60` applies `SET memory_limit` and `SET threads`. The governed profiler (`:222`), target distribution (`:149`, `:176`), and target intelligence (`:632`, `:700`) all use a bare `duckdb.connect()` — **DuckDB defaults: memory limit 80% of RAM, all cores, and for an in-memory DB with no `temp_directory`, no spilling.** The failure mode at scale is an unhandled OOM inside the lock, not graceful degradation.

### 4.6 A silent cache cliff at ~445 columns

`_MAX_ENTRY_BYTES = 2_000_000` (`result_cache.py:20`). `set()` computes `len(json.dumps(value))` and **returns silently** when it exceeds. The profile emits one unbounded entry per column in both `predictors` and `missingness`.

At ~4.5 KB per predictor the ceiling is crossed at **~445 columns**. Above that, every request is a permanent cache miss paying the full cold cost forever — and **nothing in the response, logs, or diagnostics reveals that caching has stopped.** Given the measured 215× warm speedup, this cliff is severe.

### 4.7 Unbounded endpoints

- `GET /api/eda/sample?max_rows=` — no `ge`/`le`, then `df.head(max_rows).to_dict(orient="records")`. `?max_rows=99999999` serializes the whole population (~170 MB of JSON in server RAM).
- `GET /api/data/get_sample?max_rows=` — identical defect.
- `GET /api/eda/correlation` — full O(C²) matrix, no column cap (~20 MB at 1,000 columns, ~500 MB at 5,000).
- One unbounded `fetchall()`: categorical binning (`governed_profile_service.py:541-544`) has **no `LIMIT`**; truncation to 20 categories happens in Python afterwards. The sibling module `target_intelligence_service.py:695-710` does this correctly with a `COUNT(DISTINCT)` guard and a 422 — the pattern exists and was not applied here.

### 4.8 The 923 MB checkpoint is a per-request cost

`.runtime/workflow_checkpoint.json` = **923,653,366 bytes** (verified) is rewritten in full on a 2-second debounce from 20 call sites, including every dataset activation. It also gates startup: `load_checkpoint` must parse it before the server serves its first request. A dead 114 MB `.pkl` sits beside it.

---

## 5. Envelopes

### 5.1 Extrapolation model (arithmetic shown)

Anchored on the **measured 19.39 s**. Work is O(rows × columns) because statement count is linear in C and every statement is a full scan.

```
k = 19.39 s / (170,884 rows × 31 cols) = 3.66 × 10⁻⁶ s per cell-profile  ≈ 273,000 cell-profiles/s
Memory = rows × cols × 35 bytes   (all_varchar materialization)
```

**Assumptions, stated so they can be falsified:** DuckDB hash aggregates stay linear in R until memory pressure; per-cell cost is independent of C while the table fits in RAM; all predictors are numeric quantile-binned; no memory limit is set (true — §4.5), so DuckDB uses all cores.

### 5.2 Depth (C = 31, cold, CSV)

| Rows | Projected cold profile | Peak DuckDB memory | Verdict |
| --- | --- | --- | --- |
| **170,884** | **19.4 s (MEASURED)** | 185 MB | works; already 6× over an interactive budget |
| 1,000,000 | ~113 s | 1.09 GB | browser/proxy timeouts; nothing server-side stops it |
| 5,000,000 | ~9.5 min | 5.43 GB | lock held 9 minutes |
| 10,000,000 | ~19 min | **10.9 GB** | **OOM on a 16 GB host** |
| 50,000,000 | ~1.6 h | 54.3 GB | not reachable |
| 100,000,000 | ~3.2 h | 108.5 GB | not reachable |
| 1,000,000,000 | ~32 h | 1.09 TB | not reachable |

**With Parquet materialized** (~10× faster, ~4.3× less memory): 1M ≈ 11 s, 10M ≈ 113 s / 2.5 GB, 100M ≈ 19 min / 25 GB. **One unclicked button moves the ceiling by an order of magnitude on both axes.**

### 5.3 Width (R = 170,884)

| Columns | Statements | Projected | Peak memory | Cached? |
| --- | --- | --- | --- | --- |
| 31 | 187 | 19.4 s (measured) | 185 MB | yes |
| 100 | 601 | ~63 s | 598 MB | yes |
| **445** | 2,671 | ~4.6 min | 2.66 GB | **cliff** |
| 1,000 | 6,001 | ~10.4 min | 5.98 GB | **never** |
| 5,000 | 30,001 | ~52 min | 29.9 GB | never |

Plus, in a **single statement**, the C-way simultaneous `COUNT(DISTINCT)` at `:351-355`: ~5.5 GB at C=1,000, ~27 GB at C=5,000. The optimization that removed one N+1 concentrated its memory into one operator.

**Ingress is inconsistent:** `/api/data/upload_csv` enforces 500k rows / 750 columns; the **Dataset Library upload — the path that produces governed artifacts — enforces only a 250 MB size cap.** The less-guarded path is the governed one.

### 5.4 Concurrency (CLASS_TRAIN, cold)

One panel mount = two phases ≈ **27 s of lock-held work per user** (the `include_iv` flag is part of the cache key, so phase 1 and phase 2 are separate keys and both run `compute_quality` — ~34% pure duplication).

| Concurrent users | Mean latency | p100 | Threadpool slots | Verdict |
| --- | --- | --- | --- | --- |
| 1 | 27 s | 27 s | 1–2 / 40 | slow but functional |
| 5 | 81 s | 135 s | 5–10 / 40 | users assume it is broken |
| 10 | 149 s | 270 s | 10–20 / 40 | unusable |
| **25** | 351 s | **11 min** | **25–40 / 40** | **threadpool saturated — `/api/health` stops answering** |
| 50 | 11.5 min | 22.5 min | 40/40 + queued | platform down |
| 100 | 23 min | 45 min | 40/40 + queued | platform down |

> **This is the single most important scalability result in the audit.** The failure is not "profiling is slow" — it is that blocked profiling requests consume the shared threadpool until **every sync endpoint in ATLAS stops responding**. The platform does not degrade; it stops.

---

## 6. What fails first, in order

| # | Failure | Trigger |
| --- | --- | --- |
| **1** | **Threadpool starvation — entire API unresponsive** | ~25–40 concurrent workflow users |
| 2 | Result cache silently disabled | > ~445 columns |
| 3 | Checkpoint write memory spike | **already happening** — 923 MB, saves failing |
| 4 | DuckDB OOM (no limit, no spill) | ~10–12M rows × 31 cols on 16 GB |
| 5 | `_DATASTORES` unbounded growth | ~40–100 (user, project) scopes |
| 6 | Unbounded `fetchall` on a high-cardinality categorical | first real dataset with an ID column |
| 7 | O(C²) correlation payload | 500+ numeric columns |
| 8 | `database is locked` on the security DB | sustained multi-user load (journal_mode=`delete`, verified) |
| 9 | `registry.json` read-modify-write races | concurrent registrations |

Note that CLASS_TRAIN's all-numeric schema is why #6 has not surfaced yet.

---

## 7. Local vs enterprise architecture

**What must change to move the ceiling, in dependency order:**

1. **Materialize Parquet at registration.** Largest single win — measured 10× time, 4.3× memory. Purely additive.
2. **Fold near-zero variance into the existing single-pass aggregate.** Removes ~30 of 33 quality queries at C=31, ~999 at C=1,000.
3. **Replace the global lock with the existing `CONCURRENCY` governor** and move profiling onto the `run_async` job pattern the codebase already implements — so the HTTP thread is released and over-limit callers get a 429 instead of a thread.
4. **Instantiate `Deadline`.** The class exists; use it.
5. **Route all four DuckDB sites through `open_bounded_connection`** and set `temp_directory` so large sessions spill rather than OOM.
6. **Paginate `predictors`/`missingness`** so the cache cliff cannot be reached.
7. **Fix the checkpoint** (see [05-persistence-jobs-and-recovery.md](audit-output/05-persistence-jobs-and-recovery.md)) — it is a per-request cost today.

Beyond that, enterprise scale requires what any single-process architecture requires: multiple app instances behind a shared cache (the current cache is process-local), object storage for artifacts, a real queue for heavy analytics, and PostgreSQL in place of SQLite.

---

## 8. Recommended scale-test harness

Drive over HTTP against a real uvicorn process — in-process TestClient makes T7/T8 meaningless.

| # | Test | Threshold |
| --- | --- | --- |
| T1 | Statement count per profile (instrumented `_Session`) | ≤ `2E + 12`; **fails today at 187** |
| T2 | Artifact parses per panel mount | 1; **currently 2** |
| T3 | Cold/warm latency | cold ≤ 5 s at 170k×31 (**19.4 s today**); warm ≤ 250 ms (**0.09 s — passes**) |
| T4 | CSV vs Parquet delta | Parquet ≥ 5× faster |
| T5 | Peak RSS during one profile | ≤ `R × C × 40 B` |
| T6 | Cacheability at C=500 | second request `cached: true`; **fails today** |
| T7 | Concurrency ramp 1/5/10/25/50 | p95 < 3× single-user; **≈ N× today** |
| **T8** | **`/api/health` during T7** | **p99 ≤ 250 ms throughout — the most important test in the harness** |
| T9 | Cancel releases the lock | next request starts < 500 ms |
| T10 | Timeout enforcement | 504 within the configured bound; **no bound exists today** |
| T11 | High-cardinality categorical | RSS delta ≤ 100 MB or 422 |
| T12 | Cross-project EDA cache isolation | correct `projectId`; **fails today** |
| T13/T14 | Correlation and `max_rows` caps | bounded payload / 422 |
| T15 | Checkpoint size and write duration | ≤ 25 MB, ≤ 2 s; **923 MB today** |
| T16/T17 | Audit-write contention; registry write race | zero `database is locked`; no lost updates |

Gate CI on T1, T2, T6, T8, T12, T14 — cheap, deterministic, and each pins one finding above.

---

## 9. Verdict

**Warm-path performance is genuinely good** (0.09 s, 215× cache speedup) and the bounded-response discipline is real and broadly applied. The cold path is 19.4 s for a 170k-row dataset on 2014 hardware, and the limits are structural rather than hardware-bound.

**The current tested scale is one user.** Concurrency has never been measured — the repository's own performance report says so explicitly. Everything in §5.4 is projection from a serialization constant, and the honest summary is: **ATLAS today is a single-analyst system that will stop serving all traffic somewhere between 10 and 40 concurrent analytical users.**

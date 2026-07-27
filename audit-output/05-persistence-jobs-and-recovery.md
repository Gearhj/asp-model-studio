# 05 — Persistence, Jobs, and Failure Recovery

**Method:** static review plus **read-only live inspection** of both SQLite databases (`mode=ro` URI, `SELECT`/`PRAGMA` only) and the artifact tree. Every measured number below was independently re-run by the main agent.

---

## 1. Headline

ATLAS has **eight independent durable stores and no transaction, reconciliation, or backup mechanism spanning them.** Three governance-critical facts are dual-written with no shared transaction, and **all three have already measurably diverged in the live environment.**

The live database contains **312 dangling foreign-key references** — verified — and **no code anywhere runs an integrity check**.

---

## 2. Persistence inventory

| Store | Location | Live state | Restart-safe |
| --- | --- | --- | --- |
| Application SQLite | `server/data/atlas_local.db` (27.3 MB, 60 tables) | 127 projects, 245 users, 189 evidence, 15 scoring runs | Yes — **WAL verified** |
| Security SQLite | `server/artifacts/security/atlas_security.db` (2.6 MB) | 200 users, 9,136 audit events, sessions | Yes — **`journal_mode=delete` verified** |
| Dataset registry | `registry.json` (88.5 KB) | 43 datasets | Yes |
| Project links | `project_links.json` | 44 links | Yes |
| Dataset artifacts | `artifacts/datasets/**` | **332 MB** of CSVs | Yes |
| Evidence JSON | `evidence_registry.json` + `items/` (44 MB) | 227 index / 203 files | Yes |
| Other JSON registries | credit_risk, notebooks, MDD, analytics, scoring_runs | — | Yes |
| **Checkpoint** | `.runtime/workflow_checkpoint.json` | **923,653,366 bytes** | **Currently failing — §5** |
| In-process | `DATASTORE`, `RESULTS`, `TRAINING_JOBS` | — | Lost (partly via checkpoint) |
| Browser | `localStorage` / `sessionStorage` | ~20 unscoped keys | Per-browser only |

**Connection management.** `BaseRepository` opens a **brand-new connection per statement** and closes it ([base_repository.py:12-26](server/persistence/repositories/base_repository.py#L12-L26)). One API call touching five repositories opens five connections and runs five independent transactions. Thread-safe by construction — at the cost of **no cross-repository atomicity**.

**The two databases are configured very differently — verified live:**

| | `atlas_local.db` | `atlas_security.db` |
| --- | --- | --- |
| `journal_mode` | **`wal`** ✓ | **`delete`** ✗ |
| `busy_timeout` | 10,000 ms ✓ | not set (5 s default) ✗ |

The security database is in rollback-journal mode **and receives a write on every authenticated request** (`UPDATE sessions SET last_seen_at`). In `delete` mode a writer takes an EXCLUSIVE lock that blocks all readers. **This is the first place `database is locked` will appear under concurrency — and it fails *authentication*, surfacing as an unhandled 500 on every endpoint.**

**Migrations.** 15 `.sql` files applied in lexicographic order with a `schema_migrations` table. Applied via `connection.executescript`, which issues an implicit `COMMIT` before running — so **a migration failing partway leaves its earlier statements permanently committed with no `schema_migrations` row.** Migrations `0012` and `0013` are bare `ALTER TABLE ADD COLUMN` statements, which raise `duplicate column name` on re-run. The next boot then raises `PersistenceUnavailableError`, which `main.py:169-171` catches and **`print()`s — the app boots with a dead database while `/api/health` still returns 200.** There are **no down-migrations**.

**Every JSON registry is a lock-free read-modify-write.** Worse, the "atomic" helper uses a **fixed** temp filename (`registry.json.tmp`), so two concurrent writers open the same temp file, interleave bytes, and both `replace()` it — publishing genuinely corrupt JSON, not merely a lost update. (`session_checkpoint.py:484` gets this right with a `uuid4` temp name; the registries do not.) Several stores (`evidence_store.py:57-59`, `analytics_store.py:38-40`, credit-risk) use a **naive in-place truncate** with no temp file at all.

Every reader then swallows parse errors and returns an empty default — so a corrupt registry **reads as empty and the next save persists that emptiness**, permanently destroying the index.

---

## 3. Source-of-truth map — measured divergence

| Fact | Store A | Store B | **Measured divergence** |
| --- | --- | --- | --- |
| Audit event | `audit_events` (9,136) | `audit_log` (5,466) | **~3,900 A-only, ~267 B-only** |
| Evidence | JSON (227 index / 203 files) | `evidence_artifacts` (189) | only ~126 IDs common; **53 index rows with no file; 29 files not indexed** |
| Dataset↔project link | `project_links.json` (44) | `registry.json.linkedProjects` (34) | **10 links in A only** |
| User | security DB (200) | app DB (245) | **45-user gap** |
| Project record | **`localStorage` (primary)** | `projects` table (best-effort mirror) | 127 rows vs 36 linked vs 112 evidence projects |
| Dataset catalogue | `registry.json` (43) | `datasets` table (**0 rows**) | table B has no writer |
| Model version | — | `model_versions` (**0 rows**) | **artifact root does not exist** |

**Browser-only facts with no server equivalent** — a distinct and serious class:
workflow-node evidence · experiment tracking · **analyst-authored Python/SAS code** · **credit-bureau special-value treatments** (FCRA/ECOA-relevant) · enterprise data-access metadata · split strategy / balance method / k-folds (bare global keys) · evaluation review and proposed operating policy.

**Sign-out clears almost none of it.** `auth.ts:52` calls `clearUserDatasetState()`, which sweeps only `atlas:modeling-dataset:*` in **sessionStorage**. Every `localStorage` key above survives sign-out and is readable by the next user of the same browser profile.

---

## 4. Transactions and concurrency

**There is no cross-store transaction boundary anywhere.** Representative crash windows:

- **Dataset registration** (7 sequential effects): dying between the CSV write and the registry save leaves an **orphan directory with a full CSV copy, invisible to every listing and never garbage-collected** — there is no dataset delete endpoint at all, only archive. And re-uploading the same file creates a *second* dataset: three copies of CLASS_TRAIN exist live (`_982c7a7d`, `_982c7a7d_35930`, `_982c7a7d_98716`).
- **Model version save** (5 effects, 3 transactions): `next_version_number()` is a `SELECT MAX(...)` in its own connection followed by a separate `insert`, and `model_versions` has **no `UNIQUE(model_id, version_number)`** — two concurrent saves produce duplicate version numbers.
- **Project deletion** (9 effects across 5 stores): nothing cleans JSON evidence, analytics insights, credit-risk profiles, notebooks, MDD documents, `resource_permissions`, `share_links`, or `sharing_events`.

**A deleted project can be resurrected with its old grants.** `save_workflow_state` authorizes with `allow_missing=True`, which returns without any permission check when the project is absent, then calls `ensure_project` — which **creates the row**. The 59 dangling `resource_permissions` and 17 dangling `project_collaborators` rows would become live grants again.

### Verified integrity state

```
PRAGMA foreign_key_check on atlas_local.db → 312 violations
  decision_journal    → projects : 182
  evidence_artifacts  → projects : 113
  project_collaborators → projects : 17
```

All three tables declare `ON DELETE CASCADE` and `PRAGMA foreign_keys = ON` is issued on every connection — yet the violations exist. Enforcement is not end-to-end, and **nothing monitors it**.

---

## 5. The checkpoint — a live, unreported failure

**Verified in `uvicorn.err.log`:**

```
147: Workflow checkpoint is critically large: 236674128 bytes (critical threshold 104857600)
234: Failed to save workflow checkpoint: TypeError('Object of type int64 is not JSON serializable')
235: ... 400499872   322: Failed to save ...   323: ... 564325616
410: Failed to save ...   411: ... 728151360   498: Failed to save ...   499: ... 891977104
```

Growth is **exactly +163,825,744 bytes per additional scope**. On-disk: **923,653,366 bytes** — 8.8× the critical threshold — plus a dead **114 MB** `.pkl` beside it.

**Three compounding defects:**

1. **The write fails.** `json.dumps(payload, indent=2, sort_keys=True)` has **no `default=` handler** (verified), and `target` / `training_timestamp` bypass `_encode()`. One numpy scalar aborts the save for **all 32 scopes at once**.
2. **Failure is invisible.** The failure logs at WARNING and returns `False`; `schedule_checkpoint_save` returns `True` unconditionally and is fire-and-forget. **No API response and no user ever learns that draft state was not persisted.**
3. **The guard is decorative.** `CHECKPOINT_SIZE_CRITICAL_BYTES` is documented as log-only: *"Thresholds NEVER discard state."*

**Consequence:** the checkpoint is the **only** durable path for training results (the job system deliberately does not persist itself, on the explicit grounds that "RESULTS is that durable path"). When the checkpoint fails, that path does not exist and completed training results are lost on restart.

---

## 6. Job system

**Training** runs as bare `daemon=True` threads inside the API process. No queue, no broker, no persistence — all state lives in module-singleton dicts. A second, fully synchronous path (`POST /model/train`) still exists that blocks an HTTP worker for the whole fit and **cannot be cancelled**.

**On restart the job simply ceases to exist** — 404, not resumed, not marked failed. This is the honest option and it is **VERIFIED BY TEST** (`modeling_state_characterization_test.py::test_interrupted_training_job_does_not_resume_as_running_after_restart`).

**Job ownership is captured and enforced** — `owner_user_id` and `project_id` on every record, checked on every accessor, verified by two named tests. **This is the strongest part of the job system.**

**Cancellation is cooperative only.** The event is checked before and during preparation, but `train_models(...)` is a single uninterruptible call — a long grid search runs to completion after "cancel" while the UI reports cancelled. Scoring cancellation is documented in-code as non-functional.

**Duplicate submit is not prevented.** No idempotency key, no in-flight guard. Both jobs capture the *same* `ResultStore` instance and both call `set_last_summary` — **last writer wins and one job's results are silently destroyed.**

### The model registry has never persisted a model — VERIFIED

`models` = 0 rows · `model_versions` = 0 rows · **`server/artifacts/model_registry/` does not exist** · all 15 scoring runs `model_version_id IS NULL`.

The sole write path is wrapped in `except Exception: return None` and the caller treats `None` as normal, still returning `{"ok": true}`. **"Save Final Model" has been reporting success while persisting nothing.** After any restart, `RESULTS.final_model` is `None` and the documented fallback has no artifact to load — **scoring is permanently broken until the model is retrained**, which requires the dataset and splits, which live only in the failing checkpoint.

---

## 7. Failure matrix

| Condition | Behaviour | Status |
| --- | --- | --- |
| Frontend refresh | Store rehydrates from sessionStorage; job pointer re-read from an **unscoped** key | VERIFIED for registry/context; **UNVERIFIED** for the job pointer |
| Sign-out / different user | Only the dataset key is cleared; everything else persists | PARTIALLY VERIFIED — and untrue for every other key |
| Restart mid-profiling | Orphan version directory, no registry entry, no cleanup | UNVERIFIED |
| Restart mid-training | Job vanishes cleanly (404, no false resume) | **VERIFIED BY TEST** |
| Interrupted scoring | Not interruptible; orphan Parquet possible | UNVERIFIED |
| Duplicate submit | Two jobs, shared ResultStore, one result destroyed | UNVERIFIED — no idempotency test |
| Stale browser response | Project Context has a revision check — but it is **TOCTOU** (separate GET, not a conditional PUT). Every other endpoint is last-write-wins | VERIFIED for the happy path only |
| Artifact missing | Scoring → 409; dataset → silent default; evidence → 404 while still listed (53 live cases) | UNVERIFIED |
| SQLite locked | app DB → 503 after 10 s, no retry; security DB → unhandled 500 | UNVERIFIED |
| **Corrupt JSON registry** | **Reads as empty; next save persists the emptiness — permanent destruction** | UNVERIFIED (server); the *browser* registry correctly quarantines |
| **Corrupt checkpoint** | **Fails safe — no partial restore, file untouched** | **VERIFIED BY 3 NAMED TESTS** |
| Low disk | Checkpoint survives (verified by test); naive JSON writers corrupt in place | PARTIALLY VERIFIED |

---

## 8. Retention, deletion, orphans

**There is no retention policy, no TTL, no purge job, and no orphan sweeper anywhere.** `scoring_runs.retention_policy` is always written as `'standard'` and read by nothing. Datasets have **no delete path at all** — 332 MB of CSVs are retained forever.

**Measured orphans:**

| Orphan | Count |
| --- | --- |
| `decision_journal` → deleted project | **182** |
| `evidence_artifacts` → deleted project | **113** |
| `project_collaborators` → deleted project | **17** |
| `resource_permissions` with no live project | **59 of 176** |
| `project_links.json` → deleted project | **13 of 44** |
| Evidence index rows with no file | **53** |
| Evidence files not in the index | **29** |
| `scoring_runs` with `project_id = NULL` | **12 of 15** |
| Stale per-process security DBs in `server/data/` | **36 files** (verified) |
| Dead `workflow_checkpoint.pkl` | **114 MB** (verified) |

**Can you delete something another user depends on? Yes, three ways.** The JSON evidence router has **no authorization at all** — `DELETE /api/evidence/{id}` deletes any item by ID (confirmed live in [03-security-and-isolation.md](audit-output/03-security-and-isolation.md)). `archive_dataset` requires only dataset write access, not access to the consuming projects. Project deletion archives model versions and scoring runs other users' evidence references, with no dependency check and no notification.

---

## 9. Backup and recovery

**A correct backup must capture ≈ 1.31 GB across nine locations** — both SQLite files *with their WAL sidecars*, the 332 MB dataset tree, 44 MB of evidence, scoring Parquet, the JSON registries, the 923 MB checkpoint, and **each user's browser storage (not capturable server-side at all)**.

**Is a consistent point-in-time backup possible today? No.** Eight independent stores, no global write barrier, no quiesce endpoint, no maintenance mode, no shared transaction. SQLite's online-backup API and `VACUUM INTO` exist and are **used nowhere**. The two audit trails are already inconsistent by ~3,900 rows, so no snapshot can be internally consistent regardless of technique.

| Metric | Today |
| --- | --- |
| **RPO** | **Unbounded** — no scheduled backup exists |
| RPO for modeling drafts | 30 s best case; **∞ in practice** (saves failing) |
| **RTO** | **Undefined** — no restore procedure exists |
| Unrecoverable | fitted models (registry empty), all browser-only facts, ~3,900 audit events |

The only backup tooling, `scripts/reset_atlas_db.py`, copies **only `atlas_local.db`** — no WAL sidecars (risking a torn copy), no security DB (**the primary audit trail**), no artifacts, no checkpoint. `docs/PERSISTENCE.md` still describes ATLAS as browser-persistence-only. `docs/ARCHITECTURE.md` names the documented "backup" as a **developer's local folder sync**.

---

## 10. Findings

| ID | Sev | Title |
| --- | --- | --- |
| PJ-P0-1 | P0 | Checkpoint saves failing in production; 923 MB rewritten per request; failure invisible to callers |
| PJ-P0-2 | P0 | Model registry has never persisted a model; failure silently swallowed; scoring unrecoverable after restart |
| PJ-P0-3 | P0 | Two divergent audit trails; ~3,900 events in only one; second write is `except: pass` |
| PJ-P0-4 | P0 | Evidence split across three stores, already diverged; JSON evidence API has no authorization |
| PJ-P1-5 | P1 | Duplicate training submit creates two jobs sharing one result store |
| PJ-P1-6 | P1 | Project deletion is a 9-step non-atomic fan-out; deleted projects resurrectable with old grants |
| PJ-P1-7 | P1 | **312 dangling foreign keys live**; no integrity check exists anywhere |
| PJ-P1-8 | P1 | Migrations not atomic; a partial migration bricks every subsequent boot; no down-migrations |
| PJ-P1-9 | P1 | Every JSON registry is a lock-free RMW; "atomic" writers share a fixed temp filename |
| PJ-P2-10 | P2 | Browser is primary store for project/workflow state; DB write is a failure-swallowing mirror |
| PJ-P2-11 | P2 | Sign-out leaves the previous user's projects, decision journal, code, and treatments in the browser |
| PJ-P2-12 | P2 | Training and scoring cancellation are not real cancellation |
| PJ-P2-13 | P2 | Six durability paths swallow exceptions and return success-shaped results |
| PJ-P2-14 | P2 | Security DB uses rollback-journal mode with a write on every request |
| PJ-P2-15 | P2 | Frontend abandons a running training job on a single failed poll |
| PJ-P3-16 | P3 | No backup, restore, retention, or orphan cleanup; the one script captures ~2% of state |

Full detail is in [09-findings-register.csv](audit-output/09-findings-register.csv).

**The unifying theme:** six separate durability paths swallow exceptions and return success. Each is individually defensible ("durability is additive, never fatal"). Their combined effect is that **the API cannot distinguish "saved" from "not saved"** — which is precisely how an empty model registry and a ~3,900-row audit divergence reached this state undetected.

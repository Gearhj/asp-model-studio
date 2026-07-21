# ATLAS Predictive Modeling — Shared In-Memory State: Architecture Discovery & Staged Migration Plan

**Scope:** analysis and implementation planning only. No production code was modified while producing this document. This document is exhaustive but not omniscient — every claim below is anchored to a specific file and line range so it can be independently re-verified; anywhere the evidence was ambiguous, that ambiguity is stated rather than papered over.

---

## 1. Executive summary

ATLAS's classic modeling workflow (Data Acquisition → EDA → Outliers/Missing → Feature Engineering → Split → Train → Evaluate/Interpret/Score) is built on two module-level singleton stores, `DATASTORE` (`server/core/dataset_store.py`) and `RESULTS` (`server/core/result_store.py`), plus a third, fully global, unscoped store, `TRAINING_JOBS` (`server/training/training_job_service.py`).

The good news first: `DATASTORE` and `RESULTS` are **not** naïve global singletons. Both already route through a proxy (`DatasetStoreProxy`, `ResultStoreProxy`) that resolves a per-request scope key from `active_user()` — a `contextvars.ContextVar` set by `require_user()` from the session cookie on every authenticated request (`server/security/security_store.py:544-608`). That means two genuinely different authenticated users are already correctly isolated from each other in the common case. This is a real, working control, not a false sense of safety — it was verified by reading `require_user`'s cookie-to-user resolution path and the proxy's `_scope_key()`.

The actual problem is narrower and more specific than "everything is global": **the scope key is `user_id` only.** There is no `project_id`, `workflow_run_id`, `dataset_version_id`, or `training_job_id` dimension anywhere in `DATASTORE`/`RESULTS`. Concretely, this produces four confirmed failure modes, each traced to specific code:

1. **One user, two projects (same tab sequence or two browser tabs) silently clobber each other.** `POST /api/data/set_sample` (`server/core/metadata_router.py:94-156`), `POST /api/outliers/apply` (`server/preprocessing/outlier_router.py:59-88`), `POST /api/missing/apply`, and `POST /api/balancing_split/config` (`server/splitting/split_router.py:82-215`) accept **no project identifier at all** in their request bodies and unconditionally overwrite the single `DATASTORE.raw_df` / `.processed_df` / `.X_train…y_test` slot for that user. This is demonstrated, not inferred — the Pydantic models for every one of these endpoints were read in full (§3, §6).
2. **Training results are invisible to project collaborators and can be overwritten by a stale background job after the user switches projects.** `RESULTS` is user-scoped; a teammate with legitimate project access (per `SharingService`, see the FND-002 work in this same codebase) cannot see a colleague's trained model at all, because it lives in the colleague's private per-user `RESULTS` instance, never the project's. Separately, `training_job_service.py`'s background thread (`Thread(target=self._run, ...)`, line 178-183) captures `job["_result_store"] = RESULTS.current()` (line 167) **at job-creation time**, so a job that finishes after the launching user has switched to a different project silently writes Project A's results into whatever `RESULTS` slot that user is now using for Project B — because the store is keyed by user, not by project.
3. **A server restart collapses every user's in-memory session into one `"anonymous"` bucket, effectively for nobody.** `session_checkpoint.py`'s `load_checkpoint()` (lines 81-107) is called from `@app.on_event("startup")` (`server/main.py:149-160`), outside any request context, so `active_user()` is `None` and the proxy resolves to the literal `"anonymous"` scope. Whichever single scope was last checkpointed on save becomes the one restored, and it is not restored into any real user's session.
4. **Training jobs have no authorization check at all**, independent of the `DATASTORE`/`RESULTS` problem. `TRAINING_JOBS` (`server/training/training_job_service.py:539`) is a bare module-level object, not run through the user-scoping proxy pattern the other two stores use. `GET /api/model/train/jobs/active` returns every active job for every user (`training_job_service.py:213-216`), and `GET /api/model/train/jobs/{job_id}` / `POST /.../cancel` accept any `job_id` string with no ownership or project-membership check (`server/training/trainer_router.py:39-52`).

The right fix is **not** a single "add project_id everywhere" pass. Different artifact classes need different keys: transient working state (raw/processed frames, splits, in-progress preprocessing config) is legitimately per-*(user, project)*, because two collaborators editing the same project concurrently must not stomp each other's draft state either. But *committed* artifacts — trained models, the last training summary, the selected final model — belong to the *project*, not the user, so every authorized collaborator sees the same thing (§8).

This document inventories every read/write site (§3), traces what identity is and isn't available at each layer (§6), evaluates whether ATLAS already has a persistence mechanism fit for this (§8 — yes, partially, and it should be reused, not duplicated), and lays out nine independently-deployable migration stages (§10) starting from the smallest safe first step (§16): a scoping seam with zero behavior change, backed by tests that pin down today's actual behavior — both what already works and what doesn't — before anything is touched.

---

## 2. Definitions of all shared mutable stores

### 2.1 `DATASTORE` — `server/core/dataset_store.py`

```python
_DATASTORES: Dict[str, DatasetStore] = {}          # line 226

def _scope_key() -> str:                            # line 229-236
    user = active_user() or {}
    return str(user.get("userId") or "anonymous")

def get_scoped_dataset_store(scope=None) -> DatasetStore:  # line 239-243
    key = scope or _scope_key()
    if key not in _DATASTORES:
        _DATASTORES[key] = DatasetStore()
    return _DATASTORES[key]

DATASTORE = DatasetStoreProxy()                      # line 261, module-level singleton
```

`DatasetStoreProxy.__getattr__`/`__setattr__` (lines 246-257) transparently forward every attribute access to `get_scoped_dataset_store().<attr>` — so `DATASTORE.raw_df = df` and `DATASTORE.raw_df` both resolve the *current request's* user-scoped instance on every single access, not once per request. `DatasetStore` itself (lines 11-224) holds: `raw_df`, `processed_df` (pandas DataFrames), `target` (str), `X_train`/`X_test`/`y_train`/`y_test` (DataFrame/Series — the governed Step-6 split), and `meta: Dict[str, Any]` — a free-form dict used as a secondary store for `feature_manifest`, `outlier_application`, `missing_application`, `missing_config`, `split_record`, `split_config`, `split_status`, `selected_columns`, `materialized_feature_names`, `dataset_version`, `source`, `target_prevalence`, `bureau_review`, `active_training_job_id`. **Keyed by `user_id` only. Never evicted — `_DATASTORES` grows by one entry per distinct user (or `"anonymous"`) for the life of the process.**

### 2.2 `RESULTS` — `server/core/result_store.py`

Structurally identical pattern (`_RESULT_STORES` dict, `_scope_key()` — a byte-for-byte duplicate of `dataset_store.py`'s, lines 76-83 — `get_scoped_result_store`, `ResultStoreProxy`, module singleton at line 107). `ResultStore` (lines 6-70) holds: `last_training_summary`, `training_timestamp`, `model_availability`, `model_artifacts` (dict of model_key → fitted sklearn estimator/pipeline object or an RFE result dict), `model_artifact_metadata` (dict of model_key → provenance dict), `final_model` (single fitted-object slot), `final_model_metadata`, `scoring_reference` (a dict that can hold an entire uploaded scoring DataFrame plus a score array, `eval_service.py:2300`). **Same key (`user_id` only), same no-eviction behavior.**

### 2.3 `TRAINING_JOBS` — `server/training/training_job_service.py`

```python
TRAINING_JOBS = TrainingJobService()                 # line 539
```

`TrainingJobService.__init__` (lines 49-52) holds `self._jobs: dict[str, dict]` keyed by a `uuid4()`-derived `job_id` string, plus `self._cancel_events` and a single `threading.Lock`. **This is not scoped at all** — it is not routed through the `_scope_key()` pattern the other two stores use, and it is a genuinely global, process-wide dict shared by every user. `job_id` is unguessable (cryptographically random), so this is not trivially exploitable by brute force, but nothing checks that the caller of `GET /jobs/{job_id}` or `POST /jobs/{job_id}/cancel` (`server/training/trainer_router.py:39-52`) is the job's owner or a member of the job's project. `GET /jobs/active` (`training_job_service.py:213-216`, `trainer_router.py:34-36`) returns **every** active job for **every** user, unfiltered.

### 2.4 Other module-level state consulted and ruled out of scope

- `server/scoring/scoring_router.py`, `server/model_documentation/*`, `server/monitoring/*` — grepped for `DATASTORE`/`RESULTS`: **zero matches in all three.** These are already built on the SQLite persistence layer (`server/persistence/repositories/*`), which is project-scoped by design (see FND-001/FND-002 authorization work in this same codebase). They are correctly out of scope for this migration.
- `server/eda/workspace_service.py` has its own **in-memory result cache** separate from `DATASTORE`/`RESULTS`: `_key()` (lines 173-183) builds a `hashlib.sha256` cache key from `DATASTORE.meta.get("dataset_version"/"version_id")` and the feature manifest, used by `_cached()` (line 205). This cache key is derived from data that is itself only user-scoped, so it inherits the same cross-project collision risk one layer removed, and should be addressed in the same stage as `DATASTORE.meta` (§10, Stage 3).
- `TRAINER = TrainerService()` (`server/training/trainer_service.py:207`) is **stateless** — it holds only a class-level `MODEL_LABELS` dict computed once from `MODEL_CATALOG` (read-only, not mutated per-request). It is a thin facade over `DATASTORE`/`RESULTS` and needs no isolation work of its own.

---

## 3. Complete read/write inventory

Legend: **R** = read, **W** = write, **RW** = read-modify-write. "Ids in payload?" reports what was verified by reading the actual Pydantic request model or function signature — never inferred from the route name, per the investigation brief.

### 3.1 Data Acquisition — `server/core/metadata_router.py`, `server/main.py`

| Site | Endpoint | Object.attr | Data | R/W | Ids in payload? |
|---|---|---|---|---|---|
| `metadata_router.py:141` | `POST /api/data/set_sample` | `DATASTORE.set_raw(df)` | full uploaded DataFrame | W | `SetSamplePayload` (lines 77-82): `headers, rows, target, selected_columns, dataset_version`. **No project_id.** |
| `metadata_router.py:142-145` | same | `.meta["selected_columns"]`, `.meta["dataset_version"]`, `RESULTS.clear_model_artifacts()` | list[str], str, (clears all training artifacts) | W | — |
| `metadata_router.py:167-201` | `POST /api/data/set_target` | reads `.get_base_df()`; writes `.set_target`, `.processed_df=None`, pops manifest/split keys, `.meta["selected_columns"]`, `RESULTS.clear_model_artifacts()` | DataFrame; str; (invalidation) | RW | `SetTargetPayload` (lines 85-88): same fields, **no project_id** |
| `metadata_router.py:219-256` / `262-297` | `GET /api/columns`, `GET /api/data/get_sample` | `.get_active_df()`, `.target`, `.meta["selected_columns"]` | DataFrame, str, list | R | query params only, no ids |
| `main.py:165-228` | `POST /api/data/upload_csv` | `.set_raw(df)`, `.meta["selected_columns"]`, `.meta["source"]` | full uploaded DataFrame | W | no body fields besides the file; **no project_id** (this endpoint's own docstring calls itself a legacy/compat path — `Step01_DataAcquisition.tsx` uses `set_sample` instead) |

### 3.2 Preprocessing — Outliers, Missing Values

| Site | Endpoint | Object.attr | Data | R/W | Ids in payload? |
|---|---|---|---|---|---|
| `outlier_router.py:35,46,52-53` | `POST /api/outliers/summary` | `.get_raw_active_df()`, `.target`, `.meta["dataset_version"]`, `.meta["outlier_application"]` | DataFrame; str; str; dict | R | `OutlierSummaryRequest` — no ids |
| `outlier_router.py:59-88` | `POST /api/outliers/apply` | reads `.target`, `.meta["dataset_version"]`; writes `.set_processed(work)`, `.meta["processed_stage"]`, `.meta["outlier_application"]`, pops `.meta["missing_application"]`/`["missing_config"]`, sets `.meta["split_status"]="stale"`, mutates `.meta["feature_manifest"]["split_status"]` | DataFrame; provenance dict | RW | `OutlierApplyRequest` — no ids |
| `missing_router.py:44,74-93` | `_pre_missing_df` (internal, used by summary/apply) | replays the **stored `outlier_application` config dict** against a freshly re-derived source frame | dict (functionally a fitted-transform substitute, not just metadata) | R | n/a helper |
| `missing_router.py:143,176-178` | `GET /api/missing/summary` | `.target`, `.meta["outlier_application"]`, `.meta["dataset_version"]`, `.meta["missing_application"]` | str; dict; str; dict | R | query params only, no ids |
| `missing_router.py:234-252` | `POST /api/missing/apply` | reads `.meta["dataset_version"]`, `.meta["outlier_application"]`; writes `.set_processed(work)`, `.meta["processed_stage"]`, `.meta["missing_config"]`, `.meta["missing_application"]`, `.meta["split_status"]="stale"` | DataFrame; provenance dict | RW | `MissingApplyRequest` — no ids |

**Confirmed defect pattern:** `outlier_application` and `missing_application` are single dict keys under one `meta` dict — mutually exclusive within the store (applying outliers pops the missing-value record, `outlier_router.py:83-85`). A user cannot have in-progress outlier and missing-value treatments for two different projects at once; the second project's `/apply` call silently clobbers the first project's `processed_df` and treatment record.

### 3.3 Feature Profiling / Quality Profiling / Bureau Detection

| Site | Endpoint | Object.attr | Data | R/W | Ids in payload? |
|---|---|---|---|---|---|
| `feature_profile_service.py:120-207` | `POST /api/data/feature-profile` | `.get_base_df()`, `.target`, `.get_selected_columns()`, `.meta["feature_manifest"]`, `.meta["source"]` | DataFrame, str, list, dict, dict | R | `FeatureProfileRequest`/`DataProfileRequest` — no ids |
| `quality_profile_service.py:71-177` | `POST /api/data/quality-profile` | `.get_base_df()`, `.target`, `.meta["source"]`, `.meta["dataset_version"]` | DataFrame, str, dict, str | R | `DataProfileRequest` — no ids |
| `bureau_detection_service.py:56-158` | `POST` bureau-detection endpoint | reads `.get_base_df()`, `.target`; **writes** `.meta["bureau_review"]` (persisted via `save_checkpoint()` in `bureau_detection_router.py:17`) | DataFrame, str; detection-result dict incl. reviewer rationale/treatment selections | RW | `BureauDetectionRequest` — no ids |

### 3.4 Feature Engineering — `server/features/feature_service.py`

| Site | Function | Object.attr | Data | R/W | Ids in payload? |
|---|---|---|---|---|---|
| `feature_service.py:33-51` | `_existing_manifest`, `_base_columns`, `_original_feature_rows` | `.meta["feature_manifest"]`, `.get_base_df()`, `.meta["materialized_feature_names"]`, `.get_selected_columns()`, `.target` | dict, DataFrame, list, list, str | R | n/a (internal helpers) |
| `feature_service.py:79,95,117` | manifest row builders | `.meta["dataset_version"]`, `.target` | str (defaults to the literal string `"in-memory"` when absent), str | R | none |
| `feature_service.py:130-212` | `get_manifest` / `update_manifest` (`POST /api/features/manifest`) | reads `.meta["dataset_version"]`, `.meta["split_status"]`, `.X_train`; **writes** `.meta["feature_manifest"]`, `.meta["selected_columns"]`, `.meta["split_status"]`, then calls `.reset_splits()` | dict, str, split-presence flag; dict, list, str; (invalidates Step-6 split) | RW | `FeatureManifestUpdateRequest.dataset_version: str = ""` is **accepted but never validated** against what's actually loaded before the manifest/split are mutated |
| `feature_service.py:329-370` | `materialize_manifest` (`POST /api/features/materialize`) | reads `.get_base_df()`, `.meta["materialized_feature_names"]`; **writes** `.set_processed(frame)` (replaces `processed_df`), `.meta["processed_stage"]`, `.meta["materialized_feature_names"]`, `.meta["selected_columns"]`, `.meta["split_status"]`, `.meta["feature_manifest"]` | DataFrame; provenance | RW | `FeatureMaterializeRequest.manifest_version` only |

### 3.5 Splitting & Balancing — `server/splitting/split_router.py`

| Site | Endpoint | Object.attr | Data | R/W | Ids in payload? |
|---|---|---|---|---|---|
| `split_router.py:52-72` | `GET /api/balancing_split/status` | `.get_base_df()`, `.target`, `.meta["split_record"/"feature_manifest"/"split_status"/"dataset_version"]`, `.get_splits()`, `.get_selected_columns()` | DataFrame, str, dicts/str, split tuple, list | R | GET, no body |
| `split_router.py:142-215` | `POST /api/balancing_split/config` | reads `.meta["feature_manifest"]`, `.meta["dataset_version"]`, `.get_selected_columns()`; **writes** `.meta["selected_columns"]`, `.set_splits(X_train, X_test, y_train, y_test)`, `.meta["split_record"/"split_config"/"target_prevalence"/"split_status"/"feature_manifest"]` | dict, str, list; 4 DataFrame/Series objects; provenance dicts | RW | `SplitConfigPayload` carries `dataset_version` (used only as a 409 staleness check against stored `meta`, not a storage key) — **no project_id** |

This is the single highest-blast-radius write in the whole pipeline: it unconditionally replaces `X_train`/`X_test`/`y_train`/`y_test`, which is what every downstream training and evaluation call consumes.

### 3.6 Training — `server/training/trainer_service.py`, `trainer_router.py`, `training_job_service.py`, `training_preflight_service.py`

| Site | Function/Endpoint | Object.attr | Data | R/W | Ids in payload? |
|---|---|---|---|---|---|
| `training_preflight_service.py:79-88` (`training_preflight`, `POST /api/model/train/preflight`) | reads `.get_splits()`, `.meta["split_record"/"feature_manifest"/"split_status"/"dataset_version"/"source"/"dataset_id"]`, `.target` | split frames, provenance dicts/strings | R | `TrainingJobRequest` **does** carry `project_id, dataset_id, dataset_version, target, split_id, feature_manifest_version` — but `request.project_id` is **read nowhere in this function**; it's accepted and ignored. |
| `trainer_service.py:83-114` (`_get_or_create_splits`) | reads `.get_splits()`, `.meta["split_status"]`, `.target`, `.meta["feature_manifest"]`, `.get_selected_columns()` | split frames, provenance | R | called with only `k_folds` |
| `trainer_service.py:131-204` (`train`, sync path `POST /api/model/train`) | reads (above); **writes** `RESULTS.set_model_artifacts(artifacts, metadata)`, `RESULTS.set_last_summary(safe_summary)` | fitted estimators dict; summary dict | RW | `trainer_router.py:131-134` reads `project_id`/`dataset_version`/`target`/`problem_type` straight off the raw request dict and passes them through as **descriptive strings only** — never used to key storage |
| `training_job_service.py:68,103-104,176` (`create`, `POST /api/model/train/jobs`) | reads `.get_splits()` (via `TRAINER._get_or_create_splits`), `.meta["feature_manifest"/"split_record"]`; **writes** `.meta["active_training_job_id"] = job_id` | split frames (copied by value into thread args at line 180), dicts, job_id string | RW | `TrainingJobRequest.project_id` **is** sent by the frontend (`Step06_Train.tsx:379`) and **is** stored into `job["project_id"]`/`job["contract"]["project_id"]` (lines 140,148) — used for **display/mismatch-detection only**, never as a storage partition |
| `training_job_service.py:167` | `create` | `job["_result_store"] = RESULTS.current()` | captured store **reference**, resolved by the *launching* user's scope at creation time | R (capture) | this is what makes background-thread result delivery land in the right *user's* store — see §5 scenario 7 for why that's still not enough |
| `training_job_service.py:200-210` (`get`, `GET /jobs/{job_id}`) | reads `.meta["dataset_version"]`, `.meta["split_record"]["split_id"]` | strings | R | runs on the request thread — correct scope — used to auto-mark a job `"interrupted"` if the dataset/split changed under it |
| `training_job_service.py:256-257` (`cancel`) | pops `.meta["active_training_job_id"]` | — | W | request thread, correct scope |
| `training_job_service.py:279-354` (`_run`, background `Thread`) | line 353-354: reads/pops `.meta["active_training_job_id"]` | — | RW | **runs on a bare `threading.Thread`, which does not inherit the caller's `contextvars.Context`** — `active_user()` returns `None` here, so this access resolves to the `"anonymous"` scope, not the launching user's. See §5 for the concrete consequence. |
| `training_job_service.py:526,528` (`_finalize`) | `job["_result_store"].set_model_artifacts(...)`, `.set_last_summary(...)` | fitted models, summary | W | uses the **captured reference**, not the proxy — correctly lands in the launching user's `RESULTS`, but see §5 scenario 7 for why "the launching user's `RESULTS`" is itself the problem |
| `trainer_router.py:188-225` (`GET /api/train/last`) | `RESULTS.get_last_summary()` | last summary dict | R | accepts `project_id, dataset_version, target, problem_type` as **query params**, compares them against the stored summary's own fields, and returns a **soft `context_error` string** on mismatch — not a 403/404, and only if the caller bothers to pass them |

### 3.7 Evaluation, Interpretation, Scoring — `server/evaluation/eval_service.py` (~56 sites), `eval_router.py`

This is the largest and most heterogeneous consumer. Full function-level table (see the underlying research transcript for exhaustive line numbers; summarized here by object and pattern):

| Object | Held data | Consumers | Ids available? |
|---|---|---|---|
| `DATASTORE.get_splits()` | X_train/X_test/y_train/y_test | `_test_data`, `rfe`, `_rfe_regression`, `vif_summary`, `vsi_summary`, `save_rfe_model`, `final_model_status`, `save_selected_model_as_final`, `export_model_bundle`, `score_development_split`, `_default_priors` | none of these functions receive a run/split id; some (rfe, decision_tree, decision_boundary, feature_importance, model_details) receive a `context` dict (`project_id/dataset_version/target/problem_type`) via `eval_router.py`'s `_context()` helper (lines 48-59) but it is used **only** by `_artifact_context_mismatch` (below), never to select *which* split to read |
| `RESULTS.get_model_artifact(model_name)` / `.model_artifacts` | fitted sklearn Pipeline/estimator, or an RFE result dict | every interpretation endpoint (importance, details, tree, pdp, sensitivity, shap, decision_boundary, knn_clusters) | `model_name` (a short catalog key, e.g. `"logreg"`) is the only selector; unkeyed by project |
| `RESULTS.get_final_model()` / `.final_model_metadata` | single fitted-model slot | `sensitivity_summary`, `vif_summary`, `vsi_summary`, `final_model_status`, `_resolve_scoring_model`, `export_model_bundle` | none |
| `RESULTS.set_final_model(...)` | **write** — overwrites the one global final-model slot | `save_rfe_model` (line 1851), `_save_rfe_regression_model` (1916), `save_selected_model_as_final` (1977) | `context.project_id` **is captured into the written metadata** (so it's recorded) but **not used to key the write** — a second project's "save as final" silently replaces the first project's final model |
| `RESULTS.set_scoring_reference({..., "X": X.copy(), "scores": ...})` | **write** — an entire uploaded scoring DataFrame plus predictions, single global slot | `score_dataset` (`POST /score/upload`, line 2300); no reader of `get_scoring_reference()` found in these two files — currently dead/latent state that would collide across projects the moment a consumer is added |
| `eval_service.py:96-119` (`_artifact_context_mismatch`) | compares caller-supplied `expected` (`project_id/dataset_version/target/problem_type`) against the **stored artifact metadata**, returns a human-readable mismatch string | called by `feature_importance` and similar interpretation endpoints | this is the *only* place ATLAS today does anything resembling cross-project protection for evaluation state, and it is a **post-hoc soft check**, not a storage boundary — it fires after the read has already happened, and only for the subset of endpoints whose router function bothered to accept the four context fields |

**Endpoints that accept *no* identifying context at all** (verified against `eval_router.py`, full file read): `GET /eval/curves` (line 16-19, only `model`), `GET /eval/deciles` (22-25), `GET /eval/command_center` (28-35), `GET /eval/knn_clusters` (43-45), and (per the research pass) `/interpretation/sensitivity_summary`, `/interpretation/vif`, `/interpretation/vsi`, `/score/upload`, `/score/development-split`.

No `threading.Thread`, `ThreadPoolExecutor`, or `asyncio.create_task` exists in `eval_service.py` or `eval_router.py` — every evaluation/interpretation/scoring call runs synchronously inside the request, so `active_user()` is correctly populated throughout this file. The isolation gap here is entirely about the *missing project dimension* in the key, not about thread-context propagation.

### 3.8 EDA — `server/eda/eda_router.py`, `server/eda/workspace_service.py`

All sites are read-only against `.get_active_df()` / `.target` / `.meta["dataset_version"/"version_id"/"feature_manifest"]` (`eda_router.py:73,140`; `workspace_service.py:159,162,173,183,205`). None of the request models (`EDAWorkspaceRequest`, the raw dict bodies used by `d3_histogram`) carry project/dataset/run ids. `workspace_service.py` additionally maintains its own in-memory result cache keyed off `DATASTORE.meta`'s version tag (§2.4) — same root cause, one layer removed.

### 3.9 Dataset Library bridge — `server/datasets/dataset_router.py`

`POST /api/datasets/{dataset_id}/versions/{version_id}/activate` (lines 152-191) is the only bridge from the persistent, already-id-rich dataset library into `DATASTORE`. It reads the versioned CSV artifact off disk (real `dataset_id`/`version_id` path params) and **writes** `DATASTORE.set_raw(df)`, `.set_target(None)`, `.meta["selected_columns"/"dataset_version"/"source"]`, and calls `RESULTS.clear_model_artifacts()` (line 181) — a full, unconditional overwrite of the single per-user slot, with no project scoping at the activation boundary itself (see §8 for why this endpoint is the natural seam for Stage 3).

### 3.10 Analytics Engine adapter — `server/analytics_engine/dataset_adapter.py`

`load_dataset()` (lines 17-28) is the one place in the whole codebase that already does the *right* thing: when its payload includes `dataset_id`/`dataset_version_id` (optional, checked at lines 17-23), it reads the versioned artifact **directly from the dataset registry on disk**, bypassing `DATASTORE` entirely. Only when those ids are absent does it fall back to `DATASTORE.get_active_df()` (line 24). This is the pattern §8 and §10 recommend generalizing.

---

## 4. Current state-flow diagram

```
                     ┌─────────────────────────────────────────────────────┐
                     │  require_user(request)  — server/security/security_store.py:544
                     │  cookie → user_for_session() → set_active_user(user)  │
                     │  (contextvars.ContextVar, per-request, NOT copied    │
                     │   into bare threading.Thread / ThreadPoolExecutor)   │
                     └───────────────────────┬───────────────────────────────┘
                                              │ active_user() available for the
                                              │ rest of THIS request's call stack
                                              ▼
   Step01 Data Acquisition ──▶ metadata_router.set_sample ──▶ DATASTORE.set_raw(df)  ─┐
   Step01 (library)        ──▶ dataset_router.activate_dataset_version ──▶ same slot ─┤
                                                                                       │
   Step02 EDA               ──▶ eda_router / workspace_service ──▶ reads DATASTORE ◀──┤
   Step03/04 Outliers/Missing──▶ outlier_router/missing_router ──▶ RW same slot ──────┤   ALL OF THIS
   Step05 Feature Eng        ──▶ feature_service ──▶ RW same slot ────────────────────┤   IS KEYED ONLY
   Step06 Balance & Split    ──▶ split_router ──▶ W: X_train/X_test/y_train/y_test ───┤   BY:
                                                                                       │
   Step06 Train (sync)       ──▶ trainer_service.train ──▶ R splits, W RESULTS ───────┤     _scope_key()
   Step06 Train (async job)  ──▶ training_job_service.create ─┐                       │     = active_user()
        (request thread)         reads DATASTORE, captures    │                       │       .userId
                                  RESULTS.current() by ref ────┤                       │     or "anonymous"
                                  spawns Thread ────────────┐  │                       │
                                                             │  │                      │
        (background thread,                                 ▼  ▼                      │
         NO active_user() context) ──▶ _run/_finalize ──▶ writes via CAPTURED          │
                                       RESULTS reference (correct user) but             │
                                       reads/pops DATASTORE.meta via PROXY              │
                                       (resolves to "anonymous" — wrong scope) ─────────┤
                                                                                        │
   Step08 Evaluate/Interpret/Score ──▶ eval_service ──▶ R splits+artifacts, W final_model/scoring_reference
                                                                                        │
   TRAINING_JOBS (job_id → job dict) ─────────────────────────────────────────────────┘
        NOT routed through the scope proxy at all — one global dict for every user.
        GET /jobs/active returns ALL users' jobs. GET/cancel /jobs/{id} has no
        ownership check.

   @app.on_event("startup") ──▶ load_checkpoint() ──▶ runs with NO request context
        ──▶ active_user() is None ──▶ writes into the "anonymous" scope only,
            regardless of which user's data was last checkpointed.
```

---

## 5. Concrete cross-user and cross-project failure scenarios

Each scenario below is graded against what was actually verified in code, not assumed.

1. **User A loads Dataset A, then User B loads Dataset B (two different real users).** — **Not currently broken.** `_scope_key()` correctly separates them by `userId` (`dataset_store.py:229-236`, `result_store.py:76-83`), and `require_user` resolves identity from an unforgeable session cookie, not a client-supplied id. This is the one property the current design does get right, and it should be preserved, not discarded, by any migration stage.

2. **User A trains while User B trains (two different real users).** — **`DATASTORE`/`RESULTS` are fine** (same reasoning as #1). **`TRAINING_JOBS` is not**: `GET /api/model/train/jobs/active` (`trainer_router.py:34-36` → `training_job_service.py:213-216`) returns both users' jobs, unfiltered, to whichever of them calls it. `GET /jobs/{job_id}` and `POST /jobs/{job_id}/cancel` (`trainer_router.py:39-52`) perform no ownership check — User B, if they learn User A's `job_id` (e.g., from a shared screenshot, log line, or browser history), can view or cancel User A's training job.

3. **One user opens two projects in different browser tabs.** — **Confirmed broken**, the core defect this document exists to describe. Both tabs share one `require_user`-resolved identity, so both resolve to the *same* `DATASTORE`/`RESULTS` instance. Uploading a dataset for Project 2 in tab 2 (`metadata_router.py:141`, `DATASTORE.set_raw(df)`) immediately overwrites Project 1's in-progress `raw_df`/`processed_df`/splits in tab 1, with tab 1 given no signal until its next action returns wrong data, a "stale split" error (`trainer_service.py:88-89`), or a manifest-mismatch error (`training_preflight_service.py`, comparing `request.dataset_version` against the now-different `DATASTORE.meta["dataset_version"]`).

4. **A server restart occurs halfway through a workflow.** — **Confirmed broken, worse than "data is lost."** `save_checkpoint()` (`session_checkpoint.py:42-78`) is called from inside request handlers (e.g. `metadata_router.py:147`, `training_job_service.py:312,344`) and snapshots whichever *single* scope was active for **that specific call** via the proxy — there is one checkpoint file (`CHECKPOINT_PATH`, line 15) for the whole process, last-write-wins across all users. `load_checkpoint()` (lines 81-107) runs from `@app.on_event("startup")` (`main.py:149-160`) with no request in flight, so `active_user()` is `None` and every write in `load_checkpoint` (`DATASTORE.raw_df = ...`, etc.) resolves to the `"anonymous"` scope. **Net effect: after every restart, no authenticated user's session is actually restored — the one snapshot that happened to be saved last becomes attached to a scope no real user will ever be authenticated as.**

5. **A user returns to a previously completed project.** — **Confirmed broken for working state, fine for governance artifacts.** Governance-relevant records (workflow state, evidence, decisions, audit trail — all in the SQLite persistence layer covered by the FND-001 authorization fix) do survive and are correctly project-scoped. The actual modeling matrices, fitted encoders/transforms, splits, and feature manifest do not persist per-project at all — they live only in the single current `DATASTORE` slot for that user, which has near-certainly been overwritten by whatever the user touched most recently (another project, a re-upload, or lost entirely per #4). Returning to an old project means redoing Steps 1-6, or worse, silently inheriting an unrelated project's leftover state.

6. **Training, evaluation, and scoring requests overlap.** — **Partially mitigated by accident, not by design.** The async training path copies `X_train`/`X_test`/`y_train`/`y_test` **by value** into the background thread's arguments (`training_job_service.py:180`, `X_train.copy()` etc.), so an in-flight job is safe from a concurrent `POST /balancing_split/config` overwrite. But every evaluation/interpretation/scoring call (§3.7) reads `DATASTORE.get_splits()` / `RESULTS.get_model_artifact(...)` **fresh, at arbitrary later request time**, fully decoupled from when they were written. If a split rebuild or retrain happens in between — from the same user working a different project in another tab — an interpretation endpoint will silently compute diagnostics against a mismatched split/model pair. The only guard is the soft, opt-in `_artifact_context_mismatch` check (§3.7), which most of these endpoints don't even invoke with real context.

7. **Background or long-running jobs complete after the user switches projects.** — **Confirmed broken, most concrete instance of the whole problem.** `training_job_service.py:167` captures `job["_result_store"] = RESULTS.current()` — the *user's* store, resolved once at job creation. If that user starts training on Project A, then switches their single open tab to Project B (which, per #3, reuses the identical `DATASTORE`/`RESULTS` instance), and Project A's background job finishes afterward, `_finalize` (lines 526,528) calls `job["_result_store"].set_model_artifacts(...)` / `.set_last_summary(...)` — writing Project A's results directly into what is now, from the frontend's perspective, "Project B's" `RESULTS`. The only thing standing between the user and silently seeing Project A's model as if it were Project B's is the client-side check in `GET /api/train/last` (`trainer_router.py:203-224`), and only if the caller supplies a matching `project_id` and the endpoint's soft string-comparison catches it. Additionally, the same job's `finally` block (`training_job_service.py:352-354`) tries to clear `DATASTORE.meta["active_training_job_id"]` from the background thread, which — per the context-propagation gap in §3.6 — resolves to the `"anonymous"` scope and silently no-ops, so that marker is never actually cleared from the real user's store for a job that completes normally (only `cancel()`, which runs on the request thread, clears it correctly). This is independent confirmation, via a real dead-code path, that background-thread code in this file is not operating in the scope its author intended.

**Additional finding not in the original scenario list, found during discovery:** two different, *authorized* collaborators on the *same* project cannot see each other's trained models at all, because `RESULTS` partitions by user, not project. This is a functional regression relative to what ATLAS's project-sharing model (`SharingService`, see the earlier FND-002 work) is supposed to provide, and it needs to be an explicit design input for §8, not an incidental side effect of "isolating by project."

---

## 6. Existing identifiers available at each layer

| Identifier | Where it's authoritative | Where it's already threaded through | Where it's missing |
|---|---|---|---|
| **user_id** | `require_user()` (`security_store.py:544-608`) — resolved server-side from the `atlas_session` httponly cookie via `user_for_session()`, never trusted from client input. Exposed per-request via `active_user()` ContextVar. | Every router in §3 is mounted with `dependencies=[Depends(require_user)]` (`main.py:241-275`), so `active_user()` is populated for the entire synchronous call stack of every one of these endpoints. FastAPI/Starlette's `run_in_threadpool` (used for any non-`async def` route handler) explicitly copies the caller's `contextvars.Context` into its worker thread, so this holds even though most of these are plain `def` endpoints. | **Bare `threading.Thread` and `concurrent.futures.ThreadPoolExecutor` do not inherit `contextvars.Context`** — confirmed by the dead-code symptom in `training_job_service.py:353-354` (§5, scenario 7). This is the *only* place `active_user()` is unavailable during code triggered by an authenticated request. |
| **project_id** | Exists as a real, persisted concept elsewhere (`server/persistence/repositories/project_repository.py`, `server/projects/project_registry.py`, `dataset_registry.py`'s `project_links.json`). | Sent by the frontend to `TrainingJobRequest.project_id` (`Step06_Train.tsx:379`, pulled from `useWorkflowStore`) and stored into `job["project_id"]`/`job["contract"]["project_id"]`. Accepted as an optional query param by a handful of `eval_router.py` endpoints (`/interpretation/importance`, `/interpretation/details`, `/eval/tree`, `/interpretation/rfe`, `/interpretation/decision_boundary`) via `_context()` (lines 48-59). | Absent from `SetSamplePayload`, `SetTargetPayload`, `OutlierApplyRequest`, `OutlierSummaryRequest`, `MissingApplyRequest`, `MissingSummaryRequest`, `FeatureManifestUpdateRequest`, `FeaturePreviewRequest`, `FeatureMaterializeRequest`, `BureauDetectionRequest`, `DataProfileRequest`/`FeatureProfileRequest`, `SplitConfigPayload`, `EDAWorkspaceRequest`, and most of `eval_router.py` (`/eval/curves`, `/eval/deciles`, `/eval/command_center`, `/eval/knn_clusters`, `/interpretation/sensitivity_summary`, `/interpretation/vif`, `/interpretation/vsi`, `/score/upload`, `/score/development-split`). Everywhere it *is* present, it is used only for a soft post-hoc mismatch string, never as a storage key. |
| **dataset_id / dataset_version_id** | Real, content-addressed ids in `dataset_registry.py` (`datasetId`, `versionId`; artifacts live at `ARTIFACT_ROOT/<datasetId>/versions/<versionId>/`). | Path params on `dataset_router.py`'s `/activate` endpoint; free-text-copied into `DATASTORE.meta["dataset_version"]` and `TrainingJobRequest.dataset_id`/`.dataset_version`. | Never validated against the real registry id at read time; `feature_service.py` defaults the label to the literal string `"in-memory"` when absent (line 79/117), which is not a real version and would collide across every dataset ever loaded without a real id. |
| **workflow_run_id / training_job_id** | `training_job_service.py`'s `job_id` (`f"train-job-{uuid4().hex}"`, line 77) is the only real "run" identity anywhere in this subsystem. | Present on every training job record and its summary (`job["job_id"]`, `summary["training_job_id"]`, line 481). | No equivalent exists for the pre-training pipeline stages (EDA/preprocessing/feature engineering/split) — those only have "whichever state is currently in `DATASTORE` for this user" as their implicit run. |
| **model_id / model_version_id** | `model_key`/`model_name` — a short catalog string (`"logreg"`, `"dtree"`, `"final"`, `"final_rfe"`) indexing into `RESULTS.model_artifacts`. | Used consistently as the *within-store* selector for every interpretation/scoring endpoint. | Not a durable registry id — it only has meaning inside one (unscoped) `RESULTS` instance; ATLAS's actual model registry (`server/registry/`) is a separate, already project-scoped system this subsystem doesn't connect to. |
| **session cookie / request context** | `SESSION_COOKIE_NAME = "atlas_session"` (`security_store.py:23`), validated server-side. | As above — this is the root of trust for user_id. | Carries no project dimension; the frontend's "current project" (`useWorkflowStore.projectId`) is purely a client-side notion until a given endpoint chooses to accept and send it. |

**Direct answer to investigation point 5** (does the frontend already send `project_id`?): **Partially, and inconsistently.** `Step06_Train.tsx` sends it for job creation. No other Step0X page's API calls (`Step01_DataAcquisition.tsx`, `Step04_Outliers.tsx`, `Step04_MissingValues.tsx`, `Step05_EncodingScaling.tsx`, `Step06_BalancingSplit.tsx`, `Step02_EDA.tsx`) were found sending `project_id`/`projectId` to their respective backend calls (verified by grep against `src/steps/*.tsx` and the corresponding backend Pydantic models, not inferred from route names). The frontend *has* `projectId` available everywhere via `useWorkflowStore` (confirmed at `Step06_Train.tsx:325`, and this store is the single global workflow-state store used by every step page) — it simply isn't being sent to most of these endpoints today.

---

## 7. Recommended target architecture

Reuse the proxy pattern that already exists — it is sound — but change what it keys on, and stop treating all state as one class.

**Do not adopt a single universal key.** The evidence in §3 and §5 shows two genuinely different lifetimes and sharing rules:

- **Working / draft state** (raw and processed frames, splits, in-progress preprocessing config, feature manifest draft, EDA cache) is per-*(user, project)*. It must not leak between a user's two open projects (§5.3), but it also must not silently merge two different collaborators' concurrent edits to the *same* project into one shared mutable frame — each collaborator's in-progress draft is their own until something is explicitly committed. **Recommended key: `(user_id, project_id)`.**
- **Committed / result artifacts** (trained model objects, the last training summary, the project's selected final model) are per-*project*, not per-user, so every authorized collaborator sees the same thing — this directly fixes the cross-collaborator-invisibility gap found in §5. **Recommended key: `(project_id, training_job_id)` for the training run's own artifacts, with a separate `(project_id,)`-keyed "current final model" pointer** that a governed action (§3.7's `save_selected_model_as_final`/`save_rfe_model`) updates explicitly — mirroring how a "champion model" concept already works elsewhere in ATLAS's registry.
- **`TRAINING_JOBS`** needs both a `project_id` foreign key (already present in the job record, just unused for access control) and an authorization check reusing `SharingService.check_permission(user, "project", project_id, "view"/"edit")` — the exact mechanism already established for FND-001/FND-002 in this codebase — rather than inventing a second authorization system.
- **Dataset content itself** should not be duplicated into a third copy. §3.9-3.10 show the dataset registry (`dataset_registry.py`) already has real `(datasetId, versionId)` identity and `project_links.json` already associates `(projectId, datasetId, versionId)`. `analytics_engine/dataset_adapter.py:17-24` already demonstrates the correct pattern: read the versioned artifact directly from the registry when an id is available, and treat `DATASTORE` purely as a *materialized working copy*, not the source of truth.

This directly answers the brief's evaluation question: **`user_id + project_id` is necessary and sufficient for working state; `workflow_run_id` (in the form of `training_job_id`, which already exists) is the right key for training-run artifacts specifically, not for the whole pipeline; a user-only or project-only key is demonstrably insufficient** — user-only is the current, broken design (§5.3, §5.4, §5.7), and project-only would reintroduce a different bug (two collaborators' simultaneous unsaved drafts on the same project overwriting each other, which is not currently reported as a symptom only because concurrent same-project editing by two different real users doesn't appear to be exercised by any current test — §7.1 below).

### 7.1 What "fitness for large DataFrames / fitted transformers / model objects" rules out

An SQL-row-per-value model (like most of `server/persistence/repositories/*`) is a poor fit for a multi-hundred-MB DataFrame or a fitted `sklearn.Pipeline` object — serializing/deserializing those on every request would be a severe latency and memory regression, and `session_checkpoint.py`'s existing JSON-via-`to_json(orient="split")` approach (lines 19-28) already shows the cost of treating a DataFrame as a persistence-layer value: it round-trips through JSON, which does not preserve dtypes reliably and does not scale past a few hundred thousand cells. **The target architecture keeps large, fitted, in-process objects in memory** (this is not a persistence-layer migration), scoped by a proper compound key instead of a single implicit slot — persistence (§9) is reserved for what's small enough and needs to survive a restart.

---

## 8. Proposed state key and ownership model

```
DATASTORE  (working/draft state — one instance per open (user_id, project_id) pair)
  scope_key = f"{user_id}:{project_id}"
  raw_df, processed_df, target, X_train..y_test, meta{...}
  — same shape as today's DatasetStore; only _scope_key() changes.
  — ownership: only the (user_id) half of the key is checked against the caller's
    session (never client-supplied); project_id must additionally pass
    SharingService.check_permission(user, "project", project_id, "edit") before
    any write, and "view" before any read, exactly like the FND-001 persistence
    routes already do.

RESULTS  (committed artifacts — one instance per project_id, not per user)
  scope_key = project_id
  model_artifacts, model_artifact_metadata, last_training_summary,
  final_model, final_model_metadata, scoring_reference{...}
  — every read requires SharingService.check_permission(user, "project",
    project_id, "view"); every write requires "edit" or "admin" per the
    existing PERMISSION_LEVELS ranking used throughout the sharing system.

TRAINING_JOBS  (job registry — already globally unique by job_id; add authorization,
                not a new key)
  job["project_id"] already exists — enforce SharingService.check_permission
  on get/cancel; filter /jobs/active by the caller's accessible projects.
```

**Security requirements from the brief, mapped to this model:**

- *A user cannot access another user's state* — preserved: the `user_id` half of `DATASTORE`'s key still comes from `active_user()`, never client input.
- *A shared collaborator sees only state permitted through project authorization* — this is what moving `RESULTS` to project-level plus a `SharingService.check_permission` gate directly buys, and it wasn't true before (§5, additional finding).
- *One project cannot consume another project's active state* — this is what adding `project_id` to `DATASTORE`'s key directly buys (§5.3).
- *Stale job completion cannot overwrite a newer run* — requires `training_job_service.py`'s `_finalize` to check, at write time, whether a newer job for the same `project_id` has completed since this job started (a simple `created_at`/`job_id` comparison against the project-scoped `RESULTS`'s own `last_training_summary.training_job_id`), and skip the write (with an audit/log entry) if so — this is new logic, not just a re-key, and is called out as its own stage (§10, Stage 4).
- *State lookup never relies solely on a caller-supplied user ID* — preserved throughout; `user_id` always comes from `active_user()`; the only caller-supplied piece of the key is `project_id`, and every access to it is gated by `SharingService.check_permission`, not merely "does this project_id string match."
- *The authenticated identity remains authoritative* — unchanged; this migration adds a second, permission-checked dimension to the key, it does not touch how `user_id` itself is established.

---

## 9. Temporary versus durable artifact classification

| Artifact | Class | Rationale |
|---|---|---|
| `raw_df`, `processed_df`, `X_train..y_test` | **Temporary** (in-memory only, per `(user, project)`) | Multi-hundred-MB pandas objects; recomputable from the dataset registry + stored preprocessing config; not appropriate for a SQL row |
| `meta["outlier_application"]`, `["missing_application"]`, `["feature_manifest"]`, `["split_record"]`, `["split_config"]` | **Durable, small** — candidate for the existing `workflow_state` / project-scoped persistence tables (see FND-001 work), because they're plain dicts, not DataFrames, and losing them on restart is exactly what causes §5.5 | Should move to durable storage in a *later* stage once the in-memory key is fixed — re-deriving `processed_df` from a durably-stored `outlier_application`/`missing_application`/`feature_manifest` config plus the registry's `raw_df` is a smaller, safer durability story than trying to durably store the DataFrames themselves |
| `model_artifacts` (fitted estimators), `final_model` | **Temporary, in-memory, per-project** | Fitted objects, not serializable to SQL; already partially mirrored by `server/registry` for *approved* models — that governance boundary should remain the durability line, not this working cache |
| `last_training_summary`, `job["summary"]` | **Durable, small** — this is already metrics/JSON, and `training_job_service.py`'s own `_public_job` (`json_safe`) shows it's already JSON-safe | Good candidate to persist into the existing `run_records`/`decisions` persistence tables (already used elsewhere in ATLAS for governance) once the key is fixed |
| `scoring_reference` | **Temporary, short-lived, per-(user, project, upload)** | Currently dead code (no reader found, §3.7) — do not carry it forward into the new key structure without first confirming a real consumer; if kept, it should get its own short TTL, not indefinite retention |
| `TRAINING_JOBS._jobs` | **Temporary, in-memory, but should gain a durable summary record** | The live job dict (per-model progress, thread state) is inherently ephemeral; its terminal `summary` is already written to `RESULTS.last_training_summary` and should also be the thing that lands in `run_records` |

---

## 10. Migration stages

Every stage is independently deployable and revertible. None require the others to have shipped first except where explicitly noted as a hard dependency.

### Stage 1 — Introduce a scoped-state key abstraction and characterization tests. **No behavior change.**
Add a small, explicit key-builder (e.g. `server/core/modeling_scope.py`) with a function like `def dataset_scope_key(user_id: str, project_id: str | None) -> str`, but for this stage have `DATASTORE`/`RESULTS`'s existing `_scope_key()` continue to return `user_id`-only exactly as today (the new function exists but is unused by any call site yet — it's a seam, not a change). Pair this with a new test file that pins down **today's actual behavior**, both what already works (two different real users are isolated) and what's broken (same user, two projects, collide) — this is the regression harness every later stage is validated against, and it directly produces the evidence the brief demands ("do not claim concurrency safety without an executed test") for the *starting point*, not just the end state.
**Files:** new `server/core/modeling_scope.py`; new `tests/modeling_state_characterization_test.py`.
**Effort: S (1-2 days).**

### Stage 2 — Require `project_id` at the request boundary for the highest-risk write endpoints.
Add `project_id: str | None = None` to `SetSamplePayload`, `SetTargetPayload`, `OutlierApplyRequest`, `MissingApplyRequest`, `SplitConfigPayload`, `FeatureManifestUpdateRequest`, `FeatureMaterializeRequest`, and `TrainingJobRequest` already has it. Log (don't yet reject) when it's missing, so Stage 3 can be rolled out safely once telemetry shows adoption. Update the frontend call sites that don't currently send it: `Step01_DataAcquisition.tsx`, `Step04_Outliers.tsx`, `Step04_MissingValues.tsx`, `Step05_EncodingScaling.tsx`, `Step06_BalancingSplit.tsx`, `Step02_EDA.tsx` — each already has `projectId` available via `useWorkflowStore` (confirmed pattern at `Step06_Train.tsx:325,379`), so this is "start sending a value you already have," not new frontend state.
**Files (backend):** `server/core/metadata_router.py`, `server/preprocessing/outlier_router.py`, `server/preprocessing/missing_router.py`, `server/splitting/split_router.py`, `server/features/feature_types.py`. **Files (frontend, narrowly scoped to the request-body construction, not page redesign):** the six Step0X files listed above.
**Note on the brief's "do not change frontend pages unless absolutely required":** this is that required case — the backend cannot obtain `project_id` from nowhere, and it is already present client-side.
**Effort: M (3-5 days), mostly mechanical.**

### Stage 3 — Re-key `DATASTORE` by `(user_id, project_id)`.
Change `dataset_store.py`'s `_scope_key()` to combine `active_user().userId` with a new per-request `active_project_id` (a second `contextvars.ContextVar`, set by a small dependency alongside `require_user`, populated from Stage 2's now-arriving `project_id` fields, with a graceful `"<user_id>:unscoped"` fallback — logged, not rejected — for any caller that still hasn't been updated). No call site in outlier_router.py/missing_router.py/feature_service.py/eda_router.py/workspace_service.py/dataset_router.py/split_router.py needs to change beyond what Stage 2 already did, because they all go through the `DATASTORE` proxy — this is the payoff of that pattern already existing. Add the `SharingService.check_permission` gate here (view for reads, edit for writes), reusing the exact mechanism from FND-001.
**Files:** `server/core/dataset_store.py`, `server/eda/workspace_service.py` (its own cache key, §2.4), a new small dependency alongside `require_user`.
**Effort: L (1-2 weeks) — this is the stage that actually closes §5.3.**

### Stage 4 — Re-key `RESULTS` by `project_id` (not user), and fix the stale-job-completion race.
Change `result_store.py`'s `_scope_key()` to `project_id` alone (with the same `SharingService` gate as Stage 3, view for reads/edit for training writes). Update `training_job_service.py`'s `job["_result_store"] = RESULTS.current()` (line 167) to resolve the **project-scoped** store instead of the user-scoped one, and add the "stale completion" guard described in §8 (compare the finishing job's `job_id`/`created_at` against the project's currently-recorded `last_training_summary.training_job_id` before overwriting). This directly fixes §5's "additional finding" (cross-collaborator invisibility) and scenario 7 (stale job overwrite).
**Files:** `server/core/result_store.py`, `server/training/training_job_service.py`, `server/training/trainer_service.py`.
**Hard dependency: Stage 3** (needs the same `active_project_id` context piece).
**Effort: L (1-2 weeks).**

### Stage 5 — Authorize and scope `TRAINING_JOBS`.
Add a `SharingService.check_permission(user, "project", job["project_id"], "view"/"edit")` gate to `get`, `cancel`, and a new project-filtered variant of `active` (`training_job_service.py:195-263`), and change `GET /api/model/train/jobs/active` (`trainer_router.py:34-36`) to accept and require a `project_id` query param, filtering the global `_jobs` dict down to that project before returning anything. This closes §5 scenario 2's cross-user job visibility/cancellation gap independent of Stages 3-4.
**Files:** `server/training/training_job_service.py`, `server/training/trainer_router.py`.
**No hard dependency on Stages 3-4** — can ship in parallel or before them.
**Effort: M (3-5 days).**

### Stage 6 — Fix background-thread context propagation and the restart-checkpoint collapse.
(a) In `training_job_service.py`, resolve and capture the `(user_id, project_id)` scope explicitly on the request thread at job-creation time (the same pattern already used correctly for `RESULTS` at line 167) and pass it explicitly into `_run`/`_train_one`/`_finalize`, instead of letting those background-thread methods touch the `DATASTORE`/`RESULTS` proxies directly (which silently resolve to `"anonymous"`, per §5 scenario 7 / §3.6). (b) Rewrite `session_checkpoint.py` to iterate every known scope in `_DATASTORES`/`_RESULT_STORES` (requires a small export/iteration method added to each store module, not exposed today) rather than snapshotting/restoring only the single "current" proxy value, and to key the checkpoint file's contents by scope rather than writing one flat, last-writer-wins document.
**Files:** `server/training/training_job_service.py`, `server/core/session_checkpoint.py`, `server/core/dataset_store.py`, `server/core/result_store.py`.
**Hard dependency: Stages 3-4** (there's nothing meaningful to iterate/restore per-scope until the scope key itself includes `project_id`).
**Effort: M (3-5 days).**

### Stage 7 — Make evaluation/interpretation/scoring context mandatory, not a soft check.
Add `project_id`/`training_job_id` (or equivalently, once Stage 4 lands, simply route these calls through the now project-scoped `RESULTS`, making an explicit id largely redundant) to the endpoints in §3.7 that currently accept none (`/eval/curves`, `/eval/deciles`, `/eval/command_center`, `/eval/knn_clusters`, `/interpretation/sensitivity_summary`, `/interpretation/vif`, `/interpretation/vsi`, `/score/upload`, `/score/development-split`), and replace `_artifact_context_mismatch`'s soft string-comparison (`eval_service.py:96-119`) with a hard rejection (409) once the storage key itself enforces the boundary — the soft check becomes redundant defense-in-depth rather than the only defense.
**Files:** `server/evaluation/eval_router.py`, `server/evaluation/eval_service.py`.
**Soft dependency: Stage 4** (this stage is much smaller if `RESULTS` is already project-keyed, since most of the work becomes "delete the now-redundant soft check" rather than "add a new hard one").
**Effort: M (3-5 days).**

### Stage 8 — Remove legacy globals and bound memory growth.
Once telemetry from Stage 2 shows zero requests missing `project_id`, drop the user-only/unscoped fallback paths added in Stages 2-3, delete the `"anonymous"`-bucket special case, remove `RESULTS.scoring_reference` if Stage 4's audit confirms it's still unused, and add a bounded eviction policy (LRU with a TTL, sized to concurrent active sessions) to `_DATASTORES`/`_RESULT_STORES`/`TRAINING_JOBS._jobs`, none of which are ever cleaned up today (§2.1, §2.2, §2.3) — this is an existing, independent memory-growth risk uncovered during this discovery, not caused by the migration.
**Files:** `server/core/dataset_store.py`, `server/core/result_store.py`, `server/training/training_job_service.py`.
**Effort: S (1-2 days).**

### Stage 9 — Concurrency and restart test suite.
Real `TestClient`-driven integration tests (matching the pattern already established by `tests/persistence_authorization_test.py` and `tests/project_access_consolidation_test.py` in this same codebase — two real registered users, real cookies, real HTTP calls) proving: (a) two different users training concurrently don't see each other's jobs; (b) one user with two projects open no longer clobbers either project's working state; (c) a training job that completes after its launching user has switched projects lands in the correct project's `RESULTS`, not the currently-open one; (d) a simulated process restart (save → new process → load) correctly restores each of several users'/projects' state independently rather than collapsing into one bucket. This is the stage that actually earns the "concurrency safety" claim the brief requires be backed by an executed test — none of the earlier stages should be described as "done" in isolation without this.
**Files:** new `tests/modeling_state_isolation_test.py`, new `tests/modeling_state_restart_test.py`.
**Hard dependency: Stages 3, 4, 5, 6** (there is nothing to test until the isolation exists).
**Effort: M (3-5 days).**

---

## 11. Files affected by each stage (summary table)

| Stage | Backend files | Frontend files | New files |
|---|---|---|---|
| 1 | — | — | `server/core/modeling_scope.py`, `tests/modeling_state_characterization_test.py` |
| 2 | `metadata_router.py`, `outlier_router.py`, `missing_router.py`, `split_router.py`, `feature_types.py` | `Step01_DataAcquisition.tsx`, `Step04_Outliers.tsx`, `Step04_MissingValues.tsx`, `Step05_EncodingScaling.tsx`, `Step06_BalancingSplit.tsx`, `Step02_EDA.tsx` | — |
| 3 | `dataset_store.py`, `workspace_service.py` | — | small new `require_user`-adjacent dependency module |
| 4 | `result_store.py`, `training_job_service.py`, `trainer_service.py` | — | — |
| 5 | `training_job_service.py`, `trainer_router.py` | — | — |
| 6 | `training_job_service.py`, `session_checkpoint.py`, `dataset_store.py`, `result_store.py` | — | — |
| 7 | `eval_router.py`, `eval_service.py` | — | — |
| 8 | `dataset_store.py`, `result_store.py`, `training_job_service.py` | — | — |
| 9 | — | — | `tests/modeling_state_isolation_test.py`, `tests/modeling_state_restart_test.py` |

---

## 12. Backward-compatibility risks

- **Stage 2's frontend changes are the single biggest compatibility risk in the whole plan.** Any client the team doesn't control (a saved Postman collection, an internal script, a not-yet-updated build) that calls these endpoints without `project_id` must continue to work during the rollout — hence Stage 2 explicitly logs rather than rejects, and Stage 3's fallback key is a graceful (if unscoped) default rather than a hard error, until Stage 8 removes it once telemetry confirms adoption.
- **`RESULTS` moving from user-scoped to project-scoped (Stage 4) changes who can see what**, on purpose (§5's additional finding) — but this must be communicated as an intended behavior change, not a silent side effect: today, a user's *own* results on a project they no longer have access to (e.g., access was revoked) would currently still be visible to them via their private `RESULTS`; after Stage 4, correctly, it will not be. This is a security fix, but it is also observably different behavior for at least one real user path and should be called out in release notes.
- **`training_preflight_service.py`'s existing dataset_version/split_id/feature_manifest_version staleness checks (§3.6)** already assume a single active dataset per user; once `project_id` becomes part of the key (Stage 3), these checks need to be re-verified against the new per-project state rather than removed, since they still protect against a *different* problem (an out-of-date frontend cache within the same project).
- **`session_checkpoint.py`'s on-disk format changes shape in Stage 6** (from one flat document to one keyed by scope) — the migration must handle reading an old-format checkpoint file gracefully on the first restart after deployment (import it into whichever scope it can, or discard it with a logged warning) rather than crash `restore_session_checkpoint()` at startup (`main.py:149-160`).

---

## 13. Testing strategy

- **Stage 1** establishes characterization tests for *today's* behavior (both correct and broken) as the baseline every later stage is diffed against.
- **Every stage 2-7** should include unit/service-level tests for its own specific change (e.g., Stage 5's authorization gate gets a test mirroring `tests/persistence_authorization_test.py`'s pattern: two real users, one project, verify 403/200 on job get/cancel).
- **Stage 9** is the dedicated integration pass proving the composed system: real `fastapi.testclient.TestClient`, real registered users, real cookies — not calling service classes directly, per the standard already set by `tests/project_access_consolidation_test.py` in this codebase (direct service-class tests were explicitly found to create false confidence in that earlier work, since they never prove the router actually enforces anything).
- **Restart simulation** (Stage 9) should genuinely start a second process against the same checkpoint file/database rather than just calling `load_checkpoint()` in-process, to catch anything that depends on process-local state that a real restart would clear (e.g., the `_DATASTORES`/`_RESULT_STORES` dicts themselves, which no serialization step currently rebuilds — see §12).
- Every claim in this document about "already works" (§5, scenarios 1-2's `DATASTORE`/`RESULTS` half) or "is broken" (everything else in §5) is stated as a code-reading finding, not a tested one — Stage 1 is what converts the "already works" claims into an executed, regression-guarded fact, and Stage 9 is what converts the "will be fixed" claims into one. **No concurrency-safety claim in this document should be treated as proven until Stage 9's tests exist and pass.**

---

## 14. Rollback strategy

Each stage is designed to be revertible independently:

- **Stages 1, 8, 9** are additive/subtractive only (new test files, or deleting now-dead fallback code) — trivially revertible by reverting the commit.
- **Stage 2** is additive (new optional payload fields, new logging) — revertible without data loss; no stored data depends on the new fields yet.
- **Stage 3** changes a pure function (`_scope_key()`) with an in-memory-only effect — if it needs to be rolled back, the fallback path (unscoped key) it was built with becomes the sole path again; no persisted data format changes, so a rollback simply means state stops being partitioned by project again (reintroducing §5.3, not a new failure).
- **Stage 4** is the riskiest to roll back cleanly, because it changes *who can see what* — a rollback here should be treated as a security-relevant change in its own right (a user could regain visibility into a project's results they no longer have access to) and reviewed accordingly, not just reverted mechanically.
- **Stage 5** (authorization gate) should never be rolled back without equal scrutiny — reverting it reopens the cross-user job visibility/cancellation gap in §5 scenario 2.
- **Stage 6's checkpoint format change** needs the backward-compatible reader described in §12 kept in place for at least one full deploy cycle after rollback, so a rollback doesn't strand users on a checkpoint file the older code can't parse.
- **Stage 7** can be rolled back independently of Stage 4 (it only removes a soft check and adds new required query params — both are cleanly reversible).

---

## 15. Estimated effort by stage

Using S = 1-2 engineer-days, M = 3-5 engineer-days, L = 1-2 engineer-weeks, for a single experienced engineer already familiar with this codebase; treat these as rough planning inputs, not commitments — actual effort depends heavily on how much of Stage 9's testing surfaces issues in earlier stages that need follow-up.

| Stage | Effort | Cumulative |
|---|---|---|
| 1 — scoping seam + characterization tests | S | S |
| 2 — require project_id at the boundary | M | S+M |
| 3 — re-key DATASTORE by (user, project) | L | S+M+L |
| 4 — re-key RESULTS by project, fix stale-job race | L | S+2M+2L |
| 5 — authorize/scope TRAINING_JOBS | M | +M |
| 6 — fix thread context + checkpoint restart | M | +M |
| 7 — make eval/scoring context mandatory | M | +M |
| 8 — remove legacy globals, bound memory | S | +S |
| 9 — concurrency + restart test suite | M | +M |

Total: roughly 6-8 engineer-weeks end to end for one engineer, with Stages 1-2 and Stage 5 parallelizable against each other (Stage 5 has no dependency on Stages 3-4), and Stages 6-7 parallelizable against each other once Stage 4 lands.

---

## 16. The smallest safe first implementation step

**Stage 1, and specifically only its second half: the characterization test file.**

Before touching any production code, add `tests/modeling_state_characterization_test.py` using the existing `fastapi.testclient.TestClient` pattern already established in this codebase (`tests/persistence_authorization_test.py`, `tests/project_access_consolidation_test.py`) to prove, with two real registered users and real HTTP calls against `server.main.app`:

1. Two different authenticated users each uploading a dataset via `POST /api/data/set_sample` do **not** see each other's data on a subsequent `GET /api/data/get_sample` — this should pass today and serves as the regression guard that nothing in later stages is allowed to break.
2. One authenticated user, sending two different `project_id`-flavored payloads (once `project_id` exists as an accepted-but-unused field per Stage 2, or, before that, simply two different dataset uploads in sequence representing "project A" then "project B") to `POST /api/data/set_sample`, **does** observe the second upload silently overwriting the first — this should fail today (i.e., the assertion should currently demonstrate the bug), and is exactly the assertion Stage 3 is expected to flip from "bug reproduced" to "bug fixed."

This step requires no production code change, carries zero deployment risk, and produces the two load-bearing facts every later stage's correctness is measured against: proof of what already works, and proof of what doesn't, both pinned down as executable tests rather than claims in a document.

---

*Prepared as a code-grounded discovery and planning exercise. No production source was modified. No migration work has begun.*

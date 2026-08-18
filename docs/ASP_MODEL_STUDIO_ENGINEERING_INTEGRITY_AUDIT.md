# ASP Model Studio — Engineering Integrity Audit

**Type:** Bounded engineering-integrity review (no model training, no broad refactor)
**Date:** 2026-08-18
**Reviewer role:** Senior software architect / security reviewer / debugging specialist
**Repository:** `C:\Users\james\asp-model-studio` (only)

---

## 1. Executive verdict

ASP Model Studio is **structurally coherent and defensively engineered**. The
authentication boundary is fail-closed, project/dataset isolation is enforced at
the router layer with an explicit second ACL for Dataset Library access,
logical-URI → filesystem resolution is hardened against traversal/symlink/hardlink
escape, and database migrations are per-file atomic. The preserved but unfinished
Phase 4 **Milestone B** checkpoint (lineup / starter-duration / bullpen usage) is
**structurally leakage-safe** and cannot present unregistered results in the UI.

**No P0 or P1 defects were found.** Two real **P2** defects were found and
**repaired** (each with a focused regression test): a duplicate-authority defect in
the dataset totals, and a latent fail-open default in `current_user()` that could
synthesize administrator authority when no user context was present. The remainder
are P3 observations.

> **Update 2026-08-18 (targeted auth-context hardening pass):** finding **P2-2**
> (`current_user()` synthesized admin) is now **RESOLVED** — see §11 and §13. The
> original audit had deferred it; a bounded call-path analysis confirmed no caller
> legitimately depends on the synthesized admin, so it was repaired fail-closed.

This is an honest "largely sound" result — the value here is the verification and
the two concrete isolation/robustness findings, not a long defect list.

| Severity | Count | Repaired |
|----------|-------|----------|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 2 | 2 |
| P3 | 4 | 0 (observations) |

---

## 2. Scope

In scope and reviewed: `src/sports/`, `src/apps/ModelingApp.tsx`,
`src/components/Sidebar.tsx`, `server/main.py`, `server/security/`,
`server/persistence/`, `server/sports_datasets/`, `server/sports_identity_bridges/`,
`server/sports_modeling/`, `server/sports_phase4/`, and the corresponding tests.

Out of scope (per instructions): model research/training, grid searches, external
providers, sibling repositories (`ai-sports-predictor`, `ds-workflow-starter`),
architecture redesign, dependency upgrades, branding changes, financial ATLAS.

Excluded from reading: `node_modules`, `.venv`, `dist`, `.runtime`, `test-results`,
caches, model artifacts, Parquet data, exchange packages.

**Confirmed constraints at completion:** provider calls = 0 · external-network
calls = 0 · sibling-repo access = 0 · commits = 0 · pushes = 0 · remote changes = 0
· exchange-package writes = 0.

---

## 3. Baseline Git state

- **Branch:** `main`
- **HEAD:** `f1e22d467bcc1d6c120f82667c672d02c5c30995` (matches expected Milestone A; **unchanged** by this audit)
- **Working tree:** intentionally dirty with the preserved Milestone B checkpoint.

Preserved Milestone B checkpoint (present before the audit, **untouched**):

- Modified (tracked): `src/apps/ModelingApp.tsx`, `src/components/Sidebar.tsx`,
  `src/sports/ForecastWorkflow.tsx`, `src/sports/SportsProjectOverview.tsx`,
  `src/sports/SportsProjects.tsx`, `src/sports/StudioHome.tsx`,
  `src/sports/StudioModules.tsx`, `src/sports/sportsConfig.ts`,
  `src/sports/sportsEvidenceApi.ts`, `tests/sportsProductConversion.test.mjs`
- Untracked: `docs/contracts/MLB_{BULLPEN_USAGE,LINEUP_PROJECTION,STARTER_DURATION}_V1.md`,
  `scripts/run_mlb_participation_usage.py`,
  `server/sports_phase4/participation_{features,metrics,runner,training}.py`,
  `src/sports/Phase4Surfaces.tsx`,
  `tests/e2e/sports-phase4-components.spec.ts`,
  `tests/sports_phase4_participation_{cli,contract,features,fixture,training_runner}*.py`

Baseline test health captured before edits: `sportsProductConversion.test.mjs`
= 15 pass; Milestone B participation pytest (contract/features/cli/training) = 22 pass.

---

## 4. Architecture reviewed

- **Frontend routing:** `ModelingApp.tsx` (React Router). Sports surfaces under
  `src/sports/*`; Milestone B adds `/player-team-state`, `/participation-usage`
  and `Phase4Surfaces.tsx`. Evidence hook: `useActiveSportsDataset` →
  `GET /api/sports/datasets/active`.
- **Auth boundary:** `server/security/security_store.py` (`require_user`,
  `ActiveUserContextMiddleware`) + `server/main.py:assert_api_routes_authenticated`
  which **fails startup** if any `/api/*` route (outside a small public allowlist)
  lacks a `require_user` dependency.
- **Sports dataset identity:** `server/sports_datasets/constants.py` (immutable
  `MANIFEST_SHA`, `REGISTRATION_ID`, `PROJECT_ID`, `EXPECTED_TOTALS`) →
  `registry.py` (persist) → `access.py` (bounded lazy Parquet reads).
- **Project ↔ dataset linkage:** `server/persistence/` (`project_dataset_activations`,
  `sharing_service`) with independent project-ACL and Dataset-Library-ACL.
- **Registry / logical-URI handling:** `asp-model-exchange://` and
  `asp-model-studio-runtime://` logical roots; physical paths never surface to the
  frontend (sanitized in `sportsEvidenceApi.ts`).
- **Storage roots:** exchange root `ASP_MODEL_EXCHANGE_ROOT` (admin-only, backend
  env only, never a `VITE_` var); runtime under `.runtime/` (gitignored); security
  DB and persistence DB gitignored.

---

## 5. Backend/frontend contract findings

The sports contract surface was traced from `Phase4Surfaces.tsx` /
`StudioModules.tsx` → `sportsEvidenceApi.ts` (normalizers) →
`server/sports_datasets/router.py` → `registry.py:public_dataset`.

- **Aligned.** The normalizers in `sportsEvidenceApi.ts` treat every backend field
  as untrusted, coerce with explicit `finiteNumber`/`publicString`, and **never
  upgrade** `UNKNOWN`/`MISSING`/`BLOCKED`/`NOT_CONFIGURED`/`RESEARCH_*` into a
  stronger state. `getEvidence` maps `404`/`204` → `null` → honest `empty` state,
  and non-OK responses **throw** rather than fabricate data.
- **No stale mock/demo fallback.** `PlaceholderTable` and empty states are labelled
  as such; no substituted zeros or synthetic metrics were found.
- **No physical paths to the frontend.** `isPhysicalReference` +
  `sanitizePublicEvidenceValue` withhold `file:`/drive-letter/UNC/absolute paths and
  strip `*path`/`physical*` keys before rendering.
- **P2 — duplicate authority for `packageFiles` (REPAIRED).** See §9/§13.

No P1 contract defects (field the backend never supplies, or a field the frontend
misinterprets) were found.

---

## 6. Security findings

Positive posture (verified against the live backend on `127.0.0.1:8101`):

- Unauthenticated `GET /api/sports/datasets/active`, `/api/projects`,
  `/api/admin/users` → **401** (fail-closed). `/api/persistence/health` is public
  and returns only `{ok, status}` — the router **discards** `database.health()`’s
  `databasePath`, so no path disclosure.
- **Dev-header impersonation is off in this deployment:** requests with
  `X-ATLAS-USER-ID` still returned **401**. The header is only honored when
  `ATLAS_ENABLE_DEV_USER_HEADER && ATLAS_LOCAL_DEV && !ATLAS_HOSTED_MODE` **and**
  the client is loopback; the frontend only sends it under Vite `DEV`, so it is not
  shipped in a production build.
- **Passwords:** `pbkdf2_sha256`, 260k iterations, per-user random salt,
  constant-time compare; lockout after threshold; every auth outcome audited inside
  the same transaction (a prior rollback-swallows-audit bug is fixed and commented).
- **Sessions:** `HttpOnly`, `Secure` in hosted mode, `SameSite=Lax`, TTL, server-side
  revocation on role/status change.
- **Hosted config fails closed:** `validate_security_configuration()` raises on
  wildcard/insecure CORS, default secret/password, insecure cookies, dev bypasses.
- **Path traversal / filesystem escape:** `access.py:_resolve_partition` validates
  the package-relative URI, `resolve(strict=True)`, requires the package root in
  `resolved.parents`, and rejects symlinks, junctions/reparse points, and hardlink
  substitution (`st_nlink != 1`). This is a strong containment boundary.
- **SQL:** all queries reviewed use parameter binding; no string-formatted user
  input into SQL was found in the sports paths.

Finding:

- **P2 — latent fail-open default in `current_user()` (documented, not repaired).**
  See §11.

---

## 7. Isolation findings

- **Project isolation:** every project-scoped route calls `_authorize_project(...)`
  (`view`/`edit`/`admin`) via `SharingService.check_permission` before acting.
  Project listing filters to `view`-permitted rows.
- **Dataset-vs-project ACL separation:** `_project_with_durable_dataset_state` and
  `_workflow_state_for_dataset_acl` resolve Dataset Library access **independently**
  of project access and **redact** the active dataset identity, activation revision,
  and lineage artifact IDs from a project collaborator who lacks Dataset Library
  access — failing closed without leaking identity.
- **Sports evidence scoping:** `registry.py:public_dataset` attaches `paBaseline`
  and `phase4` only when the candidate study's `projectId`, `registrationId`,
  `manifestSha`, `partitionAuthoritySha`, **and** the full Phase-3 parent identity
  (`runId`, `runSha`, `experimentId`, feature-contract name/sha, `featureViewId`,
  `graphId`, terminal status) all match independently projected authorities. A
  cross-project or superseded child study cannot masquerade as active.

No cross-project or cross-user leakage path was found.

---

## 8. Milestone B structural findings (no workloads run)

Reviewed `participation_contract.py`, `participation_features.py`, and the frontend
`Phase4Surfaces.tsx` **statically** (no fitting, no runtime evidence manufactured).
All structural guarantees the checkpoint claims are **enforced in code**:

- **Prior-date-only evidence:** `_BatHistory.features` computes windows with
  `bisect.bisect_left(ordinals, target_ordinal)` — strictly **before** the target
  date. `_strict_row_guard` requires `strict_same_game_pregame_eligible is False`
  and `strict_prior_eligible_after_game_final is True`, so only rows finalized
  before the target game contribute. No same-date / future evidence path exists.
- **2025 excluded from tuning/selection:** `INNER_TUNING_SEASON = 2023`,
  `SELECTION_SEASON = 2024`, `FINAL_EVALUATION_SEASON = 2025`, and
  `componentRequiresImprovementInBoth2024And2025`. 2025 rows are frozen evaluation
  evidence only.
- **No ID / memorization features:** feature lists are `prior_*` counts/rates;
  canonical identity is used only for joins and lineage (asserted in both the
  contract and the UI copy).
- **Candidate-pool misses preserved honestly:** `ACCEPTABLE_POOL_COVERAGE`,
  `*_BLOCKED` decision enums, and `BLOCKED_DECISION_LIMITATIONS` keep misses as
  measured limitations rather than silently dropping them.
- **Checkpoint/resume:** `COMPONENT_CHECKPOINT_SCHEMA_VERSION`, per-component
  checkpoint filenames, and `BLOCKED_STAGES` provide component-local resume.
- **Status cannot become operational:** the only terminal states are
  `RESEARCH_COMPONENT` / `RESEARCH_BASELINE` / `REJECTED` / `BLOCKED`. There is no
  `operational`/`deployed` state reachable from this pipeline.
- **UI cannot claim unregistered results:** every `Phase4Surfaces.tsx` surface is
  existence-gated on `study?.components[key]`; with no registered study the pages
  render honest "not registered / not configured" empty states.

No Milestone B structural defect was found. (Its analytical training was **not**
run, per instructions.)

---

## 9. P0 findings

None.

---

## 10. P1 findings

None.

---

## 11. P2 findings

### P2-1 — Duplicate authority for the package-file count *(REPAIRED)*
- **File / function:** `server/sports_datasets/registry.py` → `_dataset_totals`
- **Root cause:** `"packageFiles": 335` was an independent literal duplicating
  `EXPECTED_TOTALS["package_files"]` in `constants.py`, which the consumer validates
  the approved exchange package against (`consumer.py` line ~947) **before**
  registration is allowed. Two sources of truth for one validated fact.
- **Realistic failure scenario:** if a re-approved exchange package ever changes its
  file count, `EXPECTED_TOTALS` (and the consumer gate) would move while the literal
  `335` stayed put. The frontend `totals.packageFiles` would then display a count
  that **contradicts the count the backend actually validated**, quietly eroding the
  evidence guarantees the UI exists to convey.
- **Repair:** reference `EXPECTED_TOTALS["package_files"]` (value-preserving today).
- **Regression test:** `tests/sports_dataset_totals_authority_test.py`.

### P2-2 — Fail-open synthetic admin in `current_user()` — **RESOLVED (2026-08-18)**
- **File / function:** `server/datasets/dataset_registry.py` → `current_user()` and
  `user_can_access()`
- **Root cause:** when there was no ambient authenticated user and no `local-user`
  row, `current_user()` returned a synthesized `{"userId": "local-user",
  "role": "admin"}`. `user_can_access(...)` then short-circuited to `True` for any
  dataset when passed no explicit user.
- **Old behavior:** absent user context ⇒ implicit administrator ⇒ any dataset
  readable/writable through `user_can_access`/`require_dataset`/
  `list_accessible_datasets`.
- **Reachability (why it was P2, not P1):** **not reachable via HTTP.** Every
  `/api/*` route is auth-gated (`assert_api_routes_authenticated`, verified by live
  401s), and `ActiveUserContextMiddleware` sets `ACTIVE_USER` for authenticated
  requests, so in a request handler `current_user()` returns the real user. The
  synthetic admin only materialized with no ambient context — a latent fail-**open**
  for future non-request callers (background jobs, scheduled retraining, ingestion,
  scoring, monitoring, CLI/service tasks).
- **Call-path analysis performed:** every direct caller of `current_user()` was
  classified. Only `user_can_access` consumes the `role == "admin"` branch, and only
  as the fail-open side effect. All other callers use `current_user().get("userId")`
  for provenance stamps (`registeredBy`/`createdBy`/`linkedBy`/journal `actorUserId`)
  or return the dict in a response; **none** gate behavior on the synthesized admin
  role. `list_accessible_datasets` (callers: `find_similar_datasets`,
  `GET /api/datasets`, model-diagnostics dataset scan) is only reached from
  auth-gated HTTP paths. The recovery CLI (`scripts/dataset_library_recovery.py`)
  does not call `current_user`/`user_can_access`/`require_dataset` at all. No
  legitimate non-request path depends on the synthesized admin.
- **New behavior (fail-closed contract):**
  1. `current_user()` now returns an explicit `UNAUTHENTICATED_CONTEXT`
     (`{"userId": None, "role": "none", ...}`) instead of a synthesized admin when
     there is neither an active user nor a real bootstrap `local-user`. An
     explicitly provisioned local bootstrap user (only created under
     `ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP`) is a real identity and is still returned
     unchanged.
  2. `user_can_access()` gained a guard: `if not user_id: return False` — so a
     context with no concrete identity can never match a dataset whose `ownerUserId`
     is also null (`None == None`).
  Net contract: **no authenticated or explicit user context ⇒ no implicit
  administrator.** Elevated internal operations must supply an explicit active-user
  context (`security_store.set_active_user` / the request middleware).
- **Remaining compatibility limitation:** none functional. In the (non-request) edge
  case, provenance stamps written without an active user become `None`
  ("Unauthenticated") instead of a fake `local-user` — a more honest record, not an
  authorization change. HTTP flows always have a real user and are unaffected.
- **Regression test:** `tests/current_user_fail_closed_test.py` (12 tests).

---

## 12. P3 findings (observations, not repaired)

- **Legacy ATLAS naming residue** (`ATLAS_*` env vars, `atlas_session` cookie,
  `atlas_security.db`, `X-ATLAS-USER-ID`). These are compatibility identifiers, not
  functional defects; the audit scope explicitly excludes a broad rename. No visible
  financial-services behavior leaks into the sports UI (confirmed by the contract
  test "expose no finance positioning").
- **No `.gitattributes` EOL normalization** on a Windows checkout → persistent
  `LF→CRLF` warnings. Cosmetic; no functional impact.
- **Two `uvicorn server.main:app` processes** were observed both attempting port
  8101 (only one can own it). Operational/launcher hygiene, not a code defect.
- **`persistence/health` is public** by design; verified it leaks no path/schema
  (returns `{ok, status}` only). Listed for completeness.

---

## 13. Repairs made

1. **`server/sports_datasets/registry.py`** — `_dataset_totals` now returns
   `EXPECTED_TOTALS["package_files"]` instead of the literal `335`, and imports
   `EXPECTED_TOTALS` from `constants.py`. Value-preserving; removes the duplicate
   authority (P2-1).
2. **`server/datasets/dataset_registry.py`** — `current_user()` no longer synthesizes
   a `role="admin"` context; it returns an explicit `UNAUTHENTICATED_CONTEXT`
   (`userId=None`, `role="none"`) when there is no active user and no real bootstrap
   `local-user`. `user_can_access()` gained a `if not user_id: return False` guard so
   an identity-less context cannot match a null-owner dataset (P2-2). Fail-closed;
   preserves explicit-user, admin, owner, viewer, and local-bootstrap behavior.

No other production code was changed. No Milestone B file, model artifact, or
runtime evidence was modified.

---

## 14. Tests added

1. **`tests/sports_dataset_totals_authority_test.py`** — two focused unit tests over
   a minimal in-memory fake package (no DB, no exchange, no training):
   - `test_package_files_references_validated_authority` — pins
     `totals["packageFiles"]` to `EXPECTED_TOTALS["package_files"]`.
   - `test_other_totals_still_derive_from_manifest` — guardrail that the change did
     not accidentally re-source manifest-derived totals from the constant.
2. **`tests/current_user_fail_closed_test.py`** — 12 hermetic unit tests (patch the
   two collaborators imported into the module namespace; no DB, no request, no
   training) proving: the fallback is not admin and carries no identity; the fallback
   is a defensive copy; `user_can_access`/`list_accessible_datasets` fail closed
   without context (including the null-owner case); explicit admin/owner/viewer and
   unrelated-user behavior is unchanged; explicit active-user and legitimate
   local-bootstrap admin contexts still work.

---

## 15. Verification results

Run once after the repair stabilized:

| Check | Result |
|-------|--------|
| `py_compile server/sports_datasets/registry.py` | **OK** |
| `pytest tests/sports_dataset_totals_authority_test.py` | **2 passed** |
| `node tests/sportsProductConversion.test.mjs` (sports contract) | **15 pass / 0 fail** |
| `tsc --noEmit -p tsconfig.json` (frontend types, Milestone B included) | **exit 0** |
| `git diff --check` | **clean** |

**Auth-context hardening pass (P2-2), verified once each:**

| Check | Result |
|-------|--------|
| `py_compile server/datasets/dataset_registry.py` | **OK** |
| `pytest tests/current_user_fail_closed_test.py` | **12 passed** |
| `pytest tests/dataset_storage_reconciliation_test.py tests/phase2a_registration_external_identity_test.py tests/dataset_library_recovery_test.py` (dataset authorization) | **107 passed** |
| `pytest tests/persistence_authorization_test.py` (cross-user containment) | **5 passed** |
| `git diff --check` | **clean** |

Full production build was **not** run: no frontend file was edited by this audit
(the `.tsx`/`.ts` changes are the pre-existing Milestone B checkpoint), and
`tsc --noEmit` already validates the types. The Milestone B participation pytest
baseline (22 pass) was captured before edits and not re-run, since nothing in that
path was modified.

---

## 16. Known inherited issues not repaired

- **P2-2** — now **RESOLVED** (auth-context hardening pass, 2026-08-18). No longer
  an inherited issue.
- **P3** legacy ATLAS naming residue, missing EOL normalization, duplicate uvicorn
  process — all out of the bounded repair scope.
- No inherited test failure was observed to be caused by this audit's change.

---

## 17. Recommended next engineering actions

1. **~~Close P2-2~~ — DONE.** `current_user()` now fails closed and the deny-by-default
   regression test is in place. If a future internal privileged operation genuinely
   needs elevated authority, introduce an *explicit* system/service context
   (`set_active_user` with a provisioned service identity) rather than reintroducing
   any implicit admin.
2. Add a `.gitattributes` (`* text=auto eol=lf`) to remove CRLF churn on Windows.
3. Add a small contract test that asserts the live `public_dataset` response keys are
   a superset of the fields `sportsEvidenceApi.ts` normalizers read, to catch future
   backend field renames at CI time rather than at runtime.
4. When Milestone B is resumed, keep the existence-gated UI and the strict Phase-3
   parent-identity matching in `public_dataset` — they are the mechanisms preventing
   unregistered/cross-study evidence from surfacing.

---

## 18. Exact files changed

- **Modified:** `server/sports_datasets/registry.py` (P2-1)
- **Modified:** `server/datasets/dataset_registry.py` (P2-2 auth-context hardening)
- **Added:** `tests/sports_dataset_totals_authority_test.py` (P2-1)
- **Added:** `tests/current_user_fail_closed_test.py` (P2-2)
- **Added (this report):** `docs/ASP_MODEL_STUDIO_ENGINEERING_INTEGRITY_AUDIT.md`

All changes left **unstaged**. HEAD unchanged at `f1e22d4`. Milestone B checkpoint
intact. No commit, no push, no remote change.

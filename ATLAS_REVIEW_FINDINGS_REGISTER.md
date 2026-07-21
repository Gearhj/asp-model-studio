# ATLAS Review Findings Register

Independent platform review — source workspace `C:\Users\james\ds-workflow-starter`. Review date: 2026-07-21.

**Methodology key**, used in the "Verification" field of every finding:
- **Runtime-verified**: reproduced against a live backend process (started with `uvicorn server.main:app`) using real HTTP requests (curl) and, where noted, direct inspection of the SQLite database state. Full reproduction commands are given.
- **Code-traced**: confirmed by reading the actual implementation end-to-end (not inferred from naming, routes, or reports). File and line citations given.
- **Static/inferred**: pattern identified from code structure but not executed; lower confidence, flagged explicitly.
- **Not verified**: brief asked for browser click-through UI verification. No browser-automation tool was available in this environment. Where a finding depends on that, it says so explicitly rather than fabricating an observation.

All test accounts and test data created during this review (`audit-user-a@test.local`, `audit-user-b@test.local`, `audit-lockout@test.local`, their sessions, and the projects/evidence they created) were deleted from `server/artifacts/security/atlas_security.db` and `server/data/atlas_local.db` at the end of the review. The review backend process was stopped. The only durable environment change made was syncing `.venv` packages (`pydantic`, `fastapi`, `uvicorn`, `starlette`) to the versions already pinned in the repository's own `requirements.txt` — see FND-014.

---

## CRITICAL

### FND-001 — Cross-user IDOR on the SQLite persistence layer: full read/write/delete of another user's projects and evidence
**Category:** Authorization | **Confidence:** High | **Verification:** Runtime-verified

**Affected files:** `server/persistence/persistence_router.py` (`get_project` L143-156, `update_project` L159-189, `delete_project` L192-213, `list_evidence`/`create_evidence` L261-309, and by the same pattern `runs`, `decisions`, `documentation`, `exports`, `workflow-state`)

**Reproduction:**
```
POST /api/auth/register  -> User A session cookie
POST /api/auth/register  -> User B session cookie
POST /api/projects (as A)              -> {"projectId": "project_bbef..."}
GET  /api/projects/{id} (as B)         -> 200, full project JSON returned
PUT  /api/projects/{id} (as B)         -> 200, project renamed, updatedBy = B's userId
DELETE /api/projects/{id} (as B)       -> 200, {"deleted": true}
GET  /api/projects/{id} (as A)         -> 404 "ATLAS project was not found"
```
Repeated for evidence: User B could list and read evidence titled "Confidential Evidence A" created by User A on the same project (`GET /api/projects/{id}/evidence` as B → 200, full record returned).

**Observed behavior:** Every endpoint requires *authentication* (`Depends(require_user)`) but performs **no resource-level authorization check**. Any authenticated user can read, overwrite, and permanently delete any other user's project and everything nested under it, by ID alone. Project IDs are returned directly in API responses (not secret), so no guessing is even required — but they are also low-entropy enough (`project_` + 32 hex chars, predictable structure) that this is a textbook IDOR regardless.

**Expected behavior:** `get_project`/`update_project`/`delete_project` and the evidence/runs/decisions/documentation/exports endpoints should call the authorization layer before acting.

**Root cause is precisely located and the fix is small:** `server/sharing/sharing_service.py` already implements exactly the needed check — `SharingService.check_permission(user, resource_type, resource_id, permission)` (L131-147) correctly handles owner-match, admin role, and explicit permission grants. **It is never called from `persistence_router.py`.** The `user` parameter in every affected endpoint is used only to *stamp* `owner_user_id`/`created_by`/`updated_by` on write, never to *gate* access.

**Risk:** In a multi-user deployment, any user can read, tamper with, or destroy any other user's project, model evidence, decisions, and documentation. This is a complete confidentiality and integrity failure for the platform's core object.

**Recommendation:** In every affected endpoint, call `sharing_service.check_permission(user, "project", project_id, "view"|"edit"|"admin")` (or the resource-appropriate type) and raise `HTTPException(403)` on denial, before touching the record. Add a regression test that performs exactly the reproduction above and asserts 403.

**Remediation size:** Medium (the authorization primitive already exists; wiring it into ~15 endpoints plus tests is the work).

**Blocks:** pilot, enterprise deployment, regulated production use. Does **not** block single-user local demo (no second user exists to exploit it), but does block any "trusted internal demo" that involves more than one login.

---

### FND-002 — Two parallel, disconnected "project" systems with no shared source of truth
**Category:** Architecture / Authorization | **Confidence:** High | **Verification:** Runtime-verified + code-traced

**Affected files:** `server/persistence/persistence_router.py` (new SQLite-backed project CRUD) vs. `server/projects/project_router.py` + `server/security/security_store.py` (`grant_project_access`, `list_project_access`, `user_can_access_project`) — the legacy JSON-registry ACL system.

**Reproduction:** Created a project through the new persistence API (`POST /api/projects`). Immediately queried the legacy ACL endpoint for the same ID: `GET /api/projects/{id}/access` → `200 {"access": []}` — not even the creating user is listed as owner in the legacy system. The legacy system has no knowledge the project exists.

**Observed behavior:** ATLAS has two independent "what is a project and who can touch it" subsystems that do not talk to each other. FND-001 exists specifically because the *newer* system (which is what the current frontend and `/api/projects` actually use) never calls the *older* system's ACL logic, and there is no reconciliation between them.

**Risk:** This is not just a bug site, it's a structural hazard: any future feature built against "project access" has a 50/50 chance of picking the unenforced path. It also means any security fix applied to only one system (e.g., patching `security_store.grant_project_access`) will not protect the other.

**Recommendation:** Pick one system as authoritative (the SQLite persistence layer is clearly the direction of travel given `server/persistence/`, `server/sharing/`, `server/registry/` were all built on it) and either delete the legacy JSON-ACL project code path or explicitly migrate it to delegate to `SharingService`. Do not maintain both.

**Remediation size:** Medium-to-Large (requires deciding which callers still depend on the legacy path).

**Blocks:** enterprise deployment, regulated production use.

---

### FND-003 — Account lockout is completely non-functional; the same bug silently drops audit records for every failed/denied login
**Category:** Authentication / Auditability | **Confidence:** High | **Verification:** Runtime-verified + code-traced

**Affected file:** `server/security/security_store.py`, function `authenticate()`, L370-419.

**Reproduction:**
```
Register audit-lockout@test.local
5x POST /api/auth/login with wrong password  -> 401 each time (LOCKOUT_THRESHOLD = 5)
Direct SQLite read of users table immediately after:
  failed_login_count = 0, locked_until = None   (expected: 5, and a future locked_until)
POST /api/auth/login with the CORRECT password -> 200 OK, immediate success, no lockout
```

**Root cause:** L373 opens `with connect() as conn:`. On a failed-password branch (L387-397), the code executes `conn.execute("UPDATE users SET failed_login_count = ..., locked_until = ...")` (L392-395) and writes an audit event (L396), **then raises the `generic` 401 HTTPException while still inside the `with` block** (L397). Python's `sqlite3.Connection.__exit__` rolls back the transaction when the block exits via an exception rather than normally. Every write made earlier in that same `with` block — the lockout counters *and* the `auth.login.failure` audit event — is silently discarded. The identical pattern exists for the "disabled user" (L379-381) and "account locked" (L383-385) denial branches: those audit entries are also rolled back and never persisted.

**Verification of the audit gap:** because the only branch that returns normally (without raising) is the success path (L398-419), that is the only branch whose audit event actually commits. `list_audit_events()` / `/api/audit/events` can therefore show a user logging in successfully with **zero prior failed attempts on record**, even if hundreds occurred. For a financial-services audit trail, this is a materially misleading gap, not just a missing feature.

**Risk:** (1) Brute-force / credential-stuffing protection is entirely absent in practice — the threshold and lockout duration configuration (`LOCKOUT_THRESHOLD`, `LOCKOUT_SECONDS`) is dead code. (2) The audit log — the artifact a validator or auditor would trust — has a systematic blind spot for exactly the events (failed logins, denied access to disabled/locked accounts) that security review most needs to see.

**Recommendation:** Restructure `authenticate()` so failure-path writes are committed before the exception propagates — e.g. `conn.commit()` immediately after each `conn.execute(UPDATE...)`/`audit_event(...)` pair and before `raise generic`, or move the `raise` outside the `with` block entirely (raise a sentinel, then raise the HTTPException after the block closes normally). Add a regression test that performs 5 failed logins, asserts `locked_until` is set via direct persistence read, asserts a subsequent correct-password login is rejected until the lockout window expires, and asserts the audit log contains 5 `auth.login.failure` events.

**Remediation size:** Small (a few lines; the logic itself is otherwise correctly designed).

**Blocks:** pilot, enterprise deployment, regulated production use. This single fix closes both an authentication gap and a governance/audit gap.

---

## HIGH

### FND-004 — Development environment does not match the repository's own pinned dependencies; venv contained corrupted partial installs
**Category:** Deployment readiness | **Confidence:** High | **Verification:** Runtime-verified

**Affected files:** `.venv/` (environment, not source), `requirements.txt`.

**Observed behavior:** `.venv/Scripts/python.exe -c "import fastapi"` failed outright (`ModuleNotFoundError: No module named 'pydantic_core.core_schema'`) before this review began. Diagnosis: the installed `pydantic` was `2.6.1` and `fastapi` was `0.110.0`, while `requirements.txt` pins `pydantic==2.7.4` and `fastapi==0.115.0` — the environment had drifted from the repo's own declared dependencies and the resulting mismatch broke imports entirely. `pip` additionally reported two corrupted/partially-removed package installs (`~cikit-learn`, `~ydantic-core` — mangled directory names left over from an interrupted install/uninstall).

**Action taken during this review:** Reinstalled `pydantic==2.7.4`, `fastapi==0.115.0`, `uvicorn[standard]==0.30.6` to match the versions already pinned in `requirements.txt` (not an upgrade beyond what the repo declares). After this, the app imports and starts cleanly. This was necessary to perform any of the runtime verification this review is built on, and is reported here rather than silently applied.

**Risk:** If this is representative of how the working environment is maintained, a fresh clone following the repo's own `requirements.txt` may currently install cleanly (untested — this review only had the pre-existing drifted venv to observe), but the drifted state found here shows there is no enforced mechanism (lockfile hash pinning, CI dependency check) keeping the working environment aligned with what's declared. The corrupted partial installs suggest at least one prior `pip install`/`uninstall` was interrupted and never cleaned up.

**Recommendation:** Add a CI step that does a clean `pip install -r requirements.txt` into a fresh venv and runs `pip check` / `python -c "from server.main import app"` on every commit. Consider `pip-compile`/lockfile pinning with hashes for reproducibility.

**Remediation size:** Small.

**Blocks:** external demo (a demo machine in this state fails at startup), pilot.

---

### FND-005 — No segregation of duties between model/case submission and validation approval
**Category:** Governance | **Confidence:** Medium | **Verification:** Code-traced

**Affected file:** `server/validation/validation_service.py`, `approve()` L345-376.

**Observed behavior:** `approve()` requires the caller to hold a role in `VALIDATOR_ROLES`, but never checks that the approver is a different person from whoever submitted/owns the case being approved. There is no "cannot approve your own submission" rule enforced server-side.

**Risk:** For a regulated model-validation workflow, self-approval is exactly the control a SOC2/MRM audit checks for. Its absence here means the platform cannot currently demonstrate maker-checker separation, even though the role system (`VALIDATOR_ROLES`) suggests the intent exists.

**Recommendation:** In `approve()`, look up the case's submitter/owner and reject if `approver_user_id == submitter_user_id` unless an explicit dual-role override is logged with justification.

**Remediation size:** Small.

**Blocks:** regulated production use.

---

### FND-006 — Credit Risk Studio and the newer Analytics/Statistical Engine use inconsistent "full dataset" enforcement (one now correct, confirms the other's earlier gap is closed)
**Category:** Analytical correctness | **Confidence:** High | **Verification:** Code-traced

**Affected files:** `server/analytics_engine/dataset_adapter.py` L13-28 (correct pattern); `server/credit_risk/woe_iv_engine.py` L111-113, `server/credit_risk/scorecard_engine.py` L114-116 (now also correct — see note).

**Observed behavior — this is a positive finding, recorded here because it corrects a CRITICAL issue raised in an earlier session of this engagement.** At the time of an earlier review pass, `woe_iv_engine.py` and `scorecard_engine.py` computed WOE/IV and scorecard points from `data_sample.csv` (a capped preview), which would have produced governed-looking numbers derived from an unrepresentative sample. **As of this review, both files now explicitly require `data_full.csv` and raise `HTTPException(409, "...sample artifacts are not valid for reporting.")` if only the sample exists.** The newer `analytics_engine/dataset_adapter.py` (used by the classification/regression/time-series/forecasting/experimentation diagnostics) independently implements the same correct pattern (`InsufficientDataError` if `data_full.csv` is missing).

**Residual concern:** SQL Data Studio (`server/sql_studio/sql_engine.py`) still explicitly operates on preview/sample rows only (`"previewLimitation": "Phase 12A registers preview/sample SQL results only."`, confirmed in an earlier pass of this engagement) and its `register-result` endpoint still allows promoting a sample-derived result to a governed dataset with only a soft description-field warning, not a hard block. This is the one place the "full dataset" discipline that credit-risk and analytics-engine now both enforce has not yet been applied.

**Recommendation:** Port the same `data_full.csv`-or-409 pattern from `dataset_adapter.py` into `sql_studio`'s `register-result` path, or explicitly stamp any sample-derived registered dataset as `SAMPLE — not valid for governed reporting` and block it from being selected as a WOE/IV, scorecard, or model-training input.

**Remediation size:** Small.

**Blocks:** pilot (if SQL Studio results are used for reporting), regulated production use.

---

### FND-007 — `optimization` and `analytics_engine` backends exist and are wired to dedicated frontend features; three declared workflow types (Reinforcement Learning, Computer Vision, Graph Analytics) have no dedicated implementation at all
**Category:** Functional completeness | **Confidence:** High | **Verification:** Code-traced

**Affected files:** `src/config/workflows.ts` (workflow definitions), `src/features/{optimization,llm,experimental-design}/`, `src/workflows/time-series/`, vs. absence of any `src/features/reinforcement-learning`, `src/features/computer-vision`, `src/features/graph-analytics`.

**Observed behavior:** `workflows.ts` declares 12 project types with real-sounding, domain-specific step lists (e.g. Graph Analytics: "Entity and Edge Definition," "Graph Construction"; Reinforcement Learning: "State Space," "Environment Definition"). Of these, Predictive Modeling, Credit Risk Studio, A/B Testing, Experimental Design, Optimization, Time Series & Forecasting, and LLM/Generative AI each have a dedicated frontend implementation and/or a connected backend (verified: `src/api/analyticsEngine.ts` and 30+ consuming files; `src/features/optimization/` with a real 10-file solver backend `server/optimization/`; `src/workflows/time-series/TimeSeriesProfile.tsx`). **Reinforcement Learning, Computer Vision, and Graph Analytics have no corresponding directory anywhere in `src/features` or `src/workflows`, and `WorkflowPlaceholderStep.tsx` has no branch for any of the three** (its only per-type branches are `isAbTestingWorkflow` and `projectType === "experimental-design"`). Selecting one of these three project types renders the fully generic step form — free-text "Objective," "Inputs," "Assumptions," "Validation," "Decision," "Rationale," "Notes" fields with no domain tooling — for every step, regardless of the specific, plausible-sounding step labels shown in the sidebar.

**Risk:** A user selecting "Graph Analytics" sees a professional-looking 6-step workflow (Project Context, Entity and Edge Definition, Graph Construction, ...) with no indication that none of those steps do anything graph-specific. This is the exact "misleading completeness" pattern the review brief asked to be flagged: a route and step labels exist; the analytical capability does not.

**Recommendation:** Either build minimal dedicated tooling for these three project types, or — much cheaper and honest in the interim — visibly label them "Early Access / Generic Workflow" in the UI and remove the domain-specific step labels until real functionality backs them.

**Remediation size:** Architectural (to build real tooling) or Small (to relabel honestly).

**Blocks:** external demo (if presented as equivalent to the other workflows), pilot.

---

## MEDIUM

### FND-008 — `react-router-dom` pulls in a `react-router` version with 10 known advisories (2 rated High by `npm audit`)
**Category:** Supply chain / dependency | **Confidence:** High | **Verification:** Runtime-verified (`npm audit --omit=dev`)

**Affected file:** `package.json` (`"react-router-dom": "^7.9.5"`), which resolves to a `react-router` 7.0.0-pre.0–7.11.0 range.

**Observed behavior:** `npm audit --omit=dev` reports 2 high-severity advisories against the resolved `react-router`, including open-redirect/XSS classes (GHSA-2w69-qvjg-hvjx, GHSA-9jcx-v3wj-wh4m, GHSA-2j2x-hqr9-3h42, and others in the same advisory family) and a DoS via unbounded path expansion. `npm audit fix` is reported available.

**Recommendation:** Run `npm audit fix` (or bump the pin explicitly) and re-verify the app still builds/routes correctly, since this is a routing library and a major-version-range jump risk exists.

**Remediation size:** Small, but verify regression afterward.

**Blocks:** external demo, pilot (routing-layer XSS/open-redirect in a product handling financial model data is not acceptable to ship past internal demo).

---

### FND-009 — Session cookie lacks the `Secure` flag whenever `ATLAS_LOCAL_DEV=true` and `ATLAS_HOSTED_MODE=false`, and both default to values that favor convenience
**Category:** Authentication | **Confidence:** High | **Verification:** Runtime-verified

**Affected file:** `server/security/security_router.py`, `set_session_cookie()`.

**Observed behavior:** Live login response: `set-cookie: atlas_session=...; HttpOnly; Max-Age=28800; Path=/; SameSite=lax` — no `Secure` attribute. This is intentional and correct *for local development over HTTP* (a `Secure` cookie would simply never be sent over plain HTTP, breaking local dev) — flagged here as MEDIUM only because it depends entirely on an operator correctly setting `ATLAS_HOSTED_MODE=true` (or `ATLAS_LOCAL_DEV=false`) before any non-local deployment, and there is no startup assertion (comparable to `assert_api_routes_authenticated`) that fails loudly if a non-local `ATLAS_CORS_ORIGINS` is configured while `ATLAS_LOCAL_DEV` is still `true`.

**Recommendation:** Add a startup check: if `ATLAS_CORS_ORIGINS` contains a non-localhost origin, require `ATLAS_HOSTED_MODE=true`, and refuse to start otherwise (mirroring the pattern already used for `assert_api_routes_authenticated`).

**Remediation size:** Small.

**Blocks:** enterprise deployment (as a defense-in-depth gap, not an active exploit today).

---

### FND-010 — HTML sanitizer for report/documentation rendering is a hand-rolled regex blocklist, not an allowlist parser
**Category:** Frontend security (XSS) | **Confidence:** High | **Verification:** Code-traced (carried forward from an earlier pass of this engagement; re-confirmed present)

**Affected files:** `src/lib/htmlSanitizer.ts` (`sanitizeReportHtml`), consumed via `src/lib/reportFormatting.ts` L163 and rendered with `dangerouslySetInnerHTML` in `src/components/ReportSectionContent.tsx` L115.

**Observed behavior:** `sanitizeReportHtml` strips a fixed list of tag names via regex and strips `on*=` attributes and `javascript:` URLs via regex. Regex-based HTML sanitizers are well-documented as bypassable (obfuscated/encoded payloads, unlisted tags like `<svg>`/`<math>` with event handlers, attribute-based vectors the blocklist doesn't enumerate). The passthrough path is reached whenever evidence/documentation narrative content begins with a tag or contains `class="atlas-"` — both attacker-influenceable if narrative text is user-entered (documentation sections, evidence summaries).

**Recommendation:** Replace with an allowlist-based sanitizer (e.g., DOMPurify configured with an explicit allowed tag/attribute list). Keep the plain-text/escape-first path as the default for anything not already known-safe generated HTML.

**Remediation size:** Small.

**Blocks:** pilot, enterprise deployment.

---

### FND-011 — Clean-copy sync target is stale relative to the active source workspace
**Category:** Deployment / process | **Confidence:** High | **Verification:** Runtime-verified (`diff -rq`)

**Affected paths:** `C:\Users\james\Projects\ATLAS\atlas-app` vs. `C:\Users\james\ds-workflow-starter`.

**Observed behavior:** A directory diff at the start of this review found material differences already present before any of this review's own edits: `src/apps/ModelingApp.tsx`, `src/lib/selectDecisionSupport.ts`, `src/steps/AuthPages.tsx`, `src/steps/Step06_Train.tsx`, `src/steps/Step08_Evaluation.tsx`, `src/steps/WorkflowPlaceholderStep.tsx`, `server/training/trainer.py`, `server/training/training_job_service.py`, and `server/requirements.txt` all differ between the two trees, and `src/state/stepOrder.tx` exists only in the clean copy (a file the source workspace no longer has — meaning the clean copy is not simply "behind," it also contains a file that was since removed/renamed in source). This review's own session added further drift (the A/B Testing workflow fix from earlier in this engagement, and no sync was run afterward).

**Risk:** Whoever or whatever consumes the clean copy (a packaging step, a demo environment, a second developer) is working from meaningfully different code than what has actually been reviewed and fixed. Auth pages and the training pipeline differing is particularly concerning given this review's security findings concern exactly those areas.

**Recommendation:** Run `npm run sync:atlas` (the existing `scripts/sync-atlas-clean-copy.ps1`) after any session that touches source, and add a CI or pre-commit check that fails if the two trees diverge beyond an explicit allowlist (e.g., local `.db` files, which is expected and fine — `server/data/atlas_api_context_*.db` files present only in source are harmless per-run artifacts, not a real gap).

**Remediation size:** Small (process fix, not code).

**Blocks:** external demo (if the demo is run from the clean copy).

---

## LOW / INFORMATIONAL

### FND-012 — Weak-password rule and account creation behave correctly (positive finding)
**Category:** Authentication | **Confidence:** High | **Verification:** Runtime-verified

Registering with password `"password"` was correctly rejected (`400 {"detail":"Choose a less common passphrase."}`); PBKDF2-SHA256 with per-user random salt at 260,000 iterations is used for storage (`server/security/security_store.py` `hash_password`). Recorded as a strength, not a gap — but see FND-013 for the residual recommendation.

### FND-013 — Password hashing algorithm is PBKDF2, not a memory-hard KDF
**Category:** Authentication | **Confidence:** High | **Verification:** Code-traced

**Affected file:** `server/security/security_store.py`. The platform's own `/api/security/diagnostics` endpoint already self-reports this as a "warning" ("Install argon2id/bcrypt for production-grade hosted deployment") — the gap is self-documented, not hidden. Recommendation: migrate to argon2id before any hosted deployment. **Remediation size:** Small-Medium (migration must support re-hashing existing credentials on next login).

### FND-014 — Startup-time route-authentication guard is real and currently passing (positive finding)
**Category:** Authorization | **Confidence:** High | **Verification:** Runtime-verified

`server/main.py` `assert_api_routes_authenticated()` walks the full FastAPI dependency graph at app-construction time and raises `RuntimeError` if any `/api/*` route (outside an explicit small allowlist: health, persistence health, login, register, password reset) lacks a `require_user` dependency anywhere in its dependency chain. Confirmed this executes successfully at import time against the current 381-route app (no exception raised). This is a strong, low-maintenance-cost control against the class of bug this engagement flagged in an earlier pass (ungated routers) — and it does not, and structurally cannot, catch FND-001 (which is a *resource-level* authorization gap on routes that are correctly *authenticated*). Recorded as a genuine strength.

### FND-015 — Python/R code execution is now disabled by default and requires an explicit external sandbox command; environment variables passed to any executed code are allowlisted rather than a full `os.environ` copy
**Category:** Code execution | **Confidence:** High | **Verification:** Runtime-verified + code-traced

`server/python_execution.py`: `run_python_request` returns `{"ok": false, "status": "unavailable", ...}` unless `ATLAS_CODE_SANDBOX_COMMAND` is set to an operator-provided sandbox invocation (e.g., a container wrapper). Confirmed live: a fresh backend with no sandbox command configured refused to execute arbitrary Python (`"Python execution is disabled until ATLAS_CODE_SANDBOX_COMMAND points to an approved OS/container sandbox."`), including attempts to read environment variables or list server files. `execution_env()` builds the child process environment from an explicit `SAFE_ENV_KEYS` allowlist plus two ATLAS-specific markers, not `os.environ.copy()`. This is a substantial improvement over the raw, unauthenticated, full-environment subprocess execution found in an earlier pass of this engagement, and the router is now also gated by `Depends(require_user)`. **Residual risk, not re-scored here as it cannot be verified without a real deployment:** ATLAS does not ship or validate a specific sandbox implementation — the security of "enabled" execution is entirely dependent on what an operator points `ATLAS_CODE_SANDBOX_COMMAND` at. A naive value (e.g., a bare `python {script}` with no container/namespace isolation) would silently restore full code-execution risk while appearing "configured." Recommend the platform ship a reference-validated sandbox command and refuse to start execution against commands that don't match a known-safe pattern.

---

## Findings not fully verified in this pass (explicitly flagged, not fabricated)

- **Browser-driven UX/completion-state walkthroughs** (Phase 3/7 of the audit brief) — no browser-automation tool was available in this environment. Findings about page layout, visual hierarchy, and click-through completion states in this review's companion `ATLAS_WORKFLOW_AND_UX_REVIEW.md` are based on component source review (what renders, what a click handler does, what state it writes/reads), not an observed rendered browser session. Any claim in that document about literal visual appearance is qualified as such.
- **Concurrency / load behavior at 100–100,000 users or multi-million-row datasets** — assessed by code inspection only (in-memory `DATASTORE` singleton, synchronous training calls, SQLite as the persistence engine); no load test was run. See `ATLAS_REMEDIATION_ROADMAP.md` for what inspection supports.
- **Full audit of all 53 test files' individual assertions** — a representative sample was read in depth (credit risk, A/B testing/experimentation, persistence, workflow navigation — several read to the point of running them and diagnosing failures in an earlier pass of this engagement). The pattern found in that sample (many `.mjs` tests assert against component *source text* via regex rather than executing behavior) is characterized in `ATLAS_TEST_COVERAGE_AND_CONFIDENCE_REVIEW.md`, but not every one of the 53 files was individually read end-to-end.

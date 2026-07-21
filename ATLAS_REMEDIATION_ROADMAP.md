# ATLAS Remediation Roadmap

Cross-references `ATLAS_REVIEW_FINDINGS_REGISTER.md` (FND-IDs) throughout. Organized by the timeboxes requested in the review brief; each item has an acceptance criterion that is a behavior, not a code change, so completion can be verified the same way this review found the problem (live requests, not just a diff).

---

## Immediate security repairs — 1 to 3 days

### R1. Enforce resource-level authorization on the persistence layer
- **Objective:** Close FND-001 (cross-user IDOR on projects/evidence/runs/decisions/documentation/exports).
- **Subsystem:** `server/persistence/persistence_router.py`.
- **Reason:** Live-reproduced full read/write/delete of another user's project and evidence with zero special tooling — this is the single most severe issue found.
- **Prerequisite:** None — `SharingService.check_permission()` already exists and is correct (proven by its own passing unit tests).
- **Estimated effort:** 1-2 days (wiring + tests) for an engineer already familiar with the router.
- **Acceptance criteria:** Register two users. User B's `GET`/`PUT`/`DELETE` against a project or evidence record owned solely by User A returns 403. User A's own access is unaffected. A regression test performing exactly this sequence exists and is in CI.

### R2. Fix the login-failure transaction-rollback bug
- **Objective:** Close FND-003 (account lockout and failed-login audit logging both non-functional).
- **Subsystem:** `server/security/security_store.py`, `authenticate()`.
- **Reason:** Brute-force protection is currently dead code; the audit trail silently drops every failed/denied login, which is independently a governance defect.
- **Prerequisite:** None.
- **Estimated effort:** Half a day (the fix is a few lines — commit before raising, or raise outside the `with` block); a further half day to grep the codebase for the same `with connect() as conn: ... raise` pattern elsewhere, since this bug class may not be unique to `authenticate()`.
- **Acceptance criteria:** 5 failed logins against one account, followed by a direct DB read, shows `failed_login_count == 5` and a non-null `locked_until`. A subsequent correct-password login is rejected until the lockout window passes. The audit log contains 5 `auth.login.failure` events for the sequence.

### R3. `npm audit fix` for the react-router advisories
- **Objective:** Close FND-008.
- **Subsystem:** `package.json`/`package-lock.json`.
- **Reason:** Two high-severity advisories (open redirect/XSS class) in a routing library actively used for every page.
- **Prerequisite:** None.
- **Estimated effort:** Under a day, including a smoke-test pass on navigation after the bump.
- **Acceptance criteria:** `npm audit --omit=dev` reports 0 high/critical; `npm run build` and the existing navigation-related test suites pass.

---

## Critical workflow repairs — 1 to 2 weeks

### R4. Retire or merge the legacy project-ACL system
- **Objective:** Close FND-002 — one authoritative source of truth for "who can access this project."
- **Subsystem:** `server/projects/project_router.py`, `server/security/security_store.py` (`grant_project_access`/`user_can_access_project`) vs. `server/persistence/` + `server/sharing/`.
- **Reason:** A second, disconnected authorization system is a standing invitation for the next feature to wire into the wrong one, exactly as happened with FND-001.
- **Prerequisite:** R1 complete (so there is a known-good target to consolidate onto).
- **Estimated effort:** 3-5 days, mostly in finding and updating any remaining callers of the legacy path.
- **Acceptance criteria:** A single code search for "project access check" finds exactly one implementation. Any frontend or backend caller of the legacy endpoints either is removed or transparently delegates to `SharingService`.

### R5. Segregation of duties in Validation Center approvals
- **Objective:** Close FND-005.
- **Subsystem:** `server/validation/validation_service.py`, `approve()`.
- **Reason:** A regulated model-validation workflow without maker-checker separation cannot pass a real MRM review.
- **Prerequisite:** None.
- **Estimated effort:** 1-2 days including a test.
- **Acceptance criteria:** A user who submitted/owns a validation case cannot call `approve()` on it and receives an explicit, logged denial; a different validator can.

### R6. Replace the regex HTML sanitizer with an allowlist parser
- **Objective:** Close FND-010.
- **Subsystem:** `src/lib/htmlSanitizer.ts`, `src/components/ReportSectionContent.tsx`.
- **Reason:** Regex blocklists are a known-weak XSS defense for a code path that renders user/AI-generated narrative.
- **Prerequisite:** None.
- **Estimated effort:** 1-2 days (integrate DOMPurify or equivalent, configure an explicit allowed tag/attribute set, verify existing report rendering still looks correct).
- **Acceptance criteria:** A payload like `<img src=x onerror=alert(1)>` embedded in evidence/documentation narrative renders inert.

### R7. Fix the "throw-before-navigate" save pattern wherever else it exists
- **Objective:** Prevent recurrence of the A/B Testing "Mark Complete does nothing" class of bug in other workflows.
- **Subsystem:** `src/steps/WorkflowPlaceholderStep.tsx` and any other step component with a save-then-navigate handler.
- **Reason:** The root cause (a local-storage write failure, usually caused by unrelated large keys, throwing before navigation) is a pattern, not a one-off; it was found and fixed in A/B Testing this engagement but not audited elsewhere.
- **Prerequisite:** None.
- **Estimated effort:** 2-3 days to audit and fix any additional instances.
- **Acceptance criteria:** Every "Mark Complete & Next" style handler in the codebase separates "attempt to persist locally" (best-effort, non-blocking on failure) from "advance workflow state and navigate" (always attempted), matching the pattern now in place for A/B Testing.

### R8. Add router-level authorization regression tests
- **Objective:** Close the test-confidence gap identified in `ATLAS_TEST_COVERAGE_AND_CONFIDENCE_REVIEW.md` §2/§5.
- **Subsystem:** `tests/admin_sharing_backend_test.py` (extend) or a new `tests/api_authorization_test.py`.
- **Reason:** The existing `SharingService` unit tests are strong but do not exercise the HTTP layer where FND-001 actually lived; without this, the same class of bug can reappear silently.
- **Prerequisite:** R1.
- **Estimated effort:** 2-3 days, reusing the existing two-user fixture pattern already present in `admin_sharing_backend_test.py`.
- **Acceptance criteria:** For every resource type under `persistence_router.py`, a test exists asserting: owner succeeds, unrelated authenticated user gets 403, unauthenticated caller gets 401.

---

## Pilot readiness — 2 to 6 weeks

### R9. Migrate password hashing to argon2id
- **Objective:** Close FND-013 (self-flagged by the platform's own diagnostics).
- **Subsystem:** `server/security/security_store.py`.
- **Prerequisite:** None; must support transparent re-hash of existing credentials on next successful login (don't force a mass password reset).
- **Estimated effort:** 3-5 days.
- **Acceptance criteria:** New credentials are stored as argon2id; existing PBKDF2 credentials continue to authenticate and are upgraded in place on next login; `/api/security/diagnostics` no longer warns.

### R10. Enforce secure-cookie / non-local-deployment startup guard
- **Objective:** Close FND-009's residual risk.
- **Subsystem:** `server/main.py` (extend the existing `assert_api_routes_authenticated` pattern).
- **Prerequisite:** None.
- **Estimated effort:** 1 day.
- **Acceptance criteria:** Starting the app with a non-localhost `ATLAS_CORS_ORIGINS` entry while `ATLAS_HOSTED_MODE` is false and `ATLAS_LOCAL_DEV` is true fails fast with a clear error, mirroring how `assert_api_routes_authenticated` already fails fast on an unauthenticated route.

### R11. Close the SQL Data Studio sample-to-governed-dataset gap
- **Objective:** Complete FND-006 (credit-risk and analytics-engine already fixed; SQL Studio's `register-result` path is the one place left).
- **Subsystem:** `server/sql_studio/sql_router.py`/`sql_engine.py`.
- **Prerequisite:** None; the correct pattern already exists in `server/analytics_engine/dataset_adapter.py` to copy from.
- **Estimated effort:** 2-3 days.
- **Acceptance criteria:** A SQL Studio result derived only from preview/sample rows cannot be registered as a dataset usable for model training/WOE-IV/scorecard input without an explicit, hard-blocking warning equivalent to the 409 credit-risk now returns.

### R12. Add CSRF token scheme and independent rate limiting
- **Objective:** Defense-in-depth beyond `SameSite=Lax` and the (now-fixed) lockout.
- **Subsystem:** API-wide middleware.
- **Prerequisite:** R2.
- **Estimated effort:** 1 week.
- **Acceptance criteria:** State-changing requests without a valid CSRF token are rejected; login attempts are throttled per-IP independent of the per-account lockout counter.

### R13. CI dependency-drift guard
- **Objective:** Prevent recurrence of FND-004.
- **Subsystem:** CI pipeline (not currently inspected in depth — no CI config was reviewed as part of this pass; add one if none exists).
- **Prerequisite:** None.
- **Estimated effort:** 1-2 days.
- **Acceptance criteria:** A CI job installs `requirements.txt` into a clean venv and runs `python -c "from server.main import app"` and `pip check` on every commit; a broken/drifted environment fails CI rather than being discovered during a review.

### R14. Path-traversal hardening on dataset version reads
- **Objective:** Validate `version_id` against an allowlist pattern and dataset membership before filesystem access.
- **Subsystem:** `server/datasets/dataset_registry.py`.
- **Prerequisite:** None.
- **Estimated effort:** 1 day.
- **Acceptance criteria:** A crafted `version_id` containing `../` sequences is rejected with 400, not resolved to a path outside the dataset's version directory.

### R15. Real browser end-to-end test layer for the two most-used workflows
- **Objective:** Close the entirely-absent browser-e2e tier identified in `ATLAS_TEST_COVERAGE_AND_CONFIDENCE_REVIEW.md` §5-6.
- **Subsystem:** New `tests/e2e/` (Playwright recommended given the React/Vite stack).
- **Prerequisite:** None.
- **Estimated effort:** 1-2 weeks for Predictive Modeling and A/B Testing coverage.
- **Acceptance criteria:** A real browser session can fill a step, click "Mark Complete & Next," navigate, refresh, and the CI-run test asserts the text is still present — the exact sequence this review could not itself execute for lack of a browser tool, and the exact sequence that was broken in A/B Testing before this engagement's fix.

---

## Enterprise readiness — 1 to 3 months

### R16. Per-user/per-project scoping of predictive-modeling session state
- **Objective:** Remove the in-memory `DATASTORE`/`RESULTS` singleton as a source of cross-user interference.
- **Subsystem:** `server/core/dataset_store.py`, `server/training/`, `server/evaluation/`, and every router that reads `DATASTORE`/`RESULTS` directly.
- **Reason:** Two users training concurrently on the same backend process today would corrupt each other's session — invisible in single-user local use, a hard blocker the moment a second concurrent user exists.
- **Prerequisite:** R1 (fix the object-level authorization first; this is the session-state equivalent of the same problem).
- **Estimated effort:** 3-6 weeks — this is the largest single architectural item in the roadmap outside R17.
- **Acceptance criteria:** Two authenticated users can run the Predictive Modeling workflow concurrently against different datasets without either seeing the other's data/results.

### R17. Migrate Credit Risk Studio onto shared modeling primitives
- **Objective:** Stop hand-porting the same leakage/discipline fixes twice (per `ATLAS_WORKFLOW_AND_UX_REVIEW.md` §4).
- **Subsystem:** `server/credit_risk/`, `server/training/`, `server/splitting/`.
- **Prerequisite:** R16 ideally lands first or concurrently, since both touch the same modeling core.
- **Estimated effort:** 4-8 weeks (Large/Architectural).
- **Acceptance criteria:** Credit Risk Studio's training/split logic calls the same shared functions Predictive Modeling uses, rather than maintaining a parallel implementation; a fix applied once (e.g., a new leakage rule) is automatically effective in both workflows.

### R18. Sandbox-command validation for code execution
- **Objective:** Close the residual risk in FND-015 — ATLAS currently trusts whatever `ATLAS_CODE_SANDBOX_COMMAND` an operator configures.
- **Subsystem:** `server/python_execution.py`.
- **Prerequisite:** None.
- **Estimated effort:** 1-2 weeks (define and ship a reference sandbox invocation, e.g., a validated container-runtime wrapper, and reject configured commands that don't match a known-safe shape).
- **Acceptance criteria:** ATLAS ships (or documents and validates against) at least one concrete, tested sandbox command; a configured command that doesn't provide filesystem/network isolation is flagged in `/api/security/diagnostics` rather than silently trusted.

### R19. Decide and build real tooling (or explicit relabeling) for Reinforcement Learning, Computer Vision, Graph Analytics
- **Objective:** Close FND-007's misleading-completeness gap.
- **Subsystem:** `src/features/` (new directories) or `src/config/workflows.ts` (relabel).
- **Prerequisite:** Product decision on which (if any) of the three to invest in before an enterprise sales cycle surfaces them.
- **Estimated effort:** Relabeling: under a week. Real tooling per workflow: 4-8 weeks each (Architectural).
- **Acceptance criteria:** Either dedicated functional tooling exists matching the depth of Optimization/Time Series, or the UI clearly marks these as early-access/generic before an enterprise buyer or pilot customer can be misled by the step labels.

---

## Longer-term platform hardening — 3 to 6 months

### R20. Unify the audit-log and workflow-state persistence mechanisms
- **Objective:** One audit trail, one workflow-state store — remove the three-way split (localStorage / SQLite persistence / legacy JSON registry) identified in `ATLAS_WORKFLOW_AND_UX_REVIEW.md` §1.
- **Subsystem:** Platform-wide.
- **Prerequisite:** R4, R16, R17 — this is the consolidation that those items are each individually working toward.
- **Estimated effort:** 2-3 months.
- **Acceptance criteria:** Workflow completion state, audit events, and project/evidence records each have exactly one authoritative store; the legacy JSON project registry and its `.gitignore`-excluded artifacts are formally retired.

### R21. Full statistical/analytical correctness re-audit across all workflows
- **Objective:** Extend the leakage/full-dataset/calibration discipline already verified for credit risk and the new analytics engine to every remaining workflow (Optimization solver correctness, Time Series backtesting discipline, general Predictive Modeling leakage across all preprocessing steps).
- **Subsystem:** `server/optimization/`, `server/analytics_engine/modules/time_series.py`/`forecasting.py`, `server/preprocessing/`, `server/splitting/`, `server/training/`.
- **Prerequisite:** None, but most efficient once R16/R17 land so there is one modeling core to audit instead of several.
- **Estimated effort:** 6-8 weeks of dedicated senior-DS/validator time.
- **Acceptance criteria:** A documented, per-workflow statistical-correctness sign-off equivalent in rigor to what this review was able to establish for credit-risk WOE/IV and the classification-diagnostics module.

### R22. Formal model-governance immutability audit
- **Objective:** Verify (not just infer from absence of a `delete` method) that Registry, Validation, and Monitoring records cannot be silently altered post-approval, and reconcile the inconsistent deletion posture found across those three modules (Registry/Validation appear append-only; Monitoring has a `remove_metric` deletion capability).
- **Subsystem:** `server/registry/`, `server/validation/`, `server/monitoring/`.
- **Prerequisite:** R5, R20.
- **Estimated effort:** 3-4 weeks.
- **Acceptance criteria:** A written, tested policy for what is and isn't mutable post-approval across all three modules, with tests asserting an approved record cannot be altered without creating a new version.

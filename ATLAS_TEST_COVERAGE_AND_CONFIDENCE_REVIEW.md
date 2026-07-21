# ATLAS Test Coverage and Confidence Review

## 1. Inventory

53 test files under `tests/`: 33 `.mjs` (Node's built-in `node:test`, exercising frontend source and, for a subset, calling a live backend) and 20 `.py` (`unittest`, exercising backend services directly), covering roughly 40 `npm run test:*` scripts plus two Python-only scripts. Total backend Python test volume alone is ~2,785 lines. This is a substantial, actively maintained suite, not a token gesture — the question this report answers is not "do tests exist" but "what do they actually prove," per the review brief's explicit instruction not to credit test names or file existence as proof of correctness.

## 2. The central finding: a real, well-designed unit test coexists with a real, live-reproducible bug it cannot see

This is the clearest illustration of test-confidence risk found in this review, and it is worth walking through in full because it explains *why* FND-001 (cross-user IDOR, see `ATLAS_REVIEW_FINDINGS_REGISTER.md`) shipped past a test suite that includes a file literally named `admin_sharing_backend_test.py`.

That file (`tests/admin_sharing_backend_test.py`) is a genuinely good unit test: it spins up a real, isolated temp SQLite database per test (not mocked), exercises `SharingService.share_resource`, `check_permission`, `revoke_share`, group-based sharing, access requests, and share links, and asserts the correct allow/deny outcome at every step (e.g., `test_direct_share_grants_and_revokes_project_access` proves that after a grant, `check_permission` returns `allowed: True`, and after revocation, `allowed: False`). **Every one of these assertions is true and passes.** The `SharingService` class is correctly implemented.

What the test never does is call the actual HTTP layer that a real client uses — `GET /api/projects/{id}`, `PUT /api/projects/{id}`, `DELETE /api/projects/{id}` in `server/persistence/persistence_router.py`. Those endpoints, as this review verified live (FND-001), never call `SharingService.check_permission` at all. The unit test proves the lock mechanism works in isolation; it does not, and structurally cannot, prove the door is actually fitted with that lock. This is not a subtle testing-philosophy nitpick — it is the exact reason a CRITICAL, fully-reproducible-in-under-two-minutes vulnerability shipped with a green test suite.

**This pattern is the single largest source of false confidence in the codebase**, and it is worth searching for deliberately: any other service-layer class with a well-tested unit suite should be checked for whether the router that's supposed to call it actually does.

## 3. Frontend `.mjs` tests: mostly source-text assertions, not behavior

A representative sample was read in full this engagement (`creditRiskStudio.test.mjs`, `experimentation.test.mjs`, `workflowNavigationState.test.mjs`, `persistence.test.mjs`, `openProjectRoute.test.mjs`, `regression.test.mjs` — six files, read completely, not skimmed):

- **`creditRiskStudio.test.mjs`** (103 assertions): every one is `assert.match(sourceFileText, /some regex/)` — reading a `.tsx` file as a raw string and checking a substring/pattern exists. Example: `assert.match(page, /"Traditional Scorecard Path"/)`. This proves the string is present in the source; it proves nothing about whether the component renders it, whether a click does anything, or whether the underlying calculation is correct. Recall from this engagement's earlier pass: the platform had a real, live target-leakage bug (`RiskPerformance` appearing in IV ranking with IV=17) that this exact test file did not catch, for exactly this reason — it checks for the presence of exclusion-related regex patterns in the frontend source, not that the backend engine actually excludes the column.
- **`experimentation.test.mjs`**: same pattern. This engagement modified this file directly (as part of fixing the A/B Testing "Mark Complete" bug) and found first-hand that one of its assertions was pinned to an exact, now-superseded string in the save-handler's diagnostic message (`"Browser cache quota hit. Pruned stale A/B Testing cache and retried save successfully."`) — a string that existed in source but whose *presence* was being used as a proxy for "the quota-retry behavior works," when in fact the behavior it nominally covered (graceful recovery from a full-quota save) was the very thing that was broken. The test could not distinguish "the feature works" from "the feature's error message happens to still be spelled the same way."
- **`workflowNavigationState.test.mjs`**: same pattern; this engagement also had to update one assertion here (`assert.match(workflowPlaceholder, /setState\(loadNodeState\(projectId, step\.id\)\)/)`) because it was pinned to one specific expression form; a semantically identical refactor (assigning to an intermediate variable first) failed the test despite being correct.
- **`persistence.test.mjs`, `regression.test.mjs`**: not fully characterized line-by-line in this pass beyond confirming they pass; recommend the same "does it call source-as-text or actually execute the code path" audit be applied to the remaining ~27 unreviewed `.mjs` files before trusting their names.

**Consequence:** a large fraction of the `.mjs` suite functions as a *documentation-drift detector* (did someone remove a label, a route string, a button) rather than a *behavior-correctness suite*. That has real value (it does catch accidental deletions and typos in user-facing strings), but it is a materially weaker guarantee than the test names suggest, and it is exactly the kind of test the review brief warned against crediting.

## 4. Backend `.py` tests: generally stronger, with the sharing-vs-router gap as the standout risk

The Python `unittest` files that were read this pass (`admin_sharing_backend_test.py` in full; others inventoried by name/size) follow a better pattern: real service classes, real temp SQLite databases per test, real assertions on returned data — not mocks of the thing being tested. This is meaningfully more trustworthy than the `.mjs` source-matching pattern. The gap is not in test *quality* but test *scope*: these tests exercise services directly, one layer below the HTTP router, and — per §2 — nothing found in this review closes the loop by testing the router layer itself for the authorization checks that matter most.

`python_execution_test.py` exists and (by name/location) should cover the sandboxing behavior confirmed live in this review (FND-015); not read function-by-function this pass — recommend verifying it actually asserts `ok: false` when no sandbox command is configured (the correct, current behavior) rather than asserting the old unsandboxed-execution behavior.

## 5. What's missing entirely

- **No test found (in the files reviewed) that performs a genuine cross-user HTTP request sequence** — i.e., register two users, have user B call an endpoint for user A's resource, assert 403/404. This is precisely the test that would have caught FND-001, and it does not require any new test infrastructure to write: `admin_sharing_backend_test.py` already has the exact two-user (`ADMIN`, `ANALYST`) fixture pattern needed; it simply needs to call the FastAPI router (via `TestClient` or an equivalent) instead of only the service class.
- **No test found that verifies the account-lockout threshold via direct persistence inspection** (which is exactly how this review found FND-003 — a live login attempt sequence plus a direct SQLite read of `failed_login_count`/`locked_until`).
- **No test found that asserts the audit log contains an entry for a failed or denied login** — the same bug (FND-003) silently defeats this, and no test currently checks for it.
- **No browser end-to-end test layer exists** (e.g., Playwright/Cypress) — everything is either Node reading source text or Python calling service classes directly. There is no test in the suite that would have caught the A/B Testing "button does nothing" bug the way an actual user experienced it (a real click, in a real browser, against real `localStorage` quota pressure from *unrelated* keys). This is the gap between "the code that handles a click exists and contains the right strings" and "clicking the button in a real session with realistic accumulated state actually works," and it is a full tier of the test pyramid that is currently absent.
- **No dedicated leakage-regression test found** for the general Predictive Modeling pipeline (as opposed to the credit-risk-specific `credit_risk_leakage_test.py`, whose contents were not fully read this pass but whose existence at least targets the right concern).

## 6. Recommended test pyramid (not written in full during this review, per review brief scope)

| Layer | Current state | Recommended addition |
|---|---|---|
| Unit (service-level) | Present, generally well-built (e.g., `SharingService` tests) | Continue; this layer is a genuine strength |
| Repository/persistence | Present via real temp-SQLite fixtures | Continue |
| API integration (router-level, via `TestClient`, asserting HTTP status + payload for both the authorized and unauthorized caller) | **Largely absent** — this is the single highest-value gap | Add for every resource type in `persistence_router.py`: authorized-owner success, unauthorized-other-user 403, unauthenticated 401 |
| Browser end-to-end | **Absent entirely** | Add a minimal Playwright suite covering the core "fill a step, click complete, navigate, refresh, confirm persistence" loop for at least Predictive Modeling and A/B Testing |
| Security-specific (lockout, audit-completeness, IDOR, sandbox-off-by-default) | **Absent** | Add the four tests described in §5 directly; they are cheap given existing fixtures |
| Statistical/analytical correctness (leakage, calibration, full-vs-sample enforcement) | Partially present (`credit_risk_leakage_test.py` exists; scope not fully verified) | Verify existing coverage against the specific `RiskPerformance`/`bad_flag`/`atlas_split` exclusion rules and extend to the general Predictive Modeling pipeline |
| Persistence/restart | Present (`persistence.test.mjs`, `sqlitePersistence.test.mjs` + paired backend test) | Continue; add a cross-workflow-state consistency check per the "stale project state" concern in the workflow report |
| Cross-user access isolation | **Absent as an executed test; present only as an unexploited capability in `SharingService`'s own unit tests** | This is the top-priority addition — see §5 |

## 7. Bottom line

The test suite is larger and, in its Python half, better-constructed than a superficial read would suggest — this is not a "the tests are fake" finding. The specific and important gap is structural: the layer that would catch authorization bugs (API integration tests that assert a *different* user is denied) does not exist, while the layer below it (service unit tests) is strong enough to create false confidence that the system as a whole is protected. Closing that one gap — router-level, two-user, allow/deny API tests — would have caught this review's single most severe finding before it ever reached a live review, and is the highest-leverage testing investment available to the team right now.

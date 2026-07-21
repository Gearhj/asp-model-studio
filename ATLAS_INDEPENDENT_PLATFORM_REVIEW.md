# ATLAS — Independent Platform Review (Executive Report)

**Reviewer method note, stated up front because it matters for how much weight to put on this document:** this review did not stop at reading code. The backend was actually started (after repairing a broken local dependency environment — see below), and the most consequential claims in this report were verified against a live, running instance using real HTTP requests, two independently registered user accounts, and direct database inspection — not inferred from route names, component names, or prior completion reports. Where something could not be verified this way (primarily: literal browser rendering, since no browser-automation tool was available in this environment, and load/concurrency behavior at scale), this report says so explicitly rather than presenting inference as observation. Full evidence, file/line citations, and reproduction steps for every claim below live in the six companion documents this review also produced.

## What ATLAS is today

ATLAS is a genuinely substantial, actively-developed data-science and model-governance platform for financial institutions: a FastAPI backend with 381 API routes, a React/Vite frontend, and real implementations behind most of its headline capabilities — not a demo shell. The core Predictive Modeling pipeline (14 steps, project context through model monitoring), Credit Risk Studio (WOE/IV, scorecard, AI/ML underwriting challenger), A/B Testing, Experimental Design, Optimization (a real 10-file solver backend with a transportation-problem template), a new statistical/analytical engine (real ROC/KS/calibration/decile computation via scikit-learn), and a maturing governance layer (Registry, Validation Center with a challenge/response/approval flow, Monitoring Center, Admin console, Sharing, Audit Log) all exist as working code, gated behind real authentication, and this review found and fixed a live, user-reported workflow bug (the A/B Testing "Mark Complete" button) in the course of the engagement.

It is also, right now, a platform with **one critical, live-reproducible authorization defect that would let any two registered users read, overwrite, and delete each other's projects and evidence**, and a second bug that quietly defeats both brute-force account-lockout protection and the audit trail's ability to record failed logins. Both are precisely scoped, single-root-cause, and inexpensive to fix — this is not a platform that needs to be rebuilt, but it is not safe to put in front of a second real user today.

## Strongest capabilities

1. **A real, working authentication-gate invariant.** `assert_api_routes_authenticated()` walks the entire route graph at startup and refuses to boot if any API route lacks authentication — confirmed passing against all 381 routes. This is exactly the kind of structural control that prevents an entire bug class, and it appears to be a direct, effective response to an earlier recommendation in this engagement.
2. **Code execution is now conservatively designed.** Python/R execution is off by default, requires an operator-supplied external sandbox command, and passes only an allowlisted environment when enabled — verified live. This closed what was previously the platform's most dangerous single feature.
3. **The credit-risk leakage and full-dataset issues raised earlier in this engagement are fixed and verified.** `RiskPerformance`/`atlas_split` exclusion and mandatory use of the full governed dataset (not a preview sample) for WOE/IV and scorecard training are both confirmed in the current code, with a hard 409 block if only a sample exists.
4. **A newer statistical/analytical engine that gets the hard part right.** `analytics_engine`'s classification-diagnostics module computes real ROC-AUC, PR-AUC, KS, calibration, and decile statistics from scikit-learn against the governed full-dataset artifact — genuine computation, not fabricated output.
5. **Dataset Library has real per-resource access control**, unlike the newer persistence layer — proof the team knows how to build this correctly, which makes the gap elsewhere more clearly a wiring omission than a knowledge gap.
6. **The sharing/permission model (`SharingService`) is well-designed** — owner, admin, and explicit-grant logic, correctly proven by its own passing unit tests.
7. **Domain-specific guidance content is genuinely good.** The "Atlas Guide" text for every workflow type, including the placeholder ones, reads like it was written by someone who understands each domain.
8. **Uploads are properly constrained** — extension allowlist, size/row/column caps, no filename-derived storage path.
9. **Sensible secrets hygiene** — no hardcoded credentials found in source, `.gitignore` correctly excludes local databases and env-local files, error messages are redacted before persistence in at least one confirmed path.
10. **The team responds to findings.** Comparing this pass to an earlier pass in the same engagement, multiple real fixes landed in the interim (auth gating, sandboxed execution, credit-risk leakage/full-dataset enforcement) — a good sign for how the remaining findings in this report will be handled.

## Weakest capabilities

1. **Resource-level authorization on the entire new persistence layer is absent** — the platform's single most severe defect (see below).
2. **Two disconnected "who can access this project" systems** exist simultaneously, with no reconciliation.
3. **Account lockout and failed-login audit logging both silently fail** due to one shared root cause (a database transaction rolled back by the same exception used to signal "wrong password").
4. **Three of twelve declared workflow types (Reinforcement Learning, Computer Vision, Graph Analytics) are step-label shells with no domain tooling behind them**, indistinguishable in navigation from the real workflows until you try to use them.
5. **The test suite's frontend half largely checks that strings exist in source files, not that behavior is correct** — and the one area with a strong, well-built unit test (sharing/permissions) doesn't test the layer where the critical bug actually lives.
6. **Session/modeling state is a single in-memory backend singleton**, not scoped per user — invisible today, a hard blocker at more than one concurrent user.
7. **Credit Risk Studio duplicates rather than reuses the core modeling pipeline**, meaning fixes must be applied twice.
8. **The clean-copy deployment target was already stale before this review began**, in files directly relevant to auth and training.
9. **The local dependency environment had drifted from the repository's own pinned versions badly enough to break entirely** — no CI guard currently prevents this.
10. **A hand-rolled regex HTML sanitizer** guards a real (if narrow) XSS surface where an allowlist library would be materially safer.

## Major security concerns

The dominant pattern is **authorization, not authentication**. ATLAS checks "is someone logged in" correctly almost everywhere. It does not yet check "is this specific logged-in person allowed to touch this specific object" on its newest and now-central data model. That single gap (FND-001) is a full read/write/delete compromise of every user's projects and evidence the moment a second real user exists, and it was proven live in minutes with no special tooling — register two accounts, request the second user's project ID, and every operation succeeds. A second, unrelated bug (FND-003) means the platform's brute-force protection has never actually engaged, and — more consequentially for a governance product — the audit log has a systematic blind spot for exactly the security-relevant events (failed and denied logins) an auditor would ask to see first. Full detail, reproduction, and fixes: `ATLAS_SECURITY_REVIEW.md` and `ATLAS_REVIEW_FINDINGS_REGISTER.md`.

## Major workflow concerns

The A/B Testing "Mark Complete & Next Step" button — the specific defect reported at the start of this engagement — was root-caused and fixed during this review: a save handler that threw before navigating whenever browser storage quota was exhausted by *unrelated* keys, which is why repeated attempts to fix it by pruning only A/B-prefixed storage kept failing. That specific bug is now closed (pending the user's own browser confirmation, since no browser tool was available to this review). The pattern behind it — a "must save before navigating" handler with no fallback — is worth auditing across the rest of the platform. Separately, three declared workflow types have no real implementation behind their step labels, which is a credibility risk the moment a prospect or pilot customer tries to actually use them rather than just browse the navigation.

## Enterprise-readiness assessment

Not ready. The core object model (projects, evidence) has no per-resource access control, which is disqualifying for any deployment with more than one real user — precisely the definition of "enterprise." The governance layer (Registry, Validation, Monitoring) is structurally promising — real challenge/response/approval flows exist — but lacks segregation of duties in validation approval and has an audit trail that (until FND-003 is fixed) cannot be trusted to show every access-denial event. None of this requires a rebuild; it requires wiring an authorization primitive that already exists correctly elsewhere in the codebase into the ~15 endpoints that currently skip it, plus the handful of fixes catalogued in `ATLAS_REMEDIATION_ROADMAP.md`.

## Commercial-readiness assessment

For a **single-operator, local-only demo**, ATLAS is in genuinely good shape today, and is more capable than a surface look at "yet another AI platform" pitch would suggest — the credit-risk and statistical-engine depth is real. For **any demo involving a second logged-in party**, or any pilot with real institutional users, the platform is not ready until the Immediate and Critical items in the roadmap close — not because the vision or architecture is wrong, but because one specific, well-understood, inexpensively-fixed gap currently breaks the platform's most basic multi-user promise.

## Recommended priorities

1. Fix FND-001 (resource-level authorization) and FND-003 (lockout/audit rollback bug) — days, not weeks, and they unblock everything else.
2. Add the router-level, two-user authorization regression tests that would have caught FND-001, using the fixture pattern that already exists in `admin_sharing_backend_test.py`.
3. Consolidate the two project-access systems onto one.
4. Decide, explicitly and soon, what to do about the three placeholder workflow types before they reach a prospect's screen.
5. Everything else in `ATLAS_REMEDIATION_ROADMAP.md`, in the order given there.

## Final rating

**6.5 / 10 as an architecture and product vision; 3.5 / 10 as of today's authorization state for anything beyond single-user local use.** The gap between those two numbers is the entire story of this review: a platform with real, defensible depth in the areas that are hardest to fake (statistical correctness, domain modeling, governance data model) sitting one wiring gap away from being genuinely deployable to a second user.

---

## Scoring (1–10 per category)

| Category | Score | Evidence | What blocks the next point |
|---|---|---|---|
| Functional completeness | 6 | 7 of 12 workflows have real dedicated implementations; 3 are step-label shells (FND-007) | Real tooling (or honest relabeling) for RL/CV/Graph Analytics |
| Workflow coherence | 6 | Predictive Modeling and Credit Risk are coherent internally; three parallel state-persistence mechanisms exist platform-wide (§1 of workflow report) | Consolidate to one persistence mechanism |
| Analytical correctness | 7 | Credit-risk leakage/full-dataset fixed and verified; classification-diagnostics module is real and correct | Extend the same rigor to Optimization solver and Time Series backtesting (not independently re-derived this pass) |
| Data persistence | 5 | Real SQLite persistence layer exists and works functionally | No resource-level access control on it (FND-001) — this alone caps the score |
| Security | 3 | Authentication, code-execution sandboxing, and route-level auth gating are all sound | Resource-level authorization is broken platform-wide (FND-001); lockout doesn't work (FND-003) |
| Authorization | 2 | Route-level ("is someone logged in") is correctly enforced everywhere, verified live | Resource-level ("is this the right someone") is absent on the primary data model |
| Governance | 5 | Real Registry/Validation/Monitoring services with challenge-response-approval flow | No segregation of duties (FND-005); inconsistent immutability posture across the three modules |
| Auditability | 4 | Audit infrastructure exists and mostly works for successful actions | Silently drops failed/denied-login events (FND-003); two parallel audit systems |
| Documentation (product documentation generation) | 6 | Model Documentation Studio exports real Word/PowerPoint/Excel artifacts, router auth-gated | Human-acceptance gating for AI-generated narrative not independently verified this pass |
| User experience | 5 | Domain terminology and per-workflow guidance text are genuinely good; A/B Testing bug (now fixed) shows the save/navigate pattern is fragile elsewhere too | Audit and fix the same throw-before-navigate pattern across all workflows (R7) |
| Visual design | Unable to score | No browser-rendering verification was possible in this environment | Requires a browser-capable review pass |
| Maintainability | 5 | Modular router structure, clear service-layer separation in newer code (persistence/, sharing/, analytics_engine/) | Two competing project systems and Credit Risk Studio's duplicated modeling logic both actively work against maintainability |
| Test confidence | 4 | Real, well-built service-level unit tests exist (esp. Python side); large test volume | Frontend suite is dominated by source-text assertions; the one strong unit-test area doesn't cover the layer where the critical bug lives (see test report §2) |
| Deployment readiness | 4 | App starts cleanly once dependencies match `requirements.txt`; clear router/module structure | Local dev environment was found badly drifted from the repo's own pins with no CI guard against recurrence (FND-004); clean-copy sync was already stale |
| Enterprise readiness | 2 | Real governance data model exists as a foundation | FND-001 alone is disqualifying for any multi-user deployment |

## Readiness by deployment tier

| Tier | Verdict |
|---|---|
| Founder-operated local use | **Ready**, with the caveat that code execution remains genuinely unsandboxed if an operator ever sets `ATLAS_CODE_SANDBOX_COMMAND` to something naive |
| Trusted internal demonstration | **Ready with caution** — do not demonstrate with two live logged-in accounts, and don't rely on lockout if showing the auth flow |
| External customer demonstration | **Not ready** — FND-001 is a two-minute reproduction away from being visible to anyone who registers a second account |
| Controlled pilot | **Not ready** — requires FND-001, FND-002, FND-003, FND-005 closed at minimum |
| Enterprise deployment | **Not ready** — requires the above plus argon2id migration, CSRF hardening, and per-user session-state scoping |
| Regulated production use | **Not ready** — requires all of the above plus the segregation-of-duties and audit-completeness guarantees a real MRM/SOC2 review would require, none of which can be honestly claimed until FND-001/002/003/005 are closed and independently re-verified |

---

## Top 10 strengths
1. Live-verified, passing startup guard that enforces authentication on every API route.
2. Code execution is off by default and requires explicit, allowlisted-environment sandboxing when enabled.
3. Credit-risk target-leakage and sample-vs-full-dataset issues from an earlier pass of this engagement are fixed and verified.
4. A real statistical/analytical engine computing genuine ROC/KS/calibration/decile diagnostics on governed full-dataset artifacts.
5. Dataset Library has real, correct per-resource access control — proof the pattern is known and buildable.
6. `SharingService` is a well-designed, correctly-tested permission model.
7. Genuinely good, domain-specific guidance content across every workflow type.
8. Sound upload handling (allowlist, size caps, no filename-derived paths).
9. No hardcoded secrets found; sensible `.gitignore` and error-redaction practices.
10. Demonstrated responsiveness — multiple real fixes landed between an earlier pass and this one, and this review itself found and fixed a live, user-reported bug.

## Top 10 defects or gaps
1. Resource-level IDOR across the entire persistence layer (FND-001).
2. Two disconnected project-access systems (FND-002).
3. Account lockout / failed-login audit logging both silently broken by one rollback bug (FND-003).
4. No segregation of duties in validation approval (FND-005).
5. Three placeholder workflow types presented as equivalent to real ones (FND-007).
6. Frontend test suite mostly checks source text, not behavior; the one strong unit-test area doesn't cover the router layer where the critical bug lives.
7. Predictive-modeling session state is an unscoped backend singleton.
8. Credit Risk Studio duplicates rather than reuses core modeling logic.
9. Regex-based HTML sanitizer on a real (narrow) XSS surface.
10. Local dependency environment drifted badly from the repo's own pins, with no CI guard.

## Top 10 security risks
1. Cross-user read/write/delete of projects and evidence (FND-001).
2. Non-functional brute-force lockout (FND-003).
3. Audit trail blind spot for failed/denied logins (FND-003, same root cause).
4. Two parallel authorization systems increasing the odds of the next feature wiring into the wrong one (FND-002).
5. `react-router` supply-chain advisories (2 high severity) (FND-008).
6. Regex HTML sanitizer bypass risk on narrative rendering (FND-010).
7. No CSRF token scheme beyond `SameSite=Lax`.
8. No independent rate limiting (compounds #2).
9. Security posture of "enabled" code execution depends entirely on an unvalidated operator-supplied sandbox command.
10. `Secure` cookie flag correctness depends on operator configuration with no enforced startup guard.

## Top 10 next builds
1. Wire `SharingService.check_permission` into every `persistence_router.py` endpoint (FND-001 fix).
2. Fix the `authenticate()` transaction-rollback bug (FND-003 fix).
3. Router-level, two-user authorization regression test suite.
4. Consolidate the two project-access systems.
5. Segregation-of-duties check in Validation Center approvals.
6. Per-user/per-project scoping of predictive-modeling session state.
7. Migrate Credit Risk Studio onto shared modeling primitives.
8. Real tooling (or explicit relabeling) for RL/CV/Graph Analytics.
9. Browser end-to-end test layer for the two most-used workflows.
10. CI dependency-drift guard.

---

## The four callouts

**Single most serious security issue:** Cross-user IDOR on the persistence layer (FND-001) — live-reproduced full read/write/delete of another user's project and evidence, with a clean, already-existing fix available.

**Single most serious functional issue:** The same finding, viewed functionally — the platform's central object model (projects, evidence) has no owner enforcement, which undermines every governance claim built on top of it (Registry, Validation, Monitoring, Documentation all assume project/evidence integrity that currently isn't protected).

**Single most serious workflow issue:** Three of twelve declared workflow types are fully-navigable step sequences with real-sounding, domain-specific labels and zero domain tooling behind them (FND-007) — the platform's most convincing-looking gap, because nothing about the UI signals it's a shell until a user tries to actually use it.

**Single largest source of false confidence:** `admin_sharing_backend_test.py` — a genuinely well-built unit test that proves the permission-checking service works correctly in isolation, passing green the entire time the router that was supposed to call that service didn't call it. This is the clearest evidence in the whole review that test-suite size and quality at one layer can actively mask a critical gap at the layer above it.

**Single highest-value next build:** Wiring `SharingService.check_permission` into `persistence_router.py`. It is small, it is already-designed, it closes the review's most severe finding, and it is the one change that unblocks every "not ready" verdict in the readiness table above from moving to at least "controlled pilot with remaining medium-priority items open."

---

*Companion documents: `ATLAS_REVIEW_FINDINGS_REGISTER.md` (full evidence), `ATLAS_SECURITY_REVIEW.md`, `ATLAS_WORKFLOW_AND_UX_REVIEW.md`, `ATLAS_FUNCTIONAL_COMPLETENESS_MATRIX.md`, `ATLAS_TEST_COVERAGE_AND_CONFIDENCE_REVIEW.md`, `ATLAS_REMEDIATION_ROADMAP.md`.*

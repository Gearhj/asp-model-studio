# ASP Model Studio — Repair Priority Plan (Fable 5.1 audit)

Audit base `bff19a8a657bc96dea0469fad481acdcb4234386`. Finding IDs refer to `ASP_MODEL_STUDIO_FABLE51_FINDINGS.json`.
Nothing in this plan was implemented during the audit.

## A. Immediate P0/P1 security or leakage blockers (before any second user touches the primary)

| Order | Finding | Repair | Regression test |
| --- | --- | --- | --- |
| A1 | **F-001 (P0)** self-grant project takeover via `grant_project_access` first-owner bootstrap | Remove the bootstrap exception or bind it to `projects.owner_user_id == granter` (and only when the project row exists). Make `POST /projects/{id}/access/grant`, `revoke`, and `GET /projects/{id}/access` call `SharingService.assert_can_manage` before any read/write. | Two-user HTTP test: B creates project, A self-grants → 403; A reads ACL → 403; admin grants → recorded with audit; existing `tests/persistence_authorization_test.py` extended. |
| A2 | **F-005 (P1)** authoritative persistence DB written by unregistered actors (`local-user`, `codex-wave2-prior-engine`, `codex-stage3-*`) | Require a registered `users.user_id` for every `created_by_user_id`/`created_by` (FK + trigger); make evaluator scripts authenticate through the API or a service identity that is registered; purge or annotate the demo/bootstrap rows synced into the authoritative `users` table; refuse startup when `ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP` is set against a non-default persistence path. | Insert with unknown actor → rejected; startup with bootstrap flags and the authoritative `ATLAS_SQLITE_PATH` → refused. |
| A3 | **F-002 (P1)** Wave 2 V2 prior authorities exist only under `.tmp/asp-player-prior-wave2/.runtime` (cwd-relative default root) | Make `ASP_MLB_PLAYER_PRIOR_V2_ROOT` default to the governed runtime root (same resolver as `stage3_executable_artifact._artifact_root`); republish the 39 content-addressed manifests into the primary root through the production store (`publish_artifact`) and re-point `projects/asp-mtlozhdx/current.json`; verify `9d9cfaf3…` resolves from the primary checkout. | Resolver test that asserts the store root is absolute and inside the runtime root; feature-engineering summary on `asp-mtlozhdx` from a fresh cwd shows 10 `READY_GOVERNED_PRIOR_V2`. |
| A4 | **F-003 (P1)** Model Laboratory / evaluation / downstream / artifact / scoring hard-bound to `asp-mtddc6pw` and to hard-coded checksums | Replace `EXPECTED_PROJECT_ID`/`EXPECTED_*` constants with the project-bound resolver already used by Stage 3 EDA (registration → Gold → policies → feature sets → split), keeping the exact-identity checks but sourcing them from the project's own registered authorities. | Synthetic project completes plan → job → receipt on a second project; `asp-mtddc6pw` receipts still reproduce byte-for-byte. |

## B. Private-alpha blockers

| Order | Finding | Repair | Regression test |
| --- | --- | --- | --- |
| B1 | F-004 (P2) unauthenticated-to-project ACL read | Authorize `GET /projects/{id}/access` with `view`. | Foreign user → 403. |
| B2 | F-006 (P2) `/cockpit/*` research-object routes unscoped | Require a project binding (`authorize_modeling_scope`) or an explicit research role; return 403 otherwise. | Ordinary user without binding → 403. |
| B3 | F-013 (P2) semantic/zero-variance/foreign-policy fields registerable when no specification draft exists | Apply the compiled specification's `BLOCKED`/`HELD_CLOSED` dispositions in `_catalog` eligibility regardless of whether a draft row exists; reject `treatmentPolicies` whose project id differs from the feature set's project. | Fresh project: draft with `holiday_name` → 409; foreign policy ids → 409 at draft. |
| B4 | F-010 (P2) Stage 2 profile `lru_cache` serves tampered partitions until restart | Key the cache on `(manifest sha, tuple of partition sha256 + size + mtime)` or add a TTL and a cheap size/mtime re-check on every hit. | Flip a partition byte after priming → next read fails closed. |
| B5 | F-024 (P2) `run_records`, `projects.owner_user_id`, `audit_log` mutable | Add append-only/immutability triggers mirroring the Stage 3 version tables; ownership changes only through an audited transfer. | Direct UPDATE/DELETE → IntegrityError. |
| B6 | F-015 (P2) no login rate limiting; account lockout usable as denial of service | Per-IP throttle at the proxy plus exponential backoff in `authenticate`; consider soft lockout with CAPTCHA-free challenge. | 150 attempts/12 s → 429 after threshold. |
| B7 | F-018 (P2) credentialed CORS for AI Sports Predictor dev origins | Drop the hard-coded local origin list unless `ATLAS_LOCAL_DEV=true`; hosted mode already rejects non-https origins. | Preflight from 127.0.0.1:5173 → no ACAO. |
| B8 | F-024b/F-040 (P2) no scheduled backup; naive copy loses WAL data | Nightly `sqlite3.Connection.backup()` + `wal_checkpoint(TRUNCATE)` + off-box copy; `PRAGMA integrity_check` at startup with fail-closed option. | Restore drill script in CI. |
| B9 | F-012 (P2) hard-coded absolute staging paths | Move `asp-data-staging` defaults into the launcher/env; refuse to start when a root is missing instead of silently pointing at `C:\Users\james\…`. | Startup on a clean host without the path → explicit configuration error. |
| B10 | F-027 (P2) vulnerable dependencies | Upgrade starlette/fastapi, python-multipart, lightgbm; upgrade react-router; refresh vite/rollup/postcss dev chain. | `pip-audit`/`npm audit` gates in CI. |
| B11 | F-031 (P2) security DB rollback-journal mode + per-request session write | Switch the security DB to WAL, batch `last_seen_at` updates (e.g., at most once per minute), and serve sessions from Redis at Tier 2. | Concurrent user creation + 25 readers → 0 HTTP 500. |

## C. Controlled-beta blockers

| Order | Item | Repair |
| --- | --- | --- |
| C1 | F-030 single in-process worker, no queue/quotas | Dedicated worker processes, durable queue, per-user/project quotas, admission on `totalFits` (see architecture plan). |
| C2 | SQLite → PostgreSQL | Port migrations and immutability triggers; pgbouncer; PITR. |
| C3 | F-008 combined specification adoption `NOT_IMPLEMENTED` | Implement atomic adoption (outlier + missing + specification) with audit; keep blockers fail-closed. |
| C4 | Data rights (F-034) | Record provider review outcomes for Statcast, Lahman (share-alike), Chadwick, Retrosheet; register MLB Stats API; block external exposure until `effectiveStatus != GOVERNED_LOCAL_RESEARCH_ONLY`. |
| C5 | Observability, TLS, secrets, rate limits | Per architecture plan Tier 2. |
| C6 | F-029 test signal | Retire or fix the 53 stale legacy source-contract node tests and the ~183 backend failures that are legacy-ATLAS fixture dependent; make the suite green on a clean checkout so CI gates mean something. |
| C7 | F-021 password reset stub / F-016 session cap / F-020 weak password policy | Real reset flow, session limits, zxcvbn-style policy. |

## D. Public / enterprise-scale blockers

- Tenant-scoped object storage and per-tenant quotas; SSO/OIDC; WORM audit; sandboxed deserialization; DR; source-rights policy engine; NFL/NBA/UFC workflows are not started.

## E. Modeling-workflow improvements (non-blocking)

- F-009 re-verify executable-artifact bundles on the summary read (or show "verified at publication, not re-verified").
- F-011 convert V2 store exceptions to governed 409 responses.
- F-032 accurate error codes for companion/pointer tamper.
- Install `shap` in the governed environment or remove the SHAP option from the UI until available.
- Persist `outlierTreatment` execution evidence per fold even when `RETAIN` (already the adopted policy) so policy and execution reconcile explicitly.
- Expose the `_profile_gold` verification timestamp in the Stage 2 payload.

## F. Later enhancements

- Feature-set draft de-duplication (identical drafts create new versions).
- Existence-inference hardening (F-022): return 404 for foreign projects consistently.
- Audit noise: stop writing two audit rows for every unauthenticated probe (F-019).
- Frontend chunking (2.8 MB main bundle).

## G. Work explicitly rejected as low-value or busy work

- Rewriting the 124 bandit B608 "hardcoded SQL" hits: they are identifier-quoted DDL/DML with parameterized values; no injection path was found.
- Replacing PBKDF2-SHA256 (260k iterations) with argon2 before beta: acceptable as is.
- Adding CSRF tokens while every state change is JSON+cookie with `SameSite=Lax` and CORS-restricted origins: low value until a cross-site form or GET side effect exists; fix B7 first.
- Chasing the `verify --no-deps` warnings from pip-audit or the Browserslist staleness warnings.
- Re-running the golden-corpus/hermetic gate suites that require the Codex disposable-root environment variables; they are intentionally held closed.
- "Fixing" the 300 skipped tests that gate on Gen-3 V2 publication / D3 feature-view materialization; they skip by design when local research objects are absent.

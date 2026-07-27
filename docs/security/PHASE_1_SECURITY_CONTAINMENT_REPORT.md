# ATLAS Security Containment Phase 1 — Final Report

Date: 2026-07-27  
Repository: `C:\Users\james\ds-workflow-starter`  
Baseline branch: `master`  
Baseline HEAD: `4e21fdd57e6c0318b34a60b579679f279cbedd5f`

This phase contains identity, privileged registration, development authentication, public disclosure, startup configuration, and the focused release gate. It does **not** claim that ATLAS is production-secure or complete the resource-authorization program.

## 1. Git status and baseline

Before changes there were no staged files. The worktree already contained tracked changes in Data Acquisition, dataset/evidence registries, and E2E results, plus untracked audit deliverables, evidence items, screenshots, an E2E spec, and E2E artifacts.

Those pre-existing files were preserved. No reset, clean, checkout, restore, stash, rebase, commit, stage, push, merge, or history-changing command was run.

## 2. Proven public-registration root cause

Pre-patch behavioral HTTP testing proved that `/api/auth/register` accepted an anonymous JSON `role`, passed it unchanged from `RegisterRequest.role` to `create_user`, persisted it when it matched `ROLES`, created a session, and returned the privileged user representation. Because `admin`, `validator`, `manager`, and `model_manager` were accepted roles, self-registration could directly grant privilege.

## 3. Proven development-header root cause

`ATLAS_LOCAL_DEV` defaulted to true. `development_user_header_enabled()` returned true whenever local or development mode was active and hosted mode was false; there was no dedicated opt-in. `require_user()` evaluated `X-ATLAS-USER-ID` before session authentication, did not bind it to the network peer, and could bootstrap an administrator. `ATLAS_AUTH_ENABLED=true` did not disable this password-free branch.

## 4. Proven information-disclosure paths

- Anonymous 401 payloads included active user IDs, display names, roles, the development-header name, a real seeded administrator ID, the received ID, and worked impersonation instructions.
- `/api/persistence/health` exposed the database path, engine/schema/configuration detail, header enablement, and a worked header example.
- Administrator diagnostics exposed the resolved security database filesystem path.

## 5. Final public-registration behavior

- `ATLAS_ALLOW_PUBLIC_REGISTRATION` defaults to false.
- Disabled registration always returns `403` with `Public registration is not enabled.` before an email lookup, so existing and non-existing emails receive the same response.
- When explicitly enabled, registration always assigns `data_scientist`.
- The compatibility `role` field is accepted temporarily but ignored for strings, aliases, case/whitespace variants, objects, arrays, null, and malformed privilege inputs.
- The browser request no longer sends a role and the public page has no role selector.

## 6. Final role-assignment behavior

- Privileged role assignment remains on authenticated administration endpoints.
- Generic user patching no longer accepts `role`; the dedicated role endpoint is required.
- The actor is derived from `require_user`, never from the request body.
- Successful and permission-denied role changes use `user.role.changed` audit records with the authenticated actor.
- Rejected administrator requests for unsupported roles are also audited as denied.
- Successful responses explain the selected role, actor, permission impact, audit consequence, and immediate target-session revocation.
- Administrator user creation records its actor.

## 7. Final development-header behavior

`X-ATLAS-USER-ID` is ignored unless all of the following are true:

- `ATLAS_ENABLE_DEV_USER_HEADER=true`
- `ATLAS_LOCAL_DEV=true`
- `ATLAS_HOSTED_MODE=false`
- the direct network peer is loopback
- no untrusted forwarded chain is present
- startup validation has accepted the configuration

The default for both the dedicated header flag and local development is false. Session-cookie authentication is the normal mechanism. A valid session plus a different development-header identity returns `400 Conflicting authentication identities`.

## 8. Loopback and proxy enforcement

Only `127.0.0.1` and `::1` (including other addresses recognized by the standard IP library as loopback) are accepted as direct peers. The `Host` header is not consulted. `Forwarded` is never interpreted for this password-free path. `X-Forwarded-For` is rejected unless the immediate loopback proxy IP is explicitly listed in `ATLAS_TRUSTED_PROXY_IPS`, and the forwarded origin is also loopback.

## 9. Hosted startup validation

`validate_security_configuration()` is the centralized validator and is called before persistence/checkpoint restoration on every application startup and by security-store initialization.

Hosted startup fails on:

- authentication disabled
- local/development mode
- development identity header
- local-user bootstrap
- default or shorter-than-32-character session secret
- hardcoded local administrator password
- non-Secure cookies
- missing, wildcard, or non-HTTPS allowed origins
- invalid trusted-proxy IP configuration

Errors identify unsafe setting names without printing secret values. Local mode returns a secret-free machine-readable summary and prints active warnings for the developer.

## 10. User-enumeration removal

Anonymous authentication failures now return only `{"error": "authentication required"}`. They do not include user IDs, names, roles, emails, lockout state, session IDs, header instructions, or available-user lists. Login denial remains the same generic email/password error for missing, wrong-password, inactive, and locked accounts.

## 11. Diagnostic authorization

- `/api/health` returns only `{"ok": true, "status": "running"}`.
- `/api/persistence/health` returns the same minimal payload.
- Persistence-health failure returns a generic `503 Service unavailable` without an internal path.
- `/api/security/diagnostics` requires an authenticated `admin`, `auditor`, or `model_manager`.
- The administrative response includes a machine-readable secret-free configuration summary and no database path, session secret, password, session, or registered-user list.

## 12. Session and cookie regression result

- PBKDF2 password hashing with per-user salt and constant-time `hmac.compare_digest` verification is preserved.
- Login, logout revocation, expiry rejection, failed-login persistence, and lockout pass.
- Cookies remain `HttpOnly` and `SameSite=Lax`.
- Hosted mode defaults to and requires `Secure`; non-hosted mode can opt in with `ATLAS_COOKIE_SECURE=true`.
- No session token is returned in URL parameters or authentication response JSON.
- Role and status changes revoke all active sessions for the affected user.

## 13. Canonical security test command

```text
npm run test:security
```

The command invokes `scripts/run_security_tests.py`, selects the repository virtual environment when present, and otherwise uses the active Python (for CI portability).

## 14. Security test inventory and wiring guard

`tests/security_test_inventory.json` declares six behavioral suites and one structural suite. The runner:

- checks that every required file exists
- fails if a required file is not wired
- reports behavioral and structural counts separately
- fails when a required security suite reports skipped tests
- fails immediately on any nonzero suite result

Source-text checks are explicitly labeled `structural security check`; they are not counted as behavioral proof.

## 15. CI security workflow

`.github/workflows/security-gate.yml`:

- checks out the repository
- installs Node 20 and Python 3.12
- runs `npm ci`
- installs the authoritative `server/requirements.txt`
- runs `npx tsc -b`
- runs `npm run test:security`
- reruns the focused containment suite
- uses disposable runner-temp security and persistence databases
- grants only read access to repository contents
- uploads no databases, datasets, artifacts, credentials, sessions, or logs

The workflow file was validated structurally and locally through its commands; it has not yet executed on GitHub-hosted infrastructure.

## 16. Exact files created

- `.github/workflows/security-gate.yml`
- `docs/security/PHASE_1_SECURITY_CONTAINMENT_REPORT.md`
- `docs/security/RESOURCE_AUTHORIZATION_INVENTORY.md`
- `docs/security/SECURITY_CONFIGURATION.md`
- `scripts/run_security_tests.py`
- `tests/security_containment_test.py`
- `tests/security_test_inventory.json`

## 17. Exact files modified by this phase

- `package.json`
- `server/main.py`
- `server/persistence/persistence_router.py`
- `server/security/security_router.py`
- `server/security/security_store.py`
- `src/lib/auth.ts`
- `src/steps/AuthPages.tsx`
- `tests/analysis_scope_test.py`
- `tests/analytical_data_plane_test.py`
- `tests/checkpoint_lifecycle_test.py`
- `tests/dataset_lifecycle_test.py`
- `tests/model_registry_test.py`
- `tests/modeling_state_characterization_test.py`
- `tests/persistence_authorization_test.py`
- `tests/project_access_consolidation_test.py`
- `tests/project_context_persistence_test.py`
- `tests/scoring_runs_test.py`
- `tests/sqlite_persistence_backend_test.py`
- `tests/target_intelligence_test.py`
- `tests/userManagement.test.mjs`
- `tests/validation_segregation_of_duties_test.py`
- `tests/vi_production_integration_test.py`

The one-line environment changes in registration-dependent suites explicitly enable test-only public registration. Privileged validation fixtures now provision roles directly as trusted test setup and authenticate through login, instead of using public role injection. The project-context fixture now places its disposable database under repository `.tmp` to work inside the workspace sandbox.

## 18. Database migrations

None. Existing security and persistence schemas were retained.

## 19. Tests added

`tests/security_containment_test.py` contains 15 behavioral test groups covering disabled/default registration, privilege payload variants, email response parity, authorized/audited role changes, default header rejection, explicit loopback use, forwarded spoofing, identity conflicts, minimal health, diagnostics authorization/redaction, login/logout/expiry, session revocation on role change, route-authentication assertion, hosted configuration combinations, fatal hosted startup, and hosted Secure cookies.

Existing lockout, persistence authorization, project-access, validation SoD, SQLite persistence/development identity, and structural user-management suites are wired into the gate.

## 20. Commands executed

Read-only/baseline commands included `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, staged/unstaged/untracked inspection, `rg` security-flow/test discovery, focused file reads, `git diff --stat`, `git diff --check`, and final status checks.

Behavioral/build commands included:

- pre-patch `.venv\Scripts\python.exe tests\security_containment_test.py` (expected failures proving vulnerabilities)
- repeated post-patch `.venv\Scripts\python.exe tests\security_containment_test.py`
- repeated `npm run test:security`
- `python -m py_compile` for changed Python modules/tests
- `npm run build`
- `npm run test:data-acquisition-status`
- `npm run test:project-context-persistence`

No command targeted a live security or application database.

## 21. Test totals and results

Final canonical security gate:

- Behavioral: 55 passed across six suites
- Structural: 30 assertions passed
- Required security skips: 0
- Failures: 0

Focused workflow regressions:

- Data Acquisition status: 27 passed
- Project-context JavaScript: 12 passed
- Project-context Python: 10 passed, 1 pre-existing capability skip (`per-user project listing` is not exposed)

Non-failing warnings:

- Existing Pydantic V2 `dict()` deprecation warnings
- AnyIO `MemoryObject*Stream` resource warnings around the intentional startup-failure TestClient assertion
- Existing frontend bundle-size/dynamic-import and stale browser-data warnings

## 22. Build and TypeScript results

`npm run build` passed. This ran `tsc -b` successfully and completed the Vite production modeling build (3,116 modules transformed).

## 23. Remaining security limitations

- The broad resource-authorization program remains intentionally incomplete. Several file-backed and ID-addressed resource families have authentication but no proven owner/project authorization.
- Evidence, Documentation/MDD, Notebooks, SQL Studio, analytics, Registry, Monitoring, Credit Risk, Recovery, Charts, and Model Diagnostics require cross-user behavioral remediation in the next phase.
- Async analytical identity propagation and code-execution isolation need dedicated threat models.
- Public registration keeps a deprecated ignored `role` compatibility input; it should be removed after clients have migrated.
- Invitation/provisioning workflows are not implemented; privileged provisioning currently uses authenticated administration.
- Password-reset endpoints remain local stubs.
- PBKDF2 is preserved; Argon2id/bcrypt migration is a future hosted-hardening item.
- SameSite cookies are preserved, but a broader CSRF program is outside this phase.
- Clean GitHub-hosted CI execution remains to be observed after the workflow is pushed.

## 24. Resource-authorization inventory

`docs/security/RESOURCE_AUTHORIZATION_INVENTORY.md`

It marks the requested high-risk families and does not label endpoints secure merely because they use `require_user`.

## 25. Audit deliverables

No file under `audit-output/` was created, edited, deleted, renamed, staged, or packaged by this phase. The directory remains untracked exactly as it appeared in the baseline status.

## 26. Git history

Nothing was staged or committed. No branch, tag, remote, or Git history was changed.

## 27. Final verdict

| Question | Verdict |
|---|---|
| Can anonymous registration grant privilege? | **No.** It is disabled by default and, when explicitly enabled, always creates `data_scientist`. |
| Is `X-ATLAS-USER-ID` active by default? | **No.** Dedicated header and local-development flags both default false. |
| Can hosted mode boot with development impersonation active? | **No.** Startup validation raises a fatal error before persistence/checkpoint initialization. |
| Can anonymous callers enumerate users through authentication/health responses? | **No** on the contained authentication and public health surfaces tested in this phase. |

Phase 1 containment is complete. This verdict is scoped to the tested identity, registration, startup, disclosure, session, and release-gate surfaces; it is not a claim of full production security.

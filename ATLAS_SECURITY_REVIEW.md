# ATLAS Security Review

Companion document to `ATLAS_REVIEW_FINDINGS_REGISTER.md`, which holds full reproduction detail for every finding cited here by ID. This document adds threat-model framing and per-tier verdicts.

## 1. Threat model and trust boundaries

ATLAS is a single FastAPI backend (`server/main.py`, 381 routes) behind a Vite/React SPA, with two persistence layers in active use (SQLite for security/users and, newly, for projects/evidence/registry/validation/monitoring; JSON files under `server/artifacts/` for datasets, credit-risk artifacts, and a legacy project-ACL system) plus an in-memory singleton (`DATASTORE`) for the active predictive-modeling session.

**Trust boundaries identified:**

1. **Browser ↔ API** — session-cookie authenticated (`atlas_session`, HttpOnly, SameSite=Lax). CORS is an explicit origin allowlist plus an env-extendable list.
2. **User ↔ User** — the boundary FND-001 breaks. Two authenticated users are supposed to be isolated except through explicit sharing; today they are not, for the entire persistence-layer resource family (projects, evidence, runs, decisions, documentation, exports).
3. **API ↔ generated code execution** — Python/R/SAS execution, gated behind auth and (as of this review) behind an operator-supplied external sandbox command that is unset by default. See FND-015.
4. **API ↔ filesystem** — dataset artifacts, evidence, security DB, and the workflow checkpoint all live under `server/artifacts/` and `.runtime/` on local disk, without per-tenant filesystem isolation (single OS user, single process).
5. **API ↔ LLM provider** — `python_execution.py`'s `/api/llm/cleanup-question` calls an operator-configured `ATLAS_LLM_ENDPOINT` only if set; no default external call is made without configuration. No API keys were found hardcoded in source during this review (see §9).

**Attack surface, ranked by what this review could actually reach and test:** the persistence/project/evidence API (now the primary object model — CRITICAL, broken); the auth endpoints (mostly sound, with one governance-relevant bug — FND-003); code execution (now conservatively gated); the SQL Data Studio's constrained SQL execution (sound, see §7); the frontend's HTML-rendering paths for AI/user-generated narrative (weak sanitizer, FND-010).

## 2. Authentication — Findings: FND-003, FND-009, FND-012, FND-013

- Registration/login/logout, `/api/auth/me`, session cookie issuance, and password-change all function correctly at the API level (runtime-verified).
- Password policy (min length, common-password blocklist) is enforced server-side and correctly rejected a weak password in live testing.
- Password storage is PBKDF2-SHA256 with per-user salt at 260k iterations — adequate but self-flagged by the platform's own diagnostics as needing argon2id for hosted production (FND-013).
- **Account lockout does not work** (FND-003) due to a transaction-rollback bug that also silently drops the audit trail for every failed or denied login. This is the most consequential authentication finding: it is both a brute-force exposure and an audit-integrity gap.
- Session cookies are `HttpOnly` + `SameSite=Lax`, correctly omit `Secure` only under local-dev configuration (FND-009) — but there is no enforced guard preventing that configuration from reaching a non-local deployment.
- No rate limiting exists independent of the (currently broken) lockout mechanism — confirmed by code review of the auth router; no IP-based throttling middleware is present.
- A default local admin account (`local-user` / configurable `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD`) is auto-created on first run when `ATLAS_AUTH_ENABLED` is false or no admin exists — appropriate for local dev, and gated behind `ATLAS_AUTH_ENABLED` at the `require_user` dependency, but its existence and default password value should be treated as a hard blocker checklist item before any hosted deployment (verify no deployment ships with `ATLAS_DEFAULT_ADMIN_PASSWORD` unset from its source default).

## 3. Authorization — Findings: FND-001, FND-002

This is the review's most serious area. `assert_api_routes_authenticated()` (FND-014) is a real, currently-passing, well-designed control that guarantees every non-public `/api/*` route requires *someone* to be logged in. It cannot, and does not, guarantee that the logged-in someone is *authorized for the specific resource* they're requesting — and for the entire new SQLite persistence layer, that second check was never added (FND-001). Live testing proved full cross-user read, write, and delete on projects and evidence with zero special tooling — two registered accounts and the resource ID returned by the API's own "create" response.

The existence of a second, disconnected legacy project-ACL system (FND-002) compounds this: even after FND-001 is fixed for the primary system, any code path still reading the legacy `security_store.user_can_access_project` will be unaware of resources created through the primary API.

**Positive:** the `sharing` subsystem (`server/sharing/sharing_service.py`) is a properly designed, owner/admin/explicit-grant permission model with the right primitives (`check_permission`, `assert_can_manage`). The fix for FND-001 is to *use* it, not to build new authorization logic.

## 4. Input and injection risks

- **SQL execution (SQL Data Studio):** `server/sql_studio/sql_engine.py` restricts execution to `SELECT`/`WITH` statements, blocks a keyword list (`insert|update|delete|drop|alter|create|truncate|merge|exec|execute|call|pragma|attach|detach|replace|vacuum|reindex`), rejects multi-statement input (`;` present → rejected), and runs against an ephemeral `:memory:` SQLite database populated only with the caller's own selected dataset previews — not a shared database. This is sound as designed; the one residual analytical-correctness note (sample vs. full data) is FND-006. The keyword blocklist approach is inherently less robust than AST-based parsing (a keyword outside the enumerated list could theoretically slip through in a future SQLite feature), but given execution is confined to an ephemeral in-memory DB seeded only with the caller's own data, the practical exploitation value of a blocklist gap here is low.
- **Python/R/SAS code execution:** see FND-015 — disabled by default, allowlisted environment when enabled, requires an operator-supplied sandbox. Residual risk is entirely in what operators configure `ATLAS_CODE_SANDBOX_COMMAND` to, which this review cannot verify for any specific deployment.
- **HTML/XSS:** `dangerouslySetInnerHTML` is used in exactly one confirmed location (`src/components/ReportSectionContent.tsx`), fed through a regex-blocklist sanitizer (FND-010). Plain narrative text elsewhere is passed through `escapeHtml` (a proper allowlist-by-omission escape), which is correctly implemented in `src/lib/reportFormatting.ts`.
- **Path traversal:** dataset artifact reads (`server/datasets/dataset_registry.py`, `read_version_artifact`) build paths from `dataset_id`/`version_id`; `version_id` is not validated against the dataset's actual version list or a safe character pattern before being joined into a filesystem path (identified in an earlier pass of this engagement; not independently re-verified live in this pass — treat as open until re-checked).
- **CSV/formula injection, ZIP-slip, archive extraction:** no archive-extraction code path was found in the reviewed server modules (no `zipfile`/`tarfile` usage handling untrusted uploads). CSV upload (`/api/data/upload_csv`) is parsed with `pandas.read_csv` directly into a DataFrame, not shelled out to anything — no command-injection surface identified there. Exported Excel files (`openpyxl`) write user-controlled string values into cells; a cell beginning with `=`, `+`, `-`, or `@` opened later in Excel is a classic CSV/formula-injection vector into whatever spreadsheet tool opens the export. **Not independently verified whether cell values are prefixed/escaped before writing** — flag as open, low-effort to check and fix (prefix a leading apostrophe or single-quote-escape formula-triggering leading characters).

## 5. Data and file security

- Datasets are stored server-side under `server/artifacts/datasets/<dataset_id>/versions/<version_id>/` with `profile.json`, `preview.json`, `data_sample.csv`, and (per FND-006) `data_full.csv`. Access to the *registry entry* for a dataset is gated by `require_dataset()`'s `user_can_access()` check (a real per-resource ACL check, unlike the persistence-layer projects) — this subsystem does the resource-level check the persistence layer is missing.
- Uploads are extension-allowlisted (`.csv`, `.txt`), byte/row/column-capped (`MAX_UPLOAD_BYTES`, `MAX_UPLOAD_ROWS`, `MAX_UPLOAD_COLUMNS`, all env-configurable). No filesystem path is derived from the uploaded filename for storage — DataFrame content is stored, not the raw file — eliminating a class of path-traversal-via-filename risk.
- Local persistence artifacts (`server/data/atlas_local*.db`, `server/artifacts/security/*.db`) are excluded from the clean-copy sync per `.gitignore`; several stray timestamped `atlas_api_context_*_security.db` files were found in `server/data/` (harmless per-run artifacts from repeated local test runs, not a leak, but worth a periodic cleanup).

## 6. API security

- CORS: explicit allowlist of local dev origins plus an env-extendable list; `allow_credentials=True` with `allow_methods/headers=["*"]` — acceptable given the explicit-origin allowlist, but confirm no wildcard origin is ever added to `ATLAS_CORS_ORIGINS` in any deployment (a wildcard combined with `allow_credentials=True` would be a real gap).
- No CSRF token scheme was found; reliance is on `SameSite=Lax` cookies, which mitigates classic cross-site form-POST CSRF for state-changing `fetch` calls from third-party origins in modern browsers, but is not a complete substitute for a CSRF token on a cookie-authenticated API.
- No rate limiting on any endpoint (compounds FND-003).
- Error responses observed during live testing were appropriately generic for auth failures (`"Email or password is not valid."` regardless of cause) and did not leak stack traces or internals in the responses this review triggered.
- `/api/health` and `/api/persistence/health` are intentionally public; the public-path allowlist in `main.py` is a short, explicit, auditable list — a good pattern.

## 7. LLM and AI-assisted features

- `POST /api/llm/cleanup-question` only calls an external endpoint if `ATLAS_LLM_ENDPOINT` is explicitly configured; otherwise it falls back to a deterministic, non-LLM text-cleanup function (`deterministic_question_cleanup`) and clearly labels the response `"source": "deterministic"` vs `"source": "llm"`. This is an honest design — it does not silently claim AI involvement it didn't perform.
- No evidence was found of project data being sent to an external LLM provider by default, no hardcoded API keys for any LLM provider, and no prompt-injection-relevant tool-invocation loop (the platform does not appear to let an LLM call back into ATLAS's own write APIs autonomously) in the modules reviewed. **Not exhaustively verified** — the LLM/Generative AI project-type workflow (`src/features/llm/`) was inventoried for existence but not read function-by-function in this pass; a follow-up pass should specifically check whether generated narrative/documentation text is ever saved as "approved" documentation without an explicit human-acceptance step.

## 8. Dependencies and supply chain — Finding: FND-008, FND-004

- `npm audit --omit=dev` found 2 high-severity advisories, both from the `react-router` package pulled in transitively by `react-router-dom@^7.9.5` (open-redirect/XSS/DoS advisory family). Fixable via `npm audit fix`.
- Python dependencies are version-pinned in `requirements.txt`; the *installed* environment had drifted from those pins badly enough to break imports entirely (FND-004), which this review corrected to establish a working baseline. `pip check` reported no broken *requirement* relationships after the fix, but flagged two corrupted partial installs (`~cikit-learn`, `~ydantic-core`) as warnings — cosmetic (pip ignores them) but indicative of an interrupted install/uninstall that was never cleaned up.
- No dependency-confusion or unpinned-version risk identified in `package.json` (all deps use caret ranges against a committed `package-lock.json`) or `requirements.txt` (all deps use exact `==` pins).

## 9. Secrets and configuration

- `SESSION_SECRET` defaults to a literal string (`"atlas-local-dev-default-session-secret"`) if `ATLAS_SESSION_SECRET` is unset — appropriate for local dev, and the platform's own `/api/security/diagnostics` self-reports this as a warning when the default is in use. No enforced startup refusal exists if this default is still active outside local mode (same gap pattern as FND-009).
- No API keys, tokens, or connection strings were found hardcoded in the reviewed source files. `.env.modeling` and `.env.scheduling` (tracked in git) contain only `VITE_API_BASE`/`VITE_APP_TARGET` values, not secrets. `.gitignore` correctly excludes `.env.local`, `.env.*.local`, `.venv/`, `.runtime/`, and `server/artifacts/security/*.db`.
- Sanitization of error messages before persistence exists for at least the SAS-connection-settings path (`sanitize_error()` in `python_execution.py` redacts `password|passwd|pwd|token|secret` patterns before writing to disk) — a good, specific control.

## 10. Residual risk summary

After the fixes already applied between the earlier pass of this engagement and now (router-level auth gating, code-execution sandboxing default-off, environment allowlisting, credit-risk full-dataset enforcement), the **dominant residual risk is authorization, not authentication**: the platform correctly checks "is this a logged-in user" almost everywhere, and does not yet check "is this logged-in user allowed to touch this specific object" on its newest and most central data model (projects, evidence, runs, decisions, documentation, exports). This is a coherent, well-scoped gap — not evidence of broad carelessness — and the fix is to wire an authorization primitive that already exists correctly elsewhere in the codebase (`SharingService.check_permission`) into the endpoints that skip it.

## 11. Security-readiness verdict by deployment tier

| Tier | Verdict | Reasoning |
|---|---|---|
| **Local-only, single user** | Acceptable | No second user exists to exploit FND-001/FND-002; code execution is off by default; auth works for its single purpose (gating the unauthenticated internet). |
| **Trusted internal demo (one presenter, no real second login)** | Acceptable with caution | Same reasoning as above, but do not demonstrate the platform with two live logged-in accounts, and do not rely on account lockout if showing the auth flow. |
| **External demo (prospect logs in themselves, or two accounts are shown)** | **Not ready** | FND-001 is trivially demonstrable by anyone who registers a second account and reuses a project ID they can see in their own browser network tab from a shared/previous session, or simply asks "what if I try someone else's project ID." |
| **Controlled pilot (real institution, real users, real data)** | **Not ready** | FND-001, FND-002, FND-003, FND-005 must all close first. A pilot with real financial data and multiple named users is exactly the scenario FND-001 breaks completely. |
| **Enterprise deployment** | **Not ready** | All CRITICAL and HIGH findings, plus argon2id migration (FND-013), CSRF hardening, and the `Secure`-cookie startup guard (FND-009), are prerequisites. |
| **Regulated production (financial-services model risk management)** | **Not ready** | In addition to the above, requires the segregation-of-duties fix (FND-005), a resolved single source of truth for project access (FND-002), and an audit trail proven not to drop events under any failure path (FND-003 fix plus a broader audit of other `with connect() as conn: ... raise` patterns elsewhere in the codebase for the same rollback bug class — this review found and fixed-in-diagnosis one instance; a systematic grep for the pattern is recommended before declaring the class closed). |

## 12. Prioritized remediation plan (security-only; see `ATLAS_REMEDIATION_ROADMAP.md` for the full cross-functional roadmap)

1. **Immediate (1-3 days):** FND-001 (wire `SharingService.check_permission` into persistence_router), FND-003 (fix the transaction-rollback bug in `authenticate()`), FND-008 (`npm audit fix`).
2. **1-2 weeks:** FND-002 (retire or merge the legacy ACL system), FND-005 (segregation of duties in validation approval), FND-010 (allowlist HTML sanitizer), formula-injection check on Excel export.
3. **2-6 weeks (pilot readiness):** FND-013 (argon2id migration), FND-009 (enforced secure-cookie startup guard), CSRF token scheme, rate limiting independent of lockout, systematic grep for the `with connect() as conn: ... raise` rollback pattern across the codebase.
4. **1-3 months (enterprise readiness):** dependency-drift CI guard (FND-004), sandbox-command validation for code execution (FND-015 residual), path-traversal hardening on dataset version reads.

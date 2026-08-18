# ASP Model Studio — Deep Security & Financial-Integration Readiness Audit

**Type:** Adversarial security review (OWASP ASVS / API Security as structural checklist)
**Date:** 2026-08-18
**Repository:** `C:\Users\james\asp-model-studio` (only)
**Threat framing:** assume a future attacker trying to steal money, credentials,
subscriber access, proprietary models, or admin authority. Prove each trust
boundary fails closed.

---

## 1. Executive verdict

ASP Model Studio is a **local/single-tenant model-development studio** with a
**mature, fail-closed security core**. Authentication is server-side and
auth-gated on every `/api` route (enforced at startup and verified with live 401
probes); authorization is enforced with a project ACL plus an independent
Dataset-Library ACL; the filesystem boundary rejects traversal, symlink, junction,
and hardlink escape; user-facing SQL runs in in-memory SQLite (no file access) and
the analytical DuckDB path disables extensions (no SSRF); Python execution is a
deliberate expert boundary that is disabled in hosted mode. **No secrets are
committed.** There is **no payment/Stripe/webhook/Patreon code today** (greenfield).

**No P0 findings. No P1 findings.** One **P2** untrusted-deserialization gap in a
currently-unused model-load helper was **repaired** (checksum now verified before
`joblib.load`, with a tamper-rejection regression test). The rest are P2/P3
hardening and future-readiness items.

| Severity | Count | Repaired |
|----------|-------|----------|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 3 | 1 |
| P3 | 4 | 0 (documented) |

**Deployment readiness (this repo, standalone):** **SAFE FOR PRIVATE POC / LOCAL
DEVELOPMENT.** Not yet payment-connected (no Stripe code). Production blockers are
listed in §19.

---

## 2. Threat model & attack surface

**Assets:** proprietary MLB models & artifacts, immutable dataset registrations,
research evidence, user accounts/roles, audit log, the admin role, and (future)
payment entitlements.

**Primary surfaces:**
- FastAPI backend on `127.0.0.1:8101` — all `/api/*` routes auth-gated.
- Session auth via HttpOnly cookie `atlas_session`.
- Expert code execution (`/api/python/run`) — hosted-disabled.
- User-facing SQL Lab (in-memory SQLite) and analytical DuckDB plane.
- Model artifact storage (joblib) under a governed, gitignored artifact root.
- Immutable exchange package (read-only), logical-URI resolved.
- Vite/React SPA; session is a cookie, not a JS-readable token.

**Trust boundaries today:** browser → backend (cookie auth); backend → local
exchange package (read-only, hash-verified); backend → local filesystem
(root-contained). No external network egress in normal operation.

---

## 3. Baseline Git state

- **HEAD:** `f1e22d467bcc1d6c120f82667c672d02c5c30995` (unchanged)
- Worktree carries the preserved Milestone B checkpoint plus the prior audit
  repairs (dataset-total authority, `current_user` fail-closed) and their tests.
- This pass adds one repair + one test + this report. **Nothing staged/committed.**

---

## 4. Authentication & session security (ASVS V2/V3)

**Strong / fail-closed:**
- Passwords: `pbkdf2_sha256`, 260k iterations, per-user 16-byte salt, constant-time
  compare (`hmac.compare_digest`). Weak-password denylist + 8-char minimum.
- Sessions: `secrets.token_urlsafe(32)` (256-bit), server-side table with
  `expires_at`/`revoked_at`, TTL (8h default), revoked on role/status change and on
  logout.
- Cookies: `HttpOnly`, `SameSite=Lax`, `Secure` in hosted mode; not JS-readable.
- Brute force: lockout after `ATLAS_LOCKOUT_THRESHOLD` (5) failures for
  `ATLAS_LOCKOUT_SECONDS` (900s); every auth outcome audited **inside** the same
  transaction (a previous rollback-swallows-audit bug is fixed).
- Dev impersonation header (`X-ATLAS-USER-ID`) is honored only when
  `ATLAS_ENABLE_DEV_USER_HEADER && ATLAS_LOCAL_DEV && !ATLAS_HOSTED_MODE` **and** the
  client is loopback; live probe with the header still returned **401**. The SPA
  only sends it under Vite `DEV`, so it never ships to a production bundle.
- Hosted config **fails startup** on wildcard/insecure CORS, default session secret
  (<32 chars), default admin password, insecure cookies, or dev bypasses.
- **No absent user context becomes admin** — the prior `current_user()` fail-closed
  repair holds and is regression-tested.

**Findings:**
- **P2-A (default dev secret & admin password).** `ATLAS_SESSION_SECRET` and
  `ATLAS_DEFAULT_ADMIN_PASSWORD` have hard-coded local-dev defaults. This is
  acceptable for local dev and **cannot** reach a hosted deployment
  (`validate_security_configuration()` rejects them when `ATLAS_HOSTED_MODE`), but
  any non-local exposure MUST set real values. *Production blocker, already
  machine-enforced for hosted mode.*
- **P3 (no CSRF token).** Auth is a `SameSite=Lax` cookie with CORS credentialed to
  an allowlist; Lax + strict origin allowlist mitigates classic CSRF for the local
  posture. If cookie auth is ever exposed cross-site, add a CSRF token or move to
  `SameSite=Strict` for state-changing routes.

---

## 5. Authorization / IDOR / tenant isolation (ASVS V4 / API1,API5)

- Every project route calls `_authorize_project(project_id, user, view|edit|admin)`
  via `SharingService.check_permission` (server-side; UI hiding is never the
  control). Project listing filters to `view`-permitted rows.
- **Dataset ACL is independent of project ACL.** A project collaborator without
  Dataset-Library access has the active dataset identity, activation revision, and
  lineage artifact IDs **redacted** (`_workflow_state_for_dataset_acl`) — fails
  closed without leaking identity. Verified by `persistence_authorization_test.py`
  (cross-user sequence, 5 passed).
- **Sports evidence** (`registry.public_dataset`) attaches child studies only when
  projectId, registrationId, manifestSha, partitionAuthoritySha, and the full
  Phase-3 parent identity all match — no cross-project/superseded masquerade.
- **Null-owner access** is fixed: `user_can_access` now returns `False` when there
  is no concrete identity (guards `None == None` owner match).
- Admin endpoints (`/api/admin/*`, role change, audit) enforce `require_role({"admin"})`
  / `AUDIT_ROLES` server-side; role change revokes existing sessions.

No horizontal/vertical escalation or IDOR path was found.

---

## 6. Dataset / artifact / filesystem security (ASVS V12)

- **Partition resolution** (`sports_datasets/access.py:_resolve_partition`):
  validates the package-relative URI, `resolve(strict=True)`, requires the package
  root in `resolved.parents`, and rejects symlinks, junctions/reparse points
  (`FILE_ATTRIBUTE_REPARSE_POINT`), and hardlink substitution (`st_nlink != 1`).
  Partition bytes/rows/schema/sha are re-verified against the registry on every read.
- **Model artifacts** (`model_artifacts.py`): `_within_artifact_root` containment;
  `_artifact_path` rejects `/`, `\`, `..` in the version id; write-once
  (`mkdir(exist_ok=False)`, no overwrite); staged→verify→checksum→atomic
  `os.replace`.
- **Logical URIs** validated against `asp-model-exchange://` / runtime prefixes;
  physical paths are sanitized out of all frontend responses.

No path traversal, ZIP-slip (no archive extraction of untrusted input exists),
UNC, or encoded-traversal escape was found.

---

## 7. Command / code execution (ASVS V5 / API8)

- `python_execution.py` is an **intentional expert code-execution boundary**: user
  code is written to a temp file and run via a resolved, allowlisted sandbox command
  (list form, `env=execution_env()`), **never** `shell=True`, and is **disabled in
  hosted mode** (`EXECUTION_ENABLED = ... and not HOSTED_MODE`). Gated by
  `require_user`. Classified as a deliberate, correctly-gated boundary.
- **No `shell=True` anywhere.** All `subprocess.run` calls use fixed, list-form,
  server-controlled argument vectors (`git rev-parse HEAD`, `git worktree list`,
  probes). No user input reaches an argument vector.
- **Untrusted deserialization — P2-B (REPAIRED).** `joblib.load` (pickle opcodes)
  appears in `model_artifacts.py`. `verify_model_artifact` already checksum-verifies
  before an optional deserialize, but the bare `load_model_artifact` helper loaded
  **without** checksum verification. See §16.

---

## 8. SQL / database security (ASVS V5.3)

- **SQL Lab** (`sql_studio/sql_engine.py`) executes user SQL against **in-memory
  SQLite** loaded only with the caller's **ACL-authorized** dataset preview rows
  (`require_dataset` per reference). `is_read_only_select` blocks
  DDL/DML/PRAGMA/ATTACH/EXEC and multi-statements (`;`); `conn.execute` cannot run a
  second statement. In-memory SQLite exposes no file-read functions → no
  exfiltration. Row cap ≤1000.
- **Analytical DuckDB** (`analytics/engines/duckdb_engine.py`) takes a **structured
  query contract**, not raw user SQL. Identifiers are regex-validated and
  double-quote-escaped against the resolved schema; values are parameter-bound;
  `autoinstall/autoload_known_extensions = false` (no `httpfs` → **no SSRF via
  remote URLs**); memory/thread limits applied; source paths are artifact-root
  resolved upstream.
- **Migrations** are per-file atomic under `BEGIN IMMEDIATE` with a post-lock recheck;
  no `executescript`; transaction-breaking SQL rejected. Parameterized queries
  throughout; the only f-string SQL uses fixed table-name tuples or validated
  identifiers.

**P3:** `duckdb_engine.register_source` interpolates the (server-controlled)
artifact path into `read_parquet('...')`. It is upstream-contained to the artifact
root and filenames are content-addressed, so injection is not currently reachable;
prefer path parameter binding as defense-in-depth.

---

## 9. Frontend security (ASVS V5 / V14)

- **No `dangerouslySetInnerHTML`, `innerHTML`, `document.write`, `eval`, or
  `javascript:` sinks** — React auto-escaping is relied on throughout.
- **No auth token in `localStorage`/`sessionStorage`.** Session is the HttpOnly
  cookie; `localStorage` holds only UI caches (`modelflow-user`, project snapshots,
  a "keep-signed-in" email). Tampering these changes only the local UI — the backend
  re-validates authority from the cookie on every request.
- API errors are structured; physical paths are withheld from responses
  (`isPhysicalReference`/`sanitizePublicEvidenceValue`).
- **No secrets bundled into the frontend**; the exchange root is backend-only env,
  never a `VITE_` var.

---

## 10. API security (ASVS / OWASP API Top 10)

- **API1/API5 (object/function authorization):** enforced server-side (see §5).
- **API2 (auth):** every `/api` route requires a session; `assert_api_routes_authenticated`
  fails startup otherwise.
- **API4 (resource limits):** upload byte/row/column caps; SQL/DuckDB row/memory/
  cardinality caps; query cancellation registry; analytical plane returns **429** on
  concurrency limits.
- **API6 (mass assignment):** project/evidence upserts map explicit fields; owner is
  preserved via merge (`update_project`), not client-overridable on edit.
- **API7 (SSRF):** no server-side fetch of user-supplied URLs; DuckDB remote
  extensions disabled.

**P2-C (rate limiting on auth/expensive endpoints).** Login has lockout, and the
analytical plane has concurrency limits, but there is **no general per-IP/per-user
rate limit** on `/api/auth/login`, registration, or expensive modeling endpoints.
Adequate for local/single-tenant; a **production blocker** before any public
exposure (credential-stuffing / denial-of-service / denial-of-wallet once metered
providers or payments are added).

---

## 11. Secret management (ASVS V6)

- **No committed secrets.** Scans for `sk_live_/sk_test_/rk_/whsec_/AKIA/BEGIN * PRIVATE
  KEY/xox*/ghp_/AIza*` over tracked+untracked source/config found **nothing**.
- `.gitignore` covers `.env`, `.env.local`, `.env.*.local`, security/persistence
  `*.db`. Tracked `.env.modeling`/`.env.scheduling` contain only non-secret mode
  flags and an empty exchange-root placeholder.
- Only dev-default credentials exist (session secret, admin password) — rejected in
  hosted mode (see P2-A). Secrets cannot leak via responses (paths sanitized) or the
  frontend bundle.

---

## 12. Stripe / payment readiness (greenfield — no code today)

There is **no Stripe/payment/billing/webhook code** in the repo. Required target
architecture when it is added:

- Client → **ASP backend** → **Stripe Checkout / Customer Portal** (Stripe-hosted;
  no card/bank data touches ASP).
- **Secret key server-side only**, outside Git (env/secret manager); use a
  **restricted key** where the flows allow; strict **test/live isolation** by env.
- **Server-side price/product authority** and **server-side entitlement ledger** —
  never trust client-provided amount, price ID, or subscription status.
- **No entitlement granted from the redirect/success page** — only from a verified
  webhook event reconciled into the ledger.
- **Least-privilege** Stripe account roles; **documented key rotation** and an
  incident-revocation runbook (see §17).
- **Future bank linkage:** use Stripe-managed/tokenized ACH (Financial Connections)
  — ASP must **never** store online-banking credentials or raw routing/account
  numbers; keep only opaque processor tokens.

**Readiness verdict:** *NOT payment-connected; architecture specified. Do not ship
payments until §12/§13 controls exist.*

---

## 13. Webhook security (none today — spec for when added)

Require: raw-body **signature verification** (`Stripe-Signature`) before any JSON
parsing/mutation; timestamp tolerance (replay window); **event-ID dedup** table;
**event-type allowlist**; idempotent processing; tolerate duplicate/out-of-order
delivery; reconcile subscription state from Stripe as source of truth (never trust a
forged `customer.subscription.*`/refund event). The endpoint must be the *only* path
that mutates entitlements.

---

## 14. Model / registry / supply-chain integrity (ASVS V10)

- Artifacts are **content-addressed by sha-256**, write-once, checksum-verified at
  stage and finalize; the registry stores metadata + logical references, not bytes
  in the DB.
- Predictions/calibration bind to exact model version; superseded artifacts cannot
  masquerade (active-selection + parent-identity gates).
- **A user cannot register/replace an artifact for a project they do not own** —
  artifact write goes through owner/edit-authorized model-registry endpoints and the
  immutable per-version path (no overwrite).
- **P2-B (REPAIRED):** the one deserialization back-door (`load_model_artifact`
  without checksum) is closed — see §16. There is **no untrusted model-bundle import
  in ASP today** (that boundary lives in the future AI Sports Predictor exchange).

---

## 15. Dependency / supply chain (ASVS V14)

- npm: `package-lock.json` present; **no** `preinstall/postinstall/prepare` lifecycle
  scripts; **no** git/file/URL deps (all registry versions) → no dependency-confusion
  or lifecycle-script RCE vector introduced by manifests.
- Python: `requirements.txt` **fully `==`-pinned** (fastapi, pydantic, numpy, pandas,
  scikit-learn, xgboost, joblib, duckdb, etc.). No unpinned lines.
- No broad CVE scan performed (per scope); recommend adding `pip-audit`/`npm audit`
  in CI as a follow-up (not a blocker for POC).

---

## 16. Repairs made (this pass)

**P2-B — `load_model_artifact` unverified `joblib.load` (untrusted deserialization).**
- **File:** `server/model_registry/model_artifacts.py` → `load_model_artifact`.
- **Root cause:** the helper deserialized any file inside the governed artifact root
  **without** verifying the registry checksum, unlike `verify_model_artifact`. Since
  `joblib.load` executes pickle opcodes, a tampered/substituted/stale artifact (a
  future model-bundle import, a filesystem compromise) would become arbitrary code
  execution on load. It had a single test caller and no production caller yet, so the
  gap was latent — but it is exactly the "untrusted model deserialization" risk the
  threat model calls out.
- **Fix (fail-closed):** `load_model_artifact(relative_path, *, expected_checksum)`
  now computes the on-disk sha-256 and **refuses to deserialize** unless it matches
  the registry checksum (empty/mismatch → `ValueError`, before `joblib.load`).
- **Caller updated:** `tests/model_registry_test.py:598` passes `row["checksum"]`.
- **Regression test:** `tests/model_artifact_load_verification_test.py` (5 tests,
  hermetic; `ARTIFACT_ROOT` patched to a temp dir) — correct checksum loads; wrong/
  empty checksum rejected; a **tampered on-disk artifact is refused and
  `joblib.load` is asserted un-called**.

No other production code changed. No model methodology, metrics, artifacts, or
Milestone B files were modified.

---

## 17. Incident-response recommendations (specify now, before payments)

- **Session-secret compromise:** rotate `ATLAS_SESSION_SECRET`; all sessions
  invalidate (HMAC-derived observ. hashes change; require re-login).
- **Admin compromise:** disable the account (`/api/admin/users/{id}/disable` revokes
  sessions), rotate its password, review `audit_events` for `user.role.changed`/
  `access.denied`.
- **Provider/Stripe key compromise (future):** revoke in the provider dashboard,
  rotate via secret manager, replay-scan webhook/event logs, reconcile the
  entitlement ledger against Stripe.
- **Model tampering:** the checksum gate (§16) now blocks load of a mismatched
  artifact; on alert, re-verify all `model_versions.checksum` against disk and
  quarantine mismatches.

---

## 18. Tests added / verification

- **Added:** `tests/model_artifact_load_verification_test.py` (5 passed).
- **Updated:** `tests/model_registry_test.py:598` (pass checksum to hardened API).

| Check | Result |
|-------|--------|
| `py_compile` (model_artifacts, dataset_registry, sports_datasets/registry) | **OK** |
| `pytest tests/model_artifact_load_verification_test.py` | **5 passed** |
| `pytest current_user_fail_closed + sports_dataset_totals` | **14 passed** |
| Secret scan (sk_/rk_/whsec_/AKIA/PRIVATE KEY/xox/ghp_/AIza) | **no matches** |
| `git diff --check` | **clean** |

**Inherited failure (not caused by this change):**
`tests/model_registry_test.py::ModelRegistryTrainingIntegrationTests::test_artifact_round_trips_and_matches_live_predictions`
fails at **line 249** — a `422 analysis_partition_preview_stale` in the shared
training/promotion **setup** (analysis-partition preview-fingerprint precondition),
a different subsystem that runs before the edited line 598. My `load_model_artifact`
behavior is proven independently by the 5 hermetic tests above. Recorded, not
chased (per scope).

---

## 19. Remaining risks & production-blocking recommendations

**Not blocking for LOCAL/POC. Blocking before any authenticated/public/paid beta:**
1. **P2-A** Set real `ATLAS_SESSION_SECRET` (≥32 chars) and admin password; enable
   `ATLAS_HOSTED_MODE` (already fails closed on defaults).
2. **P2-C** Add per-IP/per-user rate limiting to `/api/auth/*`, registration, and
   expensive modeling/export endpoints (credential-stuffing / DoS / denial-of-wallet).
3. **Payments:** implement §12/§13 exactly (server-side entitlement ledger,
   Stripe-hosted flows, signed+deduped webhooks) before any billing.
4. **P3** Add CSRF defense if cookie auth is ever exposed cross-site; parameter-bind
   the DuckDB source path; add `pip-audit`/`npm audit` to CI.

**Standalone readiness verdict:** **SAFE FOR PRIVATE POC / LOCAL DEVELOPMENT.**

---

## 20. Files changed (this pass)

- **Modified:** `server/model_registry/model_artifacts.py` (P2-B fix)
- **Modified:** `tests/model_registry_test.py` (caller passes checksum)
- **Added:** `tests/model_artifact_load_verification_test.py`
- **Added (this report):** `docs/ASP_MODEL_STUDIO_DEEP_SECURITY_AUDIT.md`

All changes **unstaged**. HEAD unchanged at `f1e22d4`. Milestone B intact. No commit,
no push, no remote change. Real Stripe calls = 0 · real bank calls = 0 ·
sports-provider calls = 0 · credentials printed = 0 · financial ATLAS / sibling
repos accessed = 0.

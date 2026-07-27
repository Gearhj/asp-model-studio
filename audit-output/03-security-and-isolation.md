# 03 — Security and Multi-User Isolation

**Method:** static review of all 39 router modules and the auth core, plus **live non-mutating GET probes** against the running backend (port 8001) using three real identities. No exploitation, no writes, no external systems, no live testing of the escalation paths (those are confirmed from source only).

---

## 1. Headline judgement

The isolation work claimed in prior reports **is real where it was done**, and it is well engineered. It stops at the modeling core. Every "studio" router added in a later phase inherited *authentication* from the router-level dependency in `server/main.py` and **never received authorization**.

A startup assertion, `assert_api_routes_authenticated` ([server/main.py:82-103](server/main.py#L82-L103)), walks every `/api/*` route's dependency tree and raises if `require_user` is missing. It passes 412/412. **It verifies authentication only.** That green signal reads like proof of isolation and is not — this is the single most important structural observation in the audit.

---

## 2. Authentication model — OBSERVED FACT

Three identity paths in `_resolve_authenticated_user` ([server/security/security_store.py:545-578](server/security/security_store.py#L545-L578)), consumed by `require_user` ([:581-634](server/security/security_store.py#L581-L634)):

| Priority | Path | Credential required |
| --- | --- | --- |
| 1 | `X-ATLAS-USER-ID` header names a user id directly | **No** |
| 2 | `ATLAS_AUTH_ENABLED=false` → become `local-user` (role `admin`) | **No** |
| 3 | `atlas_session` cookie → `sessions` table | Yes |

**Verified live.** A request with no identity header returns `401`. A request with `X-ATLAS-USER-ID: local-user` returns `200` and `/api/auth/me` reports `role: "admin"`.

**What is done well:** PBKDF2-HMAC-SHA256 at 260,000 iterations with a 16-byte per-user salt and `hmac.compare_digest` verification ([:248-264](server/security/security_store.py#L248-L264)); `secrets.token_urlsafe(32)` sessions with 8h TTL, revocation, and expiry checked on every read ([:430-477](server/security/security_store.py#L430-L477)); 5-failure/15-minute lockout with correct transaction-commit ordering ([:394-427](server/security/security_store.py#L394-L427)).

---

## 3. P0 findings

### SEC-P0-1 — Unauthenticated privilege escalation to platform admin via public self-registration

**OBSERVED FACT — verified in source.** `/api/auth/register` is in `PUBLIC_API_PATHS` ([server/main.py:72-79](server/main.py#L72-L79)) and passes the caller-supplied role straight through:

```python
# server/security/security_router.py:39-42
class RegisterRequest(BaseModel):
    email: str; displayName: str; password: str
    role: str = "data_scientist"          # caller-controlled

# server/security/security_router.py:89-93
user = create_user(email=..., password=payload.password, role=payload.role)
login = authenticate(payload.email, payload.password, request)
set_session_cookie(response, login["sessionId"], login["expiresAt"])
```

The only validation is membership in `ROLES` ([server/security/security_store.py:284-287](server/security/security_store.py#L284-L287)), and `ROLES` contains `"admin"` ([:44](server/security/security_store.py#L44)). The handler then issues a live session cookie.

`role == "admin"` short-circuits every downstream check — `sharing_service.py:135-136`, `security_store.py:938-939`, `admin_service.py:29-31`.

> **Not tested live.** Confirming this would create an admin account in the user's database. The source is unambiguous and the audit is read-only, so it is reported on source evidence alone. **Exploitability: one unauthenticated POST.**

**Fix:** force the lowest role server-side in `register()`, ignoring the payload field. Gate public registration behind `ATLAS_ALLOW_PUBLIC_REGISTRATION`, default false.
**Remediation test:** unauthenticated `POST /api/auth/register {"role":"admin"}` → assert created role is `data_scientist` and `GET /api/admin/users` with the returned session is 403.

### SEC-P0-2 — Header-asserted identity is enabled by default; any client becomes any user without a password

**OBSERVED FACT — verified in source and live.**

```python
# server/security/security_store.py:26-27
ATLAS_LOCAL_DEV   = os.getenv("ATLAS_LOCAL_DEV",   "true").lower() in {"1","true","yes"}
ATLAS_HOSTED_MODE = os.getenv("ATLAS_HOSTED_MODE", "false").lower() in {"1","true","yes"}

# server/security/security_store.py:89-92
def development_user_header_enabled() -> bool:
    return not ATLAS_HOSTED_MODE and (ATLAS_DEV_MODE or ATLAS_LOCAL_DEV)   # True with no config

# server/security/security_store.py:582-585
if development_user_header_enabled() and requested_dev_user:
    user = _resolve_authenticated_user(request, allow_dev_bootstrap=True)   # no password
```

The header branch precedes the session branch, so **`ATLAS_AUTH_ENABLED=true` does not suppress it**. The one guard, `enforce_hosted_security_configuration()` ([:108-116](server/security/security_store.py#L108-L116)), returns immediately unless `ATLAS_HOSTED_MODE` is explicitly true — **fail-open**.

**Verified live:** the entire audit was conducted by asserting three different identities via this header with no credentials.

**Compounding — the target list is published to unauthenticated callers.** A request with *no* credentials returns a 401 body containing `available_dev_users`: a roster of real user ids, display names, and roles ([:592-593](server/security/security_store.py#L592-L593), [:510-515](server/security/security_store.py#L510-L515)). `GET /api/persistence/health` — a public route ([server/main.py:74](server/main.py#L74)) — advertises `devUserHeaderEnabled` and a worked header example ([server/persistence/persistence_router.py:139-153](server/persistence/persistence_router.py#L139-L153)).

**Why this is severe rather than a dev convenience:** an operator who does the two obvious hardening steps — set `ATLAS_AUTH_ENABLED=true` and a strong admin password — **is still fully exposed**, because neither variable controls this path.

**Fix:** invert the default. Require an affirmative `ATLAS_ENABLE_DEV_USER_HEADER=true` **and** default `ATLAS_LOCAL_DEV` to `false`; bind the header path to loopback only; run `enforce_hosted_security_configuration()` unconditionally at startup; strip `available_dev_users` from 401 bodies and the header hint from the public health route.
**Remediation test:** with no env vars set, `GET /api/projects` with `X-ATLAS-USER-ID: <seeded admin>` → assert 401.

### SEC-P0-3 — Authenticated users execute arbitrary native code as the server process; `=default` is not a sandbox

**OBSERVED FACT — verified in source.**

```python
# server/code_execution/sandbox_policy.py:136,152-153
SYMBOLIC_DEFAULTS = {"default","venv","project-venv"}
if raw_command.strip().lower() in SYMBOLIC_DEFAULTS: raw_command = default_sandbox_command()

# server/code_execution/sandbox_policy.py:271
return f'"{venv}" -I {SCRIPT_TOKEN}'

# server/python_execution.py:287-296
completed = subprocess.run(command, cwd=str(temp_dir), capture_output=True,
                           timeout=TIMEOUT_SECONDS, env=execution_env())
```

`ATLAS_CODE_SANDBOX_COMMAND=default` — **the setting this project requires for Python execution** — resolves to the project's own venv interpreter with `-I`, run as a plain child of the API process. `-I` ignores `PYTHON*` env vars and the user site directory. It does **not** restrict `open()`, `os.remove`, `subprocess`, `socket`, or `ctypes`. There is no container, seccomp, namespace, chroot, rlimit, or separate OS user. The child inherits the API process's full filesystem privileges — including the SQLite auth database and password hashes.

The module's own claim — *"enabling execution does not widen the deployment's trust boundary"* ([sandbox_policy.py:40-42](server/code_execution/sandbox_policy.py#L40-L42)) — is true for the **operator** and false for the **end user**, who gains server-process code execution. This is the most consequential mis-framing in the codebase.

**The authorization guard is conditional:**

```python
# server/python_execution.py:367-371
if request.projectId:                     # projectId defaults to "" at :126
    authorize_modeling_scope(user, request.projectId, "view")
return run_python_request(request)        # runs regardless
```

Omit `projectId` and **no authorization runs at all**. The sibling execution routes — `POST /api/code/r/run` ([:426](server/python_execution.py#L426)), `/code/sas/run` ([:517](server/python_execution.py#L517)), `/code/sas-compatible/run` ([:583](server/python_execution.py#L583)), and `POST /api/notebooks/{id}/run-cell` / `run-all` ([server/notebooks/notebook_router.py:93,105](server/notebooks/notebook_router.py#L93)) — declare **no user parameter and no project scope at all**.

**Mitigating:** defaults are safe when unset (execution refused, [:222-229](server/code_execution/sandbox_policy.py#L222-L229)), and `ATLAS_HOSTED_MODE=true` disables it. The policy layer is well built *for what it targets* — allowlisted interpreter, resolved-path identity check, shell-metacharacter rejection, argv-only invocation. It defends against a malicious **operator config**, not malicious **user code**.

**Fix:** make authorization unconditional; add `require_user` + project scope to the R/SAS/notebook routes; rename `default` to something that cannot be mistaken for a sandbox; require a real isolation boundary (container, dropped capabilities, read-only rootfs, no network, non-privileged UID, rlimits) for any multi-user deployment.

### SEC-P0-4 — Cross-user IDOR across ~12 resource families — **CONFIRMED LIVE**

This is the finding with the strongest evidence in the audit: predicted from source by the security lane, then **reproduced against the running system**.

**Live probe setup (GET only, nothing mutated):**
- `ADMIN` = `local-user` (role `admin`)
- `DS_A` = a real `data_scientist` who owns **1 project and 0 datasets**
- `DS_B` = a second real `data_scientist`

**Result — what DS_A could actually read:**

| Probe | DS_A result | Verdict |
| --- | --- | --- |
| `GET /api/evidence` | **227 items spanning 112 distinct projects and 16 distinct creators** | cross-project exposure |
| `GET /api/evidence/{foreign id}` | **200 — full governance record** incl. project name, business-objective summary, model ids | cross-project read |
| `GET /api/notebooks` | **5 notebooks, all foreign** (projects DS_A does not own) | cross-project exposure |
| `GET /api/notebooks/{foreign id}` | **200 — full notebook including cell source** | cross-project read |
| `GET /api/projects/registry` | **27 projects, all 27 foreign** | list-filter bypass |
| `GET /api/projects/recovery/scan` | 27 candidates (same as admin) | recovery tooling exposure |
| `GET /api/registry/assets` / `activity` | 100 / 100 (same as admin) | cross-project exposure |
| `GET /api/users` | **200 users** — full directory incl. email, `failedLoginCount`, `lockedUntil` | info disclosure |
| `GET /api/monitoring/plans?projectId=<foreign>` | 200 | cross-project |
| `GET /api/validation/queue?projectId=<foreign>` | 200 | cross-project |
| `GET /api/sql-studio/queries` | 200 | cross-project |

**The controls that DO work — also verified live:**

| Probe | DS_A | ADMIN | Verdict |
| --- | --- | --- | --- |
| `GET /api/datasets` (list) | **0 datasets** | 12 | correctly filtered |
| `GET /api/datasets/{foreign}` | **403** | 200 | correctly enforced |
| `GET /api/datasets/{foreign}/versions` | **403** | 200 | correctly enforced |
| `GET /api/projects` (list) | **1 (own)** | 127 | correctly filtered |
| `GET /api/admin/*` (10 endpoints) | **403** | 200 | correctly enforced |
| `GET /api/audit-log`, `/api/audit/events` | **403** | 200 | correctly enforced |
| `GET /api/security/diagnostics` | **403** | 200 | correctly enforced |
| No identity header | **401** | — | correctly enforced |

**The decisive contrast:** `GET /api/projects` returns 1 project; `GET /api/projects/registry` returns 27. Two project-list endpoints, one filtered, one not.

**Root cause — OBSERVED FACT.** The unfiltered routers receive `Depends(require_user)` at the `main.py` include level ([:286-304](server/main.py#L286-L304)) and perform zero resource checks. Representative:

```python
# server/evidence/evidence_router.py:95-99 — no user param, no ownership check
@router.get("/evidence/{evidence_id}")
def read_evidence(evidence_id: str) -> Dict[str, Any]:
    item = get_evidence(evidence_id)
    ...
# server/evidence/evidence_router.py:110-112 — any user deletes any evidence
@router.delete("/evidence/{evidence_id}")
def remove_evidence(evidence_id: str) -> Dict[str, Any]:
    return {"ok": True, "deleted": delete_evidence(evidence_id)}
```

The correct pattern already exists in the same codebase — `_authorize_project` ([server/persistence/persistence_router.py:73-107](server/persistence/persistence_router.py#L73-L107)), `authorize_modeling_scope` ([server/core/modeling_scope.py:56-107](server/core/modeling_scope.py#L56-L107)), `_get_model_authorized` ([server/model_registry/model_registry_service.py:160-168](server/model_registry/model_registry_service.py#L160-L168)).

**Affected routers (no resource-level authorization found):** `evidence`, `monitoring` (40 endpoints), `credit_risk` (31 endpoints — no handler declares a `user` at all), `analytics_engine`, `model_documentation`, `validation`, `notebooks`, `sql_studio`, `registry`, `projects/project_router`, `analytics/analytics_router`, `charts`, `model_diagnostics`, `optimization`, `experimentation`, plus `GET /api/projects/{id}/access` ([server/security/security_router.py:204-206](server/security/security_router.py#L204-L206)) and `GET /api/users` ([server/datasets/dataset_router.py:85-87](server/datasets/dataset_router.py#L85-L87)).

**Write-side exposure (predicted from source; not exercised, because the audit is read-only):** `DELETE /api/evidence/{id}`, `PUT /api/monitoring/plans/{id}`, alert close/accept-risk, `PATCH /api/validation/cases/{id}`, `POST /api/projects/registry` (overwrite any project record), `DELETE /api/notebooks/{id}`.

**Regulatory impact — the most serious item for a bank pilot.** Credit-risk scorecards, WOE/IV binning, validation findings, and evidence packs are precisely the artifacts SR 11-7 / OCC 2011-12 require to be access-controlled and segregated between development and independent validation. A developer able to silently alter a validator's findings collapses the effective-challenge control.

**Fix:** apply `authorize_modeling_scope` as the first statement of every project-scoped route; add service-layer `_get_<resource>_authorized` for id-addressed resources; filter LIST routes per row. Then **extend the startup assertion into `assert_api_routes_authorized`** with a reviewed allowlist, so the green signal means what it appears to mean and cannot regress.
**Remediation test:** two-user integration suite issuing B's session against A's ids across all affected endpoints, asserting 403/404 — gated in CI.

---

## 4. P1 findings

**SEC-P1-1 — Cross-resource substitution.** `POST /api/python/run` authorizes `projectId` ([server/python_execution.py:369-370](server/python_execution.py#L369-L370)) and separately authorizes `context.datasetId` via `require_dataset` ([server/code_execution/dataset_binding.py:73](server/code_execution/dataset_binding.py#L73)) — but never checks the dataset is linked to that project. The correct both-sides pattern exists at [server/datasets/dataset_router.py:201-205](server/datasets/dataset_router.py#L201-L205). Same shape in `credit_risk` register-model/save-evidence. `PUT /api/evidence/{id}` accepts an arbitrary `projectId` and re-parents freely, while the persistence router explicitly forbids exactly that ([persistence_router.py:405-408](server/persistence/persistence_router.py#L405-L408)).

**SEC-P1-2 — Session cookie not `Secure` by default; no CSRF token.** `secure = not ATLAS_LOCAL_DEV or ATLAS_HOSTED_MODE` ([server/security/security_router.py:84](server/security/security_router.py#L84)) evaluates to **False** with defaults. `httponly` and `samesite="lax"` are correctly set. No CSRF token, double-submit, or Origin check exists anywhere. `SameSite=Lax` incidentally mitigates the cookie path but gives **zero** protection on the header path (SEC-P0-2). CORS uses `allow_credentials=True` with `allow_headers=["*"]` ([server/main.py:143-145](server/main.py#L143-L145)), so `X-ATLAS-USER-ID` is accepted cross-origin from any allowed origin.

**SEC-P1-3 — No per-user resource quotas.** Per-request bounds are good (250 MB / 500k rows / 750 cols upload; 60s code timeout; DuckDB memory/thread limits). Per-user aggregate bounds do not exist: nothing limits concurrent `/python/run` subprocesses, and `subprocess.run` sets no memory or child-process rlimit. Several `limit` params are unclamped — `monitoring/router.py:37,148`, `persistence_router.py:594,605`, `admin/router.py:206` (default 5000) — while the correct pattern exists at `registry/router.py:34` (`Query(100, ge=1, le=500)`).

---

## 5. P2 / P3 findings

| ID | Finding | Evidence |
| --- | --- | --- |
| SEC-P2-1 | **Model artifact checksum stored but never verified on load.** `joblib.load` (pickle, executes on deserialize) runs on unverified bytes | [server/model_registry/model_artifacts.py:59-60,83](server/model_registry/model_artifacts.py#L83) |
| SEC-P2-2 | **Audit trail append-only by API but no tamper-evidence.** No `DELETE FROM audit` / `UPDATE audit` anywhere (good); no hash chain or signature (gap). Attribution derives from header-asserted identity, so it is forgeable at source | [server/security/security_store.py:692-756](server/security/security_store.py#L692-L756) |
| SEC-P2-3 | **CSV/Excel exports do not neutralize formula injection.** No leading `= + - @` handling anywhere. Attacker-controlled text reaches audit-log CSV and evidence exports — opened by admins and validators | [server/admin/admin_service.py:238-244](server/admin/admin_service.py#L238-L244) |
| SEC-P2-4 | **Info disclosure — verified live.** `GET /api/users` returns 200 users with email/`failedLoginCount`/`lockedUntil` to any authenticated caller; 401 bodies list valid user ids | [server/datasets/dataset_router.py:85-87](server/datasets/dataset_router.py#L85-L87) |
| SEC-P2-5 | **Dataset `editor` can self-escalate to `owner`.** Grant requires only `write=True`, which `editor` satisfies; the granted role is not checked against the granter's level | [server/datasets/dataset_registry.py:616-622](server/datasets/dataset_registry.py#L616-L622) |
| SEC-P3-1 | Unescaped HTML sink in report rendering (sanitization behaviour of `renderReportContentHtml` **UNVERIFIED**) | [src/components/ReportSectionContent.tsx:115](src/components/ReportSectionContent.tsx#L115) |
| SEC-P3-2 | SQL guard is a regex denylist rather than a parser. Blast radius small (in-memory SQLite, caller's own rows) but denylists erode | [server/analytics/analytics_router.py:261-269](server/analytics/analytics_router.py#L261-L269) |
| SEC-P3-3 | ~9 declared Python packages have **zero import sites**, including `python-jose` and `mlflow`. Two unmounted unguarded routers (`stela_router.py`, `viz_endpoints.py`) would bypass the startup check if mounted, since it skips non-`/api/` paths ([main.py:98](server/main.py#L98)) | `requirements.txt` |

---

## 6. What is genuinely well built

Stated plainly, because it is substantial and should not be lost in the finding count:

- **Path traversal is well defended everywhere** — segment regex + `relative_to()` containment on dataset artifacts ([dataset_registry.py:560-574](server/datasets/dataset_registry.py#L560-L574)), `_within_artifact_root()` on model read/write/delete, resolved-path containment on sandbox staging, `basename()` + extension allowlist on upload. **No `FileResponse`/`send_file` anywhere. No archive extraction anywhere.**
- **Unsafe deserialization is narrow.** Server-wide, `shell=True`, `eval(`, `exec(`, `pickle.load`, `torch.load`, `yaml.load(` return **zero** hits. The only pickle-family sink is one guarded `joblib.load`.
- **SQL is parameter-bound.** DuckDB values use `?` placeholders; identifiers pass a strict allowlist regex that raises on mismatch; extension autoinstall/autoload disabled.
- **Password hashing, session management, and lockout are correct.**
- **The modeling core is genuinely isolated** — DATASTORE and RESULTS keyed by `(user_id, project_id)`, TRAINING_JOBS ownership enforced, dataset ACL, model-registry and scoring-run authorization, and per-row list filtering in the persistence router. **Verified live: 19 of 19 core probes behave correctly.**
- **`assert_api_routes_authenticated` is a good control** — it just needs extending from authentication to authorization.

---

## 7. Two-user authorization matrix (summary)

Static analysis produced 49 matrix cells: **19 CONFIRMED-BY-CODE**, **27 GAP**, **3 UNVERIFIED**. Live probing confirmed the CONFIRMED cells behave correctly and confirmed 11 of the GAP cells are exploitable read-side today by an ordinary, legitimately provisioned user with no bypass required.

---

## 8. Deployment-tier verdict

| Tier | Verdict |
| --- | --- |
| **Local single-user developer edition** | **Acceptable today.** With one trusted user on loopback, none of the P0s has a second party to harm. |
| **Paid design-partner pilot (multiple named users)** | **Blocked.** SEC-P0-1, P0-2 and P0-4 must close first. P0-4 is reachable by ordinary pilot participants with no bypass. |
| **Single-institution controlled deployment** | **Blocked.** All four P0s plus P1-1 and P1-2; SEC-P0-3 requires a real execution boundary or execution disabled. |
| **Enterprise multi-user production** | **Blocked.** All of the above plus audit tamper-evidence, per-user quotas, and artifact-integrity verification. |

**Minimum viable fix order:** SEC-P0-1 (one-line change) → SEC-P0-2 (invert the default, fail-closed) → SEC-P0-4 (systematic; extend the startup assertion so it cannot regress) → SEC-P0-3 (real sandbox, or disable execution in multi-user deployments).

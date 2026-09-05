# ASP Model Studio — Threat Model (Fable 5.1 independent audit)

Audit base: branch `codex/mlb-player-prior-wave2`, HEAD `bff19a8a657bc96dea0469fad481acdcb4234386`.
Audit branch: `claude/fable51-model-studio-security-ml-integrity-audit`.
Scope: the ASP Model Studio repository only (`C:\Users\james\asp-model-studio`). AI Sports Predictor was not inspected.

This document records the actors, assets, trust boundaries, attack paths, and abuse cases that drove the dynamic tests in the
main audit report. Where a path was exercised, the result is cross-referenced to a finding ID
(`docs/ASP_MODEL_STUDIO_FABLE51_FINDINGS.json`).

## 1. System summary (as built at bff19a8)

| Layer | Implementation | Notes |
| --- | --- | --- |
| Frontend | React 18 + Vite, `src/apps/ModelingApp.tsx`, served by Vite dev server on 127.0.0.1:5274 | Cookie session, `credentials: "include"` on every fetch |
| API | FastAPI + uvicorn (single process, sync handlers on a thread pool), `server/main.py`, 616 routes | Every `/api/*` route except six public paths requires `require_user` (enforced by `assert_api_routes_authenticated` at startup) |
| Identity | `server/security/security_store.py`: PBKDF2-SHA256 (260k iterations), opaque 43-char session ids, `SameSite=Lax; HttpOnly` cookie, 8h TTL, lockout after 5 failures | Separate SQLite security DB |
| Authorization | `server/sharing/sharing_service.py` (`check_permission`): admin role bypass, project owner, explicit `resource_permissions` rows | Legacy `/projects/{id}/access/*` routes map onto the same table |
| Persistence | SQLite, WAL, `busy_timeout=10000`, `foreign_keys=ON` per connection, 38 migrations, 114 tables | One file for projects/authorities, one for identity |
| Scientific authorities | Content-addressed JSON manifests on disk (Gold, sufficient-statistics companion, V1/V2 prior stores, executable artifacts, model-lab receipts) | Roots resolved from env vars, repo-relative defaults, and hard-coded staging paths |
| Background work | In-process `ThreadPoolExecutor(max_workers=1)` per job family, interprocess file locks, job rows in `run_records` | No external queue, no worker process |
| External sources | Statcast (Baseball Savant), Retrosheet, Chadwick, Lahman, nflverse (research) | Ingested by scripts outside the API; the API never calls a provider |

## 2. Actors

| Actor | Capability assumed | Motivation |
| --- | --- | --- |
| A1 Unauthenticated visitor | Network access to the API/frontend | Enumerate, brute force, exhaust audit storage |
| A2 Ordinary authenticated user (`data_scientist`) | Valid session, own projects | Read or alter other users' projects, models, evidence; reach final OOT |
| A3 Project owner | Full control of own project | Bypass scientific gates (adopt blocked policy, register non-executable feature set, promote) |
| A4 Workspace administrator | Admin role bypass on every resource | Accidental or deliberate cross-project mutation without a governed version/audit trail |
| A5 Malicious authenticated user | A2 plus tooling | Privilege escalation, artifact substitution, identity confusion |
| A6 Compromised browser session | Stolen cookie or XSS | Act as the victim across projects |
| A7 Malicious uploaded dataset | CSV/JSON upload through `/api/data/upload_csv` | Formula injection, oversized payloads, parser bombs |
| A8 Malicious archive | Not currently accepted (no archive ingestion endpoint) | Zip-slip if a future `.atlas` package importer lands |
| A9 Malicious serialized model | Write access to an artifact root | Arbitrary code execution through `joblib.load` |
| A10 Compromised model worker | Same process as the API (no separation) | Full read/write of every authority root and both databases |
| A11 Accidental concurrent operator | A second agent/session (Codex, another shell, a second uvicorn) | Duplicate jobs, lock contention, contamination of authoritative stores |
| A12 Internal developer | Repository and workstation access | Hard-coded defaults, test pollution of `.runtime`, script actors writing authoritative rows |
| A13 External data provider | Controls upstream content and terms | Rights restrictions, silent schema/content changes |
| A14 Dependency / supply-chain attacker | npm/PyPI packages | Vulnerable transitive dependencies (see scanner receipt) |

## 3. Assets

| Asset | Where | Protection observed | Finding refs |
| --- | --- | --- | --- |
| Credentials | `security.credentials` (PBKDF2) | Hashed with per-user salt; never returned by API | — |
| Sessions | `security.sessions` | Opaque ids, expiry enforced, revocation on logout/role change | F-021 (no cap, no rotation) |
| Project identities & ownership | `persistence.projects.owner_user_id` + `resource_permissions` | Owner/admin/explicit-grant checks on nested routes | **F-001 (self-grant takeover)**, F-004 |
| Uploaded files | Dataset Library roots | Size/row/column limits, immutable versions | F-030 (formula injection not sanitized) |
| Bronze/Silver/Gold/contextual evidence | `C:\Users\james\asp-data-staging\*` (outside repo) | Content-addressed manifests; complete-byte verification on cold load | F-010 (warm-cache masks tamper), F-012 (hard-coded staging paths) |
| Targets (`outcome`) | Gold partitions | Non-selectable in EDA/features; excluded from feature sets | — (verified) |
| Final-OOT outcomes | Gold 2026 partition rows 2026-08-14..27; companion sealed partition (payload NULL) | Date-bounded scans, filter rejection, plan option rejection | — (verified) |
| Prior authorities (V1/V2) | `.runtime/.../stage3-player-prior-authorities*` | Content-addressed; pointer per project | **F-002 (V2 store lives only in a disposable worktree)**, F-011 (500 on tamper) |
| Treatment policies / specification | `stage3_*` tables (immutability triggers) | Draft/adopt with checksums; adoption held closed | F-013 (gating depends on draft existence) |
| Split contracts | `stage3_split_contract_versions` | Immutable trigger; registration gated by quality gates | — (verified) |
| Model binaries / preprocessing / OOF | `stage3-executable-artifacts` (joblib + parquet) | Manifest-last publication; every member re-hashed before `joblib.load` | F-009 (summary endpoint does not re-verify) |
| Model-lab receipts | `stage3-model-laboratory/objects/sha256/*.json` | Content-addressed; tampered receipts drop out of the ledger | — (verified) |
| Champion/challenger decisions | `run_records` decision rows | Explicit user decisions only; no auto-promotion | F-003 (single-project binding) |
| Registry entries / exports | `run_records`, `export_artifacts` | Append-only | — |
| Audit history | `security.audit_events` + `persistence.audit_log` | Append-only intent; deletable by DB owner | F-024 (no tamper evidence), F-022 (write amplification) |
| Source-rights records | `sports_dataset_rights`, `sports_dataset_limitations` | Persisted per registration | See data-rights matrix |

## 4. Trust boundaries

```
 Browser (React) ──cookie──▶ FastAPI API ──sqlite3──▶ persistence.db / security.db
      │                        │   │
      │                        │   └──fs──▶ .runtime/asp-model-studio/* (artifacts, prior stores, locks, checkpoints)
      │                        │                 ▲
      │                        └──fs──▶ C:\Users\james\asp-data-staging\* (Gold, companion, Silver)   ── scripts (Codex/dev) write here
      │                        └──fs──▶ C:\Users\james\asp-model-exchange\* (immutable exchange)
      │
      └── other local origins (127.0.0.1:5173 AI Sports Predictor) are CORS-allowed with credentials in local mode
 In-process ThreadPoolExecutor(1) "worker" shares memory, env, and file handles with the API
 Codex worktrees (.tmp/*) run their own backends against the SAME persistence.db and staging roots
```

Boundary observations that matter for controlled beta:

1. **API ⇄ worker** is not a boundary today. A job runs inside the API process; there is no sandbox, quota, or memory ceiling beyond `_native_worker_budget`.
2. **Primary checkout ⇄ staging roots**: the API trusts absolute staging paths compiled into source. Anyone with filesystem access to `asp-data-staging` or a Codex worktree can redirect scientific authority without touching the repository.
3. **One project ⇄ another**: enforced by `SharingService.check_permission` on every `/projects/{id}/…` route, but the legacy grant route contains a bootstrap exception that any user can trigger (F-001).
4. **One user ⇄ another**: `ACTIVE_USER` context propagation is correct under concurrency (400 interleaved requests, zero identity mix-ups), but non-project cockpit routes (`/cockpit/*`) expose the shared research object to every authenticated user.
5. **One sport ⇄ another**: NFL and other sports are `RESEARCH_ONLY`/`PLANNED` in the registry; no NFL API routes exist; registrations share tables but carry `sport`/`league` columns and distinct id prefixes.
6. **Model Studio ⇄ AI Sports Predictor**: no code path in this repository calls AISP; the only coupling is the exchange root and the permissive local CORS list.
7. **Raw source ⇄ governed derivatives**: derivations run in scripts with synthetic actor ids (`codex-wave2-prior-engine`, `codex-stage3-*`) written straight into authoritative tables (F-005).

## 5. Attack-path diagram (highest-risk paths)

```
[A2/A5 ordinary user]
   │ POST /api/projects/{victim}/access/grant {userId: self, permission: owner}
   ▼ (first_owner_claim exception: no permission rows yet ⇒ granted)                 ─── F-001 (P0)
[admin-level permission on victim project]
   ├─▶ GET/PUT/DELETE project, workflow state, forecast contract              (demonstrated)
   ├─▶ read feature sets, policies, split, runs, downstream decisions          (demonstrated)
   └─▶ POST stage3-downstream/selection (challenger decision)                  (reachable; not executed)

[A12 developer / A11 concurrent agent]
   │ run evaluator script in a worktree with default security DB + bootstrap flags
   ▼
[authoritative persistence.db mutated by "local-user" / "codex-*" actor ids]   ─── F-005 (P1)
   └─▶ V2 fitted authorities written ONLY under .tmp/<worktree>/.runtime      ─── F-002 (P1)

[A9 malicious serialized model]
   │ needs write access to stage3-executable-artifacts root
   ▼ every member is re-hashed against the content-addressed manifest before joblib.load
[blocked at verify_artifact_bundle]                                            ─── verified (18/18 tampers rejected)

[A1 visitor]
   ├─▶ unlimited login attempts (no IP rate limit; per-account lockout only)   ─── F-020
   └─▶ every unauthenticated request writes 2 audit rows                        ─── F-022

[A2 user, final OOT]
   ├─▶ EDA/treatment filters into 2026-08-14..27  ⇒ FINAL_OOT_FILTER_PROHIBITED (verified)
   ├─▶ manual split into OOT ⇒ SPLIT_MANUAL_BOUNDARY_NOT_REPRESENTED (verified)
   ├─▶ plan option finalOot ⇒ MODEL_DEVELOPMENT_FORBIDDEN_OPTION (verified)
   └─▶ cockpit data-preview season=2025 ⇒ 410 (verified)
```

## 6. Asset / control matrix

| Control | Credentials | Sessions | Projects | Datasets | Gold/OOT | Priors | Policies/Spec | Splits | Models/Artifacts | Decisions | Audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Authentication required | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Per-resource authorization | n/a | own | ✔ except F-001/F-004 | dataset ACL | via project | via project | via project | via project | via project | via project | role-gated |
| Content addressing | n/a | n/a | — | manifests | ✔ | ✔ | checksums | checksums | ✔ | receipts | — |
| Immutability (DB trigger) | — | — | — | — | — | — | ✔ | ✔ | — | append-only | none |
| Re-verification on read | — | expiry | — | — | cold only (F-010) | ✔ (500 on failure, F-011) | ✔ | ✔ | loader only (F-009) | ✔ | — |
| Audit event | ✔ | ✔ | ✔ | ✔ | — | — | ✔ | ✔ | ✔ | ✔ | — |
| Backup | none (F-040) | none | none | dataset bundles only | none | none | none | none | none | none | none |

## 7. Abuse-case inventory (tested)

| ID | Abuse case | Result | Finding |
| --- | --- | --- | --- |
| AC-01 | User A lists/reads/edits/deletes User B's project by id | Denied (403) on 60+ routes | — |
| AC-02 | User A self-grants "owner" on User B's project | **Granted** | F-001 |
| AC-03 | User A self-grants on the authoritative Wave 2 project | **Granted** | F-001 |
| AC-04 | User A reads any project's ACL | Allowed (200) | F-004 |
| AC-05 | Existence inference: 403 vs 404 body/status | Distinguishable | F-023 |
| AC-06 | Non-admin calls admin/audit/diagnostics routes | Denied | — |
| AC-07 | Self role escalation | Denied | — |
| AC-08 | 400 interleaved requests from two users | 0 identity mix-ups | — |
| AC-09 | Reuse revoked/forged/expired cookie | Denied (401) | — |
| AC-10 | Session fixation with attacker-chosen id | New id issued | — |
| AC-11 | Cross-site POST with valid cookie and evil Origin | Processed (server relies on SameSite=Lax) | F-025 |
| AC-12 | 150 login attempts / 12 s | No throttling | F-020 |
| AC-13 | Unauthenticated GET flood | 1 audit row per request per DB | F-022 |
| AC-14 | Final-OOT reach through EDA, treatments, splits, plans, cockpit | All closed | — |
| AC-15 | Target column as EDA variable / feature | Rejected | — |
| AC-16 | Tamper model/preprocessor/OOF/manifest/paths | Loader rejects 18/18 | F-009 (summary only) |
| AC-17 | Tamper Gold partition while API warm | Served from cache | F-010 |
| AC-18 | Tamper V2 prior store | 500 (fail closed, unhandled) | F-011 |
| AC-19 | Edit immutable DB rows directly | Trigger rejects split/policy/spec versions; run_records/projects mutable | F-024 |
| AC-20 | Register feature set containing semantic/zero-variance fields on a project with no spec draft | See main report §9 | F-013 |
| AC-21 | Adopt the specification with tampered booleans | Rejected | — |
| AC-22 | Use another project's adopted policy ids | Draft accepted; registration rejected as stale | — |
| AC-23 | Duplicate concurrent drafts with same expected checksum | Exactly one wins (CAS) | — |
| AC-24 | Cockpit research-object routes without project membership | Authenticated but unscoped | F-006 |

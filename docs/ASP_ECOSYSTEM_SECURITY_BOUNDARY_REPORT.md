# ASP Ecosystem — Cross-System Security Boundary Report

**Date:** 2026-08-18
**Scope:** trust boundaries between the components of the ASP ecosystem. No code was
copied between repositories. Companion deep audits:
`asp-model-studio/docs/ASP_MODEL_STUDIO_DEEP_SECURITY_AUDIT.md` and
`ai-sports-predictor/docs/AI_SPORTS_PREDICTOR_DEEP_SECURITY_AUDIT.md`.

---

## 1. Components & trust zones

| Component | Trust zone | Notes |
|-----------|-----------|-------|
| Customer browser / mobile app | **Untrusted** | Holds a bearer JWT (AISP) or session cookie (ASP). Never an authority. |
| AI Sports Predictor (AISP) backend | **Trusted (product)** | Public-facing product; owns customer identity + entitlements. |
| ASP Model Studio (ASP) backend | **Trusted (internal lab)** | Local/single-tenant model development; not public. |
| Model-exchange package | **Semi-trusted, verified** | Content-addressed data (parquet/JSON); trusted only after SHA-256 + pinned-digest verification. |
| Stripe / payment processor (future) | **External, authoritative for money** | Source of truth for payment; verified via signed webhooks only. |
| Sports data providers (The Odds API, MLB StatsAPI, Open-Meteo) | **External, untrusted input** | Rate/quota controlled; responses are untrusted data. |

---

## 2. The boundaries and how each must fail closed

### B1. Browser → AISP / ASP backend
- **Control:** server-side auth on every route (AISP: `get_current_user` Bearer+JWT;
  ASP: `require_user` cookie session, enforced at startup). UI hiding is never
  authorization. **Absent context never becomes a user/admin** (both repos verified;
  ASP `current_user()` hardened this pass).
- **Must never cross unprotected:** raw passwords (Argon2/PBKDF2 only), session
  secrets, admin tokens, another user's data.

### B2. ASP Model Studio → model-exchange package → AI Sports Predictor
- **Direction:** ASP publishes an immutable, content-addressed bundle; AISP imports.
- **Controls (verified on the AISP import side):** per-file SHA-256 recomputed from
  bytes; semantic manifest digest recomputed and all derived IDs verified; **pinned
  expected authority digests** (bridge/alias/dimension) → **downgrade/rollback
  prevention**; symlink/junction/reparse/hardlink/escape rejection; **parquet-only**,
  no `pickle`/`joblib` → **no code executes on import**.
- **Must never cross unprotected:** an **unsigned or tampered bundle** (rejected by
  digest mismatch), a **downgraded/stale bundle** (rejected by pinned digest), any
  **executable/pickled model** (format not permitted), ASP **physical/runtime paths**
  (stripped/rejected).
- **Recommendation:** if a bundle ever transits an untrusted channel (not just local
  disk), add a **detached signature** over the manifest digest; content-addressing +
  pinned digests already cover the local trust model.

### B3. Backend → Stripe / payment processor (future)
- **Direction:** client → backend → Stripe-hosted Checkout/Portal; Stripe →
  **signed webhook** → backend → **server-side entitlement ledger** → entitlement
  decides access. (AISP already has the server-side entitlement table.)
- **Must never cross unprotected / must never be trusted from the client:**
  amount, price ID, subscription status, "success" redirect. Entitlement is granted
  **only** from a signature-verified, de-duplicated webhook event reconciled against
  Stripe.
- **Must never be stored:** card data, raw bank/online-banking credentials, raw
  routing/account numbers. Use Stripe-hosted + tokenized ACH (Financial Connections).

### B4. Backend → sports data providers
- **Control:** hardcoded provider base URLs (no user-supplied URL fetch → no SSRF);
  strict quota (AISP: `ODDS_DAILY_REQUEST_BUDGET=1`, polling off, cooldown, floor).
  Provider responses are **untrusted data**, validated before persistence.
- **Must never cross unprotected:** provider API keys (backend-only, gitignored
  `.env`; never in a `VITE_*`/frontend bundle or logs).

### B5. Backend ↔ expert code / SQL execution (ASP)
- **Control:** Python execution is an intentional expert boundary, **disabled in
  hosted mode**, file-based, no `shell=True`; SQL Lab is in-memory SQLite over
  ACL-authorized previews; analytical DuckDB disables extensions (no SSRF). These are
  **single-tenant local** capabilities and must remain disabled in any multi-tenant
  or public deployment.

---

## 3. WHAT MUST NEVER CROSS A TRUST BOUNDARY UNPROTECTED

- **Stripe secret keys** — server-side only, secret manager, never frontend/logs.
- **Bank credentials / raw card / routing-account numbers** — never stored; tokenized
  processor references only.
- **Session/JWT secrets** (`ATLAS_SESSION_SECRET`, AISP `SECRET_KEY`) — server-side,
  ≥32 random chars in any shared/prod deployment (both repos machine-enforce this in
  hosted/production mode).
- **Provider credentials** (`THE_ODDS_API_KEY`, future `LLM_API_KEY`) — backend `.env`
  only; a live Odds key currently exists in AISP's untracked `.env` (not committed) —
  protect and rotate as needed.
- **Unsigned / tampered / downgraded model artifacts** — rejected by SHA-256 +
  pinned-digest verification (exchange) and by the ASP artifact checksum gate
  (`load_model_artifact`, hardened this pass).
- **Raw customer passwords** — Argon2 (AISP) / PBKDF2-SHA256 (ASP), never logged.
- **Privileged admin tokens / admin authority** — server-side role checks only; no
  implicit admin from an absent context (both repos verified/hardened).

---

## 4. Least-privilege architecture (recommended target)

1. **Keep ASP Model Studio private** (local/single-tenant). Its expert Python/SQL
   execution must never be exposed to untrusted users; hosted mode already disables
   Python execution.
2. **AISP is the only public surface.** It owns customer identity + the entitlement
   ledger; ASP never authenticates end customers.
3. **One-way, verified exchange** ASP → AISP: content-addressed bundles, verified on
   import, pinned to expected digests. AISP never imports executable model code.
4. **Payments live only in AISP**, behind Stripe-hosted flows + signed webhooks +
   the server-side entitlement ledger. ASP has no payment surface.
5. **Provider egress is backend-only, quota-bounded, hardcoded-URL** (no SSRF), keys
   in secret storage.
6. **Secrets in a manager** (not `.env`) for any shared/prod deployment; rotation +
   incident-revocation runbooks per the deep audits.

---

## 5. Ecosystem readiness verdict

Choosing the **highest state supported by current evidence**:

> **SAFE FOR PRIVATE POC** (both repositories).

Rationale: both systems are fail-closed for auth/authorization, isolate tenants and
datasets, verify the model-exchange boundary (content-addressed, downgrade-protected,
no code execution on import), keep secrets out of Git, and gate weak dev defaults out
of production. They are **not yet** at *Authenticated Beta* / *Payment-Connected
Beta* because the following remain open (none are P0/P1):

- General **rate limiting** on auth/expensive endpoints (both repos).
- **Token-storage** decision in AISP (sessionStorage bearer vs HttpOnly cookie) + CSP.
- **Per-route entitlement** enforcement confirmation in AISP.
- **Payments** (Stripe-hosted + signed webhooks + entitlement ledger) not yet built.
- Production **secret provisioning** (machine-enforced, must be performed at go-live).

Once the rate-limiting + entitlement + token-storage items land, the ecosystem can
move to **READY FOR AUTHENTICATED BETA**; **PAYMENT-CONNECTED BETA** additionally
requires the §B3 Stripe architecture.

---

## 6. Confirmations (both repositories)

Real Stripe calls = 0 · real bank calls = 0 · sports-provider calls = 0 · no real
payment objects created · no full credentials printed (masked only) · no Git
commits/pushes/remote changes · financial ATLAS and `ds-workflow-starter` **not
accessed** · no code copied between repositories.

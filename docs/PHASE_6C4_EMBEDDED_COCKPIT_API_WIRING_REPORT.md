# Phase 6C.4 — Embedded PA Cockpit API Wiring Repair

## 1. Executive Verdict

**Root cause: a stale backend process, not a code defect.** The embedded (and standalone) PA
Modeling Cockpit is correctly wired: it uses the single shared API client, the correct base, and the
routes are mounted. The live `GET /cockpit/objective 404` occurs because the **running uvicorn
backend predates the Phase 6A cockpit router** and has not been restarted. **Resolution: restart the
ASP Model Studio backend.** This pass adds a durable frontend↔backend route-contract test that
proves the wiring and guards against future drift, plus an actionable error state for exactly this
stale-server case. **No backend code changed; no workflow changed.**

## 2. Reproduction & Decisive Diagnosis

Probing the live backend on `127.0.0.1:8101` (no auth):

| Path | Live backend | Meaning |
|---|---|---|
| `/api/sports/datasets/active` | **401** | route exists, needs auth |
| `/api/cockpit/objective` | **404** | route **absent from the running process** |
| `/api/cockpit/model-families` | **404** | route absent from the running process |

A 401 vs 404 split with the same client and base proves the running process simply lacks the
`/api/cockpit/*` routes — i.e., it was started before the cockpit router existed and is stale.

## 3. Frontend Request Construction (unchanged, correct)

`src/sports/cockpit/cockpitApi.ts` uses the **shared** client `getJSON`/`postJSON` from
`src/lib/api.ts` (no second client). `useEndpoint("/cockpit/objective")` fetches
`` `${BASE}${path}` `` where `BASE` comes from `VITE_API_BASE` (`/api` in `.env.modeling`, or the
absolute `http://127.0.0.1:8101/api` set by `start-asp-model-studio.ps1`). The resulting URL is
`/api/cockpit/objective` — **exactly the mounted route**. The error string `GET /cockpit/objective
failed: 404` logs only `${path}`; the fetched URL is `BASE + path`. No missing `/api` prefix, no
lost project context, no Vite-proxy mismatch (the proxy forwards all `/api/*`, and `/api/sports/*`
works).

## 4. Backend Route (present, correct)

`server/main.py:96` imports the router; `server/main.py:500`
`app.include_router(sports_cockpit_router, prefix="/api", …)` inside `create_app()`; `main.py:523`
`app = create_app()` — so the module-level `app` that uvicorn serves **does** include the cockpit
routes. `TestClient(app)` returns **200** for every cockpit GET endpoint (objective, population,
profile, outliers, missing, feature-catalog, feature/kinds, temporal-split, model-families,
champion, experiments, autopilot, eligibility, simulate, segmentation/*).

## 5. Standalone vs Embedded (single implementation)

Both render the **same** `PaModelingCockpit` component (embedded passes only `embedded` to suppress
the hero) and the **same** `cockpitApi.ts` → **same** shared client → **same** URLs. There is no
divergent API path; a fix to one is a fix to both. Confirmed by test
`test_frontend_uses_single_shared_api_client`.

## 6. The Fix

Because the wiring is already correct, the durable code contribution is a **route-contract test**
that fails if any frontend cockpit path ever stops resolving to a mounted backend route (the class of
defect a 404 represents), plus an **actionable error UX** so this stale-server situation is
self-diagnosing instead of a cryptic raw error.

- `tests/sports_cockpit_route_contract_test.py` — extracts every `/cockpit/...` path the frontend
  calls (18 static + 3 dynamic patterns) and asserts each matches a route mounted under `/api` in the
  assembled app; asserts the shared client is used and no host is hard-coded.
- `src/sports/cockpit/cockpitUi.tsx` `LoadGate` — on a 404 it now shows: *"The modeling API could
  not be reached … the backend is likely running an older build that predates the modeling cockpit —
  restart the ASP Model Studio backend to load the `/api/cockpit` routes, then reload."* It still
  shows the raw error and never fabricates an empty success state.

## 7. Endpoint Audit (all resolve to mounted routes)

objective · population · profile · profile/feature/{name} · outliers · missing · feature-catalog ·
feature/kinds · feature/profile · feature/ablation · temporal-split · model-families · champion ·
experiment/run · experiments · experiments/{id} · autopilot · eligibility · provider/verify ·
simulate · segmentation/summary · segmentation/kmeans · segmentation/pca · segmentation/stability ·
segmentation/grid — **all present** (route-contract test green; every one returns 200 via TestClient
apart from the heavy POST run/autopilot/simulate which are contract-verified separately).

## 8. Browser Acceptance

The live browser fix is to **restart the backend** (the running process is stale). I did **not**
restart the owner's stack: the start script generates a **random session secret per launch** (line
95) so a restart would log the owner out, and it asserts the ports are free (requiring the running
processes to be killed first) — tearing down the owner's authenticated session is not appropriate
here. After the owner restarts via `powershell -File scripts/start-asp-model-studio.ps1 -Start`
(with the stale backend stopped), `/api/cockpit/objective` returns 401 (exists) instead of 404 and
the embedded Step-6 cockpit loads. Browser walkthrough is therefore owner-deferred pending that
restart; the wiring correctness is fully covered by the contract test and TestClient.

## 9. Tests

- `tests/sports_cockpit_route_contract_test.py` — **4 passing** (routes mounted; every frontend path
  resolves; core 15-step endpoints present; single shared client).
- `tests/paModelingCockpit.test.mjs` — **15 passing** (14 prior + actionable-404 error).
- `tests/sportsGuidedWorkflow.test.mjs` — **26 passing** (unchanged).
- TypeScript clean; production build clean; **no Python/backend files changed**.

## 10. Remaining Limitations

- The definitive live fix requires a backend restart (a runtime action), which the owner performs;
  no code change can make a stale in-memory process load new routes.
- Session secret is random per launch (documented start-script behavior), so a restart re-requires
  login. Setting `ASP_MODEL_STUDIO_SESSION_SECRET` externally would make sessions survive restarts —
  a future convenience, out of scope here.

## 11. Exact Next Action

Restart the backend, reload `/workflows/mlb?step=6`, confirm Objective loads, then **stop
engineering and begin scientist modeling** in the embedded cockpit.

### Confirmations
workflow redesign = 0 · new science = 0 · model retraining = 0 · Monte Carlo = 0 · D3 changed = no ·
Phase 5 changed = no · auth weakened = no · security weakened = no · provider/network calls = 0 ·
backend code changed = no · pushes = 0 · remote changes = 0.

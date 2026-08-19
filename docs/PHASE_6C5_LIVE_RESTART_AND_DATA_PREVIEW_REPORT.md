# Phase 6C.5 — Live Backend Restart + Real Data Preview

## 1. Executive Verdict

Both live defects are resolved. **(A)** The stale backend that predated the cockpit router was
restarted; `/api/cockpit/*` now serves (401 unauth, **no 404**), so the embedded Step-6 cockpit
loads. **(B)** The scientist can now SEE the actual bound data: a governed, bounded plate-appearance
preview (real rows + schema/roles + target distribution + dev/val/frozen counts) is embedded in
both **Step 2 (Baseball Data Evidence)** and the cockpit **Step 02 (Data & Population)**. No science
changed; the new backend surface is a read-only, auth-scoped, bounded preview.

## 2. Part A — Live Backend Restart

- **Stale backend PID:** `86868` — `C:\Python312\python.exe -m uvicorn server.main:app --host
  127.0.0.1 --port 8101 --workers 1` (bare launch, system Python; predates the Phase 6A cockpit
  router). Confirmed stale: `/api/sports/datasets/active` → **401** (route exists) vs
  `/api/cockpit/objective` → **404** (route absent).
- **Method:** validated a fresh backend on a scratch port (8199) with the repo `.venv` Python and
  only `ASP_MODEL_EXCHANGE_ROOT` set — all cockpit + sports routes returned 401 (exist). The app
  falls back to the **default** session secret when `ATLAS_SESSION_SECRET` is unset (security_store
  line 56), which is what the bare-launched stale backend also used, so a matching relaunch
  **preserves the owner's session** (no logout). Then stopped **only** PID 86868 (verified its
  command line before killing — no unrelated processes touched) and relaunched a fresh
  `.venv` uvicorn on 8101; the frontend (node/vite, PID 17220 on 5274) was left untouched.
- **Cockpit route after restart (live :8101):**
  `/api/cockpit/objective` → **401**, `/api/cockpit/data-preview` → **401**,
  `/api/cockpit/model-families` → **401**, `/api/sports/datasets/active` → **401**. **No 404.**
- **Objective in the browser:** reloading `/workflows/mlb?step=6` now loads Objective (401 unauth →
  200 for the authenticated session). Auth/security unchanged.

## 3. Part B — Data Preview on Step 2 (Baseball Data Evidence)

After binding, Step 2 embeds `DataPreviewPanel` ("Your selected data"): a profile strip (rows,
columns, seasons, target, feature-missing %), the development/validation/frozen split, the 8-class
**target distribution**, sample controls (First 25 / Random, season filter, column search), a
**25-row** real-record table (game_date, season, game_id, batter/pitcher uuid, outcome, context
inning/outs/base, batter avg/obp/so/hr rates, pitcher era9/whip/so — IDs truncated), and a
**schema table** (column · type · **role** · missing % · example) under a disclosure. A secondary
"Open Full Data Warehouse ↗" preserves the deep-dive.

## 4. Part C — Cockpit Data & Population Preview

The embedded cockpit Step 02 embeds the same `DataPreviewPanel` ("Modeling matrix preview"),
explicitly the **modeling matrix / feature view** (`MLB_PA_FEATURE_VIEW_V1`, plate-appearance grain,
2023–2025) distinct from the broader raw registered evidence. It shows the actual rows cockpit
experiments train on, with the same schema/roles/target/split content.

## 5. Endpoint & Data Facts

- **New endpoint:** `GET /api/cockpit/data-preview?season=&limit=&sample=` — auth-scoped (behind
  `require_user`), **bounded** (limit clamped to ≤ 50), season-filterable, from the governed feature
  view. No file paths in the payload (test-enforced); no client file access; no synthetic rows.
- **Preview rows shown:** 25 (real registered records, e.g. `2023-03-30 · BOS game · STRIKEOUT`).
- **Columns shown (16 curated):** game_date, season, game_id, batter_uuid, pitcher_uuid, outcome,
  context_inning, context_outs_before, context_base_mask_before, batter_avg, batter_obp,
  batter_so_per_pa, batter_hr_per_pa, pitcher_era9, pitcher_whip, pitcher_so_per_bfp.
- **Schema:** 29 columns with roles TARGET (outcome) · TIME (game_date, season) · GROUPING
  (game_id) · IDENTIFIER (plate_appearance_id, batter/pitcher uuid) · FEATURE (the 22 model
  features).
- **Target distribution:** all 8 classes with real counts/shares (STRIKEOUT 123,685 …).
- **Development / Validation / Frozen counts:** 2023 = **184,104** · 2024 = **182,449** ·
  2025 = **182,926**. (The registered evidence spans additional raw seasons/families available in
  the Data Warehouse — surfaced honestly in the panel note.)

## 6. Tests

- **Backend** `tests/sports_cockpit_data_preview_test.py` — **6**: bounded rows (clamp ≤ 50), real
  registered records, schema roles, target distribution + dev/val/frozen splits, season filter, **no
  filesystem-path leakage**. `tests/sports_cockpit_route_contract_test.py` — **4** (now includes
  `/cockpit/data-preview`). `tests/sports_cockpit_test.py` (6A) — **16**. **26 backend passing.**
- **Frontend** `tests/sportsGuidedWorkflow.test.mjs` — **27** (Step 2 renders the real preview) ·
  `tests/paModelingCockpit.test.mjs` — **16** (cockpit Data & Population renders the modeling-matrix
  preview; bounded; no fixtures). TypeScript clean; production build clean; `py_compile` clean.

## 7. Performance & Safety

Bounded ≤ 50 rows; the feature view is loaded once and cached in the engine; no 900k-row payloads.
Auth + dataset authority respected; no arbitrary file-path access; dataset containment unchanged.

## 8. Remaining Limitations

- The preview is the plate-appearance **modeling matrix** (feature view, 2023–2025). Raw
  registered families/seasons (2021–2025) remain in the Data Warehouse via the secondary link.
- The live restart is a runtime action; the code needs no change to serve the routes — a future
  convenience would be pinning `ASP_MODEL_STUDIO_SESSION_SECRET` so restarts never risk logout.

## 9. Exact Next Action

Reload `/workflows/mlb?step=6`, confirm Objective loads and the Data & Population preview shows real
rows — then **stop engineering and begin model development** in the embedded cockpit.

### Confirmations
workflow redesign = 0 · new science = 0 · model retraining = 0 · Monte Carlo = 0 · D3 changed = no ·
Phase 5 changed = no · auth weakened = no · security weakened = no · provider/network calls = 0 ·
pushes = 0 · remote changes = 0.

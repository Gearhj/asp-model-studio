# ASP Model Studio — NFL 2026 Prospective Research-Shadow Activation

## Scope and disposition

The ASP Model Studio producer side of the NFL 2026 prospective shadow is active on
`codex/nfl-2026-prospective-shadow`, started from
`e60f5b1500e1c574e17a526a6c2e8bef047f92e2`. It is strictly
`RESEARCH_SHADOW`, `NOT_PROMOTED`, and `NOT_EXECUTABLE`. It does not publish to an
official-pick or bankroll track, read sportsbook fields, call a provider, fit a model,
or change MLB behavior.

Historical conclusion preserved: the M1 challenger did not demonstrate improvement
over the sportsbook benchmark (2025 OOT home-win log loss 0.628770 versus market
0.606989). Nothing in this activation changes that conclusion.

## Frozen model verification

- Candidate: `nfl-m1-xgboost-fixed-research-challenger-2026-shadow`
- Engine: `NFL_M1_XGBOOST` / NFL M1 Long-History XGBoost
- Model manifest SHA-256: `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9`
- Model binary SHA-256: `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd`
- Training cutoff: `2026-02-08`
- Feature tier: `LONG_HISTORY_CORE`
- Ordered predictor count: 197
- Ordered feature-contract SHA-256: `ef5c4f9ce8c3dd04a473e7ecb2ea3a255154f65a1bb3fda9d2ebc19bf1cb8f4d`
- Frozen training-foundation manifest SHA-256: `f3e142f05bf9f503168b256db4e05d83c373e94425e1c3147d0817fdf37f3bbb`
- Paired-residual authority SHA-256: `34b95d42f55d5be424752b73b4450d8b8d17a9a3e434659ac0b0cc9a185984be`

Verification independently hashes and reloads the existing artifact, confirms the exact
ordered predictor contract, frozen median/missing-indicator preprocessing, training
cutoff, and `contains2026SeasonOutcome=false`. The activation reload fixture is bound to
the manifest, binary, and feature-vector hashes and is reproduced on every later run
without refitting:

- Fixture SHA-256: `6ff9b65fb1963d75462a3d9e257483e9746e44bc07bf39d2d372cdb5a64de691`
- Fixture: `C:\Users\james\asp-data-staging\nfl\m1-prospective-shadow-v1\activation-fixtures\sha256\6ff9b65fb1963d75462a3d9e257483e9746e44bc07bf39d2d372cdb5a64de691\fixture.json`

Because the original two-file M1 artifact had no persisted scoring fixture, this is a
new activation verification fixture. It is not represented as historical M1 evidence.

## Point-in-time feature materialization

The registered 2026 schedule contains 272 eligible regular-season games from
2026-09-09 through 2027-01-10, including 31 January 2027 games belonging to NFL season
2026. Schedule `gametime` is interpreted as documented US Eastern time with
`America/New_York` daylight-saving rules.

Each vector:

- has all 197 predictors in the frozen order;
- uses completed prior games with strict `game_date < target game_date` semantics;
- preserves null/cold-start behavior from M1;
- binds its forecast and source cutoffs, feature values hash, source-foundation
  manifest, frozen training-foundation manifest, and model manifest;
- records that target outcomes and market fields were not read.

The frozen training authority remains pinned. Prospective feature input resolves the
latest independently verified compatible foundation/current snapshot, so completed
2026 games can update later rolling features instead of permanently using the
preseason snapshot. A historical-shadow parity check for `2025_01_ARI_NO` matched the
registered Gold row on all 197 predictors (including nulls), with zero mismatches and
without reading the game outcome.

## Forecasts and simulation

Initial activation time was `2026-08-30T00:54:52.304219Z`
(`2026-08-29 20:54:52.304219 America/New_York`). It created:

- 272 immutable `EARLY` forecasts;
- 272 immutable `CURRENT` forecasts;
- 0 `FINAL_PREGAME` forecasts, because no game was yet inside the governed window;
- 544 forecast snapshots total;
- 57 immutable per-slate-date bundles.

`FINAL_PREGAME` is permitted only in the narrow window 15–30 minutes before kickoff;
earlier refreshes remain `CURRENT`, and no final snapshot is backfilled at or after
the 15-minute cutoff. Unchanged evidence creates at most one final snapshot in that
window. An unchanged-evidence rerun at `2026-08-30T01:03:53.166652Z` reevaluated all
272 games and produced zero new forecasts and zero new bundles. It also reused the
existing stable feature evidence rather than writing new unreferenced vector objects.
A different producer commit is part of the governed CURRENT identity: it preserves the
original EARLY snapshot and creates exactly one new CURRENT version per event. The
coordinated post-commit activation run therefore binds live CURRENT forecasts to the
final implementation revision while retaining the initial snapshots as immutable
history.

The exact frozen XGBoost score estimator feeds M1's paired empirical residual
simulator with seed 731001 and 10,000 common draws per game. Outputs include coherent
home/away and tie probabilities, expected scores, joint score, margin, and total
distributions, integer and half-point spread/total projections (including push mass),
most-likely scores, intervals, and stability uncertainty. The exchange validator
recomputes these projections from the joint PMF and fails closed on disagreement.

## Exchange publication

The implementation extends the existing `aisp-daily-forecast-bundles` exchange family
with strict `ASP_SPORTS_FORECAST_EXCHANGE_V1` bundles and
`ASP_SPORTS_GAME_FORECAST_V1` child records. The historical V1 producer behavior is
unchanged. Each new bundle is canonical JSON in a SHA-256-addressed immutable object,
with an independently checked consumer fixture and validation instructions.

- Producer inventory: `C:\Users\james\asp-data-staging\nfl\m1-prospective-shadow-v1\prospective-index.json`
- Consumer locator: `C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\nfl-2026-research-shadow-index.json`
- Locator schema: `ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V2`
- Current-authority bundle count: 57 (544 records: 272 EARLY + 272 latest CURRENT)
- Current-authority list SHA-256: `7ac7fe691bdaf5022c94f01939694ef1476d169a3ecbc09fafb897af745ad809`
- Historical bundle count: 57 (the superseded CURRENT v1 remains discoverable)
- Historical list SHA-256: `ca8be97635b61f4bf21689c4956a6968f28f53bc837f25c99cdb398ee8090e4b`
- First slate bundle (2026-09-09): `c1eaa2f3d3c9734699e59def34ef8d8e0dee21e0cb1ba427c6833650381fa84f`
- Final regular-season slate bundle (2027-01-10): `11018e67797870acc3d5d9aec5d70a63d12d9c624ce084e6cf59efb7abe5289b`

The small mutable locator is navigation only. Its current and historical bundle lists
are sorted, unique, and disjoint; each list hash is
`SHA256(canonical_json_bytes(bundleSha256s))`. Current slate bundles deterministically
compose the immutable first EARLY plus the latest CURRENT and, when available, latest
valid FINAL_PREGAME record for every event. Superseded versions remain discoverable
through the historical list, and every underlying object stays immutable. The producer
verifies every named bundle before atomically replacing the locator. A consumer must
still independently hash and validate every selected bundle. This avoids unsafe
enumeration of an unrelated ACL-protected legacy object in the same established
exchange family.

## Verification and repository state

Focused command:

`python -m pytest -p no:cacheprovider tests/nfl_2026_prospective_shadow_test.py -q`

Result: **6 passed**. Coverage includes frozen artifact hashes/reload, 197/197
historical parity, cutoff and season-boundary rules, schedule population including
January 2027, immutable bundle verification, locator verification, research-only
disposition, unchanged-evidence forecast and feature-object idempotence, and the
unchanged legacy post-2024 rejection rule.

Operational command:

`python -m scripts.run_nfl_2026_prospective_shadow --producer-revision e60f5b1500e1c574e17a526a6c2e8bef047f92e2`

Initial result: 272 games, 272 feature vectors, 544 forecasts, 57 bundles, zero fits,
zero promotions, and no market-field read. Final repeat result: 272 games, zero new
forecasts, zero new bundles, and independently reproduced reload fixture.

Repository changes are limited to the producer/verifier, CLI, focused tests, and this
report. Source data, Parquet, model binaries, predictions, and API keys remain outside
Git. The preserved untracked Phase 7D3 audit report remains byte-identical at SHA-256
`72c5a70d12a61f04ffdebf2d3a5a11b17236b29abd0d9d36fd035ddd12593a6`.

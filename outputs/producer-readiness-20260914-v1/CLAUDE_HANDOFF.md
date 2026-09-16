# September 14 MLB / NFL producer handoff

Document created at **2026-09-14T15:42:17.508228+00:00**.

Operational evidence only. No new forecast, model activation, paper-experiment authorization, account, wager, scheduler or promotion is created by this document. Physical documentation publication is recorded separately in `delivery-receipt.json`; all forecast clocks below remain their original values.

Repository: `C:\Users\james\asp-model-studio`, branch `codex/mlb-starter-duration-source-intake-v1`, inspected HEAD `b6b0cee5958bee25c9977b1a6efc74502597341b`. The eight inherited tracked modifications were preserved. NBA joint-distribution results are retained; the close-score correction is deferred.

## MLB: ten checkpoints not due, ten games missing lineups, zero V18 forecasts

The existing `ASP MLB V18 Research Publisher` Windows task is enabled, Ready, and returned 0 at 15:27:27Z. It runs the pinned release `9bb1a947fc863596433fac569822ad95f2c71dac` through `.runtime/mlb-v18-unattended/deployment.json`, preserving the existing OS byte lock. Its substantive 15:22:25–15:22:28Z receipt shows all ten September 14 games at `CHECKPOINT_NOT_DUE`. A 15:37:24Z dispatcher receipt records `NOT_DUE_NO_PROVIDER_OR_MODEL_ACTIVITY`. At that snapshot its next substantive tick is 16:22:25.577031Z. The task itself wakes every five minutes; checkpoint policy determines work.

A fresh read-only persisted-input capture at **15:28:38.024665Z** confirms both confirmed ordered lineups are unavailable for every game. Timing and input readiness are separate dimensions: **10 not due; 10 lineup-blocked; 0 due and supported; 0 demonstrated overdue producer failures; 0 produced/published/import-confirmed V18 forecasts**. Historical Gen1/development forecasts in the database do not count as V18.

| Away at home | MLBAM gamePk | First pitch UTC | Original V18 cutoff UTC | Last required-input check UTC |
|---|---:|---|---|---|
| LAD at CIN | 824465 | Sep 14 22:40 | Sep 14 22:35 | 11:17:25.801620 |
| CWS at CLE | 824386 | Sep 14 22:40 | Sep 14 22:35 | 11:17:25.801620 |
| DET at TOR | 822765 | Sep 14 23:07 | Sep 14 23:02 | 12:17:25.878534 |
| BAL at NYM | 823575 | Sep 14 23:10 | Sep 14 23:05 | 12:17:25.878534 |
| ATL at CHC | 824629 | Sep 14 23:40 | Sep 14 23:35 | 13:22:24.145916 |
| NYY at MIN | 823656 | Sep 14 23:40 | Sep 14 23:35 | 13:22:24.145916 |
| SF at STL | 823006 | Sep 14 23:45 | Sep 14 23:40 | 13:22:24.145916 |
| SD at COL | 824308 | Sep 15 00:40 | Sep 15 00:35 | 14:22:24.560993 |
| SEA at LAA | 823981 | Sep 15 01:38 | Sep 15 01:33 | 14:22:24.560993 |
| MIA at AZ | 825034 | Sep 15 01:40 | Sep 15 01:35 | 14:22:24.560993 |

The governing owner must retain confirmed-input and original-clock checks. There is no justified manual forecast regeneration or early checkpoint override. This snapshot does not promise later readiness. Do not infer V18 readiness from the unrelated Gen1 completeness number.

An accounting-only package already exists at:

`C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\944eaa131c8a19b644ae81ac7d5e0c6e07679f9022911a3136339323e99d51a4\exchange-package.json`

Package content identity `944eaa131c8a19b644ae81ac7d5e0c6e07679f9022911a3136339323e99d51a4`; owner-reported physical manifest SHA-256 `7cf247a7b4943d51b2cefcd0b7da5dbdfdce05712db47dc481d1cc76c3b92021`, 4,341 bytes. It is **non-importable, zero forecasts**. Do not run the forecast importer on it.

First owner publication is recorded within **03:07:25.323229–03:07:31.993700Z**, in local immutable tick `outputs/mlb-v18-unattended-v1/objects/sha256/0c3bad52505584d58c23f7111b09ecb943509098b9772d2ab87a111c91c52c2c/tick.json` (physical SHA matches directory, 64,628 bytes; published=true/reused=false). The 15:22 owner reused it. Exact external publication syscall time is not retained; these are receipt bounds.

**Existing qualification remains:** this session receives Windows AccessDenied on that exact exchange directory/manifest, including an elevated read. Local handoff and receipt bytes verify, and the Windows owner reports successful package verification/reuse; external bytes and consumer readability were not independently verified here. The same qualification was recorded in `docs/MLB_V18_CONDITIONAL_CHAMPION_HANDOFF_V1.md:50`. No root cause or approved owner-side ACL repair was established by the bounded review. No ACL, owner or lock was changed. If Claude's consumer gets `PACKAGE_NOT_READABLE`, retain that disposition separately from missing confirmed lineups. Do not treat zero forecasts as evidence of a model failure.

## NFL: DEN away at KC home, original CURRENT v7 remains selected

Event `2026_01_DEN_KC`, ESPN `401872931`, kickoff **2026-09-15 00:15Z / September 14 20:15 EDT**. The [official Chiefs schedule](https://www.chiefs.com/game-day/2026/reg-week1/broncos-at-chiefs/) confirms Denver at Kansas City, Monday 7:15 PM CDT. Existing FINAL_PREGAME eligibility is **23:45Z through 00:00Z** (30–15 minutes before kickoff); no FINAL_PREGAME is due now.

Exact forecast ID:

`asp-sports-game-forecast:sha256:2d9d0197aa7ef02c15a110cf7ce5f36ad2a87d2f1c2a92601d9989d5c487aec9`

| Quantity | Unchanged CURRENT v7 |
|---|---:|
| DEN win probability | 0.5753 |
| KC win probability | 0.3817 |
| Equal final-score probability | 0.0430 |
| Expected DEN / KC points | 20.3887 / 18.2688 |
| Expected home margin / total | -2.1199 / 38.6575 |
| Draw count / seed | 10,000 / 731001 |

All probabilities are fractions. Original forecast availableAt: `2026-09-08T09:30:50.543556Z`; forecast cutoff: `2026-09-08T09:30:22.560047Z`; source and schedule cutoff: `2026-08-29T14:07:34.968754Z`; original bundle generation: `2026-09-08T09:31:04.260289Z`. This handoff does not refresh any of those clocks.

The repaired current Foundation, published `2026-09-14T09:31:35.465218Z`, contains **15 completed 2026 games through September 13**. Current nflverse PBP and team/player-stat release assets were successfully captured at 09:30Z. DEN and KC each have **zero own completed 2026 regular-season games**, so their feature inputs have not changed. DEN's latest prior game is `2025_21_NE_DEN` (January 25); KC's is `2025_18_KC_LV` (January 4). All **197** numerical inputs match the original and post-repair vector exactly: **0 changes**, semantic values SHA `be915b738d3851bf043f3524d27dbc8da8b9bd2684a34be553d14ab16ecf03ff`.

Coverage is **153 non-null / 44 missing**; missing values are the 22 season-to-date metrics for each team. Existing fitted median imputation applies, with readiness 78 against threshold 50. Readiness is not complete raw inputs or validated predictive superiority. Named QB participation, injuries, lineups and explicit overtime dynamics are absent from active M1 mechanics.

The exact retained September 13 event plan says `REUSE_UNCHANGED_FORECAST`, publication complete `2026-09-13T19:36:26.145618Z`; the September 14 current index updated at `09:33:08.398782Z` still selects v7 and binds the new Foundation. The bounded inspection did not locate a separate September 14 activation event-plan receipt. This qualification does not justify re-running unchanged inputs.

**Tie semantics:** 430 of the 10,000 retained paired final scores are equal; 5,753 favor DEN and 3,817 favor KC. There is no generic “other” category. This is modeled final-score equality after paired-residual sampling/rounding, not regulation ties or overtime occurrence. There is no explicit overtime resolution stage, and the 4.30% has not been independently validated as calibrated real NFL final-tie probability. Preserve three-way semantics; do not use MLB's zero-tie binary conversion or silently renormalize these probabilities for a market.

Engine: `NFL_M1_XGBOOST` / `NFL_M1_2026_RESEARCH_SHADOW_V1`, candidate `nfl-m1-xgboost-fixed-research-challenger-2026-shadow`. This is separate from the NFL play-level research simulator. Frozen producer revision `5d114f5502d875b012dc75672db975166e09e561`; model binary SHA `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd`; model manifest SHA `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9`; feature contract SHA `ef5c4f9ce8c3dd04a473e7ecb2ea3a255154f65a1bb3fda9d2ebc19bf1cb8f4d`. Training is 7,276 games, 1999–2025 seasons, cutoff February 8, 2026; fitted preprocessing unchanged; calibration NONE. Simulator `NFL_M1_EMPIRICAL_PAIRED_RESIDUAL` / `NFL_M1_EMPIRICAL_CORRELATED_RESIDUAL_V1`.

Use the existing verified bundle, preserving original child identity:

`C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\sha256\d82406ea3d6c4e8cbe9eeaa773d0484d98b7d40f755d630a605c06ed49aec707\bundle.json`

Physical SHA equals directory digest, **128,703 bytes**; the CURRENT v7 child is identical to the original. Bundle schema `ASP_SPORTS_FORECAST_EXCHANGE_V1`, child `ASP_SPORTS_GAME_FORECAST_V1`. Existing locator `nfl-2026-research-shadow-index.json` is mutable; its inspected physical digest is recorded in `nfl-readiness.json`. Validate immutable bundle and child using the existing adapter; do not import this Markdown document as a forecast. No new consumer acknowledgement was established by this producer inspection.

## Paper-research interface and exact evidence

Existing V1 permits importing/displaying unpromoted research forecasts. It requires RESEARCH_SHADOW, NOT_PROMOTED, NOT_EXECUTABLE, researchShadowOnly=true; executionAllowed/modelPromotionAllowed/parlaysAllowed remain false. No champion prerequisite was demonstrated in the inspected import/display paths. An old source cutoff or feature-readiness pass grants no paper or funded authority.

The precise missing wire capability is an explicit binding to **one separately authorized paper experiment** with its cohort, original deadlines and stopping rules. The smallest proposed extension is `ASP_NFL_PAPER_RESEARCH_ELIGIBILITY_V1`, a specifically registered `PAPER_RESEARCH_ELIGIBILITY` kind in the existing research-supplement mechanism. Bind experiment ID and authorization-receipt hash; cohort identity; event/forecast/bundle/model/feature identities; technical eligibility/reasons; and original clocks plus actual evidence/publication clocks. Preserve all execution/promotion authority false. This is a **proposal only**, not a granted eligibility record. Strict V1 fields cannot be bypassed by adding an ad hoc flag or renaming an existing supplement kind. Claude owns consumer implementation and verification of separately authorized paper rules and compatible market settlement.

Exact local evidence lives at `C:\Users\james\asp-model-studio\outputs\producer-readiness-20260914-v1\`: `mlb-readiness.json` (canonical mappings, checkpoint rows, source/receipt references), `nfl-readiness.json` (physical bindings, source coverage, frozen configuration, vector equality and draw accounting), `paper-research-contract.json` (exact source-code/schema references), `mlb-first-publication.json` and `mlb-owner-snapshot.json`. `evidence-index.json` supplies physical SHA-256 and byte counts. Reproduce byte checks with `.venv\Scripts\python.exe scripts\verify_producer_readiness_20260914.py`. Checks do not run a producer or read outcomes.

This run made zero manual provider requests, model executions, fitted-model changes, AISP database writes, scheduler/lock changes, or sealed-outcome reads. MLB input collection and ordinary publication continue through their existing owners; NFL's existing source sync and publisher remain operating. No forecast was backdated, overwritten, regenerated or restamped.

Evidence index physical SHA-256: `91064b08b8a45780f649bac9618dee389d454554d25a70c7a5e3c818e373a8c1`, 1,742 bytes. Its actual creation clock is separate from all forecast clocks.

# ASP Model Studio — 2025-Trained to 2026 Daily Walk-Forward Experiment

Status: **BLOCKED BEFORE MODEL FIT**

## Research question

> If ASP had been trained using all authorized data through the end of 2025, how well would it have predicted 2026 MLB games day by day?

The current local authorities cannot answer this question. They contain reusable 2025 base-feature evidence, but no authorized 2026 evaluation population or game-truth authority. Fitting models without a valid evaluation population would consume time without producing the requested evidence, while using the small unregistered AISP operational slice would falsely represent an incomplete convenience sample as a governed season-to-date walk-forward study.

## Starting state

- Starting branch: `codex/game-simulation-market-mvp`
- Starting HEAD: `4fb1aaf182e525ea7f617e4ac839fa5f1901606b`
- Experiment branch: `codex/2025-to-2026-walk-forward`
- `main`: `924db29511f93909f9d785855bfa056775443690` (unchanged)
- Existing Phase 7B1–7B6 work was preserved.
- The untracked Phase 7D3 audit report was not modified.
- No push or remote mutation was performed.

## Exact data inventory

| Authority | Identity | Available coverage | Result for this experiment |
|---|---|---|---|
| Advanced Bronze | Manifest SHA-256 `fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a` | 2,233 partitions: 25 year-null authority records and 368 partitions for each year 2019–2024; zero 2025/2026 partitions | Cannot produce 2025 advanced Silver or any 2026 evaluation rows |
| Current Silver | `C:\Users\james\asp-data-staging\mlb-silver-v1` | 13 current logical objects; current Statcast pitch and PA facts cover 2019–2024 only | No reusable 2025/2026 advanced Silver |
| Gold V1 | `gold-table:gold_mlb_pa_v1:sha256:56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0` | 716,813 PAs: 178,522 / 175,508 / 182,072 / 180,711 in 2021–2024 | Existing 48-feature Direct Gold/E10 source stops at 2024 |
| Governed Gen3 sealed 2025 | Logical SHA-256 `4c33b9e57a6b8ffc00cd3ac803c31b31b75e0cf38cde6fbcd17027f669a06d20` | 182,926 PAs, 2,430 games, 2025-03-18 through 2025-09-28 | Reusable for Base-22 target/history under the new split, but not a substitute for the missing 26 advanced Gold features |
| Authorized 2026 Model Studio data | None | Zero partitions, zero PAs, zero games, no game-truth authority | Hard blocker |

The active immutable FD1 package is valid and contains 3,738,096 rows across 2021–2025. Its 2025 season has 182,926 PAs and 2,430 games, but it does not extend the verified Phase 7B advanced Silver/Gold contract. The current Gold V1 manifest explicitly declares seasons `[2021, 2022, 2023, 2024]`.

An exact filename and authority scan found no 2026 partition in:

- `C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1`
- `C:\Users\james\asp-data-staging\mlb-silver-v1`
- `C:\Users\james\asp-data-staging\mlb-gold-v1`
- `C:\Users\james\asp-model-exchange\datasets\mlb-fd1`
- `C:\Users\james\asp-model-studio\.runtime\asp-model-studio\sports-modeling`

Read-only inspection found a small AISP operational raw slice captured on August 13, 14, and 27. Its latest deduplicated schedule snapshots contain 12 final games for 2026-08-26. Those bytes are not registered Model Studio Bronze, Silver, Gold, or game-truth authority; they do not provide full chronological 2026 PA features/outcomes; and they were not used. AI Sports Predictor was not modified.

Latest fully completed **authorized** 2026 date: **none**.

## Why execution stopped before fitting

The requested comparison requires the same eligible 2026 games for Base, Direct Gold, and E10. For every date D it also requires:

- 2026 PA identities and features for forecast construction;
- completed D-1 outcomes for chronological recent-state updates;
- full-game and first-five truth;
- pregame-known lineup/starter inputs or explicit readiness failures;
- exact game identities for paired bootstrap intervals.

All five are absent from the authorized 2026 authorities. Consequently:

- no 2026 label was opened for tuning or fitting;
- no model, preprocessor, ensemble, or calibration object was fit;
- no game simulation began;
- no engine was selected or promoted;
- no empty prediction file or misleading zero-row chart was created.

The existing implementation seams are reusable once data exists: Base-22 and Direct-48 fitting from `recent_data_walk_forward`, chronological state from `walk_forward_state`, the fixed E10 stacker from `walk_forward_ensemble`, and the Phase 7B6 pregame simulator and probability-provider path. The legacy oracle participant path must not be used because actual substitutions/reliever choices would leak future game information.

## Engine leaderboard

| Engine | Games | Log loss | Brier | Accuracy | Calibration | Score MAE | Total MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| AISP/Base reference | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| Direct Gold | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| E10 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |

No paired confidence interval, monthly table, rolling 14/30-day table, calibration curve, cumulative loss-difference chart, monthly chart, recent-state coverage chart, or most-recent-14-day statistic exists because there are no eligible evaluation games.

## Historical odds feasibility

**HISTORICAL_ODDS_REQUIRED_FOR_BANKROLL_REPLAY**

No governed historical sportsbook prices are present, so bankroll, ROI, profit, CLV, and bet recommendations were not calculated.

The current AISP configuration has a nonempty provider credential, but credential presence does not prove validity or historical entitlement. Its implemented adapter calls only the current MLB odds endpoint; it does not implement the historical endpoint. No provider request was made and zero credits were consumed.

The provider's official documentation states that historical snapshots are available only on paid usage plans and that historical odds cost `10 × regions × markets` credits. With the locally configured one region and three markets, one nonempty historical snapshot could cost 30 credits. The documentation reports historical featured-market snapshots from June 2020, at five-minute intervals from September 2022. Therefore 2026 MLB historical quotes appear technically obtainable in principle, but access must first be confirmed and a bounded historical adapter/storage policy must be implemented. Sources: [The Odds API V4 documentation](https://the-odds-api.com/liveapi/guides/v4/) and [historical odds documentation](https://the-odds-api.com/historical-odds-data/).

## Exact unblock condition

Provide or register, through the existing Model Studio pipelines:

1. authorized 2025 advanced Silver inputs sufficient to materialize the existing 48-feature Gold contract without redesign;
2. authorized 2026 PA/Gold evaluation rows and completed game truth from Opening Day through an explicit fully completed cutoff;
3. pregame-known starter/lineup evidence with honest readiness flags;
4. exact 2026 game identities compatible with the existing simulator.

Once those inputs exist, the bounded implementation is one experiment orchestrator: create development-only chronological OOF predictions through 2025, freeze Base/Direct/E10 before 2026, score every game on D before advancing any D outcomes, simulate all three engines with common random numbers, and persist request-addressed artifacts outside Git. No new model family or governance hierarchy is needed.

## Final decision

**E. EXPERIMENT_BLOCKED**

- 2026 games evaluated: `0`
- Best engine: `N/A`
- Best log loss: `N/A`
- Best accuracy: `N/A`
- Best Brier: `N/A`
- 95% CI versus Direct Gold: `N/A`
- Most recent 14-day performance: `N/A`
- Bankroll replay currently possible: `No`
- Exact blocker: zero authorized 2026 evaluation/game-truth rows, plus no 2025 advanced Silver/48-feature Gold extension for Direct Gold and E10

AISP_2025_TO_2026_WALK_FORWARD_BLOCKED

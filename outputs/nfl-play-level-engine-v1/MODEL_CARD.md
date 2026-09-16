# NFL independent play-level research engine V1

Model: `NFL_DEVELOPMENT_HIERARCHICAL_PLAY_V1`, version `1.0.0`.

Status: `RESEARCH_SHADOW`, `NOT_PROMOTED`; wagering and AISP execution authority are both false. This track neither explains nor replaces M1 or the independent drive engine.

## Evidence and fitted artifact

The registered, physically separated nflverse 2018–2024 play-by-play partitions contain 340,587 rows across 1,942 games. Normalization retains 287,007 supported joint play outcomes. Source files, exclusion counts, licenses, original retrieval timestamps and checksums are retained in the fit receipts. No 2025-season partition was opened.

The final model uses all supported Development evidence through the **2024 season**, whose last game date is **2025-02-09**. That date is not 2025-season evidence. The exact source objects were locally retrieved on **2026-08-29 at 13:34:33.063899 UTC**. Neither retrieval nor publication implies current roster evidence.

Final fitted artifact:

- Path: `fits/4680f832fb9453878c2c0ec64685675425824d3f1d4bc3d859c14d0e9ac0529b/model.joblib`
- SHA-256: `055c67a5d090c8de5d6fcf4338185484a1cd721988f24e4d37612a5a09ed921e`
- Bytes: 131,976,505

## Conditional model and legal state engine

Recency-weighted categorical probabilities and joint empirical donor distributions condition on phase, down/distance, ten-yard field bands, late-half clock/score bands, and offensive/defensive team units. One donor supplies its joint yards, elapsed clock, supported air yards, turnover/recovery/return evidence and kick or try result; these outcomes are not drawn independently.

The hierarchy's prior strengths are 300 plays for down/distance, 120 for field position and 80 for clock/score. Team-unit mixture mass is `0.5 × n/(n+400)`, normalized with the context/league mixture. These are **fixed predeclared assumptions**, not empirically estimated optimal hyperparameters. There was no tuning or calibration fit.

Historical exposure decays by 0.65 per season. For 2026, team-unit exposure based on 2024 evidence receives an additional `0.65² = 0.4225` discount. Unknown teams use the fitted league prior. No generic frozen median is used. Current rosters, quarterbacks, injuries, weather, markets and explicit venue/home advantage are excluded, not imputed.

Try choice excludes its action-dependent 15-/2-yard starting spot. The legal state engine derives conversions, scoring, possession changes, downs and clock progression from the sampled outcome and current simulated state. It does not copy donor-game scores. Regulation, halftime and regular-season overtime are explicit transitions. Unsupported states fail rather than silently acquiring an arbitrary field position.

## Chronological Development validation

The validation fit contains 245,403 plays through 2023, with an exclusive cutoff of 2024-09-01. The held-out 2024 population contains 41,604 supported plays. Full-game validation uses the first 32 regular-season 2024 games by date and event ID, with 200 simulations per game and unchanged through-2023 priors. Actual final scores enter metric calculation only.

| Measure | Result |
|---|---:|
| Conditional play-type log loss | 1.182461 |
| Phase-only baseline log loss | 1.516647 |
| First-down rate, observed / sampled | 0.292992 / 0.292271 |
| Scrimmage turnover rate, observed / sampled | 0.017298 / 0.017222 |
| Scrimmage sack rate, observed / sampled | 0.039210 / 0.037462 |
| Scrimmage yards, observed / sampled mean | 5.520 / 5.459 |
| Supplied elapsed clock, observed / sampled mean | 23.909 / 24.407 seconds |
| Full-game home/away/tie log loss | 0.708462 |
| Full-game multiclass Brier sum | 0.504947 |
| Margin / total mean absolute error | 10.0533 / 9.9005 points |
| Simulated / observed mean total | 39.3017 / 42.7188 points |
| Simulated / observed drives per game | 21.0025 / 21.4688 |
| Simulated / observed scoreboard points per drive | 1.8713 / 1.9898 |
| Impossible states / score / continuity failures | 0 / 0 / 0 across 6,400 simulations |
| Frozen artifact reload, complete sequence mismatch | 0 |

The whole-game fixture underpredicts mean total by 3.417 points. Its probabilities are raw and uncalibrated. A small retrospective fixture does not establish current pregame calibration, predictive superiority or a wagering edge. Later archive retrieval is not proof of a historically archived pre-kickoff source release.

## Scenarios and geometry

The seven single-factor sensitivities are BASE; clock-duration multipliers 0.90 and 1.10; pass-intent odds multipliers 1.25 and 0.80 relative to other intents; fourth-down go-odds multiplier 1.50; and turnover-donor odds multiplier 1.25. Elevated turnover changes turnover **risk**, not only variance. These are not coaching predictions or causal effects. Population summaries, scenario deltas and independent M1 comparisons are in each supplement and the final verification receipt.

Longitudinal geometry uses modeled play endpoints and supported air-yard targets. Lateral curves are explicitly schematic, not fitted routes or tracking. A completed pass can have separate air and net-YAC segments. Interception/recovery and return coordinates remain in the pre-play possession frame. A sack/lost-fumble may have separate net-sack and recovery/return segments: no unknown loose-ball bridge is invented. Player identities, physical speed, hang time and measured ball tracking are unavailable.

## Limitations and execution lineage

- Only 16 donors explicitly identify quarterback sneaks; short runs are not relabeled as sneaks.
- Elapsed clock to the next live play includes runoff. There is no timeout-strategy model; missing and period-ending clock intervals are excluded.
- Most penalties, laterals, multiple-fumble plays, defensive tries and onside/muffed/blocked kicks are unsupported. Safety free kicks use an explicitly labeled ordinary-kick prior; detailed landing-zone exceptions and postseason overtime are not modeled.
- Overtime uses the regulation-trained conditional play law under explicit regular-season overtime rules; an overtime-specific tactical policy was not fitted.
- Touchdowns, goals and touchbacks use declared rule-era administration, not invented physical measurements.
- One completed preliminary fit was preserved and superseded after identifying 119 unsupported compound interception/incomplete-pass fumble records. Its component results are not final-design validation. Additional historical draws before its interruption were not fully counted and are not inferred.
- The corrected numerical design used two completed fits. Total historical fit starts/completions, including the preserved preliminary artifact, are **three/three**.
- The later sack/fumble renderer correction changed no donor, model, state transition or numerical validation. Its publication successor explicitly references checksum-verified original validation; it performed zero new fits or statistical evaluations.

Original declarations, fitted objects, validation and interruption receipts remain intact. All completed publications are discoverable through this directory's `CURRENT.json`; the immutable handoff lists the external artifacts and their manifests. No AISP write, provider call, sealed-OOT read, official decision, position or policy change belongs to this run.

## Completed Week 1 publication

All 16 events have seven populations of 1,000 simulations each: **112,000 population simulations**, **672 distinct-within-population complete representatives** and **108,466 representative play events**. There are no skips. Generation took 3,727.406024 seconds (62.12 minutes). Every population was generated by actual play-state transitions; only the six selected full paths per population are retained for animation, while all 1,000 finals and aggregate diagnostics are retained.

The supported populations contain 17,497,323 play/period events, including 404 explicitly classified simulated sneaks. All population distributions reconcile exactly. The rerun reused all 112 artifact/manifest references with zero new simulation starts and zero representative replays; a new publication receipt, not a numerical forecast version, was created.

| Sensitivity | Predeclared parameter change | Mean total | Change from BASE | Turnovers/game |
|---|---|---:|---:|---:|
| BASE | None | 40.7984 | 0 | 2.1518 |
| Faster pace | Clock duration ×0.90 | 45.5501 | +4.7518 | 2.4020 |
| Slower pace | Clock duration ×1.10 | 36.9096 | −3.8888 | 1.9591 |
| Pass-heavy | Pass-intent odds ×1.25 | 42.5034 | +1.7050 | 2.3311 |
| Run-heavy | Pass-intent odds ×0.80 | 38.9942 | −1.8042 | 2.0229 |
| Aggressive fourth | Fourth-down go odds ×1.50 | 41.1991 | +0.4007 | 2.1616 |
| Elevated turnover | Turnover-donor odds ×1.25 | 40.7912 | −0.0072 | 2.6941 |

These are equal-weight means across the 16 event populations, not causal effects or selected decision policies. BASE mean total is **40.7984 versus M1's 44.0436**. BASE mean home/away/tie probabilities are **0.492313 / 0.498000 / 0.009688**, versus M1's **0.550325 / 0.416588 / 0.033088**. Neither engine was adjusted to force agreement.

Completed canonical events: `2026_01_NE_SEA`, `2026_01_SF_LA`, `2026_01_ATL_PIT`, `2026_01_BAL_IND`, `2026_01_BUF_HOU`, `2026_01_CHI_CAR`, `2026_01_CLE_JAX`, `2026_01_NO_DET`, `2026_01_NYJ_TEN`, `2026_01_TB_CIN`, `2026_01_ARI_LAC`, `2026_01_GB_MIN`, `2026_01_MIA_LV`, `2026_01_WAS_PHI`, `2026_01_DAL_NYG`, `2026_01_DEN_KC`.

Thirty distinct focused tests passed across the scoped runs; the changed renderer's six tests were rerun successfully. Actual publication verification additionally checked all 112 object manifests, their distributions and representative selection, pregame timestamps, source preservation and idempotency. No full repository suite was run.

## Import handoff

- Contract: `C:\Users\james\asp-model-exchange\contracts\NFL_LABS_PLAY_LEVEL_CONTRACT_V1.json`
- Contract SHA-256: `7563c2f36652d76f5ee2bbf60a90f396b50cb9007603c75ed41a508b9b215649` (15,867 bytes)
- Current index: `C:\Users\james\asp-model-exchange\nfl-labs-play-level-supplements\current.json`
- Immutable handoff: `C:\Users\james\asp-model-studio\outputs\nfl-play-level-engine-v1\sha256\654b4a8b3850a040d237f66309e247a89de2fc276477995306c886a49142f8c0\handoff.json`
- Handoff SHA-256: `654b4a8b3850a040d237f66309e247a89de2fc276477995306c886a49142f8c0` (151,041 bytes)
- Final verification: `C:\Users\james\asp-model-studio\outputs\nfl-play-level-engine-v1\verification\sha256\55a83fcb2f83ff8043bc8dcaf0a7b7784d1097ba35074946b291975f73681b71\verification.json`
- Final verification SHA-256: `55a83fcb2f83ff8043bc8dcaf0a7b7784d1097ba35074946b291975f73681b71`

Exact Claude instruction:

> Import all 112 precomputed supplements referenced by `C:\Users\james\asp-model-exchange\nfl-labs-play-level-supplements\current.json` using `C:\Users\james\asp-model-exchange\contracts\NFL_LABS_PLAY_LEVEL_CONTRACT_V1.json`; verify the immutable handoff SHA-256 `654b4a8b3850a040d237f66309e247a89de2fc276477995306c886a49142f8c0` and every artifact/manifest checksum and byte count. Keep `NFL_DEVELOPMENT_HIERARCHICAL_PLAY_V1` separate from M1 and the drive engine, consume the complete representative plays and modeled/schematic geometry as supplied, execute no model in AISP, and preserve research-shadow/no-wagering authority and all existing forecasts and positions.

Verdict: `NFL_PLAY_LEVEL_SIMULATION_EVIDENCE_READY`.

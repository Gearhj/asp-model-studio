# NFL, CFB and NBA feature-readiness study design

Status: frozen before the new feature-block calculations.

This study extends the governed `multisport-feature-engineering-audit-v1` evidence. It does not create a new holdout, promote a model, or certify historical source publication times. Every assessed row is previously inspected reconstructed historical evidence acquired later. No row from calendar year 2026 is eligible.

## Bound population

The only numerical inputs are the three allowlisted projected Parquet artifacts under `C:\Users\james\asp-model-studio\outputs\multisport-feature-engineering-audit-v1\permitted-input-projections`. Their physical SHA-256 values are recorded by the executable design receipt before any target column is loaded. The script rejects a different file, a season beyond the bound maximum, a game date on or after 2026-01-01 UTC, duplicate game identity, or a feature-source date on or after kickoff where such lineage is retained.

Chronological roles are retained from the earlier audit:

| Sport | Development | Reused later evidence |
|---|---|---|
| NFL | 2022 | 2023-2024 |
| CFB | 2021-2022 | 2023-2024 |
| NBA | 2020-21 through 2022-23 (audit seasons 2021-2023) | 2023-24 and 2024-25 (audit seasons 2024-2025) |

Each assessment season is predicted from strictly earlier seasons. Preprocessing, imputers, scaling, encoders, opponent adjustments, and shrinkage statistics are fit inside that origin. Calendar-week blocks are the uncertainty unit. Reused later evidence is diagnostic and cannot be called untouched OOT.

## Frozen candidate blocks

The screen is limited to the current supported baseline plus at most four additive blocks. Unsupported blocks are reported as blocked rather than synthesized.

* **NFL:** current fixed-recipe feature set; missingness indicators; support-aware cold-start shrinkage; fold-local opponent-adjusted pass/rush EPA contrasts; the combined eligible blocks. Opponent adjustment uses only prior training games and the target row's already pregame rolling EPA inputs. It never uses the target score.
* **CFB:** current Ridge alpha100 feature set; missingness indicators; support-aware cold-start shrinkage; fold-local opponent/schedule strength adjustment of prior scoring and yardage features; the combined eligible blocks. Conference priors require a governed conference identity column; absent that column, the conference block fails closed.
* **NBA:** current corrected Ridge alpha100 point feature set; missingness indicators; support-aware cold-start transforms; schedule-density/rest interactions already derivable from retained pregame features; the combined eligible blocks. Possession, shooting, rebounding, turnover, injury, lineup, and player-strength blocks remain unavailable in this population.

No broad hyperparameter search is permitted. Ridge uses alpha 100. The NFL estimator uses the repository's frozen M1 research-clone recipe and seed. Additive blocks may change the feature matrix, but model families and estimator settings remain fixed.

## Metrics and gates

Primary point metrics are mean score MAE, margin MAE, and total MAE. Winner probability metrics are reported only for an existing supported probability channel: NFL's native research-clone probability, CFB's previously fit Development calibrator on reused later evidence, and NBA's separately estimated Elo probability. NBA Elo cannot establish a point-block probability gain.

Reported probability diagnostics are log loss, Brier score, AUC, accuracy, calibration bias, and reliability bins. NFL final ties are retained in descriptive counts and excluded from the explicitly labelled binary home-win diagnostics. No MLB zero-tie convention is applied.

A block is a research priority only when it:

1. improves the predeclared primary metric on pooled reused evidence;
2. has a paired 95% calendar-week block-bootstrap interval excluding zero for at least one primary metric without material degradation in the other two (degradation greater than 0.15 points); and
3. does not reverse to material harm in either reused assessment season.

Development evidence is used to check implementation and freeze transformations. Later evidence is reused once for the bounded comparison. Failure to pass is informative and does not trigger another search.

## Missingness and cold-start rules

Every field is assigned one of: structural, source-era, not-yet-observed, identity/unmatched, or anomalous. Imputation is hierarchical and fold-local: team-season prior where available, then prior-season team value, then training-league median. Every imputation path emits a missingness and support indicator. Zero is never used as a generic missing value.

Cold start is defined before calculation as fewer than five current-season games for either team. A team's current estimate is shrunk toward its prior-season or training-league baseline with weight `n / (n + 5)`. Existing model features are preserved; the screen adds explicit support-aware contrasts and does not overwrite retained inputs.

## Injury and availability boundary

No retained population contains certified point-in-time injury participation evidence. The study therefore produces a source-readiness matrix and proposed contract only. It will not impute player absences from postgame participation, current rosters, or result data.

## Leakage and access boundary

Target scores are loaded only after this design is frozen and solely for the declared calculations. Feature construction excludes the target row and all later games. No sealed evidence, Final OOT payload, 2026 outcome field, sportsbook price, provider request, production artifact mutation, AISP write, or exchange write is permitted. The earlier `ACCESS_EXCEPTION.json` remains part of the qualification: a rejected discovery snapshot exposed raw 2026 NFL result fields, but those fields are not inputs to this study.

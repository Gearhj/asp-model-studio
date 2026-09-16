# NFL drive competing-risks survival challenger V1

**RETAIN_EXISTING_PLAY_ENGINE**

One frozen L2 multinomial hazard candidate; no operational model change. Historical archives acquired August 29, 2026 qualify these as reconstructed research, not certified pregame vintages. 2025 remains sealed and 2026 outcomes were not used.

The current-decision hazard scores improve, but this does not establish stable full-game improvement. Failed admission checks: energyUpperBound, totalGuardrail, bothLaterSeasons. The primary 2024 energy upper bound is +0.2066 against the frozen +0.2000 limit; total CRPS changes +0.1496 against the +0.1000 guardrail.

Red-zone and two-minute conditional hazard scores improve in the declared later cells. Backed-up drives have no supported gain. Remaining-drive length CRPS worsens slightly in both later seasons, and 2024 cumulative-incidence Brier also worsens slightly. Improved next-decision classification is insufficient to advance this integrated component.

## Matched full-game assessment

Candidate minus baseline; negative proper-score differences are better. 95% intervals resample football weeks, not plays or draws. 200 paired-seed simulations per configuration per target; stochastic paths can diverge.

| Role | Games | Baseline energy | Candidate energy | Energy change [95% interval] | Winner LL change | Margin CRPS change | Total CRPS change | Runtime ratio |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| development | 36 | 8.6751 | 8.6934 | +0.0183 [-0.2367, +0.2822] | -0.0103 | +0.0679 | -0.0338 | 2.05x |
| reused2023 | 36 | 8.4513 | 8.6472 | +0.1959 [+0.0163, +0.3820] | +0.0023 | +0.0979 | +0.2114 | 1.86x |
| reusedValidation2024 | 36 | 10.4353 | 10.3991 | -0.0362 [-0.2787, +0.2066] | -0.0429 | -0.2754 | +0.1496 | 1.44x |

## Drive predictions

| Role | Supported recorded states | Baseline / integrated hazard stabilized NLL | Baseline / candidate Brier sum | Baseline / candidate drive-length CRPS |
|---|---:|---:|---:|---:|
| development | 3129 | 0.3643 / 0.3507 | 0.1659 / 0.1562 | 1.4296 / 1.3968 |
| reused2023 | 3145 | 0.3477 / 0.3366 | 0.1539 / 0.1464 | 1.3701 / 1.3782 |
| reusedValidation2024 | 3006 | 0.3544 / 0.3425 | 0.1584 / 0.1505 | 1.3546 / 1.3630 |

### Reused 2024 current-decision causes

Rates use supported recorded decision states as the denominator, not whole drives. Brier changes are descriptive contributions to the multiclass score.

| Cause | Observed rate | Baseline rate | Candidate rate | Candidate minus baseline Brier |
|---|---:|---:|---:|---:|
| CONTINUE | 0.8370 | 0.8414 | 0.8467 | -0.00305 |
| TOUCHDOWN | 0.0373 | 0.0254 | 0.0255 | -0.00034 |
| FIELD_GOAL_MADE | 0.0226 | 0.0208 | 0.0212 | -0.00023 |
| FIELD_GOAL_MISSED_OR_BLOCKED | 0.0037 | 0.0028 | 0.0027 | -0.00002 |
| PUNT | 0.0532 | 0.0528 | 0.0541 | -0.00067 |
| OFFENSIVE_TURNOVER | 0.0183 | 0.0158 | 0.0132 | -0.00002 |
| TURNOVER_ON_DOWNS | 0.0096 | 0.0101 | 0.0095 | -0.00028 |
| SAFETY | 0.0007 | 0.0005 | 0.0004 | +0.00001 |
| END_OF_HALF_OR_GAME | 0.0176 | 0.0305 | 0.0268 | -0.00324 |

### Predeclared situation diagnostics, reused 2023/2024

Overlapping cells; exploratory intervals are unadjusted. Fewer than 20 represented games is insufficient for interpretation.

| Situation | Games | Integrated hazard NLL change [95% interval] | Interpretation support |
|---|---:|---|---|
| red_zone | 72 | -0.0265 [-0.0358, -0.0184] | Supported exploratory cell |
| opponent_territory | 56 | -0.0080 [-0.0162, +0.0008] | Supported exploratory cell |
| backed_up | 43 | +0.0014 [-0.0094, +0.0149] | Supported exploratory cell |
| two_minute | 70 | -0.0461 [-0.0606, -0.0327] | Supported exploratory cell |
| fourth_quarter | 72 | -0.0106 [-0.0148, -0.0063] | Supported exploratory cell |
| leading | 72 | -0.0075 [-0.0125, -0.0025] | Supported exploratory cell |
| trailing | 72 | -0.0149 [-0.0209, -0.0097] | Supported exploratory cell |
| short_yardage | 72 | -0.0259 [-0.0341, -0.0180] | Supported exploratory cell |
| home | 72 | -0.0108 [-0.0143, -0.0077] | Supported exploratory cell |
| away | 72 | -0.0121 [-0.0163, -0.0082] | Supported exploratory cell |
| early_season | 12 | -0.0154 [-0.0197, -0.0107] | Insufficient |
| cold_start | 0 | Unavailable | Insufficient |
| low_total_games | 15 | -0.0092 [-0.0154, -0.0045] | Insufficient |
| high_total_games | 11 | -0.0094 [-0.0146, -0.0047] | Insufficient |
| overtime | 6 | +0.0000 [+0.0000, +0.0000] | Insufficient |

Conditional probabilities use a fixed 128-proposal estimate. Primary conditional NLL applies the same Jeffreys 0.5-per-cell score stabilization to both arms; raw zero-count and classifier scores are retained separately. The integrated law projects hazards to a finite feasible proposal set; it is not the raw classifier law.

The complete JSON retains terminal-cause Brier/reliability, cumulative incidence at 1/3/5/10/20 decisions, remaining length/time, offensive points before tries, game AUC/accuracy, scoring biases, all 50/80/90 intervals, tails and situation diagnostics. Sparse cells are marked.

## Admission and limitations

Frozen gate results: `{"adequateDriveGames": true, "adequateGames": true, "bothLaterSeasons": false, "calibrationGuardrail": true, "driveNll": true, "energyImproves": true, "energyUpperBound": false, "exactMassLegalityFallback": true, "marginGuardrail": true, "runtime": true, "totalGuardrail": false, "winnerGuardrail": true}`.

Drive exclusions are whole-drive exclusions. No-play penalties are separate decision transitions; timeouts/administrative markers are not snaps; period endings are observed terminals, not ordinary censoring. Exclusion-related selection bias remains attached to conditional results. Full-game evaluations include all declared supported identities, using pregame team identities/season and earlier-season priors only.

Postseason is excluded from full-game comparison because the existing engine rejects postseason overtime. Overtime uses the unchanged legal regular-season engine and exact hazard fallback. Ties remain genuine final ties in a three-class Brier sum. Scores are produced through legal scoring events: no final-score clipping, rounding or rejection is added.

2024 is reused Validation. 2023 was previously included in baseline training and is secondary reused evidence; its new target fold trains only through 2022. No independent prospective superiority claim is available.

New drive ordering uses retained order_sequence. Initial play-ID-only auditing produced 619 apparent score-order failures; all 1,942 scores reconcile after the documented research-label correction. Original donor normalization and published artifacts remain unchanged. Its existing period-end/clock support limitations are not repaired by this challenger.

The game cohort was fixed by canonical identity within week. It overrepresents alphabetically earlier team IDs and is not a league-representative random sample. The 108 games are assessment units; 43,200 simulated outcomes are not independent football observations.

With 200 game draws, a single empirical class probability has maximum binomial sampling standard error about 0.0354. This is simulation precision, not a bound on model error. Winner log loss uses the declared 1e-15 numerical floor for zero empirical observed-class probabilities; zero counts remain explicit in the assessment.

The original play engine receipt supports held-out play log loss 1.182461 versus 1.516647. The supplied orientation values RPS 0.217 and drive-TD MAE 0.081 were not present in that authoritative receipt and are not attributed to this baseline.

Adapter branch counters for 2021/2022 cover only games executed after the documented midpoint-history correction restart; retained earlier full-game draws are unchanged. The 2023/2024 counters cover their complete game runs. CPU and wall timings are descriptive: baseline runs first and warms the shared donor cache. Peak memory is process-wide, not isolated component memory.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -B scripts\run_nfl_drive_survival_v1.py --stage replay
```

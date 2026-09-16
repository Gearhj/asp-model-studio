# CFB archetype and extended-gap challenger V1

**RETAIN_GLOBAL_BASELINE**. Production Ridge and the existing Syracuse–Pittsburgh forecast are unchanged.

This is reconstructed historical research. Development chose all new settings; 2023–2024 is reused Validation and 2025 is secondary reused evidence. No 2026 outcome entered this study.

Clustering produced stable groups but did not add stable incremental predictive value. Its small Validation gain did not persist in both Validation seasons and reversed in reused 2025. The global baseline remains preferred.

The gap/early-season adjustment improved nominal 90% margin coverage from 85.49% to 89.12% across 193 reused Validation games, with average intervals 6.14 points wider. Its primary energy-score interval still crosses zero and it failed the predeclared Development improvement threshold. There are **zero >21-day same-season gaps in 2023–2025**, so later-period evidence supports only an early-season diagnostic, not an established extended-gap benefit. Development has 35 such extended-gap games.

## Baseline binding and chronology discrepancy

The prior 8,543-game count includes 47 current 2026 games. Historical coverage is 8,496 games through 2025; 2014–2015 warm up the point model, and 2016 supplies the first OOF residual season. There are 7,067 recorded OOF point predictions; 718 from 2016 lack a complete earlier residual season and are point-only here.

The exact legacy residual rule admitted any earlier kickoff, including games potentially still in progress. Its outputs are reproduced under `legacy_reference`, with original artifacts retained. The new comparison uses **EXACT_RIDGE_WITH_SEASON_COMPLETE_PAIRED_RESIDUALS_V1**: the identical point forecasts, sampler, 10,000 draws, seeds, rounding and tie treatment, with residual donors restricted to strictly earlier seasons. This study-specific donor eligibility correction is not a change to the published production baseline. Fallback identity is measured against this explicitly named eligible comparison population, not falsely claimed against the legacy reference.

The Syracuse–Pittsburgh forecast already uses completed historical residuals through 2025; this historical same-day-donor gap does not make that prospective residual population late or change its bytes.

Legacy reference scores reconcile exactly for 2,695 saved games. 4,776 assessed legacy populations have a donor kickoff less than six hours before the target. This establishes a timing-certification gap, not the number of actually leaked outcomes.

Ridge's saved Development logistic calibration used all Development labels; its Development probabilities are not chronological OOF. Joint-derived winner scores below use earlier-season residuals. Elo and the later-period Ridge channel are reported separately in ASSESSMENT.json.

## Matched results

Lower energy, CRPS, log loss, Brier and MAE are better. Brier is mean (home-win probability − binary outcome)². Coverage is compared with its nominal level; narrower alone is not better.

| Population | Arm | Games | Applied | Energy | Margin CRPS | Total CRPS | Winner LL | Brier | Margin MAE | Total MAE | Margin 90% coverage / width |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | legacy_reference | 4106 | 0 | 10.6540 | 9.7009 | 9.4370 | 0.5597 | 0.1889 | 13.647 | 13.313 | 0.915 / 58.14 |
| development | baseline | 4106 | 0 | 10.6532 | 9.6971 | 9.4414 | 0.5595 | 0.1888 | 13.647 | 13.313 | 0.917 / 58.17 |
| development | cluster_k2 | 4106 | 2145 | 10.6516 | 9.6949 | 9.4397 | 0.5593 | 0.1888 | 13.643 | 13.310 | 0.916 / 58.19 |
| development | gap | 4106 | 555 | 10.6518 | 9.6946 | 9.4403 | 0.5583 | 0.1886 | 13.647 | 13.313 | 0.921 / 58.81 |
| reused_validation | legacy_reference | 1491 | 0 | 10.2934 | 9.3979 | 9.1226 | 0.5598 | 0.1896 | 13.272 | 12.913 | 0.916 / 56.41 |
| reused_validation | baseline | 1491 | 0 | 10.2901 | 9.3937 | 9.1239 | 0.5595 | 0.1895 | 13.272 | 12.913 | 0.918 / 56.46 |
| reused_validation | cluster_k2 | 1491 | 1277 | 10.2872 | 9.3904 | 9.1223 | 0.5598 | 0.1896 | 13.261 | 12.909 | 0.919 / 56.48 |
| reused_validation | gap | 1491 | 193 | 10.2877 | 9.3897 | 9.1233 | 0.5587 | 0.1893 | 13.272 | 12.913 | 0.923 / 57.25 |
| reused_2025 | legacy_reference | 752 | 0 | 10.0004 | 9.2503 | 8.7852 | 0.5372 | 0.1814 | 13.032 | 12.531 | 0.916 / 56.03 |
| reused_2025 | baseline | 752 | 0 | 9.9980 | 9.2479 | 8.7792 | 0.5376 | 0.1815 | 13.032 | 12.531 | 0.915 / 56.12 |
| reused_2025 | cluster_k2 | 752 | 644 | 10.0057 | 9.2544 | 8.7865 | 0.5385 | 0.1818 | 13.045 | 12.549 | 0.915 / 56.15 |
| reused_2025 | gap | 752 | 99 | 9.9960 | 9.2442 | 8.7793 | 0.5374 | 0.1814 | 13.032 | 12.531 | 0.918 / 56.92 |

## Frozen admission decision

- **cluster_k2: does not pass**. Targeted energy difference -0.0034, 95% week-block interval [-0.0119, +0.0041], n=1277. Failed requirements: developmentEnergy, laterTargetEnergy95, targetCoverage90, bothValidationSeasons.
- **gap: does not pass**. Targeted energy difference -0.0185, 95% week-block interval [-0.0521, +0.0039], n=193. Failed requirements: developmentEnergy, laterTargetEnergy95.

All three k values were screened on Development; only the frozen choice is compared later. No later cluster or subgroup was selected because it scored well. Groupwise intervals are exploratory and not family-wise corrected. A 2025 win cannot rescue a failed Validation gate.

## Target regions and harms

| Region (reused Validation) | Arm | Games | Δ energy [95% block interval] | Δ margin CRPS | Δ total CRPS | Δ winner LL |
|---|---|---:|---|---:|---:|---:|
| weak_support | cluster_k2 | 193 | +0.0000 [+0.0000, +0.0000] | +0.0000 | +0.0000 | +0.0000 |
| weak_support | gap | 193 | -0.0185 [-0.0521, +0.0039] | -0.0307 | -0.0041 | -0.0065 |
| openers | cluster_k2 | 91 | +0.0000 [+0.0000, +0.0000] | +0.0000 | +0.0000 | +0.0000 |
| openers | gap | 91 | -0.0343 [-0.0644, +0.0280] | -0.0579 | -0.0041 | -0.0084 |
| first_primary_games | cluster_k2 | 161 | +0.0000 [+0.0000, +0.0000] | +0.0000 | +0.0000 | +0.0000 |
| first_primary_games | gap | 161 | -0.0108 [-0.0507, +0.0256] | -0.0242 | -0.0020 | -0.0051 |
| ordinary | cluster_k2 | 1298 | -0.0033 [-0.0117, +0.0040] | -0.0038 | -0.0018 | +0.0003 |
| ordinary | gap | 1298 | +0.0000 [+0.0000, +0.0000] | +0.0000 | +0.0000 | +0.0000 |
| conference | cluster_k2 | 1064 | -0.0068 [-0.0154, +0.0010] | -0.0097 | -0.0007 | +0.0002 |
| conference | gap | 1064 | -0.0000 [-0.0023, +0.0018] | -0.0005 | +0.0000 | -0.0004 |
| nonconference | cluster_k2 | 427 | +0.0068 [-0.0025, +0.0164] | +0.0128 | -0.0036 | +0.0004 |
| nonconference | gap | 427 | -0.0083 [-0.0207, +0.0024] | -0.0126 | -0.0019 | -0.0019 |

The archetype correction improved conference-game energy by about 0.0068 points but worsened nonconference energy by about 0.0068; both intervals include zero. In reused 2025 it worsened overall energy by 0.0077, margin and total CRPS, point MAE and winner log loss. The gap adjustment worsened targeted margin CRPS by 0.0105 and Brier by 0.00076 in 2023 while improving those metrics in 2024. These are small, unstable effects, not support for adding complexity.

The assessment JSON includes every individual season, 2020 separately, cluster/matchup cells, home/away errors, signed biases and quantiles, all 50/80/90% intervals, calibration intercept/slope and reliability bands, low/high total tails, Elo-favorite upsets and 28-point margins. Small tail groups are marked unsupported for interpretation. Simulation draws are numerical samples; bootstrap units are actual calendar-week game blocks.

## Limits and operational decision

The existing governed feature set lacks pace, play tendencies, play-level explosiveness, roster, returning production, quarterback, transfer and injury inputs. Total-yards and turnover profiles are available. Cluster associations describe historical states; they do not establish causal matchup mechanisms. Team IDs and conference labels are used for diagnostics only.

Gap adjustment leaves Ridge point expectations and raw residual means fixed and changes centered margin variability only. Flooring, rounding and conditioning on non-tied finals can still shift final means and probabilities; per-game raw/final accounting is retained. It does not append overtime.

The global production baseline remains preferred for current operation. Any research pass is permission for further controlled research only, not AISP integration, new forecasts, wagering or promotion. No provider requests or consumer writes were made.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -B scripts\run_cfb_archetype_gap_v1.py --stage replay
# Full deterministic regeneration in a separate output directory:
.\.venv\Scripts\python.exe -B scripts\run_cfb_archetype_gap_v1.py --stage all --output outputs\cfb-archetype-extended-gap-replay
```

DESIGN.json precedes fitting; FROZEN_SELECTION.json precedes later assessment. artifact-index.json binds sources, immutable originals, models, fold profiles, predictions, score rows, example draws and report bytes.

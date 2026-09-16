# NBA Gen 1: one close-score support comparison

**SUPPORTED_FURTHER_RESEARCH**. Leave the published point/Elo forecast unchanged and keep this corrected joint distribution research-only; no new future study or consumer handoff is opened. The reused 95% interval includes zero for energy; passing a directional point-estimate gate does not establish a stable or meaningful predictive gain.

The same 7,009 previously inspected games and 10,000 retained pairs per game are compared. Negative candidate-minus-baseline proper-score/error differences are better. This is Category A finalized historical reconstruction, not a new OOT or prospective result. The saved paired baseline was unpublished research; the published point/Elo forecast has drawCount=0 and remains unchanged.

Development already had excess one-point mass before tie projection: rounded simulations assigned 5.26%, versus 4.01% observed; projecting 2.63% rounded ties to adjacent untied scores raised final one-point mass to 7.89%.

| Cohort | Games | Arm | Energy | Margin CRPS | Home CRPS | Away CRPS | One-point predicted / actual |
|---|---:|---|---:|---:|---:|---:|---:|
| All | 7,009 | Saved paired | 10.43416 | 7.87354 | 6.68990 | 6.69573 | 7.78% / 4.01% |
| All | 7,009 | Close-score | 10.43408 | 7.87080 | 6.68991 | 6.69602 | 4.52% / 4.01% |
| Development 2021–23 | 3,338 | Saved paired | 10.47716 | 7.74132 | 6.67452 | 6.78251 | 7.89% / 4.01% |
| Development 2021–23 | 3,338 | Close-score | 10.47723 | 7.73870 | 6.67446 | 6.78299 | 4.73% / 4.01% |
| Reused 2024–26 | 3,671 | Saved paired | 10.39506 | 7.99376 | 6.70389 | 6.61682 | 7.68% / 4.00% |
| Reused 2024–26 | 3,671 | Close-score | 10.39484 | 7.99091 | 6.70396 | 6.61694 | 4.34% / 4.00% |

| Season ending | Games | Δ energy | Δ margin CRPS | One-point baseline → candidate / actual |
|---|---:|---:|---:|---:|
| 2021 | 880 | +0.00019 | -0.00096 | 7.52% → 5.34% / 4.32% |
| 2022 | 1,230 | -0.00034 | -0.00457 | 7.91% → 4.48% / 3.25% |
| 2023 | 1,228 | +0.00040 | -0.00185 | 8.14% → 4.53% / 4.56% |
| 2024 | 1,225 | +0.00029 | -0.00307 | 7.61% → 4.30% / 3.67% |
| 2025 | 1,221 | -0.00020 | -0.00199 | 7.73% → 4.37% / 4.50% |
| 2026 | 1,225 | -0.00073 | -0.00351 | 7.70% → 4.35% / 3.84% |

Paired 95% intervals use 2,000 ISO-calendar-week bootstrap resamples (seed 731201).
All: Δ energy -0.00008 [-0.00038, +0.00022]; Δ margin CRPS -0.00274 [-0.00402, -0.00146].
Development: Δ energy +0.00007 [-0.00028, +0.00042]; Δ margin CRPS -0.00262 [-0.00414, -0.00101].
Reused 2024–26: Δ energy -0.00022 [-0.00070, +0.00025]; Δ margin CRPS -0.00286 [-0.00485, -0.00079].

Reused 2024–26 interval coverage, with average width in points in parentheses:

| Distribution | 50% baseline → candidate | 80% baseline → candidate | 90% baseline → candidate |
|---|---:|---:|---:|
| Home | 51.9% (16.22) → 52.0% (16.24) | 80.8% (30.25) → 80.9% (30.29) | 90.6% (38.95) → 90.6% (38.97) |
| Away | 53.6% (15.95) → 53.7% (15.97) | 82.3% (30.65) → 82.3% (30.67) | 91.8% (39.48) → 91.8% (39.54) |
| Total | 51.9% (25.62) → 51.9% (25.62) | 82.3% (49.30) → 82.3% (49.30) | 90.8% (62.31) → 90.8% (62.31) |
| Margin | 51.6% (18.11) → 52.1% (18.28) | 79.8% (35.04) → 79.8% (35.11) | 90.1% (46.18) → 90.1% (46.20) |

The component ran on 6,803 games; 206 retained the exact baseline because calibration prerequisites were unmet. It changed 5,951,360/70,090,000 pairs (8.49%) across 6,803 games. Mean absolute game-level home-mean change was 0.0070 points; maximum 0.0260. Maximum individual team-score change was 1 points. Draw-level nonnegative-support fallbacks: 0.

Every draw total and winner, all pairs with absolute margin above 8, and the full denominator were preserved. Consequently winner probabilities, picks, log loss, Brier, every total score/quantile/coverage and total tail mass remain exactly unchanged per game. This component cannot improve winner predictions or totals. Original paired count hashes and artifacts remain unchanged.

A preserved first execution stopped on floating-point summation-order roundoff in total MCSE; the successor verifies identical draw totals and total mass, checks recomputed summaries within 1e-12, and carries the original numerical total summaries unchanged, with the frozen kernel, radius and decision gate preserved.

Across retained home/away 1%, 5%, 95% and 99% quantile checks, the largest absolute change in reused 2024–26 outside frequency was 0.027 percentage points (home, quantile 0.05; 4.903% → 4.931%); all threshold means and outside-frequency changes are retained in JSON.

Residual reused close-mass gaps remain: odd margins 1/3/5/7 22.19% predicted versus 19.20% observed; even margins 2/4/6/8 19.28% versus 21.22%; all margins 1–8 41.46% versus 40.42%. Conditional transport preserves these masses, so their discrepancies remain uncorrected.

Radius 8 was chosen at the first observed-versus-simulated close-margin cumulative crossing in Development, before later-season comparison. Development kernels use strictly earlier dates, at least 200 calibration games and at least 20 observed close finishes per parity; insufficient support gives exact fallback. The post-2023 kernel uses all 3,338 eligible Development games only. Underlying source history spans 2019–2026; assessment targets span 2021–2026. This does not repair missing historical revision clocks, certify unrecorded pregame information, or establish prospective calibration. No point model, original residual sampler, winner model, total tail, provider collection, forecast publication or authority was changed.

The JSON assessment retains all frozen-group proper scores, home/away/margin paired uncertainty, interval widths, absolute-margin bins 1–8 and source bindings. Games are the assessment units. Simulation MCSE is numerical precision, not a bound on model error.

Read-only reproduction:

```powershell
.venv/Scripts/python.exe scripts/replay_nba_gen1_close_score.py --game-id nba-neil:2024:2023-10-24:DEN:LAL
```

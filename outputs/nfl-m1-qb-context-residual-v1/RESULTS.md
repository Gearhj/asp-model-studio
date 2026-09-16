# NFL M1 lagged QB-usage-conditioned residual challenger

**Decision: reject this configuration for advancement and retain the existing pooled sampler.** The joint energy difference was effectively zero, its interval included benefit and harm, and both winner guardrails worsened. No prospective candidate was frozen.

The completed chronological comparison uses 838 paired residual donors from 2020–2022 and all 570 eligible games in 2023–2024. Each point forecast came from M1 trained only on earlier seasons. Both arms use the same point predictions, 10,000 draws per game, paired residual bank, nonnegative transformation, stochastic rounding and tie handling. The fitted production M1 artifacts and ordinary publication are unchanged.

| Metric (lower is better) | A pooled | B conditioned | B − A | Paired 95% block interval |
|---|---:|---:|---:|---:|
| energy | 8.254915 | 8.254864 | -0.000051 | [-0.017956, +0.019055] |
| logLoss | 0.668019 | 0.670767 | +0.002748 | [-0.000055, +0.005756] |
| brierSum | 0.447134 | 0.449209 | +0.002074 | [-0.000060, +0.004332] |
| homeCRPS | 5.382527 | 5.376993 | -0.005534 | [-0.025993, +0.016126] |
| awayCRPS | 5.148178 | 5.154137 | +0.005959 | [-0.006000, +0.018509] |
| totalCRPS | 7.382033 | 7.384834 | +0.002801 | [-0.027282, +0.033448] |
| marginCRPS | 7.429833 | 7.428319 | -0.001514 | [-0.020652, +0.019668] |

Brier is the sum of squared probability errors over **AWAY/TIE/HOME**, using the existing three-class probability convention. No MLB binary conversion is applied. The interval resamples 44 season/week blocks 2,000 times; the 10,000 simulated draws are not independent observed games. Paired simulation MCSE is retained separately.

| Lagged context: home / away | Applied / fallback games | Matching donors | ESS | Δ expected home / away | Δ energy | Δ log loss | Δ summed Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| STABLE / STABLE | 318 / 0 | 444 | 526.7 | +0.131 / +0.311 | +0.01143 | +0.00198 | +0.00161 |
| MIXED / STABLE | 71 / 0 | 120 | 301.4 | -0.802 / -0.277 | +0.03305 | +0.00553 | +0.00560 |
| STABLE / MIXED | 67 / 0 | 94 | 293.2 | +0.618 / -0.144 | -0.08972 | +0.00812 | +0.00405 |
| MIXED / MIXED | 0 / 22 | 26 | 838.0 | +0.000 / +0.000 | +0.00000 | +0.00000 | +0.00000 |
| Either side UNKNOWN | 0 / 92 | Not conditioned | 838.0 | 0 / 0 | 0 | 0 | 0 |

Conditioning ran on **456 games**. The **114 exact pooled fallbacks** comprise 92 unknown contexts and 22 mixed/mixed games with only 26 matching donors, below the frozen minimum of 40. Every fallback uses all 838 pooled donors. The fitted local shrinkage is n/(n+100); no thresholds or weights were selected from assessment results.

| Supported home / away context | Δ variance home / away | Δ home-away correlation | Δ P(total ≥ 60), pp | Δ P(home ≤ 10), pp | Δ P(away ≤ 10), pp | Δ P(abs margin ≥ 21), pp |
|---|---:|---:|---:|---:|---:|---:|
| STABLE / STABLE | +0.239 / +0.379 | +0.0078 | +1.022 | -0.153 | -0.680 | -0.076 |
| MIXED / STABLE | -5.793 / +3.168 | -0.0122 | -1.752 | +1.784 | +1.162 | +0.093 |
| STABLE / MIXED | -0.428 / -0.767 | +0.0305 | -0.131 | -1.454 | +0.791 | +0.008 |

Variance is in squared points; pp means percentage points. Mixed lagged usage did not uniformly widen the score distribution or lower both teams' means. The population means shifted by +0.0457 home and +0.1221 away points (+0.1678 total). No arm was recentered after weighting.

Period stability: 2023: Δ energy +0.010967, Δ log loss +0.004068, Δ Brier +0.002935, 232/285 supported; 2024: Δ energy -0.011070, Δ log loss +0.001429, Δ Brier +0.001214, 224/285 supported.

Coverage, interval-width and ESS guardrails passed. Primary-score confidence, period stability, winner guardrails and the all-marginal-CRPS guardrail did not. The small energy difference does not establish improvement, and the direction of winner-score changes triggers the predeclared rejection rule.

Context means only the prior two or three eligible same-season games, with at least 20 dropbacks and 90% actor attribution per selected game. It uses a conservative reconstructed availability delay and never the target game's actual quarterback. Archived historical expected-starter/injury availability was not established, so it is absent. NFLverse documents separate update schedules for PBP, player stats, participation and depth charts; available present-day rows do not certify historical pregame availability. [Official source schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html).

This is reused Development with finalized-source corrections and inherited model-selection limitations. Chronological model training does not make it untouched external confirmation. Sealed 2025 and the two motivating opening-2026 results were excluded; no provider acquisition, point-model fit, production change or new monitor occurred.

Frozen configuration: C:\Users\james\asp-model-studio\outputs\nfl-m1-qb-context-residual-v1\objects\sha256\833cfe6adf23ac818d4d499a4bc78b738a4123e6eaa5e00eca0492b184b70ce1\fitted-config.json; physical SHA256 833cfe6adf23ac818d4d499a4bc78b738a4123e6eaa5e00eca0492b184b70ce1.
Assessment: C:\Users\james\asp-model-studio\outputs\nfl-m1-qb-context-residual-v1\objects\sha256\8fe07257e3acba7c9f7445331a2e3991d08c088e4bf7241b15781b8f769a5bd2\assessment.json; physical SHA256 8fe07257e3acba7c9f7445331a2e3991d08c088e4bf7241b15781b8f769a5bd2.

Reproduce the comparison from the retained frozen configuration and admitted assessment data:

```powershell
.venv/Scripts/python.exe -B scripts/run_nfl_m1_qb_context_residuals.py --phase assess --data outputs/nfl-m1-qb-context-residual-v1/residuals/assessment-residuals.parquet --contexts outputs/nfl-m1-qb-context-residual-v1/contexts/contexts.parquet --source-receipt outputs/nfl-m1-qb-context-residual-v1/residuals/assessment-residuals-receipt.json
.venv/Scripts/python.exe -B scripts/report_nfl_m1_qb_context_residuals.py
```

The sampler configuration is self-contained: `authority_from_config(config)` restores its paired bank; `simulate_comparison(...)` accepts point means, exact game identities/dates and honest context keys. It cannot establish current starter availability. The current decision does not authorize a prospective publication.

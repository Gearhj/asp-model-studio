# NBA Gen 1 paired final-score distribution — completed research assessment

**Recommendation: needs a specific close-score support correction before consumer use.** Retain this executable paired-residual baseline for further research. Pairing improves measured joint and marginal distribution scores, but the minimum-distance support rule places excessive probability on one-point finishes. No new model, calibration or publication is promoted.

One matched comparison covers **7,009 games**, 2020–21 through 2025–26, with **10,000 draws per game per arm**. All seasons are reused historical evidence. The first 200 games lack the frozen minimum of 200 earlier OOF donors and remain unsupported. The 2019–20 season supplies initial point-model training, not in-sample residual donors. Neutral-site exclusions and original point-model cohorts remain unchanged.

These are new retrospective research populations built from original season-forward corrected Ridge predictions. Every residual is actual HOME/AWAY minus its saved chronological out-of-fold prediction. The six fitted training boundaries precede their donor games; each target uses only strictly earlier-date donors. Same-date donors and targets are excluded. No all-history refit is applied retrospectively. Original acquisition lineage and finalized-record reconstruction qualifications remain attached: unobserved historical publication times and revision vintages are not reconstructed. The corrected feature specification was chosen using already-inspected Development evidence, so chronological fitting does not restore an untouched test.

The method was frozen at **2026-09-14T14:33:13.114412+00:00**: `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1`. It subtracts the two means of the expanding earlier-donor bank, samples complete residual pairs, and adds corrected Ridge expectations. The simple benchmark permutes the sampled AWAY residual vector, preserving both exact pre-support marginal samples but removing their dependence in expectation. Both arms use the same Ridge points, 10,000 draws and score-support rule. There are no residual-scale/window searches or fitted calibration changes.

Scores already include overtime. The support treatment projects each latent pair onto the nearest nonnegative, unequal integer score pair. After nearest coordinate rounding, a tie goes to the nearest valid one-coordinate ±1 neighbor; only equal distances (absolute tolerance 1e-12) use a symmetric seeded choice. It neither appends overtime nor discards draws or caps the upper tail. The original overtime-dependent simulator remains unchanged and unassessed.

**Matched proper scores** — lower is better; Δ is paired minus benchmark. Energy and CRPS are in points; binary Brier is `(pHome − actualHomeWin)²`; final tie probability is zero.

| Metric | Permuted benchmark | Paired residual | Δ [95% calendar-week interval] |
|---|---:|---:|---:|
| Joint energy | 10.465254 | 10.434157 | -0.031097 [-0.037189, -0.025006] |
| Total CRPS | 10.773072 | 10.755059 | -0.018013 [-0.031592, -0.004136] |
| Margin CRPS | 7.974640 | 7.873538 | -0.101103 [-0.119430, -0.083082] |
| Winner log loss | 0.626806 | 0.625271 | -0.001535 [-0.003312, +0.000384] |
| Binary Brier | 0.218509 | 0.217916 | -0.000593 [-0.001279, +0.000140] |
| Total MAE | 15.158994 | 15.159016 | +0.000022 [-0.000071, +0.000112] |
| Margin MAE | 11.019020 | 11.019049 | +0.000029 [-0.000060, +0.000122] |

Joint energy improves by 0.297% and improves in every season below. Winner-score intervals include zero, so recurring winner improvement is not established. Expected-score errors are effectively unchanged. Intervals use 2,000 paired bootstrap resamples across 142 ISO calendar weeks, seed 731201; they describe game-level historical variation, not model/source uncertainty or proof of prospective gain.

| Season | Games | Benchmark energy | Paired energy | Paired total CRPS | Paired margin CRPS |
|---|---:|---:|---:|---:|---:|
| 2020–21 | 880 | 10.9734 | 10.9322 | 11.5690 | 7.9057 |
| 2021–22 | 1,230 | 10.4687 | 10.4415 | 10.5954 | 8.0778 |
| 2022–23 | 1,228 | 10.2297 | 10.1868 | 10.8307 | 7.2865 |
| 2023–24 | 1,225 | 10.3212 | 10.2954 | 10.4177 | 7.9886 |
| 2024–25 | 1,221 | 10.2955 | 10.2669 | 10.5258 | 7.8279 |
| 2025–26 | 1,225 | 10.6462 | 10.6224 | 10.8207 | 8.1643 |

**Central interval coverage and mean width** — equal-tail inverted-CDF quantiles, inclusive endpoints; widths are points. Full home/away results are retained in `assessment.json` and `results-table.csv`.

| Distribution / nominal | Benchmark coverage / width | Paired coverage / width |
|---|---:|---:|
| Total 50% | 47.64% / 23.05 | 52.95% / 26.35 |
| Total 80% | 75.70% / 43.80 | 82.21% / 50.09 |
| Total 90% | 87.17% / 56.23 | 91.03% / 63.31 |
| Margin 50% | 62.59% / 23.04 | 52.53% / 18.32 |
| Margin 80% | 88.87% / 43.81 | 81.01% / 35.36 |
| Margin 90% | 95.46% / 56.22 | 90.80% / 46.73 |

Pairing corrects much of the benchmark’s narrow total range and overly wide margin range. This is aggregate coverage, not certification of every conditional game or sportsbook line.

| Predeclared group | Games | Paired energy Δ | Paired total 80% coverage | Paired margin 80% coverage |
|---|---:|---:|---:|---:|
| Both ordinary rest supported | 6,928 | -0.0312 | 82.27% | 81.08% |
| Unavailable rest | 81 | -0.0239 | 76.54% | 75.31% |
| Either team season opener | 79 | -0.0266 | 75.95% | 75.95% |

The 79 opener and 81 unavailable-rest games overlap heavily; they are small descriptive groups, not independent confirmations. Winner log loss worsens slightly on both groups. No unsupported rest values were invented and no subgroup-specific correction was fitted.

**Tails:** Development froze low totals at ≤193 and high totals at ≥258. High totals occur in 6.95% of games versus paired 7.04% and benchmark 5.04%. Low totals occur in 4.18% versus paired 5.77% and benchmark 4.03%; the paired low tail is too heavy in aggregate. Observations fall below the paired 1st percentile in 0.63% and above its 99th in 0.98%. In 2025–26, the upper-95% exceedance rate is 6.86%. Tail-selected group tables are descriptive and cannot be read as unconditional interval coverage tests. Empirical donors preserve retained extremes but do not model unobserved tails beyond donor support.

**Support effects:** No negative latent draws occurred. Rounded ties occur in 2.60% of paired draws, all retained and resolved. One-point mass moves from 5.19% after rounding to **7.78%**, versus **4.01% observed**. The rule amplifies a pre-existing excess near-zero margin mass; it does not explain all of it. No latent winner sign or home-win probability changed in these sampled populations. The final-minus-latent mean changes are HOME +0.000097, AWAY -0.000187, total -0.000090 points. Maximum absolute per-game changes are HOME 0.0440, AWAY 0.0368, total 0.0728. Thus means are not claimed unchanged.

Total 1st/99th percentile shifts remain below one point in every game (maximum 0.9867/0.9990). Integer support raises average low/high threshold probabilities by 0.296/0.286 percentage points versus the continuous samples. `support-effects.parquet` retains all four stage summaries and tails, including both arms. Full-bank centering preserves the Ridge means only before finite sampling and support; finite sample means remain separate quantities.

**Separate Elo output:** Joint-derived and Elo winner picks disagree on 972/7,009 games; two joint probabilities are exactly 0.5. Mean absolute probability difference is 6.44 percentage points. These outputs are not forced to agree and do not replace published Elo. Reliability bins are retained, including sparse extreme bins; no calibration was fitted.

**Illustrative totals query:** HOU at OKC, 2025-10-21, `nba-espn:game:401809243`, chosen by earliest eligible 2025–26 metadata before scoring. The new retrospective population has expected HOME 116.8141, AWAY 108.3384; total 80% range [201, 249]. Joint HOME-win probability is 0.7294; the separate saved Elo probability is 0.735343. These are illustrative lines, not recorded market prices.

| Line | Over win | Push | Under win | Draws |
|---|---:|---:|---:|---:|
| 225 | 0.4915 | 0.0237 | 0.4848 | 10,000 |
| 225.5 | 0.4915 | 0.0000 | 0.5085 | 10,000 |

Probability units are fractions from 0 to 1. Over wins when total > line, pushes at equality, loses below; Under reverses win/loss. Full final totals include overtime. Expected net return per unit stake is `pWin*(decimalOdds-1)-pLoss`; fair decimal odds are `1+pLoss/pWin` when pWin>0. There are no recorded prices or profitability claims. Correct probability accounting is not proof of calibrated exact push mass.

**Retention and verification:** 14,018 full populations retain 140,180,000 draws as 28,849,128 unique joint cells across 12 files (30,648,468 physical bytes). Joint count compression is lossless; it preserves the pairs and all scoring tails, not draw order. Seeds and ordered-draw hashes reproduce that order. All game/arm counts, means, winner mass and joint digests reconcile after rereading the saved files. Twelve targeted game/arm replays reproduce exact ordered draws and proper scores. Eighteen synthetic checks cover chronology, support, probability accounting and exact energy-score parity. These software checks are separate from the 7,009 observed-game assessment units.

The conditional paired-sampler MCSE is simulation precision only (mean winner MCSE about 0.00463). Benchmark MCSE fields are iid-reference approximations because permutation induces dependence; they are not used for improvement claims. The original 123 bound artifacts/dirty files remain byte-identical, including the published BOS–DET point/Elo forecast with drawCount=0. An initial storage-range accessor typo stopped execution before any population was saved; its original runner and additive repair receipt are retained. No statistical setting changed.

**Next correction:** Address the excess near-zero/one-point mass with one Development-only discrete-support treatment while keeping Ridge and residual pairing fixed. This assignment does not fit it, open a prospective study, integrate AISP, or add work to Claude. Aggregate range improvements justify preserving the research baseline; they do not justify promoting its exact-score probabilities.

**Reproduce a retained example without writing or republishing anything:**

```powershell
.venv/Scripts/python.exe scripts/replay_nba_gen1_joint_residual.py --game-id nba-espn:game:401809243 --line 225.5
```

The one-time study commands were `run_nba_gen1_joint_residual.py freeze`, `run`, `report`, `verify`, followed by `verify_nba_gen1_joint_counts.py`. Completed artifacts are immutable; the replay command above is repeatable. Source/model bindings are in `residual-provenance.json`; the method is in `method-freeze.json`; all proper scores, groups and uncertainty are in `assessment.json`; `index.json` binds physical bytes. No provider requests, model fitting, new forecasts, consumer imports or operating authority changes occurred.

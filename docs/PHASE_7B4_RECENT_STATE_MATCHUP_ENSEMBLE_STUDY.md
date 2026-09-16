# Phase 7B4 — Recent-state, matchup, and ensemble study

## Terminal research decision

**E. ADOPT_RELIABILITY_GATED_ENSEMBLE**

The development-only rolling-origin study selected `E10`, the fixed
reliability-gated multinomial Logistic stacker. On the one-time frozen 2024
validation population, `E10` improved multiclass log loss from
`1.4778808498644482` to `1.4761173475094573`. The paired whole-game bootstrap
interval for `E10 - Direct Gold` was entirely below zero:
`[-0.0022254009280201366, -0.0013376007605967381]`.

This is a research-only result. No model was promoted and no production
selection authority was changed.

## Frozen scope and authority

- Study branch: `phase7b4-recent-state-matchup-ensemble-study`
- Implementation base: `009b3f87aa9352fee16e4c27ce5d0bc8bcb7c91d`
- Gold dataset: `gold-table:gold_mlb_pa_v1:sha256:56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0`
- Gold manifest SHA-256 before read, after read, and after study:
  `5e962e86aabe4450b05e13552814ce46355ab3e92a08641d890b1e47adf8629b`
- Frozen Direct Gold experiment:
  `de7966fba2e6dfd1cde466eadb2b8cd6d737695fd75d89d5fce0938e8060538f`
- Direct Gold model SHA-256:
  `1ea82a4a724ccd00913d69fa6e94c8a990c258793465b8da7b064350a44a9f92`
- Development population: 536,102 rows from 2021–2023
- Development rolling-origin OOF population: 302,260 rows
- Frozen validation population: 180,711 rows from 2024
- Governed class order: `STRIKEOUT`, `WALK_HBP_CI`, `HOME_RUN`, `SINGLE`,
  `DOUBLE`, `TRIPLE`, `BIP_OUT`, `OTHER_REACH`

Bronze and Silver were not rebuilt. Gold V1 was not altered. The study opened
only 2021, 2022, 2023, and 2024. It did not open 2025 or 2026 and did not use
outside data.

## Components and temporal controls

The fixed component contract is machine-readable at
[`phase7b4/feature-component-specification.json`](phase7b4/feature-component-specification.json).
It covers the Direct model, long-term state, 14- and 42-completed-day state,
180- and 365-day exponential decay, 6-by-6 soft cluster matchup, exact
batter-versus-pitcher history shrunk with prior strength 50, and
expectation-adjusted recent residual form.

Every empirical state excludes the target PA and all current-day PAs. For
each rolling validation block, state, clusters, preprocessing, models, and
ensemble parameters were fitted only on earlier rows. Historical Direct
expectations used by the residual component were produced with deterministic
two-fold whole-game cross-fitting inside each outer training population, so a
game never contributed to the model that scored its residual expectations.
No 2024 result participated in candidate selection or weight fitting.

The six prescribed rolling blocks contained 59,830, 58,693, 33,799, 60,330,
58,399, and 31,209 validation rows, respectively, reconciling exactly to
302,260 OOF rows.

## Development-only selection

The selected non-Direct standalone component was `RECENT_RESIDUAL_FORM`; the
selected simple ensemble was `E7`; and the best overall OOF candidate was
`E10`. Selection used development OOF log loss only.

| Candidate | Role | OOF log loss | Summed Brier | ECE | Accuracy | Macro-F1 | Coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| `RECENT_RESIDUAL_FORM` | best non-Direct standalone | 1.482415053433148 | 0.7056938830273262 | 0.008832392482110847 | 0.4512307285118772 | 0.09487370703117852 | 0.5714384966585059 |
| `DIRECT_MODEL` | anchor | 1.482507057146505 | 0.7057306635077544 | 0.009196282369512246 | 0.45112155098259776 | 0.09439794532405912 | 1.0 |
| `E7` | best simple ensemble | 1.4824450619261842 | 0.7057033862839235 | 0.008996516831772846 | 0.45118771918216105 | 0.09463704001110164 | 1.0 |
| `E9` | optimized convex blend | 1.4804016213772493 | 0.705000843100487 | 0.003335084091863114 | 0.45182955071792497 | 0.09257446853384332 | 1.0 |
| `E10` | reliability-gated stacker | 1.476932189990602 | 0.7040666840806663 | 0.001448814090316141 | 0.4525971018328591 | 0.0941833067734784 | 1.0 |

## Frozen 2024 result

| Candidate | Log loss | Summed Brier | ECE | Accuracy | Macro-F1 | Improvement vs Direct |
|---|---:|---:|---:|---:|---:|---:|
| Direct Gold | 1.4778808498644482 | 0.7040277515790683 | 0.001438315874177647 | 0.4534035006170073 | 0.09332003157919234 | 0.0 |
| `E10` | 1.4761173475094573 | 0.7035297983115686 | 0.006936599439379347 | 0.4534145680119085 | 0.09002992701356265 | +0.001763502354990898 |
| `E9` | 1.4766224326199442 | 0.7036234978492208 | 0.0051395432114551085 | 0.45377425834619917 | 0.09038477770832254 | +0.0012584172445040398 |

`E10` improved the primary log-loss objective and summed Brier score. Its ECE
and macro-F1 were worse than Direct Gold, so adoption here means retaining the
fixed research architecture for further out-of-time evaluation—not promoting
it or claiming uniform metric dominance.

## Bootstrap and robustness

The paired bootstrap used 2,000 replicates over 2,409 whole-game clusters with
seed `20260824`. Differences are candidate minus Direct Gold; negative values
favor the candidate.

| Candidate | Point difference | 95% interval | Replicates favoring candidate |
|---|---:|---:|---:|
| `E10` | -0.0017635023549908558 | [-0.0022254009280201366, -0.0013376007605967381] | 1.0 |
| `E9` | -0.0012584172445040806 | [-0.0015565856257770522, -0.0009737414083926763] | 1.0 |

`E10` improved log loss in every 2024 month from March through September.
Its lift was larger in the high-disagreement slice than in the low-disagreement
slice. It improved seen-batter and both seen/unseen-pitcher slices, but worsened
the unseen-batter slice. Per-class lift was concentrated: it improved
`STRIKEOUT`, `WALK_HBP_CI`, and `TRIPLE`, while the other five classes were
worse. The evidence therefore supports broad calendar stability and strong
paired-game uncertainty, but not uniform class or cold-start dominance.

## Coverage and ensemble interpretation

On the frozen 2024 block, long-term, decay, and cluster components covered
149,331 rows (`0.8263525739993691`). Exact batter-versus-pitcher history
covered 73,692 rows (`0.40778923253150057`) with mean effective sample size
`4.229495739021875`.

The 14-day, 42-day, and residual recent-state components had zero 2024
coverage. This is the intentional consequence of freezing all state before
the entire 2024 validation block: after the offseason, no within-block 2024
updates are permitted. Their probability fallback equals the authorized
anchor, while their missingness and reliability fields remain available to
the stacker.

The static convex blend `E9` assigned most mass to residual form
(`0.698258014828982`), with long-term (`0.21062387583024375`), exact BvP
(`0.07015591852020682`), and decay-180 (`0.020962190820567522`) supplying the
remainder. The displayed `E10` values are normalized coefficient-magnitude
diagnostics, not fixed per-row probability weights.

## Tables

Each table is committed in CSV and JSON form:

1. [Standalone component leaderboard](phase7b4/tables/standalone-component-leaderboard.csv)
2. [Ensemble leaderboard](phase7b4/tables/ensemble-leaderboard.csv)
3. [Incremental lift versus Direct Gold](phase7b4/tables/incremental-lift-versus-direct.csv)
4. [Component coverage and reliability](phase7b4/tables/component-coverage-reliability.csv)
5. [Monthly stability](phase7b4/tables/monthly-stability.csv)
6. [Bootstrap uncertainty](phase7b4/tables/bootstrap-uncertainty.csv)
7. [Final ensemble weights](phase7b4/tables/final-ensemble-weights.csv)

## Charts

Each chart is committed as reviewable PNG and SVG:

1. [2024 log-loss improvement](phase7b4/charts/01_2024_log_loss_improvement.png)
2. [Candidate/component heatmap](phase7b4/charts/02_candidate_component_heatmap.png)
3. [Monthly stability](phase7b4/charts/03_monthly_stability.png)
4. [Calibration/reliability](phase7b4/charts/04_calibration_reliability.png)
5. [Ensemble weights](phase7b4/charts/05_ensemble_weights.png)
6. [Disagreement performance](phase7b4/charts/06_disagreement_performance.png)

## Artifact evidence

Large models, state objects, OOF/validation predictions, and reliability
matrices remain outside Git under the immutable request-addressed root:

`C:\Users\james\asp-data-staging\mlb-gold-v1\recent-state-studies\sha256\29f3cac53d9d3274dece1ba016ca96b841615b01c72ac61dc7dc2b5fddb751da`

- Study SHA-256: `29f3cac53d9d3274dece1ba016ca96b841615b01c72ac61dc7dc2b5fddb751da`
- Results SHA-256: `60632b3be970759b3b9cce14a2c979e2978874a24021688a1bdb62139dc4718c`
- Manifest status: `RESEARCH_ONLY`
- Promotion eligible: `false`
- Manifest-listed artifacts: 58
- Independently rehashed artifact failures: 0
- Focused `tests/phase7b2` verification: 30 passed, 0 failed, 0 errors

## Limitations and next experiment

- State is frozen before each validation block; same-block updates are
  deliberately excluded.
- Recent-window coverage can decay late in a frozen block and is zero after a
  long offseason when an entire season is the untouched block.
- `E10` diagnostic chart weights are global normalized coefficient magnitudes,
  not row-level gates.
- The matched Gold population excludes 13,471 fail-closed bridge rows across
  2021–2024.

If this architecture remains of interest, repeat the exact fixed study on a
future untouched season after that season becomes authorized. Do not broaden
the model family for that confirmation run.

No promotion was requested or performed.

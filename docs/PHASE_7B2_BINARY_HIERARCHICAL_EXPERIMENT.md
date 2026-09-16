# Phase 7B2 BATTER_RETIRED binary / hierarchical PA experiment

## Status

`BINARY_HIERARCHICAL_TARGET_EXPERIMENT_COMPLETE`

This was a research-only experiment on the frozen `gold_mlb_pa_v1` object
`56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0`.
No Bronze, Silver, or Gold data was rebuilt; no feature was added; no 2025 row
was opened; and no model was registered, promoted, or made champion-eligible.

## Target contract

The experiment uses the requested class-level operational definition:

- `OUT`: `STRIKEOUT`, `BIP_OUT`
- `NOT_OUT`: `WALK_HBP_CI`, `HOME_RUN`, `SINGLE`, `DOUBLE`, `TRIPLE`,
  `OTHER_REACH`

The governed FD1 target taxonomy maps only Retrosheet `roe` and `fc` to
`OTHER_REACH`; in both cases this batter reaches. `OTHER_REACH` therefore has
no mixed batter-retired semantics under the frozen target contract.

Development was the existing 536,102 matched 2021–2023 rows. Validation was
the exact existing 180,711 matched 2024 rows. The realized 2024 `OUT` rate was
0.6784755770263017; the development-frequency forecast was
0.6743623414947155.

## Binary results

PR-AUC is average precision. ECE uses ten equal-width bins. Calibration is the
diagnostic logistic recalibration `y ~ intercept + slope * logit(p)`; the null
forecast's constant score makes its joint slope unidentifiable.

| Model | Log loss | Brier | Cal intercept | Cal slope | ECE | ROC-AUC | PR-AUC | Accuracy | Fit s | Score s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Binary class-frequency null | 0.628051796018 | 0.218163387112 | 0.018792697717 | — | 0.004113235532 | 0.500000000000 | 0.678475577026 | 0.678475577026 | 0.000662 | 0.000261 |
| Collapsed Base Logistic | 0.626262522280 | 0.217361121691 | 0.092330245847 | 0.907148218326 | 0.006101378623 | 0.536567593204 | 0.701580363378 | 0.678475577026 | 0 (persisted) | 0.289915 |
| Collapsed Gold Logistic | 0.626018498939 | 0.217263042539 | 0.186352822195 | 0.792237619035 | 0.010367411645 | 0.540332742528 | 0.705533758940 | 0.678442374842 | 0 (persisted) | 0.411276 |
| Dedicated Base binary Logistic | 0.626199599210 | 0.217343649049 | 0.066300224926 | 0.941258641083 | 0.005541830947 | 0.536632395837 | 0.701842471598 | 0.678464509631 | 7.372293 | 0.193175 |
| Dedicated Gold binary Logistic | 0.625963633509 | 0.217245747123 | 0.172000178261 | 0.809120389735 | 0.009491083331 | 0.540202628270 | 0.705510165173 | 0.678453442236 | 34.727448 | 0.312564 |
| Dedicated Gold binary HGB | 0.626062579404 | 0.217289678913 | 0.227341795427 | 0.733125089711 | 0.011631944384 | 0.540027100779 | 0.705178271072 | 0.678475577026 | 19.516117 | 1.996127 |
| **Dedicated Gold binary Extra Trees** | **0.625743761355** | **0.217137006290** | -0.269026529300 | 1.414258489466 | 0.007596870610 | **0.540489407719** | **0.705671512282** | 0.678475577026 | 261.756774 | 4.310813 |

All seven requested evaluations completed without a model error. The two
collapsed rows scored the byte-verified persisted eight-class artifacts; they
were not refit.

## Hierarchical reconstruction

The Extra Trees binary probability replaced only the total `OUT` versus
`NOT_OUT` mass of the direct Gold Logistic vector. Within each group, the
direct Gold Logistic class ratios were retained.

| Variant | Multiclass log loss | Summed Brier | Top-label ECE | Accuracy | Macro-F1 |
|---|---:|---:|---:|---:|---:|
| Direct Gold Logistic | 1.4778808498644482 | 0.704027751579 | 0.001438315874 | 0.453403500617 | 0.093320031579 |
| Hierarchical reconstruction | **1.4776061122808983** | **0.703924693972** | 0.002310235930 | 0.453375832130 | 0.092580577668 |

The reconstruction improved log loss by 0.000274737584 and summed Brier by
0.000103057607. ECE, accuracy, and macro-F1 were slightly worse. Probability
verification passed for all 180,711 rows: exact governed class order, finite,
nonnegative, row sums within 4.44e-16 of one, and within-group proportions
preserved within 4.44e-16.

## Recommendation

`C. ADOPT_HIERARCHICAL_8_CLASS_ARCHITECTURE`

The dedicated binary model improved the existing collapsed Gold binary log
loss, and substituting its group mass improved the primary eight-class log-loss
metric and summed Brier. This is an architecture recommendation only; nothing
was promoted. The small magnitude and mixed secondary metrics should remain
visible in any subsequent experiment.

## Evidence and command

Authoritative result root:

`C:\Users\james\asp-data-staging\mlb-gold-v1\binary-experiments\sha256\feece979e84ef89f4057fd71c4e3be4d20e5042ea28be4fedd4c2223b16f3591`

Result SHA-256: `df121180534ce4396d8b929abea92f66e28b57a5673a676413cb47fb3b6d4cfc`

Report SHA-256: `31c8bfb5f59e9d2de57ddfbe5f04fb164a803bfbb8939df39f072e0413713529`

Command:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.phase7b_research --binary-hierarchical --gold-root C:\Users\james\asp-data-staging\mlb-gold-v1
```

Focused verification: `14 passed`, `0 failed`, `0 errors` in
`tests/phase7b2`.

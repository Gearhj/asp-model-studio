# NFL overnight Development model laboratory

- Run: `matrix-fcc3cd9a5446-foundation-ebb6912919a5`
- Development population: 6,991 games, 1999–2024
- Validation: five expanding, game-atomic seasonal folds (2020–2024)
- Final OOT: 2025 SEALED and physically unread
- Planned/completed/failed/skipped screening pipelines: 22/22/0/0
- Tuned finalists: 2, four predeclared configurations per outer fold
- Development-selected score pipeline: `HIST_GRADIENT_BOOSTING_B_T2`
- Calibration: `REGULARIZED_CALIBRATED`
- Status: `RESEARCH_SHADOW`, `NOT_PROMOTED`, no wagering or AISP execution authority

## Leading pipelines

| Pipeline | Family | Features | Treatment | Raw log loss | Brier | Margin MAE | Total MAE |
|---|---|---|---|---:|---:|---:|---:|
| HIST_GRADIENT_BOOSTING_B_T2 | HIST_GRADIENT_BOOSTING | B | T2 | 0.674775 | 0.448931 | 10.1357 | 10.6985 |
| M1_RECIPE_FOLD_REFIT | XGBOOST | B | T0 | 0.674896 | 0.448840 | 10.0699 | 10.6270 |
| HIST_GRADIENT_BOOSTING_B_T1 | HIST_GRADIENT_BOOSTING | B | T1 | 0.675733 | 0.449657 | 10.1355 | 10.6983 |
| XGBOOST_F1_T1 | XGBOOST | F1 | T1 | 0.676002 | 0.449611 | 10.1010 | 10.5896 |
| XGBOOST_B_T1 | XGBOOST | B | T1 | 0.676028 | 0.449603 | 10.1049 | 10.5954 |

Chronological calibration reduced HGB-T2 log loss to 0.662128 and the fold-refitted M1 recipe to 0.665318. The selected calibrated system minus calibrated M1 difference is −0.003190; its 95% season-week clustered bootstrap interval is [−0.009351, 0.002521] across 109 blocks. The interval crosses zero. This is Development evidence, not independent confirmation, so M1 remains retained. The HGB-T2 result is preserved only as an unpromoted research finalist.

## Treatment and feature findings

- T1/T2 helped Ridge by −0.003923/−0.003691 raw log loss versus T0.
- T1/T2 helped histogram boosting by −0.001278/−0.002236 versus T0.
- T1 helped XGBoost slightly (−0.000357); T2 hurt (+0.001845).
- Both Extra Trees treatments and both MLP treatments hurt their T0 baselines.
- F1 helped Ridge (−0.003557) and was negligible for XGBoost (−0.000025), but hurt HGB (+0.005256).
- F2 hurt all three controlled T1 comparisons. These are whole-package effects, not isolated causal effects of individual preprocessing components.
- Historical quarterback, injury, and weather context was excluded because usable pregame availability was not established in the registered 197-input authority.

## Artifacts and workflow

- Core manifest SHA-256: `c8faf34053fa8268c62aee3248585eb5116f121eefffe0b69eeb21a089435203`
- Core handoff SHA-256: `41bc98012c6da923fef4c489d9ff48548e74d1f693990d9f4558ccf918044180`
- Treatment/feature manifest SHA-256: `d63cf395ce759db5bd3664510adb4ff3d2a86339d663f5f7e7e121b614495127`
- Fitted score artifact SHA-256: `e3aac46a7ad60378c63f7472d66d866e8cd3e5768d37b1cdff260784d365599e`; reload mismatch 0
- Fitted calibrator SHA-256: `fa6a0ba17669bb15a566a74f0937272abd2416104c1d86751525782ce5eeecff`; reload mismatch 0
- No-fit interpretability supplement SHA-256: `5d4e52be7f7568d9a3b8d8a8a4732db505c5286481839052324248813839f681`
- Registered Model Studio project: `sports-project-nfl-overnight-model-lab-v1`
- Registered workflow evidence: steps 8 (laboratory), 9 (Development OOF), and 10 (calibration/interpretability)
- Registered model lifecycle: `research_candidate`, `research_only`, `development_oof_only`, champion pointer `NULL`

The registered market table was excluded from benchmarking because it has no quote-observation timestamp, so comparable pregame timing cannot be proven. Recommended next decision: retain M1 and, only if separately authorized, run a fixed prospective research-shadow comparison of the preserved calibrated HGB-T2 finalist.

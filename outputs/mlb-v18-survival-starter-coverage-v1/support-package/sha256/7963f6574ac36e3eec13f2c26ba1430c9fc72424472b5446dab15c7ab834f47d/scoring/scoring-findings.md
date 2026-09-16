Existing frozen MLB pairs

Candidate minus baseline. Negative log loss/Brier/absolute-error/CRPS/energy differences favor candidate. Signed run error is predicted minus observed.

| Study | Status | Final H-A | Δ log loss | Δ Brier |
|---|---|---:|---:|---:|
| 2026-09-11 COL-DET duration | SCORED_ONE_MATCHED_GAME | 6-2 | -0.008113 | -0.003837 |
| 2026-09-12 NYM-NYY transition | SCORED_ONE_MATCHED_GAME_SUMMARY_MEASURES_ONLY | 2-12 | -0.003315 | -0.001531 |
| 2026-09-12 KC-BOS transition | SCORED_ONE_MATCHED_GAME | 5-1 | +0.001952 | +0.000924 |

NYM–NYY candidate distributions were not retained; its eligible measurements are winner and mean-score errors. Missing optional component truth does not block whole-game scoring.

Studies remain separate: baseline/source horizons and duration/transition interventions differ. No pooled ensemble comparison.

One pair is one observed game; 5,000 draws measure simulation precision, not 5,000 independent assessment observations.

Run: `.venv/Scripts/python.exe scripts/score_mlb_frozen_component_pairs_v1.py`

Immutable result: C:\Users\james\asp-model-studio\outputs\mlb-v18-survival-starter-coverage-v1\scoring\objects\sha256\00bb026ffab2f678569c9462f884604df4572f9aa5430ad8e97caec3d54c98a8\scoring-findings.json (SHA256 00bb026ffab2f678569c9462f884604df4572f9aa5430ad8e97caec3d54c98a8)

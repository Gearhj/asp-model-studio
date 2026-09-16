Existing frozen MLB pairs

Candidate minus baseline. Negative log loss/Brier/absolute-error/CRPS/energy differences favor candidate. Signed run error is predicted minus observed.

| Study | Status | Final H-A | Δ log loss | Δ Brier |
|---|---|---:|---:|---:|
| SYNTHETIC persistence transition | SCORED_ONE_MATCHED_GAME_SUMMARY_MEASURES_ONLY | 3-1 | -0.064539 | -0.022500 |

NYM–NYY candidate distributions were not retained; its eligible measurements are winner and mean-score errors. Missing optional component truth does not block whole-game scoring.

Studies remain separate: baseline/source horizons and duration/transition interventions differ. No pooled ensemble comparison.

One pair is one observed game; 5,000 draws measure simulation precision, not 5,000 independent assessment observations.

Run: `.venv/Scripts/python.exe scripts/score_mlb_frozen_component_pairs_v1.py`

Immutable result: C:\Users\james\asp-model-studio\outputs\mlb-v18-three-arm-pregame-comparison-v1\scoring\focused-checks\synthetic-persistence-v1\objects\sha256\7016314312fe39794d29d31ecc5b445f89cc2088d9cfc80ef125750e2299aa09\scoring-findings.json (SHA256 7016314312fe39794d29d31ecc5b445f89cc2088d9cfc80ef125750e2299aa09)

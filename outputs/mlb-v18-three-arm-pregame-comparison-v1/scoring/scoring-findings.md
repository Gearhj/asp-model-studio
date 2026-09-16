Existing frozen MLB pairs

Candidate minus baseline. Negative log loss/Brier/absolute-error/CRPS/energy differences favor candidate. Signed run error is predicted minus observed.

| Study | Status | Final H-A | Δ log loss | Δ Brier |
|---|---|---:|---:|---:|
| 2026-09-11 COL-DET duration | AWAITING_ELIGIBLE_FINAL | Pending | — | — |
| 2026-09-12 NYM-NYY transition | AWAITING_ELIGIBLE_FINAL | Pending | — | — |
| 2026-09-12 KC-BOS transition | AWAITING_ELIGIBLE_FINAL | Pending | — | — |

NYM–NYY candidate distributions were not retained; its eligible measurements are winner and mean-score errors. Missing optional component truth does not block whole-game scoring.

Studies remain separate: baseline/source horizons and duration/transition interventions differ. No pooled ensemble comparison.

One pair is one observed game; 5,000 draws measure simulation precision, not 5,000 independent assessment observations.

Run: `.venv/Scripts/python.exe scripts/score_mlb_frozen_component_pairs_v1.py`

Immutable result: C:\Users\james\asp-model-studio\outputs\mlb-v18-three-arm-pregame-comparison-v1\scoring\objects\sha256\56db3b1ad642ad7b1a8f4894c43394aad1b29ee025198cf0dbdc9a5f4fda30ad\scoring-findings.json (SHA256 56db3b1ad642ad7b1a8f4894c43394aad1b29ee025198cf0dbdc9a5f4fda30ad)

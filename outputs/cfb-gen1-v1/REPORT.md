# College Football Gen 1 report

A qualifying real College Football population was admitted for private reconstructed historical research.

Selected point model: `ridge_alpha100`. Distribution recommendation: `SUPPORTED_FOR_FURTHER_RESEARCH_NOT_PROSPECTIVE_AUTHORITY`.

The admitted primary population has 8,543 real FBS-v-FBS regular-season games across 2014-2026. Development has 6,253 games (2014-2015 warmup; 4,824 scored season-forward games in 2016-2022), Validation has 1,491 games, the reused 2025 historical holdout has 752, and current 2026 contains 47 completed primary games that were excluded from selection.

The frozen roles are Development 2014–2022 (2014–2015 warmup; 2016–2022 season-forward scoring), Validation 2023–2024, reused historical holdout 2025, and prospective current season 2026. No 2026 result was used for selection.

| Population | Model | Games | Margin MAE | Total MAE | Winner log loss | Brier | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| Validation 2023-24 | league | 1,491 | 15.823 | 13.783 | 0.6785 | 0.2427 | 0.586 |
| Validation 2023-24 | ridge_alpha100 | 1,491 | 13.272 | 12.913 | 0.5601 | 0.1898 | 0.712 |
| Validation 2023-24 | hgb_l2_50 | 1,491 | 13.401 | 13.045 | 0.5627 | 0.1911 | 0.705 |
| Validation 2023-24 | elo_winner_only | 1,491 | — | — | 0.6060 | 0.2088 | 0.673 |
| 2025 holdout | league | 752 | 16.136 | 13.467 | 0.6759 | 0.2414 | 0.593 |
| 2025 holdout | ridge_alpha100 | 752 | 13.032 | 12.531 | 0.5418 | 0.1827 | 0.719 |
| 2025 holdout | hgb_l2_50 | 752 | 13.027 | 12.630 | 0.5452 | 0.1841 | 0.714 |
| 2025 holdout | elo_winner_only | 752 | — | — | 0.5946 | 0.2033 | 0.694 |

The paired-residual assessment covers 2,695 games with 10,000 joint draws each. Joint energy score is 10.372; total CRPS 9.165; margin CRPS 9.497. Central 80% coverage is 0.822 for total and 0.822 for margin.

Development froze low/high total tails at <= 34 and >= 80. Across assessment games, predicted versus observed rates are 0.140 versus 0.125 for the low tail and 0.078 versus 0.075 for the high tail.

The final-score transformation floored 1,333,897 negative team-score samples and resolved 504,660 initial discrete ties. It shifted mean home/away scores by 0.147/0.126 points; the retained accounting reports its low/high-tail probability shifts separately.

Excluded-context diagnostics on reused 2023-2025 evidence contain 365 FBS-versus-non-FBS regular-season games (margin/total MAE 15.796/12.963) and 137 combined postseason games (margin/total MAE 13.588/13.716). They did not train or select the primary model; bowl/playoff subtypes remain unavailable.

The clearest weakness is opener or extended-gap support: 242 such games have joint energy score 12.131, margin CRPS 12.000, winner log loss 0.684, and only 82.2% coverage for the nominal 90% margin interval. The 2020 regime and nonconference games also have worse distribution scores than the overall population.

The main limitations are incomplete exact postseason subtype classification, historically reconstructed rather than captured pregame vintages, missing quarterback/player/injury context, and a current 2026 schedule file with no future kickoff after capture.

No local future forecast was created: `NO_ELIGIBLE_FUTURE_GAME_IN_CAPTURE`.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe -B scripts\acquire_cfb_gen1_v1.py
.\.venv\Scripts\python.exe -B scripts\run_cfb_gen1_v1.py
```

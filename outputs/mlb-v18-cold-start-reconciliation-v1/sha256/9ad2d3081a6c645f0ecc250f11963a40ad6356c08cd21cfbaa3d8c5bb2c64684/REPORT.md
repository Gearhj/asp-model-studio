# MLB V18 cold-start reconciliation

240 specified features, 64 no-history entries; 218 selected source features + 55 prior outputs = 273 inputs before categorical expansion.

All 21 prior treatments execute: 11 Wave 1 raw + posterior/reliability/effective-N/std/state, and 10 Wave 2 posterior-only. Five immutable fitted preprocessing artifacts verified. Ordinary prior median/mode fallback: **0 recorded** across disjoint validation folds. Governed WHIP population fallback: **56**, a distinct valid authority and not the held batter population.

The 56 held Development PAs have observed zero prior PA exposure, prior_missing=false and three undefined raw annual rates; all five companion AB/hit/extra-base components are exactly zero, with no missing component cells. V2 supports TRUE_NO_OPPORTUNITY; V1 does not register that state. Hold remains unchanged (51 OOF PAs).

| Saved subgroup | PAs | V18 log loss | History complement PAs | V18 complement log loss |
|---|---:|---:|---:|---:|
| BATTER_TRUE_COLD_START | 37,828 | 1.468556158 | 463,711 | 1.475081722 |
| PITCHER_TRUE_COLD_START | 49,629 | 1.490401279 | 451,910 | 1.472853085 |
| EITHER_PLAYER_TRUE_COLD_START | 83,174 | 1.481061258 | 418,365 | 1.473302914 |
| BATTING_NO_PRIOR_GAME | 3,385 | 1.480644147 | 498,154 | 1.474548397 |
| FIELDING_NO_PRIOR_GAME | 3,386 | 1.484833954 | 498,153 | 1.474519906 |
| EITHER_TEAM_NO_PRIOR_GAME | 3,535 | 1.482913993 | 498,004 | 1.474530449 |

History complement means these source no-history flags are false; it does not prove all rolling histories are established. Complements use additive saved sums. Their game counts and intervals are not inferred. Original subgroup paired game-clustered intervals are retained in JSON. These overlapping observational groups do not establish causal treatment uplift.

V14's older audit remains historical; its possible median seam is not asserted to have occurred in its recorded folds. V18's guards reject unapproved prior states before a generic imputer. No concrete new defect was found in this bounded saved-evidence reconciliation. No MLB fit, source scan, OOT access, AISP action or accepted-artifact change occurred.

Evidence: `C:\Users\james\asp-model-studio\outputs\mlb-v18-cold-start-reconciliation-v1\sha256\9ad2d3081a6c645f0ecc250f11963a40ad6356c08cd21cfbaa3d8c5bb2c64684\reconciliation.json`; SHA-256 `9ad2d3081a6c645f0ecc250f11963a40ad6356c08cd21cfbaa3d8c5bb2c64684`.

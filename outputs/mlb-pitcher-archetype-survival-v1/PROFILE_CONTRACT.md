Pitcher-style research profile contract

This experiment asks whether prior pitching style adds information about starter duration. It preserves the seven existing duration predictors, the all-cause removal definition and the separate GAME_END endpoint. Style does not assert current readiness, pitch quality or optimal managerial usage.

For each eligible historical start, the builder takes recorded pitches from completed games on dates in `[start date − 365 days, start date)`. It excludes all same-day games, the target appearance, later games and known completion/identity holds. The 2023–2024 history pool requires both starts to be supported by the corrected duration ledger. The 2022 warmup requires an exact registered game identity and empty Retrosheet completion metadata. All nine permanent exclusions are checked before telemetry access; the selected source partitions are physically limited to 2022–2024.

Profile support requires an exact pitcher identity, at least 200 prior recorded pitches across three dates, and one consistent observed throwing hand. A statistic requires at least 30 finite measurements for its pitch group; otherwise it remains missing and the training-only imputer handles it. Usage always divides by all eligible recorded pitches, retaining an explicit UNKNOWN category. Missing features are not invented velocity or pitch quality.

| Feature | Definition / units |
|---|---|
| Throwing hand | `style_throws_left`: 1 for L, 0 for R; inconsistent/unknown hand makes the profile unsupported |
| Pitch usage | Fraction of prior recorded pitches in FF/FA, SI/FT, FC, SL/ST/SV, CU/KC, CH, FS/FO, OTHER or UNKNOWN |
| Typical velocity | Median recorded release speed, mph, separately for each group |
| Upper velocity | 90th percentile, linear empirical quantile, mph, separately for each group |
| Movement | Median source `pfx_x` and `pfx_z`, feet; signed horizontal source orientation retained |
| Release | Median source horizontal/vertical release position and extension, feet |

Horizontal movement and release position retain the source catcher-view orientation with explicit throwing hand; the builder does not assert a hand-normalized movement convention. The source `pfx` measurements are descriptive movement values, not effectiveness scores. No location/command or outcome-based pitch-quality predictor is introduced. A descriptive label such as curve-heavy is based on usage, never on an assumption that the curve is good.

The feature era is 2022–2024, after the 2020 tracking-system transition. Slider/sweeper/slurve classifications are grouped for modeling, while exact raw type counts and statistics remain in profile metadata. This avoids treating the introduction of the sweeper label as an independently measured new style. Location fields are omitted; no location definition is bridged across seasons. Measurement reference: [Baseball Savant CSV documentation](https://baseballsavant.mlb.com/csv-docs).

The retained historical source revisions were captured in August 2026. These are prior-event reconstructions, not evidence that the exact revised pitch classifications or values were published before each 2023–2024 start. That limitation stays attached to every result and fitted artifact.

The source layers remain quarantined and not production-model eligible. The current work order authorizes a separate validated private research derivative; it does not change Bronze/Silver eligibility or register a production feature. Attribution: MLB Advanced Media / Baseball Savant, Retrosheet and Chadwick Bureau. Raw sources are not redistributed.

All A/B/C models use the same profile-supported training, temperature-fitting and assessment appearances. The clustering transform sees one row per training start, with style fields only. It receives no duration outcome, rest, workload or future appearance data. Imputation, scaling and Gaussian-mixture selection are learned in training and then applied unchanged, following the [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html).

The operational adapter must retain complete, eligible workload history as well as profile support. Protected future-history exceptions naming CURRENT_HGB do not cover this new component. Historical profile coverage therefore does not establish current deployment readiness. A research hazard lookup alone is not a simulated game or published forecast.

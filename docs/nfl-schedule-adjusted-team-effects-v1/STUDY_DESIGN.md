# Frozen study design

This design was frozen on 2026-09-17 before the experiment loaded any reused 2023–2024 score outcomes. The task estimates pass and rush offense/defense effects from prior opponents with a transparent ridge two-way model. It keeps the existing NFL M1 XGBoost score recipe fixed and adds only the declared feature blocks.

The source unit is one team-game. A target origin is an NFL season-week; all games in that week are excluded, including earlier games in the same week. Each fit uses only prior weeks and prior seasons whose game dates precede the earliest target date. Missing unit EPA remains missing. A team with no eligible history receives the league-centered ridge prior and explicit zero support rather than a fabricated observation.

The Development search is exactly four combinations: ridge alpha 10 or 50 and prior-season decay 0.50 or 0.75. One common setting is chosen by average pass/rush EPA RMSE over 2020–2022 Development origins. It is then frozen. Downstream variants are baseline, pass only, rush only, and pass plus rush. The 2023–2024 outcomes remain reused diagnostics.

The baseline is the exact 197-feature `NFL_M1_XGBOOST` research recipe, refit on strictly earlier seasons at each assessment origin. Its binary probability is a diagnostic proxy. The retained all-history artifact and the operational 10,000-draw three-way package are separate artifacts and cannot serve as historical out-of-sample predictions.

The JSON companion is authoritative for metrics, clustered bootstrap, diagnostic segments, and the advancement gate.

# Feature schema and lineage contract

All numeric predictors use EPA per play or dimensionless support quantities. Positive offense effects increase expected offensive EPA. Positive defense effects mean the named defense allowed more opponent EPA in the fitted response model.

## Pass block

- `home_pass_offense_effect`, `away_pass_offense_effect`: latent offense deviations.
- `home_pass_defense_effect`, `away_pass_defense_effect`: latent defense-allowance deviations.
- `pass_season_environment`: intercept plus target-season environment.
- `pass_home_venue_effect`: fitted offense-is-home coefficient.
- `home_pass_matchup_estimate`, `away_pass_matchup_estimate`: fitted EPA for each offense against the named opposing defense.
- `home_pass_matchup_advantage`, `away_pass_matchup_advantage`: matchup estimate less season environment.
- `pass_matchup_difference`: home estimate minus away estimate.
- `pass_residual_scale`: weighted training RMSE.
- Per side: current support, weighted support, shrinkage weight, and uncertainty proxy.

The rush block has the identical schema with `rush` replacing `pass`.

## Row lineage

Each row also carries game ID, season, week, home/away identity, feature origin time, latest source game/date for each unit, estimator configuration ID, and unit-specific training-population SHA-256. The external Parquet sidecar is bound by `FEATURE_LINEAGE.json`.

Source objects and physical hashes are frozen in `STUDY_DESIGN.json`. The target projection has SHA-256 `30737340c0b75d2c39ccd64a08137fbc77f766753cabbdc669902117df229427`. The team-game object has physical SHA-256 `11631f1cc5e74252f011aa553b84b84035272ea9f433ed057fc342427686e362`.

The sidecar has 6,447 rows, 40 numeric candidate predictors, seasons 2000–2024, and zero predictor missing cells. It is research-only and has no provider, publication, or production side effects.

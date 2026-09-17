# Schedule-adjustment methodology

For unit `u` in pass and rush, each eligible team-game response is fitted as:

`EPA_u = intercept + season environment + offense-team effect + opponent-defense effect + offense-is-home effect + error`.

The implementation uses `DictVectorizer` and `sklearn.linear_model.Ridge(solver="lsqr")`. A row from source season `s` receives weight `decay^(targetSeason-s)`. The Development grid was alpha `{10, 50}` by decay `{0.50, 0.75}`. One common configuration was selected by mean pass/rush RMSE across 2020–2022 Development origins. The locked choice is alpha 10, decay 0.50.

A target origin is `(season, week)`. Eligible source rows must be from an earlier season or an earlier week in the same season and must have `game_date` before the earliest target date. All same-week results are conservatively excluded. Fits include regular season and completed prior postseason games. Target assessment games are regular season.

Missing unit EPA rows are excluded from that unit fit. No zero replacement is allowed. Unseen teams receive a zero latent deviation from the ridge prior. The row records current-season support, weighted earlier support, `current/(current+8)` shrinkage weight, and `1/sqrt(weightedSupport+1)` uncertainty proxy. These are support diagnostics rather than posterior credible intervals.

The sidecar retains raw offense/defense effects, season and home effects, home and away matchup estimates, deviations from the season environment, matchup differences, residual scale, support signals, latest admitted game/date, estimator identity, and a deterministic hash of the fitted population.

Downstream assessment holds the 197 M1 predictors and XGBoost recipe fixed. Candidate feature blocks are pass, rush, or both. Each assessment season is refit from earlier seasons only. Calendar season-week blocks are resampled 2,000 times for paired intervals.

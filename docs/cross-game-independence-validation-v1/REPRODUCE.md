# Reproduction

Run from the source checkout with the existing Model Studio environment:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -B scripts\cross_game_independence_study.py `
  --nfl 'C:\Users\james\asp-data-staging\nfl\overnight-model-laboratory-v1\runs\matrix-fcc3cd9a5446-foundation-ebb6912919a5\pipelines\m1_recipe_fold_refit\oof_predictions.parquet' `
  --nfl-schedule 'C:\Users\james\asp-data-staging\nfl\bronze-v1\objects\schedules\all-seasons\schedules\asset=567593295\updated=95587c2bf9eb89e8\sha256=18d03fef3b91eb38472ed9f678bb11a9bfbec7b9a664dfce4c60ab247cbee9d3\games.parquet' `
  --nba 'C:\Users\james\asp-model-studio\outputs\nba-gen1-long-gap-v1\development\predictions.parquet' `
  --cfb 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-v1\data\season-forward-predictions.parquet' `
  --output '.tmp\cross-game-independence-results.json' `
  --created-at-utc '2026-09-16T17:46:00Z'
```

The replay file must have SHA-256 `fafc0b9bd9997e65fa6db209bceb6dacb91943528e136ed23603daf922ffef24`, matching `RESULTS.json` byte for byte.

Focused verification:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -m pytest -q `
  tests\test_cross_game_independence_study.py `
  tests\test_market_probabilities.py `
  tests\test_scotty_demo_release.py
```

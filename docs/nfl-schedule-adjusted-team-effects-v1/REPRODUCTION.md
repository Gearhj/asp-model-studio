# Reproduction

Use the Model Studio environment. Raw feature and prediction artifacts remain under `C:\Users\james\asp-model-studio\outputs\nfl-schedule-adjusted-team-effects-v1` and are not committed.

```powershell
Set-Location C:\Users\james\asp-model-studio-source-nfl-team-effects

# Development-only selection and all-origin feature sidecar. This stage loads no 2023/24 score outcomes.
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\assess_nfl_schedule_adjusted_effects_v1.py freeze-development

# Run only after DEVELOPMENT_SELECTION.json is frozen and committed.
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\assess_nfl_schedule_adjusted_effects_v1.py assess

# Focused integrity checks.
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\assess_nfl_schedule_adjusted_effects_v1.py verify
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -m pytest -q tests\test_nfl_schedule_adjusted_effects.py
```

The sidecar was independently generated twice with identical SHA-256 `c77cfe435832656892eddbd63230639cfb317e010ff32d4c1dff815c7bd160e8`. The assessment prediction Parquet was generated repeatedly with identical SHA-256 `2cd80180cee4cb9fffdf5a516cdd6d9682a99beca988a6761e396d83b89442db`. Runtime fields in JSON receipts are expected to vary; predictions, metrics, feature samples, and figures were identical.

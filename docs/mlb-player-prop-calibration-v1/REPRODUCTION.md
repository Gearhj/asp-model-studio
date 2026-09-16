# Reproduction

Run the focused source checks:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -m pytest `
  tests\test_mlb_v18_player_prop_sidecar.py `
  tests\test_mlb_v18_player_prop_calibration.py -q
```

Dry-run the retained MIA–AZ replay classification without writing an artifact or reading a result:

```powershell
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe `
  scripts\register_mlb_v18_player_prop_calibration_capture.py `
  --forecast-object C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1\objects\sha256\2f07648c51e830736d65ff37689c563bb2195ec767090d14ecc8e905968cbdac `
  --sidecar-object C:\Users\james\asp-model-studio-source-mlb-player-prop\outputs\mlb-v18-player-prop-sidecar-v1\objects\sha256\3259706deca700ac6d0ea1b8779eaae9fdbcc359612b69ad3168dd920924d3d4 `
  --model-training-end 2026-05-01 `
  --recorded-at 2026-09-16T23:00:00Z `
  --historical-feature-chronology UNCERTIFIED_HISTORICAL_FEATURE_CHRONOLOGY
```

Expected disposition: `RETROSPECTIVE_DERIVATION_ONLY`, `assessmentEligible=false`, and `writeDisposition=DRY_RUN_NO_WRITE`.

For a later future game, the existing owner must first run the already documented sidecar command before first pitch. Then run the registration command with that immutable forecast object, the new local sidecar object and the actual registration time. Supplying `--output-root` writes only a content-addressed local research declaration; it does not publish or schedule anything.

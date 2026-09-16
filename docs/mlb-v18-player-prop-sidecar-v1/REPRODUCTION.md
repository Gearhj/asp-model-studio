# Reproduction and verification

Use the repository's governed Python environment. The command below performs two complete 5,000-draw replays, so the retained reference runtime is about 12 minutes per population on the original host.

```powershell
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\build_mlb_v18_player_prop_sidecar.py `
  --forecast-object C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1\objects\sha256\2f07648c51e830736d65ff37689c563bb2195ec767090d14ecc8e905968cbdac `
  --pa-model C:\Users\james\asp-model-studio\outputs\mlb-v18-whole-game-challenger\sha256\a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27\executable\v18-pa-fold5.joblib `
  --transition-model C:\Users\james\asp-model-studio\outputs\mlb-v18-whole-game-challenger\sha256\a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27\executable\transition-fold4.json `
  --output-root outputs\mlb-v18-player-prop-sidecar-v1 `
  --created-at 2026-09-16T22:23:51.6357333Z `
  --threads 4
```

Reusing that exact creation time and the unchanged authenticated inputs must return `REUSED_BYTE_IDENTICAL` with sidecar SHA-256 `3259706deca700ac6d0ea1b8779eaae9fdbcc359612b69ad3168dd920924d3d4`. A new actual creation time intentionally creates a distinct sidecar identity.

Focused tests:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -m pytest tests\test_mlb_v18_player_prop_sidecar.py -q
```

The replay script authenticates original object members and executable hashes before model deserialization, reconciles counters-disabled and counters-enabled populations, reconciles against the saved forecast population and summaries, verifies the sidecar after serialization, and writes only the local research output tree.

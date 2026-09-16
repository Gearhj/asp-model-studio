# Prospective cross-game evidence v1

This directory documents an inactive, no-network evidence contract. Start with [REPORT.md](REPORT.md), then review:

- [dependency vocabulary](DEPENDENCY_VOCABULARY.md);
- [frozen-gate binding](FROZEN_GATE_BINDING.md);
- [retention and correction rules](RETENTION_AND_CORRECTION_RULES.md);
- [producer integration matrix](PRODUCER_INTEGRATION_MATRIX.md);
- [calibration dispositions](CALIBRATION_DISPOSITIONS.json);
- [Claude handoff](CLAUDE_HANDOFF.md);
- JSON Schemas in `schemas/`; and
- synthetic fixtures in `fixtures/`.

Build deterministic fixtures:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -B `
  scripts\build_prospective_cross_game_evidence_fixtures.py `
  --output .tmp\prospective-cross-game-fixtures
```

Validate a pre-outcome fixture:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -B `
  scripts\validate_prospective_cross_game_evidence.py `
  --kind PRE_OUTCOME `
  --record docs\prospective-cross-game-evidence-v1\fixtures\pre-outcome.json
```

The scripts perform no network, provider, database, exchange, AISP, model or scheduler operation.

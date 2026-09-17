# Reproduction

## Environment

Run from the clean source worktree with the deployed checkout left read-only:

```powershell
Set-Location C:\Users\james\asp-model-studio-source-nfl-cfb-nba-readiness
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -m unittest tests.test_nfl_cfb_nba_feature_readiness_v1 -v
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\nfl_cfb_nba_feature_readiness_v1.py
```

The runner accepts `--input-dir` only to support an explicitly supplied mirror. It still requires the exact SHA-256, row count, season ceiling and schema declared in `STUDY_DESIGN.json`. It fails closed on altered bytes, duplicate IDs, dates on or after 2026-01-01 UTC, or retained CFB/NBA feature-source dates at or after target time.

## Exact inputs

| Sport | Rows | SHA-256 |
|---|---:|---|
| NFL | 6,695 | `30737340c0b75d2c39ccd64a08137fbc77f766753cabbdc669902117df229427` |
| CFB | 7,744 | `03f33aee8e8882f71e87dd20267f51c339dce7bb91c1063290dc86e508d3458b` |
| NBA | 6,952 | `680ffe438bed958456743993b9f20a05ac2f0b04a6d07bc235aa842a1a27277a` |

Paths and byte counts are in `BOUND_INPUT_RECEIPT.json`. Raw and model artifacts remain outside Git under their existing permissions. Only aggregate results and figures are committed.

## Determinism and scope

The seed is 9,172,601. Model thread pools are limited to one. The NFL model uses the frozen repository configuration and seed 731001. Calendar-week bootstrap uses 2,000 replicates. Plot sampling is aggregate/deterministic; row-level evidence is not retained.

Expected runtime on the verified local environment is about 2.5 minutes (153.466 seconds in the retained replay), dominated by 15 NFL fixed-recipe fits. The focused unit suite covers chronology primitives indirectly through the guarded runner plus direct tests for support-bounded shrinkage, participant orientation, explicit missingness, deterministic week bootstrap and tie handling. The final replay compared 38 generated machine results and figures byte for byte; none changed.

`artifact-index.json` records physical SHA-256 and byte count for every committed report, JSON output and figure. Physical hashes are artifact integrity values, not model identities.

## Non-actions

Reproduction makes no network request, provider call, AISP write, exchange publication, scheduler change or production-owner mutation. It does not deserialize or overwrite current production models. It must not be pointed at current-season outcome snapshots, sealed data or Final OOT payloads.

# Development-only Ridge gap diagnosis

All nine negative expectations are HOME scores in the 2021 season-forward fold. The original 968-game model and all 78 saved feature inputs reproduce them exactly at the original fold batch size; no fit, correction or new performance comparison was run.

| Date | Away at home | Original home / away expectation | Home / away recorded gap | Rest-term home contribution |
|---|---|---:|---:|---:|
| 2020-12-22 | LAC at LAL | -0.664 / 102.806 | 130 / 129 days | -112.960 points |
| 2020-12-23 | ATL at CHI | -136.224 / 96.115 | 287 / 286 days | -250.242 points |
| 2020-12-23 | MIL at BOS | -2.061 / 103.968 | 131 / 131 days | -113.363 points |
| 2020-12-23 | CHO at CLE | -136.077 / 97.587 | 287 / 286 days | -250.242 points |
| 2020-12-23 | DAL at PHO | -2.687 / 101.417 | 131 / 131 days | -113.363 points |
| 2020-12-23 | DET at MIN | -138.182 / 91.420 | 287 / 286 days | -250.242 points |
| 2020-12-23 | SAS at MEM | -1.593 / 102.200 | 131 / 131 days | -113.363 points |
| 2020-12-23 | MIA at ORL | -1.935 / 107.580 | 131 / 130 days | -113.835 points |
| 2020-12-23 | UTA at POR | -1.451 / 100.140 | 131 / 131 days | -113.363 points |

The first-fold observed training support is 0–8 HOME days and 0–9 AWAY days. The two direct gap coefficients contribute −0.676 HOME points per HOME gap day and −0.198 HOME points per AWAY gap day, before the separate difference term. The nine scored rows contain 129–287-day gaps. Prior dates and arithmetic reconcile; gaps are days since the preceding retained regular-season game, not verified physical rest because excluded competitions may intervene.

Development includes no observed gap from 13 through 128 days. Its 22 within-season long-gap team exposures are neutral 2020 restart games, which remain history but never enter the oriented fitting cohort. Other long gaps occur at season opening. This explains why the first-fold scaler never learned their range.

The supported next test is one symmetric training-only ordinary-calendar-rest availability rule. Estimate its upper support bound from pooled HOME/AWAY known nonopener training gaps. Mark season-opening or out-of-envelope rest inputs unavailable, update rest_known/back_to_back consistently and recompute the rest difference with missingness preserved. Retain raw gaps and reasons in the audit. The bound comes from training inputs, not selected miss scores. Do not clip predicted scores or invent a learned hiatus effect.

Full inputs, units, scaler/coefficients, training ranges, preceding-game identities and all 78 contribution terms for each game are in `nine-negative-ridge-diagnosis.json`. Contributions are additive accounting, not causes. Maximum absolute contribution-sum error: 8.53e-14 points; fitted-artifact forecast reproduction is exact at original batch size.

Only original Development files were opened. Validation, holdout and 2026 outcomes were not accessed. Original source/features/models/predictions and prior diagnosis remain unchanged.

Run the following command to create this additive evidence; it refuses to overwrite an existing output:

```powershell
.venv/Scripts/python.exe -B outputs/nba-gen1-long-gap-v1/diagnosis/diagnose_development.py
```

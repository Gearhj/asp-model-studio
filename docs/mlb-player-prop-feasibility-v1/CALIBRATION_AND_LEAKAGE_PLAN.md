# Calibration and leakage plan

No model is selected or promoted by this audit. Existing PA calibration is not player-prop calibration.

## Admissible design

1. Register Development and Validation seasons/dates before reading player-prop results. Keep Final OOT sealed and apply the permanent whole-game quarantine to identity metadata before any future authorized OOT access.
2. For each target game, use the fold-correct V18 model and only timestamped evidence available before its forecast cutoff: schedule revision, announced starters, confirmed ordered lineups and pregame feature histories.
3. Generate the full game from those pregame inputs. Never use actual PA count, actual batting order changes, actual relievers, substitutions, postgame participation or target-game aggregate statistics as forecast inputs.
4. Retain named per-draw statistics and score the official observed statistic only after the game is final under a governed revision. Games, not simulation draws, are the assessment units.
5. Freeze stat definitions, participation eligibility, missing-evidence fallbacks and block bootstrap plan before Validation scoring.

## Metrics

- Binary thresholds such as 1+ hit or HR: log loss, Brier, reliability/ECE, calibration intercept/slope and AUC. AUC measures discrimination, not calibration.
- Integer totals such as TB or starter Ks: CRPS or ranked probability score for the full count distribution, mean absolute error and central interval coverage.
- Report coverage and missing-participant disposition, batting-slot/support bands and starter-removal exposure bands.
- Use game-date or calendar-week blocks for paired uncertainty. MCSE describes 5,000-draw numerical precision only and is not predictive uncertainty across games.
- Compare with sportsbook prices only in a separate study using time-compatible captured quotes and exact settlement rules. Profitability, CLV and no-vig disagreement are not calibration evidence.

## Existing evidence that is insufficient

- PA-level chronological OOF predictions can audit class probabilities conditional on recorded PAs, but actual PA membership and exposure are already known there.
- Oracle whole-game replays use actual substitutions and pitcher sequences.
- Population diagnostics condition on simulated paths rather than actual observed PAs.
- Final lineups or postgame box scores acquired after the historical cutoff cannot certify what was known pregame.

## Leakage checks

Reject any row or game where target outcomes, actual participation, later lineup revisions, later starter changes, actual relievers, later feature aggregates or closing prices enter construction. Group folds by game date. Fit calibration only inside Development/Validation chronology. Preserve all inspected later periods as reused evidence; do not call them untouched confirmation.

# Frozen initial Development limits

The initial symmetric limits are **5 runs per team per played half-inning** and
**14 runs per team per game**, frozen at **2026-09-13T16:36:39.181644+00:00**.
An entire original simulated game is excluded only when a limit is strictly
exceeded. Equality is accepted. Neither accepted scores nor sequences change.

The source is the existing governed FD1 Retrosheet `play_transition` family,
semantic manifest `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`.
The existing transition contract declares Development 2021–2023. The FD1 source
labels 2021–2022 prior-only history; these records are used here as a historical
scoring prior, not same-game pregame features. No 2024 validation, 2025 retired,
2026 Final OOT, September 12 outcome, or forecast-performance data enter the
quantiles.

The retained population contains 7,267 games from April 1, 2021 through October 1,
2023: 2,421 / 2,419 / 2,427 by season. It supplies 128,887 actually played half-innings
and 14,534 team-game scores. Both linear 99th percentiles are already integers,
5 and 14; rounding upward does not change them. The settings are not optimized.

All 568,472 retained play records contribute their runs, including 21,722 non-PA
plays and their 1,105 runs. Zero-run played halves and natural walkoff halves count;
unplayed home halves do not. There are 120 completed seven-inning games, 648 games
that went beyond their scheduled regulation, and 15 suspended games subsequently
completed. Of 7,289 candidate games, 22 are excluded as whole games: two fail
score-delta reconciliation and 20 lack the required natural regulation-or-later
terminal. This conservatively excludes shortened games without a separately
certified completion rule. No game matches the permanent quarantine.

Each included game's run deltas, source score continuity, completed interior
halves, terminal state, and two team totals reconcile. A separate reconstruction
of each quantile from the retained integer histograms reproduced both limits.
The old replay Markdown contract reverses `top_bottom`; the existing replay code
and all score deltas establish the actual source convention, 0=away/top and
1=home/bottom. The first derivation attempt failed closed on this discrepancy,
before calculating a quantile; correcting that mapping did not change the
declared cohort or introduce performance selection.

The immutable selection receipt also discloses that reading an old published
replay summary unexpectedly displayed previously published 2024/2025 sample
results. No value from that summary enters this derivation, and no raw partition
for either year was opened.

`current.json` binds the immutable rule, pre-outcome metadata selection, and
source accounting. All 22 selected Parquet partition hashes and 53,062,393 local
bytes match the governed manifest. Provider requests, downloaded bytes, and
cost are all zero.

Reproduce or reuse the frozen declaration:

```powershell
.venv/Scripts/python.exe -B scripts/derive_mlb_v18_score_limits_v1.py
```

The information used here was obtained free of charge from and is copyrighted
by Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org.
ASP transformation: pooled historical scoring quantiles on the stated
Development cohort. Includes identity evidence from the Chadwick Baseball Bureau
Persons Register under the ODC Attribution License. These are private research
artifacts; inherited V18 chronology remains uncertified.

# FiveThirtyEight source admission for NBA Gen 1 historical pilot

Admit the official **FiveThirtyEight NBA Elo historical dataset** for a reduced-feature **Category A** research pilot, subject to identity/score validation. The [publisher dataset documentation](https://github.com/fivethirtyeight/data/tree/master/nba-elo) identifies real game records and attributes game information to Basketball-Reference. This is a publisher download; it does not call Basketball-Reference or a paid provider.

The [repository README](https://github.com/fivethirtyeight/data/blob/4c1ff5e3aef1816ae04af63218015066e186c147/README.md) expressly applies **CC BY 4.0 to datasets** unless otherwise noted. The NBA directory has no contrary notice. The [retained dataset license](source-review/dataset-LICENSE) permits reproduction and adaptation. Internal statistical model development can proceed under these published terms; a bespoke permission document is unnecessary. The software MIT license is not the basis for data rights.

If sharing licensed/adapted material, retain attribution and license notices, identify modifications and do not imply endorsement. No separate prohibition on model-derived forecasts was found. Publication rights and prospective evidence eligibility are different matters: this archive does not establish a current schedule or contemporaneous pregame availability.

Download once from:

`https://raw.githubusercontent.com/fivethirtyeight/data/6d880e939ad3d11d94c137c911681b3cf718fd74/nba-elo/nbaallelo.csv`

Git blob SHA-1: `6d6ccd07151aed322e1a77c57ea83b8ea58c5523`; expected physical size **18,173,265 bytes**. One anonymous HTTPS request, **$0** incremental cost; cap **20,000,000 bytes**. No account, trial, sports-provider credit or purchase. The CSV was not downloaded during this review. Two successful metadata probes preceded four retained metadata/document requests (91,512 retained bytes); bytes for those first two responses were not measured. A sandbox connection attempt failed without a response. Dataset request/byte usage belongs to the subsequent acquisition receipt.

Documented metadata supplies stable game IDs, league/season/date, team and franchise IDs, playoff flags, mirrored team rows and H/A/N orientation. Final game points support full-game point and winner models. The original publisher Elo values and forecast probabilities will be excluded from our features; our chronological Elo must be recomputed.

Exact season counts are to be established from identity-only columns before model roles are registered and score columns are parsed. The file's December 2022 newline-format commit is a source revision, not a game information-availability timestamp. Preserve actual acquisition time; never assign fabricated historical publication clocks. Exclude targets, same-day ambiguities and later games from rolling state according to the declared contract.

Unsupported: team boxes/possessions, scheduled tipoff clocks, per-game historical availability/revision vintages, explicit cancelled/rescheduled lineage, overtime-period scores and current/future schedule. Therefore richer feature models, the proposed empirical overtime simulator, and Categories B/C remain outside this archive's support. These gaps need not block point/Elo fitting.

Attribution for retained and transformed data: **Game data published by FiveThirtyEight, with game-information provenance credited to Basketball-Reference.com; licensed CC BY 4.0. ASP Model Studio filters regular-season records, reconciles identities, reconstructs chronological features and fits independent research models. No publisher endorsement is implied.**

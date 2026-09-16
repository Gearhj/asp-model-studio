# Recent NBA source admission

Admit **Neil Paine's NBA-elo archive** for Category A reconstructed historical research, subject to the metadata, identity, score, and scope checks below. This extends the completed FiveThirtyEight pilot without reopening its approval. No current-season or prospective certification is implied.

## Bounded source options

1. The official FiveThirtyEight [NBA forecasts data directory](https://github.com/fivethirtyeight/data/tree/4c1ff5e3aef1816ae04af63218015066e186c147/nba-forecasts) links a historical NBA Elo CSV. Its existing dataset CC BY 4.0 approval remains intact. A metadata-only HEAD probe of the old CSV URL now follows redirects and returns `text/html`, with ABC News response headers, rather than an identifiable CSV asset. No game-data body was acquired from this endpoint. This is an endpoint availability finding, not a revocation of its data license.
2. [Neil Paine's data archive](https://github.com/Neil-Paine-1/NBA-elo/tree/9a485bacef9f18f6a8e3ec671f13b9609386f0fa) explicitly describes itself as NBA Elo data updated from FiveThirtyEight. It is a repository of CSV datasets and associated documentation, not an API client. The root [MIT license](https://github.com/Neil-Paine-1/NBA-elo/blob/9a485bacef9f18f6a8e3ec671f13b9609386f0fa/LICENSE.txt) is the publisher's repository license. Applying that license to the data archive permits retaining, processing, adapting, and internally modeling its contents. This application follows the repository's data-only scope; it does not rely on a separately licensed client library. Preserve Neil Paine's notice and the original FiveThirtyEight CC BY 4.0 attribution for upstream material. No contrary dataset-specific notice or separate prohibition on derived forecasts was found. No third source was checked.

## One selected export

`https://raw.githubusercontent.com/Neil-Paine-1/NBA-elo/9a485bacef9f18f6a8e3ec671f13b9609386f0fa/NBA%20Elo%202025%20-%20nba_elo.csv`

Expected physical size: **15,487,867 bytes**. Git blob SHA-1: **4752ac88d1d5e62c430914767e4e56d91560a5df**. Root repository revision: `9a485bacef9f18f6a8e3ec671f13b9609386f0fa`. Selected file's latest revision: `37db89481b02cbdf5f7d0bc1e41271ebb11bd283`, committed **2025-04-14T22:31:06Z**. This revision clock is not a game-level historical publication clock.

The similarly named `nba_elo.csv` is older: its last file update was March 18, 2025. Its 15,618,762-byte size must not be mistaken for the selected April export. Neither source offers verified 2025–26 coverage; exact admitted seasons and dates must be established from the selected export's metadata before outcomes are assessed.

The authorized next intake is **one anonymous HTTPS GET**, exact expected size above, hard cap **17,000,000 bytes**, **$0** incremental cost. No account, trial, subscription, sportsbook credit, or vendor contact is involved. Preserve physical bytes, SHA-256, Git blob hash, actual capture time, and source revision. Do not reset or repurpose previous accounting: the completed pilot's one 18,173,265-byte data download remains separately recorded. If this export passes, cumulative NBA corpus acquisition will be two downloads and **33,661,132 bytes**, excluding documentation/metadata traffic.

## Analytical intake conditions

- Inspect header and only identity/scope metadata before registering chronological roles. Do not import publisher pregame or postgame Elo, RAPTOR, probabilities, or ratings as model inputs.
- The FiveThirtyEight format documents date, season, neutral/playoff markers, team1/team2 and final score1/score2. Confirm the actual selected header. No team-box fields, original scheduled tipoff clocks, historical revision vintages, or period/overtime records have been established from documentation. Do not assume they exist.
- Team1's home orientation needs validation. Reconcile overlapping old seasons against the preserved pilot's explicit H/A records using date and unordered team pair. Document aliases and any disagreement. A neutral game's team1 axis is not an actual home designation.
- If there is no native game ID, use a versioned source-specific identity from the date and stable team pair, assert uniqueness, and retain row/source bindings. Do not claim an NBA API game ID or a complete postponement/reschedule ledger.
- Regular-season scope must explicitly exclude the NBA Cup championship games, even if their playoff marker is empty: **2023-12-09 IND/LAL** and **2024-12-17 MIL/OKC**. The NBA explains that the championship does not count toward regular-season records or statistics: [2023 pregame explanation](https://www.nba.com/news/lakers-pacers-in-season-tournament-championship-3-storylines), [2024 official schedule explanation](https://www.nba.com/news/starting-5-aug-14-inside-the-emirates-nba-cup-2024-schedule). These are metadata exclusions, not score-driven selection. Cup semifinals remain regular-season games, subject to explicit neutral-site handling.
- Calendar date supports Category A earlier-day reconstruction only. Preserve same-day exclusion, unknown historical publication vintages, and actual present acquisition clocks. Do not create synthetic historical tipoff/publication timestamps.
- Publicly licensed final-score data can support the reduced league/Elo/Ridge/HGB screen. Its acquisition does not establish contemporary personnel inputs, a 2026–27 schedule, prospective eligibility, or the proposed period-based joint simulator.

Attribution for retained/derived records: **NBA game data published in Neil Paine's NBA-elo archive, updated from FiveThirtyEight, whose original game-information provenance credits Basketball-Reference. Neil Paine's MIT notice and upstream FiveThirtyEight CC BY 4.0 attribution are retained. ASP Model Studio filters identities and scope, reconstructs earlier-day features, and fits independent research models. No publisher endorsement is implied.**

Seven direct GETs retained metadata/documentation; one logical HEAD probe checked the former FiveThirtyEight CSV and followed redirects. Browser search/document reads are separate metadata review with unmeasured transport bytes. There were no game corpus downloads in this source-review subtask. Exact retained documentation checksums and byte accounting are in `source-review.json`; subsequent corpus acquisition belongs to its own receipt.

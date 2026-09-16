# College Football Gen 1 source review

Decision: ADMITTED_FOR_PRIVATE_RECONSTRUCTED_HISTORICAL_RESEARCH.

The retained SportsDataverse population contains 50 exact parquet assets, 4,272,150 acquired bytes across 63 requests, and $0 incremental cost.

Schedules, team boxes, season-aware team identities and small period-score assets reconcile sufficiently for the bounded baseline. The retained data-hub evidence states CC BY 4.0 treatment with attribution. Producer software metadata is separately licensed; its software license is not treated as an independent grant for upstream ESPN-derived fields. This pilot is private research only, and display or redistribution remains unapproved.

The source has 10,819 schedule rows and 259 distinct team IDs. The primary population contains 139 team IDs. All final games with retained linescores through 2025 reconcile (10,470/10,470), including 427 overtime games.

The apparent duplicate is explicitly resolved: ESPN game 400767534 (Illinois-Kent State) is postponed at 01:00Z on 2015-09-05; game 400835430 is the distinct 18:00Z final, 52-3. Only the final enters the primary population.

The source files were acquired now from finalized historical releases. They do not establish historical pregame publication vintages, so all historical results are evidence class A. Exact conference-championship and bowl-versus-playoff subtypes are absent. Week 15+ regular-season rows are withheld rather than guessed.

The 2026 schedule asset contains 185 rows and 84 finals, but zero kickoffs after the 2026-09-14T21:01:47.277922+00:00 capture. It is a partial current-season asset, not a complete 2026 schedule.

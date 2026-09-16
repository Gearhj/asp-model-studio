# V19 source-backed forward evidence

This isolated addition closes a calculation gap, not a historical-vintage gap. It does not modify the frozen V18 vector, scheduled publisher, original forecasts, AISP, or any fitted model. No performance improvement is claimed for these new source fields.

## Implemented

`server/sports_current_statcast/mlb_v19_source_evidence.py` verifies immutable single-day MLB schedule and Statcast captures before deterministic derivation. It supports:

- Player recorded-pitch events, pitch-bearing appearances, and calendar days with pitches over the prior 1, 3, and 7 official calendar dates.
- Calendar days since the latest observed recorded pitch, with explicit bounded-window uncertainty. Actual recovery hours and pitcher availability remain null.
- Team recorded-pitch workload, separately identifying nonopening pitchers. An opening recorded pitcher is an observation of the completed game, not a pregame announced-starting-pitcher vintage.
- Latest observed selected-staff batches, preserving superseded player observations without inferring release, injury, or present eligibility.
- Original starter/lineup observation clocks and their ages at the original evidence cutoff. Probable starters remain probable.
- Prior completed-game schedule spacing and reviewed venue-centroid distance. These remain start-to-start and travel proxies, not actual recovery/travel measurements; this is already a V18-supported family, not a newly discovered improvement.
- Content-addressed immutable supplements, source byte/hash verification, exact unchanged reruns, and explicit predecessor support for corrections.

`scripts/build_mlb_v19_source_evidence.py` constructs the bounded September 10 demonstration. It is not a collector and does not install any recurring operation.

## Actual bounded execution

The builder reused 14 existing immutable capture receipts and 19,873,522 raw source bytes for September 3–9. All seven schedule/Statcast game-ID reconciliations were complete: 96 completed games, 28,155 source rows, 28,074 recorded pitch events, 81 automatic ball/strike events excluded, and zero duplicate rows. Unclassified pitch types remain included. Official box-score pitch totals have not independently been verified.

There were **zero provider requests, zero downloaded bytes, $0 source cost, zero model fits, zero sealed-payload reads, and zero original-forecast changes** in this work. No August 14–27 raw data was opened; the earlier operational-only source exception was not used.

The seven-day captures were actually retrieved on September 10, before the original COL–NYY and PIT–CWS forecasts. Their source availability is not retroactively assigned to September 3–9. The supplements themselves were calculated later and are not forecasts purportedly published before first pitch.

| September 10 probable starter | Recorded pitches, prior 7 days | Pitch-bearing appearances | Calendar days since observed pitch |
|---|---:|---:|---:|
| COL Ryan Feltner, 663372 | 95 | 1 | 6 |
| NYY Max Fried, 608331 | 72 | 1 | 6 |
| PIT Jared Jones, 683003 | 91 | 1 | 6 |
| CWS Hagen Smith, 696146 | 61 | 2 | 4 |

All four had zero recorded pitches in the prior 1 and 3 calendar days. This is known-zero **recorded pitch exposure in the complete observed window**, not no career history, no warmup work, or proof of health/availability.

| Team | Nonopening-pitcher recorded pitches, prior 1 day | Prior 3 days | Prior 7 days | Latest observed selected nonstarter pool |
|---|---:|---:|---:|---:|
| COL | 33 | 96 | 327 | 8 |
| NYY | 40 | 74 | 213 | 8 |
| PIT | 127 | 166 | 444 | 8 |
| CWS | 76 | 194 | 470 | 7 |

The original CWS selected pool also contained player 699823 with a September 9 roster observation. The latest other CWS observations were September 10. The supplement preserves that older row as `SUPERSEDED_OBSERVATION_CURRENT_MEMBERSHIP_UNKNOWN`; it neither mutates the V18 forecast nor silently awards current membership. This selected pool is not a complete active roster or a verified bullpen-availability list.

Both games used confirmed lineups and probable starters. At the original capture, lineup/starter observation ages were about 0.46/0.47 minutes for COL–NYY and 0.93/1.04 minutes for PIT–CWS. Legacy ingestion-clock values are retained separately, including cases where AISP's recorded ingestion clock precedes source observation; no clock is repaired or relabeled.

## Scientific eligibility and missing families

New workload/confirmation/roster fields are **not admitted to historical Development training or evaluation**. The existing original captures prove availability for those September 10 games only. A current download of older history does not establish the historical injury, transaction, starter, lineup, or weather state. A forward archive can make future evaluation possible, but no recurring archive is installed by this assignment.

Still unsupported: actual bullpen availability, complete transaction history, injuries/return-from-absence, actual game end/recovery time, warmup/bullpen-session loads, contemporaneous game-time weather/roof/umpire authority, independently verified official pitch counts, and historical publication vintages for the new current-state sources. No synthetic values, median/mode values, or source-failure-to-zero conversion were introduced.

Restrictive source authority is retained: `LOCAL_PRIVATE_MODEL_DEVELOPMENT`, MLB Statcast `GOVERNED_LOCAL_RESEARCH_ONLY`, attribution, commercial-rights review, and no public raw redistribution. No additional rights were inferred.

## Final source package

`outputs/mlb-v19-current-state-specialists-v1/source-evidence/sha256/16fbc59e7ff99e44bde5b30433ee548b39e9430aaaade003c8c2eca6b07300c6/source-package.json`

SHA-256: `16fbc59e7ff99e44bde5b30433ee548b39e9430aaaade003c8c2eca6b07300c6`.

The package references both game supplements, all derived captures, original immutable raw receipts, original operational audit, and implementation checksums. Earlier local construction receipts remain unchanged. Repeated derivation returned identical supplement identities and bytes.

Focused verification: `tests/test_mlb_v19_source_evidence.py`, **5 passed** in the supported Windows execution context. Checks cover source-gap versus known-zero distinction, exact rolling counts, future/sealed rejection before payload access, original cutoff enforcement, selected-roster supersession, immutable reruns, home/away pitch orientation, automatic-pitch-event exclusion, and residual/unclassified pitch retention. An initial sandbox temporary-directory access failure was an execution-context failure, not a statistical/model result; no access control was changed.

Next scientific use: maintain these fields as separately timestamped forward evidence until sufficient truly prospective vintages exist. Do not imply they affected frozen V18 or this study's historical candidate metrics.

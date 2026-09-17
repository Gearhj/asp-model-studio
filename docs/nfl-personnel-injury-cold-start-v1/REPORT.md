# NFL quarterback, personnel and injury evidence foundation

## Outcome

**INSUFFICIENT_ADMISSIBLE_EVIDENCE.** The requested historical challenger was not run. Retained nflverse snapshots support an identity-safe contract, descriptive coverage audit, strictly prior helpers and an inactive prospective capture path. They do not preserve the physical historical release vintages needed to prove the target-game expected quarterback, roster/depth state and injury revision before kickoff.

## Evidence inspected

- Injury reports: 84,684 rows, 2009–2024 in the admitted audit.
- Weekly rosters: 859,529 rows, 2002–2024.
- Depth charts: 869,185 rows, 2001–2024.
- Snap counts: 297,999 rows, 2012–2024; target-game values prohibited.
- Player and draft identity tables were inspected only for crosswalk/static fields. Career outcome fields in the draft table were excluded.
- Game schedule columns supplied identity, orientation, week, date and time only. Score/outcome columns were not loaded.

## Main findings

1. `date_modified` gives useful injury-row timing but no immutable release-vintage proof. Current assets can contain later corrections.
2. Weekly rosters and depth charts lack a retained append-only publication/revision chain for old cutoffs. An official upstream issue asking about contemporaneous roster vintages remains unanswered.
3. Prior-game snaps and player performance can be used only after completion and a conservative publication boundary. They cannot identify the target-game starter.
4. Existing M1 already models lagged team passer usage. This work adds the missing evidence semantics; it does not relabel that mixture as current-quarterback identity.
5. Identity resolution is exact-ID only. Name collisions, trades and legacy team aliases are measured and fail closed where ambiguous.
6. Existing schedule data contains venue and weather fields, but weather remains outside this experiment and unchanged.

## Implemented

- Immutable pregame personnel record with source/effective/retrieval/cutoff clocks, revision predecessor and physical row digest.
- Append-only correction validation, exact-ID resolution, explicit injury/availability vocabulary and eight distinct missingness states.
- Strictly prior quarterback-performance shrinkage helper, cold-start semantics and target-game snap rejection.
- Seven-request, 64 MiB inactive 2026 capture plan with 2 GiB retained ceiling and content-addressed raw bytes outside Git.
- Deterministic outcome-free audit and six SVG evidence figures.

## Historical experiment

No assessment results exist. The gate failed before 2023–2024 outcomes were read. This is not `NO_INCREMENTAL_VALUE`; predictive value remains unknown.

## External activity

Official public documentation was read through the browser. The browser tool does not expose physical response byte counts, so those bytes are recorded as unavailable rather than invented. No authenticated provider request, artifact download, sportsbook call or paid request occurred; cost was $0. The capture planner executed in dry-run mode only.

## Next dependency

Activate the prospective capture under a separately authorized existing NFL owner, preserving pre-cutoff revisions for expected quarterback, injuries, roster and depth. After enough supported 2026 game-weeks accrue, freeze the fixed M1 block comparison before outcomes.

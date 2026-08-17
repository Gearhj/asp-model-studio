# MLB_PA_FEATURE_VIEW_V1

## Status

`BLOCKED_IDENTITY_BRIDGE_REQUIRED — NOT MATERIALIZED`

The finalized `asp.mlb.open-data.fd1` package does not contain a package-bound identity bridge from plate-appearance Retrosheet player identifiers to the canonical UUIDs used by `player_prior`. FD1 remains frozen and valid as published. The feature view must not be constructed until a separately immutable `SPORTS_IDENTITY_BRIDGE_V1` companion, bound to the FD1 manifest, supplies that authority.

## Intended target and row authority

- Target family: `plate_appearance`
- Target field: `outcome`
- Group key: `game_id`
- Time key: `game_date`
- Row identity: `plate_appearance_id`
- Join-only identities: `batter_id`, `pitcher_id`
- Development seasons: 2023–2025 rolling-origin folds

The immutable probability-vector order is:

1. `STRIKEOUT`
2. `WALK_HBP_CI`
3. `HOME_RUN`
4. `SINGLE`
5. `DOUBLE`
6. `TRIPLE`
7. `BIP_OUT`
8. `OTHER_REACH`

No component may alphabetize or otherwise reorder these classes.

## Intended eligible evidence

Only package-bound, point-in-time-proven Y−1-or-earlier `player_prior` evidence may become predictors:

- BATTING-domain prior metrics for the batter;
- PITCHING-domain prior metrics for the pitcher;
- explicit missing-batter-prior and missing-pitcher-prior indicators;
- training-population-only imputation values.

The package exposes no validated batter handedness or pitcher-hand field. No game-state context is included because every available inning/base/out/score field is classified `RETROSPECTIVE_ACTUAL_NOT_PREGAME_SAFE`.

## Absolute exclusions

The following are target, timing-risk, identity-only, grouping-only, or provenance fields and may not be model predictors:

- `outcome` and all target-derived or terminal-result fields;
- `terminal_play_id`, `terminal_play_number`, `source_terminal_token`;
- `outs_after`, `base_mask_after`, `runs_scored`;
- `inning`, `top_bottom`, `outs_before`, `base_mask_before`, `visiting_score_before`, `home_score_before` in FD1, because their pregame/simulation availability is not proven;
- actual lineup, starter, reliever-usage, or untimestamped actual-weather evidence;
- `game_id`, `plate_appearance_id`, canonical player IDs, batter IDs, and pitcher IDs as model features;
- source keys, versions, checksums, partitions, manifests, rights controls, and logical URIs;
- same-season annual priors, later events, same-game cumulative results, future-season totals, market data, odds, closing lines, and CLV.

## Required preprocessing boundary

If the contract is unblocked, every fold must fit numeric imputation, feature order, scaling, and any interaction construction on its training portion only. Rookie/missing-prior values must use training-population means with explicit indicators. Same-date games remain grouped, and no random split is permitted.

## Blocking evidence

For all primary-fold plate appearances, `batter_id` and `pitcher_id` use unresolved `retrosheet:player:*` identities. `player_prior.canonical_player_id` uses unrelated UUIDs, `player_prior.player_id` is null, and `lahman_player_id` belongs to another namespace.

Exact Y−1 membership joins are:

| Target season | PA rows | Batter-prior matches | Pitcher-prior matches |
|---|---:|---:|---:|
| 2023 | 184,104 | 0 | 0 |
| 2024 | 182,449 | 0 | 0 |
| 2025 | 182,926 | 0 | 0 |

The manifest references an `active_identity_evidence` logical artifact, but its crosswalk bytes are not part of the exact 335-file package. A checksum or aggregate claim cannot reconstruct the mapping.

## Minimum immutable companion authority required

A `SPORTS_IDENTITY_BRIDGE_V1` companion must bind itself to FD1 manifest SHA `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49` and contain the compact active 2021–2025 player identity spine. Each row must carry the canonical player UUID and exact source-version-bound Retrosheet, Lahman, Chadwick, and available MLBAM identifiers, together with mapping status, confidence, rights controls, source versions, and a row checksum.

The companion must prove exact one-to-one coverage of every 2023–2025 plate-appearance batter and pitcher identifier and joinability to every relevant `player_prior` canonical UUID. It must reject duplicate or conflicting source identifiers, use no name-based matching, and preserve genuine rookies without eligible prior evidence as missing-prior cases rather than identity failures.

Do not modify `SPORTS_DATASET_MANIFEST_V1` or the finalized FD1 package. Once the companion is registered and validated, Milestone B may resume from the existing dataset registration without repeating Milestone A or the complete FD1 hash scan unless an FD1 file changes. Until then, Candidates 1–3, preprocessing artifacts, fold predictions, calibration, bootstrap evidence, and a model-registry decision remain absent by design.

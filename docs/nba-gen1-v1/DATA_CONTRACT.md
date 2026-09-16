# NBA Gen 1 real-population contract

**No conforming real index has been delivered or registered.** This document specifies the offline interface implemented by [authority.py](C:/Users/james/asp-model-studio/server/sports_nba_gen1/authority.py). It is not evidence that any source is licensed, real or timestamp-qualified. Test fixtures exercise parsing only and must never enter this interface for a model assessment.

The precise remaining source request, endpoint identities, planning byte/call bounds, unknown entitlement and $0 task accounting are in [SOURCE_REQUEST.md](C:/Users/james/asp-model-studio/outputs/nba-gen1-v1/SOURCE_REQUEST.md) and [source-qualification.json](C:/Users/james/asp-model-studio/outputs/nba-gen1-v1/source-qualification.json). The preferred delivery is an existing lawful SportsDataIO NBA export for 2020–21 through 2025–26, including schedules, both team boxes and period scores. No account, trial, purchase or provider contact is authorized by this contract.

## Physical binding

Every bound artifact has exactly these required reference fields:

```json
{"path": null, "sha256": null, "bytes": null}
```

The nulls deliberately make this illustration unusable. Delivery must supply an absolute file path, lowercase physical SHA-256 of the exact retained bytes and integer byte count. No newline normalization precedes checksum verification. Original source objects remain retained alongside normalized tables. Normalization requires its own code identity, acquisition lineage, units and source-field mappings; it must not replace the originals.

Outcome-bearing normalized and original objects must be isolated by season so Development access cannot read Validation/OOT payloads. Shared metadata-only approval and team-identity objects may be referenced across partitions. A large original file containing all seasons cannot be included among a Development partition's raw objects merely because its normalized table is separated.

## Index: `NBA_GEN1_REAL_POPULATION_INDEX_V1`

The JSON index contains metadata and physical references, not game scores or box statistics. The following fields are required before outcome access.

| Field | Required value or type |
|---|---|
| `schemaVersion` | `NBA_GEN1_REAL_POPULATION_INDEX_V1` |
| `dataClassification` | `REAL_UNSCRAMBLED_OFFICIAL_GAMES`; fixtures, simulations and scrambled trials fail admission |
| `reviewStatus` | `VERIFIED_REAL_TRAINING_AUTHORITY` backed by the named review receipt |
| `reviewedBy`, `provider`, `reviewedAtUtc` | Source-review identity, provider/dataset identity and actual review clock |
| `approvalReceipt` | Physical reference to the named source-admission approval and account/dataset authority |
| `rights` | Object with each of the five permissions below explicitly established |
| `rightsEvidence` | Nonempty array of physically bound applicable rights documents/receipts |
| `timestampSemantics` | `AUTHENTICATED_SOURCE_REVISION_AVAILABILITY` |
| `timestampEvidence` | Physical reference establishing source clock meaning, timezone and historical availability |
| `costAuthorization.newSpendingAllowed` | `false`; account entitlement, remaining allowance and zero incremental cost must be evidenced separately |
| `teamIdentityMap` | Physical reference to the reconciled source/canonical team and franchise map |
| `identityReconciliation.unresolvedReplacementEvents` | `0`; cancellation, postponement and replacement lineage must already be resolved |
| `seasons` | At least five consecutive complete season partitions, ordered by integer start year |

The exact `rights` keys are `retrieval`, `rawRetention`, `historicalModelTraining`, `derivedForecastRetention`, and `derivedForecastDisplay`. All must be `true` with supporting evidence; setting booleans is not a grant of rights. Evidence must distinguish account-specific real NBA entitlement from a generic product page, document permitted seasons/endpoints, original-byte and artifact retention including post-termination restrictions, internal modeling/evaluation use, and derived research exchange/display. Do not infer raw feed redistribution or spending authority.

Each `seasons` entry contains:

| Field | Meaning |
|---|---|
| `season` | Integer season start year; `2024` means 2024–25, independent of provider URL token conventions |
| `completeRegularSeason` | `true` only with certified complete regular-season scope and reconciled identities |
| `metadata` | Physical reference to the identity-only Parquet below |
| `games` | Physical reference to this season's normalized game/team-box Parquet |
| `overtimePeriods` | Physical reference to this season's overtime-period Parquet; preserve the schema even when empty |
| `rawObjects` | Nonempty array of physical references to retained original source responses for that season |

Keep source URLs, credential-free parameters, capture timestamps, checksum/revision lineage and normalization mappings in the bound source receipt. Every game's `source_object_sha256` must identify a retained raw object in its season. Source API season parameters must come from the provider's governed season mapping, not from guessing the start-year integer.

## Identity-only season metadata

The required Parquet columns are:

```text
game_id
season
season_type
home_team_id
away_team_id
scheduled_tipoff_utc
schedule_available_at_utc
status
source_revision
source_available_at_utc
source_published_at_utc
captured_at_utc
source_object_sha256
```

`game_id`, `home_team_id` and `away_team_id` are nonempty stable identities; home and away differ. `season` is an integer start year, and `season_type` is `REGULAR`. Completed-season metadata permits `FINAL`, `CANCELLED` and `POSTPONED`; only FINALs enter features and labels. Preserve excluded event identities rather than silently replacing them. `source_revision` is a positive integer; `(game_id, source_revision)` is unique across the index.

Home/away identities and season must remain constant across revisions. The present gate requires one resolved scheduled-tipoff identity per game. Conflicting schedule vintages must be reconciled upstream with explicit source-backed reschedule/supersedes lineage; aliasing a replacement as another game is not accepted. It is not acceptable to use a retrospectively corrected date as if its pre-tip schedule authority were known.

All clocks must have an explicit timezone and normalize to UTC:

- `schedule_available_at_utc < scheduled_tipoff_utc`.
- `source_published_at_utc <= source_available_at_utc <= captured_at_utc`.
- A FINAL's `source_available_at_utc` is after its tipoff.
- Revision availability does not move backward as revision numbers increase.

`source_available_at_utc` is the authenticated availability of that exact revision, not today's acquisition time relabeled as historical availability. `captured_at_utc` is the actual capture/acquisition clock. A final archived `Updated` value may make the last revision eligible only after that time; it does not establish an earlier version or pre-tip schedule. No invented next-day publication or inferred pregame fact is allowed.

Metadata cannot contain `home_score`, `away_score`, `overtime_periods` or any box column below. Identity and role inspection therefore does not expose score/box payloads. Team maps and source review must resolve canonical aliases before game labels are loaded.

## Full-game rows

The season `games` Parquet contains every metadata column, in the same one-row-per-revision identity/order as the metadata partition, plus:

```text
home_score, away_score, overtime_periods
home_fgm, home_fga, home_fg3m, home_ftm, home_fta,
home_oreb, home_dreb, home_tov, home_minutes
away_fgm, away_fga, away_fg3m, away_ftm, away_fta,
away_oreb, away_dreb, away_tov, away_minutes
```

Both scores include overtime. `fgm`, `fga`, `fg3m`, `ftm`, `fta`, `oreb`, `dreb`, `tov`, scores and `overtime_periods` are finite nonnegative integer counts on FINAL rows. Minutes are summed player minutes, with five players on court: `240 + 25 × overtime_periods`, within 0.1 minute at source admission. Do not substitute one team's elapsed game minutes, seconds or a player average without a documented unit conversion retaining the original components.

Require `FG3M <= FGM <= FGA`, `FTM <= FTA`, and `score = 2 × FGM + FG3M + FTM`. FINAL NBA scores cannot tie. Missing final boxes remain unsupported; do not fill them with fabricated values. Cancelled/postponed rows may lack outcomes and are excluded from numeric history.

The point-in-time feature builder uses only eligible earlier revisions. Labels use the latest admitted final revision for each stable game at the relevant training or assessment gate; that final revision is retained in the residual and scoring identities. A source correction cannot retroactively improve an old feature row's availability.

## Overtime-period rows

The season `overtimePeriods` Parquet requires:

```text
game_id, source_revision, period, home_points, away_points,
source_available_at_utc, source_object_sha256
```

Each row represents a complete observed overtime period, with integer `period >= 5` and nonnegative integer point counts. `(game_id, source_revision, period)` is unique. Every row must map to an admitted FINAL revision and its exact source clock and raw-object hash. For a game with `n` overtime periods, retain exactly periods `5` through `4+n`; data ordering does not substitute for period identity.

All earlier overtime periods must have tied point contributions; the last must resolve the tie. Subtracting all overtime points from each final score must give the same nonnegative regulation score. This verifies overtime scoring against the final margin. The raw full box should retain regulation period scoring as well; the normalized tie-treatment table needs only the overtime periods.

A simulation donor bank may use only source-qualified overtime periods from eligible earlier training games. Its minimum is 20 periods. Missing overtime evidence blocks supported full-game simulation instead of inventing tie-breaking probabilities.

## Role declaration and reproducible artifacts

Registration writes `NBA_GEN1_CHRONOLOGICAL_DECLARATION_V1` under an immutable SHA-addressed object and a pointer. It binds the source index, metadata identity hash, exact feature contract and seven numerical modules: `authority.py`, `features.py`, `distribution.py`, `models.py`, `assessment.py`, `runner.py` and `forecast.py`. Roles are all but the last two seasons for Development, then Validation and OOT. For the requested six seasons this gives 2020–2023 / 2024 / 2025. The original plan is retained when registration is repeated with identical bindings; changed source or executable code requires a new study identity.

The separate numerical phases require the earlier phase receipts: Development before Validation, locked selection before OOT, and the retained OOT assessment before refit. A one-time OOT access receipt prevents silent repeated opening. Training and residual donor identities are season-forward; no in-sample or target-game residual may become its own uncertainty model. All original joint populations and fitted preprocessing remain retained.

The commands and expected analysis outputs are in [MODEL_CARD.md](C:/Users/james/asp-model-studio/docs/nba-gen1-v1/MODEL_CARD.md). No successful source index, model fit, metrics table or future example has been manufactured to illustrate these contracts.

## Future research-shadow interface

The forecast runner is for a genuine scheduled regular-season game, with authenticated schedule identity and only source evidence available before its forecast cutoff and tipoff. It must bind the exact fitted research artifact, preprocessor, feature contract, canonical/source game and team IDs, baseline input lineage, deterministic seed and 10,000 original paired HOME/AWAY score draws. `NBA_GEN1_SCHEDULE_EVIDENCE_V1` binds the exact schedule target/revision, source index and actually captured source object. `NBA_GEN1_CURRENT_HISTORY_COVERAGE_V1` certifies both target teams' complete game membership through the exact source cutoff, with no missing game IDs and a physically bound history population; stale off-season histories cannot silently stand in for current inputs.

Outputs include home/away win fractions, expected scores, expected total and home margin, home/away/total/margin distributions, central prediction intervals, simulation and overtime diagnostics, source cutoff, actual creation time and separate actual publication time. Final tie probability is zero only when the supported overtime rule completes; unsupported cases remain explicit dispositions. No fixture may serve as a demonstration forecast and no AISP import or display is implied by creating an export.

The request/publication schema is a research-only extension for future integration. It grants no account, decisions, wagers, staking, scheduler or production authority, and does not modify the existing MLB/NFL exchanges.

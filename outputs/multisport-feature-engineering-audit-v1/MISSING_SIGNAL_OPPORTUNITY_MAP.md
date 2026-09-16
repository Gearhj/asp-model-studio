# Missing-signal opportunity map

This is an acquisition-free research map. Every proposed gain is a hypothesis. The complete per-family rationale, rights, clocks, identity, missingness, cost and priority dimensions are retained in `PRIORITIZED_FEATURE_BACKLOG.json`. No documentation visit is an API entitlement check.

## MLB

Existing bounded official-source/Statcast intake and protected-history exception remain exact-scope only. Documentation grants no blanket acquisition or evaluation exception. Redistribution and new source scope require prior review.

| Family | Existing/new information and rationale | Source | Estimated engineering days |
|---|---|---|---:|
| Velocity/pitch-mix changes | CHANGE_OVER_EXISTING_LEVELS: Current velocity and3 pitch-group levels already exist; a within-pitcher change may distinguish form from career skill. No2026 miss attribution used. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 4 |
| Starter pitch-count/removal hazard | EXISTING_RESEARCH_NOT_NEW_ACQUISITION_BY_DEFAULT: Six-field starter history and survival path exist; extra dynamic removal coupling would address exposure, but study superiority is unestablished. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 5 |
| Bullpen workload/availability | NEW_NAMED_REPLACEMENT_INFORMATION: Anonymous relief mixture cannot represent a particular available replacement; BF workload and uncertainty about availability could improve exposure. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 7 |
| Batter/pitcher handedness | ALREADY_PRESENT: Six confirmed matchup fields already cover basic platoon effects. Avoid redundant acquisition. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 2 |
| Lineup-strength changes | DERIVED_FROM_CONFIRMED_PARTICIPANTS: Confirmed order is present; aggregate strength change relative to ordinary order is not a separate validated input. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 3 |
| Park/weather interactions | PARTIAL_NEW_CONTEXT: Park/time proxies exist; true pre-cutoff weather and source missingness need resolution before interaction fitting. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 5 |
| Travel/rest | MOSTLY_PRESENT: Large existing travel/rest block; establish reliance before adding duplicate mileage or circadian formulas. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 2 |
| Catcher/umpire context | SOURCE_GAP: Catcher IDs are documented; no qualified umpire pregame source/vintage established here. Skill effects not yet demonstrated. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 6 |
| Shrunk short-term form | MOSTLY_REPACKAGING_CURRENT_HISTORY: Annual/100PA/250BF priors already shrink noisy rates; explicit level-change signal could be tested without an expanding slice search. | [Official documentation](https://baseballsavant.mlb.com/csv-docs) | 3 |

## NFL

Existing local nflverse source contracts admit research with attribution (PBP CC-BY4.0; participation has separate CC-BY-SA/FTN terms). No API calls needed for existing PBP/Gold. New current personnel/other source rights remain unverified.

| Family | Existing/new information and rationale | Source | Estimated engineering days |
|---|---|---|---:|
| Opponent-adjusted EPA and offense-defense matchup | NEW_CONDITIONING_EXISTING_ADMITTED_DATA: EPA and scoring perturbations hurt across all three origins; raw rates do not separate opponent quality. Fix scope to pass/run offense and opposing defense adjustments. | [Official documentation](https://nflreadr.nflverse.com/reference/load_pbp.html) | 4 |
| Success rate | ALREADY_PRESENT: Already32 success/early-down-related horizon/side inputs; incremental reliance is weak in2022/23 and stronger2024. | [Official documentation](https://nflreadr.nflverse.com/reference/load_pbp.html) | 1 |
| Pass rate over expected | NEW_TENDENCY_FROM_PBP: Raw play choice can separate pace/game-state response from ability; absent197. Source expectation model chronology must be pinned. | [Official documentation](https://nflreadr.nflverse.com/reference/load_pbp.html) | 4 |
| Explosive-play rates | ALREADY_PRESENT: Pass>=20/run>=10 on both offenses/defenses already present; margin reliance positive across origins. | [Official documentation](https://nflreadr.nflverse.com/reference/load_pbp.html) | 1 |
| Pressure/sack/protection | PARTIAL_NEW_INFORMATION: Sack rate present; pressure without sacks and OL continuity are missing. Participation feed timing limits current use. | [Official documentation](https://nflreadr.nflverse.com/articles/dictionary_participation.html) | 6 |
| Early/late-down performance | ALREADY_PRESENT: Early success plus3rd/4th conversion already exist; weak grouped marginal reliance, not evidence to add more rates. | [Official documentation](https://nflreadr.nflverse.com/reference/load_pbp.html) | 2 |
| Red-zone performance | DISTINCT_DRIVE_DENOMINATOR: Existing metric is touchdown PER PLAY inside20, not scoring-trip conversion; denominator clarification is meaningful. | [Official documentation](https://nflreadr.nflverse.com/reference/load_pbp.html) | 3 |
| Special teams | NEW_M1_UNIT_SIGNAL: Not in active197; play engine includes kicks separately. Earlier PBP can support team kicking/return expectations with shrinkage. | [Official documentation](https://nflreadr.nflverse.com/reference/load_pbp.html) | 4 |
| Quarterback status | PREGAME_CLOCK_GAP: Timing-unproven schedule starter fields excluded; completed QB-context study does not authorize a new outcome-selected correction. | [Official documentation](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html) | 6 |
| Offensive-line continuity | NEW_PERSONNEL_SIGNAL_WITH_FEED_GAP: Roster presence is not planned snap share; historical snap IDs available but current participation feed is delayed. | [Official documentation](https://nflreadr.nflverse.com/articles/dictionary_participation.html) | 7 |
| Injuries/projected participation | SOURCE_REQUIRED: Historical injury tables do not establish a current reliable pregame feed. Need proper observed status and revision time. | [Official documentation](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html) | 8 |
| Weather/rest/travel | PARTIAL_NEW_CONTEXT: Rest/roof/surface present; archived weather often game-time observation. Forecast-vintage weather and geographic travel missing. | [Official documentation](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html) | 5 |
| Personnel usage | UNAVAILABLE_PROSPECTIVELY_AS_ASSUMED: Historical formations/player IDs exist; FTN post2023 season-end cadence prevents naive prospective rolling usage. | [Official documentation](https://nflreadr.nflverse.com/articles/dictionary_participation.html) | 7 |

## NBA

Existing score/date history permission preserved; it does not establish a SportsDataIO box/projection entitlement. Unscrambled retention, internal training and derived forecast display rights must be established for a new source. No trial/account/purchase requested.

| Family | Existing/new information and rationale | Source | Estimated engineering days |
|---|---|---|---:|
| Projected player minutes | NEW_INFORMATION_SOURCE_REQUIRED: Point model has no players; team scoring history cannot know rotation changes. No certified minutes snapshots admitted. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 10 |
| Injury/availability | NEW_INFORMATION_SOURCE_REQUIRED: No player-status features in78. Status needs actual pregame capture; current final box status is not equivalent. | [Official documentation](https://official.nba.com/nba-injury-report-2025-26-season/) | 6 |
| Expected/confirmed starters | NEW_INFORMATION_SOURCE_REQUIRED: Actual Started is postgame; require projected/confirmed pregame edition and IDs. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 6 |
| Lineup strength | NEW_INFORMATION_SOURCE_REQUIRED: Requires expected minutes plus earlier player strength; do not multiply unknown minutes by arbitrary talent. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 12 |
| On/off impact | NEW_INFORMATION_SOURCE_REQUIRED: Paired lineup possession data could supply relative impact; confounded teammates/opponents and missing admitted play history. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 12 |
| Rotation depth | NEW_INFORMATION_SOURCE_REQUIRED: Potentially explains roster changes ignored by score history; no repeatable miss-region evidence in this audit. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 8 |
| Rest/back-to-back | ALREADY_PRESENT: Already engineered with ordinary-rest support and3/7/14-day density; small stable margin reliance later. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 1 |
| Travel | PARTIAL_SOURCE_REQUIRED: Dates alone are not miles/time-zone burden. Need venue identities and itinerary assumptions, not fabricated travel. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 4 |
| Pace and team possession efficiency | NEW_INFORMATION_SOURCE_REQUIRED: Recent scoring drives totals but mixes possession volume and efficiency; full-game boxes can separate them. Existing78 cannot. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 6 |
| Shot-location profile | NEW_INFORMATION_SOURCE_REQUIRED: Earlier shot mix may distinguish offense styles; not inferable from totals, and source/rights not admitted. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 8 |
| Three-point attempt behavior | NEW_BOX_INFORMATION: Team FGA/3PA history can add shot mix; current scoring variance adds little stable total value. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 5 |
| Rebounding | NEW_BOX_INFORMATION: Earlier ORB/DRB opportunities could improve possession retention; counts require denominators. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 5 |
| Turnovers | NEW_BOX_INFORMATION: Earlier turnover frequency separates lost possessions from poor shooting; absent score/date inputs. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 5 |
| Free-throw generation | NEW_BOX_INFORMATION: FTA relative to attempts/possessions may add scoring route; current points history only indirectly reflects it. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 5 |
| Player/lineup matchup | DEFER_UNTIL_PERSONNEL_FOUNDATION: Depends on first building timestamped availability and minutes; premature without base player inputs. | [Official documentation](https://sportsdata.io/developers/data-dictionary/nba) | 15 |

## CFB

Existing CFBD authorization covers admitted source scope only. Published access tiers are not unrestricted acquisition/redistribution authority. Retained terms prohibit raw-data resale/redistribution; new endpoint scope and cumulative allowance must be checked before intake.

| Family | Existing/new information and rationale | Source | Estimated engineering days |
|---|---|---|---:|
| Recruiting/returning-production prior | NEW_OFFSEASON_INFORMATION: Elo dominates margin and opening support is thin; roster-quality prior might capture offseason change. No guaranteed improvement. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 6 |
| Transfers | NEW_INFORMATION_SOURCE_REQUIRED: Portal membership alone does not prove enrollment/eligibility or expected role; needs captured roster reconciliation. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 7 |
| Returning production | NEW_OFFSEASON_INFORMATION: Forward-looking source is documented; preserve preseason revision and team/player basis, not final-season retention. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 5 |
| Quarterback continuity | NEW_INFORMATION_SOURCE_REQUIRED: QB snaps/status not in35. Need eligible past snaps plus genuine expected-starter capture. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 7 |
| Coaching changes | NEW_OFFSEASON_INFORMATION: Tenure dates may explain changed schemes; no causal inference from past-win differences. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 5 |
| Conference/opponent adjustment of team performance | NEW_CONDITIONING_EXISTING_ADMITTED_DATA: Yardage drives totals while raw scoring/turnovers add little conditional reliance. Earlier opponents can residualize strength instead of relying on a conference-match indicator. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 4 |
| Pace/play tendencies | NEW_DENOMINATORS_VERIFY_CACHED_SCHEMA: Raw yards confound volume/efficiency; admitted boxes may contain play counts but coverage not established by this audit. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 5 |
| Opponent-adjusted efficiency | NEW_GAME_LEVEL_SIGNAL_SOURCE_SCOPE_REQUIRED: Game-level PPA/plays documented; avoid importing end-season adjusted ratings into earlier targets. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 6 |
| Explosiveness | NEW_PLAY_SIGNAL_SOURCE_REQUIRED: Missing from35; game-level play gains needed, no target game counts. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 6 |
| Havoc | NEW_GAME_LEVEL_SIGNAL_SOURCE_REQUIRED: Raw turnovers already weak; sacks/TFL/disruption with denominators could add information but cannot assume gain. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 6 |
| Garbage-time adjustment | NEW_PLAY_CONTEXT_SOURCE_REQUIRED: Could improve comparable efficiency but needs chronological play filtering/rule freeze; not score-driven pruning. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 7 |
| Special teams | NEW_UNIT_INFORMATION: Missing unit scoring/field-position contribution; lagged kicks and returns require source coverage. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 6 |
| Roster continuity | NEW_OFFSEASON_INFORMATION: Source rosters documented; membership and retained production differ, revision clocks essential. | [Official documentation](https://api.collegefootballdata.com/data-availability) | 7 |

## Source timing and cost qualifications

- [MLB](https://baseballsavant.mlb.com/csv-docs): Pitch fields include velocity, pitch type, handedness and catcher identity. Documented fields do not establish current local capture or permission for new intake.
- [NFL_PBP](https://nflreadr.nflverse.com/reference/load_pbp.html): Season-level PBP is documented from1999. Existing local Gold and pre2025 Bronze provide the internal-research starting evidence.
- [NFL_TIMING](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html): PBP is refreshed after games and later corrections. FTN participation from2023 is postseason-only; it cannot be treated as an in-season feed. Depth charts from2025 use timestamped updates. The documentation reports the old injury source discontinued after2024; no current availability is assumed.
- [NFL_PERSONNEL](https://nflreadr.nflverse.com/articles/dictionary_participation.html): The documented schema includes personnel, player IDs and pressure; prior-game fields are not target-game pregame facts.
- [NBA](https://sportsdata.io/developers/data-dictionary/nba): The vendor documents player-game projections, minutes, starting status, injuries, IDs and update timestamps in US Eastern time. Some columns are scrambled in trial feeds. Documentation does not establish an unscrambled entitlement or model-training/display rights.
- [NBA_INJURY](https://official.nba.com/nba-injury-report-2025-26-season/): Official report page exists; no report payload was fetched in this audit. Historical completeness and permitted automated capture remain unverified.
- [CFB](https://api.collegefootballdata.com/data-availability): CFBD documents games/boxes, advanced stats, roster/coaches, recruiting, transfers and returning production with different start years. Returning production is described as preseason; historical records may be revised. Current-season/row completeness is not guaranteed.
- [CFB_ACCESS](https://collegefootballdata.com/api-tiers): Published free tier lists1000 calls/month and basic/stat/recruiting/advanced access; paid tiers add capabilities. Existing account entitlement and cumulative remaining allowance were deliberately not queried or changed.
- [CFB_USAGE](https://api.collegefootballdata.com/usage-and-access): Availability and access are distinct. Playground calls count against usage; none was invoked.

The principal NFL adjustment uses existing admitted Gold/PBP: **0 new calls, USD0 incremental provider cost**, approximately **3–5 engineering days**. CFB season-level expansion is a planning envelope of11 requests and at most20MiB per family for2014–24, subject to exact existing scope and remaining cumulative quota. It is not a request to execute. NBA/MLB new feed costs and archive sizes remain unknown; no fabricated zero-price entitlement.

## Market information

Independent model input, timestamp-compatible benchmark, validation-trained model/market blend, and postprediction offered-price edge are four different uses. A future blend could be tested only on matched pre-cutoff quotes with the same market settlement definition and chronological roles. Closing odds cannot retroactively serve an earlier forecast. This audit consumed no SportsGameOdds or The Odds API objects and assigns no profitability claim or acquisition priority to untimed market data.

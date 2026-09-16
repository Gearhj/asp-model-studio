# V19 research: what V18's 246 current raw fields actually contained

This is a read-only interpretation of the two original September 10 publications, not a replacement forecast, an assertion that V18 is fully current, or a new historical validation dataset. The pinned V18 scheduled deployment was not touched.

The [immutable manifest](../outputs/mlb-v19-current-state-specialists-v1/feature-quality/sha256/f98565904485f5995752bf3b3cb0dc8abea3d1b6860352ea097d942684d370ac/manifest.json) binds the field audit, cold-start specification, ranked gaps and original operational evidence. Its SHA-256 is `f98565904485f5995752bf3b3cb0dc8abea3d1b6860352ea097d942684d370ac`.

## Exact accounting

Each game has 246 raw fields in 34 templates: 18 initial lineup matchups and 16 staff candidates. Every field and all 16,728 values across the two games are preserved exactly, with original sources/clocks, frozen transformations, mean-prediction dependencies and missing-state branches. Repeated templates are not unique players.

| Evidence quality | Fields per game | COL–NYY cells | PIT–CWS cells |
|---|---:|---:|---:|
| Complete for the stated current definition | 176 | 6,656 | 6,467 |
| Current but partly observed / recovery proxy | 31 | 382 | 571 |
| Historical annual prior by design | 25 | 776 | 467 |
| Verified absence with semantic treatment | 0* | 74 | 383 |
| Missing numeric source family, correctly flagged | 14 | 476 | 476 |
| Unsupported raw contract field | 0 | 0 | 0 |
| Total | 246 | 8,364 | 8,364 |

*At field level the 25 mixed annual-prior fields retain their historical-prior classification; their absent cells are counted separately. Cell categories are exclusive. Do not add field and cell counts or interpret zero wholly absent fields as zero missing values. There are 68 actual null cells for COL–NYY and 352 for PIT–CWS; the semantic-absence totals also count 6 and 31 populated `prior_missing=1` cells respectively.

“Complete” means complete for that field's precise definition, not measured predictive value or complete current team state. It includes 6 mapping/eligibility fields and 5 hypothetical simulation-state fields. A generated initial base state is not an observation of an unplayed PA.

The 31 partly observed fields comprise 21 pitcher-window fields with at least one template below 250 BF, plus 10 recovery/circadian/travel-proxy fields. Calendar-based long-rest remains complete for its day-count definition. Every batter has the required 100-PA window here; that does not establish unchanged lineup membership or health.

The 14 source-gap fields are batting/fielding versions of seven indicators: recent bullpen workload, previous-venue altitude, previous-game end, previous-game end-time, previous-game duration, pregame temperature, and current-venue altitude. Their value of 1 accurately records absence; it does not supply the missing number. The two end-time indicators overlap and are not two independent missing data feeds.

## Families and limitations

- **Annual player skill:** 25 fields use the latest eligible frozen FD1 season, possibly older than 2025. Annual absence is not proof of rookie status, no career, or no current rolling evidence. Hierarchical pooling must distinguish that domain from current history.
- **Recent player history:** 31 fields use verified completed-game windows. Small pitcher windows have genuine lower exposure, not a pipeline failure. Release-speed sums and squared sums remain floating-point measurements; counts retain their exact event interpretation. Full pitch composition retains unclassified pitches.
- **Starters, lineup and handedness:** original starters are `PROBABLE`; original starting lineups are `CONFIRMED`. The forecast is conditional on those identities. Fixed starting lineups do not model the bench, later substitutions or late scratches.
- **Relief quality versus availability:** observed annual/recent skill for active staff candidates is available; individual availability, injury clearance and manager intentions are not. PIT's original CWS staff includes MLBAM `699823` from September 9, about 35.31 hours old at forecast creation and older than the latest retained September 10 team batch. Its membership is unproven by that newer batch. The original forecast and historical metrics remain preserved; the audit does not silently fix the old publication.
- **Rest/travel/calendar:** 150 team/context and 23 calendar fields largely describe scheduled starts, venue paths and fixed alignment. They do not measure actual travel itineraries or end-to-start recovery.
- **Catcher, actual roof state, umpire, transactions/injury/return and minor-league translations:** no corresponding fitted source-backed capability exists in this 246-field contract. Together with individual bullpen availability, these are six explicitly unsupported outside-contract families; they are not added to the 246 denominator.

Original observations, availability and ingestion clocks remain independent. Missing provider-publication or explicit retrieval clocks are left missing; ingestion is not relabeled publication. Current reconstruction of older games does not establish historical pregame vintages.

## Per-feature cold-start design

The [246-row semantic specification](../outputs/mlb-v19-current-state-specialists-v1/feature-quality/sha256/8e88e564a2e12e754f8c723d39a1864ef9bb4589b57c14134fe55063d2a98f25/cold-start-specification.json) attaches six states to every field: no opportunity, low exposure, no observation, inapplicable, source failure, and new player/changed role. It binds the exact frozen V18 treatment and explicitly separates proposed V19 families from actually fitted treatments in the study's executable package.

Observed zero numerator with positive applicable denominator is valid. Zero denominator, unobserved pitch data, absent annual domain, source failure and opposite-role inapplicability are not interchangeable. Training-prefix role/hand/archetype pooling and exposure-aware updating are candidate treatments, not invented observations. Previous-season decay, minor-league translations, replacement-level scalars and return-from-injury adjustments cannot be declared implemented without their required Development fit and source evidence. Generic global median/mode fallback is forbidden.

None of the 246 raw V18 fields is an uncertainty-only control. Frozen posterior standard deviations, reliability and exposure features are classifier inputs and can legitimately change PA means. A new field *designated uncertainty-only* must remain outside the ordered mean contract and pass fixed-seed, byte-exact mean-invariance checks. This audit itself does not fit or test a new uncertainty adjustment.

## Ranked local source work

The [ranked gap artifact](../outputs/mlb-v19-current-state-specialists-v1/feature-quality/sha256/2c75cb8a47d1f4d39b5495987cbc65232207294dbd8a811f424b6e6158a0321a/ranked-source-gaps.json) records qualitative predictive value, frequency, point-in-time reliability, historical reconstructability, availability and implementation cost. Priority is: pitching workload/rest; exact player history/semantic priors; current roster and confirmation clocks; actual game-end recovery; existing schedule context; pregame weather/roof; static park authority; catcher effects; transaction/return state; umpire context.

The source-additions component owns actual implemented workload/roster/confirmation supplements and coverage. This ranking does not claim their implementation, historical backtest eligibility or predictive gain. In particular, current downloads of old games cannot repair missing historical observation vintages.

[Official Savant CSV documentation](https://baseballsavant.mlb.com/csv-docs) documents game/player/pitch identity, release speed, catcher identity and previous-game interval. Its umpire field is deprecated; its days-until-next-game field is future-dependent and must not become a pregame predictor. [MLB terms](https://www.mlb.com/official-information/terms-of-use) do not establish an unrestricted commercial grant.

Existing project restrictions remain: `LOCAL_PRIVATE_MODEL_DEVELOPMENT`, Statcast `GOVERNED_LOCAL_RESEARCH_ONLY`, attribution, commercial-rights review and no inferred raw redistribution permission.

## Focused verification

Run `.venv\Scripts\python.exe scripts\build_mlb_v19_feature_quality.py`. It reads one checksum-pinned operational JSON only; no model, history source payload, AISP database, provider data or Final OOT is loaded. Repetition produces the same immutable manifest. Validation confirmed all 16,728 values unchanged, 246 ordered fields, 2 games, source references resolving and exclusive category sums.

`tests/test_mlb_v19_feature_quality.py`: 2 tests passed, protecting the populated-gap-indicator distinction and annual-domain absence versus genuinely short current history. Two public documentation pages were opened; zero provider data requests, $0 cost, zero model fits and zero sealed-data reads.

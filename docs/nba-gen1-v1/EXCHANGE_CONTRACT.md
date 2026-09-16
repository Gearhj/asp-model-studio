# NBA Gen 1 research forecast contract

**Proposed, unactivated schema: `NBA_GEN1_RESEARCH_FORECAST_V1`.** This document
does not represent a published forecast or AISP import. The builder requires a
real future game and admitted evidence; it does not create a demonstration game.
NBA remains research-only and unfunded. No account, decisions, wagers, scheduler,
staking policy or bankroll are created by this interface.

`server.sports_nba_gen1.forecast.build_shadow_forecast` builds one object locally.
The publisher, when separately integrated, must use the existing exchange's
content-addressed package convention: `packages/sha256/<physical index sha256>/`.
No new scheduler or parallel forecasting engine is needed.

## Binding and eligibility

The builder takes the fitted model, retained history/residual/overtime frames,
one identity-only target, exact source cutoff, and `bindings`. Each physical
reference is `{path, sha256, bytes}`. SHA-256 is over the exact file bytes with no
newline normalization. The required references are:

| Binding | Required content |
|---|---|
| `sourceIndex` | Real, unscrambled official game source index with named review, authenticated revision-availability semantics and supported retrieval, raw retention, training and derived-forecast retention/display rights. |
| `approvalReceipt` | The exact receipt bound by the source index. |
| `modelArtifact` | Trusted serialized `FittedPointModel`, or a bundle whose `model` entry is that object. |
| `preprocessorArtifact` | Same physical artifact as `modelArtifact`; preprocessing is embedded and never refit by prediction. |
| `featureContract` | JSON exactly equal to the executing `features.feature_contract()`. |
| `historyPopulation` | Exact retained Parquet frame passed to the builder, with final scores, boxes, revisions, source-availability and capture clocks. |
| `historyCoverageReceipt` | Current complete-history certification described below. |
| `residualPopulation` | Exact retained Parquet of chronological OOF errors in `residual_home`, `residual_away` order, with game IDs and source/tipoff clocks. |
| `residualReceipt` | Chronological residual receipt described below. |
| `overtimePopulation` | Actual observed period points, with `game_id`, `source_revision`, `period`, `home_points`, `away_points`, `source_available_at_utc`, `source_object_sha256`; tied intermediate OT periods must remain included. |
| `scheduleEvidence` | Identity-only schedule receipt described below. |

Also supply `modelConfigurationIdentity` and `modelTrainingIdentitySha256`.
Physical model verification includes matching the supplied in-memory object to
the retained fitted object. Frame contents must equal their bound Parquet bytes.

The target contains only `game_id`, `source_game_id`, `season` (start year),
`season_type=REGULAR`, `home_team_id`, `away_team_id`,
`scheduled_tipoff_utc`, `schedule_available_at_utc`, `status=SCHEDULED`,
`source_revision`, and optional home/away team names. Scores, boxes, lineups and
undeclared target fields are rejected. Required clocks are timezone-aware:

```text
schedule availability < source cutoff <= actual execution start < tipoff
actual execution completion < tipoff
```

The schedule receipt has schema `NBA_GEN1_SCHEDULE_EVIDENCE_V1`, the exact
`target`, `dataClassification=REAL_UNSCRAMBLED_OFFICIAL_GAMES`,
`sourceIndexSha256`, actual `capturedAtUtc <= cutoff`, and a physical
`sourceObject` reference. Rescheduled games require an already reconciled stable
identity and authentic schedule revision; a replacement must not duplicate it.

The coverage receipt has schema `NBA_GEN1_CURRENT_HISTORY_COVERAGE_V1`,
`targetGameId`, both `teamIds`, `sourceIndexSha256`, `historyPopulation`,
`sourceCutoffUtc`, `completeThroughUtc`, `membershipComplete=true`,
`missingGameIds=[]`, `createdAtUtc`, `reviewedBy`, and nonempty physical `evidence`
references. Both cutoff fields must equal this forecast's cutoff. This receipt
must result from actual authorized coverage reconciliation, not an assertion
that an old history table is current. Missing intervening games are unsupported.
Every retained history row used has availability strictly before the cutoff and
actual capture no later than the cutoff. Target rows are excluded from feature
construction. Each team needs at least five current/immediately-prior-season
games under the fixed feature contract.

The residual receipt has schema `NBA_GEN1_CHRONOLOGICAL_RESIDUAL_RECEIPT_V1`,
`residualType=CHRONOLOGICAL_OUT_OF_FOLD_ACTUAL_MINUS_PREDICTED`, `population`,
`sourceIndexSha256`, `modelConfigurationIdentity`,
`allTrainingBeforeDonorTipoff=true`, `allFeatureHistoryBeforeDonorTipoff=true`,
and physical `foldEvidence` references that establish those statements.
At least 200 distinct eligible earlier games and 20 eligible observed overtime
periods are required. Periods must match retained final revisions, clocks and
source bytes. Each included OT game must retain its complete period sequence,
reconciling to tied regulation and final scores. Missing evidence never becomes a simulation
fallback presented as genuine NBA Gen 1.

## Forecast semantics

Engine is `NBA_GEN1_TEAM_MARGIN_TOTAL`; version is `NBA_GEN1_RESEARCH_V1`.
The scope is NBA regular-season **full-game scores including overtime**. All
score units are points; probabilities are explicit fractions in `[0,1]`.

The forecast contains `homeWinProbability`, `awayWinProbability`,
`tieProbability=0`, `expectedHomeScore`, `expectedAwayScore`, `expectedTotal`,
and `expectedHomeMargin`. These are means and probabilities from the complete
original joint population. `pointModelExpected*` separately retains the point
model's margin/total-derived expectations. Stochastic rounding, the zero floor
and empirical tie resolution can change the simulation means; diagnostics retain
their actual shifts rather than claiming exact equality to point predictions.

Each of `home`, `away`, `total`, `margin` has a complete integer frequency table:
`{value, count, probability}` with denominator `drawCount=10000`. Totals and
margins always come from paired scores: `home[i]+away[i]` and `home[i]-away[i]`.
No tail trimming, independent marginal sampling or summed medians are permitted.
Central 50%, 80%, 90% intervals use empirical `inverted_cdf` quantiles. Full joint
draws remain the primary distribution evidence.

Each draw samples a complete oriented HOME/AWAY chronological residual pair,
using one pooled mean subtraction per residual column. Negative latent scores
are floored at zero, then stochastically rounded. Any tied draw receives a
complete empirical HOME/AWAY overtime-period increment; tied intermediate
periods may repeat, up to the documented safeguard. The entire forecast is
unsupported if a draw remains tied. No draws are discarded or coin-flip winners
invented. The residuals already describe full-game outcomes: this is a documented
tie-resolution adjustment, not a claim that initial draws represent regulation.

The simulation receipt gives the seed, PRNG/child-stream policy, donor counts,
raw tie frequency, appended periods, before/after means and home-win probability.
MCSE is numerical sampling precision, not a bound on model error or the count of
independent assessment observations.

## Package and import

A genuine package should contain `index.json`, `forecast.json`, `population.npz`,
`feature-audit.json`, and a concise `CLAUDE_HANDOFF.md`. The index binds every file
by physical path, SHA-256 and byte count; the package directory is named by the
exact physical index SHA-256. Retain the original arrays, including joint
`home_runs` and `away_runs` keys (legacy internal names; values are **NBA points**),
residual draw indices and overtime-period counts. The forecast includes a logical
checksum of C-order little-endian signed-int64 `[draw, HOME/AWAY]` scores; this is
distinct from the physical NPZ checksum, which must also be recorded.

`createdAtUtc` is actual execution completion. The builder leaves
`publishedAtUtc=null`, `population.physicalArtifact=null`, and
`publicationDisposition=BUILT_LOCALLY_NOT_PUBLISHED`. Only an actual publisher
may attach the retained population file reference and actual publication clock,
under an immutable version. The original source cutoff and creation time must
remain unchanged. A package published after the governing cutoff must never be
represented as prospective.

Import by the exact `forecastId`, stable game/source IDs, orientation, model and
feature-contract hashes, source cutoff and complete joint population. Confirm
10,000 untied paired draws, probability/count reconciliation, distribution means
and all physical hashes before accepting the package. Keep source absence or
unsupported history explicit. Do not infer AISP import or display from package
publication; only a consumer receipt can establish acknowledgement.

Every object retains `researchOnly=true`, and `productionAuthority`,
`wageringAuthority`, `schedulerAuthority`, `accountCreationAuthority` are false.
This contract supplies no market quotes, ticket enumeration, account or policy.

# MLB_PA_FEATURE_VIEW_V1

## Consumer boundary

`MLB_PA_FEATURE_VIEW_V1` is the governed input contract for an eight-class
plate-appearance component model. It is suitable for retrospective component
research inside a future simulator; it is not a complete pregame forecast, a
game simulator, a betting model, or an exportable ASP bundle.

Registered Phase 3 authorities:

- semantic contract SHA-256:
  `fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e`;
- feature schema SHA-256:
  `1660eed54bf3904c2f2306d5a0171e7df6bf87fdc4fa9d39fb5ec2e8e741afd6`;
- feature-view identity:
  `mlb-pa-feature-view:sha256:74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b`;
- registered research run:
  `sports-pa-research-run:sha256:9ee241378320fb820aab2531a6525d2d4624d42e7ff6c406e147f28c6800fd07`.

The view is accepted only when bound to the complete frozen authority set:

- dataset registration `sports-dataset-1b58d5d1def2c9b7`;
- project `sports-project-mlb-fd1-1b58d5d1def2`;
- parent manifest SHA-256
  `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`;
- parent partition-authority SHA-256
  `8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437`;
- identity-bridge registration `sports-identity-bridge-6b69e7dcf4c5db76`;
- identity bridge SHA-256
  `6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf`;
- alias and dimension row authorities
  `ddb828aee391b2f725ba4540a874865963313e6c210f246eacd7bbcf28025661`
  and `6f30e1b30ca41002d6cbb2dea8b90da5abfad4f62f96237e780fbee518005acf`;
- exact join audit
  `sports-identity-join-audit:sha256:375ef4faef6716a8d66fe68b30c12bf8caff5b9255aa71fc4bd7354f9589b8b9`.

## Population and class order

The target population is exactly the primary plate-appearance rows from 2023,
2024, and 2025: 184,104, 182,449, and 182,926 rows, respectively. The immutable
probability-vector order is:

| Zero-based index | Class |
|---:|---|
| 0 | `STRIKEOUT` |
| 1 | `WALK_HBP_CI` |
| 2 | `HOME_RUN` |
| 3 | `SINGLE` |
| 4 | `DOUBLE` |
| 5 | `TRIPLE` |
| 6 | `BIP_OUT` |
| 7 | `OTHER_REACH` |

Any other row count, season, population, target encoding, or class order fails
closed.

## Exact identity and Y-minus-one priors

Retrosheet batter and pitcher values join exactly through the registered bridge
to a canonical UUID. The UUID is a governed join key only; it is never a model
feature. Batter features use only the BATTING domain and pitcher features use
only the PITCHING domain. For target season `Y`, select the latest deterministic
annual row satisfying both `season <= Y - 1` and
`eligible_from_season <= Y`. Same-season and future evidence are prohibited.

A resolved identity without eligible earlier history is legitimate missingness.
It produces a role-specific missing-prior indicator and fold-local imputation;
it is not an identity failure and must not be filled by a later season.

## Included component-state block

Only values verified to exist before the terminal plate-appearance event may be
used as component-state predictors:

- inning;
- inning half / batting-team home-away state;
- outs before;
- base occupancy mask before; and
- batting-team score differential before the plate appearance.

The enforced domains are inning 1–14, `top_bottom=0` when the visiting team bats
and `top_bottom=1` when the home team bats, outs 0–2, and base mask 0–7. Score
differential is visitor minus home for `top_bottom=0` and home minus visitor for
`top_bottom=1`. All five projected context fields have zero nulls in the
registered 549,479-row view. These fields describe state at component
invocation. Their inclusion does not claim that a standalone pregame caller
already knows future game state. Batter side, pitcher hand, and platoon features
are absent from FD1 and therefore are not included.

## Included prior block

The bounded batter block contains `log1p(PA)` plus AVG, OBP, SLG, SO/PA,
(BB+HBP)/PA, and HR/PA, where `PA = AB + BB + HBP + SF + SH`.
`log1p(PA)` is defined at zero; rate features require a positive declared
denominator.

The bounded pitcher block contains `log1p(BFP)`, ERA9, WHIP, SO/BFP, BB/BFP,
HR/BFP, HBP/BFP, and GS/G, where `ERA9 = 27*ER/IPouts` and
`WHIP = 3*(BB+H)/IPouts`. `log1p(BFP)` is defined at zero; nonpositive rate
denominators produce missing values rather than fabricated rates.

## Absolute exclusions

The matrix excludes the terminal outcome and target-derived/post-terminal
fields; final score and game outcome; actual participants, starters, reliever
usage, and untimestamped actual weather; odds and CLV; same-season or future
totals; source IDs, player UUIDs, game IDs, partition/checkpoint/manifest IDs,
checksums, and governance hashes. Batter and pitcher IDs condition exact prior
lookup only; IDs otherwise remain outside the matrix for joins and lineage,
while `game_id` is the whole-game bootstrap key. `game_date`, which is not an
ID, drives the date-atomic chronological split. Participation, lineup, and usage
models are not part of this feature view.

## Fold-local preprocessing and evaluation

Categorical encoding, numeric imputation, and all other learned preprocessing
fit only on the current training population. The internal 2023 tuning split is
chronological and keeps dates atomic. Frozen rolling-origin evaluation fits on
2023 and evaluates 2024, then refits the frozen selected policy through 2024
and evaluates 2025 once. The 2025 season is retrospective rolling-origin
validation, not an untouched holdout and never a tuning source.

The bounded multinomial candidates use scikit-learn LBFGS, L2 regularization,
`C` values `0.05`, `0.2`, and `1.0`, `max_iter=2000`, and `tol=1e-7`.
Convergence warnings or exhausting the iteration ceiling fail closed. The
registered C4 combined candidate selected `C=1.0`; this is research evidence,
not deployment authorization.

## Storage contract

Contract, schema, feature-view Parquet, preprocessing, model, class-order,
prediction, metric, calibration, bootstrap, lineage, and model-card artifacts
live only in ignored target-local runtime storage. The artifact index records
each content-addressed artifact's SHA-256, byte count, media type, and logical
URI. Artifact envelopes carry their creation and run or materialization
identity, code revision, source authorities, and feature-contract SHA;
row/fold/partition lineage is included only where applicable.

The canonical feature Parquet has stable materialization identity
`sports-pa-feature-materialization:sha256:ff425ca7a4aa0180837d3265fbb02d34484f6ea7a495cc5a5545bd9aeb836a55`.
A separate `FEATURE_VIEW_RUN_BINDING` connects it to final research run
`sports-pa-research-run:sha256:9ee241378320fb820aab2531a6525d2d4624d42e7ff6c406e147f28c6800fd07`.
SQLite stores metadata and logical `asp-model-studio-runtime://` references
only; prediction rows and model bytes remain outside the relational database.

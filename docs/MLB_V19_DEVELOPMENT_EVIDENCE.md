# V19 bounded Development evidence inventory

This inventory was made for the V19 research branch without reading Final OOT,
running a model fit, changing a source, contacting a provider, touching AISP, or
operating the pinned V18 publisher. Existing study results below are already-used
Development evidence, not independent confirmation for V19.

## Exact V18 and safe reusable cohort

The authoritative reproduction receipt is
`outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/baseline-reproduction-0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9.json`.
Its physical SHA-256 is the filename digest. It identifies all five frozen fitted
V18 preprocessors/encoders/estimators and records zero bitwise prediction mismatches
on the physically safe matched population. New verification should hash these
already-separated caches and replay saved fold estimators; it need not reopen
the mixed source partition or regenerate caches.

| Safe cache, relative to the receipt directory | Rows | SHA-256 |
|---|---:|---|
| raw-development.parquet | 676,499 | d5fdb7bcbe058f34334483a21b14e83129d19c1727d20eddb469c18668ff3b82 |
| matched-oof.parquet | 494,432 | 3e816c20f6276837062b97aaa5398984ac0b3660731cc086dfae4aef04f2c8ba |
| training-fold-1-treated.parquet | 182,067 | 1dc414cb12b0fbaead886dd3a7956650017ebf58dbbd5f722c2cfa3aa44a3290 |
| validation-fold-1-treated.parquet | 99,780 | 18e8d411bd68e21541fb8ab3bbf212e06a798f2c1336d95da530706c37f192be |
| validation-fold-2-treated.parquet | 100,267 | 6cf0d36229d542c871f2b1e3bbd4f8d6fea39247b0ae228a6e527ae044e13e80 |
| validation-fold-3-treated.parquet | 99,926 | 0c5901366a0a4e7636b33ffdb4dec2ba1be14a141b9bea2bb2ce241b78e3a836 |
| validation-fold-4-treated.parquet | 100,302 | dba60b5362c6f3305ead8e09f009890c2662a198a61f877deafbb7c7b6be263e |
| validation-fold-5-treated.parquet | 94,157 | 216438add2f7d7c663fc9ff3ce5ee4812e863131650506bc1f6805c651bf3ab2 |

The raw cache has 251 columns: the 246-input contract plus permitted identity,
target and fold metadata. Its 676,499 rows are outcome-independently eligible
Development observations through August 6, 2026; 2025 remains Development.
It contains 182,067 initial training observations and 494,432 OOF observations
across 6,570 games. The 56 previously held known-zero annual-prior observations
remain outside this cohort. No new handling is inferred for those held rows.

The accepted original OOF contains 501,539 observations. The difference of 7,107
is intentional: the old physically restricted reader excluded the mixed row
group and the incomplete August 7 boundary date. August 14–27, 2026 remains
sealed. Never read/hash the entire mixed source object to recover those rows.

| Fold | Training end | Validation window used | OOF PAs | Games |
|---|---|---|---:|---:|
| 1 | 2023-10-01 | 2024-03-20–2024-07-06 | 99,780 | 1,330 |
| 2 | 2024-07-06 | 2024-07-07–2025-04-15 | 100,267 | 1,338 |
| 3 | 2025-04-15 | 2025-04-16–2025-07-27 | 99,926 | 1,327 |
| 4 | 2025-07-27 | 2025-07-28–2026-05-01 | 100,302 | 1,327 |
| 5 | 2026-05-01 | 2026-05-02–2026-08-06 | 94,157 | 1,248 |

`stage3_corrected_preprocessing_artifacts.load_research_pipeline(reference,
root=Path('.runtime/asp-model-studio/stage3-model-laboratory'))` authenticates a
saved fitted artifact before loading it. `pipeline.preprocessor.transform_frame`
performs the 246-to-273 semantic/prior treatment; its saved encoder then applies
the training-fitted categorical treatment. For exact original raw probabilities,
use `_aligned_probabilities(pipeline.estimator, encoded)` as in
`mlb_regime_baseline.reproduce_and_cache`, not a differently normalized wrapper.

Five model digests, in fold order:

1. `7ad16b4237df5e3672b093b0d68cda94c73e60cb37f85811262615a3326db0d6`
2. `bc048c5dbbeafb1854774fedca94af157dbcbc537b59bbfcd25384e37376b57b`
3. `faaf792ab69055751c41e7d51cc63eb342f2f6724eafd202ec5d6fd489a64433`
4. `cbc7f3f6c8bcebe4f1c0c1ece64dbc741e2d7af1d0d8d5064294fad0c413291e`
5. `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`

All reside at `objects/research-model/sha256/<digest>.joblib` under that runtime
root. Frozen HGB settings: 500 iterations, learning rate 0.03, 31 leaves,
minimum leaf 50, L2 1.0, no early stopping, no max depth; seeds 20260907–20260911.
The accepted five-fold execution receipt recorded 7,685,875 ms (about 128 minutes)
including its pipeline work. New full-tree fitting is not comparable to the
approximately 135-second old correction-only study.

## Prior study reuse and scientific limitations

`scripts/run_mlb_regime_hybrid_study.py` and its corresponding `mlb_regime_*`
modules provide class-offset, membership-offset, interaction-offset, residual,
soft-gate, temperature and paired uncertainty machinery. Prior clusters were
chosen/fitted using 2023 only, not refreshed separately in every later fold.
The new study must implement its newly declared fold-local clustering design;
it must not relabel old cluster assignments as new fold-fitted evidence.

The old study used folds 1–2 for discovery, fold 3 for correction fitting,
chronological segments of fold 4 for gate/calibration/selection, and fold 5 for
its final Development comparison. On fold 5 the previously preserved V18/RF
combination had calibrated log loss 1.4722241819314617 versus calibrated V18
1.4724824504125849. Its original RF estimator is unavailable: these saved RF
probabilities are historical research evidence only, never an operational input
or a substitute for a newly fitted independently named tree challenger. The
offset, cluster, residual and soft-gate alternatives all lost to V18 in that
same prior fold-5 comparison. This entire cohort has already been inspected.

## Exact game identities and honest game-simulation path

The original map only covers OOF games, not the 2,406 initial 2023 training
games. `scripts/build_mlb_v19_game_context.py` closes that launch-critical gap
using the existing authenticated 2023 legacy Silver game/team dimensions.
The resulting **outcome-free** complete 8,976-game map is
`outputs/mlb-v19-current-state-specialists-v1/game-context/sha256/b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a/game-context.parquet`,
SHA-256 `9a642b0f373ef27bb684f46304661929843e9d60bef8188d2341c6373790296d`,
268,180 bytes. It verifies the exact canonicalGameId/game_id/date triple and both
canonical teams for every raw Development row's game. Existing OOF team mappings
are reused unchanged. No provider call, OOT payload, source mutation or new
identity invention is involved; the original 20 score columns are not read into
or exported from this projection.

Safe game context:
`outputs/mlb-regime-hybrid-ensemble-v1/game-context/sha256/90dc14c30b5c0b0279730ce716af13e6d3fd23527c36289c3778e8286ee77c02/game-context.parquet`
has SHA-256 `1c694e7b8bf185e6fd7366461295290c15a406fb8f527d725e4fbb6d08313adf`,
6,570 canonical game/team pairs, source/Retrosheet codes, and 20 final-score
diagnostic pairs for May 2–3, 2026. Scores derive from authenticated final-game
last ordered raw pitch post-scores. They are evaluation-only, not features and
not a separate independent official-score verification. This cache can be joined
many-to-one on canonicalGameId without rereading source partitions.

`mlb_regime_simulation.load_accepted_transition(ROOT)` authenticates the unchanged
transition-fold4.json digest
`0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253`,
whose training end is July 27, 2025. `compare_paired_game_mechanics` uses common
random numbers for baseline/challenger side-average PA vectors and returns win
loss/Brier, score/margin/total bias/MAE/RMSE, intervals, extra innings and legality.
Its label is **ORACLE_MECHANICS_SENSITIVITY_NONPREGAME**: realized PA inventories
and state-local probabilities cannot become pregame lineups or participant
vintages. The smallest honest comparison is the fixed 20 date/ID-selected fold-5
games with 500 draws each, reported only as mechanics sensitivity.

No authenticated historical pre-first-pitch participant/lineup vintages were
found in these relevant Development assets. The original whole-game bundle has
one separate prospective 2026 forecast and 10 oracle mechanics games, not a
matched chronological predictive game backtest. The September 10 operational
forecasts are separate prospective receipts, not Development validation games.
Consequently pregame game-skill improvement, market disagreement regimes and
game-level predictive calibration cannot be established by this cohort. Do not
invent those metrics from PA averages or reuse the old small market study as
confirmation.

## New pure evaluation helpers

`server/sports_current_statcast/mlb_v19_evaluation.py` contains fixed pregame
regime masks, earlier-fold-only persistence selection, matched diagnostics,
descriptive paired intervals/removal sensitivity and the labeled mechanics
wrapper. It has no file reads, provider interfaces, model fitting or publication.
The two focused tests protect target/in-game-state-invariant membership and
exclusion of future-fold targets/probabilities before discovery.

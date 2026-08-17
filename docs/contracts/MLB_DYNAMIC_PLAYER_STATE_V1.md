# MLB_DYNAMIC_PLAYER_STATE_V1

Status: research-only Phase 4 Milestone A contract. It does not authorize deployment, forecasting, wagering, or exchange publication.

## Authority and purpose

The component derives batter and pitcher state only from completed terminal plate-appearance outcomes in the registered `plate_appearance` family. It binds the exact MLB FD1 dataset registration, manifest, partition authority, the exact identity bridge and join audit, and the registered Phase 3 run, feature-view artifact, class order, and raw C4 prediction artifacts. Annual or game-level batting and pitching statistics are not dynamic-state evidence.

The target/lineage population is the immutable Phase 3 feature view for 2023–2025. Historical state reads the exact registered 2021–2025 plate-appearance partitions. Every Retrosheet batter and pitcher source ID must resolve through exactly one bridge alias to a canonical player UUID. Unresolved, duplicate, or ambiguous identities fail the run.

## Temporal policy

An outcome is eligible only when:

`source.final_available_date < target.game_date`

Same-date outcomes are excluded, including earlier games of a doubleheader. A suspended game remains unavailable until its registered final-availability date. UUIDs are lineage/grouping keys only and never predictors themselves.

The three normalized representations are:

- `A_PRESEASON`: all player outcomes available before January 1 of the target season, shrunk to the role/league distribution. It is static within a season.
- `B_CUMULATIVE`: all prior-final-date player outcomes, shrunk to the role/league distribution.
- `C_RECENCY`: long-term evidence from seasons through target season minus two, plus a disjoint exponentially weighted recent set from the prior/current season. The overlap count must be zero.

The immutable class order is `STRIKEOUT`, `WALK_HBP_CI`, `HOME_RUN`, `SINGLE`, `DOUBLE`, `TRIPLE`, `BIP_OUT`, `OTHER_REACH`. Each state has seven log odds against `OTHER_REACH`, effective sample size, entropy, days since evidence, 7/30/90-day counts, and an explicit missing-history flag. Every normalized row has a deterministic `stateRowId` and semantic `rowContentSha`.

## Tuning and candidates

The state policy grid is half-life `{30, 60, 120, None}` days crossed with prior ESS `{50, 150, 300}`. Selection uses a date-atomic chronological inner-2023 split and mean batter/pitcher posterior-predictive log loss. The selected policy is frozen before any 2024 or 2025 evaluation.

After that freeze, the runner reports posterior-predictive log loss and summed multiclass Brier separately for every role (`BATTER`, `PITCHER`), state kind (`A_PRESEASON`, `B_CUMULATIVE`, `C_RECENCY`), and governing fold (2024, 2025). These 12 records are descriptive evidence only: neither fold can change the frozen state policy. They are exposed at `component.metrics.statePosteriorPredictive` and in a dedicated content-addressed artifact.

The model candidates are:

- `D0`: the exact registered Phase 3 raw C4 fold predictions; never refit or relabelled.
- `D1`: context plus cumulative batter state.
- `D2`: context plus cumulative pitcher state.
- `D3`: context plus cumulative batter and pitcher state.
- `D4`: context plus recency batter and pitcher state.

`D1`–`D4` use true multinomial L2 logistic regression and the existing bounded C grid `{0.05, 0.2, 1.0}`. C is selected only on inner-2023 evidence. All four dynamic candidates train on 2023 and are compared on raw 2024 probabilities. The selected dynamic candidate is frozen using 2024 log loss, then Brier, then candidate ordinal. Only after selection are all candidates fit through 2024 and evaluated on 2025.

## Calibration, uncertainty, and decision

Raw probabilities are always retained. A scalar temperature is fit on the selected candidate's raw 2024 probabilities and applied unchanged to 2025. Scaled probabilities become the final variant only when log loss and summed multiclass Brier are both non-worse within `1e-10` on the 2024 eligibility gate and again on the governing 2025 gate. Raw, scaled, and final evidence remain present even when scaling is rejected.

Game-ID cluster bootstrap comparisons report selected-versus-D0 raw and final differences for log loss and Brier in both folds with 500 resamples and seed `20260817`. Missing-history and ESS-band subgroup metrics are retained.

Only raw selected probabilities can earn `DYNAMIC_STATE_RESEARCH_CHALLENGER`: raw log loss must improve on D0 in both folds, raw Brier must improve or tie within `1e-10` in both folds, and raw top-label ECE plus every raw classwise ECE may exceed D0 by at most `0.005` in each fold. Scaling and bootstrap evidence are reported but cannot earn the challenger decision. The exact decision enum is:

- `DYNAMIC_STATE_RESEARCH_CHALLENGER`
- `DYNAMIC_STATE_RESEARCH_BASELINE`
- `DYNAMIC_STATE_REJECTED`
- `DYNAMIC_STATE_BLOCKED`

## Artifacts and downstream state

The primary normalized state artifact contains the Phase 3 participant/date snapshot universe. A second content-addressed historical index stores daily eight-class sufficient statistics at `canonical_player_uuid + role + final_available_date + source_season` grain. Its strict loader verifies the descriptor, artifact bytes/SHA, Parquet metadata/schema, row identities/checksums, semantic content digest, source counts, and source partitions before reconstructing `HistoricalOutcomeIndex`.

Downstream participation code loads that ignored-runtime index and calls:

```python
history = load_historical_dynamic_index(artifact_bytes, descriptor=history_descriptor)
rows = dynamic_state_rows_for_keys(
    history,
    ((game_date, canonical_player_uuid, role), ...),
    policy=frozen_policy,
)
```

The result contains exactly one sorted `C_RECENCY` row per requested unique key, using the same row identity/checksum and state math as the primary artifact. This supports prior-only participation pool candidates without exchange rereads, target injection, or stale previous-game snapshots.

The registry-facing component has exactly these common keys: `componentId`, `componentType`, `contractName`, `contractSha`, `descriptor`, `candidates`, `selected`, `folds`, `metrics`, `calibration`, `bootstrap`, `coverage`, `decision`, `artifactIds`. Its `componentType` is `DYNAMIC_PLAYER_STATE`. Artifact references are returned separately.

Every referenced artifact is content-addressed by artifact ID, SHA-256, and byte count. JSON bodies carry a strict `artifactBindings` envelope and Parquet bodies carry the same canonical JSON in schema metadata. The binding records one creation time and code revision for the run (or the original immutable materialization for reused state/history), dataset manifest SHA, identity-bridge manifest SHA, Phase 3 feature-contract SHA, component contract SHA, temporal fold, exact dynamic/Phase 3 source partition IDs, and identical class/target order. The runner reconciles each external reference to the exact body bytes and validates these non-circular body bindings before returning the component.

The body binding also records `artifactType`; Parquet repeats that value in a dedicated schema-metadata field. A reference cannot relabel otherwise valid bytes. `DYNAMIC_STATE_POSTERIOR_PREDICTIVE` holds the 12 frozen role/state/fold records. `DYNAMIC_MODEL_CARD` holds the full selected candidate, folds, candidate metrics, posterior evidence, calibration, bootstrap, coverage, decision object, and dataset/bridge/Phase 3/state/history lineage. Its artifact inventory intentionally excludes its own reference to avoid a circular digest. `DYNAMIC_FINAL_CHECKPOINT` carries the full decision object, not only its enum label.

## Runtime safety and invocation

All outputs live under the ignored repository boundary `.runtime/asp-model-studio/sports-modeling/mlb-dynamic-player-state-v1`. Raw absolute paths are checked before resolution; symlink, junction/reparse, traversal, and hardlink substitution are rejected. A reused checkpoint must match freshly rebuilt semantic state and historical-index Parquet bytes after applying the original immutable materialization binding. This permits immutable reuse across code revisions without allowing a self-consistent stale checkpoint; current and materialization revisions remain in the descriptor.

Source validation reuses the existing governed cache at `.runtime/asp-model-studio/sports-modeling/dataset-validation/validation-cache.json`; Milestone A does not create a second validation authority. The cache must already exist as a non-reparse, single-link regular file, and validation must report exactly 329 hits and zero misses. Preflight prints those counts. The CLI opens only `.runtime/asp-model-studio/persistence/asp_model_studio.db`, initializes its migrations, and immediately calls `SportsPhase4Registry.validate_registered_authorities()` before any exchange or sports-modeling runtime read. Missing or tampered registered dataset, project, bridge, join-audit, Phase 3 run, feature, or graph authority blocks both preflight and the full run. After a full run, the same registry instance atomically registers the complete dynamic-only Phase 4 study. It prints the component, study, and graph IDs. Progress output explicitly identifies `Milestone A` / `Dynamic Player State`, reports fold/candidate/rows/errors/memory and available throughput, and reports an unavailable ETA honestly during blocking fits.

The public CLI is a supervisor; all validation, modeling, artifact writes, and registration occur in its worker process. Worker progress is an exact NDJSON protocol, and the same injected callback receives dataset, bridge, materialization, and every fit-stage event. The supervisor tracks the Windows Job Object process tree and hard-terminates the worker and descendants when any logistic operation exceeds 90 minutes, total runtime exceeds eight hours, protocol silence exceeds 90 seconds, or tree memory exceeds eight GiB. Kernel job memory accounting fails closed. A killed worker cannot register, while already atomically published content-addressed checkpoints remain reusable. Internal 30/45-second heartbeats and post-fit/stage-boundary gates remain defense in depth. With the 12 frozen role/state/fold evaluations, a typical live run is estimated at about 30–60 minutes with roughly 1.5–3 GiB working memory; this estimate has not been confirmed by launching the governed full run. The hard limits are deliberately higher.

Preflight only (database initialization, registered-authority validation, 329-hit warmed-cache proof, and source/runtime validation; no Phase 4 build or study registration):

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B scripts\run_mlb_dynamic_player_state.py `
  --exchange-root C:\Users\james\asp-model-exchange `
  --database .\.runtime\asp-model-studio\persistence\asp_model_studio.db `
  --preflight-only
```

Full research run, only after explicit approval:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B scripts\run_mlb_dynamic_player_state.py `
  --exchange-root C:\Users\james\asp-model-exchange `
  --database .\.runtime\asp-model-studio\persistence\asp_model_studio.db `
  --user-id target-local-administrator
```

Python API:

```python
result = run_mlb_dynamic_player_state(
    project_id=PROJECT_ID,
    parent=validated_parent,
    identity_bridge=validated_bridge,
    runtime_root=runtime_root,
    code_revision=content_bound_revision,
    progress=two_argument_callback,
)
component = result["component"]
artifacts = result["artifacts"]
```

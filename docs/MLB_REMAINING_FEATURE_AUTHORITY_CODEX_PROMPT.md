# Codex Implementation Prompt — Wave 1: MLB Governed Sufficient-Statistics Companion Table

Paste everything below the line into Codex. Scope is deliberately limited to Wave 1 of `docs/MLB_REMAINING_FEATURE_AUTHORITY_SCIENCE_AUDIT.md`. Do not extend it.

---

You are implementing **Wave 1** of the MLB remaining-feature-authority plan for ASP Model Studio, repository `C:\Users\james\asp-model-studio`.

## Scope (exact)

Publish a governed, point-in-time **sufficient-statistics companion table** beside the frozen Current Gold, so the governed prior engine can bind exact denominators for 12 of the 13 blocked prior features. Materialize **only** the integer components the Gold build already reads or computes. Do **not** change the 48-feature Gold contract, its manifest, or any published Gold object. Do **not** fit, score, calibrate, register a feature set, adopt a policy, or open final OOT.

Authoritative references (read before coding):
- `docs/MLB_REMAINING_FEATURE_AUTHORITY_SCIENCE_AUDIT.md` §4 (materialization contract) and §10 (Wave 1).
- `docs/MLB_REMAINING_FEATURE_AUTHORITY_MATRIX.json` (`waves.wave1.fields`).
- `server/sports_modeling/feature_view.py` (`_batting_features`, `_pitching_features`, `_prior_lookup`) — the exact annual components and Y−1 rule.
- `server/sports_gold/features.py` (`aggregate_pitch_history`, `prepare_pa_history`, `_prior_window_features`) — the exact rolling counts and the strict `gameDate < target.gameDate` window.
- `server/sports_current_statcast/gold.py` (`build_current_gold`, `_write_object`, manifest pattern).
- `server/sports_current_statcast/stage3_player_prior_authority.py` (`_BINDINGS`, `exposureFeature`).

## Safety (non-negotiable)

- Work only in a fresh isolated worktree from the current HEAD of `codex/mlb-governed-prior-engine-v1`; never in the primary checkout; never touch `C:\Users\james\worktrees\asp-remaining-authority-audit`.
- Preserve untracked `ASP_MLB_Feature_Treatment_Specification.xlsx` and `docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md`.
- No `reset`, `clean`, `stash`, force operations, history rewrite, `main` changes, or pushes.
- Never read the Gold `outcome` column in the new builder; never open `FINAL_OOT` rows for any statistic (rows may be carried by key only).
- Live project database: read-only except the single registration row described below, and only after tests pass.

## Deliverable 1 — builder

Add `server/sports_current_statcast/sufficient_stats.py` with `build_current_sufficient_stats(...)` that:

1. Loads the **verified** current Gold publication (`verify_current_gold`) and reuses its exact inputs: `_load_current_manifest`, `_current_paths`, `resolve_current_silver` for `fact_statcast_plate_appearance` / `fact_statcast_pitch`, `_load_dim_player`, `_load_player_priors` (FD1 `player_prior`, seasons ≤ 2025). Fail closed on any SHA mismatch exactly as `build_current_gold` does.
2. **Annual components** — for every Gold row, using the same `_prior_lookup(target_seasons=…)` selection (latest row with `season ≤ Y−1` and `eligible_from_season ≤ Y`, `identity_resolution_status == "EXACT"`, `same_season_predictor_eligible is False`), emit integers (NULL when the prior row is absent; **never 0 for absence**):
   - batting: `batter_prior_ab, batter_prior_h, batter_prior_2b, batter_prior_3b, batter_prior_hr, batter_prior_bb, batter_prior_hbp, batter_prior_sf, batter_prior_sh, batter_prior_so` from `metrics_json` keys `AB, H, 2B, 3B, HR, BB, HBP, SF, SH, SO` via the existing `_metric` (fail closed on missing/non-numeric/negative).
   - pitching: `pitcher_prior_ipouts, pitcher_prior_h, pitcher_prior_bb, pitcher_prior_hbp, pitcher_prior_bfp, pitcher_prior_g, pitcher_prior_gs` from `IPouts, H, BB, HBP, BFP, G, GS`.
   - also carry `batter_prior_eligible_from_season` / `pitcher_prior_eligible_from_season` (int16, nullable).
   - Do **not** materialize `ER` or `R`.
3. **Rolling components** — extend `aggregate_pitch_history` with one additional aggregate `fastball_velocity_sumsq = Σ(_fb_velo²)` (null-safe, 0.0 when no fastball velocity), thread it through `prepare_pa_history` `count_cols` and `_prior_window_features` `metric_columns`, and return the window sums (do not alter any existing Gold rate or its formula):
   - pitcher (last 250 BF, strictly before target `gameDate`, existing ordering `(entity, gameDate, mlbamGamePk, atBatNumber, canonicalPaId)`): `pitcher_last250_pitch_count, pitcher_last250_swing_count, pitcher_last250_whiff_count, pitcher_last250_fastball_count, pitcher_last250_breaking_count, pitcher_last250_offspeed_count, pitcher_last250_fastball_velocity_count, pitcher_last250_fastball_velocity_sum (float64), pitcher_last250_fastball_velocity_sumsq (float64)`.
   - batter (last 100 PA): `batter_last100_swing_count, batter_last100_whiff_count`.
   - Windows with zero prior history yield count 0 and the existing `*_insufficient` / `*_whiff_missing` / `*_velocity_missing` semantics remain the authority for missingness; do not add new flags.
   The cleanest implementation is to have `_prior_window_features` return the raw window sums alongside the rate payload (e.g., a second frame) so the Gold rates and the companion counts are produced from **one** pass and cannot diverge.
4. Output: one Parquet object with exactly one row per Gold `canonicalPaId` (697,729 today; same partitioning by season as Gold), columns `canonicalPaId, game_date, season, datasetRole` + the fields above, integer dtypes (`int32`/`int64`), **no outcome or target column**. Content-addressed under `mlb-current-statcast-gold-v1/objects/sha256/…` with a new publication manifest `MLB_CURRENT_STATCAST_SUFFICIENT_STATS_V1` (dataset id `gold-table:gold_mlb_current_pa_sufficient_stats_v1`) that records: the Gold manifest SHA it was built from, current Silver manifest SHA, FD1 manifest SHA, `dim_player` publication SHA, row count, per-season row counts, per-column non-null and zero counts (development rows only), and `historyCutoff: "annual: season <= Y-1 (eligible_from_season <= Y); rolling: source.gameDate < target.gameDate; same-date games excluded"`. Do **not** modify `current.json` for the Gold dataset; write a separate `current-sufficient-stats.json` locator.
5. Registration: one read-only-registration row for the new dataset in `sports_dataset_registrations` (and rights rows copied from the FD1 and current-Statcast registrations), following `scripts/register_current_statcast_dataset.py`. No feature set, no policy, no project activation.
6. CLI: `scripts/build_current_sufficient_stats.py` with `--verify-only` and `--no-publish-current`, mirroring `build_mlb_contextual_gold.py`.

## Deliverable 2 — prior-engine binding (bindings only; no fit)

In `server/sports_current_statcast/stage3_player_prior_authority.py`, extend `_BINDINGS` so these features declare their exact exposure and numerator components from the companion table (statuses become `READY_GOVERNED_PRIOR_V1` only when the companion columns are present and integer-validated; otherwise keep the existing BLOCKED reason):

| feature | method | exposure | numerator / components |
|---|---|---|---|
| `pitcher_last250_whiff_rate` | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `pitcher_last250_swing_count` | `pitcher_last250_whiff_count` |
| `batter_last100_whiff_rate` | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `batter_last100_swing_count` | `batter_last100_whiff_count` |
| `batter_last100_contact_rate` | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `batter_last100_swing_count` | `swing − whiff` (mark `derivedComplementOf: batter_last100_whiff_rate`; the audit retires it from feature sets) |
| `pitcher_last250_{fastball,breaking,offspeed}_usage` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES` (one family) | `pitcher_last250_pitch_count` | the three family counts, implicit `other = pitch_count − Σ` |
| `pitcher_last250_avg_fastball_velocity` | `NORMAL_NORMAL_EMPIRICAL_BAYES` | `pitcher_last250_fastball_velocity_count` | `fastball_velocity_sum`, `fastball_velocity_sumsq` |
| `pitcher_whip` | `GAMMA_POISSON_COMPONENT_SHRINKAGE` | `pitcher_prior_ipouts` | `pitcher_prior_h`, `pitcher_prior_bb` (WHIP posterior = 3·(H̃+B̃B)/IPouts) |
| `pitcher_gs_per_g` | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `pitcher_prior_g` | `pitcher_prior_gs` |
| `batter_avg` | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `batter_prior_ab` | `batter_prior_h` |
| `batter_obp` | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `batter_prior_ab + bb + hbp + sf` | `h + bb + hbp` (mark `retiredFromFeatureSets: true`) |
| `batter_slg` | `DIRICHLET_MULTINOMIAL_COMPONENT_SHRINKAGE` | `batter_prior_ab` | `{1B = H−2B−3B−HR, 2B, 3B, HR, AB−H}` (SLG posterior from shrunk components) |
| `pitcher_era9` | unchanged — remains BLOCKED (`ER` deliberately not materialized; audit verdict RETIRE) |

Implementing the actual Dirichlet/Gamma/Normal fitting is **Wave 2**; in this wave only the bindings, integer validation (`rate × exposure` reconstructs the numerator within `1e-6` for every non-null existing rate), and the READY/BLOCKED status logic change. Recompile the treatment spec as a **new DRAFT** only; do not adopt.

## Tests (must fail before, pass after, and be added under `tests/`)

1. **Equivalence**: for every development row and every existing Gold rate among the 13, `rate == numerator / exposure` from the companion table within `1e-6` (NULL-for-NULL). Include `contact_rate == 1 − whiff_rate` and usage shares from the counts.
2. **Point-in-time (rolling)**: mutating a target PA's pitch results/outcome changes none of that PA's count columns; shifting one PA's date earlier changes only the windows of later PAs; same-date PAs are excluded.
3. **Point-in-time (annual)**: season-Y rows equal the Y−1 (or latest eligible earlier) `metrics_json`; adding a season-Y `player_prior` row never changes season-Y outputs; a rookie yields NULL counts and `*_prior_missing = 1`, never 0.
4. **Future isolation**: appending 2026 rows leaves 2023–2025 companion rows byte-identical.
5. **Determinism**: two builds produce identical object and manifest SHAs.
6. **Gold immutability**: the Gold manifest SHA, `current.json`, and all 48-feature objects are byte-identical before/after; the feature contract still reports exactly 48 features.
7. **Target isolation**: the builder's column projection never includes `outcome`; assert via the Parquet read schema.
8. **OOT**: FINAL_OOT rows may be carried by key; assert no statistic is computed from any FINAL_OOT pitch or PA (their `gameDate ≥ 2026-08-14` must never enter any window because no development target date exceeds 2026-08-13; assert `max(history gameDate used) ≤ 2026-08-13` for development targets).
9. **Registration**: one registration row, rights rows copied, zero feature sets, zero adopted policies, historical executable artifact `stage3-executable-artifact-11dc936dcf9d558fe3d8f0a179615b19` SHA `58ddf83092c2e91fde4c61c35f16c8cc5a3702d3a4da8f9f9164f2eab5641f6b` unchanged.
10. Existing suites stay green: `tests/sports_stage3_player_prior_authority_test.py`, `tests/current_statcast_pa_test.py`, `tests/sports_current_gold_stage2_review_test.py`, frontend `npm run test:sports-product`, `npm run build:modeling`.

## Report back (exact)

Worktree/branch/HEAD before and after; main HEAD unchanged; files changed; the new dataset id, manifest SHA, object SHA(s), row count; per-column non-null counts for development rows; the equivalence test's maximum absolute reconstruction error; prior-blocker counts before (13) and after (expected 12 bindable, `pitcher_era9` still BLOCKED); confirmation of 0 model fits, 0 OOT rows read, 0 target reads, 0 Gold mutations, 0 policy adoptions, 0 feature-set registrations, 0 pushes; commits created (logical: builder, engine bindings, tests, docs).

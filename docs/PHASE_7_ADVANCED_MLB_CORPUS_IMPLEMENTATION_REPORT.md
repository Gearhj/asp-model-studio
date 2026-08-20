# Phase 7 — Advanced MLB Corpus & Gen-3 Development Integration · Implementation Report

**Repo:** asp-model-studio · **Branch:** `phase7-advanced-mlb-data-integration` (from `a95b197`)
**Scope executed:** the governed, no-download **Gen-3 2021–2023 development-population extension** and its
training-volume ablation. The advanced Statcast pitch-level corpus is designed and scoped (see the Plan
doc) but **not acquired in this session** — it is documented below as the remaining production-feed work,
not fabricated.

---

## 1. What was built (and why no download was needed)

The registered FD1 dataset package (at `ASP_MODEL_EXCHANGE_ROOT/datasets/mlb-fd1/<sha256>/`) **already
contains source plate-appearance partitions for 2021–2025** plus the `player_prior` family — the same
governed source that produced the Gen-2 view. The Gen-2 builder (`feature_view.build_mlb_pa_feature_view_v1`)
is deliberately frozen to 2023–2025 (`TARGET_SEASONS` + a `population_category == GEN2_PRIMARY_2023_2025`
assertion) under the Phase-6E PRIOR_ONLY_HISTORY contract. Phase 7 adds a **parallel governed pathway**
(`server/sports_modeling/feature_view_gen3.py`) that reuses the exact identity resolution, prior lookup,
and per-row feature math, widening only the season gate (2021–2025) and the population gate (accepting
`GEN2_PRIOR_ONLY_2021_2022` as well). The frozen Gen-2 view is untouched.

**Materialization** (`scripts/phase7_build_gen3.py`, output under the gitignored
`.runtime/…/mlb-pa-gen3-v1/`):

| Season | Materialized PA rows | Registered source | Quarantined | Role |
|---|---|---|---|---|
| 2021 | 181,732 | 181,818 | 86 | development (prior-blind) |
| 2022 | 181,972 | 182,052 | 80 | development |
| 2023 | 184,104 | 184,104 | 0 | development |
| 2024 | 182,449 | 182,449 | 0 | validation / selection |
| 2025 | 182,926 | 182,926 | 0 | secondary OOT (sealed) |
| **Total** | **913,183** | 913,349 | 166 | — |

**Development population grows from 184,104 (2023-only) to 547,808 (2021–2023) — a 2.97× increase**,
meeting the "more than double, nearly triple" objective. Content SHA-256 of the Gen-3 parquet:
`a11d287372f30552…`. Partition authority: `8dec143b06622af0…`. Bridge:
`sports-identity-bridge-manifest:sha256:6b69e7dcf4c5db76…`.

## 2. Base-feature parity (correctness proof)

The ablation harness verifies, by a vectorized join on `plate_appearance_id`, that the Gen-3 view's 22
base features equal the frozen Gen-2 view on every overlapping row: **549,479 rows compared, 0 feature
mismatches, identical = True.** Independently, the Gen-3 build's 2023–2025 prior-coverage reproduces the
frozen `EXPECTED_PRIOR_COVERAGE` exactly (e.g. 2023 BATTER 169,005 eligible / 15,099 missing; 2023
PITCHER 159,568 / 24,536; 2024 BATTER 170,594 / 11,855). The base-feature semantics are therefore
identical across all seasons — the requirement for a fair training-volume ablation.

## 3. Point-in-time / knowledge-time integrity

- `player_prior` season=Y carries `eligible_from_season = Y+1`, `same_season_predictor_eligible = False`.
  Target season S resolves the latest prior with `prior_season ≤ S−1` and `eligible_from ≤ S`. **Every
  2021 target PA is legitimately prior-blind** (`batter_prior_missing = pitcher_prior_missing = True`,
  eligible = 0/181,732) because the earliest partition is 2021 (eligible from 2022); 2022 and 2023 are
  prior-valid. This is a real, documented property (matches `GOVERNED_TEMPORAL.priorOnlyReason`), surfaced
  via the existing `*_prior_missing` indicators — not hidden.
- The FD1 PA rows already carry the leakage contract fields (`available_only_after_game_final`,
  `target_only_not_pregame_feature=True`, `strict_same_game_pregame_eligible=False`,
  `timing_risk_label`), which the Gen-3 gate re-asserts per row.

## 4. Compatibility hazards handled (Gate 6)

- **2021 NL pitchers batting / 2022 universal DH:** `designated_hitter_used` present in source; batter
  identity resolves through the same bridge; no special-casing needed for the base view.
- **Doubleheaders / suspended games:** `doubleheader_id`, `game_number`, `game_suspended`,
  `suspension_completion_date` present; lineage keys (`plate_appearance_id`) remain unique.
- **Extra-inning tail beyond the frozen contract:** 27 PAs (2021: 20 in innings 15–16; 2022: 7 in inning
  15) exceed the frozen `context_inning ≤ 14` schema (2023–2025 never exceed 14) → quarantined as
  `EXTRA_INNING_BEYOND_CONTRACT` to preserve identical feature semantics.
- **Relocated / neutral-site "home" games:** 139 PAs (2021: 66, 2022: 73) where home/visiting labels do
  not follow the batting-half convention (e.g. Toronto's 2021 home games at Dunedin/Buffalo) → quarantined
  as `BATTING_TEAM_CONVENTION_ANOMALY` rather than fed a possibly-wrong `score_difference`.

## 5. Fail-closed quarantine (Gate 3/4/17)

166 anomalous 2021/2022 rows are **explicitly quarantined with a reason and count** in
`gen3-reconciliation.json` — never silently dropped. Reconciliation closes exactly per season
(materialized + quarantined == registered source: 181,732 + 86 = 181,818; 181,972 + 80 = 182,052). Zero
quarantine in 2023–2025 (parity). No unresolved-identity rows entered the modeling view.

## 6. Temporal authority (Gate 8): `MLB_GEN3_TEMPORAL_CONTRACT_V1`

Constants live in `feature_view_gen3.py`: development **2021–2023**, validation/selection **2024**,
secondary OOT **2025** (sealed — never used for selection, not auto-scored), prospective sealed **2026**
(untouched). Prior history 2019–2020 is documented as the acquisition needed to make 2021 fully
prior-valid (deferred).

## 7. Security / containment (Gate 18)

Ingestion/build runs as trusted local developer tooling (`scripts/phase7_*`), never through the
application's user-code execution route. All runtime/raw artifacts live under the gitignored
`.runtime/asp-model-studio/…/mlb-pa-gen3-v1/`; nothing raw enters git. No absolute host paths are
hard-coded into application science (the builder takes the validated package + bridge as inputs; the
runner resolves the exchange root from env/`.env.local`). The Gen-3 view does not reuse the sports-cockpit
experiment namespace as authority.

## 8. Tests (Gate 19)

`tests/sports_modeling_phase7_gen3_test.py`: temporal-contract invariants (2025 never development, 2026
absent), builder season/population gate, 2021 prior-blindness + 2022/2023 prior-validity, **exact
prior-coverage parity with frozen Gen-2**, explicit quarantine (reasons, reconciliation closure, none in
2023–2025), and Gen-3 schema (22 base features + target + season). Parquet-dependent tests skip cleanly
if Gen-3 is not materialized.

## 9. Known limitations / remaining production-feed work

- **Advanced Statcast corpus (Gates 1A/2/5/9/10/11/16)** — pitch-level discipline/contact/arsenal/bat-
  tracking families require acquiring ≈25M Statcast pitches (2019–2025); designed + availability-matrixed
  in the Plan doc, **not acquired or fabricated** here. Est. ~2–4 GB compressed, multi-hour chunked
  download + transform, network-gated.
- **2019–2020 prior history** — needed to make 2021 fully prior-valid (Lahman-2020 → `player_prior` 2020);
  deferred. 2021 currently participates as a prior-blind development band.
- **Full Data-Warehouse/UX/server-execution-authority selection of the Gen-3 view (Gates 12–14)** — the
  Gen-3 view is materialized + governed + ablation-proven, but not yet wired as a selectable server-
  authorized dataset version in the cockpit UI; this is the next integration step.
- **B0–B7 advanced-family study (Gate 15B)** — blocked on the Statcast corpus.

## 10. Guarantees

D3/C4 changed = no · retrained = no · registered champion overwritten = no · Gen-2 view modified = no ·
target changed = no · 2021 added as development target = **yes** (prior-blind, governed via
`feature_view_gen3` + `MLB_GEN3_TEMPORAL_CONTRACT_V1`) · 2022 added = **yes** (prior-valid) · 2023
development retained = yes · 2024 = selection only · 2025 used for fitting/feature/hyperparameter
selection = no · 2025 auto-scored = no (sealed behind `--run-secondary-oot-2025`) · 2026 touched = no ·
raw data committed = 0 · credentials printed = 0 · provider calls outside allowlist = 0 · security
weakened = no · pushes = 0 · main modified = no.

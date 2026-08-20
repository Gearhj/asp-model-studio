# Phase 7 — Advanced MLB Data Integration · Gate 0/1 Preflight & Plan

**Repo:** asp-model-studio · **Branch:** `phase7-advanced-mlb-data-integration` (from `a95b197`)
**Status of this document:** read-only preflight (Gate 0) + source/license manifest (Gate 1) + governed
execution plan. No data was downloaded to produce it.

---

## 0. Executive preflight finding (decisive)

The single most important preflight result: **the registered FD1 dataset package already contains
source plate-appearance partitions for 2021–2025**, partitioned `season=/month=`, at the governed model
exchange (`ASP_MODEL_EXCHANGE_ROOT → datasets/mlb-fd1/<sha256>/parquet/plate_appearance/`). Verified row
counts per season:

| Season | PA rows | Population category | Prior availability |
|---|---|---|---|
| 2021 | 181,818 | `GEN2_PRIOR_ONLY_2021_2022` | **prior-blind** (no ≤2020 `player_prior`) |
| 2022 | 182,052 | `GEN2_PRIOR_ONLY_2021_2022` | valid (uses 2021 prior) |
| 2023 | 184,104 | `GEN2_PRIMARY_2023_2025` | valid (uses 2022 prior) |
| 2024 | 182,449 | `GEN2_PRIMARY_2023_2025` | valid (uses 2023 prior) |
| 2025 | 182,926 | `GEN2_PRIMARY_2023_2025` | valid (uses 2024 prior) |

Consequence: **the PRIMARY objective — making 2021–2023 real, executable development target rows with
the base 22-feature semantics — requires NO external download.** It is achievable by extending the
existing governed feature-view build to 2021–2022 (a parallel Gen-3 pathway that reuses the exact
identity/prior/feature helpers), because the Gen-2 builder is deliberately frozen to 2023–2025
(`TARGET_SEASONS` + a `population_category == GEN2_PRIMARY_2023_2025` assertion) by the Phase-6E
PRIOR_ONLY_HISTORY contract.

`player_prior` semantics (verified): a `player_prior` row for `season=Y` carries
`eligible_from_season = Y+1` and `same_season_predictor_eligible = False`; target season S resolves the
latest prior with `prior_season ≤ S−1` and `eligible_from ≤ S`. The earliest partition is `season=2021`
(eligible from 2022), so **every 2021 target PA is legitimately prior-blind** (matches
`GOVERNED_TEMPORAL.priorOnlyReason`). 2022 and 2023 targets are fully prior-valid.

---

## 1. Environment inventory (Gate 0.4)

Python 3.12.6 · pandas 2.2.1 · pyarrow 25.0.0 · duckdb 1.5.5 · polars 1.43.0 · numpy 1.26.4 ·
httpx 0.27.0 · scikit-learn 1.6.1. **Not installed:** `requests`, `pybaseball`, `kaggle`.
Decision: use `httpx`/direct Baseball Savant CSV endpoints (no `pybaseball` dependency added to the app
venv); **Kaggle sources are excluded** (no credentials; the prompt requires core completion to not depend
on Kaggle). Disk: **252 GB free** on C: — ample. No global upgrades to the app environment.

## 2. Existing ASP data contracts audited (Gate 0.1)

- **Dataset:** `asp.mlb.open-data.fd1` (`server/sports_datasets/constants.py`), consumed from
  `ASP_MODEL_EXCHANGE_ROOT/datasets/mlb-fd1/<content-sha>/` via `SportsDatasetManifestConsumer`.
  Families present: `plate_appearance, player_prior, player_game_batting/pitching/fielding,
  play_transition, pitch_sequence, bullpen_usage, starter_usage, weather`.
- **Identity bridge:** `MlbFd1IdentityBridgeAdapter` (BRIDGE_MANIFEST_SHA `6b69e7d…`) → `retrosheet_aliases`
  (retro id → canonical uuid) + `dimension_uuids`. Registered under
  `.runtime/…/sports-modeling/identity-bridges/`.
- **Gen-2 feature view:** `server/sports_modeling/feature_view.py::build_mlb_pa_feature_view_v1` →
  content-addressed parquet under `.runtime/…/mlb-pa-v1/objects/sha256/**/mlb-pa-feature-view-v1.parquet`,
  **2023–2025 only, 549,479 rows, 22 features** (5 context + 8 batter + 9 pitcher). `TARGET_SEASONS=(2023,
  2024,2025)`, `EXPECTED_TOTAL_ROWS=549,479`. Cockpit reads it via `engine._feature_view_path()`.
- **Provenance:** the FD1 PA family carries knowledge-time/leakage fields already — `game_date`,
  `event_date`, `available_only_after_game_final`, `final_available_date`, `strict_same_game_pregame_eligible`
  (False), `target_only_not_pregame_feature` (True), `timing_risk_label`, `designated_hitter_used`,
  `doubleheader_id`, `game_number`, `game_suspended`, `suspension_completion_date`, `retrosheet_game_id`,
  `park_id`, `game_type`. This is the raw material for both the game/identity bridges and knowledge-time.

`.runtime/` is gitignored (verified `git check-ignore`); the Gen-3 namespace path is ignored. Worktree has
only the anticipated untracked `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md` (preserved, unstaged).

## 3. Source matrix (Gate 1)

| Source | Grain | Join key | Terms | Knowledge-time | Phase-7 role |
|---|---|---|---|---|---|
| **FD1 package (already registered)** | PA (2021–2025) + player_prior | canonical uuid via bridge; retro game id | ASP-governed RETROSHEET/Lahman derivation | fields already present | **CORE — base-22 Gen-3 2021–2023 dev rows (no download)** |
| Baseball Savant / Statcast | pitch / PA | `game_pk`, `at_bat_number`, `pitch_number`; batter/pitcher MLBAM | MLBAM public research | pregame trailing only | Advanced feature corpus (discipline/contact/arsenal/bat-tracking) — **acquisition required, deferred** |
| Retrosheet | event/game/roster | retro game id, retro player id | Retrosheet attribution required | pregame | 2019–2020 prior history; umpire/lineup enrichment — deferred |
| Chadwick register | person xref | key_mlbam/key_retro/key_bbref/key_uuid | public domain | n/a | canonical identity authority V2 — deferred |
| SABR Lahman | season/player | playerID/bbref | public (CC BY-SA 3.0 attribution) | season-complete | 2020 priors for prior-valid 2021; season features — deferred |
| Kaggle mirrors | varies | MLBAM/season | Kaggle terms | n/a | **excluded** (no creds; non-authoritative) |

## 4. Bronze/Silver/Gold + bridges (Gates 2–7) — design

- **Bronze:** immutable source-native partitions under `.runtime/asp-model-studio/mlb-advanced-corpus/bronze/`
  (`source=/season=/month=`), content-addressed with per-chunk manifest (source, date range, retrieval UTC,
  status, rows, cols, schema hash, SHA-256, adapter version). Statcast in ≤monthly chunks.
- **Silver:** normalized `fact_statcast_pitch`, `fact_statcast_plate_appearance`, `dim_player`, `dim_game`,
  `bridge_player_identity` (Chadwick UUID authority, exact MLBAM/retro/bbref joins, **no fuzzy join in
  production**; ambiguity → quarantine report), `bridge_game_identity` (date→home→away→type→DH-number→time,
  one-to-one, doubleheaders/suspensions explicit, fail-closed).
- **Gold:** `MLB_ADVANCED_PA_FEATURE_VIEW_V1` — one row per target PA with knowledge-time cutoff and lineage
  fingerprints (dataset/target/knowledge-time/temporal/catalog SHAs).
- The **existing FD1 bridge already provides the canonical player identity + retro game id** for
  2021–2025, so the Gen-3 base view reuses it directly; Statcast integration adds MLBAM→canonical via the
  same bridge (extended with Chadwick where needed).

## 5. Temporal contract (Gate 8): `MLB_GEN3_TEMPORAL_CONTRACT_V1`

Prior history 2019–2020 · **development 2021–2023** · validation/selection **2024** · secondary OOT **2025**
(never used for selection; not auto-scored) · prospective sealed **2026** (not touched). 2021 is retained
as a prior-blind development band (documented); fully prior-valid 2021 requires 2020 `player_prior`
(Lahman-2020 acquisition — deferred).

## 6. Advanced feature catalog (Gate 9) — designed, Statcast-gated

Families A–J are specified in `MLB_ADVANCED_FEATURE_CATALOG_V1` (plate discipline; contact quality; pitch-
type profile; pitcher arsenal; contact suppression; batter×pitcher matchup; workload/rest; game/environment;
reliability/sample-size; **Bat Tracking 2024+ as a separate non-comparable family**). All point-in-time,
strict `< knowledge_time`. These require the Statcast corpus and are **not fabricated** in this phase; the
schema-availability matrix (2019–2025) accompanies the implementation report.

## 7. This-session scope (honest)

**Executed now (no download, fully governed):**
1. Gen-3 base feature build 2021–2025 via a parallel governed builder that reuses the exact
   identity/prior/feature helpers (`server/sports_modeling/feature_view_gen3.py`); 2023–2025 output is
   verified byte-identical to the frozen Gen-2 view (parity proof).
2. `MLB_GEN3_TEMPORAL_CONTRACT_V1` + the **A0/A1/A2 training-volume ablation** (dev {2023} vs {2022–23} vs
   {2021–23}; select on 2024; 2025 sealed behind `--run-secondary-oot-2025`).
3. Focused tests + implementation & ablation reports + local commits. D3/C4, Gen-2, 2025-selection, 2026 —
   untouched.

**Deferred (documented as remaining production work, not fabricated):** Statcast acquisition (≈25M pitches
2019–2025) and the advanced feature families; 2019–2020 prior-history acquisition; full Data-Warehouse/UX/
server-execution-authority integration for the Gen-3 view; the B0–B7 advanced-family study; Kaggle
reconciliation. Resource estimate for Statcast: ~2–4 GB compressed, dozens–hundreds of chunked Savant CSV
requests, multi-hour download + transform — beyond a single safe session and gated on network reliability.

## 8. Go/no-go (Gate 0.6)

Disk ✅ · storage stays out of git ✅ · no unexpected tracked mods ✅ · core independent of network/Kaggle ✅.
**Proceed** with the executed scope above; treat Statcast acquisition as a separate, network-gated follow-on.

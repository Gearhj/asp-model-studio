# MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1 — Governed Contract (E1)

**Type:** Feature family / materialization (leakage-safe plate-discipline *process*
features). **Not** a model. **Phase:** Phase 4C (E1). Trains nothing, evaluates
nothing, claims no predictive improvement. The class order and target are unchanged.

---

## 1. Purpose

Exploit the **free** governed FD1 pitch-sequence evidence as far as it honestly goes,
building leakage-safe batter and pitcher *process* features (ball/strike/foul/in-play
tendencies, two-strike and first-pitch behaviour, pitches-per-PA) that plausibly bear
on D3's known STRIKEOUT and WALK_HBP_CI weaknesses — **before** buying premium
tracking data. Any predictive value is proven only later, in a separate governed
experiment.

## 2. Source schema authority

Family `pitch_sequence` (`retrosheet_fd1_...`, one row per PA):
`game_id`, `game_date`, `season`, `plate_appearance_id`, `half_play_number`,
`batter_id`, `pitcher_id`, `source_pitch_sequence` (String), and
`source_pitch_code_characters` (List[String]). Encoding declared by
`source_event_granularity = RETROSHEET_PLAY_PITCH_SEQUENCE_NOT_STATCAST_PITCH`;
`velocity_available = movement_available = location_available =
contact_tracking_available = False`. Identity is exact canonical (Retrosheet) IDs;
**no names, no fuzzy matching.**

## 3. Parser semantics (`MLB_PITCH_SEQUENCE_PARSER_V1`)

Deterministic, source-version aware, idempotent, no silent dropping. Supported
categories and codes (measured 100% classified on real 2021–2025 data):

| Category | Codes |
|----------|-------|
| BALL | B, V (automatic ball) |
| CALLED_STRIKE | C, A (automatic strike) |
| SWINGING_STRIKE | S, M (missed bunt), T (foul tip) |
| FOUL | F, L (foul bunt), O (foul tip on bunt) |
| IN_PLAY | X |
| HIT_BY_PITCH | H |
| PITCHOUT | P (counts as a ball for count state) |
| NON_PITCH (skipped; never advances count) | `.` `>` `*` `+` `1` `2` `3` `N` `R` |

Every other symbol is counted as **UNKNOWN** (explicit, never dropped). Count-state
reconstruction: ball → balls+1; called/swinging strike → strikes+1 (cap 2); foul →
strikes+1 only if strikes < 2; IN_PLAY / HIT_BY_PITCH terminal. `first_pitch_strike`
= first delivered pitch is called/swinging/foul/in-play. `reached_two_strikes` =
count reached 2 strikes. Two-strike sub-events counted after reaching two strikes.

Explicitly **not decoded** (absent from free data, never inferred): velocity, pitch
type, spin, movement, location, target, catcher call, swing speed, exit velocity,
launch angle.

## 4. Strict temporal policy

Features for a target PA in game G on date D use **only** evidence strictly before D.
Excluded: the target PA's own pitches; all PAs on date D (doubleheaders included);
future evidence; same-season final totals; terminal target info. Same strict
prior-date standard as D3 / Milestone B (implemented via per-(entity, day) cumulative
sums + `merge_asof(..., allow_exact_matches=False)`).

## 5. Feature families

For each of **batter** and **pitcher**, and each window **cumulative** (all prior
dates) and **trailing-30-day**:
`prior_pas`, `prior_pitches`, `ball_rate`, `called_strike_rate`,
`swinging_strike_rate`, `foul_rate`, `in_play_rate`, `two_strike_pa_rate`,
`first_pitch_strike_rate`, `pitches_per_pa`, `missing_history`, `low_sample`
(prior_pas < 25). Rates are null when the denominator is 0.

**Windows tradeoff:** cumulative + trailing-30-day are materialized. Trailing-60/90-day
are deferred (runtime), reconstructable from the same day-level cumulative table.

## 6. Missingness / sample-size rules

Never filled from future or full-season evidence. Players with no prior history carry
`missing_history = 1` and null rates; `low_sample` flags thin history. Every rate has
its `prior_pas` / `prior_pitches` denominator alongside it.

## 7. Count-state features status

Two-strike reach and first-pitch-strike are materialized (reliably reconstructable).
Granular 0-2 / 1-2 / 2-2 / 3-2 reach rates are **PARTIAL** (reconstructable from the
same parser but not materialized in V1) and are marked as such — not approximated.

## 8. Absolute exclusions

No model training/evaluation; no interaction (E2) features; no archetypes; no
handedness/platoon; no premium/Statcast; no class/target change; no game simulator.

## 9. E2 forward contract (design only)

Future E2 combines batter process state × pitcher process state (e.g. batter
swinging-strike rate × pitcher swinging-strike rate; batter ball rate × pitcher ball
rate; batter first-pitch-strike exposure × pitcher first-pitch-strike tendency; batter
two-strike vulnerability × pitcher two-strike dominance). Not materialized here.

## 10. Artifact storage & version identity

Materialized feature matrix is a content-addressed zstd Parquet under ignored runtime
storage (`.runtime/asp-model-studio/sports-phase4/pitch-sequence-features/`), logical
URI `asp-model-studio-runtime://sports-phase4/pitch-sequence-features/...`; **never
committed**. Version identity = contract SHA + parser version + dataset authority +
code revision → `materializationId`. Readiness JSON is registry-ready evidence.

## 11. Terminal statuses

`PITCH_SEQUENCE_FEATURES_READY` / `PITCH_SEQUENCE_FEATURES_PARTIALLY_READY` /
`PITCH_SEQUENCE_FEATURES_BLOCKED`, decided from measured parse quality + coverage.
READY means the features are materialized and leakage-safe — **not** that a catcher/
strikeout/walk effect is proven predictive.

## 12. Implementation

`server/sports_phase4/pitch_sequence_features.py` (parser),
`server/sports_phase4/pitch_sequence_run.py` (vectorized materialization),
`scripts/run_mlb_pitch_sequence_features.py` (CLI). Tests:
`tests/sports_phase4_pitch_sequence_features_test.py`,
`tests/sports_phase4_pitch_sequence_run_test.py`.

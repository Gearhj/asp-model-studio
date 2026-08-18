# MLB_CATCHER_INFLUENCE_READINESS_V1 — Governed Contract

**Type:** Data-availability & sample-support **readiness audit**.
**Not** a predictive model. **Phase:** Phase 4 (companion to Milestone B).
**Status at authoring:** implemented and **READY_TO_RUN**; no audit has been
executed, so **no coverage numbers exist yet** (they are produced only when the
operator runs the audit against the governed dataset).

---

## 1. Purpose (and explicit non-purpose)

This component measures **how much catcher and pitcher-catcher battery evidence
exists** in the current free historical dataset, **how reliably catcher identity
can be reconstructed**, and **how sparse** pitcher-catcher and catcher-batter
histories actually are — so a future catcher/battery study can be *designed*
against real coverage.

It explicitly **does not**:
- estimate causal catcher quality or any catcher effect;
- claim the catcher personally **called** a pitch (no caller identity exists in
  free data);
- estimate framing without pitch-location/tracking evidence;
- produce betting predictions or any model performance metric.

## 2. Approved terminology

- **CATCHER_ASSOCIATED_EFFECT** — an association between the catcher on the field
  and outcomes (not proof of causal catcher skill).
- **PITCHER_CATCHER_BATTERY_EFFECT** — a joint pitcher+catcher association.
- **CATCHER_BATTER_ARCHETYPE_INTERACTION** — a catcher × batter-archetype
  association.

"Catcher called pitch" is **not** used as observed evidence unless a future
authoritative source identifies the caller.

## 3. Catcher identity reconstruction

Catcher identity is reconstructed from **exact canonical identities** (via the
governed identity bridge) using defensive appearances (`player_game_fielding`
catcher starts), and — where present — ordered in-game substitution events. **No
player names / fuzzy inference.**

- **Starting catcher per team-game:** DETERMINISTIC (exactly one catcher start),
  AMBIGUOUS (more than one), or MISSING (none). A second catcher start is never
  silently chosen.
- **Catcher active at each PA:** assigned by `pa_index` interval between
  substitutions. A **contradictory** substitution chain marks the remainder
  AMBIGUOUS — never forward-filled through ambiguity.
- Ambiguous and missing intervals are reported, not hidden.

## 4. Temporal classification

- **STRICT PREGAME ELIGIBLE** — prior-date catcher workload/rest/history.
- **PRIOR-HISTORY ELIGIBLE** — pitcher-catcher and catcher-batter prior-PA counts,
  computed strictly before the target game (no target-PA self-inclusion; same-date
  ties excluded via `bisect_left`).
- **RETROSPECTIVE TARGET/ANALYSIS ONLY** — the current-game reconstructed catcher
  identity itself (not a strict pregame predictor until a future lineup source
  supplies it before game time).
- **UNAVAILABLE** — premium/tracking fields (see §8).

A future model's predictors must use only prior-to-target evidence. Retrospective
reconstruction is not blurred with prospective availability.

## 5. Coverage metrics (produced at run time)

Per season present in the package (2021–2025), with **2023–2025** reported
separately as the primary modeling-readiness population: games/team-games, games
with deterministic starting catcher, starting-catcher coverage rate, plate
appearances, PAs with deterministic catcher assignment, PA coverage rate,
ambiguous PAs, missing PAs, catcher substitutions, unique catchers, catcher
starts/appearances.

## 6. Prior-history sample-size distributions

For **pitcher-catcher battery** and **catcher × batter**, over the modeling
population, with strict prior-only counting (target PA never in its own history):
bands `0 / 1-9 / 10-24 / 25-49 / 50-99 / 100-249 / 250+`; unique pairs; median /
p75 / p90 / p95 / max prior PAs; and `>=25 / >=50 / >=100 / >=250` fractions.
Starters and relievers are separated where role evidence supports it.

## 7. Battery fallback readiness levels

Each modeling unit maps to the lowest defensible level (these are **readiness**
thresholds, not proven-optimal modeling thresholds):

| Level | Min prior samples | Meaning |
|-------|-------------------|---------|
| LEVEL_0_LEAGUE_GLOBAL | 0 | League/global fallback only |
| LEVEL_1_MAIN_EFFECTS | 1 | Pitcher-only / catcher-only main effects |
| LEVEL_2_CATCHER_POOLED | 25 | Catcher-level pooled effect defensible |
| LEVEL_3_BATTERY_POOLED | 50 | Pitcher-catcher battery pooled effect defensible |
| LEVEL_4_BATTERY_SPECIFIC | 250 | Well-supported battery-specific effect |

Because direct catcher-batter pair history is expected to be sparse, a future
model should prefer catcher main effect + batter-archetype interaction +
hierarchical partial pooling + league fallback over per-pair estimation.

## 8. Free feature inventory & premium gaps

Free/derivable catcher features are labeled AVAILABLE / DERIVABLE /
PARTIALLY_AVAILABLE / UNRELIABLE / UNAVAILABLE (confirmed against the resolved
schema at run time). Fields that current free evidence does **not** support —
pitch target/actual location, framing, called-strike-probability-added, Blocks
Above Average, blocking difficulty, pop time, arm strength, throw velocity,
exchange time, **catcher pitch-caller identity**, pitcher execution vs target,
and all **ABS challenge** fields — are classified
PREMIUM_TRACKING_LIKELY_REQUIRED / NEW_DATA_SOURCE_REQUIRED / CURRENTLY_UNAVAILABLE
and are **never fabricated**.

## 9. Terminal readiness statuses

- **CATCHER_INFLUENCE_READY_FOR_RESEARCH_DESIGN** — high starting-catcher
  reconstruction coverage (≥0.97), high PA assignment coverage (≥0.90), reliable
  identity linkage, quantified battery distribution, honest feature inventory.
  READY authorizes a future study **design** only; it does **not** prove any
  catcher effect predictive.
- **CATCHER_INFLUENCE_PARTIALLY_READY** — usable starting-catcher coverage but
  incomplete PA-level assignment/evidence.
- **CATCHER_INFLUENCE_DATA_AUDIT_BLOCKED** — reconstruction or linkage coverage
  insufficient on current free evidence.

## 10. Future model design (documentation only — `MLB_CATCHER_AND_BATTERY_EFFECT_V1`)

Nested ablation, no coefficients estimated here:
`M0` batter+pitcher+D3 state → `M1` +catcher main effect → `M2` +battery
interaction → `M3` +catcher-batter archetype interaction → `M4` +free
pitch-sequence tendencies → `M5` +premium tracking/framing/blocking. Hierarchical
partial pooling shrinks sparse batteries toward pitcher, catcher, archetype, then
league effects.

## 11. Integration

- **Registry:** the audit produces a content-addressed, registry-ready payload
  (contract ID/SHA, run ID, dataset + identity-bridge authority, seasons, coverage,
  battery/catcher-batter distributions, feature inventory, premium gaps, terminal
  status, limitations). No predictive model or performance metric is registered.
- **Model graph:** a single **Catcher Influence Readiness** audit node. All
  predictive catcher nodes (Catcher State, Battery Interaction, Catcher-Batter
  Archetype Interaction, Pitch Selection/Sequencing, Framing, Blocking,
  Throwing/Running Control, ABS Challenge Decision) remain `NOT_CONFIGURED`.
- **Frontend:** a Catcher Influence Readiness section under Participation & Usage,
  showing honest `NOT_RUN` until real audit evidence exists; never a catcher score
  or ranking.

## 12. Implementation

`server/sports_phase4/catcher_readiness.py` (pure, schema-agnostic algorithms),
`server/sports_phase4/catcher_readiness_run.py` (governed vectorized runner), and
`scripts/run_mlb_catcher_readiness.py` (CLI). Tests:
`tests/sports_phase4_catcher_readiness_test.py` (pure engine) and
`tests/sports_phase4_catcher_readiness_run_test.py` (run pipeline).

### Resolved-schema note (FD1 v5, recorded 2026-08-18 after execution)

`player_game_fielding` (v5) provides `fielding_position` (2 = catcher),
`stat_d_gs` (started), `appearance_sequence`, `stat_d_ifouts` (defensive outs), and
`stat_d_pb/po/a/e/dp` (postgame descriptive). `plate_appearance` provides
`pitching_team_id` (defense = catcher's team), `pitcher_id`, `batter_id`,
`game_date`, `half_play_number`. **There is no governed substitution-event / PA-index
family.** Consequently PA-level catcher assignment is DETERMINISTIC only for
single-catcher team-games; multi-catcher team-games (~12 %) are reported AMBIGUOUS
rather than forward-filled. This is the measured basis for the
`CATCHER_INFLUENCE_PARTIALLY_READY` result and is a data-coverage limitation, not a
lowered threshold.

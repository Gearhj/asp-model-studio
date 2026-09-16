# MLB V18 Play Geometry trace supplement

Status: `V18_PLAY_GEOMETRY_TRACE_SUPPLEMENT_READY_FOR_AISP`

A separately versioned, content-addressed supplement that adds statistically
modelled batted-ball geometry and explicit anonymous runner movements to V18
sequential simulation paths. It is an enrichment and visualisation layer. It
does not alter the accepted V18 forecast, and it is not a replacement for the
V18 plate-appearance outcome model.

Parent bundle: `mlb-v18-whole-game-a6e7e99122f1b60701a4728b`
Parent SHA-256: `a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27`

## 1. Scientific boundary

Two concepts are kept strictly apart.

**V1 — state-consistent geometry supplement (implemented).** The V18 outcome,
outs, base masks and runs are already authoritative. Conditioned on them, this
layer samples a historically fitted geometry and an explicit runner-movement
template that are *compatible* with the play V18 already sampled. It answers
"what plausible geometry and runner movement fit this simulated play?" and never
"what should this play have been?". It makes no causal claim: the sampled
geometry did not produce the outcome, it is drawn to be consistent with it.

**Future — geometry-first challenger (design only, section 8).** A model in
which contact quality generates the outcome rather than the reverse. Not fitted
here.

## 2. Registered data authority

Source: `sports-dataset-1b58d5d1def2c9b7`, family `play_transition`, manifest
`1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`, ACTIVE and
VALID. Seasons 2023-2025, 22 partitions, **570,548 observations**, every
partition checksum-verified before use. Registered
`target_eligibility = ["play_base_out_transition"]` and
`temporal_classification = [RETROSPECTIVE, AVAILABLE_ONLY_AFTER_GAME_FINAL]`, so
it is used only as a chronological Development training target and never as a
pregame feature.

Chronological fold: fit on 2023-2024 (380,609 rows), evaluate on 2025 (189,939
rows). No later evidence reaches a fitted distribution.

### Supported

| Field | Source | Notes |
|---|---|---|
| PA outcome, outs before/after, base mask before/after, runs | `play_transition` | Authoritative state |
| **Explicit runner identifiers on each base, before and after** | `runner_on_{first,second,third}_{before,after}` | Real advancement is *recovered*, not inferred |
| Batted-ball trajectory (ground / line / fly / popup) | Retrosheet `event_text` letter | Recorded |
| Fielding-location zone and depth modifier (S/M/D/XD) | Retrosheet `event_text` location | Recorded |
| Park identity | `park_id` | Retrosheet park id |

### Unsupported — omitted, never invented

`launch_speed`, `launch_angle`, `hc_x`, `hc_y`, `hit_distance_sc` are absent
from every registered MLB authority. Searched: FD1 `play_transition`,
`plate_appearance`, `pitch_sequence`, `player_game_fielding`, `weather`; the
Silver `current_statcast_pa` contract; the Gold sports contracts; and the
inactive `sports-dataset-current-statcast` registration. FD1 `pitch_sequence`
carries `contact_tracking_available` as a **coverage flag only**, with no
measured value. The Gold contract states outright that "Phase 7B1 Silver V1 does
not retain launch_speed, launch_angle, launch_speed_angle, or another governed
barrel indicator".

Consequently `exitVelocityMph`, `launchAngleDegrees`, `sprayAngleDegrees`,
`projectedDistanceFeet` and any measured landing coordinate are emitted as
**null** with a stated reason. What is emitted instead is a zone-derived
direction, depth class and point, labelled
`geometryAuthority = RETROSHEET_LOCATION_ZONE_CENTROID`.

Batter and pitcher handedness are not carried by `play_transition`, so
handedness is not a geometry conditioning level. No external ingestion pipeline
was built.

## 3. Coordinate system — `ASP_NORMALIZED_DIAMOND_V1`

Origin at home plate `(0, 0)`. `y` runs along the home-plate-to-centre-field
axis; `x` is positive toward first base and right field. Units are
dimensionless: `1.0` on the centre-field axis is the nominal centre-field
reference distance. **No value is expressed in feet.** Foul lines at ±45°; fair
territory is `abs(direction) <= 45`. Depth is clipped to `[0.02, 1.35]`. A
non-contact outcome yields null geometry and no ball trace; a contact play with
no recorded location yields a null point and `UNLOCATED_CONTACT`. No CSS colour
or pixel dimension appears in the artifact.

Transformation: trajectory letter to `battedBallType`; location zone to a zone
centroid direction and nominal depth; the depth modifier scales the depth;
`x = depth·sin(direction)`, `y = depth·cos(direction)`.

Ball traces are described as `PROJECTED_VISUAL_TRAJECTORY_FROM_SIMULATED_
GEOMETRY_NOT_A_MEASURED_FLIGHT_PATH`. The single control point is derived
deterministically from the trajectory class and the endpoint; its `lift`
component is a normalized drawing aid with no physical unit.

`startFraction` and `endFraction` on runner movements are presentation
sequencing values in `[0, 1]`. No measured timing authority exists and they must
never be shown as elapsed time.

## 4. Geometry model

A transparent conditional empirical sampler. Trajectory, zone, depth and the
foul flag are drawn as **one joint value**, so a sampled geometry is always a
combination that actually occurred; variables are never sampled independently.

Backoff hierarchy, most specific first, with a 25-observation minimum support:

1. `outcome × park`
2. `outcome`
3. `league_contact_prior` (any contact)

Conditioning on batted-ball type would be circular because the type is part of
the drawn value; handedness is unavailable. Sampling is a deterministic function
of a seed derived from the game, path index and plate-appearance number, so a
replay reproduces every draw exactly.

## 5. Runner-movement model

Historical templates are **recovered**, not guessed: FD1 records the identifier
on each base before and after the play, so the real `(from, to)` assignment is
read directly. Templates are fitted jointly and drawn jointly.

Backoff hierarchy:

1. `outcome × baseState × outs × runs × endState × outsAdded × battedBallType`
2. `outcome × baseState × outs × runs × endState × outsAdded`
3. `outcome × baseState × runs × endState × outsAdded`
4. `baseState × runs × endState × outsAdded`
5. `DETERMINISTIC_LEGAL_BACKOFF`

Every emitted template must satisfy, and is rejected otherwise: no runner
occupies two destinations; no destination base holds two runners; runners never
pass one another; scored runners equal `runsScored`; recorded outs equal
`outsAfter − outsBefore`; and reconstructed occupancy equals `baseMaskAfter`.

The third out is handled exactly as the accepted transition model defines it:
when `outsBefore + outsAdded ≥ 3` the half-inning ends, `baseMaskAfter` is 0 and
surviving runners are **stranded** (`movementReason = STRANDED_INNING_ENDED`),
not retired. Half-inning changes clear the bases. A home-run state clears every
runner.

The deterministic backoff enumerates the entire legal space — at most three
runners plus the batter over five destinations — and takes the
minimum-advancement template, tie-broken stably. It is flagged
`authority = DETERMINISTIC_LEGAL_BACKOFF` wherever used.

Anonymous runner identities are minted when a simulated batter reaches base and
carried forward until the runner advances, scores, is retired or is stranded.
They are deterministic under replay and are **never** presented as real players.

## 6. Fold-local evaluation (fit 2023-2024, evaluate 2025)

**Geometry** — 182,926 evaluated plays:

| Metric | Value |
|---|---|
| Batted-ball-type distribution agreement | 0.9946 |
| Location-zone distribution agreement | 0.9908 |
| Depth-class distribution agreement | 0.9954 |
| Outcome compatibility rate | 0.99952 |
| Fair-territory validity | 1.0000 |
| Missing-geometry rate | 0.0000 |
| Backoff use | 116,295 `outcome_park`, 8,591 `outcome`, 58,040 no-contact, 0 league prior |

No distribution agreement is reported for exit velocity, launch angle, spray
angle or distance, because no such evidence is registered.

**Runner movements** — 175,990 evaluated plays:

| Metric | Fitted sampler | Baseline |
|---|---|---|
| Exact joint template accuracy | **0.99725** | 0.80154 |
| Destination accuracy | 0.99667 | — |
| Illegal-transition rate | 0.0000 | — |
| Runs / outs / ending-state reconciliation | 1.0 by construction | — |

Reconciliation rates are 1.0 by invariant rather than by fit: a template that
violates any conservation rule is rejected before it can be emitted.

The single transparent baseline is the deterministic legal backoff with no
historical fitting. The fitted sampler improves exact joint accuracy from 0.802
to 0.997, so no additional challenger was introduced. No hyperparameter or
algorithm search was run.

Per-outcome exact accuracy: home run 1.000, triple 1.000, walk/HBP 0.99994,
strikeout 0.99984, single 0.99638, double 0.99612, ball-in-play out 0.99604,
other reach 0.97551. Backoff use is highest on other-reach (1.1%) and doubles
(0.30%), and is 0.08% overall.

## 7. Representative paths and V18 invariance

Six predeclared deterministic selectors are implemented: `TYPICAL`, `HOME_WIN`,
`AWAY_WIN`, `HIGH_SCORING` (conditional 90th percentile), `LOW_SCORING`
(conditional 10th percentile) and `EXTRA_INNINGS`.

The accepted bundle persists **one** representative trace, and the accepted
configuration cannot be re-executed here: rebuilding
`V18StateProbabilityProvider` requires the pregame bullpen evidence, which the
bundle does not ship. With one candidate every selector would trivially return
that same path, so the supplement reports `selectionDegenerate = true` and marks
all six selectors **unsatisfied** rather than presenting one trace as six
representatives. The one accepted path is fully enriched and published.

V18 invariance is verified field-by-field across all 74 plate appearances for
every persisted field (`pa`, `inning`, `half`, `battingOrderPosition`,
`pitcherState`, `outcome`, `outsBefore`, `outsAfter`, `baseMaskBefore`,
`baseMaskAfter`, `runsScored`, `homeScoreAfter`, `awayScoreAfter`,
`pitchingChange`): `allInvariantsHeld = true`, zero mismatches. Population
values are copied read-only. No probability, expected run, outcome, transition,
final score, simulation count or seed was modified.

Park conditioning note: the accepted pregame snapshot records a venue *name*
while FD1 keys parks by Retrosheet park id, and no registered crosswalk exists.
Geometry for the prospective game therefore backs off one level to the
outcome-conditional distribution. That backoff is reported per play rather than
resolved by guessing a park.

## 8. Future geometry-first challenger (design only — not fitted)

A later architecture would invert the causal order:

1. a plate-appearance model predicts strikeout, walk, hit-by-pitch or ball in
   play;
2. a contact model generates exit velocity, launch angle and spray angle
   jointly, conditioned on batter, pitcher, handedness matchup and count;
3. park geometry, outfield dimensions, defensive alignment and weather decide
   whether the batted ball becomes an out, an error or a hit, and for how many
   bases;
4. a runner model with runner speed and fielder arm strength determines
   advancement;
5. the resulting state feeds the next plate appearance.

Analytical upside over the outcome-first model: contact-quality distributions
carry information the eight-class outcome discards; batter-pitcher interaction
and handedness enter where they physically act; park and outfield dimensions
become explicit rather than absorbed into a team effect; defence and positioning
become modellable; and expected bases and run value follow from geometry instead
of from a marginal outcome table. The clearest expected gain is in the **tails**
of totals and run differentials, where the outcome-first model's independence
assumptions are weakest.

Evaluation would be chronological and paired against the current V18 model on
the same folds: PA-level multiclass log loss, game-level home-win log loss and
Brier score, total-runs and run-differential distribution calibration, and tail
coverage at the 5th/95th percentiles. It would have to clear the existing
acceptance protocol's operational gates (illegal states, nontermination,
calibration bands) before any comparative claim, and it would require registered
Statcast tracking evidence that does not exist in the current Development
authority — that registration is the prerequisite, not the modelling.

## 9. Governance

Final OOT remains sealed: no Final OOT feature, target or scoring was accessed.
V18 was not recalibrated or refit, the accepted transition model is unchanged,
nothing was promoted or deployed, the AISP repository was not modified, and no
wagering decision exists. The supplement sets `wageringAuthority = false`,
`promotionStatus = NOT_PROMOTED`, `executionAllowedInAISP = false` and
`displayAuthority = RESEARCH_SHADOW_PLAY_GEOMETRY`.

## 10. Limitations

- Exit velocity, launch angle, spray angle in degrees and landing distance in
  feet are not registered and are emitted as null.
- The emitted point is a location-zone centroid, not a measured landing
  coordinate.
- Runner identity is anonymous; a reconstructed movement is a state-consistent
  template, never a named player's real route.
- `startFraction` / `endFraction` are presentation sequencing values, not
  measured timestamps.
- V1 makes no claim that the sampled geometry caused the sampled outcome.
- Only one representative path is available; the other five selectors need a new
  Development-only trace generation, which needs pregame bullpen evidence the
  accepted bundle does not ship.
- Park conditioning is unavailable for the prospective game for want of a
  registered venue-name-to-park-id crosswalk.

# MLB V18 player-prop feasibility audit

**Disposition: `PLAYER_PROP_PROBABILITIES_UNSUPPORTED_BY_EXISTING_IMMUTABLE_POPULATION`.**

The current V18 forecast package cannot honestly answer whether Shohei Ohtani or any other named batter will record a hit. The 5,000-draw population retains paired final scores, innings, total PA counts and one representative event trace. Optional population sidecars retain per-draw outcome counts by team and inning. Neither artifact retains the named batter or pitcher attached to every event in every draw. Many different player allocations produce the same retained team totals, so the missing identity cannot be reconstructed.

V18's live simulation mechanics are closer to supporting these props than the package is. The provider selects one of nine fixed batting-order templates and distinguishes `STARTER` from `TEAM_BULLPEN` at every simulated PA. An unchanged deterministic rerun can therefore collect named-batter hits, total bases and home runs, and named-starting-pitcher strikeouts, without multiplying PA marginals. That is a new producer sidecar and requires an invariance gate; it is not a probability already contained in the immutable forecast.

No probability evaluator was added. Adding one over the present artifacts would turn an unidentified allocation into a number. The included focused tests instead prove the non-identifiability, bind the audited source hashes and keep the capability matrix fail-closed.

## Existing path inventory

| Layer | Retained information | Named-player implication |
|---|---|---|
| PA model | Eight ordered classes: strikeout, walk/HBP/CI, home run, single, double, triple, ball-in-play out, other reach. Batter and pitcher identities select the pregame templates. | Single/double/triple/home-run classes are sufficient for hits and official total bases if the sampled event remains bound to the batter. Strikeout is sufficient for pitcher Ks if the active named pitcher remains bound. |
| Sequential simulator | Batting side, batting-order position, `STARTER` versus `TEAM_BULLPEN`, PA class, base/out transition and final scores. Fixed nine-player batting orders; transparent starter hook; anonymous bullpen mixture. | A collector can map side+slot to the frozen lineup and starter state to the named starter. It cannot identify a reliever. |
| Forecast population | 5,000 paired `awayRuns`/`homeRuns`, innings and PA totals; score PMFs. | Supports game moneyline/spread/total, not player props. |
| Forecast trace | One representative path by default. Events contain slot and coarse pitcher state, not player IDs. | One selected draw is not a probability population. Player IDs could be reattached to that draw only as a diagnostic under the fixed-lineup contract. |
| Population diagnostics | Per-draw team/inning outcome counts, probability sums, starter BF/removal and anonymous-relief BF. | Preserves exposure and event correlation at team level, but not allocation to a named batter. Starter strikeouts are not separately retained. |
| Historical whole-game path | Historical participant oracle replays actual PA membership, substitutions and pitcher changes. Every PA was not persisted. | Not a prospective player-prop forecast and unusable for honest pregame calibration because actual participation reacts to outcomes. |

The representative audited V18 source receipt identifies forecast `mlb-v18-daily-game-2f07648c51e830736d65ff37`, 5,000 draws and population SHA-256 `a302b39e17922a208ac90b14310d82fefa60451734704a45e26d4f34f7282faa`. This audit used its retained source-validation metadata and implementation contracts. It did not open outcomes, Final OOT or sealed evidence.

## Why marginal multiplication is invalid

The count of a batter's PAs depends on batting slot, inning termination, team scoring, walk-offs and extra innings. The PA probabilities also change with inning, outs, base state, score differential and starter removal. Multiplying initial or average PA marginals assumes an exposure count and dependence structure that V18 did not assert. It would also sever the player event from the same draw's game state. The only defensible route is to count the named player's sampled events inside each original correlated draw.

## Prop dispositions

| Prop | Current immutable package | Simulator mechanics | Smallest honest change |
|---|---|---|---|
| Batter 1+ hit | Unsupported | Mechanically derivable in an exact replay: count single+double+triple+home run for the named lineup slot in each draw. | Passive named-player per-draw counter, exact replay invariance, conditional participation disclosure. |
| Batter total bases | Unsupported | Mechanically derivable: single + 2×double + 3×triple + 4×home run from the same named path. | Same counter; retain integer total-base count per draw. |
| Batter home run | Unsupported | Mechanically derivable: count `HOME_RUN` for the named lineup slot. | Same counter. |
| Starting-pitcher strikeouts | Unsupported | Mechanically derivable for the named starter while `pitcherState=STARTER`; hook and exposure correlation are retained. | Retain starter strikeout count per draw and bind the named starter. Validate the duration limitation. |
| Reliever strikeouts | Unsupported | Anonymous bullpen mixture has no active reliever identity. | A separately governed availability/selection/usage model; a counter alone is insufficient. |

“Mechanically derivable” is not a model-quality claim. The existing fixed lineup has no bench, pinch-hitter, defensive-substitution or injury process. The starter hook is a transparent policy, and bullpen probabilities are an anonymous team mixture. The player-prop population would be conditional on the frozen participants and mechanics.

## Lineups, changes and game status

The current publisher requires a nine-player ordered lineup, exact MLB identities, announced starters and pre-cutoff evidence. Its current-state path additionally requires `lineupAuthority.status=CONFIRMED`. It rejects a capture at or after first pitch and accepts only scheduled/pregame statuses. A changed lineup cannot reuse a prior participant binding merely because its numeric features match.

After simulation begins, the order remains fixed. V18 has no scratch, pinch-hit, substitution or player-availability distribution. A late scratch therefore requires a new eligible forecast revision or a fail-closed disposition. Postponed/cancelled games are ineligible because their status is outside the accepted pregame set; any settlement void belongs to the quote and house rules, not to the existing model.

## Evidence and model limitations

- The five V18 chronological PA folds and OOF predictions support eight-class PA discrimination/calibration analysis at the PA grain. They do not establish per-game player count calibration because they do not provide prospective joint PA exposure and participation paths.
- Existing population diagnostics are simulated-path diagnostics. Their probability sums condition on simulated exposures; they are not frozen predictions for the actual PAs.
- Historical participant oracle replays use actual participants and substitutions and cannot be relabeled pregame evidence.
- Training/feature chronology limitations remain attached to the V18 historical evidence.
- The permanent whole-game quarantine remains in force. No Final OOT payload, reduced or otherwise, was read in this audit.

## Required next producer increment

Add a passive collector to the existing 5,000-draw run. For each event, map batting side and order slot to the exact frozen canonical player; map `STARTER` to the exact opposing starting pitcher; and retain per-draw integer arrays for batter PA, hits, singles, doubles, triples, home runs, total bases and starter strikeouts. The collector must not draw randomness, change provider calls, alter draw order or affect stopping. It must reconcile every player count to team class counts and reproduce the original score arrays, trace and forecast summaries exactly.

Publish nothing until a separate research sidecar is identity-bound to the exact forecast/package/population/model, source cutoff, confirmed lineup revision, starters, seed and draw count. An unconditional market assessment additionally needs either a supported void/participation model or an explicit final eligibility check that makes the result conditional on the player starting under compatible house rules.

The chronological calibration study should then use governed Development and Validation games only, reconstruct pregame participants from timestamped evidence, generate fold-correct player paths, and score observed games as the independent units. See `CALIBRATION_AND_LEAKAGE_PLAN.md`.

## Activity accounting

- Authenticated provider calls: **0**
- Provider response bytes: **0**
- Provider credits/cost: **0 / $0**
- AISP writes, exchange writes, forecasts, model runs/fits, scheduler changes, decisions, positions and promotions: **0**
- Outcome payloads, sealed evidence and protected Final OOT rows opened: **0**

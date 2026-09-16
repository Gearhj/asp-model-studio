# MLB V18 player-prop research sidecar

## Disposition

`IMPLEMENTED_RESEARCH_ONLY_NOT_CALIBRATED_NOT_PUBLISHED`

The smallest honest producer increment is a passive observer on the existing V18 event stream. It retains named-batter PA, 1B, 2B, 3B, HR, H and TB counts for every draw, plus BF and strikeouts for each frozen named starter only while the simulator reports `pitcherState=STARTER`. The simulator's `TEAM_BULLPEN` remains anonymous.

The implementation does not alter the V18 probability provider, starter hook, transition model, seeds, RNG calls, draw order, scoring, termination, forecast object, current publisher or exchange. It adds no model and grants no consumer authority.

## Governed replay

The unsealed MIA-at-AZ forecast used for verification is:

- Game: `5dc9aa85-3f85-4a91-874a-a3194d9179c8`, MLBAM `825030`
- Forecast: `mlb-v18-daily-game-2f07648c51e830736d65ff37`
- Immutable forecast object: `2f07648c51e830736d65ff37689c563bb2195ec767090d14ecc8e905968cbdac`
- Draws/seed: 5,000 / `20260907`
- Original paired-score population: `a302b39e17922a208ac90b14310d82fefa60451734704a45e26d4f34f7282faa`
- Earliest authenticated publication: `2026-09-16T00:58:42.501188+00:00`; logical receipt `4c5bd1c3d3068e05eef03a1854e9aa0ab5f1e77c779f98850efd7473f8623038`; physical receipt SHA-256 `7a8671f98f24b15405a0ae932adc469fc35a0fd04176cff88719f0e5f2cb8067`
- PA model: `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`
- Transition model: `0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253`
- Confirmed lineup observations: away `18c12518-016e-4ae4-bd2b-70bc3737b741`; home `4e95cda7-12aa-46d7-9204-049838d73da8`

The replay authenticates every original package member before loading inputs. Because the live prospective guard correctly rejects post-start execution, the runner reconstructs the forecast's recorded authorization instant only while building the frozen preprocessing cache. It does not change any feature value. Exact equality to the saved 5,000-draw population and the counters-disabled run is mandatory.

## Results

The retained replay receipt records exact equality for all 5,000 away scores, all 5,000 home scores, innings, PA counts, representative trace and every stored summary/rate. The paired-score population remains `a302b39e17922a208ac90b14310d82fefa60451734704a45e26d4f34f7282faa`. Existing forecast member bytes were read and rehashed only; none were written.

The final local sidecar is 267,423 bytes with SHA-256 `3259706deca700ac6d0ea1b8779eaae9fdbcc359612b69ad3168dd920924d3d4`. Its manifest SHA-256 is `57486ab76bf02c9b9f50a06c1b0c70c90e5bf28c35d1a3849fcc01619afcd7a0`, and its replay-receipt SHA-256 is `eb4badc5856fffcce0a85855e42317f71c9ca16fe4c183b3643a42776da46f31`. Every per-draw identity and arithmetic reconciliation passed. The simulator does not expose RNG terminal state through the observer contract, so it was not captured; exact output equality and the observer's zero-random-call design are the available invariance proof.

## What the sidecar means

The population is conditional on the fixed confirmed starting lineups, named starters and unchanged V18 mechanics. The simulator has no bench, pinch-hitter, defensive substitution, in-game injury, late-scratch, cancellation, postponement or sportsbook void model. It cannot support named reliever props. Starting-pitcher strikeouts end when the existing hook switches that pitching team to the anonymous bullpen state.

The pure evaluator reports empirical win/loss/push mass and binomial Monte Carlo standard error. `pVoid` is `null`. It emits no price, fair value, edge, expected return, decision or stake.

## Operations accounting

- Predictive fits: 0
- Provider calls/bytes/credits/cost: 0 / 0 / 0 / $0
- Outcome and sealed reads: 0 / 0
- AISP writes: 0
- Exchange writes and forecast publications: 0
- Publisher, scheduler, owner and discovery changes: 0

## Next dependency

The exact next dependency is a separately registered chronological player-prop calibration study using governed Development/Validation evidence and point-in-time player participation. This sidecar is infrastructure for that study, not evidence that any prop probability is calibrated or useful.

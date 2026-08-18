# MLB_GAME_REPLAY_ENGINE_V1

Governed **engineering/research** contract for the Phase 5 deterministic historical
MLB game-replay engine. Mechanical, not predictive. It samples no outcomes, uses no model
probabilities, and computes nothing about betting.

## Principle

Before predicting a baseball game, prove the kernel can replay a real one — event by event
and state by state. This contract defines a deterministic **replay validator**, not a
probabilistic simulator.

## Source authority

Only the governed FD1 `play_transition` family (dataset manifest `1b58d5d1…`), which is a
complete per-play ledger with authoritative before/after state. Verified properties:
`play_number` is contiguous 1..N per game; within a half-inning each play's `*_before`
equals the previous play's `*_after`; `base_mask` bits are first=1, second=2, third=4 and
match `runner_on_{first,second,third}` (empty encoded as the string `None`); `runs_scored`
reconciles the score deltas; extra-innings place an automatic runner on second
(`automatic_runner_placement_before`, `automatic_runner_base=2`); regulation innings are 9
(or 7 for the 2021–2022 doubleheader rule). Runner destinations are taken from the source
after-state (**actual advancement**), never from crude one-base-per-single rules.

## Input

Ordered play sequence per game: game identity, `play_number`, `plate_appearance_id`,
inning, half (`top_bottom`: 1=top/0=bottom), `outs_before/after`, `base_mask_before/after`,
`visiting_score_before/after`, `home_score_before/after`, `runs_scored`, batter/pitcher
identity, `pa_outcome`, `event_text`, `regulation_innings`, `pbp_quality`, automatic-runner
fields.

## State

`inning`, `top`, `outs`, `base_mask` (0..7), `away_score`, `home_score`, `terminal`. Base
occupancy and runner identities are carried from the source.

## Mechanics

The engine tracks state independently from a fresh start (inning 1, top, 0 outs, empty
bases, 0–0) and, at every play: validates its tracked before-state against the source
(inning/half/outs/bases/score continuity), validates the play mechanically (outs stay in
`[0,3]` and never decrease; `runs_scored` equals the score deltas; runs are attributed only
to the batting team), adopts the authoritative after-state, and on the third out performs a
deterministic half-inning transition (top→bottom same inning; bottom→top increments inning;
outs reset; bases clear — the extra-innings ghost runner on second is honored at a half
start). Game-end is validated: a completed game is not tied and reaches at least regulation,
with a home walk-off / lead ending it and a tie continuing to extra innings.

## Output & reconciliation

Per game: reconstructed state after each event, scoring events, inning transitions, final
score/inning, terminal state, and a reconciliation result — `finalScoreExact`,
`terminalInningExact`, `runsReconcile`, `gameEndValid`, `zeroContinuityMismatch`.
Classification: `EXACT_REPLAY`, `PARTIAL_REPLAY`, `REPLAY_MISMATCH`, or `SOURCE_INSUFFICIENT`
(non-FULL pbp or a non-contiguous ledger). Mismatches are never hidden and are ranked by
category, inning, and outcome for forensics.

## Readiness

`GAME_REPLAY_ENGINE_READY` / `GAME_REPLAY_ENGINE_PARTIALLY_READY` / `GAME_REPLAY_ENGINE_BLOCKED`.
READY means the deterministic mechanics are trustworthy enough to begin probabilistic
simulation — it does **not** mean a forecasting simulator exists.

## Exclusions

No Monte Carlo, no PA-outcome sampling, no D3-probability-driven outcomes, no win / run-line
/ total probabilities, no betting edge, no residual layer, no live updates, no ASP export,
no prospective feeds, no premium data, no new PA experiments, no algorithm tournament, no
E6, no provider/network calls, no new data acquisition. The provider Protocols
(`PAOutcomeProvider`, `RunnerAdvanceProvider`, `HistoricalReplayProvider`, …) are design
seams only; the future probabilistic simulator swaps `HistoricalReplayProvider` for a
sampling provider.

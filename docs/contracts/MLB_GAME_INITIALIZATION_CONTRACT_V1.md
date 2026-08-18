# MLB_GAME_INITIALIZATION_CONTRACT_V1

**Status:** engineering interface contract (Phase 5C, Monte-Carlo entry gate 7).
Historical replay initialization only. **Not** a forecast or a betting artifact.

## Purpose

Define and validate the initial state of a historical game simulation, pin the authorities a
run binds to, and declare a single controlled RNG lineage, so a future whole-game Monte Carlo
starts every game from a legal, authority-pinned, reproducible opener.

## Initialization fields

- game id, game date, season, away team, home team, regulation innings
- starting inning = **1**, top half, outs = **0**, bases empty (`base_mask = 0`)
- away score = 0, home score = 0
- away batting order (nine resolved players), home batting order (nine resolved players)
- away starting pitcher, home starting pitcher
- active lineup identities
- transition-model authority, PA-model authority, participant-provider authority
- RNG seed lineage, simulation id / replay mode

## Initial-state validation

Before simulation the initial state must be exactly inning 1, top half, no outs, bases empty,
scoreless; both team identities present and distinct; both batting orders exactly nine distinct
resolved players; both starting pitchers present; replay mode = `HISTORICAL_REPLAY`. Any
violation fails closed.

## Era / special-rule initialization

Normal games initialize bases-empty at inning 1. Era and special-case mechanics are handled
source-realistically by the already-proven kernel and transition model, not reinvented here:

- **Extra-inning automatic runner** — the Phase 5A kernel recognizes the governed
  `automatic_runner_placement_before` / `automatic_runner_base` at a half-inning start; the
  Phase 5B transition model fits from source-realistic base-out mechanics. Extra-inning
  initialization is a mid-game half-inning opener, not a game opener.
- **Shortened / weather-called games** — the source is authoritative on when a game ended; the
  kernel reconciles the exact final score and inning and does not treat a short game as an
  anomaly.
- **Doubleheaders / suspended-resumed games** — carried by the governed `doubleheader_id`,
  `game_suspended`, and `final_available_date` fields; the initializer binds the game identity
  and defers mechanics to the proven kernel.

## RNG lineage

One controlled lineage: a **master seed** derives a per-game seed from the master plus a
stable game key (`SHA-256(game_key)` folded into a NumPy `SeedSequence`), which then spawns
independent **PA-sample** and **transition** child generators. Identical initialization +
authorities + master seed reproduce an identical sampled sequence; a different seed diverges.

## Simulation event record

A lightweight per-PA event record is defined for future Monte Carlo (used only in tests / small
validation here): simulation id, game id, PA index, inning, half, outs before, base state
before, batter, pitcher, PA-probability authority, sampled PA class, transition-model
authority, sampled transition, runs scored, outs after, base state after, and RNG lineage.
Millions of events are **not** persisted.

## Prohibitions

No whole-game Monte Carlo, no win/run-line/total probabilities, no betting logic, no
prospective feeds, no model changes.

# MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1

**Status:** engineering interface contract (Phase 5C, Monte-Carlo entry gate 6).
Outputs are labeled **`HISTORICAL_REPLAY_ONLY`**.

## Purpose

Provide the **actual historical participants** of a game so a retrospective simulator backtest
can hold participant identity fixed. Holding actual participants fixed keeps participant
uncertainty from contaminating PA/simulator validation; the first Monte-Carlo validation runs
against real historical participants, not projected ones.

This is **not** the future prospective participation provider and **not** the Milestone B
lineup / starter-duration / bullpen-usage forecasts. Those research models are used later in a
separate simulator ablation. Because this provider's only role is historical backtesting, it
may use retrospective source evidence.

## Source authority

FD1 `play_transition` ledger (dataset `sports-dataset-1b58d5d1def2c9b7`, manifest `1b58d5d1…`)
— the same governed authority Phase 5A replay and Phase 5B transitions consume. No new data.

## Provided per game

- Starting lineup per team (nine slots, batting-order order).
- Batting order.
- Starting catcher (retrosheet fielding role code `2`), when available.
- Starting pitcher per team.
- Pitcher-change sequence (ordered distinct pitchers) per team.
- Batter substitutions (per-slot occupant changes across the game).
- Active batter and batting-order slot for each plate appearance.
- Active pitcher for each plate appearance.

## Reconstruction rules

Rows are the governed `play_transition` rows for one game, in `play_number` order. Halves:
`top_bottom == 0` is the top half (away bats / home pitches). A team's starting lineup is the
`lineup_player_ids` snapshot at its first batting play, in slot order; the starting catcher is
the slot whose `retrosheet_lineup_role_codes` entry is `2`. A team's pitcher sequence is the
ordered distinct `pitcher_id` values across the plays it pitches; the first is the starting
pitcher. Batter substitutions are per-slot occupant changes across successive lineup snapshots.
Plate appearances are the terminal rows (`pa_outcome` present); the active batter/pitcher are
that row's `batter_id`/`pitcher_id`, and the slot is the batter's index in the current lineup
snapshot.

## Identity binding

Identity is bound exactly from the ledger's terminal PA rows (retrosheet player ids). The
retrosheet↔canonical mapping used to bind participants to the D3 provider's player state is
1:1 (verified: 0 violations across 365,375 governed 2024-2025 PAs). No fuzzy name matching; no
unresolved id is silently accepted.

## Completeness

A game whose participants reconstruct exactly is `PARTICIPANT_REPLAY_COMPLETE`. Any game that
cannot be exactly reconstructed (non-`FULL` play-by-play, a lineup that is not nine, an
unresolved batter/pitcher, a batter absent from the lineup snapshot) is marked
`PARTICIPANT_REPLAY_INCOMPLETE` — never guessed.

## Shared interface

`HistoricalParticipantReplayProvider` implements a simulation-facing contract that a future
`FutureProjectedParticipationProvider` (lineup projection + starter + bullpen +
confirmed/prospective feed) will share where practical. The future projected provider is **not**
implemented here.

## Prohibitions

No forecasts, no projected participation, no bullpen/lineup/starter prediction, no betting
metrics, no whole-game Monte Carlo, no external feeds.

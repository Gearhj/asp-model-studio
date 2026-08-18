"""Game initialization contract + RNG lineage (MLB_GAME_INITIALIZATION_CONTRACT_V1).

Phase 5C simulation-input component. Defines and validates the initial state of a historical
game simulation, pins the model/transition/participant authorities a run binds to, and
declares a single controlled RNG lineage (master -> game -> PA-sample / transition) with
deterministic child-seed derivation so that identical initialization + authorities + master
seed reproduce an identical sampled sequence. Also defines a lightweight simulation event
record for future Monte Carlo (used only in tests / small validation here).

No whole-game Monte Carlo, win/run-line/total probabilities, or betting logic. Normal games
initialize bases-empty at inning 1; era/special-rule mechanics (extra-inning automatic
runner, shortened/suspended games) are already handled source-realistically by the proven
Phase 5A kernel and Phase 5B transition model and are documented, not reinvented here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_phase5.game_replay import GameState

GAME_INIT_CONTRACT_NAME = "MLB_GAME_INITIALIZATION_CONTRACT_V1"
GAME_INIT_SCHEMA_VERSION = "MLB_GAME_INITIALIZATION_CONTRACT_V1"

REPLAY_MODE_HISTORICAL = "HISTORICAL_REPLAY"


class GameInitializationError(RuntimeError):
    """Fail-closed error for an invalid or under-specified game initialization."""


@dataclass(frozen=True)
class SimulationAuthorities:
    """The pinned authorities a simulation binds to (no forecasts, no betting)."""

    dataset_registration_id: str
    dataset_manifest_sha: str
    replay_contract: str
    transition_contract: str
    transition_model_sha: str
    pa_provider_contract: str
    pa_model_authority: str
    participant_provider_contract: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "datasetRegistrationId": self.dataset_registration_id,
            "datasetManifestSha": self.dataset_manifest_sha,
            "replayContract": self.replay_contract,
            "transitionContract": self.transition_contract,
            "transitionModelSha": self.transition_model_sha,
            "paProviderContract": self.pa_provider_contract,
            "paModelAuthority": self.pa_model_authority,
            "participantProviderContract": self.participant_provider_contract,
        }


@dataclass(frozen=True)
class RngLineage:
    """One controlled simulation RNG lineage with deterministic child-seed derivation.

    ``master_seed`` -> per-game seed (derived from master + a stable game key) -> independent
    PA-sample and transition child generators. Same master + game key reproduces the same
    generators; different seeds diverge.
    """

    master_seed: int
    game_key: str

    def _game_seed_sequence(self) -> np.random.SeedSequence:
        digest = hashlib.sha256(self.game_key.encode("utf-8")).digest()
        game_entropy = int.from_bytes(digest[:8], "big")
        return np.random.SeedSequence([int(self.master_seed), game_entropy])

    def game_seed(self) -> int:
        return int(self._game_seed_sequence().generate_state(1, dtype=np.uint64)[0])

    def pa_rng(self) -> np.random.Generator:
        child = self._game_seed_sequence().spawn(2)[0]
        return np.random.default_rng(child)

    def transition_rng(self) -> np.random.Generator:
        child = self._game_seed_sequence().spawn(2)[1]
        return np.random.default_rng(child)

    def as_dict(self) -> dict[str, Any]:
        return {
            "masterSeed": self.master_seed,
            "gameKey": self.game_key,
            "gameSeed": self.game_seed(),
            "childDerivation": "SHA256_GAME_KEY_THEN_NUMPY_SEEDSEQUENCE_SPAWN",
        }


@dataclass(frozen=True)
class GameInitialization:
    game_id: str
    game_date: str
    season: int
    away_team_id: str
    home_team_id: str
    regulation_innings: int
    away_batting_order: tuple[str, ...]
    home_batting_order: tuple[str, ...]
    away_starting_pitcher: str
    home_starting_pitcher: str
    authorities: SimulationAuthorities
    rng: RngLineage
    replay_mode: str = REPLAY_MODE_HISTORICAL
    simulation_id: str | None = None

    def initial_state(self) -> GameState:
        """Inning 1, top half, no outs, bases empty, scoreless."""

        return GameState(inning=1, top=True, outs=0, base_mask=0, away_score=0, home_score=0)

    def validate(self) -> None:
        if not self.game_id:
            raise GameInitializationError("game_id required")
        if not self.game_date:
            raise GameInitializationError("game_date required")
        if self.season not in (2024, 2025):
            raise GameInitializationError("season must be a supported historical season")
        if not self.away_team_id or not self.home_team_id:
            raise GameInitializationError("both team identities required")
        if self.away_team_id == self.home_team_id:
            raise GameInitializationError("away and home teams must differ")
        if self.regulation_innings < 1:
            raise GameInitializationError("regulation innings must be positive")
        for label, order in (
            ("away", self.away_batting_order),
            ("home", self.home_batting_order),
        ):
            if len(order) != 9 or any(not p for p in order):
                raise GameInitializationError(f"{label} batting order must be nine resolved players")
            if len(set(order)) != 9:
                raise GameInitializationError(f"{label} batting order has duplicate players")
        if not self.away_starting_pitcher or not self.home_starting_pitcher:
            raise GameInitializationError("both starting pitchers required")
        if self.replay_mode != REPLAY_MODE_HISTORICAL:
            raise GameInitializationError("Phase 5C supports historical replay mode only")
        state = self.initial_state()
        if (state.inning, state.top, state.outs, state.base_mask, state.away_score, state.home_score) != (
            1,
            True,
            0,
            0,
            0,
            0,
        ):
            raise GameInitializationError("initial state is not the canonical inning-1 opener")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": GAME_INIT_SCHEMA_VERSION,
            "contractName": GAME_INIT_CONTRACT_NAME,
            "gameId": self.game_id,
            "gameDate": self.game_date,
            "season": self.season,
            "awayTeamId": self.away_team_id,
            "homeTeamId": self.home_team_id,
            "regulationInnings": self.regulation_innings,
            "startingInning": 1,
            "startingHalf": "top",
            "startingOuts": 0,
            "startingBaseMask": 0,
            "awayScore": 0,
            "homeScore": 0,
            "awayBattingOrder": list(self.away_batting_order),
            "homeBattingOrder": list(self.home_batting_order),
            "awayStartingPitcher": self.away_starting_pitcher,
            "homeStartingPitcher": self.home_starting_pitcher,
            "authorities": self.authorities.as_dict(),
            "rng": self.rng.as_dict(),
            "replayMode": self.replay_mode,
            "simulationId": self.simulation_id,
        }


@dataclass(frozen=True)
class SimulationEventRecord:
    """Lightweight per-PA sampled event record (future Monte Carlo; small validation only)."""

    simulation_id: str
    game_id: str
    pa_index: int
    inning: int
    top: bool
    outs_before: int
    base_mask_before: int
    batter_id: str
    pitcher_id: str
    pa_probability_authority: str
    sampled_pa_class: str
    transition_model_authority: str
    sampled_transition: tuple[int, int, int]  # (outs_added, base_mask_after, runs)
    runs_scored: int
    outs_after: int
    base_mask_after: int
    rng_master_seed: int
    rng_game_key: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "simulationId": self.simulation_id,
            "gameId": self.game_id,
            "paIndex": self.pa_index,
            "inning": self.inning,
            "half": "top" if self.top else "bottom",
            "outsBefore": self.outs_before,
            "baseMaskBefore": self.base_mask_before,
            "batterId": self.batter_id,
            "pitcherId": self.pitcher_id,
            "paProbabilityAuthority": self.pa_probability_authority,
            "sampledPaClass": self.sampled_pa_class,
            "transitionModelAuthority": self.transition_model_authority,
            "sampledTransition": {
                "outsAdded": self.sampled_transition[0],
                "baseMaskAfter": self.sampled_transition[1],
                "runs": self.sampled_transition[2],
            },
            "runsScored": self.runs_scored,
            "outsAfter": self.outs_after,
            "baseMaskAfter": self.base_mask_after,
            "rng": {"masterSeed": self.rng_master_seed, "gameKey": self.rng_game_key},
        }


__all__ = [
    "GAME_INIT_CONTRACT_NAME",
    "GAME_INIT_SCHEMA_VERSION",
    "REPLAY_MODE_HISTORICAL",
    "GameInitializationError",
    "SimulationAuthorities",
    "RngLineage",
    "GameInitialization",
    "SimulationEventRecord",
]

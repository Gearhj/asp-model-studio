"""Historical participant replay provider (MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1).

Phase 5C simulation-input component. Supplies the ACTUAL historical participants for a game
so a retrospective simulator backtest can hold participant identity fixed (participant
uncertainty must not contaminate PA/simulator validation). Every output is labeled
``HISTORICAL_REPLAY_ONLY`` — it is NOT the future prospective participation provider and NOT
the Milestone B lineup/starter/bullpen forecasts.

It uses only the governed FD1 ``play_transition`` ledger (the same authority Phase 5A/5B
consume), reconstructing per game: starting lineup and batting order per team, starting
catcher, starting pitcher, pitcher-change sequence, batter substitutions, and the active
batter/pitcher for each plate appearance. Identity is bound exactly (retrosheet ids from the
ledger's terminal PA rows); no fuzzy name matching, no invented participants. Games whose
participants cannot be exactly reconstructed are marked ``PARTICIPANT_REPLAY_INCOMPLETE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

PARTICIPANT_CONTRACT_NAME = "MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1"
PARTICIPANT_SCHEMA_VERSION = "MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1"
PROVENANCE_LABEL = "HISTORICAL_REPLAY_ONLY"

# Retrosheet fielding position code for the catcher.
CATCHER_ROLE_CODE = 2
LINEUP_SIZE = 9

COMPLETE = "PARTICIPANT_REPLAY_COMPLETE"
INCOMPLETE = "PARTICIPANT_REPLAY_INCOMPLETE"


class ParticipantReplayError(RuntimeError):
    """Structurally impossible participant input (never used to hide an incompleteness)."""


def _empty(value: Any) -> str | None:
    text = "" if value is None else str(value)
    return None if text in ("", "None", "nan") else text


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    try:  # numpy array
        return [str(v) for v in value.tolist()]
    except AttributeError:
        return [str(value)]


def _as_int_list(value: Any) -> list[int]:
    out: list[int] = []
    if value is None:
        return out
    seq = value.tolist() if hasattr(value, "tolist") else value
    for v in seq:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            out.append(-1)
    return out


@dataclass(frozen=True)
class PlateAppearanceParticipant:
    play_number: int
    plate_appearance_id: str | None
    inning: int
    top: bool
    batting_team_id: str
    pitching_team_id: str
    batter_id: str
    pitcher_id: str
    batting_order_slot: int  # 1..9, the batter's lineup slot; 0 if unresolved
    pa_outcome: str | None


@dataclass(frozen=True)
class TeamParticipants:
    team_id: str
    starting_lineup: tuple[str, ...]       # slot order, length 9
    batting_order: tuple[int, ...]         # 1..9 aligned to starting_lineup
    starting_catcher: str | None
    starting_pitcher: str | None
    pitcher_sequence: tuple[str, ...]      # ordered distinct pitchers used
    batter_substitutions: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class GameParticipants:
    game_id: str
    game_date: str
    season: int
    away_team_id: str
    home_team_id: str
    provenance: str
    status: str
    away: TeamParticipants | None
    home: TeamParticipants | None
    plate_appearances: tuple[PlateAppearanceParticipant, ...]
    incompleteness_reasons: tuple[str, ...] = ()

    def active_pitcher_at(self, play_number: int) -> str | None:
        for pa in self.plate_appearances:
            if pa.play_number == play_number:
                return pa.pitcher_id
        return None

    def public(self) -> dict[str, Any]:
        def _team(t: TeamParticipants | None) -> dict[str, Any] | None:
            if t is None:
                return None
            return {
                "teamId": t.team_id,
                "startingLineup": list(t.starting_lineup),
                "battingOrder": list(t.batting_order),
                "startingCatcher": t.starting_catcher,
                "startingPitcher": t.starting_pitcher,
                "pitcherSequence": list(t.pitcher_sequence),
                "batterSubstitutionCount": len(t.batter_substitutions),
            }

        return {
            "gameId": self.game_id,
            "gameDate": self.game_date,
            "season": self.season,
            "awayTeamId": self.away_team_id,
            "homeTeamId": self.home_team_id,
            "provenance": self.provenance,
            "status": self.status,
            "away": _team(self.away),
            "home": _team(self.home),
            "plateAppearanceCount": len(self.plate_appearances),
            "incompletenessReasons": list(self.incompleteness_reasons),
        }


def _reconstruct_team(
    team_id: str,
    batting_rows: Sequence[Mapping[str, Any]],
    pitching_rows: Sequence[Mapping[str, Any]],
    reasons: list[str],
    side: str,
) -> TeamParticipants | None:
    if not batting_rows:
        reasons.append(f"{side}_NO_BATTING_ROWS")
        return None
    first = batting_rows[0]
    lineup = _as_list(first.get("lineup_player_ids"))
    roles = _as_int_list(first.get("retrosheet_lineup_role_codes"))
    if len(lineup) != LINEUP_SIZE:
        reasons.append(f"{side}_LINEUP_NOT_NINE")
        starting_lineup: tuple[str, ...] = tuple(lineup)
        batting_order: tuple[int, ...] = tuple(range(1, len(lineup) + 1))
        catcher = None
    else:
        starting_lineup = tuple(lineup)
        batting_order = tuple(range(1, LINEUP_SIZE + 1))
        catcher = None
        if len(roles) == LINEUP_SIZE:
            for player, code in zip(lineup, roles):
                if code == CATCHER_ROLE_CODE:
                    catcher = player
                    break
        if catcher is None:
            reasons.append(f"{side}_NO_STARTING_CATCHER")

    # Pitcher sequence: ordered distinct pitchers the OPPONENT faced while this team batted
    # are the opponent's; this team's pitchers appear on its pitching rows.
    pitcher_sequence: list[str] = []
    for row in pitching_rows:
        pid = _empty(row.get("pitcher_id"))
        if pid and (not pitcher_sequence or pitcher_sequence[-1] != pid):
            if pid not in pitcher_sequence:
                pitcher_sequence.append(pid)
    starting_pitcher = pitcher_sequence[0] if pitcher_sequence else None
    if starting_pitcher is None:
        reasons.append(f"{side}_NO_STARTING_PITCHER")

    # Batter substitutions: a slot's occupant changing across the batting-order snapshots.
    substitutions: list[dict[str, Any]] = []
    previous = list(starting_lineup)
    for row in batting_rows:
        snapshot = _as_list(row.get("lineup_player_ids"))
        if len(snapshot) != len(previous):
            continue
        for slot, (old, new) in enumerate(zip(previous, snapshot), start=1):
            if old != new:
                substitutions.append(
                    {
                        "slot": slot,
                        "playNumber": int(row.get("play_number", 0) or 0),
                        "outgoing": old,
                        "incoming": new,
                    }
                )
        previous = snapshot

    return TeamParticipants(
        team_id=team_id,
        starting_lineup=starting_lineup,
        batting_order=batting_order,
        starting_catcher=catcher,
        starting_pitcher=starting_pitcher,
        pitcher_sequence=tuple(pitcher_sequence),
        batter_substitutions=tuple(substitutions),
    )


def reconstruct_game_participants(rows: Sequence[Mapping[str, Any]]) -> GameParticipants:
    """Reconstruct actual historical participants for one game from its play_transition rows."""

    if not rows:
        raise ParticipantReplayError("participant replay requires at least one row")
    ordered = sorted(rows, key=lambda r: int(r.get("play_number", 0) or 0))
    first = ordered[0]
    game_id = str(first["game_id"])
    away_team = str(first["visiting_team_id"])
    home_team = str(first["home_team_id"])
    game_date = str(first.get("game_date"))
    season = int(first.get("season"))
    reasons: list[str] = []

    if any(str(r.get("pbp_quality") or "UNKNOWN") != "FULL" for r in ordered):
        reasons.append("PBP_NOT_FULL")

    # Rows by half: top (top_bottom==0) => away bats / home pitches.
    away_batting = [r for r in ordered if int(r.get("top_bottom", 0) or 0) == 0]
    home_batting = [r for r in ordered if int(r.get("top_bottom", 0) or 0) == 1]

    away = _reconstruct_team(away_team, away_batting, home_batting, reasons, "AWAY")
    home = _reconstruct_team(home_team, home_batting, away_batting, reasons, "HOME")

    # Plate appearances: the terminal rows (pa_outcome present) in play order.
    pas: list[PlateAppearanceParticipant] = []
    for row in ordered:
        outcome = _empty(row.get("pa_outcome"))
        if outcome is None:
            continue
        top = int(row.get("top_bottom", 0) or 0) == 0
        batter = _empty(row.get("batter_id"))
        pitcher = _empty(row.get("pitcher_id"))
        lineup = _as_list(row.get("lineup_player_ids"))
        slot = lineup.index(batter) + 1 if batter in lineup else 0
        if batter is None:
            reasons.append("PA_UNRESOLVED_BATTER")
        if pitcher is None:
            reasons.append("PA_UNRESOLVED_PITCHER")
        pas.append(
            PlateAppearanceParticipant(
                play_number=int(row.get("play_number", 0) or 0),
                plate_appearance_id=_empty(row.get("plate_appearance_id")),
                inning=int(row.get("inning", 0) or 0),
                top=top,
                batting_team_id=str(row.get("batting_team_id")),
                pitching_team_id=str(row.get("pitching_team_id")),
                batter_id=batter or "",
                pitcher_id=pitcher or "",
                batting_order_slot=slot,
                pa_outcome=outcome,
            )
        )

    unresolved_slot = sum(1 for p in pas if p.batting_order_slot == 0)
    if unresolved_slot:
        reasons.append("PA_BATTER_NOT_IN_LINEUP")

    status = COMPLETE if not reasons else INCOMPLETE
    return GameParticipants(
        game_id=game_id,
        game_date=game_date,
        season=season,
        away_team_id=away_team,
        home_team_id=home_team,
        provenance=PROVENANCE_LABEL,
        status=status,
        away=away,
        home=home,
        plate_appearances=tuple(pas),
        incompleteness_reasons=tuple(sorted(set(reasons))),
    )


class HistoricalParticipantReplayProvider:
    """Provides actual historical participants for retrospective backtesting only."""

    def __init__(self, games: Mapping[str, GameParticipants]) -> None:
        self._games = dict(games)

    @classmethod
    def from_rows_by_game(
        cls, rows_by_game: Mapping[str, Sequence[Mapping[str, Any]]]
    ) -> "HistoricalParticipantReplayProvider":
        return cls(
            {gid: reconstruct_game_participants(rows) for gid, rows in rows_by_game.items()}
        )

    def game_ids(self) -> list[str]:
        return sorted(self._games)

    def participants(self, game_id: str) -> GameParticipants:
        game = self._games.get(game_id)
        if game is None:
            raise ParticipantReplayError(f"no participant replay for game {game_id}")
        return game

    def batting_order(self, game_id: str, team_id: str) -> Sequence[str]:
        game = self.participants(game_id)
        for team in (game.away, game.home):
            if team is not None and team.team_id == team_id:
                return team.starting_lineup
        raise ParticipantReplayError(f"team {team_id} not in game {game_id}")

    def active_pitcher(self, game_id: str, play_number: int) -> str | None:
        return self.participants(game_id).active_pitcher_at(play_number)


# --------------------------------------------------------------------------------------
# Shared simulation-facing interface (section 16). The future projected provider will
# implement the same contract; it is NOT implemented here.
# --------------------------------------------------------------------------------------
class ParticipationReplayProvider(Protocol):
    def participants(self, game_id: str) -> GameParticipants: ...


class FutureProjectedParticipationProvider(Protocol):
    """Placeholder seam for a future prospective provider (lineup + starter + bullpen +
    confirmed/prospective feed). Deliberately NOT implemented in Phase 5C."""

    def participants(self, game_id: str) -> GameParticipants: ...


__all__ = [
    "PARTICIPANT_CONTRACT_NAME",
    "PARTICIPANT_SCHEMA_VERSION",
    "PROVENANCE_LABEL",
    "COMPLETE",
    "INCOMPLETE",
    "ParticipantReplayError",
    "PlateAppearanceParticipant",
    "TeamParticipants",
    "GameParticipants",
    "reconstruct_game_participants",
    "HistoricalParticipantReplayProvider",
    "ParticipationReplayProvider",
    "FutureProjectedParticipationProvider",
]

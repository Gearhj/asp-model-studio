"""Development-only conditional drive-outcome and empirical-progression engine.

This is an independent research model. It neither explains nor targets M1 scores.
Only 2018--2024 physically separated PBP partitions are opened. State-to-outcome
probabilities are fitted; duration/field progression are sampled jointly from
training drives of the sampled outcome and similar starting field position.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .labs_simulation import file_record

DRIVE_ENGINE = "NFL_DEVELOPMENT_CONDITIONAL_DRIVE_V2"
FEATURES = ["startYardline100", "halfSecondsRemaining", "scoreDifferential",
            "homePossession", "pregameOffensePointsPerDrive", "pregameDefensePointsAllowedPerDrive",
            "lateHalf", "startYardlineSquared"]
RULES_URL = "https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf"
OUTCOMES = {"Touchdown": "TD", "Field goal": "FG", "Punt": "PUNT", "Turnover": "TURNOVER",
            "Turnover on downs": "DOWNS", "Missed field goal": "MISSED_FG", "Opp touchdown": "DEF_TD",
            "Safety": "SAFETY", "End of half": "END_HALF"}


def _duration(value: Any) -> float:
    try:
        minutes, seconds = str(value).split(":")
        return float(minutes)*60+float(seconds)
    except (TypeError, ValueError):
        return float("nan")


def starting_kickoff_evidence(group: pd.DataFrame, first_scrimmage: pd.Series) -> tuple[bool, float, str]:
    """Bind touchback only to the actual kickoff preceding this drive's scrimmage.

    A later punt/interception touchback is never evidence about the opening kick.
    Repeated/absent kicks and missing flags remain unknown and leave the kickoff
    sampling bank; their observed drive starting spot remains valid model data.
    """
    kicks = group.loc[group["play_type"].eq("kickoff") & group["play_id"].lt(first_scrimmage["play_id"])]
    if len(kicks) != 1:
        status = "STARTING_KICKOFF_ABSENT" if len(kicks) == 0 else "STARTING_KICKOFF_AMBIGUOUS"
        return False, float("nan"), status
    kick = kicks.iloc[0]
    if kick.get("posteam") != first_scrimmage["posteam"] or kick["touchback"] not in (0, 1):
        return True, float("nan"), "STARTING_KICKOFF_TOUCHBACK_UNKNOWN"
    return True, float(kick["touchback"]), "OBSERVED_STARTING_KICKOFF_PLAY"


def load_development_drives(bronze_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    pointer = json.loads((bronze_root / "current.json").read_bytes())
    manifest = json.loads((bronze_root / pointer["manifestRelativePath"]).read_bytes())
    partitions = [p for p in manifest["partitions"] if p["familyId"] == "play_by_play" and p.get("season") in range(2018, 2025)]
    if {p["season"] for p in partitions} != set(range(2018, 2025)):
        raise ValueError("expected separated Development PBP2018--2024 partitions")
    columns = ["season", "game_id", "game_date", "week", "home_team", "away_team", "season_type",
               "play_id", "posteam", "defteam", "fixed_drive", "fixed_drive_result", "drive_time_of_possession",
               "drive_start_transition", "yardline_100", "half_seconds_remaining", "game_seconds_remaining",
               "qtr", "posteam_score", "defteam_score", "total_home_score", "total_away_score", "play_type", "touchback"]
    rows, source_files, exclusions = [], [], {}
    for partition in sorted(partitions, key=lambda p: p["season"]):
        path = bronze_root / partition["relativePath"]
        source_ref = file_record(path)
        if source_ref["sha256"] != partition["fileSha256"]:
            raise ValueError("Development source checksum differs")
        source_files.append({**source_ref, "season": partition["season"], "license": partition["license"]})
        frame = pq.read_table(path, columns=columns).to_pandas()
        if not frame["season"].eq(partition["season"]).all():
            raise ValueError("partition season differs")
        frame = frame.sort_values(["game_id", "play_id"])
        for (game, drive), group in frame.groupby(["game_id", "fixed_drive"], sort=False):
            live = group.loc[group["posteam"].notna() & group["yardline_100"].between(1, 99) & ~group["play_type"].isin(["kickoff", "extra_point", "no_play"])]
            if live.empty:
                exclusions["NO_SCRIMMAGE_DRIVE"] = exclusions.get("NO_SCRIMMAGE_DRIVE", 0)+1
                continue
            first = live.iloc[0]
            kind = OUTCOMES.get(first["fixed_drive_result"])
            if kind is None or first["qtr"] > 4:
                exclusions["UNSUPPORTED_OR_OVERTIME_TRAINING_DRIVE"] = exclusions.get("UNSUPPORTED_OR_OVERTIME_TRAINING_DRIVE", 0)+1
                continue
            own_home = first["posteam"] == first["home_team"]
            own = group["total_home_score" if own_home else "total_away_score"].max() - first["posteam_score"]
            opp = group["total_away_score" if own_home else "total_home_score"].max() - first["defteam_score"]
            duration = _duration(first["drive_time_of_possession"])
            allowed = ((kind == "TD" and own in (6, 7, 8) and opp == 0) or
                       (kind == "FG" and own == 3 and opp == 0) or
                       (kind == "DEF_TD" and opp in (6, 7, 8) and own == 0) or
                       (kind == "SAFETY" and opp == 2 and own == 0) or
                       (kind in ("PUNT", "TURNOVER", "DOWNS", "MISSED_FG", "END_HALF") and own == opp == 0))
            if not allowed or not np.isfinite(duration) or duration <= 0:
                exclusions["INCOMPLETE_OR_UNSUPPORTED_SCORE_DURATION"] = exclusions.get("INCOMPLETE_OR_UNSUPPORTED_SCORE_DURATION", 0)+1
                continue
            starts_kickoff, kickoff_touchback, kickoff_status = starting_kickoff_evidence(group, first)
            rows.append({"season": int(first["season"]), "gameId": str(game), "driveId": int(drive),
                         "date": str(first["game_date"]), "week": int(first["week"]), "homeTeam": first["home_team"], "awayTeam": first["away_team"],
                         "offense": first["posteam"], "defense": first["defteam"], "seasonType": first["season_type"],
                         "startYardline100": float(first["yardline_100"]), "halfSecondsRemaining": float(first["half_seconds_remaining"]),
                         "scoreDifferential": float(first["posteam_score"]-first["defteam_score"]), "homePossession": int(own_home),
                         "outcome": kind, "ownPoints": int(own), "opponentPoints": int(opp), "duration": duration,
                         "endYardline100": float(live.iloc[-1]["yardline_100"]), "startsWithKickoff": starts_kickoff,
                         "kickoffTouchback": kickoff_touchback, "kickoffEvidenceStatus": kickoff_status,
                         "legacyKickoffTouchback": bool(group["touchback"].eq(1).any()),
                         "gameSecondsRemaining": float(first["game_seconds_remaining"])})
    drives = pd.DataFrame(rows).sort_values(["date", "gameId", "driveId"]).reset_index(drop=True)
    drives["nextStartYardline100"] = drives.groupby("gameId")["startYardline100"].shift(-1)
    drives["nextOffense"] = drives.groupby("gameId")["offense"].shift(-1)
    drives["nextStartObserved"] = drives["nextOffense"].eq(drives["defense"]) & drives["nextStartYardline100"].between(1, 99)
    return drives, {"schemaVersion": "NFL_DEVELOPMENT_DRIVE_EVIDENCE_V1", "sources": source_files,
                    "seasonsRead": list(range(2018, 2025)), "sealedOotRead": False,
                    "driveCount": len(drives), "gameCount": drives["gameId"].nunique(), "exclusions": exclusions,
                    "kickoffEvidenceStates": {str(k): int(v) for k,v in drives["kickoffEvidenceStatus"].value_counts().items()},
                    "kickoffTouchbackCorrectedComparedWithAnyDriveTouchback": int((drives["startsWithKickoff"] & drives["kickoffTouchback"].notna() & drives["legacyKickoffTouchback"].ne(drives["kickoffTouchback"].eq(1))).sum()),
                    "grain": "one completed regulation drive; score increments include tries; no individual identities"}


def enrich_pregame(drives: pd.DataFrame) -> pd.DataFrame:
    """Strict prior-date state; same-day outcomes never enter a pregame team estimate."""
    frame = drives.copy()
    frame["pregameOffensePointsPerDrive"] = 0.0
    frame["pregameDefensePointsAllowedPerDrive"] = 0.0
    history: dict[str, list[float]] = {}
    league_points, league_n, previous_season = 0.0, 0.0, None
    for day, indices in frame.groupby("date", sort=True).groups.items():
        season = int(frame.loc[indices[0], "season"])
        if previous_season is not None and season != previous_season:
            for values in history.values():
                for i in range(4): values[i] *= .65 ** (season-previous_season)
            league_points *= .65 ** (season-previous_season)
            league_n *= .65 ** (season-previous_season)
        # The first initialization is explicitly fixed at2.0 points/drive, not a median.
        center = league_points/league_n if league_n else 2.0
        for index in indices:
            row = frame.loc[index]
            off = history.get(row["offense"], [0, 0, 0, 0])
            defense = history.get(row["defense"], [0, 0, 0, 0])
            frame.at[index, "pregameOffensePointsPerDrive"] = (off[0]+40*center)/(off[1]+40)
            frame.at[index, "pregameDefensePointsAllowedPerDrive"] = (defense[2]+40*center)/(defense[3]+40)
        for index in indices:
            row = frame.loc[index]
            off = history.setdefault(row["offense"], [0.0]*4)
            defense = history.setdefault(row["defense"], [0.0]*4)
            off[0] += row["ownPoints"]; off[1] += 1
            defense[2] += row["ownPoints"]; defense[3] += 1
            league_points += row["ownPoints"]; league_n += 1
        previous_season = season
    frame["lateHalf"] = frame["halfSecondsRemaining"].le(120).astype(int)
    frame["startYardlineSquared"] = frame["startYardline100"] ** 2
    return frame


@dataclass
class DriveModel:
    estimator: Any
    banks: dict[tuple[str, int], np.ndarray]
    all_banks: dict[str, np.ndarray]
    kickoff: np.ndarray
    training_cutoff: str
    training_season: int
    league_center: float
    team_state: dict[str, tuple[float, float, float, float]]
    training_drives: int

    def context(self, home: str, away: str, season: int) -> tuple[float, float, float, float]:
        discount = .65 ** max(0, season-self.training_season)
        result = []
        for team in (home, away):
            o, n, d, dn = self.team_state.get(team, (0, 0, 0, 0))
            result.extend(((o*discount+40*self.league_center)/(n*discount+40), (d*discount+40*self.league_center)/(dn*discount+40)))
        return tuple(result)


def fit_drive_model(drives: pd.DataFrame, *, end_season: int) -> DriveModel:
    if end_season >= 2025:
        raise ValueError("sealed season is not permitted for drive fitting")
    train = drives.loc[drives["season"] <= end_season].copy()
    estimator = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=300, random_state=930731))
    estimator.fit(train[FEATURES].to_numpy(float), train["outcome"])
    banks, all_banks = {}, {}
    for kind, group in train.groupby("outcome"):
        # Next field position is observed only when possession changed normally.
        next_yard = group["nextStartYardline100"].where(group["nextStartObserved"], np.nan)
        bank = np.column_stack([group["duration"], group["endYardline100"], group["ownPoints"], group["opponentPoints"], next_yard])
        all_banks[kind] = bank
        buckets = (group["startYardline100"].to_numpy() // 20).astype(int)
        for bucket in range(5):
            subset = bank[buckets == bucket]
            if len(subset) >= 20: banks[(kind, bucket)] = subset
    kickoff_rows = train.loc[train["startsWithKickoff"] & train["kickoffTouchback"].notna() & train["startYardline100"].between(1, 99)]
    kickoff = kickoff_rows[["startYardline100", "kickoffTouchback"]].to_numpy(float)
    state = {}
    for team in sorted(set(train["offense"]) | set(train["defense"])):
        off = train.loc[train["offense"].eq(team)]; defense = train.loc[train["defense"].eq(team)]
        ow = .65 ** (end_season-off["season"].to_numpy()); dw = .65 ** (end_season-defense["season"].to_numpy())
        state[team] = (float(np.dot(ow, off["ownPoints"])), float(ow.sum()), float(np.dot(dw, defense["ownPoints"])), float(dw.sum()))
    return DriveModel(estimator, banks, all_banks, kickoff, str(train["date"].max()), end_season,
                      float(train["ownPoints"].mean()), state, len(train))


def overtime_finished(home: int, away: int, possessions: int, *, first_drive_defensive_score: bool,
                      first_drive_td: bool, season: int, postseason: bool) -> bool:
    if first_drive_defensive_score:
        return True
    both_required = season >= 2025 or (postseason and season >= 2022)
    if possessions == 1 and first_drive_td and not both_required:
        return True
    return possessions >= 2 and home != away


def simulate_drive_game(model: DriveModel, *, home_team: str, away_team: str, season: int,
                        postseason: bool, seed: int, pace_multiplier: float = 1.0) -> dict[str, Any]:
    if not .9 <= pace_multiplier <= 1.1:
        raise ValueError("supported pace duration multiplier is0.9--1.1 only")
    rng = np.random.default_rng(seed)
    context = model.context(home_team, away_team, season)
    score = [0, 0]; sequence = []; opening = int(rng.integers(2)); regulation_tie = False

    def kickoff_yard() -> float:
        row = model.kickoff[int(rng.integers(len(model.kickoff)))]
        # Model all direct-touchback starts using the applicable standard kickoff spot;
        # landing-zone-touchback distinction remains a declared unsupported detail.
        if row[1]: return float(65 if season >= 2025 else (70 if season == 2024 else 75))
        return float(row[0])

    def play_period(seconds: float, possession: int, period: str, *, ot: bool = False) -> tuple[float, int, bool]:
        yard = kickoff_yard(); used_possessions = 0; overtime_ended = False
        while seconds > 0:
            off_idx = 0 if possession == 0 else 2; def_idx = 3 if possession == 0 else 1
            state = np.asarray([[yard, seconds, score[possession]-score[1-possession], int(possession == 0), context[off_idx], context[def_idx], int(seconds <= 120), yard*yard]])
            scaled = (state[0]-model.estimator[0].mean_)/model.estimator[0].scale_
            logits = model.estimator[1].coef_ @ scaled + model.estimator[1].intercept_
            probabilities = np.exp(logits-np.max(logits)); probabilities /= probabilities.sum()
            kind = str(rng.choice(model.estimator[1].classes_, p=probabilities))
            bank = model.banks.get((kind, min(4, int(yard//20))), model.all_banks[kind])
            sample = bank[int(rng.integers(len(bank)))]
            duration, end_yard, own, opp, next_yard = sample
            duration = max(1.0, duration*pace_multiplier)
            before = list(score); seconds_before = seconds
            # A drive censored by the half/regular-OT clock is not granted a score.
            if kind == "END_HALF" or duration > seconds:
                duration = seconds; own = opp = 0; kind = "CLOCK_EXPIRED"; end_yard = None
            if ot:
                # No unnecessary try after a touchdown that itself ends overtime.
                both_required = season >= 2025 or (postseason and season >= 2022)
                if opp >= 6: opp = 6
                if own >= 6 and ((used_possessions == 0 and not both_required) or
                                 (used_possessions >= 1 and score[possession]+6 > score[1-possession])):
                    own = 6
            score[possession] += int(own); score[1-possession] += int(opp)
            seconds = max(0.0, seconds-duration)
            used_possessions += 1
            next_possession = possession if kind == "DEF_TD" else 1-possession
            if kind in ("TD", "FG", "DEF_TD", "SAFETY"):
                next_start = kickoff_yard()
            elif np.isfinite(next_yard):
                next_start = float(next_yard)
            else:
                # Unobserved turnover return: explicit no-return field-position treatment.
                next_start = float(np.clip(100-(end_yard if end_yard is not None else yard), 1, 99))
            event = {"driveNumber": len(sequence)+1, "period": period,
                     "possession": "HOME" if possession == 0 else "AWAY", "offenseTeam": home_team if possession == 0 else away_team,
                     "startYardline100": yard, "endYardline100": end_yard,
                     "periodSecondsBefore": seconds_before, "periodSecondsAfter": seconds, "durationSeconds": duration,
                     "outcome": kind, "homePointsAdded": score[0]-before[0], "awayPointsAdded": score[1]-before[1],
                     "homeScoreAfter": score[0], "awayScoreAfter": score[1],
                     "nextPossession": "HOME" if next_possession == 0 else "AWAY", "nextStartYardline100": next_start if seconds else None}
            sequence.append(event)
            if ot and overtime_finished(*score, used_possessions,
                                       first_drive_defensive_score=used_possessions == 1 and opp > 0,
                                       first_drive_td=used_possessions == 1 and own >= 6, season=season, postseason=postseason):
                overtime_ended = True
                break
            possession, yard = next_possession, next_start
            if len(sequence) > 250: raise ValueError("drive engine did not terminate")
        return seconds, possession, overtime_ended

    play_period(1800, opening, "REGULATION_HALF_1")
    play_period(1800, 1-opening, "REGULATION_HALF_2")
    regulation = list(score); regulation_tie = score[0] == score[1]
    if regulation_tie:
        if postseason:
            # Continuous post-season OT preserves possession opportunity across15-minute
            # boundaries; this first version deliberately refuses unsupported continuation.
            raise ValueError("POSTSEASON_OVERTIME_CONTINUATION_UNSUPPORTED_V1")
        play_period(600 if season >= 2017 else 900, int(rng.integers(2)), "OVERTIME", ot=True)
    result = {"homeScore": score[0], "awayScore": score[1], "regulationHomeScore": regulation[0],
              "regulationAwayScore": regulation[1], "regulationTie": regulation_tie, "reachedOvertime": regulation_tie,
              "finalTie": score[0] == score[1], "seed": seed, "drives": sequence}
    verify_drive_accounting(result)
    return result


def verify_drive_accounting(game: dict[str, Any]) -> None:
    home = away = 0
    clocks: dict[str, float] = {}
    for drive in game["drives"]:
        if drive["durationSeconds"] <= 0 or drive["periodSecondsAfter"] < 0:
            raise ValueError("invalid drive clock")
        if drive["period"] in clocks and clocks[drive["period"]] != drive["periodSecondsBefore"]:
            raise ValueError("discontinuous drive clock")
        clocks[drive["period"]] = drive["periodSecondsAfter"]
        if abs(drive["periodSecondsBefore"]-drive["durationSeconds"]-drive["periodSecondsAfter"]) > 1e-9:
            raise ValueError("drive clock accounting differs")
        home += drive["homePointsAdded"]; away += drive["awayPointsAdded"]
        if [home, away] != [drive["homeScoreAfter"], drive["awayScoreAfter"]]: raise ValueError("drive score accounting differs")
    if [home, away] != [game["homeScore"], game["awayScore"]]: raise ValueError("final drive score differs")

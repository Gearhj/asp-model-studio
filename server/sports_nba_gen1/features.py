"""Fixed, source-independent NBA team features with target-time admission.

This module certifies calculations, not source rights or authentic availability
clocks.  The population admission layer must establish those independently.
No fixture or synthetic calculation check is evidence of model performance.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math

import numpy as np
import pandas as pd


BOX_FIELDS = ("fgm", "fga", "fg3m", "ftm", "fta", "oreb", "dreb", "tov", "minutes")
RATE_FIELDS = ("off_efficiency", "def_efficiency", "adjusted_off_efficiency",
               "adjusted_def_efficiency", "pace", "efg", "tov_rate", "oreb_rate", "fta_rate")
TEAM_FIELDS = RATE_FIELDS + (
    "elo", "rest_days", "back_to_back", "games_last_3_days", "games_last_7_days",
    "games_last_14_days", "season_games_played", "rolling_games", "prior_season_games",
    "current_season_weight", "history_supported", "early_season", "rest_known",
    "prior_off_efficiency", "prior_def_efficiency", "prior_pace",
)
FEATURE_COLUMNS = tuple(f"{side}_{field}" for side in ("home", "away") for field in TEAM_FIELDS) + (
    "home_court", "elo_home_win_probability", "league_history_games",
) + tuple(f"difference_{field}" for field in RATE_FIELDS + ("elo", "rest_days", "games_last_7_days"))

_CONTRACT = {
    "schema": "nba-gen1-point-in-time-features-v1",
    "scope": "NBA REGULAR full-game FINAL scores including overtime",
    "sourceGate": "Caller authenticates real data, rights, clocks, schedule identity and completeness; no source certification is inferred here.",
    "cutoff": "source_available_at_utc < target scheduled_tipoff_utc; source scheduled_tipoff_utc < target tipoff; target game excluded",
    "revisionPolicy": "Latest eligible source revision by availability, then revision; one game identity, one contribution. Later revisions never enter earlier target rows.",
    "possessions": "0.5*((home_fga + 0.44*home_fta - home_oreb + home_tov) + (away_fga + 0.44*away_fta - away_oreb + away_tov))",
    "pace": "estimated possessions * 48 / ((home_minutes + away_minutes) / 10); minutes are summed player minutes",
    "efficiencyUnits": "points per 100 estimated possessions",
    "fourFactors": {"efg": "(fgm + 0.5*fg3m)/fga", "tov_rate": "tov/(fga + 0.44*fta + tov)",
                    "oreb_rate": "oreb/(oreb + opponent_dreb)", "fta_rate": "fta/fga"},
    "aggregation": "Arithmetic average of game-level rates, symmetric across teams; equal-game weights, not possession-weighted pooled rates.",
    "rollingWindowGames": 20,
    "priorSeason": "Immediately preceding season only; team prior-season rates shrunk to that season's league rates with 10 pseudo-games. If absent, use earlier admitted league rates.",
    "currentSeason": "Last 20 current-season game rates shrunk to prior-season ratings with 10 pseudo-games; weight n/(n+10). All-season game count retained separately.",
    "opponentAdjustment": "As-of-target chronological replay of admitted results. Game offense minus (opponent earlier-game raw defense rating minus earlier league defense); analogous defense adjustment. No iterative fit. Replay ratings are not asserted to be pregame captures for those historical games.",
    "elo": {"initial": 1500.0, "homeAdvantage": 65.0, "scale": 400.0, "k": 20.0,
            "seasonRegression": "At each new season regress previous Elo two-thirds toward its prior value and one-third to 1500; skipped seasons repeat regression.",
            "update": "Chronological eligible final wins/losses; overtime is a normal full-game win/loss."},
    "rest": "max(0, Eastern-calendar dates between latest admitted completed game and target minus one); nullable if no prior admitted game",
    "backToBack": "Exactly one Eastern-calendar day between latest admitted completed game and target; false when history unavailable, accompanied by rest_known=0",
    "density": "Counts of admitted completed games with scheduled tipoffs in [target minus 3/7/14 elapsed days, target)",
    "unsupported": "history_supported=0 when current plus immediately-prior-season game count <5; no prior league rates yields nullable features, never fabricated statistics",
    "earlySeason": "current-season completed games <10",
    "homeCourt": "Nominal scheduled home orientation, not certified neutral-venue or travel information",
    "noPregameEvidence": ["injuries", "expected_starters", "lineups", "player_talent", "travel", "referees", "market_odds"],
    "numericFeatures": list(FEATURE_COLUMNS),
}


def feature_contract() -> dict:
    """Return a serializable fixed definition and its canonical identity."""
    result = deepcopy(_CONTRACT)
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    result["sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def _timestamp(value, field: str) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError(f"{field} must be an explicit timezone-aware timestamp")
    return result.tz_convert("UTC")


def _identity(record: dict, *, target: bool) -> dict:
    row = dict(record)
    for name in ("game_id", "home_team_id", "away_team_id"):
        if name not in row or pd.isna(row[name]) or not str(row[name]).strip():
            raise ValueError(f"Missing stable {name}")
        row[name] = str(row[name])
    if row["home_team_id"] == row["away_team_id"]:
        raise ValueError("Home and away identities must differ")
    if row.get("season_type") != "REGULAR":
        raise ValueError("Only the declared REGULAR population is supported")
    if not isinstance(row.get("season"), (int, np.integer)) or row["season"] < 1946:
        raise ValueError("season must be an integer start year")
    row["season"] = int(row["season"])
    row["scheduled_tipoff_utc"] = _timestamp(row["scheduled_tipoff_utc"], "scheduled_tipoff_utc")
    if not target and row.get("status") != "FINAL":
        raise ValueError("History must contain eligible FINAL records only")
    if target and row.get("status") not in ("SCHEDULED", "FINAL"):
        raise ValueError("Target must be SCHEDULED or FINAL; resolve cancellation/rescheduling upstream")
    return row


def _history_records(games: pd.DataFrame) -> list[dict]:
    records = []
    identities, versions, revision_clocks = {}, set(), defaultdict(list)
    for raw in games.to_dict("records"):
        row = _identity(raw, target=False)
        row["source_available_at_utc"] = _timestamp(row["source_available_at_utc"], "source_available_at_utc")
        if row["source_available_at_utc"] <= row["scheduled_tipoff_utc"]:
            raise ValueError("A FINAL record cannot be available at or before its own tipoff")
        revision = row.get("source_revision", 1)
        if not isinstance(revision, (int, np.integer)) or revision < 1:
            raise ValueError("source_revision must be a positive integer")
        row["source_revision"] = int(revision)
        gid = row["game_id"]
        identity = (row["season"], row["home_team_id"], row["away_team_id"])
        if gid in identities and identities[gid] != identity:
            raise ValueError("A game identity changes season or home/away orientation")
        identities[gid] = identity
        key = (gid, row["source_revision"])
        if key in versions:
            raise ValueError("Duplicate game/revision; reconcile repeated or replacement events upstream")
        versions.add(key)
        revision_clocks[gid].append((row["source_revision"], row["source_available_at_utc"]))
        for side in ("home", "away"):
            for field in ("score",) + BOX_FIELDS:
                value = float(row[f"{side}_{field}"])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"Invalid {side}_{field}")
                if field != "minutes" and not value.is_integer():
                    raise ValueError(f"{side}_{field} must be an integer count")
                row[f"{side}_{field}"] = value
            if row[f"{side}_fga"] <= 0 or row[f"{side}_minutes"] <= 0:
                raise ValueError("Positive attempts and minutes are required")
            if row[f"{side}_fg3m"] > row[f"{side}_fgm"] or row[f"{side}_fgm"] > row[f"{side}_fga"]:
                raise ValueError("Field-goal components do not reconcile")
            if row[f"{side}_ftm"] > row[f"{side}_fta"]:
                raise ValueError("Free-throw components do not reconcile")
            if row[f"{side}_score"] != 2*row[f"{side}_fgm"] + row[f"{side}_fg3m"] + row[f"{side}_ftm"]:
                raise ValueError("Final score does not reconcile with team box points")
        if row["home_score"] == row["away_score"]:
            raise ValueError("A completed NBA game cannot be tied")
        ot = row.get("overtime_periods")
        if not isinstance(ot, (int, np.integer)) or ot < 0:
            raise ValueError("overtime_periods must be a nonnegative integer")
        expected_minutes = 240 + 25*int(ot)
        if any(abs(row[f"{side}_minutes"] - expected_minutes) > 1 for side in ("home", "away")):
            raise ValueError("Team minutes disagree with completed full-game overtime duration")
        records.append(row)
    for clocks in revision_clocks.values():
        ordered = sorted(clocks)
        if any(a[1] > b[1] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Higher revisions must not precede lower revision availability")
    return sorted(records, key=lambda r: (r["source_available_at_utc"], r["source_revision"], r["game_id"]))


def _mean(rows: list[dict], field: str) -> float:
    values = [row[field] for row in rows if math.isfinite(row[field])]
    return float(sum(values)/len(values)) if values else float("nan")


def _shrink(value: float, count: int, prior: float, strength: int = 10) -> float:
    if not math.isfinite(prior):
        return value
    if not count or not math.isfinite(value):
        return prior
    return (count*value + strength*prior)/(count+strength)


class _League:
    def __init__(self):
        self.sums = defaultdict(lambda: defaultdict(float))
        self.counts = defaultdict(int)

    def append(self, season: int, metrics: dict) -> None:
        for key in (season, None):
            self.counts[key] += 1
            for field in RATE_FIELDS:
                self.sums[key][field] += metrics[field]

    def mean(self, season: int | None, field: str) -> float:
        count = self.counts.get(season, 0)
        return self.sums[season][field]/count if count else float("nan")


def _rates_for(team: str, season: int, histories: dict, league: _League) -> tuple[dict, dict, list, list]:
    current = histories.get((team, season), [])
    previous = histories.get((team, season-1), [])
    league_prior_season = season-1 if league.counts.get(season-1, 0) else None
    rolling = current[-20:]
    priors, result = {}, {}
    for field in RATE_FIELDS:
        priors[field] = _shrink(_mean(previous, field), len(previous), league.mean(league_prior_season, field))
        result[field] = _shrink(_mean(rolling, field), len(rolling), priors[field])
    return result, priors, current, previous


def _replay(records: list[dict], target_season: int, state=None) -> tuple[dict, _League, dict]:
    """Replay only records already admitted at the target's cutoff."""
    histories, league, elo = state if state is not None else (defaultdict(list), _League(), {})
    ordered = sorted(records, key=lambda r: (r["scheduled_tipoff_utc"], r["game_id"]))
    for row in ordered:
        season, home, away = row["season"], row["home_team_id"], row["away_team_id"]
        if season > target_season:
            raise ValueError("Historical season identity exceeds target season")
        before = {team: _rates_for(team, season, histories, league)[0] for team in (home, away)}
        league_off = league.mean(None, "off_efficiency")
        league_def = league.mean(None, "def_efficiency")
        possessions = sum(row[f"{side}_fga"] + .44*row[f"{side}_fta"] - row[f"{side}_oreb"] + row[f"{side}_tov"] for side in ("home", "away"))/2
        if possessions <= 0:
            raise ValueError("Estimated possessions must be positive")
        pace = possessions*48/((row["home_minutes"] + row["away_minutes"])/10)
        both = []
        for side, other, team, opponent in (("home", "away", home, away), ("away", "home", away, home)):
            raw_off = 100*row[f"{side}_score"]/possessions
            raw_def = 100*row[f"{other}_score"]/possessions
            opp_def, opp_off = before[opponent]["def_efficiency"], before[opponent]["off_efficiency"]
            def_deviation = opp_def-league_def if math.isfinite(opp_def) and math.isfinite(league_def) else 0.
            off_deviation = opp_off-league_off if math.isfinite(opp_off) and math.isfinite(league_off) else 0.
            rebound_denominator = row[f"{side}_oreb"] + row[f"{other}_dreb"]
            if rebound_denominator <= 0:
                raise ValueError("Offensive rebound rate requires positive rebound opportunities")
            metrics = {"game_id": row["game_id"], "tipoff": row["scheduled_tipoff_utc"],
                       "off_efficiency": raw_off, "def_efficiency": raw_def,
                       "adjusted_off_efficiency": raw_off-def_deviation,
                       "adjusted_def_efficiency": raw_def-off_deviation, "pace": pace,
                       "efg": (row[f"{side}_fgm"] + .5*row[f"{side}_fg3m"])/row[f"{side}_fga"],
                       "tov_rate": row[f"{side}_tov"]/(row[f"{side}_fga"] + .44*row[f"{side}_fta"] + row[f"{side}_tov"]),
                       "oreb_rate": row[f"{side}_oreb"]/rebound_denominator,
                       "fta_rate": row[f"{side}_fta"]/row[f"{side}_fga"]}
            both.append((team, metrics))
        # Both teams' rates were calculated from the same earlier-game state.
        for team, metrics in both:
            histories[(team, season)].append(metrics)
            league.append(season, metrics)
            value, elo_season = elo.get(team, (1500., season))
            elo[team] = (1500. + (value-1500.)*(2/3)**(season-elo_season), season)
        home_rating, away_rating = elo[home][0], elo[away][0]
        probability = 1/(1 + 10**((away_rating-home_rating-65)/400))
        change = 20*(float(row["home_score"] > row["away_score"])-probability)
        elo[home], elo[away] = (home_rating+change, season), (away_rating-change, season)
    return histories, league, elo


def build_features(games: pd.DataFrame, target_games: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Build target rows using only eligible earlier FINAL revisions.

    `games` is the authenticated, authorized history. `target_games` contains
    identity/schedule columns only; scores or boxes on targets are never read.
    If targets are omitted, unique latest source identities define the targets.
    Audit binds each target's eligible game/revision set by canonical hash,
    with the source identity/revision/time ledger retained once for all targets.
    """
    records = _history_records(games)
    if target_games is None:
        latest = {row["game_id"]: row for row in records}
        targets = [_identity(row, target=True) for row in latest.values()]
    else:
        targets = [_identity(row, target=True) for row in target_games.to_dict("records")]
    if len({row["game_id"] for row in targets}) != len(targets):
        raise ValueError("Targets must contain exactly one schedule identity per game")
    targets.sort(key=lambda r: (r["scheduled_tipoff_utc"], r["game_id"]))
    output, audit_rows, active, pointer = [], [], {}, 0
    state, replayed, last_order_key = None, {}, None
    full_replays, incremental_updates = 0, 0
    history_identities = {r["game_id"]: (r["season"], r["home_team_id"], r["away_team_id"]) for r in records}
    for target in targets:
        cutoff, gid, season = target["scheduled_tipoff_utc"], target["game_id"], target["season"]
        identity = (season, target["home_team_id"], target["away_team_id"])
        if gid in history_identities and history_identities[gid] != identity:
            raise ValueError("Target and history disagree on game orientation or season")
        while pointer < len(records) and records[pointer]["source_available_at_utc"] < cutoff:
            row = records[pointer]
            active[row["game_id"]] = row
            pointer += 1
        eligible = [r for key, r in active.items() if key != gid and r["scheduled_tipoff_utc"] < cutoff]
        eligible_versions = {r["game_id"]: r["source_revision"] for r in eligible}
        new_rows = [r for r in eligible if replayed.get(r["game_id"]) != r["source_revision"]]
        order_key = lambda r: (r["scheduled_tipoff_utc"], r["game_id"])
        changed_old = any(gid0 not in eligible_versions or eligible_versions[gid0] != revision for gid0, revision in replayed.items())
        inserted_earlier = last_order_key is not None and any(order_key(r) < last_order_key for r in new_rows)
        if state is None or changed_old or inserted_earlier:
            state = _replay(eligible, season)
            full_replays += 1
        elif new_rows:
            state = _replay(new_rows, season, state)
            incremental_updates += 1
        histories, league, elo = state
        replayed = eligible_versions
        last_order_key = max((order_key(r) for r in eligible), default=None)
        result = {name: target[name] for name in ("game_id", "season", "scheduled_tipoff_utc", "home_team_id", "away_team_id")}
        result["home_court"] = 1.
        result["league_history_games"] = len(eligible)
        for side in ("home", "away"):
            team = target[f"{side}_team_id"]
            rates, priors, current, previous = _rates_for(team, season, histories, league)
            all_history = sorted([r for (tid, _), values in histories.items() if tid == team for r in values], key=lambda r: r["tipoff"])
            last = all_history[-1]["tipoff"] if all_history else None
            date_difference = (cutoff.tz_convert("America/New_York").date() - last.tz_convert("America/New_York").date()).days if last is not None else None
            value, elo_season = elo.get(team, (1500., season))
            metrics = {**rates, "elo": 1500. + (value-1500.)*(2/3)**(season-elo_season),
                       "rest_days": max(0, date_difference-1) if date_difference is not None else float("nan"),
                       "back_to_back": int(date_difference == 1), "rest_known": int(last is not None),
                       "season_games_played": len(current), "rolling_games": min(20, len(current)),
                       "prior_season_games": len(previous), "current_season_weight": min(20,len(current))/(min(20,len(current))+10),
                       "history_supported": int(len(current)+len(previous) >= 5), "early_season": int(len(current) < 10),
                       "prior_off_efficiency": priors["off_efficiency"], "prior_def_efficiency": priors["def_efficiency"], "prior_pace": priors["pace"]}
            for days in (3, 7, 14):
                metrics[f"games_last_{days}_days"] = sum(cutoff-pd.Timedelta(days=days) <= r["tipoff"] < cutoff for r in all_history)
            result.update({f"{side}_{key}": value for key, value in metrics.items()})
        result["elo_home_win_probability"] = 1/(1 + 10**((result["away_elo"]-result["home_elo"]-65)/400))
        for field in RATE_FIELDS + ("elo", "rest_days", "games_last_7_days"):
            result[f"difference_{field}"] = result[f"home_{field}"]-result[f"away_{field}"]
        output.append(result)
        bindings = [(r["game_id"], r["source_revision"]) for r in sorted(eligible, key=lambda r: r["game_id"])]
        binding_sha = hashlib.sha256(json.dumps(bindings, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        audit_rows.append({"game_id": gid, "cutoff": cutoff.isoformat(), "eligibleHistoryGames": len(eligible),
                           "maxHistoryAvailability": max((r["source_available_at_utc"] for r in eligible), default=None).isoformat() if eligible else None,
                           "eligibleHistoryIdentitySha256": binding_sha, "homeSupported": bool(result["home_history_supported"]),
                           "awaySupported": bool(result["away_history_supported"])})
    frame = pd.DataFrame(output, columns=["game_id", "season", "scheduled_tipoff_utc", "home_team_id", "away_team_id", *FEATURE_COLUMNS])
    audit = {"schema": "nba-gen1-feature-audit-v1", "featureContract": feature_contract(),
             "historyRows": len(records), "distinctHistoryGames": len({r["game_id"] for r in records}),
             "targetGames": len(targets), "sourceAdmissionNotPerformedHere": True,
             "chronologicalFullReplays": full_replays, "incrementalUpdates": incremental_updates,
             "historyRevisions": [{"game_id": r["game_id"], "season": r["season"], "home_team_id": r["home_team_id"],
                                   "away_team_id": r["away_team_id"], "source_revision": r["source_revision"],
                                   "scheduled_tipoff_utc": r["scheduled_tipoff_utc"].isoformat(),
                                   "source_available_at_utc": r["source_available_at_utc"].isoformat()} for r in records],
             "allRowsStrictlyBeforeTarget": True, "targetRows": audit_rows}
    return frame, audit

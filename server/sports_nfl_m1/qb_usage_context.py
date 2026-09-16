"""Research-only lagged QB-usage context; never infer a target game's starter.

Only the listed identity and usage columns are opened from physically separated
Development PBP. Historical availability is a conservative reconstruction, not
an archived publication vintage. Current expected starters and injuries are not
inputs to this component.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow.parquet as pq

from .current_state_features import TEAM_ALIASES, completion_upper_bound


CONTRACT = "NFL_M1_LAGGED_QB_USAGE_CONTEXT_V1"
EVIDENCE_CLASS = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
DEVELOPMENT_SEASONS = frozenset(range(1999, 2025))
GAME_TYPES = frozenset({"REG", "POST", "WC", "DIV", "CON", "SB"})
PBP_COLUMNS = (
    "season", "season_type", "week", "game_id", "game_date", "home_team",
    "away_team", "posteam", "play_id", "play_type", "qb_dropback",
    "qb_scramble", "two_point_attempt", "passer_player_id", "rusher_player_id",
)


@dataclass(frozen=True)
class UsageContextConfig:
    lookback_games: int = 3
    minimum_prior_games: int = 2
    minimum_dropbacks_per_game: int = 20
    minimum_attribution_fraction: float = 0.90
    stable_dominant_share: float = 0.80
    reconstructed_lag_hours: int = 48
    same_season_only: bool = True

    def __post_init__(self):
        if not (2 <= self.minimum_prior_games <= self.lookback_games):
            raise ValueError("at least two prior games and a compatible lookback required")
        if self.minimum_dropbacks_per_game < 1:
            raise ValueError("positive dropback support required")
        if not (0 < self.minimum_attribution_fraction <= 1):
            raise ValueError("attribution fraction must be in (0,1]")
        if not (0.5 < self.stable_dominant_share <= 1):
            raise ValueError("dominant share must exceed one half")
        if self.reconstructed_lag_hours != 48 or not self.same_season_only:
            raise ValueError("V1 fixes a 48-hour reconstruction lag and same-season history")


DEFAULT_CONFIG = UsageContextConfig()


def _team(value: Any) -> str:
    if value is None or pd.isna(value) or not str(value).strip():
        raise ValueError("missing team identity")
    return TEAM_ALIASES.get(str(value), str(value))


def _file_ref(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
            "byteCount": len(raw)}


def aggregate_usage_partition(frame: pd.DataFrame, *, expected_season: int) -> pd.DataFrame:
    """Count source-flagged dropbacks with explicit missing actor attribution.

    Pass/run rows with qb_dropback=1 and no two-point attempt are opportunities.
    The actor is the source passer ID or, only on a flagged scramble without a
    passer ID, the rusher ID. Trick-play passers can therefore contribute; this
    is observed dropback usage, not a position-roster or current-starter claim.
    """
    if expected_season not in DEVELOPMENT_SEASONS:
        raise ValueError("only separated Development 1999--2024 is permitted")
    if not set(PBP_COLUMNS).issubset(frame.columns):
        raise ValueError("PBP identity/usage columns are incomplete")
    if not frame["season"].eq(expected_season).all():
        raise ValueError("physical partition contains a different season")
    frame = frame.loc[frame["season_type"].isin(GAME_TYPES), list(PBP_COLUMNS)].copy()
    if frame.duplicated(["game_id", "play_id"]).any():
        raise ValueError("duplicate PBP game/play identity")
    rows = []
    for game_id, game in frame.groupby("game_id", sort=True):
        identity_columns = ("season", "season_type", "week", "game_date", "home_team", "away_team")
        if any(game[column].nunique(dropna=False) != 1 for column in identity_columns):
            raise ValueError("ambiguous PBP game identity")
        first = game.iloc[0]
        game_date = pd.Timestamp(first["game_date"]).normalize().tz_localize(None)
        base = {"canonical_game_id": str(game_id), "game_date": game_date,
                "season": expected_season, "week": int(first["week"]),
                "game_type": str(first["season_type"]),
                "canonical_home_team_id": _team(first["home_team"]),
                "canonical_away_team_id": _team(first["away_team"]),
                "available_utc": completion_upper_bound(game_date) + pd.Timedelta(hours=48),
                "evidence_class": EVIDENCE_CLASS}
        valid = game["play_type"].isin(["pass", "run"]) & game["qb_dropback"].eq(1) & game["two_point_attempt"].eq(0)
        for side in ("home", "away"):
            team_id = base[f"canonical_{side}_team_id"]
            own = game.loc[game["posteam"].map(lambda x: None if pd.isna(x) else _team(x)).eq(team_id)]
            dropbacks = game.loc[valid & game.index.isin(own.index)]
            actors = dropbacks["passer_player_id"].replace("", None).copy()
            scrambled = actors.isna() & dropbacks["qb_scramble"].eq(1)
            actors.loc[scrambled] = dropbacks.loc[scrambled, "rusher_player_id"].replace("", None)
            counts = Counter(str(actor) for actor in actors.dropna())
            total = len(dropbacks)
            attributed = sum(counts.values())
            leader = min(counts, key=lambda key: (-counts[key], key)) if counts else None
            rows.append({**base, "team_id": team_id,
                         "dropbacks": total, "attributed_dropbacks": attributed,
                         "unattributed_dropbacks": total - attributed,
                         "attribution_fraction": attributed / total if total else None,
                         "actor_counts_json": json.dumps(dict(sorted(counts.items())), sort_keys=True),
                         "leader_id": leader,
                         "leader_share": counts[leader] / attributed if leader is not None else None,
                         "unknown_dropback_flag_rows": int(own.loc[own["play_type"].isin(["pass", "run"]), "qb_dropback"].isna().sum()),
                         "unknown_two_point_flag_rows": int((own["qb_dropback"].eq(1) & own["two_point_attempt"].isna()).sum())})
    return pd.DataFrame(rows)


def load_development_usage(bronze_root: Path, *, seasons: Iterable[int] = range(2020, 2025)):
    """Verify source identity before opening only permitted usage columns.

    Season scope is checked before any pointer or payload access. The mixed
    manifest is metadata; 2025 source payloads are never opened or hashed.
    """
    seasons = tuple(sorted(set(int(season) for season in seasons)))
    if not seasons or not set(seasons).issubset(DEVELOPMENT_SEASONS):
        raise ValueError("only explicitly scoped Development 1999--2024 is permitted")
    root = Path(bronze_root).resolve()
    pointer = json.loads((root / "current.json").read_bytes())
    manifest_path = (root / pointer["manifestRelativePath"]).resolve()
    if not manifest_path.is_relative_to(root):
        raise ValueError("Bronze manifest escapes source root")
    manifest_ref = _file_ref(manifest_path)
    if manifest_ref["sha256"] != pointer["manifestSha256"]:
        raise ValueError("Bronze manifest physical checksum differs")
    manifest = json.loads(manifest_path.read_bytes())
    partitions = [item for item in manifest["partitions"] if item["familyId"] == "play_by_play"
                  and item.get("season") in seasons]
    if len(partitions) != len(seasons) or {item["season"] for item in partitions} != set(seasons):
        raise ValueError("declared PBP seasons are missing or duplicated")
    frames, sources = [], []
    for partition in sorted(partitions, key=lambda item: item["season"]):
        path = (root / partition["relativePath"]).resolve()
        if not path.is_relative_to(root) or f"season={partition['season']}" not in path.parts:
            raise ValueError("PBP source is not physically season-separated")
        ref = _file_ref(path)
        if ref["sha256"] != partition["fileSha256"]:
            raise ValueError("PBP source checksum differs")
        source = {**ref, "season": partition["season"],
                  **{key: partition.get(key) for key in ("retrievedAt", "assetUpdatedAt", "releasePublishedAt", "sourceUrl", "license")}}
        parquet = pq.ParquetFile(path)
        if not set(PBP_COLUMNS).issubset(parquet.schema_arrow.names):
            raise ValueError("required PBP usage columns unavailable")
        frames.append(aggregate_usage_partition(parquet.read(columns=list(PBP_COLUMNS)).to_pandas(), expected_season=partition["season"]))
        sources.append(source)
    usage = pd.concat(frames, ignore_index=True)
    receipt = {"contract": CONTRACT, "sourceManifest": manifest_ref, "sources": sources,
               "seasonsRead": list(seasons), "columnsRead": list(PBP_COLUMNS),
               "teamGameRows": len(usage), "distinctGames": int(usage["canonical_game_id"].nunique()),
               "sealed2025Read": False, "target2026OutcomesRead": False,
               "targetStarterKnown": False, "evidenceClass": EVIDENCE_CLASS,
               "definitions": context_definition(),
               "limitations": ["Finalized historical source corrections remain; these are not archived pregame input vintages.",
                               "Observed prior dropback actors do not identify the expected target-game quarterback or availability.",
                               "The 48-hour embargo follows next-calendar-day noon New York, not observed publication time."]}
    return usage, receipt


def context_definition(config: UsageContextConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    return {"contract": CONTRACT, "name": "lagged QB-usage-conditioned", "config": asdict(config),
            "states": ["STABLE", "MIXED", "UNKNOWN"],
            "opportunity": "qb_dropback=1 AND play_type in {pass,run} AND two_point_attempt=0",
            "actor": "passer_player_id, otherwise rusher_player_id only when qb_scramble=1; unresolved retained separately",
            "shareDenominator": "attributed dropbacks across selected eligible prior games",
            "stable": "latest two prior leaders equal AND pooled dominant share >= stable_dominant_share",
            "unknown": "fewer minimum_prior_games, any selected game below dropback minimum, or any attribution fraction below minimum",
            "contextKey": "home_context|away_context; home/away orientation retained",
            "cutoff": "minimum target forecast_cutoff_utc within season/week; default midnight New York on first date of season/week",
            "availability": "strict prior reconstructed available_utc < slate cutoff; exclude target ID; same season only",
            "targetStarterKnown": False, "currentAvailabilityUsed": False}


def _side_context(history: pd.DataFrame, config: UsageContextConfig) -> tuple[str, dict[str, Any]]:
    history = history.sort_values(["game_date", "canonical_game_id"], kind="stable").tail(config.lookback_games)
    counts: Counter[str] = Counter()
    for value in history["actor_counts_json"]:
        counts.update(json.loads(value))
    attributed = sum(counts.values())
    dominant = min(counts, key=lambda key: (-counts[key], key)) if counts else None
    share = counts[dominant] / attributed if dominant is not None else None
    leaders = history["leader_id"].tolist()
    change = leaders[-1] != leaders[-2] if len(leaders) >= 2 else None
    reasons = []
    if len(history) < config.minimum_prior_games:
        reasons.append("INSUFFICIENT_PRIOR_GAMES")
    if not history.empty and history["dropbacks"].lt(config.minimum_dropbacks_per_game).any():
        reasons.append("INSUFFICIENT_DROPBACKS")
    if not history.empty and history["attribution_fraction"].fillna(0).lt(config.minimum_attribution_fraction).any():
        reasons.append("INSUFFICIENT_ACTOR_ATTRIBUTION")
    state = "UNKNOWN" if reasons else "STABLE" if not change and share >= config.stable_dominant_share else "MIXED"
    details = {"state": state, "unknownReasons": reasons, "priorGameCount": len(history),
               "priorGameIds": history["canonical_game_id"].tolist(),
               "priorAvailableUtc": [value.isoformat() for value in history["available_utc"]],
               "priorDropbacks": history["dropbacks"].astype(int).tolist(),
               "priorAttributedDropbacks": history["attributed_dropbacks"].astype(int).tolist(),
               "attributedDropbacks": attributed, "actorCounts": dict(sorted(counts.items())),
               "dominantActorId": dominant, "dominantShare": share,
               "concentration": sum((count / attributed) ** 2 for count in counts.values()) if attributed else None,
               "latestLeaderChanged": change, "latestPriorLeaderId": leaders[-1] if leaders else None,
               "targetStarterKnown": False, "currentAvailabilityUsed": False}
    return state, details


def build_lagged_contexts(target_games: pd.DataFrame, usage: pd.DataFrame,
                          *, config: UsageContextConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """Return one oriented context per target, without consulting target usage.

    Callers may pass only identity metadata for target games. Extra target
    fields are ignored. Same-week observations cannot enter later week games.
    """
    required = {"canonical_game_id", "game_date", "season", "week",
                "canonical_home_team_id", "canonical_away_team_id"}
    if not required.issubset(target_games.columns):
        raise ValueError("target game identity metadata is incomplete")
    targets = target_games[list(required) + (["forecast_cutoff_utc"] if "forecast_cutoff_utc" in target_games else [])].copy()
    if targets["canonical_game_id"].duplicated().any():
        raise ValueError("duplicate target identity")
    targets["game_date"] = pd.to_datetime(targets["game_date"]).dt.tz_localize(None).dt.normalize()
    if "forecast_cutoff_utc" in targets:
        targets["forecast_cutoff_utc"] = pd.to_datetime(targets["forecast_cutoff_utc"], utc=True)
    else:
        targets["forecast_cutoff_utc"] = targets["game_date"].dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    targets["slate_cutoff_utc"] = targets.groupby(["season", "week"], dropna=False)["forecast_cutoff_utc"].transform("min")
    history = usage.copy()
    history["available_utc"] = pd.to_datetime(history["available_utc"], utc=True)
    history["game_date"] = pd.to_datetime(history["game_date"]).dt.tz_localize(None).dt.normalize()
    if history.duplicated(["canonical_game_id", "team_id"]).any():
        raise ValueError("duplicate team-game usage identity")
    by_team = {str(team): frame for team, frame in history.groupby("team_id", sort=False)}
    rows = []
    for target in targets.to_dict("records"):
        row = {"canonical_game_id": str(target["canonical_game_id"]),
               "forecast_cutoff_utc": target["forecast_cutoff_utc"],
               "slate_cutoff_utc": target["slate_cutoff_utc"],
               "evidence_class": EVIDENCE_CLASS, "target_starter_known": False}
        for side in ("home", "away"):
            team = _team(target[f"canonical_{side}_team_id"])
            prior = by_team.get(team, history.iloc[:0])
            prior = prior.loc[prior["available_utc"].lt(target["slate_cutoff_utc"])
                              & prior["canonical_game_id"].ne(str(target["canonical_game_id"]))
                              & prior["season"].eq(int(target["season"]))
                              & prior["game_date"].lt(target["game_date"])]
            state, detail = _side_context(prior, config)
            row[f"{side}_context"] = state
            row[f"{side}_details_json"] = json.dumps(detail, sort_keys=True)
        row["qb_context_group"] = row["home_context"] + "|" + row["away_context"]
        rows.append(row)
    return pd.DataFrame(rows)

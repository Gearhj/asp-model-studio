"""Retrospectively reconstructed NFL sufficient statistics and cold-start states.

This is NOT an archive of historical publication vintages. The user-authorized
48/72-hour reconstruction embargo follows a conservative completion upper bound
(the next calendar day's noon in New York). Finalized-source corrections can
remain. Only physically separated 1999--2024 PBP files are opened.
"""
from __future__ import annotations

import hashlib
import inspect
from collections import OrderedDict
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.sports_nfl.gold import ROLLING_METRICS

EVIDENCE_CLASS = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
OBSERVED_CLASS = "OBSERVED_AS_OF"
SEASONS = tuple(range(1999, 2025))
TEAM_ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LAR", "LA": "LAR"}
FORMER_MEDIAN_FIELDS = tuple(f"{side}_{metric}_season_to_date" for side in ("home", "away") for metric in ROLLING_METRICS)
RATE_METRICS = frozenset(metric for metric in ROLLING_METRICS if metric.endswith("_rate"))
_TREATMENT_SLATE_CACHE: OrderedDict = OrderedDict()
_TREATMENT_SLATE_CACHE_LIMIT = 2048


def clear_treatment_cache() -> None:
    _TREATMENT_SLATE_CACHE.clear()


MIRRORS = {"defensive_epa_per_play": "offensive_epa_per_play", "defensive_pass_epa_per_play": "pass_epa_per_play",
           "defensive_rush_epa_per_play": "rush_epa_per_play", "defensive_success_rate": "success_rate",
           "defensive_explosive_pass_allowed_rate": "explosive_pass_rate",
           "defensive_explosive_rush_allowed_rate": "explosive_rush_rate"}
RAW_COLUMNS = ("season game_id game_date week season_type home_team away_team home_score away_score "
               "posteam defteam play_type play_id order_sequence game_seconds_remaining epa success yards_gained "
               "down third_down_converted fourth_down_converted yardline_100 touchdown interception fumble_lost "
               "qb_dropback sack penalty passer_player_id").split()
METRIC_DEFINITIONS = {
    "points_for": ("final points including overtime", "completed team games"),
    "points_against": ("opponent final points including overtime", "completed team games"),
    "offensive_epa_per_play": ("sum observed EPA on pass/run plays", "pass/run plays with observed EPA"),
    "pass_epa_per_play": ("sum observed pass-play EPA", "pass plays with observed EPA"),
    "rush_epa_per_play": ("sum observed run-play EPA", "run plays with observed EPA"),
    "success_rate": ("sum observed source success on pass/run plays", "pass/run plays with observed success"),
    "explosive_pass_rate": ("pass plays gaining at least 20 yards", "pass plays with observed yards"),
    "explosive_rush_rate": ("run plays gaining at least 10 yards", "run plays with observed yards"),
    "early_down_success_rate": ("source success on first/second-down pass/run plays", "first/second-down pass/run plays with observed success"),
    "third_down_conversion_rate": ("sum observed third_down_converted", "third-down plays with observed conversion flag"),
    "fourth_down_conversion_rate": ("sum observed fourth_down_converted", "fourth-down plays with observed conversion flag"),
    "red_zone_td_play_rate": ("touchdowns on pass/run plays starting within 20 yards", "such red-zone plays with observed touchdown flag"),
    "turnover_rate": ("plays with interception or lost fumble", "possession plays with both turnover flags observed"),
    "sack_rate": ("observed sacks on quarterback dropbacks", "dropbacks with observed sack flag"),
    "penalty_rate": ("sum observed penalty flag", "possession plays with observed penalty flag"),
    "seconds_per_play": ("sum consecutive-row elapsed game clock on pass/run plays in [0,120] seconds", "pass/run plays with supported observed elapsed clock"),
}
for _defensive, _offensive in MIRRORS.items():
    METRIC_DEFINITIONS[_defensive] = ("opponent " + METRIC_DEFINITIONS[_offensive][0], METRIC_DEFINITIONS[_offensive][1])


def treatment_inventory() -> list[dict[str, Any]]:
    """Exact 44 registered season-to-date fields; no renamed median branch."""
    return [{"feature": f"{side}_{metric}_season_to_date", "metric": metric,
             "definition": METRIC_DEFINITIONS[metric][0], "exposureDenominator": METRIC_DEFINITIONS[metric][1],
             "evidenceClass": EVIDENCE_CLASS, "eligibilityClass": "A_RECONSTRUCTABLE_WITH_B_SEASON_START_PRIOR",
             "unit": ("probability" if metric in RATE_METRICS else "seconds per eligible play" if metric == "seconds_per_play"
                      else "EPA points per eligible play" if "epa_per_play" in metric else "points per completed game"),
             "entityGrain": "team-game historical sufficient statistics to pre-slate team/unit state",
             "knownZero": "Observed numerator zero with positive exposure is evidence, not missingness.",
             "structuralNotApplicable": "Zero opportunities contribute zero exposure, never a pseudo-observation.",
             "unavailableCurrentSeason": "Eligible multi-season team/unit evidence regressed to empirical league; widened uncertainty.",
             "staleTreatment": "Fold-selected offseason retention times game-recency weights; missing seasons recorded separately.",
             "priorHierarchy": "eligible league -> opponent-adjusted team/unit; prior usage-weighted QB layer is separate",
             "updateRule": "strict available_at < first forecast cutoff of season/week; whole slate atomic",
             "missingnessIndicator": f"{side}_{metric}_season_to_date__source_unknown",
             "uncertainty": "exposure-dependent posterior standard deviation plus separate missing-season count",
             "exclusionRule": "Native unavailable when no eligible empirical league/team evidence exists; no generic fallback.",
             "leakageRisk": "Finalized historical corrections remain; no target-game starters/rosters/injuries/weather used.",
             "implementationStatus": "IMPLEMENTED_RECONSTRUCTED", "genericMedianOrModeFallback": False}
            for side in ("home", "away") for metric in ROLLING_METRICS]


def _record(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(payload).hexdigest(), "byteCount": len(payload)}


def _team(value: Any) -> str:
    return TEAM_ALIASES.get(str(value), str(value))


def completion_upper_bound(game_date: Any) -> pd.Timestamp:
    return (pd.Timestamp(game_date).normalize() + pd.Timedelta(days=1, hours=12)).tz_localize("America/New_York").tz_convert("UTC")


def _attach_timing(games: pd.DataFrame) -> pd.DataFrame:
    games = games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"]).dt.tz_localize(None).dt.normalize()
    if "forecast_cutoff_utc" not in games:
        games["forecast_cutoff_utc"] = games["game_date"].dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    else:
        games["forecast_cutoff_utc"] = pd.to_datetime(games["forecast_cutoff_utc"], utc=True)
    games["slate_cutoff_utc"] = games.groupby(["season", "week"], dropna=False)["forecast_cutoff_utc"].transform("min")
    if "completion_upper_bound_utc" not in games:
        games["completion_upper_bound_utc"] = games["game_date"].map(completion_upper_bound)
    games["completion_upper_bound_utc"] = pd.to_datetime(games["completion_upper_bound_utc"], utc=True)
    for lag in (48, 72):
        games[f"available_{lag}h_utc"] = games["completion_upper_bound_utc"] + pd.Timedelta(hours=lag)
    games["availability_method"] = "RECONSTRUCTED_NEXT_DAY_NOON_NEW_YORK_COMPLETION_UPPER_BOUND_PLUS_LAG_NOT_PUBLICATION_TIME"
    games["evidence_class"] = EVIDENCE_CLASS
    return games


def _stats(values: pd.Series) -> tuple[float, float, float]:
    observed = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    observed = observed[np.isfinite(observed)]
    return float(observed.sum()), float(len(observed)), float(np.dot(observed, observed))


def aggregate_pbp_partition(frame: pd.DataFrame, *, expected_season: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Canonical metric predicates, with actual known-value exposures retained.

    Unlike generic null-to-zero treatment, missing historical event flags do not
    add opportunities. Rate predicates otherwise follow sports_nfl/canonical.py.
    """
    if expected_season not in SEASONS or not frame["season"].eq(expected_season).all():
        raise ValueError("only physically separated Development1999--2024 is permitted")
    frame = frame.loc[frame["season_type"].isin(["REG", "POST", "WC", "DIV", "CON", "SB"])].copy()
    order = "order_sequence" if "order_sequence" in frame else "play_id"
    frame = frame.sort_values(["game_id", order, "play_id"], kind="stable")
    frame["elapsed_seconds"] = frame["game_seconds_remaining"] - frame.groupby("game_id")["game_seconds_remaining"].shift(-1)
    games, team_rows, qb_rows = [], [], []
    for game_id, group in frame.groupby("game_id", sort=False):
        first = group.iloc[0]
        score_columns = [pd.to_numeric(group[key], errors="coerce").dropna().unique() for key in ("home_score", "away_score")]
        if any(len(values) != 1 for values in score_columns):
            raise ValueError(f"missing or ambiguous final score truth for {game_id}")
        home, away = _team(first["home_team"]), _team(first["away_team"])
        game = {"canonical_game_id": str(game_id), "game_date": pd.Timestamp(first["game_date"]),
                "season": expected_season, "week": int(first["week"]), "game_type": str(first["season_type"]),
                "canonical_home_team_id": home, "canonical_away_team_id": away,
                "home_points": float(score_columns[0][0]), "away_points": float(score_columns[1][0]),
                "evidence_class": EVIDENCE_CLASS}
        games.append(game)
        offense_stats = {}
        for team_id, own in group.loc[group["posteam"].notna()].groupby("posteam", sort=False):
            team_id = _team(team_id)
            scrimmage, passing, rushing = own["play_type"].isin(["pass", "run"]), own["play_type"].eq("pass"), own["play_type"].eq("run")
            metrics = {"offensive_epa_per_play": _stats(own.loc[scrimmage, "epa"]),
                       "pass_epa_per_play": _stats(own.loc[passing, "epa"]),
                       "rush_epa_per_play": _stats(own.loc[rushing, "epa"]),
                       "success_rate": _stats(own.loc[scrimmage, "success"]),
                       "explosive_pass_rate": _stats(own.loc[passing & own["yards_gained"].notna(), "yards_gained"].ge(20)),
                       "explosive_rush_rate": _stats(own.loc[rushing & own["yards_gained"].notna(), "yards_gained"].ge(10)),
                       "early_down_success_rate": _stats(own.loc[scrimmage & own["down"].isin([1, 2]), "success"]),
                       "third_down_conversion_rate": _stats(own.loc[own["down"].eq(3), "third_down_converted"]),
                       "fourth_down_conversion_rate": _stats(own.loc[own["down"].eq(4), "fourth_down_converted"]),
                       "red_zone_td_play_rate": _stats(own.loc[scrimmage & own["yardline_100"].le(20), "touchdown"]),
                       "turnover_rate": _stats(own.loc[own["interception"].notna() & own["fumble_lost"].notna(), ["interception", "fumble_lost"]].max(axis=1)),
                       "sack_rate": _stats(own.loc[own["qb_dropback"].eq(1), "sack"]),
                       "penalty_rate": _stats(own["penalty"]),
                       "seconds_per_play": _stats(own.loc[scrimmage & own["elapsed_seconds"].between(0, 120), "elapsed_seconds"])}
            offense_stats[team_id] = metrics
            for player_id, passer in own.loc[passing & own["passer_player_id"].notna() & own["epa"].notna()].groupby("passer_player_id", sort=False):
                total, n, sumsq = _stats(passer["epa"])
                qb_rows.append({**{key: game[key] for key in ("canonical_game_id", "game_date", "season", "week", "evidence_class")},
                                "team_id": team_id, "player_id": str(player_id), "attempts": n, "epa_sum": total, "epa_sumsq": sumsq})
        full_stats = {}
        for team_id, opponent, score, allowed in ((home, away, game["home_points"], game["away_points"]), (away, home, game["away_points"], game["home_points"])):
            if team_id not in offense_stats or opponent not in offense_stats:
                raise ValueError(f"incomplete team play evidence for {game_id}")
            full_stats[team_id] = {**offense_stats[team_id], "points_for": (score, 1., score * score), "points_against": (allowed, 1., allowed * allowed),
                                   **{defensive: offense_stats[opponent][offensive] for defensive, offensive in MIRRORS.items()}}
        for team_id, opponent in ((home, away), (away, home)):
            for metric in ROLLING_METRICS:
                numerator, denominator, sumsq = full_stats[team_id][metric]
                other_numerator, other_denominator, other_sumsq = full_stats[opponent][metric]
                team_rows.append({**{key: game[key] for key in ("canonical_game_id", "game_date", "season", "week", "evidence_class")},
                                  "team_id": team_id, "opponent_team_id": opponent, "is_home": team_id == home, "metric": metric,
                                  "numerator": numerator, "denominator": denominator, "sumsq": sumsq,
                                  "allowed_numerator": other_numerator, "allowed_denominator": other_denominator, "allowed_sumsq": other_sumsq,
                                  "source_unknown": denominator == 0, "value": numerator / denominator if denominator else np.nan})
    return pd.DataFrame(games), pd.DataFrame(team_rows), pd.DataFrame(qb_rows)


def load_reconstructed_history(bronze_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    root = Path(bronze_root).resolve()
    pointer = json.loads((root / "current.json").read_bytes())
    manifest_path = (root / pointer["manifestRelativePath"]).resolve()
    if not manifest_path.is_relative_to(root):
        raise ValueError("manifest escapes Bronze root")
    manifest_ref = _record(manifest_path)
    if manifest_ref["sha256"] != pointer["manifestSha256"]:
        raise ValueError("Bronze manifest checksum differs")
    manifest = json.loads(manifest_path.read_bytes())
    partitions = [p for p in manifest["partitions"] if p["familyId"] == "play_by_play" and p.get("season") in SEASONS]
    if len(partitions) != len(SEASONS) or {p["season"] for p in partitions} != set(SEASONS):
        raise ValueError("expected26 separated Development PBP seasons1999--2024")
    game_frames, team_frames, qb_frames, sources = [], [], [], []
    raw_count = 0
    for partition in sorted(partitions, key=lambda item: item["season"]):
        path = (root / partition["relativePath"]).resolve()
        if not path.is_relative_to(root) or f"season={partition['season']}" not in path.parts:
            raise ValueError("source is not physically season-separated")
        source = _record(path)
        if source["sha256"] != partition["fileSha256"]:
            raise ValueError("historical source checksum differs")
        sources.append({**source, **{key: partition[key] for key in ("season", "license", "retrievedAt", "assetUpdatedAt", "releasePublishedAt")},
                        "evidenceClass": EVIDENCE_CLASS})
        parquet = pq.ParquetFile(path)
        available = set(parquet.schema_arrow.names)
        required = set(RAW_COLUMNS) - {"order_sequence"}
        if not required.issubset(available):
            raise ValueError(f"missing required historical PBP columns: {sorted(required - available)}")
        frame = parquet.read(columns=[column for column in RAW_COLUMNS if column in available]).to_pandas()
        raw_count += len(frame)
        games, team, qb = aggregate_pbp_partition(frame, expected_season=partition["season"])
        game_frames.append(games); team_frames.append(team); qb_frames.append(qb)
    games = _attach_timing(pd.concat(game_frames, ignore_index=True)).sort_values(["game_date", "canonical_game_id"]).reset_index(drop=True)
    team = pd.concat(team_frames, ignore_index=True)
    qb = pd.concat(qb_frames, ignore_index=True)
    timing = games[["canonical_game_id", "forecast_cutoff_utc", "slate_cutoff_utc", "completion_upper_bound_utc", "available_48h_utc", "available_72h_utc", "availability_method"]]
    team = team.merge(timing, on="canonical_game_id", validate="many_to_one")
    qb = qb.merge(timing, on="canonical_game_id", validate="many_to_one")
    receipt = {"schemaVersion": "NFL_RECONSTRUCTED_CURRENT_STATE_COHORT_V2", "evidenceClass": EVIDENCE_CLASS,
               "sources": sources, "registeredManifest": manifest_ref, "seasonsRead": list(SEASONS), "sealedOotRead": False,
               "rawPlayRows": raw_count, "gameCount": len(games), "teamMetricRows": len(team), "qbGameRows": len(qb),
               "gameCountsBySeason": {str(key): int(value) for key, value in games.groupby("season").size().items()},
               "treatmentInventory": treatment_inventory(), "genericMedianOrModeFallbackCount": 0,
               "completionMethod": "NEXT_CALENDAR_DAY_NOON_AMERICA_NEW_YORK_UPPER_BOUND_NOT_OBSERVED_GAME_COMPLETION",
               "forecastCutoffMethod": "MIDNIGHT_NEW_YORK_FIRST_DATE_OF_SEASON_WEEK; CONSERVATIVE_BEFORE_KICKOFF",
               "lagsHours": [48, 72], "lateCorrectionLineageAvailable": False,
               "limitations": ["Retrospective finalized records, not archived historical publication vintages; late corrections can remain.",
                   "No target-game starter, roster, participation, injury, coaching-change, venue/weather, or market inputs.",
                   "Conservative completion upper bound and whole-week atomicity can omit genuinely available recent games.",
                   "Rates use observed opportunity denominators; source-unknown flags do not become invented zero events.",
                   "Declared canonical-definition correction: turnover_rate requires both interception/fumble_lost flags observed rather than coalescing missing flags to zero; all other event rates similarly count only observed labels.",
                   "Historical PBP EPA is the provider-derived historical label, not a newly trained fold-local EPA estimator."]}
    return games, team, qb, receipt


def load_reconstructed_sources(bronze_root: Path, cache_root: Path | None = None):
    """Optional immutable cache, bound to exact source manifest and this code.

    The cache contains only the reconstructed Development aggregates. It never
    loads a mixed-season foundation or inspects a sealed2025 PBP payload.
    """
    if cache_root is None:
        return load_reconstructed_history(bronze_root)
    bronze_root = Path(bronze_root).resolve()
    pointer = json.loads((bronze_root / "current.json").read_bytes())
    extraction_sources = "\n".join(inspect.getsource(function) for function in (
        aggregate_pbp_partition, load_reconstructed_history, _attach_timing, completion_upper_bound, _stats, _team, treatment_inventory))
    extraction_sources += json.dumps({"columns": RAW_COLUMNS, "metrics": list(ROLLING_METRICS), "definitions": METRIC_DEFINITIONS,
                                      "aliases": TEAM_ALIASES, "mirrors": MIRRORS}, sort_keys=True)
    identity = {"bronzeManifestSha256": pointer["manifestSha256"], "extractorSha256": hashlib.sha256(extraction_sources.encode()).hexdigest(),
                "evidenceClass": EVIDENCE_CLASS, "seasons": list(SEASONS)}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = Path(cache_root).resolve() / key
    manifest_path = directory / "cache-manifest.json"
    if manifest_path.exists():
        cache = json.loads(manifest_path.read_bytes())
        if cache["identity"] != identity:
            raise ValueError("cached reconstruction identity differs")
        frames = []
        for name in ("games", "team", "qb"):
            path = Path(cache["objects"][name]["path"]).resolve()
            if not path.is_relative_to(Path(cache_root).resolve()):
                raise ValueError("cached aggregate escapes cache root")
            reference = _record(path)
            if reference["sha256"] != cache["objects"][name]["sha256"] or reference["byteCount"] != cache["objects"][name]["byteCount"]:
                raise ValueError("cached reconstruction checksum differs")
            frames.append(pd.read_parquet(path))
        return *frames, cache["receipt"]
    # This one verified prior implementation has IDENTICAL extraction functions;
    # only treatment-state batching changed. Preserve its objects and append an
    # explicit equivalence receipt, rather than mislabeling old code as new code.
    legacy_sha = "e5059c705a55b32448529581d653fd910ef986ca29ef0a161b15e98b7a33a5c4"
    for old_manifest in Path(cache_root).resolve().glob("*/cache-manifest.json"):
        old = json.loads(old_manifest.read_bytes())
        old_identity = old.get("identity", {})
        if old_identity.get("implementationSha256") != legacy_sha or any(old_identity.get(key) != identity[key] for key in ("bronzeManifestSha256", "evidenceClass", "seasons")):
            continue
        registered_path = bronze_root / pointer["manifestRelativePath"]
        if _record(registered_path)["sha256"] != pointer["manifestSha256"]:
            raise ValueError("registered manifest checksum differs")
        registered = json.loads(registered_path.read_bytes())
        expected = {int(partition["season"]): partition["fileSha256"] for partition in registered["partitions"]
                    if partition["familyId"] == "play_by_play" and partition.get("season") in SEASONS}
        actual = {int(source["season"]): source["sha256"] for source in old["receipt"]["sources"]}
        if expected != actual or set(actual) != set(SEASONS):
            raise ValueError("legacy cache source receipts do not match separated Development sources")
        frames = []
        for name in ("games", "team", "qb"):
            path = Path(old["objects"][name]["path"]).resolve()
            if not path.is_relative_to(Path(cache_root).resolve()):
                raise ValueError("legacy aggregate escapes cache root")
            ref = _record(path)
            if any(ref[key] != old["objects"][name][key] for key in ("sha256", "byteCount")):
                raise ValueError("legacy cached aggregate checksum differs")
            frame = pd.read_parquet(path)
            if not frame["season"].isin(SEASONS).all():
                raise ValueError("legacy aggregate contains a non-Development season")
            frames.append(frame)
        directory.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump({"identity": identity, "objects": old["objects"], "receipt": old["receipt"],
                       "currentImplementationSha256": _record(Path(__file__))["sha256"],
                       "equivalentExtractionReuse": {"priorCacheManifest": _record(old_manifest),
                           "priorImplementationSha256": legacy_sha, "claim": "EXTRACTION_FUNCTIONS_UNCHANGED; TREATMENT_BATCHING_ONLY; EXACT_SOURCE_AND_AGGREGATE_HASHES_VERIFIED"}}, stream, sort_keys=True)
        return *frames, old["receipt"]
    games, team, qb, receipt = load_reconstructed_history(bronze_root)
    directory.mkdir(parents=True, exist_ok=True)
    references = {}
    for name, frame in (("games", games), ("team", team), ("qb", qb)):
        path = directory / f"{name}.parquet"
        if path.exists():
            raise ValueError("incomplete immutable cache must not be overwritten")
        frame.to_parquet(path, index=False)
        references[name] = _record(path)
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump({"identity": identity, "objects": references, "receipt": receipt,
                   "currentImplementationSha256": _record(Path(__file__))["sha256"]}, stream, sort_keys=True)
    return games, team, qb, receipt


def _validate_lag(lag_hours: int) -> None:
    if lag_hours not in (48, 72):
        raise ValueError("only preregistered48h/72h reconstruction lags permitted")


def _available(frame: pd.DataFrame, lag_hours: int) -> pd.Series:
    column = f"available_{lag_hours}h_utc"
    if column in frame:
        return pd.to_datetime(frame[column], utc=True)
    if "completion_upper_bound_utc" in frame:
        return pd.to_datetime(frame["completion_upper_bound_utc"], utc=True) + pd.Timedelta(hours=lag_hours)
    return pd.to_datetime(frame["game_date"].map(completion_upper_bound), utc=True) + pd.Timedelta(hours=lag_hours)


def fit_league_prior(train_games: pd.DataFrame, team: pd.DataFrame, qb: pd.DataFrame, *, lag_hours: int = 48) -> dict[str, Any]:
    """Fold-local pooling parameters only; caller owns all model fitting choices."""
    _validate_lag(lag_hours)
    if train_games.empty or not train_games["season"].isin(SEASONS).all():
        raise ValueError("nonempty Development training IDs required")
    ids = set(train_games["canonical_game_id"].astype(str))
    selected = team.loc[team["canonical_game_id"].astype(str).isin(ids)]
    means, variances, prior_exposure = {}, {}, {}
    for metric, group in selected.groupby("metric"):
        n, total, sq = group["denominator"].sum(), group["numerator"].sum(), group["sumsq"].sum()
        means[metric] = float(total / n) if n else None
        variances[metric] = max(float(sq / n - (total / n) ** 2), 1e-8) if n else None
        prior_exposure[metric] = float(4 * n / max(1, len(group)))
    q = qb.loc[qb["canonical_game_id"].astype(str).isin(ids)]
    n, total, sq = q["attempts"].sum(), q["epa_sum"].sum(), q["epa_sumsq"].sum()
    return {"means": means, "variances": variances, "prior_exposure": prior_exposure,
            "qb_mean": float(total / n) if n else None, "qb_variance": max(float(sq / n - (total / n) ** 2), 1e-8) if n else None,
            "qb_prior_exposure": 100., "training_ids": sorted(ids), "training_cutoff": str(pd.to_datetime(train_games["game_date"]).max().date()),
            "parametersAvailableAfter": str(_available(selected, lag_hours).max()), "evidence_class": EVIDENCE_CLASS,
            "priorExposureMeaning": "four training-average games of actual metric opportunities; not a pseudo median"}


def qb_player_prior(qb: pd.DataFrame, player_id: str, *, cutoff_utc: Any, season: int, decay: float,
                    league_prior: dict[str, Any], lag_hours: int = 48) -> dict[str, Any]:
    """Historical ability prior for an independently sourced current role/scenario."""
    _validate_lag(lag_hours)
    if not qb["season"].isin(SEASONS).all():
        raise ValueError("non-Development QB history forbidden")
    eligible = qb.loc[_available(qb, lag_hours).lt(pd.Timestamp(cutoff_utc)) & qb["season"].le(season)]
    weights = decay ** (season - eligible["season"].to_numpy(float))
    total_n = float(np.dot(weights, eligible["attempts"]))
    center = float(np.dot(weights, eligible["epa_sum"])) / total_n if total_n else np.nan
    player = eligible.loc[eligible["player_id"].eq(player_id)]
    weights = decay ** (season - player["season"].to_numpy(float))
    n, total = float(np.dot(weights, player["attempts"])), float(np.dot(weights, player["epa_sum"]))
    strength = float(league_prior.get("qb_prior_exposure", 100.))
    variance = league_prior.get("qb_variance")
    return {"playerId": str(player_id), "mean": (total + strength * center) / (n + strength) if np.isfinite(center) else None,
            "effectiveExposure": n, "posteriorSd": float(np.sqrt(variance / (n + strength))) if variance is not None else None,
            "evidenceClass": EVIDENCE_CLASS, "roleStatus": "ROLE_REQUIRES_SEPARATE_OBSERVED_AS_OF_EVIDENCE",
            "unseenPlayerTreatment": "LEAGUE_PASSER_PRIOR_WITH_ZERO_PLAYER_EXPOSURE" if n == 0 else "PLAYER_TO_LEAGUE_PARTIAL_POOLING"}


def _safe_variance(prior: dict, metric: str, numerator: float, denominator: float, sumsq: float) -> float:
    value = prior.get("variances", {}).get(metric)
    if value is not None and np.isfinite(value) and value > 0:
        return float(value)
    return max(sumsq / denominator - (numerator / denominator) ** 2, 1e-8) if denominator > 0 else np.nan


def _batch_team_metrics(eligible: pd.DataFrame, prior: dict, season: int, opponent_adjustment: float):
    """Equivalent grouped reductions without hundreds of pandas subframes."""
    metrics = tuple(ROLLING_METRICS)
    m = len(metrics)
    team_code, teams = pd.factorize(eligible["team_id"], sort=False)
    metric_code = pd.Categorical(eligible["metric"], categories=metrics).codes.astype(np.int64)
    group_code = team_code * m + metric_code
    size = len(teams) * m
    w = eligible["_weight"].to_numpy(float)
    n = eligible["denominator"].to_numpy(float)
    numer = eligible["numerator"].to_numpy(float)
    sq = eligible["sumsq"].to_numpy(float)
    league_n = np.bincount(metric_code, weights=w*n, minlength=m)
    league_sum = np.bincount(metric_code, weights=w*numer, minlength=m)
    league_sq = np.bincount(metric_code, weights=w*sq, minlength=m)
    counts = np.bincount(metric_code, minlength=m)
    with np.errstate(invalid="ignore", divide="ignore"):
        centers = league_sum / league_n
    strengths = np.asarray([float(prior.get("prior_exposure", {}).get(metric, 4*league_n[j]/max(1, counts[j]))) for j, metric in enumerate(metrics)])
    variances = np.asarray([_safe_variance(prior, metric, league_sum[j], league_n[j], league_sq[j]) for j, metric in enumerate(metrics)])
    group_n = np.bincount(group_code, weights=w*n, minlength=size).reshape(-1, m)
    allowed_n = np.bincount(group_code, weights=w*eligible["allowed_denominator"].to_numpy(float), minlength=size).reshape(-1, m)
    allowed_sum = np.bincount(group_code, weights=w*eligible["allowed_numerator"].to_numpy(float), minlength=size).reshape(-1, m)
    with np.errstate(invalid="ignore", divide="ignore"):
        allowed = (allowed_sum + strengths*centers) / (allowed_n + strengths)
    team_map = {str(team): j for j, team in enumerate(teams)}
    opponent_codes = eligible["opponent_team_id"].map(team_map).fillna(-1).to_numpy(int)
    opponent_values = centers[metric_code].copy()
    known = opponent_codes >= 0
    opponent_values[known] = allowed[opponent_codes[known], metric_code[known]]
    adjusted = numer + n*opponent_adjustment*(centers[metric_code]-opponent_values)
    adjusted_sum = np.bincount(group_code, weights=w*adjusted, minlength=size).reshape(-1, m)
    current = eligible["season"].to_numpy(int) == int(season)
    current_n = np.bincount(group_code, weights=n*current, minlength=size).reshape(-1, m)
    with np.errstate(invalid="ignore", divide="ignore"):
        means = (adjusted_sum + strengths*centers) / (group_n + strengths)
        sds = np.sqrt(variances / (group_n + strengths))
        league_sds = np.sqrt(variances / strengths)
    rate_columns = np.asarray([metric in RATE_METRICS for metric in metrics])
    means[:, rate_columns] = np.clip(means[:, rate_columns], 0, 1)
    league_means = centers.copy(); league_means[rate_columns] = np.clip(league_means[rate_columns], 0, 1)
    states = {None: {metric: (league_means[j], 0., league_sds[j], 0.) for j, metric in enumerate(metrics)}}
    for i, team in enumerate(teams):
        states[str(team)] = {metric: (means[i, j], group_n[i, j], sds[i, j], current_n[i, j]) for j, metric in enumerate(metrics)}
    # Every team-game has one points_for row even when another metric is missing.
    game_rows = metric_code == 0
    game_counts = np.bincount(team_code[game_rows], minlength=len(teams))
    current_counts = np.bincount(team_code[game_rows & current], minlength=len(teams))
    latest = np.full(len(teams), -1, dtype=int)
    np.maximum.at(latest, team_code, eligible["season"].to_numpy(int))
    metadata = {str(team): (int(latest[i]), int(game_counts[i]), int(current_counts[i])) for i, team in enumerate(teams)}
    return states, metadata


def build_treatment_states(games: pd.DataFrame, team: pd.DataFrame, qb: pd.DataFrame, *, lag_hours: int = 48,
                           decay: float = .65, league_prior: dict[str, Any] | None = None,
                           half_life_games: float = 8., opponent_adjustment: float = 1., _vectorized: bool = True,
                           _memoize: bool = True) -> pd.DataFrame:
    """Exposure-pooled, opponent-adjusted priors at strict reconstructed cutoffs.

    Fold-fitted variances and pooling strengths are parameters, not observations.
    The empirical league center always uses only eligible events at that cutoff.
    Opponent adjustment is an association adjustment using prior allowed values;
    rate posteriors stay on [0,1] and are not claimed to be exact beta posteriors.
    """
    _validate_lag(lag_hours)
    if not 0 < decay <= 1 or half_life_games <= 0 or not 0 <= opponent_adjustment <= 1:
        raise ValueError("invalid declared prior/recency parameters")
    if not team["season"].isin(SEASONS).all() or (len(qb) and not qb["season"].isin(SEASONS).all()):
        raise ValueError("non-Development history is forbidden")
    prior = league_prior or {}
    targets = _attach_timing(games)
    targets["_input_order"] = np.arange(len(targets))
    targets = targets.sort_values(["slate_cutoff_utc", "canonical_game_id"])
    history_columns = ["game_date", "canonical_game_id", "season", "team_id", "opponent_team_id", "metric",
                       "numerator", "denominator", "sumsq", "allowed_numerator", "allowed_denominator"]
    history = team[history_columns].copy(); history["_available"] = _available(team, lag_hours)
    history = history.sort_values(["game_date", "canonical_game_id", "team_id", "metric"])
    passer_columns = ["game_date", "canonical_game_id", "season", "team_id", "player_id", "attempts", "epa_sum", "epa_sumsq"]
    passers = qb[passer_columns].copy(); passers["_available"] = _available(qb, lag_hours)
    ordered_q_games = passers[["game_date", "canonical_game_id"]].drop_duplicates().sort_values(["game_date", "canonical_game_id"])
    qb_game_rank = {game_id: i for i, game_id in enumerate(ordered_q_games["canonical_game_id"])}
    memoize = _memoize and _vectorized
    if memoize:
        fingerprint = hashlib.sha256(pd.util.hash_pandas_object(history, index=False).to_numpy().tobytes()
                                     + pd.util.hash_pandas_object(passers, index=False).to_numpy().tobytes()).hexdigest()
        used_prior = {name: prior.get(name) for name in ("variances", "prior_exposure", "qb_variance", "qb_prior_exposure")}
        prior_identity = hashlib.sha256(json.dumps(used_prior, sort_keys=True, default=str).encode()).hexdigest()
    records = []
    for (season, week, cutoff), slate in targets.groupby(["season", "week", "slate_cutoff_utc"], sort=True):
        cutoff = pd.Timestamp(cutoff)
        slate_records = slate.to_dict("records")
        if memoize:
            key = (fingerprint, prior_identity, lag_hours, decay, half_life_games, opponent_adjustment, int(season), int(week), str(cutoff),
                   tuple((row["canonical_game_id"], row["canonical_home_team_id"], row["canonical_away_team_id"]) for row in slate_records))
            if key in _TREATMENT_SLATE_CACHE:
                cached = _TREATMENT_SLATE_CACHE[key].to_dict("records")
                records.extend({**game, **features} for game, features in zip(slate_records, cached))
                _TREATMENT_SLATE_CACHE.move_to_end(key)
                continue
        slate_start = len(records)
        eligible = history.loc[history["_available"].lt(cutoff) & history["season"].le(season)
                               & ~history["canonical_game_id"].isin(slate["canonical_game_id"])]
        if int(week) == 1:
            eligible = eligible.loc[eligible["season"].lt(season)]
        eligible = eligible.copy()
        # Reverse within-team/metric game rank yields exposure-weighted recency,
        # rather than treating one-play and sixty-play game rates equally.
        ages = eligible.groupby(["team_id", "metric"]).cumcount(ascending=False).to_numpy(float)
        eligible["_weight"] = np.exp2(-ages / half_life_games) * decay ** (season - eligible["season"].to_numpy(float))
        if _vectorized:
            batch_states, batch_metadata = _batch_team_metrics(eligible, prior, int(season), opponent_adjustment)
        else:
            weighted, metric_row_counts = {}, {}
            for metric, group in eligible.groupby("metric"):
                metric_row_counts[metric] = len(group)
                w = group["_weight"].to_numpy(float)
                n = float(np.dot(w, group["denominator"]))
                total = float(np.dot(w, group["numerator"]))
                sq = float(np.dot(w, group["sumsq"]))
                weighted[metric] = (total, n, sq)
            team_groups = {(team_id, metric): group for (team_id, metric), group in eligible.groupby(["team_id", "metric"], sort=False)}
            whole_team_groups = {team_id: group for team_id, group in eligible.groupby("team_id", sort=False)}
            allowed = {}
            for (team_id, metric), group in team_groups.items():
                total, league_n, _ = weighted[metric]
                center = total / league_n if league_n else np.nan
                strength = float(prior.get("prior_exposure", {}).get(metric, 4 * league_n / max(1, metric_row_counts.get(metric, 0))))
                w = group["_weight"].to_numpy(float)
                n = float(np.dot(w, group["allowed_denominator"]))
                allowed[(team_id, metric)] = (float(np.dot(w, group["allowed_numerator"])) + strength * center) / (n + strength) if n + strength > 0 else center
        q_eligible = passers.loc[passers["_available"].lt(cutoff) & passers["season"].le(season)
                                  & ~passers["canonical_game_id"].isin(slate["canonical_game_id"])]
        if int(week) == 1:
            q_eligible = q_eligible.loc[q_eligible["season"].lt(season)]
        q_eligible = q_eligible.copy()
        q_eligible["_weight"] = decay ** (season - q_eligible["season"].to_numpy(float))
        q_n = float(np.dot(q_eligible["_weight"], q_eligible["attempts"]))
        q_total = float(np.dot(q_eligible["_weight"], q_eligible["epa_sum"]))
        q_center = q_total / q_n if q_n else np.nan
        q_variance = prior.get("qb_variance")
        if q_variance is None:
            q_variance = max(float(np.dot(q_eligible["_weight"], q_eligible["epa_sumsq"])) / q_n - q_center ** 2, 1e-8) if q_n else np.nan
        if _vectorized:
            qb_team_indices = q_eligible.groupby("team_id", sort=False).indices
            qb_player_indices = q_eligible.groupby("player_id", sort=False).indices
            qb_weights = q_eligible["_weight"].to_numpy(float)
            qb_attempts = q_eligible["attempts"].to_numpy(float)
            qb_sums = q_eligible["epa_sum"].to_numpy(float)
            qb_player_values = {}
        for game in slate_records:
            result = dict(game)
            result.update(evidence_class=EVIDENCE_CLASS, reconstructed_lag_hours=lag_hours,
                          generic_median_mode_fallback_count=0, eligible_history_max_available_at=str(eligible["_available"].max()) if len(eligible) else None)
            for side in ("home", "away"):
                team_id = game[f"canonical_{side}_team_id"]
                if _vectorized:
                    latest_season, prior_games, current_games = batch_metadata.get(team_id, (None, 0, 0))
                else:
                    own_all = whole_team_groups.get(team_id, eligible.iloc[:0])
                    latest_season = int(own_all["season"].max()) if len(own_all) else None
                    prior_games = int(own_all["canonical_game_id"].nunique())
                    current_games = int(own_all.loc[own_all["season"].eq(season), "canonical_game_id"].nunique())
                gap = int(season) - latest_season if latest_season is not None else int(season) - min(SEASONS)
                result[f"{side}_prior_season_gap"] = gap
                result[f"{side}_missing_season_uncertainty"] = max(0, gap - 1)
                result[f"{side}_prior_games"] = prior_games
                result[f"{side}_current_games"] = current_games
                for metric in ROLLING_METRICS:
                    name = f"{side}_{metric}_season_to_date"
                    if _vectorized:
                        mean, n, sd, current_n = batch_states.get(team_id, batch_states[None])[metric]
                        result.update({name: mean, name + "__effective_exposure": n, name + "__posterior_sd": sd,
                                       name + "__current_exposure": current_n, name + "__source_unknown": not np.isfinite(mean)})
                        continue
                    total, league_n, sq = weighted.get(metric, (0., 0., 0.))
                    center = total / league_n if league_n else np.nan
                    strength = float(prior.get("prior_exposure", {}).get(metric, 4 * league_n / max(1, metric_row_counts.get(metric, 0))))
                    own = team_groups.get((team_id, metric))
                    n, adjusted_total, current_n = 0., 0., 0.
                    if own is not None:
                        w = own["_weight"].to_numpy(float)
                        n = float(np.dot(w, own["denominator"]))
                        opponents = np.asarray([allowed.get((opponent, metric), center) for opponent in own["opponent_team_id"]], float)
                        adjustment = opponent_adjustment * (center - opponents)
                        adjusted_total = float(np.dot(w, own["numerator"].to_numpy(float) + own["denominator"].to_numpy(float) * adjustment))
                        current_n = float(own.loc[own["season"].eq(season), "denominator"].sum())
                    mean = (adjusted_total + strength * center) / (n + strength) if n + strength > 0 and np.isfinite(center) else np.nan
                    if metric in RATE_METRICS and np.isfinite(mean):
                        mean = float(np.clip(mean, 0, 1))
                    variance = _safe_variance(prior, metric, total, league_n, sq)
                    result[name] = mean
                    result[name + "__effective_exposure"] = n
                    result[name + "__posterior_sd"] = float(np.sqrt(variance / (n + strength))) if n + strength > 0 else np.nan
                    result[name + "__current_exposure"] = current_n
                    result[name + "__source_unknown"] = not np.isfinite(mean)
                usage = q_eligible.iloc[qb_team_indices.get(team_id, [])] if _vectorized else q_eligible.loc[q_eligible["team_id"].eq(team_id)]
                recent_games = (sorted(usage["canonical_game_id"].unique(), key=qb_game_rank.__getitem__)[-4:] if _vectorized
                                else list(usage.sort_values(["game_date", "canonical_game_id"])["canonical_game_id"].drop_duplicates())[-4:])
                usage = usage.loc[usage["canonical_game_id"].isin(recent_games)]
                mixture = []
                for player_id, player_usage in usage.groupby("player_id", sort=True):
                    if _vectorized:
                        if player_id not in qb_player_values:
                            indices = qb_player_indices[player_id]
                            qb_player_values[player_id] = (float(np.dot(qb_weights[indices], qb_attempts[indices])),
                                                           float(np.dot(qb_weights[indices], qb_sums[indices])))
                        n, total = qb_player_values[player_id]
                    else:
                        player = q_eligible.loc[q_eligible["player_id"].eq(player_id)]
                        n = float(np.dot(player["_weight"], player["attempts"]))
                        total = float(np.dot(player["_weight"], player["epa_sum"]))
                    strength = float(prior.get("qb_prior_exposure", 100.))
                    mean = (total + strength * q_center) / (n + strength) if np.isfinite(q_center) else np.nan
                    weight = float(np.dot(player_usage["_weight"], player_usage["attempts"]))
                    mixture.append({"playerId": str(player_id), "weight": weight, "mean": mean, "exposure": n,
                                    "variance": float(q_variance) / (n + strength), "evidenceClass": EVIDENCE_CLASS,
                                    "roleMeaning": "PRIOR_TEAM_USAGE_NOT_TARGET_STARTER"})
                mass = sum(item["weight"] for item in mixture)
                mean = sum(item["weight"] * item["mean"] for item in mixture) / mass if mass else q_center
                variance = sum(item["weight"] * (item["variance"] + (item["mean"] - mean) ** 2) for item in mixture) / mass if mass else q_variance
                result[f"{side}_qb_epa_mean"] = mean
                result[f"{side}_qb_posterior_sd"] = float(np.sqrt(variance)) if variance is not None and np.isfinite(variance) else np.nan
                result[f"{side}_qb_effective_exposure"] = sum(item["weight"] * item["exposure"] for item in mixture) / mass if mass else 0.
                result[f"{side}_qb_mixture"] = json.dumps(mixture, sort_keys=True)
            result["no_current_history"] = result["home_current_games"] == result["away_current_games"] == 0
            result["low_qb_exposure"] = min(result["home_qb_effective_exposure"], result["away_qb_effective_exposure"]) < 100
            records.append(result)
        if memoize:
            # Cache only derived features; caller targets/identity/order are
            # always reconstructed from the current request, never cached truth.
            base_columns = set(slate.columns)
            cached_features = [{name: value for name, value in row.items() if name not in base_columns} for row in records[slate_start:]]
            _TREATMENT_SLATE_CACHE[key] = pd.DataFrame(cached_features)
            _TREATMENT_SLATE_CACHE.move_to_end(key)
            while len(_TREATMENT_SLATE_CACHE) > _TREATMENT_SLATE_CACHE_LIMIT:
                _TREATMENT_SLATE_CACHE.popitem(last=False)
    result = pd.DataFrame(records).sort_values("_input_order").drop(columns="_input_order").reset_index(drop=True)
    result.attrs["featureEvidenceClass"] = {name: EVIDENCE_CLASS for name in result if name.startswith(("home_", "away_"))}
    result.attrs["treatmentInventory"] = treatment_inventory()
    result.attrs["missingSeasonUncertaintyUnit"] = "COUNT_OF_UNOBSERVED_INTERVENING_SEASONS_NOT_SCORE_SD"
    return result

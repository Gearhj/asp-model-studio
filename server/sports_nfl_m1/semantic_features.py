"""Date-atomic football priors; no median and no target-game starter inference.

The registered rolling rates are means of game-level rates, not binomial
sufficient statistics.  Their declared estimator is consequently a continuous
normal/normal game-average approximation.  Count denominators are valid games,
not invented play counts.  Player EPA uses observed prior passer-play counts.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from server.sports_nfl.gold import GAME_CONTEXT_FEATURES, GAME_FEATURES, ROLLING_METRICS, FEATURE_FAMILY_CATALOG
from server.sports_nfl.publication import verify_parquet_object
from .data_authority import DEFAULT_NFL_STAGING_ROOT, resolve_nfl_m1_authority

WINDOWS = ("season_to_date", "last_4", "last_8", "last_16")
CATEGORIES = ("game_type", "roof", "surface")
PRIOR_GAMES = 4.0
OFFSEASON_RETENTION = 0.65
QB_PRIOR_PLAYS = 100.0


def source_objects(root: Path) -> tuple[Any, dict[str, Path], dict[str, Any]]:
    authority = resolve_nfl_m1_authority(root, deep_verify=False)
    manifest = json.loads((root / "manifests" / "sha256" / authority.foundation_manifest_sha256 / "foundation-manifest.json").read_text())
    names = {"fact_nfl_team_game", "fact_nfl_play", "snapshot_nfl_depth_chart", "snapshot_nfl_weekly_roster"}
    paths = {}
    refs = {}
    for item in manifest["objects"]:
        if item["tableName"] in names:
            verified = verify_parquet_object(root, item["manifestSha256"])
            paths[item["tableName"]] = Path(verified["path"])
            refs[item["tableName"]] = item
    return authority, paths, refs


def load_sources(root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1"):
    """Physical predicates exclude every sealed-season feature/outcome row."""
    authority, paths, refs = source_objects(root)
    columns = list(dict.fromkeys([*GAME_FEATURES, "canonical_game_id", "game_date", "canonical_home_team_id", "canonical_away_team_id", "home_points", "away_points"]))
    games = pd.read_parquet(authority.game_path, columns=columns, filters=[("season", "<", 2025)])
    team = pd.read_parquet(paths["fact_nfl_team_game"], filters=[("season", "<", 2025)])
    team = team.loc[team.completed & team.game_type.ne("PRE")].copy()
    # Predicate is inside the scan before aggregation, not a post-load filter.
    with duckdb.connect() as con:
        qb = con.execute("""SELECT canonical_game_id, game_date, season,
          possession_team_id team_id, passer_player_id player_id,
          count(epa)::DOUBLE attempts, sum(epa)::DOUBLE epa_sum,
          sum(epa * epa)::DOUBLE epa_sumsq
          FROM read_parquet(?) WHERE season < 2025 AND game_type <> 'PRE'
          AND play_type = 'pass' AND passer_player_id IS NOT NULL AND epa IS NOT NULL
          GROUP BY ALL ORDER BY game_date, canonical_game_id, player_id""", [str(paths["fact_nfl_play"])]).df()
    for frame in (games, team, qb):
        frame["game_date"] = pd.to_datetime(frame.game_date)
        if int(frame.season.max()) >= 2025:
            raise ValueError("sealed season entered semantic authority")
    games = games.sort_values(["game_date", "canonical_game_id"], kind="stable").reset_index(drop=True)
    return authority, games, team, qb, refs


def make_history_features(games: pd.DataFrame, team: pd.DataFrame, qb: pd.DataFrame) -> pd.DataFrame:
    """Publish only strictly prior-date states, including within-validation updates.

    Histories are accumulated date-atomically: no outcome from another game on
    the same calendar date is available.  This conservative date availability
    is historical reconstruction, not proof of an archived release timestamp.
    """
    team_hist: dict[str, list[dict]] = defaultdict(list)
    player_hist: dict[str, list[dict]] = defaultdict(list)
    team_qb: dict[str, list[dict]] = defaultdict(list)
    team_dates = {day: group.to_dict("records") for day, group in team.groupby("game_date")}
    qb_dates = {day: group.to_dict("records") for day, group in qb.groupby("game_date")}
    all_days = sorted(set(team_dates) | set(qb_dates) | set(games.game_date))
    games_dates = {day: group.to_dict("records") for day, group in games.groupby("game_date")}
    records = []
    for day in all_days:
        for game in games_dates.get(day, []):
            result = dict(game)
            for side in ("home", "away"):
                history = team_hist[str(game[f"canonical_{side}_team_id"])]
                prior = [item for item in history if int(item["season"]) < int(game["season"])]
                previous_season = max((int(item["season"]) for item in prior), default=None)
                previous = [item for item in prior if item["season"] == previous_season]
                # Prior season is frozen: it never contains current-season games.
                prior_matrix = np.asarray([[item.get(metric, np.nan) for metric in ROLLING_METRICS] for item in previous], float).reshape(-1, len(ROLLING_METRICS))
                result[f"{side}_prior_season_gap"] = int(game["season"]) - previous_season if previous_season else 0
                result[f"{side}_actual_history_games"] = len(history)
                for j, metric in enumerate(ROLLING_METRICS):
                    finite = prior_matrix[:, j][np.isfinite(prior_matrix[:, j])]
                    result[f"{side}_{metric}__prior_sum"] = float(finite.sum())
                    result[f"{side}_{metric}__prior_n"] = len(finite)
                for window in WINDOWS:
                    history_window = ([item for item in history if item["season"] == game["season"]]
                                      if window == "season_to_date" else history[-int(window.rsplit("_", 1)[1]):])
                    matrix = np.asarray([[item.get(metric, np.nan) for metric in ROLLING_METRICS] for item in history_window], float).reshape(-1, len(ROLLING_METRICS))
                    ages = np.arange(len(history_window) - 1, -1, -1, dtype=float)
                    weights = np.exp2(-ages / 8.0)
                    if history_window:
                        weights *= OFFSEASON_RETENTION ** np.asarray([int(game["season"]) - int(item["season"]) for item in history_window])
                    for j, metric in enumerate(ROLLING_METRICS):
                        valid = np.isfinite(matrix[:, j])
                        name = f"{side}_{metric}_{window}"
                        result[f"{name}__sum"] = float(np.sum(matrix[valid, j] * weights[valid]))
                        result[f"{name}__n"] = float(weights[valid].sum())
                        result[f"{name}__observed_games"] = int(valid.sum())
                        result[f"{name}__unknown_games"] = int(len(history_window) - valid.sum())
                past_usage = team_qb[str(game[f"canonical_{side}_team_id"])]
                recent_ids = list(dict.fromkeys(item["canonical_game_id"] for item in past_usage))[-4:]
                usage: dict[str, float] = defaultdict(float)
                for item in past_usage:
                    if item["canonical_game_id"] in recent_ids:
                        age = len(recent_ids) - 1 - recent_ids.index(item["canonical_game_id"])
                        usage[str(item["player_id"])] += float(item["attempts"]) * (0.5 ** age)
                mixture = []
                for player_id, weight in sorted(usage.items()):
                    records_before = player_hist[player_id]
                    decay = np.asarray([OFFSEASON_RETENTION ** (int(game["season"]) - int(item["season"])) for item in records_before])
                    n = float(np.sum([float(item["attempts"]) * d for item, d in zip(records_before, decay)]))
                    total = float(np.sum([float(item["epa_sum"]) * d for item, d in zip(records_before, decay)]))
                    last = records_before[-1]
                    mixture.append({"playerId": player_id, "weight": weight, "n": n, "sum": total,
                                    "experienceSeasons": int(game["season"]) - min(int(item["season"]) for item in records_before),
                                    "historicalTeamChange": len({item["team_id"] for item in records_before}) > 1,
                                    "lastTeamId": last["team_id"]})
                result[f"{side}__lagged_passer_mixture"] = json.dumps(mixture, sort_keys=True)
                result[f"{side}__last_passer_date"] = str(past_usage[-1]["game_date"].date()) if past_usage else None
            records.append(result)
        # Only after every forecast on this day has been constructed.
        for item in team_dates.get(day, []):
            team_hist[str(item["team_id"])].append(item)
        for item in qb_dates.get(day, []):
            player_hist[str(item["player_id"])].append(item)
            team_qb[str(item["team_id"])].append(item)
    return pd.DataFrame(records).sort_values(["game_date", "canonical_game_id"]).reset_index(drop=True)


@dataclass
class SemanticTreatment:
    design: str
    means: dict = field(default_factory=dict)
    variances: dict = field(default_factory=dict)
    categories: dict = field(default_factory=dict)
    qb_mean: float = 0.0
    qb_variance: float = 1.0
    group_means: dict = field(default_factory=dict)
    training_end: str = ""
    names: tuple[str, ...] = ()

    def fit(self, train: pd.DataFrame, team: pd.DataFrame, qb: pd.DataFrame):
        self.training_end = str(pd.Timestamp(train.game_date.max()).date())
        # Fold parameters see training games only; validation updates are raw
        # sufficient-statistic updates and cannot refit pooling parameters.
        eligible = team.loc[team.game_date <= train.game_date.max()]
        # Recent training eras define the league center, avoiding 1999 being an
        # equally weighted 2024 offensive environment. Window fixed before fit.
        eligible = eligible.loc[eligible.season >= int(train.season.max()) - 2]
        for metric in ROLLING_METRICS:
            x = pd.to_numeric(eligible[metric], errors="coerce").to_numpy(float)
            x = x[np.isfinite(x)]
            if len(x) < 10:
                raise ValueError(f"BROKEN_SOURCE_NO_TRAINING_AUTHORITY:{metric}")
            self.means[metric] = float(x.mean())
            self.variances[metric] = max(float(x.var(ddof=1)), 1e-8)
        self.categories = {name: tuple(sorted(set(train[name].fillna("__UNKNOWN__").astype(str)) | {"__UNKNOWN__"})) for name in CATEGORIES}
        q = qb.loc[qb.game_date <= train.game_date.max()]
        self.qb_mean = float(q.epa_sum.sum() / q.attempts.sum())
        self.qb_variance = max(float(q.epa_sumsq.sum() / q.attempts.sum() - self.qb_mean ** 2), 1e-8)
        group_values: dict[str, list] = defaultdict(list)
        latest_player_states = {}
        # Group centers use only past-player states available in training rows,
        # not eventual career performance, draft grades, or validation labels.
        for side in ("home", "away"):
            for day, value in zip(train.game_date, train[f"{side}__lagged_passer_mixture"]):
                for item in json.loads(value):
                    if item["n"] > 0:
                        if item["playerId"] not in latest_player_states or day > latest_player_states[item["playerId"]][0]:
                            latest_player_states[item["playerId"]] = (day, item)
        for _, item in latest_player_states.values():
            group_values[self._group(item)].append((item["sum"], item["n"]))
        self.group_means = {key: float((sum(v[0] for v in values) + 500 * self.qb_mean) / (sum(v[1] for v in values) + 500)) for key, values in group_values.items()}
        _, names, _ = self._transform(train.head(1))
        self.names = tuple(names)
        return self

    @staticmethod
    def _group(item: dict) -> str:
        exposure = "LOW" if item["n"] < 100 else "MID" if item["n"] < 500 else "HIGH"
        return ("NEW" if item["experienceSeasons"] == 0 else "RETURNING") + "_" + exposure

    def _transform(self, frame: pd.DataFrame):
        columns, names, counts = [], [], defaultdict(int)
        def add(name, values):
            columns.append(np.asarray(values, float)); names.append(name)
        for name in GAME_CONTEXT_FEATURES:
            if name == "roof":
                # Recorded open/closed retractable-roof status need not be
                # known at the pregame cutoff. No archived release supports it.
                continue
            if name in CATEGORIES:
                values = frame[name].fillna("__UNKNOWN__").astype(str)
                values = values.where(values.isin(self.categories[name]), "__UNKNOWN__")
                for level in self.categories[name]:
                    add(f"{name}=={level}", values.eq(level))
            else:
                values = pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
                if name.endswith(("prior_games", "prior_season_games")) and (np.isnan(values).any() or (values < 0).any()):
                    raise ValueError(f"INVALID_OBSERVED_EXPOSURE:{name}")
                # Context missingness is native, explicitly not a cold-start
                # estimate. No global clipping or learned imputation is used.
                add(name, values)
                add(f"{name}__source_unknown", np.isnan(values))
        posterior_by_name = {}
        for side in ("home", "away"):
            for metric in ROLLING_METRICS:
                league, variance = self.means[metric], self.variances[metric]
                pn = frame[f"{side}_{metric}__prior_n"].to_numpy(float)
                ps = frame[f"{side}_{metric}__prior_sum"].to_numpy(float)
                gap = frame[f"{side}_prior_season_gap"].to_numpy(float)
                previous = (ps + PRIOR_GAMES * league) / (pn + PRIOR_GAMES)
                prior = league + OFFSEASON_RETENTION ** np.maximum(gap, 1) * (previous - league)
                for window in WINDOWS:
                    name = f"{side}_{metric}_{window}"
                    n = frame[f"{name}__n"].to_numpy(float)
                    total = frame[f"{name}__sum"].to_numpy(float)
                    unknown = frame[f"{name}__unknown_games"].to_numpy(float)
                    # Rolling windows already contain prior seasons; adding
                    # that same season as an informative prior double-counts
                    # games. Only season-reset windows use the frozen season.
                    center = prior if window == "season_to_date" else league
                    estimate = (total + PRIOR_GAMES * center) / (n + PRIOR_GAMES)
                    if not np.isfinite(estimate).all() or (n < 0).any():
                        raise ValueError(f"INVALID_PRIOR_STATE:{name}")
                    unresolved = (n == 0) & (unknown > 0)
                    # An observed historical game with an undefined metric is
                    # not a true zero-game cold start. Without event exposures
                    # we cannot distinguish no opportunities from source loss.
                    # Keep the estimate natively missing with an explicit flag.
                    estimate[unresolved] = np.nan
                    add(name, estimate)
                    add(f"{name}__effective_games", n)
                    add(f"{name}__posterior_sd", np.sqrt(variance / (n + PRIOR_GAMES)))
                    add(f"{name}__unknown_games", unknown)
                    posterior_by_name[name] = estimate
                    counts["prior_only_cells"] += int(((n == 0) & ~unresolved).sum())
                    counts["blended_cells"] += int((n > 0).sum())
                    counts["source_unknown_cells"] += int((unknown > 0).sum())
                    counts["unresolved_native_missing_cells"] += int(unresolved.sum())
            if self.design in {"C2", "C3"}:
                values = defaultdict(list)
                for raw in frame[f"{side}__lagged_passer_mixture"]:
                    mixture = json.loads(raw)
                    weights = np.asarray([item["weight"] for item in mixture], float)
                    weights = weights / weights.sum() if len(weights) else weights
                    prior_means = [self.group_means.get(self._group(item), self.qb_mean) if self.design == "C3" else self.qb_mean for item in mixture]
                    estimates = np.asarray([(item["sum"] + QB_PRIOR_PLAYS * prior) / (item["n"] + QB_PRIOR_PLAYS) for item, prior in zip(mixture, prior_means)])
                    mean = float(np.sum(weights * estimates)) if len(weights) else self.qb_mean
                    uncertainty = float(np.sum(weights * (np.asarray([self.qb_variance / (item["n"] + QB_PRIOR_PLAYS) for item in mixture]) + (estimates - mean) ** 2))) if len(weights) else self.qb_variance / QB_PRIOR_PLAYS
                    values["lagged_qb_epa"].append(mean)
                    values["lagged_qb_uncertainty"].append(np.sqrt(uncertainty))
                    values["lagged_passer_entropy"].append(float(-np.sum(weights * np.log(np.maximum(weights, 1e-12)))))
                    values["lagged_low_exposure_mass"].append(float(sum(w for w, item in zip(weights, mixture) if item["n"] < 100)) if len(weights) else 1.0)
                    values["lagged_historical_team_change_mass"].append(float(sum(w for w, item in zip(weights, mixture) if item["historicalTeamChange"])))
                    values["lagged_passer_unknown"].append(int(not mixture))
                # Relative contrast, not a second absolute QB-strength offset.
                values["lagged_qb_epa"] = np.asarray(values["lagged_qb_epa"]) - posterior_by_name[f"{side}_pass_epa_per_play_last_16"]
                for key, value in values.items():
                    add(f"{side}_{key}", value)
        return np.column_stack(columns), names, dict(counts)

    def transform(self, frame: pd.DataFrame):
        values, names, counts = self._transform(frame)
        if tuple(names) != self.names:
            raise ValueError("SEMANTIC_ENCODED_ORDER_MISMATCH")
        return values, counts

    def state(self):
        return {"contract": "NFL_SEMANTIC_TREATMENT_V1", "design": self.design, "trainingEnd": self.training_end,
                "sourceInputCount": 197, "selectedRegisteredInputCount": 196, "additionalSourceFeatures": 0 if self.design == "C1" else 12,
                "expandedInputCount": len(self.names), "expandedNames": self.names,
                "leagueMeans": self.means, "leagueGameVariances": self.variances, "qbMean": self.qb_mean,
                "qbVariance": self.qb_variance, "qbGroupMeans": self.group_means,
                "priorGames": PRIOR_GAMES, "offseasonRetention": OFFSEASON_RETENTION,
                "qbPriorPlays": QB_PRIOR_PLAYS, "categoricalLevels": self.categories,
                "genericMedianBranch": False, "actualTargetStarterKnown": False,
                "sourceOutage": "N0_WITH_UNDEFINED_PRIOR_GAMES_NATIVE_MISSING; PARTIAL_HISTORY_AVAILABLE_OBSERVATIONS_PLUS_UNKNOWN_COUNT",
                "categoricalOrdering": "INTERLEAVED_EXACT_EXPANDED_NAMES"}


def feature_policy(games: pd.DataFrame, history: pd.DataFrame, authority: Any, refs: dict) -> dict:
    rows = []
    for index, name in enumerate(GAME_FEATURES, 1):
        window = next((w for w in WINDOWS if name.endswith("_" + w)), None)
        side = name.split("_")[0] if name.startswith(("home_", "away_")) else None
        metric = name[len(side) + 1:-(len(window) + 1)] if window else None
        raw = games[name]
        is_rate = bool(metric and metric.endswith("rate"))
        unit = ("probability/game-average rate" if is_rate else "EPA per eligible play" if metric and "epa" in metric else "seconds per play" if metric == "seconds_per_play" else "points per game" if metric in {"points_for", "points_against"} else "category" if name in CATEGORIES else "count/calendar/context")
        row = {"stableId": f"NFL197_{index:03}", "feature": name, "side": side, "definition": name.replace("_", " "),
               "footballMeaning": f"{metric.replace('_', ' ')} over {window}, game-average estimator" if metric else name.replace("_", " "),
               "units": unit, "entityGrain": "team-pregame" if side else "game-pregame",
               "validDomain": "[0,1]" if is_rate else "real signed" if metric and "epa" in metric else "nonnegative" if metric else "declared schedule domain",
               "source": "fact_nfl_team_game" if metric else "gold_nfl_game_pregame_v1/schedule",
               "sourceIdentity": refs["fact_nfl_team_game"]["manifestSha256"] if metric else authority.game_manifest_sha256,
               "joinKeys": ["canonical_game_id", f"canonical_{side}_team_id"] if side else ["canonical_game_id"],
               "availability": "STRICT_PRIOR_COMPLETED_CALENDAR_DATE" if metric or side else "KNOWN_PREGAME_SCHEDULE",
               "releaseTiming": "Historical event availability reconstructed; original source release vintage not archived",
               "historicalRows": len(games), "historicalPresent": int(raw.notna().sum()),
               "weeks1to4Rows": int(games.week.le(4).sum()), "weeks1to4Present": int(raw[games.week.le(4)].notna().sum()),
               "currentCoverage": "2026 NO CURRENT_SEASON_COMPLETED_GAMES; protected2025 cannot initialize new candidate",
               "missingnessReason": "zero current-season exposure / no prior history / missing game source" if metric else "source unavailable or first observed schedule history",
               "structuralZero": "zero valid completed games is observed exposure; undefined rate is never observed zero" if metric else "raw zero retained; unknown separate",
               "exposureDenominator": "valid observed team-game metric count; recency-weighted effective games. NOT event-binomial count" if metric else "not applicable",
               "seasonReset": "freeze previous-season mean; pool4 league games; retain0.65 deviation each offseason; blend current evidence with4 prior games" if metric else "recompute schedule and counts",
               "sparseHistory": "normal-normal game-average posterior; finite posterior SD" if metric else "raw observed count/native missing with indicator",
               "rookieNewEntity": "league prior with4 game strength and greater uncertainty" if metric else "explicit unknown category/count0",
               "sourceOutage": "n0 with undefined observed-game metrics -> native missing; partial valid history uses posterior plus unknown count; no median or rate0" if metric else "native missing plus source-unknown indicator",
               "staleEvidence": "offseason0.65 regression and8-game half-life; retain true last-observed dates",
               "notApplicable": "native missing and explicit state; categorical UNKNOWN; no fabricated status",
               "priorHierarchy": "three-training-season league -> previous team season -> target window" if metric else "none",
               "sufficientStatistics": "weighted metric sum, weighted valid games, previous-season sum/count; fold league mean/variance" if metric else "observed schedule/context",
               "reliability": "n_eff/(n_eff+4)" if metric else "explicit source indicator",
               "uncertainty": "sqrt(fold game variance/(n_eff+4)); approximation for game-average rates" if metric else "not modeled",
               "transformation": "identity; no global clipping/log; signed EPA preserved" if metric else "one-hot including unknown" if name in CATEGORIES else "identity/native missing plus indicator",
               "rationale": "rates are game means lacking event exposure, so no false beta-binomial claims; normal-normal approximation" if metric else "preserve schedule semantics",
               "stateIndicators": "effective_games, posterior_sd, unknown_games" if metric else "source_unknown or UNKNOWN category",
               "historicalLiveParity": "same immutable SemanticTreatment.transform; publisher must supply same prior-date history;2025 authority gap explicit",
               "implementation": "server/sports_nfl_m1/semantic_features.py:SemanticTreatment",
               "disposition": "IMPLEMENTED", "selectedIn": ["C1", "C2", "C3"]}
        rows.append(row)
        if name == "roof":
            row.update({"disposition": "EXCLUDED_BY_TIMING_DECISION", "selectedIn": [],
                        "reason": "Recorded retractable-roof open/closed status lacks pregame archived release authority", "transformation": "Excluded; not one-hot encoded"})
    qb_features = ("lagged_qb_epa", "lagged_qb_uncertainty", "lagged_passer_entropy", "lagged_low_exposure_mass", "lagged_historical_team_change_mass", "lagged_passer_unknown")
    for side in ("home", "away"):
        for key in qb_features:
            rows.append({"stableId": f"NFL_ADDED_{side}_{key}", "feature": f"{side}_{key}", "definition": "Strict prior-game passing-personnel mixture: " + key,
                         "units": "EPA relative to team passing prior" if key == "lagged_qb_epa" else "uncertainty/count/probability",
                         "entityGrain": "team-pregame mixture over historically observed passers", "source": "fact_nfl_play", "sourceIdentity": refs["fact_nfl_play"]["manifestSha256"],
                         "joinKeys": ["canonical_game_id", "possession_team_id", "passer_player_id"], "availability": "STRICT_PRIOR_COMPLETED_CALENDAR_DATE",
                         "releaseTiming": "Reconstructed prior-game availability, no target-game QB identity", "historicalCoverage": "1999-2024 prior-game passing evidence; initial histories empty",
                         "currentCoverage": "new candidate current publication blocked by protected2025 prior initialization", "structuralZero": "zero prior plays means undefined player efficiency, not EPA0",
                         "exposureDenominator": "observed passer EPA plays; not QB starts", "priorHierarchy": "C2 league -> player; C3 experience/exposure peer -> player",
                         "sufficientStatistics": "prior player EPA sum/sumsq/count; offseason-weighted; last4team-game usage mixture",
                         "sparseHistory": "normal-normal100play prior; no median", "rookieNewEntity": "unknown passer mixture -> league prior and explicit unknown; NOT identified rookie starter",
                         "sourceOutage": "unknown mixture plus league uncertainty", "seasonReset": "player history retained globally;0.65 offseason decay",
                         "staleEvidence": "prior usage evidence date retained; no assertion current player remains on roster", "notApplicable": "no current starter knowledge for every event",
                         "reliability": "n/(n+100)", "uncertainty": "within posterior variance plus between-candidate variance",
                         "transformation": "identity, contrast to existing team pass EPA to limit double counting", "stateIndicators": "entropy, low exposure mass, unknown",
                         "historicalLiveParity": "same treatment, prior-date observations only", "implementation": "server/sports_nfl_m1/semantic_features.py:SemanticTreatment", "disposition": "IMPLEMENTED_SUPPORTED_LAGGED_COMPONENT", "selectedIn": ["C2", "C3"]})
    present = {r["feature"] for r in rows}
    for family, candidates in FEATURE_FAMILY_CATALOG.items():
        if family in {"LONG_HISTORY_CORE", "PLAY_STATE", "MARKET_BENCHMARK_SEPARATE"}:
            continue
        for name in candidates:
            if name in present:
                continue
            present.add(name)
            rows.append({"stableId": f"NFL_PROPOSED_{name}", "feature": name, "definition": name.replace("_", " "), "family": family,
                         "disposition": "EXCLUDED_UNSUPPORTED_SOURCE_OR_PREGAME_VINTAGE", "selectedIn": [],
                         "reason": "Not a consumed input; target starter, release-vintage, injuries/weather forecast, role or sufficient-statistics authority not established for this experiment. No missing-as-healthy assumption.",
                         "implementation": "Explicit excluded input; not manufactured or median filled"})
    return {"contract": "NFL_FEATURE_TREATMENT_SPECIFICATION_V1", "registeredFeatureCount": 197,
            "implementedRegisteredFeatureCount": 196, "explicitlyExcludedRegisteredFeatureCount": 1, "allRegisteredFeaturesHaveImplementedDecision": True, "addedImplementedSourceFeatures": 12,
            "sourceFeatureCount": len(rows), "rows": rows, "genericMedianBranchesInNewCandidates": 0,
            "C2": "supported lagged passing personnel only; actual pregame QB starter/roster continuity unproven",
            "C3": "fold-local simple exposure/experience peer pooling; no clustering tournament",
            "rights": "nflverse CC-BY-4.0 attribution; LOCAL_PRIVATE_RESEARCH; no wagering authority",
            "authority": authority.foundation_manifest_sha256}

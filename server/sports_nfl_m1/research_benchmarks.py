"""Matched Development benchmarks, separated from tradable-price evidence.

This module never fits a model, opens 2025 outcomes, or requests paid data.
Historical odds are descriptive references, not a contemporaneous backtest.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import numpy as np
import pandas as pd

from .data_authority import resolve_nfl_m1_authority

ARCHIVE_REVISION = "fbec1afa38ece5befe24fb21be8ddba8eb160fe6"
ARCHIVE_COMMITTED_AT = "2023-01-24T15:55:27Z"
ARCHIVE_URL = f"https://raw.githubusercontent.com/fivethirtyeight/nfl-elo-game/{ARCHIVE_REVISION}/data/nfl_games.csv"
LEGACY_RUN = Path(r"C:\Users\james\asp-data-staging\nfl\overnight-model-laboratory-v1\runs\matrix-fcc3cd9a5446-foundation-ebb6912919a5")
DEFAULT_OUTPUT = Path("outputs/nfl-research-benchmarks-v1")
ALIASES = {"STL": "LA", "LAR": "LA", "SD": "LAC", "OAK": "LV", "WSH": "WAS"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def immutable_json(root: Path, name: str, value: Any) -> tuple[Path, str]:
    payload = canonical_bytes(value)
    digest = hashlib.sha256(payload).hexdigest()
    path = root / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("immutable benchmark collision")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
    return path.resolve(), digest


def no_vig_home(home_odds: np.ndarray, away_odds: np.ndarray) -> np.ndarray:
    """Multiplicative/proportional normalization of American moneylines."""
    home = np.asarray(home_odds, float)
    away = np.asarray(away_odds, float)
    if home.shape != away.shape or not np.isfinite(home).all() or not np.isfinite(away).all():
        raise ValueError("aligned finite moneylines required")
    if np.any(np.abs(home) < 100) or np.any(np.abs(away) < 100):
        raise ValueError("American prices must have magnitude at least 100")
    def implied(x):
        return np.where(x > 0, 100 / (100 + np.abs(x)), np.abs(x) / (100 + np.abs(x)))
    first, second = implied(home), implied(away)
    return first / (first + second)


def conditional_home(away: np.ndarray, tie: np.ndarray, home: np.ndarray) -> np.ndarray:
    matrix = np.column_stack((away, tie, home)).astype(float)
    if not np.isfinite(matrix).all() or np.any(matrix < 0) or not np.allclose(matrix.sum(axis=1), 1, atol=1e-10):
        raise ValueError("invalid original three-way probability")
    denom = matrix[:, 0] + matrix[:, 2]
    if np.any(denom <= 0):
        raise ValueError("non-tie probability has no support")
    return matrix[:, 2] / denom


def timestamp_matched_quotes(quotes: pd.DataFrame, forecasts: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Choose latest per-bookmaker quote at declared cutoff; expose exclusions.

    No fabricated timestamp, settlement contract or line conversion is allowed.
    Duplicate event/bookmaker/observed timestamps fail rather than select by order.
    """
    required = {"eventId", "bookmaker", "observedAtUtc", "homeMoneyline", "awayMoneyline", "settlementContract"}
    if not required <= set(quotes):
        raise ValueError("missing quote fields: " + ",".join(sorted(required - set(quotes))))
    if forecasts.eventId.duplicated().any():
        raise ValueError("one frozen forecast cutoff per event required")
    joined = quotes.merge(forecasts[["eventId", "forecastCutoffUtc", "scheduledStartUtc"]], on="eventId", how="left", validate="many_to_one")
    for col in ("observedAtUtc", "forecastCutoffUtc", "scheduledStartUtc"):
        # Naive timestamps must not silently acquire an invented UTC designation.
        has_zone = joined[col].astype(str).str.contains(r"(?:Z|[+-]\d\d:\d\d)$", regex=True)
        joined[col] = pd.to_datetime(joined[col].where(has_zone), utc=True, errors="coerce")
    joined["exclusionReason"] = "INCLUDED"
    def reject(mask, reason):
        joined.loc[mask & joined.exclusionReason.eq("INCLUDED"), "exclusionReason"] = reason
    reject(joined.forecastCutoffUtc.isna() | joined.scheduledStartUtc.isna(), "FORECAST_CUTOFF_OR_KICKOFF_UNAVAILABLE")
    reject(joined.observedAtUtc.isna(), "QUOTE_TIME_UNAVAILABLE")
    reject(joined.forecastCutoffUtc >= joined.scheduledStartUtc, "NOT_PREGAME_FORECAST")
    reject(joined.observedAtUtc > joined.forecastCutoffUtc, "QUOTE_AFTER_CUTOFF")
    reject(~joined.settlementContract.eq("FULL_GAME_INCLUDING_OT_TIE_VOID"), "SETTLEMENT_UNVERIFIED")
    reject(joined.bookmaker.isna() | joined.bookmaker.astype(str).str.strip().eq(""), "BOOKMAKER_UNAVAILABLE")
    for price in ("homeMoneyline", "awayMoneyline"):
        values = pd.to_numeric(joined[price], errors="coerce")
        reject(~np.isfinite(values) | values.abs().lt(100), "INVALID_PRICE")
    included = joined.loc[joined.exclusionReason.eq("INCLUDED")].copy()
    if included.duplicated(["eventId", "bookmaker", "observedAtUtc"]).any():
        raise ValueError("ambiguous duplicate timed quote")
    counts = {str(k): int(v) for k, v in joined.exclusionReason.value_counts().items()}
    selected = included.sort_values("observedAtUtc").groupby(["eventId", "bookmaker"], as_index=False).tail(1)
    selected["quoteAgeSeconds"] = (selected.forecastCutoffUtc - selected.observedAtUtc).dt.total_seconds()
    return selected, counts


def block_interval(values: np.ndarray, frame: pd.DataFrame, seed: int = 731019) -> dict[str, Any]:
    values = np.asarray(values, float)
    if len(values) != len(frame) or len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("finite aligned paired differences required")
    blocks = frame.season.astype(str) + ":" + frame.week.astype(str)
    grouped = pd.DataFrame({"value": values, "block": blocks.to_numpy()}).groupby("block").value.agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(grouped), (2000, len(grouped)))
    samples = grouped["sum"].to_numpy()[draws].sum(axis=1) / grouped["count"].to_numpy()[draws].sum(axis=1)
    return {"pairedMean": float(values.mean()), "interval95": np.quantile(samples, [0.025, 0.975]).tolist(), "events": len(values), "seasonWeekBlocks": len(grouped), "method": "2000 percentile resamples of whole season/week blocks; exploratory Development interval, no post-selection independence"}


def binary_losses(p: np.ndarray, actual_home: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-12, 1 - 1e-12)
    truth = np.asarray(actual_home, int)
    return -(truth * np.log(p) + (1 - truth) * np.log1p(-p))


def _model_table(path: Path, label: str, calibrated: bool = False) -> pd.DataFrame:
    frame = pd.read_parquet(path, filters=[("season", ">=", 2020), ("season", "<=", 2024)])
    if frame.canonical_game_id.duplicated().any():
        raise ValueError("duplicate OOF event")
    prefix = "calibrated" if calibrated else "raw"
    frame["modelId"] = label
    frame["pHomeConditional"] = conditional_home(frame[f"{prefix}_away_probability"], frame[f"{prefix}_tie_probability"], frame[f"{prefix}_home_probability"])
    for side in ("away", "tie", "home"):
        frame[f"p_{side}"] = frame[f"{prefix}_{side}_probability"]
    return frame


def fetch_538(output_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Pinned Jan2023 revision cannot contain sealed2025; filter before scores."""
    cache = output_root / "sources" / "538-development.json"
    if cache.exists():
        cached = json.loads(cache.read_text())
        if cached["provenance"]["revision"] != ARCHIVE_REVISION:
            raise ValueError("538 archive revision mismatch")
        return pd.DataFrame(cached["rows"]), cached["provenance"]
    with urlopen(ARCHIVE_URL, timeout=45) as response:
        payload = response.read()
    text = payload.decode("utf-8-sig")
    import csv
    rows = []
    # No source outcome is converted or used before this season guard.
    for source in csv.DictReader(io.StringIO(text)):
        season = int(source["season"])
        if season >= 2025:
            raise ValueError("pinned archive unexpectedly contains protected season")
        if not 1999 <= season <= 2024:
            continue
        rows.append({key: source[key] for key in ("date", "season", "team1", "team2", "elo_prob1")})
    provenance = {"publisher": "FiveThirtyEight", "url": ARCHIVE_URL, "revision": ARCHIVE_REVISION, "revisionCommittedAt": ARCHIVE_COMMITTED_AT, "sha256": hashlib.sha256(payload).hexdigest(), "byteCount": len(payload), "retrievedAtUtc": datetime.now(timezone.utc).isoformat(), "selectedSeasons": [1999, 2024], "selectedRows": len(rows), "attribution": "FiveThirtyEight nfl-elo-game historical Elo data and code; repository MIT license", "evidenceClass": "HISTORICAL_MODEL_REFERENCE", "timing": "Documented pregame Elo field in a retrospectively generated archive; exact as-published per-game timestamp unverified. Not claimed prospective.", "excludedFields": ["score1", "score2", "result1", "postgame ratings", "QB actual participation"], "sealedSeasonPresent": False}
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("xb") as stream:
        stream.write(canonical_bytes({"rows": rows, "provenance": provenance}))
    return pd.DataFrame(rows), provenance


def evaluate(output_root: Path = DEFAULT_OUTPUT, candidate_paths: dict[str, Path] | None = None) -> dict[str, Any]:
    authority = resolve_nfl_m1_authority(deep_verify=False)
    market = pd.read_parquet(authority.market_path, filters=[("season", ">=", 2020), ("season", "<=", 2024)])
    schedule = pd.read_parquet(authority.schedule_path, columns=["game_id", "season", "gameday", "home_team", "away_team"], filters=[("season", ">=", 2020), ("season", "<=", 2024)])
    model_paths = {
        "M1_RECIPE_RAW": LEGACY_RUN / "pipelines/m1_recipe_fold_refit/oof_predictions.parquet",
        "M1_RECIPE_CALIBRATED": LEGACY_RUN / "analysis/calibration/m1_recipe_fold_refit/oof_predictions.parquet",
        "HGB_T2_LEGACY_RAW": LEGACY_RUN / "pipelines/hist_gradient_boosting_b_t2/oof_predictions.parquet",
        "HGB_T2_LEGACY_CALIBRATED": LEGACY_RUN / "analysis/calibration/hist_gradient_boosting_b_t2/oof_predictions.parquet",
    }
    if set(candidate_paths or {}) & set(model_paths):
        raise ValueError("candidate identity must not overwrite a saved baseline")
    model_paths.update(candidate_paths or {})
    models = {label: _model_table(path, label, calibrated=label.endswith("_CALIBRATED")) for label, path in model_paths.items()}
    identities = set(models["M1_RECIPE_RAW"].canonical_game_id)
    for model in models.values():
        identities &= set(model.canonical_game_id)
    if not identities:
        raise ValueError("no matched candidate population")
    models = {key: value.loc[value.canonical_game_id.isin(identities)].sort_values("canonical_game_id").reset_index(drop=True) for key, value in models.items()}
    reference = models["M1_RECIPE_RAW"]
    for model in models.values():
        if not np.array_equal(model[["canonical_game_id", "actual_home_points", "actual_away_points"]].to_numpy(), reference[["canonical_game_id", "actual_home_points", "actual_away_points"]].to_numpy()):
            raise ValueError("matched events have mismatching score labels")
    scoreboard: dict[str, Any] = {"contract": "ASP_NFL_MATCHED_BENCHMARK_SCOREBOARD_V1", "createdAtUtc": datetime.now(timezone.utc).isoformat(), "status": "RESEARCH_SHADOW", "promotionState": "NOT_PROMOTED", "wageringAuthority": False, "executionAllowedInAISP": False, "finalOotAccessed": False, "cohortEvents": len(reference), "seasons": [2020, 2024], "basis": "Development paired comparisons on identical events, not independent evidence after model selection", "modelBenchmarks": [], "historicalMarketReference": [], "matchedPublishedModelReference": [], "sourceIdentities": {"foundationManifestSha256": authority.foundation_manifest_sha256, "marketParquetSha256": sha_file(authority.market_path)}}
    cls = np.where(reference.actual_home_points > reference.actual_away_points, 2, np.where(reference.actual_home_points < reference.actual_away_points, 0, 1))
    scoreboard["sourceIdentities"]["modelOofInputs"] = {label: {"path": str(path), "sha256": sha_file(path), "byteCount": path.stat().st_size, "probabilityColumns": "calibrated" if label.endswith("_CALIBRATED") else "raw"} for label, path in model_paths.items()}
    base_probs = reference[["p_away", "p_tie", "p_home"]].to_numpy(float)
    base_loss = -np.log(np.clip(base_probs[np.arange(len(cls)), cls], 1e-12, 1))
    for label, model in models.items():
        p = model[["p_away", "p_tie", "p_home"]].to_numpy(float)
        ll = -np.log(np.clip(p[np.arange(len(cls)), cls], 1e-12, 1))
        scoreboard["modelBenchmarks"].append({"modelId": label, "events": len(model), "threeWayLogLoss": float(ll.mean()), "brierSum3Classes": float(np.square(p - np.eye(3)[cls]).sum(axis=1).mean()), "marginMAE": float(np.abs((model.predicted_home_points-model.predicted_away_points)-(model.actual_home_points-model.actual_away_points)).mean()), "totalMAE": float(np.abs((model.predicted_home_points+model.predicted_away_points)-(model.actual_home_points+model.actual_away_points)).mean()), "pairedLogLossVersusM1Raw": block_interval(ll-base_loss, model)})
    joined = reference.merge(market, on="canonical_game_id", how="left", validate="one_to_one", suffixes=("", "_market"))
    money = np.isfinite(joined.home_moneyline) & np.isfinite(joined.away_moneyline) & joined.home_moneyline.abs().ge(100) & joined.away_moneyline.abs().ge(100)
    decisive = joined.actual_home_points.ne(joined.actual_away_points)
    money_rows = joined.loc[money & decisive].copy()
    money_rows["marketHome"] = no_vig_home(money_rows.home_moneyline.to_numpy(), money_rows.away_moneyline.to_numpy())
    true_home = money_rows.actual_home_points.gt(money_rows.actual_away_points).astype(int).to_numpy()
    market_ll = binary_losses(money_rows.marketHome.to_numpy(), true_home)
    scoreboard["marketContract"] = {"evidenceClass": "HISTORICAL_MARKET_REFERENCE_TIMING_UNVERIFIED", "source": "Registered nflverse historical schedule lines", "moneyline": "Proportional no-vig American odds. Conditional home probability pH/(pH+pA). Tied actual games excluded under declared two-way tie-void analytical convention; original 3-way forecasts retained.", "settlementLimitation": "Bookmaker identity, contemporaneous quote time and book-specific settlement rules are absent. Full-game including-OT analytical reference, not verified execution/settlement evidence.", "spread": "nflverse spread_line is signed expected home winning margin (positive means home favorite). Home cover iff actual home-away exceeds spread_line; equality push. No spread-to-probability mapping.", "total": "Final home+away points including OT; over iff greater than total_line; equality push.", "stakingOrSelection": "None; no wagering edge or tradability claim", "coverage": {"pairedMoneylineEvents": int(money.sum()), "tiedEventsExcludedFromTwoWay": int((money & ~decisive).sum()), "twoWayEvaluatedEvents": len(money_rows), "spreadEvents": int(joined.spread_line.notna().sum()), "totalEvents": int(joined.total_line.notna().sum()), "quoteTimestamps": 0}}
    scoreboard["historicalMarketReference"].append({"referenceId": "MARKET_PROPORTIONAL_NO_VIG", "events": len(money_rows), "twoWayLogLoss": float(market_ll.mean()), "brierBinaryHome": float(np.square(money_rows.marketHome.to_numpy()-true_home).mean())})
    for label, model in models.items():
        matched = money_rows[["canonical_game_id", "marketHome"]].merge(model, on="canonical_game_id", validate="one_to_one").sort_values("canonical_game_id")
        truth = matched.actual_home_points.gt(matched.actual_away_points).astype(int).to_numpy()
        model_ll = binary_losses(matched.pHomeConditional.to_numpy(), truth)
        mll = binary_losses(matched.marketHome.to_numpy(), truth)
        record: dict[str, Any] = {"modelId": label, "events": len(matched), "twoWayConditionalLogLoss": float(model_ll.mean()), "brierBinaryHome": float(np.square(matched.pHomeConditional.to_numpy()-truth).mean()), "pairedLogLossMinusMarket": block_interval(model_ll-mll, matched)}
        game_lines = model.merge(market, on="canonical_game_id", validate="one_to_one", suffixes=("", "_market"))
        for kind, line, actual, prediction in (("margin", "spread_line", game_lines.actual_home_points-game_lines.actual_away_points, game_lines.predicted_home_points-game_lines.predicted_away_points), ("total", "total_line", game_lines.actual_home_points+game_lines.actual_away_points, game_lines.predicted_home_points+game_lines.predicted_away_points)):
            mask = np.isfinite(game_lines[line])
            errors = np.abs(prediction[mask]-actual[mask])
            market_errors = np.abs(game_lines.loc[mask, line]-actual[mask])
            record[kind] = {"events": int(mask.sum()), "modelMAE": float(errors.mean()), "marketLineMAE": float(market_errors.mean()), "pairedAbsoluteErrorMinusMarket": block_interval((errors-market_errors).to_numpy(), game_lines.loc[mask]), "pushes": int((actual[mask] == game_lines.loc[mask, line]).sum())}
        scoreboard["historicalMarketReference"].append(record)
    try:
        archive, provenance = fetch_538(output_root)
        archive["season"] = archive.season.astype(int)
        archive = archive.loc[archive.season.between(2020, 2024)].copy()
        archive["team1"] = archive.team1.replace(ALIASES)
        archive["team2"] = archive.team2.replace(ALIASES)
        schedule["home_team"] = schedule.home_team.replace(ALIASES)
        schedule["away_team"] = schedule.away_team.replace(ALIASES)
        archive = archive.merge(schedule, left_on=["date", "team1", "team2"], right_on=["gameday", "home_team", "away_team"], validate="one_to_one")
        archive["elo_prob1"] = archive.elo_prob1.astype(float)
        scoreboard["sourceIdentities"]["FiveThirtyEight"] = provenance
        for label, model in models.items():
            matched = model.merge(archive[["game_id", "elo_prob1"]], left_on="canonical_game_id", right_on="game_id", validate="one_to_one")
            tied = matched.actual_home_points.eq(matched.actual_away_points)
            matched = matched.loc[~tied]
            truth = matched.actual_home_points.gt(matched.actual_away_points).astype(int).to_numpy()
            model_ll = binary_losses(matched.pHomeConditional.to_numpy(), truth)
            ref_ll = binary_losses(matched.elo_prob1.to_numpy(), truth)
            scoreboard["matchedPublishedModelReference"].append({"modelId": label, "referenceId": "538_ELO_HISTORICAL_RECONSTRUCTION", "events": len(matched), "tiesExcluded": int(tied.sum()), "seasons": sorted(matched.season.unique().astype(int).tolist()), "modelTwoWayConditionalLogLoss": float(model_ll.mean()), "referenceTwoWayLogLoss": float(ref_ll.mean()), "pairedLogLossMinusReference": block_interval(model_ll-ref_ll, matched), "limitation": "538 supplies no distinct tie forecast; evaluate decisive outcomes only, not a three-way comparison or timestamp-matched prospective claim"})
    except (OSError, ValueError) as exc:
        scoreboard["publishedReferenceBlocker"] = f"{type(exc).__name__}: {exc}"
    scoreboard["nfeloDisposition"] = {"status": "NOT_IMPORTED_RIGHTS_AND_HISTORICAL_VINTAGE_UNRESOLVED", "source": "https://github.com/greerreNFL/nfelo", "licenseObserved": None, "reason": "Public repository metadata reports no license. Current power-rating page is not immutable per-game prediction evidence. Need permitted versioned Development-only pregame export with event and creation/as-of identities.", "marketInformed": True, "methodReference": "https://www.nfeloapp.com/nfl-power-ratings/"}
    scoreboard["timestampMatchedMarketComparison"] = {"status": "JOIN_IMPLEMENTED_NO_AUTHORIZED_TIMESTAMPED_QUOTES", "events": 0, "missingEvents": len(reference), "joinImplementation": "server/sports_nfl_m1/research_benchmarks.py:timestamp_matched_quotes", "minimalExportContract": {"eventId": "canonical NFL event", "bookmaker": "source bookmaker", "observedAtUtc": "original timezone-aware quote capture time, not export time", "homeMoneyline": "American odds", "awayMoneyline": "American odds", "settlementContract": "FULL_GAME_INCLUDING_OT_TIE_VOID or explicitly supported alternative", "optional": ["spreadLineHomeHandicap", "homeSpreadOdds", "awaySpreadOdds", "totalLine", "overOdds", "underOdds", "sourceSnapshotId", "sourceUseAuthority"]}, "boundedAcquisitionRequest": "Provide already entitled exports for these matched Development event IDs or collect permitted prospective quotes before each frozen forecast cutoff; no paid historical request is authorized. Preserve bookmaker, original capture time, line/price and OT/tie/push rules."}
    event_payload = reference[["canonical_game_id", "season", "week", "game_date"]].copy()
    event_payload["game_date"] = event_payload.game_date.astype(str)
    event_path, event_sha = immutable_json(output_root, "matched-events.json", event_payload.to_dict("records"))
    scoreboard["matchedEvents"] = {"path": str(event_path), "sha256": event_sha}
    path, digest = immutable_json(output_root, "scoreboard.json", scoreboard)
    pointer = {"contract": "ASP_NFL_BENCHMARK_CURRENT_V1", "path": str(path), "sha256": digest, "completed": True}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "current.json").write_bytes(canonical_bytes(pointer))
    return pointer

"""Source-backed current V18 calculations using the accepted feature builders.

This module does not load source data files or fit parameters. Sealed evaluation
files/row groups remain excluded. A loader-verified, separately acquired
operational-history capability may authorize protected calendar dates solely for
current inputs. Reconstruction clocks never become historical forecast vintages.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import ast
import inspect
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa

from server.sports_gold.features import aggregate_pitch_history, prepare_pa_history, _prior_window_features
from server.sports_modeling.feature_contract import _included_field_definitions
from server.sports_modeling.feature_view import _batting_features
from .contextual_features import (
    GameContextInput, VenueAuthority, TeamAuthority, MLB_TEAM_AUTHORITIES,
    GAME_CONTEXT_FEATURES, build_team_game_context,
)

CATEGORIES = {
    1: "ALREADY_AVAILABLE_CORRECTLY_MAPPED",
    2: "RAW_EVIDENCE_EXISTS_CALCULATION_MISSING",
    3: "RAW_EVIDENCE_EXISTS_IDENTITY_MAPPING_MISSING",
    4: "RAW_EVIDENCE_EXISTS_TIMESTAMP_OR_AVAILABILITY_INCOMPATIBLE",
    5: "AWAITING_LINEUP_OR_STARTER_CONFIRMATION",
    6: "LEGITIMATELY_UNAVAILABLE_AT_CURRENT_SEASON_STAGE",
    7: "GENUINELY_MISSING_EXTERNAL_SOURCE",
    8: "INTENTIONALLY_EXCLUDED",
}
ANNUAL_COMPONENTS = {
    "batter_prior_ab": "AB", "batter_prior_h": "H", "batter_prior_2b": "2B",
    "batter_prior_3b": "3B", "batter_prior_hr": "HR", "pitcher_prior_ipouts": "IPouts",
    "pitcher_prior_h": "H", "pitcher_prior_bb": "BB", "pitcher_prior_g": "G", "pitcher_prior_gs": "GS",
}
ANNUAL_FEATURES = frozenset({
    "batter_log1p_pa", "batter_avg", "batter_slg", "batter_so_per_pa", "batter_bb_hbp_per_pa",
    "batter_hr_per_pa", "batter_prior_missing", "pitcher_log1p_bfp", "pitcher_whip",
    "pitcher_so_per_bfp", "pitcher_bb_per_bfp", "pitcher_hr_per_bfp", "pitcher_hbp_per_bfp",
    "pitcher_gs_per_g", "pitcher_prior_missing", *ANNUAL_COMPONENTS,
})
EXPOSURES = {"batter": "batter_prior_pa_count", "pitcher": "pitcher_prior_bf_count"}
RETIRED = ("pitcher_era9", "batter_obp", "batter_last100_contact_rate")


def _utc(value: Any) -> datetime:
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Evidence timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sealed(day: Any) -> bool:
    return "2026-08-14" <= str(day)[:10] <= "2026-08-27"


def accepted_handedness(targets: pd.DataFrame) -> pd.DataFrame:
    """Exact Gold matchup encoding, including its explicit unknown-hand state.

    This does not infer a handedness from historical batting side. A missing
    current-source value stays missing via the fitted model's indicator feature.
    Parity is checked against build_advanced_features_with_sufficient_statistics.
    """
    stand = targets["stand"].fillna("").astype(str).str.upper()
    throws = targets["pThrows"].fillna("").astype(str).str.upper()
    matchup = pd.DataFrame(index=targets.index)
    matchup["matchup_batter_bats_left"] = stand.eq("L").astype(np.float64)
    matchup["matchup_batter_bats_switch"] = stand.eq("S").astype(np.float64)
    matchup["matchup_batter_hand_missing"] = (~stand.isin(["L", "R", "S"])).astype(np.float64)
    matchup["matchup_pitcher_throws_left"] = throws.eq("L").astype(np.float64)
    matchup["matchup_pitcher_hand_missing"] = (~throws.isin(["L", "R"])).astype(np.float64)
    matchup["matchup_platoon_advantage"] = (
        ((stand.eq("L") & throws.eq("R")) | (stand.eq("R") & throws.eq("L"))
         | (stand.eq("S") & throws.isin(["L", "R"])))
        & stand.isin(["L", "R", "S"]) & throws.isin(["L", "R"])
    ).astype(np.float64)
    return matchup


def _clock(record: Mapping, cutoff: datetime, *, completed: bool = False) -> dict:
    if not record.get("sourceIdentity"):
        raise ValueError("Missing source identity")
    observed, available, ingested = (_utc(record[k]) for k in ("observedAt", "availableAsOf", "ingestedAt"))
    if observed > available or available > cutoff or ingested > cutoff:
        raise ValueError("Evidence not available at current forecast cutoff")
    if completed:
        finished = record.get("completedAt") or record.get("completionConfirmedAt")
        if not finished or _utc(finished) > available or str(record.get("status", "")).upper() != "FINAL":
            raise ValueError("Prior-game completion not established before evidence availability")
    return {k: record.get(k) for k in (
        "sourceIdentity", "observedAt", "availableAsOf", "ingestedAt", "completedAt",
        "completionConfirmedAt", "sourceCutoff", "sha256", "restrictions",
    ) if record.get(k) is not None}


def calculate_annual_features(targets: pd.DataFrame, annual_priors: Sequence[Mapping], *,
                              as_of_utc: Any, annual_authority: Mapping | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Latest eligible FD1/Lahman prior season, not a replacement current-season model.

    Normalized rows bind canonicalPlayerId/domain/season/eligibleFromSeason/metrics
    to separate source clocks. Verified absence requires completePlayerDomains in
    annual_authority; a missing row alone is unknown, not a rookie declaration.
    """
    cutoff = _utc(as_of_utc)
    output = pd.DataFrame(np.nan, index=targets.index, columns=sorted(ANNUAL_FEATURES))
    records: dict[tuple[str, str], list[Mapping]] = {}
    for record in annual_priors:
        _clock(record, cutoff)
        if int(record["eligibleFromSeason"]) <= int(record["season"]):
            raise ValueError("Annual prior must first become eligible in a later season")
        records.setdefault((str(record["canonicalPlayerId"]), str(record["domain"]).upper()), []).append(record)
    evidence = []
    for index, target in targets.iterrows():
        day = date.fromisoformat(str(target["gameDate"])[:10])
        if _sealed(day):
            raise ValueError("FINAL_OOT_SEALED")
        for role, domain in (("batter", "BATTING"), ("pitcher", "PITCHING")):
            player = str(target[role+"CanonicalPlayerId"])
            eligible = [r for r in records.get((player, domain), []) if int(r["season"]) < day.year
                        and int(r["eligibleFromSeason"]) <= day.year]
            item = {"targetIndex": index, "canonicalPaId": target["canonicalPaId"], "role": role, "playerId": player}
            if not eligible:
                authority = annual_authority or {}
                known = f"{player}:{domain}" in authority.get("completePlayerDomains", [])
                known = known or (authority.get("frozenPriorFamilyComplete") is True
                    and domain in authority.get("completePriorDomainPopulation", ())
                    and player in authority.get("_verifiedCanonicalPlayerIds", ()))
                if known:
                    _clock(authority, cutoff)
                    output.loc[index, role+"_prior_missing"] = 1
                evidence.append({**item, "status": "NO_ELIGIBLE_FROZEN_FD1_PRIOR" if known else "ANNUAL_PRIOR_EVIDENCE_UNKNOWN",
                                 "careerNoHistoryInferred": False})
                continue
            latest = max(int(r["season"]) for r in eligible)
            chosen = [r for r in eligible if int(r["season"]) == latest]
            if len(chosen) != 1:
                raise ValueError("Duplicate annual canonical-player/domain/season authority")
            record = chosen[0]
            metrics = record["metrics"]
            required = ("AB", "BB", "HBP", "SF", "SH", "H", "2B", "3B", "HR", "SO") if role == "batter" else (
                "BFP", "IPouts", "BB", "H", "SO", "HR", "HBP", "GS", "G")
            for field in required:
                n = float(metrics[field])
                if not math.isfinite(n) or n < 0 or not n.is_integer():
                    raise ValueError("Annual event/exposure counts must be exact nonnegative integers: "+field)
            if role == "batter":
                values = _batting_features(metrics)
            else:
                def ratio(a, b):
                    return a/b if b > 0 else np.nan
                bfp, outs, games = float(metrics["BFP"]), float(metrics["IPouts"]), float(metrics["G"])
                values = {"pitcher_log1p_bfp": math.log1p(bfp),
                    "pitcher_whip": ratio(3*(metrics["BB"]+metrics["H"]), outs),
                    "pitcher_gs_per_g": ratio(metrics["GS"], games),
                    **{f"pitcher_{short}_per_bfp": ratio(metrics[source], bfp) for short, source in (
                        ("so", "SO"), ("bb", "BB"), ("hr", "HR"), ("hbp", "HBP"))}}
            values[role+"_prior_missing"] = 0
            values.update({f: metrics[m] for f, m in ANNUAL_COMPONENTS.items() if f.startswith(role+"_")})
            for field, value in values.items():
                if field in output:
                    output.loc[index, field] = value
            evidence.append({**item, "status": "LATEST_ELIGIBLE_FROZEN_ANNUAL_PRIOR", "sourceSeason": latest,
                             "source": _clock(record, cutoff), "noCurrentSeasonStrengthUpdateClaimed": True})
    return output, evidence


def calculate_current_player_features(targets: pd.DataFrame, pa_history: pd.DataFrame, pitches: pd.DataFrame, *,
    as_of_utc: Any, history_authority: Mapping, annual_priors: Sequence[Mapping] = (),
    annual_authority: Mapping | None = None) -> tuple[pd.DataFrame, dict]:
    """Reuse exact accepted last-100-PA/last-250-BF arithmetic without target rows.

    A truncated or sealed-gap archive cannot assert low exposure. Full last-N
    windows after completeFrom are usable only with contiguous verified captures;
    total historical exposure additionally requires allHistoryComplete or an
    exact separately timestamped cumulativeExposure.
    """
    cutoff = _utc(as_of_utc)
    source = _clock(history_authority, cutoff)
    complete_from, complete_through = (date.fromisoformat(str(history_authority[k])) for k in ("completeFrom", "completeThrough"))
    targets = targets.copy()
    targets["gameDate"] = pd.to_datetime(targets.gameDate)
    if targets.canonicalPaId.duplicated().any() or any(_sealed(d) for d in targets.gameDate):
        raise ValueError("Duplicate target identity or FINAL_OOT_SEALED")
    if len(targets.gameDate.dt.date.unique()) != 1:
        raise ValueError("Calculate one current calendar day per immutable snapshot")
    target_day = targets.gameDate.iloc[0].date()
    if complete_through != target_day-timedelta(days=1):
        raise ValueError("Completed prior-date history coverage is stale or future-dated")
    expected_dates = {(complete_from+timedelta(days=offset)).isoformat()
                      for offset in range((complete_through-complete_from).days+1)}
    contiguous_coverage = (bool(expected_dates)
        and history_authority.get("contiguousRequestedDatesComplete") is True
        and history_authority.get("missingDates") == []
        and expected_dates.issubset(set(history_authority.get("requestedDates", ()))))
    history = pa_history.copy()
    if history.empty or pitches.empty:
        raise ValueError("Completed PA/pitch history unavailable; an empty archive is not verified player cold start")
    for frame in (history, pitches):
        if frame.empty:
            continue
        if any(_sealed(d) for d in frame.gameDate):
            from .mlb_v18_current_sources import verify_operational_source_rows
            # Only the source loader can authenticate newly acquired operational
            # receipts. A date exception or public purpose flag alone is not enough.
            verify_operational_source_rows(frame, history_authority, as_of_utc=cutoff)
        if any(date.fromisoformat(str(d)[:10]) >= target_day for d in frame.gameDate):
            raise ValueError("Target-date or future history is forbidden")
        for record in frame.to_dict("records"):
            _clock(record, cutoff, completed=True)
    if not set(history.canonicalGameId).isdisjoint(set(targets.canonicalGameId)):
        raise ValueError("Target game cannot enter completed history")
    if not set(pitches.canonicalPaId).issubset(set(history.canonicalPaId)):
        raise ValueError("Pitch identity is not a completed-history PA")
    if not set(history.canonicalPaId).issubset(set(pitches.canonicalPaId)):
        raise ValueError("Incomplete pitch evidence cannot become zero pitch opportunity")
    aggregation = aggregate_pitch_history(pa.Table.from_pandas(pitches, preserve_index=False))
    prepared = prepare_pa_history(history, aggregation, allowed_seasons=tuple(sorted(set(history.season.astype(int)))))
    values, reports = [], []
    for role, window in (("batter", 100), ("pitcher", 250)):
        identity = role+"CanonicalPlayerId"
        rates, statistics = _prior_window_features(prepared, targets, entity_column=identity,
            window=window, role=role, return_sufficient_statistics=True)
        combined = pd.concat([rates, statistics], axis=1)
        combined = combined.drop(columns=[f for f in RETIRED if f in combined])
        for index, target in targets.iterrows():
            player = str(target[identity])
            prior_rows = prepared[(prepared[identity].astype(str) == player) & (prepared.gameDate.dt.date < target_day)]
            post_gap_count = int((prior_rows.gameDate.dt.date >= complete_from).sum())
            full = contiguous_coverage and history_authority.get("allHistoryComplete") is True
            known_new = contiguous_coverage and player in history_authority.get("verifiedDebutSinceCompleteFrom", {}).get(role, [])
            exposure = history_authority.get("cumulativeExposure", {}).get(role, {}).get(player)
            exposure_supported, exact_exposure = full, None
            if exposure:
                _clock(exposure, cutoff)
                if str(exposure.get("completeThrough")) != complete_through.isoformat():
                    raise ValueError("Cumulative exposure cutoff differs")
                exact_exposure = float(exposure["value"])
                if not math.isfinite(exact_exposure) or exact_exposure < 0 or not exact_exposure.is_integer():
                    raise ValueError("Cumulative exposure must be an exact count")
                if exact_exposure < len(prior_rows):
                    raise ValueError("Selected history exceeds authoritative cumulative exposure")
                exposure_supported = True
            # A current-player window extract is not the complete global archive.
            # The source loader separately proves last-N ordering across the
            # historical/current-source boundary. Exact count equality is required
            # for a sparse window: it must contain this player's entire accepted
            # history, without inventing a debut or global allHistoryComplete.
            # Unknown exposure cannot activate this path.
            complete_player_window = (
                player in history_authority.get("completeWindowPlayers", {}).get(role, [])
                and exact_exposure is not None
                and (len(prior_rows) >= window or exact_exposure == len(prior_rows)))
            window_supported = contiguous_coverage and (post_gap_count >= window or full or known_new or complete_player_window)
            if not window_supported:
                combined.loc[index, :] = np.nan
            elif prior_rows.empty:
                # Exact zero opportunity is distinct from an unknown archive.
                for field in combined:
                    if field.endswith(("_count", "_sum", "_sumsq")):
                        combined.loc[index, field] = 0
                    elif field.endswith(("_insufficient", "_missing")):
                        combined.loc[index, field] = 1
            if exact_exposure is not None:
                combined.loc[index, EXPOSURES[role]] = exact_exposure
            elif not full:
                combined.loc[index, EXPOSURES[role]] = np.nan
            reports.append({"targetIndex": index, "canonicalPaId": target.canonicalPaId, "role": role,
                "playerId": player, "window": window, "observedPAsAfterCompleteFrom": post_gap_count,
                "contiguousSourceCoverageVerified": contiguous_coverage,
                "missingCaptureDates": history_authority.get("missingDates"),
                "windowSupported": window_supported, "cumulativeExposureSupported": exposure_supported,
                "completePlayerWindowVerified": contiguous_coverage and complete_player_window,
                "status": "EXACT_PRIOR_DATE_WINDOW" if window_supported else "INCOMPLETE_WINDOW_NOT_COLD_START",
                "source": source, "sealedGap": history_authority.get("sealedGap")})
        values.append(combined)
    annual, annual_evidence = calculate_annual_features(targets, annual_priors, as_of_utc=cutoff, annual_authority=annual_authority)
    output = pd.concat([annual, *values], axis=1)
    return output, {"schemaVersion": "MLB_V18_CURRENT_PLAYER_FEATURES_V1", "rows": reports,
        "annual": annual_evidence, "source": source, "fitted": False, "genericImputation": False,
        "calculation": "ACCEPTED_GOLD_PRIOR_WINDOW_FEATURES_UNCHANGED", "historicalPublicationVintageClaimed": False}


def calculate_current_context(game: GameContextInput, *, history: Sequence[Mapping],
    venues: Mapping[str, VenueAuthority], as_of_utc: Any, history_authority: Mapping,
    teams: Mapping[str, TeamAuthority] = MLB_TEAM_AUTHORITIES) -> tuple[dict, dict]:
    """Both batting perspectives via the accepted contextual builder, no new rules.

    Each history item wraps game:GameContextInput plus source/completion clocks.
    Missing windows remain unknown; a missing end timestamp is never fabricated.
    """
    cutoff = _utc(as_of_utc)
    source = _clock(history_authority, cutoff)
    if not game.scheduled_start_utc or cutoff >= game.scheduled_start_utc or _sealed(game.game_date):
        raise ValueError("Current context must be pregame and outside sealed OOT")
    if date.fromisoformat(str(history_authority["completeThrough"])) != game.game_date-timedelta(days=1):
        raise ValueError("Incomplete current schedule history")
    safe = []
    for record in history:
        prior = record["game"]
        identity_only = record.get("identityOnly") is True
        if prior.canonical_game_id == game.canonical_game_id or prior.game_date >= game.game_date:
            raise ValueError("Forbidden target/date schedule history")
        if identity_only:
            if any(getattr(prior, name) is not None for name in (
                "actual_end_utc", "duration_minutes", "innings_played", "recent_bullpen_workload", "pregame_temperature")):
                raise ValueError("Schedule identity-only projection contains forbidden result/feature payload")
            _clock(record, cutoff)
            if str(record.get("status", "")).upper() != "FINAL":
                raise ValueError("Only completed-game identity keys may enter current schedule history")
        else:
            if _sealed(prior.game_date):
                raise ValueError("FINAL_OOT_SEALED")
            _clock(record, cutoff, completed=True)
        safe.append(prior)
    complete_from = date.fromisoformat(str(history_authority["completeFrom"]))
    sides, reports = {}, []
    for side, team in (("AWAY", game.away_team_id), ("HOME", game.home_team_id)):
        row = build_team_game_context(game, team, history=safe, venues=venues, teams=teams)
        missing = []
        # These accepted fields require all-season or contiguous counts. Do not
        # shorten their lookback silently merely because current snapshots exist.
        if not history_authority.get("allSeasonScheduleComplete"):
            for field in ("series_rematch_indicator",):
                row[field] = None
                missing.append(field)
        for days, fields in ((14, ("repeat_opponent_within_14_days",)),
                            (7, ("repeat_opponent_within_7_days", "games_last_7_days", "travel_distance_last_7_days")),
                            (3, ("games_last_3_days", "travel_distance_last_3_days"))):
            if complete_from > game.game_date-timedelta(days=days) and not history_authority.get("allSeasonScheduleComplete"):
                for field in fields:
                    row[field] = None
                    missing.append(field)
        priors = sorted([g for g in safe if team in (g.home_team_id, g.away_team_id)], key=lambda g:(g.game_date, g.canonical_game_id))
        if not priors and not history_authority.get("allSeasonScheduleComplete"):
            from .mlb_v18_current_inputs import CURRENT_ONLY_CONTEXT
            for field in tuple(row):
                if field not in CURRENT_ONLY_CONTEXT and field not in GAME_CONTEXT_FEATURES and field not in (
                    "canonical_game_id", "team_id", "opponent_team_id", "prior_game_id", "context_feature_version",
                    "history_cutoff_rule", "rivalry_authority_status", "actual_end_utc", "excluded_interactions",
                    "missing_reason_category", "missing_reasons"):
                    row[field] = None
                    missing.append(field)
        # A trip that begins before the known archive has an unknown length.
        home = team == game.home_team_id
        if priors and all((p.home_team_id == team) == home for p in priors) and not history_authority.get("allSeasonScheduleComplete"):
            for field in ("consecutive_road_games", "road_trip_game_number", "home_stand_game_number", "road_trip_length_x_travel"):
                row[field] = None
                missing.append(field)
        sides[side] = row
        reports.append({"side": side, "teamId": team, "unsupportedHistoryFields": sorted(set(missing)), "source": source})
    return sides, {"schemaVersion": "MLB_V18_CURRENT_CONTEXT_FEATURES_V1", "rows": reports,
                   "sameDateExcluded": True, "source": source, "builderUnchanged": True}


def feature_family(field: str) -> str:
    if field in ANNUAL_FEATURES:
        return "ANNUAL_PLAYER_PRIOR"
    if field.startswith(("batter_", "pitcher_")):
        return "COMPLETED_PA_PITCH_HISTORY"
    if field.startswith(("batting_", "fielding_")):
        return "TEAM_SCHEDULE_VENUE_CONTEXT"
    if field.startswith("matchup_"):
        return "CONFIRMED_PARTICIPANT_HANDEDNESS"
    if field.startswith("context_"):
        return "SIMULATED_PA_STATE"
    if field in GAME_CONTEXT_FEATURES:
        return "CURRENT_SCHEDULE_CALENDAR"
    return "CANONICAL_IDENTITY_METADATA"


def reconcile_field_contract(source_order: Sequence[str], preprocessing_metadata: Mapping, *,
    availability: Mapping[str, Mapping], field_specifications: Sequence[Mapping] = ()) -> dict:
    """Exactly one evidence-backed category for each of the accepted 246 fields.

    availability must cover each field or its family and specify category1..8,
    evidence,status,repair. No default claims that missing columns equal sources.
    """
    if len(source_order) != 246 or len(set(source_order)) != 246 or list(source_order) != preprocessing_metadata["sourceColumns"]:
        raise ValueError("Frozen 246-field ordering differs")
    base = {f["featureName"]: f for f in _included_field_definitions()}
    specs = {str(f.get("feature_name", f.get("featureName", f.get("feature", "")))): dict(f) for f in field_specifications}
    transforms = preprocessing_metadata["transformationContracts"]
    bindings = preprocessing_metadata["prior"]["outputSchema"]["bindings"]
    semantic = preprocessing_metadata["semantic"]
    model_columns = {f["feature"]: f for f in transforms["modelFeatureColumns"]}
    expression = {}
    for node in ast.walk(ast.parse(inspect.getsource(build_team_game_context))):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    expression[key.value] = ast.unparse(value)
    rows = []
    for index, field in enumerate(source_order):
        family = feature_family(field)
        state = availability.get(field, availability.get(family))
        if not state or int(state.get("category", 0)) not in CATEGORIES or not state.get("evidence"):
            raise ValueError("Field classification lacks explicit evidence: "+field)
        category = int(state["category"])
        suffix = field.split("_", 1)[1] if field.startswith(("batting_", "fielding_")) else field
        binding = bindings.get(field)
        definition = base.get(field, {}).get("transformation")
        if field in ANNUAL_COMPONENTS:
            definition = "Exact "+ANNUAL_COMPONENTS[field]+" count in latest eligible prior-season player/domain row"
        if not definition and binding:
            definition = binding.get("componentDefinition") or binding.get("exposureDefinition")
        if not definition and suffix in expression:
            definition = "Accepted contextual builder expression: "+expression[suffix]
        if not definition:
            if field in EXPOSURES.values():
                definition = "All accepted-history completed prior-date PA count for this player and role; not annual prior or last-window exposure"
            elif "last100" in field or "last250" in field:
                definition = "Accepted Gold _prior_window_features output "+field+"; pitch counts sum over last100PA/last250BF, including unclassified pitches"
            elif field.startswith("matchup_"):
                definition = "Accepted pre-PA handedness indicator "+field+" from confirmed batter L/R/S and pitcher L/R; unknown has explicit hand_missing"
            else:
                definition = "Canonical current-event/hypothetical-PA identity metadata: "+field
        window = binding.get("historyWindow") if binding else (
            "LATEST_ELIGIBLE_PRIOR_SEASON" if family == "ANNUAL_PLAYER_PRIOR" else
            "LAST_100_PA_OR_LAST_250_BF_AND_FULL_ACCEPTED_HISTORY_EXPOSURE" if family == "COMPLETED_PA_PITCH_HISTORY" else
            "PRIOR_COMPLETED_DATES; 3/7/14-day windows, previous game and contiguous trips; series rematch uses season history" if family == "TEAM_SCHEDULE_VENUE_CONTEXT" else "CURRENT_PREGAME_OR_SIMULATED_PA")
        treatment = {"modelSlot": model_columns.get(field), "semanticRule": semantic.get("rules", {}).get(field),
            "nativeMissingWhenAuthorized": field in semantic.get("nativeMissingFeatures", []),
            "priorMethod": binding.get("method") if binding else None,
            "priorRepresentation": ("RAW_PLUS_FROZEN_POSTERIOR_EXPOSURE_RELIABILITY_UNCERTAINTY_HISTORY" if field in transforms["wave1SourceFeatures"] else
                                    "FROZEN_POSTERIOR_IN_EXISTING_SOURCE_SLOT" if field in transforms["wave2SourceFeatures"] else
                                    "SOURCE_OR_TREATMENT_DEPENDENCY_NOT_EXTRA_MODEL_FEATURE")}
        rows.append({"order": index, "field": field, "definition": definition, "sourceFamily": family,
            "entityGrain": "PLAYER_ROLE" if family in {"ANNUAL_PLAYER_PRIOR", "COMPLETED_PA_PITCH_HISTORY"} else
                           "TEAM_GAME_PERSPECTIVE" if family == "TEAM_SCHEDULE_VENUE_CONTEXT" else "GAME_OR_HYPOTHETICAL_PA",
            "lookbackWindow": window, "requiredAvailability": "observedAt <= availableAsOf <= forecast cutoff < first pitch; ingestedAt separate; prior game FINAL/completion confirmed before availability; source date strictly before target date",
            "v18Transformation": treatment, "acceptedSpecification": specs.get(field),
            "missingValueTreatment": "No generic median/mode; exact frozen semantic/prior treatment only. Unknown history remains unavailable, not zero or rookie.",
            "coldStartTreatment": "Verified no history only: retained frozen training-fold league/hierarchical prior and authorized native-NaN branch; known-zero opportunity remains distinct.",
            "category": category, "categoryName": CATEGORIES[category], "currentImplementationStatus": state.get("status"),
            "exactRepair": state.get("repair"), "classificationEvidence": state["evidence"]})
    return {"schemaVersion": "MLB_V18_CURRENT_246_FIELD_RECONCILIATION_V1", "fieldCount": len(rows),
        "sourceOrder": list(source_order), "sourceFamilyCounts": dict(Counter(r["sourceFamily"] for r in rows)),
        "categoryCounts": {str(k): sum(r["category"] == k for r in rows) for k in CATEGORIES}, "fields": rows,
        "retiredOutsideSourceOrder": list(RETIRED), "genericImputation": False, "modelFitting": False,
        "sameDateHistoryRulePreserved": True, "finalOotPhysicalReadAuthorized": False}


def field_contract_markdown(contract: Mapping) -> str:
    lines = ["# V18 current-input field reconciliation", "", "Exactly 246 raw source/dependency fields, not 246 external sources.", "",
             "| Order | Field | Family | Category | Definition | Window | Treatment | Current status / repair |", "|---:|---|---|---:|---|---|---|---|"]
    for row in contract["fields"]:
        treatment = row["v18Transformation"]
        cells = [row["order"], row["field"], row["sourceFamily"], row["category"], row["definition"], row["lookbackWindow"],
                 str(treatment["priorMethod"] or treatment["priorRepresentation"]), str(row["currentImplementationStatus"])+" / "+str(row["exactRepair"])]
        lines.append("| "+" | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in cells)+" |")
    lines.extend(["", "The companion JSON retains per-field source evidence, clocks, entity grain, accepted specification, exact transformation rule, missing/cold-start treatment, and repair. No prior snapshot is overwritten.", ""])
    return "\n".join(lines)


def _legitimate_missing(field: str, raw: Mapping, metadata: Mapping, player_note: Mapping | None = None) -> bool:
    """Recognize explicit frozen missing states, never merely HGB NaN tolerance."""
    role = "batter" if field.startswith("batter_") else "pitcher" if field.startswith("pitcher_") else None
    if field in ANNUAL_FEATURES and role and raw.get(role+"_prior_missing") == 1:
        return True
    if role and field not in EXPOSURES.values() and ("last100" in field or "last250" in field):
        count = raw.get("batter_last100_pa_count" if role == "batter" else "pitcher_last250_bf_count")
        if count == 0 and player_note and player_note.get("windowSupported"):
            return True
    semantic = metadata.get("semantic", {})
    rule = semantic.get("rules", {}).get(field)
    if rule and rule.get("kind") in {"NO_PRIOR_CONTEXT", "COLD_EXPOSURE", "STRUCTURAL_ZERO"}:
        from .stage3_semantic_treatment import _state, SemanticTreatmentError
        try:
            _, cold, source, invalid = _state(pd.DataFrame([raw]), field, rule)
            return bool(cold[0] and not source[0] and not invalid[0])
        except (KeyError, ValueError, TypeError, SemanticTreatmentError):
            return False
    if field in semantic.get("travelInteractions", ()):
        prefix = "batting" if field.startswith("batting_") else "fielding"
        return raw.get(prefix+"_previous_game_missing") == 1 and raw.get(prefix+"_team_alignment_missing") == 0
    return False


def compose_current_game(snapshot: Mapping, source_bundle: Any, contract: Mapping, *, as_of_utc: Any = None) -> dict:
    """Compose starting-lineup rows with all246 slots and explicit source gaps.

    contract may additionally supply _crosswalk (MLBAM->accepted player ID),
    _teamCrosswalk (MLBAM team ID->accepted abbreviation), _annualPriors and
    _annualAuthority. source_bundle is CurrentHistory or a mapping; optional
    schedule_games/schedule_authority hold a separate identity-only schedule.
    No historical lineup is substituted and no bullpen roster is manufactured.
    """
    from .mlb_v18_current_inputs import compose_current_input, _source_reason, _provenance
    bundle = dict(source_bundle) if isinstance(source_bundle, Mapping) else vars(source_bundle)
    annual_priors = contract.get("_annualPriors", bundle.get("annual_priors", ()))
    annual_authority = contract.get("_annualAuthority", bundle.get("annual_authority"))
    order = list(contract["rawFeatureColumns"])
    cutoff = _utc(as_of_utc or snapshot["capturedAt"])
    info = snapshot["game"]
    game_id, start = str(info["game_id"]), _utc(info["starts_at"])
    sides = {s["side"]: s for s in snapshot.get("sides", [])}
    blockers = []
    def block(reason, dependency, **extra):
        item = {"reason": reason, "dependency": dependency, **extra}
        if item not in blockers:
            blockers.append(item)
    authority_path = Path(__file__).with_name("mlb_context_authorities_v1.json")
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    preprocessing = contract.get("_preprocessingMetadata")
    if preprocessing is None:
        from .mlb_regime_baseline import verified_json
        sha = "4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684"
        preprocessing = verified_json(Path(__file__).resolve().parents[2] /
            f".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/{sha}.json", sha)
    venues = {}
    for v in authority["venues"]:
        for mlbam in v["mlbVenueIds"]:
            venues[str(mlbam)] = VenueAuthority(str(mlbam), v["latitude"], v["longitude"], v["timeZone"],
                v["altitudeFeet"], v["country"], v.get("region"))
    venue_key = str(info.get("source_venue_id") or "")
    venue = venues.get(venue_key)
    timezone_name = venue.timezone_name if venue else info.get("timezone")
    if not timezone_name:
        block("EXACT_VENUE_TIMEZONE_UNAVAILABLE", "CURRENT_SCHEDULE_VENUE_IDENTITY")
        return {"event": {"canonicalGameId": game_id, "startsAtUtc": start.isoformat()}, "rows": [], "fieldReports": [],
                "blockers": blockers, "providerInputs": {}, "canSimulate": False, "coverage": {"rawInputCount": 246}}
    day = start.astimezone(ZoneInfo(timezone_name)).date()
    if cutoff >= start or _sealed(day) or str(info.get("status", "")).upper() not in {"SCHEDULED", "PREGAME", "PRE_GAME"}:
        raise ValueError("Target must be prospective pregame outside sealed Final OOT")
    game_state = next(iter(snapshot.get("gameState") or []), {})
    event_source = {"sourceIdentity": game_state.get("source") or "AISP_PERSISTED_SCHEDULE",
        "observedAt": game_state.get("observed_at"), "availableAsOf": game_state.get("available_as_of"), "eventId": game_id}
    event = {"canonicalGameId": game_id, "gameDate": day.isoformat(), "startsAtUtc": start.isoformat(),
        "venueTimezone": timezone_name, "venueId": venue_key,
        "homeTeamId": sides.get("HOME", {}).get("team", {}).get("abbreviation"),
        "awayTeamId": sides.get("AWAY", {}).get("team", {}).get("abbreviation"), "source": event_source,
        "sourceCutoff": cutoff.isoformat()}
    crosswalk = contract.get("_crosswalk", bundle.get("mlbam_to_canonical", {}))
    if annual_authority is not None:
        annual_authority = {**annual_authority, "_verifiedCanonicalPlayerIds": frozenset(crosswalk.values())}
    targets, raw_rows, base_reports, metadata = [], [], [], []
    used_hand_supplements = {}
    def participant_hand(value, src, mlbam_id, canonical_id, name, allowed):
        if value not in (None, ""):
            return value, src
        candidates = []
        for record in bundle.get("currentPlayerIdentityEvidence", []):
            if str(record.get("mlbamId")) != str(mlbam_id) or record.get(name) not in allowed:
                continue
            if record.get("canonicalPlayerId") not in (None, canonical_id):
                raise ValueError("Current handedness supplement canonical identity differs")
            if record.get("sourcePurpose") != "CURRENT_PLAYER_IDENTITY":
                raise ValueError("Current handedness supplement has incompatible purpose")
            _clock(record, cutoff)
            candidates.append(record)
        if not candidates:
            return value, src
        latest = max(candidates, key=lambda r: (_utc(r["availableAsOf"]), _utc(r["ingestedAt"])))
        if len({r[name] for r in candidates if r["availableAsOf"] == latest["availableAsOf"]}) > 1:
            raise ValueError("Conflicting current handedness source authority")
        used_hand_supplements[(str(mlbam_id), name)] = {**latest, "canonicalPlayerId": canonical_id}
        return latest[name], {**latest, "source": latest["sourceIdentity"]}
    for batting_side, defending_side in (("AWAY", "HOME"), ("HOME", "AWAY")):
        batting, defending = sides.get(batting_side, {}), sides.get(defending_side, {})
        lineup, starter = batting.get("lineupAuthority", {}), defending.get("starter", {})
        entries = list(batting.get("lineup") or [])
        if lineup.get("status") != "CONFIRMED" or len(entries) != 9 or [int(e.get("batting_order", 0)) for e in entries] != list(range(1, 10)):
            block("CURRENT_CONFIRMED_ORDERED_LINEUP_UNAVAILABLE", batting_side+"_LINEUP", category=5)
            continue
        for entry in entries:
            batter, pitcher = crosswalk.get(str(entry.get("mlbam"))), crosswalk.get(str(starter.get("mlbamId")))
            if not batter or not pitcher:
                block("EXACT_CURRENT_PLAYER_IDENTITY_MAPPING_UNAVAILABLE", batting_side+"_PARTICIPANTS", category=3,
                      batterMlbamId=entry.get("mlbam"), pitcherMlbamId=starter.get("mlbamId"))
                continue
            try:
                bats, bats_source = participant_hand(entry.get("bats"), lineup, entry.get("mlbam"), batter,
                                                      "bats", {"L", "R", "S"})
                throws, throws_source = participant_hand(starter.get("throws"), starter, starter.get("mlbamId"), pitcher,
                                                          "throws", {"L", "R"})
            except (KeyError, TypeError, ValueError) as exc:
                block("CURRENT_HANDEDNESS_SUPPLEMENT_INCOMPATIBLE", str(exc), category=4)
                continue
            pa_id = f"SIMULATION_INPUT:{game_id}:{batting_side}:{entry['batting_order']}"
            fields = {}
            for name, value, src, player in (
                ("batterCanonicalPlayerId", batter, lineup, batter), ("pitcherCanonicalPlayerId", pitcher, starter, pitcher),
                ("batterBats", bats, bats_source, batter), ("pitcherThrows", throws, throws_source, pitcher)):
                fields[name] = {"value": value, "playerId": player, "eventId": game_id, "sourceIdentity": src.get("source"),
                    "observedAt": src.get("observedAt"), "availableAsOf": src.get("availableAsOf")}
            fields["canonicalPaId"] = {**event_source, "value": pa_id, "identityKind": "HYPOTHETICAL_PA"}
            try:
                raw, report = compose_current_input(source_order=order, event=event, batting_side=batting_side,
                    as_of_utc=cutoff, field_evidence=fields, treated_order=contract.get("treatedFeatureColumns", []),
                    prior_output_schema=contract.get("priorOutputSchema", {}))
            except ValueError as exc:
                block("CURRENT_PARTICIPANT_OR_EVENT_TIMESTAMP_INCOMPATIBLE", str(exc), category=4)
                continue
            # Gold defines missing flags, but fitted V18 deliberately holds an
            # unknown hand. Only exact known hands may become executable inputs;
            # a current source-null value is never guessed from observed PA side.
            hand_records = [fields["batterBats"], fields["pitcherThrows"]]
            if (bats_source is not lineup or throws_source is not starter) and bats in {"L", "R", "S"} and throws in {"L", "R"} and all(
                    _source_reason(record, game_id, cutoff) is None for record in hand_records):
                hands = accepted_handedness(pd.DataFrame([{"stand": bats, "pThrows": throws}])).iloc[0].to_dict()
                for name, value in hands.items():
                    raw.loc[:, name] = value
                for field in report["fields"]:
                    if field["field"] in hands:
                        field.update(supported=True, status="ACCEPTED_GOLD_HANDEDNESS_FROM_VERIFIED_CURRENT_SOURCE",
                                     provenance=[_provenance(record) for record in hand_records])
            targets.append({"canonicalPaId": pa_id, "canonicalGameId": game_id, "gameDate": day.isoformat(),
                            "batterCanonicalPlayerId": batter, "pitcherCanonicalPlayerId": pitcher,
                            "stand": bats, "pThrows": throws})
            raw_rows.append(raw.iloc[0].to_dict())
            base_reports.append(report)
            metadata.append({"battingSide": batting_side, "battingOrder": int(entry["batting_order"]),
                             "batterMlbamId": str(entry["mlbam"]), "pitcherMlbamId": str(starter["mlbamId"])})
    starting_rows = len(raw_rows)
    roster_report = []
    current_roster = bundle.get("currentRoster", snapshot.get("currentRoster", []))
    if isinstance(current_roster, Mapping):
        current_roster = [r for rows in current_roster.values() for r in rows]
    for defending_side, batting_side in (("HOME", "AWAY"), ("AWAY", "HOME")):
        defending = sides.get(defending_side, {})
        team = defending.get("team", {})
        starter_id = str(defending.get("starter", {}).get("mlbamId"))
        candidates = []
        for original in current_roster:
            r = {**original, "mlbamId": original.get("mlbamId", original.get("mlbam_id")),
                "sourceIdentity": original.get("sourceIdentity", original.get("source")),
                "observedAt": original.get("observedAt", original.get("observed_at")),
                "availableAsOf": original.get("availableAsOf", original.get("available_as_of")),
                "ingestedAt": original.get("ingestedAt", original.get("ingested_at"))}
            team_match = r.get("team_id", r.get("teamId")) in {team.get("uuid"), team.get("abbreviation")} or r.get("team_code") == team.get("abbreviation")
            if not team_match or str(r.get("position", r.get("role", ""))).upper() not in {"P", "PITCHER", "SP", "RP"}:
                continue
            if str(r["mlbamId"]) == starter_id:
                continue
            if not r.get("active_roster", r.get("activeRoster", False)) or str(r.get("availability_status", r.get("rosterStatus", ""))).upper() != "ACTIVE":
                continue
            try:
                _clock(r, cutoff)
                if r.get("effective_at") and _utc(r["effective_at"]) > cutoff:
                    raise ValueError("Roster effective time follows cutoff")
                if str(r.get("source_mode", "LIVE")).upper() != "LIVE":
                    raise ValueError("Non-live roster")
            except (KeyError, TypeError, ValueError) as exc:
                roster_report.append({"side": defending_side, "mlbamId": r["mlbamId"], "status": "ROSTER_TIMESTAMP_INCOMPATIBLE", "reason": str(exc)})
                continue
            player = crosswalk.get(str(r["mlbamId"]))
            if not player or r.get("throws") not in {"L", "R"}:
                roster_report.append({"side": defending_side, "mlbamId": r["mlbamId"], "status": "ROSTER_IDENTITY_OR_HANDEDNESS_UNRESOLVED"})
                continue
            observed = bundle["pa_history"]
            prior = observed[observed.pitcherCanonicalPlayerId.astype(str).eq(str(player))] if not observed.empty else observed
            last = max(prior.gameDate.astype(str), default="") if not prior.empty else ""
            candidates.append((last, str(player), r))
        # Same bounded last-eight candidate rule; membership comes from the live
        # active roster, not from a historical pitching appearance alone.
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        base_index = next((i for i, m in enumerate(metadata[:starting_rows]) if m["battingSide"] == batting_side), None)
        if base_index is None:
            continue
        for _, player, r in candidates[:8]:
            target = {**targets[base_index], "canonicalPaId": f"SIMULATION_INPUT:{game_id}:STAFF:{defending_side}:{player}",
                      "pitcherCanonicalPlayerId": player, "pThrows": r["throws"]}
            raw, report = deepcopy(raw_rows[base_index]), deepcopy(base_reports[base_index])
            raw.update(canonicalPaId=target["canonicalPaId"], pitcherCanonicalPlayerId=player)
            bats, throws = target["stand"], target["pThrows"]
            all_hands = accepted_handedness(pd.DataFrame([{"stand": bats, "pThrows": throws}])).iloc[0].to_dict()
            hands = {name: int(all_hands[name]) for name in (
                "matchup_pitcher_throws_left", "matchup_pitcher_hand_missing", "matchup_platoon_advantage")}
            raw.update(hands)
            for field in report["fields"]:
                if field["field"] in {*hands, "pitcherCanonicalPlayerId", "canonicalPaId"}:
                    field.update(supported=True, status="CURRENT_ACTIVE_ROSTER_STAFF_IDENTITY", provenance=[_clock(r, cutoff)])
            targets.append(target)
            raw_rows.append(raw)
            base_reports.append(report)
            metadata.append({"battingSide": batting_side, "battingOrder": metadata[base_index]["battingOrder"],
                "batterMlbamId": metadata[base_index]["batterMlbamId"], "pitcherMlbamId": str(r["mlbamId"]), "rosterSide": defending_side})
            roster_report.append({"side": defending_side, "mlbamId": str(r["mlbamId"]), "canonicalPlayerId": player,
                "status": "CURRENT_ACTIVE_NONSTARTER_STAFF_CANDIDATE", "source": _clock(r, cutoff),
                "notAClaimOfActualFutureAppearance": True})
    target_frame = pd.DataFrame(targets)
    player_values, player_report = None, {}
    if len(targets):
        try:
            player_values, player_report = calculate_current_player_features(target_frame, bundle["pa_history"], bundle["pitches"],
                as_of_utc=cutoff, history_authority=bundle["authority"], annual_priors=annual_priors,
                annual_authority=annual_authority)
        except (KeyError, TypeError, ValueError) as exc:
            block("COMPLETED_PLAYER_HISTORY_CONTRACT_INCOMPLETE", str(exc), category=4)
            try:
                player_values, annual_report = calculate_annual_features(target_frame, annual_priors,
                    as_of_utc=cutoff, annual_authority=annual_authority)
                player_report = {"annual": annual_report, "rollingUnavailable": str(exc)}
            except (KeyError, TypeError, ValueError) as annual_exc:
                block("ANNUAL_PRIOR_CONTRACT_INCOMPLETE", str(annual_exc), category=4)
    contexts, context_report = {}, {}
    schedule = bundle.get("schedule_games", bundle.get("schedule_identity_rows", bundle.get("games", [])))
    schedule_authority = bundle.get("schedule_authority", bundle.get("schedule_identity_authority", bundle["authority"]))
    if schedule_authority and schedule_authority.get("family") == "SCHEDULE_IDENTITIES_ONLY":
        dates = sorted(str(g["gameDate"]) for g in schedule if g.get("gameDate"))
        first = dates[0] if dates else None
        complete = bool(first and schedule_authority["startDate"] <= first
                        and schedule_authority["throughDate"] >= (day-timedelta(days=1)).isoformat())
        schedule_authority = {**schedule_authority, "completeFrom": schedule_authority["startDate"],
            "completeThrough": (day-timedelta(days=1)).isoformat(), "allSeasonScheduleComplete": complete,
            "seasonStartDate": first}
        recent = {str(g["canonicalGameId"]): g for g in bundle.get("games", [])}
        converted = []
        for source_game in schedule:
            g = dict(source_game)
            if str(g.get("status", "")).upper() not in {"FINAL", "COMPLETED EARLY"}:
                # Retain the target's pregame series identity separately below.
                if str(g.get("mlbamGamePk")) == str(info.get("source_game_id")):
                    converted.append(g)
                continue
            prior = recent.get(str(g["canonicalGameId"]))
            if prior is not None and not _sealed(g["gameDate"]):
                g = {**g, **prior, "identityOnly": False}
                if g.get("inningsPlayed") is None and "inning" in bundle["pa_history"]:
                    innings = pd.to_numeric(bundle["pa_history"].loc[
                        bundle["pa_history"].canonicalGameId.astype(str).eq(str(g["canonicalGameId"])), "inning"], errors="coerce").dropna()
                    if len(innings):
                        g["inningsPlayed"] = int(innings.max())
            else:
                g.update(identityOnly=True, status="FINAL", inningsPlayed=None, completedAt=None, durationMinutes=None)
            converted.append(g)
        schedule = converted
    team_map = contract.get("_teamCrosswalk", {str(t["mlbam_id"]): t["abbreviation"] for t in snapshot.get("teamIdentityCrosswalk", [])})
    def team_code(g, side):
        mapped = team_map.get(str(g.get(side+"TeamMlbamId")))
        direct = g.get(side+"TeamAbbreviation")
        result = mapped or direct
        if result not in MLB_TEAM_AUTHORITIES:
            raise ValueError("Exact registered team-code mapping unavailable: "+str(g.get(side+"TeamMlbamId")))
        return result
    try:
        history = []
        for g in schedule:
            if date.fromisoformat(str(g["gameDate"])) >= day:
                continue
            prior = GameContextInput(str(g["canonicalGameId"]), date.fromisoformat(str(g["gameDate"])),
                team_code(g, "home"), team_code(g, "away"), str(g["venueMlbamId"]),
                _utc(g["scheduledStartUtc"]) if g.get("scheduledStartUtc") else None,
                actual_end_utc=_utc(g["completedAt"]) if g.get("completedAt") else None,
                duration_minutes=g.get("durationMinutes"), innings_played=g.get("inningsPlayed"),
                series_game_number=g.get("seriesGameNumber"), games_in_series=g.get("gamesInSeries"))
            history.append({**g, "game": prior})
        target_schedule = next((g for g in schedule if str(g.get("mlbamGamePk")) == str(info.get("source_game_id"))), {})
        game = GameContextInput(game_id, day, event["homeTeamId"], event["awayTeamId"], venue_key, start,
            series_game_number=target_schedule.get("seriesGameNumber"), games_in_series=target_schedule.get("gamesInSeries"),
            season_start_date=date.fromisoformat(schedule_authority["seasonStartDate"]) if schedule_authority.get("seasonStartDate") else None,
            is_home_opener=not any(p["game"].home_team_id == event["homeTeamId"] for p in history)
                if schedule_authority.get("allSeasonScheduleComplete") else False)
        contexts, context_report = calculate_current_context(game, history=history, venues=venues, as_of_utc=cutoff,
                                                              history_authority=schedule_authority)
        if not schedule_authority.get("allSeasonScheduleComplete"):
            for value in contexts.values():
                value["is_home_opener"] = None
    except (KeyError, TypeError, ValueError) as exc:
        block("SCHEDULE_CONTEXT_CONTRACT_INCOMPLETE", str(exc), category=4)
    field_reports, categories = [], []
    for index, raw in enumerate(raw_rows):
        fields = {f["field"]: dict(f) for f in base_reports[index]["fields"]}
        batting_side = metadata[index]["battingSide"]
        def assign(field, value, provenance, reason):
            if field not in fields:
                return
            supported = value is not None and not (isinstance(value, (float, np.floating)) and not np.isfinite(value))
            raw[field] = value if supported else None
            fields[field].update(supported=supported, status=reason if supported else "UNKNOWN_OR_NATIVE_MISSING_REQUIRES_TREATMENT_AUTHORITY",
                                 provenance=provenance)
        if player_values is not None:
            for field, value in player_values.iloc[index].items():
                family = feature_family(field)
                is_annual = family == "ANNUAL_PLAYER_PRIOR"
                field_authority = (annual_authority or {}) if is_annual else bundle["authority"]
                assign(field, value, [{"sourceIdentity": field_authority.get("sourceIdentity"),
                    "evidenceSection": "sourceEvidence.player.annual" if is_annual else "sourceEvidence.player",
                    "targetIndex": index, "sourceFamily": family}], "ACCEPTED_CURRENT_PLAYER_CALCULATION")
        for prefix, side in (("batting", batting_side), ("fielding", "HOME" if batting_side == "AWAY" else "AWAY")):
            for field, value in contexts.get(side, {}).items():
                if field in GAME_CONTEXT_FEATURES:
                    assign(field, value, [{"sourceIdentity": schedule_authority.get("sourceIdentity"),
                        "evidenceSection": "sourceEvidence.context"}], "ACCEPTED_CALENDAR_CALCULATION")
                else:
                    assign(prefix+"_"+field, value, [{"sourceIdentity": schedule_authority.get("sourceIdentity"),
                        "evidenceSection": "sourceEvidence.context", "side": side}], "ACCEPTED_CURRENT_CONTEXT_CALCULATION")
        unsupported = []
        for field in order:
            family = feature_family(field)
            f = fields[field]
            role = "batter" if field.startswith("batter_") else "pitcher"
            note = next((r for r in player_report.get("rows", []) if r["targetIndex"] == index and r["role"] == role), None)
            if not f["supported"] and _legitimate_missing(field, raw, preprocessing, note):
                f.update(supported=True, status="EXPLICIT_LEGITIMATE_MISSING_FROZEN_TREATMENT_REQUIRED",
                         physicalValueMissing=True, frozenTransformValidationRequired=True)
            f["category"] = 1 if f["supported"] else 4
            f["categoryName"] = CATEGORIES[f["category"]]
            f["sourceFamily"] = family
            if not f["supported"]:
                unsupported.append(field)
        categories.extend(f["category"] for f in fields.values())
        field_reports.append({**metadata[index], "canonicalPaId": raw.get("canonicalPaId"), "fields": [fields[f] for f in order],
                              "rawSupportedCount": 246-len(unsupported), "missingRawFields": unsupported})
    if field_reports:
        missing = sorted(set(f for report in field_reports for f in report["missingRawFields"]))
        if missing:
            block("EXACT_SOURCE_OR_TREATMENT_DEPENDENCIES_UNRESOLVED", "V18_RAW_INPUT_CONTRACT", fields=missing, category=4)
    else:
        block("NO_CONFIRMED_STARTING_MATCHUPS_COMPOSED", "CURRENT_PARTICIPANTS", category=5)
    by_side = {side: [raw_rows[i] for i, meta in enumerate(metadata) if meta["battingSide"] == side and "rosterSide" not in meta] for side in ("AWAY", "HOME")}
    bullpen = {side: [raw_rows[i] for i, meta in enumerate(metadata) if meta.get("rosterSide") == side] for side in ("AWAY", "HOME")}
    for side in ("AWAY", "HOME"):
        if not bullpen[side]:
            opposite = "HOME" if side == "AWAY" else "AWAY"
            if current_roster and not by_side[opposite]:
                block("CURRENT_STAFF_TEMPLATE_WAITS_OPPONENT_LINEUP", opposite+"_CONFIRMED_LINEUP", category=5)
            else:
                block("CURRENT_STAFF_INPUT_POOL_NOT_SUPPORTED", side+"_PIT_ROSTER_IDENTITY_AND_PLAYER_STATE", category=3 if current_roster else 5)
    provider = {"awayBatters": by_side["AWAY"], "homeBatters": by_side["HOME"],
        "awayStarter": by_side["HOME"][0] if by_side["HOME"] else None,
        "homeStarter": by_side["AWAY"][0] if by_side["AWAY"] else None, "awayBullpen": bullpen["AWAY"], "homeBullpen": bullpen["HOME"]}
    return {"schemaVersion": "MLB_V18_CURRENT_GAME_COMPOSITION_V1", "event": event, "rows": raw_rows[:starting_rows],
        "fieldReports": field_reports, "blockers": blockers, "providerInputs": provider,
        "canSimulate": not blockers and starting_rows == 18 and bool(bullpen["AWAY"]) and bool(bullpen["HOME"]),
        "frozenTransformValidationRequired": True,
        "coverage": {"rawInputCount": 246, "rowsComposed": starting_rows, "staffTemplateRows": len(raw_rows)-starting_rows, "expectedStartingRows": 18,
            "bestRawSupportedCount": max((r["rawSupportedCount"] for r in field_reports), default=0),
            "worstRawSupportedCount": min((r["rawSupportedCount"] for r in field_reports), default=0),
            "categoryCellCounts": {str(k): categories.count(k) for k in CATEGORIES}},
        "sourceEvidence": {"player": player_report, "context": context_report,
            "history": {key: value for key, value in bundle["authority"].items() if not str(key).startswith("_")},
            "currentRoster": roster_report,
            **({"currentPlayerIdentitySupplements": list(used_hand_supplements.values())} if used_hand_supplements else {}),
            "staticVenueAuthoritySha256": hashlib.sha256(authority_path.read_bytes()).hexdigest()},
        "sourceDigest": bundle["authority"].get("sourceIdentity"), "historicalTemplatesBorrowed": False,
        "genericImputation": False, "modelFitting": False}

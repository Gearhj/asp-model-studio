"""Inference-only, immutable current NFL joint-score research publication.

Numerical model evidence stays separate from observed current roster context.
Nothing here fits, opens a source partition outside 2026, or writes to AISP.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.audit_assurance.canonical import canonical_json_bytes
from .current_state_model import INPUT_NAMES, RATE_NAMES, MODEL_IDS, SEED
from .forward_vintages import DEFAULT_OUTPUT as ARCHIVE_ROOT, schedule_events_from_handoff, select_vintage
from .labs_simulation import (AUTHORITY, file_record, immutable_json,
                              verify_object, summarize_scores, utc)

OUTPUTS_ROOT = Path(__file__).resolve().parents[2] / "outputs"
CONTRACT = "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2"
DRAW_COUNT = 5000
MISSING_SEASON_ADMISSION_REASON = "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"


def _checked_ref(ref):
    if file_record(Path(ref["path"])) != {key: ref[key] for key in ("path", "sha256", "byteCount")}:
        raise ValueError("PUBLICATION_PARENT_CHECKSUM_OR_BYTE_COUNT_DIFFERS")
    return {key: ref[key] for key in ("path", "sha256", "byteCount")}


def _put(root, name, body):
    digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return immutable_json(Path(root) / "sha256" / digest / name, body)


def _publish_labeled_object(record, root):
    """Same Labs object shape with explicit authorized evidence labels."""
    digest = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    path = Path(root) / "sha256" / digest / "artifact.json"
    artifact = immutable_json(path, record)
    manifest = immutable_json(path.with_name("manifest.json"), {
        "schemaVersion": "NFL_LABS_ARTIFACT_MANIFEST_V1", **AUTHORITY,
        "evidenceClass": "OBSERVED_AS_OF", "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF",
        "artifactSchemaVersion": record["schemaVersion"], "files": [artifact]})
    return {"artifact": artifact, "manifest": manifest, "eventId": record["eventId"],
            "forecastId": record["forecastId"], "modelId": record["model"]["engineId"],
            "artifactSchemaVersion": record["schemaVersion"]}


def _value(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def _context(archive_root, cutoff, qb, system):
    """Only physically 2026 source snapshots; listed roles are not starters."""
    result = {"schemaVersion": "NFL_CURRENT_OBSERVED_CONTEXT_V2", **AUTHORITY,
              "evidenceClass": "OBSERVED_AS_OF", "numericallyIncorporated": False,
              "confirmedStarterKnown": False, "families": {}, "listedQuarterbacks": [],
              "limitation": "Listed roster/depth roles are not confirmed starters or probability weights. Historical core uses only lagged passer evidence; no current injury/weather/roster value is inserted into that model."}
    if not (Path(archive_root) / "CURRENT.json").exists():
        result["status"] = "FORWARD_ARCHIVE_NOT_YET_CAPTURED"
        return result
    player_priors = {}
    for family in ("rosters", "weekly_rosters", "depth_charts", "injuries", "practice_reports", "weather_forecasts"):
        vintage = select_vintage(Path(archive_root), family, cutoff)
        if vintage is None:
            result["families"][family] = {"status": "UNAVAILABLE_AT_FORECAST_CUTOFF"}
            continue
        if vintage.get("season") != 2026 or vintage.get("sourceIdentity", {}).get("season") != 2026:
            raise ValueError("CURRENT_CONTEXT_REQUIRES_PHYSICAL_2026_AUTHORITY")
        result["families"][family] = {"status": "OBSERVED_CONTEXT_ONLY_NOT_MODEL_INPUT",
            **{key: vintage.get(key) for key in ("payload", "observedAtUtc", "sourceRetrievedAtUtc", "assetUpdatedAtUtc", "releasePublishedAtUtc", "effectiveAt", "sourceRights", "sourceVersionIdentity")}}
        if family not in {"rosters", "weekly_rosters", "depth_charts"}:
            continue
        path = Path(vintage["payload"]["path"])
        schema = pq.ParquetFile(path).schema_arrow.names
        columns = [name for name in ("season", "week", "team", "club_code", "gsis_id", "position", "position_abbr", "pos_abb",
                   "full_name", "football_name", "first_name", "last_name", "player_name", "depth_team", "depth_position",
                   "pos_rank", "pos_slot", "status", "dt") if name in schema]
        if not columns:
            continue
        # The archived envelope already verified the exclusively 2026 source;
        # physical predicate is an additional guard when the season column exists.
        frame = pd.read_parquet(path, columns=columns, filters=[("season", "==", 2026)] if "season" in schema else None)
        position = next((name for name in ("position", "position_abbr", "pos_abb") if name in frame), None)
        team_column = next((name for name in ("team", "club_code") if name in frame), None)
        if position is None or team_column is None:
            continue
        raw_qb_rows = int(frame[position].astype(str).str.upper().eq("QB").sum())
        if "dt" in frame:
            frame["_effective_utc"] = pd.to_datetime(frame["dt"], utc=True, errors="coerce")
            frame = frame.loc[frame["_effective_utc"].notna() & frame["_effective_utc"].le(pd.Timestamp(cutoff))]
            # Select the latest TEAM snapshot first. Merely selecting each
            # player's last row would silently retain players removed months ago.
            latest = frame.groupby(team_column)["_effective_utc"].transform("max")
            frame = frame.loc[frame["_effective_utc"].eq(latest)].drop(columns="_effective_utc")
            selection_rule = "LATEST_VALID_TEAM_DEPTH_SNAPSHOT_THEN_TEAM_GSIS_DEDUPLICATION"
        else:
            # This publication is specifically the already registered Week1
            # schedule. A future-effective weekly role cannot enter its context.
            if "week" in frame:
                weeks = pd.to_numeric(frame["week"], errors="coerce")
                frame = frame.loc[weeks.isna() | weeks.le(1)]
            selection_rule = "CURRENT_ARCHIVED_2026_WEEK1_ROSTER_NO_ORIGINAL_ROW_EFFECTIVE_TIME_ASSERTED"
        rows = frame.loc[frame[position].astype(str).str.upper().eq("QB")].copy()
        if "gsis_id" not in rows:
            result["families"][family]["qbIdentityStatus"] = "NO_GSIS_COLUMN"
            continue
        rows = rows.drop_duplicates([team_column, "gsis_id"], keep="last")
        selected_records = [{key: _value(value) for key, value in row.items()} for row in rows.to_dict("records")]
        result["families"][family].update(qbRowsInArchivedObject=raw_qb_rows,
            selectedQbRows=len(selected_records), selectionRule=selection_rule,
            selectedRowsSha256=hashlib.sha256(canonical_json_bytes(selected_records)).hexdigest(),
            selectedEffectiveTimes=sorted({str(row["dt"]) for row in selected_records if row.get("dt") is not None}))
        for row in selected_records:
            if row.get("dt") is not None and not pd.isna(row["dt"]):
                effective = pd.Timestamp(row["dt"])
                effective = effective.tz_localize("America/New_York") if effective.tzinfo is None else effective
                if effective.tz_convert("UTC") > pd.Timestamp(cutoff):
                    continue
            identity = row.get("gsis_id")
            if identity is None or pd.isna(identity) or not str(identity).startswith("00-"):
                continue
            team_id = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}.get(str(row[team_column]), str(row[team_column]))
            item = {"teamId": team_id, "gsisId": str(identity), "sourceFamily": family,
                    "evidenceClass": "OBSERVED_AS_OF",
                    "listedRole": "QB_NOT_CONFIRMED_STARTER", "sourceRows": {key: _value(value) for key, value in row.items()},
                    "observedAtUtc": vintage["observedAtUtc"], "numericallyIncorporated": False}
            # A historical player prior is a conditional research description,
            # not a model forecast under an invented starter assignment.
            from .current_state_features import qb_player_prior
            if str(identity) not in player_priors:
                player_priors[str(identity)] = qb_player_prior(qb, str(identity), cutoff_utc=cutoff,
                    season=2026, decay=system.decay, league_prior=system.league_prior, lag_hours=system.lag_hours)
            item["historicalPlayerPrior"] = player_priors[str(identity)]
            result["listedQuarterbacks"].append(item)
    result["uniqueQuarterbackIdentities"] = len(player_priors)
    result["status"] = "CURRENT_CONTEXT_SEPARATE_FROM_NUMERICAL_CORE"
    return result


def _distribution(home, away):
    home, away = np.asarray(home), np.asarray(away)
    if home.shape != (DRAW_COUNT,) or away.shape != home.shape or np.any(home < 0) or np.any(away < 0):
        raise ValueError("INVALID_CURRENT_SCORE_POPULATION")
    if not np.isfinite(home).all() or not np.isfinite(away).all() or np.any(home != np.floor(home)) or np.any(away != np.floor(away)):
        raise ValueError("CURRENT_SCORES_MUST_BE_FINITE_NONNEGATIVE_INTEGERS")
    pairs, counts = np.unique(np.column_stack((home, away)), axis=0, return_counts=True)
    joint = [{"homeScore": int(pair[0]), "awayScore": int(pair[1]), "count": int(count), "probability": float(count/DRAW_COUNT)} for pair, count in zip(pairs, counts)]
    marginals = {}
    for key, values, name in (("scoreMarginDistribution", home-away, "homeMinusAway"), ("totalScoreDistribution", home+away, "totalScore")):
        unique, counts = np.unique(values, return_counts=True)
        marginals[key] = [{name: int(value), "probability": float(count/DRAW_COUNT)} for value, count in zip(unique, counts)]
    quantiles = {name: {str(q): float(np.quantile(values, q)) for q in (.05, .25, .5, .75, .95)}
        for name, values in (("homeScore", home), ("awayScore", away), ("marginHomeMinusAway", home-away), ("total", home+away))}
    spreads = [{"line": float(line), "homeCoverProbability": float(np.mean(home-away+line > 0)),
                "awayCoverProbability": float(np.mean(home-away+line < 0)), "pushProbability": float(np.mean(home-away+line == 0))}
               for line in np.arange(-14, 14.5, .5)]
    totals = [{"line": float(line), "overProbability": float(np.mean(home+away > line)),
               "underProbability": float(np.mean(home+away < line)), "pushProbability": float(np.mean(home+away == line))}
              for line in np.arange(20, 71, .5)]
    return {"jointScoreDistribution": joint, **marginals, "scoreSummary": summarize_scores(home, away),
            "quantiles": quantiles, "spreadCoverProbabilities": spreads, "overUnderProbabilities": totals,
            "keyMarginMass": {str(k): float(np.mean(home-away == k)) for k in (-14,-10,-7,-3,0,3,7,10,14)},
            "representativeFinals": [{"representativeId": f"sample-{i}", "homeScore": int(home[i]), "awayScore": int(away[i]), "selectionSeed": SEED}
                                      for i in np.linspace(0, DRAW_COUNT-1, 12, dtype=int)],
            "reconciliation": {"jointPopulationCount": DRAW_COUNT, "jointProbabilityMass": sum(row["probability"] for row in joint),
                               "marginalDistributionsExact": True, "rawProbabilitiesDerivedFromSamePopulation": True}}


def _feature_evidence(row, historical_sources):
    values = []
    for name in INPUT_NAMES:
        item = {"feature": name, "value": _value(row[name]), "evidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF",
                "sourceEvidence": "REGISTERED_1999_2024_FINALIZED_PBP_SOURCES", "genericFallback": False,
                "historicalPublicationVintageEstablished": False}
        if name in RATE_NAMES:
            item.update(effectiveExposure=_value(row[f"{name}__effective_exposure"]),
                        currentSeasonExposure=_value(row[f"{name}__current_exposure"]),
                        posteriorSd=_value(row[f"{name}__posterior_sd"]), sourceUnknown=bool(row[f"{name}__source_unknown"]))
            item["treatmentState"] = ("UNAVAILABLE_INCREMENTAL_EFFECT_EXCLUDED" if item["value"] is None else
                "HIERARCHICAL_PRIOR_ONLY" if item["currentSeasonExposure"] == 0 else "PRIOR_PLUS_CURRENT_SEASON_EVIDENCE")
        values.append(item)
    return {"inputs": values, "historicalSources": historical_sources, "currentTargetStarterKnown": False,
            "currentRosterContextNumericallyIncorporated": False, "sealed2025InitializationExcluded": True,
            "missingInterveningSeasons": {side: int(row[f"{side}_missing_season_uncertainty"]) for side in ("home", "away")}}


def _single_event_predictions(system, events, team, qb, ensemble_weight, clock, skips):
    """A fixed one-event CRN shape is independent of the other eligible games."""
    for event in events:
        inference_time = utc(clock())
        if inference_time >= utc(event["kickoffUtc"]):
            skips.append({"eventId": event["eventId"], "reason": "KICKOFF_REACHED_BEFORE_SINGLE_EVENT_INFERENCE"})
            continue
        frame = pd.DataFrame([{"canonical_game_id": event["eventId"], "season": 2026, "week": event["week"], "game_type": "REG",
            "game_date": pd.Timestamp(event["kickoffUtc"]).tz_convert("America/New_York").normalize().tz_localize(None),
            "canonical_home_team_id": event["homeTeamId"], "canonical_away_team_id": event["awayTeamId"],
            "forecast_cutoff_utc": inference_time, "home_points": None, "away_points": None}])
        # The final guard is adjacent to the actual frozen-estimator invocation.
        inference_time = utc(clock())
        if inference_time >= utc(event["kickoffUtc"]):
            skips.append({"eventId": event["eventId"], "reason": "KICKOFF_REACHED_BEFORE_SINGLE_EVENT_INFERENCE"})
            continue
        frame["forecast_cutoff_utc"] = inference_time
        predicted = system.predict(frame, team, qb, draws=DRAW_COUNT, seed=SEED)
        components = list(MODEL_IDS)
        if ensemble_weight is not None:
            weight = float(ensemble_weight)
            if not np.isfinite(weight) or not 0 <= weight <= 1:
                raise ValueError("INVALID_FROZEN_ENSEMBLE_WEIGHT")
            use = np.random.default_rng(SEED + 41).random((1, DRAW_COUNT)) < weight
            hierarchical, residual = predicted["HIERARCHICAL"], predicted["RESIDUAL"]
            predicted["ENSEMBLE"] = {**hierarchical,
                "homeDraws": np.where(use, residual["homeDraws"], hierarchical["homeDraws"]),
                "awayDraws": np.where(use, residual["awayDraws"], hierarchical["awayDraws"]),
                "scoreMeans": (1-weight)*hierarchical["scoreMeans"] + weight*residual["scoreMeans"],
                "residualAuthoritySha256": None}
            components.append("ENSEMBLE")
        yield event, inference_time, predicted, components


def publish_current_v2(system, team, qb, model_ref, study_ref, output, *, source_receipt,
                       ensemble_weight=None, archive_root=ARCHIVE_ROOT,
                       clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
    """Publish 5000-draw laws from frozen models; no fit or source acquisition."""
    output = Path(output).resolve()
    if not output.is_relative_to(OUTPUTS_ROOT.resolve()) or output == OUTPUTS_ROOT.resolve():
        raise ValueError("CURRENT_PUBLICATION_REQUIRES_DEDICATED_MODEL_STUDIO_OUTPUT")
    model_ref, study_ref = _checked_ref(model_ref), _checked_ref(study_ref)
    if isinstance(source_receipt, dict) and "path" in source_receipt and "sources" not in source_receipt:
        source_ref = _checked_ref(source_receipt)
        source_receipt = json.loads(Path(source_ref["path"]).read_bytes())
    if source_receipt.get("sealedOotRead") is not False or any(int(source["season"]) >= 2025 for source in source_receipt.get("sources", [])):
        raise ValueError("HISTORICAL_SOURCE_RECEIPT_MUST_EXCLUDE_SEALED_2025")
    sources = source_receipt.get("sources", [])
    if not sources or any(not source.get("retrievedAt") for source in sources):
        raise ValueError("ACTUAL_HISTORICAL_SOURCE_RETRIEVAL_REQUIRED")
    historical_cutoff = max(utc(source["retrievedAt"]) for source in sources)
    for frame in (team, qb):
        if (frame.season.astype(int) >= 2025).any():
            raise ValueError("CURRENT_CORE_REQUIRES_EXPLICIT_HISTORICAL_THROUGH_2024_INPUTS")
    trained_seasons = {int(str(identity).split("_", 1)[0]) for identity in system.league_prior.get("training_ids", [])}
    if not trained_seasons or max(trained_seasons) != 2024 or pd.Timestamp(system.metadata["trainingEnd"]).year > 2025:
        raise ValueError("MODEL_TRAINING_BOUNDARY_DIFFERS")
    selection = schedule_events_from_handoff()
    started = utc(clock())
    if historical_cutoff > started:
        raise ValueError("SOURCE_RETRIEVAL_AFTER_ACTUAL_FORECAST_CLOCK")
    context = _context(archive_root, started, qb, system)
    context_ref = _put(output / "contexts", "context.json", context)
    source_summary = [{key: source.get(key) for key in ("season", "sha256", "byteCount", "retrievedAt", "assetUpdatedAt", "releasePublishedAt", "license", "evidenceClass")} for source in sources]
    eligible, skips = [], []
    for event in selection["events"]:
        if utc(event["kickoffUtc"]) <= utc(clock()):
            skips.append({"eventId": event["eventId"], "reason": "KICKOFF_REACHED_BEFORE_INFERENCE"})
        else:
            eligible.append(event)
    inference_time = utc(clock())
    still_pregame = []
    for event in eligible:
        if utc(event["kickoffUtc"]) <= inference_time:
            skips.append({"eventId": event["eventId"], "reason": "KICKOFF_REACHED_AT_BATCH_INFERENCE_GUARD"})
        else:
            still_pregame.append(event)
    eligible = still_pregame
    artifacts, forecasts, feature_refs, reused = [], [], [], 0
    if eligible:
        for event, inference_time, predicted, components in _single_event_predictions(system, eligible, team, qb, ensemble_weight, clock, skips):
            index = 0
            if utc(clock()) >= utc(event["kickoffUtc"]):
                skips.append({"eventId": event["eventId"], "reason": "KICKOFF_REACHED_DURING_INFERENCE"}); continue
            state = predicted["_states"].iloc[index]
            feature_evidence = _feature_evidence(state, source_summary)
            feature_ref = _put(output / "features", "feature-state.json", {"schemaVersion": "NFL_CURRENT_STATE_FEATURE_EVIDENCE_V2", "eventId": event["eventId"], "evidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", **feature_evidence})
            feature_refs.append(feature_ref)
            for component in components:
                # A sparse training-only missing-season flag acquired asymmetric
                # score-mean coefficients. Do not admit its unvalidated current regime,
                # including previously cached objects. The scoring-only dynamic
                # baseline does not consume this flag in its mean estimator.
                if component != "DYNAMIC" and any(
                    count > 0 for count in feature_evidence["missingInterveningSeasons"].values()
                ):
                    skips.append({"eventId": event["eventId"], "component": component,
                        "reason": MISSING_SEASON_ADMISSION_REASON,
                        "missingInterveningSeasons": feature_evidence["missingInterveningSeasons"]})
                    continue
                population = predicted[component]
                distribution = _distribution(population["homeDraws"][index], population["awayDraws"][index])
                numerical = {"modelSha256": model_ref["sha256"], "component": component, "eventId": event["eventId"],
                    "featureStateSha256": feature_ref["sha256"], "draws": DRAW_COUNT, "seed": SEED,
                    "randomStreamScope": "SINGLE_EVENT_FIXED_1_BY_5000_COMMON_RANDOM_NUMBERS",
                    "ensembleResidualWeight": ensemble_weight if component == "ENSEMBLE" else None,
                    "jointScoreDistribution": distribution["jointScoreDistribution"]}
                numerical_sha = hashlib.sha256(canonical_json_bytes(numerical)).hexdigest()
                identity_path = output / "identities" / numerical_sha / "publication.json"
                if identity_path.exists():
                    old = json.loads(identity_path.read_bytes())
                    verify_object(old["publishedObject"]); _checked_ref(old["forecast"])
                    artifacts.append(old["publishedObject"]); forecasts.append(old["forecast"]); reused += 1; continue
                publication_time = utc(clock())
                if publication_time >= utc(event["kickoffUtc"]):
                    skips.append({"eventId": event["eventId"], "component": component, "reason": "KICKOFF_REACHED_BEFORE_PUBLICATION"}); continue
                engine_id = f"NFL_CURRENT_STATE_{component}_V2"
                forecast_id = "nfl-current-state-v2:sha256:" + numerical_sha
                model = {"engineId": engine_id, "modelVersion": "NFL_RECONSTRUCTED_CURRENT_STATE_V2",
                    "trainingCutoff": system.metadata["trainingEnd"], "trainingSeasonEnd": 2024,
                    "modelArtifact": model_ref, "study": study_ref, "evidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF"}
                common = {**AUTHORITY, "sport": "NFL", "forecastId": forecast_id, "eventId": event["eventId"],
                    "evidenceClass": "OBSERVED_AS_OF",
                    "homeTeam": {"teamId": event["homeTeamId"], "abbreviation": event["homeTeamId"], "source": "NFLVERSE"},
                    "awayTeam": {"teamId": event["awayTeamId"], "abbreviation": event["awayTeamId"], "source": "NFLVERSE"},
                    "model": model, "scheduledStartUtc": event["kickoffUtc"], "forecastCreatedUtc": inference_time.isoformat(),
                    "forecastCutoffUtc": inference_time.isoformat(), "sourceCutoffUtc": historical_cutoff.isoformat(),
                    "sourceCutoffMeaning": "LATEST_REGISTERED_RETRIEVAL_OF_RECONSTRUCTED_HISTORICAL_MODEL_INPUTS_NOT_NEW_CURRENT_TEAM_EVIDENCE",
                    "publishedAtUtc": publication_time.isoformat(), "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF",
                    "forecastObservationEvidenceClass": "OBSERVED_AS_OF", "featureEvidence": feature_ref,
                    "currentObservedContext": context_ref, "currentContextNumericallyIncorporated": False,
                    "historicalEvidenceThroughDate": str(pd.to_datetime(team.game_date).max().date()),
                    "sealed2025Excluded": True, "lateHistoricalCorrectionsPossible": True,
                    "noGenericMedianOrModeFallback": True, "scheduleSource": selection["sourceHandoffs"],
                    "missingInputs": ["SEALED_2025_SEASON_INITIALIZATION", "CONFIRMED_CURRENT_STARTER", "HISTORICAL_INJURY_ROSTER_WEATHER_VINTAGES"],
                    "uncertainty": {"scoreMeanSd": population["stateUncertainty"][index].tolist(),
                        "isCalibrated": False, "missingSeasonCount": feature_evidence["missingInterveningSeasons"]},
                    "scoreMeanEstimator": {"home": float(population["scoreMeans"][index, 0]), "away": float(population["scoreMeans"][index, 1])},
                    "treatmentBranchCounts": population["branchCounts"], "numericalIdentitySha256": numerical_sha,
                    "randomStreamScope": "SINGLE_EVENT_FIXED_1_BY_5000_COMMON_RANDOM_NUMBERS",
                    "publicationStabilityReason": "Other games starting or disappearing never shift this event's residual or rounding streams.",
                    "independentOfM1": True, "explainsM1Forecast": False}
                forecast = _put(output / "forecasts", "forecast.json", {"schemaVersion": "NFL_CURRENT_STATE_GAME_FORECAST_V2", **common, **distribution["scoreSummary"], "jointScoreDistribution": distribution["jointScoreDistribution"]})
                artifact = {"schemaVersion": "NFL_LABS_SCORE_DISTRIBUTION_V1", **common, "sourceForecast": {**forecast, "forecastId": forecast_id},
                    "drawCount": DRAW_COUNT, "seed": SEED, "scenario": {"scenarioId": "BASE", "modelInputChange": False},
                    "generatingLaw": {"id": "NFL_CURRENT_STATE_PAIRED_INNER_HOLDOUT_RESIDUAL_V2",
                        "representation": "EXACT_5000_DRAW_EMPIRICAL_JOINT_PMF", "pairedResidualDependencePreserved": True,
                        "calibration": "RAW_DISTRIBUTION_ONLY", "residualAuthoritySha256": population["residualAuthoritySha256"],
                        "ensembleSelectionSeed": SEED + 41 if component == "ENSEMBLE" else None,
                        "ensembleResidualWeight": ensemble_weight if component == "ENSEMBLE" else None},
                    **distribution, "simulatedDrives": None, "simulatedGames": None,
                    "limitations": ["Reconstructed finalized Development inputs; historical publication vintages and correction lineage are not established.",
                        "2025 is excluded, leaving a missing intervening season and explicitly wider uncalibrated uncertainty.",
                        "Current archived roster/depth roles and historical named-player priors are descriptive context, not numerical starter scenarios.",
                        "Final-score residual law is not constrained to legal scoring sequences; no drive/play paths or overtime incidence are fabricated.",
                        "No sportsbook quote is included; spread/total and push probabilities are queries of this same raw measure."]}
                item = _publish_labeled_object(artifact, output / "nfl-labs-score-distributions-v2")
                verify_object(item)
                immutable_json(identity_path, {"evidenceClass": "OBSERVED_AS_OF", "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "numericalIdentitySha256": numerical_sha, "publishedObject": item, "forecast": forecast})
                artifacts.append(item); forecasts.append(forecast)
    _checked_ref(model_ref); _checked_ref(study_ref)
    receipt = {"schemaVersion": CONTRACT, "contract": CONTRACT, **AUTHORITY, "evidenceClass": "OBSERVED_AS_OF", "publishedAtUtc": utc(clock()).isoformat(),
        "eventCount": len(selection["events"]), "forecastEventCount": len({item["eventId"] for item in artifacts}),
        "forecastCount": len(forecasts), "artifactCount": len(artifacts), "unchangedNumericalObjectsReused": reused,
        "model": model_ref, "study": study_ref, "sourceScheduleProjection": selection, "currentObservedContext": context_ref,
        "artifacts": artifacts, "forecasts": forecasts, "skips": skips, "drawsPerForecast": DRAW_COUNT,
        "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "forecastObservationEvidenceClass": "OBSERVED_AS_OF",
        "providerCalls": 0, "modelFits": 0, "sealed2025Read": False, "aispWrites": 0,
        "importInstruction": "Verify the handoff and each forecast/artifact manifest checksum and byte count. Register the separate NFL_CURRENT_STATE_*_V2 research engines and import precomputed forecasts plus NFL_LABS_SCORE_DISTRIBUTION_V1 artifacts by canonical event/model/forecast identity. Keep M1 and play-level engines separate; do not execute models, replace prior forecasts, grant wagering authority, or infer drive/play paths."}
    handoff = _put(output / "handoffs", "handoff.json", receipt)
    files = [handoff, context_ref, model_ref, study_ref, *feature_refs, *forecasts]
    files.extend(ref for item in artifacts for ref in (item["artifact"], item["manifest"]))
    manifest = _put(output / "manifests", "manifest.json", {"schemaVersion": "NFL_CURRENT_STATE_PUBLICATION_MANIFEST_V2", **AUTHORITY,
        "evidenceClass": "OBSERVED_AS_OF", "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF",
        "files": files, "handoff": handoff, "forecastCount": len(forecasts), "eventCount": receipt["forecastEventCount"],
        "publishedAtUtc": receipt["publishedAtUtc"], "sourceCutoffUtc": historical_cutoff.isoformat()})
    return {"handoff": handoff, "manifest": manifest, "forecastCount": len(forecasts), "eventCount": receipt["forecastEventCount"],
            "skipCount": len(skips), "skips": skips, "reused": reused, "context": context_ref}

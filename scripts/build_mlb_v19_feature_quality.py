"""Research-only quality and semantic-treatment supplement to frozen V18 evidence.

Reads one checksum-pinned operational JSON audit, not history payloads, an
estimator, or a database. The two games remain original September 10 forecasts;
this is an interpretation of their evidence, never a replacement publication.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_SHA = "2bcf37de2fd76316ec850ebec2f06c7383fcd7c5afa275071ea21f8aafc95e29"
INPUT = ROOT / f"outputs/mlb-v18-unattended-v1/evidence/sha256/{INPUT_SHA}/sept10-operational-evidence.json"
DEST = ROOT / "outputs/mlb-v19-current-state-specialists-v1/feature-quality"
CATEGORIES = (
    "FULLY_CURRENT", "CURRENT_BUT_PARTIALLY_OBSERVED", "HISTORICAL_PRIOR_BY_DESIGN",
    "MISSING_WITH_SEMANTIC_TREATMENT", "MISSING_THROUGH_SOURCE_PIPELINE_GAP", "UNSUPPORTED",
)
GAP_INDICATORS = (
    "recent_bullpen_workload_missing", "previous_venue_altitude_missing",
    "previous_game_end_time_missing", "previous_game_end_missing",
    "previous_game_duration_missing", "pregame_temperature_missing",
    "current_venue_altitude_missing",
)
REST_PROXIES = (
    "short_rest_indicator", "long_travel_x_short_rest",
    "circadian_short_recovery_component", "circadian_disruption_score",
    "overnight_travel_proxy",
)
SEMANTIC_STATES = (
    "NO_OPPORTUNITY", "LOW_EXPOSURE", "NO_OBSERVATION", "INAPPLICABLE",
    "SOURCE_FAILURE", "NEW_PLAYER_OR_CHANGED_ROLE",
)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def reference(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def store(name, document):
    raw = canonical(document)
    digest = hashlib.sha256(raw).hexdigest()
    path = DEST / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable research artifact collision")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return reference(path)


def family(field):
    name, source = field["field"], field["sourceFamily"]
    if source == "ANNUAL_PLAYER_PRIOR":
        return "BATTER_ANNUAL_PRIOR" if name.startswith("batter_") else "PITCHER_ANNUAL_PRIOR"
    if source == "COMPLETED_PA_PITCH_HISTORY":
        return "BATTER_RECENT_HISTORY" if name.startswith("batter_") else "PITCHER_RECENT_HISTORY"
    if source != "TEAM_SCHEDULE_VENUE_CONTEXT":
        return source
    if "bullpen" in name:
        return "BULLPEN_WORKLOAD_AVAILABILITY"
    if "temperature" in name:
        return "WEATHER"
    if "altitude" in name:
        return "PARK_ALTITUDE"
    if any(term in name for term in ("travel", "zone", "circadian", "body_clock", "venue_coordinate")):
        return "TRAVEL_CIRCADIAN_CONTEXT"
    if any(term in name for term in ("previous_game", "rest", "played_", "games_last", "consecutive_game")):
        return "REST_RECOVERY_CONTEXT"
    return "TEAM_SCHEDULE_MATCHUP_CONTEXT"


def cell_quality(field, cell, row):
    """Exclusive evidence-quality category, separate from numeric raw presence."""
    name, source, value = field["field"], field["sourceFamily"], cell["value"]
    if not cell["supported"]:
        return CATEGORIES[5], "UNSUPPORTED_CONTRACT_CELL", "No supported source/treatment mapping."
    if any(name.endswith(suffix) for suffix in GAP_INDICATORS) and value == 1:
        return CATEGORIES[4], "SOURCE_FAILURE", "The indicator correctly records a missing source quantity; its populated 1 is not numeric coverage of that quantity."
    if source == "ANNUAL_PLAYER_PRIOR":
        if value is None or (name.endswith("prior_missing") and value == 1):
            return CATEGORIES[3], "NO_OBSERVATION_IN_FROZEN_ANNUAL_DOMAIN", "Frozen FD1 annual-domain absence is explicitly treated; no claim of zero career history or rookie status."
        return CATEGORIES[2], "OBSERVED_ELIGIBLE_PRIOR_SEASON", "Eligible prior-season source by design, not current-season skill or current health."
    if value is None:
        return CATEGORIES[3], "NO_OBSERVATION", "Explicit frozen missing treatment; no replacement observation is invented."
    if source == "COMPLETED_PA_PITCH_HISTORY" and "last250" in name and row.get("pitcher_last250_bf_count", 250) < 250:
        return CATEGORIES[1], "LOW_EXPOSURE", "All retained BF are current to the declared cutoff, but fewer than the intended 250 BF exist in the accepted-history domain."
    if source == "COMPLETED_PA_PITCH_HISTORY" and "last100" in name and row.get("batter_last100_pa_count", 100) < 100:
        return CATEGORIES[1], "LOW_EXPOSURE", "All retained PA are current to the declared cutoff, but fewer than the intended 100 PA exist in the accepted-history domain."
    if source == "TEAM_SCHEDULE_VENUE_CONTEXT" and any(name.endswith(s) for s in REST_PROXIES):
        return CATEGORIES[1], "PROXY_WITH_MISSING_RECOVERY_COMPONENT", "Scheduled start/venue proxy is available; actual game-end recovery and travel itinerary are not observed."
    if source == "SIMULATED_PA_STATE":
        return CATEGORIES[0], "DERIVED_HYPOTHETICAL_STATE", "Complete for its defined simulation state, not an observed future PA. Recomputed during simulation."
    return CATEGORIES[0], "OBSERVED_OR_DETERMINISTIC_CURRENT_DEFINITION", "Supported for its stated source grain and cutoff; this is not an assertion of predictive strength or provider publication-vintage availability."


def better_source(field):
    name, source = field["field"], field["sourceFamily"]
    if "bullpen" in name:
        return {"gapId": "PITCHER_WORKLOAD", "availability": "EXISTING_LOCAL_HISTORY_DERIVABLE", "scope": "Prior completed-game appearances, pitch counts and rest; not medical clearance or manager availability."}
    if "temperature" in name:
        return {"gapId": "PREGAME_WEATHER_ROOF", "availability": "NO_VERIFIED_PREGAME_VINTAGE", "scope": "A final-game weather description cannot establish pregame weather/roof knowledge; forward timestamped observations required."}
    if "altitude" in name:
        return {"gapId": "PARK_STATIC_AUTHORITY", "availability": "NOT_BOUND_IN_ACCEPTED_REGISTRY", "scope": "Versioned stadium altitude and roof capability require independently sourced venue authority; no invented coordinates/elevations."}
    if any(term in name for term in ("previous_game_end", "previous_game_duration", "short_recovery", "short_rest")):
        return {"gapId": "ACTUAL_RECOVERY", "availability": "CURRENT_ENDPOINT_CAPABILITY_NOT_HISTORICAL_VINTAGE", "scope": "Use separately timestamped completed-game end/duration when available; do not infer final out from scheduled start plus typical duration."}
    if source == "ANNUAL_PLAYER_PRIOR":
        return {"gapId": "SEMANTIC_PLAYER_PRIORS", "availability": "EXISTING_LOCAL_ANNUAL_AND_RECENT_HISTORY", "scope": "Fold-local role/hand/cluster pooling or carryover must be learned using authorized Development only. Recent history is not a replacement annual observation."}
    if source == "COMPLETED_PA_PITCH_HISTORY":
        return {"gapId": "PLAYER_HISTORY_EXPOSURE", "availability": "EXISTING_LOCAL_COMPLETED_HISTORY", "scope": "Reuse exact windows and coverage receipts; gaps in observed pitches remain unknown and do not become zeros."}
    if source in ("CANONICAL_IDENTITY_METADATA", "CONFIRMED_PARTICIPANT_HANDEDNESS"):
        return {"gapId": "ROSTER_LINEUP_STARTER_CLOCKS", "availability": "EXISTING_LOCAL_CURRENT_RECEIPTS", "scope": "Refresh original confirmations independently of model publication; probable starter is not confirmed availability."}
    if source == "SIMULATED_PA_STATE":
        return {"gapId": None, "availability": "NOT_AN_EXTERNAL_SOURCE_FIELD", "scope": "Preserve legal hypothetical simulator state and orientation."}
    return {"gapId": "SCHEDULE_CONTEXT", "availability": "EXISTING_LOCAL_SCHEDULE", "scope": "Already calculated from schedule/venue authority; exact start times are not actual travel or recovery observations."}


def cold_start_spec(field):
    name, source = field["field"], field["sourceFamily"]
    role = "BATTER" if name.startswith("batter_") else "PITCHER" if name.startswith("pitcher_") else "TEAM_OR_CONTEXT"
    spec = {"field": name, "order": field["order"], "featureFamily": family(field),
            "role": role, "definition": field["definition"], "entityGrain": field["entityGrain"],
            "baselineTreatment": field["frozenMissingTreatment"], "baselineAbsentTreatment": field["actualAbsentTreatment"],
            "genericMedianOrMode": False, "sourceFailureCanBecomeZero": False,
            "v19SpecificationStatus": "DECLARED_SEMANTIC_POLICY_NOT_A_FITTED_TREATMENT_CLAIM",
            "intendedUncertaintyOnly": False, "states": {}, "candidateTreatmentFamilies": []}
    if source == "ANNUAL_PLAYER_PRIOR":
        denominator = "IPouts" if name == "pitcher_whip" else "G" if name in ("pitcher_gs_per_g", "pitcher_prior_g", "pitcher_prior_gs") else "AB" if name in ("batter_avg", "batter_slg", "batter_prior_ab", "batter_prior_h", "batter_prior_2b", "batter_prior_3b", "batter_prior_hr") else "PA" if role == "BATTER" else "BFP"
        spec.update(exposureAuthority=f"Eligible annual {denominator}; distinct from all-history and rolling-window exposure", knownZeroRule="Exact zero event counts are valid only with observed applicable positive exposure; zero denominator has no empirical rate.",
                    candidateTreatmentFamilies=["FOLD_LOCAL_ROLE_HANDEDNESS_OR_ARCHETYPE_PRIOR", "PREVIOUS_SEASON_CARRYOVER_WITH_TRAINING_LEARNED_DECAY"],
                    hierarchyFallback="Player prior if supported -> training-prefix role/hand or stable archetype -> training-prefix league/role prior. This is exposure-aware probabilistic pooling, never a median observation.")
        spec["states"] = {
            "NO_OPPORTUNITY": "Verified complete annual-domain record with zero applicable denominator: preserve zero exposure and missing rate; use registered probabilistic prior, not a zero rate.",
            "LOW_EXPOSURE": "Retain exact counts; shrink component distribution using training-prefix fitted concentration/variance; preserve exposure as a legitimate mean-reliability input.",
            "NO_OBSERVATION": "Complete frozen annual domain has no eligible row: retain prior_missing and semantic prior branch. It does not establish no current PA, no career, or rookie identity.",
            "INAPPLICABLE": "Respect batting/pitching role and denominator domain; do not fill the opposite role using team or global numbers.",
            "SOURCE_FAILURE": "Absent or unverified source authority is UNKNOWN/SOURCE_FAILURE, not annual cold start; block required inference unless an explicitly fitted unknown-state model supports it.",
            "NEW_PLAYER_OR_CHANGED_ROLE": "Use verified identity and role; training-prefix role/hand hierarchy when available. No minor-league translation, injury decay, or replacement-level value without separately fitted/source-backed evidence.",
        }
    elif source == "COMPLETED_PA_PITCH_HISTORY":
        window = 100 if role == "BATTER" else 250
        denominator = "finite fastball release-speed count" if "velocity" in name else "swing count" if "whiff" in name or "swing" in name else "full pitch count, including other/unclassified" if any(x in name for x in ("usage", "pitch_count", "breaking_count", "fastball_count", "offspeed_count")) else "completed PA" if role == "BATTER" else "completed BF"
        spec.update(exposureAuthority=f"Exact accepted last-{window}-PA/BF window; estimator component exposure is {denominator}", knownZeroRule="Observed zero numerator with positive exact denominator is a valid zero. A missing pitch observation or zero denominator is not a zero rate.",
                    candidateTreatmentFamilies=["EXPOSURE_AWARE_FROZEN_COMPONENT_POSTERIOR", "FOLD_LOCAL_ROLE_OR_ARCHETYPE_POOLING"],
                    hierarchyFallback="Use verified annual/role prior plus observed component counts; never infer absent career from an empty captured window.")
        spec["states"] = {
            "NO_OPPORTUNITY": "Only after coverage is proved complete: retain exact zero exposure; do not manufacture velocity, usage or whiff rate when their denominators are zero.",
            "LOW_EXPOSURE": f"Use available counts below {window} PA/BF and their component denominators; update posterior with exposure, preserve low-exposure state and unclassified composition category.",
            "NO_OBSERVATION": "No captured measurement with nonzero PA/BF means source/measurement missingness; keep it distinct from zero opportunity.",
            "INAPPLICABLE": "Velocity with no fastballs or whiff rate with no swings has no empirical value; only a tested model-specific component prior may supply a predictive distribution.",
            "SOURCE_FAILURE": "Incomplete game/pitch coverage, unresolved identity, or late availability blocks current evidence; never count missing records as zero usage/workload.",
            "NEW_PLAYER_OR_CHANGED_ROLE": "Verified small current exposure pools toward a training-prefix role/hand/cluster prior. Return-from-absence decay needs dated evidence and Development fitting; do not invent medical or rookie state.",
        }
    else:
        spec.update(exposureAuthority="Exact event/team/calendar or simulated-state authority; no player-rate denominator", knownZeroRule="A zero must be the deterministic result of complete applicable source inputs; missing source state remains distinct.")
        spec["states"] = {
            "NO_OPPORTUNITY": "For schedule counts, zero is valid only after complete prior-window coverage; first-season/no-prior-game state remains explicit. Not applicable to required identity or legal simulator state.",
            "LOW_EXPOSURE": "Short schedule/history windows retain their actual counts and limits; do not manufacture prior games or travel.",
            "NO_OBSERVATION": "Preserve dedicated missing-state indicator and omit unsupported quantity; required event/player mapping or handedness follows explicit skip contract.",
            "INAPPLICABLE": "Preserve physical/semantic applicability: no previous venue at genuine first observation, roof/weather distinction, and hypothetical PA state not an observed future event.",
            "SOURCE_FAILURE": "Unknown schedule, end time, weather, roster or venue authority stays unknown; no typical duration, synthetic weather or global category mode.",
            "NEW_PLAYER_OR_CHANGED_ROLE": "Bind current canonical identity/roster role using observed receipts; do not infer role or availability from old historical participation alone.",
        }
        if source == "TEAM_SCHEDULE_VENUE_CONTEXT":
            spec["candidateTreatmentFamilies"] = ["SOURCE_BACKED_DETERMINISTIC_CONTEXT_WITH_EXPLICIT_UNKNOWN_STATE"]
    if source == "SIMULATED_PA_STATE":
        spec["candidateTreatmentFamilies"] = ["PRESERVE_LEGAL_SIMULATOR_STATE_NO_IMPUTATION"]
    spec["meanUncertaintyBoundary"] = "V18 exposure/reliability/posterior-SD predictors legitimately enter PA means. Any new field explicitly designated uncertainty-only must be excluded from mean feature ordering and tested by counterfactual perturbation. This specification does not relabel V18 predictors as uncertainty-only."
    assert set(spec["states"]) == set(SEMANTIC_STATES)
    return spec


def gaps():
    # Ranked research judgments, not estimated effect sizes or a statistical tournament.
    rows = [
        ("PITCHER_WORKLOAD", "Bullpen and starter workload/rest", "HIGH_PLAUSIBLE_NOT_MEASURED", "EVERY_GAME", "HIGH_WITH_COMPLETE_PRIOR_GAMES", "PRIOR_EVENTS_RECONSTRUCTABLE_VINTAGES_NOT_ESTABLISHED", "EXISTING_LOCAL_HISTORY", "LOW", "Derive appearances, pitches in prior 1/3/7 days, days since last appearance, and last-start pitch count from exact completed pitch history. Workload is not individual availability.", "PROSPECTIVE_ARCHIVE_ONLY_UNTIL_HISTORICAL_VINTAGES_ESTABLISHED"),
        ("PLAYER_HISTORY_EXPOSURE", "Exact recent player evidence and semantic priors", "HIGH_PLAUSIBLE_NOT_MEASURED", "EVERY_GAME", "HIGH_WHEN_COVERAGE_VERIFIED", "AUTHORIZED_DEVELOPMENT_COUNTS_AVAILABLE", "EXISTING_LOCAL_HISTORY_AND_ANNUAL_PRIORS", "LOW_TO_MEDIUM", "Reuse exact history; distinguish absent annual prior from real current exposure; fit any new pooling/decay inside training prefixes.", "DEVELOPMENT_EVALUATION_ONLY_ON_AUTHORIZED_EXISTING_SNAPSHOTS"),
        ("ROSTER_LINEUP_STARTER_CLOCKS", "Current roster and starter/lineup confirmation", "HIGH_PLAUSIBLE_NOT_MEASURED", "EVERY_GAME", "HIGH_FOR_RETAINED_ORIGINAL_RECEIPTS", "OLD_PUBLICATION_VINTAGES_INCOMPLETE", "EXISTING_LOCAL_CURRENT_RECEIPTS", "LOW", "Archive original observed/available clocks, latest full roster batch and explicit probable/confirmed states. Do not treat roster presence as reliever fitness.", "PROSPECTIVE_ONLY_CONTEXT_UNLESS_MATCHED_VINTAGE_EXISTS"),
        ("ACTUAL_RECOVERY", "Prior-game end and duration", "MEDIUM_PLAUSIBLE_NOT_MEASURED", "MOST_GAMES", "HIGH_ONLY_IF_FINAL_EVENT_CLOCK_RETAINED", "NOT_IN_ACCEPTED_CONTEXT_AUTHORITY", "NOT_ESTABLISHED_IN_LOCAL_CONTRACT", "MEDIUM", "Acquire/read explicit completed-game end/duration if lawful and present; never estimate actual end from average duration. Existing scheduled-start proxy stays labeled proxy.", "FORWARD_ONLY_PENDING_SOURCE_PROOF"),
        ("SCHEDULE_CONTEXT", "Schedule rest/travel", "MEDIUM_PLAUSIBLE_NOT_MEASURED", "EVERY_GAME", "HIGH_FOR_SCHEDULE_VINTAGE", "EXISTING_DERIVED_DEVELOPMENT_CONTEXT", "ALREADY_IMPLEMENTED", "LOW", "Preserve current schedule identity and timezone/coordinate registry. Actual itineraries and recovery are not implied.", "NO_NEW_NUMERIC_EVIDENCE_REQUIRED_FOR_EXISTING_DEFINITION"),
        ("PREGAME_WEATHER_ROOF", "Pregame weather and actual roof state", "MEDIUM_PLAUSIBLE_NOT_MEASURED", "WEATHER_SENSITIVE_GAMES", "UNKNOWN_WITHOUT_PREGAME_CAPTURE", "NO_MATCHED_PREGAME_VINTAGES", "NOT_VERIFIED", "MEDIUM", "Retain forward timestamped forecasts/roof announcements if established. Final-game conditions cannot be relabeled pregame evidence.", "FORWARD_ONLY_NOT_ADMITTED_TO_THIS_HISTORICAL_COMPARISON"),
        ("PARK_STATIC_AUTHORITY", "Park altitude and roof capability", "MEDIUM_PLAUSIBLE_NOT_MEASURED", "EVERY_GAME_STATIC_CONTEXT", "HIGH_IF_VERSIONED_PRIMARY_AUTHORITY", "STATIC_VERSION_MAPPING_REQUIRED", "NOT_BOUND_IN_ACCEPTED_REGISTRY", "MEDIUM", "Add only source-backed venue facts with dated identity and source rights. Roof capability is not actual open/closed state.", "UNSUPPORTED_UNTIL_VERSIONED_SOURCE_BOUND"),
        ("CATCHER_EFFECTS", "Catcher identity and defense/framing", "MEDIUM_PLAUSIBLE_NOT_MEASURED", "EVERY_GAME", "IDENTITY_REQUIRES_PREGAME_LINEUP", "HISTORICAL_CATCHER_IDS_NOT_PREGAME_VINTAGES", "SOURCE_SCHEMA_DOCUMENTS_FIELDER_2", "MEDIUM_TO_HIGH", "Savant fielder_2 identifies the catcher per pitch; that does not prove the catcher was known pregame or supply a fitted catcher effect. Not in the 246-field V18 contract.", "NOT_IMPLEMENTED_IN_BOUNDED_CURRENT_FEATURE_CONTRACT"),
        ("TRANSACTION_RETURN_STATE", "Transactions, injury and return-from-absence", "MEDIUM_PLAUSIBLE_NOT_MEASURED", "SUBSET_OF_GAMES", "REQUIRES_PUBLISHED_AND_EFFECTIVE_DATES", "HISTORICAL_PUBLICATION_VINTAGES_UNVERIFIED", "CURRENT_ROSTER_ONLY_CONFIRMED", "MEDIUM_TO_HIGH", "Roster batch differences identify observed membership changes, not injury cause, transaction publication time or medical clearance.", "FORWARD_ONLY_PENDING_EXACT_SOURCE_RECEIPTS"),
        ("UMPIRE_CONTEXT", "Pregame umpire evidence", "UNKNOWN_NOT_MEASURED", "EVERY_GAME", "UNVERIFIED", "NO_VALID_TIMED_UMPIRE_FAMILY", "SAVANT_UMPIRE_FIELD_DEPRECATED", "HIGH", "Do not infer missing pregame umpire from deprecated CSV field or current final box score.", "UNSUPPORTED"),
    ]
    names = ("gapId", "family", "likelyPredictiveValue", "frequency", "pointInTimeReliability", "historicalReconstructability", "currentAvailability", "implementationCost", "smallestAction", "researchAdmission")
    return [{"priority": i, **dict(zip(names, row)), "rankingBasis": "Pre-result qualitative scientific judgment; not empirically estimated lift", "sourceRights": "Existing project authority only: LOCAL_PRIVATE_MODEL_DEVELOPMENT; Statcast GOVERNED_LOCAL_RESEARCH_ONLY; attribution and commercial review remain required; no raw redistribution permission inferred."} for i, row in enumerate(rows, 1)]


def roster_quality(game):
    """Diagnose original membership evidence without rewriting old selections."""
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    roster = game["originalSourceEvidence"]["roster"]
    latest = {side: max(parse(r["source"]["observedAt"]) for r in roster if r["side"] == side) for side in ("HOME", "AWAY")}
    result = []
    for member in roster:
        observed = parse(member["source"]["observedAt"])
        superseded = observed < latest[member["side"]]
        result.append({"canonicalPlayerId": member["canonicalPlayerId"], "mlbamId": member["mlbamId"],
                       "side": member["side"], "originalObservedAt": member["source"]["observedAt"],
                       "sourceAgeHoursAtForecast": (parse(game["forecastCreatedAt"]) - observed).total_seconds() / 3600,
                       "membershipQuality": "OLDER_THAN_LATEST_RETAINED_TEAM_BATCH_CURRENT_MEMBERSHIP_UNPROVEN" if superseded else "LATEST_RETAINED_TEAM_BATCH_CANDIDATE_NOT_AVAILABILITY",
                       "historicalPlayerMetricsRemainObserved": True,
                       "interpretation": "Membership vintage is separate from the quality of that player's historical statistics. This audit preserves the original forecast and does not repair it retrospectively."})
    return result


def build():
    raw = INPUT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUT_SHA:
        raise ValueError("Original operational audit checksum mismatch")
    old = json.loads(raw)
    assert old["fieldCount"] == 246 and len(old["publishedGames"]) == 2
    fields = sorted(old["fields"], key=lambda f: f["order"])
    assert [f["order"] for f in fields] == list(range(246))
    game_lookup = {g["gameId"]: g for g in old["publishedGames"]}
    row_values = defaultdict(dict)
    for field in fields:
        for gid, game in field["perGame"].items():
            for cell in game["cells"]:
                row_values[(gid, cell["templateId"])][field["field"]] = cell["value"]
    sources, audit_fields = {}, []
    counters = {gid: {"cells": Counter(), "fields": Counter(), "families": defaultdict(Counter)} for gid in game_lookup}
    for field in fields:
        per_game = {}
        for gid, observed in field["perGame"].items():
            cells = []
            for cell in observed["cells"]:
                category, state, reason = cell_quality(field, cell, row_values[(gid, cell["templateId"])])
                source_ids = []
                for source in cell["sourceEvidence"]:
                    sid = hashlib.sha256(canonical(source)).hexdigest()
                    source_ids.append(sid)
                    sources[sid] = {"originalEvidence": source, "observedAt": source.get("observedAt"),
                                    "availableAsOf": source.get("availableAsOf"), "ingestedAt": source.get("ingestedAt"),
                                    "retrievedAt": source.get("retrievedAt"), "providerPublishedAt": source.get("providerPublishedAt"),
                                    "retrievalClockInterpretation": "Only an explicitly supplied retrieval field is populated here; ingestion/observation is preserved without being relabeled provider publication time."}
                cells.append({"templateId": cell["templateId"], "actualRawValue": cell["value"], "qualityCategory": category,
                              "semanticState": state, "qualityReason": reason, "sourceEvidenceRefs": source_ids,
                              "frozenTreatmentApplied": cell["treatmentApplied"],
                              "recordedTreatedOutputsForAbsentStartingRow": cell["recordedTreatedOutputsForAbsentStartingRow"]})
                counters[gid]["cells"][category] += 1
                counters[gid]["families"][family(field)][category] += 1
            counts = Counter(c["qualityCategory"] for c in cells)
            # Conservative field-level rule: any poorer-than-current evidence
            # is represented, but annual mixed domains keep their prior design.
            if field["sourceFamily"] == "ANNUAL_PLAYER_PRIOR":
                primary = CATEGORIES[2] if counts[CATEGORIES[2]] else CATEGORIES[3]
            else:
                primary = next(c for c in reversed(CATEGORIES) if counts[c])
            counters[gid]["fields"][primary] += 1
            per_game[gid] = {"fieldQualityCategory": primary, "categoryCellCounts": {c: counts[c] for c in CATEGORIES},
                             "mixedEvidenceStates": len(counts) > 1, "rawNullCount": observed["absentCount"],
                             "templateCount": len(cells), "forecastCreatedAt": game_lookup[gid]["forecastCreatedAt"],
                             "evidenceCutoff": game_lookup[gid]["evidenceCutoff"], "cells": cells}
        audit_fields.append({k: field[k] for k in ("order", "field", "definition", "entityGrain", "sourceFamily", "lookbackWindow", "transformation", "actualAbsentTreatment", "frozenMissingTreatment", "numericalRole")} | {
            "featureFamily": family(field), "betterFreeSource": better_source(field), "perGame": per_game,
            "frozenV18Changed": False, "uncertaintyOnly": False,
            "structurallyUnavailableInOriginalContract": False,
            "qualityDoesNotEstablishEffectSize": True})
    summary = []
    for gid, counts in counters.items():
        game = game_lookup[gid]
        assert sum(counts["cells"].values()) == 246 * 34 and sum(counts["fields"].values()) == 246
        summary.append({"gameId": gid, "sourceGameId": game["sourceGameId"], "teams": game["teams"],
                        "forecastObjectSha256": game["forecastObject"]["objectSha256"],
                        "forecastCreatedAt": game["forecastCreatedAt"], "evidenceCutoff": game["evidenceCutoff"],
                        "fieldCounts": {c: counts["fields"][c] for c in CATEGORIES},
                        "cellCounts": {c: counts["cells"][c] for c in CATEGORIES},
                        "familyCellCounts": {f: {c: cs[c] for c in CATEGORIES} for f, cs in sorted(counts["families"].items())},
                        "actualNullRawCells": game["rawNullCellCount"], "participants": game["participants"],
                        "rosterEvidence": game["originalSourceEvidence"]["roster"],
                        "rosterMembershipQuality": roster_quality(game),
                        "starterConfirmation": "PROBABLE_NOT_CONFIRMED", "orderedLineups": "CONFIRMED_STARTING_ORDER_ONLY_NO_BENCH_MODEL"})
    audit = {"schemaVersion": "MLB_V19_V18_CURRENT_FEATURE_QUALITY_AUDIT_V1", "predecessor": reference(INPUT),
             "readScope": "One retained operational audit only; no source history, Final OOT, database or estimator payload is opened.",
             "providerDataCalls": 0, "providerCostUsd": 0, "modelFits": 0, "finalOotPayloadReads": 0,
             "fieldCount": 246, "gameCount": 2, "templateCountPerGame": 34,
             "categoryDefinitions": {CATEGORIES[0]: "Complete for the exact current/static/hypothetical definition; not evidence of effect size or full current team condition.", CATEGORIES[1]: "Current evidence with an incomplete target history window or explicitly approximate recovery observation.", CATEGORIES[2]: "Frozen annual prior observed in its eligible historical season, not current-season strength.", CATEGORIES[3]: "Verified absence in an authorized semantic domain; source failure is not recoded cold start.", CATEGORIES[4]: "A numeric evidence family is absent and its correct missing indicator is populated; this is not numeric-source coverage.", CATEGORIES[5]: "No supported source/semantic mapping."},
             "countingRule": "Cell counts are exclusive across 246 fields x 34 source templates per game. Field counts are conservative: annual domains retain HISTORICAL_PRIOR_BY_DESIGN while their absent cells are separately enumerated; other fields take the least-current cell state. Field and cell counts must not be added. Repeated templates are not distinct players.",
             "hypotheticalStateCaveat": "Five state fields are complete simulator initial conditions; they are never observations of an unplayed game.",
             "identityFreshnessCaveat": "Observed player history does not prove current staff membership. Original roster batch quality is diagnosed separately per game, without relabeling historical player measurements as unavailable.",
             "sourceClockCatalog": sources, "games": summary, "fields": audit_fields,
             "outOfContractFamilies": [
                 {"family": "BULLPEN_INDIVIDUAL_AVAILABILITY", "status": "UNSUPPORTED", "reason": "Active staff quality and historical workload do not establish actual medical/manager availability."},
                 {"family": "CATCHER_EFFECT", "status": "UNSUPPORTED", "reason": "No catcher-effect input or fitted contract among 246 raw fields."},
                 {"family": "ACTUAL_ROOF_STATE", "status": "UNSUPPORTED", "reason": "No pregame roof observation or fitted raw field."},
                 {"family": "UMPIRE", "status": "UNSUPPORTED", "reason": "No timestamp-compatible pregame umpire evidence or raw field; Savant umpire field deprecated."},
                 {"family": "TRANSACTION_INJURY_RETURN_STATE", "status": "UNSUPPORTED", "reason": "Current active roster is not a dated transaction/injury history and cannot identify reason for absence."},
                 {"family": "ROOKIE_MINOR_LEAGUE_TRANSLATION", "status": "UNSUPPORTED", "reason": "No fitted source-backed translation; annual-domain absence is not rookie identity."},
             ], "outOfContractCountingRule": "These six limitations are outside 246 and are not inserted into its denominator."}
    cold = {"schemaVersion": "MLB_V19_PER_FEATURE_SEMANTIC_COLD_START_SPEC_V1", "predecessor": reference(INPUT),
            "scope": "A field-complete semantic design and exact baseline-treatment map, not a claim that every proposed new prior was fitted.",
            "stateOrder": SEMANTIC_STATES, "fields": [cold_start_spec(f) for f in fields],
            "unsupportedProposals": ["No minor-league translation fitted", "No injury/return decay without dated source", "No unverified replacement-level scalar", "No global median/mode"],
            "uncertaintyRule": {"baselineUncertaintyOnlyRawFieldCount": 0, "newIntendedUncertaintyOnlyFields": "Must be stored outside ordered mean-prediction contract; any perturbation must produce byte-identical probability/score means with fixed seeds.", "legitimateMeanInputs": "Exposure and reliability used in shrinkage remain supported mean inputs, not uncertainty-only flags."}}
    gaps_doc = {"schemaVersion": "MLB_V19_RANKED_SOURCE_GAPS_V1", "predecessor": reference(INPUT),
                "ranking": gaps(), "documentationReview": [
                    {"url": "https://baseballsavant.mlb.com/csv-docs", "finding": "Documents pitcher/game/PA/pitch identities, release speed, catcher fielder_2 and previous-game interval. Umpire is deprecated. Days-until-next-game is future-dependent and prohibited as a pregame predictor."},
                    {"url": "https://www.mlb.com/official-information/terms-of-use", "finding": "Public documentation availability does not grant unrestricted commercial rights; preserve existing restricted project authority."}],
                "documentationPageOpens": 2, "providerDataRequests": 0, "costUsd": 0,
                "rights": {"status": "GOVERNED_LOCAL_RESEARCH_ONLY", "usage": "LOCAL_PRIVATE_MODEL_DEVELOPMENT", "attributionRequired": True, "commercialRightsReviewRequired": True, "rawRedistributionAuthority": False},
                "implementationStatus": "Source implementations and their actual coverage are recorded separately by the V19 source-additions receipt; this ranking does not claim an endpoint field is ingested."}
    artifacts = {"qualityAudit": store("feature-quality.json", audit), "coldStartSpecification": store("cold-start-specification.json", cold), "rankedSourceGaps": store("ranked-source-gaps.json", gaps_doc)}
    manifest = {"schemaVersion": "MLB_V19_FEATURE_QUALITY_MANIFEST_V1", "artifacts": artifacts,
                "predecessor": reference(INPUT), "producer": reference(Path(__file__).resolve()),
                "fieldCount": 246, "gameCount": 2, "cellCount": 16728,
                "games": [{k: g[k] for k in ("gameId", "fieldCounts", "cellCounts", "actualNullRawCells")} for g in summary],
                "operationalV18Modified": False, "researchShadowOnly": True, "wageringAuthority": False,
                "providerDataRequests": 0, "finalOotPayloadReads": 0}
    return {"manifest": store("manifest.json", manifest), **artifacts, "games": manifest["games"]}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))

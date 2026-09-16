"""Read-only comparison of independently generated, saved current NFL laws.

No simulator/model execution, fitting, outcomes, or calibration are involved.
The current-state score law does not generate or explain the saved play paths.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from server.audit_assurance.canonical import canonical_json_bytes
from .labs_simulation import AUTHORITY, file_record, immutable_json, verify_object, utc

ROOT = Path(__file__).resolve().parents[2]
PLAY_HANDOFF = ROOT / "outputs/nfl-play-level-engine-v1/sha256/654b4a8b3850a040d237f66309e247a89de2fc276477995306c886a49142f8c0/handoff.json"
PLAY_HANDOFF_SHA256 = "654b4a8b3850a040d237f66309e247a89de2fc276477995306c886a49142f8c0"
CONTRACT = "NFL_CURRENT_STATE_VERSUS_INDEPENDENT_PLAY_BASE_V2"
FIELDS = ("expectedHomeScore", "expectedAwayScore", "expectedMarginHomeMinusAway", "expectedTotal",
          "homeWinProbability", "awayWinProbability", "tieProbability")


def _read(ref):
    observed = file_record(Path(ref["path"]))
    if observed != {key: ref[key] for key in ("path", "sha256", "byteCount")}:
        raise ValueError("LAW_COMPARISON_HANDOFF_CHECKSUM_DIFFERS")
    body = json.loads(Path(ref["path"]).read_bytes())
    if any(body.get(key) != value for key, value in AUTHORITY.items()):
        raise ValueError("LAW_COMPARISON_RESEARCH_AUTHORITY_DIFFERS")
    return body


def _identity(artifact):
    return (artifact["eventId"], artifact["homeTeam"]["teamId"],
            artifact["awayTeam"]["teamId"], utc(artifact["scheduledStartUtc"]).isoformat())


def _summary(artifact):
    values = {field: float(artifact["scoreSummary"][field]) for field in FIELDS}
    if not np.isfinite(list(values.values())).all():
        raise ValueError("NONFINITE_SAVED_DISTRIBUTION_SUMMARY")
    if abs(values["expectedHomeScore"] + values["expectedAwayScore"] - values["expectedTotal"]) > 1e-9:
        raise ValueError("SAVED_EXPECTED_TOTAL_DOES_NOT_RECONCILE")
    if abs(values["expectedHomeScore"] - values["expectedAwayScore"] - values["expectedMarginHomeMinusAway"]) > 1e-9:
        raise ValueError("SAVED_EXPECTED_MARGIN_DOES_NOT_RECONCILE")
    return values


def compare_current_with_play_base(new_handoff_ref: dict, output: Path,
                                  *, play_handoff: Path = PLAY_HANDOFF) -> dict:
    """Return an immutable comparison reference; both source bundles untouched."""
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()) or output == ROOT / "outputs":
        raise ValueError("COMPARISON_OUTPUT_REQUIRES_DEDICATED_MODEL_STUDIO_DIRECTORY")
    play_ref = file_record(Path(play_handoff))
    if play_ref["sha256"] != PLAY_HANDOFF_SHA256:
        raise ValueError("EXACT_ACCEPTED_PLAY_HANDOFF_REQUIRED")
    old, new = _read(play_ref), _read(new_handoff_ref)
    if old.get("schemaVersion") != "NFL_PLAY_LEVEL_HANDOFF_V1" or new.get("schemaVersion") != "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2":
        raise ValueError("UNSUPPORTED_LAW_COMPARISON_HANDOFF_CONTRACT")
    references, effects = old["artifacts"], old["scenarioEffects"]
    if len(references) != len(effects) or any(ref["eventId"] != effect["eventId"] for ref, effect in zip(references, effects)):
        raise ValueError("PLAY_SCENARIO_INDEX_NOT_ALIGNED")
    # The accepted publisher appends these arrays together in both new/reused
    # paths. The index selects candidates; each selected artifact must itself
    # prove BASE. Other scenario payloads are not opened.
    bases = {}
    for ref, effect in zip(references, effects):
        if effect["scenarioId"] != "BASE":
            continue
        artifact = verify_object(ref)
        if artifact.get("schemaVersion") != "NFL_LABS_PLAY_LEVEL_SIMULATION_V1" or artifact.get("scenario", {}).get("scenarioId") != "BASE":
            raise ValueError("SELECTED_PLAY_ARTIFACT_IS_NOT_BASE")
        event = artifact["eventId"]
        if event in bases:
            raise ValueError("DUPLICATE_PLAY_BASE_EVENT")
        summary = _summary(artifact)
        if any(abs(summary[field] - float(effect["scoreSummary"][field])) > 1e-12 for field in FIELDS):
            raise ValueError("PLAY_BASE_SUMMARY_DIFFERS_FROM_HANDOFF")
        bases[event] = (ref, artifact, summary)
    rows, unmatched = [], []
    seen = set()
    for ref in new["artifacts"]:
        artifact = verify_object(ref)
        component = artifact["model"]["engineId"]
        key = (artifact["eventId"], component)
        if key in seen:
            raise ValueError("DUPLICATE_CURRENT_EVENT_MODEL")
        seen.add(key)
        if artifact.get("schemaVersion") != "NFL_LABS_SCORE_DISTRIBUTION_V1" or artifact.get("scenario", {}).get("scenarioId") != "BASE":
            raise ValueError("CURRENT_COMPARISON_REQUIRES_BASE_SCORE_DISTRIBUTION")
        event = artifact["eventId"]
        if event not in bases:
            unmatched.append({"eventId": event, "modelId": component, "reason": "NO_EXACT_PLAY_BASE_EVENT_ID"})
            continue
        old_ref, old_artifact, old_summary = bases[event]
        # A source-event alias is not silently treated as identity equivalence.
        if _identity(artifact) != _identity(old_artifact):
            raise ValueError(f"MATCHED_EVENT_TEAM_OR_KICKOFF_IDENTITY_DIFFERS:{event}")
        if component == old_artifact["model"]["engineId"]:
            raise ValueError("COMPARISON_REQUIRES_DISTINCT_ENGINE_IDENTITIES")
        current = _summary(artifact)
        rows.append({"eventId": event, "currentModelId": component,
            "independentPlayModelId": old_artifact["model"]["engineId"],
            "comparisonStatus": "NOT_COUPLED_NOT_CALIBRATED_TO_MATCH",
            "evidenceClass": "OBSERVED_AS_OF",
            "observationMeaning": "COMPARISON_OF_SAVED_CURRENT_FORECAST_DISTRIBUTIONS_NOT_GAME_OUTCOME_EVIDENCE",
            "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF",
            "currentForecastId": artifact["forecastId"], "independentPlayForecastId": old_artifact["forecastId"],
            "currentArtifact": ref, "independentPlayBaseArtifact": old_ref,
            "currentCreatedUtc": artifact["forecastCreatedUtc"], "playCreatedUtc": old_artifact["forecastCreatedUtc"],
            "currentSourceCutoffUtc": artifact["sourceCutoffUtc"], "playSourceCutoffUtc": old_artifact["sourceCutoffUtc"],
            "current": current, "independentPlayBase": old_summary,
            "currentMinusIndependentPlayBase": {field: current[field] - old_summary[field] for field in FIELDS}})
    unmatched_play = sorted(set(bases) - {row["eventId"] for row in rows})
    record = {"contract": CONTRACT, "schemaVersion": CONTRACT, **AUTHORITY,
        "evidenceClass": "OBSERVED_AS_OF", "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF",
        "comparisonStatus": "NOT_COUPLED_NOT_CALIBRATED_TO_MATCH", "currentHandoff": new_handoff_ref,
        "independentPlayHandoff": play_ref, "matchedEventCount": len({row["eventId"] for row in rows}),
        "matchedEventModelRows": len(rows), "rows": rows, "unmatchedCurrent": unmatched,
        "playEventsWithoutCurrentForecast": unmatched_play, "modelsExecuted": 0, "modelsFit": 0,
        "calibrationFits": 0, "newPlayPaths": 0, "actualGameOutcomesRead": False, "sealed2025Read": False,
        "limitations": ["Differences are disagreement between distinct saved generating laws, not an estimate of accuracy or a wagering edge.",
            "Different source cutoffs, training authorities, draw counts and forecast creation times are retained; the laws are not forced to agree.",
            "The current score model has not conditioned, regenerated or explained the independent play-engine BASE paths."]}
    digest = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    return immutable_json(output / "sha256" / digest / "comparison.json", record)

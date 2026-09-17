"""Current-source V18 execution and immutable publication; never historical templates.

Source capture/calculation is deliberately outside the estimator. This publisher
accepts only a complete, evidenced composition, or writes an explicit skip. It
loads no training population, changes no model parameters and writes no AISP data.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd

from server.sports_phase5.base_out_transition import TransitionModel
from server.sports_modeling.metrics import PA_CLASS_ORDER
from . import mlb_v18_daily_slate as daily
from .mlb_v18_current_slate import ROOT, load_contract, reference, sha_file, utc, write_object
from .mlb_v18_whole_game_challenger import (
    V18StateProbabilityProvider, compose_raw_template, simulate_prospective_game,
)
from .mlb_v18_player_prop_sidecar import PlayerPropCollector
from .mlb_v18_player_prop_prospective_capture import (
    FailOpenPlayerPropObserver,
    OUTPUT_NAME as PLAYER_PROP_CAPTURE_OUTPUT_NAME,
    existing_capture as existing_player_prop_capture,
    finalize_and_register as finalize_player_prop_capture,
    planned_forecast_manifest,
    write_failure_receipt as write_player_prop_capture_failure,
)

OUTPUT = (ROOT / "outputs/mlb-v18-current-state-pipeline-v1").resolve()
RESEARCH = {**daily.RESEARCH_FLAGS, "status": "RESEARCH_SHADOW"}
PUBLICATION_SAFETY_MARGIN = timedelta(minutes=5)


def _require_publication_window(snapshot):
    """Reserve five minutes for bounded persistence before actual first pitch."""
    now, start = datetime.now(timezone.utc), utc(snapshot["game"]["starts_at"])
    if now >= start:
        raise daily.DailySlateError("GAME_ALREADY_STARTED", "No new inference or publication after first pitch")
    if now + PUBLICATION_SAFETY_MARGIN >= start:
        raise daily.DailySlateError("PUBLICATION_SAFETY_CUTOFF_REACHED",
            "New inference and publication close five minutes before first pitch")


def _forecast_evidence_cutoff(forecast):
    cutoff = forecast.get("sourceCutoff")
    if isinstance(cutoff, Mapping):
        return cutoff.get("snapshotCapturedAt") or forecast["capturedAt"]
    return cutoff or forecast["capturedAt"]


def current_template(*, source_order, batter_row, pitcher_row, state):
    """Compose exactly the saved numeric features while retaining both identities.

    The historical composer took the pitcher identity from the batter template.
    Current evidence binds the actual opposing pitcher (including staff members)
    and creates a hypothetical PA identity, never an observed or historical PA.
    """
    if batter_row["canonicalGameId"] != pitcher_row["canonicalGameId"] or batter_row["game_date"] != pitcher_row["game_date"]:
        raise ValueError("CURRENT_MATCHUP_EVENT_IDENTITY_MISMATCH")
    result = compose_raw_template(source_order=source_order, batter_row=batter_row, pitcher_row=pitcher_row, state=state)
    batter = str(batter_row["batterCanonicalPlayerId"])
    pitcher = str(pitcher_row["pitcherCanonicalPlayerId"])
    result.loc[:, "pitcherCanonicalPlayerId"] = pitcher
    result.loc[:, "canonicalPaId"] = f"HYPOTHETICAL:{batter_row['canonicalGameId']}:{batter}:{pitcher}:{state['context_top_bottom']}"
    if result["matchup_batter_hand_missing"].iloc[0] == 1 or result["matchup_pitcher_hand_missing"].iloc[0] == 1:
        # Accepted Gold uses zero advantage plus explicit missing-hand flags;
        # this is unknown handedness, not an inferred left/right identity.
        result.loc[:, "matchup_platoon_advantage"] = 0
    return result


def _source_identity(value):
    """Operational polling clocks cannot create another evidentiary state."""
    if isinstance(value, dict):
        return {key: _source_identity(item) for key, item in value.items() if key not in {
            "capturedAt", "capturedAtUtc", "asOfUtc", "generatedAt", "existingForecastMetadata",
            "snapshotContentSha256", "contentSha256", "runtimeSeconds", "queryReceipts", "snapshotCapturedAt",
            "_operationalSourceCapability",
        }}
    if isinstance(value, list):
        return [_source_identity(item) for item in value]
    return daily.json_safe(value)


def _fixed_object(root, key, body):
    """Append-only lookup: unchanged evidence reuses its original timestamped object."""
    pointer = root / "evidence-keys" / f"{key}.json"
    if pointer.exists():
        record = json.loads(pointer.read_text(encoding="utf-8"))
        path = Path(record["path"])
        if sha_file(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
            raise ValueError("CURRENT_STATE_SNAPSHOT_CHECKSUM_MISMATCH")
        return record, True
    record, _ = write_object(root, "feature-snapshot.json", daily.json_safe(body))
    pointer.parent.mkdir(parents=True, exist_ok=True)
    with pointer.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True, separators=(",", ":"))
    return record, False


def _numeric_value(value):
    """Canonical numerical equality: JSON 1/1.0 and missing scalars are equal."""
    value = daily.json_safe(value)
    if isinstance(value, dict):
        return {key: _numeric_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_numeric_value(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("CURRENT_NUMERICAL_INPUT_MUST_BE_FINITE_OR_NULL")
        if value.is_integer():
            return int(value)
    return value


def numerical_input_identity(snapshot, composition, contract=None):
    """Bind eligible feature values and frozen execution, never producer metadata.

    Retain ordered participants and all registered raw fields, including missing
    values consumed by the frozen treatment. Extra provider-row provenance is
    retained in evidence but cannot change numerical forecast identity.
    """
    order = (contract or load_contract())["rawFeatureColumns"]
    inputs = composition["providerInputs"]
    required = {"awayBatters", "homeBatters", "awayStarter", "homeStarter", "awayBullpen", "homeBullpen"}
    if set(inputs) != required:
        raise ValueError("CURRENT_PROVIDER_INPUT_CONTRACT_MISMATCH")
    def row_values(row):
        if not isinstance(row, Mapping) or set(order) - set(row):
            raise ValueError("CURRENT_PROVIDER_ROW_MUST_RETAIN_ALL_246_RAW_FIELDS")
        return [row[name] for name in order]
    provider = {name: [row_values(row) for row in value] if isinstance(value, list) else row_values(value)
                for name, value in inputs.items()}
    return daily.sha_json(_numeric_value({
        "schemaVersion": "MLB_V18_ELIGIBLE_NUMERICAL_INPUT_IDENTITY_V2",
        "gameId": snapshot["game"]["game_id"],
        "scheduledStart": utc(snapshot["game"]["starts_at"]).isoformat(),
        "scheduledInnings": int(snapshot["game"].get("scheduled_innings") or 9),
        "rawFeatureOrder": order, "rawRows": [row_values(row) for row in composition["rows"]],
        "providerInputs": provider, "modelSha256": daily.PA_MODEL_SHA256,
        "transitionSha256": daily.TRANSITION_MODEL_SHA256,
        "treatmentSha256": daily.TREATMENT_MANIFEST_SHA256,
        "parentBundleSha256": daily.PARENT_BUNDLE_SHA256,
        "providerCacheSemantics": "ONE_ROW_TRANSFORM_PER_TEMPLATE_V1",
        "seed": daily.MASTER_SEED, "simulations": daily.SIMULATION_COUNT,
    }))


def _validate_eligible_inputs(snapshot, composition):
    """A cache hit never substitutes for validating this capture's eligibility."""
    daily.validate_pregame_snapshot(snapshot)
    cutoff = utc(snapshot["capturedAt"])
    if cutoff > datetime.now(timezone.utc):
        raise ValueError("CURRENT_SOURCE_CAPTURE_IS_IN_THE_FUTURE")
    sides = {side["side"]: side for side in snapshot["sides"]}
    for side in sides.values():
        if side["lineupAuthority"].get("status") != "CONFIRMED":
            raise ValueError("CURRENT_CONFIRMED_ORDERED_LINEUP_UNAVAILABLE")
        for source in (side["starter"], side["lineupAuthority"]):
            if not source.get("observedAt") or not source.get("ingestedAt"):
                raise ValueError("CURRENT_PARTICIPANT_ORIGINAL_CLOCKS_REQUIRED")
            if not utc(source["observedAt"]) <= utc(source["availableAsOf"]) <= cutoff:
                raise ValueError("CURRENT_PARTICIPANT_AVAILABILITY_CLOCK_INVALID")
            if utc(source["ingestedAt"]) > cutoff:
                raise ValueError("CURRENT_PARTICIPANT_INGESTED_AFTER_CUTOFF")
    event = composition.get("event", {})
    if event.get("canonicalGameId", snapshot["game"]["game_id"]) != snapshot["game"]["game_id"]:
        raise ValueError("CURRENT_COMPOSITION_EVENT_IDENTITY_MISMATCH")
    for source_cutoff in (composition.get("sourceCutoff"), event.get("sourceCutoff")):
        clocks = (source_cutoff.get("snapshotCapturedAt"), source_cutoff.get("evidenceAvailableAt")) if isinstance(source_cutoff, Mapping) else (source_cutoff,)
        if any(value and utc(value) > cutoff for value in clocks):
            raise ValueError("CURRENT_COMPOSITION_SOURCE_CUTOFF_INVALID")
    for row in composition["rows"]:
        if row["canonicalGameId"] != snapshot["game"]["game_id"]:
            raise ValueError("CURRENT_COMPOSITION_EVENT_IDENTITY_MISMATCH")
    # These reports bind the composed canonical IDs to the current MLB IDs and
    # batting slots. Numeric equality alone must not bless a changed lineup.
    for report in composition.get("fieldReports", []):
        if report.get("rosterSide"):
            continue
        batting_side = report["battingSide"]
        opponent = "HOME" if batting_side == "AWAY" else "AWAY"
        order = int(report["battingOrder"])
        if (not 1 <= order <= 9
                or str(report["batterMlbamId"]) != str(sides[batting_side]["lineup"][order-1]["mlbam"])
                or str(report["pitcherMlbamId"]) != str(sides[opponent]["starter"]["mlbamId"])):
            raise ValueError("CURRENT_COMPOSITION_PARTICIPANT_BINDING_MISMATCH")
    # Composition already verifies source-family completeness. Recheck all
    # retained original clocks before authorizing reuse of its numeric values.
    def verify_clocks(value):
        if isinstance(value, Mapping):
            available = value.get("availableAsOf")
            observed = value.get("observedAt")
            ingested = value.get("ingestedAt")
            if ((available and utc(available) > cutoff) or (observed and utc(observed) > cutoff)
                    or (ingested and utc(ingested) > cutoff)
                    or (available and observed and utc(observed) > utc(available))):
                raise ValueError("CURRENT_COMPOSITION_SOURCE_CLOCK_INVALID")
            for item in value.values():
                verify_clocks(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                verify_clocks(item)
    verify_clocks(composition)


def _verified_forecast(root, pointer):
    directory = daily._verify_existing_object(root, pointer)
    forecast = json.loads((directory / "forecast.json").read_text(encoding="utf-8"))
    execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
    feature = execution.get("featureSnapshot") or {}
    if (not feature or reference(feature["path"]) != {
            key: feature[key] for key in ("path", "sha256", "bytes")}):
        raise ValueError("CURRENT_FORECAST_FEATURE_SNAPSHOT_CHECKSUM_MISMATCH")
    # Existing timestamps stay immutable; capturedAt alone is not publication.
    if not forecast.get("forecastCreatedAt") or not (
            utc(forecast["capturedAt"]) <= utc(forecast["forecastCreatedAt"]) < utc(forecast["scheduledStart"])):
        raise ValueError("CURRENT_EXISTING_FORECAST_PUBLICATION_CLOCK_INVALID")
    return directory, forecast


def _reuse_numerical_forecast(root, numeric, snapshot, contract):
    pointer_path = root / "numerical-keys-v2" / f"{numeric}.json"
    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        directory, forecast = _verified_forecast(root, pointer)
        execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
        evidence = json.loads((directory / "pregame-evidence.json").read_text(encoding="utf-8"))
        original = {"rows": execution["rawTemplates"], "providerInputs": execution["providerInputs"]}
        if (forecast["gameId"] != snapshot["game"]["game_id"]
                or numerical_input_identity(evidence, original, contract) != numeric):
            raise ValueError("CURRENT_NUMERICAL_KEY_INPUT_BINDING_MISMATCH")
        return pointer, forecast
    # Read legacy indices without changing them. Recompute identity from each
    # matching game's authenticated original inputs, including regulation length
    # (which the legacy key omitted). This adds an alias, never a forecast version.
    candidates = [json.loads(path.read_text(encoding="utf-8"))
                  for path in sorted((root / "numerical-keys").glob("*.json"))]
    indexed = {pointer["objectSha256"] for pointer in candidates}
    # A restart can occur after the forecast directory is committed but before
    # its numerical index is written. Recover that object instead of rescoring.
    for path in sorted((root / "objects" / "sha256").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("gameId") == snapshot["game"]["game_id"] and manifest.get("objectSha256") not in indexed:
            candidates.append({"publicationKey": manifest["publicationKey"],
                "objectSha256": manifest["objectSha256"], "relativePath": path.parent.relative_to(root).as_posix()})
    for pointer in candidates:
        directory = root / pointer["relativePath"]
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("gameId") != snapshot["game"]["game_id"]:
            continue
        directory, forecast = _verified_forecast(root, pointer)
        parent = forecast.get("parentAuthority", {})
        if (parent.get("paModelSha256") != daily.PA_MODEL_SHA256
                or parent.get("transitionModelSha256") != daily.TRANSITION_MODEL_SHA256
                or parent.get("bundleSha256") != daily.PARENT_BUNDLE_SHA256
                or forecast.get("simulation", {}).get("seed") != daily.MASTER_SEED
                or forecast.get("simulation", {}).get("count") != daily.SIMULATION_COUNT):
            continue
        execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
        if execution.get("modelIdentity", {}).get("treatmentManifestSha256") != daily.TREATMENT_MANIFEST_SHA256:
            continue
        evidence = json.loads((directory / "pregame-evidence.json").read_text(encoding="utf-8"))
        old_composition = {"rows": execution["rawTemplates"], "providerInputs": execution["providerInputs"]}
        if numerical_input_identity(evidence, old_composition, contract) == numeric:
            pointer_path.parent.mkdir(parents=True, exist_ok=True)
            with pointer_path.open("x", encoding="utf-8") as stream:
                json.dump(pointer, stream, sort_keys=True, separators=(",", ":"))
            return pointer, forecast
    return None


def _player_window_identity(snapshot, composition, row, role):
    """Exact accepted last-N source proof, independent of other selected players."""
    history = composition.get("sourceEvidence", {}).get("history", {})
    selection = history.get("windowSelectionProof", {})
    source = selection.get("identity", {})
    player = row.get(role + "CanonicalPlayerId")
    proofs = [proof for proof in selection.get("rows", [])
              if proof.get("playerId") == player and proof.get("role") == role]
    if len(proofs) != 1 or not all(source.get(key) for key in (
            "historySourceIdentity", "baseExposureIdentity")):
        return None
    proof = proofs[0]
    player_evidence = composition.get("sourceEvidence", {}).get("player", {})
    if player_evidence.get("calculation") != "ACCEPTED_GOLD_PRIOR_WINDOW_FEATURES_UNCHANGED":
        return None
    reports = player_evidence.get("rows", [])
    supported = any(report.get("canonicalPaId") == row.get("canonicalPaId")
        and report.get("playerId") == player and report.get("role") == role
        and report.get("windowSupported") is True and report.get("cumulativeExposureSupported") is True
        for report in reports)
    if not supported or not proof.get("orderedPaIdsSha256"):
        return None
    cutoff = utc(snapshot["capturedAt"])
    clocks = [history.get(key) for key in ("observedAt", "availableAsOf", "ingestedAt")]
    if (any(value is None for value in clocks) or max(utc(value) for value in clocks) > cutoff
            or utc(clocks[0]) > utc(clocks[1])):
        raise ValueError("CURRENT_PLAYER_WINDOW_SOURCE_CLOCK_INVALID")
    expected_day = (datetime.fromisoformat(str(row["game_date"])[:10])-timedelta(days=1)).date().isoformat()
    if (history.get("completeThrough") != expected_day or not history.get("contiguousRequestedDatesComplete")
            or history.get("missingDates") != [] or cutoff > datetime.now(timezone.utc)):
        raise ValueError("CURRENT_PLAYER_WINDOW_SOURCE_COMPLETENESS_INVALID")
    window = 100 if role == "batter" else 250
    if (proof.get("window") != window or proof.get("selectedPaCount") != min(window, proof.get("acceptedCumulativeExposure", -1))
            or proof.get("selection") != "EXACT_ACCEPTED_GOLD_ORDER_LAST_N_FROM_FULL_ACCEPTED_2019_TO_CURRENT_SOURCE_UNIVERSE"):
        raise ValueError("CURRENT_PLAYER_WINDOW_SELECTION_PROOF_INVALID")
    exposure = "batter_prior_pa_count" if role == "batter" else "pitcher_prior_bf_count"
    sample = "batter_last100_pa_count" if role == "batter" else "pitcher_last250_bf_count"
    if row.get(exposure) != proof["acceptedCumulativeExposure"] or row.get(sample) != proof["selectedPaCount"]:
        raise ValueError("CURRENT_PLAYER_WINDOW_COUNTS_DIFFER_FROM_EXACT_SOURCE_PROOF")
    return {"schemaVersion": "MLB_V18_EXACT_PLAYER_WINDOW_VECTOR_V2", "gameDate": str(row["game_date"])[:10],
        "sourceAuthorities": {key: source[key] for key in (
            "historySourceIdentity", "baseExposureIdentity")},
        "orderedWindowProof": proof, "treatmentManifestSha256": daily.TREATMENT_MANIFEST_SHA256,
        "calculation": "ACCEPTED_GOLD_PRIOR_WINDOW_FEATURES_UNCHANGED"}


def reuse_player_window_vectors(snapshot, composition, *, output_root=OUTPUT, persist=True):
    """Reuse exact proven arithmetic, never approximate or round a feature value.

    Gold uses prefix cumulative sums. Selecting another game's participant
    histories changes irrelevant older prefixes and can change the final bits of
    an identical last-N window. Retain the first authenticated vector for that
    exact window and source content. Annual, context and handedness stay current.
    """
    if not composition.get("sourceEvidence", {}).get("history", {}).get("windowSelectionProof"):
        return composition
    root, result = Path(output_root), deepcopy(composition)
    fields = load_contract()["rawFeatureColumns"]
    role_fields = {role: [field for field in fields if field.startswith(role + suffix)
                         or field == exposure]
        for role, suffix, exposure in (("batter", "_last100_", "batter_prior_pa_count"),
                                        ("pitcher", "_last250_", "pitcher_prior_bf_count"))}
    rows = list(result.get("rows", []))
    for value in result.get("providerInputs", {}).values():
        rows.extend(value if isinstance(value, list) else [value] if isinstance(value, Mapping) else [])
    requests = {}
    for row in rows:
        for role in role_fields:
            identity = _player_window_identity(snapshot, result, row, role)
            if identity is not None:
                key = daily.sha_json(identity)
                requests.setdefault(key, {"identity": identity, "role": role, "rows": []})["rows"].append(row)
    if not requests:
        return composition
    values, records, anchors, missing = {}, {}, {}, set()
    for key, item in requests.items():
        path = root / "player-window-keys" / f"{key}.json"
        if not path.exists():
            missing.add(key)
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if reference(record["path"]) != {name: record[name] for name in ("path", "sha256", "bytes")}:
            raise ValueError("CURRENT_PLAYER_WINDOW_VECTOR_CHECKSUM_MISMATCH")
        cached = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
        if cached["identity"] != item["identity"] or set(cached["values"]) != set(role_fields[item["role"]]):
            raise ValueError("CURRENT_PLAYER_WINDOW_VECTOR_BINDING_MISMATCH")
        values[key], records[key] = cached["values"], record
        if cached.get("authority", {}).get("originalForecastObjectSha256"):
            anchors[key] = cached["authority"]
    # Seed legacy numerical vectors from the earliest authenticated publication,
    # before considering freshly recalculated values. No source payload is read.
    originals = []
    if missing:
        for path in (root / "objects" / "sha256").glob("*/forecast.json"):
            forecast = json.loads(path.read_text(encoding="utf-8"))
            if (forecast.get("gameId") == snapshot["game"]["game_id"]
                    and forecast.get("forecastCreatedAt")):
                originals.append((utc(forecast["forecastCreatedAt"]), path))
    for _, path in sorted(originals):
        manifest = json.loads(path.with_name("manifest.json").read_text(encoding="utf-8"))
        pointer = {"relativePath": path.parent.relative_to(root).as_posix(), "objectSha256": manifest["objectSha256"]}
        directory, forecast = _verified_forecast(root, pointer)
        parent = forecast.get("parentAuthority", {})
        if parent.get("paModelSha256") != daily.PA_MODEL_SHA256 or parent.get("transitionModelSha256") != daily.TRANSITION_MODEL_SHA256:
            continue
        execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
        original = json.loads(Path(execution["featureSnapshot"]["path"]).read_text(encoding="utf-8"))
        old_composition = original["composition"]
        old_rows = list(execution["rawTemplates"])
        for value in execution["providerInputs"].values():
            old_rows.extend(value if isinstance(value, list) else [value])
        for row in old_rows:
            for role in role_fields:
                identity = _player_window_identity(original, old_composition, row, role)
                key = daily.sha_json(identity) if identity else None
                if key in missing and key not in values:
                    values[key] = {field: row[field] for field in role_fields[role]}
                    anchors[key] = {"originalForecastObjectSha256": manifest["objectSha256"],
                                    "featureSnapshot": execution["featureSnapshot"]}
        if missing.issubset(values):
            break
    bindings = []
    for key, item in requests.items():
        if key not in values:
            first = item["rows"][0]
            values[key] = {field: first[field] for field in role_fields[item["role"]]}
            if any(_numeric_value({field: row[field] for field in role_fields[item["role"]]}) != _numeric_value(values[key])
                   for row in item["rows"]):
                raise ValueError("CURRENT_IDENTICAL_PLAYER_WINDOW_HAS_CONFLICTING_VECTORS")
        if key not in records and persist:
            body = {"identity": item["identity"], "values": values[key], "firstCapturedAt": snapshot["capturedAt"],
                    "authority": anchors.get(key, {"basis": "FIRST_COMPLETE_SOURCE_WINDOW_CALCULATION"}),
                    "producerProvenance": {name: result["sourceEvidence"]["history"]["windowSelectionProof"]["identity"].get(name)
                        for name in ("sourceImplementationSha256", "exposureImplementationSha256")}, **RESEARCH}
            record, _ = write_object(root, "player-window-vector.json", daily.json_safe(body))
            path = root / "player-window-keys" / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, sort_keys=True, separators=(",", ":"))
            records[key] = record
        for row in item["rows"]:
            row.update(values[key])
        bindings.append({"playerId": item["identity"]["orderedWindowProof"]["playerId"], "role": item["role"],
            "exactSourceWindowIdentity": key, "vectorSnapshot": records.get(key),
            "originalPublicationAnchor": anchors.get(key), "roundingApplied": False})
    result["playerWindowVectorCache"] = sorted(bindings, key=lambda binding: (binding["role"], binding["playerId"]))
    return result


class CurrentV18Engine:
    """Only the accepted frozen PA and transition artifacts, not a data warehouse."""
    def __init__(self):
        bundle = ROOT / "outputs/mlb-v18-whole-game-challenger/sha256" / daily.PARENT_BUNDLE_SHA256
        model = bundle / "executable/v18-pa-fold5.joblib"
        transition = bundle / "executable/transition-fold4.json"
        for path, digest in ((model, daily.PA_MODEL_SHA256), (transition, daily.TRANSITION_MODEL_SHA256)):
            if sha_file(path) != digest:
                raise ValueError("ACCEPTED_V18_EXECUTABLE_CHECKSUM_MISMATCH")
        self.pipeline = joblib.load(model)
        self.transition = TransitionModel.from_dict(json.loads(transition.read_text(encoding="utf-8")))
        self.contract = load_contract()
        if list(self.pipeline.ordered_features) != self.contract["rawFeatureColumns"]:
            raise ValueError("ACCEPTED_V18_RAW_FEATURE_ORDER_MISMATCH")
        self.model_identity = {"name": "MLB_V18_HGB_PA", "paFold": 5, "transitionFold": 4,
            "paArtifact": reference(model), "transitionArtifact": reference(transition),
            "parentBundleSha256": daily.PARENT_BUNDLE_SHA256,
            "treatmentSpecificationId": daily.TREATMENT_SPECIFICATION_ID,
            "treatmentManifestSha256": daily.TREATMENT_MANIFEST_SHA256,
            "paClassOrder": list(PA_CLASS_ORDER), "rawInputCount": 246, "treatedInputCount": 273,
            "frozenPriorPaths": {f"wave{wave}": self.pipeline.preprocessor.prior["outputSchema"][f"wave{wave}Features"]
                for wave in (1, 2)},
            "frozenPriorChecksum": self.pipeline.preprocessor.prior["fittedTreatmentChecksum"],
            "frozenSemanticChecksum": self.pipeline.preprocessor.semantic["fittedChecksum"],
            "preprocessorAndEncoderPreservedInsidePaArtifact": True,
            "currentForecastEligibility": "COMPLETE_VERIFIED_PREGAME_SOURCE_CONTRACT_REQUIRED",
            "fitCount": 0, **RESEARCH}

    def forecast(self, snapshot: Mapping, composition: Mapping, feature_snapshot: Mapping) -> dict:
        from .mlb_v18_prospective_transform import ProspectiveFrameAuthority, wrap_prospective_pipeline

        started = time.perf_counter()
        def progress(stage):
            print(json.dumps({"event": "CURRENT_V18_SCORING_PROGRESS", "gameId": snapshot["game"]["game_id"],
                              "stage": stage, "elapsedSeconds": round(time.perf_counter()-started, 3)}), flush=True)
        progress("VERIFYING_COMPLETE_PREGAME_INPUTS")
        _validate_eligible_inputs(snapshot, composition)
        feature_path = Path(feature_snapshot["path"])
        if sha_file(feature_path) != feature_snapshot["sha256"] or feature_path.stat().st_size != feature_snapshot["bytes"]:
            raise ValueError("CURRENT_FEATURE_SNAPSHOT_AUTHENTICATION_FAILED")
        persisted = json.loads(feature_path.read_text(encoding="utf-8"))
        if (_source_identity(persisted["composition"]) != _source_identity(composition)
                or persisted["game"]["game_id"] != snapshot["game"]["game_id"]):
            raise ValueError("CURRENT_FEATURE_SNAPSHOT_INPUT_BINDING_MISMATCH")
        now = datetime.now(timezone.utc)
        _require_publication_window(snapshot)
        if not composition.get("canSimulate") or composition.get("blockers"):
            raise daily.DailySlateError("INCOMPLETE_CURRENT_FEATURE_EVIDENCE", "Complete current-state authority is required")
        inputs = composition["providerInputs"]
        if set(inputs) != {"awayBatters", "homeBatters", "awayStarter", "homeStarter", "awayBullpen", "homeBullpen"}:
            raise ValueError("CURRENT_PROVIDER_INPUT_CONTRACT_MISMATCH")
        raw = pd.DataFrame(composition["rows"], columns=self.contract["rawFeatureColumns"])
        authority = ProspectiveFrameAuthority(
            event_id=str(snapshot["game"]["game_id"]), game_date=str(raw.game_date.iloc[0])[:10],
            evidence_cutoff_utc=str(snapshot["capturedAt"]), kickoff_utc=str(snapshot["game"]["starts_at"]),
            snapshot_sha256=feature_snapshot["sha256"], authorized_at_utc=now.isoformat(),
            venue_timezone=composition.get("venueTimezone") or composition["event"]["venueTimezone"],
        )
        pipeline = wrap_prospective_pipeline(self.pipeline, authority)
        # Preserve the accepted one-row transformation semantics for every PA.
        treated = [pipeline.preprocessor.transform_frame(raw.iloc[[i]]) for i in range(len(raw))]
        probabilities = np.concatenate([pipeline.predict_proba(raw.iloc[[i]]) for i in range(len(raw))])
        if any(item.shape != (1, 273) for item in treated) or probabilities.shape != (len(raw), 8):
            raise ValueError("CURRENT_RAW246_TREATED273_PA8_PARITY_FAILURE")
        progress("RAW246_TREATED273_INITIAL_PA_PROBABILITIES_VERIFIED")
        provider = V18StateProbabilityProvider(pipeline,
            away_batters=inputs["awayBatters"], home_batters=inputs["homeBatters"],
            away_starter=inputs["awayStarter"], home_starter=inputs["homeStarter"],
            away_bullpen=inputs["awayBullpen"], home_bullpen=inputs["homeBullpen"],
            temperature=None, template_composer=current_template)
        progress("ALL_STARTER_AND_STAFF_MATCHUP_TEMPLATES_TRANSFORMED")
        args = dict(game_id=str(snapshot["game"]["game_id"]), provider=provider,
            transition_model=self.transition, master_seed=daily.MASTER_SEED,
            regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=1)
        player_prop_collector = PlayerPropCollector(daily.SIMULATION_COUNT)
        player_prop_observer = FailOpenPlayerPropObserver(player_prop_collector)
        observer_started = time.perf_counter()
        population = simulate_prospective_game(
            **args, n_sims=daily.SIMULATION_COUNT, event_observer=player_prop_observer,
        )
        observer_seconds = time.perf_counter() - observer_started
        progress("ACCEPTED_5000_GAME_SIMULATION_COMPLETED")
        a = simulate_prospective_game(**args, n_sims=64)
        b = simulate_prospective_game(**args, n_sims=64)
        same = all(np.array_equal(a[k], b[k]) for k in ("homeRuns", "awayRuns", "innings", "paCounts")) and a["traces"] == b["traces"]
        if not same or population["illegalStateCount"] or population["nonterminationCount"]:
            raise ValueError("ACCEPTED_CURRENT_SIMULATION_REPRODUCTION_OR_LEGALITY_FAILURE")
        published = datetime.now(timezone.utc)
        if published >= utc(snapshot["game"]["starts_at"]):
            raise daily.DailySlateError("GAME_STARTED_DURING_EXECUTION", "No retroactive pregame publication is authorized")
        _require_publication_window(snapshot)
        home, away = (np.asarray(population[k], dtype=np.float64) for k in ("homeRuns", "awayRuns"))
        total, margin = home+away, home-away
        p = float(population["homeWinProbability"])
        def distribution(values):
            return [{"value": value, "probability": n/len(values)} for value, n in sorted(Counter(map(int, values)).items())]
        sides = {s["side"]: s for s in snapshot["sides"]}
        execution = {"schemaVersion": "MLB_V18_CURRENT_STATE_EXECUTION_INPUTS_V1",
            "featureSnapshot": dict(feature_snapshot), "rawTemplates": raw.to_dict("records"),
            "treatedFeatureOrder": self.contract["treatedFeatureColumns"],
            "treatedRows": pd.concat(treated).to_dict("records"),
            "initialPaClassOrder": list(PA_CLASS_ORDER), "initialPaProbabilities": probabilities,
            "providerInputs": inputs, "population": population, "modelIdentity": self.model_identity,
            "sourceCutoff": composition.get("sourceCutoff") or composition.get("event", {}).get("sourceCutoff") or snapshot["capturedAt"],
            "genericMedianModeFallbacks": 0, "refits": 0,
            "runtimeSeconds": time.perf_counter()-started}
        forecast = {"schemaVersion": daily.GAME_SCHEMA, "gameId": snapshot["game"]["game_id"],
            "sourceGameId": snapshot["game"].get("source_game_id"), "capturedAt": snapshot["capturedAt"],
            "forecastCreatedAt": published.isoformat(), "scheduledStart": snapshot["game"]["starts_at"],
            "pregameStatus": snapshot["game"]["status"], "sourceCutoff": execution["sourceCutoff"],
            "venue": {"name": snapshot["game"].get("venue"), "timezone": authority.venue_timezone},
            "teams": {side:sides[side]["team"] for side in sides},
            "starters": {side:sides[side]["starter"] for side in sides},
            "lineupAuthorities": {side:sides[side]["lineupAuthority"] for side in sides},
            "parentAuthority": {"bundleId": daily.PARENT_BUNDLE_ID, "bundleSha256": daily.PARENT_BUNDLE_SHA256,
                "acceptanceProtocolV2Sha256": daily.ACCEPTANCE_PROTOCOL_V2_SHA256,
                "paModelSha256": daily.PA_MODEL_SHA256, "transitionModelSha256": daily.TRANSITION_MODEL_SHA256,
                "paFold": 5, "transitionFold": 4, "providerCacheSemantics": "ONE_ROW_TRANSFORM_PER_TEMPLATE_V1"},
            "evidenceDigest": daily.evidence_logical_digest(snapshot), "snapshotContentSha256": snapshot["contentSha256"],
            "executionInputDigest": daily.sha_json(daily.json_safe(execution)),
            "rawTemplateDigest": daily.sha_json(daily.json_safe(execution["rawTemplates"])),
            "probabilities": {"homeWin": p, "awayWin": 1-p},
            "expectations": {"homeRuns": float(home.mean()), "awayRuns": float(away.mean()),
                "totalRuns": float(total.mean()), "homeMinusAwayRuns": float(margin.mean())},
            "rates": {"oneRunGame": population["oneRunRate"], "extraInning": population["extraInningRate"]},
            "distributions": {"homeRuns": distribution(home), "awayRuns": distribution(away),
                "totalRuns": distribution(total), "homeMinusAwayRuns": distribution(margin)},
            "simulation": {"count": 5000, "seed": daily.MASTER_SEED, "illegalStateCount": 0,
                "nonterminationCount": 0, "deterministicReplay": same, "deterministicReplaySimulations": 64,
                "representativePathCount": 1},
            "monteCarloUncertainty": {"method": "MONTE_CARLO_NORMAL_APPROXIMATION_95_PERCENT",
                "homeWinProbabilityStandardError": math.sqrt(p*(1-p)/5000)},
            "knownLimitations": ["Fixed ordered lineup; no bench/substitution model.",
                "Accepted starter-removal and team-staff mixture rules are not individual availability predictions.",
                "Current archive reconstruction is not historical publication-vintage evidence."],
            "finalOot": {"locked": True, "opened": False, "featureRowsRead": 0, "targetsRead": 0, "scored": False},
            **RESEARCH}
        payload = daily.json_safe({"forecast": forecast, "executionInputs": execution, "evidence": snapshot,
            "representativePath": {"schemaVersion": "MLB_V18_DAILY_REPRESENTATIVE_PATH_V1",
                "gameId": forecast["gameId"], "simulationIndex": 0, "events": population["traces"][0]}})
        daily.validate_forecast_payload(snapshot, payload)
        # Private in-process transport only.  The caller removes this object
        # before computing or writing any immutable forecast member.
        payload["_playerPropCapture"] = {
            "collector": player_prop_collector,
            "observerFailureCategory": player_prop_observer.failure_category,
            "observerSeconds": observer_seconds,
        }
        return payload


def _player_prop_capture_root(forecast_root, override=None):
    if override is not None:
        return Path(override)
    root = Path(forecast_root)
    if root.name == OUTPUT.name:
        return root.parent / PLAYER_PROP_CAPTURE_OUTPUT_NAME
    return root / "_player-prop-prospective-capture"


def publish_composed_game(snapshot, composition, *, output_root=OUTPUT, engine=None, player_prop_capture_root=None):
    """Always retain raw246 and reason evidence; never execute an unsupported row."""
    root = Path(output_root)
    if composition.get("canSimulate") and not composition.get("blockers"):
        _validate_eligible_inputs(snapshot, composition)
    composition = reuse_player_window_vectors(snapshot, composition, output_root=root)
    rows = daily.json_safe(composition.get("rows", []))
    contract = load_contract()
    if any(set(row) != set(contract["rawFeatureColumns"]) for row in rows):
        raise ValueError("CURRENT_SNAPSHOT_MUST_RETAIN_ALL_246_RAW_FIELDS")
    identity = daily.sha_json(_source_identity({"source": snapshot, "composition": composition}))
    body = {"schemaVersion": "MLB_V18_CURRENT_STATE_FEATURE_SNAPSHOT_V1", "evidenceIdentity": identity,
        "capturedAt": snapshot["capturedAt"], "game": snapshot["game"], "sides": snapshot["sides"],
        "rawFeatureOrder": contract["rawFeatureColumns"], "treatedFeatureOrder": contract["treatedFeatureColumns"],
        "treatmentSpecificationId": daily.TREATMENT_SPECIFICATION_ID,
        "treatmentManifestSha256": daily.TREATMENT_MANIFEST_SHA256,
        "composition": composition, "noHistoricalPublicationVintageClaim": True, **RESEARCH}
    record, reused = _fixed_object(root, identity, body)
    result = {"gameId": snapshot["game"]["game_id"], "featureSnapshot": record,
        "unchangedEvidenceReused": reused, "rawRows": len(rows), "coverage": composition.get("coverage"),
        "blockers": list(composition.get("blockers") or []), "status": "SKIPPED"}
    if not composition.get("canSimulate") or result["blockers"]:
        if not result["blockers"]:
            result["blockers"] = [{"reason": "COMPLETE_SIMULATION_MATCHUP_EVIDENCE_NOT_ATTESTED"}]
        return result
    _validate_eligible_inputs(snapshot, composition)
    numeric = numerical_input_identity(snapshot, composition, contract)
    result["numericalInputSha256"] = numeric
    existing = _reuse_numerical_forecast(root, numeric, snapshot, contract)
    if existing:
        pointer, forecast = existing
        try:
            capture = existing_player_prop_capture(
                _player_prop_capture_root(root, player_prop_capture_root), pointer["objectSha256"]
            )
            capture_status = ({"status": "EXISTING_PROSPECTIVE_CAPTURE_REUSED",
                "package": capture["package"]} if capture else
                {"status": "NO_PROSPECTIVE_CAPTURE_NO_REPLAY_AUTHORIZED"})
        except Exception as exc:
            capture_status = {"status": "EXISTING_CAPTURE_LOOKUP_FAILED_FORECAST_REUSE_CONTINUES",
                "category": getattr(exc, "code", type(exc).__name__)}
        return {**result, **pointer, "status": "UNCHANGED_NUMERICAL_FORECAST_REUSED", "newInference": False,
                "forecastCreatedAt": forecast["forecastCreatedAt"], "capturedAt": forecast["capturedAt"],
                "evidenceCutoff": _forecast_evidence_cutoff(forecast),
                "scheduledStart": forecast["scheduledStart"],
                "playerPropCapture": capture_status}
    _require_publication_window(snapshot)
    active_engine = engine or CurrentV18Engine()
    enriched_snapshot = {**snapshot, "currentStateEvidenceIdentity": identity}
    enriched_snapshot["contentSha256"] = daily.sha_json(daily.json_safe({k:v for k,v in enriched_snapshot.items() if k != "contentSha256"}))
    payload = active_engine.forecast(enriched_snapshot, composition, record)
    private_capture = payload.pop("_playerPropCapture", None)
    # Enforce the publication deadline again at the immutable-write boundary,
    # even when a caller supplies an engine implementation.
    forecast = payload["forecast"]
    if (datetime.now(timezone.utc) >= utc(snapshot["game"]["starts_at"])
            or not utc(snapshot["capturedAt"]) <= utc(forecast["forecastCreatedAt"]) < utc(snapshot["game"]["starts_at"])):
        raise daily.DailySlateError("GAME_STARTED_DURING_EXECUTION", "No retroactive pregame publication is authorized")
    _require_publication_window(snapshot)
    planned_manifest = planned_forecast_manifest(enriched_snapshot, payload)
    capture_root = _player_prop_capture_root(root, player_prop_capture_root)
    capture_result, capture_failure = None, None
    if private_capture is not None:
        if private_capture.get("observerFailureCategory") is not None:
            capture_failure = "PLAYER_PROP_OBSERVER_FAILED_" + str(
                private_capture["observerFailureCategory"]
            )
        else:
            try:
                capture_result = finalize_player_prop_capture(
                    collector=private_capture["collector"],
                    forecast_manifest=planned_manifest,
                    payload=payload,
                    output_root=capture_root,
                    observer_seconds=private_capture.get("observerSeconds"),
                )
            except Exception as exc:
                capture_failure = getattr(exc, "code", type(exc).__name__)
    if datetime.now(timezone.utc) >= utc(snapshot["game"]["starts_at"]):
        raise daily.DailySlateError("GAME_STARTED_DURING_EXECUTION", "No retroactive pregame publication is authorized")
    pointer = daily._publish_game(root, enriched_snapshot, payload)
    if pointer["objectSha256"] != planned_manifest["objectSha256"]:
        raise daily.DailySlateError("PERSISTENCE_PUBLICATION_FAILURE",
            "published object identity differs from the pre-write forecast identity")
    if capture_failure is not None:
        try:
            capture_result = write_player_prop_capture_failure(
                output_root=capture_root,
                game_id=str(snapshot["game"]["game_id"]),
                forecast_object_sha256=pointer["objectSha256"],
                category=str(capture_failure),
            )
        except Exception as failure_exc:
            capture_result = {"status": "PLAYER_PROP_CAPTURE_AND_FAILURE_RECEIPT_FAILED_FORECAST_CONTINUES",
                "category": str(capture_failure),
                "failureReceiptCategory": getattr(failure_exc, "code", type(failure_exc).__name__)}
    elif private_capture is None:
        capture_result = {"status": "ENGINE_DID_NOT_ATTACH_PLAYER_PROP_OBSERVER"}
    pointer_path = root / "numerical-keys-v2" / f"{numeric}.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    with pointer_path.open("x", encoding="utf-8") as stream:
        json.dump(pointer, stream, sort_keys=True, separators=(",", ":"))
    return {**result, **pointer, "newInference": pointer["status"] == "PUBLISHED", "blockers": [],
            "forecastCreatedAt": forecast["forecastCreatedAt"], "capturedAt": forecast["capturedAt"],
            "evidenceCutoff": _forecast_evidence_cutoff(forecast),
            "scheduledStart": forecast["scheduledStart"], "playerPropCapture": capture_result}


def current_handoff(root, slate_date, forecasts, *, games=None):
    """A polling receipt is new; an unchanged immutable forecast handoff is not."""
    root = Path(root).resolve()
    published = {row["gameId"]: row["objectSha256"] for row in forecasts}
    accounting = None if games is None else [
        {"gameId": row["gameId"], "status": "PUBLISHED" if row["gameId"] in published else row["status"],
         **({"rosterReadiness": _source_identity(row["rosterReadiness"])}
            if row.get("rosterReadiness") else {}),
         **({"objectSha256": published[row["gameId"]]} if row["gameId"] in published else
            {"reason": row.get("reason") or row.get("error"), "blockers": _source_identity(row.get("blockers", []))})}
        for row in sorted(games, key=lambda row: row["gameId"])]
    identity_body = {"slateDate": slate_date.isoformat(), "forecasts": forecasts}
    if accounting is not None:
        identity_body["gameAccounting"] = accounting
    identity = daily.sha_json(identity_body)
    index_path = root / "handoff-keys" / f"{identity}.json"
    if index_path.exists():
        descriptor = json.loads(index_path.read_text(encoding="utf-8"))
        if reference(descriptor["path"]) != {k:descriptor[k] for k in ("path", "sha256", "bytes")}:
            raise ValueError("CURRENT_HANDOFF_CHECKSUM_MISMATCH")
        if accounting is not None:
            for row in forecasts:
                _verified_forecast(root, row)
        return descriptor
    if accounting is None:
        _, logical_digest, path = daily._write_handoff(root, slate_date, forecasts)
    else:
        children = []
        for row in forecasts:
            directory, forecast = _verified_forecast(root, row)
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            evidence = json.loads((directory / "pregame-evidence.json").read_text(encoding="utf-8"))
            execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
            feature = execution["featureSnapshot"]
            if reference(feature["path"]) != {key: feature[key] for key in ("path", "sha256", "bytes")}:
                raise ValueError("CURRENT_HANDOFF_FEATURE_SNAPSHOT_CHECKSUM_MISMATCH")
            feature_body = json.loads(Path(feature["path"]).read_text(encoding="utf-8"))
            children.append({**row, "importIdentity": row["objectSha256"],
                "forecastCreatedAt": forecast["forecastCreatedAt"],
                "evidenceCutoff": _forecast_evidence_cutoff(forecast),
                "sourceRetrievalTimestamps": {"snapshotRetrievedAt": evidence["capturedAt"],
                    "participantEvidence": [{"side": side["side"], "starter": side["starter"],
                        "lineupAuthority": side["lineupAuthority"]} for side in evidence["sides"]],
                    "queryReceipts": evidence.get("queryReceipts", [])},
                "participants": evidence["sides"], "modelIdentity": execution["modelIdentity"],
                "probabilities": forecast["probabilities"], "expectations": forecast["expectations"],
                "simulation": forecast["simulation"], "distributions": forecast["distributions"],
                "evidenceReadiness": feature_body["composition"].get("coverage"),
                "featureSnapshot": feature, "manifest": daily.file_record(directory / "manifest.json", root),
                "childBindings": manifest["artifacts"], **RESEARCH})
        body = {"schemaVersion": daily.HANDOFF_SCHEMA_V2 if forecasts and all(
                    row.get("playGeometry") and row.get("populationGeometry") for row in forecasts) else daily.HANDOFF_SCHEMA,
                "slateDate": slate_date.isoformat(), "generatedAt": datetime.now(timezone.utc).isoformat(),
                "parentBundleId": daily.PARENT_BUNDLE_ID, "parentBundleSha256": daily.PARENT_BUNDLE_SHA256,
                "acceptanceProtocolV2Sha256": daily.ACCEPTANCE_PROTOCOL_V2_SHA256,
                "forecasts": children, "gameAccounting": accounting,
                "consumerRules": ["verify manifest and all child checksums and byte counts",
                    "associate exact existing canonical event and participant IDs", "skip unknown games",
                    "import idempotently by objectSha256", "do not execute V18", "preserve Gen1",
                    "preserve official policy; do not create decisions or positions",
                    "RESEARCH_SHADOW only; no wagering or promotion authority"], **RESEARCH}
        logical_digest = daily.sha_json(daily.json_safe(body))
        handoff = {**body, "handoffId": f"mlb-v18-daily-handoff-{logical_digest[:24]}", "handoffSha256": logical_digest}
        path = f"handoffs/sha256/{logical_digest}/aisp-handoff.json"
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if json.loads(target.read_text(encoding="utf-8")) != daily.json_safe(handoff):
                raise ValueError("CURRENT_HANDOFF_IMMUTABLE_CONTENT_MISMATCH")
        else:
            with target.open("x", encoding="utf-8") as stream:
                json.dump(daily.json_safe(handoff), stream, sort_keys=True, separators=(",", ":"))
    descriptor = {**reference(root/path), "logicalHandoffSha256": logical_digest, "outputRoot": str(root)}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("x", encoding="utf-8") as stream:
        json.dump(descriptor, stream, sort_keys=True, separators=(",", ":"))
    return descriptor


def current_import_receipt(root, slate_date, forecasts, games, handoff):
    """Use the existing AISP daily importer receipt contract without an AISP write."""
    root = Path(root).resolve()
    published_ids = {row["gameId"] for row in forecasts}
    published = [{"gameId": row["gameId"], "status": "PUBLISHED",
                  "objectSha256": row["objectSha256"], "artifactPath": row["relativePath"],
                  "capturedAt": row["capturedAt"], "scheduledStart": row["scheduledStart"]}
                 for row in forecasts]
    unresolved = [{**row, "reason": row.get("reason") or row.get("error") or
                   "; ".join(str(b.get("reason", b)) for b in row.get("blockers", []))}
                  for row in games if row["gameId"] not in published_ids]
    body = {"schemaVersion": daily.RECEIPT_SCHEMA, "mode": "CURRENT_SOURCE_FROZEN_V18_PUBLICATION",
            "slateDate": slate_date.isoformat(), "generatedAt": datetime.now(timezone.utc).isoformat(),
            "games": published + unresolved, "gamesDiscovered": len(games),
            "handoffForecasts": len(forecasts), "forecastsCompleted": sum(bool(g.get("newInference")) for g in games),
            "gamesSkipped": sum(g["status"] == "SKIPPED" for g in unresolved),
            "gamesFailed": sum(g["status"] == "FAILED" for g in unresolved),
            "handoffSha256": handoff["logicalHandoffSha256"],
            "handoffPath": Path(handoff["path"]).relative_to(root).as_posix(),
            "executionAccounting": {"modelFits": 0, "simulationsPerPublishedGame": daily.SIMULATION_COUNT,
                                    "currentGamesInferred": sum(bool(g.get("newInference")) for g in games)},
            "aispRowsModified": 0, "gen1RowsModified": 0, "providerCalls": 0,
            "finalOot": {"locked": True, "opened": False, "featureRowsRead": 0, "targetsRead": 0, "scored": False},
            **RESEARCH}
    receipt = daily._write_receipt_and_locator(root, slate_date, body)
    path = root / "slates" / slate_date.isoformat() / "sha256" / receipt["receiptSha256"] / "slate-result.json"
    return {**reference(path), "logicalReceiptSha256": receipt["receiptSha256"]}


def publish_slate(snapshot_collection, compositions, *, output_root=OUTPUT):
    root = Path(output_root)
    games, engine = [], None
    # The model is loaded lazily only for an eligible cache miss.
    class LazyEngine:
        def forecast(self, *args):
            nonlocal engine
            if engine is None:
                engine = CurrentV18Engine()
            return engine.forecast(*args)
    for snapshot, composition in zip(snapshot_collection["snapshots"], compositions, strict=True):
        try:
            games.append(publish_composed_game(snapshot, composition, output_root=root, engine=LazyEngine()))
        except Exception as exc:
            category = getattr(exc, "category", getattr(exc, "code", type(exc).__name__))
            status = "SKIPPED" if category in {"GAME_ALREADY_STARTED", "GAME_STARTED_DURING_EXECUTION", "PUBLICATION_SAFETY_CUTOFF_REACHED"} else "FAILED"
            failure = {"gameId": snapshot["game"]["game_id"], "status": status,
                "category": category, "error": str(exc)}
            failure["receipt"], _ = write_object(root, "failure.json", failure)
            games.append(failure)
    date_eastern = utc(snapshot_collection["capturedAt"]).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    if snapshot_collection["snapshots"]:
        date_eastern = utc(snapshot_collection["snapshots"][0]["game"]["starts_at"]).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    forecasts = daily.collect_slate_forecasts(root, date_eastern)
    handoff = None
    if forecasts:
        handoff = current_handoff(root, date_eastern, forecasts, games=games)
    import_receipt = current_import_receipt(root, date_eastern, forecasts, games, handoff) if handoff else None
    report = {"schemaVersion": "MLB_V18_CURRENT_STATE_RUN_V1", "capturedAt": snapshot_collection["capturedAt"],
        "completedAt": datetime.now(timezone.utc).isoformat(), "games": games, "scheduledGameCount": len(games),
        "newForecastCount": sum(bool(g.get("newInference")) for g in games),
        "validForecastCount": sum(g["status"] in {"PUBLISHED", "DUPLICATE_ALREADY_PUBLISHED", "UNCHANGED_NUMERICAL_FORECAST_REUSED"} for g in games),
        "skippedGameCount": sum(g["status"] == "SKIPPED" for g in games),
        "failedGameCount": sum(g["status"] == "FAILED" for g in games), "handoff": handoff,
        "aispImportReceipt": import_receipt,
        "publicationDisposition": "FORECAST_HANDOFF_AVAILABLE" if handoff else "NO_CURRENT_FORECAST_HANDOFF",
        "aispWrites": 0, "fits": 0, "finalOotPayloadReads": 0,
        "unattendedServiceActivated": False, **RESEARCH}
    report["receipt"], _ = write_object(root, "run.json", daily.json_safe(report))
    return report

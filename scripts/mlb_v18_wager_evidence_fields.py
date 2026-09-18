"""Read exact V18 forecast-bound evidence; never acquire, fit, simulate or read finals.

The caller chooses the population and applies identity quarantine before calling.
Complex columns are compact JSON strings. Counts/quantiles calculated here are
DERIVED_NOW_FROM_RETAINED_INPUTS, not diagnostics asserted to exist at decision.
Source-history references are never followed. A model binary is hash checked but
never deserialized. Legacy daily-template forecasts remain a distinct input era.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import base64
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, pstdev
import struct
from typing import Any
import zlib


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A timestamp without timezone cannot establish availability")
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=512)
def _physical(path_string: str, size: int, mtime_ns: int) -> str:
    digest = hashlib.sha256()
    with Path(path_string).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ref(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path.resolve()), "sha256": _physical(str(path.resolve()), stat.st_size, stat.st_mtime_ns), "bytes": stat.st_size}


def _verify_ref(record: dict, path: Path | None = None) -> dict:
    target = path or Path(record["path"])
    result = _ref(target)
    if result["sha256"] != record["sha256"] or result["bytes"] != record["bytes"]:
        raise ValueError(f"Evidence hash/size mismatch: {target}")
    return result


def _missing(value: Any) -> bool:
    return value is None or isinstance(value, float) and not math.isfinite(value)


def _quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo) if hi != lo else ordered[lo]


def _summary(values: list[float]) -> dict:
    return {"n": len(values), "mean": mean(values) if values else None,
            "sd": pstdev(values) if values else None,
            "quantiles": {str(p): _quantile(values, p) for p in (.05, .1, .25, .5, .75, .9, .95)},
            "min": min(values) if values else None, "max": max(values) if values else None}


def _counts(rows: list[dict]) -> dict:
    return dict(sorted(Counter(key for row in rows for key, value in row.items() if _missing(value)).items()))


def _indicators(rows: list[dict]) -> dict:
    """Affirmative frozen indicators, separate from physical null-cell counts."""
    return dict(sorted(Counter(key for row in rows for key, value in row.items()
                               if key.endswith(("_missing", "_insufficient")) and value == 1).items()))


def _prediction_counts(vector: dict, count: int) -> list[int]:
    if vector.get("encoding") != "BASE64_ZLIB_UINT16_LE_V1" or vector.get("count") != count or not 0 < count <= 10000:
        raise ValueError("Observer prediction vector encoding/count invalid")
    compressed = base64.b64decode(vector["data"], validate=True)
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, count * 2 + 1)
    if not decompressor.eof or decompressor.unused_data or len(raw) != count * 2:
        raise ValueError("Observer prediction vector size invalid")
    if hashlib.sha256(raw).hexdigest() != vector["rawSha256"]:
        raise ValueError("Observer prediction vector checksum mismatch")
    return list(struct.unpack("<" + "H" * count, raw))


def _player_record(template: dict, role: str) -> dict:
    prefix = role + "_"
    fields = [key for key in template if key.startswith(prefix) and any(
        word in key for word in ("count", "missing", "insufficient", "prior_g", "prior_ab", "prior_ipouts"))]
    return {"canonical_player_id": template.get(role + "CanonicalPlayerId"),
            **{key: template[key] for key in sorted(fields)}}


def _source_clocks(sides: list[dict]) -> list[dict]:
    return [{"side": side.get("side"), "kind": kind,
             **{key: evidence.get(key) for key in ("source", "observationId", "payloadChecksum", "observedAt", "availableAsOf", "ingestedAt")}}
            for side in sides for kind in ("starter", "lineupAuthority")
            for evidence in [side.get(kind, {})]]


def _observer_metadata(directory: Path, object_sha: str, decision: datetime | None,
                       forecast: dict, population: dict) -> dict:
    """Read only exact prospective package and its prediction count vectors."""
    root = directory.parents[2].parent / "mlb-v18-player-prop-prospective-v1"
    key_path = root / "forecast-keys" / (object_sha + ".json")
    if not key_path.exists():
        return {"status": "NO_EXACT_FORECAST_PROSPECTIVE_OBSERVER_KEY; NO_RETROSPECTIVE_REPLAY_SUBSTITUTED"}
    key = json.loads(key_path.read_text(encoding="utf-8"))
    if key.get("forecastObjectSha256") != object_sha:
        raise ValueError("Observer forecast key mismatch")
    discovery_path = Path(key["discovery"]["path"]).resolve()
    if not discovery_path.is_relative_to(root.resolve() / "discovery"):
        raise ValueError("Observer discovery escaped permitted root")
    _verify_ref(key["discovery"], discovery_path)
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    package = discovery["package"]
    target = Path(package["path"]).resolve()
    if not target.is_relative_to(root.resolve() / "objects" / "sha256"):
        raise ValueError("Observer package escaped permitted root")
    manifest_path = target / "manifest.json"
    if _ref(manifest_path)["sha256"] != package["manifestPhysicalSha256"]:
        raise ValueError("Observer manifest physical checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k not in {"packageId", "packageSha256"}}
    if hashlib.sha256(_json(body).encode()).hexdigest() != package["sha256"]:
        raise ValueError("Observer package logical checksum mismatch")
    if any(record.get("forecastObjectSha256") != object_sha for record in (discovery, manifest)):
        raise ValueError("Observer package forecast mismatch")
    members = {r["relativePath"]: r for r in manifest["members"]}
    if set(members) != {"capture.json", "registration.json", "sidecar.json"}:
        raise ValueError("Observer package members outside prediction-only whitelist")
    _verify_ref(members["registration.json"], target / "registration.json")
    registration = json.loads((target / "registration.json").read_text(encoding="utf-8"))
    if registration.get("forecastObjectSha256") != object_sha:
        raise ValueError("Observer registration forecast mismatch")
    registered = _utc(registration.get("registeredAt"))
    scheduled = _utc(registration.get("timing", {}).get("scheduledStart"))
    if not registered or not scheduled or registered >= scheduled:
        raise ValueError("Observer is not genuinely pregame")
    sidecar_path = target / "sidecar.json"
    _verify_ref(members["sidecar.json"], sidecar_path)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if sidecar.get("schemaVersion") != "ASP_MLB_V18_PLAYER_PROP_POPULATION_V1":
        raise ValueError("Unexpected observer prediction schema")
    binding = sidecar["binding"]
    counts = Counter(zip(population["awayRuns"], population["homeRuns"]))
    cells = [{"awayScore": int(away), "homeScore": int(home), "count": count}
             for (away, home), count in sorted(counts.items())]
    expected = {"forecastObjectSha256": object_sha, "gameId": forecast["gameId"],
                "simulationCount": forecast["simulation"]["count"], "masterSeed": forecast["simulation"]["seed"],
                "populationSha256": hashlib.sha256(_json(cells).encode()).hexdigest(),
                "modelArtifactSha256": forecast.get("parentAuthority", {}).get("paModelSha256"),
                "transitionArtifactSha256": forecast.get("parentAuthority", {}).get("transitionModelSha256")}
    if any(binding.get(key) != value for key, value in expected.items()):
        raise ValueError("Observer prediction/model/population binding mismatch")
    if _utc(sidecar.get("createdAt")) != registered or _utc(binding.get("scheduledStart")) != scheduled:
        raise ValueError("Observer prediction clock mismatch")
    summaries, relief_summaries = {}, {}
    starter_rows = sidecar.get("startingPitchers", [])
    if len(starter_rows) != 2 or {p.get("side") for p in starter_rows} != {"AWAY", "HOME"}:
        raise ValueError("Observer starter sides invalid")
    for pitcher in starter_rows:
        side = pitcher["side"]
        retained_starter = forecast.get("starters", {}).get(side, {})
        if (str(pitcher.get("mlbamId")) != str(retained_starter.get("mlbamId"))
                or pitcher.get("playerId") != retained_starter.get("uuid")):
            raise ValueError("Observer starting pitcher identity mismatch")
        summaries[side] = {k: pitcher.get(k) for k in ("playerId", "mlbamId", "displayName", "modelTemplatePlayerId")}
        relief_summaries[side] = {}
        for statistic in ("BATTERS_FACED", "STRIKEOUTS"):
            values = _prediction_counts(pitcher["statistics"][statistic], expected["simulationCount"])
            summaries[side][statistic] = _summary(values)
            relief_values = _prediction_counts(sidecar["anonymousReliefSummary"][side][statistic], expected["simulationCount"])
            relief_summaries[side][statistic] = _summary(relief_values)
    return {"status": "GENUINE_PROSPECTIVE_EXACT_FORECAST_CAPTURE_METADATA_VERIFIED",
            "package": package, "registered_at": registration["registeredAt"],
            "registered_before_decision": None if not decision else registered <= decision,
            "created_after_decision": None if not decision else registered > decision,
            "registered_before_start": registered < scheduled,
            "registered_at_or_before_decision_cutoff_t15": registered <= scheduled - timedelta(minutes=15),
            "registered_at_or_before_research_cutoff_t5": registered <= scheduled - timedelta(minutes=5),
            "role": registration.get("role"), "authority": registration.get("authority"),
            "sidecar_reference": {**members["sidecar.json"], "path": str(target / "sidecar.json")},
            "sidecar_payload_read": True, "prediction_vectors_decoded": "STARTER_AND_ANONYMOUS_RELIEF_BF_K_ONLY",
            "starting_pitcher_summary_derived": summaries, "anonymous_relief_summary_derived": relief_summaries,
            "recorded_accounting": sidecar.get("accounting"),
            "retained_diagnostics": "Per-draw named batter PA/H/TB/HR and starter BF/K; anonymous relief BF/K. Starter/relief summaries derived now from retained predictions; no starter outs field exists."}


def extract_forecast_evidence(forecast_dir: Path, decision_utc: str | None = None) -> dict:
    """Return one exact-forecast row. Integrity or unsafe-path failures fail closed.

    Only exact manifest children, the bound feature snapshot/model bytes, and
    exact prospective prediction sidecars may be read. No history/source payload
    or observed target outcome is opened.
    No loss/win label is accepted here; those belong to reconciled wager authority.
    """
    directory = Path(forecast_dir).resolve()
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k not in {"objectId", "objectSha256"}}
    logical = hashlib.sha256(_json(body).encode()).hexdigest()
    if logical != manifest.get("objectSha256") or directory.name != logical:
        raise ValueError("Forecast object manifest identity mismatch")
    allow = {"forecast.json", "execution-inputs.json", "pregame-evidence.json", "representative-path.json"}
    children = {}
    for record in manifest.get("artifacts", []):
        name = record["relativePath"]
        if name not in allow:
            raise ValueError(f"Unexpected forecast child: {name}")
        children[name] = {**record, "path": str(directory / name)}
    required = {"forecast.json", "execution-inputs.json", "pregame-evidence.json"}
    if not required.issubset(children):
        raise ValueError("Required immutable forecast children missing")
    _verify_ref(children["forecast.json"], directory / "forecast.json")
    forecast = json.loads((directory / "forecast.json").read_text(encoding="utf-8"))
    # This guard rejects target dates in the protected period before execution,
    # pregame, feature snapshots or models are opened. Root applies broader keys.
    start = _utc(forecast.get("scheduledStart"))
    if start and "2026-08-14" <= start.date().isoformat() <= "2026-08-27":
        raise ValueError("Protected MLB target period is not authorized")
    children = {name: _verify_ref(record, directory / name) for name, record in children.items()}
    execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
    evidence = json.loads((directory / "pregame-evidence.json").read_text(encoding="utf-8"))
    if forecast.get("gameId") != manifest.get("gameId"):
        raise ValueError("Manifest/forecast game identity mismatch")
    model = execution.get("modelIdentity", {})
    model_verified, gaps = {}, []
    for name in ("paArtifact", "transitionArtifact"):
        record = model.get(name)
        if record:
            path = Path(record["path"])
            if path.suffix not in {".joblib", ".json"} or "executable" not in path.parts:
                raise ValueError("Model binding is not an approved executable artifact")
            try:
                model_verified[name] = _verify_ref(record)
            except FileNotFoundError:
                model_verified[name] = {**record, "verification": "FILE_MISSING"}
                gaps.append(name + " file missing; retained binding only")
        else:
            gaps.append(name + " explicit artifact reference not retained in execution")
    composition, feature_ref = {}, execution.get("featureSnapshot")
    feature_status = "NOT_RETAINED_IN_THIS_FORECAST_ERA"
    if feature_ref:
        path = Path(feature_ref["path"]).resolve()
        # Only current-state feature objects, never files named source/history/
        # outcomes or arbitrary references embedded in their evidence sections.
        expected_root = directory.parents[2]
        permitted = (path.name == "feature-snapshot.json" and path.is_relative_to(expected_root / "objects" / "sha256")
                     and not any(part.lower() in {"sealed", "final-oot", "final_oot"} for part in path.parts))
        if not permitted:
            feature_status = "NOT_OPENED_UNAPPROVED_OR_PROTECTED_FEATURE_PATH"
            gaps.append(feature_status)
        else:
            try:
                _verify_ref(feature_ref, path)
                feature = json.loads(path.read_text(encoding="utf-8"))
                if feature.get("schemaVersion") != "MLB_V18_CURRENT_STATE_FEATURE_SNAPSHOT_V1":
                    raise ValueError("Unexpected bound feature snapshot schema")
                if feature.get("game", {}).get("game_id") != forecast["gameId"]:
                    raise ValueError("Feature snapshot game mismatch")
                composition = feature.get("composition", {})
                feature_status = "VERIFIED_RETAINED_CURRENT_FEATURE_SUMMARY_NO_SOURCE_LINKS_FOLLOWED"
            except FileNotFoundError:
                feature_status = "BOUND_FEATURE_SNAPSHOT_FILE_MISSING"
                gaps.append(feature_status)
    provider = execution.get("providerInputs", {})
    raw = execution.get("rawTemplates", [])
    treated = execution.get("treatedRows", [])
    population = execution.get("population", {})
    home = population.get("homeRuns", [])
    away = population.get("awayRuns", [])
    if not home or len(home) != len(away):
        raise ValueError("No aligned retained paired score population")
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in home + away):
        raise ValueError("Invalid retained paired score population")
    if len(home) != forecast.get("simulation", {}).get("count"):
        raise ValueError("Recorded simulation count disagrees with retained population")
    derived_p_home = sum(h > a for h, a in zip(home, away)) / len(home)
    probability = forecast.get("probabilities", {})
    total, margin = [h + a for h, a in zip(home, away)], [h - a for h, a in zip(home, away)]
    probability_delta = abs(derived_p_home - probability.get("homeWin", derived_p_home))
    reports = composition.get("fieldReports", [])
    fields = [f for report in reports for f in report.get("fields", [])]
    source_evidence = composition.get("sourceEvidence", {})
    player = source_evidence.get("player", {})
    # Deduplicate repeated PA matchup support; separate role and player.
    annual, windows = {}, {}
    for record in player.get("annual", []):
        key = (record.get("role"), record.get("playerId"))
        annual[key] = {k: record.get(k) for k in ("role", "playerId", "sourceSeason", "status", "careerNoHistoryInferred", "noCurrentSeasonStrengthUpdateClaimed")}
    for record in player.get("rows", []):
        key = (record.get("role"), record.get("playerId"))
        windows[key] = {k: record.get(k) for k in ("role", "playerId", "window", "windowSupported", "observedPAsAfterCompleteFrom", "cumulativeExposureSupported", "completePlayerWindowVerified", "status")}
    history = source_evidence.get("history", {})
    sides = evidence.get("sides", [])
    captured, created, decision = _utc(forecast.get("capturedAt")), _utc(forecast.get("forecastCreatedAt")), _utc(decision_utc)
    clocks = _source_clocks(sides)
    late_source_clocks = [x for x in clocks if decision and any(_utc(x.get(k)) and _utc(x[k]) > decision for k in ("observedAt", "availableAsOf"))]
    row = {
        "model_evidence_schema": "MLB_V18_WAGER_MODEL_EVIDENCE_V1",
        "forecast_object_sha256": logical, "forecast_dir": str(directory),
        "game_id": forecast.get("gameId"), "source_game_id": forecast.get("sourceGameId"),
        "input_era": "CURRENT_SOURCE_V18" if feature_ref else "LEGACY_TEMPLATE_V18_SEPARATE",
        "forecast_created_at": forecast.get("forecastCreatedAt"), "input_captured_at": forecast.get("capturedAt"),
        "scheduled_start": forecast.get("scheduledStart"), "decision_utc": decision_utc,
        "forecast_before_decision": None if not decision or not created else created <= decision,
        "input_before_decision": None if not decision or not captured else captured <= decision,
        "forecast_minutes_before_start": (start - created).total_seconds() / 60 if start and created else None,
        "decision_minutes_before_start": (start - decision).total_seconds() / 60 if start and decision else None,
        "source_clock_after_decision_count": len(late_source_clocks) if decision else None,
        "manifest_physical_sha256": _ref(manifest_path)["sha256"],
        "artifact_verification": "MANIFEST_IDENTITY_AND_ALL_CHILD_BYTES_VERIFIED",
        "artifact_refs_json": _json(children), "model_identity_json": _json(model),
        "model_artifact_verification_json": _json(model_verified),
        "pa_model_sha256": model.get("paArtifact", {}).get("sha256") or forecast.get("parentAuthority", {}).get("paModelSha256"),
        "transition_model_sha256": model.get("transitionArtifact", {}).get("sha256") or forecast.get("parentAuthority", {}).get("transitionModelSha256"),
        "parent_bundle_sha256": model.get("parentBundleSha256") or forecast.get("parentAuthority", {}).get("bundleSha256"),
        "treatment_manifest_sha256": model.get("treatmentManifestSha256"),
        "frozen_prior_checksum": model.get("frozenPriorChecksum"), "frozen_semantic_checksum": model.get("frozenSemanticChecksum"),
        "feature_snapshot_json": _json(feature_ref), "feature_snapshot_status": feature_status,
        "source_cutoff_json": _json(execution.get("sourceCutoff", forecast.get("sourceCutoff"))),
        "source_clocks_json": _json(clocks), "late_source_clocks_json": _json(late_source_clocks),
        "teams_json": _json(forecast.get("teams", {})), "starters_json": _json(forecast.get("starters", {})),
        "lineup_authorities_json": _json(forecast.get("lineupAuthorities", {})),
        "lineups_json": _json({side.get("side"): side.get("lineup", []) for side in sides}),
        "recorded_coverage_json": _json(composition.get("coverage")),
        "recorded_blockers_json": _json(composition.get("blockers")),
        "raw_starting_template_rows": len(raw), "treated_starting_template_rows": len(treated),
        "raw_missing_cells": sum(_counts(raw).values()), "treated_missing_cells": sum(_counts(treated).values()),
        "raw_missing_by_field_json": _json(_counts(raw)), "treated_missing_by_field_json": _json(_counts(treated)),
        "raw_affirmative_missing_insufficient_indicator_cells": sum(_indicators(raw).values()),
        "raw_affirmative_missing_insufficient_by_field_json": _json(_indicators(raw)),
        "field_report_template_rows": len(reports),
        "field_report_status_counts_json": _json(dict(Counter(f.get("status") for f in fields))),
        "explicit_legitimate_missing_cells": sum(f.get("status") == "EXPLICIT_LEGITIMATE_MISSING_FROZEN_TREATMENT_REQUIRED" for f in fields),
        "physical_missing_flag_cells": sum(f.get("physicalValueMissing") is True for f in fields),
        "unsupported_field_cells": sum(f.get("supported") is False for f in fields),
        "generic_median_mode_fallbacks_recorded": execution.get("genericMedianModeFallbacks"),
        "generic_imputation_recorded": composition.get("genericImputation"),
        "historical_templates_borrowed_recorded": composition.get("historicalTemplatesBorrowed"),
        "annual_player_support_json": _json(list(annual.values())), "window_player_support_json": _json(list(windows.values())),
        "annual_prior_missing_unique_batters": sum(r["role"] == "batter" and r["status"] == "NO_ELIGIBLE_FROZEN_FD1_PRIOR" for r in annual.values()),
        "annual_prior_missing_unique_pitchers": sum(r["role"] == "pitcher" and r["status"] == "NO_ELIGIBLE_FROZEN_FD1_PRIOR" for r in annual.values()),
        "history_complete_through": history.get("completeThrough"), "history_all_complete_recorded": history.get("allHistoryComplete"),
        "history_limitation_json": _json(history.get("limitations", [])),
        "initial_pa_class_order_json": _json(execution.get("initialPaClassOrder")),
        "initial_pa_probabilities_json": _json(execution.get("initialPaProbabilities")),
        "simulation_count": len(home), "simulation_seed": forecast.get("simulation", {}).get("seed"),
        "p_home_win": probability.get("homeWin"), "p_away_win": probability.get("awayWin"),
        "mc_home_win_se_recorded": forecast.get("monteCarloUncertainty", {}).get("homeWinProbabilityStandardError"),
        "full_game_win_se_recorded": forecast.get("monteCarloUncertainty", {}).get("fullGameWinProbabilityStandardError"),
        "mc_uncertainty_recorded_json": _json(forecast.get("monteCarloUncertainty", {})),
        "mc_uncertainty_scope": "FINITE_SIMULATION_PRECISION_ONLY; NOT_MODEL_INPUT_OR_CALIBRATION_UNCERTAINTY",
        "p_home_draw_reconciliation_abs": probability_delta,
        "retained_expectations_json": _json(forecast.get("expectations", {})),
        "retained_marginal_distributions_json": _json(forecast.get("distributions", {})),
        "paired_distribution_ref_json": _json({**children["execution-inputs.json"], "home_json_pointer": "/population/homeRuns", "away_json_pointer": "/population/awayRuns", "paired_by": "ARRAY_INDEX"}),
        "paired_score_summary_derived_json": _json({"home": _summary(home), "away": _summary(away), "total": _summary(total), "home_margin": _summary(margin)}),
        "pitching_change_rate_away_recorded": population.get("pitchingChangeRateAway"),
        "pitching_change_rate_home_recorded": population.get("pitchingChangeRateHome"),
        "known_limitations_recorded_json": _json(forecast.get("knownLimitations", [])),
        "starter_duration_evidence": "AGGREGATE_PITCHING_CHANGE_RATES_AND_ONE_REPRESENTATIVE_TRACE; NO_ALL_DRAW_STARTER_BF_OR_OUTS_IN_CANONICAL_FORECAST",
        "duration_implementation_context": "V18 monotone policy hook (not a fitted duration model): default expected BF=23; inning/BF/runs/TTO; no change before BF9; cap .95. Context from reviewed implementation, not a per-forecast duration attestation.",
        "bullpen_implementation_context": "Anonymous arithmetic mean of retained staff-template PA probabilities; no named reliever selection, availability or fatigue law. Current source era: up to 8 active nonstarter roster candidates ordered by latest permitted prior appearance then identity.",
        "decision_time_software_deployment_identity": None,
        "not_retained_json": _json(["Per-forecast runtime deployment hash is not present in canonical forecast fields; current deployment is not a historical attestation.", "Full per-draw starter BF/outs and individual bullpen assignment are not in canonical population.", "Current roster active status is not individual bullpen readiness.", "Canonical population has one representative path, not 5,000 retained event traces."]),
        "derived_now_json": _json(["Physical hash verification", "Missing-value and player-support aggregates", "Timestamp comparisons", "Paired-score summaries and probability reconciliation"]),
        "source_payload_links_followed": 0, "outcomes_read": 0,
    }
    for side in ("away", "home"):
        starter = provider.get(side + "Starter", {})
        batters, staff = provider.get(side + "Batters", []), provider.get(side + "Bullpen", [])
        row[side + "_starter_support_json"] = _json(_player_record(starter, "pitcher"))
        row[side + "_batter_support_json"] = _json([_player_record(r, "batter") for r in batters])
        row[side + "_staff_support_json"] = _json([_player_record(r, "pitcher") for r in staff])
        row[side + "_staff_template_count"] = len(staff)
        row[side + "_staff_missing_cells"] = sum(_counts(staff).values())
        row[side + "_staff_affirmative_missing_insufficient_cells"] = sum(_indicators(staff).values())
        row[side + "_staff_affirmative_missing_insufficient_by_field_json"] = _json(_indicators(staff))
        row[side + "_starter_prior_missing"] = starter.get("pitcher_prior_missing")
        row[side + "_starter_last250_bf_count"] = starter.get("pitcher_last250_bf_count")
        row[side + "_starter_prior_bf_count"] = starter.get("pitcher_prior_bf_count")
        row[side + "_batter_prior_missing_count"] = sum(r.get("batter_prior_missing") == 1 for r in batters)
        row[side + "_batter_low_window_count"] = sum(r.get("batter_last100_insufficient") == 1 for r in batters)
        participant = next((s for s in sides if s.get("side") == side.upper()), {})
        lineup = participant.get("lineup", [])
        orders = [r.get("batting_order") for r in lineup]
        row[side + "_starter_confirmation_status"] = forecast.get("starters", {}).get(side.upper(), {}).get("confirmationState")
        row[side + "_lineup_status"] = forecast.get("lineupAuthorities", {}).get(side.upper(), {}).get("status")
        row[side + "_lineup_count"] = len(lineup)
        row[side + "_ordered_lineup_slot_count"] = len({int(x) for x in orders if x is not None})
        row[side + "_ordered_lineup_complete_1_to_9"] = sorted(int(x) for x in orders if x is not None) == list(range(1, 10))
    row["evidence_gaps_json"] = _json(gaps)
    observer = _observer_metadata(directory, logical, decision, forecast, population)
    row["prospective_observer_status"] = observer["status"]
    row["prospective_observer_metadata_json"] = _json(observer)
    row["observer_registered_at"] = observer.get("registered_at")
    row["observer_registered_before_decision"] = observer.get("registered_before_decision")
    row["observer_created_after_decision"] = observer.get("created_after_decision")
    row["observer_registered_before_start"] = observer.get("registered_before_start")
    row["observer_registered_by_t15"] = observer.get("registered_at_or_before_decision_cutoff_t15")
    row["observer_registered_by_t5"] = observer.get("registered_at_or_before_research_cutoff_t5")
    for side in ("away", "home"):
        summary = observer.get("starting_pitcher_summary_derived", {}).get(side.upper(), {})
        row[side + "_starter_bf_summary_derived_json"] = _json(summary.get("BATTERS_FACED"))
        row[side + "_starter_k_summary_derived_json"] = _json(summary.get("STRIKEOUTS"))
        row[side + "_starter_bf_mean_derived"] = summary.get("BATTERS_FACED", {}).get("mean")
        row[side + "_starter_k_mean_derived"] = summary.get("STRIKEOUTS", {}).get("mean")
        row[side + "_anonymous_relief_summary_derived_json"] = _json(observer.get("anonymous_relief_summary_derived", {}).get(side.upper()))
    return row

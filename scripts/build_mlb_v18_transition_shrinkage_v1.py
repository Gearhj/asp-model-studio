"""Build and score the fixed V18 hierarchical transition research component."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_starter_duration_paired_scoring import empirical_crps
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_daily_slate import _verify_existing_object
from server.sports_current_statcast.mlb_starter_duration_paired_simulation import (
    POPULATION_ARRAYS,
    REFERENCE,
    simulate_research_arm,
)
from server.sports_current_statcast.mlb_v18_current_publication import CurrentV18Engine
from server.sports_current_statcast.mlb_v18_ensemble_candidate import build_saved_historical_replay_provider
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.hierarchical_transition import HierarchicalTransitionModel

OUT = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"
PROTOCOL = OUT / "protocol.json"
FORECAST_OBJECTS = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/objects/sha256"
AISPE = Path(r"C:\Users\james\ai-sports-predictor\outputs\v18-error-analysis-evidence")
AISPE_MANIFEST_SHA256 = "722a7bbb1f8fa1fcc98ff59a3436ed92fc35fa7b9c88304cf6b537dc3e7e54e4"
PROTECTED = {"823343", "824235", "822693"}
PILOT = "7323d8f3-9b24-464d-903e-fe290913d73b"
COMPONENT_ID = "MLB_BASE_OUT_TRANSITION_HIERARCHICAL_SHRINKAGE_V1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha(path), "bytes": path.stat().st_size}


def put(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Immutable artifact conflict: {path}")
        return
    with path.open("xb") as stream:
        stream.write(raw)


def _dist(model: Any, outcome: str, outs: int, base: int) -> tuple[list[tuple[int, int, int]], np.ndarray]:
    rows = model.distribution(outcome, outs, base)["transitions"]
    transitions = [(int(r["outsAdded"]), int(r["baseMaskAfter"]), int(r["runs"])) for r in rows]
    return transitions, np.asarray([r["probability"] for r in rows], dtype=float)


def transition_fit_source_scores(model: Any, source: bt.TransitionModel) -> dict[str, Any]:
    """Score against the component's own fit counts; localization only."""
    n = 0
    log_loss = brier = run_error = run_abs_error = mode_correct = 0.0
    dp_n = dp_brier = dp_bias = 0.0
    for key, counts in source.cells.items():
        outcome, outs_text, base_text = key.split("|")
        outs, base = int(outs_text), int(base_text)
        transitions, probabilities = _dist(model, outcome, outs, base)
        index = {t: i for i, t in enumerate(transitions)}
        mode = transitions[int(np.argmax(probabilities))]
        predicted_runs = float(sum(t[2] * p for t, p in zip(transitions, probabilities)))
        dp_probability = float(sum(p for t, p in zip(transitions, probabilities) if t[0] == 2))
        opportunity = outcome == "BIP_OUT" and outs < 2 and bool(base & 1)
        for observed, count in counts.items():
            if observed not in index:
                continue
            count = int(count)
            p_observed = float(probabilities[index[observed]])
            n += count
            log_loss += count * -math.log(max(p_observed, 1e-300))
            brier += count * (float(np.dot(probabilities, probabilities)) + 1.0 - 2.0 * p_observed)
            run_error += count * (predicted_runs - observed[2])
            run_abs_error += count * abs(predicted_runs - observed[2])
            mode_correct += count * float(mode == observed)
            if opportunity:
                label = float(observed[0] == 2)
                dp_n += count
                dp_brier += count * (dp_probability - label) ** 2
                dp_bias += count * (dp_probability - label)
    return {
        "status": "FIT_SOURCE_RECONSTRUCTION_SELECTION_USE_NONE",
        "observations": n,
        "transitionLogLoss": log_loss / n,
        "summedTransitionBrier": brier / n,
        "runConversionSignedError": run_error / n,
        "runConversionMae": run_abs_error / n,
        "baseMaskAndRunModeAccuracy": mode_correct / n,
        "doublePlayOpportunities": int(dp_n),
        "doublePlayOpportunityBrier": dp_brier / dp_n,
        "doublePlayProbabilityBias": dp_bias / dp_n,
    }


def _allowed_identity(identity: Mapping[str, Any]) -> bool:
    keys = [identity.get("canonicalGameId"), identity.get("mlbGamePk")]
    day = str(identity.get("eventDate") or "")[:10]
    return (all(final_oot_eligible_key_mask(keys)) and keys[0] != PILOT
            and bool(day) and not "2026-08-14" <= day <= "2026-08-27")


def _identity_before_payload(line: str) -> dict[str, Any]:
    """Decode only the non-nested identity member before admitting a JSONL row.

    The transport file has upstream SQL exclusions. This extra gate makes the
    local cohort/pilot rule precede JSON decoding of any outcome member.
    """
    match = re.search(r'(?<!\\)"identity"\s*:\s*', line)
    if match is None:
        raise ValueError("Outcome record has no identity metadata")
    identity, _ = json.JSONDecoder().raw_decode(line, match.end())
    if not isinstance(identity, dict):
        raise ValueError("Invalid outcome record identity")
    return identity


def _freeze_forecast_identities(wanted: list[str]) -> dict[str, dict[str, str]]:
    eligible = {}
    for object_sha in wanted:
        directory = _verify_existing_object(FORECAST_OBJECTS.parent.parent, {
            "relativePath": f"objects/sha256/{object_sha}", "objectSha256": object_sha})
        forecast = json.loads((directory / "forecast.json").read_text(encoding="utf-8"))
        identity = {"canonicalGameId": str(forecast["gameId"]),
                    "mlbGamePk": str(forecast["sourceGameId"]),
                    "eventDate": str(forecast["scheduledStart"])[:10]}
        if not _allowed_identity(identity):
            raise ValueError("Protected, sealed or pilot game in frozen comparison cohort")
        if identity["canonicalGameId"] in eligible:
            raise ValueError("Duplicate game in frozen comparison cohort")
        eligible[identity["canonicalGameId"]] = {
            **identity, "forecastId": "mlb-v18-daily-" + object_sha}
    return eligible


def _aisp_outcomes(eligible: Mapping[str, Mapping[str, str]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    manifest_path = AISPE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sha256") != AISPE_MANIFEST_SHA256:
        raise ValueError("AISP evidence manifest identity changed")
    if set(manifest["selectionRules"]["permanentExclusions"]) != PROTECTED:
        raise ValueError("AISP evidence does not enforce the permanent exclusions")
    if manifest["guarantees"].get("sealedOutcomesQueried") is not False:
        raise ValueError("Sealed Final OOT outcomes were queried")
    data = AISPE / manifest["file"]
    if data.stat().st_size != manifest["bytes"] or sha(data) != manifest["sha256"]:
        raise ValueError("AISP outcome evidence checksum mismatch")
    outcomes: dict[str, dict[str, Any]] = {}
    for line in data.open(encoding="utf-8"):
        identity = _identity_before_payload(line)
        game_id = str(identity["canonicalGameId"])
        if not _allowed_identity(identity) or game_id not in eligible:
            continue
        game_pk = str(identity["mlbGamePk"])
        if game_pk != eligible[game_id]["mlbGamePk"]:
            raise ValueError("Outcome identity differs from frozen forecast")
        row = json.loads(line)
        if row["forecast"]["forecastId"] != eligible[game_id]["forecastId"]:
            continue
        outcome = row.get("outcome") or {}
        if outcome.get("eligible") and outcome.get("homeScore") is not None and outcome.get("awayScore") is not None:
            if game_id in outcomes:
                raise ValueError("Duplicate eligible outcome revision for frozen forecast")
            outcomes[game_id] = {
                "homeScore": int(outcome["homeScore"]),
                "awayScore": int(outcome["awayScore"]),
                "homeWin": int(bool(outcome["homeWin"])),
                "gamePk": game_pk,
                "source": outcome.get("source"),
                "payloadChecksum": outcome.get("payloadChecksum"),
                "cohort": row.get("cohort"),
            }
    return outcomes, {"manifest": ref(manifest_path), "records": ref(data)}


def _score_population(population: Mapping[str, Any], truth: Mapping[str, Any]) -> dict[str, Any]:
    home = np.asarray(population["homeRuns"], dtype=float)
    away = np.asarray(population["awayRuns"], dtype=float)
    if home.shape != (5000,) or away.shape != (5000,):
        raise ValueError("Exactly 5,000 paired draws required")
    actual_home, actual_away = int(truth["homeScore"]), int(truth["awayScore"])
    p_home = float((home > away).mean())
    y = float(truth["homeWin"])
    arrays = {"home": home, "away": away, "total": home + away, "margin": home - away}
    actual = {"home": actual_home, "away": actual_away,
              "total": actual_home + actual_away, "margin": actual_home - actual_away}
    return {
        "homeWinProbability": p_home,
        "winnerLogLoss": float(-(y * math.log(max(p_home, 1e-15)) + (1-y) * math.log(max(1-p_home, 1e-15)))),
        "winnerBrier": float((p_home-y) ** 2),
        **{f"{name}Crps": empirical_crps(values, actual[name]) for name, values in arrays.items()},
        **{f"{name}AbsoluteMeanError": abs(float(values.mean())-actual[name]) for name, values in arrays.items()},
    }


def _mean(rows: list[dict[str, Any]], name: str) -> float:
    return float(np.mean([row[name] for row in rows]))


def build() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    wanted = protocol["gameComparison"]["eligibleForecastObjectSha256"]
    if len(wanted) != 16 or len(set(wanted)) != 16 or PILOT in wanted:
        raise ValueError("Frozen common cohort differs")
    eligible = _freeze_forecast_identities(wanted)
    outcomes, outcome_refs = _aisp_outcomes(eligible)
    with threadpool_limits(limits=4):
        engine = CurrentV18Engine()
        candidate = HierarchicalTransitionModel.from_baseline(
            engine.transition,
            prior_strength=float(protocol["scope"]["priorStrength"]),
            legal_floor=float(protocol["scope"]["legalFloor"]),
        )
        candidate_raw = canonical_json_bytes(candidate.to_dict())
        candidate_sha = hashlib.sha256(candidate_raw).hexdigest()
        candidate_path = OUT / f"components/sha256/{candidate_sha}/transition.json"
        put(candidate_path, candidate_raw)
        component = ref(candidate_path)
        component["componentId"] = COMPONENT_ID

        baseline_component = transition_fit_source_scores(engine.transition, engine.transition)
        changed_component = transition_fit_source_scores(candidate, engine.transition)
        rows: list[dict[str, Any]] = []
        arrays: dict[str, np.ndarray] = {}
        baseline_reproduced = None
        pa_reload_mismatches = 0
        for index, object_sha in enumerate(wanted):
            print(json.dumps({"event": "TRANSITION_COMPARISON_GAME_START", "index": index + 1,
                              "games": len(wanted), "forecastObjectSha256": object_sha}), flush=True)
            directory = FORECAST_OBJECTS / object_sha
            forecast = json.loads((directory / "forecast.json").read_text(encoding="utf-8"))
            snapshot = json.loads((directory / "pregame-evidence.json").read_text(encoding="utf-8"))
            execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest["objectSha256"] != object_sha or forecast["gameId"] == PILOT:
                raise ValueError("Forecast object identity or pilot exclusion differs")
            game_pk = str(forecast["sourceGameId"])
            if game_pk in PROTECTED:
                raise ValueError("Protected game entered simulation cohort")
            feature_ref = execution["featureSnapshot"]
            feature_path = Path(feature_ref["path"])
            if sha(feature_path) != feature_ref["sha256"] or feature_path.stat().st_size != feature_ref["bytes"]:
                raise ValueError("Feature snapshot checksum mismatch")
            feature = json.loads(feature_path.read_text(encoding="utf-8"))
            provider, replay = build_saved_historical_replay_provider(
                engine, snapshot, feature["composition"], execution,
                snapshot_sha256=feature_ref["sha256"],
                original_forecast_created_at=forecast["forecastCreatedAt"],
            )
            pa_reload_mismatches += int(replay["initialProbabilityMismatches"])
            args = dict(game_id=forecast["gameId"], provider=provider, n_sims=5000,
                        master_seed=20260907, arm=REFERENCE,
                        regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=0)
            if index == 0:
                baseline_check = simulate_research_arm(transition_model=engine.transition, **args)
                saved = execution["population"]
                baseline_reproduced = all(np.array_equal(np.asarray(baseline_check[k]), np.asarray(saved[k]))
                                          for k in ("homeRuns", "awayRuns", "innings", "paCounts"))
                if not baseline_reproduced:
                    raise ValueError("Research loop does not reproduce frozen V18 baseline")
            challenger = simulate_research_arm(transition_model=candidate, **args)
            baseline = execution["population"]
            if challenger["illegalStateCount"] or challenger["nonterminationCount"]:
                raise ValueError("Changed transition produced an invalid population")
            truth = outcomes.get(forecast["gameId"])
            if truth is None:
                raise ValueError(f"Governed final absent for fixed game {forecast['gameId']}")
            baseline_score = _score_population(baseline, truth)
            changed_score = _score_population(challenger, truth)
            rows.append({"forecastObjectSha256": object_sha, "gameId": forecast["gameId"],
                         "gamePk": game_pk, "scheduledStart": forecast["scheduledStart"],
                         "truth": truth, "baseline": baseline_score, "change": changed_score})
            for branch, population in (("baseline", baseline), ("change", challenger)):
                for field in ("homeRuns", "awayRuns", "innings", "paCounts"):
                    arrays[f"game_{index:02d}_{branch}_{field}"] = np.asarray(population[field], dtype="<i8")
            print(json.dumps({"event": "TRANSITION_COMPARISON_GAME_COMPLETE", "index": index + 1,
                              "games": len(wanted), "gameId": forecast["gameId"]}), flush=True)

    score_names = ("winnerLogLoss", "winnerBrier", "homeCrps", "awayCrps", "totalCrps", "marginCrps",
                   "homeAbsoluteMeanError", "awayAbsoluteMeanError", "totalAbsoluteMeanError", "marginAbsoluteMeanError")
    summary = {branch: {name: _mean([row[branch] for row in rows], name) for name in score_names}
               for branch in ("baseline", "change")}
    delta = {name: summary["change"][name] - summary["baseline"][name] for name in score_names}
    paired_draw_delta: dict[str, Any] = {}
    for name in ("home", "away", "total", "margin", "homeWin"):
        differences = []
        for index in range(len(rows)):
            bh, ba = arrays[f"game_{index:02d}_baseline_homeRuns"], arrays[f"game_{index:02d}_baseline_awayRuns"]
            ch, ca = arrays[f"game_{index:02d}_change_homeRuns"], arrays[f"game_{index:02d}_change_awayRuns"]
            if name == "home": values = ch - bh
            elif name == "away": values = ca - ba
            elif name == "total": values = (ch+ca) - (bh+ba)
            elif name == "margin": values = (ch-ca) - (bh-ba)
            else: values = (ch > ca).astype(float) - (bh > ba).astype(float)
            differences.append(values)
        values = np.concatenate(differences)
        paired_draw_delta[name] = {"mean": float(values.mean()),
                                   "pairedMonteCarloStandardError": float(values.std(ddof=1)/math.sqrt(len(values)))}

    arrays["game_ids"] = np.asarray([row["gameId"] for row in rows], dtype="U64")
    archive = io.BytesIO()
    np.savez_compressed(archive, **arrays)
    population_raw = archive.getvalue()
    with np.load(io.BytesIO(population_raw), allow_pickle=False) as restored:
        if any(not np.array_equal(restored[name], value) for name, value in arrays.items()):
            raise ValueError("Saved population reload differs")
    component_delta = {name: changed_component[name]-baseline_component[name]
                       for name in ("transitionLogLoss", "summedTransitionBrier", "runConversionSignedError",
                                    "runConversionMae", "baseMaskAndRunModeAccuracy",
                                    "doublePlayOpportunityBrier", "doublePlayProbabilityBias")}
    result = {
        "schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_COMPARISON_V1",
        "componentId": COMPONENT_ID,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "status": "HISTORICAL_PREGAME_REPLAY_FIXED_COMMON_COHORT",
        "verdict": "INSUFFICIENT_EVIDENCE",
        "verdictReason": "The game-level replay is historical and the transition diagnostic reuses fit counts; neither is untouched confirmation.",
        "games": len(rows), "simulationsPerConfigurationPerGame": 5000, "masterSeed": 20260907,
        "baseline": summary["baseline"], "change": summary["change"], "changeMinusBaseline": delta,
        "pairedDrawMeanChange": paired_draw_delta,
        "componentLocalization": {"baseline": baseline_component, "change": changed_component,
                                  "changeMinusBaseline": component_delta},
        "gameResults": rows,
        "verification": {"baselineFirstGameExactReplay": baseline_reproduced,
                         "initialPaProbabilityMismatches": pa_reload_mismatches,
                         "illegalStateCount": 0, "nonterminationCount": 0,
                         "savedPopulationReloadMismatches": 0,
                         "paModelChanged": False, "starterUsageChanged": False,
                         "protectedGamesPresent": False, "pilotOutcomeUsed": False,
                         "finalOotPayloadBytesRead": 0},
        "authority": {"researchShadowOnly": True, "executionAllowedInAisp": False,
                      "wageringAuthority": False, "promotionStatus": "NOT_PROMOTED",
                      "componentFitSource": "ACCEPTED_TRANSITION_FOLD4_COUNTS_2023_2025",
                      "historicalTrainingChronologyCertified": False},
        "componentArtifact": component, "protocol": ref(PROTOCOL), "outcomeEvidence": outcome_refs,
        "uncertainty": "Paired Monte Carlo SE describes finite-draw noise only. It does not measure predictive uncertainty or establish improvement.",
    }
    result_raw = canonical_json_bytes(result)
    population_sha = hashlib.sha256(population_raw).hexdigest()
    result_sha = hashlib.sha256(result_raw).hexdigest()
    directory = OUT / f"objects/sha256/{result_sha}"
    put(directory / "comparison.json", result_raw)
    put(directory / "populations.npz", population_raw)
    manifest = {
        "schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_MANIFEST_V1",
        "resultSha256": result_sha, "componentId": COMPONENT_ID,
        "files": {"comparison.json": {"sha256": result_sha, "bytes": len(result_raw)},
                  "populations.npz": {"sha256": population_sha, "bytes": len(population_raw)}},
        "componentArtifact": component, "protocol": ref(PROTOCOL),
        "researchShadowOnly": True, "executionAllowedInAisp": False,
        "wageringAuthority": False, "promotionStatus": "NOT_PROMOTED",
    }
    manifest_raw = canonical_json_bytes(manifest)
    put(directory / "manifest.json", manifest_raw)
    current = {"schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_CURRENT_V1",
               "resultSha256": result_sha, "result": ref(directory / "comparison.json"),
               "manifest": ref(directory / "manifest.json"), "population": ref(directory / "populations.npz"),
               "component": component, "verdict": result["verdict"]}
    (OUT / "current.json").write_bytes(canonical_json_bytes(current))
    return current


if __name__ == "__main__":
    print(json.dumps(build(), indent=2), flush=True)

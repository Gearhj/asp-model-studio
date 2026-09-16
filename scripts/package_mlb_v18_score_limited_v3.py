"""Package a frozen, supported score-limited V18 comparison for research exchange.

This producer does not simulate, read game outcomes, write AISP, or publish to
the exchange. V3 is a proposed narrow consumer extension, not current support.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np

from scripts.package_mlb_v18_transition_adapter_v2 import (
    canonical, reference, verify_ref, read_json, aware, immutable,
    _baseline_authority, _distribution, _summary,
)
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_score_limited import COMPONENT_ID, MIN_RETAINED_DRAWS

OUTPUT = ROOT / "outputs/mlb-v18-score-limited-v1/adapter-v3"
CONFIGURATION_ID = "mlb-v18-score-limited-v1"
COMPONENT_SOURCE = ROOT / "server/sports_current_statcast/mlb_v18_score_limited.py"
FLAGS = {
    "executionAllowed": False, "wageringAuthority": False,
    "activatesModel": False, "executionAllowedInAISP": False,
    "candidateAuthority": False,
}

CONTRACT = """# Proposed score-limited V3 candidate contract

This is a separate research configuration, `mlb-v18-score-limited-v1`.
No current AISP consumer support or import is claimed.

The narrow extension to `server/app/shadow_import/mlb_ensemble_candidate.py`
is to accept `AISP_MLB_ENSEMBLE_CANDIDATE_HANDOFF_V3` and permit `SCORE_LIMIT`
under V3 only, preserving V1/V2 behavior. Keep the existing V1 child forecast
and object-manifest schemas, frozen-system authority and per-game baseline
binding checks, immutable hashes, identity checks and false authority flags.

`SCORE_LIMIT` is post-simulation whole-game filtering. It is neither DURATION,
TRANSITION nor CALIBRATION. The rule excludes an entire original draw when any
played half-inning exceeds the half-inning limit OR either team's final score
exceeds the team-game limit. Equality is accepted; both teams use identical
limits. Scores, event sequences and stopping behavior are never modified.

`baselineBinding.simulationCount` remains 5000. The child
`simulation.simulationCount` and `retainedSimulationCount` equal the actual
accepted count; `sourceSimulationCount` remains 5000. Every candidate marginal,
expectation and win probability uses the accepted count as its denominator.
No retained draw means no supported forecast. This configuration also refuses
fewer than the rule's fixed minimum retained draws (initially 1000).

The checksummed `accepted-population.npz` contains the unchanged 5000 baseline
scores, innings and PA counts; ascending `accepted_indices`; a length-5000
Boolean `acceptance_mask`; and the indexed candidate subsets. The consumer
should verify the mask/index equality, candidate array equality to each
baseline array indexed by accepted indices, unchanged frozen-baseline arrays,
integer nonnegative scores, terminal non-ties, counts and probability mass.
Full inning arrays remain in `source-population.npz`; the source-sidecar binds
these to the exact ordinary V18 baseline. Other per-draw summaries are linked
through these original indices. Only the original representative trace was
retained; this package does not claim full event sequences were stored.

The candidate's `publishedAt` is the immutable local comparison freeze, as in
the existing candidate convention, and is explicitly labelled. The later
exchange publication receipt supplies the actual delivery time. Prospective
classification requires rule publication before filtering, source capture
before the original policy cutoff, and comparison freeze plus package creation
before that same cutoff. The rule is not backdated to baseline publication.

Verify the exact package against the existing baseline authority and ordinary
baseline import. File it as research evidence under its distinct configuration;
display the source count, retained count, exclusion rate, integer limits,
Monte Carlo precision and false authority flags. Return an import receipt with
the exact handoff/configuration/forecast/baseline identities. Research import
and display are not production activation or promotion. No AISP settings,
positions, bankroll, selection policy or existing component studies change.
"""


def _check(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _ref_bytes(item: dict) -> bytes:
    return verify_ref(item).read_bytes()


def build(execution_ref: dict) -> dict:
    """Build locally from a checksummed execution descriptor; no outcome access."""
    execution_path = verify_ref(execution_ref)
    e = read_json(execution_path)
    _check(e.get("status") == "SUPPORTED", "SUPPORTED_FILTER_EXECUTION_REQUIRED")
    _check(e.get("componentIdentity") == COMPONENT_ID,
           "EXECUTED_SCORE_LIMIT_COMPONENT_IDENTITY_REQUIRED")
    _check("componentSource" in e and e["componentSource"] == reference(COMPONENT_SOURCE),
           "EXECUTED_SCORE_LIMIT_COMPONENT_SOURCE_MISMATCH")
    verify_ref(e["componentSource"])
    _check(e.get("classification") == "PROSPECTIVE_SCORE_LIMITED_RESEARCH",
           "PROSPECTIVE_CLASSIFICATION_REQUIRED")
    _check(all(final_oot_eligible_key_mask([e["gameId"], str(e["sourceGameId"])])),
           "WHOLE_GAME_QUARANTINE")
    _check(not "2026-08-14" <= str(e["scheduledStartUtc"])[:10] <= "2026-08-27",
           "SEALED_FINAL_OOT_DATE")
    for flag in FLAGS:
        _check(e.get(flag, False) is False, "RESEARCH_AUTHORITY_REQUIRED:" + flag)
    _check(e.get("outcomesRead", False) is False, "OUTCOME_FREE_EXECUTION_REQUIRED")
    clock = datetime.now(timezone.utc)
    cutoff = aware(e["deadlineUtc"])
    _check(aware(e["createdAtUtc"]) <= aware(e["frozenAtUtc"]) <= clock < cutoff
           < aware(e["scheduledStartUtc"]), "PROSPECTIVE_FILTER_CLOCKS_INVALID")

    rule = read_json(verify_ref(e["rule"]))
    rule_publication = read_json(verify_ref(e["rulePublication"]))
    # An earlier timestamp alone does not establish publication of this rule.
    _check(rule_publication.get("status") == "PUBLISHED_RULE"
           and rule_publication.get("rule") == e["rule"],
           "SUCCESSFUL_EXACT_RULE_PUBLICATION_REQUIRED")
    _check("deliveredRule" in rule_publication, "DELIVERED_RULE_BYTES_REQUIRED")
    delivered_rule = reference(verify_ref(rule_publication["deliveredRule"]))
    _check(delivered_rule["sha256"] == e["rule"]["sha256"]
           and delivered_rule["bytes"] == e["rule"]["bytes"],
           "DELIVERED_RULE_DIFFERS_FROM_EXECUTED_RULE")
    publication_clock = rule_publication.get("publishedAtUtc")
    _check(publication_clock is not None and aware(publication_clock) <= aware(e["createdAtUtc"]),
           "RULE_PUBLICATION_MUST_PRECEDE_FILTER_EXECUTION")
    _check(aware(rule["frozenAtUtc"]) <= aware(publication_clock),
           "RULE_FREEZE_MUST_PRECEDE_PUBLICATION")
    limits = rule["limits"]
    _check(all(isinstance(limits[k], int) and not isinstance(limits[k], bool)
               and limits[k] >= 0 for k in
               ("maxRunsPerPlayedHalfInning", "maxRunsPerTeamGame")),
           "FIXED_INTEGER_SCORE_LIMITS_REQUIRED")
    minimum = rule.get("minimumRetainedDraws")
    _check(isinstance(minimum, int) and not isinstance(minimum, bool)
           and minimum == MIN_RETAINED_DRAWS, "FROZEN_COMPONENT_MINIMUM_RETAINED_DRAWS_REQUIRED")

    b = load_baseline(e["baselineObjectSha256"])
    f = b["forecast"]
    _check(str(f["sourceGameId"]) == str(e["sourceGameId"])
           and f["gameId"] == e["gameId"], "EXACT_BASELINE_GAME_REQUIRED")
    _check(reference(b["directory"] / "forecast.json") == e["baselineForecast"],
           "EXACT_BASELINE_FORECAST_BYTES_REQUIRED")
    _check(reference(b["directory"] / "execution-inputs.json") == e["sourceExecutionInputs"],
           "EXACT_BASELINE_EXECUTION_BYTES_REQUIRED")
    _check(f["sourceCutoff"] == e["sourceCutoff"] == b["execution"]["sourceCutoff"],
           "UNCHANGED_SOURCE_CUTOFF_REQUIRED")
    _check(aware(f["scheduledStart"]) == aware(e["scheduledStartUtc"]),
           "ORIGINAL_START_REQUIRED")
    _check(cutoff == aware(f["scheduledStart"])-timedelta(minutes=15),
           "ORIGINAL_FIFTEEN_MINUTE_CUTOFF_REQUIRED")
    _check(e["baselineForecastId"] == "mlb-v18-daily-" + e["baselineObjectSha256"],
           "EXACT_BASELINE_FORECAST_ID_REQUIRED")
    _check(e["featureSnapshot"] == b["execution"]["featureSnapshot"],
           "EXACT_BASELINE_FEATURE_SNAPSHOT_REQUIRED")
    _check(aware(f["capturedAt"]) < cutoff, "ORIGINAL_CAPTURE_MUST_PRECEDE_CUTOFF")
    _check(int(f["simulation"]["count"]) == int(e["sourceSimulationCount"]) == 5000,
           "EXACT_5000_SOURCE_POPULATION_REQUIRED")
    for name in ("sourceSidecar", "sourcePopulation", "acceptedPopulation", "featureSnapshot"):
        verify_ref(e[name])
    source_sidecar = read_json(verify_ref(e["sourceSidecar"]))
    _check(source_sidecar["baselineObjectSha256"] == e["baselineObjectSha256"]
           and source_sidecar["gameId"] == e["gameId"]
           and str(source_sidecar["sourceGameId"]) == str(e["sourceGameId"]),
           "DIAGNOSTIC_SIDECAR_BASELINE_BINDING_MISMATCH")
    declared_populations = [source_sidecar.get(k) for k in
                           ("population", "parentPopulation", "enrichedPopulation")]
    _check(e["sourcePopulation"] in declared_populations,
           "DIAGNOSTIC_POPULATION_NOT_BOUND_BY_SIDECAR")

    arrays = {}
    with np.load(verify_ref(e["acceptedPopulation"]), allow_pickle=False) as z:
        indices = np.asarray(z["accepted_indices"])
        mask = np.asarray(z["acceptance_mask"])
        _check(mask.shape == (5000,) and mask.dtype == np.dtype(bool), "BOOLEAN_SOURCE_ACCEPTANCE_MASK_REQUIRED")
        _check(indices.ndim == 1 and np.issubdtype(indices.dtype, np.integer)
               and np.array_equal(indices, np.flatnonzero(mask)), "ACCEPTED_INDICES_MUST_MATCH_SOURCE_MASK")
        count = len(indices)
        _check(minimum <= count <= 5000 and count == int(e["retainedDrawCount"]),
               "INSUFFICIENT_OR_MISMATCHED_RETAINED_DRAWS")
        for key in ("homeRuns", "awayRuns", "innings", "paCounts"):
            base = np.asarray(z["baseline_" + key])
            accepted = np.asarray(z["accepted_" + key])
            _check(base.shape == (5000,) and np.array_equal(base, b["baseline"][key]),
                   "BASELINE_DRAW_IDENTITY_MISMATCH:" + key)
            _check(accepted.shape == (count,) and np.array_equal(accepted, base[indices]),
                   "ACCEPTED_DRAW_WAS_MODIFIED:" + key)
            arrays[key] = accepted
    home, away = arrays["homeRuns"], arrays["awayRuns"]
    _check(np.all(home != away) and np.all(home >= 0) and np.all(away >= 0)
           and np.issubdtype(home.dtype, np.integer) and np.issubdtype(away.dtype, np.integer),
           "TERMINAL_INTEGER_NONTIED_GAME_SCORES_REQUIRED")
    with np.load(verify_ref(e["sourcePopulation"]), allow_pickle=False) as source:
        _check(all(key in source for key in ("runs", "half_innings_started", "terminal_reason",
                                             "home_runs", "away_runs", "innings", "pa_counts")),
               "REQUIRED_SOURCE_COUNTERS_MISSING")
        runs = np.asarray(source["runs"])
        played = np.asarray(source["half_innings_started"])
        terminal = np.asarray(source["terminal_reason"])
        _check(runs.ndim == 3 and runs.shape[:2] == (5000, 2) and runs.shape[2] > 0
               and np.issubdtype(runs.dtype, np.integer) and np.all(runs >= 0),
               "FULL_NONNEGATIVE_INTEGER_INNING_COUNTER_POPULATION_REQUIRED")
        _check(played.shape == runs.shape and np.all((played == 0) | (played == 1))
               and np.all(runs[played == 0] == 0), "PLAYED_HALF_INNING_COUNTERS_INVALID")
        _check(terminal.shape == (5000,) and np.all(np.isin(terminal, (1, 2, 3))),
               "ALL_SOURCE_GAMES_MUST_COMPLETE_NATURALLY")
        _check(np.array_equal(source["home_runs"], b["baseline"]["homeRuns"])
               and np.array_equal(source["away_runs"], b["baseline"]["awayRuns"])
               and np.array_equal(source["innings"], b["baseline"]["innings"])
               and np.array_equal(source["pa_counts"], b["baseline"]["paCounts"])
               and np.array_equal(runs.sum(axis=2)[:, 0], source["away_runs"])
               and np.array_equal(runs.sum(axis=2)[:, 1], source["home_runs"]),
               "SOURCE_INNING_COUNTERS_DO_NOT_RECONCILE_TO_BASELINE")
        last_played = np.where(played.any(axis=1), np.arange(1, runs.shape[2] + 1), 0).max(axis=1)
        _check(np.array_equal(last_played, b["baseline"]["innings"])
               and np.all(played[:, 0].sum(axis=1) > 0) and np.all(played[:, 1].sum(axis=1) > 0),
               "COMPLETED_GAME_PLAYED_INNINGS_DO_NOT_RECONCILE")
        expected_mask = (~((runs > limits["maxRunsPerPlayedHalfInning"]) & (played == 1)).any(axis=(1, 2))
                         & (np.asarray(b["baseline"]["homeRuns"]) <= limits["maxRunsPerTeamGame"])
                         & (np.asarray(b["baseline"]["awayRuns"]) <= limits["maxRunsPerTeamGame"]))
        _check(np.array_equal(mask, expected_mask), "ACCEPTANCE_MASK_DOES_NOT_IMPLEMENT_FROZEN_RULE")
    summary = _summary(home, away)
    for key, value in summary.items():
        _check(key in e["summary"] and np.isclose(value, e["summary"][key], rtol=0, atol=1e-12),
               "ACCEPTED_POPULATION_SUMMARY_MISMATCH:" + key)
    _check(np.isclose(e["exclusionRate"], 1-count/5000, rtol=0, atol=1e-12),
           "EXCLUSION_DENOMINATOR_MISMATCH")

    baseline_authority, authority_refs = _baseline_authority(f)
    config = {
        "schemaVersion": "MLB_V18_SCORE_LIMIT_ADAPTER_CONFIGURATION_V3",
        "configurationId": CONFIGURATION_ID, "componentId": COMPONENT_ID,
        "componentSource": e["componentSource"], "componentFile": "score-limit-component.py",
        "componentRole": "SCORE_LIMIT", "baseline": baseline_authority,
        "rule": e["rule"], "limits": limits, "minimumRetainedDraws": minimum,
        "mechanism": "POST_SIMULATION_SYMMETRIC_WHOLE_GAME_REJECTION",
        "calibrationChanged": False, "durationChanged": False, "transitionChanged": False,
        "sourceSimulationCount": 5000, "seed": f["simulation"]["seed"],
        "packager": reference(__file__), **FLAGS,
    }
    config_bytes = canonical(config)
    config_sha = hashlib.sha256(config_bytes).hexdigest()
    package_key = hashlib.sha256(canonical({"executionSha256": execution_ref["sha256"],
                                           "configurationSha256": config_sha})).hexdigest()
    package_root = OUTPUT / "packages/sha256" / package_key
    existing_receipt = package_root / "package-receipt.json"
    if existing_receipt.exists():
        saved = read_json(existing_receipt)
        _check(saved["sourceExecution"] == execution_ref
               and saved["configurationSha256"] == config_sha,
               "EXISTING_PACKAGE_BINDING_MISMATCH")
        for descriptor in saved["artifacts"]:
            verify_ref(descriptor)
        return {**saved, "receipt": reference(existing_receipt)}
    parent = f["parentAuthority"]
    child = {
        "schemaVersion": "MLB_ENSEMBLE_CANDIDATE_GAME_FORECAST_V1", "artifactType": "PROSPECTIVE",
        "forecastId": "mlb-v18-score-limited-" + execution_ref["sha256"],
        "baselineForecastId": "mlb-v18-daily-" + e["baselineObjectSha256"],
        "canonicalGameId": f["gameId"], "eventId": f["gameId"], "sourceGameId": str(f["sourceGameId"]),
        "season": aware(f["scheduledStart"]).year,
        "homeTeam": f["teams"]["HOME"]["uuid"], "awayTeam": f["teams"]["AWAY"]["uuid"],
        "capturedAt": f["capturedAt"], "publishedAt": e["frozenAtUtc"],
        "publicationClockMeaning": "IMMUTABLE_LOCAL_COMPARISON_FREEZE; ACTUAL_EXCHANGE_DELIVERY_IS_RECORDED_SEPARATELY",
        "scheduledStart": f["scheduledStart"], "policyCutoffUtc": e["deadlineUtc"],
        "sourceCutoff": f["sourceCutoff"], "featureVectorSha256": f["snapshotContentSha256"],
        "baselineBinding": {"parentBundleSha256": parent["bundleSha256"],
            "acceptanceProtocolSha256": parent["acceptanceProtocolV2Sha256"],
            "numericalArtifactSha256": e["baselineObjectSha256"],
            "featureVectorSha256": f["snapshotContentSha256"], "simulatorId": "V18_WHOLE_GAME_MONTE_CARLO",
            "simulatorVersion": f["schemaVersion"], "simulatorSeed": f["simulation"]["seed"],
            "simulationCount": 5000, "sourceCutoffUtc": f["capturedAt"]},
        "probabilities": {"homeWin": summary["homeWinProbability"], "awayWin": 1-summary["homeWinProbability"], "tie": 0.0},
        "expectations": {"homeRuns": summary["meanHomeRuns"], "awayRuns": summary["meanAwayRuns"],
            "totalRuns": summary["meanTotalRuns"], "homeMinusAwayRuns": summary["meanRunDifferential"]},
        "distributions": {"homeRunDistribution": _distribution(home), "awayRunDistribution": _distribution(away),
            "totalRunDistribution": _distribution(home+away), "runDifferentialDistribution": _distribution(home-away)},
        "simulation": {"simulatorId": "V18_WHOLE_GAME_SCORE_LIMITED_RESEARCH", "simulatorVersion": config_sha,
            "seed": f["simulation"]["seed"], "simulationCount": count, "sourceSimulationCount": 5000,
            "retainedSimulationCount": count, "excludedSimulationCount": 5000-count,
            "acceptedPopulationFile": "accepted-population.npz", "acceptedIndicesArray": "accepted_indices",
            "acceptanceMaskArray": "acceptance_mask", "sourcePopulationFile": "source-population.npz",
            "monteCarloStandardError": float(np.sqrt(summary["homeWinProbability"]*(1-summary["homeWinProbability"])/count)),
            "uncertainty": e["uncertainty"], "predictiveImprovementEstablished": False},
        "componentsApplied": [{"componentId": "MLB_V18_HGB_PA", "ran": True}, {"componentId": COMPONENT_ID, "ran": True}],
        "eligibility": {"eligible": True, "status": "PREGAME_RESEARCH_SHADOW", "outcomesRead": False},
        "scoreLimits": limits, "exclusions": e["exclusions"], "exclusionRate": e["exclusionRate"],
        "sourceExecutionSha256": execution_ref["sha256"], "knownLimitations": [
            "V18 fitted training and feature chronology remains qualified.",
            "Monte Carlo precision does not bound model or input error.",
            "V3 score-limit consumer support and import remain unconfirmed.",
            "Original accepted draw indices preserve unchanged games; full unsaved PA sequences are not claimed retained."], **FLAGS,
    }
    files = {"forecast.json": canonical(child), "configuration.json": config_bytes,
             "score-limit-component.py": _ref_bytes(e["componentSource"]),
             "execution-receipt.json": execution_path.read_bytes(),
             "baseline-forecast.json": _ref_bytes(e["baselineForecast"]),
             "baseline-execution-inputs.json": _ref_bytes(e["sourceExecutionInputs"]),
             "feature-snapshot.json": _ref_bytes(e["featureSnapshot"]),
             "source-sidecar.json": _ref_bytes(e["sourceSidecar"]),
             "source-population.npz": _ref_bytes(e["sourcePopulation"]),
             "accepted-population.npz": _ref_bytes(e["acceptedPopulation"]),
             "score-limit-rule.json": _ref_bytes(e["rule"]),
             "rule-publication.json": _ref_bytes(e["rulePublication"])}
    artifacts = [{"relativePath": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                 for name, data in sorted(files.items())]
    body = {"schemaVersion": "MLB_ENSEMBLE_CANDIDATE_OBJECT_MANIFEST_V1", "artifacts": artifacts,
            "sourceExecutionSha256": execution_ref["sha256"], "configurationSha256": config_sha}
    object_sha = hashlib.sha256(canonical(body)).hexdigest()
    object_root = package_root / "objects/sha256" / object_sha
    for name, data in files.items():
        immutable(object_root / name, data)
    immutable(object_root / "manifest.json", canonical({**body, "objectSha256": object_sha}))
    immutable(package_root / "configuration.json", config_bytes)
    immutable(package_root / "contract-v3.md", CONTRACT.encode("utf-8"))
    immutable(package_root / "code" / Path(__file__).name, Path(__file__).read_bytes())
    for name, descriptor in authority_refs.items():
        immutable(package_root / "baseline-authority" / name, _ref_bytes(descriptor))
    handoff = {"schemaVersion": "AISP_MLB_ENSEMBLE_CANDIDATE_HANDOFF_V3", "artifactType": "PROSPECTIVE",
        "candidate": {"engineId": "MLB_ENSEMBLE_CANDIDATE", "engineVersion": CONFIGURATION_ID,
            "modelArtifactSha256": config_sha, "manifestSha256": config_sha}, "baseline": baseline_authority,
        "components": [{"componentId": "MLB_V18_HGB_PA", "role": "BASE", "sha256": baseline_authority["modelArtifactSha256"], "status": "FROZEN"},
            {"componentId": COMPONENT_ID, "role": "SCORE_LIMIT", "sha256": e["rule"]["sha256"], "status": "SHADOW_ONLY"}],
        "forecasts": [{"sourceGameId": str(f["sourceGameId"]), "objectSha256": object_sha,
            "relativePath": object_root.relative_to(package_root).as_posix(), "manifestFile": "manifest.json", "forecastFile": "forecast.json"}],
        "configuration": {"relativePath": "configuration.json", "sha256": config_sha, "bytes": len(config_bytes)},
        "contractExtensionRequired": True, "consumerSupportConfirmed": False,
        "publicationClockNote": "Local immutable freeze and exchange delivery have separate clocks; no original baseline clock is changed.", **FLAGS}
    handoff["handoffSha256"] = hashlib.sha256(canonical(handoff)).hexdigest()
    handoff_ref = immutable(package_root / "aisp-handoff.json", canonical(handoff))
    finished = datetime.now(timezone.utc)
    _check(finished < cutoff, "PACKAGE_COMPLETED_AFTER_ORIGINAL_DEADLINE_DO_NOT_PUBLISH")
    receipt = {"schemaVersion": "MLB_V18_SCORE_LIMITED_ADAPTER_PACKAGE_RECEIPT_V3",
        "createdAtUtc": finished.isoformat(), "packageRoot": str(package_root),
        "handoff": handoff_ref, "logicalHandoffSha256": handoff["handoffSha256"],
        "configurationId": CONFIGURATION_ID, "configurationSha256": config_sha,
        "componentId": COMPONENT_ID, "sourceExecution": execution_ref,
        "baselineObjectSha256": e["baselineObjectSha256"], "sourceGameId": str(f["sourceGameId"]),
        "forecastId": child["forecastId"], "originalCutoffUtc": e["deadlineUtc"],
        "sourceSimulationCount": 5000, "retainedDrawCount": count,
        "baselineDrawIdentityExact": True, "acceptedOriginalIndicesExact": True,
        "retainedDrawSummariesReconciled": True, "filterMaskReconciled": True,
        "outcomeReads": 0, "simulationsRun": 0, "modelLoads": 0, "aispWrites": 0,
        "exchangeWrites": 0, "publicationStatus": "LOCAL_PACKAGE_READY",
        "consumerSupportConfirmed": False, "contractExtensionRequired": True, **FLAGS}
    receipt["artifacts"] = [{**reference(p), "relativePath": p.relative_to(package_root).as_posix()}
                            for p in sorted(package_root.rglob("*")) if p.is_file()]
    receipt_ref = immutable(package_root / "package-receipt.json", canonical(receipt))
    return {**receipt, "receipt": receipt_ref}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-ref", type=Path, required=True,
                        help="JSON descriptor containing path, sha256 and bytes of the frozen execution")
    args = parser.parse_args()
    print(json.dumps(build(read_json(args.execution_ref)), indent=2))

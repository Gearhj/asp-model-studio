from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..persistence.db import Database, json_dumps, json_loads, now_iso
from .constants import (
    EXPECTED_PROHIBITED_USES,
    EXPECTED_TOTALS,
    LOGICAL_PACKAGE_ROOT,
    MANIFEST_SHA,
    PROJECT_ID,
    PROJECT_NAME,
    REGISTRATION_ID,
)
from .consumer import ManifestValidationError, ValidatedPackage
from .feature_audit import build_mlb_pa_feature_audit


IDENTITY_BRIDGE_BLOCKER = {
    "limitationId": "MLB_PA_PLAYER_PRIOR_IDENTITY_BRIDGE_ABSENT",
    "scope": "CONSUMER_MODELING",
    "description": (
        "The exchange does not contain a governed cross-family identity bridge from "
        "plate-appearance batter/pitcher identifiers to player_prior identifiers; exact "
        "Y−1 joins are therefore blocked rather than inferred."
    ),
    "blocks": ["MLB_PA_FEATURE_VIEW_V1", "plate_appearance_modeling"],
}

_CURRENT_STATCAST_DATASET_ID = "asp.mlb.statcast.current-pa.v1"


def _historical_current_statcast(registration: Mapping[str, Any]) -> bool:
    metadata = registration.get("metadata_json") or {}
    return (
        registration.get("dataset_id") == _CURRENT_STATCAST_DATASET_ID
        and isinstance(metadata, Mapping)
        and metadata.get("authorityState") == "HISTORICAL"
    )


def _schema_union(family: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for variant in family["physical_variants"]:
        for field in variant["fields"]:
            name = str(field["name"])
            if name not in fields:
                fields[name] = dict(field)
            else:
                existing_types = fields[name].setdefault("physicalDtypes", [fields[name]["dtype"]])
                if field["dtype"] not in existing_types:
                    existing_types.append(field["dtype"])
    return list(fields.values())


def _dataset_totals(validated: ValidatedPackage) -> dict[str, Any]:
    manifest = validated.manifest
    seasons = manifest["seasons"]
    family_rows = {item["family_id"]: item["row_count"] for item in manifest["data_families"]}
    return {
        # Single source of truth: the consumer validates the approved package
        # contains exactly EXPECTED_TOTALS["package_files"] files before
        # register() runs, so the frontend-facing count must reference that same
        # authority instead of an independent literal that could silently drift.
        "packageFiles": EXPECTED_TOTALS["package_files"],
        "parquetFiles": manifest["totals"]["parquet_files"],
        "rows": manifest["totals"]["rows"],
        "parquetBytes": manifest["totals"]["parquet_bytes"],
        "games": sum(item["games"] for item in seasons),
        "plateAppearances": sum(item["plate_appearances"] for item in seasons),
        "transitions": sum(item["transitions"] for item in seasons),
        "starterTargets": sum(item["starter_targets"] for item in seasons),
        "bullpenAppearances": sum(item["bullpen_appearances"] for item in seasons),
        "playerPriors": family_rows["player_prior"],
        "partitions": len(manifest["partitions"]),
        "playerIdentityCoverage": manifest["identity_coverage"]["primary_2023_2025"]["exact_reference_rate"],
    }


def _evidence_coverage(manifest: Mapping[str, Any]) -> dict[str, Any]:
    seasons = manifest["seasons"]
    return {
        "lineups": {
            "status": "PARTIAL_RETROSPECTIVE_TIMING_RISK",
            "bySeason": [
                {
                    "season": item["season"],
                    "covered": item["complete_lineup_coverage"]["covered"],
                    "eligible": item["complete_lineup_coverage"]["eligible"],
                    "ratio": item["complete_lineup_coverage"]["ratio"],
                }
                for item in seasons
            ],
        },
        "starters": {"status": "RETROSPECTIVE_TARGET_ONLY", "rows": sum(item["starter_targets"] for item in seasons)},
        "bullpen": {"status": "RETROSPECTIVE_TARGET_ONLY", "rows": sum(item["bullpen_appearances"] for item in seasons)},
        "weather": {
            "status": "RETROSPECTIVE_TIMING_RISK",
            "bySeason": [
                {
                    "season": item["season"],
                    "covered": item["weather_coverage"]["covered"],
                    "eligible": item["weather_coverage"]["eligible"],
                    "ratio": item["weather_coverage"]["ratio"],
                }
                for item in seasons
            ],
        },
        "playerIdentity": {
            "status": "MANIFEST_REFERENCE_COVERAGE_VALID",
            "exactReferenceRate": manifest["identity_coverage"]["primary_2023_2025"]["exact_reference_rate"],
            "unresolvedReferences": manifest["identity_coverage"]["primary_2023_2025"]["unresolved_references"],
            "detail": "This is publisher manifest/reference coverage only; it does not authorize a plate-appearance to player_prior canonical join.",
        },
        "transitionCoverage": {"status": "VALID", "rows": sum(item["transitions"] for item in seasons)},
        "taxonomyCoverage": {"status": "VALID", "eightClassTaxonomyComplete": manifest["data_quality_evidence"]["eight_class_taxonomy_complete"]},
    }


def _load_active_runtime_audit(registration: Mapping[str, Any], subdir: str) -> dict[str, Any] | None:
    """Authority-gated read of a governed sports-phase4 runtime audit artifact.

    Shared by the catcher-readiness and pitch-sequence-feature projections. Read-only
    and defensive: any absence, parse error, or dataset-authority mismatch yields
    ``None`` so the frontend shows an honest not-run state rather than stale or
    cross-dataset evidence. Never fabricates evidence and never fits a model.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE4_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase4"
        )
        artifact = root / subdir / "latest.audit.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        audit = record.get("audit") if isinstance(record, Mapping) else None
        if not isinstance(audit, Mapping):
            return None
        authority = audit.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        return dict(audit)
    except Exception:
        return None


def _load_active_catcher_readiness(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    return _load_active_runtime_audit(registration, "catcher-readiness")


def _load_active_pitch_sequence_features(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    return _load_active_runtime_audit(registration, "pitch-sequence-features")


def _load_active_process_interactions(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    return _load_active_runtime_audit(registration, "process-interactions")


def _load_active_incremental_study(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 4E E1/E2 incremental-signal research study.

    Reads ``e1-e2-incremental-signal-study/latest.study.json`` (a research study, not a
    model or feature materialization). Read-only and defensive: any absence, parse error,
    or dataset-authority mismatch yields ``None`` for an honest not-run state. Surfaces a
    compact, honest view only -- never a promoted-model or champion-change claim.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE4_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase4"
        )
        artifact = root / "e1-e2-incremental-signal-study" / "latest.study.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("study") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        # Project only the compact, honest fields the surface needs.
        incremental = payload.get("incrementalTable") or {}
        return {
            "studyId": payload.get("studyId"),
            "contractName": payload.get("contractName"),
            "researchOnly": payload.get("researchOnly", True),
            "promotedModel": payload.get("promotedModel", False),
            "changesChampionStatus": payload.get("changesChampionStatus", False),
            "modelPolicy": payload.get("modelPolicy"),
            "population": payload.get("population"),
            "branchFeatureCounts": payload.get("branchFeatureCounts"),
            "anchor": payload.get("anchor"),
            "incrementalRows": incremental.get("rows"),
            "practicalBandDefinition": incremental.get("practicalBandDefinition"),
            "strikeout": payload.get("strikeout"),
            "walkHbpCi": payload.get("walkHbpCi"),
            "bootstrap": payload.get("bootstrap"),
            "decision": payload.get("decision"),
            "nextStep": payload.get("nextStep"),
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


def _load_active_game_replay(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 5 deterministic game-replay engine evidence.

    Reads ``sports-phase5/game-replay/latest.replay.json`` (an engineering/research
    component, not a predictive model or a probabilistic simulator). Read-only and
    defensive: any absence, parse error, or dataset-authority mismatch yields ``None`` for
    an honest not-run state. Surfaces a compact, honest readiness view only.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE5_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase5"
        )
        artifact = root / "game-replay" / "latest.replay.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("replay") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        full = payload.get("full") or {}
        sample = payload.get("sample") or {}
        reference = (full.get("metrics") if full.get("executed") else None) or sample.get("metrics") or {}
        return {
            "replayRunId": payload.get("replayRunId"),
            "contractName": payload.get("contractName"),
            "researchOnly": payload.get("researchOnly", True),
            "probabilisticSimulation": payload.get("probabilisticSimulation", False),
            "readinessStatus": payload.get("readinessStatus"),
            "seasons": payload.get("seasons"),
            "sourceFamily": payload.get("sourceFamily"),
            "fullExecuted": bool(full.get("executed")),
            "gamesAttempted": reference.get("gamesAttempted"),
            "classificationCounts": reference.get("classificationCounts"),
            "exactReplayRate": reference.get("exactReplayRate"),
            "finalScoreExactRate": reference.get("finalScoreExactRate"),
            "inningSequenceExactRate": reference.get("inningSequenceExactRate"),
            "zeroContinuityRate": reference.get("zeroContinuityRate"),
            "mismatchesByCategory": reference.get("mismatchesByCategory"),
            "mismatchForensics": payload.get("mismatchForensics"),
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


def _load_active_base_out_transition(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 5B base-out transition model (simulation component).

    Not a PA model, game forecast, betting model, or Monte Carlo result. Read-only and
    defensive: absence / parse error / authority mismatch -> ``None`` (honest not-run state).
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE5_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase5"
        )
        artifact = root / "base-out-transition" / "latest.transition.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("transition") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        val = payload.get("validation2024") or {}
        frozen = payload.get("frozen2025") or {}
        stress = payload.get("stochasticStressTest") or {}
        return {
            "transitionRunId": payload.get("transitionRunId"),
            "contractName": payload.get("contractName"),
            "readinessStatus": payload.get("readinessStatus"),
            "researchOnly": payload.get("researchOnly", True),
            "parentReplayAuthority": payload.get("parentReplayAuthority"),
            "retainedPolicy": payload.get("retainedPolicy"),
            "devSeasons": payload.get("devSeasons"),
            "developmentRows": payload.get("developmentRows"),
            "primaryStateCells": payload.get("primaryStateCells"),
            "sparseCellCount": payload.get("sparseCellCount"),
            "deterministicRules": payload.get("deterministicRules"),
            "illegalProbabilityMass": (payload.get("legality") or {}).get("illegalProbabilityMass"),
            "validation2024": {k: val.get(k) for k in ("logLoss", "brier", "top1Accuracy", "top2Coverage",
                                                       "runsScoredMae", "outsAddedAccuracy", "baseMaskAfterAccuracy",
                                                       "inningEndingAccuracy", "fallbackUsage", "perOutcome")},
            "frozen2025": {k: frozen.get(k) for k in ("logLoss", "brier", "top1Accuracy", "top2Coverage",
                                                      "runsScoredMae", "outsAddedAccuracy", "baseMaskAfterAccuracy",
                                                      "inningEndingAccuracy", "fallbackUsage")},
            "stochasticStressTest": {k: stress.get(k) for k in ("illegalStateCount", "duplicatedRunnerCount",
                                                                "lostRunnerCount", "totalSampledTransitions")},
            "reproducibility": payload.get("reproducibility"),
            "modelArtifact": {k: (payload.get("modelArtifact") or {}).get(k) for k in ("sha256", "byteCount", "format")},
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


def _load_active_simulation_input(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 5C simulation input layer (Monte-Carlo entry gates).

    Not a game forecast, betting model, or Monte-Carlo result. Read-only and defensive:
    absence / parse error / authority mismatch -> ``None`` (honest not-run state). Surfaces a
    compact readiness view: D3 reproduction, participant coverage, eligible games, throughput,
    short-sequence legality, and the Monte-Carlo entry decision.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE5_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase5"
        )
        artifact = root / "simulation-input" / "latest.simulation.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("simulationInput") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        pa = payload.get("paProvider") or {}
        repro = pa.get("reproduction") or {}
        throughput = pa.get("throughput") or {}
        coverage = (payload.get("participantProvider") or {}).get("coverage") or {}
        seq = payload.get("shortSequenceIntegration") or {}
        perf = payload.get("monteCarloPerformanceEstimate") or {}
        decision = payload.get("monteCarloEntryDecision") or {}
        eligible = payload.get("eligiblePopulation") or {}
        return {
            "runId": payload.get("runId"),
            "contractName": payload.get("contractName"),
            "researchOnly": payload.get("researchOnly", True),
            "parentAuthorities": payload.get("parentAuthorities"),
            "readiness": payload.get("readiness"),
            "monteCarloEntryDecision": decision.get("decision"),
            "monteCarloEntryGates": decision.get("gates"),
            "paProvider": {
                "contractName": pa.get("contractName"),
                "modelAuthority": pa.get("modelAuthority"),
                "classOrder": pa.get("classOrder"),
                "exactReproduction": repro.get("exactReproduction"),
                "rowsCompared": repro.get("rowsCompared"),
                "maxAbsProbabilityDiff": repro.get("maxAbsProbabilityDiff"),
                "meanAbsProbabilityDiff": repro.get("meanAbsProbabilityDiff"),
                "mismatchCount": repro.get("mismatchCount"),
                "classOrderMismatchCount": repro.get("classOrderMismatchCount"),
                "logLoss": repro.get("logLoss"),
                "expectedLogLoss": repro.get("expectedLogLoss"),
                "throughputPasPerSecond": throughput.get("batchPasPerSecond"),
                "singleRowLatencyMs": throughput.get("singleRowLatencyMs"),
                "modelLoadMs": throughput.get("modelLoadMs"),
                "artifactFormat": pa.get("artifactFormat"),
                "missingHistoryAllScoredValid": (pa.get("missingHistory") or {}).get("allScoredValid"),
            },
            "participantProvider": {
                "contractName": (payload.get("participantProvider") or {}).get("contractName"),
                "provenance": (payload.get("participantProvider") or {}).get("provenance"),
                "coverage": coverage,
            },
            "gameInitialization": {
                "contractName": (payload.get("gameInitialization") or {}).get("contractName"),
                "validated": (payload.get("gameInitialization") or {}).get("validated"),
            },
            "shortSequenceIntegration": {k: seq.get(k) for k in (
                "sequences", "pasPerSequence", "totalPlateAppearances", "illegalStates",
                "invalidProbabilityVectors", "duplicatedRunners", "lostRunners",
                "inningProgressionOk", "clean", "sameSeedReproducible", "differentSeedDivergent")},
            "eligiblePopulation": eligible,
            "monteCarloPerformanceEstimate": {k: perf.get(k) for k in (
                "measuredPasPerSecond", "oneGame1000Sims", "slate15Games1000Sims",
                "fullSeason2024_1000Sims", "batchingRecommended")},
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


def _load_active_whole_game_monte_carlo(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 5D whole-game Monte Carlo research baseline.

    A research simulation component under HISTORICAL_PARTICIPANTS_ORACLE_MODE — not a game
    forecast, betting model, or market comparison. Read-only and defensive: absence / parse
    error / authority mismatch -> ``None``. Surfaces the score-distribution accuracy, interval
    coverage, diagnostic winner calibration, D3 game-level value, and readiness only.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE5_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase5"
        )
        artifact = root / "whole-game-monte-carlo" / "latest.montecarlo.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("monteCarlo") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        by_season = payload.get("bySeason") or {}

        def _season_view(season: str) -> dict[str, Any]:
            ev = by_season.get(season) or {}
            sm = ev.get("scoreMetrics") or {}
            return {
                "games": ev.get("games"),
                "actualMeanTotal": ev.get("actualMeanTotal"),
                "simulatedMeanTotal": ev.get("simulatedMeanTotal"),
                "totalBias": (sm.get("total") or {}).get("bias"),
                "totalMae": (sm.get("total") or {}).get("mae"),
                "totalRmse": (sm.get("total") or {}).get("rmse"),
                "crpsTotal": sm.get("crpsTotal"),
                "runDiffMae": (sm.get("diff") or {}).get("mae"),
                "coverageTotal": (ev.get("coverage") or {}).get("intTotal"),
                "winner": ev.get("winner"),
                "calibrationEce": (ev.get("calibration") or {}).get("ece"),
                "actualHomeWinRate": ev.get("actualHomeWinRate"),
                "meanSimulatedHomeWinProb": ev.get("meanSimulatedHomeWinProb"),
                "baselineG0": ev.get("baselineG0"),
                "distributionShapeTotal": ev.get("distributionShapeTotal"),
                "shapeVerdict": ev.get("shapeVerdict"),
                "dispersionRatioTotal": ev.get("dispersionRatioTotal"),
                "errorConcentrationCrpsTotal": ev.get("errorConcentrationCrpsTotal"),
                "legality": ev.get("legality"),
            }

        return {
            "runId": payload.get("runId"),
            "contractName": payload.get("contractName"),
            "researchOnly": payload.get("researchOnly", True),
            "participantMode": payload.get("participantMode"),
            "parentAuthorities": payload.get("parentAuthorities"),
            "simulationsPerGame": payload.get("simulationsPerGame"),
            "developmentStandardSimulations": payload.get("developmentStandardSimulations"),
            "eligibleGames": payload.get("eligibleGames"),
            "convergence": payload.get("convergence"),
            "bySeason": {s: _season_view(s) for s in ("2024", "2025")},
            "d3GameLevelValue": payload.get("d3GameLevelValue"),
            "contactQualityPriority": payload.get("contactQualityPriority"),
            "participationAblationDecision": payload.get("participationAblationDecision"),
            "simulatorReadiness": payload.get("simulatorReadiness"),
            "legality": payload.get("legality"),
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


def _load_active_participation_ablation(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 5E projected-participation ablation (P0->P3 study).

    A research diagnostic — not a game forecast, betting model, or market comparison. Read-only
    and defensive: absence / parse error / authority mismatch -> ``None``. Surfaces per-branch
    metrics, incremental degradation, bootstrap, and the component/overall decisions only.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE5_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase5"
        )
        artifact = root / "projected-participation-ablation" / "latest.ablation.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("ablation") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        by_season = payload.get("bySeason") or {}

        def _season_view(season: str) -> dict[str, Any]:
            ev = by_season.get(season) or {}
            branches = ev.get("branches") or {}

            def _branch(b: str) -> dict[str, Any]:
                br = branches.get(b) or {}
                sm = br.get("scoreMetrics") or {}
                return {
                    "winner": br.get("winner"),
                    "totalCrps": sm.get("crpsTotal"),
                    "totalBias": (sm.get("total") or {}).get("bias"),
                    "totalMae": (sm.get("total") or {}).get("mae"),
                    "runDiffMae": (sm.get("diff") or {}).get("mae"),
                    "cov90Total": (br.get("coverage") or {}).get("intTotal", {}).get("90"),
                    "meanSimulatedHomeWinProb": br.get("meanSimulatedHomeWinProb"),
                    "actualHomeWinRate": br.get("actualHomeWinRate"),
                    "calibrationEce": br.get("calibrationEce"),
                }

            return {
                "branches": {b: _branch(b) for b in ("P0", "P1", "P2", "P3")},
                "deltas": ev.get("deltas"),
            }

        return {
            "runId": payload.get("runId"),
            "contractName": payload.get("contractName"),
            "researchOnly": payload.get("researchOnly", True),
            "branchLabels": payload.get("branchLabels"),
            "projectionAuthorities": payload.get("projectionAuthorities"),
            "simulationsPerGame": payload.get("simulationsPerGame"),
            "comparableGames": payload.get("comparableGames"),
            "bySeason": {s: _season_view(s) for s in ("2024", "2025")},
            "bootstrap": payload.get("bootstrap"),
            "stateFallback": payload.get("stateFallback"),
            "meanLineupRecall": payload.get("meanLineupRecall"),
            "overallDecision": payload.get("overallDecision"),
            "lineupGameImpact": payload.get("lineupGameImpact"),
            "starterDurationGameImpact": payload.get("starterDurationGameImpact"),
            "bullpenGameImpact": payload.get("bullpenGameImpact"),
            "remainingOracleDependencies": payload.get("remainingOracleDependencies"),
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


def _load_active_severe_miss_forensics(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 4F severe-miss forensic study (analysis only).

    Reads ``severe-miss-forensics/latest.study.json``. Read-only and defensive: any absence,
    parse error, or dataset-authority mismatch yields ``None`` for an honest not-run state.
    Surfaces a compact, honest view; never a promoted-model claim and never per-player names.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE4_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase4"
        )
        artifact = root / "severe-miss-forensics" / "latest.study.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("study") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        seasons = payload.get("seasons") or {}
        latest = seasons.get("2025") if isinstance(seasons, Mapping) else None
        pareto = None
        if isinstance(latest, Mapping):
            pareto = ((latest.get("pareto") or {}).get("logLoss") or {}).get("rows")
        decision = payload.get("decision") or {}
        return {
            "studyId": payload.get("studyId"),
            "contractName": payload.get("contractName"),
            "researchOnly": payload.get("researchOnly", True),
            "officialPopulationPreserved": payload.get("officialPopulationPreserved", True),
            "population": payload.get("population"),
            "anchor": payload.get("anchor"),
            "pareto2025": pareto,
            "tailSensitivity2025": latest.get("tailSensitivity") if isinstance(latest, Mapping) else None,
            "overIndex2025": (latest.get("overIndex") or {}).get("worst_5pct") if isinstance(latest, Mapping) else None,
            "confusionPairs2025": (latest.get("confusionPairsWorst5") or {}).get("pairs", [])[:6] if isinstance(latest, Mapping) else None,
            "severeMissClassifier": {
                "rocAuc": (payload.get("severeMissClassifier") or {}).get("rocAuc"),
                "prAuc": (payload.get("severeMissClassifier") or {}).get("prAuc"),
            },
            "randomness": decision.get("randomness"),
            "topThreePatterns": decision.get("topThreePatterns"),
            "recommendedNextStep": decision.get("recommendedNextStep"),
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


def _load_active_starter_identity(registration: Mapping[str, Any]) -> dict[str, Any] | None:
    """Authority-gated read of the Phase 5F starter-identity projection + Q0->Q1 study.

    A research component — not a game forecast, betting model, or market comparison. Read-only and
    defensive: absence / parse error / authority mismatch -> ``None``. Surfaces starter accuracy,
    the Q0/Q1 simulator impact, and the decisions only.
    """

    import json
    import os
    from pathlib import Path

    try:
        configured = os.getenv("ASP_MODEL_STUDIO_PHASE5_RUNTIME_ROOT", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2] / ".runtime" / "asp-model-studio" / "sports-phase5"
        )
        artifact = root / "starter-identity" / "latest.starter.json"
        if not artifact.is_file():
            return None
        record = json.loads(artifact.read_text(encoding="utf-8"))
        payload = record.get("starterIdentity") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            return None
        authority = payload.get("datasetAuthority") or {}
        if (
            authority.get("registrationId") != registration.get("registration_id")
            or authority.get("manifestSha") != registration.get("manifest_sha")
        ):
            return None
        ev = payload.get("starterEvaluation") or {}
        by_season = payload.get("bySeason") or {}

        def _starter_season(s: str) -> dict[str, Any]:
            m = (ev.get("bySeason") or {}).get(s) or {}
            return {k: m.get(k) for k in ("candidatePoolCoverage", "top1Accuracy", "top2Accuracy",
                                          "top3Accuracy", "logLoss", "brier", "mrr", "meanCandidateCount", "top1AccuracyCovered")}

        def _sim_season(s: str) -> dict[str, Any]:
            sv = by_season.get(s) or {}
            def _branch(b):
                br = sv.get(b) or {}
                sm = br.get("scoreMetrics") or {}
                return {"winner": br.get("winner"), "totalCrps": sm.get("crpsTotal"),
                        "totalBias": (sm.get("total") or {}).get("bias"),
                        "cov90Total": (br.get("coverage") or {}).get("intTotal", {}).get("90"),
                        "meanSimulatedHomeWinProb": br.get("meanSimulatedHomeWinProb")}
            return {"Q0": _branch("Q0"), "Q1": _branch("Q1"), "delta": sv.get("delta"),
                    "starterCorrectRate": sv.get("starterCorrectRate"),
                    "segmentBothCorrect": sv.get("segmentBothCorrect"), "segmentAnyWrong": sv.get("segmentAnyWrong")}

        return {
            "runId": payload.get("runId"),
            "contractName": payload.get("contractName"),
            "researchOnly": payload.get("researchOnly", True),
            "devSeasons": payload.get("devSeasons"),
            "modelDecision": payload.get("modelDecision"),
            "simulationsPerGame": payload.get("simulationsPerGame"),
            "comparableGames": payload.get("comparableGames"),
            "starterEvaluation": {s: _starter_season(s) for s in ("2024", "2025")},
            "baselines": ev.get("baselines"),
            "earlySeason": ev.get("earlySeason"),
            "bySeason": {s: _sim_season(s) for s in ("2024", "2025")},
            "bootstrap": payload.get("bootstrap"),
            "simulatorDecision": payload.get("simulatorDecision"),
            "pregameSimulatorReadiness": payload.get("pregameSimulatorReadiness"),
            "remainingOracleParticipation": payload.get("remainingOracleParticipation"),
            "priorities": payload.get("priorities"),
            "stateFallback": payload.get("stateFallback"),
            "projectedStarterCanonicalMissing": payload.get("projectedStarterCanonicalMissing"),
            "limitations": payload.get("limitations"),
        }
    except Exception:
        return None


class SportsDatasetRegistry:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, validated: ValidatedPackage, *, user_id: str) -> dict[str, Any]:
        manifest = validated.manifest
        if manifest["manifest_sha256"] != MANIFEST_SHA:
            raise ManifestValidationError("REGISTRATION_AUTHORITY_MISMATCH", "Only the approved MLB FD1 manifest can be registered")
        registered_at = now_iso()
        totals = _dataset_totals(validated)
        evidence_coverage = _evidence_coverage(manifest)
        feature_audit = build_mlb_pa_feature_audit(validated)
        metadata = {
            "adapter": "SPORTS_DATASET_CONSUMER_ADAPTER_V1",
            "contractVersion": manifest["contract_version"],
            "canonicalizationVersion": manifest["canonicalization_version"],
            "partitionAuthoritySha": validated.partition_authority_sha,
            "validationRootIdentity": validated.root_identity,
            "validationCache": {"hits": validated.cache_hits, "misses": validated.cache_misses},
            "modelingBlockers": [IDENTITY_BRIDGE_BLOCKER],
            "featureAudit": feature_audit,
        }
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE manifest_sha = ?",
                (MANIFEST_SHA,),
            ).fetchone()
            existing_project = connection.execute(
                """
                SELECT created_by, created_at
                FROM sports_research_projects
                WHERE registration_id = ? AND project_id = ? AND project_name = ?
                LIMIT 1
                """,
                (REGISTRATION_ID, PROJECT_ID, PROJECT_NAME),
            ).fetchone()
            registration_disposition = "REUSED" if existing is not None else "CREATED"
            if existing is not None:
                if existing["registration_id"] != REGISTRATION_ID or existing["logical_package_root"] != LOGICAL_PACKAGE_ROOT:
                    raise ManifestValidationError("REGISTRATION_CONFLICT", "Existing dataset registration conflicts with the approved identity")
                connection.execute(
                    """
                    UPDATE sports_dataset_registrations
                    SET dataset_id = ?, dataset_version_id = ?, manifest_id = ?, package_id = ?,
                        sport = ?, league = ?, evidence_cutoff = ?, published_at = ?,
                        validation_status = 'VALID', last_validated_at = ?, active = 1,
                        rights_status = ?, limitation_count = ?, totals_json = ?, seasons_json = ?,
                        evidence_coverage_json = ?, metadata_json = ?
                    WHERE registration_id = ?
                    """,
                    (
                        manifest["dataset_id"],
                        manifest["dataset_version_id"],
                        manifest["manifest_id"],
                        manifest["package_id"],
                        manifest["sport"],
                        manifest["league"],
                        manifest["evidence_cutoff"],
                        manifest["published_at"],
                        validated.validated_at,
                        "APPROVED_LOCAL_PRIVATE_USE",
                        len(manifest["known_limitations"]),
                        json_dumps(totals, {}),
                        json_dumps(manifest["seasons"], []),
                        json_dumps(evidence_coverage, {}),
                        json_dumps(metadata, {}),
                        REGISTRATION_ID,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE sports_dataset_registrations SET active = 0 WHERE dataset_id = ?",
                    (manifest["dataset_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sports_dataset_registrations (
                      registration_id, dataset_id, dataset_version_id, manifest_id, manifest_sha,
                      package_id, sport, league, evidence_cutoff, published_at, logical_package_root,
                      validation_status, registered_at, last_validated_at, registered_by, rights_status,
                      limitation_count, active, totals_json, seasons_json, evidence_coverage_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VALID', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        manifest["dataset_id"],
                        manifest["dataset_version_id"],
                        manifest["manifest_id"],
                        manifest["manifest_sha256"],
                        manifest["package_id"],
                        manifest["sport"],
                        manifest["league"],
                        manifest["evidence_cutoff"],
                        manifest["published_at"],
                        LOGICAL_PACKAGE_ROOT,
                        registered_at,
                        validated.validated_at,
                        user_id,
                        "APPROVED_LOCAL_PRIVATE_USE",
                        len(manifest["known_limitations"]),
                        json_dumps(totals, {}),
                        json_dumps(manifest["seasons"], []),
                        json_dumps(evidence_coverage, {}),
                        json_dumps(metadata, {}),
                    ),
                )

            # A successful revalidation replaces all governed child metadata
            # atomically.  Idempotency must never preserve corrupt or stale
            # partition/schema/fold/project rows from a prior local write.
            for table in (
                "sports_research_projects",
                "sports_dataset_limitations",
                "sports_dataset_rights",
                "sports_dataset_temporal_folds",
                "sports_dataset_populations",
                "sports_dataset_schemas",
                "sports_dataset_partitions",
            ):
                connection.execute(f"DELETE FROM {table} WHERE registration_id = ?", (REGISTRATION_ID,))

            for partition in manifest["partitions"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_partitions (
                      partition_id, registration_id, family, season, month, logical_uri,
                      row_count, byte_count, minimum_date, maximum_date, schema_id,
                      physical_schema_fingerprint, file_sha, source_key, source_version_id,
                      original_source_logical_identity, checkpoint_lineage_id, governance_checksum,
                      target_eligibility_json, temporal_classification_json, rights_ids_json, physical_schema_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        partition["partition_id"],
                        REGISTRATION_ID,
                        partition["family"],
                        partition["season"],
                        partition["month"],
                        f"{LOGICAL_PACKAGE_ROOT}/{partition['package_relative_uri']}",
                        partition["row_count"],
                        partition["byte_count"],
                        partition["minimum_date"],
                        partition["maximum_date"],
                        partition["schema_id"],
                        partition["physical_schema_fingerprint"],
                        partition["file_sha256"],
                        partition["source_key"],
                        partition["source_version_id"],
                        partition["original_source_logical_identity"],
                        partition["checkpoint_lineage_id"],
                        partition["governance_checksum"],
                        json_dumps(partition["target_eligibility"], []),
                        json_dumps(partition["temporal_classification"], []),
                        json_dumps(partition["source_rights_ids"], []),
                        json_dumps(partition["physical_schema"], []),
                    ),
                )

            schema_families = {item["family"]: item for item in validated.schema_registry["families"]}
            for family_name, family in schema_families.items():
                connection.execute(
                    """
                    INSERT INTO sports_dataset_schemas (
                      registration_id, family, logical_schema_version, compatible_partition_count,
                      physical_variant_count, fields_json, physical_variants_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        family_name,
                        family["logical_schema_version"],
                        family["partition_count"],
                        family["physical_variant_count"],
                        json_dumps(_schema_union(family), []),
                        json_dumps(family["physical_variants"], []),
                    ),
                )

            for population in manifest["populations"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_populations (
                      registration_id, population_id, row_count, predicate_json, allowed_uses_json,
                      prohibited_uses_json, temporal_meaning, evaluation_precedence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        population["population_id"],
                        population["expected_row_count"],
                        json_dumps(population["row_selection"], {}),
                        json_dumps(population["allowed_uses"], []),
                        json_dumps(population["prohibited_uses"], []),
                        population["temporal_meaning"],
                        population["evaluation_precedence"],
                    ),
                )

            for fold in manifest["temporal_contract"]["folds"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_temporal_folds (
                      registration_id, fold_id, training_seasons_json, validation_season,
                      training_end, validation_start, validation_end, training_rows, validation_rows
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        fold["fold_id"],
                        json_dumps(fold["training_seasons"], []),
                        fold["validation_season"],
                        fold["training_end"],
                        fold["validation_start"],
                        fold["validation_end"],
                        fold["training_rows"],
                        fold["validation_rows"],
                    ),
                )

            for right in validated.source_rights["records"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_rights (
                      registration_id, rights_control_id, display_name, source_name, status,
                      allowed_uses_json, prohibited_uses_json, attribution, controls_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        REGISTRATION_ID,
                        right["rights_control_id"],
                        right["display_name"],
                        right["source_name"],
                        right["fd1_use"]["status"],
                        json_dumps(right["allowed_purposes"], []),
                        json_dumps(EXPECTED_PROHIBITED_USES, []),
                        right.get("required_attribution_text") or right.get("attribution_text") or "No package use; attribution is not activated.",
                        json_dumps(right["controls"], {}),
                        json_dumps(
                            {
                                "fd1Use": right["fd1_use"],
                                "inventoryClassification": right["inventory_classification"],
                                "rightsClassification": right["rights_classification"],
                                "reviewNote": right["review_note"],
                            },
                            {},
                        ),
                    ),
                )

            for limitation in manifest["known_limitations"]:
                connection.execute(
                    """
                    INSERT INTO sports_dataset_limitations (registration_id, limitation_id, scope, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    (REGISTRATION_ID, limitation["limitation_id"], limitation["scope"], limitation["description"]),
                )

            workflow = {
                "objective_forecast_contract": {"status": "COMPLETE", "evidence": "Exact MLB pregame-final forecast contract registered."},
                "data_evidence_manifest": {"status": "COMPLETE", "evidence": f"Validated {manifest['manifest_id']}."},
                "identity_coverage_leakage": {
                    "status": "BLOCKED",
                    "evidence": "Primary within-family identity coverage is exact, but the package-bound PA-to-prior bridge is absent.",
                    "featureAudit": feature_audit,
                },
                "temporal_validation": {"status": "COMPLETE", "evidence": "Two frozen retrospective rolling-origin folds registered."},
                "player_team_state": {"status": "BLOCKED", "evidence": IDENTITY_BRIDGE_BLOCKER["description"]},
                "participation_usage": {"status": "NOT_CONFIGURED"},
                "event_models": {"status": "NOT_CONFIGURED"},
                "game_simulation": {"status": "NOT_CONFIGURED"},
                "candidate_models_experiments": {"status": "NOT_CONFIGURED"},
                "calibration_reliability": {"status": "NOT_CONFIGURED"},
                "model_graph_decision": {"status": "NOT_CONFIGURED"},
                "export_to_asp": {"status": "NOT_CONFIGURED"},
            }
            connection.execute(
                """
                INSERT INTO sports_research_projects (
                  project_id, registration_id, project_name, sport, league, development_period,
                  prior_history, forecast_lifecycle, primary_target, secondary_targets_json,
                  baseline_population, upper_bound_population, research_purpose, workflow_evidence_json,
                  created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROJECT_ID,
                    REGISTRATION_ID,
                    PROJECT_NAME,
                    "Baseball",
                    "MLB",
                    "2023–2025",
                    "2021–2022",
                    "Pregame — Final",
                    "Plate-Appearance Outcome",
                    json_dumps(
                        [
                            "Joint Score Distribution",
                            "Home Win Probability",
                            "Run Differential",
                            "Total Runs",
                            "Player Outcome Distribution",
                        ],
                        [],
                    ),
                    "Strict Deployable",
                    "Enhanced Research",
                    "Establish the first leakage-safe player-event baseline for the MLB Gen-2 forecasting system.",
                    json_dumps(workflow, {}),
                    existing_project["created_by"] if existing_project is not None else user_id,
                    existing_project["created_at"] if existing_project is not None else registered_at,
                    registered_at,
                ),
            )
        result = self.get(REGISTRATION_ID)
        if result is None:
            raise RuntimeError("Sports dataset registration was not persisted")
        result["registration_disposition"] = registration_disposition
        return result

    @staticmethod
    def _decode_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        from ..persistence.db import decode_row

        return decode_row(row)

    def get(self, registration_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE registration_id = ?",
                (registration_id,),
            ).fetchone()
        return self._decode_row(row)

    def get_active(self) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_registrations WHERE active = 1 AND validation_status = 'VALID' ORDER BY registered_at DESC LIMIT 1"
            ).fetchone()
        decoded = self._decode_row(row)
        return None if decoded is not None and _historical_current_statcast(decoded) else decoded

    def list_valid(self) -> list[dict[str, Any]]:
        """Return every validated registration available for explicit selection."""

        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sports_dataset_registrations
                WHERE validation_status = 'VALID'
                ORDER BY active DESC, registered_at DESC, registration_id
                """
            ).fetchall()
        decoded = [self._decode_row(row) or {} for row in rows]
        return [row for row in decoded if not _historical_current_statcast(row)]

    def activate(self, registration_id: str) -> dict[str, Any] | None:
        """Select one already-validated registration without changing its evidence."""

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM sports_dataset_registrations
                WHERE registration_id = ? AND validation_status = 'VALID'
                """,
                (registration_id,),
            ).fetchone()
            if row is None:
                return None
            metadata = json_loads(row["metadata_json"], {})
            if isinstance(metadata, Mapping) and metadata.get("workspaceActivationEligible") is False:
                # Catalog-visible foundations (currently NFL) remain inspect-only
                # until their own workflow receives explicit activation authority.
                return None
            if (
                row["dataset_id"] == _CURRENT_STATCAST_DATASET_ID
                and isinstance(metadata, Mapping)
                and metadata.get("authorityState") == "HISTORICAL"
            ):
                return None
            connection.execute("UPDATE sports_dataset_registrations SET active = 0 WHERE active = 1")
            connection.execute(
                "UPDATE sports_dataset_registrations SET active = 1 WHERE registration_id = ?",
                (registration_id,),
            )
        return self.get(registration_id)

    def list_partitions(self, registration_id: str, *, family: str | None = None, seasons: Sequence[int] = ()) -> list[dict[str, Any]]:
        clauses = ["registration_id = ?"]
        parameters: list[Any] = [registration_id]
        if family:
            clauses.append("family = ?")
            parameters.append(family)
        if seasons:
            placeholders = ",".join("?" for _ in seasons)
            clauses.append(f"season IN ({placeholders})")
            parameters.extend(seasons)
        query = f"SELECT * FROM sports_dataset_partitions WHERE {' AND '.join(clauses)} ORDER BY family, season, month, logical_uri"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._decode_row(row) or {} for row in rows]

    def get_schema(self, registration_id: str, family: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_schemas WHERE registration_id = ? AND family = ?",
                (registration_id, family),
            ).fetchone()
        return self._decode_row(row)

    def get_fold(self, registration_id: str, fold_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sports_dataset_temporal_folds WHERE registration_id = ? AND fold_id = ?",
                (registration_id, fold_id),
            ).fetchone()
        return self._decode_row(row)

    def public_dataset(self, registration: Mapping[str, Any]) -> dict[str, Any]:
        registration_id = str(registration["registration_id"])
        with self.database.connection() as connection:
            families = [dict(row) for row in connection.execute(
                "SELECT family, SUM(row_count) AS rows FROM sports_dataset_partitions WHERE registration_id = ? GROUP BY family ORDER BY family",
                (registration_id,),
            ).fetchall()]
            populations = [self._decode_row(row) or {} for row in connection.execute(
                "SELECT * FROM sports_dataset_populations WHERE registration_id = ? ORDER BY evaluation_precedence",
                (registration_id,),
            ).fetchall()]
            folds = [self._decode_row(row) or {} for row in connection.execute(
                "SELECT * FROM sports_dataset_temporal_folds WHERE registration_id = ? ORDER BY validation_season",
                (registration_id,),
            ).fetchall()]
            rights = [self._decode_row(row) or {} for row in connection.execute(
                "SELECT * FROM sports_dataset_rights WHERE registration_id = ? ORDER BY rights_control_id",
                (registration_id,),
            ).fetchall()]
            limitations = [dict(row) for row in connection.execute(
                "SELECT limitation_id, scope, description FROM sports_dataset_limitations WHERE registration_id = ? ORDER BY limitation_id",
                (registration_id,),
            ).fetchall()]
            project = self._decode_row(connection.execute(
                "SELECT * FROM sports_research_projects WHERE registration_id = ? ORDER BY created_at LIMIT 1",
                (registration_id,),
            ).fetchone())
        metadata = registration.get("metadata_json") or {}
        is_current_statcast = metadata.get("datasetKind") == "CURRENT_STATCAST_PLATE_APPEARANCE"
        include_active_children = bool(registration.get("active")) and not is_current_statcast
        identity_bridge = None
        pa_baseline = None
        phase4 = None
        try:
            # Kept as a lazy import so the parent dataset adapter remains usable
            # independently of optional companion-contract registrations.
            if not include_active_children:
                candidate_bridge = None
            else:
                from ..sports_identity_bridges.registry import SportsIdentityBridgeRegistry

                candidate_bridge = SportsIdentityBridgeRegistry(self.database).public_active()
            # Companion evidence is never project-latest authority.  In
            # particular, the frozen FD1 identity bridge must not leak onto the
            # independently named current-Statcast PA registration.
            if (
                isinstance(candidate_bridge, Mapping)
                and candidate_bridge.get("parentRegistrationId") == registration_id
                and candidate_bridge.get("parentManifestSha") == registration.get("manifest_sha")
                and candidate_bridge.get("parentPartitionAuthoritySha")
                    == metadata.get("partitionAuthoritySha")
            ):
                identity_bridge = candidate_bridge
        except sqlite3.OperationalError:
            # An absent additive bridge migration or registration is an honest
            # no-evidence state, not a reason to hide the parent dataset.
            identity_bridge = None
        try:
            # Research-model evidence is additive and sports-specific. Keep it
            # nested in the already-governed active dataset response instead of
            # introducing a second browser fetch or a production registry claim.
            if not include_active_children:
                active_research = None
            else:
                from ..sports_modeling.registry import SportsPAResearchRegistry

                active_research = SportsPAResearchRegistry(self.database).public_active()
            candidate_baseline = (
                active_research.get("paBaseline")
                if isinstance(active_research, Mapping)
                else None
            )
            candidate_run = (
                candidate_baseline.get("run")
                if isinstance(candidate_baseline, Mapping)
                else None
            )
            candidate_parent = (
                candidate_run.get("parent")
                if isinstance(candidate_run, Mapping)
                else None
            )
            if (
                project is not None
                and isinstance(candidate_parent, Mapping)
                and candidate_parent.get("registrationId") == registration_id
                and candidate_run.get("projectId") == project["project_id"]
            ):
                pa_baseline = candidate_baseline
        except sqlite3.OperationalError as exc:
            # Migration 0031 and a completed run are both optional. The parent
            # dataset remains truthful and usable when neither exists yet.
            if "no such table: sports_pa_research_runs" not in str(exc).casefold():
                raise
            pa_baseline = None
        try:
            # Phase 4 is an additive child study. It is visible only when its
            # exact dataset, project, and immutable Phase 3 parent all match the
            # independently projected authorities above.
            if not include_active_children:
                active_phase4 = None
            else:
                from ..sports_phase4.registry import SportsPhase4Registry

                active_phase4 = SportsPhase4Registry(self.database).public_active()
            candidate_phase4 = (
                active_phase4.get("phase4")
                if isinstance(active_phase4, Mapping)
                else None
            )
            candidate_dataset = (
                candidate_phase4.get("dataset")
                if isinstance(candidate_phase4, Mapping)
                else None
            )
            candidate_parent = (
                candidate_phase4.get("phase3Baseline")
                if isinstance(candidate_phase4, Mapping)
                else None
            )
            phase3_run = (
                pa_baseline.get("run")
                if isinstance(pa_baseline, Mapping)
                else None
            )
            phase3_feature = (
                pa_baseline.get("featureView")
                if isinstance(pa_baseline, Mapping)
                else None
            )
            phase3_graph = (
                pa_baseline.get("graph")
                if isinstance(pa_baseline, Mapping)
                else None
            )
            phase3_decision = (
                pa_baseline.get("decision")
                if isinstance(pa_baseline, Mapping)
                else None
            )
            if (
                project is not None
                and isinstance(candidate_phase4, Mapping)
                and isinstance(candidate_dataset, Mapping)
                and isinstance(candidate_parent, Mapping)
                and isinstance(phase3_run, Mapping)
                and isinstance(phase3_feature, Mapping)
                and isinstance(phase3_graph, Mapping)
                and isinstance(phase3_decision, Mapping)
                and candidate_phase4.get("projectId") == project["project_id"]
                and candidate_dataset.get("registrationId") == registration_id
                and candidate_dataset.get("manifestSha") == registration.get("manifest_sha")
                and candidate_dataset.get("partitionAuthoritySha")
                    == metadata.get("partitionAuthoritySha")
                and candidate_parent.get("runId") == phase3_run.get("runId")
                and candidate_parent.get("runSha") == phase3_run.get("runSha")
                and candidate_parent.get("experimentId")
                    == (phase3_run.get("experiment") or {}).get("experimentId")
                and candidate_parent.get("featureContractName")
                    == phase3_feature.get("contractVersion")
                and candidate_parent.get("featureContractSha")
                    == phase3_feature.get("contractSha")
                and candidate_parent.get("featureViewId")
                    == phase3_feature.get("featureViewId")
                and candidate_parent.get("graphId") == phase3_graph.get("graphId")
                and candidate_parent.get("status")
                    == phase3_decision.get("terminalStatus")
            ):
                phase4 = candidate_phase4
        except sqlite3.OperationalError as exc:
            if "no such table: sports_phase4_studies" not in str(exc).casefold():
                raise
            phase4 = None
        limitation_source = (
            "CURRENT_STATCAST_MANIFEST"
            if metadata.get("datasetKind") == "CURRENT_STATCAST_PLATE_APPEARANCE"
            else "EXCHANGE_MANIFEST"
        )
        public_limitations = [
            {"limitationId": item["limitation_id"], "scope": item["scope"], "description": item["description"], "source": limitation_source}
            for item in limitations
        ]
        public_limitations.extend({**item, "source": "CONSUMER_AUDIT"} for item in metadata.get("modelingBlockers", []))
        seasons = registration.get("seasons_json") or []
        manifest_metadata = metadata.get("manifestMetadata") or {}
        current_sync = manifest_metadata.get("syncHealth")
        if registration.get("dataset_id") == _CURRENT_STATCAST_DATASET_ID:
            sync_root = self.database.path.parent.parent / "current-statcast-sync"
            try:
                attempt = json.loads((sync_root / "latest-attempt.json").read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                attempt = None
            try:
                success = json.loads((sync_root / "latest-success.json").read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                success = None
            if isinstance(attempt, Mapping):
                operational_keys = (
                    "status",
                    "attemptedAtUtc",
                    "requestedThroughDate",
                    "priorRegisteredThroughDate",
                    "latestMlbFinalDate",
                    "datesInspected",
                    "datesAdded",
                    "datesUnchanged",
                    "datesCorrected",
                    "completeEmptyDates",
                    "failedDates",
                    "failedStage",
                    "errorType",
                    "error",
                )
                operational = {
                    key: attempt[key] for key in operational_keys if key in attempt
                }
                current_sync = {
                    **(dict(current_sync) if isinstance(current_sync, Mapping) else {}),
                    **(
                        {"resultingCoverage": success.get("resultingCoverage")}
                        if isinstance(success, Mapping)
                        and isinstance(success.get("resultingCoverage"), Mapping)
                        else {}
                    ),
                    **operational,
                    "lastSuccessfulAtUtc": (
                        success.get("attemptedAtUtc") if isinstance(success, Mapping) else None
                    ),
                }
        result = {
            "registrationId": registration_id,
            "datasetId": registration["dataset_id"],
            "datasetVersionId": registration["dataset_version_id"],
            "manifestId": registration["manifest_id"],
            "manifestSha": registration["manifest_sha"],
            "packageId": registration["package_id"],
            "sport": registration["sport"],
            "league": registration["league"],
            "evidenceCutoff": registration["evidence_cutoff"],
            "publishedAt": registration["published_at"],
            "logicalRoot": registration["logical_package_root"],
            "partitionAuthoritySha": metadata.get("partitionAuthoritySha"),
            "validationStatus": registration["validation_status"],
            "registeredAt": registration["registered_at"],
            "rightsStatus": registration["rights_status"],
            "limitationCount": registration["limitation_count"],
            "active": bool(registration["active"]),
            "seasons": [item["season"] for item in seasons],
            "totals": registration.get("totals_json") or {},
            "families": [{"family": item["family"], "rows": item["rows"]} for item in families],
            "seasonCoverage": [
                {
                    "season": item["season"],
                    "games": item.get("games"),
                    "plateAppearances": item.get("plate_appearances"),
                    "transitions": item.get("transitions"),
                    "starterTargets": item.get("starter_targets"),
                    "bullpenAppearances": item.get("bullpen_appearances"),
                    "earliestDate": (item.get("date_range") or {}).get("earliestDate"),
                    "latestDate": (item.get("date_range") or {}).get("latestDate"),
                }
                for item in seasons
            ],
            "populations": [
                {
                    "populationId": item["population_id"],
                    "rows": item["row_count"],
                    "predicate": item["predicate_json"],
                    "uses": item["allowed_uses_json"],
                    "prohibitions": item["prohibited_uses_json"],
                }
                for item in populations
            ],
            "folds": [
                {
                    "foldId": item["fold_id"],
                    "trainingSeasons": item["training_seasons_json"],
                    "validationSeason": item["validation_season"],
                    "trainingRows": item["training_rows"],
                    "validationRows": item["validation_rows"],
                }
                for item in folds
            ],
            "evidenceCoverage": registration.get("evidence_coverage_json") or {},
            "rights": [
                {
                    "rightsControlId": item["rights_control_id"],
                    "displayName": item["display_name"],
                    "sourceName": item["source_name"],
                    "source": item["source_name"],
                    "status": item["status"],
                    "allowedUses": item["allowed_uses_json"],
                    "prohibitedUses": item["prohibited_uses_json"],
                    "attribution": item["attribution"],
                }
                for item in rights
            ],
            "limitations": [item["description"] for item in public_limitations],
            "limitationDetails": public_limitations,
            "modelingBlockers": metadata.get("modelingBlockers", []),
            "featureAudit": metadata.get("featureAudit"),
            "dateCoverage": metadata.get("dateCoverage"),
            "temporalContract": (metadata.get("manifestMetadata") or {}).get("temporalContract"),
            "modelingStatus": metadata.get("modelingStatus"),
            "modelFitOccurred": metadata.get("modelFitOccurred"),
            "currentStatcastSync": current_sync,
            "workspaceActivationEligible": metadata.get("workspaceActivationEligible", True),
            "compatibleWorkflowIds": metadata.get("compatibleWorkflowIds", []),
            "authorityLayer": metadata.get("authorityLayer"),
            "authorityState": metadata.get("authorityState"),
            "sourceProvider": metadata.get("sourceProvider"),
            "sourceFamilies": metadata.get("sourceFamilies", []),
            "featureFamilies": metadata.get("featureFamilies", {}),
            "featureEraContracts": metadata.get("featureEraContracts", {}),
            "quality": metadata.get("quality", {}),
            "nflCurrentSync": (
                (metadata.get("manifestMetadata") or {}).get("syncHealth")
                if registration.get("league") == "NFL"
                else None
            ),
        }
        if identity_bridge is not None:
            result["identityBridge"] = identity_bridge
        if pa_baseline is not None:
            result["paBaseline"] = pa_baseline
        if phase4 is not None:
            catcher_readiness = _load_active_catcher_readiness(registration)
            if catcher_readiness is not None:
                phase4 = {**phase4, "catcherReadiness": catcher_readiness}
            pitch_sequence_features = _load_active_pitch_sequence_features(registration)
            if pitch_sequence_features is not None:
                phase4 = {**phase4, "pitchSequenceFeatures": pitch_sequence_features}
            process_interactions = _load_active_process_interactions(registration)
            if process_interactions is not None:
                phase4 = {**phase4, "processInteractions": process_interactions}
            incremental_study = _load_active_incremental_study(registration)
            if incremental_study is not None:
                phase4 = {**phase4, "incrementalSignalStudy": incremental_study}
            severe_miss_forensics = _load_active_severe_miss_forensics(registration)
            if severe_miss_forensics is not None:
                phase4 = {**phase4, "severeMissForensics": severe_miss_forensics}
            game_replay = _load_active_game_replay(registration)
            if game_replay is not None:
                phase4 = {**phase4, "gameReplay": game_replay}
            base_out_transition = _load_active_base_out_transition(registration)
            if base_out_transition is not None:
                phase4 = {**phase4, "baseOutTransition": base_out_transition}
            simulation_input = _load_active_simulation_input(registration)
            if simulation_input is not None:
                phase4 = {**phase4, "simulationInput": simulation_input}
            whole_game_monte_carlo = _load_active_whole_game_monte_carlo(registration)
            if whole_game_monte_carlo is not None:
                phase4 = {**phase4, "wholeGameMonteCarlo": whole_game_monte_carlo}
            participation_ablation = _load_active_participation_ablation(registration)
            if participation_ablation is not None:
                phase4 = {**phase4, "participationAblation": participation_ablation}
            starter_identity = _load_active_starter_identity(registration)
            if starter_identity is not None:
                phase4 = {**phase4, "starterIdentity": starter_identity}
            result["phase4"] = phase4
        if project:
            workflow_evidence = project["workflow_evidence_json"]
            identity_stage = (workflow_evidence.get("identity_coverage_leakage") or {}).get("status")
            terminal_status = (
                ((pa_baseline.get("decision") or {}).get("terminalStatus"))
                if pa_baseline is not None
                else None
            )
            project_status = (
                f"REGISTERED_PA_{terminal_status}"
                if terminal_status
                else (
                    "REGISTERED_IDENTITY_BRIDGE_VALIDATED"
                    if identity_bridge is not None and identity_stage == "COMPLETE"
                    else "REGISTERED_MODELING_BLOCKED"
                )
            )
            result["project"] = {
                "projectId": project["project_id"],
                "projectName": project["project_name"],
                "name": project["project_name"],
                "status": project_status,
                "workflowId": "mlb-forecasting",
                "sport": project["sport"],
                "league": project["league"],
                "developmentPeriod": project["development_period"],
                "priorHistory": project["prior_history"],
                "forecastLifecycle": project["forecast_lifecycle"],
                "primaryTarget": project["primary_target"],
                "secondaryTargets": project["secondary_targets_json"],
                "baselinePopulation": project["baseline_population"],
                "upperBoundPopulation": project["upper_bound_population"],
                "researchPurpose": project["research_purpose"],
                "workflowEvidence": workflow_evidence,
                "stages": workflow_evidence,
                "featureAudit": metadata.get("featureAudit"),
            }
        return result

    def record_query_start(
        self,
        *,
        query_id: str,
        registration_id: str,
        user_id: str,
        operation: str,
        logical_scope: str,
        fields: Sequence[str],
        requested_limit: int | None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sports_dataset_query_audit (
                  query_id, registration_id, user_id, operation, logical_scope, fields_json,
                  requested_limit, status, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?)
                """,
                (query_id, registration_id, user_id, operation, logical_scope, json_dumps(list(fields), []), requested_limit, now_iso()),
            )

    def record_query_finish(
        self,
        query_id: str,
        *,
        status: str,
        rows_scanned: int,
        rows_returned: int,
        error_code: str | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE sports_dataset_query_audit
                SET status = ?, rows_scanned = ?, rows_returned = ?, completed_at = ?, error_code = ?
                WHERE query_id = ?
                """,
                (status, rows_scanned, rows_returned, now_iso(), error_code, query_id),
            )

"""Reconstruct and aggregate the accepted 5,000-game V18 population."""

from __future__ import annotations

from datetime import UTC, datetime
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.persistence.db import Database
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast.stage3_model_laboratory import resolve_model_lab_authority
from server.sports_current_statcast.mlb_v18_play_geometry import PlayGeometryModel
from server.sports_current_statcast.mlb_v18_play_geometry_trace import SELECTORS
from server.sports_current_statcast.mlb_v18_population_geometry import (
    ACCEPTANCE_PROTOCOL_V2_SHA256,
    CONTACT_GRID,
    EXPECTED_SIMULATIONS,
    FRAME_SIZE,
    PATH_GRID,
    PLAY_GEOMETRY_SHA256,
    PARENT_BUNDLE_SHA256,
    PopulationAccumulator,
    PopulationGeometryError,
    accumulation_frames,
    attach_representatives,
    population_digest,
    reconcile_forecast,
    representative_indices,
    sha,
    verify_manifest,
)
from server.sports_current_statcast.mlb_v18_whole_game_challenger import (
    V18StateProbabilityProvider,
    compose_raw_template,
    simulate_prospective_game,
)
from server.sports_phase5 import base_out_transition as bt
from scripts import finalize_mlb_v18_whole_game_challenger as original
from scripts.build_mlb_v18_play_geometry_supplement import (
    EVAL_SEASONS,
    TRAIN_SEASONS,
    load_fd1_rows,
)


BUNDLE = ROOT / "outputs/mlb-v18-whole-game-challenger/sha256" / PARENT_BUNDLE_SHA256
PLAY_GEOMETRY = ROOT / "outputs/mlb-v18-play-geometry/sha256" / PLAY_GEOMETRY_SHA256
ACCEPTANCE = ROOT / "outputs/mlb-v18-acceptance-protocol-v2/sha256" / ACCEPTANCE_PROTOCOL_V2_SHA256
COHORT = ROOT / "outputs/mlb-gen1-bet-readiness-cohort/sha256/cd44ef70d6d4a5f3258cfad2cd6222accc5a39431d131184cf7b851ecced5785"
OUTPUT = ROOT / "outputs/mlb-v18-population-geometry"
DB = ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db"
MASTER_SEED = 20260907


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def file_record(path: Path, base: Path) -> dict:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        uncompressed = gzip.decompress(raw)
        compressed_bytes = len(raw)
    else:
        uncompressed = raw
        compressed_bytes = len(gzip.compress(raw, compresslevel=9, mtime=0))
    return {
        "relativePath": path.relative_to(base).as_posix(),
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "uncompressedBytes": len(uncompressed),
        "compressedBytes": compressed_bytes,
    }


def verify_parent_artifacts() -> tuple[dict, dict, dict]:
    parent = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    if parent.get("bundleSha256") != PARENT_BUNDLE_SHA256 or parent.get("simulation", {}).get("count") != EXPECTED_SIMULATIONS:
        raise PopulationGeometryError("accepted parent bundle identity or simulation count differs")
    parent_body = {key: value for key, value in parent.items() if key not in {"bundleId", "bundleSha256"}}
    if sha(parent_body) != PARENT_BUNDLE_SHA256:
        raise PopulationGeometryError("accepted parent bundle canonical checksum differs")
    for row in parent["artifacts"]:
        path = BUNDLE / row["relativePath"]
        if path.stat().st_size != row["bytes"] or file_sha(path) != row["sha256"]:
            raise PopulationGeometryError(f"accepted parent artifact differs: {row['relativePath']}")

    play = json.loads((PLAY_GEOMETRY / "manifest.json").read_text(encoding="utf-8"))
    supplement = json.loads((PLAY_GEOMETRY / "play-geometry-supplement.json").read_text(encoding="utf-8"))
    if play.get("supplementSha256") != PLAY_GEOMETRY_SHA256 or sha(supplement) != PLAY_GEOMETRY_SHA256:
        raise PopulationGeometryError("accepted Play Geometry supplement checksum differs")
    for row in play["artifacts"]:
        path = PLAY_GEOMETRY / row["relativePath"]
        if path.stat().st_size != row["bytes"] or file_sha(path) != row["sha256"]:
            raise PopulationGeometryError(f"Play Geometry artifact differs: {row['relativePath']}")

    acceptance = json.loads((ACCEPTANCE / "manifest.json").read_text(encoding="utf-8"))
    if acceptance.get("contractSha256") != ACCEPTANCE_PROTOCOL_V2_SHA256:
        raise PopulationGeometryError("Acceptance Protocol V2 identity differs")
    for row in acceptance.get("implementationFiles", []):
        path = ROOT / row["relativePath"]
        if path.stat().st_size != row["bytes"] or file_sha(path) != row["sha256"]:
            raise PopulationGeometryError(f"Acceptance Protocol V2 implementation differs: {row['relativePath']}")
    cohort = json.loads((COHORT / "cohort.json").read_text(encoding="utf-8"))
    cohort_body = {key: value for key, value in cohort.items() if key != "cohortSha256"}
    if sha(cohort_body) != cohort["cohortSha256"]:
        raise PopulationGeometryError("Gen 1 readiness cohort identity differs")
    return parent, play, acceptance


def recover_execution_authority(parent: dict) -> tuple[dict, V18StateProbabilityProvider, bt.TransitionModel, dict]:
    snapshot = json.loads((BUNDLE / "aisp-pregame-snapshot.json").read_text(encoding="utf-8"))
    forecast = json.loads((BUNDLE / "prospective-forecast.json").read_text(encoding="utf-8"))
    if snapshot.get("outcomesRead") is not False or snapshot.get("aispRowsModified") != 0:
        raise PopulationGeometryError("accepted pregame snapshot boundary differs")

    model_path = BUNDLE / "executable/v18-pa-fold5.joblib"
    model_record = next(row for row in parent["executionPayload"] if row["relativePath"] == "executable/v18-pa-fold5.joblib")
    if file_sha(model_path) != model_record["sha256"]:
        raise PopulationGeometryError("accepted PA model checksum differs")
    pipeline = joblib.load(model_path)
    source_order = tuple(pipeline.ordered_features)
    if len(source_order) != 246 or len(pipeline.preprocessor.ordered_features) != 273:
        raise PopulationGeometryError("accepted PA model feature contract differs")

    authority = resolve_model_lab_authority(Database(DB), "asp-mtlozhdx")
    if authority.split["finalOot"].get("locked") is not True:
        raise PopulationGeometryError("Final OOT seal is not active")
    corrected_set = next(
        (item for item in authority.feature_sets
         if (item.get("transformationContracts") or {}).get("semanticTreatmentVersion") == "MLB_SEMANTIC_TREATMENT_V1"
         and len(item.get("orderedFeatures") or []) == 273),
        None,
    )
    if corrected_set is None:
        raise PopulationGeometryError("registered V18 273-input feature set is unavailable")
    development = lab._fold_frame(authority, corrected_set["orderedFeatures"], include_oof_identity=True, include_target=True)
    source_identity = development.attrs.get("correctedSourceIdentity") or {}
    if (
        source_identity.get("treatmentSpecificationId") != parent["featureContract"]["treatmentSpecificationId"]
        or source_identity.get("treatmentManifestChecksum") != parent["featureContract"]["manifestSha256"]
        or len(development) != 683_662
    ):
        raise PopulationGeometryError("authenticated V18 Development authority differs")

    mlbam = [str(entry["mlbam"]) for side in snapshot["sides"] for entry in side["lineup"]]
    mlbam += [str(side["starter"]["mlbamId"]) for side in snapshot["sides"]]
    crosswalk, crosswalk_evidence = original.identity_map(mlbam)
    batter_ids = [crosswalk.get(str(entry["mlbam"])) for side in snapshot["sides"] for entry in side["lineup"]]
    starter_by_side = {side["side"]: crosswalk.get(str(side["starter"]["mlbamId"])) for side in snapshot["sides"]}
    if any(value is None for value in starter_by_side.values()):
        raise PopulationGeometryError("accepted starter identity cannot be reconstructed")
    batter_evidence = original.latest_rows(development, source_order, [value for value in batter_ids if value], "BATTER")
    pitcher_evidence = original.latest_rows(development, source_order, list(starter_by_side.values()), "PITCHER")
    fallback = original.cold_batter(development, source_order)
    sides = sorted(snapshot["sides"], key=lambda row: row["side"] == "HOME")
    away_side, home_side = sides
    side_batters, cold_fallbacks = {}, []
    for side in sides:
        rows = []
        for entry in side["lineup"]:
            canonical = crosswalk.get(str(entry["mlbam"]))
            if canonical and canonical in batter_evidence:
                rows.append(batter_evidence[canonical])
            else:
                rows.append(dict(fallback))
                cold_fallbacks.append({"side": side["side"], "slot": entry["batting_order"], "mlbamId": str(entry["mlbam"])})
        side_batters[side["side"]] = rows
    away_starter_id, home_starter_id = starter_by_side["AWAY"], starter_by_side["HOME"]
    away_bullpen = original.bullpen_rows(authority.eda_authority, development, source_order, away_side["team"]["abbreviation"], away_starter_id)
    home_bullpen = original.bullpen_rows(authority.eda_authority, development, source_order, home_side["team"]["abbreviation"], home_starter_id)

    raw_templates = []
    for side, batters, opposing in (
        ("AWAY", side_batters["AWAY"], pitcher_evidence[home_starter_id]),
        ("HOME", side_batters["HOME"], pitcher_evidence[away_starter_id]),
    ):
        for slot, batter in enumerate(batters, 1):
            row = compose_raw_template(
                source_order=source_order, batter_row=batter, pitcher_row=opposing,
                state={"context_inning": 1, "context_top_bottom": 0 if side == "AWAY" else 1,
                       "context_outs_before": 0, "context_base_mask_before": 0,
                       "context_batting_score_diff_before": 0},
            )
            row.insert(0, "templateSide", side)
            row.insert(1, "templateSlot", slot)
            raw_templates.append(row)
    reconstructed_templates = pd.concat(raw_templates, ignore_index=True)
    accepted_templates = pq.read_table(BUNDLE / "prospective-raw-246.parquet").to_pandas()
    if list(reconstructed_templates.columns) != list(accepted_templates.columns):
        raise PopulationGeometryError("reconstructed prospective raw-template columns differ from the accepted bundle")
    try:
        pd.testing.assert_frame_equal(
            reconstructed_templates.reset_index(drop=True),
            accepted_templates.reset_index(drop=True),
            check_dtype=False,
            check_exact=True,
        )
    except AssertionError as exc:
        raise PopulationGeometryError(
            f"reconstructed prospective raw-template values differ from the accepted bundle: {exc}"
        ) from exc

    transition_path = BUNDLE / "executable/transition-fold4.json"
    transition_record = next(row for row in parent["executionPayload"] if row["relativePath"] == "executable/transition-fold4.json")
    if file_sha(transition_path) != transition_record["sha256"]:
        raise PopulationGeometryError("accepted transition checksum differs")
    transition = bt.TransitionModel.from_dict(json.loads(transition_path.read_text(encoding="utf-8")))
    provider = V18StateProbabilityProvider(
        pipeline=pipeline,
        away_batters=side_batters["AWAY"], home_batters=side_batters["HOME"],
        away_starter=pitcher_evidence[away_starter_id], home_starter=pitcher_evidence[home_starter_id],
        away_bullpen=away_bullpen, home_bullpen=home_bullpen, temperature=None,
    )
    json_safe = original.json_safe
    execution = {
        "schemaVersion": "MLB_V18_EXECUTION_AUTHORITY_RECOVERY_V1",
        "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "constructionImplementation": {
            "path": "scripts/finalize_mlb_v18_whole_game_challenger.py",
            "gitCommit": "a13768cc412e412a2a605d3021e89e8d09e3cfc2",
            "currentFileSha256": file_sha(ROOT / "scripts/finalize_mlb_v18_whole_game_challenger.py"),
            "acceptedImplementationSnapshotSha256": next(row["sha256"] for row in parent["executionPayload"] if row["relativePath"].endswith("mlb_v18_whole_game_challenger.py")),
        },
        "prospectiveSnapshotSha256": file_sha(BUNDLE / "aisp-pregame-snapshot.json"),
        "acceptedRawTemplateFileSha256": file_sha(BUNDLE / "prospective-raw-246.parquet"),
        "rawTemplateLogicalDigest": sha(json_safe(reconstructed_templates.to_dict(orient="records"))),
        "featureContract": parent["featureContract"],
        "developmentAuthority": {
            "rows": len(development), "sourceMaximumDate": "2026-08-13",
            "correctedSourceIdentity": source_identity,
            "finalOotLocked": True, "finalOotRowsRead": 0,
        },
        "identityCrosswalk": crosswalk_evidence,
        "coldStartFallbacks": cold_fallbacks,
        "providerInputs": {
            "sourceOrderedFeatures": list(source_order),
            "awayBatters": json_safe(side_batters["AWAY"]),
            "homeBatters": json_safe(side_batters["HOME"]),
            "awayStarter": json_safe(pitcher_evidence[away_starter_id]),
            "homeStarter": json_safe(pitcher_evidence[home_starter_id]),
            "awayBullpen": json_safe(away_bullpen),
            "homeBullpen": json_safe(home_bullpen),
        },
        "bullpenEvidence": {
            "method": "EXACT_ORIGINAL_DEVELOPMENT_TEAM_STAFF_DISTRIBUTION",
            "sourceWindow": {"start": "2026-07-15", "end": "2026-08-13"},
            "selection": "LATEST_ROW_PER_NON_STARTER_PITCHER_THEN_LAST_EIGHT_IN_STABLE_GAME_DATE_CANONICAL_PA_ORDER",
            "awayTeam": away_side["team"]["abbreviation"], "homeTeam": home_side["team"]["abbreviation"],
            "awayMembers": len(away_bullpen), "homeMembers": len(home_bullpen),
            "awayDigest": sha(json_safe(away_bullpen)), "homeDigest": sha(json_safe(home_bullpen)),
            "substitution": False, "postgameProspectiveEvidenceUsed": False,
        },
        "acceptedModels": {"paModelSha256": model_record["sha256"], "transitionModelSha256": transition_record["sha256"]},
        "simulation": parent["simulation"],
    }
    execution["executionAuthoritySha256"] = sha(execution)
    del development
    return execution, provider, transition, {"snapshot": snapshot, "forecast": forecast}


def build_handoff(summary: dict, sizes: dict[str, dict[str, int]]) -> dict:
    decoded = int(sum(row["uncompressedBytes"] for row in sizes.values()) * 4)
    return {
        "schemaVersion": "AISP_MLB_V18_POPULATION_GEOMETRY_HANDOFF_V1",
        "registrationState": "READY_FOR_AISP_AGENT_REGISTRATION_NOT_REGISTERED",
        "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "playGeometrySupplementSha256": PLAY_GEOMETRY_SHA256,
        "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
        "populationDigest": summary["populationDigest"],
        "modes": {
            "BROADCAST_REPLAY": {"default": True, "source": "accepted V18 representative trace", "fallbackWhenPopulationUnavailable": True},
            "PLAY_GEOMETRY": {
                "source": "existing checksum-valid Play Geometry supplement",
                "existingTraceVerification": {
                    "completeGameCount": 1, "plateAppearances": 74,
                    "geometryBearingContactPlays": 53,
                    "explicitRunnerMovementOnEveryPlay": True,
                    "ballTraceForEverySupportedContact": True,
                    "persistedStateFieldsPresent": ["outcome", "inning", "half", "outs", "bases", "score", "pitcherState", "battingOrderPosition"],
                    "scoringPlayMarkers": True, "pitchingChangeMarkers": True,
                    "finalState": {"awayTeam": "TOR", "awayRuns": 2, "homeTeam": "ATH", "homeRuns": 1, "innings": 10},
                },
                "rendererLayers": ["BALL_PATHS", "RUNNER_PATHS", "SCORING_PLAYS", "PITCHING_CHANGES"],
                "scopes": ["CURRENT_PLAY", "CURRENT_INNING", "FULL_GAME"],
                "controls": ["PLAY", "PAUSE", "PREVIOUS", "NEXT", "SPEED", "SCRUB", "INNING_JUMP", "SCORING_PLAY_JUMP", "RESTART_ACCUMULATION"],
                "pathBehavior": {"current": "BRIGHT_ANIMATED", "prior": "PROGRESSIVELY_FADED", "ballAndRunnerLayersSeparate": True},
            },
            "SIMULATION_POPULATION": {
                "semantics": "CONVERGENCE_ACROSS_COMPLETE_SIMULATED_GAMES_NOT_ONE_CONTINUOUS_GAME",
                "simulationCount": EXPECTED_SIMULATIONS, "frameCount": EXPECTED_SIMULATIONS // FRAME_SIZE,
                "targetDurationSeconds": [10, 15],
                "controls": ["PLAY", "PAUSE", "REPLAY", "SPEED", "JUMP_TO_COMPLETE"],
                "layerToggles": ["CONTACT_DENSITY", "BALL_PATHS", "RUNNER_TRAFFIC", "SCORING_PLAYS"],
                "neverAttach": ["ONE_GAME_INNING", "ONE_GAME_SCORE", "ONE_GAME_OUTS"],
            },
        },
        "authorityLabels": {
            "PERSISTED_V18_STATE": "Accepted outcome, transition, score and terminal population state.",
            "MODELLED_GEOMETRY": "Retrosheet-derived projected display geometry; never measured tracking.",
            "HISTORICAL_RUNNER_TEMPLATE": "Anonymous movement sampled from registered retrospective target evidence.",
            "DETERMINISTIC_LEGAL_BACKOFF": "Anonymous legal movement used when fitted support is insufficient.",
            "DISPLAY_INTERPOLATION": "Presentation sequencing or fading, not physical timing.",
            "POPULATION_AGGREGATION": "Deterministic counts over the accepted 5,000 complete simulations.",
        },
        "loading": {
            "initial": ["population-summary.json", "population-accumulation-frames.json"],
            "progressiveOptional": ["population-contact-density.json", "population-path-density.json", "population-runner-traffic.json", "representative-paths.json"],
            "artifactUncompressedBytes": {name: row["uncompressedBytes"] for name, row in sizes.items()},
            "artifactCompressedBytes": {name: row["compressedBytes"] for name, row in sizes.items()},
            "expectedDecodedMemoryBytesConservative": decoded,
            "maximumSupportedInitialPayloadBytes": 4 * 1024 * 1024,
            "maximumSupportedTotalDecodedMemoryBytes": 8 * 1024 * 1024,
            "typedArrayCompatibility": True,
        },
        "consumerVerification": [
            "Verify manifest identity and every object checksum and byte count.",
            "Require exact parent bundle, Play Geometry supplement, and Acceptance Protocol V2 identities.",
            "Require exactly 5,000 simulations and the final frame cumulative count of 5,000.",
            "On any missing object or checksum failure, fall back to Broadcast Replay.",
        ],
        "wageringAuthority": False, "promotionStatus": "NOT_PROMOTED", "executionAllowedInAISP": False,
        "finalOotOpened": False, "aispModified": False,
    }


def report(summary: dict, context: dict, runtime: float) -> str:
    bullpen = context.get("bullpenEvidence") or {}
    sizes = context.get("sizes") or {}
    uncompressed = sum(row.get("uncompressedBytes", 0) for row in sizes.values())
    compressed = sum(row.get("compressedBytes", 0) for row in sizes.values())
    selectors = summary["representatives"]["selectors"]
    selector_text = ", ".join(
        f"{name}={row['simulationIndex']}" for name, row in sorted(selectors.items())
    )
    return f"""# V18 Population Geometry supplement

Verdict: `V18_POPULATION_GEOMETRY_SUPPLEMENT_READY_FOR_AISP`

The accepted TOR@ATH V18 population was reconstructed with the exact saved PA model,
transition model, prospective snapshot, Development carry-forward templates, and the
original Development team-staff bullpen construction. No fitted or prospective input
was substituted.

- Complete simulations: {summary['simulationCount']:,}
- Frames: {summary['frameCount']} × {summary['frameSize']} simulations
- Population digest: `{summary['populationDigest']}`
- Execution-authority digest: `{summary['executionAuthoritySha256']}`
- Recovered bullpen evidence: TOR {bullpen.get('awayMembers', 8)} rows `{bullpen.get('awayDigest', 'see execution authority')}`; ATH {bullpen.get('homeMembers', 8)} rows `{bullpen.get('homeDigest', 'see execution authority')}`
- Bullpen source window and rule: {bullpen.get('sourceWindow', {'start': '2026-07-15', 'end': '2026-08-13'})}; {bullpen.get('selection', 'original stable Development staff-distribution rule')}
- Contact / geometry-bearing / scoring plays: {summary['counts']['contactPlays']:,} / {summary['counts']['geometryBearingPlays']:,} / {summary['counts']['scoringPlays']:,}
- Runner segments: {summary['counts']['runnerSegments']:,}
- Contact grid: {CONTACT_GRID[0]} × {CONTACT_GRID[1]}
- Path grid: {PATH_GRID[0]} × {PATH_GRID[1]}
- Unique representative paths: {summary['representatives']['uniquePathCount']}
- Selectors satisfied: {selector_text}
- Exact accepted-metric reconciliation: {summary['reconstruction']['allMetricsMatch']}
- Home win / away win: {summary['finalPopulation']['homeWinProbability']:.4f} / {1-summary['finalPopulation']['homeWinProbability']:.4f}
- Expected home / away / total runs: {summary['finalPopulation']['meanHomeRuns']:.4f} / {summary['finalPopulation']['meanAwayRuns']:.4f} / {summary['finalPopulation']['meanTotalRuns']:.4f}
- Run differential / one-run / extra-inning: {summary['finalPopulation']['meanRunDifferential']:.4f} / {summary['finalPopulation']['oneRunRate']:.4f} / {summary['finalPopulation']['extraInningRate']:.4f}
- Illegal states / nonterminations: {summary['illegalStateCount']} / {summary['nonterminationCount']}
- Aggregate object sizes before manifest: {uncompressed:,} bytes uncompressed; {compressed:,} bytes under deterministic gzip sizing
- Conservative browser decoded-memory estimate: {uncompressed*4:,} bytes
- Final OOT reads: 0
- Runtime: {runtime:.3f} seconds

Geometry is modelled Retrosheet zone-centroid visualization evidence, not measured
Statcast tracking. Population layers are bounded one-dimensional filters rather than a
multidimensional cube. AISP must fall back to Broadcast Replay if any identity or object
checksum fails. The venue-name/Retrosheet-park-id crosswalk remains unavailable, so the
geometry sampler uses its disclosed outcome-level backoff. Exit velocity, launch angle,
measured spray angle, measured landing coordinates, physical flight timing, named runner
identity, substitutions, and bench behavior remain unsupported and are not fabricated.
"""


def main() -> int:
    started = time.perf_counter()
    parent, play, acceptance = verify_parent_artifacts()
    print(json.dumps({"stage": "PARENTS_VERIFIED"}), flush=True)
    execution, provider, transition, accepted = recover_execution_authority(parent)
    print(json.dumps({"stage": "EXECUTION_AUTHORITY_RECOVERED", "bullpen": execution["bullpenEvidence"]}), flush=True)

    snapshot, forecast = accepted["snapshot"], accepted["forecast"]
    first = simulate_prospective_game(
        game_id=snapshot["game"]["game_id"], provider=provider, transition_model=transition,
        n_sims=EXPECTED_SIMULATIONS, master_seed=MASTER_SEED,
        regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=0,
    )
    reconstruction = reconcile_forecast(first, forecast)
    if not reconstruction["allMetricsMatch"]:
        raise PopulationGeometryError("exact 5,000-game reconstruction differs from the accepted forecast")
    first_digest = population_digest(first)
    selections = representative_indices(first, forecast)
    selected_indexes = sorted({int(row["simulationIndex"]) for row in selections.values()})
    print(json.dumps({"stage": "POPULATION_RECONSTRUCTED", "digest": first_digest, "representatives": selected_indexes}), flush=True)

    rows, geometry_authority = load_fd1_rows()
    geometry_model = PlayGeometryModel(fold_id="DEV_2023_2024_FIT_2025_EVAL", seasons=TRAIN_SEASONS)
    geometry_model.fit(row for row in rows if int(row.get("season") or 0) in TRAIN_SEASONS)
    del rows
    park = str(snapshot.get("game", {}).get("venue") or "UNKNOWN_PARK")
    terminal = {
        "away": np.asarray(first["awayRuns"]), "home": np.asarray(first["homeRuns"]),
        "innings": np.asarray(first["innings"]),
    }
    accumulator = PopulationAccumulator(model=geometry_model, park=park, game_id=str(forecast["gameId"]), terminal=terminal)
    second = simulate_prospective_game(
        game_id=snapshot["game"]["game_id"], provider=provider, transition_model=transition,
        n_sims=EXPECTED_SIMULATIONS, master_seed=MASTER_SEED,
        regulation=int(snapshot["game"].get("scheduled_innings") or 9),
        trace_indices=selected_indexes, event_observer=accumulator.observe,
    )
    second_digest = population_digest(second)
    if second_digest != first_digest or not reconcile_forecast(second, forecast)["allMetricsMatch"]:
        raise PopulationGeometryError("deterministic population replay differs")

    frames = accumulation_frames(first, accumulator.per_simulation)
    representatives = attach_representatives(
        selections, selected_indexes, second["traces"], model=geometry_model,
        park=park, game_id=str(forecast["gameId"]),
    )
    contact = accumulator.contact_payload()
    paths = accumulator.path_payload()
    runners = accumulator.runner_payload()
    summary = {
        "schemaVersion": "MLB_V18_POPULATION_GEOMETRY_SUMMARY_V1",
        "parentBundleId": parent["bundleId"], "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "engineId": "MLB_V18_WHOLE_GAME_CHALLENGER_V1",
        "transitionModelSha256": parent["transition"]["sha256"],
        "playGeometrySupplementId": play["supplementId"], "playGeometrySupplementSha256": PLAY_GEOMETRY_SHA256,
        "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
        "masterSeed": MASTER_SEED, "seedPolicy": parent["simulation"]["policy"],
        "simulationCount": EXPECTED_SIMULATIONS, "populationDigest": first_digest,
        "populationDigestSchema": "ASP_V18_POPULATION_ARRAY_DIGEST_V1",
        "geometryModelIdentity": {
            "version": "MLB_V18_PLAY_GEOMETRY_SAMPLER_V1", "foldId": geometry_model.fold_id,
            "trainSeasons": list(TRAIN_SEASONS), "evaluationSeasons": list(EVAL_SEASONS),
            "authorityManifestSha256": geometry_authority["manifestSha256"],
        },
        "executionAuthoritySha256": execution["executionAuthoritySha256"],
        "generatedAt": datetime.now(UTC).isoformat(),
        "coordinateSystemVersion": "ASP_NORMALIZED_DIAMOND_V1",
        "frameCount": len(frames), "frameSize": FRAME_SIZE,
        "counts": {
            "plateAppearances": accumulator.total_events,
            "contactPlays": accumulator.contact_events,
            "geometryBearingPlays": accumulator.geometry_events,
            "scoringPlays": accumulator.scoring_events,
            "runnerSegments": int(sum(accumulator.runner_segments.values())),
        },
        "representatives": {"uniquePathCount": representatives["uniquePathCount"], "sharedSelections": representatives["sharedSelections"], "selectors": representatives["selectors"]},
        "reconstruction": {**reconstruction, "firstPopulationDigest": first_digest, "replayPopulationDigest": second_digest, "deterministicReplay": first_digest == second_digest},
        "finalPopulation": {key: forecast[key] for key in ("homeWinProbability", "meanAwayRuns", "meanHomeRuns", "meanTotalRuns", "meanRunDifferential", "oneRunRate", "extraInningRate")},
        "illegalStateCount": int(second["illegalStateCount"]), "nonterminationCount": int(second["nonterminationCount"]),
        "governance": {"researchShadow": True, "wageringAuthority": False, "promotionStatus": "NOT_PROMOTED", "executionAllowedInAISP": False, "finalOotOpened": False, "providerCalls": 0, "aispWrites": 0, "v18PredictiveModelFits": 0, "geometryAuthorityReconstructions": 1, "recalibrations": 0},
    }

    staging = ROOT / ".runtime/asp-model-studio/v18-population-geometry" / f"build-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    write_json(staging / "population-summary.json", summary)
    write_json(staging / "population-accumulation-frames.json", {"schemaVersion": summary["schemaVersion"], "frames": frames})
    write_json(staging / "population-contact-density.json", contact)
    write_json(staging / "population-path-density.json", paths)
    write_json(staging / "population-runner-traffic.json", runners)
    write_json(staging / "representative-paths.json", representatives)
    execution_raw = canonical_json_bytes(execution)
    (staging / "execution-authority.json.gz").write_bytes(gzip.compress(execution_raw, compresslevel=9, mtime=0))

    initial_sizes = {
        row["relativePath"]: {
            "uncompressedBytes": row["uncompressedBytes"],
            "compressedBytes": row["compressedBytes"],
        }
        for row in (file_record(path, staging) for path in staging.iterdir() if path.is_file())
    }
    handoff = build_handoff(summary, initial_sizes)
    write_json(staging / "aisp-population-geometry-handoff.json", handoff)
    runtime = time.perf_counter() - started
    report_text = report(summary, {"bullpenEvidence": execution["bullpenEvidence"], "sizes": initial_sizes}, runtime)
    (staging / "report.md").write_text(report_text, encoding="utf-8")

    artifacts = [file_record(path, staging) for path in sorted(staging.iterdir()) if path.is_file()]
    manifest_body = {
        "schemaVersion": "MLB_V18_POPULATION_GEOMETRY_MANIFEST_V1",
        "verdict": "V18_POPULATION_GEOMETRY_SUPPLEMENT_READY_FOR_AISP",
        "parentBundleId": parent["bundleId"], "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "acceptedConfiguration": parent["simulation"],
        "playGeometrySupplementId": play["supplementId"], "playGeometrySupplementSha256": PLAY_GEOMETRY_SHA256,
        "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
        "executionAuthoritySha256": execution["executionAuthoritySha256"],
        "populationDigest": first_digest, "simulationCount": EXPECTED_SIMULATIONS,
        "artifacts": artifacts,
        "finalOot": {"opened": False, "rowsRead": 0, "targetsRead": 0, "scored": False},
        "operations": {"v18PredictiveModelFits": 0, "geometryAuthorityReconstructions": 1, "recalibrations": 0, "providerCalls": 0, "aispWrites": 0, "promotions": 0, "deployments": 0, "readinessPolicyStudies": 0},
        "runtimeSeconds": round(runtime, 3),
    }
    supplement_sha = sha(manifest_body)
    manifest = {**manifest_body, "supplementId": f"mlb-v18-population-geometry-{supplement_sha[:24]}", "supplementSha256": supplement_sha}
    write_json(staging / "manifest.json", manifest)
    target = OUTPUT / "sha256" / supplement_sha
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(staging)
    else:
        staging.replace(target)
    verify_manifest(target, expected_supplement_sha=supplement_sha)
    write_json(OUTPUT / "latest.json", {"supplementId": manifest["supplementId"], "supplementSha256": supplement_sha, "relativePath": target.relative_to(ROOT).as_posix()})
    print(json.dumps({"verdict": manifest["verdict"], "supplementId": manifest["supplementId"], "supplementSha256": supplement_sha, "path": str(target), "runtimeSeconds": round(time.perf_counter()-started, 3)}, sort_keys=True))
    return 0


def repackage(source: Path) -> int:
    """Correct packaging metadata without repeating an authoritative simulation."""

    started = time.perf_counter()
    source = source.resolve()
    old = verify_manifest(source)
    parent, play, _ = verify_parent_artifacts()
    summary = json.loads((source / "population-summary.json").read_text(encoding="utf-8"))
    staging = ROOT / ".runtime/asp-model-studio/v18-population-geometry" / f"package-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    preserved = [
        "population-summary.json", "population-accumulation-frames.json",
        "population-contact-density.json", "population-path-density.json",
        "population-runner-traffic.json", "representative-paths.json",
        "execution-authority.json.gz",
    ]
    for name in preserved:
        shutil.copy2(source / name, staging / name)
    summary_selectors = summary["representatives"]["selectors"]
    representatives = json.loads((staging / "representative-paths.json").read_text(encoding="utf-8"))
    for name, row in summary_selectors.items():
        row["rank"] = 1
        representatives["selectors"][name]["rank"] = 1
    write_json(staging / "population-summary.json", summary)
    write_json(staging / "representative-paths.json", representatives)
    size_rows = [file_record(staging / name, staging) for name in preserved]
    size_contract = {
        row["relativePath"]: {"uncompressedBytes": row["uncompressedBytes"], "compressedBytes": row["compressedBytes"]}
        for row in size_rows
    }
    write_json(staging / "aisp-population-geometry-handoff.json", build_handoff(summary, size_contract))
    execution = json.loads(gzip.decompress((staging / "execution-authority.json.gz").read_bytes()))
    (staging / "report.md").write_text(
        report(summary, {"bullpenEvidence": execution["bullpenEvidence"], "sizes": size_contract}, float(old["runtimeSeconds"])),
        encoding="utf-8",
    )
    artifacts = [file_record(path, staging) for path in sorted(staging.iterdir()) if path.is_file()]
    body = {
        key: value for key, value in old.items()
        if key not in {"supplementId", "supplementSha256", "artifacts", "packagingSourceSupplementSha256"}
    }
    body["artifacts"] = artifacts
    supplement_sha = sha(body)
    manifest = {**body, "supplementId": f"mlb-v18-population-geometry-{supplement_sha[:24]}", "supplementSha256": supplement_sha}
    write_json(staging / "manifest.json", manifest)
    target = OUTPUT / "sha256" / supplement_sha
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(staging)
    else:
        staging.replace(target)
    verify_manifest(target, expected_supplement_sha=supplement_sha)
    write_json(OUTPUT / "latest.json", {"supplementId": manifest["supplementId"], "supplementSha256": supplement_sha, "relativePath": target.relative_to(ROOT).as_posix()})
    print(json.dumps({"stage": "REPACKAGED", "sourceSupplementSha256": old["supplementSha256"], "supplementId": manifest["supplementId"], "supplementSha256": supplement_sha, "path": str(target), "runtimeSeconds": round(time.perf_counter()-started, 3)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--repackage-from":
        raise SystemExit(repackage(Path(sys.argv[2])))
    if len(sys.argv) != 1:
        raise SystemExit("usage: build_mlb_v18_population_geometry_supplement.py [--repackage-from PATH]")
    raise SystemExit(main())

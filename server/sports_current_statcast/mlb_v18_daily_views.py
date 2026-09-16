"""Content-addressed renderer supplements for immutable daily V18 forecasts.

The forecast object remains the parent authority.  This module replays its
saved execution inputs with the accepted model and seed, refuses any metric
drift, and publishes additive Play Geometry and Simulation Population objects.
It never reads AISP, calls a provider, fits a predictive model, or opens OOT.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
import gzip
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Callable, Mapping, Sequence
import uuid

import numpy as np
import pandas as pd

from scripts.build_mlb_v18_play_geometry_supplement import (
    EVAL_SEASONS,
    TRAIN_SEASONS,
    load_fd1_rows,
)
from server.sports_current_statcast.mlb_v18_daily_slate import (
    ACCEPTANCE_PROTOCOL_V2_SHA256,
    DailySlateError,
    PARENT_BUNDLE_SHA256,
    RESEARCH_FLAGS,
    SIMULATION_COUNT,
    V18ExecutionEngine,
    _as_utc,
    _verify_existing_object,
    collect_slate_forecasts,
    file_record,
    sha_bytes,
    sha_json,
    validate_forecast_payload,
    write_json,
)
from server.sports_current_statcast.mlb_v18_play_geometry import (
    COORDINATE_SYSTEM,
    COORDINATE_SYSTEM_DEFINITION,
    GEOMETRY_MODEL_VERSION,
    RUNNER_MODEL_VERSION,
    PlayGeometryModel,
)
from server.sports_current_statcast.mlb_v18_play_geometry_trace import enrich_path
from server.sports_current_statcast.mlb_v18_population_geometry import (
    FRAME_SIZE,
    PopulationAccumulator,
    accumulation_frames,
    attach_representatives,
    population_digest,
    reconcile_forecast,
    representative_indices,
)
from server.sports_current_statcast.mlb_v18_whole_game_challenger import (
    STATE_FEATURES,
    V18StateProbabilityProvider,
    V18WholeGameError,
    compose_raw_template,
    simulate_prospective_game,
)
from server.sports_datasets.consumer import canonical_json_bytes


VIEW_POINTER_SCHEMA = "MLB_V18_DAILY_VIEW_POINTER_V1"
PLAY_HANDOFF_SCHEMA = "AISP_MLB_V18_PLAY_GEOMETRY_HANDOFF_V1"
PLAY_SCHEMA = "MLB_V18_PLAY_GEOMETRY_TRACE_V1"
POPULATION_HANDOFF_SCHEMA = "AISP_MLB_V18_POPULATION_GEOMETRY_HANDOFF_V1"
POPULATION_MANIFEST_SCHEMA = "MLB_V18_POPULATION_GEOMETRY_MANIFEST_V1"
POPULATION_SUMMARY_SCHEMA = "MLB_V18_POPULATION_GEOMETRY_SUMMARY_V1"
POPULATION_LAYER_SCHEMA = "MLB_V18_POPULATION_GEOMETRY_SUPPLEMENT_V1"
POPULATION_FRAMES_SCHEMA = "MLB_V18_POPULATION_GEOMETRY_FRAMES_V1"
DISPLAY_PLAY = "RESEARCH_SHADOW_PLAY_GEOMETRY"
DISPLAY_POPULATION = "RESEARCH_SHADOW_POPULATION_GEOMETRY"


@dataclass(frozen=True)
class DailyViewResult:
    game_id: str
    object_sha256: str
    play_geometry: dict[str, Any]
    population_geometry: dict[str, Any]
    reproduction: dict[str, Any]
    already_present: bool


def _load_object(output_root: Path, row: Mapping[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    pointer = {
        "relativePath": row["relativePath"],
        "objectSha256": row["objectSha256"],
    }
    root = _verify_existing_object(output_root, pointer)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    forecast = json.loads((root / "forecast.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "pregame-evidence.json").read_text(encoding="utf-8"))
    execution = json.loads((root / "execution-inputs.json").read_text(encoding="utf-8"))
    representative = json.loads((root / "representative-path.json").read_text(encoding="utf-8"))
    validate_forecast_payload(evidence, {"forecast": forecast, "representativePath": representative})
    if sha_json(execution) != forecast.get("executionInputDigest"):
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "daily execution-input digest differs")
    if sha_json(execution.get("rawTemplates") or []) != forecast.get("rawTemplateDigest"):
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "daily raw-template digest differs")
    return root, manifest, forecast, evidence, execution, representative


def _forecast_contract(forecast: Mapping[str, Any]) -> dict[str, Any]:
    probability = forecast["probabilities"]
    expectations = forecast["expectations"]
    rates = forecast["rates"]
    simulation = forecast["simulation"]
    return {
        "homeWinProbability": float(probability["homeWin"]),
        "meanAwayRuns": float(expectations["awayRuns"]),
        "meanHomeRuns": float(expectations["homeRuns"]),
        "meanTotalRuns": float(expectations["totalRuns"]),
        "meanRunDifferential": float(expectations["homeMinusAwayRuns"]),
        "oneRunRate": float(rates["oneRunGame"]),
        "extraInningRate": float(rates["extraInning"]),
        "simulationCount": int(simulation["count"]),
        "masterSeed": int(simulation["seed"]),
        "illegalStateCount": int(simulation["illegalStateCount"]),
        "nonterminationCount": int(simulation["nonterminationCount"]),
    }


class _VectorizedTemplateProvider(V18StateProbabilityProvider):
    """Historical cache construction used by the published September 8 slate."""

    def __post_init__(self) -> None:
        if len(self.away_batters) != 9 or len(self.home_batters) != 9:
            raise V18WholeGameError("prospective batting orders must contain nine templates")
        if not self.away_bullpen or not self.home_bullpen:
            raise V18WholeGameError("each pregame team bullpen distribution must be nonempty")
        self._cache: dict[tuple[int, ...], np.ndarray] = {}
        self._treated_templates: dict[tuple[int, int, int], list[pd.Series]] = {}
        template_frames: list[pd.DataFrame] = []
        template_owners: list[tuple[int, int, int]] = []
        initial_state = {
            "context_inning": 1,
            "context_top_bottom": 0,
            "context_outs_before": 0,
            "context_base_mask_before": 0,
            "context_batting_score_diff_before": 0,
        }
        for is_top in (0, 1):
            batters = self.away_batters if is_top else self.home_batters
            starter = self.home_starter if is_top else self.away_starter
            bullpen = self.home_bullpen if is_top else self.away_bullpen
            for slot, batter in enumerate(batters):
                for is_bullpen, pitchers in ((0, (starter,)), (1, bullpen)):
                    for pitcher in pitchers:
                        template_frames.append(compose_raw_template(
                            source_order=self.pipeline.ordered_features,
                            batter_row=batter,
                            pitcher_row=pitcher,
                            state={**initial_state, "context_top_bottom": 0 if is_top else 1},
                        ))
                        template_owners.append((is_top, slot, is_bullpen))
        raw_templates = pd.concat(template_frames, ignore_index=True)
        treated_templates = self.pipeline.preprocessor.transform_frame(raw_templates)
        for owner, (_, row) in zip(
            template_owners, treated_templates.iterrows(), strict=True
        ):
            self._treated_templates.setdefault(owner, []).append(row)
        if any(name not in treated_templates.columns for name in STATE_FEATURES):
            raise V18WholeGameError("a dynamic game-state field is not directly executable")
        # This intentionally reproduces the optimized cache used by the
        # September 8 publisher before ONE_ROW_TRANSFORM_PER_TEMPLATE_V1 was
        # recorded.  Exact reconciliation against the immutable forecast is
        # the acceptance gate; equivalence to the successor scorer is not.


def _provider(
    engine: V18ExecutionEngine,
    execution: Mapping[str, Any],
    forecast: Mapping[str, Any],
    *,
    semantics: str | None = None,
) -> V18StateProbabilityProvider:
    values = execution.get("providerInputs") or {}
    required = (
        "awayBatters", "homeBatters", "awayStarter", "homeStarter",
        "awayBullpen", "homeBullpen",
    )
    if any(not values.get(name) for name in required):
        raise DailySlateError("PREPROCESSING_FAILURE", "saved daily provider inputs are incomplete")
    semantics = (
        semantics
        or (forecast.get("parentAuthority") or {}).get("providerCacheSemantics")
        or "VECTORIZED_TEMPLATE_TRANSFORM_V0"
    )
    provider_type = (
        V18StateProbabilityProvider
        if semantics == "ONE_ROW_TRANSFORM_PER_TEMPLATE_V1"
        else _VectorizedTemplateProvider
    )
    return provider_type(
        pipeline=engine.pipeline,
        away_batters=values["awayBatters"],
        home_batters=values["homeBatters"],
        away_starter=values["awayStarter"],
        home_starter=values["homeStarter"],
        away_bullpen=values["awayBullpen"],
        home_bullpen=values["homeBullpen"],
        temperature=None,
    )


def _artifact_reference(output_root: Path, target: Path, digest: str) -> dict[str, Any]:
    return {
        "supplementSha256": digest,
        "relativePath": target.relative_to(output_root).as_posix(),
        "manifestFile": "manifest.json",
    }


def _install(staging: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        for source in staging.iterdir():
            counterpart = target / source.name
            if not counterpart.is_file() or counterpart.read_bytes() != source.read_bytes():
                raise DailySlateError(
                    "PERSISTENCE_PUBLICATION_FAILURE",
                    f"content-addressed view artifact differs: {target.name}",
                )
        shutil.rmtree(staging)
    else:
        os.replace(staging, target)


class DailyViewBuilder:
    """One-authority builder reused across a slate; no predictive fitting."""

    def __init__(self, repo_root: Path, engine: V18ExecutionEngine | None = None):
        self.repo_root = repo_root.resolve()
        self.engine = engine or V18ExecutionEngine(self.repo_root)
        rows, self.geometry_authority = load_fd1_rows()
        self.geometry_model = PlayGeometryModel(
            fold_id="DEV_2023_2024_FIT_2025_EVAL", seasons=TRAIN_SEASONS
        )
        self.geometry_model.fit(
            row for row in rows if int(row.get("season") or 0) in TRAIN_SEASONS
        )
        self.geometry_reconstruction_count = 1

    def build(self, output_root: Path, row: Mapping[str, Any]) -> DailyViewResult:
        output_root = output_root.resolve()
        object_root, manifest, forecast, evidence, execution, representative = _load_object(
            output_root, row
        )
        object_sha = str(manifest["objectSha256"])
        game_id = str(forecast["gameId"])
        existing = read_view_pointer(output_root, object_sha)
        if existing is not None:
            return DailyViewResult(
                game_id=game_id,
                object_sha256=object_sha,
                play_geometry=existing["playGeometry"],
                population_geometry=existing["populationGeometry"],
                reproduction={"allMetricsMatch": True, "deterministicReplay": True},
                already_present=True,
            )

        recorded_semantics = (forecast.get("parentAuthority") or {}).get(
            "providerCacheSemantics"
        )
        provider_semantics = recorded_semantics or "VECTORIZED_TEMPLATE_TRANSFORM_V0"
        provider = _provider(
            self.engine, execution, forecast, semantics=provider_semantics
        )
        regulation = int((evidence.get("game") or {}).get("scheduled_innings") or 9)
        accepted = _forecast_contract(forecast)
        first = simulate_prospective_game(
            game_id=game_id,
            provider=provider,
            transition_model=self.engine.transition,
            n_sims=SIMULATION_COUNT,
            master_seed=int(forecast["simulation"]["seed"]),
            regulation=regulation,
            trace_count=0,
        )
        reproduction = reconcile_forecast(first, accepted)
        # The first September 8 publication predated an explicit semantics
        # marker and spans the publisher's transition from vectorized-template
        # caching to the successor one-row transform. Resolve that historical
        # ambiguity only by exact replay of the immutable forecast.
        if not reproduction["allMetricsMatch"] and recorded_semantics is None:
            alternate_semantics = "ONE_ROW_TRANSFORM_PER_TEMPLATE_V1"
            alternate_provider = _provider(
                self.engine, execution, forecast, semantics=alternate_semantics
            )
            alternate = simulate_prospective_game(
                game_id=game_id,
                provider=alternate_provider,
                transition_model=self.engine.transition,
                n_sims=SIMULATION_COUNT,
                master_seed=int(forecast["simulation"]["seed"]),
                regulation=regulation,
                trace_count=0,
            )
            alternate_reproduction = reconcile_forecast(alternate, accepted)
            if alternate_reproduction["allMetricsMatch"]:
                provider = alternate_provider
                provider_semantics = alternate_semantics
                first = alternate
                reproduction = alternate_reproduction
        if not reproduction["allMetricsMatch"]:
            mismatches = {
                key: value for key, value in reproduction["comparisons"].items()
                if not value["matches"]
            }
            raise DailySlateError(
                "SIMULATION_FAILURE",
                "daily 5,000-game replay differs from the published forecast: "
                + json.dumps(mismatches, sort_keys=True),
            )
        first_digest = population_digest(first)
        park = str((forecast.get("venue") or {}).get("name") or "UNKNOWN_PARK")
        enriched = enrich_path(
            model=self.geometry_model,
            path=representative["events"],
            park=park,
            path_index=0,
            game_id=game_id,
        )
        if len(enriched["events"]) != len(representative["events"]):
            raise DailySlateError("SIMULATION_FAILURE", "Play Geometry omitted a representative-path PA")

        play_ref = self._publish_play(
            output_root, manifest, forecast, enriched, object_root
        )
        selections = representative_indices(first, accepted)
        selected_indexes = sorted(
            {int(value["simulationIndex"]) for value in selections.values()}
        )
        if len(selected_indexes) != 6:
            raise DailySlateError("SIMULATION_FAILURE", "daily population did not select six distinct games")
        terminal = {
            "away": np.asarray(first["awayRuns"]),
            "home": np.asarray(first["homeRuns"]),
            "innings": np.asarray(first["innings"]),
        }
        accumulator = PopulationAccumulator(
            model=self.geometry_model,
            park=park,
            game_id=game_id,
            terminal=terminal,
        )
        second = simulate_prospective_game(
            game_id=game_id,
            provider=provider,
            transition_model=self.engine.transition,
            n_sims=SIMULATION_COUNT,
            master_seed=int(forecast["simulation"]["seed"]),
            regulation=regulation,
            trace_indices=selected_indexes,
            event_observer=accumulator.observe,
        )
        second_digest = population_digest(second)
        replay = reconcile_forecast(second, accepted)
        if second_digest != first_digest or not replay["allMetricsMatch"]:
            raise DailySlateError(
                "SIMULATION_FAILURE", "daily population replay is not deterministic"
            )
        representatives = attach_representatives(
            selections,
            selected_indexes,
            second["traces"],
            model=self.geometry_model,
            park=park,
            game_id=game_id,
        )
        population_ref = self._publish_population(
            output_root=output_root,
            manifest=manifest,
            forecast=forecast,
            execution=execution,
            play_ref=play_ref,
            accepted=accepted,
            first=first,
            second=second,
            first_digest=first_digest,
            reproduction=reproduction,
            accumulator=accumulator,
            representatives=representatives,
            provider_semantics=provider_semantics,
        )
        pointer_body = {
            "schemaVersion": VIEW_POINTER_SCHEMA,
            "gameId": game_id,
            "objectSha256": object_sha,
            "playGeometry": play_ref,
            "populationGeometry": population_ref,
            **RESEARCH_FLAGS,
        }
        pointer = {**pointer_body, "pointerSha256": sha_json(pointer_body)}
        write_json(output_root / "view-publications" / f"{object_sha}.json", pointer)
        return DailyViewResult(
            game_id=game_id,
            object_sha256=object_sha,
            play_geometry=play_ref,
            population_geometry=population_ref,
            reproduction={
                **reproduction,
                "firstPopulationDigest": first_digest,
                "replayPopulationDigest": second_digest,
                "deterministicReplay": True,
            },
            already_present=False,
        )

    def _publish_play(
        self,
        output_root: Path,
        manifest: Mapping[str, Any],
        forecast: Mapping[str, Any],
        enriched: Mapping[str, Any],
        object_root: Path,
    ) -> dict[str, Any]:
        object_sha = str(manifest["objectSha256"])
        supplement = {
            "schemaVersion": PLAY_SCHEMA,
            "supplementKind": "V18_DAILY_PLAY_GEOMETRY_TRACE_SUPPLEMENT",
            "parentBundleId": manifest["objectId"],
            "parentBundleSha256": object_sha,
            "coordinateSystem": COORDINATE_SYSTEM_DEFINITION,
            "geometryModelVersion": GEOMETRY_MODEL_VERSION,
            "runnerModelVersion": RUNNER_MODEL_VERSION,
            "dataAuthority": self.geometry_authority,
            "modelConfiguration": {
                "foldId": self.geometry_model.fold_id,
                "trainSeasons": list(TRAIN_SEASONS),
                "evaluationSeasons": list(EVAL_SEASONS),
                "rowsFitted": self.geometry_model.rows_fitted,
                "rowsWithLocation": self.geometry_model.rows_with_location,
                "rowsWithRunnerTemplate": self.geometry_model.rows_with_runner_template,
            },
            "v18Invariance": {
                "forecastSha256": sha_bytes((object_root / "forecast.json").read_bytes()),
                "representativePathSha256": sha_bytes((object_root / "representative-path.json").read_bytes()),
                "plateAppearancesBefore": enriched["plateAppearances"],
                "plateAppearancesAfter": len(enriched["events"]),
                "forecastModified": False,
            },
            "wageringAuthority": False,
            "promotionStatus": "NOT_PROMOTED",
            "executionAllowedInAISP": False,
            "displayAuthority": DISPLAY_PLAY,
            "finalOotOpened": False,
            "limitations": [
                "Geometry is modelled from registered Retrosheet location zones, not measured tracking.",
                "Runner identity is anonymous and movement is state-consistent.",
                "Presentation fractions are not measured physical timing.",
            ],
        }
        digest = sha_json(supplement)
        staging = output_root / ".staging" / "play-geometry" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=False)
        write_json(staging / "play-geometry-supplement.json", supplement)
        write_json(staging / "representative-paths.json", {"paths": [enriched]})
        handoff = {
            "schemaVersion": PLAY_HANDOFF_SCHEMA,
            "supplementId": f"mlb-v18-daily-play-geometry-{digest[:24]}",
            "supplementSha256": digest,
            "parentBundleId": manifest["objectId"],
            "parentBundleSha256": object_sha,
            "supplementFile": "play-geometry-supplement.json",
            "pathsFile": "representative-paths.json",
            "coordinateSystem": COORDINATE_SYSTEM,
            "wageringAuthority": False,
            "promotionStatus": "NOT_PROMOTED",
            "executionAllowedInAISP": False,
            "displayAuthority": DISPLAY_PLAY,
        }
        write_json(staging / "aisp-play-geometry-handoff.json", handoff)
        artifacts = [file_record(path, staging) for path in sorted(staging.iterdir())]
        write_json(staging / "manifest.json", {
            "supplementId": handoff["supplementId"],
            "supplementSha256": digest,
            "parentBundleSha256": object_sha,
            "artifacts": artifacts,
            "verdict": "V18_PLAY_GEOMETRY_TRACE_SUPPLEMENT_READY_FOR_AISP",
        })
        target = output_root / "play-geometry" / "sha256" / digest
        _install(staging, target)
        return _artifact_reference(output_root, target, digest)

    def _publish_population(
        self,
        *,
        output_root: Path,
        manifest: Mapping[str, Any],
        forecast: Mapping[str, Any],
        execution: Mapping[str, Any],
        play_ref: Mapping[str, Any],
        accepted: Mapping[str, Any],
        first: Mapping[str, Any],
        second: Mapping[str, Any],
        first_digest: str,
        reproduction: Mapping[str, Any],
        accumulator: PopulationAccumulator,
        representatives: Mapping[str, Any],
        provider_semantics: str,
    ) -> dict[str, Any]:
        object_sha = str(manifest["objectSha256"])
        play_sha = str(play_ref["supplementSha256"])
        authority_body = {
            "schemaVersion": "MLB_V18_DAILY_VIEW_EXECUTION_AUTHORITY_V1",
            "parentBundleSha256": object_sha,
            "sourceExecutionInputDigest": forecast["executionInputDigest"],
            "providerCacheSemantics": provider_semantics,
            "sourceObjectSha256": object_sha,
            "acceptedModelBundleSha256": PARENT_BUNDLE_SHA256,
            "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
            "geometryAuthorityManifestSha256": self.geometry_authority["manifestSha256"],
            "simulation": {"count": SIMULATION_COUNT, "seed": forecast["simulation"]["seed"]},
            "finalOot": {"opened": False, "rowsRead": 0, "targetsRead": 0},
            "operations": {"providerCalls": 0, "aispWrites": 0, "v18PredictiveModelFits": 0},
        }
        authority_sha = sha_json(authority_body)
        authority = {**authority_body, "executionAuthoritySha256": authority_sha}
        frames = accumulation_frames(first, accumulator.per_simulation)
        contact = accumulator.contact_payload()
        paths = accumulator.path_payload()
        runners = accumulator.runner_payload()
        summary = {
            "schemaVersion": POPULATION_SUMMARY_SCHEMA,
            "parentBundleId": manifest["objectId"],
            "parentBundleSha256": object_sha,
            "engineId": "MLB_V18_WHOLE_GAME_CHALLENGER_V1",
            "playGeometrySupplementSha256": play_sha,
            "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
            "masterSeed": forecast["simulation"]["seed"],
            "seedPolicy": forecast["simulation"]["seedPolicy"],
            "simulationCount": SIMULATION_COUNT,
            "populationDigest": first_digest,
            "populationDigestSchema": "ASP_V18_POPULATION_ARRAY_DIGEST_V1",
            "executionAuthoritySha256": authority_sha,
            "generatedAt": forecast["capturedAt"],
            "coordinateSystemVersion": COORDINATE_SYSTEM,
            "frameCount": len(frames),
            "frameSize": FRAME_SIZE,
            "counts": {
                "plateAppearances": accumulator.total_events,
                "contactPlays": accumulator.geometry_events,
                "geometryBearingPlays": accumulator.geometry_events,
                "scoringPlays": accumulator.scoring_events,
                "runnerSegments": int(sum(accumulator.runner_segments.values())),
            },
            "representatives": {
                "uniquePathCount": representatives["uniquePathCount"],
                "sharedSelections": representatives["sharedSelections"],
                "selectors": representatives["selectors"],
            },
            "reconstruction": {
                **reproduction,
                "firstPopulationDigest": first_digest,
                "replayPopulationDigest": population_digest(second),
                "deterministicReplay": True,
            },
            "finalPopulation": dict(accepted),
            "illegalStateCount": int(second["illegalStateCount"]),
            "nonterminationCount": int(second["nonterminationCount"]),
            "governance": {
                "researchShadow": True,
                "wageringAuthority": False,
                "promotionStatus": "NOT_PROMOTED",
                "executionAllowedInAISP": False,
                "finalOotOpened": False,
                "providerCalls": 0,
                "aispWrites": 0,
                "v18PredictiveModelFits": 0,
                "geometryAuthorityReconstructions": self.geometry_reconstruction_count,
                "recalibrations": 0,
            },
        }
        staging = output_root / ".staging" / "population-geometry" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=False)
        write_json(staging / "population-summary.json", summary)
        write_json(staging / "population-accumulation-frames.json", {
            "schemaVersion": POPULATION_FRAMES_SCHEMA, "frames": frames,
        })
        write_json(staging / "population-contact-density.json", contact)
        write_json(staging / "population-path-density.json", paths)
        write_json(staging / "population-runner-traffic.json", runners)
        write_json(staging / "representative-paths.json", representatives)
        (staging / "execution-authority.json.gz").write_bytes(
            gzip.compress(canonical_json_bytes(authority), compresslevel=9, mtime=0)
        )
        handoff = {
            "schemaVersion": POPULATION_HANDOFF_SCHEMA,
            "registrationState": "READY_FOR_AISP_AGENT_REGISTRATION_NOT_REGISTERED",
            "parentBundleId": manifest["objectId"],
            "parentBundleSha256": object_sha,
            "playGeometrySupplementSha256": play_sha,
            "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
            "populationDigest": first_digest,
            "simulationCount": SIMULATION_COUNT,
            "frameCount": len(frames),
            "wageringAuthority": False,
            "promotionStatus": "NOT_PROMOTED",
            "executionAllowedInAISP": False,
            "finalOotOpened": False,
            "aispModified": False,
        }
        write_json(staging / "aisp-population-geometry-handoff.json", handoff)
        artifacts = [file_record(path, staging) for path in sorted(staging.iterdir())]
        manifest_body = {
            "schemaVersion": POPULATION_MANIFEST_SCHEMA,
            "verdict": "V18_POPULATION_GEOMETRY_SUPPLEMENT_READY_FOR_AISP",
            "parentBundleId": manifest["objectId"],
            "parentBundleSha256": object_sha,
            "acceptedConfiguration": {
                "count": SIMULATION_COUNT,
                "masterSeed": forecast["simulation"]["seed"],
                "policy": forecast["simulation"]["seedPolicy"],
            },
            "playGeometrySupplementId": f"mlb-v18-daily-play-geometry-{play_sha[:24]}",
            "playGeometrySupplementSha256": play_sha,
            "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
            "executionAuthoritySha256": authority_sha,
            "populationDigest": first_digest,
            "simulationCount": SIMULATION_COUNT,
            "artifacts": artifacts,
            "finalOot": {"opened": False, "rowsRead": 0, "targetsRead": 0, "scored": False},
            "operations": {
                "v18PredictiveModelFits": 0,
                "geometryAuthorityReconstructions": self.geometry_reconstruction_count,
                "recalibrations": 0,
                "providerCalls": 0,
                "aispWrites": 0,
                "promotions": 0,
                "deployments": 0,
                "readinessPolicyStudies": 0,
            },
        }
        digest = sha_json(manifest_body)
        write_json(staging / "manifest.json", {
            **manifest_body,
            "supplementId": f"mlb-v18-daily-population-geometry-{digest[:24]}",
            "supplementSha256": digest,
        })
        target = output_root / "population-geometry" / "sha256" / digest
        _install(staging, target)
        return _artifact_reference(output_root, target, digest)


def read_view_pointer(output_root: Path, object_sha: str) -> dict[str, Any] | None:
    path = output_root / "view-publications" / f"{object_sha}.json"
    if not path.is_file():
        return None
    pointer = json.loads(path.read_text(encoding="utf-8"))
    body = {key: value for key, value in pointer.items() if key != "pointerSha256"}
    if (
        pointer.get("schemaVersion") != VIEW_POINTER_SCHEMA
        or pointer.get("objectSha256") != object_sha
        or pointer.get("pointerSha256") != sha_json(body)
    ):
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "daily view pointer differs")
    for key in ("playGeometry", "populationGeometry"):
        reference = pointer.get(key) or {}
        _verify_reference(output_root, reference, key)
    return pointer


def _verify_reference(
    output_root: Path, reference: Mapping[str, Any], family: str
) -> None:
    digest = str(reference.get("supplementSha256") or "")
    root = output_root / PurePosixPath(str(reference.get("relativePath") or ""))
    if len(digest) != 64 or root.name != digest or not (root / "manifest.json").is_file():
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", f"daily {family} pointer is incomplete")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("supplementSha256") != digest:
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", f"daily {family} manifest identity differs")
    for artifact in manifest.get("artifacts") or []:
        path = root / PurePosixPath(str(artifact.get("relativePath") or ""))
        raw = path.read_bytes()
        if len(raw) != int(artifact.get("bytes", -1)) or sha_bytes(raw) != artifact.get("sha256"):
            raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", f"daily {family} artifact differs")
    if family == "playGeometry":
        supplement = json.loads((root / "play-geometry-supplement.json").read_text(encoding="utf-8"))
        actual = sha_json(supplement)
    else:
        body = {
            key: value for key, value in manifest.items()
            if key not in {"supplementId", "supplementSha256"}
        }
        actual = sha_json(body)
    if actual != digest:
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", f"daily {family} canonical identity differs")


def view_references(output_root: Path, object_sha: str) -> dict[str, Any] | None:
    pointer = read_view_pointer(output_root, object_sha)
    if pointer is None:
        return None
    return {
        "playGeometry": pointer["playGeometry"],
        "populationGeometry": pointer["populationGeometry"],
    }


def backfill_slate_views(
    output_root: Path,
    slate_date: date,
    *,
    repo_root: Path,
    workers: int = 1,
    engine: V18ExecutionEngine | None = None,
    game_ids: Sequence[str] = (),
    progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Backfill every published forecast on a slate without changing it."""

    if workers < 1 or workers > 4:
        raise ValueError("workers must be between 1 and 4")
    root = output_root.resolve()
    requested = {str(value) for value in game_ids}
    rows = [
        row for row in collect_slate_forecasts(root, slate_date)
        if not requested or str(row.get("gameId")) in requested
    ]
    builder = DailyViewBuilder(repo_root, engine=engine)

    def build(row: Mapping[str, Any]) -> dict[str, Any]:
        try:
            result = builder.build(root, row)
            return {
                "gameId": result.game_id,
                "objectSha256": result.object_sha256,
                "status": "ALREADY_PRESENT" if result.already_present else "BACKFILLED",
                "forecastReproduction": result.reproduction,
                "playGeometry": result.play_geometry,
                "populationGeometry": result.population_geometry,
            }
        except Exception as exc:
            return {
                "gameId": str(row.get("gameId")),
                "objectSha256": str(row.get("objectSha256")),
                "status": "FAILED",
                "reason": str(exc),
            }

    ordered: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="v18-daily-views") as pool:
        futures = {pool.submit(build, row): index for index, row in enumerate(rows)}
        for future in as_completed(futures):
            result = future.result()
            ordered[futures[future]] = result
            if progress is not None:
                progress(result)
    results = [ordered[index] for index in sorted(ordered)]
    failures = [row for row in results if row["status"] == "FAILED"]
    return {
        "schemaVersion": "MLB_V18_DAILY_VIEW_BACKFILL_RECEIPT_V1",
        "slateDate": slate_date.isoformat(),
        "gamesRequested": len(rows),
        "gamesBackfilled": sum(row["status"] == "BACKFILLED" for row in results),
        "alreadyPresent": sum(row["status"] == "ALREADY_PRESENT" for row in results),
        "gamesFailed": len(failures),
        "forecastReproductionPassed": sum(
            row.get("forecastReproduction", {}).get("allMetricsMatch") is True
            and row.get("forecastReproduction", {}).get("deterministicReplay") is True
            for row in results
        ),
        "results": results,
        "modelLoads": builder.engine.model_load_count,
        "v18PredictiveModelFits": builder.engine.fit_count,
        "geometryAuthorityReconstructions": builder.geometry_reconstruction_count,
        "providerCalls": 0,
        "aispWrites": 0,
        "finalOot": {"opened": False, "rowsRead": 0, "targetsRead": 0, "scored": False},
        **RESEARCH_FLAGS,
    }


__all__ = [
    "DailyViewBuilder",
    "DailyViewResult",
    "backfill_slate_views",
    "read_view_pointer",
    "view_references",
]

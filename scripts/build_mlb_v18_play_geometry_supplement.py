"""Fit, evaluate and publish the V18 Play Geometry trace supplement.

Bounded, Development-only, read-only with respect to every accepted artifact.
It loads registered FD1 ``play_transition`` evidence, fits fold-local geometry
and runner-movement distributions, evaluates them chronologically, enriches the
accepted V18 representative path, verifies V18 invariance, and writes a
content-addressed supplement plus an AISP handoff.

    python -m scripts.build_mlb_v18_play_geometry_supplement

Final OOT is never opened: only FD1 Development seasons declared below are read,
and they are registered as retrospective target evidence.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from server.sports_current_statcast.mlb_v18_play_geometry import (  # noqa: E402
    COORDINATE_SYSTEM,
    COORDINATE_SYSTEM_DEFINITION,
    GEOMETRY_MODEL_VERSION,
    PARENT_BUNDLE_ID,
    PARENT_BUNDLE_SHA256,
    RUNNER_MODEL_VERSION,
    SCHEMA_VERSION,
    UNSUPPORTED_GEOMETRY_FIELDS,
    PlayGeometryModel,
    observed_runner_template,
    parse_event_text,
    template_is_legal,
)
from server.sports_current_statcast.mlb_v18_play_geometry_trace import (  # noqa: E402
    SELECTORS,
    build_ball_trace,
    enrich_path,
    select_representative_paths,
    verify_v18_invariance,
)

DATABASE = REPOSITORY_ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db"
EXCHANGE_ROOT = Path(r"C:\Users\james\asp-model-exchange")
BUNDLE = (
    REPOSITORY_ROOT / "outputs/mlb-v18-whole-game-challenger/sha256" / PARENT_BUNDLE_SHA256
)
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs/mlb-v18-play-geometry"

FD1_REGISTRATION_ID = "sports-dataset-1b58d5d1def2c9b7"
FD1_MANIFEST_SHA256 = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
FD1_LOGICAL_PREFIX = "asp-model-exchange://"

#: Chronological Development window, matching the accepted V18 game baseline.
DEVELOPMENT_SEASONS = (2023, 2024, 2025)
#: Fit on the earlier seasons, evaluate on the later one. No future evidence
#: reaches a fitted distribution.
TRAIN_SEASONS = (2023, 2024)
EVAL_SEASONS = (2025,)

COLUMNS = (
    "game_id", "game_date", "season", "plate_appearance_id", "play_number",
    "pa_outcome", "event_text", "park_id", "batter_id",
    "outs_before", "outs_after", "base_mask_before", "base_mask_after",
    "runs_scored",
    "runner_on_first_before", "runner_on_second_before", "runner_on_third_before",
    "runner_on_first_after", "runner_on_second_after", "runner_on_third_after",
)


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def load_fd1_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Registered, checksum-verified FD1 play transitions for Development."""

    connection = sqlite3.connect(str(DATABASE))
    connection.row_factory = sqlite3.Row
    try:
        registration = connection.execute(
            "SELECT manifest_sha, validation_status, active FROM sports_dataset_registrations "
            "WHERE registration_id = ?",
            (FD1_REGISTRATION_ID,),
        ).fetchone()
        if registration is None:
            raise RuntimeError("FD1 registration is unavailable.")
        if (
            str(registration["manifest_sha"]) != FD1_MANIFEST_SHA256
            or str(registration["validation_status"]) != "VALID"
            or int(registration["active"]) != 1
        ):
            raise RuntimeError("FD1 registration differs from the pinned authority.")
        partitions = connection.execute(
            "SELECT season, month, logical_uri, row_count, file_sha, "
            "target_eligibility_json, temporal_classification_json "
            "FROM sports_dataset_partitions WHERE registration_id = ? AND family = 'play_transition' "
            f"AND season IN ({','.join('?' * len(DEVELOPMENT_SEASONS))}) ORDER BY season, month",
            (FD1_REGISTRATION_ID, *DEVELOPMENT_SEASONS),
        ).fetchall()
    finally:
        connection.close()

    rows: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    root = EXCHANGE_ROOT.resolve()
    for partition in partitions:
        uri = str(partition["logical_uri"])
        if not uri.startswith(FD1_LOGICAL_PREFIX):
            raise RuntimeError("FD1 logical URI is outside the registered scheme.")
        relative = PurePosixPath(uri[len(FD1_LOGICAL_PREFIX):])
        path = root.joinpath(*relative.parts).resolve()
        path.relative_to(root)
        if not path.is_file() or sha_bytes(path.read_bytes()) != str(partition["file_sha"]):
            raise RuntimeError(f"FD1 partition bytes differ: {uri}")
        table = pq.read_table(path, columns=list(COLUMNS))
        if table.num_rows != int(partition["row_count"]):
            raise RuntimeError(f"FD1 partition row count differs: {uri}")
        rows.extend(table.to_pylist())
        inventory.append({
            "season": int(partition["season"]),
            "month": int(partition["month"]),
            "rowCount": int(partition["row_count"]),
            "fileSha256": str(partition["file_sha"]),
            "targetEligibility": json.loads(partition["target_eligibility_json"] or "[]"),
            "temporalClassification": json.loads(partition["temporal_classification_json"] or "[]"),
        })

    authority = {
        "registrationId": FD1_REGISTRATION_ID,
        "manifestSha256": FD1_MANIFEST_SHA256,
        "family": "play_transition",
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "trainSeasons": list(TRAIN_SEASONS),
        "evaluationSeasons": list(EVAL_SEASONS),
        "partitionCount": len(inventory),
        "observationCount": len(rows),
        "partitions": inventory,
        "finalOotOpened": False,
        "usedAs": "CHRONOLOGICAL_DEVELOPMENT_TRAINING_TARGET_ONLY",
    }
    return rows, authority


def audit_fields(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Bounded inventory of what the registered evidence does and does not carry."""

    total = len(rows)
    parsed = [parse_event_text(row.get("event_text")) for row in rows]
    contact = [item for item in parsed if item.contact]
    located = [item for item in contact if item.has_location and item.trajectory]
    with_template = sum(1 for row in rows if observed_runner_template(row) is not None)

    return {
        "observationCount": total,
        "supported": {
            "paOutcome": {"present": sum(1 for r in rows if r.get("pa_outcome")), "usableAsTarget": True},
            "outsBeforeAfter": {"present": total, "usableAsTarget": True},
            "baseMaskBeforeAfter": {"present": total, "usableAsTarget": True},
            "runsScored": {"present": total, "usableAsTarget": True},
            "explicitRunnerIdentifiers": {
                "present": with_template,
                "missingness": round(1 - with_template / total, 6) if total else None,
                "semantics": "Retrosheet identifier occupying each base before and after the play.",
                "usableAsTarget": True,
                "prospectiveUse": "NOT_A_PREGAME_FEATURE",
            },
            "battedBallTrajectory": {
                "present": sum(1 for item in contact if item.trajectory),
                "semantics": "Retrosheet G/L/F/P trajectory letter.",
                "usableAsTarget": True,
            },
            "hitLocationZone": {
                "present": len(located),
                "missingness": round(1 - len(located) / len(contact), 6) if contact else None,
                "semantics": "Retrosheet fielding-location zone with an optional depth modifier.",
                "usableAsTarget": True,
            },
            "parkIdentity": {"present": sum(1 for r in rows if r.get("park_id")), "usableAsTarget": True},
        },
        "unsupported": {
            name: {"present": 0, "reason": reason}
            for name, reason in UNSUPPORTED_GEOMETRY_FIELDS.items()
        },
        "searchedAuthorities": [
            "FD1 play_transition (ACTIVE, registered)",
            "FD1 plate_appearance / pitch_sequence / player_game_fielding / weather",
            "sports-dataset-current-statcast (INACTIVE registration)",
            "Silver current_statcast_pa contract",
            "Gold sports contracts",
        ],
        "notes": [
            "FD1 pitch_sequence carries contact_tracking_available as a coverage flag "
            "only; it retains no measured tracking value.",
            "The Silver current-Statcast PA contract retains bb_type but its "
            "registration is inactive and it does not retain launch_speed, "
            "launch_angle, hc_x, hc_y or hit_distance_sc.",
            "Batter and pitcher handedness are absent from play_transition, so "
            "handedness is not a geometry conditioning level.",
        ],
    }


def evaluate(model: PlayGeometryModel, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fold-local evaluation on held-out chronological evidence."""

    observed_bb: Counter = Counter()
    sampled_bb: Counter = Counter()
    observed_zone: Counter = Counter()
    sampled_zone: Counter = Counter()
    observed_depth: Counter = Counter()
    sampled_depth: Counter = Counter()
    geometry_backoff: Counter = Counter()
    runner_backoff: Counter = Counter()
    geometry_rows = compatible = fair_valid = 0
    missing_geometry = 0

    template_rows = template_exact = destination_correct = destination_total = 0
    illegal = 0
    by_outcome: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "exact": 0, "backoff": 0})

    for index, row in enumerate(rows):
        outcome = row.get("pa_outcome")
        if not outcome:
            continue
        parsed = parse_event_text(row.get("event_text"))
        park = str(row.get("park_id") or "UNKNOWN_PARK")
        seed = (row.get("plate_appearance_id"), index)

        geometry = model.sample_geometry(outcome=outcome, park=park, seed=seed)
        geometry_rows += 1
        geometry_backoff[geometry.get("geometryBackoffLevel") or "NO_CONTACT"] += 1
        if geometry["contactOccurred"] and geometry.get("point") is None:
            missing_geometry += 1
        # A non-contact outcome must never receive geometry, and a contact
        # outcome must never be assigned a non-contact geometry.
        if geometry["contactOccurred"] == parsed.contact:
            compatible += 1
        if geometry.get("point") is not None and geometry["point"]["fairTerritory"]:
            fair_valid += 1
        if parsed.contact and parsed.trajectory:
            observed_bb[parsed.trajectory] += 1
            observed_zone[parsed.zone] += 1
            observed_depth[parsed.depth or "UNMODIFIED"] += 1
        if geometry.get("battedBallType"):
            sampled_bb[geometry["battedBallType"]] += 1
            sampled_zone[geometry.get("locationZone")] += 1
            sampled_depth[geometry.get("depthModifier") or "UNMODIFIED"] += 1

        truth = observed_runner_template(row)
        if truth is None:
            continue
        mask_before = int(row.get("base_mask_before") or 0)
        mask_after = int(row.get("base_mask_after") or 0)
        runs = int(row.get("runs_scored") or 0)
        outs_added = int(row.get("outs_after") or 0) - int(row.get("outs_before") or 0)
        outs_before = int(row.get("outs_before") or 0)
        if not template_is_legal(
            truth, mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        ):
            continue
        template, level, _ = model.sample_runner_template(
            outcome=outcome, mask_before=mask_before,
            outs_before=outs_before, runs=runs,
            mask_after=mask_after, outs_added=outs_added,
            batted_ball_type=parsed.trajectory, seed=seed,
        )
        template_rows += 1
        runner_backoff[level] += 1
        bucket = by_outcome[outcome]
        bucket["n"] += 1
        if level == "DETERMINISTIC_LEGAL_BACKOFF":
            bucket["backoff"] += 1
        if not template_is_legal(
            template, mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        ):
            illegal += 1
        if tuple(template) == tuple(truth):
            template_exact += 1
            bucket["exact"] += 1
        truth_map = dict(truth)
        for origin, destination in template:
            destination_total += 1
            if truth_map.get(origin) == destination:
                destination_correct += 1

    def agreement(left: Counter, right: Counter) -> float | None:
        keys = set(left) | set(right)
        left_total = sum(left.values()) or 1
        right_total = sum(right.values()) or 1
        if not keys:
            return None
        distance = sum(
            abs(left[key] / left_total - right[key] / right_total) for key in keys
        ) / 2
        return round(1 - distance, 6)

    return {
        "evaluationSeasons": list(EVAL_SEASONS),
        "geometry": {
            "rowsEvaluated": geometry_rows,
            "battedBallTypeAgreement": agreement(observed_bb, sampled_bb),
            "locationZoneAgreement": agreement(observed_zone, sampled_zone),
            "depthClassAgreement": agreement(observed_depth, sampled_depth),
            "outcomeCompatibilityRate": round(compatible / geometry_rows, 6) if geometry_rows else None,
            "fairTerritoryValidRate": (
                round(fair_valid / sum(sampled_bb.values()), 6) if sum(sampled_bb.values()) else None
            ),
            "missingGeometryRate": round(missing_geometry / geometry_rows, 6) if geometry_rows else None,
            "backoffUsage": dict(geometry_backoff),
            "observedBattedBallTypes": dict(observed_bb),
            "sampledBattedBallTypes": dict(sampled_bb),
            "unsupportedFields": sorted(UNSUPPORTED_GEOMETRY_FIELDS),
            "note": (
                "Exit velocity, launch angle, spray angle and distance are not "
                "registered, so no distribution agreement is reported for them."
            ),
        },
        "runnerMovements": {
            "rowsEvaluated": template_rows,
            "exactJointTemplateAccuracy": (
                round(template_exact / template_rows, 6) if template_rows else None
            ),
            "destinationAccuracy": (
                round(destination_correct / destination_total, 6) if destination_total else None
            ),
            "illegalTransitionRate": round(illegal / template_rows, 6) if template_rows else 0.0,
            "scoredRunReconciliationRate": 1.0,
            "outReconciliationRate": 1.0,
            "endingBaseStateReconciliationRate": 1.0,
            "reconciliationNote": (
                "Runs, outs and ending occupancy are enforced by construction: a "
                "template that violates any of them is rejected before it can be "
                "emitted, so these rates are 1.0 by invariant, not by fit."
            ),
            "backoffUsage": dict(runner_backoff),
            "byOutcome": {
                outcome: {
                    "n": bucket["n"],
                    "exactTemplateAccuracy": round(bucket["exact"] / bucket["n"], 6) if bucket["n"] else None,
                    "backoffRate": round(bucket["backoff"] / bucket["n"], 6) if bucket["n"] else None,
                }
                for outcome, bucket in sorted(by_outcome.items())
            },
        },
        "baseline": {
            "name": "DETERMINISTIC_LEGAL_BACKOFF",
            "description": (
                "Lead-runner-first legal assignment with no historical fitting. "
                "The fitted sampler is compared against it on exact joint "
                "template accuracy."
            ),
        },
    }


def evaluate_baseline(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The transparent baseline: legal backoff with no fitted distribution."""

    from server.sports_current_statcast.mlb_v18_play_geometry import legal_backoff_template

    total = exact = 0
    for row in rows:
        truth = observed_runner_template(row)
        if truth is None:
            continue
        mask_before = int(row.get("base_mask_before") or 0)
        mask_after = int(row.get("base_mask_after") or 0)
        runs = int(row.get("runs_scored") or 0)
        outs_added = int(row.get("outs_after") or 0) - int(row.get("outs_before") or 0)
        outs_before = int(row.get("outs_before") or 0)
        if not template_is_legal(
            truth, mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        ):
            continue
        candidate = legal_backoff_template(
            mask_before=mask_before, mask_after=mask_after, runs=runs,
            outs_added=outs_added, outs_before=outs_before,
        )
        if candidate is None:
            continue
        total += 1
        if tuple(candidate) == tuple(truth):
            exact += 1
    return {
        "rowsEvaluated": total,
        "exactJointTemplateAccuracy": round(exact / total, 6) if total else None,
    }


def main() -> int:
    started = time.perf_counter()
    print(json.dumps({"stage": "LOAD_FD1"}), flush=True)
    rows, authority = load_fd1_rows()

    print(json.dumps({"stage": "AUDIT", "rows": len(rows)}), flush=True)
    inventory = audit_fields(rows)

    train = [row for row in rows if int(row.get("season") or 0) in TRAIN_SEASONS]
    evaluation_rows = [row for row in rows if int(row.get("season") or 0) in EVAL_SEASONS]
    print(json.dumps({"stage": "FIT", "train": len(train), "eval": len(evaluation_rows)}), flush=True)

    model = PlayGeometryModel(fold_id="DEV_2023_2024_FIT_2025_EVAL", seasons=TRAIN_SEASONS)
    model.fit(train)

    print(json.dumps({"stage": "EVALUATE"}), flush=True)
    metrics = evaluate(model, evaluation_rows)
    metrics["baselineResult"] = evaluate_baseline(evaluation_rows)

    print(json.dumps({"stage": "ENRICH"}), flush=True)
    forecast = json.loads((BUNDLE / "prospective-forecast.json").read_text(encoding="utf-8"))
    snapshot = json.loads((BUNDLE / "aisp-pregame-snapshot.json").read_text(encoding="utf-8"))
    park = str((snapshot.get("game") or {}).get("venue") or "UNKNOWN_PARK")
    accepted_paths = forecast.get("traces") or []

    enriched = []
    for position, path in enumerate(accepted_paths):
        enriched.append(enrich_path(
            model=model, path=path, park=park,
            path_index=position, game_id=str(forecast.get("gameId")),
        ))

    selection = select_representative_paths(enriched, forecast)
    invariance = verify_v18_invariance(forecast, enriched)

    runtime = round(time.perf_counter() - started, 3)
    supplement = {
        "schemaVersion": SCHEMA_VERSION,
        "supplementKind": "V18_PLAY_GEOMETRY_TRACE_SUPPLEMENT",
        "parentBundleId": PARENT_BUNDLE_ID,
        "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "coordinateSystem": COORDINATE_SYSTEM_DEFINITION,
        "geometryModelVersion": GEOMETRY_MODEL_VERSION,
        "runnerModelVersion": RUNNER_MODEL_VERSION,
        "dataAuthority": authority,
        "fieldInventory": inventory,
        "modelConfiguration": {
            "foldId": model.fold_id,
            "trainSeasons": list(TRAIN_SEASONS),
            "evaluationSeasons": list(EVAL_SEASONS),
            "minimumSupport": model.geometry.minimum_support,
            "geometryBackoffHierarchy": ["outcome_park", "outcome", "league_contact_prior"],
            "runnerBackoffHierarchy": [
                "outcome_state_outs_runs_after_bbtype",
                "outcome_state_outs_runs_after",
                "outcome_state_runs_after",
                "state_runs_after",
                "DETERMINISTIC_LEGAL_BACKOFF",
            ],
            "rowsFitted": model.rows_fitted,
            "rowsWithLocation": model.rows_with_location,
            "rowsWithRunnerTemplate": model.rows_with_runner_template,
        },
        "evaluation": metrics,
        "representativePaths": selection,
        "parkConditioningNote": (
            "The accepted pregame snapshot records a venue NAME while the "
            "registered FD1 evidence keys parks by Retrosheet park id. No "
            "registered crosswalk between the two exists, so geometry for the "
            "prospective game falls back one level to the outcome-conditional "
            "distribution. That backoff is reported per play rather than "
            "resolved by guessing a park."
        ),
        "v18Invariance": invariance,
        "wageringAuthority": False,
        "promotionStatus": "NOT_PROMOTED",
        "executionAllowedInAISP": False,
        "displayAuthority": "RESEARCH_SHADOW_PLAY_GEOMETRY",
        "finalOotOpened": False,
        "runtimeSeconds": runtime,
        "limitations": [
            "Exit velocity, launch angle, spray angle in degrees and landing "
            "distance in feet are not registered and are emitted as null.",
            "The emitted point is a Retrosheet location-zone centroid, not a "
            "measured landing coordinate.",
            "Runner identity is anonymous. A reconstructed movement is a "
            "state-consistent template, never a named player's real route.",
            "startFraction and endFraction are presentation sequencing values, "
            "not measured timestamps.",
            "V1 does not claim the sampled geometry caused the already-sampled "
            "V18 outcome.",
        ],
    }

    digest = sha_bytes(canonical(supplement))
    target = OUTPUT_ROOT / "sha256" / digest
    target.mkdir(parents=True, exist_ok=True)
    (target / "play-geometry-supplement.json").write_text(
        json.dumps(supplement, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (target / "representative-paths.json").write_text(
        json.dumps({"paths": enriched}, indent=2, sort_keys=True, default=str), encoding="utf-8")

    handoff = {
        "schemaVersion": "AISP_MLB_V18_PLAY_GEOMETRY_HANDOFF_V1",
        "supplementId": f"mlb-v18-play-geometry-{digest[:24]}",
        "supplementSha256": digest,
        "parentBundleId": PARENT_BUNDLE_ID,
        "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "supplementFile": "play-geometry-supplement.json",
        "pathsFile": "representative-paths.json",
        "coordinateSystem": COORDINATE_SYSTEM,
        "wageringAuthority": False,
        "promotionStatus": "NOT_PROMOTED",
        "executionAllowedInAISP": False,
        "displayAuthority": "RESEARCH_SHADOW_PLAY_GEOMETRY",
        "verification": [
            "Hash play-geometry-supplement.json canonically and require it to "
            "equal supplementSha256.",
            "Require parentBundleSha256 to equal the registered V18 shadow "
            "forecast's bundle checksum before associating the supplement.",
            "Require wageringAuthority=false, promotionStatus=NOT_PROMOTED and "
            "executionAllowedInAISP=false.",
        ],
        "association": (
            "Attach to the shadow forecast whose bundle_sha256 equals "
            "parentBundleSha256. The supplement never replaces the persisted "
            "path; it adds a geometry layer beside it."
        ),
        "rendering": {
            "ballTrace": (
                "Draw only when contactOccurred is true and ballTrace is present. "
                "Use start, control and end in the normalized coordinate system, "
                "mapping y to the home-plate-to-centre-field axis."
            ),
            "runnerTrace": (
                "Draw one path per runnerMovements entry using from/to base "
                "states. startFraction/endFraction are presentation sequencing "
                "values only."
            ),
            "modelledVersusPersisted": (
                "Fields under geometry and runnerMovements are MODELLED. "
                "outcome, outs, base masks, runs and scores are PERSISTED V18 "
                "state and must be rendered exactly as given.",
            ),
            "timing": (
                "No measured timing authority exists. Never present "
                "startFraction/endFraction as elapsed real time."
            ),
            "failClosed": (
                "If geometry is missing, absent or fails verification, render "
                "the existing Broadcast Replay without ball traces. Never "
                "synthesise a trajectory in the consumer."
            ),
            "preserveExisting": (
                "The existing V18 Broadcast Replay remains the default view. "
                "Play Geometry is an additional, separately labelled view."
            ),
        },
        "limitations": supplement["limitations"],
    }
    (target / "aisp-play-geometry-handoff.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True), encoding="utf-8")

    manifest = {
        "supplementId": handoff["supplementId"],
        "supplementSha256": digest,
        "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "artifacts": [
            {
                "relativePath": name,
                "sha256": sha_bytes((target / name).read_bytes()),
                "bytes": (target / name).stat().st_size,
            }
            for name in sorted(
                p.name for p in target.iterdir() if p.name != "manifest.json"
            )
        ],
        "verdict": "V18_PLAY_GEOMETRY_TRACE_SUPPLEMENT_READY_FOR_AISP",
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "latest.json").write_text(
        json.dumps({"supplementSha256": digest, "path": str(target.relative_to(REPOSITORY_ROOT))},
                   indent=2), encoding="utf-8")

    print(json.dumps({
        "stage": "DONE",
        "supplementSha256": digest,
        "enrichedPaths": len(enriched),
        "selectorsSatisfied": len(selection["satisfied"]),
        "invariance": invariance["allInvariantsHeld"],
        "runtimeSeconds": runtime,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Focused integration and reconciliation check for the MLB V18 ensemble candidate."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts.run_mlb_v18_ensemble_release_candidate_v1 import duration_supported
from server.sports_current_statcast.mlb_v18_ensemble_candidate import load_calibrator
from server.sports_current_statcast.mlb_v18_prospective_transform import (
    HistoricalReplayFrameAuthority,
    ProspectiveFrameAuthority,
    ProspectiveAuthorityError,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


OUT = ROOT / "outputs/mlb-v18-ensemble-release-candidate-v1"


def digest(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path: Path | str) -> dict:
    target = Path(path).resolve(strict=True)
    return {"path": str(target), "sha256": digest(target), "bytes": target.stat().st_size}


def verify_ref(reference: dict) -> None:
    path = Path(reference["path"]).resolve(strict=True)
    if digest(path) != reference["sha256"] or path.stat().st_size != int(reference["bytes"]):
        raise ValueError("Reference reconciliation failed: " + str(path))


def refs(value):
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"} <= set(value):
            yield value
        for child in value.values():
            yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    current_path = OUT / "current.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    package_path = Path(current["package"]["path"])
    package = json.loads(package_path.read_text(encoding="utf-8"))
    selection_path = Path(package["comparison"]["calibration"]["path"])
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    game_path = Path(package["comparison"]["game"]["path"])
    game = json.loads(game_path.read_text(encoding="utf-8"))
    manifest_path = OUT / "manifest.json"
    manifest_before = ref(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    checked = {}
    for document in (current, package, selection, game, manifest):
        for reference in refs(document):
            verify_ref(reference)
            checked[reference["sha256"]] = reference

    if package["classOrder"] != list(PA_CLASS_ORDER) or package["defaultConfiguration"] != "A_FROZEN_V18_BASELINE_HOOK":
        raise ValueError("Release class order or default configuration differs")
    if selection["selected"] is not None or selection["selectionEligibleCandidates"]:
        raise ValueError("A calibration candidate was enabled despite the frozen selection rule")
    probe = np.asarray([[.20, .09, .03, .15, .05, .01, .46, .01]], dtype=float)
    validate_probability_matrix(probe, class_order=PA_CLASS_ORDER)
    for reference in selection["artifacts"].values():
        result = load_calibrator(reference).transform(probe)
        validate_probability_matrix(result, class_order=PA_CLASS_ORDER)

    if (game["status"] != "COMPLETED_ONE_GAME_HISTORICAL_REPLAY_TOO_SPARSE_FOR_ORDERING"
            or set(game["configurationResults"]) != {
                "A_FROZEN_V18_BASELINE_HOOK", "B_V18_PLUS_CALIBRATION",
                "C_V18_PLUS_DURATION", "D_V18_PLUS_CALIBRATION_PLUS_DURATION"
            }):
        raise ValueError("Four-way game comparison is incomplete")
    for value in game["configurationResults"].values():
        if value["simulations"] != 5000 or value["illegalStateCount"] or value["nonterminationCount"]:
            raise ValueError("Game replay accounting failed")
    if game["paReload"]["initialProbabilityMismatches"] != 0:
        raise ValueError("Saved initial probability reproduction failed")

    pair = json.loads(Path(game["v18Pair"]["path"]).read_text(encoding="utf-8"))
    pair_inputs = json.loads(Path(pair["inputs"]["path"]).read_text(encoding="utf-8"))
    unsupported = deepcopy(pair_inputs["durationInputs"])
    unsupported["status"] = "UNSUPPORTED_TEST_FIXTURE"
    if duration_supported(unsupported):
        raise ValueError("Unsupported duration input did not fail closed")

    now = datetime.now(timezone.utc)
    try:
        ProspectiveFrameAuthority(event_id="fixture", game_date="2026-09-11",
            evidence_cutoff_utc=(now-timedelta(days=2)).isoformat(),
            kickoff_utc=(now-timedelta(days=1)).isoformat(), snapshot_sha256="0"*64,
            authorized_at_utc=(now-timedelta(days=2)).isoformat(), venue_timezone="America/Detroit").validate()
    except ProspectiveAuthorityError:
        prospective_post_start_rejected = True
    else:
        raise ValueError("Live prospective authority accepted a post-start invocation")

    feature = json.loads(Path(pair_inputs["featureSnapshot"]["path"]).read_text(encoding="utf-8"))
    HistoricalReplayFrameAuthority(
        event_id=pair["gameId"], game_date="2026-09-11",
        evidence_cutoff_utc=pair_inputs["sourceCutoff"]["evidenceAvailableAt"],
        captured_at_utc=game["paReload"]["archivedPregameCapture"],
        original_forecast_created_at_utc=pair_inputs["originalForecastCreatedAt"],
        kickoff_utc=pair["scheduledStartUtc"], snapshot_sha256=pair_inputs["featureSnapshot"]["sha256"],
        replay_authorized_at_utc=now.isoformat(), venue_timezone=feature["composition"]["venueTimezone"],
    ).validate()

    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if branch != package["branch"] or head != package["head"]:
        raise ValueError("Branch or HEAD changed after package construction")

    receipt = {
        "schemaVersion": "MLB_V18_ENSEMBLE_RC_INTEGRATION_VERIFICATION_V1",
        "verifiedAt": now.isoformat(), "candidateId": package["candidateId"],
        "checks": {
            "referencedArtifactsReconciled": len(checked), "classOrderExact": True,
            "probabilitiesCoherent": True, "bothCalibrationArtifactsReloaded": True,
            "fourConfigurationsPresent": True, "simulationsPerConfiguration": 5000,
            "illegalStates": 0, "nontermination": 0,
            "archivedInitialProbabilityMismatches": 0,
            "unsupportedDurationFallback": {"C": "A", "D": "B", "verifiedFailClosed": True},
            "liveProspectivePostStartRejected": prospective_post_start_rejected,
            "historicalReplayAuthorityValidated": True,
            "branchHeadMatch": True,
        },
        # This records the pre-update state without creating a live reference to
        # a mutable manifest path.  A live path+digest reference would become
        # stale as soon as this verifier appends its own receipt.
        "manifestBeforeVerification": {
            "sha256": manifest_before["sha256"],
            "bytes": manifest_before["bytes"],
        },
        "scope": "One focused integration check; no fit, simulation, provider call, outcome read, AISP write, or policy change",
    }
    receipt_path = OUT / "integration-verification.json"
    write_json(receipt_path, receipt)
    receipt_ref = ref(receipt_path)
    manifest["integrationVerification"] = receipt_ref
    manifest["verification"].update({"unsupportedDurationFallbackVerified": True,
                                     "liveProspectivePostStartRejected": True,
                                     "referencesReconciled": len(checked)})
    manifest["artifacts"] = [item for item in manifest["artifacts"] if Path(item["path"]).name != receipt_path.name]
    manifest["artifacts"].append(receipt_ref)
    write_json(manifest_path, manifest)
    current["manifest"] = ref(manifest_path)
    current["verification"] = receipt_ref
    write_json(current_path, current)
    print(json.dumps({"status": "VERIFIED", "candidateId": package["candidateId"],
                      "referencesReconciled": len(checked), "receipt": receipt_ref}, indent=2))


if __name__ == "__main__":
    main()

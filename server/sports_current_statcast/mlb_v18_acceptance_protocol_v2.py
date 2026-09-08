"""Immutable successor to the MLB V18 prospective acceptance protocol V1.

V2 corrects statistical labels, gates formal inference on temporal support, and
keeps the proposed noninferiority margin from authorizing advancement.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast import mlb_v18_acceptance_protocol as v1


SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_ACCEPTANCE_INPUT_V2"
OUTPUT_SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_ACCEPTANCE_RESULT_V2"
CONTRACT_SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_ACCEPTANCE_PROTOCOL_V2"
PREDECESSOR_SHA256 = "1d72242432e045a7f921e115c8a7ad00ed11c80a8b8503f512ebaec67a087aaf"
FORMAL_LOOKS = {1: 250, 2: 500}
FORMAL_ALPHA_PER_LOOK = 0.025
MINIMUM_TEMPORAL_BLOCKS = 8

PROTOCOL: dict[str, Any] = deepcopy(v1.PROTOCOL)
PROTOCOL.update({
    "schemaVersion": CONTRACT_SCHEMA_VERSION,
    "verdict": "V18_PROSPECTIVE_ACCEPTANCE_PROTOCOL_V2_PREDECLARED_AND_EXECUTABLE",
    "predecessor": {
        "schemaVersion": v1.CONTRACT_SCHEMA_VERSION,
        "protocolSha256": PREDECESSOR_SHA256,
        "relationship": "IMMUTABLE_SUCCESSOR_NO_PREDECESSOR_MUTATION",
    },
})
PROTOCOL["planningBasis"].pop("detectableTwoSided95AbsoluteDifference", None)
PROTOCOL["planningBasis"].update({
    "evidenceStatus": "ASSUMPTION_NOT_EMPIRICALLY_ESTIMATED",
    "approximateTwoSided95CiHalfWidth": {
        "20": 0.0686, "50": 0.0434, "100": 0.0307, "250": 0.0194, "500": 0.0137,
    },
    "definition": "1.96 times the assumed standard error; not a powered minimum detectable effect",
})
PROTOCOL["noninferiorityMargin"] = {
    "valueLogLoss": 0.020,
    "disposition": "PROPOSED_NOT_APPROVED",
    "automaticAdvancementEnabled": False,
    "intendedUse": "A practical prospective tolerance for paired home-win log loss, if separately approved before outcomes are used for that decision.",
    "developmentEvidence": [
        {
            "estimand": "V18_MINUS_V14_MATCHED_PA_MULTICLASS_LOG_LOSS",
            "estimate": 0.00003123643363910823,
            "confidenceInterval95": [-0.00021197314611217394, 0.0002814535219026799],
            "limitation": "PA-level multiclass endpoint; not the prospective whole-game home-win endpoint.",
        },
        {
            "estimand": "E10_MINUS_DIRECT_GOLD_HOLDOUT_HOME_WIN_LOG_LOSS",
            "estimate": -0.008507298304209529,
            "confidenceInterval95": [-0.02507892029935546, 0.007551198071710137],
            "limitation": "Different game engines and evidence population; does not approve a V18-versus-Gen1 margin.",
        },
    ],
    "justification": "Existing Development evidence supports continued monitoring but does not scientifically approve a +0.020 whole-game loss tolerance.",
}
PROTOCOL["formalInference"] = {
    "method": "DETERMINISTIC_CHRONOLOGICAL_ISO_WEEK_BLOCK_BOOTSTRAP",
    "minimumIndependentTemporalBlocks": MINIMUM_TEMPORAL_BLOCKS,
    "formalLooks": [
        {"lookNumber": 1, "pairedGames": 250, "alpha": FORMAL_ALPHA_PER_LOOK, "confidenceLevel": 0.975},
        {"lookNumber": 2, "pairedGames": 500, "alpha": FORMAL_ALPHA_PER_LOOK, "confidenceLevel": 0.975},
    ],
    "familywiseRule": "Bonferroni fixed allocation: alpha 0.025 at each of two formal looks; total alpha no greater than 0.05.",
    "cohortRule": "Each formal look uses the first 250 or 500 chronologically eligible paired games, respectively.",
    "invocationRule": "A formalLook declaration must be immutable and identify look 1 or 2; reports without it are descriptive only.",
    "regressionRule": "Formal material-regression claims use the same allocated interval and temporal-block minimum.",
    "operationalIndependence": "Operational failures may trigger immediate action without statistical performance inference.",
}
PROTOCOL["repeatedLooks"] = {
    "daily": "DESCRIPTIVE_ONLY_NO_FORMAL_INFERENCE",
    "earlyCheckpoints": "20, 50, and 100 are descriptive; operational failures remain actionable.",
    "formal": "Only immutable LOOK_250 and LOOK_500 declarations invoke formal inference.",
    "alphaAllocation": "0.025 at each formal look, yielding a two-sided 97.5% interval at each look.",
}
PROTOCOL["betReadinessResearchStages"] = {
    "A": "EXPLORATORY_READINESS_AND_DECISION_POLICY_DESCRIPTION_NO_THRESHOLD_OPTIMIZATION",
    "B": "POLICY_SELECTION_REQUIRES_SEPARATE_PREDECLARED_AUTHORITY",
    "C": "INDEPENDENT_POLICY_EVALUATION_ON_UNTOUCHED_COHORT",
    "D": "AUTHORITY_TO_AFFECT_VIRTUAL_POSITIONS_REQUIRES_SEPARATE_EXPLICIT_APPROVAL",
}


class AcceptanceProtocolV2Error(ValueError):
    pass


def protocol_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(PROTOCOL)).hexdigest()


def _time(value: Any):
    return v1._time(value)


def validate_input(payload: Mapping[str, Any]) -> None:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise AcceptanceProtocolV2Error("schemaVersion must identify the V2 input contract")
    if payload.get("protocolSha256") != protocol_sha256():
        raise AcceptanceProtocolV2Error("protocolSha256 does not match the immutable V2 contract")
    if not isinstance(payload.get("records"), list):
        raise AcceptanceProtocolV2Error("records must be a list")
    look = payload.get("formalLook")
    if look is None:
        return
    if not isinstance(look, Mapping) or look.get("immutable") is not True or not look.get("lookId"):
        raise AcceptanceProtocolV2Error("formalLook must have an immutable identity")
    number = look.get("lookNumber")
    if number not in FORMAL_LOOKS or look.get("checkpointPairedGames") != FORMAL_LOOKS[number]:
        raise AcceptanceProtocolV2Error("formalLook must exactly identify predeclared look 1/250 or 2/500")


def _v1_payload(payload: Mapping[str, Any], records: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    result = dict(payload)
    result["schemaVersion"] = v1.SCHEMA_VERSION
    result["protocolSha256"] = v1.protocol_sha256()
    result["records"] = list(payload["records"] if records is None else records)
    result.pop("formalLook", None)
    return result


def _paired_records(payload: Mapping[str, Any], base: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    included = {row["recordSha256"] for row in base["exclusions"] if row["pairedIncluded"]}
    rows = [row for row in payload["records"] if v1._digest(row) in included]
    return sorted(rows, key=lambda row: (_time(row["scheduledStart"]), str(row["gameId"])))


def adjusted_block_interval(values: Sequence[float], dates: Sequence[str], *, alpha: float = FORMAL_ALPHA_PER_LOOK,
                            resamples: int = 5000) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    groups: dict[str, list[int]] = defaultdict(list)
    for index, value in enumerate(dates):
        stamp = _time(value)
        year, week, _ = stamp.isocalendar()
        groups[f"{year}-W{week:02d}"].append(index)
    if not len(array):
        return {"status": "NOT_ESTIMABLE", "blocks": 0, "lower": None, "upper": None}
    blocks = [np.asarray(groups[key], dtype=int) for key in sorted(groups)]
    rng = np.random.default_rng(v1.BOOTSTRAP_SEED)
    samples = np.empty(resamples, dtype=float)
    for iteration in range(resamples):
        selected = rng.integers(0, len(blocks), size=len(blocks))
        indices = np.concatenate([blocks[number] for number in selected])
        samples[iteration] = float(array[indices].mean())
    return {
        "status": "ESTIMATED" if len(blocks) >= MINIMUM_TEMPORAL_BLOCKS else "INSUFFICIENT_TEMPORAL_BLOCKS",
        "method": "CHRONOLOGICAL_ISO_WEEK_BLOCK_BOOTSTRAP",
        "blocks": len(blocks), "minimumBlocks": MINIMUM_TEMPORAL_BLOCKS,
        "resamples": resamples, "seed": v1.BOOTSTRAP_SEED,
        "alpha": alpha, "confidenceLevel": 1.0-alpha,
        "mean": float(array.mean()),
        "lower": float(np.quantile(samples, alpha/2)),
        "upper": float(np.quantile(samples, 1-alpha/2)),
    }


def evaluate(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_input(payload)
    base = v1.evaluate(_v1_payload(payload))
    paired = _paired_records(payload, base)
    result = deepcopy(base)
    result["schemaVersion"] = OUTPUT_SCHEMA_VERSION
    result["protocolSha256"] = protocol_sha256()
    result["predecessorProtocolSha256"] = PREDECESSOR_SHA256
    result["statisticalDefinitions"] = {
        "planningValues": "APPROXIMATE_95_PERCENT_CI_HALF_WIDTHS_NOT_POWERED_MDES",
        "planningAssumptionsEmpiricallyEstimated": False,
        "noninferiorityMarginDisposition": "PROPOSED_NOT_APPROVED",
        "automaticNoninferiorityAdvancementEnabled": False,
    }
    look = payload.get("formalLook")
    formal: dict[str, Any] = {
        "status": "DESCRIPTIVE_ONLY_NO_FORMAL_LOOK",
        "look": look,
        "minimumTemporalBlocks": MINIMUM_TEMPORAL_BLOCKS,
        "decision": None,
    }
    state = base["evidenceState"]
    if state == "OPERATIONAL_FAILURE":
        formal.update({"status": "OPERATIONAL_FAILURE_IMMEDIATE", "decision": "OPERATIONAL_FAILURE"})
    elif not look:
        if len(paired) < 20:
            state = "NOT_STARTED" if not payload["records"] else "INSUFFICIENT_EVIDENCE"
        else:
            state = "CONTINUE_RESEARCH_SHADOW"
    else:
        checkpoint = FORMAL_LOOKS[int(look["lookNumber"])]
        if len(paired) < checkpoint:
            formal.update({"status": "INSUFFICIENT_PAIRED_GAMES", "pairedGamesRequired": checkpoint,
                           "pairedGamesAvailable": len(paired)})
            state = "CONTINUE_RESEARCH_SHADOW" if len(paired) >= 20 else "INSUFFICIENT_EVIDENCE"
        else:
            cohort = paired[:checkpoint]
            formal_base = v1.evaluate(_v1_payload(payload, cohort))
            y = np.asarray([int(row["settlement"]["homeRuns"] > row["settlement"]["awayRuns"]) for row in cohort])
            p18 = np.asarray([float(row["v18"]["homeWinProbability"]) for row in cohort])
            p1 = np.asarray([float(row["gen1"]["homeWinProbability"]) for row in cohort])
            delta = v1._loss(p18, y) - v1._loss(p1, y)
            interval = adjusted_block_interval(delta, [row["scheduledStart"] for row in cohort])
            formal.update({"status": interval["status"], "pairedGames": checkpoint,
                           "cohortLastGameId": cohort[-1]["gameId"], "primaryInterval": interval,
                           "calibrationFailure": formal_base["decision"]["calibrationFailure"]})
            if interval["status"] != "ESTIMATED":
                formal["decision"] = "FORMAL_INFERENCE_INSUFFICIENT"
                state = "CONTINUE_RESEARCH_SHADOW"
            elif formal_base["decision"]["calibrationFailure"]:
                formal["decision"] = "CALIBRATION_FAILURE"
                state = "MATERIAL_REGRESSION"
            elif interval["lower"] > 0.020:
                formal["decision"] = "MATERIAL_REGRESSION"
                state = "MATERIAL_REGRESSION"
            elif interval["upper"] < 0:
                formal["decision"] = "ADVANCE_AS_SUPERIOR"
                state = "ADVANCE_AS_SUPERIOR"
            elif interval["upper"] < 0.020:
                formal["decision"] = "NONINFERIORITY_BOUND_MET_MARGIN_NOT_APPROVED"
                state = "RETAIN_AS_DIVERSITY_CHALLENGER"
            else:
                formal["decision"] = "FORMAL_RESULT_UNRESOLVED"
                state = "RETAIN_AS_DIVERSITY_CHALLENGER"
    result["formalInference"] = formal
    result["scientificState"] = state
    result["evidenceState"] = state
    result["decision"]["comparativeClaimAllowed"] = formal["status"] == "ESTIMATED"
    result["decision"]["advancementAllowed"] = formal.get("decision") == "ADVANCE_AS_SUPERIOR"
    result["decision"]["automaticNoninferiorityAdvancementEnabled"] = False
    result["lineage"].update({"predecessorModified": False, "acceptedBundleModified": False})
    result.pop("resultSha256", None)
    result["resultSha256"] = v1._digest(result)
    return result


def human_report(result: Mapping[str, Any]) -> str:
    formal = result["formalInference"]
    lines = [
        "# MLB V18 prospective acceptance evaluation V2", "",
        f"- Evidence state: `{result['evidenceState']}`",
        f"- Paired settled games available: {result['metrics'].get('pairedGames', 0)}",
        f"- Formal-inference status: `{formal['status']}`",
        f"- Formal decision: `{formal.get('decision') or 'NONE'}`",
        "- Noninferiority margin: `PROPOSED_NOT_APPROVED`; automatic NI advancement disabled.",
        "- Planning figures: approximate assumption-based 95% CI half-widths, not powered MDEs.", "",
        "Final OOT remained sealed. No model was fitted. AISP was not modified.",
    ]
    return "\n".join(lines) + "\n"


def write_evaluation(payload: Mapping[str, Any], output_root: Path) -> Path:
    result = evaluate(payload)
    target = output_root / "sha256" / result["resultSha256"]
    target.mkdir(parents=True, exist_ok=True)
    (target / "result.json").write_bytes(canonical_json_bytes(result))
    (target / "report.md").write_text(human_report(result), encoding="utf-8")
    return target

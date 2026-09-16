"""Verify saved play-level publication only; never load or execute a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_nfl_m1.labs_simulation import file_record, immutable_json, utc, verify_object
from server.sports_nfl_m1.play_validation import distribution_summary, representative_indices


def verify(output: Path, *, idempotency_before: Path | None = None, check_rerun_inputs: bool = False) -> dict:
    pointer = json.loads((output / "CURRENT.json").read_bytes())
    handoff_ref = pointer["handoff"]
    assert file_record(Path(handoff_ref["path"])) == handoff_ref
    handoff = json.loads(Path(handoff_ref["path"]).read_bytes())
    assert handoff["eventCount"] == 16 and handoff["artifactCount"] == 112 and not handoff["skips"]
    declaration_ref = handoff["declaration"]
    assert file_record(Path(declaration_ref["path"])) == declaration_ref
    declaration = json.loads(Path(declaration_ref["path"]).read_bytes())
    for ref in declaration["implementation"].values():
        assert file_record(Path(ref["path"])) == ref, "declared generating implementation changed"
    contract_ref = handoff["contract"]
    assert file_record(Path(contract_ref["path"])) == contract_ref
    groups = defaultdict(list)
    events = defaultdict(set)
    play_types = Counter()
    parent_m1 = {}
    representative_plays = representative_count = population_count = impossible = 0
    for item in handoff["artifacts"]:
        record = verify_object(item)
        rebuilt = distribution_summary(record["populationFinals"])
        for key, value in rebuilt.items():
            assert value == record[key], f"population/distribution mismatch: {item['eventId']} {key}"
        chosen = representative_indices(record["populationFinals"])
        assert chosen == {game["label"]: game["simulationIndex"] for game in record["simulatedGames"]}
        assert len(set(chosen.values())) == 6
        assert (utc(record["sourceCutoffUtc"]) <= utc(record["inferenceStartedUtc"])
                <= utc(record["forecastCreatedUtc"]) <= utc(record["publishedAtUtc"])
                < utc(record["scheduledStartUtc"]))
        assert record["status"] == "RESEARCH_SHADOW" and record["promotionStatus"] == "NOT_PROMOTED"
        assert record["wageringAuthority"] is False and record["executionAllowedInAISP"] is False
        assert file_record(Path(record["sourceForecast"]["path"])) == record["sourceForecast"]
        scenario = record["scenario"]["scenarioId"]
        if scenario == "BASE":
            parent_m1[record["eventId"]] = record["sourceForecast"]["sha256"]
        groups[scenario].append({key: record[key] for key in ("scoreSummary", "scenarioDelta", "populationAccounting", "m1Comparison")})
        events[record["eventId"]].add(scenario)
        population_count += record["drawCount"]
        representative_count += len(record["simulatedGames"])
        representative_plays += sum(len(game["plays"]) for game in record["simulatedGames"])
        impossible += record["populationAccounting"]["impossibleStateCount"]
        play_types.update(record["populationAccounting"]["playTypeCounts"])
    expected = set(declaration["currentPublication"]["scenarioIds"])
    assert all(values == expected for values in events.values()) and set(groups) == expected
    assert population_count == 112000 and representative_count == 672 and impossible == 0
    if check_rerun_inputs:
        from scripts.publish_nfl_play_level import _source_forecasts
        exchange = Path(contract_ref["path"]).parent.parent
        assert {record["eventId"]: item["artifact"]["sha256"] for record, item in _source_forecasts(exchange)} == parent_m1, "M1 discovery changed; do not launch an unintended new population"
        source_manifest = Path(declaration["sourceRegistration"]["path"])
        bronze = source_manifest.parents[3]
        source_pointer = json.loads((bronze / "current.json").read_bytes())
        assert source_pointer["manifestSha256"] == declaration["sourceRegistration"]["sha256"], "source registration changed; rerun is not the same authority"
    idempotency = None
    if idempotency_before is not None:
        original_ref = file_record(idempotency_before)
        assert original_ref["sha256"] == idempotency_before.parent.name
        original = json.loads(idempotency_before.read_bytes())
        assert original["artifacts"] == handoff["artifacts"] and original["declaration"] == handoff["declaration"]
        assert handoff["actualPopulationGameSimulationStartsThisInvocation"] == 0
        assert handoff["actualRepresentativeReplayStartsThisInvocation"] == 0
        assert handoff["reusedImmutablePopulations"] == 112
        assert original["actualPopulationGameSimulationStartsThisInvocation"] == 112000
        assert original["actualRepresentativeReplayStartsThisInvocation"] == 672
        idempotency = {"originalHandoff": original_ref, "rerunHandoff": handoff_ref,
                       "identicalArtifactAndManifestReferences": 112, "newSimulationStarts": 0,
                       "newRepresentativeReplays": 0, "reusedPopulations": 112}
    means = lambda values: sum(values) / len(values)
    effects = {}
    for scenario, records in groups.items():
        effects[scenario] = {
            "events": len(records),
            "meanScoreSummary": {key: means([record["scoreSummary"][key] for record in records]) for key in records[0]["scoreSummary"]},
            "meanPairedScenarioDelta": {key: means([record["scenarioDelta"][key] for record in records]) for key in records[0]["scenarioDelta"]},
            "meanTurnoversPerGame": means([record["populationAccounting"]["turnoversPerGame"] for record in records]),
            "meanPlaysPerGame": means([record["populationAccounting"]["playsPerGame"]["mean"] for record in records]),
            "meanM1ScoreSummary": {key: means([record["m1Comparison"]["m1ScoreSummary"][key] for record in records]) for key in records[0]["m1Comparison"]["m1ScoreSummary"]},
            "meanPlayEngineMinusM1": {key: means([record["m1Comparison"]["playEngineMinusM1"][key] for record in records]) for key in records[0]["m1Comparison"]["playEngineMinusM1"]},
        }
    result = {"schemaVersion": "NFL_PLAY_LEVEL_PUBLICATION_VERIFICATION_V1", "handoff": handoff_ref,
              "contract": contract_ref, "events": len(events), "populations": 112,
              "populationGames": population_count, "completeRepresentatives": representative_count,
              "representativePlayEvents": representative_plays, "populationPlayTypeCounts": dict(play_types),
              "populationDistributionMismatch": 0, "impossibleStateCount": impossible,
              "allPregame": True, "parentM1ArtifactsUnchanged": True,
              "scenarioEffects": effects, "modelExecutedByVerifier": False,
              "rerunInputsVerifiedUnchanged": check_rerun_inputs, "idempotency": idempotency}
    digest = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    ref = immutable_json(output / "verification" / "sha256" / digest / "verification.json", result)
    return {"receipt": ref, "events": 16, "populations": 112, "populationGames": population_count,
            "completeRepresentatives": representative_count, "representativePlayEvents": representative_plays,
            "populationDistributionMismatch": 0, "impossibleStateCount": impossible}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "outputs/nfl-play-level-engine-v1")
    parser.add_argument("--idempotency-before", type=Path)
    parser.add_argument("--check-rerun-inputs", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.output_root, idempotency_before=args.idempotency_before, check_rerun_inputs=args.check_rerun_inputs), indent=2))

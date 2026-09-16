"""Execute supported frozen survival pairs for the separately declared slate.

Uses the verified three-arm mechanics and candidate packager with a separate
output/exchange namespace. Missing history is a pending prerequisite, never a
new fallback forecast counted as a survival execution. No network or outcomes.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from threadpoolctl import threadpool_limits
import run_mlb_v18_three_arm_pregame_v1 as frozen
from server.sports_current_statcast.mlb_starter_duration_current_inputs import build_current_duration_inputs
from server.sports_current_statcast.mlb_v18_unattended import atomic_state, single_owner

STUDY = "mlb-v18-survival-starter-coverage-v1"
OUT = ROOT / "outputs" / STUDY
COMPARISONS = OUT / "comparisons"
DECLARATION = OUT / "declaration.json"
PRE_AMENDMENT_INPUT_SHA = "b9d9e24b62e17e8f640f785d25441cf9c254c987be16f553c919e6e788531c6f"
AMENDED_INPUT_SHA = "3d03ac3693c4a8f91e8d127a4e315dcd9b4b5025930406e943ffec349e1f5dd9"
PRE_AMENDMENT_DRIVER_SHA = "aef32b4225cf4a407fe03476df9c4b17d8ba6ad95399e987ae0df1ff77c2e8ea"
SIX_SOURCE_AMENDMENT_SHA = "85adccfc8e257bd8cf28ab86e485c67693f665a5e2ab726da776134958d8212f"


def coverage():
    descriptor = frozen.ref(DECLARATION)
    value = frozen.read(descriptor)
    if (value["schemaVersion"] != "MLB_V18_SURVIVAL_STARTER_COVERAGE_DECLARATION_V1"
            or value["outcomeAccess"] is not False or value["candidateAuthority"] is not False
            or value["comparison"]["simulationsPerArm"] != 5000
            or value["comparison"]["masterSeed"] != frozen.daily.MASTER_SEED):
        raise ValueError("FROZEN_COVERAGE_DECLARATION_REQUIRED")
    for row in value["games"]:
        if not all(frozen.final_oot_eligible_key_mask([row["gameId"], row["sourceGameId"]])):
            raise ValueError("QUARANTINED_DECLARED_GAME")
    return descriptor, value


def history_pointer(declaration_ref):
    # Separate pointer; the original pilot/current history pointer is untouched.
    return (ROOT / "outputs/mlb-starter-duration-paired-research-v1/starter-history/cohorts"
            / declaration_ref["sha256"] / "current.json")


def source_guard_successor(previous, current_shared, current_driver):
    """Allow only this exact input-authorization change, before any attempt."""
    from server.sports_current_statcast.mlb_starter_duration_quarantine import (
        SIX_AUTHORITY_POINTER, load_exception_authority)
    old_shared = previous["sharedExecutionCode"]
    input_path = str(ROOT / "server/sports_current_statcast/mlb_starter_duration_current_inputs.py")
    if (len(old_shared) != len(current_shared)
            or [r["path"] for r in old_shared] != [r["path"] for r in current_shared]):
        raise ValueError("COVERAGE_SHARED_CODE_SCOPE_CHANGED")
    changes = [(old, new) for old, new in zip(old_shared, current_shared) if old != new]
    if (len(changes) != 1 or changes[0][0]["path"] != input_path
            or changes[0][0]["sha256"] != PRE_AMENDMENT_INPUT_SHA
            or changes[0][1]["sha256"] != AMENDED_INPUT_SHA
            or previous["coverageDriver"]["sha256"] != PRE_AMENDMENT_DRIVER_SHA
            or previous["coverageDriver"]["path"] != current_driver["path"]):
        raise ValueError("ONLY_EXACT_SIX_SOURCE_INPUT_GUARD_SUCCESSOR_ALLOWED")
    authority_ref = json.loads(SIX_AUTHORITY_POINTER.read_bytes())
    if authority_ref.get("sha256") != SIX_SOURCE_AMENDMENT_SHA:
        raise ValueError("EXACT_SIX_SOURCE_AMENDMENT_REQUIRED_FOR_PROTOCOL_SUCCESSOR")
    return load_exception_authority(authority_ref)["authorityRef"]


def protocol():
    cover_ref, cover = coverage()
    pointer = COMPARISONS / "declaration-current.json"
    predecessor = None
    previous = None
    source_amendment = None
    current_shared = [frozen.ref(ROOT / p) for p in frozen.SHARED_CODE]
    current_driver = frozen.ref(__file__)
    if pointer.exists():
        descriptor = json.loads(pointer.read_text())
        value = frozen.read(descriptor)
        if (value["coverageDeclaration"] != cover_ref
                or value["driver"] != frozen.ref(frozen.__file__)):
            raise ValueError("COVERAGE_EXECUTION_CONFIGURATION_CHANGED")
        for item in value["components"].values():
            frozen.read(item) if Path(item["path"]).suffix == ".json" else frozen.ref(item["path"])
            if frozen.ref(item["path"]) != item:
                raise ValueError("FROZEN_COMPONENT_CHANGED")
        if value["coverageDriver"] == current_driver and value["sharedExecutionCode"] == current_shared:
            return descriptor, value
        if any(COMPARISONS.glob("cohorts/*/attempts/*.json")):
            raise ValueError("CANNOT_REVISE_CONFIGURATION_AFTER_NUMERICAL_ATTEMPT")
        source_amendment = source_guard_successor(value, current_shared, current_driver)
        predecessor = descriptor
        previous = value
    # Selection already happened before outcome access. No new members here.
    value = {
        "schemaVersion": frozen.SCHEMA + "_DECLARATION",
        "declaredAtUtc": cover["declaredAtUtc"], "slateDate": cover["slateDate"],
        "games": sorted(cover["games"], key=lambda g: (frozen.utc(g["deadlineUtc"]), g["gameId"])),
        "stopAfterUtc": cover["stopAfterUtc"],
        "coverageDeclaration": cover_ref, "coverageDriver": frozen.ref(__file__),
        "priorUnexecutedProtocol": predecessor,
        "configurationRecordedAtUtc": frozen.now().isoformat(),
        "sourceAmendment": source_amendment,
        "scheduleEvidence": cover["identityEvidence"], "excludedAtDeclaration": [],
        "arms": list(frozen.ARMS), "simulationCountPerArm": 5000,
        "masterSeed": frozen.daily.MASTER_SEED, "paModelSha256": frozen.daily.PA_MODEL_SHA256,
        "treatmentManifestSha256": frozen.daily.TREATMENT_MANIFEST_SHA256,
        "baselineTransitionSha256": frozen.daily.TRANSITION_MODEL_SHA256,
        "baselineParentBundleSha256": frozen.daily.PARENT_BUNDLE_SHA256,
        "sharedExecutionCode": current_shared,
        "components": {frozen.ARMS[1]: frozen.ref(frozen.SURVIVAL_PATH),
                       frozen.ARMS[2]: frozen.ref(frozen.TRANSITION_PATH)},
        "transitionProtocol": frozen.ref(ROOT / "outputs/mlb-v18-transition-shrinkage-v1/protocol.json"),
        "transitionConfiguration": {"priorStrength": 20.0, "legalFloor": 1e-6, "trainingSeasons": [2023, 2024, 2025]},
        "driver": frozen.ref(frozen.__file__), "outcomeAccess": False,
        "historicalTrainingChronologyCertified": False,
        "baselineRule": "Reuse exact original ordinary baseline and all original input clocks; no baseline substitution after a numerical attempt.",
        "historyCutoffRule": "Separate certified cohort registry must have been available by original baseline snapshot capture.",
        "stoppingRule": "Fixed September13 membership and original deadlines. At most one numerical attempt per game. No scheduler or implicit follow-up.",
        "fallbackRule": "Missing evidence stays pending without numerical execution or publication. An execution failure retains the exact baseline but is never a supported survival trial.",
        **frozen.FLAGS,
    }
    if value["components"][frozen.ARMS[1]]["sha256"] != frozen.SURVIVAL_SHA or value["components"][frozen.ARMS[2]]["sha256"] != frozen.TRANSITION_SHA:
        raise ValueError("FROZEN_COMPONENT_IDENTITY_CHANGED")
    if previous is not None:
        mutable = {"sharedExecutionCode", "coverageDriver", "priorUnexecutedProtocol",
                   "configurationRecordedAtUtc", "sourceAmendment"}
        if ({k: v for k, v in previous.items() if k not in mutable}
                != {k: v for k, v in value.items() if k not in mutable}):
            raise ValueError("SOURCE_AMENDMENT_CANNOT_CHANGE_COHORT_OR_COMPARISON")
    descriptor = frozen.put("declaration.json", value, COMPARISONS)
    atomic_state(pointer, descriptor)
    return descriptor, value


def supported_inputs(bundle, cover_ref):
    pointer = history_pointer(cover_ref)
    try:
        if pointer.exists():
            descriptor = json.loads(pointer.read_text())
            digest = str(descriptor["sha256"])
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("COHORT_HISTORY_CONTENT_ADDRESS_INVALID")
            history_root = ROOT / "outputs/mlb-starter-duration-paired-research-v1/starter-history"
            expected = history_root / "objects/sha256" / digest / "manifest.json"
            if Path(descriptor["path"]).resolve() != expected.resolve():
                raise ValueError("COHORT_HISTORY_MANIFEST_OUTSIDE_REGISTERED_NAMESPACE")
            manifest = frozen.read(descriptor)
            # Check materialization before the existing reader opens any rows.
            if frozen.utc(manifest["createdAt"]) > frozen.utc(bundle["snapshot"]["capturedAt"]):
                raise ValueError("HISTORY_MATERIALIZED_AFTER_ORIGINAL_BASELINE_CUTOFF")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "UNSUPPORTED", "missingReasons": [f"{type(exc).__name__}: {exc}"],
                "historyPointer": str(pointer), "rowPayloadRead": False}
    return build_current_duration_inputs(bundle["snapshot"],
        as_of_utc=bundle["snapshot"]["capturedAt"], history_pointer=pointer)


def plan():
    descriptor, declared = protocol()
    status = frozen.plan(descriptor, declared, COMPARISONS)
    for row in status["records"]:
        if row["status"] != "BASELINE_OBJECT_AVAILABLE":
            continue
        bundle = frozen.load_baseline(row["baselineObjectSha256"])
        frozen.verify_member(bundle, row, declared, frozen.now())
        registered = supported_inputs(bundle, declared["coverageDeclaration"])
        row["historyStatus"] = registered["status"]
        row["historyMissingReasons"] = registered.get("missingReasons", [])
        if registered["status"] != "SUPPORTED":
            row["status"] = "PENDING_CERTIFIED_HISTORY_BEFORE_ORIGINAL_BASELINE_CUTOFF"
    status["counts"]["readySupportedSurvival"] = sum(r["status"] == "BASELINE_OBJECT_AVAILABLE" for r in status["records"])
    status["historyPointer"] = str(history_pointer(declared["coverageDeclaration"]))
    status["coverageDriver"] = frozen.ref(__file__)
    return descriptor, declared, status


def execute(bundle, row, declared, duration, deadline):
    from server.sports_current_statcast.mlb_starter_duration_paired_publication import load_duration_model
    from server.sports_current_statcast.mlb_starter_duration_paired_simulation import (
        _duration_lookup, simulate_research_arm, REFERENCE, CHALLENGER, verify_frozen_mechanics)
    from server.sports_current_statcast.mlb_v18_current_publication import CurrentV18Engine
    from server.sports_phase5.hierarchical_transition import HierarchicalTransitionModel

    if duration["status"] != "SUPPORTED":
        raise ValueError("GENUINELY_SUPPORTED_HISTORY_REQUIRED_BEFORE_EXECUTION")
    base = bundle["baseline"]
    populations = {arm: base for arm in frozen.ARMS}
    arms = {frozen.ARMS[0]: {"status": "BASELINE_REUSED", "actualConfiguration": frozen.ARMS[0],
                            "componentTrial": False, "summary": frozen.compact(base)}}
    engine = CurrentV18Engine()
    provider, reload = frozen.shared_provider(engine, bundle)
    metadata = {"frozenMechanics": verify_frozen_mechanics(), "paReload": reload,
                "durationInputs": duration, "coverageDriver": frozen.ref(__file__)}
    kwargs = {"game_id": row["gameId"], "provider": provider, "n_sims": 5000,
              "master_seed": frozen.daily.MASTER_SEED,
              "regulation": int(bundle["snapshot"]["game"].get("scheduled_innings") or 9),
              "trace_count": 0, "deadline_utc": deadline}
    for arm in frozen.ARMS[1:]:
        try:
            if frozen.now() >= deadline:
                raise ValueError("ORIGINAL_EXECUTION_DEADLINE_CLOSED")
            if arm == frozen.ARMS[1]:
                model, identity = load_duration_model()
                lookup, inference = _duration_lookup(model, duration["home"], duration["away"])
                population = simulate_research_arm(**kwargs, transition_model=engine.transition,
                    arm=CHALLENGER, duration_lookup=lookup)
                detail = {"durationInference": inference, "durationModelIdentity": identity}
            else:
                component = HierarchicalTransitionModel.from_dict(frozen.read(declared["components"][arm]))
                if (component.prior_strength, component.legal_floor, component.seasons) != (20.0, 1e-6, (2023, 2024, 2025)):
                    raise ValueError("FROZEN_TRANSITION_SETTINGS_CHANGED")
                population = simulate_research_arm(**kwargs, transition_model=component, arm=REFERENCE)
                detail = {}
            if len(population["homeRuns"]) != 5000 or population["illegalStateCount"] or population["nonterminationCount"]:
                raise ValueError("INVALID_COMPONENT_POPULATION")
            populations[arm] = population
            arms[arm] = frozen.applied(population, {"configuration": arm, "component": declared["components"][arm], **detail})
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            arms[arm] = frozen.fallback(base, f"{type(exc).__name__}: {exc}")
    return populations, arms, metadata


def run(max_games, wall_seconds):
    if not 1 <= max_games <= 15 or not 30 <= wall_seconds <= 1200:
        raise ValueError("BOUNDED_EXECUTION_LIMIT_REQUIRED")
    descriptor, declared, status = plan()
    results = []
    wall_deadline = frozen.now() + timedelta(seconds=wall_seconds)
    with single_owner(frozen.PRODUCER_LOCK) as owned:
        if not owned:
            return {"status": "DEFERRED_ORDINARY_PUBLISHER_LOCK_BUSY", "newSimulations": 0}
        for row in status["records"]:
            if len(results) >= max_games or frozen.now() >= wall_deadline:
                break
            if row["status"] != "BASELINE_OBJECT_AVAILABLE":
                continue
            bundle = frozen.load_baseline(row["baselineObjectSha256"])
            frozen.verify_member(bundle, row, declared, frozen.now())
            duration = supported_inputs(bundle, declared["coverageDeclaration"])
            if duration["status"] != "SUPPORTED":
                continue
            begun = frozen.now()
            attempt = frozen.state_root(COMPARISONS, descriptor) / "attempts" / (row["gameId"] + ".json")
            attempt.parent.mkdir(parents=True, exist_ok=True)
            with attempt.open("x", encoding="utf-8") as stream:
                json.dump({"startedAtUtc": begun.isoformat(), "declaration": descriptor,
                           "baselineObjectSha256": bundle["objectSha256"], "historyInputs": duration,
                           "coverageDriver": frozen.ref(__file__), "numericalAttemptLimit": 1}, stream)
            try:
                with threadpool_limits(limits=4):
                    populations, arms, metadata = execute(bundle, row, declared, duration,
                        min(wall_deadline, frozen.utc(row["deadlineUtc"])))
                retained = frozen.retain(bundle, row, descriptor, declared, populations, arms, metadata, begun, COMPARISONS)
                results.append(retained)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                results.append(frozen.put("blocked-attempt.json", {"gameId": row["gameId"],
                    "blockedAtUtc": frozen.now().isoformat(), "reason": f"{type(exc).__name__}: {exc}",
                    "prospectiveForecastFrozen": False, **frozen.FLAGS}, COMPARISONS))
    _, _, final = plan()
    final["thisRunResults"] = results
    item = frozen.put("status.json", final, COMPARISONS)
    atomic_state(COMPARISONS / "current.json", item)
    return {"status": item, "counts": final["counts"]}


def package(export):
    import package_mlb_v18_three_arm_pregame_comparison_v1 as packager
    protocol()
    status_ref = json.loads((COMPARISONS / "current.json").read_text())
    value = frozen.read(status_ref)
    if not value["counts"]["survivalSupported"]:
        return {"status": "NO_SUPPORTED_SURVIVAL_RUN_NO_CANDIDATE_PACKAGE", "published": 0}
    for row in value["records"]:
        if "result" in row and row["arms"][frozen.ARMS[1]]["status"] != "APPLIED":
            row["unpublishedExecutionResult"] = row.pop("result")
            row["status"] = "SURVIVAL_NOT_APPLIED_EXCLUDED_FROM_CANDIDATE_PACKAGE"
    selected = frozen.put("supported-publication-status.json", value, COMPARISONS)
    source_dependencies = ROOT / "outputs/mlb-v18-three-arm-pregame-comparison-v1/dependency-identities.json"
    dependencies = json.loads(source_dependencies.read_text())
    paths = {row["path"] for row in dependencies["codeAndGovernance"]}
    paths.update((str(Path(__file__).resolve()),
                  str(ROOT / "server/sports_current_statcast/mlb_starter_duration_history.py")))
    dependencies = {"schemaVersion": "MLB_SURVIVAL_COVERAGE_CODE_BINDINGS_V1",
                    "codeAndGovernance": [frozen.ref(p) for p in sorted(paths)]}
    atomic_state(COMPARISONS / "dependency-identities.json", dependencies)
    # The existing contract implementation owns validation and publication.
    # Only its isolated study paths are configured; no contract/mechanics edits.
    packager.STUDY = STUDY
    packager.OUTPUT = COMPARISONS
    packager.EXCHANGE = Path(r"C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1") / "survival-starter-coverage-v1"
    # The legacy CLI owns this lock; calling its library requires the same lock.
    with single_owner(packager.LOCK) as owned:
        if not owned:
            return {"status": "DEFERRED_EXISTING_RESEARCH_PUBLICATION_OWNER", "published": 0}
        return packager.build(Path(selected["path"]), export=export)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "package"))
    parser.add_argument("--max-games", type=int, default=1)
    parser.add_argument("--wall-seconds", type=int, default=1200)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    result = plan()[2] if args.command == "plan" else (run(args.max_games, args.wall_seconds)
             if args.command == "run" else package(args.export))
    print(json.dumps(frozen.daily.json_safe(result), indent=2, allow_nan=False))

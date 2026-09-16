"""Package frozen three-arm draws for the existing AISP candidate importer.

No inference, fitting, source collection, outcomes or AISP writes. Export is an
explicit option, confined to this study inside the existing research exchange.
Survival uses consumer V1; transition uses the proposed V2 role extension.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_unattended import single_owner

STUDY = "mlb-v18-three-arm-pregame-comparison-v1"
OUTPUT = ROOT / "outputs" / STUDY
DAILY = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/objects/sha256"
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1") / "three-arm-pregame-comparison-v1"
LOCK = ROOT / "outputs/mlb-starter-duration-paired-research-v1/research.lock"
AUTHORITY = ROOT / "outputs/mlb-v18-conditional-champion-v1/aisp-handoff/sha256/a3d6ea3fdb9ddecc42e7b5ecac975d0d132931c0ca7bfc0938bdcef205f2d300/champion-handoff.json"
PA_SHA = "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b"
SURVIVAL_SHA = "f64f82b4fadf35acd3418bc298548c48bb73cf624fe8c70ba01a87c33e8d2370"
TRANSITION_SHA = "8c91d687c95ff81ad11efa7a5e718aa5bbfeb0aa97cc05795bd26e3954939640"
ARMS = {"V18_SURVIVAL_ONLY": ("DURATION", "HGB_PREGAME", SURVIVAL_SHA, "V1"),
        "V18_TRANSITION_ONLY": ("TRANSITION", "MLB_BASE_OUT_TRANSITION_HIERARCHICAL_SHRINKAGE_V1", TRANSITION_SHA, "V2")}
FLAGS = {"researchShadowOnly": True, "executionAllowed": False, "executionAllowedInAISP": False,
         "wageringAuthority": False, "activatesModel": False, "candidateAuthority": False,
         "modelActivationAllowed": False, "promotionStatus": "NOT_PROMOTED"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verified(item):
    path = Path(item["path"]).resolve(strict=True)
    actual = reference(path)
    if actual["sha256"] != item["sha256"] or actual["bytes"] != item["bytes"]:
        raise ValueError("ARTIFACT_REFERENCE_MISMATCH:" + str(path))
    return path


def immutable(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("IMMUTABLE_COLLISION:" + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return reference(path)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
        stream.write(canonical(value))
        temporary = Path(stream.name)
    os.replace(temporary, path)


def utc(value):
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    return moment.astimezone(timezone.utc)


def distribution(values):
    return {str(int(value)): int(n) / len(values) for value, n in sorted(Counter(values.tolist()).items())}


def summary(home, away):
    return {"homeWinProbability": float((home > away).mean()), "meanHomeRuns": float(home.mean()),
            "meanAwayRuns": float(away.mean()), "meanTotalRuns": float((home + away).mean()),
            "meanRunDifferential": float((home - away).mean())}


def baseline_authority(forecast):
    if reference(AUTHORITY)["sha256"] != AUTHORITY.parent.name:
        raise ValueError("BASELINE_AUTHORITY_HASH_MISMATCH")
    authority = read(AUTHORITY)
    identity, parent = authority["modelIdentity"], forecast["parentAuthority"]
    if (identity["artifactSha256"] != PA_SHA or parent["paModelSha256"] != PA_SHA
            or identity["parentLogicalBundleSha256"] != parent["bundleSha256"]
            or identity["parentBundleId"] != parent["bundleId"]):
        raise ValueError("FROZEN_BASELINE_IDENTITY_MISMATCH")
    binding = {"engineId": "MLB_V18_WHOLE_GAME", "engineVersion": parent["bundleId"],
               "modelArtifactSha256": PA_SHA, "parentBundleId": identity["parentBundleId"],
               "trainingRunId": identity["trainingRunId"]}
    refs = {"authority-handoff.json": reference(AUTHORITY)}
    for key in ("championManifest", "frozenBindings", "developmentIntegrity", "registrationReceipt"):
        verified(authority[key])
        binding[key + "Sha256"] = authority[key]["sha256"]
        refs[key + ".json"] = authority[key]
    return binding, refs


def baseline_files(object_sha):
    directory = DAILY / object_sha
    manifest = read(directory / "manifest.json")
    if manifest["objectSha256"] != object_sha:
        raise ValueError("BASELINE_OBJECT_IDENTITY_MISMATCH")
    files = {}
    for name in ("forecast.json", "execution-inputs.json"):
        descriptor = next(row for row in manifest["artifacts"] if row["relativePath"] == name)
        item = {"path": str(directory / name), "sha256": descriptor["sha256"], "bytes": descriptor["bytes"]}
        files[name] = verified(item)
    return read(files["forecast.json"]), read(files["execution-inputs.json"]), files


def candidate_object(package_root, game, arm, config_sha, declaration_ref):
    """One already-frozen arm, preserving the original baseline and child clocks."""
    receipt, receipt_ref = game["receipt"], game["receiptRef"]
    baseline, execution, source_files = game["baseline"], game["execution"], game["sourceFiles"]
    role, component_id, component_sha, _ = ARMS[arm]
    applied = receipt["arms"][arm]["applied"]
    reason = receipt["arms"][arm].get("fallbackReason")
    if not isinstance(applied, bool) or (not applied and not reason):
        raise ValueError("EXPLICIT_COMPONENT_APPLIED_OR_FALLBACK_REQUIRED")
    home, away = game["arrays"][arm + "_homeRuns"], game["arrays"][arm + "_awayRuns"]
    values = summary(home, away)
    parent = baseline["parentAuthority"]
    forecast_id = "mlb-v18-" + ("survival-" if role == "DURATION" else "transition-") + receipt_ref["sha256"]
    forecast = {"schemaVersion": "MLB_ENSEMBLE_CANDIDATE_GAME_FORECAST_V1", "artifactType": "PROSPECTIVE",
        "forecastId": forecast_id, "baselineForecastId": "mlb-v18-daily-" + receipt["sourceForecastObjectSha256"],
        "canonicalGameId": baseline["gameId"], "eventId": baseline["gameId"], "sourceGameId": baseline["sourceGameId"],
        "season": utc(baseline["scheduledStart"]).year, "configurationId": arm,
        "actualConfiguration": arm if applied else "V18_BASE",
        "homeTeam": baseline["teams"]["HOME"]["uuid"], "awayTeam": baseline["teams"]["AWAY"]["uuid"],
        "capturedAt": baseline["capturedAt"], "publishedAt": receipt["pairFrozenAtUtc"],
        "scheduledStart": baseline["scheduledStart"], "policyCutoffUtc": receipt["policyCutoffUtc"],
        "publicationClockMeaning": "ORIGINAL_IMMUTABLE_PREGAME_THREE_ARM_FREEZE_NOT_PACKAGING_TIME",
        "sourceCutoff": baseline["sourceCutoff"], "featureVectorSha256": baseline["snapshotContentSha256"],
        "baselineBinding": {"parentBundleSha256": parent["bundleSha256"],
            "acceptanceProtocolSha256": parent["acceptanceProtocolV2Sha256"],
            "numericalArtifactSha256": receipt["sourceForecastObjectSha256"],
            "featureVectorSha256": baseline["snapshotContentSha256"], "simulatorId": "V18_WHOLE_GAME_MONTE_CARLO",
            "simulatorVersion": baseline["schemaVersion"], "simulatorSeed": baseline["simulation"]["seed"],
            "simulationCount": 5000, "sourceCutoffUtc": baseline["capturedAt"]},
        "probabilities": {"homeWin": values["homeWinProbability"], "awayWin": 1 - values["homeWinProbability"]},
        "expectations": {"homeRuns": values["meanHomeRuns"], "awayRuns": values["meanAwayRuns"],
                         "totalRuns": values["meanTotalRuns"], "homeMinusAwayRuns": values["meanRunDifferential"]},
        "distributions": {"homeRunDistribution": distribution(home), "awayRunDistribution": distribution(away),
                          "totalRunDistribution": distribution(home + away), "runDifferentialDistribution": distribution(home - away)},
        "simulation": {"simulatorId": "V18_WHOLE_GAME_MONTE_CARLO",
            "simulatorVersion": STUDY + ":" + role.lower() if applied else baseline["schemaVersion"],
            "seed": 20260907, "count": 5000, "simulationCount": 5000,
            "fallbackToOriginalDraws": not applied,
            "pairedPopulationFile": "paired-populations.npz", "pairedPopulationSha256": receipt["population"]["sha256"],
            "populationKeys": {"home": arm + "_homeRuns", "away": arm + "_awayRuns"},
            "baselinePopulationKeys": {"home": "V18_BASE_homeRuns", "away": "V18_BASE_awayRuns"},
            "seedPolicy": "SeedSequence([masterSeed,first8BytesBigEndianSHA256(canonicalGameId)]).spawn(3):PA,transition,hook",
            "predictiveImprovementEstablished": False},
        "componentsApplied": [{"componentId": "MLB_V18_HGB_PA", "role": "BASE", "ran": True},
            {"componentId": component_id, "role": role, "ran": applied,
             **({"fallbackReason": reason} if not applied else {})}],
        "eligibility": {"eligible": True, "status": "PREGAME_RESEARCH_SHADOW", "outcomesRead": False,
                        "componentTrialSupported": applied},
        "sourceRunReceiptSha256": receipt_ref["sha256"], "declarationSha256": declaration_ref["sha256"],
        "knownLimitations": ["Historical fitted training and feature chronology remains qualified.",
            "Monte Carlo error is separate from uncertainty across real games.",
            "Fallback output is operational coverage, not a supported component trial."], **FLAGS}
    files = {"forecast.json": canonical(forecast), "execution-receipt.json": verified(receipt_ref).read_bytes(),
             "paired-populations.npz": verified(receipt["population"]).read_bytes(),
             "baseline-forecast.json": source_files["forecast.json"].read_bytes(),
             "baseline-execution-inputs.json": source_files["execution-inputs.json"].read_bytes(),
             "declaration.json": verified(declaration_ref).read_bytes()}
    component_ref = game["componentRefs"][arm]
    if component_ref["sha256"] != component_sha:
        raise ValueError("PINNED_COMPONENT_IDENTITY_MISMATCH")
    files["duration.joblib" if role == "DURATION" else "transition.json"] = verified(component_ref).read_bytes()
    artifacts = [{"relativePath": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                 for name, raw in sorted(files.items())]
    body = {"schemaVersion": "MLB_ENSEMBLE_CANDIDATE_OBJECT_MANIFEST_V1", "artifacts": artifacts,
            "configurationSha256": config_sha, "sourceRunReceiptSha256": receipt_ref["sha256"]}
    object_sha = hashlib.sha256(canonical(body)).hexdigest()
    object_root = package_root / "objects/sha256" / object_sha
    for name, raw in files.items():
        immutable(object_root / name, raw)
    immutable(object_root / "manifest.json", canonical({**body, "objectSha256": object_sha}))
    return {"sourceGameId": baseline["sourceGameId"], "objectSha256": object_sha,
            "relativePath": object_root.relative_to(package_root).as_posix(),
            "manifestFile": "manifest.json", "forecastFile": "forecast.json"}, forecast


def handoff_guide(package_root, result):
    destination = EXCHANGE / "packages/sha256" / package_root.name
    survival = destination / "V18_SURVIVAL_ONLY/aisp-handoff.json"
    transition = destination / "V18_TRANSITION_ONLY/aisp-handoff.json"
    lines = ["# Frozen V18 three-arm pregame comparison", "",
        "Import precomputed research forecasts only. The unchanged ordinary V18 baseline remains the enabled default. "
        "Calibration is disabled; execution, activation and wagering authority are false.", "",
        "This package contains two separately identified candidates sharing each game's exact original baseline: "
        "V18_SURVIVAL_ONLY uses the existing V1 BASE/DURATION contract; V18_TRANSITION_ONLY uses V2 BASE/TRANSITION. "
        "The V2 consumer extension is still required. No consumer import or display is confirmed by this package.", "",
        "| Configuration | Source game | Canonical game | Exact forecast ID | Exact baseline forecast ID |",
        "|---|---|---|---|---|"]
    for row in result["forecasts"]:
        lines.append("| " + " | ".join(str(row[k]) for k in
            ("configurationId", "sourceGameId", "canonicalGameId", "forecastId", "baselineForecastId")) + " |")
    lines += ["", "Each object preserves source cutoff, original capturedAt/freeze, scheduled start, policy cutoff, "
        "component status, seed 20260907, 5,000 paired draws and exact configuration/component identities. "
        "The publication receipt separately records first actual exchange publication time. Fallback forecasts "
        "reuse exact baseline draws and do not count as component trials.", "",
        "Import the named ordinary V18 baseline IDs first if absent. Use the existing Windows-owned ordinary "
        "V18 handoff and server/scripts/mlb_v18_daily_slate.py import --handoff <immutable ordinary handoff> "
        "--receipt <consumer-owned receipt path>. Do not substitute a newer baseline forecast for the named ID.", "",
        "Run the survival import from PowerShell after the package has actually been exported:", "", "```powershell",
        "Set-Location 'C:\\Users\\james\\ai-sports-predictor\\server'", "$candidateImport = @'",
        "import sys,json", "from pathlib import Path", "from dataclasses import asdict",
        "from app.db.session import SessionLocal",
        "from app.shadow_import.mlb_ensemble_candidate import verify_package,register_package",
        "verified = verify_package(Path(sys.argv[1]))",
        "if verified.rejected or not verified.forecasts:",
        "    raise ValueError('Package rejected or empty: '+repr(verified.rejected))",
        "with SessionLocal() as session:", "    receipt = register_package(session, verified)",
        "    session.commit()", "    print(json.dumps(asdict(receipt), default=str))", "'@",
        "& '..\\.venv\\Scripts\\python.exe' -c $candidateImport '" + str(survival) + "'", "```", "",
        "For TRANSITION, first extend the existing consumer to accept HANDOFF_V2 plus TRANSITION only under V2, "
        "retain the V1 child forecast/object schemas and existing baseline/clock/idempotency checks, and persist "
        "the actual handoff version in bundle.contract_version. Then run the same command with this exact handoff:",
        "", "```powershell", "& '..\\.venv\\Scripts\\python.exe' -c $candidateImport '" + str(transition) + "'", "```", "",
        "Current candidate_comparison selects one latest candidate and the latest baseline. Add a configuration "
        "selector and bind the displayed baseline by the candidate's stored baselineForecastId so both separate "
        "comparisons remain inspectable. An old imported ensemble replay does not establish support for these candidates.", "",
        "The original three assessment studies remain separate. COL–DET824227 and NYM–NYY823496 require a "
        "provenance-bearing FINAL revision; KC–BOS824712 requires a persisted eligible final. The governed "
        "game_final_outcomes record must include FINAL status, revision/source and required clocks. Core score "
        "columns cannot replace that record. Do not infer unavailable starter BF or transition sequences.", "",
        "Scoring command: `.\\.venv\\Scripts\\python.exe scripts/score_mlb_frozen_component_pairs_v1.py` in Model Studio. "
        "The original paired identities and scoring rules stay fixed; no new Monte Carlo run is needed to score them."]
    if result.get("existingPairScoringEvidence"):
        lines += ["", "Pinned existing-pair scoring receipt SHA-256: `" + result["existingPairScoringEvidence"]["sha256"] +
                  "`; copied as `existing-pair-scoring-findings.json`."]
    lines += ["", "After import, return exact forecast IDs, imported/already-present/rejected counts, bundle contract version "
        "and consumer receipt path. Report display confirmation separately. A few observed games establish integration "
        "and measurement, not predictive superiority.", ""]
    return "\n".join(lines).encode()


def export_package(package_ref):
    """Copy this study only; never replace the existing ensemble current pointer."""
    receipt_path = verified(package_ref)
    package_root = receipt_path.parent
    target_root = EXCHANGE / "packages/sha256" / package_root.name
    if not target_root.resolve().is_relative_to(EXCHANGE.resolve()):
        raise ValueError("EXCHANGE_DESTINATION_ESCAPE")
    target_receipt = target_root / "publication-receipt.json"
    if target_receipt.exists():
        saved = read(target_receipt)
        if saved["sourcePackage"]["sha256"] != package_ref["sha256"]:
            raise ValueError("PUBLICATION_SOURCE_MISMATCH")
        return reference(target_receipt)
    package = read(receipt_path)
    published_at = datetime.now(timezone.utc)
    previous_clocks = {}
    if (EXCHANGE / "current.json").exists():
        previous = read(verified(read(EXCHANGE / "current.json")))
        previous_clocks = {row["forecastId"]: row for row in previous.get("forecastPublicationClocks", [])}
    clocks = []
    for forecast in package["forecasts"]:
        old = previous_clocks.get(forecast["forecastId"])
        if old and old["objectSha256"] != forecast["objectSha256"]:
            raise ValueError("PUBLISHED_FORECAST_IDENTITY_REWRITE")
        first_published = utc(old["firstExchangePublishedAtUtc"]) if old else published_at
        if first_published >= utc(forecast["policyCutoffUtc"]):
            raise ValueError("NEW_EXCHANGE_PUBLICATION_AFTER_FORECAST_DEADLINE:" + forecast["forecastId"])
        clocks.append({"forecastId": forecast["forecastId"], "objectSha256": forecast["objectSha256"],
                       "firstExchangePublishedAtUtc": first_published.isoformat(),
                       "immutableForecastFrozenAtUtc": forecast["publishedAt"],
                       "policyCutoffUtc": forecast["policyCutoffUtc"]})
    copied = []
    for source in sorted(package_root.rglob("*")):
        if source.is_file():
            relative = source.relative_to(package_root)
            item = immutable(target_root / relative, source.read_bytes())
            copied.append({"relativePath": relative.as_posix(), **item})
    # Publication becomes reviewable only once all immutable package bytes exist.
    # An execution that crosses a cutoff during copying leaves no current pointer.
    published_at = datetime.now(timezone.utc)
    for row in clocks:
        if row["forecastId"] not in previous_clocks:
            row["firstExchangePublishedAtUtc"] = published_at.isoformat()
            if published_at >= utc(row["policyCutoffUtc"]):
                raise ValueError("EXCHANGE_COPY_COMPLETED_AFTER_FORECAST_DEADLINE:" + row["forecastId"])
    result = {"schemaVersion": "MLB_V18_THREE_ARM_EXCHANGE_PUBLICATION_V1", "sourcePackage": package_ref,
        "publishedAtUtc": published_at.isoformat(), "objects": copied,
        "forecastPublicationClocks": clocks,
        "handoffs": {arm: reference(target_root / (arm + "/aisp-handoff.json")) for arm in ARMS},
        "consumerImportConfirmed": False, "consumerDisplayConfirmed": False,
        "oldExchangePointerModified": False, **FLAGS}
    published = immutable(target_receipt, canonical(result))
    atomic_json(EXCHANGE / "current.json", published)
    return published


def build(current_path, *, export=False):
    current = read(current_path)
    status_ref = current if {"path", "sha256", "bytes"} <= current.keys() else reference(current_path)
    status = read(verified(status_ref))
    if status.get("schemaVersion") != "MLB_V18_THREE_ARM_PREGAME_V1_STATUS":
        raise ValueError("THREE_ARM_DRIVER_STATUS_REQUIRED")
    declaration_ref = status["declaration"]
    declaration = read(verified(declaration_ref))
    if (declaration.get("schemaVersion") != "MLB_V18_THREE_ARM_PREGAME_V1_DECLARATION"
            or declaration.get("paModelSha256") != PA_SHA
            or declaration.get("arms") != ["V18_BASE", *ARMS]
            or declaration.get("simulationCountPerArm") != 5000
            or declaration.get("masterSeed") != 20260907
            or declaration.get("outcomeAccess") is not False):
        raise ValueError("FROZEN_THREE_ARM_DECLARATION_REQUIRED")
    for arm, (_, _, digest, _) in ARMS.items():
        if declaration["components"][arm]["sha256"] != digest:
            raise ValueError("DECLARED_COMPONENT_CHANGED")
        verified(declaration["components"][arm])
    transition = read(verified(declaration["components"]["V18_TRANSITION_ONLY"]))
    if transition["priorStrength"] != 20.0 or transition["legalFloor"] != 1e-6:
        raise ValueError("FROZEN_TRANSITION_PARAMETERS_CHANGED")
    members = {row["gameId"]: row for row in declaration["games"]}
    if len(members) != len(declaration["games"]) or not all(final_oot_eligible_key_mask(
            [key for row in declaration["games"] for key in (row["gameId"], str(row["sourceGameId"]))])):
        raise ValueError("DECLARATION_IDENTITY_QUARANTINE_FAILED")
    if "2026-08-14" <= declaration["slateDate"] <= "2026-08-27":
        raise ValueError("SEALED_SLATE_FORBIDDEN")
    completed = [row["result"] for row in status["records"] if "result" in row]
    if not completed:
        return {"status": "NO_FROZEN_FORECASTS_TO_PACKAGE", "declared": len(members),
                "sourceStatus": status_ref, "published": 0, "importConfirmed": 0,
                "remaining": [{"gameId": row["gameId"], "status": row["status"]} for row in status["records"]], **FLAGS}
    completed.sort(key=lambda item: item["sha256"])
    scoring_ref = None
    if (OUTPUT / "scoring/current.json").exists():
        scoring_ref = read(OUTPUT / "scoring/current.json")
        verified(scoring_ref)
    package_key = hashlib.sha256(canonical({"declaration": declaration_ref["sha256"],
        "results": [row["sha256"] for row in completed], "scoring": scoring_ref["sha256"] if scoring_ref else None,
        "packager": reference(__file__)["sha256"]})).hexdigest()
    package_root = OUTPUT / "packages/sha256" / package_key
    receipt_path = package_root / "package-receipt.json"
    if receipt_path.exists():
        package_ref = reference(receipt_path)
        result = {"package": package_ref, "receipt": read(receipt_path), "reused": True}
        if export:
            result["publication"] = export_package(package_ref)
        return result
    games, seen, authority, authority_refs = [], set(), None, None
    for item in completed:
        original = read(verified(item))
        game_id = original["gameId"]
        if game_id not in members or game_id in seen:
            raise ValueError("UNDECLARED_OR_DUPLICATE_FROZEN_GAME")
        seen.add(game_id)
        member = members[game_id]
        if (original.get("schemaVersion") != "MLB_V18_THREE_ARM_PREGAME_V1_RESULT"
                or original.get("declaration") != declaration_ref
                or original.get("outcomeRead") is not False
                or original.get("candidateAuthority") is not False
                or original.get("executionAllowedInAISP") is not False
                or original.get("wageringAuthority") is not False
                or str(original["sourceGameId"]) != str(member["sourceGameId"])
                or original["simulationCountPerConfiguration"] != 5000
                or original["masterSeed"] != 20260907):
            raise ValueError("FROZEN_RESULT_AUTHORITY_OR_IDENTITY_MISMATCH")
        if not (utc(declaration["declaredAtUtc"]) <= utc(original["executionStartedAtUtc"])
                <= utc(original["frozenAtUtc"]) < utc(original["deadlineUtc"])
                < utc(original["scheduledStartUtc"])):
            raise ValueError("FROZEN_RESULT_CLOCKS_INVALID")
        if (utc(original["deadlineUtc"]) != utc(member["deadlineUtc"])
                or utc(original["scheduledStartUtc"]) != utc(member["scheduledStartUtc"])):
            raise ValueError("DECLARED_CUTOFF_CHANGED")
        baseline, execution, source_files = baseline_files(original["sourceForecastObjectSha256"])
        if (baseline["gameId"] != game_id or str(baseline["sourceGameId"]) != str(original["sourceGameId"])
                or baseline["teams"] != original["teams"]
                or utc(baseline["scheduledStart"]) != utc(original["scheduledStartUtc"])
                or baseline["sourceCutoff"] != original["sourceCutoff"]
                or execution["sourceCutoff"] != original["sourceCutoff"]
                or baseline["forecastCreatedAt"] != original["baselineForecastCreatedAtUtc"]
                or original["baselineForecastId"] != "mlb-v18-daily-" + original["sourceForecastObjectSha256"]
                or reference(source_files["forecast.json"]) != original["baselineForecast"]
                or reference(source_files["execution-inputs.json"]) != original["executionInputs"]
                or baseline["simulation"]["count"] != 5000 or baseline["simulation"]["seed"] != 20260907):
            raise ValueError("EXACT_BASELINE_BINDING_MISMATCH")
        binding, refs = baseline_authority(baseline)
        if authority is not None and binding != authority:
            raise ValueError("MIXED_BASELINE_AUTHORITY")
        authority, authority_refs = binding, refs
        arrays = {}
        with np.load(verified(original["population"]), allow_pickle=False) as saved:
            for arm in ("V18_BASE", *ARMS):
                for side in ("homeRuns", "awayRuns"):
                    key = arm + "_" + side
                    values = np.asarray(saved[key])
                    if (values.shape != (5000,) or not np.isfinite(values).all()
                            or (values < 0).any() or (values != np.floor(values)).any()):
                        raise ValueError("INVALID_RETAINED_DRAWS:" + key)
                    arrays[key] = values.astype(np.int64)
                home, away = arrays[arm + "_homeRuns"], arrays[arm + "_awayRuns"]
                if np.any(home == away):
                    raise ValueError("TERMINAL_TIED_GAME_DRAW")
                reported = original["arms"][arm]["summary"]
                if any(not np.isclose(value, reported[name], rtol=0, atol=1e-12)
                       for name, value in summary(home, away).items()):
                    raise ValueError("RETAINED_DRAW_SUMMARY_MISMATCH:" + arm)
            for side in ("homeRuns", "awayRuns"):
                if not np.array_equal(arrays["V18_BASE_" + side], execution["population"][side]):
                    raise ValueError("ORIGINAL_BASELINE_DRAWS_DIFFER")
        receipt = {**original, "pairFrozenAtUtc": original["frozenAtUtc"], "policyCutoffUtc": original["deadlineUtc"],
                   "arms": {name: dict(value) for name, value in original["arms"].items()}}
        for arm in ARMS:
            branch = receipt["arms"][arm]
            if branch["status"] not in {"APPLIED", "BASELINE_FALLBACK"}:
                raise ValueError("ARM_SUPPORT_STATUS_REQUIRED")
            branch["applied"] = branch["status"] == "APPLIED"
            if branch["applied"]:
                if branch.get("component") != declaration["components"][arm] or not branch.get("componentTrial"):
                    raise ValueError("APPLIED_COMPONENT_IDENTITY_MISMATCH")
            else:
                if branch.get("componentTrial") or not branch.get("fallbackReason"):
                    raise ValueError("FALLBACK_CANNOT_COUNT_AS_COMPONENT_TRIAL")
                if any(not np.array_equal(arrays[arm + "_" + side], arrays["V18_BASE_" + side])
                       for side in ("homeRuns", "awayRuns")):
                    raise ValueError("FALLBACK_MUST_BE_EXACT_BASELINE")
        games.append({"receipt": receipt, "receiptRef": item, "baseline": baseline, "execution": execution,
                      "sourceFiles": source_files, "arrays": arrays, "componentRefs": declaration["components"]})
    generated_at = datetime.now(timezone.utc).isoformat()
    handoffs, forecast_rows = {}, []
    for arm, (role, component_id, component_sha, version) in ARMS.items():
        arm_root = package_root / arm
        config = {"schemaVersion": "MLB_V18_THREE_ARM_CONFIGURATION_V1", "configurationId": arm,
                  "componentId": component_id, "componentSha256": component_sha, "role": role,
                  "paModelSha256": PA_SHA, "baseline": authority, "calibrationEnabled": False,
                  "declarationSha256": declaration_ref["sha256"], "simulationCount": 5000,
                  "seed": 20260907, "transitionPriorStrength": 20.0, "transitionLegalFloor": 1e-6,
                  "unsupportedFallback": "V18_BASE", "packager": reference(__file__), **FLAGS}
        config_raw = canonical(config)
        config_sha = hashlib.sha256(config_raw).hexdigest()
        immutable(arm_root / "configuration.json", config_raw)
        entries = []
        for game in games:
            entry, forecast = candidate_object(arm_root, game, arm, config_sha, declaration_ref)
            entries.append(entry)
            forecast_rows.append({"configurationId": arm, "forecastId": forecast["forecastId"],
                "baselineForecastId": forecast["baselineForecastId"], "canonicalGameId": forecast["canonicalGameId"],
                "sourceGameId": forecast["sourceGameId"], "capturedAt": forecast["capturedAt"],
                "publishedAt": forecast["publishedAt"], "scheduledStart": forecast["scheduledStart"],
                "policyCutoffUtc": forecast["policyCutoffUtc"],
                "componentTrialSupported": forecast["eligibility"]["componentTrialSupported"],
                "componentsApplied": forecast["componentsApplied"], "objectSha256": entry["objectSha256"]})
        handoff = {"schemaVersion": "AISP_MLB_ENSEMBLE_CANDIDATE_HANDOFF_" + version,
            "bundleId": "mlb-v18-three-arm-" + role.lower() + "-" + package_key[:24],
            "generatedAt": generated_at, "slateDate": declaration["slateDate"], "artifactType": "PROSPECTIVE",
            "candidate": {"engineId": "MLB_ENSEMBLE_CANDIDATE",
                "engineVersion": "mlb-v18-three-arm-" + role.lower() + "-v1",
                "modelArtifactSha256": config_sha, "manifestSha256": config_sha},
            "baseline": authority, "components": [
                {"componentId": "MLB_V18_HGB_PA", "role": "BASE", "sha256": PA_SHA, "status": "FROZEN"},
                {"componentId": component_id, "role": role, "sha256": component_sha, "status": "SHADOW_ONLY"}],
            "forecasts": entries, "configuration": {"relativePath": "configuration.json", "sha256": config_sha,
                "bytes": len(config_raw)}, "contractExtensionRequired": version == "V2",
            "consumerImportConfirmed": False, "consumerDisplayConfirmed": False,
            "publicationClockNote": "generatedAt is package construction; child publishedAt is the original immutable pregame freeze.", **FLAGS}
        handoff["handoffSha256"] = hashlib.sha256(canonical(handoff)).hexdigest()
        handoffs[arm] = immutable(arm_root / "aisp-handoff.json", canonical(handoff))
    for name, descriptor in authority_refs.items():
        immutable(package_root / "baseline-authority" / name, verified(descriptor).read_bytes())
    immutable(package_root / "declaration.json", verified(declaration_ref).read_bytes())
    immutable(package_root / "source-status.json", verified(status_ref).read_bytes())
    code_snapshots = []
    dependency_path = OUTPUT / "dependency-identities.json"
    if not dependency_path.exists():
        raise ValueError("FROZEN_DRIVER_DEPENDENCY_IDENTITY_REQUIRED")
    dependencies = read(dependency_path)
    for descriptor in [reference(__file__), *dependencies["codeAndGovernance"]]:
        source = verified(descriptor)
        if not source.is_relative_to(ROOT):
            raise ValueError("CODE_SNAPSHOT_OUTSIDE_STUDIO")
        relative = source.relative_to(ROOT)
        snapshot = immutable(package_root / "code" / relative, source.read_bytes())
        code_snapshots.append({"sourceRelativePath": relative.as_posix(), **snapshot})
    counts = {"declared": len(members), "locallyFrozenGames": len(games), "candidateForecasts": len(forecast_rows),
        "survivalSupported": sum(g["receipt"]["arms"]["V18_SURVIVAL_ONLY"]["applied"] for g in games),
        "transitionSupported": sum(g["receipt"]["arms"]["V18_TRANSITION_ONLY"]["applied"] for g in games),
        "commonSupported": sum(all(g["receipt"]["arms"][a]["applied"] for a in ARMS) for g in games),
        "fallbackArms": sum(not g["receipt"]["arms"][a]["applied"] for g in games for a in ARMS),
        "blockedOrPending": len(members) - len(games), "consumerImportConfirmed": 0, "consumerDisplayConfirmed": 0}
    result = {"schemaVersion": "MLB_V18_THREE_ARM_PACKAGE_RECEIPT_V1", "packageKey": package_key,
        "generatedAtUtc": generated_at, "sourceStatus": status_ref, "declaration": declaration_ref,
        "handoffs": handoffs, "counts": counts, "forecasts": forecast_rows,
        "codeSnapshots": code_snapshots,
        "existingPairScoringEvidence": scoring_ref,
        "pending": [{"gameId": r["gameId"], "status": r["status"]} for r in status["records"] if "result" not in r],
        "verification": {"originalBaselineDrawsExact": True, "retainedSummaryReconciled": True,
            "fallbackDrawsExact": True, "outcomeReads": 0, "inferenceRuns": 0, "fits": 0},
        "consumerStatus": {"V18_SURVIVAL_ONLY": "V1_IMPORT_VALIDATION_REQUIRED_NO_IMPORT_CONFIRMED",
            "V18_TRANSITION_ONLY": "REQUIRES_V2_TRANSITION_ROLE_SUPPORT_NO_IMPORT_CONFIRMED",
            "display": "Current AISP selects one latest candidate and latest baseline; request configuration selector and exact baselineForecastId binding."},
        "importPrerequisite": "Every baselineForecastId must first be registered through the existing ordinary V18 importer.",
        "aispImport": {"workingDirectory": r"C:\Users\james\ai-sports-predictor\server",
            "api": "app.shadow_import.mlb_ensemble_candidate.verify_package + register_package",
            "pythonCode": "import sys,json; from pathlib import Path; from dataclasses import asdict; from app.db.session import SessionLocal; from app.shadow_import.mlb_ensemble_candidate import verify_package,register_package; p=verify_package(Path(sys.argv[1])); assert p.forecasts and not p.rejected; s=SessionLocal(); r=register_package(s,p); s.commit(); print(json.dumps(asdict(r),default=str)); s.close()",
            "invocation": "..\\.venv\\Scripts\\python.exe -c <pythonCode above> <exact handoff path>",
            "transitionCondition": "Claude must implement the narrowly documented V2 version/TRANSITION-role support before this command can accept V2."}, **FLAGS}
    if scoring_ref:
        immutable(package_root / "existing-pair-scoring-findings.json", verified(scoring_ref).read_bytes())
    for name in ("contract-evidence-v2.json", "dependency-identities.json", "focused-checks.json"):
        if (OUTPUT / name).exists():
            immutable(package_root / name, (OUTPUT / name).read_bytes())
    result["claudeGuide"] = immutable(package_root / "CLAUDE_HANDOFF.md", handoff_guide(package_root, result))
    package_ref = immutable(receipt_path, canonical(result))
    atomic_json(OUTPUT / "package-current.json", package_ref)
    response = {"package": package_ref, "receipt": result, "reused": False}
    if export:
        response["publication"] = export_package(package_ref)
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=OUTPUT / "current.json")
    parser.add_argument("--export", action="store_true", help="Publish this package into the existing research exchange")
    args = parser.parse_args()
    with single_owner(LOCK) as owned:
        if not owned:
            raise SystemExit("EXISTING_RESEARCH_PUBLICATION_LOCK_BUSY")
        print(json.dumps(build(args.current, export=args.export), indent=2))

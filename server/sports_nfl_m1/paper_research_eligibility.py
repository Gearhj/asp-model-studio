"""Frozen producer evidence for one authorized virtual NFL experiment.

Uses the existing research-supplement container. It never grants production
authority, fetches quotes, fits, runs a forecast, or writes an AISP account.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from server.sports_gold.nfl_shadow_exchange import verify_sports_forecast_bundle
from .current_shadow import _effective_forecasts
from .labs_simulation import utc

EVENT = "2026_01_DEN_KC"
FORECAST = "asp-sports-game-forecast:sha256:2d9d0197aa7ef02c15a110cf7ce5f36ad2a87d2f1c2a92601d9989d5c487aec9"
KIND = "PAPER_RESEARCH_ELIGIBILITY"
VERSION = "ASP_NFL_PAPER_RESEARCH_ELIGIBILITY_V1"
GOVERNANCE = dict(status="RESEARCH_SHADOW", researchShadowOnly=True,
                  executionAllowedInAisp=False, modelPromotionAllowed=False,
                  wageringAuthority=False)


def canonical_json_bytes(value: object) -> bytes:
    """AISP research-supplement wire encoding; distinct from audit ASCII JSON."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def immutable_json(path: Path, value: object) -> dict:
    """Write and re-read exact consumer bytes without changing existing objects."""
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable object already differs: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise ValueError("Written consumer bytes differ: " + str(path))
    return physical(path)


def physical(path: Path) -> dict:
    raw = path.read_bytes()
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def require_physical(reference: dict) -> None:
    if physical(Path(reference["path"])) != {k: reference[k] for k in ("path", "sha256", "bytes")}:
        raise ValueError("Evidence bytes differ: " + reference["path"])


def validate_evidence(doc: dict) -> None:
    """Reference kind validator; existing consumer must explicitly register kind."""
    if doc["schemaVersion"] != "AISP_RESEARCH_SUPPLEMENT_V1" or doc["sport"] != "NFL":
        raise ValueError("Unsupported container or sport")
    if doc["kind"] != KIND or doc["artifactVersion"] != VERSION or doc["governance"] != GOVERNANCE:
        raise ValueError("Unexpected kind/version/authority")
    if doc["simulation"] != {"kind": "NONE", "count": 0}:
        raise ValueError("Eligibility is not a new simulation")
    binding, summary = doc["binding"], doc["summaries"]
    if binding["eventId"] != EVENT or binding["forecastId"] != FORECAST:
        raise ValueError("This evidence is bound only to the preserved DEN-KC forecast")
    auth = summary["authorization"]
    if not auth["experimentId"] or auth["mode"] != "VIRTUAL_RESEARCH_ONLY":
        raise ValueError("Missing exact virtual experiment authorization")
    if auth["virtualInitialBankrollUsd"] != 1000 or auth["positionCapFraction"] != .005 or auth["maxDailyNflPregameQuotes"] != 1:
        raise ValueError("User-authorized scope differs")
    if auth["realMoneyAuthorized"] is not False:
        raise ValueError("No real-money authority")
    if auth["scopeOfThisEvidence"] != [EVENT]:
        raise ValueError("No unbounded cohort eligibility")
    for key in ("sourceReceipt", "confirmationMessage"):
        require_physical(auth[key])
    if summary["tieDiagnostic"]["conclusion"]["concreteUnusableProbabilityDefectFound"]:
        raise ValueError("Required probability defect remains")
    if summary["producerDisposition"] != "ELIGIBLE_EVIDENCE_FOR_AUTHORIZED_VIRTUAL_RESEARCH_WITH_LIMITATIONS":
        raise ValueError("Unsupported producer disposition")
    if binding["modelArtifactSha256"] != summary["frozenConfiguration"]["engine"]["modelBinarySha256"]:
        raise ValueError("Frozen model identity differs")
    if binding["engineId"] != summary["frozenConfiguration"]["engine"]["engineId"]:
        raise ValueError("Frozen engine identity differs")
    if auth["realMoneyExecutionAllowed"] is not False or auth["consumerVirtualExperimentAuthorized"] is not True:
        raise ValueError("Separate virtual approval from real-money execution")
    captured = json.loads(Path(auth["sourceReceipt"]["path"]).read_bytes())
    policy = captured["policyConstants"]
    approved = captured["activationConstants"]
    if (auth["experimentName"] != approved["ERA_NAME"] or auth["policyVersion"] != policy["POLICY_VERSION"]
            or auth["positionCapFraction"] != policy["POSITION_CAP_UNCALIBRATED"]
            or auth["virtualInitialBankrollUsd"] != policy["STARTING_BANKROLL"]
            or auth["existingModelBinding"] != approved["MODEL_BINDING"]
            or binding["modelArtifactSha256"] != approved["MODEL_BINDING"]["model_binary_sha256"]):
        raise ValueError("Authorization or model differs from the retained consumer record")
    timing = summary["timing"]
    if (timing["originalFinalPregameDeadlineUtc"] != "2026-09-15T00:00:00Z"
            or timing["originalFinalPregameWindowStartUtc"] != "2026-09-14T23:45:00Z"
            or timing["scheduledStartUtc"] != "2026-09-15T00:15:00Z"):
        raise ValueError("Original event clocks changed")
    if doc["sourceCutoffUtc"] != summary["frozenConfiguration"]["originalForecastClocks"]["sourceCutoffUtc"]:
        raise ValueError("Original source cutoff was restamped")
    if utc(doc["publishedUtc"]) >= utc(timing["originalFinalPregameDeadlineUtc"]):
        raise ValueError("Original final-pregame deadline has passed")
    if utc(timing["originalForecastAvailableAtUtc"]) >= utc(timing["scheduledStartUtc"]):
        raise ValueError("Forecast was not pregame")
    probs = summary["probabilitySemantics"]["threeWayProbabilities"]
    if any(not 0 <= p <= 1 for p in probs.values()) or abs(sum(probs.values()) - 1) > 1e-12:
        raise ValueError("Winner probability mass differs")


def build_document(readiness: dict, diagnostic: dict, authorization: dict, *, published_utc: str) -> dict:
    f = readiness["effectiveForecast"]
    if f["forecastId"] != FORECAST or diagnostic["forecastId"] != FORECAST:
        raise ValueError("Readiness/diagnostic forecast binding differs")
    return {
        "schemaVersion": "AISP_RESEARCH_SUPPLEMENT_V1", "artifactVersion": VERSION,
        "supplementId": f"nfl-paper-eligibility:{authorization['experimentId']}:{EVENT}:v1",
        "kind": KIND, "sport": "NFL", "governance": GOVERNANCE,
        "binding": {"eventId": EVENT, "engineId": f["engine"]["engineId"],
                    "forecastId": FORECAST, "modelArtifactSha256": f["engine"]["modelBinarySha256"]},
        "sourceCutoffUtc": f["originalForecastClocks"]["sourceCutoffUtc"],
        "publishedUtc": published_utc, "simulation": {"kind": "NONE", "count": 0},
        "summaries": {
            "producerDisposition": "ELIGIBLE_EVIDENCE_FOR_AUTHORIZED_VIRTUAL_RESEARCH_WITH_LIMITATIONS",
            "authorization": authorization,
            "frozenConfiguration": f,
            "forecastBundle": readiness["physicalReferences"]["currentAuthorityBundle"],
            "originalForecastBundle": readiness["physicalReferences"]["originalBundle"],
            "modelArtifact": readiness["physicalReferences"]["modelArtifactIncludingFittedPreprocessing"],
            "originalFeatureVector": readiness["physicalReferences"]["originalFeatureVector"],
            "currentInputCoverage": readiness["numericalInputCoverage"],
            "semanticReuse": readiness["semanticReuse"],
            "timing": {
                "scheduledStartUtc": "2026-09-15T00:15:00Z",
                "originalFinalPregameWindowStartUtc": "2026-09-14T23:45:00Z",
                "originalFinalPregameDeadlineUtc": "2026-09-15T00:00:00Z",
                "originalForecastAvailableAtUtc": f["originalForecastClocks"]["availableAsOfUtc"],
                "sourceAndForecastClocksUnchanged": True,
                "eligibilityCreatedAtUtc": published_utc,
                "finalPregameReceiptStillRequiredFromExistingOwner": True,
                "laterForecastRule": "This document attests only CURRENT v7. A later FINAL_PREGAME ID must pass the existing owner and consumer model-binding/timing checks; this document is not an attestation of unseen inputs. The approved consumer policy already pins M1 and does not require a new generic supplement importer. No regenerator is invoked here.",
            },
            "probabilitySemantics": {
                "units": "FRACTION_0_TO_1",
                "threeWayProbabilities": {"awayWin": f["awayWinProbability"], "homeWin": f["homeWinProbability"], "tie": f["tieProbability"]},
                "tieMeaning": "EQUAL_MODELED_FINAL_SCORES_NOT_OTHER_OR_OVERTIME_OCCURRENCE",
                "calibrationValidated": False,
                "settlementMustBeExplicit": True,
                "ifMoneylineTieRefund": {
                    "away": {"pWin": f["awayWinProbability"], "pPush": f["tieProbability"], "pLoss": f["homeWinProbability"]},
                    "home": {"pWin": f["homeWinProbability"], "pPush": f["tieProbability"], "pLoss": f["awayWinProbability"]},
                    "qualification": "Conditional settlement example only. Claude must bind actual quote rules; preserve all three raw masses.",
                },
                "quoteProvidedByProducer": False,
                "decisionOrProfitabilityClaim": False,
            },
            "tieDiagnostic": diagnostic,
            "consumerResponsibilities": [
                "Verify actual experiment authorization and existing experiment rules; do not replace a cohort or stopping rule.",
                "The existing AISP paper-activation path already pins this model. This additive evidence is not a new activation prerequisite. If registering it via the generic supplement importer, explicitly admit the new kind/version and verify bindings; old importers must reject it.",
                "Obtain the single authorized daily pregame quote through the existing owner, with actual timestamp, market and tie/push settlement.",
                "Apply the approved virtual account and 0.5% position cap under existing experiment rules. Producer execution remains false while separate consumer virtual authorization is true. No real-money execution or champion status is granted.",
                "Use the existing final-pregame owner/window; retain immutable forecast and decision clocks. A paper outcome is not a proven edge.",
            ],
        },
    }


def verify_package(directory: Path) -> dict:
    if {p.name for p in directory.iterdir()} != {"manifest.json", "supplement.json"}:
        raise ValueError("Supplement inventory differs")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if (manifest["schemaVersion"] != "AISP_RESEARCH_SUPPLEMENT_MANIFEST_V1"
            or manifest["contractVersion"] != "AISP_RESEARCH_SUPPLEMENT_V1"):
        raise ValueError("Unsupported manifest contract")
    identity = {k: v for k, v in manifest.items() if k != "supplementSha256"}
    if hashlib.sha256(canonical_json_bytes(identity)).hexdigest() != directory.name or manifest["supplementSha256"] != directory.name:
        raise ValueError("Manifest identity differs")
    if (directory / "manifest.json").read_bytes() != canonical_json_bytes(manifest):
        raise ValueError("Manifest is not canonical")
    raw = (directory / "supplement.json").read_bytes()
    if manifest["artifacts"] != [{"file": "supplement.json", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}]:
        raise ValueError("Physical supplement checksum/bytes differ")
    doc = json.loads(raw)
    if raw != canonical_json_bytes(doc) or manifest["governance"] != GOVERNANCE:
        raise ValueError("Canonical encoding or manifest authority differs")
    for key in ("kind", "supplementId", "sport"):
        if doc[key] != manifest[key]:
            raise ValueError("Manifest binding differs")
    validate_evidence(doc)
    return doc


def publish(*, exchange_root: Path, output_root: Path, authorization_path: Path) -> dict:
    readiness_path = Path("outputs/producer-readiness-20260914-v1/nfl-readiness.json")
    readiness = json.loads(readiness_path.read_bytes())
    diagnostic_path = output_root / "tie-diagnostic.json"
    diagnostic = json.loads(diagnostic_path.read_bytes())
    successor_path = output_root / "tie-diagnostic-successor.json"
    successor = json.loads(successor_path.read_bytes())
    authorization = json.loads(authorization_path.read_bytes())
    bundle_ref = readiness["physicalReferences"]["currentAuthorityBundle"]
    source = verify_sports_forecast_bundle(exchange_root, bundle_ref["sha256"])
    forecast = _effective_forecasts(source.record)[EVENT]
    if forecast["forecastId"] != FORECAST:
        raise ValueError("Original CURRENT selection differs")
    references = [readiness["physicalReferences"][k] for k in (
        "currentAuthorityBundle", "originalBundle", "originalFeatureVector", "modelArtifactIncludingFittedPreprocessing", "modelManifest")]
    for ref in references:
        require_physical(ref)
    locator_path = exchange_root / "aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json"
    locator = json.loads(locator_path.read_bytes())
    if bundle_ref["sha256"] not in locator["currentBundleSha256s"]:
        raise ValueError("Bound CURRENT bundle is no longer selected")
    now = datetime.now(timezone.utc).isoformat()
    doc = build_document(readiness, diagnostic, authorization, published_utc=now)
    doc["summaries"]["tieDiagnosticSuccessor"] = successor
    doc["producer"] = {"readinessReceipt": physical(readiness_path), "diagnosticReceipt": physical(diagnostic_path),
                       "diagnosticSuccessorReceipt": physical(successor_path),
                       "authorizationRecord": physical(authorization_path), "currentLocatorSnapshot": physical(locator_path),
                       "modelFitOccurred": False, "forecastRegenerated": False, "providerRequests": 0}
    validate_evidence(doc)
    data = canonical_json_bytes(doc)
    manifest = {"schemaVersion": "AISP_RESEARCH_SUPPLEMENT_MANIFEST_V1", "contractVersion": "AISP_RESEARCH_SUPPLEMENT_V1",
                "supplementId": doc["supplementId"], "kind": KIND, "sport": "NFL", "governance": GOVERNANCE,
                "artifacts": [{"file": "supplement.json", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}]}
    digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    manifest["supplementSha256"] = digest
    directory = exchange_root / "nfl-labs-supplements/sha256" / digest
    # Existing supplement discovery scans immutable object directories. No shared
    # discovery pointer or scheduled owner is changed for this additive artifact.
    immutable_json(directory / "supplement.json", doc)
    immutable_json(directory / "manifest.json", manifest)
    verify_package(directory)
    for ref in references:
        require_physical(ref)
    receipt = {"schemaVersion": "NFL_PAPER_RESEARCH_ELIGIBILITY_DELIVERY_V1", "supplementAddress": digest,
               "manifest": physical(directory / "manifest.json"), "supplement": physical(directory / "supplement.json"),
               "publicationStartedUtc": now, "publicationCompletedUtc": datetime.now(timezone.utc).isoformat(),
               "forecastId": FORECAST, "sourceForecastsAndModelsUnchanged": True,
               "consumerAcknowledgement": "NOT_ESTABLISHED", "newKindExplicitConsumerSupportRequiredForGenericImport": True,
               "newSupplementImporterRequiredToActivateExistingPaperPolicy": False,
               "providerRequests": 0, "forecastExecutions": 0, "aispWrites": 0, "governance": GOVERNANCE}
    immutable_json(output_root / "publication" / digest / "delivery-receipt.json", receipt)
    return receipt

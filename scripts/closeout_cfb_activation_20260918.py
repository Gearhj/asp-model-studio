"""Assemble the authorized producer handoff from retained, verified receipts.

Local only: no acquisition, owner invocation, installation, or consumer writes.
The live discovery pointer remains the authority for present eligibility.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(r"C:\Users\james\asp-model-studio")
OUT = ROOT / "outputs/cfb-recurring-activation-20260918-v1"
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange")
COORD = EXCHANGE / "cfb-activation-20260918"
PRODUCTION = EXCHANGE / "cfb-gen1-production-v1"
VERIFY = OUT / "independent-verification/sha256/69a7d54e6c486414f86e2244d022f9f65700d8a5f5fc7807cc373ee0cf94edc4/receipt.json"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def verified_load(binding):
    assert ref(binding["path"]) == binding, binding
    return load(binding["path"])


def immutable(root, name, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    path = root / hashlib.sha256(data).hexdigest() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return ref(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounting-receipt", required=True)
    args = parser.parse_args()
    verification = load(VERIFY)
    assert verification["status"] == "PASS"
    discovery = verified_load(verification["discovery"])
    paper = verified_load(verification["paperReceipt"])
    final_index = verified_load(verification["finalEvidenceIndex"])
    source_index_ref = load(COORD / "RETAINED_EVIDENCE_POINTER.json")["index"]
    source_index = verified_load(source_index_ref)
    original_ref = source_index["artifacts"]["original57PublicationIndexJson"]
    original = verified_load(original_ref)
    packages = {row["forecastId"]: row for row in discovery["packages"]}
    supplements = {row["forecastId"]: row for row in paper["games"]}
    assert len(packages) == len(supplements) == original["packageCount"] == 57
    rows = []
    for old in original["rows"]:
        forecast_id = old["forecastId"]
        current, supplement = packages[forecast_id], supplements[forecast_id]
        assert current["packageAddress"] == old["packageIndex"]["sha256"] == supplement["packageAddress"]
        assert current["committedAtUtc"] == old["originalPublishedAtUtc"]
        rows.append({"forecastId": forecast_id, "providerGameId": old["sourceGameId"],
                     "originalIdentityOrientationKickoffAndProbabilityEvidence": old,
                     "producerDiscoverySnapshot": current, "paperEligibility": supplement,
                     "consumerImported": None, "consumerHistorical": None,
                     "consumerExcluded": None, "consumerAcknowledgement": "NOT_YET_ACKNOWLEDGED"})
    assert paper["publishedCount"] == 57 and paper["reusedCount"] == 0
    observed = load(OUT / "final-scheduler-observation.json")
    assert observed["cfbOwnerCount"] == 1 and observed["lastTaskResult"] == 0
    assert all(row["xmlUnchanged"] for row in observed["preservedOwners"])
    object_root = OUT / "closeout/objects/sha256"
    scheduler = immutable(object_root, "scheduler.json", observed)
    runtime = immutable(object_root, "runtime-binding.json", load(ROOT / ".runtime/cfb-gen1-slate-publisher/deployment.json"))
    status_path = COORD / "CONSUMER_STATUS.md"
    status_text = status_path.read_text(encoding="utf-8")
    assert "INITIAL REQUIREMENTS" in status_text, "Consumer updated; inspect acknowledgement before publishing."
    ack_dir = EXCHANGE / "consumer-acknowledgements/aisp-cfb-gen1-production-v1"
    assert not ack_dir.exists() or not any(p.is_file() for p in ack_dir.rglob("*")), "Read newly arrived consumer acknowledgement first."
    consumer = immutable(object_root, "consumer-observation.json", {
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "statusFile": ref(status_path), "statusText": status_text,
        "acknowledgementDirectory": str(ack_dir), "acknowledgementFound": False,
        "importedCount": None, "status": "NOT_YET_ACKNOWLEDGED"})
    lines = load(COORD / "LINES_PROBE_EVIDENCE.json")
    for key in ("analysis", "completionReceipt", "rawResponse"):
        assert ref(lines[key]["path"]) == lines[key]
    installer = [ref(path) for pattern in ("plan-*.json", "install-*.json", "verify-*.json")
                 for path in (OUT / "consumer-successor-activation").glob(pattern)]
    assert len(installer) == 3 and all(load(item["path"])["exitCode"] == 0 for item in installer)
    reconciliation = immutable(PRODUCTION / "activation-evidence/sha256", "ORIGINAL_57_RECONCILIATION.json", {
        "schemaVersion": "CFB_PRODUCER_ACTIVATION_RECONCILIATION_V1",
        "discoverySnapshot": verification["discovery"], "currentDiscoveryPointer": str(PRODUCTION / "slate-discovery/current.json"),
        "originalInventory": original_ref, "paperReceipt": verification["paperReceipt"],
        "consumerObservation": consumer, "rows": rows,
        "semantics": "Producer status is a receipt-time snapshot. Consumer import/historical/excluded counts remain unknown until acknowledged. Current decisions require a fresh verified discovery lease and all consumer gates."})
    predecessor = PRODUCTION / "handoffs/sha256/b38413fa1668183f66205fc5aac951acdee74a236a499146941cd965d030b2c0/handoff.json"
    handoff = {
        "schema": "CFB_RECURRING_ACTIVATION_HANDOFF_V1",
        "publicationKind": "INSTALLED_PRODUCER_AND_CONSUMER_EVIDENCE",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(), "predecessor": ref(predecessor),
        "producerInstalled": True, "installationAuthorized": True, "recurringAcquisitionAuthorized": True,
        "consumerAcknowledged": False, "consumerActivationEstablished": False, "realMoneyAuthority": False,
        "deploymentId": verification["deploymentId"], "deploymentManifest": verification["deployment"],
        "release": verification["release"], "recurringPlan": verification["plan"],
        "paperPolicyAuthorization": verification["paperAuthorization"],
        "deploymentAuthorization": ref(OUT / "authorization/sha256/715085de981711a912b02e25deaaf7b43bc5e46faab716a78c94db12755ef24e/grant.json"),
        "source": {"branch": "codex/cfb-recurring-activation-20260918-v1", "deployedImplementationCommit": verification["sourceCommit"],
                   "closeoutBuilderParentCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                   "linesProbeBranch": "codex/cfb-lines-probe-20260918-v1", "linesProbeCommit": "fbf59a36db07d21a7e09dc5525aaed318cf124be"},
        "model": {"configurationIdentity": "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1", "pairedDraws": 10000,
                  "predictionReleaseIdentity": "5c853df0e441902eb71dfb1426ab645e707e22d8e91399b755fd332e0080530e",
                  "unchangedModelAndPopulation": True, "probabilityChannelAuthority": original["channels"]},
        "operationalRepairs": ["Task principal resolved through exact exported XML SID; strict installer checks retained",
                               "Canonical prediction release inherited across operational successors",
                               "Already committed unchanged forecasts may be re-vouched through T-15 under exact virtual-only grant; new forecast and supplement publication remain before T-30",
                               "Same locked owner exports admitted literal-source finals and per-forecast paper supplements locally"],
        "scheduler": scheduler, "runtimeBindingSnapshot": runtime, "supportedInstallerReceipts": installer,
        "naturalLauncher": verification["launcher"], "naturalOwner": verification["ownerReceipt"], "naturalRunner": verification["runnerReceipt"],
        "firstNaturalCapture": ref(ROOT / ".runtime/cfb-gen1-slate-publisher/state/capture/attempts/635c9fe0642040b0a43d684ac4664ee0/completion.json"),
        "discoverySnapshot": verification["discovery"], "currentDiscoveryPointer": str(PRODUCTION / "slate-discovery/current.json"),
        "countsAtVerifiedSnapshot": {"originalForecasts": 57, "producerEligible": 57, "producerHistorical": 0,
                                     "originalForecastsExcluded": 0, "newlySimulatedOrPublishedForecasts": 0,
                                     "newPaperSupplements": 57, "allScheduleDispositions": dict(Counter(row["disposition"] for row in discovery["games"])),
                                     "exclusionReasons": dict(Counter(row.get("reason") for row in discovery["games"] if row["disposition"] == "EXCLUDED"))},
        "reconciliation": reconciliation, "paperReceipt": verification["paperReceipt"],
        "paperSupplementRoot": str(EXCHANGE / "cfb-gen1-research-v1/paper-eligibility/sha256"),
        "finalResultIndex": verification["finalEvidenceIndex"], "currentFinalResultPointer": str(PRODUCTION / "final-result-evidence/current.json"),
        "finalResultSummary": final_index["summary"], "retainedSourceEvidence": source_index_ref,
        "linesProbe": lines, "accountingAndNextDue": ref(args.accounting_receipt),
        "independentVerification": ref(VERIFY), "focusedValidation": {"combinedTestsPassed": 75, "linesProbeTestsPassed": 9},
        "consumerObservation": consumer,
        "nextConsumerStep": "Claude must import/reconcile the 57 immutable forecasts and individual supplements against current discovery, admit retained finals through AISP canonical gates, activate only authorized virtual policy through its existing owner, and publish an import acknowledgement. CFBD lines acquisition time is not a quote timestamp and does not change SGO quote authority.",
        "ownerLeftRunning": True, "aispWritesByProducer": 0,
    }
    binding = immutable(PRODUCTION / "handoffs/sha256", "handoff.json", handoff)
    pointer = {"schema": "CFB_ACTIVATION_PRODUCER_HANDOFF_POINTER_V1", "handoff": binding,
               "currentDiscoveryPointer": handoff["currentDiscoveryPointer"], "currentFinalResultPointer": handoff["currentFinalResultPointer"]}
    temporary = COORD / "PRODUCER_HANDOFF.json.tmp"
    temporary.write_text(json.dumps(pointer, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temporary.replace(COORD / "PRODUCER_HANDOFF.json")
    print(json.dumps(binding))


if __name__ == "__main__":
    main()

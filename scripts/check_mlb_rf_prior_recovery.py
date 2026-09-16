"""Recover historical RF V1 authority only by exact checksum equality.

This utility reads authenticated JSON receipts and already-fitted V18 parameter
objects. It does not load frames, estimators, model libraries, or fit functions.
Historical timing metadata was not hashed and is intentionally not invented.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory"
OUTPUT = ROOT / "outputs/mlb-v18-rf-operationalization-v1/prior-recovery"
RF_RECEIPT_SHA = "15e7e65f2cf6931fc57b922f3be5fdce1e9244b38b31582d026db7d15cd45440"
RF_CANDIDATE_ID = "stage3-candidate-5a26360c71194c10b2c101d27f253bdf"
RF_OOF_SHA = "b7aefeb898ba1673b66859381d195abdcac43105857ee108ec3081c8bd03ea83"
COMPARISON_SHA = "12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d"
IGNORED_FIT_KEYS = {"fittedChecksum", "fittedId", "fitDurationMs"}


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_json(path: Path, expected_sha: str | None = None,
              expected_bytes: int | None = None) -> tuple[dict, dict]:
    if path.suffix != ".json":
        raise ValueError("Only JSON receipts and fitted authority objects may be read")
    raw = path.read_bytes()
    if expected_sha is not None and sha(raw) != expected_sha:
        raise ValueError(f"Source checksum mismatch: {path}")
    if expected_bytes is not None and len(raw) != expected_bytes:
        raise ValueError(f"Source byte count mismatch: {path}")
    return json.loads(raw), {"path": str(path.resolve()), "sha256": sha(raw), "bytes": len(raw)}


def write_immutable(path: Path, payload: dict) -> dict:
    raw = canonical(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Immutable output conflict: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"path": str(path.resolve()), "sha256": sha(raw), "bytes": len(raw)}


def checked_fitted_body(payload: dict) -> dict:
    body = {key: value for key, value in payload.items() if key not in IGNORED_FIT_KEYS}
    digest = sha(canonical(body))
    expected_id = f"{body['schemaVersion']}:{body['foldId']}:sha256:{digest}"
    if payload["fittedChecksum"] != digest or payload["fittedId"] != expected_id:
        raise ValueError("Serialized V18 prior failed its historical checksum definition")
    if body["trainingEnd"] >= "2026-08-14":
        raise ValueError("Fitted authority crosses the sealed boundary")
    return body


def main() -> None:
    receipt, receipt_ref = load_json(
        RUNTIME / f"candidate-attempts/objects/sha256/{RF_RECEIPT_SHA}.json", RF_RECEIPT_SHA)
    candidate = receipt["candidate"]
    if (candidate["candidateId"] != RF_CANDIDATE_ID or candidate["modelFamily"] != "random_forest"
            or candidate["evaluationEvidence"]["reloadableArtifactSha256"] != RF_OOF_SHA
            or receipt["finalOotTargetAccessed"] is not False):
        raise ValueError("Original RF authority differs")
    folds = candidate["folds"]
    if [fold["foldNumber"] for fold in folds] != list(range(1, 6)):
        raise ValueError("Exact five original chronological folds required")
    total_rows = folds[0]["trainRows"] + sum(fold["validationRows"] for fold in folds)
    for index, fold in enumerate(folds):
        if fold["trainRows"] + sum(item["validationRows"] for item in folds[index:]) != total_rows:
            raise ValueError("Original expanding-population counts do not reconcile")
        if fold["trainEnd"] >= fold["validationStart"] or fold["validationEnd"] >= "2026-08-14":
            raise ValueError("Original fold receipt crosses the sealed boundary")
    comparison, comparison_ref = load_json(ROOT / (
        f"outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-{COMPARISON_SHA}.json"))
    comparison_body = {key: value for key, value in comparison.items() if key != "resultChecksum"}
    if (comparison["resultChecksum"] != COMPARISON_SHA or sha(canonical(comparison_body)) != COMPARISON_SHA
            or comparison["authority"]["treatmentVersion"] != 18
            or comparison["finalOot"]["accessed"] is not False):
        raise ValueError("Saved V18 comparison authority differs")
    references = {row["foldNumber"]: row["fittedArtifact"]
                  for row in comparison["treatmentExecution"]["fittedFoldArtifacts"]}
    if set(references) != set(range(1, 6)):
        raise ValueError("Five saved V18 preprocessing objects required")
    results = []
    for fold in folds:
        number = fold["foldNumber"]
        reference = references[number]
        path = (RUNTIME / reference["relativePath"]).resolve()
        if not path.is_relative_to((RUNTIME / "objects/corrected-preprocessing/sha256").resolve()):
            raise ValueError("Fitted JSON path escaped the intended authority store")
        preprocessing, source_ref = load_json(path, reference["sha256"], reference["bytes"])
        prior = preprocessing["prior"]["wave1FittedAuthority"]
        body = checked_fitted_body(prior)
        historical = fold["preprocessing"]["governedPriorTreatment"]
        historical_body = {key: value for key, value in historical.items() if key != "evidenceChecksum"}
        if sha(canonical(historical_body)) != historical["evidenceChecksum"]:
            raise ValueError("RF governed-prior receipt checksum differs")
        if (body["authorityId"] != historical["wave1AuthorityId"]
                or body["trainingStart"] != fold["trainStart"]
                or body["trainingEnd"] != fold["trainEnd"]
                or body["trainingRows"] != fold["trainRows"]
                or body["projectId"] != receipt["projectId"]
                or set(body["parameters"]) != set(historical["wave1Features"])):
            raise ValueError(f"Fold {number}: successor parameters lack exact original authority compatibility")
        reconstructed = copy.deepcopy(body)
        reconstructed["features"] = list(historical["wave1Features"])
        reconstructed["foldId"] = f"CORE_CHALLENGER_FOLD_{number}"
        reconstructed["rowsAfterTrainingCutoffExcluded"] = total_rows - fold["trainRows"]
        digest = sha(canonical(reconstructed))
        match = digest == historical["wave1FittedChecksum"]
        row = {
            "foldNumber": number, "status": "EXACT_HISTORICAL_CHECKSUM_MATCH" if match else "NOT_RECOVERED_CHECKSUM_MISMATCH",
            "historicalFittedId": historical["wave1FittedId"],
            "historicalFittedChecksum": historical["wave1FittedChecksum"],
            "reconstructedFittedChecksum": digest, "exactHistoricalChecksumMatch": match,
            "trainingStart": body["trainingStart"], "trainingEnd": body["trainingEnd"],
            "trainingRows": body["trainingRows"], "featureCount": len(reconstructed["features"]),
            "successorPreprocessingSource": source_ref, "successorFittedChecksum": prior["fittedChecksum"],
            "parameterBytesChanged": False, "parameterEstimationPerformed": False,
            "metadataChanges": {key: {"successor": body[key], "historical": reconstructed[key]}
                                for key in ("features", "foldId", "rowsAfterTrainingCutoffExcluded")
                                if body[key] != reconstructed[key]},
        }
        if match:
            recovered = {**reconstructed, "fittedChecksum": digest, "fittedId": historical["wave1FittedId"]}
            checked_fitted_body(recovered)
            file_sha = sha(canonical(recovered))
            row["recoveredAuthority"] = write_immutable(OUTPUT / f"objects/sha256/{file_sha}.json", recovered)
        else:
            row["reason"] = "Existing successor parameter body cannot reproduce original RF checksum; no approximation attempted"
        results.append(row)
    result = {
        "schemaVersion": "MLB_RF_HISTORICAL_V1_ZERO_FIT_RECOVERY_CHECK_V1",
        "candidateId": RF_CANDIDATE_ID, "rfOofSha256": RF_OOF_SHA,
        "status": "ALL_FIVE_V1_AUTHORITIES_RECOVERED_EXACTLY" if all(row["exactHistoricalChecksumMatch"] for row in results)
                  else "HISTORICAL_V1_RECOVERY_INCOMPLETE",
        "originalDevelopmentRows": total_rows, "folds": results,
        "sources": {"rfCandidateReceipt": receipt_ref, "acceptedV18Comparison": comparison_ref},
        "utility": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__).read_bytes())},
        "scope": "V1_PRIOR_ONLY_NOT_RF_ESTIMATOR_OR_COMPLETE_PREPROCESSOR_REPRODUCTION",
        "checksumDefinition": "Canonical entire fitted authority body, excluding fittedChecksum, fittedId and fitDurationMs; identical to original V1 implementation",
        "historicalFitDuration": "NOT_RECOVERED_NOT_INVENTED_NOT_PART_OF_AUTHORITY_CHECKSUM",
        "originalArtifactPhysicalBytesClaimed": False,
        "parameterEstimationCalls": 0, "modelFitCalls": 0, "sourceFrameReads": 0,
        "estimatorLoads": 0, "forecastTransforms": 0, "ootPayloadReads": 0,
        "providerCalls": 0, "aispActivity": False,
    }
    result_ref = write_immutable(OUTPUT / f"result-{sha(canonical(result))}.json", result)
    print(json.dumps({"status": result["status"], "folds": [
        {key: row[key] for key in ("foldNumber", "status", "historicalFittedChecksum", "reconstructedFittedChecksum")}
        for row in results], "result": result_ref}, indent=2))


if __name__ == "__main__":
    main()

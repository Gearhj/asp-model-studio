"""Inspect only the completed archetype study's fixed, verified receipts.

This replaces the incident's ad hoc exclusion-list summary. No CLI path is
accepted, embedded references are never followed, and nested objects are never
returned. This is an inspection convenience, not a filesystem access control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "outputs/mlb-pitcher-archetype-survival-v1"
RECEIPTS = {
    "workspace-preflight": ("workspace-preflight.json", "bc8b291f61bd98a2eaf4245c2d2589b9f205735f9eb5d770ba3541611c9ecf85", 5909),
    "declaration": ("declaration.json", "21cfc3edf23278f965030b1fc9a517d6e4a82523d048de9ad5a588237cb1ba27", 9865),
    "prospective-feasibility": ("prospective-feasibility.json", "619efe0425cec3c5ddbefb243c0c5ddda2bc9b64dd37a880aeb95c72f1190233", 2274),
    "profiles": ("objects/sha256/782f14f53dbe881d877f1ba9bcb62d5df68866bfba37061bc31210184216bf43/profiles.json", "782f14f53dbe881d877f1ba9bcb62d5df68866bfba37061bc31210184216bf43", 350060),
    "fit": ("objects/sha256/951a2b60c6d9bf2f4deeed8d4c6586afa7cdd8798f3dd7aa0c68001ddbadfd9c/fit.json", "951a2b60c6d9bf2f4deeed8d4c6586afa7cdd8798f3dd7aa0c68001ddbadfd9c", 10848),
    "assessment": ("objects/sha256/b8be226bfbc5622344cd6758d0203b0aaa3a91972162412b0cbe12a3477ff2e2/assessment.json", "b8be226bfbc5622344cd6758d0203b0aaa3a91972162412b0cbe12a3477ff2e2", 48560),
}
# Dotted paths select individual leaves; an object at a selected path is denied.
LEAVES = (
    "schema", "schemaVersion", "recordedAtUtc", "snapshotAtUtc", "startedAtUtc",
    "completedAtUtc", "frozenAtUtc", "createdAtUtc", "status", "startingHead",
    "branch", "head", "providerCalls", "providerRequests", "candidateForecasts",
    "newGameForecasts", "futureCandidateCohortDeclared", "existingStudiesChanged",
    "assessmentPredictionsOrOutcomesReadByThisStage",
    "assessmentOutcomeColumnsOpenedAtUtc", "fitsFrozenAtUtc",
    "physicallySeparateDevelopment.firstDate", "physicallySeparateDevelopment.lastDate",
    "physicallySeparateDevelopment.starts", "physicallySeparateDevelopment.eligibleStarts",
    "physicallySeparateDevelopment.permanentExcludedGamesPresent",
    "identityGate.nineQuarantinedGamesPresent", "identityGate.sealedEvaluationPayloadOpened",
    "qualification.rawProtectedOrSealedEvaluationArtifactOpened",
    "qualification.zeroProtectedParsedFieldExposureClaimPermitted",
)


def project_metadata(document: dict) -> dict:
    """Return allowlisted scalar leaves, without copying any nested payload."""
    result = {}
    for path in LEAVES:
        value = document
        for key in path.split("."):
            if not isinstance(value, dict) or key not in value:
                break
            value = value[key]
        else:
            if value is not None and type(value) not in (str, int, float, bool):
                raise ValueError("METADATA_LEAF_MUST_BE_SCALAR")
            result[path] = value
    return result


def inspect_receipt(name: str) -> dict:
    # Reject an unknown name before attempting any file operation.
    if name not in RECEIPTS:
        raise ValueError("ONLY_FIXED_ARCHETYPE_RECEIPTS_ALLOWED")
    relative, digest, size = RECEIPTS[name]
    path = STUDY / relative
    if not path.resolve().is_relative_to(STUDY.resolve()):
        raise ValueError("RECEIPT_RESOLVES_OUTSIDE_STUDY")
    raw = path.read_bytes()
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("FIXED_RECEIPT_BYTES_CHANGED")
    return {"receipt": name, "path": str(path), "sha256": digest,
            "bytes": size, "metadata": project_metadata(json.loads(raw))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", choices=sorted(RECEIPTS), required=True)
    args = parser.parse_args()
    print(json.dumps(inspect_receipt(args.receipt), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

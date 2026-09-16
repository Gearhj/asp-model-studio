"""Re-encode an immutable eligibility object for AISP; preserve every JSON value."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from server.sports_nfl_m1.paper_research_eligibility import (
    canonical_json_bytes, immutable_json, physical, require_physical,
    validate_evidence, verify_package,
)

ORIGINAL = "391240384408f975febde5c8ac369cd55a814c9d8bd652c4880e5be16aea7c9f"
EXPECTED = "7fac31dc0bec36ded4b363bc5e8b9bc4a4b8311fa5b671ab32f00820686ffa18"


def republish(exchange_root: Path, output_root: Path) -> dict:
    original = exchange_root / "nfl-labs-supplements/sha256" / ORIGINAL
    if {p.name for p in original.iterdir()} != {"manifest.json", "supplement.json"}:
        raise ValueError("Predecessor inventory differs")
    before = {name: physical(original / name) for name in ("manifest.json", "supplement.json")}
    raw = (original / "supplement.json").read_bytes()
    doc = json.loads(raw)
    old_manifest = json.loads((original / "manifest.json").read_bytes())
    old_identity = {k: v for k, v in old_manifest.items() if k != "supplementSha256"}
    if (old_manifest["supplementSha256"] != ORIGINAL
            or hashlib.sha256(canonical_json_bytes(old_identity)).hexdigest() != ORIGINAL):
        raise ValueError("Predecessor manifest identity differs")
    if old_manifest["artifacts"] != [{"file": "supplement.json", "sha256": before["supplement.json"]["sha256"], "bytes": len(raw)}]:
        raise ValueError("Predecessor supplement bytes differ from its manifest")
    legacy_bytes = json.dumps(doc, ensure_ascii=True, allow_nan=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
    if raw != legacy_bytes:
        raise ValueError("Predecessor does not match the diagnosed ASCII encoding")
    validate_evidence(doc)
    encoded = canonical_json_bytes(doc)
    # The expected digest is an assertion, never a substituted file identity.
    actual_sha = hashlib.sha256(encoded).hexdigest()
    if len(encoded) != 34047 or actual_sha != EXPECTED:
        raise ValueError(f"Investigate encoding result: {len(encoded)} bytes / {actual_sha}")
    if json.loads(encoded) != doc:
        raise ValueError("Parsed supplement changed")
    references = [doc["summaries"][k] for k in (
        "forecastBundle", "originalForecastBundle", "modelArtifact", "originalFeatureVector")]
    for ref in references:
        require_physical(ref)
    manifest = deepcopy(old_manifest)
    manifest.pop("supplementSha256")
    manifest["artifacts"] = [{"file": "supplement.json", "sha256": actual_sha, "bytes": len(encoded)}]
    address = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    manifest["supplementSha256"] = address
    destination = original.parent / address
    started = datetime.now(timezone.utc).isoformat()
    immutable_json(destination / "supplement.json", doc)
    immutable_json(destination / "manifest.json", manifest)
    completed = datetime.now(timezone.utc).isoformat()
    after_doc = verify_package(destination)
    if after_doc != doc or (destination / "supplement.json").read_bytes() != encoded:
        raise ValueError("Successor values or delivered bytes differ")
    for ref in [*references, *before.values()]:
        require_physical(ref)
    receipt = {
        "schemaVersion": "NFL_PAPER_ELIGIBILITY_ENCODING_SUCCESSOR_V1",
        "change": "ENCODING_ONLY_ENSURE_ASCII_FALSE_UTF8",
        "predecessorAddress": ORIGINAL, "predecessorFiles": before,
        "successorAddress": address,
        "successorFiles": {name: physical(destination / name) for name in before},
        "publicationStartedAtUtc": started, "publicationCompletedAtUtc": completed,
        "originalEvidencePublishedUtc": doc["publishedUtc"],
        "parsedSupplementExactlyUnchanged": True,
        "originalEvidenceAndForecastClocksPreserved": True,
        "originalFilesForecastsModelsUnchanged": True,
        "independentConsumerEncodingExpectedSha256": EXPECTED,
        "actualSupplementSha256": actual_sha, "actualSupplementBytes": len(encoded),
        "consumerImportAcknowledgement": "NOT_ESTABLISHED_FOR_SUCCESSOR",
        "providerRequests": 0, "modelExecutions": 0, "accountOperations": 0,
    }
    # Keep the consumer's exact two-file package inventory. The new publication
    # clocks and predecessor relationship belong to a separate immutable receipt.
    receipt_sha = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    receipt_ref = immutable_json(
        exchange_root / "aisp-daily-forecast-bundles/handoffs/sha256" / receipt_sha / "encoding-successor-receipt.json",
        receipt,
    )
    local = output_root / "sha256" / address
    immutable_json(local / "package/supplement.json", doc)
    immutable_json(local / "package/manifest.json", manifest)
    immutable_json(local / "publication-receipt.json", receipt)
    return {"successorAddress": address, "files": receipt["successorFiles"],
            "publicationReceipt": receipt_ref, "publicationCompletedAtUtc": completed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/nfl-paper-eligibility-utf8-successor-v1"))
    args = parser.parse_args()
    print(json.dumps(republish(args.exchange_root, args.output_root), ensure_ascii=False, indent=2))

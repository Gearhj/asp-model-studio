"""Publish the immutable MLB ensemble candidate into its isolated research exchange namespace."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/mlb-v18-ensemble-release-candidate-v1"
DESTINATION = Path(r"C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_ref(reference: dict) -> Path:
    path = Path(reference["path"]).resolve(strict=True)
    if digest(path) != reference["sha256"] or path.stat().st_size != int(reference["bytes"]):
        raise ValueError("Source reference checksum mismatch: " + str(path))
    return path


def references(value):
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"} <= set(value):
            yield value
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def immutable_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(target) != digest(source):
            raise ValueError("Immutable exchange collision: " + str(target))
        return
    with target.open("xb") as handle, source.open("rb") as incoming:
        shutil.copyfileobj(incoming, handle)


def atomic_json(path: Path, value: dict) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> None:
    if DESTINATION.resolve() != Path(r"C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1").resolve():
        raise ValueError("Only the isolated MLB ensemble research exchange namespace is allowed")
    current = json.loads((SOURCE / "current.json").read_text(encoding="utf-8"))
    queue = [current["package"], current["handoff"], current["manifest"], current["verification"]]
    seen: dict[str, dict] = {}
    dependencies: dict[str, dict] = {}
    while queue:
        reference = queue.pop()
        if reference["sha256"] in seen or reference["sha256"] in dependencies:
            continue
        path = verify_ref(reference)
        if path.is_relative_to(SOURCE.resolve()):
            seen[reference["sha256"]] = reference
            if path.suffix.lower() == ".json":
                try:
                    queue.extend(references(json.loads(path.read_text(encoding="utf-8"))))
                except json.JSONDecodeError:
                    pass
        else:
            dependencies[reference["sha256"]] = reference

    copied = []
    for checksum, reference in sorted(seen.items()):
        source = verify_ref(reference)
        target = DESTINATION / "objects/sha256" / checksum / source.name
        immutable_copy(source, target)
        copied.append({"relativePath": target.relative_to(DESTINATION).as_posix(),
                       "sha256": checksum, "bytes": target.stat().st_size})
    code = []
    package = json.loads(verify_ref(current["package"]).read_text(encoding="utf-8"))
    for name in ("script", "candidateModule", "replayAuthorityModule"):
        reference = package["runnable"][name]
        source = verify_ref(reference)
        target = DESTINATION / "code/sha256" / reference["sha256"] / source.name
        immutable_copy(source, target)
        code.append({"name": name, "relativePath": target.relative_to(DESTINATION).as_posix(),
                     "sha256": reference["sha256"], "bytes": target.stat().st_size})

    receipt = {
        "schemaVersion": "MLB_V18_ENSEMBLE_RESEARCH_EXCHANGE_PUBLICATION_V1",
        "candidateId": package["candidateId"], "packageSha256": current["package"]["sha256"],
        "handoffSha256": current["handoff"]["sha256"], "manifestSha256": current["manifest"]["sha256"],
        "objects": copied, "code": code, "externalDependencies": list(dependencies.values()),
        "researchShadowOnly": True, "promotionStatus": "NOT_PROMOTED",
        "executionAllowedInAISP": False, "wageringAuthority": False,
        "aispDatabaseWrites": 0, "officialV18PointersModified": 0,
    }
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    receipt_sha = hashlib.sha256(payload).hexdigest()
    receipt_target = DESTINATION / "objects/sha256" / receipt_sha / "publication-receipt.json"
    receipt_target.parent.mkdir(parents=True, exist_ok=True)
    if receipt_target.exists():
        if receipt_target.read_bytes() != payload:
            raise ValueError("Immutable publication receipt collision")
    else:
        with receipt_target.open("xb") as handle:
            handle.write(payload)
    exchange_current = {
        "schemaVersion": "MLB_V18_ENSEMBLE_RESEARCH_EXCHANGE_CURRENT_V1",
        "candidateId": package["candidateId"],
        "package": {"relativePath": next(x["relativePath"] for x in copied if x["sha256"] == current["package"]["sha256"]),
                    "sha256": current["package"]["sha256"], "bytes": current["package"]["bytes"]},
        "handoff": {"relativePath": next(x["relativePath"] for x in copied if x["sha256"] == current["handoff"]["sha256"]),
                    "sha256": current["handoff"]["sha256"], "bytes": current["handoff"]["bytes"]},
        "publicationReceipt": {"relativePath": receipt_target.relative_to(DESTINATION).as_posix(),
                               "sha256": receipt_sha, "bytes": len(payload)},
        "researchShadowOnly": True, "promotionStatus": "NOT_PROMOTED",
        "executionAllowedInAISP": False, "wageringAuthority": False,
    }
    atomic_json(DESTINATION / "current.json", exchange_current)
    print(json.dumps({"status": "EXPORTED", "destination": str(DESTINATION),
                      "candidateId": package["candidateId"], "objects": len(copied),
                      "codeFiles": len(code), "publicationReceipt": exchange_current["publicationReceipt"]}, indent=2))


if __name__ == "__main__":
    main()

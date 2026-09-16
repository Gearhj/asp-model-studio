"""Export the transition research package to its isolated model-exchange namespace."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"
DESTINATION = Path(r"C:\Users\james\asp-model-exchange\mlb-v18-transition-shrinkage-v1")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(reference: dict) -> Path:
    path = Path(reference["path"]).resolve(strict=True)
    if sha(path) != reference["sha256"] or path.stat().st_size != int(reference["bytes"]):
        raise ValueError(f"Reference differs: {path}")
    return path


def copy_immutable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha(target) != sha(source):
            raise ValueError(f"Immutable exchange conflict: {target}")
        return
    with target.open("xb") as destination, source.open("rb") as incoming:
        shutil.copyfileobj(incoming, destination)


def atomic_json(path: Path, value: dict) -> None:
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, prefix=path.name+".", suffix=".tmp") as stream:
        stream.write(raw)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def main() -> None:
    if DESTINATION.resolve() != Path(r"C:\Users\james\asp-model-exchange\mlb-v18-transition-shrinkage-v1").resolve():
        raise ValueError("Only the isolated transition research namespace is allowed")
    current = json.loads((SOURCE / "current.json").read_text(encoding="utf-8"))
    handoff = json.loads(verify(current["handoff"]).read_text(encoding="utf-8"))
    references = [current[name] for name in ("package", "handoff", "forecastIndex", "decisionNote",
                                                "prospectivePair", "component", "result", "manifest", "population")]
    references.append(handoff["protocol"])
    references.extend(handoff.get("supplementary", {}).values())
    objects = []
    for reference in references:
        source = verify(reference)
        if not source.is_relative_to(SOURCE.resolve()):
            raise ValueError("Package object outside isolated source namespace")
        target = DESTINATION / "objects/sha256" / reference["sha256"] / source.name
        copy_immutable(source, target)
        objects.append({"name": source.name, "relativePath": target.relative_to(DESTINATION).as_posix(),
                        "sha256": reference["sha256"], "bytes": reference["bytes"]})
    code = []
    for reference in handoff["code"]:
        source = verify(reference)
        if not source.is_relative_to(ROOT.resolve()):
            raise ValueError("Runnable source outside Model Studio")
        target = DESTINATION / "code/sha256" / reference["sha256"] / source.name
        copy_immutable(source, target)
        code.append({"name": source.name, "relativePath": target.relative_to(DESTINATION).as_posix(),
                     "sha256": reference["sha256"], "bytes": reference["bytes"]})
    adapter = None
    adapter_index_ref = handoff.get("supplementary", {}).get("adapterEnvelopeIndex")
    if adapter_index_ref:
        adapter_index = json.loads(verify(adapter_index_ref).read_text(encoding="utf-8"))
        for reference in adapter_index["artifacts"]:
            source = verify(reference)
            source_root = (SOURCE / "adapter-v2").resolve()
            if not source.is_relative_to(source_root):
                raise ValueError("Adapter artifact outside isolated adapter namespace")
            target = DESTINATION / "adapter-v2" / source.relative_to(source_root)
            copy_immutable(source, target)
        source_handoff = verify(adapter_index["handoff"])
        destination_handoff = DESTINATION / "adapter-v2" / source_handoff.relative_to((SOURCE / "adapter-v2").resolve())
        adapter = {"path": str(destination_handoff), "sha256": adapter_index["handoff"]["sha256"],
                   "bytes": adapter_index["handoff"]["bytes"],
                   "consumerImplementationStatus": "PENDING_CLAUDE_V2_TRANSITION_ROLE", "importConfirmed": False}
    receipt = {
        "schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_EXCHANGE_PUBLICATION_V1",
        "componentId": handoff["componentId"], "verdict": handoff["verdict"],
        "handoffSha256": current["handoff"]["sha256"], "objects": objects, "code": code,
        "runnableCommand": handoff["runnableCommand"], "contractExtensionRequired": True,
        "adapterHandoff": adapter,
        "researchShadowOnly": True, "candidateAuthority": False,
        "executionAllowedInAisp": False, "wageringAuthority": False,
        "aispWrites": 0, "officialV18PointersModified": 0,
    }
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    receipt_path = DESTINATION / f"objects/sha256/{digest}/publication-receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        if receipt_path.read_bytes() != raw:
            raise ValueError("Publication receipt conflict")
    else:
        with receipt_path.open("xb") as stream:
            stream.write(raw)
    by_sha = {row["sha256"]: row for row in objects}
    exchange_current = {
        "schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_EXCHANGE_CURRENT_V1",
        "componentId": handoff["componentId"], "verdict": handoff["verdict"],
        "handoff": by_sha[current["handoff"]["sha256"]],
        "package": by_sha[current["package"]["sha256"]],
        "forecastIndex": by_sha[current["forecastIndex"]["sha256"]],
        "decisionNote": by_sha[current["decisionNote"]["sha256"]],
        "prospectivePair": by_sha[current["prospectivePair"]["sha256"]],
        "component": by_sha[current["component"]["sha256"]],
        "publicationReceipt": {"relativePath": receipt_path.relative_to(DESTINATION).as_posix(),
                               "sha256": digest, "bytes": len(raw)},
        "runnableCommand": handoff["runnableCommand"],
        "adapterHandoff": adapter,
        "contractExtensionRequired": True,
        "researchShadowOnly": True, "candidateAuthority": False,
        "executionAllowedInAisp": False, "wageringAuthority": False,
    }
    atomic_json(DESTINATION / "current.json", exchange_current)
    print(json.dumps({"status": "EXPORTED", "destination": str(DESTINATION),
                      "handoff": exchange_current["handoff"],
                      "publicationReceipt": exchange_current["publicationReceipt"]}, indent=2))


if __name__ == "__main__":
    main()

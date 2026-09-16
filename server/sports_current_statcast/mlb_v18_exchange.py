"""Append-only export of precomputed current V18 research packages.

No AISP import, provider request, model reload or inference occurs here.
The default is a read-only plan; callers must opt in to the exchange write.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from . import mlb_v18_current_publication as publication

DEFAULT_EXCHANGE_ROOT = Path("C:/Users/james/asp-model-exchange/mlb-v18-current")
SCHEMA = "MLB_V18_PRECOMPUTED_EXCHANGE_PACKAGE_V1"


def _read(reference):
    actual = publication.reference(reference["path"])
    if any(actual[key] != reference[key] for key in ("sha256", "bytes")):
        raise ValueError("V18_EXCHANGE_SOURCE_CHECKSUM_MISMATCH")
    return json.loads(Path(reference["path"]).read_text(encoding="utf-8"))


def _child(root, relative):
    relative = str(relative)
    parts = PurePosixPath(relative).parts
    if not parts or "\\" in relative or ":" in relative or PurePosixPath(relative).is_absolute() or any(p in {".", ".."} for p in parts):
        raise ValueError("V18_EXCHANGE_UNSAFE_RELATIVE_PATH")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("V18_EXCHANGE_CHILD_ESCAPES_ROOT")
    return result


def _research(value):
    for key, expected in publication.daily.RESEARCH_FLAGS.items():
        if value.get(key) != expected:
            raise ValueError("V18_EXCHANGE_RESEARCH_AUTHORITY_MISMATCH")


def _logical(value, prefix):
    digest = value.get(prefix + "Sha256")
    body = {k: v for k, v in value.items() if k not in {prefix + "Sha256", prefix + "Id"}}
    if publication.daily.sha_json(body) != digest:
        raise ValueError("V18_EXCHANGE_LOGICAL_CHECKSUM_MISMATCH")
    return digest


def _accounting_identity(receipt):
    """Full slate dispositions, excluding per-invocation execution evidence.

    Tick receipts and changed evidence references remain in Studio. Stable
    published objects plus the same disposition/reason for every game do not
    require another physical copy of the forecasts in Model Exchange.
    """
    rows = [{"gameId": g["gameId"], "status": g["status"],
             "objectSha256": g.get("objectSha256"),
             "reason": g.get("reason") or g.get("error"),
             "blockers": publication._source_identity(g.get("blockers", []))}
            for g in sorted(receipt["games"], key=lambda g: g["gameId"])]
    return publication.daily.sha_json({"slateDate": receipt["slateDate"], "games": rows,
        "gamesDiscovered": receipt["gamesDiscovered"], "gamesSkipped": receipt["gamesSkipped"],
        "gamesFailed": receipt.get("gamesFailed", 0), "handoffForecasts": receipt.get("handoffForecasts")})


def _package_result(manifest, descriptor, *, publish, reused):
    return {"packageRoot": str(Path(descriptor["path"]).parent),
            "packageContentSha256": manifest["packageContentSha256"], "manifest": descriptor,
            **{key: manifest[key] for key in ("handoff", "receipt", "importable", "importCommand", "importInstruction", "forecastCount", "gameCount")},
            "fileCount": len(manifest["files"]), "published": bool(publish), "reused": reused,
            "executionCount": 0, "aispWrites": 0, "providerCalls": 0}


def _reuse_index(index_path, exchange_root, handoff_ref, accounting_sha, *, publish):
    index = json.loads(index_path.read_text(encoding="utf-8"))
    descriptor = index["manifest"]
    manifest_path = Path(descriptor["path"]).resolve()
    if not manifest_path.is_relative_to(exchange_root / "sha256"):
        raise ValueError("V18_EXCHANGE_INDEX_OUTSIDE_PACKAGE_ROOT")
    manifest = _read(descriptor)
    _research(manifest)
    package_root = manifest_path.parent
    if (package_root.name != manifest["packageContentSha256"]
            or publication.daily.sha_json(manifest["identityPayload"]) != package_root.name
            or manifest["identityPayload"]["files"] != [{k: r[k] for k in ("relativePath", "sha256", "bytes")} for r in manifest["files"]]
            or index.get("accountingSha256") != accounting_sha
            or index.get("sourceHandoff") != manifest["sourceHandoff"]
            or index.get("sourceReceipt") != manifest["sourceReceipt"]
            or manifest["sourceHandoff"]["sha256"] != handoff_ref["sha256"]):
        raise ValueError("V18_EXCHANGE_INDEX_BINDING_MISMATCH")
    for item in manifest["files"]:
        actual = publication.reference(_child(package_root, item["relativePath"]))
        if any(actual[k] != item[k] for k in ("sha256", "bytes")):
            raise ValueError("V18_EXCHANGE_IMMUTABLE_CHILD_CONFLICT")
    if any(not Path(manifest[key]["path"]).resolve().is_relative_to(package_root) for key in ("handoff", "receipt")):
        raise ValueError("V18_EXCHANGE_INDEX_DESCRIPTOR_ESCAPES_PACKAGE")
    copied_handoff = _read(manifest["handoff"])
    copied_receipt = _read(manifest["receipt"])
    if (manifest["handoff"]["sha256"] != handoff_ref["sha256"]
            or _accounting_identity(copied_receipt) != accounting_sha
            or copied_receipt["handoffSha256"] != copied_handoff["handoffSha256"]):
        raise ValueError("V18_EXCHANGE_INDEX_ACCOUNTING_MISMATCH")
    # Return the original package's source/receipt identities, never the newly
    # validated tick receipt as if its bytes were inside this older package.
    return _package_result(manifest, descriptor, publish=publish, reused=True)


def export_current_handoff(handoff_ref, receipt_ref, *, exchange_root=DEFAULT_EXCHANGE_ROOT, publish=False):
    """Validate/plan, or atomically export, a handoff plus its import receipt.

    Returns packageRoot, manifest descriptor, handoff/receipt descriptors,
    importable, importCommand and published/reused flags. With publish=False no
    output directories are created; returned descriptors describe planned bytes.
    Empty forecasts are exported as accounting only and have no import command.
    Original execution JSON retains absolute source feature-snapshot paths; the
    same snapshot bytes are also copied into their package-relative locations.
    Unchanged handoff bytes and full-slate accounting reuse the first verified
    exchange package and its original receipt; new tick receipts stay in Studio.
    """
    handoff, receipt = _read(handoff_ref), _read(receipt_ref)
    _research(handoff)
    _research(receipt)
    handoff_sha, receipt_sha = _logical(handoff, "handoff"), _logical(receipt, "receipt")
    handoff_path = Path(handoff_ref["path"]).resolve()
    # This exact four-level layout is required by the existing AISP importer.
    root = handoff_path.parents[3]
    handoff_relative = f"handoffs/sha256/{handoff_sha}/aisp-handoff.json"
    receipt_relative = f"slates/{handoff['slateDate']}/sha256/{receipt_sha}/slate-result.json"
    if handoff_path != _child(root, handoff_relative) or Path(receipt_ref["path"]).resolve() != _child(root, receipt_relative):
        raise ValueError("V18_EXCHANGE_IMPORT_LAYOUT_MISMATCH")
    if handoff.get("schemaVersion") != publication.daily.HANDOFF_SCHEMA:
        raise ValueError("V18_EXCHANGE_ONLY_CURRENT_V1_HANDOFF_SUPPORTED")
    if receipt.get("schemaVersion") != publication.daily.RECEIPT_SCHEMA or receipt.get("handoffSha256") != handoff_sha or receipt.get("slateDate") != handoff.get("slateDate"):
        raise ValueError("V18_EXCHANGE_RECEIPT_BINDING_MISMATCH")
    forecasts = handoff.get("forecasts")
    games = receipt.get("games")
    if not isinstance(forecasts, list) or not isinstance(games, list):
        raise ValueError("V18_EXCHANGE_SLATE_ACCOUNTING_REQUIRED")
    published_pairs = {(str(g["gameId"]), g["objectSha256"]) for g in games if g["status"] == "PUBLISHED"}
    forecast_pairs = {(str(g["gameId"]), g["objectSha256"]) for g in forecasts}
    if published_pairs != forecast_pairs or len(forecast_pairs) != len(forecasts) or len({g["gameId"] for g in forecasts}) != len(forecasts):
        raise ValueError("V18_EXCHANGE_FORECAST_ACCOUNTING_MISMATCH")
    if len({g["gameId"] for g in games}) != len(games) or receipt.get("gamesDiscovered") != len(games):
        raise ValueError("V18_EXCHANGE_DUPLICATE_OR_UNACCOUNTED_GAME")
    if receipt.get("gamesSkipped") != sum(g["status"] == "SKIPPED" for g in games):
        raise ValueError("V18_EXCHANGE_SKIP_COUNT_MISMATCH")
    files = {}

    def add(path, expected=None):
        path = Path(path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("V18_EXCHANGE_SOURCE_CHILD_OUTSIDE_OUTPUT_ROOT")
        relative = path.relative_to(root).as_posix()
        _child(root, relative)
        actual = publication.reference(path)
        if expected and any(actual[k] != expected[k] for k in ("sha256", "bytes")):
            raise ValueError("V18_EXCHANGE_CHILD_CHECKSUM_MISMATCH")
        record = {"relativePath": relative, "sourcePath": str(path), "sha256": actual["sha256"], "bytes": actual["bytes"]}
        if relative in files and files[relative] != record:
            raise ValueError("V18_EXCHANGE_CONFLICTING_CHILD_BINDING")
        files[relative] = record

    add(handoff_path, handoff_ref)
    add(receipt_ref["path"], receipt_ref)
    for entry in forecasts:
        directory = _child(root, entry["relativePath"])
        if directory.name != entry["objectSha256"] or entry.get("manifestFile") != "manifest.json" or entry.get("forecastFile") != "forecast.json":
            raise ValueError("V18_EXCHANGE_FORECAST_PATH_BINDING_MISMATCH")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        _research(manifest)
        # Bound and hash every child before calling the existing verifier, whose
        # original implementation assumes its internal pointers are trusted.
        add(directory / "manifest.json", entry.get("manifest"))
        required = {"forecast.json", "pregame-evidence.json", "execution-inputs.json", "representative-path.json"}
        for child in manifest.get("artifacts", []):
            add(_child(directory, child["relativePath"]), child)
            required.discard(child["relativePath"])
        if required:
            raise ValueError("V18_EXCHANGE_REQUIRED_CHILD_MISSING")
        if entry.get("childBindings") is not None and entry["childBindings"] != manifest["artifacts"]:
            raise ValueError("V18_EXCHANGE_CHILD_BINDINGS_DIFFER")
        execution = json.loads((directory / "execution-inputs.json").read_text(encoding="utf-8"))
        snapshot = execution["featureSnapshot"]
        if Path(snapshot["path"]).name != "feature-snapshot.json":
            raise ValueError("V18_EXCHANGE_EXPECTED_CURRENT_FEATURE_SNAPSHOT")
        # Bound the absolute pointer before the existing verifier follows it.
        add(snapshot["path"], snapshot)
        _, forecast = publication._verified_forecast(root, entry)
        _research(forecast)
        if forecast["gameId"] != entry["gameId"] or manifest["gameId"] != entry["gameId"]:
            raise ValueError("V18_EXCHANGE_EVENT_BINDING_MISMATCH")
        if entry.get("featureSnapshot") is not None and entry["featureSnapshot"] != snapshot:
            raise ValueError("V18_EXCHANGE_FEATURE_BINDING_MISMATCH")
        if entry.get("playGeometry") or entry.get("populationGeometry"):
            raise ValueError("V18_EXCHANGE_VIEW_SUPPLEMENT_EXPORT_NOT_SUPPORTED")
    # Skip evidence is independently useful even when there is no forecast.
    for game in games:
        for key in ("featureSnapshot", "receipt"):
            if game.get(key):
                descriptor = game[key]
                if Path(descriptor["path"]).suffix != ".json":
                    raise ValueError("V18_EXCHANGE_EXPECTED_JSON_SKIP_EVIDENCE")
                add(descriptor["path"], descriptor)
    exchange_root = Path(exchange_root).resolve()
    accounting_sha = _accounting_identity(receipt)
    index_path = exchange_root / "handoff-keys" / handoff_ref["sha256"] / (accounting_sha + ".json")
    if index_path.exists():
        return _reuse_index(index_path, exchange_root, handoff_ref, accounting_sha, publish=publish)
    ordered = sorted(files.values(), key=lambda r: r["relativePath"])
    identity = {"schemaVersion": SCHEMA, "handoffSha256": handoff_sha, "receiptSha256": receipt_sha,
                "files": [{k: r[k] for k in ("relativePath", "sha256", "bytes")} for r in ordered]}
    package_sha = publication.daily.sha_json(identity)
    package_root = exchange_root / "sha256" / package_sha
    importable = bool(forecasts)
    copied_handoff = {**handoff_ref, "path": str(package_root / handoff_relative), "outputRoot": str(package_root)}
    copied_receipt = {**receipt_ref, "path": str(package_root / receipt_relative)}
    command = (f'python -m scripts.mlb_v18_daily_slate import --handoff "{copied_handoff["path"]}" '
               f'--receipt "{copied_receipt["path"]}"') if importable else None
    instruction = ("In AISP's server environment, verify the package manifest and all child bytes, then run " + command +
                   ". Import only precomputed V18 as a separate RESEARCH_SHADOW track beside Gen1; do not execute/refit V18, change Gen1 or official policy, create decisions/positions, or grant wagering/promotion authority. "
                   "Map forecast availability to forecastCreatedAt and evidence cutoff to capturedAt, requiring capturedAt <= forecastCreatedAt < scheduledStart; preserve original source clocks. Repeat the import to verify idempotency.") if importable else (
                   "Accounting-only package: no forecasts. Do not invoke AISP's forecast importer, which rejects empty handoffs. Retain the explicit game skips and wait for a prospective forecast handoff.")
    manifest = {"schemaVersion": SCHEMA, "packageContentSha256": package_sha, "identityPayload": identity,
                "sourceHandoff": handoff_ref, "sourceReceipt": receipt_ref, "files": ordered,
                "handoff": copied_handoff, "receipt": copied_receipt, "importable": importable,
                "importCommand": command, "importInstruction": instruction,
                "forecastCount": len(forecasts), "gameCount": len(games),
                "status": "RESEARCH_SHADOW" if importable else "RESEARCH_ACCOUNTING_ONLY_NO_FORECASTS",
                "absoluteExecutionReferencesPreserved": True,
                "portability": "Copied feature snapshots have package-relative locations in files. Immutable execution JSON retains original local absolute paths; a relocated consumer must resolve those through this manifest without rewriting originals.",
                "executionCount": 0, "aispWrites": 0, "providerCalls": 0, **publication.daily.RESEARCH_FLAGS}
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    manifest_ref = {"path": str(package_root / "exchange-package.json"), "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
    reused = False

    def verify_destination():
        if (package_root / "exchange-package.json").read_bytes() != blob:
            raise ValueError("V18_EXCHANGE_IMMUTABLE_MANIFEST_CONFLICT")
        for item in ordered:
            actual = publication.reference(_child(package_root, item["relativePath"]))
            if any(actual[k] != item[k] for k in ("sha256", "bytes")):
                raise ValueError("V18_EXCHANGE_IMMUTABLE_CHILD_CONFLICT")

    if publish:
        if package_root.exists():
            verify_destination()
            reused = True
        else:
            stage_root = exchange_root / ".staging"
            stage_root.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix="v18-export-", dir=stage_root))
            try:
                for item in ordered:
                    destination = _child(stage, item["relativePath"])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item["sourcePath"], destination)
                    actual = publication.reference(destination)
                    if any(actual[k] != item[k] for k in ("sha256", "bytes")):
                        raise ValueError("V18_EXCHANGE_SOURCE_CHANGED_DURING_COPY")
                (stage / "exchange-package.json").write_bytes(blob)
                package_root.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.rename(stage, package_root)
                except FileExistsError:
                    verify_destination()
                    reused = True
            finally:
                if stage.exists():
                    if not stage.resolve().is_relative_to(stage_root.resolve()) or stage == stage_root:
                        raise ValueError("V18_EXCHANGE_STAGING_SCOPE_INVALID")
                    shutil.rmtree(stage)
            verify_destination()
        index = {"schemaVersion": "MLB_V18_EXCHANGE_HANDOFF_INDEX_V1", "accountingSha256": accounting_sha,
                 "sourceHandoff": handoff_ref, "sourceReceipt": receipt_ref, "manifest": manifest_ref}
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_blob = json.dumps(index, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(prefix=".index-", dir=index_path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(index_blob)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Hard-link installation is atomic and refuses an existing
                # destination on both Windows and POSIX; no index is replaced.
                os.link(temporary, index_path)
            except FileExistsError:
                return _reuse_index(index_path, exchange_root, handoff_ref, accounting_sha, publish=publish)
        finally:
            if temporary.exists():
                temporary.unlink()
    return _package_result(manifest, manifest_ref, publish=publish, reused=reused)

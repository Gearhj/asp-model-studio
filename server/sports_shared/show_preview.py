"""Immutable editorial derivatives. No inference, source acquisition or consumer writes.

Sources are admitted by sport adapters, never by changing their horizon. The
consumer's unmodified, hash-pinned pure validator runs before discovery changes.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import uuid
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
SCHEMA = "AISP_SHOW_PREVIEW_FORECAST_V1"
CONFIG = "MULTISPORT_SHOW_PREVIEW_EXACT_SOURCE_REUSE_V1"
TREE = "show-preview-forecasts-v1"
AUTHORITY = {"research_only": True, "editorial_only": True,
             "grants_wagering_authority": False, "final_pregame_evidence": False,
             "model_promotion_allowed": False, "position_selection_allowed": False,
             "stake_selection_allowed": False, "scheduler_authority": False}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(UTC)


def iso(value):
    return utc(value).isoformat().replace("+00:00", "Z")


def clocks(slate):
    day = date.fromisoformat(slate) - timedelta(days=1)
    return {key: iso(datetime.combine(day, time(hour, minute), NY))
            for key, hour, minute in [("identify_utc", 15, 0), ("resolve_utc", 15, 15),
                                     ("publish_by_utc", 16, 0), ("freeze_utc", 16, 30),
                                     ("recording_utc", 17, 0)]}


def physical(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": digest(raw), "bytes": len(raw)}


def checked_file(ref):
    raw = Path(ref["path"]).read_bytes()
    if len(raw) != ref["bytes"] or digest(raw) != ref["sha256"]:
        raise ValueError("source physical bytes changed: " + ref["path"])
    return raw


def contained(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe relative exchange path")
    result = Path(root) / path
    if not result.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("exchange path escapes root")
    return result


def immutable(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("immutable conflict: " + str(path))
        return
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def consumer_validator(path, sha):
    """Load only the inspected pure contract module, without app/db imports."""
    path = Path(path)
    if digest(path.read_bytes()) != sha:
        raise ValueError("consumer validator revision changed; inspect successor before using it")
    name = "asp_show_preview_consumer_" + sha
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        old = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = old
    return sys.modules[name].validate_forecast


def validate_source(source, now):
    if source["sport"] not in ("MLB", "NFL", "NBA", "CFB"):
        raise ValueError("unsupported sport")
    if source["source_schema"] == SCHEMA or source.get("source_horizon") == "SHOW_PREVIEW":
        raise ValueError("preview cannot masquerade as an original source")
    kickoff = utc(source["game"]["kickoff_utc"])
    if source["game"]["slate_date"] != kickoff.astimezone(NY).date().isoformat():
        raise ValueError("Eastern slate identity mismatch")
    if source["game"]["away"]["abbreviation"] == source["game"]["home"]["abbreviation"]:
        raise ValueError("home/away identity collision")
    cut, created, available = map(utc, (source["source_cutoff_utc"], source["source_created_utc"], source["source_available_utc"]))
    if not cut <= created <= available <= utc(now) < kickoff:
        raise ValueError("source not genuinely available before preview creation")
    if source["sport"] == "MLB" and source.get("preview_evidence_certified") is not True:
        raise ValueError("MLB_PREVIEW_FEATURE_AND_LINEUP_AUTHORITY_UNAVAILABLE")
    for ref in source["files"]:
        checked_file(ref)
    from .show_preview_sources import verify_source_outputs
    verify_source_outputs(source)
    if not source.get("limitations"):
        raise ValueError("preview limitations must be explicit")
    for side in ("away", "home"):
        team = source["team_evidence"][side]
        for field in ("starter_status", "lineup_status"):
            if team[field] not in ("CONFIRMED", "PROBABLE", "UNKNOWN", "NOT_APPLICABLE"):
                raise ValueError("invalid team evidence status")
        if "UNKNOWN" in (team["starter_status"], team["lineup_status"]) and not team["missing_evidence"]:
            raise ValueError("unknown inputs require missing-evidence disclosure")


def source_key(source):
    # Changing evidence/schedule/config produces a successor; wall clocks do not
    # force an otherwise unchanged forecast to be regenerated or restamped.
    stable = {k: v for k, v in source.items() if k != "availability_proof"}
    return digest(canonical({"configuration": CONFIG, "source": stable}))


def build_preview(source, created, published, predecessor=None):
    validate_source(source, created)
    schedule = clocks(source["game"]["slate_date"])
    if not utc(created) <= utc(published) <= utc(schedule["publish_by_utc"]):
        raise ValueError("PREVIEW_DEADLINE_MISSED")
    src = {"forecast_id": source["source_forecast_id"], "schema": source["source_schema"],
           "horizon": source["source_horizon"], "forecast_sha256": source["source_forecast_sha256"],
           "source_cutoff_utc": source["source_cutoff_utc"], "created_utc": source["source_created_utc"],
           "available_utc": source["source_available_utc"], "publication_utc": source.get("source_publication_utc"),
           "files": source["files"], "availability_proof": source["availability_proof"],
           "prediction_reused": True, "simulation_reused": source["simulation"]["draw_count"] > 0,
           "regenerated": False}
    doc = {"schema_version": SCHEMA, "horizon": "SHOW_PREVIEW", "sport": source["sport"],
           "league": source["league"], "season": str(source["season"]), "game": source["game"],
           "created_utc": iso(created), "publication_utc": iso(published),
           "source_cutoff_utc": source["source_cutoff_utc"], "intended_show_board_freeze_utc": schedule["freeze_utc"],
           "production_clock": schedule, "configuration": CONFIG, "model": source["model"],
           "feature_contract": source["feature_contract"], "simulation": source["simulation"],
           "expected_score": source["expected_score"], "probabilities": source["probabilities"],
           "probability_units": "FRACTIONS_0_TO_1", "distribution": source["distribution"],
           "forecast_output_semantics": source["forecast_output_semantics"],
           "availability": source["availability"], "team_evidence": source["team_evidence"],
           "missing_evidence": source["missing_evidence"], "limitations": source["limitations"],
           "support_classification": "EARLY_RESEARCH_EXACT_SOURCE_REUSE",
           "authority": AUTHORITY, "derivation": src, "source_binding_key": source_key(source),
           "predecessor_forecast_id": predecessor}
    doc["forecast_id"] = "asp-show-preview:sha256:" + digest(canonical(doc))
    doc["integrity"] = {"content_sha256": digest(canonical(doc)), "physical_files": []}
    return doc


def validate_document(doc, validator, now):
    validator(doc, now=utc(now))
    if doc.get("configuration") != CONFIG or not doc.get("derivation", {}).get("prediction_reused"):
        raise ValueError("RELABELLED_SOURCE_WITHOUT_PREVIEW_DERIVATION")
    if doc["authority"] != AUTHORITY:
        raise ValueError("preview authority differs")
    if doc["forecast_id"] == doc["derivation"]["forecast_id"] or doc["derivation"]["regenerated"]:
        raise ValueError("source forecast identity reused or regenerated")
    body = {k: v for k, v in doc.items() if k not in ("forecast_id", "integrity")}
    if doc["forecast_id"] != "asp-show-preview:sha256:" + digest(canonical(body)):
        raise ValueError("preview forecast identity mismatch")
    if clocks(doc["game"]["slate_date"]) != doc["production_clock"]:
        raise ValueError("preview clock mismatch")
    if not utc(doc["created_utc"]) <= utc(doc["publication_utc"]) <= utc(doc["production_clock"]["publish_by_utc"]):
        raise ValueError("PREVIEW_DEADLINE_MISSED")
    for field in doc["probabilities"].values():
        if isinstance(field, bool) or not math.isfinite(field):
            raise ValueError("invalid finite probability")
    if abs(sum(doc["probabilities"].values()) - 1) > 1e-10:
        raise ValueError("probability mass mismatch")
    if not re.fullmatch("[0-9a-f]{64}", doc["model"]["artifact_sha256"]):
        raise ValueError("invalid model hash")
    for value in doc["expected_score"].values():
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid score")


def verify_package(directory, validator, now=None):
    directory = Path(directory)
    raw = (directory / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    if directory.name != digest(raw):
        raise ValueError("package address is physical manifest hash")
    for item in manifest["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe package member")
        checked_file({**item, "path": str(contained(directory, relative))})
    doc = json.loads((directory / "forecast.json").read_bytes())
    validate_document(doc, validator, now or datetime.now(UTC))
    source = json.loads((directory / "source-binding.json").read_bytes())
    # Revalidate local original objects; then derive the entire document again.
    validate_source(source, doc["created_utc"])
    replay = build_preview(source, doc["created_utc"], doc["publication_utc"], doc["predecessor_forecast_id"])
    replay["integrity"]["physical_files"] = doc["integrity"]["physical_files"]
    if canonical(replay) != (directory / "forecast.json").read_bytes():
        raise ValueError("exact derivation replay differs")
    if doc["integrity"]["physical_files"] != [r for r in manifest["files"] if r["path"] != "forecast.json"]:
        raise ValueError("integrity member inventory differs")
    return doc


@contextmanager
def publication_lock(root):
    # No timed stealing. A crash requires inspecting this dedicated lock.
    path = root / "publication.lock"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, canonical({"pid": os.getpid(), "created_utc": iso(datetime.now(UTC))}))
        os.close(fd)
        yield
    finally:
        path.unlink()


def publish(sources, exchange_root, validator, *, now_fn=lambda: datetime.now(UTC)):
    root = Path(exchange_root).resolve() / TREE
    root.mkdir(parents=True, exist_ok=True)
    started = now_fn()
    with publication_lock(root):
        pointer = root / "discovery.json"
        prior_raw = pointer.read_bytes() if pointer.exists() else None
        prior = json.loads(prior_raw) if prior_raw else {"packages": []}
        if prior_raw and (root / "indexes/sha256" / (digest(prior_raw)+".json")).read_bytes() != prior_raw:
            raise ValueError("discovery history binding differs")
        entries = list(prior["packages"])
        results = []
        for source in sources:
            key = source_key(source)
            same = next((e for e in entries if e["source_binding_key"] == key), None)
            if same:
                verify_package(contained(root, same["package_path"]), validator, now_fn())
                results.append({**same, "disposition": "REUSED_BYTE_IDENTICAL"})
                continue
            moment = now_fn()
            if utc(moment) > utc(clocks(source["game"]["slate_date"])["publish_by_utc"]):
                results.append({"sport": source["sport"], "game": source["game"], "disposition": "PREVIEW_DEADLINE_MISSED"})
                continue
            older = [e for e in entries if e["sport"] == source["sport"] and e["source_game_ref"] == source["game"]["source_game_ref"]]
            predecessor = older[-1]["forecast_id"] if older else None
            doc = build_preview(source, moment, now_fn(), predecessor)
            payloads = {"source-binding.json": canonical(source)}
            # Exact source forecast/population bytes, with no new draws.
            for number, ref in enumerate(source["files"]):
                payloads[f"source-{number}{Path(ref['path']).suffix}"] = checked_file(ref)
            members = [{"path": name, "sha256": digest(raw), "bytes": len(raw)} for name, raw in sorted(payloads.items())]
            doc["integrity"]["physical_files"] = members
            validate_document(doc, validator, now_fn())
            payloads["forecast.json"] = canonical(doc)
            members = sorted(members + [{"path": "forecast.json", "sha256": digest(payloads["forecast.json"]), "bytes": len(payloads["forecast.json"])}], key=lambda x: x["path"])
            manifest = {"schema_version": "ASP_SHOW_PREVIEW_PACKAGE_V1", "forecast_id": doc["forecast_id"],
                        "content_sha256": doc["integrity"]["content_sha256"], "files": members}
            manifest_raw = canonical(manifest)
            address = digest(manifest_raw)
            parent = root / "sha256"
            parent.mkdir(exist_ok=True)
            stage = root / (".staging-" + uuid.uuid4().hex)
            stage.mkdir()
            checked = stage / address
            checked.mkdir()
            for name, raw in payloads.items():
                immutable(checked / name, raw)
            immutable(checked / "manifest.json", manifest_raw)
            verify_package(checked, validator, now_fn())
            if utc(now_fn()) > utc(doc["production_clock"]["publish_by_utc"]):
                raise ValueError("PREVIEW_DEADLINE_MISSED_DURING_VERIFICATION; discovery unchanged")
            os.rename(checked, parent / address)
            stage.rmdir()
            completed = iso(now_fn())
            if utc(completed) > utc(doc["production_clock"]["publish_by_utc"]):
                raise ValueError("PREVIEW_DEADLINE_MISSED_DURING_PUBLICATION; package not discovered")
            receipt = {"schema_version": "ASP_SHOW_PREVIEW_PUBLICATION_RECEIPT_V1", "package_sha256": address,
                       "publication_started_utc": doc["publication_utc"], "package_verified_utc": completed,
                       "source_unchanged": True, "model_executions": 0, "provider_calls": 0, "aisp_writes": 0}
            receipt_raw = canonical(receipt)
            receipt_path = "receipts/sha256/" + digest(receipt_raw) + ".json"
            immutable(root / receipt_path, receipt_raw)
            entry = {"sport": doc["sport"], "slate_date": doc["game"]["slate_date"],
                     "source_game_ref": doc["game"]["source_game_ref"], "forecast_id": doc["forecast_id"],
                     "source_binding_key": key, "package_path": "sha256/" + address,
                     "package_sha256": address, "forecast_sha256": digest(payloads["forecast.json"]),
                     "publication_receipt": receipt_path, "publication_completed_utc": completed,
                     "consumer_acknowledgement": None}
            entries.append(entry)
            results.append({**entry, "disposition": "PUBLISHED"})
        if entries != prior["packages"]:
            # One atomic pointer swap only after every new member validates.
            for entry in entries:
                verify_package(contained(root, entry["package_path"]), validator, now_fn())
            discovery = {"schema_version": "ASP_SHOW_PREVIEW_DISCOVERY_V1", "horizon": "SHOW_PREVIEW",
                         "created_utc": iso(now_fn()), "predecessor_sha256": digest(prior_raw) if prior_raw else None,
                         "packages": entries}
            raw = canonical(discovery)
            immutable(root / "indexes" / "sha256" / (digest(raw) + ".json"), raw)
            temp = root / (".discovery-" + uuid.uuid4().hex)
            immutable(temp, raw)
            os.replace(temp, pointer)
        return {"started_utc": iso(started), "completed_utc": iso(now_fn()), "results": results,
                "discovery": physical(pointer) if pointer.exists() else None}

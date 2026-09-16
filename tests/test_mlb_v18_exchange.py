"""Synthetic packaging only: no model, provider, AISP or real exchange writes."""
from datetime import date
import json
from pathlib import Path

import pytest

from server.sports_current_statcast import mlb_v18_current_publication as publication
from server.sports_current_statcast.mlb_v18_exchange import export_current_handoff


def test_immutable_exchange_copy_reuse_tamper_rejection_and_empty_accounting(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Export must never load or execute a model")

    monkeypatch.setattr(publication, "CurrentV18Engine", forbidden)
    source = tmp_path / "source"
    destination = tmp_path / "exchange"
    fixture = {"synthetic": "PACKAGING_ONLY_NOT_REAL_FORECAST"}
    feature, _ = publication.write_object(source, "feature-snapshot.json", fixture)
    forecast = {"gameId": "SYNTHETIC_EXCHANGE_ONLY", "capturedAt": "2099-04-01T10:00:00Z",
                "forecastCreatedAt": "2099-04-01T10:01:00Z", "scheduledStart": "2099-04-01T18:00:00Z",
                **publication.daily.RESEARCH_FLAGS}
    payloads = {"forecast.json": forecast, "execution-inputs.json": {"featureSnapshot": feature},
                "pregame-evidence.json": fixture, "representative-path.json": fixture}
    children = []
    encoded = {}
    for name, value in payloads.items():
        blob = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        encoded[name] = blob
        children.append({"relativePath": name, "sha256": publication.daily.sha_bytes(blob), "bytes": len(blob)})
    body = {"schemaVersion": "MLB_V18_DAILY_GAME_OBJECT_MANIFEST_V1", "publicationKey": "synthetic",
            "gameId": forecast["gameId"], "artifacts": children, **publication.daily.RESEARCH_FLAGS}
    digest = publication.daily.sha_json(body)
    directory = source / "objects/sha256" / digest
    directory.mkdir(parents=True)
    for name, blob in encoded.items():
        (directory / name).write_bytes(blob)
    (directory / "manifest.json").write_text(json.dumps({**body, "objectSha256": digest, "objectId": "synthetic"}), encoding="utf-8")
    row = {"gameId": forecast["gameId"], "objectSha256": digest,
           "relativePath": directory.relative_to(source).as_posix(), "manifestFile": "manifest.json",
           "forecastFile": "forecast.json", "capturedAt": forecast["capturedAt"], "scheduledStart": forecast["scheduledStart"]}
    handoff = publication.current_handoff(source, date(2099, 4, 1), [row])
    receipt = publication.current_import_receipt(source, date(2099, 4, 1), [row], [{**row, "status": "PUBLISHED", "newInference": True}], handoff)
    plan = export_current_handoff(handoff, receipt, exchange_root=destination)
    assert plan["importable"] and not destination.exists() and not plan["published"]
    exported = export_current_handoff(handoff, receipt, exchange_root=destination, publish=True)
    repeated = export_current_handoff(handoff, receipt, exchange_root=destination, publish=True)
    assert repeated["reused"] and exported["manifest"] == plan["manifest"] == repeated["manifest"]
    # An unchanged tick has its own Studio execution receipt. Keep the original
    # import receipt/package instead of copying every forecast again.
    tick_receipt = publication.current_import_receipt(source, date(2099, 4, 1), [row],
        [{**row, "status": "PUBLISHED", "newInference": False}], handoff)
    assert tick_receipt["sha256"] != receipt["sha256"]
    tick = export_current_handoff(handoff, tick_receipt, exchange_root=destination, publish=True)
    assert tick["reused"] and tick["packageRoot"] == exported["packageRoot"]
    assert tick["manifest"] == exported["manifest"] and tick["handoff"] == exported["handoff"]
    assert tick["receipt"] == exported["receipt"] and Path(tick_receipt["path"]).exists()
    assert len(list((destination / "sha256").iterdir())) == 1
    saved_manifest = json.loads(Path(tick["manifest"]["path"]).read_text())
    assert saved_manifest["sourceReceipt"] == receipt
    assert Path(exported["handoff"]["path"]).parents[3] == Path(exported["packageRoot"])
    assert (Path(exported["packageRoot"]) / Path(feature["path"]).relative_to(source)).read_bytes() == Path(feature["path"]).read_bytes()
    assert (Path(exported["packageRoot"]) / row["relativePath"] / "execution-inputs.json").read_bytes() == encoded["execution-inputs.json"]
    (directory / "forecast.json").write_bytes(b"tampered synthetic fixture")
    with pytest.raises(ValueError, match="CHECKSUM"):
        export_current_handoff(handoff, receipt, exchange_root=destination)
    empty = publication.current_handoff(source, date(2099, 4, 2), [])
    skip = {"gameId": "SYNTHETIC_SKIP_ONLY", "status": "SKIPPED", "reason": "MISSING_SOURCE"}
    empty_receipt = publication.current_import_receipt(source, date(2099, 4, 2), [], [skip], empty)
    accounting = export_current_handoff(empty, empty_receipt, exchange_root=destination, publish=True)
    assert not accounting["importable"] and accounting["importCommand"] is None
    assert accounting["forecastCount"] == 0 and accounting["gameCount"] == 1
    assert accounting["executionCount"] == accounting["aispWrites"] == accounting["providerCalls"] == 0
    changed_skip = {**skip, "reason": "DIFFERENT_SOURCE_BLOCKER"}
    changed_receipt = publication.current_import_receipt(source, date(2099, 4, 2), [], [changed_skip], empty)
    changed = export_current_handoff(empty, changed_receipt, exchange_root=destination, publish=True)
    assert not changed["reused"] and changed["packageRoot"] != accounting["packageRoot"]

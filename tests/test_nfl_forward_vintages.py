"""Four focused archive contracts; all source objects are synthetic 2026 fixtures."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.sports_nfl_m1 import forward_vintages as archive


def _json_object(root, filename, body):
    raw = archive.canonical_json_bytes(body)
    sha = hashlib.sha256(raw).hexdigest()
    path = root / "sha256" / sha / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "sha256": sha, "byteCount": len(raw)}


def _registration(bronze, partitions):
    ref = _json_object(bronze / "manifests", "manifest.json", {"partitions": partitions})
    (bronze / "current.json").write_text(json.dumps({"manifestRelativePath": str(Path(ref["path"]).relative_to(bronze)),
                                                   "manifestSha256": ref["sha256"]}), encoding="utf-8")


def _source(bronze, version=1):
    path = bronze / "objects/rosters/season=2026" / f"roster-{version}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"season": [2026], "team": ["SEA"], "gsis_id": [str(version)]}), path)
    raw = path.read_bytes()
    return {"familyId": "rosters", "season": 2026, "relativePath": str(path.relative_to(bronze)),
            "coverage": {"seasons": [2026]}, "status": "COMPLETE", "license": {"license": "CC-BY-4.0", "attribution": "Synthetic test"},
            "sourceContractVersion": "NFLVERSE_SOURCE_FAMILY_V1", "fileSha256": hashlib.sha256(raw).hexdigest(),
            "byteCount": len(raw), "retrievedAt": "2026-09-08T10:00:00Z", "assetUpdatedAt": "2026-09-08T09:00:00Z",
            "releasePublishedAt": "2022-01-28T02:12:10Z", "sourceUrl": "https://example.invalid/synthetic"}


def _environment(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    bronze = tmp_path / "bronze"
    bronze.mkdir()
    monkeypatch.setattr(archive, "OUTPUTS_ROOT", outputs)
    return bronze, outputs / "archive"


def _capture(bronze, output, day=9, schedule=None):
    return archive.capture_forward_vintages(bronze_root=bronze, output_root=output, schedule_handoff=schedule,
                                           clock=lambda: datetime(2026, 9, day, 12, tzinfo=timezone.utc))


def test_forward_observation_is_not_backdated_and_unchanged_capture_is_noop(tmp_path, monkeypatch):
    bronze, output = _environment(tmp_path, monkeypatch)
    _registration(bronze, [_source(bronze)])
    first = _capture(bronze, output)
    original_pointer = (output / "CURRENT.json").read_bytes()
    assert archive.select_vintage(output, "rosters", "2026-09-09T11:59:59Z") is None
    vintage = archive.select_vintage(output, "rosters", "2026-09-09T12:00:00Z")
    assert vintage["observedAtUtc"] == vintage["earliestPermittedForecastCutoffUtc"] == "2026-09-09T12:00:00Z"
    assert vintage["sourceRetrievedAtUtc"] == "2026-09-08T10:00:00Z"
    assert vintage["evidenceClass"] == "OBSERVED_AS_OF"
    assert vintage["wageringAuthority"] is False and vintage["executionAllowedInAISP"] is False
    second = _capture(bronze, output, 10)
    assert second["status"] == "NO_OP" and second["manifest"] == first["manifest"]
    assert (output / "CURRENT.json").read_bytes() == original_pointer
    assert len(list((output / "vintages/rosters").rglob("vintage.json"))) == 1


def test_corrections_preserve_asof_lineage_even_across_source_unavailability(tmp_path, monkeypatch):
    bronze, output = _environment(tmp_path, monkeypatch)
    _registration(bronze, [_source(bronze)])
    first = _capture(bronze, output)
    old = archive.select_vintage(output, "rosters", "2026-09-09T12:00:00Z")
    old_bytes = Path(old["payload"]["path"]).read_bytes()
    _registration(bronze, [])
    missing = _capture(bronze, output, 10)
    assert missing["families"]["rosters"]["status"] == "UNAVAILABLE"
    assert archive.select_vintage(output, "rosters", "2026-09-09T12:00:00Z") == old
    _registration(bronze, [_source(bronze, 2)])
    final = _capture(bronze, output, 11)
    new = archive.select_vintage(output, "rosters", "2026-09-11T12:00:00Z")
    assert new["previousFamilyVintage"] == first["families"]["rosters"]["vintage"]
    assert new["payload"]["sha256"] != old["payload"]["sha256"]
    assert archive.select_vintage(output, "rosters", "2026-09-10T23:59:59Z") == old
    assert Path(old["payload"]["path"]).read_bytes() == old_bytes
    assert final["families"]["rosters"]["status"] == "AVAILABLE"


def test_other_season_payloads_are_never_opened_and_source_checksums_fail_closed(tmp_path, monkeypatch):
    bronze, output = _environment(tmp_path, monkeypatch)
    sealed = {"familyId": "schedules", "season": None, "relativePath": "objects/schedules/all-seasons/DO_NOT_OPEN.parquet",
              "coverage": {"seasons": [2025, 2026]}, "status": "COMPLETE"}
    _registration(bronze, [sealed])
    with monkeypatch.context() as context:
        context.setattr(archive.pq, "ParquetFile", lambda *args, **kwargs: pytest.fail("sealed or mixed payload was opened"))
        result = _capture(bronze, output)
    assert result["families"]["schedules"]["status"] == "UNAVAILABLE"
    assert result["sealed2025PayloadRead"] is False
    manifest = json.loads(Path(result["manifest"]["path"]).read_bytes())
    assert manifest["sourcePayloadSeasonsRead"] == []
    source = _source(bronze)
    source["fileSha256"] = "0" * 64
    _registration(bronze, [source])
    with pytest.raises(archive.ForwardVintageError, match="checksum or byte count"):
        _capture(bronze, output, 10)


def test_partial_schedule_projection_preserves_identities_without_forecast_values(tmp_path, monkeypatch):
    bronze, output = _environment(tmp_path, monkeypatch)
    _registration(bronze, [])
    publication = tmp_path / "publication"
    forecast = {"eventId": "2026_01_SF_LA", "sourceEventId": "nflverse:2026_01_SF_LA", "homeTeamId": "LAR", "awayTeamId": "SF",
                "kickoffUtc": "2026-09-10T00:20:00Z", "forecastId": "unchanged-frozen-forecast",
                "forecastCreatedUtc": "2026-09-08T10:00:00Z", "evidenceCutoffUtc": "2026-08-29T13:00:00Z",
                "expectedHomeScore": 24.6, "homeWinProbability": 0.63, "outcome": "DO_NOT_PROJECT"}
    child = _json_object(publication / "slates", "handoff.json", {"season": 2026, "executionAllowedInAISP": False, "forecasts": [forecast]})
    parent = _json_object(publication, "handoff.json", {"season": 2026, "executionAllowedInAISP": False, "eventCount": 1,
                          "slateHandoffs": [{"handoffPath": child["path"], "handoffSha256": child["sha256"]}],
                          "source": {"assets": [{"familyId": "schedules", "license": "CC-BY-4.0", "fileSha256": "metadata-only"}]}})
    projection = archive.schedule_events_from_handoff(Path(parent["path"]))
    assert projection["eventCount"] == 1 and projection["fullSeasonCoverage"] is False
    assert projection["events"][0]["eventId"] == forecast["eventId"]
    assert not {"expectedHomeScore", "homeWinProbability", "outcome"} & projection["events"][0].keys()
    result = _capture(bronze, output, schedule=Path(parent["path"]))
    vintage = archive.select_vintage(output, "schedules", "2026-09-09T12:00:00Z")
    assert result["families"]["schedules"]["rowCount"] == 1
    assert vintage["sourceIdentity"]["derivation"] == "DERIVED_FROM_PRECOMPUTED_FORECAST_SCHEDULE_PROJECTION"
    assert vintage["sourceRetrievedAtUtc"] is None
    assert vintage["observedAtUtc"] == "2026-09-09T12:00:00Z"
    Path(child["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(archive.ForwardVintageError, match="checksum differs"):
        archive.schedule_events_from_handoff(Path(parent["path"]))

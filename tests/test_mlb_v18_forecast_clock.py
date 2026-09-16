import json
from pathlib import Path

import pytest

from server.sports_current_statcast.mlb_v18_forecast_clock import (
    ForecastCreationClockError,
    resolve_forecast_created_at_v1,
)


FIXTURES = Path(__file__).parent / "fixtures/mlb_v18_forecast_clock"


def test_actual_legacy_state_shape_resolves_exact_clock_from_bound_immutable_forecast(tmp_path):
    legacy = json.loads((FIXTURES / "legacy-runtime-state.json").read_text(encoding="utf-8"))
    assert legacy["sourcePhysicalSha256"] == "3eb4ca8538f7f0d6705d63a03fefeca3f97a3ff5467c11a2b56e42cbbbc0cf3e"
    assert all("forecastCreatedAt" not in row for row in legacy["state"]["games"].values())

    object_id = "683a0c14751466ab34f703a3f60f8fb3ddcf9e00160a03d5eaa4402d25a2426e"
    target = tmp_path / "objects/sha256" / object_id
    target.mkdir(parents=True)
    for name in ("manifest.json", "forecast.json"):
        (target / name).write_bytes((FIXTURES / name).read_bytes())
    binding = {
        "gameId": "8cad9313-5d8d-4300-ac6d-66a74a6d3459",
        "objectSha256": object_id,
        "relativePath": f"objects/sha256/{object_id}",
        "forecastFile": "forecast.json",
        "manifestFile": "manifest.json",
    }
    receipt = resolve_forecast_created_at_v1(binding, output_root=tmp_path)
    assert receipt["forecastCreatedAt"] == "2026-09-14T19:38:03.000665+00:00"
    assert receipt["source"] == "BOUND_IMMUTABLE_FORECAST_ARTIFACT"
    assert receipt["currentTimeFallbackUsed"] is False
    assert receipt["historicalStateRewritten"] is False
    assert legacy == json.loads((FIXTURES / "legacy-runtime-state.json").read_text(encoding="utf-8"))


def test_direct_retained_clock_is_preserved_byte_for_byte_and_no_now_fallback_exists():
    value = "2026-09-10T21:29:52.660204+00:00"
    receipt = resolve_forecast_created_at_v1({"forecastCreatedAt": value})
    assert receipt["forecastCreatedAt"] == value
    with pytest.raises(ForecastCreationClockError, match="UNRESOLVED"):
        resolve_forecast_created_at_v1({"checkedAt": "2026-09-15T01:42:44.830841+00:00"})


def test_bound_forecast_tamper_and_conflicting_direct_clock_fail_closed(tmp_path):
    object_id = "683a0c14751466ab34f703a3f60f8fb3ddcf9e00160a03d5eaa4402d25a2426e"
    target = tmp_path / "objects/sha256" / object_id
    target.mkdir(parents=True)
    for name in ("manifest.json", "forecast.json"):
        (target / name).write_bytes((FIXTURES / name).read_bytes())
    binding = {"gameId": "8cad9313-5d8d-4300-ac6d-66a74a6d3459", "objectSha256": object_id,
               "relativePath": f"objects/sha256/{object_id}"}
    conflict = {**binding, "forecastCreatedAt": "2026-09-14T19:38:04.000665+00:00"}
    with pytest.raises(ForecastCreationClockError, match="MISMATCH"):
        resolve_forecast_created_at_v1(conflict, output_root=tmp_path)
    payload = bytearray((target / "forecast.json").read_bytes())
    payload[-2] ^= 1
    (target / "forecast.json").write_bytes(payload)
    with pytest.raises(ForecastCreationClockError, match="SHA256_MISMATCH"):
        resolve_forecast_created_at_v1(binding, output_root=tmp_path)


def test_forecast_object_manifest_binding_supports_operational_receipt_shape(tmp_path):
    target = tmp_path / "immutable"
    target.mkdir()
    for name in ("manifest.json", "forecast.json"):
        (target / name).write_bytes((FIXTURES / name).read_bytes())
    manifest = target / "manifest.json"
    binding = {
        "gameId": "8cad9313-5d8d-4300-ac6d-66a74a6d3459",
        "forecastObject": {
            "objectSha256": "683a0c14751466ab34f703a3f60f8fb3ddcf9e00160a03d5eaa4402d25a2426e",
            "manifest": {
                "path": str(manifest),
                "sha256": "a6d1ce176fda17c89f65dea59beda16d172e7b530ed1986ba14963ea21c5b4ba",
                "bytes": 1065,
            },
        },
    }
    receipt = resolve_forecast_created_at_v1(binding)
    assert receipt["forecastCreatedAt"] == "2026-09-14T19:38:03.000665+00:00"
    assert receipt["source"] == "BOUND_IMMUTABLE_FORECAST_ARTIFACT"

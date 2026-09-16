"""Focused synthetic guards; no sports datasets, estimator fits or AISP access."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from server.model_registry import mlb_v18_conditional as champion
from server.model_registry import model_registry_service as registry


def decision():
    return dict(effective_at="2026-09-12T04:00:00Z", decision_at="2026-09-12T16:00:00Z",
                event_id="fixture-game", first_pitch="2026-09-12T17:00:00Z",
                forecast={"modelName": "MLB_V18_HGB_PA", "paArtifactSha256": champion.PA_SHA,
                          "eventId": "fixture-game", "forecastCreatedAt": "2026-09-12T15:00:00Z",
                          "evidenceCutoffAt": "2026-09-12T14:59:00Z"},
                quote_eligible=True, existing_policy_eligible=True, adjusted_edge=0.02)


def test_prospective_boundary_and_no_backfill_or_model_mixing():
    args = decision()
    assert champion.prospective_decision_eligibility(**args) == "ELIGIBLE_FOR_VIRTUAL_POLICY_EVALUATION_ONLY"
    for replacement, reason in [
        ({"decision_at": "2026-09-12T03:59:59Z"}, "GEN1_ERA_NO_RECOMPUTATION"),
        ({"already_decided": True}, "HISTORICAL_DECISION_IMMUTABLE"),
        ({"forecast": None}, "V18_FORECAST_MISSING_NO_GEN1_FALLBACK"),
        ({"first_pitch": "2026-09-12T15:00:00Z"}, "EVENT_ALREADY_STARTED"),
        ({"event_id": "other-event"}, "EVENT_IDENTITY_MISMATCH"),
        ({"adjusted_edge": 0.019999}, "EXISTING_2_PERCENT_ADJUSTED_EDGE_NOT_MET"),
        ({"quote_eligible": False}, "EXISTING_QUOTE_READINESS_CUTOFF_OR_STAKE_RULE_NOT_MET"),
    ]:
        assert champion.prospective_decision_eligibility(**(args | replacement)) == reason
    bad = deepcopy(args)
    bad["forecast"]["modelName"] = "GEN1"
    assert champion.prospective_decision_eligibility(**bad) == "WRONG_MODEL_OR_ARTIFACT"
    bad = deepcopy(args)
    bad["forecast"]["forecastCreatedAt"] = "2026-09-12T17:00:01Z"
    assert champion.prospective_decision_eligibility(**bad) == "INVALID_PREGAME_TEMPORAL_ORDER"
    bad["forecast"]["forecastCreatedAt"] = "2026-09-12T15:00:00"
    assert champion.prospective_decision_eligibility(**bad) == "MISSING_OR_INVALID_TEMPORAL_EVIDENCE"


def test_registration_authorizes_before_reading_manifest(monkeypatch):
    def denied(*args):
        raise HTTPException(status_code=403)
    monkeypatch.setattr(registry, "authorize_modeling_scope", denied)
    monkeypatch.setattr(champion, "verify_manifest", lambda *a, **k: pytest.fail("Unauthorized artifact read"))
    with pytest.raises(HTTPException) as error:
        registry.register_mlb_v18_conditional_champion({"userId": "not-owner"}, "missing", "bad")
    assert error.value.status_code == 403


def test_reference_checksum_and_scope_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(champion, "ROOT", tmp_path)
    payload = tmp_path / "synthetic.txt"
    payload.write_bytes(b"clearly synthetic artifact fixture")
    ref = champion.descriptor(payload)
    assert champion.verify_reference(ref) == ref
    with pytest.raises(ValueError, match="checksum/byte-count"):
        champion.verify_reference(ref | {"sha256": "0" * 64})
    with pytest.raises(ValueError, match="inside Model Studio"):
        champion.verify_reference(ref | {"path": str(tmp_path.parent / "outside")})


def test_pointer_registration_idempotent_survives_new_service(tmp_path, monkeypatch):
    from server.persistence.db import Database
    from server.persistence.service import PersistenceService
    database = Database(tmp_path / "synthetic.sqlite")
    assert database.initialize()["ok"]
    service = PersistenceService(database)
    user = {"userId": "synthetic-owner"}
    service.projects.ensure(champion.PROJECT, {"owner_user_id": user["userId"]})
    manifest = {"historicalIntegrityLimitation": "synthetic timing limitation",
                "trainingIdentity": {}, "featureContract": {"manifestSha256": "synthetic"},
                "targetContract": {"targetName": "outcome"}, "authority": dict.fromkeys(champion.FLAGS, True),
                "authorization": {"requestSha256": champion.DECISION_SHA}, "predecessor": "GEN1_UNCHANGED"}
    monkeypatch.setattr(champion, "verify_manifest", lambda *a, **k: {"manifest": manifest, "sizeBytes": 123})
    first = champion.register_authorized(service, user, tmp_path / "synthetic-manifest", "a" * 64)
    reloaded = PersistenceService(Database(database.path))
    second = champion.register_authorized(reloaded, user, tmp_path / "synthetic-manifest", "a" * 64)
    assert first["operation"] == "REGISTERED_CONDITIONAL_CHAMPION"
    assert second["operation"] == "EXACT_REUSE"
    assert reloaded.models.get(champion.MODEL)["current_version_id"] == first["modelVersionId"]
    row = reloaded.model_versions.get(first["modelVersionId"])
    assert row["validation_status"] == "historical_validation_under_review"
    assert row["final_holdout_status"] == "sealed_unread"
    assert row["selection_metric_value"] is None
    with pytest.raises(champion.ModelRegistryConflictError):
        champion.register_authorized(reloaded, user, tmp_path / "synthetic-manifest", "b" * 64)
    with database.transaction() as connection:
        connection.execute("UPDATE model_versions SET quarantined_at='synthetic-quarantine' WHERE model_version_id=?", (first["modelVersionId"],))
    with pytest.raises(champion.ModelRegistryConflictError):
        champion.register_authorized(reloaded, user, tmp_path / "synthetic-manifest", "a" * 64)
    with pytest.raises(ValueError, match="lifecycle mismatch"):
        champion.verify_record(reloaded, reloaded.model_versions.get(first["modelVersionId"]))

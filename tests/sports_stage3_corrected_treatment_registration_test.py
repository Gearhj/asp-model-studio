from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np
import pandas as pd

from scripts.register_mlb_corrected_treatment import same_fold_population
from server.sports_current_statcast import stage3_corrected_treatment_spec as corrected
from server.sports_current_statcast import stage3_corrected_eligibility as row_eligibility
from server.sports_current_statcast import stage3_feature_engineering as engineering
from server.sports_current_statcast import stage3_feature_treatment_spec as specifications
from server.sports_current_statcast import stage3_model_eligibility as eligibility
from server.sports_current_statcast import stage3_model_laboratory as model_lab
from server.sports_current_statcast import stage3_player_prior_authority as prior


@pytest.fixture
def base_manifest():
    source = specifications.load_source_specification()
    decision = json.loads(Path(specifications.CORE_CHALLENGER_DECISION_PATH).read_text(encoding="utf-8"))
    deferred = set(decision["deferredFeatures"]) | set(decision["deferredDerivedBindings"])
    bindings = [prior._decorate_binding_template(item) for item in prior._BINDINGS]
    for binding in bindings:
        if binding["status"] not in {"READY_GOVERNED_PRIOR_V1", "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"}:
            binding.update(status="READY_GOVERNED_PRIOR_V2", executable=True, selectable=False)
    by_name = {binding["feature"]: binding for binding in bindings}
    rows = deepcopy(source["features"])
    for row in rows:
        name = row["feature_name"]
        binding = by_name.get(name)
        retired = binding is not None and binding["status"] == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
        excluded = name in deferred or retired or row["recommended_inclusion"].startswith("EXCLUDE_")
        row.update(executable_selectable=not excluded, preprocessing_executable=not excluded, execution_contract={"missing": {}}, backend_eligibility=True)
        row["executable_status"] = binding["status"] if binding else "DEFERRED_CONTEXT_AUTHORITY" if name in deferred else "READY"
        if binding and binding["status"] == "READY_GOVERNED_PRIOR_V2":
            row["executable_selectable"] = False
        if binding and not retired:
            row["execution_contract"]["missing"]["priorAuthority"] = binding
    return {"features": rows, "priorAuthority": {"bindings": bindings}, "featureInventorySha256": "a" * 64, "executionSummary": {"blocked": 0}, "exceptions": [], "reconciliation": {"fatal": False}, "projectAuthority": {"authorityKey": "test-authority"}}


def compiled_fixture(base_manifest, monkeypatch):
    decision = corrected.correction_decision()
    monkeypatch.setattr(corrected, "REFERENCE_V14_MANIFEST_SHA", corrected.content_sha(base_manifest))
    monkeypatch.setattr(corrected, "correction_decision", lambda: deepcopy(decision))
    manifest = corrected.build_corrected_manifest(base_manifest)
    return {**manifest, "manifestChecksum": corrected.content_sha(manifest)}


def test_exact_source_scope_expands_registered_v1_outputs_without_optional_v2(base_manifest):
    schema = corrected.build_model_feature_schema(base_manifest)
    assert len(schema["sourceOrderedFeatures"]) == 218
    assert len(schema["orderedFeatures"]) == 273
    assert schema["orderedFeatures"][:218] == schema["sourceOrderedFeatures"]
    assert len(schema["wave1SourceFeatures"]) == 11
    assert len(schema["wave2SourceFeatures"]) == 10
    assert not any("__prior_v2__" in name for name in schema["orderedFeatures"])
    for name, outputs in schema["wave1OutputBindings"].items():
        binding = next(item for item in base_manifest["priorAuthority"]["bindings"] if item["feature"] == name)
        assert list(outputs) == list(corrected.WAVE1_OUTPUT_ROLES)
        assert all(outputs[role] == binding["derivedOutputs"][role] for role in corrected.WAVE1_OUTPUT_ROLES)
    assert len([item for item in schema["columns"] if item["role"] == "historyState" and item["dataType"] == "categorical"]) == 11


def test_successor_preserves_base_exclusions_and_records_explicit_corrections(base_manifest, monkeypatch):
    before = deepcopy(base_manifest)
    compiled = compiled_fixture(base_manifest, monkeypatch)
    assert base_manifest == before
    excluded = compiled["correctedTreatment"]["preservedExcludedWorkbookFeatures"]
    assert len(excluded) == 22
    assert {"pitcher_era9", "batter_obp", "batter_last100_contact_rate", "holiday_name", "doubleheader_game_number"} <= set(excluded)
    corrected_matchup = next(item for item in compiled["features"] if item["feature_name"] == "matchup_platoon_advantage")
    original_matchup = next(item for item in before["features"] if item["feature_name"] == "matchup_platoon_advantage")
    assert corrected_matchup["source_model_handling"] == original_matchup["model_handling"]
    assert corrected_matchup["approved_deviation"]["authorizationChecksum"] == "61046f7c1465733f70623bb74533e050fbca8ed93a8c2fb55346e71afa6f1ae9"
    assert compiled["correctedTreatment"]["parentOnlyAblations"] == "DEFERRED_BY_EXPLICIT_USER_DECISION"


def test_changed_predecessor_and_missing_registered_output_fail_closed(base_manifest):
    with pytest.raises(ValueError, match="exact authenticated V14"):
        corrected.build_corrected_manifest(base_manifest)
    changed = deepcopy(base_manifest)
    binding = next(item for item in changed["priorAuthority"]["bindings"] if item["status"] == "READY_GOVERNED_PRIOR_V1")
    del binding["derivedOutputs"]["posteriorStd"]
    with pytest.raises(ValueError, match="registered posteriorStd"):
        corrected.build_model_feature_schema(changed)


def test_registration_requires_exact_adopted_schema_and_rejects_injected_columns(base_manifest, monkeypatch):
    compiled = compiled_fixture(base_manifest, monkeypatch)
    manifest = {key: value for key, value in compiled.items() if key != "manifestChecksum"}
    adopted = {"manifest": manifest, "manifestChecksum": compiled["manifestChecksum"]}
    monkeypatch.setattr(engineering, "Stage3TreatmentRepository", lambda _: SimpleNamespace(combined_spec_state=lambda *args: {"adopted": adopted}))
    contract = corrected.corrected_transformation_contracts(compiled)
    schema = compiled["modelFeatureSchema"]
    catalog = {name: {"name": name, "dataType": "numeric", "eligible": True} for name in schema["sourceOrderedFeatures"]}
    result = engineering._corrected_registration_contract(None, SimpleNamespace(project_id="asp-mtlozhdx", review_digest="test"), contract, schema["orderedFeatures"], catalog)
    assert result == contract and len(catalog) == 273
    with pytest.raises(engineering.Stage3FeatureEngineeringError, match="exact adopted 273"):
        engineering._corrected_registration_contract(None, SimpleNamespace(project_id="asp-mtlozhdx", review_digest="test"), contract, [*schema["orderedFeatures"], "outcome"], catalog)
    altered = deepcopy(contract)
    altered["sourceOrderedFeatures"].append("pitcher_era9")
    with pytest.raises(engineering.Stage3FeatureEngineeringError, match="exact adopted 273"):
        engineering._corrected_registration_contract(None, SimpleNamespace(project_id="asp-mtlozhdx", review_digest="test"), altered, schema["orderedFeatures"], catalog)


def test_old_feature_registration_not_reinterpreted_as_corrected(base_manifest, monkeypatch):
    compiled = compiled_fixture(base_manifest, monkeypatch)
    contract = corrected.corrected_transformation_contracts(compiled)
    universe = {"orderedFeatures": compiled["modelFeatureSchema"]["orderedFeatures"], "exclusions": [], "transformationContracts": contract}
    assert eligibility.assess_feature_set({"orderedFeatures": universe["orderedFeatures"], "transformationContracts": contract}, universe)["executable"] is True
    historical = {"orderedFeatures": compiled["modelFeatureSchema"]["sourceOrderedFeatures"], "transformationContracts": {"ordered": []}}
    original = deepcopy(historical)
    assert eligibility.assess_feature_set(historical, universe)["executable"] is False
    assert historical == original


def test_legacy_compile_is_default_until_successor_adopted(monkeypatch):
    monkeypatch.setattr(specifications.eda, "_resolve_authority", lambda *args: SimpleNamespace(review_digest="test"))
    monkeypatch.setattr(specifications, "Stage3TreatmentRepository", lambda _: SimpleNamespace(combined_spec_state=lambda *args: {"adopted": None, "history": []}))
    sentinel = {"manifestChecksum": "legacy-unchanged"}
    monkeypatch.setattr(specifications, "_compile_legacy_project_specification", lambda *args: sentinel)
    assert specifications.compile_project_specification(None, "asp-mtlozhdx") is sentinel
    with pytest.raises(specifications.Stage3FeatureTreatmentSpecError, match="exact adopted V14"):
        specifications.compile_project_specification(None, "asp-mtlozhdx", semantic_treatment_version=corrected.SEMANTIC_TREATMENT_VERSION)


def test_fold_preservation_ignores_only_changed_feature_binding_identity():
    reference = [{"foldNumber": 1, "trainEnd": "2023-10-01", "trainRows": 182072, "selectedFeatureSetIds": ["old"], "checksum": "old-hash"}]
    rebound = [{**reference[0], "selectedFeatureSetIds": ["new"], "checksum": "new-hash"}]
    assert same_fold_population(reference, rebound)
    rebound[0]["trainRows"] -= 1
    assert not same_fold_population(reference, rebound)


def test_corrected_eligibility_authenticates_all_273_outputs_and_preserves_physical_catalog(base_manifest, monkeypatch):
    compiled = compiled_fixture(base_manifest, monkeypatch)
    manifest = {key: value for key, value in compiled.items() if key != "manifestChecksum"}
    source_rows = [
        {
            "name": item["feature_name"], "order": index + 1, "role": "PREGAME_FEATURE",
            "dataType": "numeric", "featureFamily": "TEST", "governanceStatus": "ELIGIBLE",
            "availabilityStatus": "AVAILABLE", "missingPercentDevelopment": 0.0,
            "leakageRisk": "NO_TARGET_OR_FUTURE_EVIDENCE", "forecastTimeAvailability": "PREGAME_KNOWN",
        }
        for index, item in enumerate(manifest["features"])
    ]
    source_rows.extend({**source_rows[0], "name": f"unapproved_rivalry_{index}", "governanceStatus": "PROPOSED_NOT_APPROVED"} for index in range(14))
    before = deepcopy(source_rows)
    monkeypatch.setattr(eligibility.feature_engineering, "_catalog", lambda _: (source_rows, {}))
    authority = SimpleNamespace(
        eda_authority=SimpleNamespace(project_id="asp-mtlozhdx", source_dataset_id="test", source_manifest_sha="a" * 64,
                                      gold_manifest_sha="b" * 64, contextual_manifest_sha="c" * 64, review_digest="test"),
        authority_key="test-authority", split={}, outlier_policy={}, missing_policy={},
        treatment_specification={"manifest": manifest, "manifestChecksum": compiled["manifestChecksum"]},
    )
    result = eligibility.build_model_eligibility(authority)
    assert result["orderedFeatures"] == manifest["modelFeatureSchema"]["orderedFeatures"]
    assert result["featureCount"] == 273
    assert result["reconciliation"]["physicalCandidateCount"] == 254
    assert result["reconciliation"]["registeredDerivedOutputCount"] == 55
    assert result["reconciliation"]["excludedPredictorCount"] == 36
    assert result["reconciliation"]["totalCandidateCount"] == 309
    assert result["transformationContracts"] == corrected.corrected_transformation_contracts(compiled)
    assert source_rows == before
    assert eligibility.build_model_eligibility(authority)["checksum"] == result["checksum"]
    authority.treatment_specification["manifestChecksum"] = "0" * 64
    with pytest.raises(RuntimeError, match="authenticated adopted"):
        eligibility.build_model_eligibility(authority)


def _quarantine_frame():
    return pd.DataFrame({
        "canonicalPaId": [f"pa-{i}" for i in range(5)], "canonicalGameId": [f"game-{i}" for i in range(5)],
        "game_date": ["2023-05-01"] * 5, "batter_log1p_pa": [0.0, np.nan, 0.0, 1.0, 1.0],
        "batter_prior_missing": [False, True, True, False, False],
        "batter_so_per_pa": [np.nan, np.nan, np.nan, .25, .25],
        "batter_bb_hbp_per_pa": [np.nan, np.nan, np.nan, .1, .1],
        "batter_hr_per_pa": [np.nan, np.nan, np.nan, .05, .05],
        "pitcher_whip": [1.2, 1.2, 1.2, 1.2, np.nan],
    })


def _quarantine_set():
    return {"transformationContracts": {"semanticTreatmentVersion": corrected.SEMANTIC_TREATMENT_VERSION,
                                        "rowEligibilityPolicy": row_eligibility.registered_policy()}}


def test_quarantine_holds_only_exact_known_zero_pa_and_preserves_cold_and_whip():
    frame = _quarantine_frame()
    before = frame.copy(deep=True)
    mask, evidence = row_eligibility.eligibility_mask(frame, _quarantine_set())
    assert mask.tolist() == [False, True, True, True, True]
    assert evidence["heldRows"] == 1 and evidence["eligibleRows"] == 4
    assert evidence["heldObservations"][0]["reason"] == row_eligibility.REASON
    assert evidence["targetValuesRead"] == evidence["valuesImputed"] == evidence["sourceRowsDeleted"] == 0
    assert "outcome" not in str(evidence["heldObservations"])
    pd.testing.assert_frame_equal(frame, before)
    assert row_eligibility.eligibility_mask(frame, _quarantine_set())[1]["eligibilityChecksum"] == evidence["eligibilityChecksum"]


@pytest.mark.parametrize("column,value", [("batter_prior_missing", "false"), ("batter_prior_missing", np.nan), ("batter_prior_missing", .5), ("batter_log1p_pa", "0"), ("batter_log1p_pa", np.nan), ("batter_so_per_pa", "invalid")])
def test_quarantine_cannot_swallow_other_invalid_states(column, value):
    frame = _quarantine_frame()
    frame[column] = frame[column].astype(object)
    frame.loc[0, column] = value
    mask, evidence = row_eligibility.eligibility_mask(frame, _quarantine_set())
    assert mask.all() and evidence["heldRows"] == 0


def test_quarantine_requires_registered_policy_and_seals_oot_before_feature_access():
    frame = _quarantine_frame()
    mask, evidence = row_eligibility.eligibility_mask(frame, {})
    assert mask.all() and evidence["status"] == "NOT_REGISTERED_NOT_APPLIED"
    altered = _quarantine_set()
    altered["transformationContracts"]["rowEligibilityPolicy"]["expectedDevelopmentHeldRows"] = 57
    with pytest.raises(ValueError, match="exact registered"):
        row_eligibility.eligibility_mask(frame, altered)
    with pytest.raises(ValueError, match="FINAL_OOT_SEALED"):
        row_eligibility.eligibility_mask(pd.DataFrame({"game_date": ["2026-08-14"]}), _quarantine_set())


def _synthetic_live_resolution(base_manifest, monkeypatch):
    compiled = compiled_fixture(base_manifest, monkeypatch)
    manifest = {key: value for key, value in compiled.items() if key != "manifestChecksum"}
    manifest["coreChallengerDecision"] = {"disposition": "DEFERRED_CONTEXT_AUTHORITY"}
    manifest["priorAuthority"].update(wave1AuthorityId="v1", wave1AuthorityChecksum="v1-sha", authorityId="v2", authorityChecksum="v2-sha")
    combined = {"manifest": manifest, "manifestChecksum": corrected.content_sha(manifest), "status": "ADOPTED",
                "projectId": "asp-mtlozhdx", "goldManifestSha": "g" * 64, "authorityReviewDigest": "review",
                "finalOot": {"locked": True}, "linkedPolicies": {
                    "outlier": {"policyId": "outlier", "checksum": "outlier-sha"},
                    "missing": {"policyId": "missing", "checksum": "missing-sha"}}}
    schema = manifest["modelFeatureSchema"]
    authority = SimpleNamespace(project_id="asp-mtlozhdx", review_digest="review", gold_manifest_sha="g" * 64,
                                schema=SimpleNamespace(names=list(schema["sourceOrderedFeatures"])))
    development = {"startDate": "2023-03-30", "endDate": "2026-08-13", "rows": 683662}
    feature_set = {"featureSetId": "corrected", "checksum": "feature-sha", "status": "REGISTERED", "projectId": authority.project_id,
                   "authority": {"goldManifestSha": authority.gold_manifest_sha, "reviewDigest": authority.review_digest},
                   "development": development, "finalOot": {"locked": True}, "orderedFeatures": list(schema["orderedFeatures"]),
                   "transformationContracts": corrected.corrected_transformation_contracts({**manifest, "manifestChecksum": combined["manifestChecksum"]}),
                   "treatmentPolicies": deepcopy(combined["linkedPolicies"]), "unavailableExclusions": []}
    split = {"development": development, "selectedFeatureSetIds": ["corrected"],
             "contract": {"selectedFeatureSets": [{"featureSetId": "corrected", "checksum": "feature-sha"}]}}
    physical_rows = [{"name": name, "dataType": "numeric", "eligible": True} for name in schema["sourceOrderedFeatures"]]
    monkeypatch.setattr(engineering, "_catalog", lambda _: (deepcopy(physical_rows), {}))
    monkeypatch.setattr(model_lab.eda, "_resolve_authority", lambda *args: authority)
    monkeypatch.setattr(model_lab, "ProjectRepository", lambda _: SimpleNamespace(get=lambda _: {"project_name": "Synthetic corrected authority"}))
    repository = lambda _: SimpleNamespace(combined_spec_state=lambda *args: {"adopted": combined, "latestDraft": None})
    monkeypatch.setattr(model_lab, "Stage3TreatmentRepository", repository)
    monkeypatch.setattr(engineering, "Stage3TreatmentRepository", repository)
    monkeypatch.setattr(model_lab, "Stage3FeatureSetRepository", lambda _: SimpleNamespace(list_versions=lambda *args: [feature_set]))
    monkeypatch.setattr(model_lab, "_split_by_exact_identity", lambda *args: split)
    monkeypatch.setattr(model_lab, "_policy_by_exact_identity", lambda *args, kind, expected: deepcopy(combined["linkedPolicies"]["outlier" if kind == "OUTLIER" else "missing"]))
    monkeypatch.setattr(model_lab.sufficient_stats, "registered_sufficient_statistics_authority", lambda *args, **kwargs: {})
    monkeypatch.setattr(model_lab.player_prior, "project_authority_manifest", lambda *args, **kwargs: {"authorityId": "v1", "authorityChecksum": "v1-sha", "featureSets": {"executable": schema["wave1SourceFeatures"]}})
    bundle = {"authorityId": "v2", "authorityChecksum": "v2-sha", "definition": {"artifactSha256": "definition"}, "foldAuthorities": []}
    monkeypatch.setattr(model_lab, "load_current_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(model_lab, "load_artifact", lambda *args, **kwargs: {})
    monkeypatch.setattr(model_lab.player_prior_v2, "_validate_bundle", lambda value, **kwargs: value)
    monkeypatch.setattr(model_lab.player_prior_v2, "authenticate_companion", lambda *args, **kwargs: {"_developmentPaths": []})
    return authority, combined, feature_set, split


def test_actual_model_lab_authority_resolution_accepts_exact_273_registered_outputs(base_manifest, monkeypatch):
    authority, combined, feature_set, _ = _synthetic_live_resolution(base_manifest, monkeypatch)
    assert len(authority.schema.names) == 218
    resolved = model_lab.resolve_model_lab_authority(None, "asp-mtlozhdx")
    assert resolved.feature_sets == (feature_set,)
    assert len(resolved.feature_sets[0]["orderedFeatures"]) == 273
    assert resolved.treatment_specification == combined


@pytest.mark.parametrize("mutation", ["unknown_output", "retired_input", "missing_parent", "contract_hash", "manifest_hash", "split_hash", "gold", "project", "oot_unlocked"])
def test_actual_model_lab_authority_rejects_forged_or_stale_corrected_registration(base_manifest, monkeypatch, mutation):
    authority, combined, feature_set, split = _synthetic_live_resolution(base_manifest, monkeypatch)
    if mutation == "unknown_output": feature_set["orderedFeatures"].append("unregistered_prior_output")
    elif mutation == "retired_input": feature_set["orderedFeatures"].append("pitcher_era9")
    elif mutation == "missing_parent": authority.schema.names.remove("batter_so_per_pa")
    elif mutation == "contract_hash": feature_set["transformationContracts"]["treatmentManifestChecksum"] = "bad"
    elif mutation == "manifest_hash": combined["manifestChecksum"] = "bad"
    elif mutation == "split_hash": split["contract"]["selectedFeatureSets"][0]["checksum"] = "bad"
    elif mutation == "gold": feature_set["authority"]["goldManifestSha"] = "bad"
    elif mutation == "project": feature_set["projectId"] = "other-project"
    elif mutation == "oot_unlocked": feature_set["finalOot"]["locked"] = False
    with pytest.raises(model_lab.Stage3ModelLaboratoryError):
        model_lab.resolve_model_lab_authority(None, "asp-mtlozhdx")

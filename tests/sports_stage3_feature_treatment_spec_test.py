from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any

from openpyxl import Workbook, load_workbook
import pytest

from scripts.compile_mlb_feature_treatment_spec import (
    FIELD_NAMES,
    PRIMARY_SHEET,
    REQUIRED_COLUMNS,
    SUPPORTING_SHEETS,
    WorkbookSpecificationError,
    compile_workbook,
)
from server.persistence.db import Database
from server.persistence.repositories.stage3_feature_set_repository import (
    NO_CURRENT_FEATURE_SET,
)
from server.persistence.repositories.stage3_treatment_repository import (
    Stage3TreatmentPersistenceError,
    Stage3TreatmentRepository,
)
from server.sports_current_statcast import stage3_feature_engineering as feature_engineering
from server.sports_current_statcast import stage3_feature_treatment_spec as specification
from server.sports_current_statcast import stage3_treatments as treatments
from server.sports_current_statcast.contextual_features import (
    ORDERED_GOLD_PLUS_CONTEXT_FEATURES,
)
from server.sports_gold.contracts import GOLD_FEATURES


PROJECT_ID = "asp-mtlozhdx"
WORKBOOK_SHA256 = "0e2d5f2b0d495c941ae97fb84c216f0b5ccdfe904519db0acb616d1543a66679"


def _source() -> dict[str, Any]:
    return specification.load_source_specification()


def _write_source_workbook(
    path: Path,
    source: dict[str, Any],
    *,
    duplicate_first_feature: bool = False,
) -> None:
    """Build a hermetic workbook with the production 240-row source contract."""

    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet_names = [PRIMARY_SHEET, *SUPPORTING_SHEETS]
    for sheet_name in sheet_names:
        workbook.create_sheet(sheet_name)
    matrix = workbook[PRIMARY_SHEET]
    matrix.append(list(REQUIRED_COLUMNS))
    records = deepcopy(source["features"])
    if duplicate_first_feature:
        records[1]["feature_name"] = records[0]["feature_name"]
    for record in records:
        row: list[Any] = []
        for column in REQUIRED_COLUMNS:
            value = record[FIELD_NAMES[column]]
            if column == "Missing %" and value is not None:
                value = float(value) / 100.0
            row.append(value)
        matrix.append(row)
    matrix.append([None] * len(REQUIRED_COLUMNS))
    matrix.append(["Scientific footer; not a feature row"])
    for sheet_name in SUPPORTING_SHEETS:
        workbook[sheet_name].append([sheet_name])
    workbook.save(path)
    workbook.close()


def _extra_family(name: str) -> str:
    if name.endswith("_home_x_rivalry"):
        return "INTERACTION"
    if name.endswith("_rivalry_mapping_missing"):
        return "MISSINGNESS"
    return "DIVISION_RIVALRY"


def _backend_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    source_by_name = {str(row["feature_name"]): row for row in source["features"]}
    rows: list[dict[str, Any]] = []
    for order, name in enumerate(ORDERED_GOLD_PLUS_CONTEXT_FEATURES, start=1):
        scientific = source_by_name.get(name)
        if scientific is not None:
            family = str(scientific["feature_family"])
            data_type = str(scientific["data_type"])
            core = str(scientific["core_status"]).lower() == "yes"
            missing_percent = float(scientific["missing_percent"])
            disposition = str(scientific["recommended_inclusion"])
            role = (
                "SIMULATION_GENERATED_STATE"
                if disposition == "SIMULATOR_REQUIRED"
                else "MISSINGNESS_INDICATOR"
                if disposition == "INCLUDE_DERIVED_INDICATOR"
                else "PREGAME_FEATURE"
            )
            eligible = True
            governance_status = "ELIGIBLE"
        else:
            family = _extra_family(name)
            data_type = (
                "categorical"
                if name.endswith(("_rivalry_pair", "_rivalry_mapping_missing"))
                else "numeric"
            )
            core = False
            missing_percent = 0.0
            role = (
                "MISSINGNESS_INDICATOR"
                if name.endswith("_rivalry_mapping_missing")
                else "PREGAME_FEATURE"
            )
            # These two indicators are the important adversarial case: the
            # pre-spec inventory exposed them, so the combined authority must
            # explicitly hold them closed rather than silently omit them.
            eligible = name.endswith("_rivalry_mapping_missing")
            governance_status = (
                "ELIGIBLE" if eligible else "INACTIVE_PENDING_RIVALRY_APPROVAL"
            )
        rows.append(
            {
                "order": order,
                "name": name,
                "featureFamily": family,
                "dataType": data_type,
                "role": role,
                "core": core,
                "contextual": name not in GOLD_FEATURES,
                "binary": bool(
                    scientific
                    and scientific["semantic_class"]
                    in {"Binary indicator", "Missingness indicator"}
                ),
                "simulationGeneratedState": bool(
                    scientific
                    and scientific["recommended_inclusion"] == "SIMULATOR_REQUIRED"
                ),
                "governanceStatus": governance_status,
                "eligible": eligible,
                "availabilityStatus": "AVAILABLE_IN_EXACT_CONTEXTUAL_GOLD",
                "sourceLineage": f"accepted-current-gold::{name}",
                "pointInTimeTreatment": "source.game_date < target.game_date",
                "coverageDevelopment": 1.0 - missing_percent / 100.0,
                "missingPercentDevelopment": missing_percent,
            }
        )
    return rows


def _authority(tmp_path: Path) -> tuple[SimpleNamespace, Path]:
    gold_path = tmp_path / "immutable-current-gold.parquet"
    gold_path.write_bytes(b"immutable-current-gold-sentinel")
    public = {
        "projectId": PROJECT_ID,
        "sourceDatasetId": "asp.mlb.statcast.current-pa.v1",
        "sourceManifestSha": "1" * 64,
        "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
        "goldManifestSha": "2" * 64,
        "contextualDatasetId": "gold-table:gold_mlb_current_pa_context_v2",
        "contextualManifestSha": "3" * 64,
        "exclusionMembershipArtifactSha": "4" * 64,
        "reviewDigest": "5" * 64,
    }
    authority = SimpleNamespace(
        project_id=PROJECT_ID,
        registration_id="registration-current",
        dataset_version_id="current-pa-v1",
        activation_revision=7,
        source_dataset_id=public["sourceDatasetId"],
        source_manifest_sha=public["sourceManifestSha"],
        source_publication_sha="6" * 64,
        gold_manifest_sha=public["goldManifestSha"],
        contextual_manifest_sha=public["contextualManifestSha"],
        review_digest=public["reviewDigest"],
        paths=(gold_path,),
        schema=SimpleNamespace(
            names=tuple(ORDERED_GOLD_PLUS_CONTEXT_FEATURES)
            + ("game_date", "outcome", "canonicalPaId")
        ),
        public=lambda: dict(public),
    )
    return authority, gold_path


@pytest.fixture()
def governed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    source = _source()
    authority, gold_path = _authority(tmp_path)
    holder: dict[str, Any] = {
        "authority": authority,
        "rows": _backend_rows(source),
    }

    def resolve(_database: Database, project_id: str) -> SimpleNamespace:
        assert project_id == PROJECT_ID
        return holder["authority"]

    def feature_catalog(_authority_value: object):
        rows = deepcopy(holder["rows"])
        return rows, {str(row["name"]): row for row in rows}

    def treatment_catalog(_authority_value: object):
        return {
            str(row["name"]): {
                "name": row["name"],
                "dataType": row["dataType"],
                "role": row["role"],
                "category": row["featureFamily"],
                "featureFamily": row["featureFamily"],
                "selectable": bool(row["eligible"]),
            }
            for row in holder["rows"]
        }

    monkeypatch.setattr(specification.eda, "_resolve_authority", resolve)
    monkeypatch.setattr(feature_engineering, "_catalog", feature_catalog)
    monkeypatch.setattr(treatments, "_catalog", treatment_catalog)
    monkeypatch.setattr(
        specification.eda,
        "_scan",
        lambda *_args, **_kwargs: pytest.fail(
            "Treatment-spec compilation/drafting must not scan development or final-OOT rows."
        ),
    )
    database = Database(tmp_path / "stage3-feature-treatment-spec.db")
    database.initialize()
    return SimpleNamespace(
        database=database,
        authority=authority,
        authority_holder=holder,
        inventory_holder=holder,
        source=source,
        gold_path=gold_path,
        authority_key=treatments._authority_payload(authority)["authorityKey"],
    )


def _by_name(compiled: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["feature_name"]): row for row in compiled["features"]}


def _save(governed: SimpleNamespace, checksum: str | None = None) -> dict[str, Any]:
    compiled = specification.compile_project_specification(
        governed.database, PROJECT_ID
    )
    return specification.save_treatment_specification_draft(
        governed.database,
        PROJECT_ID,
        {
            "authorityKey": governed.authority_key,
            "expectedManifestChecksum": checksum or compiled["manifestChecksum"],
        },
        actor_user_id="scientist-1",
    )


def test_compiler_parses_exact_unique_240_row_contract_and_persists_workbook_hash(
    tmp_path: Path,
) -> None:
    """Backend properties 1, 2, and 6 (source artifact side)."""

    source = _source()
    assert len(source["features"]) == 240
    assert len({row["feature_name"] for row in source["features"]}) == 240
    assert source["source_workbook"]["sha256"] == WORKBOOK_SHA256
    assert source["source_workbook"]["required_columns"] == list(REQUIRED_COLUMNS)

    workbook_path = tmp_path / "feature-treatment.xlsx"
    _write_source_workbook(workbook_path, source)
    compiled = compile_workbook(workbook_path)
    assert len(compiled["features"]) == 240
    assert len({row["feature_name"] for row in compiled["features"]}) == 240
    assert compiled["source_workbook"]["sha256"] == hashlib.sha256(
        workbook_path.read_bytes()
    ).hexdigest()


def test_compiler_rejects_duplicate_keys_and_changed_workbook_gets_new_identity(
    tmp_path: Path,
) -> None:
    """Backend properties 2 and 28 (workbook identity side)."""

    source = _source()
    duplicate_path = tmp_path / "duplicate.xlsx"
    _write_source_workbook(duplicate_path, source, duplicate_first_feature=True)
    with pytest.raises(WorkbookSpecificationError, match="Duplicate feature names"):
        compile_workbook(duplicate_path)

    workbook_path = tmp_path / "changed.xlsx"
    _write_source_workbook(workbook_path, source)
    before = compile_workbook(workbook_path)
    workbook = load_workbook(workbook_path)
    matrix = workbook[PRIMARY_SHEET]
    rationale_column = list(REQUIRED_COLUMNS).index("Scientific Rationale") + 1
    matrix.cell(row=2, column=rationale_column).value += " Reviewed source revision."
    workbook.save(workbook_path)
    workbook.close()
    after = compile_workbook(workbook_path)
    assert after["source_workbook"]["sha256"] != before["source_workbook"]["sha256"]
    assert after["source_artifact_id"] != before["source_artifact_id"]


def test_exact_reconciliation_has_no_fuzzy_path_and_holds_all_extras_closed(
    governed: SimpleNamespace,
) -> None:
    """Backend properties 3, 4, and 5."""

    compiled = specification.compile_project_specification(
        governed.database, PROJECT_ID
    )
    reconciliation = compiled["reconciliation"]
    assert reconciliation["workbookFeatureCount"] == 240
    assert reconciliation["backendFeatureCount"] == 254
    assert reconciliation["exactMatchCount"] == 240
    assert reconciliation["unmatchedWorkbookFeatures"] == []
    assert reconciliation["fuzzyMatchesUsed"] == 0
    assert reconciliation["fatal"] is False
    additional = reconciliation["additionalBackendFeatures"]
    assert [row["featureName"] for row in additional] == list(
        specification.EXPECTED_ADDITIONAL_FEATURES
    )
    assert len(additional) == 14
    assert all(row["executableSelectable"] is False for row in additional)
    exposed_mapping_indicators = [row for row in additional if row["backendEligibility"]]
    assert {row["featureName"] for row in exposed_mapping_indicators} == {
        "batting_rivalry_mapping_missing",
        "fielding_rivalry_mapping_missing",
    }
    assert all(
        row["executableResolution"] == "HELD_CLOSED_NO_TREATMENT_INFERRED"
        for row in additional
    )

    adversarial_source = deepcopy(governed.source)
    adversarial_source["features"][0]["feature_name"] = (
        str(adversarial_source["features"][0]["feature_name"]).upper()
    )
    rejected = specification._reconcile(governed.authority, adversarial_source)
    assert rejected["exactMatchCount"] == 239
    assert rejected["fuzzyMatchesUsed"] == 0
    assert rejected["fatal"] is True
    assert rejected["unmatchedWorkbookFeatures"] == [
        "FIELDING_HOURS_SINCE_PREVIOUS_GAME_END"
    ]


def test_project_compilation_is_deterministic_and_inventory_changes_identity(
    governed: SimpleNamespace,
) -> None:
    """Backend properties 7 and 28 (feature-inventory identity side)."""

    first = specification.compile_project_specification(governed.database, PROJECT_ID)
    second = specification.compile_project_specification(governed.database, PROJECT_ID)
    assert second["manifestChecksum"] == first["manifestChecksum"]
    assert second["specificationId"] == first["specificationId"]
    assert second == first

    changed_rows = deepcopy(governed.inventory_holder["rows"])
    changed_rows[0]["sourceLineage"] += "::new-governed-version"
    governed.inventory_holder["rows"] = changed_rows
    changed = specification.compile_project_specification(governed.database, PROJECT_ID)
    assert changed["reconciliation"]["fatal"] is False
    assert changed["featureInventorySha256"] != first["featureInventorySha256"]
    assert changed["manifestChecksum"] != first["manifestChecksum"]
    assert changed["specificationId"] != first["specificationId"]


def test_semantic_execution_mapping_is_fail_closed_and_never_uses_blanket_iqr(
    governed: SimpleNamespace,
) -> None:
    """Backend properties 11 through 20."""

    compiled = specification.compile_project_specification(governed.database, PROJECT_ID)
    rows = _by_name(compiled)
    outlier_input, missing_input = specification._policy_inputs(compiled)
    assert outlier_input["globalMethod"] == "NO_STATISTICAL_DETECTION"
    assert outlier_input["globalTreatment"] == "RETAIN"

    source_blocked = {
        "batting_hours_since_previous_game_end",
        "fielding_hours_since_previous_game_end",
        "batting_altitude_change_feet",
        "fielding_altitude_change_feet",
    }
    coverage_blocked = {
        "batting_previous_game_duration_minutes",
        "fielding_previous_game_duration_minutes",
    }
    for name in source_blocked | coverage_blocked:
        assert rows[name]["executable_selectable"] is False
        assert missing_input["overrides"][name]["method"] == "DROP_VARIABLE"
        assert missing_input["overrides"][name]["method"] not in {
            "MEAN",
            "MEDIAN",
            "MODE",
            "CONSTANT",
        }

    doubleheader = rows["doubleheader_game_number"]
    holiday = rows["holiday_name"]
    assert doubleheader["executable_status"] == "BLOCKED"
    assert missing_input["overrides"]["doubleheader_game_number"]["method"] != "MEDIAN"
    assert holiday["executable_status"] == "BLOCKED"
    assert missing_input["overrides"]["holiday_name"]["method"] != "MODE"

    binary = [row for row in compiled["features"] if row["semantic_class"] == "Binary indicator"]
    categorical = [row for row in compiled["features"] if row["data_type"] == "categorical"]
    assert len(binary) == 73
    assert all(
        row["execution_contract"]["outlier"]["detector"]
        == "REGISTERED_BOOLEAN_DOMAIN_VALIDATION"
        for row in binary
    )
    assert all(
        (outlier_input["overrides"].get(row["feature_name"]) or {}).get("treatment")
        not in {"CAP_IQR", "WINSORIZE"}
        for row in categorical
    )
    ordinary_categories = [
        row
        for row in categorical
        if row["semantic_class"]
        not in {"Binary indicator", "Missingness indicator"}
        and row["recommended_inclusion"]
        not in {
            "EXCLUDE_UNTIL_SOURCE_REPAIRED",
            "EXCLUDE_UNTIL_COVERAGE_REPAIRED",
        }
    ]
    assert all(
        row["execution_contract"]["outlier"]["detector"]
        == "ALLOWED_CATEGORY_SEMANTIC_VALIDATION"
        for row in ordinary_categories
    )

    cyclic = [row for row in compiled["features"] if row["semantic_class"] == "Cyclic encoding"]
    assert len(cyclic) == 6
    assert all(row["logical_domain"] == "[-1,1]" for row in cyclic)
    assert all(
        row["execution_contract"]["outlier"]["detector"]
        == "HARD_BOUNDS_MINUS_ONE_TO_ONE"
        for row in cyclic
    )
    rates = [row for row in compiled["features"] if row["semantic_class"] == "Rate / skill estimate"]
    assert len(rates) == 21
    assert all(
        str(row["logical_domain"]).startswith(("[0,", ">=0"))
        or str(row["logical_domain"]).startswith("Registered semantic domain")
        for row in rates
    )
    assert all(
        row["execution_contract"]["outlier"]["detector"]
        == "PHYSICAL_BOUNDS_AND_DENOMINATOR_VALIDATION"
        for row in rates
    )

    simulator = [row for row in compiled["features"] if row["recommended_inclusion"] == "SIMULATOR_REQUIRED"]
    assert len(simulator) == 5
    assert all(row["executable_resolution"] == "REQUIRE_VALID_SIMULATOR_STATE_NO_IMPUTATION" for row in simulator)
    assert all(
        row["execution_contract"]["outlier"]["detector"]
        == "STATE_MACHINE_VALIDATION"
        for row in simulator
    )
    assert all(
        missing_input["overrides"][row["feature_name"]]["method"]
        not in {"MEAN", "MEDIAN", "MODE", "CONSTANT", "PREDICTED"}
        for row in simulator
    )

    interactions = [
        row
        for row in compiled["features"]
        if row["recommended_inclusion"] == "RECOMPUTE_AFTER_PARENT_TREATMENT"
    ]
    assert len(interactions) == 8
    assert all(row["interaction_parent_lineage"] for row in interactions)
    assert all(len(row["execution_contract"]["lineage"]["parentFeatures"]) == 2 for row in interactions)
    assert all(
        row["execution_contract"]["lineage"]["transformationOrder"]
        == [
            "TREAT_PARENTS_INSIDE_TRAINING_FOLD",
            "RECOMPUTE_INTERACTION",
            "APPLY_FROZEN_PIPELINE",
        ]
        for row in interactions
    )
    assert all(
        row["executable_resolution"]
        == "HOLD_UNTIL_PARENT_FIRST_FOLD_LOCAL_RECOMPUTATION_IS_REGISTERED"
        for row in interactions
    )

    _save(governed)
    for blocked_name in (
        "fielding_hours_since_previous_game_end",
        "batting_previous_game_duration_minutes",
    ):
        with pytest.raises(feature_engineering.Stage3FeatureEngineeringError) as caught:
            feature_engineering.save_feature_set_draft(
                PROJECT_ID,
                governed.database,
                {
                    "authorityKey": governed.authority_key,
                    "featureSetKey": f"blocked-{blocked_name}",
                    "name": f"Blocked {blocked_name}",
                    "orderedFeatures": [blocked_name],
                    "expectedChecksum": NO_CURRENT_FEATURE_SET,
                },
                "scientist-1",
            )
        assert caught.value.code == "FEATURE_SET_INACTIVE_FEATURE"


def test_fold_local_model_family_and_indicator_contracts_are_explicit(
    governed: SimpleNamespace,
) -> None:
    """Backend properties 21 through 25."""

    compiled = specification.compile_project_specification(governed.database, PROJECT_ID)
    outlier_input, missing_input = specification._policy_inputs(compiled)
    _outlier_method, _outlier_policy, outlier_fitting, _ = treatments._validate_policy_payload(
        governed.database, governed.authority, "OUTLIER", outlier_input
    )
    _missing_method, _missing_policy, missing_fitting, _ = treatments._validate_policy_payload(
        governed.database, governed.authority, "IMPUTATION", missing_input
    )
    for fitting in (outlier_fitting, missing_fitting):
        assert fitting["fitScope"] == "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY"
        assert fitting["validationTransform"] == "PARAMETERS_FROM_CORRESPONDING_TRAINING_FOLD_ONLY"
        assert fitting["finalOotParameterFittingProhibited"] is True
        assert fitting["targetOutcomeInputsProhibited"] is True

    fallbacks = [
        row
        for row in compiled["features"]
        if row["executable_status"] == "READY_WITH_EXPLICIT_FALLBACK"
    ]
    assert len(fallbacks) == 22
    assert all(
        row["model_family_resolution"]["tree_native_missing"]
        != row["model_family_resolution"]["dense_matrix"]
        for row in fallbacks
    )
    assert all(
        row["model_family_resolution"]["fallback_label"]
        == "INTERIM_TECHNICAL_FALLBACK"
        for row in fallbacks
    )

    governed_prior_rows = [
        row
        for row in compiled["features"]
        if row["recommended_inclusion"]
        in {
            "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
            "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
        }
    ]
    assert len(governed_prior_rows) == 24
    assert all(
        row["execution_contract"]["missing"]["strategy"]
        == "GOVERNED_PRIOR_REQUIRED_NOT_IMPLEMENTED"
        for row in governed_prior_rows
    )
    assert all(not row["executable_selectable"] for row in governed_prior_rows)

    indicators = [
        row
        for row in compiled["features"]
        if row["recommended_inclusion"] == "INCLUDE_DERIVED_INDICATOR"
    ]
    assert len(indicators) == 42
    assert all(row["exact_name_match"] for row in indicators)
    assert all(row["source_or_lineage_identity"] for row in indicators)
    assert all(
        row["executable_resolution"]
        == "DETERMINISTIC_BOOLEAN_RECOMPUTATION_NO_STATISTICAL_IMPUTATION"
        for row in indicators
    )
    # A physically complete indicator column is not evidence that the flag is
    # beneficial.  Preserve the workbook's exact semantics: prior-state flags
    # can describe genuine baseball state or cold start, while every indicator
    # remains subject to source-era/extraction/pipeline drift review.
    assert all(row["missing_percent"] == 0 for row in indicators)
    assert all(
        "No statistical imputation" in row["missing_treatment"]
        for row in indicators
    )
    assert all(
        "monitor source-era leakage and drift" in row["model_handling"]
        for row in indicators
    )
    indicator_names = {row["feature_name"] for row in indicators}
    assert {
        "batting_previous_game_missing",
        "fielding_previous_game_missing",
    } <= indicator_names
    prior_state_or_cold_start = {
        name
        for name in indicator_names
        if "_previous_" in name or "recent_bullpen_workload" in name
    }
    source_extraction_or_pipeline = indicator_names - prior_state_or_cold_start
    assert len(prior_state_or_cold_start) == 20
    assert len(source_extraction_or_pipeline) == 22
    paired = {
        indicator
        for row in compiled["features"]
        for indicator in row["execution_contract"]["lineage"]["pairedIndicators"]
    }
    exact_names = {row["feature_name"] for row in compiled["features"]}
    assert paired
    assert paired <= exact_names

    unsupported = specification._execution_contract("UNREGISTERED_RECOMMENDATION")
    assert unsupported["executableStatus"] == "BLOCKED"
    assert unsupported["selectable"] is False
    assert unsupported["fallbackLabel"] is None
    assert "no registered executable mapping" in unsupported["blockedReason"]


def test_combined_draft_is_append_only_idempotent_and_does_not_touch_gold_or_oot(
    governed: SimpleNamespace,
) -> None:
    """Backend properties 6, 9, 10, and 27."""

    gold_before = hashlib.sha256(governed.gold_path.read_bytes()).hexdigest()
    first = _save(governed)["data"]
    draft_summary = first["draft"]
    draft = Stage3TreatmentRepository(governed.database).combined_spec_state(
        PROJECT_ID, governed.authority.review_digest
    )["latestDraft"]
    assert draft_summary["status"] == "DRAFT"
    assert draft_summary["specificationDraftId"] == draft["specificationId"]
    assert draft["sourceWorkbookSha256"] == WORKBOOK_SHA256
    assert draft["manifestChecksum"] == first["specification"]["manifestChecksum"]
    assert draft["goldManifestSha"] == governed.authority.gold_manifest_sha
    assert draft["finalOot"]["locked"] is True
    assert draft["manifest"]["finalOotIdentity"]["targetsAccessed"] is False
    assert draft["immutable"] is True
    assert first["audit"] == {
        "sourceRowsMutated": 0,
        "goldRowsMutated": 0,
        "finalOotRowsOpened": 0,
        "finalOotTargetsAccessed": False,
        "preprocessingFits": 0,
        "modelFits": 0,
        "scores": 0,
        "calibrations": 0,
        "promotions": 0,
        "providerCalls": 0,
    }

    second = _save(governed)["data"]
    assert second["draft"]["specificationDraftId"] == draft["specificationId"]
    assert second["draft"]["checksum"] == draft["checksum"]
    with governed.database.connection() as connection:
        spec_count = connection.execute(
            "SELECT COUNT(*) FROM stage3_feature_treatment_spec_versions"
        ).fetchone()[0]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM stage3_feature_treatment_spec_events"
        ).fetchone()[0]
    assert spec_count == 1
    assert event_count == 1
    assert hashlib.sha256(governed.gold_path.read_bytes()).hexdigest() == gold_before

    with governed.database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE stage3_feature_treatment_spec_versions SET notes = 'changed' "
                "WHERE feature_treatment_spec_id = ?",
                (draft["specificationId"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM stage3_feature_treatment_spec_versions "
                "WHERE feature_treatment_spec_id = ?",
                (draft["specificationId"],),
            )


def test_existing_adopted_policies_remain_exactly_immutable(
    governed: SimpleNamespace,
) -> None:
    """Backend property 8."""

    repository = Stage3TreatmentRepository(governed.database)
    authority = treatments._persistence_authority(governed.authority)
    fitting = {
        "fitScope": "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY",
        "validationTransform": "PARAMETERS_FROM_CORRESPONDING_TRAINING_FOLD_ONLY",
        "finalOotParameterFittingProhibited": True,
        "targetOutcomeInputsProhibited": True,
    }
    adopted_ids: dict[str, str] = {}
    for kind in ("OUTLIER", "IMPUTATION"):
        draft = repository.save_draft(
            authority=authority,
            policy_kind=kind,
            global_method="DOMAIN_BOUNDS" if kind == "OUTLIER" else "DATA_TYPE_AWARE",
            policy={"legacyAdoptedSentinel": kind},
            fitting_rule=fitting,
            notes="pre-existing adopted policy",
            actor_user_id="prior-scientist",
        )
        adopted = repository.adopt(
            project_id=PROJECT_ID,
            policy_kind=kind,
            authority_review_digest=governed.authority.review_digest,
            draft_policy_id=str(draft["policyId"]),
            actor_user_id="prior-scientist",
        )
        adopted_ids[kind] = str(adopted["policyId"])

    with governed.database.connection() as connection:
        before = {
            row["treatment_policy_id"]: tuple(row)
            for row in connection.execute(
                "SELECT * FROM stage3_treatment_policy_versions "
                "WHERE policy_status = 'ADOPTED' ORDER BY treatment_policy_id"
            ).fetchall()
        }
    result = _save(governed)["data"]
    assert result["adoptionPerformed"] is False
    assert result["adoptedSpecification"] is None
    assert {
        result["priorPolicies"]["outlier"]["policyId"],
        result["priorPolicies"]["missing"]["policyId"],
    } == set(adopted_ids.values())
    with governed.database.connection() as connection:
        after = {
            row["treatment_policy_id"]: tuple(row)
            for row in connection.execute(
                "SELECT * FROM stage3_treatment_policy_versions "
                "WHERE policy_status = 'ADOPTED' ORDER BY treatment_policy_id"
            ).fetchall()
        }
    assert after == before


def test_combined_draft_blocks_every_individual_policy_adoption(
    governed: SimpleNamespace,
) -> None:
    saved = _save(governed)["data"]["draft"]
    repository = Stage3TreatmentRepository(governed.database)
    child_ids = {
        "OUTLIER": saved["outlierPolicyRef"]["policyId"],
        "IMPUTATION": saved["missingPolicyRef"]["policyId"],
    }

    for kind, policy_id in child_ids.items():
        with pytest.raises(
            Stage3TreatmentPersistenceError, match="unadopted combined"
        ):
            repository.adopt(
                project_id=PROJECT_ID,
                policy_kind=kind,
                authority_review_digest=governed.authority.review_digest,
                draft_policy_id=policy_id,
                actor_user_id="scientist-1",
            )

    with governed.database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM stage3_treatment_policy_versions "
            "WHERE policy_status = 'ADOPTED'"
        ).fetchone()[0] == 0

    authority = treatments._persistence_authority(governed.authority)
    fitting_rule = {
        "fitScope": "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY",
        "validationTransform": "PARAMETERS_FROM_CORRESPONDING_TRAINING_FOLD_ONLY",
        "finalOotParameterFittingProhibited": True,
        "targetOutcomeInputsProhibited": True,
    }
    for kind in ("OUTLIER", "IMPUTATION"):
        legacy = repository.save_draft(
            authority=authority,
            policy_kind=kind,
            global_method=("DOMAIN_BOUNDS" if kind == "OUTLIER" else "DATA_TYPE_AWARE"),
            policy={"unrelatedLegacyDraft": kind},
            fitting_rule=fitting_rule,
            notes="unrelated legacy draft",
            actor_user_id="legacy-scientist",
        )
        with pytest.raises(
            Stage3TreatmentPersistenceError, match="combined feature-treatment"
        ):
            repository.adopt(
                project_id=PROJECT_ID,
                policy_kind=kind,
                authority_review_digest=governed.authority.review_digest,
                draft_policy_id=str(legacy["policyId"]),
                actor_user_id="legacy-scientist",
            )

    with governed.database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM stage3_treatment_policy_versions "
            "WHERE policy_status = 'ADOPTED'"
        ).fetchone()[0] == 0


def test_stale_gold_authority_cannot_apply_prior_compilation(
    governed: SimpleNamespace,
) -> None:
    """Backend property 26."""

    compiled = specification.compile_project_specification(governed.database, PROJECT_ID)
    stale_key = governed.authority_key
    replacement = deepcopy(governed.authority)
    replacement.gold_manifest_sha = "9" * 64
    replacement_public = replacement.public()
    replacement_public["goldManifestSha"] = replacement.gold_manifest_sha
    replacement.public = lambda: dict(replacement_public)
    governed.authority_holder["authority"] = replacement

    with pytest.raises(treatments.Stage3TreatmentError) as caught:
        specification.save_treatment_specification_draft(
            governed.database,
            PROJECT_ID,
            {
                "authorityKey": stale_key,
                "expectedManifestChecksum": compiled["manifestChecksum"],
            },
            actor_user_id="scientist-1",
        )
    assert caught.value.code == "TREATMENT_AUTHORITY_STALE"


def test_disposition_counts_and_adoption_gate_are_source_derived(
    governed: SimpleNamespace,
) -> None:
    compiled = specification.compile_project_specification(governed.database, PROJECT_ID)
    assert compiled["dispositionCounts"] == dict(
        sorted(specification.EXPECTED_DISPOSITION_COUNTS.items())
    )
    assert sum(compiled["dispositionCounts"].values()) == 240
    assert Counter(
        row["scientific_recommendation"] for row in compiled["features"]
    ) == Counter(specification.EXPECTED_DISPOSITION_COUNTS)
    assert compiled["canCreateDraft"] is True
    assert compiled["canAdopt"] is False
    with pytest.raises(specification.Stage3FeatureTreatmentSpecError) as caught:
        specification.adopt_treatment_specification(
            governed.database,
            PROJECT_ID,
            {"authorityKey": governed.authority_key},
            actor_user_id="scientist-1",
        )
    assert caught.value.code == "TREATMENT_SPEC_DRAFT_REQUIRED"

    saved = _save(governed)["data"]["draft"]
    base = {
        "authorityKey": governed.authority_key,
        "expectedManifestChecksum": saved["manifestChecksum"],
    }
    with pytest.raises(specification.Stage3FeatureTreatmentSpecError) as caught:
        specification.adopt_treatment_specification(
            governed.database,
            PROJECT_ID,
            {**base, "specificationDraftId": "not-the-current-draft"},
            actor_user_id="scientist-1",
        )
    assert caught.value.code == "TREATMENT_SPEC_DRAFT_NOT_CURRENT"

    with pytest.raises(specification.Stage3FeatureTreatmentSpecError) as caught:
        specification.adopt_treatment_specification(
            governed.database,
            PROJECT_ID,
            {
                "authorityKey": governed.authority_key,
                "specificationDraftId": saved["specificationDraftId"],
                "expectedManifestChecksum": "0" * 64,
            },
            actor_user_id="scientist-1",
        )
    assert caught.value.code == "TREATMENT_SPEC_DRAFT_CHECKSUM_MISMATCH"

    with pytest.raises(specification.Stage3FeatureTreatmentSpecError) as caught:
        specification.adopt_treatment_specification(
            governed.database,
            PROJECT_ID,
            {
                **base,
                "specificationDraftId": saved["specificationDraftId"],
            },
            actor_user_id="scientist-1",
        )
    assert caught.value.code == "TREATMENT_SPEC_ADOPTION_BLOCKED"

from __future__ import annotations

import copy
import hashlib
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast import stage3_feature_treatment_spec as specification
from server.sports_current_statcast import stage3_player_prior_authority as prior
from server.sports_datasets.consumer import canonical_json_bytes


EXPECTED_PRIOR_ORDER = (
    "pitcher_whip",
    "pitcher_era9",
    "pitcher_so_per_bfp",
    "pitcher_hr_per_bfp",
    "pitcher_hbp_per_bfp",
    "pitcher_gs_per_g",
    "pitcher_bb_per_bfp",
    "batter_so_per_pa",
    "batter_slg",
    "batter_obp",
    "batter_hr_per_pa",
    "batter_bb_hbp_per_pa",
    "batter_avg",
    "pitcher_last250_avg_fastball_velocity",
    "pitcher_last250_whiff_rate",
    "pitcher_last250_walk_rate",
    "pitcher_last250_strikeout_rate",
    "pitcher_last250_offspeed_usage",
    "pitcher_last250_fastball_usage",
    "pitcher_last250_breaking_usage",
    "batter_last100_whiff_rate",
    "batter_last100_contact_rate",
    "batter_last100_walk_hbp_rate",
    "batter_last100_strikeout_rate",
)

EXPECTED_READY = frozenset(
    {
        "pitcher_so_per_bfp",
        "pitcher_hr_per_bfp",
        "pitcher_hbp_per_bfp",
        "pitcher_bb_per_bfp",
        "batter_so_per_pa",
        "batter_hr_per_pa",
        "batter_bb_hbp_per_pa",
        "pitcher_last250_walk_rate",
        "pitcher_last250_strikeout_rate",
        "batter_last100_walk_hbp_rate",
        "batter_last100_strikeout_rate",
    }
)

EXPECTED_BLOCKS = {
    "pitcher_whip": (
        "WHIP requires prior IPouts plus BB and H; BFP is not its denominator and "
        "those sufficient statistics are not materialized in Current Gold."
    ),
    "pitcher_era9": (
        "ERA9 requires prior IPouts and ER; BFP is not its denominator and those "
        "sufficient statistics are not materialized in Current Gold."
    ),
    "pitcher_gs_per_g": (
        "GS/G requires exact prior games and games-started counts; BFP is not a "
        "valid opportunity denominator and neither count is materialized in Current Gold."
    ),
    "batter_slg": (
        "SLG requires exact at-bats and total-base components; prior PA is not its "
        "denominator and the sufficient statistics are not materialized in Current Gold."
    ),
    "batter_obp": (
        "OBP requires AB+BB+HBP+SF opportunities; prior PA also includes sacrifice "
        "hits and cannot be substituted for the unmaterialized denominator."
    ),
    "batter_avg": (
        "AVG requires exact at-bats and hits; prior PA is not its denominator and "
        "at-bats are not materialized in Current Gold."
    ),
    "pitcher_last250_avg_fastball_velocity": (
        "Velocity shrinkage requires eligible-fastball count and within-window variance; "
        "the materialized BF count is not a velocity observation count."
    ),
    "pitcher_last250_whiff_rate": (
        "Pitcher whiff rate requires the exact classifiable-swing count; BF count is "
        "not the denominator and swing count is not materialized in Current Gold."
    ),
    "pitcher_last250_offspeed_usage": (
        "Pitch usage requires the exact all-pitch opportunity count; BF count is not "
        "the denominator and pitch count is not materialized in Current Gold."
    ),
    "pitcher_last250_fastball_usage": (
        "Pitch usage requires the exact all-pitch opportunity count; BF count is not "
        "the denominator and pitch count is not materialized in Current Gold."
    ),
    "pitcher_last250_breaking_usage": (
        "Pitch usage requires the exact all-pitch opportunity count; BF count is not "
        "the denominator and pitch count is not materialized in Current Gold."
    ),
    "batter_last100_whiff_rate": (
        "Batter whiff rate requires the exact classifiable-swing count; PA count is "
        "not the denominator and swing count is not materialized in Current Gold."
    ),
    "batter_last100_contact_rate": (
        "Batter contact rate requires the exact classifiable-swing count; PA count is "
        "not the denominator and swing count is not materialized in Current Gold."
    ),
}

EXPECTED_RETIRED = frozenset(
    {"pitcher_era9", "batter_obp", "batter_last100_contact_rate"}
)
EXPECTED_WAVE2 = frozenset(EXPECTED_BLOCKS) - EXPECTED_RETIRED
EXPECTED_WAVE2_EXPOSURES = {
    "pitcher_whip": "pitcher_prior_ipouts",
    "pitcher_gs_per_g": "pitcher_prior_g",
    "batter_slg": "batter_prior_ab",
    "batter_avg": "batter_prior_ab",
    "pitcher_last250_avg_fastball_velocity": (
        "pitcher_last250_fastball_velocity_count"
    ),
    "pitcher_last250_whiff_rate": "pitcher_last250_swing_count",
    "pitcher_last250_offspeed_usage": "pitcher_last250_pitch_count",
    "pitcher_last250_fastball_usage": "pitcher_last250_pitch_count",
    "pitcher_last250_breaking_usage": "pitcher_last250_pitch_count",
    "batter_last100_whiff_rate": "batter_last100_swing_count",
}


def _stable_fitted(fitted: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in fitted.items() if key != "fitDurationMs"}


def _authority_manifest() -> dict[str, object]:
    return prior.project_authority_manifest(
        {
            "projectId": "asp-synthetic-prior-test",
            "goldDatasetId": "gold-table:synthetic-current-pa",
            "goldManifestSha": "1" * 64,
            "contextualDatasetId": "gold-table:synthetic-current-pa-context",
            "contextualManifestSha": "2" * 64,
            "reviewDigest": "3" * 64,
        },
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="4" * 64,
    )


def _sufficient_statistics_authority(
    *,
    gold_manifest_sha256: str = "1" * 64,
    manifest_sha256: str = "5" * 64,
    object_sha256: tuple[str, ...] = ("6" * 64, "7" * 64),
) -> dict[str, object]:
    required_columns = sorted(
        {
            column
            for feature in EXPECTED_WAVE2
            for column in prior.feature_binding(feature)["requiredSufficientStatistics"]
        }
    )
    content: dict[str, object] = {
        "schemaVersion": prior.SUFFICIENT_STATISTICS_AUTHORITY_SCHEMA,
        "datasetId": prior.SUFFICIENT_STATISTICS_DATASET_ID,
        "manifestContract": prior.SUFFICIENT_STATISTICS_MANIFEST_CONTRACT,
        "manifestSha256": manifest_sha256,
        "objectSha256": list(object_sha256),
        "sourceGoldManifestSha256": gold_manifest_sha256,
        "physicalSchemaSha256": "8" * 64,
        "validationEvidenceSha256": "9" * 64,
        "requiredColumns": required_columns,
        "verified": True,
        "integerValidation": True,
        "equivalenceValidation": True,
        "finalOotSealed": True,
        "rightsStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
    }
    checksum = hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    return {
        **content,
        "authorityChecksum": checksum,
        "authorityId": (
            f"{prior.SUFFICIENT_STATISTICS_AUTHORITY_SCHEMA}:sha256:{checksum}"
        ),
    }


def _resign_authority_manifest(manifest: dict[str, object]) -> None:
    import hashlib

    content = {
        key: value
        for key, value in manifest.items()
        if key not in {"authorityChecksum", "authorityId"}
    }
    checksum = hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    manifest["authorityChecksum"] = checksum
    manifest["authorityId"] = f"{prior.AUTHORITY_NAME}:sha256:{checksum}"


def _annual_training_frame() -> pd.DataFrame:
    """A is repeated and duplicated; only its latest distinct state may be fit."""

    return pd.DataFrame(
        {
            "canonicalPaId": ["pa-a0", "pa-a1", "pa-a1-copy", "pa-b", "pa-c"],
            "game_date": [
                "2024-01-01",
                "2024-02-01",
                "2024-02-01",
                "2024-02-01",
                "2024-02-01",
            ],
            "batterCanonicalPlayerId": ["A", "A", "A", "B", "C"],
            "batter_so_per_pa": [0.8, 0.2, 0.2, 0.4, 0.1],
            "batter_log1p_pa": np.log1p([10, 100, 100, 100, 100]),
            "batter_prior_missing": [0, 0, 0, 0, 0],
        }
    )


def _fit_annual(frame: pd.DataFrame | None = None) -> dict[str, object]:
    return prior.fit_prior_authority(
        _annual_training_frame() if frame is None else frame,
        training_end="2024-12-31",
        authority_manifest=_authority_manifest(),
        fold_id="fold-1",
        features=["batter_so_per_pa"],
    )


def _rolling_training_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "canonicalPaId": ["pa-a", "pa-b", "pa-c"],
            "game_date": ["2024-04-01", "2024-04-01", "2024-04-01"],
            "batterCanonicalPlayerId": ["A", "B", "C"],
            "batter_last100_strikeout_rate": [0.2, 0.3, 0.1],
            "batter_last100_pa_count": [20, 100, 50],
            "batter_last100_insufficient": [1, 0, 1],
        }
    )


def _fit_rolling() -> dict[str, object]:
    return prior.fit_prior_authority(
        _rolling_training_frame(),
        training_end="2024-12-31",
        authority_manifest=_authority_manifest(),
        fold_id="fold-rolling",
        features=["batter_last100_strikeout_rate"],
    )


def test_binding_inventory_is_exact_deterministic_and_fail_closed() -> None:
    assert prior.PRIOR_FEATURES == EXPECTED_PRIOR_ORDER
    assert prior.SUPPORTED_PRIOR_FEATURES == EXPECTED_READY
    assert prior.BLOCKED_PRIOR_FEATURES == EXPECTED_WAVE2
    assert prior.WAVE2_ENGINE_PRIOR_FEATURES == EXPECTED_WAVE2
    assert prior.RETIRED_PRIOR_FEATURES == EXPECTED_RETIRED
    assert len(prior.PRIOR_FEATURES) == 24
    assert len(prior.SUPPORTED_PRIOR_FEATURES) == 11
    assert len(prior.BLOCKED_PRIOR_FEATURES) == 10
    assert len(prior.RETIRED_PRIOR_FEATURES) == 3

    first = prior.authority_configuration()
    second = prior.authority_configuration()
    assert first == second
    assert first is not second
    assert tuple(binding["feature"] for binding in first["bindings"]) == EXPECTED_PRIOR_ORDER
    for feature in EXPECTED_READY:
        binding = prior.feature_binding(feature)
        assert binding is not None
        assert binding["status"] == "READY_GOVERNED_PRIOR_V1"
        assert binding["executable"] is True
        assert binding["method"] == "BETA_BINOMIAL_EMPIRICAL_BAYES"
        assert binding["exposureFeature"]
        assert binding["blockedReason"] is None
        assert binding["selectable"] is True
    for feature in EXPECTED_WAVE2:
        binding = prior.feature_binding(feature)
        assert binding is not None
        assert binding["status"] == "BLOCKED_REQUIRES_PRIOR_AUTHORITY"
        assert binding["executable"] is False
        assert binding["selectable"] is False
        assert binding["exposureFeature"] == EXPECTED_WAVE2_EXPOSURES[feature]
        assert binding["exposureTransform"] == "VALIDATE_INTEGER"
        assert binding["numeratorComponents"]
        assert binding["compositionComponents"]
        assert binding["componentFields"]["exposure"] == (
            EXPECTED_WAVE2_EXPOSURES[feature]
        )
        assert binding["derivedOutputs"] == {}
        assert binding["rawFeatureDecision"] == (
            "HOLD_RAW_FIELD_NONSELECTABLE_PENDING_WAVE2_ENGINE"
        )
        assert binding["blockedReason"] == EXPECTED_BLOCKS[feature]
        assert binding["requiredEstimator"] in {
            "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES",
            "DIRICHLET_MULTINOMIAL_COMPONENT_SHRINKAGE",
            "GAMMA_POISSON_COMPONENT_SHRINKAGE",
            "NORMAL_NORMAL_EMPIRICAL_BAYES",
        }
    for feature in EXPECTED_RETIRED:
        binding = prior.feature_binding(feature)
        assert binding is not None
        assert (
            binding["status"]
            == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
        )
        assert binding["executable"] is False
        assert binding["selectable"] is False
        assert binding["blockedReason"] is None
        assert binding["scientificDecisionResolved"] is True
        assert binding["registeredDefinition"]
        assert binding["retirementReason"]
        assert binding["componentFields"]["composition"]
        assert binding["derivedOutputs"] == {}
        assert binding["rawFeatureDecision"] == (
            "DROP_RAW_FIELD_RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
        )

    for feature in {
        "pitcher_last250_offspeed_usage",
        "pitcher_last250_fastball_usage",
        "pitcher_last250_breaking_usage",
    }:
        assert "pitcher_last250_other_or_unclassified_pitch_count" in (
            prior.feature_binding(feature)["compositionComponents"]
        )
    slg = prior.feature_binding("batter_slg")
    assert set(slg["derivedComponents"]) == {
        "batter_prior_1b",
        "batter_prior_ab_out",
    }

    configured = {
        binding["feature"]: binding
        for binding in prior.authority_configuration()["bindings"]
    }
    assert all(
        configured[feature]["derivedOutputs"] == {}
        and configured[feature]["rawFeatureDecision"]
        == "HOLD_RAW_FIELD_NONSELECTABLE_PENDING_WAVE2_ENGINE"
        for feature in EXPECTED_WAVE2
    )
    assert all(
        configured[feature]["derivedOutputs"] == {}
        and configured[feature]["rawFeatureDecision"]
        == "DROP_RAW_FIELD_RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
        for feature in EXPECTED_RETIRED
    )

    # Callers cannot mutate the checked-in authority through a returned object.
    first["bindings"][0]["feature"] = "mutated"
    assert prior.authority_configuration() == second
    assert prior.feature_binding("not-a-feature") is None


def test_verified_exact_companion_changes_only_ten_bindings_to_wave2_ready() -> None:
    companion = _sufficient_statistics_authority()
    for feature in EXPECTED_PRIOR_ORDER:
        direct = prior.feature_binding(
            feature,
            sufficient_statistics_authority=companion,
            expected_gold_manifest_sha256="1" * 64,
        )
        nested = prior.feature_binding(
            feature,
            sufficient_statistics_authority={"bindingAuthority": companion},
            expected_gold_manifest_sha256="1" * 64,
        )
        assert direct == nested
        if feature in EXPECTED_WAVE2:
            assert direct["status"] == "BINDING_READY_REQUIRES_WAVE2_ENGINE"
            assert direct["executable"] is False
            assert direct["selectable"] is False
            assert direct["blockedReason"] is None
            assert direct["exposureFeature"] == EXPECTED_WAVE2_EXPOSURES[feature]
            assert direct["numeratorComponents"]
            assert direct["compositionComponents"]
            assert direct["derivedOutputs"] == {}
            assert direct["rawFeatureDecision"] == (
                "HOLD_RAW_FIELD_NONSELECTABLE_PENDING_WAVE2_ENGINE"
            )
            assert direct["estimatorImplementationStatus"] == (
                "NOT_IMPLEMENTED_REQUIRES_WAVE2"
            )
            assert direct["bindingEvidence"]["authorityId"] == companion["authorityId"]
            assert direct["bindingEvidence"]["manifestSha256"] == "5" * 64
            assert direct["bindingEvidence"]["objectSha256"] == ["6" * 64, "7" * 64]
        elif feature in EXPECTED_RETIRED:
            assert direct["status"] == (
                "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
            )
            assert direct["bindingEvidence"] is None
            assert direct["derivedOutputs"] == {}
        else:
            assert direct["status"] == "READY_GOVERNED_PRIOR_V1"
            assert direct["executable"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"authorityChecksum": "0" * 64}),
        lambda value: value.update({"sourceGoldManifestSha256": "2" * 64}),
        lambda value: value.update({"finalOotSealed": False}),
        lambda value: value.update(
            {
                "requiredColumns": [
                    column
                    for column in value["requiredColumns"]
                    if column != "pitcher_last250_fastball_velocity_sumsq"
                ]
            }
        ),
    ],
)
def test_missing_or_invalid_companion_evidence_keeps_wave2_features_blocked(
    mutate,
) -> None:
    companion = _sufficient_statistics_authority()
    mutate(companion)
    binding = prior.feature_binding(
        "pitcher_whip",
        sufficient_statistics_authority=companion,
        expected_gold_manifest_sha256="1" * 64,
    )
    assert binding["status"] == "BLOCKED_REQUIRES_PRIOR_AUTHORITY"
    assert binding["executable"] is False
    assert binding["selectable"] is False
    assert binding["bindingEvidence"] is None


@pytest.mark.parametrize(
    "feature", ["pitcher_whip", "pitcher_era9", "batter_obp"]
)
def test_nonexecutables_cannot_enter_v1_fit_or_transform_inputs(feature: str) -> None:
    with pytest.raises(prior.PlayerPriorAuthorityError) as required_error:
        prior.required_input_columns([feature])
    assert required_error.value.code == "PRIOR_FEATURE_NOT_EXECUTABLE"

    with pytest.raises(prior.PlayerPriorAuthorityError) as fit_error:
        prior.fit_prior_authority(
            _annual_training_frame(),
            training_end="2024-12-31",
            authority_manifest=_authority_manifest(),
            fold_id="non-executable",
            features=[feature],
        )
    assert fit_error.value.code == "PRIOR_FEATURE_NOT_EXECUTABLE"


def test_configuration_and_project_authority_identities_are_content_addressed() -> None:
    configuration = prior.authority_configuration()
    expected_checksum = hashlib.sha256(canonical_json_bytes(configuration)).hexdigest()
    assert prior.authority_checksum() == expected_checksum
    assert len(expected_checksum) == 64
    assert prior.authority_checksum(configuration=copy.deepcopy(configuration)) == expected_checksum
    assert prior.authority_checksum(
        configuration=prior.authority_configuration(overrides={"testOnlyRevision": 2})
    ) != expected_checksum

    authority = SimpleNamespace(
        public=lambda: {
            "projectId": "asp-mtlozhdx",
            "goldDatasetId": "gold:current",
            "goldManifestSha": "1" * 64,
            "contextualDatasetId": "gold:context",
            "contextualManifestSha": "2" * 64,
            "reviewDigest": "3" * 64,
        }
    )
    first = prior.project_authority_manifest(
        authority,
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="4" * 64,
    )
    second = prior.project_authority_manifest(
        authority,
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="4" * 64,
    )
    changed = prior.project_authority_manifest(
        authority,
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="5" * 64,
    )
    assert first == second
    assert first["authorityId"] == f"{prior.AUTHORITY_NAME}:sha256:{first['authorityChecksum']}"
    assert first["configurationChecksum"] == expected_checksum
    assert first["readyFeatureCount"] == 11
    assert first["bindingReadyRequiresWave2EngineFeatureCount"] == 0
    assert first["retiredFeatureCount"] == 3
    assert first["blockedFeatureCount"] == 10
    assert first["featureCount"] == 24
    assert first["featureSets"] == {
        "executable": [
            feature for feature in EXPECTED_PRIOR_ORDER if feature in EXPECTED_READY
        ],
        "bindingReadyRequiresWave2Engine": [],
        "retiredByScientificDecision": [
            feature for feature in EXPECTED_PRIOR_ORDER if feature in EXPECTED_RETIRED
        ],
        "blockedByMissingEvidence": [
            feature for feature in EXPECTED_PRIOR_ORDER if feature in EXPECTED_WAVE2
        ],
    }
    first_bindings = {binding["feature"]: binding for binding in first["bindings"]}
    assert all(
        first_bindings[feature]["derivedOutputs"] == {}
        and first_bindings[feature]["rawFeatureDecision"]
        == "HOLD_RAW_FIELD_NONSELECTABLE_PENDING_WAVE2_ENGINE"
        for feature in EXPECTED_WAVE2
    )
    assert all(
        first_bindings[feature]["derivedOutputs"] == {}
        and first_bindings[feature]["rawFeatureDecision"]
        == "DROP_RAW_FIELD_RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
        for feature in EXPECTED_RETIRED
    )
    assert first["foldLocal"] == first["pointInTime"] == "PASS"
    assert first["finalOotPolicy"] == "LOCKED_NOT_OPENED_NOT_FIT"
    assert changed["authorityId"] != first["authorityId"]

    with_companion = prior.project_authority_manifest(
        authority,
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="4" * 64,
        sufficient_statistics_authority=_sufficient_statistics_authority(),
    )
    assert with_companion["authorityId"] != first["authorityId"]
    assert with_companion["readyFeatureCount"] == 11
    assert with_companion["bindingReadyRequiresWave2EngineFeatureCount"] == 10
    assert with_companion["retiredFeatureCount"] == 3
    assert with_companion["blockedFeatureCount"] == 0
    assert with_companion["featureSets"]["bindingReadyRequiresWave2Engine"] == [
        feature for feature in EXPECTED_PRIOR_ORDER if feature in EXPECTED_WAVE2
    ]
    assert with_companion["featureSets"]["blockedByMissingEvidence"] == []
    companion_bindings = {
        binding["feature"]: binding for binding in with_companion["bindings"]
    }
    assert all(
        companion_bindings[feature]["status"]
        == "BINDING_READY_REQUIRES_WAVE2_ENGINE"
        and companion_bindings[feature]["derivedOutputs"] == {}
        and companion_bindings[feature]["rawFeatureDecision"]
        == "HOLD_RAW_FIELD_NONSELECTABLE_PENDING_WAVE2_ENGINE"
        for feature in EXPECTED_WAVE2
    )
    assert all(
        companion_bindings[feature]["status"]
        == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
        and companion_bindings[feature]["derivedOutputs"] == {}
        and companion_bindings[feature]["rawFeatureDecision"]
        == "DROP_RAW_FIELD_RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
        for feature in EXPECTED_RETIRED
    )
    assert with_companion["sufficientStatisticsAuthority"]["manifestSha256"] == (
        "5" * 64
    )
    assert with_companion["sufficientStatisticsAuthority"]["objectSha256"] == [
        "6" * 64,
        "7" * 64,
    ]
    changed_object = prior.project_authority_manifest(
        authority,
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="4" * 64,
        sufficient_statistics_authority=_sufficient_statistics_authority(
            object_sha256=("6" * 64, "a" * 64)
        ),
    )
    assert changed_object["authorityId"] != with_companion["authorityId"]
    assert changed_object["sufficientStatisticsAuthority"]["objectSha256"] == [
        "6" * 64,
        "a" * 64,
    ]


def test_fit_rejects_tampered_or_stale_project_authority_manifest() -> None:
    frame = _annual_training_frame()
    tampered = _authority_manifest()
    tampered["goldManifestSha"] = "9" * 64
    with pytest.raises(prior.PlayerPriorAuthorityError) as checksum_error:
        prior.fit_prior_authority(
            frame,
            training_end="2024-12-31",
            authority_manifest=tampered,
            fold_id="fold-tampered-authority",
            features=["batter_so_per_pa"],
        )
    assert checksum_error.value.code == "PRIOR_AUTHORITY_CHECKSUM_MISMATCH"

    stale_configuration = _authority_manifest()
    stale_configuration["configurationChecksum"] = "0" * 64
    _resign_authority_manifest(stale_configuration)
    with pytest.raises(prior.PlayerPriorAuthorityError) as configuration_error:
        prior.fit_prior_authority(
            frame,
            training_end="2024-12-31",
            authority_manifest=stale_configuration,
            fold_id="fold-stale-configuration",
            features=["batter_so_per_pa"],
        )
    assert configuration_error.value.code == "PRIOR_AUTHORITY_CONFIGURATION_STALE"


def test_spec_integration_clears_only_the_eleven_executable_bindings() -> None:
    for feature in EXPECTED_PRIOR_ORDER:
        disposition = (
            "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR"
            if feature == "pitcher_last250_avg_fastball_velocity"
            else "HIERARCHICAL_PRIOR_PLUS_INDICATOR"
        )
        execution = specification._execution_contract(feature, disposition)
        structured = specification._structured_execution_contract(
            {
                "feature_name": feature,
                "recommended_inclusion": disposition,
                "outlier_treatment": "Retain after domain validation.",
                "logical_domain": "[0,1]",
                "missing_treatment": "Use the reviewed player prior.",
            },
            {"dataType": "numeric", "binary": False, "sourceLineage": f"gold::{feature}"},
            execution,
        )
        feature_prior = structured["missing"]["priorAuthority"]
        assert feature_prior["authorityName"] == prior.AUTHORITY_NAME
        assert feature_prior["pointInTime"] == feature_prior["foldLocal"] == "PASS"
        if feature in EXPECTED_READY:
            assert execution["executableStatus"] == "READY_GOVERNED_PRIOR_V1"
            assert execution["selectable"] is True
            assert structured["missing"]["strategy"] == (
                "GOVERNED_PLAYER_TO_MLB_LEAGUE_BETA_BINOMIAL_PRIOR_V1"
            )
            assert feature_prior["status"] == "READY_GOVERNED_PRIOR_V1"
            assert feature_prior["blockedReason"] is None
            assert structured["lineage"]["exposureFeature"]
            assert len(structured["lineage"]["derivedPriorOutputs"]) == 17
        elif feature in EXPECTED_WAVE2:
            assert execution["executableStatus"] == "BLOCKED"
            assert execution["selectable"] is False
            assert execution["blockedReason"] == EXPECTED_BLOCKS[feature]
            assert structured["missing"]["strategy"] == (
                "GOVERNED_PRIOR_REQUIRED_EXACT_SUFFICIENT_STATISTIC_UNAVAILABLE"
            )
            assert feature_prior["blockedReason"] == EXPECTED_BLOCKS[feature]
            assert structured["lineage"]["exposureFeature"] == (
                EXPECTED_WAVE2_EXPOSURES[feature]
            )
        else:
            assert feature in EXPECTED_RETIRED
            assert execution["executableStatus"] == (
                "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
            )
            assert execution["selectable"] is False
            assert execution["blockedReason"] is None
            assert structured["selectable"] is False
            assert feature_prior["status"] == (
                "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
            )
            assert feature_prior["blockedReason"] is None


def test_beta_binomial_fit_uses_latest_unique_player_states_and_exact_numerics() -> None:
    frame = _annual_training_frame()
    fitted = _fit_annual(frame)
    parameter = fitted["parameters"]["batter_so_per_pa"]

    trials = np.array([100.0, 100.0, 100.0])
    successes = np.array([20.0, 40.0, 10.0])
    rates = successes / trials
    expected_mean = (successes.sum() + 0.5) / (trials.sum() + 1.0)
    sample_variance = np.var(rates, ddof=1)
    sampling_variance = np.mean(expected_mean * (1.0 - expected_mean) / trials)
    corrected_variance = max(0.0, sample_variance - sampling_variance)
    raw_strength = expected_mean * (1.0 - expected_mean) / corrected_variance - 1.0
    expected_strength = np.clip(raw_strength, 1e-9, np.quantile(trials, 0.95))

    assert parameter["playerStateCount"] == 3
    assert parameter["totalObservedTrials"] == 300
    assert parameter["totalObservedSuccesses"] == 70
    assert parameter["priorMean"] == pytest.approx(expected_mean)
    assert parameter["sampleRateVariance"] == pytest.approx(sample_variance)
    assert parameter["meanBinomialSamplingVariance"] == pytest.approx(sampling_variance)
    assert parameter["correctedBetweenPlayerVariance"] == pytest.approx(corrected_variance)
    assert parameter["priorStrength"] == pytest.approx(expected_strength)
    assert parameter["alpha"] == pytest.approx(expected_mean * expected_strength)
    assert parameter["beta"] == pytest.approx((1.0 - expected_mean) * expected_strength)
    assert parameter["alpha"] + parameter["beta"] == pytest.approx(
        parameter["priorStrength"]
    )

    # The earlier A state and an exact same-day duplicate cannot double count.
    changed_earlier = frame.copy()
    changed_earlier.loc[0, "batter_so_per_pa"] = 0.1
    assert _fit_annual(changed_earlier)["fittedChecksum"] == fitted["fittedChecksum"]

    conflicting = frame.copy()
    conflicting.loc[2, "batter_so_per_pa"] = 0.3
    with pytest.raises(prior.PlayerPriorAuthorityError) as caught:
        _fit_annual(conflicting)
    assert caught.value.code == "PRIOR_POINT_IN_TIME_STATE_CONFLICT"


def test_fit_excludes_finite_rows_with_explicit_failure_reasons() -> None:
    frame = _annual_training_frame()
    frame["batter_so_per_pa__missing_reason"] = [
        "",
        "",
        "",
        "source_unavailable",
        "COMPUTATION_FAILURE",
    ]
    fitted = _fit_annual(frame)
    parameter = fitted["parameters"]["batter_so_per_pa"]

    # B and C have perfectly finite, domain-valid rates and exposures. Their
    # governed failure reasons nevertheless prohibit them from population fit.
    assert fitted["trainingRows"] == 5
    assert parameter["playerStateCount"] == 1
    assert parameter["totalObservedTrials"] == 100
    assert parameter["totalObservedSuccesses"] == 20
    assert parameter["priorMean"] == pytest.approx(20.5 / 101.0)


def test_annual_transform_distinguishes_cold_history_and_fail_closed_states() -> None:
    feature = "batter_so_per_pa"
    fitted = _fit_annual()
    frame = pd.DataFrame(
        {
            "canonicalPaId": [f"transform-annual-{index}" for index in range(8)],
            "game_date": ["2025-06-01"] * 8,
            "batterCanonicalPlayerId": [f"batter-{index}" for index in range(8)],
            feature: [np.nan, np.nan, np.nan, 0.2, 0.2, 0.2, 0.3, 0.1234],
            "batter_log1p_pa": [
                np.nan,
                np.nan,
                np.log1p(10),
                np.log1p(10),
                np.log1p(10),
                np.log1p(0),
                np.log1p(10),
                np.log1p(10),
            ],
            "batter_prior_missing": [1, 0, 0, 0, 0, 1, 0, 0],
            f"{feature}__missing_reason": [
                "",
                "",
                "",
                "SOURCE_UNAVAILABLE",
                "COMPUTATION_FAILURE",
                "",
                "",
                "",
            ],
            # Deliberate forbidden distractors: transforms must be target-independent.
            "outcome": ["hit"] * 8,
            "target": np.arange(8),
        }
    )
    transformed = prior.transform_prior_feature(frame, fitted, feature)
    outputs = prior.feature_binding(feature)["derivedOutputs"]
    states = transformed[outputs["historyState"]].tolist()
    assert states == [
        "TRUE_COLD_START",
        "SOURCE_UNAVAILABLE",
        "SOURCE_UNAVAILABLE",
        "SOURCE_UNAVAILABLE",
        "COMPUTATION_FAILURE",
        "COMPUTATION_FAILURE",
        "PRIOR_SEASON_ONLY",
        "COMPUTATION_FAILURE",
    ]
    assert transformed[outputs["priorLevel"]].tolist() == [
        "MLB_LEAGUE_POPULATION",
        "NONE_FAIL_CLOSED",
        "NONE_FAIL_CLOSED",
        "NONE_FAIL_CLOSED",
        "NONE_FAIL_CLOSED",
        "NONE_FAIL_CLOSED",
        "PLAYER_HISTORY_PLUS_MLB_LEAGUE_POPULATION",
        "NONE_FAIL_CLOSED",
    ]

    parameter = fitted["parameters"][feature]
    assert transformed.loc[0, outputs["posteriorMean"]] == pytest.approx(
        parameter["priorMean"]
    )
    assert transformed.loc[0, outputs["effectiveN"]] == 0
    assert transformed.loc[0, outputs["posteriorReliability"]] == 0
    assert transformed.loc[6, outputs["observedSuccesses"]] == 3
    assert transformed.loc[6, outputs["observedTrials"]] == 10
    assert transformed.loc[6, outputs["posteriorAlpha"]] == pytest.approx(
        parameter["alpha"] + 3
    )
    assert transformed.loc[6, outputs["posteriorBeta"]] == pytest.approx(
        parameter["beta"] + 7
    )
    expected_mean = (parameter["alpha"] + 3) / (parameter["priorStrength"] + 10)
    assert transformed.loc[6, outputs["posteriorMean"]] == pytest.approx(expected_mean)
    assert transformed.loc[6, outputs["posteriorReliability"]] == pytest.approx(
        10 / (parameter["priorStrength"] + 10)
    )
    assert transformed.loc[6, outputs["decayWeight"]] == 1.0
    assert math.isnan(transformed.loc[6, outputs["observationAgeDays"]])
    fail_rows = [1, 2, 3, 4, 5, 7]
    assert transformed.loc[fail_rows, outputs["posteriorMean"]].isna().all()
    assert transformed.loc[fail_rows, outputs["priorStrength"]].isna().all()

    changed_targets = frame.copy()
    changed_targets["outcome"] = ["out"] * len(frame)
    changed_targets["target"] = np.arange(100, 100 + len(frame))
    pd.testing.assert_frame_equal(
        transformed,
        prior.transform_prior_feature(changed_targets, fitted, feature),
    )

    final_oot = frame.iloc[[6]].copy()
    final_oot["game_date"] = "2026-08-14"
    with pytest.raises(prior.PlayerPriorAuthorityError) as oot_error:
        prior.transform_prior_feature(final_oot, fitted, feature)
    assert oot_error.value.code == "PRIOR_TRANSFORM_CROSSES_FINAL_OOT"


def test_frozen_transform_is_row_local_when_later_rows_are_appended_or_changed() -> None:
    feature = "batter_so_per_pa"
    fitted = _fit_annual()
    earlier = pd.DataFrame(
        {
            "canonicalPaId": ["earlier-pa"],
            "game_date": ["2025-04-01"],
            "batterCanonicalPlayerId": ["A"],
            feature: [0.3],
            "batter_log1p_pa": np.log1p([10]),
            "batter_prior_missing": [0],
        }
    )
    later = pd.DataFrame(
        {
            "canonicalPaId": ["later-pa"],
            "game_date": ["2025-05-01"],
            "batterCanonicalPlayerId": ["A"],
            feature: [0.8],
            "batter_log1p_pa": np.log1p([10]),
            "batter_prior_missing": [0],
        }
    )
    earlier_only = prior.transform_prior_feature(earlier, fitted, feature)
    appended = pd.concat([earlier, later], ignore_index=True)
    with_later = prior.transform_prior_feature(appended, fitted, feature)
    changed_later = appended.copy()
    changed_later.loc[1, feature] = 0.0
    changed_later.loc[1, "batter_log1p_pa"] = np.log1p(100)
    with_changed_later = prior.transform_prior_feature(changed_later, fitted, feature)

    pd.testing.assert_frame_equal(earlier_only, with_later.iloc[[0]])
    pd.testing.assert_frame_equal(earlier_only, with_changed_later.iloc[[0]])
    assert prior.feature_binding(feature)["historyCutoff"] == (
        "source.gameDate < target.gameDate (same-date rows excluded)"
    )


def test_rolling_transform_distinguishes_sparse_and_established_history() -> None:
    feature = "batter_last100_strikeout_rate"
    fitted = _fit_rolling()
    frame = pd.DataFrame(
        {
            "canonicalPaId": ["transform-rolling-cold", "transform-rolling-sparse", "transform-rolling-established"],
            "game_date": ["2025-06-01", "2025-06-02", "2025-06-03"],
            "batterCanonicalPlayerId": ["cold", "sparse", "established"],
            feature: [np.nan, 0.2, 0.3],
            "batter_last100_pa_count": [0, 20, 100],
            "batter_last100_insufficient": [1, 1, 0],
        }
    )
    transformed = prior.transform_prior_feature(frame, fitted, feature)
    outputs = prior.feature_binding(feature)["derivedOutputs"]
    assert transformed[outputs["historyState"]].tolist() == [
        "TRUE_COLD_START",
        "SPARSE_HISTORY",
        "ESTABLISHED_HISTORY",
    ]
    assert transformed[outputs["effectiveN"]].tolist() == [0.0, 20.0, 100.0]
    reliability = transformed[outputs["posteriorReliability"]].tolist()
    assert reliability[0] == 0
    assert 0 < reliability[1] < reliability[2] < 1
    assert transformed.loc[0, outputs["posteriorMean"]] == pytest.approx(
        fitted["parameters"][feature]["priorMean"]
    )


def test_rolling_insufficient_flag_cannot_invent_zero_when_exposure_is_missing() -> None:
    feature = "batter_last100_strikeout_rate"
    fitted = _fit_rolling()
    frame = pd.DataFrame(
        {
            "canonicalPaId": ["transform-rolling-missing-exposure"],
            "game_date": ["2025-06-01"],
            "batterCanonicalPlayerId": ["missing-exposure"],
            feature: [np.nan],
            "batter_last100_pa_count": [np.nan],
            "batter_last100_insufficient": [1],
        }
    )
    transformed = prior.transform_prior_feature(frame, fitted, feature)
    outputs = prior.feature_binding(feature)["derivedOutputs"]
    assert transformed.loc[0, outputs["historyState"]] == "SOURCE_UNAVAILABLE"
    assert transformed.loc[0, outputs["priorLevel"]] == "NONE_FAIL_CLOSED"
    assert math.isnan(transformed.loc[0, outputs["posteriorMean"]])
    assert math.isnan(transformed.loc[0, outputs["effectiveN"]])
    assert math.isnan(transformed.loc[0, outputs["posteriorReliability"]])


def test_fit_isolated_from_validation_future_values_and_target_columns() -> None:
    base = _annual_training_frame()
    future = pd.DataFrame(
        {
            "canonicalPaId": ["future-a", "future-z"],
            "game_date": ["2025-01-01", "2025-01-02"],
            "batterCanonicalPlayerId": ["A", "Z"],
            "batter_so_per_pa": [0.0, 1.0],
            "batter_log1p_pa": np.log1p([1000, 1000]),
            "batter_prior_missing": [0, 0],
        }
    )
    first_frame = pd.concat([base, future], ignore_index=True)
    first_frame["outcome"] = np.arange(len(first_frame))
    changed = first_frame.copy()
    changed.loc[changed["game_date"].str.startswith("2025"), "batter_so_per_pa"] = [1.0, 0.0]
    changed.loc[changed["game_date"].str.startswith("2025"), "batter_log1p_pa"] = np.log1p(
        [1, 1]
    )
    changed["outcome"] = np.arange(100, 100 + len(changed))

    first = _fit_annual(first_frame)
    second = _fit_annual(changed)
    assert _stable_fitted(first) == _stable_fitted(second)
    assert first["fittedChecksum"] == second["fittedChecksum"]
    assert first["parameters"]["batter_so_per_pa"]["playerStateCount"] == 3
    assert first["rowsAfterTrainingCutoffExcluded"] == 2
    assert first["fitEvidence"] == {
        "populationUnit": "LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF",
        "validationFeatureValuesReadForFit": False,
        "targetColumnRead": False,
        "finalOotRowsFit": 0,
        "modelFits": 0,
        "scores": 0,
    }

    with pytest.raises(prior.PlayerPriorAuthorityError) as caught:
        prior.fit_prior_authority(
            base,
            training_end="2026-08-14",
            authority_manifest=_authority_manifest(),
            fold_id="forbidden-oot",
            features=["batter_so_per_pa"],
        )
    assert caught.value.code == "PRIOR_CUTOFF_CROSSES_FINAL_OOT"


def test_fitted_checksum_and_preprocessor_binding_fail_closed_and_are_stable() -> None:
    fitted = _fit_annual()
    repeated = _fit_annual()
    assert fitted["fittedChecksum"] == repeated["fittedChecksum"]
    assert fitted["fittedId"] == repeated["fittedId"]

    tree = prior.preprocessing_identity(fitted=fitted, model_family="tree")
    tree_again = prior.preprocessing_identity(fitted=fitted, model_family="TREE")
    linear = prior.preprocessing_identity(
        fitted=fitted,
        model_family="linear",
        scaler_fit_rows_checksum="training-rows:abc",
    )
    assert tree == tree_again
    assert tree["id"].endswith(tree["checksum"])
    assert tree["fittedPriorChecksum"] == fitted["fittedChecksum"]
    assert tree["scientificValueAuthority"] == (
        "CANONICAL_VALUES_IDENTICAL_ACROSS_MODEL_FAMILIES"
    )
    assert tree["scaling"] == "NONE_TREE_NATIVE"
    assert linear["scaling"] == "TRAINING_ROWS_ONLY"
    assert linear["scalerFitRowsChecksum"] == "training-rows:abc"
    assert linear["id"] != tree["id"]
    assert tree["modelFitCreated"] is False
    assert linear["modelFitCreated"] is False

    for dense_family in ("LINEAR", "NEURAL_OR_DISTANCE"):
        with pytest.raises(prior.PlayerPriorAuthorityError) as scaler_error:
            prior.preprocessing_identity(
                fitted=fitted,
                model_family=dense_family,
            )
        assert scaler_error.value.code == "PRIOR_SCALER_FIT_EVIDENCE_REQUIRED"

    tampered = copy.deepcopy(fitted)
    tampered["parameters"]["batter_so_per_pa"]["alpha"] += 1
    with pytest.raises(prior.PlayerPriorAuthorityError) as caught:
        prior.transform_prior_feature(_annual_training_frame(), tampered, "batter_so_per_pa")
    assert caught.value.code == "PRIOR_FITTED_CHECKSUM_MISMATCH"

    id_tampered = copy.deepcopy(fitted)
    id_tampered["fittedId"] = f"{fitted['fittedId']}:tampered"
    assert id_tampered["fittedChecksum"] == fitted["fittedChecksum"]
    with pytest.raises(prior.PlayerPriorAuthorityError) as id_error:
        prior.transform_prior_feature(
            _annual_training_frame(), id_tampered, "batter_so_per_pa"
        )
    assert id_error.value.code == "PRIOR_FITTED_ID_MISMATCH"

    with pytest.raises(prior.PlayerPriorAuthorityError) as family_error:
        prior.preprocessing_identity(fitted=fitted, model_family="unsupported")
    assert family_error.value.code == "PRIOR_MODEL_FAMILY_UNSUPPORTED"


def test_development_diagnostics_are_target_free_aggregate_preprocessing_evidence() -> None:
    feature = "batter_last100_strikeout_rate"
    fitted = _fit_rolling()
    frame = pd.DataFrame(
        {
            "canonicalPaId": ["diag-cold", "diag-sparse", "diag-established", "diag-source"],
            "game_date": ["2024-05-01", "2024-05-02", "2024-06-01", "2024-06-02"],
            "batterCanonicalPlayerId": ["cold", "sparse", "established", "source"],
            feature: [np.nan, 0.2, 0.3, np.nan],
            "batter_last100_pa_count": [0, 20, 100, 10],
            "batter_last100_insufficient": [1, 1, 0, 0],
            "outcome": ["single", "out", "home_run", "walk"],
        }
    )
    first = prior.development_diagnostics(frame, fitted, features=[feature])
    changed = frame.copy()
    changed["outcome"] = ["changed"] * len(changed)
    second = prior.development_diagnostics(changed, fitted, features=[feature])
    assert {key: value for key, value in first.items() if key != "durationMs"} == {
        key: value for key, value in second.items() if key != "durationMs"
    }
    assert first["scope"] == "DEVELOPMENT_ONLY_FEATURE_CELLS"
    assert first["rows"] == 4
    assert first["featureCount"] == 1
    assert first["historyStateCounts"] == {
        "ESTABLISHED_HISTORY": 1,
        "SOURCE_UNAVAILABLE": 1,
        "SPARSE_HISTORY": 1,
        "TRUE_COLD_START": 1,
    }
    assert first["priorLevelCounts"] == {
        "MLB_LEAGUE_POPULATION": 1,
        "NONE_FAIL_CLOSED": 1,
        "PLAYER_HISTORY_PLUS_MLB_LEAGUE_POPULATION": 2,
    }
    assert first["rowHistoryStatePresenceCounts"] == {
        "ESTABLISHED_HISTORY": 1,
        "SOURCE_UNAVAILABLE": 1,
        "SPARSE_HISTORY": 1,
        "TRUE_COLD_START": 1,
    }
    assert first["rowPriorLevelPresenceCounts"] == {
        "MLB_LEAGUE_POPULATION": 1,
        "NONE_FAIL_CLOSED": 1,
        "PLAYER_HISTORY_PLUS_MLB_LEAGUE_POPULATION": 2,
    }
    assert first["rowsUsingPlayerHistory"] == 2
    assert first["rowsUsingRolePrior"] == 0
    assert first["rowsUsingLeaguePrior"] == 1
    assert first["trueColdStartRows"] == 1
    assert set(first["perFeature"]) == {feature}
    assert set(first["reliabilityQuantiles"]) == {"p0", "p25", "p50", "p75", "p90", "p100"}
    assert first["targetRead"] is False
    assert first["finalOotRowsRead"] == 0
    assert first["modelFits"] == 0
    assert "predictions" not in first
    assert "scores" not in first


def test_required_inputs_and_nonexecutable_features_reject_unsupported_shortcuts() -> None:
    required = set(prior.required_input_columns(["batter_so_per_pa"]))
    assert required == {
        "canonicalPaId",
        "game_date",
        "batterCanonicalPlayerId",
        "batter_so_per_pa",
        "batter_log1p_pa",
        "batter_prior_missing",
    }
    assert "outcome" not in required
    assert "target" not in required
    with pytest.raises(prior.PlayerPriorAuthorityError) as blocked:
        prior.required_input_columns(["batter_avg"])
    assert blocked.value.code == "PRIOR_FEATURE_NOT_EXECUTABLE"
    with pytest.raises(prior.PlayerPriorAuthorityError) as unknown:
        prior.required_input_columns(["not_a_feature"])
    assert unknown.value.code == "PRIOR_FEATURE_NOT_EXECUTABLE"

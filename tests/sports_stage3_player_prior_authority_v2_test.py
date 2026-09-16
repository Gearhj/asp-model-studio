from __future__ import annotations

import copy
import hashlib
import shutil
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.persistence.db import Database
from server.sports_current_statcast import stage3_eda as eda
from server.sports_current_statcast import stage3_player_prior_authority as prior_v1
from server.sports_current_statcast import stage3_player_prior_authority_v2 as prior_v2
from server.sports_current_statcast import sufficient_stats
from server.sports_current_statcast.stage3_player_prior_artifact_store_v2 import (
    PriorArtifactStoreV2Error,
    load_artifact,
    publish_artifact,
)


EXPECTED_WAVE2_FEATURES = {
    "pitcher_whip",
    "pitcher_gs_per_g",
    "batter_slg",
    "batter_avg",
    "pitcher_last250_avg_fastball_velocity",
    "pitcher_last250_whiff_rate",
    "pitcher_last250_offspeed_usage",
    "pitcher_last250_fastball_usage",
    "pitcher_last250_breaking_usage",
    "batter_last100_whiff_rate",
}
EXPECTED_RETIRED_FEATURES = {
    "pitcher_era9",
    "batter_obp",
    "batter_last100_contact_rate",
}
EXPECTED_METHODS = {
    "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
    "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES",
    "GAMMA_POISSON_COMPONENT_SHRINKAGE",
    "NORMAL_NORMAL_EMPIRICAL_BAYES",
}


@pytest.fixture()
def writable_tmp_path() -> Path:
    """Avoid Python's Windows 0o700 temp-directory ACL under the test sandbox."""

    root = Path(__file__).resolve().parent / ".wave2-authority-test-tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)
        try:
            root.rmdir()
        except OSError:
            pass


def _project_authority() -> dict[str, object]:
    return {
        "projectId": "asp-wave2-authority-test",
        "goldDatasetId": "gold-table:synthetic-current-pa",
        "goldManifestSha": prior_v2.EXPECTED_GOLD_MANIFEST_SHA256,
        "contextualDatasetId": "gold-table:synthetic-current-pa-context",
        "contextualManifestSha": "2" * 64,
        "reviewDigest": "3" * 64,
    }


def _v1_manifest() -> dict[str, object]:
    return prior_v1.project_authority_manifest(
        _project_authority(),
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="4" * 64,
    )


def _companion_authentication() -> dict[str, object]:
    binding_unsigned: dict[str, object] = {
        "schemaVersion": "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1",
        "datasetId": prior_v2.EXPECTED_COMPANION_DATASET_ID,
        "manifestContract": sufficient_stats.CURRENT_SUFFICIENT_STATS_CONTRACT,
        "manifestSha256": prior_v2.EXPECTED_COMPANION_MANIFEST_SHA256,
        "objectSha256": list(prior_v2.EXPECTED_COMPANION_OBJECT_SHA256),
        "sourceGoldManifestSha256": prior_v2.EXPECTED_GOLD_MANIFEST_SHA256,
        "sourceGoldUpstreamAuthoritiesSha256": (
            prior_v2.EXPECTED_GOLD_UPSTREAM_AUTHORITY_SHA256
        ),
        "sourceCurrentSilverManifestSha256": (
            prior_v2.EXPECTED_SOURCE_CURRENT_SILVER_SHA256
        ),
        "physicalSchemaSha256": prior_v2.EXPECTED_COMPANION_PHYSICAL_SCHEMA_SHA256,
        "validationEvidenceSha256": prior_v2.EXPECTED_COMPANION_VALIDATION_SHA256,
        "requiredColumns": list(sufficient_stats.SUFFICIENT_STATISTIC_COLUMNS),
        "verified": True,
        "integerValidation": True,
        "equivalenceValidation": True,
        "finalOotSealed": True,
        "rightsStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
    }
    binding_checksum = prior_v2._sha256(binding_unsigned)
    assert binding_checksum == prior_v2.EXPECTED_BINDING_AUTHORITY_CHECKSUM
    binding = {
        **binding_unsigned,
        "authorityChecksum": binding_checksum,
        "authorityId": prior_v2.EXPECTED_BINDING_AUTHORITY_ID,
    }
    allowed_oot = {
        "canonicalPaId", "datasetRole", "materialization_status", "materialization_reason"
    }
    footer_content = {
        "method": "PARQUET_FOOTER_COLUMN_STATISTICS_ONLY_NO_PAYLOAD_DECODE",
        "rowCount": prior_v2.FINAL_OOT_ROWS,
        "payloadColumns": [
            {
                "column": name,
                "nullCount": prior_v2.FINAL_OOT_ROWS,
                "numValues": 0,
            }
            for name in sufficient_stats.sufficient_statistics_schema().names
            if name not in allowed_oot
        ],
    }
    assert prior_v2._sha256(footer_content) == prior_v2.EXPECTED_OOT_FOOTER_SHA256
    rights = {
        "effectiveStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
        "allowedUses": ["LOCAL_PRIVATE_MODEL_DEVELOPMENT", "READ_ONLY_REGISTRATION"],
        "attributionRequired": True,
        "commercialRights": "UNCLEAR_REQUIRES_REVIEW",
        "combinationRule": "INTERSECTION_MOST_RESTRICTIVE_APPLICABLE_SOURCE_AUTHORITY",
        "sourceAuthorities": [
            {
                "rightsControlId": "CHADWICK_PERSONS_REGISTER",
                "status": "USED",
                "attribution": "Chadwick Bureau Persons Register attribution.",
            },
            {
                "rightsControlId": "MLB_STATCAST",
                "status": "GOVERNED_LOCAL_RESEARCH_ONLY",
                "attribution": "MLB Advanced Media / Baseball Savant Statcast attribution.",
            },
            {
                "rightsControlId": "SABR_LAHMAN_MODERN_MLB",
                "status": "USED_MODERN_MLB_ONLY",
                "attribution": "SABR Lahman Database attribution.",
            },
        ],
    }
    public: dict[str, object] = {
        "registrationId": prior_v2.EXPECTED_COMPANION_REGISTRATION_ID,
        "registrationActive": False,
        "bindingAuthority": binding,
        "datasetId": prior_v2.EXPECTED_COMPANION_DATASET_ID,
        "manifestSha256": prior_v2.EXPECTED_COMPANION_MANIFEST_SHA256,
        "objectSha256": list(prior_v2.EXPECTED_COMPANION_OBJECT_SHA256),
        "physicalSchemaSha256": prior_v2.EXPECTED_COMPANION_PHYSICAL_SCHEMA_SHA256,
        "validationEvidenceSha256": prior_v2.EXPECTED_COMPANION_VALIDATION_SHA256,
        "sourceGoldManifestSha256": prior_v2.EXPECTED_GOLD_MANIFEST_SHA256,
        "sourceCurrentSilverManifestSha256": prior_v2.EXPECTED_SOURCE_CURRENT_SILVER_SHA256,
        "sourceGoldPartitionSha256": list(prior_v2.EXPECTED_GOLD_PARTITION_SHA256),
        "goldDeclaredUpstreamAuthoritySha256": prior_v2.EXPECTED_GOLD_UPSTREAM_AUTHORITY_SHA256,
        "currentSilverParentMatch": True,
        "bindingAuthorityId": prior_v2.EXPECTED_BINDING_AUTHORITY_ID,
        "bindingAuthorityChecksum": prior_v2.EXPECTED_BINDING_AUTHORITY_CHECKSUM,
        "rights": rights,
        "limitations": ["Commercial use requires explicit rights review."],
        "rowIdentity": {
            "method": "EXACT_CANONICAL_PA_ID_AND_ROLE_PROJECTION",
            "rowCount": prior_v2.DEVELOPMENT_ROWS + prior_v2.FINAL_OOT_ROWS,
            "checksum": prior_v2.EXPECTED_ROW_IDENTITY_SHA256,
            "goldMatch": True,
        },
        "development": {"rows": prior_v2.DEVELOPMENT_ROWS, "partitions": 4},
        "finalOot": {
            "rows": prior_v2.FINAL_OOT_ROWS,
            "status": "KEY_ONLY_UNMATERIALIZED",
            "payloadRowsRead": 0,
            "payloadColumnsRead": [],
            "footerEvidence": {
                **footer_content,
                "checksum": prior_v2.EXPECTED_OOT_FOOTER_SHA256,
            },
        },
    }
    return {**public, "authenticationChecksum": prior_v2._sha256(public)}


def _definition(*, compiler_sha256: str = "e" * 64) -> dict[str, object]:
    return prior_v2.build_authority_definition(
        _project_authority(),
        v1_authority_manifest=_v1_manifest(),
        companion_authentication=_companion_authentication(),
        treatment_specification_key="MLB_FEATURE_TREATMENT_SPEC_V1",
        treatment_source_sha256="d" * 64,
        compiler_version="wave2-test",
        compiler_sha256=compiler_sha256,
    )


def _fake_bundle() -> dict[str, object]:
    return {
        "authorityId": "MLB_PLAYER_STATE_PRIOR_AUTHORITY_V2:sha256:" + "a" * 64,
        "authorityChecksum": "a" * 64,
        "companionBindingAuthorityId": "SUFFICIENT_STATISTICS_AUTHORITY:sha256:" + "b" * 64,
        "foldContract": {
            "contractId": "FOLD_CONTRACT:test",
            "contractChecksum": "c" * 64,
            "artifactSha256": "d" * 64,
        },
        "foldAuthorities": [
            {
                "foldId": f"GOVERNED_CHRONOLOGICAL_FOLD_{number}",
                "fittedId": f"FITTED:{number}",
                "fittedChecksum": f"{number}" * 64,
                "artifactSha256": f"{number}" * 64,
            }
            for number in range(1, 6)
        ],
        "finalDevelopmentAuthority": {
            "fittedId": "FITTED:FINAL_DEVELOPMENT",
            "fittedChecksum": "f" * 64,
            "artifactSha256": "f" * 64,
        },
    }


def _synthetic_fit_frame() -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for day_number, date in enumerate(("2024-01-01", "2024-01-02"), start=1):
        for player_number in range(1, 6):
            pitcher_games = 40 + 2 * player_number + day_number
            pitcher_starts = 8 + player_number
            pitcher_outs = 300 + 20 * player_number + 3 * day_number
            batter_at_bats = 350 + 15 * player_number + day_number
            batter_hits = 85 + 4 * player_number
            doubles = 15 + player_number
            triples = 2
            home_runs = 8 + player_number
            pitcher_swings = 90 + 5 * player_number + day_number
            pitcher_whiffs = 14 + 3 * player_number
            pitch_count = 260 + 10 * player_number + day_number
            fastballs = 120 + 5 * player_number
            breaking = 55 + 2 * player_number
            offspeed = 40 + player_number
            other = pitch_count - fastballs - breaking - offspeed
            velocity_count = 35 + 4 * player_number
            velocity_mean = 90.0 + player_number / 2.0 + day_number / 10.0
            velocity_variance = 1.5 + player_number / 10.0
            velocity_sum = velocity_count * velocity_mean
            velocity_sumsq = (
                (velocity_count - 1) * velocity_variance
                + velocity_count * velocity_mean**2
            )
            batter_swings = 55 + 4 * player_number + day_number
            batter_whiffs = 8 + 2 * player_number
            records.append(
                {
                    "canonicalPaId": f"train-{day_number}-{player_number}",
                    "canonicalGameId": f"game-{day_number}",
                    "game_date": date,
                    "season": 2024,
                    "pitcherCanonicalPlayerId": f"pitcher-{player_number}",
                    "batterCanonicalPlayerId": f"batter-{player_number}",
                    "pitcher_prior_missing": 0,
                    "batter_prior_missing": 0,
                    "pitcher_last250_insufficient": 0,
                    "pitcher_last250_whiff_missing": 0,
                    "pitcher_last250_velocity_missing": 0,
                    "batter_last100_insufficient": 0,
                    "batter_last100_whiff_missing": 0,
                    "pitcher_prior_g": pitcher_games,
                    "pitcher_prior_gs": pitcher_starts,
                    "pitcher_prior_ipouts": pitcher_outs,
                    "pitcher_prior_h": 70 + 5 * player_number,
                    "pitcher_prior_bb": 18 + 2 * player_number,
                    "batter_prior_ab": batter_at_bats,
                    "batter_prior_h": batter_hits,
                    "batter_prior_2b": doubles,
                    "batter_prior_3b": triples,
                    "batter_prior_hr": home_runs,
                    "pitcher_last250_swing_count": pitcher_swings,
                    "pitcher_last250_whiff_count": pitcher_whiffs,
                    "pitcher_last250_pitch_count": pitch_count,
                    "pitcher_last250_fastball_count": fastballs,
                    "pitcher_last250_breaking_count": breaking,
                    "pitcher_last250_offspeed_count": offspeed,
                    "pitcher_last250_other_or_unclassified_pitch_count": other,
                    "pitcher_last250_fastball_velocity_count": velocity_count,
                    "pitcher_last250_fastball_velocity_sum": velocity_sum,
                    "pitcher_last250_fastball_velocity_sumsq": velocity_sumsq,
                    "batter_last100_swing_count": batter_swings,
                    "batter_last100_whiff_count": batter_whiffs,
                }
            )

    poison = copy.deepcopy(records[-1])
    poison.update(
        {
            "canonicalPaId": "validation-poison",
            "canonicalGameId": "validation-game",
            "game_date": "2024-02-01",
        }
    )
    protected = {
        "canonicalPaId",
        "canonicalGameId",
        "game_date",
        "season",
        "pitcherCanonicalPlayerId",
        "batterCanonicalPlayerId",
        "pitcher_prior_missing",
        "batter_prior_missing",
        "pitcher_last250_insufficient",
        "pitcher_last250_whiff_missing",
        "pitcher_last250_velocity_missing",
        "batter_last100_insufficient",
        "batter_last100_whiff_missing",
    }
    for column in set(prior_v2.required_input_columns()) - protected:
        poison[column] = -17
    records.append(poison)
    return pd.DataFrame.from_records(records)


def _fold_record(*, fold_id: str = "GOVERNED_CHRONOLOGICAL_FOLD_1") -> dict[str, object]:
    fold_number = 0 if fold_id == "FINAL_DEVELOPMENT" else int(fold_id.rsplit("_", 1)[-1])
    content: dict[str, object] = {
        "foldId": fold_id,
        "foldNumber": fold_number,
        "trainStart": "2024-01-01",
        "trainEnd": "2024-01-02",
        "validationStart": "2024-02-01" if fold_id != "FINAL_DEVELOPMENT" else None,
        "validationEnd": "2024-02-01" if fold_id != "FINAL_DEVELOPMENT" else None,
        "trainRows": 10,
        "validationRows": 1 if fold_id != "FINAL_DEVELOPMENT" else 0,
        "trainGames": 2,
        "validationGames": 1 if fold_id != "FINAL_DEVELOPMENT" else 0,
        "preprocessingFitScope": (
            "TRAINING_ROWS_OF_THIS_FOLD_ONLY"
            if fold_id != "FINAL_DEVELOPMENT"
            else "ALL_AUTHORIZED_DEVELOPMENT_ROWS_ONLY"
        ),
        "validationStatisticsUsedForTraining": False,
        "finalOotUsed": False,
    }
    return {**content, "checksum": prior_v2._sha256(content)}


def _chronological_bundle_frame() -> pd.DataFrame:
    """Six date-atomic games: one warmup day plus five validation days."""

    seed = _synthetic_fit_frame().iloc[:5].copy()
    days: list[pd.DataFrame] = []
    for day_number, game_date in enumerate(
        pd.date_range("2023-12-31", "2024-01-05", freq="D"), start=1
    ):
        daily = seed.copy(deep=True)
        daily["canonicalPaId"] = [
            f"bundle-{day_number}-{player_number}" for player_number in range(1, 6)
        ]
        daily["canonicalGameId"] = f"bundle-game-{day_number}"
        daily["game_date"] = game_date.date().isoformat()
        daily["season"] = game_date.year
        days.append(daily)
    return pd.concat(days, ignore_index=True)


def _chronological_bundle_fixture(
    monkeypatch: pytest.MonkeyPatch, root: Path
) -> dict[str, object]:
    frame = _chronological_bundle_frame()
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_START", "2023-12-31")
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_END", "2024-01-05")
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_ROWS", len(frame))

    contract = prior_v2.bind_fold_contract_project(
        prior_v2.build_five_fold_contract(frame), "asp-wave2-authority-test"
    )
    definition = _definition()
    definition_receipt = publish_artifact(definition, root=root)
    contract_receipt = publish_artifact(contract, root=root)
    children = [
        prior_v2.fit_fold_authority(
            frame,
            definition,
            fold,
            fold_contract_id=contract["contractId"],
            fold_contract_checksum=contract["contractChecksum"],
        )
        for fold in contract["folds"]
    ]
    child_receipts = [publish_artifact(child, root=root) for child in children]
    final_content: dict[str, object] = {
        "foldId": "FINAL_DEVELOPMENT",
        "foldNumber": 0,
        "trainStart": "2023-12-31",
        "trainEnd": "2024-01-05",
        "validationStart": None,
        "validationEnd": None,
        "trainRows": len(frame),
        "validationRows": 0,
        "trainGames": int(frame["canonicalGameId"].nunique()),
        "validationGames": 0,
        "trainingMembershipChecksum": prior_v2._membership_checksum(frame),
        "preprocessingFitScope": "ALL_AUTHORIZED_DEVELOPMENT_ROWS_ONLY",
        "validationStatisticsUsedForTraining": False,
        "finalOotUsed": False,
    }
    final_record = {
        **final_content,
        "checksum": prior_v2._sha256(final_content),
    }
    final = prior_v2.fit_fold_authority(
        frame,
        definition,
        final_record,
        fold_contract_id=contract["contractId"],
        fold_contract_checksum=contract["contractChecksum"],
        scope_kind="FINAL_DEVELOPMENT",
    )
    final_receipt = publish_artifact(final, root=root)
    bundle = prior_v2.assemble_fit_bundle(
        definition,
        children,
        final,
        fold_contract=contract,
        definition_artifact_sha256=definition_receipt["sha256"],
        fold_contract_artifact_sha256=contract_receipt["sha256"],
        fold_artifact_sha256=[receipt["sha256"] for receipt in child_receipts],
        final_artifact_sha256=final_receipt["sha256"],
    )
    return {
        "frame": frame,
        "definition": definition,
        "definitionReceipt": definition_receipt,
        "contract": contract,
        "contractReceipt": contract_receipt,
        "children": children,
        "childReceipts": child_receipts,
        "final": final,
        "finalReceipt": final_receipt,
        "bundle": bundle,
    }


def test_wave2_manifest_promotes_exactly_ten_bindings_and_preserves_output_roles() -> None:
    manifest = prior_v2.combined_project_authority_manifest(_v1_manifest(), _fake_bundle())
    bindings = {item["feature"]: item for item in manifest["bindings"]}
    wave2 = {
        feature: binding
        for feature, binding in bindings.items()
        if binding["status"] == prior_v2.READY_GOVERNED_PRIOR_V2
    }

    assert set(prior_v2.WAVE2_FEATURES) == EXPECTED_WAVE2_FEATURES
    assert set(wave2) == EXPECTED_WAVE2_FEATURES
    assert manifest["readyV2FeatureCount"] == 10
    assert manifest["statusCounts"][prior_v2.READY_GOVERNED_PRIOR_V2] == 10
    assert {binding["method"] for binding in wave2.values()} == EXPECTED_METHODS
    assert len({binding["familyId"] for binding in wave2.values()}) == 7

    for feature, binding in wave2.items():
        output = binding["outputContract"]
        candidates = output["modelCandidateOutputs"]
        audit_only = output["auditOnlyOutputs"]
        assert binding["status"] == "READY_GOVERNED_PRIOR_V2"
        assert binding["executable"] is True
        assert binding["selectable"] is False
        assert output["rawFeatureSelectable"] is False
        assert output["defaultSelected"] is False
        assert candidates and audit_only
        assert set(candidates).isdisjoint(audit_only)
        assert set(output["recommendedAblationBundle"]).issubset(candidates)
        assert feature not in candidates
        assert all(name.startswith(f"{feature}__prior_v2__") for name in candidates)
        assert all(
            name.startswith(f"{feature}__prior_v2__")
            or name.startswith("mlb_prior_v2__")
            for name in audit_only
        )

    retired = {feature: bindings[feature] for feature in EXPECTED_RETIRED_FEATURES}
    assert all(
        binding["status"]
        == prior_v1.RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION
        for binding in retired.values()
    )
    assert all(binding["executable"] is False for binding in retired.values())
    assert all(binding["selectable"] is False for binding in retired.values())
    assert manifest["retiredFeatureCount"] == 3


def test_exact_family_wiring_uses_registered_components_and_no_forbidden_proxy() -> None:
    row = _synthetic_fit_frame().iloc[[0]].copy()

    gs = prior_v2._family_evidence(row, "PITCHER_GS_APPEARANCE")
    assert gs["exposure"][0] == row["pitcher_prior_g"].iloc[0]
    assert np.array_equal(
        gs["components"][0],
        [
            row["pitcher_prior_gs"].iloc[0],
            row["pitcher_prior_g"].iloc[0] - row["pitcher_prior_gs"].iloc[0],
        ],
    )

    for family_id, trial, success in (
        (
            "PITCHER_LAST250_WHIFF",
            "pitcher_last250_swing_count",
            "pitcher_last250_whiff_count",
        ),
        (
            "BATTER_LAST100_WHIFF",
            "batter_last100_swing_count",
            "batter_last100_whiff_count",
        ),
    ):
        evidence = prior_v2._family_evidence(row, family_id)
        assert np.array_equal(
            evidence["components"][0],
            [row[success].iloc[0], row[trial].iloc[0] - row[success].iloc[0]],
        )

    pitch_features = {
        "pitcher_last250_fastball_usage",
        "pitcher_last250_breaking_usage",
        "pitcher_last250_offspeed_usage",
    }
    assert {
        prior_v2.FEATURE_TO_FAMILY[feature] for feature in pitch_features
    } == {"PITCHER_LAST250_PITCH_COMPOSITION"}
    pitch = prior_v2._family_evidence(
        row, "PITCHER_LAST250_PITCH_COMPOSITION"
    )
    assert np.array_equal(
        pitch["components"][0],
        row[
            [
                "pitcher_last250_fastball_count",
                "pitcher_last250_breaking_count",
                "pitcher_last250_offspeed_count",
                "pitcher_last250_other_or_unclassified_pitch_count",
            ]
        ].iloc[0].to_numpy(dtype=np.float64),
    )
    assert pitch["components"][0].sum() == pitch["exposure"][0]

    assert {
        prior_v2.FEATURE_TO_FAMILY[feature]
        for feature in ("batter_avg", "batter_slg")
    } == {"BATTER_PRIOR_AB_OUTCOME_COMPOSITION"}
    batting = prior_v2._family_evidence(
        row, "BATTER_PRIOR_AB_OUTCOME_COMPOSITION"
    )
    ab = row["batter_prior_ab"].iloc[0]
    hits = row["batter_prior_h"].iloc[0]
    doubles = row["batter_prior_2b"].iloc[0]
    triples = row["batter_prior_3b"].iloc[0]
    home_runs = row["batter_prior_hr"].iloc[0]
    assert np.array_equal(
        batting["components"][0],
        [
            hits - doubles - triples - home_runs,
            doubles,
            triples,
            home_runs,
            ab - hits,
        ],
    )
    assert batting["components"].shape[1] == 5
    assert batting["components"][0].sum() == ab

    assert prior_v2._FAMILIES["PITCHER_PRIOR_WHIP_COMPONENTS"][
        "sourceColumns"
    ] == ("pitcher_prior_ipouts", "pitcher_prior_h", "pitcher_prior_bb")
    required = set(prior_v2.required_input_columns())
    assert {
        "outcome", "target", "pitcher_prior_bfp", "pitcher_prior_hbp"
    }.isdisjoint(required)
    assert set(prior_v2.RETIRED_FEATURES).isdisjoint(prior_v2.FEATURE_TO_FAMILY)
    assert all(
        prior_v2.feature_binding(feature) is None
        for feature in prior_v2.RETIRED_FEATURES
    )


def test_latest_state_population_fit_deduplicates_repeated_pa_rows() -> None:
    frame = _synthetic_fit_frame().iloc[:10].copy()
    definition = _definition()
    record = _fold_record()
    kwargs = {
        "fold_contract_id": "FOLD_CONTRACT:test",
        "fold_contract_checksum": "f" * 64,
    }
    baseline = prior_v2.fit_fold_authority(frame, definition, record, **kwargs)
    copies = []
    for copy_number in range(3):
        duplicate = frame.copy()
        duplicate["canonicalPaId"] = duplicate["canonicalPaId"].astype(str) + f"-copy-{copy_number}"
        copies.append(duplicate)
    repeated = prior_v2.fit_fold_authority(
        pd.concat(copies, ignore_index=True), definition, record, **kwargs
    )
    assert repeated["trainingRows"] == 3 * baseline["trainingRows"]
    assert repeated["parameters"] == baseline["parameters"]
    assert repeated["populationStateChecksums"] == baseline[
        "populationStateChecksums"
    ]


def test_latest_state_population_uses_one_latest_season_state_per_player() -> None:
    seed = _synthetic_fit_frame().iloc[[0]].copy(deep=True)
    older = seed.copy(deep=True)
    older["canonicalPaId"] = "season-state-2023"
    older["game_date"] = "2023-09-01"
    older["season"] = 2023
    older["pitcher_prior_g"] = 20
    older["pitcher_prior_gs"] = 4

    latest = seed.copy(deep=True)
    latest["canonicalPaId"] = "season-state-2024"
    latest["game_date"] = "2024-09-01"
    latest["season"] = 2024
    latest["pitcher_prior_g"] = 100
    latest["pitcher_prior_gs"] = 50
    repeated_latest = latest.copy(deep=True)
    repeated_latest["canonicalPaId"] = "season-state-2024-repeated-pa"

    authorized = pd.concat(
        [repeated_latest, older, latest], ignore_index=True
    ).sample(frac=1.0, random_state=31).reset_index(drop=True)
    states, checksum = prior_v2._latest_family_states(
        authorized, "PITCHER_GS_APPEARANCE"
    )
    reference, reference_checksum = prior_v2._latest_family_states(
        pd.concat([older, latest], ignore_index=True),
        "PITCHER_GS_APPEARANCE",
    )

    assert len(states) == 1
    assert states.loc[0, "game_date"] == pd.Timestamp("2024-09-01")
    assert states.loc[0, "component_0"] == 50
    assert states.loc[0, "component_1"] == 50
    assert states.loc[0, "exposure"] == 100
    assert checksum == reference_checksum
    pd.testing.assert_frame_equal(states, reference)

    future = latest.copy(deep=True)
    future["canonicalPaId"] = "season-state-2025"
    future["game_date"] = "2025-09-01"
    future["season"] = 2025
    future["pitcher_prior_g"] = 300
    future["pitcher_prior_gs"] = 1
    mixed = pd.concat([authorized, future], ignore_index=True)
    cutoff = pd.to_datetime(mixed["game_date"]).le(pd.Timestamp("2024-12-31"))
    cutoff_states, cutoff_checksum = prior_v2._latest_family_states(
        mixed.loc[cutoff], "PITCHER_GS_APPEARANCE"
    )
    pd.testing.assert_frame_equal(cutoff_states, reference)
    assert cutoff_checksum == reference_checksum


def test_fold_and_final_fit_are_content_deterministic_and_validation_payload_is_excluded() -> None:
    frame = _synthetic_fit_frame()
    definition = _definition()
    record = _fold_record()
    kwargs = {
        "fold_contract_id": "FOLD_CONTRACT:test",
        "fold_contract_checksum": "f" * 64,
    }
    first = prior_v2.fit_fold_authority(frame, definition, record, **kwargs)
    reordered = prior_v2.fit_fold_authority(
        frame.sample(frac=1.0, random_state=19).reset_index(drop=True),
        definition,
        record,
        **kwargs,
    )
    mutated_validation = frame.copy()
    validation = mutated_validation["canonicalPaId"].eq("validation-poison")
    for column in set(prior_v2.required_input_columns()) - {
        "canonicalPaId",
        "canonicalGameId",
        "game_date",
        "season",
        "pitcherCanonicalPlayerId",
        "batterCanonicalPlayerId",
    }:
        mutated_validation.loc[validation, column] = -999_999
    mutation_fit = prior_v2.fit_fold_authority(
        mutated_validation, definition, record, **kwargs
    )

    assert first == reordered == mutation_fit
    assert first["trainingRows"] == 10
    assert first["rowsOutsideTrainingExcludedBeforeComponentRead"] == (
        prior_v2.DEVELOPMENT_ROWS - 10
    )
    assert first["featureBindings"] == list(prior_v2.WAVE2_FEATURES)
    assert set(first["parameters"]) == set(prior_v2._FAMILIES)
    assert {value["method"] for value in first["parameters"].values()} == {
        "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
        "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES_METHOD_OF_MOMENTS",
        "GAMMA_POISSON_COMPONENT_SHRINKAGE",
        "NORMAL_NORMAL_EMPIRICAL_BAYES",
    }
    assert first["fitEvidence"] == {
        "populationUnit": "LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF",
        "validationFeatureValuesReadForFit": False,
        "targetColumnsRead": [],
        "finalOotRowsRead": 0,
        "modelFits": 0,
        "featureSetsRegistered": 0,
        "policiesAdopted": 0,
    }

    final_record = _fold_record(fold_id="FINAL_DEVELOPMENT")
    final_first = prior_v2.fit_fold_authority(
        frame,
        definition,
        final_record,
        scope_kind="FINAL_DEVELOPMENT",
        **kwargs,
    )
    final_second = prior_v2.fit_fold_authority(
        frame.copy(),
        definition,
        final_record,
        scope_kind="FINAL_DEVELOPMENT",
        **kwargs,
    )
    assert final_first == final_second
    assert final_first["scopeKind"] == "FINAL_DEVELOPMENT"
    assert final_first["fittedId"] != first["fittedId"]


def test_family_outputs_preserve_joint_formulas_and_edge_state_semantics() -> None:
    frame = _synthetic_fit_frame().iloc[:10].copy()
    fitted = prior_v2.fit_fold_authority(
        frame,
        _definition(),
        _fold_record(),
        fold_contract_id="FOLD_CONTRACT:test",
        fold_contract_checksum="f" * 64,
    )

    pitch = prior_v2.transform_prior_family(
        frame.iloc[:3], fitted, "PITCHER_LAST250_PITCH_COMPOSITION"
    )
    pitch_prefix = "mlb_prior_v2__pitcher_last250_pitch_composition__posterior_"
    pitch_cells = [
        f"{pitch_prefix}{name}"
        for name in ("fastball", "breaking", "offspeed", "other_or_unclassified")
    ]
    assert np.allclose(pitch[pitch_cells].sum(axis=1), 1.0, atol=1e-14)
    assert bool(pitch[pitch_cells[-1]].gt(0).all())

    batting = prior_v2.transform_prior_family(
        frame.iloc[:3], fitted, "BATTER_PRIOR_AB_OUTCOME_COMPOSITION"
    )
    batting_prefix = "mlb_prior_v2__batter_prior_ab_outcome_composition__posterior_"
    batting_cells = [
        f"{batting_prefix}{name}"
        for name in ("single", "double", "triple", "home_run", "non_hit_at_bat")
    ]
    average = batting[prior_v2.feature_binding("batter_avg")["derivedOutputs"]["posteriorMean"]]
    slugging = batting[prior_v2.feature_binding("batter_slg")["derivedOutputs"]["posteriorMean"]]
    assert np.allclose(average, batting[batting_cells[:4]].sum(axis=1))
    assert np.allclose(
        slugging,
        batting[batting_cells].to_numpy()
        @ np.asarray([1.0, 2.0, 3.0, 4.0, 0.0]),
    )

    whip = prior_v2.transform_prior_family(
        frame.iloc[:3], fitted, "PITCHER_PRIOR_WHIP_COMPONENTS"
    )
    whip_binding = prior_v2.feature_binding("pitcher_whip")
    assert np.allclose(
        whip[whip_binding["derivedOutputs"]["posteriorMean"]],
        3.0
        * (
            whip["pitcher_whip__prior_v2__hits_per_out_posterior_mean"]
            + whip["pitcher_whip__prior_v2__walks_per_out_posterior_mean"]
        ),
    )
    zero_outs = frame.iloc[[0]].copy()
    zero_outs["pitcher_prior_ipouts"] = 0
    zero_outs["pitcher_prior_h"] = 1
    zero_outs["pitcher_prior_bb"] = 1
    fallback = prior_v2.transform_prior_family(
        zero_outs, fitted, "PITCHER_PRIOR_WHIP_COMPONENTS"
    )
    assert fallback[whip_binding["derivedOutputs"]["historyState"]].iloc[0] == "COMPUTATION_FAILURE"
    assert fallback[whip_binding["derivedOutputs"]["posteriorReliability"]].iloc[0] == 0
    assert np.isfinite(fallback[whip_binding["derivedOutputs"]["posteriorMean"]].iloc[0])

    velocity = prior_v2.transform_prior_family(
        frame.iloc[:3], fitted, "PITCHER_LAST250_FASTBALL_VELOCITY"
    )
    velocity_prefix = "pitcher_last250_avg_fastball_velocity__prior_v2"
    assert np.allclose(
        velocity[f"{velocity_prefix}__sample_mean"],
        frame.iloc[:3]["pitcher_last250_fastball_velocity_sum"]
        / frame.iloc[:3]["pitcher_last250_fastball_velocity_count"],
    )
    zero_velocity = frame.iloc[[0]].copy()
    zero_velocity[
        [
            "pitcher_last250_fastball_velocity_count",
            "pitcher_last250_fastball_velocity_sum",
            "pitcher_last250_fastball_velocity_sumsq",
        ]
    ] = 0
    velocity_fallback = prior_v2.transform_prior_family(
        zero_velocity, fitted, "PITCHER_LAST250_FASTBALL_VELOCITY"
    )
    assert velocity_fallback[f"{velocity_prefix}__posterior_reliability"].iloc[0] == 0
    assert velocity_fallback[f"{velocity_prefix}__posterior_mean"].iloc[0] == pytest.approx(
        fitted["parameters"]["PITCHER_LAST250_FASTBALL_VELOCITY"]["populationMean"]
    )


def test_batting_domain_failures_and_oot_rejection_are_fail_closed() -> None:
    frame = _synthetic_fit_frame().iloc[:10].copy()
    fitted = prior_v2.fit_fold_authority(
        frame,
        _definition(),
        _fold_record(),
        fold_contract_id="FOLD_CONTRACT:test",
        fold_contract_checksum="f" * 64,
    )
    h_ab = frame.iloc[[0]].copy()
    h_ab["batter_prior_h"] = h_ab["batter_prior_ab"] + 1
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as invalid_h:
        prior_v2.transform_prior_family(h_ab, fitted, "BATTER_PRIOR_AB_OUTCOME_COMPOSITION")
    assert invalid_h.value.code == "PRIOR_V2_COMPONENT_RECONCILIATION_FAILED"

    negative_single = frame.iloc[[0]].copy()
    negative_single["batter_prior_2b"] = negative_single["batter_prior_h"] + 1
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as invalid_single:
        prior_v2.transform_prior_family(
            negative_single, fitted, "BATTER_PRIOR_AB_OUTCOME_COMPOSITION"
        )
    assert invalid_single.value.code == "PRIOR_V2_COMPONENT_RECONCILIATION_FAILED"

    # Date authority is checked before the transform requests any component column.
    oot_identity_only = pd.DataFrame({"game_date": [prior_v2.FINAL_OOT_START]})
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as oot:
        prior_v2.transform_prior_family(
            oot_identity_only, fitted, "PITCHER_LAST250_WHIFF"
        )
    assert oot.value.code == "PRIOR_V2_TRANSFORM_CROSSES_FINAL_OOT"


def test_target_and_later_transform_rows_cannot_change_an_earlier_output() -> None:
    frame = _synthetic_fit_frame().iloc[:10].copy()
    fitted = prior_v2.fit_fold_authority(
        frame,
        _definition(),
        _fold_record(),
        fold_contract_id="FOLD_CONTRACT:test",
        fold_contract_checksum="f" * 64,
    )
    earlier = frame.iloc[:3].copy()
    baseline = prior_v2.transform_prior_feature(
        earlier, fitted, "pitcher_last250_whiff_rate"
    )
    target_changed = earlier.assign(outcome=["A", "B", "C"])
    changed = prior_v2.transform_prior_feature(
        target_changed, fitted, "pitcher_last250_whiff_rate"
    )
    pd.testing.assert_frame_equal(baseline, changed)

    later = frame.iloc[[3]].copy()
    later["canonicalPaId"] = "later-row"
    later["game_date"] = "2026-08-13"
    extended = prior_v2.transform_prior_feature(
        pd.concat([earlier, later], ignore_index=True),
        fitted,
        "pitcher_last250_whiff_rate",
    )
    pd.testing.assert_frame_equal(
        baseline.reset_index(drop=True), extended.iloc[:3].reset_index(drop=True)
    )


def test_future_season_rows_cannot_change_an_earlier_fitted_authority() -> None:
    frame = _synthetic_fit_frame()
    definition = _definition()
    record = _fold_record()
    kwargs = {
        "fold_contract_id": "FOLD_CONTRACT:test",
        "fold_contract_checksum": "f" * 64,
    }
    baseline = prior_v2.fit_fold_authority(frame, definition, record, **kwargs)

    future = frame.iloc[[0]].copy(deep=True)
    future["canonicalPaId"] = "future-season-row"
    future["canonicalGameId"] = "future-season-game"
    future["game_date"] = "2025-07-01"
    future["season"] = 2025
    for column in set(prior_v2.required_input_columns()) - {
        "canonicalPaId",
        "canonicalGameId",
        "game_date",
        "season",
        "pitcherCanonicalPlayerId",
        "batterCanonicalPlayerId",
    }:
        future[column] = -999_999
    with_future = prior_v2.fit_fold_authority(
        pd.concat([frame, future], ignore_index=True),
        definition,
        record,
        **kwargs,
    )

    assert with_future == baseline
    assert baseline["fitEvidence"]["populationUnit"] == (
        "LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF"
    )
    assert prior_v2.HISTORY_CUTOFF.startswith("annual: season <= Y-1")


def test_definition_identity_changes_with_governed_configuration() -> None:
    first = _definition(compiler_sha256="e" * 64)
    changed = _definition(compiler_sha256="f" * 64)
    assert first["definitionChecksum"] != changed["definitionChecksum"]
    assert first["definitionId"] != changed["definitionId"]


def test_five_fold_contract_is_expanding_date_atomic_and_content_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2023-12-31", "2024-01-10", freq="D")
    frame = pd.DataFrame(
        {
            "canonicalPaId": [f"pa-{number}" for number in range(len(dates))],
            "canonicalGameId": [f"game-{number}" for number in range(len(dates))],
            "game_date": dates,
        }
    )
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_START", "2023-12-31")
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_END", "2024-01-10")
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_ROWS", len(frame))

    first = prior_v2.build_five_fold_contract(frame)
    second = prior_v2.build_five_fold_contract(
        frame.sample(frac=1.0, random_state=23).reset_index(drop=True)
    )
    assert first == second
    assert len(first["folds"]) == 5
    assert first["targetColumnsRead"] == []
    assert first["featureSetRegistered"] is False

    previous_validation_end: pd.Timestamp | None = None
    validation_dates: set[pd.Timestamp] = set()
    for number, fold in enumerate(first["folds"], start=1):
        train_end = pd.Timestamp(fold["trainEnd"])
        validation_start = pd.Timestamp(fold["validationStart"])
        validation_end = pd.Timestamp(fold["validationEnd"])
        assert fold["foldNumber"] == number
        assert train_end < validation_start <= validation_end
        assert fold["preprocessingFitScope"] == "TRAINING_ROWS_OF_THIS_FOLD_ONLY"
        assert fold["validationStatisticsUsedForTraining"] is False
        assert fold["finalOotUsed"] is False
        if previous_validation_end is not None:
            assert train_end == previous_validation_end
        previous_validation_end = validation_end
        validation_dates.update(pd.date_range(validation_start, validation_end, freq="D"))

    assert validation_dates == set(pd.date_range("2024-01-01", "2024-01-10", freq="D"))


def test_fit_and_definition_tampering_fail_closed() -> None:
    definition = _definition()
    fitted = prior_v2.fit_fold_authority(
        _synthetic_fit_frame(),
        definition,
        _fold_record(),
        fold_contract_id="FOLD_CONTRACT:test",
        fold_contract_checksum="f" * 64,
    )

    tampered_fit = copy.deepcopy(fitted)
    tampered_fit["parameters"]["PITCHER_GS_APPEARANCE"]["priorStrength"] += 1.0
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as fit_error:
        prior_v2._validate_fitted(tampered_fit, definition=definition)
    assert fit_error.value.code == "PRIOR_V2_FITTED_CHECKSUM_MISMATCH"

    tampered_definition = copy.deepcopy(definition)
    tampered_definition["finalOotIdentity"]["payloadRowsRead"] = 1
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as definition_error:
        prior_v2._validate_definition(tampered_definition)
    assert definition_error.value.code == "PRIOR_V2_DEFINITION_CHECKSUM_MISMATCH"


def test_content_addressed_artifact_replay_and_byte_tamper_fail_closed(
    writable_tmp_path: Path,
) -> None:
    tmp_path = writable_tmp_path
    payload = {"schemaVersion": "TEST_V1", "nested": {"z": 2, "a": 1}}
    first = publish_artifact(payload, root=tmp_path)
    second = publish_artifact(copy.deepcopy(payload), root=tmp_path)
    assert first["sha256"] == second["sha256"]
    assert first["created"] is True
    assert second["created"] is False
    assert load_artifact(first["sha256"], root=tmp_path) == payload

    artifact_path = Path(first["path"])
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
    with pytest.raises(PriorArtifactStoreV2Error) as error:
        load_artifact(first["sha256"], root=tmp_path)
    assert error.value.code == "PRIOR_V2_ARTIFACT_CHECKSUM_MISMATCH"


def test_parent_bundle_verifies_fold_contract_children_and_zero_model_activity(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = writable_tmp_path
    fixture = _chronological_bundle_fixture(monkeypatch, root)
    definition = fixture["definition"]
    contract = fixture["contract"]
    bundle = fixture["bundle"]
    verified = prior_v2._validate_bundle(
        bundle, expected_definition=definition, root=root
    )

    assert len({item["fittedId"] for item in verified["foldAuthorities"]}) == 5
    assert [item["trainingRows"] for item in verified["foldAuthorities"]] == [
        5,
        10,
        15,
        20,
        25,
    ]
    assert [item["trainingEnd"] for item in verified["foldAuthorities"]] == [
        "2023-12-31",
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
    ]
    assert verified["finalDevelopmentAuthority"]["fittedId"] not in {
        item["fittedId"] for item in verified["foldAuthorities"]
    }
    assert verified["finalDevelopmentAuthority"]["trainingStart"] == (
        contract["developmentIdentity"]["startDate"]
    )
    assert verified["finalDevelopmentAuthority"]["trainingEnd"] == (
        contract["developmentIdentity"]["endDate"]
    )
    assert verified["finalDevelopmentAuthority"]["trainingRows"] == (
        contract["developmentIdentity"]["rows"]
    )
    assert verified["finalDevelopmentAuthority"]["trainingMembershipChecksum"] == (
        contract["developmentIdentity"]["membershipChecksum"]
    )
    assert verified["foldContract"] == {
        "contractId": contract["contractId"],
        "contractChecksum": contract["contractChecksum"],
        "artifactSha256": fixture["contractReceipt"]["sha256"],
    }
    assert verified["audit"]["preprocessingFits"] == 6
    assert all(
        verified["audit"][name] == 0
        for name in (
            "predictiveModelFits",
            "scores",
            "calibrations",
            "promotions",
            "featureSetsRegistered",
            "policiesAdopted",
            "goldRowsMutated",
            "companionRowsMutated",
            "historicalArtifactMutations",
            "finalOotPayloadRowsRead",
            "finalOotPayloadRowsTransformed",
        )
    )


def test_parent_bundle_rejects_resigned_child_attached_to_wrong_fold(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = writable_tmp_path
    fixture = _chronological_bundle_fixture(monkeypatch, root)
    definition = fixture["definition"]
    folds = fixture["contract"]["folds"]
    children = fixture["children"]
    bundle = fixture["bundle"]

    wrong_fold = copy.deepcopy(children[0])
    wrong_fold["foldChecksum"] = folds[1]["checksum"]
    wrong_content = {
        key: copy.deepcopy(value)
        for key, value in wrong_fold.items()
        if key not in {"fittedChecksum", "fittedId"}
    }
    wrong_checksum = prior_v2._sha256(wrong_content)
    wrong_fold["fittedChecksum"] = wrong_checksum
    wrong_fold["fittedId"] = (
        f"{prior_v2.FITTED_SCHEMA_VERSION}:{wrong_fold['foldId']}:sha256:{wrong_checksum}"
    )
    wrong_receipt = publish_artifact(wrong_fold, root=root)
    tampered_bundle = copy.deepcopy(bundle)
    tampered_bundle["foldAuthorities"][0].update(
        {
            "fittedId": wrong_fold["fittedId"],
            "fittedChecksum": wrong_checksum,
            "artifactSha256": wrong_receipt["sha256"],
            "foldChecksum": wrong_fold["foldChecksum"],
        }
    )
    tampered_content = {
        key: copy.deepcopy(value)
        for key, value in tampered_bundle.items()
        if key not in {"authorityChecksum", "authorityId"}
    }
    tampered_checksum = prior_v2._sha256(tampered_content)
    tampered_bundle["authorityChecksum"] = tampered_checksum
    tampered_bundle["authorityId"] = (
        f"{prior_v2.AUTHORITY_NAME}:sha256:{tampered_checksum}"
    )
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as mismatch:
        prior_v2._validate_bundle(
            tampered_bundle, expected_definition=definition, root=root
        )
    assert mismatch.value.code == "PRIOR_V2_CHILD_FOLD_RECORD_MISMATCH"


def test_fold_contract_rejects_a_resigned_chronological_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _chronological_bundle_frame()
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_START", "2023-12-31")
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_END", "2024-01-05")
    monkeypatch.setattr(prior_v2, "DEVELOPMENT_ROWS", len(frame))
    contract = prior_v2.bind_fold_contract_project(
        prior_v2.build_five_fold_contract(frame), "asp-wave2-authority-test"
    )

    invalid = copy.deepcopy(contract)
    invalid["folds"][1]["validationStart"] = "2024-01-03"
    invalid["folds"][1]["validationEnd"] = "2024-01-03"
    invalid_record_content = {
        key: copy.deepcopy(value)
        for key, value in invalid["folds"][1].items()
        if key != "checksum"
    }
    invalid["folds"][1]["checksum"] = prior_v2._sha256(
        invalid_record_content
    )
    invalid_content = {
        key: copy.deepcopy(value)
        for key, value in invalid.items()
        if key not in {"contractChecksum", "contractId"}
    }
    invalid_checksum = prior_v2._sha256(invalid_content)
    invalid["contractChecksum"] = invalid_checksum
    invalid["contractId"] = (
        f"{prior_v2.FOLD_CONTRACT_SCHEMA_VERSION}:sha256:{invalid_checksum}"
    )

    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as chronology:
        prior_v2._validate_fold_contract(invalid)
    assert chronology.value.code == "PRIOR_V2_FOLD_NOT_EXPANDING"


def test_parent_bundle_rejects_a_chronological_child_as_final_development(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = writable_tmp_path
    fixture = _chronological_bundle_fixture(monkeypatch, root)

    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as scope:
        prior_v2.assemble_fit_bundle(
            fixture["definition"],
            fixture["children"],
            fixture["children"][-1],
            fold_contract=fixture["contract"],
            definition_artifact_sha256=fixture["definitionReceipt"]["sha256"],
            fold_contract_artifact_sha256=fixture["contractReceipt"]["sha256"],
            fold_artifact_sha256=[
                receipt["sha256"] for receipt in fixture["childReceipts"]
            ],
            final_artifact_sha256=fixture["childReceipts"][-1]["sha256"],
        )
    assert scope.value.code == "PRIOR_V2_CHILD_SCOPE_INVALID"


def test_parent_bundle_rejects_resigned_narrow_final_development_child(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = writable_tmp_path
    fixture = _chronological_bundle_fixture(monkeypatch, root)
    narrow = copy.deepcopy(fixture["final"])
    narrow["trainingRows"] = int(narrow["trainingRows"]) - 5
    narrow_content = {
        key: copy.deepcopy(value)
        for key, value in narrow.items()
        if key not in {"fittedChecksum", "fittedId"}
    }
    narrow_checksum = prior_v2._sha256(narrow_content)
    narrow["fittedChecksum"] = narrow_checksum
    narrow["fittedId"] = (
        f"{prior_v2.FITTED_SCHEMA_VERSION}:FINAL_DEVELOPMENT:sha256:{narrow_checksum}"
    )

    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as scope:
        prior_v2.assemble_fit_bundle(
            fixture["definition"],
            fixture["children"],
            narrow,
            fold_contract=fixture["contract"],
            definition_artifact_sha256=fixture["definitionReceipt"]["sha256"],
            fold_contract_artifact_sha256=fixture["contractReceipt"]["sha256"],
            fold_artifact_sha256=[
                receipt["sha256"] for receipt in fixture["childReceipts"]
            ],
            final_artifact_sha256="f" * 64,
        )
    assert scope.value.code == "PRIOR_V2_FINAL_DEVELOPMENT_SCOPE_INVALID"


def test_resigned_malformed_fitted_parameter_payload_fails_closed() -> None:
    frame = _synthetic_fit_frame().iloc[:10].copy()
    fitted = prior_v2.fit_fold_authority(
        frame,
        _definition(),
        _fold_record(),
        fold_contract_id="FOLD_CONTRACT:test",
        fold_contract_checksum="f" * 64,
    )
    malformed = copy.deepcopy(fitted)
    malformed["parameters"]["PITCHER_GS_APPEARANCE"]["priorAlpha"][0] = -1.0
    malformed_content = {
        key: copy.deepcopy(value)
        for key, value in malformed.items()
        if key not in {"fittedChecksum", "fittedId"}
    }
    checksum = prior_v2._sha256(malformed_content)
    malformed["fittedChecksum"] = checksum
    malformed["fittedId"] = (
        f"{prior_v2.FITTED_SCHEMA_VERSION}:{malformed['foldId']}:sha256:{checksum}"
    )

    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as error:
        prior_v2._validate_fitted(malformed, definition=_definition())
    assert error.value.code == "PRIOR_V2_FITTED_PARAMETER_DOMAIN_INVALID"


def test_resigned_companion_receipt_cannot_change_identity_or_rights() -> None:
    changed_identity = copy.deepcopy(_companion_authentication())
    changed_identity["objectSha256"][0] = "0" * 64
    changed_identity["authenticationChecksum"] = prior_v2._sha256(
        {
            key: value
            for key, value in changed_identity.items()
            if key != "authenticationChecksum"
        }
    )
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as identity:
        prior_v2.companion_evidence_reference(changed_identity)
    assert identity.value.code == "PRIOR_V2_COMPANION_RECEIPT_IDENTITY_INVALID"

    relaxed_rights = copy.deepcopy(_companion_authentication())
    relaxed_rights["rights"]["effectiveStatus"] = "PUBLIC_REDISTRIBUTION_ALLOWED"
    relaxed_rights["authenticationChecksum"] = prior_v2._sha256(
        {
            key: value
            for key, value in relaxed_rights.items()
            if key != "authenticationChecksum"
        }
    )
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as rights:
        prior_v2.companion_evidence_reference(relaxed_rights)
    assert rights.value.code == "PRIOR_V2_COMPANION_RIGHTS_INVALID"


def test_missing_companion_registration_fails_closed(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sufficient_stats,
        "registered_sufficient_statistics_authority",
        lambda *_args, **_kwargs: None,
    )
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as error:
        prior_v2.authenticate_companion(
            Database(writable_tmp_path / "missing-companion.db"),
            _project_authority(),
            output_root=writable_tmp_path,
        )
    assert error.value.code == "PRIOR_V2_COMPANION_AUTHENTICATION_FAILED"


def test_final_oot_null_proof_uses_footer_statistics_only(
    writable_tmp_path: Path,
) -> None:
    tmp_path = writable_tmp_path
    path = tmp_path / "oot-key-only.parquet"
    table = pa.table(
        {
            "canonicalPaId": ["pa-1", "pa-2", "pa-3"],
            "payload_count": pa.array([None, None, None], type=pa.int64()),
            "payload_sum": pa.array([None, None, None], type=pa.float64()),
        }
    )
    pq.write_table(table, path, write_statistics=True)

    evidence = prior_v2._oot_footer_null_evidence(
        path, ["payload_count", "payload_sum"]
    )
    assert evidence["method"] == "PARQUET_FOOTER_COLUMN_STATISTICS_ONLY_NO_PAYLOAD_DECODE"
    assert evidence["rowCount"] == 3
    assert evidence["payloadColumns"] == [
        {"column": "payload_count", "nullCount": 3, "numValues": 0},
        {"column": "payload_sum", "nullCount": 3, "numValues": 0},
    ]
    assert evidence["checksum"] == prior_v2._sha256(
        {key: value for key, value in evidence.items() if key != "checksum"}
    )

    materialized = tmp_path / "oot-materialized.parquet"
    pq.write_table(
        pa.table({"payload_count": pa.array([None, 1, None], type=pa.int64())}),
        materialized,
        write_statistics=True,
    )
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as error:
        prior_v2._oot_footer_null_evidence(materialized, ["payload_count"])
    assert error.value.code == "PRIOR_V2_OOT_PAYLOAD_MATERIALIZED"


LIVE_DATABASE = Path(
    r"C:\Users\james\asp-model-studio\.runtime\asp-model-studio\persistence\asp_model_studio.db"
)
LIVE_COMPANION_MANIFEST = (
    sufficient_stats.DEFAULT_CURRENT_GOLD_ROOT
    / "sufficient-statistics"
    / "publications"
    / "sha256"
    / prior_v2.EXPECTED_COMPANION_MANIFEST_SHA256
    / "manifest.json"
)
LIVE_GOLD_MANIFEST = (
    sufficient_stats.DEFAULT_CURRENT_GOLD_ROOT
    / "publications"
    / "sha256"
    / prior_v2.EXPECTED_GOLD_MANIFEST_SHA256
    / "manifest.json"
)
LIVE_RUNTIME_ROOT = LIVE_DATABASE.parent.parent
LIVE_HISTORICAL_ARTIFACT_ROOT = (
    LIVE_RUNTIME_ROOT
    / "stage3-executable-artifacts"
    / "objects"
    / "sha256"
    / "58ddf83092c2e91fde4c61c35f16c8cc5a3702d3a4da8f9f9164f2eab5641f6b"
)
LIVE_V1_POINTER = (
    LIVE_RUNTIME_ROOT
    / "stage3-player-prior-authorities"
    / "projects"
    / "asp-mtlozhdx"
    / "current.json"
)
LIVE_V1_OBJECT = (
    LIVE_RUNTIME_ROOT
    / "stage3-player-prior-authorities"
    / "objects"
    / "sha256"
    / "afe4ebdae76ef5c9429637c0b01007d464ca3b921092e92fa6486c3e3e2a139b"
    / "manifest.json"
)
WAVE1_DRAFT_IDENTITIES = (
    (
        "stage3_feature_treatment_spec_versions",
        "feature_treatment_spec_id",
        "stage3-feature-treatment-spec-06154e576ec9474580540f6cca287a17",
    ),
    (
        "stage3_treatment_policy_versions",
        "treatment_policy_id",
        "stage3-outlier-policy-7a9cba6a30b64e73bae613b720ea5805",
    ),
    (
        "stage3_treatment_policy_versions",
        "treatment_policy_id",
        "stage3-imputation-policy-1721c0822d744ca69ecc2c9d82841de4",
    ),
)


def _tree_content_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _wave1_draft_snapshot(database: Database) -> tuple[tuple[object, ...], ...]:
    rows: list[tuple[object, ...]] = []
    with database.connection() as connection:
        for table, identity_column, identity in WAVE1_DRAFT_IDENTITIES:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {identity_column} = ?",
                (identity,),
            ).fetchone()
            assert row is not None, f"Missing immutable Wave 1 DRAFT {identity}."
            rows.append((table, identity, *tuple(row)))
    return tuple(rows)


@pytest.mark.parametrize(
    ("tamper_kind", "expected_code"),
    (
        ("manifest", "PRIOR_V2_COMPANION_MANIFEST_INVALID"),
        ("partition", "PRIOR_V2_COMPANION_PARTITION_INVALID"),
    ),
)
def test_physically_modified_companion_manifest_or_partition_fails_closed(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
    expected_code: str,
) -> None:
    partitions: list[dict[str, object]] = []
    for number in range(5):
        role = (
            "DEVELOPMENT_SELECTION"
            if number < 4
            else sufficient_stats.FINAL_OOT_SEALED
        )
        table = pa.table(
            {
                "canonicalPaId": [f"physical-companion-{number}"],
                "datasetRole": [
                    "DEVELOPMENT_SELECTION" if number < 4 else "FINAL_OOT"
                ],
            }
        )
        temporary_path = writable_tmp_path / f"partition-{number}.parquet"
        pq.write_table(table, temporary_path, write_statistics=True)
        object_sha = prior_v2._file_sha(temporary_path)
        relative_path = f"objects/sha256/{object_sha}.parquet"
        object_path = writable_tmp_path / relative_path
        object_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.replace(object_path)
        partitions.append(
            {
                "relativePath": relative_path,
                "sha256": object_sha,
                "partitionRole": role,
            }
        )
    manifest_bytes = prior_v2.canonical_json_bytes({"partitions": partitions})
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = (
        writable_tmp_path
        / "sufficient-statistics"
        / "publications"
        / "sha256"
        / manifest_sha
        / "manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest_bytes)
    if tamper_kind == "manifest":
        manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    else:
        partition_path = writable_tmp_path / str(partitions[0]["relativePath"])
        partition_path.write_bytes(
            partition_path.read_bytes() + b"physically modified companion partition"
        )

    binding = copy.deepcopy(_companion_authentication()["bindingAuthority"])
    binding["manifestSha256"] = manifest_sha
    binding["objectSha256"] = [str(item["sha256"]) for item in partitions]
    monkeypatch.setattr(
        sufficient_stats,
        "registered_sufficient_statistics_authority",
        lambda *_args, **_kwargs: binding,
    )
    with pytest.raises(prior_v2.PlayerPriorAuthorityV2Error) as error:
        prior_v2.authenticate_companion(
            Database(writable_tmp_path / "tampered-companion.db"),
            _project_authority(),
            output_root=writable_tmp_path,
            expected_manifest_sha256=manifest_sha,
        )
    assert error.value.code == expected_code


@pytest.mark.skipif(
    not all(
        path.exists()
        for path in (
            LIVE_DATABASE,
            LIVE_COMPANION_MANIFEST,
            LIVE_GOLD_MANIFEST,
            LIVE_HISTORICAL_ARTIFACT_ROOT,
            LIVE_V1_POINTER,
            LIVE_V1_OBJECT,
        )
    ),
    reason="Immutable local MLB companion authority is not installed.",
)
def test_live_authentication_keeps_oot_sealed_and_all_inherited_authorities_immutable() -> None:
    database = Database(LIVE_DATABASE)
    authority = eda._resolve_authority(database, "asp-mtlozhdx")
    gold_before = LIVE_GOLD_MANIFEST.read_bytes()
    companion_before = LIVE_COMPANION_MANIFEST.read_bytes()
    historical_before = _tree_content_sha256(LIVE_HISTORICAL_ARTIFACT_ROOT)
    v1_before = LIVE_V1_POINTER.read_bytes()
    v1_object_before = LIVE_V1_OBJECT.read_bytes()
    drafts_before = _wave1_draft_snapshot(database)

    authentication = prior_v2.authenticate_companion(database, authority)
    final_oot = authentication["finalOot"]
    footer = final_oot["footerEvidence"]

    assert authentication["manifestSha256"] == prior_v2.EXPECTED_COMPANION_MANIFEST_SHA256
    assert authentication["registrationActive"] is False
    assert authentication["rowIdentity"]["goldMatch"] is True
    assert final_oot["rows"] == prior_v2.FINAL_OOT_ROWS
    assert final_oot["status"] == "KEY_ONLY_UNMATERIALIZED"
    assert final_oot["payloadRowsRead"] == 0
    assert final_oot["payloadColumnsRead"] == []
    assert footer["method"] == "PARQUET_FOOTER_COLUMN_STATISTICS_ONLY_NO_PAYLOAD_DECODE"
    assert footer["rowCount"] == prior_v2.FINAL_OOT_ROWS
    assert len(footer["payloadColumns"]) == len(
        sufficient_stats.sufficient_statistics_schema().names
    ) - 4
    assert all(item["nullCount"] == prior_v2.FINAL_OOT_ROWS for item in footer["payloadColumns"])
    assert all(item["numValues"] == 0 for item in footer["payloadColumns"])
    assert "_developmentPaths" in authentication
    assert not any(str(column).lower() in {"outcome", "target"} for column in final_oot["payloadColumnsRead"])
    assert hashlib.sha256(gold_before).hexdigest() == prior_v2.EXPECTED_GOLD_MANIFEST_SHA256
    assert hashlib.sha256(companion_before).hexdigest() == prior_v2.EXPECTED_COMPANION_MANIFEST_SHA256
    assert (LIVE_HISTORICAL_ARTIFACT_ROOT / "manifest.json").is_file()
    assert hashlib.sha256(
        (LIVE_HISTORICAL_ARTIFACT_ROOT / "manifest.json").read_bytes()
    ).hexdigest() == LIVE_HISTORICAL_ARTIFACT_ROOT.name
    v1_pointer = prior_v2._load_json(LIVE_V1_POINTER)
    assert v1_pointer["artifactSha256"] == LIVE_V1_OBJECT.parent.name
    assert hashlib.sha256(v1_object_before).hexdigest() == LIVE_V1_OBJECT.parent.name
    v1_object = prior_v2._load_json(LIVE_V1_OBJECT)
    assert v1_object["authority"]["authorityId"] == (
        "MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1:sha256:"
        "a363331fc47083bf5aaac07c437f2998ea21650b78538d2a69e258851812ff43"
    )
    assert v1_object["authority"]["authorityChecksum"] == (
        "a363331fc47083bf5aaac07c437f2998ea21650b78538d2a69e258851812ff43"
    )
    assert LIVE_GOLD_MANIFEST.read_bytes() == gold_before
    assert LIVE_COMPANION_MANIFEST.read_bytes() == companion_before
    assert _tree_content_sha256(LIVE_HISTORICAL_ARTIFACT_ROOT) == historical_before
    assert LIVE_V1_POINTER.read_bytes() == v1_before
    assert LIVE_V1_OBJECT.read_bytes() == v1_object_before
    assert _wave1_draft_snapshot(database) == drafts_before

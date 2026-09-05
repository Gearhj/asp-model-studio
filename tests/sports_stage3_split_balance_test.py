from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pytest

from server.persistence.db import Database
from server.persistence.repositories.stage3_split_contract_repository import (
    NO_CURRENT_SPLIT_CONTRACT,
    Stage3SplitContractRepository,
)
from server.sports_current_statcast import stage3_split_balance as split


PROJECT_ID = "synthetic-stage3-project"
FEATURE_SET_ID = "stage3-feature-set-core-48-v1"
FEATURE_SET_SHA = "a" * 64


def _frame() -> pd.DataFrame:
    # Complete 2023 warm-up plus an irregular, multi-season validation era.
    date_games = [
        ("2023-03-30", 2),
        ("2023-06-01", 1),
        ("2023-10-01", 2),
        ("2024-03-20", 1),
        ("2024-04-02", 3),
        ("2024-05-10", 2),
        ("2024-07-06", 1),
        ("2024-07-07", 2),
        ("2024-09-29", 3),
        ("2025-03-27", 1),
        ("2025-04-15", 2),
        ("2025-04-16", 3),
        ("2025-06-01", 1),
        ("2025-07-27", 2),
        ("2025-07-28", 3),
        ("2025-09-28", 1),
        ("2026-03-25", 2),
        ("2026-05-01", 3),
        ("2026-05-02", 1),
        ("2026-06-15", 2),
        ("2026-08-13", 3),
    ]
    rows: list[dict[str, object]] = []
    game_number = 0
    pa_number = 0
    for game_date, games in date_games:
        for _game in range(games):
            game_number += 1
            for outcome_index, outcome in enumerate(split.GOLD_CLASS_ORDER):
                pa_number += 1
                rows.append(
                    {
                        "canonicalGameId": f"game-{game_number:04d}",
                        "canonicalPaId": f"pa-{pa_number:06d}",
                        "game_date": game_date,
                        "outcome": outcome,
                        "batterCanonicalPlayerId": f"batter-{(game_number + outcome_index) % 17:02d}",
                        "pitcherCanonicalPlayerId": f"pitcher-{game_number % 11:02d}",
                        "batter_prior_missing": int(pa_number % 19 == 0),
                        "pitcher_prior_missing": int(pa_number % 31 == 0),
                        "batter_last100_insufficient": int(pa_number % 13 == 0),
                        "pitcher_last250_insufficient": int(pa_number % 23 == 0),
                        "feature_cont": None if pa_number % 10 == 0 else pa_number / 100.0,
                    }
                )
    # Poison final-OOT rows prove the scanner predicate runs before target use.
    rows.extend(
        [
            {
                "canonicalGameId": "oot-game",
                "canonicalPaId": f"oot-pa-{index}",
                "game_date": "2026-08-14",
                "outcome": "FINAL_OOT_TARGET_MUST_NOT_BE_READ",
                "batterCanonicalPlayerId": "oot-batter",
                "pitcherCanonicalPlayerId": "oot-pitcher",
                "batter_prior_missing": 0,
                "pitcher_prior_missing": 0,
                "batter_last100_insufficient": 0,
                "pitcher_last250_insufficient": 0,
                "feature_cont": 1.0,
            }
            for index in range(8)
        ]
    )
    return pd.DataFrame(rows)


def _authority() -> SimpleNamespace:
    fields = {
        "canonicalGameId": pa.string(),
        "canonicalPaId": pa.string(),
        "game_date": pa.string(),
        "outcome": pa.string(),
        "batterCanonicalPlayerId": pa.string(),
        "pitcherCanonicalPlayerId": pa.string(),
        "batter_prior_missing": pa.int64(),
        "pitcher_prior_missing": pa.int64(),
        "batter_last100_insufficient": pa.int64(),
        "pitcher_last250_insufficient": pa.int64(),
        "feature_cont": pa.float64(),
    }
    public = {
        "projectId": PROJECT_ID,
        "sourceDatasetId": "asp.mlb.statcast.current-pa.v1",
        "sourceManifestSha": "1" * 64,
        "goldDatasetId": split.CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": "2" * 64,
        "contextualDatasetId": "gold-table:gold_mlb_current_pa_context_v2",
        "contextualManifestSha": "3" * 64,
        "reviewDigest": "4" * 64,
    }
    return SimpleNamespace(
        project_id=PROJECT_ID,
        registration_id="registration-current",
        dataset_version_id="current-pa-v1",
        activation_revision=7,
        source_dataset_id=public["sourceDatasetId"],
        source_manifest_sha=public["sourceManifestSha"],
        gold_manifest_sha=public["goldManifestSha"],
        contextual_manifest_sha=public["contextualManifestSha"],
        review_digest=public["reviewDigest"],
        schema=pa.schema([pa.field(name, dtype) for name, dtype in fields.items()]),
        public=lambda: dict(public),
    )


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "stage3-split.db")
    database.initialize()
    return database


def _install_feature_set_authority(database: Database, authority: SimpleNamespace) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stage3_feature_set_versions (
              feature_set_id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              feature_set_status TEXT NOT NULL,
              registration_id TEXT NOT NULL,
              dataset_version_id TEXT NOT NULL,
              activation_revision INTEGER NOT NULL,
              source_dataset_id TEXT NOT NULL,
              source_manifest_sha TEXT NOT NULL,
              gold_manifest_sha TEXT NOT NULL,
              contextual_manifest_sha TEXT NOT NULL,
              authority_review_digest TEXT NOT NULL,
              content_sha256 TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO stage3_feature_set_versions (
              feature_set_id, project_id, feature_set_key, feature_set_name,
              feature_set_version, feature_set_status, registration_id,
              dataset_version_id, activation_revision, source_dataset_id,
              source_manifest_sha, gold_manifest_sha, contextual_manifest_sha,
              authority_review_digest, development_start_date,
              development_end_date, development_rows, final_oot_start_date,
              final_oot_end_date, final_oot_rows, ordered_features_json,
              family_memberships_json, transformation_contracts_json,
              interaction_contracts_json, content_sha256, created_by_user_id,
              created_at
            ) VALUES (
              ?, ?, 'core-48', 'Core Gold 48', 1, 'REGISTERED', ?, ?, ?, ?, ?,
              ?, ?, ?, '2023-03-30', '2026-08-13', 328,
              '2026-08-14', '2026-08-27', 8, '["feature_cont"]', '{}', '{}',
              '{}', ?, 'test-user', '2026-08-31T00:00:00Z'
            )
            """,
            (
                FEATURE_SET_ID,
                PROJECT_ID,
                authority.registration_id,
                authority.dataset_version_id,
                authority.activation_revision,
                authority.source_dataset_id,
                authority.source_manifest_sha,
                authority.gold_manifest_sha,
                authority.contextual_manifest_sha,
                authority.review_digest,
                FEATURE_SET_SHA,
            ),
        )


@pytest.fixture
def governed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Database, SimpleNamespace, pd.DataFrame, str, list[dict[str, object]]]:
    authority = _authority()
    source = _frame()
    development = source.loc[source["game_date"] <= "2026-08-13"].copy()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(split.eda, "_resolve_authority", lambda *_args: authority)
    monkeypatch.setattr(split.eda, "DEVELOPMENT_START", "2023-03-30")
    monkeypatch.setattr(split.eda, "DEVELOPMENT_END", "2026-08-13")
    monkeypatch.setattr(split.eda, "DEVELOPMENT_ROWS", len(development))
    monkeypatch.setattr(split.eda, "EXPECTED_FINAL_OOT", ("2026-08-14", "2026-08-27", 8))
    monkeypatch.setattr(split.eda, "FINAL_OOT_ROWS", 8)
    monkeypatch.setattr(
        split.eda,
        "_variables",
        lambda _authority: [
            {
                "name": "feature_cont",
                "selectable": True,
                "missingPercent": float(100.0 * development["feature_cont"].isna().mean()),
            }
        ],
    )

    def scan(
        _authority: object, columns: list[str], filters: dict[str, object]
    ) -> pd.DataFrame:
        calls.append({"columns": list(columns), "filters": dict(filters)})
        scoped = source.copy()
        if filters.get("startDate"):
            scoped = scoped.loc[scoped["game_date"] >= filters["startDate"]]
        if filters.get("endDate"):
            scoped = scoped.loc[scoped["game_date"] <= filters["endDate"]]
        return scoped[list(dict.fromkeys(columns))].copy()

    monkeypatch.setattr(split.eda, "_scan", scan)
    database = _database(tmp_path)
    key = split._authority_payload(authority)["authorityKey"]
    return database, authority, source, key, calls


def _accepted_payload() -> dict[str, object]:
    return {
        "foldCount": 5,
        "selectedFeatureSetIds": [FEATURE_SET_ID],
        "classPolicy": "NATURAL_BASE_RATES",
        "minimumTrainingGames": 1,
        "minimumValidationGames": 1,
    }


def test_summary_is_exact_development_only_and_never_reads_oot_target(
    governed: tuple[Database, SimpleNamespace, pd.DataFrame, str, list[dict[str, object]]]
) -> None:
    database, _authority_value, source, _key, calls = governed
    result = split.split_balance_summary(PROJECT_ID, database)
    development = source.loc[source["game_date"] <= "2026-08-13"]
    summary = result["data"]["summary"]
    assert summary["developmentRows"] == len(development)
    assert summary["developmentGames"] == development["canonicalGameId"].nunique()
    assert summary["developmentDates"] == development["game_date"].nunique()
    assert summary["finalOotRows"] == 8
    assert summary["finalOotLocked"] is True
    assert result["audit"]["finalOotTargetAccessed"] is False
    assert result["audit"]["modelActivity"]["fits"] == 0
    assert result["audit"]["splitActivity"]["modelsFit"] == 0
    assert all(call["filters"]["endDate"] == "2026-08-13" for call in calls)
    assert "FINAL_OOT_TARGET_MUST_NOT_BE_READ" not in {
        item["value"] for item in result["data"]["targetDistribution"]
    }
    assert result["data"]["contractState"]["expectedChecksum"] == NO_CURRENT_SPLIT_CONTRACT


def test_automatic_five_fold_design_is_game_grouped_date_atomic_and_globally_balanced(
    governed: tuple[Database, SimpleNamespace, pd.DataFrame, str, list[dict[str, object]]]
) -> None:
    database, authority, source, key, _calls = governed
    _install_feature_set_authority(database, authority)
    result = split.generate_automatic_split(
        PROJECT_ID, database, {"authorityKey": key, **_accepted_payload()}
    )
    folds = result["data"]["folds"]
    assert len(folds) == 5
    assert folds[0]["trainStart"] == "2023-03-30"
    assert folds[0]["trainEnd"] == "2023-10-01"
    assert folds[0]["validationStart"] == "2024-03-20"
    assert folds[-1]["validationEnd"] == "2026-08-13"
    assert all(
        folds[index]["trainGames"] < folds[index + 1]["trainGames"]
        for index in range(4)
    )
    validation_games: list[str] = []
    for fold in folds:
        assert fold["trainEnd"] < fold["validationStart"]
        assert fold["training"]["classDistribution"]
        assert fold["validation"]["classDistribution"]
        assert fold["training"]["physicalMissingness"]["featuresEvaluated"] == 1
        assert fold["training"]["physicalMissingness"]["byFeature"][0]["feature"] == "feature_cont"
        mask = source["game_date"].between(
            fold["validationStart"], fold["validationEnd"]
        )
        games = source.loc[mask, "canonicalGameId"].unique().tolist()
        assert len(games) == fold["validationGames"]
        validation_games.extend(games)
    expected_validation = set(
        source.loc[
            source["game_date"].between("2024-01-01", "2026-08-13"),
            "canonicalGameId",
        ]
    )
    assert set(validation_games) == expected_validation
    assert len(validation_games) == len(set(validation_games))
    counts = [fold["validationGames"] for fold in folds]
    assert max(counts) - min(counts) <= 3
    failing_gates = [
        gate
        for gate in result["data"]["design"]["qualityGates"]
        if gate["status"] != "PASS"
    ]
    assert result["data"]["design"]["allBlockingGatesPass"] is True, failing_gates
    assert result["data"]["design"]["selectedFeatureSets"] == [
        {"featureSetId": FEATURE_SET_ID, "checksum": FEATURE_SET_SHA}
    ]


def test_automatic_design_checksum_and_training_fold_weights_are_reproducible(
    governed: tuple[Database, SimpleNamespace, pd.DataFrame, str, list[dict[str, object]]]
) -> None:
    database, authority, source, key, _calls = governed
    _install_feature_set_authority(database, authority)
    payload = {
        "authorityKey": key,
        **_accepted_payload(),
        "classPolicy": "INVERSE_FREQUENCY_CLASS_WEIGHTS",
    }
    first = split.generate_automatic_split(PROJECT_ID, database, payload)["data"]["design"]
    second = split.generate_automatic_split(PROJECT_ID, database, payload)["data"]["design"]
    assert first["checksum"] == second["checksum"]
    assert [fold["checksum"] for fold in first["folds"]] == [
        fold["checksum"] for fold in second["folds"]
    ]
    fold_one_weights = first["folds"][0]["classWeights"]
    validation_start = first["folds"][0]["validationStart"]
    validation_end = first["folds"][0]["validationEnd"]
    source.loc[source["game_date"].between(validation_start, validation_end), "outcome"] = split.GOLD_CLASS_ORDER[0]
    altered = split.generate_automatic_split(PROJECT_ID, database, payload)["data"]["design"]
    assert altered["folds"][0]["classWeights"] == fold_one_weights
    assert altered["classPolicy"]["validationFrequenciesUsed"] is False


def test_manual_design_validates_exact_boundaries_overlap_oot_random_and_embargo(
    governed: tuple[Database, SimpleNamespace, pd.DataFrame, str, list[dict[str, object]]]
) -> None:
    database, authority, _source, key, _calls = governed
    _install_feature_set_authority(database, authority)
    automatic = split.generate_automatic_split(
        PROJECT_ID, database, {"authorityKey": key, **_accepted_payload()}
    )["data"]["folds"]
    manual_folds = [
        {
            "trainStart": fold["trainStart"],
            "trainEnd": fold["trainEnd"],
            "validationStart": fold["validationStart"],
            "validationEnd": fold["validationEnd"],
        }
        for fold in automatic
    ]
    valid = split.validate_manual_split(
        PROJECT_ID,
        database,
        {
            "authorityKey": key,
            **_accepted_payload(),
            "folds": manual_folds,
            "trainingPolicy": "EXPANDING_WINDOW",
        },
    )
    assert valid["data"]["valid"] is True
    truncated = [dict(item) for item in manual_folds]
    truncated[-1]["validationEnd"] = "2026-06-15"
    with pytest.raises(split.Stage3SplitBalanceError) as incomplete:
        split.validate_manual_split(
            PROJECT_ID,
            database,
            {"authorityKey": key, **_accepted_payload(), "folds": truncated},
        )
    assert incomplete.value.code == "SPLIT_MANUAL_VALIDATION_COVERAGE_INCOMPLETE"
    explicit_gap = split.validate_manual_split(
        PROJECT_ID,
        database,
        {
            "authorityKey": key,
            **_accepted_payload(),
            "folds": truncated,
            "allowGaps": True,
        },
    )
    coverage_gate = next(
        gate
        for gate in explicit_gap["data"]["qualityGates"]
        if gate["code"] == "VALIDATION_ASSIGNMENT_COMPLETE"
    )
    assert coverage_gate["status"] == "PASS"
    assert "Explicit manual gaps" in coverage_gate["detail"]
    overlap = [dict(item) for item in manual_folds]
    overlap[1]["validationStart"] = overlap[0]["validationEnd"]
    with pytest.raises(split.Stage3SplitBalanceError) as duplicate:
        split.validate_manual_split(
            PROJECT_ID,
            database,
            {"authorityKey": key, **_accepted_payload(), "folds": overlap},
        )
    assert duplicate.value.code in {
        "SPLIT_MANUAL_TARGET_DATE_LEAKAGE",
        "SPLIT_MANUAL_VALIDATION_OVERLAP",
    }
    oot = [dict(item) for item in manual_folds]
    oot[-1]["validationEnd"] = "2026-08-14"
    with pytest.raises(split.Stage3SplitBalanceError) as final_oot:
        split.validate_manual_split(
            PROJECT_ID,
            database,
            {"authorityKey": key, **_accepted_payload(), "folds": oot},
        )
    assert final_oot.value.code == "SPLIT_MANUAL_BOUNDARY_NOT_REPRESENTED"
    with pytest.raises(split.Stage3SplitBalanceError) as random_method:
        split.generate_automatic_split(
            PROJECT_ID,
            database,
            {"authorityKey": key, **_accepted_payload(), "method": "RANDOM_STRATIFIED_K_FOLD"},
        )
    assert random_method.value.code == "SPLIT_RANDOM_METHOD_PROHIBITED"
    embargoed = split.generate_automatic_split(
        PROJECT_ID,
        database,
        {"authorityKey": key, **_accepted_payload(), "embargoDays": 14},
    )["data"]["folds"]
    assert all(
        (pd.Timestamp(fold["validationStart"]) - pd.Timestamp(fold["trainEnd"])).days
        >= 15
        for fold in embargoed
    )


def test_split_contract_draft_register_supersede_checksum_and_concurrency(
    governed: tuple[Database, SimpleNamespace, pd.DataFrame, str, list[dict[str, object]]]
) -> None:
    database, authority, _source, key, _calls = governed
    _install_feature_set_authority(database, authority)
    base = {
        "authorityKey": key,
        **_accepted_payload(),
        "mode": "AUTOMATIC",
        "expectedChecksum": NO_CURRENT_SPLIT_CONTRACT,
        "notes": "first",
    }
    first = split.save_split_draft(
        PROJECT_ID, database, base, actor_user_id="user-1"
    )["data"]["contract"]
    assert first["status"] == "DRAFT"
    same = split.save_split_draft(
        PROJECT_ID,
        database,
        {**base, "expectedChecksum": first["checksum"]},
        actor_user_id="user-1",
    )["data"]["contract"]
    assert same["contractId"] == first["contractId"]
    stale_checksum = first["checksum"]
    second = split.save_split_draft(
        PROJECT_ID,
        database,
        {**base, "notes": "second", "expectedChecksum": stale_checksum},
        actor_user_id="user-1",
    )["data"]["contract"]
    with pytest.raises(split.Stage3SplitBalanceError) as stale:
        split.save_split_draft(
            PROJECT_ID,
            database,
            {**base, "notes": "concurrent loser", "expectedChecksum": stale_checksum},
            actor_user_id="user-2",
        )
    assert stale.value.code == "SPLIT_CONCURRENT_SAVE_CONFLICT"
    registered = split.register_split_contract(
        PROJECT_ID,
        database,
        {
            "authorityKey": key,
            "contractId": second["contractId"],
            "expectedChecksum": second["checksum"],
        },
        actor_user_id="user-1",
    )["data"]["contract"]
    assert registered["status"] == "REGISTERED"
    successor = split.save_split_draft(
        PROJECT_ID,
        database,
        {
            **base,
            "notes": "successor",
            "embargoDays": 1,
            "expectedChecksum": registered["checksum"],
        },
        actor_user_id="user-1",
    )["data"]["contract"]
    replacement = split.register_split_contract(
        PROJECT_ID,
        database,
        {
            "authorityKey": key,
            "contractId": successor["contractId"],
            "expectedChecksum": successor["checksum"],
        },
        actor_user_id="user-1",
    )["data"]["contract"]
    state = Stage3SplitContractRepository(database).contract_state(
        PROJECT_ID, authority.review_digest
    )
    assert state["currentRegistered"]["contractId"] == replacement["contractId"]
    assert any(
        row["contractId"] == registered["contractId"]
        and row["status"] == "SUPERSEDED"
        for row in state["history"]
    )
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE stage3_split_contract_versions SET notes = 'tampered' WHERE split_contract_id = ?",
                (replacement["contractId"],),
            )
        events = {
            row["event_type"]
            for row in connection.execute(
                "SELECT event_type FROM stage3_split_contract_events"
            ).fetchall()
        }
        bindings = connection.execute(
            """
            SELECT feature_set_id, feature_set_checksum, ordinal
            FROM stage3_split_contract_feature_sets
            WHERE split_contract_id = ?
            ORDER BY ordinal
            """,
            (replacement["contractId"],),
        ).fetchall()
        assert [tuple(row) for row in bindings] == [
            (FEATURE_SET_ID, FEATURE_SET_SHA, 0)
        ]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """
                UPDATE stage3_split_contract_feature_sets
                SET feature_set_checksum = ? WHERE split_contract_id = ?
                """,
                ("b" * 64, replacement["contractId"]),
            )
    assert {"DRAFT_CREATED", "DRAFT_UPDATED", "CONTRACT_REGISTERED", "CONTRACT_SUPERSEDED"}.issubset(events)


def test_registration_fails_closed_without_registered_feature_set_authority(
    governed: tuple[Database, SimpleNamespace, pd.DataFrame, str, list[dict[str, object]]]
) -> None:
    database, _authority_value, _source, key, _calls = governed
    preview = split.generate_automatic_split(
        PROJECT_ID,
        database,
        {"authorityKey": key, **_accepted_payload()},
    )["data"]["design"]
    gate = next(
        item
        for item in preview["qualityGates"]
        if item["code"] == "FEATURE_SET_VERSIONS_REGISTERED"
    )
    assert gate["status"] == "FAIL"
    draft = split.save_split_draft(
        PROJECT_ID,
        database,
        {
            "authorityKey": key,
            **_accepted_payload(),
            "mode": "AUTOMATIC",
            "expectedChecksum": NO_CURRENT_SPLIT_CONTRACT,
        },
        actor_user_id="user-1",
    )["data"]["contract"]
    with pytest.raises(split.Stage3SplitBalanceError) as blocked:
        split.register_split_contract(
            PROJECT_ID,
            database,
            {
                "authorityKey": key,
                "contractId": draft["contractId"],
                "expectedChecksum": draft["checksum"],
            },
            actor_user_id="user-1",
        )
    assert blocked.value.code == "SPLIT_QUALITY_GATES_BLOCKED"

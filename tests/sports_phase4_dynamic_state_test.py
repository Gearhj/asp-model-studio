from __future__ import annotations

import math
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase4.dynamic_contract import (
    CONTRACT_NAME,
    DECISION_ENUM,
    KEY_COLUMNS,
    LOG_ODDS_CLASSES,
    dynamic_state_contract_payload,
    dynamic_state_contract_sha,
    dynamic_state_schema_sha,
    dynamic_state_schema_spec,
)
from server.sports_phase4.dynamic_state import (
    DynamicPolicyTuning,
    DynamicStateIntegrityError,
    FrozenDynamicPolicy,
    _arrow_schema,
    _history_arrow_schema,
    _history_content_sha,
    _logical_content_sha,
    build_dynamic_player_state_from_tables,
    build_historical_dynamic_index,
    build_historical_outcome_index,
    dynamic_state_rows_for_keys,
    exact_retrosheet_alias_map,
    historical_dynamic_index_descriptor,
    load_historical_dynamic_index,
    materialize_dynamic_player_state,
    tune_dynamic_policy,
)


BATTER_UUID = "00000000-0000-4000-8000-000000000101"
PITCHER_UUID = "00000000-0000-4000-8000-000000000102"
DIMENSIONS = frozenset({BATTER_UUID, PITCHER_UUID})
ALIASES = {
    "batter-key": BATTER_UUID,
    "pitcher-key": PITCHER_UUID,
}


def _source_row(
    ordinal: int,
    *,
    game_date: str,
    final_date: str,
    outcome: str,
) -> dict[str, object]:
    return {
        "plate_appearance_id": f"historical-pa-{ordinal}",
        "game_id": f"historical-game-{ordinal}",
        "game_date": game_date,
        "season": int(game_date[:4]),
        "batter_id": "batter-key",
        "pitcher_id": "pitcher-key",
        "outcome": outcome,
        "final_available_date": final_date,
        "available_only_after_game_final": True,
        "future_evidence_allowed": False,
        "canonical_identity_resolved": False,
        "target_only_not_pregame_feature": True,
        "strict_same_game_pregame_eligible": False,
        "timing_risk_label": "RETROSPECTIVE_EVENT_OUTCOME_TIMING_RISK",
    }


def _historical_rows() -> list[dict[str, object]]:
    return [
        _source_row(1, game_date="2021-04-01", final_date="2021-04-01", outcome="STRIKEOUT"),
        _source_row(2, game_date="2022-04-05", final_date="2022-04-05", outcome="SINGLE"),
        _source_row(3, game_date="2023-04-09", final_date="2023-04-09", outcome="HOME_RUN"),
        # Same-date evidence is ineligible even when another game on that date completed.
        _source_row(4, game_date="2023-04-10", final_date="2023-04-10", outcome="DOUBLE"),
        # A suspended game's outcome remains unavailable until its final date.
        _source_row(5, game_date="2023-04-01", final_date="2023-04-11", outcome="TRIPLE"),
    ]


def _target_table() -> pa.Table:
    rows: list[dict[str, object]] = []
    ordinal = 0
    for season, dates in (
        (2023, ("2023-04-07", "2023-04-08", "2023-04-09", "2023-04-10", "2023-04-12")),
        (2024, ("2024-04-01",)),
        (2025, ("2025-04-01",)),
    ):
        for game_date in dates:
            ordinal += 1
            rows.append(
                {
                    "plate_appearance_id": f"target-pa-{ordinal}",
                    "game_id": f"target-game-{ordinal}",
                    "game_date": game_date,
                    "season": season,
                    "outcome": PA_CLASS_ORDER[ordinal % len(PA_CLASS_ORDER)],
                    "batter_canonical_player_uuid": BATTER_UUID,
                    "pitcher_canonical_player_uuid": PITCHER_UUID,
                }
            )
    return pa.Table.from_pylist(rows)


def _history(rows: list[dict[str, object]] | None = None):
    return build_historical_outcome_index(
        [pa.Table.from_pylist(rows or _historical_rows())],
        alias_rows=ALIASES,
        dimension_uuids=DIMENSIONS,
        source_partition_ids=("plate-appearance-2021", "plate-appearance-2022", "plate-appearance-2023"),
    )


class SportsPhase4DynamicStateTest(unittest.TestCase):
    def test_contract_has_exact_public_name_bindings_and_decision_enum(self) -> None:
        payload = dynamic_state_contract_payload()
        self.assertEqual(payload["contractName"], "MLB_DYNAMIC_PLAYER_STATE_V1")
        self.assertEqual(CONTRACT_NAME, "MLB_DYNAMIC_PLAYER_STATE_V1")
        self.assertEqual(tuple(payload["evaluationPolicy"]["decisionEnum"]), DECISION_ENUM)
        self.assertEqual(
            payload["temporalPolicy"]["eligibilityPredicate"],
            "source.final_available_date < target.game_date",
        )
        self.assertEqual(
            payload["authorityBindings"]["dataset"]["sourceFamily"],
            "plate_appearance",
        )
        self.assertTrue(payload["authorityBindings"]["dataset"]["descriptorSourcePartitionIdsRequired"])
        self.assertEqual(
            payload["artifactPolicy"]["bodyBindingFields"],
            [
                "schemaVersion",
                "createdAt",
                "codeRevision",
                "datasetManifestSha",
                "identityBridgeManifestSha",
                "phase3FeatureContractSha",
                "componentContractSha",
                "artifactType",
                "temporalFold",
                "sourcePartitionIds",
                "classOrder",
                "targetOrder",
            ],
        )
        self.assertTrue(payload["artifactPolicy"]["selfDigestCircularityProhibited"])
        self.assertIn("stateRowId", [field["name"] for field in dynamic_state_schema_spec()["fields"]])
        self.assertEqual(dynamic_state_contract_sha(payload), dynamic_state_contract_sha())
        self.assertEqual(len(dynamic_state_schema_sha()), 64)

    def test_prior_date_rule_and_final_availability_are_fail_closed(self) -> None:
        history = _history()
        policy = FrozenDynamicPolicy.create(half_life_days=30, prior_ess=50)
        before_final = history.snapshot(
            role="BATTER",
            canonical_player_uuid=BATTER_UUID,
            target_game_date="2023-04-10",
            target_season=2023,
            state_kind="B_CUMULATIVE",
            policy=policy,
        )
        self.assertEqual(before_final.eligible_event_count, 3)
        self.assertEqual(before_final.last_evidence_date, "2023-04-09")
        self.assertEqual(before_final.window_counts, (1, 1, 1))

        after_final = history.snapshot(
            role="BATTER",
            canonical_player_uuid=BATTER_UUID,
            target_game_date="2023-04-12",
            target_season=2023,
            state_kind="B_CUMULATIVE",
            policy=policy,
        )
        self.assertEqual(after_final.eligible_event_count, 5)
        self.assertEqual(after_final.last_evidence_date, "2023-04-11")
        self.assertEqual(after_final.days_since_evidence, 1)

        rows = _historical_rows()
        rows[0].pop("final_available_date")
        with self.assertRaisesRegex(DynamicStateIntegrityError, "missing required fields"):
            _history(rows)

    def test_preseason_and_recency_states_are_nonoverlapping_and_explicit(self) -> None:
        history = _history()
        policy = FrozenDynamicPolicy.create(half_life_days=60, prior_ess=150)
        preseason_early = history.snapshot(
            role="PITCHER",
            canonical_player_uuid=PITCHER_UUID,
            target_game_date="2023-04-10",
            target_season=2023,
            state_kind="A_PRESEASON",
            policy=policy,
        )
        preseason_late = history.snapshot(
            role="PITCHER",
            canonical_player_uuid=PITCHER_UUID,
            target_game_date="2023-09-10",
            target_season=2023,
            state_kind="A_PRESEASON",
            policy=policy,
        )
        self.assertEqual(preseason_early.eligible_event_count, 2)
        self.assertEqual(preseason_early.evidence_cutoff_exclusive, "2023-01-01")
        self.assertEqual(preseason_early.probabilities.tolist(), preseason_late.probabilities.tolist())

        recency = history.snapshot(
            role="PITCHER",
            canonical_player_uuid=PITCHER_UUID,
            target_game_date="2023-04-10",
            target_season=2023,
            state_kind="C_RECENCY",
            policy=policy,
        )
        self.assertEqual(recency.long_term_event_count, 1)
        self.assertEqual(recency.recent_event_count, 2)
        self.assertEqual(recency.overlap_event_count, 0)
        self.assertLess(recency.recent_effective_count, recency.recent_event_count)
        self.assertFalse(recency.missing_history)
        self.assertTrue(math.isclose(float(recency.probabilities.sum()), 1.0))

    def test_exact_bridge_rejects_ambiguous_and_unresolved_source_ids(self) -> None:
        with self.assertRaisesRegex(DynamicStateIntegrityError, "ambiguous or duplicated"):
            exact_retrosheet_alias_map(
                [
                    {"namespace": "RETROSHEET", "parent_join_key": "duplicate", "canonical_player_uuid": BATTER_UUID},
                    {"namespace": "RETROSHEET", "parent_join_key": "duplicate", "canonical_player_uuid": PITCHER_UUID},
                ],
                DIMENSIONS,
            )
        unresolved = _historical_rows()
        unresolved[0]["batter_id"] = "not-in-bridge"
        with self.assertRaisesRegex(DynamicStateIntegrityError, "identity is unresolved"):
            _history(unresolved)

    def test_tuning_uses_only_date_atomic_inner_2023_and_is_deterministic(self) -> None:
        history = _history()
        first = tune_dynamic_policy(_target_table(), history)
        second = tune_dynamic_policy(_target_table(), history)
        self.assertEqual(first.public(), second.public())
        self.assertEqual(len(first.candidates), 12)
        self.assertEqual(first.split_evidence["sourceSeason"], 2023)
        self.assertTrue(first.split_evidence["dateAtomic"])
        self.assertFalse(first.public()["selectionUses2024Or2025"])
        self.assertIn(first.policy.half_life_days, (30, 60, 120, None))
        self.assertIn(first.policy.prior_ess, (50, 150, 300))

    def test_frozen_role_state_evidence_is_complete_and_2025_cannot_affect_policy(self) -> None:
        target = _target_table()
        mutated_rows = target.to_pylist()
        changed = False
        for row in mutated_rows:
            if row["season"] == 2025:
                row["outcome"] = (
                    "STRIKEOUT" if row["outcome"] != "STRIKEOUT" else "HOME_RUN"
                )
                changed = True
        self.assertTrue(changed)
        mutated = pa.Table.from_pylist(mutated_rows, schema=target.schema)
        arguments = {
            "alias_rows": ALIASES,
            "dimension_uuids": DIMENSIONS,
            "code_revision": "fixture:frozen-evidence",
            "source_partition_ids": ("fixture-pa-history",),
        }
        first = build_dynamic_player_state_from_tables(
            [pa.Table.from_pylist(_historical_rows())],
            target,
            **arguments,
        )
        second = build_dynamic_player_state_from_tables(
            [pa.Table.from_pylist(_historical_rows())],
            mutated,
            **arguments,
        )
        self.assertEqual(first.policy.public(), second.policy.public())
        self.assertEqual(first.tuning.public(), second.tuning.public())
        evidence = first.posterior_predictive
        self.assertTrue(evidence["policyFrozenBeforeEvaluation"])
        self.assertFalse(evidence["selectionUses2024Or2025"])
        self.assertEqual(len(evidence["byRoleStateFold"]), 12)
        self.assertEqual(
            {
                (row["role"], row["stateKind"], row["validationSeason"])
                for row in evidence["byRoleStateFold"]
            },
            {
                (role, state_kind, season)
                for role in ("BATTER", "PITCHER")
                for state_kind in ("A_PRESEASON", "B_CUMULATIVE", "C_RECENCY")
                for season in (2024, 2025)
            },
        )
        first_2024 = [
            row for row in first.posterior_predictive["byRoleStateFold"]
            if row["validationSeason"] == 2024
        ]
        second_2024 = [
            row for row in second.posterior_predictive["byRoleStateFold"]
            if row["validationSeason"] == 2024
        ]
        self.assertEqual(first_2024, second_2024)
        self.assertNotEqual(
            [row for row in first.posterior_predictive["byRoleStateFold"] if row["validationSeason"] == 2025],
            [row for row in second.posterior_predictive["byRoleStateFold"] if row["validationSeason"] == 2025],
        )

    def test_materialization_has_deterministic_ids_checksums_and_bytes(self) -> None:
        history = _history()
        policy = FrozenDynamicPolicy.create(half_life_days=30, prior_ess=50)
        tuning = DynamicPolicyTuning(
            policy=policy,
            split_evidence={"dateAtomic": True, "sourceSeason": 2023},
            candidates=(),
        )
        target = _target_table()
        first = materialize_dynamic_player_state(target, history, tuning, code_revision="fixture:v1")
        reversed_target = target.take(pa.array(list(reversed(range(target.num_rows)))))
        second = materialize_dynamic_player_state(
            reversed_target,
            history,
            tuning,
            code_revision="fixture:v1",
        )
        self.assertEqual(first.row_count, len(set(target["game_date"].to_pylist())) * 2 * 3)
        self.assertEqual(first.content_sha, second.content_sha)
        self.assertEqual(first.parquet_bytes, second.parquet_bytes)
        rows = first.table.to_pylist()
        self.assertEqual(len({row["stateRowId"] for row in rows}), len(rows))
        for row in rows:
            semantic = dict(row)
            state_row_id = semantic.pop("stateRowId")
            row_sha = semantic.pop("rowContentSha")
            self.assertEqual(row_sha, sha256_bytes(canonical_json_bytes(semantic)))
            natural_key = {name: row[name] for name in KEY_COLUMNS}
            expected_id = "mlb-dynamic-player-state-row:sha256:" + sha256_bytes(
                canonical_json_bytes(
                    {
                        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_ROW_IDENTITY_V1",
                        "contractSha": dynamic_state_contract_sha(),
                        "naturalKey": natural_key,
                    }
                )
            )
            self.assertEqual(state_row_id, expected_id)
            self.assertEqual(
                len([name for name in row if name.startswith("log_odds_")]),
                len(LOG_ODDS_CLASSES),
            )
        parquet = pq.ParquetFile(pa.BufferReader(first.parquet_bytes))
        metadata = parquet.schema_arrow.metadata
        self.assertEqual(metadata[b"contractName"].decode(), CONTRACT_NAME)
        self.assertEqual(metadata[b"contentSha"].decode(), first.content_sha)

    def test_logical_content_sha_is_stable_across_live_parquet_batch_layout(self) -> None:
        history = _history()
        policy = FrozenDynamicPolicy.create(half_life_days=30, prior_ess=50)
        tuning = DynamicPolicyTuning(
            policy=policy,
            split_evidence={"dateAtomic": True, "sourceSeason": 2023},
            candidates=(),
        )
        base = materialize_dynamic_player_state(
            _target_table(),
            history,
            tuning,
            code_revision="fixture:live-batch-layout",
        ).table
        row_count = 65_537
        repeated = base.take(
            pa.array(
                [index % base.num_rows for index in range(row_count)],
                type=pa.int64(),
            )
        )
        schema = _arrow_schema()
        fresh_batches = [
            pa.RecordBatch.from_pydict(
                repeated.slice(offset, min(24_000, row_count - offset)).to_pydict(),
                schema=schema,
            )
            for offset in range(0, row_count, 24_000)
        ]
        fresh = pa.Table.from_batches(fresh_batches, schema=schema)
        self.assertEqual([batch.num_rows for batch in fresh.to_batches()], [24_000, 24_000, 17_537])
        expected = _logical_content_sha(fresh, policy=policy)

        sink = pa.BufferOutputStream()
        pq.write_table(fresh, sink, row_group_size=65_536)
        parquet_bytes = sink.getvalue().to_pybytes()
        parquet = pq.ParquetFile(pa.BufferReader(parquet_bytes))
        self.assertEqual(parquet.num_row_groups, 2)
        restored = pq.read_table(pa.BufferReader(parquet_bytes))
        self.assertNotEqual(
            [batch.num_rows for batch in fresh.to_batches()],
            [batch.num_rows for batch in restored.to_batches()],
        )
        self.assertEqual(_logical_content_sha(restored, policy=policy), expected)

    def test_historical_index_roundtrip_and_on_demand_rows_are_exact_and_tamper_evident(self) -> None:
        history = _history()
        first = build_historical_dynamic_index(history, code_revision="fixture:v1")
        second = build_historical_dynamic_index(history, code_revision="fixture:v1")
        self.assertEqual(first.content_sha, second.content_sha)
        self.assertEqual(first.parquet_bytes, second.parquet_bytes)

        artifact_sha = sha256_bytes(first.parquet_bytes)
        artifact = {
            "artifactId": f"sports-phase4-artifact:dynamic_history_index:sha256:{artifact_sha}",
            "artifactType": "DYNAMIC_HISTORY_INDEX",
            "logicalUri": (
                f"asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
                f"objects/sha256/{artifact_sha[:2]}/{artifact_sha}/dynamic-history-index.parquet"
            ),
            "sha256": artifact_sha,
            "byteCount": len(first.parquet_bytes),
            "mediaType": "application/vnd.apache.parquet",
        }
        descriptor = historical_dynamic_index_descriptor(first, artifact)
        loaded = load_historical_dynamic_index(first.parquet_bytes, descriptor=descriptor)
        policy = FrozenDynamicPolicy.create(half_life_days=60, prior_ess=150)
        original_snapshot = history.snapshot(
            role="BATTER",
            canonical_player_uuid=BATTER_UUID,
            target_game_date="2023-04-12",
            target_season=2023,
            state_kind="C_RECENCY",
            policy=policy,
        )
        loaded_snapshot = loaded.snapshot(
            role="BATTER",
            canonical_player_uuid=BATTER_UUID,
            target_game_date="2023-04-12",
            target_season=2023,
            state_kind="C_RECENCY",
            policy=policy,
        )
        self.assertEqual(original_snapshot.eligible_event_count, loaded_snapshot.eligible_event_count)
        self.assertEqual(original_snapshot.probabilities.tolist(), loaded_snapshot.probabilities.tolist())

        on_demand = dynamic_state_rows_for_keys(
            loaded,
            (("2023-04-12", BATTER_UUID, "BATTER"),),
            policy=policy,
        )
        tuning = DynamicPolicyTuning(
            policy=policy,
            split_evidence={"dateAtomic": True, "sourceSeason": 2023},
            candidates=(),
        )
        full = materialize_dynamic_player_state(
            _target_table(),
            history,
            tuning,
            code_revision="fixture:v1",
        ).table
        matching = [
            row
            for row in full.to_pylist()
            if row["game_date"] == "2023-04-12"
            and row["canonical_player_uuid"] == BATTER_UUID
            and row["role"] == "BATTER"
            and row["state_kind"] == "C_RECENCY"
        ]
        self.assertEqual(on_demand.to_pylist(), matching)

        tampered_rows = first.table.to_pylist()
        tampered_rows[0]["count_strikeout"] += 1
        tampered_table = pa.Table.from_pylist(
            tampered_rows,
            schema=first.table.schema,
        )
        original_metadata = pq.ParquetFile(pa.BufferReader(first.parquet_bytes)).schema_arrow.metadata
        sink = pa.BufferOutputStream()
        pq.write_table(tampered_table.replace_schema_metadata(original_metadata), sink)
        tampered_bytes = sink.getvalue().to_pybytes()
        tampered_sha = sha256_bytes(tampered_bytes)
        tampered_descriptor = dict(descriptor)
        tampered_descriptor.update(
            {
                "artifactId": f"sports-phase4-artifact:dynamic_history_index:sha256:{tampered_sha}",
                "artifactSha": tampered_sha,
                "artifactBytes": len(tampered_bytes),
                "logicalUri": (
                    f"asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
                    f"objects/sha256/{tampered_sha[:2]}/{tampered_sha}/dynamic-history-index.parquet"
                ),
            }
        )
        with self.assertRaisesRegex(DynamicStateIntegrityError, "row identity or checksum"):
            load_historical_dynamic_index(tampered_bytes, descriptor=tampered_descriptor)

    def test_history_content_sha_is_stable_across_live_parquet_batch_layout(self) -> None:
        built = build_historical_dynamic_index(_history(), code_revision="fixture:history-layout")
        row_count = 65_537
        repeated = built.table.take(
            pa.array(
                [index % built.table.num_rows for index in range(row_count)],
                type=pa.int64(),
            )
        )
        schema = _history_arrow_schema()
        fresh_batches = [
            pa.RecordBatch.from_pydict(
                repeated.slice(offset, min(24_000, row_count - offset)).to_pydict(),
                schema=schema,
            )
            for offset in range(0, row_count, 24_000)
        ]
        fresh = pa.Table.from_batches(fresh_batches, schema=schema)
        bindings = {
            "source_partition_ids": built.source_partition_ids,
            "source_row_count": built.source_row_count,
            "resolved_reference_count": built.resolved_reference_count,
        }
        expected = _history_content_sha(fresh, **bindings)

        sink = pa.BufferOutputStream()
        pq.write_table(fresh, sink, row_group_size=65_536)
        parquet_bytes = sink.getvalue().to_pybytes()
        self.assertEqual(
            pq.ParquetFile(pa.BufferReader(parquet_bytes)).num_row_groups,
            2,
        )
        restored = pq.read_table(pa.BufferReader(parquet_bytes))
        self.assertNotEqual(
            [batch.num_rows for batch in fresh.to_batches()],
            [batch.num_rows for batch in restored.to_batches()],
        )
        self.assertEqual(_history_content_sha(restored, **bindings), expected)


if __name__ == "__main__":
    unittest.main()

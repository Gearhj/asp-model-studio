from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pyarrow as pa
import pytest

from server.sports_current_statcast import contextual_gold as contextual_gold_module
from server.sports_current_statcast.contextual_features import (
    CONTEXT_FEATURES,
    FUTURE_ABLATION_FAMILIES,
    GameContextInput,
    TeamAuthority,
    VenueAuthority,
)
from server.sports_current_statcast.contextual_gold import (
    CONTEXT_GOLD_CONTRACT,
    CONTEXT_GOLD_DATASET_ID,
    _append_context,
    _team_context,
    _team_table,
    _write_verification_receipt,
    contextual_feature_review,
    ContextualGoldError,
    issue_contextual_verification_receipt,
)
from server.sports_current_statcast.contextual_sources import ContextSourceGame
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_gold.contracts import GOLD_FEATURES


def _source() -> ContextSourceGame:
    return ContextSourceGame(
        canonical_game_id="game-1",
        season=2026,
        game_date=date(2026, 7, 4),
        home_team_id="HOME",
        away_team_id="AWAY",
        venue_key="MLB_STATS_API:1",
        scheduled_start_utc=datetime(2026, 7, 4, 23, tzinfo=timezone.utc),
        start_time_local=None,
        series_game_number=2,
        games_in_series=3,
        doubleheader_game_number=None,
        is_home_opener=False,
        duration_minutes=180,
        innings_played=9,
        source_game_id="1",
        source_partition_id="schedule-2026",
        source_sha256="a" * 64,
        source_cutoff="2026-07-05T00:00:00Z",
    )


def test_context_projection_preserves_core_order_values_and_row_identity() -> None:
    source = _source()
    game = GameContextInput(
        canonical_game_id=source.canonical_game_id,
        game_date=source.game_date,
        home_team_id=source.home_team_id,
        away_team_id=source.away_team_id,
        venue_id=source.venue_key,
        scheduled_start_utc=source.scheduled_start_utc,
        series_game_number=source.series_game_number,
        games_in_series=source.games_in_series,
        season_start_date=date(2026, 3, 25),
    )
    venues = {
        source.venue_key: VenueAuthority(
            source.venue_key, 40.8296, -73.9262, "America/New_York"
        )
    }
    teams = {
        "HOME": TeamAuthority("HOME", "AL", "E", "America/New_York"),
        "AWAY": TeamAuthority("AWAY", "NL", "E", "America/Chicago"),
    }
    rows, index = _team_context(
        [game],
        venues=venues,
        teams=teams,
        sources={source.canonical_game_id: source},
        distance_version="HAVERSINE_TEST_V1",
    )
    team_table = _team_table(rows)
    core_values: dict[str, list[object]] = {
        "canonicalPaId": ["pa-1"],
        "canonicalGameId": [source.canonical_game_id],
        "game_date": [source.game_date.isoformat()],
        "datasetRole": ["FINAL_OOT"],
    }
    for position, feature in enumerate(GOLD_FEATURES):
        core_values[feature] = [0 if feature == "context_top_bottom" else float(position)]
    core = pa.table(core_values)

    projected = _append_context(
        core,
        team_table=team_table,
        index=index,
        sources={source.canonical_game_id: source},
        distance_version="HAVERSINE_TEST_V1",
    )

    assert projected.num_rows == core.num_rows == 1
    assert projected.column_names[: len(core.column_names)] == core.column_names
    assert projected.select(core.column_names).equals(core)
    assert projected.column_names[
        len(core.column_names): len(core.column_names) + len(CONTEXT_FEATURES)
    ] == list(CONTEXT_FEATURES)
    assert projected["canonicalPaId"].to_pylist() == ["pa-1"]
    assert projected["batting_team_alignment_missing"].to_pylist() == [0.0]
    assert projected["fielding_team_alignment_missing"].to_pylist() == [0.0]
    assert projected["batting_rivalry_game"].to_pylist() == [None]


def test_manifest_only_stage2_review_is_exactly_source_bound(tmp_path, monkeypatch) -> None:
    manifest = {
        "manifestContract": CONTEXT_GOLD_CONTRACT,
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "status": "RESEARCH_ONLY_FEATURE_EVIDENCE",
        "rowCount": 7,
        "coreFeatureCount": 48,
        "addedFeatureCount": len(CONTEXT_FEATURES),
        "totalFeatureCount": 48 + len(CONTEXT_FEATURES),
        "sourceGold": {"manifestSha256": "g" * 64},
        "teamGameContext": {"rowCount": 2},
        "rivalryMapping": {"status": "PROPOSED_NOT_APPROVED"},
        "featureCoverage": {},
        "featureFamilies": {
            name: list(features) for name, features in FUTURE_ABLATION_FAMILIES.items()
        },
        "interactions": [],
        "limitations": ["No model operation."],
    }
    body = canonical_json_bytes(manifest)
    sha = sha256_bytes(body)
    path = tmp_path / "publications" / "sha256" / sha / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    receipt_sha, receipt_path = _write_verification_receipt(
        tmp_path,
        sha,
        manifest,
        {
            "verified": True,
            "rowCount": 7,
            "teamGameRowCount": 2,
            "coreFeatureCount": 48,
            "addedFeatureCount": len(CONTEXT_FEATURES),
            "totalFeatureCount": 48 + len(CONTEXT_FEATURES),
            "modelsFitted": 0,
        },
    )
    current = {
        "manifestSha256": sha,
        "currentManifestSha256": sha,
        "manifestRelativePath": path.relative_to(tmp_path).as_posix(),
        "verificationReceiptSha256": receipt_sha,
        "verificationReceiptRelativePath": receipt_path.relative_to(tmp_path).as_posix(),
    }
    (tmp_path / "current.json").write_text(json.dumps(current), encoding="utf-8")

    assert contextual_feature_review(
        tmp_path, source_gold_manifest_sha256="other"
    ) is None
    review = contextual_feature_review(
        tmp_path, source_gold_manifest_sha256="g" * 64
    )
    assert review is not None
    assert review["verified"] is True
    assert review["manifestSha256"] == sha
    assert review["rowCount"] == 7
    assert [family["name"] for family in review["families"]] == list(
        FUTURE_ABLATION_FAMILIES
    )
    assert review["features"][:48][0]["category"] == "CORE_GOLD_48"
    assert all(not family["includedByDefault"] for family in review["families"][1:])


def test_stage2_review_fails_closed_for_missing_tampered_or_mismatched_receipt(
    tmp_path,
) -> None:
    manifest = {
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "rowCount": 1,
        "coreFeatureCount": 48,
        "addedFeatureCount": len(CONTEXT_FEATURES),
        "totalFeatureCount": 48 + len(CONTEXT_FEATURES),
        "sourceGold": {"manifestSha256": "g" * 64},
        "teamGameContext": {"rowCount": 2, "sha256": "t" * 64},
    }
    body = canonical_json_bytes(manifest)
    sha = sha256_bytes(body)
    manifest_path = tmp_path / "publications" / "sha256" / sha / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(body)
    locator = tmp_path / "current.json"
    locator.write_text(json.dumps({
        "manifestSha256": sha,
        "currentManifestSha256": sha,
        "manifestRelativePath": manifest_path.relative_to(tmp_path).as_posix(),
    }), encoding="utf-8")
    with pytest.raises(ContextualGoldError, match="receipt is missing"):
        contextual_feature_review(tmp_path)

    receipt_sha, receipt_path = _write_verification_receipt(
        tmp_path, sha, manifest,
        {"verified": True, "rowCount": 1, "teamGameRowCount": 2,
         "coreFeatureCount": 48, "addedFeatureCount": len(CONTEXT_FEATURES),
         "totalFeatureCount": 48 + len(CONTEXT_FEATURES), "modelsFitted": 0},
    )
    current = {"manifestSha256": sha, "currentManifestSha256": sha,
               "manifestRelativePath": manifest_path.relative_to(tmp_path).as_posix(),
               "verificationReceiptSha256": receipt_sha,
               "verificationReceiptRelativePath": receipt_path.relative_to(tmp_path).as_posix()}
    locator.write_text(json.dumps(current), encoding="utf-8")
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(ContextualGoldError, match="not content-addressed"):
        contextual_feature_review(tmp_path)

    receipt_path.write_bytes(canonical_json_bytes({
        **json.loads(receipt_path.read_bytes()[:-1]), "manifestSha256": "x" * 64
    }))
    mismatched_sha = sha256_bytes(receipt_path.read_bytes())
    mismatched_path = tmp_path / "verification-receipts" / "sha256" / mismatched_sha / "receipt.json"
    mismatched_path.parent.mkdir(parents=True)
    mismatched_path.write_bytes(receipt_path.read_bytes())
    current.update({"verificationReceiptSha256": mismatched_sha,
                    "verificationReceiptRelativePath": mismatched_path.relative_to(tmp_path).as_posix()})
    locator.write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(ContextualGoldError, match="bindings differ"):
        contextual_feature_review(tmp_path)


def test_metadata_only_receipt_issuance_preserves_manifest_and_objects(
    tmp_path, monkeypatch,
) -> None:
    manifest = {
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "rowCount": 11,
        "coreFeatureCount": 48,
        "addedFeatureCount": len(CONTEXT_FEATURES),
        "totalFeatureCount": 48 + len(CONTEXT_FEATURES),
        "sourceGold": {"manifestSha256": "g" * 64},
        "teamGameContext": {"rowCount": 4, "sha256": "t" * 64},
        "partitions": [{"sha256": "p" * 64}],
    }
    body = canonical_json_bytes(manifest)
    sha = sha256_bytes(body)
    manifest_path = tmp_path / "publications" / "sha256" / sha / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(body)
    object_path = tmp_path / "objects" / "sha256" / "immutable.parquet"
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"immutable-object")
    (tmp_path / "current.json").write_text(json.dumps({
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "manifestSha256": sha,
        "currentManifestSha256": sha,
        "historicalManifestSha256s": [],
        "manifestRelativePath": manifest_path.relative_to(tmp_path).as_posix(),
    }), encoding="utf-8")
    monkeypatch.setattr(contextual_gold_module, "verify_contextual_gold", lambda *_args, **_kwargs: {
        "verified": True, "rowCount": 11, "teamGameRowCount": 4,
        "coreFeatureCount": 48, "addedFeatureCount": len(CONTEXT_FEATURES),
        "totalFeatureCount": 48 + len(CONTEXT_FEATURES), "modelsFitted": 0,
    })

    result = issue_contextual_verification_receipt(tmp_path, sha)

    current = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    assert result["verificationReceiptSha256"] == current["verificationReceiptSha256"]
    assert manifest_path.read_bytes() == body
    assert object_path.read_bytes() == b"immutable-object"
    receipt = tmp_path / current["verificationReceiptRelativePath"]
    assert receipt.is_file() and sha256_bytes(receipt.read_bytes()) == current["verificationReceiptSha256"]

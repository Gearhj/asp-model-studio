from __future__ import annotations

import json
import os
import unittest
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow.parquet as pq

from server.sports_datasets.consumer import ValidatedPackage
from server.sports_datasets.feature_audit import build_mlb_pa_feature_audit
from tests.sports_dataset_test_fixture import golden_corpus_available


PACKAGE_RELATIVE_ROOT = (
    Path("datasets")
    / "mlb-fd1"
    / "sha256-1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
)
EXPECTED_MANIFEST_SHA = (
    "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
)

EXPECTED_PA_COUNTS = {
    2023: 184_104,
    2024: 182_449,
    2025: 182_926,
}

EXPECTED_PA_DATE_RANGES = {
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-20", "2024-09-30"),
    2025: ("2025-03-18", "2025-09-28"),
}

EXPECTED_SAME_DATE_AUTHORITY = (
    "Use final_available_date, source game_number, doubleheader_id, and canonical "
    "game identity; never borrow later same-date game evidence."
)

EXPECTED_PRIOR_ROLE_COUNTS = {
    2023: {"BATTING": 1_495, "PITCHING": 871},
    2024: {"BATTING": 1_457, "PITCHING": 863},
    2025: {"BATTING": 1_454, "PITCHING": 855},
}

EXPECTED_CLASS_ORDER = (
    "STRIKEOUT",
    "WALK_HBP_CI",
    "HOME_RUN",
    "SINGLE",
    "DOUBLE",
    "TRIPLE",
    "BIP_OUT",
    "OTHER_REACH",
)

PA_CONTEXT_FIELDS = (
    "inning",
    "top_bottom",
    "outs_before",
    "base_mask_before",
    "visiting_score_before",
    "home_score_before",
)

PA_TARGET_OR_POST_EVENT_FIELDS = (
    "terminal_play_id",
    "terminal_play_number",
    "source_terminal_token",
    "outcome",
    "outs_after",
    "base_mask_after",
    "runs_scored",
)

PA_PROVENANCE_FIELDS = (
    "source_key",
    "source_version_id",
    "source_filename",
    "source_row_number",
    "source_row_checksum",
    "source_file_sha256",
    "row_checksum",
)

ACTUAL_LINEUP_FIELDS = (
    "lineup_position",
    "actual_starting_lineup",
    "actual_batting_order",
    "actual_fielding_positions",
    "actual_fielding_positions_source",
)

ACTUAL_WEATHER_FIELDS = (
    "start_time_source",
    "day_night",
    "field_condition",
    "precipitation",
    "sky",
    "temperature_f",
    "wind_direction",
    "wind_speed_mph",
    "weather_coverage",
    "weather_source",
    "noaa_gap_fill",
)

EXCLUDED_IDENTITY_CLASSES = frozenset({"TARGET", "PROVENANCE"})
EXCLUDED_TEMPORAL_CLASSES = frozenset(
    {
        "POSTGAME_TARGET_ONLY",
        "PROVENANCE_ONLY",
        "RETROSPECTIVE_ACTUAL_NOT_PREGAME_SAFE",
    }
)


def _package_root() -> Path:
    configured = os.environ.get("ASP_MODEL_EXCHANGE_ROOT", "").strip()
    if not configured:
        raise RuntimeError("ASP_MODEL_EXCHANGE_ROOT is required")
    exchange_root = Path(configured).resolve(strict=True)
    package_root = (exchange_root / PACKAGE_RELATIVE_ROOT).resolve(strict=True)
    if exchange_root not in package_root.parents:
        raise AssertionError("Approved package root escaped ASP_MODEL_EXCHANGE_ROOT")
    return package_root


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"Expected JSON object in {path.name}")
    return value


def _partition_path(package_root: Path, partition: dict[str, Any]) -> Path:
    relative_uri = str(partition["package_relative_uri"])
    path = (package_root / Path(*relative_uri.split("/"))).resolve(strict=True)
    if package_root not in path.parents:
        raise AssertionError(f"Partition escaped approved package root: {relative_uri}")
    return path


def _field_authority(
    schema_registry: dict[str, Any], family: str
) -> dict[str, set[tuple[str, str]]]:
    family_record = next(item for item in schema_registry["families"] if item["family"] == family)
    authority: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for variant in family_record["physical_variants"]:
        for field in variant["fields"]:
            authority[field["name"]].add(
                (
                    field["target_feature_identity_classification"],
                    field["temporal_risk_classification"],
                )
            )
    return dict(authority)


def _is_excluded(authority: set[tuple[str, str]]) -> bool:
    return bool(authority) and all(
        identity_class in EXCLUDED_IDENTITY_CLASSES
        or temporal_class in EXCLUDED_TEMPORAL_CLASSES
        for identity_class, temporal_class in authority
    )


def _audit_feature_authority(package_root: Path) -> dict[str, Any]:
    manifest = _load_json(package_root / "sports-dataset-manifest.json")
    schema_registry = _load_json(package_root / "schema-registry.json")
    selected_partitions = [
        item
        for item in manifest["partitions"]
        if (
            item["family"] == "plate_appearance"
            and item["season"] in EXPECTED_PA_COUNTS
        )
        or (
            item["family"] == "player_prior"
            and item["season"] in (2022, 2023, 2024)
        )
    ]
    before_stats = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (
            package_root / "sports-dataset-manifest.json",
            package_root / "schema-registry.json",
            *(_partition_path(package_root, item) for item in selected_partitions),
        )
    }

    prior_ids: dict[tuple[int, str], set[str]] = defaultdict(set)
    prior_player_id_nulls = 0
    prior_rows = 0
    non_uuid_canonical_ids: list[str] = []
    invalid_prior_season_pairs: list[tuple[int, int]] = []
    same_season_eligibility_values: set[Any] = set()

    for partition in selected_partitions:
        if partition["family"] != "player_prior":
            continue
        table = pq.ParquetFile(_partition_path(package_root, partition)).read(
            columns=(
                "canonical_player_id",
                "player_id",
                "domain",
                "season",
                "eligible_from_season",
                "same_season_predictor_eligible",
            )
        )
        prior_rows += table.num_rows
        prior_player_id_nulls += table.column("player_id").null_count
        canonical_ids = table.column("canonical_player_id").to_pylist()
        domains = table.column("domain").to_pylist()
        prior_seasons = table.column("season").to_pylist()
        eligible_seasons = table.column("eligible_from_season").to_pylist()
        same_season_eligibility_values.update(
            table.column("same_season_predictor_eligible").to_pylist()
        )
        for canonical_id, domain, prior_season, eligible_season in zip(
            canonical_ids, domains, prior_seasons, eligible_seasons, strict=True
        ):
            if int(prior_season) + 1 != int(eligible_season):
                invalid_prior_season_pairs.append(
                    (int(prior_season), int(eligible_season))
                )
            try:
                parsed = uuid.UUID(canonical_id)
            except (AttributeError, TypeError, ValueError):
                non_uuid_canonical_ids.append(str(canonical_id))
                continue
            if str(parsed) != canonical_id.lower():
                non_uuid_canonical_ids.append(str(canonical_id))
            if domain in ("BATTING", "PITCHING"):
                prior_ids[(int(eligible_season), domain)].add(canonical_id)

    pa_counts = defaultdict(int)
    namespaces: set[Any] = set()
    resolution_values: set[Any] = set()
    invalid_retrosheet_ids = 0
    date_ranges: dict[int, list[str | None]] = {
        season: [None, None] for season in EXPECTED_PA_COUNTS
    }
    game_dates: dict[int, dict[str, set[str]]] = {
        season: defaultdict(set) for season in EXPECTED_PA_COUNTS
    }
    join_counts = {
        season: {"BATTING": 0, "PITCHING": 0}
        for season in EXPECTED_PA_COUNTS
    }

    for partition in selected_partitions:
        if partition["family"] != "plate_appearance":
            continue
        season = int(partition["season"])
        table = pq.ParquetFile(_partition_path(package_root, partition)).read(
            columns=(
                "batter_id",
                "pitcher_id",
                "game_id",
                "game_date",
                "identity_namespace",
                "canonical_identity_resolved",
            )
        )
        pa_counts[season] += table.num_rows
        batter_ids = table.column("batter_id").to_pylist()
        pitcher_ids = table.column("pitcher_id").to_pylist()
        partition_game_ids = table.column("game_id").to_pylist()
        partition_game_dates = table.column("game_date").to_pylist()
        for game_id, game_date in zip(
            partition_game_ids, partition_game_dates, strict=True
        ):
            game_dates[season][game_id].add(game_date)
        partition_min = min(partition_game_dates)
        partition_max = max(partition_game_dates)
        current_min, current_max = date_ranges[season]
        date_ranges[season][0] = (
            partition_min if current_min is None else min(current_min, partition_min)
        )
        date_ranges[season][1] = (
            partition_max if current_max is None else max(current_max, partition_max)
        )
        namespaces.update(table.column("identity_namespace").to_pylist())
        resolution_values.update(table.column("canonical_identity_resolved").to_pylist())
        invalid_retrosheet_ids += sum(
            not isinstance(player_id, str)
            or not player_id.startswith("retrosheet:player:")
            for player_id in (*batter_ids, *pitcher_ids)
        )
        batter_priors = prior_ids[(season, "BATTING")]
        pitcher_priors = prior_ids[(season, "PITCHING")]
        join_counts[season]["BATTING"] += sum(
            batter_id in batter_priors for batter_id in batter_ids
        )
        join_counts[season]["PITCHING"] += sum(
            pitcher_id in pitcher_priors for pitcher_id in pitcher_ids
        )

    target = next(
        item
        for item in manifest["target_definitions"]
        if item["target_id"] == "plate_appearance_outcome"
    )
    after_stats = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in before_stats
    }
    return {
        "pa_counts": dict(pa_counts),
        "namespaces": namespaces,
        "resolution_values": resolution_values,
        "invalid_retrosheet_ids": invalid_retrosheet_ids,
        "prior_rows": prior_rows,
        "prior_player_id_nulls": prior_player_id_nulls,
        "non_uuid_canonical_ids": non_uuid_canonical_ids,
        "invalid_prior_season_pairs": invalid_prior_season_pairs,
        "same_season_eligibility_values": same_season_eligibility_values,
        "prior_role_counts": {
            season: {
                role: len(prior_ids[(season, role)])
                for role in ("BATTING", "PITCHING")
            }
            for season in EXPECTED_PA_COUNTS
        },
        "join_counts": join_counts,
        "date_ranges": {
            season: tuple(bounds) for season, bounds in date_ranges.items()
        },
        "game_ids_with_multiple_dates": {
            season: sorted(
                game_id
                for game_id, dates in dates_by_game.items()
                if len(dates) != 1
            )
            for season, dates_by_game in game_dates.items()
        },
        "same_date_authority": manifest["temporal_contract"][
            "same_date_game_ordering"
        ],
        "no_current_season_future_evidence": manifest["temporal_contract"][
            "no_current_season_future_evidence"
        ],
        "no_current_game_evidence": manifest["temporal_contract"][
            "no_current_game_evidence"
        ],
        "class_order": tuple(target["ordered_classes"]),
        "authorities": {
            family: _field_authority(schema_registry, family)
            for family in (
                "plate_appearance",
                "player_game_batting",
                "player_game_pitching",
                "weather",
            )
        },
        "exchange_unchanged": before_stats == after_stats,
    }


@unittest.skipUnless(
    golden_corpus_available(),
    "ASP_MODEL_EXCHANGE_ROOT is required for package authority tests",
)
class SportsDatasetFeatureAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        write_error = AssertionError(
            "Feature-authority audit must not write feature or model output"
        )
        with (
            patch.object(Path, "write_text", side_effect=write_error) as write_text,
            patch.object(Path, "write_bytes", side_effect=write_error) as write_bytes,
            patch.object(Path, "mkdir", side_effect=write_error) as mkdir,
            patch.object(Path, "touch", side_effect=write_error) as touch,
            patch.object(pq, "write_table", side_effect=write_error) as write_table,
        ):
            package_root = _package_root()
            cls.audit = _audit_feature_authority(package_root)
            validated = ValidatedPackage(
                package_root=package_root,
                manifest=_load_json(package_root / "sports-dataset-manifest.json"),
                schema_registry=_load_json(package_root / "schema-registry.json"),
                source_rights=_load_json(package_root / "source-rights.json"),
                validation_report=_load_json(package_root / "validation-report.json"),
                partition_authority_sha="",
                root_identity="feature-authority-test",
                cache_hits=0,
                cache_misses=0,
                validated_at="feature-authority-test",
            )
            cls.live_feature_audit = build_mlb_pa_feature_audit(validated)
            cls.no_feature_or_model_output = not any(
                writer.called
                for writer in (write_text, write_bytes, mkdir, touch, write_table)
            )

    def test_package_only_identity_authority_blocks_feature_materialization(self) -> None:
        self.assertEqual(self.audit["pa_counts"], EXPECTED_PA_COUNTS)
        self.assertEqual(self.audit["namespaces"], {"RETROSHEET"})
        self.assertEqual(self.audit["resolution_values"], {False})
        self.assertEqual(self.audit["invalid_retrosheet_ids"], 0)

        self.assertGreater(self.audit["prior_rows"], 0)
        self.assertEqual(
            self.audit["prior_player_id_nulls"], self.audit["prior_rows"]
        )
        self.assertEqual(self.audit["non_uuid_canonical_ids"], [])
        self.assertEqual(self.audit["invalid_prior_season_pairs"], [])
        self.assertEqual(self.audit["same_season_eligibility_values"], {False})
        self.assertEqual(
            self.audit["prior_role_counts"], EXPECTED_PRIOR_ROLE_COUNTS
        )
        self.assertEqual(
            self.audit["join_counts"],
            {
                season: {"BATTING": 0, "PITCHING": 0}
                for season in EXPECTED_PA_COUNTS
            },
        )

        self.assertEqual(self.audit["date_ranges"], EXPECTED_PA_DATE_RANGES)
        self.assertEqual(
            self.audit["game_ids_with_multiple_dates"],
            {season: [] for season in EXPECTED_PA_COUNTS},
        )
        self.assertEqual(
            self.audit["same_date_authority"], EXPECTED_SAME_DATE_AUTHORITY
        )
        self.assertIs(self.audit["no_current_season_future_evidence"], True)
        self.assertIs(self.audit["no_current_game_evidence"], True)

        self.assertEqual(self.audit["class_order"], EXPECTED_CLASS_ORDER)
        self.assertTrue(self.audit["exchange_unchanged"])
        self.assertTrue(self.no_feature_or_model_output)

    def test_live_feature_audit_matches_independent_package_authority(self) -> None:
        live = self.live_feature_audit
        self.assertEqual(
            set(live),
            {
                "contractVersion",
                "status",
                "method",
                "sourceManifestSha",
                "observedNamespaces",
                "perSeasonRows",
                "joinEvidence",
                "checks",
                "unsafeContext",
                "missingBridge",
                "auditedAt",
            },
        )
        self.assertEqual(live["contractVersion"], "MLB_PA_FEATURE_VIEW_V1")
        self.assertEqual(live["status"], "BLOCKED")
        self.assertEqual(
            live["method"], "PACKAGE_ONLY_EXACT_NAMESPACE_MEMBERSHIP_AUDIT_V1"
        )
        self.assertEqual(live["sourceManifestSha"], EXPECTED_MANIFEST_SHA)
        self.assertEqual(
            live["observedNamespaces"],
            {
                "plateAppearance": ["RETROSHEET"],
                "playerPrior": ["ASP_CANONICAL_UUID", "LAHMAN_PLAYER_ID"],
            },
        )

        rows_by_season = {
            item["season"]: item for item in live["perSeasonRows"]
        }
        self.assertEqual(set(rows_by_season), set(EXPECTED_PA_COUNTS))
        for season in EXPECTED_PA_COUNTS:
            with self.subTest(season=season):
                row = rows_by_season[season]
                self.assertEqual(
                    row["plateAppearanceRows"], self.audit["pa_counts"][season]
                )
                self.assertEqual(
                    row["eligibleBattingPriorRows"],
                    self.audit["prior_role_counts"][season]["BATTING"],
                )
                self.assertEqual(
                    row["eligiblePitchingPriorRows"],
                    self.audit["prior_role_counts"][season]["PITCHING"],
                )
                self.assertEqual(
                    row["eligibleUniqueBatterPriorCanonicalIds"],
                    self.audit["prior_role_counts"][season]["BATTING"],
                )
                self.assertEqual(
                    row["eligibleUniquePitcherPriorCanonicalIds"],
                    self.audit["prior_role_counts"][season]["PITCHING"],
                )
                self.assertEqual(row["batterYMinus1JoinMatches"], 0)
                self.assertEqual(
                    row["batterYMinus1JoinDenominator"], EXPECTED_PA_COUNTS[season]
                )
                self.assertEqual(row["pitcherYMinus1JoinMatches"], 0)
                self.assertEqual(
                    row["pitcherYMinus1JoinDenominator"], EXPECTED_PA_COUNTS[season]
                )

        join_evidence = live["joinEvidence"]
        self.assertEqual(join_evidence["batterMatches"], 0)
        self.assertEqual(join_evidence["pitcherMatches"], 0)
        self.assertEqual(
            join_evidence["batterDenominator"], sum(EXPECTED_PA_COUNTS.values())
        )
        self.assertEqual(
            join_evidence["pitcherDenominator"], sum(EXPECTED_PA_COUNTS.values())
        )
        self.assertIs(join_evidence["inferenceOrFuzzyMatchingUsed"], False)
        self.assertIs(join_evidence["sameSeasonPredictorEligibleObserved"], False)
        self.assertIs(
            join_evidence["plateAppearanceCanonicalIdentityResolvedObserved"],
            False,
        )
        self.assertEqual(
            live["checks"],
            {
                "roleSpecificPriorSets": True,
                "eligibleFromEqualsTargetSeason": True,
                "priorSeasonPlusOneEqualsEligibleFromSeason": True,
                "sameSeasonPredictorEligibilityUniversallyFalse": True,
                "plateAppearanceNamespaceRetrosheetOnly": True,
                "plateAppearanceCanonicalIdentityResolvedUniversallyFalse": True,
            },
        )

        self.assertIs(live["unsafeContext"]["actualHistoricalEvidenceUsed"], False)
        self.assertIs(live["missingBridge"]["isMissing"], True)
        self.assertEqual(
            live["missingBridge"]["requiredArtifact"],
            "PACKAGE_BOUND_RETROSHEET_TO_ASP_CANONICAL_PLAYER_ID_BRIDGE",
        )
        audited_at = datetime.fromisoformat(live["auditedAt"].replace("Z", "+00:00"))
        self.assertIsNotNone(audited_at.tzinfo)

    def test_schema_authority_excludes_leakage_and_timing_risk_fields(self) -> None:
        authorities = self.audit["authorities"]
        pa = authorities["plate_appearance"]
        for field in PA_CONTEXT_FIELDS:
            with self.subTest(family="plate_appearance", field=field):
                self.assertEqual(
                    pa[field],
                    {("FEATURE", "RETROSPECTIVE_ACTUAL_NOT_PREGAME_SAFE")},
                )
                self.assertTrue(_is_excluded(pa[field]))

        for field in (*PA_TARGET_OR_POST_EVENT_FIELDS, *PA_PROVENANCE_FIELDS):
            with self.subTest(family="plate_appearance", field=field):
                self.assertTrue(_is_excluded(pa[field]))

        batting = authorities["player_game_batting"]
        for field in ACTUAL_LINEUP_FIELDS:
            with self.subTest(family="player_game_batting", field=field):
                self.assertTrue(_is_excluded(batting[field]))

        pitching = authorities["player_game_pitching"]
        self.assertEqual(
            pitching["actual_start_flag"], {("TARGET", "POSTGAME_TARGET_ONLY")}
        )
        self.assertTrue(_is_excluded(pitching["actual_start_flag"]))

        weather = authorities["weather"]
        for field in ACTUAL_WEATHER_FIELDS:
            with self.subTest(family="weather", field=field):
                self.assertEqual(
                    weather[field],
                    {("FEATURE", "RETROSPECTIVE_ACTUAL_NOT_PREGAME_SAFE")},
                )
                self.assertTrue(_is_excluded(weather[field]))


if __name__ == "__main__":
    unittest.main()

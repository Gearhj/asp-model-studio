from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import unittest
import uuid

from server.sports_gold.nfl_shadow_exchange import (
    ASP_SPORTS_FORECAST_EXCHANGE_V1,
    derive_sports_forecast_bundle_id,
    derive_sports_game_forecast_id,
    write_nfl_2026_research_shadow_locator,
    write_sports_forecast_bundle,
)
from server.sports_nfl_m1.week2_paper_eligibility import (
    DEFAULT_AUTHORIZATION_SOURCE_PATH,
    build_document,
    canonical_json_bytes,
    publish_week2_successors,
    validate_document,
    validate_forecast,
    verify_package,
)
from server.sports_nfl_m1.prospective_shadow import FINAL_PREGAME_CONSUMER_IMPORT_RESERVE_MINUTES


ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "outputs/four-sport-operational-handoff-20260915-v1/nfl-week-2-readiness.json"


class Week2EligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ledger = json.loads(READINESS.read_bytes())
        cls.summary = next(row for row in ledger["effectiveForecasts"] if row["eventId"] == "2026_02_DET_BUF")
        bundle = json.loads(Path(cls.summary["bundle"]["path"]).read_bytes())
        cls.forecast = next(row for row in bundle["forecasts"] if row["forecastId"] == cls.summary["forecastId"])
        cls.published = "2026-09-15T15:00:00Z"

    def test_exact_forecast_reconciles(self):
        population = validate_forecast(self.forecast, published_utc=self.published)
        self.assertEqual(population["drawCount"], 10_000)
        self.assertAlmostEqual(population["probabilityMass"], 1.0)
        self.assertAlmostEqual(population["tieProbability"], self.forecast["tieProbability"])

    def test_final_publication_reserves_one_full_consumer_interval(self):
        self.assertEqual(FINAL_PREGAME_CONSUMER_IMPORT_RESERVE_MINUTES, 6)
        kickoff = datetime(2026, 9, 18, 0, 15, tzinfo=timezone.utc)
        latest_publication = kickoff.replace(minute=54, hour=23, day=17)
        latest_import = latest_publication.replace(minute=59, hour=23, day=17)
        decision_cutoff = kickoff.replace(minute=0)
        self.assertEqual(latest_publication.isoformat(), "2026-09-17T23:54:00+00:00")
        self.assertLess(latest_import, decision_cutoff)

    def test_exact_document_and_unicode(self):
        document = build_document(
            self.forecast,
            bundle_reference=self.summary["bundle"],
            authorization_reference={"path": "authorization.txt", "sha256": "a" * 64, "bytes": 1},
            published_utc=self.published,
        )
        validate_document(document)
        raw = canonical_json_bytes(document)
        self.assertIn("—".encode("utf-8"), raw)
        self.assertEqual(raw, json.dumps(document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def test_incompatible_forecasts_are_rejected(self):
        mutations = (
            ("week", 3),
            ("season", 2025),
        )
        for key, value in mutations:
            candidate = deepcopy(self.forecast)
            candidate[key] = value
            with self.assertRaises(ValueError):
                validate_forecast(candidate, published_utc=self.published)
        candidate = deepcopy(self.forecast)
        candidate["engine"]["modelBinarySha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_forecast(candidate, published_utc=self.published)
        candidate = deepcopy(self.forecast)
        candidate["simulator"]["simulationCount"] = 9_999
        with self.assertRaises(ValueError):
            validate_forecast(candidate, published_utc=self.published)
        candidate = deepcopy(self.forecast)
        candidate["homeWinProbability"] += 0.01
        with self.assertRaises(ValueError):
            validate_forecast(candidate, published_utc=self.published)

    def test_scope_cannot_expand_to_unseen_forecast(self):
        document = build_document(
            self.forecast,
            bundle_reference=self.summary["bundle"],
            authorization_reference={"path": "authorization.txt", "sha256": "a" * 64, "bytes": 1},
            published_utc=self.published,
        )
        document["summaries"]["authorization"]["scopeOfThisEvidence"].append("UNSEEN")
        with self.assertRaises(ValueError):
            validate_document(document)

    def test_newer_forecast_publishes_exact_successor_then_reuses_without_writes(self):
        forecast = deepcopy(self.forecast)
        forecast["snapshotType"] = "FINAL_PREGAME"
        forecast["snapshotVersion"] = 1
        forecast["forecastCutoffUtc"] = "2026-09-17T23:45:00Z"
        forecast["availableAsOfUtc"] = "2026-09-17T23:50:00Z"
        forecast["forecastId"] = derive_sports_game_forecast_id(forecast)
        bundle = {
            "schemaVersion": ASP_SPORTS_FORECAST_EXCHANGE_V1,
            "bundleId": "PENDING",
            "sport": "NFL",
            "league": "NFL",
            "season": 2026,
            "slateDate": forecast["eventDate"],
            "generatedAtUtc": "2026-09-17T23:51:00Z",
            "status": "RESEARCH_SHADOW",
            "researchShadowOnly": True,
            "modelPromotionAllowed": False,
            "executionAllowed": False,
            "parlaysAllowed": False,
            "forecasts": [forecast],
        }
        bundle["bundleId"] = derive_sports_forecast_bundle_id(bundle)
        root = ROOT / "outputs" / f"nfl-week2-successor-focused-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        try:
            exchange = root / "exchange"
            exchange.mkdir()
            published = write_sports_forecast_bundle(
                exchange,
                bundle,
                now_utc=lambda: datetime(2026, 9, 17, 23, 51, tzinfo=timezone.utc),
            )
            write_nfl_2026_research_shadow_locator(
                exchange,
                current_bundle_sha256s=[published.bundle_sha256],
                historical_bundle_sha256s=[],
                feature_contract_sha256=forecast["engine"]["featureContractSha256"],
                updated_at_utc="2026-09-17T23:51:00Z",
                now_utc=lambda: datetime(2026, 9, 17, 23, 51, tzinfo=timezone.utc),
            )
            first = publish_week2_successors(
                exchange_root=exchange,
                output_root=root / "local",
                authorization_source_path=DEFAULT_AUTHORIZATION_SOURCE_PATH,
                forecast_ids=[forecast["forecastId"]],
                published_utc="2026-09-17T23:52:00Z",
            )
            self.assertEqual(first["supplementsPublished"], 1)
            self.assertEqual(first["supplementsReused"], 0)
            package = exchange / "nfl-labs-supplements/sha256" / first["packages"][0]["supplementAddress"]
            self.assertEqual(verify_package(package)["document"]["binding"]["forecastId"], forecast["forecastId"])
            before = {
                str(path.relative_to(exchange)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in exchange.rglob("*") if path.is_file()
            }
            second = publish_week2_successors(
                exchange_root=exchange,
                output_root=root / "local",
                authorization_source_path=DEFAULT_AUTHORIZATION_SOURCE_PATH,
                forecast_ids=[forecast["forecastId"]],
                published_utc="2026-09-17T23:53:00Z",
            )
            after = {
                str(path.relative_to(exchange)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in exchange.rglob("*") if path.is_file()
            }
            self.assertEqual(second["supplementsPublished"], 0)
            self.assertEqual(second["supplementsReused"], 1)
            self.assertFalse(second["indexUpdated"])
            self.assertEqual(before, after)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()

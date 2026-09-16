"""Focused scope, identity, deadline and physical-byte checks; no forecasts run."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from uuid import uuid4

from server.sports_nfl_m1.paper_research_eligibility import (
    GOVERNANCE, KIND, build_document, canonical_json_bytes, immutable_json,
    validate_evidence, verify_package,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/nfl-paper-research-eligibility-20260914-v1"


class FrozenEligibilityTests(unittest.TestCase):
    def setUp(self):
        readiness = json.loads((ROOT / "outputs/producer-readiness-20260914-v1/nfl-readiness.json").read_bytes())
        diagnostic = json.loads((OUTPUT / "tie-diagnostic.json").read_bytes())
        auth = json.loads((OUTPUT / "authorization-binding.json").read_bytes())
        self.doc = build_document(readiness, diagnostic, auth, published_utc="2026-09-14T17:00:00Z")

    def test_exact_authorized_evidence(self):
        validate_evidence(self.doc)
        self.assertEqual(self.doc["summaries"]["authorization"]["initialPositionCapUsd"], 5)
        self.assertEqual(self.doc["summaries"]["probabilitySemantics"]["threeWayProbabilities"],
                         {"awayWin": .5753, "homeWin": .3817, "tie": .043})

    def test_expanded_authority_and_cap_rejected(self):
        for field in ("executionAllowedInAisp", "wageringAuthority", "modelPromotionAllowed"):
            doc = deepcopy(self.doc)
            doc["governance"][field] = True
            with self.assertRaises(ValueError):
                validate_evidence(doc)
        doc = deepcopy(self.doc)
        doc["summaries"]["authorization"]["positionCapFraction"] = .01
        with self.assertRaises(ValueError):
            validate_evidence(doc)

    def test_other_forecast_model_or_expired_publication_rejected(self):
        for field in ("forecastId", "modelArtifactSha256"):
            doc = deepcopy(self.doc)
            doc["binding"][field] = "different"
            with self.assertRaises(ValueError):
                validate_evidence(doc)
        doc = deepcopy(self.doc)
        doc["publishedUtc"] = "2026-09-15T00:00:00Z"
        with self.assertRaises(ValueError):
            validate_evidence(doc)

    def test_container_bytes_and_reproduction(self):
        raw = canonical_json_bytes(self.doc)
        self.assertEqual(raw, canonical_json_bytes(json.loads(raw)))
        manifest = {"schemaVersion": "AISP_RESEARCH_SUPPLEMENT_MANIFEST_V1",
                    "contractVersion": "AISP_RESEARCH_SUPPLEMENT_V1", "kind": KIND,
                    "supplementId": self.doc["supplementId"], "sport": "NFL", "governance": GOVERNANCE,
                    "artifacts": [{"file": "supplement.json", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}]}
        digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
        manifest["supplementSha256"] = digest
        temporary = ROOT / "tmp" / ("nfl-paper-eligibility-" + uuid4().hex)
        target = temporary / digest
        target.mkdir(parents=True)
        try:
            (target / "manifest.json").write_bytes(canonical_json_bytes(manifest))
            (target / "supplement.json").write_bytes(raw)
            self.assertEqual(verify_package(target), self.doc)
            (target / "supplement.json").write_bytes(raw + b"\n")
            with self.assertRaises(ValueError):
                verify_package(target)
        finally:
            for name in ("supplement.json", "manifest.json"):
                (target / name).unlink(missing_ok=True)
            target.rmdir()
            temporary.rmdir()

    def test_unicode_interoperability_against_consumer_contract(self):
        original = OUTPUT / "publication/391240384408f975febde5c8ac369cd55a814c9d8bd652c4880e5be16aea7c9f/package/supplement.json"
        doc = json.loads(original.read_bytes())
        self.assertEqual(doc["summaries"]["authorization"]["experimentName"],
                         "ASP NFL RESEARCH PAPER BANKROLL \u2014 2026 V1")
        # Independent oracle: the consumer-specified encoder, not the producer
        # helper re-encoding its own output. This fails with the old ASCII writer.
        consumer_bytes = json.dumps(doc, ensure_ascii=False, allow_nan=False,
                                    sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(consumer_bytes), 34047)
        self.assertEqual(hashlib.sha256(consumer_bytes).hexdigest(),
                         "7fac31dc0bec36ded4b363bc5e8b9bc4a4b8311fa5b671ab32f00820686ffa18")
        self.assertEqual(canonical_json_bytes(doc), consumer_bytes)
        temporary = ROOT / "tmp" / ("nfl-paper-unicode-" + uuid4().hex)
        temporary.mkdir(parents=True)
        target = temporary / "supplement.json"
        try:
            immutable_json(target, doc)
            self.assertEqual(target.read_bytes(), consumer_bytes)
            self.assertEqual(json.loads(target.read_bytes()), doc)
            self.assertNotEqual(original.read_bytes(), consumer_bytes)
        finally:
            target.unlink(missing_ok=True)
            temporary.rmdir()


if __name__ == "__main__":
    unittest.main()

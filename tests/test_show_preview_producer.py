"""Focused preview checks. Synthetic documents are never exchange forecasts."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
import uuid

from server.sports_shared import show_preview as p
from server.sports_shared.show_preview_sources import base, CFB_MODEL, NBA_MODEL, nba_source

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "outputs/multisport-show-preview-producer-v1/context/context.json"


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        context = json.loads(CONTEXT.read_bytes())
        pin = context["consumer_validator"]
        cls.validator = staticmethod(p.consumer_validator(pin["path"], pin["sha256"]))

    def setUp(self):
        # Windows sandbox applies unusable ACLs to tempfile's mode0700 dirs.
        # Keep scoped fixtures under a normal inherited-permission directory.
        self.root = ROOT / "outputs/show-preview-focused-tests" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.now = p.utc("2026-09-16T19:15:00Z")
        f = {"schemaVersion": "CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1", "forecastId": "synthetic-only-cfb",
             "baseline": {"configuration": "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1", "drawCount": 0,
                          "expectedAwayPoints": 21., "expectedHomePoints": 28., "ridgeAwayWinProbability": .4,
                          "ridgeHomeWinProbability": .6, "tieProbability": 0.},
             "modelBindings": {"selectedModel": {"physicalSha256": CFB_MODEL}},
             "sourceCutoff": "2026-09-15T19:00:00Z", "createdAt": "2026-09-15T19:01:00Z",
             "game": {"scheduled_at": "2026-09-17T23:30:00Z", "game_id": 123, "away_team": "Away", "home_team": "Home"}}
        path = self.root / "fixture-source.json"
        p.immutable(path, p.canonical(f))
        game = {"canonical_game_id": None, "source_game_ref": "cfbd:123", "slate_date": "2026-09-17",
                "kickoff_utc": "2026-09-17T23:30:00Z", "away": {"abbreviation": "A", "name": "Away"},
                "home": {"abbreviation": "H", "name": "Home"}}
        self.source = base("CFB", f["forecastId"], f["schemaVersion"], "PROSPECTIVE_RESEARCH", p.digest(path.read_bytes()),
            f["sourceCutoff"], f["createdAt"], "2026-09-15T19:02:00Z", "2026-09-15T19:02:00Z",
            [p.physical(path)], {"captured_utc": "2026-09-15T20:00:00Z"}, game,
            {"model_id": "CFB_GEN1_RIDGE", "model_version": "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1", "artifact_sha256": CFB_MODEL},
            {"sha256": "b"*64}, {"identity": "synthetic", "draw_count": 0, "seed": None, "reused": False},
            {"away": 21., "home": 28.}, {"away_win": .4, "home_win": .6, "tie": 0.}, None,
            "Deterministic synthetic contract fixture only.", ["Synthetic Unicode — never a real forecast."])

    def document(self):
        return p.build_preview(self.source, self.now, self.now)

    def test_consumer_encoding_unicode_and_horizon(self):
        doc = self.document()
        result = self.validator(doc, now=self.now)
        self.assertEqual(result.content_sha256, doc["integrity"]["content_sha256"])
        raw = json.dumps({k:v for k,v in doc.items() if k != "integrity"}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        self.assertEqual(p.digest(raw), result.content_sha256)
        doc["horizon"] = "FINAL_PREGAME"
        with self.assertRaises(ValueError): p.validate_document(doc, self.validator, self.now)

    def test_relabelling_or_changing_source_values_rejected(self):
        source = deepcopy(self.source)
        source["expected_score"]["home"] += 1
        with self.assertRaisesRegex(ValueError, "source numerical"): p.build_preview(source, self.now, self.now)
        doc = self.document()
        doc.pop("derivation")
        doc["integrity"]["content_sha256"] = p.digest(p.canonical({k:v for k,v in doc.items() if k != "integrity"}))
        with self.assertRaisesRegex(ValueError, "RELABELLED"): p.validate_document(doc, self.validator, self.now)

    def test_cutoff_deadline_and_utc_midnight(self):
        self.assertEqual(p.clocks("2026-09-17")["publish_by_utc"], "2026-09-16T20:00:00Z")
        self.assertEqual(p.clocks("2026-11-03")["publish_by_utc"], "2026-11-02T21:00:00Z")
        self.assertEqual(p.clocks("2027-03-15")["publish_by_utc"], "2027-03-14T20:00:00Z")
        self.assertEqual(p.utc("2026-09-18T00:15:00Z").astimezone(p.NY).date().isoformat(), "2026-09-17")
        with self.assertRaisesRegex(ValueError, "DEADLINE"): p.build_preview(self.source, self.now, "2026-09-16T20:00:01Z")
        source = deepcopy(self.source)
        source["source_available_utc"] = "2026-09-16T19:16:00Z"
        with self.assertRaises(ValueError): p.build_preview(source, self.now, self.now)
        with self.assertRaises(ValueError): p.utc("2026-09-16T19:15:00")

    def test_identity_status_missing_evidence_and_probability(self):
        for change in (lambda s: s["game"].update(slate_date="2026-09-18"),
                       lambda s: s["probabilities"].update(home_win=.8),
                       lambda s: s["team_evidence"]["away"].update(starter_status="PROJECTED_CONFIRMED"),
                       lambda s: s["team_evidence"]["away"].update(missing_evidence=[])):
            source = deepcopy(self.source)
            change(source)
            with self.assertRaises(ValueError): p.build_preview(source, self.now, self.now)

    def test_atomic_publication_replay_tamper_and_no_resimulation(self):
        original = Path(self.source["files"][0]["path"]).read_bytes()
        first = p.publish([self.source], self.root, self.validator, now_fn=lambda:self.now)
        pointer = Path(first["discovery"]["path"])
        before = pointer.read_bytes()
        second = p.publish([self.source], self.root, self.validator, now_fn=lambda:self.now)
        self.assertEqual(second["results"][0]["disposition"], "REUSED_BYTE_IDENTICAL")
        self.assertEqual(before, pointer.read_bytes())
        self.assertEqual(original, Path(self.source["files"][0]["path"]).read_bytes())
        directory = self.root / p.TREE / first["results"][0]["package_path"]
        self.assertEqual(p.verify_package(directory, self.validator, self.now)["simulation"]["draw_count"], 0)
        file = directory / "forecast.json"
        file.write_bytes(file.read_bytes()+b" ")
        with self.assertRaises(ValueError): p.verify_package(directory, self.validator, self.now)
        self.assertEqual(before, pointer.read_bytes())

    def test_failure_does_not_update_discovery_and_lock_is_exclusive(self):
        def fail(*a, **kw): raise ValueError("consumer refused")
        with self.assertRaises(ValueError): p.publish([self.source], self.root, fail, now_fn=lambda:self.now)
        root = self.root / p.TREE
        self.assertFalse((root/"discovery.json").exists())
        with p.publication_lock(root):
            with self.assertRaises(FileExistsError): p.publish([self.source], self.root, self.validator, now_fn=lambda:self.now)

    def test_mlb_fails_closed_and_no_production_imports(self):
        source = deepcopy(self.source)
        source["sport"] = "MLB"
        with self.assertRaisesRegex(ValueError, "MLB_PREVIEW"): p.build_preview(source, self.now, self.now)
        text = (ROOT/"server/sports_shared/show_preview.py").read_text()
        for forbidden in ("import joblib", "import requests", "import random", "import numpy", "create_engine", "simulate_prospective_game"):
            self.assertNotIn(forbidden, text)

    def test_nba_capability_uses_synthetic_baseline_without_bos_det(self):
        game = {"game_id": "synthetic-nba-1", "away_team_code": "AWY", "home_team_code": "HOM",
                "scheduled_tipoff_utc": "2026-09-17T23:30:00Z"}
        f = {"schema": "NBA_GEN1_JOINT_PROSPECTIVE_FORECAST_V1", "arm": "baseline",
             "configurationIdentity": "NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1", "forecastId": "synthetic-nba",
             "sourceCutoffUtc": "2026-09-15T19:00:00Z", "createdAtUtc": "2026-09-15T19:01:00Z", "game": game,
             "jointSimulation": {"drawCount": 2, "expectedScores": {"awayAWY": 100.5, "homeHOM": 101.5},
                "winnerProbabilities": {"awayAWY": .5, "homeHOM": .5, "tie": 0.},
                "intervals": {"margin": [{"level": .9, "lower": -1, "upper": 3}],
                              "total": [{"level": .9, "lower": 200, "upper": 204}]}},
             "limitations": ["Synthetic no-model fixture; never publish to the real exchange."]}
        for name, value in (("nba.json", f), ("nba-population.json", [[101, 100], [100, 103]]),
                            ("nba-publication.json", {"publishedAtUtc": "2026-09-15T19:02:00Z"})):
            p.immutable(self.root/name, p.canonical(value))
        context = {"captured_utc": "2026-09-15T20:00:00Z", "rows": [
            {"league": "NBA", "starts_at": game["scheduled_tipoff_utc"], "is_home": home,
             "abbreviation": abbr, "canonical_game_id": "synthetic-id"} for home, abbr in ((False,"AWY"),(True,"HOM"))]}
        source = nba_source(p.physical(self.root/"nba.json"), p.physical(self.root/"nba-population.json"),
                            p.physical(self.root/"nba-publication.json"), {"sha256": NBA_MODEL}, {"input_count": 78}, context)
        doc = p.build_preview(source, self.now, self.now)
        p.validate_document(doc, self.validator, self.now)
        self.assertEqual(doc["game"]["source_game_ref"], "synthetic-nba-1")
        self.assertEqual(doc["probabilities"]["tie"], 0)


if __name__ == "__main__":
    unittest.main()
